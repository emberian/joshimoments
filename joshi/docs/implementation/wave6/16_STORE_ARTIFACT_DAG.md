# Wave 6 exact fixture artifact DAG

Status: **PASS for one durable exact fixture DAG over prior exact content; BLOCKED for empirical,
operational, product, causal or economic authority.**

Migration V14 adds `wave6_fixture_artifact_dag_v1` and its normalized member table. The sole store
accepts the checked `artifact_dag_v1.json` only after the exact N00 registration, six schemas and
all three V13 evaluation-content rows already exist.

## Exact closure

The adapter strictly parses the canonical DAG against the durable registration, resolves every
member ID, kind and content digest to a prior durable content row, and derives a stable DAG identity
from program identity plus semantic DAG digest. One maintenance transaction retains the exact
bytes, semantic and physical digests, aggregate fixture clocks, exact ordered members and fixed
fixture-only ceiling. SQL triggers recheck registration binding and require every member's content
commit to precede the DAG commit.

Readback reparses the exact bytes, recomputes the self and document digests, compares every scalar
and normalized member, then reloads each content object and rechecks its program, kind, digest and
strictly earlier commit. Exact retry returns the original commit. Missing content, changed member
content, invalid topology and a second batch for the same DAG refuse.

The frozen DAG has three parentless checked evaluation members, semantic digest
`sha256:54c1773c3c0c29a9663bb5ad53b2d9b203a9dc8a1c7723935cabed74bc65ce09`, maximum information
cutoff `2026-08-18T00:10:00.000000Z`, and maximum production time
`2026-08-18T00:32:00.000000Z`.

## Authority boundary

This is a real durable fixture occurrence, so the root witness reports
`fixtureArtifactDagOccurrence=true`. Its times and candidate contents remain declared checked
fixtures, not store-observed market facts, prospective outputs or released results. The same witness
keeps `empiricalArtifactOccurrence`, Wave 5 gate resolution, operational release, empirical claim,
provider I/O, external mutation, product qualification and live qualification false.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-store wave6 --lib
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
cargo test --locked --offline -p joshi-core wave6_registration --lib
./scripts/wave6-foundation-readiness
```
