# Lane 09 — infrastructure, reliability, and security boundaries

Status: pre-engineering research. This lane proposes boundaries and acceptance gates; it
does not authorize implementation, key access, signing, submission, or any transaction.

## Question and posture

The apparatus has two things to protect at first: Ember's money **and the validity of the
evidence from which the project learns**. A system that cannot lose funds but silently
rewrites event time, drops a feed, backfills future metadata into the past, or omits flat
watching intervals can still destroy the project. Conversely, a wonderful evidence system
does not earn permission to transact.

The initial architecture should therefore make read-only collection and replay useful on
their own, while leaving a narrow and reviewable seam where execution could be added much
later. “Dry run” must initially mean that signing and broadcast capabilities do not exist in
the process graph, not merely that a Boolean happens to be false.

This lane treats every external payload, SDK, web page, social post, model output, clock,
RPC, and derived projection as fallible. It treats the local operator as authorized but
capable of misclicks, duplicated gestures, stale interpretations, and reasonable decisions
made from degraded data. It does not assume that the strategy has positive expected value.

## Facts observed in `joshibot` compost

These are code observations, not endorsements of the old architecture as a whole.

### Strong primitives worth re-deriving

- `shitcoims_lpexec/rpc.py` uses a method allowlist that omits `sendTransaction`. The LP
  package can read and simulate but has no broadcast operation. This is much stronger than
  a dry-run flag.
- `shitcoims_lpexec/guard.py` treats SDK-produced transactions as hostile bytes. It decodes
  the complete v0 message, resolves address lookup tables, requires unsigned input, checks
  signer count and fee payer, walks every top-level instruction, checks DLMM discriminators,
  binds pool and position accounts to an expected plan, derives the destination wrapped-SOL
  account itself, and caps wrapping and priority fees.
- `shitcoims_lpexec/allowlist.py` makes absence the default. Unknown future instructions and
  all known swap instructions are rejected. The refusal of `rebalance_liquidity` is
  especially instructive: a legitimate operation was withheld because the guard could not
  establish its semantic effect from the instruction alone.
- `shitcoims_lpexec/signer.py` accepts only the result of the guard, orders signers according
  to the message, and verifies the resulting signatures locally. The builder never receives
  a key.
- `shitcoims_sentinel/transaction.py` supplements instruction validation with a simulation
  postcondition: the intended target balance changes by the intended amount, other owned
  tokens do not change, and minimum SOL output returns to the wallet.
- `shitcoims_sentinel/executor.py` derives a transaction signature before submission,
  durably records it, and refuses to build a replacement while the old signature could
  still land. Unknown is an explicit terminal-pending condition requiring reconciliation,
  not permission to retry.
- `shitcoims_sentinel/storage.py` uses a process lock, file lock, temporary file, `fsync`,
  and atomic rename for mutable state.
- `shitcoims_lpexec/ledger.py` separates intended, simulated, and actual outcomes. It also
  records ingest time separately from source event time and requires divergences to remain
  visible until classified.
- `shitcoims_tape/schema.py` preserves raw integer amounts without JSON floating-point loss,
  distinguishes chain and observation clocks, records censoring, and stores reserves rather
  than only prices.

These should become behavioral specifications and adversarial fixtures. They should not be
copied wholesale before the new operation model is understood.

### Gaps and traps not to inherit

- Sentinel keys live in the same long-running process that owns policy, network clients,
  state, and notification behavior. That is too much authority in one fault domain.
- The old arm file is wallet-scoped and persistent. It is not bound to a particular action,
  mint, amount, policy version, nonce, or expiry. Multiple independent gates help against
  accidents, but do not provide narrowly delegated authority.
- Some guard restrictions are conditional on optional arguments. For example, an empty
  expected-pool set widens the LP guard from the plan's pool to every globally allowlisted
  pool. A later signer API should make the narrow capability structurally required.
- Safety is divided among planner, guard, and simulation. An empty but allowlisted pool can
  be rejected by planning while remaining acceptable to the byte guard. A compromised
  planner is exactly why the signer needs independent effect and cap checks.
- A program/discriminator allowlist is necessary but not sufficient. Upgradeable programs,
  CPI behavior, account role changes, token extensions, and changed vendor transaction
  shapes can invalidate old assumptions while leaving a familiar program ID visible.
- Simulation is valuable but is neither consensus finality nor a promise about the state at
  landing. It can be stale, provider-specific, based on a replaced blockhash, or invalidated
  by intervening trades.
- The LP JSONL ledger flushes each row but does not `fsync` it. Its reader silently skips
  malformed rows. Using such a reader for a daily spend cap can undercount after corruption
  or a torn write. A monetary reservation journal must fail closed on an unreadable record.
- Counting only `submit` rows as spent leaves a crash boundary around signed/released or
  ambiguously submitted transactions. Limits must reserve capacity before a signed
  capability leaves the signer and release it only through reconciliation.
- Per-mint pending state prevents one class of duplicate exit, but does not by itself make
  cross-mint portfolio caps or multiple processes serializable.
- UI bundle regex tests that assert the absence of `/execute` calls are useful tripwires,
  not authority boundaries. The UI must be untrusted even if its current source appears
  read-only.
- Error redaction correctly recognizes API keys embedded in URLs, but redaction should be a
  structured logging rule applied before serialization, not a convention each exception
  path must remember.

## Assets, trust assumptions, and threat model

### Assets

1. Private keys, RPC credentials, provider cookies, and later any signing capability.
2. Wallet balances, token lots, LP positions, and authority over them.
3. Raw evidence, source payloads, event order, clock provenance, attention traces, gestures,
   scene manifests, and annotations.
4. The integrity and reproducibility of derived projections, studies, model outputs, and
   accounting.
5. Ember's private explanations, dispositions, watchlists, and portfolio state.
6. Availability during a fast decision without pretending that stale or missing data is
   current.

### Plausible threats and ordinary failures

- A compromised or buggy SDK returns a validly encoded transaction with additional
  instructions, accounts, signers, destinations, or costs.
- A vendor changes an endpoint, schema, fee model, ranking, program, instruction layout, or
  pagination rule without notice.
- An RPC equivocates, lags, omits transactions, reports a stale blockhash, or times out after
  accepting a submission.
- WebSocket reconnects create duplicates or gaps; an HTTP poll silently falls behind;
  cursor persistence and event persistence tear across a crash.
- Hostile coin names, social posts, links, images, metadata, or model prompts attempt XSS,
  prompt injection, address substitution, resource exhaustion, or accidental navigation.
- A displayed mint, pool, or wallet resembles the intended address. Current metadata is
  mistaken for historical metadata.
- A model hallucinates an identity, transition, quote, fee, or disposition, or treats
  untrusted social text as an instruction.
- The UI double-submits a gesture, reconnects and retries, renders a projection from mixed
  high-water marks, or omits a degraded-source warning.
- Two policy workers race against the same balance or daily budget. A process restarts and
  forgets an in-flight order. A disk fills between state transitions.
- Wall time jumps, source clocks are skewed, block time is null, event time is revised, or
  ingest time is accidentally used as causal time.
- A schema migration changes meaning while retaining the field name. A backfill overwrites
  what was known contemporaneously.
- A local process, browser dependency, notebook, or analytics job reads a secret it never
  needed. Logs or crash reports exfiltrate a URL containing a credential.
- The operator arms the wrong coin, acts on stale glass, mistakes “stop submission” for
  cancellation, or intentionally changes disposition while an earlier order is unresolved.

### Assumptions and non-assumptions

- Public market and social sources are untrusted evidence sources, not authorities over the
  local machine.
- The local machine and OS account are initially trusted. If an attacker has root access
  while a software key is usable, process separation alone cannot protect that key.
- TLS helps transport integrity but does not make one provider's answer canonical.
- Solana consensus and program behavior are external facts to observe; no local projection
  is a source of wallet truth.
- Models are untrusted analysts. They receive data and may emit annotations, but never gain
  tools, keys, order authority, or the ability to change a risk envelope.
- Positive PnL is never a security invariant. Accurate accounting, bounded authority, and
  honest unknown states are.

## Proposed trust boundaries

The following is a candidate decomposition to test, not a commitment to languages or
deployment units.

```text
public sources / RPCs / social surfaces
                  |
                  v
          source-specific collectors  ---- heartbeats/gap reports
                  |
        append raw observations only
                  v
       immutable local evidence store <---- operator-event writer
                  |                              ^
                  |                              |
          replay / projections             local UI gestures
             |          |                       |
             v          v                       v
          analytics   query service       intent/capability service
             |          |                       |
       annotations      +--------> local UI     |       later phases only
                                                v
                                          policy / planner
                                                |
                                         unsigned plan + tx
                                                v
                                      executor / simulator
                                                |
                                  exact short-lived authorization
                                                v
                                   isolated signer + signing journal
                                                |
                                      signed expiring bytes
                                                v
                                      submitter / reconciler
                                                |
                                           chain truth
```

“Service” need not mean distributed infrastructure. Initially these can be local processes
or modules with separately testable capability surfaces. The important distinction is which
component can read or append which class of record, open which network destination, and ever
possess a key.

### Capability matrix

| Component | May read | May append or produce | Must not possess or do |
|---|---|---|---|
| Collector | Its source configuration and public responses | Raw source envelopes, cursor commits, heartbeats, explicit gaps | Wallet keys, operator annotations, policy state, arbitrary filesystem writes, transactions |
| Evidence store | Incoming validated envelopes | Append immutable records and segment manifests | Enrichment, source-time guessing, deletion in normal operation, network access |
| Projection/replay | Immutable evidence and versioned schemas | Disposable checkpoints and named projections | Mutate raw evidence, call execution APIs, claim currentness past its high-water mark |
| Analytics/model worker | Selected evidence/projections | Versioned annotations with inputs, code/model/prompt version, production time | Treat annotations as facts, call signer/executor, follow instructions embedded in source text |
| Query service | Projections and health state | Read responses with provenance/high-water marks | General SQL/filesystem access from the browser, keys, order creation |
| UI | Query responses and its own local interaction state | Operator events through a narrow append endpoint; later, explicit intent requests | Direct provider credentials, arbitrary evidence writes, signing, broadcast, raw HTML execution |
| Policy/planner | Immutable decision context, operator authorization, risk configuration | Proposals, deterministic plans, counterfactuals | Keys, submission, silent action on missing context |
| Executor/simulator (later) | Exact plan, public chain state, quote, durable order journal | Unsigned transaction candidate, simulation record, submission/reconciliation requests | Private keys, broad filesystem access, trusting its own bytes |
| Signer (later) | Exact expiring authorization, risk limits, chain state needed for independent validation | Refusal or signed bytes plus durable issuance record | Social/model feeds, UI sessions, arbitrary transactions, general outbound network access |
| Submitter/reconciler (later) | Signed expiring bytes, chain/RPC responses, signing journal | Broadcast attempts and chain-derived resolutions | Re-signing, changing bytes, inventing fills, clearing unknown orders |

A single process combining several rows is acceptable only while its aggregate authority is
still harmless. Collector and projection may coexist during an early experiment. Signer and
policy should not.

## Load-bearing invariants

These should become machine-checkable properties before implementation grows around them.

### Evidence invariants

1. Raw observations are append-only. Corrections and enrichments are new records referring
   to old records, never updates in place.
2. Every accepted record has a stable event identity, source identity, source cursor or
   explicit absence, source payload version, fetch/observation time, persistence time, and
   content hash. Chain records additionally preserve slot, signature, transaction index when
   available, commitment/finality, and nullable block time.
3. Raw integer quantities are stored exactly. Units, mint decimals, quote/base orientation,
   and fee inclusion are explicit rather than inferred from field names.
4. Source/event time, block time, observed time, ingest/persist time, and local monotonic
   latency are different fields. No transformation silently substitutes one for another.
5. Missing, stale, censored, parse-failed, and not-applicable are values with different
   meanings. None is silently converted to zero, false, or an empty list.
6. At-least-once collection plus deterministic deduplication is preferred over a false
   exactly-once claim. Replaying the same input twice produces the same projection.
7. A source cursor advances atomically with durable evidence. After any crash, recovery may
   duplicate input but must not skip input because the cursor outran the store.
8. Every rendered scene and operator gesture names the evidence/projection high-water marks
   it used. Later enrichment cannot rewrite what Ember was shown at decision time.
9. Every derived value names its transformation version and inputs. A projection can be
   deleted and rebuilt from genesis to the same canonical digest.
10. A collector's silence is never interpreted as absence of market activity without a
    positive heartbeat and source-specific completeness claim covering the interval.

### Authority and execution invariants for a later phase

1. During the present phase, no repository process reads a wallet key, signs, submits, or
   exposes a transaction endpoint.
2. Later, the only key-reading component is the signer. A builder, UI, policy, model,
   collector, and general application server are always keyless.
3. Every signature requires a one-shot or tightly bounded authorization containing wallet,
   action family, exact assets/venues, maximum input and cost, minimum output or exact
   postcondition, expiry, nonce, policy/limit version, and plan hash.
4. The signer decodes and validates the complete transaction independently. It does not
   trust the executor's summary, SDK, simulation classification, address labels, or account
   list.
5. Programs, discriminators, account roles, signers, writable accounts, destinations,
   token programs/extensions, mints, pools, fee payer, compute budget, tips, rent, and total
   SOL/token deltas are denied by default and checked against the exact authorization.
6. A simulation must be fresh enough, cover every wallet account relevant to the stated
   postcondition, and use the exact bytes to be signed. Simulation is necessary evidence,
   never sufficient authority.
7. The signer fsyncs an issuance row containing signature, transaction hash, authorization,
   blockhash, last valid height, and reserved limits before signed bytes leave its boundary.
8. One logical order produces one signed byte string. Submission retries rebroadcast those
   exact bytes; they do not rebuild or re-sign within the validity window.
9. Ambiguous submission is `unresolved`, not failed. No conflicting action for the affected
   inventory or reserved budget may proceed until reconciliation proves the transaction
   landed or can no longer land.
10. Provider success is not a fill. Only decoded chain effects at the required commitment
    establish actual lots, balances, fees, realized PnL, and inventory.
11. Caps are reserved durably before signature release and computed from the journal, not
    process memory. Restart, concurrency, unreadable journals, or clock rollover cannot
    reset them.
12. Stopping the system cannot cancel a transaction already broadcast. The glass must say
    whether it stopped proposals, revoked future signing, stopped rebroadcast, or merely
    lost data.

## Evidence store and replay architecture

### Raw envelope

A minimal raw envelope should carry these concepts even if physical storage begins as
segmented JSONL or SQLite:

- `record_id`: deterministic from source namespace and source-native identity when
  available; otherwise from a canonical content digest plus a collision discriminator;
- `source`, `source_instance`, endpoint/subscription, request or connection generation, and
  collector build/version;
- immutable raw payload bytes or a lossless canonical representation, content type, payload
  hash, and parse status;
- source-native cursor/sequence, Solana slot/signature/index/commitment where relevant;
- `t_source`, `t_block`, `t_observed_wall`, `t_observed_monotonic`, and `t_persisted`, each
  nullable only with an explicit reason;
- receipt context such as status code, response headers needed to interpret caching, and
  request parameters with secrets redacted before serialization;
- schema/envelope version and links to superseded/correction records;
- completeness metadata: snapshot versus delta, expected coverage, gap before/after, and
  whether the record came from live observation or later backfill.

Lossless does not require keeping authentication headers or tracking identifiers. Secrets
must be removed before a payload crosses into generic logging or storage.

### Write path and idempotence

The write unit should be a transaction containing observations, the cursor/high-water mark
they justify, and collector health. If the chosen first store cannot atomically commit all
three, use a write-ahead spool whose recovery rule is “repeat, never skip.” The store should
reject a conflicting duplicate—same identity, different payload—as a visible source
revision rather than arbitrarily choosing one.

Projection workers consume immutable offsets and commit their own checkpoint only after
their output is durable. Side effects are avoided during replay: model calls, notifications,
and later order proposals are represented as intents and run through explicitly disabled
effect sinks. Replaying a historical operator gesture must never recreate a live order.

Canonical ordering is a projection concern. Arrival order remains evidence. When two events
cannot be totally ordered, the projection preserves the tie/partial order instead of making
wall-clock precision up.

### Scene capture

A decision scene should be a small manifest, not a giant mutable database snapshot. It
references:

- all source and projection high-water marks;
- board membership, ranks, viewport bounds, opened panels, chart window/resolution, and
  candidate alternatives visible or available;
- quote and portfolio observations with their individual ages;
- source-health/degradation state as rendered;
- operator gesture, local monotonic time, and UI build;
- optional screenshots or rendered artifacts as supplementary evidence, never the only
  evidence.

This makes “what did Ember know?” replayable without claiming that every underlying source
was complete.

### Schema evolution

- Raw envelope schemas and domain schemas are versioned independently.
- A field's meaning, unit, orientation, or null semantics never changes in place. Add a new
  field/schema version and write an explicit adapter.
- Migrations create new projection namespaces or tables and preserve the old one until a
  replay equivalence/difference report has been reviewed.
- Backfills use their actual fetch time, the original event time when known, and an explicit
  `backfill` provenance. They never masquerade as contemporaneously available evidence.
- Entity-resolution changes append assertions with evidence and validity intervals. They do
  not rewrite old authors, creators, or identities.
- Every release that changes a projection must replay a fixed adversarial corpus and a
  representative historical segment from genesis. Expected changes are described, not
  waved through as a new digest.
- Unknown future event variants are retained raw and marked unparsed; they do not disappear
  merely because the current domain schema cannot represent them.

## Data degradation and clock discipline

Each source should publish a health record containing last successful receipt, last
source-native event, current cursor/slot, connection generation, reconnect and retry counts,
parse/drop/conflict counts, observed lag distribution, and known gap intervals. Health is
per feed and per coverage class; “RPC green” cannot imply “social complete.”

The UI should render one of at least four states for data on which an interpretation
depends:

- **current within stated tolerance**;
- **stale**, with age and last known value;
- **gap/degraded**, with the affected interval or coverage;
- **unknown/unavailable**, without carrying forward a value as if current.

No single green light represents system health. A chart may be current while candidate
ranking is unknown and social threads are eight minutes stale. A scene manifest preserves
that mixed state.

Wall time is needed for human interpretation; monotonic time is needed for local latency
and expiry measurement; chain slot/order is needed for on-chain causality. Local wall-clock
offset should be monitored against more than one time source, but upstream timestamps are
not rewritten to “correct” them. Record observed skew and choose the analysis clock
explicitly.

In a later execution phase, a stale or gapped quote/reserve/fee/portfolio source must
invalidate the corresponding authorization. Social degradation may prevent a social policy
from arming while still allowing a separately authorized manual exit. Degradation rules
belong to the action's declared dependencies, not one global Boolean.

## Local-first deployment and secret handling

The default system should function on Ember's machine with local durable storage, a loopback
UI, and no cloud control plane. Cloud compute may later receive deliberately selected,
redacted evidence for batch analysis; it should not silently receive wallet state,
annotations, watchlists, browser cookies, or keys.

Initial controls:

- bind application APIs to loopback or a permissioned Unix-domain socket;
- reject browser cross-origin requests and WebSocket origins rather than relying only on an
  unguessable port;
- render coin/social content as escaped text; proxy or isolate media; never inject source
  HTML; mark outbound links and addresses as untrusted;
- give model workers data-only prompts, no ambient tools, and a schema-constrained output
  channel; source text cannot add instructions or authority;
- store operator annotations and portfolio context with private-by-default file permissions;
- use encrypted local backups for irreplaceable evidence and test restore, while excluding
  caches that are cheaply replayable;
- collect no telemetry by default; make any external model/provider transfer visible and
  attributable in provenance;
- redact secrets structurally at client construction and log-field serialization. Never put
  API keys in a value that generic exception formatting can retain.

The current repository must contain no secrets. Example configuration contains paths or
placeholders only. Secret files are regular files with no group/world permission, but mode
checks are not a complete solution: later key custody should prefer a hardware or OS-backed
signing interface if it can express the required transaction review. If a software key is
temporarily unavoidable, bind it to the expected pubkey, keep it in the isolated signer,
avoid inheritance by child processes, redact crash dumps, and use a dedicated small wallet
whose role and maximum loss are explicit.

Different economic roles should use different keys and different signer allowlists. A
trading key should not be able to manage DLMM positions; an LP key should not be able to
swap; an evidence/API credential should authorize no wallet action. Key separation does not
require assuming the five-wallet proposal in the old design is correct—the minimum set
should follow the eventual operation model.

## Later transaction safety architecture

This section is intentionally conditional on a future explicit review.

### From gesture to authorization

A fast crackle UI cannot demand slow manual transaction review at every micro-action, but
the alternative is not an indefinitely armed wallet. Ember can explicitly create a narrow,
short-lived capability such as:

```text
wallet: trading-role-A
mint: exact address
venue/program family: Pump curve and/or exact canonical pool
allowed actions: buy, partial sell, full sell
entry budget: <= X lamports total
inventory budget: <= Y raw tokens / Z executable SOL value
minimum net-exit rule: named policy version
maximum impact/slippage/fees/priority/rent: exact caps
concurrency: one unresolved order for this mint; N globally
not_before / expires_at / nonce
scene_id, operator_gesture_id, policy_version, limit_version
```

Policy may decide *when* within that envelope to propose an action. It cannot widen the
envelope. Disposition changes—promoting a crackle remainder to a runner, re-entering after a
flat interval, or adding to a fancoin catalyst position—produce new operator events and, if
needed, new capabilities. Re-entry is not silently inherited from a previous arm.

### Independent validation

The executor constructs an unsigned candidate and records the quote, fee configuration,
reserves, accounts, blockhash, intended inventory delta, and postconditions. The signer
then re-fetches or receives independently authenticated chain state sufficient to check:

- transaction bytes hash to the authorized plan;
- exact expected signer set and fee payer;
- all static and lookup-table accounts are resolved;
- program IDs, upgrade/deployment facts, instruction discriminators, account roles,
  writable accounts, and token extensions match a reviewed specification;
- buy input, sell quantity, remaining balance, destinations, minimum output, aggregate SOL
  loss, fee/tip/CU/rent, and asset/pool identities fit the capability;
- the blockhash and all quote/reserve/fee observations are inside their TTL/slot-distance;
- no conflicting order, wallet lock, daily reservation, global kill state, or source-health
  prerequisite is open;
- simulation of the exact bytes proves explicit wallet postconditions and touches no
  unrelated owned assets.

The signer should refuse duplicate compute-budget setters, unknown instructions, unexpected
signers, unexpected writable accounts, and any new program variant until reviewed. “Known
program” is not enough.

### Order journal, submission, and reconciliation

Candidate lifecycle:

```text
proposed -> planned -> simulated -> operator-authorized -> signing
         -> signed/reserved -> submitting -> submitted
         -> processed -> confirmed -> finalized -> reconciled
                                  \-> expired/dead
                                  \-> unresolved (blocking/manual)
```

Not every order will visit every optimistic state, but transitions are append-only. An order
is never deleted to mean failure. Each transition has writer identity, wall and monotonic
time, source slot/commitment where applicable, and previous-record hash/order ID.

The signer owns a durable issuance spool. The submitter owns attempt records. The reconciler
observes all managed wallet addresses directly from chain and is the sole writer of actual
fills/lots/inventory effects. A provider's execute response is only evidence about an
attempt. Reconciliation uses signatures, inner instructions/events, pre/post token and SOL
balances, fees, account closures/rent, and finality. Disagreements among intent, simulation,
provider report, and chain are preserved and classified.

An unresolved order reserves its worst-case budget and locks conflicting inventory. A
replacement may be signed only after final chain evidence or blockhash expiry establishes
that the old bytes cannot land. Multi-transaction operations add much harder intermediate
state and partial-completion risks; the first live scope should avoid them unless each step
is independently safe and the operator has an explicit recovery plan.

### Limits and kill controls

Limits should include, as applicable:

- maximum input, output sold, transaction cost, priority/tip, rent, price impact, and
  authorized slippage;
- minimum liquid SOL reserve and maximum total executable exposure;
- per-mint, disposition-book, wallet, hour/day, and total-session budgets;
- maximum open and unresolved orders, action rate, turnover, and correlated-theme exposure;
- exact program/venue/mint/pool/destination allowlists;
- maximum observation age/slot distance and required source-health predicates;
- a session loss boundary based on reconciled executable outcomes plus worst-case reserved
  exposure, not marks alone.

At least four controls need separate names and visible state:

1. **Stop proposals** — policy emits nothing new.
2. **Revoke future signing** — signer rejects capabilities not already issued.
3. **Stop submission/rebroadcast** — signed bytes are no longer sent, though previously sent
   bytes may still land.
4. **Exit-only/panic disposition** — a separately reviewed policy that may reduce exposure;
   it is not implied by “kill.”

There should be a local physical or command-line disarm path independent of the UI. Loss of
UI, analytics, model, or social feeds must not prevent viewing wallet truth or revoking
future signing. A kill event and its scope are journaled, but the control remains effective
even if the main evidence store is unavailable.

## Observability and operations

The operator-facing health surface should make absence legible. Suggested metrics/events:

### Evidence plane

- last receipt and source-native event per feed, cursor/slot lag, reconnect generations;
- source-to-observe and observe-to-persist latency distributions, not only averages;
- duplicate, conflict, out-of-order, parse-failure, unknown-variant, and dropped-record
  counts;
- open gaps and censoring reasons by coverage class;
- spool depth, projection checkpoint/high-water mark, replay lag, query snapshot watermark;
- disk free space, write/fsync latency, corrupt-segment detection, last verified backup and
  restore drill;
- wall-clock offset/jump and monotonic discontinuity after reboot;
- model/annotation version, input scene, latency, cost, failure, and refusal counts.

### Later authority plane

- proposals, authorizations, refusals by invariant, simulations, signing issuances,
  reservations, submissions, rebroadcasts, finality lag, and unresolved orders;
- exact quote/reserve/fee age at signing and landing;
- intended versus simulated versus actual deltas and classified divergences;
- remaining per-order/session/day budgets including unresolved reservations;
- signer and submitter liveness, disarm state, wallet locks, and capability expiry;
- balance snapshots from at least one independent reconciliation path.

Logs are structured and redact before write. Error messages contain public identifiers and
stable error codes, not request URLs, headers, cookies, raw model prompts, or signed
transaction bytes. Raw signed bytes belong in the restricted order journal only if needed
for reconciliation. Alerts include the last known good time and whether the condition is
`bad` or merely `unknown`.

## Failure modes and expected response

| Failure | Unsafe or misleading response | Required response |
|---|---|---|
| Collector reconnect duplicates events | Count both or discard arbitrarily | Stable dedup; preserve receipt provenance and conflicts |
| Cursor committed before records | Continue after the gap | Atomic commit or repeat-from-spool recovery |
| Endpoint returns a new schema | Coerce missing fields to zero | Retain raw payload, mark unparsed variant, degrade dependent views |
| Feed goes quiet | Display “no activity” | Heartbeat expires; show unknown/gap with last known time |
| Board polling displaces older coins | Treat disappearance as death | Explicit coverage/censoring event and continuing hot-watch lane |
| Source clock is skewed | Rewrite timestamp silently | Preserve source time and observed skew; choose analysis clock explicitly |
| Projection migration changes result | Overwrite old database | New projection version plus replay diff and rollback path |
| Backfill learns current creator/identity | Insert it into past scenes | Append later knowledge with validity/observation interval |
| Hostile post addresses the model | Model changes policy or calls a tool | Treat post as quoted data; schema-only annotation, no authority |
| UI reconnect repeats an arm/annotation | Duplicate action | Idempotency key tied to gesture; exact duplicate returns existing record |
| Mixed projection watermarks | Render a coherent-looking impossible scene | Snapshot manifest declares all component watermarks and degradation |
| Disk full/torn journal | Skip malformed line and continue caps | Fail closed, retain spool, alert, require repair/reconciliation |
| SDK adds an instruction/account | Sign because program ID is familiar | Unknown-by-default signer refusal |
| RPC simulation passes but state moves | Assume landing effect | TTL/slot bound, on-chain limits, and post-landing reconciliation |
| Submit call times out | Build a replacement | Persist known signature; rebroadcast identical bytes or remain unresolved |
| Process crashes after signing | Forget transaction and budget | Recover signer issuance spool and reserved cap before new actions |
| Daily cap process restarts/races | Reset or oversubscribe cap | Transactional durable reservation journal with one writer/lock |
| Kill pressed after broadcast | Claim order cancelled | Stop future authority and report outstanding bytes until resolved |
| Social feed fails during manual exit | Prevent all safety actions | Dependency-specific gating; separately authorized manual/exit path |
| Reconciliation disagrees with provider | Prefer convenient answer | Chain-derived actual state; preserve and classify divergence |

## Phased gates

Progression is evidence-based and monotone: a phase may add capability only after its
acceptance criteria pass. A later phase does not weaken earlier evidence guarantees.

### R0 — design-only repository (current)

- No key loader, signer, broadcast RPC method, transaction endpoint, or secret in the tree.
- Threat model, evidence contract, clock semantics, and source dependency declarations are
  reviewed.
- CI/static inspection demonstrates absence of signing/broadcast capabilities; this is a
  tripwire in addition to code review, not the sole boundary.

### R1 — offline evidence and replay

- Fixture-only collectors write duplicates, conflicts, gaps, reordered events, clock skew,
  unknown schema variants, and interrupted writes.
- Rebuild from genesis is deterministic and effect-free.
- Schema migrations produce explicit diffs; corrupt state fails visibly.

### R2 — live public read-only collectors

- Egress is restricted to reviewed read endpoints; no wallet key exists on the process.
- Source health, cursor durability, raw capture, and gap recovery run prospectively.
- Provider secrets are redacted, permissioned, and absent from evidence/logs.

### R3 — local cockpit and operator-event capture

- UI is loopback/origin-protected and source content is inert.
- Every gesture is idempotent and every scene names its watermarks and degradation state.
- Replay reproduces what was shown without generating notifications or actions.

### R4 — shadow policy and executable observation

- Policies emit proposals/counterfactuals only. Quotes, fees, reserves, expected fills, and
  hypothetical timing are recorded with TTL and provenance.
- There is still no transaction builder, key, signer, or broadcast method.
- Prospective data can attribute operator selection, waiting, management, exit, flat-watch,
  and re-entry decisions without pretending they are independent positions.

### R5 — unsigned construction and adversarial simulation laboratory

- Requires a separate explicit review even though it remains non-broadcasting.
- Builder is keyless and its bytes face an independent hostile-input guard.
- RPC client structurally omits broadcast; fixtures exercise unknown instructions, lookup
  tables, token variants, altered account roles, address poisoning, stale state, and
  malicious SDK output.
- No real key is needed; deterministic throwaway fixture keys are not assets.

### R6 — isolated signing laboratory, no broadcast

- Requires a new explicit authorization and a reviewed signer protocol.
- Signer has narrow IPC permissions, durable issuance/reservation journal, exact capability
  binding, independent validation, disarm path, and no general network access.
- Use a disposable, tightly funded wallet only if a real-key exercise is justified. Signed
  bytes never reach a broadcast-capable client.

### R7 — manually initiated, tiny live slice

- Requires a dedicated live-risk review, named wallet/loss budget, restore/reconciliation
  drills, and explicit operator consent.
- One venue/action family, one-shot short-lived capabilities, one unresolved order at a
  time, exact-byte rebroadcast, and chain reconciliation.
- No unattended entry, no multi-transaction workflow, and no inference that a successful
  transaction proves a profitable strategy.

### R8 — bounded reactive automation

- Consider only after enough R7 orders establish landing, reconciliation, cap behavior,
  source freshness, and intervention ergonomics.
- Expand one dimension at a time: action family, venue, concurrent mints, duration, or
  capital—not all together.
- Any signer-spec/program/schema drift returns the affected action to refusal or shadow.

LP management should have separate R5–R8 gates from spot trading because its programs,
account effects, multi-step risks, and wallet role differ. A reviewed spot signer must not
accidentally authorize LP actions or vice versa.

## Smallest useful experiment for this lane

Build no trading code. Define and exercise one offline “crash-and-replay scene” fixture:

1. Generate two source streams for one synthetic coin: chain-like trades/reserves and a
   social/board stream. Include duplicate delivery, reordered events, a conflicting source
   revision, one unknown payload variant, clock skew, and a deliberate feed gap.
2. Append an operator sequence representing inspect, arm, exit, watch while flat, re-entry,
   partial realization, and promotion of a remainder to runner. Capture one scene manifest
   per gesture.
3. Interrupt the collector between evidence and cursor persistence and interrupt a
   projection between output and checkpoint persistence.
4. Restart, replay, and verify:
   - no source event is skipped;
   - duplicates do not change economic counts;
   - the conflict and unknown variant remain visible;
   - the gap renders as degraded, never “no activity”;
   - scenes reproduce the original watermarks and do not acquire later enrichment;
   - replaying twice yields the same canonical projection digest;
   - the episode contains two inventory intervals and a flat watching interval rather than
     three falsely independent positions;
   - no replay sink can notify, propose a live action, sign, or broadcast;
   - a torn/corrupt durable record stops the relevant projection rather than being skipped.

This is the smallest experiment because it tests the apparatus properties that all strategy
families need, without creating a premature universal schema or touching money. A second,
later offline experiment can run an adversarial corpus of unsigned Solana transactions
against a proposed signer spec; that is not required for the first vertical slice.

## Open questions

- Which local store gives atomic evidence+cursor commits, efficient append, immutable raw
  payload retention, and replay without turning the project into database engineering?
- Which Pump/PumpSwap surfaces expose source-native stable identities and cursors, and which
  require synthesized identities with an acknowledged collision risk?
- How much raw social media and imagery can be retained legally and operationally, and what
  deletion obligations can coexist with immutable research provenance?
- Is a browser merely a renderer for a local API, or must it capture the Pump-equivalent
  scene directly? Browser/session cookies should not enter collectors by accident.
- What is the right granularity for scene manifests: every UI frame, meaningful viewport
  changes, gestures, or a bounded ring buffer around gestures?
- Can a hardware/OS-backed signer expose enough transaction detail for independent semantic
  checking, or will a small software-key signer be necessary for the first live slice?
- Which program deployment/upgrade facts must invalidate a signer specification
  automatically?
- How should global portfolio reservations serialize independent strategy books without
  coupling their inference logic?
- What confirmation/finality level is sufficient for responsive inventory while preserving
  an honest provisional/final distinction?
- Which kill actions remain possible when the evidence store, UI, RPC provider, or local
  network is down?

## Dependencies on other lanes

- **Evidence/event model:** stable episode, inventory-interval, gesture, scene, provenance,
  and source-health semantics.
- **Attention and UI instrumentation:** viewport/candidate denominator, idempotent gesture
  definitions, scene-capture cadence, and degraded-state presentation.
- **Market data and execution-quality research:** feed completeness, quote/reserve/fee
  semantics, canonical pools, freshness tolerances, and chain reconciliation fields.
- **Crackle/runner/fancoin/LP lanes:** each action family's dependency declaration,
  disposition transitions, maximum-loss semantics, and operations that must be impossible.
- **Accounting lane:** lots, basis, partial exits, runner exposure, flat intervals,
  re-entries, fees/rent, unresolved reservations, and actual-vs-mark valuation.
- **Model/LLM lane:** annotation provenance, prompt-injection containment, external data
  transfer policy, and reproducible model/prompt/input versions.
- **Product architecture:** local deployment shape, query snapshot semantics, offline and
  degraded behavior, backup/restore, and operator kill ergonomics.

The reconciliation phase should choose the smallest boundary set that preserves these
invariants. It should not select technology or introduce a signer merely because the old
repository already contains one.
