//! Publication-specific opaque identities.

use core::fmt;

use joshi_domain::{StableString, WireStringError};
use serde::{Deserialize, Serialize};

macro_rules! publication_identity {
    ($name:ident, $doc:literal) => {
        #[doc = $doc]
        #[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(StableString);

        impl $name {
            /// Creates an opaque identity after stable-string validation.
            ///
            /// # Errors
            ///
            /// Rejects empty, padded, controlled-character, or oversized input.
            pub fn new(value: impl Into<String>) -> Result<Self, WireStringError> {
                StableString::new(value).map(Self)
            }

            /// Returns the exact retained identity.
            #[must_use]
            pub fn as_str(&self) -> &str {
                self.0.as_str()
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }
    };
}

publication_identity!(
    ProjectionPublicationId,
    "Identity of one immutable exact-projection publication occurrence."
);
publication_identity!(
    CockpitPublicationId,
    "Identity of one append-only cockpit head naming a scene and projection publication."
);
