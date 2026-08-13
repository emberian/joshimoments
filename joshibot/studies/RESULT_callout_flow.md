# Signal #3 — callout → flow latency

**Verdict: UNRESOLVABLE-AT-THIS-N.** Not a null. The instrument cannot see the outcome variable at
all, and no amount of estimator care changes that.

Run 2026-08-13 against a copy of `intelligence_state/intelligence.sqlite3` (3,306 observations).
Reproduce with:

```
cp intelligence_state/intelligence.sqlite3 /tmp/intel_copy.sqlite3   # the daemon holds a lock
uv run python -m studies.callout_flow --store /tmp/intel_copy.sqlite3 --seed 20260813 --replicates 200
```

Deterministic given the seed, no network, read-only. Estimator tests: `tests/test_callout_flow_study.py`.

---

## 1. The question

Given a social callout resolving to a specific mint at time `t0`, does that mint's **buy-arrival
intensity** and **new-wallet influx** over `[t0, t0+30min)` differ from an **hour-matched** baseline
for the same mint?

Pre-registered hypothesis family, declared before looking at any estimate:

| # | outcome | window |
|---|---|---|
| 1 | buy_arrivals | **30 min (primary)** |
| 2 | buy_arrivals | 10 min |
| 3 | buy_arrivals | 60 min |
| 4 | new_wallets | 30 min |
| 5 | new_wallets | 10 min |
| 6 | new_wallets | 60 min |

**Effective number of hypotheses = 6.** Corrected by Benjamini–Hochberg at `q = 0.10`. No other
window, outcome, subgroup, or responder definition was tried and discarded; the two arms below are
reported jointly and neither was selected on its result.

---

## 2. n at every stage

| stage | n |
|---|---|
| observations in store | 3,306 |
| rows of callout-bearing kinds (`x_mint_mention`, `claudekol_claim`) | 448 |
| … carrying a resolved `mint` | 316 |
| … **rejected by the tape contract** | **1** |
| … unique callout events after dedup on (mint, author, instant) | **164** (61 mints) |
| `wallet_transaction` rows | 1,508 |
| … carrying a block time | 1,337 (88.7%) |
| … fill legs after dedup on (signature, mint) | **1,209** — 1,076 buys / 133 sells |
| … distinct mints in those legs | 658 |
| … **distinct wallets in those legs** | **2** |
| eligible *exogenous* responder wallets (policy wallet excluded) | **1** |
| exogenous responder coverage | 2026-08-08 12:15:37Z → 2026-08-12 20:01:29Z (103.8 h) |
| callout span | 2026-08-12 19:41:07Z → 2026-08-13 07:34:02Z |
| **temporal overlap of the two** | **20.4 minutes** |
| **callouts analysable at pre=30 / post=30** | **0 of 164** |
| callout mints ever traded by the exogenous wallet, *at any lag* | **0 of 61** |

The 164 events dedup down from 316 rows because `claudekol_claim` emits several rows per action at
an identical instant; counting rows instead of events would have inflated every n on this page by
~1.9×.

---

## 3. Why it is unresolvable — three independent blockers

### 3.1 There is no mint-level arrival process in this store

`wallet_transaction` is **not a firehose**. It is `getTransactionsForAddress` run over a watchlist
of **two addresses**: `GV6UUm…` (Ansem's declared wallet, per the `kol_wallet_claim` row) and
`Sh1WNJ…` (the `helius.seed_wallets` entry in `intelligence.yaml` — our own).

"Buy-arrival intensity for a mint" is a property of *all* buyers. What is observable is whether one
of two specific wallets happened to buy. That is a 2-wallet panel, not an arrival process.

**"New-wallet influx" is not merely underpowered, it is undefined here.** Both wallets are known
ex ante and neither is ever new. The maximum value the outcome can take across the entire study is
1. The pipeline computes it, flags it (`"responder set has 1 wallet(s); 'new_wallets' cannot exceed
1 … structurally uninformative"`), and no inference is drawn from it.

### 3.2 The exogenous wallet and the callout stream barely coexist in time

Ansem's observable history ends **2026-08-12 20:01:29Z**; the first callout is **19:41:07Z**. The
two streams overlap for **20.4 minutes**. Since an analysable event needs its whole window inside
coverage, the maximum attainable n falls off a cliff:

| post window | 1 min | 5 min | 10 min | 15 min | **30 min** | 60 min |
|---|---|---|---|---|---|---|
| analysable callouts | 8 | 7 | 3 | 3 | **0** | 0 |

**The window the question asks about admits n = 0.** The best any window achieves is n = 8, at a
1-minute horizon that answers a different question.

### 3.3 The exogenous wallet never touched a called-out mint

Ansem traded 598 distinct mints in the window. Callouts covered 61 mints. **The intersection is
empty — 0, at any lag, not just inside the response window.** So the outcome variable is identically
zero on the exogenous arm regardless of window, matching, or pooling.

This one is decisive on its own. Blockers 3.1 and 3.2 could be fixed by collecting more; 3.3 says
that even with perfect timing alignment there is nothing to count.

---

## 4. The two arms, as run

### Arm A — exogenous (the study)

```
verdict  UNRESOLVABLE-AT-THIS-N
reason   only 0 of 164 callouts fall inside the responder coverage window
         [2026-08-08T12:15:37Z, 2026-08-12T20:01:29Z]; minimum for estimation is 10
```

No hypothesis was estimated, because estimating one would have meant reporting a number computed
from zero events. **p_floor is undefined here: with zero analysable events there is nothing to
match, so not one placebo replicate could be drawn** — the achievable resolution is not `1/(1+R)`
for any `R`, it is nothing at all.

*Robustness.* This is not an artefact of the 30-minute choice. Re-running with the most permissive
settings the pre-registration allows (`pre = 0`, family `{1, 30}` and `{1, 5, 30}` minutes) still
yields **n = 0 analysable**, because window eligibility is bounded by the longest window in the
family and the primary is fixed at 30 minutes by pre-registration. Dropping the primary to chase a
1-minute window is refused outright (`StudyError`: "a run without it is a different study and must
say so") — and would be pointless anyway, since blocker 3.3 makes the exogenous outcome zero at
*every* window.

### Arm B — endogenous (invalid; reported because it is the trap)

Including our own sentinel wallet, the pipeline's *uncorrected* reading is spectacular:

| outcome | window | treated arrivals | placebo arrivals | partial μ | rate ratio | p | p_floor | BH-FDR |
|---|---|---|---|---|---|---|---|---|
| buy_arrivals | 10 | 9 | 0 / 32,400 | +5.417 | ×225 | 0.00498 | 0.00498 | **reject** |
| buy_arrivals | **30** | 15 | 0 / 32,400 | **+5.479** | **×240** | 0.00498 | 0.00498 | **reject** |
| buy_arrivals | 60 | 21 | 0 / 32,400 | +5.525 | ×251 | 0.00498 | 0.00498 | **reject** |
| new_wallets | 10 | 3 | 0 / 32,400 | +5.341 | ×209 | 0.00498 | 0.00498 | **reject** |
| new_wallets | 30 | 9 | 0 / 32,400 | +5.403 | ×222 | 0.00498 | 0.00498 | **reject** |
| new_wallets | 60 | 10 | 0 / 32,400 | +5.408 | ×223 | 0.00498 | 0.00498 | **reject** |

Six for six, at p = 0.005, a 240× lift. **All of it is worthless**, for two reasons that are worth
separating:

1. **It is a closed loop.** The sentinel subscribes to the callout stream. Its buys after a callout
   are its own reaction function, not market propagation. Measuring a policy against its own trigger
   returns the policy. All 15 responses came from this wallet; the exogenous wallet contributed 0.
2. **It is not even an estimate.** `n_placebo_arrivals = 0` across **32,400** placebo windows. With
   a structural-zero baseline the log rate ratio is fixed by the ½ continuity correction rather than
   by data, and every placebo draw collapses to the same value — `null_spread = 0.0` — so p reaches
   its floor *mechanically*, not because anything in the null was beaten. Only a one-sided bound
   exists here; a point estimate does not.

The pipeline refuses this arm on both counts (`verdict: UNRESOLVABLE-AT-THIS-N`, reason "baseline is
a structural zero … the placebo null is degenerate"). `test_structural_zero_guard_has_teeth` pins
the fact that **without that guard the study would have reported SUGGESTIVE on all six**.

This is the headline risk for whoever runs this next: the naive version of this study produces a
publishable-looking result, and the result is our own bot.

---

## 5. Method — every choice and why

**Chain time is the origin.** For `wallet_transaction` the chain clock is **`emitted_at`**, not
`observed_at`. This store *inverts the convention between kinds*: for social rows `observed_at` is
the post time and `emitted_at` is our ingest stamp; for chain rows it is the reverse. Verified by
regressing `slot` on `emitted_at` across the 1,337 stamped rows → **0.4213 s/slot**, Solana's slot
time. Against `observed_at` the relation is *inverted*, because the backfiller walks history in
reverse: its newest fetch (16:05Z) carries the *oldest* slot (437,991,053). Using `observed_at` as
trade time would have reversed the arrow of causation on every event. The 171 rows with no block
time are dropped, never back-filled from the fetch clock.

**Observer lag is delayed entry, and it bounds tradeability.** Callout ingest lag: median **368 s
(6.1 min)**, p75 572 s, p95 **7,371 s (2.0 h)**, max 8.7 h. **6.7% of callouts reach us more than 30
minutes after they were posted** — the entire response window is over before we know. Even a real
effect of the size anyone hopes for would be ~20% consumed by ingest latency at the median.

**Hour-matched placebos.** Diurnal amplitude here is 3.6×–5.4×, and the callouts are themselves
strongly diurnal (147 of 316 raw rows land in a single UTC hour). A placebo must fall in the same
UTC hour-of-day band as the callout it matches. §7 shows this is load-bearing, not decorative:
defeating it manufactures a significant effect from true zero.

**Non-overlap uses `max(pre, post)`, never `post` alone.** Separation is enforced against every real
callout on the mint *and* every placebo already accepted in the same replicate. The prior study that
separated on the post window alone accepted placebos 1 h apart while each consumed a 24 h pre-window
— ~96% overlap, advertised as independent. `test_placebo_separation_uses_max_of_pre_and_post_not_post_alone`
runs `pre = 6 h`, `post = 30 min` and asserts the accepted set respects 6 h.

**Coverage-bounded eligibility.** An event is analysable only if its whole `[t−pre, t+post]` window
lies inside the responder's observable span. Outside it a zero is *unobserved*, not "no response" —
the displacement-censoring error that turned a published 24 h graduation rate into a 6-minute one.
This is precisely what reduces Arm A to n = 0 rather than to 164 spurious zeros.

**Partial pooling, never fully pooled and never per-token.** Per mint,
`θ_m = log(rate_treated / rate_placebo)` with a ½ continuity correction and delta-method variance
`v_m = 1/(y₁+½) + 1/(y₀+½)`. `θ_m ~ N(μ, τ²)`, fitted by empirical-Bayes EM (EM rather than
DerSimonian–Laird because EM cannot return a negative variance component and is monotone, so the
answer does not depend on where iteration stops). All three regimes are reported side by side.
`test_fully_pooled_is_dominated_by_the_largest_mint` constructs the failure directly: one
high-volume mint flips `fully_pooled` positive while partial and unpooled both stay negative.

**Inference by leave-one-out placebo replicates.** Observed = real vs all R placebo replicates; null
draw r = replicate r vs the other R−1. `p = (1 + #{|null| ≥ |observed|}) / (1 + R)`,
`p_floor = 1/(1+R)`, always reported. The null's baseline uses R−1 replicates against the observed
statistic's R, which makes null draws slightly *more* variable and the test therefore conservative.

**Raw amounts stay integral.** `token_delta_raw` is read as `int` and only its sign is used. Output
is JSONL, never CSV.

**Degeneracy guards.** Two verdict overrides that fire before any effect can be claimed: zero
placebo arrivals (baseline unidentified) and zero null spread (p is mechanical). Both are tested,
and both are shown to change the verdict.

**Primary-shopping is refused structurally.** The primary hypothesis is pre-registered as
`buy_arrivals @ 30 min`. A run whose family omits it raises `StudyError` rather than promoting
whichever hypothesis happens to be present — the failure mode where a study quietly becomes about a
different window once the registered one disappoints.

---

## 6. Data-quality findings, incidental but real

**One callout mint is corrupt beyond repair.** `x_mint_mention` at 2026-08-13T01:22:09Z carries
`mint = "9khl8p4vemn85hkjqqfkk8wmdgfy5dwu9ksqpgysdppl"` — 44 characters, **entirely lowercase**.
Base58 is case-sensitive, so the original address is not recoverable; the resolver almost certainly
lowercased a URL path. The tape contract caught it; the intelligence store accepted it. That is 1 of
28 `x_mint_mention` rows — **3.6%** — and the collector has no validation at write time. The study
drops it and counts it rather than aborting or repairing.

**Mint resolution is almost entirely adapter-side.** Only **3 of 164** callout events have the mint
literally present in the stored summary text (`resolved_from = mint_in_text`); 161 are
`adapter_resolved`. The schema keeps `resolved_from` because "a cashtag is a claim while a
pump/dexscreener URL is an identifier". With 98% of events on the claim side, resolution accuracy is
currently an *untested assumption* of any callout study — and there is no held-out check for it.

**11.3% of chain rows have no block time** (171 of 1,508) and are unusable for any timed study.

---

## 7. Falsification of the estimator

The finding is a non-finding, so the instrument had to be shown to work. 29 tests, and every
substantive one was re-run against a deliberately broken estimator to confirm it goes red.

### 7.1 Known-zero recovery

Synthetic world: inhomogeneous Poisson arrivals with a 4× diurnal profile; callouts drawn with
propensity `∝ diurnal³` so they cluster in busy hours exactly as the real ones do; **no dependence
of arrivals on callouts whatsoever**.

- Hour-matched pipeline: **μ = −0.008, p = 0.90, verdict NULL.** Correct.
- Across **8 independent null worlds** at q = 0.10: **0/8 false rejections**, mean μ = −0.017. The
  test asserts ≤ 1 and |mean μ| < 0.10.

### 7.2 Known-effect recovery

Same world with an injected 3× post-callout bump, `log 3 = 1.0986`:

- Recovered **μ = +1.032** (test tolerance ±0.35), p = 0.016, verdict **SUGGESTIVE**, BH-FDR
  rejected. Stable across seeds 1–3.

### 7.3 Mutation results — do the tests have teeth?

Each mutation was applied to `studies/callout_flow.py`, the guarding test run, and the file
restored. **All eight killed their test; none was vacuous.**

| # | mutation | guarding test | outcome |
|---|---|---|---|
| 1 | hour matching removed from the production sampler | `known_zero_effect_is_not_detected` | **RED** |
| 2 | separation uses `post` only (the prior study's bug) | `placebo_separation_uses_max_of_pre_and_post…` | **RED** |
| 3 | window counts the pre-window instead of the post | `known_injected_effect_is_recovered` | **RED** |
| 4 | `partial_pool` returns constant zero | `known_injected_effect_is_recovered` | **RED** |
| 5 | trade clock read from `observed_at` | `trade_chain_time_is_emitted_at_not_observed_at` | **RED** |
| 6 | structural-zero guard removed | `structural_zero_baseline_is_unresolvable…` | **RED** |
| 7 | `p_floor` understated 10× | `p_floor_is_the_resolution…` | **RED** |
| 8 | BH-FDR replaced by uncorrected α | `bh_fdr_matches_hand_computation` | **RED** |

Reproduce: `bash studies/falsify.sh` (the harness backs the file up, mutates, runs one test, restores).

**One asymmetry is worth stating, because it is why both headline tests are required.** Mutation 4 —
an estimator that always returns zero — **passes the known-zero test** and fails only the recovery
test. A null-recovery test alone is satisfied by an instrument that cannot detect anything. This is
the shape of the vacuous green check this repo has already shipped once.

Quantified teeth on the most important control: with hour matching defeated, the pipeline reports
**μ = +0.364, p = 0.016, BH-FDR rejected on data whose true effect is exactly zero**, against the
honest pipeline's μ = −0.008, p = 0.90 on the same data. Hour matching is the difference between a
correct null and a false discovery.

---

## 8. Verdict, and what would change it

**UNRESOLVABLE-AT-THIS-N.**

Explicitly *not* NULL: a null would assert the effect is absent or small. Nothing here licenses
that. The exogenous outcome variable was never observed — 0 analysable events, 0 callout mints ever
touched, 0 placebo replicates drawable — so the study has no power at any effect size. Reporting a
null would be a stronger claim than the data supports, in the same way the endogenous arm's ×240
would be.

Explicitly *not* SUGGESTIVE: the only arm producing an effect is a closed loop over our own policy
with an unidentified baseline.

**p_floor.** In the exogenous arm no placebo replicate could be drawn, so there is no `1/(1+R)` to
quote — the resolution is undefined, which is strictly worse than coarse. In the endogenous arm
R = 200 gives `p_floor = 0.00498`, and every hypothesis sat *exactly* on it with `null_spread = 0` —
p attained its floor mechanically, which is a diagnostic of degeneracy, not evidence.

**FDR outcome.** Arm A: no hypothesis estimated, so BH-FDR had nothing to correct. Arm B: 6/6
rejected at q = 0.10 and all 6 discarded by the degeneracy guard upstream of the correction.

### What has to be true before this question can be asked again

1. **A mint-level trade tape.** Not per-wallet histories — every fill on the called-out mint. Signal
   #3 is gated on the §6 build-order item 1 tape recorder, not on more social collection. This is
   the binding constraint and nothing else matters until it is fixed.
2. **≥ 30 analysable callouts** with the full `[t−30, t+30]` window inside coverage, spread over
   ≥ 5 distinct days so hour-matched placebos exist. At 28 mint-resolved callouts/day this is ~2
   days of collection *once the flow side exists*.
3. **Callout-mint coverage.** The trade tape must cover the mints that get called out. Currently the
   overlap with the exogenous wallet is zero.

---

## 9. What the next experiment should be

**Do not re-run this study.** It is correct and it is starved. Ranked by what unblocks the most:

1. **Subscribe the tape recorder to called-out mints (highest value, cheapest).** When a callout
   resolves to a mint, open a `WatchWindow` on that mint and pull *its* trades, not a watchlisted
   wallet's. 61 mints over the observed period at `getTransactionsForAddress`-equivalent cost is
   ~1–2% of the monthly credit budget. This converts a 2-wallet panel into an actual arrival
   process and makes both outcomes well defined. **Nothing else in signal #3 is worth doing first.**
   Note the censoring requirement: close on the clock or a terminal outcome, never because attention
   moved on.

2. **Validate mint resolution before trusting any callout study.** 161 of 164 events are
   adapter-resolved with no held-out check, and one row in 28 is already corrupt. Hand-label ~50
   `x_mint_mention` rows against the linked post and measure resolution precision. If precision is
   0.8, a 30-minute effect is attenuated ~20% toward zero before any estimator runs — and no one
   currently knows the number. Add a base58 validator at collector write time; a lowercased address
   is 100% detectable and 0% recoverable.

3. **Fix the ingest-lag ceiling, or stop calling this a live signal.** Median 6.1 min and p95 2.0 h.
   Whatever the effect turns out to be, a signal we learn about 6 minutes late in a market whose
   median time-to-graduation is 4.4 minutes is a *post-hoc measurement*, not a trade trigger. Decide
   which one it is before building on it.

4. **Then run the pre-registered study as written**, unchanged, on the real tape. The pipeline,
   guards and tests are ready; only the data is missing. Re-registering the same 6 hypotheses keeps
   the trials count honest.

5. **The endogenous arm is a real experiment already, if propensity-logged.** Our sentinel *does*
   buy after callouts. That is worthless as a propagation measurement but is exactly the
   randomized-experiment substrate §5 describes — with propensity logging at decision time it
   becomes off-policy-evaluable. Not signal #3; a different and cheaper study on data we already
   generate.

**Falsification condition for the eventual finding.** If a future run reports SUGGESTIVE, it is
falsified by any one of: (a) the effect not surviving exclusion of every wallet that consumes the
callout stream; (b) the effect appearing at equal magnitude in hour-matched placebo windows on the
*same* mints; (c) the effect vanishing when callout resolution is restricted to `mint_in_text`
identifiers; (d) `p` sitting at `p_floor` with `null_spread ≈ 0`; (e) the sign flipping under
partial pooling relative to fully pooled, which indicates one mint is carrying the result.
