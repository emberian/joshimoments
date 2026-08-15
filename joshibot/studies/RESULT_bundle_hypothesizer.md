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
| **`FBvxneTq…` — universal launch sniper, 17,908 coins** | 262 | **42.7%** | **1.4%** |

**The negative control sits at 42.7% same-slot.** A wallet that shares 1.4% of its portfolio with
the caller — i.e. one that is provably not coordinated with him, just fast — concentrates at the
same slot almost as hard as the three that share 99%.

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
