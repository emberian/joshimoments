# Formal model

## Scope and formalization stance

The book is a sequence of compatible but non-identical models. This document does not pretend they
form one closed axiom system. It extracts a **typed dependency graph**: which observable objects are
defined, which assumptions enter each model, which quantities are inferred, and which conclusions
are identities, model results, or empirical regularities.

All equations are rewritten in consistent notation but retain the book's equation identifier and
printed-page reference. A formula marked **verified** was checked against a page render. A formula
is not evidence that its assumptions hold for JOSHI.

## 1. Domains, indices, and clocks

### 1.1 Indices

- `t,u`: calendar time unless the local model explicitly uses discrete event time.
- `n,k`: event/trade index.
- `τ`: wall-time or model lag.
- `ℓ`: discrete event-time lag.
- `T`: execution/metaorder horizon.
- `i`: agent, asset, or event subtype according to context.

JOSHI must type these separately. A Solana slot, transaction index, instruction index, source event
time, receive time, render time, operator gesture time, and finality time cannot inhabit one generic
timestamp.

### 1.2 Price and volume domains

For the LOB source model:

```text
b_t  = best bid
a_t  = best ask
s_t  = a_t - b_t                         spread
m_t  = (a_t + b_t)/2                     mid-price
p_t  = transaction price
V_b,t, V_a,t                             best-queue volumes
ε_n ∈ {-1,+1}                            sell/buy market-order sign
υ_n ≥ 0                                  child-order volume
```

These are definitions, not empirical claims [pp. 44–51]. In an AMM, `a_t`, `b_t`, and queue
volumes may not exist. A future cross-venue formalization needs an abstract `PriceObservation`
whose subtype is one of `lob_mid`, `pool_marginal`, `size_quote`, `fill_average`, or `external_mark`.

### 1.3 Event and information filtrations

Let `F_t` denote information available immediately before the focal action. The book uses this
implicitly or explicitly when separating prediction from reaction [pp. 210–211, Eqs. 11.1–11.4].
For JOSHI, the filtration must be materialized as an eligible evidence manifest:

```text
F_t^known = observations available by cutoff t
            + source health and coverage by t
            + operator-visible scene by t
            - later corrections, outcomes, and mutable metadata
```

This is a causal-data contract, not a claim that the filtration is complete.

## 2. Price statistics

### Definition P1 — variogram

For a price process `p_t`,

```math
\mathcal V(\tau) := \mathbb E[(p_{t+\tau}-p_t)^2].
```

For a diffusive random walk, `V(τ)=Dτ` [p. 24, Eq. 2.1; verified]. This linearity is a model
benchmark. Empirical price series need not be Gaussian even when the variogram is close to linear.

### Definition P2 — return autocorrelation and signature volatility

For zero-mean stationary normalized increments `r_t` with variance `σ_r²`,

```math
C_r(\tau) := \frac{\mathbb E[r_t r_{t+\tau}]}{\sigma_r^2},
\qquad
\sigma^2(\tau) := \frac{\mathcal V(\tau)}{\tau\bar p^2}.
```

[pp. 24–25, Eqs. 2.6 and 2.8; verified]. The signature curve rises with net positive serial
dependence and falls with net mean reversion under the chapter's stationary additive setup
[pp. 25–26, Eq. 2.9 and Fig. 2.1].

### Model result P3 — statistical efficiency is weaker than fundamental efficiency

Nearly zero linear return predictability can coexist with fat tails, volatility clustering, excess
volatility, and prices far from a fundamental benchmark [pp. 33–37]. Therefore:

```text
uncorrelated returns  !=  IID returns
uncorrelated returns  !=  Gaussian returns
uncorrelated returns  !=  correct fundamental valuation
```

This distinction is foundational for JOSHI: a weak price-direction predictor does not show that the
attention/management process lacks structure.

## 3. LOB state and queue dynamics

### Definition Q1 — imbalance

For best queues,

```math
I_t := \frac{V_{b,t}}{V_{b,t}+V_{a,t}}.
```

The book studies the probability that the ask depletes first as a function of `I` [pp. 118–131,
especially Figs. 7.2 and 7.5]. This object is undefined for a venue without two standing best
queues.

### Model Q2 — unit birth–death queue

Assume unit orders, independent Poisson limit arrivals at rate `λ`, market executions at rate `μ`,
and cancellations at rate `ν` independent of queue size. For `V≥1`:

```math
V\to V+1 \text{ at rate }\lambda,
\qquad
V\to V-1 \text{ at rate }\mu+\nu.
```

[p. 80, Eq. 5.1; verified]. With immediate reinjection after depletion, the queue-length
distribution satisfies

```math
\partial_t P(V,t)=-(\lambda+\mu+\nu)P(V,t)
 +\lambda P(V-1,t)+(\mu+\nu)P(V+1,t)+J(t)\pi(V).
```

[p. 81, Eq. 5.2; verified]. `π(V)` is the newborn-queue distribution and `J(t)` the depletion/
reinjection flux.

Assumptions are intentionally severe: unit size, independent homogeneous arrivals, one queue, and
an imposed reinjection rule. The stationary condition requires that growth not dominate shrinkage.

### Model Q3 — state-dependent cancellation and Q-CIR limit

If cancellation is per order, total cancellation is `νV`. In the continuum approximation:

```math
\partial_tP \approx -\partial_V(F(V)P)+\partial^2_{VV}(D(V)P),
```

with

```math
F(V)=\lambda-\mu-\nu V,
\qquad
D(V)=\frac{\lambda+\mu+\nu V}{2},
\qquad
V^*=\frac{\lambda-\mu}{\nu}.
```

[p. 94, Eqs. 5.45–5.46; verified]. This provides mean reversion toward `V*` and can generate rare
queue depletions when the potential barrier is large. The book labels the diffusion a modified CIR
or Q-CIR process.

### Model Q4 — empirically calibrated Fokker–Planck coefficients

Given a conditional distribution of queue changes over a decorrelation interval `τ_c`,

```math
F(V)=\frac{1}{\tau_c}\sum_{\delta V}\delta V\,P(\delta V\mid V),
\qquad
D(V)=\frac{1}{2\tau_c}\sum_{\delta V}(\delta V)^2P(\delta V\mid V).
```

[p. 105, Eq. 6.8; verified]. The second-order Kramers–Moyal truncation requires changes small
relative to the state and higher conditional moments negligible at the selected scale. Sweeping
orders violate this approximation and require jump/reinjection terms [pp. 104–115].

### Model Q5 — coupled best queues

The bid/ask state `V=(V_b,V_a)` can be approximated by a two-dimensional Fokker–Planck equation
with drift vector `F(V)` and diffusion matrix `D(V)` [pp. 127–128, Eqs. 7.11–7.12]. Even with zero
off-diagonal diffusion, the queues remain coupled if each drift/variance depends on both volumes.

### Empirical result Q6 — imbalance predicts a local boundary event

For the large-tick NASDAQ examples, queue imbalance predicts which best queue empties first, but a
purely diffusive independent-queue model produces the wrong functional curvature. Moderate drift
relative to diffusion improves the shape [pp. 119–131, Figs. 7.2, 7.5, and 7.6]. This is a specific
one-boundary-event result, not a general directional alpha theorem.

## 4. Event clustering

### Definition H1 — point-process intensity

For counting process `N(t)`, the conditional intensity `ϕ(t)` is the instantaneous expected event
rate given the history. A homogeneous Poisson process has constant `ϕ`; an inhomogeneous process
permits deterministic time variation [pp. 164–166].

### Model H2 — linear Hawkes intensity

```math
\phi(t)=\phi_0(t)+\int_{-\infty}^{t}\Phi(t-u)\,dN(u)
       =\phi_0(t)+\sum_{t_i<t}\Phi(t-t_i),
```

where `Φ≥0` is the influence kernel [pp. 166–167, Eqs. 9.10–9.11; verified]. For constant base
intensity, define

```math
g:=\int_0^\infty \Phi(u)\,du.
```

Stationarity in the linear model requires `g<1`, and then

```math
\bar\phi=\frac{\phi_0}{1-g}.
```

[p. 168, Eqs. 9.12–9.13; verified]. This is a model stability condition, not evidence that an
estimated market process literally branches.

### Model result H3 — covariance identifies a linear Hawkes kernel only within the model class

The rescaled intensity covariance and kernel obey a Yule–Walker/Wiener–Hopf relation [p. 169,
Eq. 9.15]. Thus first- and second-order statistics determine a linear Hawkes specification.
However, the same two-point statistics do not establish time-directed causality; the book states
this limitation explicitly [pp. 169 and 184].

### Model extension H4 — price/activity feedback

The book sketches a nonlinear intensity containing both linear event excitation and squared trend
feedback [p. 183, Eqs. 9.36–9.37]. Small price-feedback terms can create fat-tailed intensity where
a pure linear Hawkes model cannot. JOSHI should treat this as a candidate interaction topology,
not copy its parametric form before measurement.

## 5. Persistent signed flow

### Definition O1 — sign autocorrelation

For balanced signs `ε_n∈{-1,+1}`,

```math
C(\ell):=\mathbb E[\epsilon_n\epsilon_{n+\ell}].
```

The empirical long-memory regime is described as

```math
C(\ell)\sim c_\infty\ell^{-\gamma},\qquad 0<\gamma<1,
```

which is non-summable [p. 188, Eq. 10.2 and surrounding text].

### Model O2 — discrete autoregressive copying

A DAR process selects a past lag from distribution `K(ℓ)` and copies/anti-copies that sign. Its
autocorrelation satisfies

```math
C(\ell)=(2p-1)\sum_{n\ge1}K(n)C(\ell-n),\qquad C(0)=1,
```

and its next-sign conditional mean is a linear weighted history [p. 194, Eqs. 10.6–10.7]. The
construction can represent persistence; it does not decide whether the mechanism is herding or
order splitting.

### Model O3 — LMF metaorder splitting

In the stylized Lillo–Mike–Farmer construction, a population of long-lived parent metaorders emits
same-sign child orders. If parent durations have a tail controlled by exponent `ζ`, sign memory
decays with

```math
\gamma=\zeta-1.
```

[pp. 194–197, especially p. 197]. The book argues that participant-tagged data supports splitting
as the main source of long-lag persistence in traditional markets, with short-lag herding also
possible [pp. 197–198]. The attribution is empirical and venue-dependent.

### Constraint O4 — efficiency paradox

Persistent signed flow plus constant permanent same-sign impact would generate predictable,
super-diffusive prices. Therefore at least one must adapt:

```text
impact magnitude/history
liquidity state
opposite event flow
information/noise contribution
or the assumption of price diffusivity
```

[pp. 191–202]. This constraint motivates the propagator and asymmetric-liquidity models.

## 6. Impact as a causal and statistical object

### Definition I1 — reaction, observed, and prediction impact

Given pre-action information `F_t`, define reaction impact as the difference between matched worlds
with and without the focal execution:

```math
I^{react}_{t+\ell}
=\mathbb E[m_{t+\ell}\mid execute_t,F_t]
-\mathbb E[m_{t+\ell}\mid no\ execute_t,F_t].
```

Observed impact is

```math
I^{obs}_{t+\ell}
=\mathbb E[m_{t+\ell}\mid execute_t]-m_t,
```

and prediction impact is the no-execution drift implied by the trader's information:

```math
I^{pred}_{t+\ell}
=\mathbb E[m_{t+\ell}\mid no\ execute_t,F_t]-m_t.
```

The bookkeeping identity is

```math
I^{obs}=I^{react}+I^{pred}.
```

[pp. 210–211, Eqs. 11.1–11.4; verified]. Only observed impact is directly available from one
history. Historical replay cannot produce the mutually exclusive counterfactual.

### Definition I2 — signed response

```math
\mathcal R(\ell):=\mathbb E[\epsilon_n(m_{n+\ell}-m_n)].
```

This is an observed conditional association, not reaction impact. Conditioning on volume, state,
previous signs, and price-changing status changes its meaning [pp. 212–224].

### Empirical result I3 — market-order response and spread share a scale

In the NASDAQ sample, lag-one response for small-tick stocks is proportional to the mean spread;
price-changing and non-price-changing market orders have sharply different responses [pp. 213–221,
Table 11.1 and Figs. 11.1–11.6]. The book interprets this through competitive compensation of
liquidity providers, with large-tick cases requiring explicit queue mechanics.

### Empirical model I4 — square-root metaorder impact

For parent volume `Q` executed over horizon `T`, contemporaneous market volume `V_T`, volatility
`σ_T`, and coefficient `Y`:

```math
I^{peak}(Q,T)\approx Y\sigma_T\left(\frac{Q}{V_T}\right)^\delta,
\qquad \delta\approx\tfrac12.
```

[p. 234, Eq. 12.6; verified]. The book reports `δ` roughly 0.4–0.7 across reviewed data, with the
square-root description supported across multiple mature asset classes and market structures
[pp. 233–239, Fig. 12.2]. This is an empirical scaling law, not a theorem and not automatically an
AMM law.

### Model result I5 — impact path and execution shortfall

If the partial impact path itself follows square-root scaling in executed fraction, then mean
impact-induced shortfall per unit quantity is about two-thirds of peak impact [pp. 240–241,
Eqs. 12.10–12.11; verified]. The coefficient depends on the assumed path; it is not an accounting
identity for arbitrary execution.

## 7. Propagator and history-dependent liquidity

### Model G1 — linear transient impact

```math
m_t=m_{t_0}+\sum_{t_0\le n<t}G(t-n)\epsilon_n
                 +\sum_{t_0\le n<t}\xi_n,
```

where `G(ℓ)` is the lagged reaction kernel and `ξ` residual price movement [p. 252, Eq. 13.7]. With
`K(ℓ)=G(ℓ+1)-G(ℓ)`, returns are

```math
r_t=G(1)\epsilon_t+\sum_{n<t}K(t-n)\epsilon_n+\xi_t.
```

[pp. 252–253, Eqs. 13.8–13.9; verified].

### Model result G2 — response is not the bare kernel

Signed-flow correlation adds the effect of correlated predecessors and descendants, so generally
`R(ℓ)≠G(ℓ)` [p. 253, Eq. 13.10]. Estimating mechanical impact from a simple post-trade mean response
is therefore structurally wrong even inside the model.

### Model constraint G3 — long-range resilience

If signs have `C(ℓ)∼ℓ^{-γ}` and the impact kernel has `G(ℓ)∼ℓ^{-β}`, a diffusive critical balance
in the linear model requires

```math
\beta_c=\frac{1-\gamma}{2}.
```

[p. 256, Eq. 13.17; verified]. Slower decay gives super-diffusion; faster decay gives mean
reversion under the model assumptions. This is a consistency relation, not proof that actual
resilience uses one power law.

### Model G4 — history-dependent impact

An alternative representation lets current impact depend on the predictability/surprise of the
event rather than assigning one decaying effect to every historical event [pp. 259–261]. The two
views can coincide under special event models, but the multi-event extension shows that transient
impact models form only a restricted subclass of history-dependent impact models [pp. 275–285,
Eqs. 14.11–14.14].

### Model result G5 — asymmetric liquidity

Empirically fitted multi-event histories indicate that past same-sign events reduce the impact of a
future same-sign price-changing event, while opposite-sign histories can increase it [pp. 278–285].
The book calls this stabilizing adaptation asymmetric liquidity. Its failure is a candidate crisis
mechanism, not an always-valid trading signal.

## 8. Adverse selection, spread, and provider P&L

### Model K1 — Kyle's linear impact coefficient

In the one-period Gaussian Kyle model, informed-value uncertainty `σ_F` and noise-flow scale
`Σ_V` imply

```math
\Lambda=\frac{\sigma_F}{2\Sigma_V}.
```

[p. 293, Eq. 15.7; verified]. The result depends on a competitive market maker, one informed
trader, Gaussian noise, linear pricing, and a terminal value. The book later rejects linear,
permanent, scale-independent impact as empirically inadequate [pp. 295–296].

### Model M1 — MRR surprise dynamics

In the Madhavan–Richardson–Roomans model,

```math
p_{F,t}-p_{F,t-1}=G^*(\epsilon_t-\hat\epsilon_t)+\xi_t,
\qquad
\hat\epsilon_t=\mathbb E_{t-1}[\epsilon_t].
```

[p. 309, Eq. 16.18; verified]. Competitive conditional quotes yield constant spread `s=2G*` in
the simplest case and the response relation

```math
\mathcal R(\ell)=G^*(1-C(\ell))=\frac{s}{2}(1-C(\ell)).
```

[p. 310, Eq. 16.22; verified]. The model also predicts an affine relation between long-run
per-trade variance and squared spread [p. 311, Eq. 16.23]. These are falsifiable model restrictions,
not definitions.

### Economic decomposition M2 — provider break-even

Across Chapters 16–17, liquidity-provider value has the schematic form

```text
provider P&L
= spread/rebate/fee capture
- adverse post-fill price response
- inventory and liquidation cost
- priority/opportunity/operating cost.
```

The book's inventory-control approximation expresses the selection term as a response-kernel/
sign-correlation weighted cost [p. 325, Eq. 17.12; verified]. In the MRR benchmark the components
balance exactly; the NASDAQ examples suggest naïve market making is negative, top queue priority
can be valuable for large-tick stocks, and random priority roughly breaks even after then-current
rebates [pp. 327–330, Figs. 17.1–17.3].

This decomposition transfers conceptually to LPs; the formula does not.

## 9. Latent liquidity and nonlinear impact

### Model L1 — marginal intention densities

Let `ρ⁺(x,t)` and `ρ⁻(x,t)` be marginal latent demand and supply at relative price
`x=p-p_F`. Between clearing events the model assumes diffusion of reservation prices, cancellation,
and new intention arrival:

```math
\partial_t\rho^\pm(x,t)
=D\,\partial_{xx}^2\rho^\pm(x,t)-\nu^\pm(x)\rho^\pm(x,t)+\lambda^\pm(x).
```

[p. 342, Eq. 18.4; verified]. These are latent intention densities, not visible book depth.

### Model result L2 — V-shaped marginal liquidity under frequent clearing

In the continuous-clearing limit, the stationary buy/sell densities vanish linearly near the
transaction price, with slope `L`, giving a V-shaped marginal-liquidity profile [pp. 345–350,
Eqs. 18.13–18.18 and Fig. 18.5]. Figure 18.6 supplies a 2013 Bitcoin visible-book analogue, under
the authors' argument that this young market revealed an unusually large fraction of intentions
[pp. 350–351].

### Model L3 — nonlinear latent-order-book equation

Let `χ=ρ⁺-ρ⁻`, let `j(t)` be signed metaorder flux, and let `x*(t)` be transaction price relative to
the reference. In the locally linear, short-horizon limit, the price satisfies the self-consistent
equation

```math
\mathcal L x^*(t)
=\int_0^t\frac{j(u)}{\sqrt{4\pi D(t-u)}}
  \exp\!\left[-\frac{(x^*(t)-x^*(u))^2}{4D(t-u)}\right]du.
```

[p. 357, Eq. 19.7; verified]. Assumptions include stationary initial latent liquidity, local
linearity, small enough displacement, no strategy-induced parameter change, infinitesimal order
granularity, and negligible new/cancelled intentions over the impact horizon.

For sufficiently small trading rate, this reduces to a linear inverse-square-root propagator
[p. 358, Eq. 19.8]. For constant-rate execution, the nonlinear regime recovers a square-root impact
form [p. 358, Eq. 19.9; verified].

### Model result L4 — no mechanical closed-loop profit

The chapter represents expected cost of any closed, zero-information trading trajectory as a
non-negative quadratic form, hence `C≥0` [pp. 361–362]. This is a desirable simulator invariant:
an impact model that produces expected profit from a fee-free uninformed round trip is structurally
suspect. It does not imply that all real closed loops lose, because predictive information and
external state changes are excluded from the proposition.

### Model limitations L5

The authors list unresolved mismatches: the model's `β=1/2` decay is too mean-reverting relative to
observed sign memory; the predicted low-participation prefactor depends too much on trading speed;
order granularity is omitted; and strategic behavior is weak [pp. 362–364]. These limitations are
part of the formal model, not footnotes to discard.

## 10. Self-referential prices

### Model S1 — heterogeneous forecast error with crowd feedback

Agent `i` updates a pricing error `δ_t^i` using private error correction, the market's average
mispricing, idiosyncratic noise, and heterogeneous response to news [p. 373, Eqs. 20.1–20.2;
verified]. Aggregation can yield multiple regimes: stable correction, persistent mispricing, and
bifurcation when self-reference overwhelms correction [pp. 372–375].

The transfer is structural: social actors can use other actors' behavior as information, creating
feedback and weak anchors. The specific polynomial model is not a memecoin-price law.

## 11. Execution as a constrained control problem

### Definition E1 — three execution scales

The book distinguishes:

1. macro: desired quantity and horizon;
2. meso: schedule within the horizon; and
3. micro: venue and market-versus-limit order choice.

[pp. 384–385 and 402–403]. JOSHI adds a prior scale: whether to enter/exit/re-enter at all, which is
operator policy rather than execution of a fixed metaorder.

### Model E2 — linear-propagator schedule

For signed trading rate `j(t)`, symmetric linear impact kernel `G`, and total quantity constraint
`∫₀ᵀj(t)dt=Q`, expected impact cost is quadratic:

```math
\mathbb E[C_{impact}]
=\frac12\int_0^T\int_0^T j(t)G(|t-t'|)j(t')\,dt\,dt'.
```

[p. 388, Eq. 21.5; verified]. The optimum depends entirely on kernel, risk, signal, and constraint
assumptions. For one exponential kernel, the solution has boundary blocks plus a constant interior;
in a fast-decay limit it tends to TWAP [p. 388, Eqs. 21.7–21.9].

### Constraint E3 — signal horizon versus execution cost

Slower execution reduces modeled impact but risks losing the prediction that motivated the trade.
Market orders buy certainty/immediacy and incur explicit impact/spread; limit orders face
non-execution, opportunity cost, queue position, and adverse selection [pp. 389–401].

### Epistemic warning E4 — phantom-order replay

Inserting hypothetical trades into historical order flow without modeling the market reaction omits
an effect of the same order as the strategy difference being studied [p. 402]. This directly
falsifies naïve JOSHI backtests that replay a different action while leaving all later AMM/social/
wallet state fixed.

## 12. Cross-model propositions and their status

| proposition | status | source | what would falsify its use in JOSHI |
| --- | --- | --- | --- |
| A price can be nearly linearly unpredictable while flow is predictable. | Empirical synthesis plus compatible models | pp. 36–37, 187–202, 249–268 | JOSHI evidence showing stable return predictability after costs would change, not invalidate, the measurement framework. |
| Observed post-trade motion is not mechanical impact. | Counterfactual identity | pp. 210–211, Eqs. 11.1–11.4 | Cannot be falsified as an identity; only operational definitions can be wrong. |
| Persistent signed flow requires adaptive impact/liquidity for diffusive prices. | Model consistency condition | pp. 251–258 | AMM prices need not be diffusive; external arbitrage, lifecycle jumps, or nonstationarity may supply a different balance. |
| Metaorder impact is concave and near square-root in many mature markets. | Empirical regularity | pp. 233–242 | Prospective venue/lifecycle data with stable alternative scaling and controlled selection. |
| Visible liquidity is a small fraction of intentions. | Empirical/behavioral interpretation | pp. 68–72, 187–202, 337–351 | No direct falsifier for intentions; observable proxies can bound but not identify it. |
| Provider revenue is offset by selection and inventory risk under competition. | Economic equilibrium heuristic plus empirical examples | pp. 298–330 | Persistent net provider profit after all costs, capacity, and tail inventory under attainable entry could reject the local break-even approximation. |
| Closed-loop mechanical impact cost should not be negative. | Model-design invariant | pp. 361–362 | A real profitable loop with exogenous information does not falsify it; a simulator-only uninformed loop does. |
| Instantaneous mark is unsafe for large-position valuation. | Consequence of size-dependent impact; practical claim | pp. 418–419 | Deep executable quotes demonstrating negligible size effect for the actual position and route. |

## 13. Dependency graph

```text
venue rules + event identity + exact clocks
           |
           +--> price object ----------------> returns / variogram / signature
           |
           +--> market state ----------------> queue or reserve/bin dynamics
           |                                      |
           |                                      +--> depletion / local direction
           |
           +--> event stream --> intensity/Hawkes + signed-flow memory
                                                     |
                                                     v
pre-action information manifest ----------------> observed response
           |                                      /          \
           |                             prediction impact   reaction impact (latent)
           |                                               /
           +----------------------------------------------+
                                                          v
signed-flow memory + adaptive liquidity ------------> propagator consistency
                                                          |
                                                          v
parent flow + participation + state ----------------> impact path / decay
                                                          |
                  provider fee/spread + selection + inventory
                                      |                   |
                                      +-------------------+
                                                          v
                                                  execution / LP P&L
                                                          |
                 source and model transfer constraints ---+
                                                          v
                                               JOSHI study, not policy
```

No arrow from deterministic replay to reaction impact exists. No arrow from a fitted Hawkes kernel
to causal social contagion exists. No arrow from an LOB queue imbalance to an AMM trade exists until
an AMM-specific state variable and prospective test are supplied.

## 14. Minimum typed JOSHI interface implied by the formalization

This is a semantic boundary, not an implementation specification:

```text
MarketObservation
  venue/lifecycle/source/evidence clocks
  raw event identity and coverage
  exact asset effects or exact state change

PriceObservation
  kind: mark | marginal | size_quote | fill_average | liquidation
  size/route/state/fee/clock/profile

SignedFlowEvent
  aggressor/sign definition
  exact base and quote atoms
  participant attribution quality
  parent/metaorder link quality

ImpactStudyRow
  focal event and pre-event information manifest
  observed response at multiple lags
  state/coverage/missingness
  no mechanical-causality label

LiquidityProviderEpisode
  fee income
  exact inventory path
  executable withdrawal/liquidation path
  adverse-selection response
  rebalancing/network/opportunity cost

OperatorEpisode
  discovery scene and stance
  inventory epochs and management tranches
  partial exit / runner / flat watch / re-entry
  witnessed and knowledge-cutoff evidence
```

Anything less will collapse distinctions that the book shows are economically material. Anything
substantially more should be earned by one concrete JOSHI study.

