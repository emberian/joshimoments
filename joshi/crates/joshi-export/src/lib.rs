//! Typed Arrow/Parquet materialization for the frozen analysis snapshot V1 contract.
//!
//! The writer recomputes schema, logical, physical, table, and manifest closure. Returned values
//! have private fields and are the only export capability accepted by `joshi-store`.

mod assertions;
mod census;
mod coverage;
mod error;
mod g0;
mod production;
mod snapshot;
mod specs;

pub use census::{
    CensusGapV1, CensusWindowV1, LANDED_ERROR_FAMILY, LANDED_NO_ERROR_FAMILY, ListingErrorCensusV1,
    listing_error_census_v1,
};
pub use error::{ExportError, Result};
pub use production::{
    CockpitPublicationInputV2, G0ImportArtifactReadbackV1, G0ImportPartReadbackV1,
    OperationalExportRequestV2, OperationalPublicationV2, ProjectionPublicationInputV2,
    PythonValidatorV2, ValidatedProductionSnapshotV2, ValidationReceiptV2,
    export_operational_snapshot_v2, validate_operational_snapshot_v2_directory,
};
pub use snapshot::{
    ExportSnapshotReceiptV1, ExportSnapshotStatus, ValidatedExportSnapshotV1,
    ValidatedTableArtifactV1, rewrite_snapshot_v1,
};
