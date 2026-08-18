//! Pure compact-census candidate/reference evaluator.
//!
//! This crate performs no provider I/O and cannot execute hydration, decode, or census writes. It
//! compares already retained candidate stream facts with an exact finalized reference and emits a
//! bounded, thresholded disposition.

mod error;
mod evaluate;
mod model;

pub use error::BakeoffError;
pub use evaluate::evaluate;
pub use model::*;

pub const BAKEOFF_CONTRACT: &str = "joshi.census_bakeoff/v1";
pub const BAKEOFF_SCHEMA_VERSION: u64 = 1;

#[cfg(test)]
mod tests;
