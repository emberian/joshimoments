//! Stable cross-capability contracts for the local JOSHI core.
//!
//! These types deliberately encode identity, clocks, open-world discriminators, and replay views
//! without importing a transport, database, wallet, or execution protocol.

mod clock;
mod identity;
mod variant;
mod view;
mod wire;

pub use clock::{
    AcquisitionClocks, AsOfVector, ChainAsOf, ClockReading, ScopedCursorError, ScopedSourceCursor,
    ScopedSourceCursors, SourceAsOf, SourceAsOfError, SourceClock, UtcTimestamp,
};
pub use identity::{
    AccountId, AcquisitionId, AssertionId, AssetId, BatchDigest, BlobId, ClientSessionId,
    CommandId, CommitSeq, CoverageId, CursorId, EpisodeId, LotId, ObservationId, PoolId,
    PositionId, ProtocolProfileId, QuoteId, RequestFingerprint, SceneId, SourceEventId, SourceId,
    ValueDigest, VenueId, WalletEffectId,
};
pub use variant::{OpenVariant, VariantRecognition};
pub use view::{RetrospectiveView, ViewBundle, WitnessedView};
pub use wire::{StableString, WireIntegerError, WireStringError, WireU64, WireU128};

/// Version of the JSON-visible domain contract.
pub const DOMAIN_CONTRACT_VERSION: &str = "joshi.domain.v1";
