# Wave 6 exact program persistence

Status: **PASS for durable exact N00 fixture registration; BLOCKED above
`unverified_semantic_fixture_only`.**

Migration V11 and `joshi-store` now provide the first sole-store Wave 6 spine. The adapter accepts
the exact canonical [`program_registration_v1.json`](../../../fixtures/wave6/program_registration_v1.json),
commits it once, and reparses and cross-checks it after read-only reopen.

## Closed contract

The V11 row retains:

- exact canonical registration bytes and byte length;
- the program, family, semantic-version and store-owned batch identities;
- the registration's self-digest and the physical document SHA-256;
- source-tree, build, environment and configuration digests;
- exact gate/artifact/symbol counts and bounded local budgets;
- fixture time, store commit sequence and store commit digest; and
- the fixed authority and `unverified_semantic_fixture_only` ceiling.

The SQLite trigger rechecks the exact JSON discriminators, counts, budgets and digests against the
stored columns and requires a nonbackdated maintenance commit. Update and delete are forbidden.
Rust readback strictly reparses the bytes and independently compares every retained scalar. Exact
retry returns the original store commit; changed bytes or a second batch for the same program
refuse.

The frozen fixture has:

```text
programId              w6-program-fixture-001
registrationDigest     sha256:d176471cc0796d302880711d30bc94069f484082896cdf4287abc2cfe0148e8f
documentDigest         sha256:f698341092e28d3e79ceac24fbe7dd332298d1996d0718a49cbbc5682037001f
consumedWave5Gates      0
providerUnits           0
externalMutationUnits   0
```

The program row is introduced by V11; the ordinary/latest store now migrates through the additive
V16 exact campaign-bundle table. V15 retains the fixture-decision ledger; V16 atomically retains
the five exact N03 campaign documents after resolving the prior program and campaign schema. The
Wave 5 G0 root path uses the explicit forward-only V10 migration boundary, so its frozen V10 export
contract does not silently change when Wave 6 tables exist.

Core exposes a bounded local witness:

```bash
cargo run --locked --offline -p joshi-core -- \
  wave6-program-registration --state /tmp/joshi-wave6-program
```

It creates or reopens one latest V19 catalog, commits the checked fixture, all six registered
schema documents, three exact evaluation outputs, their exact fixture DAG and three fixture
dispositions, plus the atomic five-document campaign bundle. It makes exact idempotent retries,
drops the writer, and independently loads the full chain through a read-only store. Its V6 JSON
report fixes
`status=fixture_only`, the unverified ceiling, zero consumed gates/provider units/external mutation
units, a false prospective-campaign-journal field, and false operational/empirical/product/live
fields. A repeated invocation returns the same original commit identities.

## Refusals and ceiling

This adapter does not accept or resolve a Wave 5 gate reference. It persists the checked fixture
DAG, fixture dispositions and one exact five-document campaign bundle, but not a prospective
campaign journal, human approval, observed outcome, score or nonfixture model output. It has no
provider, Glass, wallet, signing, submission, deployment or external-mutation path.

Consequently, the durable receipt proves only that the exact fixture contract was stored and
reopened. It does not make the program `store_resolved` in the operational sense and cannot raise
any Wave 6 result above the fixture-only ceiling.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
cargo test --locked --offline -p joshi-core \
  exact_source_and_publication_reopen_without_promoting_root_or_live --lib
cargo test --locked --offline -p joshi-core wave6_registration --lib
```

These gates cover V4-to-V19 upgrade, V9/V10 frozen migration boundaries, exact registration,
conflict refusal, idempotent retry, read-only reopen and continued V10 G0 isolation.
