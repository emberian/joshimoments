# RESULT: everyone who ever called nosis, DREGG, weave and SOLVE

Operator tasking, verbatim: *"we need to investigate anyone who ever called nosis, dregg, weave,
or solve."*

Code: `studies/cluster_callers.py` (`pilot` / `census` / `profile` / `report`). Data under
`state/callouts/cluster_*` (gitignored); full output at
`state/callouts/cluster_callers_run.txt`. Byte-identical across two runs.

```
uv run --group research python -m studies.cluster_callers report \
  --census 'state/callouts/cluster_census_*.jsonl,state/callouts/cluster_pre_*.jsonl,state/callouts/cluster_control_pre.jsonl' \
  --profiles 'state/callouts/cluster_profiles*.jsonl' \
  --slices 'state/callouts/*.slices.jsonl' --draws 2000
```

**Spend: $2.509** of Apify (10,036 gross tweets at $0.00025), against a pre-registered $8 gate.
A pilot on DREGG's first six hours cost $0.008 and set the extrapolated ceiling at $2.98 before
anything larger was bought.

---

## 0. The one-paragraph answer

**Half of the calls on the operator's coins come from 13% of the accounts, and that 13% is
machinery.** Across the full life of all four coins — 1,900 (coin, tweet) rows from 484 distinct
accounts — 63 accounts are either machine-classified or members of a shared copy-template family,
and they produce **50.5% of every mint-bearing call**. The cross-coin structure is not a roster
of loyal followers; it is a **template**: one 17-account family posts variants of *"2X up from my
call on $TICKER — CA: …"* across **all four coins**, and several sub-groups post
character-identical text from different handles. Only **2 accounts** called three of the four,
and **none** called all four.

The four coins were **not** promoted the same way. Against a null that preserves each account's
call count and the coin's own temporal envelope, **nosis and weave show real burst promotion**
(p = 0.0005 and 0.0095) — nosis's tightest window is 10 distinct accounts inside 300 seconds,
16 minutes after launch. **SOLVE does not survive that null** (p = 0.108) and **DREGG is a clean
null** (p = 1.000): DREGG's observed clustering is actually *below* its own envelope, and its
tightest window is two accounts, one of whom is the operator.

So: DREGG, the coin that matters most to the operator's income, is the one with **no detectable
purchased-burst signature** in this census. nosis and weave have one.

---

## 1. The census, and what the query shapes are worth

Full life of each coin, 30-minute-to-24-hour slices, deduped on tweet id. **0 slices hit the
actor's result cap and 0 queries failed**, so this is a census of these query patterns over these
windows rather than a sample thinned by traffic.

| coin | rows | mint-bearing | cashtag-only | accounts | first call |
|---|---|---|---|---|---|
| nosis | 586 | 302 | 284 | 224 | 2026-08-09 07:46 |
| weave | 204 | 113 | 91 | 76 | 2026-08-03 22:39 |
| SOLVE | 116 | 38 | 78 | 25 | 2026-07-20 23:31 |
| DREGG | 994 | 398 | 596 | 201 | 2026-06-27 13:47 |
| **total** | **1,900** | **851** | **1,049** | **484 distinct** | |

**Two of the four tasked query shapes are dead weight**, which is a reusable measurement:

| shape | rows | mint-bearing |
|---|---|---|
| bare contract address (`ca`) | 768 | **100.0%** |
| cashtag | 1,724 | 39.2% |
| `url:pump.fun` | **3** in 50 full-life slices, all duplicates of `ca` | — |
| `url:dexscreener.com/solana` | **0** | — |

X indexes the address *inside* the expanded URL, so the bare-address query already returns the
link posts. A rerun should buy `ca` and `cashtag` only.

### 1.1 Both controls, and the contamination that did not happen

`PROGRAM.md` §3.12 demands a known-zero and a known-effect arm; both ran.

**Known-zero:** the `ca` query over each coin's *pre-creation* mirror window (154 / 283 / 622 /
1,181 hours) returned **0 rows on all four**. The instrument does not manufacture callouts.

**Cashtag background:** the brief expected heavy false-positive contamination, because `$SOLVE`,
`$weave` and `$nosis` are ordinary English words. **It did not materialise** — 0 background rows
for `$SOLVE`, `$weave` and `$nosis`. `$DREGG` returned 12, and those 12 are a *different* `$DREGG`
(mint `Bv7yfJJ…Dpump`, a duck coin whose dev says so outright, last seen 2026-06-16); it never
appears post-launch. Measured, not assumed.

**Instrument check:** one query over DREGG's whole 49-day pre-window and 50 separate 24-hour
slices returned the *identical* 12 tweets (symmetric difference 0), so long-window queries
enumerate rather than truncate.

---

## 2. Who they are — and a hole in the inherited classifier

`RESULT_caller_wallets.md` §6 classified callers by **boilerplate share**: the fraction of an
average tweet's words appearing in ≥80% of that account's own tweets. Applied unchanged here:

| class | accounts | share of calls |
|---|---|---|
| human | 123 | 51.2% |
| templated_shill | 15 | 23.4% |
| **high_rate_bot** | **25** | 4.2% |
| automated_relay | 5 | 0.7% |
| project_self | 2 | — |
| unclassifiable (no profile sample) | 314 | 19.8% |

**The §6 method has a hole and this cohort walks straight into it.** 23 of the 33 accounts caught
posting a *shared* template score as "human", because boilerplate is measured **within** an
account — and a farm that posts a different copywriter's line on each coin repeats nothing within
any single account. Within-account novelty, across-account identity.

What separates them is **posting rate**, and the distribution is sharply bimodal: p50 19, p75 81,
**p90 1,029**, max **4,481 tweets/day**. Any threshold in ~150–900 gives the same partition; the
one tuned parameter introduced by this study (`HIGH_POST_RATE = 200`) sits in that plateau. The
resulting `high_rate_bot` class has a median of 1,042 posts/day and 907 followers.

Account age is **not obtainable** through this adapter; posting rate stands in for it.

---

## 3. The cross-coin answer — it is a template, not a roster

Raw overlap is thin:

| called | accounts | mint-bearing only |
|---|---|---|
| one coin | 444 | 229 |
| **two coins** | **38** | 24 |
| **three coins** | **2** | 1 |
| all four | **0** | 0 |

Reading only that table, the answer would be "there is no cross-coin caller base". That reading
is wrong, because **the shared object is the copy, not the handle**:

* a **17-account family** posting variants of *"2X up from my call on $TICKER — CA: …"* across
  **all four coins**;
* a **13-account family** posting *"Watch your entry on $TICKER"* across SOLVE + nosis + weave;
* several groups **character-identical** (cohesion 1.00) across different handles and different
  coins — including an airdrop-phish swarm posting *"OK .. this was random / checked $NOSIS and
  wallet was eligible / just claimed $$$"* word-for-word from @Thegoto1now, @saglikcibeyy and
  @AgussFalon.

Cross-account Jaccard similarity has p50 = 0.031 and p99 = 0.400, so the 0.60 grouping threshold
sits far out in the tail and only **0.40% of account pairs** clear it. These families are not an
artifact of a loose threshold.

**63 of 484 accounts (13%) are machine-classified or template-family, and they produce 50.5% of
all mint-bearing calls.** By coin: nosis 27% of callers, weave 35%, SOLVE 27%, **DREGG 14%**.

### 3.1 The plausible genuine repeat callers

15 of the 25 multi-coin mint-bearing callers show **no** machine or template evidence. These are
the accounts most likely to be real repeat followers of the operator's work, and the only names
in this document worth a human's attention:

@Nik_smoke37 (45 calls), @humblesamble (22), @Andri_Snnn (10), @RikitoBB21yg, @cfm_sol,
@king_cultre, @Knight_Caller11, @emnirex, @caiohollanda, @SovereignMeme4, @Motier_crypto,
@OverseerMD, @inizizi_, @Sealsprincessa, @wang202688.

"No evidence of machinery" is not "verified human". It means they cleared boilerplate, posting
rate and template-family screens.

---

## 4. Was it purchased? The burst null, per coin

A burst of accounts calling one coin within minutes is purchased promotion's signature. The
statistic is the mean number of distinct *other* accounts calling within ±300 s. Two nulls,
2,000 draws, seed 20260815, p-floor 0.0005:

* **naive** — uniform reshuffle. Reported only to size the trap.
* **envelope-preserving** — holds each account's call count and the coin's own coarse temporal
  envelope (60-min kernel) fixed, destroying only sub-5-minute alignment.

| coin | n | accts | observed | naive | p_naive | envelope | **p_env** |
|---|---|---|---|---|---|---|---|
| nosis | 302 | 142 | 3.609 | 0.342 | 0.0005 | 2.178 | **0.0005** |
| weave | 113 | 49 | 0.965 | 0.064 | 0.0005 | 0.560 | **0.0095** |
| SOLVE | 38 | 15 | 0.316 | 0.010 | 0.0005 | 0.165 | **0.1084** |
| **DREGG** | 398 | 74 | 0.043 | 0.034 | 0.2459 | 0.171 | **1.0000** |

**nosis and weave were burst-promoted. SOLVE and DREGG were not.**

nosis's tightest window is **10 distinct accounts inside 300 seconds, 16 minutes after launch**.
DREGG's observed clustering is *below* its own envelope — a clean null — and its tightest window
is 2 accounts, one of which is @ember_arlynx.

The naive null overstates by ~10× on nosis and **would have called SOLVE significant**. The
envelope-preserving null eats most of it and kills SOLVE outright. That is the **fourth** time
this repo has watched a structure-preserving null delete a headline (`RESULT_flow_signals`;
`RESULT_copytrading` 73× → 0.98×; `RESULT_caller_wallets` §2.1 20× → 1.20×). Bandwidth
sensitivity (15 / 60 / 240 / 1440 min) is stable except at 15 min, where the kernel is only 3×
the test window and absorbs the effect by construction.

---

## 5. Limits, stated plainly

* **Four query patterns, not the internet.** Per `RESULT_caller_wallets.md` §6 these are queries
  for links posted by *tooling*. Somebody who wrote "dregg is going to run" with no address and
  no cashtag is invisible here. "First caller" means first in this census.
* **55.2% of rows are cashtag-only.** Without an address they cannot be resolved from text; 30
  are multi-coin posts and the remaining 1,019 are reported as ambiguous rather than counted
  either way.
* **Profile coverage is partial and the machine share is therefore a FLOOR.** 139 of 484 accounts
  have a `from:` sample — 100% of the 40 multi-coin accounts, 58% of the 220 with ≥2 calls, and
  **0% of the 252 single-call accounts**. The 314 "unclassifiable" accounts are a coverage
  statement, not a finding.
* **The referral-link arm is non-functional here** (fired on 6 of 484). X rewrites links to t.co
  and the adapter keeps only visible text, so the expanded host §6 classified on is unavailable.
  Boilerplate plus posting rate carry the classification alone.
* **Account age is unavailable** through this adapter.
* **One life-window per coin, no regime replication.** The four coins launched into four
  different weeks, and this market's regime shifts in weeks (`PROGRAM.md` §3.6).
* The largest cross-coin template group has cohesion min 0.29 — a template *family* with
  variants, not one string. The cohesion-1.00 groups are literally identical text.
* An evidence-tier column exists because the extractor is not the join: 45 rows carry no
  parseable mint but were returned by an address-bearing query, and 1 is an ALL-CAPS
  `SOLANA:8PECVCC…PUMP` that base58 cannot decode. Requiring the extractor to re-find the address
  would have silently dropped all 46.

**Trials: ~21 substantive configurations** (5 pilot shapes, 4 census shapes, 2 control shapes × 4
coins, 4 evidence tiers, 1 template threshold, 1 window × 2 nulls × 4 bandwidths). One new tuned
parameter (`HIGH_POST_RATE`); every other threshold imported unchanged from
`RESULT_caller_wallets.md` §6. Per `PROGRAM.md` §3.9 that argues against reading anything into
SOLVE's p = 0.108, and for the findings that are large and structural: the template families, the
0-of-4 known-zero control, the 50.5%-of-calls-from-13%-of-accounts share, and DREGG's flat null.

---

## 6. What follows

1. **DREGG's promotion looks organic on this instrument, and nosis's does not.** That is the
   operator-facing sentence. It is a statement about *burst structure in a callout census*, not
   about whether anybody was paid — this census cannot see a payment.
2. **Buy `ca` and `cashtag` only** on any rerun. The two URL shapes returned 3 rows and 0 rows
   across 50 full-life slices each.
3. **Fix the §6 classifier upstream** — within-account boilerplate cannot see a farm that varies
   copy per coin, and 23 accounts slipped through as "human". Posting rate is the cheap patch;
   cross-account template clustering is the real one, and it is implemented here.
4. **The 252 single-call accounts are unclassified**, which caps every machine-share number in
   this document as a floor. Profiling them is pure Apify spend and would sharpen §2 and §3.
5. **Do not read the 15 named accounts in §3.1 as endorsements.** They are the residue after
   three screens, on one window, with no wallet link — and `RESULT_caller_wallets.md` §10 is
   explicit that handle→wallet joins do not work.
