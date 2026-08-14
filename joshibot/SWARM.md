# joshibot — swarm execution plan

Companion to PROGRAM.md. That document says what the evidence establishes; this one says how to
build it with a fleet without the fleet building a mirror.

---

## The one principle

**The binding constraint on swarming is interface existence, not work volume.** An agent that cannot
see the foundation it depends on reconstructs the interface from prose and verifies against its own
reconstruction — green in a scratchpad, broken on integration. So the plan has exactly two kinds of
work:

- **Foundations** — the shared interfaces everything else reads. These are *anti-swarm*. Fanning them
  out produces N incompatible mirrors. Author them tight, in-session, as real types on disk that
  build.
- **Tracks** — work that consumes a foundation interface and produces something behind it. These
  swarm cleanly *once the interface exists*, and only then.

Everything below is a consequence of drawing that line in the right place.

---

## The ground-truth manifest — the 8 shared interfaces

These are what a swarm agent must be handed verbatim (real signatures, absolute paths, which repo).
Until they exist, the thing that reads them cannot be swarmed.

1. **Tape event schema** — read by the recorder, every signal study, the replay harness. JSONL.
2. **Fill-semantics type + its exported C ABI** — read by replay, the hardened sentinel, the envelope.
3. **History type / causal index** — read by the DSL and every strategy term. Makes lookahead a type error.
4. **DSL term algebra** — read by the search harness, the envelope, the trial-count computation.
5. **Provenance / accounting types** — read by the sentinel's cost-basis fix, the kernel, replay PnL.
6. **Envelope constraint type** — read by the online layer and the signer.
7. **Entity-resolution output format** (`wallet → entity`) — read by signals #1, #4, #5, #6, #7.
8. **Propensity-log schema** — read by the online layer, OPE, and attribution.

Get these right and the rest genuinely parallelizes. Leave any implicit and every agent touching it
mirrors.

---

## Phase 0 — foundations (in-session, NOT swarmed)

High-leverage design work that sets the defaults everything inherits. Do it tight. Small enough for
one coherent authorship pass; too load-bearing to fan out.

- **Tape schema (#1, #7, #8).** What a recorded launch/trade/reserve/callout event is, time-aligned,
  clock-censored (never displacement-censored — verify against Marino's 4.4-min-median-with-a-tail).
  The entity-resolution output and propensity-log shapes are small and go here too.
- **Lean kernel type design (#2–#6).** The signatures, before the proofs. Internal order: history
  type (#3) → DSL (#4); fills (#2) and accounting (#5) are more independent; envelope (#6) sits on
  #2+#5. Proofs deepen incrementally after the signatures land.

**Say the substrate out loud:** this is a **Lean-authored decision kernel**. Rust/Python `@[export]`
→ C → FFI *into* the emitted artifact; they never hand-write fill semantics, DSL terms, accounting,
or envelope checks. The AIR-in-Lean tripwire applies here by analogy — "does the envelope admit this
action" rhymes with "does the prover accept X," and the moment a lane starts writing a fill or a
constraint in Rust "because a crate is right there," that is the drift. Check it at constraint #1.

**No floats in the kernel.** ℤ lamports and raw base units throughout. Floats are where proofs die,
and raw-units/UI-amount/lamports/SOL confusion is a live hazard already.

---

## Phase 1 — parallel tracks (swarmable once Phase 0 lands)

### Track A — sentinel hardening (independent of Phase 0; can start now)

The existing Python codebase, protecting/earning real money. Clean file ownership → no collisions.
Both audits gave exact file:line. **Do not stop the running process to do this.**

- **A1 — `executor.py` + `clients.py`.** Write executor tests against a fake Jupiter + fake RPC
  *first* (the review's explicit ordering — behavior changes only after tests exist), then: the
  double-submit fix (`executor.py:231-254` / retry loop `:154` — resolve the stored signature before
  any retry, never build a second order while one is unresolved), the 32-address simulation ceiling
  (`executor.py:193-200` vs `clients.py:193` — chunk or narrow, assert loudly), and computed `minOut`
  from live reserves replacing `slippage_bps:1500` (`clients.py:342,381`; ~200–300bps for slot drift,
  wide only on the explicit panic path).
- **A2 — `engine.py`.** The cost-basis fix (the priority; `engine.py:770-773`). Approach that
  preserves the isolation the review praised: the sentinel reconstructs its own basis from its **own**
  chain history (it already has Helius + its own pubkey) — do *not* import from
  `shitcoims_intelligence`. Plus: stop auto-resuming terminal `failed` intents on restart
  (`engine.py:1137-1175`).
- **A3 — `server.py` + `cli.py`.** Config lost-update (move the read-modify-write of `config.positions`
  inside `_policy_lock`, `server.py:94,104,126`), and make `--status` incapable of executing
  (`cli.py:51/232`).

No file is owned by two lanes. After the lanes land: full `uv run pytest` + whole-tree build (the
red-umbrella lesson — per-file green hides a broken downstream), then the audit gate.

### Track B — tape recorder (needs #1)

The firehose to `/tank` on hbox. Bootstrap history from MELT (41k tokens, 218M txs, crawled Jito
bundle traces) and RED-PUMP (860k launch records, CC-BY-4.0) — the latter as launch-metadata only,
its outcome labels are displacement-censored. **This is do-first among the new work: data compounds
regardless of which strategy wins and cannot be recorded retroactively.**

**Findings from the signal-#3 feasibility spike (2026-08-13), measured on the live store.** The spike
tried to run the callout→flow study on existing data and found it *structurally* impossible, not
underpowered. Everything below is a measured number, and each item is a requirement on this track.

- **BUG, fix first, ~10 lines.** `shitcoims_intelligence/helius.py` line ~942 reads
  `event_slot = int(result["slot"])` but passes `item` to `normalize_wallet_transaction`, whose
  `item.get("blockTime")` (schema.py line ~381) is **always `None`** on this path — Solana's
  `transactionNotification` carries a slot but no block time. Result: **169/169 live-path rows have no
  event clock**, while the 1,312 backfill rows do. The only rows with a usable timestamp are the ones
  that arrive late (ingest-minus-block p50 = **31 hours**). Resolve slot→time via a cached
  `getBlockTime` and make block time **mandatory**: a row without one goes to a defect stream, never
  silently written. Do not substitute a slot→time linear fit — measured residual p90 ≈ 24 s against a
  response measured in minutes.
- **The two clocks are inverted between sources, and joining them silently fabricates latencies.**
  Chain rows: `observed_at` = ingest, `emitted_at` = block time. Social rows: `observed_at` = post
  time, `emitted_at` = scrape. Evidence this is not hypothetical: Spearman(`observed_at`, slot) =
  **−0.77** on the third-party wallet — ingest time runs *backwards* against chain time, because
  backfill paginates newest-first. 88.6% of the tape arrives in pages sharing a single `observed_at`
  second; the worst page collapses **29.14 hours** of chain time into one instant. Name the fields
  `t_event` / `t_ingest` so the semantics cannot invert, join analysis on `t_event` only, and make a
  mixed join a type error — which is exactly what the kernel's causally-indexed history type is for.
- **Three gaps in the landed `shitcoims_tape/schema.py`**, all confirmed absent:
  1. **No control-mint concept at all** (zero occurrences of `control`/`matched`). Without matched
     controls there is no baseline and therefore no study — see below. Needs the matching key *and*
     the achieved caliper recorded per control row, so match quality is auditable rather than asserted.
     Match on **curve position (vSol)**, not FDV or price: §1.1 says drops cluster at specific vSol
     levels, so vSol is the confounder to balance.
  2. **No `fee_payer` / `trader_paid_fee`** on `Trade`. This is the discriminator that separates real
     trades from inbound spam, and it is not a corner case — see the dust finding below.
  3. **No same-slot atomic/bundle field.** MEV is the dominant false positive for signal #4, and it
     cannot be excluded after the fact.
- **The index is the whole problem.** A wallet-indexed tape records zero flow for any (mint, hour)
  the watched wallets ignored — a structural zero, not a measurement, so every rate ratio is `+inf`
  or `0/0`. Measured: 64% of tape mints have exactly **one** leg; median per-mint observed span is
  **0.00 h**. The landed schema is already mint-indexed and carries `WatchWindow`/`WatchClose`, which
  is right — keep it, and make the window binding: absence inside a window is evidence of zero,
  absence outside it is no information. Any analysis window overlapping a subscription gap is
  **excluded, never zero-filled** (measured: 5 disconnects in ~17 h, ~1 per 3.4 h, so a 60-minute
  window intersecting one is routine).
- **Overdispersion is measured — but do NOT apply it twice.** Hourly flow *counts* are genuinely
  overdispersed (Fano ~11.5–16.7, negative-binomial `k ≈ 0.695`), and that inflates any power
  calculation whose estimand is a **count**. It does **not** transfer to price estimands:
  studies/RESULT_power_gate.md measured the *price* variance inflation against a compound-Poisson
  baseline at **0.59–1.17×, not 17×**, because the bursts here are two-sided arbitrage round trips
  that partly cancel. An earlier draft of this bullet said a Poisson-assuming calculation understates
  n by ~17× *in general*; that is wrong for price-based estimands, where a σ measured from prices
  already contains the burst structure. (The same counts yield `n̂ = 1 − 1/√Fano`, which is a
  *pipeline diagnostic and not a branching ratio* — on a two-wallet tape a wallet's own trades are
  trivially self-exciting. Do not quote it.)
- **Callout supply is cheap; flow is the entire cost.** 134.7 distinct mint-resolved callouts/day
  measured, so n=400 is ~3 days — but collect **4 weeks** so temporal folds (§3 rules 1 and 6) contain
  regime variation. Helius: ~48% of the 10M plan at 5 controls per treated mint, ~29% at 3 controls.
  That k is the budget knob, and per §3 rule 7 it must be reported with every number.
- **Only one social source is fast enough to trade on.** Post→detection p50: `x_mint_mention` **209 s**,
  `claudekol_claim` 1,280 s, `x_reply` 8,291 s, `x_tweet` 16,271 s, `x_kol_post` 15,624 s. Against
  Marino's 4.4-minute median time-to-graduation, only `x_mint_mention` is inside the decision window at
  all, and its p90 of 10.6 min is already outside it. Everything else is a research feed, not a signal.
  Target p90 ≤ 60 s on mint-bearing kinds.
- **Deduplicate calls at write time.** 357 mint-bearing rows collapse to **66 distinct called-out
  mints** — a 5.4× re-scrape inflation, with one mint re-observed 51 times. Any n counted in rows is
  inflated 5.4×. Needs a stable `call_id` = hash(platform, author_id, post_id, mint), where a re-scrape
  **updates** rather than inserts. Also: 4 of the 66 mints rest on a free-text regex with **no on-chain
  validation** — add a mint-account existence check before a mint enters any study.

**Free finding for signal #4, worth more than the study that produced it:** the third-party KOL wallet
in the store is **88.5% inbound dust** — 981 of 1,108 rows are unsolicited token transfers from 753
distinct senders (705 one-shot) spraying 581 mints, while the wallet itself signed **three**
transactions. Watching a famous wallet mostly measures people spamming *at* it. Any KOL-flow metric
must filter on `trader_paid_fee`, which is gap (2) above.

### Track C — Lean kernel implementation (needs #2–#6 signatures)

Fills → accounting → DSL → envelope, with the proofs PROGRAM.md §2 names. Limited internal
parallelism (fills + accounting can go concurrently; DSL and envelope build on them). The envelope
theorem — *no admitted action sequence exceeds exposure X, quantified over all learners* — is the one
worth the effort.

### Track E — signal research spikes (needs #1 + #7; some run on existing data NOW)

Self-contained offline studies, each an adversarial audit of its own claim. #3 (callout→flow) can
start immediately against the intelligence store's existing 28 mint-resolved callouts/day + the
`wallet_transaction` tape. #1 (SVN clustering) and #2 (funding-tree entity resolution) are the
highest method-to-data-volume fits and only need the recorder's early output. Run these as
exploration, not production — a spike that comes back null is a *result*, logged as such.

### Phase 2 (after B + C exist)

Replay + search harness (exact AMM fills, MAP-Elites over DSL terms, OPE over our own propensity-logged
trades, purged walk-forward, honest trials accounting), then the signal queue through it.

---

## Non-negotiable defaults every prompt carries

Your prompt's defaults carry the project's values; agents take whatever default you write. Bake these
into every lane prompt so nobody has to remember to be careful:

- temporal splits only; entity-level grouping (cluster, then split)
- never SMOTE / resample; natural base rates + proper scoring rules
- baselines (EdgeBank / popularity / gradient-boosted trees) before any fancier model
- AUPRC / precision@k, never accuracy or ROC-AUC at high base rates
- JSONL, not CSV; clock-censoring, not displacement-censoring
- Lean-authored kernel, Rust/Python FFI into it; no floats in the kernel
- the sophisticated part is the **architecture and the methodology, not the model class**. The
  published failures of GNNs and Transformers here are real but *confounded* — MELT gave its sequence
  models raw price/volume while the tabular models got engineered features, and Elliptic's graph harm
  is attributed to sparse, prior-shifted conditions we may not share. So the rule is not "never build
  one," it is: **baselines first (EdgeBank / popularity / boosted trees), and any richer model class
  must beat a matched-capacity MLP on the *same* features, under a strictly inductive protocol.**
  Varying model class and input representation together is not an experiment, it is a confound —
  Elliptic's own largest effect was a 39.5-point transductive-vs-inductive leakage gap, far bigger
  than anything architecture bought

---

## Verification gate (applied to every track)

Green + self-reported "done" is not verification. A vacuous `P → P` builds green and reports success.
The gate is a separate adversarial audit agent that:

- reads the actual **theorem statements** (Lean) / **test assertions** (Python) and rejects vacuous
  or tautological ones
- builds against the **real tree** itself, not a scratchpad
- for a signal spike, checks the claim against the methodology standard (PROGRAM.md §3) — was the
  split temporal? was a null run? is the metric base-rate-preserving?

Trust the checker, not the lane's summary. Harvest with `cv workflow`. A "failed" run still has good
lanes — harvest and commit the done ones, don't discard the run.

---

## Audit cadence — and the failure of nerve it corrects

The gate in the previous section is a BUILD check. It proves the tree compiles, the tests pass
and no theorem rests on `sorry`. It does not prove the tests assert anything or that the
theorems say what their docstrings claim, and those are different questions.

Running the build gate and calling it verification is the exact substitution this project keeps
finding in other people's work: a purge parameter that was a no-op, a zero-control that a
detect-nothing estimator passes perfectly, an AUC of 1.0 from features computed off the labels.
Each of those had a green pipeline.

So the adversarial audit is not optional and it is not the same step. It runs on a SCHEDULE,
not on a feeling that the work looks finished:

- after every swarm wave, before the next one is launched;
- whenever a component's claims get stronger (a new theorem, a new guarantee in a docstring);
- and periodically on components that have NOT changed, because their dependencies have.

The auditor is told to REFUTE, is forbidden from trusting summaries or mutation matrices, and
must produce per-item conclusions with runnable reproductions. "It all looks good" is the
weakest result it can return and is only acceptable after demonstrated effort.

Note for whoever runs this next: the first three waves of this project shipped with the build
gate run every time and the adversarial audit run ZERO times, because the build gate kept
coming back green and green feels like enough. It is not. Schedule the audit.

## Swarm-safety mechanics (paid for in real debugging)

- Commit **named files** while lanes are live; never `git add -A` (half-written siblings).
- After any lane touches a shared struct/interface, build the **whole tree**, not the changed files.
- Workflow-JS: no apostrophes/contractions in script string literals; a zsh glob-no-match aborts the
  whole compound command; backticks in a double-quoted `-m` get command-substituted (write prose
  commit messages to a file, `git commit -F`).
- hbox is co-tenant (codex owns the datacake HOL build); build under `swarm-build`, keep waves small.

---

## Money sequencing

The $600 goes to the **instrument, not the bot.** Today shitcoims still runs the −29%/round-trip
fabricated-basis engine; moving capital in before Track A lands funds exactly what lost 7.47 SOL.
Compute and data spend (Helius credits, hbox time) is the higher-return allocation right now, and the
fee stream means we are **not capital-constrained on the research** — that is the luxury position this
whole plan is built on. Fund the bot after the sentinel can measure its own PnL; fund the research
freely.
