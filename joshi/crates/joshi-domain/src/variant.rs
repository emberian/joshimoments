use crate::{StableString, WireStringError};
use serde::{Deserialize, Serialize};

/// Whether this build understands an open-world discriminator.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VariantRecognition {
    /// The discriminator has a typed interpretation in this build.
    Known,
    /// The discriminator is retained but not interpreted by this build.
    Unknown,
}

/// An open-world discriminator that preserves unrecognized source variants.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize, Deserialize)]
pub struct OpenVariant {
    /// Exact source or contract discriminator.
    pub discriminator: StableString,
    /// Interpretation status in the producing build.
    pub recognition: VariantRecognition,
}

impl OpenVariant {
    /// Constructs a discriminator recognized by this build.
    ///
    /// # Errors
    ///
    /// Returns [`WireStringError`] when the discriminator violates the stable string boundary.
    pub fn known(discriminator: impl Into<String>) -> Result<Self, WireStringError> {
        Ok(Self {
            discriminator: StableString::new(discriminator)?,
            recognition: VariantRecognition::Known,
        })
    }

    /// Constructs an unrecognized discriminator while retaining it losslessly.
    ///
    /// # Errors
    ///
    /// Returns [`WireStringError`] when the discriminator violates the stable string boundary.
    pub fn unknown(discriminator: impl Into<String>) -> Result<Self, WireStringError> {
        Ok(Self {
            discriminator: StableString::new(discriminator)?,
            recognition: VariantRecognition::Unknown,
        })
    }

    /// Returns whether typed interpretation is unavailable.
    #[must_use]
    pub const fn is_unknown(&self) -> bool {
        matches!(self.recognition, VariantRecognition::Unknown)
    }
}

#[cfg(test)]
mod tests {
    use super::OpenVariant;

    #[test]
    fn unknown_discriminator_round_trips() {
        let value = OpenVariant::unknown("provider_added_this_yesterday");
        assert!(value.is_ok());
        if let Ok(value) = value {
            let encoded = serde_json::to_string(&value);
            assert!(encoded.is_ok());
            if let Ok(encoded) = encoded {
                let decoded = serde_json::from_str::<OpenVariant>(&encoded);
                assert_eq!(decoded.ok(), Some(value));
            }
        }
    }
}
