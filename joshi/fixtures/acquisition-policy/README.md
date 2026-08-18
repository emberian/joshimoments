# Acquisition-policy fixtures

These are synthetic, offline fixtures for `joshi-acquisition-policy`.

- `deterministic_scope.json` contains four append-only intents over one exact independent-census
  denominator: a cold-labeled mint, a losing-labeled mint, a high-activity-labeled mint, and a
  model proposal. The labels are test-only adversarial metadata and never enter the reducer.
- `expected_summary.json` freezes the normal and overload decisions. Normal capacity retains the
  two most recently justified activating subjects. Denominator-only overload removes every hot
  desire while retaining the exact census membership/digest/count/coverage closure.

All exact integers in policy fixture wire contracts are decimal JSON strings. The separate
supervisor-reservation adapter test intentionally consumes the current supervisor's canonical
numeric reservation bytes, validates them, and converts generation/attempt ordinals to the policy
wire representation without changing their values.

The fixtures contain no provider credential, real wallet, endpoint, subscription, trade, or
profitability claim.
