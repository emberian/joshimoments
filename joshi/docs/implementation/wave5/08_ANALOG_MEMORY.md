# Wave 5 — earlier-only analog memory

Status: pure deterministic artifact implementation; no provider, store, filesystem, or Glass I/O.

## Boundary

`analysis/src/joshi_analysis/analog_memory/` consumes already materialized point-in-time records.
It does not query the operational store, fetch providers, fit a model, or expose a strategy/action
claim. `DecisionRecord` contains only typed feature/filter observations as known at its own
decision cutoff. Filter values carry ontology and identity version/digest references and are
explicitly outcome-free; an outcome-derived feature is rejected.

Each candidate decision cutoff must be strictly earlier than the query cutoff. Every feature's
`known_at`, `available_at`, ontology/identity version references, and effective times must be no
later than its record cutoff. A later observation, ontology version, identity correction, outcome,
or availability cannot enter indexing, distance, ranking, or tie-breaking. Duplicate decision or
subject identities are refused rather than silently merged.

## Artifacts

`AnalogArtifact` is a canonical decision-mode artifact containing:

- query ID and cutoff;
- named/versioned `DistanceSpec` and missingness policy; weights and penalties are finite, bounded
  exact decimal values with at least one nonzero weight (binary floats and booleans are rejected);
- decomposed per-feature distances and explicit missing/gap components;
- deterministic neighbors ordered by `(distance, decision_id, subject_id)`; or
- `none_analogous` when no comparable candidate remains.

`PlainFilterArtifact` is an outcome-blind exact-filter baseline. It is retained separately from
nearest-neighbor output and carries its own filter identity. `RetrospectiveReveal` is a separate
artifact with a reveal ID, exact source analog digest, reveal time, and an exact partition of every
neighbor ID into one typed outcome closure. The only closure states are `matured`, `missing`,
`conflicting`, and `censored`. Every closure binds `known_at <= maturity_at <= revealed_at`;
matured closures carry outcome/evidence digests, conflicting closures carry sorted, unique
conflicting evidence digests, and missing/censored closures carry explicit reasons. It cannot
mutate or add fields to the decision-mode artifact.

Missingness is explicit: `skip` omits a component, `penalize` records a configured component
penalty, and `exclude` removes the candidate. If all components are missing/skipped, retrieval
returns `none_analogous`; it never converts a gap to zero similarity.

## Adversarial gates

`fixtures/analog-memory/adversarial.v1.json` covers equal/future cutoffs, future ontology and
identity corrections, outcome-derived features, gap policies, deterministic ties, and separate
retrospective reveal. The uniquely named `analysis/tests/test_analog_memory.py` asserts canonical
repeatability, strict earlier-only behavior, decomposed exact distances, duplicate/gap/version
refusal, typed outcome maturity, and no outcome leakage.

No analog artifact qualifies a forecast, policy, acquisition allocation, ranking intervention, or
economic result. Any later scoring or usefulness judgment must be a separately registered
retrospective intervention.
