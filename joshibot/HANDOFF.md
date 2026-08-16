# Handoff — 2026-08-16

For codex, picking this up cold with room to play. The previous handoff (2026-08-14) is
pre-everything: a ~20-agent wave has run since, the v2 design (JOSHI) is written, and the
season has a law now. This replaces it. Read time ~15 minutes; then you know where the live
edges, the dead ends, and the bodies are.

The spine is still `PROGRAM.md` (what the evidence establishes) and `SWARM.md` (how to build
with a fleet). This document is the map on top of them. Every number here was checked against
the `studies/RESULT_*.md` it came from; where the brief that launched me and the committed
result disagreed, the result won and it is flagged.

---

## 1. The season's law — read this first

**Entry-prediction is dead.** Not "weak" — dead, established ~12 independent ways this wave,
at every horizon and every signal we could build. This is the single most important thing to
inherit, because the temptation is to re-run it in a new costume, and it will come back null
again while costing days.

The refutations, each its own RESULT doc:

- **`exploration_map`** — a *pre-declared* 542-cell sweep (539 evaluable). 8 cells survive
  BY-FDR at q=0.10; **0 clear the 2.26% round-trip friction.** The one all-gate survivor's top
  decile still returns −0.21%. The information the streams *do* carry is about visibility,
  survival, and bleed-speed — exit/position-management questions — never entry direction.
- **`callout_edge` / `callout_flow` / `callout_volatility`** — buying what the callout feed
  names returns −11.9% at 1h, −43.6% at 8h, and *worse the louder the call* (burst −64.7%,
  big-caller −65.8%). Caller identity is an anti-signal: **permuting caller identity raises
  test AUC and beats reality 24/24 draws.** What a callout *does* mark is two-sided flow (33
  both-sided trades/hr vs 2) and volatility — a locator, never a direction.
- **`caller_wallets` / `quality_callers` / `cluster_callers` / `jackduval_workup`** — most
  "callers" are not people with wallets (X-handle→wallet joins for 5/146). The one wallet link
  that survives is a 161-stranger launch-crowd, not front-running. jackduvalcalls is a sub-minute
  sniper down 179.65 SOL over 10 days (17.7% win rate), who has **never touched any of the
  operator's coins.** The attention *pulse* is real and huge (47× print density); the copy trade
  still doesn't clear friction (median +$1.14/pulse, **mean −$0.19**, 128 exit configs / 0
  positive means).
- **`imitation_signal`** — clone/imitator swarms carry no host-return info beyond mcap+age;
  matched-control return difference is **+0.00% median at every horizon**, and **permuting which
  coin was swarmed beats reality 22/24 draws.** (Swarm onset *is* a survival marker: swarmed
  hosts live 10.7 min vs 1.0 min — use it as an avoid/hold covariate, not a trade.)
- **`copytrading`** — undetectable once burstiness is held fixed. The naive i.i.d. null said
  73× coordination; the structure-preserving null says 1.01×. 0/8 leader-follower pairs survive.
  The app flow is FOMO herding, not mirroring, and the second-mover penalty (0.879%/slot) eats
  half the round-trip edge.
- **`board_entry`** — the operator's "buy the dip on attention" premise is right about the
  drawdown and *backwards on the trade*: it's continuation, not reversion (shallow-drawdown +
  near-highs entries +5.73%/2h, p(up) 76%; deep-drawdown −0.45%). But the effect **reverses/
  dissolves under censoring** (deep coins are censored 65→81% more) and there is no held-out day
  yet — a lead, not an edge.
- **`bandit_search`** — the when/size/exit policy search is null: best cell +6.93% vs a
  permuted-world floor of +5.99% (p=0.455). The prior "+21.77%/8h" was survivorship; priced
  honestly it's −12.24% net.
- **`llm_filter`** — an LLM glance adds *negative* information over five numbers: showing it the
  name/description/image made its ranking measurably worse (+0.212 Spearman, p=0.0008). The vibe
  channel is noise.

The throughline: **attention marks flow and survival, never direction; and every headline
effect this wave came from an i.i.d. null and died under a structure-preserving one.** That is
the law. Do not spend codex-time trying to beat it.

### What is POSITIVE

Three things survived audit, and they are the whole game:

**(a) TOLLS — get paid for being positioned where flow crosses, prediction-free.**
- **The fee stream is the business, at a 23× ratio over everything else.** The definitive
  lifetime reconstruction (`position_history`, 5 wallets / 2,012 tx, reconciles to the lamport)
  puts the operating result at **+718.4 SOL ≈ +$54,471**, of which **trading is −32.45 SOL**
  (negative in 4 of 5 wallets). Trading is a research program funded by the tolls, not a rent
  strategy. (It also retracts three first-draft figures — the "8.31 SOL fee income" in the
  −7.47 SOL window was actually *zero*; 223 SOL still sits at 3 unidentified destinations, so
  no honest on-chain net-worth exists until those + the Coinbase internals are labeled.)
- Creator fees are the business. The fee is a **25-rung step function, 5 bps apart, keyed on
  SOL market cap**, verified 1,058/1,058 swaps (`dregg_boundary`) — *not* the USD tier-table.
  Realized creator take is **1.00× the published ladder** over a 48-day exact reconstruction
  (this **corrects** `toll_positioning`'s 0.93× and its "dead 38%-of-income social stream,"
  which turned out to be a live single-pipe sweep by the operator's own wallet — nothing died).
  30-day income runs **$4.8k–$9.7k against $4.1k obligations** (1.16–2.36× coverage). The joint
  fee+inventory position is **long its own price essentially everywhere** — a rally through the
  next rung is +fee-income *and* +escrow mark — so *never spend to defend a price boundary*
  (`dregg_boundary` kills the rival-$DREGG "boundary press" campaign as −EV, ~$19/yr).
- LP fee *harvest* positioned on the desk's own token-token DLMM pools is real and large as a
  numerator: fee-tier rent of ~5.5% vs 0.20% PumpSwap = **28× advantage**, 15.2× realized on a
  6-hour sample (`swing_cluster`, `power_gate`). **But** — and this is the honest status — across
  10 closed cluster positions the book is **−$130.80 net and −$595.14 versus holding the
  baskets** (`edge_creation`, `circuit_theory`). The pools earned $879 in fees and still lost to
  HODL because the tokens rose and IL/adverse-selection ate it. Token/SOL LPing is −EV by ~an
  order of magnitude (η = 0.055–0.235, and **LP is +EV ⟺ η > VR(T)**). LP fee harvest is a toll,
  not yet a proven edge; the reversion premise that says "IL is temporary" is unchecked
  bounce-free (VR ≈ 0.80–1.01 = random walk). **Highest-value open LP question: the rebalance /
  duty-cycle rule** — DREGG/nosis lost purely on a 49.4% duty cycle (an out-of-range DLMM is an
  open circuit taking zero flow).

**(b) The OPERATOR'S OWN JUDGMENT is the desk's best-measured signal.**
- Discretionary/one-sided ladder exits beat routing by **+1.96%** (hour-clustered SE 0.59%,
  **t=3.31, n=221** fills). Operator-typed cost basis realized **+18.1%** where the machine's
  fabricated-from-quote basis realized **−29.1%** (same bot, same window). Operator-picked
  wiggles extract a **median +$1.14/pulse** where the rule-book runs −5% and every searched
  bracket has a negative mean. The *selection* is the operator's; the rule can't reproduce it.
- This is why the desk is **operator-coupled by design** (JOSHI §0). The automated layer,
  unsupervised, is the worst thing here (−7.47 SOL in one live window). The mandate is:
  **instrument the operator, don't replace them.**

**(c) EXITS and AVOID signals — the surviving edge is on the sell/skip side.**
- **`operator_crime` CLEAN birth-time screen** (POSITIVE, shippable): on 106.6M tx, rug risk is
  ~decided in the first 60 minutes from the birth slot. A birth-time CLEAN screen admits 4.8% of
  coins, **99.96% clean, 20× fewer collapses.** Counter-intuitive: "deployer never dumped" is a
  1.71× *risk* factor (no record = first-timer). Target the reused sniper crew, not the deployer.
- **`crime_signatures` GHOST_TOWN filter** (positive carve-out): the crime *score* is a **null as
  an exit signal** (precision 0.0000, inverted AUC — never wire it to a sell). But GHOST_TOWN
  (C→0) is a forward-visible danger state: no exit at the quoted price when capacitance collapses.
  Also: the sentinel's 20% stop is mis-set — a 20% fall is irreversible only 0.7% of the time,
  an 80% fall 51.6%.
- **`pvp_vamps` PvP-state as a wiggle selector** (positive covariate only): do NOT build a PvP
  entry book or exit trigger (both refuted); wire the PvP score as a covariate into the wiggle
  book's candidate ranking — it's a positive selector for two-sided flow.
- **`unrealized_pnl` — the one place cost basis is not redundant.** At the coin level basis is a
  lossy re-encoding of the price path (support/resistance NULL, 0/18 cells). The single survivor:
  among co-holders of one coin at one instant, the *next seller* is predictable from its own
  basis — and **the sign flips with position age**. Young (<10 min) positions sell from *above*
  median (profit-taking); old (>10 min) sell from *below* (capitulation). Read a high sell-hazard
  as "take profit" to a fresh position and "cut loss" to a stale one — an exit-side read, never
  a level to trade against. Realization policy is a **wallet fingerprint** (AUC 0.775 on
  coin-disjoint own-halves), not a crew signal (0.518).

**Also settled — execution is cheap and safe, and the scary numbers were our own bug.**
`execution_landing` retracts the "1–52% landing / friction 2–10× the model" alarm: a
transaction shaped like ours lands **95–97%** for ~$0.001, and sandwiches are *structurally
impossible* at the operator's clip (threshold B > φ·Y is $19–72; a $9 clip is below it
everywhere; 0 of 382 attackable slots attacked). Policy: bid 100k–300k µL/CU, call the AMM
**directly**, CU limit from sim ×1.15 (not the 200k constant, which is 1.78× median), sign
once and rebroadcast, **skip Jito for v1** (revert protection saves ~$0.00007/send). Maker-side
resting orders are a NO (`jupiter_programs`: one keeper fills you, you write a free option). The
one unmeasured execution risk is the *send-time drop rate*, which needs our own instrumentation.
Timing: do discretionary chain work (claims, rebalances) in the **06:00–10:00 UTC cheap-gas
window** (`seasonality`: fees peak 15:00 UTC, +32% over the 07:00 trough) — but *never* schedule
harvesting by the clock; the market has a clock, the opportunity does not (wiggle quality is a
diurnal null).

**Do not let any lane re-run a dead entry study.** The positive surface is tolls, the operator,
and the exit/avoid side. That is where codex should play.

---

## 2. The one open edge candidate — the 8-second ladder

`studies/RESULT_cluster_map.md` (event-first clustering over 1,534,512 wallets / 10 days →
13,462 fleets covering 78,340 wallets; 223 of 300 tested cluster pairs *systematically avoid
each other*, a real market partition, z up to −112.6).

The thing nobody was looking for: **six clusters — 34 wallets — enter the same coins at fixed
8-second intervals** (rungs at −4, 0, +8, +16, +24, +32 s). They have made **63,052 entries and
62 exits (0.098%).** They are not trading; they accumulate on a metronome and never sell (they
bought nosis in launch order at +5…+41 s and still hold). Validated three ways (11 pairwise
offsets fit one 1-D ladder with 0 mismatches; survives dropping the partition; fired live on
nosis). Coincidence is ruled out; the dust-airdrop alternative is decisively rejected (distinct
amounts / entries 0.996–0.9998).

> **Flag for codex — the launching brief had this wrong.** The brief said "110 clusters / 479
> wallets, coins graduate 35–62% vs 3%." Those figures appear **nowhere** in the committed
> results. The verified object is **6 clusters / 34 wallets / 8-second cadence / 0.098% exit
> rate**; there is no graduation-rate comparison for the ladder in any study. Cite the real
> numbers.

**What is open: make vs pick vs coincidence.** Coincidence is out. Sybil-accumulation-ahead-of-
distribution, a buy-every-launch indexing bot, and paid holder-count manufacturing all fit "buys
on a metronome, never sells," and the current instrument cannot separate them. The named file in
the brief — `studies/ladder_causality.py` — **does not exist yet**; the working artifact is
`studies/cluster_map.py`. Writing the causality study is the next move, and the doc already points
the way: the exploitable channel is **synchronized exits, not entries** (entry carries a
launch-sniping confound; synchronized-exit separation is ∞ against a control that shares zero
exits). This is the most interesting live thread in the repo.

---

## 3. The methodology is load-bearing — inherit it or the numbers lie

The repo's entire credibility is this discipline (PROGRAM.md §3). It is not pedantry: every one
of these turned a manufactured effect into a null this wave.

- **Structure-preserving nulls, never i.i.d.** Rotation/block/degree-preserving nulls, not
  independent shuffles. The manufactured-effect factor is routinely 3×–73× (copytrading 73×→1.01×;
  caller recycling 20×→1.20×; SVN Bonferroni FWER 0.600 from *zero* planted coordination). A single
  null is a knob; use **two nulls compared at matched density** and hand only the intersection down.
- **Executable-exit marking, never marginal price.** This is the difference between +950 and
  −179.65 SOL on one wallet (`jackduval_workup`): marginal-price marking flips the sign. Value
  every position at what the exit would actually realize (bounce-free, from vault reserves), never
  last-trade closes (which carry bid-ask bounce — the scar that made "reversion" look real when
  VR is actually ≈1).
- **Censoring priced, not dropped.** Pricing censored rows vs dropping them swung callout returns
  from −14.6% to +25.0% on the same 45 pairs. Deep-drawdown coins are censored *more*, which is
  exactly what makes `board_entry`'s flat group a mirage.
- **Temporal splits + entity-level grouping.** Random-vs-temporal is worth 54 points of recall.
  Cluster wallets first, then split — one actor must never straddle train/test.
- **Both controls, always.** A known-zero world *and* a known-effect world. A detect-nothing
  estimator passes a false-positive test perfectly; only planted recovery catches it.
- **Burst-effective-sample-size, and don't double-count it.** Count overdispersion (Fano ~11–17)
  is real and inflates *count* estimands; it does **not** transfer to *price* estimands (measured
  0.59–1.17×). t=40 and rotation-p=0.011 can both be correct on the same data — the burst ESS is
  why.
- **No study row-loops a corpus.** DuckDB/polars over parquet; a `for` loop over corpus rows in
  pure Python is a defect (SUBSTRATE tripwire). And: **dry-run the billed superset before buying
  the subset** — a $54 lesson, because BigQuery bills columns×partitions and the WHERE is free.
- **Mutation testing lies unless you clear `__pycache__`** between steps (same-length, same-second
  edits leave stale bytecode running). Green build ≠ verified — schedule the adversarial audit
  that reads the actual assertions, on a calendar, not on a feeling (SWARM.md).

---

## 4. What is LIVE right now

Eight launchd daemons, all supervised by the watchdog. Check them:

```
launchctl list | grep shitcoims          # the eight below should all carry a PID
uv run python scripts/watchdog.py         # freshness per collector; "quiet" vs "dead" as data
```

| daemon | label | what it does |
|---|---|---|
| boards | `com.shitcoims.boards` | trending/boards tape |
| firehose | `com.shitcoims.firehose` | PumpPortal push feed; **funded key `~/.pumpportal-key`** (0.01 SOL / 10k events) unlocks `subscribeTokenTrade` per-mint trade streams |
| cluster | `com.shitcoims.cluster` | cluster tape recorder on **12 pools** (`state/cluster_tape/swaps/`) |
| inteld | `com.shitcoims.inteld` | intelligence daemon |
| paperdesk | `com.shitcoims.paperdesk` | **5 books**: medium, short, wiggle, toll, **operator** (the hunch book) |
| swarms | `com.shitcoims.swarms` | swarm/duel census (`state/swarms/census-*.jsonl`, families, candles) |
| hunch | `com.shitcoims.hunch` | the hunch-capture API behind the glass |
| watchdog | `com.shitcoims.watchdog` | supervises all of the above; report-only for dead-by-choice components |

**THE SENTINEL IS DEAD BY OPERATOR CHOICE. Never restart it.** It is absent from launchctl on
purpose (the automated sell-only engine that lost 7.47 SOL). Its state files (`state/sentinel-
state.json`, `state/LIVE_ARMED`) linger but nothing runs them. The ban lifts in conversation,
never in a UI, and v2 builds instruments to *earn* the lift, not to resurrect it.

The watchdog uses the sentinel's alerting *mechanism* but not its code; its freshness targets are
becoming product SLOs under JOSHI (a stale trenches feed is a defect with an owner).

---

## 5. The hunch loop / operator book — the desk's future

This is the live capture surface for the operator's judgment, and it is where the next real edge
is expected to come from (the (state, action) tape is the intuition training set).

- **In the glass**: press **8** to reach the coin explorer; each card carries **[wiggle] / [down]
  / [up] / [watch]** and every operator position carries a one-keystroke **zap** (exit, no
  ceremony, records full tape-state at the moment of exit). CLI mirror: `scripts/hunch`.
- A `[wiggle]` opens a real paper position in paperdesk's **operator** book; the belief is
  recorded *before* the instrument readback flips, so the scorecard can later measure what the
  operator's eye adds over the instruments. Row shape is deliberately the JOSHI `Expectation`
  record's, so migration is a read, not a reconstruction.
- The tape is `state/hunches.jsonl`, append-only, fsynced, verbatim utterance, `hunch.retraction.v1`
  rows instead of edits.

**Status: 0 real operator rows.** All 12 rows currently in `hunches.jsonl` are agent/test demos,
and **every one is retracted** (each has a matching retraction row explicitly stating "not an
operator gesture"). The plumbing is proven end-to-end (CLI → tape → HunchSource → operator book →
fill → clock → close → zap); it is waiting on the operator's first real gesture to populate the
training set. The zap-recorded (state, exit) pairs are the corpus the reactive-exit policy (JOSHI
model-ladder rung 0) will be fitted to — so the 5-minute wiggle clock is a *backstop*, not the
policy (the operator's exits were always reactive; hold-duration was never the rule).

---

## 6. The data assets

- **`state/bulk_pump/` — the 10-day full-flow corpus.** ~55 GB, 10 daily parquet shards
  (2026-08-05 → 08-14), **106,639,238 transactions** — the corpus `operator_crime` ran on. It is
  **born-in-window**: it contains only coins created inside the window, which is the `--select`
  trap documented in the latest commit (a coin-subset filter on `coins.parquet` silently drops
  everything born before the window). One `corrupt_shards.txt` present — check it. Mirrors are
  meant to live on persvati and hbox; `scripts/corpus_verify.py` is referenced as the check but
  **does not exist yet** — until it lands, do not trust a remote mirror without verifying it
  yourself.
- **`state/bulk_history/` — the 48-day 11-pool history.** BigQuery replay-grade, 2026-06-27 →
  08-13, ~368,795 rows/day across 11 pools, exact-integer pre/post vault reserves, validated
  876/876 swaps on both legs. This is the deep tape for fee-stream reconstruction and pool
  physics. Trap: `failed` ≠ `attempt` (90.1% of pump.fun txs are failed sniper bots; a ~24× gap).
- **The affine pricing identity — the enabling tool.** For any constant-product pool `x·y=k`,
  marginal price `p = k / v_tok²`, so **`log p = log k − 2·log v_tok`** (`v_tok` = token vault
  reserve). This prices every coin exactly from one vault read plus `k` — no aggregator, no fee,
  $0. It underwrites the entire cluster-physics program. It is *also why* the hardcode audit's
  `decimals … or 0` bugs are catastrophic: a wrong exponent corrupts `v_tok` and blows price up
  by 10⁶–10⁹×.
- **The tapes**: `state/cluster_tape/` (12 pools of swaps), `state/callouts/`, `state/callers/`,
  `state/crime/`, `state/firehose/`, `state/swarms/`, plus the study data caches under
  `studies/data/`. The pump.fun social layer is free and every content object carries a native
  `walletAddress` (`pump_social_api`) — the handle→wallet join that crippled caller studies is
  dissolved; `pumpsocial` collects it.

---

## 7. The compute

- **persvati (24c / 83G, never sleeps)** — the box for heavy folds and the corpus mirror. It is
  **memory-bound via DuckDB thread count, not `memory_limit`** — cap threads, don't cap memory,
  or it OOMs. It hosts the always-on collectors/watchdog and, under JOSHI, will host `joshid`
  (projections and horizons must survive a closed laptop lid).
- **hbox (24c / 123G, /tank 1.9T)** — secondary corpus node for wide sweeps. **Co-tenant with
  codex's OWN datacake HOL build** — spare its poly/Holmake procs, keep waves small, build under
  `swarm-build` (enforced MemoryMax; bare `taskset` caps CPU only and memory is what kills the
  box). earlyoom is live and sshd is OOM-immune.
- **The Mac** — interactive / the glass / the only key-holding box. Keys never leave it, so there
  is no unattended broadcast path anywhere in the topology, by design.
- `SUBSTRATE.md` is the v1.5 consolidation plan (five packages: `tapecraft`, `marketdata`,
  `friction`, `cohortkit`, contracts-as-seams); **`JOSHI.md` is the v2 that supersedes it** where
  they conflict (JOSHI §10 reconciles them explicitly).

---

## 8. JOSHI v2 status — design-complete, not built

`JOSHI.md` + `design/{domain-model,glass,reconciler}.md`. **The frame: JOSHI is the operator's
private copy of the pump.fun app** — the same daily surfaces served from our own tapes with the
instrument disciplines and the operator-native gestures (hunch, zap, expectation, duel) woven in.
The creator side (launching) stays on the real pump.fun, manual forever.

- **The architecture**: one append-only typed **journal** as the single seam; every state store
  is a pure fold over it; the only mutation path is a command; every automated decision carries
  its propensity. TAPE (world observations) and JOURNAL (desk facts) are separated *by type* — the
  fix for v1's closed-loop contamination. Language cut: Lean kernel (fills/accounting/envelope/DSL,
  already built, load-bearing via the `joshi-oracle` C ABI), C#/.NET domain core, TS glass (kept),
  Python research (unchanged), ported Python signer organs.
- **Status: NOT built. No code has changed.** It is design-lane output. It awaits the operator's
  (1) confirmation of **ceremony placement** (per-order for Quality, at-playbook-arm for Scalp —
  proposed-normative, marked pending), and (2) blessing of **M0**, the first phase:
  *journal-alongside, riskless* — stand up `joshid` + the schema registry, tail v1's existing
  state files read-only and lift them into journal events, nothing depends on the journal yet.
  Exit criterion: journal replay reproduces v1 state snapshots with zero divergence over 7 days.
- **harden-don't-rewrite still binds.** The money organs (`transaction.py`, lpexec guard/allowlist/
  signer), the Lean kernel, the tape contracts, and the research harnesses **port with their
  tests**; nothing that holds keys or touches chain state is rewritten to satisfy a diagram.

---

## 9. Open questions, ranked

1. **Ladder causality** — make vs pick vs coincidence on the 8-second ladder (§2). Coincidence
   is out; the rest is open. Attack it through **synchronized exits**, and write the study that
   the brief called `ladder_causality.py` (it doesn't exist yet).
2. **Does the operator's intuition-premium survive at n=50+ hunches?** The +$1.14-median /
   +1.96%-exit / +18.1%-basis edges are all real but small-n and selection-driven. The hunch loop
   exists to answer this; it needs real operator rows (currently 0).
3. **The LP rebalance / duty-cycle rule** — the highest-value open LP question. Fee harvest is a
   real toll but hasn't beaten HODL (−$595); the loss is carried by range-exit (49.4% duty cycle)
   and a handful of gap swaps. Whether `η·D > VR` clears over >1 day is unshown — and note the
   day-scale reversion that made the pair look attractive **does not replicate** (`mean_reversion`:
   the prior DREGG/SOLVE ρ̂=0.901 / HL 6.6h re-measures to ρ̂=0.974 / HL 26.2h, p=0.103, and the
   whole question is *unresolvable*, not refuted, until the pools reach ~90 days — which is free,
   so wait rather than spend credits on span you cannot buy).
4. **The wallet-behavior estimator's iceberg detector** — entity resolution / SVN co-trading are
   built and *calibrated* but return no links on the 2-wallet live store; they need a mint-indexed
   multi-wallet panel (1.5–5% of the monthly Helius plan) before any entity-level number exists.
   Their failure mode is engineered to refuse — a future "large entity" means a tripwire was
   disarmed (a degree-preserving null was skipped).
5. **Does a new community-launch renew or cannibalize the DREGG fee stream?** Fee income decays
   with the volume it taxes (volume t½ ~12 d from launch; RW null beats every fitted decay OOS).
   The volume lever (~1.86× → ~$250/day) is worth far more than any boundary-press micro-optimization.
6. **JOSHI M0** — stand up the journal alongside, prove 7-day zero-divergence replay. Riskless,
   additive, and every week not recording the operator's beliefs is data lost forever.

---

## 10. The scars — these are landmines, not trivia (PROGRAM §9 / JOSHI §9.2)

Each is a real cost paid, and each is a class that recurs. If you touch the money path, know all of them.

- **Fabricated cost basis (×3 sites)** — engine auto-protect, `policies.from_quote`, dashboard
  prefill all stamped basis from the *current exit quote*, turning every stop into a loss (−7.47
  SOL). Fixed structurally (basis is a provenance type with no constructor from a quote; draft
  types carry no basis field). The web form's prefill is scar rank-0 in the hardcode audit.
- **Two clocks** — the intelligence store inverted `t_event`/`t_ingest` between kinds (Spearman
  −0.77; one page collapsed 29 h of chain time into an instant). Join on `t_event` only; a
  mixed-clock join must be a type error.
- **Address fabrication / poisoning** — a live campaign dusts leading+trailing vanity matches at
  the operator's real payees within seconds of a genuine transfer. **Two fabricated addresses
  were caught this week via the ed25519 on-curve / base58-decode-to-32-bytes check** (a regex
  passes ~1 in 4 lowercased addresses). Rule: never copy a destination out of transaction history;
  destinations come only from the attested address book.
- **The −151% partial row** (and the censored-96% drop, the 24× attempt overcount) — hand-rolled
  loops folding partials/censoring wrong. This class is the reason for the "no study row-loops a
  corpus" tripwire.
- **Double-submit** — signature recorded only on confirm, so a retry built a fresh order and
  over-sold with scale-outs live. Fix: record the signature *locally before submit*; `unresolved`
  is terminal-pending, never auto-resumed, resolved only by the reconciler on chain evidence.
- **Closed-loop contamination** — including the desk's own sentinel wallet in a treatment set
  manufactured p=0.00498 from nothing (plus a mechanically-floored placebo, 0/32,400 arrivals).
  Own-wallet rows enter studies only through the reconciler with `actor` stamped.
- **Marginal-vs-executable marking** — the +950-vs-−179.65-SOL sign flip on one wallet. Mark at
  executable-exit valuation, never marginal/last-trade price.
- **Hardcoded constants in fact costumes** — `GAS_USD=0.30` (a cap; real median is $0.0042, 33–94×
  wrong, sitting *on* the arb-band boundary); `decimals … or 0` (10⁶–10⁹× TVL error); SOL=$150 in
  our own tree. The `--check` CI gate exists but is green only because nothing has moved; the
  ranked list is unapplied.

---

## 11. What NOT to do

- **Do not re-run dead entry studies** (§1). The law is established ~12 ways; a new costume returns
  null and costs days.
- **Do not restart the sentinel.** Dead by operator choice; the ban lifts in conversation only.
- **Do not mark at marginal price.** Executable-exit valuation always, or the sign flips.
- **Do not trust a remote corpus mirror without verifying it yourself** (`corpus_verify.py`
  doesn't exist yet). And beware the born-in-window `--select` trap on `bulk_pump`.
- **Do not `git add -A` while lanes are live** — commit named files (`git commit -m … -- <paths>`);
  a half-written sibling or a zsh glob-no-match will bite. Backticks in a double-quoted `-m` get
  command-substituted (write prose messages to a file, `git commit -F`).
- **Do not touch the money code to satisfy an architecture diagram.** The signer organs, the Lean
  kernel, the tape contracts port *with their tests*; JOSHI is a new spine around ported organs,
  not a rewrite of anything that holds keys.
- **Do not read an i.i.d. null as a result** — structure-preserving, two nulls, matched density.
- **Do not spare hbox by using bare `taskset`** — `swarm-build` (memory is what kills the box),
  small waves, and spare codex's own datacake procs.
- **Do not build**, per the audited nulls: callout-following, follow-the-wallet copytrading, a PvP
  entry/exit book, an LLM in the screening loop, maker-side (resting-order) execution, an always-on
  Helius firehose, or a token↔token pool as a "cheaper wire" (there is no routing demand — 1 of 593
  swaps was a genuine direct trade; the product is a toll on a cycle you closed, not a wire).

---

## Pointers

- Spine: `PROGRAM.md` (evidence), `SWARM.md` (how to build with a fleet + the audit cadence),
  `SUBSTRATE.md` (v1.5 consolidation), `JOSHI.md` + `design/*.md` (v2).
- Every study is `studies/<name>.py` with a `studies/RESULT_<name>.md` beside it. The RESULT is
  the authority; read it before the code.
- Merge gate: `scripts/check.sh` (ruff, mypy-gated, pytest, dashboard tsc/eslint/render, lake
  build, no-sorry, axiom audit). The Lean kernel builds in ~2s with no mathlib.
- `~/paperbin/` — 93 papers, PDF + extracted `.txt`; grep the `.txt` companions.

The bar, unchanged: the results in this field that survive are *parameter-free relations between
independently measurable quantities*. "My model reproduces the stylized facts" is worth nothing.
Everything else is a simulation that typechecks. Have fun in the trenches ( ⌐■_■ )
