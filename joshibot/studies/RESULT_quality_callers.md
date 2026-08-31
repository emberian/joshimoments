# RESULT: jackduvalcalls is real, the pulse is real, and the dollar is the median

Run 2026-08-15.

```
uv run --group research python -m studies.quality_callers collect-jack --start 1785600000 --end 1786860000
uv run --group research python -m studies.quality_callers collect-cluster
uv run --group research python -m studies.quality_callers build-panel     # on persvati, see §7
uv run --group research python -m studies.quality_callers report --draws 200
uv run --group research python -m studies.quality_callers cluster-table
uv run --group research python -m studies.quality_callers watchlist
```

Code: `studies/quality_callers.py`. Artifacts: `state/callers/quality_cluster.jsonl` (518 rows),
`state/callers/watchlist.jsonl`, `state/callers/raw/*.jsonl` (the X censuses, with per-slice
truncation manifests).

**Spend: $1.91 of Apify X collection. $0 of BigQuery.** 99 census queries + ~11 probes, 7,428
billed items, 0 truncated slices at the adaptive floor.

---

## 0. The one-paragraph answer

**The wallet is found, the mechanism the operator described is real and large, and the strategy
still does not clear friction.** `jackduvalcalls` is the *pump.fun* username of
`BAr5csYt…XJPh` — on-curve, flow-verified, 17,494 pump.fun followers, bio *"never wrong, always
early."* — and on the operator's own fatdogwithhat trade the chain reads end to end:
coin created **16:41:04**, Jack's first fill **16:46:38**, operator's first buy **16:52:09**, a
**5 m 31 s** lead through the pump.fun following feed. Jack's trades mark an enormous attention
pulse: **808 price prints in the five minutes after a pulse against 17 for a matched ambient
coin**, and a round-trip-to-net-move ratio of **22.7 against 2.5** — nine times more wiggle per
unit of direction. The operator's felt "roughly a dollar per event" reproduces exactly: the
**median** extraction per pulse is **+$1.14** at a 0.1 SOL clip. But the **mean is −$0.19**
[95% CI −$0.375, −$0.008], the losing tail is bigger than the dollar, and across **128 exit
brackets × 4 latencies, not one configuration has a positive mean**. Faster reaction does not
rescue it — 2 s buys **+$0.16/event** over a 300 s reaction, inside the noise — so the
amplification thesis is refuted on this window. Two of five roster accounts (`orangie`,
`daumen`) show nominally positive extraction on n = 61 and 69 and are the next experiment, not
a result.

Three things fell out that are worth more than the strategy:

1. **The channel is the pump.fun following feed, and it is seconds ahead of every echo channel
   this repo has measured.** `RESULT_caller_wallets.md` found callouts arriving a median 26 s
   *after* the burst. This one fires on the *trade*.
2. **@jackduval does not post contract addresses.** 4 of 464 tweets over 14 days carry a mint,
   across 2 distinct coins. A study that had measured "his callouts" on X would have measured
   nothing and called it a null.
3. **Not one of the 18 pump.fun-username matches in the quality-cluster census ever traded the
   coin its handle called.** Route 1 yields names, not identities, and the second leg is what
   separates them.

---

## 1. The wallet, and what grade of evidence it carries

The operator said "jackduvalcalls". That string resolves on two different platforms to two
different things, and conflating them is how this study would have measured the wrong entity.

| claim | verdict | evidence |
|---|---|---|
| X handle `jackduvalcalls` posts callouts | **false** | `from:jackduvalcalls` returns **0** tweets over 2026-08-01 .. 08-16, collected the same way as the positive control |
| the X account that posts is `@jackduval` | true | 464 tweets over the same window, 51,738 followers |
| `jackduvalcalls` is a **pump.fun** username | **true** | `/users/search?searchTerm=jackduvalcalls` → `BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh`, 17,494 followers, bio *"never wrong, always early."* |
| pump.fun's own `x_username` field links them | false | null, as `RESULT_caller_wallets.md` §1 route 2 found on all 317 wallets it probed |

**Address hygiene, both legs, per `wallet_labels.yaml`'s resolution rule:**

- **on-curve:** `on_curve("BAr5csYt…") is True` (`studies/copytrading.py:427`). A fabricated
  address lands on the curve about half the time, so this is necessary and not sufficient.
- **flow-verified:** 1,419 successful token-balance legs over 271 pump mints in
  `state/bulk_pump`, 2026-08-05 .. 08-11; 969 non-zero token accounts and 59.09 SOL at
  2026-08-15. It is a wallet that exists and trades.

**Corroboration that it is *this person's* wallet** (this is the part that is inference):

- It holds **25,231,399.36** of `89RAitwPJBEfLK4Gcg5iv7AjFABHWNvoD5rkvRkvpump`. `@jackduval`
  tweeted twice on 2026-08-04 that he had personally paid creators to make TikToks for that
  exact mint. The wallet's first successful buy is **2026-08-04T03:19:17Z**, 9 h 33 m before
  his first tweet naming it.
- On the operator's own trade (§2) it is in the coin, at size, minutes ahead.

**Grade: `probable`, not `attested`.** What would upgrade it is one glance: the operator opening
`pump.fun` on the `jackduvalcalls` profile and confirming the address. Recorded in
`state/callers/watchlist.jsonl` as such.

**An impostor was found in the same search and is recorded so nobody re-resolves it:**
`9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP`, username **`jackduvalcaIIs`** — capital-I
homoglyph for the two lowercase Ls — 9 followers. A fuzzy join would have taken it. This is the
same attack shape as the address-poisoning campaign in `wallet_labels.yaml`, moved up a layer
from base58 to usernames.

---

## 2. The operator's own trade, reconstructed to the second

`Boqj1AxUGZSPFxyNrt2x9aEeR97R45JmUg1dPwKVpump` ($FATDOG, "fatdogwithhat"), 2026-08-15. This is
one event and is reported as one event — but it is the only place in this repo where the whole
causal chain has been observed with real timestamps on both ends.

| t (UTC) | who | what |
|---|---|---|
| 16:41:04 | — | coin created |
| **16:46:38** | **jackduvalcalls** | first fill: +250,477 tokens, −0.2273 SOL |
| 16:47:07 | jackduvalcalls | +273,994 tokens, −0.2582 SOL |
| 16:49:18 | jackduvalcalls | +1,100,820 tokens, −1.0020 SOL |
| **16:52:09** | **operator** | buy 66,564 tokens, −0.1056 SOL |
| 16:52:16 | operator | sell 66,564 tokens, +0.0973 SOL *(7-second round trip)* |
| 16:53:31 | jackduvalcalls | +785,977 tokens, −1.0020 SOL |
| **17:04:38** | **jackduvalcalls** | +695,086 tokens, −1.0035 SOL |
| **17:04:48** | **operator** | buy 64,789 tokens, −0.1036 SOL *(**10 s** after Jack)* |
| 17:10:02 / 17:19:07 / 17:24:30 | jackduvalcalls | three more ~1 SOL adds |
| 17:31:58 | operator | sell 64,789 tokens, +0.1037 SOL |

**Lead on the first entry: 5 m 31 s. On the second: 10 seconds.** The second is the
following-feed notification working as designed.

Two things this event settles that no aggregate could:

- **Jack was not exiting into the operator.** 116 successful transactions on this mint, **10
  buys and zero sells**, 12.43 SOL deployed over 44 minutes, still holding 16.6 M tokens. This
  is accumulation, not a distribution. The front-running mechanism `RESULT_caller_wallets.md`
  went looking for is not what is happening here.
- **His revert rate is 98.2%** — 6,433 signatures on that one token account for 116 fills. He
  is a sniper bot operator, not a person clicking buy.

Operator P&L on the two round trips, from the chain (SOL deltas include fees): **−0.0083 SOL**
then **+0.0001 SOL**. The 15 cents is inside the noise of a 0.1 SOL clip; §4 says why that is
the expected shape rather than bad luck.

---

## 3. The mechanism: the pulse is real and it is enormous

Unit of analysis is the **pulse** — one buy leg by the followed wallet on one mint, which is
what the following feed fires on. **839 pulses over 7.0 days = 120/day across 255 mints.**

Five minutes after a pulse, against a matched ambient coin (same instant, traded within the
previous 300 s, never touched by the wallet):

| | prints / 5 min | summed \|Δlog p\| | round-trip ÷ net move |
|---|---|---|---|
| **at the pulse** | **808** | **10.99** | **22.66** |
| ambient | 17 | 0.034 | 2.46 |

That is a **47× density** difference and a **9× two-sidedness** difference. The operator's model
of the channel — *"his callouts reliably drive me to coins"* whose churn is the resource — is
**correct and is the largest effect in this study.** `RESULT_callout_volatility.md`'s finding
that callouts mark wiggle rather than direction reproduces here with the latency inverted: this
channel fires on the trade, not on a tweet about the trade.

(The ambient row rests on 5 coins, because a random live coin usually cannot supply four prints
in five minutes. That failure *is* the contrast, and it is reported as 5 rather than hidden.)

---

## 4. The latency-decay curve — the deliverable, and it is flat

Extraction per pulse under the desk's own discipline: enter at `t + L`, wiggle bracket, exit on
take-profit / stop / clock, friction recomputed per fill from the pool's measured depth
(`shitcoims_scalper.policy.round_trip_friction`), 0.1 SOL clip, marked at $160/SOL.

| latency | n | mean net | **$/pulse (mean)** | **$/pulse (median)** | p(win) | ambient | lift |
|---|---|---|---|---|---|---|---|
| **2 s** (pumpportal `accountTrade`) | 831 | −1.82% | **−$0.292** | **+$0.651** | 69.6% | −$0.447 | +$0.156 |
| 15 s | 829 | −3.93% | −$0.629 | +$0.606 | 60.9% | −$0.712 | +$0.083 |
| 60 s (fast human) | 826 | −3.44% | −$0.550 | +$0.601 | 59.9% | −$0.739 | +$0.190 |
| **300 s** (the operator's app notification) | 819 | −2.43% | **−$0.388** | +$0.403 | 51.2% | −$0.475 | +$0.087 |

**There is no latency gradient.** 2 s beats 300 s by **$0.10 per event** on the mean, and the
curve is not even monotone — 60 s beats 15 s. The amplification thesis says the operator's slow
reaction is what limits the take; on this window it is not. What limits the take is that the
mean is negative at every latency.

**And the median is the operator's dollar.** At the best brackets the median pulse extracts
**+$1.10 to +$1.24** — which is precisely the lived experience being reported, and it is not an
illusion. It is the *median*. Sixty-nine percent of pulses pay about a dollar; the other 31%
give back more than the winners took. Over one afternoon you feel the median. Over 120 pulses a
day you get the mean.

### 4.1 Can any bracket monetise it? No — 128 tried

Grid over latency {2, 300 s} × hold {30, 60, 120, 330 s} × TP {2, 3, 5, 9%} × SL {4, 6, 10, 25%}
= **128 configurations, the honest trials count.**

- **Zero configurations have a positive mean.** Best in-sample is −0.945%.
- **118 of 128 survive BY-FDR at q = 0.10 — every survivor is a significant LOSS.**
- Best-on-train applied out of sample: **−0.64% → −2.31%**, a 3.6× degradation.

`PROGRAM.md` §3.9 says past ~7 configurations an in-sample Sharpe of 1 is an out-of-sample zero.
Here we did not even find an in-sample positive to deflate.

### 4.2 The three arms the brief asked for, scored side by side

| arm | how it is entered | n | net mean | note |
|---|---|---|---|---|
| **(a) at Jack's buy** | wallet-trade detection, +2 s | 252 | **−0.90%** [−2.46%, +0.60%] | CI straddles zero; rotation null p = 0.57; coin-shuffle null p = 0.16 |
| (c) at burst detection on his coins | ≥15 distinct buyers in a minute, +60 s to observe it | 206 | −2.63% | on coins he *ignored*: −5.16% |
| (b) at his callout | he posts ~no CAs (§5) | **2 mints / 14 days** | not measurable | population estimate `RESULT_callout_edge.md`: −11.9% at 1 h |

So the expected ordering **(c) ≻ (a) ≻ (b)** is **wrong**: (a) beats (c) by **+2.00 pp**
paired on the same 205 coins, 95% CI [−0.32, +4.29], p = 0.088. Watching the wallet is worth
about two percentage points a trade over watching the chain — and **his buy lands within 60
seconds of the chain-visible burst on 60.5% of coins**, so most of the time you are not even
early, you are simultaneous.

At a 30 s latency — the board tape's cadence — arm (a) is **−4.93%**, and its test half is
−6.75%. Whatever is there needs a second-scale stream to touch at all.

### 4.3 Buy-and-hold, for completeness

If you skip the bracket and simply hold what he buys: median **−23.6% at 5 min**, **−64.5% at
30 min**, **−69.0% at 2 h**, p(up) 31% / 20% / 15%. The bracket is doing real work; without it
this is a catastrophe. And the actionable window itself — his buy to the crowd burst, median
lead 60 s — moves **−10.0%** median, clearing the 2.57% friction bar in only 42.1% of cases.

---

## 5. @jackduval's X account is not a callout channel

464 tweets, 2026-08-02 .. 08-15, censused adaptively with **0 truncated slices**.

- **4 tweets carry a mint. 2 distinct mints.** Both are coins he was openly promoting
  (`OnlyMarms`, and the TikTok coin `89RAitwP…`).
- **2 cashtag mentions in the entire corpus**, both `$OnlyMarms`.
- 414 of 464 are replies. The 50 original posts are PnL screenshots (*"+ $95,000"*,
  *"+ $50,000 on the day"*), trader drama, and market commentary.

He even addresses the accusation directly: *"i see a lot of confusion on the tl about me catching
all these runners so early… people saying i'm launching these myself… fact is i'm just a good
trader"*. The crowd disagrees in public (*"Jack duval bundled again"*, *"sells his sides and buys
on his main"*), and §2's 98.2% revert rate says the truth is at least "runs sniper
infrastructure".

**This is why the estimand mattered.** A study that took "his callouts" to mean his tweets would
have found n = 2, reported a clean null, and missed a 120-pulse-a-day channel entirely.

---

## 6. The quality-cluster census — 476 callers, and every wallet join fails its second leg

`state/callers/quality_cluster.jsonl`, **518 (caller, coin) rows over 476 distinct handles**,
censused over each coin's full life from the pump.fun creation clock.

| coin | mint | created | tweets | callers |
|---|---|---|---|---|
| DREGG | `XkeTXo11…pump` | 2026-06-27 | 1,118 | 193 |
| SOLVE | `GwyWFsDK…pump` | 2026-07-20 | 141 | 25 |
| weave | `8PecVcCG…pump` | 2026-08-03 | 258 | 44 |
| nosis | `FPfi9q1A…pump` | 2026-08-09 | 798 | 240 |

Taxonomy, using `RESULT_caller_wallets.md` §6's boilerplate discriminator:

| class | rows |
|---|---|
| single call, unclassifiable from one tweet | 305 |
| automated relay (boilerplate ≥ 0.6 or links ≥ 0.8) | 90 |
| repeat, not template-detected | 123 |

The feed is dominated by one account: `0x8hero` posts **423 of DREGG's 1,118 tweets**.

### 6.1 The join, route by route

| route | mechanism | yield |
|---|---|---|
| 1 | pump.fun username == X handle | **18 of 476** (3.8%) — matches `RESULT_caller_wallets.md`'s 3.4% |
| 1b | **…and that wallet ever traded the coin it called** | **0 of 18** |
| 2 | pump.fun `x_username` field | 0 (dead, as before) |
| 3 | the coin's advertised X profile is the caller | 3 (`ember_arlynx`/DREGG, `plan9nosis`/nosis, `open_solve`/SOLVE) |
| 4 | temporal join with a time-matched permutation null | **degenerate — see below** |

**Route 1b is the finding.** Sixteen handles have a byte-identical pump.fun username, and not
one of those wallets appears as a counterparty on the coin its namesake called. Every one is
graded `weak_name_collision_possible` in the artifact — and the follower counts say why: 14 of
18 have **0–51 pump.fun followers**. Anyone can register a username. A name match is a name, and
the trade is what makes it an identity.

**Route 4 has no power here and is reported as such rather than as a result.** Two callers
(`dex_kolwatcher`, `AiSolanaKols` — both obviously relay bots) come out at p = 0.002, FDR-10%
"significant", on a best overlap of **one wallet across two coins** with a null mean of 0.00.
With a universe of **four coins**, the time-matched substitution usually has no admissible
substitute, the null collapses to zero, and any overlap at all looks infinitely surprising. This
is the mirror image of the hypergeometric trap `RESULT_caller_wallets.md` §3 disclosed: there
the null was too weak, here it is too small. **Both survivors are artifacts of a 4-coin universe.**

**The attributed window is 7 days, not 48.** `state/bulk_history/` carries the cluster's full
48-day pool history but has **no trader attribution** — bulk rows are pool-level only. Only
`state/cluster_tape/` (2026-08-09 .. 08-15) carries `counterparty`, so every wallet-side
statement about cluster callers is confined to those 7 days, and `call_inside_attributed_tape`
is a field on every row so the reader can see which is which.

---

## 7. The roster arm — does the pulse generalise?

Route 1 over 51 candidate handles found **5 pump.fun accounts with ≥ 500 followers**, all
on-curve, all flow-verified against the corpus.

| account | pump.fun followers | pump mints | priced | pulses | pulses/day | prints/5 min | wiggle ratio | **$/pulse** | median $ | p(win) |
|---|---|---|---|---|---|---|---|---|---|---|
| **jackduvalcalls** | 17,494 | 271 | 259 | 839 | 119.9 | 808 | 22.7 | **−$0.191** [−0.375, −0.008] | +$1.140 | 69.8% |
| **daumen** | 30,368 | 322 | 47 | 72 | 10.3 | 200 | 10.4 | **+$0.265** [−0.225, +0.685] | +$1.124 | 60.9% |
| **cupsey** | 14,682 | 48 | 10 | 11 | 1.6 | 351 | 7.3 | n too small | — | — |
| **cooker** | 3,287 | 359 | 37 | 126 | 18.0 | 1,720 | 47.0 | −$0.173 [−0.830, +0.442] | +$1.237 | 80.2% |
| **orangie** | 2,461 | 186 | 38 | 61 | 8.7 | 582 | 15.9 | **+$0.611** [+0.021, +1.131] | +$1.199 | 83.6% |

Three readings, in decreasing order of how much they should be trusted.

**The mechanism generalises.** Every one of the five marks a pulse 3–19× more two-sided than
ambient's 2.46. This is not a jackduvalcalls fact; it is a following-feed fact. The following
feed is a **flow-pulse calendar**, and that is the durable object here.

**Churn does not equal extraction.** `cooker` has the densest pulse in the roster (1,720
prints/5 min, wiggle ratio 47.0) and a negative mean. Whatever converts churn into dollars, raw
two-sidedness is not it.

**`orangie` and `daumen` are hypothesis-generating and nothing more.** n = 61 and 69, one exit
bracket chosen on Jack's data, and **two positives out of five accounts tried is exactly what
chance produces**. `orangie`'s CI clears zero by $0.02. The ambient control could not be
computed at that n — a random-coin draw rarely yields 15 priced fills against 61 instants — so
these rows have **no null at all**. They are the next experiment.

Coverage caveat, stated because it bounds every roster row: the panel prices Jack's mints plus a
deterministic **4% hash sample** of the market, so the roster accounts have only ~4% of their
mints priced. The sample is unbiased (it is a hash of the mint, independent of anything about
the coin), so the estimates are unbiased — they are just thin.

---

## 8. What this costs to run live, and the two reasons it is not free money

At 2 s latency, 0.1 SOL clip, one wallet: **−$0.292/pulse × 120 pulses/day = −$35/day.**
`orangie`'s in-sample +$0.611 × 8.7/day would be +$5.30/day if it survived a null, which it has
not been tested against.

Two effects make even that optimistic:

- **We would become part of the pulse.** At any size the entry competes with the same 808
  prints it is trying to harvest. The friction model here charges impact against measured pool
  depth, but it does not model *other copiers arriving on the same notification* — and a
  following feed with 17,494 subscribers is a crowded trade by construction.
- **Adverse selection on the tail.** The 31% of pulses that lose are not random: they are the
  ones where Jack is early to something that does not run, and those are exactly the ones a
  copier holds longest before the stop fires.

---

## 9. Trials, spend, and limits

**Configurations evaluated:** 128 in the bracket grid, 18 in the earlier first-buy grid, 7
latencies × 3 arms in §4.2, 5 roster accounts × 1 bracket, 4 join routes, 2 nulls × 2 arms.
Call it **~170 substantive configurations.** Nothing positive is offered as a result: the
positives (median dollar, orangie, daumen) are all labelled as median-not-mean or as
hypothesis-generating, and the negatives are large, monotone in nothing, and survive their nulls.

**Spend:** $1.91 Apify (99 census queries + ~11 probes, 7,428 items, **0 slices truncated at the
adaptive floor** — the census claim is structural, not lucky). $0 BigQuery. ~1,100 free pump.fun
calls, browser-UA, ≥160 ms apart. Helius RPC read-only (the client's method allowlist forbids
signing).

**Limits, stated plainly:**

- **The panel is 2026-08-05 .. 08-11, seven days.** The persvati mirror of `bulk_pump` is
  complete for 08-05 .. 08-10 and 19% complete for 08-11; days 08-12 .. 08-14 are **empty
  there** although present locally. The panel build was moved off this Mac mid-study on a
  resource directive, so the window is the mirror's, not the corpus's. Extending it is a rerun,
  not new code.
- **§2 is one event.** It is the only end-to-end observation of the channel and is reported as
  a single event, not an estimate.
- **The ambient control thins out fast.** At 839 instants it is solid; at 61 it cannot be
  computed. Every roster row without a null says so.
- **`orangie` and `daumen` have no null.** See §7.
- **The cluster wallet-join window is 7 days of a 48-day coin.** §6.
- **Route 4's null is degenerate on a 4-coin universe.** §6.1. Its two "survivors" are artifacts.
- **$160/SOL is a marking constant**, not a measurement; every dollar figure divides back out.
- **The wallet identification is `probable`.** §1. One operator glance upgrades or kills it.
- **Jack's own directional record is deliberately not the estimand** — the operator's own
  correction. He bought 12.43 SOL of the fatdog coin and sold none of it; whether that was a
  good trade is not this study's question.

---

## 10. What follows

1. **Get the operator to confirm the address**, which is one page load, and the grade goes from
   `probable` to `attested`.
2. **The following feed is a flow-pulse calendar. Build the calendar, not the copy trade.** The
   durable finding is §3 and §7's first reading: these accounts' trades mark 3–19× two-sidedness
   with second-scale lead. `accountTrade` subscriptions on the five roster wallets would surface
   pulses as first-class events in the operator's glass. That is a *candidate generator* — the
   same conclusion `RESULT_callout_edge.md` §6 reached about the callout feed, arrived at from
   the opposite direction and with a much better instrument.
3. **Do not size up the copy trade.** 128 brackets, zero positive means, and a 3.6× out-of-sample
   degradation. The dollar the operator feels is the median and the mean is negative.
4. **Test `orangie` and `daumen` properly** — full panel coverage of their mints rather than a
   4% sample, an ambient null at their n, and a pre-registered bracket. That is one persvati
   pass and no new collection.
5. **Re-run on the full 10-day corpus** once the persvati mirror is complete, and extend forward:
   the pulse rate (120/day) means a week roughly triples every n in this document.
