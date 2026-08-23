//! Exact, no-I/O accounting projections over finalized wallet observations.
//!
//! Landed wallet effects are the inventory authority. Lot basis and episode attribution are
//! separate projections: neither can rewrite observed balances, and neither claims that a
//! particular lot-selection policy is universally meaningful.
//!
//! Identity and wire values come from `joshi-domain`; this crate does not mint a competing set of
//! cross-capability identifiers.

#![forbid(unsafe_code)]

pub mod accounting;
pub mod amount;
pub mod basis;
pub mod effect;
pub mod episode;
pub mod lots;
pub mod model;
pub mod portfolio;

/// Stable semantic contract implemented by the current pure projector.
pub const ACCOUNTING_CONTRACT_VERSION: &str = "joshi.accounting.v1";

#[cfg(test)]
mod vector_tests;
