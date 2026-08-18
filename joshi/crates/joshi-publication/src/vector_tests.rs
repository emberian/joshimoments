//! Deterministic publication vectors and fault-injected durable-port tests.

use std::collections::BTreeMap;

use joshi_domain::{
    AsOfVector, ChainAsOf, CommitSeq, OpenVariant, SceneId, StableString, UtcTimestamp,
    ValueDigest, WireU64,
};
use joshi_projection::{
    AccountingProjectionDto, CoverageStatus, LiquidityProjectionDto, MarketProjectionDto,
    PROJECTION_CONTRACT, PROJECTION_VERSION, ProjectionCoverage, ProjectionDraft,
    ProjectionInputClosure, build_projection, build_projection_incremental, projection_bytes,
};
use serde::Deserialize;
use thiserror::Error;

use super::*;

const VECTORS: &str = include_str!("../../../fixtures/publication/publication_vectors.json");
const ARTIFACT_VECTOR: &str =
    include_str!("../../../fixtures/publication/projection_artifact_v1.json");
const PUBLICATION_VECTOR: &str =
    include_str!("../../../fixtures/publication/projection_publication_v1.json");
const COCKPIT_VECTOR: &str =
    include_str!("../../../fixtures/publication/cockpit_publication_v1.json");

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("test stable string")
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().expect("test canonical timestamp")
}

fn digest(fill: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).expect("test digest")
}

fn empty_accounting() -> AccountingProjectionDto {
    AccountingProjectionDto {
        asset_definitions: Vec::new(),
        landed_balances: Vec::new(),
        landed_effects: Vec::new(),
        inventory: Vec::new(),
        lots: Vec::new(),
        realized: Vec::new(),
        unrealized: Vec::new(),
        episodes: Vec::new(),
        capital_recovery: Vec::new(),
    }
}

fn projection_draft(
    projection_id: &str,
    supersedes_projection_id: Option<&str>,
    through: u64,
) -> ProjectionDraft {
    ProjectionDraft {
        projection_id: stable(projection_id),
        supersedes_projection_id: supersedes_projection_id.map(stable),
        calculator_build: stable("joshi-publication-test-build"),
        request_digest: digest('1'),
        input: ProjectionInputClosure {
            from_commit_seq: CommitSeq::new(1),
            through_commit_seq: CommitSeq::new(through),
            as_of: AsOfVector {
                catalog_commit: CommitSeq::new(through),
                sources: BTreeMap::new(),
                chain: Some(ChainAsOf {
                    cluster: stable("solana-mainnet-beta"),
                    slot: WireU64::new(1_000 + through),
                    finality: OpenVariant::known("finalized").expect("finality"),
                }),
                projections: BTreeMap::from([(
                    stable(PROJECTION_CONTRACT),
                    stable(PROJECTION_VERSION),
                )]),
                rendered_at: timestamp("2026-08-17T12:00:00.000000Z"),
            },
            controlled_domain_id: stable("controlled-domain-publication-test"),
            effective_assertions: Vec::new(),
            observation_ids: Vec::new(),
        },
        coverage: vec![ProjectionCoverage {
            scope: stable("publication_minimal_fixture"),
            status: CoverageStatus::Complete,
            gap_ids: Vec::new(),
        }],
        accounting: empty_accounting(),
        market: MarketProjectionDto {
            marks: Vec::new(),
            quotes: Vec::new(),
            full_position_quotes: Vec::new(),
        },
        liquidity: LiquidityProjectionDto {
            positions: Vec::new(),
        },
    }
}

fn publication_draft(
    publication_id: &str,
    supersedes_publication_id: Option<&str>,
) -> ProjectionPublicationDraft {
    ProjectionPublicationDraft {
        batch_id: stable(&format!("batch-{publication_id}")),
        publication_id: ProjectionPublicationId::new(publication_id).expect("publication ID"),
        supersedes_publication_id: supersedes_publication_id
            .map(|value| ProjectionPublicationId::new(value).expect("prior publication ID")),
    }
}

fn context(commit: u64) -> PublicationCommitContext {
    PublicationCommitContext {
        catalog_id: stable("catalog-publication-test"),
        catalog_schema: stable("joshi.sqlite.v7"),
        commit_seq: CommitSeq::new(commit),
    }
}

fn first_publication() -> (PreparedProjection, ProjectionPublicationV1) {
    let artifact =
        build_projection(projection_draft("projection-001", None, 10)).expect("first projection");
    let prepared = prepare_projection(artifact).expect("first prepare");
    let publication = finalize_projection_publication(
        &prepared,
        publication_draft("publication-001", None),
        context(11),
        None,
    )
    .expect("first publication");
    (prepared, publication)
}

fn second_artifact() -> joshi_projection::ProjectionArtifactV1 {
    build_projection(projection_draft(
        "projection-002",
        Some("projection-001"),
        20,
    ))
    .expect("second projection")
}

fn second_publication(prior: &ProjectionPublicationV1) -> ProjectionPublicationV1 {
    let prepared = prepare_projection(second_artifact()).expect("second prepare");
    finalize_projection_publication(
        &prepared,
        publication_draft("publication-002", Some("publication-001")),
        context(21),
        Some(prior),
    )
    .expect("second publication")
}

fn cockpit_draft(
    cockpit_id: &str,
    scene_id: &str,
    supersedes: Option<&str>,
) -> CockpitPublicationDraft {
    CockpitPublicationDraft {
        batch_id: stable(&format!("batch-{cockpit_id}")),
        cockpit_publication_id: CockpitPublicationId::new(cockpit_id).expect("cockpit ID"),
        scene_id: SceneId::new(scene_id).expect("scene ID"),
        manifest_digest: digest('9'),
        query_policy: stable("newest_append_only_publication_at_explicit_cutoff_v1"),
        supersedes_cockpit_publication_id: supersedes
            .map(|value| CockpitPublicationId::new(value).expect("prior cockpit ID")),
    }
}

#[test]
fn full_and_incremental_materialization_are_byte_identical() {
    let prior =
        build_projection(projection_draft("projection-001", None, 10)).expect("prior projection");
    let target = projection_draft("projection-002", Some("projection-001"), 20);
    let full = build_projection(target.clone()).expect("full target");
    let incremental = build_projection_incremental(&prior, target).expect("incremental target");

    assert_eq!(full, incremental);
    assert_eq!(
        projection_bytes(&full).expect("full bytes"),
        projection_bytes(&incremental).expect("incremental bytes")
    );
}

#[test]
fn prepare_publication_and_cockpit_keep_every_digest_domain_distinct() {
    let (prepared, publication) = first_publication();
    assert_ne!(
        prepared.artifact().result_digest,
        *prepared.artifact_digest()
    );
    assert_ne!(prepared.artifact_digest(), prepared.input_closure_digest());
    validate_publication_against_prepared(&publication, &prepared).expect("publication binding");

    let prepared_receipt = PreparedProjectionArtifactReceiptV1::new(
        prepared.artifact().projection_id.clone(),
        prepared.artifact().result_digest.clone(),
        prepared.artifact_digest().clone(),
        prepared.checkpoint().artifact_bytes,
    )
    .expect("prepared receipt");
    validate_prepared_artifact_receipt(&prepared, &prepared_receipt).expect("CAS binding");
    let receipt = ProjectionPublicationReceiptV1::from_publication(
        &publication,
        PublicationCommitStatus::Accepted,
    );
    receipt
        .validate_against(&publication)
        .expect("publication receipt binding");
    let retry_receipt = ProjectionPublicationReceiptV1::from_publication(
        &publication,
        PublicationCommitStatus::Idempotent,
    );
    retry_receipt
        .validate_against(&publication)
        .expect("idempotent retry receipt binding");
    assert_ne!(receipt.status, retry_receipt.status);

    let cockpit = finalize_cockpit_publication(
        cockpit_draft("cockpit-001", "scene-001", None),
        &publication,
        context(12),
        None,
    )
    .expect("cockpit publication");
    let cockpit_receipt =
        CockpitPublicationReceiptV1::from_publication(&cockpit, PublicationCommitStatus::Accepted);
    cockpit_receipt
        .validate_against(&cockpit)
        .expect("cockpit receipt binding");
    let cockpit_retry_receipt = CockpitPublicationReceiptV1::from_publication(
        &cockpit,
        PublicationCommitStatus::Idempotent,
    );
    cockpit_retry_receipt
        .validate_against(&cockpit)
        .expect("idempotent cockpit retry receipt binding");
    assert_ne!(cockpit_receipt.status, cockpit_retry_receipt.status);

    let mut substituted_cockpit_receipt = cockpit_receipt;
    substituted_cockpit_receipt.cockpit_publication_digest = substituted_cockpit_receipt
        .projection_publication_digest
        .clone();
    assert!(matches!(
        substituted_cockpit_receipt.validate_against(&cockpit),
        Err(PublicationError::ReceiptMismatch)
    ));

    let mut substituted = receipt;
    substituted.result_digest = substituted.artifact_digest.clone();
    assert!(matches!(
        substituted.validate_against(&publication),
        Err(PublicationError::ReceiptMismatch)
    ));
}

#[test]
fn immutable_queries_validate_id_and_each_digest_domain() {
    let (prepared, publication) = first_publication();
    let queries = [
        ProjectionPublicationQueryV1::PublicationId {
            publication_id: publication.publication_id.clone(),
        },
        ProjectionPublicationQueryV1::PublicationDigest {
            publication_digest: publication.publication_digest.clone(),
        },
        ProjectionPublicationQueryV1::ArtifactDigest {
            artifact_digest: publication.artifact_digest.clone(),
        },
        ProjectionPublicationQueryV1::ResultDigest {
            result_digest: publication.result_digest.clone(),
        },
    ];
    let loaded = LoadedProjectionPublicationV1 {
        publication: publication.clone(),
        artifact: prepared.artifact().clone(),
        artifact_bytes: prepared.bytes().to_vec(),
    };
    for query in &queries {
        loaded.validate(query).expect("exact immutable query");
    }

    let substituted = ProjectionPublicationQueryV1::ArtifactDigest {
        artifact_digest: publication.result_digest.clone(),
    };
    assert!(matches!(
        loaded.validate(&substituted),
        Err(PublicationError::QueryMismatch)
    ));
}

#[test]
fn selection_never_turns_stale_unsupported_missing_or_conflict_into_zero() {
    let (_, prior) = first_publication();
    let current = second_publication(&prior);
    let policy = stable("newest_append_only_publication_at_explicit_cutoff_v1");
    let fresh = select_projection_publication(
        policy.clone(),
        CommitSeq::new(20),
        CommitSeq::new(30),
        ProjectionSelectionInput::Found(current.clone()),
    )
    .expect("fresh");
    assert!(matches!(
        fresh.state,
        ProjectionSelectionStateV1::Fresh { .. }
    ));

    let stale = select_projection_publication(
        policy.clone(),
        CommitSeq::new(20),
        CommitSeq::new(30),
        ProjectionSelectionInput::Found(prior.clone()),
    )
    .expect("stale");
    assert!(matches!(
        stale.state,
        ProjectionSelectionStateV1::Stale { lag_commits, .. } if lag_commits.get() == 10
    ));
    let unsupported = select_projection_publication(
        policy.clone(),
        CommitSeq::new(20),
        CommitSeq::new(30),
        ProjectionSelectionInput::Unsupported {
            reason: stable("dlmm_accrual_profile_unsupported"),
            prior: Some(prior.clone()),
        },
    )
    .expect("unsupported");
    assert!(matches!(
        unsupported.state,
        ProjectionSelectionStateV1::Unsupported { prior: Some(_), .. }
    ));
    let missing = select_projection_publication(
        policy.clone(),
        CommitSeq::new(20),
        CommitSeq::new(30),
        ProjectionSelectionInput::Missing {
            reason: stable("no_publication_for_controlled_domain"),
        },
    )
    .expect("missing");
    assert!(matches!(
        missing.state,
        ProjectionSelectionStateV1::Missing { .. }
    ));

    let mut alternate_draft =
        projection_draft("projection-002-alternate", Some("projection-001"), 20);
    alternate_draft.request_digest = digest('2');
    let alternate_prepared =
        prepare_projection(build_projection(alternate_draft).expect("alternate projection"))
            .expect("alternate prepare");
    let alternate = finalize_projection_publication(
        &alternate_prepared,
        publication_draft("publication-002-alternate", Some("publication-001")),
        context(22),
        Some(&prior),
    )
    .expect("alternate publication");
    let conflict = select_projection_publication(
        policy,
        CommitSeq::new(20),
        CommitSeq::new(30),
        ProjectionSelectionInput::Conflicting {
            reason: stable("named_policy_found_two_unsuperseded_candidates"),
            candidates: vec![current, alternate],
        },
    )
    .expect("conflict");
    assert!(matches!(
        conflict.state,
        ProjectionSelectionStateV1::Conflicting { ref candidates, .. }
            if candidates.len() == 2
    ));

    for selection in [fresh, stale, unsupported, missing, conflict] {
        let json =
            String::from_utf8(projection_selection_bytes(&selection).expect("selection JSON"))
                .expect("UTF-8");
        assert!(!json.contains("null"));
        assert!(!json.contains("\"value\":0"));
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FailStage {
    None,
    Prepare,
    Commit,
    Head,
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
#[error("fault injected at durable publication boundary")]
struct FakeStoreError;

#[derive(Clone, Debug)]
struct FakeStore {
    next_commit: u64,
    fail: FailStage,
    prepared: BTreeMap<String, Vec<u8>>,
    publications: Vec<LoadedProjectionPublicationV1>,
    heads: Vec<CockpitPublicationV1>,
}

impl FakeStore {
    fn new() -> Self {
        Self {
            next_commit: 100,
            fail: FailStage::None,
            prepared: BTreeMap::new(),
            publications: Vec::new(),
            heads: Vec::new(),
        }
    }

    fn context(&mut self) -> PublicationCommitContext {
        let value = context(self.next_commit);
        self.next_commit += 1;
        value
    }

    fn visible_head(&self, policy: &str) -> Option<&CockpitPublicationV1> {
        self.heads
            .iter()
            .filter(|value| value.query_policy.as_str() == policy)
            .max_by_key(|value| value.commit_seq)
    }

    fn query(&self, query: &ProjectionPublicationQueryV1) -> Option<LoadedProjectionPublicationV1> {
        self.publications
            .iter()
            .find(|value| query.validate_loaded(&value.publication).is_ok())
            .cloned()
    }
}

impl ProjectionPublicationStore for FakeStore {
    type Error = FakeStoreError;

    fn prepare_projection_artifact(
        &mut self,
        prepared: &PreparedProjection,
    ) -> Result<PreparedProjectionArtifactReceiptV1, Self::Error> {
        if self.fail == FailStage::Prepare {
            return Err(FakeStoreError);
        }
        self.prepared.insert(
            prepared.artifact_digest().to_string(),
            prepared.bytes().to_vec(),
        );
        PreparedProjectionArtifactReceiptV1::new(
            prepared.artifact().projection_id.clone(),
            prepared.artifact().result_digest.clone(),
            prepared.artifact_digest().clone(),
            prepared.checkpoint().artifact_bytes,
        )
        .map_err(|_| FakeStoreError)
    }

    fn commit_projection_publication(
        &mut self,
        prepared: &PreparedProjection,
        prepared_receipt: &PreparedProjectionArtifactReceiptV1,
        draft: ProjectionPublicationDraft,
        previous: Option<&ProjectionPublicationV1>,
    ) -> Result<CommittedProjectionPublicationV1, Self::Error> {
        validate_prepared_artifact_receipt(prepared, prepared_receipt)
            .map_err(|_| FakeStoreError)?;
        if self.fail == FailStage::Commit {
            return Err(FakeStoreError);
        }
        let publication =
            finalize_projection_publication(prepared, draft, self.context(), previous)
                .map_err(|_| FakeStoreError)?;
        let receipt = ProjectionPublicationReceiptV1::from_publication(
            &publication,
            PublicationCommitStatus::Accepted,
        );
        self.publications.push(LoadedProjectionPublicationV1 {
            publication: publication.clone(),
            artifact: prepared.artifact().clone(),
            artifact_bytes: prepared.bytes().to_vec(),
        });
        Ok(CommittedProjectionPublicationV1 {
            publication,
            receipt,
        })
    }

    fn append_cockpit_publication(
        &mut self,
        draft: CockpitPublicationDraft,
        projection: &ProjectionPublicationV1,
        previous: Option<&CockpitPublicationV1>,
    ) -> Result<CommittedCockpitPublicationV1, Self::Error> {
        if self.fail == FailStage::Head {
            return Err(FakeStoreError);
        }
        let publication = finalize_cockpit_publication(draft, projection, self.context(), previous)
            .map_err(|_| FakeStoreError)?;
        let receipt = CockpitPublicationReceiptV1::from_publication(
            &publication,
            PublicationCommitStatus::Accepted,
        );
        self.heads.push(publication.clone());
        Ok(CommittedCockpitPublicationV1 {
            publication,
            receipt,
        })
    }

    fn load_projection_publication(
        &self,
        query: &ProjectionPublicationQueryV1,
    ) -> Result<Option<LoadedProjectionPublicationV1>, Self::Error> {
        Ok(self.query(query))
    }
}

fn bootstrap_fake_store() -> (FakeStore, ProjectionPublicationV1, CockpitPublicationV1) {
    let mut store = FakeStore::new();
    let artifact =
        build_projection(projection_draft("projection-001", None, 10)).expect("prior projection");
    let publication = publish_projection(
        &mut store,
        artifact,
        publication_draft("publication-001", None),
        None,
    )
    .expect("prior publication")
    .publication;
    let head = append_cockpit_head(
        &mut store,
        cockpit_draft("cockpit-001", "scene-001", None),
        &publication,
        None,
    )
    .expect("prior head")
    .publication;
    (store, publication, head)
}

#[test]
#[allow(clippy::too_many_lines)] // One fault matrix proves every prepare/commit/head boundary.
fn crash_matrix_exposes_only_prior_complete_or_new_complete_publication() {
    let (base, prior, prior_head) = bootstrap_fake_store();
    let policy = prior_head.query_policy.to_string();
    let query_new = ProjectionPublicationQueryV1::PublicationId {
        publication_id: ProjectionPublicationId::new("publication-002").expect("new ID"),
    };

    let mut prepare_crash = base.clone();
    prepare_crash.fail = FailStage::Prepare;
    assert!(
        publish_projection(
            &mut prepare_crash,
            second_artifact(),
            publication_draft("publication-002", Some("publication-001")),
            Some(&prior),
        )
        .is_err()
    );
    assert_eq!(
        prepare_crash
            .visible_head(&policy)
            .expect("prior head")
            .cockpit_publication_id,
        prior_head.cockpit_publication_id
    );
    assert!(prepare_crash.query(&query_new).is_none());
    assert_eq!(prepare_crash.prepared, base.prepared);

    let mut commit_crash = base.clone();
    commit_crash.fail = FailStage::Commit;
    assert!(
        publish_projection(
            &mut commit_crash,
            second_artifact(),
            publication_draft("publication-002", Some("publication-001")),
            Some(&prior),
        )
        .is_err()
    );
    assert!(commit_crash.query(&query_new).is_none());
    assert_eq!(commit_crash.heads, base.heads);
    assert_eq!(commit_crash.prepared.len(), base.prepared.len() + 1);

    let mut head_crash = base.clone();
    let committed = publish_projection(
        &mut head_crash,
        second_artifact(),
        publication_draft("publication-002", Some("publication-001")),
        Some(&prior),
    )
    .expect("new publication")
    .publication;
    assert!(head_crash.query(&query_new).is_some());
    assert_eq!(
        head_crash
            .visible_head(&policy)
            .expect("prior head after publication commit")
            .cockpit_publication_id,
        prior_head.cockpit_publication_id
    );
    head_crash.fail = FailStage::Head;
    assert!(
        append_cockpit_head(
            &mut head_crash,
            cockpit_draft("cockpit-002", "scene-002", Some("cockpit-001")),
            &committed,
            Some(&prior_head),
        )
        .is_err()
    );
    assert_eq!(
        head_crash
            .visible_head(&policy)
            .expect("prior still visible")
            .cockpit_publication_id,
        prior_head.cockpit_publication_id
    );

    head_crash.fail = FailStage::None;
    let new_head = append_cockpit_head(
        &mut head_crash,
        cockpit_draft("cockpit-002", "scene-002", Some("cockpit-001")),
        &committed,
        Some(&prior_head),
    )
    .expect("new head")
    .publication;
    assert_eq!(
        head_crash
            .visible_head(&policy)
            .expect("new visible head")
            .cockpit_publication_id,
        new_head.cockpit_publication_id
    );
    assert_eq!(head_crash.heads.len(), 2);
}

#[test]
fn finalized_contract_rejects_provisional_projection_or_publication_tags() {
    let mut draft = projection_draft("projection-provisional", None, 10);
    draft.input.as_of.chain.as_mut().expect("chain").finality =
        OpenVariant::known("processed").expect("processed finality");
    assert!(build_projection(draft).is_err());

    let (_, publication) = first_publication();
    let mut value = serde_json::to_value(publication).expect("publication JSON");
    value["finality"] = serde_json::Value::String("provisional".into());
    assert!(serde_json::from_value::<ProjectionPublicationV1>(value).is_err());
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct VectorManifest {
    contract: String,
    schema_version: u16,
    golden: Golden,
    crash_cases: Vec<CrashCase>,
    selection_cases: Vec<String>,
}

#[derive(Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Golden {
    artifact_bytes: String,
    artifact_digest: String,
    result_digest: String,
    input_closure_digest: String,
    checkpoint_digest: String,
    publication_bytes: String,
    publication_digest: String,
    cockpit_bytes: String,
    cockpit_publication_digest: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CrashCase {
    stage: String,
    visible: String,
    new_queryable: bool,
}

#[test]
fn language_neutral_manifest_pins_exact_bytes_digests_and_closed_cases() {
    let manifest: VectorManifest = serde_json::from_str(VECTORS).expect("strict vector manifest");
    assert_eq!(manifest.contract, "joshi.publication_vectors");
    assert_eq!(manifest.schema_version, 1);
    assert_eq!(manifest.crash_cases.len(), 6);
    assert_eq!(
        manifest
            .crash_cases
            .iter()
            .map(|value| value.stage.as_str())
            .collect::<Vec<_>>(),
        [
            "before_prepare",
            "after_prepare",
            "during_commit",
            "after_commit",
            "during_head",
            "after_head"
        ]
    );
    assert!(
        manifest
            .crash_cases
            .iter()
            .filter(|value| value.new_queryable)
            .all(|value| value.stage == "after_commit"
                || value.stage == "during_head"
                || value.stage == "after_head")
    );
    assert!(
        manifest
            .crash_cases
            .iter()
            .take(5)
            .all(|value| value.visible == "prior_stale")
    );
    assert_eq!(manifest.selection_cases.len(), 5);

    let (prepared, publication) = first_publication();
    let cockpit = finalize_cockpit_publication(
        cockpit_draft("cockpit-001", "scene-001", None),
        &publication,
        context(12),
        None,
    )
    .expect("cockpit");
    let publication_bytes = projection_publication_bytes(&publication).expect("publication bytes");
    let cockpit_bytes = cockpit_publication_bytes(&cockpit).expect("cockpit bytes");
    assert_eq!(ARTIFACT_VECTOR.trim_end().as_bytes(), prepared.bytes());
    assert_eq!(PUBLICATION_VECTOR.trim_end().as_bytes(), publication_bytes);
    assert_eq!(COCKPIT_VECTOR.trim_end().as_bytes(), cockpit_bytes);
    let actual = Golden {
        artifact_bytes: prepared.bytes().len().to_string(),
        artifact_digest: prepared.artifact_digest().to_string(),
        result_digest: prepared.artifact().result_digest.to_string(),
        input_closure_digest: prepared.input_closure_digest().to_string(),
        checkpoint_digest: prepared.checkpoint().checkpoint_digest.to_string(),
        publication_bytes: publication_bytes.len().to_string(),
        publication_digest: publication.publication_digest.to_string(),
        cockpit_bytes: cockpit_bytes.len().to_string(),
        cockpit_publication_digest: cockpit.cockpit_publication_digest.to_string(),
    };
    assert_eq!(manifest.golden, actual);

    let canonical = serde_json_canonicalizer::to_vec(
        &serde_json::from_str::<serde_json::Value>(VECTORS).expect("fixture JSON"),
    )
    .expect("canonical fixture");
    let reparsed = serde_json_canonicalizer::to_vec(
        &serde_json::from_slice::<serde_json::Value>(&canonical).expect("canonical JSON"),
    )
    .expect("recanonicalized fixture");
    assert_eq!(canonical, reparsed);
}
