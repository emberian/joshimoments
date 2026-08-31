# Isometric semantic-subsumption audit

Date: 2026-08-18  
Dragon's Clutch baseline: `eb8c82045bf8218e0d740227c372749bfe50122f`  
Input: Isometric Protocol official whitepaper/site v1.2, supplied in the research request

## Result

**[VERIFIED]** Dragon's Clutch already has the stronger settlement primitive:
an exhaustive state basis, complete-set conservation, bounded portfolio payoffs,
a coupled simplex auction, and a derived distributional-basis kernel. A graded
range payoff is a payoff function over the resolved state, not a new kind of
market.

**[VERIFIED]** Clutch does not yet subsume three product mechanisms: an
always-quoting cost-function market maker, passive range-selected LP capital, or
a transferable token for one whole portfolio. The degree-1 basis is implemented
in the pure kernel/reference seam, but the full Solana account path retains the
layout residue recorded in
[`DISTRIBUTIONAL_CLAIMS_DESIGN.md`](../../docs/implementation/DISTRIBUTIONAL_CLAIMS_DESIGN.md).
The current basis is bounded to 16 outcomes.

**[VERIFIED]** The Isometric pricing mechanism cannot be adopted as specified.
Its per-bin-liquidity field is not globally integrable when the `b_k` differ;
LMSR and sigmoid curves are simultaneous price authorities without one stated
potential; Gaussian range liabilities do not inherit the categorical `b ln N`
loss bound; and live liquidity-parameter changes create unaccounted value
transfers.

**[PROPOSED]** Subsumption should use three orthogonal additions: a generalized
bounded-payoff compiler, one scalar-potential market-maker interface, and
separately capitalized LP tranches with immutable liquidity epochs.

**[REJECTED]** Per-bin `b_k` LMSR, dual pricing, unfunded insurance promises,
VaR-capitalized leverage, mutable live-market terms, and subjective arbitration
should not become Clutch features merely to match a checklist.

## Evidence discipline and meaning of subsumption

- **[VERIFIED]** means checked against the pinned local source/documents or
  established by an explicit derivation here. It does not mean “formally
  verified”; no proof is claimed closed by this memo.
- **[SOURCED]** means stated by the supplied v1.2 material or the coordinating
  official-source review, but not established by executable artifacts here.
- **[INFERRED]** depends on an unstated implementation choice.
- **[PROPOSED]** is a Clutch extension or gate, not a landed feature.
- **[REJECTED]** is unsuitable unless replaced by a materially different,
  invariant-preserving construction.

**[SOURCED]** The official-source review found a public v1.2 description but no
public implementation repository, deployed-program manifest, audit report, or
machine-checked proof artifact. This is therefore an audit of specified
semantics, not code or a deployment. The description also gives differing
insurance funding sources/percentages; that is treated as an unfrozen
specification, not evidence about conduct or intent.

Let `Omega` be one Market's immutable terminal-history set and let a product be
`g : Omega -> [0,U]` in exact collateral atoms or a frozen rational scale.
Algorithmic subsumption requires:

1. exact representation, or a disclosed `g_hat` with a checked error bound;
2. one scalar cost function or exact clearing relation for every quote;
3. dedicated collateral covering supremum terminal liability after every step;
4. deterministic resolution from frozen evidence;
5. honest exit semantics—transfer/sell capability is not guaranteed liquidity;
6. one canonical owner for every token, balance, escrow, and liability; and
7. exact integer units with one named rounding convention.

**[REJECTED]** Feature-count subsumption is too weak. Adding leverage,
“insurance,” voting, and NFTs can broaden a UI while destroying the invariant.

## Market-maker audit

### Constant-liquidity LMSR

For finite, mutually exclusive, exhaustive unit states and one constant `b>0`,

```text
C(q) = b log(sum_i exp(q_i/b)),
p_i = exp(q_i/b) / sum_j exp(q_j/b).
```

**[VERIFIED]** This is one potential, so a trade costs
`C(q+Delta)-C(q)` independently of decomposition, prices sum to one, and the
uniform finite-state subsidy bound is `b log N`. With fixed positive weights
`mu_i` summing to one,

```text
C_mu(q) = b log(sum_i mu_i exp(q_i/b)),
max_loss <= b log(1/min_i mu_i).
```

Weights change the prior and bound; they do not create independent coordinate
liquidity parameters.

### Per-bin `b_k` is not a cost-function market maker

**[SOURCED]** Isometric proposes `b_k=b_base(L_k/L_avg)` and localized trade
costs with `q_j/b_j` inside one log-sum-exp but `b_k` outside for a trade in
coordinate `k`. Let `S(q)=sum_j exp(q_j/b_j)`. The implied quote is

```text
p_i(q) = exp(q_i/b_i)/S(q).
```

For `i != j`,

```text
partial p_i / partial q_j = -p_i p_j/b_j,
partial p_j / partial q_i = -p_i p_j/b_i.
```

**[VERIFIED]** Mixed partials agree only when `b_i=b_j` wherever both prices
are positive. Thus no global cost potential exists for differing `b_k`, and
the stated path-independence claim is false.

Concrete counterexample: with two bins, `b_1=1`, `b_2=2`, `q=(0,0)`, buying one
unit of bin 1 then bin 2 under the displayed localized costs totals
`0.9417451003`; reversing the order totals `1.0618596072`. The same endpoint
differs by `0.1201145069`.

Further consequences:

- **[VERIFIED]** `L_k=0` gives `b_k=0` and undefined `q_k/b_k`, contradicting
  the claimed minimum depth unless an unstated floor exists.
- **[VERIFIED]** changing one `L_k` changes `L_avg`, hence every other bin's
  parameter; the mechanism is not local.
- **[INFERRED]** changing the “active bin” set creates another discontinuity
  unless that set is immutable.

**[REJECTED]** Do not import this formula, its path-independence claim, or its
`b ln N` bound.

### Dynamic parameters and continuous notation

**[VERIFIED]** Even a valid LMSR reprices inventory when `b` changes. Moving
from `C_old` to `C_new` at fixed `q` creates the value transfer
`C_new(q)-C_old(q)`. Someone must fund it and the new maximum loss. Updating a
field while positions remain open is not accounting.

**[SOURCED]** The paper also gives
`C(q)=b log(integral exp(q(x)/b)w(x)dx)`. **[VERIFIED]** This is coherent for
one fixed positive normalized measure, but it is not the per-bin-`b_k` formula.
The finite `b log N` bound does not survive an unrestricted atomless continuum:
a payoff can concentrate on arbitrarily small measure. A continuous mechanism
needs a restricted payoff class/minimum support and a new bound. Once
discretized, the implemented bins and exact weights own the guarantee.

### LMSR plus sigmoid

**[SOURCED]** Isometric assigns market pricing to LMSR and per-range
“micro-pricing” to a sigmoid. **[VERIFIED]** A sigmoid has a valid
one-dimensional integral, but the document does not say how its marginal price
composes with the LMSR price for the same share.

- Replacing LMSR per range loses a coherent simplex for overlapping ranges.
- Adding sigmoid cost to LMSR remains integrable but marginal prices no longer
  sum to one; a complete set need not cost one.
- Multiplication or post-normalization requires a new potential and
  mixed-partial proof.

**[VERIFIED]** Time-varying sigmoid steepness also reprices open supply without
a trade; `partial C/partial t`, its recipient, and reserve must be specified.
“Cooling off” is not a conservation rule.

**[REJECTED]** Admit one price potential per tranche, never two authorities.

### Purchase inventory differs from promised payout

**[SOURCED]** The purchase rule distributes a range share across bins by
uniform overlap, while settlement assigns an integrated Gaussian payoff.
**[VERIFIED]** A uniform overlap basket pays a rectangular function. An
integrated Gaussian is smooth and positive outside the selected interval.
Unless the overlap vector is exactly the settlement vector, pricing inventory
omits terminal liability.

**[PROPOSED]** Every trade must lower to the canonical payoff bytes used by
settlement. The MM and simplex auction price the same bytes; “range” and
“conviction” own no second truth.

## Gaussian payouts and solvency

For `a<b`, resolution `y`, and `sigma>0`, the displayed range payoff is

```text
g_[a,b](y) = (1/(b-a)) integral_a^b exp(-(y-x)^2/(2 sigma^2)) dx.
```

**[VERIFIED]** It lies in `(0,1]`, but for any nonzero-width range it is
strictly below one even when `y` is the range center: the integrand equals one
at only one point. Thus “dead center gives full payout” conflicts with the
displayed integrated formula unless a range-dependent renormalization is added.
That changes prices/liabilities and must be frozen explicitly.

For positions `r=1..R` with shares `s_r` and payoffs `g_r(y)`, exact liability
is

```text
Liability(y) = sum_r s_r g_r(y),
RequiredCollateral = sup_y Liability(y).
```

**[VERIFIED]** Individual bounds `g_r<=1` do not make Gaussian claims mutually
exclusive. Many nearby claims can all pay near one in the same state. Raw
Gaussian kernels also do not sum pointwise to one; their sum varies with state,
spacing, edges, and `sigma`. Consequently `max_r s_r`, per-bin LP deposits, and
the categorical `b ln N` subsidy do not bound this book.

Current Clutch distributional terms produce exact integer weights `phi_i(y)`:

```text
0 <= phi_i(y) <= D,
sum_i phi_i(y) = D.
```

A nonnegative coefficient portfolio pays

```text
g_hat(y) = sum_i c_i phi_i(y)/D.
```

**[VERIFIED]** In the degree-1 basis, coefficients sampled from a bounded target
produce its piecewise-linear interpolant. Since the basis is nonnegative and
sums to one after scaling, coefficients in `[0,U]` imply `g_hat` in `[0,U]`.
Point and integrated-range Gaussians are therefore ordinary bounded portfolios,
and the current batch relation already admits atomic proportional portfolios.

**[INFERRED]** This exactly settles the interpolant, not the analytic Gaussian.
Sixteen anchors may be inadequate for a narrow curve. Isometric is also
discretized in practice, but its `N` is not bounded to 16 in the reviewed text.

**[PROPOSED]** Add a closed-enum payoff compiler that publishes the analytic
target/normalization, exact settling coefficients, a reproducible bound on
`sup_y|g-g_hat|`, knot/edge/rounding rules, units, and maximum payout. The
settlement authority is `g_hat`, not the plotted analytic curve.

## LP capital, fees, and insurance

**[SOURCED]** Isometric calls a single-USDC deposit “single-sided LP,” assigns
it a range, and describes terminal underwriting loss as impermanent loss.
**[VERIFIED]** With one deposited asset and synthetic outcome liabilities, the
risk is market-making/underwriting loss. “IL” does not define the counterfactual
portfolio, mark, withdrawal amount, or terminal debt. Its capital measure is
maximum state-contingent shortfall, not spot-pair divergence.

**[PROPOSED]** Call it an LP guarantee tranche. Its exact state liability is
stored and its collateral cannot be withdrawn while needed, regardless of the
UI range.

**[SOURCED]** Fee allocation is displayed as
`yield_i=(risk_i/sum_j risk_j) total_fees`, with risk described as variance
inside the range. **[VERIFIED]** Deposit size and actual utilized liability are
absent. Equal risk scores give a small and large deposit the same fee share; if
computed per position, splitting can alter the denominator. Variance is not a
worst-case reserve or a general measure of tail underwriting.

**[PROPOSED]** Attribute fees by immutable capital-at-risk and executed exposure
under an anti-fragmentation identity. Candidates include incremental
maximum-liability reserve and Clutch's exact state-contingent dispersion. Both
remain experimental until Sybil, partition-refinement, and decomposition tests
pass.

**[SOURCED]** The proposed fund covers LP loss above a threshold and is
replenished by future token/protocol activity; safeguards may raise the
threshold if reserves fall. **[VERIFIED]** This is a senior state-contingent
claim. It is solvent only if dedicated capital covers the correlated maximum
shortfall of all policies after claim priority. Future fees have zero value in
the admission invariant. Raising the threshold after deposit changes the
contract or proves the original cap was not guaranteed.

**[REJECTED]** Do not admit “insurance covers all loss above 5%” unless fully
prepaid and immutable. A limited, pro-rata discretionary rebate is different
and must not be called a guarantee. Optional future revenue may capitalize only
future policies, consistent with [`ECONOMICS.md`](../../docs/ECONOMICS.md).

## Leverage and liquidation

**[SOURCED]** Isometric triggers liquidation using
`VaR_alpha=mu_portfolio-z_alpha sigma_portfolio`. **[VERIFIED]** Under ordinary
normal-return conventions this is a lower quantile of value/P&L, not
automatically a positive maximum loss. Meaning depends on sign, horizon,
distribution, correlation, and mark. Prediction payoffs are nonlinear and jump
at resolution; mean and variance do not bound the worst state, and a 99%
quantile explicitly permits a tail beyond it.

**[REJECTED]** VaR cannot capitalize protocol solvency. Clutch's exact
alternative is bounded claims reserved at worst-state payout, with no margin
call or liquidation.

**[SOURCED]** The Dutch auction starts above estimated value and descends per
slot. **[VERIFIED]** Solvency still requires a timely buyer, valid mark, and
atomic transfer/extinguishment before collateral falls below debt. A start above
“fair value” does not cause demand to exist. A Dutch auction redistributes MEV;
it does not eliminate MEV or bound bad debt by itself. The stated per-slot
leverage fee also lacks complete time normalization, compounding, cap, and
missed-slot rules.

**[REJECTED]** Leverage/liquidation remain Clutch non-goals. An external lender
may accept Eggs, but its debt/oracle/liquidation boundary cannot weaken a Hoard.

## Oracle and governance semantics

**[SOURCED]** The displayed “TWAP” is an arithmetic mean of samples.
**[VERIFIED]** That is time-weighted only on a frozen equal-duration grid or
when each sample carries its represented duration. A buffer size, a 30-minute
label, and a minimum sample count do not freeze cadence. **[PROPOSED]** Reuse
Clutch's exact `FeedSpec`, grid, duration-weighted integer accumulator, coverage,
repair deadline, and sealed `WindowResult`.

**[SOURCED]** Samples beyond `3 sigma` of a running median are excluded.
**[VERIFIED]** The algorithm is incomplete without scale estimator,
initialization, window, update order, ties, integer rounding, handling of honest
jumps, and minimum post-rejection coverage. Running filters can make accepted
history submission-order dependent. **[PROPOSED]** Any robust filter must be a
frozen total function yielding a conservative interval or deterministic refusal;
it may not silently manufacture a midpoint.

**[SOURCED]** Multiple feeds, optimistic resolution, and arbitration are named
without one complete cross-source aggregation/disagreement/failover relation in
the supplied material. **[REJECTED]** Subjective arbitration is outside
objective Clutch V1. Objective multi-source markets require canonical source
sets, units/orientation, synchronized time, dispersion bounds, and one
deterministic conservative result or failure.

**[SOURCED]** Governance may alter fees, insurance, oracle and leverage
parameters, with timelocks and a council veto. **[VERIFIED]** If applied to an
open market, such changes mutate signed economics, evidence, or guarantees.
Bounded votes and delay expose mutation; they do not preserve terms. The claim
of no admin keys is also in tension with a privileged veto and any upgrade
authority whose graph is not available here.

**[REJECTED]** Governance cannot mutate a live Market's source, basis,
collateral, fees, reserve, or failure rule. **[PROPOSED]** Coordination may
approve new immutable Templates, Realms, adapters, or deployment binaries;
existing Markets stay on their frozen versions.

## Token-2022 and position NFTs

**[SOURCED]** Isometric calls Token-2022 dependency-free/native while relying on
PermanentDelegate and TransferHook. **[VERIFIED]** CPI still depends on the
deployed Token-2022 program and runtime. Clutch correctly keeps it outside
Eggcrate as an unverified adapter boundary.

**[SOURCED]** The permanent delegate is described as irrevocable and used for
settlement/liquidation. **[INFERRED]** Change/disable semantics and ultimate
control depend on the pinned Token-2022 version and authority graph; no public
program artifact here proves “irrevocable.” **[VERIFIED]** Burn prevents double
claim only when canonical mint/account/amount/position and payout are checked
atomically. Resolution cannot proactively burn unknown holder accounts; a
claimant must present them or an enumeration mechanism must exist.

**[SOURCED]** TransferHook is used to block transfers, collect fees, and update
owner references. **[VERIFIED]** It is an executable callback/additional-account
surface that wallets, routers, markets, and lenders must support, reducing
permissionless compatibility. Deriving Position from NFT mint already decouples
identity from owner; persisting another owner field creates a second truth unless
all paths prove equality with token ownership.

**[REJECTED]** Canonical Eggs should retain base Token-2022 mints without
PermanentDelegate, TransferHook, freeze, or transfer fee, as the current adapter
requires.

**[VERIFIED]** A whole-position NFT transfers an entire position but cannot
partially sell fungible shares without split/wrap/close. Clutch Eggs and atomic
portfolio orders support partial quantities but no single portfolio token.
**[PROPOSED]** If demanded, an optional wrapper may mint a base receipt only
against escrowed exact Egg coefficients and burn atomically on unwrap/redemption.
It owns no payout truth and adds no delegate/hook authority.

## Semantic subsumption matrix

| Capability | Clutch at pinned baseline | Disposition |
|---|---|---|
| Continuous-value settlement | Finite partitions plus derived degree-1 partition-of-unity basis | **[VERIFIED] partial:** close Solana account-layout residue |
| Graded proximity payoff | Any bounded nonnegative curve as portfolio interpolant | **[VERIFIED] semantic subsumption:** add named compiler/error certificate |
| Exact analytic Gaussian/`erf` | Not implemented | **[PROPOSED] defer:** exact spline settlement is safer |
| Rectangular range | Exact basket of basis Eggs | **[VERIFIED] subsumed** |
| Atomic range/curve trade | Proportional portfolio intents in coupled batch relation | **[VERIFIED] subsumed semantically; program evidence remains** |
| Coherent distribution prices | Scaled simplex plus complete-set conversion | **[VERIFIED] stronger core** |
| Always-on automated quote | Native venue is a batch auction | **[VERIFIED] not subsumed:** optional scalar-potential MM needed |
| Concentrated passive LP | No passive LP tranche | **[VERIFIED] not subsumed:** add fully reserved tranches; reject `b_k` |
| Dynamic depth | No live parameter mutation | **[PROPOSED] new immutable tranche/epoch only** |
| Early transfer | Materialized fungible Token-2022 Eggs transfer | **[VERIFIED] subsumed; liquidity not guaranteed** |
| Early protocol quote | No always-on buyer | **[VERIFIED] not subsumed:** depends on optional MM capital |
| Terminal funding | Market-local Hoard/max-liability invariant | **[VERIFIED] stronger** |
| LP loss cap | No insurance promise | **[REJECTED] unfunded; PROPOSED only if fully reserved** |
| Leverage and VaR liquidation | Explicit non-goal | **[REJECTED]** |
| Objective TWAP/path result | Frozen feed/window/statistic and accumulator design | **[VERIFIED] semantic subsumption; runtime remains prototype** |
| Subjective arbitration | Not admitted | **[REJECTED] for V1** |
| Fungible composable claims | Hybrid internal balances and canonical base Token-2022 Eggs | **[VERIFIED] stronger for partial trading** |
| Whole-position bearer NFT | Absent | **[PROPOSED] optional escrow wrapper only** |
| Risk-sensitive trade fees | Exact state-contingent dispersion hypothesis | **[VERIFIED] more coherent metric, not promoted policy** |
| LP fee attribution | Absent | **[PROPOSED] capital/exposure-aware rule** |
| Emission/staking rewards | Not required | **[REJECTED] as safety capital** |
| Mutable live governance | Forbidden | **[VERIFIED] stronger** |
| Formal-verification claim | No closed proof claimed; boundaries documented | **[VERIFIED] honest gap:** close named theorems first |

## Coherent generalized Clutch design

### One payoff basis

Freeze `phi_0..phi_(n-1)` over authenticated evidence with exact integers:

```text
0 <= phi_i(omega) <= D,
sum_i phi_i(omega) = D for every admitted omega.
```

**[VERIFIED]** The current `DerivedBasis` kernel already consumes this
invariant; complete sets redeem exactly and coefficient portfolios are bounded.
**[PROPOSED]** A `CompiledPayoff` artifact should contain exact coefficients,
scale/units, target metadata, error certificate, and digest. Range, Gaussian,
call, put, tail, and indemnity shapes all lower to it. No range-specific supply
truth is introduced.

### One market-maker potential

On a finite settlement grid, let `z_x` be aggregate payout sold in state `x`.
A coherent generalized LMSR reference is

```text
C(z) = b log(sum_x mu_x exp(z_x/b)),
mu_x>0, sum_x mu_x=1,
trade_cost(a) = C(z+a)-C(z).
```

**[VERIFIED]** This prices the actual payoff vector—Egg, range, or Gaussian
approximation—and has finite weighted bound `b log(1/min_x mu_x)`.

**[PROPOSED]** This is reference semantics, not permission to put `exp/log` in
Eggcrate. Any admitted MM must provide:

1. one scalar potential or exact discrete-potential table;
2. convexity, monotonicity, and complete-set translation invariance;
3. normalized nonnegative state prices or an exact subgradient rule;
4. a finite checked loss bound for the admitted payoff class;
5. exact integer buy/sell rounding with persistent carry or explicit spread;
6. a post-trade vault covering exact worst-state liability;
7. total behavior/refusal for every arithmetic bound; and
8. immutable parameters while inherited inventory remains.

For integer quotes, path independence is the commuting square

```text
Delta_i(q)+Delta_j(q+e_i) = Delta_j(q)+Delta_i(q+e_j)
```

before the named fee/rounding boundary. If local curvature is valuable, derive
it from one convex regularizer

```text
C(q) = sup_(p in simplex) (p dot q - R(p))
```

and prove its potential/loss bound. Coordinate prefactors around one
log-sum-exp are not a substitute.

### Separately capitalized LP tranches

Each tranche owns one vault, immutable potential/version, inventory/liability
vector, admissible payoff/range policy, maximum-loss reserve, booked work, fee
ledger, and exposure epoch.

**[PROPOSED]** A range policy limits which canonical payoff vectors a tranche
quotes; it does not pretend liability exists only inside a UI interval.
Withdrawal is admitted only if (a) liability is zero, (b) another fully funded
tranche atomically assumes exact liability and reserve, or (c) the residual
vault still covers worst-state liability plus booked work.

LP principal is not Hoard principal. MM trader claims need their own protected
reserve or atomic conversion into funded Eggs. Neutral issuance remains usable
without an LP.

### Guarantees and wrappers

**[PROPOSED]** Model an LP loss cap as a senior bounded payoff with immutable
aggregate capacity and dedicated collateral. Admission checks correlated worst
case; capacity exhaustion refuses new policies and cannot dilute old ones.

**[PROPOSED]** A portfolio wrapper may escrow exact Eggs and mint receipts with

```text
escrowed Eggs = receipt supply * frozen coefficients.
```

Its payout authority is only the underlying Hatch; it has no oracle, MM,
insurance, owner, or governance truth.

## Proof and falsifier gates

No extension may be called formally verified without naming the exact theorem,
source digest, toolchain, assumptions, and unverified adapter/runtime boundary.
Draft 8 should require:

1. **[PROPOSED] Payoff compiler:** accepted coefficients are bounded,
   unit-compatible, exact, and covered by a sound whole-domain error bound.
2. **[PROPOSED] Partition of unity:** every derived vector is nonnegative and
   sums exactly to `D`; complete sets redeem exactly.
3. **[PROPOSED] Potential:** quotes are differences of one potential; discrete
   mixed trade squares commute before rounding/fees.
4. **[PROPOSED] Price:** state prices normalize and complete-set translation
   costs exactly one unit.
5. **[PROPOSED] Loss bound:** reserve plus collected net cost covers maximum
   terminal payout for every reachable inventory.
6. **[PROPOSED] Payoff identity:** range trades update inventory with the exact
   bytes used at settlement, never an overlap proxy.
7. **[PROPOSED] Parameter epoch:** LP entry/exit cannot reprice or underfund old
   inventory without an explicit conserving transfer.
8. **[PROPOSED] Withdrawal:** every accepted withdrawal preserves tranche and
   claimant solvency.
9. **[PROPOSED] Guarantee:** coverage cannot be diluted by later policies,
   governance, or fee failure.
10. **[PROPOSED] Rounding:** charges, payments, fees, carry, and settlement
    conserve every atom and resist fragmentation.
11. **[PROPOSED] Oracle:** observations have one order/grid; filter/aggregation
    is total and yields a unique value/interval or frozen failure.
12. **[PROPOSED] Token refinement:** internal inventory, mint supply, wrapper
    escrow, and CPI deltas have one semantic owner.

Adversarial fixtures must include unequal-`b` order reversal; zero-liquidity
bins; LP entry/exit at fixed inventory; overlap inventory versus Gaussian
liability; many coincident Gaussian claims; curve edges; honest jumps through
the outlier filter; missing/disagreeing sources; insurance exhaustion; no-bid
liquidation; transfer during settlement; direct token burns; unknown extensions;
and every one-atom rounding boundary.

## Draft 8 disposition

Incorporate:

- **[PROPOSED]** bounded distributional payoffs as the primitive;
- **[PROPOSED]** Gaussian/range examples compiled to exact portfolios with
  disclosed error;
- **[PROPOSED]** optional scalar-potential and LP-tranche interfaces that cannot
  weaken neutral issuance;
- **[PROPOSED]** maximum state liability, immutable terms, and prepayment as the
  comparison criteria; and
- **[PROPOSED]** a strict distinction between transferable and liquid.

Defer behind proof and measurement:

- **[PROPOSED]** onchain `exp/log`, outcome bounds above 16 or a fine settlement
  grid, exact analytic `erf`, portfolio wrappers, and LP fee weighting.

Refuse:

- **[REJECTED]** displayed per-bin `b_k` LMSR and dual LMSR/sigmoid authority;
- **[REJECTED]** parameter changes that do not settle value transfer and preserve
  inherited guarantees;
- **[REJECTED]** insurance capitalized by future fees;
- **[REJECTED]** VaR as a substitute for exact terminal collateral;
- **[REJECTED]** subjective arbitration in objective V1;
- **[REJECTED]** hooks/delegates/freeze on canonical Eggs; and
- **[REJECTED]** claims that a polynomial approximation is financially adequate
  without pinned domain, fixed-point implementation, directed error,
  monotonicity/range, and overflow proofs.

## Publication and regulatory boundary

**[PROPOSED]** Do not mention Isometric or another competitor in a public filing,
marketing claim, or regulator-facing packet until the official URL, version,
retrieval date, archive digest, exact quoted claims, and any public code/program
identities are frozen in a provenance manifest. No accusation about sponsors or
intent follows from this audit; claims are classified only as specified,
unsupported, internally inconsistent, or unimplemented.

**[VERIFIED]** Clutch is mathematically capable of expressing the coherent target:
continuous-value, graded, range-shaped, and Gaussian-like exposure. It is not yet
an AMM/LP protocol and should not claim literal feature subsumption until the
cost-function/tranche layers exist and the derived account path closes.

**[PROPOSED]** Draft 8 should aim higher than checklist parity: one objective
payoff compiler, one conserved basis, one price authority per tranche, exact
maximum-liability collateral, and optional liquidity that may fail to quote but
may never make settlement insolvent. That is the version worth specifying and
proving before separate legal and deployment gates permit regulator engagement.
