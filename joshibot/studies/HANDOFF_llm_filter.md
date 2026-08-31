# Lane handoff — LLM-as-selection-filter

**Lane:** prototype an LLM selection filter and measure whether it beats the mechanical one.
**Owned files:** `studies/llm_filter.py`, `studies/RESULT_llm_filter.md` (plus this handoff).
**Nothing else was touched.** `shitcoims_sentinel/lots.py` and `studies/board_entry.py` show as
modified in the tree — those are other lanes, not this one.

**Status: done and committed.** Nine screening arms across five elicitations, ~1,530 coin
judgements, **$5.4 measured spend**, one clear negative answer plus two corrections that land
outside this lane.

---

## 1. Read this first if you read nothing else

**Three findings here affect other people's work, not just mine.**

### 1.1 `RESULT_board_entry.md`'s headline baseline is not entity-level (§3.2)

The published split — shallow **+21.77% / 67% up** vs deep **−1.06% / 33% up** at 8 h — reproduces
exactly, but those **1,271 rows are 189 distinct mints**. The same coin re-enters the boards dozens
of times in ten hours and each re-entry was counted as an independent observation.

| | published (1,271 rows) | **entity-level (189 mints)** |
|---|---|---|
| shallow (<50% off ATH) | +21.77% median, 67% up | **+4.62% median, 57.8% up** |
| deep (≥50% off ATH) | −1.06% median, 33% up | **−0.29% median, 41.5% up** |
| p(up) gap | +34 pp | **+16.3 pp** |

The effect is **real and half the size it looked**. It survives its own null at entity level
(rank AUC 0.623, p=0.0025; Spearman(−drawdown, return) +0.321, p=0.0005), so this is a correction,
not a refutation. Whoever owns `board_entry.py` should decide whether to restate it there — I did
not edit another lane's file.

### 1.2 The 8 h-evaluable cohort is not the population the scalper trades

Requiring an *observed* 8 h forward return selects hard on age and size:

| horizon | n (deduped) | graduated | median age | median mcap | younger than 1 h |
|---|---|---|---|---|---|
| 1 h | 606 | 397 (66%) | 3.3 days | $34,051 | 153 (25%) |
| **8 h** | **189** | **167 (88%)** | **15.0 days** | **$374,166** | **8 (4%)** |

Informative censoring does not only bias the *level* upward — **it changes which coins you are
studying**. Any 8 h board-entry finding is a finding about mature graduated tokens re-appearing on
the `last_trade_timestamp` board (171 of 189), not about the sub-hour launches the scalper buys.
This applies to the incumbent baseline as much as to anything I ran.

### 1.3 Market cap at entry beats drawdown as a single unfitted column

No fitting, nothing to overfit; `rankscore = 0.5 + ρ/2`, 0.5 is chance, below 0.5 predicts down:

| feature | rankscore (8 h) | p |
|---|---|---|
| **market cap at entry** | **0.665** | 0.0005 |
| SOL in curve | 0.342 | 0.0005 |
| drawdown from ATH | 0.339 | 0.0005 |
| age | 0.379 | 0.0015 |
| reply count | 0.429 | 0.055 |
| seconds since last trade | 0.533 | 0.334 |
| board rank | 0.529 | 0.431 |

At the **1 h** horizon the ordering changes and **age** is strongest (0.323, p=0.0004) — younger is
better. Anyone building a mechanical filter should know drawdown is not the best free column at
either horizon.

---

## 2. The answer to the lane's actual question

**No. The LLM filter does not beat the mechanical one, and the qualitative content is worse than
useless.** In decreasing order of confidence:

1. **Showing the model the coin's identity made it worse.** Paired permutation on the
   sighted-vs-content-free difference (swap which arm's signal is used per coin, 5,000 times):
   **+0.212 Spearman, p=0.0008**. Comparing two p-values is not a comparison, so this is the test
   that matters. The name, description, image URI and socials are not an unused channel — they
   carry noise the model acts on.
2. **The best arm was re-deriving drawdown.** `probblind` (numbers only) hit ρ=+0.227 (p=0.0016),
   then fell to **+0.102 (p=0.164)** with drawdown partialled out and **+0.086 (p=0.243)** with
   market cap partialled out. Nothing survives past the incumbent's own columns.
3. **Five elicitations, none worked.** Buy/skip verdict, calibrated probability, batched 0–100
   conviction, free-form pick-a-subset, unordered colour palette. This was not one bad prompt.

Point estimates for the **sighted** LLM are on the wrong side of zero at both horizons, on two
disjoint cohorts, in both framings — four chances to show a positive sign, none taken.

### Arm-by-arm (8 h cohort, n=189)

| arm | sees content | n | buy rate | Spearman | p | top-half AUC | p |
|---|---|---|---|---|---|---|---|
| full — verdict | yes | 189 | 0% | −0.001 | 0.984 | 0.496 | 0.936 |
| blind — verdict | no | 189 | 0% | +0.152 | 0.036 | 0.579 | 0.140 |
| probfull — P(up) | yes | 184 | 1% | +0.040 | 0.603 | 0.503 | 0.937 |
| **probblind — P(up)** | no | 189 | 3% | **+0.227** | **0.0016** | 0.634 | 0.0082 |
| batchfull — 25/call | yes | 189 | 24% | −0.004 | 0.949 | 0.500 | 1.000 |
| batchblind — 25/call | no | 189 | 33% | +0.065 | 0.371 | 0.548 | 0.263 |
| *baseline* | — | 189 | 44% | +0.321 | 0.0005 | 0.623 | 0.0025 |

**1 h cohort (n=189 sampled from 606):** probfull **−0.116** (p=0.124) against a baseline of
**+0.330** (p=0.0001). probblind −0.034 (p=0.635).

**Trials accounting (§3.9):** nine arms × four reported statistics = 36 tests, and the arms were
not pre-registered (the probability framing was a reaction to the verdict framing collapsing; the
1 h horizon was a reaction to the cohort problem). Bonferroni for family-wise 5% is **p < 0.0014**.
`probblind`'s raw ρ misses it. **Nothing in this study survives both the correction and the
drawdown control.**

### Two vivid results worth not rounding off

- **The colour arm** (unordered ten-word palette, no scale, never treated as ordered) is the only
  elicitation grok differentiated on — all ten colours used, 15–25 coins each. Its partition
  spreads p(up) 34 points, slate 70% / +10.72% median down to violet 26.7%. Between-colour rank
  spread **242.9, p=0.0769, null 95% [43.6, 292.4]** — inside the null band. Closest anything came;
  still not a signal.
- **The pick arm** (free-form, no schema, high effort, model chooses its own rate) picked **4 of
  139**, and all four went down: −80.7%, −41.8%, −38.2%, −0.1%. Median −40.00%, p(up) 0%, against
  52% up among the 135 it passed on. **n=4 — do not over-read it.** It is in the writeup because
  "found nothing" would be the flattering summary rather than the accurate one.

---

## 3. Invocation path and economics — reusable by any lane

- **grok CLI 1.0.3** at `~/.grok/bin/grok`, grok.com **session** auth, `grok-4.6` (bills as
  `grok-4.6-build`). No `XAI_API_KEY` on this machine — there is no raw-API path.
- Headless: `grok -p PROMPT --output-format json --json-schema '{…}'`. Returns `structuredOutput`,
  a full `usage` breakdown, and **`total_cost_usd`** — which is why every cost here is measured.
- It is an **agent harness, not a completion endpoint**: a 1.1 KB prompt bills ~10.4k input tokens.
- **Latency ~40 s median, p90 to 103 s** under load. **13.6 calls/min at ten concurrent workers.**
  Below the ~15 coins/min arrival rate; 4.4× under the 59.7/min board-entry rate.
- **Batching is the whole economic story.** 25 coins per call is **20× throughput and 21× cost
  efficiency**; the full 189-coin cohort screens in **8 calls / $0.045 / 409 s single-threaded**
  against $1.06 and ten workers unbatched. But it does **not** help latency (~52 s/call), it
  **silently drops ids** (only 78% returned at batch 50), and batched scores correlate only
  **0.54–0.66** with single-call scores — it answers a different question. Scored as its own arms
  rather than assumed equivalent.
- **The Claude path exists and was not used.** `tokeman` fronts five OAuth accounts;
  `~/dev/allgame/claude_resident/{auth,sdk_call}.py` is the pattern (drain most-used-first, one-shot
  completions on plan limits). One class against the `Backend` protocol.
- **Kagi:** key in `~/dev/allgame/.env`, v1 shape in `claude_resident/tools/web_tools.py` —
  `POST https://kagi.com/api/v1/search`, `Authorization: Bearer`, `{"query": …}`,
  results at `data.search[]`.

---

## 4. Two live bugs found — one is a warning for every lane

- **`grok`'s cwd must not be inside your working data.** It was pointed at `.cache/llm_filter/` and
  the agent **announced it was about to read "prior decision logs and a cohort file"** — this
  study's own answers. It now runs in an empty temp dir with `--max-turns 1`. **If any other lane
  shells out to `grok`, check its `--cwd`.** It only surfaced because the reply failed to parse; a
  contaminated arm that happened to parse would have looked fine.
- **`base_arm` did not map the taste/colour arms to the sighted feature set**, so they were asking
  for a vibe read on a table of numbers. Caught only because the model said so in its reply ("the
  board feed only has metrics").

---

## 5. What is on disk

`.cache/llm_filter/` (71 MB, gitignored):

| path | what |
|---|---|
| `cohort-28800.json`, `cohort-3600.json` | the entity-deduped cohorts, with forward returns |
| `meta.json` | immutable creation-time metadata, 189+189 mints |
| `decisions-{arm}-grok[-h3600].jsonl` | every decision, with a real `PropensityRecord` each |
| `decisions-*-stub.jsonl` | the known-zero control run |
| `cards-28800/` | **189 rendered stimulus cards** (169 with a real logo) |
| `logos/` | cached logo blobs |
| `run-*.log` | per-arm screening logs |

Decision logs are the record of what happened: `grok -p` is nondeterministic and unversioned
against us, so re-running will not reproduce these verdicts.

---

## 6. What I would do next, in order

1. **Fix the callout join. This is the coordinator's, and it outranks everything else here.** The
   operator's actual strategy was reading the **callout feed** — who called it, how loudly.
   `intelligence_state/intelligence.sqlite3` holds 9,354 observations across four sources, but
   **only 10 of the 333 cohort mints (3%)** appear in it. So this lane tested an LLM on pump.fun
   metadata, which is strictly weaker than what the human was using. **A null on "name and
   description" is not a null on "who called this."** Collector problem, not a modelling problem.
2. **Vision LLM over the rendered cards. ~$5, one command away.** `--stage render` already built
   189 cards: logo pasted at top, then ticker/name/description/numbers **rendered as pixels, not
   passed as tokens** (a human reading the name is doing visual word-form processing, and a
   separate text channel would model a different act). Every arm I ran passed `image_uri` as a
   **URL string** — the visual channel is genuinely untested. If pixels move the number, that is
   the finding, and it is cheap.
3. **TRIBE v2 as the pre-verbal probe** (`facebook/tribev2`, **0.71 GB, ungated**, runs locally;
   LLaMA 3.2 + V-JEPA2 + Wav2Vec-BERT → fMRI on fsaverage5, `(n_timesteps, ~20k vertices)`). Every
   arm here asked grok to *say* something; if the glance is a pattern-match that does not decompose
   onto language, verbalisation is the lossy step and no prompt reaches past it.
   **The overfitting objection is already answered and the machinery is in the harness.**
   `representation_test` scores a representation with **distance correlation** and RSA/Mantel —
   pairwise distances only, no weights, no hyperparameter, no split to leak across, nothing that
   can memorise 189 labels. Outcomes are permuted, never the representation.
   Two things to know before quoting it: **dCor works and Mantel does not** (planted nonlinear
   dependence in 64 dims: dCor p=0.0007, **Mantel misses at p=0.187**), and **raw dCor is not an
   effect size** (the known-zero world still returns 0.295 — read the permutation p).
   Remaining limits: power is still n=189; a pump.fun screenshot is out of distribution for a model
   trained on films; **CC-BY-NC-4.0 rules out live commercial use**.
   And the framing caveat that outranks all three: a faithful simulation of the glance reproduces
   *the operator's own judgement*, and this lane is what happens when that judgement is tested
   against a number.
4. **A held-out day.** One 10 h tape, one regime. §3.1 is unmet for the baseline as much as for the
   LLM. `RESULT_board_entry.md` already flags it.

---

## 7. Gotchas for whoever picks this up

- `--stage selftest` runs with **no network and no spend** and is the first thing to run if a
  number looks surprising. `--backend stub` runs the whole pipeline free and **must report
  nothing** — that is the known-zero world, and §3.12 wants a known-effect check too (both are in
  the selftest).
- The harness **imports the real `shitcoims_tape.schema.PropensityRecord`** rather than mirroring
  it, and asserts the schema rejects propensity 0 — which is what makes the epsilon floor
  load-bearing. Do not replace it with a local dataclass.
- `build_cohort` **hard-fails** if `studies/board_entry.py`'s `HORIZONS_S` stops covering the
  requested horizon. That constant is another lane's, and a silent empty cohort would be a study
  reported on nothing.
- Cost caps are enforced per arm (`--max-usd`) and screening **resumes** from an existing decision
  log, so an interrupted run is never re-paid for.
- Omissions are recorded as **errors, never imputed** — batching's failure mode is silent dropping,
  and imputing 0.5 would hide it.

## 8. Commits

```
55059e8  harness with propensity logging and controls
5a39457  does not beat drawdown; blind arm beats sighted
bff6cd3  partial correlations + paired arm test kill both positive readings
6b36163  batching, free-form pick arm, colour arm, and two bugs it caught
0dc80d5  colour and pick arms reported; callout channel was never testable
0ceda9e  TRIBE v2 scoped behind a cheap pixels test
1acef48  final pick-arm numbers — 4 of 139, all four down
296184f  render the coin as pixels; score representations without fitting
```
