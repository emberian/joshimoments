# Wave 6 known-truth and counterexample lab

Status: first estimator-specific `N01/W6-K` suite implemented at fixture-only authority. It tests
an exact signed-flow probe; it is not a market estimator, store-resolved release, or completion of
all venue-specific Wave 6 counterexamples.

The implementation lives in
[`analysis/src/joshi_analysis/wave6_known_truth`](../../../analysis/src/joshi_analysis/wave6_known_truth)
with focused tests in
[`analysis/tests/wave6_known_truth`](../../../analysis/tests/wave6_known_truth).

## Purpose and boundary

The lab builds a frozen suite whose truth is known by construction and checks one exact candidate
result for every case. It does not fit a model, open a store, admit evidence, call a provider,
change acquisition or presentation, reserve resources, or produce an economic action. Its fixed
authority is:

```text
fixture_only_no_market_causal_policy_or_economic_claim
```

The current estimator family is deliberately small:

```text
exact_signed_flow_fixture_probe_v1
```

That scope makes failures legible. It does not imply that signed flow is a sufficient field,
predictor, cause, strategy, or useful product surface.

## Eight required adversaries

The suite requires each class exactly once:

| Case | Required behavior |
| --- | --- |
| identifiable recovery | recover exact `13 - 5 = 8` |
| non-identifiability | emit the full compatible set `{5, 11}`, never one point |
| shortcut trap | retain exact orientation and recover `-7`, not the positive shortcut |
| future leakage | ignore a later malformed row and retain exact earlier result `3` |
| coverage birth/death | refuse a named hot-scope gap instead of returning zero/empty success |
| topology change | retain topology-v1 value `4` and exclude topology-v2 value `9` |
| unit/gauge/wide atom | recover `(2^53 + 1) + (2^53 + 3) = 2^54 + 4` as an integer |
| reflexive policy change | keep baseline value `2` separate from policy-induced value `20` |

Every case freezes a state time, knowledge cutoff, commit cutoff, topology epoch, policy epoch,
unit, exact evidence rows, negative control, and falsifier. Candidate results bind the exact cut,
used and excluded evidence IDs, disposition, exact value or compatible set, refusal reasons, fixed
authority, and recomputed result digest.

## Executable leakage rule

Availability and commit coordinates are checked before semantic payload. A future row may contain
malformed validity, orientation, or atom fields without poisoning an earlier cut. Such a row:

- remains in the complete generator fixture manifest so the attack is auditable;
- is absent from the earlier cut-local input digest;
- is absent from used and excluded evidence in the earlier result; and
- cannot change the derived truth or candidate result digest.

The focused regression physically removes the future row and requires the earlier input digest and
derived expectation to remain identical.

Known-but-out-of-scope topology, policy, validity, and coverage rows are different: they are
processed at the cut and remain explicit exclusions or typed refusals.

## Exactness and refusal

Atoms and orientations must be Python integers with booleans rejected. No float conversion is
performed. Multiple compatible fixture worlds produce a sorted identified set. Gaps/unknowns,
unit mismatch, empty selection, invalid selected payload, result substitution, missing suite cases,
duplicate cases, cut changes, authority changes, and digest changes refuse.

Passing the suite says only that a named candidate reproduced these eight generated cases. It
cannot waive later source, coverage, mechanics, topology, measurement-error, store, prospective,
or operator gates.

## Verification

```bash
uv --directory analysis run --locked pytest tests/wave6_known_truth -q
uv --directory analysis run --locked ruff check \
  src/joshi_analysis/wave6_known_truth tests/wave6_known_truth
uv --directory analysis run --locked pytest -q
uv --directory analysis run --locked ruff check src tests
```

Focused result: 8 tests pass. The complete locked analysis suite and Ruff also pass.

## Remaining `N01` work

This is the shared generic spine plus one estimator-specific suite, not the full domain battery.
The master plan still requires separate exact fixtures for Pump floor-plus-one and virtual/real
reserve behavior, DLMM one-bin/share rounding, migration splice, same-slot reorder, identity
revision, platform-wide burst, operator-label induction, runner mark/liquidation divergence,
self-routed fee wash, and frozen-future exit/re-entry. Each later candidate must name the subset it
actually passed; a generic signed-flow success cannot promote a venue/mechanics/operator lane.
