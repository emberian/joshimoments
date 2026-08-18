# Lane 06 — Rust crate estate and dependency boundaries

Status: implementation research and decision record  
Researched: 2026-08-16  
Target machine: Apple arm64, macOS 26.6.1, 96 GiB RAM  
Operational register: [`../RUST_CRATES.md`](../RUST_CRATES.md)

## 1. Question and answer

Which Rust dependencies let Joshi build the V1 evidence machine quickly without
letting a framework, provider SDK, or serialization convenience redefine what
the evidence means?

The answer is a deliberately ordinary commodity foundation—Tokio, Reqwest,
Tungstenite, Rusqlite, SHA-256, Arrow/Parquet, Axum, Serde, exact-number
crates—surrounded by project-owned semantic seams. The most dangerous libraries
for this project are not low-quality libraries. They are broad, competent
abstractions whose hidden decisions look like convenience: automatic retry,
connection pooling, SDK transaction clients, lossy fan-out, decimal arithmetic,
configuration overlays, schema-generating authority, and auto-approved snapshots.

The dependency policy is therefore:

1. buy commodity mechanisms;
2. own evidence and financial meaning;
3. pin volatile protocol/oracle surfaces much harder than ordinary utilities;
4. quarantine broad provider/protocol graphs behind private adapters;
5. add crates only when their first consumer and falsification test exist.

This lane is scoped to V1 read/record/replay/render/analyze. It recommends no
transaction construction, signing, submission, or secret-bearing account
automation.

## 2. Sources, method, and fact/judgment boundary

The survey used current official documentation, crates.io metadata, upstream
source manifests/lockfiles, and the actual local workspace graph. Version and
feature claims are dated because this ecosystem moves quickly.

Each section distinguishes:

- **Observed fact** — a property of the current workspace or linked primary
  source;
- **Judgment** — Joshi's architectural choice given the program invariants;
- **Gate** — a small test that can disprove the judgment before commitment.

The machine had Rust 1.97.1 active in the project and also had
`cargo-audit` 0.22.2, `cargo-vet` 0.10.1, `cargo-nextest` 0.9.136,
`cargo-fuzz` 0.12.0, and `cargo-insta` 1.28.0 installed. Installation is not
approval and PATH state is not a reproducible toolchain.

Primary orientation sources include the [Rust release
notes](https://doc.rust-lang.org/stable/releases.html), [Cargo resolver
reference](https://doc.rust-lang.org/cargo/reference/resolver.html), [Cargo tree
reference](https://doc.rust-lang.org/cargo/commands/cargo-tree.html), upstream
crate documentation linked in each section, and immutable protocol provenance
listed in §9.

## 3. Decision forces

The crate estate follows these stronger system decisions:

- immutable observations and explicit coverage/correction evidence;
- deterministic offline replay with no network or secret dependency;
- exact financial and protocol arithmetic;
- SQLite as operational truth with one writer and a project-owned commit
  protocol;
- exact-byte content-addressed blobs and manifested Parquet research exports;
- bounded by records **and bytes**, with observable overload and gap behavior;
- a local, same-origin HTTP UI using SSE until bidirectionality is proved;
- canonical project DTOs, never SDK types, crossing domain boundaries;
- Python/DuckDB as downstream research consumers rather than embedded engines;
- no execution path in V1.

Consequently “has a convenient async API” and “supports many Solana methods”
are not automatically benefits. They can be liabilities if they obscure
attempts, pull signing capability into a read-only process, or duplicate runtime
and cryptography generations.

## 4. Workspace, compiler, and update policy

### Observed facts

The repository currently uses:

- `rust-toolchain.toml` pinned to **1.97.1**, minimal profile, with Clippy and
  rustfmt;
- edition 2024, resolver 3, and `rust-version = "1.97"`;
- members `apps/core` and `crates/*`, with only core/domain/evidence in
  `default-members`;
- workspace lints forbidding unsafe code and warning on Clippy all/pedantic;
- release overflow checks and thin LTO;
- a committed resolver graph in `Cargo.lock`.

[Rust 1.97.1's release note](https://doc.rust-lang.org/stable/releases.html)
identifies a compiler fix for an LLVM miscompilation in 1.97.0. Resolver 3 uses
the package `rust-version` as a dependency-selection fallback, as described in
the [2024 resolver documentation](https://doc.rust-lang.org/edition-guide/rust-2024/cargo-resolver.html).

### Judgment

Adopt this baseline exactly. `1.97.0` is not a sensible reproducibility pin when
the patch release fixes possible wrong-code generation. Every package should
inherit workspace version, edition, MSRV, license, publish flag, and lints.

Run CI/release gates with `cargo ... --workspace --all-targets`: invoking Cargo
with no package selection misses `joshi-sources` and `joshi-accounting` under the
current `default-members` list.

Use two pinning regimes:

| Dependency kind | Manifest policy | Lock/update policy |
|---|---|---|
| Ordinary utility | Compatible version requirement | Commit lockfile; update intentionally in small groups. |
| Format family such as Arrow | Exact same family version | Upgrade all family members together with cross-reader goldens. |
| Protocol package/oracle | Exact `=` version plus registry checksum, or immutable Git revision | Record upstream artifact/IDL provenance and rerun differential fixtures. |
| Cargo tool | Pin in CI bootstrap/tool manifest | Do not infer CI behavior from Ember's installed PATH. |

Every dependency update inspects both `cargo tree -d` and `cargo tree -e
features`, checks source/license/advisories/MSRV, and runs the affected
conformance tests. A `Cargo.lock` is necessary but does not explain why a new
duplicate runtime, TLS, cryptography, serialization, or Solana generation is
present.

### Gate

A fresh checkout on Apple arm64 and CI must install the exact toolchain, build
offline after dependency fetch, run `cargo test --workspace --all-targets`, and
produce the same canonical fixture digests. The gate deliberately includes
packages outside `default-members`.

## 5. Error, schema, identity, time, and numeric foundations

### Decision matrix

| Concern | Decision | Candidate | Reason and boundary |
|---|---|---|---|
| Library errors | Adopt | `thiserror` 2.0.20 | Typed variants preserve program decisions and are cheap to inspect/test. |
| Binary/task context | Defer | `anyhow` 1.0.104 | Useful at a final operator boundary, but opaque context chains must not become library contracts. |
| Rich terminal reports | Defer | `miette` 7.6 | Add when source-span diagnostics become an actual operator need. |
| Serde | Adopt | `serde` 1.0.229 | Stable derive ecosystem; canonical project DTOs own schema. |
| JSON | Adopt | `serde_json` 1.0.151 | Parse ordinary provider/control JSON. Avoid features that silently widen semantics. |
| RFC 8785 canonical JSON | Probe/dev | `serde_json_canonicalizer` 0.3.2 | Existing accounting-test oracle; cross-language exact vectors precede any durable use. |
| Error path | Adopt at ingress | `serde_path_to_error` 0.1.20 | Tells an operator which nested provider/config field failed without changing DTOs. |
| JSON Schema | Probe/dev | `schemars` 1.2.2 | Useful for drift reporting and UI/tooling, not authoritative protocol schema. |
| Serde helpers | Defer | `serde_with` 3.22 | Add only for a repeated, reviewed representation; custom financial/wire forms remain project code. |
| Stable IDs | Adopt | project-owned string newtypes | Namespaces, validation, and evolution are evidence semantics. |
| Solana base58 text | Adopt in adapter | `bs58` 0.5.1 | Use the codec, then apply project-owned byte-length/key-type validation. |
| Generated IDs | Defer | `uuid` 1.24 | UUIDv7 could identify local occurrences; it cannot define event time, truth, or replay order. |
| Wall-clock values | Adopt | `time` 0.3.55 | Explicit parse/format features and existing workspace use. |
| Durations/deadlines | Adopt | `std::time::Instant` | Monotonic elapsed time; never serialize it as evidence. |
| Arbitrary integers/rationals | Adopt | `num-bigint` 0.4.6, `num-rational` 0.4.2, `num-traits` 0.2.19 | Exact ledger values and ratios. Keep the already aligned bigint 0.4 family. |
| U256 | Probe | `ruint` 1.20 | Good fixed-width primitive if a named protocol vector requires it. Keep it inside protocol/math modules. |
| Decimal | Reject for truth | `rust_decimal` 1.42 | Bounded decimal scale/range cannot represent all protocol integers or exact arbitrary ratios. |

### Observed facts

Serde JSON's optional features include `arbitrary_precision`, `preserve_order`,
and `unbounded_depth`; they alter numeric/object/depth behavior. They should not
be ambient workspace features. See the [serde_json feature
list](https://docs.rs/crate/serde_json/latest/features).

`num-rational` 0.4.2 depends on `num-bigint` 0.4, visible in its [published
manifest](https://docs.rs/crate/num-rational/0.4.2/source/Cargo.toml). Moving only
`num-bigint` to the newer 0.5 line would create duplicate, non-interoperable
BigInt types. `rust_decimal` documents its bounded 96-bit representation and
scale in the [crate documentation](https://docs.rs/rust_decimal/latest/rust_decimal/).
`ruint` provides const-generic fixed-width unsigned integers in its [upstream
repository](https://github.com/recmo/uint).

[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) is relevant to canonical
JSON but also explains interoperability limits around large JSON numbers. Joshi
already makes u64/u128 wire integers decimal strings. Canonicalization cannot
repair a schema that first rounded a number through IEEE-754.

### Judgment

Keep closed schemas strict and treat unknown variants explicitly where protocol
evolution is open. Do not conflate `deny_unknown_fields` with universal safety:
it belongs on a genuinely closed configuration or DTO version, not an upstream
object expected to add fields.

Use exact integer strings at wire boundaries and project-owned conversion
functions with range errors. RFC 8785 canonicalization happens only after that
semantic encoding choice; a canonicalizer cannot restore a large integer that
was first represented as an imprecise JSON number. Use rationals for accounting truth and explicit
rounding only at a named protocol/display boundary. Floats are admissible for
plots and statistical computation after exact facts are retained; they are not
ledger or quote truth.

Generated JSON Schema is an output for drift/UI tooling. The Rust type plus
versioned schema contract and goldens remain authority. Likewise, a UUID library
must not smuggle “roughly time ordered” into replay semantics; acquisition and
source clocks already own that problem.

### Gate

Property tests must cover min/max integers, leading signs/zeros, overflow,
division/rounding boundaries, serde round trips, unknown variants, and
cross-language canonical JSON. A fixture should demonstrate that values above
2^53 survive Rust → JSON → TypeScript/Python without becoming JSON numbers.

## 6. Concurrency, cancellation, HTTP, WebSocket, retry, and rate limiting

### Observed facts

Tokio's [bounded `mpsc::channel`](https://docs.rs/tokio/latest/tokio/sync/mpsc/fn.channel.html)
provides backpressure when capacity is reached. Capacity is a message count,
not a byte budget. Tokio Util's [`CancellationToken`](https://docs.rs/tokio-util/latest/tokio_util/sync/struct.CancellationToken.html)
offers cooperative cancellation; a token does not itself specify drain, flush,
commit, or child-task completion ordering.

Reqwest 0.13 has an explicit [retry policy
module](https://docs.rs/reqwest/latest/reqwest/retry/index.html). Its default
client policy performs a small set of safe protocol-level retries with an extra
request budget. Reqwest's [TLS documentation](https://docs.rs/reqwest/latest/reqwest/tls/)
also makes provider selection a feature decision. `tokio-tungstenite` supplies
the Tokio WebSocket integration in its [upstream
repository](https://github.com/snapview/tokio-tungstenite).

The current source graph deliberately uses Reqwest with defaults disabled plus
`json,rustls`, and Tokio Tungstenite with defaults disabled plus
`connect,rustls-tls-webpki-roots`. It does not contain a native-TLS/rustls
duplicate.

[`governor`](https://docs.rs/governor/latest/governor/) implements GCRA rate
limiting. It can supply the clock/quota primitive, but it does not know provider
credits, endpoint weights, evidence policy, or replay meaning.

### Judgment

Adopt:

- `tokio` 1.53.1 with only named runtime/sync/time/net features needed by each
  package; never enable `full` for convenience;
- `tokio-util` 0.7.19 for `CancellationToken`;
- `bytes` 1.12.1 and `futures-util` 0.3.34 inside transport adapters;
- `reqwest` 0.13.4 and `tokio-tungstenite` 0.30 under the current minimal rustls
  feature choices;
- `url` 2.5.8 for parsing, behind a redacted display/debug wrapper.

Explicitly set `reqwest::retry::never()` for evidentiary source requests.
Project-owned supervision decides whether another attempt is legal and records
attempt number, trigger, delay, response/transport result, `Retry-After`, budget
exhaustion, and resultant coverage. A retry middleware—even a good one—cannot
silently turn two network attempts into one apparent acquisition.

Retain the current project-owned deterministic backoff policy because injected
entropy and recorded schedules serve replay/test semantics. Do not add `backon`
or Tower retry middleware. Probe `governor` only as a local primitive beneath a
provider quota wrapper.

Every queue carrying evidence has both:

1. a bounded Tokio record channel; and
2. a byte/credit budget, normally a `Semaphore` permit owned until processing
   completes.

Reject `tokio::sync::mpsc::unbounded_channel` for evidence and reject
`tokio::sync::broadcast` as durable fan-out: broadcast receivers can lag and
lose messages. It is acceptable only for explicitly expendable UI hints after
durable truth already exists.

`CancellationToken` is the wake-up mechanism, not the shutdown design. The
project protocol must stop admission, stop/reconcile sources, drain bounded
queues, commit/flush, checkpoint diagnostics, then join children with a bounded
deadline and explicit incomplete-shutdown evidence.

### Gate

Use a deterministic fake HTTP/WS provider to exercise:

- DNS/connect/TLS/HTTP/JSON failures and status-class policy;
- `Retry-After` date/seconds, attempt exhaustion, and deterministic jitter;
- WS ping/pong, clean and abrupt close, duplicate frames, reordering,
  subscription generations, re-subscription failure, overlap, and backfill;
- an oversized single record and many small records against both budgets;
- cancellation at every transition, including a full writer channel.

The same accepted observations and coverage facts must replay to the same
projection digest. Network timings themselves need not reproduce; their
recorded decisions do.

## 7. SQLite, migrations, locking, CAS, and temporary files

### Observed facts

SQLite 3.51.3 fixed a WAL-reset corruption bug documented in the [SQLite release
news](https://www.sqlite.org/draft/news.html). The [WAL
documentation](https://www.sqlite.org/wal.html) describes concurrency and
checkpoint behavior; the [online backup API](https://www.sqlite.org/backup.html)
exists specifically for consistent live backups.

Rusqlite 0.40.2's `libsqlite3-sys` 0.38.2 bundled source is SQLite 3.53.2, above
the required floor. Rusqlite's current default feature set is not the minimal
one Joshi needs, so the manifest should use `default-features = false` and
select the bundled/backup/checking features explicitly. Primary source:
[rusqlite repository and feature manifest](https://github.com/rusqlite/rusqlite).

`rusqlite_migration` stores migration level using SQLite `user_version`; its
[documentation](https://docs.rs/rusqlite_migration/latest/rusqlite_migration/)
does not supply Joshi's required content-addressed migration ledger.

Rust's standard [`File::try_lock`](https://doc.rust-lang.org/std/fs/struct.File.html)
is stable on this toolchain, so no extra file-lock crate is required for the
single-instance guard.

### Judgment

Adopt Rusqlite when the persistence crate exists:

- one connection-owning writer task;
- WAL mode, `synchronous=FULL`, explicit busy/checkpoint policy;
- no SQLx, Diesel, SeaORM, `deadpool-sqlite`, `r2d2`, or
  `tokio-rusqlite` in V1;
- blocking SQLite work isolated consciously from async source tasks, rather
  than hidden behind a pool;
- online Backup API or `VACUUM INTO` for live snapshots; never byte-copy a live
  database.

The one-writer invariant is a semantic simplification, not a performance
accident. A pool would create ambiguous transaction ordering and busy behavior
before measurement shows a need.

Own a small forward-only migration ledger recording ordered ID, SHA-256 of exact
migration content, application time, binary/schema version, and outcome. Apply
under an appropriate transaction and fail if an already-applied ID's content
changes. `user_version` may be a convenience marker but is not authority. This
is one of the few mechanisms Joshi should write because the checksum semantics
are part of recoverability and provenance.

Adopt `sha2` 0.10.9 for SHA-256 over exact blob bytes. Retaining the 0.10 line is
also likely to coexist better with protocol dependencies; moving solely to the
0.11 line would not change SHA-256 output but would add another crypto-common
generation in today's graph. Do not add BLAKE3 as an unlabeled second meaning of
“digest.” It can be reconsidered for a measured, explicitly named internal
performance index, never as an implicit replacement for an evidence reference.

Adopt `tempfile` 3.27 for safe allocation and cleanup only. It must not hide the
durability protocol: create in the destination filesystem, write, flush and sync
file, atomically rename, sync parent directory, then commit the SQLite reference.
Do not use a generic atomic-write crate unless a crash test proves that exact
ordering on supported macOS/filesystems.

### Gate

Build a kill-point test around each persistence boundary:

1. temp allocated;
2. partial bytes written;
3. file synced;
4. rename complete;
5. parent synced;
6. DB transaction begun;
7. reference committed;
8. checkpoint/backup in progress.

On restart, every committed reference resolves to bytes with the declared
SHA-256; no half-record is visible; unreferenced complete blobs are recoverable
or garbage-collectable under an explicit policy. Repeat migration application,
change an old migration byte, and verify checksum mismatch is fatal. Restore a
live backup into a fresh process and replay it.

## 8. Arrow, Parquet, local API, and UI transport

### Observed facts

The Rust Arrow project publishes coordinated Arrow and Parquet crates in the
[arrow-rs repository](https://github.com/apache/arrow-rs). The surveyed stable
family is 59.2.0. Parquet features are documented in the [Rust Parquet
API](https://arrow.apache.org/rust/parquet/index.html). The Arrow logical memory
format and Parquet storage format are related but distinct; see the [Arrow
format specification](https://arrow.apache.org/docs/format/Columnar.html).

The Parquet crate's defaults pull several compression codecs. Its `arrow`
integration also brings Arrow IPC machinery transitively. That does not make
Arrow IPC a durable Joshi format.

Axum 0.8 provides an [`Sse` response](https://docs.rs/axum/latest/axum/response/sse/)
with event IDs and keepalive support. Its WebSocket extractor is feature-gated;
there is no need to enable it merely because the UI is live.

### Judgment

Adopt an exact matched family when the exporter lands:

- `arrow-array = =59.2.0`;
- `arrow-schema = =59.2.0`;
- `parquet = =59.2.0`, defaults disabled, features `arrow,zstd`.

Exact family pinning prevents a partial Arrow update and makes research export
behavior reviewable. Accept Arrow IPC as a transitive implementation detail of
the adapter if required, but do not publish it as a durable interchange contract
without a separate decision. Do not add every Parquet codec. Do not embed
DuckDB, DataFusion, or Polars in the recorder: V1 writes manifested Parquet and
the Python/DuckDB research layer reads it.

Own the export manifest. It records partition query/as-of bounds, schema epoch
and fingerprint, file paths, row counts, min/max/null statistics as applicable,
SHA-256, producer build, and completion state. Write files before atomically
publishing the complete manifest.

Adopt Axum 0.8.9, Tower 0.5.3, and Tower HTTP 0.6.11 when the local API exists.
Reqwest 0.13.4 already resolves Tower HTTP 0.6.11; choosing current 0.7 merely
for freshness would create two middleware generations without a V1 benefit.
Reconsider 0.7 only for a named feature or when Reqwest's compatible line moves.
Choose minimal Axum features (`http1`, `json`, `tokio`, route tracing as needed),
only explicit Tower HTTP layers, and same-origin static assets. SSE is the first
server-to-browser stream; browser commands are ordinary POST requests. Do not
enable CORS, WebSocket, cookies/sessions, templating, or a second API framework
without a named consumer.

SSE delivery is a projection notification, not the evidence log. Event IDs must
identify a durable cursor or let the browser learn that it must refetch. A slow
or disconnected UI may miss hints without corrupting truth, provided the UI
visibly catches up from durable state or reports a gap.

### Gate

Export a partition containing nulls, maximum integer strings, timestamps,
unknown variants, and nested/list values. Read it independently through PyArrow
and DuckDB; compare schemas, row count, exact values, timestamp units/zones, and
manifest/file digests. Rewrite from a deterministic fixture and determine which
physical-byte differences are acceptable; never claim byte-deterministic
Parquet unless proved.

For the UI, throttle a browser until the SSE buffer is exceeded, reconnect with
`Last-Event-ID`, restart the server, and rotate the durable projection. The UI
must end at the current projection or explicitly surface an unrecoverable range.
Test that no source credential can appear in an API DTO, error body, URL, static
asset, or developer console.

## 9. Solana, Helius, Pump, PumpSwap, and Meteora

### 9.1 Boundary first

Protocol facts belong in small source/protocol adapters. Domain and evidence
crates see Joshi DTOs only. Adapters expose read/decode/normalize operations, not
SDK clients or builders. Package features for transaction construction,
signing, sending, airdrops, and local validators remain disabled or absent.

The first production path should use documented Solana/Helius HTTP and
WebSocket protocols over the already adopted transports. The [official Solana
Rust client documentation](https://solana.com/docs/clients/official/rust)
describes the componentized SDK direction. Avoid the broad `solana-sdk` default
surface and `solana-client` unless a specific parsing primitive cannot be
implemented or imported narrowly.

### 9.2 Helius

**Observed fact.** Helius exposes provider-specific WebSocket methods including
[`transactionSubscribe`](https://www.helius.dev/docs/api-reference/rpc/websocket/transactionsubscribe).
The broad [Helius Rust SDK](https://github.com/helius-labs/helius-rust-sdk)
includes substantial Solana and transaction-oriented surface and uses defaults
that do not match Joshi's intentionally narrow TLS graph. Helius also publishes
a [LaserStream SDK](https://github.com/helius-labs/laserstream-sdk), while the
Yellowstone ecosystem currently exposes `yellowstone-grpc-client` 13.3.

**Judgment.** Adopt raw standard/provider RPC and WS adapters first. Reject the
general Helius SDK in broad core. Defer LaserStream/Yellowstone until baseline
measurements establish that standard feeds cannot meet loss, ordering,
backfill, or latency needs. If probed, place gRPC/protobuf and its runtime graph
in a replaceable adapter and preserve the same normalized DTO/evidence contract.

**Gate.** Run the same captured interval through standard WS plus backfill and a
candidate streaming service. Compare completeness, duplicates, observed/source
ordering, reconnect behavior, latency distribution, provider cost units, and
replay digest. Faster is not better if gaps become unknowable.

### 9.3 Pump and PumpSwap

The primary protocol artifacts for the survey are:

- Pump public docs/IDL at immutable commit
  `9c82f61cb711b044a17f770ab8ce9f9bdf78f333`, including
  [`pump.json`](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/idl/pump.json);
- PumpSwap public documentation at that same [docs
  revision](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/PUMP_SWAP_README.md);
- official Rust [`pump-rust-client`
  **0.1.11**](https://crates.io/crates/pump-rust-client/0.1.11), crates.io checksum
  `c738b448634ffbc3ec6d0e5d3c38253a4a8a9216ec78929b1a1b4e1e773d59fa`,
  whose [packaged VCS metadata](https://docs.rs/crate/pump-rust-client/0.1.11/source/.cargo_vcs_info.json)
  records commit `71f2983cd893b284af489c9d2c677d1f7ae9aff9`;
- independent TypeScript oracles
  [`@pump-fun/pump-sdk@1.36.0`](https://www.npmjs.com/package/@pump-fun/pump-sdk/v/1.36.0)
  and
  [`@pump-fun/pump-swap-sdk@1.19.0`](https://www.npmjs.com/package/@pump-fun/pump-swap-sdk/v/1.19.0).

**Observed fact.** `pump-rust-client` 0.1.11 is MIT and has empty default
features, which is helpful. The package does not declare a repository URL, so
the crates.io tarball/checksum is presently the reproducible source artifact;
the embedded commit identifier is provenance but not independently browsable
source. Its direct manifest permits broad ranges:
`anchor-lang >=0.31,<2`, `anchor-spl >=0.31,<2`, and
`solana-program >=2.1.21`; the optional `client`/`local-validator` features add
more runtime capabilities. Its published source lock resolves the direct
Pump-facing `solana-program` at 2.3.0 and Anchor at 1.0.2, whose subtree includes
Solana 3-generation components. Multiple generations are therefore a real graph
possibility even before Joshi adds its own preferences.

**Judgment.** Probe the official Rust package only in an isolated decoder/math
adapter with `pump-rust-client = "=0.1.11"`, default features disabled, the
registry checksum recorded, and a probe lock matching the publisher's concrete
Anchor/Solana resolution. Never enable `client` or `local-validator` in the V1
read-only binary. Do not re-export generated accounts, instructions, clients,
or SDK error types.

The broad ranges are not evidence that the package is defective. They are a
reason not to let the root resolver casually choose the protocol ABI/type
universe. If a narrower manual decoder over a few audited Solana component
types has materially less graph and passes the same vectors, prefer it.

Use the exact TypeScript SDKs as independent offline oracles for account/event
decoding and quote math. They are not runtime truth and should not share
implementation code with Rust. Store inputs, exact versions, outputs, and
rounding expectations as committed fixtures.

**Gate.** Test valid, boundary, malformed, unknown-version, and historical
account/event bytes plus exact quote vectors. Compare Rust adapter, official
TypeScript SDK, documented formula, and when possible chain-observed result.
Every discrepancy remains visible; do not “normalize” it away with float
tolerances.

### 9.4 Meteora DLMM

The surveyed provenance is the [Meteora DLMM repository commit
`fb02e51ae677bbd18e76543f702dae40632426db`](https://github.com/MeteoraAg/dlmm-sdk/tree/fb02e51ae677bbd18e76543f702dae40632426db)
and
[`@meteora-ag/dlmm@1.9.14`](https://www.npmjs.com/package/@meteora-ag/dlmm/v/1.9.14).

**Observed facts.** At that revision the Rust workspace uses Anchor 0.31 and
Solana SDK 2.1-compatible ranges and brings a broad graph through `commons`,
including async Anchor client/Tokio and several math/serialization packages. Its
[changelog](https://github.com/MeteoraAg/dlmm-sdk/blob/fb02e51ae677bbd18e76543f702dae40632426db/CHANGELOG.md)
states that the earlier `dlmm_interface` was removed; advice to depend on that
crate is stale for this revision. The `commons` package lacks a declared license
and the repository root does not provide clear license text for the Rust code.
The published TypeScript package declares ISC.

**Judgment.** Do not ship, copy, or link the Rust repository as a production
dependency until its license is clarified. Its broad graph also makes it a poor
broad-core dependency. It may be examined in an isolated research probe at the
exact revision. Adopt the exact ISC TypeScript package solely as an offline
quote/state oracle while building a narrow Rust normalization/math adapter from
licensed specifications and clean protocol observations.

No legal conclusion is implied; “license unclear” is a release gate requiring
upstream clarification, not an accusation.

**Gate.** Construct boundary fixtures around active bin, bin arrays, fee/reward
state, price/amount conversion, partial range liquidity, rounding, and
add/remove-liquidity views. Compare exact TypeScript outputs with Rust and
on-chain state. Record upstream commit/package tarball digest and license in the
fixture manifest.

### 9.5 Protocol dependency acceptance rule

A native protocol crate advances from probe to adopt only if it:

1. has usable license provenance;
2. has an immutable source/package identity and reproducible lock;
3. can compile without execution/signing features;
4. does not leak types across the adapter;
5. has an understood duplicate/unsafe/crypto/TLS graph;
6. passes independent differential fixtures;
7. makes the adapter smaller or safer than narrow manual parsing;
8. preserves unknown variants and original bytes for future reinterpretation.

## 10. Configuration, secrets, diagnostics, and metrics

### Matrix

| Concern | Decision | Candidate | Boundary |
|---|---|---|---|
| CLI | Adopt | `clap` 4.5.60 requirement / 4.6.6 current lock, derive | Explicit startup arguments and subcommands only. |
| Typed config file | Adopt when needed | `toml` 1.1.4 + Serde | Versioned closed config, explicit precedence, actionable parse paths. |
| Platform locations | Adopt | `directories` 6.0 `ProjectDirs` | Resolve default app data/config/cache paths; CLI override remains explicit. |
| Secret wrapper | Adopt | `secrecy` 0.10.3 | Adapter edge and explicit exposure only. |
| Dotenv/magic overlay | Reject | `dotenvy`, generic env config mergers | Hidden precedence and accidental secret loading damage reproducibility. |
| Structured diagnostics | Adopt | `tracing` 0.1.44 + `tracing-subscriber` 0.3.23 | Redacted operational context, never authoritative evidence. |
| Async log appender | Reject initially | `tracing-appender` | Common nonblocking mode can drop events and guards can be lost on abrupt exit. |
| Metrics facade | Probe | `metrics` 0.24.6 | Counters/gauges/histograms with finite, reviewed label vocabulary. |
| Prometheus endpoint | Probe | `metrics-exporter-prometheus` 0.18.3 | Disable defaults, render its recorder on existing Axum, and configure upkeep explicitly; defaults add HTTP listener and push gateway. |

### Observed facts

[`directories::ProjectDirs`](https://docs.rs/crate/directories/latest) computes
platform-appropriate application directories. [`secrecy`](https://docs.rs/secrecy/latest/secrecy/)
requires explicit secret exposure and reduces accidental `Debug`/serialization
leaks, but cannot protect a key from a compromised process.

The [`tracing-appender` non-blocking
implementation](https://docs.rs/tracing-appender/latest/src/tracing_appender/non_blocking.rs.html)
documents lossy behavior and the need to retain its guard. The [`metrics`
facade](https://docs.rs/metrics/latest/metrics/index.html) is recorder-based;
the application still owns label cardinality and exporter lifecycle.

### Judgment

Configuration contains paths and public operational settings. Credentials are
referenced by an explicit source and loaded only by the source adapter; they are
never serialized into evidence, replay bundles, snapshots, URLs, errors, or
debug output. Use `PathBuf`, not home-directory string concatenation. No crate
should search dotenv files or merge environment values behind the caller's
back.

Wrap/redact URL display because provider API keys commonly appear in query
parameters. Secrecy is defense in depth, not a substitute for redaction or OS
permissions.

Tracing explains what the process is doing; evidence records what the system
knows. Never recover truth from logs. Metrics labels must come from finite enums
such as source kind/status class, never wallet, mint, signature, URL, error text,
or user-supplied strings. A metric exporter that mints unbounded labels is a
local denial-of-service bug.

### Gate

Snapshot every CLI/config error with secret-shaped values and assert complete
redaction. Traverse API responses, logs, metrics labels, panic hooks, replay
bundles, and support archives. Verify two identical explicit configurations
resolve the same paths/settings regardless of working directory and ambient
dotenv files.

## 11. Testing, fuzzing, and deterministic fixtures

### Decision matrix

| Layer | Decision | Tool | Use |
|---|---|---|---|
| Unit/integration | Adopt | built-in test harness | Small invariants and offline vertical slice. |
| Property tests | Adopt | `proptest` 1.11 | Exact math, DTO normalization, state transitions, range/coverage merging. |
| Fuzzing | Adopt | `cargo-fuzz` 0.12, `libfuzzer-sys` 0.4.13, `arbitrary` 1.4.2 | Parser/framing/migration and protocol adapter targets. |
| Concurrency models | Probe | `loom` 0.7.2 | Reduced one-writer/queue/shutdown algorithms. |
| Canonical snapshots | Adopt plain files | committed bytes/JSON/SQL/manifest fixtures | Human-reviewable exact inputs and outputs with provenance. |
| Noncanonical snapshots | Limited adopt | `insta` 1.48 | CLI errors/debug renderings only, reviewed interactively. |
| Model checking | Defer | Kani | Only after a bounded proof obligation is named. |
| Mutation testing | Probe/scheduled | `cargo-mutants` 27.1 | Evidence/accounting semantic cores, not the whole workspace on every PR. |

### Observed facts

Cargo Fuzz's [setup documentation](https://rust-fuzz.github.io/book/cargo-fuzz/setup.html)
requires a nightly toolchain and supports Apple silicon. That nightly is a
tooling dependency; production remains on pinned stable. [Loom](https://docs.rs/loom/latest/loom/)
explores modeled concurrent executions by substituting synchronization
primitives. Insta's [review workflow](https://insta.rs/docs/cli/) makes snapshot
updates convenient, including modes that can automatically accept changes.

### Judgment

Canonical fixtures must be boring files with explicit provenance and ordinary
diffs. Never set an automatic Insta update mode in CI for protocol, evidence,
accounting, schema, or export contracts. Insta is reasonable for error-message
or presentation snapshots whose exact bytes are not part of truth.

Fuzz untrusted boundaries and assert semantic properties, not only “did not
panic.” Examples: malformed data cannot be committed as a valid observation;
re-decoding retained bytes cannot alter the original acquisition record;
round-trip normalization is idempotent; invalid migrations leave the prior
schema usable.

Loom should model a small abstraction of admission, writer acknowledgment,
cancellation, and flush; trying to run the real network/SQLite stack under Loom
is unlikely to pay off. Kani waits until a particular bounded function and proof
claim exist.

### Gate

Maintain a fixture manifest with source, retrieval/creation date, upstream
version/commit, license/redistribution status, exact input digest, expected
semantic result, and whether bytes may be published. Fuzz corpora may contain
derived/public data only; do not accidentally commit provider keys or private
wallet/account material.

## 12. Supply-chain, licenses, advisories, and graph hygiene

### Decision matrix

| Tool | Version researched | Decision | Purpose and caveat |
|---|---:|---|---|
| `cargo-audit` | 0.22.2 | Adopt | Check the committed lock against [RustSec](https://rustsec.org/). Advisory absence is not a security audit. |
| `cargo-deny` | 0.20.2 | Adopt | [Advisory, ban, license, and source checks](https://embarkstudios.github.io/cargo-deny/checks/index.html). Keep exceptions narrow and explained. |
| `cargo-vet` | 0.10.2 | Pilot | Audit high-risk crates and imports using [cargo-vet](https://mozilla.github.io/cargo-vet/). Auto exemptions are bootstrap inventory, not review evidence. |
| `cargo-nextest` | 0.9.143 | Adopt | Faster/reliable workspace runner with CI archive/config pin. |
| `cargo-llvm-cov` | 0.9.0 | Adopt | Coverage visibility; do not optimize tests for a percentage. |
| `cargo-machete` | 0.9.2 | Advisory adopt | Detect likely unused dependencies; review target/build/dev false positives. |
| `cargo-about` | 0.9.1 | Distribution gate | Generate license notices from the actual lock. |
| `cargo-auditable` | 0.7.5 | Release gate | Embed dependency metadata in shipped binaries; see [upstream](https://github.com/rust-secure-code/cargo-auditable). |

### Current duplicate graph

The 2026-08-16 `cargo tree --workspace --target=all --duplicates` snapshot has
no Solana, Anchor, SQLite, Arrow, or gRPC generation yet. Notable duplicates are:

| Duplicate | Cause | Decision |
|---|---|---|
| `digest`/`block-buffer`/`crypto-common` 0.10 and 0.11 | SHA-256 0.10.9 versus WebSocket SHA-1 0.11 subtree | Accept and monitor. Moving the evidence hash alone would not remove all protocol-era duplication and is not a semantic benefit. |
| `getrandom` 0.3 and 0.4 | Proptest/dev randomness versus Tungstenite/tempfile graph | Accept dev/runtime generation split; recheck in protocol builds. |
| `rand` 0.9 and 0.10 | Dev properties versus WS dependencies | Accept for now; never expose either RNG in evidence semantics. |
| `syn` 2 and 3 | Established derives versus newer Clap derive graph | Accept procedural-macro build-time duplication. |
| `webpki-roots` 0.26 and 1.0 | Wrapper and current TLS roots | Inspect feature graph; presently not a second TLS backend. |

Duplicates are costs, not automatic defects. The graph gate is stricter for
runtime/crypto/protocol type universes because two Solana/Anchor generations can
make types non-interoperable and inflate audit surface. Build-time `syn`
duplicates are less consequential.

### Judgment

Adopt `cargo-audit` plus `cargo-deny` in routine CI. Pilot `cargo-vet` on
protocol, crypto, unsafe, parser, and persistence crates; a team this small
cannot meaningfully line-audit the whole crates.io graph immediately. Record
trusted publisher/source criteria narrowly. Do not transform all unaudited
crates into permanent wildcard exemptions just to make the check green.

Only crates.io and explicitly approved immutable Git sources are allowed.
Disallow unknown registries and moving branches. A Git revision does not solve
license provenance or protect against a bad upstream commit; a crates.io
checksum does not prove semantic quality.

Generate license notices/SBOM inputs from the lock before any distribution.
Meteora's unclear Rust licensing is exactly the kind of issue this gate must
catch before code has already become architectural.

## 13. Abstractions explicitly rejected in V1

| Abstraction | Why it is dangerous here | Replacement |
|---|---|---|
| Automatic HTTP/Tower retries | Hides acquisition attempts and can exceed provider/semantic budgets. | Project source supervisor with explicit attempt evidence. |
| Unbounded async queues | Converts overload into memory growth and unknowable loss timing. | Bounded record channel plus byte permits and explicit gap policy. |
| `broadcast` as event truth | Slow receivers lag and lose values. | Durable projection cursor; broadcast/SSE only expendable hints. |
| SQLite connection pool/ORM | Obscures one-writer ordering, transactions, busy policy, and SQL shape. | One Rusqlite owner and explicit SQL/repository functions. |
| Generic migration framework | `user_version` or opaque checksums do not satisfy provenance. | Small SHA-256 migration ledger. |
| Broad Solana/provider SDK in core | Pulls execution capabilities and multiple protocol generations into domain code. | Narrow read-only adapter and normalized DTOs. |
| SDK DTOs in domain | Couples retained evidence to one dependency/version's interpretation. | Retain original bytes and map to versioned Joshi DTOs. |
| Fixed decimal/float as truth | Cannot represent arbitrary integer/rational protocol values exactly. | u64/u128/i128/U256 and BigInt/BigRational with explicit rounding. |
| Magical config/env merge | Makes startup state and credential provenance hard to reproduce. | Typed explicit CLI/file/reference precedence. |
| Async logs as evidence | Buffers may drop and logs lack commit/coverage semantics. | Durable evidence records; logs are diagnostics. |
| Generated schema as authority | Generator changes can redefine contracts without a semantic decision. | Versioned project schema plus goldens; generated schema is a check. |
| Auto-accepted snapshots | Turns an implementation change into “expected truth” without review. | Plain canonical goldens and manual discrepancy disposition. |
| Generic atomic-write helper | May not perform file and directory sync in Joshi's required order. | Explicit same-filesystem durability protocol over `tempfile`/`std`. |
| Arrow IPC by transitive accident | A pulled crate is not a chosen durable format. | Manifested Parquet is the approved research interchange. |

## 14. What to buy and what to own

### Do not write these ourselves

- HTTP, WebSocket, TLS, URL, or JSON machinery;
- SQLite FFI, WAL, backup, or SQL parsing;
- SHA-256 or cryptographic primitives;
- secure temporary-name allocation;
- Arrow array and Parquet encoding/decoding;
- Axum HTTP routing or SSE wire framing;
- GCRA/token-bucket primitives;
- arbitrary/fixed-width integer or rational arithmetic;
- secret-value wrapper behavior;
- property generation, fuzzing engine, coverage instrumentation, or advisory
  database client.

### Keep these bespoke

- evidence envelopes, original-byte retention, identities, source/acquisition
  clocks, assertions, coverage, gaps, corrections, and provenance;
- commit semantics, one-writer acknowledgment, crash recovery, as-of vectors,
  replay ordering, and witnessed/retrospective distinctions;
- queue byte budgets, overload outcomes, provider quota meaning, retry evidence,
  WS generations, overlap, and backfill policy;
- canonical protocol DTOs, unknown-variant retention, capability boundaries,
  independent-oracle comparisons, and discrepancy disposition;
- lots, episodes, exact accounting, fee/rounding policies, and model labels;
- migration checksum/epoch semantics, schema contracts, CAS references, and
  Parquet export manifests;
- user gesture/annotation/decision ontology and the sensorium that captures it.

The line is not “custom code good” or “dependency bad.” We outsource mechanism
where a crate has a stable, testable seam. We retain meaning where changing a
default could change what Joshi believes happened.

## 15. Dependency-wave bakeoff

Before adding the next broad set of crates, implement one common, offline-testable
vertical fixture through candidate boundaries:

### Fixture

A deterministic fake provider serves:

- an HTTP historical page with a maximum u64-as-string, unknown protocol
  variant, and `Retry-After` response before success;
- a WebSocket sequence containing duplicate frames, a malformed frame,
  disconnect, resubscription generation, overlap, and a provable gap;
- protocol account/event bytes and quote vectors for Pump/PumpSwap/Meteora;
- a controlled shutdown at every queue/persistence boundary.

The system stores original bytes in SHA-256 CAS, commits immutable acquisition
and observation records through one writer, projects a current view, streams a
hint over SSE, exports a manifested Parquet partition, and replays offline.

### Falsifiable acceptance criteria

1. Rust replay produces the same semantic projection digest without network,
   provider SDK, secrets, or wall-clock dependence.
2. Every network attempt and missing interval is visible; disabling any hidden
   client retry does not change the apparent acquisition count.
3. Memory stays under a declared bound for both many-small and one-large inputs;
   overload becomes explicit evidence rather than silent loss.
4. Kill-point recovery never exposes a referenced-missing blob or half-committed
   observation.
5. Rust protocol results match the pinned independent TypeScript oracle on exact
   integers/rounding, or preserve and classify the discrepancy.
6. PyArrow and DuckDB independently read the Parquet export with matching exact
   values and manifest statistics.
7. A lagged/restarted browser reaches durable current state through SSE resume
   or explicit refetch/gap behavior.
8. `cargo tree -d` and the feature graph contain no unexplained execution,
   native-TLS, gRPC, Solana, Anchor, crypto, or async-runtime generation.
9. `cargo deny`, `cargo audit`, licenses, and fixture redistribution checks pass
   with narrow, documented exceptions only.

If the official protocol SDK makes criteria 5 and 8 worse than a narrow decoder,
reject it despite saving initial lines of code. If Rusqlite's synchronous owner
cannot sustain the measured ingest fixture without violating latency/bounds,
measure where the time went before adding a pool. If SSE cannot meet criterion
7, add WebSocket only for the proven requirement.

## 16. Recommended introduction order

1. Keep the current domain/evidence/accounting/source baseline and make all
   package metadata/dependencies/lints inherit from the workspace.
2. Add Rusqlite + bundled SQLite, migration ledger, SHA-256 CAS, and crash tests.
3. Add Axum SSE and the same-origin local API around durable projections.
4. Add the exact Arrow/Parquet 59.2 family and cross-reader export gate.
5. Add tracing/subscriber and finite metrics only where operational questions
   are already named.
6. Probe protocol packages one at a time in private adapter manifests, starting
   with raw transport plus retained bytes and independent TypeScript goldens.
7. Consider Helius LaserStream/Yellowstone only after standard feed completeness
   and recovery have been measured.

This order keeps broad, unstable dependency graphs out of the recording spine
until the evidence machine can test them rather than merely trust them.
