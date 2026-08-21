# Restricted derived-analysis goldens

`derived-c3bdb466464f40bd262500641b152320a4d2f4d404928e054be7fb9bd0c1ffa5/`
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
