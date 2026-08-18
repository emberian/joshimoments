use core::fmt;
use joshi_domain::{StableString, WireStringError};
use serde::{Deserialize, Deserializer, Serialize, Serializer, de};
use std::str::FromStr;
use thiserror::Error;

/// An exact JSON-number lexeme carried as a JSON string without numeric coercion.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct JsonNumberLexeme(StableString);

impl JsonNumberLexeme {
    /// Validates the complete JSON-number grammar and retains the original spelling.
    ///
    /// # Errors
    ///
    /// Returns an error for a non-number or unstable string.
    pub fn new(value: impl Into<String>) -> Result<Self, NumberLexemeError> {
        let value = value.into();
        validate_json_number(&value)?;
        StableString::new(value)
            .map(Self)
            .map_err(NumberLexemeError::Wire)
    }

    /// Returns the exact retained lexeme. No normalization is performed.
    #[must_use]
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

impl<'de> Deserialize<'de> for JsonNumberLexeme {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(de::Error::custom)
    }
}

/// Invalid exact JSON-number spelling.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum NumberLexemeError {
    /// The string boundary rejected the value.
    #[error(transparent)]
    Wire(#[from] WireStringError),
    /// The complete JSON-number grammar did not match.
    #[error("value is not an exact JSON-number lexeme")]
    Grammar,
}

fn validate_json_number(value: &str) -> Result<(), NumberLexemeError> {
    let bytes = value.as_bytes();
    let mut index = 0;
    if bytes.first() == Some(&b'-') {
        index += 1;
    }
    match bytes.get(index) {
        Some(b'0') => index += 1,
        Some(b'1'..=b'9') => {
            index += 1;
            while bytes.get(index).is_some_and(u8::is_ascii_digit) {
                index += 1;
            }
        }
        _ => return Err(NumberLexemeError::Grammar),
    }
    if bytes.get(index) == Some(&b'.') {
        index += 1;
        let start = index;
        while bytes.get(index).is_some_and(u8::is_ascii_digit) {
            index += 1;
        }
        if index == start {
            return Err(NumberLexemeError::Grammar);
        }
    }
    if matches!(bytes.get(index), Some(b'e' | b'E')) {
        index += 1;
        if matches!(bytes.get(index), Some(b'+' | b'-')) {
            index += 1;
        }
        let start = index;
        while bytes.get(index).is_some_and(u8::is_ascii_digit) {
            index += 1;
        }
        if index == start {
            return Err(NumberLexemeError::Grammar);
        }
    }
    if index == bytes.len() {
        Ok(())
    } else {
        Err(NumberLexemeError::Grammar)
    }
}

/// An exact signed 64-bit integer serialized as a canonical decimal JSON string.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SignedWireI64(i64);

impl SignedWireI64 {
    /// Creates a signed wire integer.
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    /// Returns the native value.
    #[must_use]
    pub const fn get(self) -> i64 {
        self.0
    }
}

impl fmt::Display for SignedWireI64 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for SignedWireI64 {
    type Err = SignedWireIntegerError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let parsed = value
            .parse::<i64>()
            .map_err(|_| SignedWireIntegerError::INVALID)?;
        if parsed.to_string() != value {
            return Err(SignedWireIntegerError::INVALID);
        }
        Ok(Self(parsed))
    }
}

impl Serialize for SignedWireI64 {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for SignedWireI64 {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        value.parse().map_err(de::Error::custom)
    }
}

/// Invalid canonical signed wire integer.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("signed wire integer must use the canonical i64 decimal representation")]
pub struct SignedWireIntegerError {
    _private: (),
}

impl SignedWireIntegerError {
    const INVALID: Self = Self { _private: () };
}

#[cfg(test)]
mod tests {
    use super::{JsonNumberLexeme, SignedWireI64};

    #[test]
    fn number_lexemes_are_lossless_and_strict() {
        for value in ["0", "-0", "1.2300e-7", "9007199254740993", "1E+999"] {
            assert!(JsonNumberLexeme::new(value).is_ok(), "{value}");
        }
        for value in ["", "+1", "01", "1.", ".1", "NaN", "1e", "1 2"] {
            assert!(JsonNumberLexeme::new(value).is_err(), "{value}");
        }
    }

    #[test]
    fn signed_wire_integer_is_canonical_string() {
        assert_eq!(
            serde_json::to_string(&SignedWireI64::new(-7)).unwrap(),
            "\"-7\""
        );
        assert!(serde_json::from_str::<SignedWireI64>("\"-0\"").is_err());
        assert!(serde_json::from_str::<SignedWireI64>("7").is_err());
    }
}
