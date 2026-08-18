# Empirical claims and claim classes

## Classification discipline

The book is empirical in orientation, but it interleaves observations, definitions, exact
consequences of toy models, and broader interpretations. This file keeps them separate.

| tag | class | meaning |
| --- | --- | --- |
| **T** | conditional theorem/identity | Exact mathematical consequence once the displayed assumptions hold. It is not a theorem that real markets satisfy those assumptions. |
| **M** | model result | Analytical or simulated output of a specified model, often approximate or calibrated. |
| **E** | empirical evidence | Pattern reported for a named data set or literature surveyed by the book. |
| **H** | heuristic/interpretation | Mechanism, extrapolation, or practical inference proposed by the authors. |
| **J** | JOSHI hypothesis | New transfer candidate introduced by this corpus; no source-book evidence for the exact venue/process. |

The preface explicitly says the book does not present theorems about how markets *should* behave
[p. xv, PDF 16]. Here `T` is only a bookkeeping category for conditional mathematics.

## Source-data boundary

The book's core worked data are not a timeless market census:

- many LOB examples use PCLN, TSLA, CSCO, and INTC on NASDAQ during 2015, restricted to 10:30–15:00
  and excluding disrupted days [Table 4.1, p. 60; Appendix A.1, p. 422];
- some cross-sectional figures use 120 liquid US/NASDAQ stocks in 2015 [Figs. 4.11–4.12,
  pp. 71–72; Fig. 16.6, p. 315];
- Figure 12.2 uses nearly 500,000 proprietary futures metaorders from June 2007 through December
  2010 [p. 235];
- Figure 18.6 uses Bitcoin LOB snapshots every 15 minutes from May through September 2013
  [p. 351]; and
- several broad claims synthesize cited studies across equities, futures, FX, options, and Bitcoin
  rather than one common corpus.

JOSHI should preserve `market × venue × epoch × lifecycle × observation policy` on every analogous
estimate. “Universal” in the source is a research challenge, not an ingestion default.

## Empirical evidence

### E1 — heavy-tailed price changes

**Claim.** Return distributions have much fatter tails than a Gaussian random walk; extreme moves
are more frequent than the Gaussian benchmark [pp. 28–32, summary pp. 36–37].

**Evidence class.** Literature-level stylized fact illustrated by source data.

**Limits.** Tail exponent and stationarity vary with scale and regime. A memecoin lifecycle with
absorbing collapse, migration, and manipulation need not have one stable tail law.

### E2 — clustered activity and volatility

**Claim.** Intense and calm periods cluster; much high-frequency activity does not align one-to-one
with externally identified news [pp. 30–36].

**Evidence class.** Broad stylized fact plus author synthesis.

**Limits.** “No identified news” is not “no external cause.” Missing social/platform information can
make an exogenous process appear endogenous.

### E3 — nearly flat volatility signatures across scales

**Claim.** Empirical signature plots are close to flat across a broad frequency range, indicating
weak linear price-return predictability even though other statistics are nontrivial [pp. 23–27,
36–37].

**Limits.** The price definition and microstructure noise matter. AMM marginal prices, external
marks, and size-specific liquidation quotes can have different signatures.

### E4 — pronounced intraday seasonality

**Claim.** NASDAQ activity/volume has a J/U-shaped daily profile; spreads narrow after the open;
depth evolves differently for large- and small-tick stocks [pp. 59–62, Figs. 4.1–4.2].

**Sample.** Four focal NASDAQ stocks, 2015 restricted hours.

**Limits.** Solana is continuous and global. Relevant seasonality may follow geography, platform
features, creator schedules, US waking hours, or chain congestion rather than an exchange open.

### E5 — relative tick size organizes LOB regimes

**Claim.** Spread, best depth, trade size relative to depth, and volume profile vary strongly with
relative tick size [pp. 62–72, Figs. 4.3–4.12].

**Sample.** Four focal stocks plus a 120-stock cross-section for selected figures.

**Limits.** An AMM bin step or atomic precision does not reproduce queue priority or a one-tick
spread floor.

### E6 — displayed liquidity is small relative to daily flow

**Claim.** The instantaneous volume visible in a LOB is a small fraction of daily traded volume
[pp. 66–72, Table 4.1].

**Interpretive bridge.** The book argues this reveals much larger latent intentions [pp. 187–202,
337–338].

**Limits.** The visible/latent distinction is not identified by one ratio. For AMMs, on-chain
reserves can be visible while future order flow and LP edits remain latent.

### E7 — order arrivals and cancellations are not homogeneous Poisson flow

**Claim.** Events cluster and exhibit state/time dependence, contradicting the independent,
homogeneous order-flow assumption used by simple null models [pp. 63–66, 154–155, 163–184].

**Limits.** A Poisson process can remain a useful baseline. Rejection does not select Hawkes as the
causal truth.

### E8 — queue changes are not always small

**Claim.** A calibrated Fokker–Planck approximation improves when sweeping market orders/jumps are
represented explicitly; the small-increment assumption is better for large-tick queues than
small-tick ones [pp. 107–116, Table 6.1].

**Limits.** AMM trades routinely traverse nonlinear reserve/bin states; diffusion should not be the
default local approximation without scale checks.

### E9 — best-queue imbalance predicts the next local price direction

**Claim.** For the large-tick examples, `I=V_b/(V_a+V_b)` is strongly associated with which best
queue empties first [pp. 118–131, Figs. 7.2 and 7.5].

**Limits.** The result predicts one queue-depletion boundary, not multi-horizon return or profit.
The variable does not exist on a constant-product AMM.

### E10 — linear Hawkes fits often imply long kernels and near-critical feedback

**Claim.** Financial-event calibrations reviewed by the book often produce power-law memory and
feedback norm near the linear-model stability boundary `g=1` [pp. 173–184].

**Limits.** The book itself warns that criticality can be an artifact of a restrictive model trying
to represent long memory, and that two-point fit does not prove causal excitation [pp. 183–184].

### E11 — market-order signs have long memory

**Claim.** Signed market-order autocorrelation decays approximately as a non-summable power law over
long lags across several studied asset classes [pp. 187–192, Fig. 10.1].

**Limits.** Event definition, broker aggregation, hidden parent orders, and sample coverage matter.
Hot-scope selection can manufacture apparent persistence.

### E12 — order splitting dominates long-lag sign persistence in the reviewed identity data

**Claim.** Participant/broker-tagged evidence reviewed in the book attributes much long-lag
persistence to the same actor splitting a parent order; other actors may herd at short lags and
become contrarian at long lags [pp. 193–198].

**Limits.** A wallet is not a person, router, strategy, or independent actor. Memecoin social
herding may be more important than in institutional parent-order data.

### E13 — trade sign and subsequent price move are positively associated

**Claim.** Buy trades precede positive average price changes and sell trades precede negative ones;
lag-one response differs sharply for price-changing versus non-price-changing market orders
[pp. 208–225, Table 11.1].

**Limits.** This is observed impact. It does not identify how much motion the focal trade caused.

### E14 — single-order response is concave in size and state-conditioned

**Claim.** Larger market orders have larger average response, but the relation is concave; trade
size is selected against available liquidity, so large orders often arrive when depth can absorb
them [pp. 214–219, Figs. 11.3–11.5].

**Limits.** Conditioning on trade size alone confounds state selection. AMM exact-size curves are
known mechanically at one state, but landing and subsequent response remain endogenous.

### E15 — same-direction predictability is buffered by liquidity

**Claim.** Two same-direction trades have less than twice the unconditional impact of one; expected
same-sign orders face less marginal impact than surprising/opposite events [pp. 219–221, 278–285].

**Interpretation.** The book calls the mechanism asymmetric liquidity.

**Limits.** Direct causal adaptation is not observed solely from conditional responses. In AMMs,
arbitrage, fee tiers, routing, and reserve geometry can create other asymmetries.

### E16 — metaorder peak impact is broadly concave and near square-root

**Claim.** Across literature and the nearly 500,000-metaorder futures example, normalized peak
impact is well described by `Y σ_T (Q/V_T)^δ` with `δ` around one-half over a substantial domain
[pp. 233–239, Eq. 12.6, Fig. 12.2].

**Limits.** The authors enumerate selection, signal, duration, and data-resolution biases
[pp. 236–239]. The law concerns parent orders, not arbitrary aggregation windows.

### E17 — impact paths and decay are not instantaneous

**Claim.** Average impact grows during execution, falls after completion, and may retain a slow
long-run component; the exact permanent/transient separation is difficult [pp. 230–242,
Fig. 12.1].

**Limits.** Metaorder end times are often hidden; market conditions evolve; social attention can
alter the post-trade path.

### E18 — propagator kernels fitted from response/sign data decay slowly

**Claim.** For the four NASDAQ examples, fitted bare kernels decay roughly as a power law while
observed response stays comparatively flat/saturating [pp. 253–258, Fig. 13.1].

**Limits.** Kernel inversion is sensitive to finite samples and model misspecification. A fitted
kernel is reduced-form, not mechanical truth.

### E19 — multi-event histories reveal stabilizing liquidity response

**Claim.** Event-type models indicate that market orders, limit orders, and cancellations respond
to one another; expected same-sign pressure is partially offset by subsequent liquidity provision
[pp. 270–285].

**Limits.** Requires dense event-resolved LOB data and stable event meanings. Pump/AMM event classes
must be reconstructed from protocol state, not copied from Table 14.1.

### E20 — spread and lagged response are of comparable scale

**Claim.** The MRR relation between response, sign autocorrelation, spread, and per-trade volatility
is surprisingly close in the book's equity tests despite model simplicity [pp. 309–316,
Figs. 16.3–16.6].

**Limits.** A spread floor, anonymous market orders, and centralized matching are model context.
AMM round-trip cost has different components.

### E21 — naïve market-making is not free spread capture

**Claim.** Simple inventory-controlled electronic market-making strategies in the book's examples
are negative or near break-even after adverse price response; top queue priority and rebates matter
for large-tick stocks [pp. 319–330, Figs. 17.1–17.3].

**Limits.** Sample and fee schedule are historical. The transferable claim is the P&L decomposition,
not the numerical result.

### E22 — a visible Bitcoin book showed locally linear depth in 2013

**Claim.** Fifteen-minute Bitcoin snapshots from May–September 2013 showed a locally linear mean
volume profile near price, yielding quadratic cumulative depth [pp. 350–351, Fig. 18.6].

**Interpretation.** The authors treat that young market's visible book as an unusually good proxy
for latent supply/demand.

**Limits.** This proxy claim is not observed directly and is especially unsafe for current AMMs.

### E23 — simple liquidity provision is highly competitive

**Claim.** Market- and typical limit-order costs are roughly comparable absent short-term signals;
limit profitability depends on priority and accurate local state [pp. 329–330, 394–403].

**Limits.** “Roughly equivalent” is an equilibrium tendency, not a per-trade identity. Retail
latency, rebates, MEV, and failure change the attainable set.

## Conditional theorems and identities

### T1 — Hawkes stationary mean

For a linear Hawkes process with nonnegative integrable kernel norm `g<1`,
`bar(ϕ)=ϕ₀/(1-g)` [p. 168, Eqs. 9.12–9.13]. If `g≥1`, this stationary solution does not exist.

This says nothing by itself about the stability of a real market fitted with a misspecified Hawkes
model.

### T2 — response decomposition

Given the definitions and common pre-action information set,
`I_obs=I_react+I_pred` [pp. 210–211, Eq. 11.4]. This is a causal bookkeeping identity. The two
unobserved components are not identified by one realized history.

### T3 — long-memory/propagator diffusive balance

In the stationary linear propagator model with power-law sign memory and kernel decay, diffusive
variance requires `β=(1-γ)/2` [p. 256, Eq. 13.17]. Change the model, price process, or stationarity
and the condition can fail.

### T4 — MRR response restriction

Inside the simplest MRR model with `s=2G*`,
`R(ℓ)=s[1-C(ℓ)]/2` [p. 310, Eq. 16.22]. This is useful precisely because it is falsifiable.

### T5 — closed-loop nonnegative cost in the latent-liquidity model

Under the Chapter 19 impact equation and a zero-net-volume trajectory with no predictive signal,
expected impact cost is nonnegative [pp. 361–362]. This is a model-consistency property, not a
general no-arbitrage proof for every venue.

## Model results that must not be quoted as facts

| model result | source | fragile assumptions |
| --- | --- | --- |
| Constant-rate queues become critical near equal birth/death rates and have broad depletion times. | Ch. 5, pp. 80–88 | unit events, Poisson independence, one queue, fixed reinjection |
| Per-order cancellation creates a stationary Q-CIR-like queue around `V*`. | Ch. 5, pp. 89–98 | linear total cancellation, diffusion limit, state-independent arrivals/executions |
| A calibrated 2-D diffusion can approximate large-tick best queues. | Chs. 6–7 | small increments, selected decorrelation interval, correct jump/reinjection model |
| Santa Fe zero-intelligence flow generates spread/volatility/impact but misses correlated adaptive flow. | Ch. 8 | homogeneous independent Poisson mechanisms and stylized placement/cancel rules |
| A DAR copying kernel can reproduce sign autocorrelation. | Sec. 10.4.2 | model construction, not participant mechanism |
| Kyle impact is linear/permanent with `Λ=σ_F/(2Σ_V)`. | Ch. 15 | one informed trader, noise traders, competitive linear maker, Gaussian/terminal setup |
| Glosten–Milgrom spread compensates adverse selection. | Sec. 16.1 | terminal value, maker knows mixture, break-even competition, stylized order choice |
| V-shaped latent liquidity produces square-root nonlinear impact. | Chs. 18–19 | latent-density dynamics, local linearity, many infinitesimal intentions, stable parameters |
| One exponential propagator yields boundary blocks plus constant-rate optimal execution. | p. 388, Eqs. 21.7–21.9 | linear symmetric kernel, fixed `Q,T`, no venue/landing state, specified cost only |

## Heuristics and author interpretations

### H1 — most short-/medium-term variance is endogenous

The book cites activity/volatility feedback models suggesting a very large endogenous share and
argues that short-/medium-term price dynamics are dominated by self-reference [p. 36]. This is an
author synthesis, not one directly measured invariant. The exogenous boundary changes with data
coverage.

### H2 — liquidity taking and provision form a stabilizing tit-for-tat

The multi-event evidence and propagator consistency motivate a feedback picture in which providers
offset predictable taker flow [pp. 284–285]. Useful mechanism; not a guarantee during crises or on
AMMs.

### H3 — the order-flow view explains more puzzles than the fundamental-value view

Chapter 20 favors price formation through interaction over rapid discovery of a pre-existing true
price [pp. 366–376]. It presents this as a scientific position supported by accumulated puzzles,
not a settled theorem.

### H4 — modern liquidity providers can become correlated exactly when needed most

The book argues that many providers use similar volatility/activity/trend risk indicators and can
withdraw together [p. 418]. This is a systemic interpretation with direct relevance to LP crowding,
but requires current venue evidence.

### H5 — instantaneous marks are unsafe for large portfolios

Impact-adjusted valuation should haircut large positions because the current price only values an
infinitesimal trade [pp. 418–419]. The general conclusion is compelling; the book's numerical
example is not a memecoin haircut rule.

## JOSHI hypotheses generated, not inherited

| ID | hypothesis | prospective falsifier |
| --- | --- | --- |
| J1 | Signed AMM trade flow has lifecycle-conditional persistence partly attributable to repeated wallets/routers. | Little or unstable out-of-sample persistence after coverage, routing, and wallet clustering controls. |
| J2 | Expected same-direction AMM trades have different marginal/post-trade impact from surprising trades after conditioning on exact state. | No stable response difference beyond deterministic reserve geometry and fees. |
| J3 | Social/callout/creator events change trade intensity over multiple time scales. | Held-out intensity forecasts do not improve over seasonal/state baselines; event-time associations vanish after common-cause controls. |
| J4 | Meteora LP fee income is offset by adverse inventory conversion around one-sided flow, analogous economically to market-maker selection. | Reconciled prospective LP paths retain net advantage after withdrawal/liquidation, rebalancing, network, and opportunity costs across regimes. |
| J5 | A crackle's attainable edge depends more on state-conditioned quote/fill response than on chart microdip shape alone. | Shape-only policy retains independent net performance after exact quote, latency, fee, and state controls. |
| J6 | Partial exit plus runner can improve the joint distribution of realized cash and retained convex exposure for some dispositions. | Prospectively declared partial policies are dominated by attainable full-exit/hold baselines after all costs and residual liquidation. |
| J7 | Full-size liquidation and impact-adjusted exposure change Ember's decisions relative to marginal marks. | Natural-use study finds no material decision changes and negligible mark/quote gaps for scoped positions. |

These hypotheses justify instrumentation and bounded studies. None authorizes a trading policy.

