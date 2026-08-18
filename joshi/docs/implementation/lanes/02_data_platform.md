# Implementation lane 02: data platform substrate

Status: schema, adversarial fixture, and the bounded `crates/joshi-store` durable slice are
implemented and validated. This lane introduces no network, credential, wallet, transaction, or
economic-authority surface.

## Outcome

The repository now has a real forward-only SQLite boundary at `schema/` and a language-neutral E0
tape at `fixtures/tape/`. The substrate preserves the distinctions most likely to be accidentally
deduplicated:

| Identity | Meaning | Equality is not |
| --- | --- | --- |
| acquisition | one request, connection, poll, recovery, or fixture occurrence | equal bytes |
| observation | one result occurrence within an acquisition | the alleged upstream event |
| blob | SHA-256 identity of exact retained source bytes | an observation or event ID |
| source event | typed provider/chain natural key | its economic value |
| assertion | one producer/version claim, with valid time and system-known commit | permanent truth |
| coverage/gap/cursor | scoped evidence about successful or missing observation | global socket health |
| scene | one witnessed, cutoff, or retrospective view contract | a current recomputation |
| command | one idempotent semantic operator act | a fill or economic capability |
| outbox item | mutable rebuildable work | evidence or a general effects queue |
| export manifest | one immutable file generation over a closed commit range | a mutable analytical store |

Raw evidence, interpretation, delivery to a scene, operator semantics, operational work, and
analytical export therefore do not share a universal event row.

## Artifacts

- `schema/migrations/0001_evidence.sql` creates commits, sources, acquisitions, exact blobs,
  observations, source events, and many-to-many observation/event identity.
- `0002_assertions_coverage.sql` adds assertion supersession, typed exact amounts, append-only
  coverage/gap recovery, and cursor advancement tied to primary observation evidence in the same
  commit and acquisition.
- `0003_scenes_commands.sql` adds three replay modes, per-source/projection delivery watermarks,
  separate eligible/surfaced/rendered/viewport/interacted/compared memberships, and commands whose
  only admitted ceiling is `observe_only` / `evidence_only`.
- `0004_operations_exports.sql` adds versioned projection checkpoints, a bounded non-economic
  outbox, immutable export manifests/supersessions, disposal records, a latest-cursor view, and
  ordinary-operation append-only triggers.
- `0005_lossless_contract.sql` preserves the stabilized Rust evidence contract through explicit
  typed sidecars, full-scope cursor state, reference-local media/retention policy, protection-domain
  blob objects and disposal, exact coverage boundaries/recovery evidence, scene/command artifact
  domains, and parent export snapshots whose exact manifest closes over all parts.
- `0006_optional_acquisition_monotonic.sql` makes the acquisition-start monotonic clock an exact
  nullable all-or-none pair. It preserves existing readings while allowing browser acquisitions
  that have only a source wall clock to remain honestly unknown rather than inheriting a core
  commit `Instant`. The runner performs the necessary table rebuild with FK rewriting disabled,
  restores all PRAGMAs, and requires a clean `foreign_key_check` before success.
- `schema/checks/catalog_invariants.sql` executes cross-table invariants that SQLite cannot express
  as a row-local check.
- `fixtures/tape/load.sql`, `expected.sql`, and `manifest.json` define and verify duplicate versus
  equal-valued-distinct events, an unknown variant, a gap and recovery, late correction, witnessed
  versus retrospective replay, runner/flat-watch/re-entry semantics, idempotency, exact decimal
  strings, and an export manifest.
- `schema/validate.sh` selects a safe SQLite runtime, applies and checksums the migration prefix,
  loads the trace, hashes every external artifact, runs positive and negative invariants, and runs
  integrity and foreign-key checks.

The export fixture is intentionally an opaque `.parquet.fixture`, not a real Parquet golden. It
tests the write-first hash/path/catalog boundary only. The analysis/export lane must supply an
actual typed Parquet interoperability fixture.

## Bitemporal and replay contract

`commit_seq` is the only local system-known order. It is not event time. Assertions carry a
separate event-valid interval and append a `supersedes_assertion_id`; the old row is never updated.
The fixture's decoder-v1 trade is effective at cutoff 7, while decoder-v2 is effective
retrospectively through cutoff 11 even though both claim the same earlier event interval.

An as-known assertion query for semantic key `S` and commit `K`:

1. admits only assertions with `produced_commit_seq <= K`;
2. removes an admitted assertion only when an admitted later assertion explicitly supersedes it;
3. reports multiple unsuperseded branches as a conflict instead of selecting by wall time; and
4. applies event-valid filtering only after the system-known cutoff.

A witnessed scene is stricter than that query. Its global knowledge cutoff and every delivered
source/projection watermark must also admit the row. A retrospective scene names its witnessed
basis and a separate outcome cutoff. The stored view blob is the witnessed rendering contract; a
current reducer may not silently replace it.

Times are stored by domain: UTC microseconds for cross-process wall times, canonical decimal text
plus a clock/process identity for local monotonic values, chain slot/order fields where supplied,
and explicit absent/bounded states. Exact asset atoms are canonical signed decimal text, never
SQLite `REAL` or a JavaScript number.

## Crash-commit protocol

The one writer owns the SQLite connection and all acknowledgements.

### Raw ingest and cursor

1. Validate identities, exact integer strings, clocks, source scope, batch bounds, and absence
   semantics before touching durable state. Compute the canonical batch digest.
2. For each external payload, hash the original bytes, write a unique temporary file beneath the
   blob root, sync the file, atomically rename it to the hash-sharded destination on the same
   filesystem, and sync the destination directory. An existing destination is accepted only after
   length and hash verification. Inline bytes skip this step.
3. Enter `BEGIN IMMEDIATE` on the sole WAL/FULL writer. Insert the `ingest_commit` row to allocate
   `commit_seq`, then new acquisition/blob metadata, observations, source-event identities and
   links, assertions/evidence, coverage events/gaps/recoveries, cursor rows and their exact evidence
   links, and permitted outbox work.
4. Before commit, require every cursor's primary observation and all declared evidence to share
   that cursor's commit and acquisition, require actual evidence count to equal `evidence_count`,
   and rerun the batch-local relationship invariants. Any failure rolls back the whole batch.
5. Commit under `synchronous=FULL`. Only after SQLite returns success may the source be acknowledged
   or a durable receipt be returned.

A crash before blob rename leaves only a temp file. A crash after rename but before the database
commit may leave an unreferenced immutable blob, which a grace-period scrub can quarantine and
later reap. A crash anywhere inside the SQLite transaction leaves neither cursor nor observation.
A crash after successful commit but before source acknowledgement may redeliver; acquisition and
observation idempotency accept an exact retry and reject an identity/value conflict. A committed
cursor cannot outrun its evidence.

### Scene and command

Prepare any external view/screenshot/command payload first. In one SQLite transaction insert the
commit, blob metadata, scene, watermarks, choice memberships, command, resulting operator
assertions, and projection work. Return `DurableReceipt` only after commit. An exact retry of
`(client_session_id, idempotency_key)` returns the original receipt; a different payload under that
key is a conflict. The UI must not manufacture success after a disconnected reply.

### Projection and export

A small projection writes rows and its append-only checkpoint in one transaction. A Parquet export
writes, validates, syncs, renames, directory-syncs, and hashes the file first; only then does one
transaction insert `export_manifest` and the checkpoint. Readers open committed manifest paths,
never a directory glob. An interrupted file is an orphan, not an export.

Startup verifies the actual SQLite binding version and PRAGMAs, performs WAL recovery, runs foreign
key and quick integrity checks, verifies recent cursor/blob relationships, requeues expired outbox
leases, and records downtime/source gaps before resuming a scope. Backup uses the SQLite Online
Backup API or `VACUUM INTO`, never a live-file copy.

## Exact `crates/joshi-store` follow-up API

This section preserves the pre-implementation handoff for design history. The implemented API and
stabilized evidence contract described under “Durable store implementation result” below supersede
its sketches and its then-current contract-gap list.

The follow-up should implement these owned boundaries without moving `schema/` or
`fixtures/tape/`:

```rust
pub struct StoreConfig {
    pub catalog_path: PathBuf,
    pub blob_root: PathBuf,
    pub inline_blob_max_bytes: u64,
    pub busy_timeout: Duration,
}

pub enum StoreMode { SingleWriter, ReadOnly }
pub struct SqliteStore { /* one write connection or read-only pool */ }
pub struct BlobStore { /* same-filesystem temp, CAS prepare, hash verify */ }

impl SqliteStore {
    pub fn open(config: StoreConfig, mode: StoreMode) -> Result<Self, StoreError>;
    pub fn apply_migrations(&mut self, schema_dir: &Path) -> Result<MigrationReport, StoreError>;
    pub fn commit_ingest(&mut self, batch: IngestBatch) -> Result<DurableReceipt, StoreError>;
    pub fn commit_scene_command(
        &mut self,
        batch: SceneCommandBatch,
    ) -> Result<DurableReceipt, StoreError>;
    pub fn commit_projection(
        &mut self,
        batch: ProjectionBatch,
    ) -> Result<DurableReceipt, StoreError>;
    pub fn commit_export(
        &mut self,
        prepared: PreparedExport,
    ) -> Result<DurableReceipt, StoreError>;
    pub fn as_known_assertions(
        &self,
        keys: &[SemanticKey],
        cutoff: CommitSeq,
    ) -> Result<Vec<EffectiveAssertion>, StoreError>;
    pub fn load_scene(&self, scene_id: &SceneId) -> Result<StoredScene, StoreError>;
    pub fn verify(&self, depth: VerifyDepth) -> Result<VerificationReport, StoreError>;
    pub fn online_backup(&self, destination: &Path) -> Result<BackupManifest, StoreError>;
}

impl BlobStore {
    pub fn prepare(&self, bytes: &[u8], metadata: BlobMetadata)
        -> Result<PreparedBlob, StoreError>;
    pub fn verify(&self, blob: &PreparedBlob) -> Result<(), StoreError>;
}
```

`IngestBatch` is not a list of independent `append()` calls. It contains one commit header and
vectors of acquisitions, prepared blobs, observations, source events, observation/event links,
assertions and evidence links, coverage windows/events/gaps/recoveries, cursor advances, and
allowed outbox items. `CursorAdvance` requires a non-empty evidence list and names a primary
observation. `SceneCommandBatch` similarly commits the scene and command receipt together.

`DurableReceipt` contains `commit_seq`, stable identity/idempotency key, canonical batch digest,
and `Accepted | Idempotent`; it can only be constructed after successful commit or exact readback.
Identity conflicts, branching assertion conflicts, unsafe runtime/PRAGMA state, missing prepared
bytes, cursor/evidence disagreement, unknown migration history, disk-full, and integrity defects
are typed failures. There is no generic SQL escape hatch in collector or UI APIs.

The current `joshi-evidence` in-memory seam is useful but is not yet this durable API. The store
adapter must make these differences explicit rather than smuggling them into defaults:

- `BlobId` is algorithm-qualified in Rust (`sha256:<hex>`) while SQLite stores the validated raw
  SHA-256 column; mapping is one-to-one and must reject any other algorithm.
- the in-memory observation currently carries at most one source-event ID, while the schema permits
  one raw transaction to contain many events through `observation_source_event`;
- the in-memory acquisition currently carries a cursor value, while durable cursor advancement
  requires an atomic `CursorAdvance` with exact observation evidence;
- current assertion drafts lack semantic key, event-valid interval, supersession, value digest,
  and command evidence needed for correction/replay; and
- current coverage gaps combine detection and recovery in one value, while the durable store
  appends recovery records at their later commit.

Evolve the public evidence contract or add lossless store-specific drafts before wiring collectors.
Do not infer missing fields, collapse multiple source events, or treat an acquisition cursor string
as authority to advance.

## Validation result

`schema/validate.sh` passes with the installed fixed Homebrew SQLite **3.53.2** runtime. It applied
six migrations twice (the second pass checksum-verifies as a no-op), separately proved an
`0001`-`0004` catalog upgrades cleanly through `0005` and the V6 table rebuild, loaded 13 commits, six
observations, seven assertions, twelve exact external artifacts, and executed general plus
case-specific invariants. Negative checks rejected an append-only rewrite, a duplicate command
idempotency key, and a non-integer value in a STRICT integer column. Final `integrity_check` and
`foreign_key_check` passed.

This does not yet prove process-kill durability, filesystem power-loss behavior, production binding
version, concurrent-reader checkpoint behavior, backup/restore, real Parquet export, or load
capacity. Those remain gates for `joshi-store`, not claims implied by a clean SQL load.

## Dependencies and next gate

The Rust follow-up depends on the domain/evidence contract owners agreeing on the lossless batch
shapes above, and on the root workspace selecting a SQLite crate that exposes its actual linked
runtime, backup API, busy/checkpoint behavior, and extended error codes. Source collectors depend
only on the evidence draft contract; they never receive a database handle. Glass depends on
versioned read DTOs and durable command receipts; it never receives SQL or raw mutable rows.

## Durable store implementation result

`crates/joshi-store` now links `rusqlite 0.40.2` with its bundled `libsqlite3-sys 0.38.2`
amalgamation (`SQLite 3.53.2`), backup support, and extra runtime checks. Startup rejects a linked
runtime below 3.51.3, verifies application ID, WAL, `synchronous=FULL`, foreign keys and schema
history, and holds a catalog-adjacent OS file lease for the writer's full lifetime. A second writer
fails immediately. The prior commit digest is read only after `BEGIN IMMEDIATE`, so the append chain
cannot fork between validation and allocation.

The ingest API accepts a bounded `DurableIngestBatch` plus exact per-observation physical policy
and explicit gap severity. It validates canonical ordering, complete policy key sets, exact
microsecond clocks and intervals, reference/source causality, supported strict discriminators,
number-free canonical assertion values and recomputed assertion value digests before installing CAS
bytes. Logical `batchDigest` excludes only its own expected-digest field; a separate
`storeAdmissionDigest` binds that logical digest to normalized retention, content-encoding,
placement and gap policy. Stable IDs and digests remain algorithm-qualified in Rust; only a strict
lowercase `sha256:` adapter strips the prefix for SQL.

The post-commit `joshi.store.ingest_receipt` is an explicit camel-case wire contract. It echoes the
catalog/schema identity, batch ID, logical and store-admission digests, one closed commit range,
decimal-string counts for acquisitions/raw blobs/raw bytes and all seven logical families, the
ordered acquisition closure, and full scoped gap outcomes. It is constructed only after commit or
exact readback. The companion ingress digest has a different preimage and must never be compared to
this batch digest: the core HTTP adapter must validate and echo the source receipt closure and bind
it to the nested store receipt as two separate digests.

Blob identity is only exact-content SHA-256. `blob_object` separates physical copies by protection
domain, while `observation_blob_contract` owns media type, encoding and retention. Thus equal bytes
may be public and private observations without either changing identity or sharing an ambiguous
disposal target. Private/social/disposable payloads are always external; external files are written
to unique temporaries, synced, renamed, directory-synced and hash-verified before SQL can reference
them. SQL transaction rollback may leave only an immutable unreferenced CAS object, which is safe
for later grace-period reclamation.

Implemented repositories cover source/projection registration; acquisition, observation,
source-event, assertion and evidence relations; positive coverage, gaps, later recovery evidence
and atomic cursor advancement; effective assertions as known at a commit; sorted full-scope cursor
and `SourceAsOf` construction; witnessed/cutoff/retrospective scene bytes, watermarks, choice sets
and evidence-only commands; parent export snapshots with exact manifest plus all immutable parts;
full/quick integrity verification; and online catalog backup plus digest-checked restore hooks.
Descriptive acquisition/observation cursor text is never promoted to a watermark.

The scene/command and export methods are structural durable repositories, not yet public canonical
Glass or analysis admission. The core adapter must still parse `GlassViewV1` and reconcile all DTO
identities/cutoffs/watermarks/choice indexes before calling the scene repository. Likewise, the
analysis adapter must parse the exact export manifest bytes and prove they name the supplied part
paths, hashes, row counts and lineage before registration. Opaque bytes are retained exactly, but
the store deliberately does not pretend that hashing opaque bytes proves those higher-level
contracts.

Executable tests prove single-writer exclusion, strict/camel-case receipt closure, wrong digest and
invalid interval rejection before CAS mutation, all four event-time states, unknown variant
retention, one acquisition with multiple occurrence ordinals, full-scope cursor authority, exact
scene byte reload, and an injected failure after all SQL rows but before commit followed by a safe
retry over already-synced CAS bytes. The following gates pass for the crate:

```text
cargo test --manifest-path crates/joshi-store/Cargo.toml --locked
cargo clippy --manifest-path crates/joshi-store/Cargo.toml --all-targets --locked -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --manifest-path crates/joshi-store/Cargo.toml --no-deps --locked
schema/validate.sh
```

Remaining promotion gates are real process-kill/power-loss tests on the target filesystem,
checkpoint/read-load benchmarks, artifact-inclusive backup restoration, a real Parquet golden, CAS
orphan reclamation, and the two strict core adapters described above. The store is ready as the
offline bounded substrate; it is not an authorization to expose a network listener or economic
effect.
