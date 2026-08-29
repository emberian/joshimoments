# $DREGG utility — the product portfolio (2026-08-29)

What we can actually offer, grounded in a full inventory of ~/dev/joshi + ~/dev/joshibot.
The frame Ember set: real analytics with content people want — not honesty-posturing, not
reselling predictions we ourselves refuted. The assets that survived the season's ~12
refutations point at exactly three sellable categories: AVOID (rug/launch screening),
KNOW-YOUR-ENEMY (wallet/caller/crew intelligence), and THE TAPE (measured market structure).
Entry signals are explicitly not for sale — we hold the receipts that they're dead, and that
negative knowledge is itself content.

## The five products

### 1. LAUNCH SCREEN — birth-time rug risk, live  ⭐ strongest predictive asset
From ONE SLOT of data at coin birth (joshibot `operator_crime`, 106.6M tx):
- bundled-at-birth coins rip at 1.598% vs 0.070% — 23× separation
- the birth-time CLEAN screen admits 4.8% of coins at 99.96% clean — 20× fewer collapses
- the persistent bad actor is the SNIPER CREW, not the deployer (birth-slot sniper overlap
  Jaccard 0.2834 same-deployer vs 0.0014 matched) — crew reuse is trackable
- 96–99% of lifetime rip risk resolves in the first hour
Product: a live launch-safety feed + API (webhook/TG): every new pump.fun launch scored
within seconds — CLEAN / BUNDLED / KNOWN-CREW + the measured base rates. B2B angle:
launchpads, TG bots, and wallets integrate the score (paid in $DREGG).
Build gap: wire the existing firehose to the (already-validated) screen; re-train cadence.

### 2. WALLET DOSSIERS — the 728k-wallet behavioral layer
joshibot `state/wallets/`: 728,017 wallets × 44 features over 58.7M priced legs, with a
written JOIN CONTRACT; rebuilds from corpus in ~1 minute.
- guild (HARVESTER/SLOW/ACCUMULATOR/FLASH/AFTERMARKET — only AFTERMARKET is net-positive)
- realization-policy fingerprint (LOSS_CUTTER / AVERAGES_DOWN / PROFIT_RUNNER / preset-bot)
- EXECUTABLE realized PnL (never marks unsold bags), win rate, hold times, entry latency
- iceberg detector: 4.35M distribution episodes — "a large holder is piecewise-dumping this
  coin" — plus per-coin exit signal (5,345 coins)
Product: wallet lookup + per-coin holder composition ("who am I trading against in THIS
coin: 40% preset bots, 2 known crews, 1 active iceberg"). The measured headline is the
marketing: the crowd netted −738k SOL in 10 days; 32.5% of wallets are net-positive.
Build gap: scheduled corpus refresh (the $27 BigQuery pull) + a thin API.

### 3. THE CALLOUT RECORD — caller track records, deletions remembered, receipts sealed
pump-native social (joshibot `pumpsocial` + joshi callout taps): the author IS a wallet;
callouts carry userId, username, entry price, pump's own peak multiple, thesis.
- measured truth for the record pages: callouts are an ANTI-signal (−11.9% @1h, −43.6% @8h,
  WORSE when louder: 2+ callers in 10 min → −64.7%; follower count anti-correlates ρ=−0.502)
- DELETION TRACKING (Ember's idea): snapshot diffs + the community socket's moderation
  events → callers' scrubbed losers stay on their record. Un-retrofakeable — archive value
  compounds from turn-on day.
- TLSNotary seals (Ember's idea): notarize first sightings so the receipt survives disputes
  ("according to pump's own server at time T"). Trust model stated; spike needed on tlsn
  TLS1.3 + pump's CDN.
Product: leaderboard + per-caller pages + deletion alerts. Spicy, shareable, and the only
honest one possible — everyone else's leaderboard is gameable by deletion.

### 4. THE DAILY PVP WIRE — the flagship report (the $DREGG daily)
Generated largely by the resident analyst from live taps + the corpus. Sections that write
themselves from measured machinery:
- launches: count, graduation rate (base 0.63%), screen-category mix, notable CLEAN survivors
- crew watch: which sniper crews/clusters were active (13,462 clusters mapped; predation
  pairs; the 8-second-ladder graduation detector), deployer recidivism
- the PvP meter: failed-bot pressure (90.1% of txs are failed snipers; failed≠attempt 24×),
  rotation cohort share, fee seasonality clock (peak 15:00Z, +32% over trough)
- flow leaderboard: biggest measured winners/losers by guild, iceberg activity roundup
- callout desk: the day's loudest calls + the callers' real records + deletions caught
- workability corner (joshi census machinery): which structure persisted (ρ=0.59), the
  regime mix (σ² signature)
Free tier gets three teaser items; holders get the full wire + archives.

### 5. THE RESEARCH VAULT — datasets + methodology for quants
- bulk_pump: 106,639,238 exact-integer transactions, 10 days, provenance-stamped, traps
  documented; bulk_history: 48 days incl. 922k FAILED txs; tapes; wallets parquet
- the 46 RESULT docs (the refutations are the demo of rigor), the Lean kernel + LiteSVM
  differential oracle, replay/OPE harness with leakage guards
Product: dataset access + published-research cadence. Some RESULTs published free as
credibility marketing ("we measured callout-following so you don't have to fund it").

## Tiers (sketch — numbers TBD with Ember)
- FREE: weekly caller leaderboard, wire teasers, rate-limited wallet lookups, published
  research. The funnel.
- HOLDER (hold N $DREGG): full Daily Wire + archive, full Callout Record + deletion alerts,
  full dossiers, launch-screen daily digest.
- STAKER (hold M >> N): LIVE launch-screen feed (webhook/TG), live iceberg/exit alerts on
  named coins, rate-limited API.
- PARTNER/B2B: full API + datasets + white-label screen integration for launchpads/TG
  bots/wallets; custom questions answered by the resident analyst. Paid in $DREGG.

## Sequencing (cheapest-first, value-density order)
1. TURN THE ARCHIVE ON (days): callout snapshots + deletion diffs start compounding now;
   keeper back on; corpus refresh scheduled. Zero product risk, pure asset accrual.
2. CALLOUT RECORD + first DAILY WIRE (1–2 weeks): data exists; resident writes the wire;
   static site + TG channel gated by a $DREGG balance check. First visible utility.
3. LAUNCH SCREEN live (2–4 weeks): firehose→screen wiring; the flagship API.
4. DOSSIERS API (after refresh cadence proven), VAULT last.
5. TLSNotary spike runs parallel (research-grade, not blocking).

## Standing constraints (engineering bars, stated once)
Corpus freshness (bulk ends 08-14 — refresh is a scheduled $27 spend); recall unmeasured on
the %pump filter; screens RANK, they don't convict (the dossier/record language must carry
this); the do-not-build list stands (no entry signals, no callout-following, no copytrading
products — we sell the refutations instead); read-only posture everywhere; keys/venue ToS
reviewed before anything is hosted for third parties.

## v1 decisions locked (2026-08-29, Ember)
- All three products staged tight; hbox hosts everything; TG-gated + public site.
- GATE THRESHOLD: N = 3,333,333 $DREGG (≈$1,065 at lock time, px $0.0003194) — token-denominated.
- TG bot: reuse @ltshitcoims_bot's existing token (~/.shitcoims-tg) — ONE bot process serves
  gate + invites + Ember's approvals/alerts. New handle only if branding warrants later.
- Helius: Ember's existing ~/.helius-key goes to hbox (her machine); no separate product key.
- Cloudflare: account exists; only a wrangler token needed at site time.
