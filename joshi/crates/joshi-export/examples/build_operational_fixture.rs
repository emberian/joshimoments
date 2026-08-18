//! Build the checked operational Snapshot V2 witness from an immutable V8 catalog backup.

use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_export::{
    OperationalExportRequestV2, OperationalPublicationV2, ProjectionPublicationInputV2,
    PythonValidatorV2, export_operational_snapshot_v2,
};
use std::{env, path::PathBuf};

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("fixture stable identity")
}

fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("fixture digest")
}

fn main() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .expect("workspace root")
        .to_owned();
    let mut arguments = env::args_os().skip(1);
    let catalog = arguments.next().map_or_else(
        || workspace.join("tmp/w4export/catalog-v8.sqlite"),
        PathBuf::from,
    );
    let destination = arguments.next().map_or_else(
        || workspace.join("fixtures/export/operational_snapshot_v2"),
        PathBuf::from,
    );
    assert!(
        arguments.next().is_none(),
        "expected at most catalog and destination"
    );
    let request = OperationalExportRequestV2 {
        catalog_snapshot_path: catalog,
        catalog_id: stable("catalog-publication-test"),
        catalog_schema: stable("joshi.sqlite.v8"),
        from_commit_seq: CommitSeq::new(1),
        through_commit_seq: CommitSeq::new(13),
        export_request_id: stable("export-production-fixture-001"),
        producer_build: stable("joshi-export-operational-fixture-v2"),
        created_at: "2026-08-17T12:00:00.000000Z"
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
        coverage_window_ids: vec![stable("cov_export_wall")],
        destination,
        python_validator: PythonValidatorV2 {
            program: PathBuf::from("uv"),
            analysis_directory: workspace.join("analysis"),
        },
    };
    let artifact = export_operational_snapshot_v2(&request).expect("operational fixture export");
    println!("{}", artifact.snapshot_id());
}
