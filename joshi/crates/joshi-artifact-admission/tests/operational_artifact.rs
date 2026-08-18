use joshi_artifact_admission::{
    ArtifactAdmissionError, StoreResolvedChartSamplesV1, StoreResolvedParquetPartV2,
    validate_derived_artifact_v2, validate_derived_artifact_v2_part,
};
use joshi_domain::{StableString, ValueDigest};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

const ARTIFACT: &str = "../../fixtures/artifact/derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55";

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(ARTIFACT)
}

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("stable test value")
}

fn digest(value: &str) -> ValueDigest {
    ValueDigest::new(value).expect("test digest")
}

fn artifact_part(root: &Path) -> StoreResolvedParquetPartV2 {
    StoreResolvedParquetPartV2 {
        path: root.join("descriptive_chart_shapes.parquet"),
        relative_path: stable("descriptive_chart_shapes.parquet"),
        schema_id: stable("joshi.analysis.descriptive-chart-shape/v2"),
        schema_digest: digest(
            "sha256:e86c6fec68c8f6fa24b512fafb5cfd48caabe673f9872ccfa030b97d822aaff7",
        ),
        physical_digest: digest(
            "sha256:37ac32ee54b10f5558ed8bf724a576f5242d4a8ece1fe87c487723b5959b79b0",
        ),
        logical_digest: digest(
            "sha256:6e08dc1a38d278ccf38744c5c58ba29861ae9339fa5f05725000c510fe8c910f",
        ),
        byte_length: 4439,
        row_count: 0,
    }
}

fn chart_samples() -> StoreResolvedChartSamplesV1 {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("workspace")
        .to_owned();
    StoreResolvedChartSamplesV1 {
        snapshot_id: digest(
            "sha256:e9ecd5990b24c88650ebed19b4afa8c3b60d647948865fe3d2cac9df6fd71845",
        ),
        snapshot_manifest_digest: digest(
            "sha256:4fb25f95de1568b0c68c0e61ad64aa5b2a9f9b516979caa1075dff9e99c2475f",
        ),
        part: StoreResolvedParquetPartV2 {
            path: workspace.join("fixtures/export/operational_snapshot_v2/chart_samples.parquet"),
            relative_path: stable("chart_samples.parquet"),
            schema_id: stable("joshi.analysis.chart-sample/v1"),
            schema_digest: digest(
                "sha256:0ddd21d4a5df4db60e19b5262d2bac08e84c87d567c3b27d003f8f164ca2f9c3",
            ),
            physical_digest: digest(
                "sha256:460d599fe424f1a59922318f8b5fb6f7868dd54776cce4e7a1a1f91a5dd38b33",
            ),
            logical_digest: digest(
                "sha256:4025cebaba910b1477edd3ecba91f2fbd8af95bf0645439358740a2b670c5c61",
            ),
            byte_length: 3204,
            row_count: 0,
        },
    }
}

fn copy_fixture(destination: &Path) {
    fs::create_dir(destination).expect("create artifact copy");
    for name in ["manifest.json", "descriptive_chart_shapes.parquet"] {
        fs::copy(fixture().join(name), destination.join(name)).expect("copy fixture file");
    }
}

#[test]
fn independently_reads_operational_v2_artifact_with_no_authority() {
    let value = validate_derived_artifact_v2(&fixture()).expect("operational artifact");
    assert_eq!(
        value.artifact_id().as_str(),
        "sha256:759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55"
    );
    assert_eq!(
        value.snapshot_id().as_str(),
        "sha256:e9ecd5990b24c88650ebed19b4afa8c3b60d647948865fe3d2cac9df6fd71845"
    );
    assert_eq!(value.publication_ids()[0].as_str(), "publication-001");
    assert_eq!(
        value.analysis_run_id().as_str(),
        "analysis-run-production-fixture-001"
    );
    assert_eq!(
        value.claim_scope().as_str(),
        "descriptive_only_not_predictive_or_strategy_claim"
    );
    assert_eq!(
        (
            value.uncertainty().0.as_str(),
            value.uncertainty().1.as_str()
        ),
        ("not_estimated", "deterministic_descriptive_transform")
    );
    assert_eq!(value.support(), (0, 0, 0));
    assert!(value.rows().is_empty());
}

#[test]
fn store_resolved_part_uses_the_same_physical_and_semantic_validation() {
    let root = fixture();
    let manifest = fs::read(root.join("manifest.json")).expect("manifest bytes");
    let value =
        validate_derived_artifact_v2_part(&manifest, &artifact_part(&root), &chart_samples())
            .expect("store-resolved part");
    assert_eq!(
        value.artifact_id().as_str(),
        "sha256:759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55"
    );
    assert!(value.rows().is_empty());
}

#[test]
fn incomplete_or_different_store_descriptor_is_refused() {
    let root = fixture();
    let manifest = fs::read(root.join("manifest.json")).expect("manifest bytes");
    let mut part = artifact_part(&root);
    part.byte_length += 1;
    let error = validate_derived_artifact_v2_part(&manifest, &part, &chart_samples())
        .expect_err("different store descriptor");
    assert!(error.to_string().contains("store-resolved"));
}

#[test]
fn altered_parquet_bytes_are_refused() {
    let temporary = tempfile::tempdir().expect("temporary root");
    let artifact = temporary.path().join("artifact");
    copy_fixture(&artifact);
    let part = artifact.join("descriptive_chart_shapes.parquet");
    let mut bytes = fs::read(&part).expect("part bytes");
    bytes.push(0);
    fs::write(part, bytes).expect("tamper part");
    assert!(matches!(
        validate_derived_artifact_v2(&artifact),
        Err(ArtifactAdmissionError::Digest(_))
    ));
}

#[test]
fn self_rehashed_future_known_manifest_is_refused() {
    let temporary = tempfile::tempdir().expect("temporary root");
    let artifact = temporary.path().join("artifact");
    copy_fixture(&artifact);
    let manifest_path = artifact.join("manifest.json");
    let mut value: Value =
        serde_json::from_slice(&fs::read(&manifest_path).expect("manifest bytes"))
            .expect("manifest JSON");
    value["fit"]["maximum_input_available_at"] =
        Value::String("2099-01-01T00:00:00.000000Z".into());
    let mut preimage = value.clone();
    preimage
        .as_object_mut()
        .expect("object")
        .remove("artifact_id");
    value["artifact_id"] = Value::String(format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(&preimage).expect("canonical JSON"))
    ));
    let mut bytes = serde_json::to_vec(&value).expect("canonical manifest");
    bytes.push(b'\n');
    fs::write(manifest_path, bytes).expect("write manifest");
    let error = validate_derived_artifact_v2(&artifact).expect_err("future-known refusal");
    assert!(error.to_string().contains("future-known"));
}
