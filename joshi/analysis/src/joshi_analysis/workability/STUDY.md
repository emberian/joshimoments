# workability census v1 — which statistics tell us which coins to work?

Registration version: `joshi.workability_census.v1`
Registered: 2026-08-24, BEFORE any provider request of this study was made and before any
sampled coin's tape was seen.

Author knowledge disclosure (required, non-blank): the author has read `HANDOFF.md`'s measured
findings (the n=6 callout dip study, the 0-of-5 replay negative, the fee-tier-dominates
finding), `scalplab/REGISTRATION.md`, the route catalog's measurement notes in
`crates/joshi-pump-api/src/catalog.rs`, and the callout_entry_window scripts. The author has
seen NO price path, NO tape, and NO row of any coin this census will sample. The tier-latency
decomposition below is a reconstruction of the primary agent's method from its one-line
description (slot = first 12 digits of `slotIndexId`; legs at same-slot / +2 / +8 / +32); the
primary's own implementation was not found in the tree, so the precise definitions in section 3
are DECLARED HERE and are this study's, not a paraphrase of measured prose.

Any deviation from this protocol requires saying so in the run section, per house rules.

## 0. The question, in Ember's words

A lightweight census over pump.fun — mints from the past 3 days, a scattering of callouts from
the past 1 day — asking: are there *statistics* that tell us which coins to work? are any of
our autostrats (sad as they are rn) up to the task of harvesting out of them? These are NOT
her selected coins; this is the control corpus, a study.

**This whole census is an oracle-window STUDY.** Every tape here is a retrospective backfill
(`retrospective_none` decision clock, in scalplab's vocabulary): the polls that retain the
trades run after the fact, so no number below is a live-executable claim. Window-B "outcomes"
are what a coin OFFERED, bounded by an oracle that saw the window whole; realized harvest under
a live clock is strictly less, by an amount this study cannot measure.

## 1. Population and sample

Enumeration routes (all anonymous product reads through `joshi-pump-product-read`, each gated
by its reviewed row projection; every request ledgered):

- `discovery_coins` sort=`created_timestamp` DESC, 3 pages of 70 — the newest cohort.
- `discovery_coins` sort=`last_trade_timestamp` DESC, 3 pages of 70 — the recently-active
  cohort. (The /coins route carries NO volume field; activity here means "printed a trade
  recently", nothing more.)
- `currently_live` 2 pages — the livestreaming cohort, the only audience-size number anywhere.
- `coin_search` searchTerm sweep of 4 generic single-letter terms, 1 page each — the ONLY
  route carrying `volume_1h_usd`; a term sweep is a biased sample of whatever the terms match,
  stated as such.

Known biases, named: none of these routes is a census; /coins moves under its own offsets
(~1 coin/s creation), the board is not enumerable to 3 days' depth (~260k mints), and every
row here is a coin the PRODUCT chose to show someone. The population this sample represents is
"coins the discovery surfaces would show an anonymous visitor on 2026-08-24", not "coins that
exist". The BigQuery designs in section 8 are how the true denominator would be measured; they
were not run (credential finding stated there).

Stratification: from the union of enumerated rows, keep mints with `created_timestamp` within
72h of the census instant, then draw ~250-350 mints stratified across:

- age bucket: 0-6h, 6-24h, 24-48h, 48-72h (from `created_timestamp`, provider-asserted);
- market-cap bucket at enumeration: <$10k, $10k-$50k, >$50k (`usd_market_cap`,
  provider-asserted, read-time);
- graduated vs bonding (`complete`, provider-asserted).

Cells are filled by deterministic seeded draw (seed declared in the manifest); cells with fewer
members than their quota take everything they have and the shortfall is reported, never
back-filled from fatter cells. Coins whose tape turns out empty (zero retained trades) are
retained in the manifest with that fact — an empty walk is a finding about the stratum, not a
re-roll.

Callout sample (section 6): from the last 24h, targeting n≈60-120 callouts, via
`callout_top` (promoted rows) on the sampled active mints plus `community_callouts`
(fixed newest-50 window, poll-or-lose) on the most active sampled mints. `community_callouts`
has NO reviewed row projection in the tree today; its bytes are retained by the admission path
but quarantined, and every number derived from them is labeled `retained_quarantined`.

## 2. Per-mint measurement (~3-5 requests each, hard ledger)

Per sampled mint:

1. `joshi-pump-trades-backfill`, 2-4 pages of 100, newest-first, into a PER-MINT state dir
   (one coin per catalog; the grid replay refuses mixed-tape dirs, and this keeps provenance
   per-coin). The retained span is whatever 200-400 trades cover — minutes on a busy coin,
   days on a quiet one; the span is a per-coin fact carried on every number.
2. `coin_exact` (1 request): venue, market cap, created, `complete`, `pump_swap_pool`.
3. `candles` interval=1s, currency=SOL, limit=1000 (1 request). The candle window is
   NEWEST-ANCHORED at read time, i.e. it overlaps window B (and the post-B present), NOT
   window A. Candles therefore serve ONLY as a B-side cross-check of realized range against
   the trades tape, and never as a window-A feature. (This is a deviation from the tasking's
   sketch, which listed candle slope under features; anchoring makes that leak, so it is
   moved to the outcome side with this note. Candles are read for a random ~1/2 subsample of
   mints to stay inside budget; subsample membership is seeded and recorded.)

Tapes are loaded through `scalplab.tape.load_tape` (REGISTRATION.md governs; the loader's
dedupe, exact-Decimal prices, and provenance are reused verbatim). Expected provenance:
`pump_api_polled`, `retrospective_none`.

## 3. The tier-latency decomposition (the shared helper, declared)

Slot: the first 12 digits of `slotIndexId`, as integer (scalplab's `_SLOT_DIGITS`). One slot
≈ 400ms nominal Solana cadence; tiers are stated in slots, rates per hour of venue event time.

**Movement shares.** Over a window's deduplicated, slot-ordered events: total movement =
Σ|Δ log price| over consecutive events. The intra-slot share is the fraction of that sum from
pairs in the SAME slot; cross-slot is the rest. Intra-slot movement is unreachable to any
actor slower than same-slot inclusion.

**Floor-clearing legs.** Decompose the price path into alternating trough→peak legs
(a leg boundary wherever direction reverses on the event path). An up-leg CLEARS THE FLOOR
iff peak/trough ≥ 1 + floor_bps/10⁴, exact Decimal comparison, scalplab-style. Legs/hour =
count / (window event-time span in hours).

**Tier survival.** For delay δ ∈ {0 ("same-slot"), 2, 8, 32} slots: an up-leg survives δ iff,
entering at the first event with slot ≥ trough_slot + δ (for δ=0: the next event with slot ==
trough_slot; absent such an event the leg is unavailable at tier 0) at that event's price, the
remaining rise to the leg's peak still clears the floor. Tier-δ legs/hour counts surviving
legs. δ=32 ≈ 12.8s ≈ the measured chain-to-receipt latency of our own polling infrastructure
(HANDOFF: "~12s chain-to-receipt at finalized") — tier 32 is the tier we could plausibly act
at today; tier 0 is the co-located oracle bound, named as oracle.

**Floors.** Primary: per-coin venue floor — bonding coins 247 bps round trip (Study M0's
measured curve floor, the `callout_entry_window` constant); graduated coins 2 × the leg bps of
the fee-tier row their SOL market cap selects, worst-of-the-two-retained-tables
(`joshi-liquidity/src/tier.rs` retained table heads, verbatim constants; the SOL market cap
proxy is price × 10⁹, the callout-route identity). Sensitivity: the flat declared 250 bps
(scalplab default) computed alongside every primary number.

## 4. The A/B split and the candidate statistics

Split rule, declared: per coin, split_instant = earliest event time + 1/2 of the event-time
span (venue timestamps, 1s precision) — the same fraction-of-event-time-span rule as the grid
panel's declared split (`--split-num 1 --split-den 2`), so the Python split and the replay's
held-out window agree up to timestamp precision (any residual mismatch is reported per coin).
Window A = events strictly before split_instant; window B = events at/after it. Features read
A only; outcomes read B only; nothing crosses.

Candidate statistics from window A (denominator: the window's own DURATION — see RUN note R1:
clarified after pilot coin 1 and before the full run, a rate over a time-split window divides
by the window's time length, so a half-window in which the coin died is a zero rate, which is
an outcome and never an insufficiency. A coin with <20 A-events is insufficient for features;
the replay arm additionally requires >=10 B-events):

| id | statistic |
|-----|-----------|
| S1 | tier-0 floor-clearing legs/hour (A) |
| S2 | tier-2 legs/hour (A) |
| S3 | tier-8 legs/hour (A) |
| S4 | tier-32 legs/hour (A) |
| S5 | trade intensity, trades/hour (A) |
| S6 | unique traders/hour (A) |
| S7 | trader concentration: unique/total (A) |
| S8 | buy imbalance: signed quote volume / total quote volume (A) |
| S9 | drift slope: OLS of log price on hours (A), per hour |
| S10 | realized log range (A) |
| S11 | intra-slot movement share (A) |
| S12 | callout count with createdAt inside A (occurrence clock; absent where no callout route row exists — absent, not zero) |
| S13 | log SOL market-cap proxy at split: last A price × 10⁹ |

Outcomes on window B:

| id | outcome |
|----|---------|
| O1-O4 | tier-{0,2,8,32} floor-clearing legs/hour (B) |
| O5 | grid harvest (section 7; replay arm only) |

## 5. The interaction test

**Pre-named primary pair** (the only tests this study calls confirmatory):
(a) S4→O4 — does window-A tier-32 workability predict window-B tier-32 workability? (the
persistence question); (b) S5→O4 — does cheap intensity predict it just as well? (the
"do we even need the fancy statistic" control). Test: Spearman rank correlation, exact-tie
handling, n stated; significance by permutation (10,000 seeded shuffles).

Everything else — the full S1-S13 × O1-O4 grid — is EXPLORATORY. The multiple-comparisons
reality is stated with the table: 52 cells on a few hundred coins; naive Bonferroni holds a
cell only below α=0.05/52 ≈ 0.00096, and any cell that survives is still one census on one
72h window of one venue's product surface. Decile contrast reported alongside: median O4 of
the top decile by each S vs the median of a seeded random control drawn from the same
eligible pool, with both n's.

## 6. The callout arm (n=6 → n≈100)

For each sampled callout with `createdAt` (occurrence time, epoch ms on `callout_top`,
ISO-microseconds on `community_callouts` — normalised explicitly, per the catalog note): if
the mint's retained per-mint tape already covers [t0−5min, t0+30min], measure from it;
otherwise one dedicated seek walk (`--seek` t0+30min, `--stop-before` t0−5min, ≤2 pages) into
a per-callout state dir. The measurement is the callout_entry_window `excursion.py` method,
carried over so the numbers are comparable with the n=6 study: anchor = first trade at/after
t0; dip depth/timing below the anchor; entry-coverage gate (tape must reach t0, else the
window is tail-only and EXCLUDED from the dip distribution — busy-coin coverage bias stated);
would-quote lift from anchor vs from trough, net of the per-coin floor of section 3.

ON EVERY NUMBER: the occurrence-vs-availability confound — `createdAt` says when the callout
says it happened, never when we could have known; short-lag structure mixes reaction-to-callout
with what-the-callout-reacted-to, and this study cannot separate them.

## 7. The harvest arm (are the sad autostrats up to it?)

The only committed autostrat family that can replay a POLLED tape is the grid-ladder ensemble
(`target/release/examples/grid_tape_replay --polled-root`, panel contract
`joshi.liquidity.grid_sweep_panel.v1`). Its declared selection rule picks a cell on the FIRST
window and evaluates it once on the held-out window — which is this study's window B under the
same 1/2 split. The harvest number harvested per coin: `held_out_net_bps` of the
first-window-selected cell, read beside `held_out_full_hold_bps` / `held_out_half_hold_bps`
and the panel's own drift haircuts.

Named limitation, found in recon: the polled replay derives ONLY `pump_amm` rows — the
committed family CANNOT price a bonding-curve coin from a polled tape. The harvest arm is
therefore graduated-coins-only, and "are our autostrats up to harvesting bonding coins" is
answered NO ON CAPABILITY GROUNDS before any economics: the tooling cannot currently express
the attempt. That absence is a first-class result.

Design: among eligible coins (pump_amm venue, ≥20 A-events, ≥10 B-events), replay (a) the top
decile by S4(A), (b) an equal-n seeded random control from the same eligible pool. Question:
does selecting by the statistic improve what the family extracts on B, net of its own
haircuts? Report the two distributions of held_out_net_bps with n each, the win-rate against
doing-nothing-outside-adverse, and the difference with a permutation p (10,000 seeded).
The five socket-tape scalper variants (`tape_replay`) cannot run on polled tapes at all —
stated, not worked around.

## 8. Budgets, receipts, and what BigQuery would add

Hard budget 2,200 provider requests, self-enforced by an append-only ledger checked BEFORE
every spend (the callout_entry_window Ledger pattern); refusal at the ceiling is a
deliverable. Pacing ≥2.0s between product reads; `community_callouts` shares a measured
~1 req/s GLOBAL budget with every pump.fun visitor — paced ≥3s and a 429 is weather, never
absence. Helius (≤200, key present at ~/.helius-key) is spent ONLY if a sub-question needs
chain truth; the census as designed needs none (every clock and price is labeled
provider-asserted), so the expected Helius spend is 0.

BigQuery finding, checked cheaply as instructed: the `bq` CLI (2.1.29) and gcloud credentials
exist, but the BigQuery API is DISABLED in the only configured project
(`gen-lang-client-0657209111`); enabling it is setup this study will not do. The three
population-level queries that would de-bias section 1, designed and not run:

1. **The true denominator.** Count mints created per 6h bucket over the 72h window on the
   pump.fun program (`bigquery-public-data.crypto_solana_mainnet_us.Instructions` filtered to
   the pump program id and create instruction, partition-pruned to the window), with per-mint
   trade counts — the population age × activity histogram our product-surface sample would be
   weighed against.
2. **Population intensity distribution.** Per-mint swap counts and unique signers over the
   same window (Instructions/Transactions join, partition-pruned) — locates our strata in the
   true intensity distribution and prices the survivorship of "the board showed it".
3. **Population tier structure.** For one 6h slice, per-slot trade counts per mint —
   the population share of intra-slot vs cross-slot printing, to check whether the sample's
   tier decomposition (S11) is representative or board-selected.

Each would be dry-run first; the Solana public dataset bills terabytes when unpruned, and the
run gate is an explicit stated estimate per query.

## 9. Honesty floor

House rules throughout: absence stated, ages on every number, provider claims labeled
provider-asserted, oracle bounds named oracle, `retrospective_none` on every tape, no
statistic promoted to "signal" language without its out-of-window number beside it, negative
results first-class. The run section below was empty when this design was registered.

---

# RUN (filled in after; any deviation from the above is flagged inline)

(to be completed)
