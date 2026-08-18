# Rust crate estate

Status: implementation decision register  
Survey date: 2026-08-16  
Detailed evidence: [`lanes/06_crate_estate.md`](lanes/06_crate_estate.md)

This is the dependency policy for the V1 read/record/replay/render/analyze
system. It is intentionally narrower than a catalogue of useful Rust crates.
A crate belongs in the workspace only when it replaces commodity machinery
without taking ownership of Joshi's evidence, replay, accounting, or protocol
semantics.

## Decision vocabulary

| State | Meaning |
|---|---|
| **Adopt** | Approved when a named consumer exists. Keep the resolved version in `Cargo.lock`; do not add speculative dependencies. |
| **Probe** | Evaluate behind a private adapter or dev-only bakeoff. It is not part of the durable architecture yet. |
| **Defer** | Plausible after a concrete need or scale threshold appears. |
| **Reject** | Do not introduce in V1; it conflicts with an architectural invariant or duplicates a smaller mechanism. |

“Adopt” does not mean “add all of these now.” The smallest dependency graph is
the one needed by the current executable path.

## Workspace and dependency rules

- Pin the toolchain exactly to Rust **1.97.1** in `rust-toolchain.toml`. Rust
  1.97.1 contains the compiler fix that makes 1.97.0 an unsuitable reproducible
  baseline.
- Use edition 2024, resolver 3, `rust-version = "1.97"`, a committed
  `Cargo.lock`, workspace-inherited package metadata/dependencies/lints, and
  release overflow checks.
- CI and local release gates operate on `--workspace --all-targets`; the current
  `default-members` intentionally omit some libraries.
- Ordinary implementation crates use compatible requirements plus the lockfile.
  Protocol packages, wire-format families, and independent oracles use exact
  versions, registry checksums, or immutable Git revisions.
- A dependency update is a reviewed change: inspect `cargo tree -d`, feature
  unification, licenses/advisories, MSRV, and the relevant golden/differential
  tests. Do not run blanket `cargo update` as maintenance.
- Do not re-export third-party SDK, HTTP, SQL, or Arrow types from domain APIs.

## Approved baseline

Versions are the researched compatible line as of the survey date. Existing
workspace versions remain valid even if a newer compatible release is selected
by the lockfile.

| Concern | State | Crate/version | Feature and boundary policy |
|---|---:|---|---|
| CLI | Adopt | `clap` requirement 4.5.60; current lock 4.6.6 | `derive`; process edge only. |
| Typed errors | Adopt | `thiserror` 2.0.20 | Libraries expose typed, inspectable errors. |
| Application context | Defer | `anyhow` 1.0.104 | Only at a binary/task boundary; never a domain API. |
| Rich terminal diagnostics | Defer | `miette` 7.6 | Add only if operator diagnostics justify its graph. |
| Serialization | Adopt | `serde` 1.0.229, `serde_json` 1.0.151 | Strict DTOs; deny unknown fields where closed schemas require it. No `preserve_order`, `arbitrary_precision`, or `unbounded_depth`. |
| RFC 8785 canonical JSON | Probe/dev | `serde_json_canonicalizer` 0.3.2 | Retain the current accounting test oracle; promote only after cross-language vectors. Large financial integers remain strings before canonicalization. |
| Parse-path errors | Adopt | `serde_path_to_error` 0.1.20 | Untrusted provider/config boundaries only. |
| Generated JSON Schema | Probe | `schemars` 1.2.2 | Dev/tooling drift check; generated schema is not protocol authority. |
| Stable identifiers | Adopt | project-owned newtypes | Validated strings with explicit namespaces. Do not introduce UUIDs by default. |
| Solana base58 text | Adopt in adapter | `bs58` 0.5.1 | Commodity codec plus project-owned length/type validation; base58 text is not a generic domain ID. |
| Occurrence IDs | Defer | `uuid` 1.24 | UUIDv7 only if a later local-occurrence use case is proved; never truth or replay order. |
| Wall time | Adopt | `time` 0.3.55 | Wire parsing/formatting; use `Instant` for elapsed time. No direct `chrono`. |
| Exact ledger math | Adopt | `num-bigint` 0.4.6, `num-rational` 0.4.2, `num-traits` 0.2.19 | Keep the aligned 0.4 bigint family. Integers/rationals, not floating point, own truth. |
| Protocol U256 | Probe | `ruint` 1.20 | Adapter/math module only after Pump/Meteora vectors demand it. |
| Fixed decimal | Reject for truth | `rust_decimal` 1.42 | Display/input convenience may be reconsidered; it cannot represent general protocol or rational truth. |
| Async runtime | Adopt | `tokio` 1.53.1 | Minimal named features. No `full`. |
| Cancellation | Adopt | `tokio-util` 0.7.19 | `CancellationToken` plus a project-owned phased-shutdown protocol. |
| Streams/sinks/bytes | Adopt | `futures-util` 0.3.34, `bytes` 1.12.1 | Adapter internals only. |
| HTTP | Adopt | `reqwest` 0.13.4 | `default-features = false`, `json,rustls`; explicitly disable its implicit retry policy. |
| WebSocket | Adopt | `tokio-tungstenite` 0.30 | `default-features = false`, `connect,rustls-tls-webpki-roots`; source adapters only. |
| URL parsing | Adopt | `url` 2.5.8 | Wrap/redact URLs before logging because query strings can contain credentials. |
| Retry | Reject generic middleware | project-owned source supervisor | Attempts, delay, exhaustion, and coverage are evidence. A hidden retry layer is semantically unsafe. |
| Rate limiting | Probe | `governor` 0.10.4 | Primitive only, preferably `default-features = false, features = ["std"]`; wrapper owns provider quotas and evidence. |
| SQLite | Adopt at persistence consumer | `rusqlite` 0.40.2 | `default-features = false`; use bundled SQLite >=3.51.3 plus only needed `backup`/checking features. One writer, no pool. |
| Migrations | Reject generic runner | project-owned SHA-256 migration ledger | Forward-only ordered SQL, content checksum, transactional application. `user_version` alone is insufficient. |
| Hashing | Adopt | `sha2` 0.10.9 | SHA-256 over exact bytes for evidence/CAS. Algorithm is part of the reference. |
| Temporary files | Adopt | `tempfile` 3.27 | Allocation/cleanup only; Joshi still owns write, sync, rename, parent sync, then DB-reference ordering. |
| Parquet export | Adopt at exporter | Arrow/Parquet family `=59.2.0` | Exact matched `arrow-array`, `arrow-schema`, `parquet`; Parquet with `default-features = false, features = ["arrow","zstd"]`. |
| Embedded analysis engine | Reject | DuckDB/DataFusion Rust bindings | V1 analysis consumes manifested Parquet in Python/DuckDB. Do not put an engine in the recorder. |
| Local HTTP API | Adopt at API consumer | `axum` 0.8.9, `tower` 0.5.3, `tower-http` 0.6.11 | Minimal features. Stay on the already resolved Tower HTTP 0.6 line unless a 0.7-only capability is proved; SSE first, same-origin static UI, no CORS or WebSocket yet. |
| Configuration | Adopt when file exists | `toml` 1.1.4, `directories` 6.0 | Typed config, deny unknown fields, explicit precedence, platform paths. No magical environment overlay. |
| Secrets in memory | Adopt | `secrecy` 0.10.3 | Source adapter edge only. It reduces accidental exposure; it is not a vault. |
| Logging | Adopt | `tracing` 0.1.44, `tracing-subscriber` 0.3.23 | Structured diagnostics with redaction. Logs are not evidence. |
| Async log writer | Reject initially | `tracing-appender` | Its common non-blocking mode can be lossy. If later used, retain the guard and still treat logs as expendable. |
| Metrics | Probe | `metrics` 0.24.6, `metrics-exporter-prometheus` 0.18.3 | Exporter defaults disabled; render its recorder on the existing server instead of adding its listeners/push gateway. Finite labels; metrics are not evidence. |
| Properties | Adopt | `proptest` 1.11 | Domain/accounting/state-machine invariants. |
| Fuzzing | Adopt in tooling | `cargo-fuzz` 0.12, `libfuzzer-sys` 0.4.13, `arbitrary` 1.4.2 | Nightly tooling only; target parsers, framing, migration recovery, and protocol normalization. |
| Concurrency model check | Probe | `loom` 0.7.2 | Tiny modeled queue/shutdown algorithms, not production I/O code. |
| Snapshots | Limited adopt | plain committed goldens; `insta` 1.48 only for noncanonical output | Never auto-accept canonical wire/accounting/protocol fixtures. |

## Protocol and provider quarantine

The system needs protocol facts but does not need a protocol SDK in broad core.
No V1 package may import signing, transaction construction, or submission
capabilities.

| Surface | State | Provenance | Rule |
|---|---:|---|---|
| Solana standard HTTP/WS | Adopt | documented JSON-RPC | Implement a narrow read-only adapter over `reqwest`/`tokio-tungstenite`; normalize immediately into Joshi DTOs. |
| Solana component crates | Probe | match adapter generation exactly | Use only the smallest component crate required for canonical parsing. Avoid monolithic `solana-sdk` and `solana-client`. |
| Helius standard RPC/WS | Adopt | documented endpoints | Raw transport first. Provider-specific methods are capability-gated source adapters. |
| Helius Rust SDK | Reject in broad core | `helius` 1.1.0 | Broad Solana/transaction surface and default native-TLS graph violate the read-only narrow boundary. |
| Helius LaserStream / Yellowstone | Defer | `helius-laserstream` 0.6.3 / `yellowstone-grpc-client` 13.3 | Reconsider only after the standard-source baseline is measured and loss/backfill needs are known. |
| Pump official Rust client | Probe in isolated adapter | `pump-rust-client` 0.1.11 (manifest `=0.1.11`); crates.io SHA-256 `c738b448634ffbc3ec6d0e5d3c38253a4a8a9216ec78929b1a1b4e1e773d59fa`; packaged VCS metadata records commit `71f2983cd893b284af489c9d2c677d1f7ae9aff9` | Keep default features empty; never enable `client`/`local-validator`; do not expose SDK types. Its broad Anchor/Solana ranges and absent repository URL require an exact lock-and-feature probe. |
| Pump/PumpSwap TypeScript SDKs | Adopt as independent oracle only | `@pump-fun/pump-sdk@1.36.0`; `@pump-fun/pump-swap-sdk@1.19.0` | Offline differential fixtures or an isolated research harness, not runtime authority. |
| Pump public docs/IDL | Adopt as source material | docs commit `9c82f61cb711b044a17f770ab8ce9f9bdf78f333` | Vendor/provenance the exact relevant artifact; test it against captured fixtures. |
| Meteora Rust repo | Probe only; blocked for production | commit `fb02e51ae677bbd18e76543f702dae40632426db` | The relevant Rust workspace is broad and its `commons` package/repository lacks clear package license metadata. Obtain license clarity before shipping any copied or linked code. |
| Meteora TypeScript SDK | Adopt as independent oracle only | `@meteora-ag/dlmm@1.9.14`, ISC | Differential quote/state fixtures in an isolated harness; no TypeScript SDK types in core. |

The Pump 0.1.11 source manifest permits wide Anchor/Solana ranges. Its published
lockfile resolves Pump-facing `solana-program` 2.3.0 while the Anchor 1.0.2
subtree includes Solana 3-generation components. That is a quarantine signal,
not proof of a bug: reproduce the publisher lock, examine `cargo tree -d`, then
falsify the adapter against official TypeScript fixture vectors before adoption.

## Supply-chain and quality gates

| Tool | State | Use |
|---|---:|---|
| `cargo audit` 0.22.2 | Adopt | RustSec advisory check on the committed lock. |
| `cargo deny` 0.20.2 | Adopt | Advisories, bans/duplicate policy, sources, and explicit license policy. |
| `cargo vet` 0.10.2 | Pilot | Audit high-risk protocol, crypto, parser, and unsafe crates. Auto-generated exemptions are inventory, not proof. |
| `cargo nextest` 0.9.143 | Adopt | Workspace test execution; ordinary `cargo test` remains supported. |
| `cargo llvm-cov` 0.9.0 | Adopt | Coverage signal for behavioral tests, never a quality target by itself. |
| `cargo machete` 0.9.2 | Adopt as advisory | Find unused dependencies; review build/dev/target false positives manually. |
| `cargo about` 0.9.1 | Defer to distribution | Produce notices/SBOM inputs from the actual locked graph. |
| `cargo auditable` 0.7.5 | Defer to release packaging | Embed dependency provenance in distributed binaries. |
| `cargo mutants` 27.1 | Probe on schedule | Selected accounting/evidence modules, not every PR. |
| Kani | Defer | Only after a small safety-critical function and proof obligation are named. |

The installed machine already has Rust 1.97.1, `cargo-audit` 0.22.2,
`cargo-vet` 0.10.1, `cargo-nextest` 0.9.136, `cargo-fuzz` 0.12.0, and
`cargo-insta` 1.28.0. Tool policy names desired compatible versions; tools
should be deliberately upgraded and pinned in CI rather than assuming whatever
is on Ember's PATH.

## Never outsource these semantics

These are project code even when commodity crates supply primitives:

- evidence envelopes, source/acquisition clocks, stable IDs, exact-byte blob
  references, coverage and correction semantics;
- commit ordering, crash recovery, replay order, as-of vectors, and witnessed
  versus retrospective views;
- bounded record-and-byte budgets, gap policy, retry-attempt evidence, source
  generations, overlap and backfill;
- protocol-normalized DTOs, capability boundaries, fixture provenance, and
  conformance decisions;
- accounting lots, cost basis, exact rational arithmetic, episode definitions,
  and strategy policies;
- migration-ledger meaning, schema epochs, export manifests, and canonical
  serialization contracts.

Conversely, do **not** write our own HTTP or WebSocket stack, TLS, URL or JSON
parser, SQLite binding/backup implementation, SHA-256, temporary-file allocator,
Arrow/Parquet encoder, web server or SSE framing, rate-limiter primitive,
big-integer/rational/U256 arithmetic, secret wrapper, property generator, or
fuzzing engine.

## Mandatory bakeoffs before the next dependency wave

1. **Transport/replay:** record HTTP and WS attempts, disconnects, duplicate
   frames, reconnect generations, overlap, `Retry-After`, and coverage gaps;
   replay them offline to the same projection digest.
2. **SQLite/CAS crash matrix:** terminate after every durable-write boundary and
   prove recovery leaves no referenced-missing blob or committed half-record.
3. **Protocol conformance:** run fixed Pump/PumpSwap/Meteora account and quote
   vectors through Rust normalization and the pinned TypeScript oracle; compare
   exact integers and explicit rounding.
4. **Parquet portability:** export a manifested partition, read it using both
   PyArrow and DuckDB, and verify row counts, nullability, integer widths,
   timestamps, schema fingerprint, and file digest.
5. **SSE resume/lag:** force a slow browser, reconnect with `Last-Event-ID`, and
   prove the UI either catches up from durable state or exposes an explicit gap.
6. **Dependency audit:** capture `cargo tree -e features` and `cargo tree -d` for
   the baseline and each protocol probe; reject unexpected TLS, async runtime,
   Solana, crypto, or serialization generations unless the adapter documents why.
