# Review 02: getting to a truthful, useful cockpit without building the universe first

Status: pre-engineering reconciliation review. This document proposes product/research sequencing;
it does not authorize a wallet key, signer, transaction builder, submission path, purchase, or live
trade.

## Verdict

The lane plans are individually careful and collectively too large to call a first slice. If their
respective “smallest experiments” are simply combined, the project begins with an all-program chain
census, Pump feed parity, social and identity history, exact household accounting, a general event
store, deterministic replay, a hot quote engine, viewport telemetry, a portfolio/LP model, a
30-day fancoin docket, provider comparisons, and a polished cockpit. That is an abstract platform
program, even though every component has a legitimate eventual use.

The critical path is narrower:

> First prove that one discovery-to-inspection-to-management loop can be reproduced faithfully
> enough that Ember naturally uses it, and that one such session can be replayed without lying
> about what was known, intended, executable, or owned.

The first real product should therefore be a **read-only one-surface cockpit with an episode rail**,
not a general market data platform and not a shadow trading engine. It should become useful in
stages:

1. establish whether the Pump surface needed for one natural loop is lawfully and technically
   observable;
2. make current exposure and one ongoing episode legible while manual trading remains elsewhere;
3. make one Pump discovery surface and one coin workbench good enough to become Ember's natural
   place to look;
4. add shadow crackle/management counterfactuals only after the natural behavior is being captured;
5. broaden to one additional discovery hypothesis at a time, based on cockpit use;
6. consider any money-moving capability only under a separate later review.

This sequence deliberately accepts temporary incompleteness. It does not accept semantic
dishonesty. A small slice may omit a feed, model, strategy book, or counterfactual. It may not call
a mark an executable quote, a transfer profit, a fee sweep endorsement, a viewport gaze, a full
sell an episode resolution, or a feed substitute Pump parity.

## What “vertically useful” means here

A slice is vertically useful only if all of the following are true:

- Ember can use it during an ordinary market session for a concrete task they already perform.
- It begins before, rather than after, the decision whose context matters.
- It preserves the minimal scene, clocks, source health, operator act, and wallet consequence needed
  to tell an honest later story.
- It produces an operator-visible benefit now: clearer exposure, a better chart/social view, a
  lower-friction gesture, an exact hurdle, or a recognizable replay.
- It remains read-only with respect to money in the current phase.
- Its omissions are visible and constrain the claims that may be made from it.

A backend-only collector is a feasibility spike, not a product slice. A dashboard used only after
Ember finds a coin on Pump is a position companion, not an attention-funnel instrument. A beautiful
mock with fabricated candles or delayed marks is neither.

## The product/data feasibility spike must happen first

### Spike 0 — Pump surface and one-loop truth test

Run this before choosing the application architecture or committing to full-market ingestion. It
should be bounded to several normal Ember sessions plus a short source probe; it is not a crawler
build.

#### Observe the real workflow

Record, with Ember's explicit participation, three ordinary sessions in which they use Pump and any
other current tools. Use app-scoped notes or capture only. Inventory:

- which discovery surface produced each material candidate;
- exact sort/filter/search state, visible neighboring candidates, and update rhythm;
- which card fields, images, badges, posts, replies, callouts, communities, identities, holder or
  flow views, and chart behaviors affected inspection;
- what caused a switch to another site such as Padre;
- what Ember did on partial realization, full exit, continued flat watching, and re-entry;
- which cues Ember says were material but our candidate source cannot reproduce.

Do not start by assuming that `New`, `Trending`, `Live`, or `Callouts` is the first surface. Choose
the first surface from observed frequency and importance.

#### Probe only the selected loop

For that one discovery route and its coin detail page, compare the reference product with:

- supported or otherwise reviewed source access for exact candidate membership and order;
- the existing read-only Pump social adapters as a dated feasibility probe;
- public on-chain launch, trade, reserve, migration, fee, and wallet data;
- a genuine event-backed chart path;
- direct official-SDK and Jupiter query-only quotes at Ember's intended sizes;
- a read-only history and balance reconstruction for the wallet presently used.

Every compared field is classified as `public chain`, `authorized public/social`, `Pump-only`,
`derived`, `mutable/current-only`, `delayed`, `unavailable`, or `access status unresolved`. The
spike must include an explicit terms/access review. It must not quietly turn a browser-shipped key
or reverse-engineered endpoint into a presumed durable licence or SLA.

#### Required output

Produce a field-and-latency matrix and choose exactly one operating mode:

1. **Replacement-capable:** the chosen surface and coin page can be reproduced with stable enough
   access and measured fidelity.
2. **Companion-capable:** source APIs are incomplete, but app-scoped capture of the Pump view Ember
   is actually using is permitted and reliable enough to preserve choice-set and scene evidence.
3. **On-chain observatory only:** neither parity nor faithful user-side capture is available. Joshi
   can build its own observable universe but cannot claim to measure the Pump attention funnel.
4. **Stop/rethink:** the inaccessible Pump-only texture is central to Ember's selection and the
   reduced product would not earn natural use.

#### Exit criteria

The spike passes into the replacement-capable path only if:

- one named discovery surface can be identified by exact mints and order for at least 100
  consecutive reference cards or list entries sampled during the sessions;
- at least 95% of those items are captured by the proposed source within the measured reaction
  window, and every mismatch is retained rather than silently dropped;
- every cue Ember identifies as material on that surface is either reproduced, explicitly marked
  unavailable, or intentionally left in the reference-product companion view;
- a genuine chart/event source and a size-specific quote are available for at least 90% of the
  inspected mints in the sample, with unsupported lifecycle/venue cases named;
- the access basis, rate behavior, mutable fields, cache behavior, and expected breakage mode are
  written down; and
- Ember can review a reconstructed sample scene and identify no unknown material omission.

These percentages are product-feasibility gates, not scientific estimates. If personalization or
opaque ranking makes exact comparison impossible, the result is not “close enough”; it selects the
companion or observatory path and narrows the claims.

The spike fails if a source can produce similar-looking cards but not the actual choice set, if its
latency is large relative to Ember's reaction loop, if lawful/stable collection is unresolved, or
if the proposed chart is a reconstruction from broad percentage windows. Do not compensate by
starting a general data platform.

## Smallest sequence of useful slices

The slices below are cumulative only where the earlier capability proved useful. Their boundaries
are product behaviors, not infrastructure milestones.

### Slice 1 — exposure truth and one episode notebook

**User value:** Ember gets one trustworthy place to see the three named retained runners and to
mark what is happening to the next coin they care about, even while all financial action remains in
Pump or Padre.

Build only:

- a read-only wallet scope, initially one explicitly named wallet unless internal-transfer evidence
  requires a small declared household set;
- exact current quantities and a reconstructed history for RADON, EarthCoin, and CRASHIUS, with
  basis/proceeds gaps visible;
- current full-balance executable liquidation quotes where available, clearly separated from chart
  marks;
- one coin workbench opened by exact mint, with a genuine event-backed chart and source-health
  state;
- one persistent exposure/episode rail;
- coarse acts: `mark`, `watch`, `arm shadow`, `take some intent`, `keep remainder`, `zap intent`,
  `watch flat`, `re-enter intent`, and `resolve`; free text or `not articulable` is optional;
- append-only local operator events and scene references at those acts;
- observation of external wallet transactions and manual episode attribution when intent was not
  captured; and
- one outcome-hidden/as-known replay followed by an optional retrospective note.

The old runner histories are accounting fixtures, not historical attention examples. The first
prospective episode is the first valid scene-capture example.

Do not build a general portfolio service, a final event ontology, market-wide ingestion, a social
graph, automated microdip logic, LP controls, or a signer for this slice.

#### Exit criteria

- The scoped wallet's current token quantities reconcile exactly to finalized balances, or every
  residual has a named unresolved cause.
- The three runners display realized proceeds, remaining basis quality, exact quantity, executable
  liquidation value or honest unquotability, and current downside without calling any remainder
  free.
- A naturally occurring partial/full manual action is detected and linked without inventing its
  intent or fill time.
- One episode can remain open through a flat interval and a later re-entry intent; fresh basis starts
  at the new inventory epoch.
- A replay restores the market/chart, quote, portfolio, gesture, and known gaps that were actually
  available at the act. Later observations do not appear in the as-known view.
- Ember recognizes the segmentation and says the surface is useful for managing or remembering the
  exposure. If it feels like clerical bookkeeping, stop and revise before adding feeds.
- The repository and running process contain no signing or broadcast capability.

### Slice 2 — one discovery surface to one replayable workbench

**User value:** this is the first genuine cockpit slice. Ember can perform one common
discovery-to-inspection loop in Joshi without losing material information, while continuing to
trade manually elsewhere.

Add only the single surface selected in Spike 0:

- exact served membership/order and source response health;
- rendered and viewport membership separately;
- list freezing while a row is targeted, expanded, or annotated;
- direct navigation into the same coin workbench without destroying the originating list epoch;
- the chart, market/flow facts, and Pump social/thread elements that Spike 0 found material;
- an episode/exposure rail containing exposed, pending-external, and watching-flat rows;
- structured scene state plus an app-only screenshot at consequential gestures;
- exact-mint links out to the current manual execution surface; and
- external fill reconciliation when the wallet changes.

The UI should capture acts before explanation and should not ask Ember to choose among speculative
crackle types. `Other`, an empty fragment, and `not articulable` are normal states.

#### Exit criteria

- During at least five ordinary sessions, including two consecutive sessions after the latest
  material product change, Ember uses Joshi as the primary observation surface for the selected
  discovery loop. Switching to Pump/Padre for manual execution is expected; switching to recover
  missing discovery or coin-context information is logged as a parity defect.
- Sampled candidate membership meets the Spike 0 fidelity gate, and list reorder cannot change the
  target of a pointer/touch gesture.
- Every consequential gesture references a complete choice set, viewport, chart domain, source
  watermarks, quote/portfolio snapshot, and product version, or is visibly marked incomplete.
- At least 95% of gestures in the trial produce a recognizable replay without manual data repair;
  every failure is classified.
- Every observed wallet delta either reconciles to an economic event or remains visibly
  unattributed. No external transaction receives a fabricated pre-action scene.
- Median act-recording overhead is below the threshold Ember sets after the first session, and no
  exit or re-entry is missed because the product requested annotation.
- Ember's only material reason to leave this loop is an intentionally deferred capability, not an
  unknown gap disguised by the UI.

If these conditions fail, do not add more feeds. Repair the selected loop or adopt the companion
mode explicitly.

### Slice 3 — shadow crackle and episode-management instrument

**User value:** after Ember selects a coin, Joshi supplies vigilance, honest net hurdles, and
counterfactual memory without touching capital.

Add:

- `ARM SHADOW CRACKLE` with intended size, TTL, and one-shot scope;
- promotion of the selected mint to a high-resolution hot lane;
- exact direct/Jupiter query-only buy and sell quotes using current venue state, dynamic fee config,
  effective reserves, expected/minimum outputs, network/account assumptions, and quote age;
- immediate-entry and a small fixed family of candidate microdip interpretations evaluated side by
  side, with no claim that any one definition is Ember's crackle;
- latency-perturbed hypothetical execution rather than fills on the trigger tick;
- shadow `take some`, `profit + runner`, `zap`, `watch flat`, and `re-enter` paths inside one
  episode;
- a small contemporaneous comparison set from actually viewed/rejected candidates, not a
  whole-market mechanical policy; and
- immediate optional fragments plus selected outcome-hidden interviews.

There are no shadow “fills.” There are hypothetical quotes and paths. Manual external fills remain
actual and are reconciled separately.

#### Exit criteria

- At least 20 naturally armed episodes or two weeks of ordinary use, whichever is later, are
  captured without creating trades to fill the sample.
- Every shadow action can be recomputed from exact source state or is labeled unquotable; no chart
  price is substituted.
- Quote/replay uncertainty is materially smaller than the economic target: specifically, the p95
  discrepancy or latency envelope must be less than 20% of the smallest net-profit hurdle Ember
  would actually act on. If not, the proposed micro-profit scale is unresolved at this apparatus
  resolution.
- Immediate entry, candidate wait triggers, no entry/expiry, actual manual gestures, partial
  retention, full exit, flat watch, and re-entry are separately inspectable.
- The interface still clears Slice 2's natural-use and burden gates.
- The output is an apparatus report and a frozen protocol for a later cohort, not an EV verdict.

### Slice 4 — selective breadth, one earned lane at a time

Only after the selected-loop cockpit is producing natural behavior should the product broaden.
Choose the next lane from observed unmet needs, not from the elegance of the architecture. Likely
candidates include:

- another Pump discovery surface;
- followed-account and wallet activity that may precede callouts;
- launch/deployer/community “territory” context;
- fancoin/creator/community transition watches;
- richer runner and consolidated portfolio glass; or
- read-only LP schedule visualization.

Each candidate begins as a pane or feed inside the existing workbench and tape. It does not get an
independent warehouse, ontology, or automation engine.

Lane 12 gives the ecology and wallet ideas a useful narrow shape:

- A **territory** is a revisable temporal query over coins, launches, communities, and attention,
  not a predictive ecology service and not a permanent partition. The first UI is only a compact
  family strip showing exact mints, relationship evidence, alternatives, and a provisional leader
  by a named metric.
- A **watched wallet** is a candidate router. A direct, decoded signed trade by a wallet attached to
  a profile Ember already follows may promote a mint and its territory to the hot lane. It is not a
  copy instruction, an endorsement, a claim of skill, or proof that every profile wallet is a trade
  wallet.

These should be separate bounded additions even though they share a card. Prefer the wallet-router
pilot first if cockpit use confirms that followed accounts are already a meaningful part of Ember's
attention surface: it has a direct product action (`inspect` or `dismiss`) and a clear earliest-source
comparison. Start with at most 10–20 explicitly promoted profiles for 14 calendar days. Require
direct signed-user evidence, per-wallet coverage, complete buys/sells/partials, chain
reconciliation, exact receipt latency, anonymous-flow controls, and current quotes. Alert once per
mint/scene even when several watched wallets touched it.

Run a territory pilot only for attended/fancoin/wallet-promoted candidates, with at most 20 hot
territories for 14 calendar days. Seed exact metadata/image/deployer families, then show uncertainty
and let Ember say `same`, `not same`, `OG for now`, `moving to`, or nothing articulable. Preserve
typed relations: launch resemblance, community overlap, capital migration, and inferred wallet
fleet membership must never become one generic edge. A lightweight projection over the shared tape
is enough; do not introduce a graph database or ecological simulator.

#### Exit criteria for any added lane

- Ember used it in at least three ordinary sessions and can name a decision, comparison, or
  avoided mistake it made easier; mere curiosity clicks do not qualify.
- Its raw evidence, source coverage, point-in-time semantics, and missingness survive replay.
- It produces a measurable addition to the attention funnel—new inspections, explicit rejections,
  or better context on existing episodes—without displacing the primary loop with noise.
- Any identity, wallet, community, ecological, or social relation is presented with evidence and
  uncertainty rather than as a fact learned from a username/ticker match.
- If the lane is unused or mostly duplicates the primary surface, park it. Do not retain it because
  a future model might want the fields.
- For wallet routing specifically, continue only when at least one verified direct-trader profile
  repeatedly supplies useful lead time or selection context beyond anonymous flow at tolerable
  alert cost. Shelve it as a strategy input when identity adds no held-out information, arrives no
  earlier, or mainly induces FOMO. Its social identity can remain part of the scene.
- For territories specifically, continue only when the strip repeatedly reveals a rival,
  predecessor, successor, or movement Ember would otherwise miss, or adds information beyond
  coin-local state. Shelve the higher-order layer when proposals are mostly ambient collisions or
  launch farms, migration collapses to ordinary wallet rotation, or maintenance costs more
  attention than it returns.

### Slice 5 — retrieval, interviews, and the first evaluation block

Once prospective episodes exist, add analytical value without inventing autonomy:

- retrieve causally prior scenes similar to the current one and show their heterogeneous outcomes;
- sample replay-backed interviews, with outcome-hidden and outcome-aware passes kept distinct;
- offer pairwise `same kind / importantly different / cannot tell` comparisons;
- let provisional crackle/disposition tokens emerge from use; and
- freeze the first chronological evaluation protocol only after coverage, dependency, tail
  frequency, and quote error have been measured.

Program synthesis, circuit abduction, multimodal ranking, and realtime LLM transition analysis can
begin here as offline/versioned annotations. None should appear as a capital-authorizing control.

#### Exit criteria

- Retrieved examples come only from evidence available before the current decision and link back to
  their raw scenes.
- Ember recognizes some comparisons as meaningful or explicitly demonstrates that the proposed
  representation is inadequate.
- Immediate and retrospective accounts are not merged into one ground-truth label.
- The evaluation protocol names population, policy/version, outcomes, executable assumptions,
  regime grouping, stopping rule, and falsifier before its future block is opened.

## What to defer aggressively

Until the preceding slices earn them, defer:

- a universal event schema covering every eventual source and strategy family;
- Kafka, ClickHouse, Kubernetes, a lakehouse, or indefinite retention of verbose whole-market
  transactions and media;
- paid low-latency infrastructure before a bounded standard-RPC/source test demonstrates the need;
- complete Pump parity across every board, search mode, live stream, community, social, mobile, and
  personalized surface;
- a 30-day fancoin study before the shared surface can preserve candidates and point-in-time state;
- whole-X ingestion, a general identity graph, sentiment scores, and realtime LLM decision support;
- automated wallet copying, ecological territory scores, autonomous candidate nomination, or a
  claim that followed accounts are skilled;
- a fixed 3–8 disposition taxonomy or 2–5 crackle taxonomy;
- analog embeddings, program synthesis, hybrid-system identification, or an ML feature store before
  replayable prospective scenes exist;
- LP construction, add/remove/rebalance, exact signer postconditions, and LP capital policy;
- a generalized household portfolio allocator beyond the current read-only scope;
- mobile parity, complex drawing tools, TradingView Advanced Charts, and desktop packaging;
- a transaction builder, signer, key loader, send endpoint, managed signing product, or tiny-live
  trial.

The deferral is not a declaration that these components are unimportant. It keeps them from
preventing the only process that can tell us which ones matter.

## Selective composting from `joshibot`

Old components should be copied as small, named donors with conformance tests and provenance. Do
not make `joshi` import the old repository as a runtime dependency, and do not migrate its current
database/state wholesale.

### Adapt now or during the feasibility spike

| old asset | temporary use | do not inherit |
| --- | --- | --- |
| `app/components/pricechart.tsx` | Lightweight Charts setup, log scale, crosshair, and the discipline of distinguishing genuine OHLC from reconstructed points | `shitcoims_sentinel/candles.py`; its DexScreener percentage-window path is not a live chart |
| `app/components/instrument.tsx`, `app/lib/measure.ts`, selected CSS/Radix primitives | compact observed/derived/stale/absent display grammar and visual shell | the old page hierarchy or implied strategy verdicts |
| list-freeze and target-stability logic in `app/views/explorer.tsx` | behavioral fixture for preventing reordering under a gesture | the 1,986-line component, `/hunch/*` coupling, `wiggle/up/down/watch` ontology, six-second feed as hot data, or paper position semantics |
| `shitcoims_pumpsocial/endpoints.py`, `client.py`, `models.py`, `crawl.py`, `probe.py` | dated, structurally read-only feasibility adapter; endpoint health tests; raw social/thread shape discovery | unsupported routes as a stable API, today's mutable creator as history, vendor model as canonical schema, peak/multiplier fields as inputs, or the browser-shipped key as proof of permission |
| `shitcoims_scalper/boards.py` and `firehose.py` | board/source comparison fixtures, manifests, explicit gaps, vendor-precision warnings | 30-second board polling as a crackle feed or a board-derived mechanical policy |
| `shitcoims_scalper/swarm_detect.py` | prospective exact-metadata/image/deployer family seeds, collision-null fixtures, and launch-source gap tests for a later territory strip | “three similar launches” as a buy signal, permanent family membership, or the old costly-signal story |
| `shitcoims_intelligence/kol_wallets.py`, `helius_live.py`, and account-trade support in `firehose.py` | explicit low-confidence profile-wallet claims, small read-only watch manifests, provider feasibility, and per-key health regression cases | profile wallet as verified trader, correlated wallets as one human, watched buy as copy authority, or global socket health as proof a quiet key is covered |
| `shitcoims_tape` validators and health tests | exact integer/unit checks, separate clocks, reserve capture, censoring/gap regression cases | the whole `TapeEvent` schema, observation-time event IDs, byte-equality dedupe, or the current rotate-only durability semantics as the new canonical store |
| `shitcoims_intelligence/pnl.py` | pure read-only lot and unknown-basis reconstruction fixture | FIFO as the operator's universal realized-PnL meaning, wallet-local accounting as the household ledger, or a quote as historical basis |
| `shitcoims_sentinel/lots.py` and basis reconstruction in `engine.py` | regression tests that flat inventory resets trail/basis state and unknown basis remains unknown | mint runtime state as episode identity, automatic protection policy, or an inactivity boundary |
| `shitcoims_paperdesk/hunch.py` and relevant tests | exact utterance, gesture/ingest clocks, append-before-readback, correction/retraction, and idempotency ideas | default confidence, fixed hunch kinds, one-entry/one-close position, or delayed board markouts |
| `shitcoims_lpexec` guard/signer/ledger tests | later adversarial fixtures for hostile SDK bytes, intended/simulated/actual divergence, and no-broadcast RPC | any present signer capability or the old planner's uniform one-sided policy |

### Adapt only after the first cockpit loop passes

- The existing React/Vite/Tailwind package manifest is a useful dependency baseline, but start a
  small new application shell rather than copying the old dashboard wholesale.
- The old `glass.py` and sentinel server can be mined for response fixtures and endpoint behavior;
  they should not become the new backend because their domain objects already encode the old policy.
- Old LP, execution, and study code belongs in regression fixtures and reference notebooks until a
  product use requires a fresh adapter.
- Prior study datasets may test parsers, disappearance semantics, and known bugs. They cannot stand
  in for prospective operator scenes.

## Dependencies that make apparently small slices dishonest

### A live chart is not merely a chart component

It requires an ordered event/account source, lifecycle and venue identity, gap semantics, honest
aggregation, and a defined migration boundary. Reusing the old reconstructed price path while
calling the result “high resolution” would invalidate the cockpit at its perceptual center.

### A profit hurdle is not merely a fee percentage

It requires exact contemplated size, current reserve/curve state, dynamic fee configuration,
venue, impact, account/network cost assumptions, quote time/slot, and actual inventory basis. Until
those exist, show unavailable rather than a plausible percentage.

### An exposure rail is not a wallet balance widget

It requires transfer/custody classification, basis quality, actual partial proceeds, pending or
external actions, exact residual quantity, and a fresh full-size liquidation quote. If history is
incomplete, the useful product is a quantity/value rail with a visible PnL gap—not synthetic basis.

### Replay cannot be added later

Choice set, viewport, render/product version, source watermarks, chart domain, quote, portfolio
state, and gesture time must be captured at the act. A screenshot alone loses semantics; structured
state alone will miss early visual variables. The first prospective gesture therefore needs both a
small scene manifest and an optional app-only perceptual checksum.

### A selected-coin workbench is not an attention-funnel instrument

If Ember first chooses the coin in Pump and only then pastes it into Joshi, the system may study
management, but it cannot estimate selection uplift or what the whole Pump surface contributed.
The product and every later report must name that boundary.

### External manual execution has a causal gap

Wallet observation can establish that a transaction happened. It cannot recover pointer-down,
intent time, the exact quote seen, rejected attempts, or why the action happened. A pre-action
gesture or reviewed companion capture closes part of this gap. Otherwise intent remains unknown.

### Social parity is more than post text

If images, author identity, thread/reply structure, community membership, ordering, and update
rhythm affect Ember's judgment, a sentiment string or post-count API is not parity. Raw social
content also creates retention, deletion, prompt-injection, and terms dependencies that must be
resolved before broad collection.

### “Whole market” has multiple costs

Compact program events may be affordable market-wide; verbose transactions, per-mint quotes,
screenshots, posts, replies, media, and identity enrichment are not one firehose. The census/hot
split is necessary, but it should be introduced source-by-source after measuring actual volume.

### Exact candidate order may not be observable

Pump rankings may be personalized, cached, session-dependent, or geographically variable. A
different public endpoint returning similar coins cannot be relabeled the list Ember saw. Either
capture the actual rendered surface under a reviewed companion design or define Joshi's own
surface and limit the estimand accordingly.

### Privacy and append-only evidence pull in opposite directions

Market evidence can be immutable while operator notes, screenshots, and interviews require a real
hard-erasure path. The first scene format needs separate retention classes; otherwise “build the
tape first” accumulates intimate data without a usable deletion boundary.

### A local read-only app still needs reliability

The first slice does not need distributed services, but it does need crash-visible persistence,
idempotent gestures, source gaps, raw observation retention, and deterministic enough replay. A
single SQLite database plus content-addressed raw files is plausible. A mutable “latest state” JSON
file with best-effort logging is not.

## Alternative plan if Pump social/feed parity is inaccessible

### Preferred fallback: an explicit Pump companion

If reviewed app-scoped user-side capture is permissible, keep Pump as the discovery renderer and
put Joshi beside it:

- an in-app browser integration or narrowly scoped browser companion records the actual rendered
  candidate IDs/order, viewport, selected mint, navigation, and app-only screenshot around a
  gesture;
- the local Joshi workbench adds the exact episode rail, wallet accounting, hot on-chain chart,
  executable quote/hurdle, annotations, and replay;
- exact-mint links return to Pump/Padre for manual execution;
- source fields that can be independently collected are archived; Pump-only rendered material is
  retained only under the reviewed policy;
- DOM/layout breakage opens a coverage gap instead of fabricating continuity.

This is not as clean as a replacement surface, but it can capture natural selection sooner and
avoid spending months cloning a volatile frontend. The product must make the boundary visible:
Pump supplied the candidate and some social context; Joshi supplied additional measurement and
management glass.

### Last fallback: define a new observable universe

If neither source parity nor companion capture is acceptable, build a clearly named on-chain-first
observatory:

- all Pump launches and lifecycle changes;
- one internally defined recent/activity board with reproducible ordering;
- public chain trade/reserve state and query-only quotes;
- read-only wallet activity for a deliberately curated set of followed Pump-associated wallets,
  with identity uncertainty shown;
- authorized social enrichments only where available;
- manual mint nomination and post-selection episode capture.

Under this mode:

- do not say “same or better Pump feed”;
- do not estimate the value of Ember's Pump selection funnel;
- study only Joshi-surfaced selection and post-selection management;
- treat coins discovered in Pump and pasted into Joshi as left-truncated operator nominations;
- compare whether Ember actually chooses to spend time in the new surface.

If Ember continues relying on inaccessible Pump-only social/community texture for most meaningful
selections, the honest decision is to keep Joshi as a management companion or pause the replacement
project. Building a large substitute dataset that omits the cues driving attention would recreate
the original error at product scale.

## Scope traps to reject during planning

1. **“Just define the universal event envelope first.”** Define the small invariant header and raw
   blob references needed by Slice 1; let real sources force the next fields.
2. **“Run every lane's pilot in parallel.”** The combined pilot is a platform. Run source probes in
   parallel only when they answer the selected loop's gate.
3. **“The backend can come first because the UI is easy.”** Natural use and scene capture are the
   experiment. A backend that arrives months before them accumulates the wrong denominator.
4. **“One feed is parity.”** It is parity only for the named workflow proved in the audit.
5. **“Paste mint” as the initial steady state.** Useful for exposure management, but insufficient
   for selection research; graduate quickly to one discovery surface or companion capture.
6. **“Shadow trading” before quote calibration.** A trigger plus a later mark is another paper desk.
7. **“Exact replay of every pixel.”** Preserve semantic scene state plus salient screenshots; do
   not build a browser emulator or continuous video archive.
8. **“General household accounting before any rail.”** Scope one wallet and three fixtures; widen
   only when transfers or obligations make the narrow boundary false.
9. **“Social graph before social pane.”** Render raw threads and identity evidence on attended
   coins first. Build graph breadth when a concrete transition/wallet question requires it.
10. **“Copy trading” as a wallet-watch requirement.** The watched trader has already moved the
    curve. Measure whether the event routes useful attention before asking whether any second-mover
    action survives latency, impact, fees, and Ember's selection.
11. **“Ecology” as one graph.** Narrative families, community movement, and coordinated trading
    fleets are different edge types. Begin with bounded territory queries around attended coins.
12. **“Buttons for the anticipated taxonomy.”** Stable acts first, provisional personal tokens
    later, automation vocabulary last.
13. **“LLM summary as immediate value.”** Early summaries can change the process before the raw
    process is measured. Start with offline/versioned interpretation and reveal it deliberately.
14. **“A signer seam means we may as well implement the signer.”** The current useful path ends at
    query-only quotes, manual external execution, and wallet reconciliation.

## The live-money boundary

No slice in this review requires Joshi to sign or submit. Manual trading through the tools Ember
already trusts is compatible with learning whether the cockpit is useful, provided the intent gap
is visible.

A later move from shadow observation to unsigned construction, signing laboratory, or tiny-live
execution should require a separate review and the monotone gates in lane 09. At minimum, the
one-surface cockpit must already be natural, episode/accounting replay must close, quote error must
be small relative to the intended edge, external actions must reconcile, and the strategy family
must have a declared loss envelope. Live execution is not the missing ingredient for discovering
whether the first cockpit surface deserves to exist.

## Recommended immediate decision

Authorize only Spike 0 and the design of Slice 1. Do not yet authorize a full collector stack or
cockpit implementation. The next engineering plan should begin from the operating mode selected by
the Pump surface test and should name the exact first discovery loop.

The decisive early milestone is:

> Ember uses one honest Joshi loop during real sessions, the product helps rather than clerks, and a
> later replay shows the same choice set, graph/social context, exposure, executable information,
> gesture, and uncertainty that actually existed.

Once that works, additional infrastructure is no longer abstract platform work: every extension
can be justified by a missing piece of a real episode.
