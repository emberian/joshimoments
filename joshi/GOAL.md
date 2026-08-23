# GOAL — close out work and science before 6am (2026-08-22)

**Standing goal.** Iterate on improving JOSHI, answer questions, access what data is needed
(up to $10), and close out as much work and science as possible before 6am.

## What JOSHI is actually for, so no lane compresses it

Ember trades memecoins on pump.fun. She spots a coin with good live volatility and WORKS it —
repeated entries and exits pulling profit out of the wiggle. She calls that a **crackle**; a coin is
a **venue she works**, not a position she holds. Real crackles are **8-20% lifts over minutes to
tens of minutes**, sometimes returned to later. The product is: she says "LOOK AT $BOOBUS, GREAT
MICROVOLATILITY", and the machine helps her pull a few dollars out, often enough to pay rent.

## The governing corpus

`docs/microstructure/trades_quotes_prices/` (2,739 lines, from Bouchaud/Bonart/Donier/Gould) is the
best thing in this repo and governs all analysis. Three binding rules:
1. **There is no universal price.** Seven distinct objects; the gaps between them are state variables.
2. **On a bonding curve, price movement is deterministic given reserve state.** Flow is the signal;
   price is a readout. Any response study must first subtract deterministic curve movement.
3. **Event time and wall time are both first-class.** Solana adds slot/tx/instruction/landing/finality.
   Support multiple clocks without inventing a total order.

Its research program is already numbered M0-M4 with falsifiers and "useful residue" for each.

## Thrust

- **M0 price geometry** (deputy live): replace the 190 bps scalar with round-trip cost as a FUNCTION
  OF SIZE at real reconstructed state. Decides whether crackle economics hold at Ember's clip size.
- **Phase 1 corpus** (deputy live): 100M+ rows of authoritative market-wide signed flow in
  ~/dev/joshibot/state/bulk_pump, never read by JOSHI. Make it queryable; then measure how common
  8-20% excursions actually are.
- **Phase 3 discovery**: turn on DiscoveryCoins/CalloutRecent so Ember can find coins inside JOSHI.

## Two findings from reading FORMAL_MODEL.md myself

**1. JOSHI has ZERO of the six types the corpus calls the minimum semantic boundary.**
`MarketObservation`, `PriceObservation` (kind: mark|marginal|size_quote|fill_average|liquidation),
`SignedFlowEvent`, `ImpactStudyRow`, `LiquidityProviderEpisode`, `OperatorEpisode` — 0 files each
across 38 crates and 177k lines. What exists instead is five registration/receipt ceremony types
around "episode" (EpisodeBasisV1, EpisodeProtocolRegistrationV1, EpisodeProtocolReceiptV1,
EpisodeLaunchRegistrationV1, EpisodeLaunchReceiptV1) and no type saying what an episode IS —
inventory epochs, partial exit, runner, flat watch, re-entry. The apparatus grew the paperwork
around every concept and never the concept. The corpus's own line: "Anything substantially more
should be earned by one concrete JOSHI study." 38 crates is substantially more and none was earned.

**2. The adaptive timescale instrument already exists as Definition P2.**
Signature volatility sigma^2(tau) := V(tau)/(tau*pbar^2) over the variogram V(tau) := E[(p_{t+tau}-p_t)^2].
The curve RISES with net positive serial dependence and FALLS with net mean reversion. So you do not
pick an interval — you sweep tau and read where structure lives. CORRECTED BY EMBER 2026-08-21 23:40: a crackle is NOT just dip-then-recover. That was the first
example she happened to give, and I built an instrument on it twice. Sometimes she enters and it is
simply going up. So the signature plot does not IDENTIFY a crackle, it TYPES one: falling curve =
mean-reverting (dip-and-recover) kind, rising curve = positive serial dependence ("Goin up") kind.
Both are extractable and both are crackles.

What is common across crackles is therefore NOT a shape. It is: moves large enough to clear cost, at
a timescale she can act on, repeating often enough to work the coin more than once. So the honest
measurement is the UNSIGNED excursion magnitude distribution at her timescale plus the repeat rate
per coin, with the shape allowed to fall out per coin rather than being assumed. This may be how the
"2-5 types of crackle" become measurable: cluster worked coins by signature shape plus flow stats
and see whether they separate. That is operator-process Q2 answered by measurement rather than by
asking her to introspect a taxonomy.

Comparing the signature of a coin Ember would work against one she would not is still a direct
measurement of her selection and still needs no taxonomy from her. This replaces the 1-second-bar
approach entirely.

## CORRECTION I OWE EMBER

I told her repeatedly that the 55GB corpus had "never been read by anything" and framed Phase 1 as
first contact. **That is false.** joshibot has roughly ten completed studies against these exact
bytes (seasonality, callout_volatility, jackduval_workup, operator_crime, quality_callers,
failure_stream, cluster_map, bundle_hypothesizer, unrealized_pnl, plus RESULT_*.md), and
joshibot/scripts/pump_history.py documents the collection method, the zero-failures property and the
curve-price identity. Every one of those facts was independently re-derived tonight and matched. The
corpus was composted along with a repo that had already mined it. Correct framing is PORT AND
RE-VERIFY, never first read. I asserted "nobody has ever read them" in a deputy brief and to Ember.

## THE REAL BOTTLENECK, clarified by Ember 2026-08-22 00:30

When Ember said she "cannot execute on her trades efficiently" she did NOT mean cost, slippage or
strategy. She meant, verbatim: **"i literally couldn't push buttons fast enough to capture the
opportunity before it scrolled past me."**

That is an interface problem, and it is the founding problem of the project: she uses a screen reader
and works keyboard-only, and JOSHI exists because pointer-heavy tools hurt her hands. I spent most of
tonight on microstructure and never touched the thing actually stopping her.

Her own August spec already said it: "i select coins that the automation will watch for a microdip,
buy it, scalp as soon as a extremely minimal +PnL is taken. IT'S GOTTA BE REACTIVE AFTER MY
DECISION." She was never meant to press the buttons. She decides; the machine reacts. Today no
mechanism exists to hand a coin to anything, so she does selection AND reaction AND execution by hand
against a feed that discards.

**The key asymmetry: pump.fun's feed FORGETS, and JOSHI is a retention machine.** A coin that
scrolled past is an opportunity that existed and was lost because nothing held it. Fixing that needs
NO execution authority and is buildable read-only. Deputy dispatched: one keystroke to hold, held
means held across feed refreshes, the mark commits durably through the existing gesture route bound
to exact scene bytes, and NO taxonomy at capture time.

Tonight's microstructure work is not wasted — M0 says what size to take once she can act, the
census says the supply is there — but neither addresses the bottleneck she named.

## CORRECTED 2026-08-22 01:08 — the FEE TIER dominates, not the venue

I told Ember "choosing a graduated pool over a mid-curve coin is worth more than any execution
refinement". That is one step short of true and I should not have said it that way.

A freshly graduated PumpSwap pool read tonight: **249 bps fee floor, 0.81 SOL max clip at 8%** —
indistinguishable from the bonding curve and 4x worse than the other pool. Its 42.8 SOL market cap
selects the fee program's FIRST TIER ROW at (lp 2, protocol 93, creator 30) = 125 bps a leg, the
same as the curve. **"Graduated" alone predicts nothing.** The lever is WHICH TIER ROW THE MARKET CAP
SELECTS, and the readout now prints it. Next increment worth having: how far she is from the next
threshold, since the tables are steep (creator 30 -> 95 -> 90 -> ... -> 5 bps) and proximity to a
boundary is actionable.

Also: the two PumpSwap tier tables DISAGREE over a wide populated band (second threshold at 420 SOL
vs 59 SOL of market cap) and no retained byte says which applies. The readout uses the WORSE of the
two and says so — errs against the trade, never for it. The fix is reading the fee program's GetFees
return from a landed swap's inner instructions.

**State age is bigger than any arithmetic in this whole lane.** Chain-to-receipt was 11-13 seconds,
mostly `finalized` commitment depth rather than slowness. The graduated pool moved 9-10 bps in 30
seconds (~17-29 bps/min), so **its entire 60 bps fee floor is two to four minutes of drift.** The
commitment choice is a priced decision, not a default.

## THE ORIGINAL M0 FINDING (superseded in part by the above)

Largest clip an 8% crackle can gross-break-even on:
  live bonding curve (42 SOL reserve):  **1.12 SOL ~ $108**
  graduated PumpSwap (1,493 SOL):       **54.1 SOL ~ $5,250**
At 20%: 3.47 SOL ($337) and 137.9 SOL ($13,400). ~50x difference in tradeable clip, from 4x on fees
and 35x on depth. **Choosing a graduated pool over a mid-curve coin is worth more than any execution
refinement this project could build.** With a real network fee it is an INTERVAL not a ceiling —
below ~0.0004 SOL the tx fee eats the trade — so the hurdle is U-shaped.

Two different things get called "round-trip cost":
  ABORT COST (buy then sell back) is FLAT at every size, because traversal reverses exactly.
    247 bps curve / 60 bps pool.
  CRACKLE HURDLE (how far the mark must lift to break even) CLIMBS.
    254->5,672 bps curve / 61->1,451 bps pool.
The 190.03 bps figure was neither: 190.03/2 = 95.015 = exactly the on-chain protocol
fee_basis_points of 95, so it caught the protocol fee and MISSED the 30 bps creator fee. True
pump-curve floor is 246.91 bps. Dimensionless law: hurdle_bps ~= 2*fee_bps + 2*(clip/Qe), knee at
clip ~= fee_rate * Qe.

Validated against SIX LANDED FILLS TO THE ATOM. M0 continue/stop: CONTINUE scoped to PumpSwap;
for the bonding curve STOP or scope hard. Binding uncertainty is STATE AGE, not quote error — pool
mark drifted 35.6 bps in 49s, curve marginal price fell ~3,575 bps in 13.6 min.

## Handed back, not fixed here

- `joshi-sources::PumpSwapPool::decode` would REFUSE the measured pool and MISPRICE it: requires
  bytes 243..301 zero (they are not) and hardcodes virtual_quote_reserves 0. Omitting the offset-245
  field overstates base-out by 119 bps — 4x the entire round-trip fee, in the FLATTERING direction.
- Global account `creator_fee_basis_points = 5` is STALE; the program applies 30.
- frontend-api-v3 /coins is UNUSABLE AS STATE: 8 of 12 rows marked incomplete were complete on chain
  with zero reserves; of the 4 genuinely live, one was off by 158x. Candidate addresses only.

## CORRECTION 2 from Ember, 2026-08-22 00:45 — I overindexed on "dip and recover" AGAIN

Her actual meaning: **from the moment she starts watching the coin (usually RIGHT AFTER A CALLOUT)
there would usually be a decent-magnitude dip OR OTHER VARIANCE worth considering an entry after.**

It was never a price pattern. It is an ENTRY-WINDOW statement. So my signature-regime work measured
whole-coin-lifetime dynamics when the relevant window is the minutes after a clock starts on the coin.

The methodological key this hands us: **a callout is a t=0 that ALIGNS ACROSS COINS.** Without a
common origin, coin histories are not comparable and cannot be averaged; with one, "what does minute
3 look like across 10,000 coins" becomes a real question. Nothing in this project has ever done a
cross-sectional study because nothing had an origin to align on.

Historical corpus has no callout data (on-chain only), so the available t=0 is FIRST OBSERVED TRADE
— which is exactly Ember's "first day of a coin's life" question. The live callout-aligned version
is the sequel and needs callout capture we do not yet retain (CalloutTop/CalloutByMint are real
routes; CalloutRecent is a phantom).

## Thrust, 2026-08-22 17:10 — THE LIVING WAVE

Ember's call: do not bring it up until it is living. Four Fable deputies, disjoint territories,
building the window instead of the photograph:

- KEEPER (apps/collector, ops/): the process that outlives a terminal. ops/keeper.toml config
  (watched mints DREGG+SOLVE, the wallet, budgets, cadences), bounded acquisition cycles through
  the existing admission machinery, hard self-enforced budgets, heartbeat file, launchd plist,
  kill-mid-cycle coherence. A silent stop must be distinguishable from a still market.
- LIVING SCENE (apps/core, apps/glass): scenes stay immutable; liveness = NEW scenes + the operator
  CHOOSING to advance. Follow mode re-derives on catalog advance via the backup-overlay pattern; a
  scene FEED route lists scenes newest-first (a list of immutable facts, not a mutable pointer);
  Glass announces politely, never swaps silently (screen reader). Holds + journal survive advance.
- RESIDENT ENGINE (apps/resident): the claude_agent_sdk loop over the proven plumbing. Jailed
  in-process MCP tools only (read_scene, read_journal, append_note, list_scenes w/ graceful 404),
  tools=[] so no host reach, session resume, tokeman rotation, interval turns + stdin conversation.
  "An empty turn is a valid turn."
- PORTFOLIO (crates/joshi-wallet-source, joshi-accounting): PortfolioStatementV1 as a pure
  derivation from durable wallet observations — every number with its derivation, price KIND and
  age labelled per the no-universal-price rule, DLMM position via meteora.rs, the unobservable
  resting limit order a NAMED absence. CLI against the real funds catalog; route+rail spec only
  (core/glass are sibling territory).

## Plus THE PUMP WAVE, 2026-08-22 17:25 — three Fable lanes back on the memecoining itself

- CALLOUT SCIENCE (pump-api, pump-adapter, analysis/): compose a callout population (no global feed
  exists — discovery sweeps x callout_top x callout_by_user fan-out), outcome census with the
  multiple=1 floor as its own bin, caller-signal check (port-and-reverify joshibot's
  quality_callers, not first contact), and THE ENTRY-WINDOW MEASUREMENT: seek the trades tape to
  each callout's createdAt and measure the first 30-60 min — is there usually a decent-magnitude
  dip or variance worth entering after? Ember's own loop, measured at last. Occurrence-vs-
  availability confound stated on every result. <=300 requests.
- LIVE TAPE (joshi-sources/examples/coin_tape_live.rs only): review the mid-write recorder
  honestly, record a real hot mint under sane machine load, frame anatomy + tape-vs-swap-api
  cross-validation (cheapest two-source check JOSHI has ever had), and the live event-resolution
  vs one-minute-candle drawdown verdict. Keeper-adoption seam spec'd, not built.
- PAPER DESK (joshi-liquidity, market-math, one new example): the year-old ask — papertrading her
  actual hypotheses LIVE. PaperEpisodeV1: hypothesis verbatim, declared rules executed without
  cleverness, would-quotes from M0's to-the-atom arithmetic carrying state age and fee tier,
  would-PnL NAMED AS ARITHMETIC with the unmodeled-risk list structurally adjacent (landing,
  failure, competition — unknowable from our data and said so). Unable to lie by construction.
  Evidence seam into the journal spec'd, not built.

Territory: two lanes share joshi-sources/examples on DISJOINT files, named in both briefs.

Seams named in the briefs: keeper is sole writer of its catalog dir; living-scene watches it
read-only; resident degrades gracefully if the feed route is absent; portfolio specs its surface
rather than colliding in service.rs. Primary integrates and commits as they land.

- COCKPIT WIRING (apps/core, apps/glass, joshi-liquidity): connect the hold gesture to the pre-trade
  readout so a held coin shows fee floor + break-even clip interval, plus tier proximity.
- LIVE CLOCK (joshi-pump-api, joshi-pump-adapter, joshi-sources): the sequel both studies ended at.
  Callout capture gives the t=0 that aligns coins; SubscribeTokenTrade gives the per-coin EVENT tape.
  The decisive question: can a live event-resolution tape see the dip that candles miss? The corpus
  says the gap is enormous (57.7% of no-drawdown-on-candles coins had one at event resolution);
  verifying it live on bytes we retained ourselves is the difference between a finding about a
  BigQuery export and a finding about the instrument Ember would actually use.

## Superseded thrust, 2026-08-22 01:15

Two deputies live:
- COHORT GEOMETRY (analysis/): align every mint on first observed trade, characterize first
  hour/day/week, decompose "goes to zero" into an outcome vocabulary with right-censoring stated,
  candles as a control against flow, and only then ask whether anything is predictive against a real
  baseline with a TIME-based holdout. Gated by the corpus's own "Promotion questions before ML".
- COCKPIT WIRING (apps/core, apps/glass, joshi-liquidity): connect the hold gesture to the pre-trade
  readout so a held coin shows its fee floor and break-even clip INTERVAL, plus new tier-proximity
  (which fee row the market cap selects and how far to the next). This closes the loop between the
  two lanes that landed tonight and have never met.

## THE ANSWER TO EMBER'S DIP QUESTION, 2026-08-22 01:30

**Of 113,859 mints whose MINUTE CANDLES SHOW NO DRAWDOWN AT ALL, 57.7% had one at event
resolution.** Median event drawdown 0.182 log (~ -16.7%); median candle drawdown exactly ZERO.
**That is the dip she watches for, and the chart she would be looking at does not render it.**

And there is usually no chart at all: **77.1% of the cohort has <=3 candles in its entire first
hour** (median 2). For most coins in the window that matters, a candle view is not thin — it is
absent.

CANDLES ARE A RELABELLING OF FLOW, measured not assumed: slope of log-price on log-reserve is
EXACTLY -2.0 with r^2 EXACTLY 1.0 over 21M events; signed flow telescopes into reserve displacement
on 99.89% of mints; corr(log return, reserve displacement) = 1.0 to twelve decimals. Spearman
0.9963 / 0.99996 / **1.000000** for the three candle features against their flow counterparts, with
identical single-feature AUCs to four decimals. My prior was right and is now a measurement.

## What a coin's life looks like (226,760 standard-supply curve mints, aligned on BIRTH)

- Intensity decays as **t^-1.35, r^2 = 0.996**, 30s to 12h — an aftershock shape over four orders of
  magnitude inside a day.
- **80% of every account a coin will ever touch in 24h has touched it by minute 5.**
- Survival: 80.5% @1s, 63.4% @1min, 36.8% @5min, 20.7% @1h, 8.0% @24h, 1.2% @6d.
  **Nearly one in five is finished within a second of creation.**
- Death threshold EARNED from a measured resurrection hazard: a 1h silence resolves into a further
  trade 31% of the time (a pause); a 24h silence 6.1%.
- **"Goes to zero" is mechanical here**: the launch price is a hard floor pre-migration and 83.4% of
  coins end with >=99.9% of supply back on the curve — every token bought was sold back. Of mints
  that ever sold >=0.1% of supply, 80.4% came all the way back, median 48 seconds.

## Predictive: yes, but the strongest predictor is arithmetic

At 5 min, coins with NOTHING OUTSTANDING are alive at 1h 2.6% of the time vs 61.4% with tokens
outstanding — AUC 0.889, and it is an accounting identity (a coin nobody holds cannot produce a
sell, and a sell is the event predicted). Flow structure adds +0.055 AUC over that state
(0.873->0.928); **adding candles to flow NEVER helps on any target.** Most of what is knowable is
knowable in the first minute (60s 0.844 / 300s 0.888 / 1800s 0.921).

Held out by birth day with a buffer; negative control returns chance. **Not tradeable and nothing
has an action attached**, because this corpus structurally cannot score cost, failure, capacity or
residual inventory — every fill in it landed.

## The deputy's push-back that points at tonight's other lane

**"Ember's current policy is not a baseline and cannot be, because there is no record of which coins
she looked at."** Capturing what was on screen and when is worth more than further modelling on
these bytes. That is exactly what the hold gesture committed tonight begins to capture.

## AUTHENTICATED ACCESS UNLOCKED, 2026-08-22 — driven with Ember's own wallet

pump.fun uses Sign-In-With-Solana: sign the literal string "Sign in to pump.fun: {ms-timestamp}"
with the wallet's ed25519 key, base58 the signature, POST {address,signature,timestamp} to
frontend-api-v3/auth/login, receive a 30-day auth_token cookie. Verified working from the shitcoims
wallet: userId 37869d39... It is an AUTHENTICATION signature, not a transaction — nothing on-chain,
no spend. The exact format was found empirically: bare timestamp -> 401, the colon-space prefix -> 200.

UNLOCKS the global callout leaderboard (401 to anonymous): top callers each with topCallouts
(coinMint, calloutPrice, multiple, createdAt, maxPriceSol, thesis, wallets). Top-8 best multiples
seen: 41.5, 50, 235.4, 61.4, 120.2, 56, 86.8, 371.8. The fan-out ROOT the callout-science lane was
approximating.

TRUST POSTURE, deliberately separate: JOSHI now acts AS Ember's account, distinct from anonymous
product reads. The companion extension keeps its no-auth-material boundary. Authenticated access is
its own gated lane: a SIWS session provider in joshi-pump-api, token + wallet key treated like the
Helius credential (0600, never rendered/logged/committed), READ-ONLY routes only. HARD RULE: the key
signs ONLY the login timestamp, never a transaction. Routed to the callout-science deputy to build +
explore the authed surface honestly. Token never committed; a live one sits 0600 in scratchpad only.

## Done log

- 2026-08-22 05:55 CALLOUT OUTCOMES FETCHED LIVE, and they are directly usable. `callout_top/{mint}`
  returns per callout: `createdAt`, `peakTimestamp`, `calloutPrice`, `maxPriceSol`, `multiple`,
  `marketCap`, and **`thesis` — the caller's own words**. Two real callouts read tonight:
  multiple 4.5 with 11.36 h to peak, and multiple 1 with no peak yet.
  - **`multiple` reconciles with maxPriceSol/calloutPrice** (4.5 vs 4.548). The provider's headline
    number is derivable from its own fields, so it can be CHECKED rather than trusted. Do that at
    scale before relying on it.
  - **`multiple = 1` with the two prices equal is a FLOOR, not an unknown** — it means the coin never
    exceeded its callout price. Treating it as missing would silently drop every failed callout,
    which is exactly the survivorship error this project keeps finding.
  - `peakTimestamp = null` genuinely is unknown-so-far and must not be read as "no peak".
  - `/callout/list/{user}` is keyed by USER, not mint. That resolves the "unexplained empty array"
    from the discovery lane: it was called with a mint where a user id belongs. Not a provider
    oddity — a parameter mismatch.
  - Caveat: 2 callouts on 1 mint. This is the instrument working, not a result.

- 2026-08-22 05:11 CALLOUT CLOCK FOUND. Salvaged from a lane that stalled mid-write. The callout
  routes carry `createdAt` (the t=0 that aligns coins), plus `peakTimestamp` on callout_top and
  `maxMultiplier` + `maxMultiplierAt` on callout_by_user. **The provider already states, per callout,
  when it was made, how far the coin ran, and how long that took.** The entry-window study is one
  route away rather than a corpus rebuild. NOT answered and must not be assumed: an availability
  time — a callout is a clean origin only if we know both when it happened and when it became
  visible, and nothing states the second. Also discovered `callout_by_user`, which was not in the
  catalog.
- 2026-08-22 04:00 COCKPIT WIRING + LIVE CAPTURE. A held coin now shows fee floor, break-even clip
  INTERVAL, and which fee tier row its market cap selects with distance to the next. Route is
  per-mint deliberately: a scene is what the feed carried at one commit, a readout is what an
  account read said at one slot. I added `--write-capture` to the live driver and exercised it
  against a real pool at finalized slot 440866559, so the route serves live numbers not a fixture.
  THIRD INSTANCE of one gap: a JSON-RPC account response is POSITIONAL and names no address, like
  the candle window that names no coin and the curve account that names no mint. The capture carries
  what the body cannot state and renders the address list as a DECLARATION BY THE READER.
- 2026-08-22 02:00 Operator runbook rewritten against what actually runs (five new tools tonight).

## Known-not-real: Glass test failures under load

The Glass suite reports 1, 4 or 10 failures depending on the run, every one timing out at a uniform
~7100-7400 ms, including pure logic tests that should be instant. `MarketChart.test.tsx` passes 7/7
in isolation and the text it could not find exists at MarketChart.tsx:234. **Machine load average
was 77 / 94 / 70.** These are contention timeouts, not defects. Re-verify on a quiet machine before
believing any Glass failure tonight. Rust gates are unaffected (103 pump, 41 liquidity, 157 sources).

- 2026-08-22 01:08 VENUE DECODER + PRE-TRADE READOUT, 207 tests (was 179), workspace clippy clean.
  The 119 bps overstatement is fixed and independently reproduced from retained bytes. Offset-245
  named `unattributed_quote_side_reserve_atoms` after a 42-pool survey found the SAME value on 29 of
  them — a protocol-wide constant, not per-pool state, consistent with a virtual reserve and not
  proof of one. Byte 244 was the identical bug forming again (0 on 37 pools, 1 on 5). Bonding curves
  are NOT fixed length (49/115/150/151/256 bytes across 96 curves) so the old decoder would have
  refused most of the market. Fee-config addresses are now RECOMPUTED as PDAs rather than carried as
  observed values, which matters because a bonding curve account never names its mint. Global is
  refused as a fee source with the shortfall named (declares creator 5, program applies 30).

- 2026-08-22 00:39 SIGNATURE REGIMES, two negative results and one that matters.
  (a) The signature slope does NOT separate worked coins from quiet ones (median 1.245 vs 1.095,
      rising 25/40 vs 20/36). Partly a badly posed test on my part: the bands are defined by
      AMPLITUDE and sigma^2 normalises amplitude out by construction. It measures shape, and was
      never the instrument for tradeability.
  (b) NO DISCRETE DYNAMIC REGIMES on this axis. Continuous spread, 24% reverting / 34% flat / 42%
      trending, largest gaps all in the sparse tail above 2.8 rather than between modes. One
      statistic cannot refute a multi-dimensional taxonomy, so this is evidence against types being
      visible HERE, not against types.
  (c) THE FINDING THAT MATTERS: the spread is large and real. Same market, same window, some coins
      mean-revert strongly and others trend strongly. **A dip-and-recover rule is wrong on ~42% of
      coins; a momentum rule is wrong on ~24%.** Ember's correction — that a crackle is not only
      dip-then-recover — shows up in the data as two large populations rather than one shape with
      exceptions. Direction-agnostic extraction is structural, not stylistic.
  Scope: graduated AMM pools only; the curve carries 79% of qualifying half-hours and is excluded
  because its price object is a model, and M0 found pools carry ~50x the tradeable clip anyway.

- 2026-08-22 00:34 ROW-PROJECTION GATE + CANDIDATE FINDER, 100 tests (69 at start of night).
  All three discovery routes now promote, live, on fresh bodies whose document fingerprints had
  already drifted while the row gate correctly held.
  - My gate spec needed one correction, made after three live pages refused within minutes: v1
    required every leaf seen on every row of 1,308 rows, which included leaves the crate never
    reads. All three refusals were genuine catches (a coin with NO metadata at all, a nested
    mayhem/complete_reason nobody had read, a search row for a coin that has NEVER traded) but
    requiring an unread field protects nothing and costs a refusal on every rare row — "which is how
    a fail-closed gate becomes noise a tired reader waves through". Required is now exactly the
    projection the code reads, and a review requiring more is itself refused.
  - It added a rule I did not ask for and should have: AN EMPTY PAGE REFUSES. Every per-row check
    passes vacuously over zero rows, and this provider answers past-the-end with a bare [] identical
    to matched-nothing, so promoting it would certify a row shape from no rows.
  - THE DEPUTY CAUGHT ITS OWN FABRICATION: it had reported no-term search pages returning
    volume_1h_usd "of exactly 0". They carry NO volume key at all — the zero was its own readout
    defaulting an absent field. It corrected the catalog, the review rationales, and made the field
    optional rather than required.
  - Carrying BOTH market caps with tags naming each other paid immediately: a coin surfaced whose two
    provider values disagree by NINE PERCENTAGE POINTS, not the 0.31% of the census. Visible only
    because neither was picked.
  - CANDIDATE FINDER LIVE: 92-second window, 159 -> 153 mints, 58 in both. Top of slate
    **+274%, -96%, +63%, +40%, -27% over ~92 seconds.** 11 of 58 carried measured volume; the other
    47 say "the flow sweep's terms did not reach this mint; this is not a volume of zero".

- 2026-08-22 00:55 CORPUS READ AND CENSUSED. 106,639,238 rows / 449,723 mints / 2.5M owners /
  220,475,360 signed balance changes, queryable in 30-50ms per mint over 107M rows.
  **THE HUNTING GROUND IS DENSE: 174,192 mints (38.7% of corpus, 54.9% of those that traded) had at
  least one half-hour with >=4 trades and >=8% unsigned range. ~34,000 qualifying half-hours/day,
  ~23,000 with >=10 SOL.** Robust across 27 configs (153,430-186,156). My independent re-derivation
  with different tiling: 176,284 mints, 36,730/day.
  - REPEAT RATE, conditioned on span (raw counts are misleading because most coins live <30min):
    series alive >3 days average 151.9 workable half-hours of which 51.9 qualify; 71.1% of them have
    >=10 qualifying. So Ember's harvest question is descriptively YES and **the binding constraint is
    attention, not supply**.
  - **Ember's 8-20% band is only 18.0% of workable half-hours; >20% moves are 42.6%; median workable
    half-hour ranges 13.7%. Her band describes her exit discipline, not the market.** Do not hard-code it.
  - `err` is empty on ALL 106M rows and structurally cannot be otherwise: extraction keeps only
    transactions where a pump-mint balance CHANGED, and a revert rolls balances back. No attempt /
    landing / adverse-selection study is possible on these bytes; that needs a re-pull, not a flag.
  - Selection is `mint LIKE '%pump'` — a vanity CONVENTION. High precision, UNMEASURED RECALL.
  - Native SOL lamports are not carried, so curve trades have NO observed SOL amount.
    sol_leg_lamports_exact stays NULL and a separately-named model column carries the readout.
    Nothing coalesces them and that separation must survive every downstream join.
  - Curve model validated against pump.fun's OWN reserves from an independent joshibot boards tape:
    99.23% exact to better than 1e-6, median relative error 4.8e-9.
  - Caveats that must travel with the census: last-trade mark is not an executable quote (8% range
    is not 8% of edge); max/min in a tile is an ORACLE BOUND assuming you turn at the extremes;
    79% of qualifying half-hours rest on the curve model rather than observed SOL.

- 2026-08-21 23:47 DISCOVERY MEASURED, 81 tests green. Headline: two 5-page sweeps of
  /coins?sort=last_trade_timestamp 97 SECONDS apart, joined on mint -> 64 of ~200 mints persisted
  (the persisting third is approximately "coins with continuous flow"), and **10 of those moved
  >=8%, 5 moved >=20%, inside 97 seconds**. That is exactly Ember's crackle magnitude, in a feed we
  can poll. Snapshot differencing is the candidate finder.
  - /callout/recent is a PHANTOM: 400 "Validation failed (uuid is expected)" because /callout/{uuid}
    catches it. Catalogued for 3 days as a real global feed. Refutation retained as a fixture.
  - The trust gate CANNOT promote any listing route: schema_fingerprint collapses array elements, so
    a fingerprint is the union of key sets of whichever coins landed in the page. 11 reads -> 8
    fingerprints. All three routes quarantined by named refusal. Decision made: replace with a
    per-row required-leaf + closed-optional-leaf gate (narrows, does not widen). Deputy implementing.
  - Fields silently dropped from FOUR coin routes including one already promoted: ath_market_cap
    (only within-lifetime peak) and volume_1h_usd (only realised-flow number in the catalog).
  - updated_at is epoch SECONDS while its siblings are MILLISECONDS -> reads as January 1970.
  - market_cap_usd vs usd_market_cap disagree up to 0.31%; neither preferred.
  - Reserves go STALE on graduation: a bonded coin kept launch-constant virtual_sol_reserves while
    its market cap fell 97%. Price cannot be derived from reserves post-bonding. Flagged to M0.
  - /coins/search-unrestricted is a live-volume leaderboard wearing a search route's name: rows
    strictly descending by volume_1h_usd on every page tested.

- 2026-08-21 23:43 P2 signature instrument landed (analysis/src/joshi_analysis/signature.py, 5
  tests, 181 analysis tests green). First microstructure statistic JOSHI has computed from its own
  durably retained provider bytes. On the retained 200-bar window: event-time signature falls
  monotonically 2.30 -> 0.52 (pure mean reversion) while wall-time signature RISES to a hump at ~5s
  (0.089 -> 0.246) then falls to 0.033. Same bytes, opposite reading at short lags, because gap
  compression makes an index step "one traded interval" and an elapsed step "one interval of wall
  clock including silence". Positive serial dependence inside a burst, reversion across bursts =
  stylized fact E2 visible in our own data. Caveat: one coin, one window, 45-78 pairs at short wall
  lags. The instrument works; this is not yet a result about the market.

- 2026-08-21 23:07 committed the three deputy lanes: pump tap measured (candles is a bare array, the
  normalizer had been silently returning 0 rows of 1000; `before` is inert; trades cursor is a
  seekable keyset), ORBITFAN's fabricated 15-number dossier removed from the live cockpit, contract
  widened so absence is expressible (realizedNetSol nullable -> "Not reconciled").
- Gate at that commit: fmt clean, workspace clippy -D warnings 0, Rust 228 tests across 7 crates,
  Glass 191 tests / 28 files, typecheck clean.
