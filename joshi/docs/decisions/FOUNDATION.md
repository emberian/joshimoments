# Foundation decision

Status: accepted semantic foundation; pre-engineering; 2026-08-16.

## Decision

Proceed with `joshi`, but do not treat it as `joshibot` V2 in the ordinary rewrite sense.
It is a clean semantic boundary around a different object:

> a locally controlled, system-read-only market observatory and operator cockpit that can
> faithfully preserve Ember's selection, interpretation, execution context, episode management,
> social context, and external wallet consequences before attempting to learn or automate them.

`joshibot` remains a compost repository. Its results, fixtures, protocol knowledge, and selected
safety mechanisms may be re-derived or adapted. Its strategy laws, domain types, running state,
and architecture do not migrate by default.

The project is worth doing because the instrument and workstation can be useful before a trading
edge is established. It must also be capable of showing that any or all strategy families are
unprofitable. Proceeding is conditional on earning one natural, replayable cockpit loop; it is not
a commitment to build a universal platform or live bot.

## Semantic architecture

```text
untrusted public/authorized sources             local operator interaction
  chain · Pump surface · social · quotes          viewport · gesture · utterance
                    \                               /
                     v                             v
                 append-oriented evidence tape
          observations · blobs · coverage · operator records
                              |
                              v
                  versioned assertions/derivations
                 identity · market · social · accounting
                    /               |                \
                   v                v                 v
          witnessed replay   knowledge-cutoff   retrospective replay
                    \               |                /
                     +--------------+---------------+
                                    v
                         local cockpit and studies
              market surface · workbench · episode rail · replay

Future authority is a separate, later-reviewed graph:

operator capability -> planner -> unsigned bytes -> independent guard
                    -> isolated signer -> identical-byte submitter
                    -> chain reconciliation
```

No component in the current architecture constructs, signs, or submits a transaction. Ember may
trade manually through external tools; those are external live actions observed after the fact or
linked to a prior gesture where one exists.

## Canonical semantic spine

### Behavioral and financial identity

| Term | Meaning |
|---|---|
| **portfolio domain** | Versioned set of wallets, token accounts, vaults, LP positions, and custody locations included in consolidated accounting. |
| **financial ledger** | Exact asset-flow and balance projection over the portfolio domain, independent of episode labels or strategy stories. |
| **operator episode** | Stable continuity of attention and intent across zero or more inventory epochs. It may span full exit, flat watching, and re-entry. |
| **subject link** | Versioned link from an episode or hot scope to a mint, coin family, person, wallet, pool, LP position, or territory. Episode identity is not mint identity. |
| **inventory epoch** | Maximal flat-to-nonflat-to-flat accounting interval for one mint in the portfolio domain. Re-entry begins fresh basis without necessarily beginning a new episode. |
| **fill** | Reconciled asset effect of a landed economic action. It is not an intent, quote, submission, or provider response. |
| **acquisition lot** | Acquired units with exact provenance, basis quality, and remaining quantity. |
| **management tranche** | Optional, prospective allocation of fungible quantity to a book or playbook. It is attribution, not custody. |
| **clip** | Noncanonical operator-facing or analytical grouping whose rule must be declared. It is not a ledger primitive. |
| **book allocation** | Risk/reporting and authorization overlay on one consolidated balance sheet. Moving value between books creates no profit. |

An episode can follow a coin family across competing mints; accounting remains mint- and asset-keyed.
Only an operator resolution, explicit adjudication, or correction resolves an episode. Inactivity
may make it dormant, but cannot prove that attention or thesis ended.

### Operator meaning

Do not encode Ember's relationship to a coin in one disposition enum. Preserve five optional,
versioned axes:

| Axis | Question | Examples |
|---|---|---|
| **playbook / entry mode** | What observation or early-management behavior is armed? | crackle variant, immediate entry, social-transition watch |
| **stance** | What relationship to current exposure is intended? | retain, reduce-only, watch flat, undecided |
| **thesis** | Why might attention or exposure continue? | might send, community coalescing, graph-only, not articulable |
| **horizon / review condition** | Until when or what event? | minutes, creator action, next review, open-ended |
| **management act** | What is Ember doing now? | take some, exit, keep remainder, re-enter |

Raw gestures and exact utterances are permanent provenance. Personal labels are versioned
annotations that can be renamed, split, merged, deprecated, or contradicted without rewriting the
original act.

The stable semantic event core is smaller than the UI vocabulary:

- attention: `attention_marked`, `watch_started`, `watch_changed`, `watch_ended`;
- watcher: `playbook_armed`, `playbook_changed`, `playbook_cancelled`, `playbook_expired`;
- economic intent: `increase_requested`, `reduce_requested`, `exit_all_requested`,
  `reentry_requested`;
- meaning: `stance_asserted`, `thesis_asserted`;
- episode: `episode_resolved`, `episode_reopened`;
- research: `annotation_recorded`, `comparison_recorded`, `correction_recorded`.

Product macros expand into these records. For example, `PROFIT + RUNNER` is a reduction request
plus an assertion about the reconciled remainder; the inventory action must never wait for the
annotation. `ZAP` is an immediate full-exit request, not a claim that it filled or that the episode
ended.

### Evidence identity and time

| Term | Meaning |
|---|---|
| **observation** | One source acquisition attempt/result. It always has a unique observation ID, even when its bytes repeat. |
| **blob** | Exact retained bytes addressed by content hash. Several observations may refer to one blob. |
| **source object/event key** | Typed source-native candidate identity. Equal values at different chain indices remain distinct events. |
| **assertion** | Versioned typed claim decoded, reconciled, or inferred from observations. |
| **derivation** | Versioned computed/model output with exact input manifest and production time. |
| **coverage** | Scope, interval, source health, completeness claim, and explicit gaps. Collector silence is not market silence. |
| **evidence tape** | Logical append-oriented corpus of observations, operator records, assertions, derivations, scenes, retention events, and coverage—not one universal table. |
| **financial ledger** | Reconciled asset projection. It remains separate from evidence acquisition and episode attribution. |
| **journal** | Reserved for durability-critical future authority, reservation, signing, submission, and reconciliation records. |

Preserve source/event time, chain order and finality, request time, receive time, persistence time,
availability time, render/viewport time, operator gesture time, enrichment time, and execution
lifecycles as different clocks. No derived view may silently substitute one for another.

Identity, territory membership, social state, fee routing, and metadata are bitemporal: when a
relation is alleged to be true and when Joshi could know it are separate intervals.

Ordinary immutability means no in-place semantic rewriting. Retention and hard erasure are explicit
authorized events. A tombstone may preserve that content was erased, under which policy and when,
without preserving the content or allowing a derived cache to keep serving it.

### Choice context, scene, and replay

A choice context preserves distinct sets:

1. census eligible;
2. source surface membership and order;
3. client rendered;
4. viewport visible;
5. interacted with;
6. explicitly compared, shortlisted, ranked, or rejected.

None implies the next. Dwell and hover remain physical events, not claims of attention.

A **scene manifest** names the actual rendered state, choice context, chart viewport, raw-source
and projection watermarks, quote/portfolio observations, current episode meaning, product version,
gesture geometry, and optional app-only screenshot at a consequential moment.

Three replay products are required:

- **witnessed replay:** what the application actually rendered, including stale values, omissions,
  feature flags, and gaps;
- **knowledge-cutoff replay:** a named computation using only evidence available by a cutoff and
  named parser/model versions;
- **retrospective replay:** a later best account using finality, backfills, corrections, and known
  outcomes.

What the backend possessed and what Ember saw are not interchangeable.

### Hot observation

A runtime **hot scope** is a typed, manifest-driven increase in fidelity. Its subject can be a
mint, coin family, person/identity, wallet set, pool/LP position, territory, or small declared
composite. Activation, expansion, degradation, and closure are events.

The whole-market census remains compact. It supplies denominators, lifecycle, coarse flow, family
candidates, and routes into hot scopes. Expensive quotes, threads, media, screenshots, full
transactions, and operator context are collected for declared hot scopes and measured samples.

Hot observation may remain active while inventory is zero if the episode is watching for re-entry.

## Strategy and context boundaries

### Crackle, runner, and active episode management

Crackle is a watcher/entry and early-management family, not a complete position lifecycle. Initial
microdip definitions remain parallel hypotheses. A human-created `ARM SHADOW CRACKLE` starts a
bounded hot scope and shadow quote paths; it does not authorize money movement.

Partial realization, runner promotion, full exit, flat watching, and re-entry are compositional
episode acts. Evaluation compares complete paths at common terminal horizons with all friction,
remaining executable exposure, saved downside, forgone upside, and opportunity cost visible.

### Fancoin and social transition

Model a nonmonotone state vector over identity evidence, fee routing, public participation,
community structure, liquidity/capacity, and competing coins. Ordinary permissionless creator-fee
collection or distribution is not creator intent. A platform-authorized social fee claim is not
direct human signature, endorsement, or proof about one mint; mint attribution requires
point-in-time routing reconstruction.

### Territory/ecology

Ecology begins as a small query and display layer over typed launch/narrative, community, and
trading-fleet relations. These three ecologies never become one generic `related` edge. A territory
is overlapping, revisable, and uncertainty-bearing; it is not a permanent partition, canonical
winner, predictive score, or new subsystem.

Preserve the launch, identity, family, community, wallet, and migration facts now. Render a small
family strip only for attended or otherwise promoted scopes. A higher-order ecology layer earns
existence only if it reveals meaningful rivals, succession, fragmentation, or movement that coin-
local state misses.

### Followed accounts and wallets

A Pump follow, profile wallet, author wallet, direct signed trade wallet, funder, relayer, deployer,
fee recipient, and inferred controller are different typed relations. A directly decoded watched-
wallet action may route a mint plus territory into a hot scope. It is not an endorsement, proof of
skill, copy instruction, or privileged pre-trade signal.

The candidate event must show exact wallet/profile evidence, side/size/slot, receipt latency,
anonymous flow, current quote/capacity, competing coins, and source coverage. Ember's subsequent
inspection and arm are new selection acts. Alert once per mint/scene while preserving every wallet
event.

### LP inventory

An LP is custody plus a versioned schedule of contingent trades across bins. Preserve exact token
composition, fees, active/inactive range, and the fully traversed exposure surface. Distinguish:

- add inventory without changing the schedule's meaning;
- remove a bounded portion of bins/assets;
- rebalance or reweight existing custody;
- recenter through an actual swap or inventory conversion.

Swap authority defaults false. A book is not a pile of “LP money”; it is a risk and opportunity
overlay on consolidated assets. Capital may be removed because another opportunity is better
without claiming that removal restored the original SOL composition.

## Estimation and learning order

The target is a changing, partially observed sequential policy. Ember's attention is both a sensor
and a missing-not-at-random sampler. The honest progression is:

1. census and high-resolution attended hot scopes;
2. exact episode/portfolio and execution-quality reconstruction;
3. matched contemporaneous choice sets and stable shadow paths;
4. empirical distributions and multi-state/competing-risk descriptions;
5. analog retrieval linked to raw prior scenes;
6. multimodal representations and transition/ranking models with chronological evaluation;
7. counterexample-guided program synthesis from prospective partial specifications;
8. hybrid-system or circuit abduction for sensor design and equivalence classes of mechanisms.

Off-policy evaluation applies only to supported system-randomized actions with known conditional
propensities. A human explanation or deterministic choice does not create a valid propensity.

LLM outputs are untrusted, versioned annotations. They never overwrite sources, widen a hot scope,
change a portfolio limit, or gain execution capability. Historical LLM analysis may leak outcomes
through pretrained knowledge even when the prompt is cutoff-safe; label it interpretive unless
that channel is controlled.

## Build-versus-buy boundary

Reuse replaceable plumbing:

- official Pump, PumpSwap, Meteora, Solana, and wallet interfaces;
- RPC/WebSocket or measured Yellowstone-compatible transport;
- query-only Jupiter routes as a comparison/fallback;
- conventional transactional storage and columnar analytics;
- Lightweight Charts or another renderer;
- a small web application shell;
- later, independently benchmarked landing infrastructure.

Build and own meanings:

- source-neutral evidence envelopes and coverage;
- attention funnel and scene manifests;
- episodes, epochs, lots, optional tranches, external-action attribution, and accounting;
- evolving operator language and gestures;
- point-in-time identity, social transition, territory, and wallet evidence;
- exact quote artifacts and episode-level hurdle views;
- witnessed/knowledge-cutoff/retrospective replay;
- research registry, model provenance, and falsification gates.

No provider-enriched trade object, sentiment score, candle, identity claim, wallet label, or PnL
headline becomes canonical. Paid services must win measured source/provider comparisons.

The largest external uncertainty is lawful, stable access to the Pump discovery and social surface.
Until one exact loop passes a fidelity/access test, the product is a candidate companion or an
on-chain-first observatory—not a Pump replacement.

## Capability ladder and safety

Adopt the monotone R0–R8 ladder:

| Level | Capability |
|---|---|
| R0 | Design-only repository; no key, builder, signer, broadcast method, or secret. |
| R1 | Offline adversarial evidence and deterministic replay. |
| R2 | Live public/authorized read-only collectors with gaps and provenance. |
| R3 | Local cockpit, scenes, gestures, and external wallet reconciliation. |
| R4 | Query-only executable observations and shadow proposals. |
| R5 | Separately reviewed unsigned construction and hostile-byte simulation lab. |
| R6 | Separately authorized isolated signing lab with no broadcast. |
| R7 | Dedicated tiny, manually initiated live slice. |
| R8 | One-dimension-at-a-time bounded reactive automation. |

The current foundation authorizes design through R4 only; the pre-engineering plan further limits
immediate work to feasibility and slice design. Spot and LP authority take separate R5–R8 paths.

Every playbook arm names an effect ceiling:

```text
observe_only < shadow_propose < construct_unsigned < request_signature < execute_bounded
```

An upgrade cannot increase the ceiling of an existing arm. Future `capability_issued` is separate
from `playbook_armed` and must bind exact wallet, assets, venues, actions, amounts, limits, expiry,
nonce, plan/policy version, and scene.

Financial safety begins before transaction code. Household/date reserves, opportunity reserve,
maximum learning loss, current executable exposure, correlated territory/community exposure, and
unresolved reservations must be visible. Money originating as fees or prior wins is not risk-free.

## Formal-methods boundary

Formal and executable specifications are valuable for:

- exact integer asset conservation and portfolio reconciliation;
- episode/epoch independence and append-only attribution;
- observation identity, causal cutoffs, cursor atomicity, gaps, and replay determinism;
- quote freshness and state binding;
- authority monotonicity, durable reservations, no duplicate signing, identical-byte retry, and
  transaction-effect validation;
- separately, multi-step LP transformation postconditions.

Begin with property-based and state-machine tests. Apply model checking or proof where concurrency,
crash recovery, or monetary authority makes testing insufficient. Do not formalize the provisional
crackle taxonomy, market profitability, a stationary social circuit, or a learned policy before
the observational language exists.

## Product contract

The mature observational product has four continuously reachable contexts:

1. market surface;
2. coin/family workbench;
3. persistent episode and exposure rail, including watching-flat episodes;
4. replay and interview queue.

The first slice implements only the subset earned by the feasibility plan. Product acceptance is
behavioral: Ember naturally uses the loop, exits and re-entry are not obstructed, scene replay is
recognizable, source gaps are visible, and the product does not force the anticipated taxonomy.

## Decisions deliberately deferred

- the final count and names of dispositions and crackle types;
- automatic runner promotion, re-entry, averaging down, or episode resolution;
- a microdip definition, exit policy, scalar risk utility, or fixed evaluation horizon;
- an LP range, volatility kernel, or rebalancing policy;
- a universal market circuit, social score, model family, or autonomous strategy;
- a universal event enum or final physical schema;
- PostgreSQL versus SQLite, stream vendor, router, chart licence, frontend framework, desktop
  wrapper, or managed signer;
- full Pump parity, mobile parity, complex drawing tools, whole-X collection, continuous video, or
  ambient input capture;
- transaction construction, signing, submission, live capital experiments, or scaling.

These are deferred because real source behavior and operator use should decide them, not because
they are presumed unimportant.

## Superseded foundations

The following statements from `joshibot` are not design constraints:

- entry prediction is dead;
- callouts are never useful except as a fixed anti-signal;
- one position or lot is the policy lifecycle;
- one hunch button both states belief and opens a policy;
- a five-minute or any fixed hold clock represents Ember's management;
- `quality/scalp` is the canonical population split;
- expectations should compile into playbooks before ordinary acts are captured;
- C#/Lean/TypeScript or any other language boundary has already been selected;
- the old system should be hardened and ported as a whole.

The scoped negative results and strong safety/evidence fixtures remain in the compost map.

## Consequences

This decision narrows the immediate project while preserving its ambition. The work first produces
truthful scenes, exact accounting, and a natural cockpit. If successful, it creates the substrate
on which chart-shape learning, social-transition models, program synthesis, circuit abduction,
LP control, and bounded execution can be investigated without repeating the old projection error.

If Pump access or natural product use fails, the project may remain a useful management companion,
become an explicitly on-chain observatory, or stop. That is a valid result. The architecture is
designed so a failure of replacement or strategy profitability does not invalidate the ledger,
replay, or containment work that has independently earned value.
