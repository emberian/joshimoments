# joshibot — research program

Written 2026-08-13 after a full audit of the live desk, the marketfabric codebase, and ~100 papers
across memecoin empirics, market impact, point processes, graph methods, and ML evaluation.

This document is the spine. It exists so the next session (human or agent) starts from the evidence
rather than from vibes.

**Provenance.** The first draft was assembled from subagent reports. On 2026-08-13 the two anchor
papers — Marino/Lillo (base rates, the no-go result) and MELT (the performance ceiling) — were read
directly and every number attributed to them checked against the source; §0's fee schedule, §1.1,
§1.2 and §1.3 now quote verified text, and the corrections are in the git history. Claims sourced to
the *other* ~93 papers remain agent-reported and are **not** yet verified at that standard. Treat an
unverified number as a lead, not a fact — that is exactly the discipline §3 demands of everyone else.

---

## 0. Situation

**What happened.** The sell-only sentinel ran live for ~5h on 2026-08-12 and the wallet lost
**7.47 SOL (~$564)** — reconstructed from chain two independent ways, reconciling to the lamport.
137 buys, 121 sells, 92 mints. 8.31 SOL of fee income flowed in during the window; the book ended
at ~1.1 SOL.

**Why.** `engine.py:770-773` stamps cost basis from the *current Jupiter exit quote* when a lot needs
one. PnL therefore starts at 0% by construction, and the stop fires that far below wherever the coin
had already fallen. The natural experiment is clean — same bot, same window, same market:

| basis source | round trips | mean return |
|---|---|---|
| operator-typed | 3 | **+18.1%** |
| fabricated from quote | 16 | **−29.1%** |

Prediction check: the model said Sully would realize −20% and Zoo −32% when their stops fired. They
fired mid-session and realized **−20.2%** and **−31.7%**.

**Money context.** Obligations ~$4,100/mo (rent ×2, utilities, AI, groceries) plus a $40k IRS debt.
DREGG creator fees run $213–313/day at current volume — covering obligations 1.6–2.3× with
$2.3–5.3k/mo surplus. Fees are linear in *volume*, and the pump.fun tier is *inverse* to size
(0.95% under $300k FDV, 0.60% to $1M, 0.35% above), so a falling price partially hedges the rate.
Independently corroborated by Marino §VII, which states the schedule from on-chain observation:
creators take **0.3% during the bonding-curve phase**, then a dynamic PumpSwap fee **"ranging from
0.950% down to 0.050%"** as the token grows. Two unrelated sources, same inverse ladder — the hedge
is a real property of the protocol, not an artifact of how we read the docs.
**Measured correction (studies/RESULT_circuit_model.md §dissipation):** the operator's actual DREGG
income against actual volume implies a realized creator take of **0.81–1.19%**, statistically
excluding the 0.60% tier this section assumed. The income model above is therefore *conservative* —
real coverage runs ~1.5–2× the tier-table figures. Why the realized rate exceeds the published tier
(fee-structure change, bonding-curve component, or tier misread) is unresolved; the direction is
favourable either way.
**The fee stream is the business; trading is a research program funded by it, not a rent strategy.**

---

## 1. What the evidence actually establishes

### 1.1 Base rates (the most valuable output of the whole review)

- **Graduation rate 0.63%** — Marino/Naviglio/Tarantelli/**Lillo**, arXiv:2602.14860, 655,770 tokens.
  Best-sourced figure in the field. (A 2026 measurement suggests lower, ~0.33%+, but its collector
  was displacement-censored — see §3.)
- **Median time-to-graduation 4.4 minutes**, median ~457 curve swaps. The decision window is minutes.
- **92.22%** of tokens with ≥30 swaps show a ≥4σ dump event — 169,938 of 184,282 (Marino, Shewhart
  chart on log-returns, `k=4`, median–MAD with Gaussian-consistent scaling `1/0.67449`).
- **2.55% graduate among those same 184,282 tokens with ≥30 swaps** — versus 0.63% unconditional.
  Surviving to 30 swaps alone quadruples the base rate; it is the cheapest conditioning in the paper
  and it is a *filter*, not a prediction.
- **84.13%** of *migrated* tokens are high-risk; **73%** fall below 0.4× migration price within
  20 minutes (MELT, arXiv:2602.13480).
- **~60%** of tokens live <1 day (Cernera et al., USENIX Sec'23).
- **36.5% of supply** is held by coordinated/bundled accounts disguised as independent (MELT).
- **98.7%** of launches have a dev buy in the create transaction — so raw dev-buy presence is
  uninformative; the *bundle-adjusted minus naive* top-10 delta is the signal (+24pp high-risk vs
  +6pp low-risk).
- **Accumulation is multi-wallet; the dump is frequently single-wallet** (Marino §VIII: "accumulation
  is often executed through multiple wallets, and it is common for the subsequent dump to be carried
  out by a single" one). That asymmetry is a free structural prior for signal #4 — and Marino's other
  half of the same finding is that predicting the *pump* leg is much harder than the dump leg.
- **Large drops cluster at specific vSol levels**, once enough SOL has accumulated to make liquidation
  worthwhile — dumps are not uniformly distributed along the curve, so curve position is a real
  conditioning variable for exit timing.

### 1.2 What is actually refuted — narrower than it sounds

Marino's no-go result constrains **buy-and-hold-to-graduation conditioned on curve-local on-chain
features**. Under every conditioning variable tested, P(graduate | vSol) sits below the breakeven
parabola `(vSol/115)²`. The paper explicitly notes dynamic strategies are *not* excluded.

The only conditioning that ever beat breakeven: **top-10 creators by prior graduation ratio**,
identified on the first half of the month and tested on the second (genuine temporal OOS) — and only
*at sufficiently advanced stages of the bonding curve*, i.e. the curve crosses breakeven late, not
everywhere. Per-creator graduation ratios run **0.023–0.084** against the 0.63% base, a **3.7–13.3×
lift**, over 51–268 tokens each (1,115 total across the ten; the filter requires ≥50 tokens per
creator). The authors flag it themselves: *"the statistical support in this conditioning is limited."*

Note what did **not** clear breakeven: conditioning on early participation by ex-ante identified
**top traders** raises the curve above the vSol-only baseline but stays *below* breakeven throughout.
Marino's reading is that top traders are a double-edged signal — they accelerate early liquidity but
exit fast, often around graduation.

**Not tested anywhere in the published literature:** conditional entries, time-boxed exits, exit-rule
design of any kind, social-propagation signals as live inputs, cross-token rotation, or anything
resembling how a person actually trades. Absence of measurement, not measured absence.

### 1.3 The honest performance ceiling

MELT is the calibration anchor — the only paper whose negatives come from the same population as its
positives, with a chronological split and no resampling:

- Best AUPRC **0.5827** vs 0.2589 random → **~2.25× lift**.
- Tabular beats sequence models, and the ordering is worth memorising: MLP 0.5729, RF 0.5688, LGBM
  0.5642, XGBoost 0.5636, LR 0.5338 — then LSTM 0.5023, GRU 0.4972, TCN 0.4844, **Transformer 0.4841,
  dead last and a full 5 AUPRC points below plain logistic regression**. The authors' mechanism, which
  generalizes to our regime: *"short and noisy trading sequences lack the long-range dependencies that
  Transformers are designed to exploit."*
- The top three are hybrids within 0.0023 of each other (MLP+LSTM 0.5827, MLP+LGBM 0.5821, MLP+RF
  0.5804) — a statistical tie — and the pure MLP trails the best by 0.0098. **The entire measured value
  of the sequence branch is about one AUPRC point.**

**But the comparison is confounded, and this matters for what we build.** MELT varied *model class*
and *input representation together*: the tabular models received engineered features (context, holding
concentration, market activity, bundle statistics) while the sequence models received, in the paper's
own words, "pure time-series of price and trading volumes." So the result is **not** "Transformers lose
on this problem"; it is "Transformers lose on price-and-volume alone, against engineered features."
Nobody has fed a sequence or graph model the *relational* structure — follower trade flows, launcher
identity, the wallet graph, cross-token flow — which is precisely the long-range structure attention
exists to exploit. That experiment is open, cheap, and ours to run.

Two further caveats found in the source, neither in the headline:

- **The ML experiments used 21,635 subsampled tokens** (16,048 high-risk / 5,587 normal), not the full
  41,470. The 0.2589 random baseline is just that 25.82% normal share.
- **MELT trains with class-weighted BCE**, weights inversely proportional to class counts. That is a
  soft rebalance: it shifts the implied prior and therefore **decalibrates the output probabilities**.
  Their AUPRC is rank-based and survives; their probabilities do not. Since our envelope needs
  *calibrated* probabilities for an EV decision (§3 rule 3), copy MELT's features and protocol but
  **not** its loss weighting.
- The ablation is sharper than "concentration matters": dropping holding concentration alone costs
  only 0.0036 AUPRC, dropping bundle stats alone costs 0.0278, but dropping **both** costs 0.0461 —
  more than the sum. Raw concentration is near-worthless on its own and only becomes informative
  against the bundle-adjusted baseline. That is the +24pp/+6pp delta, confirmed by ablation.
- Economic eval: buy at migration, sell at a random time within the hour. No model: **−60.7%**.
  Best model: **−26.6%**. *The best published pre-migration model converts a catastrophic loss into
  a large loss.*

Plan around 2–3× lift over base rate. Against these base rates that is economically meaningful. The
0.95+ AUCs in this literature are all leakage (§3).

### 1.4 Execution — one part of the bot was already right

- **AMM impact is path-independent** (Angeris et al.): N slices yield exactly the same proceeds as
  one shot at zero fee, strictly less with fees. Almgren-Chriss slicing has no basis in a CFMM —
  the rate-dependent temporary impact term is identically zero, so the optimal half-life is zero.
  **The single-shot full-bag exit is correct. Never build the TWAP.**
- **Round-trip identity:** buy `B` SOL of a token and sell straight back in the same pool → exactly
  `B` minus fees, at any depth. Impact self-cancels. So the 0.80 → 0.031 SOL disasters were *not*
  execution failures; they require the pool's SOL side to have fallen ~80% from other people's
  selling.
- **The real execution bug is `slippage_bps: 1500`.** It hands sandwichers their unconstrained
  optimum (~1.9% tax on a 1 SOL exit, ~6.3% at 3.5 SOL in a $30k pool), degrades Jupiter's own
  routing toward selfish routing, and guarantees filling into a collapsing pool. Fix: compute
  `minOut` from live reserves, allow ~200–300bps for slot drift, keep wide only on the panic path.
  Then submit via Jito/MEV-protected RPC, which removes the channel rather than pricing it.
- **Stops:** Kaminski & Lo — negative expected value under a random walk, positive only under
  momentum. At 50%/hr vol a −10% stop is hit within ~5 minutes on pure noise, a −20% within ~21.
  Anything tighter than ~30% is a coinflip. Prefer time-boxes; gate any stop on measured
  sell-intensity rather than price alone.
- **Size the entry so the exit is a non-event:** `ρ_exit = B/Y` exactly, slippage `= B/(Y+B)`.
  Refuse entries above ~2% of a pool's SOL side. One line, uses state already fetched.

### 1.5 Methods — what survives at our data scale

Everywhere this domain has been honestly measured, **hygiene and simple statistics beat
architecture**:

- A zero-parameter hash table (EdgeBank) ranks 2nd across 13 temporal-graph benchmarks; on the crypto
  benchmark it ties TGN, and a decayed popularity counter beats both by 14 MRR points.
- On Elliptic under strict-inductive evaluation, **random forest on tabular features beats every
  GNN** (F1 0.821 vs GraphSAGE 0.689 ± 0.017) — and *randomly shuffled edges outperform the real
  transaction graph by 8.9 F1 points*. Read the fine print, though: the paper's largest effect is not
  about model class at all. GraphSAGE scores **0.294 transductive vs 0.689 inductive** — a 39.5-point
  paired gap (d = 15.8, p = 2.6e-12) "explained entirely by training-time exposure to test-period
  adjacency." That is a *leakage* finding, and it binds us whatever architecture we pick. Run
  leakage-free, the graph branch still contributes a real **+0.018 F1** over a matched-capacity MLP —
  small, but not zero — and the authors attribute the harm specifically to Elliptic's "sparse,
  prior-shifted conditions." A dense memecoin co-trading graph is not obviously that regime.
- Union-find over funding relations does the work that GNNs claim; the only GNN wash-trading paper
  is perfectly circular (labels from DFS cycles, features from centrality on the same graph).

Per-token estimation is hopeless at 10²–10³ events, and the fix is structural: **pool the shape
globally, estimate one or two scalars locally.** Hierarchical beats both extremes quantitatively:
pooled branching 0.899 (biased up, mega-units dominate), unpooled 0.717 ± 0.139 (prior-dominated),
**partial 0.742 ± 0.026 — same answer, 5× sharper**.

**SEISMIC was the cited template for that, and reading it retracts the citation.** The first draft
described it as "global kernel fitted once across thousands of cascades … ~15% error on final size
after 10 minutes, on cascades with median 110 events." Verified against arXiv:1506.02594, three of
those four clauses are wrong and the transfer has a blocking finding:

- **"Thousands of cascades" is fabricated** — the word "thousand" appears nowhere in the paper. The
  kernel is fitted from **15 hand-picked tweets**, chosen precisely because their authors had enormous
  follower counts so that reshares are first-generation and the raw reaction time is directly
  observable. That is not a pooling estimator; it is *deconvolution avoidance*. The transferable idea
  is much sharper than "pool": **find a sub-population where the primitive is directly observable and
  measure it there.**
- **"15% at 10 minutes" splices two halves of one sentence.** 15% is the **1-hour** figure; at 10
  minutes it is **25%**. It is *median* APE (95th percentile at 10 min is 71%), measured against
  `R₁₄days` rather than true final size, from a model with ~10 fitted calibration constants tuned to
  minimise that very metric.
- **"Median 110 events" is right but backwards as evidence.** It is the training-set median after
  filtering 3.2B tweets to 166,076 with **≥50 retweets**, and predictions only begin *once a cascade
  reaches 50 events*. So the task is a 2× extrapolation from a hard floor — evidence that SEISMIC
  needs 50 events before it will speak, not that it works at our scale.
- **Blocking: it requires per-node out-degree `nᵢ` in every equation** — intensity, both accumulators,
  the infectiousness estimator, the prediction formula, and the criticality threshold `p* = 1/n*`.
  `nᵢ` is the *denominator* of `p̂ₜ`. Without it `p̂ₜ` is undefined, not degraded. A wallet buying a
  fresh mint has no follower count, and the only available substitute — constant `nᵢ` — collapses the
  model into the RPM family, which the paper measures as **worse than linear regression** in exactly
  the early window we care about.
- **Its kernel carries no shape in our window.** `φ(s)` is *flat* below 5 minutes by construction, so
  the globally-pooled object degenerates to a constant precisely where we operate. Worse, from the
  paper's own fitted parameters (`θ = 0.242`, `c = 6.27e-4`, `s₀ = 300s`; normalisation checks to
  0.965): **81% of reaction mass arrives after 5 minutes, the median reaction time is ~36 minutes, and
  the mean is infinite** (θ < 1, so the tail integral diverges). Against Marino's 4.4-minute median
  time-to-graduation that is the wrong timescale by roughly 8×.
- **It also cannot anchor the hierarchical argument above** — it has no prior over `pₜ`, no shrinkage,
  no random-coefficients structure. It is a *fully-pooled-shape model with an unregularised per-unit
  MLE*: the baseline partial pooling would improve on, not an instance of it.
- **No saturation term at all.** The underlying branching process has no exhaustion mechanism — fine
  when a 110-event cascade runs against hundreds of millions of users, first-order wrong for a token
  whose buyer population is small, finite, and observable in the pool. For us, exhaustion *is* the
  dominant dynamic and the thing that decides when to exit.

**What does transfer, and is what we should have cited:** (i) the **ranking** result — 78 of the top
100 cascades recovered within 10 minutes on a 500-wide shortlist — because top-k selection over a live
universe is our actual problem, and rank is far more robust to a miscalibrated scalar than a point
estimate is; (ii) the **O(Rₜ), 0.02s-per-unit** online cost, 180× faster than its nearest rival, which
is what makes any of this family viable in a live loop. (iii) And the honest floor it establishes:
plain log-linear regression, `log R∞ = αₜ + log Rₜ` — literally "scale the current count by a
time-dependent constant" — **beats both competing point-process models early**. That is one line of
code and it is the first thing any cascade model of ours must beat.

The name for why 3-token pooling produced incoherent signs: **Pesaran & Smith 1995** — pooling
dynamic panels with heterogeneous slopes is inconsistent and misleading. (Their own prescription is the
*mean-group estimator*; hierarchical/EB shrinkage is the Swamy random-coefficients route — a fine fix,
but not the one P&S wrote.) Empirical-Bayes shrinkage buys **18.8% RMSE reduction on real fund alphas**
(Huij & Verbeek Table 11: 1.12% → 0.91%, t = 9.98). The ~40% figure quoted in the first draft is from
their *Monte Carlo*, where the data-generating process is exactly the estimator's assumed prior — the
best case a correctly-specified prior can buy, not an empirical result. Note also that they shrink
toward a **common** cross-sectional mean; the *group*-conditional variant this document prescribes is
the one they tested and found marginal (0.26% → 0.28% top-decile alpha, "the benefits from using
conditional priors are only marginal"). Shrinkage is applied to betas as well as alpha, and is stronger
for short histories — at our record lengths a wallet is pulled essentially onto the group mean, so what
this buys is **ranking across many units, not per-unit identification**.

---

## 2. Architecture

```
  firehose ──► TAPE (/tank, JSONL)         ← record first; it compounds regardless
                 │
                 ├─► LEAN KERNEL           ← fills, accounting, DSL causality, envelope
                 │      @[export] → C → linked from Rust/Python
                 │
                 ├─► REPLAY + SEARCH       ← exact AMM fills; MAP-Elites over DSL terms
                 │      GPU-vectorized on hbox
                 │
                 └─► ONLINE                ← bandit over archive elites, dust size
                        │                     propensity-logged, OPE recycles every trade
                        └─► ENVELOPE ──► signer
```

**Why Lean for the kernel, specifically.** Not purity — *drift resistance under agent contribution*.
2026-08-12 was the controlled experiment: plausible-looking generated Python shipped two money-losing
bugs (provenance, protocol ordering) that survived everything except an external audit. Care doesn't
scale across agent contributors; types do. In scope:

- **AMM fill semantics** — constant-product and the bonding curve are exact integer/rational algebra.
  Round-trip identity, path independence, monotonicity, `minOut` bounds realized output. No analysis,
  no measure theory, mathlib-comfortable, few hundred lines.
- **Accounting** — cost basis as a *provenance type*, constructible only from observed chain fills.
  The −7.47 SOL bug becomes inexpressible. Lot state machines. "No second order while a prior
  signature is unresolved."
- **Strategy DSL** — strategies as terms over a causally-indexed history type, so **lookahead is a
  compile error**. The effective trial count `N` for deflated-Sharpe becomes the *cardinality of the
  grammar* — certifiable rather than guessed.
- **Envelope** — see §5.

Out of scope: estimator theory (research-grade formalization, months per result — statistics stay in
Python), and the async I/O shell (the burden there is the environment model, and a proof against a
wrong model of Jupiter's confirmation semantics is false confidence).

**No floats in the kernel.** ℤ lamports and raw base units throughout. Floats are where proofs die,
and the raw-units/UI-amount/lamports/SOL confusion is a real live hazard.

If throughput ever demands it: a Rust fast path **differentially tested against the proved kernel as
oracle** over millions of random tapes. (Case tests prove nothing formally — this is engineering
discipline, not verification, and should never be described as the latter.)

---

## 3. Methodology standard — non-negotiable

Every one of these was violated by published work we read, with measurable consequences.

1. **Temporal splits only.** Random-vs-temporal on the same model and corpus is worth **54 points of
   recall** (0.778 → 0.234). Ten times any sampling error.
2. **Entity-level grouping.** Cluster wallets first, then split — one actor must never straddle
   train/test. Scam campaigns share deployers; clone families share bytecode.
3. **Never SMOTE/resample.** SMOTE-before-split manufactures **AUC 0.95 from uniform noise**; eleven
   published studies' 88.8–99.4 corrected to ~47–65. It also destroys the calibrated probability an
   EV decision needs. Use natural base rates + proper scoring rules.
4. **Baselines before models.** EdgeBank-style memorization, decayed popularity, and gradient-boosted
   trees on tabular features — *all three* — before anything fancier. On current evidence they win.
5. **Base-rate-preserving metrics.** AUPRC and precision@k, never accuracy or ROC-AUC at 74–98% base
   rates. Precision `= πr/(πr + (1−π)f)`; do the arithmetic yourself.
6. **Per-window metric breakdowns.** Aggregate reporting hides regime collapse — Elliptic's models
   fell ~244× after a single market shutdown. The pump.fun regime shifts in weeks.
7. **Report the threshold with every number.** The same NFT market yields wash estimates from 0.12%
   to 94.5% depending purely on knob settings. There is no ground truth in this field.
8. **Clock-based censoring, never displacement-based.** Verify the pipeline by checking that observed
   time-to-graduation reproduces Marino's median 4.4 min *with a tail*. If your max is ~5 minutes,
   your instrument is truncated.
9. **Trials accounting.** After ~7 independent configurations, expected best in-sample Sharpe of 1
   corresponds to OOS zero; 5 years of data supports ~45. The DSL grammar makes `N` computable.
10. **Run the null.** Inhomogeneous-Poisson-with-decaying-μ and history-independent constant
    intensity. If they tie, there is no self-excitation to model.
11. **JSONL, not CSV.** Memecoin symbols contain commas, quotes, and newlines by design.
12. **Both controls, always — a null control alone is worthless.** Every estimator must be run
    against a known-ZERO world *and* a known-EFFECT world. An instrument that detects nothing
    passes a false-positive test perfectly, so a green zero-control certifies a broken
    estimator exactly as readily as a working one. Independently discovered twice here: the
    callout lane found a constant-zero estimator passing its known-zero test and failing only
    recovery; the co-trading lane shipped a degenerate ranking (a z-score under a zero-variance
    null scored every unreached pair `+inf`) that its zero-coordination control stayed green
    through for a full iteration, and only planted recovery caught.
13. **Two nulls, compared at matched DENSITY.** Validated-link density varies by an order of
    magnitude across null models at the same p-value, so a single null is a knob, not a test.
    Measured here on co-trading: 16× spread in edge count between the hypergeometric and
    degree-preserving nulls at nominally comparable thresholds, and only 29% edge agreement
    (Jaccard 0.169) at matched density on a world where the clusters were *planted*. Hand only
    the intersection downstream. The stakes: with zero planted coordination but heavy-tailed
    activity and active wallets — exactly the population worth studying — Bonferroni FWER
    measured **0.600**, and BH produced **~99 confident clusters out of nothing in 30/30
    worlds**. The degree-preserving null deleted 100% of them.

**Instrument checks we owe ourselves.** Exponential-kernel Hawkes on a launch tape is biased in
*both* directions: kernel misspecification pushes branching down (true kernels are power-law), while
non-stationarity pushes it up — concatenated pure-Poisson segments with a varying baseline yield
n̂ ≈ 1 from true zero, and a launch-decay ramp is that exact pathology. Cheap controls: simulate
inhomogeneous Poisson with the empirical decay profile at true n=0 and see what the pipeline reports;
and compute the kernel-free estimator `n̂ = 1 − 1/√Fano(W)` whose W-scaling doubles as a long-memory
diagnostic.

*Verified against Hardiman & Bouchaud (1403.5227), with one qualification our earlier draft omitted:*
the mean–variance estimator is **biased downward at finite W** — "σ²_W/W is a biased estimator … and
will generally under-estimate the branching ratio, becoming exact only in the limit W → ∞." So a low
n̂ from this control is not evidence of low endogeneity; it is the floor. Use it to *refute* a high
Hawkes-MLE branching ratio, never to confirm a low one. The sanity anchor is exact: Fano = 1 ⟺ Poisson
⟺ n = 0.

**Burstiness, if we ever compute it.** Goh–Barabási `B = (r−1)/(r+1)` on `r = σ/μ` of interevent times
has a hard finite-size ceiling, because `r ≤ √(n−1)`. Exactly, `B_max(n) = (√(n−1) − 1)/(√(n−1) + 1)`
— **0.817 at n = 100**, of which the familiar `1 − 2/√n` (0.80) is the large-n asymptotic. So B is
confounded with event count and **cross-token B comparisons at different trade counts are invalid**.
Kim & Jo's replacement (their eq. 22) has no such bound and is a two-line change:

```
A_n(r) = (√(n+1)·r − √(n−1)) / ((√(n+1) − 2)·r + √(n−1)),    0 ≤ r ≤ √(n−1)
```

Their framing is exactly our use case: "if two event sequences have the same r but different n, the
original burstiness parameter cannot distinguish which is more bursty, while our novel measure can."

**Live bug in our harvested numerics:** `shitcoims_intelligence/numerics.py:29` is the naive Gini —
downward-biased at small n, pathological under infinite variance (which *is* the holder distribution),
and computed over a deliberately fragmented address set. Bundle-correct it or drop it.

---

## 4. Signal queue

Ranked by (evidence it could work) × (feasibility now). Helius Developer is $49/mo for 10M credits;
`getTransactionsForAddress` costs 10 credits per 100 txs. Parse raw — the Enhanced API is 100
credits/call.

| # | Signal | Method | Cost | Status |
|---|---|---|---|---|
| 1 | **Coordinated-cluster detection** | SVN: hypergeometric null on **nine typed** (buy/sell/round-trip × same) co-occurrences per wallet pair, **pair-specific T**; Bonferroni for specificity, BH-FDR for coverage; drop opposite-action links; **weighted Infomap — not union-find** | 300 tokens × 5k trades = **1.5% of monthly credits** | **Read §4.1 before spending a credit.** The power claim was ours, not the paper's, and it was wrong |
| 2 | **Funding-tree entity resolution** | First-funder + deposit-address reuse, CEX exclusion; then bundle-adjusted concentration delta | 50k wallets ≈ **10%** | Prerequisite for everything else. MELT recipe is fully specified |
| 3 | **Callout → flow latency** | Intensity response on mint-resolved callouts vs hour-matched baseline, hierarchically pooled across tokens | store already collecting (28 mint-resolved/day) | Genuinely unexplored. Pipeline exists end-to-end; grok's eval ran n=0 only because events were never wired to the tape |
| 4 | **Organic vs manufactured flow** | Union-find + position-netting + PnL-negativity + funding ancestry. Exclude same-slot atomics (MEV is the dominant false positive) | CPU once local | The classifier *is* the alpha — everyone can detect callouts; separating real from farmed is the edge |
| 5 | **Deployer ancestry prior** | Creator history extended from "this creator" to "this creator's wallet cluster" via (2) | cheap | Only published variable that ever beat breakeven; undermined solely by small n, which clustering fixes |
| 6 | **Population skill *fraction*** (not a per-wallet screen — see §4.2) | Storey π̂₀ over a **jointly**-randomized null on a shared clock; report a proportion, not per-entity verdicts | CPU, but needs **breadth** | Rewritten. Both numbers in the original row were fabricated, and the per-entity framing is unsupported by its own sources |
| 7 | **Rotation / attention flow** | `F[i,j,t]` = SOL moved token i→j through shared wallets; cluster tokens by wallet overlap; lead-lag on flow | moderate | Direct observation, no inference needed — the thing equities must estimate, we can read |
| 8 | **Rug model** | MELT recipe: pre-migration behavioral + bundle features → GBM, chronological split | moderate | Calibrate to AUPRC ≈0.58 and a still-negative naive backtest |
| 9 | **Metaorder reconstruction** | Splitter-vs-random wallet classification; measure `P(L) ∝ L^{−α−1}`, check `γ = α−1` | moderate | Took nine years of privileged exchange access to do once (PRL 2023). Public firehose here. Unpublished in this domain |

**Not worth it:** token-level Diebold-Yilmaz or Granger networks (parameter counts, nonsynchronous
artifacts — do sector indices at N≤10); cross-impact matrices (O(N²), and the flow-correlation
structure carries the content anyway); any GNN (no honestly-evaluated win on any blockchain task);
full-universe wallet screening (1M+ wallets ≈ 5 months of credits).

**Known anti-signals:** liquidity-locker contracts (~90% of tokens that used them still rugged);
raw top-10 holder share; PnL leaderboards (several top-10 wallets in Marino's data executed
*only sells* — 1,793/1,793, 632/632 — they are aggregation/exit-liquidity addresses, not traders).

**Copy-trading reality:** identified smart money averages ~14%/trade while a copier gets ~3% from
bonding-curve imitation penalty alone, before MEV — and adversaries deliberately build
profitable-looking wallets to bait copiers. Any follow-the-wallet strategy must clear that gap.

### 4.1 Signal #1, corrected against Tumminello (arXiv:1107.3942)

The first draft of the row above was written from a summary. Reading the paper broke it in four places,
and one of them was arithmetic.

**The power calculation was never in the paper.** Tumminello contains *no* power analysis at all — no
MDE, no sample-size calculation. The "overlap ≥5 → p ≈ 3e-6–5e-11" figure was our own construction, and
its conclusion was **false**. Bonferroni at `pt = 0.01` over `10⁶` pairs with nine tests each is
`0.01/(9·10⁶) = 1.1e-9`. The quoted `3e-6` misses that by ~2,700×; only the `5e-11` end — two wallets on
exactly 5 of 300 tokens overlapping on all five, i.e. the single most favourable configuration in the
range — clears. Worse, `10⁶` pairs is only ~1,415 wallets. Signal #2 plans **50k**, giving 1.1e10 tests
and a threshold of `8.9e-13`, while the *minimum attainable* p for a 5-of-300 pair is `5.1e-11`. **At
that scope no such pair can ever validate, regardless of the data.** Pairs grow as n²; the claim did not
survive one order of magnitude.

The honest form is a feasibility gate, checkable before spending anything:

```
C(T, N) ≥ 9·n(n−1) / (2α)          T = tokens, N = tokens per wallet, n = wallets
```

And "overlap ≥5" is not a criterion in the first place — significance depends on `λ = Ni·Nj/T`. For the
*active bot wallets we actually want*, the rule inverts: two wallets each on 100 of 300 tokens have
λ = 33, so an overlap of 5 is **under**-expressed, p ≈ 1.

**Three method errors.** (i) It is **nine typed tests per pair**, not one — a 3-state variable (buy /
sell / both) crossed with itself, which is exactly where Bonferroni's ×9 comes from. (ii) **Union-find
is not in the paper and does not work**: connected components give one blob holding 99.6% of the FDR
network and 81% of the Bonferroni network. Clustering is **weighted Infomap**, weights = count of
validated co-occurrences (1–3). (iii) `T` is **pair-specific** — the intersection of the two actors'
activity periods, defined by holding *anything*, not by activity in the studied asset. Using a global T
for a short-lived wallet inflates significance, and short-lived wallets are our whole population.

**The blocking risk, and it is not small.** The hypergeometric null assumes roughly uniform marginals
across the index; the paper justifies this explicitly because Nokia's daily state counts fluctuate over
"a range smaller than one decade" (§3). Memecoin activity is a launch spike with power-law decay —
*several* decades — and token popularity is heavy-tailed. Under a non-uniform baseline the
hypergeometric massively overstates significance: everything co-occurs in the first minutes by
construction, the null validates nearly every pair, and the output is a dense meaningless network.
**A stratified or configuration-model null is a precondition, not a refinement.**

**What we should steal that we had missed.** The paper carries a *second* hypergeometric layer for
over/under-expression of cluster attributes — precisely the tool for "is this cluster over-expressed in
rugs, in sniper labels, in one deployer's tokens," and it is also the paper's only real validation.
Also note the recipe **removes opposite-action links before clustering**; for us those are the likeliest
wash-trading signature, so adopting it verbatim would discard the thing we most want to see.

**Finally, calibrate expectations:** this paper does *no* economic validation — no returns, no PnL, no
predictive test (it defers that to a companion paper), and only 7 of its 30 largest clusters show any
validated compositional signature. It establishes that coordinated groups are *detectable*. It
establishes nothing about whether detecting them pays.

### 4.2 Signal #6, rewritten against Barras/Scaillet/Wermers, Fama–French, and Huij–Verbeek

The original row cited "3.14% skilled, 44% of skilled classifications persist OOS." **Neither number
exists in any of the three papers.** "3.14" appears twice in Fama–French Table IV — once as a
percent-of-simulations count, once as an average simulated t(α) — both unrelated to a skilled
proportion. "44%" appears nowhere; the nearest real figures are a 36.7–55.9% *portfolio turnover*
retention (funds re-selected by the same rule a year later, on an 80%-overlapping formation window —
not out-of-sample persistence of a classification) and **41.5%, which is the achieved FDR: the fraction
of the portfolio that *are* false discoveries.** We had cited the failure rate as if it were the
success rate.

**The real benchmark, stated honestly.** Barras' headline is **75.4% zero-alpha, 24.0% unskilled, 0.6%
skilled** — and of that 0.6% they write it is *"statistically indistinguishable from zero"* and that
they *"cannot reject that all of the right tail funds are merely lucky."* The flagship application of
this technique returns a **null**. Their FDR portfolio earns 1.45%/yr out-of-sample while holding 41.5%
false members, retains 36.7% of picks after one year and under 6% after three, and its edge
*"consistently declines"* to nothing by the mid-2000s. That is the bar — worth knowing before writing
"beat or match" next to it.

**Why the per-wallet framing has to go.** Power in this literature comes from **M (cross-sectional
breadth), never from T**, and it buys a *population parameter* — π₀ or σ — not per-entity verdicts.
Fama–French say it outright: *"The source of the power is our large sample of funds."* Neither paper
claims to identify an individual skilled fund; Barras explicitly decline to. So the defensible version
of #6 is **"what fraction of wallets are skilled"**, which is cheap and well-supported — and which
requires exactly the breadth §4's "not worth it" list rules out on cost. **That contradiction is
unresolved and must be resolved before this signal is built.**

**Four ways the sign-randomization null breaks, in severity order:**

1. **Cross-wallet dependence — the failure mode Barras name as unrecoverable.** They write that under
   perfect herding "the p-value histogram would *not* converge... we would make serious errors no matter
   where we set λ*." They escape only by measurement: mean residual correlation **0.08**, and 15% of
   fund pairs share *zero* months. Wallets long the same token in the same minute are correlated ≈1 by
   construction. Fama–French quantified the cost of ignoring joint structure: a significance statistic
   falling from *">99% of runs"* to **68–82%** once months are sampled jointly, biasing inference
   **toward false positive performance**. Independent per-wallet flips are the maximally wrong response.
   Fix: randomize **jointly on a shared clock**, or block-permute the token's price path.
2. **Discrete p-values break Storey.** π̂₀ needs a near-uniform histogram above λ*; a k-trade wallet has
   2^k sign assignments (a 12-trade wallet floors at p ≈ 2.4e-4). π̂₀ is biased **up**, the skilled
   proportion biased **down** — yielding an unfalsifiable "no skilled wallets" that is indistinguishable
   from a true negative.
3. **The null is not risk-adjusted.** Both papers measure alpha against a factor benchmark; π₀ is a
   statement about a *residual*. Sign-flipping raw wallet PnL adjusts for nothing, so "everyone long a
   token that went up" scores as skill in every long wallet. **We have never defined what a wallet's
   alpha is relative to.** That is the prerequisite question.
4. **Every sample-length floor is violated by an order of magnitude** — Barras ≥60 monthly obs,
   Huij–Verbeek >12, Fama–French ≥8 (and they flag *8* as a tail-bias source). Our wallets have tens of
   trades. Plus: flipping directions preserves timing exactly, so the test has power only against
   *directional* skill and none against timing, sizing, or exit skill — which is where a memecoin edge
   would actually live. And own-trade price impact (§1.4, `ρ_exit = B/Y`) means the flipped sequence is
   not a realizable history at all.

**Terminology.** "Storey π₀ + BH" misnames the method: Barras split two-sided p-values into tails
(`F̂γ± = π̂₀γ/2`) and target a right-tail **FDR⁺**, explicitly *"an extension of the traditional FDR...
since the latter does not distinguish between bad and good luck."* It is not BH, and calling it BH here
collides with §4 #1's genuine BH-FDR, making two different methods read as one.

**The deeper tension our first draft got backwards.** Fama–French never cite Barras — they pass in the
night, both JF 2010, and the "dispute" is literature-level, not in-paper. The *live* disagreement is
structural: Barras impose a **point mass at exactly α = 0** carrying π₀ ≈ 75%; Fama–French model true α
as **continuous** (normal, σ ≈ 1.25%/yr pre-expense), under which the mass at exactly zero is zero and
"75.4% are zero-alpha" is not a well-posed statement. Under a continuous truth, every small-but-real α
produces near-uniform p-values and is **absorbed into π̂₀**. That is the low-power critique in its
structural form, and it applies to any π₀-based screen we build. (They agree on the headline, though:
net of costs skill is undetectable; pre-expense there is real dispersion in both tails.)

**Unresolved, and worth a line in §3:** multiplicity is now accounted **twice and never composed** —
§3 rule 9 counts trials over the DSL grammar, §4 #6 corrects FDR over entities. If a wallet screen feeds
strategy selection, the trial counts *multiply* and neither correction covers the product.

### 4.3 What a wallet's alpha is measured against

§4.2 surfaced the hole: both fund papers measure alpha against a factor benchmark, π₀ describes a
*residual*, and we had never said what a wallet's return is a residual **of**. Raw PnL adjusts for
nothing — under it, everyone long a token that went up scores as skilled. There is no CAPM for
memecoins and there will not be one, so this is a design choice. The honest move is to choose a
benchmark for its *properties* and state them.

**Required properties**, each one earned from a failure we actually hit:

1. Computable from the tape **at decision time** (no lookahead — §3, and the kernel's `View t`).
2. A no-skill wallet scores **zero in expectation**, exactly, not asymptotically.
3. Not corrupted by **cross-wallet dependence** — the blocker that killed the sign-randomization null.
4. Not corrupted by **discreteness** at tens of trades — the blocker that broke Storey's π̂₀.
5. **Survivorship-free**: dead tokens must enter with their real paths.
6. **Decomposable**, because timing skill and selection skill are different signals wanting different
   detectors, and conflating them is likely why one "skill screen" kept failing.

**The primary benchmark: a within-token timing permutation.** For a wallet's round trip on mint `m`
with entry `t_in`, exit `t_out`, duration `D = t_out − t_in`, hold `D` fixed and randomise *when*:
draw `t'` uniformly over placements where `[t', t'+D]` lies wholly inside the mint's `WatchWindow`, and
recompute the SOL return along the same recorded reserve path. The p-value is the fraction of
counterfactual placements beating the observed one.

Why this specific construction, property by property: token selection **cancels identically** because
every counterfactual is on the same price path (1, 6). It is an **exact conditional permutation test** —
no asymptotics, no π₀, no uniformity assumption, so discreteness is a non-issue (4). Crucially it
**dissolves the dependence blocker** (3): two wallets in the same token are no longer compared to each
other but each to counterfactual versions of *itself* on a fixed path, so the correlation that made
independent sign-flips invalid simply does not enter. Dead tokens contribute their real, bad paths (5).

**And note what it replaces.** The old design preserved *timing* and randomised *direction*. On
pump.fun you can only be long — there is no short — so the direction was never a real degree of
freedom, and randomising it tested a choice the trader never made. Timing is the live decision.
Inverting the permutation is not a patch; it is the difference between testing a decision and testing
an artifact.

**The secondary benchmark: selection, against matched controls.** Timing permutation is *blind* to
selection by construction — a wallet that only ever buys eventual winners but times them averagely
scores zero. That component needs the control-mint machinery now specified in SWARM.md Track B: for an
entry on `m` at curve position `v` and time `t`, compare `m`'s forward return to controls matched on
launch bucket, vSol band, and hour-of-day. It is second because it *requires collection we do not yet
have*, whereas timing permutation runs on the tape as specified.

Together they are exactly §5's attribution decomposition — *entry selection, exit timing, induced
reaction* — which means the envelope's attribution monitor and the wallet-alpha definition are the same
object viewed from two directions, and should be built once.

**Decided (2026-08-13): report the interaction term separately.** Selection and timing are not additive
in log-return once fees and price impact enter. Of the options — attribute the cross term to one side,
split it, or report it — reporting is both the cheapest and the only reversible one. It costs nothing
to compute (it is the residual, `total − selection − timing`) and one column to display, whereas any
attribution rule needs a justification, invites quiet gaming, and **cannot be undone** once numbers are
built on it. Equity performance attribution hit this exact three-way problem long ago and settled on the
same answer for the same reason. It also carries information: a large interaction means selection and
timing are not separable on this desk — that the wallets picking well are the wallets timing well, or
that costs are eating the decomposition — and that is a finding, not noise. If it turns out negligible
we can stop reporting it; the reverse is not available.

---

## 5. The envelope

The learner proposes; the envelope decides. Same pattern as `transaction.py` treating Jupiter as
adversarial, lifted one level: **our own learner is an untrusted proposer behind a verified gate.**

Constraints (small, typed, Lean-kernel territory):

- per-trade size cap as **both** bankroll fraction and pool-impact cap (`ρ = B/Y ≤ θ`)
- aggregate exposure cap
- daily loss budget with circuit breaker
- single-wallet operation
- no same-wallet short-window round trips (wash-shaped *and* scientifically worthless)
- kill switch

The theorem worth proving: *no action sequence the envelope admits can exceed exposure X* — quantified
over **all possible learners**, which is the only guarantee worth having about a component we don't
fully understand.

**Reward must be realized SOL** computed from wallet deltas by the verified accounting kernel. Never
mark-to-market on a bag the learner itself holds (self-referential reward), never intermediate
proxies like "price moved after my buy" (selects for noise-chasing and overfits).

**Propensity logging is the whole ballgame.** Every action logged with the probability/policy state
that generated it, at decision time. That single habit makes the tape counterfactual-ready — off-policy
evaluation, doubly-robust estimates, "what would policy B have earned on policy A's data." None of it
is reconstructible later. With it, every trade is a small randomized experiment; without it, our own
trades are just more observational data.

**Attribution monitoring:** decompose realized PnL by mechanism (entry selection, exit timing,
induced reaction) so that where the edge lives is a finding, and what to do about it is a policy
decision made with full information.

---

## 6. Build order

1. **Tape recorder → `/tank`.** Launches, trades, reserve states, callouts, time-aligned, JSONL,
   clock-censored. *Data compounds regardless of which strategy wins; it cannot be recorded
   retroactively.* Bootstrap history from MELT (41k tokens, 218M txs, crawled Jito bundle traces —
   not reconstructible from chain) and RED-PUMP (860k launch records, CC-BY-4.0) — the latter as a
   launch-metadata corpus only, since its outcome labels are displacement-censored.
2. **Harden the live sentinel in place** (do not stop it to rewrite): cost basis from chain,
   double-submit fix, computed `minOut`, Jito submission, executor tests against fake Jupiter/RPC,
   config race, address ceiling, `--status` executing under `--live`, failed-intent auto-resume.
3. **Lean kernel:** fills → accounting → DSL → envelope.
4. **Replay + search harness:** exact AMM fills, MAP-Elites over DSL terms, OPE over our own logged
   trades, purged walk-forward, honest trials accounting.
5. **Signal queue** §4, in order, through that machinery.

---

## 7. Reading list

**First five.** Marino/Lillo arXiv:2602.14860 (our exact problem, by half the order-flow canon —
start here, it sets the ceiling) · Hardiman & Bouchaud arXiv:1403.5227 (8pp, kernel-free branching
ratio from statistics we already compute) · Filimonov & Sornette arXiv:1308.6756 (read as a threat
model: every way a Hawkes fit lies, with numbers) · Prata et al. arXiv:2308.01915 (82.6% → 59.2%;
twenty minutes saves a month of deep learning) · Kim & Jo arXiv:1604.01125 (6pp, fixes the burstiness
finite-size bug).

**Then.** MELT arXiv:2602.13480 (evaluation protocol + economic eval) · SEISMIC arXiv:1506.02594
(the architecture to copy) · Tumminello et al. arXiv:1107.3942 (statistically validated networks) ·
Barras/Scaillet/Wermers JF 2010 (FDR framework) + Andrikogiannopoulou & Papakonstantinou JF 2019
(its low-power failure mode, which is our regime) · Bailey/Borwein/López de Prado/Zhu, *Notices of
the AMS* 61(5) (trials accounting as a theorem) · Bouchaud/Bonart/Donier/Gould, *Trades, Quotes and
Prices* ch. 10–13 (the one book).

Local corpus: **`~/paperbin/`** — 93 papers, PDF plus extracted `.txt`, flat
`descriptive-slug[-arxivid].pdf` naming (e.g. `marino-lillo-pumpfun-token-success-prediction-2602.14860`,
`melt-memecoin-behavioral-trace-dataset-2602.13480`, `tumminello-statistically-validated-investor-clusters`).
Grep the `.txt` companions to search the corpus without opening a PDF. Two papers are image-only scans
with no text layer (`lo-mackinlay-nonsynchronous-trading`, `lo-mackinlay-contrarian-profits`).

---

## 8. The dissipation reframe (2026-08-13, operator's insight)

The operator's circuit intuition reorganized the program, and the mapping is literal, not poetic:
a CFMM pool is a nonlinear capacitor (reserves = charge, marginal price = voltage, `x·y=k` the V–Q
curve); the token graph is a circuit (pools = edges); no-arb is KVL with a dead band whose width is
the fee sum around the cycle; exogenous order flow is EMF injection; a measured ratio half-life is an
RC constant.

**Corrected by the formalization (studies/RESULT_circuit_model.md, which derived rather than
analogized):** three identities are exact — `C = w_x·w_y·TVL` (TVL/4 at 50/50, verified to 6 s.f.), a
DLMM is strictly a *series battery-cell stack* (C = ∞ inside a bin, 0 at an edge, concentration factor
`4/W ≈ 5–20×`), and the per-swap energy ledger closes to 94–98% with the gap being exactly the
third-order term. But two of this section's original components were **wrong**: (i) fees are *not*
I²R — dissipation is linear in |flow|, so the fee element is a **back-to-back diode pair**, and the
no-trade band is literally the diode dead-zone; (ii) **liquidity sets capacitance, not conductance** —
price displacement scales with accumulated charge (`V = Q/C`), not current. The only genuinely ohmic
element is *behavioural* — arbitrageur response — and it is the model's single free parameter,
identified rather than fitted via `R = τ/C` with both sides measured.

**The reorganizing sentence, corrected: everyone in this market predicts voltage; the money is in
owning the junctions.** Fee income is the diode forward-drop collected on every crossing — direction-
indifferent, prediction-free. It explains the audit trail in one line — every verified-then-collapsed signal
(§4.1–4.3, the SEISMIC retraction) was a voltage-prediction claim; every revenue stream that survives
audit is a tax on current (creator fees, LP fees on token-token pools at 26–159%/day turnover,
studies/RESULT_swing_cluster.md), indifferent to flow direction.

What this **changes**:

- **Measurement is state estimation, not label prediction.** The tape's job is "where is charge
  accumulated, where is curl standing, where is flow organic" — questions answerable *now* — not
  "which token graduates," a question the whole literature failed. The §4 queue reorders accordingly:
  state-measuring signals (#1 coordination = manufactured-EMF detection, #7 rotation = current
  mapping) over outcome-predicting ones (#8 rug model).
- **A new first-class object: the network map.** Live graph of the cluster — per-edge conductance,
  charge state, curl residual, which edges are *ours* — merging the flow tape, the panel, and the LP
  meter. This is the desk's actual dashboard, and it is interface-shaped (candidate #9 in SWARM.md's
  manifest).
- **A move the old frame could not see: deliberate edge creation.** Placing a pool between two
  communities that lack a low-resistance path makes us the monopolist wire on a route flow wants to
  take (the $0-TVL SOLVE/DREGG pool is an unbuilt instance). Pool placement is a *strategic* decision
  now, informed by measured relative-vol + reversion + absence of competing paths.
- **The closed loop is legitimate and measurable.** The DREGG null (community activity → ~1.86×
  volume, no durable price effect) reads in this frame as: *the operator can drive current through
  their own resistors.* Volume-linked income plus volume-driving capability is a feedback loop the
  desk owns end-to-end; the callout-latency machinery measures its gain.
- **Identification we already own:** the scalper's ε-explored entries are propensity-logged randomized
  current injections — the experiment the cross-impact literature cannot run (Capponi–Cont's
  propagation-vs-common-flow confound dissolves under randomized injection). Impedance spectroscopy
  fell out of infrastructure built for a different reason.

What this does **not** change: the envelope and its theorem (an exposure cap quantified over all
learners is exactly "no action sequence can overcharge the book"); the verification discipline of §3;
the scalper's clock-exit logic; the base rates. And it names the frame's own failure mode honestly —
**capacitors leak.** Every fee stream is denominated in cluster tokens; the cluster is one correlated
capacitor bank that can discharge together if the community dies. Discharge protection is structural:
cluster-level (not per-token) exposure caps, and harvested fees converted to SOL on a schedule rather
than left compounding in the bank.

---

## The bar

The results in this field that survived — `γ = α−1`, `β = (1−γ)/2`, `δ = ½`, Marchenko-Pastur — are
all **parameter-free relations between independently measurable quantities**. That is the standard.
"My model reproduces the stylized facts" is worth approximately nothing; one-line GARCH reproduces
fat tails and volatility clustering. Everything else is a simulation that typechecks.
