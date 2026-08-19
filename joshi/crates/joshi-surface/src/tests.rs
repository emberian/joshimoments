use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use sha2::{Digest, Sha256};

use super::*;

const PROFILE_FIXTURE: &str =
    include_str!("../../../fixtures/surface/daily_use_surface_profile_v1.json");

fn s(value: &str) -> StableString {
    StableString::new(value).unwrap()
}
fn t(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).unwrap()
}
fn d(fill: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).unwrap()
}

fn profile() -> DailyUseSurfaceProfileV1 {
    let task = SurfaceTaskV1 {
        task_id: s("open-launch"),
        name: s("open launch"),
        critical: true,
        accessibility: AccessibilityEvidence {
            keyboard: true,
            large_target: true,
            screen_reader: true,
            reduced_motion: true,
            evidence_id: s("a11y-1"),
        },
    };
    let mut value = DailyUseSurfaceProfileV1 {
        contract: s(SURFACE_CONTRACT),
        schema_version: SURFACE_SCHEMA_VERSION,
        profile_id: s("daily-1"),
        profile_version: WireU64::new(1),
        ember_approval_id: s("ember-approval-1"),
        approved_at: t("2026-08-17T12:00:00.000000Z"),
        surfaces: vec![
            SurfaceEntryV1 {
                surface_id: s("launch"),
                kind: SurfaceKind::LaunchNew,
                critical: true,
                route: s("/launch"),
                source: s("pump"),
                personalization: s("none"),
                ordering: s("newest"),
                pagination: s("cursor"),
                cadence: s("60s"),
                fields_media: vec![s("mint"), s("name")],
                field_status: BTreeMap::from([
                    (s("mint"), SurfaceStatus::PromotedContinuous),
                    (s("name"), SurfaceStatus::PromotedContinuous),
                ]),
                status: SurfaceStatus::PromotedContinuous,
                approval: None,
                tasks: vec![task],
            },
            SurfaceEntryV1 {
                surface_id: s("chain-lifecycle"),
                kind: SurfaceKind::LifecycleMigrationPools,
                critical: true,
                route: s("/chain"),
                source: s("solana"),
                personalization: s("none"),
                ordering: s("slot"),
                pagination: s("none"),
                cadence: s("event"),
                fields_media: vec![s("migration")],
                field_status: BTreeMap::from([(
                    s("migration"),
                    SurfaceStatus::PublicChainAlternativeNotProductParity,
                )]),
                status: SurfaceStatus::PublicChainAlternativeNotProductParity,
                approval: None,
                tasks: vec![SurfaceTaskV1 {
                    task_id: s("inspect-lifecycle"),
                    name: s("inspect lifecycle"),
                    critical: true,
                    accessibility: AccessibilityEvidence {
                        keyboard: true,
                        large_target: true,
                        screen_reader: true,
                        reduced_motion: true,
                        evidence_id: s("a11y-2"),
                    },
                }],
            },
        ],
        profile_digest: d('0'),
        authority: s(READ_ONLY_AUTHORITY),
    };
    value.profile_digest = value.computed_digest().unwrap();
    value
}

fn universe(cutoff: UtcTimestamp) -> DeclaredObservedUniverseV1 {
    let subjects = vec![s("mint-a"), s("mint-b"), s("mint-c")];
    let mut hash = Sha256::new();
    hash.update(serde_json::to_vec(&subjects).unwrap());
    DeclaredObservedUniverseV1 {
        universe_id: s("census-1"),
        surface_version: WireU64::new(1),
        cutoff,
        eligible_count: WireU64::new(3),
        eligible_subjects: subjects,
        eligible_digest: ValueDigest::new(format!("sha256:{:x}", hash.finalize())).unwrap(),
        closed: true,
        sample_only: false,
    }
}

fn observation(
    id: &str,
    subject: &str,
    known_at: &str,
    membership: SurfaceMembership,
    order: &str,
) -> SurfaceObservationV1 {
    SurfaceObservationV1 {
        event_id: s(id),
        subject: s(subject),
        observed_at: t(known_at),
        known_at: t(known_at),
        supersedes_event_id: None,
        surface_id: s("launch"),
        source_id: s("pump"),
        memberships: vec![membership],
        fields: BTreeMap::from([(
            s("name"),
            FieldState::Covered {
                observed_at: t(known_at),
            },
        )]),
        order_key: s(order),
        evidence_digest: d('2'),
    }
}

#[test]
fn profile_keeps_critical_gaps_visible_without_parity_credit() {
    let value = profile();
    value.validate().unwrap();
    assert_eq!(value.critical_count(), 2);
    assert!(!value.surfaces[1].status.counts_product_parity());
}

#[test]
fn full_and_incremental_cuts_are_identical_and_late_correction_does_not_leak() {
    let p = profile();
    let cut1 = t("2026-08-17T12:00:00.000000Z");
    let cut2 = t("2026-08-17T13:00:00.000000Z");
    let values = vec![
        observation(
            "e1",
            "mint-a",
            "2026-08-17T11:00:00.000000Z",
            SurfaceMembership::Census,
            "001",
        ),
        observation(
            "e2",
            "mint-b",
            "2026-08-17T11:30:00.000000Z",
            SurfaceMembership::DenominatorOnly,
            "002",
        ),
        observation(
            "e3",
            "mint-c",
            "2026-08-17T12:30:00.000000Z",
            SurfaceMembership::Census,
            "003",
        ),
    ];
    let first = SurfaceReducer::reduce(&p, universe(cut1), &values, cut1, 10).unwrap();
    assert_eq!(first.rendered.len(), 1);
    assert_eq!(first.omissions.len(), 2);
    let late = SurfaceReducer::reduce(&p, universe(cut2), &values, cut2, 10).unwrap();
    let incremental =
        SurfaceReducer::reduce_incremental(&first, &p, universe(cut2), &values, cut2, 10).unwrap();
    assert_eq!(late, incremental);
    assert_eq!(
        late.canonical_bytes().unwrap(),
        incremental.canonical_bytes().unwrap()
    );
    assert_eq!(
        first.reducer_digest,
        SurfaceReducer::reduce(&p, universe(cut1), &values, cut1, 10)
            .unwrap()
            .reducer_digest
    );
}

#[test]
fn qualification_is_independent_and_requires_exact_ack() {
    let p = profile();
    let ack = |id: &str| EmberUseAcknowledgmentV1 {
        acknowledgment_id: s(&format!("ack-{id}")),
        build_digest: d('3'),
        session_id: s(id),
        profile_digest: p.profile_digest.clone(),
        reduced_navigation_burden: true,
        preserved_orientation: true,
        worth_reopening: true,
        acknowledged_at: t("2026-08-17T12:00:00.000000Z"),
    };
    let tasks = BTreeSet::from([s("open-launch")]);
    let one = EmberUseSessionV1 {
        session_id: s("session-1"),
        build_digest: d('3'),
        profile_digest: p.profile_digest.clone(),
        supported_critical_tasks: tasks.clone(),
        switched_away_for_parity_gap: false,
        switch_reason: None,
        fixture_rendered: true,
        live_read_only: true,
        evidence: vec![
            QualificationEvidenceRefV1 {
                contract: s("joshi.surface.evidence_receipt.v1"),
                kind: QualificationEvidenceKind::FixtureRender,
                evidence_id: s("fixture-receipt"),
                evidence_digest: d('4'),
            },
            QualificationEvidenceRefV1 {
                contract: s("joshi.surface.evidence_receipt.v1"),
                kind: QualificationEvidenceKind::LiveReadOnly,
                evidence_id: s("live-receipt"),
                evidence_digest: d('5'),
            },
        ],
        acknowledgment: ack("session-1"),
    };
    let two = EmberUseSessionV1 {
        session_id: s("session-2"),
        build_digest: d('3'),
        profile_digest: p.profile_digest.clone(),
        supported_critical_tasks: tasks,
        switched_away_for_parity_gap: false,
        switch_reason: None,
        fixture_rendered: false,
        live_read_only: true,
        evidence: vec![QualificationEvidenceRefV1 {
            contract: s("joshi.surface.evidence_receipt.v1"),
            kind: QualificationEvidenceKind::LiveReadOnly,
            evidence_id: s("live-receipt-2"),
            evidence_digest: d('6'),
        }],
        acknowledgment: ack("session-2"),
    };
    let result = qualify_cockpit(&p, &[one, two]).unwrap();
    assert!(result.capabilities.is_empty());
    assert!(!result.verified);
    assert_eq!(result.status.as_str(), "unqualified");
}

#[test]
fn strict_profile_bytes_reject_unknown_fields() {
    let bytes = profile().canonical_bytes().unwrap();
    let mut json: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    json.as_object_mut()
        .unwrap()
        .insert("surprise".to_owned(), serde_json::Value::Bool(true));
    assert!(parse_profile(&serde_json::to_vec(&json).unwrap()).is_err());
}

#[test]
fn canonical_profile_fixture_round_trips_exactly() {
    let parsed = parse_profile(PROFILE_FIXTURE.trim_end().as_bytes()).unwrap();
    assert_eq!(
        parsed.canonical_bytes().unwrap(),
        PROFILE_FIXTURE.trim_end().as_bytes()
    );
}

#[test]
fn strict_parsers_and_sample_universe_close_exact_bytes_and_denominator() {
    let p = profile();
    let mut padded_profile = vec![b' '];
    padded_profile.extend(p.canonical_bytes().unwrap());
    assert!(matches!(
        parse_profile(&padded_profile),
        Err(SurfaceError::DigestMismatch)
    ));

    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let cut = SurfaceReducer::reduce(&p, universe(cutoff), &[], cutoff, 10).unwrap();
    let mut padded_cut = vec![b' '];
    padded_cut.extend(cut.canonical_bytes().unwrap());
    assert!(matches!(
        parse_surface_cut(&padded_cut),
        Err(SurfaceError::DigestMismatch)
    ));

    let mut sample = universe(cutoff);
    sample.closed = false;
    sample.sample_only = true;
    sample.eligible_subjects.push(s("mint-c"));
    assert!(matches!(
        sample.validate(),
        Err(SurfaceError::UniverseNotClosed)
    ));
}

#[test]
fn stale_age_is_recomputed_at_the_exact_cutoff() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let mut stale = observation(
        "stale",
        "mint-a",
        "2026-08-17T11:00:00.000000Z",
        SurfaceMembership::Census,
        "001",
    );
    stale.fields.insert(
        s("name"),
        FieldState::Stale {
            observed_at: t("2026-08-17T11:00:00.000000Z"),
            age_seconds: WireU64::new(1),
        },
    );
    assert!(matches!(
        SurfaceReducer::reduce(&p, universe(cutoff), &[stale], cutoff, 10),
        Err(SurfaceError::Cutoff)
    ));
}

#[test]
fn adversarial_future_observation_and_open_universe_are_refused() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let mut future = observation(
        "future",
        "mint-a",
        "2026-08-17T12:00:00.000000Z",
        SurfaceMembership::Census,
        "001",
    );
    future.observed_at = t("2026-08-17T12:01:00.000000Z");
    assert!(SurfaceReducer::reduce(&p, universe(cutoff), &[future], cutoff, 10).is_err());
    let mut bad = universe(cutoff);
    bad.eligible_subjects.push(s("not-in-digest"));
    assert!(SurfaceReducer::reduce(&p, bad, &[], cutoff, 10).is_err());
    let empty = qualify_cockpit(&p, &[]).unwrap();
    assert!(empty.capabilities.is_empty());
}

#[test]
fn supersession_is_point_in_time_and_input_order_independent() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let mut correction = observation(
        "e2",
        "mint-a",
        "2026-08-17T11:30:00.000000Z",
        SurfaceMembership::Hot,
        "001",
    );
    correction.supersedes_event_id = Some(s("e1"));
    let original = observation(
        "e1",
        "mint-a",
        "2026-08-17T11:00:00.000000Z",
        SurfaceMembership::Census,
        "001",
    );
    let a = SurfaceReducer::reduce(
        &p,
        universe(cutoff),
        &[original.clone(), correction.clone()],
        cutoff,
        10,
    )
    .unwrap();
    let b =
        SurfaceReducer::reduce(&p, universe(cutoff), &[correction, original], cutoff, 10).unwrap();
    assert_eq!(a, b);
    assert_eq!(a.rendered[0].memberships, vec![SurfaceMembership::Hot]);
}

#[test]
fn profile_rejects_task_id_reuse_across_surfaces() {
    let mut p = profile();
    p.surfaces[1].tasks[0].task_id = s("open-launch");
    p.profile_digest = p.computed_digest().unwrap();
    assert!(matches!(p.validate(), Err(SurfaceError::DuplicateTask)));
}

#[test]
fn closed_cut_rejects_missing_or_extra_partition_subjects() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let values = vec![observation(
        "e1",
        "mint-a",
        "2026-08-17T11:00:00.000000Z",
        SurfaceMembership::Census,
        "001",
    )];
    let mut missing = SurfaceReducer::reduce(&p, universe(cutoff), &values, cutoff, 10).unwrap();
    missing.omissions.pop();
    missing.reducer_digest = missing.computed_reducer_digest().unwrap();
    assert!(matches!(
        missing.validate(),
        Err(SurfaceError::UniverseNotClosed)
    ));

    let mut extra = SurfaceReducer::reduce(&p, universe(cutoff), &values, cutoff, 10).unwrap();
    extra.omissions.push(SurfaceOmissionV1 {
        subject: s("mint-extra"),
        reason: s("not_observed_by_cutoff"),
        membership: SurfaceMembership::DenominatorOnly,
    });
    extra.omissions.sort_by(|a, b| a.subject.cmp(&b.subject));
    extra.reducer_digest = extra.computed_reducer_digest().unwrap();
    assert!(matches!(
        extra.validate(),
        Err(SurfaceError::UniverseNotClosed)
    ));
}

#[test]
fn source_states_keep_unknown_cells_per_absent_subject() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let cut = SurfaceReducer::reduce(&p, universe(cutoff), &[], cutoff, 10).unwrap();
    assert_eq!(cut.source_states.len(), 9);
    for subject in ["mint-b", "mint-c"] {
        let cells: Vec<_> = cut
            .source_states
            .iter()
            .filter(|cell| cell.subject.as_str() == subject)
            .collect();
        assert_eq!(cells.len(), 3);
        assert!(
            cells
                .iter()
                .all(|cell| matches!(cell.state, FieldState::Unknown { .. }))
        );
    }
    let mint_a_name = cut
        .source_states
        .iter()
        .find(|cell| cell.subject.as_str() == "mint-a" && cell.field.as_str() == "name")
        .unwrap();
    assert!(matches!(mint_a_name.state, FieldState::Unknown { .. }));
    let with_observation = SurfaceReducer::reduce(
        &p,
        universe(cutoff),
        &[observation(
            "observed",
            "mint-a",
            "2026-08-17T11:00:00.000000Z",
            SurfaceMembership::Census,
            "001",
        )],
        cutoff,
        10,
    )
    .unwrap();
    let covered = with_observation
        .source_states
        .iter()
        .find(|cell| cell.subject.as_str() == "mint-a" && cell.field.as_str() == "name")
        .unwrap();
    assert!(matches!(covered.state, FieldState::Covered { .. }));
}

#[test]
fn profile_bound_cut_rejects_missing_field_cells() {
    let p = profile();
    let cutoff = t("2026-08-17T12:00:00.000000Z");
    let mut cut = SurfaceReducer::reduce(&p, universe(cutoff), &[], cutoff, 10).unwrap();
    cut.source_states.pop();
    cut.reducer_digest = cut.computed_reducer_digest().unwrap();
    assert!(matches!(
        cut.validate_against(&p),
        Err(SurfaceError::UniverseNotClosed)
    ));
}

fn hot_lease() -> HotLeaseV1 {
    let created = t("2026-08-17T12:00:00.000000Z");
    HotLeaseV1 {
        lease_id: s("lease-1"),
        intent: HotScopeIntentV1 {
            intent_id: s("intent-1"),
            subject: s("mint-a"),
            reason: s("operator-watch"),
            denominator: s("census-1"),
            created_at: created,
        },
        desired: HotScopeDesiredV1 {
            desired_id: s("desired-1"),
            intent_id: s("intent-1"),
            lease_id: s("lease-1"),
            reason: s("operator-watch"),
            ttl_seconds: ttl(60),
            expires_at: t("2026-08-17T12:01:00.000000Z"),
        },
        denominator: s("census-1"),
        control_reservation: HotControlWriteReservationV1 {
            reservation_id: s("control-1"),
            desired_id: s("desired-1"),
            reserved_at: created,
            control_digest: d('7'),
        },
        applied: Some(HotScopeAppliedV1 {
            applied_id: s("applied-1"),
            desired_id: s("desired-1"),
            control_reservation_id: s("control-1"),
            applied_at: t("2026-08-17T12:00:10.000000Z"),
            receipt_id: s("receipt-1"),
        }),
        degraded: None,
        acquisition_reservation: AcquisitionReservationV1 {
            reservation_id: s("acquire-1"),
            subject: s("mint-a"),
            reserved_at: t("2026-08-17T12:00:20.000000Z"),
            cost_digest: d('8'),
        },
        authority: SurfaceSemanticAuthority::UnverifiedSemantic,
    }
}

#[test]
fn lease_and_session_parsers_require_exact_canonical_bytes() {
    // Before this, a lease or a session could only enter through a struct an integrator built
    // itself; neither DTO had a parser, so neither had an exact-byte rule.
    let lease = hot_lease();
    let bytes = lease.canonical_bytes().unwrap();
    assert_eq!(parse_hot_lease(&bytes).unwrap(), lease);
    let mut padded = vec![b' '];
    padded.extend(bytes.clone());
    assert!(matches!(
        parse_hot_lease(&padded),
        Err(SurfaceError::DigestMismatch)
    ));
    let mut broken: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    broken
        .as_object_mut()
        .unwrap()
        .insert("surprise".to_owned(), serde_json::Value::Bool(true));
    assert!(parse_hot_lease(&serde_json::to_vec(&broken).unwrap()).is_err());

    let p = profile();
    let session = EmberUseSessionV1 {
        session_id: s("session-parse"),
        build_digest: d('3'),
        profile_digest: p.profile_digest.clone(),
        supported_critical_tasks: BTreeSet::from([s("open-launch")]),
        switched_away_for_parity_gap: false,
        switch_reason: None,
        fixture_rendered: true,
        live_read_only: false,
        evidence: Vec::new(),
        acknowledgment: EmberUseAcknowledgmentV1 {
            acknowledgment_id: s("ack-parse"),
            build_digest: d('3'),
            session_id: s("session-parse"),
            profile_digest: p.profile_digest,
            reduced_navigation_burden: true,
            preserved_orientation: true,
            worth_reopening: true,
            acknowledged_at: t("2026-08-17T12:00:00.000000Z"),
        },
    };
    let bytes = session.canonical_bytes().unwrap();
    assert_eq!(parse_ember_use_session(&bytes).unwrap(), session);
    let mut padded = vec![b' '];
    padded.extend(bytes);
    assert!(matches!(
        parse_ember_use_session(&padded),
        Err(SurfaceError::DigestMismatch)
    ));
}
