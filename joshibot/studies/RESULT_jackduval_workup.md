# RESULT: jackduvalcalls — the watch, and what the wallet turned out to be

Operator tasking, verbatim: *"we need to be watching his wallet."*

This file has two halves. The first is the **instrument**: what it took to actually watch him,
including two defects that would have made the watch silently useless. The second is the
**measurement**: what the wallet does.

Status of each claim is marked. Nothing here is a recommendation to trade.

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
| **jackduvalcalls** | `BAr5csYt…XJPh` | **17,468** | never renamed |
| jackduvalll | | 20 | — |
| jack_duval | | 13 | 2026-02-08 |
| jackduvalstocks | | 13 | 2025-09-18 |
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

**n = 1.** One round trip is an existence proof, not a distribution.

What it establishes: he snipes **brand-new bonding-curve launches within seconds** and exits
inside a minute. All 5 of his captured rows are `pool: "pump"` (bonding curve), while all four
cluster coins trade `pump-amm`. He operates in a different market from the operator's coins.

**Consequence for how he should be scored:** a 1 h / 8 h forward-return framing — the horizon
`RESULT_callout_edge.md` uses for the callout population — is very likely the **wrong
instrument** for this caller. Whatever he is doing happens inside the first minute.

---

## 5. Open, and owned elsewhere in this session

The decisive question this workup raises and does **not** yet answer:

> **Does he tweet the coins he is holding, during the hold?**

If a call goes out between his buy and his sell, his followers are his exit liquidity. That
needs the X census joined to these trade times — for each call, the signed offset from buy to
tweet and from tweet to sell. Pending.

Also pending: whether `BAr5csYt…` is his *only* wallet (temporal join against a time-matched
null, per `RESULT_caller_wallets.md` §3 — and note §4's lesson that the one link that survived
there turned out to be a 161-wallet crowd, not a person).

---

## 6. Limits

* **§4 is n = 1**, live, and on vendor floats.
* **The corpus ends 2026-08-14**; today is covered only by the live firehose tape. Two sources,
  adjacent windows.
* **Transaction counts in §3 are token-balance touches**, not classified buys/sells — a
  transaction touching his wallet is not necessarily a discretionary trade of his.
* **The namespace census is one query on one day.** Handles are cheap to mint; thirteen today
  is not thirteen next week.
* **Nothing here prices his calls.** No forward returns, no wiggle measurement, no null. This
  file is the instrument plus the wallet's shape; the scoring is §5.
