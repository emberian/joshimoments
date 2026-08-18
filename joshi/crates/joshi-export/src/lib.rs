//! Typed Arrow/Parquet materialization for the frozen analysis snapshot V1 contract.
//!
//! The writer recomputes schema, logical, physical, table, and manifest closure. Returned values
//! have private fields and are the only export capability accepted by `joshi-store`.

mod coverage;
mod error;
mod production;
mod snapshot;
mod specs;

pub use error::{ExportError, Result};
pub use production::{
    CockpitPublicationInputV2, OperationalExportRequestV2, OperationalPublicationV2,
    ProjectionPublicationInputV2, PythonValidatorV2, ValidatedProductionSnapshotV2,
    ValidationReceiptV2, export_operational_snapshot_v2,
};
pub use snapshot::{
    ExportSnapshotReceiptV1, ExportSnapshotStatus, ValidatedExportSnapshotV1,
    ValidatedTableArtifactV1, rewrite_snapshot_v1,
};
