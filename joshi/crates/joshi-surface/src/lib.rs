//! Pure, point-in-time contracts for the Wave 5 daily-use sensorium.
//!
//! This crate owns no writer, provider, UI, credential, wallet, or execution capability. It
//! reduces already admitted observations into a strict surface DTO and records the evidence
//! needed by publication and Glass. In particular, a public-chain alternative is never silently
//! promoted to product parity.
//!
//! Under the default `store-readback` feature it additionally owns a **read-only** adapter over
//! the operational catalog: [`readback::derive_surface_cut`] takes a store handle and a durable
//! commit sequence and derives the population, the facts, the gaps and both clocks from committed
//! rows, so a cut no longer depends on a caller projecting its own inputs. Read
//! [`readback`]'s module documentation for the exact list of inputs that still cannot be derived
//! from the catalog schema; that list, not a green test, is what bounds this package's ceiling.

#![forbid(unsafe_code)]

mod error;
mod model;
#[cfg(feature = "store-readback")]
pub mod readback;
mod reduce;

pub use error::*;
pub use model::*;
#[cfg(feature = "store-readback")]
pub use readback::{
    DerivedSurfaceV1, SURFACE_FIELD_ASSERTION_DOMAIN, SURFACE_READBACK_CONTRACT,
    SURFACE_READBACK_SCHEMA_VERSION, SurfaceCatalogReadback, SurfaceDerivationReceiptV1,
    SurfaceOpenGapV1, SurfaceReadbackError, SurfaceSourceBindingV1, UnresolvedSurfaceInput,
    derive_surface_cut, parse_surface_derivation_receipt, surface_event_identity,
    surface_field_semantic_key,
};
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

#[cfg(all(test, feature = "store-readback"))]
mod readback_tests;
