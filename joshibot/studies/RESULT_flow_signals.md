# Will it dump, and IN WHAT MANNER — a competing-risks treatment

`studies/flow_signals.py` · run `uv run python studies/flow_signals.py` · results land in
`studies/data/flow_signals_results.json` · pure stdlib, deterministic given `--seed`, opens no socket.

---

## 0. The one-paragraph answer

**The competing-risks framing is right, it is unoccupied ground in the literature, and it is
the part of this study that survives.** Built it: a landmark Aalen–Johansen model over 3,241
risk intervals from 124 tokens, four mutually exclusive exit modes, exact identity check. It
delivers the "and how": the conditional mode mix swings from **89% SILENCE / 0% CLIFF** in one
stratum to **68% DOUBLE / 23% BLEED / 5% SILENCE** in another, which is information a binary
"will it dump" label cannot carry at all.

**The second prototype — a calibrated sequential changepoint detector on the live tape — is a
NULL, and the null is the finding.** The detector is sound (validated against planted shifts,
where it beats CUSUM by ~2× in detection delay). But on 27 hours of real flow across the
operator's four pools, once you compare against an autocorrelation-preserving null rather than
an i.i.d. one, **the entire apparent signal disappears**: excess alarm rate over the block null
is −0.59 to +0.27 per 1000 swaps against a 2.0 baseline, i.e. zero or negative. What looked like
regime change is metaorder splitting. A single i.i.d. null would have shipped a bogus alarm.

And one covariate finding was killed by its own falsification test — see §5. That is the most
useful paragraph in this document.

---

## 1. The four coins, located

All four have **already crossed** a −70% drawdown from their observed peak. That is not the
interesting part. **How** they crossed is:

| coin | bars | max DD from observed peak | worst single hour | manner | left-truncated? |
|---|---:|---:|---:|---|---|
| weave | 211 | −92.9% | **−78.3%** | CLIFF-shaped | no |
| nosis | 119 | −89.9% | **−64.0%** | CLIFF-shaped | no |
| SOLVE | 553 | −79.4% | −37.4% | step | no |
| DREGG | 999 | −79.0% | **−17.6%** | **BLEED-shaped** | **yes (1000-bar API cap)** |

DREGG reached −79% **without ever losing more than 17.6% in a single hour.** weave reached
−92.9% with a single hour of −78.3%. Those are two completely different objects that a binary
"down 80%" label calls the same thing, and they imply opposite actions: a cliff is unexitable
(you are filled after it), a bleed is exitable at leisure for weeks. This is the whole argument
for the framing, visible in four rows.

DREGG's −79.0% is a **lower bound** — it sits exactly on the 1000-bar API cap, so its true peak
predates our window. 77 of 145 cohort tokens share that defect; it is handled as left truncation
(see §3) rather than ignored.

### 1.1 The decision readout — what distribution each coin currently faces

Current state at each coin's latest landmark, against the cohort's tercile cuts
(`rv24` cuts at 0.00727 / 0.01643; `gapfrac` cuts at 0.0 / 0.0):

| coin | `rv24` (24h realised vol) | tercile | `gapfrac` | drawdown at landmark |
|---|---:|---|---:|---:|
| DREGG | 0.0302 | **T3** | 0.000 | −0.707 |
| SOLVE | 0.0288 | **T3** | 0.333 (T3) | −0.486 |
| weave | 0.0926 | **T3** | 0.000 | −0.717 |
| nosis | 0.1439 | **T3** (no landmark yet — only 119 bars) | 0.000 | — |

**All four are in the top volatility tercile**, and not marginally: nosis sits ~9× above the T3
cut, weave ~6×. So the distribution they face over the next 168 hours is the T3 row:

| stratum | P(any event @168h) | CIF CLIFF | CIF BLEED | CIF SILENCE | CIF DOUBLE |
|---|---:|---:|---:|---:|---:|
| rv24 T1 | 0.036 | 0.0000 | 0.0000 | 0.0321 | 0.0040 |
| rv24 T2 | 0.032 | 0.0000 | 0.0000 | 0.0256 | 0.0061 |
| **rv24 T3 (all four coins)** | **0.292** | **0.0099** | **0.0669** | 0.0159 | **0.1988** |

Read plainly: for a coin in this state, over a week — **~1% chance of a cliff, ~7% chance of a
bleed to −60%, ~1.6% chance of going silent, ~20% chance of doubling**, and ~71% chance nothing
decisive happens. The dominant single outcome is *up*, and the bad mass is concentrated in BLEED
(exitable) rather than CLIFF (not exitable). That is the actionable shape.

**Three caveats that bind this table**, and they are not decoration:
1. `rv24` is a **scaling identity, not a prediction** (§5). This table tells you the *size of the
   distribution you are standing in*; it does not say the model foresaw anything.
2. The cohort is **survivor-selected** (§3), so all four bad-mode numbers are biased **low**.
3. All four coins sit **far beyond** the T3 cut, so this is extrapolation from a stratum whose
   members are much calmer than they are. The honest use is ordinal — "the bad mass is BLEED,
   not CLIFF" — not the decimal places.

---

## 2. Verdict on the framing, and what the literature actually does

**Endorsed.** A token leaves through one of several mutually exclusive doors, and which door it
takes *is* the decision-relevant content. The right objects are a cause-specific hazard per mode
and a cumulative incidence function (CIF) per mode.

**The corpus does not do this.** Grepping all 99 papers in `~/paperbin/joshibot` for
`competing risk`, `cumulative incidence`, `Fine-Gray`, `subdistribution`, `cause-specific`,
`Aalen`, `accelerated failure time`, `discrete-time hazard` returns **zero hits**. Exactly one
paper does survival analysis of any kind.

### arXiv 2607.02823 — the one survival paper, and its instrument is broken

`pumpfun-graduation-regime-windows-censored-2607.02823` — Kaplan–Meier + L2-penalised Cox
(concordance 0.858, `lifelines 0.30.3`), N = 832,941 mints, **1,651 graduations**, 831,290
TIMEOUTs. Cox HRs: `has_telegram` 5.402 [4.733, 6.166], log(1+mcap) 4.506 [4.293, 4.729],
`has_twitter` 1.305 [1.192, 1.428].

- **Not competing risks.** Two states, GRADUATED vs TIMEOUT, and TIMEOUT is treated as
  *censoring* rather than as a competing event. With all censoring at exactly 24h and all
  failures before 6 min, its KM estimator is arithmetically the pooled binomial proportion —
  the paper concedes the asymptote "coincides with the pooled graduation rate of 0.198% to
  within the displayed precision." The survival machinery adds nothing over a 2×2 table.
- **Displacement-censored, exactly as PROGRAM.md §3.8 predicts.** Median time-to-graduation 1.0
  min, **maximum 5.0 min** (5.98 on the chain-time basis) inside a nominal **1,440-minute**
  window. Marino & Lillo measure a median of **4.4 min from creation** on a distribution with
  "a pronounced heavy tail … a minority of tokens requires tens of minutes to migrate." So this
  observer recorded **zero** graduations past a point beyond which roughly half of Marino's
  occur. PROGRAM.md §3.8 says: verify you reproduce Marino's 4.4-min median *with a tail*; if
  your max is ~5 minutes your instrument is truncated. This is that failure, in print.
- Corroborated three ways: every order statistic across 1,651 events lands on an integer
  (minute-quantised times ⇒ ~5 distinct failure times in the whole KM); the authors admit a
  four-day window where "launch-detection callbacks appear to have been wired before the
  graduation-detection callbacks", converting graduations into censoring events by a wiring
  defect; and the mcap bin at exactly 30.00 SOL holds **1 graduation in 91,247 mints** against
  ~77 expected at the neighbouring rate — a Poisson tail event of order 1e-30.
- The same author's companion paper (`2607.02795`) **abandoned** its Cox model six weeks later:
  "coverage is too thin to support a Cox-PH estimate."

Its headline claim is a 3.18× decline in graduation rate attributed to a compositional shift. A
detection horizon that dies at ~6 minutes produces a deficit of that order *mechanically*, and
the paper never tests the artifact hypothesis against its own.

### The only other relevant material

`solana-rugpull-hype-to-collapse` Table IV is the corpus's only per-exit-mode *time*
distribution (Rug Pull median lifespan 0.0246 d; Freeze Authority Abuse 0.483 d; Liquidity
Manipulation 0.0385 d; Pump-and-Dump 0.0221 d) — but as raw quantiles, with no censoring model
and no competing-risks structure. `memecoin-viral-to-void` is the only paper that *names* the
sharp-vs-slow distinction ("hard pull" vs "soft pull") and never operationalises it; **its
labels are also partly randomly fabricated by its own admission** ("If none of these sources
provide explicit labeling information, positive samples are randomly generated at a rate of
15%"), then SMOTE-oversampled — do not use its numbers for anything.

---

## 3. What was built

**Estimand.** Not first-passage-from-birth. That construction was built first and **discarded on
measurement**: 46 of 145 cohort tokens cross −70% from their running peak, but the median return
*after* the crossing is **+41.2%**, the p75 is **9.70×** and the p90 is **42.89×**. The
operator's own coins make the point unarguable:

| coin | crossed −70% at bar | post-crossing max | post-crossing end |
|---|---:|---:|---:|
| weave | **3** of 211 | **58.37×** | 20.35× |
| nosis | **7** of 119 | **41.27×** | 8.91× |
| SOLVE | 35 of 553 | 4.11× | 2.10× |
| DREGG | 622 of 999 | 1.52× | 0.86× |

weave "died" three hours into its observed life and then traded up 58×. That event is the
post-launch shakeout, not deterioration; an estimator built on it measures launch mechanics and
calls it death. (DREGG is the one that crossed *late*, at bar 622 — consistent with its
BLEED-shaped path in §1.)

So the clock starts where the operator stands — **at a landmark**, holding a coin, asking what
the next week looks like. At each landmark (every 24h of observed life, requiring 168h of prior
history) we follow forward 168h and record the **first** of four mutually exclusive absorbing
events:

| mode | definition (report the threshold with every number — PROGRAM.md §3.7) |
|---|---|
| SILENCE | ≥12 consecutive hours with no bar. GeckoTerminal omits zero-trade bars, so the gap *is* the observation. |
| CLIFF | one bar with close-to-close return ≤ **−50%** |
| BLEED | cumulative return from landmark ≤ **−60%**, no prior CLIFF |
| DOUBLE | cumulative return from landmark ≥ **+100%** — the competing *good* event |
| censored | none of the above by min(168h, end of data) |

"Sharp dump with recovery" is deliberately **not** a fifth mode: a transient that recovers has
not absorbed the token, so it must stay in the risk set rather than exit it. "Graduation/
migration" is unobservable here by construction — the cohort is discovered from a top-volume
snapshot of already-migrated pools, so migration is a selection criterion, not an event.

**Estimator.** Aalen–Johansen, non-parametric:
`CIF_k(t) = Σ_{t_i≤t} S(t_{i-1}) · d_ki/n_i`, with `S` the all-cause Kaplan–Meier. The identity
`Σ_k CIF_k + S = 1` is asserted at runtime and returns **1.000000000000** exactly.

Cox and Fine–Gray were **demoted on event counts** — with 10 CLIFF events overall and 0–6 in a
split half, a subdistribution hazard ratio has a CI spanning an order of magnitude. Non-parametric
first is not modesty; it is the only thing the counts support (PROGRAM.md §1.5).

CIs are by **entity-level bootstrap** (resample *tokens*, carry all their landmarks) because
stride-24h landmarks inside a 168h horizon overlap heavily and a landmark-level bootstrap would
treat one token's week as seven independent weeks (PROGRAM.md §3.2).

**The selection that binds every number below.** The cohort is GeckoTerminal's
`h24_volume_usd_desc` ranking, so every token in it survived to the snapshot *with high volume*.
Every rate below is conditional on membership in a top-volume snapshot on 2026-08-13/14 — "among
tokens that had a big day, this is what happens next" — and is biased **down** as an
unconditional death rate. It cannot be repaired from this cache. It is, however, close to the
population the operator actually holds: coins that still trade.

---

## 4. Base rates (fixed thresholds, horizon 168h)

145 tokens with ≥72 hourly bars, **77 sitting on the 1000-bar API cap** (left-truncated);
**3,241 landmarks from 124 tokens**; 2,906 censored.

| mode | events | CIF @24h | CIF @72h | **CIF @168h** | entity-bootstrap 95% CI @168h |
|---|---:|---:|---:|---:|---|
| CLIFF | 10 | 0.0016 | 0.0029 | **0.0032** | [0.0003, 0.0080] |
| BLEED | 59 | 0.0013 | 0.0066 | **0.0211** | [0.0106, 0.0340] |
| SILENCE | 70 | 0.0010 | 0.0096 | **0.0247** | [0.0072, 0.0423] |
| DOUBLE | 196 | 0.0145 | 0.0383 | **0.0671** | [0.0439, 0.0949] |
| *all-cause survival* | — | 0.9817 | 0.9426 | **0.8840** | — |

So for a median cohort token at a random hour: **~5% chance of a bad exit within a week, ~7%
chance of doubling, ~88% chance nothing decisive happens.** The bad-exit mass is dominated by
BLEED and SILENCE, not CLIFF — the cliff is rare (0.32%) once a token is established.

**The naive 1−KM estimator (treating competing events as censoring) overstates every cause**, as
theory requires: BLEED +6.71%, SILENCE +5.79%, CLIFF +2.08%, DOUBLE +1.95%. Honest note: at
these low event rates that bias is *small*. The argument for competing risks here is **not** the
1−KM bias — it is the mode mix in §5, which a binary label cannot represent at all.

### The mode mix — this is the "AND HOW"

Conditional on *something* happening within 168h, which door does it take? (in-sample, terciles)

| stratum | n | P(any event) | CLIFF | BLEED | SILENCE | DOUBLE |
|---|---:|---:|---:|---:|---:|---:|
| `rv24` T1 (quietest third) | 1081 | 0.036 | 0% | 0% | **89%** | 11% |
| `rv24` T3 (most volatile third) | 1080 | 0.292 | 3% | 23% | 5% | **68%** |
| `gapfrac` T3 (thinnest third) | 674 | 0.184 | 7% | 6% | **48%** | 39% |

A quiet, gappy token dies of **irrelevance**. A volatile token either **doubles or bleeds** and
essentially never goes silent. Same cohort, same horizon, opposite failure modes. A binary "will
it dump" classifier must average these, and the average describes neither.

---

## 5. THE FALSIFICATION — and the covariate finding it killed

The obvious objection to §4: **all four thresholds are fixed in return space**, so a
high-volatility token crosses *any* fixed threshold more often. Is `rv24` predicting the mode
mix, or is it just measuring scale?

The test: re-run everything with thresholds in the token's **own** robust-volatility units —
Marino & Lillo's Shewhart rule, `σ_MAD = MAD/0.67449`, CLIFF at `−4σ_MAD`, cumulative bands at
`±3σ_MAD·√h`. Runnable: `--vol-normalised`.

**`rv24`'s effect vanishes completely.**

| thresholds | `rv24` T1 mode mix | `rv24` T3 mode mix | median permutation p (20 partitions) | partitions with p<0.05 |
|---|---|---|---:|---:|
| fixed return | 89% SILENCE, 0% CLIFF, 0% BLEED | 68% DOUBLE, 23% BLEED, 5% SILENCE | **0.005** | **64.7%** |
| vol-normalised | 70% CLIFF, 19% DOUBLE, 5% SILENCE | 65% CLIFF, 26% DOUBLE, 1% SILENCE | **0.483** | **0.0%** |

Under vol-normalisation *no* covariate separates the mode mix in a single one of 20 partitions:
`dd` p=0.326 (15% of partitions), `gapfrac` p=0.401 (0%), `rv24` p=0.483 (0%), `dvol24` p=0.512
(0%).

**So `rv24` is a scaling identity, not a discovery.** "Volatile things cross fixed thresholds
more often" is true, mechanically guaranteed, and carries no surprise. It remains genuinely
useful for *sizing the distribution you face* — if you want P(−60% in 7 days) in real P&L terms,
fixed thresholds are the decision-relevant ones and `rv24` legitimately conditions that
probability. It must simply never be called a predictive edge. That distinction is the finding.

**Bonus result: Marino's k=4 σ_MAD dump detector does not port to hourly post-graduation
series.** Under vol-normalised thresholds it fires CLIFF on **1,260 of 3,226 landmarks (39%)**
within 7 days. Hourly memecoin log-returns are heavy-tailed enough that MAD badly understates
the tail, so a −4σ_MAD rule has essentially no specificity here. It was designed for
bonding-curve tick data and should stay there.

---

## 6. The strict gate

Token-disjoint **and** temporal: train tokens before the median landmark hour, **disjoint** test
tokens after. Statistic = total-variation distance between the top and bottom tercile's
conditional mode mix. Null = permute the covariate across whole tokens (preserving each token's
internal structure), recompute.

Critically, this is repeated over **20 independent token partitions**, because one partition is
not a test at this scale — during development a single partition moved `dd` from p=0.55 to
p=0.07 on nothing but a reseed.

Fixed thresholds, 20 partitions, 200 permutation draws each, ~827 test landmarks per partition:

| covariate | sep_out median | sep_out IQR | permutation p median | p IQR | **partitions with p<0.05** |
|---|---:|---|---:|---|---:|
| `rv24` (realised vol) | **0.783** | [0.409, 0.971] | **0.005** | [0.005, 0.139] | **64.7%** |
| `gapfrac` (thinness) | 0.382 | [0.252, 0.435] | 0.129 | [0.045, 0.320] | 30.0% |
| `dd` (drawdown state) | 0.371 | [0.298, 0.475] | 0.291 | [0.124, 0.522] | 10.0% |
| `dvol24` (volume trend) | 0.090 | [0.058, 0.117] | 0.682 | [0.498, 0.851] | 0.0% |

Only `rv24` clears consistently — and it still **fails in roughly a third of partitions**, which
is the correct amount of humility for 10–70 events split four ways. `gapfrac` is the
near-tautological one (a token trading thinly now is likely to stop trading; this is the
EdgeBank/memorisation baseline, not a discovery) and it does not survive. `dd` and `dvol24` are
flat nulls.

And per §5, `rv24`'s survival here is **not** evidence of predictive content: it is a scaling
identity that evaporates the moment the thresholds are put in the token's own volatility units.

The permutation null's median separation is large (~0.24–0.38) — with 10–70 events split four
ways, a raw mode-mix distance of 0.35 is *nothing*. This is exactly why PROGRAM.md §3.10 demands
a null: the unnulled numbers look impressive and are noise.

---

## 7. Changepoint detection — detector validated, live result NULL

### 7.1 The detector (and why this one)

**Shiryaev–Roberts e-detector.** Each restart point `j` carries a betting martingale against the
null sell-rate `p0`, mixed over the alternative with a uniform Beta(1,1) prior:

```
E_j(t) = [B(1+s, 1+f) / B(1,1)] / [p0^s · (1-p0)^f]     R_t = Σ_j E_j(t)     stop at R_t ≥ A
```

`ARL₀ ≥ A` by Ville's inequality plus optional stopping — **anytime-valid**, no multiple-testing
correction for continuous monitoring, and the threshold *is* the ARL₀. **No tuned knob**, which
is the entire reason to prefer it. Restart pruning caps memory by dropping the smallest terms,
which can only *lower* `R_t` and therefore only delay stopping: the false-alarm guarantee
survives pruning by construction.

The corpus contains **zero** e-values, conformal prediction, anytime-valid testing, CUSUM
detectors, or changepoint methods of any kind. Its entire online-detection apparatus is Marino's
single 4σ Shewhart chart. This is unoccupied ground too.

### 7.2 Both controls, at matched ARL₀

PROGRAM.md §3.12 — a null control alone certifies a broken estimator as readily as a working
one, so every detector is also run against a **planted, known-size shift**. Comparison is at
matched ARL₀ (~1500 samples), the only fair protocol: a detector with ARL₀=100 is *supposed* to
alarm ~15 times in 1500 steps, so "did it ever alarm" is meaningless.

| planted shift | e-detector | CUSUM | BOCPD |
|---|---|---|---|
| p 0.50→0.60 | power 1.00, **delay 158** | power 0.92, delay 412 | power 0.00, — |
| p 0.50→0.70 | power 1.00, **delay 52** | power 1.00, delay 108 | power 0.00, — |
| p 0.50→0.80 | power 1.00, delay 20 | power 1.00, **delay 18.5** | power 0.50, delay 158.5 |

The e-detector **dominates CUSUM by ~2.5× in detection delay** for small and medium shifts and
ties at large ones. BOCPD is not competitive — and in fairness that is misspecification (a
Normal-Inverse-Gamma model on a Bernoulli stream), which is precisely the cost being measured:
BOCPD needs an observation model *and* a hazard prior, i.e. two knobs, where the e-detector
needs neither.

### 7.3 Live, on the operator's coins — and the null that kills it

Merged tape: BigQuery replay + live RPC, deduped on signature, **2026-08-13 00:04 → 08-14 03:22**
(~27h). weave 2,356 swaps, nosis 7,687, DREGG 530, SOLVE 165 (too few to run).

**Two nulls, compared at matched density** (PROGRAM.md §3.13 — one null is a knob, not a test).
The threshold is set so the **i.i.d. permutation** null alarms at exactly 2.0 per 1000 swaps;
observed and block-null rates are then read off *at that same threshold*.

| pool | lag-1 sign autocorr | i.i.d. null | **observed** | **block-50 null** | excess over block null |
|---|---:|---:|---:|---:|---:|
| weave | +0.328 | 2.0 | 4.775 | 4.509 | **+0.265** |
| nosis | +0.230 | 2.0 | 4.553 | 4.634 | **−0.081** |
| DREGG | +0.448 | 2.0 | 4.717 | 5.307 | **−0.590** |

Against the i.i.d. null the observed rate looks like a **2.4× excess** — a publishable-looking
alarm. Against the **autocorrelation-preserving** block null it is **zero or negative in all
three pools.** The same holds for a second, independent observable (robustly standardised signed
SOL size under CUSUM): nosis observed 1.63 vs block null 1.99; weave 2.65 vs 2.92; DREGG 4.72 vs
4.72.

**Verdict: on 27 hours of tape, the sign and size of order flow carry no changepoint structure
beyond their own marginal and short-range autocorrelation.** What a single-null study would have
reported as deterioration is metaorder splitting — buys follow buys, sells follow sells, at
lag-1 autocorrelation +0.23 to +0.45. This is a real, measured property of the flow; it is just
not a regime change.

Nor is there direction. Median forward price move after an alarm vs at matched random times:
weave −0.37% vs −1.51%, nosis −1.76% vs −1.16%, DREGG −1.67% vs −3.35%. The detector answers
"something changed", never "which way" — and on this tape it does not even reliably answer the
first.

**A defect caught mid-study, worth recording.** The first version matched thresholds to a target
ARL₀. On nosis the target exceeded the usable series length, the search collapsed onto a grid
endpoint, and it returned a **saturated** detector (A=1.0) alarming every refractory period on
any input. It reported observed = i.i.d. = block = 5.041 to three decimals, which reads like a
beautifully clean null and is in fact a broken instrument — the §3.12 failure mode exactly. The
fix is matched *density* rather than matched nominal level, plus an explicit
`calibration_degenerate` flag in the output.

---

## 8. Order-flow decomposition, and Marino's asymmetry refuted in sign

**The multi-wallet-in / single-wallet-out claim does not hold on these pools.** Marino & Lillo
argue accumulation is fragmented across many wallets while the dump is concentrated in one. On
signer-bearing records, all four pools show the **opposite**:

| pool | records w/ signer | buy-side top-1 share | buy HHI | sell-side top-1 share | sell HHI |
|---|---:|---:|---:|---:|---:|
| weave | 296 | 0.134 | 0.053 | **0.066** | **0.038** |
| nosis | 2,317 | 0.276 | 0.086 | **0.183** | **0.047** |
| DREGG | 81 | 0.351 | 0.182 | **0.280** | **0.115** |
| SOLVE | 165 | 0.127 | 0.060 | 0.136 | 0.069 |

Sell-side concentration is **lower** than buy-side in three of four, and level in the fourth.

Two honest qualifications, and they cut both ways:
1. **Marino never measured the buy side.** Checked against the paper: the multi-wallet
   accumulation half is an *incentive argument* with an explicit deferral ("we leave a
   systematic study of pump-prediction mechanisms to future work"). The only number attached to
   the asymmetry is **56.41% one-wallet vs 43.59% multi-wallet dump episodes** — a bare
   majority, not the overwhelming regularity the framing implies.
2. **Our window is 27 hours of a quiet regime on established survivor tokens**, and signers
   exist only on the RPC-sourced subset (296/2,356 = 12.6% for weave), which is a
   *time-contiguous slice*, not a random sample. Marino measures launch-phase pump.fun tokens.
   These are different populations and the disagreement may be regime, not error.

The defensible statement: **in the operator's actual holding regime, distribution is more
dispersed than accumulation, so a "one wallet is dumping" trigger would not have fired**, and
the asserted asymmetry should not be built on without re-measuring it on the specific tokens
held.

Diagnostics retained (not signals): Kim–Jo `A_n(r)` burstiness — weave 0.227, nosis 0.282,
SOLVE 0.334 — used instead of Goh–Barabási `B` because `B ≤ (√(n−1)−1)/(√(n−1)+1)` (0.817 at
n=100) is confounded with event count, making cross-token comparison at different trade counts
invalid. Fano factor at 1-minute bins: weave 14.69, nosis 17.38, SOLVE 9.70, giving a
Hardiman–Bouchaud branching **floor** of n ≥ 0.739 / 0.760 / —. That is a floor, never a
measurement: σ²_W/W under-estimates and becomes exact only as W→∞, so it can refute a high
branching ratio and never confirm a low one.

---

## 9. What was demoted, and why

| method | verdict |
|---|---|
| **Hawkes / branching ratio** | **Demoted, and not for cost.** Filimonov & Sornette show Hawkes on a *mixture of pure Poisson segments with regime changes* returns n̂≈1 when the truth is **0**; concatenating n=0.5 and n=0.2 segments estimates n̂=1.0, and a 60% background-rate difference alone reaches criticality. A memecoin's arrival process *is* a regime mixture — launch, plateau, dump, death. The statistic is driven to criticality by exactly the structure we want to detect and cannot separate the two. Kept only as the kernel-free Fano floor. |
| **Fine–Gray / cause-specific Cox** | Demoted on event counts (10 CLIFF events total). A subdistribution HR here has a CI spanning an order of magnitude. |
| **BOCPD** | Demoted on measurement (§7.2) — two knobs (observation model + hazard prior) where the e-detector has none, and not competitive at matched ARL₀. |
| **Conformal prediction** | Demoted as **premature, not wrong**. Calibrating across tokens is the right instinct, but conformal wraps a point predictor and §5 shows we do not yet have one whose signal survives falsification. Conformalising noise yields beautifully calibrated intervals of width 1.0. Revisit when there is a predictor. |
| **Goh–Barabási burstiness** | Demoted for Kim–Jo `A_n(r)` — finite-size ceiling makes cross-token comparison invalid. |
| **GNNs / SVN co-trading / temporal-graph models** | Demoted on the record already in PROGRAM.md §1.5 and §4.1. Nothing here disturbs it; memorisation remains the baseline to beat. |
| **First-passage-from-birth survival** | Demoted on measurement (§3) — it measures the launch shakeout, not deterioration. |

---

## 10. What would actually move this forward

1. **The cohort has no flow.** The survival model runs on hourly OHLCV; exact signed flow exists
   only for the 4 cluster pools. Putting real OFI into the CIF needs `bulk_history` for the
   *cohort*, which is BigQuery spend we did not make. This is the single highest-value
   increment: every covariate tested in §5 was price/volume-derived, and every one of them
   failed falsification. Flow-derived covariates have not been tested at all.
2. **27 hours is not enough tape** to conclude much about changepoints. The null result in §7.3
   is honest for this window and should not be generalised to "changepoint detection does not
   work on memecoins."
3. **Signers on the bulk path** (the 267 GB/day `accounts` column) would make §8 a real
   measurement rather than a 12.6% windowed slice.
4. **The recovery mode** was deliberately left out (§3) rather than faked. It is recoverable as
   `CIF_CLIFF` conditioned on subsequent DOUBLE and is the natural next mode to add.

---

## 11. Methodology compliance (PROGRAM.md §3)

| # | requirement | where |
|---|---|---|
| 1 | temporal splits only | §6 — token-disjoint **and** temporal, 20 partitions |
| 2 | entity-level grouping | §6 split by token; §4 CIs by entity-level bootstrap |
| 3 | never SMOTE/resample | no resampling anywhere; natural base rates throughout |
| 4 | baselines before models | non-parametric AJ before any regression; Cox/Fine–Gray demoted |
| 5 | base-rate-preserving metrics | CIFs and mode mixes, never accuracy or ROC-AUC |
| 7 | report the threshold with every number | §3 table; every knob in `Thresholds`, echoed into results JSON |
| 8 | clock-based, never displacement-based censoring | §2 (2607.02823's failure); §3 (our 1000-bar cap handled as left truncation) |
| 9 | trials accounting | 4 pre-committed covariates, all 4 reported including failures; 2 observables in §7.3, both reported |
| 10 | run the null | §6 permutation null; §7.3 two nulls |
| 12 | **both** controls | §7.2 known-zero **and** known-effect worlds |
| 13 | two nulls at matched density | §7.3 i.i.d. and block-50 at a matched threshold |

**A null result is a result.** §7.3 is one, §5 kills a covariate finding this study generated
itself, and neither is buried.
