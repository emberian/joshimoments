use core::fmt;
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};
use std::str::FromStr;
use thiserror::Error;

const MAX_STABLE_STRING_BYTES: usize = 512;

/// A validated, lossless string used at wire boundaries.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct StableString(String);

impl StableString {
    /// Validates and retains a string without normalization.
    ///
    /// # Errors
    ///
    /// Returns [`WireStringError`] when the value is empty, padded, contains control characters,
    /// or exceeds the stable boundary.
    pub fn new(value: impl Into<String>) -> Result<Self, WireStringError> {
        let value = value.into();
        validate_stable_string(&value)?;
        Ok(Self(value))
    }

    /// Returns the exact retained string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Consumes this wrapper and returns the exact retained string.
    #[must_use]
    pub fn into_inner(self) -> String {
        self.0
    }
}

impl fmt::Display for StableString {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl TryFrom<String> for StableString {
    type Error = WireStringError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::new(value)
    }
}

impl TryFrom<&str> for StableString {
    type Error = WireStringError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        Self::new(value)
    }
}

impl<'de> Deserialize<'de> for StableString {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(de::Error::custom)
    }
}

/// Validation failure for a stable string or typed string identity.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum WireStringError {
    /// Empty strings cannot identify a value.
    #[error("stable strings must not be empty")]
    Empty,
    /// Whitespace normalization would make identity ambiguous.
    #[error("stable strings must not have leading or trailing whitespace")]
    SurroundingWhitespace,
    /// Control characters are never accepted in identifiers or discriminators.
    #[error("stable strings must not contain control characters")]
    ControlCharacter,
    /// The value is too large for an identifier/discriminator boundary.
    #[error("stable strings must be at most {MAX_STABLE_STRING_BYTES} UTF-8 bytes")]
    TooLong,
}

pub(crate) fn validate_stable_string(value: &str) -> Result<(), WireStringError> {
    if value.is_empty() {
        return Err(WireStringError::Empty);
    }
    if value.trim() != value {
        return Err(WireStringError::SurroundingWhitespace);
    }
    if value.chars().any(char::is_control) {
        return Err(WireStringError::ControlCharacter);
    }
    if value.len() > MAX_STABLE_STRING_BYTES {
        return Err(WireStringError::TooLong);
    }
    Ok(())
}

/// Parsing failure for a decimal-string wire integer.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum WireIntegerError {
    /// Empty decimal strings are invalid.
    #[error("wire integers must not be empty")]
    Empty,
    /// Only the canonical unsigned decimal representation is accepted.
    #[error("wire integers must use minimal unsigned decimal digits")]
    NonCanonical,
    /// The value does not fit the target integer type.
    #[error("wire integer is out of range")]
    OutOfRange,
}

macro_rules! decimal_wire_integer {
    ($name:ident, $inner:ty) => {
        #[doc = "An exact integer serialized as a canonical decimal JSON string."]
        #[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
        pub struct $name($inner);

        impl $name {
            /// Creates a wire integer from its native value.
            #[must_use]
            pub const fn new(value: $inner) -> Self {
                Self(value)
            }

            /// Returns the native value.
            #[must_use]
            pub const fn get(self) -> $inner {
                self.0
            }

            /// Adds one, returning `None` on overflow.
            #[must_use]
            pub const fn checked_next(self) -> Option<Self> {
                match self.0.checked_add(1) {
                    Some(value) => Some(Self(value)),
                    None => None,
                }
            }
        }

        impl From<$inner> for $name {
            fn from(value: $inner) -> Self {
                Self::new(value)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }

        impl FromStr for $name {
            type Err = WireIntegerError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                if value.is_empty() {
                    return Err(WireIntegerError::Empty);
                }
                if value != "0" && value.starts_with('0')
                    || !value.bytes().all(|byte| byte.is_ascii_digit())
                {
                    return Err(WireIntegerError::NonCanonical);
                }
                value
                    .parse::<$inner>()
                    .map(Self)
                    .map_err(|_| WireIntegerError::OutOfRange)
            }
        }

        impl Serialize for $name {
            fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
            where
                S: Serializer,
            {
                serializer.collect_str(self)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                struct DecimalStringVisitor;

                impl de::Visitor<'_> for DecimalStringVisitor {
                    type Value = $name;

                    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                        formatter.write_str("a canonical unsigned decimal string")
                    }

                    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
                    where
                        E: de::Error,
                    {
                        value.parse().map_err(E::custom)
                    }
                }

                deserializer.deserialize_str(DecimalStringVisitor)
            }
        }
    };
}

decimal_wire_integer!(WireU64, u64);
decimal_wire_integer!(WireU128, u128);

#[cfg(test)]
mod tests {
    use super::{StableString, WireU64, WireU128};

    #[test]
    fn integer_wire_format_is_a_decimal_string() {
        let encoded = serde_json::to_string(&WireU128::new(u128::MAX));
        assert_eq!(
            encoded.ok().as_deref(),
            Some("\"340282366920938463463374607431768211455\"")
        );

        let decoded = serde_json::from_str::<WireU64>("\"18446744073709551615\"");
        assert_eq!(decoded.ok().map(WireU64::get), Some(u64::MAX));
        assert!(serde_json::from_str::<WireU64>("42").is_err());
        assert!(serde_json::from_str::<WireU64>("\"042\"").is_err());
    }

    #[test]
    fn stable_strings_are_not_silently_normalized() {
        assert!(StableString::new(" source ").is_err());
        assert!(StableString::new("").is_err());
        assert_eq!(
            StableString::new("source:a").map(StableString::into_inner),
            Ok("source:a".into())
        );
    }
}
