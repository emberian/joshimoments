use core::fmt;

use joshi_domain::{StableString, WireStringError};
use serde::{Deserialize, Serialize};

macro_rules! topology_id {
    ($name:ident, $description:literal) => {
        #[doc = $description]
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(StableString);

        impl $name {
            /// Creates a validated opaque identifier without normalization.
            ///
            /// # Errors
            ///
            /// Returns [`WireStringError`] when the identifier is not a stable wire string.
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

topology_id!(
    TransactionId,
    "Identity of one chain transaction under a declared chain namespace."
);
topology_id!(
    TransactionFactId,
    "Identity of one immutable as-observed transaction canonicality/finality version."
);
topology_id!(
    ProgramId,
    "Canonical identity of an observed on-chain program."
);
topology_id!(
    FlowId,
    "Identity of one exact directed asset-transfer occurrence."
);
topology_id!(SwapId, "Identity of one exact decoded swap occurrence.");
topology_id!(
    LiquidityEventId,
    "Identity of one exact liquidity-position event occurrence."
);
topology_id!(
    BundleId,
    "Identity of one ordered same-transaction fact bundle."
);
topology_id!(
    HypothesisId,
    "Identity of one immutable inferred topology-claim version."
);
topology_id!(
    HypothesisSeriesId,
    "Semantic correction line shared by superseding hypothesis versions."
);
topology_id!(
    DerivationId,
    "Identity of one deterministic point-in-time derived row or window."
);
topology_id!(
    SnapshotId,
    "Identity of one immutable topology snapshot request."
);
