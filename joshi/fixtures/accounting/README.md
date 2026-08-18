# Accounting conformance vectors

These fixtures are language-neutral inputs and expected projections for
`joshi.accounting.v1`. They contain no wallet authority, live network data, or trade instruction.

Rules:

- Every atomic integer is a canonical unsigned decimal JSON string.
- Rational values are reduced `{ "numerator", "denominator" }` pairs with a positive denominator.
- Account effects are derived from the `before` and `after` finalized snapshots; classifications
  do not supply or override ledger deltas.
- Lot disposal always names its allocations. Array order is significant; no implementation may
  silently substitute FIFO, LIFO, or another policy.
- `basis_quality: "unknown"` never means zero basis.
- Episode inventory is attribution over ledger truth. Going exactly flat may be followed by
  `continue_watching_flat`; re-entry then starts a new basis epoch inside the same episode.
- Committed files are readable JSON. Conformance runners serialize parsed values with RFC 8785 JCS
  when comparing canonical bytes; JSON object member order and whitespace in these source files are
  not semantic.

`arithmetic.json` exercises fixed-width and rounding boundaries. `state_machine.json` exercises
wallet-effect, lot, capital-recovery, and episode invariants. Expected values must be reviewed and
must not be regenerated from the implementation under test.

