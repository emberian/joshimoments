# RESULT: the bundler hypothesizer — same-slot is sniping, breadth is coordination

Operator tasking, verbatim: *"apparently this is called 'bundling'? and we want to be building a
'bundler hypothesizer and analyzer'"* — followed immediately by the correction that shaped the
whole design: *"well it isn't just the same slot one entity. there may be less obvious strats,
this one was just really obvious and easy to find."*

Code: `studies/bundle_hypothesizer.py`. Artifacts under `.cache/bundle/` and `state/crime/`
(gitignored).

> **Status: sections 1–3 are settled and are the design. Sections 4+ carry the measurements and
> are marked with their own n and nulls.**

---

## 1. Why this is not a same-slot detector

The obvious signature — several wallets buying one coin in the same slot, in separate
transactions — is real, and it is what surfaced the case that started this. Three wallets trade in
the same second as a watched caller's buys (`RESULT_jackduval_workup.md` §5.7). But building a
detector on that would have been a mistake, and the control says so out loud:

| wallet | pairs within ±4 slots of his buys | **share at d_slot = 0** | shared-coin breadth |
|---|---|---|---|
| `6Eegkyd2…` | 2,639 | **52.8%** | **99.2%** |
| `DkWzWsQT…` | 2,511 | **53.1%** | **98.8%** |
| `D7xK1ZLz…` | 2,037 | **48.9%** | **99.6%** |
| **`FBvxneTq…` — universal launch sniper** | 262 | **42.7%** | **6.3%** *(corrected, §5.1)* |

**The negative control sits at 42.7% same-slot.** A wallet that shares 6.3% of its traded
portfolio with the caller — i.e. one that is provably not coordinated with him, just fast —
concentrates at the same slot almost as hard as the three that share 99%.

*(That 6.3% was first published as 1.4%. The correction, and why it makes the control **better**
rather than worse, is §5.1.)*

The reason is structural: **everyone racing a new launch lands in the same few slots.** Same-slot
co-occurrence measures *how contested a coin's first seconds were*, not *who is working together*.
A same-slot detector is a launch-sniping detector wearing a different name, and on this market it
would fire on most of the population.

Two further shape facts, from the same table's underlying data:

* The offset profiles are **symmetric** — d = −1 and d = +1 match to within a few counts
  (208/208, 200/197, 167/166). A *reactive copier* lags and would leave a one-sided positive tail.
  These wallets are not reacting to him; they are co-scheduled with him, or all of them react to a
  common trigger.
* Same-slot `tx_index` offsets are spread across ±1…±3 rather than tightly consecutive. A true
  atomic Jito bundle executes as a contiguous run. **This is a fleet firing into one slot, not one
  bundle** — which means even the "obvious" case was not the textbook object.

What separated the three from the control was **breadth**, which involves no timing at all.

---

## 2. The design: rank linkage channels by how expensive they are to evade

This is the whole idea, and it follows directly from the operator's correction. A coordinator who
learns that same-slot is being watched adds jitter — that costs nothing. A coordinator cannot
cheaply stop trading the coins they are there to trade.

So channels are ranked by **evasion cost**, and the cheap ones are demoted to corroboration:

| # | channel | what it links on | evasion cost | role |
|---|---|---|---|---|
| 1 | **portfolio specificity** | fraction of A's coins also traded by B, **both directions** | **high** — you would have to trade coins you do not want | load-bearing |
| 2 | **lifecycle coupling** | wallets first-seen / last-seen together; rotation chains | **high** — needs fresh funding and a fresh history | load-bearing |
| 3 | **supply parking** | tokens moved wallet→wallet with **no curve movement** in that transaction | **high** — the transfer is the strategy | load-bearing |
| 4 | **accumulate/dump asymmetry** | many wallets in, one wallet out | structural | corroborating |
| 5 | **size choreography** | shared clip-size generator (CV of clips) | moderate | corroborating |
| 6 | **timing** | slot offsets, offset symmetry, `tx_index` adjacency, Jito tip in `fee_lamports` | **low — trivially jittered** | corroborating only |
| 7 | **sequential / relay** | wallets that *never* overlap but whose set recurs across coins | — | the evasion of #6, so it is detected *as* the evasion |

Channel 7 deserves the emphasis the operator's correction gave it. Anti-correlated timing is as
unlikely under independence as correlated timing. A coordinator who staggers to defeat same-slot
detection produces a *closed recurring wallet set with suspiciously non-overlapping timing* — and
that is a positive signature, not an absence of one.

**The output is a hypothesis, not a verdict.** The product is "this set is consistent with shape
X, inconsistent with Y, and undecidable between Z and W **given this corpus**" — plus which
channels could not fire because the data cannot see them. A binary bundle/not-bundle answer would
be a claim the evidence cannot support.

### 2.1 What can never be separated here, stated up front

* **"One entity's wallets" vs "a copy bot that follows only that wallet"** — both produce ~99%
  breadth. Nothing in a trade tape distinguishes them. `RESULT_jackduval_workup.md` §5.7 leaves
  this open for exactly this reason.
* **A market maker vs a wash trader** — inherited verbatim from `RESULT_caller_wallets.md` §6.1;
  they leave the same trace, so manufactured-volume numbers are a **ceiling**, never a finding.
* **MEV from coordination**, where the MEV is a same-slot sandwich. `PROGRAM.md` §4 signal 4 says
  "exclude same-slot atomics (MEV is the dominant false positive)". §1 here refines that: on this
  market the dominant same-slot false positive is **launch sniping**, not MEV.

---

## 3. What this desk cannot measure, and why

**Funding ancestry is not computable on local data.** `PROGRAM.md` signal #2 specifies
"first-funder + deposit-address reuse" as the prerequisite for everything else, and it would be
the most decisive channel available — a common funder is near-dispositive where breadth is only
suggestive. It cannot be built here:

* `state/bulk_pump/daily/*.parquet` (106M transactions, 2026-08-05 → 08-14) carries **token
  balances only** — `pre`/`post` as `STRUCT(owner, mint, amount, decimals, account_index)[]`.
  No native-SOL transfer legs, no fee payer, no signer.
* `state/bulk_history/parquet/*.parquet` (48 days, 2026-06-27 → 08-13) reaches back much further
  but is a **single-pool swap tape** — `label` is `DREGG/SOL` and its only identity column is
  `signature`. **No owner field at all.**

`SWARM.md` §"Three gaps" records "**No same-slot atomic/bundle field.** MEV is the dominant false
positive for signal #4, and it cannot be excluded after the fact." For the *live* tape schema that
still holds. For **retrospective** work it does not: `bulk_pump` carries `block_slot`, `tx_index`
and `fee_lamports`, which is exactly the atomic/bundle view that gap says is missing. That gap is
closeable for history, and this module closes it — while §1 argues the field is worth much less
than the gap statement assumed.

**Launch bundling is only answerable for one of the operator's four coins.** The owner-bearing
corpus starts 2026-08-05:

| coin | created | launch inside the owner-bearing corpus? |
|---|---|---|
| nosis | 2026-08-09 | **yes** — the one clean case |
| weave | 2026-08-03 | **no** — 2 days early; post-launch accumulation only |
| SOLVE | 2026-07-20 | **no** |
| DREGG | 2026-06-27 | **no** — and the 48-day tape that reaches it has no owners |

No launch verdict is offered for weave, SOLVE or DREGG. That is a data boundary, not a finding,
and it is not worked around.

---

## 4. The fleet caught firing, live, four minutes after it was subscribed

`RESULT_jackduval_workup.md` §5.7 found the coordinated set retrospectively and could not say
whether the wallets lead, follow, or fire together — a ten-day corpus has slots, but same-slot
`tx_index` is not a clock. So the three were added to the live `accountTrade` subscription at
**18:36:59Z**. **Four minutes later the whole fleet fired**, on a coin none of them had touched
before.

`JDKBdwTqveZKqY9A8UVLySjvhfhvPt4r3DUfsyeEpump`, offsets relative to the first frame:

| t | wallet | side | SOL | balance after |
|---|---|---|---|---|
| +0.000 s | shadow_B | buy | 1.012852 | 18,538,072 |
| +0.001 s | **jackduval** | buy | 1.037355 | 18,091,373 |
| +0.068 s | shadow_C | buy | 1.164884 | 19,313,441 |
| +0.069 s | shadow_A | buy | 1.184909 | 18,638,267 |
| +5.130 s | shadow_C | buy | 0.264004 | 21,712,300 |
| +5.131 s | shadow_A | buy | 0.244013 | 20,836,671 |
| +5.263 s | **jackduval** | buy | 0.227438 | 20,124,379 |
| +5.263 s | shadow_B | buy | 0.242324 | 20,687,283 |
| **+39.580 s** | shadow_B | **sell** | 2.845926 | **0** |
| **+39.580 s** | **jackduval** | **sell** | 2.548800 | **0** |
| **+39.620 s** | shadow_A | **sell** | 2.437017 | **0** |
| **+39.620 s** | shadow_C | **sell** | 2.345393 | **0** |

**5.3778 SOL in, 10.1771 SOL out — +4.7994 SOL (+89.2%) in 39.6 seconds**, across four wallets
acting as one.

Five things this settles that the corpus could not:

1. **It is a genuine multi-wallet operation, not a copy bot.** All four enter inside **69
   milliseconds** and exit inside **40 milliseconds**, each to a **zero** balance. A copier
   watching a leader cannot exit 40 ms after him on a coordinated schedule; it would lag by a
   network round trip and would not know to go flat.
2. **jackduval is not the leader.** shadow_B's buy precedes his by **1 ms**, and on the second
   tranche two shadows precede him by 133 ms. He is a peer in a four-wallet fleet, not a caller
   the others follow. **Watching "his wallet" is watching one quarter of an entity** — which
   materially reframes the operator's original request.
3. **Sizes are choreographed but deliberately jittered** — 1.0129 / 1.0374 / 1.1649 / 1.1849, then
   0.2440 / 0.2423 / 0.2274 / 0.2640. Near-equal, never equal. That is what evading a
   naive exact-size matcher looks like, and it is why §2 ranks size choreography as a *moderate*
   channel: the CV is tight but no two clips match.
4. **The exit is the tell.** Four wallets going flat within 40 ms is the single least deniable
   event in this file. Independent traders do not simultaneously zero.
5. **Two tranches, five seconds apart** — a first block of ~1.1 SOL each and a top-up of ~0.24
   SOL each. That is a size ladder, executed in parallel across the fleet.

A second coin in the same window, `HewQyEvrnAiGUEVHSSdh4A8Ws3PuWySTPjuzERvXpump`, shows the same
four wallets buying twice in near-lockstep (all four inside 87 ms, then all four again inside
35 ms). Every leg reports `newTokenBalance: 0`, which is anomalous for a buy and is **not
interpreted here** — it may be a failed or immediately-reverted position, and one unexplained
field is not worth a story.

**n = 2 coins, one 4-minute window.** The choreography is unambiguous; its *frequency* is not
estimated. What this window establishes is the mechanism, and that the live subscription is the
right instrument for it — the retrospective corpus produced a 99% breadth statistic and an open
question, and forty seconds of forward tape closed the question the corpus could not.


---

## 5. What the framework is, and what it caught in its own inputs

`studies/bundle_hypothesizer.py` — nine channels, each with its own structure-preserving null.
The extraction was validated against §1's hand numbers first and reproduces them exactly
(99.2 / 98.8 / 99.6).

### 5.1 The control was weaker than published — and fixing it strengthened the result

The negative control was reported in §1 as touching **17,908 coins** and sharing **1.4%**.
**15,671 of those mints it never traded.** They are inbound airdrop dust: **24,699 inbound
transfer legs and zero outbound**. Its real traded book is **2,237 coins**, so true specificity is
**6.3%, not 1.4%**.

The separation is therefore **99.6% vs 6.3%** — still decisive, and now for the right reason.

The lesson generalises past this one wallet: **coins touched is not coins traded**, and
unsolicited inbound dust silently inflates the denominator of any portfolio-overlap statistic. It
is the same genus as the address-poisoning campaign `wallet_labels.yaml` already documents — dust
arriving uninvited — except here it corrupts a *measurement* rather than a label. Any future
breadth statistic must be computed over the traded book.

### 5.2 The gate, pre-declared and passed without per-case tuning

One threshold set (`spec ≥ 0.60, pop_z ≥ 5, cb_ratio ≥ 3, cb_p ≤ 0.01, |P| ≥ 20`), declared before
running and applied unchanged to every arm:

| arm | n | fired |
|---|---|---|
| known positives | 3 | **3** |
| universal-sniper control | 1 | **0** |
| **hard negatives** (top-40 co-traders) | 40 | **0** |
| random co-traders | 100 | 1 |
| synthetic known-**zero** | 34 | **0** — 0% FPR |
| synthetic known-**effect** | 34 | **3 of 3 planted** |

**The hard negatives are what make this mean anything.** `64hP97Bwr5…` shares **302** of the
caller's coins — *more than known-positive `D7xK1ZLz…`'s 275*. **Raw overlap count cannot separate
coordination from being busy**; only the asymmetric *fraction* can. A detector built on "how many
coins do they share" would rank a non-member above a member.

Both PROGRAM.md §3.12 controls ran. 18 of 100 randoms are reported **undecidable** (`|P| < 20`,
underpowered) rather than counted as negatives.

---

## 6. Which channels actually carry information

| channel | verdict |
|---|---|
| **portfolio specificity** | **separates on its own** — the only channel that does |
| **lifecycle coupling** | **fires** — `6Eeg` and `DkWz` share first slot **437,325,417 exactly**; **0 of 2,556** background pairs tie |
| **cross-wallet size choreography** | **fires** — log-size-ratio sd **0.64–0.77** vs background **2.32**; they trade at ~**1.02×** the caller's clip |
| accumulate/dump asymmetry | **null, and near-tautological** — it restates channel 1 |
| relay / sequential | null — they are co-timed, not staggered |
| rotation | null — zero links |
| wash trading | 2.38% **ceiling** only, never a finding |
| timing | separates by effect size (16× vs 2.3×) but **every arm including the control hits the MC p-floor** |

Three results here are worth more than the detections.

**Marino's asymmetry is absent.** `PROGRAM.md` §1.1 imports as a "free structural prior" that
accumulation is multi-wallet while the dump is single-wallet. On this fleet, **buy-wallets =
sell-wallets = 2.746, exactly**. They accumulate together and they dump together. The imported
prior does not hold here and should not be assumed elsewhere without checking.

**The self-CV size statistic from `RESULT_caller_wallets` §6.1 does not separate.** What separates
is *cross-wallet* size agreement — the ratio between wallets' clips, not the variance within one
wallet's own. That is a different statistic than the one this repo already had.

**It is confirmed not an atomic Jito bundle.** `tx_index` median offset **6**, only ~13% adjacent,
and **fees are not elevated** — no Jito tip signature. A fleet firing simultaneously, not one
bundle. §1's reading holds.

---

## 7. The shape is *nested*, which is what rules out copy bots

The decisive structural fact, and it needs no null:

```
D7xK (277)  ⊂  DkWz (343)  ⊂  6Eeg (355)  ⊂  CALLER (494)
```

…and the three shadows are **95.8–99.6% contained in each other**.

**Three independent copy bots would each be contained in the caller, but NOT in one another.**
Independent copiers of the same target overlap only through the target; they would not form a
chain. A nested hierarchy is what one operator running wallets at different capital tiers looks
like. Together with §4's 40 ms synchronised exit, "copy bot" is no longer the live alternative.

The framework also proposed a **fourth member on its own initiative**:
`7uyGRgoCRKfynPbB35kWQwEGz9pmRvUyNFunV939mXpN` — 53 coins, 96.2% contained, top-5 under both
nulls. Proposed, not attested; `inferred` at best.

---

## 8. The operator's four coins — no supply parking, and two false alarms killed first

**Both false alarms are reported because each was one edit away from being published as a finding.**

1. The first transfer detector picked **one pool per mint**. Correct pre-graduation, catastrophic
   after: nosis has an 81,452-signature pool *and* a 21,588-signature second pool plus routers, so
   **17% of legs were misfiled as transfers**, producing a 686-wallet component and a headline of
   **"+44.4 pp, high-risk"**. Fixed with a wSOL test (94,411 of nosis's 98,435 signatures are
   swaps) plus structural infrastructure detection.
2. Union-find over what remained *still* gave **+37.2 pp** — a star on one hub. That hub made
   **0 curve buys and 703 outbound transfers to 168 addresses**, of which **136 later bought and
   133 sold on the curve independently**. It is a **distributor/faucet, not parked supply**. Fixed
   by excluding hubs on fan-out.

This is `PROGRAM.md` §4's warning about union-find arriving on schedule, twice.

After both fixes:

| coin | naive top-10 | bundle-adjusted | **delta** | launch answerable? |
|---|---|---|---|---|
| nosis | 19.4% | 19.4% | **+0.0 pp** | **yes** |
| weave | 26.0% | 26.0% | **+0.0 pp** | no |
| SOLVE | 48.2% | 48.8% | **+0.6 pp** | no |
| DREGG | 48.9% | 49.4% | **+0.5 pp** | no |

MELT's high-risk marker is **+24 pp** and its low-risk marker **+6 pp**. **All four sit below even
the low-risk marker. There is no detectable supply parking on any of the operator's coins.**

**nosis's launch — the only one inside the corpus.** Five wallets bought in the create slot at
`tx_index` 44 / 495 / 504 / 510 / 565 / 566. Scattered, with only 565/566 adjacent: **a
competitive snipe, not a bundle.** 37 buyers in the first 50 slots, 15 of whom still hold, for
**7.1% of supply** today. All five first-slot wallets touch **only one** of the operator's four
coins — no recurring cross-coin fleet works these launches.

**On `numerics.py:29`'s naive Gini** (`PROGRAM.md:389`: "bundle-correct it or drop it"): on these
four coins the naive figure is essentially right — nosis 0.8990 → 0.8990. The fragmentation the
program worries about **is not present here**. The bug is real and worth fixing; it is not
currently producing a wrong number on the operator's own coins.

---

## 9. Limits

* **Funding ancestry is not computable on this machine** (§3), and it is the one thing that would
  separate "one entity's wallets" from "a co-located fleet renting the same signal". Both produce
  nested portfolios and symmetric same-slot timing. **Not faked.**
* **Trials: 9 channels × 2 nulls = 18 tests**, one threshold set. Divide any single channel's p by
  18. The claims offered as real are the gate outcome, the nesting, and the ~0 pp concentration
  deltas — none of which is a marginal p-value.
* **Exclusions itemised**: 18/100 randoms undecidable; 70/145 left-censored and 71/145
  right-censored on the lifecycle channel; zero-delta legs, `err` transactions and wSOL legs
  dropped.
* **§8's launch verdict covers nosis only.** SOLVE, DREGG and weave launched before the
  owner-bearing corpus begins, and the 48-day tape that reaches them has no owner column. No
  verdict was guessed for them.
* Both giant-component artifacts are kept **in the module** rather than deleted, because the
  failure mode is the reusable lesson.
