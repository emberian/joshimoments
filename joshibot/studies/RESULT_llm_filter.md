# RESULT: the LLM glance costs 40 seconds and half a cent, and on this cohort it knows nothing

2026-08-15. `studies/llm_filter.py` over `state/boards/`, six screening arms, 945 model
calls, **$3.19 measured spend**. The question was whether an LLM's few-second look at a
coin — name, description, image, socials, the vibe — carries information that five numeric
comparisons do not. On the cohort we can actually evaluate, it does not, and the
content-free control scores *better* than the sighted one.

---

## 1. The invocation path that actually exists

The operator said "grok cli" and grok CLI is genuinely installed. Reported rather than
assumed, because the shape of it determines every latency number below.

| | |
|---|---|
| binary | `~/.grok/bin/grok` → `~/.grok/downloads/grok-1.0.3-macos-aarch64` |
| auth | `grok.com` session (`auth_method: "session"` in `~/.grok/models_cache.json`); **no** `XAI_API_KEY`/`GROK_API_KEY` in the environment |
| models | `grok-4.6` (default), `grok-4.5`; the backend bills as `grok-4.6-build` |
| headless | `grok -p PROMPT --output-format json --json-schema '{…}'` |
| returns | `text`, `structuredOutput`, `usage{input,output,cache,reasoning}`, and **`total_cost_usd`** |

That last field is why every cost in this report is *measured* rather than estimated — the
CLI does its own accounting and we read it.

**There is no raw-API path on this machine.** `grok` is an *agent harness*, not a completion
endpoint: it boots a process, loads a system preamble, and runs a turn. A 1.1 KB prompt bills
~10.4k input tokens on average. That overhead is not a defect to optimise around here — it is
the thing being measured, because it is what a production screen would actually pay.

**The Claude path exists and was deliberately not used.** `tokeman`
(`~/.cargo/bin/tokeman`) fronts five OAuth accounts, two healthy at run time (`account A`
2% weekly, `account B` 62%; `account C` at 94%, `account D` exhausted, `account E`
403 `oauth_not_allowed_for_organization`), and `~/dev/allgame/claude_resident/` is the
established pattern — `auth.py:choose_account` drains the *most*-used account first so weekly
remainders do not expire unused, and `sdk_call.py` runs one-shot completions through the Agent
SDK so sidecars bill against plan limits rather than metered credit. Adding it is one class
against the `Backend` protocol in `llm_filter.py`. Grok was used because the operator named it
and because it self-reports cost, which this study needed.

`--backend stub` is a third implementation: a deterministic hash-based judge that exercises
every path with zero spend and carries no outcome information. It is the known-zero world the
scorer is required to find nothing in.

---

## 2. Latency and cost — a first-class result, not a footnote

Measured over the six real screening runs, ten concurrent workers, `--reasoning-effort low`:

| arm | calls | $/call | in tok | out tok | latency median | p90 |
|---|---|---|---|---|---|---|
| full (sighted verdict) | 189 | $0.00467 | 1,971,179 | 59,903 | **40.1 s** | 49.6 s |
| blind (numbers only) | 189 | $0.00273 | 784,761 | 66,908 | 40.1 s | 103.4 s |
| probfull (sighted) | 189 | $0.00560 | 1,415,704 | 67,784 | 42.1 s | 53.7 s |
| probblind (numbers only) | 189 | $0.00278 | 685,248 | 91,777 | 43.5 s | 48.2 s |

Sighted prompts cost **~1.8× per call** what content-free ones do, entirely in input tokens —
the description and URLs are the whole difference. That is the price of the channel §6 shows to
be harmful.

**Sustained throughput: 13.6 calls/min** at ten concurrent workers (measured over a 300 s
window mid-run; a cold 8-way burst was slower, 6.8/min, because every worker pays process
startup at once). Single-call latency does not improve with concurrency — it stays at ~40 s
and the p90 balloons past 100 s under sustained load.

**What that ceiling implies, in the operator's units:**

- ~15 new coins/min arrive. A ten-worker pool does **13.6/min**. It cannot screen the feed —
  not "expensively", *at all*, with zero headroom.
- Board entries in this tape arrive at **59.7/min** (35,808 in 9.99 h). That is **4.4× over
  capacity**. Screening the whole tape would take **43.9 hours of wall time for 10 hours of
  events** and cost **$167**.
- At a sustainable 15/min the bill is **$4.20/hour, ~$101/day**.
- The scalper holds for 180–420 s (`shitcoims_scalper.policy.JitterRanges`). A 40 s decision
  latency **consumes 10–22% of the intended hold before the position is even opened**.

So the LLM cannot be a first-stage screen. It is at best a **second-stage filter over
candidates a cheap filter has already cut by ≥4.4×** — and a second stage is only worth 40 s
and half a cent if it adds information. The rest of this report is about whether it does.

---

## 3. The cohort — and a correction to the baseline we were told to beat

The brief quoted the incumbent as splitting 8 h forward returns **+21.77% / 67% up** (shallow)
versus **−1.06% / 33% up** (deep). That reproduces exactly from `studies/board_entry.py`.
It is also **not an entity-level number**, and PROGRAM.md §3.2 is not optional.

At the 8 h horizon, 1,381 board entries have an observed forward return. They are **189
distinct mints**. The same coin re-enters the boards dozens of times in ten hours, and each
re-entry was being counted as an independent observation.

Deduplicated to one row per mint (the earliest entry), on the identical data:

| | published (1,271 rows) | **entity-level (189 mints)** |
|---|---|---|
| shallow (<50% off ATH) | +21.77% median, 67% up | **+4.62% median, 57.8% up** |
| deep (≥50% off ATH) | −1.06% median, 33% up | **−0.29% median, 41.5% up** |
| p(up) gap | +34 pp | **+16.3 pp** |

**The effect is real and it is half the size it looked.** Everything below is measured against
the entity-level column, because that is the one that is true.

### The cohort is not the population the scalper trades

This matters more than the shrinkage. Requiring an *observed* 8 h return selects for coins
that stayed on a board for eight hours, and that is a filter on age and size:

| horizon | n (deduped) | graduated | median age | median mcap | younger than 1 h |
|---|---|---|---|---|---|
| 1 h | 606 | 397 (66%) | 3.3 days | $34,051 | 153 (25%) |
| **8 h** | **189** | **167 (88%)** | **15.0 days** | **$374,166** | **8 (4%)** |

The 8 h-evaluable cohort is **88% already-graduated, median two weeks old, median $374k market
cap**. It is not fresh launches. Informative censoring does not merely bias the *level* of the
returns upward — it changes *which coins you are studying*. Any 8 h finding on board entries,
including the incumbent baseline, is a finding about mature graduated tokens re-appearing on
the `last_trade_timestamp` board (171 of 189), not about the sub-hour launches the scalper
actually buys.

### Sampling rule

Stated once, applied without exception, and enforced in `build_cohort`:

1. `board_entry` rows with a usable market cap at t0 and a known `drawdown_from_ath`.
2. Forward return at the horizon **observed, not censored** (`board_entry.value_at` decides;
   we do not reimplement it).
3. **One row per mint**, the earliest entry.
4. Everything surviving 1–3 is screened. No subsampling, no stratification, no class balancing.
   At 8 h that is the complete population of 189. At 1 h the population is 606 and a seeded
   uniform draw of 189 was taken *before* any screening (`--sample 189 --seed 17`).

### Leakage control

Name, description, image URI and socials are fetched live from
`frontend-api-v3.pump.fun/coins/{mint}` **today**; the tape is from the past. Only fields that
cannot have changed are taken from that fetch (`IMMUTABLE_META_FIELDS`). Every number that
moves — market cap, ATH, reply count, completion, last trade — is read from the tape snapshot
at t0. Verified: `created_timestamp` from the live API matches tape-derived age on **189/189**
mints. Metadata coverage: 189 names, 147 descriptions, 189 images, 127 with socials.

---

## 4. What the LLM has to beat

The incumbent, on the 189-mint cohort, at its published 50%-off-ATH threshold:

| statistic | value | shuffled-label null | p |
|---|---|---|---|
| p(up) gap | **+16.3 pp** | 95th pct of \|gap\| = 14.2 pp | 0.021 |
| rank AUC | **0.623** | 95% [0.416, 0.583] | **0.0025** |
| Spearman(−drawdown, return) | **+0.321** | 95% [−0.146, +0.141] | **0.0005** |

Note the p(up) gap barely clears its own null. At n=189 the null band on that statistic is
±14 pp wide, which is why the rank statistics are the ones quoted: they use the whole return
distribution, not just its sign, and they are the more powerful test at this sample size.

### Baselines before models (§3.4) — and drawdown is not even the best column

Each raw number alone, no fitting, nothing to overfit. `rankscore = 0.5 + ρ/2`, so 0.5 is
chance and below 0.5 means the feature predicts *down*:

| feature | rankscore | p |
|---|---|---|
| **market cap at entry** | **0.665** | 0.0005 |
| SOL in curve | 0.342 | 0.0005 |
| drawdown from ATH | 0.339 | 0.0005 |
| age | 0.379 | 0.0015 |
| reply count | 0.429 | 0.055 |
| seconds since last trade | 0.533 | 0.334 |
| board rank | 0.529 | 0.431 |

**Market cap at entry is a stronger single-feature selector than drawdown** (0.165 from chance
versus 0.161), and it is free. The bar is higher than the brief stated.

---

## 5. The four arms, and what they found

Two framings, because the first came back degenerate; each in a sighted and a content-free
version. Every decision is logged as a real `shitcoims_tape.schema.PropensityRecord`.

### The verdict framing collapsed

Asked for `buy`/`skip` with a confidence, grok-4.6 said **`skip` to 189 of 189 coins** in the
sighted arm and 189 of 189 in the blind arm. Its reasons were coherent and, on this cohort,
correct — *"a ~658-day-old graduated token with broken ATH data, no listed socials, and a $71M
cap, not a fresh launch with 8-hour upside"* — which is the model reading §3's problem back to
us: the 8 h-evaluable population is mature graduated tokens, and it declined to buy any of them.

**A filter that selects nothing is an off switch, not a filter.** There is no contrast to score
and no propensity worth logging. What survives is the *graded* signal: the stated confidence,
which varied across only 8–9 distinct values.

### Results

Primary statistic is the graded signal's rank correlation with the 8 h forward return, plus the
AUC of the selector you would actually run (top half by signal; threshold reported in the table).

| arm | sees content | usable n | buy rate | Spearman(signal, return) | p | top-half AUC | p |
|---|---|---|---|---|---|---|---|
| **full** — verdict | yes | 189 | 0% | **−0.001** | 0.984 | 0.496 (thr 0.070) | 0.936 |
| **blind** — verdict | no | 189 | 0% | **+0.152** | 0.036 | 0.579 (thr 0.070) | 0.140 |
| **probfull** — P(up) | yes | 184 (5 err) | 1% | **+0.040** | 0.603 | 0.503 (thr 0.340) | 0.937 |
| **probblind** — P(up) | no | 189 | 3% | **+0.227** | **0.0016** | 0.634 (thr 0.380) | 0.0082 |
| *baseline, for reference* | — | 189 | 44% | +0.321 | 0.0005 | 0.623 | 0.0025 |

**Every sighted arm is indistinguishable from zero. Both blind arms are not.**

The sighted verdict arm's rank correlation with the outcome is **−0.001** — not weak, not
noisy, *absent*. The probability framing, added specifically to rescue a usable ranking out of
the degenerate verdict, produced 18 distinct values spanning 0.12–0.57 and a correlation of
+0.040 (p=0.60) with a top-half AUC of 0.503 against the baseline's 0.623.

Meanwhile the arm **forbidden to see the name, description, image and socials** reached
Spearman **+0.227 (p=0.0016)** and AUC **0.634 (p=0.0082)** — nominally matching the drawdown
baseline. That inversion is the result of this study, and §6 is about whether it survives.

---

## 6. What the nulls said

**Shuffled-label null (the required one).** Verdicts held fixed, outcomes permuted 20,000
times, two-sided. This is both the null and the inference procedure — no bootstrap, no
resampling for balance. It is also the reason the p(up) gap is not the headline: its null band
is ±14 pp at n=189, which swallows most real effects. Every sighted arm sits in the dead centre
of its null (p=0.982, p=0.590). The scorer was validated on both controls §3.12 demands: on the
information-free stub it reports p=0.217 (finds nothing), and on a planted effect p=0.0005
(finds it).

**Content-free control — this is the finding, and it is worse than "no help".** The blind arms
see the identical numbers with every identifying string removed, and they beat the sighted ones
in both framings. Comparing two p-values is not a comparison, so the difference was tested
directly: per coin, randomly swap which arm's signal is used, 5,000 times, and see how often the
gap in Spearman is that large.

| framing | blind ρ | sighted ρ | paired difference | p |
|---|---|---|---|---|
| verdict | +0.152 | −0.001 | **+0.154** | 0.024 |
| probability | +0.227 | +0.040 | **+0.212** | **0.0008** |

**Showing grok-4.6 the coin's name, description, image URI and socials measurably made its
ranking worse.** Not neutral — worse, at p=0.0008 on the framing with the most resolution.
Corroborating detail: the arms agreed on 97–100% of verdicts, the median absolute signal shift
caused by the content was 0.010–0.040, and the correlation between *that content-induced shift*
and the actual outcome was **−0.183** (verdict) and **−0.141** (probability). Where the vibe
moved the model, it moved it the wrong way.

**The vibe channel is not empty; it is actively misleading.** This is exactly the failure mode
the control exists to catch.

**Partial correlation — and the blind arm's skill evaporates too.** The blind arm was handed
the same numbers the baseline uses, so the only question worth asking is whether it added
anything *beyond* them. Partialling the incumbent's own columns out of the rank correlation:

| arm | raw ρ | p | ρ \| drawdown | p | ρ \| market cap | p |
|---|---|---|---|---|---|---|
| blind (verdict) | +0.152 | 0.036 | **−0.005** | 0.946 | +0.145 | 0.046 |
| **probblind** | **+0.227** | **0.0016** | **+0.102** | **0.164** | **+0.086** | 0.243 |
| probfull | +0.040 | 0.603 | +0.021 | 0.795 | −0.104 | 0.160 |
| full | −0.001 | 0.984 | −0.108 | 0.140 | −0.021 | 0.776 |

**Control for drawdown and the best arm in the study drops from +0.227 (p=0.0016) to +0.102
(p=0.164).** Control for market cap instead and it drops to +0.086 (p=0.243). The verdict-framing
blind arm goes to −0.005. The LLM given only numbers was **re-deriving the drawdown rule** — an
expensive, high-latency, stochastic reimplementation of one comparison.

**Same-rate random selector.** At the blind arm's 19% selection rate a coin flip produces a
|gap| of 8.3 pp median, 24.4 pp at the 95th percentile. The blind arm's +21.4 pp does not clear
its own random comparator's 95th percentile.

**Temporal split (§3.1/§3.6).** One tape means this is a within-window check, not a held-out
day, and it is damning anyway: the sighted arm's p(up) gap is **+17.3 pp in the early half and
−25.7 pp in the late half**. A signal that reverses sign across a 2-hour window is noise with a
story attached.

**Trials accounting (§3.9).** Six arms × four reported statistics = 24 tests, and the arms were
not pre-registered — the probability framing was added *after* the verdict framing came back
degenerate, and the 1 h horizon was added after the 8 h cohort turned out to be unrepresentative.
Bonferroni for family-wise 5% is **p < 0.0021**. `probblind`'s raw ρ (p=0.0016) clears it; every
partial correlation, every sighted arm, and every AUC does not. **The only result that survives
both the correction and the drawdown control is that there is no result.** The baseline is
exempt: it was published before this study and is the thing being tested against.

---

## 7. Verdict

**The LLM filter does not beat the mechanical filter, and the qualitative content is worse than
useless.** Three claims, in decreasing order of confidence:

1. **Seeing the coin's identity made the model worse.** Paired difference between the
   content-free and sighted arms: **+0.212 Spearman, p=0.0008**. This is the strongest number
   in the study and it points the wrong way for the hypothesis. The name, description, image URI
   and socials are not an unused channel — they are a channel carrying noise the model acts on.
2. **The best arm was re-deriving drawdown.** `probblind` reached ρ=+0.227 (p=0.0016) on numbers
   alone, then fell to **+0.102 (p=0.164)** with drawdown partialled out and **+0.086 (p=0.243)**
   with market cap partialled out. Nothing survives past the incumbent's own columns.
3. **No arm beat the baseline on any statistic.** Best AUC 0.634 versus 0.623 — a difference of
   0.011, inside the noise, and gone under the partials. Best Spearman +0.227 versus +0.321.

And the cost of not beating it: **40 s and $0.005 per coin**, a 13.6 calls/min ceiling below the
arrival rate, and 10–22% of the intended hold spent waiting for the verdict.

The brief asked us to state plainly whether the LLM improved on the drawdown number. **It did
not.** It also did not improve on market cap at entry, which is a better single column than
drawdown and costs nothing.

The one thing the model got right, it got right by *refusing to play*: it correctly identified
that the 8 h-evaluable cohort is mature graduated tokens rather than fresh launches, and
declined all 189. That is a real observation about our evaluation set, delivered as a degenerate
policy — and it is the study's best argument for §8.1 over any amount of prompt engineering.

---

## 8. What would actually change the answer

Listed in order of how much they threaten the conclusion.

1. **A cohort the model was built to judge.** The decisive weakness is §3's finding: 8 h
   evaluability selects for 15-day-old graduated coins. A vibe judgement plausibly matters most
   for a 90-second-old launch with a picture and a name and nothing else — and those coins are
   almost entirely absent here (8 of 189). The two 1 h-horizon arms in this study
   (`--horizon 3600`, 25% of the cohort under an hour old) are the first step; a proper answer
   needs entry-time screening on the live feed, where age is not selected on at all.
2. **The image.** `image_uri` was passed as a **URL string**, not as pixels. The model never saw
   a single picture. "Glancing at the chart and the vibe" is substantially a *visual* act and
   this study did not test it. This is the largest thing left undone and it is not cheap to fix
   at 40 s/call.
3. **Held-out day.** One 10 h tape, one regime. §3.1 is unmet for the baseline as well as for
   the LLM, and `RESULT_board_entry.md` already flags it.
4. **Power.** n=189 is what the 8 h horizon leaves after entity dedup — a property of the data,
   not the budget. The null band on the p(up) gap is ±14 pp. A weak-but-real edge of 5 pp is
   undetectable here and this study cannot rule one out.
5. **A better prompt.** Possible, and the honest place to be sceptical of ourselves: two
   framings were tried and the second was a reaction to the first. But the content-free control
   argues the ceiling is low — the model's answers barely moved when the content was removed, so
   prompt work on the content is polishing a channel that carries ~0.01 of signal.

## 9. Caveats

- **Returns are market-cap ratios from board snapshots, not fills.** No friction, no slippage,
  no landing. At ~2.4% measured round-trip friction the entity-level shallow median (+4.62% at
  8 h) clears costs; the 1 h numbers largely do not.
- **Informative censoring is bounded, not corrected.** Both arms and the baseline are scored on
  the identical survivor cohort, so the bias cancels in the contrast — it does not cancel in the
  level, and every level quoted here is biased up.
- **5 of 189 probfull calls returned no structured output** and are excluded, not imputed.
- **`grok -p` is nondeterministic and unversioned against us.** Re-running will not reproduce
  these verdicts exactly. The decision logs in `.cache/llm_filter/` are the record.
- **Total spend $3.19 across 945 calls**, under a $1.80-per-arm cap enforced in the harness.

## 10. Reproducing

```
python studies/llm_filter.py --stage selftest                 # no network, no spend
python studies/llm_filter.py --stage cohort                   # tape -> 189 mints
python studies/llm_filter.py --stage meta                     # immutable metadata only
python studies/llm_filter.py --stage screen --arm full  --backend grok --max-usd 1.80
python studies/llm_filter.py --stage screen --arm blind --backend grok --max-usd 1.80
python studies/llm_filter.py --stage score
```

`--backend stub` runs the whole pipeline with zero spend and must report nothing; that is the
known-zero control, and it is the first thing to run if any number here looks surprising.
