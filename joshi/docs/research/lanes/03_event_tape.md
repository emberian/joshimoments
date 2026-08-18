# Lane 03: event tape, choice-set memory, and replay

Status: research proposal; no engineering commitment.

## Recommendation

JOSHI needs one evidence substrate with two acquisition modes:

- a **market census** that continuously records what existed, what Pump surfaced, and coarse
  lifecycle, market, and social state across the whole observable surface;
- **hot lanes** that begin when a coin enters Ember's attention and preserve every state change,
  quote evaluation, interaction, and execution outcome at the resolution required to reconstruct
  an episode, including flat intervals and re-entry.

These are not separate datasets joined after the fact. A hot lane is a declared change in
observation resolution inside the same time-indexed evidence system. Its opening, manifest,
degradation, and closing are themselves events. This is how we retain the market-wide denominator
while spending high-resolution attention only where it can teach us something.

The tape must support two different replays:

1. **As-known replay:** exactly what the operator and system could have known at a decision time.
   Late backfills, later identity resolutions, future engagement counts, and corrected chain facts
   are excluded.
2. **Retrospective replay:** the best later account of what happened, including final chain state,
   corrections, and later outcomes.

Conflating them creates future leakage. Keeping only the first prevents honest outcome analysis.

This lane specifies evidence, not a database product. Append-only object storage, a log, and
derived analytical tables are plausible implementation components, but choosing them now would be
premature.

## Scope and questions

The tape must make the full process in `docs/PROJECT.md` inspectable:

```text
market universe -> surfaced set -> rendered set -> viewport -> inspection -> disposition
    -> entry -> management -> exit -> flat watch -> re-entry -> retained exposure -> resolution
```

It must answer, without reconstructing intent from transactions alone:

- What market and social observations existed?
- Which observations had reached JOSHI by then?
- What candidates did the product fetch, rank, render, and place in the viewport?
- What did Ember open, hover, compare, annotate, arm, reduce, exit, keep watching, and revisit?
- What exact chart range, feed items, portfolio state, and executable quotes were visible?
- What did a source say at the time, even if it later changed or disappeared?
- Where was the recorder blind, stale, delayed, or decoding against an obsolete contract?
- What transaction was intended, quoted, constructed, sent, landed, and reconciled?
- Can a later study recompute an interpretation under a new parser or model without rewriting
  history?

This lane does not define episode accounting, trading policies, or the final UI. It provides the
evidence those components consume.

## Evidence from the `joshibot` compost

The old repository contains useful, tested fragments. It also demonstrates why a broader contract
is necessary.

### Load-bearing ideas to retain

- `shitcoims_tape/schema.py` keeps raw token and lamport amounts as integers in memory and decimal
  strings in JSON. This avoids silent `f64` corruption and should remain universal for monetary,
  reserve, supply, and fee quantities.
- It separates chain time from observer time and retains virtual and real bonding-curve reserves.
  `studies/PANEL.md` reconciled 100 of 100 sampled reserve states against Pump to within one base
  unit. Exact state, rather than chart price, is the correct substrate for quote replay.
- `shitcoims_tape/sources.py` and `shitcoims_scalper/firehose.py` treat disconnects as data. Watch
  manifests, gaps, heartbeats, cursor termination, and informative censoring are more valuable than
  a collector that silently reconnects and looks healthy.
- `shitcoims_scalper/firehose.py` preserves `t_event = null` when PumpPortal supplies no event clock
  and labels vendor-rounded floats as unsuitable for accounting. Missing precision must not be
  manufactured.
- `shitcoims_pumpsocial/models.py` separates a post's event time from ingest time, keeps mutable
  engagement counts as read-time snapshots, preserves raw text and thread structure, validates
  wallet-shaped identifiers, and treats absent counts as unknown rather than zero.
- `shitcoims_pumpsocial/crawl.py` reports full-page-without-cursor, page caps, cursor loops,
  unreadable reply tails, and failed roots as truncation rather than silently calling a crawl
  complete.
- `shitcoims_scalper/boards.py` records board membership and rank as snapshots and explicitly opens
  and closes observation windows. Board absence outside a live window is unknown.

### Limits and scars that change this design

- The old tape is a market-event schema, not an evidence envelope. It cannot represent viewport,
  choice set, operator gesture, quote lifecycle, source response, correction, model interpretation,
  or the transition from an exit to continued flat watching and re-entry.
- Its `event_id` hashes `observed_at` and provenance together with the alleged fact. Consequently,
  the same fact arriving through two sources is not necessarily the same identifier. Conversely,
  `studies/PANEL.md` reports 28 byte-identical fills within transactions being collapsed. Two
  legitimately repeated events may have identical values. Observation identity, raw-payload
  identity, and event/fact identity must be separate concepts.
- The old board fetcher maps any exception to `[]`; the watcher then interprets `[]` as a failed
  fetch. That is safer than calling it an empty board, but it loses status, body, latency, and the
  distinction between a valid empty response and a transport failure.
- The panel found 2.54% of trade events were rejected after Pump's layout drifted. Fail-closed
  parsing was correct; retaining raw transaction/log/instruction bytes is what allows later parser
  repair. A normalized row alone cannot be re-decoded.
- The old launch reader converted an omitted social flag into `False` on round-trip. This is a
  concrete demonstration that nullability is not enough; observation status must survive every
  serialization and materialization.
- Pump's social APIs contain mutable peak statistics, stale caches, HTTP-200 nulls, ambiguous
  `userId` namespaces, multiple casing conventions, capped pagination without a cursor, and
  reverse-engineered contracts that drift. The raw response and source contract version matter as
  much as the parsed object.
- Thirty-second board polling measured broad surfacing but cannot resolve a seconds-scale crackle.
  Board entry/exit is interval-censored between successful polls, not known at the ingest timestamp.
- The old `Callout` tape retained only a text hash while the social package retained prose. Future
  multimodal and LLM analyses require the source content, media, authorship, and thread context,
  subject to an explicit retention policy.

These are observed properties of the local code and studies, not claims about a future system.

## Proposed abstraction: three layers, not one universal event row

### 1. Raw observation

A raw observation says, “source S returned these bytes to collector C at this time under this
request and watch manifest.” It does not claim the source was true.

Conceptual fields:

```text
ObservationEnvelope
  observation_id             unique acquisition attempt/result, never a fact key
  source_id                  provider + endpoint/program + network
  source_contract_version    documented/IDL/bundle/probe version, if known
  collector_build, run_id
  watch_window_id, scope_id
  request_id                 joins request, response, retries, and pagination
  source_object_locator      typed namespace; never an unqualified `userId`
  source_cursor / sequence / subscription id
  t_request_start
  t_receive                  first/last byte or websocket frame receipt
  t_persist
  local_monotonic_start/end  latency despite wall-clock adjustment
  source_event_clock         value, unit, authority, precision, or explicit absence
  chain_locator              cluster, slot, tx index, signature, instruction/log index
  commitment/finality
  http/ws metadata           status, selected safe headers, cache/computed-at metadata
  raw_blob_hash              hash of exact bytes before parsing
  raw_encoding/content_type/byte_length
  parse_status               unparsed, parsed, partial, quarantined, contract_drift
  redaction_manifest         credentials/cookies that were never stored
```

`observation_id` is always unique. Repeated fetches of identical bytes have different observation
IDs and the same blob hash. That distinction measures cache staleness and source availability.

The raw store must never contain wallet secrets, bearer tokens, signed login challenges, cookies,
or credentialed URLs. Public transaction signatures and signed transaction bytes are not private
keys, but execution retention still needs a reviewed policy before trading is enabled.

### 2. Versioned assertion

A parser produces typed assertions from one or more observations. Assertions are replaceable
beliefs, not mutable facts.

```text
Assertion
  assertion_id
  assertion_kind
  natural_event_key          source- and kind-specific, with a typed namespace
  subject/object ids
  value                      exact integers plus explicit units where monetary
  event_order/event_interval
  evidence_observation_ids
  parser/decoder version
  produced_at
  validity                   asserted, disputed, superseded, retracted, canonical
  supersedes/retracts
  quality flags              delayed, partial, inferred, interval-censored, vendor-rounded
```

Examples of natural event keys:

- chain event: `(cluster, signature, tx_index, instruction_path, log_or_event_index)`;
- account state: `(cluster, account, slot, write_version)`;
- social object revision: `(provider, object_namespace, object_id, raw_blob_hash)`;
- board snapshot: `(provider, board, request_id)`;
- operator gesture: `(client_session, monotonically increasing gesture_sequence)`.

Values are not deduplicated merely because they are byte-identical. Two equal swaps in one
transaction remain two events because their instruction/event indices differ.

### 3. Derived interpretation and materialized view

Chart bars, identities, community states, LLM labels, volatility kernels, analog embeddings,
episodes, and candidate rankings are derivations:

```text
Derivation
  derivation_id, kind
  input observation/assertion/derivation ids
  code/model/prompt/config versions
  produced_at and earliest_available_at
  output blob/value
  exploration/production designation
  supersedes/retracts
```

An LLM conclusion such as “creator appears aware” is never written into the raw post or promoted
to an eternal coin attribute. A later model can recompute it from the same inputs. Non-deterministic
outputs are stored with the exact output, model identifier, prompt/template version, and input
manifest.

## Two acquisition modes

### Market census

The census preserves the denominator and the Pump-like information surface. Its minimum scope is:

- Pump launches, curve lifecycle, migrations, and venue/pool relationships;
- compact exact Pump and PumpSwap trade facts where a program-level stream makes this feasible;
- periodic state reconciliation sufficient to detect stream gaps and reserve drift;
- all candidate-board responses with exact membership, order, rank, query, limit, and polling
  interval;
- global/recent callouts, communities/trenches surfacing, live-stream state, and other feed items
  JOSHI actually renders;
- metadata and media locators as first observed, with later revisions separate;
- source coverage and health.

The census is allowed to be coarse, but never ambiguously coarse. For example, a board membership
change observed between successful polls at `t0` and `t1` has an event interval `(t0, t1]`; it did
not necessarily happen at `t1`. A five-second flow bucket records the exact covered interval,
source completeness, input count, and transformation version.

Program-level acquisition should retain compact raw instruction/event bytes and ordering metadata
even if full verbose transaction JSON cannot be kept forever. During the measurement pilot, retain
both; choose a reduction only after measuring which fields are needed for balance, signer, fee,
reserve, failed-attempt, and decoder-drift reconciliation.

### Hot lane

A hot lane is keyed by mint but scoped by a declared manifest. Opening one records:

- why it opened: operator selected, inspected, armed, currently held, runner, social-watch, or
  machine-nominated;
- requested feeds and accounts, quote venues, chart resolutions, wallet/episode links, and TTL;
- the observation coverage already available before activation;
- activation latency and the interval that remains unknowable because high-resolution watching
  began after selection.

While hot, preserve:

- every relevant transaction/event and account-state update in chain order;
- bonding-curve or pool reserves, virtual reserves, token supply/decimals, program/config state,
  dynamic fee configuration, migration state, and route availability;
- exact size-specific quote requests and policy evaluations;
- live social posts/replies/callouts and revisions at the fastest source-supported cadence;
- chart source points and the chart domain actually rendered;
- viewport scenes, gestures, annotations, and disposition changes;
- wallet transactions and balance changes observable on chain, whether initiated by JOSHI or
  externally;
- explicit time spent flat but still watching.

Closing or degrading the lane records why, which subscriptions actually closed, the last high-water
marks, and whether the episode remains open. “No position” must not automatically mean “stop
watching”; exit-and-re-entry is part of the policy being measured.

## Time and order model

One field called `timestamp` is structurally inadequate. Use the following clocks without copying
one into another:

- **Source event time:** when the source claims a post, callout, board computation, or other event
  occurred. It includes authority, unit, timezone, and precision. It may be absent or wrong.
- **Chain order:** `(slot, transaction index, instruction path/event index, write version)` is the
  ordering authority for chain events. `block_time` is useful wall time but not a total order.
- **Request/receive/persist time:** when our process requested, received, and durably stored an
  observation. These establish whether it was usable at a decision time.
- **Available time:** when parsing/validation completed and the observation entered a product view
  or policy. This is derived from recorded pipeline transitions, not guessed from ingest time.
- **Render/viewport time:** when a specific view model was rendered and when its viewport state was
  sampled or changed.
- **Decision time:** client-origin gesture time plus server receipt. Pointer-down, confirmation,
  transaction signing, and semantic action are separate when relevant.
- **Enrichment time:** when a resolver, LLM, or study produced an interpretation.
- **Execution times:** quote requested/received, transaction built, signed, first sent, each
  rebroadcast, RPC acknowledgement, processed, confirmed, finalized, expired, and reconciled.

Local wall time should be accompanied by a monotonic duration clock and clock-health samples. An NTP
step must not create a negative execution latency. Uncertain source times carry intervals or
precision rather than false microseconds.

Backfill keeps its true late ingest/available times. It may improve retrospective replay but never
appears in as-known replay before it arrived.

## Required observation families

### Pump/PumpSwap chain state

For every relevant chain item, retain enough raw context to re-decode after IDL drift and a typed
assertion containing:

- exact chain locator and finality history;
- program and instruction/event identity, including unknown discriminator and trailing bytes;
- mint, curve/pool/venue, trader, signers, and fee payer as distinct roles;
- exact token and quote deltas with mints, decimals, and units;
- protocol, creator, LP, buyback, cashback/rebate, network, priority, and rent components when
  observed; unknown components remain unknown rather than folded into one invented fee;
- curve/pool state before and after where observed, including virtual quote reserves;
- current fee-config account version/hash and tier used for the quote/trade;
- transaction success or failure, error, compute consumption, and balance reconciliation;
- migration links between curve and canonical pool and any route ambiguity.

Hot-lane account snapshots should be anchored to slot and raw account-data hash. A quote cannot
claim to be exact if its reserve state is merely “latest sometime recently.” Census-derived
reserves may advance from a complete event stream, but periodic authoritative account snapshots
must detect gaps. After a gap, derived state remains tainted until reconciled.

Pre-finalized Solana observations may later be orphaned. Record the original observation and append
a finality/canonicality correction; never delete the first view of what the live system saw.

### Boards, feeds, and choice sets

For every fetch, preserve request parameters, safe response metadata, raw response, source
`computedAt`/cache age if present, and exact item order. Derive separately:

```text
surface set    all items returned and eligible under the query
rendered set   items JOSHI materialized after client filters
viewport set   items intersecting the visible application viewport
interaction set items opened, hovered, compared, dismissed, annotated, or armed
```

Viewport is evidence of possible exposure, not proof of gaze or comprehension. Hover, dwell, scroll,
and panel opening strengthen attention evidence but still do not justify pretending we have eye
tracking.

A `SceneSnapshot` should reference, rather than copy inconsistently:

```text
scene_id, client_session, UI build and feature flags
t_render, t_capture, viewport dimensions and application panel geometry
active routes/tabs, sort/filter/search state
ordered surface/rendered/viewport item ids and coordinates
opened mint(s), comparison set, feed cursors
chart domain, resolution, indicators, zoom, drawings and selected point
portfolio/accounting snapshot id
displayed quote ids and staleness badges
latest observation/derivation watermark by source
optional application-only screenshot blob
```

Capture a full scene at session start, hot-lane open, and every consequential gesture, with deltas
between. Structured state makes replay and analysis possible; app-scoped screenshots provide a
perceptual checksum and recover details the initial schema forgot. Screenshots must not include
unrelated desktop content.

Every gesture references the scene and choice set it acted within. A later interview references the
original gesture and replays its as-known scene, while remaining a new retrospective annotation.

### Quotes and execution telemetry

A quote is an observation for one exact action, not a price mark:

```text
QuoteObservation
  quote_id, episode/hot_lane/mint
  side, exact input or exact output, raw integer amount and mint
  venue/route and program versions
  state anchor: slot + account hashes + fee-config hash
  gross input/output, every known fee/rebate, impact, min/max constraint
  transaction/network assumptions: priority, compute, ATA/rent, slippage
  requested/received/displayed/expired times
  provider response blob and local quote implementation version
  validity and rejection reason
```

For a crackle exit, the evaluation must use the actual token amount available and net SOL that could
be received, compared with actual settled costs. Persist every state or policy evaluation capable of
triggering an action; purely deterministic intermediate display quotes may be regenerated from their
state and implementation version, but quotes shown at decisions or used by automation are always
materialized.

Execution is a lifecycle, not a boolean:

```text
intent -> confirmation -> build -> simulation -> signature -> send attempts
       -> processed/landed-failed/landed-success/expired/unknown
       -> confirmed/finalized -> balance and inventory reconciliation
```

Record the transaction message/hash, exact signed bytes or a reviewed equivalent, same-bytes
rebroadcast identity, RPC endpoint class, simulation result, send response, chain error, fill event,
and reconciled wallet deltas. Never infer a fill from an accepted RPC response or a chart movement.

During the current research phase, JOSHI does not sign or submit. The schema can record shadow
quotes, operator intent, and externally submitted transactions observed on public chain data.

### Social, media, community, and identity

Raw social observations include response bytes and revision snapshots for:

- posts, replies, callouts, deletion/tombstone status, authors, mentions, and thread edges;
- community headers and whatever membership evidence the source truly supplies;
- profiles, numeric social IDs, usernames, display names, bios, follower/following observations,
  and timestamped follow edges;
- media URL, response metadata, content hash, media type, dimensions/duration, and—where policy and
  source terms permit—first-seen bytes;
- verified social-recipient fee claims, ordinary permissionless fee sweeps, public participation,
  and later LLM interpretations as distinct event kinds.

Engagement and profile fields mutate. Each fetch is a snapshot at read time, not a correction to
the post-time record. A deleted or edited object appends a new revision. If a legal or policy
requirement forces content deletion, preserve a deletion audit/tombstone and hash only if permitted;
immutability is not a reason to violate that requirement.

Identity is a bitemporal evidence graph, not a mutable `creator` column:

```text
IdentityAssertion
  typed subject and object namespaces
  relation: controls_wallet, linked_social_id, used_username, represented_person,
            fee_recipient, deployer, public_participant, suspected_imitation, ...
  evidence ids and method
  event-valid interval             when the relation allegedly held
  system-known interval            when JOSHI believed it
  confidence/status and resolver version
  supersedes/retracts
```

This prevents today's creator, username, or resolved person from leaking into an earlier scene.
Provider-local UUIDs, wallets, numeric X IDs, and handles never share an unqualified ID field.

## Replay contract

### As-known replay

Given client session or episode `E` and decision time `T`:

1. select only observations durably received and made available by `T`;
2. apply only parser, identity, ranking, and model versions deployed at `T`;
3. restore the UI build, feature flags, filters, chart domain, drawings, viewport geometry, and
   source watermarks from the referenced scene;
4. restore quote values actually displayed, including staleness and unavailable routes;
5. render gaps and missing fields as unknown;
6. verify against the optional app screenshot and a scene/view-model hash.

This replay answers what the policy could know. A post created before `T` but fetched after `T` is
not present.

### Retrospective replay

Retrospective replay uses final canonical chain facts, source event times, late backfills, corrected
parsers, identity revisions, and observed future outcomes. It answers what happened, not what was
known. Both replays point to the same immutable observations and declare the view policy used.

### Counterfactual execution replay

A counterfactual quote or fill is reproducible only if the tape has exact pre-action state, ordering,
fee configuration, token amount, route, and latency assumption. It must be labeled simulated and
must not inherit the actual transaction's favorable ordering. If a source gap makes reserves
unreconstructable, the interval is unquotable rather than interpolated.

Replay manifests should hash all required blobs, versions, and configuration so a result can prove
which evidence it consumed. The first replay implementation should favor correctness over trying to
recreate every animation.

## Corrections, disagreement, and deletion

- Raw observations never update in place.
- A new source response for the same object is a new revision, even if only a count changed.
- A corrected decoder appends new assertions against the old bytes and supersedes its own prior
  assertion; it does not rewrite the observation.
- Independent sources may disagree. Store both assertions and make reconciliation a versioned
  derivation with evidence, never “last write wins.”
- Backfill closes a knowledge gap retrospectively but does not erase the recorded outage or change
  when JOSHI learned the event.
- Retention expiry appends a manifest naming the blobs removed, policy, time, and surviving hashes.
  A replay then reports unavailable evidence rather than silently using a materialized table.

## Coverage and source-outage ledger

Coverage must be queryable per source and scope. A global “collector was up” flag is insufficient
when one keyed subscription, cursor family, board, mint, or social endpoint has silently died.

```text
CoverageWindow
  coverage_id, run_id, source_id
  exact subscription/request manifest and typed scope
  opened_at, first_success_at, last_event_at, last_heartbeat_at, closed_at
  source cursor/sequence/slot high-water marks
  events, bytes, defects, quarantines, retries
  close reason and whether censoring is informative

CoverageGap
  source_id and exact affected scope
  lower/upper time and slot/cursor bounds
  detection method
  cause: disconnect, process_down, auth/rejection, rate_limit, schema_drift,
         stale_cache, open_but_silent, disk_backpressure, clock_fault, unknown
  recovery attempts and backfill coverage
  resolved/partially_resolved/unrecoverable
```

Detect both transport and semantic outages:

- HTTP error, timeout, websocket close, process death, disk write failure;
- a 200 response with null, capped, malformed, repeated, or implausibly stale content;
- open socket with active global frames but no keyed-feed frames;
- cursor loop or high-water mark that stops advancing;
- parser quarantine or unknown-discriminator rate change;
- cross-source launch/trade/reserve counts diverging beyond measured tolerance;
- state reconciliation failing after apparently complete event coverage;
- heartbeat present but event freshness outside the source's empirically measured distribution.

Heartbeats prove only the component emitting them is alive. An external watchdog must detect a dead
process that cannot emit its own failure. Quietness becomes a valid zero only inside healthy,
correctly scoped coverage with a source for which silence has that meaning.

## Volume, tiering, and retention

Do not choose retention from intuition. Run a bounded pilot and measure, per source and event family:

- events and requests per second, burst percentiles, and reconnect bursts;
- raw, normalized, indexed, and compressed bytes per event;
- parser quarantine rate and full-transaction promotion rate;
- hot-lane duration, concurrent hot mints, quote evaluations, scenes, screenshots, and media bytes;
- write latency, queue depth, dropped events, and replay read amplification.

The capacity identity is simple and should be printed in the pilot report:

```text
daily bytes = 86,400 * mean events/second * mean stored bytes/event
```

For scale intuition only, 100 events/s at 500 compressed bytes is 4.32 GB/day, whereas keeping
10 KB transaction envelopes is 86.4 GB/day. The decision between those representations changes
annual storage by tens of terabytes. Actual measurements, not these examples, decide.

A plausible retention hierarchy to test:

- keep small exact chain event bytes, natural keys, coverage, launches, migrations, board/feed
  membership, gestures, decisions, and all episode-linked evidence durably;
- keep full verbose market-wide transaction/provider responses in a rolling raw tier, promoting
  hot-lane, sampled-control, disagreement, quarantine, and reconciliation records to durable
  storage before expiry;
- keep deterministic census rollups durably with input coverage and transformation versions;
- keep hot-lane state, quotes, scenes, annotations, and execution telemetry for the life of the
  research corpus;
- deduplicate media and raw blobs by content hash, while retaining each observation envelope;
- use a deliberate media and operator-annotation retention policy rather than inheriting the
  chain-data policy.

This hierarchy is a hypothesis. The pilot must first determine whether compact raw program events
plus promoted transactions preserve enough context. Deleting raw evidence too early would make
future questions unanswerable; retaining every verbose response forever could prevent the recorder
from running reliably.

Backpressure behavior must be explicit. If storage cannot keep up, fail/degrade by declared source
priority and open a coverage gap. Never drop the busiest events silently, because loss correlated
with activity corrupts precisely the regimes of interest.

## Invariants

1. Raw source bytes are immutable; corrections are appended.
2. Every parsed or derived value cites input evidence and a producing version.
3. Unknown, absent, observed zero, parse failure, source refusal, and stale are distinct states.
4. Raw monetary/state quantities are exact integers with typed mints and units; vendor-rounded
   numbers remain labeled approximations.
5. Chain events use a complete within-transaction locator; equal-valued events are not collapsed.
6. Observation identity, blob identity, source-object identity, and canonical event identity are
   separate.
7. Source event, chain, ingest, available, render, decision, enrichment, and execution clocks are
   never substituted for one another.
8. A zero or absence is usable only inside a healthy, scoped coverage window.
9. Backfilled data never appears in as-known replay before its actual availability time.
10. Every consequential gesture references a contemporaneous scene and choice set.
11. Viewport means possibly visible, never definitely perceived.
12. Every automated action references the exact policy evaluation and quote that authorized it.
13. A quote references exact size, state slot/hash, route, fees, assumptions, and expiry.
14. A fill comes only from chain-confirmed execution and wallet reconciliation, never an RPC ack or
    chart mark.
15. Parser drift quarantines raw observations and raises health defects; it does not stop raw
    capture or coerce a partial decode into a fact.
16. Hot-lane open/close/degradation and flat-watching intervals are first-class events.
17. No credential or secret-bearing request material enters the raw store.

## Failure modes and counterexamples

### The tape captures transactions but not the decision

An exit followed by re-entry looks like two unrelated trades. Without the scene, annotation, flat
watch, and disposition transitions, no study can tell graph-driven management from a fixed exit
rule. Transaction history alone is insufficient.

### The scene is a screenshot only

A screenshot may recover visual atmosphere but cannot identify the complete candidate denominator,
exact quote, feed cursor, or source freshness. Keep structured view state plus an app screenshot at
salient moments.

### The scene is structured only

An early schema will omit visual details Ember responded to. Without periodic perceptual captures,
we will not know that the formal scene was a pale projection. Use both representations.

### Hot watching begins after the interesting event

This is unavoidable when human attention selects a coin. Record activation latency and retain the
coarse census before activation. Do not backfill high-resolution state and pretend it was live.

### Poll time is treated as event time

Board membership, profile counts, and community state are observations at poll time; a transition
usually happened in an interval. Treating the right endpoint as exact manufactures ordering against
trades and gestures.

### Current identity leaks into history

Using today's creator, username, or represented person at old decision times creates apparent early
knowledge. Identity assertions need event-valid and system-known intervals.

### An endpoint is green but semantically dead

A 200 with a repeated cache, null payload, capped first page, or a silently rejected subscription is
not healthy coverage. Raw responses, high-water marks, freshness distributions, and cross-source
checks are necessary.

### Dedupe removes real events or preserves duplicate observations as facts

Content equality is neither event identity nor source independence. Use chain location for chain
events, typed object revisions for social data, and raw hash only for blob storage.

### Reserve state survives a gap as if nothing happened

Advancing an AMM state machine requires complete ordered inputs. Taint derived state on a gap and
reconcile from an authoritative account snapshot before quoting again.

### Layout drift is a missing-at-random assumption

The old panel's trade-event drift was not guaranteed uniform across coins or regimes. Monitor defect
rates by event size, discriminator, program version, mint, and time; preserve bytes for later decode.

### Retention creates invisible non-reproducibility

A materialized feature may outlive the raw inputs that justified it. Expiry manifests and replay
health must state when recomputation is no longer possible.

### Volume shedding follows market activity

Queues overflow on the busiest coins, creating falsely calm data and biased execution estimates.
Priority degradation must emit scoped gaps and be tested under bursts.

### External trades have fills but no intent

During early use Ember may act through Pump or another interface. Public chain observation records
the fill, but not when the decision was made or what was seen. JOSHI needs a lightweight pre-action
gesture or manual link; otherwise label intent as unobserved rather than reconstructing it.

### Reorg or RPC disagreement rewrites live history

The live system may act on a confirmed state later orphaned. Preserve the original observation,
record finality transitions, and use canonical state only in retrospective replay.

## Smallest useful vertical slice

Build no general warehouse first. Prospectively record one real operator session and the next coin
that passes through inspection, a crackle decision, management, an exit, continued watching, or
re-entry. Existing RADON, EarthCoin, and CRASHIUS can test current exposure rendering, but their past
attention scenes cannot be reconstructed and must not be treated as captured episodes.

The slice is read-only and shadow-only under the current project boundary:

1. Run a bounded census containing launch/migration stream, the exact boards and feeds rendered in
   the prototype, raw responses, and coverage health.
2. On `inspect` or `arm`, open one hot lane and record its manifest and activation gap.
3. Capture exact chain events/account states, dynamic fee state, and event-driven shadow quotes for
   that mint. No transaction is signed or submitted.
4. Capture a full structured scene and app-only screenshot at inspection, arm, hypothetical or
   externally executed entry, partial/full exit, disposition change, and re-entry; record deltas and
   lightweight annotations between them.
5. If Ember trades externally, observe the public wallet transaction and allow an explicit gesture
   to link it to the episode. Keep intent unknown if no gesture preceded it.
6. Replay each decision once as-known and once retrospectively. Conduct one replay-backed annotation
   or interview after the session.
7. Deliberately inject a source disconnect, a late backfill, and an unknown parser field/event into
   the test environment.
8. Measure event rate, raw/compressed size, hot-lane amplification, end-to-end lag, and replay cost.

Acceptance checks:

- the replay reproduces the exact ordered choice set, viewport, chart domain, source freshness,
  portfolio snapshot reference, and displayed quote at every captured gesture;
- a social item fetched after a decision is absent from as-known replay and present retrospectively;
- a disconnect renders an unknown interval and is not zero-filled after backfill;
- two identical-valued events at different chain indices both survive;
- quote recomputation from the same state and implementation matches exact raw output, or the
  discrepancy is surfaced;
- an observed external transaction reconciles exact wallet deltas and is not assigned fabricated
  intent;
- raw payloads rejected by the current parser remain retrievable for a corrected parser;
- no stored record contains configured secret canaries or credentialed URLs;
- the capacity report gives measured daily storage and a declared loss/degradation policy.

This slice is useful even if Ember's strategy is negative-EV: it establishes whether the apparatus
is measuring the policy that actually occurred.

## Dependencies on other lanes

- **Product sensorium and interaction design:** defines boards/feeds rendered, gesture semantics,
  chart state, disposition controls, and the minimum non-disruptive attention trace.
- **Episode and portfolio accounting:** supplies episode, lot, inventory-interval, realized-basis,
  runner, flat-watch, and external-transaction linkage semantics.
- **Pump/PumpSwap protocol and quote research:** supplies current IDLs, state accounts, event
  ordering, dynamic fee/config rules, migration mapping, quote invariants, and reconciliation.
- **Execution and safety:** defines intent/authorization states, telemetry, credential boundary,
  transaction-byte retention, circuit breakers, and what remains shadow-only.
- **Social transition and identity:** defines typed entity namespaces, claim/participation events,
  community assertions, revision semantics, and media policy.
- **Research/evaluation:** defines chronological folds, contemporaneous controls, episode outcomes,
  replay APIs, exploration labels, and which census rollups must remain recomputable.
- **Operations/storage:** owns external liveness monitoring, durable append semantics, capacity,
  retention/backup, corruption detection, and recovery drills.

The dependency runs both ways: those lanes may refine their domain schemas, but none may bypass raw
observations, coverage, clocks, scenes, or versioned derivation provenance.

## Unresolved questions

1. Can full compact Pump/PumpSwap program events be retained market-wide indefinitely, and which
   full transaction fields must be promoted for later signer, failed-attempt, and fee analysis?
2. Which independent chain source is affordable enough to measure provider omission rather than
   merely parser coverage?
3. What source cadence and latency are required for a hot lane to resolve the crackle types Ember
   experiences? This must be measured against interaction traces, not chosen from a generic charting
   requirement.
4. How much app-scoped visual capture is necessary to discover omitted perceptual variables without
   producing unusable volume or capturing unrelated personal information?
5. Which public social/media bytes may be retained, for how long, and how are source deletion and
   legal erasure handled?
6. Can JOSHI observe an external Pump action early enough to link intent without adding enough UI
   friction to change Ember's behavior?
7. What exact event marks `available_at` in a distributed client: parser completion, state-store
   commit, client receipt, or first render? The slice should measure all four before choosing a
   study-facing definition.
8. Which raw fields are needed to reproduce chart rendering, including vendor aggregation and
   intra-bar order, without retaining redundant pixels indefinitely?
9. How long should a hot lane remain active while flat, and may resolution decrease without changing
   the policy being observed?
10. What is the minimum viable correction/finality model for live Solana decisions versus historical
    analysis?

No answer here depends on assuming the strategy works. The requirement is that, after an episode,
we can say what existed, what was available, what Ember attended to and expressed, what the system
did, what actually filled, and exactly where we do not know.
