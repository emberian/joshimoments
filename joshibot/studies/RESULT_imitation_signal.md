# RESULT: imitation swarms — the costly-signal channel, and it is a null with a sign

Run 2026-08-15 with the tape pinned:

```
uv run --group research python -m studies.imitation_signal --report \
    --tape-end 1786798500 --k 3 --window 1800 --horizon 3600
```

The pin matters — the collectors are live, so every extra minute makes one more row
horizon-eligible and moves every number. Full output at `studies/data/imitation_live_run.txt`
(untracked: `studies/data/` is gitignored) and it reproduces from the tapes in `state/`.

Code: `shitcoims_scalper/swarm_detect.py`, `studies/imitation_signal.py`,
`tests/test_swarm_detect.py`.
Data: `state/firehose/new_token/`, `state/swarms/census-*.jsonl`, `state/swarms/candles/`.
**Spend: $0.00.** Every endpoint used is keyless and free.

---

## 0. The one-paragraph answer

**A swarm of imitators carries no information about the host's forward return that market cap
and age do not already carry, and the one dose-response that looks like the hypothesis is
confounding.** On 9,708 launches over 9.8 h of listening, the detector fires 547 onsets; 445
survive censoring. Against matched never-swarmed hosts balanced on size, age, dev buy,
turnover and **momentum already banked**, the difference in host return is **−0.86% / +1.32% /
+0.01% / +1.12% / +13.80%** mean at 5/15/30/60/120 min, with **median difference exactly
+0.00% at every horizon** and Mann-Whitney p = 0.24, 0.35, 0.33, 0.80, 0.38. Adding the swarm
block to the free columns *lowers* test AUC on the short label from **0.842 to 0.813**, and
**permuting which coin got swarmed beats the real assignment in 20 of 24 draws** — the same
signature the callout study found for caller identity. Only **6 of 30 tests survive BH-FDR at
q = 0.10**, and five of those six are the clone arm, which the live/dead decomposition shows is
a **24–28 pp dead-fraction gap** rather than a return: among rows that actually traded, the
clone edge at 60 min is **−0.36%**. Meanwhile the detector itself is barely above the collision
floor: real families exceed an i.i.d.-shuffled stream by only **1.06×** and onsets by **1.13×**.
The costly-signal mechanism is refuted in its own strongest form — the correlation with the
number of *independent payers* collapses from ρ = −0.165…−0.224 (p < 0.001) to
**−0.007…−0.088 (all p > 0.06)** once the free columns are removed.

Two things did survive, and both are real:

* **Swarmed hosts live much longer.** Median survival from onset is **10.7 min vs 1.0 min** for
  matched controls (log-rank p < 0.0001), and at 60 min **67.2% are dead vs 82.8%**. A swarm is
  a genuine marker of *attention*. It simply does not convert into return.
* **The sign, where there is one, is negative.** Every raw dose measure points down, the
  parasite arm's median return is negative at every horizon, and nothing anywhere in this
  study points up. Consistent with the callout result and for a related structural reason:
  by the time three parasites have paid to attach themselves, the move that attracted them
  has happened.

This is a null with a power floor, not a shrug. A **uniform multiplicative shift of +1% to +5%**
applied to every row that traded would have been detected at 80% power. And it does not
refute "watch for imitators" as *situational awareness* — §9 states which version survives.

---

## 1. The hypothesis, and the one reason to expect a different answer than last time

The operator's words: *"noticing when scam/imitators start popping up. i'm willing to bet
that if we are fast we can setup positions that will massively gain from them when they are
even slightly legitimate."*

`RESULT_callout_edge.md` closed the social channel with a null that had a sign — buying a
callout returns **−11.9% at 1 h**, the callout block *lowers* test AUC from 0.796 to 0.665,
and permuting caller identity **beat** the real identity in 24 of 24 draws. The structural
reading offered there was that talking is free, so the loudest callers are recruiting exit
liquidity.

An imitator is not talking. A clone costs a create transaction plus a dev buy, and it is
aimed at a chosen target. A swarm is therefore a **costly signal**: N adversaries each
spending money to assert that one specific coin has attention worth stealing. That is the
one theoretical reason to expect a different answer from the callout channel, and this study
exists to make it survive the data or die.

It is worth naming the reason it might still fail, before any number appears. Nothing
guarantees a parasite's attention estimate is *early*. If clones show up only once a coin has
already run, the swarm is a lagging indicator of a finished move, and paying to attach
yourself to it is perfectly consistent with the host being over.

---

## 2. The instrument

### 2.1 Two transports, because a socket is not a census

Launches come from the union of two sources with different failure modes:

| source | what it gives | what it misses |
|---|---|---|
| PumpPortal socket (`state/firehose/new_token/`) | push, ~2 s latency, `traderPublicKey`, `solAmount`, `initialBuy`, `marketCapSol`, `uri` | **no `image_uri`**, no vendor clock at all, and it drops when the socket drops |
| pump.fun REST list (`state/swarms/census-*.jsonl`) | `created_timestamp` (a real vendor clock), `image_uri`, `ath_market_cap`, `reply_count` | it is a poller — the failure mode this repo was already burned by — and pages to a hard wall at `offset≈2000`, ~1.9 h of history |

Measured agreement over a quiet 33-minute window: the socket carried **565 of 572** REST
coins, **98.8%**. So the socket is good when it is up, and the census exists for when it is
not — and for `image_uri`, which turns out to be one of the strongest clone links in the
data.

Three defects in the raw tape that a naive read would have propagated:

1. **A 172-minute hole.** The tape for 2026-08-15 has one clean segment and one long gap.
   The study restricts to the ledger's demonstrated `watch_open`/`watch_close` intervals;
   outside them, absence of a launch is our blindness, not the market's silence.
2. **Double ingestion.** Two socket windows were connected simultaneously for ten minutes and
   every launch in that stretch landed on the tape twice. Deduping by mint is not hygiene
   here — counting rows would have doubled the apparent launch rate and manufactured a family
   out of every coin.
3. **The real launch rate is ~1090/hour**, not the ~300/hour a naive read of the gappy tape
   suggests.

### 2.2 Prices, free and retroactive

`https://swap-api.pump.fun/v1/coins/<mint>/candles?interval=1m&currency=SOL` returns
per-minute OHLCV in SOL, keyless, one request per mint, and **retains at least a month** —
so the price path of any coin in the tape is recoverable after the fact rather than having to
be polled forward. A candle exists only for a minute in which the pool traded.

Validated against the socket's own `marketCapSol` on 24 fresh mints: `candle[0].open × 1e9 /
marketCapSol` has median **0.974** — the candle open is the bucket's first print, usually just
before the dev buy that the socket's market cap already includes.

**Why mark-to-last-trade is close to an executable price here, unlike on an AMM.** The
callout study had to caveat its marks: a coin that stopped trading has a quote but no
counterparty. On the pump.fun bonding curve the curve *is* the counterparty — a sell executes
against the program at a deterministic price whether or not another human is present. The
study still reports `live` (did anything trade in the window) beside every return, because
"attainable" is not "attained", and it reports the two halves separately (§5.3) because that
distinction turns out to decide the whole clone-arm result.

### 2.3 What counts as an imitation

Launches are clustered by five links, strongest first, and every family records which fired:

| link | meaning |
|---|---|
| `uri` | identical metadata document — same artwork, same description. As close to a confession as this data gets |
| `image` | identical `image_uri` (census only) |
| `symbol` | identical alphanumeric-folded ticker |
| `symbol_squashed` | identical after collapsing character runs: `READ` ≡ `READDDDDDDDDD`. Known cost: also merges `BULL` with `BUL`, so it is its own kind and never folded into `symbol` |
| `name_near` | normalised edit distance ≥ 0.82 on the folded name, trigram-blocked |

### 2.4 The host is an observable, not a guess

"Earliest member" is the right prior — an imitation postdates its target — but it is wrong
exactly when it matters, because if the original launched before we were listening then the
earliest member *we saw* is itself a clone. So the detector takes an optional traction probe
and the host is the family member with the most SOL-equivalent turnover **before** the onset
instant, falling back to earliest. Only candles at or before the onset are read, so the probe
cannot see the future the study then measures. Every event row records which rule fired, and
families whose earliest member sits within one matching window of the stream's own start are
flagged `host_left_censored` and excluded from the cohort.

### 2.5 The taxonomy that must never be pooled

`traderPublicKey` splits the phenomenon in two:

* **parasite** — no single deployer emits more than 60% of the clones *and* the host's own
  deployer is absent from them. Independent adversaries converging on one target. **This is
  the hypothesis.**
* **farm** — one deployer emits more than 60% of the clones. A factory shipping inventory.
* **self_farm** — the host's own deployer did most of the cloning. A dev spamming their own
  idea.
* **mixed** — the host's deployer is present among the cloners but not dominant.

**The honest limit on this discriminator, stated once and loudly:** distinct-deployer count
is an *upper* bound on independence. Sybil wallets are free, and MELT puts 36.5% of supply in
coordinated hands. Nothing in this study clusters wallets by funding ancestry (that is
PROGRAM.md signal #2, and it is a prerequisite this study did not have). A four-wallet
"parasite" swarm may be one actor with four wallets. The detector records each cloner's prior
launch count in the same tape as a cheap partial check — a wallet with fifty prior launches is
infrastructure — but the clean test is unbuilt.

---

## 3. The three ways this could have produced a false positive, and what was done about each

1. **Ambient collisions.** Only 23.6% of launches carry a ticker unique within 30 minutes
   (measured by the callout study's cashtag resolver). `SOLANA` launches ~25 times in four
   hours with nobody imitating anybody. Handled by **two** detector-level nulls, because
   PROGRAM.md §3.13 is explicit that one null is a knob rather than a test:
   * **shuffle** — launch identity permuted i.i.d. across the tape. Every symbol keeps its
     frequency; same-symbol launches no longer arrive together. This is the collision floor.
   * **rotation** — identity shifted as a block. Because the launch rate is near-constant, a
     rotation carries a burst *intact* to a different hour and merely lands it on a different
     host. It answers the narrower question "is it the swarm, or just a coin that had
     traction at that minute?" — and anyone reading its family count as "the detector finds
     nothing" has misread it. Both are run; the difference between them is reported.
2. **The free columns.** Market cap and age are the reigning champions at AUC 0.796. A coin
   that attracts clones is a coin that has *already moved*, and "coins that just moved keep
   mean-reverting" is not the hypothesis. Handled by matched controls that balance momentum
   and turnover, not just size and age — see §5.2 for how much this mattered — and by the
   incremental-AUC test, which is the only question that counts.
3. **Survivorship.** Dropping the coins that die flipped the callout cohort's 8 h return from
   −14.6% to **+25%**. Every row here is priced mark-to-last-trade, the dead are counted as
   their own state in a competing-risks table, and §5.9 splits the clone arm into rows that
   traded inside the window and rows that did not.

---

## 4. Methodology bindings actually honoured

* **Temporal splits only**, with the **family as the indivisible entity** — a host and its
  clones share a deployer network, an image and a minute of market regime, and a control
  inherits its treated row's family id so a matched pair cannot straddle either.
* **No resampling of any kind.** Natural base rates throughout.
* **Both controls.** A known-zero world (three label nulls) *and* a known-effect world (a
  planted treated→label effect the estimator must recover). A green zero-control certifies a
  broken estimator exactly as readily as a working one.
* **Competing risks** via `lifelines`, reported as {up, down, dead} rather than a mean over
  survivors.
* **Trials counted and FDR'd**, with the sweep over the detector's two free knobs (`k`, the
  matching window) reported rather than hidden.
* **A power floor.** A null without a minimum detectable effect is a shrug, so every headline
  comparison carries the multiplicative shift the cohort could have detected at 80% power.

---

## 5. The result

### 5.1 The taxonomy: imitation is mostly a factory, not a mob

Over 9.8 h of listening, 9,708 deduped launches, 1,001 families of size ≥ 2 and 547 onsets at
k = 3:

| | families (size ≥ 2) | onsets (k ≥ 3) |
|---|---|---|
| `parasite` — distinct deployers, host's dev absent | 218 (21.8%) | 222 (40.6%) |
| `farm` — one deployer > 60% of clones | 347 (34.7%) | 82 (15.0%) |
| `self_farm` — the host's own deployer cloning itself | 349 (34.9%) | 166 (30.4%) |
| `mixed` | 87 (8.7%) | 77 (14.1%) |

**Roughly 70% of imitation families are one wallet talking to itself.** The launch farms and
self-farms together outnumber genuine multi-deployer convergence three to one at the family
level. This is the single most important descriptive fact in the study, and it is why the
brief's instruction never to pool the two arms was correct: a naive "N clones appeared"
detector spends most of its firing on inventory.

The largest real family spans `website`, `READDDDDDDDDD` and `GRANNY` across 363 launches,
held together by a shared `image_uri` — one campaign varying its ticker and name while reusing
artwork. It is correctly one object, and it is a factory.

### 5.2 Onset lag: "fast" is not an infrastructure problem

| | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|
| host launch → onset | 0 s | 27 s | **98 s** | 344 s | 1018 s |
| first clone → onset | 1 s | 17 s | **80 s** | 262 s | 906 s |

And the ingestion term, measured rather than quoted: our socket is **p50 1.18 s / p95 1.81 s**
behind pump.fun's own `created_timestamp`, on 9,258 launches, and never ahead of it.

So the budget decomposes cleanly. About one second to *hear* about a launch; about a hundred
to be *sure* it is a swarm. The second term dominates the first by two orders of magnitude,
which locates "if we are fast" entirely in the choice of k — how many clones you are willing
to wait for — and not in latency engineering. Waiting for a fourth clone costs a further
~60 s of median lag and throws away a third of the events (547 → 367).

Conditioning returns on the lag answers the too-early/too-late question, and the answer is
neither: at 60 min, onsets firing inside 60 s return −7.75% mean / −14.24% median, and those
firing at 60–300 s return +6.49% mean / −3.49% median. The median is negative in the fast bin
and the momentum already banked at onset is 0.00% there versus −5.08% in the slower bin, i.e.
the earliest detections catch coins that have not moved yet — and they still do not go up.

### 5.3 The event study, and why the raw numbers are not the finding

Raw host returns from onset are negative at every horizon (all onsets: −3.26% / −8.66% /
−10.45% / −2.41% / −5.81% mean at 5/15/30/60/120 min; medians −0.05% to −3.56%). The parasite
arm's *medians* are worse than the farm arm's at every horizon (−4.76%, −8.13%, −10.17%,
−11.97%, −15.44%) even though its means occasionally turn positive — a heavy right tail on a
small n, which is exactly why the medians and the rank tests carry the argument here.

But raw returns are not evidence of anything without the counterfactual, because a swarm forms
around a coin that has already moved.

### 5.4 The control arm: the effect is the confounder

Matching on size, age and dev buy alone leaves the covariates badly imbalanced (|SMD| up to
0.67) and produces an apparent **−11% to −17%** treated-minus-control effect at
Mann-Whitney p ≈ 0.0005. Adding `momentum_so_far`, `log_vol_sol_so_far` and
`traded_minutes_so_far` to the match — the three covariates that encode "this coin has already
moved" — brings every |SMD| inside 0.21 and the effect **disappears**:

| horizon | treated mean | control mean | Δ mean | Δ median | Mann-Whitney p |
|---|---|---|---|---|---|
| 5 m | +1.72% | +2.59% | −0.86% | **+0.00%** | 0.2445 |
| 15 m | −0.06% | −1.38% | +1.32% | **+0.00%** | 0.3496 |
| 30 m | −1.69% | −1.70% | +0.01% | **+0.00%** | 0.3253 |
| 60 m | +0.81% | −0.31% | +1.12% | **+0.00%** | 0.7965 |
| 120 m | +11.63% | −2.17% | +13.80% | **+0.00%** | 0.3761 |

171 treated rows found a control; 309 controls at ≤ 2 per treated row. The 120 min mean
difference of +13.80% against a median difference of exactly zero and p = 0.38 is a single
right-tail coin, and is reported here purely so nobody rediscovers it as a finding.

The parasite-only arm (59 treated, 105 controls) is null too, with median differences of
−0.11% to −0.12% and p = 0.07–0.40.

**Power floor.** A uniform multiplicative shift of **+1%** (30/60/120 min), **+3%** (15 min) or
**+5%** (5 min), applied to every row that traded, would have been detected at 80% power and
α = 0.05. The caveat that keeps this honest: a *uniform* shift is the easiest possible effect
for a rank test to see, because it moves every live row the same way. A real effect
concentrated in a minority of coins would need to be much larger.

### 5.5 The dose-response, which is where the hypothesis actually dies

The theory's own sharpest prediction is that information scales with the number of independent
parties paying and with the amount paid. Pre-declared before looking, and it is the one place
the raw data looks alive:

| horizon | ρ(distinct deployers) raw → partial | ρ(clone spend) raw → partial |
|---|---|---|
| 5 m | −0.165 (p 0.0005) → **−0.088 (p 0.065)** | −0.198 (p<1e-4) → −0.138 (p 0.0039) |
| 15 m | −0.182 (p 0.0001) → **−0.032 (p 0.51)** | −0.210 (p<1e-4) → −0.089 (p 0.065) |
| 30 m | −0.224 (p<1e-4) → **−0.072 (p 0.15)** | −0.249 (p<1e-4) → −0.110 (p 0.025) |
| 60 m | −0.217 (p<1e-4) → **−0.053 (p 0.30)** | −0.261 (p<1e-4) → −0.105 (p 0.041) |
| 120 m | −0.200 (p 0.0003) → **−0.007 (p 0.90)** | −0.257 (p<1e-4) → −0.098 (p 0.080) |

"Partial" removes what the six free columns explain of both rank series. Three readings, all
of which matter:

1. **The number of independent payers — the core of the costly-signal argument — carries
   nothing.** It goes from p < 0.001 at every horizon to p > 0.06 at every horizon. What looked
   like N adversaries voting with their wallets was N adversaries picking a coin that was
   already big.
2. **Clone spend keeps about half its magnitude** (ρ ≈ −0.10 to −0.14) and stays under 0.05 at
   three of five horizons. Only the 5 min value survives BH-FDR. Call it a weak residual, not
   a signal.
3. **Every surviving sign is negative.** Even taken at face value, more money spent by
   imitators predicts a *worse* host. That is the opposite of the hypothesis, in the
   hypothesis's own preferred statistic.

`clone_count` — the number of clones, without regard to who paid or how much — is null raw
*and* partial at every horizon. The count is the thing a naive detector would trigger on, and
it is the least informative of the three.

### 5.6 Conditional information: the swarm block is worse than scrambling it

Temporal split at 08:59:51Z, families never straddling, 324 train / 325 test rows.

| block | label `r60m > 0` (base 6.2%) | label `r60m ≤ −10%` (base 24.3%) |
|---|---|---|
| free only | 0.721 [0.606, 0.827] | **0.842 [0.793, 0.887]** |
| swarm only | 0.668 [0.550, 0.786] | 0.769 [0.718, 0.818] |
| free + swarm | **0.772 [0.691, 0.840]** | 0.813 [0.762, 0.857] |

On the label that matters operationally — the short label, which has a usable base rate
because a dead coin marks at exactly 0.00% and collapses the "up" label to 6% — **adding the
swarm block lowers AUC from 0.842 to 0.813**, and the **swarm-block permutation null beats the
real assignment in 20 of 24 draws** (null mean 0.825 vs real 0.813). Scrambling which coin got
swarmed makes the model *better*. That is the identical signature `RESULT_callout_edge.md`
found when it permuted caller identity and beat reality 24/24.

Both label nulls are dead flat (i.i.d. 0.510, rotation 0.503, beaten 0/24), so the model does
hold real signal — and all of it is in the free columns. The known-effect control recovers a
planted treatment→label effect at 0.807 vs 0.704, so the estimator is not simply blind.

### 5.7 Survival: the one thing a swarm genuinely marks

| | n | died | median survival from onset |
|---|---|---|---|
| swarmed hosts | 445 | 344 | **10.7 min** |
| matched controls | 309 | 280 | **1.0 min** |

Log-rank p < 0.0001. Competing risks at 60 min, three exclusive states:

| | up | down | dead |
|---|---|---|---|
| treated | 7.3% | 25.5% | **67.2%** |
| control | 3.4% | 13.8% | **82.8%** |

A swarmed host is about ten times less likely to be a coin nobody ever trades again. This is a
real, large, robust difference and it is the only one in the study. It says imitators are
correctly identifying attention — they are simply identifying attention that has already
peaked, so the survival advantage arrives without a return advantage. Note also what it does
to the naive reading: dropping the dead would compare 33% of the treated arm against 17% of
the control arm, which is precisely the survivorship that flipped the callout cohort from
−14.6% to +25%.

### 5.8 The detector is 87% collision floor

| | real | i.i.d. shuffle | ratio | rotation | ratio |
|---|---|---|---|---|---|
| families (size ≥ 2) | 1001 | 944 | **1.06×** | 1016 | 0.98× |
| onsets (k ≥ 3) | 547 | 482 | **1.13×** | 553 | 0.99× |
| largest family | 363 | 224 | **1.62×** | 363 | 1.00× |

The shuffle preserves every symbol's frequency and every launch time and destroys only
co-arrival; it is the world with no imitation in it. **At k = 3 the detector finds only 13%
more onsets than that world does.** Imitation as a temporal phenomenon is real but it lives in
the tail — the largest family is 1.62× the shuffled maximum — and the bulk of what a k = 3
detector fires on is the ambient ticker collision the brief warned about, exactly as the
callout study's 23.6%-unique-ticker measurement predicted.

The rotation null reproduces the real counts almost exactly (0.98×, 0.99×, 1.00×) because the
launch rate is near-constant, so a rotation carries a burst intact and merely lands it on a
different host. That is not a failure of the detector; it is the null answering its own,
narrower question — and it answers it in the negative too, since the rotated worlds' host
returns (−3.6% to −13.3% mean at 60 min) bracket the real one (−2.4%).

**Detector recovery.** 40 planted textbook parasite swarms: 36 (90%) recovered as a single
family containing their host. Only 14 (35%) had the host *correctly nominated* — the traction
rule frequently prefers a member of a family the plant merged into. That is a real weakness of
host identification and it is stated rather than buried; it biases the study toward the null
by pointing some rows at the wrong coin.

### 5.9 The clone arm, and the artifact that would have sold it

Buying the imitators at their own launch (4,202 clone rows, 2,895 matched launch controls)
looks like the best result in the study: **+4.16% / +4.39% / +5.66% / +3.69% / +4.53%** mean
and **+3.17% / +3.84% / +4.30% / +4.36% / +4.43%** median difference, every one at
p < 0.0001, all five surviving BH-FDR.

It is bookkeeping. Clones have **no trade in the window 39–41% of the time; the controls
11–16%**. A coin with no trade after entry marks at exactly 0.00%, so an arm made of dead
coins "beats" an arm of live coins that are merely falling, with no tradeable cent changing
hands. Restricting both arms to rows that actually traded:

| horizon | all rows Δ mean | **traded-only Δ mean** | dead-fraction gap |
|---|---|---|---|
| 5 m | +4.16% | +2.37% | +24.6 pp |
| 15 m | +4.39% | +1.79% | +26.3 pp |
| 30 m | +5.66% | +3.23% | +27.3 pp |
| 60 m | +3.69% | **−0.36%** | +28.1 pp |
| 120 m | +4.53% | +1.61% | +27.6 pp |

At the primary horizon the edge is **negative** once the composition difference is removed,
and the residual few percent elsewhere sits inside the 2.26% round-trip cost of the pump.fun
curve at the sizing `studies/exploration_map.py` derives. There is no trade here.

---

## 6. Replication on an independent 24-hour census

The live window is one socket tape with holes over one 9.8 h regime. The strongest available
check is a different day, measured a different way — so the study was re-run end to end on a
**complete 24 h census of 2026-08-14**, built from the bulk pump pull plus the batch metadata
endpoint (§2.5 of the code docstring; `swarm_detect retro --day 2026-08-14`). 74,046 mints
enumerated, 33,202 of them created that day, in 218 s and $0.

```
uv run --group research python -m studies.imitation_signal --report \
    --retro-day 2026-08-14 --k 3 --window 1800 --horizon 3600 --no-candidates
```

The two cohorts are **never pooled**. This is a replication, not extra n.

| | live window (9.8 h) | retro census (24 h) |
|---|---|---|
| launches | 9,708 | 33,202 |
| families (size ≥ 2) | 1,001 | 3,453 |
| onsets at k = 3 | 547 | 1,905 |
| parasite share of onsets | 40.6% | 46.8% |
| treated rows | 445 | 1,830 |
| onset lag p50 (host → onset) | 98 s | **90 s** |
| median survival, treated | 10.7 min | **10.6 min** |
| median survival, control | 1.0 min | **1.0 min** |
| dead at 60 min, treated / control | 67.2% / 82.8% | 58.5% / 80.1% |
| onsets vs i.i.d. collision floor | 1.13× | **1.17×** |

**What replicates exactly.** The onset-lag distribution (90 s vs 98 s median), the survival gap
(10.6 vs 10.7 min treated, 1.0 min control both times, log-rank p < 0.0001), the dead-state
gap, and the excess over the collision floor (1.17× vs 1.13× onsets). These are the study's
solid measurements.

**What replicates as a null.** The matched control comparison. With four times the rows, the
median treated-minus-control difference is **+0.00% at every horizon** again, and the
**5%-trimmed** mean difference is a flat **−0.48% to −0.59%** across all five horizons. The raw
means on this day run **−478% to −803%**, entirely from one control coin that went up
enormously — which is exactly why the trimmed statistic was added, and why no mean in this
document should be read without it.

Mann-Whitney is now significant (p = 0.0000 to 0.023) because n = 376 vs 596 makes a −0.5%
shift detectable. **Significant, tiny, and negative** is the accurate summary, and it is not a
trade: 0.5% sits well inside the 2.26% round trip. It is also partly compositional — the
dead-fraction gap runs −6 to −9.5 pp — and the match on this day did **not** succeed
(worst |SMD| 0.28 on age), because the retro census carries no dev-buy field and matches on
five covariates rather than six. The report says so in its own output rather than in a
footnote.

**What flips, and therefore is not a finding.** The swarm block's incremental AUC:

| | label `r60m > 0` | label `r60m ≤ −10%` |
|---|---|---|
| live: free → free+swarm | 0.721 → 0.772 (+0.051) | 0.842 → **0.813 (−0.029)**, permutation beats real 20/24 |
| retro: free → free+swarm | 0.672 → **0.653 (−0.019)**, permutation beats real 3/24 | 0.841 → 0.856 (+0.015), permutation beats real 0/24 |

The sign of the swarm block's contribution flips across day × label. That pattern — not any
one of the four numbers — is the finding: there is no stable conditional information. The
retro free-only block is also handicapped by the missing dev-buy column, so its +0.015 is an
upper bound on what the swarm block adds there.

**What sharpens.** The dose-response on *distinct clone deployers* — the core costly-signal
quantity. On 1,765–1,828 rows the partial correlation is **−0.075 to −0.091, p = 0.0001 to
0.0014, surviving FDR at every horizon**. So with four times the power the effect is real, and
it is **negative**: more independent parties paying to imitate predicts a *worse* host. It is
also tiny — ρ ≈ −0.08 is 0.6% of rank variance. The hypothesis is not merely unsupported; in
its own sharpest statistic, at the best power this study can bring, it points the other way.

**Detector recovery on this day:** 40/40 planted swarms recovered as one family (100%), 12/40
with the host correctly nominated (30%) — the same host-nomination weakness as the live window.

---

## 7. The candidates feed contract

`state/swarms/candidates.jsonl`, append-only JSONL, one row per onset. It carries **evidence,
never a verdict** — a consumer decides direction and size; the file never says "buy".

```json
{
  "kind": "swarm_candidate", "schema": 1,
  "t_ingest": "<our clock, ISO8601 UTC>", "t_ingest_unix": 1786852740.5,
  "t_event": "<onset instant — the tradeable moment, NOT the host's launch>",
  "t_event_unix": 1786852740.0,
  "t_event_source": "launch_clock:vendor | launch_clock:ingest",
  "family_id": "f0000123",
  "host_mint": "…", "host_symbol": "…", "host_launch_t": "…",
  "host_left_censored": false,
  "host_rule": "traction | traction_agrees_earliest | earliest | earliest_no_traction",
  "taxonomy": "parasite | farm | self_farm | mixed",
  "clone_count": 2, "distinct_clone_deployers": 2, "clone_spend_sol": 4.0,
  "lag_from_host_s": 66.0, "lag_from_first_clone_s": 40.0,
  "match_kinds": {"symbol": 2},
  "host_mcap_sol_at_onset": 95.9, "host_age_s_at_onset": 66.0,
  "host_momentum_at_onset": 0.31, "host_traded_minutes_at_onset": 2,
  "members": ["<host mint>", "<clone mint>", "…"]
}
```

Consumer notes, which matter more than the schema:

* Both clocks appear twice: ISO for a human, unix float under the `_unix` suffix every
  `shitcoims_paperdesk.feeds.Source` already speaks, so tailing this needs no translation.
* This is an **event** feed, not an observation feed. It deliberately carries no curve
  reserves: a consumer already tails `state/firehose/new_token/` and should read
  `vSolInBondingCurve` from there, fresh, rather than from a stale copy here.
* `t_event` is the **onset**, not the launch. Entering from the launch is a different
  (and unmeasured) trade.
* `host_left_censored: true` means the detector could not see far enough back to be sure the
  nominated host is the original. Those rows are excluded from every number in this document
  and should be excluded from any position.
* **`taxonomy` must be read before `clone_count`.** A farm's forty clones are one wallet's
  inventory and say nothing about a host.
* **Pre-graduation pump.fun tokens cannot be shorted.** There is no borrow and no perp on a
  bonding-curve token. A negative-signal reading of this feed is therefore an *avoid list*,
  not a short book, until the host has migrated to PumpSwap.

---

## 8. Trials accounting and honest limits

**Every test in the family, BH-FDR at q = 0.10: 6 of 30 survive.** Five of the six are the
clone-arm comparisons that §5.9 shows are a dead-fraction artifact. The sixth is
`dose[partial] log_clone_spend r5m` at p = 0.0039 — negative in sign, i.e. against the
hypothesis. Every treated-vs-control and parasite-vs-control test fails (p = 0.07 to 0.80).
The dose tests enter the family with their **partial** p-values, never their raw ones;
entering the raw ones would let the confounder buy the hypothesis its own FDR survival, and
would have shown 15 of 30 "surviving".

**Sensitivity to the two free knobs**, because they are the only settings not pinned by an
observable (PROGRAM.md §3.7):

| | window 15 m | window 30 m | window 60 m |
|---|---|---|---|
| k = 3 | −4.69% mean, −2.91% med (n 409) | **−2.41%, −0.96% (n 381)** | +3.35%, −0.22% (n 314) |
| k = 4 | −10.47%, −1.98% (n 274) | −10.63%, −1.81% (n 249) | −5.37%, −0.63% (n 208) |
| k = 5 | −11.32%, −0.58% (n 216) | −11.99%, −0.27% (n 199) | −10.04%, −0.38% (n 158) |

Same grid on the 24 h retro census, where the means come out the *other* side:

| | window 15 m | window 30 m | window 60 m |
|---|---|---|---|
| k = 3 | +2.07% mean, −2.32% med (n 1671) | **+2.23%, −1.30% (n 1765)** | +4.01%, −1.37% (n 1633) |
| k = 4 | +3.99%, −1.49% (n 1143) | +6.59%, −0.81% (n 1220) | +6.76%, −0.92% (n 1180) |
| k = 5 | +12.59%, −0.89% (n 852) | +12.61%, −0.37% (n 903) | +13.35%, −0.32% (n 899) |

Across eighteen knob settings on two days the means swing from **−12% to +13%** and the
medians never leave **−2.9% to −0.2%, always negative**. The means are not measuring a return;
they are measuring which cell caught the day's one big coin. This is the whole reason the
document leads with medians, rank tests and a trimmed mean, and it is worth stating as a
standing lesson for the next lane: on a memecoin tape an arm's mean is a lottery ticket.

**BH-FDR on the retro day: 23 of 25 survive** — including `treated-vs-control` at every
horizon. That is not a reversal of the live window's null, it is what happens when n goes from
171 to 376 against an effect of −0.5%: significance arrives, effect size does not. Any reading
of this study that quotes a p-value without the trimmed effect beside it is misreading it.

### Limits, in the order they would bite

1. **Deployer count is an upper bound on independence.** Sybil wallets are free and MELT puts
   36.5% of supply in coordinated hands. Nothing here clusters wallets by funding ancestry —
   PROGRAM.md signal #2, a prerequisite this study did not have. Some share of the 218
   "parasite" families is one actor with several wallets, which means the parasite arm is
   *contaminated toward the farm arm* and the true parasite effect is measured with error. It
   does not rescue the result: the contamination would have to be near-total, and the
   dose-response on distinct deployers is flat rather than noisy.
2. **Host nomination is right 35% of the time in the planted world.** Some treated rows point
   at a clone rather than the original, which biases toward the null.
3. **One 9.8 h window, one market regime.** The pump.fun regime shifts in weeks (PROGRAM.md
   §3.6). §6 reports a 24 h replication on an independent day.
4. **96 onsets (17.6%) were dropped as left-censored** — their family's earliest member sat
   within one matching window of the start of a listening interval, so the true original may
   predate our tape. Dropping them is correct and it is also a selection: it removes swarms
   that formed right after a socket outage.
5. **The power floor is for a uniform shift.** An effect concentrated in a small minority of
   swarms — say, only those with ten or more genuinely independent deployers — is not excluded
   by this study. That cell has n ≈ 0 here.

---

## 9. Which version of the operator's hypothesis survives

The operator wrote: *"if we are fast we can setup positions that will massively gain from them
when they are even slightly legitimate."* Taking that apart against what was measured:

* **"If we are fast"** — measured, and it is not the binding constraint. Ingestion is ~1 s;
  detection is ~98 s median and is entirely a function of how many clones you wait for. Being
  faster does not help, because §5.2 shows the *fastest* detections have the worst medians.
* **"Positions that will massively gain"** — refuted for both readings. Buying the host:
  median difference exactly 0.00% against matched controls at every horizon. Buying the
  clones: the apparent +4% is a dead-fraction artifact and is −0.36% at 60 min among rows that
  traded. `p(2x)` is 2.1% for swarmed hosts against 0.7% for controls at 60 min, on n = 148.
* **"When they are even slightly legitimate"** — this is the part that survives, and only as a
  *filter*. A swarmed host is genuinely ten times more likely to still be trading an hour
  later (67.2% dead vs 82.8%). Imitators are a real attention detector. They are just not an
  early one, and attention that has already been paid for is not a return.

**What NOT to build:** a long book on swarm onsets, or a short book. There is no borrow and no
perp on a pre-graduation bonding-curve token, so the negative sign is not directly tradeable
even where it appears; the honest use of a negative signal here is an avoid-list.

**What is worth building, in priority order:**

1. **Funding-ancestry clustering (PROGRAM.md signal #2) before any re-test of this channel.**
   The single measurement that would change this study's answer is a real independence test on
   the deployers. The costly-signal argument is about *independent* payers, and this study can
   only bound that from above. It is also a prerequisite for signals #1 and #5.
2. **Use the swarm as a survival covariate, not an entry.** The 10.7 vs 1.0 min survival gap is
   the largest effect measured here and it is free to compute. It belongs in the paperdesk's
   exit/hold logic and in any duration model, not in an entry rule.
3. **The tail, not the bulk.** The detector is only 1.13× the collision floor at k = 3 but
   1.62× at the largest family. If anything in this channel is real it is in swarms far beyond
   k = 5, and this window contains too few to test. That is a pre-registerable question for a
   multi-day census (§6 shows the census is now cheap), and it should be declared with its
   threshold *before* the data is cut.
4. **Do not re-test the clone arm without the live/dead decomposition wired in.** It is the
   most seductive artifact in this dataset: n = 4,202, p < 0.0001, survives FDR, and is worth
   nothing.
