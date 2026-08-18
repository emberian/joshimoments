from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from joshi_analysis.canonical import qualified_sha256_bytes
from joshi_analysis.wave6_operator_model import (
    ActKind,
    AssertionRole,
    ClockPair,
    ComponentAssertion,
    ComponentBundle,
    ComponentKind,
    CoverageStatus,
    IntentionKind,
    OntologyAssignment,
    OntologyRelation,
    OntologyRelationKind,
    OntologyStatus,
    OntologyTerm,
    OperatorAct,
    OperatorModelError,
    RawOperatorAssertion,
    RecognitionKind,
    RecognitionResponse,
    ReconciledEconomicEffect,
    RelationScope,
    ReplayArtifactType,
    ReplayEvidenceRef,
    ReplayEvidenceRole,
    ReplayMaterialReceipt,
    ReplayPhase,
    ReplayProtocol,
    ResponseState,
    SceneBinding,
    StatedIntention,
    TemporalClosureError,
    TypedGap,
    compare_recognition,
    materialize_replay,
    validate_replay_material,
)

T0 = datetime(2026, 8, 18, 12, tzinfo=UTC)
DIGEST = qualified_sha256_bytes(b"witnessed")


def _binding(*, gap: bool = False, available_at: datetime = T0) -> SceneBinding:
    return SceneBinding(
        scene_id="scene:001",
        scene_version_id="scene:001:v1",
        scene_digest=DIGEST,
        scene_commit_seq=101,
        view_id="view:001",
        view_version_id="view:001:v1",
        view_digest=qualified_sha256_bytes(b"view:001:v1"),
        view_commit_seq=102,
        presentation_occurrence_id=None if gap else "presentation:001",
        presentation_version_id=None if gap else "presentation:001:v1",
        presentation_digest=None if gap else DIGEST,
        presentation_commit_seq=None if gap else 103,
        presentation_gap=(
            TypedGap(
                "gap:presentation:001",
                "gap:presentation:001:v1",
                qualified_sha256_bytes(b"gap:presentation:001:v1"),
                104,
                "viewport_not_witnessed",
                available_at,
            )
            if gap
            else None
        ),
        choice_context_id="choice:001",
        choice_context_version_id="choice:001:v1",
        choice_context_digest=qualified_sha256_bytes(b"choice:001:v1"),
        choice_context_commit_seq=105,
        clocks=ClockPair(T0 - timedelta(seconds=1), available_at),
    )


def _raw(**changes: object) -> RawOperatorAssertion:
    values: dict[str, object] = {
        "assertion_id": "assertion:001",
        "subject_id": "subject:001",
        "operator_id": "ember",
        "episode_id": "episode:001",
        "binding": _binding(),
        "asserted_at": T0,
        "referred_to": ClockPair(T0 - timedelta(seconds=1), T0),
        "knowledge_cut": T0,
        "elicitation_mode": "nonblocking_diary",
        "prompt_text": "What mattered?",
        "prompt_order": 0,
        "machine_suggestion_visible": False,
        "response_state": ResponseState.VERBATIM,
        "raw_bytes": b"thin silence, maybe",
    }
    values.update(changes)
    return RawOperatorAssertion(**values)  # type: ignore[arg-type]


def _component(
    component_id: str, *, cut: datetime = T0, unit: str = "base_atoms"
) -> ComponentAssertion:
    return ComponentAssertion(
        component_id=component_id,
        kind=ComponentKind.TIMING_SIZE,
        assertion_role=AssertionRole.OPERATOR_ASSERTION,
        raw_assertion_id="assertion:001",
        evidence_ref_ids=("evidence:001",),
        clocks=ClockPair(T0 - timedelta(seconds=1), T0),
        knowledge_cut=cut,
        coverage=CoverageStatus.OBSERVED,
        asset_id="asset:base",
        unit=unit,
        reference_measure="exact_atoms_at_route",
        topology_profile="dlmm:profile:001",
        claim_bytes=b"size mattered",
    )


def test_raw_capture_preserves_verbatim_opaque_ambiguity_and_append_only_correction() -> None:
    original = _raw()
    assert original.raw_digest == qualified_sha256_bytes(b"thin silence, maybe")
    assert original.artifact_digest == _raw().artifact_digest
    with pytest.raises(FrozenInstanceError):
        original.raw_bytes = b"rewritten"  # type: ignore[misc]

    opaque = _raw(
        assertion_id="assertion:opaque",
        response_state=ResponseState.OPAQUE_TOKEN,
        raw_bytes=None,
        opaque_token="token:operator-private:01",
    )
    ambiguous = _raw(
        assertion_id="assertion:ambiguous",
        response_state=ResponseState.AMBIGUOUS,
        raw_bytes=b"could be absorption or just silence",
    )
    corrected = _raw(
        assertion_id="assertion:correction",
        correction_of_assertion_id=original.assertion_id,
        raw_bytes=b"correction is a new contemporaneous statement",
    )
    assert opaque.raw_digest is None
    assert ambiguous.response_state is ResponseState.AMBIGUOUS
    assert corrected.correction_of_assertion_id == original.assertion_id
    with pytest.raises(OperatorModelError, match="cannot correct itself"):
        _raw(correction_of_assertion_id="assertion:001")


def test_future_scene_and_component_evidence_fail_closed() -> None:
    with pytest.raises(TemporalClosureError, match="binding was unavailable"):
        _raw(binding=_binding(available_at=T0 + timedelta(microseconds=1)))
    with pytest.raises(TemporalClosureError, match="component evidence was unavailable"):
        _component("component:001", cut=T0 - timedelta(microseconds=1))
    with pytest.raises(TemporalClosureError, match="future component"):
        ComponentBundle(
            "bundle:001",
            _binding(),
            T0 - timedelta(microseconds=1),
            (_component("component:001"),),
        )


def test_scene_requires_a_point_in_time_presentation_occurrence_or_typed_gap() -> None:
    gap_binding = _binding(gap=True)
    assert gap_binding.presentation_gap is not None
    with pytest.raises(OperatorModelError, match="exactly one presentation"):
        SceneBinding(
            scene_id="scene:002",
            scene_version_id="scene:002:v1",
            scene_digest=DIGEST,
            scene_commit_seq=201,
            view_id="view:002",
            view_version_id="view:002:v1",
            view_digest=DIGEST,
            view_commit_seq=202,
            presentation_occurrence_id=None,
            presentation_version_id=None,
            presentation_digest=None,
            presentation_commit_seq=None,
            presentation_gap=None,
            choice_context_id=None,
            choice_context_version_id=None,
            choice_context_digest=None,
            choice_context_commit_seq=None,
            clocks=ClockPair(T0, T0),
        )
    with pytest.raises(OperatorModelError, match="cannot manufacture"):
        SceneBinding(
            scene_id="scene:003",
            scene_version_id="scene:003:v1",
            scene_digest=DIGEST,
            scene_commit_seq=301,
            view_id="view:003",
            view_version_id="view:003:v1",
            view_digest=DIGEST,
            view_commit_seq=302,
            presentation_occurrence_id=None,
            presentation_version_id=None,
            presentation_digest=DIGEST,
            presentation_commit_seq=None,
            presentation_gap=TypedGap(
                "gap:003",
                "gap:003:v1",
                qualified_sha256_bytes(b"gap:003:v1"),
                303,
                "missing",
                T0,
            ),
            choice_context_id=None,
            choice_context_version_id=None,
            choice_context_digest=None,
            choice_context_commit_seq=None,
            clocks=ClockPair(T0, T0),
        )


def test_bundle_is_heterogeneous_and_has_no_scalar_pressure_escape_hatch() -> None:
    timing = _component("component:001", unit="base_atoms")
    social = ComponentAssertion(
        component_id="component:002",
        kind=ComponentKind.SOCIAL_ATTENTION,
        assertion_role=AssertionRole.HYPOTHESIS,
        raw_assertion_id=None,
        evidence_ref_ids=("evidence:002",),
        clocks=ClockPair(T0 - timedelta(seconds=1), T0),
        knowledge_cut=T0,
        coverage=CoverageStatus.PARTIAL,
        asset_id="asset:base",
        unit="post_revision_bytes",
        reference_measure="source_revision",
        topology_profile="surface:feed:001",
        claim_bytes=b"caller identity uncertain",
    )
    bundle = ComponentBundle("bundle:001", _binding(), T0, (timing, social))
    assert bundle.components[0].unit != bundle.components[1].unit
    assert not hasattr(bundle, "pressure")
    with pytest.raises(TypeError, match="pressure"):
        ComponentBundle("bundle:scalar", _binding(), T0, (timing,), pressure=1)  # type: ignore[call-arg]
    with pytest.raises(OperatorModelError, match="requires asset, unit"):
        ComponentAssertion(
            "component:bad",
            ComponentKind.COMPRESSION_RELEASE,
            AssertionRole.HYPOTHESIS,
            None,
            (),
            ClockPair(T0, T0),
            T0,
            CoverageStatus.OBSERVED,
            "asset:base",
            None,
            "curve",
            "pool",
            b"compression?",
        )


def test_acts_intentions_and_effects_cannot_be_conflated() -> None:
    act = OperatorAct("act:001", ActKind.MARK, _binding(), T0, T0, "assertion:001")
    intention = StatedIntention(
        "intent:001",
        IntentionKind.DESIRED_EXPOSURE,
        act.act_id,
        "assertion:001",
        _binding(),
        T0,
        T0,
        b"small only",
    )
    effect = ReconciledEconomicEffect(
        "effect:001",
        "chain-observation:001",
        "reconciliation:001",
        "boundary:household:001",
        T0,
        T0,
        (("asset:base", -11), ("asset:quote", 23)),
        DIGEST,
        (act.act_id,),
    )
    assert intention.raw_assertion_id != effect.reconciliation_id
    assert effect.related_act_ids == (act.act_id,)
    assert "effect" not in StatedIntention.__dataclass_fields__
    with pytest.raises(OperatorModelError, match="reconciled asset deltas"):
        ReconciledEconomicEffect(
            "effect:empty", "chain:2", "recon:2", "boundary:2", T0, T0, (), DIGEST
        )


def test_ontology_is_versioned_multivalued_and_branching_not_forced_taxonomy() -> None:
    old = OntologyTerm(
        "term:compression",
        "term:compression:v1",
        "compression",
        b"old words",
        T0,
        T0,
        "diary_review",
        OntologyStatus.SPLIT,
        "stance",
    )
    left = OntologyTerm(
        "term:absorption",
        "term:absorption:v1",
        "absorption",
        b"left",
        T0,
        T0,
        "diary_review",
        OntologyStatus.ACTIVE,
        "stance",
    )
    right = OntologyTerm(
        "term:thin",
        "term:thin:v1",
        "thin silence",
        b"right",
        T0,
        T0,
        "diary_review",
        OntologyStatus.ACTIVE,
        "stance",
    )
    retired = OntologyTerm(
        "term:retired",
        "term:retired:v1",
        "old phrase",
        b"old",
        T0,
        T0,
        "diary_review",
        OntologyStatus.RETIRED,
        "stance",
    )
    split = OntologyRelation(
        "relation:split:001",
        OntologyRelationKind.SPLIT_INTO,
        (old.version_id,),
        (left.version_id, right.version_id),
        RelationScope.PHENOMENOLOGICAL,
        b"distinctions separated in blind replay",
        T0,
    )
    merged = OntologyRelation(
        "relation:merge:001",
        OntologyRelationKind.MERGED_FROM,
        (left.version_id, right.version_id),
        ("term:combined:v2",),
        RelationScope.MODEL_HARMONIZATION,
        b"retrieval-only harmonization",
        T0,
    )
    assignment = OntologyAssignment(
        "assignment:001",
        "assertion:001",
        (left.version_id, right.version_id),
        "reviewer:001",
        T0,
        T0,
        True,
    )
    assert retired.status is OntologyStatus.RETIRED
    assert split.kind is OntologyRelationKind.SPLIT_INTO
    assert merged.kind is OntologyRelationKind.MERGED_FROM
    assert len(assignment.assigned_version_ids) == 2
    with pytest.raises(OperatorModelError, match="explicitly be ambiguous"):
        OntologyAssignment("assignment:none", "assertion:001", (), "reviewer:001", T0, T0, False)


def _replay_evidence(
    artifact_type: ReplayArtifactType,
    artifact_id: str,
    *,
    available_at: datetime,
    knowledge_cut: datetime,
    content: bytes,
    commit_seq: int,
) -> ReplayEvidenceRef:
    roles = {
        ReplayArtifactType.SCENE_COMPONENT_PROJECTION: ReplayEvidenceRole.SCENE_COMPONENT,
        ReplayArtifactType.PRESENTATION_OCCURRENCE: ReplayEvidenceRole.PRESENTATION,
        ReplayArtifactType.OPERATOR_ACT: ReplayEvidenceRole.ACT,
        ReplayArtifactType.RAW_OPERATOR_ASSERTION: ReplayEvidenceRole.OPERATOR_ASSERTION,
        ReplayArtifactType.RECONCILED_ECONOMIC_EFFECT: ReplayEvidenceRole.ECONOMIC_EFFECT,
        ReplayArtifactType.OUTCOME: ReplayEvidenceRole.OUTCOME,
    }
    return ReplayEvidenceRef(
        artifact_type,
        artifact_id,
        f"{artifact_id}:v1",
        qualified_sha256_bytes(content),
        roles[artifact_type],
        available_at,
        knowledge_cut,
        commit_seq,
    )


def _replay_protocol() -> ReplayProtocol:
    blind = _replay_evidence(
        ReplayArtifactType.SCENE_COMPONENT_PROJECTION,
        "scene-component:001",
        available_at=T0,
        knowledge_cut=T0,
        content=b"scene-component:001:v1",
        commit_seq=401,
    )
    outcome = _replay_evidence(
        ReplayArtifactType.OUTCOME,
        "outcome:001",
        available_at=T0 + timedelta(hours=1),
        knowledge_cut=T0 + timedelta(hours=1),
        content=b"outcome:001:v1",
        commit_seq=402,
    )
    return ReplayProtocol(
        "replay:001",
        _binding(),
        "act:001",
        T0,
        500,
        T0 + timedelta(days=1),
        600,
        (blind,),
        (outcome,),
        b"What stands out?",
        "presentation-policy:neutral:001",
    )


def _blind_receipt(protocol: ReplayProtocol) -> ReplayMaterialReceipt:
    return materialize_replay(
        protocol,
        receipt_id="receipt:blind:001",
        phase=ReplayPhase.OUTCOME_BLINDED,
        presented_at=T0,
        evidence=protocol.blinded_refs,
    )


def _aware_receipt(protocol: ReplayProtocol) -> ReplayMaterialReceipt:
    return materialize_replay(
        protocol,
        receipt_id="receipt:aware:001",
        phase=ReplayPhase.OUTCOME_AWARE,
        presented_at=T0 + timedelta(days=1),
        evidence=protocol.blinded_refs + protocol.revealed_refs,
    )


def _response(
    receipt: ReplayMaterialReceipt,
    *,
    response_id: str,
    responded_at: datetime,
    phase: ReplayPhase | None = None,
    material_digest: str | None = None,
    phase_receipt_digest: str | None = None,
) -> RecognitionResponse:
    return RecognitionResponse(
        response_id,
        "replay:001",
        receipt.phase if phase is None else phase,
        RecognitionKind.UNCERTAIN,
        responded_at,
        receipt.receipt_id,
        receipt.material_digest if material_digest is None else material_digest,
        receipt.phase_receipt_digest if phase_receipt_digest is None else phase_receipt_digest,
        "assertion:001",
        b"not enough witness",
        "assignment:001",
        True,
    )


def test_outcome_blinded_replay_rejects_future_and_never_treats_assignment_as_truth() -> None:
    protocol = _replay_protocol()
    future = _replay_evidence(
        ReplayArtifactType.SCENE_COMPONENT_PROJECTION,
        "scene-component:001",
        available_at=T0 + timedelta(seconds=1),
        knowledge_cut=T0 + timedelta(seconds=1),
        content=b"scene-component:001:v1",
        commit_seq=401,
    )
    future_protocol = replace(protocol, blinded_refs=(future,))
    with pytest.raises(TemporalClosureError, match="unavailable at blind_cut"):
        materialize_replay(
            future_protocol,
            receipt_id="receipt:future",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=T0,
            evidence=future_protocol.blinded_refs,
        )
    effect = _replay_evidence(
        ReplayArtifactType.RECONCILED_ECONOMIC_EFFECT,
        "effect:001",
        available_at=T0,
        knowledge_cut=T0,
        content=b"effect:001:v1",
        commit_seq=403,
    )
    effect_protocol = replace(protocol, blinded_refs=(effect,))
    with pytest.raises(OperatorModelError, match="cannot include an economic effect"):
        materialize_replay(
            effect_protocol,
            receipt_id="receipt:effect",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=T0,
            evidence=effect_protocol.blinded_refs,
        )
    blind = _blind_receipt(protocol)
    aware = _aware_receipt(protocol)
    validate_replay_material(protocol, blind)
    validate_replay_material(protocol, aware)
    responses = (
        _response(blind, response_id="recognition:001", responded_at=T0),
        RecognitionResponse(
            "recognition:002",
            protocol.protocol_id,
            ReplayPhase.OUTCOME_AWARE,
            RecognitionKind.RECOGNIZES,
            T0 + timedelta(days=1),
            aware.receipt_id,
            aware.material_digest,
            aware.phase_receipt_digest,
            "assertion:002",
            b"after reveal",
            "assignment:002",
        ),
    )
    comparison = compare_recognition(protocol, (blind, aware), responses)
    assert comparison.counts == (
        (RecognitionKind.RECOGNIZES, 1),
        (RecognitionKind.DOES_NOT_RECOGNIZE, 0),
        (RecognitionKind.UNCERTAIN, 1),
        (RecognitionKind.CANNOT_RECONSTRUCT, 0),
    )
    assert "not_label_truth" in comparison.claim_scope


def test_recognition_phase_is_closed_to_reveal_and_presentation_times() -> None:
    protocol = _replay_protocol()
    blind = _blind_receipt(protocol)
    aware = _aware_receipt(protocol)
    assert protocol.reveal_cut is not None

    with pytest.raises(TemporalClosureError, match="at or after reveal"):
        compare_recognition(
            protocol,
            (blind,),
            (_response(blind, response_id="recognition:late", responded_at=protocol.reveal_cut),),
        )
    with pytest.raises(TemporalClosureError, match="before reveal"):
        compare_recognition(
            protocol,
            (aware,),
            (
                _response(
                    aware,
                    response_id="recognition:early",
                    responded_at=protocol.reveal_cut - timedelta(microseconds=1),
                ),
            ),
        )
    with pytest.raises(OperatorModelError, match="material digest does not match"):
        compare_recognition(
            protocol,
            (blind,),
            (
                _response(
                    blind,
                    response_id="recognition:material-substitution",
                    responded_at=T0,
                    material_digest=qualified_sha256_bytes(b"other material"),
                ),
            ),
        )
    wrong_scene = replace(blind, binding_digest=qualified_sha256_bytes(b"other scene"))
    with pytest.raises(OperatorModelError, match="scene/presentation binding does not match"):
        compare_recognition(
            protocol,
            (wrong_scene,),
            (
                _response(
                    wrong_scene,
                    response_id="recognition:scene-substitution",
                    responded_at=T0,
                ),
            ),
        )
    with pytest.raises(OperatorModelError, match="receipt outside comparison"):
        compare_recognition(
            protocol,
            (blind,),
            (
                _response(
                    aware,
                    response_id="recognition:foreign-receipt",
                    responded_at=aware.presented_at,
                ),
            ),
        )
    with pytest.raises(
        TemporalClosureError, match="material cannot be presented at or after reveal"
    ):
        materialize_replay(
            protocol,
            receipt_id="receipt:late-blind",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=protocol.reveal_cut,
            evidence=protocol.blinded_refs,
        )
    with pytest.raises(TemporalClosureError, match="material cannot be presented before reveal"):
        materialize_replay(
            protocol,
            receipt_id="receipt:early-aware",
            phase=ReplayPhase.OUTCOME_AWARE,
            presented_at=protocol.reveal_cut - timedelta(microseconds=1),
            evidence=protocol.blinded_refs + protocol.revealed_refs,
        )


def test_recognition_requires_exact_phase_receipt_scene_and_material_identity() -> None:
    protocol = _replay_protocol()
    blind = _blind_receipt(protocol)
    with pytest.raises(OperatorModelError, match="phase does not match material receipt"):
        compare_recognition(
            protocol,
            (blind,),
            (
                _response(
                    blind,
                    response_id="recognition:phase-substitution",
                    responded_at=T0,
                    phase=ReplayPhase.OUTCOME_AWARE,
                ),
            ),
        )


def test_replay_material_is_closed_to_artifact_version_and_canonical_content_digest() -> None:
    protocol = _replay_protocol()
    exact = _blind_receipt(protocol)
    validate_replay_material(protocol, exact)
    assert exact.evidence == protocol.blinded_refs

    same_id_new_version = replace(protocol.blinded_refs[0], version_id="scene-component:001:v2")
    with pytest.raises(OperatorModelError, match="ordered typed material set"):
        materialize_replay(
            protocol,
            receipt_id="receipt:version-substitution",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=T0,
            evidence=(same_id_new_version,),
        )
    same_id_new_content = replace(
        protocol.blinded_refs[0], content_digest=qualified_sha256_bytes(b"other canonical bytes")
    )
    with pytest.raises(OperatorModelError, match="ordered typed material set"):
        materialize_replay(
            protocol,
            receipt_id="receipt:content-substitution",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=T0,
            evidence=(same_id_new_content,),
        )
    same_id_late_commit = replace(protocol.blinded_refs[0], available_commit_seq=501)
    late_commit_protocol = replace(protocol, blinded_refs=(same_id_late_commit,))
    with pytest.raises(TemporalClosureError, match="commit exceeds blind_commit_seq"):
        materialize_replay(
            late_commit_protocol,
            receipt_id="receipt:commit-substitution",
            phase=ReplayPhase.OUTCOME_BLINDED,
            presented_at=T0,
            evidence=late_commit_protocol.blinded_refs,
        )

    changed_scene = replace(
        protocol.binding,
        scene_version_id="scene:001:v2",
        scene_digest=qualified_sha256_bytes(b"scene:001:v2 canonical bytes"),
    )
    changed_presentation = replace(
        protocol.binding,
        presentation_version_id="presentation:001:v2",
        presentation_digest=qualified_sha256_bytes(b"presentation:001:v2 canonical bytes"),
    )
    for changed_binding in (changed_scene, changed_presentation):
        with pytest.raises(OperatorModelError, match="protocol digest does not match"):
            validate_replay_material(replace(protocol, binding=changed_binding), exact)
