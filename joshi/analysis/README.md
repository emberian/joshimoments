# Joshi analysis workbench

This is an offline consumer of immutable, manifested Parquet snapshots. It has no provider, wallet,
browser, model-service, operational-database, or transaction dependency.

The canonical operations are tested CLI jobs:

```bash
uv sync --locked
uv run --locked joshi-analysis validate --snapshot fixtures/snapshot_v1
uv run --locked joshi-analysis run \
  --snapshot fixtures/snapshot_v1 \
  --output-root .artifacts/chart-runs
uv run --locked joshi-analysis materialize \
  --snapshot fixtures/snapshot_v1 \
  --dataset-spec specs/datasets/operator_choices_v1.json \
  --feature-spec specs/features/chart_shape_v1.json \
  --label-spec specs/labels/competing_risk_20m_v1.json \
  --output-root .artifacts/datasets
uv run --locked joshi-analysis retrieve-analogs \
  --dataset-run .artifacts/datasets/dataset-<digest> \
  --output-root .artifacts/analogs
uv run --locked joshi-analysis kernel-prototype \
  --output-root .artifacts/kernels
uv run --locked joshi-analysis field-prototype \
  --output-root .artifacts/fields
uv run --locked pytest
uv run --locked ruff check .
```

The materialized dataset is one row per witnessed decision candidate, not one row per market tick.
It retains the exact changing choice universe, operator selection, temporal partition, explicit
feature missingness, competing-risk event, and right-censoring state. The example analog job only
retrieves earlier chart-shape episodes. It is intentionally not a predictor, strategy, backtest,
or PnL claim.

The kernel prototype estimates marked, context-conditioned descriptive response curves using
wallet-cluster support and explicit coverage. Its Hawkes-window and competing-risk outputs are
candidate-model diagnostics, not causal effects. The dynamic-field prototype keeps wallet,
attention, reserve geometry, graph divergence, circulation, and Hodge components separate across
topology epochs. It is a machine estimate and never substitutes for an operator-perception record.

Notebooks may inspect a named snapshot or run bundle later. They are never the authoritative way to
construct a cohort, feature, label, split, or result.

## Operational Snapshot V2 and restricted readback

Snapshot V1 remains frozen. Snapshot V2 adds an operational-store origin, exact committed
publication closure, and truth fingerprint; it passes the same fourteen-table row-level semantic
validator. Validate the checked cross-runtime witness with:

```bash
uv run --locked joshi-analysis validate \
  --snapshot ../fixtures/export/operational_snapshot_v2
```

An operational derived artifact requires a preregistered run occurrence distinct from its later
content digest:

```bash
uv run --locked joshi-analysis publish-derived \
  --snapshot ../fixtures/export/operational_snapshot_v2 \
  --output-root ../fixtures/artifact \
  --analysis-run-id analysis-run-production-fixture-001
uv run --locked joshi-analysis validate-derived \
  --artifact ../fixtures/artifact/derived-<content-digest>
```

Derived V2 is deliberately descriptive and noncausal. Its exact manifest denies census ranking,
hot-scope activation, truth mutation, and economic authority. Exact atom ratios are computed with
Python integer cross-products and checked rational rounding; no atom value is coerced through a
binary float. Input beyond the supported u64 boundary refuses.
