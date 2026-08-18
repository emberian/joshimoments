use crate::{WireStringError, WireU64, wire::validate_stable_string};
use core::fmt;
use serde::{Deserialize, Deserializer, Serialize, de};

macro_rules! string_identity {
    ($name:ident, $description:literal) => {
        #[doc = $description]
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Validates and retains the opaque identity without normalization.
            ///
            /// # Errors
            ///
            /// Returns [`WireStringError`] when the identity is empty, padded, contains control
            /// characters, or exceeds the stable boundary.
            pub fn new(value: impl Into<String>) -> Result<Self, WireStringError> {
                let value = value.into();
                validate_stable_string(&value)?;
                Ok(Self(value))
            }

            /// Returns the exact retained identity.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl TryFrom<String> for $name {
            type Error = WireStringError;

            fn try_from(value: String) -> Result<Self, Self::Error> {
                Self::new(value)
            }
        }

        impl TryFrom<&str> for $name {
            type Error = WireStringError;

            fn try_from(value: &str) -> Result<Self, Self::Error> {
                Self::new(value)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                let value = String::deserialize(deserializer)?;
                Self::new(value).map_err(de::Error::custom)
            }
        }
    };
}

string_identity!(
    AcquisitionId,
    "Identity of one request, frame, poll, or fixture acquisition."
);
string_identity!(
    ObservationId,
    "Identity of one retained observation occurrence; never a content hash."
);
string_identity!(
    SourceEventId,
    "Identity of an alleged provider or chain event in a typed namespace."
);
string_identity!(BlobId, "Content identity of exact retained source bytes.");
string_identity!(
    AssertionId,
    "Identity of one versioned claim derived from evidence."
);
string_identity!(SourceId, "Stable identity of an evidence source contract.");
string_identity!(CoverageId, "Identity of a coverage window or gap record.");
string_identity!(SceneId, "Identity of an immutable operator-visible scene.");
string_identity!(ClientSessionId, "Identity of one UI client session.");
string_identity!(CommandId, "Identity of one semantic operator command.");
string_identity!(
    CursorId,
    "Identity of one evidence-backed source cursor advancement."
);
string_identity!(
    BatchDigest,
    "Algorithm-qualified digest of one canonical durable-ingest batch."
);
string_identity!(
    RequestFingerprint,
    "Algorithm-qualified digest of one redacted logical source request."
);
string_identity!(
    ValueDigest,
    "Algorithm-qualified digest of one canonical assertion value."
);
string_identity!(
    AssetId,
    "Canonical identity of an asset under a named resolver contract."
);
string_identity!(
    AccountId,
    "Opaque identity of an observed account or wallet."
);
string_identity!(
    EpisodeId,
    "Identity of one immutable position/exposure episode."
);
string_identity!(
    LotId,
    "Identity of one inventory lot within accounting projections."
);
string_identity!(
    WalletEffectId,
    "Identity of one observed or reconciled economic wallet effect."
);
string_identity!(VenueId, "Identity of one market venue contract.");
string_identity!(PoolId, "Identity of one venue-native liquidity pool.");
string_identity!(
    PositionId,
    "Identity of one venue-native or reconciled liquidity position."
);
string_identity!(
    QuoteId,
    "Identity of one immutable executable or indicative quote occurrence."
);
string_identity!(
    ProtocolProfileId,
    "Identity of one versioned protocol-behavior profile."
);

/// Local durable knowledge order, serialized as a decimal string.
#[derive(
    Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize,
)]
#[serde(transparent)]
pub struct CommitSeq(WireU64);

impl CommitSeq {
    /// Initial state before any accepted evidence record.
    pub const ZERO: Self = Self(WireU64::new(0));

    /// Creates a sequence value.
    #[must_use]
    pub const fn new(value: u64) -> Self {
        Self(WireU64::new(value))
    }

    /// Returns the native value for local comparison and storage adapters.
    #[must_use]
    pub const fn get(self) -> u64 {
        self.0.get()
    }

    /// Advances the sequence, returning `None` on overflow.
    #[must_use]
    pub const fn checked_next(self) -> Option<Self> {
        match self.0.checked_next() {
            Some(value) => Some(Self(value)),
            None => None,
        }
    }
}

impl fmt::Display for CommitSeq {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[cfg(test)]
mod tests {
    use super::{CommitSeq, ObservationId};

    #[test]
    fn identities_validate_during_deserialization() {
        assert!(serde_json::from_str::<ObservationId>("\"\"").is_err());
        assert_eq!(
            serde_json::from_str::<ObservationId>("\"obs-001\"")
                .ok()
                .map(|id| id.to_string()),
            Some("obs-001".into())
        );
    }

    #[test]
    fn commit_sequence_is_not_a_json_number() {
        let value = CommitSeq::new(9);
        assert_eq!(serde_json::to_string(&value).ok().as_deref(), Some("\"9\""));
        assert!(serde_json::from_str::<CommitSeq>("9").is_err());
    }
}
