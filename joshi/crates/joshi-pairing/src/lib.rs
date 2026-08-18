//! Ordinary same-origin one-time-code pairing contracts.
//!
//! This crate owns no listener, route, store, browser API, prospective launch, wallet, or
//! execution authority. Secret code/capability bytes live only in zeroizing memory. Public
//! occurrence metadata never contains, hashes, or formats a secret.

#![forbid(unsafe_code)]
#![allow(clippy::missing_errors_doc, clippy::missing_panics_doc)]

mod error;
mod model;
mod service;

pub use error::*;
pub use model::*;
pub use service::*;

/// Ordinary pairing is deliberately not the prospective launch-bound protocol.
pub const ORDINARY_PAIRING_CONTRACT: &str = "joshi.pairing.ordinary";
pub const PAIRING_SCHEMA_VERSION: u16 = 1;
pub const PAIRING_SESSION_CONTRACT: &str = "joshi.pairing.session";
pub const PAIRING_OCCURRENCE_CONTRACT: &str = "joshi.pairing.occurrence";

#[cfg(test)]
mod tests;
