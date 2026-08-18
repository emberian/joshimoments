use super::*;

use joshi_acquisition_policy::AsOfCutoff;
use joshi_admission::{
    PublicAdmittedCounts, PublicStatus, PublicStoreReceiptV1,
    operational::{
        ExactByteClosureV1, PublicProtectionClass, SOURCE_FACT_ARTIFACT_RECEIPT_CONTRACT,
        SPOOL_CATALOG_RECEIPT_CONTRACT, SpoolBatchClosureV1,
    },
};
use joshi_attention::AttentionDataset;
use joshi_domain::{BatchDigest, ObservationId, UtcTimestamp, ValueDigest, WireU64};
use joshi_evidence::{CoverageWindow, ObservationDraft};
use joshi_market_state::{
    EffectiveFactRef, FactProtection, MarketFactPayload, MarketStateCut, SelectedFact,
    adapt_attention_event,
};
use joshi_projection::{ProjectionDraft, build_projection};
use joshi_publication::{
    ProjectionPublicationDraft, ProjectionPublicationId, PublicationCommitContext,
    PublicationCommitStatus, finalize_projection_publication, prepare_projection,
};
use serde::Deserialize;

const ATTENTION: &str = include_str!("../../../fixtures/attention/study-ready.valid.json");
const PROJECTION: &str = include_str!("../../../fixtures/publication/projection_artifact_v1.json");
const VECTORS: &str = include_str!("../../../fixtures/operational-circulation/adversarial.v1.json");

struct OwnedInputs {
    source_segment: Vec<u8>,
    source_batch: Vec<u8>,
    source_policy: Vec<u8>,
    source_receipt: Vec<u8>,
    census_artifact: Vec<u8>,
    census_receipt: Vec<u8>,
    cluster: Vec<u8>,
    market: Vec<u8>,
    market_receipt: Vec<u8>,
    projection: Vec<u8>,
    publication: Vec<u8>,
    publication_receipt: Vec<u8>,
}

impl OwnedInputs {
    fn borrowed(&self) -> CirculationInputs<'_> {
        CirculationInputs {
            source_segment_bytes: &self.source_segment,
            source_batch_bytes: &self.source_batch,
            source_policy_bytes: &self.source_policy,
            source_receipt_bytes: &self.source_receipt,
            census_artifact_bytes: &self.census_artifact,
            census_receipt_bytes: &self.census_receipt,
            selected_cluster_context_bytes: &self.cluster,
            market_state_artifact_bytes: &self.market,
            market_state_receipt_bytes: &self.market_receipt,
            projection_artifact_bytes: &self.projection,
            projection_publication_bytes: &self.publication,
            projection_receipt_bytes: &self.publication_receipt,
            census_capability: None,
            market_state_capability: None,
            publication_capability: None,
        }
    }
}

#[test]
fn valid_prefix_stops_at_named_contract_blockers() {
    let owned = valid_inputs();
    let outcome = audit_circulation(owned.borrowed()).expect("valid prefix audits");
    let CirculationOutcomeV1::Blocked {
        authority,
        verified,
        blockers,
        ..
    } = outcome
    else {
        panic!("frozen V1 contracts cannot form a full circulation witness");
    };
    assert_eq!(authority.as_str(), READ_ONLY_NO_EXECUTION);
    assert_eq!(verified.source_commit, CommitSeq::new(5));
    assert_eq!(verified.census_commit, CommitSeq::new(6));
    assert_eq!(verified.market_state_commit, CommitSeq::new(11));
    assert_eq!(verified.projection_through, CommitSeq::new(20));
    assert_eq!(verified.publication_commit, CommitSeq::new(21));
    assert_eq!(
        blockers.iter().map(|value| value.code).collect::<Vec<_>>(),
        vec![
            CirculationBlockerCode::CensusMembershipArtifactNotSemanticallyInspectable,
            CirculationBlockerCode::ProjectionMarketStateArtifactUnreferenced,
            CirculationBlockerCode::PublicationExactBytesUnbound,
        ]
    );
    assert_ne!(
        verified.digests.source_batch_exact,
        verified.digests.source_batch_logical
    );
    assert_ne!(
        verified.digests.publication_exact,
        verified.digests.publication_semantic
    );
}

#[test]
fn exact_source_byte_substitution_refuses() {
    let mut owned = valid_inputs();
    owned.source_segment.push(b'!');
    let error = audit_circulation(owned.borrowed()).expect_err("segment substitution refuses");
    assert_eq!(error.code, CirculationErrorCode::SourceReceiptClosure);
}

#[test]
fn duplicate_key_refuses_before_semantic_parsing() {
    let mut owned = valid_inputs();
    owned.cluster = duplicate_first_object_key(&owned.cluster, "cluster_context_id");
    let error = audit_circulation(owned.borrowed()).expect_err("duplicate key refuses");
    assert_eq!(error.code, CirculationErrorCode::StrictJson);
}

#[test]
fn free_standing_cluster_context_refuses() {
    let mut owned = valid_inputs();
    let mut cluster: SelectedClusterContext =
        serde_json::from_slice(&owned.cluster).expect("cluster");
    cluster.source_snapshot_digest =
        ValueDigest::new(format!("sha256:{}", "f".repeat(64))).expect("digest");
    owned.cluster = serde_json::to_vec(&cluster).expect("cluster bytes");
    let error = audit_circulation(owned.borrowed()).expect_err("unbound cluster refuses");
    assert_eq!(error.code, CirculationErrorCode::ClusterContextClosure);
}

#[test]
fn future_known_market_input_refuses() {
    let mut owned = valid_inputs();
    let mut market: MarketStateSnapshotV1 =
        serde_json::from_slice(&owned.market).expect("market snapshot");
    market.input_closure[0].available_commit = CommitSeq::new(11);
    market.attention[0].effective.available_commit = CommitSeq::new(11);
    owned.market = serde_json::to_vec(&market).expect("market bytes");
    owned.market_receipt = source_fact_receipt(
        "market-state-batch",
        market.artifact_id.as_str(),
        "market_state",
        MARKET_STATE_SNAPSHOT_CONTRACT,
        &owned.market,
        &serde_json::to_vec(&market.input_closure).expect("closure"),
        10,
        11,
    );
    let error = audit_circulation(owned.borrowed()).expect_err("future input refuses");
    assert_eq!(error.code, CirculationErrorCode::MarketStateClosure);
}

#[test]
fn publication_semantic_digest_cannot_replace_exact_byte_digest() {
    let owned = valid_inputs();
    let outcome = audit_circulation(owned.borrowed()).expect("audit");
    let CirculationOutcomeV1::Blocked {
        verified, blockers, ..
    } = outcome
    else {
        panic!("must remain blocked");
    };
    assert!(
        blockers
            .iter()
            .any(|value| { value.code == CirculationBlockerCode::PublicationExactBytesUnbound })
    );
    assert_ne!(
        verified.digests.publication_semantic,
        verified.digests.publication_exact
    );
}

#[test]
fn fixture_freezes_refusal_and_blocker_vocabulary() {
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct Vectors {
        contract: String,
        outcome: String,
        blockers: Vec<CirculationBlockerCode>,
        adversarial: Vec<Adversarial>,
    }
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct Adversarial {
        mutation: String,
        expected_error: CirculationErrorCode,
    }
    let vectors: Vectors = serde_json::from_str(VECTORS).expect("strict vocabulary fixture");
    assert_eq!(vectors.contract, CIRCULATION_REPORT_CONTRACT);
    assert_eq!(vectors.outcome, "blocked");
    assert_eq!(vectors.blockers.len(), 3);
    assert!(
        vectors
            .blockers
            .contains(&CirculationBlockerCode::PublicationExactBytesUnbound)
    );
    assert!(vectors.adversarial.iter().any(|value| {
        value.mutation == "later-known-market-input"
            && value.expected_error == CirculationErrorCode::MarketStateClosure
    }));
}

#[allow(clippy::too_many_lines)]
fn valid_inputs() -> OwnedInputs {
    let source_segment = b"source-segment:operational-circulation:v1".to_vec();
    let source_policy =
        br#"{"retention":"public_integrity","authority":"read_only_no_execution"}"#.to_vec();
    let source_batch_value = source_batch();
    let source_batch = serde_json::to_vec(&source_batch_value).expect("source batch bytes");
    let source_receipt_value = spool_receipt(
        &source_segment,
        &source_batch,
        &source_policy,
        &source_batch_value,
    );
    let source_receipt = serde_json::to_vec(&source_receipt_value).expect("source receipt bytes");

    let evidence = EvidenceLink {
        kind: EvidenceKind::Observation,
        id: stable("pump-api-obs:001:0"),
        digest: None,
        available_at: timestamp("2026-08-16T12:00:02.000000Z"),
        commit_seq: Some(WireU64::new(5)),
    };
    let coverage = EvidenceLink {
        kind: EvidenceKind::Coverage,
        id: stable("coverage:callout-recent:first-page"),
        digest: None,
        available_at: timestamp("2026-08-16T12:00:02.000000Z"),
        commit_seq: Some(WireU64::new(5)),
    };
    let census = CensusDenominatorRef {
        census_id: stable("census:operational-circulation:001"),
        kind: CensusKind::IndependentChainProvider,
        eligible_membership_artifact_id: stable("census-membership:001"),
        eligible_universe_digest: ValueDigest::new(format!("sha256:{}", "9".repeat(64)))
            .expect("digest"),
        eligible_subject_count: WireU64::new(1),
        as_of: AsOfCutoff {
            available_through: timestamp("2026-08-16T12:00:03.000000Z"),
            commit_through: Some(WireU64::new(5)),
        },
        evidence: vec![evidence],
        coverage_evidence: vec![coverage],
        parity_receipt_id: None,
    };
    let census_artifact = serde_json::to_vec(&census).expect("census bytes");
    let census_closure = CensusInputClosureV1::from_denominator(&census)
        .exact_bytes()
        .expect("census closure");
    let census_receipt = source_fact_receipt(
        "census-batch",
        census.eligible_membership_artifact_id.as_str(),
        "acquisition_policy",
        CENSUS_ARTIFACT_CONTRACT,
        &census_artifact,
        &census_closure,
        5,
        6,
    );

    let dataset: AttentionDataset = serde_json::from_str(ATTENTION).expect("attention fixture");
    let event = dataset.attention_events.first().expect("event");
    let cluster_value = dataset
        .selected_cluster_contexts
        .first()
        .expect("cluster")
        .clone();
    let cluster = serde_json::to_vec(&cluster_value).expect("cluster bytes");
    let subject = stable(event.mint_id.as_str());
    let fact = adapt_attention_event(subject.clone(), &dataset, &event.attention_event_id)
        .expect("attention adapter");
    let effective = EffectiveFactRef {
        assertion_id: joshi_domain::AssertionId::new("assertion:attention:001")
            .expect("assertion id"),
        semantic_key: stable("market-state:attention:callout-001"),
        produced_commit: CommitSeq::new(10),
        value_digest: ValueDigest::new(format!("sha256:{}", "a".repeat(64))).expect("digest"),
        supersedes_assertion_id: None,
        available_at: fact.available_at,
        available_commit: fact.available_commit,
        evidence: fact.evidence.clone(),
    };
    assert_eq!(
        effective.evidence.protection,
        FactProtection::PublicIntegrity
    );
    let MarketFactPayload::Attention(attention_fact) = fact.payload else {
        panic!("attention adapter must produce an attention fact");
    };
    let market_value = MarketStateSnapshotV1 {
        contract: stable(MARKET_STATE_SNAPSHOT_CONTRACT),
        artifact_id: stable("market-state:operational-circulation:001"),
        subject_id: subject,
        authority: stable(READ_ONLY_AUTHORITY),
        cut: MarketStateCut {
            valid_at: timestamp("2026-08-16T12:00:00.500000Z"),
            known_by: timestamp("2026-08-16T14:00:00.000000Z"),
            known_by_commit: CommitSeq::new(10),
            finalized_chain_slot: WireU64::new(100),
        },
        social_product: Vec::new(),
        lifecycle: Vec::new(),
        pool_state: Vec::new(),
        attention: vec![SelectedFact {
            effective: effective.clone(),
            value: *attention_fact,
        }],
        input_closure: vec![effective.clone()],
    };
    let market = serde_json::to_vec(&market_value).expect("market bytes");
    let market_closure = serde_json::to_vec(&market_value.input_closure).expect("market closure");
    let market_receipt = source_fact_receipt(
        "market-state-batch",
        market_value.artifact_id.as_str(),
        "market_state",
        MARKET_STATE_SNAPSHOT_CONTRACT,
        &market,
        &market_closure,
        10,
        11,
    );

    let base: ProjectionArtifactV1 = serde_json::from_str(PROJECTION).expect("projection fixture");
    let mut input = base.input.clone();
    input.through_commit_seq = CommitSeq::new(20);
    input.as_of.catalog_commit = CommitSeq::new(20);
    input.effective_assertions = vec![EffectiveAssertionRef {
        assertion_id: effective.assertion_id,
        semantic_key: effective.semantic_key,
        produced_commit_seq: effective.produced_commit,
        value_digest: effective.value_digest,
        supersedes_assertion_id: effective.supersedes_assertion_id,
    }];
    input.observation_ids = vec![ObservationId::new("pump-api-obs:001:0").expect("observation id")];
    let projection_value = build_projection(ProjectionDraft {
        projection_id: stable("projection:operational-circulation:001"),
        supersedes_projection_id: None,
        calculator_build: stable("operational-circulation-test-build:v1"),
        request_digest: ValueDigest::new(format!("sha256:{}", "1".repeat(64))).expect("digest"),
        input,
        coverage: base.coverage,
        accounting: base.accounting,
        market: base.market,
        liquidity: base.liquidity,
    })
    .expect("build projection");
    let prepared = prepare_projection(projection_value).expect("prepare projection");
    let publication_value = finalize_projection_publication(
        &prepared,
        ProjectionPublicationDraft {
            batch_id: stable("publication-batch:operational-circulation:001"),
            publication_id: ProjectionPublicationId::new("publication:operational-circulation:001")
                .expect("publication id"),
            supersedes_publication_id: None,
        },
        PublicationCommitContext {
            catalog_id: stable("catalog-operational-circulation"),
            catalog_schema: stable("joshi.sqlite.v7"),
            commit_seq: CommitSeq::new(21),
        },
        None,
    )
    .expect("finalize publication");
    let publication_receipt_value = SemanticProjectionReceipt::from_publication(
        &publication_value,
        PublicationCommitStatus::Accepted,
    );

    OwnedInputs {
        source_segment,
        source_batch,
        source_policy,
        source_receipt,
        census_artifact,
        census_receipt,
        cluster,
        market,
        market_receipt,
        projection: prepared.bytes().to_vec(),
        publication: projection_publication_bytes(&publication_value).expect("publication bytes"),
        publication_receipt: serde_json::to_vec(&publication_receipt_value)
            .expect("publication receipt bytes"),
    }
}

fn source_batch() -> DurableIngestBatch {
    let observation: ObservationDraft = serde_json::from_value(serde_json::json!({
        "acquisition": {
            "acquisition_id": "pump-api-acq:001",
            "source_id": "joshi.pump_api.acquisition.v1",
            "acquisition_kind": variant("fixture"),
            "transport_kind": variant("fixture"),
            "parent_acquisition_id": null,
            "request_fingerprint": format!("sha256:{}", "2".repeat(64)),
            "contract_version": "pump-api:v1",
            "started_at": "2026-08-16T12:00:00.000000Z",
            "started_monotonic": {"clock_id":"fixture-clock","nanoseconds":"1"},
            "source_locator": "fixture:callout-001",
            "source_cursor": "cursor:opaque:page-1",
            "clocks": {
                "requested_at": "2026-08-16T12:00:00.000000Z",
                "received_at": "2026-08-16T12:00:01.000000Z",
                "persisted_at": "2026-08-16T12:00:02.000000Z",
                "monotonic_elapsed_ns": "1000",
                "monotonic_domain": "fixture-clock"
            }
        },
        "observation": {
            "observation_id": "pump-api-obs:001:0",
            "acquisition_ordinal": "0",
            "observation_kind": variant("fixture_response"),
            "source_events": [],
            "source_variant": variant("pump_api.callout_recent"),
            "event_time": {
                "status": variant("exact"),
                "lower": "2026-08-16T12:00:00.000000Z",
                "upper": "2026-08-16T12:00:01.000000Z",
                "precision_us": "1000000"
            },
            "chain": null,
            "source_cursor": "cursor:opaque:page-1",
            "timing": {
                "received_at": "2026-08-16T12:00:01.000000Z",
                "received_monotonic": {"clock_id":"fixture-clock","nanoseconds":"2"},
                "persisted_at": "2026-08-16T12:00:02.000000Z",
                "available_at": "2026-08-16T12:00:02.000000Z"
            },
            "parse_disposition": variant("decoded"),
            "quality_code": null,
            "media_type": "application/json"
        },
        "payload": "eyJjYWxsb3V0SWQiOiJwdW1wLWNhbGxvdXQ6MDAxIn0="
    }))
    .expect("observation");
    let coverage: CoverageWindow = serde_json::from_value(serde_json::json!({
        "coverage_id": "coverage:callout-recent:first-page",
        "scope": {
            "source_id": "joshi.pump_api.acquisition.v1",
            "family": variant("callout_recent"),
            "subject": "first-page"
        },
        "lower": {"clock":"wall","value":"2026-08-16T11:59:00.000000Z"},
        "upper": {"clock":"wall","value":"2026-08-16T12:01:00.000000Z"},
        "state": variant("complete"),
        "available_at": "2026-08-16T12:00:02.000000Z"
    }))
    .expect("coverage");
    let mut batch = DurableIngestBatch {
        contract_version: stable(joshi_evidence::DURABLE_INGEST_BATCH_CONTRACT_VERSION),
        batch_id: stable("batch:operational-circulation:source:001"),
        expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64))).expect("digest"),
        observations: vec![observation],
        source_events: Vec::new(),
        assertions: Vec::new(),
        coverage_windows: vec![coverage],
        coverage_gaps: Vec::new(),
        coverage_recoveries: Vec::new(),
        cursor_advances: Vec::new(),
    };
    batch.expected_digest = SqliteStore::canonical_batch_digest(&batch).expect("batch digest");
    batch
}

fn spool_receipt(
    segment: &[u8],
    batch_bytes: &[u8],
    policy: &[u8],
    batch: &DurableIngestBatch,
) -> SpoolCatalogReceiptV1 {
    let logical = Sha256Digest::parse(batch.expected_digest.as_str()).expect("logical digest");
    let admission =
        Sha256Digest::parse(format!("sha256:{}", "3".repeat(64))).expect("admission digest");
    SpoolCatalogReceiptV1 {
        contract: SPOOL_CATALOG_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        segment_id: "segment:operational-circulation:001".into(),
        protection_domain: "public-chain-and-product".into(),
        protection_class: PublicProtectionClass::PublicIntegrity,
        exact_segment: ExactByteClosureV1::new(segment).expect("segment closure"),
        batch: SpoolBatchClosureV1 {
            batch_id: batch.batch_id.to_string(),
            exact_batch: ExactByteClosureV1::new(batch_bytes).expect("batch closure"),
            logical_batch_digest: logical.clone(),
            exact_policy: ExactByteClosureV1::new(policy).expect("policy closure"),
            store_admission_digest: admission.clone(),
        },
        catalog_receipt: PublicStoreReceiptV1 {
            contract: "joshi.store.ingest_receipt".into(),
            schema_version: 1,
            catalog_id: "catalog-operational-circulation".into(),
            catalog_schema: "joshi.sqlite.v7".into(),
            commit_seq: "5".into(),
            batch_id: batch.batch_id.to_string(),
            batch_digest: logical,
            store_admission_digest: admission,
            status: PublicStatus::Accepted,
            from_commit_seq: "5".into(),
            through_commit_seq: "5".into(),
            admitted: PublicAdmittedCounts {
                acquisitions: "1".into(),
                raw_blobs: "1".into(),
                raw_bytes: batch.observations[0].payload.len().to_string(),
                observations: "1".into(),
                source_events: "0".into(),
                assertions: "0".into(),
                coverage_windows: "1".into(),
                coverage_gaps: "0".into(),
                coverage_recoveries: "0".into(),
                cursor_advances: "0".into(),
            },
            acquisition_ids: vec!["pump-api-acq:001".into()],
            gap_outcomes: Vec::new(),
        },
        status: OperationalStatus::Accepted,
        authority: AUTHORITY.into(),
    }
}

#[allow(clippy::too_many_arguments)]
fn source_fact_receipt(
    batch_id: &str,
    artifact_id: &str,
    family: &str,
    contract: &str,
    artifact: &[u8],
    closure: &[u8],
    known: u64,
    commit: u64,
) -> Vec<u8> {
    serde_json::to_vec(&SourceFactArtifactReceiptV1 {
        contract: SOURCE_FACT_ARTIFACT_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        catalog_id: "catalog-operational-circulation".into(),
        catalog_schema: "joshi.sqlite.v7".into(),
        batch_id: batch_id.into(),
        artifact_id: artifact_id.into(),
        artifact_family: family.into(),
        artifact_contract: contract.into(),
        artifact_digest: Sha256Digest::of_bytes(artifact),
        input_closure_digest: Sha256Digest::of_bytes(closure),
        known_through_commit_seq: known.to_string(),
        commit_seq: commit.to_string(),
        authority: AUTHORITY.into(),
        status: OperationalStatus::Accepted,
    })
    .expect("source/fact receipt bytes")
}

fn duplicate_first_object_key(bytes: &[u8], key: &str) -> Vec<u8> {
    let text = String::from_utf8(bytes.to_vec()).expect("utf8 fixture");
    let needle = format!("\"{key}\":");
    let start = text.find(&needle).expect("key");
    let value_start = start + needle.len();
    let value_end = text[value_start..]
        .find(',')
        .map(|offset| value_start + offset)
        .expect("first string field comma");
    let duplicate = format!("{},", &text[start..value_end]);
    format!("{{{duplicate}{}", &text[1..]).into_bytes()
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().expect("timestamp")
}

fn variant(value: &str) -> serde_json::Value {
    serde_json::json!({"discriminator": value, "recognition": "known"})
}
