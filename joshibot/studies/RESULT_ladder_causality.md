# RESULT: the ladder is a graduation DETECTOR, not an engine — PICK, and MAKE is refuted

The last open edge candidate from `RESULT_cluster_map.md` §5: a committed **6-cluster / 34-wallet**
accumulation ladder (rungs at −4, 0, +8, +16, +24, +32 s) whose coins graduate above the 2.45%
base. `cluster_map.py` §14 left the reason **unresolved**: predict-vs-manufacture. This resolves it,
and — because *no committed study reports a graduation rate for the ladder's coins* — **measures
that rate here** with a matched control and a rotation null rather than inheriting it.

Code: `studies/ladder_causality.py` (reads cached `.cache/clustermap/` artifacts; regenerates
`.cache/ladder/`). Watchlist: `state/ladder/watchlist.jsonl`.

    uv run --group research python -m studies.ladder_causality --all

**Object under test (committed vs derived, kept distinct).** The causal treatment throughout is the
**committed 6-core spine** — `_assemble_ladder(CORE6)` reproduces its rungs *exactly* (−4, 0, +8,
+16, +24, +32 s; spacing [4,8,8,8,8]; 10 independent checks, **0 mismatches**; 34 wallets, 63,044
entries / 59 exits). Widening to all nonzero locked cluster-pairs, that spine sits inside a **derived**
component of **110 clusters / 479 wallets** on the same clock — but that is a *looser schedule
complex, not one clean ladder*: its embedding spans −6..+401 s with **38 mismatches over 185 checks**
and mixes 79 FLASH / 18 ACCUMULATOR / 8 HARVESTER / 4 SLOW. The 110 only defines *which wallets to
pull footprints for*; every causal claim below is anchored on the 6-core.

---

## 0. The one-paragraph answer

**PICK.** The ladder is a graduation *detector*, not a graduation *engine*. **MAKE (their capital
pushes coins over the line) is mechanically refuted**: graduation on pump.fun requires ~80% of a
coin's fixed supply to be *sold* into the bonding curve, and the ladder buys a median **0.44% of
supply on the coins that graduate** — *less* than on the coins that fail (1.29%), with the
non-selling core spine at **~0% median**. A capital engine cannot buy less on its successes, and
its dose-response on its own size is flat-to-inverse. **The measured graduation rate** of coins a
6-core wallet enters within 30 s is **30.6% (Wilson 95% CI [29.8%, 31.5%], n = 10,976)** — not the
brief's unverified "35–62%", *my* number from the corpus. **COINCIDENCE is real but partial**:
matching untouched coins on public early quality (birth-day × dev-buy × sniper-count × birth-legs)
lifts the base from 2.45% to **9.0%** — that much is "the ladder picks coins that look good early,
and those graduate more." **But a 3.4× residual survives the matched control** (treated 30.4% vs
matched-control 9.0%; per-day mean **3.40×**, 10-day range 2.74–4.04×, day-bootstrap 95% CI
**[3.19×, 3.61×]**), and a **rotation null** (reassign the picks within stratum) puts it at
**z ≈ 59, p < 1/1000**. And the natural experiment is decisive: among coins the ladder entered
early, its winners differ from its losers on **coin quality (5× the dev buy)**, not on the ladder's
own footprint — the PICK signature exactly. **The edge, if any, is graduation-timing** (be in before
migration), *conditionally* viable — see §6. The edge does **not** evaporate to base rate; it is
real, large, and selective.

---

## 1. The specimen — committed anchor, derived extension

`_assemble_ladder(CORE6)` rebuilds the **committed** object with no hand-tuning: clusters 1504,
6464, 4899, 17569, 16518, 13755 embed onto **−4, 0, +8, +16, +24, +32 s** (spacing [4,8,8,8,8],
10 independent checks, **0 mismatches**), 34 wallets, pure **ACCUMULATORS** — 63,044 entries /
**59 exits (0.09%)**. This is `RESULT_cluster_map.md` §5's ladder, reproduced.

**The 110/479 "organism" is a derived generalization, and I keep it honest.** Widening to the
largest connected component over *all* nonzero locked cluster-pairs (|median offset| > 1 s, IQR ≤
4 s, ≥ 50 shared coins) pulls in **110 clusters / 479 wallets** on the same clock — but its 1-D
embedding spans **−6..+401 s with 38 mismatches over 185 checks**, so it is a *looser schedule
complex, not one clean line*. By guild it is **79 FLASH / 18 ACCUMULATOR / 8 HARVESTER / 4 SLOW /
1 AFTERMARKET**: a non-selling spine (the 6 core + accumulator guild, exit-ratio < 1%) synchronized
with a **selling FLASH periphery** (exit-ratio 87%). This matters for the exit question (§6): the
part that *can* be exit liquidity is the FLASH periphery; the spine only buys. All causal tests
below use the committed 6-core as the treatment; the 110 only scopes which wallets get footprints.

**The funding hub** `H7sWT7…` has pushed **27,846 SOL over 4,286 transfers to 579 wallets since
2024-02**, and its fan-out lands on **13 organism clusters including all 6 spine clusters** — a
second, blind confirmation of the same object (`report_fanout.py`). It funded **441 wallets in
Oct–Nov 2024** and **48 fresh wallets this month**, 17 of which already map to the core spine: the
spine is being actively reinforced.

---

## 2. MAKE is refuted at the mechanism (Test A)

pump.fun graduation = ~80% of the fixed 1e9 supply sold into the curve. The ladder's purchased
**%supply** is the direct MAKE currency (the corpus has no SOL leg, but %-of-supply is the *right*
unit here — graduation is a supply-sold event). Among the **53,002 coins the ladder entered**:

| | n | median ladder %supply | p90 | median core-spine %supply |
|---|---|---|---|---|
| failed | 46,805 | **1.287%** | 27.07% | 0.000% |
| **graduated** | 6,197 | **0.436%** | 24.09% | **0.000%** |

The ladder buys **less** supply on the coins it graduates, and its spine's median contribution is
**zero**. Buying < 0.5% of supply cannot push an 80%-of-supply threshold. And the **dose-response on
their own size is non-monotone and inverse at the top**: the highest ladder-%supply deciles (where
the ladder is the *dominant* buyer, 19–27% of supply) graduate at **2.5–3.9%**, *below* the touched
average — because a high own-share means "nobody else came," not "we manufactured a winner."

**Why does supply run inverse?** On a coin with real organic demand the curve price rises fast, so a
fixed clip buys *fewer* tokens (lower %supply); on a dead coin the ladder is a big fish in an empty
pond. Supply-share is a demand *thermometer*, not a demand *cause*.

---

## 3. The `n_rungs` gradient is not (only) survivorship (Test B)

`n_rungs` rises monotonically with graduation, but the derived complex's later rungs (its embedding
reaches +401 s) can only fill if the coin is still alive, so raw `n_rungs` is partly `n_rungs ←
survival → graduation` (reverse causation). Decomposed on rungs filled in the **first 30 s** (fixed,
pre-outcome window):

| core+periphery rungs ≤30 s | n | grad | median lifetime |
|---|---|---|---|
| 0 | 219,254 | 0.6% | 59 s |
| 1 | 25,657 | 5.0% | 407 s |
| 2–3 | 15,773 | 11.6% | 792 s |
| 4–7 | 6,109 | 32.6% | 1,941 s |

Survival is clearly coupled. **But the signal survives a survivorship control**: among coins that
lived **> 600 s**, graduation still climbs **1.8% → 9.7% → 30.4% → 34.9%** with core rungs in the
first 30 s. Early presence carries real signal beyond "the coin didn't die."

---

## 4. COINCIDENCE subtracted, PICK confirmed (Tests C, E)

**Treatment** = a known **6-core-spine wallet buys within 30 s** — chosen because it is (a) decided
before the outcome and (b) exactly what the firehose can see live. n = 10,976 coins.

**The measured graduation rate (mine, not inherited): 30.6%, Wilson 95% CI [29.8%, 31.5%].**

**Matched control (the COINCIDENCE killer).** Match every treated coin to untouched coins in the
same **birth-day × dev-buy × sniper-count × birth-legs** stratum:

- matched-control (untouched, same strata): **9.04%** — this is the COINCIDENCE component: public
  early quality alone lifts 2.45% → 9.0%.
- treated (same strata): **30.42%**
- **residual lift = 3.37×**, i.e. the ladder's pick predicts graduation *beyond* everything a
  bystander can already read off the coin at birth.

**Temporally robust** — the lift is not a one-day artifact:

| day | n_treat | treated | matched-control | lift |
|---|---|---|---|---|
| 08-05 | 1,113 | 29.8% | 8.7% | 3.41× |
| 08-07 | 891 | 37.0% | 13.5% | 2.74× |
| 08-10 | 1,074 | 37.0% | 10.3% | 3.59× |
| 08-13 | 1,068 | 27.6% | 6.8% | 4.04× |
| 08-14 | 1,423 | 23.3% | 7.2% | 3.22× |

All ten days: mean **3.40×**, range **2.74–4.04×**, **day-bootstrap 95% CI [3.19×, 3.61×]**.

**Rotation null** (reassign the ladder's picks at random *within* each stratum, 1,000 draws — holds
the matched features and the pick count fixed, destroys only *which* coin it chose): observed
within-stratum treated graduation **30.65%** vs null **16.55% ± 0.24%**, **z ≈ 59, p < 1/1000**. The
pick is the ladder, not the features.

*Entity discipline (PROGRAM.md §3, the burst-ESS trap):* the ladder is **one** bursty entity, so the
trial unit is the **coin**, not the wallet-entry; the attribution null is the rotation / matched
control, and the uncertainty on the lift is the **ten-day replication**, never a naive t over 53k
correlated coins (which would be off by orders of magnitude). The Wilson CI applies only to the
rate itself (each coin its own Bernoulli); the *causal* uncertainty is the day-bootstrap.

---

## 5. The natural experiment (Test D)

Among coins the ladder entered early (core rung ≤ 30 s), **what separates its winners from its
losers?**

| | n | median dev-buy share | median snipers | median core rungs ≤30 s | **median ladder %supply** |
|---|---|---|---|---|---|
| failed | 7,612 | 0.039 | 3 | 1 | **0.592** |
| **graduated** | 3,364 | **0.207** | 4 | 3 | **0.219** |

Winners carry **~5× the dev buy** and the ladder's own supply is **lower** on them. The organism's
successes are separated from its failures by the **coin**, not by the ladder's capital — MAKE would
predict the opposite. (Winners do get more *early rungs*: consistent with the ladder committing
harder on coins it is more confident about — graded PICK — rather than manufacturing the outcome.)

**Necessary? Sufficient?** Neither. Coins graduate **without** the ladder (matched controls do so at
9%; population graduations far exceed the ladder's touched set), and the ladder enters **7,612 coins
that fail** for every 3,364 it rides to graduation. A factor that is neither necessary nor sufficient
and whose dose runs *inverse* is not making the outcome. **MAKE is dead; PICK stands.**

*The one hypothesis this cannot fully exclude* is weak **signal-MAKE** (the visible entry herds
organic buyers). It is observationally near-identical to PICK offline, and — importantly — **it
collapses to the same trade**: copy the pick, exit at migration. So the edge conclusion is
unaffected.

---

## 6. Front-run viability

**Detection is early and clean.** The first core-spine rung lands at **median +6 s** (p25 +5 s, p90
+34 s); **73% within 10 s, 85% within 30 s, 99% within 60 s**. The firehose already sees the create
and the first buys, so a *known spine wallet buying a < 10 s-old mint* is the live trigger — exactly
the +5 s cadence the organism fired on nosis.

**Fresh soldiers are pre-announced.** Every hub→wallet funding transfer **precedes** that wallet's
first trade (mechanical — gas must land first): median lead **3.1 h**, p25 **0.5 h**. So the desk
learns a new soldier *exists* hours before it fires, and can add it to the subscription in advance.
48 such wallets were funded this month.

**Paper-sim (honest boundary).** Enter at first core rung ≤ 30 s, exit at migration. Treated
graduation **30.6%**; graduated coins reach a median **411 SOL** peak mcap vs **67.6 SOL** for
failures. The **breakeven grad-exit multiple is 3.26×** at zero dead-coin recovery:

| grad-exit multiple | dead-coin recovery | EV / trade |
|---|---|---|
| 3× | 0% | −8.1% |
| 5× | 10% | +60.2% |
| 8× | 20% | +159.1% |

The corpus has no SOL leg and no curve price at +30 s, so the actual +6 s→migration multiple and
the real friction (priority fee, slippage into a moving curve, MEV) are **not measured here** — this
is a viability gate, not a backtested PnL. Given entry at +6 s and a ~411 SOL migration ceiling the
multiple is *plausibly* above breakeven, but that is the live-validation question, not a claim.

**The honest ceiling on all of §4–6: it is IN-SAMPLE.** The clusters were built from this same
corpus, so "the ladder's pick predicts" is not yet an out-of-sample edge. The mitigation is that the
deployable object is a **fixed wallet set**, not a re-clustering: the spine identities are known,
funded, and persistent, and the per-day stability + the funding-hub confirmation mean a forward run
*watching those exact wallets* is a clean prospective test. That forward run is the gate
`RESULT_cluster_map.md` §14 already left open.

---

## 7. The watchlist — the contract for the firehose

`state/ladder/watchlist.jsonl`, **66 rows**, emitted by `--watchlist`:

- the **funding hub** `H7sWT7…` (subscribe to catch the next soldier being funded);
- the **48 wallets it funded this month** — 17 already mapping to the core spine, 16 to the wider
  organism, 15 brand-new unmapped — each with its **funding transaction signature** as on-chain
  evidence;
- the **full 6-core spine** (34 wallets), the never-selling accumulators.

Each row carries `wallet`, `role`, `cid`, `funding_tx`, `first_fund_ts`, `total_sol_from_hub`, and a
prose `evidence` string. **Contract:** subscribe `accountTrade` on every `wallet`; a buy on a
< 10 s-old mint is a live ladder entry; `funding_tx` proves the wallet is one soldier. This module
**does not wire the firehose** — it defines the object the desk subscribes to.

---

## 8. Limits

- **In-sample.** Clusters built from the 2026-08-05..14 corpus; every rate inherits it. The fixed
  wallet set is the deployable, out-of-sample-testable object; the forward run is not done here.
- **No SOL leg.** "%supply" is fraction of the fixed 1e9 token supply — the correct unit for the
  graduation-threshold argument, but not a capital figure. The paper-sim multiple is therefore a
  breakeven analysis, not a PnL.
- **One entity.** The organism is one actor; coin-grain counts are a census of its decisions, not
  independent draws. Inference is the matched-control / permutation null and the ten-day replication.
- **Signal-MAKE is not fully excluded** (§5), only shown to imply the same trade as PICK.
- **The "organism" is a schedule complex, not a single wallet-linked entity** (§1): a non-selling
  spine plus a selling FLASH periphery on one clock. The causal claims here are about the **spine's
  early entry** as a treatment; the periphery is characterized but not the front-run trigger.
