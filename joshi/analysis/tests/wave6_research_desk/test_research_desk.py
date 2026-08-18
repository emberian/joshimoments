from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from joshi_analysis.errors import CoverageError, ManifestError, TemporalLeakageError
from joshi_analysis.wave6_research_desk import (
    AUTHORITY,
    ArtifactDescriptor,
    ArtifactRole,
    Control,
    CoverageStatus,
    DeskPolicy,
    DispositionKind,
    Estimand,
    ExperimentManifest,
    Falsifier,
    Feature,
    ProposalKind,
    ProposalSpec,
    ResearchDeskLedger,
    human_disposition,
    propose,
    supersession,
)

BASE = datetime(2026, 8, 1, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def policy() -> DeskPolicy:
    return DeskPolicy(
        "desk-policy-1",
        BASE + timedelta(hours=2),
        950_000,
        (),
        "token_atoms",
        "topology-1",
        "topology-v1",
        3,
        2,
        10,
        15,
    )


def descriptor(**changes: object) -> ArtifactDescriptor:
    base = ArtifactDescriptor(
        "artifact-1",
        ArtifactRole.DESIGN,
        BASE,
        BASE + timedelta(minutes=1),
        1,
        DIGEST,
        CoverageStatus.COMPLETE,
        1_000_000,
        (),
        "token_atoms",
        "topology-1",
        "topology-v1",
    )
    return replace(base, **changes)


def spec(**changes: object) -> ProposalSpec:
    base = ProposalSpec(
        ProposalKind.ESTIMAND,
        "predeclared response study",
        "pre-cut topology predicts subsequent signed flow",
        ("artifact-1",),
        Estimand(
            "mean-flow", "signed flow atoms", "eligible anchors", "signed_flow", "token_atoms"
        ),
        (Control("venue", "frozen venue id", "separate venues"),),
        (Feature("topology-degree", "degree at as-of cutoff", "count"),),
        ("reverse timing association",),
        (Falsifier("placebo-time", "no association after time permutation", "reject hypothesis"),),
        (ExperimentManifest("exp-1", "bounded offline review", ("artifact-1",), 5),),
    )
    return replace(base, **changes)


def proposal(**changes: object):
    values = {
        "policy": policy(),
        "specification": spec(),
        "descriptors": (descriptor(),),
        "created_at": BASE + timedelta(minutes=3),
        "hypothesis_locked_at": BASE + timedelta(minutes=2),
    }
    values.update(changes)
    return propose(**values)


def test_proposal_is_deterministic_immutable_and_explicitly_non_authoritative() -> None:
    first, second = proposal(), proposal()
    assert first == second
    assert first.authority == AUTHORITY
    assert first.as_dict()["claim_scope"].endswith("not_result_or_live_decision")
    assert first.as_dict()["specification"]["experiments"][0]["query_count"] == 0
    assert first.as_dict()["policy"]["max_experiment_units"] == 10
    assert first.policy_digest == first.policy.content_digest()
    assert first.commitment_digest.startswith("sha256:")
    assert first.evidence_closure_digest.startswith("sha256:")


@pytest.mark.parametrize(
    ("changed", "error"),
    [
        ({"available_at": BASE + timedelta(hours=3)}, TemporalLeakageError),
        ({"role": ArtifactRole.OUTCOME}, TemporalLeakageError),
        ({"coverage_status": CoverageStatus.PARTIAL}, CoverageError),
        ({"gap_ids": ("gap-1",)}, CoverageError),
        ({"unit": "usd"}, ManifestError),
        ({"topology_version_id": "topology-v2"}, ManifestError),
    ],
)
def test_admission_fails_closed_for_future_coverage_gap_unit_and_topology(
    changed: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        proposal(descriptors=(descriptor(**changed),))


def test_missing_denominator_controls_and_budget_escape_are_rejected() -> None:
    with pytest.raises(ManifestError, match="control"):
        proposal(specification=spec(controls=()))
    with pytest.raises(ManifestError, match="denominator"):
        proposal(specification=spec(estimand=Estimand("x", "n", "", "outcome", "token_atoms")))
    with pytest.raises(ManifestError, match="resource"):
        proposal(
            specification=spec(
                experiments=(ExperimentManifest("exp-1", "bounded review", ("artifact-1",), 16),)
            )
        )


def test_experiment_cannot_reference_an_artifact_outside_the_admitted_closure() -> None:
    with pytest.raises(ManifestError, match="admitted evidence closure"):
        proposal(
            specification=spec(
                experiments=(
                    ExperimentManifest("exp-1", "bounded review", ("artifact-unadmitted",), 1),
                )
            )
        )
    with pytest.raises(ManifestError, match="execute"):
        proposal(
            specification=spec(
                experiments=(
                    ExperimentManifest(
                        "exp-1", "bounded review", ("artifact-1",), 1, executable=True
                    ),
                )
            )
        )


def test_append_only_human_review_rejects_duplicates_and_outcome_targeted_edit() -> None:
    original = proposal()
    ledger = ResearchDeskLedger().append_proposal(original)
    disposition = human_disposition(
        original.proposal_id,
        DispositionKind.HOLD,
        "human-1",
        BASE + timedelta(minutes=4),
        "await independent review",
    )
    reviewed = ledger.append_disposition(disposition)
    assert ledger.dispositions == ()
    assert reviewed.dispositions == (disposition,)
    with pytest.raises(ManifestError, match="duplicate proposal"):
        reviewed.append_proposal(original)

    changed = proposal(specification=spec(hypothesis="post-outcome edited hypothesis"))
    revised = reviewed.append_proposal(changed)
    with pytest.raises(ManifestError, match="outcome-sensitive"):
        revised.append_revision(
            supersession(
                original.proposal_id,
                changed.proposal_id,
                "human-1",
                BASE + timedelta(minutes=5),
                "revision",
            )
        )


def test_authority_laundering_and_duplicate_ids_cannot_validate() -> None:
    item = proposal()
    with pytest.raises(ManifestError, match="authority"):
        replace(item, authority="may_trade").validate()
    duplicated = (descriptor(), replace(descriptor(), artifact_id="artifact-1"))
    with pytest.raises(ManifestError, match="duplicate"):
        proposal(
            specification=spec(artifact_ids=("artifact-1", "artifact-1")),
            descriptors=duplicated,
        )


@pytest.mark.parametrize("replacement", ["policy", "evidence"])
def test_supersession_refuses_same_id_budget_or_evidence_replacement(
    replacement: str,
) -> None:
    original = proposal()
    if replacement == "policy":
        successor = proposal(
            policy=replace(policy(), max_experiment_units=50, max_total_experiment_units=50),
            specification=spec(
                experiments=(ExperimentManifest("exp-1", "larger proposal", ("artifact-1",), 50),)
            ),
        )
        assert successor.policy_id == original.policy_id
        assert successor.policy_digest != original.policy_digest
        assert successor.commitment_digest != original.commitment_digest
        with pytest.raises(ManifestError, match="policy digest"):
            replace(original, policy=successor.policy).validate()
    else:
        successor = proposal(descriptors=(descriptor(provenance_digest="sha256:" + "b" * 64),))
        assert successor.evidence_closure_digest != original.evidence_closure_digest
        assert successor.commitment_digest != original.commitment_digest
        with pytest.raises(ManifestError, match="evidence closure"):
            replace(original, artifact_descriptors=successor.artifact_descriptors).validate()

    ledger = ResearchDeskLedger().append_proposal(original).append_proposal(successor)
    with pytest.raises(ManifestError, match="outcome-sensitive"):
        ledger.append_revision(
            supersession(
                original.proposal_id,
                successor.proposal_id,
                "human-1",
                BASE + timedelta(minutes=4),
                "attempt to replace frozen continuation inputs",
            )
        )


def test_human_review_and_revision_cannot_predate_the_proposals() -> None:
    original = proposal()
    ledger = ResearchDeskLedger().append_proposal(original)
    early_disposition = human_disposition(
        original.proposal_id,
        DispositionKind.HOLD,
        "human-1",
        BASE + timedelta(minutes=2),
        "too early",
    )
    with pytest.raises(TemporalLeakageError, match="predates"):
        ledger.append_disposition(early_disposition)

    successor = proposal(created_at=BASE + timedelta(minutes=5))
    ledger = ledger.append_proposal(successor)
    with pytest.raises(TemporalLeakageError, match="predates"):
        ledger.append_revision(
            supersession(
                original.proposal_id,
                successor.proposal_id,
                "human-1",
                BASE + timedelta(minutes=4),
                "too early",
            )
        )
