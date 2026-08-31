# RESULT: everyone who ever called nosis, DREGG, weave and SOLVE

Operator tasking, verbatim: *"we need to investigate anyone who ever called nosis, dregg, weave,
or solve."*

Code: `studies/cluster_callers.py` (`pilot` / `census` / `profile` / `report`). Data under
`state/callouts/cluster_*` (gitignored); full output at
`state/callouts/cluster_callers_run.txt`. Byte-identical across two runs (seed 20260815).

```
uv run --group research python -m studies.cluster_callers report \
  --census 'state/callouts/cluster_census_*.jsonl,state/callouts/cluster_pre_*.jsonl,state/callouts/cluster_control_pre.jsonl' \
  --profiles 'state/callouts/cluster_profiles*.jsonl' \
  --slices 'state/callouts/*.slices.jsonl' --draws 2000
```

**Spend: $2.51** of Apify (10,036 gross tweets at $0.00025), against a pre-registered $8 gate. A
$0.008 pilot on DREGG's first six hours set the worst-case extrapolation at $2.98 before anything
larger was bought. Every coin's **entire life** was walked — DREGG 49.2 d, SOLVE 25.9 d, weave
11.8 d, nosis 6.4 d — with **0 slices capped** (9 bisections, all resolved), so this is a census
of these query patterns, not a sample thinned by traffic.

---

## 0. Two things the operator should read first

Before the analysis, two findings that are **security matters, not statistics**:

1. **A drainer-bait ring is actively targeting `$NOSIS` holders.** Ten accounts — @FelipAssis,
   @jake_lenhart, @Thegoto1now, @saglikcibeyy, @AaronKnight91 and five more, several posting
   1,000+ tweets/day — run a "claim portal / check your wallet eligibility" template against
   nosis holders, including character-identical text posted from different handles (*"OK .. this
   was random / checked $NOSIS and wallet was eligible / just claimed $$$"*). This is
   wallet-drainer bait wearing the operator's coin as a lure. Its victims are the operator's own
   holders.

2. **A rival `$DREGG` has shared the flagship's ticker since 2026-05-10** — mint
   `Bv7yfJJvYGssW7UYwMqBNxHkX8psurDzsaw6Vu1Dpump`, a duck coin whose dev (@KalebOnChain) says so
   outright, and which predates the operator's DREGG. Any `$DREGG` cashtag search returns both.
   This is why cashtag rows are never merged into the caller roster in this document.

---

## 1. The one-paragraph answer

**About 480 third parties have ever called these coins, and roughly half of the calls that
actually name a contract come from ~63 machine or template accounts — including one shill service
that has worked all four launches.** Across the full life of all four coins: **1,912 (coin,
tweet) rows, 484 distinct accounts** (482 third-party; @ember_arlynx and @DreggNet are separated
out as `project_self`). The cross-coin structure is not a roster of loyal followers, it is a
**template**: a **17-account family** posted the same *"2X up from my call on $X … CA:"* and
*"Watch your entry on $X"* templates on **all four coins, weeks apart**. Every one of those
accounts scores "human" on within-account boilerplate, because each posts a *different* template
each time.

The four coins were **not** promoted alike. Against a null preserving each account's call count
and the coin's own temporal envelope, **nosis and weave carry purchased promotion's fine-scale
signature** (p = 0.0005 and 0.0095); **SOLVE is underpowered** (n = 38, p = 0.108); and **DREGG
shows no burst structure at all** (p = 1.000) — its 201 callers over 49 days are temporally
diffuse, and its clustering sits *below* its own envelope.

**DREGG — the coin that matters most to the operator's income — is the most organic-looking of
the four**, with both the flattest burst null and the lowest machine share (14% of its callers).

---

## 2. The census, and what each query shape is worth

| coin | rows | mint-bearing | cashtag-only | accounts | first call |
|---|---|---|---|---|---|
| nosis | 586 | 302 | 284 | 224 | 2026-08-09 07:46 |
| weave | 204 | 113 | 91 | 76 | 2026-08-03 22:39 |
| SOLVE | 116 | 38 | 78 | 25 | 2026-07-20 23:31 |
| DREGG | 994 | 398 | 596 | 201 | 2026-06-27 13:47 |
| **total** | **1,912** | **851** | **1,049** | **484 distinct** | |

The 851 mint-bearing rows are evidence-tiered: 805 found by the extractor, 45 returned by an
address-bearing query but carrying no parseable mint, and 1 an ALL-CAPS `SOLANA:8PECVCC…PUMP`
that base58 cannot decode. Requiring the extractor to re-find the address would have silently
dropped all 46 — the extractor is not the join.

**Two of the four tasked query shapes are dead weight**, which is a reusable measurement:

| shape | rows | precision (mint-bearing) |
|---|---|---|
| **bare contract address as text** | 768 | **100.0%** — this is the whole instrument |
| cashtag | 1,724 | **39.2%** |
| `url:pump.fun/<mint>` | 3 | fully subsumed by the `ca` query |
| `url:dexscreener.com/solana` | **0** | — |

X indexes the address *inside* the expanded URL, so the bare-address query already returns the
link posts. A rerun should buy `ca` and `cashtag` only.

### 2.1 Both controls ran, and one of them found the rival coin

`PROGRAM.md` §3.12 demands a known-zero and a known-effect arm; both ran, with slice manifests
proving the windows were actually asked for.

**Known-zero:** the `ca` query over each coin's *pre-creation* mirror window (154 / 283 / 622 /
1,181 hours) returned **0 hits on all four**. The instrument does not manufacture callouts.

**Cashtag background:** 0 pre-creation hits for `$SOLVE`, `$weave` and `$nosis` — so for those
three the ticker is genuinely quiet before launch. `$DREGG` returned **12**, and that is how the
rival duck coin in §0 was found. So DREGG's cashtag-only rows are **partly about a different
coin**, and merging cashtag rows into the caller roster would be wrong. They are reported
separately throughout and never enter the caller or burst analyses.

**Instrument check:** one query over DREGG's whole 49-day pre-window and 50 separate 24-hour
slices returned the *identical* 12 tweets (symmetric difference 0), so long-window queries
enumerate rather than truncate.

---

## 3. Who they are — and a hole in the inherited classifier

| class | accounts | share of calls |
|---|---|---|
| human | 123 | 51.2% |
| high-rate bot (median **1,042 tweets/day**) | 25 | } |
| templated shill | 15 | } **28.3%** |
| automated relay | 5 | } |
| project_self (@ember_arlynx, @DreggNet) | 2 | — |
| unclassifiable — no profile sample | 314 | 19.8% |

**The §6 boilerplate method inherited from `RESULT_caller_wallets.md` has a hole, and this cohort
walks straight into it.** Boilerplate is measured *within* an account. A shill service that posts
a **different** copywriter's line on each coin repeats nothing within any single account, so its
members all score "human". Within-account novelty, across-account identity.

What separates them is **posting rate**, sharply bimodal: p50 19, p75 81, **p90 1,029**, max
**4,481 tweets/day**. Any threshold in ~150–900 gives the same partition, so the one tuned
parameter this study introduces (`HIGH_POST_RATE = 200`) sits on a plateau rather than being
fitted.

The referral-link arm from §6 is **honestly unmeasured here**: X collapses links to t.co and the
adapter keeps only visible text, so the expanded host is unavailable. Referral classification is
a floor. Account **age** is unobtainable through this adapter; posting rate stands in.

---

## 4. The cross-coin answer — it is a template, not a roster

Raw overlap is thin, and two of its three top entries are not people:

| called | accounts | mint-bearing |
|---|---|---|
| one coin | 444 | 229 |
| **two coins** | **38** | 24 |
| **three coins** | **2** | 1 |
| all four | **0** | 0 |

The two three-coin accounts are **@dex_kolwatcher** (an automated relay) and **@AlphaWhalesX**
(cashtag-only). SOLVE ∩ DREGG mint-bearing overlap is **0**. Overlap concentrates in
**nosis ∩ weave** (11 mint-bearing) — the two most recent launches, consistent with the same
shill service being hired for both.

Reading only that table, the answer would be "there is no cross-coin caller base". That is wrong,
because **the shared object is the copy, not the handle**:

* **42 accounts** posted near-identical text (Jaccard ≥ 0.6 on ticker-stripped text);
* a **17-account family** used the *"2X up from my call on $X … CA:"* / *"Watch your entry on
  $X"* templates on **all four coins**, weeks apart — a **standing paid-shill service that gets
  hired every launch**;
* plus the **$NOSIS drainer-bait ring** of §0 and a **Moonshot vote-farm ring** on nosis + weave.

The similarity threshold is not doing the work: cross-account Jaccard has p99 = 0.40, so 0.6 sits
above the 99th percentile of the distribution.

**Machine-or-template accounts total 63 of 484 and produce 50.5% of all mint-bearing calls** —
nosis 27% of callers, weave 35%, SOLVE 27%, **DREGG 14%**. That 50.5% lands almost exactly on
`RESULT_caller_wallets.md` §6's independently-derived 51.4% machine share of the general callout
feed, by a different method on a different cohort.

### 4.1 The plausible genuine repeat callers

After removing machine and template accounts, **15 multi-coin callers remain with no bot
evidence** — the accounts most likely to be real repeat followers of the operator's work:

@Nik_smoke37 (45 calls), @humblesamble, @cfm_sol (28.6k followers), @Andri_Snnn,
@king_cultre (early on **both** DREGG at +6.0 h and weave at +2.3 h), @emnirex, @RikitoBB21yg,
@SovereignMeme4, @Motier_crypto, @OverseerMD, @inizizi_, @wang202688, @Sealsprincessa,
@Knight_Caller11, @caiohollanda.

"No evidence of machinery" is **not** "verified human" — they cleared boilerplate, posting-rate
and template-family screens, on one window, with no wallet link.

---

## 5. Was it purchased? The burst null, per coin

The statistic is the mean number of distinct *other* accounts calling within ±300 s. Two nulls,
2,000 draws, seed 20260815, p-floor 0.0005. The **envelope-preserving** null holds each account's
call count and the coin's coarse temporal profile fixed, destroying only sub-5-minute alignment;
the **naive** uniform null is reported solely to size the trap.

| coin | n | observed | envelope null | **p_env** | naive p |
|---|---|---|---|---|---|
| **nosis** | 302 | 3.61 | 2.18 | **0.0005** | 0.0005 |
| **weave** | 113 | 0.97 | 0.56 | **0.0095** | 0.0005 |
| SOLVE | 38 | 0.32 | 0.17 | 0.108 | 0.0005 |
| **DREGG** | 398 | 0.04 | 0.17 | **1.000** | 0.246 |

**nosis and weave carry purchased promotion's fine-scale signature.** nosis's tightest window is
**10 distinct accounts inside 5 minutes, at launch + 16 minutes**. weave's is a 5-account window
on 2026-08-12 — **8.8 days *after* launch**, which matches its otherwise odd arrival profile
(median call at +8.8 d). So the two bursts are different products: nosis was boosted at birth,
weave was boosted long after.

**SOLVE is underpowered**, not cleanly null — n = 38.

**DREGG shows no burst structure at all.** Its clustering sits *below* its own envelope, its
tightest window is two accounts (one of them @ember_arlynx), and its 201 callers spread diffusely
over 49 days.

The naive null would have called **SOLVE significant** and overstated nosis. The
envelope-preserving null eats most of that. This is the **fourth** time this repo has watched a
structure-preserving null delete a headline (`RESULT_flow_signals`; `RESULT_copytrading`
73× → 0.98×; `RESULT_caller_wallets` §2.1, 20× → 1.20×). Bandwidth sensitivity was swept
15 min – 24 h; verdicts are stable from 60 min up, and at 15 min the kernel is only 3× the test
window and absorbs the effect by construction.

---

## 6. Limits, stated plainly

* **These queries see tooling-shaped posts only** — pasted contract addresses and launchpad
  links. Somebody who wrote "dregg is going to run" in prose is invisible. "First caller" means
  first *in this census*.
* **1,049 cashtag-only rows are mostly unresolvable** (1,019 name no contract; 30 provably name
  other coins, including the rival `$DREGG`). They never enter the caller or burst analyses.
* **The machine share is a FLOOR and the human share an UPPER BOUND.** 252 single-call accounts
  have no profile sample at all (cost cut-off); profiles were bought for 100% of multi-coin
  callers and 58% of ≥2-call accounts. And humans hired per-post are still "human" by every text
  measure — the template families are exactly where that bound visibly breaks.
* **Referral classification is a floor** (t.co); **account age is unavailable**.
* **One life-window per coin, no regime replication.** The four launched into four different
  weeks, and this market's regime shifts in weeks (`PROGRAM.md` §3.6).
* The `url_dex` lane covered 37/100 DREGG days before being cut as redundant (0 yield, subsumed
  by `ca`); 1 of 53 priority profile handles (@solanalantarn) failed to fetch.
* The largest cross-coin template group is a template *family* with variants, not one string;
  the character-identical groups are called out separately as such.

**Trials: ~10 substantive configurations** — 4 coins × 2 nulls at one pre-chosen window, plus the
disclosed bandwidth sweep and one template threshold shown against its full distribution. That is
at or under `PROGRAM.md` §3.9's ~7-config deflation bar for the headline claims, all of which are
either structural counts or p ≤ 0.01. It argues specifically against reading anything into
SOLVE's p = 0.108.

---

## 7. What follows

1. **Warn holders about the `$NOSIS` claim-portal ring** (§0). This is the only item here with a
   deadline attached, and it needs no further measurement.
2. **The rival `$DREGG` predates nothing the operator can change**, but every cashtag-based
   metric on the flagship is contaminated by it. Anything counting `$DREGG` mentions must
   resolve to a mint first.
3. **DREGG's promotion looks organic on this instrument; nosis's and weave's do not.** That is a
   statement about *burst structure in a callout census*, not about whether anybody was paid —
   this census cannot see a payment.
4. **Buy `ca` and `cashtag` only** on any rerun. The two URL shapes returned 3 rows and 0 rows.
5. **Fix the §6 classifier upstream.** Within-account boilerplate cannot see a farm that varies
   copy per coin. Posting rate is the cheap patch; cross-account template clustering is the real
   one, and it is implemented in `cluster_callers.py`.
6. **Do not read §4.1's fifteen names as endorsements.** They are the residue after three
   screens, and `RESULT_caller_wallets.md` §10 is explicit that handle→wallet joins do not work.
