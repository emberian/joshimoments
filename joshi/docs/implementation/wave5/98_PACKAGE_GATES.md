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
schemaVersion=5
status=useful_partial
circulationWalkDigest=sha256:739bfee212739ab908d60c837ef8bed11083824379eb2dc91f8ef15ddcea82fa
g0RootEvidenceDigest=sha256:27c8bb8592d59472d4fe9b20e0ad6877fb9e9adca7145bc9b6450dff372c302d
g0ComponentDigest=sha256:62ac50fe861be81d5d4b56970866cf35211a8c8b0861c40b54d01303868dd1f4
g0InspectorSmokeDigest=sha256:cd0b0dc11b8d1c32f17fe7534b4a522c59d2c072d841a7f67bfeef40393c231e
g0EvidenceBundleDigest=sha256:5fbd7c95238ddd7eff35dfb00c34751fc6f137829d517b5372dabc6dee4b10c3
g0SnapshotId=sha256:45130f5ec35a1b12776d823f33daace3f850d4ce4a150e8b4d4a53af4975f76e
catalogMigrationDigest=sha256:47a56fe77d690c26c94e5722a3e5c13070519eda4a780d9702f31669bc29e9df
g0CatalogMigrationDigest=sha256:92616764f786ba3eaf3f2da9c739c1f5ed36f9da1beb47416bd74e20cdf69c1b
attained=run_registered, public_c0_spool_catalog_closed, component_restart_readback,
         store_resolved_fixture_source, headed_cockpit_v2_publication,
         paired_fixture_api_reopen, censored_scientific_memory,
         nonempty_v10_export_import, v10_export_recovered,
         artifact_bearing_backup_restore, g0_component_30_prefix_recovery,
         g0_final_recovery_6_prefix_recovery,
         partial_root_18_role_evidence, final_distinct_root_store_origin_reopen
fullOfflineFaultWalk=false; boundedNonfixture=false; restartRecovered=false;
sustainedObserved=false; liveReadOnly=false; preliminaryEmberUse=false;
criticalSurfaceAccessibility=false; broadParity=false
claim=offline_run_registration_public_c0_and_partial_g0_root_evidence_only
```

The ignition detail (`ignition-readiness.json`) independently reports
`registrationDigest=sha256:7780d28bd1d1a1c6d36f19718eec58f518baed4ad5fde3f1331880bdbde83fcd`,
`acceptedCommitSeq=1`, `retryStatus=idempotent`, `changedSameIdRefused=true`,
`durableProgressCount=2`, `circulationClosed=true`, `originSegmentRetained=true`,
`catalogAckReverified=true`, `restartReverified=true`, and `providerIo=false`.

The same root invocation executes `wave5-g0-root-evidence`, which runs the component and actual
in-process pairing/open/restart smoke over the same catalog. It checks the component's
eight-occurrence censored-memory closure and nonempty V10 snapshot, exact-matches the registered
run/source/publication/head and route bytes, then reopens the store and supervisor origin from
distinct restored roots while their original paths are unavailable. It emits one eighteen-role
baseline evidence bundle whose final role binds that composite readback.
The same Core suite injects process loss immediately before and after composite backup, restore and
final reopen on six fresh catalogs; every exact retry recovers the same restored truth. These are
six scheduled final-boundary cases, not the complete 37-scenario result.
It refuses to emit the witness if the paired route changes bytes, accepts the prior capability,
substitutes the run or publication, raises a browser/product/live bit, or if any partial component
closure or negative qualification bit changes. This is a root-gate pass over an explicitly partial
offline baseline conjunction, not the 37-scenario W5-G0/product/live pass.

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
