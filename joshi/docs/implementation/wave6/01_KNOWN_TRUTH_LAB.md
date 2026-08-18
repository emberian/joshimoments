# Wave 6 known-truth and counterexample lab

Status: generic and first protocol-specific `N01/W6-K` batteries implemented at fixture-only
authority. They test an exact signed-flow probe plus frozen Pump, PumpSwap, and DLMM arithmetic;
they are not a market estimator, store-resolved release, quote service, or completion of all
venue-specific Wave 6 counterexamples.

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

The current candidate families are deliberately small:

```text
exact_signed_flow_fixture_probe_v1
python_protocol_exact_reference
```

That scope makes failures legible. It does not imply that signed flow or the frozen protocol
arithmetic is a sufficient field, predictor, cause, executable quote, strategy, or useful product
surface.

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

## Seven protocol arithmetic adversaries

The protocol battery additionally pins exact raw fixture bytes for Pump/PumpSwap and DLMM:

```text
Pump/PumpSwap sha256:47837451236ec38eaffa78521d4fc6aa8ffb44d69136a19a0b532d1ad20c29df
DLMM          sha256:a84a22100cfa790aaf37b649bd7db359b3f21afd2a82d2c0074a9cf3cc11e1c8
```

It requires seven separately identified results: Pump literal floor-plus-one versus mathematical
ceiling, separate fee rounding, PumpSwap real-reserve capacity, LP-token retention, DLMM
position-share flooring, deposit-share flooring, and removal-versus-claim separation. Each result
binds the exact suite, raw fixture digest, case truth digest, candidate disposition, arithmetic
output or typed refusal, and fixed fixture-only authority. Missing, duplicate, substituted, or
boolean-as-integer results refuse.

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

Passing either suite says only that a named candidate reproduced its registered generated cases.
It cannot waive later source, coverage, mechanics, topology, measurement-error, store,
prospective, quote, route, economic, or operator gates.

## Verification

```bash
uv --directory analysis run --locked pytest tests/wave6_known_truth -q
uv --directory analysis run --locked ruff check \
  src/joshi_analysis/wave6_known_truth tests/wave6_known_truth
uv --directory analysis run --locked pytest -q
uv --directory analysis run --locked ruff check src tests
```

Focused result: 19 tests pass across the generic and protocol batteries. The complete locked
analysis suite and Ruff also pass.

## Remaining `N01` work

This is the shared generic spine plus the first Pump/PumpSwap/DLMM arithmetic battery, not the full
domain battery. The master plan still requires separate exact fixtures for migration splice,
same-slot reorder, identity revision, broader venue profiles, platform-wide burst, operator-label
induction, runner mark/liquidation divergence, self-routed fee wash, and frozen-future
exit/re-entry. Each later candidate must name the subset it actually passed; generic signed-flow or
basic protocol arithmetic success cannot promote a venue/mechanics/operator lane.
