# Implementation lane 04: analysis platform

Status: **Wave 1 offline workbench implemented and tested**.

Date: 2026-08-16.

This lane implements the minimal research spine proposed in
[`18_research_ml_environment.md`](../../research/engineering/18_research_ml_environment.md): a
locked Python job consumes one immutable manifested snapshot, refuses inputs that violate the
point-in-time contract, and publishes a content-addressed run bundle. It does not query or write the
operational store, call a provider or model service, access credentials, or expose any transaction
capability.

## Delivered boundary

The workbench lives entirely under `analysis/` and contains:

- a `pyproject.toml` and committed `uv.lock` for a Python 3.12+ environment;
- DuckDB for the explicit analytical query and PyArrow/Parquet for typed interchange and durable
  artifacts;
- a committed deterministic snapshot fixture with explicit coverage gaps;
- a fail-closed snapshot validator;
- a non-interactive `joshi-analysis` CLI;
- an example descriptive chart/episode feature job;
- deterministic, atomic run publication; and
- tests for integrity, schema, coverage, temporal availability, CLI behavior, immutability, and
  byte-for-byte reproduction.

Polars is deliberately absent. The first job needs SQL and Arrow interoperability, not another
dataframe engine; adding it would increase the locked dependency surface without adding a boundary
or capability. It can be introduced by a named study later. Notebooks are also absent for now. A
future notebook may read a named snapshot or run artifact, but it cannot be the canonical cohort,
feature, or result producer.

## Walking path

```text
manifest.json + manifested *.parquet relations (read-only snapshot)
                         |
                  strict validation
                         |
              in-memory DuckDB query
                         |
              exact-schema Arrow table
                         |
        temporary deterministic Parquet + manifest
                         |
                 atomic directory rename
                         |
   runs/run-<sha256>/{manifest.json,row_results.parquet}
```

Validation completes before DuckDB receives the table. The database connection is in-memory and is
closed after the query. The snapshot itself is never opened for writing. Only the caller-selected
artifact root is writable.

## Snapshot v1 contract

`joshi.analysis.snapshot/v1` was strengthened during the ML-ready exocortex lane to match the
cross-lane export contract. It now closes fourteen typed direct-child relations spanning scenes,
choice membership, candidates, territories, episodes, gestures, interviews, outcomes, coverage,
and provenance. The full current contract and migration rationale are in
[`11_ml_exocortex_foundation.md`](11_ml_exocortex_foundation.md).

The manifest binds:

- producer, projection, catalog commit range, and full as-of vector;
- the exact physical Parquet bytes with algorithm-qualified SHA-256;
- the Arrow schema descriptor and algorithm-qualified schema digest;
- a logical digest over the ordered typed relation;
- row count and table-specific primary key, including chart key
  `(scene_id, episode_id, sample_index)`;
- the global maximum decision-availability cut;
- exact counts of expected, observed, and explicit-gap rows plus scope/window/gap identities; and
- a self-hashed snapshot identifier over the canonical manifest preimage.

Every row records `event_time`, `observed_at`, `available_at`, and
`decision_available_at`. A valid as-known row must satisfy:

```text
event_time <= observed_at <= available_at <= decision_available_at
decision_available_at <= manifest.maximum_decision_available_at
```

This is stricter than filtering only on event time: an old event learned through a later backfill is
future information for an earlier decision. A test constructs such a row and fully rehashes both
the Parquet table and manifest; validation still rejects it at the temporal gate. The failure is
therefore not merely a checksum failure.

Coverage is represented, not imputed. An `observed` chart row requires a positive exact base/quote
atom ratio, nonnegative exact-integer volume atoms, and composite assertion/observation provenance.
A `gap` row requires null measurements, an `unknown` position state, and a durable gap ID. Each
scene/episode series contains every expected sample index, including explicit gaps. Unknown data
cannot silently disappear or become a zero.

The fixture remains intentionally tiny: four scenes, twenty expected chart samples, eighteen
observations, and two explicit gaps (`900000` ppm chart coverage). Empty optional relations are
also valid. `analysis/tools/build_fixture.py` builds the exact committed bytes and refuses to
overwrite an existing fixture; the test suite independently rebuilds every part and checks byte
identity.

## Descriptive example, not a strategy claim

The example query emits one row per scene under schema
`joshi.analysis.descriptive-chart-shape/v2`. It reports:

- expected, observed, and missing samples and coverage ppm;
- starting/ending exact base/quote atom pairs plus descriptive signed change, range, and maximum
  drawdown in integer ppm;
- an observed-step direction signature and direction-change count; and
- counts of samples marked exposed, flat-watch, and runner.

Each row and the run manifest carry the literal scope
`descriptive_only_not_predictive_or_strategy_claim`. These are path summaries useful for inspecting
whether episode plumbing preserves shape and position context. They are not a signal, fitted model,
backtest, causal estimate, PnL estimate, or recommendation. The query does not use any information
after the scene's decision-availability cut. Explicit gap counts accompany every summary; v1 does
not interpolate through gaps.

## Deterministic run bundle

`joshi.analysis.run/v1` records:

- snapshot ID and exact input manifest hash;
- job and feature versions plus SQL hash;
- package, Python, platform, DuckDB, and PyArrow versions;
- `uv.lock` and analysis source-tree hashes;
- output schema, physical hash, logical digest, row count, and primary key;
- a small deterministic coverage/result summary; and
- explicit declarations that the job needs no network and makes no operational-store writes.

Wall-clock time, temporary paths, and output-root paths are excluded from identity. The run ID is a
SHA-256 of the canonical manifest preimage. Rows are sorted by `(scene_id, episode_id)`; Parquet
writer options are fixed. A job writes into a temporary child directory and atomically renames it only after the
result and manifest are complete. Re-running the same job is idempotent if the existing bundle is
byte-identical and fails closed if the same run directory was mutated.

This provides byte reproduction on the pinned Wave 1 platform. The manifest also records platform
and runtime versions rather than pretending Parquet bytes are guaranteed identical across all
future architectures or library releases; logical hashes remain the semantic comparison boundary.

## Commands and observed gate

Run from `analysis/`:

```bash
uv sync --locked
uv run --locked joshi-analysis validate --snapshot fixtures/snapshot_v1
uv run --locked joshi-analysis run \
  --snapshot fixtures/snapshot_v1 \
  --output-root .artifacts/runs
uv run --locked pytest
uv run --locked ruff check .
```

The committed fixture validates as snapshot
`sha256:4528f461322d62ab19e2844ccca790a147cbc709f1329d851ff2acdb705d9718`. The example
job produces four row-level results. `.artifacts/` is ignored because generated run bundles are
derived outputs, not source.

The implemented test gate checks:

1. the fixture and exact coverage manifest validate;
2. physical Parquet tampering is rejected;
3. a self-consistent but future-known row is rejected;
4. snapshot self-hash tampering is rejected;
5. a rehashed but altered schema contract is rejected;
6. a rehashed but false coverage claim is rejected;
7. fixture reconstruction is byte-identical;
8. two independent job runs yield the same run ID, manifest bytes, and Parquet bytes;
9. the source snapshot remains byte-identical after a run;
10. same-root reruns are idempotent; and
11. the CLI validation and descriptive-job entry points execute successfully.

## Rust exporter integration

The Rust export lane should initially produce the exact v1 directory contract into a temporary
location, hash and validate it, and publish it immutably. The Python consumer should not open
SQLite or learn the operational schema. Integration should pass only a snapshot directory path.

Before substituting a Rust-produced fixture into the walking path, add a cross-language fixture
test that demonstrates:

- exact Arrow field names, order, nullability, and timestamp precision/timezone;
- exact integer monetary/volume units;
- composite assertion/observation provenance, scene/view identity, and corrected primary keys;
- explicit base/quote asset identity and exact atom units;
- explicit gap rows and matching coverage totals;
- both event-time and available-time semantics; and
- matching physical/schema/logical hashes as encoded in the snapshot manifest.

The Rust store must register the Python `snapshot_id` as its exact `export_snapshot_id` and prove
the installed manifest/part closure. If an exporter later needs partitioning, nested paths, or a
different schema, introduce a new manifest/schema version and validator. Do not loosen v1 parsing
until it happens to accept the new shape.

## Explicitly deferred

Wave 1 does not build model training, strategy evaluation, survival analysis, embeddings, feature
stores, model registries, online learning, GPU/cloud execution, LLM calls, notebook pipelines,
operational database readers, or product-visible scoring. Lane 11 has since added frozen
feature/label/dataset specs, temporal materialization, a non-predictive analog baseline, and future
prediction/evaluation artifact contracts; it still adds none of those deferred operational
capabilities. A five-sample fixture scene is a plumbing test, not a sufficient chart representation.
