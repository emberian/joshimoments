# RESULT: the policy search is a NULL, and the reason is that we cannot see the exit

2026-08-14. `studies/bandit_search.py` over `state/boards/` — 9.99 h of pump.fun board
membership at 30 s, 77,623 rows, 35,808 board entries, 8,879 mints in view.

The ask was a search for the program that decides **when to enter, when to exit, and how
much**, with bandits. All three were searched. The honest answer on this tape is:

- **SIZE is solved and degenerate.** B* = sqrt(priority x Y) is essentially never capped and
  the friction U around it is shallow. There is nothing to search.
- **ENTER is a null.** 1,944 configurations, and the winner does not clear the floor that
  the *same search on a permuted world* manufactures out of nothing (p = 0.455 on the mean).
- **EXIT is the only decision with structure**, and the structure is not about patience. It
  is about **whether the exit produces a fill at all**. Rules that trigger on a live quote
  beat rules that wait for a clock, by a wide margin — and the margin is still inside
  plausible fill slippage, so it is a lead, not an edge.

And one finding that reaches back and corrects `RESULT_board_entry.md`.

---

## 0. Which off-policy method, and why

**The board tape has no propensities.** We recorded what pump.fun's boards did; we never took
an action under a logged behaviour policy. `shitcoims_replay/ope.py` is therefore
**inapplicable** — its own `LoggedDecision.__post_init__` refuses a missing propensity for
exactly this reason. An IPS or SNIPS number over this tape would be a fabricated denominator,
which is the same class of error as `engine.py:770` stamping a cost basis from the exit quote.
**No importance weight is computed anywhere in this study.**

The choice was **(c) both**, with a clear primary:

**PRIMARY — (b) the tape as a simulator.** Entries replay in time order; a policy picks; the
tape supplies the path that resolves the position. Evaluation is then *on-policy inside the
simulator*, so no reweighting is needed at all — the bandit's propensities exist by
construction but are never used as weights, because the realised reward is observed directly.
The bias budget is **simulator fidelity**, and it is enumerated in the module docstring rather
than hidden. A gift of this design: the simulator gives **full-information counterfactuals**
(every arm's reward is computable at every round), so cumulative regret and the best fixed arm
in hindsight are **exact**, not estimated. The learners are still fed only the chosen arm's
reward.

**CROSS-CHECK — (a) direct method.** A ridge reward model fitted on the training window scores
the same entry predicates.

**Where they disagree, and what it means.** Out-of-sample R² of the reward model on the test
window is **+0.0012** — indistinguishable from zero — and the Spearman correlation between the
direct method's ranking of entry predicates and the simulator's is **rho = −0.130 (p = 0.35)**.
The two methods **disagree on the ordering while agreeing on the conclusion**. That is the
diagnostic the design was built to surface: an ordering that a reward model fitted on the same
features cannot reproduce is an ordering made of noise, and it says the same thing the trials
accounting says, from the other direction.

---

## 1. The finding that corrects the previous study

`RESULT_board_entry.md` reports a shallow-drawdown 8 h median of **+21.77%** with 67% up, and
notes 96% censoring as a caveat that "strengthens the finding". It does not. **The censored 96%
were dropped, so that number is computed on survivors.**

This study never drops a censored position. It **marks out** at the last price observed *at or
before* the exit trigger — never after, so no look-ahead — and reports a haircut band on that
stale price. The result, on the identical cohort:

| shallow drawdown (<50% off ATH), NET of friction | mean | median | p(win) | live fills | mean over live fills only |
|---|---|---|---|---|---|
| hold 30 min | −2.34% | −2.26% | 32% | 43% | **+12.05%** |
| hold 1 h | −4.67% | −2.34% | 34% | 37% | +15.16% |
| hold 2 h | −8.32% | −2.39% | 33% | 32% | +14.82% |
| hold 4 h | −7.55% | −2.43% | 31% | 23% | +26.56% |
| hold 6 h | −7.48% | −2.43% | 33% | 21% | +27.59% |
| hold 8 h | **−12.24%** | −2.48% | 28% | 20% | **+25.01%** |

n = 3,376 entries on 1,234 mints; 0% haircut (the optimistic end); threshold dd < 0.50.

**Read the two rightmost columns together.** Among positions that got a real quote at the exit,
longer is better — +12% at 30 min rising to +27% at 6 h, which is the horizon effect the earlier
study found. But the share of positions that get a real quote falls from 43% to 20% over the same
range, and once the other 80% are priced instead of discarded, **the mean goes the other way**.
The horizon effect and the censoring rate are the same phenomenon measured twice.

So the operator's instruction — "if your search says minutes beat hours, that is a finding worth
reporting loudly" — is triggered. **The search says exactly that, and the mechanism is that the
8-hour result was a survivorship artifact.** The +21.77% is what you earn on the coins you can
still see at hour eight. There are one in five of them, they are the ones that did not collapse,
and you cannot know in advance which they are.

---

## 2. What actually happened to positions

Across 19,380 entries x 18 exit rules, priced by how each position ended:

| resolution | share | median gross | mean gross |
|---|---|---|---|
| reached the horizon with a live quote | 20.5% | 1.010 | 1.108 |
| an exit rule fired on a live quote | 23.6% | 0.826 | 1.018 |
| mark-out: blacked out at the exit, seen again later | 18.2% | 0.997 | 0.979 |
| mark-out: left the boards for good | 16.8% | 0.932 | 0.868 |
| mark-out: no quote at all inside the horizon | 20.9% | 1.000 | 1.000 |

**55.9% of position-resolutions are stale-price mark-outs**, at a median gross of 1.000. Coins do
not visibly collapse on the way out of view — they leave near where they came in. That is why the
haircut is a **belief about the unobserved rest of the path** and not something this tape can
settle, and why every headline here is paired with a **breakeven haircut**: the discount at which
the rule's net return crosses zero.

---

## 3. ENTER: the grid search is a null

**Design.** 108 entry predicates (4 drawdown thresholds x 3 boards x 3 pool floors x 3 market-cap
floors) x 18 exit rules = **1,944 configurations**; 1,458 cleared the 200-entry floor and were
scored. Temporal split at 2/3 of the cohort (PROGRAM.md §3.1), entity-grouped: **every mint seen in
train is deleted from test** (§3.2), which costs 3,637 test entries and leaves 2,844 on 1,530
mints. Selection happens on train only; the test window is looked at once.

**Trials accounting (§3.9).**

| | |
|---|---|
| configurations defined by construction | 1,944 |
| configurations scored | 1,458 |
| effective independent trials (95%-variance PCA over the trial return streams) | **53** |
| cross-trial Sharpe dispersion | 0.0788 |
| analytic E[max SR \| no skill, N=1,458] (Bailey/López de Prado) | 0.2647 |
| best in-sample Sharpe | 0.1349 |

The nested grid is nowhere near 1,944 independent bets, so the raw Bonferroni/DSR count is far too
harsh and the PCA count is reported beside it. But neither is the real test. The real test is to
**rerun the entire 1,458-cell search on worlds where the features cannot predict the outcome** —
outcome rows permuted within 20 time blocks, preserving the marginal outcome distribution and the
correlation across exit rules, destroying only the feature-to-outcome link:

| permutation floor, 10 known-zero worlds | median of best | max of best | real | p |
|---|---|---|---|---|
| best cell's **mean net return** | +5.99% | +17.34% | **+6.93%** | **0.455** |
| best cell's **Sharpe** | 0.0651 | 0.1078 | **0.1349** | **0.091** |

**A search this size manufactures a +6% winner out of pure noise about half the time.** The
in-sample winner does not clear the measured floor. The analytic haircut and the measurement
disagree by roughly 2x; the measurement wins, because it is the same estimator on the same data
with the signal removed.

**The one look at the test window confirms it.** The train winner
(`dd<0.30, board=last_trade_timestamp, sol>=30, mc>=$100k | +100%/−50% bracket`) takes 140 test
entries on **26 mints** and returns +6.48% mean against the baseline's −17.81%. Paired on the
entries both take, the difference is **+18.30% (mint-clustered SE 9.90%, t = 1.85, p = 0.065 raw,
p = 0.971 after Šidák on N_eff = 53)**. Twenty-six mints is not a sample; the raw p does not
survive the search that produced it.

**The null result is the result: no searched entry predicate beats the simple rule on evidence
this tape can supply.**

---

## 4. EXIT: the only decision with structure — and it is not patience

Per-arm value if the arm were played on every one of the 19,380 entries, mint-clustered t:

| exit rule | cum (unit stake) | %/round | t | live fills | breakeven haircut |
|---|---|---|---|---|---|
| SKIP | 0.00 | 0.000% | — | — | — |
| hold 30 m | −553.16 | −2.854% | **−2.83** | 35% | never |
| hold 2 h | −1182.99 | −6.104% | **−3.13** | 27% | never |
| hold 4 h | −1700.71 | −8.776% | **−4.91** | 22% | never |
| trailing 25% | −463.54 | −2.392% | **−2.07** | 50% | never |
| **+12% / −30%** (the operator's own trade) | +30.18 | +0.156% | 0.24 | **60%** | 0.4% |
| **+30% / −30%** | **+97.73** | **+0.504%** | 0.56 | 56% | 1.2% |

Two things are significant here and they are both **negative**: every clock-based hold loses
money with t between −2.8 and −4.9, and it loses more the longer it waits. Nothing is
significantly positive. The two bracket rules are the only arms that beat doing nothing, and
neither is distinguishable from zero (t = 0.24 and 0.56).

**The mechanism is legible in the `live fills` column.** A bracket converts a position into a
realised fill *while the coin is still visible* — 56–60% of the time, against 22% for a 4-hour
hold. A clock exit mostly arrives to find nothing to sell into.

**And the margin is inside the fill assumption.** Charging an adverse slip on every triggered exit
(simulator assumption #2 priced — a real desk sees the trigger a poll late and crosses a spread):

| exit rule | slip 0% | slip 1% | slip 2% | slip 5% |
|---|---|---|---|---|
| hold 4 h | −8.776% | −8.776% | −8.776% | −8.776% |
| trailing 25% | −2.392% | −2.727% | −3.062% | −4.066% |
| +12% / −30% | +0.156% | **−0.333%** | −0.822% | −2.288% |
| +30% / −30% | +0.504% | +0.088% | **−0.328%** | −1.577% |

Holds are unaffected because nothing triggers them. **The entire bracket advantage is consumed by
1–2% of adverse fill**, and the breakeven haircuts (0.4% and 1.2%) say the same thing from the
censoring side. The right sentence is: *brackets are the only exit family that is not clearly
losing, and their advantage is the same size as the frictions we have not measured.*

The operator's own rule — hold something you are prepared to sit on at −30%, take the exit near
+12% — is the best-behaved rule in the entire 18-rule grid on the criteria that matter (highest
live-fill rate, positive breakeven haircut, positive mean at both 4 h and 8 h). It does not clear
significance. It also does not need to be replaced.

---

## 5. SIZE: solved, degenerate, and worth saying so

Five configurations, B* = sqrt(priority x Y) at the **measured** 35,000-lamport priority fee:

| size | median clip (SOL) | median round-trip friction | capped by rho<=2% or bankroll |
|---|---|---|---|
| 0.25x B* | 0.0133 | 2.56% | 0.5% |
| 0.5x B* | 0.0265 | 2.33% | 0.5% |
| **1x B*** | **0.0530** | **2.26%** | 0.5% |
| 2x B* | 0.1060 | 2.33% | 42.7% |
| 4x B* | 0.2121 | 2.56% | 74.4% |

The U is real and it is shallow: ±2x off the optimum costs about 0.07 pp of round trip; the
pool-impact and bankroll caps bind on 0.5% of entries at B* and only start biting at 2x. **The
sizing decision has no leverage on this tape.** It is fixed at B* everywhere else in the study,
and every return in this document is net of the friction that sizing produces.

---

## 6. BANDITS: the win exists only with feedback a live desk cannot have

Contextual, 7 arms (SKIP + 6 exit rules), 15 standardised entry features, 19,380 rounds in time
order. Regret is exact because the simulator gives full counterfactuals.

| algorithm | cum NET | mean/round | regret vs best fixed | % skip | seed spread | shuffled context | feedback received |
|---|---|---|---|---|---|---|---|
| always SKIP | 0.00 | 0.000% | +97.73 | 100% | | | |
| best fixed arm (+30%/−30%) | 97.73 | 0.504% | 0.00 | 0% | | | |
| epsilon-greedy (eps=0.10) | 42.50 | 0.219% | +55.23 | 49% | −24.7 .. 165.3 | −200.64 | |
| **LinUCB (alpha=0.50)** | **157.33** | 0.812% | **−59.59** | 46% | deterministic | −126.25 | |
| LinTS (v=0.10) | 165.26 | 0.853% | −67.52 | 60% | 46.4 .. 272.3 | −23.80 | |
| LinUCB, **delayed feedback** | **−1567.30** | −8.087% | +1665.03 | 0% | deterministic | −1567.57 | **41%** |
| LinTS, **delayed feedback** | −698.53 | −3.604% | +796.27 | 27% | −848.4 .. −594.6 | −646.75 | 66% |
| per-context ORACLE | 5465.44 | 28.201% | −5367.70 | — | | | |

Three readings, in order of how much they matter:

1. **Delayed feedback destroys the result.** A 4-hour hold teaches nothing for four hours. With
   that enforced, LinUCB never learns — it receives feedback on only **41%** of its own decisions
   before the tape ends, spends the whole window in optimistic exploration, and loses 1,567 units.
   Its shuffled-context twin scores −1567.57, i.e. **identical**: with realistic delay the context
   contributes literally nothing. **The undelayed rows are the ones a live desk cannot reproduce**,
   and they are the only rows that win.
2. **Seed spread swallows two of the three algorithms.** eps-greedy's [−24.7, 165.3] and LinTS's
   [46.4, 272.3] both straddle the best fixed arm's 97.73. Their "win" is a draw of the RNG.
   LinUCB is deterministic so it has no spread — which is not evidence of stability, just the
   absence of the test.
3. **The context does carry something, undelayed.** LinUCB scores +157.33 with real features and
   −126.25 with the feature rows permuted; on a fully permuted-outcome world it scores −73.36. So
   the contextual signal is worth roughly 280 units *when feedback is instantaneous* — and zero
   when it is not.

**The oracle bound is the useful number for planning.** A policy that picked each arm knowing that
entry's realised path would earn 28.2% per round. Everything achievable sits between 0.5% (best
fixed arm) and that. The gap is what better context could in principle buy, and no learner here
recovered more than 0.3 pp of it.

**The real conclusion about bandits on this tape:** a 10-hour tape cannot support online learning
of an hours-scale policy, because the decision horizon is a third of the data horizon. This is a
statement about the dataset, not about bandits. Bandits are the right tool the moment the tape is
long enough — or the moment the desk starts logging its own propensities, at which point
`shitcoims_replay/ope.py` becomes applicable and this whole methodological problem dissolves.

---

## 7. Capital is the binding constraint, not signal

Portfolio replay in time order, B* clips, one position per mint, over 6.0 h of entries:

| policy | 1 SOL bank | 5 SOL bank | 25 SOL bank | trades @1 / @25 |
|---|---|---|---|---|
| dd<0.50, hold 4 h (the simple rule) | −60.0% | −23.4% | −22.1% | 46 / 1,200 |
| dd<0.50, +12%/−30% | −13.1% | −1.6% | **+3.2%** | 93 / 2,427 |
| dd<0.50, +30%/−30% | −22.9% | +3.3% | **+9.3%** | 87 / 2,136 |
| dd<0.50, hold 30 m | −38.0% | +7.2% | −7.4% | 280 / 4,251 |
| grid winner | −0.4% | −6.8% | −1.6% | 63 / 265 |

**Read the trade count before the percentage.** At 1 SOL and B* ≈ 0.053 SOL the book holds ~19
positions; a 4-hour hold spends the entire window full and refuses **9,058 of 9,849** signals. Those
rows are an arbitrary 0.5% subsample of the policy, not a measurement of it — which is why the
1 SOL column is close to meaningless and is reported only to show that it is.

The structural point survives the noise: **at the operator's actual bankroll, a rule that recycles
capital dominates a rule that picks better.** That is a fact about the account, not about the
market, and it is the strongest argument in this document for short-tolerance bracket exits over
long patient holds — stronger than any of the return numbers, because it does not depend on the
haircut.

---

## 8. Both controls (§3.12)

A green zero-control certifies a broken estimator exactly as readily as a working one, so both
directions were run.

**Known-zero.** The permutation floor in §3 (10 worlds, full 1,458-cell re-search). LinUCB on a
permuted world scores **−73.36** over 12,899 rounds against a best fixed arm of 0.00 — it does not
manufacture a win.

**Known-effect, twice**, because the grid and the bandit can see different things and a control an
estimator is structurally incapable of passing tests nothing:

- *+8% planted on market cap ≥ $100k*, which **is** one of the grid's four axes. The grid's best
  cell rises from +6.93% to +14.93% and **20 of the top 20 cells carry the `mc>=100000` predicate**
  against a chance rate of 6.7/20. **RECOVERED.**
- *+8% planted on `reply_count` parity*, an arbitrary bit handed to the learner as a context
  feature. LinUCB earns **+7.76% on carrier entries vs −1.00% off-carrier**, and skips **9%** of
  carrier entries against **45%** off-carrier. **SEPARATED.**

The instrument detects an effect of the size we are hunting. The null in §3 is therefore a
measurement, not a broken pipeline.

---

## 9. Caveats, and which ones are fatal

- **One 9.99-hour window, one regime.** The temporal split is *in-window* and therefore weak in
  exactly the way §3.1 warns about: train and test share a session, a SOL price and a news cycle.
  It cannot detect regime dependence. This is the single largest hole and only a second day of
  tape closes it.
- **The haircut is a belief, not a measurement.** 55.9% of resolutions are stale-price mark-outs.
  Every primary number is quoted at the *optimistic* 0% haircut with a breakeven attached; at a 10%
  haircut the shallow-drawdown 4 h baseline goes from −17.81% to −25.96% and the grid winner from
  +6.48% to −0.66%. **Nothing that is even weakly positive survives a haircut above 1.2%** — the
  two bracket arms break even at 0.4% and 1.2% over the full cohort (2.7% at the 8 h horizon), and
  the grid winner's 9.1% belongs to a policy that is inside the permutation floor anyway.
- **Fills come from a 30 s poll.** A triggered exit books the observed poll price. Section 4 prices
  that assumption and the bracket advantage does not survive 2% of it.
- **No stop can fire in the dark.** While a coin is out of view the simulator cannot trigger a
  rule, which flatters every stop.
- **The test cohort is small after entity grouping** — 2,844 entries, and the selected policy takes
  140 of them on 26 mints. Nothing selected by this search should be sized on.
- **Market cap is price.** Supply is fixed on pump.fun, so this one is nearly free.

---

## 10. What this means for the desk

1. **Do not implement the grid winner.** It is inside the permutation floor and dies on the test
   set. Reporting it as a strategy would be the trials-accounting failure §4.1 exists to prevent.
2. **The simple rule is not the strategy either.** "Enter every shallow-drawdown board entry and
   hold 8 h" loses **−12.24%** net per entry once the 80% you cannot see at hour eight are priced
   rather than dropped, with t = −2.97. The prompt's fallback — "if nothing beats the simple rule,
   the simple rule is the strategy" — does not apply, because the simple rule is itself
   significantly negative.
3. **What is left standing is the operator's own rule**, for a reason the search made explicit and
   nobody had articulated: a bracket exit is the only kind that reliably produces a fill while the
   coin is still quotable. It is not statistically significant, and it dies at 1–2% adverse fill.
   It is the best available prior and it should be treated as a prior, not as an edge.
4. **The highest-value next action is not more search, it is instrumentation.** Three of the four
   binding uncertainties here — the haircut, the fill slip, and the feedback delay — vanish the
   moment the desk logs its own decisions with propensities and quotes its own exits. At that point
   IPS/SNIPS/DR in `shitcoims_replay/ope.py` become legitimately applicable and none of the
   simulator-fidelity apology in §0 is needed.

## Next

1. A second day of tape, for a real held-out temporal split.
2. Quote the exit from Jupiter rather than from board membership, which converts the haircut from a
   belief into a measurement and removes the study's largest source of uncertainty at a stroke.
3. Run the desk in shadow with `shitcoims_scalper/policy.py`'s logged propensities over board
   entries, so the next version of this study is a real OPE and not a simulator.
4. Model board exit as a competing risk rather than as a mark-out — `studies/flow_signals.py` has
   the survival machinery, and it would replace the haircut band with an estimated distribution.

## Reproduce

```
python3 studies/bandit_search.py                 # ~2 min: full study, both controls, 10 permutations
python3 studies/bandit_search.py --skip-worlds   # ~10 s: search + bandits only
python3 studies/bandit_search.py --bankroll-sol 5 --n-perm 50
```
