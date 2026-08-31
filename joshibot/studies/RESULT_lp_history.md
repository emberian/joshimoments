# The LP book, reconstructed from chain

Wallet `Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ` ("tha fund"), 2026-07-18 → 2026-08-14.
579 transactions, all pulled and cached; tooling in `scripts/lp/`.

Read-only throughout. No signing, no spending.

---

## The headline correction: this is not a $2k book

I had been reasoning about "tha fund" as ~$2,055 of LP capital against ~$1,950 of near-term
obligations — i.e. a book roughly equal to its liabilities. That framing is wrong.

| | |
|---|---|
| window | 27 days, 579 transactions |
| SOL transferred **in** | 31.3 SOL, 22 transfers |
| SOL transferred **out** | 152.3 SOL, 54 transfers |
| sweep destination | `HZREgM3BeTdu…` takes the large outbound flow |
| balance now | 0.28 SOL + ~$2,055 in 2 open positions |

The wallet starts the window at **zero** and ends near zero. It is an **operating account** that
cycles capital and sweeps proceeds elsewhere, not a static book. The $2,055 currently on it is
working capital mid-deployment, and it is not the measure of the operation.

**Consequence for planning:** the earlier "the LP book is approximately the liability, on a
deadline" reasoning does not hold, because the book is not where the value accumulates.

---

## 42 positions, 40 closed

Identified by account creation — a DLMM position is *created* with ~0.057 SOL of rent, which
distinguishes it from the pool, which already exists. (A first attempt keyed on instruction
account index caught pools too; the rent-creation signature is the clean discriminator.)

This independently corroborates the 39-closed-position figure measured in a parallel session.

Two distinct campaigns, and the tempo change between them is the most striking single fact:

| campaign | positions | typical hold |
|---|---|---|
| 2026-07-18 → 07-28 | 19 | tens of hours (5h, 18h, 32h, 45h, 99h) |
| 2026-08-11 → 08-13 | 23 | a few hours (0.1h, 0.8h, 1.2h, 3.6h, 6h) |

Holding periods collapsed by roughly an order of magnitude between July and August.

---

## These are ladders, not yield positions

The net flows make the strategy unambiguous. A position that takes SOL out of the wallet and
returns tokens is a **buy ladder**; one that takes tokens and returns SOL is a **sell ladder**.
Both appear, in alternation:

```
3r57GfbEZ9n…  -6.4382 SOL  →  +3,010,939 weave     buy ladder
6TfePAsND8v…  +8.1110 SOL  ←  -3,452,858 weave     sell ladder
CYFpkQdSx3k…  -7.9880 SOL  →  +3,715,744 weave     buy ladder
```

So "impermanent loss" was never the right lens, and the operator was right to reject it. These
are staged executions with a fee rebate, not yield farms.

---

## The uncomfortable number, and why it is NOT yet a verdict

Aggregating SOL-quoted legs across cleanly-attributable closed positions:

| token | buys | sells | avg buy | avg sell | spread |
|---|---|---|---|---|---|
| weave | 6,726,683 tok / 14.464 SOL | 8,138,881 tok / 12.320 SOL | 2.1503 µSOL | 1.5138 µSOL | **−29.6%** |
| DREGG | 987,803 tok / 8.834 SOL | 86,517 tok / 0.942 SOL | 8.9432 µSOL | 10.8886 µSOL | **+21.8%** |

**This does not establish that laddering lost money, and must not be read that way.** Averaging
buy and sell prices across a window measures *the token's price path*, not execution quality. If
weave simply fell between the accumulation phase and the distribution phase, a −29.6% spread is
what falling looks like — the ladder did not cause it, and a market order would have done worse,
not better.

Measuring execution quality requires comparing each fill against the market price *at that
moment*, which the tape can support and this analysis does not yet do. **That is the next
experiment, and it is the one that would actually score the strategy.**

Two further limits, stated so nobody quotes the table above as a result:

1. **The legs are commingled.** The wallet also swaps directly (115 inbound token transfers from
   DREGG's own PumpSwap pool alone), so LP flows and swap flows share the same balance changes.
   A clean LP-only PnL is not recoverable from wallet deltas without instruction-level attribution.
2. **12 of 42 positions were excluded** as not cleanly attributable — their transactions touch
   more than one position at once (batch closes), so flows cannot be assigned.

I could neither reproduce nor refute the **+$741 realised** figure from the parallel session with
this method. Different accounting, and mine is not the more trustworthy one — it is just a
different cut with clearly-stated exclusions.

---

## The survival filter — CORRECTED, and my first version was wrong

**This section originally reported "of 12 tokens: 9 alive, 3 dying, ZERO dead" and called it a
real signal. That was wrong on both the numerator and the denominator, in the flattering
direction, because of a survivorship bias I introduced myself.** The control-arm lane caught it.

**The denominator was a slice, not a criterion.** `scripts/lp/survival.py` did
`mints.most_common(20)[:12]` — a rank by how many times the wallet touched a mint, truncated to
twelve. Touch count correlates with how long the operator kept trading a token, which correlates
with the token still being alive. So the "population" was selected on the outcome being
measured. It is exactly the survivorship bias this project has spent two days finding in other
people's work, committed in a survival analysis, by me.

**The numerator was wrong too.** There IS a dead token:
`xNgLkoEHKxPhdo8Z3CANniWXsvcw6MuAeNyNg4aHoNn`, held 12.9 hours on 2026-07-24, with no DEX pair
anywhere. And `Hqhumk…pump` (Greenland) is dead on the thresholds this document itself
stated — $3,310 liquidity on **$44** of 24h volume.

Corrected, over the 21 mints held ≥60 seconds: **18 survive, 3 dead.**

| | original claim | corrected |
|---|---|---|
| tokens touched | 12 | **24** (21 held ≥60s) |
| dead | 0 | **3** |
| selection | `most_common(20)[:12]` | all mints, no outcome-correlated ranking |

### And the filter does not survive a control arm

The control lane built the counterfactual: all 43,249 pump.fun graduations over the window, a
complete on-chain census. Against a properly age-matched null the arm scores 13 of 14 where
8.93 were expected, one-sided exact **p = 0.0020** — which clears its pre-registered threshold.

But it does not hold anywhere else. Move "dead" from <$1k to <$5k liquidity and **p = 0.2299**.
Count "dying" as failure and **p = 0.2300**. Leave out the single best pick and **p = 0.0131**,
above the Bonferroni bar. Effective n is 10, not 14.

**And the decisive finding: a screen with no social information at all reproduces the record.**
Because the operator does not buy fresh graduates — median token age at entry is **5.0 days** —
the relevant null is conditional survival from that age. A rule reading "only buy graduates
already ≥14 days old" expects **12.64 survivors of 14**. The operator got 13.

The size confound cannot be doing the work (96.2% of graduations deposit an identical
206,900,000 tokens, so size is matched by construction, and time-on-curve does not separate:
33 min versus 6 min, permutation p = 0.74). But age at entry does all of it. **Verdict:
INDISTINGUISHABLE** — the filter is not refuted, it is unmeasured, and "the team is real" has
not been shown to beat "the token is a fortnight old."

The most useful number the lane produced is the power curve, because it says what to change:

| entry age | P(survive) | picks needed for significance |
|---|---|---|
| at graduation | 0.046 | 1 |
| ≥3 days | 0.272 | 3 |
| ≥7 days | 0.430 | 4 |
| ≥14 days | 0.878 | 24 |
| ≥30 days | 1.000 | never |

**Buying where the population is still dying is what makes the record informative.** The same
number of picks is worth 3 positions of evidence at a 3-day entry age and 24 at a 14-day one.

### Also corrected

The ladder table above had its symbols swapped: `XkeTXo1125vz…pump` is **DREGG**, not weave.
weave is `8PecVc…pump`. The flow figures are unaffected; the labels were wrong.

## Incidental finding worth a look

There are **two distinct tokens using the symbol "nosis"**. The one in the current open position
(`FPfi9q1A…`) is healthy: $55k liquidity, $540k daily volume. The other (`emusQFua…`) shows
**$719,696 of 24h volume against $1,445 of liquidity** — a turnover ratio of ~498×, which is not
a shape organic trading produces. That is the signature the wash-trading literature describes,
and it is worth knowing which one any future position is actually in.

---

## What to do next, ranked

1. **Score execution quality per fill.** Compare each ladder fill against the market price at
   that slot. This is the measurement that decides whether laddering beats market-selling, and
   it is the only one that separates strategy from price path. The tape infrastructure supports it.
2. **Instruction-level attribution** so LP flows separate from swap flows, recovering the 12
   excluded positions and making an LP-only PnL possible.
3. **Explain the July→August tempo change.** Holding periods fell ~10×. Was that deliberate, and
   did it help? The data can answer it.
4. **Track the survival filter prospectively.** 12/12 is encouraging and unfalsifiable in
   retrospect; recording the call *before* the outcome is what turns it into evidence.
