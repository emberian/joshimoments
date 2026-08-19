//! The bounded Wave 5 C1 public-Solana read path.
//!
//! Every module here belongs to one deliberately narrow authority chain: a store-claimed, journal-
//! bound activation admits exactly one credential-free public request for exactly one signature
//! page, retains its exact response bytes as an opaque raw observation, and stops. Nothing in this
//! module tree may become a general provider client, a reusable executor, a cursor, a coverage
//! window, an absence result, or a finality fact.
//!
//! The ceiling for every artifact produced here is [`crate::AUTHORITY_CEILING`].

pub mod evidence;
pub mod physical_size;
pub mod runtime;
// The transport is the only request-capable value in the crate, so it is deliberately NOT part of
// the published surface. `C1Transport::open` takes no admission and no reservation, so a public
// path to it would let any downstream crate mint an unlimited number of request-capable clients
// aimed at the compiled-in endpoint, bypassing the activation, the journal binding, the budget
// permit and the one-read cap entirely. `c1::runtime` is the only module that may reach it.
pub(crate) mod transport;

/// Durable contract version for every C1 journal, report, and policy artifact.
pub const C1_CONTRACT_VERSION: &str = "joshi.supervisor.c1.v1";

/// The single admitted execution disposition. It never widens.
pub const C1_EXECUTION_DISPOSITION: &str = "validation_only_no_provider_io";

/// Stable supervisor source key for the one admitted C1 source.
pub const C1_SOURCE_KEY: &str = "solana.public.mainnet";

/// Stable supervisor operation key for the one admitted C1 method.
pub const C1_OPERATION_KEY: &str = "get_signatures_for_address";
