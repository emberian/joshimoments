# Protocol conformance fixtures

All financial integers are canonical decimal strings. The fixtures deliberately separate:

- `mainnet_observation` vectors copied from finalized Solana account reads, with account identity,
  slot, layout/source revision, and exact observed fields; and
- `synthetic_boundary` vectors chosen to expose rounding, reserve, fee-component, and lifecycle
  boundaries without pretending the state occurred on chain.

The Rust tests consume these files as language-neutral vectors. Official SDKs and an independent
reference model should consume the same files in the conformance bakeoff. A source package version
or Git commit identifies an operation graph; it does not replace the state observation.

`pump_quotes.json` includes a finalized Pump curve reserve/mark observation. Its quote vectors use
explicit synthetic fee tables because the current source lane does not yet retain the chain fee
configuration closure needed to call them on-chain vectors. `dlmm.json` includes a finalized pool
and BinArray observation whose stored Q64.64 price is compared byte-for-byte with the calculator.

These fixtures authorize no network access or trading. Refreshes append a new identified vector;
they do not rewrite old expected results.
