use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_export::{
    ExportError, OperationalExportRequestV2, OperationalPublicationV2,
    ProjectionPublicationInputV2, PythonValidatorV2, export_operational_snapshot_v2,
    validate_operational_snapshot_v2_directory,
};
use rusqlite::Connection;
use std::{
    fs,
    path::{Path, PathBuf},
};

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("test stable identity")
}

fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("test digest")
}

fn workspace() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace")
        .to_owned()
}

fn copy_snapshot(source: &Path, destination: &Path) {
    fs::create_dir(destination).expect("create snapshot copy");
    for entry in fs::read_dir(source).expect("read snapshot fixture") {
        let entry = entry.expect("snapshot entry");
        fs::copy(entry.path(), destination.join(entry.file_name())).expect("copy snapshot part");
    }
}

fn request(catalog: PathBuf, destination: PathBuf) -> OperationalExportRequestV2 {
    OperationalExportRequestV2 {
        catalog_snapshot_path: catalog,
        catalog_id: stable("catalog-publication-test"),
        catalog_schema: stable("joshi.sqlite.v8"),
        from_commit_seq: CommitSeq::new(1),
        through_commit_seq: CommitSeq::new(13),
        export_request_id: stable("export-production-fixture-001"),
        producer_build: stable("joshi-export-operational-fixture-v2"),
        created_at: "2026-08-17T12:00:00.000000Z"
            .parse::<UtcTimestamp>()
            .expect("timestamp"),
        producer_projection_publication_id: stable("publication-001"),
        publications: vec![OperationalPublicationV2::Projection(
            ProjectionPublicationInputV2 {
                publication_id: stable("publication-001"),
                publication_contract: stable("joshi.projection_publication"),
                publication_digest: digest(
                    "sha256:1524b025b3e615358a53ac410600d0c386b6f18a93d9c1e19708ab034f87cb8d",
                ),
                publication_bytes_digest: digest(
                    "sha256:3b2019584418c9a521e6bb4434733b70916d30a86a7a1f52621ce7a7e429a8b6",
                ),
                projection_id: stable("projection-001"),
                projection_name: stable("joshi.read_projection"),
                projection_version: stable("joshi.projection.v1"),
                result_digest: digest(
                    "sha256:d7c6cbaf0736069a895d126fabeb94ec204bc22285611ba5f5d97098ee34a69b",
                ),
                artifact_digest: digest(
                    "sha256:54a044671521c467a312dd1b66853cda14afd8bf3f430fcc2c00919a91e7f583",
                ),
                input_closure_digest: digest(
                    "sha256:b57ebaf6f3c0edfbc06f63241a0ec52d9cd6330beedfba7cf8bb545b3b949d9b",
                ),
                through_commit_seq: CommitSeq::new(10),
                published_commit_seq: CommitSeq::new(11),
            },
        )],
        coverage_window_ids: vec![stable("cov_export_wall")],
        destination,
        python_validator: PythonValidatorV2 {
            program: PathBuf::from("uv"),
            analysis_directory: workspace().join("analysis"),
        },
        g0_import_artifact: None,
    }
}

#[test]
fn independent_restart_reopen_rehashes_every_manifested_part() {
    let fixture = workspace().join("fixtures/export/operational_snapshot_v2");
    let receipt =
        validate_operational_snapshot_v2_directory(&fixture).expect("independent restart readback");
    assert_eq!(receipt.table_count(), 14);

    let temporary = tempfile::tempdir().expect("temporary snapshot root");
    let copied = temporary.path().join("snapshot");
    copy_snapshot(&fixture, &copied);
    let part = copied.join("chart_samples.parquet");
    let mut bytes = fs::read(&part).expect("chart bytes");
    bytes.push(0);
    fs::write(part, bytes).expect("tamper copied part");
    assert!(validate_operational_snapshot_v2_directory(&copied).is_err());
}

#[test]
fn migrated_operational_catalog_produces_cross_runtime_snapshot_v2() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let value = export_operational_snapshot_v2(&request(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        temporary.path().join("snapshot"),
    ))
    .expect("production export");
    assert_eq!(
        value.snapshot_id().as_str(),
        "sha256:667934d19480a9d6e88181e0b374aff07d5dc58864037630699becbb43938fe6"
    );
    // The catalog holds seven assertions joined to their retained observations by three exact
    // evidence edges. Before the provenance adapter existed the export emitted this relation
    // empty while the rows sat in the store, which is the Wave 5 "refuses every populated table"
    // ceiling; the snapshot identity above moved when that stopped being true.
    let provenance = value
        .tables()
        .iter()
        .find(|table| table.name().as_str() == "provenance_assertions")
        .expect("provenance relation");
    assert_eq!(provenance.row_count(), 3);
    assert_eq!(
        value.export_request_id().as_str(),
        "export-production-fixture-001"
    );
    assert_eq!(
        (
            value.producer_projection().0.as_str(),
            value.producer_projection().1.as_str()
        ),
        ("joshi.read_projection", "joshi.projection.v1")
    );
    assert_eq!(value.tables().len(), 14);
    assert_eq!(
        value.rust_validation().validator(),
        "rust_independent_readback"
    );
    assert_eq!(
        value.python_validation().validator(),
        "python_semantic_validator"
    );
}

#[test]
fn future_known_scene_is_refused_before_publication() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = temporary.path().join("future.sqlite");
    fs::copy(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        &catalog,
    )
    .expect("copy catalog");
    let connection = Connection::open(&catalog).expect("open copied catalog");
    connection
        .execute_batch(
            "INSERT INTO scene
         SELECT 'scn_future_known',scene_mode,captured_commit_seq,knowledge_cutoff_commit_seq,
                outcome_cutoff_commit_seq,basis_scene_id,'future-session',99,ui_build,
                view_contract,view_contract_version,source_mode,4070908800000000,
                client_clock_id,rendered_mono_ns,view_blob_id,screenshot_blob_id,view_sha256
         FROM scene WHERE scene_id='scn_fixture_witnessed';",
        )
        .expect("insert future-known adversary");
    drop(connection);
    let error =
        export_operational_snapshot_v2(&request(catalog, temporary.path().join("snapshot")))
            .expect_err("future-known scene refusal");
    assert!(
        matches!(error, ExportError::Invalid(message) if message.contains("exceeds snapshot creation"))
    );
}

#[test]
fn altered_publication_descriptor_is_refused() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let mut value = request(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        temporary.path().join("snapshot"),
    );
    let OperationalPublicationV2::Projection(publication) = &mut value.publications[0] else {
        panic!("projection fixture")
    };
    publication.publication_bytes_digest =
        digest("sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff");
    let error = export_operational_snapshot_v2(&value).expect_err("descriptor substitution");
    assert!(matches!(error, ExportError::Invalid(message) if message.contains("stored closure")));
}

#[test]
fn selected_wall_coverage_is_nonempty_and_cross_runtime_validated() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = temporary.path().join("coverage.sqlite");
    fs::copy(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        &catalog,
    )
    .expect("copy catalog");
    let connection = Connection::open(&catalog).expect("open copied catalog");
    insert_wall_recovery(&connection);
    drop(connection);
    let mut request = request(catalog, temporary.path().join("snapshot"));
    request.coverage_window_ids = vec![stable("cov_export_wall")];
    let value = export_operational_snapshot_v2(&request).expect("bounded coverage export");
    assert_eq!(value.coverage_window_ids(), &[stable("cov_export_wall")]);
    let rows = |name: &str| {
        value
            .tables()
            .iter()
            .find(|table| table.name().as_str() == name)
            .expect("named table")
            .row_count()
    };
    assert_eq!(rows("coverage_windows"), 1);
    assert_eq!(rows("coverage_gaps"), 1);
}

#[test]
fn selected_open_or_source_cursor_coverage_refuses_without_omission() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let mut value = request(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        temporary.path().join("snapshot"),
    );
    value.coverage_window_ids = vec![stable("cov_fixture_chain")];
    let error = export_operational_snapshot_v2(&value).expect_err("open coverage refusal");
    assert!(
        matches!(error, ExportError::Invalid(message) if message.contains("valid evidence but unrepresentable"))
    );
}

#[test]
fn selected_coverage_ids_must_be_canonical() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let mut value = request(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        temporary.path().join("snapshot"),
    );
    value.coverage_window_ids = vec![stable("z"), stable("a")];
    let error = export_operational_snapshot_v2(&value).expect_err("coverage ordering refusal");
    assert!(
        matches!(error, ExportError::Invalid(message) if message.contains("strictly sorted and unique"))
    );
}

#[test]
fn selected_gap_with_unrepresentable_upper_refuses() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = temporary.path().join("gap-upper.sqlite");
    fs::copy(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        &catalog,
    )
    .expect("copy catalog");
    let connection = Connection::open(&catalog).expect("open copied catalog");
    connection
        .execute_batch(
            "INSERT INTO coverage_gap
             (gap_id,coverage_id,detected_commit_seq,detected_wall_us,cause_code,severity,
              lower_source_locator,upper_source_locator,event_lower_us,event_upper_us)
             VALUES ('gap_export_upper','cov_export_wall',4,2600000,'fixture_upper',
                     'degraded',NULL,NULL,2300000,2400000);
             INSERT INTO coverage_gap_contract
             (gap_id,scope_source_id,scope_family,scope_family_recognition,scope_subject,
              lower_boundary_json,upper_boundary_json,reason_recognition)
             VALUES ('gap_export_upper','src_fixture_chain','market_census','known','mint-fixture',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.300000Z\"}',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.400000Z\"}',
                     'known');",
        )
        .expect("insert upper-bounded gap");
    drop(connection);
    let error =
        export_operational_snapshot_v2(&request(catalog, temporary.path().join("snapshot")))
            .expect_err("gap upper refusal");
    assert!(matches!(error, ExportError::Invalid(message) if message.contains("absent upper")));
}

#[test]
fn selected_partial_recovery_refuses() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = temporary.path().join("partial.sqlite");
    fs::copy(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        &catalog,
    )
    .expect("copy catalog");
    let connection = Connection::open(&catalog).expect("open copied catalog");
    connection
        .execute_batch(
            "INSERT INTO coverage_gap_recovery
             (recovery_id,gap_id,recovery_acquisition_id,commit_seq,recovery_status,
              recovered_through_locator,evidence_blob_id)
             VALUES ('recovery_export_partial','gap_export_wall',NULL,4,'partial',NULL,NULL);
             INSERT INTO coverage_recovery_contract
             (recovery_id,status_recognition,recovered_through_json,available_wall_us)
             VALUES ('recovery_export_partial','known',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.700000Z\"}',
                     2800000);",
        )
        .expect("insert partial recovery");
    drop(connection);
    let error =
        export_operational_snapshot_v2(&request(catalog, temporary.path().join("snapshot")))
            .expect_err("partial recovery refusal");
    assert!(matches!(error, ExportError::Invalid(message) if message.contains("partial")));
}

#[test]
fn unmapped_prospective_protocol_is_not_silently_exported_as_empty_relations() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = temporary.path().join("protocol.sqlite");
    fs::copy(
        workspace().join("fixtures/export/operational_catalog_v8.sqlite"),
        &catalog,
    )
    .expect("copy catalog");
    let connection = Connection::open(&catalog).expect("open copied catalog");
    connection
        .execute_batch(
            "INSERT INTO episode_protocol_v1
         (protocol_registration_id,protocol_definition_id,protocol_revision,protocol_sha256,
          protocol_bytes,protocol_byte_length,build_sha256,configuration_sha256,budget_sha256,
          privacy_sha256,duration_us,warmup_offset_us,choice_deadline_offset_us,
          outcome_horizon_offset_us,knowledge_deadline_offset_us,authority,created_commit_seq)
         VALUES
         ('protocol-reg-adversary','protocol-adversary',1,
          '2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881',
          X'78',1,
          '1111111111111111111111111111111111111111111111111111111111111111',
          '2222222222222222222222222222222222222222222222222222222222222222',
          '3333333333333333333333333333333333333333333333333333333333333333',
          '4444444444444444444444444444444444444444444444444444444444444444',
          100,10,50,200,300,'read_only_no_execution',12);",
        )
        .expect("insert unmapped protocol");
    drop(connection);
    let error =
        export_operational_snapshot_v2(&request(catalog, temporary.path().join("snapshot")))
            .expect_err("green-by-omission refusal");
    assert!(
        matches!(error, ExportError::Invalid(message) if message.contains("without a frozen Snapshot V2 relation adapter"))
    );
}

fn insert_wall_recovery(connection: &Connection) {
    connection
        .execute_batch(
            "INSERT INTO coverage_gap_recovery
             (recovery_id,gap_id,recovery_acquisition_id,commit_seq,recovery_status,
              recovered_through_locator,evidence_blob_id)
             VALUES ('recovery_export_wall','gap_export_wall',NULL,4,'complete',NULL,NULL);
             INSERT INTO coverage_recovery_contract
             (recovery_id,status_recognition,recovered_through_json,available_wall_us)
             VALUES ('recovery_export_wall','known',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.800000Z\"}',
                     2900000);",
        )
        .expect("insert representable coverage");
}

#[test]
fn from_commit_seq_narrows_provenance_and_moves_snapshot_identity() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let catalog = workspace().join("fixtures/export/operational_catalog_v8.sqlite");
    let wide =
        export_operational_snapshot_v2(&request(catalog.clone(), temporary.path().join("wide")))
            .expect("wide export");

    // The catalog carries three assertion/observation evidence edges: two produced at commit 1 and
    // one at commit 8. Raising the lower bound past the first two must remove exactly those rows.
    let mut narrow = request(catalog, temporary.path().join("narrow"));
    narrow.from_commit_seq = CommitSeq::new(8);
    narrow.export_request_id = stable("export-production-fixture-002");
    narrow.coverage_window_ids = Vec::new();
    let narrow = export_operational_snapshot_v2(&narrow).expect("narrow export");

    assert_eq!(provenance_rows(&wide), 3);
    assert_eq!(provenance_rows(&narrow), 1);
    assert_ne!(wide.snapshot_id(), narrow.snapshot_id());
    assert_eq!(
        (wide.commit_range().0.get(), narrow.commit_range().0.get()),
        (1, 8)
    );
}

fn provenance_rows(snapshot: &joshi_export::ValidatedProductionSnapshotV2) -> u64 {
    snapshot
        .tables()
        .iter()
        .find(|table| table.name().as_str() == "provenance_assertions")
        .expect("provenance relation")
        .row_count()
}
