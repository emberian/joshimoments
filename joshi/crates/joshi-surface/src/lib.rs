//! Pure, point-in-time contracts for the Wave 5 daily-use sensorium.
//!
//! This crate intentionally owns no store, provider, UI, credential, wallet, or execution
//! capability. It reduces already admitted observations into a strict surface DTO and records
//! the evidence needed by publication and Glass. In particular, a public-chain alternative is
//! never silently promoted to product parity.

#![forbid(unsafe_code)]

mod error;
mod model;
mod reduce;

pub use error::*;
pub use model::*;
pub use reduce::*;

/// Versioned semantic contract for the S track.
pub const SURFACE_CONTRACT: &str = "joshi.daily_use_surface";
/// Current strict wire schema.
pub const SURFACE_SCHEMA_VERSION: u16 = 1;
/// Read-only authority carried by every reduced artifact.
pub const READ_ONLY_AUTHORITY: &str = "read_only_no_execution";
/// Exact receipt contract required for independent cockpit qualification evidence.
pub const QUALIFICATION_EVIDENCE_CONTRACT: &str = "joshi.surface.evidence_receipt.v1";

// Short aliases keep the stable DTO vocabulary convenient for publication/Glass adapters while
// retaining the explicit V1 names on the wire.
pub type SurfaceProfileV1 = DailyUseSurfaceProfileV1;
pub type DailyUseSurfaceEntryV1 = SurfaceEntryV1;
pub type ProductSurfaceStatus = SurfaceStatus;
pub type ParityStatus = SurfaceStatus;
pub type DeclaredUniverseV1 = DeclaredObservedUniverseV1;
pub type SurfaceProjectionV1 = SurfaceCutV1;
pub type CoverageStatus = FieldState;
pub type HotScopeControlWriteReservationV1 = HotControlWriteReservationV1;

#[cfg(test)]
mod tests;
