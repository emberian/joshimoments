# Chapter notes

These notes are intentionally compressed. They identify each chapter's object, strongest result,
largest assumption, and JOSHI consequence without reconstructing the source prose.

## 1. The ecology of financial markets — pp. 5–21

The book begins with institutions rather than prices. Walrasian auctions, dealer markets, and
continuous double auctions produce different observables and different risks. Liquidity providers
quote/clear and earn compensation while facing adverse selection, impact, inventory, and skew;
liquidity takers buy immediacy [Secs. 1.1–1.3]. Competition makes this an ecology: one participant's
order is another's information and inventory shock [Sec. 1.4].

**JOSHI read.** Venue mechanics are part of the model, never a transport detail. A Pump curve,
PumpSwap pool, Meteora bin schedule, and external LOB must have different state and cost semantics.

## 2. Price-change statistics — pp. 22–41

Variograms and signature plots give scale-aware tests of diffusion, trend, mean reversion, and
microstructure noise [Eqs. 2.1–2.10]. Empirical returns are close to linearly unpredictable while
remaining heavy-tailed, intermittent, volatility-clustered, and excessively volatile relative to
simple news stories [Secs. 2.2–2.4].

**JOSHI read.** “No robust return predictor” does not imply “no structure.” Test price level,
event intensity, tails, execution state, selection, and management separately. Use multiple price
objects; a chart mark signature is not an executable-quote signature.

## 3. Limit order books — pp. 44–57

Defines price-time queues, bid/ask/mid, spread, relative price, depth, and depletion-based price
changes. Exchange rules, matching priority, hidden orders, and auction transitions are part of the
data-generating process [Secs. 3.1–3.2; Table 3.1; Figs. 3.1–3.3].

**JOSHI read.** Do not reuse this vocabulary for AMMs by metaphor. Define native reserve/bin/
transaction objects first, then state any economic analogy.

## 4. Empirical LOB properties — pp. 58–74

The 2015 NASDAQ examples show intraday seasonality, spread/depth variation, nontrivial placement and
cancellation distributions, hump-shaped volume profiles, and a strong relative-tick-size regime
split [Table 4.1; Figs. 4.1–4.12]. Buy/sell symmetry is a long-run aggregate property, not a local
balance [p. 61].

**JOSHI read.** Every “universal” study needs venue/lifecycle/time controls. Preserve actual
observation cadence, because market intensity and liquidity are nonstationary.

## 5. Simple single-queue models — pp. 78–100

Birth–death queues show how submissions, executions, cancellations, reinjection, and first-hitting
times interact [Eqs. 5.1–5.20]. Constant total cancellation needs near-critical fine tuning for
long queues; cancellation proportional to queue length creates a stabilizing `V*` and Q-CIR
diffusion with rare depletions [Secs. 5.3–5.5].

**Largest assumption.** Independent homogeneous unit flows and imposed queue renewal.

**JOSHI read.** The method transfers: define a small state machine, its transition hazards, and its
boundary events before fitting a predictor. The queue formula does not transfer to reserves.

## 6. Large-tick single queues — pp. 101–116

The chapter estimates drift/diffusion from conditional queue changes and adds price-changing jumps
and post-depletion reinjection [Eqs. 6.1–6.8]. Rescaling volume by mean depth yields approximate
cross-stock similarity, while sweeping orders expose limits of the diffusion truncation
[Table 6.1; Figs. 6.1–6.3].

**JOSHI read.** Fit state transitions in dimensionless protocol-aware coordinates, but retain jumps,
lifecycle changes, and exact integer mechanics rather than smoothing first.

## 7. Joint best queues — pp. 117–133

Best bid/ask queues race to depletion. Imbalance predicts the winner, yet independent diffusions
give the wrong curvature; moderate state-dependent drift and coupled diffusion improve the model
[Eqs. 7.11–7.12; Figs. 7.2, 7.5, 7.6]. Post-depletion queue renewal determines longer-horizon price
behavior.

**JOSHI read.** A good one-step predictor can fail because its state representation has the wrong
geometry. Evaluate calibrated probability, coverage, and economic action value separately.

## 8. Santa Fe zero-intelligence LOB — pp. 134–158

Independent Poisson deposition, cancellation, and execution on a price grid can generate spread,
depth, volatility, and impact without strategic or fundamental information [Secs. 8.2–8.7]. It is
a useful null. Its main failures are homogeneous time, state-independent flow, independence between
event types, and absence of adaptive liquidity [Secs. 8.8–8.9].

**JOSHI read.** Null models should preserve venue mechanics and only simplify behavior. A model-free
looking simulator that omits the curve/bin rules is not a null for the actual venue.

## 9. Hawkes processes — pp. 163–186

Linear Hawkes intensity separates deterministic baseline from event-history excitation
[Eqs. 9.10–9.13]. Kernel norm controls model stationarity and the first two moments identify the
linear specification [Eqs. 9.15–9.20]. Empirical fits often need broad power-law memory and appear
near critical; nonlinear price-feedback extensions can generate fat-tailed activity [Sec. 9.6].

**Largest warning.** Correlation-based Hawkes calibration does not establish causal excitation, and
near-criticality can diagnose model restriction rather than market instability [pp. 169, 183–184].

**JOSHI read.** Use as a forecasting and compression candidate only after seasonal, coverage,
ranking, and common-cause baselines.

## 10. Long-range order-flow persistence — pp. 187–204

Trade signs remain predictable across very long event lags even while returns do not [Fig. 10.1].
DAR copying models reproduce the autocorrelation algebraically; LMF metaorder splitting creates
long memory from broad parent durations, with `γ=ζ-1` [Secs. 10.4.2–10.4.3]. Identity-resolved
evidence favors splitting over long-run herding in the reviewed mature markets [Sec. 10.4.4].

**JOSHI read.** Cluster by wallet/router/person evidence and parent-intent quality before naming
herding. The unresolved parent-order problem resembles JOSHI's episode/tranche inference problem.

## 11. Market-order impact — pp. 208–228

The central epistemic result is the decomposition of observed impact into reaction and prediction
components [Eqs. 11.1–11.4]. Only the mixture is directly observed. Empirically, response depends on
price-changing status, size, previous sign, and state; selective liquidity taking makes unconditioned
size curves concave [Table 11.1; Figs. 11.1–11.6]. Aggregate signed-volume response introduces a
scale-dependent Kyle slope [Sec. 11.4].

**JOSHI read.** A historical chart after Ember's buy does not say what the buy caused or what would
have happened without it. Counterfactual labels and error bands are mandatory.

## 12. Metaorder impact — pp. 229–244

Parent orders executed through children exhibit a remarkably broad concave impact law,
approximately `I_peak=Yσ_T√(Q/V_T)` [Eq. 12.6; Fig. 12.2]. The chapter explicitly examines domain,
selection, horizon, and signal biases [Secs. 12.3.3–12.3.5]. Impact builds along the path and decays
after execution; under a square-root path, mean shortfall per unit is about two-thirds of peak
[Eqs. 12.10–12.11].

**JOSHI read.** Never turn the square-root law into a memecoin execution engine without first
defining parent order, contemporaneous volume, venue state, route, and lifecycle. It is a baseline
shape to challenge.

## 13. The propagator model — pp. 249–269

Linear transient impact writes price as the superposition of lagged signed trades plus residual
motion [Eqs. 13.7–13.9]. Observed response combines the bare kernel with correlated flow
[Eq. 13.10]. Diffusive price behavior under long-memory flow requires long-range resilience with
`β=(1-γ)/2` [Eq. 13.17]. History-dependent impact can instead make surprises matter more than
expected orders [Sec. 13.3].

**JOSHI read.** This is a compact candidate model for decomposing predictable flow from adaptive
response. It must be fit per venue/lifecycle and compared with nonlinear/state models.

## 14. Generalized propagators — pp. 270–286

Market orders alone are a reduced description. Splitting events into price-changing/non-changing
types helps, and a six-event model adds market orders, limit orders, and cancellations on both
sides [Table 14.1]. TIM and HDIM representations diverge once event types affect one another
[Eqs. 14.11–14.14]. Cross-impact and owner-tagged impact extend the same idea [Sec. 14.5].

**JOSHI read.** Define protocol-native event types and state consequences rather than one generic
trade tape. Model migration, liquidity edits, claims, fees, and social acts as separate candidates
only when their source semantics are trustworthy.

## 15. Kyle — pp. 290–297

One informed trader selects volume against a competitive maker who observes only total informed
plus noise flow. Gaussian linear equilibrium yields permanent linear impact with
`Λ=σ_F/(2Σ_V)` [Eq. 15.7]. It captures the intuition that noise flow supplies camouflage/liquidity
and impact constrains informed profit.

**Failures.** No sign memory, linear permanent scale-independent impact, terminal fundamental value,
and conflict with square-root data [pp. 295–296].

**JOSHI read.** Keep adverse-selection intuition; reject Kyle lambda as a universal AMM parameter.

## 16. Spread determinants — pp. 298–318

Glosten–Milgrom quotes compensate adverse selection and can cease to exist when informed flow is
too toxic [Secs. 16.1.1–16.1.4]. Metaorder fair-pricing links average execution and permanent impact
[Secs. 16.1.6]. MRR removes the terminal time and makes price respond to sign surprises, predicting
`R(ℓ)=s[1-C(ℓ)]/2` and a spread/volatility relation [Eqs. 16.18–16.23]. Empirical agreement is
useful but not exact [Sec. 16.3].

**JOSHI read.** Toxicity should be an outcome-conditioned provider risk measure, not a moral label
for a wallet. LP liquidity can vanish or reprice together under perceived risk.

## 17. Market-making profitability — pp. 319–332

The chapter computes provider P&L as spread income minus response/adverse selection under inventory
control [Eq. 17.12]. Slow and fast inventory policies expose different response horizons. Empirical
examples show naïve making negative; large-tick profitability concentrates at top priority and is
sensitive to rebates [Figs. 17.1–17.3].

**JOSHI read.** Meteora analysis must reconcile fees with inventory conversion, withdrawal, route
liquidation, rebalancing cost, and missed alternatives. “Fees earned” is not LP profit.

## 18. Latent liquidity — pp. 337–353

Visible books renew faster than large parent orders, so the chapter models unexpressed intentions as
diffusing, arriving, and cancelling around a reference price [Eq. 18.4]. Frequent clearing truncates
crossing intentions and yields V-shaped marginal liquidity near price [Fig. 18.5]. Locally linear
density implies quadratic cumulative supply/demand and motivates square-root impact [Sec. 18.5].

**JOSHI read.** On-chain reserves are not the whole future supply curve. But inferring latent
intentions requires a model; do not store them as wallet facts.

## 19. Continuous-auction nonlinear impact — pp. 354–365

The latent order book becomes a reaction–diffusion system. A signed metaorder source gives a
self-consistent nonlinear price equation [Eq. 19.7]; the small-rate limit recovers a linear
inverse-square-root propagator and the nonlinear regime gives square-root peak impact
[Eqs. 19.8–19.9]. Closed uninformed loops have nonnegative expected cost [Sec. 19.5]. The authors
list decay, speed-dependence, granularity, and strategic-behavior mismatches [Sec. 19.6].

**JOSHI read.** Valuable simulator invariants and nonlinear baselines; poor direct map to discrete,
fee-bearing AMM transactions without a new derivation.

## 20. Information content of prices — pp. 366–380

The chapter contrasts rapid discovery of an external fundamental value with order-driven formation
through interacting agents. A self-referential error model shows how crowd feedback can overwhelm
weak correction and sustain mispricing [Eqs. 20.1–20.2]. The authors favor the order-flow view for
short/medium scales while acknowledging the debate remains unsettled [Secs. 20.3–20.4].

**JOSHI read.** In memecoins, social attention, platform ranking, and trader behavior may be the
object to predict. That does not make every narrative field causal or fundamental value meaningless
at all horizons.

## 21. Optimal execution — pp. 384–405

Execution has macro, meso, and micro decisions. Linear propagator costs yield variational schedule
problems [Eqs. 21.5–21.9]; adding risk or signal changes the optimum. Market orders exchange cost for
certainty; limit orders exchange immediacy for non-fill, opportunity, queue, and selection risk.
Historical insertion of phantom orders is “dodgy” because the omitted reaction can match the effect
being studied [p. 402].

**JOSHI read.** External manual execution can be reconciled exactly. Counterfactual entries/exits
need state reaction and uncertainty; a changed path cannot reuse the observed future unchanged.

## 22. Fairness and stability — pp. 406–421

Trend following, maker panic, deleveraging, and contagion transmit through impact and correlated
liquidity withdrawal [Sec. 22.1]. Regulatory tools change incentives and can create new adaptation
[Sec. 22.2]. The closing practical point is that the instantaneous price values only an
infinitesimal quantity; portfolio valuation should include liquidation impact [pp. 418–419].

**JOSHI read.** Full-size executable liquidation and correlated LP/source failure belong in the
primary exposure glass. A single green mark hides the exact risk the book is warning about.

## Appendix — pp. 422–440

Appendix A.1 bounds the principal NASDAQ sample. A.2 supplies transform machinery. A.3–A.4 clarify
volume-aware propagators and TIM/HDIM fitting. A.5 gives a second inventory-controlled maker
calculation whose MRR limit again breaks even [p. 434, Eq. A.57]. A.6 is the source symbol table.

**Extraction note.** The appendix contains some of the text layer's worst hat/prime/script-letter
substitutions. Use rendered equations for any implementation.

