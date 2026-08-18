# Implementation lane 14: typed scene, command, and export admission

Status: exact Glass/operator admission and the locked Rust Parquet fixture bridge are implemented.
The operator path is mounted by core. The export path is intentionally fixture-scoped and is not
yet a production store projection. All commands remain `evidence_only` / `observe_only`; this lane
has no network, credential, wallet, transaction, or economic authority.

## Outcome

The durable store no longer exposes its structural `SceneCommandBatch` or export-registration
methods as public canonical APIs. Normal callers can reach them only through values whose private
fields prove that exact bytes were parsed and reconciled:

```rust
SqliteStore::commit_operator_v1(
    command: &ValidatedOperatorCommandV1,
    new_scene: Option<&ValidatedGlassViewV1>,
    capture: &OperatorCaptureMetadata,
    committed_at: UtcTimestamp,
    writer_clock_id: StableString,
    committed_mono_ns: u64,
    writer_build: StableString,
) -> Result<joshi_operator::CommandReceiptV1>;

SqliteStore::commit_fixture_export_snapshot_v1(
    snapshot: &ValidatedExportSnapshotV1,
    committed_at: UtcTimestamp,
    writer_build: &StableString,
) -> Result<joshi_export::ExportSnapshotReceiptV1>;
```

`apps/core` mounts the first method at `POST /api/v1/operator/commands`. Core owns HTTP bounds,
authentication, public error mapping, and server wall/monotonic clocks; it does not call the raw
store transaction. Export mounting remains gated on a real store projection, described below.

## Exact Glass scene capability

`crates/joshi-operator::ValidatedGlassViewV1::parse_exact` deserializes the frozen
`joshi.glass.view` V1 contract with unknown-field rejection, validates every discriminator,
canonical string integer/decimal/digest, identity, clock, ordering, and internal reference, then
requires a byte-for-byte canonical re-encoding. It derives rather than accepts separate indexes:

- scene/mode/basis/catalog/render clocks;
- sorted sources and every scoped cursor;
- projection name/version/state digest;
- rendered candidate rank and ordinal; and
- distinct evidence references with source, class, observed/ingested/known clocks.

All payload knowledge clocks must be at or before `renderedAt`. Store admission then proves the
catalog cutoff exists; every source delivery/receive/cursor tuple equals the authoritative
as-known query; every projection names an exact checkpoint at the cutoff with the same state
digest; and every V1 evidence reference resolves to an observation at or before the cutoff with
the exact source and three printed clocks. A witnessed scene gets only a knowledge cutoff. A
retrospective scene inherits its basis scene's knowledge cutoff and uses the new catalog cutoff as
its outcome cutoff.

The only inferred choice membership is `rendered`, derived from the exact candidate array. The
code deliberately does not infer `eligible`, `surfaced`, `viewport`, `interacted`, or `compared`.
An optional screenshot is a separate exact artifact. Intended presentation policy,
per-occurrence assignment, and actual exposure are three different facts.

The Rust boundary is slightly narrower than the TypeScript syntax boundary where durable domain
strings cap identities at 512 bytes. Frozen V1 also accepts signed decimal `-0` because the current
TypeScript contract does; changing that acceptance set requires a new version, not a silent Rust
rewrite.

## Typed operator command

`ValidatedOperatorCommandV1` parses all eleven frozen variants with a strict kind-specific
payload and canonical bytes:

`record_focus`, `nominate_candidate`, `request_hot_scope`, `record_disposition`,
`record_crackle_family`, `record_gesture`, `record_annotation`, `record_choice_set`,
`record_post_action_report`, `link_interview`, and `compensate_command`.

The server derives the payload and full-command SHA-256 digests. Admission requires exact
scene/view binding, rejects candidate references absent from that exact view, proves referenced
prior commands exist, and prevents self-compensation. Compensation is a new append-only command;
it never edits or deletes its predecessor. The stored row and canonical payload together bind all
V1 command fields. An exact retry is reconstructed and compared field-by-field before returning
the original commit as `idempotent`; changing content under command/session-sequence/idempotency
identity is a conflict. The public recursive receipt is a separate camel-case DTO and includes the
catalog, batch and command identities, payload/full-command digests, scene/view closure, commit,
and status.

V1 has no `presentationId` or presentation digest. It must not silently acquire them. Future
choice-sensitive commands need command V2 or a separately admitted exact command-to-presentation
artifact. A digest-only policy reference is not admission proof because the store must possess and
verify the exact policy, bundle, assignment, and exposure bytes.

## Rust Arrow/Parquet fixture bridge

`crates/joshi-export::rewrite_snapshot_v1` consumes the locked Python snapshot fixture and writes
all fourteen tables through Rust Arrow/Parquet using Parquet V2, Zstd, deterministic table order,
and no dictionary encoding. Before returning a private capability it:

1. rejects a non-regular/bounded manifest and duplicate JSON keys at any nesting depth;
2. verifies the source manifest self-hash and exact fourteen-table/schema/primary-key closure;
3. verifies each source physical, schema, and canonical logical relation digest;
4. rewrites and re-reads typed rows, then recomputes row count, byte length, schema, logical, and
   physical digests;
5. replaces the producer build, recomputes `snapshot_id` from the manifest without that field,
   writes canonical compact JSON plus one newline, and installs the directory by atomic rename.

The store requires matching catalog ID, frozen public catalog schema, closed commit range, and an
exact projection checkpoint/state digest. It copies and re-hashes the manifest and fourteen files
under immutable snapshot-scoped paths, derives all SQL part drafts from the capability, and commits
one `export_snapshot` plus its exact part closure. `export_snapshot_id == snapshot_id`. The raw
registration digest now binds all snapshot and part metadata, not only paths and file digests.

The checked-in result is `fixtures/export/rust_snapshot_v1`, snapshot
`sha256:00191b83702d221d8d9f67b5214b8b12742033a9f7bd50ca94de5ba2a0680170`.
The locked Python validator accepts it with 20 rows and all fourteen tables.

This is honestly named a fixture rewrite. Rust does not yet reproduce every Python semantic gate
for created/max-decision clocks, row-level bitemporal/provenance, choice/outcome relations, and
coverage consistency. Consequently this capability is not the production store-to-analysis
export path and core readiness must not claim that closure. The next implementation must project
from an as-known store cutoff, either reproduce those validator semantics with adversarial parity
vectors or obtain an independently verified exact validation artifact, and only then expose a
general export endpoint.

## Acquisition clock correction discovered at integration

Browser companion acquisitions carry trustworthy wall clocks and page ordering but no compatible
browser monotonic reading. Reusing core commit `Instant` under the acquisition clock name invents
latency and order. `0006_optional_acquisition_monotonic.sql` therefore makes acquisition
`(local_clock_id, started_mono_ns)` an all-or-none nullable pair. Source/Pump collectors retain
`Some(MonotonicReading)`; companion acquisition start uses `None`; core commit/persist clocks remain
on their actual observation/receipt events. Fresh migration and V4-to-V6 upgrade both require a
clean foreign-key check, and a store test proves `None` persists as `(NULL,NULL)` without a
sentinel/default.

Companion snapshots also do not turn omitted object validity into `unbounded` truth. Core now emits
the specifically namespaced `companion_capture_snapshot_attestation` with semantic key
`companion.capture_snapshot:<natural-key-digest>` and an exact one-millisecond sampled-capture
interval. That interval means only “this browser response reported these bytes at this capture”; it
is prohibited as provider-object or market-event validity. Any effective object assertion still
requires source-supplied validity or a later evidence-backed resolver.

## Verification

The lane runs:

```sh
cargo test -p joshi-operator -p joshi-export -p joshi-store --all-targets
cargo clippy -p joshi-operator -p joshi-export -p joshi-store --all-targets -- -D warnings
cargo doc -p joshi-operator -p joshi-export -p joshi-store --no-deps
./schema/validate.sh
uv --directory analysis run --locked joshi-analysis validate \
  --snapshot ../fixtures/export/rust_snapshot_v1
```

Tests pin both TypeScript golden digests, reject noncanonical/unknown bytes, bind a real typed scene
to an idempotent command, prove unavailable acquisition monotonic storage, reject duplicate
manifest keys, rewrite all fourteen Parquet tables, and register/retry the complete typed snapshot
against an exact projection checkpoint.
