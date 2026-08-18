//! Build the deterministic nonempty Wave 5 G0 V10 catalog from the frozen V8 fixture.

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_projection::ProjectionAuthority;
use joshi_publication::{
    COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT, COCKPIT_V2_SCHEMA_VERSION,
    CockpitPublicationId, CockpitV2Ceiling, CockpitV2CoverageRefV1, CockpitV2CoverageState,
    CockpitV2CutoffV1, CockpitV2GapRefV1, CockpitV2HeadV1, CockpitV2MembershipKind,
    CockpitV2MembershipRefV1, CockpitV2ObservedUniverseRefV1, CockpitV2OmissionV1,
    CockpitV2ResolvedSourceFactsInputV1, CockpitV2SourceFactRefV1, CockpitV2SurfaceFieldRefV1,
    CockpitV2SurfaceProfileRefV1, ProtectionDomain, finalize_cockpit_v2,
    prepare_cockpit_v2_from_resolved_source_facts,
};
use joshi_scientific_memory::{
    ActId, ActKind, CatalogCommitSeq, Digest as MemoryDigest, Episode, EpisodeCompleteness,
    EpisodeId, LogicalSessionTick, MemoryOccurrence, OperatorAct, PresentationBinding,
    PresentationGap, PresentationGapReason, SceneBinding, SceneId, SceneRef, SessionId,
};
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf, str::FromStr};

const MIGRATIONS: [(i64, &str, &str); 2] = [
    (
        9,
        "0009_wave5_living_instrument.sql",
        include_str!("../../../schema/migrations/0009_wave5_living_instrument.sql"),
    ),
    (
        10,
        "0010_wave5_g0_store_spine.sql",
        include_str!("../../../schema/migrations/0010_wave5_g0_store_spine.sql"),
    ),
];

fn raw_digest(bytes: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(bytes.as_ref()))
}

fn bytes(value: &str) -> Vec<u8> {
    value.as_bytes().to_vec()
}

fn stable(value: impl Into<String>) -> StableString {
    StableString::new(value).expect("stable string")
}

fn qualified(raw: impl Into<String>) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", raw.into())).expect("qualified digest")
}

fn timestamp(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("timestamp")
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceOccurrenceWire {
    contract: StableString,
    schema_version: u16,
    source_occurrence_id: StableString,
    run_registration_id: StableString,
    catalog_admission_id: StableString,
    source_receipt_digest: ValueDigest,
    source_id: StableString,
    surface_profile: CockpitV2SurfaceProfileRefV1,
    facts: Vec<CockpitV2SourceFactRefV1>,
    eligible_subjects: Vec<StableString>,
    memberships: Vec<CockpitV2MembershipRefV1>,
    coverage: Vec<CockpitV2CoverageRefV1>,
    gaps: Vec<CockpitV2GapRefV1>,
    rendered_subjects: Vec<StableString>,
    omissions: Vec<CockpitV2OmissionV1>,
    known_through_commit_seq: CommitSeq,
    maximum_input_available_at: UtcTimestamp,
    protection: ProtectionDomain,
    authority: ProjectionAuthority,
}

#[allow(clippy::too_many_lines)]
fn main() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .expect("workspace")
        .to_owned();
    let destination = env::args_os().nth(1).map_or_else(
        || workspace.join("fixtures/export/operational_catalog_v10.sqlite"),
        PathBuf::from,
    );
    assert!(!destination.exists(), "catalog destination must be absent");
    fs::copy(
        workspace.join("fixtures/export/operational_catalog_v8.sqlite"),
        &destination,
    )
    .expect("copy frozen V8 catalog");
    let mut connection = Connection::open(&destination).expect("open copied catalog");
    connection
        .execute_batch("PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;")
        .expect("configure catalog");
    for (id, name, sql) in MIGRATIONS {
        let transaction = connection.transaction().expect("migration transaction");
        transaction.execute_batch(sql).expect("apply migration");
        transaction
            .execute(
                "INSERT INTO schema_migration
                 (migration_id,name,source_sha256,applied_at_us,sqlite_version)
                 VALUES (?1,?2,?3,?4,'fixture-fixed-sqlite')",
                params![id, name, raw_digest(sql), id],
            )
            .expect("record migration");
        transaction
            .pragma_update(None, "user_version", id)
            .expect("advance schema version");
        transaction.commit().expect("commit migration");
    }
    let transaction = connection.transaction().expect("fixture transaction");
    for commit in 14_i64..=25 {
        transaction
            .execute(
                "INSERT INTO ingest_commit
                 (commit_seq,commit_id,commit_class,committed_wall_us,writer_clock_id,
                  committed_mono_ns,writer_build,prior_commit_digest,commit_digest)
                 VALUES (?1,?2,'fixture',?3,'clock-g0',?4,'g0-fixture',?5,?6)",
                params![
                    commit,
                    format!("cmt_g0_{commit}"),
                    3_000_000 + commit,
                    commit.to_string(),
                    raw_digest(format!("commit-{}", commit - 1)),
                    raw_digest(format!("commit-{commit}")),
                ],
            )
            .expect("insert G0 commit");
    }

    let receipt_bytes = bytes("{\"receipt\":\"public-c0-g0\"}");
    let receipt_sha = raw_digest(&receipt_bytes);
    transaction
        .execute(
            "INSERT INTO spool_catalog_admission
             (segment_id,batch_id,protection_domain,protection_class,segment_sha256,
              segment_byte_length,exact_batch_sha256,exact_policy_sha256,logical_batch_sha256,
              store_admission_sha256,store_commit_seq,receipt_sha256,receipt_bytes,
              receipt_byte_length,recorded_commit_seq)
             VALUES ('segment-g0','batch-g0','public','public_integrity',?1,1,?2,?3,?4,?5,
                     8,?6,?7,?8,8)",
            params![
                raw_digest("segment"),
                raw_digest("batch"),
                raw_digest("policy"),
                raw_digest("logical"),
                raw_digest("admission"),
                receipt_sha,
                receipt_bytes,
                i64::try_from(receipt_bytes.len()).expect("receipt length"),
            ],
        )
        .expect("insert public C0 admission");

    let registration = bytes("{\"run\":\"g0\"}");
    let registration_sha = raw_digest(&registration);
    transaction
        .execute(
            "INSERT INTO wave5_run_registration_v1
             (run_registration_id,registration_sha256,registration_bytes,
              registration_byte_length,build_sha256,build_bytes,build_byte_length,
              source_tree_sha256,source_tree_bytes,source_tree_byte_length,
              configuration_sha256,configuration_bytes,configuration_byte_length,
              budget_sha256,budget_bytes,budget_byte_length,privacy_sha256,privacy_bytes,
              privacy_byte_length,daily_surface_profile_sha256,daily_surface_profile_bytes,
              daily_surface_profile_byte_length,authority,created_commit_seq)
             VALUES ('run-g0',?1,?2,?3,?4,X'62',1,?5,X'73',1,?6,X'63',1,?7,X'64',1,
                     ?8,X'70',1,?9,X'66',1,'read_only_no_execution',14)",
            params![
                registration_sha,
                registration,
                i64::try_from(registration.len()).expect("registration length"),
                raw_digest("b"),
                raw_digest("s"),
                raw_digest("c"),
                raw_digest("d"),
                raw_digest("p"),
                raw_digest("f"),
            ],
        )
        .expect("insert run");
    let spool_binding = bytes("{\"catalogAdmissionId\":\"catalog-g0\"}");
    transaction
        .execute(
            "INSERT INTO wave5_spool_catalog_binding_v1
             (catalog_admission_id,run_registration_id,run_registration_sha256,segment_id,
              batch_id,binding_sha256,binding_bytes,binding_byte_length,authority,
              created_commit_seq)
             VALUES ('catalog-g0','run-g0',?1,'segment-g0','batch-g0',?2,?3,?4,
                     'read_only_no_execution',15)",
            params![
                registration_sha,
                raw_digest(&spool_binding),
                spool_binding,
                i64::try_from(spool_binding.len()).expect("binding length"),
            ],
        )
        .expect("insert spool binding");

    let profile = CockpitV2SurfaceProfileRefV1 {
        profile_id: stable("daily-surface:run-g0"),
        profile_digest: qualified(raw_digest("f")),
        field_cells: vec![CockpitV2SurfaceFieldRefV1 {
            surface_id: stable("pump.discovery.public_c0"),
            source_id: stable("src_fixture_chain"),
            field: stable("mint"),
        }],
    };
    let facts = vec![CockpitV2SourceFactRefV1 {
        fact_id: stable("fact:obs_equal_correction"),
        fact_digest: qualified(raw_digest("obs_equal_correction")),
        surface_id: stable("pump.discovery.public_c0"),
        source_id: stable("src_fixture_chain"),
        subject: stable("mint-hot"),
        field: stable("mint"),
        protection: ProtectionDomain::Public,
        observed_at: timestamp("1970-01-01T00:00:02.000760Z"),
        known_at: timestamp("1970-01-01T00:00:02.000790Z"),
        commit_seq: Some(CommitSeq::new(8)),
    }];
    let memberships = vec![
        CockpitV2MembershipRefV1 {
            subject: stable("mint-cold"),
            membership: CockpitV2MembershipKind::ColdControl,
            observed_at: timestamp("1970-01-01T00:00:02.000760Z"),
            evidence_digest: qualified(raw_digest("membership-cold")),
        },
        CockpitV2MembershipRefV1 {
            subject: stable("mint-hot"),
            membership: CockpitV2MembershipKind::Hot,
            observed_at: timestamp("1970-01-01T00:00:02.000760Z"),
            evidence_digest: qualified(raw_digest("membership-hot")),
        },
    ];
    let coverage = vec![
        CockpitV2CoverageRefV1 {
            surface_id: stable("pump.discovery.public_c0"),
            source_id: stable("src_fixture_chain"),
            subject: stable("mint-cold"),
            field: stable("mint"),
            fact_ids: vec![],
            state: CockpitV2CoverageState::Unavailable,
            coverage_digest: qualified(raw_digest("coverage-cold")),
        },
        CockpitV2CoverageRefV1 {
            surface_id: stable("pump.discovery.public_c0"),
            source_id: stable("src_fixture_chain"),
            subject: stable("mint-hot"),
            field: stable("mint"),
            fact_ids: vec![stable("fact:obs_equal_correction")],
            state: CockpitV2CoverageState::Complete,
            coverage_digest: qualified(raw_digest("coverage-hot")),
        },
    ];
    let gaps = vec![CockpitV2GapRefV1 {
        gap_id: stable("gap-cold-mint"),
        surface_id: stable("pump.discovery.public_c0"),
        source_id: stable("src_fixture_chain"),
        subject: stable("mint-cold"),
        field: stable("mint"),
        reason: stable("unavailable"),
        since: timestamp("1970-01-01T00:00:02.000760Z"),
        until: None,
        evidence_digest: Some(qualified(raw_digest("gap-cold"))),
    }];
    let omissions = vec![CockpitV2OmissionV1 {
        subject: stable("mint-cold"),
        reason: stable("denominator_only"),
        membership: CockpitV2MembershipKind::DenominatorOnly,
    }];
    let maximum_input_available_at = timestamp("1970-01-01T00:00:02.000790Z");
    let source = SourceOccurrenceWire {
        contract: stable("joshi.store.wave5.source_occurrence.v1"),
        schema_version: 1,
        source_occurrence_id: stable("source-g0"),
        run_registration_id: stable("run-g0"),
        catalog_admission_id: stable("catalog-g0"),
        source_receipt_digest: qualified(receipt_sha.clone()),
        source_id: stable("src_fixture_chain"),
        surface_profile: profile.clone(),
        facts: facts.clone(),
        eligible_subjects: vec![stable("mint-cold"), stable("mint-hot")],
        memberships: memberships.clone(),
        coverage: coverage.clone(),
        gaps: gaps.clone(),
        rendered_subjects: vec![stable("mint-hot")],
        omissions: omissions.clone(),
        known_through_commit_seq: CommitSeq::new(8),
        maximum_input_available_at,
        protection: ProtectionDomain::Public,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
    };
    let descriptor = serde_json::to_vec(&source).expect("source descriptor");
    transaction
        .execute(
            "INSERT INTO wave5_source_occurrence_v1
             (source_occurrence_id,run_registration_id,catalog_admission_id,source_id,
              receipt_sha256,descriptor_contract,descriptor_sha256,descriptor_bytes,
              descriptor_byte_length,surface_profile_sha256,fact_count,eligible_subject_count,
              membership_count,coverage_count,gap_count,rendered_subject_count,omission_count,
              hot_subject_count,cold_control_subject_count,known_through_commit_seq,
              maximum_input_available_wall_us,protection_class,authority,created_commit_seq)
             VALUES ('source-g0','run-g0','catalog-g0','src_fixture_chain',?1,
                     'joshi.store.wave5.source_occurrence.v1',?2,?3,?4,?5,1,2,2,2,1,1,1,1,1,
                     8,2000790,'public_integrity','read_only_no_execution',16)",
            params![
                receipt_sha,
                raw_digest(&descriptor),
                descriptor,
                i64::try_from(descriptor.len()).expect("descriptor length"),
                raw_digest("f"),
            ],
        )
        .expect("insert source occurrence");

    let mut universe = CockpitV2ObservedUniverseRefV1 {
        universe_id: stable("universe:run-g0"),
        universe_digest: qualified("0".repeat(64)),
        eligible_count: WireU64::new(2),
        eligible_subjects: source.eligible_subjects.clone(),
    };
    universe.universe_digest = universe.computed_digest().expect("universe digest");
    let resolved_input = CockpitV2ResolvedSourceFactsInputV1 {
        contract: stable(COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT),
        schema_version: COCKPIT_V2_SCHEMA_VERSION,
        surface_profile: profile,
        observed_universe: universe,
        cutoff: CockpitV2CutoffV1 {
            knowledge_at: maximum_input_available_at,
            commit_through: Some(CommitSeq::new(8)),
            chain_slot: None,
        },
        source_facts: facts,
        memberships,
        coverage,
        gaps,
        rendered_subjects: source.rendered_subjects.clone(),
        omissions,
        ordering_policy: stable("store_resolved_membership_then_subject"),
        pagination_policy: stable("store_resolved_complete_partition"),
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        ceiling: CockpitV2Ceiling::UnverifiedSemantic,
    };
    let resolved = resolved_input.canonical_bytes().expect("resolved input");
    let prepared = prepare_cockpit_v2_from_resolved_source_facts(resolved_input)
        .expect("canonical preparation");
    let semantic = prepared.semantic_bytes.clone();
    let container = prepared.container_bytes.clone();
    let checkpoint = serde_json::to_vec(&prepared.checkpoint).expect("checkpoint bytes");
    transaction
        .execute(
            "INSERT INTO cockpit_v2_preparation_v1
             (preparation_id,source_occurrence_id,resolved_input_sha256,resolved_input_bytes,
              resolved_input_byte_length,semantic_sha256,semantic_bytes,semantic_byte_length,
              container_sha256,container_bytes,container_byte_length,checkpoint_sha256,
              checkpoint_bytes,checkpoint_byte_length,through_commit_seq,knowledge_wall_us,
              authority,created_commit_seq)
             VALUES ('preparation-g0','source-g0',?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,
                     8,2000790,'read_only_no_execution',17)",
            params![
                raw_digest(&resolved),
                resolved,
                i64::try_from(resolved.len()).expect("length"),
                prepared
                    .manifest
                    .semantic_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                semantic,
                i64::try_from(semantic.len()).expect("length"),
                prepared
                    .manifest
                    .container_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                container,
                i64::try_from(container.len()).expect("length"),
                prepared
                    .checkpoint
                    .checkpoint_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                checkpoint,
                i64::try_from(checkpoint.len()).expect("length"),
            ],
        )
        .expect("insert Cockpit preparation");
    let publication = finalize_cockpit_v2(
        &prepared,
        CockpitPublicationId::new("cockpit-v2-g0").expect("publication ID"),
        CommitSeq::new(18),
        None,
        None,
    )
    .expect("canonical publication");
    let publication_bytes = publication.canonical_bytes().expect("publication bytes");
    transaction
        .execute(
            "INSERT INTO cockpit_v2_publication_v1
             (publication_id,preparation_id,source_occurrence_id,publication_contract,
              publication_sha256,publication_bytes_sha256,publication_bytes,
              publication_byte_length,semantic_sha256,container_sha256,checkpoint_sha256,
              through_commit_seq,supersedes_publication_id,authority,created_commit_seq)
             VALUES ('cockpit-v2-g0','preparation-g0','source-g0',
                     'joshi.cockpit.v2.publication',?1,?2,?3,?4,?5,?6,?7,8,NULL,
                     'read_only_no_execution',18)",
            params![
                publication
                    .publication_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                raw_digest(&publication_bytes),
                publication_bytes,
                i64::try_from(publication_bytes.len()).expect("publication length"),
                prepared
                    .manifest
                    .semantic_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                prepared
                    .manifest
                    .container_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
                prepared
                    .checkpoint
                    .checkpoint_digest
                    .as_str()
                    .trim_start_matches("sha256:"),
            ],
        )
        .expect("insert Cockpit publication");
    let head = CockpitV2HeadV1::from_publication(&publication).expect("canonical head");
    let head_bytes = head.canonical_bytes().expect("head bytes");
    transaction
        .execute(
            "INSERT INTO cockpit_v2_head_v1
             (publication_id,source_occurrence_id,head_sha256,head_bytes,head_byte_length,
              supersedes_head_publication_id,authority,created_commit_seq)
             VALUES ('cockpit-v2-g0','source-g0',?1,?2,?3,NULL,
                     'read_only_no_execution',19)",
            params![
                head.head_digest.as_str().trim_start_matches("sha256:"),
                head_bytes,
                i64::try_from(head_bytes.len()).expect("head length"),
            ],
        )
        .expect("insert Cockpit head");

    let scene = SceneRef {
        scene_id: SceneId::new("cockpit-v2-g0").expect("scene ID"),
        scene_digest: MemoryDigest::new(publication.publication_digest.to_string())
            .expect("scene digest"),
        catalog_cutoff: CatalogCommitSeq::new(18).expect("catalog cutoff"),
    };
    let act_tick = LogicalSessionTick::new(9_007_199_254_740_993).expect("wide act tick");
    let act = MemoryOccurrence::OperatorAct(OperatorAct {
        act_id: ActId::new("act-g0").expect("act ID"),
        session_id: SessionId::new("session-g0").expect("session ID"),
        occurred_at: act_tick,
        scene: SceneBinding::Committed(scene.clone()),
        presentation: PresentationBinding::Gap(PresentationGap {
            gap_id: "presentation-gap-g0".into(),
            scene: Some(scene),
            reason: PresentationGapReason::Unavailable,
            detected_at: act_tick,
        }),
        kind: ActKind::Notice,
        subject: Some("mint-hot".into()),
        assertion: None,
    });
    let act_bytes = serde_json::to_vec(&act).expect("act bytes");
    transaction
        .execute(
            "INSERT INTO scientific_memory_occurrence_v1
             (occurrence_id,occurrence_kind,occurrence_sha256,occurrence_bytes,
              occurrence_byte_length,session_id,scene_publication_id,opening_act_id,
              closing_act_id,logical_start_tick,logical_end_tick,queue_generation,
              qualification,authority,created_commit_seq)
             VALUES ('act:act-g0','operator_act',?1,?2,?3,'session-g0','cockpit-v2-g0',
                     NULL,NULL,'9007199254740993',NULL,1,
                     'fixture_authority_unverified_semantic','read_only_no_execution',20)",
            params![
                raw_digest(&act_bytes),
                act_bytes,
                i64::try_from(act_bytes.len()).expect("act length"),
            ],
        )
        .expect("insert operator act");
    let episode = MemoryOccurrence::Episode(Episode {
        episode_id: EpisodeId::new("episode-g0").expect("episode ID"),
        session_id: SessionId::new("session-g0").expect("session ID"),
        act_ids: vec![ActId::new("act-g0").expect("act ID")],
        decision_cutoff: LogicalSessionTick::new(9_007_199_254_740_994)
            .expect("wide decision tick"),
        started_at: act_tick,
        ended_at: Some(LogicalSessionTick::new(9_007_199_254_740_994).expect("wide episode end")),
        completeness: EpisodeCompleteness::Partial,
        segments: vec![],
    });
    let episode_bytes = serde_json::to_vec(&episode).expect("episode bytes");
    transaction
        .execute(
            "INSERT INTO scientific_memory_occurrence_v1
             (occurrence_id,occurrence_kind,occurrence_sha256,occurrence_bytes,
              occurrence_byte_length,session_id,scene_publication_id,opening_act_id,
              closing_act_id,logical_start_tick,logical_end_tick,queue_generation,
              qualification,authority,created_commit_seq)
             VALUES ('episode:episode-g0','episode',?1,?2,?3,'session-g0','cockpit-v2-g0',
                     'act:act-g0','act:act-g0','9007199254740993',
                     '9007199254740994',2,'fixture_authority_unverified_semantic',
                     'read_only_no_execution',22)",
            params![
                raw_digest(&episode_bytes),
                episode_bytes,
                i64::try_from(episode_bytes.len()).expect("episode length"),
            ],
        )
        .expect("insert episode");

    let prior_manifest =
        fs::read(workspace.join("fixtures/export/operational_snapshot_v2/manifest.json"))
            .expect("prior validated snapshot manifest");
    let prior_snapshot: Value =
        serde_json::from_slice(&prior_manifest).expect("prior snapshot manifest JSON");
    let prior_snapshot_id = prior_snapshot["snapshot_id"]
        .as_str()
        .expect("prior snapshot ID")
        .to_owned();
    transaction
        .execute(
            "INSERT INTO export_snapshot
         (export_snapshot_id,contract,schema_version,manifest_relative_path,manifest_sha256,
          manifest_byte_length,from_commit_seq,through_commit_seq,scene_id,created_commit_seq)
         VALUES (?1,'joshi.analysis.snapshot/v2',2,'g0-prior/manifest.json',?2,?3,1,13,NULL,14)",
            params![
                prior_snapshot_id,
                raw_digest(&prior_manifest),
                i64::try_from(prior_manifest.len()).expect("manifest length")
            ],
        )
        .expect("insert prior snapshot");
    let validation = bytes("{\"validation\":\"g0\"}");
    transaction
        .execute(
            "INSERT INTO export_validation
         (validation_id,export_snapshot_id,manifest_sha256,rust_validation_sha256,
          python_validation_sha256,validation_sha256,validation_bytes,validation_byte_length,
          validator_build,created_commit_seq)
         VALUES ('validation-g0',?1,?2,?3,?4,?5,?6,?7,'g0-validator',14)",
            params![
                prior_snapshot_id,
                raw_digest(&prior_manifest),
                raw_digest("rust"),
                raw_digest("python"),
                raw_digest(&validation),
                validation,
                i64::try_from(validation.len()).expect("validation length")
            ],
        )
        .expect("insert prior validation");
    let truth = raw_digest("g0-truth");
    transaction
        .execute(
            "INSERT INTO production_export_request_v2
         (export_request_id,validation_id,snapshot_id,snapshot_manifest_sha256,
          truth_fingerprint_sha256,authority,created_commit_seq)
         VALUES ('prior-export-g0','validation-g0',?1,?2,?3,
                 'read_only_no_execution',14)",
            params![prior_snapshot_id, raw_digest(&prior_manifest), truth],
        )
        .expect("insert prior export request");
    let export_binding = bytes("{\"exportBindingId\":\"binding-g0\"}");
    transaction
        .execute(
            "INSERT INTO wave5_export_validation_binding_v1
         (export_binding_id,run_registration_id,run_registration_sha256,export_request_id,
          validation_id,snapshot_id,binding_sha256,binding_bytes,binding_byte_length,
          authority,created_commit_seq)
         VALUES ('binding-g0','run-g0',?1,'prior-export-g0','validation-g0',?2,?3,?4,?5,
                 'read_only_no_execution',23)",
            params![
                registration_sha,
                prior_snapshot_id,
                raw_digest(&export_binding),
                export_binding,
                i64::try_from(export_binding.len()).expect("binding length")
            ],
        )
        .expect("insert export binding");
    let status = bytes("{\"component\":\"export\",\"state\":\"ready\"}");
    transaction
        .execute(
            "INSERT INTO wave5_operational_record_v1
         (record_id,run_registration_id,run_registration_sha256,component,record_kind,state,
          cause,predecessor_record_id,evidence_commit_seq,observed_wall_us,detail_sha256,
          record_sha256,record_bytes,record_byte_length,authority,created_commit_seq)
         VALUES ('status-export-g0','run-g0',?1,'export','status','ready',NULL,NULL,23,
                 3000024,NULL,?2,?3,?4,'read_only_no_execution',24)",
            params![
                registration_sha,
                raw_digest(&status),
                status,
                i64::try_from(status.len()).expect("status length")
            ],
        )
        .expect("insert ready export status");
    let artifact_fixture = workspace.join(
        "fixtures/artifact/derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55",
    );
    let artifact_part = fs::read(artifact_fixture.join("descriptive_chart_shapes.parquet"))
        .expect("validated artifact Parquet");
    let cas_sha = raw_digest(&artifact_part);
    transaction
        .execute(
            "INSERT INTO blob
         (blob_id,created_commit_seq,storage_mode,inline_bytes,relative_path,content_length,
          stored_length,stored_sha256,compression,content_type,content_encoding,retention_class)
         VALUES (?1,25,'inline',?2,NULL,?3,?3,?1,'identity','application/x-parquet',NULL,
                 'public_source')",
            params![
                cas_sha,
                artifact_part,
                i64::try_from(artifact_part.len()).expect("part length")
            ],
        )
        .expect("insert artifact CAS blob");
    transaction
        .execute(
            "INSERT INTO blob_object
         (blob_id,storage_domain,storage_mode,inline_bytes,relative_path,stored_length,
          stored_sha256,compression)
         VALUES (?1,'public_source','inline',?2,NULL,?3,?1,'identity')",
            params![
                cas_sha,
                artifact_part,
                i64::try_from(artifact_part.len()).expect("part length")
            ],
        )
        .expect("insert artifact CAS object");
    let artifact_manifest =
        fs::read(artifact_fixture.join("manifest.json")).expect("validated artifact manifest");
    let artifact_document: Value =
        serde_json::from_slice(&artifact_manifest).expect("artifact manifest JSON");
    let artifact_id = artifact_document["artifact_id"]
        .as_str()
        .expect("artifact ID")
        .to_owned();
    let analysis_run_id = artifact_document["analysis_run_id"]
        .as_str()
        .expect("analysis run ID");
    let maximum_input_available_at = artifact_document["fit"]["maximum_input_available_at"]
        .as_str()
        .expect("maximum availability")
        .parse::<UtcTimestamp>()
        .expect("maximum availability timestamp");
    let maximum_input_available_wall_us: i64 = (maximum_input_available_at
        .as_datetime()
        .unix_timestamp_nanos()
        / 1_000)
        .try_into()
        .expect("maximum availability micros");
    let registration_bytes = bytes("{\"importId\":\"import-g0\"}");
    transaction
        .execute(
            "INSERT INTO wave5_restricted_artifact_v1
         (import_id,run_registration_id,run_registration_sha256,export_binding_id,
          export_request_id,analysis_run_id,artifact_id,artifact_contract,manifest_sha256,
          manifest_bytes,manifest_byte_length,snapshot_id,claim_scope,truth_fingerprint_sha256,
          maximum_input_available_wall_us,registration_sha256,registration_bytes,
          registration_byte_length,authority,created_commit_seq)
         VALUES ('import-g0','run-g0',?1,'binding-g0','prior-export-g0',?2,?3,
                 'joshi.analysis.derived-artifact/v2',?4,?5,?6,?7,'descriptive_noncausal',?8,
                 ?9,?10,?11,?12,'read_only_no_execution',25)",
            params![
                registration_sha,
                analysis_run_id,
                artifact_id,
                raw_digest(&artifact_manifest),
                artifact_manifest,
                i64::try_from(artifact_manifest.len()).expect("artifact manifest length"),
                prior_snapshot_id,
                truth,
                maximum_input_available_wall_us,
                raw_digest(&registration_bytes),
                registration_bytes,
                i64::try_from(registration_bytes.len()).expect("registration length")
            ],
        )
        .expect("insert restricted import");
    transaction
        .execute(
            "INSERT INTO wave5_restricted_artifact_part_v1
         (import_id,part_ordinal,blob_id,storage_domain,physical_sha256,byte_length)
         VALUES ('import-g0',0,?1,'public_source',?1,?2)",
            params![
                cas_sha,
                i64::try_from(artifact_part.len()).expect("part length")
            ],
        )
        .expect("insert restricted import part");
    transaction.commit().expect("commit G0 fixture");

    let defects: i64 = connection
        .query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| {
            row.get(0)
        })
        .expect("foreign key check");
    assert_eq!(defects, 0, "V10 fixture has foreign-key defects");
    connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
        .expect("checkpoint fixture");
    let journal: String = connection
        .query_row("PRAGMA journal_mode=DELETE", [], |row| row.get(0))
        .expect("close fixture journal");
    assert_eq!(journal, "delete");
    drop(connection);
    println!(
        "sha256:{}",
        raw_digest(fs::read(destination).expect("catalog bytes"))
    );
}
