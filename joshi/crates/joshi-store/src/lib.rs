//! Durable, single-writer `SQLite` and content-addressed storage for JOSHI evidence.
//!
//! The crate owns persistence mechanics, not source acquisition, financial interpretation, or
//! economic authority. A commit receipt is constructed only after `SQLite` reports a durable commit
//! or an exact idempotent batch is read back.

mod blob;
mod error;
mod migration;
mod model;
mod operational;
mod store;
mod wave5;
mod wave5_status;

pub use blob::{BlobStore, PreparedBlob, PreparedExport};
pub use error::{Result, StoreError};
pub use migration::{MigrationReport, RuntimeStatus};
pub use model::{
    AdmittedCounts, BackupManifest, DurableReceipt, EffectiveAssertion, GapOutcome,
    IdempotencyStatus, JustifiedCursor, ObservationStorage, OperatorCaptureMetadata,
    ProjectionRegistration, SceneMode, SceneSourceMode, SourceRegistration, StoreConfig,
    StoreIngestBatch, StoreMode, StoredScene, VerificationReport, VerifyDepth,
};
pub use operational::{
    AnalysisArtifactCommitReceipt, ArtifactProtectionClass, CockpitPublicationCapability,
    EpisodeProtocolCapability, OperationalCommitContext, OperationalCommitReceipt,
    ProductionExportCommitReceipt, ProjectionPublicationCapability, SourceFactArtifactCapability,
    SourceFactFamily, StoredAnalysisArtifactPart, StoredEpisodeProtocol,
};
pub use store::SqliteStore;
pub use wave5::{
    StoredWave5OperationalRecord, StoredWave5RestrictedArtifact, StoredWave5RunRegistration,
    StoredWave5SpoolCatalogBinding, Wave5CommitContext, Wave5CommitReceipt,
    Wave5ExportValidationBindingV1, Wave5OperationalRecordKind, Wave5OperationalRecordV1,
    Wave5OperationalState, Wave5RestrictedArtifactRegistrationV1, Wave5RunRegistrationByteBundle,
    Wave5SpoolCatalogBindingV1,
};

/// `SQLite` application identifier (`JOSH` in ASCII).
pub const APPLICATION_ID: i32 = 0x4a4f_5348;

/// Lowest upstream `SQLite` version accepted for WAL startup.
pub const MINIMUM_SQLITE_VERSION_NUMBER: i32 = 3_051_003;
