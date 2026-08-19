# Wave 6 known-truth and counterexample lab

Status: generic, first protocol-specific, first structural, and first seven-case domain `N01/W6-K`
batteries implemented at fixture-only authority. They test an exact signed-flow probe, frozen
Pump/PumpSwap/DLMM arithmetic, synthetic migration/order/identity-revision boundaries, and bounded
venue/burst/mechanism/operator/episode/household counterexamples; they are not a market estimator,
store-resolved release, identity claim, quote service, or completion of all Wave 6 counterexamples.

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
python_structural_exact_reference
python_domain_exact_reference
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

## Three structural adversaries

The structural battery pins the exact canonical fixture
`fixtures/wave6/structural_known_truth_v1.json` at:

```text
sha256:806bf5668a0de0f113677f5aad6947074cb463aa1dc9776794e22a2b491be154
```

It recomputes three separately typed boundaries:

- a migration splice sums the Pump-curve and PumpSwap within-gauge deltas (`50 + 20 = 70`) and
  retains the invalid direct cross-gauge subtraction (`-80`) only as a negative control;
- two same-slot CPMM events follow transaction index even though their display IDs sort in the
  opposite order, while an unindexed projection retains both distinct order-result digests as a
  compatible set; and
- an identity revision selects only assertions available at each knowledge/commit cut. A future
  revision, including a malformed future payload, cannot alter the earlier input digest or entity
  symbol.

Every output has a closed carrier (`decimal_integer`, `identifier`, `sha256`, or `disposition`).
The identity symbols are synthetic fixture labels. They do not claim common control, intent, or a
real wallet/account mapping.

## Seven domain counterexamples

The generated domain battery closes the seven missing families named in the first N01 review:

- one quote size produces `90` atoms under the fixture CPMM profile and `99` under the fixture
  fixed-bin profile, so a venue-specific result cannot silently transfer;
- two observed burst rows retain their exact `9` atoms while one explicit subject gap refuses a
  platform-wide total;
- identical display points retain two content-distinct compatible mechanism traces rather than one
  chart-shape diagnosis;
- one raw ambiguous operator fragment retains two compatible labels and no truth label;
- a six-atom disposal from ten atoms retains a four-atom runner and refuses terminal value without
  a terminal quote;
- internal principal plus self-fee counterlegs total twelve atoms but post zero external household
  flow; and
- an earlier zero-inventory `watching_flat` cut is byte-invariant to a future re-entry row, while a
  later cut opens a new seven-atom inventory epoch.

Every case binds sorted fixture identities, typed exact outputs, a negative control, a falsifier,
fixed fixture-only authority, and a recomputed truth digest. The candidate must return every case
exactly once with byte-exact outputs and a recomputed result/evaluation digest. The canonical
evaluation is checked in under [`fixtures/wave6/artifacts`](../../../fixtures/wave6/artifacts),
regenerates byte-for-byte in Python, and strictly cross-parses in Rust. Missing cases, changed
kind/schema mappings, duplicate or reordered JSON, authority changes, and self-digest substitution
refuse.

This fourth evaluation is intentionally **not yet** a registered N00 artifact kind or store row.
Its checked golden and strict cross-runtime parser freeze only the intrinsic fixture boundary; the
kind remains absent from the N00 artifact denominator. It cannot be counted among the three
V12/V13/V15 durable evaluation artifacts until a separate registry/schema/store change freezes
that boundary.

## Three registered exact evaluation artifacts

The first three evaluated candidates materialize the complete fields promised by their registered
V12 schemas. Each canonical artifact binds the suite digest, candidate, sorted exact passed-case
denominator, one ordered result digest per case, its pinned source-fixture digest(s) where
applicable, fixed fixture authority and a recomputed evaluation self-digest. Exact checked bytes
live under [`fixtures/wave6/artifacts`](../../../fixtures/wave6/artifacts).

Strict parsers reject unknown or duplicate fields, noncanonical JSON, malformed digests, changed
source-fixture identities, missing results, changed authority and self-digest substitution. The
tests regenerate all three outputs from their exact case batteries, require byte equality with the
checked fixtures, and independently reparse them. These are real evaluated fixture outputs, but
they remain caller-fed checked artifacts: they have not yet been admitted by the sole store and
carry no durable receipt, market observation or estimator-performance authority.

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

The focused generic, protocol, structural, domain, and exact-artifact tests pass. The complete
locked analysis suite and Ruff also pass.

## Remaining `N01` work

The seven named domain gaps now have one deterministic counterexample each, but N01 is not a
complete empirical or venue-mechanics battery. It still needs materially broader profile vectors,
multi-window burst and overlap generators, additional mechanism-equivalent charts, open operator
language cases, effect/quote-supported episode families, multi-asset household accounting, and
longer correction/re-entry histories. The new evaluation also remains unregistered and
store-unretained. Each later candidate must name the exact subset it passed; generic, basic
protocol, structural, or seven-case domain success cannot promote a venue/mechanics/identity/
operator lane.
