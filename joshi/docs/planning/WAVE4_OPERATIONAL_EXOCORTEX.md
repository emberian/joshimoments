# Wave 4 — operational exocortex

Status: implementation plan; no provider call, host mutation, deployment, purchase, wallet
authority, transaction construction, signing, submission, liquidity change, or trade is authorized
by this document.

Planning date: 2026-08-17.

Grounding:

- [`PROGRAM.md`](../implementation/PROGRAM.md)
- [`WAVE3_INTEGRATION.md`](../implementation/WAVE3_INTEGRATION.md)
- [`REMOTE_TOPOLOGY.md`](../implementation/REMOTE_TOPOLOGY.md)
- implementation lane handoffs under [`docs/implementation/lanes`](../implementation/lanes)
- [`JOSHI_THOUGHT.md`](../../JOSHI_THOUGHT.md)
- routed-liquidity research under
  [`docs/research/routed_liquidity`](../research/routed_liquidity)

## 1. Decision

Wave 4 should build a **continuous, resilient, read-only operational exocortex**: a system that
observes a bounded market surface, preserves what it did and did not see, promotes a small set of
subjects into higher-fidelity observation, continuously publishes exact point-in-time projections,
serves them through an accessible witnessed Glass, records Ember's interpretations and choices,
and exports immutable research material without letting research write truth.

This is the most ambitious useful next wave because it connects the strong Waves 1–3 components
instead of adding another isolated calculator, fixture, or model prototype. It is not a trading
system. Its product is a reliable human–machine observation and decision instrument.

Wave 4 earns the word **operational** only when one non-fixture prospective episode walks through:

```text
continuously supervised source
 -> occurrence reserved before I/O
 -> exact evidence durably spooled
 -> sole catalog writer admits it and returns an exact receipt
 -> census subject is promoted into a bounded hot scope
 -> wallet/social/lifecycle/pool facts circulate through typed point-in-time reducers
 -> immutable deterministic projection is durably published
 -> same-origin Glass reveals a durably staged presentation
 -> Ember records a presentation-bound choice or abstention
 -> production store-derived Parquet snapshot is independently validated
 -> one analysis/model artifact is imported as a restricted derivation
 -> witnessed and retrospective replays remain distinct
 -> restart, backlog recovery, integrity verification, and budget accounting close
```

The current green root command does not prove this. It proves an excellent but narrower
`source_scene_command_readiness` fixture: companion admission, store receipt/retry, one Glass scene,
one V1 operator command, verification, and reopen. Wave 4 must retain that result and widen the
walking path without weakening any of its digest, clock, cutoff, idempotency, or authority
boundaries.

## 2. What exists, and what does not

### 2.1 Green substrate

The following are real, tested foundations:

- stable domain/evidence contracts with exact microsecond UTC, optional source monotonic clocks,
  occurrence identity distinct from content, scoped cursors, coverage, gaps, and corrections;
- the V6 single-writer SQLite/CAS store, migrations, full receipts, verification, online backup,
  typed scene/operator admission, and fixture-scoped export registration;
- bounded read-only Helius, Solana, PumpPortal, direct Pump, browser companion, wallet-source, and
  remote-spool libraries;
- exact accounting, Pump/PumpSwap quote math, DLMM position/action projections, wallet topology,
  attention, and the finalized `joshi.read_projection` artifact;
- strict Glass view/operator clients, memory-only pairing primitives, presentation contracts, and
  the accessibility-first fixture workbench;
- Python snapshot validation, deterministic feature materialization, analog retrieval, kernel and
  field prototypes; and
- one offline root gate whose normal core dependency closure contains no signing or submission
  capability.

### 2.2 Boundaries still open

None of the following should be described as operational today:

- there is no always-on collector/supervisor binary;
- source output is not generally translated through one lossless source-to-spool-to-store path;
- the spool has no service, transport, health endpoint, shutdown protocol, or deployment unit;
- direct authenticated Pump social/discovery parity has not been established with Ember present;
- census membership does not yet drive durable, budgeted hot-scope leases end to end;
- wallet, topology, attention, lifecycle, and pool facts do not yet circulate from real source
  evidence through store-backed reducers into product snapshots;
- the deterministic financial projection is not durably published from store facts;
- the Rust exporter is a validated fixture rewrite, not a production store-to-Parquet projection;
- analysis artifacts cannot yet be strictly imported and displayed as restricted derivations;
- Glass is not served same-origin by core, has no safe pairing bootstrap, and presentation scene and
  event admission are not mounted;
- the inventoried remote hosts remain deployment-blocked by end-of-life operating systems; and
- there has been no prospective operational episode using the complete instrument.

Those are the Wave 4 work items. New model families, execution abstractions, and additional venue
math are not substitutes for closing them.

## 3. Wave 4 authority ceiling

Every normal process in this wave has the literal authority ceiling
`read_only_no_execution`. “Read-only” means read-only with respect to providers, chains, wallets,
markets, and other people; the system necessarily writes its own local evidence, projections,
operator records, exports, and diagnostics.

Wave 4 contains no API or dependency that can:

- obtain or derive a wallet private key, seed, challenge signature, or wallet-provider object;
- construct, simulate, sign, submit, rebroadcast, bundle, tip, or cancel a transaction;
- post, follow, like, report, message, or manufacture social engagement;
- add, remove, rebalance, claim, close, or open liquidity;
- autonomously buy, sell, hedge, crackle, copy a wallet, or act on a model output;
- expand provider spend, native-unit use, retention, or hot-scope capacity above an explicit cap;
  or
- turn a quote, modeled action, ghost edge, policy proposal, operator gesture, or model artifact into
  an economic effect.

An external manual wallet action may occur during ordinary Ember use. Joshi may later observe and
reconcile its finalized public effects. The action remains external; missing contemporaneous intent
stays unknown.

## 4. Physical topology

Wave 4 remains a local-first modular system, not a microservice program.

```text
                                Ember
                                  |
                     same-origin Glass on loopback
                     read / record / replay only
                                  |
                     +------------v-------------+
                     | Mac: joshi-core          |
                     |--------------------------|
                     | sole SQLite/CAS writer   |
                     | spool importer           |
                     | semantic admissions      |
                     | deterministic publisher  |
                     | static Glass + local API |
                     +-----+---------------+----+
                           |               |
                 immutable|               | manifested snapshot
                 artifacts|               v
                           |       local analysis batch worker
                           |       DuckDB/Python, no store write
                           |               |
                           |               v
                           |       restricted artifact import
                           |
               catalog ACK|                          optional remote tier
                           |                 after separate host approval
               +-----------v----------+       +------------------------+
               | collector supervisor |------>| hbox ciphertext replica|
               | Mac initially; later |       | no private keys/truth  |
               | persvati if repaired |       +------------------------+
               |----------------------|
               | reviewed source only |
               | pre-I/O reservation  |
               | local durable spool  |
               | no catalog/portfolio |
               +----------+-----------+
                          |
      Helius / Solana / PumpPortal / public Pump / Ember-present Pump companion/direct parity
```

The normal runtime has three roles:

1. **Collector supervisor.** Owns source credentials, attempts, source-native clocks, coverage,
   bounded queues, and one local append-only spool. It cannot read the portfolio, command Glass,
   or write SQLite.
2. **Core.** Owns the sole catalog writer, receipt translation, typed fact admission, immutable
   publications, query/command endpoints, and same-origin static Glass. It does not own provider
   sessions other than accepting a paired companion payload.
3. **Analysis worker.** Reads one manifested snapshot and writes an immutable derived bundle. It
   has no network during a run and no catalog credentials. Core later imports the bundle through a
   strict artifact admission.

`hbox` is an optional ciphertext replica, not a database, semantic writer, or sole backup.
`persvati` is only a candidate collector after repair. Hetzner is neither inspected nor purchased
and is not a Wave 4 prerequisite.

Do not create a daemon per research lane. Pure reducers remain libraries. Projection publication
and catalog registration run through the existing one-writer core. A separate process is earned
only by source credentials/fault isolation, immutable batch analysis, or remote failure-domain
separation.

## 5. Acknowledgement and progress semantics

Continuous operation needs four progress facts that must never be collapsed:

| Fact | Meaning | What it does not authorize |
| --- | --- | --- |
| occurrence reservation | a source attempt identity was durably reserved before I/O | that a response arrived |
| local spool ACK | exact segment bytes were fsynced and verified at the collector | catalog cursor advance or deletion |
| remote durability ACK | exact sealed segment bytes exist at one replica generation | semantic admission, retention release, or truth |
| catalog admission ACK | the sole writer committed the exact batch and returned the closed durable receipt | remote/local byte deletion or provider completeness |

The collector may release an in-memory payload only after the local spool ACK. It may continue
capturing while the Mac is unavailable by appending new bounded segments. A collector-local resume
token may be persisted only as an operational token tied to the sealed segment closure; it is not a
`SourceAsOf` cursor and never enters a Glass watermark. The authoritative source cursor advances
only through a catalog-committed `CursorAdvance` with its exact observation evidence.

On catalog receipt, the importer records a separate `CatalogAdmissionAck`. Retention remains a
third decision. Neither remote nor catalog ACK deletes a segment. Wave 4 implements no material
deletion controller; bounded canaries use an explicit retained/quarantine policy and stop before
the configured disk floor.

## 6. Concrete implementation lanes

One integration owner controls root manifests, shared public contracts, migrations, and the root
witness. Each other lane gets disjoint paths and submits any shared-schema need as a typed change
request. No two lanes independently edit the root lock, store migrations, or public receipt DTOs.

### W4-00 — integration, schema, and root witness

**Owned paths:** root Cargo/tooling, `apps/core`, `crates/joshi-admission`, `schema/migrations`,
`scripts/wave4-readiness`, and the Wave 4 witness contract/goldens.

**Work:**

- freeze source-spool, spool-catalog, publication, presentation, export-validation, and artifact-
  import receipts as strict camel-case public DTOs;
- add forward-only catalog support for typed source/fact artifact registration, projection
  publications, presentation scenes/events, analysis artifacts, and append-only cockpit heads;
- keep structural SQL/store drafts private behind validated capabilities;
- mount bounded loopback routes only after their typed store method exists;
- own dependency-authority and secret-canary audits; and
- produce the single `joshi.wave4.operational_witness/v1` artifact in section 14.

**Gate:** duplicate/dangerous/unknown keys, digest-domain substitution, partial 2xx, later-known
facts, mixed clocks, and same-ID changed bodies all fail before state mutation. Fresh and prior
catalog versions migrate, verify, back up, restore, and reopen.

### W4-01 — always-on supervisor and durable spool transport

**Owned paths:** a new `apps/collector`, a small `crates/joshi-supervisor`, and transport adapters
around `crates/joshi-spool`; changes to spool core require spool-owner review.

**Input seam:** bounded `SourceOutput`, direct-Pump acquisition envelopes, companion batches, and
wallet-source output plus source-specific coverage/health events.

**Output seam:** exact `DurableIngestBatch` and policy bytes inside versioned spool segments,
`LocalSpoolAck`, optional `RemoteDurabilityAck`, and later `CatalogAdmissionAck`.

**Work:**

- durably reserve acquisition/attempt identity before each HTTP request, connection generation, or
  poll; a crash after reservation but before a response becomes an explicit abandoned-attempt gap;
- supervise HTTP/WS generations, deterministic retry, inactivity, cancellation, shutdown, and
  resubscription without hidden transport retry;
- use bounded record and byte queues plus a protected gap/control reserve;
- seal authenticated-private segments before any remote boundary;
- retain and retry exact segment/batch bytes until the exact catalog receipt closes;
- expose a local health snapshot and a no-network replay command, not a public listener; and
- on graceful shutdown stop new admission, seal/fsync, write source downtime boundaries, and join
  tasks under a bounded deadline.

**Gate:** a 24-hour fake-provider run plus process-kill matrix proves repeat-never-skip semantics,
bounded memory, exact backlog recovery, corrupt-segment quarantine, no false cursor, and no source
payload released before local durability. A real canary follows only under a separate source/host
authorization.

### W4-02 — Pump product parity and source promotion

**Owned paths:** `crates/joshi-pump-api`, `extensions/pump-companion`, Pump source fixtures, and a
new strict Pump-to-admission adapter; core endpoint changes remain W4-00-owned.

**Work:**

- keep official public exact-mint and SOL-price reads as bounded source surfaces;
- with Ember present, test exactly one material authenticated read route naturally exercised by
  Ember before adding another;
- use companion raw-on private evidence and the direct client against the same route, request
  fingerprint, session class, visible filter/cursor state, and tight time boundary;
- retain exact mismatches, pagination defects, schema drift, auth lifecycle, and product-versus-
  rendered-order uncertainty;
- keep session material only in an owner-only ephemeral file or reviewed local broker; never copy
  it into fixtures, chat, CLI values, browser storage, remote spools, or logs; and
- stop on challenge/signature requirements, device binding, 401/403, persistent 429, unexpected
  scope, or any need for identity/header/key mining or evasion.

**Promotion gate:** use the lane-10 parity rule: twenty paired occurrences across at least three
ordinary sessions for a route, at least 19/20 matching ordered membership inside the measured
reaction window, understood differences, and gap-free pagination. A one-pair technical success is
only a conformance observation. If no honest headless session path exists, record
`authenticated_direct_not_admissible`; companion remains Ember-present reconnaissance/fallback and
continuous coverage honestly excludes that surface.

Authenticated Pump capture is not moved to a remote host in Wave 4. Public/provider/chain census
continues without it.

### W4-03 — census-to-hot acquisition controller

**Owned paths:** a new `crates/joshi-acquisition-policy`, scope/policy fixtures, and collector-side
control adapters. It has no store handle and no economic-action type.

**Input seam:** committed census facts, operator nominations, selected attention occurrences,
wallet candidates, source health, and explicit budget state.

**Output seam:** append-only `HotScopeIntentV1`, per-source `HotScopeDesiredV1`,
`HotScopeAppliedV1`, `HotScopeDegradedV1`, and `HotScopeClosedV1` records.

Every lease names subject kind, reason(s), opening/expiry, source families, requested fidelity,
maximum requests/pages/bytes/provider credits/native units, and the scene/policy occurrence that
requested it. Applied state is reported only after source control writes; it is not proof the
provider accepted or covered the scope.

The initial denominator is Pump/Solana launches and migrations plus only the exact product board
whose parity gate passed. If no Pump board passes, the product says `independent chain/provider
census`; it does not claim the Pump information surface.

Degradation is deterministic:

1. stop media and optional exact private bodies;
2. slow social/profile refresh;
3. shorten or evict least-recently-justified hot scopes;
4. retain compact launch/migration denominator and explicit gaps; and
5. stop cleanly before the spool/disk/control reserve is exhausted.

**Gate:** replay the same census and nominations twice to byte-identical lease decisions; overload
cannot preferentially erase high-activity or losing subjects; expiry/restart reconstructs desired
versus applied state; a model proposal cannot silently activate a scope.

### W4-04 — wallet and public-chain circulation

**Owned paths:** `crates/joshi-wallet-source`, `crates/joshi-wallet-topology`, a new typed
wallet/topology store admission adapter, and wallet circulation goldens.

**Walking seam:** exact Helius/Solana frame -> evidence batch -> retained raw transaction -> pinned
decoder result -> transaction fact version -> caller/transfer/swap/bundle facts -> store-verified
coverage -> immutable topology snapshot -> Glass/export.

The lane must connect the existing offline planner and reducer to real store receipts. It must add
the pinned Pump/PumpSwap decoder and differential vectors before calling a swap exact. Helius
Enhanced remains a quarantined vendor projection. Processed notifications are provisional; later
finalized/canonical or noncanonical versions append and drive a new snapshot without rewriting the
old one.

**Gate:** one retained finalized public-wallet acquisition round-trips exact bytes, many facts, and
coverage; a supplied noncanonical/later-known correction remains observable but disappears from an
earlier accepted snapshot; no cursor advances before receipt; no address is labeled a person,
owner, insider, or skilled wallet.

### W4-05 — social, attention, lifecycle, and pool-state circulation

**Owned paths:** strict adapters around `crates/joshi-attention`, protocol/lifecycle decoders, and a
new store-backed market-state reducer. It does not own source authentication or Glass schemas.

This lane keeps four streams separate until an explicit point-in-time projection joins them:

- **social/product:** callout, community, follow, content revision, identity link, and transition
  occurrences with private/public protection and later-known identity handling;
- **lifecycle:** Pump creation/completion/migration/creator/fee/share program facts, with product
  hints retained as provider assertions rather than chain truth;
- **pool state:** coherent finalized account closures for Pump curve, PumpSwap, and the one selected
  DLMM position/pool, including mint/token extensions, fees, vaults, bins, and unsupported fields;
  and
- **attention:** marked forcing events, selected-as-known identity/territory/cluster context,
  presentation context when actually witnessed, response coverage, and explicit censoring.

All joins run `valid-at AND known-by AND effective-as-known`, plus chain finality/slot when
applicable. The direct/companion capture-snapshot interval remains an attestation interval and may
not become eternal object validity.

**Gate:** one real source occurrence of each enabled family can be followed from observation to
typed snapshot and back to evidence; a future identity/territory/cluster correction cannot enter
the old scene; a pool account bundle that is mixed-slot, incomplete, or unsupported refuses rather
than manufacturing a quote or LP value.

### W4-06 — durable deterministic projection publication

**Owned paths:** `crates/joshi-projection`, a new `crates/joshi-publication`, and core/store
publication adapters owned jointly through W4-00 review.

**Input seam:** an explicit catalog cutoff, full as-of vector, effective assertion refs,
finalized wallet effects, verified asset definitions, coherent protocol states, coverage, and
calculator build/configuration.

**Output seam:** exact `ProjectionArtifactV1` bytes plus one append-only
`ProjectionPublicationV1` that names result digest, input closure, commit range, publication
commit, superseded publication, and authority `read_only_no_execution`.

Publication is one transaction: immutable artifact bytes are prepared and verified, the projection
checkpoint and publication row are committed, and only then may a cockpit-head record name them.
Failure leaves the prior publication available as explicitly stale; it cannot expose half a new
projection. There is no in-memory `latest` registry. “Current” means the newest append-only
publication selected by a named query policy, with its exact commit and freshness visible.

Wave 4 keeps finalized accounting separate from provisional market observation. If fast provisional
state is shown, it uses a distinct source/market snapshot contract and cannot populate landed
balances, realized PnL, lots, or finalized projection fields.

**Gate:** full rebuild and incremental publication over the same cutoff produce identical exact
bytes/digest; crash at every prepare/commit/head transition exposes either the prior complete
publication or the new complete one; missing/stale/conflicting/unsupported never becomes zero.

### W4-07 — production export and restricted model readback

**Owned paths:** `crates/joshi-export`, `analysis/`, a new artifact-admission crate, and export/model
goldens. Store registration remains behind W4-00-owned typed APIs.

**Production export path:**

```text
explicit catalog cutoff + publication IDs
 -> consistent read-only store snapshot
 -> fourteen typed relations (or a versioned successor)
 -> temp Parquet parts + exact manifest
 -> independent Rust re-read and Python semantic validation
 -> immutable directory rename
 -> typed store registration after both validations
```

The exporter queries the operational store; it does not rewrite the Python fixture. Empty optional
relations remain valid empty relations. Every event/observed/available/decision clock, choice set,
coverage row, provenance edge, asset unit, and point-in-time cutoff is derived from stored data and
checked. If Wave 4 facts require a shape not representable by snapshot V1, publish snapshot V2;
never loosen V1 until it happens to accept a different meaning.

**Model/analysis readback:** core accepts only an immutable, bounded artifact whose exact bytes,
schema, logical/physical digests, producer/build/config, input snapshot, fit cutoff, maximum input
availability, support, coverage/gaps, uncertainty, and restrictive claim scope validate. The
artifact is registered under a derived-analysis family, never inserted into observations,
protocol facts, financial effects, or effective assertions.

The first operational readback is deliberately modest: the existing descriptive analog, kernel,
or field job over the production snapshot. Glass may show it as `model_inference` or
`descriptive_noncausal`; it may not use it to rank the census or activate a hot scope without a
separate operator-accepted proposal.

**Gate:** a Rust store-derived snapshot independently passes Python, a future-known adversary fails,
the analysis run is byte-reproducible, altered output bytes fail import, and importing the artifact
does not change any prior evidence/projection digest.

### W4-08 — same-origin, paired, presentation-complete Glass

**Owned paths:** `apps/glass`, core static-serving/session routes through W4-00 review, and Rust
presentation admission.

Core serves the pinned production Glass assets and API from the same exact loopback origin. There
is no CORS wildcard, cross-origin mutation mode, token in a query string, bundled environment,
cookie, `localStorage`, or `sessionStorage`.

The pairing flow is explicit:

1. core creates a short-lived one-time pairing code and prints it only to the local terminal or
   approved native launcher;
2. Ember enters it into the same-origin Glass shell;
3. a bounded same-origin exchange consumes the code once and returns a short-lived, revocable,
   evidence-only session capability;
4. TypeScript keeps that capability only in memory and sends it in the existing pairing header;
   reload/expiry/revocation requires pairing again; and
5. provider, companion, spool-encryption, and future wallet credentials are different capabilities
   and can never satisfy this endpoint.

The server checks exact Host/Origin and Fetch Metadata posture, rejects cross-origin/preflight
traffic, compares capabilities in constant time, rotates/revokes sessions, and never logs or
serializes secret bytes. Only a minimal health/static shell is available before pairing; private
operational reads and all evidence writes require the scoped session. The existing unpaired fixture
read remains an offline/test contract, not the production exposure policy.

The first screen opens an explicit durable `CockpitPublicationV1`, which names immutable scene and
projection IDs. A new publication appends and supersedes; it is not an unversioned mutable
`latestScene` pointer.

Wave 4 also mounts strict Rust admission for the TypeScript presentation policy, bundle, staged
scene, and ordered post-mount events. Reveal follows the exact durable scene receipt. Choice-
sensitive commands use command V2 or a separately admitted exact command-to-presentation binding;
V1 commands remain visibly presentation-incomplete.

**Gate:** an attached browser—not a mocked `fetch`—performs pairing, loads an explicit publication,
parses the exact snapshot, stages presentation before reveal, records actual visibility/focus, sends
one semantic command, retries it idempotently, restarts core, and replays the witnessed scene. Axe,
keyboard, screen-reader, zoom, narrow layout, and target-size checks pass on the real operational
data path.

### W4-09 — host repair, replica, and deployment artifacts

**Owned paths:** `deploy/`, host preflight/renderers, and remote service packaging. No host may be
mutated by implementation of this lane.

Current facts remain blocking:

- `persvati` runs Ubuntu 25.10 after its July 2026 end of support;
- `hbox` runs Ubuntu 24.10 after its July 2025 end of support;
- `persvati` has unproven lid/suspend/restart continuity;
- `hbox` has memory/swap pressure, encryption disabled, and a single-device ZFS special-vdev
  failure risk;
- Tailscale reachability was asymmetric; and
- neither host is authorized for repair, credential placement, service installation, or start.

The lane first produces a dry-run mutation packet for Ember: supported-OS target verified at action
time, exact users/groups/paths/modes, artifacts and digests, service/unit diff, resource limits,
credential purposes, listener/firewall/Tailscale changes (normally none), reboots/canaries,
rollback preserving evidence, and every destructive or paid action separated.

After separate approval only, repair and qualify `persvati` as the first collector and `hbox` as a
ciphertext replica. Use system services under a locked identity, application-encrypted private
segments, no public listener, no wallet material, and exact replica generation. `hbox` is not the
sole copy. A supported-LTS Hetzner host remains an optional later purchase only if measured local
continuity—not ambition—earns recurring cost.

**Gate:** the `persvati` 24-hour canary proves restart/suspend/network recovery and exact gaps;
`hbox` proves bounded memory, ZFS health visibility, ciphertext-only replication, pause/catch-up,
and corrupt segment quarantine. Until then the root witness status is
`operational_local_only`, never `remote_resilient`.

### W4-10 — observability, backpressure, backfill, and recovery

**Owned paths:** a shared operational-status crate, finite-cardinality metrics, health/query DTOs,
and fault-injection fixtures. Logs are diagnostics, not evidence.

Every source/scope publishes a readiness vector rather than `healthy: true`:

```text
source generation and last frame
local spool ready bytes/oldest age/control reserve
replica ACK lag and generation
catalog admission lag and last closed receipt
cursor scope and open gaps/recovery state
normalizer/quarantine/drift counts
projection publication and lag
Glass presentation/command capture status
export/model artifact age
disk/inodes, CPU/RSS/FD, restart and clock-sync state
quota/native-unit/currency budget remaining
```

Metrics labels are finite source/status classes—never mint, wallet, URL, error text, social text, or
credential. Detailed subject diagnostics are bounded authenticated queries backed by durable
records.

Helius gaps may close only after bounded HTTP backfill commits exact recovered evidence and a later
recovery record. PumpPortal live-only gaps remain unrecoverable unless a different source supplies a
separately named cross-source reconstruction. Product/Pump pagination gaps remain scoped; an empty
later page is not recovery proof.

**Gate:** inject disconnects, 429/auth rejection, malformed/drifted data, disk pressure, full
queues, Mac downtime, remote downtime, replica corruption, projection failure, browser disconnect,
and clock steps. The system degrades in the declared order, exposes every gap, drains at more than
the admitted arrival rate after recovery, and never derives truth from logs.

### W4-11 — prospective operator episode and integration verdict

**Owned paths:** one preregistered episode protocol, private operator artifact policy, and the root
witness assembly owned through W4-00.

The first episode is a 30–90 minute ordinary observation session, not a profit test:

1. freeze run/build/config/budget IDs, enabled sources, census definition, hot capacity, launch
   publication, and later outcome horizon before looking at the session;
2. begin from the actual witnessed census eligible set, not a coin selected after it moved;
3. Ember nominates one candidate or explicitly abstains;
4. the controller requests and receipts a bounded hot scope;
5. Glass reveals one presentation-complete scene with coupled wallet/social/lifecycle/pool/source
   context and honest gaps;
6. Ember records a disposition, acceptable-inventory note, chart/field gesture, explicit choice, or
   abstention in the vocabulary that feels natural;
7. if Ember independently acts in Pump/Padre/wallet software, Joshi later observes the effect; no
   action is required for the episode to pass;
8. at the frozen horizon, generate a distinct retrospective scene and optional interview after the
   contemporaneous account is durable; and
9. export the store-derived snapshot, run one descriptive analysis, import it as a restricted
   artifact, restart, and replay.

The pass condition is instrumentation and usefulness: the episode is recognizable to Ember, the
choice/abstention and actual information surface are durable, no clerical step corrupts the
decision, and later knowledge stays out of the witnessed scene. Profit, a trade, a prediction, or a
model win is not required.

## 7. Dependency order

The dependency graph is deliberately strict:

```text
W4-00 public receipts/schema/witness skeleton
   |
   +--> W4-01 supervisor/spool ----------+
   +--> W4-02 Pump parity ---------------+--> W4-03 census/hot
   +--> W4-08 same-origin session shell -+          |
   +--> W4-10 status vocabulary --------------------+
                                                     |
                 +----------------+------------------+
                 v                v
              W4-04 wallet     W4-05 social/lifecycle/pool
                 +----------------+------------------+
                                  v
                         W4-06 publication
                            |            |
                            v            v
                        W4-08 Glass   W4-07 export/readback
                            +------------+
                                  v
                         W4-11 prospective episode

W4-09 remote dry-run can proceed after W4-01 CLI/config freeze;
actual repair/deployment requires separate approval and is not inferred from this plan.
```

Implementation phases:

1. **Contract closure:** exact receipts, migrations, local spool-to-store fixture, publication
   store seam, presentation Rust goldens, production snapshot input query.
2. **Local continuity:** run the supervisor and spool on the Mac against fake providers, then one
   separately authorized bounded real source set. Prove restart/backlog/gaps before remote work.
3. **State circulation:** connect wallet and one hot mint's attention/lifecycle/pool closures to
   durable reducers and publication.
4. **Operational Glass and export:** same-origin paired browser, staged presentation, production
   Parquet, restricted artifact readback.
5. **Prospective use:** one episode and root witness.
6. **Remote resilience:** only after approved host repair; replace `operational_local_only` with
   `remote_resilient` after the 24-hour canaries.

A lane cannot make its fixture “operational” by bypassing an upstream phase. In particular,
presentation breadth waits for publication; model display waits for production export; remote
deployment waits for local supervisor recovery; and prospective claims wait for the attached
browser path.

## 8. Exact walking paths

### 8.1 Source durability and outage path

```text
reserve acquisition ID + fsync
 -> issue reviewed read / receive WS frame
 -> retain exact bytes and source clocks
 -> construct lossless batch + scoped gaps
 -> seal and append exact spool segment
 -> local spool ACK
 -> optional replica transfer + remote ACK
 -> Mac importer verifies/decrypts/decodes
 -> store atomic commit + durable receipt
 -> catalog admission ACK recorded in spool
 -> authoritative cursor/as-of becomes queryable
```

Test crashes before/after every arrow. Mac downtime must create backlog, not pressure to grant the
remote spool semantic authority.

### 8.2 Census-to-hot-to-scene path

```text
launch/migration/product-board occurrence + coverage
 -> committed census projection and exact eligible universe
 -> explicit operator/attention/wallet reason
 -> HotScopeIntent with TTL and hard multidimensional budget
 -> per-source desired/applied/acknowledged state
 -> exact hot wallet/social/lifecycle/pool evidence
 -> point-in-time reducers
 -> deterministic projection publication
 -> immutable cockpit publication
 -> paired Glass presentation receipt before reveal
```

When a source fails, the scene retains the candidate and displays the failed family/gap. It does not
quietly remove the subject and improve apparent coverage.

### 8.3 Wallet and LP exposure path

```text
finalized public wallet/account observations
 -> independent landed effects and asset definitions
 -> exact lots/basis quality/episodes/inventory epochs
 -> coherent pool/position/bin closure
 -> exact mark, size quote/refusal, whole-position quote, LP inventory/action models
 -> finalized read projection
 -> Glass coupled spot + LP inventory rail
```

Deposits/withdrawals remain custody changes, not PnL. Principal, fees, rewards, rent, quotes, modeled
rebalance, and landed effects remain separate. The routed-liquidity views may display ghost-edge and
joint-policy research, but no Wave 4 object says the ghost routed, the modeled action is supported,
or a fee counter is profit.

### 8.4 Export and model-readback path

```text
named store cutoff + publication closure
 -> immutable Parquet snapshot
 -> independent validator receipt
 -> deterministic descriptive/model job
 -> immutable artifact manifest
 -> strict readback admission under derived authority
 -> later Glass scene references artifact ID/digest
```

No arrow returns to observation, settlement, wallet effect, or exact projection. A later artifact
can propose an attention subject only through an explicit proposal and operator acceptance in a
new scene.

### 8.5 Prospective choice path

```text
actual census universe
 -> explicit launch publication
 -> staged presentation + receipt
 -> actual visibility/focus events
 -> presentation-bound choice or abstention
 -> optional later external wallet effect
 -> fixed-horizon outcome/censoring
 -> distinct retrospective scene
 -> production export and replay
```

The witnessed scene is immutable. The later result never rewrites what Ember saw, believed, or
could choose.

## 9. Initial data, compute, and cost budgets

Budgets are part of the source contract, not a dashboard afterthought. These are Wave 4 S0 hard
ceilings; a measured review may lower them. Raising them requires a new configuration version and,
where money/native units or provider terms are affected, explicit Ember approval.

| Resource | S0 ceiling / target | Failure behavior |
| --- | --- | --- |
| concurrent hot mints | 5 | refuse/queue nomination; retain census |
| explicitly watched wallets | 10 public keys | refuse expansion; never recurse funders/counterparties |
| metered PumpPortal hot feed | disabled, zero authorized native-unit spend | remain census/public/Helius; show unavailable |
| authenticated Pump direct | one route under Ember-present parity; no unattended auth expansion | stop route and open scoped gap |
| direct Pump run | inherited max 20 attempts, max 3 attempts/request, >=1.1 s/host, 2 MiB body | stop; never auto-increase |
| companion response/batch | inherited 512 KiB response, 256 KiB batch, reserved gap queue | pause fail-closed if gap reserve fails |
| store admission | inherited max 256 observations and 4 MiB raw bytes/batch | split before admission or refuse |
| collector evidence queue | 4,096 records **and** 64 MiB byte permits | stop source generation; append saturation gap |
| retained spool growth | hard 1 GiB/day S0 and configured total root cap | degrade enrichment/hot breadth, then stop |
| segment size | 32 MiB maximum outer envelope for S0 | seal earlier; oversized occurrence becomes explicit gap/refusal |
| Glass snapshot/command | inherited 4 MiB / 64 KiB | bounded error; no truncated valid DTO |
| source -> local durable | p99 under 2 s in normal canary | alert/degrade; never ACK early |
| connected spool -> catalog | p95 under 30 s; drain capacity >=2x admitted arrival | show backlog/catalog lag |
| committed hot fact -> publication | p95 under 5 s at S0 | serve prior publication as stale |
| local semantic command receipt | p95 under 250 ms, none over 1 s in ordinary S0 | retain/retry exact command; surface lag |
| remote replica recovery | recover within 5 min when path returns; alert by 15 min | keep local spool; no deletion |
| collector host use | average <=1 logical CPU and <=2 GiB RSS; no sustained PSI | reduce source breadth or stop |
| free storage | greater of 20% and 100 GiB, with inode floor also configured | stop before floor |

Provider quotas are declared in provider-native units. Helius plan limits and remaining capacity
must be observed from Ember's actual account before a canary; they are not inferred from a marketing
tier. Local estimates are reconciled against provider billing observations and never called an
invoice. Automatic overage, plan upgrades, and cross-source borrowing are disabled.

The 1 GiB/day spool cap is a canary ceiling, not a retention promise. The target operating band from
the remote inventory is 0.1–1 GiB/day. Measure amplification into blobs, SQLite, WAL, backups,
Parquet, and analysis artifacts before choosing retention. Private raw social evidence remains
off by default and purpose/expiry-bound when enabled.

## 10. Degraded operation and recovery rules

The system should remain useful when one family is bad, but it must never make absence look like a
healthy zero.

| Failure | Continue | Mark unavailable or refuse |
| --- | --- | --- |
| social/Pump auth unavailable | chain census, wallet, lifecycle, exact public enrichment | social parity, follow/community completeness |
| PumpPortal disconnected | Helius/public chain and prior census with gap | live-only missing interval; no fake recovery |
| Helius WS gap | current provisional observation if labeled; bounded HTTP recovery | finalized completeness/cursor until recovery commits |
| wallet finality lag | source/market views and prior finalized projection | new landed balances/PnL |
| pool bundle mixed/stale | wallet quantities and source evidence | quote, LP action, liquidation |
| projection failure | prior immutable publication as stale | new head/current claim |
| presentation admission failure | safety information with explicit unwitnessed gap | witnessed-presentation claim |
| analysis/export failure | operational cockpit | model/analysis freshness; no substituted old score |
| Mac offline | remote/local collector spool within cap | catalog-as-of, publication, command writes |
| replica offline | local spool and catalog | off-site durability claim |
| disk/control reserve threatened | health/gap/control records | new evidence capture before hard floor |

Backfill appends new acquisitions and recovery facts. It never changes the original outage or
pretends later knowledge was available in an earlier scene. A source replacement is a new source
and comparison contract, not transparent continuity.

## 11. Security and privacy gates

- Source credentials are purpose-specific owner-only paths, loaded only by their adapter, never
  command arguments, serializable config, evidence URLs, logs, or support archives.
- Pump session material stays on the Mac for the Ember-present parity path. It is not a remote
  collector credential.
- Companion pairing, Glass session pairing, source credentials, spool encryption keys, and any
  future wallet capability are mutually non-interchangeable.
- Private segments are AEAD-sealed before leaving the origin. Replica hosts lack private-domain
  decryption keys. Content hash does not authorize cross-protection-domain physical deduplication.
- Social/profile text is hostile data. It is rendered as text, never instructions to tools or an
  LLM. Model export requires an explicit restricted derivative and purpose review.
- Same-origin Glass has no CORS fallback. Loopback bind, exact Host/Origin, body/rate/concurrency
  limits, one-time pairing, capability expiry/revocation, CSP, and secret redaction are release
  gates.
- Static assets, API responses, errors, traces, metrics, manifests, screenshots, crash bundles, and
  repository fixtures all receive secret-canary tests.
- Backup/restore preserves protection classes. Material deletion and key destruction remain
  separately authorized, append-only facts and are deferred from Wave 4.

## 12. Non-gameable acceptance gates

The following rules prevent a beautiful fixture from impersonating an operational instrument:

1. **Prospective means non-fixture.** The episode source occurrences, census membership,
   presentation events, and operator command originate after the registered run start. Synthetic
   injections may test failures but cannot satisfy the prospective support count.
2. **No hand-authored closure.** The root witness derives IDs/digests/counts from the store, spool,
   publication, browser receipts, and immutable artifacts. A manually edited JSON manifest fails.
3. **No ACK substitution.** Local spool, replica, HTTP, store, publication, presentation, export,
   and artifact-import receipts are distinct and exact.
4. **No fixture exporter.** The accepted snapshot originates from operational store rows at the
   named cutoff; rewriting `analysis/fixtures/snapshot_v1` does not pass.
5. **No mocked browser.** At least one attached production build completes same-origin pairing,
   explicit launch, staged reveal, actual focus/visibility, command, and replay.
6. **No source silence as success.** Each enabled source has positive coverage or a scoped gap.
   The eligible census denominator and evicted/rejected hot intents remain visible.
7. **No later-known leakage.** A correction with earlier valid time but later availability is
   introduced before qualification; it cannot change the witnessed scene or fit input.
8. **No model authority.** Importing or displaying an artifact cannot modify facts, exact financial
   projection, census order, or source leases. Operator acceptance is separately recorded.
9. **No width coercion.** u64/u128/U256/rational boundaries survive Rust/JSON/Arrow/Python, or the
   affected row refuses. `int64` prototypes cannot silently accept wider market values.
10. **No green-by-omission.** Full workspace, schema upgrade, companion, Glass, analysis, host
    preflight, dependency graph, backup/restore, kill/retry, and prospective evidence checks are
    all listed in one witness. Unsupported lanes remain red, not omitted.
11. **No cash or PnL gate.** A profitable manual outcome cannot rescue failed evidence or security.
    An abstention can satisfy the episode if the instrument and choice closure are genuine.
12. **No remote fiction.** A supported-host 24-hour canary is required for
    `remote_resilient`. EOL inventory or a local filesystem simulation can prove code only.

## 13. September and cash corridor

Runway pressure is real, but revenue is not an engineering milestone and Wave 4 does not claim it
will produce income. The pre-September incremental infrastructure budget remains **$0**. Existing
provider quotas are not free unless remaining capacity, renewal, contention, and overage behavior
are known. No date widens a source, retention, or authority budget automatically.

The pre-September critical path is intentionally smaller than all of Wave 4:

1. local supervisor/spool-to-store continuity using existing hardware and already intended source
   access;
2. one real census-to-hot subject with wallet/lifecycle/pool state and honest social availability;
3. durable finalized projection publication;
4. same-origin paired Glass with one presentation-bound prospective choice or abstention; and
5. one production store-derived export plus restricted descriptive artifact readback.

Remote OS repair/deployment, multiple Pump authenticated routes, broad social history, extended
model work, and routed-liquidity counterfactual breadth do not get to delay that loop. They remain
Wave 4 lanes, but a smaller truthful local instrument is the September deliverable.

Use these checkpoints rather than a promise of revenue:

| Checkpoint | Question | Continue criterion | Honest fallback |
| --- | --- | --- | --- |
| local continuity | can evidence run for 24 h without silent loss or clerical rescue? | bounded gaps, restart, drain, exact receipts | session-bound collector and exposure notebook |
| natural use | does Ember voluntarily use the surface for one real decision? | recognizable scene, low enough burden, material cues present | exact-mint/manual nomination workbench |
| source value | does the census/hot split expose useful context? | honest denominator and at least one useful promoted scope | chain observatory plus Pump-present companion |
| research closure | can actual scenes become valid immutable research input? | production export and restricted artifact readback | retain evidence/scenes; stop model expansion |
| August 30 runway review | is the next marginal slice clearer than its upkeep/cash cost? | continue one named lane | hold, pivot, shrink, or stop expansion |

At the runway review, report engineering/operator hours, incremental cash/native-unit use, local
disk/backup runway, covered versus gapped time, source burden, voluntary use, reconciliation
quality, and the single next marginal capability. Do not report hypothetical strategy value as
revenue. A tool that prevents exposure mistakes, preserves decisions, and improves exploration may
be useful before it predicts anything; if it is not naturally useful, stop platform expansion
rather than adding models or execution.

## 14. Single root readiness and witness artifact

Wave 4 has one root verifier:

```text
./scripts/wave4-readiness \
  --state <read-only-or-restored-catalog-root> \
  --prospective-session-id <session-id> \
  --output <empty-output-directory>
```

The command itself opens no provider socket, changes no remote host, and has no economic
capability. It runs the locked offline workspace/schema/browser/analysis/authority gates, verifies
a previously captured prospective session from durable state, performs backup/restore and replay,
and writes exactly one immutable root artifact:

```text
joshi.wave4.operational_witness/v1
```

The witness contains:

- self-derived witness ID/digest, exact canonical bytes, build/source/lock/config digests;
- run class (`prospective`), authority ceiling, host topology class, catalog/schema and commit
  range, full as-of vector, start/end clocks, and protection summary;
- source generations, pre-I/O reservations, exact spool segments, local/remote/catalog ACK closures,
  scopes, cursors, coverage, gaps, backfills, and quarantine facts;
- census universe, hot intent/desired/applied/closed records, budgets and actual use;
- wallet/topology, social/attention, lifecycle, and pool artifact IDs and point-in-time closure;
- projection artifact/publication/cockpit-head IDs and exact digests;
- Glass build, pairing-session occurrence (never secret), launch scene, presentation plan/receipt,
  actual exposure events, command V2/binding, choice or abstention, and witnessed replay digest;
- production export snapshot/parts/validator receipt and restricted model artifact/import receipt;
- backup/restore, integrity, foreign-key, blob, replay, restart, backlog-drain, dependency-authority,
  secret-canary, accessibility, and budget reports; and
- explicit disposition for authenticated Pump parity and remote resilience, including a stopped or
  unavailable result rather than omission.

The witness status is one of:

- `qualified_remote_resilient`: all operational gates plus approved supported-host canaries pass;
- `qualified_local_operational`: the continuous local exocortex and prospective path pass, while
  remote repair/deployment remains explicitly absent;
- `useful_partial`: a named smaller loop passes but one or more required operational joins remain;
  or
- `not_qualified`: a hard semantic, security, recovery, cost, or prospective-use gate fails.

Only the first two complete the corresponding Wave 4 claim. A pure fixture run, hand-authored
episode, rewritten fixture export, mocked browser, EOL-host simulation, or profit outcome cannot
produce either qualified status.

## 15. What Wave 4 explicitly defers

Wave 4 does not implement or authorize:

- transaction simulation, instruction/message construction, signing, submission, rebroadcast,
  Jito, relaying, or automated cancellation;
- live crackle execution, copy trading, model-directed trading, automatic exit/re-entry, or a
  “crackle profit engine”;
- LP add/remove/rebalance/claim/close/open, pool creation, a ghost edge on chain, or self-routing;
- a signer-shaped API hidden behind a feature flag;
- a causal claim that callouts, wallets, chart shapes, fields, or external liquidity cause returns;
- automatic model ranking, online learning, a feature store, vector database, model service, GPU
  service, or LLM agent in the operational truth path;
- full Pump replacement, complete social history, global wallet graph crawl, identity
  deanonymization, or broad private-content retention;
- public/multi-user hosting, mobile/desktop packaging, remote control, a second catalog writer,
  PostgreSQL migration, Kafka, ClickHouse, or a lakehouse;
- paid Hetzner or managed streaming without a measured need and explicit purchase authorization;
- material deletion, key destruction, or retention automation; and
- a promise of profitability, September revenue, or validation of Ember's strategies.

Routed-liquidity work in Wave 4 is observation and counterfactual instrumentation only: coherent
pool/bin state, exact exposure, route/quote/refusal, ghost-edge replay inputs, one consolidated
spot/LP book, and accessible policy/perception capture. The slow edge, medium schedule, and fast
spot clocks remain distinct proposals. No bin width is optimized into live capital and no
modeled-only rebalance becomes an available action.

## 16. Stop and reduction rules

Reduce or stop Wave 4 rather than widening authority when:

- the local collector cannot run 24 hours without silent loss or constant manual repair;
- direct Pump parity requires credential mining, evasion, broad private retention, or an unstable
  route whose drift outruns review;
- census coverage is too partial to support the stated denominator;
- source/store adapters require lossy defaults or make later-known data enter old scenes;
- exact wallet/pool closure cannot be reconciled for the prospective subject;
- same-origin pairing/presentation capture adds enough friction that Ember abandons the surface;
- production export cannot reproduce point-in-time/coverage/provenance semantics;
- a model artifact cannot be kept visibly separate from observed/deterministic truth;
- remote continuity requires unsafe EOL deployment, destructive storage work, or unapproved spend;
  or
- the operator loop is not voluntarily useful after repair of material truth/latency defects.

The reduction ladder is:

```text
full remote-resilient exocortex
 -> local continuous census/hot cockpit
 -> session-bound Pump companion + continuous chain observatory
 -> exact-mint/manual nomination exposure and replay instrument
 -> immutable scene/evidence notebook
 -> stop expansion while retaining fixtures, facts, and recovery measurements
```

Every rung is honest and preserves future option value. None needs a trade to justify the evidence
it collected.

## 17. Completion judgment

Wave 4 should proceed. Waves 1–3 have already answered the “is bespoke infrastructure foolish?”
question: generic off-the-shelf software can supply transports, storage, codecs, UI components,
and analytical engines, but it does not supply JOSHI's actual object—Ember's point-in-time,
coverage-aware, presentation-aware, spot/LP-coupled observation and decision process. The bespoke
part is the meaning and the joins, not reimplementing commodity machinery.

The next risk is no longer that the repository lacks serious ideas or type systems. It is that the
project could keep producing beautifully isolated artifacts and never become an instrument Ember
inhabits. Wave 4 is successful when the same exact evidence can survive source failure, spool,
catalog admission, projection, Glass, operator interpretation, export, analysis, restart, and
retrospective replay—without inventing completeness, authority, or profit anywhere along the way.
