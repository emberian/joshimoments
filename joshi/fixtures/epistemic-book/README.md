# Epistemic-book contract fixtures

`spot-claim-definition.v1.json` is the canonical exact-byte vector checked by the Rust crate.
`invalid-unknown-field.v1.json` proves strict unknown-field refusal. The focused Rust tests also
derive adversarial vectors for authority widening, post-cutoff evidence, input-manifest
substitution, unregistered first-round forecasters, source-loss scoring, cross-occurrence
substitution, false support promotion, future-outcome support, and duplicated-lineage ensembles.
Durable commit/blindness tests intentionally do not self-mint receipts: promotion remains blocked
until the store integration can mint this crate's opaque capabilities.
