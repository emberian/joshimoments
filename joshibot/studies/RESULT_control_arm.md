# The control arm: what the survival filter looks like against the population it drew from

`studies/control_arm.py`, run 2026-08-14. Read-only. 6,686 Helius credits of a 25,000 cap.

`studies/RESULT_lp_history.md` scored the operator's claimed edge as **12 tokens touched, 9
alive, 3 dying, 0 dead**, and called it "a real signal" against a population where most of
these tokens die in a day. This lane built the population, measured it over the same window,
and tested the claim.

---

## VERDICT: **INDISTINGUISHABLE**

Against the fair control the picks come in at p = 0.0020, which clears the Bonferroni bar of
0.0083 for the six pre-registered tests. It does not survive contact with anything else:

| check | result |
|---|---|
| age-matched control, headline threshold | 13/14 survive vs **8.93 expected**, p = **0.0020** |
| move "dead" from <$1k to <$5k liquidity | 10/14 vs 8.58 expected, p = **0.2299** |
| a mechanical "only buy graduates ≥14 days old" screen | expects **12.64 of 14**, operator got 13 |
| picks whose control null is ≈1 (no evidence either way) | **4 of 14** |
| leave one pick out | worst p = **0.0131**, above the Bonferroni bar |
| count "dying" as a failure instead of "not dead" | 10/14 vs 8.59 expected, p = **0.2300** |

The result exists at one definition of dead and one definition of the arm. **PROGRAM.md §3.7:
report the threshold with every number** — and when the verdict moves with the threshold, the
verdict *is* the threshold. A screen with no social information in it at all reproduces the
record. There is no evidence here that knowing the team does anything.

That is not the same as evidence that it does nothing. The design is powered — see §6, the
number is **7** — so this is a null, not an unresolvable.

---

## 1. Three corrections to `RESULT_lp_history.md` before anything else

**(a) It is not 12 tokens. It is 24, and the 12 were the 12 most-traded.**
`scripts/lp/survival.py` builds its list as `mints.most_common(20)` minus the quote assets,
sliced `[:12]`. That is a rank by how many times the wallet touched the token — which is a
rank by how long the operator kept trading it — which is correlated with the token still
being alive. The cutoff at 12 is not a criterion, it is a slice index.

Reconstructing that rank here (`top12` in the output) gives **10 alive of 12, two dead** —
including one mint with no DEX market at all. The published 12 differs from this
reconstruction by one token, because the original counted pre/post token-balance entries and
this counts transfers. Either way the "0 dead" line is a property of where the list was cut.

**(b) There is a dead token in the book.** `xNgLkoEHKxPhdo8Z3CANniWXsvcw6MuAeNyNg4aHoNn`,
held ~12.9 h on 2026-07-24, has **no DexScreener pair on any venue**. Two more —
`2Dcp8T…pump` (SFH) and `6mvct9…pump` (SHITTER) — were bought *before* graduation and never
graduated at all; SHITTER is dead, SFH is still sitting on its curve. Across all 21 mints the
wallet actually held for ≥60 s: **18 survive, 3 dead.**

**(c) The symbols in the ladder table are swapped.** `XkeTXo11…pump` is **DREGG**, not weave;
weave is `8PecVc…pump`. Mints, not symbols — the book contains two live tokens called
"nosis" (`FPfi9q1A…` at $57k liquidity and `emusQFua…` at $1.5k with a 489× volume/liquidity
ratio) and they are not the same asset.

---

## 2. The universe, and why this one

**U1 — every pump.fun token whose bonding curve completed and whose PumpSwap pool was created
in the window, enumerated from chain.**

Source: `getTransactions(type=CREATE_POOL)` on pump.fun's migration authority
`39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg`. One CREATE_POOL per graduation, carrying the
standardised deposit. **43,249 graduations, 2026-05-29 → 2026-08-14**, complete census, chain
time, 641 enhanced calls.

Why this and not something else:

- **Graduation is the chain event that makes a token LP-able.** Before it, the token is on a
  bonding curve and there is no pool to put a position into. Graduation is exactly the moment
  a token enters the set the operator could have chosen, and it is a hard, enumerable event
  rather than a judgement.
- **It contains the deaths.** A token that graduated at 09:00 and was worthless by 11:00 is in
  the frame. Nothing in the enumeration path ranks, sorts, or filters by activity — the
  pump.fun and DexScreener list endpoints all rank, and ranking is survivorship, so neither is
  used to build the frame. Both are used only to read outcomes off a frame chain already fixed.
- **It matches the operator's own venue.** 16 of the 24 mints the wallet touched are pump.fun
  mints; 14 of them graduated; all 5 mints the wallet opened a Meteora DLMM position in are
  pump.fun graduates.
- **It is matched on size by construction.** See §5 — this is the reason it beats every
  alternative on the confound the lane was asked to check.

**Why the census runs 76 days when the window is 27.** The operator does not buy fresh
graduates. Median token age at entry is **5.0 days**; the range is 5 minutes to 231 days. To
score a pick that was 55 days past graduation when it was bought, the control has to contain
tokens that are 55 days past graduation, so the census reaches back to 30 May.

### The alternative universes, and how much they change the answer

**U0 — every pump.fun launch.** From the tape's launch cohort frame, 913 launches in a
27-minute window on 2026-08-13, measured ~9 h later:

| | |
|---|---|
| completed the bonding curve | 24 / 913 = **2.6%** |
| has a real AMM pair now | 28 / 913 = **3.1%** |
| still sitting at (or under) the fixed $2,120 launch market cap | 810 / 913 = **88.7%** |
| traded at all in the last 6 h | 74 / 913 = **8.1%** |

Score the operator against U0 and 13-for-14 lands at p ≈ 10⁻²⁰. **That number is free and
means nothing**: it credits the filter with "I only bought tokens that had a pool", which is
a condition every LP on Solana satisfies by existing. This is what the lane brief meant by
the universe being the experiment, and it is why U0 is reported and not used.

**U2 — U1 restricted to graduates that had reached the same age the pick had at entry.** Not
a different frame, a different *conditioning*: the left-truncation correction. It is the
primary test, for the reason §4 gives.

**Not used: "all Meteora DLMM pools created in the window".** It is the venue-exact frame and
it was the first choice, but it cannot be enumerated without survivorship inside a sane
budget — the DLMM program's transaction stream is millions of transactions per day, its
`getProgramAccounts` surface is not affordable, and every listing API that covers it ranks by
liquidity or volume. Whereas the pump.fun migration authority carries **one clean transaction
per graduation**. This is a real substitution and it is stated: U1 is one step upstream of the
venue the operator actually LPs on.

---

## 3. What the population does

Measured on 14,760 of the 43,249 (34%) — 140 graduations sampled per day, seeded and
stratified by day, plus complete coverage of every graduation from 2026-08-10 on so the
early hours of the survival curve have tokens in them.

Status at one observation time, from the maximum-liquidity Solana pair on DexScreener.
**DEAD = no pair listed anywhere, or liquidity < $1,000, or 24 h volume < $100.**

Survival curve, each token contributing to exactly the one age bin its own age falls in:

| age since graduation | n | S(age) |
|---|---|---|
| 0.02 d (~30 min) | 41 | 0.659 |
| 0.25 d | 197 | 0.650 |
| 0.88 d | 185 | 0.822 |
| **1.25 d** | 573 | **0.412** |
| 1.75 d | 548 | 0.303 |
| 2.5 d | 1,065 | 0.176 |
| 3.5 d | 1,050 | 0.123 |
| 4.5 d | 328 | 0.098 |
| 8 d | 278 | 0.061 |
| 13.5 d | 425 | 0.035 |
| 21 d | 569 | 0.028 |
| 35 d | 846 | 0.018 |
| 50 d | 1,390 | 0.044 |
| 80 d | 935 | 0.041 |

**The cliff is at one day.** Through the first day the alive fraction sits in a noisy 64-82%
band; by 30 hours it is 41% and by 42 hours 30%. By two weeks the curve is flat at 2-4% and
stays there — everything that was going to die has died. This is the shape that makes the whole comparison turn on
*when* a token was bought, not *which*.

Population survival inside the operator's window, day-weighted to undo the deliberate
over-sampling of recent days: **9.3%**. Unweighted over the measured sample: 21.1%.

**Regime.** Graduations ran 1,482 in the first full census week and 7,044 in the week of
20 July — a **4.8× swing inside one census**, in exactly the direction PROGRAM.md §3.6 warns
about. The honest limit: **in a single cross-section, age and calendar are the same variable.**
S(60 d) can only be measured on the cohort that graduated 60 days ago. There is no split of
this data that observes an old cohort at a young age, so the confound cannot be tested here,
only bounded — §7 restricts the control to the operator's own window and re-runs.

**Instrument check (PROGRAM.md §3.8).** Observed time on the bonding curve: median **6.0
minutes**, p90 22.8 hours, max 870 days. Marino/Lillo put the median time-to-graduation at
4.4 minutes with a tail; this reproduces the order of magnitude *and* has the tail, so the
enumeration is not truncated.

---

## 4. The comparison

The operator's LP-relevant arm is the **14 pump.fun graduates the wallet held for ≥60 s** —
matched to U1 by construction. (Held, not routed: a mint that goes in and out inside one
transaction is a hop through someone else's pool, and 3 of the 24 touched mints are exactly
that.)

| mint | sym | age at entry | status now | liquidity | control null P(survive) |
|---|---|---|---|---|---|
| `XkeTXo11…` | DREGG | 20.6 d | alive | $55,777 | 1.000 |
| `Ge87Etsj…` | Jimothy | 5.8 d | alive | $534,016 | 0.381 |
| `HqhumkTH…` | Greenland | 28.2 d | **dead** | $3,310 / $44 vol | 1.000 |
| `5pVQnFwV…` | MATH | 1.2 d | dying | $4,722 | 0.100 |
| `GwyWFsDK…` | SOLVE | 5.9 d | alive | $14,750 | 0.383 |
| `2Cn914VF…` | Nick.exe | 55.3 d | alive | $16,373 | 1.000 |
| `GiRrLzda…` | SalaryCat | 1.6 d | alive | $19,371 | 0.128 |
| `DNhQZ1CE…` | ZAUTH | 230.4 d | alive | $134,966 | 1.000 |
| `8PecVcCG…` | weave | 7.2 d | alive | $29,942 | 0.899 |
| `7ZgRjHSn…` | apes | 0.03 d | alive | $14,068 | 0.413 |
| `AvecKFxn…` | COGE | 0.28 d | alive | $24,152 | 0.381 |
| `3hohWhrJ…` | Pawblo | 0.003 d | dying | $1,782 | 0.337 |
| `FPfi9q1A…` | nosis | 4.2 d | alive | $57,459 | 0.960 |
| `emusQFua…` | nosis (2nd) | 0.16 d | dying | $1,473 | 0.957 |

**Survival rates.** Operator 13/14 = **92.9%**. Population in the same window, day-weighted,
**9.3%**. Naively that is an enormous gap.

**The naive test.** Fisher's exact, one-sided, 13/14 against 1,628 survivors of 7,724 measured
in-window graduates: **p = 1.9 x 10⁻⁸**. This is the number the earlier write-up implies, and it is
wrong for one reason:

**Left truncation.** The operator did not buy graduates at graduation. They bought them at a
median age of 5 days, by which point 90% of the population is already dead — and a token that
is 5 days old has *already* survived the cliff. The honest null is not "what fraction of
graduates survive to today" but **"what fraction of graduates that reached age a go on to
reach age A"** — computable from the cross-section as S(A)/S(a) with no death times needed,
because death here is absorbing.

Each pick therefore gets its own null, so the null distribution of the survivor count is
**Poisson-binomial**, not binomial:

> **Expected survivors under the age-matched null: 8.93. Observed: 13. One-sided exact
> p = 0.0020.**

Bonferroni over the 6 pre-registered tests gives α = 0.0083, so the headline clears. Then
everything in §5 and §7 takes it back.

**Every null probability is the one-sided 95% upper Wilson limit on its bin, not the point
estimate.** A bin with zero survivors gives a point estimate of S = 0, and a null that
predicts certain death turns any survivor into infinite evidence — the study reported p = 0
off eighteen observations before this was fixed. The null is built from the strongest survival
the control data will support, so the arm has to beat the best case for chance.

**Effective n is 10, not 14.** Four picks (DREGG, Greenland, Nick.exe, ZAUTH) were bought so
far past graduation that the control null is ≈1.000: the population says they should have
survived. Three did and one — Greenland — did not, which is why it costs the arm so much.

**All six tests, since reporting only the smallest is the §3.9 failure:**

| test | p | BH | Bonferroni |
|---|---|---|---|
| dlmm (n=5) vs U1 unmatched | 4.2e-4 | 8.4e-4 | 0.0025 |
| dlmm vs U2 age-matched | 0.0325 | 0.0325 | 0.1951 |
| graduate (n=14) vs U1 unmatched | 1.9e-8 | 5.7e-8 | 1.1e-7 |
| **graduate vs U2 age-matched (primary)** | **0.0020** | 0.0030 | 0.0121 |
| touched (n=21) vs U1 unmatched | 5.0e-10 | 3.0e-9 | 3.0e-9 |
| touched vs U2 age-matched | 0.0032 | 0.0039 | 0.0194 |

The `top12` reconstruction is computed and reported but **excluded from the family**: it is a
selection-bias exhibit, not a hypothesis. Its age-matched p is 0.1599.

---

## 5. The confound check, which is where the result goes

### Size cannot be the confound inside U1, and that is measured

The brief's worry was that socially-connected projects might be systematically larger or
better funded, so that "the team is real" is a size effect any liquidity screen would catch.
**Inside U1 a size confound cannot operate**, because pump.fun graduation is a standardised
liquidity event: **96.2% of the 43,249 graduations deposit exactly 206,900,000 tokens** into
the new pool. Every token in the universe and every pump.fun pick in the arm starts its
post-curve life from the same inventory. This is the strongest argument for U1 as the frame
and it is a fact about the venue, not a modelling assumption.

(The SOL side of the deposit is *not* used: about 30% of migrations move native rather than
wrapped SOL, so it is not recoverable from parsed token transfers, and an average over the
recoverable 70% would be a selected subset. Stated rather than quietly averaged.)

**Time on the bonding curve**, the one genuine quality covariate observable before any outcome
exists, does not separate the arm either: picks median 33 minutes, universe median 6 minutes,
permutation test p = 0.74.

### The confound is seasoning, and a mechanical screen reproduces the record

What *does* separate the arm is when the tokens were bought. Run a screen that contains no
social information whatsoever — **"only buy graduates already at least X days old"** — over
the operator's own follow-up horizons:

| screen | expected survivors of 14 |
|---|---|
| no screen (buy at graduation) | 3.04 |
| ≥ 1 day old | 2.76 |
| ≥ 3 days old | 6.81 |
| ≥ 7 days old | 8.79 |
| **≥ 14 days old** | **12.64** |
| — | — |
| **the operator's actual record** | **13** |

A rule that reads no Telegram, meets no dev and forms no opinion about anybody's character
lands within a third of a token of the observed result. That is the finding the brief asked
for, and it is the most useful thing in this file.

### And so does a plain liquidity threshold

Move the liquidity floor for "dead" from $1,000 to $5,000 — a screen a bot could apply in one
line — and the separation disappears:

| dead below | population survival | arm | expected | p (age-matched) |
|---|---|---|---|---|
| $250 liq / $0 vol | 0.373 | 14/14 | 9.82 | 0.0020 |
| $1,000 liq / $100 vol | 0.211 | 13/14 | 8.93 | 0.0020 |
| $5,000 liq / $500 vol | 0.055 | 10/14 | 8.58 | **0.2299** |
| $10,000 liq / $1,000 vol | 0.035 | 10/14 | 8.59 | **0.2300** |

This sweep is doing double duty and it is worth being explicit about why. Because liquidity
decays and does not come back, S(A)/S(a) computed at threshold X is exactly
P(still above X at age A | above X at age a) — so **raising the threshold IS running the
control through a liquidity screen.** The operator entered pools with liquidity in the tens to
hundreds of thousands of dollars. At the threshold that matches what they actually bought
into, the picks and the screened population are the same.

**Answering the brief's question directly: yes. A simple liquidity threshold reproduces the
filter's performance.**

---

## 6. The power number

> **7.**

Against the age-matched null (mean survival probability across the arm's entry ages
p = 0.638), a *perfect* record needs **7 picks** to reach p ≤ 0.05, and **11** to reach
p ≤ 0.01. The arm has 14, so **the design is powered and this is a genuine null rather than an
unresolvable one** — which matters, because "we cannot tell yet" and "we looked and found
nothing that survives a threshold change" are different messages.

But 7 is not a constant. It is almost entirely set by **how seasoned the tokens are when they
are bought**, because that is what sets the null. Over a 21-day holding horizon:

| entry age | population P(survive 21 more days) | picks needed for a perfect record, α=0.05 | α=0.01 |
|---|---|---|---|
| at graduation | 0.046 | **1** | 2 |
| ≥ 6 h | 0.061 | 2 | 2 |
| ≥ 1 day | 0.071 | 2 | 2 |
| ≥ 3 days | 0.272 | 3 | 4 |
| ≥ 7 days | 0.430 | 4 | 6 |
| ≥ 14 days | 0.878 | **24** | 36 |
| ≥ 30 days | 1.000 | **never** | never |

This is the operational reading, and it inverts the intuition. **Buying fresh graduates makes
the claim cheap to prove and buying seasoned ones makes it nearly unprovable.** A perfect
record on tokens that are already a month past graduation can never be significant at any
length, because the control does not die either. If the operator wants the filter to be
testable, the picks have to be made where the population is still dying.

Against the *unmatched* base rate the answer is 2 picks — which is the trap: it is the number
that makes 12-for-12 look overwhelming, and it is wrong for exactly the reason §4 gives.

**Multiplicity.** 6 pre-registered tests, Bonferroni α = 0.0083, BH reported alongside. The
threshold sweep and the leave-one-out are sensitivity analyses on the primary, not additional
hypotheses, and are not counted.

---

## 7. Robustness, all of it

**Leave-one-out.** Dropping each pick in turn: best p = 7.9×10⁻⁵, **worst p = 0.0131** (drop
MATH), next worst 0.0116 (drop SalaryCat). So the result is not one token — but a single
omission puts it above the Bonferroni bar.

**Second instrument.** DexScreener delists inactive pairs, so "no market" is partly an
indexing policy. pump.fun's own `last_trade_timestamp` is an independent read with a different
failure mode, and needs no dollar threshold: **traded in the last 24 h**. On 3,366 universe
mints with both, the two agree **86.9%** of the time, and the disagreement is entirely
one-directional (440 dex-dead/pf-alive, **0** dex-alive/pf-dead) — DexScreener is strictly the
stricter instrument. Population survival: 12.8% by DexScreener, 19.4% by pump.fun; the arm
beats both.
Arm: **14/14 traded in the last 24 h.** The verdict does not depend on the instrument.

(Hand-checked before "no pair" was trusted as death, on twelve sampled graduates DexScreener
lists no pair for: eleven of twelve carried a pump.fun market cap under $2,000, the twelfth
$3,463, and their last recorded trades ran from two to nine days before observation. The
systematic version of that check is the cross-tab above.)

**Calendar restriction.** Restricting the control to graduations inside the operator's own
window (7,724 tokens, max age 27 d) drops the 3 picks whose entry age exceeds it and gives
11/11 observed against 5.87 expected, p = 6.1×10⁻⁵. So the result is *not* an artefact of
reaching back into the June regime — but this cut also removes Greenland, the only death, and
every pick whose null is ≈1. It should be read as "the direction holds", not as a stronger
result.

**Threshold sweep.** §5. This is the one that fails.

**Counting "dying" as a failure** (`--strict`, i.e. survival means still fully alive rather
than merely not dead): the arm goes 10/14 against 8.59 expected, **p = 0.2300**, with no
threshold argument needed at all. The operator's claim is about death, so the lenient reading
is the primary one — but under the stricter reading the two arms are simply the same, and the
verdict is INDISTINGUISHABLE either way.

**Both controls on the instrument itself.** `tests/test_control_arm.py` runs the whole
pipeline against 40 independent worlds where the picks are drawn from the same distribution as
the control (false-positive rate must stay near nominal) *and* against a world with a planted
perfect record at a resolvable n (which must be detected), per PROGRAM.md §3.12. The
known-zero control **failed on the first run — 34 of 40 null worlds fired** — and caught a
real bug: the survival curve was made monotone with a running minimum, which locks onto the
smallest noisy bin and never recovers, pushing a true S = 0.35 down to ≈0.20 and manufacturing
an edge for any arm compared against it. Replaced with weighted pool-adjacent-violators
isotonic regression, which is the maximum-likelihood fit under the monotonicity constraint.
Without the planted-effect control, an estimator that never fires would have passed the
zero-world test perfectly.

---

## 8. Assumptions, stated so they can be attacked

1. **Death is absorbing.** Nobody re-adds liquidity to a token that lost it, so a token
   observed alive at age A was alive at every age below A, and the alive fraction of an age-A
   cohort estimates S(A). This is what makes a cross-section usable without death times. If
   tokens routinely come back, the curve is wrong.
2. **Age and calendar are inseparable in one cross-section.** §3. The fix is a second census a
   month from now; two cross-sections identify what one cannot.
3. **Outcome is measured at one instant.** Every status is "as of 2026-08-14 04:00 UTC". A
   token that dies tomorrow is alive here.
4. **U1 is one step upstream of the operator's actual venue.** They LP on Meteora DLMM; the
   frame is pump.fun graduations. Justified in §2, but it is a substitution.
5. **The arm inclusion rule was fixed before outcomes were looked at**: pump.fun mint suffix,
   `complete == true`, held ≥60 s. Mechanical, so it cannot be tuned to drop an inconvenient
   token. Two nested alternatives (`dlmm`, `touched`) are reported alongside and neither
   changes the verdict.

---

## 9. What would make this measurable sooner

In order of how much they buy:

1. **Record the call before the outcome.** Everything above is retrospective and therefore
   contaminated by the operator's own attention — they kept trading the tokens that lived. A
   pre-registered list, written before the position, converts this from archaeology into an
   experiment. The list must include the **rejections**: tokens looked at and declined are the
   other half of the arm and there is currently no record of a single one.
2. **Log entry liquidity and token age at the moment of entry.** Both are one RPC call at
   position-open time, and together they collapse the two confounds this lane could only bound
   retrospectively. Without them, every future analysis has to reconstruct age from
   `pairCreatedAt` and cannot reconstruct entry liquidity at all.
3. **Buy where the population is still dying.** §6: the same record is worth 3 picks of
   evidence at a 3-day entry age and 24 at a 14-day entry age. If the operator wants the
   filter tested, the cheapest change is *when* they buy, not how many times.
4. **Re-run this census in a month.** `python studies/control_arm.py --collect` is
   incremental and costs about 3,000 credits for 30 more days. A second cross-section
   separates age from calendar, which one cannot.
5. **Report the "dying" tokens' trajectory rather than their level.** Four of the fourteen
   (MATH, Greenland, Pawblo, the second nosis) sit between $1.4k and $4.7k of liquidity, which
   is exactly where the threshold sweep does its damage — the whole verdict turns on four
   tokens sitting near a line. A liquidity time series off the tape would replace a knife-edge
   classification with a slope, and a slope does not move when the knife does.

---

## Reproduce

```
python studies/control_arm.py --collect     # network; caches under .cache/control_arm/
python studies/control_arm.py               # offline, deterministic given --seed
python studies/control_arm.py --json
python studies/control_arm.py --strict      # count "dying" as a failure
pytest tests/test_control_arm.py
```

Default seed 20260814. The seed controls only the stratified sampling of which graduations get
their outcome measured; every test statistic is exact rather than simulated, except the two
permutation tests in the confound block, which are seeded.

**Helius spend, from `.cache/control_arm/credits.json`:**

| stage | calls | credits |
|---|---|---|
| probes + operator wallet | 15 enhanced + 126 RPC | 276 |
| graduation census (first pass, 27 d) | 386 enhanced | 3,860 |
| graduation census (extension to 76 d) | 254 enhanced | 2,540 |
| incremental re-collect (idempotence check) | 1 enhanced | 10 |
| **total** | | **6,686** of a 25,000 cap |

DexScreener, the pump.fun frontend API and the tape frames are free and cost no credits.
