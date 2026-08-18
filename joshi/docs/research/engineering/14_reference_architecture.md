# Engineering lane 14 — reference architecture

Status: concrete pre-engineering reference; no implementation or live-capital authorization.

This document derives a physical architecture from the accepted semantic foundation. It is an
implementation hypothesis for Spike 0 and Slice 1, not a commitment to a universal platform. It
may be revised when source volume, Pump access, operator use, or replay measurements disagree.

## Decision in one page

Use a **local modular core with one authoritative writer**, a browser cockpit, and a small number
of replaceable local collector processes only where runtime compatibility or fault isolation earns
them. Persist immutable acquisitions and operator records in a transactional local store; persist
large or exact source bytes in a content-addressed local blob directory. Build assertions,
bitemporal identity, accounting, episodes, scenes, and replay as versioned modules and rebuildable
projections over that evidence.

The source architecture is a modular monolith. The initial deployment is a modest multi-process
local application:

```text
                          Ember
                            |
                     local browser UI
                            |
                    loopback API / stream
                            |
                    +-------v--------+
                    |   joshi core   |
                    | command/query  |
                    | one DB writer  |
                    | projections    |
                    | replay         |
                    +---+--------+---+
                        |        |
             local IPC |        | local files
                        |        |
          +-------------+--+   +-v----------------+
          | source runners |   | transactional DB |
          | chain / Pump   |   | + hashed blobs   |
          | social / quote |   +------------------+
          +----------------+
```

This is not a service architecture. Collector runners have no database credentials, no UI command
authority, and no wallet authority. They send acquisition records through a bounded local ingest
contract. The core owns append, cursor commits, gestures, scenes, queries, and projection
checkpoints. A runner may initially be an in-process task when its dependencies and failure profile
are ordinary; moving it out of process must not change semantic contracts.

The present graph is entirely read-only with respect to money. It contains no wallet secret,
transaction builder, signer, broadcast client, or transaction endpoint. Manual Pump/Padre actions
are external events later observed through public wallet state.

The minimum concrete implementation hypothesis, to be accepted only after Spike 0, is:

- TypeScript for the browser cockpit;
- a Python core for source coordination, exact projections, replay, local API, and research
  interoperation;
- Node/TypeScript runner processes only when an official SDK or reviewed browser-side integration
  makes them the faithful adapter;
- a local transactional database, with SQLite as the Slice 1 default candidate;
- a content-addressed local blob directory for exact responses, screenshots, and larger source
  artifacts;
- no Rust, graph database, message broker, columnar warehouse, container orchestrator, desktop
  wrapper, or remote control plane until a measured constraint selects it.

The topology is more important than these languages. A different stack is acceptable if it keeps
the same ownership, clock, replay, and capability boundaries.

## Decision forces

Ranked roughly by importance for the first useful cockpit:

1. **Truth before feature breadth.** Raw observations, gaps, mutable identities, actual rendered
   scenes, and external wallet effects must remain distinguishable.
2. **Natural operator use.** Capturing a gesture and scene must remain on the hot path; annotation,
   analytics, and broad enrichment must not delay an exit or re-entry in an external tool.
3. **Local-first privacy and control.** Portfolio state, screenshots, notes, and interviews stay on
   Ember's machine unless a named export says otherwise.
4. **Replay from the beginning.** The first prospective gesture needs enough structured and
   perceptual context for witnessed replay; replay cannot be bolted onto mutable latest-state
   tables later.
5. **Evolving semantics.** Operator language, crackle types, social interpretations, identity
   links, and episode attribution will change. The storage boundary must preserve original acts
   and allow new assertions without rewriting them.
6. **Source drift and partial failure.** A single board, keyed subscription, parser, or social
   endpoint can fail while everything else appears healthy. Degradation is scoped evidence.
7. **Exact accounting.** Wallet effects, lots, basis quality, inventory epochs, partial exits, flat
   watching, and re-entry cannot be inferred from one position row.
8. **Economical census plus selective fidelity.** Whole-market observations must remain compact;
   high-cost trades, quotes, threads, media, and scenes belong to promoted hot scopes.
9. **Testable containment.** Collectors, models, UI, and later policy code should be incapable of
   silently mutating evidence or gaining authority from shared process state.
10. **A reversible path to scale.** Measured ingestion or replay pressure may later justify another
    process or store, but the initial system must not prepay distributed-systems complexity.

Latency matters, but a low-latency lie is not useful. For the present product, gesture durability
and hot-view freshness have priority over census enrichment and retrospective analytics.

## Semantic-to-physical mapping

The accepted foundation names a logical evidence tape, not one physical stream or universal table.
The reference mapping is:

| Semantic object | Physical owner | Persistence rule |
| --- | --- | --- |
| Observation | evidence store | append one acquisition attempt/result; never deduplicate the observation away |
| Blob | blob store | exact bytes by content hash; several observations may reference one blob |
| Coverage window/gap | evidence store | append scoped health and gap transitions; silence alone creates no zero |
| Assertion | assertion modules | append typed parser/reconciler claim with evidence and version |
| Derivation | projection/analytics module | append or cache output with full input manifest and producer version |
| Identity relation | identity module | append bitemporal typed assertion; never mutate a current creator column into history |
| Operator record | operator command module | append idempotent gesture/utterance/meaning record |
| Scene manifest | scene module | append immutable references to actual rendered state and watermarks |
| Financial ledger fact | wallet reconciler | append/rebuild exact portfolio-domain asset effects from chain evidence |
| Episode link/meaning | episode module | append attribution and interpretation over independent financial facts |
| Projection/checkpoint | named projection module | disposable, versioned, rebuildable; never source evidence |
| Journal | absent now | reserved for future durability-critical financial authority and submission |

Common fields should live in small reusable headers, but each object family keeps a typed payload.
Do not create one `events(kind, json)` table and call the schema flexible. That merely moves every
invariant into application conditionals and makes incompatible clocks and identities look alike.

## Reference component graph

### Current observational graph

```text
                        ACQUISITION PLANE

  reference surface   chain/RPC   social/Pump   quote providers
         |                |            |               |
         +------- source-specific runners/adapters ----+
                                |
                       ObservationDraft vN
                                |
                         bounded local IPC
                                |
                     +----------v-----------+
                     | ingest + one writer  |
                     | blob commit          |
                     | cursor/coverage tx   |
                     +----------+-----------+
                                |
             immutable observations / operator records
                                |
             +------------------+------------------+
             |                  |                  |
       parser/assertion   wallet reconciler   identity resolver
             |                  |                  |
             +------------------+------------------+
                                |
                   versioned projection modules
             market · choice · episode · accounting
                                |
                 query snapshots + view contracts
                                |
                     +----------v-----------+
                     | local cockpit UI     |
                     | rendered-set ack     |
                     | viewport + gestures  |
                     +----------+-----------+
                                |
                       scene/operator append
                                |
                        promotion controller
                                |
                  hot-scope commands to adapters
```

The acquisition plane supplies data. The control arrows from UI to promotion controller alter
observation fidelity only. They do not construct or authorize economic action.

### Conditional future authority graph

This graph is an extension point, not part of Spike 0 or Slices 1–4:

```text
operator capability -> policy/planner -> unsigned bytes -> independent guard
                    -> isolated signer -> durable issuance -> identical-byte submitter
                    -> chain observer -> reconciliation journal -> financial ledger
```

It must remain a separate review, process, key boundary, and journal. The observational core can
later supply immutable scene/quote/state references, but cannot acquire authority by adding a
module or configuration flag.

## Component boundaries and capabilities

| Component | External network | Durable write | Explicitly absent |
| --- | --- | --- | --- |
| Source runner | its reviewed source only | none; emits drafts to ingest | DB access, operator/portfolio read, transaction/signing authority |
| Ingest/writer | normally none beyond local IPC | observations, blobs, coverage, cursors, operator records, scenes, assertion/projection commits | source-specific interpretation, wallet key, broadcast |
| Parser/assertion worker | none or read-only local IPC | asks writer to append versioned assertions | mutation of observations, direct projection/UI writes |
| Projection/replay | none during ordinary replay | asks writer to commit checkpoints/derivations | source calls or effects caused by historical records |
| Wallet reconciler | reviewed read-only chain/RPC | asks writer to append asset assertions and checks | episode-story invention, key, transaction submission |
| Query service/core | loopback only | none except through command/writer path | provider secret exposure, arbitrary browser SQL |
| Browser UI | loopback core; explicit external links only | semantic commands through local API | provider keys, DB/filesystem access, signing/broadcast |
| Batch/model worker | named read snapshot; named model endpoint only if approved | versioned derivation through writer/import | live action, hot-scope widening, fact overwrite |
| Promotion controller | local runner IPC | hot-scope records through writer | capital authority, undeclared collection/export expansion |

“Asks writer to append” may be an in-process function call initially and local IPC later. It is one
logical mutation boundary, not a requirement that every pure reducer become a daemon.

### Source adapters and collector runners

Each adapter owns one external contract: endpoint/program, authentication mode, cursor semantics,
rate behavior, source-time precision, and safe redaction. It emits only:

- raw bytes or a content-addressable byte stream;
- request/receipt/source clocks and source-native locators;
- a declared parser/contract hint, not canonical domain facts;
- cursor/sequence and scoped coverage health;
- acquisition defects.

The adapter never writes database tables directly. It never imports episode, accounting, or UI
domain code. A source runner gets only the provider credential it needs and an output capability to
the local ingest socket. Board collection cannot read the portfolio; a social runner cannot open
arbitrary local files; a query-only quote runner cannot broadcast.

Some adapters may run inside the core during Spike 0. Promote one to a separate runner when any of
these becomes true:

- it requires a different language/runtime or fragile browser/SDK dependency;
- its reconnect/backoff loop can block or crash the core;
- it has bursty memory/CPU use;
- it needs an independently revocable credential;
- its rate limit or lifecycle needs independent supervision.

Process isolation is earned by a fault or dependency boundary, not created once per feed.

### Ingest and evidence writer

There is one logical writer for evidence metadata and cursors. Its transaction is the unit that
prevents a cursor from outrunning stored evidence. It performs:

1. envelope validation and size limits;
2. secret-canary/redaction checks;
3. content hash and blob durability;
4. observation append;
5. coverage/cursor append or update;
6. durable acknowledgement to the runner.

At-least-once input is expected. An observation attempt remains unique even when its blob repeats.
A source-native fact/event key is resolved later by typed assertion code. The writer must not
collapse equal payloads into one market event.

The initial local database has one write coordinator even if several collectors run concurrently.
Bounded per-source queues expose pressure. If a queue must shed work, the writer records a scoped
gap before or with the loss; it never silently preferentially lose high-activity intervals.

### Parser and assertion modules

Parsers consume observations and append versioned assertions. Each parser owns:

- accepted source contract versions;
- exact decode rules and unknown-field behavior;
- natural event/object keys;
- exact units and null/unknown semantics;
- evidence links and quality flags;
- supersession rules for corrected parser versions.

Unknown or drifted data remains raw and becomes `unparsed`, `partial`, or `quarantined`; it does
not halt raw acquisition and does not become a plausible default. An assertion is a claim made by
a parser/reconciler, not an eternal fact.

### Projection modules

Market lists, charts, identity views, accounting balances, episode rails, and research features are
named projections. A projection declares:

- input assertion/record kinds and schema versions;
- cutoff policy: availability time, event-valid time, finality, and source coverage;
- reducer/projection version and configuration;
- checkpoint position and output schema;
- taint/degradation propagation;
- whether deterministic rebuild is required.

The hot query path may update a projection incrementally. Full replay remains the correctness
oracle. A checkpoint is a cache: if missing or incompatible, rebuild from a declared boundary.

Slow analytics and LLM work are derivation producers, not synchronous projection dependencies.
They may lag without freezing charts, gestures, wallet reconciliation, or source health.

### Query service and UI

The query layer returns immutable response snapshots or a stream of versioned deltas. Every view
response names:

- query/view-contract version;
- evidence and projection watermarks;
- per-source health and freshness relevant to the view;
- observed/derived/operator/machine evidence class;
- omitted, stale, unquotable, conflicting, or tainted fields.

The browser has no provider secrets and no direct access to the evidence database. It cannot submit
arbitrary queries or write facts. Its write API accepts a small command set: rendered-set
acknowledgement, viewport change, operator gesture, utterance, correction, scene commit, and hot-
scope request.

Each command carries a client-generated idempotency key, client session and sequence, client wall
and monotonic time, UI build, currently rendered snapshot ID, and expected subject. A retry returns
the original receipt. List target identity is resolved from the frozen rendered snapshot, not from
the row currently occupying a screen coordinate.

### Promotion controller

The promotion controller translates observational acts into resource changes:

```text
exact-mint open / watch / arm-shadow / held / runner / watch-flat
        -> HotScopeDeclared(subject, reason, feeds, budget, TTL, scene)
        -> idempotent adapter subscription commands
        -> HotScopeActivated / Degraded / Expanded / Closed
```

A hot scope is typed and may later name a family, identity, wallet set, pool, or small composite.
The first implementation supports exact mint plus required wallet/venue accounts only. “No
inventory” does not close a hot scope while the episode is explicitly watching flat.

Promotion is budgeted: maximum concurrent scopes, feeds, quote cadence, media policy, and TTL are
configuration with visible exhaustion. A failed promotion leaves the coarse census intact and
shows the activation gap. Later model nominations remain proposals and cannot secretly expand
retention or external-model export.

## Persistence layout

### Transactional metadata store

SQLite is the leading Slice 1 hypothesis because the system is local, has one authoritative writer,
needs multi-object transactions for evidence/cursor and gesture/scene commits, and initially has
small concurrency. The choice is not irrevocable. Spike 0 must measure write volume, burst size,
query latency, replay cost, and database growth before acceptance.

Logical table families, not final DDL:

```text
acquisition
  observations, source_requests, source_cursors
  coverage_windows, coverage_gaps, acquisition_defects
  blobs, blob_retention_events

claims
  assertions, assertion_evidence, assertion_relations
  identity_assertions, identity_evidence
  derivations, derivation_inputs

operator
  client_sessions, rendered_list_epochs, viewport_events
  operator_records, utterances, scene_manifests, scene_artifacts
  hot_scope_records

portfolio
  portfolio_domain_versions, custody_members
  reconciled_asset_effects, balance_checks, basis_quality
  fill_assertions, attribution_records

projection control
  projection_versions, projection_checkpoints, projection_defects
  stored_view_snapshots
```

Frequently rendered projections may use ordinary indexed tables in the same database. Their names
include or reference a projection version. They remain replaceable.

### Content-addressed blobs

Exact HTTP responses, transaction/log bytes, media retained under policy, screenshots, and stored
render DTOs can exceed convenient row sizes. Store them under a content hash with:

- write to a same-filesystem temporary path;
- flush/durable rename before the referencing database transaction commits;
- byte length, content type, encoding, retention class, and hash in metadata;
- reference tracking and explicit tombstone/erasure events;
- restricted permissions for operator/private artifacts.

An orphaned blob after a crash is safe and may be reclaimed only after an audit proves it has no
reference. A metadata row pointing to a missing blob is corruption and visibly breaks the affected
replay.

Market evidence and private operator artifacts should use different retention classes, and
possibly different encryption keys/directories. Backups must respect hard-erasure policy; “deleted
from the live table but still served from a projection or backup” is not erasure.

### Analytical exports

Do not make notebooks query the live database with arbitrary writes. Produce versioned, read-only
snapshots/exports at named watermarks for heavier analysis. Columnar exports or an embedded
analytical engine may be added later as disposable accelerators. They never become the only copy of
evidence or the source of operator-facing current state.

## Immutable observations and versioned assertions

The core separation is physical enough to test:

```text
same bytes fetched twice
  -> two observations
  -> one shared blob

one observation re-decoded by parser v1 and parser v2
  -> two assertions
  -> v2 supersedes/disputes v1
  -> both retain observation evidence

two sources describe one chain event
  -> two observations
  -> source-specific assertions
  -> reconciliation derivation may identify one canonical event
```

Identity keys are typed. A Pump post ID, Pump profile/user ID, X numeric ID, Solana address, mint,
pool, transaction signature, and local episode ID never share an unqualified string namespace.
Content equality is blob identity, not fact identity. Two equal fills at different instruction
indices survive as different events.

Assertions contain `produced_at` and `available_at`; later corrected facts cannot leak into an
earlier knowledge cutoff. A source response observed now may assert an event-valid time in the
past. These clocks remain separate.

## Bitemporal identity and social state

Do not put mutable `creator`, `represented_person`, `community`, or `official` columns on the coin
row. Represent typed relations such as:

```text
IdentityAssertion
  relation_kind
  subject(namespace, id)
  object(namespace, id)
  valid_from / valid_to             alleged real-world interval
  known_from / known_to             interval Joshi held this assertion
  assertion_status                  asserted/disputed/superseded/retracted
  method / confidence vocabulary
  evidence assertion/observation ids
  resolver version / produced_at
```

An open interval is not forever; it means no closing evidence has been observed. Queries must name
both `valid_at` and `known_at` when history matters. A corrected identity closes system knowledge of
the old assertion without rewriting the scenes in which it was displayed.

Social transition state is a projection over typed evidence—fee routing, platform-authorized
claim, public participation, community structure, competing mints—not a mutable scalar attached to
one coin. The same bitemporal machinery supports coin-family and territory hypotheses later, with
distinct relation kinds rather than one generic graph edge. Ordinary relational tables and indexed
queries are sufficient until measured traversals justify a graph engine.

## Choice sets, rendered state, and scenes

The architecture preserves six different sets:

```text
census eligible
  -> source surface membership/order
  -> query response served
  -> client rendered
  -> viewport visible
  -> interacted / explicitly compared
```

The server can know the first three. The client must acknowledge the last three. A list epoch is
immutable once used as a gesture target. New ranking results create a successor epoch; UI numbers
may update in place while row movement is frozen.

At a consequential gesture, the client sends a compact scene draft containing:

- source/query snapshot and rendered-list epoch IDs;
- exact subject and target geometry;
- client-rendered card/workbench DTO hash;
- viewport, chart domain/crosshair/drawings, disclosure state, and originating navigation;
- quote, portfolio, episode, and identity view snapshot IDs actually displayed;
- UI build/feature flags and client clock health;
- optional utterance and optional already-captured app screenshot hash.

The core commits the operator record and semantic scene manifest in one transaction and returns a
receipt immediately. Screenshot/perceptual capture is best effort and may attach afterward through
a separate idempotent record; it must not delay a time-sensitive gesture. A small app-scoped ring
buffer can preserve the immediately preceding render state without recording unrelated windows or
continuous video.

Witnessed replay renders the stored view DTO and scene state first. It does not depend on current
parsers producing the same answer. The product version and optional screenshot remain perceptual
checks. Knowledge-cutoff and retrospective replay are separate recomputations.

## Episode, portfolio, and accounting projections

The financial path and operator story meet only through append-only attribution:

```text
chain observations -> reconciled portfolio asset effects -> exact ledger projection
                                                      |
operator records -> episode/meaning projection -------+--> attribution view
```

The wallet reconciler owns portfolio-domain membership by version and produces exact token/SOL
effects, internal-transfer classification, fees/rent/rebates, balance checks, and basis quality.
The exact ledger closes without an episode ID. Unknown basis remains unknown.

Named projections then build:

- finalized and provisional balances by custody location and portfolio domain;
- exact acquisition lots and remaining quantities;
- average-cost operational basis within each inventory epoch;
- realized proceeds and PnL under a named convention;
- current full-size executable liquidation observations, never substituted by chart marks;
- inventory epochs bounded by exact portfolio-flat;
- operator episodes that may span several epochs and flat-watch intervals;
- optional management tranches only when prospectively asserted;
- episode rail rows combining financial facts, operator meaning, quote age, and gaps.

An external wallet transaction can create a provisional inventory epoch before its intent is known.
The UI invites an attribution link; declining or not knowing leaves it unattributed. A later
interview is a later assertion, not retroactive decision-time evidence.

Projection defects are data: balance mismatch, missing transaction order, partial decode, unknown
basis, quote absence, or conflicting episode link. The rail shows them rather than constructing a
synthetic lot or clean story.

## Market census and promoted hot lanes

### Census responsibilities

The eventual census records compact denominator evidence:

- launches, lifecycle changes, migrations, and venue relationships;
- the one or more discovery surfaces Joshi actually renders, with exact query/order snapshots;
- compact exact chain facts at the scope Spike 0 proves feasible;
- metadata revisions and source health;
- coarse market/flow rollups whose input coverage and version are explicit.

The census does not maintain continuous size-specific quotes, every full transaction response,
complete social threads/media, screenshots, or verbose identity resolution for every coin. It can
route a candidate into a hot scope, but no later study may pretend census resolution was hot-lane
resolution.

### Hot-lane responsibilities

A promoted exact-mint lane requests the state necessary for the selected workbench:

- ordered trade/account events and reserve/fee/migration state;
- genuine chart inputs across venue transition;
- current configured-size and full-inventory quotes as needed;
- wallet effects and balance checks;
- the social/thread/identity fields actually displayed;
- higher-frequency coverage health;
- scene/render/operator capture.

Activation records what was already in the census, which subscriptions succeeded, and the
high-resolution gap between operator attention and activation. Close records a reason and final
watermarks. A scope can degrade one feed without closing the others. While flat, it may step down
quote cadence or full-transaction retention but remains semantically open until the operator or a
declared resource rule changes it.

### Scheduling and pressure

Give write and computation lanes explicit priority:

1. operator gestures and scenes;
2. wallet/portfolio effects and source-health defects;
3. hot trade/reserve/quote state;
4. rendered discovery-surface evidence;
5. coarse census and backfill;
6. enrichment, media, embeddings, and retrospective analytics.

Priority does not license silent loss. It decides which acquisition is paused or sampled and which
coverage gap opens under pressure. Source-specific queue and lag metrics allow later capacity
decisions.

## Replay architecture

Three replay products share evidence but have different contracts.

### Witnessed replay

Input: a scene manifest. Restore the exact stored rendered DTO, list/viewport state, chart domain,
quote/portfolio snapshots, evidence-class/freshness labels, feature flags, utterance, and known gaps.
This is the first replay to implement. It answers what the application rendered, not everything the
backend possessed and not what Ember necessarily perceived.

### Knowledge-cutoff replay

Input: cutoff, named parser/resolver/projection/model versions, and a subject/choice context. Select
only observations whose `available_at` is at or before cutoff and bitemporal assertions known at
that cutoff. Recompute a named view. It may differ from witnessed replay because the deployed UI
did not render all available evidence.

### Retrospective replay

Input: later evidence horizon and current or named historical versions. Include finality,
backfills, corrections, identity changes, and outcomes. Retrospective output is visually and
semantically marked as later knowledge.

### Replay execution model

Reducers are pure over an ordered input manifest plus configuration. Any effect sink—collector
commands, alerts, model calls, notifications, or future economic proposals—is replaced with a
record-only stub during replay. A historical `arm` can reconstruct an observational hot scope but
cannot reopen a live subscription or future authority.

Rebuild tests compare canonical projection state, not database page bytes or timestamps generated
during the rebuild. Non-deterministic model outputs are stored derivations and replayed as exact
historical outputs unless an explicit recomputation is requested.

## Clock, ordering, and availability semantics

No process-global `timestamp` is adequate. Contracts preserve only clocks they actually possess:

- source event time with authority, precision, and possible interval;
- Solana slot, transaction index, instruction/event path, write version, block time, and finality;
- request start, first/last receipt, and durable persistence time;
- parser/projection completion and product availability time;
- client render, viewport, pointer/gesture, and server receipt time;
- enrichment/derivation production time;
- external transaction observation and reconciliation time.

Local wall time is paired with monotonic durations and clock-health samples. Cross-process latency
is a bounded estimate unless clocks are measured; process sequence and core receipt order remain
available. The core allocates durable local sequence numbers for append order but never relabels
that order as source causality.

Chain order is authoritative only within what the source established. Missing transaction index or
a reorg remains ambiguity. Board membership transitions between polls are interval-censored. A post
created before a gesture but fetched after it is unavailable to that gesture.

Every query snapshot states an `as_of` vector, not one time:

```text
chain finalized slot / live commitment slot
board request ID and receive time
social cursor and receive time
wallet balance slot/finality
quote state slot and expiry
projection checkpoint
```

The UI may summarize the vector as freshness labels, but the scene stores it exactly.

## Failure, degradation, and crash recovery

### Failure semantics by boundary

| Failure | Containment and visible result |
| --- | --- |
| One runner crashes | supervisor restarts it; exact scope opens a coverage gap; UI retains last value as stale |
| Runner retries an acknowledged batch | observations repeat; deterministic assertion keys prevent duplicate facts |
| Core crashes before acknowledgement | runner resends; cursor cannot have advanced beyond durable observation |
| Blob commits but DB transaction fails | harmless orphan blob; never infer an observation from it |
| DB references a missing/corrupt blob | affected assertion/replay becomes corrupt/unavailable; no silent cache fallback |
| Parser drifts | raw capture continues; assertions quarantine; dependent projections taint |
| One projection fails | its view freezes stale/degraded; evidence writer and gestures continue |
| LLM/analytics fails | annotation absent/degraded; no impact on hot chart, wallet, or gesture path |
| UI disconnects | collection and wallet observation continue; no viewport/gesture claims during gap |
| Core/disk unavailable | UI becomes explicitly read-only/stale; no local gesture receipt is invented |
| Hot queue overloads | pause lower priorities and open scoped gaps; never drop active regimes invisibly |
| RPC sources disagree/reorg | preserve both observations/finality transitions; live and retrospective views may differ |
| External manual trade happens during outage | recover chain effect later; intent and decision scene remain unknown unless separately captured |

### Recovery sequence

On core startup:

1. acquire the single-writer lock;
2. verify database integrity enough to trust cursors and projection checkpoints;
3. verify referenced critical blobs or mark exact corrupt scope;
4. reopen incomplete source requests/coverage windows as process-down gaps;
5. resume collectors from last durably acknowledged cursor with overlap;
6. replay assertion/projection inputs after their checkpoints;
7. reconstruct active hot scopes from append records and reissue idempotent subscriptions;
8. reconcile current portfolio balances before calling exposure current;
9. only then advertise current/degraded query readiness.

There is no “best effort green” state that skips malformed evidence or resets a cursor. If the
operator command path is available but a source is not, commands can still append with the source
gap inside their scene.

### Database backup and repair

Use consistent local snapshots and test restore on a disposable path. Evidence, blobs, and schema
registry versions must share a backup manifest. Projections may be omitted when rebuild cost is
acceptable. Repair never edits raw rows in place; it appends recovery/correction metadata or
restores from a verified backup. Private-artifact retention and hard erasure must also propagate to
backup policy.

## Schema and version boundaries

Version the seams that may change independently:

1. collector-to-ingest `ObservationDraft` envelope;
2. source contract/IDL/bundle/probe version;
3. raw observation envelope and blob format;
4. parser and typed assertion schema;
5. identity relation vocabulary and resolver version;
6. operator record semantic core and personal-label vocabulary;
7. scene manifest and rendered view DTO;
8. portfolio classifier and financial-ledger projection;
9. episode/accounting projection;
10. query/view API contract;
11. UI build and feature flags;
12. replay manifest and reducer versions.

A unit, orientation, namespace, null meaning, or time meaning never changes under the same version.
Readers support an explicit compatibility window. Unknown future variants remain retained and
unparsed. Database migrations are forward operations with a pre-migration backup and a full replay
or fixture diff; changing a projection normally creates a new projection version rather than
rewriting history.

Wire amounts use decimal strings plus explicit native units. IDs include namespaces. Contracts use
closed evidence/missingness states but allow opaque raw payloads. Code generation from a small
language-neutral schema may become useful once Python/TypeScript drift appears; it is not necessary
to introduce a large schema platform for Spike 0.

## Topology alternatives

### Alternative A — one-process modular monolith

```text
browser -> one core process -> local DB/blobs -> external sources
```

Strengths:

- fastest debugging and iteration;
- easy transactions for evidence/cursor and gesture/scene commits;
- few deployment, IPC, clock, and supervision failure modes;
- natural fit for local-only Slice 1.

Weaknesses:

- one bad source dependency or reconnect loop can harm the cockpit;
- mixed Python/Node/browser adapters become awkward;
- CPU-heavy replay/model work can starve hot paths;
- aggregate source credentials live in one process.

Verdict: the correct **source-code architecture** and acceptable Spike 0 implementation. Keep
module ports real. Isolate only demonstrated risky adapters before ordinary cockpit sessions.

### Alternative B — local multi-process system

```text
browser -> core/writer/query
              ^       |
       local IPC       +-> DB/blobs
       collectors / optional batch worker
```

Strengths:

- collector failure and SDK/runtime dependencies are contained;
- the core remains the sole semantic writer and source of query snapshots;
- credentials can be scoped per runner;
- slow batch replay can be separately scheduled;
- local IPC avoids remote-service authentication and deployment.

Weaknesses:

- supervision, bounded queues, protocol versions, and cross-process clocks become real work;
- subprocess sprawl can imitate microservices without their operational tooling;
- debugging is harder if every tiny module becomes a process.

Verdict: the recommended **initial deployment shape**, but only two or three process roles: core,
browser, and source runners as earned. A separate batch worker is optional after measured replay
contention.

### Alternative C — network services by domain or lane

```text
ingest services -> broker -> evidence service -> identity/accounting/episode services
                                      -> API gateway -> web app
```

Strengths:

- independent horizontal scale and deploys;
- explicit remote capability boundaries;
- natural fit if several machines, operators, or very high sustained volume become requirements.

Weaknesses:

- distributed ordering, partial commits, authentication, schema rollout, observability, backups,
  and replay coordination dominate the first product;
- a gesture and scene no longer share an easy transaction;
- every service can create its own competing clock and truth;
- local privacy and offline operation become harder;
- encourages an independent service for every exciting research noun.

Verdict: reject for Spike 0 and the first slices. Adopt a service only when a measured resource,
machine, trust, or availability boundary cannot be satisfied locally. Preserve the data contracts
so this remains possible without pretending it is already needed.

## Language and runtime choices

Languages affect process topology because a runtime boundary can become a fault and authority
boundary.

### TypeScript browser

The browser needs precise interaction capture, list stability, chart integration, and versioned
view contracts. TypeScript is the natural default and can selectively compost the old React/chart
behavior without importing old domain semantics. The browser stores no canonical state and no
secrets.

Whether the first shell is React/Vite is a reversible choice after Spike 0. Reusing a small known
shell is more valuable than evaluating every frontend framework. A desktop wrapper is unnecessary
while loopback browser APIs satisfy app-scoped capture and origin controls.

### Python core

Python is the leading first-core hypothesis because the existing read-only protocol/accounting
donors, exact reconstruction fixtures, research tooling, and future statistical workflows are
already nearby. It supports a fast local API and deterministic pure reducers if discipline is
enforced.

Risks:

- uncontrolled dynamic dictionaries can recreate the universal-event problem;
- CPU-heavy parsing or replay can block hot async work;
- source tasks can leak authority through imports and global clients;
- wire integer/string and enum semantics can drift from TypeScript.

Mitigations are typed boundary validation, one writer, pure projection modules, process isolation
for CPU/SDK outliers, and shared conformance fixtures. Do not solve these risks by beginning in a
distributed language-neutral framework.

### Node/TypeScript source runners

Use a Node runner when an official Pump/PumpSwap/Meteora/Solana SDK, browser integration, or exact
quote implementation is materially more faithful there. The runner accepts a narrow manifest and
returns raw acquisition/quote artifacts. It does not become a second backend and does not write the
database.

Official SDK output is still untrusted source output. Version, configuration, bytes/state inputs,
and clocks travel with the observation.

### Rust

Rust is appropriate later if measured whole-market decoding, exact state-machine replay, memory
pressure, or a future high-assurance isolated signer requires it. Introducing Rust now would add
FFI/IPC/schema and build complexity before the source and product loop are known. A slow Python
projection should first be profiled and given a representative replay benchmark; rewrite only the
bounded hot path.

### SQL and analytical runtimes

SQL is a useful durable query/projection boundary, not a domain language for every interpretation.
Python notebooks or an embedded analytical engine should consume watermark-bounded snapshots.
They do not connect to live UI command paths and never write raw evidence.

## Data and control flows

### Census acquisition

```text
scheduled/subscribed source
 -> request record
 -> raw response/frame + clocks
 -> blob/evidence commit + cursor ack
 -> parser assertion
 -> board/lifecycle/census projection
 -> immutable query snapshot
 -> rendered list epoch
 -> viewport acknowledgement
```

An unavailable source ends in coverage evidence, not an empty list.

### Promote to hot observation

```text
rendered exact mint -> operator open/watch/arm-shadow
 -> gesture + semantic scene commit
 -> HotScopeDeclared
 -> adapters subscribe/fetch required feeds
 -> each feed activates or degrades independently
 -> hot projections update chart/quote/social/workbench
```

The pre-promotion census and activation gap remain visible.

### External manual trade

```text
optional pre-action gesture -> scene receipt -> exact-mint link to Pump/Padre
 -> external wallet action (outside Joshi)
 -> chain observation -> reconciled asset effect
 -> inventory epoch/lot projection
 -> optional fill-to-episode attribution
```

If the gesture is absent, the fill is real and intent is unknown. If the chain is observed late, its
event time and Joshi availability time remain different.

### Scene and replay

```text
UI render snapshot + watermark vector
 -> consequential gesture
 -> atomic operator record + scene manifest
 -> optional screenshot attachment
 -> witnessed replay from stored view DTO
 -> separate cutoff/retrospective recomputation
```

### Assertion correction

```text
old raw bytes -> parser v1 assertion
same raw bytes -> parser v2 assertion superseding v1
 -> projection v2 rebuild/diff
 -> old witnessed scene remains unchanged
```

## Degradation contract in the product

Each view field or group carries:

- evidence class: observed, reconciled, derived, operator-attested, machine-interpreted;
- state: current, stale, gap, unknown, conflict, unquotable, corrupt;
- source/scope and last known good watermark;
- whether the value is safe for witnessed display, cutoff computation, retrospective use, or none.

Dependencies are declared per view/action. A social outage need not hide finalized wallet quantity.
A reserve gap taints reconstructed chart/quote state until an authoritative snapshot reanchors it.
A stale full-bag quote makes executable value unavailable while exact token quantity remains known.
A projection may serve its last value only as explicitly stale.

The core publishes a readiness vector rather than `healthy: true`:

```text
evidence writer current
wallet finalized through slot S
hot chain stream current/degraded
chart anchored/tainted
quote current/unquotable
social current/gapped
scene command path current
projection lag
```

## Path to later scale

Scale the bottleneck, not the nouns.

1. **Initial:** one machine, one core writer, local DB/blobs, a few collectors, direct local query.
2. **Measured CPU contention:** move replay/analytics to a local batch worker reading immutable
   snapshot manifests.
3. **Measured collector instability or runtime mismatch:** isolate that adapter behind existing
   local ingest contract.
4. **Measured database write/query contention:** separate append ingestion from analytical copies;
   preserve one logical cursor/evidence commit and avoid dual-write truth.
5. **Measured raw volume:** tier blobs and compact census representations under explicit retention;
   promote hot, sampled, drifted, and reconciliation evidence before expiry.
6. **Need for another machine or operator:** only then evaluate a networked evidence service,
   authentication, replicated database, and remote blob store.

Migration uses an append/export watermark and replay verification. Do not dual-write to two
canonical stores and hope they agree. A new store earns authority after backfill, live shadow
comparison, crash tests, and canonical projection digest agreement.

The contracts most likely to survive scaling are observation envelope, blob hash, assertion
evidence, scene manifest, projection manifest, and query snapshot. Internal class layouts and table
indexes should remain replaceable.

## Minimum architecture for Spike 0

Spike 0 is a premise test, not the first permanent daemon. Its minimum architecture is:

```text
manual/app-scoped session trace
          +
one selected-surface probe adapter
          +
one chain/chart/quote probe path
          v
small local observation store + blobs
          |
comparison/replay CLI or notebook
          |
field/latency/access report + sample scene
```

Required modules:

1. **Contract kernel:** observation/blob/coverage clocks, exact IDs/amounts, and secret redaction.
2. **One durable recorder:** transactionally couples observations and cursor/coverage.
3. **Probe adapters:** only the selected Pump loop, public chain path, genuine chart input, query-
   only quote, and one wallet history path.
4. **Offline adversarial fixture runner:** duplicates, equal repeated events, conflict, gap, skew,
   parser drift, external exit, flat watch, re-entry, partial reduction, runner assertion, and crash
   boundaries.
5. **Scene prototype:** store one structured reference/Joshi comparison scene and optional app-only
   image under a private retention class.
6. **Report/export path:** field classification, exact candidate/order comparison, latency,
   coverage, raw size, and replay result.

Not required:

- a polished UI, market-wide daemon, finalized schema, background hot-scope manager, social graph,
  general portfolio service, model worker, transaction builder, or signer;
- choosing a permanent database solely because the probe used it.

Spike 0 should nevertheless use the real envelope and crash rules so passing source code is not
thrown away. Its result selects replacement, companion, observatory, or stop/rethink mode. That
choice changes Slice 1/2 adapters and product claims, not the evidence architecture.

### Spike 0 architectural pass conditions

- Crash between evidence and cursor cannot create a skipped event; duplicate recovery is safe.
- A parser cannot delete raw bytes it rejects.
- Candidate membership/order comparisons retain mismatches and source health.
- The chart path names its exact underlying events/state and gaps.
- Query artifacts name size, route, state/slot, fee assumptions, and receipt/expiry.
- No secret canary or credentialed URL enters raw evidence, reports, or logs.
- One sample scene distinguishes source available, server served, browser rendered, and viewport.
- Replay of the adversarial fixture produces a stable digest and preserves flat watch/re-entry.
- The source-volume report is sufficient to accept or reject the proposed Slice 1 store/runtime.

## Minimum architecture for Slice 1

Slice 1 is an exposure-truth and prospective-episode notebook, not yet the whole market surface.
The minimum deployed graph is:

```text
                              local browser
                        workbench + episode rail
                                  |
                           loopback core API
                                  |
          +-----------------------+-----------------------+
          |                       |                       |
  wallet/chain observer     exact-mint hot observer   gesture/scene writer
          |                       |                       |
          +------------- one evidence writer -------------+
                                  |
                           local DB + blobs
                                  |
       wallet ledger | episode/accounting | replay projections
```

Implement only these product/data capabilities:

- one declared read-only wallet/portfolio-domain version;
- finalized wallet history and current-balance reconciliation;
- RADON, EarthCoin, and CRASHIUS as accounting/exposure fixtures, with honest unknown basis;
- one exact-mint workbench for the next natural episode;
- genuine event-backed chart with coverage/taint;
- current full-inventory executable liquidation observation or honest unquotability;
- append-only acts and optional text: mark, watch, shadow arm, partial intent, keep remainder,
  exit intent, watch flat, re-entry intent, resolution, correction;
- one semantic scene per consequential act and optional private perceptual artifact;
- external wallet-effect detection and optional episode attribution;
- exact ledger, lots/basis quality, inventory epochs, episode/flat-watch, rail, and witnessed plus
  retrospective projections;
- source/projector/readiness vector in the UI.

It does **not** require market-wide census. The selected-surface snapshots captured in Spike 0 may
remain a probe until Slice 2. The reference census/hot boundary should exist as contracts, but
building an idle whole-market collector before the exact-mint loop is useful would be platform-
first scope.

### Slice 1 process minimum

- one core process with single writer, command/query API, wallet reconciler, projections, and
  replay;
- one browser application;
- in-process collectors by default, with one Node runner only if the proven quote/chart/source SDK
  needs it;
- no always-running analytics worker unless replay measurements show UI interference;
- one local database and blob root with backup/restore script and private retention classes.

### Slice 1 architectural pass conditions

- Operator gesture receipt remains fast under source bursts and is durable before success is shown.
- Repeated client command IDs cannot duplicate gestures or hot-scope requests.
- Current wallet quantity closes to finalized chain state or shows a quantified defect.
- An external manual action creates actual asset effects without fabricated intent.
- Exact portfolio-flat begins a new basis epoch while the operator episode can remain watching flat.
- A later re-entry links to that episode but cannot inherit prior-epoch basis/trailing state.
- Witnessed replay reconstructs the stored rendered scene; later identity/parser/backfill changes do
  not enter it.
- Knowledge-cutoff replay excludes evidence received after the act.
- Parser/source/projector failure produces scoped stale/gap/taint states while gesture and unaffected
  wallet paths continue.
- Cold restart replays active episode and hot-scope state without losing or inventing intervals.
- No running process or dependency exposes signing or broadcast capability.

## Testing and verification strategy

Begin with executable properties and state-machine tests, not extensive formalization of the
provisional operator vocabulary.

### Contract tests

- every adapter against recorded raw fixtures, including unknown variants and secret canaries;
- Python/TypeScript wire conformance for exact integer strings, namespaces, missingness, and clocks;
- view DTO and scene-manifest compatibility across UI/core builds;
- official/source SDK adapter version pin and output fixtures where used.

### State-machine/property tests

- observation/cursor crash points yield repeat-never-skip behavior;
- equal-valued distinct chain events survive; repeat observations do not duplicate canonical facts;
- assertion supersession never mutates raw evidence;
- projection rebuild from genesis equals incremental state;
- bitemporal query cannot expose assertion before `known_from`;
- internal transfers conserve portfolio quantity and basis provenance;
- full-flat epoch cash flow closes exactly and re-entry resets basis;
- partial sell, runner assertion, full exit, flat watch, and re-entry remain orthogonal;
- idempotent gesture retries return one record and one scene;
- replay cannot activate effect sinks.

### Fault injection

- kill collector before/after send and before/after acknowledgement;
- kill core before/after blob rename, observation commit, cursor commit, scene commit, and projection
  checkpoint;
- fill disk or corrupt one blob/projection checkpoint in a disposable test store;
- disconnect each source independently; serve HTTP success with stale/null/malformed content;
- inject clock steps, source skew, same-slot ambiguity, source disagreement, and chain finality
  revision;
- overload census while gestures and hot events continue.

### Product verification

- target a row while new ranking epochs arrive; the recorded mint must remain the rendered target;
- replay a scene after parser and identity upgrades; witnessed view remains unchanged;
- record an external exit without gesture; UI must show financial fact and unknown intent;
- keep an episode hot through exact flat and later re-entry;
- measure time and interaction overhead of scene/gesture capture during ordinary use.

## Rejected alternatives and scope traps

1. **Microservice per lane.** Research lanes are questions, not deployment domains. It would freeze
   premature nouns, multiply clocks, and make one scene transaction distributed.
2. **One enormous process with every SDK and model.** Keep the modular core, but isolate a source
   when its runtime, credential, or crash behavior threatens the operator loop.
3. **Universal event JSON table.** Use a small common header plus typed object families. Flexible
   payloads do not excuse absent units, identities, or transition invariants.
4. **Mutable latest-state database.** It cannot support knowledge cutoffs, source disagreement,
   identity revision, or witnessed replay.
5. **Browser directly queries vendors.** It leaks credentials, loses durable receipt clocks and raw
   responses, fragments coverage, and makes scenes impossible to anchor transactionally.
6. **Kafka/ClickHouse/lakehouse first.** These solve possible future volume before the project knows
   its first surface, retention, or event shape. A local transaction and crash model is more urgent.
7. **Graph database for social/ecology.** Bitemporal typed relational assertions and bounded queries
   suffice for the first attended subjects; a generic graph invites generic `related` edges.
8. **Continuous full-market high-resolution capture.** Compact census plus declared promotion is the
   economic and epistemic boundary. Full fidelity everywhere delays the cockpit and may still omit
   what Ember saw.
9. **Screenshot/video as replay.** It lacks exact choice sets, quotes, watermarks, and source health.
   Use structured scenes plus occasional app-only images.
10. **Structured scenes without perceptual artifacts.** Early schemas will omit visual variables.
    A small private screenshot/checksum around consequential acts supplies a falsifier.
11. **Event-sourcing every cache and UI transition as eternal domain truth.** Persist evidence and
    meaningful render/gesture records; sample ordinary visual churn and keep projections disposable.
12. **Import `joshibot` as a runtime library.** Adapt donors behind new conformance tests. Old types
    and policy assumptions must not become transitive architecture.
13. **Python-only browser or TypeScript-only research stack.** Choose runtimes by role and contain
    their wire boundary; do not contort the product or analysis to eliminate one small local IPC.
14. **Rust-first rewrite.** Reserve it for measured hot paths or later monetary authority where its
    cost buys a demonstrated property.
15. **Signer-shaped abstractions in current code.** Preserve a future seam in documents and tests;
    do not let unused transaction types or clients enter an observational process.
16. **Whole-market census in Slice 1.** Exposure truth and one exact-mint episode can earn value
    first. Build the first real census only with the discovery surface selected for Slice 2.

## Decisions deferred to Spike 0 and the first operator loop

- replacement, companion, observatory, or stop/rethink operating mode;
- exact selected discovery surface and lawful capture path;
- final local database choice after measured write/replay load;
- whether any collector needs a separate process in Slice 1;
- exact chart source, quote adapter, and lifecycle support;
- scene screenshot cadence and private retention duration;
- hot-lane default TTL and fidelity step-down while flat;
- first portfolio domain beyond one named wallet;
- browser shell/chart library and whether a desktop wrapper ever becomes useful;
- thresholds that justify Rust, an analytical copy, or a network service;
- all transaction construction, signing, submission, and live-capital topology.

## Recommendation

Approve this as a reference shape only after Spike 0 confirms that one honest loop is observable.
For engineering planning, define module ports and crash invariants now, then implement the smallest
single-writer local corridor that closes one wallet, one exact-mint workbench, one gesture/scene,
one external action, one flat-watch/re-entry path, and one witnessed replay.

If that corridor is natural and trustworthy, the census and hot-lane contracts provide a direct
path to Slice 2 and Slice 3. If it is not, the architecture has spent little on irreversible
platform machinery and can shrink to an exposure manager, companion, or stopped experiment without
discarding its evidence and accounting work.
