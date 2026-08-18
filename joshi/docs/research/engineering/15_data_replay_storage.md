# Engineering lane 15: data, replay, and storage foundation

Status: concrete pre-implementation recommendation. This document selects a smallest stack and
defines the tests that may force it to grow; it does not implement anything.

## Decision

Start local-first with four deliberately narrow pieces:

1. **One SQLite database** is the transactional catalog and recent operational event store. One
   writer owns ingestion; readers use short-lived snapshots. It stores observation envelopes,
   source-event identities, assertions, coverage/cursors, scene and gesture metadata, projection
   checkpoints, manifests, and small raw payloads.
2. **A content-addressed filesystem blob store** holds screenshots, media, large responses, and
   other large or retention-sensitive bytes. Blob durability precedes the SQLite row that refers to
   it.
3. **Immutable typed Parquet files** are analytical exports and, only after measured scale requires
   it, the cold physical tier for old high-rate rows. SQLite holds the authoritative file manifest.
4. **DuckDB is a disposable analytical/replay-audit engine over those Parquet manifests.** Do not
   make a shared persistent DuckDB database part of the write path.

Use bounded in-memory ingress queues and a SQLite-backed outbox for projections. Do **not** begin
with PostgreSQL, Kafka/Redpanda, NATS, ClickHouse, a lakehouse catalog, or a custom durable event
broker. PostgreSQL is the planned operational-store successor when the workload genuinely becomes
multi-host, multi-writer, or availability-sensitive. The immutable IDs, blobs, and Parquet files
survive that transition.

In shorthand:

```text
collectors --bounded channel--> one committer --> SQLite WAL
                                        |            |
                                        |            +--> durable projection/outbox work
                                        v
                              content-addressed blobs

SQLite commit ranges --manifested export--> Parquet --query--> ephemeral DuckDB
```

This is smaller than “PostgreSQL plus a lake,” but it is not a mutable JSON file masquerading as a
log. It gives evidence and cursors one transaction boundary, keeps replay semantics ours, and
creates a portable analytical boundary before volume requires a service.

## Why this changes two earlier provisional recommendations

`lanes/10_build_buy.md` tentatively preferred PostgreSQL as soon as collectors, reducers, UI, and
annotation workers operate concurrently. Concurrency of components does not by itself require
concurrent database writers. A local writer actor can serialize append commands while readers query
SQLite WAL snapshots; projection and analytics work can run against bounded snapshots or Parquet.
Adding a server now would add administration, backup, authentication, migrations, and a second fault
domain before the actual write rate is known.

`reviews/02_vertical_slice_review.md` says a single SQLite database plus content-addressed files is
plausible for the first read-only slice. This lane agrees, but adds the constraints that make that
statement honest: a fixed SQLite version, one write owner, exact blob/commit protocol, atomic cursor
commits, checked backups, immutable export manifests, and explicit scale gates.

The choice is not “SQLite forever.” It is “do not pay PostgreSQL's operational complexity until a
measured property buys something SQLite cannot.”

## Current official behavior that constrains the choice

### SQLite

SQLite WAL lets readers proceed alongside a writer, but there is still only one writer; all WAL
users must be on the same host, and a long-lived reader can starve checkpoint completion. The WAL,
shared-memory file, and main database are a unit while live and must not be copied independently.
Those are acceptable local-first constraints, not details to discover during an outage.
([SQLite WAL](https://www.sqlite.org/wal.html))

There is also a newly relevant version floor. SQLite documents a rare WAL-reset corruption race in
versions through 3.51.2 when multiple connections write/checkpoint concurrently; it is fixed in
3.51.3 and in specified backports. The `sqlite3` CLI currently found on this machine reports
**3.51.0**, inside the affected range. That does not reveal which SQLite an eventual language
binding embeds. The application must print and enforce its runtime library version and refuse WAL
startup unless it is 3.51.3+ or an explicitly approved fixed backport.
([SQLite WAL-reset bug](https://www.sqlite.org/wal.html#the_wal_reset_bug))

For the evidence catalog, use WAL with `synchronous=FULL`: SQLite says FULL adds a WAL sync after
each commit and is ACID across power loss; NORMAL remains consistent but can lose a recently
committed transaction after power loss. Group commit, rather than weaker durability, is the first
throughput lever. `STRICT` tables, foreign keys, checks, and explicit application validation narrow
SQLite's permissive typing.
([SQLite synchronous modes](https://sqlite.org/pragma.html#pragma_synchronous),
[STRICT tables](https://sqlite.org/stricttables.html))

SQLite's own old-but-useful BLOB study found sub-100 KB blobs often faster inside SQLite and larger
blobs faster as files, while explicitly warning that hardware and filesystem determine the result.
That supports a measured inline threshold rather than millions of tiny loose files; it is not a
universal 100 KB law.
([SQLite internal versus external BLOBs](https://sqlite.org/intern-v-extern-blob.html))

### DuckDB

DuckDB is designed for analytical bulk work, not a stream of tiny durable transactions. Its current
embedded read-write concurrency is inside one process. The current docs describe multi-process
write through the beta Quack protocol and stable multi-writer DuckLake through a PostgreSQL catalog;
neither makes an embedded `.duckdb` file a better operational log for this project.
([DuckDB concurrency](https://duckdb.org/docs/current/connect/concurrency))

DuckDB is excellent over Parquet: it performs projection and filter pushdown and reads files without
loading them into a permanent database. It also documents expected nondeterminism from SQL set
semantics, parallel floating-point aggregation, platform differences, and absent `ORDER BY`. Replay
audits must therefore order explicitly, use exact integer/decimal arithmetic for economic state,
and pin engine/configuration; a query returning the same rows in an arbitrary order is not a
deterministic replay.
([DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview),
[DuckDB nondeterminism](https://duckdb.org/docs/current/operations_manual/non-deterministic_behavior))

### Parquet and Arrow

Parquet is an immutable columnar file with row groups and a footer that locates column chunks. It is
well suited to time-bounded scans and portable exports, not row-by-row append, corrections, cursor
transactions, or point mutation. Page CRCs are optional and implementation support varies, so every
JOSHI file still needs a whole-file cryptographic hash in its manifest.
([Parquet file format](https://parquet.apache.org/docs/file-format/),
[Parquet page checksums](https://parquet.apache.org/docs/file-format/data-pages/checksumming/),
[implementation status](https://parquet.apache.org/docs/file-format/implementationstatus/))

Arrow is a language-independent columnar memory/interchange format with random-access IPC files and
zero-copy-friendly layouts. Those properties make it a good boundary between DuckDB and analytical
code, but mutation is intentionally comparatively expensive and Arrow supplies no evidence catalog,
source cursor, correction semantics, or backup plan. Use Arrow batches opportunistically in memory
or for transient interchange, not as another durable truth format.
([Arrow columnar and IPC format](https://arrow.apache.org/docs/format/Columnar.html))

### PostgreSQL

PostgreSQL earns its place when JOSHI needs independent writer sessions, a server trust boundary,
row-level concurrency, richer temporal constraints, online operational maintenance, replication,
or point-in-time recovery. Native range types plus GiST exclusion constraints are valuable for
non-overlapping known/valid intervals, and PostgreSQL's WAL archiving supports point-in-time restore.
Logical replication can move ordered transactional changes to subscribers.
([PostgreSQL concurrency](https://www.postgresql.org/docs/current/mvcc.html),
[range constraints](https://www.postgresql.org/docs/current/rangetypes.html#RANGETYPES-CONSTRAINT),
[PITR](https://www.postgresql.org/docs/current/continuous-archiving.html),
[logical replication](https://www.postgresql.org/docs/current/logical-replication.html))

None of those capabilities is free: PostgreSQL adds a long-running server, roles and network
surface, vacuum/partition/index operations, base backups and WAL retention, upgrades, and restore
drills. It should replace SQLite for measured operational reasons, not be added beside it “for the
future.”

## Foundation comparison

| Foundation | Strong fit | Structural mismatch | Decision now |
|---|---|---|---|
| SQLite WAL | local atomic append + cursor, constraints, indexes, crash recovery, snapshots, one-file deployment | one writer, same host, checkpoint starvation, large analytical scans, no native range type | **Operational source of truth** with one writer and fixed runtime |
| PostgreSQL | many writers/hosts, server isolation, MVCC, ranges, partitioning, PITR, replication | deployment/backup/admin burden before need; network boundary; still poor for large binary media | **Planned successor**, not initial dependency |
| DuckDB | fast local scans, joins and exports over Parquet; out-of-core analytics | small transactions and shared multi-process operational writes are not its primary design | **Ephemeral analysis/replay audit**, no canonical `.duckdb` file |
| Parquet | compressed typed columns, pruning, broad interoperability, immutable files | no transactional append, corrections, cursors, or small point writes | **Manifested analytical export**; later cold physical tier after a gate |
| Arrow IPC | fast batch interchange, random-access file variant, language boundary | not a catalog, event log, durable correction model, or backup system | **In-memory/interchange option**, not persistence authority |
| Content-addressed files | exact bytes, cheap dedupe, atomic rename, independent retention classes | no query, referential integrity, transaction, or small-file discipline alone | **Large-blob store** behind SQLite metadata |
| SQLite outbox + memory queue | no new daemon; cursor/output checkpoint shares a transaction; simple replay | one host; ingress waiting in memory is not durable | **Initial queue model** with bounded loss window and explicit gaps |
| Custom append segments | very high sequential throughput and recoverable ingress | new framing/index/recovery code and cross-file transaction boundary | **Deferred fallback** only if SQLite ingest gate fails |
| Kafka/Redpanda/NATS JetStream | durable fan-out, consumer offsets, retention, distributed backpressure | broker administration and new delivery semantics with one local consumer graph | **Defer** until independent durable consumers are measured |
| RocksDB/LMDB | embedded high-rate ordered key/value writes | temporal joins, constraints, provenance, migrations, and ad hoc queries move into application code | **Reject initially**; compare only if SQLite fails and PostgreSQL is inappropriate |
| ClickHouse | very large interactive columnar scans and aggregations | not the transactional evidence/cursor boundary; another server | **Defer** until DuckDB/Parquet scan benchmarks fail |

This is a selection, not an invitation to install every row.

## Physical layout

A provisional local layout is:

```text
data/
  catalog/
    joshi.sqlite
    joshi.sqlite-wal
    joshi.sqlite-shm
  blobs/
    sha256/ab/cd/<content-hash>.blob
  parquet/
    family=<typed-family>/ingest_day=YYYY-MM-DD/part-<uuid>.parquet
  manifests/
    backup-<epoch>.json
  tmp/
```

The WAL and SHM paths are shown to make the live database state explicit, not because backups may
copy them ad hoc. All paths live on one local filesystem with reliable file locking and atomic
same-filesystem rename; do not place SQLite WAL on NFS or a synchronizing cloud-drive folder.

### Inline versus external bytes

Use one `blob` abstraction with two physical modes:

- small raw HTTP/WebSocket/program payloads are inline SQLite BLOBs at first;
- screenshots, media, full verbose transactions, and payloads above a provisional **64 KiB** are
  external content-addressed files;
- both modes have the same content hash, original length, MIME/encoding, retention class, and
  observation links;
- the 64 KiB boundary is a benchmark input, not a contract. Test at 16, 64, 128, and 256 KiB on
  Ember's storage before freezing it.

This avoids one filesystem inode per tiny chain event while keeping giant screenshots and media out
of every SQLite backup. Large media may also have derived thumbnail blobs; the thumbnail never
replaces the original evidence.

Hash the exact uncompressed source bytes as `content_sha256`. If storage compression is used, also
record codec/version, uncompressed size, compressed size, and `stored_sha256`. The content identity
then survives a recompression while corruption of the stored representation remains detectable.

### Blob write protocol

For an external blob:

1. redact forbidden request context before it reaches the generic store, while leaving source body
   bytes lossless where policy permits;
2. compute the content hash and write a uniquely named temp file under `data/tmp` on the same
   filesystem;
3. flush and sync the file, atomically rename it to the hash-sharded destination, then sync the
   destination directory;
4. only then commit the SQLite `blob` metadata and observation reference.

A crash before step 4 can leave an unreferenced blob, which a grace-period scrub may remove. A
committed observation must never point to a file that was not already durable. Concurrent writes of
the same hash converge on the same immutable destination after byte/hash verification.

For inline bytes, the blob and observation rows commit atomically in SQLite.

## Identity map

The prior tape blurred acquisition identity, content identity, and alleged event identity. Keep
these boundaries explicit:

| Identity | Meaning | Form and uniqueness | May repeat or revise? |
|---|---|---|---|
| `commit_seq` | local durable ingestion/order watermark | monotonically allocated signed 64-bit integer by the single writer | never reused; not a world-time ordering |
| `observation_id` | one acquisition occurrence/result | 128-bit opaque ID, unique | identical bytes fetched twice get two observations |
| `blob_id` | exact source content | 32-byte SHA-256 of original bytes | shared by identical content; not an event ID |
| `source_event_id` | provider/chain object or event being observed | internal ID for a typed namespace + canonical natural key | one event can have many observations/revisions |
| `assertion_id` | one parser/resolver claim about a source event | deterministic digest of kind, producer version, canonical value and evidence set, or equivalent unique ID with an idempotency constraint | corrections append new assertions and supersession edges |
| `projection_key` | disposable derived row | projection name + version + semantic row key + input-manifest hash | changes when producer or input manifest changes |
| `scene_id` | one captured operator-visible state | opaque ID plus client sequence and catalog watermark | later replay references it; never “refreshed” in place |

Natural source-event keys are typed and lossless:

- Solana event: cluster, signature, transaction index, instruction path, log/event index;
- account state: cluster, account, slot, write version;
- social revision: provider, object namespace, object ID, payload hash;
- board fetch/snapshot: provider, endpoint/query identity, request ID;
- operator gesture: client session and monotonic gesture sequence.

“Same source-event key, different payload” is not resolved by last-write-wins. It becomes a visible
revision or source conflict according to that source's contract. Two equal-valued chain events at
different instruction indices remain distinct.

## Schema boundary

Do not implement one JSON `events` table and ask every consumer to reinterpret it. Use a small
provenance spine plus strict typed family tables.

### Transactional spine

Conceptually, the SQLite catalog contains:

```text
source
  source_id, namespace, endpoint/program, contract version, collector build

ingest_commit
  commit_seq range, committed wall/monotonic time, writer build, transaction digest

blob
  content_sha256, storage mode, inline bytes or relative path, lengths, codec,
  stored_sha256, MIME, retention class, created commit

observation
  observation_id, commit_seq, source_id, source_event_id?, blob hash,
  request/connection/cursor identity, receive/persist/available clocks,
  source/chain clock fields, parse status, quality flags

source_event
  source_event_id, typed namespace, canonical natural-key bytes, first/last observed commit

assertion
  assertion_id, source_event_id, assertion kind, producer/version, produced commit,
  event-valid lower/upper, quality/status, supersedes/retracts

assertion_evidence
  assertion_id, observation_id, evidence role

coverage_window / coverage_gap / source_cursor
scene / scene_watermark / gesture
projection_version / projection_checkpoint / projection_job
parquet_file_manifest / backup_manifest / blob_disposal
schema_migration
```

Then type-specific strict tables carry queryable economics and product state—chain transactions and
events, account states, trades, reserves, quotes, social revisions, board snapshots/members, scene
items, portfolio observations, episode transitions. Each row references its assertion or raw
observation provenance.

JSON can carry genuinely source-specific extras, but not canonical amounts, identifiers, times,
units, state locators, or absence semantics. An unknown raw field remains in the blob until a later
schema earns a typed column.

### Exact amounts

SQLite's signed integer does not cover the full unsigned 64-bit range. Store canonical raw amounts
as validated decimal text (sign plus minimal decimal digits) or a fixed-width big-endian magnitude
with explicit sign; quote/accounting code uses arbitrary-precision integers. Never cast an arbitrary
raw amount through SQLite `REAL`. Parquet analytical schemas use a sufficient exact decimal/integer
width such as `DECIMAL(38,0)`, plus asset/mint and units.

Safe convenience columns—e.g. an `INTEGER` known to be within signed 64-bit range or a display
double—are derived and labeled. They never become the reconciliation authority.

### Clock representation

Retain the domains, not merely formatted timestamps:

- source-event lower/upper wall-time bounds and precision;
- chain slot, transaction/instruction order, commitment/finality, nullable block time;
- receive, persist, parse/available, render, client gesture, and server-receipt wall times;
- local monotonic nanoseconds and process/boot identity for duration measurement;
- enrichment/production time;
- explicit absence reason for any clock the source does not provide.

UTC epoch microseconds fit a signed 64-bit SQLite integer for the relevant horizon. Values crossing a
JavaScript boundary are serialized as decimal strings, not lossy JSON numbers. Local monotonic
values are comparable only within their recorded clock/process domain.

## Bitemporal and multi-clock queries

### System-known time

`commit_seq` is the durable knowledge order. A scene records both its global catalog cutoff and the
per-source/per-projection/client delivery watermarks it actually rendered. A row committed before
the scene but not delivered to that client is not smuggled into replay merely because the server
knew it.

An as-known query at cutoff `K`:

1. selects only observations/assertions with producing `commit_seq <= K` and within the scene's
   source delivery watermarks;
2. applies only supersession/retraction edges whose own commit is at or below `K`;
3. chooses the last applicable assertion version for a semantic key under a declared deterministic
   order;
4. keeps later backfills and enrichments hidden, even if their source event time is earlier.

Do not update an old assertion with `known_to`. Append a supersession edge. A current-state
projection may materialize `[known_from, known_to)` intervals for speed, but that projection is
rebuildable from append-only commits.

### Event-valid time

Event validity is separate:

- a chain event has a chain order and may have a block-time estimate;
- a post may have source publication time;
- a board transition observed between polls has an interval, not an invented exact timestamp;
- an identity assertion may claim the relation held over a range;
- an observed count is valid only as a snapshot at read time.

A retrospective query asks for the final accepted assertion whose valid interval covers event time
`T`. An as-known historical query asks what assertion available by commit `K` claimed about `T`.
Both dimensions must be named in study APIs; a naked `at_time(T)` is ambiguous.

SQLite represents intervals with lower/upper columns, null/unbounded flags, and indexes appropriate
to measured queries. PostgreSQL migration may use range/multirange types and exclusion constraints,
but the logical boundary does not depend on them.

### Ordering

Use source-native total order where one exists. Otherwise preserve a partial order or interval.
Replay delivery is ordered by committed/delivered sequence, not by sorting heterogeneous wall clocks
and pretending their microseconds share an authority.

## Append, correction, and projection semantics

### Ingest transaction

One SQLite transaction commits:

- every observation in the batch and its blob reference;
- any source-event identity discovered;
- the exact source cursor/high-water mark justified by those observations;
- coverage heartbeat/defect/gap records;
- outbox jobs needed by parsers/projections;
- an ingest-commit row/digest.

Only after commit may an ackable source be acknowledged. After a crash, a source may redeliver; the
observation/source idempotency constraints make repetition harmless. The cursor must never outrun
the evidence.

For unacknowledgeable WebSockets, there is inevitably a receive-to-commit vulnerability window. A
small bounded group-commit interval reduces it; restart records the gap from the last committed
source locator. A second durable ingress log would move rather than abolish this boundary and is
not justified until a throughput/recovery benchmark says so.

### Corrections

- Raw observations and source events are never updated or deleted during ordinary operation.
- A parser correction appends a new assertion referencing the same raw bytes and a supersession or
  retraction assertion.
- A source edit/deletion is a new raw observation/revision, not mutation of the first-seen bytes.
- Reorg/finality transitions append canonicality assertions while preserving what the live system
  originally saw.
- Independent source disagreement remains multiple assertions plus a versioned reconciliation
  derivation.
- Retention/hard erasure removes eligible blob bytes through an explicit privileged workflow and
  appends a disposal record; the evidence spine retains only the metadata/hash permitted by policy.

Append-only applies to evidence. Operational job leases, retry counters, and disposable current
projections may update in place because they are not claims about the world.

### Projection transaction

A small projection consumes a closed commit range, writes output, and advances its checkpoint in
one SQLite transaction. A large Parquet projection uses a write-first protocol:

1. capture the closed input commit range and exact projection version/configuration;
2. write a temp Parquet file, close it, validate footer/schema/row count, sync it, atomically rename,
   sync its directory, and compute the whole-file SHA-256;
3. commit its manifest, input range/hash, row count, schema version, min/max clocks, and projection
   checkpoint in one SQLite transaction.

A crash before step 3 leaves an unmanifested orphan, never an apparent completed export. Readers
open only files named by committed manifests, not every glob-matching file in the directory.

## Hot-lane write path and queueing

One committer owns the SQLite write connection and checkpoint policy. Collectors, UI gesture
capture, quote evaluators, and wallet observers submit typed commands through bounded channels.
Give evidence classes explicit budgets rather than an unbounded common queue:

- operator gesture/scene manifest and execution telemetry: highest durability/latency priority;
- hot-lane chain state and policy/quote evaluations;
- census chain events and source health;
- enrichments and disposable projections, which can lag or stop first.

The committer groups compatible appends for at most a small measured interval (initial test: 5 ms or
256 envelopes, whichever comes first) and uses `synchronous=FULL`. A gesture may force an earlier
commit. If a queue reaches its bound, the collector opens a scoped degradation/gap record and
applies the source-specific recovery rule; it never silently drops busiest events.

The durable `projection_job`/outbox table replaces a broker for parser, compaction, thumbnail, and
enrichment work. Workers claim idempotent jobs, write outputs, and atomically mark their checkpoint.
Model calls and notifications are effectful derivations and are disabled during replay.

Introduce an append-segment ingress spool only if all of the following are true:

- the source cannot be backpressured or replayed enough to tolerate the observed queue;
- SQLite group commit misses the benchmark after indexing and transaction scope are corrected;
- the lost receive-to-commit interval matters to an accepted estimand;
- length framing, per-record CRC/hash, segment fsync/rotation, recovery truncation, idempotent import,
  corruption stops, and cursor interaction have an adversarial test plan.

Do not introduce Kafka/NATS merely because the in-process channel is called a queue.

## Parquet analytical boundary

Write separate typed families—e.g. chain event/trade, account state, board membership, social
revision, quote/evaluation, scene/gesture, episode/accounting—rather than a universal nested event
column.

Partition first by **family and ingest UTC day**, not mint, wallet, source event type, or every
strategy label. Ingest day makes late backfill append-only instead of rewriting an old event-date
partition. Event time and mint remain columns with row-group statistics and optional indexes. If a
family/day is too large, add immutable parts; if too small, compact parts into a new manifested
generation and retire the old generation without overwriting it.

DuckDB currently recommends avoiding many tiny partitions and cites at least roughly 100 MB per
partition, with an ideal individual Parquet-file range of about 100 MB to 10 GB. For local JOSHI,
start with a more conservative target of **128 MB to 1 GB compressed per file**, then benchmark
query pruning and backup behavior.
([DuckDB partitioned writes](https://duckdb.org/docs/stable/data/partitioning/partitioned_writes),
[file-format performance](https://duckdb.org/docs/current/guides/performance/file_formats))

Every file manifest includes:

- logical family and schema version/field-ID map;
- producer binary/query/config hash and engine versions;
- input commit range plus input-manifest digest;
- row count and min/max commit, event, chain, and source times where meaningful;
- compression, Parquet format and writer options;
- whole-file SHA-256, byte length, and optional page-checksum configuration;
- creation time, superseded generation, retention class, and backup state.

Schema evolution is explicit. DuckDB's `union_by_name` is useful for exploratory reading, but
production replay must not use it to silently equate renamed fields, changed units, or changed null
semantics. A family schema registry maps field IDs and adapters deliberately.

Analyses query committed manifests. They may use Arrow record batches as the in-memory interchange
with Python/Rust processes. Reusable analytical outputs return to the evidence system as derivations
with query/code hash, input manifests, engine/configuration, result hash, and production time.

## Deterministic replay

A deterministic replay manifest contains:

- evidence commit cutoff and per-source/client/projection watermarks;
- exact observation/blob and Parquet manifest digests;
- reducer/parser/identity/model/prompt/UI versions and configuration;
- timezone, locale, numeric policy, engine versions, and ordering rules;
- scene and gesture IDs;
- declared side-effect sink: always disabled for historical replay.

Replay proceeds from immutable evidence, not a copied “latest state” table:

1. verify every referenced content/file hash and schema manifest;
2. select observations by commit/delivery cutoff for as-known replay, or final accepted assertions
   for retrospective replay;
3. apply reducers in explicit `(commit_seq, intra_commit_seq)` delivery order while retaining
   source-native chain order separately;
4. materialize typed projection state and a canonical digest;
5. restore the scene and compare structured view hash and salient screenshot;
6. run twice from empty state and require the same digest.

SQL used in a canonical digest has explicit ordering. Exact state and PnL use integers/decimals.
DuckDB canonical audit mode pins version, timezone and locale, uses one thread when a floating
aggregate could depend on reduction order, and records any accepted tolerance rather than rounding
until outputs happen to match. Nondeterministic model output is not regenerated to prove equality;
the originally stored output is replayed, while a new model run is a new derivation.

Projection checkpoints are performance artifacts. If their producer or input manifest differs,
discard and rebuild them. A successful database query is not proof that the scene is reproducible.

## Schema migrations

Maintain a strict `schema_migration` ledger with monotonic migration ID, source checksum, required
runtime versions, applied commit/time, and result schema digest. Do not rely only on SQLite
`user_version`.

Rules:

- raw envelope, typed family, projection, and Parquet schemas version independently;
- never change a field's meaning, unit, clock, orientation, or unknown semantics in place;
- prefer additive nullable columns plus strict new writers/read adapters;
- semantic changes create a new assertion/typed family or projection version;
- a large rebuild writes a new table/projection generation, compares counts/digests/replay, then
  changes a view/pointer; it does not rewrite the only copy;
- take a verified SQLite snapshot and catalog/blob manifest before a migration;
- keep old readers for the fixed adversarial corpus until an explicit compatibility boundary;
- every upgrade of SQLite, DuckDB, Arrow, Parquet writer, decoder, or compression library reruns
  fixture and crash/replay gates.

Parquet files are immutable. A schema correction writes a new generation and a supersession
manifest; it never edits an old footer.

## Crash recovery

### Startup sequence

1. Verify the runtime SQLite version and required PRAGMA results rather than assuming a setting was
   accepted. Refuse unsafe/mismatched configuration.
2. Let SQLite recover its WAL, then run a quick consistency check; run full `integrity_check` and
   `foreign_key_check` on a schedule and after suspicious shutdown/storage errors. SQLite documents
   that `integrity_check` covers low-level format, missing pages, indexes and several constraints,
   while foreign keys require their separate check.
   ([SQLite integrity checks](https://sqlite.org/pragma.html#pragma_integrity_check))
3. Verify the last ingest transactions, cursor invariants, and referenced blob existence/hash.
4. Quarantine temp/unmanifested Parquet output and retain young unreferenced blobs until the grace
   period proves they are crash orphans.
5. Requeue claimed-but-incomplete outbox work idempotently.
6. Reopen source coverage from the last committed cursor/high-water mark and append the downtime
   gap before accepting new events.
7. Rebuild disposable hot/current projections if their checkpoint/input digest is not valid.

Never skip a torn/corrupt record and continue a monetary or causal projection. Stop the affected
scope, preserve the bytes, and mark the gap/defect.

### Checkpoint discipline

The single writer owns checkpoint requests. UI and analytical queries must not hold unbounded read
transactions; DuckDB scans Parquet instead of pinning the live WAL for minutes. Monitor WAL size,
checkpoint duration/busy results, oldest reader age, and commit latency. Upgrade past the WAL-reset
bug even with one intended writer because a maintenance/backup connection can otherwise create the
prohibited concurrency accidentally.

### No ad hoc copying

Do not `cp` a live SQLite main file. SQLite states that the WAL is part of persistent state and that
separating it can lose committed transactions or corrupt the copy. Use the Online Backup API or
`VACUUM INTO` for a consistent snapshot; the Online Backup API can copy incrementally while the
database remains in use.
([SQLite Online Backup API](https://sqlite.org/backup.html),
[`VACUUM INTO`](https://sqlite.org/lang_vacuum.html#vacuuminto))

## Checksums and scrubbing

Checksums answer “are these the bytes we committed?”, not “was the source truthful?”

- each raw payload: SHA-256 over original bytes;
- each external stored blob: content and stored-representation SHA-256;
- each Parquet file: whole-file SHA-256 regardless of optional page CRCs;
- each manifest: canonical encoding hash, with previous daily manifest hash if a simple append chain
  proves useful;
- each producer/migration/schema: source/build checksum;
- each SQLite backup: snapshot file SHA-256 plus SQLite integrity and foreign-key checks;
- each replay: ordered input-manifest and canonical output digests.

Run a rolling blob/Parquet scrub plus periodic full scrub. A hash mismatch quarantines the artifact
and every dependent projection; it is not repaired from a derived table. A backup is not verified
until restored elsewhere and replayed through a known scene digest.

## Backup, restore, and retention

### Backup unit and ordering

A backup epoch is:

- an Online Backup API SQLite snapshot with maximum included `commit_seq`;
- every external blob and active Parquet file referenced by that snapshot;
- schema/build/configuration manifests required to decode and replay it;
- an outer manifest with hashes, counts, byte totals, retention/encryption class, and backup time.

Because external artifacts are written durably before their catalog reference, an incremental backup
can copy immutable blobs/Parquet first and take the SQLite snapshot last. Extra unreferenced files in
the backup are harmless; a missing referenced file fails verification. Use encrypted backups with
private-by-default permissions and at least one failure-independent destination.

Initial proposed objectives, to confirm with Ember:

- committed local evidence: zero RPO for application crash; at most the explicit group-commit window
  for received-but-not-yet-committed frames; FULL mode targets zero committed loss on power failure;
- device loss: no more than one hour of irreplaceable catalog/operator evidence and completed
  immutable artifacts once the first real sessions begin;
- restore: a clean-machine restore and one canonical session replay within four hours at pilot
  scale.

Daily backups without restore tests do not satisfy these objectives. Run an automated small restore
frequently and a full isolated restore at least monthly while the corpus is valuable.

### Retention classes

At minimum separate:

1. compact public chain facts and coverage;
2. verbose public source responses;
3. social text and third-party media;
4. app-only screenshots and viewport telemetry;
5. operator annotations/interviews and portfolio context;
6. disposable projections/caches;
7. later execution/signing telemetry under a separately reviewed policy.

Evidence immutability does not override privacy or deletion. A privileged disposal workflow appends
the authorization and affected content hashes, deletes eligible bytes and derived copies, expires
them from backups under the declared schedule, and leaves only the minimal permitted tombstone.
Retention-sensitive content should be physically separable—and possibly encrypted by class—so a
hard-erasure policy is operable rather than aspirational.

Do not cold-tier or delete source rows in the first vertical slice. After the volume pilot, a
measured archival migration may move closed commit ranges from SQLite inline storage into immutable
raw packfiles/Parquet while retaining their IDs and catalog manifests. That is a physical relocation,
not a semantic rewrite, and must pass replay equality before source deletion.

## Rough workload and capacity envelope

The old PumpPortal probe measured about 28 launches/minute, but no existing result establishes the
full Pump/PumpSwap transaction rate, verbose bytes, concurrent hot-lane amplification, or screenshot
volume that this design needs. Therefore the first 72-hour source shootout must report actual mean,
p95/p99 burst rate, payload-size distribution, and compression by family.

Use this capacity identity for every class:

```text
daily bytes = 86,400 * mean records/second * mean stored bytes/record
```

Illustrative—not predicted—loads:

| Scenario | Sustained records | Mean stored bytes | Daily volume before indexes/backups |
|---|---:|---:|---:|
| narrow pilot | 50/s | 750 B | 3.24 GB |
| broad census | 100/s | 1 KB | 8.64 GB |
| census + several hot lanes | 250/s | 1 KB | 21.6 GB |
| 300 salient screenshots/day | — | 1 MB | 0.30 GB |

SQLite index amplification, WAL, duplicate observations, filesystem allocation, Parquet
compression, and backup copies sit outside those raw figures. A fixed 10 Hz quote snapshot across
many hot mints can dominate the tape without adding information; persist every state change and
policy evaluation capable of triggering an action, not arbitrary timer noise.

Provision the first benchmark around **500 sustained envelopes/s**, a **2,500/s one-minute burst**,
1 KB median payload, 5% 64 KB payloads, eight simulated hot lanes, concurrent UI reads, and the
actual target disk. These are engineering headroom targets to be replaced by at least 2x the
measured p99 burst and 10x the measured mean from the source pilot.

## Benchmark and acceptance gates

### Gate A — version and configuration

- Runtime SQLite is 3.51.3+ or an explicitly approved fixed backport.
- WAL, FULL synchronous, foreign keys, strict schema behavior, busy handling, and application ID are
  queried back and asserted at startup.
- Database and WAL are on a supported local filesystem; free-space reserve and inode availability
  are monitored.

Failure blocks using SQLite WAL; it does not silently downgrade durability.

### Gate B — ingest under load

On the provisional workload above for 30 minutes:

- zero unexplained losses, cursor skips, conflicting duplicate acceptance, or dangling references;
- p95 observation receive-to-queryable below 25 ms and p99 below 75 ms in steady state;
- during the burst, p99 below 250 ms and the queue drains within 30 seconds;
- operator gestures/scene manifests remain p99 below 50 ms locally;
- checkpoints complete, WAL does not grow without bound, and UI reads remain available;
- disk-full and queue-full behavior produces a scoped gap and stops unsafe dependent work.

If absolute rates prove irrelevant, preserve the 10x mean/2x p99 headroom rule and document the new
numbers rather than gaming this gate.

### Gate C — point-in-time queries and replay

Against at least 30 days or a scale-equivalent synthetic corpus:

- latest hot-lane/scene queries are p95 below 75 ms under concurrent ingest;
- an as-known scene reconstruction is p95 below 250 ms excluding large screenshot decode;
- source-event revisions at the same event time but different commit times return correctly under
  both as-known and retrospective queries;
- a late backfill never appears before its commit/delivery watermark;
- two runs from empty state produce the same canonical digest and recognizable scene;
- DuckDB queries read only manifested files, use explicit ordering for digest output, and report
  engine/input versions.

### Gate D — crash matrix

Repeatedly terminate the process:

- before and after external blob rename/fsync;
- between blob durability and SQLite reference commit;
- between observation insert and cursor commit attempt;
- immediately before/after SQLite commit;
- during projection output and before/after checkpoint;
- during Parquet temp write, rename, and manifest commit;
- during backup and schema migration.

After every restart: no cursor outruns evidence, no committed reference is missing, duplicates are
idempotent, orphans are quarantined/reaped only after grace, gaps are visible, and replay digest is
stable. Corruption injection must stop the affected projection rather than skip a row.

### Gate E — backup and restore

- Snapshot uses a supported SQLite API, never an ad hoc live-file copy.
- Every manifest hash and reference validates on a clean destination.
- Restored catalog passes integrity and foreign-key checks.
- One selected session replays to its canonical digest without contacting live sources.
- Hard-erasure/retention fixtures prove disposed content is absent from eligible active backups.

### Gate F — analytical export

- Parquet row counts, exact integer/decimal values, null/unknown states, commit ranges, and min/max
  clocks reconcile with SQLite source queries.
- Interrupted export never makes a partial file visible through a committed manifest.
- Compaction preserves the logical file-generation digest and removes no source before a verified
  backup and replay-equivalence result.
- Representative chronological and mint/episode-filtered DuckDB studies meet the interactive/batch
  latency target established by the research lane; if not, profile file size, sort order, row groups
  and partition pruning before proposing another database.

## Transition to PostgreSQL or larger deployments

Move the operational catalog to PostgreSQL when one or more of these are true and cannot be solved
by keeping one local writer:

- two machines or independently deployed authorities must write concurrently;
- availability requirements no longer tolerate one local host, or point-in-time recovery/replica
  failover becomes necessary;
- SQLite misses Gate B at 2x measured peak after transaction/index/checkpoint tuning;
- long-running operational reads repeatedly starve checkpoints despite moving analytics to Parquet;
- catalog backup/restore or migration time exceeds the accepted recovery objective;
- catalog size/index maintenance makes Gate C fail (use 250 GB or 100 million active indexed rows as
  a forced review point, not an automatic migration);
- access-control boundaries require server-enforced roles rather than one trusted local process.

Do not migrate merely because the code has several processes. Route their writes through the same
committer until that becomes the measured bottleneck.

### Portable boundary

Keep store-neutral domain records and stable external IDs. SQLite-specific details stop at the
repository layer:

- `commit_seq` becomes a PostgreSQL sequence but retains existing values;
- typed IDs, exact decimal representations, source natural keys, assertion/supersession edges, and
  blob hashes remain unchanged;
- interval columns may become PostgreSQL range types and GiST indexes without changing event/known
  semantics;
- external blobs and Parquet manifests stay where they are or move to compatible object storage;
- DuckDB/Parquet analysis continues unchanged;
- no projection row is considered migration authority.

### Cutover method

1. Take a verified SQLite snapshot and closed commit watermark.
2. Export strict typed tables with counts and per-table canonical digests; load PostgreSQL with
   preserved IDs and sequences.
3. Validate constraints, blob/file references, bitemporal query fixtures, and full replay digest.
4. Pause the local writer briefly, ingest/replay the final delta, record the exact cutover watermark,
   then switch one write authority. Avoid indefinite application-level dual-write.
5. Keep the SQLite snapshot read-only until backup/restore and production replay have passed.

If near-zero downtime later matters, a temporary portable raw spool or purpose-built CDC bridge can
carry the cutover delta. Do not design that machinery before the transition exists.

After PostgreSQL, introduce a broker only when there are multiple independent durable consumers
whose lag, retention, and backpressure cannot be represented by the PostgreSQL outbox. Introduce
ClickHouse only when manifested Parquet plus DuckDB fails a measured interactive analytical
workload. A larger deployment should replace one proven boundary at a time.

## Smallest honest implementation slice

Implement only enough storage to run the offline crash-and-replay fixture and one prospective
read-only session:

1. One pinned SQLite runtime/database with the provenance spine, strict typed fixture families,
   source cursor/coverage, scene/gesture rows, and projection outbox.
2. Inline small payloads plus one external content-addressed screenshot/raw-blob path using the
   write-first protocol.
3. One pure reducer with an atomic checkpoint and deterministic state digest.
4. One Parquet export family over a closed commit range and an ephemeral DuckDB replay audit.
5. One online backup/clean restore with manifest and blob hash verification.
6. The adversarial fixture from lane 09: duplicate delivery, equal-valued distinct events,
   conflicting revision, unknown payload, clock skew, late backfill, gap, inspect/arm/exit/flat
   watch/re-entry/partial realization/runner gestures, and crashes at every durability boundary.

Do not implement generalized cold-tier deletion, PostgreSQL mirroring, a custom spool, media
encryption, Kafka, or a universal event family in this slice. Their schema boundaries are reserved;
their machinery is not yet earned.

The slice passes when a clean restore and from-empty replay reproduce the same as-known scene and
episode digest, while the gap, conflict, late knowledge, two inventory intervals, and flat-watching
interval remain visible. That result is useful independent of whether any trading strategy is good.

## Open decisions left to measurement or policy

1. Actual sustained/burst records, verbose transaction size, and hot-lane amplification from the
   72-hour source test.
2. The inline/external BLOB threshold and compression choices on Ember's target storage.
3. Whether app-scoped screenshots and operator notes need per-class encryption or another practical
   hard-erasure mechanism before broad capture.
4. Backup destination, encryption/key custody, one-hour device-loss RPO, and four-hour restore target.
5. Exact UI delivery watermark protocol; server `commit_seq` alone cannot prove what the browser
   rendered.
6. Which typed families are needed by the first vertical slice; raw unknowns remain blobs rather
   than forcing a universal schema.
7. Whether compact market-wide chain events can remain in SQLite for the research horizon or need
   early cold physical relocation after the capacity pilot.
8. Whether macOS full-filesystem sync behavior and target disk warrant an additional durability
   setting beyond SQLite FULL, based on a measured fault/durability review.

The governing principle is simple: SQLite supplies the first atomic truth boundary; content hashes
preserve exact bytes; Parquet and DuckDB make analysis cheap and portable. Everything else must
arrive because a benchmark, failure mode, or authority boundary demanded it.
