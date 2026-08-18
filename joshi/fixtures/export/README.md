# Rust snapshot V1 fixture

`rust_snapshot_v1/` is produced by `joshi-export` from the locked Python research fixture. Rust
reads and verifies all fourteen source tables, rewrites them through Arrow/Parquet, recomputes every
schema/logical/physical digest and byte/row count, replaces the producer build, and recomputes the
self-hashed manifest. The exact snapshot identity is:

`sha256:00191b83702d221d8d9f67b5214b8b12742033a9f7bd50ca94de5ba2a0680170`

Regenerate into an absent destination:

```sh
cargo run -p joshi-export --example build_fixture
```

Validate with the locked independent consumer:

```sh
uv --directory analysis run --locked joshi-analysis validate \
  --snapshot ../fixtures/export/rust_snapshot_v1
```

Expected closure: `status=valid`, `row_count=20`, and the snapshot ID above.

This artifact is an exact **fixture rewrite**, not yet a production store projection. The Rust
capability rejects structural drift and duplicate JSON object keys, while the locked Python
validator remains authoritative for the full row-level bitemporal, provenance, choice, outcome,
and coverage semantics. Store registration is intentionally named and scoped accordingly.

## Operational Snapshot V2 witness

`operational_catalog_v8.sqlite` is a deterministic synthetic catalog built by applying the exact
eight compiled migrations, recording their SHA-256 ledger, loading the adversarial tape, and
installing one exact finalized projection publication plus one Snapshot V2-representable coverage
window and gap. `operational_snapshot_v2/` is produced by
the production read-only exporter from that catalog at commit 13. It is not a rewrite of the
Python fixture.

The exact identities are:

- catalog bytes: `sha256:b5812f0e6ef903e44049717d572755cdbc94a99721e4c64ed79451c745111e3e`;
- snapshot: `sha256:e9ecd5990b24c88650ebed19b4afa8c3b60d647948865fe3d2cac9df6fd71845`;
- manifest bytes: `sha256:4fb25f95de1568b0c68c0e61ad64aa5b2a9f9b516979caa1075dff9e99c2475f`.

Regenerate into absent temporary destinations and compare the exact bytes:

```sh
cargo run --locked -p joshi-export --example build_operational_catalog_fixture -- \
  /tmp/joshi-operational-catalog.sqlite
cargo run --locked -p joshi-export --example build_operational_fixture -- \
  /tmp/joshi-operational-catalog.sqlite /tmp/joshi-operational-snapshot
uv --directory analysis run --locked joshi-analysis validate \
  --snapshot /tmp/joshi-operational-snapshot
```

The catalog and snapshot builders are fixture tools; production receives an immutable store backup
and store-validated neutral publication descriptor. The exporter verifies the complete migration
ledger, catalog digest before/after, explicit cutoff, publication semantic and exact-byte digests,
fourteen Arrow schemas, logical and physical Parquet digests, and an independent locked Python
receipt before immutable rename.

This witness contains two stored scene rows plus one selected, closed Wall-bounded coverage window
and one open-ended Wall-lower gap. Open/source-cursor/commit/unknown boundaries and partial or
unrecoverable recoveries refuse because Snapshot V2 cannot carry them losslessly. It is not a
prospective decision-study witness. Source/fact artifacts, protocol/launch/session rows, nominations,
abstentions, outcomes, and interviews remain fail-closed until a successor relation set represents
their frozen DTOs.

## Wave 5 G0 V10 exact-byte witness

`operational_catalog_v10.sqlite` extends the frozen V8 witness through migrations 0009/0010 and
canonical public builders. It contains one connected run-rooted source/publication/head/scene,
one exact wide-tick act and partial episode, one ready export binding, and one restricted import
bound to the independently reopened derived-artifact manifest and Parquet CAS part. The source,
publication, head, scene, act, episode, and import-manifest bytes are retained in the Parquet
relations and parsed again after restart by both Rust and locked offline Python.

`operational_snapshot_v10/` contains exactly 24 tables: the legacy fourteen plus the ten frozen
G0 relations. Pairing and backup are deliberately absent; they are separate store/root witnesses,
not analysis relations. Exact fixture identities are:

- catalog: `sha256:7d8d6b677ddf215ae81b0c6be9bd6e359a9b7d4748db585a2eb63a0b89b4593d`;
- snapshot: `sha256:fe6facdcf91733f5bb483a53fbda60ed54d40e4ea1384bcdd8111fadc92ecac0`;
- manifest: `sha256:c3ec855a838a32d3467122170f2e2113a854e169020adf1f1e29783db6a3be2f`.

Regenerate only into absent paths:

```sh
cargo run --locked --offline -p joshi-export --example build_g0_catalog_fixture -- \
  /tmp/joshi-g0-catalog.sqlite
cargo run --locked --offline -p joshi-export --example build_g0_operational_fixture -- \
  /tmp/joshi-g0-catalog.sqlite /tmp/joshi-g0-snapshot
uv run --locked --offline --directory analysis joshi-analysis validate --snapshot \
  /tmp/joshi-g0-snapshot
```

The expected validation receipt reports `table_count=24` and `total_row_count=10`. The public CAS
readback descriptor is neutral and cannot establish store authority; only store-owned orchestration
may resolve it from private state and durably qualify/commit the resulting export.
