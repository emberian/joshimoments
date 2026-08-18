# Wave 6 tranche-two adversarial review

Status on 2026-08-18 against working tree based on
`c32674a93a41351d9bef79ec25fa03d4da1a4b14`: **PASS at the five documented intrinsic
contract ceilings; BLOCKED at `store_resolved` and every stronger empirical or operational
ceiling**.

This review covers only the uncommitted tranche-two implementations, tests, and implementation
documents for `wave6_market_atlas`, `wave6_operator_model`, `wave6_epistemic_campaigns`,
`wave6_research_desk`, and `wave6_active_sensing`. Earlier prototype paths were not audited or
modified. This review changed no implementation or test file.

All five findings below are repair re-audits against their frozen implementations.

## Ceiling vocabulary

- `shape_only`: frozen DTO/schema construction and local validation over caller-provided values.
- `intrinsic_contract`: relationships enforced from the complete values supplied to one pure call;
  it does not prove that an ID, digest, clock, receipt, review, or evidence reference is genuine.
- `fixture_recovered`: checked-in synthetic cases exercise that shape or intrinsic relationship.
- `store_resolved`: an external owner resolves identities, contents, clocks, selection, receipts,
  append-only lineage, and human actions. A caller-spelled value is not durable proof.

## Per-lane decision at exact ceiling

| Lane | Repair re-audit | Residual P0 blocker | Exact ceiling |
| --- | --- | --- | --- |
| Market atlas | **PASS** future-ineligible payload and nullable semantic-index isolation, selected-cut refusal, and observed-row native/component identity binding. | No intrinsic P0 found in the assigned repair scope. Source identity, availability, commit, retraction, coverage, and payload values remain caller-fed. | **PASS `intrinsic_contract` point-in-time projection over supplied exact-schema rows; BLOCKED `store_resolved`.** No resolved snapshot, coverage closure, or reliable trajectory. |
| Operator model | **PASS** blind/reveal clocks, phase receipt, same-ID artifact version/content/commit closure, response-material digest, and scene/presentation binding substitutions. | No intrinsic P0 found in the assigned repair scope. Every version, digest, commit, receipt, and response remains caller-fed. | **PASS `intrinsic_contract` versioned/content-addressed replay closure; BLOCKED `store_resolved`.** No proof of rendering, viewing, recognition truth, or reconciled effect. |
| Epistemic campaigns | **PASS** target/occurrence identity and typed rule dispatch: exact binary Brier is admitted; binary log, directional multiclass, and joint hazard rules are refused by the binary preview; score-rule mutation changes occurrence identity. | No intrinsic P0 found in the assigned repair scope. The preview is deliberately not a sealed score artifact. | **PASS `intrinsic_contract` occurrence-bound binary-Brier arithmetic; BLOCKED `store_resolved`.** No sealed submission, blind round, adjudication, score, ensemble, or support. |
| Research desk | **PASS** same-ID policy/budget replacement, unadmitted experiment evidence, evidence-swapping supersession, and revision-time attacks. | No intrinsic P0 found in the assigned repair scope. Caller-provided policy, descriptors, and human IDs still have no durable owner. | **PASS `intrinsic_contract` immutable non-executable proposal; BLOCKED `store_resolved`.** No durable review, accepted design, query, result, or claim. |
| Active sensing | **PASS** nonmember/manual-floor, cross-experiment assignment, outcome-recoding, invented denominator, invented subject, and invented assignment-occurrence attacks. | No intrinsic P0 found in the assigned repair scope. Registrations, members, lineage, assignment artifacts, budgets, and provider effects remain caller-fed with no durable owner. | **PASS `intrinsic_contract` fixed-registration assignment/report closure; BLOCKED `store_resolved`.** No durable registry, cumulative cross-report ledger, provider receipt, VOI qualification, or causal result. |

No repaired lane reaches `store_resolved`, `prospective`, `retrospective_descriptive`,
`qualified_support`, `live`, `product`, or economic authority.

## Repair re-audits

### W6-T2-B1-R — campaign occurrence identity and score dispatch pass

`ClaimDefinition.semantic_digest` now commits the complete target definition, including outcome
order, target digest, score rule, and authority. `ClaimOccurrence.occurrence_id` commits that
definition digest plus subject, scene, universe content, evidence, clocks, eligible forecasters,
reveal settings, caps, and authority (`wave6_epistemic_campaigns/contracts.py:247-393`). A
submission and adjudication each carry occurrence identity and definition semantic digest, and the
engine rechecks them (`engine.py:53-64`, `117-128`). The original same-ID edited-target attacks now
fail:

```text
OCCURRENCE_ID_CHANGED True
OLD_SUBMISSION_REFUSED submission cannot be substituted across occurrences
OLD_ADJUDICATION_REFUSED adjudication cannot be substituted across occurrences
IDS_ONLY_REBIND_REFUSED submission cannot be substituted across definition content
NONHEX_DIGEST_REFUSED target_spec_digest must be sha256:<64 lowercase hex>
```

The final residual repair also types the registered scoring rules by target family. The only Brier
preview implemented is explicitly binary: it requires one of the registered binary-Brier rules and
a two-outcome domain (`contracts.py:32-96`, `engine.py:152-204`). It does not silently substitute
Brier arithmetic for a binary log, directional multiclass, provider multiclass, or joint
hazard/time-to-event definition. Fresh dispatch and identity probes produced:

```text
BINARY_BRIER_ACCEPTED 20000000000 1000000000000
BINARY_LOG_REFUSED ManifestError Brier preview requires an exact binary target and registered binary Brier rule
DIRECTIONAL_MULTICLASS_BRIER_REFUSED ManifestError Brier preview requires an exact binary target and registered binary Brier rule
HAZARD_JOINT_BRIER_REFUSED ManifestError Brier preview requires an exact binary target and registered binary Brier rule
SCORE_RULE_DEFINITION_ID_SAME True
SCORE_RULE_DEFINITION_DIGEST_CHANGED True
SCORE_RULE_OCCURRENCE_ID_CHANGED True
OLD_SCORE_RULE_SUBMISSION_REFUSED ManifestError submission cannot be substituted across occurrences
```

The campaign repair therefore **passes at the P0 intrinsic occurrence-bound binary-Brier ceiling**.
No residual intrinsic P0 was reproduced in the assigned target/occurrence/rule-dispatch scope.
Definitions and arithmetic remain caller-fed `UnverifiedSemantic` values: there is no durable
universe/evidence owner, sealed submission, mutual-blind reveal receipt, adjudication owner, score
artifact, ensemble qualification, or support decision.

### W6-T2-B3-R — research policy and evidence commitment passes

`DeskPolicy.content_digest()` covers the complete policy. `ResearchProposal` embeds that policy,
its digest, the full descriptor closure digest, and a commitment digest over the policy,
hypothesis lock, specification, descriptor bytes, authority, and claim scope
(`wave6_research_desk/contracts.py:205-223`, `411-469`). Construction requires each experiment's
artifact references to be within admitted evidence (`desk.py:77-84`). Ledger supersession requires
the exact commitment digest and orders review records after both proposals (`desk.py:146-177`).

Reproduction:

```text
SAME_POLICY_ID_DISTINCT_DIGEST True True True
IN_PLACE_POLICY_REPLACEMENT_REFUSED proposal policy digest does not match embedded policy content
BUDGET_SUPERSESSION_REFUSED an outcome-sensitive supersession cannot replace frozen policy, budget, evidence, or hypothesis
EVIDENCE_SUPERSESSION_REFUSED an outcome-sensitive supersession cannot replace frozen policy, budget, evidence, or hypothesis
UNADMITTED_EXPERIMENT_ARTIFACT_REFUSED experiment references an artifact outside admitted evidence closure
```

The assigned repair **passes at the P0 intrinsic, non-executable proposal ceiling**. The
`ResearchDeskLedger` remains a persistent value rather than a durable store; policy provenance,
descriptor provenance, and human dispositions are caller input. It therefore remains blocked
above that ceiling, but no residual intrinsic P0 was reproduced in the assigned repair scope.

### W6-T2-B4-R — versioned replay material and receipt binding pass

`materialize_replay` now refuses blinded material at or after reveal and aware material before
reveal. Each `ReplayEvidenceRef` carries a typed artifact identity, version, qualified content
digest, availability and knowledge clocks, and available commit sequence. The protocol fixes the
ordered blind/reveal material sets and both commit boundaries (`wave6_operator_model/contracts.py:
710-888`). `validate_replay_material` recomputes the protocol, scene/presentation binding, phase
cut/commit, evidence closure, material digest, receipt digest, and presentation boundary. Each
response names the receipt, material digest, and phase-receipt digest; comparison revalidates all
receipts and clocks (`contracts.py:891-1046`, `1115-1158`).

The earlier phase and structural probes still refuse:

```text
BLINDED_AFTER_REVEAL_REFUSED TemporalClosureError outcome-blinded response cannot occur at or after reveal
AWARE_BEFORE_REVEAL_REFUSED TemporalClosureError outcome-aware response cannot occur before reveal
PHASE_RECEIPT_SUBSTITUTION_REFUSED OperatorModelError recognition response phase does not match material receipt
MATERIAL_DIGEST_SUBSTITUTION_REFUSED OperatorModelError recognition response material digest does not match receipt
SCENE_SUBSTITUTION_REFUSED OperatorModelError replay receipt scene/presentation binding does not match protocol
```

The final same-ID version/content/commit and scene/presentation/material probes produced:

```text
EXACT_VERSIONED_MATERIAL_ACCEPTED sha256:3d197a4f8458f044081e6cd9d3d6b17ac14c417908345f335f54d8060a0819e4
SAME_ID_VERSION_SUBSTITUTION_REFUSED OperatorModelError replay evidence must exactly close the ordered typed material set
SAME_ID_CONTENT_SUBSTITUTION_REFUSED OperatorModelError replay evidence must exactly close the ordered typed material set
SAME_ID_COMMIT_SUBSTITUTION_REFUSED OperatorModelError replay evidence must exactly close the ordered typed material set
POST_CUT_COMMIT_REFUSED TemporalClosureError blind replay evidence commit exceeds blind_commit_seq
SCENE_SUBSTITUTION_REFUSED OperatorModelError replay receipt protocol digest does not match protocol
PRESENTATION_SUBSTITUTION_REFUSED OperatorModelError replay receipt protocol digest does not match protocol
RESPONSE_MATERIAL_SUBSTITUTION_REFUSED OperatorModelError recognition response material digest does not match receipt
```

The repair **passes at the P0 intrinsic versioned/content-addressed replay ceiling**. No residual
intrinsic P0 was reproduced in the assigned timing, receipt, scene, presentation, or material
substitution scope. The content digest proves only equality to caller-supplied canonical identity;
it does not prove that a store resolved those bytes, a renderer presented them, or a human viewed
or comprehended them. Those durable claims remain blocked exactly as the implementation document
discloses.

### W6-T2-B5-R — atlas future-null isolation and native identity binding pass

Selection now precedes payload validation, so a future-ineligible malformed price payload no
longer changes an earlier artifact. Selected native wallet/caller/topology identity and version
fields are cross-bound to generic component identity (`wave6_market_atlas/atlas.py:173-220`,
`354-368`). The original assigned attacks now fail or remain isolated:

```text
FUTURE_PAYLOAD_POISON_CLOSED True True
NATIVE_COMPONENT_DIVERGENCE_REFUSED wallet_cluster_flow component identity diverges from its native wallet_id
```

The final residual repair separates nonnullable raw knowledge/commit gating from nullable semantic
validity. `_known_by_cut` first touches only availability, commit, and retraction metadata. Only a
row known at the cut reaches `_validate_validity_index`, and only a valid row applicable to the
state time reaches payload and identity validation (`atlas.py:205-212`, `325-350`, `380-394`). A
future-known row with null `valid_lower` and malformed price payload is therefore absent—not a gap
or accepted component—at the earlier cut, but refuses when its knowledge/commit boundary is
selected:

```text
FUTURE_NULL_NO_ROW_EARLY True
FUTURE_NULL_EARLY_SNAPSHOTS_IDENTICAL True
FUTURE_NULL_EARLY_TRAJECTORIES_IDENTICAL True
FUTURE_NULL_SELECTED_REFUSED ManifestError canonical_venue_state.valid_lower must be an aware UTC timestamp
```

Combined with the earlier native/component substitution refusal, the atlas repair **passes at the
P0 intrinsic point-in-time projection ceiling over supplied exact-schema rows**. No residual
intrinsic P0 was reproduced in the assigned temporal/native-identity scope. The source IDs,
versions, events, availability and retraction clocks, commit sequences, coverage assertions, and
payloads remain caller-fed; without a resolving store the output is not a durable source snapshot,
coverage closure, or reliable empirical trajectory.

### W6-T2-B2-R — active-sensing floor and report identity repair passes

`admit_sensing_decision` now binds the exact experiment/baseline/study digests, registered
denominator, assignment-unit and public-subject eligibility, study cell, arm probability, arm
policy digest, and required reason lineage (`wave6_active_sensing/engine.py:127-203`). For every
request, a protected assignment must resolve to a registered member of the exact floor and
source-operation; a candidate may not consume a protected member (`engine.py:228-255`). A manual
enum and operator-shaped reason can no longer make a nonmember consume the manual reserve.

`admit_coverage_report` re-admits every supplied assignment against the report's exact registration,
constructs the expected outcome fields from the sealed artifact, requires exact assignment
occurrence closure, compares all assignment identity/class/policy/denominator/subject fields, and
requires ordered equality with the registered denominator occurrences (`engine.py:341-426`).

Fresh reproduction of the original and expanded attacks:

```text
NONMEMBER_MANUAL_FLOOR_REFUSED SemanticRefusal subject is not a registered manual floor member
CROSS_EXPERIMENT_ASSIGNMENT_REFUSED SemanticRefusal sensing decision names a different experiment
OUTCOME_RECODE_REFUSED SemanticRefusal outcome recodes sealed assignment fields: ['arm_id', 'assignment_artifact_digest', 'assignment_artifact_id', 'assignment_kind', 'assignment_unit_key', 'denominator_digest', 'policy_digest', 'public_subject_key', 'study_cell']
INVENTED_DENOMINATOR_OCCURRENCE_REFUSED SemanticRefusal coverage report occurrence IDs are not exact denominator closure
INVENTED_SUBJECT_REFUSED SemanticRefusal sensing assignment unit is outside the registered eligible universe
INVENTED_ASSIGNMENT_OCCURRENCE_REFUSED SemanticRefusal coverage report omits, replaces, or invents an assigned unit
```

The repair **passes at the P0 intrinsic fixed-registration assignment/report ceiling**. No residual
intrinsic P0 was reproduced in the assigned scope. This does not promote the artifacts: registration
membership, operator/model lineage, acceptance IDs, budgets, assignments, outcomes, and clocks are
still caller-provided `UnverifiedSemantic` values. There is no durable registry, cross-report
cumulative ledger, provider application receipt, human-attention proof, VOI qualification, or
causal result, so the lane remains blocked at `store_resolved` and above.

## Verification facts

Focused repaired-lane gates:

```text
uv --directory analysis run --locked pytest -q tests/wave6_epistemic_campaigns
PASS: 12 tests

uv --directory analysis run --locked pytest -q tests/wave6_research_desk
PASS: 14 tests

uv --directory analysis run --locked pytest -q tests/wave6_market_atlas
PASS: 11 tests

uv --directory analysis run --locked pytest -q tests/wave6_operator_model
PASS: 10 tests

uv --directory analysis run --locked pytest -q tests/wave6_active_sensing
PASS: 16 tests

uv --directory analysis run --locked ruff check <each repaired package and focused test path>
PASS: All checks passed for all five repaired lanes
```

The final combined campaign/atlas/operator residual gate passed 33 tests. Research desk and active
sensing retained their earlier 14-test and 16-test passing gates. Total focused collection: 63.

Green tests establish intended fixtures. The custom adversarial runs above determine the stronger
ceiling. No production files or tests were edited, and no commit was made.

## Final boundary

- **Research desk: PASS** its assigned P0 policy-budget/evidence commitment repair at the intrinsic
  non-executable proposal ceiling; **BLOCKED** durable review and every downstream research claim.
- **Campaigns: PASS** target/occurrence identity and typed binary-Brier dispatch at the intrinsic
  arithmetic ceiling; **BLOCKED** every durable campaign, adjudication, score, and support claim.
- **Operator model: PASS** phase timing and version/content/commit/scene/presentation/material
  binding at the intrinsic replay ceiling; **BLOCKED** durable rendering, viewing, recognition,
  and reconciliation claims.
- **Market atlas: PASS** future-null/payload isolation and observed native identity binding at the
  intrinsic point-in-time projection ceiling; **BLOCKED** durable source, coverage, and trajectory
  claims.
- **Active sensing: PASS** protected-floor and exact assignment/report closure at the intrinsic
  fixed-registration ceiling; **BLOCKED** every durable, provider, qualification, and causal claim.

The highest honest tranche-two statement after these reruns is:

```text
Wave 6 tranche two contains deterministic caller-fed DTO and arithmetic probes.
All five repaired lanes pass the assigned P0 intrinsic-contract adversaries: research policy and
evidence commitment; campaign occurrence identity and binary-Brier dispatch; operator phase and
versioned replay-material closure; atlas future-null selection and native identity; and active-
sensing protected selection/report lineage.
No residual intrinsic P0 was reproduced in those assigned scopes.
Every durable identity, receipt, review, support, coverage, and resolution claim still requires
a store-resolved owner.
```
