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

## Done log

- 2026-08-21 23:07 committed the three deputy lanes: pump tap measured (candles is a bare array, the
  normalizer had been silently returning 0 rows of 1000; `before` is inert; trades cursor is a
  seekable keyset), ORBITFAN's fabricated 15-number dossier removed from the live cockpit, contract
  widened so absence is expressible (realizedNetSol nullable -> "Not reconciled").
- Gate at that commit: fmt clean, workspace clippy -D warnings 0, Rust 228 tests across 7 crates,
  Glass 191 tests / 28 files, typecheck clean.
