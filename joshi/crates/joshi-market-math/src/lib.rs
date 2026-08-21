//! Exact, read-only market arithmetic bound to immutable protocol observations.
//!
//! This crate produces marks and size-specific quote projections. It has no network, wallet,
//! transaction-building, signing, submission, or policy surface. A quote is not a fill and a mark
//! is not executable liquidation value.

#![forbid(unsafe_code)]

pub mod fee;
pub mod profile;
pub mod pump;
pub mod quote;
pub mod wide;
pub mod would_quote;

/// Stable semantic contract implemented by the current exact quote kernel.
pub const MARKET_MATH_CONTRACT_VERSION: &str = "joshi.market-math.v1";

#[cfg(test)]
mod vector_tests;
