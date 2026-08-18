use joshi_domain::{StableString, WireU64};
use joshi_operational_status::{
    AUTHORITY_CEILING, BACKFILL_RESULT_CONTRACT, BackfillLimitsV1, BackfillOutcomeV1,
    BackfillPlanRequestV1, BackfillResultV1, BackfillStrategyV1, CrossSourceProofV1,
    DURABLE_PROGRESS_CONTRACT, DegradationCause, DegradationRecordV1, DegradationStage,
    DurableProgressKind, DurableProgressState, DurableProgressV1, HEALTH_CONTRACT, MetricBatchV1,
    OperationalHealthV1, OperationalQualificationV1, OperationalStatusViewV1,
    RESOURCE_SAMPLE_CONTRACT, RecoveryRecordV1, RecoveryState, ResourceKind, ResourceSampleV1,
    STATUS_TRANSITION_CONTRACT, SourceFamily, StatusJournal, StatusTransitionV1, TransitionHeadV1,
    decode_health_v1, plan_backfill,
};

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable fixture value")
}

fn health() -> OperationalHealthV1 {
    decode_health_v1(include_bytes!(
        "../../../fixtures/operational-status/health_degraded.json"
    ))
    .expect("valid health fixture")
}

#[test]
fn health_fixture_is_strict_and_metrics_have_only_finite_labels() {
    let health = health();
    let metrics = MetricBatchV1::from_health(&health, HEALTH_CONTRACT).expect("finite metrics");
    metrics.validate().expect("valid metrics");
    let encoded = serde_json::to_string(&metrics).expect("metric JSON");
    assert!(!encoded.contains("generationId"));
    assert!(!encoded.contains("gapId"));
    assert!(!encoded.contains("scopeId"));
    assert!(!encoded.contains("source-generation:"));

    let mut unknown =
        include_bytes!("../../../fixtures/operational-status/health_degraded.json").to_vec();
    let insertion = br#", "unexpectedHealthField": true"#;
    let position = unknown.len() - 2;
    unknown.splice(position..position, insertion.iter().copied());
    assert!(decode_health_v1(&unknown).is_err());
}

#[test]
fn saturation_cannot_restart_without_preservation_and_durable_gap() {
    let mut value = health();
    value.evidence_queue.saturation.durable_scoped_gap_recorded = false;
    assert!(value.validate(HEALTH_CONTRACT).is_err());
}

#[test]
fn pump_portal_same_source_backfill_is_refused_but_cross_source_plan_is_typed() {
    let health = health();
    let gap = health.coverage.open_gaps[0].clone();
    let positive_limits = BackfillLimitsV1 {
        max_requests: WireU64::new(10),
        max_pages: WireU64::new(2),
        max_bytes: WireU64::new(1_000_000),
        max_provider_credits: WireU64::new(10),
        deadline_ms: WireU64::new(60_000),
    };
    let invalid = BackfillPlanRequestV1 {
        plan_id: stable("backfill-plan:pump:same-source"),
        policy_id: stable("backfill-policy:s0"),
        planned_at: health.observed_at,
        gap: gap.clone(),
        strategy: BackfillStrategyV1::SameSourcePagination {
            source_family: SourceFamily::PumpPortalWebsocket,
            lower: gap.lower.clone(),
            upper: gap.upper.clone().unwrap_or_else(|| gap.lower.clone()),
        },
        limits: positive_limits.clone(),
    };
    assert!(plan_backfill(invalid).is_err());

    let valid = BackfillPlanRequestV1 {
        plan_id: stable("backfill-plan:pump:cross-source"),
        policy_id: stable("backfill-policy:s0"),
        planned_at: health.observed_at,
        gap: gap.clone(),
        strategy: BackfillStrategyV1::CrossSourceReconstruction {
            reconstruction_source: SourceFamily::HeliusHttp,
            reconstruction_contract: stable("pump-portal-gap-helius-reconstruction/v1"),
            lower: gap.lower.clone(),
            upper: gap.upper.clone().unwrap_or_else(|| gap.lower.clone()),
        },
        limits: positive_limits,
    };
    let plan = plan_backfill(valid).expect("cross-source reconstruction plan");
    assert_eq!(plan.authority, AUTHORITY_CEILING);
    assert!(plan.requires_exact_evidence_commit);
    assert!(plan.requires_append_only_recovery_record);

    let result = BackfillResultV1 {
        contract: BACKFILL_RESULT_CONTRACT.to_owned(),
        result_id: stable("backfill-result:pump:cross-source"),
        plan_id: plan.plan_id.clone(),
        gap_id: plan.gap_id.clone(),
        original_source: plan.original_source,
        authority: AUTHORITY_CEILING.to_owned(),
        completed_at: health.observed_at,
        outcome: BackfillOutcomeV1::CrossSourceReconstructed {
            proof: CrossSourceProofV1 {
                reconstruction_source: SourceFamily::HeliusHttp,
                reconstruction_contract: stable("pump-portal-gap-helius-reconstruction/v1"),
                evidence_receipt: health
                    .catalog
                    .last_closed_receipt
                    .expect("catalog receipt fixture"),
                observation_ids: vec![stable("observation:cross-source:1")],
                reconstruction_record_id: stable("reconstruction:pump-gap:1"),
                reconstructed_through: gap.lower,
                original_gap_remains_open: true,
            },
        },
    };
    result
        .validate_against_plan(&plan)
        .expect("bounded reconstruction result");
}

#[test]
fn cross_source_reconstruction_cannot_claim_original_gap_closed() {
    let health = health();
    let gap = health.coverage.open_gaps[0].clone();
    let result = BackfillResultV1 {
        contract: BACKFILL_RESULT_CONTRACT.to_owned(),
        result_id: stable("backfill-result:invalid-closure"),
        plan_id: stable("backfill-plan:invalid-closure"),
        gap_id: gap.gap_id,
        original_source: SourceFamily::PumpPortalWebsocket,
        authority: AUTHORITY_CEILING.to_owned(),
        completed_at: health.observed_at,
        outcome: BackfillOutcomeV1::CrossSourceReconstructed {
            proof: CrossSourceProofV1 {
                reconstruction_source: SourceFamily::HeliusHttp,
                reconstruction_contract: stable("reconstruction/v1"),
                evidence_receipt: health
                    .catalog
                    .last_closed_receipt
                    .expect("catalog receipt fixture"),
                observation_ids: vec![stable("observation:1")],
                reconstruction_record_id: stable("reconstruction:1"),
                reconstructed_through: gap.lower,
                original_gap_remains_open: false,
            },
        },
    };
    assert!(result.validate().is_err());
}

fn at(value: &str) -> joshi_domain::UtcTimestamp {
    value.parse().expect("timestamp")
}

fn head(id: &str, ordinal: u64, predecessor: Option<&str>) -> TransitionHeadV1 {
    TransitionHeadV1 {
        contract: STATUS_TRANSITION_CONTRACT.to_owned(),
        record_id: stable(id),
        ordinal: WireU64::new(ordinal),
        predecessor_record_id: predecessor.map(stable),
        recorded_at: at("2026-08-17T12:00:00.000000Z"),
        scope_id: stable("scope:collector"),
        source_family: Some(SourceFamily::HeliusHttp),
        authority: AUTHORITY_CEILING.to_owned(),
    }
}

#[test]
fn durable_progress_and_resource_samples_remain_distinct() {
    let progress = DurableProgressV1 {
        contract: DURABLE_PROGRESS_CONTRACT.to_owned(),
        progress_id: stable("receipt:1"),
        kind: DurableProgressKind::Receipt,
        scope_id: stable("scope:collector"),
        source_family: Some(SourceFamily::HeliusHttp),
        state: DurableProgressState::Committed,
        durable_commit: Some(joshi_domain::CommitSeq::new(4)),
        content_digest: Some(stable("sha256:receipt")),
        observed_at: at("2026-08-17T12:00:00.000000Z"),
        authority: AUTHORITY_CEILING.to_owned(),
    };
    progress.validate().expect("durable receipt");
    let sample = ResourceSampleV1 {
        contract: RESOURCE_SAMPLE_CONTRACT.to_owned(),
        sample_id: stable("sample:cpu:1"),
        kind: ResourceKind::CpuMillicores,
        observed: WireU64::new(20),
        limit_or_floor: WireU64::new(100),
        status: joshi_operational_status::StatusClass::Ready,
        sampled_at: at("2026-08-17T12:00:00.000000Z"),
        sample_clock_id: stable("clock:host:1"),
    };
    sample.validate().expect("resource sample");
    let encoded = serde_json::to_string(&sample).expect("sample json");
    assert!(!encoded.contains("commit") && encoded.contains("sampleClockId"));
}

#[test]
fn constructors_fix_read_only_authority_and_keep_samples_non_durable() {
    let progress = DurableProgressV1::from_store_resolved(
        stable("publication:1"),
        DurableProgressKind::Publication,
        stable("scope:glass"),
        None,
        DurableProgressState::Committed,
        Some(joshi_domain::CommitSeq::new(7)),
        Some(stable("sha256:publication")),
        at("2026-08-18T12:00:00.000000Z"),
    )
    .expect("store-resolved progress");
    assert_eq!(progress.authority, AUTHORITY_CEILING);
    assert_eq!(
        progress.qualification(),
        OperationalQualificationV1::Unverified
    );

    let sample = ResourceSampleV1::new(
        stable("sample:cpu:1"),
        ResourceKind::CpuMillicores,
        WireU64::new(10),
        WireU64::new(100),
        joshi_operational_status::StatusClass::Ready,
        at("2026-08-18T12:00:00.000000Z"),
        stable("clock:host:1"),
    )
    .expect("host sample");
    assert!(
        !serde_json::to_string(&sample)
            .expect("sample JSON")
            .contains("authority")
    );
    assert!(
        DurableProgressV1::from_store_resolved(
            stable("receipt:pending"),
            DurableProgressKind::Receipt,
            stable("scope:collector"),
            None,
            DurableProgressState::Pending,
            None,
            Some(stable("sha256:not-durable-yet")),
            at("2026-08-18T12:00:00.000000Z"),
        )
        .is_err()
    );
}

#[test]
fn recovery_evidence_requires_closure_kind_state_and_matching_context() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:evidence:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let recovery = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:evidence:2", 2, Some("transition:evidence:1")),
        degradation_record_id: stable("transition:evidence:1"),
        state: RecoveryState::UnverifiedSemantic,
        evidence_progress_id: Some(stable("gap:open")),
    });
    let gap = DurableProgressV1::from_store_resolved(
        stable("gap:open"),
        DurableProgressKind::Gap,
        stable("scope:collector"),
        Some(SourceFamily::HeliusHttp),
        DurableProgressState::Open,
        Some(joshi_domain::CommitSeq::new(3)),
        None,
        at("2026-08-17T12:00:00.000000Z"),
    )
    .expect("open gap progress");
    assert!(
        OperationalStatusViewV1::new(
            at("2026-08-17T12:00:00.000000Z"),
            vec![gap],
            Vec::new(),
            vec![degradation.clone(), recovery.clone()],
        )
        .is_err()
    );
}

#[test]
fn sampled_resource_threshold_cannot_claim_ready() {
    assert!(
        ResourceSampleV1::new(
            stable("sample:cpu:breach"),
            ResourceKind::CpuMillicores,
            WireU64::new(101),
            WireU64::new(100),
            joshi_operational_status::StatusClass::Ready,
            at("2026-08-18T12:00:00.000000Z"),
            stable("clock:host:1"),
        )
        .is_err()
    );
}

#[test]
fn status_view_allows_multiple_durable_occurrences_in_one_scope() {
    let first = DurableProgressV1::from_store_resolved(
        stable("receipt:1"),
        DurableProgressKind::Receipt,
        stable("scope:collector"),
        Some(SourceFamily::HeliusHttp),
        DurableProgressState::Committed,
        Some(joshi_domain::CommitSeq::new(1)),
        Some(stable("sha256:receipt-1")),
        at("2026-08-18T12:00:00.000000Z"),
    )
    .expect("first receipt");
    let second = DurableProgressV1::from_store_resolved(
        stable("receipt:2"),
        DurableProgressKind::Receipt,
        stable("scope:collector"),
        Some(SourceFamily::HeliusHttp),
        DurableProgressState::Committed,
        Some(joshi_domain::CommitSeq::new(2)),
        Some(stable("sha256:receipt-2")),
        at("2026-08-18T12:00:01.000000Z"),
    )
    .expect("second receipt");
    OperationalStatusViewV1::new(
        at("2026-08-18T12:00:01.000000Z"),
        vec![first, second],
        Vec::new(),
        Vec::new(),
    )
    .expect("successive receipts share a scope");
}

#[test]
fn status_view_fixture_reconstructs_without_promoting_resource_samples() {
    let view: joshi_operational_status::OperationalStatusViewV1 = serde_json::from_slice(
        include_bytes!("../../../fixtures/operational-status/status_view_durable_and_sampled.json"),
    )
    .expect("status view fixture");
    view.validate().expect("status view validates");
    assert_eq!(
        view.qualification(),
        OperationalQualificationV1::Unverified,
        "public DTOs cannot qualify operational recovery",
    );
    assert_eq!(view.durable_progress.len(), 3);
    assert_eq!(view.resource_samples.len(), 2);
    assert!(view.resource_samples.iter().all(|sample| {
        !serde_json::to_string(sample)
            .expect("sample")
            .contains("commit")
    }));
}

#[test]
fn status_view_requires_recovery_evidence_to_resolve_durable_progress() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let recovery = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:2", 2, Some("transition:1")),
        degradation_record_id: stable("transition:1"),
        state: RecoveryState::UnverifiedSemantic,
        evidence_progress_id: Some(stable("receipt:missing")),
    });
    let view = OperationalStatusViewV1::new(
        at("2026-08-17T12:00:00.000000Z"),
        Vec::new(),
        Vec::new(),
        vec![degradation, recovery],
    );
    assert!(view.is_err());
}

#[test]
fn journal_allows_only_terminal_recovery_records() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:terminal:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let pending = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:terminal:2", 2, Some("transition:terminal:1")),
        degradation_record_id: stable("transition:terminal:1"),
        state: RecoveryState::Pending,
        evidence_progress_id: None,
    });
    assert!(StatusJournal::new(vec![degradation, pending]).is_err());
}

#[test]
fn status_view_rejects_transition_recorded_after_view_clock() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:future:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let recovery = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:future:2", 2, Some("transition:future:1")),
        degradation_record_id: stable("transition:future:1"),
        state: RecoveryState::BlockedUnrecoverable,
        evidence_progress_id: None,
    });
    assert!(
        OperationalStatusViewV1::new(
            at("2026-08-17T11:59:00.000000Z"),
            Vec::new(),
            Vec::new(),
            vec![degradation.clone(), recovery.clone()],
        )
        .is_err()
    );
}

#[test]
fn recovery_refuses_future_or_scope_mismatched_evidence() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let recovery = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:2", 2, Some("transition:1")),
        degradation_record_id: stable("transition:1"),
        state: RecoveryState::UnverifiedSemantic,
        evidence_progress_id: Some(stable("receipt:scope-mismatch")),
    });
    let progress = DurableProgressV1::from_store_resolved(
        stable("receipt:scope-mismatch"),
        DurableProgressKind::Receipt,
        stable("scope:other"),
        Some(SourceFamily::HeliusHttp),
        DurableProgressState::Committed,
        Some(joshi_domain::CommitSeq::new(3)),
        Some(stable("sha256:receipt")),
        at("2026-08-17T11:59:59.000000Z"),
    )
    .expect("progress");
    assert!(
        OperationalStatusViewV1::new(
            at("2026-08-17T12:00:00.000000Z"),
            vec![progress.clone()],
            Vec::new(),
            vec![degradation.clone(), recovery.clone()],
        )
        .is_err()
    );
    let mut stale = progress;
    stale.scope_id = stable("scope:collector");
    assert!(
        OperationalStatusViewV1::new(
            at("2026-08-18T12:00:00.000000Z"),
            vec![stale],
            Vec::new(),
            vec![degradation, recovery],
        )
        .is_err()
    );
}

#[test]
fn recovery_refuses_evidence_that_predates_degradation() {
    let degradation = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:stale:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let recovery = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:stale:2", 2, Some("transition:stale:1")),
        degradation_record_id: stable("transition:stale:1"),
        state: RecoveryState::UnverifiedSemantic,
        evidence_progress_id: Some(stable("receipt:stale")),
    });
    let progress = DurableProgressV1::from_store_resolved(
        stable("receipt:stale"),
        DurableProgressKind::Receipt,
        stable("scope:collector"),
        Some(SourceFamily::HeliusHttp),
        DurableProgressState::Committed,
        Some(joshi_domain::CommitSeq::new(3)),
        Some(stable("sha256:receipt-stale")),
        at("2026-08-17T11:59:59.000000Z"),
    )
    .expect("stale progress");
    assert!(
        OperationalStatusViewV1::new(
            at("2026-08-17T12:00:00.000000Z"),
            vec![progress],
            Vec::new(),
            vec![degradation, recovery],
        )
        .is_err()
    );
}

#[test]
fn status_journal_restarts_exactly_and_refuses_stale_or_conflicting_records() {
    let first = StatusTransitionV1::Degradation(DegradationRecordV1 {
        head: head("transition:1", 1, None),
        stage: DegradationStage::CensusOnly,
        causes: vec![DegradationCause::QueuePressure],
    });
    let second = StatusTransitionV1::Recovery(RecoveryRecordV1 {
        head: head("transition:2", 2, Some("transition:1")),
        degradation_record_id: stable("transition:1"),
        state: RecoveryState::UnverifiedSemantic,
        evidence_progress_id: Some(stable("receipt:recovery")),
    });
    let journal = StatusJournal::new(vec![first.clone(), second.clone()]).expect("journal");
    let restarted = StatusJournal::new(journal.records().to_vec()).expect("restart");
    assert_eq!(journal, restarted);
    let duplicate = StatusJournal::new(vec![first.clone(), first]).expect_err("duplicate");
    assert!(duplicate.to_string().contains("status"));
    let unclosed = StatusJournal::new(vec![second]).expect_err("missing degradation");
    assert!(unclosed.to_string().contains("status"));
}
