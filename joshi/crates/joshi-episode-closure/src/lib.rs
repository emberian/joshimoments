//! Strict, read-only closure artifacts for one preregistered prospective episode.
//!
//! This leaf crate has no store handle, network client, provider capability, wallet material,
//! transaction builder, signer, submission path, or economic authority. It freezes exact V1
//! evidence contracts; durable admission and receipt production remain integration-owned.

mod error;
mod model;
mod validate;

pub use error::{ClosureError, Result};
pub use model::*;
pub use validate::{
    EpisodePrerequisites, QualifyingChoiceEvidence, ValidatedEpisodeBasis, canonical_bytes,
    content_artifact_reference, decode_interview_disposition, decode_knowledge_closure,
    decode_outcome_at_horizon, decode_session_close,
};

pub const SESSION_CLOSE_CONTRACT: &str = "joshi.episode.session_close";
pub const KNOWLEDGE_CLOSURE_CONTRACT: &str = "joshi.episode.knowledge_closure";
pub const OUTCOME_CONTRACT: &str = "joshi.episode.outcome";
pub const INTERVIEW_CONTRACT: &str = "joshi.episode.interview";
pub const SCHEMA_VERSION: u64 = 1;
pub const AUTHORITY: &str = "read_only_no_execution";
pub const ECONOMIC_CLAIM: &str = "none";
pub const MAX_ARTIFACT_BYTES: usize = 1024 * 1024;
