# Wave 5 epistemic admission: receipt-gated store seam

## Status and ceiling

`joshi-epistemic-admission` is a narrow seam between public epistemic-book DTOs
and the future private `SQLite` adapter. It has no writer, source, acquisition,
retrieval, presentation, execution, wallet, transaction, signer, or submission
authority.

Its only public success values are `UnverifiedSemantic<ClaimOccurrenceV1>` and
`UnverifiedSemantic<ForecastSubmissionV1>`. They are strict semantic preflights,
not durable claims, forecast seals, blindness proofs, scores, support, or ensemble
eligibility. Public `Resolved*PortV1` values from `joshi-epistemic-book` remain
caller assertions only.

Receipt types have private fields and no public constructors. The in-crate
`private_adapter` verifier is an implementation contract, not a writer. Until the
store migration and methods below exist, no caller can mint a book
`Durable*Capability`; the honest ceiling remains `contract_draft_fixture_validated`.

## Admission order

```text
caller DTO -> strict UnverifiedSemantic preflight
  -> private store resolves scene + universe + frozen evidence/coverage/gaps
     + information cutoff + mechanics capability rows
  -> atomic ClaimOccurrence commit and exact receipt
  -> namespace-bound empty-visibility first-round commit
  -> every eligible first round sealed -> one durable reveal
  -> admissible adjudication -> score -> earlier-only support -> shadow ensemble
```

Nothing in this chain may affect acquisition, retrieval, prompt selection, hot
leases, quote refresh, ranking, notification, presentation, operator attention,
asset reservation, transaction construction, signing, or submission. All artifacts
remain `read_only_no_execution`.

## Exact B0 clock and blindness

For every first-round submission, the private adapter must prove:

```text
maximum_input_availability <= submission_input_cutoff
 <= occurrence_information_cutoff <= occurrence_commit_at
 <= submission_production_time <= submission_commit_receipt_at
 <= issue_deadline <= target_window_origin < horizon_at < knowledge_deadline
 <= sealed_journal.reveal_not_before <= durable_reveal_at
```

The submission cutoff equals the occurrence cutoff and its frozen-input digest is
the canonical digest of that occurrence's frozen input. The occurrence receipt binds
the exact canonical occurrence bytes/digest and declared commit time; it cannot be a
later evidence fill.

Initial first rounds require exactly empty precommit visibility sets for submissions
and ensembles, plus proof that no reveal already exists. Revisions never use this
path; they disclose every visible parent and ensemble at a prospectively registered
landmark.

The sole reveal is committed only after *every registered eligible forecaster* has
one exact first-round seal. `all_eligible_sealed_at` is at least every component
commit and no later than reveal; reveal is no earlier than `reveal_not_before`.
Required count is an ensemble minimum, never permission to reveal an incomplete
eligible set.

## Required private adapter methods

The future owner adds these as `pub(crate)` methods in a co-located
`joshi-epistemic-admission` adapter backed only by private `joshi-store`
single-writer operations. No method is a public constructor.

| Method | Exact required proof / output |
| --- | --- |
| `resolve_occurrence_receipts_v1` | Canonical scene, universe, every frozen evidence/coverage/gap row, availability, cutoff, and capability rows; returns the five receipt families consumed by `verify_occurrence_receipts`. |
| `commit_claim_occurrence_v1` | Atomically writes canonical occurrence bytes/digest and all closure joins, establishes `occurrence_commit_at`, returns `OccurrenceCommitReceipt`, then mints the book capability only after receipt verification. |
| `commit_sealed_first_round_v1` | Locks the namespace; checks eligibility, empty precommit visibility, and no reveal; atomically writes canonical submission/visibility witnesses and invokes `verify_sealed_first_round_submission`. |
| `reveal_first_round_namespace_v1` | Locks the namespace, verifies every eligible forecaster has one exact seal, writes the unique reveal row, and invokes `verify_first_round_reveal`; it never accepts a required-count subset. |
| `commit_adjudication_v1` | Resolves only outcome evidence available by knowledge deadline, coverage/gaps and correction lineage; append-writes canonical adjudication and its receipt. |
| `commit_proper_score_v1` | Requires exact private occurrence, sealed-submission, and adjudication capabilities; delegates to `build_brier_score` and atomically persists canonical output. |
| `derive_support_summary_v1` | Reads complete denominator and disjoint chronological membership. Every embargo and outcome availability is strictly earlier than any consuming occurrence cutoff. |
| `commit_shadow_ensemble_v1` | Requires same definition/occurrence/conditioning, unique primary lineage, repeated support, and seal/reveal closure; calls the opaque book ensemble constructor and persists shadow H3 only. |

All methods recompute digests, lock occurrence/namespace rows across state transition,
and accept an idempotent retry only as exact-byte readback. Changed same-ID bytes,
cross-occurrence references, a second reveal, post-cutoff evidence, or a missing row
refuse before a durable receipt returns.

## Migration required of the store owner

This lane adds no schema or store code. The store owner must add a forward-only
migration after `0009_wave5_living_instrument.sql`, using canonical byte/SHA-256 and
`created_commit_seq` closure conventions already used for immutable artifacts.

| Required table(s) | Keys and invariants |
| --- | --- |
| `epistemic_claim_definition_v1` | Definition ID, canonical bytes/SHA-256, version, exact optional superseded row, authority, commit sequence. |
| `epistemic_claim_occurrence_v1` | Occurrence ID; definition/scene/universe IDs and SHA-256s; frozen-input and capability-closure SHA-256s; B0 clocks; namespace; canonical bytes/SHA-256; authority; unique commit sequence. All dependency rows precede it. |
| `epistemic_occurrence_evidence_v1` | Occurrence/ordinal, evidence ID/SHA-256, availability/validity, domain/carrier/unit/authority, explicit coverage/gap membership; unique ordinal and exact frozen-manifest closure. |
| `epistemic_occurrence_capability_v1` | Occurrence, kind/profile/maturity, artifact ID/SHA-256; unique kind/profile and exact capability-closure digest. |
| `epistemic_sealed_namespace_v1`, `epistemic_namespace_eligible_forecaster_v1` | Namespace/occurrence, required count, reveal-not-before, registered forecaster. Unique `(namespace, forecaster_id)` and one occurrence per namespace. |
| `epistemic_forecast_submission_v1`, `epistemic_submission_visibility_v1` | Submission/occurrence/namespace bindings, phase, canonical bytes/SHA-256, commit clock/sequence, frozen-input digest, immutable lineage and atomic visibility read. First rounds require registered forecaster and zero visibility rows. |
| `epistemic_first_round_reveal_v1` | Namespace primary key, all-eligible-sealed clock, reveal clock, canonical receipt/digest, commit sequence. Trigger refuses second, early, or incomplete-set reveal. |
| `epistemic_adjudication_v1`, `epistemic_adjudication_evidence_v1` | Append-only correction lineage, occurrence, knowledge cutoff, disposition, evidence availability and coverage/gap closure. |
| `epistemic_proper_score_v1` | Score ID, exact occurrence/submission/adjudication IDs and SHA-256s, canonical bytes/SHA-256, build digest, commit sequence; no mutable replacement. |
| `epistemic_support_summary_v1`, `epistemic_support_membership_v1`, `epistemic_support_window_v1` | Complete denominator; score/adjudication/occurrence membership; outcome availability; bounds and embargo. Refuse reused scores, duplicate occurrences, overlap, and current/future support. |
| `epistemic_shadow_ensemble_v1`, `epistemic_ensemble_component_v1` | Occurrence/support bindings, canonical bytes/SHA-256, components, unique primary lineage, weights/output, seal/reveal reference, read-only authority. |

Foreign keys and triggers compare SHA-256 as well as identities. Evidence/capability joins must
be no later than the occurrence; support used by an ensemble must be strictly earlier than that
occurrence cutoff. This migration must not create a competing session, launch, nomination,
abstention, outcome, or export authority.

## Adversarial witnesses

`fixtures/epistemic-admission/` records B0-late-commit, peer-visible first round,
reveal-before-seal, and future-support counterexamples. The suite exercises unverified-only
preflight, B0 refusal, and revision laundering refusal. No test self-mints a store receipt or
durable book capability.

```text
cargo test -p joshi-epistemic-admission --locked
cargo clippy -p joshi-epistemic-admission --all-targets --locked -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc -p joshi-epistemic-admission --no-deps --locked
```
