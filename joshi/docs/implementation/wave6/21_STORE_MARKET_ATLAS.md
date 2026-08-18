# V19 market-atlas fixture persistence

Status: **PASS for exact sole-store byte/schema/restart closure at
`unverified_semantic_fixture_only`; no source, field-release, market, causal, strategy, product, or
execution claim.**

Migration `0019_wave6_market_atlas_fixture.sql` and `joshi-store::wave6_market` retain the exact
Python-produced/Rust-parsed six-stratum market-atlas fixture. The writer requires the prior N00
program registration and its exact registered `market_atlas_fixture` schema, then atomically stores
the canonical bytes and normalized closure columns under a store-owned commit.

The store reopens and reparses the exact bytes before returning either an accepted or idempotent
receipt. Readback independently checks:

- physical content digest and artifact semantic self-digest;
- atlas snapshot ID/digest and input snapshot ID/logical digest;
- the state, knowledge, and input-commit cut;
- the exact six-row denominator;
- the prior registered schema bytes/digest/commit; and
- fixed caller-fed authority, descriptive claim scope, and unverified semantic ceiling.

The migration also makes the program's `maxArtifacts` budget count both the earlier evaluation
contents and this dedicated market-atlas artifact. It remains one artifact per registered program
and kind. Unknown/noncanonical fields, changed closure, missing schema, a different batch, or
changed bytes refuse without replacing prior state.

The migration SHA-256 is
`sha256:1c5f3dfa8ff53de0ef83290994c64f89113f9db7cd0e0da438d4cae55589b6fd`.

## Boundary

The retained document is still caller-fed. A store commit proves that these exact bytes survived;
it does not prove that any source/event/version, coverage window, native payload, or cut came from
the Wave 5 field-release chain. It is not included in an operational artifact DAG, is not published
to Glass, and grants no empirical or economic authority. Any future store-resolved atlas must use a
new contract that joins exact source occurrences and release receipts rather than relabel this
fixture row.

## Verification

```text
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
```
