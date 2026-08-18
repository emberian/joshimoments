# Book-to-Joshi traceability audit

Status: repository audit, 2026-08-17. Read-only findings; no execution authority.

## Executive finding

The Bouchaud–Bonart–Donier–Gould corpus has been **applied to Joshi's epistemic and
numerical foundations**, but it has **not yet been applied as the empirical program described in
`JOSHI_BEACON`**.

The influence is real. Joshi now has exact atomic protocol arithmetic, distinctions among mark,
size quote, whole-position quote, and landed effect; multiple clocks and point-in-time joins;
coverage and gaps; response labels that refuse causal overclaim; exact lots and inventory epochs;
and a presentation system that treats the operator's information surface as evidence. Those are
not cosmetic similarities. They are the book's most important constraints on asking a well-posed
question.

But the repository has not produced a signature plot, a prospective signed-flow baseline, an AMM
response atlas with deterministic curve motion separated, a propagator/HDIM comparison, a real
social intensity study, a prospective LP provider-economics docket, or a prospective corpus of
crackle/runner/re-entry episodes. The one root walking path proves companion evidence, durable
storage, an immutable Glass scene, an operator command, and replay; it does not walk a venue state
through quote/fill/liquidation calibration and then through any Book study. The current response,
field, wallet, attention, accounting, protocol, projection, export, and presentation work is mostly
typed and executable against synthetic or fixed fixtures, not joined prospectively on market data.

The routed-liquidity work is a valuable **new specialization** of the provider-economics and
impact-adjusted-valuation parts of the Book program. It is not the Book program itself. In
particular, a ghost-edge route study does not substitute for signed-flow memory, observed response,
attention excitation, execution shortfall, or Ember's composite episode study. The smallest useful
next move is therefore not more routed-liquidity formalism. It is one narrow, walking
**venue-geometry and price-object calibration spine**, followed by a prospective flow/response
sample.

## 1. Audit basis and status language

This review traces every named apparatus row, minimum evidence object, Glass surface, and M0–M7
study in [`JOSHI_BEACON`](../../microstructure/trades_quotes_prices/JOSHI_BEACON.md), plus B1–B8 in
[`OPEN_QUESTIONS`](../../microstructure/trades_quotes_prices/OPEN_QUESTIONS.md). It also checks the
transfer constraints in [`TRANSFER_LIMITS`](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md),
the full [field-model corpus](../field_models/README.md), the present implementation lanes, and the
code/fixtures/tests cited below. It evaluates completion against the composite human–machine process
in [`JOSHI_THOUGHT`](../../../JOSHI_THOUGHT.md), not against a narrower automated-trading proxy.

The status column always describes the **whole Book item**, not the strongest adjacent component:

| status | audit meaning |
| --- | --- |
| **implemented and walking** | The semantic item crosses the repository's exercised root path with durable admission/replay and a consumer; it is not merely compiled somewhere in the workspace. |
| **implemented but fixture-only** | Executable code and semantic tests exist, but the input/output is synthetic, fixed, or an offline sink rather than an admitted prospective market corpus. |
| **typed contract/reducer only** | Strong types, pure calculators, validators, or reducers exist, but the end-to-end object or study is not produced and consumed. |
| **research design only** | A serious design and falsifier exist in documents, but no executable artifact implements the item. |
| **partial/misapplied** | A nearby artifact implements only part of the object or uses a name that can be mistaken for the Book construct. |
| **absent** | No sufficiently specific design or implementation was found. A correct refusal to transfer an inapplicable LOB object can be an intentional absence. |

### What the root command actually proves

[`scripts/offline-readiness`](../../../scripts/offline-readiness) builds and tests the entire
workspace, Glass, companion, and Python analysis, then runs the core readiness walk. The runtime
walk in [`apps/core/src/readiness.rs`](../../../apps/core/src/readiness.rs) admits one companion
capture and gap, reopens the catalog, serves an exact stored Glass scene, and exercises an
idempotent operator command. The HTTP boundary is tested in
[`apps/core/tests/http.rs`](../../../apps/core/tests/http.rs).

That is meaningful integration, but it does **not** currently prove:

- continuous public-chain or Pump supervision;
- authoritative Pump/PumpSwap swap decoding and coherent historical state closure;
- a durable `joshi-projection` artifact mounted in a Glass scene;
- core admission of presentation scenes/events;
- production store-to-analysis export;
- wallet topology, attention, kernel, or field artifacts joined into the root scene; or
- any M0–M7 empirical result.

The classifications below do not upgrade a fixture merely because its package is included in the
workspace-wide test command.

## 2. Beacon design consequences

| `JOSHI_BEACON` consequence | status | concrete repository evidence | exact remaining gap |
| --- | --- | --- | --- |
| No universal `price` | **typed contract/reducer only** | [`joshi-market-math`](../../../crates/joshi-market-math/src/quote.rs) distinguishes `MarkObservation`, `SpotQuote`, and `ExecutableLiquidation`; [`joshi-projection`](../../../crates/joshi-projection/src/market.rs) further distinguishes mark, quote/refusal, and full-position quote. Protocol vectors exercise exact Pump/PumpSwap arithmetic in [`fixtures/protocol`](../../../fixtures/protocol). | No admitted state-to-quote-to-landed-fill corpus, no stressed liquidation, no production projection endpoint, and no executable-price stack in Glass. Legacy Glass still has SOL decimal fields such as `executableLiquidationSol` in [`apps/glass/src/contract/v1.ts`](../../../apps/glass/src/contract/v1.ts) and invented fixture values in [`mockSnapshot.ts`](../../../apps/glass/src/data/mockSnapshot.ts); these are not the new projection truth. |
| Event time and wall time are first-class | **implemented and walking** | Clock and as-of types are in [`joshi-domain`](../../../crates/joshi-domain/src/clock.rs), exact acquisition timing in [`joshi-sources`](../../../crates/joshi-sources/src/evidence.rs), bitemporal persistence in [`schema`](../../../schema), and the root readiness fixture crosses source receive, persistence, scene, and command clocks. Wallet/attention reducers add independent availability, slot, and semantic-validity axes. | No source gives a universal total order, correctly. The remaining work is to carry the full vector into the venue calibration and empirical studies rather than collapse it to candle time. |
| Observed response is not caused impact | **implemented but fixture-only** | The kernel prototype emits descriptive conditional response with restricted claim scope in [`response_kernels`](../../../analysis/src/joshi_analysis/response_kernels/estimator.py); causal leakage and future rows are tested in [`test_response_kernels.py`](../../../analysis/tests/test_response_kernels.py). Attention uses `marked_forcing_event_no_causal_claim` in [`joshi-attention`](../../../crates/joshi-attention/src/model.rs). | No admitted market `ObservedResponse`, matched controls, or curve-motion subtraction. The label discipline is implemented; the actual response study is not. |
| LP revenue is a path, not a fee counter | **typed contract/reducer only** | Per-bin principal, fees, rewards, unsupported values, add/remove/rebalance/close-reopen are separate in [`joshi-liquidity`](../../../crates/joshi-liquidity/src/position.rs) and [`action.rs`](../../../crates/joshi-liquidity/src/action.rs). Exact wallet effects/lots are implemented in [`joshi-accounting`](../../../crates/joshi-accounting/src/accounting.rs), and the combined fixed artifact is tested in [`joshi-projection`](../../../crates/joshi-projection/src/vector_tests.rs). | No real position path joins external fills, claims, withdrawals, network/rent costs, missed alternatives, and per-leg liquidation at a common cutoff. Routed lane 04 specifies it but does not implement it. |
| The first model is a baseline to break | **partial/misapplied** | The field/kernel lane explicitly limits its synthetic outputs and the toolbox defers specialist stacks; see [`18_kernels_fields.md`](../../implementation/lanes/18_kernels_fields.md) and [`MODELING_TOOLBOX.md`](../../implementation/MODELING_TOOLBOX.md). | The implemented “Hawkes” diagnostic is only a symmetric fixed-window log-rate screen, not a Poisson/seasonal baseline followed by a held-out Hawkes fit. No linear propagator, square-root, inventory, or HDIM baseline comparison exists. The principle is adopted; the baseline program is not. |

## 3. Concept-to-apparatus traceability

| Beacon concept/apparatus | status | exact evidence found | why this is not yet the Beacon item |
| --- | --- | --- | --- |
| 1. Price object and signature plot | **partial/misapplied** | Exact mark/quote/liquidation types and protocol profiles exist in [`joshi-market-math`](../../../crates/joshi-market-math/src/quote.rs); exact evidence-bearing DTOs exist in [`joshi-projection`](../../../crates/joshi-projection/src/market.rs). Pump and DLMM vector tests live in [`joshi-market-math/src/vector_tests.rs`](../../../crates/joshi-market-math/src/vector_tests.rs) and [`joshi-liquidity/src/vector_tests.rs`](../../../crates/joshi-liquidity/src/vector_tests.rs). | Search of code/tests finds no variogram or signature-plot implementation, no fill calibration, no multi-price overlay, and no state-age/route scale selector. The generic candle and mock SOL values in Glass are an accidental substitute, not a price-object apparatus. |
| 2. Event intensity / Hawkes | **partial/misapplied** | [`response_kernels/estimator.py`](../../../analysis/src/joshi_analysis/response_kernels/estimator.py) emits `hawkes_window_excitation_candidate`; [`test_response_kernels.py`](../../../analysis/tests/test_response_kernels.py) checks claim boundaries and censoring. Attention contracts preserve event/availability clocks and coverage in [`joshi-attention`](../../../crates/joshi-attention/src/model.rs). | The lane itself states this is a symmetric fixed-window arrival log-rate screen, not a Hawkes likelihood or branching ratio. There is no complete prospective interval, seasonal/Poisson comparator, exogenous-covariate fit, held-out event forecast, or live intensity strip. Calling this “Hawkes” without the suffix would be stale/misleading. |
| 3. Long-memory signed flow | **typed contract/reducer only** | Version-bound swaps/transfers and marked asset flow are emitted by [`joshi-wallet-topology`](../../../crates/joshi-wallet-topology/src/table.rs); wallet-source normalization reaches the topology reducer in [`crates/joshi-wallet-source/tests/offline_wallet_source.rs`](../../../crates/joshi-wallet-source/tests/offline_wallet_source.rs). | No sign definition is frozen across routed/multi-asset/LP transactions, no cold-market denominator is admitted, and no ACF, DAR/Markov, lifecycle, wallet-repeat, or herding/splitting analysis exists. A topology flow edge is necessary evidence, not a long-memory result. |
| 4. Queue/state dependence | **typed contract/reducer only** | Venue-native Pump, PumpSwap, and DLMM state/calculators exist in [`joshi-market-math`](../../../crates/joshi-market-math) and [`joshi-liquidity`](../../../crates/joshi-liquidity). The field corpus requires H1 protocol kinematics before H2 fields in [`STATE_SPACE`](../field_models/STATE_SPACE.md). | No pre-event state snapshot is joined to a real event/response series and no transition/hitting model is calibrated. Conventional queue imbalance is intentionally absent because AMMs have no FIFO best queue; exact curve/bin state is the proper replacement. |
| 5. Observed / reaction / prediction impact | **implemented but fixture-only** | Synthetic marked responses, bitemporal contexts, coverage, and noncausal claim scope are implemented in [`analysis/src/joshi_analysis/response_kernels`](../../../analysis/src/joshi_analysis/response_kernels) and tested in [`test_response_kernels.py`](../../../analysis/tests/test_response_kernels.py). | No matched-control estimate, modeled reaction term, pre-event exact protocol state, or multiple price objects are joined. It proves the schema can reject future information, not the reaction/prediction identity on market data. |
| 6. Selective liquidity taking | **research design only** | Exact size and side are retained by the quote kernels, and routed lane 06 proposes state/size/route studies in [`06_DYNAMICS_CAUSALITY.md`](06_DYNAMICS_CAUSALITY.md). | There is no response row set conditioned jointly on exact size and pre-state, no raw-versus-state-conditioned size curve, and no action-value comparison against quote/fill error. The quote calculator alone describes mechanical cost, not selective taking. |
| 7. Square-root metaorder impact | **absent** | No `ParentFlowHypothesis`, parent/child linkage, participation denominator, square-root fit, or competing scaling test was found in code or fixtures. [`TRANSFER_LIMITS`](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md) correctly forbids replacing exact AMM curve arithmetic with square-root impact. | This is a correct deferral until `Q`, `T`, child linkage, venue volume, volatility, and coverage are defined. It remains an unimplemented Book baseline, not a rejected empirical conclusion. |
| 8. Propagator / resilience | **partial/misapplied** | The field prototype emits `recovery_resilience` in [`field_models/estimator.py`](../../../analysis/src/joshi_analysis/field_models/estimator.py), tested on synthetic CPMM-shaped inputs in [`test_field_models.py`](../../../analysis/tests/test_field_models.py). Glass has a fixture panel named `liquidity_susceptibility_resilience` in [`presentation/fixtures.ts`](../../../apps/glass/src/presentation/fixtures.ts). | Neither artifact fits a linear signed-flow propagator or compares bare versus dressed response. The displayed recovery can be arbitrage, opposing flow, regime change, or attention exit. The familiar name is the highest-risk accidental substitution in the current product. |
| 9. Asymmetric liquidity | **absent** | The contracts can carry event marks and state, but no frozen event-time predictor, surprise variable, price-changing status, TIM baseline, or HDIM challenger exists. | A state-conditioned response is not yet “asymmetric liquidity”; expected-versus-surprising event response must be computed prospectively. |
| 10. Adverse selection | **typed contract/reducer only** | DLMM position entitlement and exact fees/rewards are typed in [`joshi-liquidity`](../../../crates/joshi-liquidity); whole-position quote and accounting closure are combined in [`joshi-projection`](../../../crates/joshi-projection). Routed lanes [04](04_OPTION_CONTROL_ACCOUNTING.md) and [06](06_DYNAMICS_CAUSALITY.md) define fee/selection/inventory paths. | No real provider fill is joined to subsequent executable value, non-fill opportunity, external flow attribution, or full P&L. `fee earned` and `adverse selection` therefore remain unestimated. |
| 11. Latent liquidity | **research design only** | H4 is explicitly an equivalence/abduction layer in [`FIELDS_AND_OPERATORS`](../field_models/FIELDS_AND_OPERATORS.md), and routed ghost edges are typed as counterfactual designs in [`03_GHOST_EDGE_EXPERIMENT.md`](03_GHOST_EDGE_EXPERIMENT.md). | No calibrated latent state-space model or future executable-depth scenario artifact exists. A ghost edge is a chosen intervention, not an estimate of hidden future supply; cluster/territory hypotheses are not latent liquidity either. |
| 12. Execution shortfall | **typed contract/reducer only** | Operator commands/scenes exist in [`joshi-operator`](../../../crates/joshi-operator), exact intended-versus-observed quote binding in [`joshi-market-math`](../../../crates/joshi-market-math/src/quote.rs), and landed wallet effects in [`joshi-accounting`](../../../crates/joshi-accounting/src/effect.rs). | No object joins decision price, all attempts, send/landing/finality clocks, failures, fees, route, fill, and residual. The repository correctly keeps a quote from becoming a fill, but has not decomposed shortfall. |
| 13. Instability / withdrawal | **research design only** | Coverage gaps/source health are durable in [`joshi-store`](../../../crates/joshi-store) and protocol-native liquidity edits are typed in [`joshi-liquidity`](../../../crates/joshi-liquidity/src/action.rs). Tail/refusal scenarios are specified in routed lane [04](04_OPTION_CONTROL_ACCOUNTING.md) and field red-team fixtures in [`ANALOGY_REDTEAM`](../field_models/ANALOGY_REDTEAM.md). | No time-aligned liquidity edits, route loss, quote gaps, volatility/intensity, provider failures, or correlated withdrawal docket is produced. A source outage is not itself market liquidity withdrawal. |
| 14. Impact-adjusted valuation | **typed contract/reducer only** | Fresh full-position quote requirements and unknown/stale/refused readings exist in [`joshi-projection`](../../../crates/joshi-projection/src/accounting.rs) and its fixed golden. Exact runner basis is retained in [`joshi-accounting`](../../../crates/joshi-accounting/src/lots.rs). | The projection is not durable/core-mounted or rendered from its exact bytes, and no stressed multi-route liquidation distribution exists. Current `EpisodeRail` reads legacy mock SOL decimal fields, so the product does not yet use executable exposure truth. |

### Interpretation

Observed conditional response is the only Beacon analysis row family close enough to its named
construct to classify as fixture-only rather than partial/misapplied, and it is synthetic. The
strongest implemented areas—exact price semantics, accounting, and LP arithmetic—are prerequisites.
They become Book apparatus only when joined to coherent historical/prospective state, fills,
coverage, and a consumer.

## 4. Minimum evidence objects

The corpus deliberately calls these semantic closures rather than demanding one universal table.
The audit uses that standard: distributed components are acceptable, but all named fields must close
for one occurrence.

| minimum object | status | existing pieces | missing closure / accidental substitute |
| --- | --- | --- | --- |
| `MarketEvent` | **typed contract/reducer only** | Immutable acquisition/observation/source-event evidence in [`joshi-evidence`](../../../crates/joshi-evidence/src/model.rs); exact chain transaction versions, account roles, transfers, swaps, and LP events in [`joshi-wallet-topology`](../../../crates/joshi-wallet-topology/src/fact.rs); exact social forcing events in [`joshi-attention`](../../../crates/joshi-attention/src/model.rs). | There is no portable adapter that emits one source-native venue event with decoded atomic effects, lifecycle, finality, raw observation, coverage, and attribution quality into analysis. `RawTransactionFact` is chain evidence, not by itself a market event; `AttentionEvent` is a forcing mark, not a trade. |
| `StateAtEvent` | **typed contract/reducer only** | Exact protocol state types, observations, profiles, fee rules, DLMM bins, and freshness types exist across [`joshi-market-math`](../../../crates/joshi-market-math), [`joshi-liquidity`](../../../crates/joshi-liquidity), and [`joshi-projection`](../../../crates/joshi-projection/src/market.rs). | No adapter reconstructs coherent pre-state at each market event and emits a declared size grid plus age/completeness. Nearby account observations are not proven coherent merely by nearby wall time. |
| `ObservedResponse` | **implemented but fixture-only** | A strict synthetic response contract and estimator exist in [`response_kernels/contracts.py`](../../../analysis/src/joshi_analysis/response_kernels/contracts.py) and [`estimator.py`](../../../analysis/src/joshi_analysis/response_kernels/estimator.py), with bitemporal/gap/censoring tests. | No Book price-kind vector, event-time and wall-time lag pair, deterministic curve contribution, migration/route status, or admitted real event closure. |
| `ParentFlowHypothesis` | **absent** | Wallet clusters, co-trades, bundles, and operator episodes are available as separate hypotheses/facts. | None is a parent flow. No prospective parent ID, child closure, intended/observed `Q`/`T`, participation denominator, evidence-quality enum, or revision line exists. Inferring a metaorder from a whole episode would erase exits and re-entry. |
| `LiquidityProviderPath` | **typed contract/reducer only** | Exact DLMM bin inventory/actions in [`joshi-liquidity`](../../../crates/joshi-liquidity); finalized effects/lots in [`joshi-accounting`](../../../crates/joshi-accounting); composite fixed artifact in [`joshi-projection`](../../../crates/joshi-projection). | No prospective per-position path joins starting assets, every landed add/remove/claim/rebalance, external flow, fees/rent/network cost, withdrawal, two-leg liquidation, and a separate counterfactual branch. Routed lane 04 is the design for this missing join. |
| `OperatorDecisionScene` | **partial/misapplied** | The exact Glass view and operator command are durably walked by core; strict contracts are in [`apps/glass/src/contract`](../../../apps/glass/src/contract) and [`crates/joshi-operator`](../../../crates/joshi-operator). Scene/choice/gesture tables exist in the analysis snapshot fixture. | V1 operator commands bind scene/view but not the newer presentation artifact; presentation admission is an offline TypeScript sink only. The walking scene has no exact quote/projection/LP exposure or real choice-surface adapter. It is a strong scene skeleton, not yet the Book's full pre-action scene. |

## 5. Glass surfaces implied by the Book

| Glass surface | status | present surface | exact gap |
| --- | --- | --- | --- |
| A. Executable price stack | **partial/misapplied** | `MarketChart`, candidate metrics, and `EpisodeRail` exist; exact financial projection types exist outside Glass. | Glass does not render last fill, marginal, intended clip, full runner, instruction bound, and stressed liquidation from one evidence-backed projection. Current decimal mock values can look more authoritative than the implemented read-only calculators. No production projection route exists. |
| B. Flow and intensity strip | **partial/misapplied** | The fixture-only hypothesis lab has wallet flow, marked orders, and attention-arrival panels in [`HypothesisLab.tsx`](../../../apps/glass/src/components/HypothesisLab.tsx); topology and attention rows exist in Rust fixtures. | No time-aligned event-time signed-flow raster, wall-time seasonal/residual intensity, cumulative base/quote atoms, participant uncertainty, social tracks, and exact census/hot-scope boundary are assembled from admitted artifacts. |
| C. Response surface | **implemented but fixture-only** | The exploration bundle contains caller-response and liquidity-recovery panels; TypeScript contracts and reference vectors are tested in [`apps/glass/src/presentation`](../../../apps/glass/src/presentation). | Values are `descriptive_noncausal_fixture`, not admitted Python artifacts. The surface lacks exact size/pre-state/lifecycle/price-kind/event-surprise axes and deterministic curve separation. Core cannot admit the presentation artifact yet. |
| D. LP truth waterfall | **research design only** | Detailed design appears in routed lanes [04](04_OPTION_CONTROL_ACCOUNTING.md) and [05](05_GLASS_OPERATOR.md); the exact component DTO substrate exists in `joshi-projection`. | No Glass component consumes a durable projection for principal, fees, rewards, selection, edit friction, withdrawal inventory, and per-leg liquidation. |
| E. Episode rail | **implemented but fixture-only** | [`EpisodeRail.tsx`](../../../apps/glass/src/components/EpisodeRail.tsx), exact episode/epoch logic in [`joshi-accounting/src/episode.rs`](../../../crates/joshi-accounting/src/episode.rs), and runner/flat-watch/re-entry fixtures/tests exist. | The rendered rail consumes legacy fixture accounting rather than the exact projection, and there is no prospective corpus joining notice→scene→entry→management→flat-watch→re-entry. It demonstrates interaction/semantics, not M7. |

The Wave 3 presentation lab is not the five-surface Book Glass. Its eight fixture panels are a
valuable experiment harness, but a generic `liquidity_susceptibility_resilience` panel must not be
treated as either an executable price stack or a fitted propagator.

## 6. Study M0–M7 traceability

| study | status | what exists | what must happen before the study is truthfully “run” |
| --- | --- | --- | --- |
| M0 — exact venue price geometry | **partial/misapplied** | Pump/PumpSwap/DLMM pure calculators, exact rounding/refusal fixtures, coherent intended/observed quote identity, and a single-runtime projection golden. | Acquire coherent authoritative state closures; add PumpSwap finalized vectors and decoder conformance; record decision/quote/landing/finality clocks, failed attempts, and landed fills; compare mark/marginal/size quote/fill/full liquidation; publish and render the calibration corpus. Pure formula agreement is only half of M0. |
| M1 — signed-flow persistence by lifecycle | **absent** | Exact version-bound flow facts and topology tables are available as substrate. | Freeze signs and lifecycle regimes, acquire a prospective census plus random cold stratum, prove denominators/coverage, compute ACF and IID/Markov/DAR/seasonal/shuffle baselines, and separate repeated actors/routes from broader flow. No such dataset or result exists. |
| M2 — state-conditioned observed response | **partial/misapplied** | Synthetic conditional response kernels and synthetic CPMM price-response-per-flow exist. | Join real `MarketEvent` + coherent `StateAtEvent`; target multiple typed prices; subtract/show deterministic curve movement; retain migration/rug/route loss as outcomes; compare raw and state-matched size curves. Current recovery/resilience output is not this atlas. |
| M3 — linear resilience versus history-dependent state | **partial/misapplied** | A fixed-window arrival diagnostic and a synthetic recovery number exist. | Freeze event vocabulary and epochs, fit random-walk/Poisson, linear propagator, TIM, and HDIM/state challengers on prospective data, then report held-out response/variance/residual failures. No propagator or HDIM is implemented. |
| M4 — attention excitation without causality theater | **partial/misapplied** | Rich attention event/identity/territory/coverage/censoring contracts and synthetic kernel/cohort tests exist in [`joshi-attention`](../../../crates/joshi-attention) and the Python kernel prototype. | Acquire one lawful complete board/callout census prospectively; add time-of-day, market, product-rank, unrelated-mint, future-shift, and platform-burst controls; compare seasonal/negative-binomial baselines before a point process; evaluate held out. No direct Pump social adapter or prospective result exists. |
| M5 — LP adverse selection and inventory conversion | **typed contract/reducer only** | Exact per-bin inventory, modeled action algebra, accounting, and read-only projection are implemented and fixture-tested. Routed lane 04 adds a strong joint-policy research design. | Follow a real position prospectively from a common cutoff; separate external and self flow; record every claim/add/remove/edit, fees/rent/network cost, withdrawal and leg liquidation; compare frozen no-change/edit policies; include correlated tails and opportunity baseline. |
| M6 — crackle microdip feasibility | **research design only** | Operator nominations/gestures, exact quote math, accounting, and episode semantics are prerequisites; the original design remains in `JOSHI_BEACON`. | Start at nomination; retain intended trigger and shadow attempt clocks; reconstruct attainable quote/fill/exit ladder; preserve manual interventions and failed/unlanded attempts; compare frozen branches without replaying the future as fixed. No joined microdip experiment exists. |
| M7 — partial exits, runners, and re-entry | **typed contract/reducer only** | Exact lots, partial basis, capital recovery, runners, flat-watch, and re-entry are tested in [`joshi-accounting/src/vector_tests.rs`](../../../crates/joshi-accounting/src/vector_tests.rs); projection adds stale liquidation refusal and a fixed combined golden. | Collect prospective declarations/scenes and attainable alternative quotes at common cutoffs; score realized cash plus remaining full-liquidation value and downside at a common horizon. The arithmetic state machine is real; the management-disposition study is not. |

No M0–M7 study is currently “implemented and walking.” This is not a negative empirical result. It
is a precise statement that the studies have not yet been conducted.

## 7. Strategy-family implications and promotion rule

These implications are part of the Beacon's application, even though they are not additional model
families.

| Beacon implication | status | traceability finding |
| --- | --- | --- |
| Crackle | **research design only** | The repository has nomination/gesture contracts, exact quote kernels, and accounting, but no joined nomination→trigger→quote→attempt→fill/failure→exit path. The Book has correctly weakened a generic mean-reversion story; it has not established a state-conditioned crackle edge. |
| Runner | **typed contract/reducer only** | Exact residual quantity/basis and capital recovery are implemented; fresh full-position quote linkage is fixture-tested. No durable current liquidation surface or prospective disposition comparison exists. |
| Exit, flat watch, and re-entry | **typed contract/reducer only** | The episode/epoch state machine represents exact flat, continued attention, and fresh-basis re-entry. No prospective scene corpus tests whether these discretionary revisions add value. |
| Fancoins and social transitions | **typed contract/reducer only** | Attention distinguishes creator, identity, community, social revisions, and marked events while rejecting causal contagion. Direct source completeness and held-out transition analysis remain absent. |
| Meteora LP | **typed contract/reducer only** | Venue-native bins, shares, fees, actions, and withdrawal inventory replace invalid queue formulas. The fee/selection/liquidation economic path remains unjoined on a real position. |
| Complete Pump alternative | **partial/misapplied** | The core/companion/Glass path can durably render one narrow fixture scene and semantic command; the presentation lab can preserve a rich fixture choice surface. It does not reproduce the same-or-better live Pump attention surface, continuous direct social collection, exact candidate census, or current financial truth. Therefore it can study a selected slice, not Ember's whole selection policy. |

The seven-part promotion rule is **research design only as a whole**. Joshi can already represent
venue-native definitions, coverage, operator intervention, and some quote/fee/tail inputs, but no
candidate effect has yet passed prospective held-out testing, attainable baselines, economic-error
comparison, correlated-tail/capacity accounting, and a useful-product fallback together. Nothing in
this audit earns an arm button or execution authority.

## 8. OPEN_QUESTIONS lanes B1–B8

| lane | status | trace | finding |
| --- | --- | --- | --- |
| B1 — equation and notation audit | **absent** | The book corpus has prose equations and an extraction-defect register, but no machine-readable equation registry, rendered crops, second transcription, dimensional metadata, or executable cases. | Do this narrowly before implementing Hawkes, propagator, fair-pricing, latent-liquidity, or no-manipulation formulas. Exact protocol arithmetic is not a substitute for auditing the cited book equations. |
| B2 — venue-native price/impact semantics | **partial/misapplied** | [`12_protocol_liquidity.md`](../../implementation/lanes/12_protocol_liquidity.md) implements exact Pump/PumpSwap/DLMM arithmetic; routed [02](02_VENUE_ROUTABILITY.md) compares current venue/routing possibilities. | The deliverable also requires fill, subsequent response, liquidation, authoritative observation reconstruction, and a formal cross-venue comparison. PumpSwap lacks a full finalized account closure; DLMM actions remain modeled-only; routeability research is not calibration. |
| B3 — signed-flow and activity baseline | **typed contract/reducer only** | Wallet-source/topology and attention supply exact events, marks, bitemporal identity, and coverage schemas. | No frozen prospective dataset, cold stratum, sign ACF, seasonal/Poisson baseline, participant clustering evaluation, or held-out forecast. |
| B4 — AMM observed-response atlas | **partial/misapplied** | Python produces synthetic marked responses and synthetic CPMM susceptibility/recovery artifacts. | It does not ingest authoritative AMM pre-state, show exact protocol contribution separately, or align real post-event price objects. The word `response` in an artifact name does not complete B4. |
| B5 — social intensity and transition study | **typed contract/reducer only** | [`17_attention_topology.md`](../../implementation/lanes/17_attention_topology.md) and `joshi-attention` implement the source-normalized ontology, point-in-time joins, risk rows, and adversarial fixture. | No direct source adapter, complete prospective social inventory, seasonal/common-cause baselines, negative controls, or held-out results. Companion reconnaissance is not a market-wide social census. |
| B6 — LP provider-economics docket | **typed contract/reducer only** | Exact liquidity/accounting/projection kernels plus routed lane 04 cover most semantic components. | No prospective position docket and no external-flow, adverse-selection, rebalance, opportunity, and terminal-liquidation join. The routed documents greatly improve the design but remain documents. |
| B7 — composite management episodes | **implemented but fixture-only** | Exact episode/epoch/lot arithmetic, operator command/scene contracts, 14-table analysis snapshot, fixture Glass, and adversarial runner/re-entry vectors exist. | The current corpus is manufactured. No small prospective crackle/runner/full-exit/flat-watch/re-entry set with witnessed presentations and attainable counterfactual quotes has been collected. |
| B8 — microstructure textbook comparison | **absent** | The present corpus distills the 2018 book; routed lane 02 reviews current venue/SDK facts, not the current academic evidence requested by B8. | B8 properly waits for a frozen B2 question. Do not confuse current protocol-document research with a primary-literature comparison of AMM execution, Solana MEV, discrete liquidity, crypto flow, and impact estimation. |

## 9. Accidental substitutions and stale claims

These are the places most likely to create the false impression that the Book has already been
implemented.

1. **Two incompatible `M0…` namespaces.** `JOSHI_BEACON` reserves M0–M7 for the eight Book studies.
   Routed [`06_DYNAMICS_CAUSALITY.md`](06_DYNAMICS_CAUSALITY.md) independently names causal claims
   `M0`–`M6`, where routed M0 means mechanical route possibility. This should be renamed before any
   artifact/schema uses it, for example `RL-C0…RL-C6`. Routed M0 is a fragment of Book M0, not the
   same study.

2. **“Hawkes” is currently a window screen.** The implementation explicitly says it is not a
   Hawkes likelihood or branching ratio. Product copy and manifests should retain the full name
   `hawkes_window_excitation_candidate` or, better, `fixed_window_arrival_screen` until a real
   point-process fit exists.

3. **“Resilience” is not a propagator.** The synthetic field output
   `recovery_resilience` is an observed recovery ratio for a generated venue trace. It has no
   signed-flow kernel, bare/dressed response, event-history fit, or causal identification. The
   fixture Glass panel should display that narrower definition beside the number.

4. **The projection golden is not a live projection.** The 27,146-byte Rust-only
   `joshi-projection` vector proves deterministic encoding and semantic validation. It has no
   TypeScript/Python byte mirror, durable projection endpoint, current source closure, or Glass
   consumer. A checked calculator result is not evidence a route was executable or landed.

5. **The root readiness gate is not the Book walk.** It exercises companion→store→scene→command and
   broad package tests. It does not make the fixture-only wallet, attention, projection,
   presentation, export, and model products one integrated market episode.

6. **The Rust export is fixture-scoped.** [`joshi-export`](../../../crates/joshi-export) rewrites
   and Python-validates the 14 fixed Parquet tables. It is explicitly not a production store
   projection. Moreover, current checked-in export manifests still name
   `joshi.store.catalog/v5`, while the store catalog is now `joshi.sqlite.v6`; this is acceptable
   only as frozen fixture provenance, not a current-store compatibility claim.

7. **Generic Glass is not Book Glass.** The Wave 3 lab records presentation policy carefully, but
   the source artifacts are `fixture_unverified`, the core presentation endpoints are absent, and
   the eight panels do not implement the five Beacon surfaces. The walking core scene contains a
   raw-off companion attestation and no financial projection.

8. **Legacy Glass accounting fields are stale semantic debt.** `totalSpentSol`,
   `realizedNetSol`, `executableLiquidationSol`, and related fields in the frozen V1 view are
   display decimals populated by mock data. They are not backed by `ProjectionArtifactV1` and must
   not be cited as implemented accounting or executable valuation.

9. **Wallet/cluster context is not participant truth.** `SelectedClusterContext` is deliberately a
   narrow, event-bound projection. It does not supply the participant attribution quality needed
   by M1/M2 without the full topology artifact and point-in-time selection closure.

10. **A ghost edge is neither latent liquidity nor observed provider flow.** It is a preregistered
    counterfactual operator. A route solver can establish changed mechanical possibility under
    assumptions; it cannot establish that routers would select the edge, the market would adapt,
    or fees would be earned.

11. **Routed-liquidity completeness must not displace market-wide coverage.** The routed documents
    are substantially more detailed than the still-missing M1–M4 work. That reflects recent design
    attention, not an evidence-based priority reversal.

## 10. What transfers to AMMs, and what must not

The right test is not whether an AMM object resembles an order-book noun. It is whether the source
mechanism exists.

| source-book object/question | Pump / PumpSwap / DLMM treatment | audit decision |
| --- | --- | --- |
| Mark, finite-size quote, fill, liquidation | Reconstruct from venue-native integer state, fees, route, landing state, and wallet effects. | **Direct question; new exact implementation.** This is Joshi's strongest Book application so far. |
| Signed-flow persistence and wall-time intensity | Define direction/size on authoritative swap/effect semantics; retain route/wallet uncertainty, lifecycle, coverage, and social/product covariates. | **Direct empirical question; new participant model.** Not yet run. |
| State-dependent response | Pump virtual/real reserves and completion; PumpSwap raw/effective reserves and fee profile; DLMM active bin, exact bins/shares/dynamic fees. | **Analogue requiring venue-native derivation.** Subtract/show deterministic curve movement before later response. |
| Queue imbalance, bid/ask spread, one-tick depletion, FIFO priority | These objects do not exist on the three AMM forms. A DLMM bin share is not queue position. | **Invalid direct transfer.** Their absence is correct, not backlog. |
| Queue transition/hitting methodology | Use protocol-native state transitions, discrete bin crossings, jumps, route changes, and liquidity edits. | **Method transfers; variables/equations do not.** No calibrated model yet. |
| Square-root impact | Only for a defensible parent flow after exact instantaneous AMM mechanics and route volume are defined. | **Baseline to challenge.** Never replace curve/bin traversal with it. |
| Propagator/asymmetric liquidity | Model subsequent adaptation after the known mechanical state transition, using event history and surprise under a frozen predictor. | **Analogue requiring derivation and regime boundaries.** Current “resilience” is insufficient. |
| Maker/LP economics | Fees minus adverse inventory conversion, edit/withdrawal/network costs, residual leg liquidation, and opportunity under a common horizon. | **Economic decomposition transfers directly.** Half-spread and queue-priority formulas do not. |
| Latent V-shaped order book | Future traders, LP edits, routes, attention, and arbitrage are uncertain arrivals over visible AMM state. | **Scenario/latent-model analogy only.** Never a current `latent_liquidity` fact column. |
| No-profitable closed mechanical loop | Exact simulator should not manufacture frictionless profit through rounding, internal self-fees, or inconsistent state updates. | **Conditional invariant analogue.** External arbitrage, fees, ordering, and stochastic landing must be explicit assumptions. |

Venue-native translation therefore strengthens, rather than weakens, the need for the Book. Exact
AMM arithmetic supplies H1 deterministic motion. It does not answer H2/H3 questions about who
arrived, what state adapted, what followed, or whether a policy was profitable.

## 11. Smallest high-leverage backlog that actually applies the Book

This is deliberately smaller than implementing every named model and broader than another ghost
edge paper design.

### P0 — walk one price-object calibration spine

Choose one fixed observation family for each of Pump curve, PumpSwap, and DLMM, with one economically
relevant direction/size grid. Carry:

```text
exact source bytes and coherent account closure
  -> versioned protocol state/profile
  -> mark + marginal + directional size quotes/refusals
  -> attempted transaction/simulation when available, without authority
  -> finalized landed fill/effect or explicit failure
  -> whole-position and stressed liquidation
  -> durable ProjectionArtifactV1
  -> one evidence-backed Glass executable-price stack
  -> manifested calibration rows for analysis
```

Pass only if cross-runtime encodings, state age, route/finality, and quote/fill error are explicit and
the error is below a predeclared crackle-scale hurdle for at least one scoped venue/size. This one
slice closes the most dangerous current gap: exact calculators that are never confronted with
landing state. It advances Book M0, B2, `StateAtEvent`, `OperatorDecisionScene`, Glass A, and the
valuation prerequisites for M5–M7.

Do not start with a hypothetical routed edge. Use an observed existing route/state so the first
calibration has a real fill/refusal target.

### P1 — freeze a prospective signed-flow/activity sample before fitting models

Collect a bounded census plus a deliberately random cold-mint stratum for a fixed interval. Require
authoritative swap direction/effects, lifecycle transitions, exact event and wall clocks,
wallet/route attribution quality, source coverage/gaps, and hot-scope activation times. First emit:

- IID and shuffled-within-state sign baselines;
- time-of-day/market-activity baseline;
- sign ACF in event and wall time;
- repeated-wallet/route versus residual decomposition; and
- an honest statement of which denominator is complete.

This is Book M1/B3. Do **not** fit Hawkes first. The denominator and sign semantics are the valuable
deliverable even if persistence vanishes.

### P2 — turn the existing kernel prototype into a real AMM response atlas

Join P0 `StateAtEvent` and P1 `MarketEvent` rows to create `ObservedResponse`. Show deterministic
protocol motion separately, retain multiple price kinds, and stratify on size, state, lifecycle,
route age, and preceding flow. Preserve migration, route disappearance, and source loss as outcomes
or censoring states rather than dropping them. Feed the admitted artifact into the existing
noncausal response surface. This is M2/B4; it must precede propagator/HDIM enthusiasm.

### P3 — collect one real LP path and one real management episode

For a single existing Meteora position, prospectively record all position versions, claims,
adds/removes, manual edits, withdrawal inventory, exact leg quotes, route failures, and Ember's
witnessed scenes. In parallel, follow one nominated spot episode through partial/full exit,
flat-watch, and possible re-entry. Use the current accounting/projection kernels; do not add policy
optimization. This makes the large amount of existing exact code pay rent and advances M5/M7,
B6/B7, Glass D/E, and the missing provider/operator objects.

### P4 — run the bounded attention pilot, then decide whether social modeling survives

Use the lane 17 smallest experiment: one declared board/filter, complete contemporaneous candidate
pages if lawfully available, direct/companion parity, exact revisions and availability, product
ranking, unrelated-mint and future-shift controls, and chain response coverage. Begin with seasonal
and platform-burst baselines. If honest completeness is unavailable, preserve manual scene evidence
and explicitly restrict claims; do not infer market-wide excitation from the attended slice.

### Narrow prerequisites, not new programs

- Complete B1 only for equations actually used in the next study.
- Refuse the current wide-decimal-to-`int64` response contract mismatch rather than narrowing exact
  atoms; version a tagged wide-value schema when P2 needs it.
- Rename the routed `M0`–`M6` namespace now.
- Do B8 after P0 freezes the exact contemporary questions.
- Keep the ghost-edge isolated atlas after P0, not before it. It can then consume calibrated venue
  operators instead of becoming a second unvalidated quote universe.

## 12. Far-future Lean roadmap

Lean should formalize boundaries where proof is stronger than testing. It should not be asked to
turn historical data into a theorem of profitability. The dependency order below is intentional.

### A. Exact program arithmetic, state transition, and conservation proofs

These are the highest-value proof targets because the assumptions can be finite, explicit, and
close to deployed program profiles.

1. Define dimensioned atoms, assets, pairs, fee units, checked narrowing, floor/ceiling division,
   and fixed-width word semantics. Prove basic range and rounding lemmas.
2. Specify profile-versioned Pump and PumpSwap transition/quote functions, including virtual versus
   real reserves, exact-base direction, fee tier selection, literal floor-plus-one, real payout
   capacity, and refusal. Prove nonnegative reserve/capacity properties and asset conservation
   modulo explicit fee postings.
3. Specify DLMM Q64.64 price, bin traversal, share entitlement, dynamic-fee units, add/remove, and
   in-place/no-swap conservation for the supported profile. Prove per-bin entitlement bounds,
   ordered traversal, and chunk-plan coverage. Leave unsupported composition/initial-share behavior
   outside the theorem rather than axiomatizing it silently.
4. Specify migration and cross-program asset-identity mappings as explicit state transitions. Prove
   that a migration splice preserves declared atomic conservation when its evidence closure holds.
5. Differentially check the Rust operation graph against extracted Lean functions and immutable
   program/SDK vectors. A proof of the model is not proof that the deployed program matches it;
   profile/hash/decoder conformance remains an empirical and operational obligation.

### B. Replay, accounting, and strategy-policy invariants

These are deterministic system theorems over admitted histories, not claims about returns.

1. Prove ingest idempotency, content/occurrence separation, append-only supersession, cursor-after-
   durability, witnessed replay, and no future-known row under the declared bitemporal selection
   function.
2. Prove accounting conservation over finalized wallet effects, internal controlled-domain
   transfer cancellation, lot quantity/basis partition closure, exact-flat basis closure, runner
   basis retention, and capital-recovery separation from PnL.
3. Prove episode/epoch/lot orthogonality: an episode can span flat watch and re-entry; an inventory
   epoch is flat-to-flat; attribution cannot create balances; a parent flow cannot be inferred from
   episode identity.
4. Prove LP custody transformations do not create consolidated wealth; owned self-routed fees do
   not become external income; withdrawal is not sale; unsupported liquidation legs make scalar
   value partial rather than zero.
5. Prove no silent intent netting or double reservation across slow/medium/fast policy clocks,
   authority monotonicity, hard risk/capital ceilings, idempotent command semantics, and that
   read/shadow artifacts cannot construct/sign/submit transactions.
6. Prove presentation/scene lineage: no empirical exposure before admission/visibility events,
   operator action binds the exact scene/presentation cut, and later outcomes cannot rewrite it.

Lean can prove these over a formal event algebra even if the production implementation remains
Rust/TypeScript/Python, using generated vectors, refinement tests, or a small verified reference
reducer. Full extraction is optional and should be earned by discrepancy risk.

### C. Conditional theorems under explicit stochastic or adversarial assumptions

These theorems are useful only when their assumptions are carried in the artifact and separately
tested. Lean proves the implication, not that the market satisfies the premises.

- Hawkes stationarity/finite mean under an explicitly nonnegative kernel and spectral radius below
  one; likelihood and discretization identities for the chosen family.
- Propagator response/variance identities and nonnegative closed-loop cost under an explicitly
  positive-semidefinite/no-dynamic-arbitrage kernel and stated event process.
- Relationships among observed, modeled reaction, and prediction terms under a declared
  counterfactual probability space; never identify the decomposition from one path by theorem.
- Censoring/risk-set estimand identities under stated independent/administrative censoring and
  positivity assumptions.
- Bounds on route/landing or LP reachable inventory under a declared adversarial ordering,
  bounded delay, finite capacities, and enumerated failure prefixes.
- Policy safety/regret bounds under a fixed action set, loss function, information filtration, and
  adversarial/stochastic assumptions. These can show a controller obeys a bound, not that its
  forecasts are true.

Assumption hashes and applicability predicates should travel with theorem-backed artifacts. A
green theorem with an untested stationarity, coverage, route, or exogeneity assumption is not an
empirical result.

### D. Claims Lean cannot prove from historical data

Lean cannot establish, merely from a checked historical corpus, that:

- crackle, runner, re-entry, LP, or routed-edge strategies have positive future expected value;
- a callout, creator action, wallet, cluster, or presentation caused later trading or price;
- a fitted Hawkes branching ratio represents socially caused trades;
- signed-flow memory, impact scaling, resilience, or liquidity regimes will remain stable;
- the sample covers the relevant market or that missingness is ignorable;
- an undeployed ghost edge would have attracted the replayed flow;
- Jupiter or another router will choose the same route at future states;
- Ember's discretionary selection generalizes beyond observed episodes; or
- a model's historical calibration survives adversarial platform, protocol, participant, or
  regulatory change.

Lean can verify the dataset manifest, information cut, estimator implementation, score arithmetic,
and statement “under assumptions A, this conclusion follows.” Evidence, external validity,
profitability, and causal identification remain empirical arguments with prospective falsifiers.

## 13. Decision

The correct conclusion is neither “the Book was ignored” nor “the architecture already implements
it.” The Book prevented several foundational mistakes and directly shaped high-quality exact
components. That work is worth keeping. The current risk is subtler: mistaking the sophistication
of those components—and the recent routed-liquidity documents—for evidence that the core empirical
program has run.

It has not. The highest-leverage course is to close one real price/state/quote/fill/liquidation
spine, then collect prospective flow and observed-response evidence. If that apparatus shows the
micro-profit scale is below quote/fill/source error, Joshi still yields a valuable exposure,
accounting, and operator-memory instrument. If structure survives, the existing topology,
attention, kernel, field, LP, and episode foundations become useful without having prejudged the
answer. That is exactly the Book program: build the object that can falsify the story before adding
model capacity or execution authority.
