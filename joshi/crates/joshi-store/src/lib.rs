//! Durable, single-writer `SQLite` and content-addressed storage for JOSHI evidence.
//!
//! The crate owns persistence mechanics, not source acquisition, financial interpretation, or
//! economic authority. A commit receipt is constructed only after `SQLite` reports a durable commit
//! or an exact idempotent batch is read back.

mod blob;
mod browser_presentation;
mod error;
mod g0;
mod live_observation;
mod migration;
mod model;
mod operational;
mod store;
mod wave5;
mod wave5_status;
mod wave6;
mod wave6_campaign;
mod wave6_input;
mod wave6_market;
mod wave6_operator;
mod wave6_research;

pub use blob::{BlobStore, PreparedBlob, PreparedExport};
pub use browser_presentation::{
    CockpitV2BrowserPresentationCommitReceipt, StoredCockpitV2BrowserPresentation,
};
pub use error::{Result, StoreError};
pub use g0::{
    CockpitV2CommitReceipt, PairingEpochReceipt, PairingJournalReceipt, PairingOccurrenceKind,
    PairingRateBootstrap, PairingRatePolicyV1, PairingRateWindowBootstrap,
    ScientificMemoryCommitReceipt, StoredCockpitV2Head, StoredCockpitV2Preparation,
    StoredCockpitV2Publication, StoredPairingOccurrence, StoredScientificMemoryOccurrence,
    StoredWave5SourceOccurrence, Wave5G0BackupOccurrence, Wave5G0BackupRestoreOccurrence,
    Wave5G0ExportOccurrence, Wave5G0ImportOccurrence, Wave5G0OccurrencePorts,
    Wave5G0StatusOccurrence, Wave5SourceOccurrenceV1,
};
pub use live_observation::{
    DurableSourceObservation, DurableSourceObservations, StoredOperatorCommandV1,
};
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
pub use wave6::{
    StoredWave6ArtifactSchema, StoredWave6FixtureArtifact, StoredWave6FixtureArtifactDag,
    StoredWave6FixtureDecisionLedger, StoredWave6ProgramRegistration, Wave6ArtifactSchemaReceipt,
    Wave6FixtureArtifactDagReceipt, Wave6FixtureArtifactReceipt, Wave6FixtureDecisionLedgerReceipt,
    Wave6ProgramRegistrationReceipt,
};
pub use wave6_campaign::{
    StoredWave6FixtureCampaignBundle, Wave6FixtureCampaignBundleBytes,
    Wave6FixtureCampaignBundleReceipt,
};
pub use wave6_input::{
    StoredWave6StoreInputCensus, Wave6StoreInputCensusReceipt, Wave6StoreInputCensusV1,
};
pub use wave6_market::{StoredWave6MarketAtlasFixture, Wave6MarketAtlasFixtureReceipt};
pub use wave6_operator::{
    StoredWave6OperatorEvidenceInput, Wave6OperatorEvidenceInputReceipt,
    Wave6OperatorEvidenceInputV1,
};
pub use wave6_research::{
    ResearchDispositionAuthorityV1, StoredWave6FixtureResearchDisposition,
    StoredWave6FixtureResearchProposal, StoredWave6ResearchArtifactBinding,
    Wave6FixtureResearchDispositionReceipt, Wave6FixtureResearchProposalReceipt,
};

/// `SQLite` application identifier (`JOSH` in ASCII).
pub const APPLICATION_ID: i32 = 0x4a4f_5348;

/// Lowest upstream `SQLite` version accepted for WAL startup.
pub const MINIMUM_SQLITE_VERSION_NUMBER: i32 = 3_051_003;
