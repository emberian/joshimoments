# RESULT: the callout channel — measured at last, and it is a null with a sign

Run 2026-08-15 with the price tape pinned:

```
uv run --group research python -m studies.callout_edge --report --source boards \
    --tape-end 1786767709
```

The pin matters — the collectors are live, so every extra minute of tape makes one more row
8 h-eligible and moves the 8 h numbers. The full output of that command is at
`studies/data/callout_edge_run.txt` (untracked: `studies/data/` is gitignored) and reproduces
exactly from the tapes in `state/`.

Code: `studies/callout_edge.py`, `studies/callout_backfill.py`, `studies/callout_prices.py`.
Collector changes: `shitcoims_intelligence/adapters/x_apify.py`,
`shitcoims_intelligence/runtime.py`, `shitcoims_intelligence/cashtag_resolver.py`,
`shitcoims_scalper/boards.py`, `shitcoims_scalper/feed.py`, `ops/*.plist`,
`scripts/install-research-collectors.sh`, and `intelligence.example.yaml` (the live
`intelligence.yaml` is gitignored, so the tuned settings ship in the example file).

---

## 0. The one-paragraph answer

**A callout carries no information about forward return over the free numeric columns, and
the caller-identity block is worse than noise.** On 314 callouts over 222 mints, temporally
split with no mint straddling: free columns alone score **AUC 0.796 [0.695, 0.886]** at 1 h
against a 22.7% base rate; callout columns alone score **0.471 [0.354, 0.568]**, a CI
straddling chance; and adding the callout block to the free columns *lowers* the score to
**0.665**. Permuting caller identity — scrambling who said it while keeping every timing and
market feature — **raises** test AUC to 0.719, beating the real assignment in 24 of 24 draws.
Both label nulls are dead flat (0.497 i.i.d., 0.500 rotation, p = 0.000 against the free+callout
model), so the model does hold real signal; all of it is in the free columns.

The direction is worth stating separately from the significance. Every loudness proxy points
the same way: buying on a callout returns **−11.9% at 1 h** and **−43.6% at 8 h**, and the
louder the callout the worse it gets — two or more callers within ten minutes returns
**−64.7% median −89.7% at 8 h**, a caller with over 10k followers returns **−65.8%**, and a
caller with under 1k followers returns **−23.0%**. Entity-level Spearman of caller followers
against the 8 h return is **ρ = −0.502, p < 0.0001** on 101 mints.

This does not refute the operator's original strategy. It refutes *buying what the feed says*.
§6 is explicit about which version of the hypothesis survives.

---

## 1. Step zero: three collectors were down at once

The brief said the intelligence daemon had run dead for ~24 h. It had, and it was worse than
that: **all three data sources were dead or crippled simultaneously**, and none of them were
supervised.

| collector | state found | cause |
|---|---|---|
| `inteld` (X/social) | running, `source_health = degraded`, `error_code = cycle_budget_exhausted`, `last_success_at` **null since inception** | budget and timeout misconfiguration, below |
| board recorder | **dead since 00:21 UTC**, ~3.4 h of no price tape | `--minutes N` one-shot that simply ended; no supervisor |
| pumpportal firehose | **dead since 00:51 UTC**, total lifetime 10 minutes | run once by hand with `--minutes 3` twice |
| `claudekol` | 0 rows in 24 h | **not our bug** — the upstream feed's newest action is `2026-08-13T07:34Z`. The adapter fetches it correctly today; the source stopped publishing. |

`~/Library/LaunchAgents/com.shitcoims.inteld.plist` existed but was **not loaded**, and the
label sat in launchd's disabled override database — which is why bootstrapping it failed with a
bare `Input/output error` and why somebody had resorted to `nohup`. That is the structural
reason a collector could die unnoticed for a day. Fixed by `scripts/install-research-collectors.sh`,
which `enable`s before `bootstrap`ping (the order matters and is the whole bug) and puts
`inteld`, `boards` and `firehose` under `KeepAlive`. All three are now supervised and running.

### 1.1 Why the X collector produced almost nothing

Four independent defects, each measured:

1. **A naked contract address in tweet text was never extracted.** `_extract_mint_candidates`
   matched four URL patterns only. The canonical callout shape — `CA: 3YS3sW…pump`, or the
   address pasted bare — produced zero mint candidates. Measured on the stored corpus: 27 of
   2,344 tweets carried a bare address the extractor missed, against 45 it caught by URL. On
   fresh queries the effect is much larger: `url:axiom.trade` yields 0.70 distinct mints per
   purchased tweet and **not one of them came from a URL match** — every one was rescued by the
   new bare-address extractor. `"CA" pump` likewise: 0.65 mints/tweet, all bare.
2. **Results already paid for were thrown away.** The pinned actor bills $0.00025 per returned
   tweet and returns ~20 regardless of a smaller `maxItems`; the adapter truncated to `limit`,
   so a `max_items_per_query: 6` config paid for 20 tweets and kept 6.
3. **The query timeout was below the measured query latency.** `QUERY_TIMEOUT_SECONDS = 20`
   against a measured ~15 s round trip, so ordinary tail latency tripped it, and each timeout
   burned 20 s of a 90 s cycle slice for nothing. Every `x_query_timeout` in `source_health`
   traces here. Now 45 s.
4. **The cycle budget could not finish a rotation at any latency.** 15 work items × ~15 s = 225 s
   against a 90 s slice, at a 1,800 s poll interval — so a single pass over the KOL list took
   hours, and the hard daily item cap then stopped collection entirely for the rest of the day.
   That last part is a *sampling* bug, not a throughput one: every callout after the wall is
   invisible and the surviving hours are not a random sample of the day. Replaced with a
   **rate-shaped per-cycle allowance** (`remaining_today / cycles_remaining_today`) so the budget
   lasts the day, plus discovery-first ordering.

Two correctness bugs found along the way:

- **`x_kol_post` claimed authorship that did not exist.** The record was emitted for *any* tweet
  collected under a KOL's watch, including thread replies by strangers — `subject_id =
  notthreadguy` on a tweet written by `Dontelol1`, at the highest confidence (0.55) of any X
  kind. 1,093 such rows existed. Now only genuine authorship becomes `x_kol_post`; the rest
  become `x_kol_thread` at confidence 0.30 with `authored_by_kol: false`.
- **`re.I` on the CA-marker regex silently broke base58 validity**, re-admitting `l`, `I` and `O`
  through their opposite-case counterparts and producing unusable lowercased addresses. The
  address half of the pattern is now case-sensitive, and every bare candidate must decode to
  exactly 32 bytes (`is_solana_mint`). `shitcoims_scalper/feed.py:_b58_mintish` — which gates the
  **live** scalper — was a length-plus-forbidden-character test that admitted any base58-shaped
  string; it now decodes.

**Measured effect.** Mint-resolved callouts, `x_mint_mention`: **46 rows in the three days
before** the fix; **78 rows in the 28 minutes after**. That is ~15/day → ~4,000/day, a factor of
about 260, at a cost of ~$0.60/day. `source_health` went from `degraded / cycle_budget_exhausted`
with a null `last_success_at` to `healthy`.

Discovery-query yield, measured 2026-08-15 (distinct mints per purchased tweet), which is what
the new `intelligence.yaml` query list is ordered by:

| query | mints/tweet |
|---|---|
| `url:dexscreener.com/solana` | **0.95** |
| `url:axiom.trade` | 0.70 |
| `"CA" pump` | 0.65 |
| `url:pump.fun` (the only one previously configured) | 0.45 |
| `pump.fun` | 0.35 |
| `$SOL pump.fun -filter:retweets` | 0.15 |

---

## 2. The unlock: callouts are retrospectively collectable

The reason nobody could test this channel is that the two tapes never overlapped —
`RESULT_llm_filter.md` §8.1 records 10 of 333 cohort mints appearing in the intelligence store.
Waiting for the live collector to accumulate would have taken days.

It turns out the pinned Apify actor **honours X's `since_time:` / `until_time:` search
operators**. A query bounded to a past window returns only tweets inside it. So the callout
stream can be reconstructed over exactly the window where prices already exist.

`studies/callout_backfill.py` walks the window in 30-minute slices across four discovery
queries. Over the board tape's 10 hours (2026-08-14 14:21 → 2026-08-15 00:21 UTC):

- 80 queries, **724 tweets, 459 carrying a mint, 0 failures**
- **0 slices hit the actor's result cap** — so this is a *census* of those query patterns over
  that window, not a sample thinned by whatever the daemon happened to catch. Cap-hits are
  recorded per slice precisely so truncation could never be invisible.
- Cost: ~$0.18.

---

## 3. The instrument, and why the boards tape is used with a known bias

Callout mints are priced two ways.

**GeckoTerminal minute candles** price a pool whether or not anyone is watching, which is the
right instrument in principle: it removes the board-presence selection and lets a dying coin be
*priced* rather than dropped. In practice the keyless tier serves about five requests and then
429s for a long while — measured, not assumed — so only 29 rows were priced this way within the
session. `studies/callout_prices.py` keeps grinding in the background with its own pacing file
(sharing `deterioration`'s pacing file was itself causing self-inflicted throttling) and a
**seeded random mint order**, so that whatever it finishes is an unbiased subset rather than a
biased prefix.

**The board tape** prices 74.8% of callout mints for free at 30-second cadence — much higher
coverage than expected, because the `last_trade_timestamp` board churns every few minutes and a
freshly-called coin is by construction a freshly-traded one. Its bias is exactly the one this
repo has already been burned by, so it is measured rather than argued about (§4).

Neither source ever drops a row for being censored. A quiet pool is marked at its last traded
price — that is a real price at which someone actually transacted, and it is never look-ahead —
with staleness reported alongside, because a stale mark is a real *return* but not a plausible
*fill*. At 1 h only 34.1% of marks are live; at 8 h, 6.5%.

**Unpriced callouts are itemised, not silently dropped:** of 437 callouts, 96 belong to mints
GeckoTerminal has not been asked about yet, 7 to mints with no indexed pool at all (the "callout"
named something untradeable), and 20 to coins that had not traded once at the moment of the call
— the only genuinely legitimate exclusion, since there is no entry price to compute a return
from.

---

## 4. The censoring trap, reproduced on the callout population

`RESULT_board_entry.md` reported +21.77% at 8 h; `RESULT_bandit_search.md` showed that pricing
the censored 96% instead of dropping them reverses it to −12.24%. That correction was made on the
board-entry cohort. Here it is again, on *this* cohort, measured directly by pricing the same 25
(mint, t_post) pairs under both instruments:

| 1 h | mean | median | p(up) |
|---|---|---|---|
| GeckoTerminal — prices everyone | −14.60% | −20.41% | 17.8% |
| boards, mark-at-last-price (**what this study uses**) | −9.99% | −8.21% | 13.3% |
| boards, **censored rows dropped** | **+25.00%** | −7.12% | **30.0%** |

Only 44.4% of rows survive the drop-censored filter at 1 h, and the survivorship gap is
**+39.6 pp of mean return and +12.2 pp of p(up)**, manufactured out of nothing but the exclusion
rule. It flips the sign of the answer: price everyone and a callout loses 14.6% in an hour; drop
the ones that stopped trading and the same callouts appear to make 25%. n = 45 pairs, so treat
the magnitude as a demonstration rather than an estimate — but the sign and the scale are
unambiguous, and they are the same failure that produced this repo's worst published number.
(An earlier pass with 25 pairs put the gap at +49.4 pp; more coverage moved the magnitude, not
the direction.)

**Leaving the boards is modelled as a competing risk, not as missingness.** Where a called coin
actually ends up (`lifelines`, exclusive states):

| horizon | up | down | **dead** |
|---|---|---|---|
| 1 h | 15.6% | 36.3% | **48.1%** |
| 8 h | 6.7% | 17.5% | **75.8%** |

Kaplan-Meier median survival from the moment of the callout is **1.19 hours**. Any "8 h return"
computed on survivors is a return multiplied by a 24% survival probability and reported as though
that factor were 1.

Administrative censoring is handled separately and in the right order: rows whose horizon runs
past the tape are dropped *before* the temporal split, not after. Doing it after empties the test
set entirely — the late callouts are exactly the ones lacking 8 h coverage — which is why an
earlier pass of this study reported the 8 h horizon as unmeasurable when it merely needed the
filter applied first.

---

## 5. The result

Cohort: **314 callouts on 222 mints**, 2026-08-14 14:22 → 2026-08-15 00:20 UTC. Median mint has
1 callout, max 5; every metric clusters on mint, and confidence intervals resample **mints**, not
rows — the correction `RESULT_llm_filter.md` §3 had to apply when 1,271 board-entry rows turned
out to be 189 mints.

### 5.1 Returns — buying the callout loses, and loudness makes it lose more

All rows, censored marked never dropped:

| subset | n | 1 h mean | 1 h median | p(up) | n | 8 h mean | 8 h median | p(up) |
|---|---|---|---|---|---|---|---|---|
| all callouts | 314 | −11.88% | −5.11% | 19.4% | 139 | **−43.61%** | −66.16% | 10.8% |
| first caller only | 220 | −7.83% | +0.00% | 18.2% | 101 | −38.36% | −58.00% | 10.9% |
| a later caller | 94 | −21.34% | −28.12% | 22.3% | 38 | −57.57% | −80.52% | 10.5% |
| **burst ≥ 2 callers / 10 min** | 45 | **−40.41%** | −65.71% | 15.6% | 22 | **−64.72%** | −89.67% | 9.1% |
| caller ≥ 10k followers | 6 | −37.84% | −37.42% | 16.7% | 4 | −65.79% | −78.49% | 0.0% |
| caller < 1k followers | 208 | **−5.32%** | +0.00% | 21.2% | 71 | **−23.01%** | −18.22% | 14.1% |

Entity-level (first call per mint, the honest denominator): **1 h n = 222, mean −7.76%,
p(up) 18.0%**; **8 h n = 101, mean −38.36%, median −58.00%, p(up) 10.9%**.

The loudness gradient is monotone and large in both horizons and at both levels of aggregation.
The mechanism is visible in the covariates and is not mysterious: a loud callout arrives on a
coin that has **already moved**. Median market cap at the moment of the call is $154k for a
>10k-follower caller, $37k for a multi-caller burst, and $14.6k for a <1k-follower caller; median
drawdown-from-60-min-peak at the call is +0.10 for the big caller and +0.33 for the small one.
The big accounts are buying nearer the top, and their followers arrive later still.

### 5.2 Discrimination — the callout block loses to the free columns and hurts them

Temporal split, mint never straddles, no resampling, base rate stated with every number.

**1 h** — train 164 rows / 117 mints, test 150 rows / 105 mints, test base rate p(up) = 22.7%:

| model | AUC [mint-clustered 95% CI] | AUPRC (base 0.227) |
|---|---|---|
| **free columns only** | **0.796 [0.695, 0.886]** | **0.504** |
| callout columns only | 0.471 [0.354, 0.568] | 0.219 |
| free + callout | 0.665 [0.560, 0.760] | 0.335 |
| free + callout, *with* leaky engagement counters | 0.662 [0.551, 0.758] | 0.344 |
| best single free column (`log_mcap`) | 0.772 | — |

**8 h** — train 77 rows / 54 mints, test 62 rows / 47 mints, test base rate p(up) = 12.9%:

| model | AUC [mint-clustered 95% CI] | AUPRC (base 0.115) |
|---|---|---|
| free columns only | 0.625 [0.396, 0.946] | 0.391 |
| callout columns only | 0.385 [0.211, 0.596] | 0.116 |
| free + callout | 0.549 [0.373, 0.795] | 0.195 |
| **best single free column (`log_mcap`)** | **0.775** | — |

Two things to read off this. The callout block does not merely fail to add — **it subtracts**,
0.796 → 0.665 at 1 h and 0.625 → 0.549 at 8 h. And a single free column beats every fitted model
at 8 h, which is the same shape as `RESULT_llm_filter.md`'s finding that a plain drawdown column
(ρ = +0.321) beat nine arms of verbalised judgement.

The brief's two baseline claims both reproduce: **market cap is the best single free column at
8 h** (AUC 0.775 against every fitted model's 0.625 or less; entity-level ρ = −0.341, p = 0.0005) and **age is the best at 1 h**
(entity-level ρ = **+0.303**, p < 0.0001, against market cap's −0.169 and drawdown's +0.175).

### 5.3 The nulls, and the one that matters

Test-set AUC of the free+callout model under each null, 24 draws each:

| null | AUC | 5–95% | p(null ≥ observed) |
|---|---|---|---|
| i.i.d. label shuffle | 0.497 | [0.402, 0.578] | **0.000** |
| label rotation (preserves autocorrelation) | 0.500 | [0.410, 0.578] | **0.000** |
| **caller identity permuted** | **0.719** | [0.680, 0.756] | **1.000** |

The first two matter because `RESULT_flow_signals.md` and `RESULT_copytrading.md` both found a
naive null manufacturing an effect that an autocorrelation-preserving null killed (73× → 0.98×).
Here the two agree exactly — 0.497 vs 0.500 — so the model's discrimination is real and not a
null artifact. The autocorrelation trap is not operating on this cohort.

The third null is the hypothesis test itself, and it is the finding. Scrambling *who said it*
while leaving every timing and market feature untouched **raises** test AUC from 0.665 to 0.719,
and beat the real assignment in 24 of 24 draws at 1 h (and 23 of 24 at 8 h, AUC 0.633). Real caller identity
is worse than random caller identity out of sample: the identity features encode a train-period
pattern that reverses. This is the same phenomenon `RESULT_llm_filter.md` measured for the
content channel at p = 0.0008, arrived at independently through a different door.

### 5.4 Mint-clustered inference

Logit on the full cohort, `cov_type="cluster"` on mint (n = 314, 222 mints at 1 h; n = 138, 100
mints at 8 h). **Not one callout coefficient reaches p < 0.05 at 1 h.** The two closest are
`log_followers` β = −0.297, p = 0.094 and `verified` β = +0.304, p = 0.084. At 8 h `log_followers`
reaches β = −0.685, **p = 0.047** — the only nominally significant callout coefficient in the
study, and it is *negative*. With the trials count in §7 that does not survive deflation.

Note the gap between the raw and conditional follower effect: entity-level Spearman is
ρ = −0.502 (p < 0.0001) at 8 h, but conditioning on the free columns collapses it to p = 0.047.
Almost the whole follower association is *which coins big accounts choose to call*, not what
happens because they called it.

### 5.5 Survival — the one place callout features do carry something

Cox proportional hazards on time-from-callout-to-last-trade, mint-clustered, concordance 0.762.
Event = the coin stops trading; 240 deaths in 314 rows.

| covariate | hazard ratio | p |
|---|---|---|
| `log_mcap` | 0.842 | < 0.0001 |
| `log_age_s` | 0.827 | 0.0008 |
| **`is_first_caller`** | **1.365** | **0.0049** |
| **`caller_prior_hit_rate`** | **0.433** | **0.0053** |
| **`caller_prior_calls`** | **0.986** | **0.0142** |
| `drawdown_60m` | 1.857 | 0.0140 |

Three callout features move the death hazard. Being the *first* caller we observed raises the
hazard 36% — you are early to something that dies sooner. A caller whose earlier, already-resolved
calls went up more predicts a coin that survives longer (HR 0.437). These are survival statements
and are reported only as survival statements: **a coin that lives longer is not a coin that goes
up**, and the return analysis in §5.2 says the return channel stays empty even where the survival
channel does not.

An earlier pass of this study had `log_views` as the strongest survival covariate (HR 0.649,
p < 0.0001). It was removed: the scraper reads a tweet's view count whenever it collects it,
which for a backfill is hours later, so a coin that stayed alive and kept attracting clicks lends
its own future to the feature. That is look-ahead, and it is the exact mechanism behind this
field's 0.95 AUCs. It is retained only in the "leaky" arm of §5.2, where it still fails to win.

---

## 6. What this does and does not refute

**Refuted, on this window:** buying a coin because the callout feed named it. At 1 h it returns
−11.9%, at 8 h −43.6%, half the coins are dead within the hour, and no callout feature helps you
choose among them. **Refuted more sharply:** following the loud callouts. Every loudness proxy —
follower count, caller count, burst, being a later caller — is monotonically *worse*, and the
mechanism is that loud callouts land on coins that already ran.

**Not refuted:** the operator's actual described behaviour, which was clicking every coin in the
feed and *glancing at it* — i.e. using the feed as a **candidate generator** and then applying
judgement from the free numeric columns. That version is not only unrefuted, it is directly
supported here: on the callout-generated population the free columns score AUC 0.796 at 1 h
against a 22.7% base rate, comfortably clear of both nulls at p = 0.000. The feed's value is that
it hands you a population; the judgement has to come from the numbers, not from who is shouting.

The distinction is decidable and worth the next study: this cohort cannot say whether the
callout-generated population is *better* than a random contemporaneous population, because there
is no matched control arm. That is the one experiment this instrument is now positioned to run
cheaply, and §8 makes it the top item.

---

## 7. Trials accounting and honest limits

Configurations evaluated: **18 per reported run** (2 horizons × [4 model column sets + 5 single
free columns]), across roughly 3 substantive runs plus the censoring check and two feature-set
revisions — call it **~30 configurations**. PROGRAM.md §3.9: past ~7 independent configurations,
an in-sample Sharpe of 1 corresponds to OOS zero. Applied here that is a strong argument *for*
the null and against reading anything into the single p = 0.047. The findings offered as real —
the returns, the loudness gradient, the identity-permutation null — are all large, monotone, and
consistent across horizons and aggregation levels rather than marginal.

Limits, stated plainly:

- **One 10-hour window, one day.** Regime shift in this market is measured in weeks
  (PROGRAM.md §3.6). Nothing here is a claim about next Tuesday.
- **8 h rests on 139 rows / 101 mints** after administrative censoring, and 93.5% of its marks
  are stale. The 8 h CIs are correspondingly wide (free columns [0.396, 0.946]). Because the
  collectors are live, an unpinned rerun shifts these as the tape grows — hence the pin.
- **The censoring comparison is n = 45 pairs.** Its sign is solid; its magnitude is not an
  estimate. GeckoTerminal coverage is still filling in and will sharpen it without any new code.
- **Only 6 rows have a >10k-follower caller.** The strongest-looking cell in §5.1 is the weakest
  by count; the entity-level ρ = −0.502 on 101 mints is the number to trust, not that row.
- **Callout order is order among callouts we observed.** "First caller" means first in a census
  of four discovery queries, not first on the internet.

---

## 8. What the cashtag channel turns out to cost

`x_cashtag` observations outnumber `x_mint_mention` roughly 5:1 and have always been a dead end,
because a ticker is not an address. With the firehose running, `shitcoims_intelligence/
cashtag_resolver.py` can now resolve `$TICKER` → mint against pump.fun launches — refusal-first,
resolving only when exactly one launch in the lookback window carries the ticker, and never
looking past the tweet's own timestamp.

Measured on 3.55 hours of firehose (859 launches, 242/hour): **only 23.6% of launches have a
ticker unique within ±30 minutes**, and widening the window to ±2 h does not change the number,
because the duplicates are simultaneous spam bursts — `READDDDDDDDDD` was launched 41 times,
`SOLANA` 38 times. So roughly **three quarters of the cashtag channel is unjoinable in
principle**, not merely unimplemented. That retroactively justifies the adapter's refusal to
treat cashtags as mints, and it caps what this channel can ever contribute.

The resolver ships with both controls PROGRAM.md §3.12 demands, and its current verdict is
honest: on 72 known-effect pairs (a tweet carrying both a cashtag and a URL-derived mint) it
resolves **0** — 70 `not_launched`, 2 `out_of_window` — because the firehose tape does not yet
reach back to those tweets. The known-zero arm is green at 0 false positives in 40. **A green
zero-control alone would have certified a constant-refuse resolver as working**, which is exactly
the failure §3.12 was written about; the paired control is what exposes it. The resolver is
unvalidated until the firehose has a day of history, and it is labelled as such.

---

## 9. Next, in priority order

1. **The matched control arm.** §6's open question. Sample a contemporaneous random coin for each
   callout, matched on market cap and age at the callout instant, and ask whether the
   callout-generated population outperforms it. The board tape supplies the matching pool for
   free; `board_entry.py`'s null already does the "random coin in view at the same instant" draw.
   This decides whether the feed is worth opening at all, and it needs no new collection.
2. **Let the tapes run and re-run this file.** Everything is now supervised and accumulating:
   boards at 30 s, firehose at ~19 creates/min, X at ~4,000 mint-mentions/day. A week gives a
   multi-regime cohort and an 8 h horizon that is not 93.5% stale.
3. **Finish GeckoTerminal coverage and re-run §4.** The censoring gap deserves an estimate, not a
   demonstration. Background collection is already running.
4. **Validate the cashtag resolver** once the firehose has 24 h of history, using the known-effect
   arm that already exists. If precision holds above ~0.9 on the resolvable 24%, the cashtag
   channel becomes joinable and this whole study can be re-run on ~5× the callouts.
5. **Do not build a callout-following strategy.** This is the result. The channel is a candidate
   generator, and everything past that is the free numeric columns.
