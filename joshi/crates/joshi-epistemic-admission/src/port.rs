//! Private-capability shapes for the future co-located single-writer adapter.
//!
//! All types in this module have private fields and no public constructors. They are intentionally
//! unusable as durable proof outside this crate. A future adapter must live in this crate, resolve
//! canonical store rows, and construct them only after the receipts named in the implementation
//! handoff have been read and reverified.

#![allow(dead_code)]

use joshi_domain::{StableString, UtcTimestamp, ValueDigest};
use joshi_epistemic_book::{ArtifactRefV1, CapabilityAttestationV1, FrozenInputManifestV1};

/// Exact scene row plus its immutable store receipt.
#[derive(Debug)]
pub struct SceneReceipt {
    scene: ArtifactRefV1,
    receipt: ArtifactRefV1,
}

/// Exact declared universe row plus its immutable store receipt.
#[derive(Debug)]
pub struct UniverseReceipt {
    universe: ArtifactRefV1,
    receipt: ArtifactRefV1,
}

/// Exact frozen evidence, coverage, and gap closure resolved from store rows.
#[derive(Debug)]
pub struct EvidenceClosureReceipt {
    frozen_input: FrozenInputManifestV1,
    manifest_digest: ValueDigest,
    receipt: ArtifactRefV1,
}

/// Store-resolved maximum availability and occurrence information cutoff.
#[derive(Debug)]
pub struct CutoffReceipt {
    maximum_input_availability: UtcTimestamp,
    information_cutoff: UtcTimestamp,
    receipt: ArtifactRefV1,
}

/// Exact capability attestations resolved from their persisted rows.
#[derive(Debug)]
pub struct CapabilityClosureReceipt {
    capabilities: Vec<CapabilityAttestationV1>,
    closure_digest: ValueDigest,
    receipt: ArtifactRefV1,
}

/// Atomic occurrence bytes/digest commit receipt.
#[derive(Debug)]
pub struct OccurrenceCommitReceipt {
    occurrence: ArtifactRefV1,
    committed_at: UtcTimestamp,
    receipt: ArtifactRefV1,
}

/// Occurrence-scoped sealed first-round namespace and registered eligible set.
#[derive(Debug)]
pub struct SealedNamespaceReceipt {
    occurrence: ArtifactRefV1,
    namespace_id: StableString,
    eligible_forecaster_ids: Vec<StableString>,
    required_first_round_count: u64,
    reveal_not_before: UtcTimestamp,
    receipt: ArtifactRefV1,
}

/// Store-derived visibility at the instant before one submission is committed.
#[derive(Debug)]
pub struct VisibilityReceipt {
    occurrence: ArtifactRefV1,
    submission_id: StableString,
    visible_submission_ids: Vec<StableString>,
    visible_ensemble_ids: Vec<StableString>,
    reveal_at_before_commit: Option<UtcTimestamp>,
    receipt: ArtifactRefV1,
}

/// Atomic sealed submission bytes/digest commit receipt.
#[derive(Debug)]
pub struct SubmissionCommitReceipt {
    submission: ArtifactRefV1,
    occurrence: ArtifactRefV1,
    committed_at: UtcTimestamp,
    receipt: ArtifactRefV1,
}

/// The unique all-eligible-components-sealed boundary and durable reveal occurrence.
#[derive(Debug)]
pub struct FirstRoundSealReceipt {
    occurrence: ArtifactRefV1,
    all_eligible_sealed_at: UtcTimestamp,
    reveal_at: UtcTimestamp,
    reveal_receipt: ArtifactRefV1,
}

/// Exact adjudication commit, admissible outcome evidence, coverage/gaps, and knowledge cutoff.
#[derive(Debug)]
pub struct AdjudicationReceiptSet {
    occurrence: ArtifactRefV1,
    adjudication: ArtifactRefV1,
    knowledge_cutoff: UtcTimestamp,
    outcome_evidence_digest: ValueDigest,
    coverage_closure_digest: ValueDigest,
    committed_at: UtcTimestamp,
    receipt: ArtifactRefV1,
}

/// Exact earlier-only support membership, windows, and derivation receipt.
#[derive(Debug)]
pub struct SupportLineageReceipt {
    summary: ArtifactRefV1,
    claim_definition: ArtifactRefV1,
    latest_embargo_through: UtcTimestamp,
    membership_digest: ValueDigest,
    receipt: ArtifactRefV1,
}

/// Opaque proof that an exact occurrence is store-resolved and durably committed.
#[derive(Debug)]
pub struct StoreResolvedClaimOccurrence {
    scene: SceneReceipt,
    universe: UniverseReceipt,
    evidence: EvidenceClosureReceipt,
    cutoff: CutoffReceipt,
    capabilities: CapabilityClosureReceipt,
    commit: OccurrenceCommitReceipt,
}

/// Opaque proof that one first-round submission was durably sealed while mutually blind.
#[derive(Debug)]
pub struct StoreResolvedFirstRoundSubmission {
    occurrence: StoreResolvedClaimOccurrence,
    namespace: SealedNamespaceReceipt,
    visibility: VisibilityReceipt,
    commit: SubmissionCommitReceipt,
}

/// Opaque proof of a durable, admissibly resolved adjudication.
#[derive(Debug)]
pub struct StoreResolvedAdjudication {
    occurrence: StoreResolvedClaimOccurrence,
    receipt_set: AdjudicationReceiptSet,
}

/// Opaque proof of a score whose submission, adjudication, and occurrence lineages are durable.
#[derive(Debug)]
pub struct StoreResolvedScore {
    occurrence: StoreResolvedClaimOccurrence,
    submission: StoreResolvedFirstRoundSubmission,
    adjudication: StoreResolvedAdjudication,
}

/// Opaque proof that support has an exact complete denominator and is earlier-only.
#[derive(Debug)]
pub struct StoreResolvedSupport {
    lineage: SupportLineageReceipt,
}

/// Opaque proof of a shadow-only ensemble with earlier-only support and post-seal reveal.
#[derive(Debug)]
pub struct StoreResolvedShadowEnsemble {
    occurrence: StoreResolvedClaimOccurrence,
    support: StoreResolvedSupport,
    seal: FirstRoundSealReceipt,
    component_count: u64,
}

// The fields above are intentionally retained even before the private adapter is implemented:
// they make every required store resolution explicit in the type contract and prevent accidental
// public construction. The future adapter is expected to consume all fields, at which point these
// intentional layout witnesses cease to be unused.
#[allow(dead_code)]
fn private_receipt_shape_witness(
    value: &StoreResolvedShadowEnsemble,
) -> (&ArtifactRefV1, UtcTimestamp, u64) {
    (
        &value.seal.occurrence,
        value.seal.reveal_at,
        value.component_count,
    )
}

#[path = "private_adapter.rs"]
mod private_adapter;
