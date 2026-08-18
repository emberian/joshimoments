# Forecast Protocol as an information mechanism

Status: dated external-mechanism note; read-only research; no endorsement, deposit, trading,
profitability, or execution-authority implication.

Research cutoff: **2026-08-17 America/New_York**.

## 1. Source boundary and current-status caveat

This note evaluates the public thesis around Joey Roth's Forecast Protocol:

> maximize information discovery per unit of capital, with a market acting as an inference
> machine.

The strongest primary/public sources found by the cutoff were:

- Base's 2026-04-08 cohort announcement, which identifies Joey Roth's then-stealth project as
  [a new leverage primitive for prediction markets](https://blog.base.org/introducing-base-batches-003-2);
- Forecast's [official public account](https://x.com/ForecastFDN) and
  [Joey Roth's public account](https://x.com/joeyroth), which state the leverage, LP, and
  information-discovery claims summarized below;
- Forecast's public [site](https://forecastprotocol.xyz/) and
  [2028-election preview](https://2028election.forecastprotocol.xyz/); and
- Base's separate discussion of
  [conditional asset markets](https://blog.base.org/request-for-builders-1), useful for
  distinguishing conditional claims from raw probability contracts.

The official web applications returned an interactive Cloudflare challenge to noninteractive
retrieval during this study. Public posts described the recent election interface as an
interactive preview, stated that its current data were simulated, and said that real trading
access would follow for eligible wallets. No signup, wallet connection, deposit, or purchase was
made. No public protocol specification, inspectable contract repository, complete payout table,
or primary technical paper was found through the cutoff.

Therefore this note treats Forecast's public statements as **mechanism claims to test**, not as
evidence of live price discovery, solvency, LP neutrality, or superior forecasting. A later public
specification, deployment, or launch may supersede this note; any reuse must retain the cutoff.

## 2. What the public design claims establish

Forecast publicly describes:

1. exposure to changes in prediction-market probabilities at leverage advertised as `100x+`;
2. no **price-based** liquidation;
3. a pooled USDC capital source allocated across markets in response to leverage demand;
4. LP yield from that leverage demand;
5. LP capital described as not directionally exposed to which binary outcome resolves; and
6. an ambition to make Forecast the venue where probabilities are set and new information appears
   first.

The advertised example starts with a binary-contract price of `0.67`, moves it to `0.69`, and
shows approximately `60%` at `20x` or `300%` at `100x`. The arithmetic is consistent with
amplifying the underlying contract's approximate percentage move:

```math
\frac{0.69-0.67}{0.67}\approx 2.985\%,
\qquad 20\times\approx 59.7\%,
\qquad 100\times\approx 298.5\%.
```

That example demonstrates the advertised return transform. It does not disclose the complete
loss, funding, settlement, or capital-provider mechanics.

### 2.1 Exact public unknowns

The following questions prevent an H1 mechanism judgment:

| unknown | why it matters |
| --- | --- |
| authoritative index/reference-price source and sampling | determines whether Forecast forms a price or follows another venue |
| Forecast's own bid/ask, matching, AMM, or clearing rule | determines whether synthetic demand can reveal information internally |
| exact long/short payout across entry price, exit price, expiry, and resolution | determines trader maximum loss and the meaning of leverage |
| position-close and solvency rule replacing price liquidation | `no price-based liquidation` does not identify where loss is bounded |
| funding-rate calculation and payment path | determines incentives, forced transfers, and LP revenue |
| pool allocation, utilization caps, withdrawal rules, and failure waterfall | determines capital-time, correlated capacity, and liquidity risk |
| exact proof of outcome neutrality | resolution-label neutrality is weaker than pathwise or economic neutrality |
| external hedge, routing, and arbitrage path | determines whether Forecast contributes to another venue's price discovery |
| settlement oracle, dispute, cancellation, and ambiguous-resolution handling | determines terminal exposure and truth dependence |
| deployed contracts, upgrade authority, formal specification, and proof/code relation | determines what any audit or formal-verification claim actually covers |

Until these objects are public and replayable, `100x`, `no liquidation`, `neutral capital`, and
`information appears first` cannot be combined into one verified protocol claim.

### 2.2 What outcome-neutral cannot mean by slogan alone

An LP return that does not depend on the final label `YES` versus `NO` may still depend on:

- long/short imbalance and path;
- utilization and capital allocation;
- entry/exit basis and funding;
- oracle, contract, smart-contract, and cancellation risk;
- shared-pool concentration and correlated event resolution;
- withdrawal timing and unavailable liquidity; and
- tail losses or transfers that occur before resolution.

Outcome-label neutrality is not risk-free capital, delta neutrality at every state, or invariance
of full-liquidation value.

## 3. The inference-machine thesis must be decomposed

The causal chain is:

```text
external evidence
    -> information acquisition
    -> private belief
    -> action/order
    -> venue state and executable quotes
    -> routing/hedging/arbitrage
    -> public price revelation
    -> later outcome validation
```

Forecast plausibly relaxes a constraint at the **belief-expression** step: a trader may express
more price sensitivity with less personally posted collateral. That does not automatically improve
the other steps.

### 3.1 Information acquisition

Information is acquired through research, feeds, social observation, computation, privileged
facts, and cognition outside the trade itself. Leverage creates no new evidence. It can increase
the payoff to acquiring evidence, but it can amplify uninformed, recreational, manipulative, or
common-noise demand by the same mechanical factor.

The Grossman-Stiglitz result is the relevant constraint: when information acquisition is costly,
prices cannot be perfectly revealing while leaving no reward for acquiring information. See the
[official AEA paper](https://www.aeaweb.org/aer/top20/70.3.393-408.pdf). Information-acquisition
cost and trader collateral are related only through an incentive system; they are not one resource.

### 3.2 Price revelation

Private information becomes public only through a pricing institution. Kyle's model makes the
canonical dependence explicit: informed strategic flow, noise flow, market-maker inference, and
market depth jointly determine how information enters price. See
[Kyle 1985](https://doi.org/10.2307/1913210).

Leverage can improve revelation when informed actors were genuinely collateral-constrained and
their amplified actions affect an independent clearing price or produce attributable hedging flow
into a probability-setting venue. It does not improve revelation when Forecast merely marks a
synthetic exposure to an external index without feeding information back.

### 3.3 Actionability

A probability estimate may be informative yet untradeable at the relevant size after spread,
impact, fees, latency, MEV, refusal, and position constraints. Forecast quality and profit are not
interchangeable.

The 2026 primary paper
[When do prophets profit in prediction markets?](https://arxiv.org/abs/2607.06166) proves a
forecast-skill/profit relation for a particular proper betting construction when liquidity loss is
sufficiently controlled. It also supplies counterexamples where a better forecaster's intuitive
highest-margin trade loses, or an inaccurate forecast profits. JOSHI should retain that separation.

### 3.4 Outcome validation and probability semantics

Prediction-market prices can often approximate average beliefs, but exact equality depends on
risk preferences, wealth, belief distributions, contracts, and frictions. See
[Wolfers and Zitzewitz](https://www.nber.org/papers/w12200).

One binary realization does not reveal the event's ex-ante probability. Calibration and score
improvement require prospectively defined cohorts. Strictly proper scoring rules provide an
incentive-compatible evaluation language; see
[Gneiting and Raftery](https://doi.org/10.1198/016214506000001437).

The defensible meaning of *market as inference machine* is therefore:

> a mechanism that maps costly heterogeneous evidence, beliefs, preferences, budgets, and orders
> into public size-dependent quotes whose forecast properties can be evaluated later.

It does not mean that one displayed price is a pure Bayesian posterior.

## 4. Capital-time is one resource, not the denominator

For trader collateral, the wall-time integral

```math
K_{trader}=\int C_{trader}(t)\,dt
```

is meaningful when the asset, custody state, clock, and boundary are declared. The system resource
bundle is a vector:

```math
\mathbf K=(
  K_{trader},
  K_{LP},
  K_{hedge},
  K_{inventory},
  K_{tail},
  K_{attention},
  K_{data},
  K_{latency}
).
```

These components have different owners and not always the same units. A leveraged venue can make
`K_trader` small while moving collateral occupancy, inventory, and jump risk into the other
components. Dividing an information numerator only by posted trader margin allows leverage to win
the ratio mechanically even when system resources and discovered information are unchanged.

A scalarization

```math
K_\lambda=\sum_r\lambda_r K_r
```

requires explicit policy-dependent shadow prices `lambda_r`. It is not a market invariant. The
primary artifact should remain the information/resource Pareto frontier specified in
[`INFORMATION_CAPITAL_TIME.md`](INFORMATION_CAPITAL_TIME.md).

## 5. Information numerator

For a prospectively registered cohort of resolved binary markets, with a scoring convention in
which larger is better, one possible aggregate is:

```math
\Delta S
=\sum_j w_j\left[S(p^{post}_j,y_j)-S(p^{pre}_j,y_j)\right].
```

It requires a declared public baseline, availability cutoff, update interval, market cohort,
horizon, score, abstention rule, and coverage treatment.

Entropy reduction by itself is insufficient: becoming confidently wrong lowers entropy. Volume,
open interest, volatility, price movement, displayed depth, and trader PnL are not information
measures.

For JOSHI's memecoin domain there is generally no terminal binary truth. The estimand must name a
target such as:

- future executable return by direction, size, route, and horizon;
- liquidity survival, route loss, or liquidation capacity;
- launch/migration or creator transition;
- social/community state transition;
- runner/re-entry episode outcome; or
- operator decision quality under a complete witnessed choice set.

Calling a memecoin AMM price an event probability would violate the transfer limits of both the
microstructure corpus and this field model.

## 6. Operational estimands

| layer | operational candidate | essential qualification |
| --- | --- | --- |
| acquisition | held-out proper-score gain of a source/model/operator forecast over the same baseline without it | report operator time, data cost, coverage, and source availability |
| revelation | change in calibration/proper score after a new source event | source time and availability time are separate |
| revelation latency | time to a registered fraction of a stable supported price revision | the stable reference must not use future knowledge at decision time |
| permanent/transient response | immediate state-conditioned response versus registered later-horizon response | association is not caused impact without identification |
| actionability | fill probability times realized decision value net spread, impact, fees, latency, MEV, and refusal | use direction- and size-specific executable quotes, not marks |
| trader capital-time | asset-specific posted/reserved/in-flight/deployed collateral integral | do not infer system efficiency from this component alone |
| system capital-time | separately reported trader, encumbered LP, and hedge integrals | preserve owners, carriers, and nonadditivity |
| risk use | expected shortfall, jump loss, vault drawdown, and correlated exposure beside score/decision gain | never hide risk inside an APY or capital ratio |
| route contribution | Forecast-originated hedge/arbitrage notional reaching a probability-setting venue divided by Forecast synthetic notional | requires causal attribution, not same-window volume |
| price leadership | innovations first observed in Forecast that lead other venues and survive common-news controls | lead-lag is descriptive without a route mechanism |
| forced-flow share | outcome response associated with expiry, settlement, funding, closure, hedge, vault reallocation, or withdrawal | label mechanical flow separately from evidence-motivated action |
| shared-pool spillover | capacity, funding, or spread change in unrelated markets after demand/utilization shocks elsewhere | shared capital violates independent-market assumptions |
| scale dilution | forecast quality, executable capacity, attention burden, and tail correlation as breadth grows | use chronological breadth increments and retain cold-scope controls |

No row alone is `information efficiency`. A constrained decision may select a point on the
frontier, but the underlying vector remains inspectable.

## 7. Forced flow and routed liquidity

If Forecast truly has no price-based liquidation, it may remove one familiar feedback loop:

```text
adverse price move -> liquidation -> forced order -> further adverse move
```

That would be a meaningful mechanism property. It does not eliminate forced flow. Expiry,
resolution, voluntary closure, funding, hedging, pool allocation, LP withdrawal, capacity limits,
oracle changes, and cancellation can generate mechanically contingent flows or transfers that do
not encode newly acquired information.

The routed-liquidity hierarchy applies directly:

1. adding capital can mechanically change feasible exact-size quotes (`M0`);
2. another venue changes only if orders route there, hedges touch it, or arbitrage transmits state
   (`M1-M2`);
3. lower variance on one chart may reflect flow diversion rather than calmer aggregate execution;
4. internally netted synthetic exposure may consume an upstream price without contributing to it;
5. external hedging may transmit information, but can also import shocks, attract MEV, or
   synchronize exits; and
6. a shared vault creates cross-market topology even when market fundamentals are unrelated.

The minimum price stack for a Forecast study is:

```text
upstream canonical mark/index
Forecast mark/index
Forecast bid and ask by direction and exact size
aggregate best executable quote over the declared venue set
actual fill and full costs
settlement value
```

Those are different typed functionals. Calling all of them `the probability` erases the proposed
mechanism.

## 8. Falsifiers

### F1 — first-information claim

Falsified within the supported cohort if Forecast quote innovations lag, copy, or are fully
explained by its upstream index/common public event stream, with no independent held-out
calibration or revelation-latency gain.

### F2 — price-discovery contribution

Falsified if Forecast actions neither change an independently formed Forecast clearing price nor
produce attributable routing, hedge, or arbitrage flow into a probability-setting venue.

### F3 — leverage improves discovery

Falsified if added leverage raises volume, transient response, dispersion, or manipulation without
improving prospectively evaluated calibration/proper score or time to supported revelation.

### F4 — capital efficiency

Falsified if the apparent gain disappears when trader, encumbered LP, and hedge capital-time are
reported at equal notional and risk, showing only a transfer of the denominator.

### F5 — neutral LP capital

Falsified in its strong form if full-liquidation LP value or loss tails depend materially on
outcome direction, trader imbalance, path, utilization, oracle state, or correlated resolutions
after fees are separated.

### F6 — actionable information

Falsified if displayed innovations cannot be executed at preregistered directions and sizes, or if
net fill value vanishes after spread, impact, fees, latency, failure, and MEV.

### F7 — independent pooled markets

Falsified if utilization or withdrawals in one market alter capacity, funding, quote quality, or
failure probability in otherwise unrelated markets. This would not necessarily falsify the
protocol; it falsifies analysis that treats its markets as independent.

### F8 — transfer to JOSHI memecoin inference

Falsified if a binary probability ontology is required to obtain the result, because Pump,
PumpSwap, and Meteora prices do not settle to a common terminal truth claim.

## 9. Placement in the JOSHI hierarchy

| rung | Forecast question |
| --- | --- |
| **H0 settlement identities** | what collateral and settlement assets moved, and whether the declared boundary reconciles |
| **H1 protocol kinematics** | exact payout, funding, quote, pool, allocation, withdrawal, and settlement transitions |
| **H2 descriptive fields** | observed marks, executable quote surfaces, open interest, utilization, route flow, and resource occupancy |
| **H3 fitted operators** | acquisition value, revelation latency, response kernels, route transmission, score gain, and spillovers |
| **H4 latent/abductive objects** | private information, actor type, attention, manipulation, and inferred hedging motive |
| **H5 policy/controller** | capital allocation, trade, hedge, or attention policy under explicit constraints |

Forecast's current public information-discovery story is an H5 ambition resting on publicly
incomplete H1 semantics. JOSHI should borrow the decomposition and testable questions, not promote
the slogan into a constitutive law.

## 10. Decision boundary

The durable research objective is:

> maximize prospectively measured decision or proper-score improvement subject to explicit
> collateral, inventory, tail-loss, attention, data, latency, coverage, and actionability
> constraints.

This retains the useful intuition that markets can be engineered to aggregate evidence while
preventing leverage from gaming the denominator, price movement from impersonating knowledge, or
LP risk transfer from being described as discovered information.
