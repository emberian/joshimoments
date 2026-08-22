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

## Done log

- 2026-08-21 23:07 committed the three deputy lanes: pump tap measured (candles is a bare array, the
  normalizer had been silently returning 0 rows of 1000; `before` is inert; trades cursor is a
  seekable keyset), ORBITFAN's fabricated 15-number dossier removed from the live cockpit, contract
  widened so absence is expressible (realizedNetSol nullable -> "Not reconciled").
- Gate at that commit: fmt clean, workspace clippy -D warnings 0, Rust 228 tests across 7 crates,
  Glass 191 tests / 28 files, typecheck clean.
