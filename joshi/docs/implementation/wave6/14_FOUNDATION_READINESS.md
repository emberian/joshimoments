# Wave 6 fixture-foundation witness

Status: **PASS for the exact N00 program/schema restart witness; not a Wave 6 operational
readiness claim.**

[`scripts/wave6-foundation-readiness`](../../../scripts/wave6-foundation-readiness) is the first
root runner for the Wave 6 foundation. It runs:

- all schema migrations and the V4-to-V12 upgrade check;
- the exact `joshi-wave6-registry` suite;
- the store's Wave 6 program/schema tests;
- the Core program/schema restart test; and
- two invocations of the real `wave6-program-registration` command over the same V12 catalog.

The second invocation must reproduce the original program and six schema commit identities. The
script then emits `joshi.wave6.fixture_foundation_witness.v1` with the exact report and migration
digests.

Run it with:

```bash
./scripts/wave6-foundation-readiness
```

Or provide a deliberately scoped retained directory:

```bash
JOSHI_W6_STATE=/tmp/joshi-wave6-foundation.manual \
  ./scripts/wave6-foundation-readiness
```

The path guard rejects any state directory outside `/tmp/joshi-wave6-foundation.*`.

## Hard ceiling

The only attained capability names are:

- `exact_fixture_program_restart`; and
- `exact_fixture_schema_catalog_restart`.

The witness structurally fixes all of these to false: Wave 5 gate resolution, operational release,
artifact occurrence, empirical claim, provider I/O, external mutation, product qualification and
live qualification. It does not run or summarize the Wave 6 analysis prototypes and does not
convert their caller-fed outputs into store evidence.
