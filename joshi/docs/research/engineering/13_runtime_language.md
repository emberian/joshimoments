# Engineering 13 — runtime language and system boundary

Status: architecture recommendation and falsifiable bakeoff proposal; no implementation commitment.

Survey date: **2026-08-16**. The ecosystem claims below were checked against current official or
project-primary documentation on that date. This document uses **Fact** for externally checkable
capabilities or local-machine observations, **Judgment** for an engineering evaluation, and
**Inference** when a recommendation follows from several facts but is not guaranteed by them.

## Decision in one paragraph

**Recommendation:** make the first durable JOSHI runtime a **Rust event/replay/protocol core with
the existing React/TypeScript product glass**, connected through a versioned local API. Keep Python
and Julia outside the live authority path as research consumers of Parquet/Arrow/SQLite exports.
Keep the old Node Meteora builder quarantined as an explicitly temporary, unsigned subprocess if a
read-only experiment still needs it. Do not add OCaml to the initial runtime merely because its
domain-modeling experience is attractive, and do not rewrite the UI in Rust, Blazor, or Melange.
Modern C#/.NET plus React is the credible runner-up; F# inside that .NET service is a credible
semantic-core variant. A Rust edge + OCaml reducer + TypeScript UI becomes rational only if the
bakeoff shows that OCaml prevents important semantic defects that Rust does not and that this gain
pays for a third production toolchain and a permanent protocol boundary.

This is not a recommendation to translate `joshibot`. The old repository is compost and fixtures.
The recommendation is about where newly understood invariants should live.

## What is being optimized

JOSHI is not primarily a low-latency trading bot. Its load-bearing runtime jobs are:

1. ingest fallible, duplicated, late, gapped, and schema-drifting market/social/interaction inputs;
2. durably append raw evidence before interpretation;
3. deterministically rebuild versioned assertions, scenes, inventory intervals, and full episodes;
4. preserve exact integer quantities and explicit clocks, units, source status, and unknown states;
5. serve a highly interactive chart/feed/gesture surface with bounded staleness;
6. later isolate transaction construction, simulation, signing, submission, and reconciliation;
7. export stable research data without forcing notebooks to import the live runtime's object model.

The performance target is therefore **bounded lossless flow plus reproducible recovery**, not the
lowest possible median handler latency. A language does not provide deterministic replay by making
its scheduler deterministic: replay comes from an ordered immutable input, a pure/versioned
reducer, explicit clocks and randomness, stable arithmetic, and state hashes.

## Decision forces specific to Ember's machine and the compost

**Fact — local machine.** Direct inspection on the survey date found Apple arm64 macOS 26.6.1,
96 GiB RAM, .NET SDK 10.0.301, Rust nightly 1.98.0, Node 26.4.0, Python 3.14.6 with `uv`, Julia
1.12.4, and Docker 29.5. The installed opam switch is OCaml 5.0.0 with Dune 3.14.2. The current
OCaml manual is for the newer 5.5 release; an OCaml trial therefore begins by creating/pinning a
fresh switch rather than treating the installed switch as current. Opam switches are isolated and
dependencies must be reinstalled for a new switch ([OCaml compiler-switch documentation](https://ocaml.org/docs/install-a-specific-ocaml-compiler-version),
[OCaml 5.5 manual](https://ocaml.org/manual/5.5/index.html)).

**Fact — existing estate.** `joshibot` is mostly Python, already has a React 19/TypeScript/Vite UI
with Lightweight Charts, and has a small Node builder using `@meteora-ag/dlmm` and legacy
`@solana/web3.js`. Its Python dependencies already include PyArrow. This is migration context, not
an architectural endorsement.

**Judgment.** Ninety-six GiB means memory pressure is not a reason to accept unsafe queues or a
painful UI stack. Apple arm64 support is good in all three candidates. The decisive asymmetry is
protocol and data-library fit, not raw machine capacity. Pin **stable Rust** in a project
`rust-toolchain.toml`; Ember's installed nightly is convenient for experiments but is not a reason
to make nightly features production dependencies.

## Capability facts and workload judgments

### OCaml 5

**Facts.**

- OCaml has algebraic data types, exhaustive pattern matching, GADTs, and a strong module system;
  the 5.5 manual documents GADTs and multicore domains. Domains map one-to-one to OS threads, and
  the manual recommends higher-level libraries rather than raw domain primitives
  ([OCaml parallel-programming manual](https://ocaml.org/manual/5.5/parallelism.html)).
- Eio gives OCaml 5 effects-based direct-style I/O, structured cancellation, mocks, tracing,
  bounded streams, and worker/domain pools. A full Eio stream blocks writers when full. Fibers
  within one domain are scheduled deterministically, but real I/O and multiple domains introduce
  nondeterminism; Eio also notes that the type system does not prove values sent to another domain
  are thread-safe ([Eio project documentation](https://github.com/ocaml-multicore/eio)).
- OCaml's documented native interoperability surface is C. The programmer must obey runtime/GC
  representation rules; OCaml 5 multi-domain callbacks and C code add domain-registration and
  thread-safety obligations ([OCaml C interface](https://ocaml.org/manual/5.5/intfc.html)).
- The current opam catalog has maintained SQLite bindings (5.4.1 as surveyed) and current Ed25519
  support in `mirage-crypto-ec`; Zarith provides arbitrary-precision integers through GMP
  ([sqlite3-ocaml](https://opam.ocaml.org/packages/sqlite3/),
  [mirage-crypto-ec](https://opam.ocaml.org/packages/mirage-crypto-ec/),
  [Zarith](https://opam.ocaml.org/packages/zarith/)). The survey did not find an equivalently mature
  native OCaml Arrow/Parquet stack in opam. That absence is a time-bounded catalog observation,
  not proof that no binding can be written.
- Melange compiles OCaml to readable JavaScript with JavaScript interop and supports React-style
  development, but its React guide still labels itself a work in progress
  ([Melange for React developers](https://react-book.melange.re/intro/)).
- Pump's public repository points users to official TypeScript and Rust SDKs, not OCaml
  ([Pump public docs](https://github.com/pump-fun/pump-public-docs)).

**Judgments for JOSHI.**

- **Correctness ergonomics: excellent.** The episode/disposition/evidence vocabulary fits closed
  variants and pure functions unusually well. Illegal-state-resistant APIs would be compact and
  pleasurable. OCaml still cannot make provenance complete or a reducer deterministic by itself.
- **Concurrency/backpressure: good, not magical.** Eio's bounded streams and structured lifetimes
  are appropriate. Mixing Eio, older Lwt-only libraries, C bindings, and multiple domains is the
  risk surface. One-domain ingestion plus explicit CPU pools is the least surprising design.
- **Deterministic replay: excellent for a pure core, only moderate end-to-end.** Eio's deterministic
  single-domain tests are useful, but live I/O is still nondeterministic. The tape must impose
  order before reduction in every candidate.
- **Numerical/crypto fit: adequate but adapter-heavy.** Exact lamports/tokens fit signed `int64`
  only while range checks are explicit; Solana uses `u64`, so a wrapper must reject negative and
  overflowing values. Zarith covers wider intermediate math at the cost of a GMP/C dependency.
  Crypto primitives exist, but Solana address/message/transaction codecs and Pump instruction
  builders would be ours to validate and maintain.
- **Storage fit: SQLite yes; Arrow/Parquet no clean native path.** Calling a Rust/C library or
  exporting through a process boundary is plausible, but that converts an apparent single-language
  core into a mixed system at a crucial evidence boundary.
- **UI fit: possible, strategically wrong now.** Melange could bind React, yet JOSHI already has a
  TypeScript chart surface and will need direct access to fast-moving chart and wallet libraries.
  A rewrite would spend project attention on bindings rather than operator language.
- **Tooling/AI/edit loop: pleasant for a human expert, higher variance for agents.** Dune, opam,
  LSP, `utop`, and compiler errors are good. Fewer examples and bindings mean an agent is more likely
  to invent a current API or fall back to hand-written FFI. This is a judgment to measure, not a
  claim about model intelligence.
- **Packaging/maintenance: workable, with more local ownership.** Opam and Dune produce native
  executables on Apple arm64, but source-built C dependencies and compiler-specific switches make
  a clean-machine package test essential. The pure semantic core should age well; the Solana,
  browser, and columnar adapters are where narrow ecosystem coverage would create maintenance work.
- **Pride/pleasure: potentially highest.** OCaml matches Ember's formal-methods instincts and makes
  the semantic core feel like a language design problem. That is a real retention benefit. It is
  not enough to justify owning the Solana and columnar ecosystem gaps on day one.

### Modern C# / .NET 10, with F# as a serious variant

**Facts.**

- .NET 10 is an LTS release supported through 2028-11-14
  ([Microsoft lifecycle](https://learn.microsoft.com/en-ie/lifecycle/products/microsoft-net-and-net-core)).
  C# has records, pattern matching, nullable-reference analysis, `UInt128`, `BigInteger`, and
  checked arithmetic. Integral arithmetic is **unchecked by default** unless code or the project
  enables checking; `CheckForOverflowUnderflow` can change that project default
  ([checked/unchecked reference](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/statements/checked-and-unchecked),
  [`UInt128`](https://learn.microsoft.com/en-us/dotnet/api/system.uint128?view=net-10.0),
  [`BigInteger`](https://learn.microsoft.com/en-us/dotnet/api/system.numerics.biginteger?view=net-10.0)).
- `System.Threading.Channels` supplies bounded asynchronous producer/consumer queues. The default
  bounded full mode waits, while alternate modes deliberately drop newest, oldest, or the write
  ([Channels documentation](https://learn.microsoft.com/en-us/dotnet/core/extensions/channels)).
- `Microsoft.Data.Sqlite` is a Microsoft-maintained lightweight provider. Apache Arrow publishes a
  .NET implementation, while Parquet choices are separate projects: Parquet.Net is fully managed;
  ParquetSharp wraps Arrow C++ and explicitly warns that lifetime misuse can cause native access
  violations ([Microsoft.Data.Sqlite](https://learn.microsoft.com/en-us/dotnet/standard/data/sqlite/),
  [Apache Arrow](https://github.com/apache/arrow/),
  [Parquet.Net](https://github.com/aloneguid/parquet-dotnet),
  [ParquetSharp](https://github.com/G-Research/ParquetSharp)).
- .NET has first-class logs, metrics, `Activity` traces, EventPipe, `dotnet-trace`, and OpenTelemetry
  integration ([.NET observability](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/observability-with-otel),
  [`dotnet-trace`](https://learn.microsoft.com/en-us/dotnet/core/diagnostics/dotnet-trace)).
- Self-contained and single-file publishing support macOS arm64. Native AOT also supports macOS
  arm64, but forbids dynamic loading/runtime code generation and requires trimming compatibility
  ([single-file deployment](https://learn.microsoft.com/en-us/dotnet/core/deploying/single-file/overview),
  [Native AOT](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/)).
- .NET's native boundary is P/Invoke/source-generated `LibraryImport`; Microsoft's guidance stresses
  exact C signatures, blittable structs, `SafeHandle` lifetimes, and care with pinned memory
  ([.NET native-interop guidance](https://learn.microsoft.com/en-us/dotnet/standard/native-interop/best-practices)).
- Solnet is an active community .NET Solana SDK with RPC, streaming, wallet, transaction, and SPL
  support. It is not the Pump-published SDK. Pump's own current SDK list is TypeScript and Rust
  ([Solnet](https://github.com/bmresearch/Solnet),
  [Pump public docs](https://github.com/pump-fun/pump-public-docs)).
- F# runs on the same runtime and provides discriminated unions and compile-time units of measure,
  including on integral and decimal types
  ([F# discriminated unions](https://learn.microsoft.com/dotnet/fsharp/language-reference/discriminated-unions/),
  [F# units of measure](https://learn.microsoft.com/en-us/dotnet/fsharp/language-reference/units-of-measure)).
- Blazor can call any JavaScript library through JS interop. This makes Lightweight Charts usable,
  but does not make the interop boundary disappear
  ([Blazor JavaScript interop](https://learn.microsoft.com/en-us/aspnet/core/blazor/?view=aspnetcore-10.0)).

**Judgments for JOSHI.**

- **Correctness ergonomics: good in C#, excellent in F#.** C# records and patterns can model the
  envelope, but open class hierarchies, nulls, mutation, exceptions, and unchecked-by-default
  arithmetic demand project-wide rules. F# discriminated unions and measures improve the core
  without leaving .NET; C# can host the service/interop shell.
- **Concurrency/backpressure: excellent.** Channels, async streams, cancellation tokens, and mature
  HTTP/WebSocket servers are a direct fit. Dropping modes must be banned for evidence queues unless
  a drop record is durably emitted.
- **Deterministic replay: very good if the reducer is isolated.** The GC, Tasks, and Channels do not
  hurt replay if concurrency ends at the ordered-event boundary. Avoid unordered dictionary
  iteration, ambient time, and culture-sensitive conversion in digest-producing code.
- **Numerical/crypto fit: strong primitives, medium protocol fit.** `ulong`/`UInt128` map Solana
  quantities naturally, and the build can enable overflow checking. Wire compatibility, Ed25519
  semantics, account ordering, and Pump fee math still need golden tests against official SDKs.
- **Storage/observability/packaging: strongest integrated experience.** SQLite and diagnostics are
  excellent. Arrow is credible. Parquet requires choosing a separate implementation and testing
  schema interoperability. Start JIT/self-contained; Native AOT is optional optimization, not an
  architectural goal that should force reflection-hostile design.
- **FFI/maintenance: capable, but native lifetime bugs remain native bugs.** `LibraryImport` is a
  good escape hatch for Arrow/crypto codecs, not a reason to make the core a web of native handles.
  .NET's LTS dates make upgrade expectations explicit; isolate protocol and Parquet packages so a
  runtime or native-binary update does not ripple through episode semantics.
- **UI fit: React/TypeScript still wins.** Blazor adds JS interop exactly where JOSHI needs custom
  chart primitives, pointer gestures, and fast iteration. Avalonia is credible for native desktop
  tools, not for replacing a working web chart ecosystem.
- **AI/edit loop: strongest candidate.** The SDK is installed, compiler diagnostics are legible,
  `dotnet watch` is fast, and the ecosystem is broad. F# has less training/example coverage than
  C#, so the mixed C#/F# variant needs its own agent bakeoff.
- **Pride/pleasure: likely good, not automatic.** F# can be elegant. A C# service can also become a
  sea of mutable DTOs and dependency-injection ceremony unless the semantic core has strict style
  rules.

### Rust

**Facts.**

- Rust's ownership/type system provides memory-safety and concurrency checks without a garbage
  collector; Rust 2024 is the current documented edition
  ([The Rust Programming Language](https://doc.rust-lang.org/book/)). Rust has native `u64`/`u128`
  and explicit `checked_*`, `strict_*`, saturating, and wrapping arithmetic. Cargo release builds
  disable overflow checks by default unless configured
  ([`u128` methods](https://doc.rust-lang.org/std/primitive.u128.html),
  [Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)).
- Tokio's bounded MPSC channel waits when capacity is exhausted and documents this as backpressure;
  it also documents clean shutdown and sync/async bridges
  ([Tokio MPSC](https://docs.rs/tokio/latest/tokio/sync/mpsc/index.html)).
- Anza publishes the Rust SDK used by Solana/Agave, and Pump publishes a Rust client alongside its
  TypeScript SDK. Pump's current buy documentation gives both TypeScript and Rust instruction
  examples with exact `u64` quantities
  ([Anza Solana SDK](https://github.com/anza-xyz/solana-sdk),
  [Pump buy documentation](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/BUY.md)).
- Apache's Rust implementation includes native Arrow and Parquet, synchronous and asynchronous
  readers/writers, and direct `RecordBatch` conversion. `rusqlite` can bundle and statically link a
  current SQLite, avoiding dependence on the system SQLite
  ([Apache Parquet Rust](https://arrow.apache.org/rust/parquet/index.html),
  [`rusqlite`](https://docs.rs/crate/rusqlite/latest)).
- Tokio's `tracing` records structured spans/events and can feed OpenTelemetry and Tokio Console
  ([Tokio tracing](https://tokio.rs/tokio/topics/tracing)). Cargo has incremental development builds;
  release optimization/LTO trade compile time for runtime performance
  ([Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html)).
- Rust has a C ABI/FFI, but the boundary inherits C's weaker types
  ([Rustonomicon FFI](https://doc.rust-lang.org/nomicon/ffi.html)). Tauri combines a Rust host with
  any HTML/JS/CSS frontend and builds a macOS application bundle on a Mac
  ([Tauri overview](https://v2.tauri.app/start/),
  [Tauri macOS bundles](https://v2.tauri.app/distribute/macos-application-bundle/)).

**Judgments for JOSHI.**

- **Correctness ergonomics: very good, with friction in the right and wrong places.** Enums,
  newtypes, exhaustive matches, `Result`, ownership, and explicit integer operations fit evidence
  and authority boundaries. Lifetimes help with buffer/resource ownership but add little to a pure
  episode reducer; do not contort the semantic model into borrowed graphs for speed.
- **Concurrency/backpressure: excellent.** Tokio is a proven fit, but `tokio::spawn` everywhere
  would obscure causality. Use a small supervised task graph, bounded channels, explicit queue
  telemetry, and an ordered single-writer/reducer stage. `Send + Sync` catches classes of mistakes
  Eio explicitly cannot prove across domains.
- **Deterministic replay: very good.** Serde-friendly enums, pure reducers, checked integers, and
  BLAKE3 hashes are convenient. Tokio scheduling remains nondeterministic and must not decide
  canonical ordering.
- **Numerical/crypto/protocol fit: best.** Native unsigned widths match Solana, official SDK types
  avoid reimplementing transaction codecs, and Pump's Rust crate reduces differential surface.
  Exact monetary wrappers must still encode mint/unit/orientation and enable overflow checks in
  release; primitive `u64` alone is not a money type.
- **Storage fit: best.** Native Arrow/Parquet plus bundled SQLite gives one implementation path for
  the evidence plane and research exports. Keep the canonical raw record independent of Arrow crate
  structs so library upgrades cannot redefine evidence.
- **UI fit: excellent only as a split.** Keep React/TypeScript. Lightweight Charts exposes typed
  custom series and Canvas primitives for annotations/drawing tools
  ([Lightweight Charts plugins](https://tradingview.github.io/lightweight-charts/docs/5.1/plugins/intro)).
  A Rust/WASM UI would still bind this JavaScript surface. Tauri may package the local app later;
  begin with localhost browser delivery because it is easier to inspect and automate.
- **Observability/debugging: good but less turnkey than .NET.** `tracing` is strong; async task
  inspection and macOS CPU profiling need deliberate setup. Keep spans keyed by observation,
  replay, episode, and source request rather than emitting free-text logs.
- **Packaging/maintenance: strong if versions stop at adapters.** Native Apple-arm64 binaries and
  optional Tauri bundles are straightforward. Rust itself releases frequently and Solana crates
  evolve quickly, so pin a stable toolchain/lockfile and prevent SDK types from spreading. Rust's
  source compatibility is helpful; dependency/API churn is still work.
- **AI/edit loop: good with a real tax.** `cargo check`, rust-analyzer, clippy, compiler-guided
  changes, and pervasive public examples help agents. Compile time and borrow-checker repair can
  invite noisy refactors. Small crates, owned boundary DTOs, few macro frameworks, and stable Rust
  improve both human and agent edits.
- **Pride/pleasure: high if the architecture stays simple.** A typed append/replay engine with
  explicit capabilities suits Rust. A giant generic trait cathedral would be technically proud and
  product-hostile.

## Cross-cutting comparison

Ratings below are judgments for this project, not benchmark results. `5` means best fit among these
options, not perfection.

| Concern | OCaml 5 | C#/.NET 10 | F# on .NET | Rust |
|---|---:|---:|---:|---:|
| Evidence/episode type modeling | 5.0 | 4.0 | 4.8 | 4.5 |
| Bounded async flow | 4.0 | 4.5 | 4.2 | 4.5 |
| Pure deterministic reducer | 4.8 | 4.2 | 4.6 | 4.5 |
| Exact Solana numeric/wire fit | 2.5 | 4.0 | 4.1 | 5.0 |
| Official Solana/Pump interop | 1.5 | 3.0 | 2.8 | 5.0 |
| Arrow/Parquet/SQLite | 2.0 | 4.0 | 4.0 | 5.0 |
| Existing React/TS integration | 5.0 | 5.0 | 5.0 | 5.0 |
| Native all-language UI | 2.5 | 3.5 | 3.5 | 2.5 |
| Observability/profiling | 3.5 | 5.0 | 4.5 | 4.0 |
| Apple-arm64 packaging | 3.5 | 4.0 | 4.0 | 4.5 |
| Agent/edit-loop predictability | 3.0 | 5.0 | 4.0 | 3.5 |
| Likely engineering delight for Ember | 5.0 | 3.5 | 4.5 | 4.0 |

Two cautions matter more than a tenth of a point:

- C# and Rust both default to unchecked/wrapping-compatible release behavior in important cases.
  JOSHI must require checked monetary operations in code and build configuration and test release
  artifacts, not only debug builds.
- OCaml's semantic score does not compensate automatically for hand-maintaining protocol codecs.
  Conversely, Rust's official SDK advantage does not certify an SDK-produced transaction as safe;
  independent decode/effect validation remains mandatory in any future execution lane.

## Candidate architectures

### A. Rust core + React/TypeScript glass — recommended

```text
provider/RPC adapters -> raw append + gap journal -> ordered replay/reducer -> query/stream API
       Rust                    Rust                    Rust               Rust
                                                                          |
                                                                          v
                                                            React/TypeScript/Vite

Parquet/Arrow/SQLite snapshots -> Python / Julia notebooks and model experiments (offline plane)
```

Use ordinary process/API boundaries between the UI and runtime. Inside Rust, use modules/crates
first, not microservices. A later signer/submission component is a separate local process because
it is a different authority, not because distributed systems are fashionable.

**Why it fits:** it places official protocol and native columnar tooling beside the raw evidence,
keeps the proven web UI, and leaves one strongly typed implementation of ordering, replay, and
monetary invariants. Python/Julia remain first-class research environments without becoming the
source of live truth.

**Boundary rule:** define a language-neutral, versioned schema for observation/assertion/query
DTOs. JSON with exact quantities encoded as decimal strings is sufficient for the first vertical
slice. Introduce Protobuf or Arrow IPC only after measured volume warrants it. Do not expose Rust
enum serialization as the permanent public contract.

### B. C#/.NET core + React/TypeScript glass — runner-up

This architecture substitutes an ASP.NET Core service for Rust. Enable nullable analysis, warnings
as errors, invariant culture, checked overflow project-wide, immutable domain records, bounded
Channels in wait mode, and a pure reducer assembly. Use JIT/self-contained packaging initially.

**Why it could win:** fastest edit/diagnostic loop, strongest built-in observability, excellent
local service ergonomics, and enough data tooling. It is especially credible for the read-only
phase.

**Why it currently loses:** Pump does not publish a .NET SDK. The choices are a community Solana
stack plus generated/hand-maintained Pump code, a TypeScript/Rust protocol sidecar, or treating an
official CLI as an external oracle. Each gives back some of .NET's simplicity at the boundary that
will eventually carry money.

### C. C# shell + F# semantic library + React/TypeScript — genuinely plausible mixed option

Keep networking, storage adapters, hosting, and observability in C#. Put only evidence types,
episode algebra, quote/accounting arithmetic, and reducers in a small F# library referenced in the
same .NET process. This adds a language but not an FFI or deployment unit.

**Admission condition:** the bakeoff must show materially clearer models or caught bugs versus
idiomatic C# records. If F# DTO conversion dominates the diff, use C# alone. This option is more
plausible than OCaml for an initial formal core because it retains the .NET ecosystem and packaging.

### D. OCaml core + React/TypeScript, with protocol/data sidecars

OCaml owns the reducer and perhaps the query service; official Rust or TypeScript components own
Solana/Pump adaptation; Rust/Python owns Parquet. Use a versioned process protocol, never an
in-process OCaml/Rust FFI, for fault isolation and debuggability.

**Why it is tempting:** best semantic modeling and a delightful pure replay kernel.

**Why it is not the starting recommendation:** three live languages, duplicated DTOs, fragmented
traces, coordinated releases, and two evidence crossings before a row reaches research. It spends
complexity before the ontology is stable enough to know which boundary deserves formalization.

### E. Single-language UI variants — rejected for the first slice

- **C# + Blazor:** viable, but custom chart gestures still cross JS interop.
- **OCaml + Melange/React:** viable, but adds bindings for the existing chart/UI estate.
- **Rust + WASM UI:** viable, but Lightweight Charts remains JavaScript and browser wallet/chart
  integrations stay web-native.
- **Rust + Tauri + React:** this is useful packaging, not a single-language architecture. It is an
  optional later wrapper around candidate A.

“One language” is not a valuable goal if it relocates the hardest work into bindings.

## Concrete failure and lock-in risks

| Choice | Failure/lock-in mode | Countermeasure or exit |
|---|---|---|
| Rust core | Solana crate-version churn or Pump SDK types leak through every domain object | one narrow protocol-adapter crate; internal canonical IDs/amounts/events; golden fixtures against official SDK |
| Rust core | Tokio/task topology becomes the semantic architecture | pure reducer accepts an iterator of ordered owned events; async ends before reduction |
| Rust core | long compile/macro stack slows exploratory ontology changes | small workspace, minimal proc-macro frameworks, `cargo check`, stable toolchain, owned DTOs |
| .NET core | Solnet/community Pump support drifts from on-chain programs | differential decode/quote tests; retain raw bytes; isolate adapter; never trust builder summary |
| .NET core | unchecked arithmetic, mutable DTOs, or null collapse evidence semantics | project-wide overflow checking and nullable warnings; money/source-status newtypes; property tests in Release |
| .NET core | Native AOT becomes a design constraint and breaks reflection-heavy libraries | use self-contained JIT first; AOT only after a clean publish bakeoff |
| OCaml core | no maintained Arrow/Parquet or official Pump path | process boundary with a canonical schema; do not write bespoke codecs until bakeoff justifies them |
| OCaml core | opam switch/C dependency or multi-domain C binding breakage on macOS | lockfile/switch export; one-domain core; package on a clean user account; avoid in-process native data FFI |
| Any split | schema drift, partial deploy, duplicate identifiers, broken distributed traces | compatibility tests, schema hash in every envelope, monotonic versions, replay fixtures across versions |
| React/TS UI | chart/provider object shapes become the domain schema | UI DTO facade; operator gestures are append-only domain events, not component state dumps |
| Tauri later | macOS webview/path/signing behavior becomes an unexpected runtime dependency | keep browser mode supported; packaging is downstream of the local API |
| Python/Julia research | notebook interpretation mutates canonical evidence or leaks into “as-known” replay | read-only exports; derivations name inputs/code/model and return as new annotations only |

The most dangerous lock-in is not a vendor. It is allowing a runtime library's event or DTO type to
become the evidence contract. Raw bytes, stable natural keys, explicit units/clocks, and a
language-neutral schema are the exit strategy for every option.

## Weighted decision matrix

Scores are 1–5 judgments derived from the preceding analysis. Weights reflect the first durable
vertical slice, including its eventual need to touch official transaction representations. The
matrix is an audit aid, not empirical precision.

| Criterion | Weight | Rust + TS | C# + TS | F#/.NET + TS | OCaml + TS | Rust edge + OCaml core + TS |
|---|---:|---:|---:|---:|---:|---:|
| Semantic correctness ergonomics | 16 | 4.5 | 4.0 | 4.8 | 5.0 | 4.8 |
| Official Solana/Pump interop | 17 | 5.0 | 3.0 | 2.8 | 1.5 | 4.8 |
| Concurrency/backpressure | 11 | 4.5 | 4.5 | 4.2 | 4.0 | 4.3 |
| Replay/recovery fit | 13 | 4.5 | 4.2 | 4.5 | 4.7 | 4.8 |
| Arrow/Parquet/SQLite | 10 | 5.0 | 4.0 | 4.0 | 2.0 | 4.0 |
| Existing UI/product delivery | 8 | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 |
| Observability/debugging | 6 | 4.0 | 5.0 | 4.5 | 3.5 | 3.5 |
| macOS packaging | 5 | 4.5 | 4.0 | 4.0 | 3.5 | 3.0 |
| AI/edit loop | 6 | 3.5 | 5.0 | 4.0 | 3.0 | 2.5 |
| Long-term maintenance | 5 | 4.0 | 4.5 | 3.8 | 3.3 | 2.5 |
| Engineering pleasure/pride | 3 | 4.0 | 3.5 | 4.5 | 5.0 | 4.7 |
| **Weighted result / 5** | **100** | **4.54** | **4.12** | **4.13** | **3.59** | **4.26** |

### Sensitivity tests

Reweighting prevents the base choice from merely restating its assumptions:

| Scenario | Rust + TS | C# + TS | F#/.NET + TS | OCaml + TS | Rust + OCaml + TS | Outcome |
|---|---:|---:|---:|---:|---:|---|
| Base slice | 4.54 | 4.12 | 4.13 | 3.59 | 4.26 | Rust + TS leads |
| Formal-core heavy: correctness 25, replay 20, joy 10, maintenance 10 | 4.45 | 4.11 | 4.32 | 4.11 | 4.33 | Rust still leads narrowly; mixed/F# become credible |
| Delivery/ecosystem heavy: protocol 20, UI 12, data 12, AI loop 12 | 4.54 | 4.17 | 4.00 | 3.27 | 4.02 | Rust leads; C# is runner-up |
| “Love the formal core”: correctness 25, replay 20, joy 20, maintenance 10 | 4.38 | 4.04 | 4.37 | 4.28 | 4.36 | statistical tie among Rust, F#, and split core |

For reproducibility, the scenario weight vectors in table-column order are: formal-core
`[25,8,8,20,5,5,3,3,3,10,10]`; delivery/ecosystem
`[8,20,10,5,12,12,4,8,12,8,1]`; and love-the-formal-core
`[25,5,5,20,5,3,2,2,3,10,20]`. Each sums to 100.

The last row is useful: if day-to-day delight deserves one fifth of the decision, the spreadsheet
cannot select a language. The bakeoff and Ember's felt experience should. OCaml only wins outright
if its semantic/pleasure benefit is valued very highly **and** the real cost of the protocol/data
boundaries proves lower than estimated.

## Common bakeoff specification

The bakeoff is intentionally small enough for one focused implementation per candidate and strict
enough to expose the actual JOSHI risks. Implement **Rust**, **C# or C#/F#**, and **OCaml** versions
against the same repository-owned fixtures. The UI is a shared TypeScript client and is not scored
as three rewrites.

### Fixed input

One generated fixture pack with a published manifest and expected digests:

- 1,000,000 framed observations from two producers;
- Pump create/trade/migrate-like payloads generated from a pinned public IDL plus opaque unknown
  variants;
- duplicates, byte-identical distinct events, out-of-order arrivals, slot/finality corrections,
  reconnect overlap, cursor gaps, missing source clocks, corrupt frames, and schema-version drift;
- operator events covering inspect, arm, buy fill, partial exit, retained runner, full exit, flat
  watching, re-entry, annotation, and zap;
- exact lamport/token values including `0`, `u64::MAX`, fee rounding boundaries, multiplication
  requiring a wider intermediate, and deliberate overflow;
- deterministic virtual clock, randomness seed, and crash points.

No candidate may normalize input in a language-specific preprocessor.

### Required program

1. Read both producers concurrently into a bounded capacity-4096 queue. A slow sink is injected for
   50 ms every 10,000 records. Block producers; never silently drop. Emit queue-depth and stall
   telemetry.
2. Append the exact frame and acquisition metadata before decode. Quarantine corrupt/unknown input
   without advancing a cursor past an uncommitted append.
3. Canonically order and deduplicate by explicit source/chain keys while preserving equal-but-
   distinct events.
4. Run a pure reducer producing observations, assertions, inventory intervals, and complete
   episodes, including flat-watch/re-entry intervals.
5. Use checked exact integer arithmetic and explicit base/quote units. Every overflow fixture must
   become the same typed refusal, never wrap or coerce to float.
6. Write a SQLite checkpoint and a Parquet result with the same declared schema. Kill after each
   supplied crash point, resume, and reach the same canonical BLAKE3 digest as a genesis replay.
7. Serve one snapshot query and one live event stream to the shared React client. Every response
   includes projection version and high-water marks.
8. Emit structured traces linking source request, raw append, decode, replay batch, and episode.
9. Package and run from a clean macOS arm64 user account with one documented command and no global
   dependencies beyond the chosen runtime package. Record binary/app size and startup behavior;
   do not optimize for either yet.

### Measurements

Correctness is pass/fail. For passing implementations record, without tuning heroics:

- cold setup time, first clean build, no-op build, one-file rebuild, and test duration;
- sustained/burst throughput, p50/p99 append-to-projection latency, maximum RSS, and queue depth;
- crash recovery duration and exact digest equality across 100 randomized schedules;
- lines and concepts in the domain core versus adapters; unsafe/FFI/reflection/macro use;
- compiler errors and files touched for two changes: add `Watching_flat` evidence and add a new
  Pump instruction variant while retaining unknown variants;
- one fresh AI-agent attempt per language using the same prompt/context: compile/test iterations,
  hallucinated APIs, unnecessary diff size, and human review defects;
- Ember's 1–5 ratings after two hours of debugging each: legibility, confidence, flow, and desire to
  continue.

Performance is comparative, not a race. A candidate fails on performance only if it cannot sustain
25,000 input frames/s on Ember's machine with bounded memory and zero unexplained loss, or if UI
projection latency exceeds 250 ms p99 under that synthetic burst. These are bakeoff stress gates,
not claims about expected market traffic.

### How the recommendation can be falsified

- **Choose C#/.NET** if it passes all invariants, achieves at least 75% of Rust's throughput with no
  material latency problem, takes at most 70% of the implementation/review time, and its Pump
  adapter survives golden differential tests without a permanent Rust/Node sidecar.
- **Choose C#/F#** if the F# domain library catches at least two fixture/change defects at compile
  time that idiomatic C# does not, while conversion code remains under 10% of the slice and the
  agent/edit loop is not materially worse.
- **Choose Rust + OCaml** if the OCaml reducer is substantially smaller and clearer, catches at
  least two semantic bugs missed by the Rust reducer, wins Ember's confidence/flow rating by at
  least one full point, and the versioned process boundary adds less than 15% implementation and
  operational effort. Do not use in-process FFI to make this threshold look cheaper.
- **Choose OCaml-dominant** only if it also demonstrates a maintained, interoperable
  Arrow/Parquet path and protocol-adapter plan that does not make JOSHI the maintainer of a shadow
  Solana/Pump SDK.
- **Keep Rust + TypeScript** if no challenger clears its condition. Revisit after the evidence
  ontology stabilizes or a formal reference reducer becomes valuable.

## Operating rules if Rust + TypeScript is selected

1. Stable Rust only in the durable runtime; pin compiler and dependency lockfile.
2. `#![forbid(unsafe_code)]` in semantic/evidence crates. Confine unavoidable FFI to reviewed
   adapter crates.
3. Release overflow checks on, plus checked monetary newtypes and property tests.
4. No unbounded channel in an evidence path. Any intentional sampling/drop is a typed durable
   observation with a reason and covered interval.
5. Canonical reduction is single-ordered-stream logic. Parallelize fetch/decode/export, not the
   meaning of event order.
6. Raw payload schema and IDs are project-owned and versioned; SDK structs stop at adapters.
7. React/TypeScript owns product glass and gestures, not accounting or transaction truth.
8. Python/Julia may produce versioned annotations but cannot mutate raw evidence or live state.
9. Keep browser-local delivery first. Add Tauri only when desktop packaging solves a measured
   problem.
10. Execution remains absent until its own authority gates are passed. Language choice is not a
    security review.

## Bottom line

Rust is recommended because it is the only candidate that is simultaneously near the top for
semantic correctness, bounded streaming, official Solana/Pump interoperation, exact unsigned
arithmetic, native Arrow/Parquet, and Apple-arm64 packaging while preserving the existing web UI.
C#/.NET is close enough that a bakeoff could legitimately overturn the choice, especially if speed
of iteration dominates and the protocol gap proves cheap. F# is the most credible way to obtain a
more algebraic core without a new runtime boundary. OCaml is not foolish; it is probably the most
beautiful language here for the reducer. The foolish move would be paying its ecosystem and
three-language boundary costs before demonstrating that the beauty prevents the particular errors
JOSHI is likely to make.
