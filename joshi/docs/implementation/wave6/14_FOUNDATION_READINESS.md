# Wave 6 fixture-foundation witness

Status: **PASS for the exact N00/N02 program/schema/evaluation-content/market-atlas-bytes/
fixture-DAG/decision/atomic-campaign-bundle/non-executable-proposal/caller-fed-disposition restart
witness; not a Wave 6 operational readiness, store-resolved market, or authenticated human-review
claim.**

[`scripts/wave6-foundation-readiness`](../../../scripts/wave6-foundation-readiness) is the first
root runner for the Wave 6 foundation. It runs:

- all schema migrations and the V4-to-V21 upgrade check;
- the exact `joshi-wave6-registry` and `joshi-wave6-campaign` suites;
- the store's Wave 6 program/schema/artifact-content/DAG/decision/campaign-bundle/proposal/review
  byte tests;
- the Core program/schema/artifact-content/DAG/decision/campaign-bundle/proposal/review byte restart
  test; and
- the focused Python market-atlas reducer/Ruff gates; and
- two invocations of the real `wave6-program-registration` command over the same V21 catalog.

The second invocation must reproduce the original program, six schemas, three evaluation-content
artifacts, the exact six-row market-atlas document, one fixture-DAG, one decision-ledger, one atomic
campaign-bundle, one proposal, and one caller-fed `hold` byte commit identities. The script emits
`joshi.wave6.fixture_foundation_witness.v9` with the exact report and V11-V21 migration digests. It
separately fixes store-resolved market authority, authenticated human review, approval/execution,
and result authority to false.

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
- `exact_fixture_market_atlas_bytes_restart`; and
- `exact_fixture_artifact_dag_restart`; and
- `exact_fixture_decision_ledger_restart`; and
- `exact_fixture_campaign_bundle_restart`.

The witness sets `fixtureMarketAtlasBytesOccurrence`, `fixtureArtifactDagOccurrence`,
`fixtureDispositionOccurrence`, and `fixtureCampaignBundleOccurrence` true. It explicitly fixes
`storeResolvedMarketAtlas` and `prospectiveCampaignJournal` false and also fixes all of these to
false: Wave 5 gate resolution, operational release, empirical artifact occurrence, human approval,
empirical claim, provider I/O, external mutation, product qualification, and live qualification.
It executes only the focused market-atlas fixture reducer; it does not convert caller-fed outputs,
fixture-declared clocks, fixture assignments, or dispositions into empirical evidence or operator
authority.
