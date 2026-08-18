# Wave 6 prospective campaign contract

Status: `N03/W6-C0` is implemented only at
`unverified_semantic_fixture_only`. The implementation freezes and revalidates an exact caller-fed
campaign chain. The sole store can now retain those five exact documents as one atomic fixture
bundle, but it does not run, randomize, prospectively journal, reveal, score, publish, or promote a
campaign.

The Rust contract lives in
[`crates/joshi-wave6-campaign`](../../../crates/joshi-wave6-campaign). N00 registers its checked
schema bytes at
[`fixtures/wave6/schemas/campaign_registration_v1.json`](../../../fixtures/wave6/schemas/campaign_registration_v1.json).
The deterministic five-document chain is checked in under
[`fixtures/wave6/campaign`](../../../fixtures/wave6/campaign) and cross-parsed byte-for-byte by the
crate. Migration V16 can retain that exact chain in one store commit after resolving the prior N00
program and campaign schema. Repository presence and bundle durability still grant no prospective
authority.

## Exact N00 boundary

`CampaignRegistrationV1` is accepted only against the exact parsed N00 program registration. The
program must admit `campaign_registration_fixture` with:

- schema `joshi.wave6.campaign-registration.v1` and the exact checked schema digest;
- rung `h5_policy`;
- maximum maturity `fixture_roundtrip`;
- permitted claim `fixture_campaign_protocol_only`; and
- prohibited inference `prospective_result_or_operational_campaign`.

Changing and re-closing the N00 claim boundary still makes N03 refuse. N00 continues to consume no
Wave 5 gate and to grant no provider or external-mutation budget.

## Registration and enrollment

Registration freezes:

- program, campaign, family, semantic-version, and exact self-digest identity;
- an explicit estimand with numerator, denominator, outcome, unit, and canonical signed-`i128`
  decimal value contract;
- a sorted exact eligible universe and registered exclusion reasons under a universe self-digest;
- at least two sorted arms whose distinct content digests share one invariant-safety digest and
  whose allocation probabilities sum exactly to one million parts per million;
- sorted metrics with named numerator, denominator, unit, baseline, and multiplicity family;
- the complete resolved/survival/censoring/competing/conflict/unsupported/open disposition grammar;
- correction, contamination, independent apparatus/scientific/operator stops, and bounded local
  budgets with provider and external-mutation units fixed at zero; and
- strictly advancing registration, enrollment, input, seal, maturity, outcome, and adjudication
  clocks.

`FrozenEnrollmentV1` then requires exactly one disposition for every registered universe subject,
in the original order. Included subjects cannot carry an exclusion reason; excluded subjects must
carry one of the registered reasons. The included risk set must be nonempty and must freeze no
later than the registered enrollment cutoff.

## Assignment, seal, and adjudication

`CampaignAssignmentV1` binds the exact registration and enrollment. It carries exactly one row for
each included subject, in frozen order, and copies an exact registered arm probability. Its
assignment-basis digest is explicitly caller-fed fixture material, not proof of randomization. The
assignment clock must strictly follow enrollment and precede the registered input cutoff.

`CampaignSealV1` binds registration, enrollment, and assignment IDs and digests. Its evidence list
is nonempty, strictly artifact-ID ordered, content-addressed, and bounded by both the registered
input-knowledge cutoff and a positive caller-fed fixture commit cutoff. The seal must occur after
assignment and the information cutoff but by the seal deadline. The name “seal” describes exact
bytes only: there is no hidden store, sealed journal, receipt, or blindness authority.

`CampaignAdjudicationV1` binds the exact seal and includes exactly one row for every included
subject. Every row becomes known no earlier than maturity and no later than the frozen outcome
cutoff. Dispositions have distinct shapes:

- resolved observations require a canonical signed integer, the registered unit, evidence, and no
  gap;
- healthy survival, administrative censoring, competing events, and intervention invalidation
  require evidence and no value or gap;
- source loss, unsupported, and open require a typed gap and no observed value;
- interval censoring requires both evidence and a gap; and
- conflicting requires at least two distinct evidence artifacts and no observed value.

Future evidence, commit-cutoff overflow, duplicate artifact identity, malformed signed integers,
unit substitution, missing subjects, missing required gaps, and chain/digest substitutions refuse.
The sole public claim enum is `descriptive_fixture_disposition_only`; there is no result, score,
effect, causal, policy-value, product, or economic claim API.

## Authority ceiling

Every successful parser returns `UnverifiedSemantic<T>`. The wrapper exposes exact bytes and a
document digest, but its ceiling is permanently
`unverified_semantic_fixture_only`. The campaign crate has no `joshi-store` dependency, opaque
receipt, provider client, runner, presentation hook, wallet, signer, or action API. The separate
store adapter reparses all five documents, preserves their semantic and physical digests, and
issues a store commit receipt without changing that ceiling.

The words `frozen`, `assigned`, `seal`, and `adjudication` therefore mean only that a complete
caller-fed document passed intrinsic exactness checks. They do not establish prospectivity,
mutual blindness, phase-by-phase append order, real enrollment, actual treatment, outcome truth,
or a scientific result. Those remain blocked on a prospective sole-store campaign journal and a
later registered execution/reveal boundary. The V16 atomic bundle deliberately cannot satisfy
those gates.

## Verification

The focused adversarial suite covers exact registration/enrollment roundtrip; N00 claim/schema
substitution; arm order, safety, content, probability, censoring, budget, and chronology changes;
missing/reordered/invented enrollment; subject/arm/probability assignment recoding; collapsed
phase clocks; future, duplicate, and over-cutoff evidence; foreign chain digests; incomplete
outcomes; pre-maturity knowledge; malformed signed values; unit changes; source-loss without a
gap; and conflict with only one evidence item.

```bash
cargo test --locked --offline -p joshi-wave6-campaign --all-targets
cargo clippy --locked --offline -p joshi-wave6-campaign --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline \
  -p joshi-wave6-campaign --no-deps
```

Current focused result: 12 tests pass. The honest statement is:

```text
Wave 6 has an exact, caller-fed, fixture-only prospective campaign protocol.
It does not have a store-resolved, executed, blinded, scored, or scientifically adjudicated
campaign.
```
