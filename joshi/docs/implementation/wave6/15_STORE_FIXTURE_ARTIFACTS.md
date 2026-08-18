# Wave 6 exact fixture artifact content

Status: **PASS for durable exact evaluation bytes under their registered schemas; V14 separately
binds them as a fixture DAG; BLOCKED for an empirical claim or operational release.**

Migration V13 adds `wave6_fixture_artifact_content_v1`. The sole store accepts the three checked
generic, protocol and structural known-truth evaluation outputs only after their N00 program and
V12 schema rows exist.

## Exact closure

For every retained evaluation, the store:

1. resolves the exact prior program/kind/schema/digest row;
2. cross-parses the Python-generated canonical bytes with the independent Rust N01 contract;
3. revalidates fixed authority, source-fixture digest(s), exact 8/7/3 result denominator and
   semantic self-digest;
4. derives immutable artifact identity from program, kind and physical content digest;
5. commits exact bytes, semantic and physical digests, schema commit, result count and fixed
   fixture-only ceiling under a store-owned maintenance commit; and
6. reloads and reparses every field before returning a receipt.

The SQL trigger requires the exact prior registered schema, enforces the program's artifact-count
budget in the same transaction, and keeps the content table append-only. Exact retry returns the
original commit. Kind/schema substitution, changed bytes and a second batch for the same content
refuse.

## Deliberate content boundary

The V13 row is content persistence, not an `ArtifactOccurrenceV1`. The table intentionally carries no
information cutoff, production time, parent edges or DAG digest. It resolves no Wave 5 gate and
does not make the fixture candidate a market observation, estimator result, economic claim,
product capability or live release. The public ceiling remains
`unverified_semantic_fixture_only`.

Core's V6 registration report commits, exactly retries and read-only reopens all three artifacts
after the six schemas, then separately commits their exact V14 fixture DAG. The foundation witness
therefore distinguishes a true `fixtureArtifactDagOccurrence` from the still-false
`empiricalArtifactOccurrence` qualification.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-wave6-registry --all-targets
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
cargo test --locked --offline -p joshi-core wave6_registration --lib
./scripts/wave6-foundation-readiness
```
