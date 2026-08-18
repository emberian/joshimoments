# Wave 6 fixture-foundation witness

Status: **PASS for the exact N00/N02 program/schema/evaluation-content/fixture-DAG/decision/atomic
campaign-bundle/non-executable-proposal restart witness; not a Wave 6 operational readiness
claim.**

[`scripts/wave6-foundation-readiness`](../../../scripts/wave6-foundation-readiness) is the first
root runner for the Wave 6 foundation. It runs:

- all schema migrations and the V4-to-V17 upgrade check;
- the exact `joshi-wave6-registry` and `joshi-wave6-campaign` suites;
- the store's Wave 6 program/schema/artifact-content/DAG/decision/campaign-bundle/proposal tests;
- the Core program/schema/artifact-content/DAG/decision/campaign-bundle/proposal restart test; and
- two invocations of the real `wave6-program-registration` command over the same V17 catalog.

The second invocation must reproduce the original program, six schema, three evaluation-content,
one fixture-DAG, one decision-ledger, one atomic campaign-bundle, and one proposal commit
identities. The script emits `joshi.wave6.fixture_foundation_witness.v6` with the exact report and
V11-V17 migration digests.

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
- `exact_fixture_artifact_content_restart`; and
- `exact_fixture_artifact_dag_restart`; and
- `exact_fixture_decision_ledger_restart`; and
- `exact_fixture_campaign_bundle_restart`.

The witness sets only `fixtureArtifactDagOccurrence`, `fixtureDispositionOccurrence` and
`fixtureCampaignBundleOccurrence` true. It explicitly fixes `prospectiveCampaignJournal` false and
also fixes all of these to false: Wave 5 gate resolution, operational release, empirical artifact
occurrence, human approval, empirical claim, provider I/O, external mutation, product qualification
and live qualification. It does not run or summarize the Wave 6 analysis prototypes and does not
convert their caller-fed outputs, fixture-declared clocks, fixture assignments or dispositions into
empirical evidence or operator authority.
