# What the literature actually says about LPing memecoins

Grounding pass, 2026-08-14. Every quantitative claim below carries its validation status,
because this area is worse than most: **no result in it has been independently replicated.**

---

## 0. The correction that matters most

Earlier in this session I told the operator that an LP position is short gamma and therefore
"pays when the ratio oscillates and hurts when it trends," and that a mean-reversion thesis was
consequently the right one. **That is wrong**, and the LVR paper (arXiv:2208.06046 §8) says so
in terms:

> *"the CFMM exactly breaks even if prices mean-revert, and loses more money than the
> rebalancing strategy if prices diverge, thus losing money on average… for a CFMM to perform
> well, it is not sufficient to break even when prices revert; a trading strategy which sells
> into price rises and buys into price decreases must actually make strictly positive profits
> when prices revert, in order to compensate for the losses it makes when prices diverge."*

Oscillation does not pay the LP — the inventory leg round-trips to zero while LVR accrues at
σ²/8 on every wiggle. **Fees are the only thing that pays.** "I expect the ratio to revert" is
therefore not an LP thesis; it is an argument that the inventory leg won't hurt, which is silent
on whether fees clear the cost.

Corollary, and it redirects the whole strategy: **what kills a bounded LP position is
one-directional drift, not a rug.** The survival filter is aimed at the wrong axis.

---

## 1. The "-EV" consensus does not apply here, and its source is compromised

The folk claim that ~50% of LPs lose money traces to **one document**: Loesch, Hindman,
Richardson & Welch (arXiv:2111.09192), a.k.a. the "Topaze Blue / Bancor report."

- It **is** the Bancor report. Bancor securities filings (*1:23-cv-00533-RP*, W.D. Tex., Docs.
  54 & 56) identify Richardson as Bancor Head of Research and Hindman as DAO administrator.
- The paper's own introduction notes *"Bancor v2.1 provides IL insurance at the protocol
  level."* **The authors sold the hedge against the risk their paper sized.**
- Never peer-reviewed. Never replicated. Every "two independent studies agree" framing in the
  wild is double-counting this one paper.
- Sample is the *opposite* of long-tail: 17 Ethereum pools, TVL > $10M, >75% of TVL is ETH/BTC
  against a stablecoin or each other.
- **And inside its own data the direction inverts:** per-pool negative-return share runs 34%–74%,
  and the *best* pool on every metric — lowest loss rate, one of only 3 profitable pools, best
  positive-segment ROI — was **FTM/WETH at the 1% fee tier**, the most volatile and most
  long-tail asset in the sample. Worst was MKR/ETH at 0.3%. (n=1 pool; do not overclaim.)

Corroborating evidence pointing the same way:

- **Fritsch & Canidio (arXiv:2404.05803, peer-reviewed WWW'24 companion):** in the largest ETH
  pools fees ≈ 80% of arbitrage losses, but **less-liquid pairs (MATIC-ETH, LINK-ETH) earned fees
  ~50% ABOVE losses.** Also: Uniswap **v2 beat v3** on the same pair and fee tier, fees ~3× losses.
- **The LVR paper's own calibration** (WETH-USDC, 1 year): delta-hedged LP returned **+8–9%/yr**,
  Sharpe 17 at the model level. It is not a "LPing loses money" paper.

**Defensible summary: "LPing memecoins is −EV" is not established for memecoins. It is
extrapolated from blue-chip Ethereum pools, and within the best-known such study the most
volatile pool performed best.**

---

## 2. Three structural facts that favour this specific setup

**(a) The gas constraint that dominates the literature does not bind on Solana.** Cartea, Drissi
& Monga (SIAM J. Fin. Math. 15(3), 2024 — peer-reviewed, genuine walk-forward OOS on real
Uniswap v3 data) measure recentering at **$84.8 per round trip** and conclude the strategy is
profitable *only above $1.8M of capital*. That break-even is **Ethereum gas**. Solana's cost is
4–5 orders of magnitude lower, which structurally inverts the conclusion. **Nobody has measured
recentering economics on a low-gas chain.** This is the cleanest gap in the field.

**(b) LVR is overstated when your pool IS the price-discovery venue.** Schlegel & Kilbourn
(arXiv:2507.02027, theoretical, unvalidated) show LVR scales by `(1 − marginal-liquidity ratio)`
against the reference venue. For a memecoin with no deep CEX book, that ratio approaches 1 and
**LVR → 0**. Their own words: *"Existing literature seems to systematically overestimate the
profits of arbitrageurs."* Nobody has sized the overstatement.

**(c) Fast blocks move LVR from arbitrageurs into your fee income.** The asymptotic result
(arXiv:2305.14604, peer-reviewed FC'24) is `ARB ≈ LVR × P_trade`, `P_trade ≈ σ√(Δt/2)/γ`. At
memecoin parameters on Solana (σ=20%/day, Δt=0.4s, 2% fee) that puts **ARB at ~1.5% of headline
LVR** — i.e. ~98% of the adverse selection is recaptured as fees. This is theory extrapolated
well outside its validated regime and has never been measured on Solana; treat as directional.
Measured block-time scaling (Fritsch & Canidio) is Δt^(1/3), flatter than theory's √Δt, and
**flattens below 1 second** — so Solana's edge over a 1s chain is small, but the 12s → 400ms step
is real.

---

## 3. The specific danger, which is mechanical and checkable

Meteora's dynamic fee is `f_v ∝ (volatility_accumulator × bin_step)²`. Dimensionally that is the
right shape — it scales as σ², the same power as LVR, which a fixed fee does not.

**But `volatility_reference` resets to zero after `decay_period`.** So a **slow monotonic drift** —
many bins crossed, but spread out enough that the accumulator keeps resetting — produces
**near-base fees while incurring full LVR.** That is precisely the one-directional decay that
kills a memecoin LP, and it is the scenario the fee mechanism is least able to price.

Meteora's own whitepaper concedes the tail failure: *"a tracking error occurs under extremely
volatile events due to large deviations in nominal price changes"* — it under-tracks exactly when
LVR peaks. The `variable_fee_control` parameter is set per-pool by the creator with **no published
derivation tying it to σ²/8 and no calibration anywhere**.

**Verdict: "dynamic fees compensate for volatility" is dimensionally defensible and empirically
unvalidated, on Meteora or anywhere.**

---

## 4. Two results that are directly actionable

**The quote-asset choice.** `σ²_ratio = σ_A² + σ_B² − 2ρσ_Aσ_B`, and LVR ∝ σ²_ratio. Quoting a
memecoin against SOL rather than a stablecoin **reduces LVR iff ρ > σ_SOL/(2σ_meme)**. At
σ_meme = 200%/yr, σ_SOL = 80%/yr the break-even correlation is **ρ = 0.20**:

| ρ | ratio variance vs stable quote |
|---|---|
| 0.0 | +16% |
| **0.20** | **break-even** |
| 0.5 | −24% |
| 0.7 | −40% |

Memecoin–SOL correlation plausibly exceeds 0.20 in risk-on/risk-off regimes, so the volatile
numeraire is probably helping — and **this is measurable from our own tape.** Nobody in the
literature has measured memecoin–SOL correlation.

**The small-LP equilibrium.** Lehar, Parlour & Zoican (arXiv:2307.13772): large LPs dominate
low-fee pools and reposition constantly against informed flow; **small LPs converge to high-fee
pools, accepting lower execution probability to mitigate adverse selection.** High fee tier,
wider range, less repositioning — arrived at independently of any strategy paper.

---

## 5. Why 39 positions and +$741 is not yet evidence

Four compounding reasons:

1. **The distribution, not the count.** BIS WP 1227 (Uniswap v3, May 2021–Dec 2023) finds retail
   LP daily excess returns have a **negative median and a positive mean driven by skew**. A short
   winning sample is the *expected appearance* of that distribution. In an adjacent memecoin
   sample, removing the top 3 of 190 trades flipped +117.7% cumulative to unprofitable.
2. **No control group** — no record of what the declined tokens did.
3. **Regime.** The pump.fun graduation rate moved **>25× in 30 months** (2.56% → 0.63% → 0.26% →
   2.5–6.7% post-BOOST). Anything estimated in one regime is a historical fact, not a prior.
4. **Wrong benchmark.** Zero is not the null. HODL is, and separately a random token from the
   same venue at the same time.

**The diagnostics that would settle it, in priority order:**

- **Decompose P&L into fees vs inventory change, per position.** Under the LVR identity,
  `LP P&L − rebalancing P&L = fees − LVR`, and the data requirement is stated explicitly in the
  source: only the LP's risky-asset holdings time series and the reference price. **We have both.**
  This separates the claimed edge from SOL/token beta and is the highest-value computation available.
- **Sign test on position count**, robust to the skew that makes the sum untrustworthy. One-sided,
  null P(win)=0.5: **26/39 winners → p = 0.027; 28/39 → p = 0.005; 25/39 → p = 0.054.** So ≥26 of
  39 positions individually beating their HODL counterfactual *would* be genuine evidence. The
  aggregate +$741 is not.
- **Leave-k-out sensitivity** — drop the best 1/2/3 positions and see what survives.
- **Freeze the filter in writing and log rejections from here.** Without the declined arm there is
  no measurable edge, only a description of what happened.

---

## 6. Well-supported negatives (worth more than weak citations)

1. No study reports LP returns conditional on token survival or quality. Zero, any chain, any AMM.
2. No empirical LP-return study exists for **any Solana DEX**.
3. No empirical LP-return study of a **memecoin pool** exists on any chain.
4. No LVR measurement exists for any Solana AMM or any long-tail pool.
5. No Hurst / variance-ratio / return-autocorrelation estimate exists for any memecoin population
   — so **the day-to-day mean-reversion premise is neither supported nor refuted; it is untested.**
   The one adjacent measurement (ETH, 1Hz) finds reversion half-lives of ~2 minutes, which is
   microstructure, not a daily thesis.
6. No closed-form optimal recentering rule under fixed transaction costs.
7. No measurement of recentering economics on a low-gas chain.
8. **No peer-reviewed work on bin-based AMMs at all.** `all:"DLMM"` on arXiv returns 0. Worse, the
   LVR framework provably does not cover a constant-sum bin — its authors flag the discontinuity
   (Example 6, footnote 18), note it would need local time and the Itô-Tanaka-Meyer formula, and
   decline to pursue it. **Nobody has closed that gap since.**
9. No one has measured whether DLMM's quadratic dynamic fee compensates realised LVR.
10. **Nothing in this area has been independently replicated.**

Practical note on the bin discreteness: a single bin's adverse selection is an *atom* at each
crossing (local time), scaling O(σ√T) rather than O(σ²T). But at memecoin volatility over
day-to-few-day horizons the price traverses 20–100 bins, the atoms aggregate, and the smooth σ²/8
model scaled by concentration is the right working approximation. Discreteness only bites intraday.
