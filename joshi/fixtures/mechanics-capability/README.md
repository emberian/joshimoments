# Mechanics capability fixtures

These fixtures exercise the pure W5-C status semantics only. They are not source observations,
store receipts, provider parity evidence, fills, or terminal-closure witnesses. In particular,
`partial_profile.json` intentionally has a simulation and a refused size quote but no attempt,
fill, liquidation, or close row.

The exact constructor/adversarial tests live in
`crates/joshi-mechanics-capability/src/tests.rs`.
