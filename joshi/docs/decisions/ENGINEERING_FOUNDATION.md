# Engineering foundation

Status: **provisional implementation decision, pending Decision Spike E0**. This document chooses
the default architecture to falsify. It does not authorize source access, a purchase, a wallet
credential, transaction construction, signing, submission, automation, or a trade.

Date: 2026-08-16.

> **Scope update, later 2026-08-16:** `docs/implementation/PROGRAM.md` supersedes this document's
> narrow exact-mint/source-access posture and authorizes the read, record, replay, render, and
> analyze implementation substrate. Existing Helius and PumpPortal credentials are intended API
> access, and an honestly authenticated Pump companion is a first-class accessibility adapter.
> The Rust/React/local-first truth architecture and the separation of wallet authority remain in
> force. This update does not authorize constructing, signing, submitting, or automating trades.

## Decision

Build Joshi as a local-first monorepo with a modular Rust core and a React/TypeScript browser
cockpit. The core is one semantic application and one authoritative writer, even if a source SDK
later earns a narrow subprocess boundary.

The provisional stack is:

- stable, project-pinned Rust for acquisitions, evidence commits, exact protocol and financial
  calculations, projections, replay, hot-scope control, and the local API;
- React, TypeScript, and Vite for the browser renderer and semantic gestures;
- a project-pinned SQLite runtime in WAL/FULL mode for the operational catalog, with strict tables
  and one writer;
- content-addressed local files for large or retention-sensitive exact bytes;
- immutable manifested Parquet exports and ephemeral DuckDB only when the first research snapshot
  earns them;
- a separately locked Python environment for research consumers of frozen exports;
- pinned official TypeScript SDKs as differential protocol oracles, not live financial truth;
- an independent OCaml/Zarith numerical and reducer oracle after the first natural-use slice, before
  complex accounting or LP transformations are trusted.

No C#, F#, Julia, Lean, desktop wrapper, broker, server database, managed stream, full-market
firehose, or model service belongs in the first operational graph. These are not rejected forever;
they currently remove less complexity than they add.

Rust is the default, not an article of faith. It is selected for Slice 1 only if the bounded E0
walking fixture in `ENGINEERING_CORRIDOR.md` passes. A failed gate chooses a smaller fallback rather
than producing two maintained cores.

## Why this composition wins

The runtime investigation considered OCaml 5, C#/.NET, F#, Rust, Python, and mixed architectures.
OCaml provides the most attractive pure semantic modeling experience for Ember. .NET provides the
strongest integrated application diagnostics and a very productive edit loop. Python supplies the
shortest exploratory path. Rust nevertheless has the best composed fit because:

1. Solana and Pump provide first-party Rust surfaces, while C#, Python, and OCaml would require a
   community stack, generated bindings, or another runtime at the protocol edge.
2. The deployed protocols use unsigned fixed-width integer arithmetic and operation-specific
   rounding; Rust can express the wire widths directly while still using independent wider
   intermediates and checked narrowing.
3. Native SQLite, Arrow, and Parquet support permits one operational owner to produce portable
   research artifacts without a second live application runtime.
4. Bounded channels, explicit errors, algebraic data types, exhaustive matching, and fuzz/property
   tooling fit the evidence and replay problem.
5. A Python application plus a Rust protocol/numeric authority plus a TypeScript UI would not be
   simpler than a Rust application plus a TypeScript UI. It would add a coordinator around the
   two hardest sources of truth.
6. A Rust core leaves OCaml free to be genuinely independent assurance. If OCaml were also a live
   reducer, every semantic change would create another operational release and schema boundary.

Rust does not win merely because it is fast or memory safe. It loses if ordinary semantic changes
become trait/lifetime theater, if its protocol advantage does not survive differential tests, if
the local edit/replay loop is unpleasant, or if it cannot close the representative path within the
fixed decision budget.

## Logical topology

```text
                           Ember
                             |
                  React / TypeScript browser
                  render · inspect · gesture
                             |
                 versioned loopback contract
                             |
                  +----------v-----------+
                  | stable Rust core     |
                  |----------------------|
                  | one writer           |
                  | evidence + coverage  |
                  | exact calculators    |
                  | ledger + episodes    |
                  | scenes + replay      |
                  | hot-scope control    |
                  | local query stream   |
                  +----+------------+----+
                       |            |
            observation|            | durable local state
              contracts|            |
       +---------------v--+      +--v-------------------+
       | cleared adapters |      | SQLite catalog       |
       | chain · wallet   |      | hashed blob files    |
       | exact mint       |      +----------+-----------+
       +------------------+                 |
                                            | manifested export, later
                                            v
                                  Parquet -> DuckDB/Python

Offline assurance:
  pinned TypeScript SDK comparator
  independent OCaml/Zarith oracle, when earned
```

The initial product is not a service architecture. There is one local core and one browser. A
source runner is permitted only when a runtime, credential, crash, or SDK-conformance boundary is
smaller than incorporating that adapter. It has no database credentials, portfolio query, operator
state, wallet key, or transaction endpoint.

## One owner for each kind of truth

| Object | Operational owner | What it is not |
| --- | --- | --- |
| raw observation and coverage | Rust evidence module + SQLite/blob commit | a parsed market fact |
| source event identity | typed evidence contract | a content hash or acquisition occurrence |
| assertion | versioned parser/reconciler | mutable latest truth |
| exact protocol calculation | one versioned Rust calculator | an SDK summary or UI recomputation |
| landed financial effect | finalized wallet/account reconciliation | intended or simulated effect |
| episode attribution | episode projection over independent ledger facts | ownership of balance or PnL |
| witnessed scene | exact stored renderer DTO and delivery watermarks | a retrospective reconstruction |
| research result | immutable snapshot/run bundle | permission to mutate product policy |
| future transaction attempt | absent until a new authority decision | a module to scaffold now |

SDK objects stop at adapters. Database rows stop at repositories. UI models stop at rendering and
semantic commands. Research tables do not become current operational truth.

## Product and source posture

The planning default is a companion-capable exact-mint cockpit, not a complete Pump replacement.
The accepted access research establishes:

- public chain/program facts are a strong canonical market substrate;
- Pump publishes useful exact-mint enrichment routes;
- no supported discovery/ranking/notification/follow/thread/chart API currently establishes the
  entire product surface;
- browser-visible data, permissive CORS, shipped keys, anonymous responses, and `robots.txt` do not
  by themselves authorize an automated replacement;
- a companion method must be cleared at the exact operation and field level.

Spike 0 may select one-surface replacement, reviewed companion, independent on-chain observatory,
or stop/rethink. That result changes adapters and product claims, not evidence, accounting, scene,
or replay ownership. Exact-mint manual nomination remains an honest and useful post-selection mode.

## Data and storage boundary

The first storage hypothesis is deliberately small:

```text
bounded adapters -> one committer -> SQLite WAL/FULL + content-addressed blobs
                                      |
                                      +-> durable projection/outbox work
                                      |
                                      `-> immutable manifested Parquet, later
                                                           |
                                                           `-> ephemeral DuckDB/Python
```

SQLite is conditional, not permanent doctrine. The selected binding must report a fixed SQLite
version containing the current WAL-reset fix; the host CLI's 3.51.0 library is not acceptable for
the application WAL. Startup verifies version, WAL, `synchronous=FULL`, foreign keys, and strict
schema behavior. Crash, backup/restore, checkpoint, and representative load tests must pass.

If SQLite fails those production-setting gates, replace the operational boundary with PostgreSQL.
Do not maintain both as canonical writers. Parquet files are immutable exports whose manifests
remain in the operational catalog. DuckDB is a disposable query engine, never another source of
truth.

## Acquisition and scale

The measured whole Pump/PumpSwap log path produced roughly 1,552 notifications per second and
238.9 GB/day of raw ingress, most of it failed transactions. The August system does not acquire
that stream.

Joshi instead uses:

- a compact, cheap denominator: launches, migrations, selected board/surface observations, coarse
  lifecycle, and coverage;
- a candidate router: operator nomination, reviewed followed-wallet evidence, selected surface,
  and bounded territory queries;
- explicitly leased hot scopes: exact trades/reserves, local quotes, selected social revisions,
  and consequential scenes for a few mints at a time;
- typed budgets, TTLs, queue depth, gaps, and degradation for every scope.

The pre-September incremental infrastructure budget is $0. Existing quotas are not free unless
their remaining capacity, renewal, autoscaling, and competing use are known. No date automatically
widens the budget.

## Language budget

The initial normal application graph has two production languages:

1. Rust core.
2. TypeScript browser.

Python is a separate research/probe environment. It does not participate in the normal product
startup. A TypeScript SDK comparator is an offline test dependency. If exact conformance proves a
missing Meteora or Pump SDK boundary, a narrow TypeScript source runner may be admitted by ADR and
then counts as a third production runtime.

OCaml initially owns no production state. Its first justified role is an independent, small,
network-free oracle over canonical vectors. That role preserves the strongest reason to use it—its
clear mathematical and algebraic model—without forcing the evidence, UI, Solana, and columnar
ecosystems through OCaml bindings. OCaml can be reconsidered as a durable semantic core if later
evidence shows it prevents material defects or substantially improves Ember's long-term ability to
inhabit the code.

C#/.NET remains the strongest whole-core alternative if the primary decision is reopened. F# is
considered only inside a selected .NET topology. Neither enters beside Rust merely because its
individual tooling is attractive.

## Verification allocation

The assurance order is:

1. examples and typed contracts;
2. property and executable state-machine tests;
3. deterministic evidence, market/quote, and later authority simulators;
4. raw-byte fuzzing and independent protocol differential tests;
5. crash, restore, schema-migration, and fixed replay corpora;
6. bounded model checking for a named concurrency/authority protocol;
7. deductive proof only for a small, stable mathematical kernel that survives the earlier layers.

The first committed fixture families must cover duplicate delivery, equal-valued distinct events,
source conflict, gap and recovery, late correction, partial realization and runner, exact flat,
watching-flat, re-entry, unknown basis, current quote versus mark, and witnessed versus
retrospective replay.

TLA+/Quint may later earn the evidence/cursor or transaction-attempt protocol. Kani may earn a
bounded Rust parser/guard arithmetic kernel. OCaml/Zarith earns independent calculation vectors.
Lean enters only for an enduring theorem, not for CRUD or an unstable operator ontology.

## Developer-experience contract

Engineering pride means clarity and inspectability, not maximum language or proof count:

- one monorepo and one semantic dependency graph;
- one root command for offline readiness and one for the approved local slice;
- every module names what facts it owns, permitted dependencies, invariants, and effect ceiling;
- persisted and cross-process contracts have one source and executable language-neutral vectors;
- every displayed fact can reveal its raw evidence, producer, clocks, and projection version;
- every crash or replay mismatch emits a small reproducible trace;
- no ordinary test requires the 74+ GiB `joshibot` estate, network, key, or cloud account;
- AI tasks own narrow paths and named fixtures; the same agent does not define the contract,
  implementation, goldens, and adversarial verdict for a consequential boundary;
- old code contributes named fixtures and pure donor behavior, never runtime imports or wholesale
  state migration;
- semantic changes produce decisions, migrations, and replay diffs rather than optional fields in
  a universal event.

The repository stays a monorepo through R4 and likely R5. A future signer may earn a separate
repository through a real authority and release boundary, not because it uses another language.

## Accepted now, conditional, and deferred

Accepted as the pre-engineering default:

- local-first monorepo and modular core;
- browser-neutral React/TypeScript renderer;
- one writer and explicit capability boundaries;
- stable Rust as the candidate primary core;
- SQLite/blobs as the candidate local truth boundary;
- Python-first research over immutable snapshots;
- compact census plus bounded hot scopes;
- no transaction authority and $0 incremental infrastructure.

Conditional on named gates:

- Rust and SQLite promotion through E0 and Slice 1 capacity/recovery;
- each live source through exact access, coverage, and conformance review;
- a TypeScript source runner through an identified native-Rust gap;
- companion capture through access/privacy and hostile fidelity review;
- Parquet/DuckDB through the first reproducible study;
- OCaml oracle through the first complex numerical/accounting assurance need.

Deferred:

- Pump-wide parity, broad social collection, full-market high-resolution retention;
- transaction building, keys, signing, submission, Jito, and automated policy;
- LP control, copying wallets, automated territory trading, model-visible ranking;
- desktop/mobile packaging, remote control, managed streams, server databases, brokers;
- feature stores, orchestration, model registries, vector databases, online learning;
- permanent C#/.NET, F#, OCaml, Julia, or Lean product components.

## Reopening conditions

Reopen the primary runtime decision only when one of these occurs:

- E0 cannot close the raw-to-replay walking path within its timebox;
- ordinary source-schema and episode changes require cross-cutting Rust ownership/trait work;
- a necessary source/protocol dependency is unusable on the target host;
- stable Rust cannot provide the fixed SQLite or protocol behavior required by the gates;
- TypeScript, Python, OCaml, or .NET demonstrates a materially smaller complete operational graph,
  not merely a nicer isolated reducer;
- Ember's direct experience is that the selected core is substantially less legible, confidence-
  inspiring, or enjoyable to maintain;
- the operating mode changes the actual runtime requirements rather than only the adapters.

If no challenger wins decisively, choose one smaller path and delete the losing implementation
after extracting vectors and decision evidence. Never keep both “for reference.”

## Bottom line

The architecture should feel like a small, exact instrument, not a speculative trading platform.
Rust is the best current owner for the facts that would otherwise be split across Python and an
SDK/numeric sidecar. TypeScript remains the natural glass. Python remains the natural laboratory.
OCaml remains a valuable independent conscience and possible later semantic home.

The decisive milestone is not that Rust compiles or a million rows fit in SQLite. It is that one
honest exact-mint scene flows from evidence to a screen Ember chooses to use, survives a crash, and
reappears without inventing what was known, owned, intended, or executable.
