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
globally, estimate one or two scalars locally.** The deployed template is SEISMIC (KDD'15) — global
kernel fitted once across thousands of cascades, per-unit scalar infectiousness via a growing-window
estimator, ~15% error on final size after 10 minutes, on cascades with *median 110 events*.
Hierarchical beats both extremes quantitatively: pooled branching 0.899 (biased up, mega-units
dominate), unpooled 0.717 ± 0.139 (prior-dominated), **partial 0.742 ± 0.026 — same answer, 5×
sharper**.

The name for why 3-token pooling produced incoherent signs: **Pesaran & Smith 1995** — pooling
dynamic panels with heterogeneous slopes is inconsistent and misleading. Prescription is
empirical-Bayes shrinkage toward a group mean (Huij & Verbeek: ~40% RMSE reduction on fund alphas).

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
| 6 | **Per-wallet skill screen** | **Sign-randomization null** (re-run each wallet's exact sequence 10,000× with directions flipped), then Storey π₀ + BH over *entities* | CPU | Published benchmark: 3.14% skilled, **44% of skilled classifications persist OOS**. Beat or match that |
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

## The bar

The results in this field that survived — `γ = α−1`, `β = (1−γ)/2`, `δ = ½`, Marchenko-Pastur — are
all **parameter-free relations between independently measurable quantities**. That is the standard.
"My model reproduces the stylized facts" is worth approximately nothing; one-line GARCH reproduces
fat tails and volatility clustering. Everything else is a simulation that typechecks.
