# Wave 6 fixture-foundation witness

Status: **PASS for the exact N00 program/schema/evaluation-content restart witness; not a Wave 6 operational
readiness claim.**

[`scripts/wave6-foundation-readiness`](../../../scripts/wave6-foundation-readiness) is the first
root runner for the Wave 6 foundation. It runs:

- all schema migrations and the V4-to-V13 upgrade check;
- the exact `joshi-wave6-registry` suite;
- the store's Wave 6 program/schema/artifact-content tests;
- the Core program/schema/artifact-content restart test; and
- two invocations of the real `wave6-program-registration` command over the same V13 catalog.

The second invocation must reproduce the original program, six schema and three evaluation-content
commit identities. The script emits `joshi.wave6.fixture_foundation_witness.v2` with the exact
report and V11-V13 migration digests.

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
- `exact_fixture_schema_catalog_restart`; and
- `exact_fixture_artifact_content_restart`.

The witness structurally fixes all of these to false: Wave 5 gate resolution, operational release,
artifact occurrence, empirical claim, provider I/O, external mutation, product qualification and
live qualification. It does not run or summarize the Wave 6 analysis prototypes and does not
convert their caller-fed outputs into empirical evidence. `artifactOccurrence` remains false:
the V13 rows have no information cutoff, production clock, parent topology or DAG digest.
