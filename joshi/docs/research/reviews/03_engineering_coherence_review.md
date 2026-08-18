# Engineering coherence review: one local core, one financial meaning, conditional edges

Status: cross-lane engineering reconciliation; pre-implementation; no execution, purchase, or
live-capital authorization.

Reviewed in full: `PROJECT.md`, `FOUNDATION.md`, `PRE_ENGINEERING_PROGRAM.md`, engineering lanes
13–24, and reviews 01–02.

## Executive decision

The coherent default is:

- a **greenfield local modular monolith** whose primary core runtime is **stable Rust**;
- a **React/TypeScript browser renderer** on one authenticated loopback origin;
- one logical evidence/command writer;
- **SQLite WAL** as the initial transactional catalog and operational store, with a
  content-addressed blob directory, immutable manifested Parquet exports, and ephemeral DuckDB
  analysis;
- Rust-owned protocol decoding, exact calculation, financial projection, replay, and local API;
- one narrowly scoped TypeScript source runner only when a current official SDK is demonstrably
  more faithful than Rust—Meteora DLMM is the likely exception—and only after differential
  conformance proves the exact missing boundary;
- Python as the separate, read-only research and snapshot environment;
- OCaml/Zarith as an optional test oracle for exact numerical and reducer conformance, never an
  initial production process;
- no C#, F#, Julia, Lean, desktop wrapper, broker, server database, managed stream, or general model
  service in the first production slice.

This selects the Rust recommendation in lane 13 over the Python-core recommendation in lane 14.
The reason is not that Rust is intrinsically more serious. After lanes 17 and 20 are included, a
Python core does not remain the small single-runtime architecture lane 14 describes. It becomes a
Python coordinator beside a Rust protocol/numeric authority, a TypeScript UI, and probably a Node
SDK runner. That creates more schemas, more traces, more release coupling, and more places to
recompute money than putting the read-only core around the already-required Rust boundary.

This is a **recommended implementation hypothesis**, not an accepted foundation fact. It must
survive one bounded Rust-versus-Python walking-fixture bakeoff. If it loses, the fallback is a
coherent Python-core topology described below—not a permanent Python/Rust/C#/OCaml federation.

The product posture is also explicit: **companion-capable exact-mint cockpit is the planning
default, not Pump replacement**. Lane 21 has not established a lawful, supported, stable source for
Pump ranking, personalization, threads, notifications, and other Pump-only texture. Spike 0 may
promote one named surface to replacement-capable, keep Pump as the renderer under a reviewed
companion method, select an independent on-chain observatory, or stop. The architecture survives
all four results; its product claims do not.

The current graph remains system-read-only. It contains no transaction builder, simulation path
that constructs bytes, key, signer, broadcast client, Jito endpoint, transaction API, live policy,
or placeholder package for any of those things.

Where a protocol package bundles read helpers and builder exports inseparably, its presence is not
allowed to create an application command or network effect. Prefer decode/read-only feature sets;
otherwise confine the package to a capability-poor adapter or conformance harness, expose only
fixed read/quote requests, remove wallet and send dependencies, and prove the production graph has
no credential or broadcast path. “We never call the builder” is weaker than the desired structural
boundary and must remain a named dependency defect until the package can be narrowed.

## What has authority, what is recommended, and what is still open

The engineering lanes use words such as “decision,” “recommended,” and “default” inside research
documents. Those words do not all have the same project authority.

### Already decided by the accepted foundation

- Joshi is a clean semantic boundary, not a wholesale `joshibot` rewrite.
- The current system is system-read-only through R4 even when Ember acts manually in an external
  live tool.
- Observation, assertion, derivation, financial ledger, scene, and future authority journal are
  different objects.
- Operator episode, inventory epoch, lot, and optional management tranche are different objects.
- Witnessed, knowledge-cutoff, and retrospective replay are different products.
- Exact integers, asset identity, clocks, availability, gaps, coverage, and provenance are
  load-bearing.
- The ledger closes independently of episode stories; actual and counterfactual ledgers never
  mix.
- The first useful corridor is one natural operator loop, not a universal platform.
- Any later construction, signing, submission, or live authority requires a new review.

Engineering may choose representations for those meanings. It may not silently reopen them.

### Coherent recommendations from Wave 2

- Monorepo, local-first, modular-monolith source architecture.
- Browser renderer with TypeScript/React and no durable truth in the GUI.
- One authoritative operational writer.
- SQLite + content-addressed blobs for the first local truth boundary.
- Manifested Parquet for immutable analytical exports; DuckDB as a disposable reader/auditor.
- Compact census plus leased hot scopes, not continuous high fidelity everywhere.
- Bounded queues, explicit degradation, deterministic replay, and no network in ordinary tests.
- Python-first offline research over frozen snapshots.
- Exact protocol/numeric conformance against pinned official artifacts and finalized chain effects.
- Property/state-machine/fuzz/crash testing before broad formalization.
- $0 incremental pre-September infrastructure posture.

These should become accepted ADRs only after the applicable gate passes.

### Must be decided by a bounded experiment

| Question | Decision instrument | Possible outcomes |
| --- | --- | --- |
| Pump product mode | Spike 0 access and 100-entry fidelity work | one-surface replacement, reviewed companion, on-chain observatory, stop/rethink |
| Primary core runtime | one Rust/Python walking fixture | Rust default or coherent Python fallback |
| Protocol boundary | Rust/TypeScript differential conformance | Rust native, Rust + narrow TS Meteora runner, or unsupported function |
| SQLite acceptance | runtime-version, crash, replay, and measured load gates | SQLite or replace it with PostgreSQL; never dual canonical stores |
| Browser shell sufficiency | one renderer workload in browser; wrapper only on a named failure | browser, later Tauri, or Electron for a proved Chromium requirement |
| Companion capture method | terms/privacy review plus lowest-privilege trial | explicit mint/share, deliberate app-window capture, narrowly reviewed extension, or none |
| First scene contract | natural-session evidence | exact minimal rendered/view/gesture fields and retention classes |
| First portfolio domain | wallet reconciliation | one wallet or the smallest widened controlled domain that actually closes |

### Still deliberately deferred

- exact crackle types, dispositions, model family, program-synthesis language, and ecological score;
- full-market high-resolution retention and broad social acquisition;
- server deployment, PostgreSQL, broker, ClickHouse, lakehouse, vector store, or ML platform;
- Tauri/Electron/mobile packaging unless the browser fails a named product requirement;
- persistent OCaml, C#, F#, Julia, or Lean production components;
- LP control, automated wallet copying, model-visible live ranking, and all execution authority.

## The contradictions and their resolutions

### 1. Rust core versus Python core

Lane 13 recommends Rust because Solana/Pump protocol support, checked integer widths,
Arrow/Parquet, bounded streaming, and future authority fit are strongest there. Lane 14 recommends
Python because a small local API, nearby compost donors, SQLite/data tooling, and research
interoperation could reach product use fastest. Lane 24 repeats the runway argument and warns that
Rust on the critical path needs to earn itself.

Those arguments were made at different graph boundaries. Lane 14's Python topology is simple only
while protocol and financial arithmetic remain inside Python or a small Node adapter. Lane 17 then
recommends native Rust for raw Solana/Pump interpretation, while lane 20 recommends one Rust
numeric/accounting authority. Taking all three recommendations literally yields:

```text
TypeScript browser
  -> Python application/replay/writer
       -> Rust protocol plane
       -> Rust numeric/accounting plane
       -> Node/TypeScript Meteora SDK runner
  -> Python research environment
  -> OCaml numerical oracle
```

That is not the low-ceremony Python architecture. It is a four-language operational graph plus a
test oracle, with Python coordinating the two places that own the hardest truth.

The resolution is to choose **Rust for the complete operational core**, not merely a calculator
sidecar. It owns ingest normalization, canonical ordered reduction, ledger/numerical projection,
SQLite commits, replay, hot-scope control, and the loopback API. TypeScript remains the product
renderer and, only when conformance demands it, a protocol-reference runner. Python remains a
consumer of immutable exports.

This has an important discipline: Rust is not permission for a large framework rewrite. The core
is one process and a few ordinary modules. Spike 0 source probes may remain disposable Python or
TypeScript programs. They become production only by emitting a fixture/contract that the accepted
core implements.

### 2. C#, F#, and OCaml are alternatives, not additive improvements

Lane 13 correctly treats modern C# as a credible whole-core runner-up and F# as a possible pure
library inside a .NET core. Lane 19 treats all of OCaml, C#/F#, and Rust as testable state-machine
hosts. Lane 20 gives OCaml a different and narrower role: an independent Zarith oracle.

The incoherent interpretation would add C# for service ergonomics, F# for algebraic types, OCaml
for formal flavor, Rust for protocol/numerics, TypeScript for UI, and Python for research. Each
individual choice is defensible; their union is not.

Resolution:

- **C# has no initial role.** It enters only if the whole-core bakeoff is deliberately reopened and
  .NET replaces Rust or Python rather than sitting beside them.
- **F# has no initial role.** It is available only inside a selected .NET topology; it is not a
  free-standing semantic service.
- **OCaml is test-only.** A small independent reducer/numeric oracle may consume canonical vectors
  and emit results. It has no source adapters, storage ownership, server, or UI contract.
- **Lean is absent.** No stable theorem currently earns an isomorphic production ontology.

The OCaml oracle is valuable precisely because it does not share Rust implementation structure.
It becomes harmful if every semantic change requires coordinated production releases in both.

### 3. Modular monolith versus sidecars

Lane 14 calls the source architecture a modular monolith while recommending a modest multi-process
deployment. Lane 17 recommends a TypeScript sidecar for Meteora if Rust parity fails. Lane 16 may
add a browser extension. These are compatible only if “monolith” describes semantic ownership,
not Unix process count.

Use these terms:

- **modular core:** one application and one semantic dependency graph;
- **source runner:** a replaceable adapter process for a distinct SDK, credential, crash, or
  runtime boundary;
- **companion adapter:** an optional browser-side observation client;
- **research worker:** an offline consumer of a frozen snapshot;
- **service:** a separately operated/networked authority with its own availability and release
  contract. There are no initial services.

A source runner has no database credentials, no portfolio query, no semantic projection, no key,
and no transaction endpoint. It emits observation drafts or manifest-bound quote assertions. The
core validates and commits them. Moving an adapter in or out of process cannot change what an
observation means.

Thus the recommended deployment may contain browser + core + one SDK runner without becoming a
microservice architecture. A process earns existence through a concrete dependency or failure
boundary, not because a research lane has a noun.

### 4. SQLite, Parquet, and DuckDB are complementary only under one-way authority

Lane 15's four-part storage choice is coherent and should be adopted as the default:

```text
bounded adapters -> one committer -> SQLite WAL + content-addressed blobs
                                      |
                                      v
                        immutable manifested Parquet
                                      |
                                      v
                             ephemeral DuckDB query
```

The apparent risk is three “databases.” They are not three authorities:

- SQLite is the operational catalog, evidence metadata, cursor/coverage transaction boundary,
  operator/scene store, and recent projection store.
- The blob directory holds exact large bytes whose references are committed in SQLite.
- Parquet is an immutable export or later cold physical tier whose file manifest is authoritative
  in SQLite.
- DuckDB is a query engine over named manifests. No persistent `.duckdb` file is canonical.

Research cannot write back through DuckDB or Parquet into evidence. A promoted derivation returns
through an explicit import/append contract. The application never starts querying a research
snapshot as its current truth merely because that query is fast.

SQLite acceptance is conditional: the runtime must enforce a fixed version that includes the WAL
race fix identified in lane 15, WAL/FULL/foreign-key/strict settings must be verified, and the
crash/load/restore gates must pass. If it fails, replace the operational boundary with PostgreSQL.
Do not run SQLite and PostgreSQL as indefinite dual writers.

### 5. Companion and replacement are different product claims, not UI variants

Lane 16 gives the WebExtension companion a prominent role because a normal browser application
cannot inspect another origin. Lane 21 then establishes that continuous DOM/network observation
may be technically brittle and contractually or privacy-sensitive; it recommends trying lower-
privilege methods first. Lane 24 makes the companion-capable core the runway default.

Resolution:

1. The first renderer is an ordinary local browser app and exact-mint workbench.
2. Pump remains the renderer for Pump-only fields until Spike 0 proves otherwise.
3. A pasted/shared mint or deliberate app-window scene is tested before a DOM-aware extension.
4. An extension is added only for one named field that lower-privilege capture cannot preserve,
   after access review, with Pump-only origin permission and no cookies, storage, headers, wallet
   UI, request replay, synthetic navigation, or broad history.
5. Replacement applies only to the exact sampled surface that passes the membership/order/reaction
   gate. It never becomes “complete Pump alternative” by implication.

The same cockpit can run in any mode, but every scene records the source mode and the denominator it
actually possesses. A companion screenshot is not a served set. An independently ranked Joshi
board is not the Pump board. An extension observation is not canonical market state.

### 6. Protocol truth, numerical truth, and financial truth are three contracts

Several lanes call different artifacts “canonical.” They can coexist if the word is qualified.

| Contract | Authority | It cannot establish |
| --- | --- | --- |
| source evidence | exact retained provider/chain bytes plus acquisition metadata | that the source was complete or truthful |
| decoded protocol assertion | versioned interpreter over raw evidence, with IDL/program/package identity | landed household effect by itself |
| protocol-exact calculation | one versioned Rust calculator over an exact state manifest | actual fill, landing, or currentness |
| landed financial fact | reconciled finalized asset effects over the declared portfolio domain | operator intent or episode meaning |
| financial projection | deterministic ledger/lot/basis reducer over landed facts | source evidence or strategy profitability |
| official SDK result | pinned comparator/oracle at a named version | Joshi's durable truth by fiat |

The source-of-truth chain is therefore:

```text
raw bytes -> decoded assertions -> reconciled landed asset effects -> financial ledger
                    |
                    +-> exact state manifest -> calculation artifact
```

The UI, Python studies, SQL views, TypeScript SDK, and OCaml oracle may inspect or challenge this
chain. None may independently recompute a production PnL, quote, basis, or LP schedule under the
same formula identifier.

This also resolves a potential lane 17/lane 20 duplication. The **protocol adapter** decodes state
and may invoke pinned SDK behavior during conformance. The **numeric core** owns Joshi's formulas
and exact artifacts. An SDK-shaped Rust protocol object never becomes a ledger row, and a numeric
quote never becomes a fill.

### 7. The deadline changes bakeoff size, not semantic requirements

Lane 13 proposes a million-record, multi-language runtime bakeoff. Lane 19 proposes OCaml, C#, and
Rust testing packets. Lane 20 proposes Rust, OCaml, C#, and TypeScript numerical conformance. Lane
23 narrows this to a leading architecture and one serious challenger. Lane 24 says the pre-
September corridor cannot afford architecture theater.

Running all proposals literally would spend the corridor building several miniature platforms.
The resolution is a two-level decision:

- **Runtime walking fixture:** Rust versus Python only, using the same tiny semantic/adversarial
  corpus and no duplicate UI. It selects the application core.
- **Independent conformance runners:** TypeScript official SDK and optional OCaml/Zarith programs
  operate on vectors. They are tests, not alternative applications.

Million-event throughput, 72-hour source behavior, browser host comparisons, and formal-tool
selection are separate capacity or assurance experiments. They do not block the first runtime
decision unless the measured Slice 1 load makes them relevant.

The deadline never licenses importing old state, fabricating basis, replacing a live chart with a
percentage reconstruction, calling a similar board Pump parity, skipping access review, or adding
execution for revenue. A smaller truthful artifact is the deadline fallback.

## Recommended topology and ownership

```text
                                Ember
                                  |
                    React/TypeScript browser shell
                     gesture + rendered-state client
                                  |
                    authenticated loopback contract
                                  |
             +--------------------v--------------------+
             |              Rust local core           |
             |                                         |
             | command/query | one writer | replay     |
             | evidence      | assertions | coverage   |
             | protocol      | numeric    | ledger     |
             | operator      | scenes     | hot scopes |
             +--------+------------------------+-------+
                      |                        |
             bounded adapter port      SQLite + CAS blobs
                      |                        |
        +-------------+-----------+      manifested Parquet
        |                         |              |
  Rust source tasks       optional TS runner     v
  chain/Pump reads        exact missing SDK   Python research
                                  
Optional, separately reviewed acquisition edge:
Pump browser -> deliberate scene or narrow companion adapter -> core ingest

Test-only edges:
canonical vectors -> TypeScript SDK comparator / OCaml-Zarith oracle
```

The whitespace between the current graph and any future authority graph is intentional. Do not add
future planner/signer interfaces to “preserve extensibility.” The accepted documents already
preserve the conceptual seam.

### Module ownership

| Module | Owns | Must not own |
| --- | --- | --- |
| evidence | observation identity, blobs, acquisition clocks, coverage, append contract | provider meaning, ledger classification |
| protocol | source-native decode, program/IDL profile, exact state artifacts | operator meaning, landed-effect truth |
| numeric | dimensioned exact arithmetic, formula profiles, quote/LP calculation artifacts | actual fill claim, UI formatting |
| ledger | reconciled asset effects, postings, lots, basis quality, inventory epochs | episode resolution, current mark as value |
| operator | episodes, subject links, gestures, stance/thesis/playbook records | balances, fills, authority capability |
| replay | scene manifests and witnessed/cutoff/retrospective reconstruction | live source calls during replay |
| control | desired hot scopes, leases, budgets, degradation | strategy authority or automatic capital action |
| query/application | immutable view snapshots and command orchestration | second calculation or database truth |
| UI | rendering, viewport evidence, semantic gestures | source secrets, SQL, provider calls, financial calculation |
| research | frozen snapshots, features, experiments, derivations | canonical writes, live policy, unseen score injection |

Dependency direction is inward toward semantic values and pure reducers. Storage rows, SDK types,
React state, Arrow batches, and notebook data frames stop at adapters.

## Coherent engineering vocabulary

The semantic vocabulary in `FOUNDATION.md` remains normative. Engineering should add only these
terms:

| Term | Meaning | Not synonymous with |
| --- | --- | --- |
| **operational core** | one local application owning commands, writes, projections, replay, and queries | every process in the deployment |
| **semantic core** | network/store/UI-free value types and pure transition rules | protocol SDK types or database schema |
| **protocol adapter** | versioned interpreter of raw source/chain bytes into bounded assertions/state artifacts | financial ledger or SDK oracle |
| **numeric core** | single executable owner of formula profiles and exact derived financial values | landed financial truth |
| **source runner** | replaceable, capability-poor adapter process used for runtime/fault isolation | service, backend, or semantic authority |
| **companion adapter** | optional user-side client preserving a reviewed portion of a reference-rendered scene | market census, browser automation, Pump API |
| **operational store** | transactional catalog and recent state under the one writer | evidence tape as a logical whole |
| **analytical export** | immutable manifested Parquet produced at a closed watermark | canonical mutable state |
| **research snapshot** | frozen, point-in-time-correct selection for one study | latest operational database or replay scene |
| **calculation artifact** | versioned exact request/result/profile/input-manifest record | fill or ledger posting |
| **reference oracle** | independent implementation or official artifact used to detect disagreement | production authority |
| **projection** | rebuildable named interpretation over evidence/assertions | raw fact or permanent schema |
| **view snapshot** | immutable query result actually offered to a renderer, with watermarks | all backend knowledge |
| **production runtime** | a runtime required to start or operate the approved cockpit path | offline test or research toolchain |
| **production language** | language whose artifact runs in that path | SQL schema, fixture format, or test-only oracle |

Use qualified “truth” terms in review: source evidence, landed financial truth, derived numerical
truth, witnessed render. Avoid an unqualified “single source of truth,” which obscures their
different authorities.

Also reserve **journal** for the future authority/reservation/submission records named by the
foundation. Lane 20's “financial journal” should be called the **financial ledger** and its
**postings** in code and ADRs. Reusing `journal` for ordinary asset accounting would erase a useful
capability boundary.

## Language budget

### Recommended Slice 1 budget

| Language/tool | Role | Runs in ordinary product path? | Authority |
| --- | --- | ---: | --- |
| Rust stable | operational core, protocol, numeric, ledger, replay, storage/API | yes | single operational and derived-numeric owner |
| TypeScript | React browser; optional narrow SDK runner in the same toolchain | yes | presentation or source assertion only |
| SQL | explicit store queries/migrations | inside core | storage representation, never domain meaning alone |
| Python | frozen-snapshot research and disposable source probes | no | derived research artifacts only |
| OCaml/Zarith | independent exact vectors/reducer oracle | tests only | disagreement detector only |
| Julia | named later scientific study | no | none initially |
| C#/F#/Lean | none | no | none |

This is two production languages. A Node runner does not create a third language, but it does
create another production process and must satisfy the same contract, supervision, pinning, and
trace requirements.

Python research must use a separately locked environment even though Python source probes may have
helped Spike 0. A notebook never imports Rust internals through an ad hoc FFI; it consumes
manifested Parquet/Arrow or a versioned read API. OCaml is not required for ordinary `dev up`; its
vectors or published expected results can be consumed without an installed switch in the fast
path.

### Admission rule for a third production language

A third production language requires an ADR showing all of:

1. one measured, current problem cannot be solved adequately in either selected language;
2. the new boundary removes more bespoke code or assurance risk than its schema, packaging,
   tracing, and release burden adds;
3. exactly one side owns every semantic fact;
4. the offline fixture runs when the component is absent or replaced by a recorded artifact;
5. removal/migration and version-skew behavior are tested.

“Better types,” “better AI support,” “already installed,” and “might help formal verification” do
not satisfy the rule by themselves.

## Hidden duplicate truths and dependency cycles

### Duplicate numerical authorities

Potential cycle:

```text
Rust formula -> TypeScript SDK -> Python display calculation -> SQL view -> Rust reconciliation
```

Break it by making the Rust calculation artifact the only production derived number. TypeScript is
a comparator or adapter; Python and SQL consume results. A mismatch appends a defect, not an
average or fallback number.

### SDK objects becoming domain contracts

Official Rust/TypeScript SDKs are mutable interpreters. If their account or quote objects cross
directly into SQLite, UI, or research, an SDK update silently becomes a semantic migration.
Adapters must emit repository-owned observations/assertions/calculation requests with exact
program, IDL, package, state, and source identities.

### Operational and analytical stores becoming peers

Allowing the UI to query DuckDB/Parquet directly or allowing research to update SQLite creates two
current states and a circular dependency between product and study. Exports flow outward at a
watermark; reviewed derivations return as new append records through the core.

### Ledger and episode projections owning each other

The ledger must not require an episode ID to close, and episode state must not synthesize a fill.
The only crossing is append-only attribution from a landed financial fact to an episode/tranche.
This prevents a corrected story from changing household assets and a wallet delta from claiming
intent.

### Scene replay and current query code

If witnessed replay recomputes through current reducers, parser or identity upgrades rewrite what
Ember saw. Persist the view snapshot/render contract used in the scene. Knowledge-cutoff replay may
recompute with named versions; retrospective replay may use later evidence. These paths share
evidence, not output identity.

### UI state and source coverage

A rendered list, virtualized DOM, viewport, and clicked row are not the served source list. UI
acknowledges rendered/visible sets against an immutable view snapshot. It never reconstructs the
choice denominator from current component state during replay.

### Provider health and scope health

One open socket can carry many filters while silently omitting a wallet or mint. Coverage is keyed
by exact source manifest and scope lease. Connection health cannot keep a per-key route green.

### Companion evidence and independent market evidence

Pump-rendered identity, rank, thread, or chart pixels are scene evidence. Chain/program facts are
market evidence. Joining them can enrich a scene; neither overwrites the other. A browser companion
cannot become the market collector, and an on-chain feed cannot claim what Pump rendered.

### Research features and product policy

A feature built from retrospective Parquet can accidentally re-enter the cockpit as a “useful
field,” creating future leakage and changing the attention policy. A research output becomes
operator-visible only through a promotion record, a frozen online-computable input contract, and a
new product/policy epoch.

### Process supervision and semantic orchestration

If a generic process supervisor knows hot-scope, episode, or replay meaning, infrastructure becomes
a second application. The core emits desired source manifests; supervision only starts, stops, and
reports process health. The source runner never decides which mint matters.

## Ranked architecture decisions

### Rank 0 — preserve the authority ceiling

Accept now: the implementation graph is observe/query/reconcile/replay only. No builder-shaped
interface, simulation from newly constructed bytes, signer seam in code, send dependency, or
future executor directory. Read SDKs with inseparable builder exports remain quarantined behind a
non-authoritative adapter/harness and cannot receive a wallet, blockhash, submit RPC, or generic
method dispatch. This outranks schedule and language preference.

### Rank 1 — select the product operating mode from Spike 0

Planning default: exact-mint companion-capable cockpit. Replacement remains unearned. This decision
sets what choice context and source access the architecture may claim; it is more consequential
than database or framework selection.

### Rank 2 — select one operational owner

Recommended: stable Rust core. Bake off against Python using one complete walking fixture. Do not
scaffold both architectures, and delete/archive the loser after preserving vectors and measured
results.

### Rank 3 — select one owner for every financial number

Recommended: the Rust numeric module inside the core, checked by TypeScript official comparators
and optional OCaml/Zarith vectors. Landed asset effects remain the financial authority. No UI,
notebook, SQL view, or source runner recomputes production PnL or quotes.

### Rank 4 — accept the one-writer storage boundary conditionally

Recommended: SQLite WAL + content-addressed blobs, then manifested Parquet and ephemeral DuckDB.
Acceptance requires fixed runtime version/configuration, crash/replay/restore, and measured load.
PostgreSQL is the successor if the gate fails; it is not a second initial store.

### Rank 5 — fix the logical topology before process placement

Accept: modular monolith, inward dependencies, one writer, pure reducers, adapter-owned vendor
details. Default adapters are in process; separate only the current SDK/credential/failure
boundary that earns a runner.

### Rank 6 — keep one shell-neutral web renderer

Recommended: React/TypeScript in an ordinary browser. A Tauri or Electron wrapper is downstream of
a measured browser/WKWebView/native capability failure. A companion adapter is independently
reviewed and never the system of record.

### Rank 7 — isolate research physically and temporally

Accept: Python/DuckDB/PyArrow over frozen, point-in-time-correct snapshots; immutable run bundles;
no canonical writes or automatic score visibility. This is a separate dependency graph, not a
plugin loaded into the core.

### Rank 8 — scale only the measured bottleneck

Accept for the initial corridor: selective local S0/S1, bounded tapes, $0 incremental spend, no
full raw firehose. The measured 1,552 notifications/s and 238.9 GB/day demonstrate why ordinary
development and CI must use compact, manifested fixtures. S2 and managed streams require their own
value and cost decision.

### Rank 9 — apply formal methods only at an assurance gap

Use executable types, properties, state-machine traces, fuzzing, and crash failpoints first. A
small TLA+/Quint model may earn its place for cursor/evidence atomicity or future attempt
reservations if it finds a planted defect and exports a regression trace. Kani/Dafny/Lean require a
stable named kernel. The provisional operator ontology is not such a kernel.

## The minimum bakeoff that can overturn the recommendation

### Common walking fixture

Implement the same headless path in stable Rust and Python:

```text
raw observation + blob
  -> atomic append/cursor
  -> one versioned protocol assertion
  -> one exact asset-effect/lot/inventory-epoch reduction
  -> one operator episode with flat watch and re-entry
  -> one scene/view snapshot
  -> witnessed and retrospective replay digests
```

The fixture contains duplicate delivery, equal-valued distinct events, gap/recovery, parser
correction, unknown basis, partial reduction, exact flat, and re-entry. It uses one small public
Solana fixture plus hand-readable synthetic records. No UI duplication, live collector, wallet,
cloud service, or million-record file is required.

Hard pass criteria for either candidate:

- all exact-integer, identity, missingness, cutoff, and replay invariants pass;
- a crash cannot advance the cursor beyond evidence or duplicate an economic effect;
- the complete path starts offline from one root command;
- module boundaries permit source-adapter and reducer changes without cross-layer edits;
- one representative displayed value traces to its raw bytes and calculation version;
- release-mode checks catch overflow and no floating financial value crosses the contract;
- a fresh agent can make two bounded changes without bypassing the model;
- the implementation remains small enough to delete.

Measure setup, implementation/review time, edit-to-test latency, dependency count, bridge code,
counterexample quality, semantic diff clarity, and Ember's desire to continue editing it. Rust is
selected if both pass without a material product-loop disadvantage. Python overturns the default
only if it is materially faster and clearer on the complete path, while requiring no hidden Rust
runtime and no duplicate production formula path.

Time-box the comparison to the small fixture. If neither passes promptly, reduce the slice rather
than add abstraction or another language.

### Protocol conformance after runtime selection

Run the lane 17 read-only differential harness on the exact protocol functions Slice 1 requires.
Do not make the runtime decision wait for every Pump/Meteora feature.

- Rust must decode the supported Solana/Pump fixtures exactly.
- Official TypeScript SDK outputs remain pinned comparators.
- Meteora becomes native Rust only for the state/quote paths with zero unexplained integer or
  dependency mismatches.
- A failing function stays in a narrow TypeScript runner or remains unsupported. It is not
  reimplemented approximately to preserve architectural purity.
- C# does not participate unless the whole-core decision has been explicitly reopened.

### Storage and scale after the core choice

Use the selected core for SQLite crash/load/restore gates and lane 22's captured-envelope replay.
Do not repeat a paid full firehose. The default fixture profiles are tiny, representative, and
opt-in capacity. A store/runtime that cannot clear measured S0/S1 is rejected; S2 is not a Slice 1
requirement.

## Coherent fallback if Python wins

If the walking fixture overturns Rust, choose a **Python operational core**, not Python plus a
shadow Rust backend:

```text
React/TypeScript browser
  -> Python one-writer core: evidence, storage, accounting, episode, replay, API
       -> narrow TypeScript protocol/quote runner where official SDK fidelity is required
  -> manifested Parquet -> separate locked Python research environment
```

In this alternative:

- Python owns one validated production accounting/replay implementation with explicit big-integer
  units, immutable tagged models, pure reducers, and release-independent property tests.
- TypeScript adapter results are manifest-bound assertions. Python does not duplicate venue quote
  arithmetic merely to remove the boundary.
- Rust and OCaml implementations, if retained, are test oracles only and do not run under
  `dev up`.
- The SQLite/CAS/Parquet/DuckDB topology, browser shell, source-runner capability limits, research
  isolation, and no-execution ceiling remain unchanged.
- R4 exact quote/numeric promotion reopens the runtime ADR if Python cannot satisfy protocol
  conformance. It does not smuggle a permanent Rust calculator into Slice 1 without counting the
  new boundary.

The fallback is sensitive to scope. It is credible for exposure truth and one episode corridor.
It becomes less attractive as native Pump/PumpSwap decoding, DLMM arithmetic, compact S2
processing, or future authority enters the approved product. If those become near-term rather than
optional, Rust should remain the core unless the bakeoff shows an actual blocker.

If Pump access selects stop/rethink, neither runtime “wins.” Retain the fixture and possibly the
small exposure/accounting tool; do not build a general core to vindicate the architecture review.

## Formal-method allocation

The engineering lanes agree more than they disagree here. Formalism earns complexity at stable
state and authority boundaries, not at speculative market meaning.

Use now:

- typed units/identities and exhaustive missingness;
- property tests for ledger conservation, episode/epoch independence, idempotency, and cutoffs;
- state-machine traces for evidence/cursor/checkpoint crash recovery;
- differential vectors for protocol and numerical arithmetic;
- hostile-byte fuzzing and fixed replay corpora.

Consider after the executable model exists:

- one small TLA+/Quint model for evidence/cursor durability if schedule exploration reveals a real
  concurrency gap;
- OCaml/Zarith as an independent pure numerical/reducer oracle;
- Kani for bounded Rust arithmetic/decoder predicates that remain difficult to cover.

Defer:

- Lean proofs, Dafny translations, a verified policy DSL, or mirrored OCaml production semantics;
- proof of provisional gesture/disposition taxonomies;
- formal claims about strategy profitability, market stationarity, source completeness, attention,
  or social causation.

Every formal artifact needs a production mapping, tool pin, planted defect, counterexample-to-test
path, and deletion condition. A proof whose vocabulary no longer matches the code is a liability.

## Build-versus-buy boundary

Build the meanings that define Joshi: evidence identity, coverage, episode/epoch separation,
operator gestures, scene/replay, exact accounting, calculation artifacts, and point-in-time study
contracts.

Reuse, pin, and distrust the plumbing: official SDKs/IDLs, RPC/WebSocket/Yellowstone transports,
SQLite, Parquet/Arrow/DuckDB, React, charting, and ordinary observability/test tools. Their objects
stop at adapters and their upgrades open conformance diffs.

Do not buy a feed, managed Geyser tier, object store, observability SaaS, ML platform, or desktop
packaging service in the current corridor. A paid source must solve a measured coverage/latency/
recovery problem after natural product use and remain replaceable. Trading profit is not a budget
assumption.

## Decisions the root synthesis should record

The root synthesis should record the following without pretending the gates have already run:

1. **Architecture candidate:** stable Rust local modular core + TypeScript browser, one writer,
   SQLite/CAS, manifested Parquet, ephemeral DuckDB.
2. **Product posture:** exact-mint companion-capable by default; operating mode selected only by
   Spike 0.
3. **Financial authority:** landed reconciled effects are actual truth; one core calculator owns
   derived numerical meaning; SDKs and OCaml are comparators.
4. **Language budget:** Rust and TypeScript in product; Python research; OCaml test-only; no C#,
   F#, Julia, or Lean initially.
5. **Process rule:** in-process adapters by default; one capability-poor runner only for a proved
   runtime/fault boundary.
6. **Storage rule:** one canonical operational writer/store; Parquet outward, derivations inward;
   no dual-write migration.
7. **Delivery rule:** run only the access gate, two-candidate walking fixture, exact required
   protocol conformance, and first natural Slice 1 loop. Do not run every lane's bakeoff.
8. **Cost rule:** $0 incremental local S0/S1 until an explicit later purchase decision.
9. **Authority rule:** no construction, signing, submission, live execution, or placeholder
   execution surface.

After the gates, the first ADR set should be only: operating mode, runtime, storage, contract
source, initial adapters/process shape, and retention classes. The repository skeleton follows
those decisions; it must not precede them.

## Rejected combined architectures

- Python application + Rust protocol + Rust calculator + Node SDK sidecars + OCaml production
  reducer. It duplicates boundaries while claiming Python simplicity.
- C# service shell + F# semantic library + Rust protocol + TypeScript UI. It is a plausible whole-
  core alternative decomposed into an unjustified federation.
- OCaml semantic service + Rust protocol/data service + TypeScript UI. The semantic elegance does
  not yet repay a permanent evidence crossing and third production toolchain.
- TypeScript UI as financial authority because it already holds official SDKs. Presentation and
  vendor interop do not own accounting truth.
- Python notebooks sharing application imports or a writable live SQLite connection. Research is
  not another application module.
- Persistent DuckDB plus SQLite plus Parquet as peer stores. DuckDB is disposable and manifests
  define the export.
- A process per source, strategy family, research lane, or projection. Process isolation is earned
  by dependency, failure, credential, or later authority.
- WebExtension-first product design. Companion access and permission are conditional; the local
  renderer and exact-mint core must remain useful without it.
- Full Pump replacement as an architecture premise. It is a Spike 0 result for one named surface.
- General firehose/platform work before S0/S1 natural use. The measured raw stream is feasible to
  receive but economically and operationally unjustified for the first corridor.

## Bottom line

The engineering lanes do not require a compromise stack. They point to one clean default once
their dependencies are made explicit:

> Put the durable read-only product around the Rust boundary that protocol and numerical truth
> already require; keep the UI in TypeScript; keep research in Python; use OCaml only to disagree
> with the production calculator; preserve one SQLite/CAS write authority and one-way Parquet
> exports; add sidecars only for exact SDK gaps; and let Spike 0 decide whether the product is a
> Pump companion, a one-surface replacement, an independent observatory, or a smaller stopped
> artifact.

That decision is ambitious where rigor compounds and conservative where complexity would only
delay learning. It keeps every current process unable to construct, sign, or submit a transaction.
