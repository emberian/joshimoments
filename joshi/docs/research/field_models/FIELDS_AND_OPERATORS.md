# Measures, marked fluxes, memory, and constitutive operators

## 1. A field is an indexed measure, not an atmosphere

Let `X_t` be a declared domain: accounts, DLMM bins, trade-size axis, wallets, graph nodes,
candidates, funnel stages, or operator episodes. A field is represented as a measure `mu_t` or
function relative to a named reference measure `nu_t`:

```math
\rho_t=\frac{d\mu_t}{d\nu_t}\quad\text{only when this derivative exists and is useful}.
```

Examples:

- atomic inventory measure over `(account,asset)`;
- LP inventory measure over `(bin,asset)`;
- quote cost function over exact requested size;
- event-count measure over `(time,mark)`;
- viewport-seconds measure over candidate cards;
- unique-account occupancy over social/community nodes; and
- episode capital-time over `(episode,asset)`.

The density changes when the reference measure changes. “Liquidity density per bin,” “per unit
price,” and “per unit log-price” are different quantities.

## 2. Marked event measure

For eligible events `e_i` with occurrence/chain index `tau_i` and typed mark `m_i`, define

```math
N(dm,dt)=\sum_i \delta_{(m_i,\tau_i)}(dm,dt).
```

A mark can contain:

```text
event kind and native locator
venue, pool, mint, lifecycle
direction/sign definition
exact asset deltas and size
pre/post state identity
wallet/actor role plus evidence grade
source/receive/available clocks
coverage and canonicality
operator/scene linkage, when present
```

No aggregation is valid until the eligible event universe and coverage are declared. Provider
duplicates are observations, not extra market events; equal-valued instructions with different
locators remain separate events.

### 2.1 Mark functions

A study-specific measurable function `psi(m)` turns event marks into a flux or statistic:

```math
J_\psi((t_0,t_1])=\int_{(t_0,t_1]}\int \psi(m)N(dm,dt).
```

Examples and units:

| `psi(m)` | output | unit |
| --- | --- | --- |
| `1[event=trade]` | trade count | events |
| signed base atoms | net aggressive base flow | base atoms |
| signed quote atoms | net quote consideration | quote atoms |
| wallet count with dedupe rule | participant arrival | wallet-evidence units, not people |
| `1[event=liquidity_remove]` | removal count | events |
| removed `X/Y` entitlement | LP outflow | separate X and Y atoms |
| viewport dwell | candidate exposure | viewport-seconds |
| operator action category | funnel transition | events |

A signed sum is not automatically a vector field. It becomes one only after a domain and edge
orientation are defined.

## 3. Discrete balance before continuity equations

For state measure `mu_n` and event transition `T_{e_n}`, write

```math
\mu_{n+1}=T_{e_n\#}\mu_n+S_{e_n}-R_{e_n}+U_{e_n}.
```

- `T_#` transports or pushes forward existing measure;
- `S` adds boundary-relative source mass;
- `R` removes boundary-relative sink mass; and
- `U` is an explicit unresolved/residual term.

For an asset ledger, these objects can be exact atomic postings. For attention, `T`, `S`, and `R`
are observation-defined counts and need not conserve total mass. For social graphs, node/edge
creation changes the domain itself.

### 3.1 Weak balance form

For test function `f` on the domain:

```math
\langle f,\mu_{n+1}\rangle-\langle f,\mu_n\rangle
=\langle f,T_{e_n\#}\mu_n-\mu_n\rangle
 +\langle f,S_{e_n}-R_{e_n}+U_{e_n}\rangle.
```

This is useful because it can be tested without assuming differentiability. It also exposes which
test functions are invariant. Taking `f` as an asset indicator recovers commodity conservation;
taking `f` as quote value does not.

### 3.2 Continuity notation as a coarse summary

Only after choosing a continuous or graph domain and an aggregation scale may one write

```math
\partial_t\mu+\operatorname{div}J=S-R+\mathcal R+U.
```

Here `mathcal R` denotes a typed conversion/reaction term, not a physical chemical reaction. This
equation is a bookkeeping decomposition. It predicts nothing until a constitutive operator for
`J`, `S`, `R`, or `mathcal R` is supplied and tested.

## 4. Compressible measures

In this corpus, **compressible** means only that mass or concentration over a declared domain can
change through transport, source/sink, conversion, or moving boundaries. It does not imply gas
dynamics or a pressure equation.

### 4.1 Liquidity measure

Liquidity is directional and size-dependent. Prefer the executable cost/proceeds surfaces:

```math
C_t^+(q)=\text{quote atoms required to buy }q\text{ base atoms},
```

```math
C_t^-(q)=\text{quote atoms received for selling }q\text{ base atoms},
```

with fees, state/profile, route, refusal, and observation time attached. Derived quantities may
include:

```math
\bar p_t^+(q)=C_t^+(q)/q,
\qquad
\kappa_t^+(q)=C_t^+(q)-q\,p_{marg,t}^+,
```

where `kappa` is a finite-size cost relative to a declared marginal baseline, not universal impact.

Alternative measure forms:

- LOB displayed atoms per price level/side;
- Pump/PumpSwap executable quantity before a cost/refusal boundary;
- DLMM atomic inventory over bins/assets;
- routed best attainable proceeds across venues at one cutoff.

Compression/expansion can mean a decline/increase in executable capacity within a cost band, or
concentration/dispersion of DLMM assets across bins. The definition must name direction, size,
asset, and coordinate.

### 4.2 Inventory measure

For account/position set `B`:

```math
\mu_t^{inv}=\sum_{u\in B}\sum_{a\in A}b_{u,a}(t)\delta_{(u,a)}.
```

This is exact when balances close. A quote-valued pushforward

```math
V_t^{liq}(B)=\sum_a Q_{a\to numeraire,t}(M_a^B)
```

is derived, route- and size-specific, and generally non-additive: liquidating combined holdings can
use shared capacity and change state. Never infer conservation of `V_liq` from conservation of
atoms.

For DLMM, bin concentration can be summarized using normalized asset or share weights `w_j`:

```math
H=-\sum_jw_j\log w_j,
\qquad
N_{eff}=e^H,
\qquad
HHI=\sum_jw_j^2.
```

These are descriptive and depend on whether weights use share, X atoms, Y atoms, or a declared
valuation. They are not risk measures by themselves.

### 4.3 Attention measure

Several non-equivalent measures are admissible:

```text
surface-card seconds
viewport-card seconds
open-panel seconds
active interaction counts
explicit shortlist/pairwise preference
hot-scope resource seconds
operator self-reported attention
```

For candidate `c`, one may define observed viewport exposure

```math
A^{viewport}_c([t_0,t_1])
=\int_{t_0}^{t_1}\mathbf1\{c\text{ intersects viewport at }t\}\,dt.
```

This measures possible visual exposure, not cognition. Total attention can expand when several
panels are visible, contract when the app is backgrounded, or duplicate across candidates. There is
no conservation law equating attention lost by one coin with attention gained by another.

### 4.4 Community/audience measure

Candidate measures include unique observed authors, repeat authors, reply edges, wallet holders,
buyers, or cross-platform stable identities. Each has different units and sybil/coverage defects.
A normalized audience-share measure across a coin family can describe concentration, but apparent
movement requires participant-preserving evidence and healthy coverage on every member.

## 5. Graph fluxes

### 5.1 Incidence balance

For a fixed directed graph layer with incidence matrix `B`, node occupancy `x_n`, edge flux `f_n`,
and source/sink `s_n`, a descriptive balance is

```math
x_{n+1}-x_n=Bf_n+s_n+u_n.
```

This can be exact for token transfers on a closed wallet/account graph. It is usually not exact for
people/community movement because identities, arrivals, departures, and observation coverage are
uncertain.

### 5.2 Wallet flow layers

Keep at least these edge families separate:

- exact asset transfer;
- direct signed trade participation;
- fee payment/sponsorship;
- funding/co-sign/bundle evidence;
- temporal co-trading similarity;
- inferred controller/entity relation; and
- operator social-follow/watch relation.

For direct asset transfer, edge flux is asset atoms. For signed trading, edge marks include side,
size, venue, and post-state; no conserved graph mass is implied. For inferred entity edges, a graph
flow is an H4 hypothesis, not an H0 transfer.

### 5.3 Social and territory flow

Typed flows include:

- post/reply/mention creation;
- follow/unfollow;
- first/repeat author appearance;
- audience overlap between family members;
- explicit link or public participation;
- fee-route/claim transition; and
- identifiable participant sequence consistent with migration.

“Audience moved from A to B” requires at minimum:

1. stable participant identity or bounded matching uncertainty;
2. activity decrease at A and later increase at B;
3. comparable healthy coverage;
4. family/territory membership known at the evaluated cutoff; and
5. a matched general-rotation/null comparison.

Without those, report changing node occupancy and overlap, not directed flux.

### 5.4 Dynamic graph warning

When nodes/edges enter or leave, `B_t` changes. Apparent divergence may be a topology update.
Store separately:

```math
\Delta x=\Delta_{flow}x+\Delta_{source/sink}x+\Delta_{topology}x+u.
```

Embedding drift, resolver revision, and later identity joins belong to `Delta_topology` or model
revision, never historical flow.

## 6. Conditional intensity and source/sink operators

For event family `r`, let

```math
\Lambda_r(t\mid\mathcal H_t,X_t)
```

be a fitted conditional rate given eligible observed history and state. Candidate baselines should
advance in this order:

1. healthy-coverage constant or seasonal Poisson;
2. count overdispersion/negative-binomial or state-stratified hazard;
3. autoregressive/self-exciting event history;
4. multivariate event layers; and
5. nonlinear state/history models.

`Lambda` is a forecast object. Decomposition into baseline `mu(t)` and excitation kernels is not
uniquely causal: a long kernel, unobserved common input, ranking feedback, regime mixture, and
adaptive acquisition can generate similar observed intensity.

### Falsifiers

- no held-out log-score/calibration gain over seasonal/state baseline;
- future-shift or unrelated-mint negative controls perform similarly;
- gain vanishes under source-health and platform-wide activity controls;
- parameters drift beyond their intended regime; or
- hot-scope promotion explains the apparent event acceleration.

## 7. Response and memory operators

### 7.1 Observed response

For outcome field `Y`, event class `r`, lag `tau`, and pre-event state `x`, define

```math
R_{Y\leftarrow r}(\tau\mid x)
=\mathbb E[\psi(m_e)\{Y(t_e+\tau)-Y(t_e^-)\}
  \mid e\in r,X_{t_e^-}=x,\text{eligible coverage}].
```

This is an H2/H3 conditional association. The outcome must specify price kind, quote size, route,
liquidity measure, attention count, or social transition. In AMM studies, separate deterministic
instantaneous protocol movement from subsequent observed adaptation.

### 7.2 Reaction impact

For intervention `do(e)` and pre-action information `F_t`, reaction is a counterfactual contrast:

```math
I^{react}(\tau;F_t)
=\mathbb E[Y_{t+\tau}\mid do(e),F_t]
-\mathbb E[Y_{t+\tau}\mid do(\varnothing),F_t].
```

One realized chain identifies neither term jointly. A replay that inserts/removes a trade while
holding later transactions, routes, attention, and MEV fixed estimates a frozen-path mechanical
contrast, not full reaction impact.

### 7.3 Linear memory kernel

A descriptive Volterra/propagator baseline is

```math
Y(t)-Y(t_0)
=\sum_r\int_{t_0}^{t}K_{Y,r}(t,u;X_{u^-})\psi_r(m)N_r(dm,du)+\eta(t).
```

Restrictions should be added one at a time:

- time-homogeneous: `K(t,u)=K(t-u)`;
- linear in event marks;
- state-independent;
- additive across event types;
- stationary residual; and
- fixed topology.

These are falsifiable assumptions, not the definition of a field. The Bouchaud propagator result
that response is not the bare kernel remains important; see
[`FORMAL_MODEL.md`](../../microstructure/trades_quotes_prices/FORMAL_MODEL.md#7-propagator-and-history-dependent-liquidity).

### 7.4 Flow memory

For sign/event series `epsilon_n`, measure:

```math
C_\epsilon(\ell\mid x)=\mathbb E[\epsilon_n\epsilon_{n+\ell}\mid X_n=x].
```

Candidate explanations include parent splitting, herding, repeated routers, platform bursts,
arbitrage, regime mixture, and source selection. A power-law fit does not select among them.

Required challengers:

- participant/wallet-cluster conditioning;
- lifecycle and venue stratification;
- wall-time versus event-time comparison;
- shuffled-within-state baseline;
- cold-market census stratum; and
- chronological regime holdout.

## 8. Constitutive operators

A balance law needs a closure: a map from state/history to expected flux or transition. Organize
operators by authority.

### 8.1 Exact kinematic operators, H1

```text
F_protocol(z, action) -> new state or refusal
Q_protocol(z, direction, size) -> exact quote artifact
W_position(z, shares) -> withdrawal inventory
R_ledger(pre, effects) -> reconciled postings/residual
```

These are deterministic under complete input/profile, but can still be wrong relative to deployed
programs. Their falsifier is conformance.

### 8.2 Descriptive projection operators, H2

```text
CensusAggregate(events, coverage, bins)
ExecutableSurface(exact quotes over declared sizes)
AttentionOccupancy(scene/viewport events)
GraphProjection(typed temporal assertions)
EpisodeProjection(ledger + operator events)
```

Their falsifier is provenance/replay/coverage disagreement, not economic performance.

### 8.3 Statistical constitutive operators, H3

Examples:

```math
\widehat J_t=\mathcal F_\theta(X_{\le t}),\quad
\widehat\Lambda_t=\mathcal H_\theta(N_{<t},X_t),\quad
\widehat R_\tau=\mathcal K_\theta(X_t,m_t),\quad
\Pr(\text{next transition},\tau)=\mathcal G_\theta(H_t).
```

They must declare target, support, training cutoff, regularization, uncertainty, baseline,
availability-time features, and held-out falsifier.

### 8.4 Latent-state operators, H4

Examples:

- state-space latent liquidity inferred from future arrivals/removals/trades;
- latent community state inferred from temporal typed graph evidence;
- actor/fleet equivalence class inferred from wallets/transactions;
- latent territory leadership;
- unarticulated operator predicate inferred from gestures/scenes.

Each output is a posterior or candidate explanation with evidence lineage. It must preserve
label-switching and observationally equivalent mechanisms where present.

### 8.5 Learned policy operators, H5

```math
\pi_\theta(a_t\mid Y_{\le t},D_t,I_t,\text{capability})
```

is a controller, not a market field. Showing its output to Ember changes the composite policy and
future data. Evaluation must therefore include UI exposure, override, attention displacement, and
policy-version regime changes. Safety gates remain mechanically independent of model confidence.

## 9. Reflexive coupling

JOSHI participates in the observed system even while read-only:

```text
market/social state
  -> source/product surface
  -> Ember attention and JOSHI glass
  -> manual action or changed watching
  -> landed market/portfolio state
  -> future surface and learning data
```

Consequences:

- a better display changes the policy whose historical data trained it;
- hot-scope promotion changes observation density;
- public/manual trades can change reserves and attract/respond to other agents;
- alerts can create FOMO or displace attention;
- model explanations can create labels that later appear predictive; and
- scaling changes capacity, impact, visibility, and competing-agent response.

No stationary constitutive operator is assumed across product versions. Treat each material UI or
policy change as an intervention/regime boundary and retain concurrent simple baselines where
possible.

## 10. MEV and endogenous transition order

Solana execution adds an adversarial ordering operator:

```math
z_{land}=\mathcal O_{leader/searcher/traffic}
 (z_{observe},\text{focal transaction},\text{competing transactions},\text{fees/tips}).
```

`O` is not fully observed or controlled. It can select which focal attempts land, change pool state
before the fill, bundle reactions, or make apparent response contemporaneous with execution.

Required distinctions:

- quote-state movement from the focal action;
- pre-landing competing movement;
- same-slot/bundle ordering;
- post-landing observed response;
- failed attempt and paid cost; and
- finality/reorg correction.

A field model that timestamps everything at block time and estimates a local derivative can reverse
cause/order. Chain locator and receive/send clocks remain primary.

## 11. Operator-admissibility checklist

Before fitting any `F`, `K`, `Lambda`, latent state, or policy:

1. What domain and reference measure does it act on?
2. What are input/output units?
3. Which clock and event ordering are used?
4. Which topology/profile is held fixed?
5. Which inputs were actually available at the decision cutoff?
6. How does coverage enter zeros and denominators?
7. What exact mechanical operator should be subtracted or retained?
8. What source/sink/boundary terms can mimic transport?
9. What baseline and negative controls can reject it?
10. What regime/scale bounds its support?
11. What causal statement, if any, is identified?
12. What instrument remains if the operator fails?

