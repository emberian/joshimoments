//! Narrow, artifact-bearing Wave 5 G0 source/publication component witness.
//!
//! This remains an offline fixture-only partial. It deliberately cannot claim the complete G0
//! fault walk, product use, live source coverage, or execution authority.

use std::path::Path;

use joshi_admission::{Sha256Digest, operational::AUTHORITY};
use joshi_domain::{StableString, WireStringError};
use joshi_publication::{CockpitPublicationId, CockpitV2MembershipKind};
use joshi_pump_adapter::prepare_direct_with_offline_fixture_selection;
use joshi_scientific_memory::{
    ActId, ActKind, CatalogCommitSeq, Digest as MemoryDigest, EffectStatus, Episode,
    EpisodeCompleteness, EpisodeId, EpisodePath, EpisodeSegment, LogicalSessionTick,
    LotAssociation, MemoryOccurrence, OperatorAct, PresentationBinding, PresentationGap,
    PresentationGapReason, SceneBinding, SceneId, SceneRef, SegmentId, SessionId,
};
use joshi_spool::LocalSpool;
use joshi_store::{IdempotencyStatus, SqliteStore, StoreMode};
use serde::Serialize;
use thiserror::Error;

use crate::{
    wave5_circulation::{RegisteredWave5Run, circulate_public_c0},
    wave5_readiness::{config, fixture_registration_bundles, now, spool_config, store_bundle},
};

const DIRECT_C0_FILE: &[u8] =
    include_bytes!("../../../fixtures/pump-api/direct-fetch-outcome.synthetic.json");
const OFFLINE_SELECTION_FILE: &[u8] =
    include_bytes!("../../../fixtures/pump-api/offline-fixture-selection-v1.json");

/// Deterministic component-local interruption points. These do not cover the full G0 schedule.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Wave5G0SourcePublicationFaultPoint {
    BeforeSemanticFact,
    AfterSemanticFact,
    BeforePublicationPrepare,
    AfterPublicationPrepare,
    BeforePublicationBody,
    AfterPublicationBody,
    BeforePublicationHead,
    AfterPublicationHead,
    BeforeMemoryAct,
    AfterMemoryAct,
    BeforeMemoryEpisode,
    AfterMemoryEpisode,
}

/// Exact component evidence. Every positive field is reverified after a read-only reopen.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave5G0SourcePublicationReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub catalog_schema: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub catalog_admission_id: String,
    pub selection_digest: String,
    pub source_occurrence_id: String,
    pub source_descriptor_digest: String,
    pub source_fact_count: usize,
    pub eligible_subject_count: usize,
    pub hot_subject_count: usize,
    pub cold_control_subject_count: usize,
    pub preparation_id: String,
    pub publication_id: String,
    pub publication_digest: String,
    pub publication_bytes_digest: String,
    pub head_digest: String,
    pub memory_act_id: String,
    pub memory_act_digest: String,
    pub memory_episode_id: String,
    pub memory_episode_digest: String,
    pub memory_queue_through: u64,
    pub source_semantics_closed: bool,
    pub publication_prepare_body_head_closed: bool,
    pub partial_memory_chain_closed: bool,
    pub restart_reverified: bool,
    pub full_offline_fault_walk: bool,
    pub provider_io: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

/// Walk the exact offline Pump body and separately retained selection through store-resolved
/// source facts, immutable Cockpit V2 prepare/body/head commits, and a read-only restart.
///
/// # Errors
///
/// Refuses any changed registration, source receipt, selection partition, semantic closure,
/// publication stage, commit order, or restart readback.
#[allow(clippy::too_many_lines)]
pub fn run_wave5_g0_source_publication(
    state: &Path,
) -> Result<Wave5G0SourcePublicationReport, Wave5G0SourcePublicationError> {
    run_wave5_g0_source_publication_with_fault(state, None)
}

/// Execute the component with one deterministic process-loss injection.
///
/// Reinvoking [`run_wave5_g0_source_publication`] on the same state after an injected error must
/// converge to the exact baseline report.
///
/// # Errors
///
/// Returns ordinary component errors or the requested deterministic interruption.
#[allow(clippy::too_many_lines)]
pub fn run_wave5_g0_source_publication_with_fault(
    state: &Path,
    fault: Option<Wave5G0SourcePublicationFaultPoint>,
) -> Result<Wave5G0SourcePublicationReport, Wave5G0SourcePublicationError> {
    let (registration, bundle, _) = fixture_registration_bundles()?;
    let mut store = SqliteStore::open(config(state)?, StoreMode::SingleWriter)?;
    store.migrate(now()?)?;
    let run_id = StableString::new(registration.run_id.clone())?;
    let registration_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:registration")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let registration_receipt =
        store.commit_wave5_run_registration_v1(&store_bundle(&bundle), &registration_context)?;
    if !matches!(
        registration_receipt.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) {
        return Err(Wave5G0SourcePublicationError::Invariant(
            "run registration returned an unsupported status",
        ));
    }

    // Exact fixture time is part of the immutable batch/policy/segment closure. Wall time for the
    // store-owned occurrence commits remains allocated by `begin_wave5_commit`.
    let committed_at = "2026-08-17T12:00:00.020000Z"
        .parse()
        .map_err(|_| Wave5G0SourcePublicationError::Invariant("invalid static fixture clock"))?;
    let prepared = prepare_direct_with_offline_fixture_selection(
        DIRECT_C0_FILE,
        OFFLINE_SELECTION_FILE,
        "batch:wave5-g0-source-publication-0001",
        committed_at,
        1,
    )?;
    let spool = LocalSpool::open(spool_config(state))?;
    let catalog_admission_id = "catalog-admission:wave5-g0-source-publication-0001";
    let circulation = circulate_public_c0(
        &mut store,
        &spool,
        RegisteredWave5Run {
            run_id: run_id.as_str(),
            registration_digest: registration_receipt.exact_document_digest.as_str(),
        },
        &prepared,
        "segment:wave5-g0-source-publication-0001",
        "public-fixture-wave5-g0-source-publication",
        committed_at,
        catalog_admission_id,
        env!("CARGO_PKG_VERSION"),
        None,
    )
    .map_err(|error| Wave5G0SourcePublicationError::Circulation(error.to_string()))?;

    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::BeforeSemanticFact,
    )?;
    let source_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:source")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let source_receipt = store.commit_wave5_c0_source_occurrence_v1(
        &circulation.catalog_receipt_bytes,
        &source_context,
    )?;
    inject(fault, Wave5G0SourcePublicationFaultPoint::AfterSemanticFact)?;
    let source = store
        .load_wave5_source_occurrence_v1(&source_receipt.occurrence_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "source occurrence was absent immediately after commit",
        ))?;
    let hot_subject_count = source
        .occurrence
        .memberships
        .iter()
        .filter(|value| value.membership == CockpitV2MembershipKind::Hot)
        .count();
    let cold_control_subject_count = source
        .occurrence
        .memberships
        .iter()
        .filter(|value| value.membership == CockpitV2MembershipKind::ColdControl)
        .count();
    if hot_subject_count == 0 || cold_control_subject_count == 0 {
        return Err(Wave5G0SourcePublicationError::Invariant(
            "store did not derive a nonempty hot/control partition",
        ));
    }

    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::BeforePublicationPrepare,
    )?;
    let prepare_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:prepare")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let prepare_receipt =
        store.prepare_cockpit_v2_from_store_v1(&source_receipt.occurrence_id, &prepare_context)?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::AfterPublicationPrepare,
    )?;
    let preparation = store
        .load_cockpit_v2_preparation_v1(&prepare_receipt.occurrence_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 preparation was absent immediately after commit",
        ))?;
    let publication_id = CockpitPublicationId::new("cockpit-v2-wave5-g0-offline-0001")
        .map_err(|_| Wave5G0SourcePublicationError::Invariant("invalid static publication ID"))?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::BeforePublicationBody,
    )?;
    let publication_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:body")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let publication_receipt = store.commit_cockpit_v2_publication_v1(
        &prepare_receipt.occurrence_id,
        publication_id.clone(),
        None,
        &publication_context,
    )?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::AfterPublicationBody,
    )?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::BeforePublicationHead,
    )?;
    let head_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:head")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let head_receipt = store.append_cockpit_v2_head_v1(&publication_id, &head_context)?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::AfterPublicationHead,
    )?;
    let publication = store
        .load_cockpit_v2_publication_v1(&publication_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 body was absent immediately after commit",
        ))?;
    let head = store.load_cockpit_v2_head_v1(&publication_id)?.ok_or(
        Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 head was absent immediately after commit",
        ),
    )?;
    if preparation.commit_seq >= publication.commit_seq
        || publication.commit_seq >= head.commit_seq
        || publication_receipt.commit_seq() != publication.commit_seq
        || head_receipt.commit_seq != head.commit_seq
    {
        return Err(Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 prepare/body/head commit order is not strict",
        ));
    }

    let (act_bytes, episode_bytes) = memory_fixture(&publication)?;
    inject(fault, Wave5G0SourcePublicationFaultPoint::BeforeMemoryAct)?;
    let act_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:memory-act")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let act_receipt = store.commit_scientific_memory_occurrence_v1(&act_bytes, &act_context)?;
    inject(fault, Wave5G0SourcePublicationFaultPoint::AfterMemoryAct)?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::BeforeMemoryEpisode,
    )?;
    let episode_context = store.begin_wave5_commit(
        StableString::new("wave5:g0:source-publication:memory-episode")?,
        StableString::new(env!("CARGO_PKG_VERSION"))?,
    )?;
    let episode_receipt =
        store.commit_scientific_memory_occurrence_v1(&episode_bytes, &episode_context)?;
    inject(
        fault,
        Wave5G0SourcePublicationFaultPoint::AfterMemoryEpisode,
    )?;
    let act = store
        .load_scientific_memory_occurrence_v1(act_receipt.occurrence_id())?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "memory act was absent immediately after commit",
        ))?;
    let episode = store
        .load_scientific_memory_occurrence_v1(episode_receipt.occurrence_id())?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "memory episode was absent immediately after commit",
        ))?;
    if head.commit_seq >= act.commit_seq
        || act.commit_seq >= episode.commit_seq
        || act_receipt.queue_generation() != act.queue_generation
        || episode_receipt.queue_generation() != episode.queue_generation
        || act.queue_generation.checked_add(1) != Some(episode.queue_generation)
    {
        return Err(Wave5G0SourcePublicationError::Invariant(
            "memory act/episode commit or queue order is not strict",
        ));
    }
    drop(store);

    let reopened = SqliteStore::open(config(state)?, StoreMode::ReadOnly)?;
    let reopened_source = reopened
        .load_wave5_source_occurrence_v1(&source_receipt.occurrence_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "source occurrence was absent after restart",
        ))?;
    let reopened_preparation = reopened
        .load_cockpit_v2_preparation_v1(&prepare_receipt.occurrence_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 preparation was absent after restart",
        ))?;
    let reopened_publication = reopened
        .load_cockpit_v2_publication_v1(&publication_id)?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "Cockpit V2 body was absent after restart",
        ))?;
    let reopened_head = reopened.load_cockpit_v2_head_v1(&publication_id)?.ok_or(
        Wave5G0SourcePublicationError::Invariant("Cockpit V2 head was absent after restart"),
    )?;
    let reopened_act = reopened
        .load_scientific_memory_occurrence_v1(act_receipt.occurrence_id())?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "memory act was absent after restart",
        ))?;
    let reopened_episode = reopened
        .load_scientific_memory_occurrence_v1(episode_receipt.occurrence_id())?
        .ok_or(Wave5G0SourcePublicationError::Invariant(
            "memory episode was absent after restart",
        ))?;
    if reopened_source != source
        || reopened_preparation != preparation
        || reopened_publication != publication
        || reopened_head != head
        || reopened_act != act
        || reopened_episode != episode
    {
        return Err(Wave5G0SourcePublicationError::Invariant(
            "restart changed source/publication exact truth",
        ));
    }

    Ok(Wave5G0SourcePublicationReport {
        contract: "joshi.wave5.g0_source_publication_readiness",
        schema_version: 1,
        authority: AUTHORITY,
        status: "useful_partial",
        catalog_schema: registration_receipt.catalog_schema.to_string(),
        run_registration_id: run_id.to_string(),
        run_registration_digest: registration_receipt.exact_document_digest.to_string(),
        catalog_admission_id: catalog_admission_id.into(),
        selection_digest: Sha256Digest::of_bytes(OFFLINE_SELECTION_FILE).to_string(),
        source_occurrence_id: source_receipt.occurrence_id.to_string(),
        source_descriptor_digest: source.descriptor_digest.to_string(),
        source_fact_count: source.occurrence.facts.len(),
        eligible_subject_count: source.occurrence.eligible_subjects.len(),
        hot_subject_count,
        cold_control_subject_count,
        preparation_id: preparation.preparation_id.to_string(),
        publication_id: publication_id.to_string(),
        publication_digest: publication_receipt.publication_digest().to_string(),
        publication_bytes_digest: publication_receipt.publication_bytes_digest().to_string(),
        head_digest: head.head_digest.to_string(),
        memory_act_id: act_receipt.occurrence_id().to_string(),
        memory_act_digest: act_receipt.occurrence_digest().to_string(),
        memory_episode_id: episode_receipt.occurrence_id().to_string(),
        memory_episode_digest: episode_receipt.occurrence_digest().to_string(),
        memory_queue_through: episode_receipt.queue_generation(),
        source_semantics_closed: true,
        publication_prepare_body_head_closed: true,
        partial_memory_chain_closed: true,
        restart_reverified: true,
        full_offline_fault_walk: false,
        provider_io: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn memory_fixture(
    publication: &joshi_store::StoredCockpitV2Publication,
) -> Result<(Vec<u8>, Vec<u8>), Wave5G0SourcePublicationError> {
    let scene = SceneRef {
        scene_id: memory_value(SceneId::new(
            publication.publication.publication_id.to_string(),
        ))?,
        scene_digest: memory_value(MemoryDigest::new(
            publication.publication.publication_digest.to_string(),
        ))?,
        catalog_cutoff: memory_value(CatalogCommitSeq::new(publication.commit_seq.get()))?,
    };
    let act = MemoryOccurrence::OperatorAct(OperatorAct {
        act_id: memory_value(ActId::new("g0-act-0001"))?,
        session_id: memory_value(SessionId::new("g0-session-0001"))?,
        occurred_at: memory_value(LogicalSessionTick::new(12))?,
        scene: SceneBinding::Committed(scene.clone()),
        presentation: PresentationBinding::Gap(PresentationGap {
            gap_id: "g0-presentation-gap-0001".into(),
            scene: Some(scene),
            reason: PresentationGapReason::NotMounted,
            detected_at: memory_value(LogicalSessionTick::new(11))?,
        }),
        kind: ActKind::Mark,
        subject: Some("MintA".into()),
        assertion: None,
    });
    let episode = MemoryOccurrence::Episode(Episode {
        episode_id: memory_value(EpisodeId::new("g0-episode-0001"))?,
        session_id: memory_value(SessionId::new("g0-session-0001"))?,
        act_ids: vec![memory_value(ActId::new("g0-act-0001"))?],
        decision_cutoff: memory_value(LogicalSessionTick::new(20))?,
        started_at: memory_value(LogicalSessionTick::new(12))?,
        ended_at: Some(memory_value(LogicalSessionTick::new(20))?),
        completeness: EpisodeCompleteness::Partial,
        segments: vec![
            EpisodeSegment {
                segment_id: memory_value(SegmentId::new("g0-segment-flat-watch"))?,
                start_at: memory_value(LogicalSessionTick::new(12))?,
                end_at: Some(memory_value(LogicalSessionTick::new(16))?),
                path: EpisodePath::FlatWatch,
                effect: EffectStatus::Unknown {
                    reason: "manual effect not witnessed".into(),
                },
                lot: LotAssociation::Unresolved {
                    reason: "no lot association".into(),
                },
            },
            EpisodeSegment {
                segment_id: memory_value(SegmentId::new("g0-segment-no-trade"))?,
                start_at: memory_value(LogicalSessionTick::new(16))?,
                end_at: Some(memory_value(LogicalSessionTick::new(20))?),
                path: EpisodePath::NoTrade,
                effect: EffectStatus::NotApplicableByNoTrade,
                lot: LotAssociation::NotApplicable,
            },
        ],
    });
    Ok((serde_json::to_vec(&act)?, serde_json::to_vec(&episode)?))
}

fn memory_value<T>(value: Result<T, String>) -> Result<T, Wave5G0SourcePublicationError> {
    value.map_err(Wave5G0SourcePublicationError::MemoryFixture)
}

fn inject(
    requested: Option<Wave5G0SourcePublicationFaultPoint>,
    current: Wave5G0SourcePublicationFaultPoint,
) -> Result<(), Wave5G0SourcePublicationError> {
    if requested == Some(current) {
        Err(Wave5G0SourcePublicationError::Injected(current))
    } else {
        Ok(())
    }
}

#[derive(Debug, Error)]
pub enum Wave5G0SourcePublicationError {
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Pump(#[from] joshi_pump_adapter::PumpAdapterError),
    #[error(transparent)]
    Spool(#[from] joshi_spool::SpoolError),
    #[error(transparent)]
    Wire(#[from] WireStringError),
    #[error(transparent)]
    Readiness(#[from] crate::wave5_readiness::Wave5ReadinessError),
    #[error("Wave 5 G0 circulation failed: {0}")]
    Circulation(String),
    #[error("invalid static Wave 5 G0 memory fixture: {0}")]
    MemoryFixture(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("injected Wave 5 G0 source/publication interruption at {0:?}")]
    Injected(Wave5G0SourcePublicationFaultPoint),
    #[error("Wave 5 G0 source/publication invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_source_and_publication_reopen_without_promoting_root_or_live() {
        let state = tempfile::tempdir().expect("temporary G0 component state");
        let report = run_wave5_g0_source_publication(state.path()).expect("G0 component witness");
        assert_eq!(report.source_fact_count, 2);
        assert_eq!(report.eligible_subject_count, 2);
        assert_eq!(report.hot_subject_count, 1);
        assert_eq!(report.cold_control_subject_count, 1);
        assert!(report.source_semantics_closed);
        assert!(report.publication_prepare_body_head_closed);
        assert!(report.partial_memory_chain_closed);
        assert_eq!(report.memory_queue_through, 2);
        assert!(report.restart_reverified);
        assert!(!report.full_offline_fault_walk);
        assert!(!report.provider_io);
        assert!(!report.product_qualified);
        assert!(!report.live_qualified);
        let retry =
            run_wave5_g0_source_publication(state.path()).expect("idempotent G0 component retry");
        assert_eq!(retry, report);
    }

    #[test]
    fn every_source_publication_prefix_resumes_to_one_exact_chain() {
        let points = [
            Wave5G0SourcePublicationFaultPoint::BeforeSemanticFact,
            Wave5G0SourcePublicationFaultPoint::AfterSemanticFact,
            Wave5G0SourcePublicationFaultPoint::BeforePublicationPrepare,
            Wave5G0SourcePublicationFaultPoint::AfterPublicationPrepare,
            Wave5G0SourcePublicationFaultPoint::BeforePublicationBody,
            Wave5G0SourcePublicationFaultPoint::AfterPublicationBody,
            Wave5G0SourcePublicationFaultPoint::BeforePublicationHead,
            Wave5G0SourcePublicationFaultPoint::AfterPublicationHead,
            Wave5G0SourcePublicationFaultPoint::BeforeMemoryAct,
            Wave5G0SourcePublicationFaultPoint::AfterMemoryAct,
            Wave5G0SourcePublicationFaultPoint::BeforeMemoryEpisode,
            Wave5G0SourcePublicationFaultPoint::AfterMemoryEpisode,
        ];
        for point in points {
            let state = tempfile::tempdir().expect("temporary G0 fault state");
            assert!(matches!(
                run_wave5_g0_source_publication_with_fault(state.path(), Some(point)),
                Err(Wave5G0SourcePublicationError::Injected(actual)) if actual == point
            ));
            let recovered =
                run_wave5_g0_source_publication(state.path()).expect("exact fault recovery");
            let retry =
                run_wave5_g0_source_publication(state.path()).expect("exact recovered retry");
            assert_eq!(retry, recovered);
            assert!(recovered.restart_reverified);
            assert!(!recovered.full_offline_fault_walk);
        }
    }
}
