# Routed liquidity lane 05 — Glass and operator surface

Status: **research/product design only; no execution authorization and no wire-contract freeze**.

Date: 2026-08-17.

## 1. Proposed answer

Programmable routed liquidity should appear in Glass as a **versioned contingent conversion edge
inside the same economic book as spot inventory**, not as a yield position and not as a detached
strategy bot.

The surface must let Ember answer, without doing clerical reconstruction:

1. What assets and pools can currently connect this inventory to the market?
2. In which direction, at which exact size, and under which observed state could this edge become
   economically relevant?
3. Which bins would convert which asset into which other asset?
4. What other routes compete with the owned edge for the same flow?
5. How much fee came from external flow versus Ember's own routed spot activity?
6. What inventory transformation, toxicity, loss-versus-rebalancing estimate, and opportunity cost
   accompanied those fees?
7. How much inventory is acceptable, how much capital is actually at risk, and which part remains
   liquid for the coupled spot book?
8. What did an actual exercise do, and what happened at several later markout horizons?
9. What would a precisely described but nonexistent “ghost edge” have done mechanically, and what
   remains unknowable because deploying it could have changed routing and other actors?
10. Which slow-edge, medium-schedule, and fast-spot policy declarations were in force, proposed,
    stale, contradicted, or awaiting review—and which separately registered slow/medium/fast
    repricing-latency scenario is the ghost analysis showing?

The answer is not a scalar “edge quality,” “pressure,” or “LP APY.” Glass should preserve the
vector:

```text
route feasibility and coverage
direction × size activation
exact contingent inventory conversion
gross external fees and self-routed fee transfers
protocol/creator/network/routing costs
inventory transformation and liquidation value
toxicity and LVR-like model diagnostics with assumptions
capital at risk and competing spot opportunity
exercise history and multi-horizon markouts
policy timescale, state, and operator interpretation
```

Presentation itself is a hypothesis. The graph, ladder, fee waterfall, or policy strip may improve
or impair decisions. Glass must record the exact presentation plan and subsequent exposure/gesture
events so usefulness can be evaluated without pretending that a layout is neutral.

## 2. Scope and non-claims

This lane designs an accessible read/record/replay surface. It does not define protocol math,
routing algorithms, transaction construction, wallet custody, signing, submission, or an automated
liquidity policy.

The surface must preserve these distinctions:

| displayed object | valid meaning | invalid shortcut |
| --- | --- | --- |
| route edge | a directionally typed venue/pool transition under a named state and profile | guaranteed future route or fill |
| protocol-active bin | the current protocol bin state | the router will use Ember's position |
| feasible quote | deterministic response to one admitted state, direction, size, and route plan | executable now or landed fill |
| observed route selection | a landed transaction used that route according to admitted evidence | the edge caused the transaction |
| fee accrual | an exact asset-denominated claim/effect | net income or alpha |
| toxicity/LVR-like diagnostic | a versioned outcome-conditioned estimate under a named reference and horizon | wallet morality, causal informed flow, accounting PnL, or exact loss |
| acceptable inventory | an operator declaration or policy input | current balance or authorization to trade |
| capital at risk | a scenario- and liquidation-route-conditioned vector | one timeless portfolio number |
| ghost edge | a counterfactual specification and model result | an event that would certainly have occurred |
| slow/medium/fast policy stack | three versioned operator control horizons | an autonomous controller |
| slow/medium/fast analysis scenario | registered arbitrage/repricing latency configuration | factual market speed or general policy quality |

The existing exact projection remains the source for landed accounting, balances, per-bin
inventory, fees, quote results/refusals, and modeled-only action consequences. Glass formats those
artifacts; it does not recompute financial truth with JavaScript numbers.

Provisional adapter names in this lane are `RoutedEdgeView`, `SharedInventoryView`,
`RoutePlanView`, and `PolicyStackView`. They summarize stable concepts for product discussion; they
are not a new wire contract.

This surface consumes, rather than redefines, the sibling research seams:

- [`02_VENUE_ROUTABILITY.md`](02_VENUE_ROUTABILITY.md) for venue rights, routability, route status,
  cost, account/ALT, and refusal semantics;
- [`03_GHOST_EDGE_EXPERIMENT.md`](03_GHOST_EDGE_EXPERIMENT.md) for `GhostRouteCut`, activation rows,
  sequential shadow inventory, registered repricing scenarios, and LVR-like diagnostics; and
- [`06_DYNAMICS_CAUSALITY.md`](06_DYNAMICS_CAUSALITY.md) for route/price objects, interference,
  causal non-claims, and the difference between canonical-chart calm and aggregate executable
  dynamics.

## 3. Operator object model

### 3.1 One balance sheet, two coupled books

The operator should see one consolidated asset ledger with two linked interpretations:

- **spot book:** liquid balances, spot episodes, runners, flat-watch/re-entry state, exact-size
  quotes, and competing uses of SOL;
- **routed-liquidity book:** assets currently held in positions, exact fee/reward claims, and the
  price/bin-conditioned conversion schedule exposed to routed flow.

Depositing into an edge changes custody and contingent conversion; it does not make the asset cease
to be portfolio exposure. Withdrawing changes custody; it does not liquidate the withdrawn token.
A spot action may traverse an owned edge. A route exercise may change inventory that the spot book
then manages. Both books therefore reference the same exact asset facts and inventory epochs.

### 3.2 Required identities

Every displayed row or mark should close to stable identities for:

- asset and token-program version;
- venue, protocol profile, pool, position, position version, and bin;
- route-plan occurrence and each directed hop;
- quote/simulation occurrence, exact input size, profile, state observations, and validity window;
- landed transaction/instruction/effect and route attribution quality;
- fee/reward claim and payer/flow attribution quality;
- accounting projection, episode, inventory epoch, and controlled account;
- edge lifecycle (`proposed | shadow | installed | paused | retiring | retired`), policy, policy
  version, assignment occurrence, time horizon, and declaration source;
- scene, view digest, presentation digest, and evidence cutoff; and
- estimator/build/config/input artifact for every derived or inferred measure.

Equal economic values do not merge distinct occurrences. A route plan quoted twice is two quote
occurrences. A later corrected pool observation does not rewrite the scene that used the earlier
one.

### 3.3 Four meanings of activation

Glass must never use an unlabeled “active” badge. At least four predicates coexist:

1. **Protocol active:** a bin or range is active under exact observed protocol state.
2. **Quote feasible:** an admitted calculator produced a successful size/direction-specific result
   for a named route and state; refusal remains a first-class result.
3. **Route selected:** a landed transaction is observed to have traversed the edge, with exact or
   bounded attribution.
4. **Counterfactually selected:** a simulator or model says a ghost/alternative edge would have
   been selected under explicit assumptions.

The first three may be observed or deterministically derived. The fourth is inferred. Router
product status remains more granular still:

```text
venue_native_quote != would_quote counterfactual != jupiter_candidate
                   != jupiter_routed != executed
```

A dormant owned position inside an otherwise indexed shared pool is also different from a whole
pool that fails Jupiter indexing or liquidity checks. Color, position, or the word “activation”
cannot collapse them.

## 4. Workspace and persistent safety strip

The routed-liquidity workspace is one continuous workbench, not nine unrelated dashboards.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Scene/mode · as-of clocks · source/quote health · NO EXECUTION AUTHORITY     │
├───────────────────────┬──────────────────────────────┬───────────────────────┤
│ Asset / pool graph    │ Selected evidence view       │ Coupled capital rail  │
│ route candidates      │ activation / ladder / plans │ liquid spot inventory │
│ owned + ghost edges   │ fees / markouts / policy    │ deployed inventory    │
│ coverage gaps         │ text/table always available │ acceptable bands      │
├───────────────────────┴──────────────────────────────┴───────────────────────┤
│ Timeline: route exercises · spot actions · LP edits · fees · policy changes │
├──────────────────────────────────────────────────────────────────────────────┤
│ Evidence gestures: mark · compare · propose · annotate · interview · replay │
└──────────────────────────────────────────────────────────────────────────────┘
```

The persistent safety strip cannot be hidden by presentation policy. It shows:

- immutable scene ID, replay mode, view/presentation receipt state, and catalog/chain cutoff;
- chart venue and feed scope;
- quote/route state age, finality, coverage, conflicts, and refusals;
- exact current asset inventory by custody class, with unknown/conflicting states visible;
- explicit `READ / RECORD / REPLAY ONLY` authority;
- a self-routed-fee warning whenever owned-edge and controlled-wallet route evidence overlap; and
- a presentation or event-capture gap whenever actual exposure is not fully witnessed.

## 5. The nine evidence views

Every view has a graphic form and a semantic table/text form. Observed, deterministic, operator
declared, estimated, counterfactual, missing, conflicting, and unsupported values use explicit
badges and text; they are never encoded by color alone.

### 5.1 Asset/pool route graph

The graph answers: **what can connect the held assets, through which protocol state, and which of
those edges do we own or merely observe?**

Nodes are canonical assets or, when necessary, custody states. Pool/venue transitions are directed
edges. One pool may yield two directional edges because size capacity, fees, transfer behavior,
route eligibility, and owned inventory differ by direction. A multi-hop route is a plan over edges,
not a new permanent edge.

Each edge exposes:

- venue/pool/profile and X/Y orientation in asset names, never only symbols;
- observed slot/time, source receipt time, state availability, finality, and coverage;
- owned position share/inventory where supported, separated from total pool state;
- active bin/range and whether the edge is protocol-active;
- quote sizes sampled, active capacity, net output, and success/refusal state;
- recent observed route-selection count and attribution quality;
- `venue_native_quote`, `would_quote`, `jupiter_candidate`, `jupiter_routed`, and `executed` as
  mutually non-promoting statuses;
- account count/ALT state, exact-out support, and typed abandonment/exclusion reason;
- current lifecycle and policy relationship: proposed, shadow, installed, paused, retiring, retired,
  watching, stale, or disputed; and
- expandable provenance and alternative/corrected observations.

Graph geometry is presentation, not evidence. Layout algorithm/version/seed and pinned coordinates
belong to the presentation artifact. The equivalent adjacency table sorts by source asset, target
asset, venue, pool, and edge ID. Keyboard traversal follows that semantic order, not whichever node
is visually nearest.

Selecting an edge never changes liquidity. It changes only the read context and may record an
explicit/dwell-qualified focus event.

### 5.2 Directional, size-specific activation surface

The activation surface answers: **at which tested sizes and states was this edge feasible,
selected, or estimated to compete?** It is not a heatmap of generic “pressure.”

Axes and cells are explicit:

```text
rows:    direction (A→B or B→A) × exact input-size bucket
columns: observed state/price/bin epoch or declared scenario
cell:    protocol-active | quote success/refusal | observed route share |
         counterfactual selection estimate, each on separate layers
```

A cell disclosure contains exact input/output units, route plan, fee components, deterministic
price impact, baseline and ghost net-output atoms, activation-margin atoms, active capacity,
ghost-flow/share ppm, maximum competitive fee premium, route-universe completeness, owned-edge
participation if known, quote window, support, uncertainty, and provenance.
Interpolation is forbidden unless a named estimator produced it. Untested cells say `not sampled`;
unsupported state says `unsupported`; no event says `observed zero` only when coverage proves it.

These rows are views over exact `GhostRouteCut` occurrences: pair, direction, input atoms,
point-in-time route state, schedule state, route policy, and coverage all close by identity/digest.
A surface never mixes cuts merely because they share a chart timestamp.

The accessible alternative is a pivot-like table with row/column headers, plus filters for
direction, size, state epoch, and evidence class. A text summary can state contrasts such as “quote
feasible at 0.1 SOL but refused at 1 SOL under this exact state”; it cannot recommend a size.

### 5.3 Exact bin inventory and conversion ladder

The ladder answers: **what asset is actually in each bin, and what contingent conversion would a
traversal imply?**

Each row names:

- signed bin ID, exact Q64.64 price or validated human rendering, and asset orientation;
- principal X and Y, accrued fee X/Y, and rewards separately;
- position share and unsupported fields without zero-filling;
- relation to active bin and whether it has already been traversed in the current state epoch;
- both traversal sentences, for example: “A→B traversal can convert up to Q A into B around P,”
  and the reverse if protocol semantics permit it;
- acceptable-inventory band relation and capital-risk contribution; and
- exact observation/evidence IDs and freshness.

The header also shows current inventory and the full-lower-bound/full-upper-bound inventory states.
A single-sided ladder is not a symmetric LP, and full range traversal can leave the position wholly
in one asset. Those consequences are stated in asset names before any “above/below” shorthand.

The ladder supports range focus and annotation in semantic coordinates: position ID, bin-ID
interval, asset direction, and scene. Pixel rectangles are never the evidence anchor.

The default condensed ladder may group adjacent equal-policy bins, but expanding it must reveal
every exact constituent row. Aggregation carries the method and proves unit-consistent sums from
the projection artifact. Glass itself does no asset arithmetic.

### 5.4 Competing route plans

This view compares plans for one precisely typed question:

```text
input asset + exact input atoms
desired output asset
state/knowledge cutoff
allowed venues/profiles
landing/simulation assumptions
objective being compared
```

Candidate columns include direct external route, route through an owned edge, multi-hop route,
remain in spot inventory, withdraw-only, and named ghost plan when available. Rows preserve:

- exact expected output or typed refusal;
- route observation kind (`venue_native_quote`, `would_quote`, `jupiter_candidate`,
  `jupiter_routed`, or `executed`) and no inferred promotion between kinds;
- Jupiter `/order` versus Metis `/build`, RFQ bypass, split share, exact-out support, account cap,
  ALT state, and account-exclusion reason when those artifacts exist;
- gross external LP fee, owned-LP fee rebate, consolidated household fee, protocol, creator,
  transfer, dynamic/priority, network/tip, and other supported components;
- rent by account, recoverable-on-close amount, and expected rebalance/harvest friction when the
  comparison actually includes lifecycle work;
- deterministic reserve/bin traversal and predicted post-plan inventory;
- route/state age, capacity, account/profile constraints, and coverage gaps;
- owned-fee attribution and the consolidated-portfolio treatment;
- simulation/model status and whether a result is purely mechanical or behavior-dependent; and
- opportunity/capital constraint compatibility.

“Best” is not a primitive field. A plan may dominate only under a named objective and constraint
set. Glass can sort on one exact component but keeps all vector components visible and records the
sort/filter in the presentation scene.

### 5.5 Fees versus toxicity and loss-versus-rebalancing

The fee/toxicity view answers: **what was earned, what inventory changed, and what subsequent
outcome-conditioned costs are estimated?**

Use a component waterfall and aligned horizon table:

```text
external gross fee accrual by asset
self-routed fee transfer by asset (consolidated separately)
protocol / creator / transfer / network costs
landed inventory transformation
withdrawal + per-leg liquidation value at named routes
multi-horizon markouts
toxicity estimate under named response/reference definition
LVR-like model diagnostic under named reference/rebalancing scenario
uncertainty, support, coverage, and unmodeled components
```

Toxicity is an outcome-conditioned provider-risk measure, not a label for a wallet or community.
The UI label is `LVR-like model diagnostic`, not bare `LVR`. It is not an observed ledger effect
or accounting PnL. It is a scenario-dependent difference against one registered continuous-
rebalancing reference. It depends on a reference price process, observation
frequency, rebalancing benchmark, fee treatment, route choice, and coverage. Glass must show those
assumptions beside the estimate and allow `not estimated`.

Fee accrual and economic performance are never combined into a client-computed net number. A net
result may be displayed only from an admitted accounting/analysis artifact whose units, evidence,
cutoff, and definition close exactly.

### 5.6 Acceptable inventory and capital at risk

This view places **actual**, **contingent**, **declared acceptable**, and **scenario-risk** values
side by side:

| layer | example | authority |
| --- | --- | --- |
| current custody | liquid SOL, token in wallet, X/Y principal in each position | exact projection |
| contingent conversion | per-bin inventory after a named traversal/state scenario | deterministic modeled result |
| acceptable inventory | “do not convert more than this SOL in this horizon” | operator declaration |
| policy proposal | target band and review rule generated by a named policy | proposal/analysis only |
| capital at risk | liquidation and stress vector under named routes/scenarios | exact or estimated artifact |

The rail must keep the coupled spot opportunity visible: liquid SOL available for other nominated
coins, SOL contingently offered by edges, unrecovered episode basis, runner budget, and unknown or
unrouteable residuals. It must not double-count a unit held in an LP position and again as free spot
inventory.

The `SharedInventoryView` groups each mint by custody (`wallet | LP | unsettled`) while preserving
one consolidated quantity. It shows current and contingent quantity, executable-liquidation state,
the acceptable-inventory set and headroom, reserves, and capital/rebalance/authority budget
consumption. Strategy books are attribution overlays, never separate balances.

Capital at risk is a vector, not a gauge:

- currently deployed atoms by asset;
- maximum additional conversion under the declared traversal region;
- full-withdrawal asset basket;
- exact-size per-leg liquidation proceeds or refusals;
- downside/stress scenario definitions and estimates;
- time to withdraw/redeploy assumptions;
- correlation/common-route and source gaps; and
- SOL reserved for competing spot opportunities.

Editing an acceptable band records a declaration. It does not remove bins, rebalance, hedge, or
create a transaction intent.

### 5.7 Recent exercises and markouts

An **exercise** is a landed route traversal that consumed liquidity on the edge according to
admitted transaction/pool evidence. The word is a useful analogy, not an options-law claim.

The chronological table includes:

- requested route occurrence, selected route occurrence, and landed execution occurrence as
  separate identities;
- landed signature/instruction/slot/finality and route-attribution status;
- direction, exact size, traversed bins, asset effects, and owned share if known;
- external, controlled-wallet, mixed, or unresolved flow attribution;
- accrued fee components and the later claim status;
- immediate deterministic inventory transformation;
- pre-event quote/state and decision-to-land shortfall when available;
- markouts at fixed event/wall horizons, each with venue/reference price object and coverage;
- markout `knownAt`, censoring, terminal status, and signed executable-reference unit;
- competing events, lifecycle/topology changes, and censoring; and
- links to contemporaneous operator scene, policy version, and annotations.

Chart marks appear only on a chart whose feed includes that venue or are shown on a separate route
track. A Pump chart, pool-local trade chart, aggregate provider chart, and executable route quote
are different price objects.

### 5.8 Counterfactual ghost edge

A ghost edge is a versioned, nondeployed schedule specification used to ask whether a different
placement might have been useful. Its visual grammar is dashed/patterned and always says
`COUNTERFACTUAL — NOT DEPLOYED` in text.

The `GhostRouteCut` specification includes pair, direction, exact input atoms, point-in-time route
state cut, position-like schedule state, route policy, capital budget, creation/expiry cutoff, fee
assumptions, coverage, source artifact closure, and proposal author. It has no position account and
cannot be mistaken for custody.

Two results must remain separate:

1. **Mechanical replay:** apply the fixed observed pool/flow path to the ghost schedule, explicitly
   assuming the edge would not change routing, prices, or other actors.
2. **Behavioral counterfactual:** estimate routing selection and market adaptation under a named
   model with support, uncertainty, and interference assumptions.

The first is useful bookkeeping under a false-world invariance assumption. The second is a harder
inference problem. Neither is “missed fees.” If the edge would have been large enough to change
route choice or pool state, fixed-path replay must carry an interference warning or refuse.

Ghost-edge comparison always retains the actual no-edge/deployed-edge branch, capital opportunity
cost, and exact knowledge cutoff. It never retrofits parameters after seeing the outcome without
labeling the result retrospective.

### 5.9 Slow, medium, and fast policy and scenario state

Two similarly named concepts must remain visibly separate.

The **operator policy stack** has three control horizons, not hard-coded durations:

- **slow edge policy:** total capital allocation, acceptable asset inventory, thesis/episode
  relationship, venue eligibility, reserve budget, and review/expiry conditions;
- **medium schedule policy:** edge schedule, range/bin weights, size activation region,
  rebalance/remove proposal, and opportunity comparison;
- **fast spot/hedge/crackle policy:** observed exercise response, quote/route freshness,
  inventory-band crossing, spot-book reaction proposal, temporary watch/pause declaration, and
  urgent review.

Each lane shows a versioned state card:

```text
policy + version + assignment occurrence
horizon label and clock basis
operator-declared | deterministic proposal | model proposal
state: monitoring | candidate_change | review_due | stale | refused | superseded
trigger evidence and unresolved gaps
proposed consequence in exact assets
last operator acknowledgement / disagreement / annotation
NO AUTOMATIC EFFECT
```

Fast does not mean authorized, and slow does not mean safe. A fast warning can request attention;
it cannot remove liquidity. A slow capital declaration can constrain later planning only after an
independent policy/admission layer recognizes it.

The **ghost analysis scenario strip** instead compares registered arbitrage/repricing latency
configurations over an identical fixed demand sequence. `slow`, `medium`, and `fast` there are
scenario labels backed by exact configuration IDs, latency/order rules, and state-update policy.
They are not factual market-speed labels and do not rank the operator policies above. The view shows
their sequential pre/post inventory, route share, fees by asset, organic versus arbitrage
transfers, depletion/rejection, terminal executable liquidation, and ordering-sensitivity interval
side by side. Incomplete route universe, source coverage, repricing/order scenario range, and
sampling interval remain separate uncertainty components.

## 6. Witnessed, as-known, and retrospective contracts

This design reuses the current Glass separation conceptually; it does not mutate the existing
`joshi.glass.view` contract or freeze a routed-liquidity schema in this document.

### 6.1 One truth mode per immutable view

A routed-liquidity view is a separately versioned sibling artifact bound to:

- one `mode = witnessed | knowledge_cutoff | retrospective`;
- immutable scene ID and, for recomputation, witnessed basis scene ID;
- full as-of vector: catalog commit, scoped delivered cursors/watermarks, chain slot/finality,
  projection/estimator versions and digests, and render time;
- exact routed-liquidity, quote, accounting, and analysis artifact IDs/digests;
- complete coverage/gap/conflict/refusal state; and
- exact canonical bytes plus receiver-derived digest.

`witnessed` serves the exact stored DTO bytes used at the decision. `knowledge_cutoff` is a
separately generated DTO containing only evidence available at its declared cutoff.
`retrospective` is another separately generated DTO that may include later fills, corrections,
markouts, interviews, and outcomes. The browser never filters one mixed DTO to manufacture an
earlier state.

Later markouts, later route selection, corrected transaction canonicality, future fee claims, and
the knowledge that a ghost edge would look attractive cannot inhabit the witnessed payload.

### 6.2 Presentation scene is planned; events are empirical

Reuse the repaired presentation model conceptually:

- exact versioned presentation policy;
- mandatory operator-selected assignment occurrence;
- exact exploration/routed-liquidity artifact closure;
- immutable presentation scene containing eligible items, selected items, planned render items,
  placement/order/salience, filters/toggles, omissions, comparisons, and no fabricated initial
  focus;
- receipt-before-reveal for a witnessed-complete surface; and
- append-only post-mount visibility, real DOM focus, control, and usefulness events.

The pre-reveal scene is a staged prescription, not proof that pixels rendered or that Ember looked.
Visibility events prove only component lifecycle exposure, not viewport fraction or gaze. If
admission or event receipt fails, rich safety information remains visible with an explicit
`presentation not witnessed` or `exposure capture incomplete` gap.

Safety-critical inventory, quote freshness/refusal, source health, chart scope, self-route warning,
and authority ceiling cannot be omitted by a policy hypothesis.

### 6.3 Operator decision scene

A decision scene binds, by ID and digest:

- routed-liquidity view and full as-of vector;
- presentation scene/receipt and actual exposure events available then;
- exact served/eligible route, edge, size, policy, and spot-opportunity choice sets;
- selected edge/bin/route-plan semantic coordinates;
- current accounting/LP projection and unresolved gaps;
- open spot episodes, reserved SOL, and contemporaneous alternatives;
- chart feed/venue/time bounds and enabled overlays;
- operator command/annotation occurrence and clocks; and
- later execution/effect only by a separate forward link.

No later fill or outcome rewrites the decision scene.

## 7. Semantic gestures and no-authority controls

### 7.1 Gesture vocabulary

Current controls use record/propose/request language:

| gesture | evidence meaning | explicit non-effect |
| --- | --- | --- |
| `focus edge` | deliberate research focus on a semantic edge ID | does not select a route for execution |
| `compare route plans` | records exact plan choice set and comparison members | does not choose or submit a swap |
| `mark bin range` | anchors a region to position/bin IDs and direction | does not add/remove/rebalance bins |
| `record acceptable inventory` | operator declaration with asset, band, and horizon | does not enforce or trade the band |
| `nominate ghost edge` | creates a counterfactual proposal artifact | does not create a position |
| `record route preference` | captures contemporaneous preference and why-now | does not authorize routing |
| `request policy review` | requests attention to a named policy-stack declaration | does not run a policy transition |
| `annotate exercise` | links an utterance/label to a landed exercise | does not classify it as toxic fact |
| `continue watching` | keeps an edge/episode in attention | does not keep capital deployed |
| `compensate record` | appends a semantic correction citing a prior event | never deletes history |

Every command binds scene ID, view digest, presentation ID/digest, subject, exact payload, client
session/sequence, wall and safe monotonic clocks, idempotency key, literal
`authorityClass = evidence_only`, and `effectCeiling = observe_only`. The UI waits for the matching
durable receipt before showing a mark as committed. Offline retries resend exact bytes; changed
same-ID bodies conflict.

No control accepts signer, transaction, quantity-to-submit, slippage bound, fee bid, tip, or
provider credential. A quantity may appear only as evidence annotation, acceptable band, scenario,
or ghost-plan input under a typed non-effect contract.

### 7.2 Keyboard map

The map is semantic and remappable. Shortcuts do not depend on visual position:

| shortcut | action |
| --- | --- |
| `/` | search asset, pool, position, route plan, or evidence ID |
| `G` | focus route graph |
| `A` | open activation surface |
| `B` | open exact bin ladder |
| `C` | compare route plans |
| `F` | open fees/toxicity/LVR-like diagnostic components |
| `I` | open inventory and capital-at-risk rail |
| `E` | open recent exercises/markouts |
| `X` | open ghost-edge notebook |
| `P` | open policy stack and separate repricing-scenario strip |
| `J` / `K` | next/previous semantic row within the active view |
| `Shift+J` / `Shift+K` | next/previous evidence epoch |
| `Enter` | inspect selected row without recording a disposition |
| `M` | open mark/annotation dialog for the selected semantic object |
| `?` | shortcut help and current authority explanation |

Potentially time-sensitive commands remain one-step to open and one explicit step to record. Notes
are optional. Focus is visible, and focus does not move because a live route rank changes.

### 7.3 Voice-ready hooks

Voice phrases map to the same semantic intents, for example:

- “compare this edge with the direct route at point one SOL”;
- “mark these bins as more SOL than I want to convert”;
- “keep watching this edge while flat”;
- “ghost this schedule for the medium schedule horizon”;
- “why now: external flow looks real but coverage is partial”; and
- “request a fast-policy review; do not change anything.”

The hook records an intent proposal and, only with explicit consent, the utterance or transcript.
It never grants microphone access ambiently, guesses a mint/size silently, or turns speech into an
economic effect. Ambiguity opens a semantic disambiguation list; cancel is always available.

## 8. Chart/feed scope and self-routed-fee warnings

### 8.1 Chart/feed scope

Every chart carries a persistent scope sentence:

> Pool-local PumpSwap trades through slot S; does not include Meteora, aggregator-private route
> plans, failed transactions, or unobserved provider intervals.

or its exact equivalent. The chart header names venue/pool, price object, event versus wall clock,
aggregation method, finality, availability cutoff, source health, and gaps.

Cross-venue marks use separate tracks. A route quote may be overlaid only with a distinct glyph and
text label because it is not a trade. An exercise on another venue never appears as if it occurred
on the local candle series. Sparse samples are not drawn as continuous truth without an explicit
sampling grammar.

If the current chart feed cannot observe the route that generated a fee or exercise, Glass says
`route outside chart scope`; it does not infer a matching candle move.

### 8.2 Self-routed fees

Whenever a controlled-wallet spot action may have traversed an owned edge, show:

> **Possible self-routed fee.** Gross LP accrual may include a transfer from Ember's own routed
> trade. Consolidated performance must not count that portion as external fee income.

The row distinguishes `external`, `controlled_wallet`, `mixed`, `unresolved`, and `unsupported`
attribution, with evidence quality. Exact owned-share accrual may still be uncertain because the
route or LP share decomposition is incomplete.

For consolidated economics:

- the self-paid portion received by the owned LP is an internal transfer, not new wealth;
- protocol, creator, transfer, network, priority, tip, and externally owned LP fees remain costs;
- deterministic price impact and subsequent inventory/markout remain economic effects; and
- another controlled wallet or token account does not make the event external.

Glass displays the admitted accounting result or an unresolved warning. It does not cancel these
components itself.

### 8.3 Protocol and ownership warnings

The following warnings are predicate-driven, readable in text, and non-hideable when active:

- **pair orientation:** X/Y inversion can reverse which asset the position offers; always name
  both exact mints and the trader/LP direction;
- **single-sided schedule:** a one-sided bid/ask ladder is not symmetric liquidity;
- **terminal inventory:** full traversal can leave the position entirely in one asset;
- **path-dependent provider exposure:** an in-range LP is locally short convexity relative to
  holding and receives fees as compensation; it is not a bond or passive yield account;
- **withdrawal is not sale:** removing/closing returns an asset basket unless a separately named
  swap occurs;
- **rebalance is not swap:** any modeled or protocol operation that changes the asset basket must
  itemize the actual transformation rather than hide it in the word “rebalance”;
- **mark is not liquidation:** a marginal/current chart price is not a size-specific withdrawal and
  per-leg liquidation result;
- **pool/position dormancy:** an inactive owned range in a routed shared pool differs from a whole
  pool failing router discovery/liquidity checks; and
- **authority identities:** pool initializer, LP-position owner, fee owner, config/operator
  authority, protocol owner, and token creator are separately shown and never inferred equal.

## 9. Decisions, quick reports, and interviews

### 9.1 Before and immediately after a gesture

The system automatically captures the decision scene. A low-friction report may add:

- intended horizon: fast, medium, slow, or open text;
- confidence/urgency as optional operator observations, never defaulted;
- why-now chips: route competition, inventory discomfort, external-flow evidence, fee opportunity,
  spot opportunity, source gap, chart pattern, policy review, or open text;
- acceptable asset direction: willing/unwilling/uncertain to convert A into B;
- comparison actually considered; and
- `cannot articulate yet`.

Nothing blocks inspection or a separately authorized action path. If a later system actually
constructs or lands an economic effect, it links that occurrence forward after reconciliation.
This Glass never says “executed,” “earned,” or “protected” from a gesture alone.

### 9.2 Later interview

Replay first reconstructs the witnessed scene with later outcomes hidden. Questions should be
specific and optional:

- Which edge relationship mattered: availability, likely route selection, inventory conversion,
  fee capture, or avoidance?
- Which asset were you unwilling to sell or accumulate?
- What made this fast/medium/slow rather than another horizon?
- What competing spot opportunity was live?
- Was the graph, activation surface, ladder, or fee view actually useful?
- What was missing, misleading, too dense, or too slow?
- Did you intend to change the schedule, reduce capital, remain flat, or only learn?

Only after the contemporaneous account is stored does replay reveal landed effects, later
markouts, counterfactuals, and accounting outcomes. The later interview remains a separate
retrospective annotation and may revise a label without rewriting the original utterance.

## 10. Replay and comparison grammar

Supported comparisons include:

- exact witnessed presentation versus a separately generated as-known presentation at another
  declared cutoff;
- witnessed versus retrospective, separated by a visible outcome reveal boundary;
- graph-first versus ladder-first or fee-first presentation policies on the same evidence cut;
- deployed edge versus no-edge branch;
- deployed edge versus a prospectively frozen ghost edge;
- slow-edge/medium-schedule/fast-spot policy versions at a shared cutoff;
- registered slow/medium/fast repricing scenarios over one identical fixed-demand sequence;
- direct route versus owned-edge and multi-hop plans for the same exact size; and
- action-linked scene versus a contemporaneous inaction/alternative scene when both were eligible.

Side-by-side panels share semantic cursors only when units, asset orientation, time basis, and
scene cut are compatible. Otherwise the link refuses and explains why. Outcome overlays are never
silently synchronized into a witnessed panel.

Counterfactual comparison reports three layers separately:

1. exact historical fact;
2. deterministic mechanical calculation under a fixed observed path; and
3. behavioral/model estimate with uncertainty and interference limits.

## 11. Presentation hypotheses and usefulness capture

No presentation policy is promoted as “the right dashboard.” Candidate hypotheses include:

| policy hypothesis | intended benefit | plausible harm/falsifier |
| --- | --- | --- |
| graph first | improves route/asset orientation and competing-plan awareness | adds navigation cost or hides exact bins |
| ladder first | reduces accidental unwanted inventory conversion | tunnel vision on one position or slower opportunity recognition |
| fee components beside markouts | reduces fee-chasing and self-route double counting | creates outcome anchoring or excessive caution |
| capital rail always visible | reduces unwanted SOL conversion and double allocation | consumes attention without changing decisions |
| activation surface by exact size | improves size-conditioned reasoning | heatmap salience suggests unsupported interpolation |
| ghost edge beside actual | improves prospective schedule design | encourages hindsight optimization or false-path certainty |
| three-horizon operator policy strip | makes edge/schedule/spot timescale conflicts explicit | adds ontology burden without better actions |
| registered repricing-scenario strip | exposes inventory and ordering sensitivity | looks like factual market speed or invites favorable-scenario selection |
| coupled spot opportunity panel | improves capital allocation across LP and spot | increases overtrading or regret from constant alternatives |

Policies are manually selected and versioned. There is no automatic live randomization and no
policy may hide safety-critical truth. Offline/replay comparisons may be randomized only under a
separate research protocol that cannot affect live exposure.

Usefulness evidence should include:

- operator usefulness report and free text;
- decision latency from witnessed event clocks;
- attention cost: navigation/control count and qualified focus intervals, not gaze claims;
- orientation/route-attribution corrections;
- inventory-band revisions and whether unwanted conversion was later reported;
- over-management/overtrading from reconciled episode/position analysis;
- regret and missed opportunity as retrospective operator/choice-set analyses;
- error/refusal rate and time spent resolving source gaps;
- PnL only by digest link to a reconciled accounting projection; and
- whether the operator abandoned the surface for another tool, with reason if voluntarily given.

Every outcome names its authority and time of availability. A favorable PnL does not prove the
presentation caused it. A fast click does not prove low cognitive load.

## 12. Responsive and accessibility behavior

### 12.1 Desktop

The three-column workspace may show graph, selected view, and capital rail concurrently. Panels
resize, but safety information and semantic text do not disappear below a pixel threshold. Route
updates may refresh values without moving the focused row; reorder waits until explicit acceptance
while a row is focused, inspected, annotated, or compared.

### 12.2 Narrow/mobile

Below the wide layout, the workbench becomes an ordered stack:

1. safety/as-of/authority strip;
2. coupled inventory and capital rail;
3. selected edge identity and primary evidence view;
4. alternate views and provenance;
5. exercise timeline and interview queue.

A sticky semantic view switcher exposes all nine views without horizontal precision scrolling.
Critical stale/conflict/refusal and self-route warnings remain expanded. Collapsed sections expose
their status, count, and warning summary in the accessible name. Opening a disclosure does not
discard the selected edge or scene.

### 12.3 Interaction requirements

- all targets at least 44×44 CSS pixels without precision dragging;
- full keyboard use, skip links, landmarks, deterministic focus order, and visible focus;
- graph, heatmap, ladder, and waterfall each have equivalent semantic tables and summaries;
- row/column headers and units announced for matrix cells;
- no hover-only evidence; pointer hover is never recorded as deliberate focus;
- no color-only direction, evidence class, profitability, state, or warning;
- patterns/shapes plus text for owned, external, ghost, stale, and uncertain edges;
- zoom and 200% text do not obscure safety controls or cause two-dimensional page scrolling;
- reduced-motion disables animated route flow, graph motion, and chart transitions;
- live regions announce receipts/gaps without narrating every market tick;
- virtualized tables preserve semantic row counts, selection, and screen-reader navigation; and
- raw IDs, exact atoms, and provenance are copyable without requiring a pointer.

Animation may illustrate a replayed route only on operator request. It is decorative and
`aria-hidden`; the step table is authoritative.

## 13. Progressive disclosure without information removal

The default surface prioritizes the selected edge, coupled inventory, freshness/refusals, and
current policy conflict. Density controls change how much explanatory text is expanded, not which
evidence exists.

Three levels are available everywhere:

1. **scan:** identity, direction, size/state, status, freshness, and warning;
2. **inspect:** vector components, exact assets, route/bin detail, uncertainty, and alternatives;
3. **audit:** source artifacts, observations, formulas/calculator version, canonical IDs/digests,
   corrections, coverage, and receipt closure.

An item omitted by a presentation hypothesis remains named with a typed omission reason in the
presentation manifest. Safety-critical items cannot be omitted. Search and command palette can
reach every eligible item even when it is not in the initial plan.

## 14. Smallest honest vertical slice

The first slice should be a replay-only comparison over one fixture-backed asset pair, one owned
DLMM position, one external competing route, and one prospectively frozen ghost schedule:

1. serve an immutable witnessed routed-liquidity artifact with exact per-bin inventory, one
   size/direction quote set, source health, and the coupled finalized portfolio projection;
2. stage and receipt one presentation policy before reveal;
3. render route adjacency table/graph, exact bin ladder, competing route table, capital rail, and
   recent exercise table with text equivalents;
4. record one acceptable-inventory declaration and one ghost-edge nomination as durable
   evidence-only commands;
5. append post-mount visibility and real focus/control events in order;
6. replay the witnessed scene with outcomes hidden, then load a distinct retrospective artifact
   containing markouts and reconciled accounting links; and
7. capture one usefulness report without a client-entered PnL value.

The slice is useful even if the graph adds no value: it leaves an exact inventory/conversion and
route-comparison notebook.

Do not include live transaction buttons, wallet connection, signer handoff, simulated-as-landed
language, route auto-selection, dynamic rebalancing, or a scalar optimization score.

## 15. Promotion and authority gates

Current Glass stops at read, record, replay, and proposal. Any future effect path needs separately
reviewed capabilities:

```text
evidence gesture
  -> durable receipt
  -> independently versioned plan proposal
  -> exact protocol/account-state admission
  -> independent simulation and economic postcondition verification
  -> explicit operator review of exact effects and refusals
  -> isolated signer capability
  -> submission/landing/finality reconciliation
```

No earlier receipt implies a later capability. A `request_policy_review` event is not an approved
plan. A plan is not a transaction. A successful simulation is not a fill. Signing is not landing.
Landing is not final accounting.

Before an execution surface is even designed, the project must demonstrate:

- exact protocol-profile and per-bin postcondition verification;
- route-plan/state freshness and account-closure checks;
- no hidden swaps inside add/remove/rebalance semantics;
- explicit controlled-wallet and self-routed-fee accounting;
- bounded slippage/fees/tips and independent transaction inspection;
- idempotent intent, simulation, signing, submission, landing, and reconciliation identities;
- fail-closed behavior under source gaps, drift, mismatch, expiry, or partial transactions; and
- capability separation that prevents Glass/data/analysis processes from signing.

## 16. Failure modes and falsifiers

The design should be revised or reduced if:

- graph navigation is slower or more error-prone than an adjacency table;
- activation heatmaps cause Ember to infer continuity or “pressure” from sparse cells;
- exact ladder semantics remain too difficult to verify against protocol effects;
- self-routed fees cannot be attributed well enough to prevent misleading gross-fee displays;
- route/chart coverage is too incomplete to support exercise markouts at the intended horizon;
- fixed-path ghost replay is materially affected by routing interference at realistic sizes;
- policy-horizon capture becomes clerical or forces distinctions Ember does not experience;
- persistent capital/opportunity context increases over-management more than it prevents unwanted
  conversion;
- presentation instrumentation materially slows urgent inspection; or
- the witnessed scene cannot prove the exact data and staged presentation shown before a gesture.

In those cases, retain the exact per-bin inventory, custody/accounting truth, route-plan notebook,
and evidence scenes. Drop the predictive or policy claims. The residue is still a valuable personal
instrument for understanding how spot exposure and routed liquidity interact.

## 17. Dependencies and unresolved questions

This lane depends on other work to define—not merely name—the following:

- exact directed route/plan/quote and landed route-attribution artifacts;
- protocol-native DLMM bin inventory, traversal, fees, add/remove/rebalance, and refusal semantics;
- consolidated accounting with controlled-wallet/self-route classification;
- chart/trade feed scope and route coverage evidence;
- toxicity, LVR-like, capital-risk, markout, ghost-edge, and interference estimators;
- policy declaration/version/supersession contracts across three horizons;
- scene-bound route/edge/size choice sets;
- presentation and operator admission endpoints; and
- a later isolated execution authority architecture, if it is ever justified.

Questions to carry forward:

1. Is “edge exercise” understandable to Ember, or should the product say “route used this
   liquidity” while retaining `exercise` only as an analytical term?
2. Which reference-price objects make an LVR-like diagnostic interpretable across PumpSwap,
   Meteora, and aggregator routes without inventing one global fair price?
3. Can route attribution distinguish controlled-wallet self-flow from external flow when an
   aggregator splits and recombines paths?
4. Which size grid is economically meaningful without allowing the presentation to choose a
   flattering surface after the fact?
5. How should a ghost edge refuse fixed-path replay when its hypothetical capacity would plausibly
   alter route selection?
6. Are slow-edge/medium-schedule/fast-spot truly Ember's natural policy horizons, or merely an
   engineering proposal, and are `slow/medium/fast` repricing scenarios legible without conflation?
7. What is the least intrusive way to preserve the competing spot opportunity set at an LP
   decision?
8. Which safety warnings must remain persistent versus announced only when their predicate is
   active?

These are study questions, not reasons to compress the surface prematurely.
