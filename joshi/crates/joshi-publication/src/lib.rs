//! Durable-publication contracts for exact JOSHI financial projections.
//!
//! This crate prepares and validates immutable bytes, defines append-only publication and cockpit
//! head DTOs, and orchestrates a caller-supplied durable store port. It owns no database, network,
//! valuation, transaction, wallet, signer, or submission capability.

#![forbid(unsafe_code)]

mod browser_presentation;
mod error;
mod identity;
mod model;
mod port;
mod prepare;
mod selection;
mod v2;

pub use browser_presentation::*;
pub use error::*;
pub use identity::*;
pub use model::*;
pub use port::*;
pub use prepare::*;
pub use selection::*;
pub use v2::*;

/// Immutable projection-publication contract.
pub const PROJECTION_PUBLICATION_CONTRACT: &str = "joshi.projection_publication";
/// Immutable projection checkpoint contract.
pub const PROJECTION_CHECKPOINT_CONTRACT: &str = "joshi.projection_checkpoint";
/// Prepared exact-artifact receipt contract.
pub const PREPARED_ARTIFACT_CONTRACT: &str = "joshi.projection_artifact_prepared";
/// Durable projection-publication store receipt contract.
pub const PROJECTION_PUBLICATION_RECEIPT_CONTRACT: &str =
    "joshi.store.projection_publication_receipt";
/// Append-only cockpit publication/head contract.
pub const COCKPIT_PUBLICATION_CONTRACT: &str = "joshi.cockpit_publication";
/// Durable cockpit-publication store receipt contract.
pub const COCKPIT_PUBLICATION_RECEIPT_CONTRACT: &str = "joshi.store.cockpit_publication_receipt";
/// Typed publication-selection response contract.
pub const PROJECTION_SELECTION_CONTRACT: &str = "joshi.projection_publication_selection";
/// Closed V1 schema shared by publication contracts in this crate.
pub const PUBLICATION_SCHEMA_VERSION: u16 = 1;
pub const COCKPIT_V2_MANIFEST_CONTRACT: &str = "joshi.cockpit.v2.manifest";
pub const COCKPIT_V2_PUBLICATION_CONTRACT: &str = "joshi.cockpit.v2.publication";
pub const COCKPIT_V2_CHECKPOINT_CONTRACT: &str = "joshi.cockpit.v2.checkpoint";
pub const COCKPIT_V2_QUERY_CONTRACT: &str = "joshi.cockpit.v2.query";
/// Store-resolved public source-fact closure consumed to prepare one Cockpit V2 manifest.
///
/// This remains an input contract: it has no durable receipt or publication authority.
pub const COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT: &str =
    "joshi.store.cockpit.v2.resolved_source_facts_input";
pub const COCKPIT_V2_SCHEMA_VERSION: u16 = 2;
/// Browser-authored claim that exact headed Cockpit V2 bytes mounted in one page.
pub const COCKPIT_V2_BROWSER_PRESENTATION_CLAIM_CONTRACT: &str =
    "joshi.cockpit.v2.browser_presentation_claim";
/// Closed schema for the browser presentation claim waist.
pub const COCKPIT_V2_BROWSER_PRESENTATION_SCHEMA_VERSION: u16 = 1;

#[cfg(test)]
mod v2_tests;
#[cfg(test)]
mod vector_tests;
