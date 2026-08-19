use std::str::FromStr;

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_projection::ProjectionAuthority;

use super::*;

const V2_FIXTURE: &str = include_str!("../../../fixtures/publication/cockpit_v2_manifest_v1.json");
const V2_RESOLVED_INPUT_FIXTURE: &str =
    include_str!("../../../fixtures/publication/cockpit_v2_resolved_source_facts_input_v1.json");
const V2_HEAD_FIXTURE: &str = include_str!("../../../fixtures/publication/cockpit_v2_head_v1.json");
const V2_BROWSER_PRESENTATION_FIXTURE: &str =
    include_str!("../../../fixtures/publication/cockpit_v2_browser_presentation_claim_v1.json");

fn s(value: &str) -> StableString {
    StableString::new(value).unwrap()
}
fn t(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).unwrap()
}
fn d(fill: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).unwrap()
}

#[allow(clippy::too_many_lines)]
fn manifest() -> CockpitV2ManifestV1 {
    let mut value = CockpitV2ManifestV1 {
        contract: s(COCKPIT_V2_MANIFEST_CONTRACT),
        schema_version: COCKPIT_V2_SCHEMA_VERSION,
        surface_profile: CockpitV2SurfaceProfileRefV1 {
            profile_id: s("daily-1"),
            profile_digest: d('1'),
            field_cells: vec![
                CockpitV2SurfaceFieldRefV1 {
                    surface_id: s("launch"),
                    source_id: s("solana"),
                    field: s("mint"),
                },
                CockpitV2SurfaceFieldRefV1 {
                    surface_id: s("social"),
                    source_id: s("social"),
                    field: s("reply"),
                },
            ],
        },
        observed_universe: CockpitV2ObservedUniverseRefV1 {
            universe_id: s("census-1"),
            universe_digest: d('2'),
            eligible_count: WireU64::new(2),
            eligible_subjects: vec![s("mint-1"), s("mint-2")],
        },
        cutoff: CockpitV2CutoffV1 {
            knowledge_at: t("2026-08-18T12:00:00.000000Z"),
            commit_through: Some(CommitSeq::new(10)),
            chain_slot: Some(WireU64::new(100)),
        },
        source_facts: vec![
            CockpitV2SourceFactRefV1 {
                fact_id: s("fact-1"),
                fact_digest: d('3'),
                surface_id: s("launch"),
                source_id: s("solana"),
                subject: s("mint-1"),
                field: s("mint"),
                protection: ProtectionDomain::Public,
                observed_at: t("2026-08-18T11:00:00.000000Z"),
                known_at: t("2026-08-18T11:30:00.000000Z"),
                commit_seq: Some(CommitSeq::new(9)),
            },
            CockpitV2SourceFactRefV1 {
                fact_id: s("fact-2"),
                fact_digest: d('8'),
                surface_id: s("social"),
                source_id: s("social"),
                subject: s("mint-1"),
                field: s("reply"),
                protection: ProtectionDomain::Public,
                observed_at: t("2026-08-18T11:00:00.000000Z"),
                known_at: t("2026-08-18T11:30:00.000000Z"),
                commit_seq: Some(CommitSeq::new(9)),
            },
        ],
        memberships: vec![
            CockpitV2MembershipRefV1 {
                subject: s("mint-1"),
                membership: CockpitV2MembershipKind::Hot,
                observed_at: t("2026-08-18T11:00:00.000000Z"),
                evidence_digest: d('4'),
            },
            CockpitV2MembershipRefV1 {
                subject: s("mint-2"),
                membership: CockpitV2MembershipKind::ColdControl,
                observed_at: t("2026-08-18T11:00:00.000000Z"),
                evidence_digest: d('9'),
            },
        ],
        coverage: vec![
            CockpitV2CoverageRefV1 {
                surface_id: s("launch"),
                source_id: s("solana"),
                subject: s("mint-1"),
                field: s("mint"),
                fact_ids: vec![s("fact-1")],
                state: CockpitV2CoverageState::Complete,
                coverage_digest: d('5'),
            },
            CockpitV2CoverageRefV1 {
                surface_id: s("launch"),
                source_id: s("solana"),
                subject: s("mint-2"),
                field: s("mint"),
                fact_ids: vec![],
                state: CockpitV2CoverageState::Unavailable,
                coverage_digest: d('7'),
            },
            CockpitV2CoverageRefV1 {
                surface_id: s("social"),
                source_id: s("social"),
                subject: s("mint-1"),
                field: s("reply"),
                fact_ids: vec![s("fact-2")],
                state: CockpitV2CoverageState::Unavailable,
                coverage_digest: d('a'),
            },
            CockpitV2CoverageRefV1 {
                surface_id: s("social"),
                source_id: s("social"),
                subject: s("mint-2"),
                field: s("reply"),
                fact_ids: vec![],
                state: CockpitV2CoverageState::Unavailable,
                coverage_digest: d('b'),
            },
        ],
        gaps: vec![CockpitV2GapRefV1 {
            gap_id: s("gap-1"),
            surface_id: s("social"),
            source_id: s("social"),
            subject: s("mint-1"),
            field: s("reply"),
            reason: s("unavailable"),
            since: t("2026-08-18T10:00:00.000000Z"),
            until: None,
            evidence_digest: Some(d('6')),
        }],
        rendered_subjects: vec![s("mint-1")],
        omissions: vec![CockpitV2OmissionV1 {
            subject: s("mint-2"),
            reason: s("denominator_only"),
            membership: CockpitV2MembershipKind::DenominatorOnly,
        }],
        ordering_policy: s("subject_membership_v1"),
        pagination_policy: s("cursor_v1"),
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        ceiling: CockpitV2Ceiling::UnverifiedSemantic,
        semantic_digest: d('0'),
        container_digest: d('0'),
    };
    value.observed_universe.universe_digest = value.observed_universe.computed_digest().unwrap();
    value.semantic_digest = value.computed_semantic_digest().unwrap();
    value.container_digest = value.computed_container_digest().unwrap();
    value
}

fn headed_publication() -> (CockpitV2PublicationV1, CockpitV2HeadV1, Vec<u8>, Vec<u8>) {
    let prepared = prepare_cockpit_v2(manifest()).unwrap();
    let publication = finalize_cockpit_v2(
        &prepared,
        CockpitPublicationId::new("cockpit-v2-g0-1").unwrap(),
        CommitSeq::new(11),
        None,
        None,
    )
    .unwrap();
    let head = CockpitV2HeadV1::from_publication(&publication).unwrap();
    let publication_bytes = publication.canonical_bytes().unwrap();
    let head_bytes = head.canonical_bytes().unwrap();
    (publication, head, publication_bytes, head_bytes)
}

fn browser_presentation_claim(
    publication: &CockpitV2PublicationV1,
    head: &CockpitV2HeadV1,
    publication_bytes: &[u8],
    head_bytes: &[u8],
) -> CockpitV2BrowserPresentationClaimV1 {
    let mut claim = CockpitV2BrowserPresentationClaimV1 {
        contract: s(COCKPIT_V2_BROWSER_PRESENTATION_CLAIM_CONTRACT),
        schema_version: COCKPIT_V2_BROWSER_PRESENTATION_SCHEMA_VERSION,
        idempotency_key: s("browser-presentation:browser-page-1:1"),
        client_presentation_id: s("browser-presentation-1"),
        browser_page_id: s("browser-page-1"),
        presentation_seq: WireU64::new(1),
        publication: CockpitV2PresentedPublicationRefV1 {
            publication_id: publication.publication_id.clone(),
            publication_digest: publication.publication_digest.clone(),
            publication_bytes_digest: sha256_digest(publication_bytes),
            publication_commit_seq: CommitSeq::new(11),
        },
        head: CockpitV2PresentedHeadRefV1 {
            head_digest: head.head_digest.clone(),
            head_bytes_digest: sha256_digest(head_bytes),
            head_commit_seq: CommitSeq::new(12),
        },
        source_occurrence_id: s("source-occurrence-vector-1"),
        rendered_subjects: publication.manifest.rendered_subjects.clone(),
        rendered_subject_count: WireU64::new(1),
        mounted_at: t("2026-08-18T12:01:00.000000Z"),
        client_clock_id: s("browser-page-1-performance"),
        monotonic_ns: WireU64::new(1_234_567_000),
        viewport: CockpitV2BrowserViewportV1 {
            width_css_px: WireU64::new(1_280),
            height_css_px: WireU64::new(800),
            device_pixel_ratio_milli: WireU64::new(2_000),
        },
        document_visibility: CockpitV2DocumentVisibility::Visible,
        document_has_focus: true,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        ceiling: CockpitV2BrowserPresentationCeiling::BrowserReportedNotPixelVerified,
        claim_digest: d('0'),
    };
    claim.claim_digest = claim.computed_digest().unwrap();
    claim
}

#[test]
fn v2_semantic_and_container_digests_are_distinct_and_round_trip() {
    let value = manifest();
    value.validate().unwrap();
    assert_ne!(value.semantic_digest, value.container_digest);
    let prepared = prepare_cockpit_v2(value.clone()).unwrap();
    assert_eq!(
        prepared.manifest.canonical_bytes().unwrap(),
        prepared.container_bytes
    );
    let publication = finalize_cockpit_v2(
        &prepared,
        CockpitPublicationId::new("cockpit-v2-1").unwrap(),
        CommitSeq::new(11),
        None,
        None,
    )
    .unwrap();
    publication.validate().unwrap();
    let query = CockpitV2QueryV1 {
        contract: s(COCKPIT_V2_QUERY_CONTRACT),
        publication_id: publication.publication_id.clone(),
        semantic_digest: value.semantic_digest,
        container_digest: value.container_digest,
        cutoff: value.cutoff,
    };
    query.validate_loaded(&publication).unwrap();
}

#[test]
fn browser_presentation_claim_binds_exact_headed_bytes_and_store_commits() {
    let (publication, head, publication_bytes, head_bytes) = headed_publication();
    let claim = browser_presentation_claim(&publication, &head, &publication_bytes, &head_bytes);
    let source_occurrence = s("source-occurrence-vector-1");
    claim
        .validate_against(
            &publication,
            &publication_bytes,
            CommitSeq::new(11),
            &head,
            &head_bytes,
            CommitSeq::new(12),
            &source_occurrence,
        )
        .unwrap();
    let bytes = claim.canonical_bytes().unwrap();
    let fixture_bytes = V2_BROWSER_PRESENTATION_FIXTURE
        .strip_suffix('\n')
        .unwrap()
        .as_bytes();
    assert_eq!(bytes, fixture_bytes);
    assert_eq!(
        claim.claim_digest.as_str(),
        "sha256:b3be9ee0b5097d2fb15d1718aca21d3d76b8d6e09860d887e0241bbf2de50a26"
    );
    assert_eq!(
        parse_cockpit_v2_browser_presentation_claim(&bytes).unwrap(),
        claim
    );

    let mut padded_publication = publication_bytes.clone();
    padded_publication.push(b' ');
    assert!(
        claim
            .validate_against(
                &publication,
                &padded_publication,
                CommitSeq::new(11),
                &head,
                &head_bytes,
                CommitSeq::new(12),
                &source_occurrence,
            )
            .is_err()
    );

    let mut backdated_body = claim.clone();
    backdated_body.publication.publication_commit_seq = CommitSeq::new(10);
    backdated_body.claim_digest = backdated_body.computed_digest().unwrap();
    assert!(
        backdated_body
            .validate_against(
                &publication,
                &publication_bytes,
                CommitSeq::new(10),
                &head,
                &head_bytes,
                CommitSeq::new(12),
                &source_occurrence,
            )
            .is_err()
    );
    assert!(
        claim
            .validate_against(
                &publication,
                &publication_bytes,
                CommitSeq::new(11),
                &head,
                &head_bytes,
                CommitSeq::new(13),
                &source_occurrence,
            )
            .is_err()
    );
}

#[test]
fn browser_presentation_claim_refuses_subject_clock_viewport_and_json_laundering() {
    let (publication, head, publication_bytes, head_bytes) = headed_publication();
    let source_occurrence = s("source-occurrence-vector-1");
    let claim = browser_presentation_claim(&publication, &head, &publication_bytes, &head_bytes);

    let mut wrong_subject = claim.clone();
    wrong_subject.rendered_subjects = vec![s("mint-2")];
    wrong_subject.claim_digest = wrong_subject.computed_digest().unwrap();
    assert!(
        wrong_subject
            .validate_against(
                &publication,
                &publication_bytes,
                CommitSeq::new(11),
                &head,
                &head_bytes,
                CommitSeq::new(12),
                &source_occurrence,
            )
            .is_err()
    );

    let mut before_knowledge = claim.clone();
    before_knowledge.mounted_at = t("2026-08-18T11:59:59.999999Z");
    before_knowledge.claim_digest = before_knowledge.computed_digest().unwrap();
    assert!(
        before_knowledge
            .validate_against(
                &publication,
                &publication_bytes,
                CommitSeq::new(11),
                &head,
                &head_bytes,
                CommitSeq::new(12),
                &source_occurrence,
            )
            .is_err()
    );

    let mut unbounded = claim.clone();
    unbounded.viewport.width_css_px = WireU64::new(32_769);
    unbounded.claim_digest = unbounded.computed_digest().unwrap();
    assert!(matches!(
        unbounded.validate(),
        Err(PublicationError::CockpitV2Presentation)
    ));

    let mut forged_focus = claim.clone();
    forged_focus.document_has_focus = false;
    assert!(matches!(
        forged_focus.validate(),
        Err(PublicationError::DigestMismatch { .. })
    ));

    let mut nonmonotonic_commits = claim.clone();
    nonmonotonic_commits.head.head_commit_seq = CommitSeq::new(11);
    nonmonotonic_commits.claim_digest = nonmonotonic_commits.computed_digest().unwrap();
    assert!(matches!(
        nonmonotonic_commits.validate(),
        Err(PublicationError::CockpitV2Contract)
    ));

    let mut wrong_idempotency_key = claim.clone();
    wrong_idempotency_key.idempotency_key = s("browser-presentation:other-page:1");
    wrong_idempotency_key.claim_digest = wrong_idempotency_key.computed_digest().unwrap();
    assert!(matches!(
        wrong_idempotency_key.validate(),
        Err(PublicationError::CockpitV2Presentation)
    ));

    let mut json: serde_json::Value =
        serde_json::from_slice(&claim.canonical_bytes().unwrap()).unwrap();
    json.as_object_mut()
        .unwrap()
        .insert("extra".into(), true.into());
    assert!(
        parse_cockpit_v2_browser_presentation_claim(&serde_json::to_vec(&json).unwrap()).is_err()
    );
}

#[test]
fn private_source_and_future_fact_are_refused() {
    let mut private = manifest();
    private.source_facts[0].protection = ProtectionDomain::Authenticated;
    assert!(matches!(
        private.validate(),
        Err(PublicationError::CockpitV2PrivateBytes)
    ));
    let mut future = manifest();
    future.source_facts[0].known_at = t("2026-08-18T12:01:00.000000Z");
    future.semantic_digest = future.computed_semantic_digest().unwrap();
    future.container_digest = future.computed_container_digest().unwrap();
    assert!(matches!(
        future.validate(),
        Err(PublicationError::CockpitV2Cutoff)
    ));
}

#[test]
fn commit_stage_is_monotonic_and_exact() {
    let prepared = prepare_cockpit_v2(manifest()).unwrap();
    let publication = finalize_cockpit_v2(
        &prepared,
        CockpitPublicationId::new("cockpit-v2-2").unwrap(),
        CommitSeq::new(11),
        None,
        None,
    )
    .unwrap();
    let state = CockpitV2CommitStateV1 {
        stage: CockpitV2CommitStage::Prepared,
        publication_id: publication.publication_id.clone(),
        container_digest: publication.manifest.container_digest.clone(),
        head_digest: None,
    };
    let committed = state
        .advance(CockpitV2CommitStage::Committed, &publication, None)
        .unwrap();
    let mut forged_committed = committed.clone();
    forged_committed.head_digest = Some(d('a'));
    assert!(forged_committed.validate(&publication).is_err());
    assert!(
        committed
            .advance(
                CockpitV2CommitStage::HeadPublished,
                &publication,
                Some(d('a')),
            )
            .is_err()
    );
    let head = CockpitV2HeadV1::from_publication(&publication).unwrap();
    head.validate_against(&publication).unwrap();
    assert!(
        state
            .advance(
                CockpitV2CommitStage::Committed,
                &publication,
                Some(head.head_digest.clone()),
            )
            .is_err()
    );
    let headed = committed
        .advance(
            CockpitV2CommitStage::HeadPublished,
            &publication,
            Some(head.head_digest.clone()),
        )
        .unwrap();
    assert_eq!(headed.stage, CockpitV2CommitStage::HeadPublished);
    assert!(
        headed
            .advance(CockpitV2CommitStage::Committed, &publication, None)
            .is_err()
    );
}

#[test]
fn prepared_checkpoint_cannot_cross_bind_another_profile() {
    let mut prepared = prepare_cockpit_v2(manifest()).unwrap();
    prepared.checkpoint.profile_digest = d('a');
    let material = (
        &prepared.checkpoint.profile_digest,
        &prepared.checkpoint.universe_digest,
        prepared.checkpoint.cutoff,
        &prepared.checkpoint.semantic_digest,
        &prepared.checkpoint.container_digest,
    );
    prepared.checkpoint.checkpoint_digest = digest_json(&material).unwrap();
    assert!(matches!(
        prepared.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));
}

#[test]
fn unknown_manifest_fields_are_rejected() {
    let bytes = manifest().canonical_bytes().unwrap();
    let mut json: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    json.as_object_mut().unwrap().insert(
        "privateBytes".to_owned(),
        serde_json::Value::String("no".to_owned()),
    );
    assert!(serde_json::from_value::<CockpitV2ManifestV1>(json).is_err());
}

#[test]
fn manifest_closes_membership_and_render_partitions() {
    let mut value = manifest();
    value.memberships.pop();
    value.semantic_digest = value.computed_semantic_digest().unwrap();
    value.container_digest = value.computed_container_digest().unwrap();
    assert!(matches!(
        value.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));

    let mut value = manifest();
    value.omissions.pop();
    value.semantic_digest = value.computed_semantic_digest().unwrap();
    value.container_digest = value.computed_container_digest().unwrap();
    assert!(matches!(
        value.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));
}

#[test]
fn complete_coverage_cannot_have_a_gap_and_universe_digest_is_intrinsic() {
    let mut value = manifest();
    value.coverage[0].state = CockpitV2CoverageState::Complete;
    value.gaps.push(CockpitV2GapRefV1 {
        gap_id: s("gap-2"),
        surface_id: s("launch"),
        source_id: s("solana"),
        subject: s("mint-1"),
        field: s("mint"),
        reason: s("late"),
        since: t("2026-08-18T10:00:00.000000Z"),
        until: None,
        evidence_digest: None,
    });
    value.gaps.sort_by(|a, b| a.gap_id.cmp(&b.gap_id));
    value.semantic_digest = value.computed_semantic_digest().unwrap();
    value.container_digest = value.computed_container_digest().unwrap();
    assert!(matches!(
        value.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));

    let mut value = manifest();
    value.observed_universe.eligible_subjects[0] = s("forged");
    value.semantic_digest = value.computed_semantic_digest().unwrap();
    value.container_digest = value.computed_container_digest().unwrap();
    assert!(matches!(
        value.validate(),
        Err(PublicationError::DigestMismatch { .. })
    ));
}

#[test]
fn coverage_cannot_be_empty_narrow_or_drop_a_subject_cell() {
    let mut empty = manifest();
    empty.coverage.clear();
    empty.semantic_digest = empty.computed_semantic_digest().unwrap();
    empty.container_digest = empty.computed_container_digest().unwrap();
    assert!(matches!(
        empty.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));

    let mut missing_subject = manifest();
    missing_subject.coverage.pop();
    missing_subject.semantic_digest = missing_subject.computed_semantic_digest().unwrap();
    missing_subject.container_digest = missing_subject.computed_container_digest().unwrap();
    assert!(matches!(
        missing_subject.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));

    let mut unreferenced_fact = manifest();
    unreferenced_fact
        .source_facts
        .push(CockpitV2SourceFactRefV1 {
            fact_id: s("fact-3"),
            fact_digest: d('a'),
            surface_id: s("launch"),
            source_id: s("wallet"),
            subject: s("mint-1"),
            field: s("balance"),
            protection: ProtectionDomain::Public,
            observed_at: t("2026-08-18T11:00:00.000000Z"),
            known_at: t("2026-08-18T11:30:00.000000Z"),
            commit_seq: Some(CommitSeq::new(9)),
        });
    unreferenced_fact.semantic_digest = unreferenced_fact.computed_semantic_digest().unwrap();
    unreferenced_fact.container_digest = unreferenced_fact.computed_container_digest().unwrap();
    assert!(matches!(
        unreferenced_fact.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));

    let mut duplicate_stress = manifest();
    duplicate_stress.coverage[1].fact_ids = vec![s("fact-1")];
    duplicate_stress.semantic_digest = duplicate_stress.computed_semantic_digest().unwrap();
    duplicate_stress.container_digest = duplicate_stress.computed_container_digest().unwrap();
    assert!(matches!(
        duplicate_stress.validate(),
        Err(PublicationError::CockpitV2Reference)
    ));
}

#[test]
fn v2_manifest_fixture_is_canonical() {
    let parsed: CockpitV2ManifestV1 = serde_json::from_str(V2_FIXTURE).unwrap();
    parsed.validate().unwrap();
    assert_eq!(
        parsed.canonical_bytes().unwrap(),
        V2_FIXTURE.trim_end().as_bytes()
    );
}

#[test]
fn resolved_source_facts_fixture_prepares_the_frozen_manifest() {
    let input = parse_cockpit_v2_resolved_source_facts_input(
        V2_RESOLVED_INPUT_FIXTURE.trim_end().as_bytes(),
    )
    .unwrap();
    assert_eq!(
        input.canonical_bytes().unwrap(),
        V2_RESOLVED_INPUT_FIXTURE.trim_end().as_bytes()
    );
    let prepared = prepare_cockpit_v2_from_resolved_source_facts(input).unwrap();
    assert_eq!(prepared.container_bytes, V2_FIXTURE.trim_end().as_bytes());
    let publication = finalize_cockpit_v2(
        &prepared,
        CockpitPublicationId::new("cockpit-v2-g0-1").unwrap(),
        CommitSeq::new(11),
        None,
        None,
    )
    .unwrap();
    let head = CockpitV2HeadV1::from_publication(&publication).unwrap();
    assert_eq!(
        publication.publication_digest.as_str(),
        "sha256:8c79941372588b2001608267ce562288488d3c0dd519595674cc6c0721af0f0f"
    );
    assert_eq!(
        head.canonical_bytes().unwrap(),
        V2_HEAD_FIXTURE.trim_end().as_bytes()
    );
    parse_cockpit_v2_publication(&publication.canonical_bytes().unwrap()).unwrap();
    parse_cockpit_v2_head(V2_HEAD_FIXTURE.trim_end().as_bytes()).unwrap();
}
