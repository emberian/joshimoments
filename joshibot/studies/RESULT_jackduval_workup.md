# RESULT: jackduvalcalls — the watch, and what the wallet turned out to be

Operator tasking, verbatim: *"we need to be watching his wallet."*

This file has two halves. The first is the **instrument**: what it took to actually watch him,
including two defects that would have made the watch silently useless. The second is the
**measurement**: what the wallet does.

Status of each claim is marked. Nothing here is a recommendation to trade.

---

## 0. The one-paragraph answer

**He is being watched, and he turned out to be a sub-minute sniper rather than a caller who
holds.** `BAr5csYt…` is now live on `accountTrade` — which required fixing a defect that sent one
key list to both trade feeds (wallets offered as coins, answered with permanent silence) and a
second where the free `newToken` feed masked the metered feeds dying. **Contrary to the prior
from `RESULT_caller_wallets.md` §1**, his pump.fun profile wallet *is* his trading wallet:
**2,637 transactions over ten days across 494 coins, median hold 45 seconds**, 53.5% of positions
closed inside a minute and 90.9% inside an hour. Ninety seconds after the subscription went up it
caught a whole round trip — into a coin **14 seconds after it was created**, out 58 seconds later,
2.596 SOL in and 3.025 out, reconciling to the decimal. **In its first hour the watch recorded
four complete round trips, all four profitable and all four under a minute: +0.7276 SOL on 7.116
SOL deployed.** That sample cannot hide losers — `accountTrade` reports every trade the wallet
makes — but four is four, and it shows the shape rather than an edge.

**But he is not a callout account, and he loses money.** In two weeks he posted **475 tweets and
exactly five contract addresses** — 408 of the 475 are replies. And over ten days the wallet ran
**1,229 FIFO round trips at a 17.7% win rate, median round-trip return −40.6%, −179.65 SOL
total**. His bio says *"never wrong, always early."* He is early; he is wrong 82% of the time.
Three further wallets trade **99% of their coins in the same second as his buys** (a universal
sniper control answers 1.4%), so he is not operating alone — though "his own wallets" and "a copy
bot that only follows him" are not separable here.

Three things the operator should take from that. **He never touches your coins** — nosis, weave,
DREGG and SOLVE appear zero times in 106M transactions, and he has never posted about them
either; the only trace in either direction is two strangers pitching `$nosis` *at* him. **The
horizon is wrong everywhere else**: any 1 h / 8 h framing of his calls measures something he has
already exited many times over. And **the homoglyph is an identity attack, not a trading one** —
it follows a roster of eight big callers, picked him on 2026-08-04 and renamed itself on
2026-08-09, but its median hold is 46 minutes against his 45 seconds and their four shared coins
are hours to days apart, which is nowhere near close enough to be trading against him.

Two corrections worth carrying. **His X handle is `@jackduval`, not `@jackduvalcalls`** — the
latter is only his pump.fun username and is not an X account at all. And **`fatdogwithhat` and
`calico` were not found** in either his tweets or his 493 coins, most likely because three coins
of that name were minted *today* after both tapes end — so **the X arm is unvalidated against the
two calls the operator named, and closing that needs the mint address from the operator.**

---

## 1. The instrument, and the two ways it was lying

### 1.1 One key list for two different kinds of address

`shitcoims_scalper/firehose.py` held a single `keys` list and sent it to **both** metered
subscriptions. That is wrong in a way nothing reports:

* `subscribeTokenTrade` keys are **mints** — "tell me about these coins".
* `subscribeAccountTrade` keys are **wallets** — "tell me about these traders".

Subscribing to both therefore offered each feed the other's addresses. The vendor accepts it:
a wallet is a well-formed base58 address, there is simply no coin by that name, so it answers
by saying nothing — forever, and **indistinguishably on the tape from a coin nobody traded**.
The module exists to abolish exactly that ambiguity and had reintroduced it one layer up, in
the subscription rather than in the recording of it.

The pre-existing test asserted the bug verbatim as expected output:

```python
keys=("MintOne", "WalletTwo"),
...
{"method": "subscribeTokenTrade",   "keys": ["MintOne", "WalletTwo"]},
{"method": "subscribeAccountTrade", "keys": ["MintOne", "WalletTwo"]},
```

Fixed in `b432d26`. Keys are per method everywhere; `Feed.key_kind` names what a key denotes;
`parse_keys` accepts `accountTrade=…` qualified form and a bare list **only** when exactly one
keyed feed is subscribed, refusing the ambiguous case with a message that names the fix. Every
key must decode to 32 bytes, so a typo fails at startup rather than masquerading as a quiet
market. `watch_open` now carries the subscription manifest, because *"were we listening?"* is
only half the question once a subscription has keys.

**This was load-bearing, not hygiene.** The operator's request needs `accountTrade` on a wallet
while `tokenTrade` already carries the four cluster mints. Under the old code that combination
was unexpressible.

### 1.2 The metered feeds could die without the liveness clock noticing

`subscribeNewToken` delivers ~30 events/min unconditionally, and every one reset the shared
staleness timer. So if the keyed subscriptions died — exhausted funded key, a stream the vendor
dropped — the tape stayed green forever while the wallet watch was dead. Free-feed traffic
masked metered-feed silence completely.

Fixed in `aff57a9`: an independent clock over trade rows emits `metered_stale` when the keyed
feeds go quiet while other feeds keep arriving. Armed only when a keyed feed is subscribed.
Default 1800 s, far longer than the general 120 s, because a watched wallet legitimately does
nothing for hours — this catches a *dead subscription*, not a quiet one.

Verified live: armed at 20 s, it fired at 20 s and again at 40 s while the free feed delivered
9 then 17 events. Under the old code that run was indistinguishable from healthy.

**Stated limit, honoured in the threshold:** this cannot separate "the subscription died" from
"nobody traded" for any single key. It says the metered stream *as a whole* has gone quiet,
which is actionable only because the same subscription also holds actively-traded coins.

### 1.3 Cost of the watch, measured

~3.6 trade events/min on the current subscription → **~5,200 metered events/day**. A 10k-event
funded-key allowance lasts **~46 hours**. The key needs topping up roughly every two days, and
§1.2's alarm is what catches the far side of forgetting.

### 1.4 What is running now

`ops/com.shitcoims.firehose.plist`, live and supervised:

* `tokenTrade` ← the four cluster mints (nosis, weave, DREGG, SOLVE)
* `accountTrade` ← `BAr5csYt…` (jackduvalcalls) and `9T8QKsR2…` (the homoglyph)

Both keyed subscriptions were accepted by the live socket with the funded key. The restart
recorded an honest 8.1 s gap.

**Venue coverage, checked because it would have silently bounded everything:** the feed carries
**both** venues — 203 `pump-amm` rows against 5 `pump` bonding-curve rows in the first sample.
All four cluster coins have migrated (`complete: true`) and trade on AMM pools, so a
bonding-curve-only feed would have shown nothing for them. It does not.

---

## 2. Which wallet is his, and the twelve others wearing his name

`/users/search?searchTerm=jackduval` returns **thirteen** profiles. The identification is
decisive, but **not because the name matches** — it is follower mass:

| profile | wallet | followers | username set at |
|---|---|---|---|
| **jackduvalcalls** (X: **@jackduval**) | `BAr5csYt…XJPh` | **17,468** | never renamed |
| jackduvalll | | 20 | — |
| jack_duval | | 13 | 2026-02-08 |
| jackduvalstocks (same X display name — possibly also his, see §5) | | 13 | 2025-09-18 |
| **jackduvalcalIs** (capital I) | `9T8QKsR2…ijvP` | 9 | **2026-08-09 12:22** |
| …8 more | | 0–2 | |

The real account holds **17,468 of the namespace's 17,529 followers — 99.65%**. Eleven of the
twelve others are ordinary squatting, several predating the real account by months, and are
deliberately **not** labelled adversary; nothing connects them to it.

`x_username` is null on all thirteen, so `RESULT_caller_wallets.md` §1's route 2 — the
platform's own X link — remains dead, and none of this rests on a platform-asserted link.

### 2.1 The homoglyph picked its target before it dressed up

Two API timestamps turn the imposter from an oddity into a sequence:

* **2026-08-04 11:12 UTC** — it follows the real `jackduvalcalls`.
* **2026-08-09 12:22 UTC** — it sets its username to the capital-I homoglyph, five days later.

It follows exactly **nine** accounts, **eight of them large callers** totalling ~169k followers:
slingoor (45,044), daumen (30,347), nyhrox (24,651), jeets (24,177), jackduvalcalls (17,468),
mdudas (14,225), pxblocito (11,351), chudthebuilder (1,617), plus kobecoin1 (74).

Read as a **shortlist** — that reading is inference and is labelled as one — the other seven are
candidate next impersonations, and a homoglyph of any of them should be treated as this same
actor until shown otherwise.

The real `jackduvalcalls` **follows nobody** (`following: 0`). So "follows a roster of big
callers" is itself a discriminator between the impersonator and the impersonated.

Both wallets are in `wallet_labels.yaml`, on-curve verified, confidence `inferred`.

---

## 3. The wallet trades, and that reverses the prior expectation

`RESULT_caller_wallets.md` §1 established that a caller's pump.fun *profile* wallet is almost
never their trading wallet — the handle→wallet join succeeds by identity for 5 of 146 handles,
and the platform's native `x_username` link is dead on all 317 wallets probed. The reasonable
prior was therefore that `BAr5csYt…` would show **nothing**, and that a null there would be the
finding.

That prior is **wrong for this caller.** Over the free local ten-day corpus
(`state/bulk_pump/daily/*.parquet`, 106M transactions, 2026-08-05 → 2026-08-14):

| day | jackduvalcalls | imposter |
|---|---|---|
| 2026-08-05 | 135 | 2 |
| 2026-08-06 | 255 | 0 |
| 2026-08-07 | 119 | 80 |
| 2026-08-08 | 218 | 13 |
| 2026-08-09 | 241 | 88 |
| 2026-08-10 | 286 | 9 |
| 2026-08-11 | 183 | 26 |
| 2026-08-12 | 116 | 4 |
| 2026-08-13 | **812** | 4 |
| 2026-08-14 | 272 | 0 |
| **total** | **2,637** | **226** |

His profile wallet is a **heavily active trading wallet** — ~264 transactions/day. And the
imposter is **not inert either**: 226 transactions, with its two busiest days 08-07 and 08-09.
08-09 is also the day it adopted the homoglyph; that is a same-day coincidence and is **not**
read as causation here.

### 3.1 What the ten days contain: 494 coins, median hold 45 seconds

Unpacking his token-balance legs from the same corpus — **2,817 legs across 494 distinct
mints** — gives the shape of the operation:

One of the 494 is **USDC** (`EPjFWdd5…TDt1v`, 180 legs) — a cash balance, not a traded
position, and it is excluded below. Every one of the remaining **493 ends in `pump`**: he
trades pump.fun coins and nothing else.

| span between his first and last balance change on a coin | 493 coins |
|---|---|
| p10 | 0 s |
| **median** | **45 s** |
| p90 | 2,968 s (49 min) |
| max | 230,388 s (2.7 d) |
| under 60 s | 264 / 493 = **53.5%** |
| **under 120 s** | **309 / 493 = 62.7%** |
| under 600 s | 390 / 493 = 79.1% |
| under 1 h | 448 / 493 = **90.9%** |

**He is a systematic sub-minute scalper across ~50 coins a day** — 46, 49, 40, 50, 45, 55, 48,
21, 118, 50 distinct coins on the ten days. **70.0% of his coins reach a zero balance**, i.e. he
fully exits most of what he touches. The 58-second round trip in §4 is not an anecdote: 45 s is
the *median*, and the live capture landed almost exactly on it.

*Measurement note:* this span is first-to-last balance change per coin, a proxy for hold time
and not a settled position lifetime. `p10 = 0` is coins touched in a single transaction. The
tail is real — the longest position runs 2.7 days — so "scalper" describes the mass of the
distribution, not every trade. An earlier pass of this section quoted a 9.6-day maximum; that
was the USDC balance, and excluding it is the correction.

### 3.2 He has never touched the operator's coins

| cluster coin | balance legs in 10 days |
|---|---|
| nosis | **0** |
| weave | **0** |
| DREGG | **0** |
| SOLVE | **0** |

**He never called them either.** `RESULT_cluster_callers.md` enumerates every account that called
these four coins over their full lives; **none of its 487 distinct authors contains "duval"**. He
neither trades the operator's coins nor posts about them.

What the census *does* contain is the other direction: **two tweets, by @chiikawaofiicia and
@KCUFATAW, @-mentioning `@jackduval` about `$nosis`** — *"@jackduval @Tradermayne $nosis How
about this coin?"* (2026-08-11) and *"@jackduval $nosis → $dickcoin"* (2026-08-13). People pitch
the operator's coin *to* him. He does not bite.

*Those two rows resolved the identification.* They mention **`@jackduval`**, not
`@jackduvalcalls` — which turned out to be the real X handle. §5 has the confirmation and why it
mattered.

Zero, across 106M transactions and 494 of his own mints. Whatever relationship the operator has
with this caller, it does **not** run through the operator's own coins, and there is no evidence
here of him trading against them. This also matches the venue split in §1.4: he lives on
**fresh bonding-curve launches**, and all four cluster coins have long since migrated to AMM
pools.

### 3.3 The imposter does not trade against him — a null, and the null is the finding

The hypothesis worth testing was that `9T8QKsR2…` snipes or dumps into the real caller's flow:
wear his name, ride his followers. Run against the same corpus, it does not survive.

| | jackduvalcalls | imposter |
|---|---|---|
| balance legs | 2,817 | 457 |
| distinct mints | 494 | **45** |
| **median hold span** | **45 s** | **2,749 s (46 min)** |
| under 120 s | 62.7% | **7 / 45 = 15.6%** |
| the operator's four coins | 0 | **0** |

**They are not the same kind of trader.** A 45-second median against a 46-minute one is two
different operations; the imposter is not a scalper at all.

**Coins both wallets touched: 5 — and one is USDC**, leaving **four** real overlaps. Their
timing settles it:

| offset of imposter's first touch vs the caller's | |
|---|---|
| −87,290 s | imposter first, by **24 hours** |
| −4,069 s | imposter first, by 68 minutes |
| +614 s | caller first, by 10 minutes |
| +39,935 s | caller first, by 11 hours |

**Sniping and dumping-into-flow are second-scale acts.** These offsets are hours and days. On
this corpus the imposter never lands close enough to the caller's trades to be trading against
them.

*The null this deliberately does not lean on.* Four shared coins out of 45 and 494, against a
ten-day universe of roughly 58,000 launches, is ~10× a naive independence expectation of 0.4 —
and that naive number is worthless here, because neither wallet draws uniformly from all
launches. Both select for coins that are getting attention, which shrinks the effective universe
by orders of magnitude and inflates overlap for free. This repo has had a naive null manufacture
an effect three separate times (`RESULT_flow_signals`; `RESULT_copytrading` 73× → 0.98×;
`RESULT_caller_wallets` §2.1, 20× → 1.20×). So the overlap count is reported and **not**
interpreted; the **timing** is what carries the conclusion, and it needs no null at all.

**Verdict: the impersonation is an identity attack, not an on-chain predation pattern** — on
this ten-day window. It remains a live hazard for exactly the reason it was labelled
`adversary`: the risk is that a human reads `jackduvalcalIs` as `jackduvalcalls` and acts on it.
That risk does not require the wallet to do anything at all.

---

## 4. A complete round trip, caught live

Ninety seconds after the `accountTrade` subscription went live, it captured an entire position
from entry to exit. From `state/firehose/trade/2026-08-15.jsonl`:

Coin `WBQmYhEA61fCeiQjQhSuodcLSDA2YtrNPbSB5UvJYdg` (symbol 😭, name "sob"), **created 17:08:28**.

| t (UTC) | side | tokens | SOL | balance after |
|---|---|---|---|---|
| 17:08:42.255 | buy | 18,619,587.87 | 1.040156 | 18,619,587.87 |
| 17:08:49.740 | buy | 24,170,434.59 | 1.060220 | 42,790,022.46 |
| 17:08:52.506 | buy | 4,946,168.34 | 0.258133 | 47,736,190.80 |
| 17:08:52.508 | buy | 4,402,362.99 | 0.237817 | 52,138,553.80 |
| 17:09:40.234 | **sell** | 52,138,553.80 | 3.025385 | **0** |

* First buy landed **14.3 seconds after the coin was created**.
* **2.596326 SOL in, 3.025385 SOL out — +0.429059 SOL, +16.53% gross.**
* **Total hold: 58 seconds.**

**It reconciles exactly.** Tokens bought equals tokens sold to the decimal (52,138,553.7988),
and the balance walks to zero, so this is a complete self-contained position with nothing
predating the subscription. The P&L is on **vendor-rounded floats**, which this desk's own
firehose docstring says are good for ranking and triage and not for accounting — so read
+16.53% as a magnitude, not a settled figure. Fees are not included.

### 4.1 One hour of the watch: four round trips, four winners

By 18:05 UTC — one hour of subscription — the tape held **four complete, fully-exited round
trips**, every one of them sub-minute:

| coin | SOL in | SOL out | net | hold |
|---|---|---|---|---|
| `WBQmYhEA…` | 2.5963 | 3.0254 | **+0.4291** | 58 s |
| `DGHaiWyp…` | 1.4303 | 1.4784 | **+0.0481** | 26 s |
| `Foz4nbfG…` | 1.3812 | 1.5683 | **+0.1871** | 32 s |
| `7MK1dXbn…` | 1.7082 | 1.7716 | **+0.0633** | 43 s |
| **total** | **7.1160** | **7.8437** | **+0.7276** | median 37.5 s |

**Four for four, +0.7276 SOL in an hour**, every position closed to a zero balance, holds of 58 /
26 / 32 / 43 seconds against the corpus median of 45 s.

**This sample is unbiased in the one way that matters.** `accountTrade` reports *every* trade by
the subscribed wallet, so losers cannot be hidden from it — and no `metered_stale` alarm fired,
so there is no silent gap in which losses could have gone unrecorded. That is a different and
much stronger position than the survivorship traps this repo keeps finding elsewhere.

**It is still n = 4, over one hour, on vendor-rounded floats, with fees excluded.** Four
consecutive winners is entirely achievable by luck, and nothing here establishes an edge — only
that in this hour he did not lose. What it does establish firmly is the *shape*: he takes
1.4–2.6 SOL positions into brand-new coins and is flat again inside a minute.

What it establishes: he snipes **brand-new bonding-curve launches within seconds** and exits
inside a minute. All 5 of his captured rows are `pool: "pump"` (bonding curve), while all four
cluster coins trade `pump-amm`. He operates in a different market from the operator's coins.

**Consequence for how he should be scored:** a 1 h / 8 h forward-return framing — the horizon
`RESULT_callout_edge.md` uses for the callout population — is very likely the **wrong
instrument** for this caller. Whatever he is doing happens inside the first minute.

---

## 5. He is not a callout account, and the wallet loses money

### 5.1 The social feed: 475 tweets, five contract addresses

His X handle is **`@jackduval`** (51,738 followers), not `@jackduvalcalls` — the latter is only
his pump.fun username and **is not an X account at all**: it returns zero on every query shape,
while `from:jackduval` returns 100 in the same session. This is `RESULT_caller_wallets.md` §1
route 1 exactly — `searchTerm` fuzzy-matches *pump.fun* usernames, so a near-miss was always the
expected failure mode. Found for $0 by matching the bio string *"never wrong, always early."*

Census: **475 tweets, 2026-08-01 → 2026-08-15**, 55 slices, 0 capped, 0 failed. Bounded-query
recall was **measured at 100%** against an unbounded pull (7/7, no misses), so what follows is his
behaviour and not collection loss:

| | |
|---|---|
| replies | **408** |
| quotes | 36 |
| original tweets | 31 |
| **tweets carrying a contract address** | **5** |
| tweets carrying a cashtag | 5 |

**He is not a callout account.** Eighty-six percent of his output is replies, and in two weeks he
posted five contract addresses. Whatever the operator is following him for, it is not a stream of
calls — the name `jackduvalcalls` describes a pump.fun profile, not the behaviour.
`@jackduvalstocks` returns zero and is dormant, not a second mouth.

**`fatdogwithhat` and `calico` do not appear** — not in the 475 tweets and not among the 493
coins his wallet touched. This is most likely **coverage, not identity**: three separate coins
named `fatdogwithhat` were minted *today* between 16:47 and 16:56 UTC, after both the corpus
(ends 08-15T00:00Z) and the census (ends 15:15Z). **The X arm is therefore unvalidated against
the operator's two named calls**, and "the fatdogwithhat call" does not identify a mint. *This
needs the address from the operator to close.*

### 5.2 The wallet loses money — 82% of his round trips are losers

Ten days, free corpus, SOL derived from the curve identity rather than a vendor float:

| | |
|---|---|
| priced trades / coins | 1,794 / 481 |
| SOL bought / sold | 1,321.74 / 1,183.30 |
| buy clip p10 / median / p90 | 0.197 / **0.474** / 1.617 SOL |
| FIFO round trips | 1,229 |
| hold p10 / median / p90 | 5 / **56 s** / 3,073 s |
| **win rate** | **17.7%** (218 / 1,229) |
| **median round-trip return** | **−40.6%** |
| closed P&L | −215.18 SOL |
| open position, exit-priced | 159.50 vs 123.98 SOL cost |
| **total, 10 days** | **−179.65 SOL** |

His bio says *"never wrong, always early."* He is early. He is wrong **82%** of the time.

**The sign of that total is marking-dependent, and the honest version is the pessimistic one.**
Marking his open lots at the **marginal** price gives **+950 SOL** and flips the conclusion;
marking them at what selling would actually collect (curve integral, including his own impact)
gives −179.65. The latter is correct — you cannot exit a bonding-curve position at the marginal
price — but the reader should know the number moves that far. **The win rate and the −40.6%
median are marking-independent**, and they are the robust facts.

Also separated out: **568 of his legs are transfers, not trades** (174 outbound). He tweets that
he airdrops supply to TikTok creators and pays $200–$300 per video. On a balance delta alone a
gift is indistinguishable from a sale; they are told apart by whether the bonding curve moved in
the same transaction.

### 5.3 The tension with §4.1, stated rather than smoothed

§4.1's live hour was **4 round trips, 4 winners**. Against a 17.7% base rate that is roughly a
1-in-1,000 hour. Both numbers are reported because both were measured; the disagreement is not
resolved here. Candidate explanations, none verified: different SOL accounting (PumpPortal vendor
float vs the curve identity), different unit (per-coin net vs FIFO legs — 1,229 round trips across
481 coins means ~2.5 legs per coin, and a coin can net positive while containing losing legs), and
different windows (one hour today vs ten days ending 08-15T00:00Z). **Weight the ten-day number**:
it is 1,229 round trips against 4.

### 5.4 Forward returns at his entries

n = 350, censored rows marked and never dropped. Median return from his entry price:

| horizon | 60 s | 5 m | 1 h | 8 h |
|---|---|---|---|---|
| median | **−18.6%** | −53.0% | −66.8% | −69.8% |
| win rate | 40.3% | | | 7.1% |

These include his own price impact, which is right for the copy question ("what would I get
following him") and wrong for "what did the coin do".

### 5.5 Wiggle vs ambient — a clean null

The operator's actual use for a caller is as a marker of **harvestable oscillation**, not of
forward return. That hypothesis was tested and it fails.

The instrument was validated first: the ambient arm reproduces `RESULT_callout_volatility.md`
§5.1 to the digit (337 rows; `wiggle_net_1h` median 0.42942 vs published 0.4294;
`log_two_sided_1h` 3.5264 vs 3.5264).

Conditional on log-mcap and log-age his entries beat ambient on `log_two_sided` at every horizon
(z = 3.88–6.72). **Both structure-preserving nulls kill it**: observed max |z| = 6.722 over the
declared 13-cell family, against a forward-shift null median of **7.61 (p = 0.71)** and a
matched-coin swap null median of **7.17 (p = 0.91)**. Both nulls carry the full 144 rows.

**His entry instants are not more harvestable than the ambient callout stream.** Two earlier null
specifications were discarded and are disclosed: a symmetric shift left 8 rows and a grid-binned
swap left 36 — he buys coins *seconds* old, so any null that moves him backwards in time empties
the arm by construction.

### 5.6 Buy → tweet → sell: cannot be seen, and that is not exculpation

All 5 of his calls are on coins he traded, but **4 predate the corpus**, so any pre-tweet position
is invisible by construction. Within the tape his first buys land *after* the tweets. **This is
truncation, not evidence of innocence**, and it is the one question the operator most wanted
answered. It needs a corpus that reaches back further, or forward collection from today.

### 5.7 Three wallets that appear to exist only to trade alongside him

The temporal join found candidates; the **crowd check** (`RESULT_caller_wallets.md` §4's lesson)
says a median of 37 wallets — p90 232 — sit in the same 60 s pre-band, so overlap alone proves
nothing. What decides it is **breadth**: scanning each candidate against the whole ten-day corpus.

| wallet | pump coins in 10 d | of them, his | same-slot with his buys | same-transaction |
|---|---|---|---|---|
| `6Eegkyd2qNzxSzZz3PH3jiDyqL5HFcHdcsb9zfMzWHKB` | 355 | **352 (99.2%)** | 925 | 0 |
| `DkWzWsQT9ZThfkFfdZqzNT59dZMiJXp81oob8QBG9UcT` | 342 | **338 (98.8%)** | 892 | 0 |
| `D7xK1ZLz8KQNWN8aU1jbzNAuT5xwqgFrCUUYodVU4G42` | 276 | **275 (99.6%)** | 656 | 0 |
| `FBvxneTq8dY7WKxj924CseuveWzDL5tN9JuSW3S9nJkN` *(control)* | 17,908 | 247 (**1.4%**) | 93 | 0 |

All on-curve, no pump.fun profiles. Median offset from his buy is **+0 s** — the same second on
259 / 247 / 175 of the shared coins — in **separate transactions in the same slot**, i.e. a
bundle, not one transaction funding several wallets.

The fourth row is the control that makes the first three mean anything: a universal launch sniper
that touches 17,908 coins answers **1.4%**. Three wallets answering 99% are not sampling the
market, they are sampling *him*.

**This does not separate "his own wallets" from "a copy bot that follows only him."** Confidence
`inferred`, never higher. The permutation p is weak (325 of 350 donor matches ran at the widest
level) — **the 99% is the evidence and it needs no null**.

#### 5.7.1 The slot-offset profile, and why "same slot" is the wrong test

Joining each wallet's buys to his, per shared coin, over ±4 slots:

| d_slot | −4 | −3 | −2 | **0** | +2 | +3 | +4 |
|---|---|---|---|---|---|---|---|
| `6Eegkyd2…` (n=2,639) | 5.8% | 5.3% | 4.9% | **52.8%** | 4.9% | 5.2% | 5.4% |
| `DkWzWsQT…` (n=2,511) | 6.0% | 5.5% | 4.9% | **53.1%** | 4.5% | 4.9% | 5.3% |
| `D7xK1ZLz…` (n=2,037) | 6.6% | 6.1% | 5.4% | **48.9%** | 5.0% | 5.8% | 5.8% |
| **control** `FBvxneTq…` (n=262) | 7.3% | 8.0% | 5.0% | **42.7%** | 6.1% | 6.5% | 3.8% |

**The control sits at 42.7% too.** A universal launch sniper that shares 1.4% of its coins with him
concentrates at the same slot almost as hard as the three candidates do — because *everyone racing
a new coin lands in the same few slots*. **Same-slot co-occurrence measures launch-sniping, not
coordination**, and a detector built on it would mostly detect the former. What separates the three
is breadth (99% vs 1.4%), which is timing-free.

Two further shape facts. The profiles are **symmetric** — d = −1 and d = +1 are equal to within a
few counts (208/208, 200/197, 167/166) — which argues *against* "reactive copy bot", since a copier
lags and would show a one-sided positive tail. And same-slot `tx_index` offsets are spread across
±1…±3 rather than tightly consecutive, so this is **not one atomic Jito bundle**; it is a fleet
firing into the same slot. Co-scheduled, not chained.

This is the empirical basis for `studies/bundle_hypothesizer.py`: rank linkage channels by how
expensive they are to *evade*. Timing is cheap to jitter; which coins you must trade is not.

---

## 6. Limits

* **§4.1 is n = 4 round trips over one hour**, on vendor floats, fees excluded. Four consecutive
  winners is well within luck. The sample cannot hide losses (accountTrade reports every trade,
  and no `metered_stale` alarm fired) but it is far too small to claim an edge.
* **The corpus ends 2026-08-14**; today is covered only by the live firehose tape. Two sources,
  adjacent windows.
* **Counts in §3 are token-balance touches**, not classified buys/sells — a transaction
  touching his wallet is not necessarily a discretionary trade of his, and §3.1's spans are
  first-to-last balance change per mint, a proxy for hold time rather than a settled position
  lifetime.
* **§3.2's zero is a zero on this corpus** — ten days, 2026-08-05 → 2026-08-14. It cannot speak
  to DREGG's first forty days, which predate the window.
* **The namespace census is one query on one day.** Handles are cheap to mint; thirteen today
  is not thirteen next week.
* **Nothing here prices his calls.** No forward returns, no wiggle measurement, no null. This
  file is the instrument plus the wallet's shape; the scoring is §5.
