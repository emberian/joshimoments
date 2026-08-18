# Wave 5 — Compact census bakeoff

`joshi-census-bakeoff` is a pure evaluator. It receives retained candidate and reference facts;
it never opens a provider connection, hydrates a transaction, decodes bytes, or writes census
state. The acquisition owner can adapt its result as a read-only quality decision.

The reference side is exact only for finalized, exact-hydrated, non-failed transactions whose
pinned decoder returned `decoded`. Candidate records that are failed, log-truncated, or only
program mentions are excluded from positives. Duplicate signatures are counted; conflicting
equal occurrences refuse evaluation. A stronger finality occurrence corrects a weaker reference
occurrence and is counted in `referenceFinalityCorrections`.

Both sides carry independent interval gaps. Cost caps are checked before quality classification.
The result is one of `census_qualified`, `sample_only`, `unavailable`, or `refused`; ratios and
costs use exact integer wire values and parts-per-million ratios. This public pure adapter marks
every result `unverified_semantic` and therefore caps even threshold-satisfying facts at
`sample_only`; only a store-owned integration layer with opaque coverage, receipt, decoder, and
cost attestations may promote a result to `census_qualified`.

Port: `evaluate(&BakeoffInput) -> Result<BakeoffResult, BakeoffError>`. The caller must persist the
result with its run and coverage-window identity; this crate grants no readiness, publication, or
provider-execution authority.
