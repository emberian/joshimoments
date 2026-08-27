# jupiter_conditional v1 — pre-registered conditional-settlement study

Registration version: `joshi.jupiter_conditional.registration.v1`
Registered: 2026-08-27, AFTER source-reachability/rate probes and BEFORE the fine series was
fetched and BEFORE any rule reconstruction, state, surface cell, or calibration number was
computed. Builds on `joshi.jupiter_base_rate.registration.v1` (same reference-approximation
stance; every number below is reference-approximate and says so).

**Governing principle (Ember, verbatim): "if we count the wrong thing."** Miscounting — the
wrong settlement rule, a leaky state, an unresolvable near-tie counted as resolved — is the
primary risk, above any model-capacity question. The study is ordered as gates: ground truth
first, resolution second, counting third, self-refutation (calibration) last.

## Author knowledge disclosure

Everything in the v1 disclosure, plus, known before this registration:

- Ten REAL settlement labels from the live collector (7 Up, 3 Down; 8×5m, 2×15m, all
  2026-08-27 13:45–14:30Z), inferred from post-close pinned pricing. More accrue every 5
  minutes while the collector runs; the gate will use all labels available when it executes.
- The v1 post-hoc spot check on 1-minute candles: whole-window-TWAP and endpoint rules each
  matched 3/4 real settlements, both missing POLY-915798 (a +2 bp Coinbase window that
  settled Down). The author therefore already knows rule (a) below missed one round at 1m
  resolution — one reason the finer series is a gate, not an option.
- Probe exposure: the last ~90 s of Coinbase SOL-USD trades and ~40 min of Kraken SOLUSD
  trades (SOL ≈ $107.5, i.e. it kept rising intraday); measured trade rates (Coinbase
  ≈950k trades/day; Kraken ≈35k/day) which fixed the source choice below. Binance is
  geo-blocked from here.
- No conditional statistic, no running-TWAP reconstruction, and no surface cell was computed
  before this registration.

Any deviation requires a new registration version; results under deviation must say so.

## Step 0+1 — ground-truth gate on the fine series (STOP condition)

**Fine series, chosen by measured budget (probes above):**

- Primary: **Kraken SOLUSD public trades** (`/0/public/Trades` since-walk, 1000/page,
  ns-stamped, USD-quoted), span **10 days** ending at fetch time (~350 requests; budget 500).
  This series must carry BOTH the gate and the surface.
- Cross-check: **Coinbase SOL-USD trades** (denser: ~11/s) over the labeled-rounds span only
  (2026-08-27 13:38Z → fetch time; budget 150 pages). Its role: attribute a Kraken gate
  failure to rule-wrong vs series-too-coarse.
- Both retained verbatim (raw body text + both clocks) under `state/prediction/fine/`,
  receipted, gaps durable. Still labeled **NOT settlement-exact** (venue basis vs the
  Chainlink aggregate, measured in v1 at ~2 bp median / ~6 bp p95 Coinbase-vs-Kraken).

**Price function**: p(s) = last trade price at or before s (step function). A boundary with
no trade in the preceding 120 s makes the window data-absent (excluded, counted). Arithmetic
in float64 (relative error <1e-9, far below the ~2 bp venue basis); ties at equality → Up.

**Candidate rules** (window [T, C], C = closeTime on the 300 s grid, H = C − T;
twap60(x) := (1/60)∫ p over [x−60, x]; wtwap := (1/H)∫ p over [T, C]):

- (a) `wtwap ≥ p(T)` — whole-window TWAP vs point start.
- (b) `twap60(C) ≥ twap60(T)` — the 60 s-TWAP stream read at both boundaries.
- (c) `p(C) ≥ p(T)` — raw endpoint.
- (d) `wtwap ≥ twap60(T)` — whole-window TWAP vs smoothed start.

**Gate criterion (fixed now):** each rule is scored as matches/total against ALL real
terminal-pricing labels available at gate time, on Kraken and on Coinbase separately. A rule
qualifies if it matches **≥90%** on the Kraken reconstruction and ≥90% on Coinbase where
computable. If several qualify, precedence (fixed by mechanical plausibility, not by score):
**(b), then (a), then (d), then (c)** — the resolution source is literally named a 60 s-TWAP
stream. If NO rule qualifies on Kraken: **STOP.** If a rule qualifies on Coinbase but not
Kraken, that is a resolution failure of the surface series: **STOP.** In either STOP case the
report says the counting would have been wrong and ends there.

Also reported: in-window inter-trade gap (median/p90) per venue, and Kraken-vs-Coinbase rule
outcome disagreement over the labeled span.

## Step 2 — state at decision time (matched to the gated rule; strictly causal)

Decision times per window: t = C − r for r ∈ H·{0.8, 0.6, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05}.
Every state component uses trades at or before t only. (Unit test: truncating the series at t
leaves the state bit-identical.)

Let ref = the gated rule's start reference (p(T) for (a)/(c); twap60(T) for (b)/(d)). In bps
of ref:

- **a1** = elapsed-window TWAP [T, t] vs ref.
- **a2** = p(t) vs ref.
- **gap** = a2 − a1 (the Ember mechanic: raw price vs what the average has already banked).
- **m** (determination margin, rule-mechanic): the bps by which p(t) exceeds the constant
  price that would leave the settlement exactly at a tie —
  (a)/(d): m = a2 + (e/r)·a1 with e = t − T;
  (b): for r ≥ 60, m = p(t) vs twap60(T) in bps (nothing of twap60(C) is locked yet);
  for r < 60, m = a2 − req, req from twap60(C) = ((60−r)·twap[C−60,t] + r·avg_rem)/60;
  (c): m = a2.
- **vol** = std of 5 s log-returns over [t−120, t], bps.
- **regime** (per window, at T): trailing-1h return of the same series — down < −50 bps,
  flat ∈ [−50, +50], up > +50 bps.

## Step 3 — the surface (counting, with the near-ties kept)

Windows: ALL consecutive grid windows of the Kraken span, both horizons (expected ≈2,880 5m
and ≈960 15m minus exclusions), labeled by the GATED rule's reconstruction. Real settlements
are never mixed into these counts; they are the validation set only.

- Headline: P(settle Up | m-bin, r) per horizon, with n and Wilson-95 per cell. m/a1/a2 bins
  (bps): (−∞,−30], (−30,−15], (−15,−8], (−8,−4], (−4,−1.5], (−1.5,0], (0,1.5], (1.5,4],
  (4,8], (8,15], (15,30], (30,∞).
- Conditioning stored in the result JSON: × regime (3) × vol half (split at the counting
  set's median, computed on set A only). Cells with n < 30 are flagged thin and never
  headlined.
- Near-boundary windows (|final reconstructed margin| < 2 bps — the venue-basis floor) are
  KEPT, counted, and flagged `ambiguousAtReferenceResolution`; their fraction is reported per
  horizon and per cell.
- The fee floor (~1.75 ¢ midpoint, 2–3.5 ¢ working, per the map) renders beside every
  apparent edge.

## Step 4 — falsifiability (calibration or it didn't happen)

- Temporal split by window start T: first 70% of the span = set A (counting), last 30% = set
  B (scoring). Today's real-labeled rounds fall in B by construction.
- Prediction for a B-window at each r: the A-surface cell P(up | m-bin, r); if that cell has
  n_A < 10, fall back to the A marginal P(up | r).
- Scores on B (per horizon, per r and pooled): **Brier**, a **10-bin reliability curve**
  (n, mean predicted, observed per bin), and the Brier of the constant-P baseline (set A's
  base rate) for skill.
- The same predictions scored against the REAL settlement labels (small n, stated beside).
- **License to continue (fixed now):** weighted mean |observed − predicted| (ECE) ≤ 0.10 on
  B AND Brier < baseline. Failing either = "we counted the wrong thing" — reported plainly,
  and the surface is not carried forward.

## Amendment v1.1 — the step-function refinement (registered 2026-08-27, BEFORE the fine
series was fetched and before any real-data computation; only synthetic unit tests had run)

Ember, verbatim: *"during the trend there is sometimes chop that gets quantized into a
victory."* The settlement is a step function: a tiny reversion that nicks the boundary pays
the same $1 as a huge move. Direction is not the edge; proximity-to-boundary times a likely
small move is. Three registered changes to what is HEADLINED (the gate, causality, split,
and license are unchanged):

1. **Primary axis = boundary distance d(t)**, the freeze-now settlement margin: the bps (vs
   the gated rule's start reference) by which the settlement value would clear the boundary
   if the price stayed at p(t) for the remainder — (a)/(d): d = (e·a1 + r·a2)/H;
   (b) r ≥ 60: d = a2, r < 60: d = bps(((60−r)·twap[C−60,t] + r·p(t))/60 vs ref);
   (c): d = a2. Sign of d = the side the settlement currently sits on (d = 0 → Up, per
   ties→Up). Signed-d bin edges (bps, fine near zero): ±1, ±2, ±4, ±8, ±15, ±30 (14 bins),
   crossed with the same remaining-fraction grid. The v1 m-margin remains a stored state
   variable, no longer the headline axis.
2. **P(cross) and the convex EV.** Per (|d| band, remaining) cell — |d| bands [0,1], (1,2],
   (2,4], (4,8], (8,15], (15,30], (30,∞) — report: n, the empirical cross rate P(final
   settlement opposite sign(d(t))) with Wilson-95, the side split, and the EV of buying the
   currently-losing side at registered hypothetical entries q ∈ {5¢, 15¢, 50¢, 85¢}:
   EV(q) = P(cross) − q − 0.070·q(1−q), with the breakeven cross rate q + 0.070·q(1−q)
   printed beside (5.33% / 15.89% / 51.75% / 85.89%). These entries are HYPOTHETICAL — no
   live contract prices are used; the table shows what cross rate each entry price would
   need, not a mispricing claim. Spread/overround riders per the map stated beside.
3. **The trend-day claim, measured directly.** On trend-regime windows (1h |return| > 50
   bps): cross rate for near-boundary (|d| ≤ 4 bps) vs far (|d| > 15) setups, late vs
   early, split by whether the current side AGREES with the trend direction. One
   observation per window per cell: the late state is the r-fraction 0.1 state, the early
   state is 0.4 (no pooling of correlated within-window states). The claim has legs iff
   near-boundary-late setups in trends still cross with a rate materially above the
   far-boundary rate and above the cheap-entry breakevens; either way the number is
   reported with its CI.

Calibration (step 4) now runs on the signed-d surface (P(up | d-bin, remaining), fallback
to the remaining-marginal below 10 A-samples, license unchanged) — cross predictions are a
deterministic transform of it, so the license covers the headline.

## Amendment v1.2 — NEXT-WAVE registered estimand: leg-in / min-combined-cost
(registered 2026-08-27, BEFORE sufficient contract-price data exists to test it — the
collector has been accruing both-sides price paths only since 13:48Z today)

Ember, verbatim: *"getting in on both legs of it sometimes helps hedge."* Owning both legs
pays $1 regardless of the TWAP, so it hedges iff the COMBINED cost is under $1. At any
single instant the two buy legs sum to ~$1.01 (the measured ~1% overround — a guaranteed
loss), so the hedge is a LEGGING move: each side accumulated cheap at a different moment,
blended book under a buck. Once combined < $1 the win is locked regardless of settlement —
the escape hatch on the near-boundary fade, converting a coinflip into a sure thing when
chop cooperates. Registered now, computed next wave, on `state/prediction/collect-*.jsonl`:

- **(a) min-combined-cost per round**: over the round's in-window both-sides price path
  (buyUp = the `-0` market's `buyYesPriceUsd`, buyDown = the `-1` market's, micro-USD
  VERBATIM — provider claims in provider units), the minimum over the window of (cheapest
  buyUp seen so far + cheapest buyDown seen so far). This equals min(buyUp) + min(buyDown)
  over the window and is an ORACLE-WINDOW bound on what legging could have achieved — a
  feasibility number, never a live-executable claim.
- **(b) lock rate**: the fraction of covered rounds where min-combined-cost, net of the
  explicit fee on both legs (0.070·q(1−q) each, round-up-to-cent rider stated), is < $1 —
  i.e. legging could have locked a guaranteed win.
- **(c) regime conditioning**: (a) and (b) bucketed by the v1.1 regime (trailing-1h
  reference return, ±50 bps bands). The registered thesis to confirm or refute: legging
  works in chop (both sides swing cheap at different moments) and FAILS in trend (one side
  never gives the entry, leaving a naked leg — which is a directional position, not a
  hedge, and must be reported as the failure mode, not netted away).

Coverage gates and honesty caveats, fixed now: a round counts only with >= 10 in-window
samples carrying both sides' pricing (fewer = insufficient-coverage, counted, never
imputed). The ~20 s sampling cadence MISSES cheap moments between samples, so the observed
min-combined-cost OVERSTATES the achievable cost — conservative in the right direction for
a feasibility claim, and stated beside it. Top-of-book buy prices ignore depth and the
5–250 USDC order band; no fill is assumed. The fee floor renders beside every number.
Author knowledge at registration: scattered single-instant pairs only (0.17/0.84 in the
map; 0.33/0.75 and 0.10/0.94 today) and the ~1% single-instant overround — no both-sides
path has been analyzed. Analysis runs when >= 100 covered rounds exist or after >= 7 days
of collection, whichever comes first, under this registration.

## Amendment v1.3 — the OPPORTUNITY CENSUS is the primary next-wave deliverable
(registered 2026-08-27, BEFORE the contract price paths ripen; no path has been analyzed)

Framing correction from Ember, registered before the data can tempt anyone: *"how often did
it actually settle each way" measures the COIN'S BEHAVIOR, not OPPORTUNITIES.* A strategy's
value is edge-per-opportunity × opportunities-per-unit-time × fillability — outcome base
rates touch only a sliver of the first term. The SOL-side studies (v1 base rates, this
study's conditional surface) are hereby the FOUNDATION — the fair-value/P(settle) inputs —
not the headline. The primary next-wave deliverable is ONE OPPORTUNITY CENSUS over the
collected contract price paths crossed with realized settlements (accruing since 13:48Z;
ripeness gate: >= 1 day of collection), absorbing the v1.2 leg-in estimand and the
mispricing comparison as members. Three registered strategy types:

1. **Near-boundary late fade** — the cheap side quoted late in-window while the
   freeze-now margin |d| is small: takeable when the quoted price implies P(cross) below
   the FOUNDATION surface's cross rate minus the fee.
2. **Stale buy-ahead of future rounds** — a not-yet-open round quoted at a price divergent
   from the foundation fair value (rounds are listed and quoted before their window; the
   openTime-is-listing-time finding).
3. **Leg-in under-$1** — per v1.2, unchanged mechanics, now census-framed.

Per strategy type, the census reports (all registered now):

- **RATE**: takeable setups per hour and per round, with the denominators printed (hours
  collected, rounds covered) — the "is this a business" number.
- **EDGE SIZE**: the DISTRIBUTION (quantiles, not just a mean) of divergence between the
  takeable price and the realized settlement value, net of the explicit fee
  0.070·q(1−q) per leg (round-up-to-cent rider stated).
- **REALIZED P&L**: what the mechanical rule taking EVERY flagged setup would have netted —
  losers and naked-leg fails included and itemized, never netted away — regime-split per
  the v1.1 buckets.
- **FILLABILITY**: the collected price is the provider's QUOTED price; available size is a
  separate question. Where the order-book ladder was captured, the size at the quoted
  level is reported as a bound; otherwise the setup is priced at top-of-book with the
  5–250 USDC band stated. Infinite fill is never assumed.

Causality: a setup is flagged from data available at flag time only — foundation values
enter as counting-set (A) surfaces, settlements never leak into the flag. The step-0 rule
gate still governs every settlement label; every number stays reference- and
price-approximate, fee floor beside it. Base rates are an INPUT to whether a setup is
real edge — not the product.

## Amendment v1.4 — the FLOW MODEL census (registered 2026-08-27, BEFORE any flow
feature, conditional rate, model fit, or Hawkes estimate was computed on real data)

Correction this amendment answers (Ember): the prior census's momentum signal was a
STRAWMAN — trailing-1h price DIRECTION — and its null says nothing about flow. The
microstructure literature's actual claim is that ORDER FLOW (signed volume, arrival
intensity, aggressor imbalance, trade-size structure, self-excitation) predicts short-
horizon moves. The Kraken tick tape (`state/prediction/fine/`, ~342k SOL/USD trades with
price, size, and taker side) is real flow data the strawman never touched. This amendment
registers the flow model, its features, its evaluation, and its census BEFORE fitting.

**Author knowledge at registration** (everything computed so far, nothing else):
coverage counts ONLY — Kraken tape span 1786978574–1787843067 (10.006 days, 342,189
trades); 3,357 labeled rounds, all `twap60` era; 2,955 joinable (window inside the tape
span with a 3,600 s feature lead margin): 1,999 5m + 956 15m over 238.9 h; median 156
contract fills per round. NO feature value, NO conditional rate, NO model number, NO
Hawkes estimate has been computed on real data. Unit tests run on synthetic data only.

**Population**: labeled backfill rounds (real settlement labels per BACKFILL.md
reliability order) with `windowStartUnix − 3600 ≥ tape start` and
`closeTimeUnix ≤ tape end`. Decision instants: the registered remaining-fraction grid
(REMAINING_FRACTIONS, step 2). The step-0 gate governs as always: the run executes only
under a PROCEED verdict and uses the gated rule for d(t).

**Causality contract**: every FLOW feature at instant t is a function of tape trades
with timestamp STRICTLY BEFORE t (unit-tested: truncating the tape at t, exclusive,
leaves the feature vector bit-identical). The reused state features (d, gap) keep the
v1 at-or-before-t semantics. Instants where a price-anchored feature is data-absent
(no trade within the 120 s staleness at an anchor) are EXCLUDED and counted, never
imputed. Pure count/volume features are total functions (no trades in window = 0 flow).

**Feature set, fixed now** (trailing windows W in seconds; tape = Kraken SOLUSD trades
with size s_i and taker side g_i ∈ {+1 buy, −1 sell}):

- PRICE/STATE set (the strawman's information, done properly — the ablation control):
  `rem_frac`, `rem_s`, `is_15m`; `d_bps` (freeze-now margin, gated rule); `gap_bps`
  (a2 − a1); trailing log-returns `ret_W` = 1e4·ln(p(t⁻)/p(t−W)) for W ∈ {60, 300,
  900, 3600}; realized vol `vol_fast` (5 s grid over 120 s) and `vol_slow` (30 s grid
  over 600 s), bps.
- FLOW set (the new information):
  - `ofi_W` = (Σ buy size − Σ sell size)/(Σ size) over (t−W, t), W ∈ {30, 60, 120,
    300, 900}; 0 when no trades (no flow), in [−1, 1].
  - `sv_60`, `sv_300` = asinh(Σ g_i·s_i) over the window (signed volume, SOL,
    tail-compressed).
  - `rate_W` = trade count/W for W ∈ {30, 60, 300} (arrival intensity); `accel` =
    ln((rate_30 + ε)/(rate_300 + ε)), ε = 1/300 (intensity acceleration).
  - `aci_60`, `aci_300` = (buys − sells)/count (aggressor count imbalance); 0 on empty.
  - `mo_frac_300` = fraction of trades flagged market-order (Kraken taker order type).
  - `big_ratio_300` = ln(1 + max size in (t−300, t) / median size over (t−3600, t));
    `big_count_300` = count of trades in (t−300, t) with size ≥ 5× that trailing
    median (large-trade markers; 0 when the trailing median is data-absent/zero).
  - `hx_10`, `hx_60` = Hawkes-style excitation S_β(t) = Σ_{t_i<t} e^{−β(t−t_i)} at
    FIXED timescales 1/β ∈ {10 s, 60 s} (split-independent by construction; the
    fitted-β estimate below is reported, not used as a feature).

**The Hawkes branching ratio** (the reflexivity gauge, superseding the v1 "out of
scope" note): exponential-kernel Hawkes λ(t) = μ + ηβ·Σ e^{−β(t−t_i)} fitted to the
TRAIN-span trade arrivals by EM (O(N) recursions), 2 starts (timescale inits 5 s,
60 s), best log-likelihood kept; η = branching ratio reported with its timescale and
log-likelihood vs the homogeneous-Poisson fit; per-UTC-day sub-span refits for
variability. η → 1 reads as critical/reflexive; η is a DESCRIPTIVE finding here.

**Models, fixed before fitting** (target: round settles Up, real label; one sample per
decision instant; sample weight 1/(instants in its round) so each round counts once):

- M0, model-free conditional rates: P(up | ofi_60 tercile × sign(d) × rem_frac), the
  tercile edges from TRAIN only, Wilson-95 per cell, thin cells (< 30) flagged.
- M1, logistic: L2 (λ = 1.0) on TRAIN-standardized features (clip ±8 sd), Newton/IRLS,
  ≤ 50 iterations.
- M2, gradient-boosted trees: 32-bin histograms (TRAIN quantile edges), depth 2,
  learning rate 0.1, ≤ 150 trees, min leaf weight 40, leaf L2 = 1.0, deterministic (no
  subsampling); tree count chosen by logloss on the last 15% of TRAIN (by time) —
  never on the holdout; the model kept is the one fitted on the first 85% of TRAIN.
- Ablations (the flow question itself): each of M1/M2 fitted on (P) price/state only,
  (F) flow only, (P+F) full. "Flow adds value" requires (P+F) to beat (P) on the
  holdout, not merely beat a constant.

**Split, fixed now**: temporal, by round `windowStartUnix`, over the joinable
population, both horizons pooled. Cut at the 70% quantile of round start times; rounds
straddling the cut are excluded from both sides. Primary = fit on TRAIN, evaluate once
on the 30% HOLDOUT. Secondary (stability, registered now): 3 walk-forward folds —
train on the first 40/60/80% of the span, test on the following 20% each. No random
splits anywhere. Nothing is refitted after seeing holdout numbers.

**Evaluation, fixed now** — the market is the benchmark to beat:

- Market implied probability at instant t: p_mkt = mean of the available members of
  {last Up fill ≤ 60 s old, 1 − last Down fill ≤ 60 s old} (contract fills at/before t,
  census staleness); instants with neither are market-absent (counted, excluded from
  the head-to-head).
- Head-to-head on IDENTICAL holdout instants where model and market both exist:
  Brier(model) vs Brier(p_mkt), pooled + per horizon + per remaining fraction;
  10-bin reliability + ECE for both; Brier vs the TRAIN base-rate constant as floor.
- **The yes/no bar, fixed now**: the flow claim stands iff, on the pooled holdout
  head-to-head, Brier(M2 on P+F) < Brier(p_mkt) AND ECE(M2 on P+F) ≤ 0.10 AND
  Brier(M2 on P+F) < Brier(M2 on P). Anything less is a REAL null (a genuine flow
  model failed to beat the market out-of-sample) and is reported plainly. State
  instants within a round are correlated; the pooled numbers say so and the
  per-fraction table is the decorrelated view.

**The census re-run, fixed now** (the same decision-time pipe, flow signal in the
socket): on HOLDOUT rounds only, at each decision instant, takeable price of a side =
its last fill ≤ 60 s old (v1.3 semantics); flag iff p_model(side) − q − 0.070·q(1−q)
> threshold; position rule = first flagged setup per round, 1 contract, scored by the
REAL label. Primary threshold 0 (the fee floor itself); thresholds ≥ 0.02 and ≥ 0.05
are registered sensitivity rows. Signal = M2 on P+F (M1 reported beside). Report:
setups/hour (holdout span hours printed), edge-net quantiles, realized P&L including
losers, win rate with Wilson-95, regime split (v1.1 buckets), no-quote and
feature-absent instants counted. TRAIN-round census numbers may render only as
`inSampleReference`, never as the result. All v1.3 honesty riders carry: fills are
realistic transacted prices never guaranteed size, the takeable price is a price
approximation, the Kraken reference is ~2 bp venue basis, fee floor beside every edge.

## Out of scope this pass

Contract-price mispricing/calibration vs the market (needs the collector's implied-price
history to accumulate; accruing since 2026-08-27 13:48Z). Hawkes/arrival criticality
(trade-arrival data now exists via these fetches but is out of this registration; next wave).
