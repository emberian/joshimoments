# Wave 5 package gates

Status: the root gate run was anchored at committed HEAD
`fb736acfc4f3f0f4295ae8b4d3d34c71b4247ef8`. The locked/offline workspace and root Wave 5
readiness gates pass. The resulting witnesses are deliberately
`useful_partial`; they do not qualify live providers, sustained nonfixture supervision,
publication/product parity, product Glass use, retention, scientific, or economic capabilities.
The subsequent focused supplement at `2632bf1` passed all six paired-route prefix recoveries; it
does not alter the exact root witness below.

The root run includes the reviewed Wave 6 Python tree only as a package/test fact: 187 tests and
Ruff pass. It does not use those fixture-only analysis contracts to raise any Wave 5 or Wave 6
semantic ceiling. This lane changed only this gate document.

## Workspace enumeration

`cargo metadata --locked --offline --no-deps --format-version 1` reported 38 packages:

`joshi-collector`, `joshi-domain`, `joshi-spool`, `joshi-evidence`, `joshi-store`,
`joshi-artifact-admission`, `joshi-export`, `joshi-g0-harness`, `joshi-operational-status`,
`joshi-operator`,
`joshi-publication`, `joshi-projection`, `joshi-accounting`, `joshi-liquidity`, `joshi-market-math`,
`joshi-surface`, `joshi-supervisor`, `joshi-admission`, `joshi-pump-api`, `joshi-sources`,
`joshi-core`, `joshi-pump-adapter`, `joshi-acquisition-policy`, `joshi-attention`,
`joshi-census-bakeoff`, `joshi-episode-closure`, `joshi-epistemic-admission`, `joshi-epistemic-book`,
`joshi-market-state`, `joshi-mechanics-capability`, `joshi-operational-circulation`, `joshi-pairing`,
`joshi-retention`, `joshi-scientific-memory`, `joshi-source-registry`, `joshi-wallet-admission`,
`joshi-wallet-source`, and `joshi-wallet-topology`.

## Focused gate evidence

All commands used `--locked --offline` and covered this focused set:

`joshi-retention`, `joshi-sources`, `joshi-source-registry`, `joshi-surface`,
`joshi-operational-circulation`, `joshi-admission`, `joshi-supervisor`, `joshi-publication`,
`joshi-scientific-memory`, `joshi-episode-closure`, `joshi-export`, `joshi-epistemic-book`,
`joshi-operational-status`, `joshi-census-bakeoff`, and `joshi-mechanics-capability`.

| Gate | Result | Command / qualification |
| --- | --- | --- |
| Formatting | PASS | `cargo fmt --all -- --check`. |
| Workspace check | PASS | `cargo check --locked --offline --workspace --all-targets --all-features`. |
| Workspace tests | PASS (build/test fact) | `cargo test --locked --offline --workspace --all-targets --all-features`. |
| Focused Wave 5 tests | PASS (build/test fact) | 15-package `cargo test --locked --offline ... --all-targets`; all reported tests passed, including scientific-memory (15), surface (13), publication (16), supervisor (19), sources (43 + 4 golden), retention (9), store-linked restart/fault tests, and the six paired-route prefix recoveries. |
| Clippy | PASS | `cargo clippy --locked --offline --workspace --all-targets --all-features -- -D warnings`. |
| Rustdoc | PASS | `RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline --workspace --all-features --no-deps` generated 38 package docs. |
| Schema | PASS | `./schema/validate.sh`; all checks passed, including SQLite 3.53.2 validation (10 migrations, 13 commits, 6 observations, 7 assertions). |
| Glass | PASS | Root walk: 23 files / 157 tests; offline install, typecheck, and default build passed. The explicit G0 inspector build also passed separately. |
| Pump companion | PASS | Root walk: lint, typecheck, 8 files / 46 tests, mock replay, Chrome/Firefox builds, and manifest audit passed. |
| Analysis | PASS | `uv sync --frozen --offline --all-groups`, Ruff clean, `pytest`: 187 passed. |
| Root Wave 5 readiness | PASS, `useful_partial` | `./scripts/wave5-readiness` completed with the Wave 4 structural witness plus Wave 5 ignition, circulation, and partial G0 component witnesses; no live/provider I/O. |

The Wave 6 implementations and review docs are excluded from the Wave 5 qualification claim. No
production or manifest files were edited by this lane.

## Witness and exact claim ceiling

The fresh root run retained `/tmp/joshi-wave5-readiness.8C74IJ/wave5-witness.json` and exited
`RC:0`.
Wave 4 component witness:

```text
componentReadinessDigest=sha256:741bdd57f918e38006c62b88fcc9199b686210d56be014110bbfa073dc3469c7
catalogMigrationDigest=sha256:386c4ec473e0bf33408ac91c77aa46b8d3012cd0ec2f14d7c9acf0263d14d1c9
status=useful_partial
gates=workspaceOffline, schemaFreshAndUpgrade, glassOffline, companionOffline,
       analysisOffline, economicAuthorityDependencyAudit: passed
```

Wave 5 witness (`wave5-witness.json`):

```text
schemaVersion=4
status=useful_partial
circulationWalkDigest=sha256:739bfee212739ab908d60c837ef8bed11083824379eb2dc91f8ef15ddcea82fa
g0ComponentDigest=sha256:ae54f8118635426b9ab0340d1bf205b43a309a0190a2972607eabb47d84f7ad7
g0InspectorSmokeDigest=sha256:181ae942333d4a1bb1265a7c9b2739e5c30255db4fa8c9f3cfb5170325bba5d4
g0EvidenceBundleDigest=sha256:a34cacbaa187039468049d9ab7d2e8fcce0f477f8babe911e4d0007c2ace0141
g0SnapshotId=sha256:7c7da6ef291acc42f815109745f08a0efe06aeba8d62c69ff0bd1d2eab7ba214
catalogMigrationDigest=sha256:47a56fe77d690c26c94e5722a3e5c13070519eda4a780d9702f31669bc29e9df
g0CatalogMigrationDigest=sha256:92616764f786ba3eaf3f2da9c739c1f5ed36f9da1beb47416bd74e20cdf69c1b
attained=run_registered, public_c0_spool_catalog_closed, component_restart_readback,
         store_resolved_fixture_source, headed_cockpit_v2_publication,
         paired_fixture_api_reopen, censored_scientific_memory,
         nonempty_v10_export_import, v10_export_recovered,
         artifact_bearing_backup_restore, g0_component_30_prefix_recovery
fullOfflineFaultWalk=false; boundedNonfixture=false; restartRecovered=false;
sustainedObserved=false; liveReadOnly=false; preliminaryEmberUse=false;
criticalSurfaceAccessibility=false; broadParity=false
claim=offline_run_registration_public_c0_and_partial_g0_component_closure_only
```

The ignition detail (`ignition-readiness.json`) independently reports
`registrationDigest=sha256:7780d28bd1d1a1c6d36f19718eec58f518baed4ad5fde3f1331880bdbde83fcd`,
`acceptedCommitSeq=1`, `retryStatus=idempotent`, `changedSameIdRefused=true`,
`durableProgressCount=2`, `circulationClosed=true`, `originSegmentRetained=true`,
`catalogAckReverified=true`, `restartReverified=true`, and `providerIo=false`.

The same root invocation executes `wave5-g0-source-publication`, checks its fifteen-role evidence
bundle, the eight-occurrence censored-memory closure, and nonempty V10 snapshot identity. It then
executes the actual in-process pairing/open/restart smoke and binds its secret-free file digest. It
refuses to emit the witness if the paired route changes bytes, accepts the prior capability, raises
a browser/product/live bit, or if any partial component
closure or negative qualification bit changes. This is a root-gate pass over an explicitly partial
offline component, not a W5-G0/product/live pass.

There is no red package/root gate in this current run. The remaining blockers are semantic
qualification gates, not compile/test/tooling failures: no live provider I/O, no sustained
nonfixture witness, no production publication qualification, and no broad/product/accessibility
parity. The earlier transient stale-lock, format, and rustdoc failures are superseded by this
clean current-HEAD run and are retained only in prior historical review context.

## Semantic ceiling

Per `99_INTEGRATION_REVIEW.md`, passing package gates cannot promote any capability. Current
ceilings remain fixture/offline or explicitly unverified: C0 sealed source policy only, pure
retention and scientific-memory kernels, unverified surface/publication/status projections,
fixture/sample census and mechanics checks, and no live/nonfixture/restart/sustained claims.

No provider calls, secrets, remote deploys, or transactions were performed.
