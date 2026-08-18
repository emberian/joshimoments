# Restricted derived-analysis goldens

`derived-759c5d7d2be1f318fcbc213db9759a3a4653d139ea29b6f55d47403e5d030e55/`
is the exact operational derived V2 witness. It is deterministically generated from
`fixtures/export/operational_snapshot_v2` under the preregisterable analysis occurrence
`analysis-run-production-fixture-001`:

```sh
uv --directory analysis run --locked joshi-analysis publish-derived \
  --snapshot ../fixtures/export/operational_snapshot_v2 \
  --output-root ../fixtures/artifact \
  --analysis-run-id analysis-run-production-fixture-001
```

The occurrence `analysis_run_id` is distinct from the content-derived `artifact_id`. The artifact
is `descriptive_noncausal`, retains an explicit `not_estimated` uncertainty state, and literally
denies census ranking, hot-scope activation, observation/fact/financial mutation, and economic
authority. It has zero rows because the structural operational snapshot contains no chart study;
this is valid readback, not evidence for a strategy or prospective episode.

Python proves byte reproducibility. Independent Rust admission reopens the Parquet part and checks
the exact Arrow schema, typed row invariants, primary-key order, schema/logical/physical digests,
support/coverage, fit cutoff, publication closure, and restriction ceiling. Tests reject altered
Parquet bytes and a self-rehashed future-known manifest.
