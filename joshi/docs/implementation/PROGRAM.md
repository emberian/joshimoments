# Broad-base implementation program (closed)

Status: **CLOSED 2026-08-19. Superseded by [`PILLARS.md`](PILLARS.md).**

The active program is the pillar and vertical-slice program in [`PILLARS.md`](PILLARS.md). This
document is retained as history: it is the wave-based program that ran from 2026-08-16 through
Wave 6, and its premise, capability boundaries, crate posture and walking path are still the
correct description of what the system is for. Its *sequencing* is what was retired.

Nothing below is deleted and nothing below is authority any more. Read
[`PILLARS.md`](PILLARS.md) for what is being built now, and see
[Why this program closed](#why-this-program-closed) at the end of this file for what went wrong.

Original date: 2026-08-16. Original status: authorized to scaffold and implement the read, record,
replay, render, and analyze substrate.

## Product premise

Joshi is a personal, accessibility-first, interoperability-centric Pump/Solana cockpit. It is not
an exact-mint demo waiting to become a platform later. Its first foundation must be broad enough to
support:

- the Pump attention surface Ember already uses, through honest authenticated access;
- broad public-chain and licensed-provider acquisition through Helius and PumpPortal;
- exact local evidence, durable replay, wallet and episode truth, and explicit coverage;
- a keyboard-first glass that reduces painful phone and precision-pointer interaction;
- frozen research exports and an analysis environment that can grow with the market ontology;
- later advisory and execution capabilities without placing wallet authority in the data, UI, or
  analysis processes.

Continuous acquisition must not depend on Ember's browser or laptop uptime. The primary source
path is a headless, honestly authenticated adapter for Helius, PumpPortal, public Solana, and Pump
APIs, backed by a remote append-only spool and resumable synchronization. The Pump WebExtension is
limited to endpoint/auth reconnaissance, official-render parity, drift detection, and accessibility
fallback. It is not the intended continuous production pipeline.

The existing Helius and PumpPortal subscriptions are part of the available foundation. Their use
is intended API access, subject to their documented quotas and terms. Pump-only social responses
remain a distinct authenticated source adapter, not a reason to narrow the rest of the system.

## First integrated walking path

```text
licensed/public source or fixture
  -> immutable observation envelope and coverage
  -> single-writer SQLite/CAS commit
  -> versioned assertion and projection
  -> local query/stream API
  -> accessible React glass
  -> manifested Parquet snapshot
  -> reproducible Python/DuckDB analysis
  -> witnessed replay of what Ember actually saw
```

Every component must be useful with offline fixtures. Network adapters add observations; they do
not define the domain model.

## Wave 1 lanes and ownership

| Lane | Initial ownership | First artifact |
| --- | --- | --- |
| Rust contract spine | root manifests, `crates/joshi-domain`, `crates/joshi-evidence`, `apps/core` | compilable workspace and fixture-to-query skeleton |
| Event/data substrate | `schema`, `fixtures/tape`, then `crates/joshi-store` | strict schema, adversarial fixtures, crash-safe writer |
| Accessible glass | `apps/glass` | keyboard-first feed/coin/episode/replay shell over a mock versioned contract |
| Analysis platform | `analysis` | locked CLI environment consuming a manifested local snapshot |
| Pump companion | `extensions/pump-companion` | origin-scoped authenticated capture adapter with a fully offline mock path |
| Rust crate estate | `docs/implementation/RUST_CRATES.md` | adopt/build/defer matrix with versions, licenses, activity, and seams |

No lane other than the contract-spine owner edits the root Rust manifests during Wave 1. The main
integrator owns cross-boundary contracts and merge order. Lane-specific package manifests are
permitted inside their assigned directories.

## Capability boundaries

- Acquisition processes may read provider credentials when a named probe is authorized. They do
  not receive wallet private keys.
- The browser and extension never receive Helius, PumpPortal, or wallet secrets from the core.
- Storage persists observations and provenance, never a replayable secret value.
- Analysis consumes immutable exports and cannot mutate operational truth.
- No Wave 1 component constructs, signs, submits, or rebroadcasts a transaction.
- Wallet signing will be a separate capability process. Secret paths may be configured by
  reference; secret contents must never appear in logs, fixtures, commits, command arguments, or
  agent reports.

## Crate posture

Prefer a well-maintained Rust crate over bespoke infrastructure when its semantic and operational
boundary is honest. Every production dependency must have a named purpose; protocol and financial
crates also need pinned provenance and differential fixtures. We should actively seek crates for:

- async runtime, bounded channels, cancellation, retries, and structured tracing;
- HTTP/WebSocket/Solana acquisition and rate control;
- strict SQLite access, migrations, content hashing, and crash-safe file operations;
- exact numeric types, serialization, schema generation, and property/fuzz testing;
- Arrow/Parquet export and local API transport;
- configuration, secret-path handling, diagnostics, and reproducible test fixtures.

Avoid writing a framework merely to preserve architectural purity. Avoid adopting a crate merely
because it has the desired noun in its name.

## Wave 1 integration gate

Wave 1 is integrated when one root command can, without network or credentials:

1. build and test the Rust workspace, glass, companion, and analysis environment;
2. ingest the common tape fixture without collapsing equal-valued distinct observations;
3. durably commit and replay it with an explicit coverage gap and later correction;
4. serve a versioned snapshot without JavaScript monetary-number coercion;
5. render it through keyboard-only glass and record one idempotent semantic mark;
6. export a manifested research snapshot and reproduce one analysis result; and
7. demonstrate that no component in the walking graph can construct, sign, or submit a trade.

This gate is a composition target, not permission to shrink each lane into a toy. The schemas and
interfaces should leave room for census-to-hot promotion, social context, charts, wallet watching,
episodes, LP state, and future learning without pretending those meanings are already settled.

## Wave 2 direction

Wave 2 broadens the foundation without granting economic authority:

- inventory `hbox` and `persvati` as remote Joshi hosts and retain a host-agnostic Hetzner path;
- implement a protection-domain-aware append-only remote acquisition spool with resumable sync;
- replace browser-dependent Pump collection with a direct authenticated API adapter, using the
  companion only as a parity/reconnaissance instrument;
- characterize existing paid Helius and PumpPortal access under explicit request/time/disk and
  no-overage caps;
- deepen exact protocol, quote, liquidity-position, operator-command, scene, choice-set, dataset,
  experiment-lineage, and future ensemble-prediction contracts; and
- keep the entire current source tree licensed `AGPL-3.0-or-later` with publishable provenance and
  dependency hygiene.

## Why this program closed

Closed on 2026-08-19, with Waves 5 and 6 closed out at [`wave5/CLOSEOUT.md`](wave5/CLOSEOUT.md)
and [`wave6/CLOSEOUT.md`](wave6/CLOSEOUT.md).

The program was not closed because it reached a gate. Wave 5's `W5-G0` root witness never ran and
Wave 6 never rose above `unverified_semantic_fixture_only`. It was closed because the wave framing
was holding the project back.

At close the workspace had 38 crates, roughly 158,000 lines of Rust, about 900 Rust tests, 23
migrations and four applications, and had never ingested one byte of real market data through its
evidence pipeline. The Wave 5 ceiling ledger reports the same blocker sentence in nine separate
rows — *inputs are caller projections, no adapter exists* — because nine pillars were blocked by
one missing edge, and a program organized by kernel ownership had no place to put a critical path.

The **first integrated walking path** in this document is still exactly right. It was simply never
walked: no process has ever carried one observation from a source through the store to a rendered
surface and back after a restart. Waves built every station on the line and never ran a train.

What replaces it: [`PILLARS.md`](PILLARS.md) organizes by the eight pillars in the README and by
one vertical slice per pillar, under a single promotion rule — a slice is done when a real
observation, acquired from a real source, reaches a rendered surface and can be read back after a
restart. The capability boundaries, crate posture, prohibitions and product premise stated above
carry forward unchanged.
