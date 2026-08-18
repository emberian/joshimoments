# Engineering lane 23 — developer experience, repository shape, and semantic stewardship

Status: pre-engineering design. This document proposes how engineering should feel and remain
trustworthy after the operating mode and Slice 1 architecture are approved. It does not authorize
an application scaffold, collector, database, transaction builder, key, signer, submission path,
or dependency purchase.

## Outcome

Joshi should begin as one small monorepo containing a modular local application, exact contracts,
high-value fixtures, and the documents that explain why the code means what it means. It should
not begin as a collection of services or language-specific kingdoms.

The development experience should make the honest path the easy path:

- one command shows whether the machine is ready;
- one command runs an entirely offline representative system;
- one command starts the approved local read-only slice;
- every module says what facts it owns, what it may derive, and what it must not do;
- persisted and cross-process contracts have one source, generated bindings, and executable test
  vectors;
- a source event can be traced from raw observation through assertion, projection, scene, and UI;
- schema and meaning changes leave migrations and decisions rather than archaeological layers;
- AI agents receive small path-owned tasks with named invariants and deterministic checks;
- the repository does not require the 74+ GiB `joshibot` estate, a cloud account, or a wallet key
  to build and test.

The preferred topology is a **modular monolith with a TypeScript browser surface and one primary
core runtime**. The wave-2 engineering lanes currently disagree about that runtime: lane 13
recommends Rust, lane 14 recommends Python for the first local core, and lane 20 recommends Rust as
the single numerical/accounting authority with an OCaml reference model. That disagreement is not
papered over here. It should be resolved by the root architecture decision and a representative
bake-off after Spike 0. Developer experience is one of the decision criteria, not a language choice
hidden inside this document.

The purpose of good DX here is not maximizing generated lines per hour. It is maintaining enough
clarity that Ember and an AI collaborator can change the system quickly without accidentally
changing the object being measured.

## Ground truth and constraints

The current development host is Apple arm64 macOS 26.6.1 with 96 GiB RAM. It already has OCaml
5.0.0/Dune 3.14, .NET 10.0.301, Rust nightly 1.98, Node 26, Python 3.14 with `uv`, Julia 1.12, and
Docker. These are useful options, not a requirement that Joshi exercise every installed runtime.
Project-local toolchain declarations and lockfiles remain authoritative over ambient versions.

The legacy estate is roughly 164,000 lines of Python, 9,400 lines of TypeScript/TSX, 1,900 lines of
Lean, 61 Markdown documents, and more than 74 GiB of data, studies, and state. Fresh Joshi must not:

- import `joshibot` as a runtime dependency;
- add that data tree to the repository or make ordinary tests depend on its absolute path;
- choose Python, TypeScript, C#, Lean, or any prior split merely because old code exists;
- migrate old databases or runtime state wholesale;
- treat an old generated schema, strategy type, or study conclusion as a new domain contract.

The accepted foundation further constrains the engineering shape:

- the current system is R0–R4 and system-read-only;
- observations, assertions, derivations, the financial ledger, scenes, and future authority
  journals are different objects;
- operator episode and inventory epoch are different identities;
- witnessed, knowledge-cutoff, and retrospective replay are different products;
- exact amounts, clocks, missingness, coverage, and source provenance are load-bearing;
- physical schema, storage, frontend framework, and final language split remain deferred until
  Spike 0 chooses an operating mode and the Slice 1 review approves them.

This lane therefore designs the stewardship rules first and presents a candidate skeleton only
after naming the decisions that must precede it.

## Decision summary

1. Use a monorepo through R4 and likely R5. A second repository is earned by a real authority,
   release, or access boundary—not by a second language.
2. Begin with a modular monolith: one local application runtime plus a browser UI if the approved
   product needs one. Collectors and reducers are modules or supervised processes, not services by
   default.
3. Keep the semantic core pure, storage-agnostic, network-free, and dependency-light. Adapters own
   source and vendor peculiarities.
4. Make persisted or inter-process schemas explicit contracts with one canonical definition,
   generated bindings, and language-neutral test vectors. Do not create a general contract language
   before there is a real second consumer.
5. Give every module a named owner, public boundary, allowed dependencies, invariants, and local
   test command. Avoid `common`, `utils`, and database tables as de facto ownership.
6. Pin every selected toolchain and dependency. Reproducibility means a clean machine can build and
   replay the committed fixture without network-dependent tests or hidden local data.
7. Put large, sensitive, mutable, and historical corpora outside Git behind content-addressed data
   manifests. Keep small semantic, protocol, and adversarial fixtures in Git.
8. Treat migrations as semantic artifacts. Raw observations are never rewritten to make a new
   projection convenient; derived state is preferably rebuilt.
9. Make structured local observability and lineage inspection part of the development loop, not a
   production afterthought.
10. Optimize for one primary production runtime plus TypeScript where a web UI requires it. Add a
    language only when its boundary is smaller than the complexity it removes.

## Relationship to the other engineering candidates

This lane treats the other wave-2 documents as proposals rather than accepted architecture:

- lane 13's Rust + React/TypeScript recommendation has the strongest official protocol,
  exact-numeric, Arrow/Parquet, and eventual authority fit;
- lane 14's Python core + selective Node runners has the lowest initial ceremony and a direct route
  from source probes to a local one-writer application;
- lane 15's SQLite + content-addressed blobs + manifested Parquet + ephemeral DuckDB proposal is the
  most concrete storage hypothesis and fits either runtime if its exact library behavior passes the
  platform checks;
- lane 19 deliberately makes the deterministic laboratory language-neutral;
- lane 20 argues that even if the application shell is not Rust, financial calculations should
  have one Rust executable meaning plus an independent OCaml oracle.
- lane 22 shows why the development environment must default to bounded tapes rather than a live
  firehose: the old stack measured 1,552 raw notifications/s and 238.9 GB/day of ingress, while
  even its compact successful-event floor was about 1.4 GB/day. Load and recovery work therefore
  needs named, opt-in profiles rather than hiding inside ordinary startup or CI.

The root synthesis must decide whether “one primary runtime” means the complete read-only core or
whether the numeric kernel earns a narrow second runtime immediately. A Rust numeric subprocess
inside a Python application may be safer arithmetically but worse operationally than a Rust core;
duplicating all accounting in Python and Rust would be worse than either. The DX recommendation is
to select one production owner per semantic fact and use reference implementations only in tests.

Do not scaffold around all candidate architectures while the disagreement is open. Contracts,
fixtures, and the walking scenario are the portable work; service/package directories are not.

## Repository topology: monorepo first

### Why one repository fits the present project

Most early changes cross the exact seams that must remain coherent. Adding a clock to an evidence
record may require a contract update, reducer change, replay fixture, UI freshness state, migration,
and decision note. A monorepo permits one reviewed change to carry all of those together.

It also serves AI-assisted development unusually well:

- a task can cite one commit containing contract, implementation, fixture, and documentation;
- code search sees the complete semantic dependency graph;
- generated bindings cannot drift across invisible version pins;
- the integration agent can run one root check rather than assemble several repositories;
- refactors can remain atomic without publishing placeholder packages;
- source and product versions embedded in scene manifests can derive from one repository state.

A monorepo does **not** mean every package may import every other package. It needs a stricter
dependency graph precisely because filesystem proximity makes accidental coupling easy.

### When another repository becomes justified

Split only when at least one of these becomes true:

1. The R6+ signer has a separately audited lifecycle, access policy, release authority, or machine
   boundary whose source visibility and dependency graph should be narrower than the observational
   product.
2. A protocol/contract package has an independent release cadence and real external consumers.
3. A private corpus or model has access restrictions materially different from the application
   source. Usually the data should split, not the code.
4. A component must be deployable and supported independently, and keeping it atomic with the
   monorepo has produced measured release friction.
5. Licensing makes co-location or distribution inappropriate.

“It is Rust,” “another agent owns it,” “it might scale,” and “microservices are cleaner” are not
split conditions. If a signer later leaves the repo, its exact wire contracts and conformance
vectors remain versioned on both sides, and compatibility is tested before either release.

## Logical architecture and dependency direction

The first approved application should be a modular monolith with ports and adapters, not a generic
platform. Its logical dependency direction is:

```text
semantic value types and transition rules
                   ^
                   |
evidence/accounting/replay reducers       persisted wire contracts
                   ^                               ^
                   |                               |
application use cases and query views ------------+
                   ^
                   |
source, storage, quote, wallet, and UI adapters
```

The semantic core knows no HTTP client, RPC provider, SQL table, browser component, clock singleton,
or SDK object. It receives explicit values and returns values, decisions, or typed failures.

Adapters depend inward. They translate:

- a Pump/Solana/provider payload into an observation and source-specific assertion candidate;
- storage rows into domain values without making storage the domain model;
- domain query views into UI wire values;
- operator commands into persisted operator records;
- query-only SDK results into exact quote artifacts.

Application code coordinates those ports. It does not contain a second copy of fee math,
missingness rules, episode semantics, or evidence identity.

### Module ownership contract

Every top-level module should contain a short `README.md` answering:

- What concept does this module own?
- What facts may it accept as inputs, and from which layer?
- What records or values may it produce?
- Which modules may it depend on?
- Which semantic invariants must always hold?
- Which failures are expected and how are they represented?
- Which data may it persist?
- What is explicitly outside its authority?
- What one command exercises its contract?

The README is not a design essay. It is the local map an Ember or AI reviewer reads before touching
the module. The accepted ADR or foundation document remains the normative source for cross-project
meaning.

Suggested ownership principles:

| concern | owner | may not own |
| --- | --- | --- |
| evidence identity, clocks, coverage, blob references | evidence core | Pump-specific field meanings, episode policy |
| source decoding | one source adapter | canonical identity, strategy decision, ledger truth |
| episode/stance/operator transitions | operator semantics | wallet balances or inferred fills |
| asset deltas, lots, basis quality, inventory epochs | accounting core | episode resolution or chart marks |
| scene manifests and replay cutoffs | replay core | source acquisition or mutable UI state |
| quote artifact and exact arithmetic | quote domain + venue adapter | portfolio decision or fill claim |
| UI view and gestures | cockpit application | raw-source mutation, hidden interpretation, direct wallet action |
| studies and models | research consumers | canonical facts, source writes, action authority |

No module named `common`, `shared`, `helpers`, or `utils` may become a dumping ground. Small generic
functions either belong with the concept that gives them meaning or in a deliberately tiny
foundation package with a named reason for existence.

### Schema ownership

Schemas are owned by the concept, not by the database or the first language that serialized it.

- The evidence module owns the observation envelope and coverage contract.
- The operator module owns gesture and episode-transition contracts.
- Accounting owns asset-delta, lot, basis-quality, and inventory-epoch contracts.
- Replay owns scene manifests and replay request/result contracts.
- Each adapter owns its raw provider payload preservation and source-specific decoded assertion.
- A UI query projection is owned by the application use case that promises it, not promoted to a
  universal domain schema.

Persisted schemas and in-memory types need not be identical. A storage schema may denormalize for
queries, but it must cite which reducer/version produced it and must be disposable where the
foundation calls it a projection.

Schema changes receive three labels:

- **additive representation change:** old meaning remains; a field or variant is added;
- **interpretation change:** the same evidence is decoded or reduced differently and needs a new
  assertion/projection version;
- **semantic correction:** a prior contract was wrong and requires an ADR, migration/rebuild plan,
  replay diff, and explicit affected claims.

Calling all three “migration” hides the scientific consequence.

## Contracts and generated bindings

### What earns a formal wire contract

A type becomes a contract when it is persisted durably, crosses a process/language boundary,
appears in a scene manifest, or must remain readable after the implementation type changes. Local
private function arguments do not need an IDL.

The first single-runtime slice should not invent Protobuf, JSON Schema, OpenAPI, Cap'n Proto, and a
code generator at once. Use the primary language's explicit runtime-validated schema for its first
private boundary, plus canonical JSON/test vectors where long-term readability matters. Introduce
a language-neutral schema source only when a second implementation or durable compatibility need
is real.

When that need exists, the contract source must express or document:

- exact integers and units; no JSON floating-point money;
- tagged variants rather than magic strings;
- absent, known absent, unknown, stale, censored, errored, and not applicable where relevant;
- every clock's authority and precision;
- version, producer, and source/evidence identifiers;
- forward handling of unknown variants;
- canonical test vectors and expected validation failures.

Choose the schema technology by this representational test, not by which generator has the most
logos. Protobuf's wire discipline, JSON Schema's inspectability, or a small hand-specified canonical
JSON contract may each win for a particular boundary. The contract ADR records the tradeoff.

### Generation discipline

- One file or package is authoritative for each generated contract. Never generate A from B and B
  from A.
- Generated files carry source path, source digest, generator name/version, and a “do not edit”
  header.
- Generation is deterministic and part of the root check. A clean checkout must not produce an
  unexplained diff.
- Handwritten convenience types wrap generated types; they do not fork them.
- Contract fixtures are language-neutral. Every binding must accept and reject the same vectors.
- Official Pump/PumpSwap/Meteora IDLs and SDKs are pinned external inputs. Preserve their version
  and digest; generate thin adapters, not a locally edited fork of vendor output.
- Commit generated code only when it makes consumer builds independent of unavailable tooling or
  makes protocol diffs reviewable. Otherwise generate into ignored build output. Apply one policy
  per artifact class rather than deciding file by file.
- Review the source contract and semantic fixture diff first. Generated volume must appear in a
  separate review section or commit so it cannot hide handwritten changes.

Generated bindings are not the semantic source of truth. A perfectly generated `creator_claimed:
bool` would still be the wrong contract.

## ADRs and architectural memory

Accepted project semantics live in `docs/decisions/`. Engineering decisions should use numbered
ADRs under `docs/decisions/adr/` once implementation is authorized.

An ADR should contain:

```text
status and date
decision owner
context and observed constraint
decision
alternatives actually considered
semantic or authority invariants affected
consequences and operational burden
reversibility / migration path
evidence or benchmark that would trigger reconsideration
links to contracts, fixtures, and superseded decisions
```

Write an ADR for choices that constrain multiple modules, persist data, add a runtime, widen
authority, establish a contract source, or are expensive to reverse. Do not write one for every
minor library, CSS choice, or internal refactor.

ADRs append and supersede; they are not edited into a history in which the team was always right.
If the rationale changes, add a note or successor. An AI agent may draft an ADR, but Ember owns
acceptance of normative semantics and any capability change.

## Language and runtime strategy

### The governing rule

Use the fewest runtime languages that make the code pleasant and the boundaries honest. A language
earns a place when it materially improves one of:

- source/protocol ecosystem fit;
- semantic clarity and invalid-state exclusion;
- measured throughput or latency;
- formal assurance at an authority boundary;
- Ember's willingness to read, refine, and enjoy the core code.

It does not earn a place merely because an AI can emit it or because the toolchain is already
installed.

### TypeScript

**Best fit:** cockpit UI, browser-local interaction, official JavaScript SDK integration, and a
small Node local application when throughput is modest.

**Advantages:** the shortest boundary between UI, Pump/PumpSwap/Meteora SDKs, runtime validation,
and local query APIs; very strong AI familiarity; easy shared view types; fast iteration.

**Risks:** structural typing can admit accidental lookalikes; `number` is unacceptable for raw
monetary/state quantities; JSON parsing invites unvalidated casts; npm dependency breadth and
post-install behavior can become a supply-chain and reproducibility cost; large React components
are especially easy for agents to make superficially correct and semantically tangled.

**Required discipline if selected:** strict compiler settings, `bigint` or explicitly encoded
integer types, runtime validation at every external boundary, branded identifiers/units, exhaustive
tagged unions, pure reducers, no `as unknown as`, and small UI view models distinct from domain
records.

TypeScript is the default browser hypothesis and a useful minimal-stack challenger because it can
minimize integration boundaries. It should not be presumed to own accounting, replay, or numerical
truth: lanes 13 and 20 make a substantive Rust case that the root synthesis must answer.

### Rust

**Best fit:** exact protocol decoding, high-rate event processing after measurement, content-
addressed storage primitives, and later transaction validation/authority containment.

**Advantages:** strong algebraic types, integer discipline, explicit ownership/concurrency, mature
Solana ecosystem, good property-testing support, portable single binaries, and compiler pressure
against broad classes of invalid states.

**Risks:** it introduces a process or FFI boundary beside the TypeScript UI; compile/link cycles and
generic error surfaces can slow the exploratory product loop; AI agents often “solve” ownership
friction with cloning, interior mutability, or overgeneralized traits; nightly pinning adds update
cost and should not be inherited merely because nightly 1.98 is installed.

Lanes 13 and 20 make Rust the leading durable-core candidate. It should enter early if the root
accepts their protocol/data/numeric argument or the walking fixture demonstrates that its core is
clearer enough to justify the TypeScript boundary. Stable Rust should be preferred unless a named
feature earns nightly.

### OCaml

**Best fit:** a compact pure semantic/replay kernel, executable reference model, sophisticated
state transformations, and code Ember may particularly enjoy inspecting and refining.

**Advantages:** concise algebraic data types and pattern matching, strong module boundaries, fast
native compilation, excellent expression of partial orders and explicit missingness, and a style
that naturally keeps effects at the edge. It aligns well with Ember's formal-methods instincts
without requiring theorem proving.

**Risks:** Pump/Solana/vendor SDK integration is much thinner than in TypeScript or Rust; a web UI
still creates a boundary; current AI models are less reliable about exact OCaml library APIs, Dune
stanzas, opam constraints, and multicore details than about TypeScript/C#/Rust; generated bridge
code can cost more than the semantic elegance saves.

OCaml is a credible candidate for a **small, pure oracle or core** after the contract stabilizes.
It should not become an obligatory second implementation merely to make the architecture feel
formal. If selected, pin OCaml/Dune/opam inputs and make compile/test output the arbiter of AI
suggestions.

### C# / .NET

**Best fit:** a productive local daemon with excellent debugging, structured concurrency,
serialization, SQLite/PostgreSQL access, and long-lived operational code.

**Advantages:** mature tooling, strong AI familiarity, fast incremental builds, clear stack traces,
good profiling, records/pattern matching, and a pleasant application-development loop. A single
self-contained local process is operationally attractive.

**Risks:** current Pump/Meteora ecosystem fit is weaker, which can force a TypeScript or Rust
adapter anyway; domain modeling can drift toward mutable service/DTO layers unless deliberately
functional; adding .NET to a TypeScript UI and protocol adapter may create three worlds before any
one has earned itself.

C# should win only if a representative local-daemon bake-off shows it materially improves Ember's
day-to-day loop. The old C#/Lean/TypeScript proposal has no architectural authority here.

### Python

**Best fit:** disposable source probes, research/export tooling, and—under lane 14's proposal—a
small one-writer local core whose primary objective is reaching truthful product use quickly.

**Advantages:** fastest source and data exploration loop; excellent SQLite/Arrow/Parquet/research
libraries; strong AI familiarity; trivial inspectability; direct reuse of carefully extracted
fixture/parsing knowledge without importing the old architecture.

**Risks:** exact integer units, tagged missingness, exhaustive state transitions, and cross-module
ownership rely more heavily on discipline and runtime validation; async/process topology can become
implicit; Python plus Node SDK runners and a TypeScript browser is already a three-toolchain
operational stack; the 164,000-line legacy estate makes accidental porting especially tempting.

If Python wins the first core, require runtime-validated boundary models, static checking, immutable
domain values, explicit exact-integer wrappers, pure reducers, a single write owner, and no
application imports from notebooks. Its promotion criterion is not “the spike worked”; it is that
the walking fixture, crash/replay suite, and accounting properties remain clearer and faster to
change than the Rust alternative.

Small Spike 0 probes may use Python when it is genuinely the shortest disposable path, but their
outputs and assumptions must be promoted through contracts/fixtures before code is admitted to the
product. The legacy Python volume is neither a point for nor against Python; only new code against
the new contracts is evaluated.

### Julia and research Python

Julia and a separately locked Python research environment are excellent consumers for
chronological studies, plots, notebooks, and model experiments. They consume versioned exports or
query APIs and produce versioned derivations. They do not import application internals, write
canonical evidence, or quietly become the production reducer because a study script happened to
work.

### Lean and formal artifacts

Lean should enter only after a stable, economically important theorem boundary exists—for example,
asset conservation across a finite transition model or authorization monotonicity. Executable
property and state-machine tests come first. A proof that requires maintaining an isomorphic shadow
ontology which the product no longer uses is negative assurance value.

### Recommended language budget

For Slice 1:

- one primary production runtime;
- TypeScript for a web surface if the approved product uses one;
- SQL only as a storage language, not a domain layer;
- a separately locked Python/Julia study environment outside the product dependency graph (even if
  Python is also selected for the core);
- shell only for thin command dispatch, never business logic.

If TypeScript is the primary runtime, this is one runtime, not two. If Rust, Python, OCaml, or C# is
the backend, TypeScript is the second. A protocol runner in another runtime counts as a production
runtime even when it is called a helper. A third production runtime requires an ADR naming the
measured problem it removes.

This preserves enjoyment without turning every edit into a five-toolchain ceremony. The core
question in the bake-off is not “which language is objectively best?” It is “which version will
Ember still want to inspect at 2 a.m., and which one can an agent modify without bypassing its
semantic guardrails?”

## AI-assisted task and ownership discipline

AI agents increase throughput only when their semantic and filesystem authority is narrow. Every
engineering task should be a small **task packet** containing:

- objective stated in domain language;
- why the change exists and which accepted decision governs it;
- explicit files/modules the agent owns for the task;
- contracts it may consume and contracts it may change;
- invariants and authority ceiling;
- non-goals and forbidden shortcuts;
- fixture(s) that demonstrate the case;
- exact check command and expected observable outcome;
- documentation/ADR/migration consequence;
- whether the output is exploratory, generated, or production-candidate.

The default is one agent per disjoint path set. Schema and migration ownership is serialized: one
agent changes a contract, lands or publishes its generated result, then downstream agents adapt.
Two agents should not independently “resolve” the same semantic mismatch in different modules.

For real parallel engineering, use Git worktrees or isolated branches rather than several agents
editing one checkout. Integration happens through a designated owner who reads the diff, runs the
root checks, and resolves semantic conflicts. When a shared-workspace orchestrator is unavoidable,
path ownership becomes strict and broad formatters are prohibited.

Agent handoff belongs in the task/issue or commit, not solely in chat history. A handoff records:

- what changed;
- what was deliberately not changed;
- checks run;
- remaining uncertainty;
- new dependency or generated artifact;
- contract/fixture/ADR links;
- any local data or environment prerequisite.

Useful agent roles are bounded by artifact, not prestige: source-adapter probe, contract/test-vector
author, reducer implementation, UI view, adversarial review, migration review, or integration.
The same agent should not define a security-sensitive contract, implement it, and declare its own
adversarial review complete.

### Agent-friendly code without writing code for agents

Good agent legibility is ordinary good engineering:

- names match the canonical vocabulary;
- effects and dependencies are explicit;
- small modules expose one public purpose;
- exhaustive variants replace stringly switches;
- examples are executable fixtures;
- error messages name evidence IDs, source, and violated invariant;
- root and module commands are discoverable;
- files do not mix generated code, domain logic, SQL, transport, and UI state;
- a failed check explains the semantic mismatch rather than only emitting a snapshot diff.

Do not impose arbitrary line-count limits or atomize coherent logic into dozens of files for model
context windows. A module should be the smallest unit a human can understand as one idea.

## Test data and fixture architecture

### Four fixture classes

1. **Synthetic semantic fixtures in Git.** Tiny hand-readable cases for duplicate observations,
   equal-valued distinct events, unknown basis, partial exit, exact flat, re-entry, hard erasure,
   stale quote, and each missingness variant.
2. **Pinned public protocol fixtures in Git.** Small raw account/transaction/event payloads from
   public chain state with source locator, slot/finality, acquisition date, protocol/IDL digest,
   licence/provenance note, and expected integer decode.
3. **Adversarial/regression fixtures in Git.** Minimal extracts reproducing `joshibot` scars:
   cursor outruns store, parser drift, repeated board row, future metadata leakage, fee omission,
   transfer misclassification, disappeared quote, same-slot ambiguity, and reconstructed versus
   real chart semantics.
4. **External corpora by manifest.** Large tapes, private operator scenes, screenshots, media,
   wallet histories, and the 74+ GiB legacy estate stay outside Git. A manifest names content hash,
   byte size, schema, provenance, retention class, access method, and which optional tests consume
   it.

The default root test uses classes 1–3 and works offline. Corpus tests are explicit, skippable, and
never silently pass because the data path was absent.

Fixtures also have explicit scale profiles: `tiny` for review and semantics, `representative` for
normal replay and migration tests, and externally manifested `capacity` corpora for sustained-load
and crash-recovery gates. The default demo never opens the full program stream or synthesizes its
traffic volume accidentally. A capacity result records the source rate, byte rate, duration,
machine fingerprint, reducer/config digest, gaps, and disk growth so it remains evidence rather
than a developer's recollection that the laptop once kept up.

### Fixture rules

- Tests never depend on `~/dev/joshibot`, a home-directory symlink, current mainnet state, or an
  undocumented developer database.
- Clocks, UUIDs, randomness, source order, and failure injection are controllable inputs.
- No unit or replay test reaches the network. Source contract tests are a separate command with
  recorded cassettes or explicit live credentials.
- Golden outputs are reserved for stable semantic views and witnessed render artifacts. A golden
  change requires a human-readable semantic diff, not “update snapshots.”
- Store exact raw inputs alongside expected decoded/asserted output. A normalized row alone cannot
  test future decoder repair.
- Contract fixtures include expected rejection and unknown-forward-variant cases.
- Protocol math is checked against pinned official SDK/IDL behavior and raw integer vectors.
- Property generators emphasize boundaries: zero, one raw unit, max safe amounts, rounding edges,
  same-slot ordering, partial coverage, and repeated retries.
- The offline crash/replay fixture is a root acceptance test, not a one-off spike artifact.
- Research estimators additionally retain known-zero and planted-effect fixtures, but their
  statistical tests do not become an excuse to couple the app to notebooks.

### Test layers

```text
fast unit/property tests
  -> module contract vectors
  -> deterministic reducer/replay corpus
  -> storage migration/rebuild tests
  -> adapter tests against recorded source payloads
  -> local end-to-end offline scenario
  -> explicit live read-only source probes
```

The root `check` stops before the final live layer. A developer must opt into networked probes and
their costs. No CI result should depend on today's market being active.

## One-command local environment

The repository should expose one stable command entry point, tentatively `./dev`, implemented as a
thin dispatcher after engineering authorization. Contributors should not need to remember whether
the current stack uses pnpm, Dune, Cargo, dotnet, uv, Docker Compose, or a process supervisor.

The command surface should remain small:

```text
./dev doctor       validate platform, pinned toolchains, ports, writable paths, and optional data
./dev demo         run the complete offline fixture with no network or credentials
./dev up           start the approved local read-only application and supervised dependencies
./dev check        formatting, static checks, generation cleanliness, unit/contract/replay tests
./dev test <area>  focused test routing without learning package-manager syntax
./dev replay <id>  reproduce a fixture/scene and print its provenance/digest
./dev migrate      preview and apply approved local migrations/rebuilds
./dev down         stop supervised processes without deleting evidence
```

`./dev demo` is the first-class path: a fresh contributor or agent should see one observation flow
through assertion, projection, scene, and replay without an API key. `./dev up` may use live public
read-only sources only after the relevant slice is approved. It prints the capability ceiling at
startup and must say unambiguously that no construction/signing/submission surface exists.

Startup should:

- validate configuration before starting partial process sets;
- create only disposable local derived state automatically;
- preserve evidence and explain any pending migration;
- show process/source readiness and the exact local URL;
- use loopback or a Unix-domain socket under the accepted security design;
- emit one `run_id` shared across logs and scenes;
- support a deterministic fixture mode using the same application paths as live read-only mode;
- stop cleanly without equating shutdown with transaction cancellation in later phases.

Do not make Docker mandatory for the normal Apple-arm64 edit loop if native processes are faster
and more inspectable. Containers are useful for CI parity and optional dependencies. Likewise, do
not make Nix a prerequisite merely to win the word “hermetic.” The bootstrap experiment should
measure whether a Nix/devcontainer layer reduces or adds real friction for this one-machine-first
project.

## Reproducible and hermetic enough to trust

There are three distinct goals:

1. **Reproducible semantic replay:** same raw fixture, contract versions, reducer/config, and clock
   inputs produce the same canonical output digest. This is mandatory first.
2. **Reproducible development environment:** a clean supported machine installs the declared
   toolchains/dependencies from lockfiles and passes `./dev check`. This is mandatory before Slice
   1 is called portable.
3. **Byte-reproducible release artifact:** independently produced binaries/bundles have identical
   bytes. Valuable later for signer/release assurance, but not a reason to stall the read-only
   cockpit.

Minimum rules:

- pin the primary runtime and package manager in project files;
- commit lockfiles and refuse opportunistic lockfile rewrites;
- pin protocol SDK/IDL versions exactly, without floating semver ranges;
- record generator and formatter versions;
- build CI from a pinned macOS arm64 toolchain path or a documented equivalent, plus Linux where
  server-side portability matters;
- forbid network access in unit/replay tests;
- record a build manifest containing commit, dirty state, toolchain, lockfile digests, contract
  versions, generator versions, and protocol adapter versions;
- inject clocks/randomness and normalize platform-dependent paths in semantic digests;
- make locale, timezone, and numeric conversion explicit;
- never allow local globally installed packages to satisfy undeclared imports.

Per-language pinning, if selected:

- Node: exact Node/package-manager declaration and one workspace lockfile;
- Rust: committed `rust-toolchain.toml` and `Cargo.lock`; stable unless an ADR earns nightly;
- OCaml: locked opam/Dune package universe or a reproducible switch description;
- .NET: `global.json`, centrally managed package versions, and locked restore;
- Python: `pyproject.toml` plus `uv.lock` for research environments;
- Julia: checked-in `Project.toml` and `Manifest.toml` for a study that requires it.

A top-level environment manager may pin these, but it must not duplicate the language lockfiles or
become the only documentation of versions.

## Dependency policy and updates

Dependencies are authority and maintenance surface. Each addition should name:

- which module needs it;
- why the standard library or an existing dependency is insufficient;
- runtime/build/test-only scope;
- licence and source;
- transitive/install-script implications;
- whether it touches raw evidence, network, parsing, cryptography, serialization, or money math;
- replacement/removal path.

Use three update lanes:

### Protocol- and evidence-critical

Pump/PumpSwap/Meteora SDKs and IDLs, Solana transaction libraries, serialization, database drivers,
and schema generators update one at a time. Their update PR includes fixture/conformance replay,
raw integer diffs, unknown-variant review, and an adapter/version note. No automated merge.

### Application and UI

Framework, chart, and ordinary UI packages may be grouped on a scheduled cadence after the root
checks and witnessed-render fixtures pass. A major update receives its own PR. Visual snapshot
churn is not accepted without inspecting the rendered semantic states.

### Development tooling

Linters, formatters, test runners, and type-checkers can be grouped more aggressively, but a
formatter update must be isolated from semantic work. Never let a dependency bot reformat the
repository while changing a protocol adapter.

Security updates can accelerate the cadence, not skip the tests. Lockfile integrity and provenance
are reviewed like source. In the Node ecosystem, lifecycle/post-install scripts deserve explicit
attention rather than assuming the lockfile makes arbitrary install-time code harmless.

Keep an update budget: a small project should not spend every week feeding its toolchain. Pinning is
not abandonment; schedule updates and record why a critical package remains behind.

## Migration and evolution discipline

### Raw evidence

Raw observation blobs and acquisition records are not migrated in place. A corrected decoder writes
new assertions with a producer/version and supersession relation. A retention deletion removes
content through an explicit retention event and prevents stale derived caches from serving it.

### Derived projections

Prefer rebuild-from-evidence over clever in-place mutation. Every projection declares:

- input contract/version range;
- reducer code/config version;
- checkpoint/high-water semantics;
- output schema version;
- canonical digest or reconciliation checks;
- whether it is disposable.

When volume makes a rebuild expensive, use checkpointed expand/backfill/switch/retire migrations,
but validate the new projection against the old on a representative and adversarial corpus.

### Control-plane state

Episodes, operator annotations, retention settings, and manual attribution cannot simply be thrown
away. Their migrations are transactional, append-aware, tested from the last supported snapshot,
and accompanied by a readable before/after report. Destructive or reinterpretive steps require an
ADR and backup/restore rehearsal.

### Database migrations

- Migration files are immutable after landing.
- The application records which migrations and semantic projection versions are active.
- `./dev migrate` previews affected stores and distinguishes schema change from projection rebuild.
- Startup may apply only predeclared safe local changes; it must not hide a destructive migration
  behind “up.”
- Rollback normally means restoring a pre-migration snapshot or selecting the prior projection,
  not pretending every data transformation has a trustworthy inverse.
- Tests open the previous supported fixture database, migrate it, replay representative scenes,
  and reconcile quantities/digests.

Schema compatibility is not sufficient if meaning changed. A column can retain its name and still
require a new derivation version.

## Development observability and inspectability

The product is an evidence instrument; developers need to see its evidence path while changing it.
Local development should expose:

- structured logs with human-readable pretty mode and a stable machine format;
- `run_id`, observation ID, source event key, episode ID, scene ID, assertion/derivation version,
  and source watermarks where relevant;
- source health, last receipt/event, gap intervals, queue depth, reducer checkpoint, replay lag,
  and storage write failures;
- a lineage inspector from displayed value back to assertion, raw observation/blob, producer, and
  clocks;
- a scene inspector showing rendered versus available data and the reason for every unavailable or
  stale field;
- an accounting inspector that shows exact deltas, classification, basis quality, and unresolved
  residuals;
- fault injection for duplicates, reordering, parser drift, source silence, clock skew, disk
  failure, and late backfill;
- deterministic trace export attached to a bug report without exporting secrets or unrelated
  operator data.

Start with structured events and a local debug surface. OpenTelemetry-compatible traces may be a
later adapter; an external observability SaaS is neither required nor permitted to receive private
operator/portfolio data by default.

Error design is part of DX. An error should say:

```text
what failed
which source/record/module was involved
what remains trustworthy
what state is now unknown or blocked
which correlation ID reproduces it
the safe next command
```

“Something went wrong” and a stack trace are not evidence health.

## Code review and integration

Review order should follow risk:

1. Does this change the meaning of a persisted fact, choice denominator, episode, PnL, identity,
   quote, or replay cutoff?
2. Does it widen network, filesystem, data-retention, model, or transaction authority?
3. Are source gaps, unknown variants, and failures preserved?
4. Does the contract and migration match the accepted decision?
5. Do fixtures demonstrate both the normal case and the relevant counterexample?
6. Is the implementation clear, local, and mechanically appropriate?
7. Are generated and dependency diffs explained?

Every nontrivial PR/change set should state:

- operator-visible outcome;
- semantic invariants touched;
- evidence/authority impact;
- contract/schema/migration effect;
- fixture and checks run;
- known unsupported cases;
- rollback or rebuild path;
- docs/ADR links.

AI-authored code receives the same review. Compilation and tests are necessary but do not prove the
agent used the right domain concept. A reviewer should be able to trace one representative value
through the diff.

Avoid large “foundation” PRs. Land the contract and fixture, then the smallest module behavior,
then the application path. Generated code, bulk data, dependency updates, and formatting live in
separate commits or diffs from handwritten semantic changes.

For high-consequence later work, use independent adversarial review: the author of a transaction
guard does not provide the only review of its postcondition coverage. In the current read-only
phase, independent review should focus on causal leakage, accounting, source completeness, and
retention.

## Documentation placement and discoverability

Use a small number of document homes with clear authority:

| location | purpose |
| --- | --- |
| `README.md` | project status, capability ceiling, five-minute orientation, canonical links |
| `docs/decisions/` | accepted semantic foundation and staged program |
| `docs/decisions/adr/` | accepted implementation decisions and supersession history |
| `docs/research/` | exploratory lanes, engineering investigations, and reviews; not authority |
| module `README.md` | local ownership, dependency boundary, invariants, test command |
| `contracts/` | persisted/wire schema sources, compatibility notes, and test vectors |
| `fixtures/README.md` | fixture provenance, retention class, update rules |
| `docs/runbooks/` | startup, source outage, replay, migration, backup/restore, later incident response |
| `data/manifests/` | hashes and provenance for optional external corpora, never the private data itself |

Do not duplicate the canonical vocabulary in every module. Link to `FOUNDATION.md` and document
only local consequences. Generated API reference is useful for mechanics but never replaces the
contract rationale.

A concise root `AGENTS.md` should eventually state capability ceiling, canonical vocabulary links,
root commands, prohibited actions, and task ownership rules. Add nested `AGENTS.md` files only when
a subtree genuinely has different instructions. A 2,000-line universal agent manual will be
ignored and become stale.

Source comments explain why a local invariant or workaround exists and link to its fixture/ADR.
They do not restate obvious syntax. TODOs require an issue/decision reference or a concrete
condition; speculative “future ML” TODOs do not belong in the production path.

## Architecture decisions required before scaffolding Slice 1

The accepted foundation decides meanings, but the pre-engineering program deliberately withholds
the physical application decision. Do not create the production skeleton below until the decision
checkpoint answers:

1. Which operating mode did Spike 0 select: replacement, companion, on-chain observatory, or stop?
2. What exact first coin/workflow and portfolio domain does Slice 1 own?
3. What fields and interactions are in the first scene manifest?
4. What are the retention and hard-erasure classes?
5. Which source adapters passed the chart, wallet, quote, and access probes?
6. What measured event volume, write concurrency, replay shape, and UI latency must the local
   process handle?
7. Which primary runtime and storage hypothesis won the walking-fixture bake-off?
8. Is the product a native discovery surface, a companion capture, or initially exact-mint only?
9. Which old components are fixture donors, and which minimal code transplant passed a current
   conformance test?

The answer becomes a small ADR set: operating mode, primary runtime, storage, initial adapters,
contract source, and local process shape. Only then should directory names imply those decisions.

## Proposed first repository skeleton after that checkpoint

This is a logical skeleton for Slice 1, not an instruction to create all directories now. Omit any
directory whose approved slice does not use it.

```text
joshi/
  README.md
  AGENTS.md
  dev                         # thin stable command dispatcher
  docs/
    decisions/
      FOUNDATION.md
      PRE_ENGINEERING_PROGRAM.md
      RESEARCH_PROGRAM.md
      adr/
    research/
    runbooks/
  contracts/
    evidence/                 # only persisted/cross-boundary contracts now in use
    operator/
    accounting/
    replay/
    test-vectors/
  apps/
    cockpit/                  # UI if approved by operating-mode ADR
    local/                    # one local application/process, not a service fleet
  modules/
    semantics/                # IDs, units, missingness, clocks, pure transition rules
    evidence/                 # observations, blobs, coverage; no vendor decoding
    operator/                 # episodes, gestures, stance/thesis records
    accounting/               # exact asset effects, lots, epochs, basis quality
    replay/                   # scenes and three replay modes
  adapters/
    storage/                  # one approved local store
    wallet/                   # read-only reconciliation only
    market/                   # only the chart/event source approved for Slice 1
    quotes/                   # query-only adapters; no builder or send method
    pump-surface/             # only if replacement/companion mode earned it
  fixtures/
    semantic/
    protocol/
    adversarial/
    e2e/
  data/
    manifests/                # optional corpora metadata; actual data ignored/external
  research/
    studies/                  # Python/Julia/etc consumers of versioned exports
  tools/
    generation/
    fixture-maintenance/
    checks/
```

This skeleton encodes several decisions:

- one repository;
- one local operational application rather than microservices;
- domain modules separate from source/storage/UI adapters;
- no `executor`, `signer`, `orders`, `policy-engine`, `feature-store`, `graph-service`, or LP
  control directory in Slice 1;
- contracts and fixtures visible at the root rather than hidden inside an ORM or frontend;
- studies are consumers, not runtime dependencies;
- external data is manifest-addressed, not checked in or reached by an ambient home path.

If the selected primary runtime offers a conventional workspace layout, adapt these names rather
than fighting the ecosystem. For example, a TypeScript workspace may place modules under
`packages/`; a Rust workspace may use `crates/`; Dune may use `lib/`; .NET may use `src/`. Preserve
the ownership/dependency topology, not the exact spelling.

Do not create empty directories for every future strategy family. Crackle, fancoins, ecology,
wallet routing, LP control, models, and execution enter only when an approved slice gives them an
operator use and contract.

## Reversible bootstrap experiment

After Spike 0 but before a production scaffold, run a time-boxed **walking-fixture and language
bake-off**. It touches no live wallet and uses no secret.

### Representative path

Use one committed synthetic/adversarial fixture plus one small public-chain fixture to exercise:

```text
raw observation
  -> persist with unique observation ID and content-addressed blob
  -> decode one versioned assertion with exact integer units
  -> reduce one wallet/runner accounting view with unknown basis
  -> record one operator mark and scene manifest
  -> produce witnessed and retrospective replay digests
  -> expose the result in the smallest inspectable UI or CLI
```

Inject one duplicate delivery, one equal-valued distinct chain event, one gap, one late correction,
and one re-entry after exact flat. No live collector is necessary.

### Competing implementation hypotheses

Implement the complete walking fixture once in the leading architecture selected for trial—at
present likely Rust + TypeScript under lane 13 or Python + TypeScript/Node under lane 14. Implement
the **same pure reducer/contract path**, not another UI, in the serious challenger. If the root
accepts lane 20's Rust numeric kernel independently of the shell, test that exact process/binding
boundary rather than building a vague “mixed stack.” OCaml or C# enters the bake-off only if Ember
is genuinely considering it as the durable core; do not build four miniature platforms.

Compare:

- setup steps and clean-machine reproducibility;
- edit-to-test and full-check latency;
- domain code size and conceptual locality;
- quality of exact-integer, missingness, and transition types;
- runtime validation and error inspectability;
- dependency count and protocol adapter fit;
- bridge/generated-code burden;
- behavior of two small AI-authored change tasks, including defects the compiler/tests caught;
- ease of debugging the injected failures;
- whether Ember wants to continue editing the code after the exercise.

Keep the language-neutral vectors, ADR evidence, and useful fixture. The implementations are
throwaway unless one is explicitly accepted. Avoid preserving both “for reference,” which is how
dual maintenance begins accidentally.

### Bootstrap pass condition

The chosen hypothesis should:

- start offline from one root command;
- pass on the actual Apple-arm64 host from declared toolchains alone;
- rebuild its derived view from raw fixture state deterministically;
- make the duplicate/gap/correction/re-entry visible and correct;
- permit one agent to change a source adapter fixture without touching accounting, and another to
  change the reducer without editing the UI contract;
- provide an intelligible lineage from displayed value to raw input;
- require no credentials, cloud service, global mutable environment, or legacy data tree;
- feel small enough that deleting and restarting remains credible.

If no candidate feels pleasant, do not resolve the comparison by adding more abstraction. Simplify
the walking fixture or choose the stack Ember can most readily inspect.

## Anti-patterns to reject

### Repository and architecture

- Splitting by language into `joshi-ui`, `joshi-core`, `joshi-indexer`, and `joshi-models` before
  any independent release or authority boundary exists.
- A “shared” package containing every identifier, DTO, helper, and source-specific enum.
- Database rows or SDK objects flowing directly into UI and studies as the canonical domain model.
- A service per collector, event family, or strategy book because the eventual system sounds
  distributed.
- Adding a graph database because territory and identity are described as graphs.
- Importing `joshibot` or its 74+ GiB estate to make the first demo impressive.
- Creating future `signer`, `executor`, or `policy` skeletons in an R0–R4 repository.

### Contracts and data

- One universal event enum or JSON blob with optional fields for every future source.
- Generating schemas from mutable ORM classes or frontend interfaces.
- Hand-editing generated bindings or accepting unexplained generation drift.
- Rewriting raw evidence during a parser migration.
- Calling an empty provider response a valid zero because that is easier to type.
- Snapshot tests whose only review affordance is a thousand-line JSON replacement.
- Tests that pass only because the developer has `~/dev/joshibot/data` mounted.

### Tooling and builds

- Requiring Node, Rust, OCaml, .NET, Python, Julia, Docker, and Nix merely because they are installed.
- Shell scripts containing domain logic, fee math, migration semantics, or silently destructive
  cleanup.
- “One command” implemented as a wrapper that suppresses which process failed or discards its log.
- Floating SDK versions, unreviewed lockfile churn, or network-dependent unit tests.
- A container-only macOS workflow whose filesystem, networking, and debugger are worse than native
  development without providing a meaningful reproducibility gain.
- Byte-reproducible packaging work before deterministic semantic replay.

### AI collaboration

- “Implement the backend” tasks with no owned paths, fixture, or semantic acceptance condition.
- Multiple agents editing the same contract or migration concurrently.
- Trusting an agent-generated adapter because it compiles against an SDK.
- Allowing broad formatters or mechanical renames in a shared working tree.
- Copying large generated diffs into review with handwritten changes hidden among them.
- Treating an AI summary as architectural memory instead of updating the ADR/module contract.
- Optimizing file structure solely for context-window size at the cost of human coherence.

### Engineering culture

- Ceremony that exists to resemble a large company: mandatory RFCs for tiny decisions, service
  catalogues, quarterly roadmaps, or elaborate ownership bots in a one-human project.
- “Move fast” meaning source meaning, migrations, or fixtures are undocumented.
- Formalizing unstable operator language because Ember is good at formal methods.
- Avoiding a delightful language solely because an AI produces fewer examples in it, or adopting
  one solely because it feels intellectually virtuous.
- Calling infrastructure progress product progress before Ember naturally uses the loop.

## Engineering-pride criteria

Joshi should feel like something its authors are proud to inhabit, not merely a research apparatus
that happens to run.

### Clarity

- The canonical words in code match `FOUNDATION.md`.
- A new contributor can say which module owns an observation, fill, episode, scene, and quote.
- Invalid or unknown states are explicit variants, not comments on nullable values.
- The main path reads in the same order the evidence moves.
- A code review discusses domain meaning before framework choreography.

### Inspectability

- Every displayed fact can reveal provenance and producer version.
- Every local process announces capability ceiling and source health.
- A replay mismatch provides a useful diff.
- Raw inputs survive parser defects.
- Logs and errors make unknown state more visible rather than smoothing it away.

### Mechanical sympathy

- Exact integers stay exact; large blobs are content-addressed; high-rate evidence is append-
  oriented; derived views are rebuildable.
- The census is compact and hot scopes are selective.
- Backpressure creates visible gaps rather than biased silent loss.
- The chosen language and store match measured event volume, query shape, and operator latency.
- Local Apple-arm64 development remains fast instead of emulating an imaginary cluster.

### Low ceremony

- Root commands are few and memorable.
- Most changes touch one module, one fixture, and perhaps one contract.
- There is no required cloud control plane, SaaS telemetry, or always-running orchestration stack.
- ADRs record expensive decisions, not every thought.
- The app starts with a useful offline world and explains optional live dependencies.

### Joy and continuity

- Ember can open the semantic core and enjoy the shapes rather than excavate framework glue.
- AI agents can make bounded progress without forcing Ember to re-explain the project on every
  task.
- Error messages and replay tools reward curiosity.
- Old experiments leave fixtures and decisions, not haunted code paths.
- Refactoring toward a clearer model is normal and does not require preserving premature APIs.

### No gold-plating

Pride is not maximum abstraction, proof coverage, language count, test count, or infrastructure.
Before adding a layer, ask:

1. Which current slice or invariant does it serve?
2. What failure has made the simpler design inadequate?
3. Can the layer be removed without changing evidence meaning?
4. Will Ember or an agent be able to inspect it locally?
5. Does it reduce total explanation, or merely move it?

The first engineering milestone is not a pristine architecture. It is a small repository in which
one truthful episode path is easy to run, inspect, change, and replay—and whose seams are honest
enough that later complexity can be added without composting the semantic foundation.

## Decisions for the later engineering checkpoint

The root synthesis should eventually decide, based on Spike 0 and the walking fixture:

1. monorepo confirmation and the exact trigger for a future signer split;
2. primary runtime, frontend choice, and explicit language budget;
3. local process shape and whether a browser/backend wire contract exists;
4. storage and raw-blob layout;
5. canonical contract representation and generation policy;
6. toolchain pinning/environment mechanism;
7. first adapter set and source-conformance update policy;
8. data manifest/storage location and operator-retention classes;
9. root command interface and CI host matrix;
10. module ownership/dependency rules and the initial ADR set.

Until that checkpoint, DX work should remain documents, disposable Spike 0 code, fixtures, and
measurement—not a production framework awaiting a product.
