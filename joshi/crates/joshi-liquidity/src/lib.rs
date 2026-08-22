//! Exact, read-only liquidity-position semantics over immutable observations.
//!
//! This crate models inventory and action intent. It cannot build, sign, or submit transactions,
//! and modeled intent does not imply support in a particular interface or deployed program.

#![forbid(unsafe_code)]

pub mod action;
pub mod chunk;
pub mod dlmm_fee;
pub mod pool_depth;
pub mod position;
pub mod q64;
pub mod readout;
pub mod round_trip;

/// Stable semantic contract implemented by the current liquidity kernel.
pub const LIQUIDITY_CONTRACT_VERSION: &str = "joshi.liquidity.v1";

#[cfg(test)]
mod vector_tests;
