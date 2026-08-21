//! The cold denominator one hot lease is promoted out of.
//!
//! The eligible universe is derived from bytes the catalog already holds, and only from values a
//! provider literally named. A Solana transaction's `meta.preTokenBalances` and
//! `meta.postTokenBalances` entries each carry an explicit `mint` field; those strings, and no
//! others, are the universe. Nothing is inferred from account ordering, instruction layout, or a
//! program's assumed account roles, because none of those are stated by the response.
//!
//! One mint is excluded by name: native wrapped SOL is the quote asset of essentially every
//! Pump-family swap, so it is a property of the venue rather than a subject anyone would lease.
//! The exclusion is recorded in the artifact so a replay sees it.

use std::collections::BTreeMap;

use joshi_domain::{CoverageId, StableString, UtcTimestamp, WireU64};
use joshi_sources::RetainedFrameEnvelope;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};

use crate::{Result, SupervisorError};

/// Stable wire contract of one derived mint universe artifact.
pub const MINT_UNIVERSE_CONTRACT: &str = "joshi.supervisor.census_mint_universe/v1";

/// One retained observation identity paired with its exact retained payload bytes.
pub type RetainedPayload = (String, Vec<u8>);

/// Native wrapped SOL. Excluded from the leasable universe by name, not by heuristic.
pub const WRAPPED_SOL_MINT: &str = "So11111111111111111111111111111111111111112";

/// One provider-named mint and everything the retained bytes say about where it was seen.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MintSighting {
    pub mint: String,
    /// Highest chain slot a retained transaction naming this mint reported.
    pub highest_slot: Option<u64>,
    /// Retained transactions naming this mint.
    pub sightings: u64,
}

/// The exact eligible universe, derived from retained bytes and content-addressed by them.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MintUniverseV1 {
    pub contract: String,
    pub schema_version: u64,
    /// Exact derivation rule, restated in the artifact so a replay needs no external prose.
    pub derivation: String,
    /// Observation identities the universe was derived from, in catalog order.
    pub derived_from_observations: Vec<String>,
    /// Retained payloads that carried at least one provider-named mint.
    pub payloads_with_mints: u64,
    /// Mints excluded by name, with the reason.
    pub excluded: Vec<String>,
    /// The universe, sorted by mint.
    pub mints: Vec<MintSighting>,
}

impl MintUniverseV1 {
    /// Canonical bytes of this artifact.
    ///
    /// # Errors
    ///
    /// Returns an error when the artifact cannot be serialized.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(self)?)
    }

    /// Content address of the exact artifact bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the artifact cannot be serialized.
    pub fn digest(&self) -> Result<String> {
        let mut hasher = Sha256::new();
        hasher.update(self.canonical_bytes()?);
        Ok(format!("sha256:{:x}", hasher.finalize()))
    }

    /// Number of eligible subjects in the universe.
    #[must_use]
    pub fn subject_count(&self) -> u64 {
        u64::try_from(self.mints.len()).unwrap_or(u64::MAX)
    }

    /// The one subject a deterministic rule promotes out of this universe.
    ///
    /// The rule is: highest slot first, then fewest sightings, then lexicographic mint. Highest
    /// slot picks the most recently active subject the retained bytes actually name; fewest
    /// sightings prefers the mint that is specific to that transaction over one shared across
    /// many; the lexicographic tail makes the rule total.
    #[must_use]
    pub fn deterministic_promotion(&self) -> Option<&MintSighting> {
        self.mints.iter().max_by(|left, right| {
            left.highest_slot
                .cmp(&right.highest_slot)
                .then_with(|| right.sightings.cmp(&left.sightings))
                .then_with(|| right.mint.cmp(&left.mint))
        })
    }
}

/// Derive the eligible mint universe from exact retained payloads.
///
/// Each payload must be a retained frame envelope holding one provider response body. A payload
/// that is not JSON, or that names no mint, contributes nothing and is not an error: an absent
/// mint is an absent mint, never an absence claim about the chain.
///
/// # Errors
///
/// Returns an error when a payload is not a retained frame envelope.
pub fn derive_mint_universe(payloads: &[RetainedPayload]) -> Result<MintUniverseV1> {
    let mut sightings: BTreeMap<String, MintSighting> = BTreeMap::new();
    let mut observations = Vec::with_capacity(payloads.len());
    let mut payloads_with_mints = 0_u64;
    for (observation_id, payload) in payloads {
        observations.push(observation_id.clone());
        let envelope: RetainedFrameEnvelope = serde_json::from_slice(payload).map_err(|error| {
            SupervisorError::InvalidValue(format!(
                "retained payload is not a frame envelope: {error}"
            ))
        })?;
        let Ok(body) = serde_json::from_slice::<Value>(&envelope.body) else {
            continue;
        };
        let slot = body.pointer("/result/slot").and_then(Value::as_u64);
        let named = named_mints(&body);
        if named.is_empty() {
            continue;
        }
        payloads_with_mints = payloads_with_mints.saturating_add(1);
        for mint in named {
            let sighting = sightings.entry(mint.clone()).or_insert(MintSighting {
                mint,
                highest_slot: None,
                sightings: 0,
            });
            // One retained transaction counts once per mint it names, however many balance rows
            // that mint appears in.
            sighting.sightings = sighting.sightings.saturating_add(1);
            sighting.highest_slot = match (sighting.highest_slot, slot) {
                (Some(current), Some(candidate)) => Some(current.max(candidate)),
                (current, candidate) => current.or(candidate),
            };
        }
    }
    Ok(MintUniverseV1 {
        contract: MINT_UNIVERSE_CONTRACT.to_owned(),
        schema_version: 1,
        derivation: "mint strings named by result.meta.preTokenBalances[].mint and \
                     result.meta.postTokenBalances[].mint in retained provider responses"
            .to_owned(),
        derived_from_observations: observations,
        payloads_with_mints,
        excluded: vec![format!(
            "{WRAPPED_SOL_MINT}: native wrapped SOL is the quote asset of the venue, not a subject"
        )],
        mints: sightings.into_values().collect(),
    })
}

/// Distinct provider-named mints in one parsed transaction response, excluding wrapped SOL.
fn named_mints(body: &Value) -> Vec<String> {
    let mut mints: Vec<String> = [
        "/result/meta/preTokenBalances",
        "/result/meta/postTokenBalances",
    ]
    .into_iter()
    .filter_map(|pointer| body.pointer(pointer).and_then(Value::as_array))
    .flatten()
    .filter_map(|entry| entry.get("mint").and_then(Value::as_str))
    .filter(|mint| *mint != WRAPPED_SOL_MINT)
    .map(ToOwned::to_owned)
    .collect();
    mints.sort();
    mints.dedup();
    mints
}

/// Identity of the census coverage window one denominator closes over.
///
/// # Errors
///
/// Returns an error when the identity violates the stable wire contract.
pub fn census_coverage_id(namespace: &str) -> Result<CoverageId> {
    Ok(CoverageId::new(format!("census-coverage-{namespace}"))?)
}

/// Exact knowledge cutoff of one census closure.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CensusCutoff {
    pub available_through: UtcTimestamp,
    pub commit_through: WireU64,
}

/// Parse the decimal commit sequence a public store receipt reports.
///
/// # Errors
///
/// Returns an error when the receipt's commit sequence is not a canonical decimal integer.
pub fn commit_seq_of(commit_seq: &str) -> Result<WireU64> {
    commit_seq
        .parse::<u64>()
        .map(WireU64::new)
        .map_err(|_| SupervisorError::InvalidValue("receipt commit sequence is not decimal".into()))
}

/// Build a stable string, mapping the wire failure into a supervisor error.
///
/// # Errors
///
/// Returns an error when the value violates the stable wire contract.
pub fn stable(value: impl Into<String>) -> Result<StableString> {
    Ok(StableString::new(value)?)
}
