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

## Done log

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
