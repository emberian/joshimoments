# PANEL — the first mint-indexed panel

Collected 2026-08-13. Frame, tape, reports and ledger under `tape/` (gitignored: data, not code).
Reproduce with `scripts/pumpfun_frame.py`, `scripts/collect_panel.py`, `scripts/panel_audit.py`.

Every signal lane before this one returned **UNRESOLVABLE**, and all of them for the same
reason: the only chain data on disk was a two-address *wallet* watchlist. A wallet-indexed tape
records a structural zero for every `(mint, hour)` the watched wallets ignored, so every rate
ratio is `+inf` or `0/0`. This document is about the other index.

**What it is.** 1,157 pump.fun mints, 306,216 recorded fills, 307,549 reserve readings, 53,715
wallets, in two strata: a *census* of every launch in a contiguous 27-minute window (913) and a
uniform random subsample of the previous day's graduated tokens (250). 617,236 tape lines, zero
malformed, zero duplicate event ids, zero mints dropped for want of budget.

**What it cost.** **77,620 credits of the 100,000 cap** — 0.78% of the 10M monthly plan, with
22,380 unspent. 59,540 of that bought the panel; **15,000 was wasted** on two versions of the
coverage audit that measured the wrong thing before the third one worked (§5b). §7 says what the
remainder should buy, and it is not more of the same day.

**What it is worth.** Replication against a differently-paged re-fetch of 80 completed mints
found **7,090 of 7,090** trade signatures already on the tape — coverage **1.00000**, zero
missing. Cross-vendor reserve reconciliation against pump.fun's own numbers: **93 of 100 exact
to the lamport**, and all 7 mismatches off by exactly **one base unit**.

**The verdict signal #1 was waiting for: FEASIBLE.** At an activity floor of 5 tokens per wallet
the panel yields 3,915 wallets against a Bonferroni ceiling of 151,912 — 39× of headroom. At a
floor of 2 it is 17,885 against a ceiling of 35, dead by three orders of magnitude, exactly as
PROGRAM.md §4.1 predicted from arithmetic and now confirmed on measured activity.

**The expensive thing this found.** The recorder was silently discarding **every bonding-curve
trade ever recorded**, because pump.fun spells native SOL two different ways and it only knew
one. §3.

---

## 1. How the mints were chosen

### The discovery source, and why not Helius

Mint discovery is the cheapest part of a mint-indexed panel and it must not be paid for in
Helius credits. `getSignaturesForAddress` on the pump program would spend credits to learn what
a public endpoint already publishes, and it returns *trades*, not launches — the launch would
have to be reconstructed by fetching each transaction. `frontend-api-v3.pump.fun/coins` is free,
unauthenticated, and carries `mint`, `creator`, `bonding_curve`, `pool_address`,
`created_timestamp`, `complete` (the curve finished), `quote_mint`, live reserves and a market
cap. Cost: **0 Helius credits** for the entire frame.

The third option — the intelligence store's 611 already-observed mints — was rejected, and not
on cost. Those are whatever a two-address watchlist happened to touch, and the earlier audit of
that store measured the third-party KOL wallet as **88.5% inbound dust**: 981 of 1,108 rows were
unsolicited transfers from 753 distinct senders spraying 581 mints, while the wallet itself
signed three transactions. So those 611 are close to a sample of *mints someone sprayed at a
KOL*. Building the panel on them would import the exact selection pathology the panel exists to
escape, for free instead of for credits, which is not a saving.

### The listing is not a census, and that had to be measured

Two sweeps taken two minutes apart, restricted to the *same* 28.5-minute creation window, each
returned 700 mints — and each was missing **218 of the other's**. Jaccard 0.525. One sweep sees
roughly 69% of its own stated window, and a different 69% each time.

So the frame is built from repeated sweeps, unioned over a creation window that *every* sweep
covers, and the residual is estimated rather than asserted. The estimator is **Chao1**, not
Lincoln–Petersen, because over twelve sweeps the per-mint capture counts came back
*under*-dispersed — every mint seen 6 to 10 times out of 12, none 11 or 12, none fewer than 6.
That is a rotating slice, not independent sampling; Lincoln–Petersen assumes independence and is
biased *up* under negative dependence, and it duly reported 525 against a twelve-sweep union of
469, an 11% shortfall no amount of further sweeping could ever close.

| sweeps | window | mints | singletons | Chao1 | coverage |
|---|---|---|---|---|---|
| 2 | 30.0 min | 1,021 | 597 | 1,441 | 0.708 |
| 3 | 28.8 min | 972 | 242 | 1,054 | 0.923 |
| **4** | **27.0 min** | **913** | **0** | **913** | **1.000** |
| 6 | 21.7 min | 784 | 0 | 784 | 1.000 |
| 12 | 13.1 min | 469 | 0 | 469 | 1.000 |

Four sweeps is the operating point: the widest window with no singletons. **Stated precisely:
`Chao1 == observed` means there is no evidence of unobserved mass. It is not proof of
completeness**, and under a rotating slice with a stable never-listed remainder it would look
exactly the same. It is the strongest claim this design supports.

One number fell out worth keeping: the four-sweep union implies **2,029 launches/hour**, against
the ~1,500/hour a single pass lists. A one-shot frame understates the launch rate by 26%.

### Two strata

**Stratum A — launch cohort.** Every pump.fun mint created between **18:21:59 and 18:48:57 UTC**
on 2026-08-13, a contiguous 27.0-minute window, `n = 913`, from the four-sweep union above. No
conditioning on outcome at all. 24 of the 913 had completed their bonding curve as of the last
sweep.

**Stratum B — graduated.** A uniform random subsample (`random.Random(20260813)`, seed fixed and
quoted before the draw) of size **250** from the 770 mints that pump.fun listed as `complete`
with creation times spanning 2026-08-12T15:10 to 2026-08-13T18:55 — a ~27.8-hour window. The
graduated listing is *stable* across sweeps, unlike the fresh end (two sweeps 45 s apart agreed
on 770 of 770), so a two-sweep frame suffices there.

Subsampling a census is **sampling, not censoring**: the draw is independent of everything about
the mint, so it is ignorable, and no `DISPLACED` record is owed for the 520 not drawn.

**Why both.** Stratum A can support base rates and survival within its window because nothing
about the outcome entered its selection. Stratum B cannot — it conditions on graduation — but it
is where the deep histories and the dense wallet overlap are, which is what signals #1 and #2
need. Running both is also what makes the selection effect *measurable* rather than argued.

---

## 2. Collection rule

Per mint, `getTransactionsForAddress` paged **ascending from the mint's own first transaction**,
`filters: {"status": "succeeded"}`, 100 transactions per page, until whichever comes first:

- the pagination cursor runs out → `exhausted`;
- a transaction's block time passes `launch + 3600s` → `window`;
- the page cap → `page_cap` (**truncation**);
- the run's credit budget → `budget` (**truncation**).

`window_seconds = 3600` because that is `MINIMUM_SAFE_HORIZON`: the shortest horizon that can
observe the *tail* of Marino/Lillo's 4.4-minute median time-to-graduation rather than merely
reproducing its median. Ascending order and a per-mint anchor mean every mint contributes the
identical `[launch, launch+1h]` window. A fixed *transaction count* would have handed busy mints
a shorter time window than quiet ones — observation length correlated with the outcome, which is
displacement censoring wearing a different hat.

Stratum A was not collected until **19:50 UTC**, one hour after the youngest mint in its frame
was created, so that the window was fully elapsed for every member rather than only for the old
ones.

**Censoring is on the tape, not in this document.** Complete or window-complete reads close
`DEADLINE`. Page-cap, transport-error and budget truncations close `OBSERVER_LOST`, which
`INFORMATIVE_CLOSES` counts, so `tape_health` reports a non-zero censoring rate and no study can
read the panel as complete. A frame mint the budget never reached would be written as a
zero-length `DISPLACED` window; **none were** — the budget covered both frames in full.

---

## 3. Two recorder defects found against real data

### The recorder read one spelling of SOL and dropped every bonding-curve trade

pump.fun names native SOL with the **all-zero pubkey** (the System Program) in its curve events,
and with wrapped SOL only once a PumpSwap pool exists. The recorder compared `quote_mint`
against wrapped SOL alone, so every curve `TradeEvent` went to `non_sol_quote_skipped`.

Caught on the first two real mints it was tried on: **42 of 42 and 69 of 69** decoded curve
trades dropped, 300 fetched transactions each, zero trades recorded. Only post-migration AMM
trades were getting through — the recorder was blind to the entire bonding-curve phase, where
Marino/Lillo's median 457 swaps and every sniper live.

Same five mints, same 150 credits, before and after: **735 trades → 1,123**, with 388 of them
native-SOL quoted and `non_sol_quote_skipped` at 0.

Widening a quote-mint check is exactly the move that writes a foreign token's base units into
`sol_delta_lamports`, so the unit was checked against chain rather than asserted:
`tests/fixtures/pump_native_sol_curve_trade.json` is a real mainnet transaction, and the test
requires the recorded `sol_delta_lamports` to reconcile with the trader's own lamport delta from
that transaction's `preBalances`/`postBalances`, net of declared fees and the cashback rebate. It
reconciles to **349,103 lamports on a 0.267 SOL sell — 0.13%**, the transaction fee and tip.

The guard is still load-bearing, which is the point: **USDC-quoted pump pools exist** — 7 of
250 stratum-B mints and roughly one in five of stratum A's zero-trade mints carry
`quote_mint = EPjFWd…` with `quote_decimals: 6` — and they still contribute zero trades.
**5,461** events were refused as non-SOL-quoted across the two passes. Widening SOL's spelling
did not widen the unit check.

### Per-mint history did not page, and paid for failed transactions

`HeliusHistorySource` claimed "bounded per-mint paging" and read exactly one page per mint,
dropping the cursor — a mint with 3,000 transactions contributed its most recent 100 and nothing
said so. It could not have paged: `mint_enhanced_page` discards `paginationToken`.

Also measured: an unfiltered page of a live pump.fun mint is **59–62% failed transactions**
(slippage rejections, `Custom 6004`) which the recorder discards on arrival. Every page costs 10
credits whatever is in it, so `filters: {"status": "succeeded"}` is a **~2.5×** improvement in
usable transactions per credit. The accepted value is `succeeded`; `successful`, `success` and
`ok` are all `-32602`.

And the trap that motivated the rewrite: **a short page is not the end of the history.** The
service returns a continuation token after one. Confirming exhaustion costs one extra page per
mint; assuming it is right often enough to survive testing and wrong exactly on the busiest
mints.

---

## 4. n at every stage, and what it cost

| stage | stratum A (cohort) | stratum B (graduated) | total |
|---|---|---|---|
| listed by ≥1 sweep, in the common window | 913 | 770 | — |
| **frame** (declared before spending) | **913** | **250** (uniform random of 770) | **1,157 distinct** |
| offered to the collector | 907 (6 already read in B) | 250 | 1,157 |
| reached | 907 | 250 | 1,157 |
| **displaced (never reached)** | **0** | **0** | **0** |
| read to exhaustion | 836 | 6 | 842 |
| stopped at the 1-hour window | 59 | 67 | 126 |
| **truncated by the page cap** | **12** | **177** | **189** |
| mints with ≥1 recorded trade | 810 | 243 | 1,047 |
| **credits** | **27,240** | **32,300** | — |

Plus 930 credits of pilot probes (93 `getTransactionsForAddress` attempts charged at the full
10-credit page rate — an upper bound, since 5 of them returned `-32602` and almost certainly cost
nothing), 30 for an audit smoke test, and **17,120 for the audit** — of which **15,000 was
burned by two discarded versions of the replication check** described in §5b, and only 2,120 by
the one that worked. **Total 77,620 of the 100,000 cap; 22,380 unspent.**

**Tape.** 617,236 lines, 0 malformed, 0 duplicate `event_id`s, 0 chain events without a block
time. 306,216 trade rows over 306,188 distinct fills — the 28 duplicates are byte-identical
fills inside a single transaction, which the tape's own content hash collapses too. 307,549
reserve readings, 1,157 launches, 2,314 watch records.

**Custody, which signal #2 could not get from the old store at all.** 100% of trades carry both
`signers` and `fee_payer`. 12,222 trades have **two or more signers**, giving **7,540 distinct
co-signing pairs** (4,936 seen more than once) — shared-key evidence, the strongest linkage
available, against the two-wallet store's zero. Against that, 1,829 distinct fee-payers sponsored
someone else's trade, one of them across **1,328 different traders**: merging on fee-payer would
fuse a quarter of the traded universe into one entity, which is exactly why the contract keeps
the two fields typed apart.

**Trades per mint** — note how differently the two strata are shaped, and that stratum B's
shape is partly the page cap rather than the market:

| | p10 | p50 | p90 | max | mints with 0 |
|---|---|---|---|---|---|
| A (cohort census) | 0 | 13 | 195 | 2,506 | 103 |
| B (graduated) | 234 | 979 | 1,443 | 1,876 | 7 |

Of stratum A's 103 zero-trade mints, a 60-mint sample says roughly one in five is **USDC-quoted**
(correctly refused, see §3) and the rest genuinely had no successful trade in their first hour —
about **9% of a launch cohort gets no fill at all**, dev buy included.

**Incidental mints.** 143 mints appear on the tape that were never in a frame — they shared a
transaction with a frame mint. They carry 199 trades, **0.065%** of the total. Their coverage is
arbitrary and they are excluded from every number in §5.

---

## 5. Wallet activity, and the verdict on signal #1

Restricted to frame mints, `T = 1,047` mints with trades, **53,715 wallets**, 107,210
wallet–token pairs.

| tokens traded | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| wallets | 35,830 | 9,888 | 2,492 | 1,590 | 1,342 | 809 | 497 | 175 | 159 | 125 | 76 | 61 |

p50 = 1, p90 = 4, p99 = 15, max = **214**. Two thirds of the wallets are one-token tourists,
exactly as the design anticipated.

The gate (PROGRAM.md §4.1): `C(T, N) ≥ 9·n(n−1)/(2α)` at `α = 0.01`, nine typed tests per pair.

| activity floor | wallets at or above | max feasible universe (T = 1,047) | (T = 300, for reference) | verdict |
|---|---|---|---|---|
| 2 | 17,885 | 35 | 10 | **INFEASIBLE** |
| 3 | 7,997 | 651 | 100 | **INFEASIBLE** |
| **5** | **3,915** | **151,912** | 6,597 | **FEASIBLE (39× headroom)** |
| **8** | **1,267** | **278,355,052** | 1,814,180 | **FEASIBLE** |
| 10 | 933 | 3.0×10¹⁰ | 5.6×10⁷ | FEASIBLE |

**Verdict: signal #1 is feasible on this panel at an activity floor of 5 tokens per wallet, and
comfortably so.** 3,915 wallets against a ceiling of 151,912 is 39× of headroom, which means the
floor could be relaxed toward 4 or the panel widened without the Bonferroni threshold becoming
unreachable. At a floor of 2 the design is dead by three orders of magnitude — the arithmetic
PROGRAM.md §4.1 predicted, now confirmed on real activity rather than on an assumed one.

Buy-side only — Tumminello removes opposite-action links before clustering, and PROGRAM.md's
anti-signal list warns that sell-only addresses are exit-liquidity plumbing rather than traders —
the universe is **3,542 wallets at floor 5** and 1,169 at floor 8. So the verdict survives the
stricter reading with a 43× margin.

---

## 5b. Is the tape any good? Three checks

**Replication — does the paging have holes?** 80 mints re-fetched at page size 97 instead of
100, so every page boundary lands three transactions further along, and only mints the collector
claims to have read *completely* (`exhausted` or `window`) — coverage is only checkable where
coverage is claimed. Result: **7,090 replicated trade signatures, 7,090 already on the tape,
coverage 1.00000, zero missing**, 2,120 credits. The paging is sound.

*Two earlier versions of this check reported 43% and had to be thrown away, which is worth
recording.* The first sampled *incidental* mints, whose "window" is the gap between two arbitrary
sightings — one showed 3 trades spanning 16.6 hours and ate the whole replication budget. The
second counted **every** pump trade event in a transaction that touched mint M, including trades
on other mints riding along in the same bundle or router, and reported the recorder as missing
trades it had correctly filed under a different mint. Both were bugs in the instrument, not the
tape, and both would have read as a damning coverage failure to anyone who stopped at the number.

**Reserve reconciliation — are the amounts right?** For any non-graduated mint whose last trade
(per pump.fun's own listing) fell inside our window, the tape's last recorded reserve reading
must equal pump.fun's current state exactly. **100 checked, 93 exact in all four integer fields,
7 off by exactly one base unit** — one lamport of `real_sol`, or one raw unit of
`virtual_tokens`, in the *listing's* favour or ours. So 100 of 100 agree to within a single base
unit, across two vendors, on the money path. This is the check that would break on a unit error,
and it does not.

**Layout drift — the one real coverage hole.** The pinned Borsh layouts refuse an event they
cannot decode exactly, and **2.54%** of trade events in the replication sample were refused as
`schema_drift` (185 of 7,287). That is the honest independent reference count: `306,216 / (1 −
0.0254) = 314,197` trades occurred in the windows we covered, and the tape holds **97.46%** of
them. `tape_health` reports exactly that and refuses to call the tape sound because of it. §7 has
the diagnosis.

**`tape_health` over the whole panel** (`tape/reports/tape_health.txt`):

```
lines               617236 (0 malformed)
duplicate ids       0
no block time       0
distinct mints      1300
events              launch=1157, reserve=307549, trade=306216, watch=2314
coverage            0.9746 (306216/314197 trades)
watches closed      1157 (open now 0)
censoring rate      0.0233 (27 informative)
close reasons       deadline=900, graduated=230, observer_lost=27
unresolved past dl  0
graduations         n=230 median=21.0s p90=558.0s max=3308.0s
timed on            chain=230 observer=0
tail present        True (reference median 264s, with a long tail)
SOUND               False
```

**The instrument check that matters (PROGRAM.md §3 rule 8) passes.** 230 graduations, every one
of them chain-timed at both ends, median **21 s**, p90 **558 s**, max **3,308 s** — a tail 157×
the median. A displacement-censored collector reproduces the median and destroys the tail; this
one has the tail. What the median is *not* is comparable to Marino/Lillo's 264 s: this sample
conditions on graduation and the page cap truncates the slow, busy graduations, so 21 s is a
lower bound on a differently-defined quantity, not a contradicting measurement.

**`SOUND: False` is the correct answer**, for two stated reasons — 2.54% of trades lost to layout
drift, and 27 of 1,157 watches informatively censored. Neither is hidden and neither is silent.

---

## 6. What this sample cannot support

Listed in rough order of how easily each one could be mistaken for a capability.

1. **It is not one sample.** Stratum B conditions on graduation, an outcome. Pooling the two
   strata and computing anything unconditional gives a number about neither population — a
   pooled graduation rate here would be nonsense by construction.

2. **No graduation rate beyond one hour, even in stratum A.** The observation window is
   `[launch, launch+1h]`. Marino/Lillo's median is 4.4 minutes *with a long tail*; every
   graduation after minute 60 is unobserved. What stratum A supports is a **one-hour**
   graduation rate with an explicit horizon, not "the" graduation rate.

3. **Per-mint activity is not comparable across stratum B.** Most of its mints stopped at the
   page cap, and the cap binds harder the busier the mint — truncation correlated with the
   quantity being measured. Trade counts there are lower bounds and their ordering is partly an
   artefact of the cap. Stratum A does not have this problem; almost all of its mints were read
   to exhaustion.

4. **Tokens-per-wallet is a lower bound, and the censoring is not ignorable.** A wallet that
   first touched a mint after its window closed is invisible on that mint. Since the window is
   the same length for every mint but busy mints pack more distinct wallets into it, the
   undercount is larger exactly where wallets are densest.

5. **No failed transactions.** `status: succeeded` was the 2.5x credit saving, and it means the
   tape holds nothing about slippage rejections. On a hot mint those are **59–62% of all
   transactions**, and they are the direct measurement of sniper congestion and competition for
   a fill. Any study of failed-attempt intensity has to re-collect.

6. **No temporal folds, so §3 rules 1 and 6 cannot be honoured.** Stratum A is a single
   27-minute window and stratum B a single ~28-hour window, both on 2026-08-13. There is no
   second regime to hold out. A model fitted here can be evaluated *within* the day at best, and
   the pump.fun regime shifts in weeks.

7. **No social side.** Signal #3 needs callouts joined to flow; this panel is the flow half
   only. Nothing here carries a `Callout`.

8. **No token metadata.** `Launch.has_twitter` / `has_telegram` / `has_website` live in
   off-chain JSON behind the metadata URI and were not fetched, so they are correctly *absent*
   rather than false. Any study conditioning on socials must join a sidecar first. (Note the
   read path in `schema.py` turns an absent flag into `False` on the way back in — see §7.)

9. **Incidentally-observed mints are not a sample of anything.** Mints that appear only because
   they shared a transaction with a frame mint have arbitrary, tiny coverage. They must be
   excluded from any co-occurrence or rate calculation; every number in §5 already is.

10. **One provider.** Every transaction came from Helius. The replication check varies the
    paging, not the vendor, so a systematic omission in Helius's own index would be invisible
    to it. The reserve reconciliation is the only genuinely cross-vendor check here, and it
    covers amounts on settled curve mints — not the transaction set.

---

## 7. Open items this collection surfaced and did not fix

**Pinned Borsh layout drift is losing real trades, and it is not in this package. This is the
panel's only measured coverage hole.** The recorder quarantined **25,539** pump `Program data:`
lines across the two passes against 313,288 decoded, ~7.5%. Most of that is new event types the
pinned IDL has never seen (`unknown_discriminator`), which cost nothing. The part that costs
something is **`TradeEvent`s refused on trailing bytes**, measured at **2.54% of all trade events**
in the replication sample (185 of 7,287) — call it ~7,900 fills missing from this panel.

The diagnosis: on an inspected page, four TradeEvents of 373 bytes quarantined as `schema_drift`
while the decodable ones ran 358/359/371, and the quarantined payload's *known* prefix decoded to
entirely plausible values — right mint, right user, a 0.966 SOL buy, coherent reserves. That is a
program emitting a newer event with fields appended.

This was deliberately not fixed here. `shitcoims_intelligence/pump_layouts.py` is hand-audited
and pinned to a `pump-public-docs` commit, and the fail-closed refusal is correct behaviour: a
field *inserted* rather than appended would keep the same discriminator and silently corrupt
every amount after it. The right fix is re-pinning against the current IDL, by whoever owns that
decoder, with the amounts re-checked against chain the way §3 did. Until then, per-mint trade
counts here carry a few-percent shortfall that is **not** uniform across mints.

**The schema's read path fabricates a negative.** `Launch.to_json` correctly *omits* an
unobserved social flag, but `_body_from_json` reads it back as
`has_twitter=bool(raw.get("has_twitter", False))` — so an absent flag round-trips to `False`,
turning "never fetched" into "observed absent". That is the same disease as a quote-stamped cost
basis, in the one place the contract was built to prevent it. `schema.py` is frozen and outside
this lane; flagged for whoever unfreezes it.

**`TradeEvent` carries no bonding-curve address.** The curve is known only from a witnessed
`CreateEvent`, so a mint fetched without its creation loses every reserve reading (11 events in
stratum A, 34 in stratum B — negligible here only because ascending paging starts at creation).
Deriving the curve PDA from the mint would close it; that is an inference, and it should be
made deliberately rather than by accident.

**Unspent budget: 33,500 credits, and the next pass should not be more of the same day.** The
single most valuable thing that money can buy is a **second cohort on a different day**, because
§3 rules 1 and 6 need temporal folds and this panel has none — every conclusion drawn on it is
in-sample by construction. A second 27-minute cohort plus a matched graduated subsample would
cost roughly what the first did and turn "fitted here" into "held out there".
