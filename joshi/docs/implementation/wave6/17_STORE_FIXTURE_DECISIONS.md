# Wave 6 exact fixture decision ledger

Status: **PASS for one durable append-only fixture disposition ledger over the exact prior DAG;
BLOCKED for human approval, operational release, empirical, product, live or economic authority.**

Migration V15 adds `wave6_fixture_decision_ledger_v1` plus normalized decision and evidence tables.
The sole store accepts the checked `decision_ledger_v1.json` only after its exact V14 DAG and every
referenced content object already exist.

## Exact closure

The store strictly parses the ledger against the durable registration and DAG. It derives a stable
ledger identity from program plus semantic ledger digest, retains the exact bytes, semantic and
physical digests, maximum fixture decision time and exact count, and stores each target,
predecessor, decision kind, reason and ordered evidence reference in the same maintenance
transaction. SQL triggers require the prior exact DAG and membership for every target and evidence
reference.

Readback reparses the registration, DAG and ledger, recomputes both digests, compares every scalar
and normalized decision/evidence row, and requires the DAG commit to precede the ledger commit.
Exact retry returns the original commit. Missing DAGs, target/content substitutions, invalid
branching or clocks and second-batch identity changes refuse.

The frozen ledger records three `promote_fixture_roundtrip` dispositions—one for each checked
evaluation content—with semantic digest
`sha256:9ed8f03224c75246e4ab34dee9cea8a939c4dc873faa8d7ff01afb0258813d09` and document digest
`sha256:d11988aeac754fdb2417147e9edbc06a775055f0cf07b389bd616b82587fd432`.

## Authority boundary

`promote_fixture_roundtrip` means only that deterministic fixture bytes survived their registered
contract and exact store restart. It is not a human approval, candidate selection, operational
release, empirical finding or permission to query, present, trade, sign, deploy or mutate anything.
The root witness therefore reports `fixtureDispositionOccurrence=true` while retaining
`humanApproval=false` and every empirical/operational/product/live qualification as false.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-wave6-registry --all-targets
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store -p joshi-core --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store -p joshi-core --no-deps
cargo test --locked --offline -p joshi-core wave6_registration --lib
./scripts/wave6-foundation-readiness
```
