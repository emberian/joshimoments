# Wave 6 closeout

Status: **closed, not promoted**. Wave 6 is over because the wave framing is being retired. It
never held a real observation. Its highest attained ceiling over the whole tranche is
`unverified_semantic_fixture_only`, with two deliberately narrow exceptions that resolve two
fixture Pump discovery facts. The active program is [`PILLARS.md`](../PILLARS.md).

The ceiling ledger in [`99_INTEGRATION_REVIEW.md`](99_INTEGRATION_REVIEW.md) is the source of truth.
This document records what the tranche produced, what it claimed that did not hold, and what
survives.

## What Wave 6 actually delivered

| Delivered | Owner | Honest ceiling |
| --- | --- | --- |
| An authority ladder with mechanically fixed claim verbs per rung H0-H5, closed permitted/prohibited claim lists, mandatory prohibitions, and provider and external-mutation budgets pinned to zero | `joshi-wave6-registry` | `design_only` plus `durable fixture contract` |
| Known-truth batteries: eight generic inference traps, seven Pump/PumpSwap/DLMM arithmetic cases, three structural migration/order/identity cases, seven generated domain counterexamples, all byte-exact and cross-parsed in Rust and Python | `wave6_known_truth` / N01 | `unverified_semantic_fixture_only` |
| A response-atlas prototype with cutoff-before-validation ordering, admitted-anchor risk semijoin, separate response and risk identities, explicit pending denominators, exact rational means | `wave6_response_atlas` | `intrinsic_contract` / `fixture_recovered` |
| A shadow-policy arena with strict action/quote/effect separation, residual-bearing missing terminal routes, LP transition reconciliation, self-flow non-posting, commit-aware tape order | `wave6_shadow_policy` | `intrinsic_contract` / `fixture_recovered` |
| A routed-liquidity shadow with finite sequential bins, would-quote and model-transfer and fill kept distinct, wide integers, structural incomplete-denominator refusals, mandatory self-route counterlegs | `wave6_routed_shadow` | `intrinsic_contract` / `fixture_recovered` |
| Migrations V11-V22: exact durable program, schema, evaluation content, market-atlas bytes, artifact DAG, disposition ledger, atomic campaign bundle, research proposal and disposition | `joshi-store` | `unverified_semantic_fixture_only` |
| V20: one real prior W5 public C0 discovery occurrence re-derived from the store into W6 as an input census, with denominator, hot/cold membership, coverage, gaps, cut and lineage, cross-checked in locked Python | `joshi-store`, `apps/core` | `cross_runtime_store_census_validated_not_market_atlas` |
| V22: that census joined to a headed publication, one durable operator act with its original presentation gap, and a later browser-reported claim, rebuilt after restart, refusing to repair the gap | `joshi-store`, `apps/core` | `cross_runtime_store_input_validated_not_model_admitted` |
| The adversarial repair record W6-B1 through W6-B10, and the honesty of W6-B0 | reviewers | the tranche's most durable output |

The two bridges are the good part. V20 and V22 are the only places in the entire wave program where
one component's real output became another component's input through the store, and they were built
against the store rather than around it. They are also, together, the join of *two fixture mint
discovery facts* — and they were the last thing the tranche did rather than the first.

## What Wave 6 claimed that did not hold

**Its entry gates.** The Wave 6 plan makes `W5-G*` external evidence occurrences. None of the three
prototypes consumes a store-resolved `W5-G*` occurrence. `consumedWave5Gates` is empty in the
checked-in registration and the store adapter refuses rather than resolves any such reference. Wave
6 began before its predecessor's gate existed, and then encoded that gate reference as a caller
string. W6-B0 states this plainly and it is the finding that governs the whole tranche.

**"Registered", "witnessed", "complete", "known", "exact", "common".** These words appear across the
prototypes over values the caller supplied: response occurrence IDs, version IDs, coverage windows,
availability clocks and commit sequences arrive in Arrow rows; shadow-policy evidence digests are
checked for SHA-256 shape but not recomputed from evidence; routed `universe_complete`, coverage,
candidate IDs, scenario identity and terminal manifest ID are supplied directly. A caller can still
author a self-consistent source artifact, digest and carrier ratio and thereby author scalar PnL.

**"Market atlas."** V19 persists market-atlas *bytes*. The six-stratum atlas schema admits zero of
six strata from anything observed: discovery presence is not lifecycle state, and there is no
registered venue, liquidity, wallet, caller or episode coverage.

**"Campaign engine", "active sensing", "prospective".** No enrollment, assignment, randomization,
blindness, exposure receipt, propensity, consented session, maturation, censoring or independent
adjudication has ever occurred. The atomic five-document campaign bundle is a durable set of
documents about a campaign, not a phase-by-phase prospective journal. A durable proposal is not a
review; a durable disposition is not an approval; a stored reviewer identity is explicitly
unverified.

**"Operator model."** V22 is honest about what it refuses — it will not repair the act gap, equate
memory and pairing session domains, verify human viewing, or observe recognition — and that list
is the entire content of the operator-model claim. No human has been observed recognizing anything.

**Durability as progress.** Twelve of the repository's twenty-three migrations are Wave 6 fixture
bookkeeping. The store learned to durably retain, reparse, restart-reopen and idempotently retry
documents *about a program that had never observed anything*. The engineering is correct. The
sequencing is the finding.

## The structural mistake

Wave 6 repeated Wave 5's mistake one level higher up. Wave 5 built kernels without a vertical; Wave
6 built a research apparatus for kernels without a vertical.

Every prototype is a pure function over a tape the caller wrote. That is not a criticism of the
functions: the arithmetic is exact, the refusals are typed, the denominators are explicit, and
the adversarial repairs are real. It is a statement about what the tranche could possibly have
learned.
A response atlas over an authored tape can only tell you that your reducer is correct. It cannot
tell you one thing about the market, and it was never going to, and that was knowable on the first
day.

The ceiling vocabulary is what allowed this to run for a whole tranche without anyone being wrong.
`intrinsic_contract` and `fixture_recovered` are accurate labels, honestly applied, on work that was
correctly refusing to overclaim. But an accurate label on an unfalsifiable result is still an
unfalsifiable result, and the vocabulary gave the tranche a way to score progress that never
required contact with anything outside the repository. Nine ceilings said *inputs are caller
projections* in Wave 5. Wave 6 added ten more rows saying the same thing about a different layer,
and stored them.

The single edge that would have changed this is the same one Wave 5 left disconnected:
`joshi_admission::batch::source_frames`, behind `feature = "source-edges"`, enabled by exactly one
crate that is neither application.

## Carried forward

- **V20 and V22.** They are the template. Every future slice resolves its inputs from the store the
  way these two do, and states what it refuses the way these two do.
- **The claim grammar.** Mechanically fixed verbs per rung, closed permitted-claim lists, and the
  refusal to allow a free-form inference channel. This is genuinely good and it becomes the writing
  rule for every pillar document.
- **The known-truth batteries.** Twenty-five cross-runtime counterexamples that a future estimator
  must not get wrong. They are a tiny sample rather than coverage, and they are still worth keeping
  as a permanent regression floor.
- **The exact arithmetic.** Decimal-string sums, reduced rational means, wide accumulation, exact
  `SourceCut` equality, latency and unit refusals, mandatory counterlegs, positive-output terminal
  refusal. Reuse these directly in the quote and portfolio slice.
- **The prohibitions.** Zero provider budget by default, zero external mutation, no signing, no
  submission, no fills, no causal or profit language. These are permanent, not Wave 6 policy.
- **The one-household rule and the contributions-versus-starting-value separation**, before shadow
  policy and routed liquidity are ever joined.

## Abandoned

- **The Wave 6 program registration as an authority document.** It grants nothing, it consumed no
  gate, and it will not be extended. It stays in the store as history.
- **Further fixture-durability migrations.** No new migration whose only content is a document about
  the program. The next migrations carry observations.
- **N03 prospective campaign machinery, the active-sensing engine, and the epistemic campaign engine
  as near-term work.** Randomization, blindness and adjudication are meaningless before there is a
  population to enroll. They return when a real denominator exists, and not before.
- **The three prototypes as standalone lanes.** Response atlas, shadow policy and routed shadow do
  not proceed as separate research instruments. They become consumers inside the pillar slices that
  produce their inputs, or they stay frozen where they are.
- **`unverified_semantic_fixture_only` as a shippable result.** It is an accurate label and it is no
  longer a deliverable.
