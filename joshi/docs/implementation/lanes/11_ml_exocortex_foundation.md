# Implementation lane 11: ML-ready exocortex foundation

Status: **offline semantic foundation implemented and tested; no trained model or strategy claim**.

Date: 2026-08-16.

## Outcome

The analysis workbench now carries the durable meanings needed to learn from Ember's attended slice
without prematurely turning those meanings into a model platform. It can:

1. validate a closed, point-in-time export containing witnessed scenes, exact choice universes,
   candidates, territories, episodes, operator gestures, interviews, outcomes, coverage, and
   provenance;
2. materialize a deterministic dataset whose row is one candidate in one witnessed operator
   decision;
3. preserve temporal train/embargo/validation partitions, feature missingness, competing risks,
   and right censoring;
4. retrieve earlier descriptive chart-shape analogs for validation episodes; and
5. validate a future model/ensemble prediction artifact, including uncertainty and calibration
   lineage, against the complete decision-level universe before producing decision-keyed evaluation
   rows.

This is not online learning, a signal generator, a backtest, a trading policy, or evidence that the
operator's intuitions have positive expected value. It is the substrate needed to ask those
questions without silently changing the denominator, leaking later knowledge, or treating absence
as a negative outcome.

## 1. Reconciled store-to-analysis export contract

Wave 1's first snapshot was internally reproducible but did not close the Rust store's source,
catalog, scene, or coverage lineage. The fixture and validator now implement the frozen
`ExportSnapshotManifestV1` shape in `INTEGRATION.md` section 7.2.

The top-level `joshi.analysis.snapshot/v1` manifest includes:

- producer build, projection name/version, and algorithm-qualified projection-state digest;
- catalog identity/schema and a closed decimal-string commit range;
- a full glass-style as-of vector with catalog cutoff, sorted source deliveries and scoped cursors,
  optional chain watermark, named projection deliveries/state digests, and render time;
- `as_known` knowledge mode and the maximum feature decision-availability time;
- an optional singular scene binding for a scene-specific export; and
- one exact manifest entry for every Parquet relation.

Every table entry carries its Rust/SQL `export_manifest_id`, schema identity and descriptor,
algorithm-qualified schema/physical/logical digests, byte and row counts, ordered primary key,
commit/event/chain bounds, and exact coverage scope/window/gap identifiers. External JSON always
uses `sha256:<64 lowercase hex>`; a storage adapter may strip the prefix only when writing a SQL
column whose physical contract is bare hex.

The manifest's `snapshot_id` is the SHA-256 identity of the canonical manifest preimage excluding
only `snapshot_id`. The Rust store's `export_snapshot.export_snapshot_id` and
`ExportSnapshotDraft.export_snapshot_id` must equal this value. This Python fixture proves the
consumer contract. Wave integration still requires one Rust-produced export whose installed part
files, registered export rows, manifest bytes, and Python validation all share those identities;
the Python process does not inspect SQLite and cannot independently prove a store registration that
has not been exported.

The validator rejects:

- oversized, invalid UTF-8, duplicate-key, unknown-key, or noncanonical manifests;
- unsafe, nested, escaping, missing, or symlinked part paths;
- self-hash, physical-byte, byte-length, schema, logical-relation, or row-count disagreement;
- duplicate primary keys, false commit/event bounds, or false coverage totals;
- source cursor or projection watermarks beyond the catalog cutoff;
- a producer projection not closed by the as-of vector;
- unresolved scene/decision/choice/candidate/territory/episode/coverage/provenance references;
- an event, observation, assertion, membership, gesture, or chart value unavailable at its feature
  cutoff; and
- manufactured measurements, provenance, position state, or no-event labels in a known gap.

Manifest files are bounded to 16 MiB before reading. JSON duplicate keys are rejected during parse,
before self-hash validation, so parser ambiguity cannot hide behind an otherwise valid digest.

### Provenance is a relation, not a row ID

`source_assertion_id` is not globally unique. An assertion may be supported by multiple observation
occurrences and may legitimately support multiple projected samples. Evidence joins therefore use
the composite `(source_assertion_id, source_observation_id)`. The validator accepts repeated
assertions with distinct observations and rejects an observed row that supplies only a plausible
assertion with the wrong occurrence.

### Empty optional relations stay empty

The schema closure always includes social assertions, interviews, outcomes, and gaps, but any may
have zero rows. A zero-row relation has zero expected/observed/gap counts and a null coverage ratio,
not fabricated examples or a misleading one-million-ppm completeness claim. A tested snapshot with
no social assertions, interviews, or outcomes remains valid.

## 2. Snapshot relations and their authority

The deterministic fixture contains fourteen typed Parquet relations:

| Relation | Unit and authority |
| --- | --- |
| `scenes` | witnessed renderer scene, mode, exact view digest, knowledge commit, and decision cut |
| `territories` | versioned attention/ecology territory identity, not an inferred immutable class |
| `candidates` | candidate and canonical mint-asset identity joined to its current fixture territory |
| `candidate_social_assertions` | social identity claim with event, observation, availability, and commit clocks |
| `decisions` | one operator decision context, selected candidate if any, and resulting episode link |
| `choice_members` | exact eligible witnessed universe with rank/render/viewport/interaction state |
| `episodes` | exposure/attention episode with disposition and optional re-entry predecessor |
| `chart_samples` | exact base/quote atom ratio, volume atoms, position state, and explicit sample gaps |
| `operator_gestures` | witnessed semantic gesture bound to scene/view bytes and availability clocks |
| `operator_interviews` | structured debrief supervision with prompt/transcript identity and outcome visibility |
| `outcomes` | selected decision-candidate competing-risk event or explicit right censoring |
| `provenance_assertions` | composite assertion/observation evidence closure and value digest |
| `coverage_windows` | named expected observation scope and half-open acquisition window |
| `coverage_gaps` | durable gap identity, classification, detection, and recovery knowledge |

The general chart primary key is `(scene_id, episode_id, sample_index)`. Scene mode and view digest
are repeated and reconciled to the exact stored scene. Price is not an unlabeled
`price_microunits`: every observed sample names base and quote asset IDs plus exact base and quote
atom quantities. Volume uses Arrow `decimal128(20,0)`, which covers the full unsigned 64-bit atom
range without float conversion. Descriptive ppm features may use floating arithmetic after these
exact inputs are frozen; financial, quote, fee, manifest, or accounting truth may not.

An observed chart row requires its exact evidence pair. A gap row has null price/volume, unknown
position state, no invented source assertion, and a non-null durable gap ID joined to its coverage
window and scope. Each series represents every expected sample index, including gaps.

## 3. Feature, label, and dataset specifications

Three closed JSON specifications under `analysis/specs/` are inputs to materialization, not comments
about code:

- `feature:decision-context-chart-shape/v1` fixes the entity to a decision candidate, the feature
  cutoff to `decision_available_at`, the initial feature families, explicit missingness states, and
  prohibited post-cut sources;
- `label:crackle-competing-risk-20m/v1` fixes the at-risk unit to the selected decision candidate,
  a twenty-minute horizon, three distinct event kinds, the label-observation cutoff, and the rule
  that right censoring is unknown rather than no event; and
- `dataset:operator-choice-scenes/v1` fixes the eligible choice-set denominator and disjoint
  train/embargo/validation calendar boundaries.

The loader rejects duplicate/unknown keys, mismatched spec references, weakened feature cutoff,
collapsed risk sets, changed censoring semantics, or overlapping/misordered temporal partitions.
Each materialized row and run manifest binds the semantic canonical digest and ID of all three
specifications.

The initial partition is intentionally a fixture proof rather than a scientific recommendation:

```text
decision time < 2026-08-15                     -> train
2026-08-15 through 2026-08-15 23:59:59.999999 -> excluded_embargo
2026-08-16 through 2026-08-16 23:59:59.999999 -> validation
```

Real studies need enough calendar history to choose rolling-origin folds, embargo duration, and
regime strata before looking at confirmatory outcomes. This tiny split merely demonstrates that a
later query cannot retrieve an embargo or validation row as a training analog.

## 4. Deterministic decision-candidate materialization

`joshi-analysis materialize` validates the entire snapshot, loads the three specs, and emits one
row for every eligible candidate in every witnessed decision. Rows retain:

- decision, choice-set, scene/view, candidate, territory, and optional episode identity;
- the exact per-decision universe digest, membership count, source rank, renderer ordinal,
  viewport, interaction, and operator-selection state;
- creator identity only if both wall availability and catalog commit were within the witnessed
  scene cut;
- descriptive chart status and features, with `observed`, `explicit_gap`, and `not_observed`
  distinguished;
- only gestures available by the decision cut;
- train/embargo/validation assignment;
- selected-candidate outcome as a named competing event, right-censored unknown, or not-yet-known;
  nonselected candidates are explicitly `not_selected_not_at_risk`; and
- feature/label/dataset spec lineage and input snapshot identity.

The output bundle is content-addressed, byte-reproducible on the pinned environment, written into a
temporary directory, and atomically published. Its manifest binds the source snapshot and as-of
vector, specs, dependency lock, source tree, exact Arrow schema, physical/logical artifact digests,
row count, primary key, and partition counts. The job has no network or operational-store write
path.

The fixture deliberately contains four changing universes:

```text
decision-001: candidate-a, candidate-b
decision-002: candidate-a, candidate-c, candidate-d
decision-003: candidate-b, candidate-c
decision-004: candidate-a, candidate-d, candidate-e
```

A row-wise classifier dataset could easily forget these denominators. This materialization keeps a
choice-set size and one common universe digest on every candidate row, and its validator requires
the represented set to close exactly.

## 5. Descriptive analog retrieval

`joshi-analysis retrieve-analogs` consumes a validated immutable dataset run. For each selected
validation episode with chart observations, it searches only selected training episodes whose
decision cutoff is strictly earlier. The initial deterministic distance is a transparent sum over
absolute descriptive ppm change/range/drawdown differences plus a direction-change term. It emits
the query and analog identities, rank, earlier cutoff, shape distance, territory match, and both
path signatures.

The output intentionally contains no outcome, score, probability, expected PnL, recommended action,
or policy field. Every row says `retrieval_only_not_prediction_or_strategy_claim`. This baseline
tests whether episode retrieval, temporal eligibility, artifact lineage, and shape plumbing work;
it does not test whether shape similarity predicts anything.

## 6. Future model/ensemble and evaluation contract

`joshi.analysis.decision-choice-prediction/v1` defines the artifact a future offline model must
produce. Every candidate score binds:

- model ID/version, optional ensemble ID, member count, and dataset ID;
- decision/candidate and exact witnessed universe digest;
- information cutoff equal to the decision cutoff;
- named score and uncertainty interval/level;
- calibration method plus content-addressed calibration artifact;
- explicit missing-feature policy; and
- the restricted offline model-output claim scope.

The evaluator rejects duplicated candidates, an incomplete or stale choice universe, a changed
universe digest, information after/before the registered decision cut, malformed uncertainty, an
unnamed calibration artifact, or an overstated claim scope. It emits one row per decision—not an
aggregate over isolated candidate rows—with candidate/prediction counts, selected candidate score
and rank, and the selected candidate's unmodified label state.

This means a censored decision remains `right_censored_unknown` with no event kind in evaluation.
`profit_target`, `drawdown_stop`, and `liquidity_exit` remain competing event types rather than one
binary “won” flag. No probability calibration claim is made by having fields for calibration; a
future job must produce a frozen calibration artifact and evaluation evidence.

## 7. Implemented counterexamples

The tests make four common invalid analyses concrete:

1. **Changing universe:** remove one candidate prediction from a witnessed decision and evaluation
   fails instead of silently scoring the remaining rows.
2. **Censoring:** the validation episode loses coverage before the horizon. It remains a
   right-censored unknown; it is never encoded as “did not profit.”
3. **Competing risks:** fixture outcomes include profit target, drawdown stop, and liquidity exit,
   and materialization preserves each name.
4. **Later social identity:** candidate D's creator event predates the validation decision, but the
   observation and availability occur afterward. Its decision-time identity feature remains null.

Additional adversarial tests cover future chart availability under fully rehashed input, physical
tampering, false schema/coverage claims, duplicate JSON keys, ambiguous provenance occurrence,
repeated assertion use, zero-row optional relations, deterministic fixture reconstruction,
idempotent publication, and source-snapshot immutability.

## 8. Commands and current offline gate

Run from `analysis/`:

```bash
uv sync --locked
uv run --locked joshi-analysis validate --snapshot fixtures/snapshot_v1
uv run --locked joshi-analysis materialize \
  --snapshot fixtures/snapshot_v1 \
  --dataset-spec specs/datasets/operator_choices_v1.json \
  --feature-spec specs/features/chart_shape_v1.json \
  --label-spec specs/labels/competing_risk_20m_v1.json \
  --output-root .artifacts/datasets
uv run --locked joshi-analysis retrieve-analogs \
  --dataset-run .artifacts/datasets/dataset-<digest> \
  --output-root .artifacts/analogs
uv run --locked pytest
uv run --locked ruff check .
```

The ordinary CLI/test path uses no provider credentials, model SDK, model service, vector database,
GPU, cloud resource, operational database, wallet material, transaction builder, signer, or
broadcast endpoint. `uv sync` may fetch locked packages during initial environment setup; the jobs
themselves are local-only once the environment exists.

## 9. Deliberately not built

Do not add a feature store, vector database, experiment server, model registry service, notebook
pipeline, online learner, streaming feature computation, LLM annotator, GPU/cloud runner, or model
serving endpoint yet. The current artifact manifests can grow into those studies without granting
them evidence or product authority.

The next justified additions are evidence-driven:

- a Rust-produced snapshot passed unchanged through Python validation;
- enough recorded decisions to estimate coverage and define rolling temporal folds;
- chart drawings encoded as versioned scene-coordinate annotations tied to exact view/chart data;
- interviews with prompt version, outcome-visibility status, and adjudication rather than a single
  retrospective “gut” label;
- matched choice-set and attention-policy metadata for selection-uplift studies;
- survival/competing-risk evaluation that handles time-varying exposure and censoring; and
- only then, registered analog encoders, multimodal chart/social representations, LLM annotations,
  program synthesis, or hybrid-system/circuit-abduction experiments.

Promotion remains a separate authority. A candidate first reproduces on frozen snapshots, then
passes temporal and regime holdouts, calibration/coverage checks, leakage audit, and decision-level
evaluation. Any operator-visible score creates a new attention-policy epoch. No artifact in this
lane is eligible for execution authority.
