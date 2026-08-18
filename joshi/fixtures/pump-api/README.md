# Pump API offline fixtures

All JSON in this directory is synthetic and contains no credential, cookie, wallet signature,
live social content, or provider key. The shapes are reduced from bounded observations and old
`joshibot` donor hypotheses; they are not represented as current provider documentation.

- `coins-v2.synthetic.json` tests exact numeric lexemes, including an integer above JavaScript's
  safe range and a noncanonical decimal spelling.
- `callout-recent.synthetic.json` separates contemporaneous callout fields from retrospective
  peak/multiple fields and preserves a keyset cursor.
- `discovery-page.synthetic.json` preserves rank/order and two equal-valued distinct rows.
- `schema-drift.synthetic.json` is intentionally outside the promoted schema.
- `schema-registry.v1.json` contains only reviewed synthetic fixture fingerprints.
- `request-coin-exact.synthetic.json` and `request-sol-price.synthetic.json` are request-contract
  examples. They do not make a network call by themselves.
- `parity-companion.synthetic.json` and `parity-direct.synthetic.json` are an exact-equality pair
  at the shared decoded-response-body comparison boundary.
- `direct-fetch-outcome.synthetic.json` closes exact direct ingress through the strict Pump
  adapter, spool batch/policy closure, and public store receipt without network access.
- `promotion-gate.synthetic.json` is an evaluator-only 20-pair/3-session/19-match synthetic
  golden; it is not real Pump promotion evidence.
- `promotion-not-run.v1.json` is the current typed operational absence: no route has undergone the
  required Ember-present authenticated run.

These fixtures may be used for parser, replay, and parity tests. They must never be upgraded into
a claim that an undocumented route is licensed, stable, complete, or production-ready.
