//! Evidence-backed, exact, read-only projection artifacts for the JOSHI glass.
//!
//! The crate adapts independently finalized accounting state and immutable protocol calculations
//! into one strict wire DTO. It owns no database, network, policy, transaction, or signing
//! authority.

#![forbid(unsafe_code)]

mod accounting;
mod artifact;
mod evidence;
mod liquidity;
mod market;
mod metric;
mod wire;

pub use accounting::*;
pub use artifact::*;
pub use evidence::*;
pub use liquidity::*;
pub use market::*;
pub use metric::*;
pub use wire::*;

/// Stable semantic contract for the exact read-side projection.
pub const PROJECTION_CONTRACT: &str = "joshi.read_projection";
/// Current closed wire schema version.
pub const PROJECTION_SCHEMA_VERSION: u16 = 1;
/// Named deterministic calculator contract mounted into the as-of vector.
pub const PROJECTION_VERSION: &str = "joshi.projection.v1";

#[cfg(test)]
mod vector_tests;
