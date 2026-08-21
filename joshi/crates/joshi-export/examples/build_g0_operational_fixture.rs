//! Build the exact nonempty 24-relation Wave 5 G0 operational snapshot fixture.

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_export::{
    G0ImportArtifactReadbackV1, G0ImportPartReadbackV1, OperationalExportRequestV2,
    OperationalPublicationV2, ProjectionPublicationInputV2, PythonValidatorV2,
    export_operational_snapshot_v2,
};
use serde_json::Value;
use std::{env, fs, path::PathBuf};

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("qualified digest")
}

#[allow(clippy::too_many_lines)]
fn main() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .expect("workspace")
        .to_owned();
    let mut arguments = env::args_os().skip(1);
    let catalog = arguments.next().map_or_else(
        || workspace.join("fixtures/export/operational_catalog_v10.sqlite"),
        PathBuf::from,
    );
    let destination = arguments.next().map_or_else(
        || workspace.join("fixtures/export/operational_snapshot_v10"),
        PathBuf::from,
    );
    assert!(
        arguments.next().is_none(),
        "expected at most catalog and destination"
    );

    let artifact_root = workspace.join(
        "fixtures/artifact/derived-c3bdb466464f40bd262500641b152320a4d2f4d404928e054be7fb9bd0c1ffa5",
    );
    let manifest_path = artifact_root.join("manifest.json");
    let artifact_manifest: Value =
        serde_json::from_slice(&fs::read(&manifest_path).expect("artifact manifest bytes"))
            .expect("artifact manifest JSON");
    let part = &artifact_manifest["artifacts"][0];
    let readback = G0ImportArtifactReadbackV1 {
        import_id: stable("import-g0"),
        artifact_id: digest(
            artifact_manifest["artifact_id"]
                .as_str()
                .expect("artifact ID"),
        ),
        manifest_path,
        parts: vec![G0ImportPartReadbackV1 {
            path: artifact_root.join(part["path"].as_str().expect("part path")),
            relative_path: stable(part["path"].as_str().expect("part path")),
            schema_id: stable(part["schema_id"].as_str().expect("schema ID")),
            schema_digest: digest(part["schema_digest"].as_str().expect("schema digest")),
            physical_digest: digest(part["physical_digest"].as_str().expect("physical digest")),
            logical_digest: digest(part["logical_digest"].as_str().expect("logical digest")),
            primary_key: part["primary_key"]
                .as_array()
                .expect("primary key")
                .iter()
                .map(|value| stable(value.as_str().expect("primary key field")))
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
    };
    let request = OperationalExportRequestV2 {
        catalog_snapshot_path: catalog,
        catalog_id: stable("catalog-publication-test"),
        catalog_schema: stable("joshi.sqlite.v10"),
        from_commit_seq: CommitSeq::new(8),
        through_commit_seq: CommitSeq::new(25),
        export_request_id: stable("export-production-g0-fixture-001"),
        producer_build: stable("joshi-export-operational-g0-fixture-v10"),
        created_at: "2026-08-18T12:00:00.000000Z"
            .parse::<UtcTimestamp>()
            .expect("fixture timestamp"),
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
            analysis_directory: workspace.join("analysis"),
        },
        g0_import_artifact: Some(readback),
    };
    let artifact = export_operational_snapshot_v2(&request).expect("G0 operational export");
    assert_eq!(artifact.tables().len(), 24, "exact G0 table profile");
    println!("{}", artifact.snapshot_id());
}
