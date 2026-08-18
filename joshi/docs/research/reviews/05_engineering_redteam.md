# Review 05: engineering red team — make the first artifact harder to fake than to build

Status: adversarial cross-review of engineering lanes 13–24 against the accepted foundation and
the epistemic red team. Pre-engineering only. This review authorizes no implementation, purchase,
browser capture, credential use, transaction construction, signing, submission, or capital use.

Reviewed in full:

- [`FOUNDATION.md`](../../decisions/FOUNDATION.md);
- [`11_epistemic_redteam.md`](../lanes/11_epistemic_redteam.md); and
- engineering lanes [`13`](../engineering/13_runtime_language.md) through
  [`24`](../engineering/24_runway_delivery.md).

## Verdict

The engineering packet contains many good local decisions and one dangerous global illusion: it
can make a large, unresolved platform look like a collection of small, already-justified pieces.

Lane 13 recommends a Rust core. Lane 14 recommends a Python core. Lane 20 recommends a Rust
numeric/accounting authority plus an independent OCaml implementation. Lane 17 adds official
TypeScript comparators and perhaps C#. Lane 16 adds a TypeScript browser and potentially a browser
extension or desktop shell. Lane 18 defines a separate Python research environment. Lanes 15, 19,
22, and 23 add a multi-tier store, deterministic laboratory, control plane, contract generation,
fixtures, migrations, manifests, and development shell. Each proposal has a reason. Their union is
already a multi-runtime evidence platform before Joshi has established that it may lawfully observe
the product surface Ember needs or that Ember will naturally use the resulting loop.

That ordering can make engineering quality an evasion of product risk. The system can become
excellent at retaining, replaying, and verifying the wrong evidence.

The correct adversarial posture is:

> Product/source admissibility first; one truthful operator path second; durable architecture only
> after those gates. A bakeoff may choose how to build an earned path. It must not decide whether
> the path was worth building.

The immediate threat is not only intentional benchmark gaming. A thoughtful team can game itself
by selecting fixtures that flatter its favorite language, timing only the part implemented in that
language, calling identical re-execution “replay truth,” counting two SDKs with common ancestry as
independent agreement, or declaring a companion safe because it is local. September pressure makes
all of these self-deceptions more likely.

## The packet's strongest parts

The red team should preserve what is genuinely load-bearing:

- landed asset effects outrank marks, quotes, SDK fields, and transaction intent;
- operator episode and inventory epoch are different objects;
- raw observations survive corrected parsers and projections;
- unknown, stale, unquotable, unsupported, and zero are not interchangeable;
- source health, gaps, and selection coverage are product state;
- current quantity and executable liquidation can remain useful when historical basis is unknown;
- system-read-only is a real capability boundary, not a UI convention;
- a cheap denominator plus explicitly promoted hot scopes is more defensible than indiscriminate
  high-resolution collection;
- natural operator use and witnessed scenes are product evidence; infrastructure completion is
  not; and
- every stop path should leave an exportable, useful artifact.

Those principles do not require implementing every type, replay mode, contract generator, oracle,
store tier, or language mentioned in the packet. The foundation should constrain the first slice,
not require the first slice to instantiate the entire foundation.

## How careful lanes compose into overengineering

The phrase “smallest experiment” appears in several lanes, but the experiments are not additive
without cost. Combined literally, the first engineering cycle would need:

1. a Pump workflow and access review;
2. chain acquisition from two paths, gap recovery, and a provider scorecard;
3. exact Pump, PumpSwap, Token-2022, Solana-fee, and Meteora arithmetic profiles;
4. Rust, OCaml, TypeScript, and possibly C# conformance runners;
5. a canonical JSON contract and generated bindings;
6. SQLite WAL, an external content-addressed blob store, Parquet archives, and DuckDB research
   views;
7. three replay products and bitemporal identity/metadata handling;
8. a browser cockpit and possibly a Manifest V3 companion;
9. wallet reconstruction, lots, basis quality, episodes, scenes, and lineage inspection;
10. crash, fuzz, model, migration, differential, chaos, and deterministic replay suites;
11. a selective streaming control plane with leases, budgets, degradation, and coverage; and
12. a reproducible monorepo development shell plus a separate research environment.

This is not a small vertical slice. It is a credible later architecture program. Calling each
piece “narrow” does not make their dependency graph narrow.

The packet also contains a revealing inconsistency. The reference architecture can only choose a
Python core by treating exact protocol/numeric work as adapters or later promotion. The numeric
lane can only choose a Rust authority by creating a production boundary that the runtime and DX
lanes say must be earned. The runtime lane can only choose Rust by scoring future authority and
protocol fit before the current read-only product has survived natural use. These are not merely
different implementation tastes. They place the project's first irreversible bet at different
points in the uncertainty tree.

The synthesis should not average them. It should postpone the permanent-runtime decision until a
walking path exists, and allow disposable Spike 0 code to be disposable.

### The ontology can become architecture by accident

The foundation's distinctions are essential when a feature touches them. They become harmful if
every noun immediately receives a schema, repository module, migration policy, serializer, and
cross-language binding. A first exact-mint exposure view may need observations, asset effects,
quotes, gaps, and a witnessed scene. It need not implement every future assertion graph, identity
edge, counterfactual branch, formal policy tier, research registry, or LP schedule.

A good test is deletion: if a proposed layer can be removed from the first operator path without
making one displayed claim dishonest, omit it. “We will need it eventually” is not evidence that
it belongs before first use.

## Language capture and the ways a bakeoff can lie

No language is neutral here. Rust flatters the project's desire for exactness and future safety.
OCaml flatters Ember's taste for semantic elegance. Python flatters urgency. C# flatters the desire
for a calm, productive application ecosystem. TypeScript flatters integration convenience. These
are real qualities and also sources of motivated reasoning.

### Rust and OCaml aesthetic capture

Rust can feel like financial seriousness before the program has financial authority. Its types,
checked boundaries, exhaustive enums, and single binaries are valuable, but they do not establish
source completeness, correct protocol interpretation, lawful acquisition, or operator usefulness.
Ownership and trait design can consume the short product corridor while looking like hardening.
An agent can also make Rust compile by cloning broadly, wrapping everything in `Arc<Mutex<_>>`,
using lossy `as` conversions, or hiding the domain behind generic traits. The compiler then becomes
an aesthetic certificate for code whose semantic ownership is still poor.

OCaml can express the episode/replay state space beautifully. That is not evidence that it should
own RPC, SQLite, Arrow, browser, packaging, or operational recovery. A pure OCaml reducer can win a
clarity contest by externalizing every inelegant responsibility to sidecars whose setup, contracts,
and failures are excluded from the score. An OCaml oracle is useful only if it is independently
written and narrow; an isomorphic second application is maintenance debt wearing formal-methods
clothing.

The Rust-plus-OCaml proposal is especially vulnerable to prestige escalation. One production
calculator, one mathematical oracle, TypeScript SDK comparators, a browser runtime, and Python
research already create four toolchains. That may eventually be justified for exact money math.
It is not a free consequence of admiring strong types.

### Python expedience debt

Python can reach a source probe and inspectable view quickly. It can also turn a disposable probe
into the production owner by inertia. The debt is not merely speed or type safety:

- dynamic dictionaries can erase the distinction between absent, unknown, stale, and zero;
- source DTOs can leak directly into persisted state and UI;
- notebook and application code can share imports until a study silently becomes a reducer;
- async tasks, background processes, and write ownership can remain conventional rather than
  explicit;
- exact integer values survive Python arithmetic but lose units, width, narrowing, and deployed
  overflow behavior;
- `sqlite3`, Arrow, and serialization behavior depend on the actual Python build and native
  wheels, not on “Python” as a language; and
- the 164,000-line compost makes copying a convenient old abstraction easier than specifying the
  new meaning.

A Python spike should either be accepted deliberately after the walking fixture or remain a donor
of fixtures and observations. “It already works” is not an architecture decision.

### C# ecosystem optimism

C# is plausibly pleasant for a local daemon: mature diagnostics, concurrency, packaging, SQLite,
and agent familiarity. The optimistic failure is to test those strengths while postponing the
actual Solana/Pump/Meteora integration. A clean C# service can appear to win while delegating
protocol decoding or quote truth to a Node or Rust helper. The operational result is then a
three-runtime system, not a superior C# application.

`BigInteger`, `UInt128`, records, and `checked` blocks make exact work possible, but do not make it
the default everywhere. Community Solana libraries may be valuable adapters; their existence is
not evidence of current coverage, canonical byte behavior, or independence from the same IDL and
SDK assumptions under test. Self-contained .NET packaging also needs to be tested with the actual
native SQLite/Arrow dependencies and Apple-arm64 target, not inferred from the runtime's general
quality.

### TypeScript and mixed-stack optimism

TypeScript gets an unavoidable advantage if official SDK use and a browser UI dominate the task.
It can lose that advantage instantly if exact money values pass through `number`, runtime input is
cast rather than validated, or React state becomes the domain store. A Node SDK runner is not
architecturally free: it has its own lifecycle, package supply chain, error semantics, clocks,
recovery, and version manifest.

A mixed stack must be scored as the sum of all of its processes. Calling Rust “the core,” Python
“only orchestration,” Node “only an SDK runner,” and TypeScript “only the UI” can hide more
operational surface than any single-language contender.

## Concrete bakeoff plants: how each contender can appear to win dishonestly

“Dishonestly” here includes unconscious experimental design. The following are test attacks to
plant deliberately before trusting a result.

| contender | a bakeoff can be rigged in its favor by | adversarial detection |
| --- | --- | --- |
| **Rust** | counting compiler-caught defects selected to suit Rust; giving it direct crates for protocol/Arrow paths while rivals hand-port; timing warmed reducer loops without Cargo build, adapters, SQLite `FULL`, blob sync, or browser boundary; omitting clone/trait complexity from review | include semantic defects the type system cannot see; time clean setup, full end-to-end path, crash recovery, packaging, and a later change; count every helper process and inspect domain code for casts, clones, interior mutability, and generic indirection |
| **OCaml** | assigning it only the pure reducer; excluding RPC, SQLite/Parquet, packaging, and bridge code from LOC/time; seeding exhaustiveness bugs tailored to variants; giving an OCaml expert more hand repair; timing native pure functions only | require the same declared boundary or label it an oracle rather than a core; include clean-machine opam/Dune setup, serialization, hostile bytes, and one source-version change; score all sidecars and handwritten glue |
| **C#** | testing local-daemon ergonomics while using fixtures already normalized by TypeScript/Rust; calling a community SDK an oracle; excluding NativeAOT/native dependency failures; allowing GC and memory growth outside the short run; measuring only incremental build/debug speed | start all candidates from identical raw bytes; require canonical transaction/account decode or explicitly charge the helper runtime; measure cold package, 5x replay, allocation, long-run pause, crash/restart, and unsupported protocol cases |
| **F#** | claiming compile-time domain wins while relying on C# mutable libraries and DTOs at every edge; counting F#-specific seeded union bugs; excluding interop conversion and agent repair time | inspect where the domain stops and C# objects begin; require source drift and persistence migration changes; charge conversions and duplicated type models to the candidate |
| **Python** | winning a short first-prototype clock by weakening validation, durability, and static checks; using C/Rust-backed libraries without counting their deployment; running only small warm fixtures; deferring every schema and crash issue beyond the timebox; using notebook state or local legacy data | require identical runtime-validated contracts, `FULL` durability, bounded queues, cold replay, clean environment, and no ambient home data; repeat a semantic change after the initial spike and count repair/retest time |
| **TypeScript/Node** | counting official SDK access as language merit while making other contenders reimplement it; parsing big integers into `number` only on non-adversarial fixtures; sharing UI/domain DTOs to minimize LOC; ignoring npm install scripts and process supervision | inject values beyond 2^53, hostile/unknown JSON variants, SDK version drift, offline install, and child-process failure; score browser/domain coupling and exact dependency tree |
| **Rust + OCaml** | scoring Rust's production strengths and OCaml's clarity as if both were free; excluding oracle maintenance because it is “tests”; generating both from one schema/formula while still calling them independent | compare against the best single-production-runtime design; include dual update and mismatch triage on a protocol change; reject independence when implementations share generated arithmetic or copied operation order |
| **Python + Node + TypeScript** | calling Python the only backend and Node a trivial official-SDK bridge; reusing JavaScript types between Node and browser while ignoring validation across the Python boundary | count three runtimes, three lock/update paths, process supervision, canonical serialization, error mapping, and a clean offline demo; kill the Node helper during a replay |

Additional ways to rig every candidate:

- let its advocate choose the fixtures after seeing its failures;
- let one candidate reuse legacy donors while another starts from a blank file;
- compare mature library output with a hand-built rival implementation;
- expose the challenge set, then allow only the preferred candidate a cleanup pass;
- report the best run rather than all runs and variance;
- use generated uniform rows instead of the measured payload-size and failure mix;
- give agents prompts with unequal context, examples, tool versions, or time;
- count a compiler diagnostic as a caught domain bug without proving the other implementation
  would have shipped it;
- count code size without adapters, generated bindings, fixtures, build scripts, or sidecars;
- score projected R6 authority value in a contest whose accepted scope is R0–R4; and
- turn Ember's aesthetic preference into many weighted subcriteria so that a foregone choice looks
  quantitative.

The weighted matrix in lane 13 is useful for exposing values, not for manufacturing a measurement.
Scores such as 4.54 versus 4.13 are not precise enough to justify permanent topology. A hard-gate
failure, a material operator preference, or a large end-to-end difference may decide. Small decimal
differences should not.

## Correlated SDK oracles

The protocol and numeric lanes correctly refuse to treat an SDK as landed truth, but the proposed
conformance suite can still overcount independence.

Official TypeScript and Rust implementations may share an IDL, source formula, maintainer, test
vectors, generated layout, or copied bug. A C# adapter may consume the same generated IDL. Two RPC
providers may use the same upstream chain data, transaction encoding, or indexer. Read-only
simulation may construct the transaction with the same SDK whose quote is being checked. Four
green outputs can therefore represent one assumption repeated four times.

An oracle inventory must be by **provenance**, not language:

| evidence | what it can establish | what it cannot establish alone |
| --- | --- | --- |
| deployed account/transaction bytes | exact observed bytes at a locator | correct decode or historical completeness |
| finalized controlled-wallet effects | what assets actually changed at the declared boundary | which component or intent caused an ambiguous bundled effect |
| manually derived integer boundary vector | a small operation and rounding result independent of production code | broad deployed-state coverage |
| official SDK result | conformance to a pinned supported client behavior | deployed truth, unsupported variants, or independence from copied formulas |
| read-only chain simulation | acceptance/effects of one constructed transaction at one state | quote correctness across states or independence when construction shares the SDK |
| independently written reference model | disagreement detector for specified semantics | whether the specification itself is right |
| second provider | delivery/recovery comparison | independence if the provider normalizes through the same source or omits the same data |

No majority vote is permitted. A mismatch remains unexplained until raw bytes, operation order,
deployment identity, and landed effects locate it. Agreement among descendants of the same source
counts once.

The most valuable conformance corpus is deliberately awkward: unsupported account variants,
upgrades, exact rounding boundaries, failures that still pay fees, routes whose official helpers
disagree, Token-2022 extensions, ambiguous bundles, and cases found after the oracle suite was
frozen. Easy current SDK examples should not dominate the pass rate.

## False replay determinism

Deterministic replay is necessary for debugging. It is not evidence that the recorded scene was
true, complete, causal, or useful.

The same parser can decode the same wrong raw bytes into the same wrong assertion twice. The same
canonicalizer can consistently invent an order that the source never supplied. A projection can
exclude a missing source in a deterministic way. A UI DTO captured after a decision can replay
hindsight perfectly. A frozen model output can be byte-identical while having used leaked input.
Two architectures can share a canonical bug through generated bindings. A content hash proves
byte identity, not meaning.

Three replay products add precision only if their input boundaries are independently testable:

- **witnessed replay** must prove what the product actually rendered, including unavailable fields,
  source health, viewport, and product version;
- **knowledge-cutoff replay** must prove every included fact was available by the cutoff, not merely
  that its event time was earlier; and
- **retrospective replay** may include corrected history, but must not be compared with the earlier
  decision as though the correction had been available.

Adversarial replay tests should include:

1. raw bytes that the current parser misreads but a later parser repairs;
2. two equal-valued events with distinct identities;
3. same-slot events without a source-supplied total order;
4. late and backfilled records whose event time precedes their availability;
5. a renderer that silently drops an unknown enum or stale field;
6. a quote generated from state newer than the scene;
7. mutable metadata and identity that change after the act;
8. a deliberately missing source interval that remains missing on every replay;
9. a model annotation whose prompt contains a future field; and
10. a browser/font/layout change that alters what was visible despite identical semantic rows.

A replay pass requires semantic invariants and a witnessed comparison, not only equal digests. The
digest should be described as “same declared inputs and implementation produced the same declared
output,” never as “history was reproduced.”

## SQLite: appropriate hypothesis, dangerous promise

SQLite plus immutable external blobs is a reasonable first local hypothesis. The packet sometimes
speaks as if “single writer + WAL + `synchronous=FULL`” settles durability and capacity. It does
not.

### Durability assumptions to attack

- The SQLite version used by the application binding may differ from the CLI version inspected on
  the machine. The WAL-reset fix cited in lane 15 must be verified through each actual runtime,
  native library, and packaged artifact.
- `FULL` defines SQLite behavior through the VFS; power-loss persistence still depends on the
  filesystem, drive/cache behavior, platform sync primitives, and whether the benchmark exercises
  them.
- A database row and an external blob rename do not form one atomic transaction. Every crash point
  between blob write, file sync, directory entry, database append, cursor commit, and garbage
  collection needs an explicit recoverable state.
- One logical writer can still be a queue bottleneck, priority inversion point, or single failure
  domain. It can hide contention in the process interface rather than eliminate it.
- Long readers and checkpoints can grow WAL files and change latency. Backups, migrations,
  projection rebuilds, antivirus/indexing, low disk, and UI queries must run during the capacity
  test.
- Content-addressed retention and immutable backups conflict with hard erasure unless references,
  encrypted keys, replicas, manifests, and derived extracts participate in deletion.
- SQLite can store an enormous database; that does not imply acceptable restore time, corruption
  blast radius, migration time, or human inspectability at the proposed retention volume.

### How a SQLite benchmark can win dishonestly

- use an empty or tiny database, warm page cache, and uniform short rows;
- benchmark on a temporary or unusually fast filesystem;
- switch from `FULL` to `NORMAL`, group commits more aggressively, or omit directory/blob sync;
- exclude concurrent readers, checkpoints, indexes, backup, and projection work;
- report rows per second without source bytes, index bytes, WAL high-water, or p99/p99.9 latency;
- generate one million valid rows while omitting large, malformed, duplicated, reordered, and
  conflicting payloads;
- stop before the WAL, database, APFS free-space pressure, or rational/index growth reaches steady
  state;
- measure replay after caches are populated and omit cold restart/recovery; or
- test only the database while blob staging, Parquet export, and cursor commits happen in no-op
  mocks.

The pass must use the actual runtime binding and production settings on the actual filesystem,
with the measured event-size/failure distribution, cold and warm runs, deliberate crashes, readers,
checkpointing, backup, low-disk reserve, and all bytes counted. If that passes the earned workload,
SQLite wins because it is boring and sufficient—not because its published limits are large.

## Data-cost arithmetic can be correct and still answer the wrong question

Lane 22 materially improves the packet by using measured rates: 1,552 raw messages/s, 238.9 GB/day
of raw input, 327 successful rows/s, and a 2.3–7.1 GB/day compact planning range. It also shows why
the full stream is not an August requirement. The remaining risk is denominator substitution in
cost accounting.

The storage bill is not `compact_row_bytes × successful_rows`. The complete measured quantity is:

```text
retained raw/source envelopes
+ observation and provenance records
+ database pages and indexes
+ WAL/checkpoint high-water
+ external blobs and thumbnails/redactions
+ Parquet overlap and manifests
+ backup/replica copies
+ migration/rebuild scratch space
+ logs, rejected payloads, and deterministic failure samples
+ encryption/key/deletion metadata
```

Network cost similarly includes reconnect overlap, backfill, HTTP headers and unchanged polls,
failed messages needed for coverage, provider billing on uncompressed bytes, and duplicate source
paths used for conformance. Social/media/LLM work has different unit economics and must not inherit
the chain-tape estimate.

At the stated compact range, 90 days of successful-event rows alone is roughly 207–636 GB before
the additions above. That is already incompatible with treating the current 634 GiB free-space
number as comfortable, especially when lane 22 proposes a 300 GiB reserve. A 50-byte reducer floor
is a measurement of one reducer, not a retention plan.

The financial denominator should also be **cost per useful covered decision or experiment**, not
cost per event. A cheap firehose that Ember does not use is expensive. A $0 local collector that
consumes a week of integration time or makes the machine an unreliable daily instrument is not
free. Report at least:

- incremental cash and native-unit burn;
- local disk and backup runway under measured amplification;
- operator and engineering hours;
- covered versus gapped time for the exact selected loop;
- useful candidate/scene yield;
- cost per consequential scene and per retained control observation; and
- the degradation artifact when the budget is exhausted.

Provider list prices should not enter the architecture as assumed availability. Taxes, existing
quota contention, automatic overage, renewal, plan limits, and cancellation degradation are part of
the experiment. The $0 pre-September default is the correct one.

## UI companion risk is not just an adapter problem

The UI lanes understand that Pump parity is unresolved. The remaining optimism is the belief that a
local, origin-scoped companion can be treated mainly as a technical shell choice.

It is also a legal, privacy, scientific, and supply-chain decision:

- user visibility and user consent do not create permission to continuously copy a platform,
  other users' content, ranking, private session state, or intellectual property;
- a host permission can expose much more than the intended card fields, and a later extension
  update can widen behavior without changing the product concept;
- screenshots and DOM fragments may contain wallet balances, notifications, identities, deleted
  material, livestreams, sexual or abusive content, and third-party copyrighted media;
- joining public wallets to handles, follows, dispositions, and Ember's notes produces a sensitive
  behavioral dossier even when every component was individually public;
- immutable content addressing, screenshots, backups, model prompts, and research extracts make
  deletion much harder than removing one database row;
- canvas rendering, virtualized rows, personalization, feature flags, moderation, focus, and
  below-fold serving can make a visually faithful capture scientifically incomplete;
- extension failure can be silent: a selector still returns rows while badges, order, or hidden
  filters change meaning;
- a companion changes the operator's sensorium and gesture costs, so “Ember used it” measures a
  new composite policy rather than a neutral recording of the old one; and
- local processing reduces exfiltration risk but does not resolve platform terms, authors' rights,
  retention duties, or re-identification.

The exact capture operation needs a human access/privacy decision before automated testing. An
engineering author cannot self-certify it by citing CORS, `robots.txt`, public visibility, an
anonymous response, or an origin allowlist. If that review is unresolved, manual exact-mint entry
or a narrowly deliberate app-window capture is a separate lower-capability candidate, not a
temporary implementation of continuous DOM access.

UI fidelity also needs a hostile bakeoff. A browser/PWA can appear to win by testing only a focused,
foreground Chrome session on the development machine. A Tauri or Electron shell can appear to win
by counting packaging as capability while ignoring update/security burden. A companion can appear
to pass on one account, locale, viewport, feature flag, and DOM version. Test background/suspend,
zoom, resize, virtualized lists, stale tabs, route changes, missing images, hostile content,
selector drift, and a fixture in which the extension returns plausible but wrong order.

“Zero mis-targeting” over a tiny friendly fixture is not a safety claim. It is one observation.

## AI-agent code quality and correlated confidence

The packet's task-packet and path-ownership discipline is good. It does not neutralize the fact
that agents share priors, examples, SDKs, generated schemas, and the accepted vocabulary. Several
agents can independently produce the same plausible semantic error.

Specific failure modes are:

- the agent copies operation order from the SDK into both production and oracle paths;
- a generated contract makes the same wrong field mandatory in every language;
- an adapter compiles but maps a provider identifier to the wrong canonical identity;
- a property test generates only states admitted by the implementation's own validator;
- an agent repairs the fixture rather than the code when a favored architecture fails;
- broad “cleanup” removes explicit unknown variants or source provenance as boilerplate;
- a UI snapshot looks correct while the lineage or as-known cutoff is wrong;
- two agents implement against slightly different semantic drafts and the integrator resolves the
  conflict by making fields optional;
- code review becomes test-output review because the generated diff is too large; and
- high agent throughput overwhelms Ember's ability to inspect the one path whose meaning matters.

Agent familiarity must be measured with two phases: initial construction and an unannounced later
semantic change. The second is often more diagnostic. Require independent, raw-byte holdout
fixtures and mutation tests written from failure hypotheses, not from implementation branches. The
same agent should not define a high-consequence contract, implement it, author its goldens, and
declare the adversarial review complete.

Compiler/test catch counts are especially easy to misuse. A compiler only earns credit when the
planted defect represents a realistic mistake, the candidate's normal implementation would have
admitted it, and the failure occurs before a human or shared conformance test would have caught it.
Five variations of the same language-specific mismatch do not count as five independent safety
wins.

## September urgency can corrupt scope while preserving the date

Lane 24 correctly says profit is not schedulable and that a failed gate may produce a smaller
artifact. Its 3–6 day companion core and August 20–29 targets are nevertheless optimistic when
expanded to exact reconciliation, a genuine chart, size-specific quotes, scene capture, replay,
source health, source access, and natural-use validation.

The likely deadline failure is not reckless live execution; the packet strongly resists that. It
is **substitution**:

- mark instead of size-specific quote;
- current wallet balance instead of reconciled economic effect;
- familiar public feed instead of the actual Pump choice surface;
- deterministic reconstruction instead of witnessed replay;
- present metadata instead of as-known metadata;
- screenshot instead of served set;
- agent/demo use instead of voluntary operator use;
- happy-path fixture instead of source recovery; or
- a list of implemented modules instead of one completed operator path.

Dates should collapse scope, never lower semantic gates. If R2 cannot include quote provenance, it
ships exact quantity plus explicit `unquotable`; it does not show a mark as liquidation. If source
review is unresolved, the product stays exact-mint/manual and drops parity. If witnessed replay is
not recognizable, the output is an append-only notebook prototype, not a replay system.

September should also not influence the permanent language choice. A Python spike may be fastest
without being the core; a Rust core may be durable without belonging on the two-week critical path.
The date decides how little to build, not which long-term architecture gets a waiver.

## Non-gameable decision rules

No experimental procedure is perfectly game-proof, but the following rules make favoritism and
self-deception expensive and visible.

### Rule 1 — admissibility precedes architecture

Before a permanent runtime, store, or companion decision, freeze one exact operator path and its
admissible sources. If Pump access/terms or source fidelity remains unresolved, only disposable
probes, manual exact-mint work, and source-neutral fixtures may proceed. A language cannot win by
building capabilities the selected mode is not allowed to use.

### Rule 2 — hard semantic gates precede weighted preference

A candidate first passes exact amounts/units, missingness, raw preservation, crash recovery,
as-known cutoff, keyless capability, and source-gap visibility. A hard-gate failure cannot be
averaged away by speed, aesthetics, ecosystem, or future authority. Weighted scoring is used only
among candidates that pass the same declared scope.

### Rule 3 — freeze the contest before results

Commit the task, raw fixtures, holdout hash, failure injections, production settings, machine
budget, dependency policy, time budget, scorer, and tie/default rule before implementation. Any
post-reveal change is logged, offered to all candidates under the same additional budget, and
reported rather than folded silently into the final run.

### Rule 4 — identical raw input and end-to-end boundary

Every contender starts from identical raw bytes and ends at the same user-visible/serialized
artifact. Candidate-specific normalization, SDK sidecars, generated bindings, FFI, Node runners,
storage shims, and process supervisors count in its total. A pure oracle may compete as an oracle,
not as an application core.

### Rule 5 — counterbalance people and agents

Use the same task packet, context, tool access, time, and repair policy. If possible, cross over the
implementer/agent order so the favored language is not always attempted first or by its expert.
Blind the semantic artifact review to the implementation where practical. Record all attempts and
do not cherry-pick the best transcript or run.

### Rule 6 — correctness evidence has independent ancestry

Classify every oracle by source ancestry. SDK descendants count once. Require at least small
hand-derived vectors and finalized controlled-boundary effects independent of the production
implementation. Do not majority-vote mismatches. Preserve every disagreement and resolution.

### Rule 7 — benchmark the production claim, not a flattering kernel

Use the actual runtime binding, filesystem, sync mode, blob protocol, readers, indexes, backup,
checkpoint, queue, and measured payload distribution. Report cold and warm performance, every run,
variance, bytes at every layer, p50/p95/p99/p99.9, backlog age, recovery time, and failure count.
Exclude no sidecar or setup cost needed by the claim.

### Rule 8 — changeability is part of the bakeoff

After initial completion, introduce one source-schema drift, one new missingness variant, one
accounting correction, and one crash case. Measure semantic locality, defects, migration/replay
impact, and Ember's ability to understand the diff. Initial LOC and first-demo time do not decide
the durable core alone.

### Rule 9 — natural use is a veto, not a score

No amount of replay rigor or architectural elegance rescues a cockpit Ember repeatedly leaves for
material context. Voluntary use of the exact path is assessed separately from implementation
quality. The apparatus may survive as an exposure tool, but it cannot claim to instrument the full
attention funnel.

### Rule 10 — uncertainty narrows the claim

Unsupported variants, unobservable ranks, stale quotes, incomplete history, or legal uncertainty
do not receive proxy values. They narrow the mode and displayed claim. A candidate never wins by
rendering more fields from weaker evidence.

### Rule 11 — the default is smaller, not “no decision”

Predeclare the fallback if no candidate wins decisively: retain the language-neutral fixtures,
source dossier, and useful exact-mint/exposure artifact; choose the smallest reversible runtime for
the currently earned read-only path; defer the permanent core decision. Do not respond to a tie by
building both candidates or adding an abstraction layer.

### Rule 12 — September changes the feature set only

At each date, unfinished features are dropped in the order: packaging/polish, extra sources,
history completeness, discovery breadth, shadow models. Exact quantity, honest unknowns, source
health, no-key/no-send, and claim labeling are never dropped. There is no date-based exception to
an access, privacy, or correctness gate.

## Stop conditions and the artifacts they preserve

Stopping should terminate an unjustified claim, not erase the useful evidence already earned.

| condition | stop or narrow | preserve |
| --- | --- | --- |
| the material Pump surface cannot be lawfully/stably observed, and no reviewed companion method preserves it | stop replacement/parity work; choose exact-mint or on-chain observatory only if naturally useful | field-level source/access dossier, manual workflow traces, public-chain decoder fixtures |
| Ember repeatedly returns to Pump/Padre for material context or capture changes the decision rhythm | stop claiming a natural attention instrument; do not add more telemetry to force use | exposure rail, exact-mint workbench, scene/notebook export, omission list |
| size-specific quote error, age, fees, and latency are of the same order as the proposed micro-profit hurdle | stop shadow crackle and any progression toward automation at that scale | quote conformance corpus, hurdle report, wallet/exposure tool |
| wallet effects cannot reconcile without inventing basis, intent, or fee allocation | stop PnL/strategy claims; display exact current quantities and named residuals only | raw transaction/account fixtures, unresolved-classification ledger, current liquidation view |
| SQLite fails production-setting crash, restore, latency, or 90-day reserve gates | stop store promotion; narrow retention or compare one alternative against the same fixture | immutable segments/blobs, manifests, store benchmark, replay corpus |
| no runtime candidate passes hard gates in the fixed timebox | stop the permanent language selection and delete throwaway branches after extracting vectors | canonical contract, walking fixture, mismatch report, smallest disposable read-only path |
| two candidates pass but no material difference survives the change task | choose the simpler existing operational path; do not keep both | blind review, measured tradeoffs, rejected-candidate notes |
| the conformance suite agrees only through shared SDK/generated ancestry | stop calling it independent assurance | raw bytes, ancestry map, mismatches, manually derived boundary vectors |
| replay digests match but witnessed scenes or as-known availability do not | stop causal/replay claims; relabel as deterministic reconstruction | raw scene artifacts, clocks, renderer diff, corrected replay specification |
| data amplification, provider burn, operator time, or upkeep exceeds its declared cap | stop the relevant source/fidelity tier and record a gap; never auto-upgrade | compact denominator, coverage/budget ledger, sampled raw evidence, cost report |
| privacy/access review requires broad credentials, continuous interception, unclear retention, or a contested purpose | stop that companion mechanism | manual capture protocol, data inventory, deletion design, exact-mint workflow |
| AI changes repeatedly pass tests but fail raw-byte holdouts or semantic review | stop agent parallelism and reduce task/code surface; do not add more test-generated confidence | minimized counterexamples, task packets, human-reviewed core fixture |
| the pre-September path misses its date | ship the smallest truthful completed artifact; do not fill unknowns or widen authority | D0 source dossier, D1 exposure truth, or D2 notebook—whichever actually passed |
| the system requires live money to demonstrate product value | stop the engineering claim and remain read-only | query-only feasibility report and prospective observational corpus |

Three consecutive natural-use failures for the same named omission should trigger a mode decision,
not an open-ended UI sprint. A source or runtime may be revisited only after new evidence changes
the failed premise.

## The useful minimum that survives every architecture loss

If Pump parity fails, every strategy family is unprofitable, SQLite is replaced, and the language
bakeoff is inconclusive, the project can still leave a valuable compostable core:

1. a dated field-level source/access and privacy matrix;
2. a small corpus of raw public-chain and operator-owned evidence with provenance;
3. exact current controlled-wallet quantities and named reconciliation gaps;
4. size-specific quote/conformance vectors and explicit unquotability;
5. three runner fixtures and one exit–flat–re-entry episode fixture;
6. one append-only scene/gesture record with a recognizable witnessed view;
7. SDK ancestry and protocol mismatch reports;
8. a measured storage/cost/recovery report; and
9. language-neutral adversarial fixtures for the next implementation.

That artifact is not a failed trading bot. It is a truthful exposure instrument and a much better
starting point for deciding whether a larger project deserves to exist.

## Final recommendation to the synthesis

Do not select the union of lanes 13–24. Select an uncertainty order.

1. Finish Spike 0 as an access/fidelity/product decision using normal Ember sessions.
2. Build only the exact-mint exposure path that remains useful under every source-mode outcome.
3. Preserve raw evidence, gaps, exact asset effects, current quote provenance, one scene, and the
   no-key/no-send boundary.
4. Run one pre-registered walking-fixture bakeoff only after that path is concrete. Compare at most
   the leading durable candidate and one serious challenger; treat oracle languages as oracles.
5. Adopt SQLite only after the actual binding, filesystem, blob protocol, cost amplification, and
   crash/restore workload pass.
6. Add a Pump companion only after the exact operation clears access/privacy review and a hostile
   fidelity trial.
7. Treat the research environment, broad streams, formal models, extra runtime, generated contract
   system, desktop packaging, and R5+ authority as later purchases from demonstrated value.

The project is not foolish because it may fail to prove profitable strategies. It would be
foolish only if engineering prestige made it expensive to learn that fact. The right V2 earns
complexity one operator-visible uncertainty at a time and remains worth keeping when any trading
hypothesis fails.
