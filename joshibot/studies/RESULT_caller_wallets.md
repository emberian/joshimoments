# RESULT: the callers' wallets — the mouth is 26 seconds behind the money

Run 2026-08-15 with the same tape pin `RESULT_callout_edge.md` uses:

```
uv run --group research python -m studies.caller_wallets --report --draws 400
```

Full output at `studies/data/caller_wallets_run.txt` (untracked; `studies/data/` is gitignored).
Code: `studies/caller_wallets.py`. Reproduces in ~8 minutes from the caches in
`.cache/caller_wallets/`, and the BigQuery pull is a one-liner in the module docstring.

**Spend: $1.12 of BigQuery** — one 191.2 GB scan for the swap tape plus 5.4 GB of preflight, both
dry-run first and capped with `--maximum_bytes_billed`. No X collection: the callout census
`callout_backfill.py` already bought was reused verbatim.

---

## 0. The one-paragraph answer

**The callers do not front-run their callouts, because most of them are not people and do not
have wallets — and where a wallet-to-callout link does survive a proper null, the wallet is not
the caller's, it is a crowd of 161 strangers who bought 26 seconds earlier.** Of 146 caller
handles, the X-handle→wallet join succeeds by identity for **5** (3.4%) and by the coin's own
advertised profile for **29 coins**; pump.fun's native `x_username` field is present in the
schema and **null on all 317 wallets probed**, so the lookup that would have made this a
five-minute study does not exist today. Only **1 of 22** multi-coin callers has any wallet
overlap surviving a time-matched permutation null at FDR 10%, and that caller — `AutorunAlert`,
an Axiom referral bot — turns out to be the *echo* of a 161-wallet buy burst rather than the
cause of it. **Caller-wallet identity adds AUC −0.009 at 1 h and −0.002 at 8 h** over anonymous
flow: a clean null on the operator's question as literally posed.

The study did not come back empty, though. Two things fell out of it that are worth more than
the hypothesis it was testing:

1. **Anonymous on-chain flow at the callout instant carries the information the callout does
   not.** On the pinned board-priced cohort, flow columns alone score **AUC 0.758 at 1 h and
   0.764 at 8 h**, against the callout block's 0.471 and 0.385, and at 8 h flow is the **only
   block with positive information in bits** (+0.0711 bits/row where the free columns give
   −0.0238). One column does most of it: `recycled_30m`, the share of the last half hour's
   buying already sold back, scores **0.824 alone at 8 h** — better than every fitted model in
   either study.
2. **51.4% of the "callout" feed is machine-generated referral spam from 13 accounts.**
   `RESULT_callout_edge.md` measured "what callouts predict"; what it was actually measuring, for
   the majority of its rows, was **alert bots announcing coins that had already moved**. That
   reframes its anti-signal from a claim about human influence into a claim about instrument
   latency, and it is the reason its loudness gradient is monotone.

---

## 1. The join, and the honest yield of each route

An X handle is not a wallet. Four routes were tried; each one's yield is a measurement.

| route | mechanism | yield |
|---|---|---|
| 1 | pump.fun username == X handle, via `/users/search?searchTerm=` | **5 of 146 handles** (3.4%) |
| 2 | pump.fun profile's own `x_username` / `x_id` field | **0 of 317 wallets probed** |
| 3 | the coin's advertised X **profile** is one of our callers | **29 coins** (of 70 linking a profile) |
| 4 | temporal join: a wallet that repeatedly pre-buys one caller's coins | **1 of 22 callers** at FDR 10% |

Three things about that table are worth carrying forward rather than rediscovering.

**The endpoint that works is not the endpoint that looks like it works.**
`/users/search?username=…` and `?q=…` both return HTTP 200 with `[]` for every input, including
inputs that exist. A study that used either would have reported a clean, confident zero. The live
parameter is `searchTerm`, and it fuzzy-matches pump.fun *usernames* — so it fires only when a
caller happens to use the same name on both platforms, which 5 of 146 do. `/users/{wallet}` is
the only other live shape; `/users/username/…`, `/users/by-twitter/…`, `/profiles/…` and
`/search?q=` are all 404.

**Route 2 is the one that should have worked, and it is dead.** The pump.fun user object carries
`x_username` and `x_id`. Across 317 wallets probed — 60 drawn at random from the 144,293 traders
in the cohort, plus 257 chosen as temporal-join candidates and route-3 creators — **51 had a
pump.fun profile at all and not one had a non-null `x_username`**, including accounts with 7,884
and 16,921 pump.fun followers. So the native link exists in the schema and is not served. Any
future study that wants an X↔wallet join on this platform should budget for inference, not
lookup.

**Route 3 is the only join that produces a wallet you can point at**, and it is worth separating
from the noise: 179 cohort coins advertise *some* x.com URL, but 109 of those are links to a
*status* (a coin minted about somebody's tweet, where the handle is the tweet's author and has
nothing to do with the launcher). Only the 70 profile links assert "this account is this coin",
and 29 of those name a caller. §5 measures that arm.

---

## 2. Before identity: is there any callout-induced flow to exit into?

The front-running hypothesis needs somewhere for the caller to sell. There isn't one.

Measured on 345 (caller, mint) first-call events with a full ±30 min on-chain window:

| statistic, 30 min after vs 30 min before | at the callout | same coin, crowd-matched instant |
|---|---|---|
| log(buy volume after / before) | **−0.906** (0.40×) | −0.453 (0.64×) |
| log(distinct buyers after / before) | **−0.693** (0.50×) | −0.354 (0.70×) |

Buying does not rise after a callout. It **halves**, and it halves harder than it does at a
moment on the same coin with a comparable recent crowd. The callout lands on the *far side* of
the buying, which is the mechanism behind `RESULT_callout_edge.md`'s −11.9%/1 h directly
observed in flow rather than inferred from price.

Note what the matched control cannot do: only **138 of the 345** callouts have a
comparable-crowd instant elsewhere in the same coin's life at all (190 have an age-matched
control on another coin, 183 an age-and-crowd one), because for many coins the callout **is** the
coin's unique peak. Excluding those makes the comparison conservative — the unmatched callouts
are the more extreme ones, and they are the ones dropped.

### 2.1 The recycling statistic, and the null that ate most of it

At the callout, **55.7% of the next half hour's selling is done by wallets that bought in the
previous half hour**. That is the buy→sell choreography, at the population level, without needing
to know who anybody is. It is also where this study nearly fooled itself, so all three nulls it
was checked against are reported:

| null | median share |
|---|---|
| **observed, at the callout** | **0.557** |
| same coin, a random instant *(the naive null)* | 0.028 |
| other coins, matched on coin age | 0.259 |
| other coins, matched on age **and** pre-window crowd | **0.466** |

Against the naive null this is a 20× effect. Against age it is 2.2× (p = 2.0e−19). Against age
*and* crowd it is **1.20×** — Mann-Whitney p = 5.3e−07, real but small. Nearly the whole
apparent effect is that a called coin is **27 minutes old** (median; p10 2.6 min) and has **242 distinct buyers in the
previous half hour** (median), and on any such coin the recent buyers are most of the float. This
is the third time in this repo that an autocorrelation- or composition-preserving null has eaten
most of a headline (`RESULT_flow_signals`, `RESULT_copytrading`'s 73× → 0.98×); it is now
routine enough that the naive number is reported only to show the size of the trap.

---

## 3. The temporal join: 1 of 22, and it is not what it looks like

For each caller with ≥2 on-chain-visible coins, the statistic is the largest number of that
caller's coins any single wallet bought inside the pre-window. The null replaces each of the
caller's coins with a coin called **by somebody else within ±30 minutes**, holding fixed the
caller's call count, the hour, the market-wide burst structure and every substituted coin's own
trade tape. Only whose callout it was varies.

| caller | coins | best wallet overlap | null mean | p_perm | FDR 10% |
|---|---|---|---|---|---|
| **AutorunAlert** | 51 | **48** | 25.16 | **0.002** | **YES** |
| dexevents_cat | 31 | 22 | 15.97 | 0.015 | |
| anubisgtrade | 23 | 18 | 12.53 | 0.015 | |
| dexliveevent | 19 | 14 | 10.43 | 0.035 | |
| dex_event_live | 16 | 12 | 9.19 | 0.102 | |
| …17 more | | | | 0.125 – 1.000 | |

Same answer at a 5-minute window: 1 of 22.

**A hypergeometric test was tried first and is wrong here.** Asking "given this wallet pre-bought
K of the cohort's 345 callouts, is k of caller A's n surprising" treats the 345 events as
exchangeable. They are not — a caller whose 51 calls land in one busy hour gets credit for every
wallet that happened to be awake. It returned **1,758 FDR-significant wallet-caller pairs**,
essentially all of them AutorunAlert's. The time-matched substitution above returns 1. The
difference between those two numbers is the entire methodological content of this section.

**The null result is the result for 21 of 22 callers.** On this window, the accounts that call
coins out do not detectably trade them. That kills the front-running mechanism as an explanation
for the callout anti-signal and leaves promotion — mostly automated promotion, §6.

---

## 4. The one survivor, and why it is an echo rather than a front-run

`AutorunAlert` posts *"🌟 An Axiom trader just made +2.78 SOL ($222) PNL on $truckdog!"* with an
Axiom referral link on **100%** of its tweets. Its leading wallet's timing is machine-tight:

| the leading wallet `3SkBCx49…P46d7b` | p10 | median | p90 |
|---|---|---|---|
| tweet minus its first buy, on AutorunAlert's coins (n=48) | +17 s | **+26 s** | +35 s |
| same wallet, on every other caller's coins (n=102) | +74 s | +1,212 s | +7,199 s |
| its first sell, relative to the tweet (n=11) | +21 s | +186 s | +216 s |

A 26-second lead, on 48 of 51 coins, with a 18-second interquartile spread, and *only* against
this caller. Read alone that is a front-runner caught in the act.

It is not, and the check that decides it is counting the company it keeps. **60 distinct wallets
buy in that same 5–60 s band before an AutorunAlert tweet**, seven of them on 34+ coins each, and
**all 51 of 51 coins carry such a burst: a median of 161 distinct wallets (p90 506) spread over a
median 54 seconds**. And the
wallet never closed a position before the tweet (0 of 48) — so the tweet is not reporting *its*
completed trade either.

So the causal picture is not caller→wallet. Something makes ~161 wallets buy the same coin within
a minute, and AutorunAlert's tweet is a downstream announcement of the same event, arriving
**26 seconds late**. Given the tweet's own text and referral link, the obvious candidate is an
in-app Axiom surface — the burst is the app's users, the tweet is the app's marketing channel.
That is a hypothesis this instrument cannot confirm, and it is labelled as one.

What *is* established: for the single caller in this cohort whose callouts have a reliable
on-chain precursor, **the precursor is public flow, not private identity**. Watching the wallet
buys you nothing you could not get from watching the tape.

---

## 5. The caller-is-the-project arm — an identified wallet, no inference

The 29 coins whose advertised X profile is one of our callers give a wallet with no guessing: the
coin's `creator`. 15 have creator activity on the on-chain tape.

- **8 of 15**: the creator's first buy *is* the create-transaction dev buy. That is the launch
  sequence, not front-running — you cannot front-run a coin by minting it.
- **7 of 15**: a later discretionary add, a **median 2.8 hours** before their own tweet (p10
  −1,430 s, i.e. some bought after). Accumulate-then-shill at the hours scale, not the minutes
  scale.
- First sell relative to the tweet, n = 6: median **−286 s** — the dev's first sale slightly
  *precedes* their own post. Six rows; a lead, not an estimate.

1 h return on this arm is −0.02% median / −6.56% mean (n = 14) against −5.66% / −12.12% for every
other callout (n = 300). Directionally the project's own account is the *least* bad thing in the
feed, which is the opposite of the folk model, and the n forbids anything stronger than "worth a
second look on a bigger window".

---

## 6. What the callers actually are — the reframing

Boilerplate share = the fraction of an average tweet's words that appear in ≥80% of that
account's tweets, after stripping URLs, addresses and numbers. A person writing about a coin
scores near zero; a template with the ticker slotted in scores near one.

| shape | accounts | callouts | share of feed |
|---|---|---|---|
| **automated relay / alert bot** (boilerplate ≥0.6 or referral links ≥0.8) | **13** | **236** | **51.4%** |
| 2+ calls, not template-detected | 25 | 104 | 22.7% |
| a single call, unclassifiable from text alone | 119 | 119 | 25.9% |

Thirteen accounts — 8.3% of the handles — produce over half the feed, and every one of them is a
machine: `AutorunAlert` (Axiom PnL bot, referral 1.00), the `dexevents_*` / `dexliveevent` /
`dex_event_live` / `anubisgtrade` family (all *"INFLUENCER POST: … ALL EVENTS: …"* relays,
boilerplate 0.62–0.65), `solhousesignals` (scanner, 0.67), `memcoingemalert` (retro "3x from
Private Gem Alert", 0.95). The largest *non*-templated repeat caller, `8up1658913` with 24 calls,
is a human reply-spammer @-ing strangers, which is a different failure mode and not a signal
either.

**This is the finding that most changes how to read `RESULT_callout_edge.md`.** Its four
discovery queries (`url:dexscreener.com/solana`, `url:axiom.trade`, `"CA" pump`,
`url:pump.fun`) are, by construction, queries for *links posted by tooling*. It did not measure
influence; it measured latency — and "loud callouts land on coins that already ran" is exactly
what an alert bot does, because an alert bot only fires once there is something to alert about.
Its identity-permutation null beating the real assignment 24/24 is the same fact seen from the
other side: caller identity in that cohort is mostly *which bot*, and which bot is a proxy for
which trigger threshold.

### 6.1 The taxonomy the brief asked for, filled in

PROGRAM.md §4's four classes, with the counts this cohort actually supports:

| class | how it would show | count |
|---|---|---|
| **front-runner** (buys, then calls) | wallet link surviving the null, buy before call | **0** callers — the one link that survives is a crowd, §4 |
| **bagholder-evangelist** (bought long ago, calls on the way down) | identified wallet, buy hours before the call | **7** coins in the route-3 arm, median 2.8 h |
| **the launcher shilling their own coin** | creator == caller, first buy is the create tx | **8** coins |
| **pure promoter** (never touches chain) | no wallet link by any route | **21 of 22** multi-coin callers, and 124 of 146 handles that never even reach two on-chain coins |
| **baiter** (wallet dressed to bait copiers) | machine-uniform trade sizing | **258 (wallet, coin) legs, 7.2%** of the 3,606 legs with ≥20 buys on one coin |

The baiter number is the weakest cell and is labelled so: 55,626 distinct wallets pre-bought at
least one callout; 3,606 (wallet, coin) legs did ≥20 buys on a single coin; 258 of those sized
every buy within a 25% coefficient of variation, which no discretionary trader does. That is
prevalence of *machinery* in the pre-callout crowd. **A market maker and a wash-trader leave the
same trace and nothing here separates them**, so it is not evidence of bait — it is a ceiling on
how much of the pre-callout crowd could possibly be bait.

The dominant class, by a wide margin, is pure promoter. That is the answer the front-running
hypothesis loses to.

---

## 7. What the lead is worth

If the caller's buy were the tradeable object, its value is bounded by how much of the move is
already gone when the callout lands.

| window ending at the callout | n | median | mean |
|---|---|---|---|
| last 60 s | 335 | +0.00% | +3.21% |
| last 300 s | 291 | +0.00% | +22.12% |
| last 900 s | 251 | +0.00% | +22.67% |
| last 1800 s | 152 | +0.00% | +28.53% |
| **forward 1 h from the callout** | 354 | **−5.25%** | **−14.79%** |

(These are GeckoTerminal-first marks, so like §8's GT arm they move as coverage fills; the
medians have been flat at 0.00% across every run, the means have not.)

The median callout is preceded by *no* move and followed by −5%; the mean is preceded by a
violent run and followed by −15%. The prize for being early is concentrated in a minority of
events, which is exactly the shape that makes a lead hard to monetise.

And the specific 26-second lead of §4, priced on the same tape as everything else: **median
+0.000%**, with the buy and the callout landing on the *same price bar* in 19 of 47 cases. At
30-second board cadence and 60-second GeckoTerminal candles, a 26-second lead is **below the
resolution of every price source this desk has**, before friction (~2.4% at $2.45 clips) is
considered at all. It is not a trade.

---

## 8. Information gain, taken literally

Temporal split, mint never straddles, mint-clustered CIs, base rate stated, and "bits" = mean
log-loss improvement over the train-period base rate, on the test set.

**Only the board-priced arm is pinned.** GeckoTerminal coverage is still being collected in the
background — it went 119 → 181 cohort mints *during this session* — so the GT arm's cohort grows
between runs and its numbers move with it (free+flow at 8 h read 0.847, 0.839, 0.774 and 0.781 across
four runs as coverage grew from 119 to 191 mints). The board arm is byte-stable at 314 rows / 222 mints and is the
one to quote; the GT arm is reported as a coverage-sensitive cross-check, not a result.

**1 h, board pricing** (train 164/117 mints, test 150/105, base rate 0.227, base-rate loss 0.791 bits):

| model | AUC [95% CI] | AUPRC | bits/row |
|---|---|---|---|
| free columns | **0.796** [0.695, 0.884] | 0.504 | +0.0868 |
| callout columns | 0.471 [0.354, 0.561] | 0.219 | −0.1231 |
| **on-chain flow** | **0.758** [0.635, 0.860] | 0.489 | **+0.0955** |
| free + callout | 0.665 [0.557, 0.765] | 0.335 | −0.0510 |
| free + flow | 0.790 [0.677, 0.880] | **0.533** | +0.0948 |
| free + flow + **caller-wallet identity** | 0.781 [0.661, 0.882] | 0.526 | +0.1037 |

**8 h, board pricing** (train 77/54 mints, test 62/47, base rate 0.129, base-rate loss 0.566 bits):

| model | AUC [95% CI] | AUPRC | bits/row |
|---|---|---|---|
| free columns | 0.625 [0.410, 0.918] | 0.391 | −0.0238 |
| callout columns | 0.385 [0.216, 0.582] | 0.116 | −0.1553 |
| **on-chain flow** | **0.764** [0.506, 0.943] | 0.460 | **+0.0711** |
| free + callout | 0.549 [0.386, 0.794] | 0.195 | −0.1927 |
| free + flow | 0.748 [0.558, 0.924] | 0.362 | +0.0322 |
| free + flow + **caller-wallet identity** | 0.745 [0.556, 0.924] | 0.361 | +0.0267 |

The GT-priced arm at the same moment (352 rows / 248 mints, test 73/55, base 0.123): free 0.769,
callout 0.588, flow 0.755, free+flow 0.781 (+0.0599 bits), free+flow+identity 0.767. Same
ordering, different level, and the level is a statement about coverage.

Three readings.

**Identity adds nothing.** ΔAUC = **−0.0086** at 1 h and **−0.0023** at 8 h on the pinned arm,
and −0.014 on the GT arm. The linked-wallet feature is fitted on the *train period only* and
applied forward, as it must be; it fires on 13 of 150 test rows at 1 h. This is the operator's
question answered in the operator's units, and the answer is zero.

**Anonymous flow is a real substitute for the free columns, and at 8 h it beats them.** Flow alone
scores 0.758 at 1 h and 0.764 at 8 h against the callout block's 0.471 and 0.385, and at 8 h it is
the only block with a positive bit count (+0.0711 where the free columns give −0.0238). Nulls:
i.i.d. label shuffle 0.478, label rotation 0.489, and permuting the flow block alone drops
free+flow from 0.790 to 0.727 (p = 0.04 at the 24-draw floor).

**One column does most of it, and it is the choreography column.** `recycled_30m` — the share of
the last half hour's buying that is already sold back — is the best single flow column in **all
four** configurations, and at 8 h it beats every fitted model in the study:

| | boards 1 h | boards 8 h | GT 1 h | GT 8 h |
|---|---|---|---|---|
| `recycled_30m` alone | 0.754 | **0.824** | 0.647 | 0.723 |
| runner-up | `sell_buy_10m` 0.653 | `log_buyvol_10m` 0.725 | `log_buyvol_10m` 0.579 | `log_buyvol_10m` 0.700 |

That is the same shape as `RESULT_llm_filter.md`'s plain drawdown column beating nine arms of
verbalised judgement, and `RESULT_callout_edge.md`'s `log_mcap` beating every fitted model at
8 h. It is also the honest home of §2's finding: the buy→sell recycling is real and it is
predictive — it just is not *the caller's* buy→sell.

**The 0.796 reference is fragile to the pricing instrument, not just to the model.** On the
GeckoTerminal-priced cohort — 352 rows against 314, because GT coverage grew from 29 mints when
`RESULT_callout_edge` ran to 191 now — the same free columns score **0.676 at 1 h**. Boards drop
coins that stop trading; GT prices them. The 0.796 is a survivorship number and should be quoted
as **0.63–0.80 depending on who gets priced**, exactly as that study's §4 warned in the return
domain. At 8 h the ordering reverses (0.769 GT vs 0.625 boards) because administrative censoring
bites the two cohorts differently. Both are in the table; neither is hidden.

---

## 9. Trials, spend, and limits

**Configurations evaluated:** 7 column sets × 2 price sources × 2 horizons = **28** in §8, plus 2
pre-buy windows × 22 callers in §3 (reported under BH-FDR, and the discarded hypergeometric
formulation is disclosed rather than buried), plus 3 flow contrasts × 4 nulls in §2, plus 4 join
routes and the taxonomy counts. Call it **~45 substantive configurations**. PROGRAM.md §3.9 says past ~7 an in-sample
Sharpe of 1 is an out-of-sample zero, which argues for the nulls and against the one marginal
positive. Everything offered as real here is either a null (identity), or large and consistent
across both horizons and both price sources (flow), or a structural count that needs no model at
all (the join yields, the 51.4%, the 161-wallet burst).

**Spend:** $1.12 of BigQuery (191.2 GB + 5.4 GB preflight, dry-run first, capped). $0 of Apify —
the census was already bought. ~780 pump.fun API calls, free, browser-UA, ≥150 ms apart.

**Limits, stated plainly:**

- **One 10-hour window on one day**, inherited from the callout census. Regime shift here is
  measured in weeks.
- **The on-chain pull starts 2026-08-14 00:00 UTC**, so for the 80 of 276 cohort coins created
  before it the pre-history is truncated. Every callout still has ≥14 h of prior on-chain tape,
  so minute-scale choreography is unaffected; a "bought three days ago" bagholder is invisible
  by construction, and the bagholder-evangelist class is therefore *undercounted* here.
- **176 of 321,295 (mint, wallet) rows hit the 500-trade cap** in the extraction query. They are
  high-frequency bots; their trade counts are exact, their tails are truncated.
- **SOL legs are not in token balances.** Every volume statement is in token base units,
  normalised per mint. No SOL amount in this document is inferred, because none is measured.
- **§5 rests on 15 wallets and §4's sell timing on 11 events.** They are leads.
- **§7 and the GT arm of §8 move between runs** while `callout_prices.py` keeps collecting. The
  board arm of §8 was byte-identical across four runs and is the one to quote.
- The taxonomy's "single call" bucket — 119 accounts, 25.9% of the feed — **cannot be classified
  from one tweet**. The 51.4% automated share is a floor on the machine fraction, not an estimate
  of it.

---

## 10. What follows

1. **Stop trying to join handles to wallets.** Four routes, ~$0 spent, and the best of them
   reaches 3.4% by identity. The native link is dead and the temporal join is dominated by
   crowds. Any future "follow the KOL wallet" idea should be costed against this section first.
2. **Build the flow columns into whatever the callout feed feeds.** `recycled_30m`,
   `log_buyers_60s`, `swarm_ratio` and friends are computable from the pumpportal firehose in
   real time, need no identity, need no X, and at 8 h they beat every other block measured on
   this population. That is the concrete carry-forward.
3. **The 161-wallet burst is the object worth naming.** A coordinated buy of that size inside a
   minute is detectable live and precedes the public callout by ~26 s. This study cannot say
   whether the burst itself predicts return — it was measured as a *precursor to tweets*, not as
   a signal — and that is the obvious next experiment, on the full firehose rather than on the
   273 coins that happened to get tweeted about.
4. **Re-price `RESULT_callout_edge.md`'s AUC 0.796 as 0.63–0.80** and let the GeckoTerminal
   collector finish. The instrument, not the model, is the widest source of uncertainty in both
   studies — the GT arm moved 0.847 → 0.781 inside a single afternoon purely from coverage
   filling in, which is larger than every model difference in §8, while the board arm was
   byte-identical across all four runs.
5. **Do not build a caller-wallet copy strategy.** There is nothing to copy. This is the result.
