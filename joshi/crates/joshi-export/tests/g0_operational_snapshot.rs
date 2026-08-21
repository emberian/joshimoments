use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_export::{
    G0ImportArtifactReadbackV1, G0ImportPartReadbackV1, OperationalExportRequestV2,
    OperationalPublicationV2, ProjectionPublicationInputV2, PythonValidatorV2,
    export_operational_snapshot_v2, validate_operational_snapshot_v2_directory,
};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};

fn workspace() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace")
        .to_owned()
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("digest")
}

fn artifact_readback(root: &Path) -> G0ImportArtifactReadbackV1 {
    let manifest_path = root.join("manifest.json");
    let manifest: Value =
        serde_json::from_slice(&fs::read(&manifest_path).expect("manifest bytes"))
            .expect("manifest JSON");
    let part = &manifest["artifacts"][0];
    G0ImportArtifactReadbackV1 {
        import_id: stable("import-g0"),
        artifact_id: digest(manifest["artifact_id"].as_str().expect("artifact ID")),
        manifest_path,
        parts: vec![G0ImportPartReadbackV1 {
            path: root.join(part["path"].as_str().expect("part path")),
            relative_path: stable(part["path"].as_str().expect("part path")),
            schema_id: stable(part["schema_id"].as_str().expect("schema ID")),
            schema_digest: digest(part["schema_digest"].as_str().expect("schema digest")),
            physical_digest: digest(part["physical_digest"].as_str().expect("physical digest")),
            logical_digest: digest(part["logical_digest"].as_str().expect("logical digest")),
            primary_key: part["primary_key"]
                .as_array()
                .expect("primary key")
                .iter()
                .map(|value| stable(value.as_str().expect("key")))
                .collect(),
            byte_length: part["byte_length"]
                .as_str()
                .expect("byte length")
                .parse()
                .expect("u64 byte length"),
            row_count: part["row_count"]
                .as_str()
                .expect("row count")
                .parse()
                .expect("u64 row count"),
        }],
    }
}

fn request(destination: PathBuf, artifact_root: &Path) -> OperationalExportRequestV2 {
    OperationalExportRequestV2 {
        catalog_snapshot_path: workspace().join("fixtures/export/operational_catalog_v10.sqlite"),
        catalog_id: stable("catalog-publication-test"),
        catalog_schema: stable("joshi.sqlite.v10"),
        from_commit_seq: CommitSeq::new(8),
        through_commit_seq: CommitSeq::new(25),
        export_request_id: stable("export-production-g0-fixture-001"),
        producer_build: stable("joshi-export-operational-g0-fixture-v10"),
        created_at: "2026-08-18T12:00:00.000000Z"
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
        coverage_window_ids: vec![],
        destination,
        python_validator: PythonValidatorV2 {
            program: PathBuf::from("uv"),
            analysis_directory: workspace().join("analysis"),
        },
        g0_import_artifact: Some(artifact_readback(artifact_root)),
    }
}

fn artifact_fixture() -> PathBuf {
    workspace().join(
        "fixtures/artifact/derived-c3bdb466464f40bd262500641b152320a4d2f4d404928e054be7fb9bd0c1ffa5",
    )
}

#[test]
fn nonempty_v10_exports_all_24_relations_and_reopens_cross_runtime() {
    let temporary = tempfile::tempdir().expect("temporary export root");
    let destination = temporary.path().join("snapshot");
    let exported =
        export_operational_snapshot_v2(&request(destination.clone(), &artifact_fixture()))
            .expect("V10 G0 export");
    assert_eq!(exported.tables().len(), 24);
    assert_eq!(exported.rust_validation().table_count(), 24);
    assert_eq!(exported.python_validation().table_count(), 24);
    let reopened =
        validate_operational_snapshot_v2_directory(&destination).expect("restart reopen");
    assert_eq!(reopened.table_count(), 24);
}

#[test]
fn lower_bound_support_and_post_registration_cas_tamper_are_refused() {
    let temporary = tempfile::tempdir().expect("temporary root");
    let mut below_support = request(temporary.path().join("below-support"), &artifact_fixture());
    below_support.from_commit_seq = CommitSeq::new(9);
    assert!(export_operational_snapshot_v2(&below_support).is_err());

    let copied_artifact = temporary.path().join("artifact");
    fs::create_dir(&copied_artifact).expect("artifact directory");
    fs::copy(
        artifact_fixture().join("manifest.json"),
        copied_artifact.join("manifest.json"),
    )
    .expect("copy manifest");
    fs::copy(
        artifact_fixture().join("descriptive_chart_shapes.parquet"),
        copied_artifact.join("descriptive_chart_shapes.parquet"),
    )
    .expect("copy part");
    fs::write(
        copied_artifact.join("descriptive_chart_shapes.parquet"),
        b"tampered",
    )
    .expect("tamper CAS part");
    let tampered = request(temporary.path().join("tampered"), &copied_artifact);
    assert!(export_operational_snapshot_v2(&tampered).is_err());
}
