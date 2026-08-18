use core::fmt;
use joshi_domain::{StableString, WireStringError};
use serde::{Deserialize, Serialize};

macro_rules! attention_identity {
    ($name:ident, $description:literal) => {
        #[doc = $description]
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(StableString);

        impl $name {
            /// Validates and retains the opaque identifier without normalization.
            ///
            /// # Errors
            ///
            /// Returns [`WireStringError`] when the stable string boundary rejects the value.
            pub fn new(value: impl Into<String>) -> Result<Self, WireStringError> {
                StableString::new(value).map(Self)
            }

            /// Returns the exact retained identifier.
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

attention_identity!(
    AttentionInputId,
    "Occurrence identity of one exact attention-source input."
);
attention_identity!(
    IdentityVersionId,
    "Identity of one bitemporal social-identity assertion version."
);
attention_identity!(
    TerritorySnapshotId,
    "Identity of one point-in-time, revisable territory assertion snapshot."
);
attention_identity!(
    WalletClusterHypothesisId,
    "Identity of one versioned wallet-cluster hypothesis, never a human identity."
);
attention_identity!(
    ClusterContextId,
    "Identity of one adapter-selected cluster context bound to one attention event."
);
attention_identity!(
    AttentionEventId,
    "Identity of one marked attention-forcing event occurrence."
);
attention_identity!(
    KernelEventId,
    "Identity of one immutable response-kernel event row."
);
attention_identity!(
    CohortRowId,
    "Identity of one subject membership in one versioned risk set."
);
attention_identity!(
    CommunityId,
    "Provider-qualified identity of a community or social territory."
);
attention_identity!(
    RevisionId,
    "Provider-qualified identity of one object revision or deletion occurrence."
);
attention_identity!(
    SubjectId,
    "Provider-qualified identity of a social/profile subject, not necessarily a person."
);
