//! Private store-readback adapter: a surface derived from committed catalog rows.
//!
//! Everything in the rest of this crate is pure: a caller hands in a universe, a set of
//! observations and a cutoff, and the reducer closes them. That is exactly the ceiling the Wave 5
//! integration review recorded against this package -- *inputs are caller projections*. This
//! module removes the caller from the input side. It takes a read-only handle on the operational
//! `SQLite` catalog plus a durable commit sequence, and derives the population, the per-cell
//! facts, the open gaps and both clocks from rows that a real single-writer store committed.
//!
//! # What this module is allowed to read
//!
//! Only committed evidence: `ingest_commit`, `source`, `observation`, `source_event`,
//! `observation_source_event`, `assertion`, `coverage_window`, `coverage_gap`,
//! `coverage_gap_recovery` and their lossless contract sidecars. The connection is opened
//! read-only; this crate still owns no writer, provider, credential, wallet or execution
//! capability.
//!
//! # What is derived, and from which rows
//!
//! * **Cutoff clock** -- `ingest_commit.committed_wall_us` of the requested commit sequence. A
//!   caller cannot supply the wall time of its own cut, and a catalog whose commit clock is not
//!   monotone in commit order is refused rather than silently truncated.
//! * **Population** -- the union, over the catalog sources bound to the profile, of every subject
//!   declared by a `coverage_window` opened at or before the cutoff and every subject named by a
//!   `source_event` that a committed observation `contains` or `revision`s. Order, count and the
//!   eligible digest are recomputed here; none of the three is accepted from a caller.
//! * **Facts** -- the latest committed observation per subject at the cutoff supplies the row
//!   identity, its content digest (`blob.blob_id`, the sha256 of the exact provider bytes) and
//!   both clocks. Per-field coverage comes from effective, unsuperseded assertions under the
//!   canonical [`surface_field_semantic_key`].
//! * **Gaps** -- `coverage_gap` rows detected at or before the cutoff with no terminal
//!   `coverage_gap_recovery` at or before the cutoff. Each one carries the exact window the
//!   producer authored, read losslessly from `coverage_gap_contract`, including the boundary
//!   kinds that are not wall clocks and the absent upper boundary of a gap that is still open.
//! * **Observation census** -- the number of observations committed at or before the cutoff for
//!   the bound sources, and how many of them name no subject at all. Without those two counts an
//!   empty population is indistinguishable from an empty catalog, which is exactly the absence
//!   claim this project refuses to make.
//! * **Stale age** -- recomputed as `cutoff - observed_at` against the profile's approved cadence
//!   bound. It is never read from an input.
//!
//! # What is NOT derived (read this before quoting a ceiling)
//!
//! [`UnresolvedSurfaceInput`] is a closed enum of the inputs this adapter cannot resolve from
//! catalog schema V23, and every derivation carries the set it hit. They are not warnings to be
//! filtered out; they are the exact reason a derived cut is still not a verified cut:
//!
//! * Hot-scope lease receipts have no table at all. The whole intent/desired/reservation/applied
//!   lifecycle is package-local DTO validation and stays that way.
//! * Ember-use qualification sessions have no table; [`crate::qualify_cockpit`] remains fixed at
//!   `UnverifiedSemantic`.
//! * World eligibility is not knowable from a catalog. The derived universe is exactly the subject
//!   set the catalog knows at the cutoff -- declared coverage scope union observed subjects -- and
//!   it is therefore declared `sample_only` and **not** `closed`. A list a subject can join by
//!   being observed is not a denominator, so `eligibleCount` is not the bottom of a coverage
//!   ratio. Every declared subject that carried no observation is still named as an explicit
//!   omission, so the difference between *declared and unobserved* and *observed and undeclared*
//!   survives the open universe rather than depending on it.
//! * Gap cells for a subject with no observation row cannot be expressed: the cut carries field
//!   state per observation, and inventing an event identity to hang a gap on would be exactly the
//!   caller projection this module exists to remove. Those gaps are carried explicitly on the
//!   receipt instead, and the derivation records
//!   [`UnresolvedSurfaceInput::GapCellsForUnobservedSubjects`].

use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    time::Duration,
};

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    DailyUseSurfaceProfileV1, DeclaredObservedUniverseV1, FieldState, READ_ONLY_AUTHORITY,
    SurfaceCutV1, SurfaceEntryV1, SurfaceError, SurfaceMembership, SurfaceObservationV1,
    SurfaceReducer, SurfaceStatus,
};

/// Contract discriminator for the derivation receipt emitted beside a derived cut.
pub const SURFACE_READBACK_CONTRACT: &str = "joshi.surface.store_readback.v1";
/// Wire schema version of [`SurfaceDerivationReceiptV1`].
pub const SURFACE_READBACK_SCHEMA_VERSION: u16 = 1;
/// Domain tag of the canonical per-cell assertion semantic key.
pub const SURFACE_FIELD_ASSERTION_DOMAIN: &str = "joshi.surface.field.v1";

/// Canonical semantic key under which a producer must commit a per-cell coverage assertion for
/// this adapter to read it back.
///
/// The key is a canonical JSON array rather than a delimited string so that a subject, surface or
/// field containing punctuation can never collide with another cell.
#[must_use]
pub fn surface_field_semantic_key(surface_id: &str, subject: &str, field: &str) -> String {
    // A four-element string array always encodes; the fallible path cannot be reached.
    serde_json::to_string(&[SURFACE_FIELD_ASSERTION_DOMAIN, surface_id, subject, field])
        .unwrap_or_default()
}

/// Canonical event identity for one derived cut row.
///
/// A cut row is one surface's view of one subject, so neither the observation identity nor the
/// surface/observation pair identifies it. One committed observation satisfies cells on more than
/// one profile surface, and it also names more than one subject whenever the provider bytes it
/// retained mention several -- a single Solana transaction touches every mint in its token
/// balances, and the first real Helius census committed exactly that shape. The triple is a
/// canonical JSON array of three identities that all exist -- the approved surface entry, the
/// subject's own natural key, and the exact committed observation. Nothing is synthesized.
#[must_use]
pub fn surface_event_identity(surface_id: &str, subject: &str, observation_id: &str) -> String {
    serde_json::to_string(&[surface_id, subject, observation_id]).unwrap_or_default()
}

/// A named input this adapter could not derive from the catalog.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UnresolvedSurfaceInput {
    /// No hot-scope intent, desired, control-reservation, applied or acquisition-reservation
    /// table exists. Lease receipts remain package-local DTOs.
    HotLeaseReceipts,
    /// No Ember-use session, acknowledgment or qualification-evidence table exists.
    QualificationSessions,
    /// The catalog cannot witness that the world holds no further eligible subject. The derived
    /// universe is bounded by the catalog and is declared `sample_only`, never `closed`.
    WorldEligibility,
    /// A profile surface's declared source matched no registered catalog source, so every cell of
    /// that surface is unknown for structural rather than evidential reasons.
    SurfaceSourceNotRegistered,
    /// No effective per-cell assertion exists under [`surface_field_semantic_key`] at the cutoff,
    /// so no cell can be positively covered by evidence.
    FieldAssertionsAbsent,
    /// The profile's declared render ordering is not one this adapter can derive from durable
    /// knowledge order; rows fall back to ascending commit order.
    RenderOrderingPolicy,
    /// The profile's declared cadence is not a duration, so no staleness bound exists for that
    /// surface and a fact can never be recomputed as stale.
    CadenceStalenessBound,
    /// A subject carries an open gap but no observation row, so its cells cannot carry
    /// [`FieldState::Gap`]. Those gaps are on the receipt instead.
    GapCellsForUnobservedSubjects,
    /// A subject was observed with no coverage window declaring it in scope, so no coverage level
    /// exists to resolve its product membership from. The row is rendered under
    /// [`SurfaceMembership::ObservedUndeclared`]: it was seen, and it was never in a denominator.
    UndeclaredObservedSubject,
    /// A subject's coverage level has no product membership in the S0 surface vocabulary, so it
    /// enters the denominator only.
    CoverageLevelMembership,
    /// Observations are committed at the cutoff whose source events name no subject, so their
    /// content cannot enter the population at all. The rows exist; the surface cannot see them.
    SubjectsForCommittedObservations,
}

impl UnresolvedSurfaceInput {
    /// Exact stable name of this input, for a rendered surface that must say it out loud.
    ///
    /// This is spelled out rather than derived from the serde attribute so that a rendered body
    /// and the wire cannot drift apart silently.
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::HotLeaseReceipts => "hot_lease_receipts",
            Self::QualificationSessions => "qualification_sessions",
            Self::WorldEligibility => "world_eligibility",
            Self::SurfaceSourceNotRegistered => "surface_source_not_registered",
            Self::FieldAssertionsAbsent => "field_assertions_absent",
            Self::RenderOrderingPolicy => "render_ordering_policy",
            Self::CadenceStalenessBound => "cadence_staleness_bound",
            Self::GapCellsForUnobservedSubjects => "gap_cells_for_unobserved_subjects",
            Self::UndeclaredObservedSubject => "undeclared_observed_subject",
            Self::CoverageLevelMembership => "coverage_level_membership",
            Self::SubjectsForCommittedObservations => "subjects_for_committed_observations",
        }
    }
}

/// Resolution of one profile surface's declared source against the catalog.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceSourceBindingV1 {
    /// Surface entry whose source this row resolves.
    pub surface_id: StableString,
    /// Exact `source` string the approved profile declares.
    pub declared_source: StableString,
    /// Registered catalog `source.source_id`, when the declared string matched exactly one.
    pub catalog_source_id: Option<StableString>,
}

/// Exact boundary of a gap's affected window, as the producer authored it.
///
/// A gap boundary is not always a wall clock. A provider may only be able to say "from this
/// cursor", or that it had no usable boundary at all, and the catalog retains that distinction in
/// `coverage_gap_contract`. This mirror keeps it rather than projecting every boundary onto a
/// timestamp no source ever sent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "clock", rename_all = "snake_case", deny_unknown_fields)]
pub enum SurfaceGapBoundaryV1 {
    /// Local wall-clock boundary.
    Wall {
        /// Exact retained instant.
        value: UtcTimestamp,
    },
    /// Durable knowledge-order boundary.
    Commit {
        /// Exact retained commit sequence.
        value: WireU64,
    },
    /// Source-native opaque cursor boundary.
    SourceCursor {
        /// Exact retained cursor.
        value: StableString,
    },
    /// The source explicitly did not provide a usable boundary.
    Unknown {
        /// Exact retained reason discriminator.
        reason: StableString,
    },
    /// The stored boundary is not a shape this schema version recognizes. It is named, and its
    /// exact stored encoding is retained, rather than being projected onto a clock.
    Unrecognized {
        /// Exact stored boundary JSON.
        stored: StableString,
    },
}

/// One coverage gap that is open at the cutoff.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceOpenGapV1 {
    /// Durable gap occurrence identity.
    pub gap_id: StableString,
    /// Catalog source whose scope the gap affects.
    pub catalog_source_id: StableString,
    /// Affected subject; absent for a source-wide gap.
    pub subject: Option<StableString>,
    /// Exact lower boundary of the affected window, as the producer authored it.
    pub window_lower: SurfaceGapBoundaryV1,
    /// Exact upper boundary of the affected window. `None` is the producer's own open end: the
    /// gap is not bounded above by anything the source said.
    pub window_upper: Option<SurfaceGapBoundaryV1>,
    /// Knowledge time at which the gap became durable. This is the commit clock, not the window.
    pub since: UtcTimestamp,
    /// Stored severity.
    pub severity: StableString,
    /// Stored cause code.
    pub cause: StableString,
    /// Whether every eligible subject this gap covers carries it as a derived field state. A
    /// gap over a subject with no observation row cannot be expressed in the cut at all, and a
    /// source-wide gap is only expressed for the subjects that do have one.
    pub expressed_in_cut: bool,
}

/// Exact record of how a cut was derived, what it counted, and what it could not resolve.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SurfaceDerivationReceiptV1 {
    /// Contract discriminator; always [`SURFACE_READBACK_CONTRACT`].
    pub contract: StableString,
    /// Wire schema version.
    pub schema_version: u16,
    /// Highest applied catalog migration at read time.
    pub catalog_schema_version: WireU64,
    /// Durable knowledge order the cut was taken at.
    pub cutoff_commit_seq: WireU64,
    /// Wall time of that exact commit, read from the catalog.
    pub cutoff: UtcTimestamp,
    /// Approved profile the cut closes against.
    pub profile_digest: ValueDigest,
    /// Source resolution per surface entry.
    pub bindings: Vec<SurfaceSourceBindingV1>,
    /// Subjects a coverage window declared in scope at the cutoff.
    pub declared_subjects: WireU64,
    /// Subjects a committed observation named at the cutoff.
    pub observed_subjects: WireU64,
    /// Observations committed at or before the cutoff for the bound catalog sources.
    pub committed_observations: WireU64,
    /// How many of those observations name no subject through a `contains` or `revision` source
    /// event. They are durable evidence the surface cannot see, and an empty population with a
    /// nonzero count here is a gap in the adapter above, not an empty market.
    pub observations_without_subject: WireU64,
    /// Size of the derived eligible universe.
    pub eligible_count: WireU64,
    /// Observation rows promoted to surface facts.
    pub fact_rows: WireU64,
    /// Effective per-cell assertions read at the cutoff.
    pub field_assertion_rows: WireU64,
    /// Gaps open at the cutoff.
    pub open_gaps: Vec<SurfaceOpenGapV1>,
    /// Inputs this adapter could not derive.
    pub unresolved: BTreeSet<UnresolvedSurfaceInput>,
    /// Read-only authority carried by every reduced artifact.
    pub authority: StableString,
    /// Exact identity digest over the material above.
    pub derivation_digest: ValueDigest,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ReceiptMaterial<'a> {
    contract: &'a StableString,
    schema_version: u16,
    catalog_schema_version: WireU64,
    cutoff_commit_seq: WireU64,
    cutoff: &'a UtcTimestamp,
    profile_digest: &'a ValueDigest,
    bindings: &'a [SurfaceSourceBindingV1],
    declared_subjects: WireU64,
    observed_subjects: WireU64,
    committed_observations: WireU64,
    observations_without_subject: WireU64,
    eligible_count: WireU64,
    fact_rows: WireU64,
    field_assertion_rows: WireU64,
    open_gaps: &'a [SurfaceOpenGapV1],
    unresolved: &'a BTreeSet<UnresolvedSurfaceInput>,
    authority: &'a StableString,
}

impl SurfaceDerivationReceiptV1 {
    /// Recompute the receipt's exact identity digest.
    ///
    /// # Errors
    ///
    /// Returns an error if the material cannot be encoded or digested.
    pub fn computed_digest(&self) -> Result<ValueDigest, SurfaceError> {
        let bytes = serde_json::to_vec(&ReceiptMaterial {
            contract: &self.contract,
            schema_version: self.schema_version,
            catalog_schema_version: self.catalog_schema_version,
            cutoff_commit_seq: self.cutoff_commit_seq,
            cutoff: &self.cutoff,
            profile_digest: &self.profile_digest,
            bindings: &self.bindings,
            declared_subjects: self.declared_subjects,
            observed_subjects: self.observed_subjects,
            committed_observations: self.committed_observations,
            observations_without_subject: self.observations_without_subject,
            eligible_count: self.eligible_count,
            fact_rows: self.fact_rows,
            field_assertion_rows: self.field_assertion_rows,
            open_gaps: &self.open_gaps,
            unresolved: &self.unresolved,
            authority: &self.authority,
        })?;
        digest(&bytes)
    }

    /// Validate the receipt contract and its self-declared exact digest.
    ///
    /// # Errors
    ///
    /// Returns [`SurfaceError::Contract`] for a wrong contract, schema or authority, and
    /// [`SurfaceError::DigestMismatch`] when the declared digest is not the computed one.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        if self.contract.as_str() != SURFACE_READBACK_CONTRACT
            || self.schema_version != SURFACE_READBACK_SCHEMA_VERSION
            || self.authority.as_str() != READ_ONLY_AUTHORITY
        {
            return Err(SurfaceError::Contract);
        }
        if self.computed_digest()? != self.derivation_digest {
            return Err(SurfaceError::DigestMismatch);
        }
        Ok(())
    }

    /// Compact canonical receipt bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the receipt does not validate or cannot be encoded.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, SurfaceError> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }
}

/// Parse strict canonical derivation-receipt bytes produced by this module.
///
/// # Errors
///
/// Returns [`SurfaceError::DigestMismatch`] when the input is not byte-for-byte the canonical
/// encoding of the value it decodes to.
pub fn parse_surface_derivation_receipt(
    bytes: &[u8],
) -> Result<SurfaceDerivationReceiptV1, SurfaceError> {
    let receipt: SurfaceDerivationReceiptV1 = serde_json::from_slice(bytes)?;
    receipt.validate()?;
    if receipt.canonical_bytes()? != bytes {
        return Err(SurfaceError::DigestMismatch);
    }
    Ok(receipt)
}

/// A derived cut and the exact record of how it was derived.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DerivedSurfaceV1 {
    /// Point-in-time cut closed against the approved profile.
    pub cut: SurfaceCutV1,
    /// Provenance, counts and unresolved inputs for that cut.
    pub derivation: SurfaceDerivationReceiptV1,
}

/// A store readback could not be performed or could not be honestly represented.
#[derive(Debug, thiserror::Error)]
pub enum SurfaceReadbackError {
    /// The underlying catalog rejected a read.
    #[error("catalog read failed")]
    Sqlite(#[from] rusqlite::Error),
    /// A derived value violated a surface contract. The inner refusal is part of the message:
    /// every [`SurfaceError`] arrives through this one variant, so a message that named only the
    /// wrapper turned a specific refusal -- a conflicting event identity, an unclosed universe, a
    /// cutoff violation -- into an unattributable "contract violation".
    #[error("derived surface contract violation: {0}")]
    Surface(#[from] SurfaceError),
    /// A stored JSON value could not be decoded.
    #[error("stored JSON is not decodable")]
    Json(#[from] serde_json::Error),
    /// The requested cutoff commit sequence is not in the catalog.
    #[error("cutoff commit sequence {commit_seq} is not a committed catalog commit")]
    UnknownCutoff {
        /// The requested commit sequence.
        commit_seq: u64,
    },
    /// A later commit carries an earlier wall time, so a wall-time cutoff would silently hide
    /// durably committed knowledge.
    #[error("catalog commit clock is not monotone at or before commit sequence {commit_seq}")]
    NonMonotonicCommitClock {
        /// The requested commit sequence.
        commit_seq: u64,
    },
    /// A profile surface's declared source matched more than one registered catalog source.
    #[error("declared source {declared_source} matches {matches} registered catalog sources")]
    AmbiguousSourceBinding {
        /// Exact `source` string from the approved profile.
        declared_source: String,
        /// Number of catalog sources that matched.
        matches: usize,
    },
    /// A row's own clocks contradict each other: it claims to have been observed after it became
    /// durable knowledge.
    #[error("observation {observation_id} is observed after it became durable knowledge")]
    ObservedAfterKnown {
        /// The offending observation identity.
        observation_id: String,
    },
    /// A stored integer or timestamp is outside the representable range.
    #[error("stored {field} is outside the representable range")]
    Range {
        /// Name of the offending column.
        field: &'static str,
    },
    /// A stored string cannot be represented on the strict surface wire.
    #[error("stored {field} is not a stable wire string")]
    Wire {
        /// Name of the offending column.
        field: &'static str,
    },
}

/// Read-only handle on an operational catalog, used only to derive surfaces.
pub struct SurfaceCatalogReadback {
    connection: Connection,
}

impl SurfaceCatalogReadback {
    /// Open an existing catalog read-only.
    ///
    /// # Errors
    ///
    /// Returns an error when the catalog cannot be opened read-only.
    pub fn open(catalog_path: &Path, busy_timeout: Duration) -> Result<Self, SurfaceReadbackError> {
        let connection = Connection::open_with_flags(
            catalog_path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        connection.busy_timeout(busy_timeout)?;
        Ok(Self { connection })
    }

    /// Adopt a caller-owned connection. The adapter never writes through it.
    #[must_use]
    pub const fn from_connection(connection: Connection) -> Self {
        Self { connection }
    }

    /// Highest commit sequence the catalog has committed, or `None` for an empty catalog.
    ///
    /// A caller that wants "everything the store knows" must ask the store for its own durable
    /// knowledge order rather than typing a number: that is the whole point of a derived cutoff.
    ///
    /// # Errors
    ///
    /// Returns an error when the catalog cannot be read or the stored sequence is out of range.
    pub fn latest_commit_seq(&self) -> Result<Option<u64>, SurfaceReadbackError> {
        let value: Option<i64> =
            self.connection
                .query_row("SELECT MAX(commit_seq) FROM ingest_commit", [], |row| {
                    row.get(0)
                })?;
        value
            .map(|seq| as_u64(seq, "ingest_commit.commit_seq"))
            .transpose()
    }

    /// Derive a complete point-in-time surface from committed rows at `cutoff_commit_seq`.
    ///
    /// # Errors
    ///
    /// Returns an error when the cutoff is unknown, the catalog clock is not monotone, a source
    /// binding is ambiguous, a stored row cannot be represented on the strict wire, or the derived
    /// cut does not close against the approved profile.
    pub fn derive_surface_cut(
        &self,
        profile: &DailyUseSurfaceProfileV1,
        cutoff_commit_seq: u64,
        render_limit: usize,
    ) -> Result<DerivedSurfaceV1, SurfaceReadbackError> {
        derive_surface_cut(self, profile, cutoff_commit_seq, render_limit)
    }
}

/// Derive a complete point-in-time surface from committed rows at `cutoff_commit_seq`.
///
/// The caller supplies the approved profile, the durable commit sequence and a render bound. It
/// supplies no population, no fact, no gap and no clock.
///
/// # Errors
///
/// See [`SurfaceCatalogReadback::derive_surface_cut`].
#[allow(clippy::too_many_lines)]
pub fn derive_surface_cut(
    catalog: &SurfaceCatalogReadback,
    profile: &DailyUseSurfaceProfileV1,
    cutoff_commit_seq: u64,
    render_limit: usize,
) -> Result<DerivedSurfaceV1, SurfaceReadbackError> {
    profile.validate()?;
    let connection = &catalog.connection;
    let cutoff = commit_clock(connection, cutoff_commit_seq)?;
    let catalog_schema_version = schema_version(connection)?;

    let mut unresolved = BTreeSet::from([
        UnresolvedSurfaceInput::HotLeaseReceipts,
        UnresolvedSurfaceInput::QualificationSessions,
        UnresolvedSurfaceInput::WorldEligibility,
    ]);

    // 1. Resolve every declared profile source against registered catalog sources.
    let mut bindings = Vec::with_capacity(profile.surfaces.len());
    let mut resolved: BTreeMap<String, Option<String>> = BTreeMap::new();
    for surface in &profile.surfaces {
        let declared = surface.source.as_str().to_owned();
        let catalog_source = match resolved.get(&declared) {
            Some(value) => value.clone(),
            None => {
                let value = bind_source(connection, &declared)?;
                resolved.insert(declared.clone(), value.clone());
                value
            }
        };
        if catalog_source.is_none() {
            unresolved.insert(UnresolvedSurfaceInput::SurfaceSourceNotRegistered);
        }
        bindings.push(SurfaceSourceBindingV1 {
            surface_id: surface.surface_id.clone(),
            declared_source: surface.source.clone(),
            catalog_source_id: catalog_source
                .as_deref()
                .map(wire("source.source_id"))
                .transpose()?,
        });
    }

    // 2. Derive the population: declared coverage scope union observed source-event subjects.
    // Two declared source strings can bind to one catalog source, so the census counts distinct
    // bound sources rather than bindings.
    let bound_sources: BTreeSet<String> = resolved.values().flatten().cloned().collect();
    let mut committed_observations = 0_u64;
    let mut observations_without_subject = 0_u64;
    for source in &bound_sources {
        let (total, unsubjected) = observation_census(connection, source, cutoff_commit_seq)?;
        committed_observations = committed_observations.saturating_add(total);
        observations_without_subject = observations_without_subject.saturating_add(unsubjected);
    }
    if observations_without_subject > 0 {
        unresolved.insert(UnresolvedSurfaceInput::SubjectsForCommittedObservations);
    }
    let mut coverage_level: BTreeMap<(String, String), String> = BTreeMap::new();
    let mut observed: BTreeMap<(String, String), ObservedFact> = BTreeMap::new();
    let mut declared_subjects: BTreeSet<String> = BTreeSet::new();
    let mut observed_subjects: BTreeSet<String> = BTreeSet::new();
    for source in resolved.values().flatten() {
        for (subject, level) in declared_coverage(connection, source, cutoff_commit_seq)? {
            declared_subjects.insert(subject.clone());
            coverage_level.insert((source.clone(), subject), level);
        }
        for (subject, fact) in latest_observations(connection, source, cutoff_commit_seq)? {
            observed_subjects.insert(subject.clone());
            observed.insert((source.clone(), subject), fact);
        }
    }
    let eligible: BTreeSet<String> = declared_subjects
        .union(&observed_subjects)
        .cloned()
        .collect();

    // 3. Derive open gaps and effective per-cell assertions.
    let mut gaps: BTreeMap<String, Vec<GapRow>> = BTreeMap::new();
    for source in resolved.values().flatten() {
        gaps.insert(
            source.clone(),
            open_gaps(connection, source, cutoff_commit_seq)?,
        );
    }
    let facts = field_assertions(connection, cutoff_commit_seq)?;
    if facts.is_empty() {
        unresolved.insert(UnresolvedSurfaceInput::FieldAssertionsAbsent);
    }

    // 4. Promote one fact row per surface and observed subject.
    let mut observations = Vec::new();
    let mut fact_subjects: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for surface in &profile.surfaces {
        let Some(source) = resolved.get(surface.source.as_str()).cloned().flatten() else {
            continue;
        };
        let descending = match surface.ordering.as_str() {
            "newest" => true,
            "oldest" => false,
            _ => {
                unresolved.insert(UnresolvedSurfaceInput::RenderOrderingPolicy);
                false
            }
        };
        let cadence = cadence_seconds(surface.cadence.as_str());
        if cadence.is_none() {
            unresolved.insert(UnresolvedSurfaceInput::CadenceStalenessBound);
        }
        let no_gaps: Vec<GapRow> = Vec::new();
        let source_gaps = gaps.get(&source).unwrap_or(&no_gaps);
        for subject in &eligible {
            let Some(fact) = observed.get(&(source.clone(), subject.clone())) else {
                continue;
            };
            let gap = source_gaps
                .iter()
                .find(|row| row.subject.as_deref().is_none_or(|value| value == subject));
            fact_subjects
                .entry(source.clone())
                .or_default()
                .insert(subject.clone());
            let membership = match coverage_level.get(&(source.clone(), subject.clone())) {
                Some(level) => match level.as_str() {
                    "census" => SurfaceMembership::Census,
                    "hot" => SurfaceMembership::Hot,
                    _ => {
                        unresolved.insert(UnresolvedSurfaceInput::CoverageLevelMembership);
                        SurfaceMembership::DenominatorOnly
                    }
                },
                // A census names where it looked and the market answers with what was there. A
                // subject that turned up inside a declared scope without having been declared
                // itself is observed, not denominator-only: those are opposite facts, and
                // labelling it `DenominatorOnly` would both invert it and drop the row the
                // catalog actually holds. Its product membership is still unresolved, because no
                // coverage level was ever declared for it, and the receipt says so.
                None => {
                    unresolved.insert(UnresolvedSurfaceInput::UndeclaredObservedSubject);
                    SurfaceMembership::ObservedUndeclared
                }
            };
            let mut fields = BTreeMap::new();
            for field in &surface.fields_media {
                fields.insert(
                    field.clone(),
                    cell_state(surface, field, subject, gap, cadence, cutoff, &facts)?,
                );
            }
            observations.push(SurfaceObservationV1 {
                event_id: wire("derived event identity")(&surface_event_identity(
                    surface.surface_id.as_str(),
                    subject.as_str(),
                    fact.observation_id.as_str(),
                ))?,
                subject: wire("source_event.natural_key")(subject.as_str())?,
                observed_at: fact.observed_at,
                known_at: fact.known_at,
                supersedes_event_id: None,
                surface_id: surface.surface_id.clone(),
                source_id: surface.source.clone(),
                memberships: vec![membership],
                fields,
                order_key: wire("derived order key")(&order_key(
                    fact.commit_seq,
                    fact.intra_commit_seq,
                    descending,
                ))?,
                evidence_digest: ValueDigest::new(format!("sha256:{}", fact.blob_id))
                    .map_err(|_| SurfaceError::DigestFormat)?,
            });
        }
    }

    // 5. Close the derived population and reduce. Order, count and digest are recomputed here.
    let subjects = eligible
        .iter()
        .map(|value| wire("source_event.natural_key")(value.as_str()))
        .collect::<Result<Vec<_>, _>>()?;
    let eligible_count =
        u64::try_from(subjects.len()).map_err(|_| SurfaceReadbackError::Range {
            field: "eligible subject count",
        })?;
    let universe = DeclaredObservedUniverseV1 {
        universe_id: wire("derived universe id")(&format!(
            "joshi.surface.catalog_universe.v1:{cutoff_commit_seq}"
        ))?,
        surface_version: profile.profile_version,
        cutoff,
        eligible_count: WireU64::new(eligible_count),
        eligible_digest: digest(&serde_json::to_vec(&subjects)?)?,
        eligible_subjects: subjects,
        // A catalog-derived population is a sample, never a closed denominator, and the wire says
        // so rather than leaving it to a footnote.
        //
        // `closed` on this DTO is the claim "this list is the whole universe; nothing outside it
        // can appear". Over a set defined as *declared scope union everything we happened to
        // observe*, that claim is self-satisfying: subjects enter the list by being seen, so the
        // closure can never fail and carries no information. What it does carry is a reading --
        // that `eligibleCount` is a denominator, and that observed-over-eligible is a coverage
        // ratio. For a census neither is true: here two subjects were declared and nine arrived
        // by turning up in someone else's transaction.
        //
        // `sample_only` is the field the constitution provides for exactly this, and it is
        // unconditionally true of this adapter: `WorldEligibility` is always unresolved because
        // no catalog can witness that the world holds no further subject. Declaring it keeps the
        // population honest in the direction that cannot mislead.
        //
        // Nothing is lost by the flip: `SurfaceReducer::reduce` names every declared eligible
        // subject that carried no admitted row with the exact reason `not_observed_by_cutoff`
        // whether or not the universe is closed, so a declared-and-unobserved subject is still an
        // explicit omission rather than a silence.
        closed: false,
        sample_only: true,
    };
    let cut = SurfaceReducer::reduce(profile, universe, &observations, cutoff, render_limit)?;

    // 6. Record the derivation, including everything it could not resolve.
    let mut open = Vec::new();
    let no_subjects: BTreeSet<String> = BTreeSet::new();
    for (source, rows) in &gaps {
        let carried = fact_subjects.get(source).unwrap_or(&no_subjects);
        for row in rows {
            // A gap is expressed only when every eligible subject it covers actually carries it.
            let expressed = match &row.subject {
                Some(subject) => !eligible.contains(subject) || carried.contains(subject),
                None => eligible.iter().all(|subject| carried.contains(subject)),
            };
            if !expressed {
                unresolved.insert(UnresolvedSurfaceInput::GapCellsForUnobservedSubjects);
            }
            open.push(SurfaceOpenGapV1 {
                gap_id: wire("coverage_gap.gap_id")(row.gap_id.as_str())?,
                catalog_source_id: wire("source.source_id")(source.as_str())?,
                subject: row
                    .subject
                    .as_deref()
                    .map(wire("coverage_gap_contract.scope_subject"))
                    .transpose()?,
                window_lower: row.window_lower.clone(),
                window_upper: row.window_upper.clone(),
                since: row.since,
                severity: wire("coverage_gap.severity")(row.severity.as_str())?,
                cause: wire("coverage_gap.cause_code")(row.cause.as_str())?,
                expressed_in_cut: expressed,
            });
        }
    }
    open.sort_by(|left, right| left.gap_id.cmp(&right.gap_id));
    let fact_rows = u64::try_from(observations.len()).map_err(|_| SurfaceReadbackError::Range {
        field: "derived fact row count",
    })?;
    let field_assertion_rows =
        u64::try_from(facts.len()).map_err(|_| SurfaceReadbackError::Range {
            field: "field assertion count",
        })?;
    let mut derivation = SurfaceDerivationReceiptV1 {
        contract: wire("readback contract")(SURFACE_READBACK_CONTRACT)?,
        schema_version: SURFACE_READBACK_SCHEMA_VERSION,
        catalog_schema_version: WireU64::new(catalog_schema_version),
        cutoff_commit_seq: WireU64::new(cutoff_commit_seq),
        cutoff,
        profile_digest: profile.profile_digest.clone(),
        bindings,
        declared_subjects: WireU64::new(count(declared_subjects.len(), "declared subjects")?),
        observed_subjects: WireU64::new(count(observed_subjects.len(), "observed subjects")?),
        committed_observations: WireU64::new(committed_observations),
        observations_without_subject: WireU64::new(observations_without_subject),
        eligible_count: WireU64::new(eligible_count),
        fact_rows: WireU64::new(fact_rows),
        field_assertion_rows: WireU64::new(field_assertion_rows),
        open_gaps: open,
        unresolved,
        authority: wire("readback authority")(READ_ONLY_AUTHORITY)?,
        derivation_digest: digest(b"placeholder")?,
    };
    derivation.derivation_digest = derivation.computed_digest()?;
    derivation.validate()?;
    Ok(DerivedSurfaceV1 { cut, derivation })
}

struct ObservedFact {
    observation_id: String,
    commit_seq: u64,
    intra_commit_seq: u64,
    blob_id: String,
    observed_at: UtcTimestamp,
    known_at: UtcTimestamp,
}

struct GapRow {
    gap_id: String,
    subject: Option<String>,
    window_lower: SurfaceGapBoundaryV1,
    window_upper: Option<SurfaceGapBoundaryV1>,
    since: UtcTimestamp,
    severity: String,
    cause: String,
}

struct FieldFact {
    observed_at: UtcTimestamp,
    known_at: UtcTimestamp,
    status: String,
}

fn commit_clock(
    connection: &Connection,
    cutoff_commit_seq: u64,
) -> Result<UtcTimestamp, SurfaceReadbackError> {
    let seq = sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?;
    let wall: Option<i64> = connection
        .query_row(
            "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
            params![seq],
            |row| row.get(0),
        )
        .optional()?;
    let Some(wall) = wall else {
        return Err(SurfaceReadbackError::UnknownCutoff {
            commit_seq: cutoff_commit_seq,
        });
    };
    let highest: Option<i64> = connection.query_row(
        "SELECT MAX(committed_wall_us) FROM ingest_commit WHERE commit_seq<=?1",
        params![seq],
        |row| row.get(0),
    )?;
    if highest != Some(wall) {
        return Err(SurfaceReadbackError::NonMonotonicCommitClock {
            commit_seq: cutoff_commit_seq,
        });
    }
    timestamp_from_us(wall, "ingest_commit.committed_wall_us")
}

fn schema_version(connection: &Connection) -> Result<u64, SurfaceReadbackError> {
    let value: Option<i64> = connection.query_row(
        "SELECT MAX(migration_id) FROM schema_migration",
        [],
        |row| row.get(0),
    )?;
    as_u64(value.unwrap_or_default(), "schema_migration.migration_id")
}

fn bind_source(
    connection: &Connection,
    declared: &str,
) -> Result<Option<String>, SurfaceReadbackError> {
    let mut statement = connection.prepare(
        "SELECT source_id FROM source WHERE source_id=?1 OR namespace=?1 ORDER BY source_id",
    )?;
    let rows = statement.query_map(params![declared], |row| row.get::<_, String>(0))?;
    let matched = rows.collect::<Result<Vec<_>, _>>()?;
    match matched.len() {
        0 => Ok(None),
        1 => Ok(matched.into_iter().next()),
        matches => Err(SurfaceReadbackError::AmbiguousSourceBinding {
            declared_source: declared.to_owned(),
            matches,
        }),
    }
}

fn declared_coverage(
    connection: &Connection,
    source: &str,
    cutoff_commit_seq: u64,
) -> Result<Vec<(String, String)>, SurfaceReadbackError> {
    let mut statement = connection.prepare(
        "SELECT c.scope_subject,w.coverage_level
         FROM coverage_window w JOIN coverage_window_contract c USING(coverage_id)
         WHERE w.source_id=?1 AND w.opened_commit_seq<=?2 AND c.scope_subject IS NOT NULL
         ORDER BY c.scope_subject,w.opened_commit_seq,w.coverage_id",
    )?;
    let rows = statement.query_map(
        params![
            source,
            sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?
        ],
        |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
    )?;
    // The ORDER BY makes the last row per subject the newest declaration at the cutoff.
    let mut latest: BTreeMap<String, String> = BTreeMap::new();
    for row in rows {
        let (subject, level) = row?;
        latest.insert(subject, level);
    }
    Ok(latest.into_iter().collect())
}

fn latest_observations(
    connection: &Connection,
    source: &str,
    cutoff_commit_seq: u64,
) -> Result<Vec<(String, ObservedFact)>, SurfaceReadbackError> {
    let mut statement = connection.prepare(
        "SELECT e.natural_key,o.observation_id,o.commit_seq,o.intra_commit_seq,o.blob_id,
                o.event_time_status,o.source_event_lower_us,o.received_wall_us,
                c.committed_wall_us
         FROM observation o
         JOIN observation_source_event l ON l.observation_id=o.observation_id
         JOIN source_event e ON e.source_event_id=l.source_event_id
         JOIN ingest_commit c ON c.commit_seq=o.commit_seq
         WHERE o.source_id=?1 AND o.commit_seq<=?2 AND l.relation IN ('contains','revision')
         ORDER BY e.natural_key,o.commit_seq,o.intra_commit_seq,o.observation_id",
    )?;
    let rows = statement.query_map(
        params![
            source,
            sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?
        ],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<i64>>(6)?,
                row.get::<_, i64>(7)?,
                row.get::<_, i64>(8)?,
            ))
        },
    )?;
    // The ORDER BY makes the last row per subject the newest committed knowledge at the cutoff.
    let mut latest: BTreeMap<String, ObservedFact> = BTreeMap::new();
    for row in rows {
        let (subject, observation_id, seq, intra, blob_id, status, lower, received, committed) =
            row?;
        let known_at = timestamp_from_us(committed, "ingest_commit.committed_wall_us")?;
        let observed_us = match (status.as_str(), lower) {
            ("exact" | "bounded", Some(value)) => value,
            _ => received,
        };
        let observed_at = timestamp_from_us(observed_us, "observation event time")?;
        if observed_at > known_at {
            return Err(SurfaceReadbackError::ObservedAfterKnown { observation_id });
        }
        latest.insert(
            subject,
            ObservedFact {
                observation_id,
                commit_seq: as_u64(seq, "observation.commit_seq")?,
                intra_commit_seq: as_u64(intra, "observation.intra_commit_seq")?,
                blob_id,
                observed_at,
                known_at,
            },
        );
    }
    Ok(latest.into_iter().collect())
}

fn open_gaps(
    connection: &Connection,
    source: &str,
    cutoff_commit_seq: u64,
) -> Result<Vec<GapRow>, SurfaceReadbackError> {
    let mut statement = connection.prepare(
        "SELECT g.gap_id,k.scope_subject,c.committed_wall_us,g.severity,g.cause_code,
                k.lower_boundary_json,k.upper_boundary_json
         FROM coverage_gap g
         JOIN coverage_gap_contract k ON k.gap_id=g.gap_id
         JOIN ingest_commit c ON c.commit_seq=g.detected_commit_seq
         WHERE k.scope_source_id=?1 AND g.detected_commit_seq<=?2
           AND NOT EXISTS (
             SELECT 1 FROM coverage_gap_recovery r
             WHERE r.gap_id=g.gap_id AND r.commit_seq<=?2
               AND r.recovery_status IN ('complete','unrecoverable')
           )
         ORDER BY g.detected_commit_seq,g.gap_id",
    )?;
    let rows = statement.query_map(
        params![
            source,
            sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?
        ],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?,
            ))
        },
    )?;
    let mut result = Vec::new();
    for row in rows {
        let (gap_id, subject, committed, severity, cause, lower, upper) = row?;
        result.push(GapRow {
            gap_id,
            subject,
            window_lower: gap_boundary(&lower, "coverage_gap_contract.lower_boundary_json")?,
            window_upper: upper
                .as_deref()
                .map(|value| gap_boundary(value, "coverage_gap_contract.upper_boundary_json"))
                .transpose()?,
            since: timestamp_from_us(committed, "ingest_commit.committed_wall_us")?,
            severity,
            cause,
        });
    }
    Ok(result)
}

/// Reads one stored boundary back without projecting it onto a clock it does not carry.
fn gap_boundary(
    stored: &str,
    field: &'static str,
) -> Result<SurfaceGapBoundaryV1, SurfaceReadbackError> {
    #[derive(Deserialize)]
    struct StoredVariant {
        discriminator: StableString,
    }
    #[derive(Deserialize)]
    #[serde(tag = "clock", rename_all = "snake_case")]
    enum Stored {
        Wall { value: UtcTimestamp },
        Commit { value: WireU64 },
        SourceCursor { value: StableString },
        Unknown { reason: StoredVariant },
    }
    Ok(match serde_json::from_str::<Stored>(stored) {
        Ok(Stored::Wall { value }) => SurfaceGapBoundaryV1::Wall { value },
        Ok(Stored::Commit { value }) => SurfaceGapBoundaryV1::Commit { value },
        Ok(Stored::SourceCursor { value }) => SurfaceGapBoundaryV1::SourceCursor { value },
        Ok(Stored::Unknown { reason }) => SurfaceGapBoundaryV1::Unknown {
            reason: reason.discriminator,
        },
        Err(_) => SurfaceGapBoundaryV1::Unrecognized {
            stored: wire(field)(stored)?,
        },
    })
}

/// Counts observations committed at the cutoff, and how many of them name no subject.
fn observation_census(
    connection: &Connection,
    source: &str,
    cutoff_commit_seq: u64,
) -> Result<(u64, u64), SurfaceReadbackError> {
    let (total, unsubjected): (i64, i64) = connection.query_row(
        "SELECT COUNT(*),
                SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM observation_source_event l
                    WHERE l.observation_id=o.observation_id
                      AND l.relation IN ('contains','revision')
                ) THEN 1 ELSE 0 END)
         FROM observation o WHERE o.source_id=?1 AND o.commit_seq<=?2",
        params![
            source,
            sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?
        ],
        |row| {
            Ok((
                row.get(0)?,
                row.get::<_, Option<i64>>(1)?.unwrap_or_default(),
            ))
        },
    )?;
    Ok((
        as_u64(total, "observation count")?,
        as_u64(unsubjected, "observation without subject count")?,
    ))
}

fn field_assertions(
    connection: &Connection,
    cutoff_commit_seq: u64,
) -> Result<BTreeMap<(String, String, String), FieldFact>, SurfaceReadbackError> {
    let prefix = format!("[\"{SURFACE_FIELD_ASSERTION_DOMAIN}\",%");
    let mut statement = connection.prepare(
        "SELECT a.semantic_key,a.assertion_status,a.valid_time_status,a.valid_lower_us,
                a.produced_wall_us,c.committed_wall_us,a.produced_commit_seq,a.assertion_id
         FROM assertion a JOIN ingest_commit c ON c.commit_seq=a.produced_commit_seq
         WHERE a.produced_commit_seq<=?1 AND a.assertion_status<>'retraction'
           AND a.semantic_key LIKE ?2
           AND NOT EXISTS (
             SELECT 1 FROM assertion later
             WHERE later.supersedes_assertion_id=a.assertion_id
               AND later.produced_commit_seq<=?1
           )
         ORDER BY a.semantic_key,a.produced_commit_seq,a.assertion_id",
    )?;
    let rows = statement.query_map(
        params![
            sqlite_u64(cutoff_commit_seq, "cutoff commit sequence")?,
            prefix
        ],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<i64>>(3)?,
                row.get::<_, i64>(4)?,
                row.get::<_, i64>(5)?,
            ))
        },
    )?;
    // The ORDER BY makes the last row per cell the newest effective assertion at the cutoff.
    let mut result = BTreeMap::new();
    for row in rows {
        let (key, status, valid_status, valid_lower, produced, committed) = row?;
        let Some(cell) = parse_field_semantic_key(&key) else {
            continue;
        };
        let observed_us = match (valid_status.as_str(), valid_lower) {
            ("exact" | "bounded", Some(value)) => value,
            _ => produced,
        };
        result.insert(
            cell,
            FieldFact {
                observed_at: timestamp_from_us(observed_us, "assertion valid lower")?,
                known_at: timestamp_from_us(committed, "ingest_commit.committed_wall_us")?,
                status,
            },
        );
    }
    Ok(result)
}

fn parse_field_semantic_key(key: &str) -> Option<(String, String, String)> {
    let parts: [String; 4] = serde_json::from_str(key).ok()?;
    let [domain, surface, subject, field] = parts;
    if domain == SURFACE_FIELD_ASSERTION_DOMAIN {
        Some((surface, subject, field))
    } else {
        None
    }
}

fn cell_state(
    surface: &SurfaceEntryV1,
    field: &StableString,
    subject: &str,
    gap: Option<&GapRow>,
    cadence: Option<i64>,
    cutoff: UtcTimestamp,
    facts: &BTreeMap<(String, String, String), FieldFact>,
) -> Result<FieldState, SurfaceReadbackError> {
    let absent = matches!(surface.status, SurfaceStatus::AbsentByDesign)
        || surface
            .field_status
            .get(field)
            .is_some_and(|status| matches!(status, SurfaceStatus::AbsentByDesign));
    if absent {
        return Ok(FieldState::Refused {
            reason: wire("absent-by-design reason")("absent_by_design")?,
        });
    }
    if let Some(row) = gap {
        return Ok(FieldState::Gap {
            gap_id: wire("coverage_gap.gap_id")(row.gap_id.as_str())?,
            since: row.since,
        });
    }
    let key = (
        surface.surface_id.as_str().to_owned(),
        subject.to_owned(),
        field.as_str().to_owned(),
    );
    let Some(fact) = facts.get(&key) else {
        return Ok(FieldState::Unknown {
            reason: wire("unknown reason")("field_not_asserted_by_cutoff")?,
        });
    };
    match fact.status.as_str() {
        "accepted" => {}
        other => {
            return Ok(FieldState::Unknown {
                reason: wire("unknown reason")(&format!("field_assertion_{other}"))?,
            });
        }
    }
    if fact.observed_at > fact.known_at || fact.observed_at > cutoff {
        return Ok(FieldState::Unknown {
            reason: wire("unknown reason")("field_assertion_event_time_after_knowledge")?,
        });
    }
    let age = (cutoff.as_datetime() - fact.observed_at.as_datetime()).whole_seconds();
    let age_seconds = u64::try_from(age).map_err(|_| SurfaceReadbackError::Range {
        field: "derived stale age",
    })?;
    if cadence.is_some_and(|bound| age > bound) {
        return Ok(FieldState::Stale {
            observed_at: fact.observed_at,
            age_seconds: WireU64::new(age_seconds),
        });
    }
    Ok(FieldState::Covered {
        observed_at: fact.observed_at,
    })
}

fn cadence_seconds(cadence: &str) -> Option<i64> {
    // Sub-second cadences are deliberately not a staleness bound: the surface wire carries whole
    // seconds, so a millisecond cadence would round to an unfalsifiable zero.
    if cadence.ends_with("ms") {
        return None;
    }
    let (digits, multiplier) = match cadence.as_bytes().last()? {
        b's' => (&cadence[..cadence.len() - 1], 1_i64),
        b'm' => (&cadence[..cadence.len() - 1], 60),
        b'h' => (&cadence[..cadence.len() - 1], 3_600),
        _ => return None,
    };
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    digits.parse::<i64>().ok()?.checked_mul(multiplier)
}

fn order_key(commit_seq: u64, intra_commit_seq: u64, descending: bool) -> String {
    let (primary, secondary) = if descending {
        (u64::MAX - commit_seq, u64::MAX - intra_commit_seq)
    } else {
        (commit_seq, intra_commit_seq)
    };
    format!("{primary:020}{secondary:020}")
}

fn digest(bytes: &[u8]) -> Result<ValueDigest, SurfaceError> {
    let mut hash = Sha256::new();
    hash.update(bytes);
    ValueDigest::new(format!("sha256:{:x}", hash.finalize()))
        .map_err(|_| SurfaceError::DigestFormat)
}

fn wire(field: &'static str) -> impl Fn(&str) -> Result<StableString, SurfaceReadbackError> {
    move |value| StableString::new(value).map_err(|_| SurfaceReadbackError::Wire { field })
}

fn count(value: usize, field: &'static str) -> Result<u64, SurfaceReadbackError> {
    u64::try_from(value).map_err(|_| SurfaceReadbackError::Range { field })
}

fn as_u64(value: i64, field: &'static str) -> Result<u64, SurfaceReadbackError> {
    u64::try_from(value).map_err(|_| SurfaceReadbackError::Range { field })
}

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64, SurfaceReadbackError> {
    i64::try_from(value).map_err(|_| SurfaceReadbackError::Range { field })
}

fn timestamp_from_us(
    value: i64,
    field: &'static str,
) -> Result<UtcTimestamp, SurfaceReadbackError> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or(SurfaceReadbackError::Range { field })?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| SurfaceReadbackError::Range { field })?;
    UtcTimestamp::new(datetime).map_err(|_| SurfaceReadbackError::Range { field })
}
