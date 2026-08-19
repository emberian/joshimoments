from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.wave6_operator_model import (
    MODEL_ADMISSION_REFUSAL,
    StoreOperatorEvidenceError,
    validate_store_operator_evidence_report,
)


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()


def _digest(label: str) -> str:
    return qualified_sha256_bytes(label.encode())


def _valid_report() -> dict[str, Any]:
    program = "w6-program-fixture-001"
    census = "wave6-input-census:" + "1" * 64
    source = "source-c0:" + "2" * 64
    publication_id = "cockpit-v2-wave5-g0-offline-0001"
    publication_digest = _digest("publication")
    publication_bytes_digest = _digest("publication-bytes")
    head_digest = _digest("head")
    head_bytes_digest = _digest("head-bytes")
    act_id = "g0-act-0001"
    memory_id = f"act:{act_id}"
    presentation_id = "scripted-presentation-session-001"
    pairing_session = "pair-session-001"
    subject = "MintA"

    scene = {
        "sceneId": publication_id,
        "sceneDigest": publication_digest,
        "catalogCutoff": "10",
    }
    memory = {
        "kind": "operator_act",
        "value": {
            "actId": act_id,
            "sessionId": "g0-session-0001",
            "occurredAt": "12",
            "scene": {"status": "committed", "value": scene},
            "presentation": {
                "status": "gap",
                "value": {
                    "gapId": "g0-presentation-gap-0001",
                    "scene": copy.deepcopy(scene),
                    "reason": "not_mounted",
                    "detectedAt": "11",
                },
            },
            "kind": "mark",
            "subject": subject,
            "assertion": None,
        },
    }
    claim: dict[str, Any] = {
        "contract": "joshi.cockpit.v2.browser_presentation_claim",
        "schemaVersion": 1,
        "idempotencyKey": "browser-presentation:scripted-page-001:1",
        "clientPresentationId": presentation_id,
        "browserPageId": "scripted-page-001",
        "presentationSeq": "1",
        "publication": {
            "publicationId": publication_id,
            "publicationDigest": publication_digest,
            "publicationBytesDigest": publication_bytes_digest,
            "publicationCommitSeq": "10",
        },
        "head": {
            "headDigest": head_digest,
            "headBytesDigest": head_bytes_digest,
            "headCommitSeq": "11",
        },
        "sourceOccurrenceId": source,
        "renderedSubjects": [subject],
        "renderedSubjectCount": "1",
        "mountedAt": "2026-08-19T04:45:23.803574Z",
        "clientClockId": "scripted-page-001-clock",
        "monotonicNs": "1",
        "viewport": {
            "widthCssPx": "1280",
            "heightCssPx": "800",
            "devicePixelRatioMilli": "1000",
        },
        "documentVisibility": "visible",
        "documentHasFocus": True,
        "authority": "read_only_no_execution",
        "ceiling": "browser_reported_not_pixel_verified",
    }
    claim["claimDigest"] = qualified_sha256_bytes(_bytes(claim))
    identity = [
        "joshi.store.wave6_operator_evidence_input_identity.v1",
        program,
        census,
        memory_id,
        presentation_id,
    ]
    binding = "wave6-operator-input:" + qualified_sha256_bytes(canonical_json_bytes(identity))[7:]
    document = {
        "contract": "joshi.store.wave6.operator-evidence-input.v1",
        "schemaVersion": 1,
        "bindingId": binding,
        "programId": program,
        "inputCensusBindingId": census,
        "inputCensusDocumentDigest": _digest("input-census"),
        "inputCensusCommitSeq": "20",
        "sourceOccurrenceId": source,
        "publicationId": publication_id,
        "publicationDigest": publication_digest,
        "publicationBytesDigest": publication_bytes_digest,
        "publicationCommitSeq": "10",
        "headDigest": head_digest,
        "headBytesDigest": head_bytes_digest,
        "headCommitSeq": "11",
        "memoryOccurrenceId": memory_id,
        "memoryOccurrenceDigest": qualified_sha256_bytes(_bytes(memory)),
        "memoryCommitSeq": "12",
        "memoryQueueGeneration": "1",
        "memoryOccurrence": memory,
        "presentationClaimId": presentation_id,
        "presentationClaimDigest": claim["claimDigest"],
        "presentationClaimBytesDigest": qualified_sha256_bytes(_bytes(claim)),
        "presentationCommitSeq": "13",
        "pairingSessionId": pairing_session,
        "presentationClaim": claim,
        "subjectId": subject,
        "actPresentationGapRetained": True,
        "presentationRepairsActGap": False,
        "sessionEquivalenceClaimed": False,
        "humanViewingVerified": False,
        "recognitionObserved": False,
        "operatorModelResolved": False,
        "authority": "read_record_replay_propose_shadow_only",
        "claimScope": (
            "store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model"
        ),
        "semanticCeiling": "store_resolved_operator_evidence_input_only",
    }
    return {
        "contract": "joshi.core.wave6_operator_evidence_input_report.v1",
        "schemaVersion": 1,
        "status": "useful_partial",
        "authority": "read_record_replay_propose_shadow_only",
        "semanticCeiling": "store_resolved_operator_evidence_input_only",
        "claimScope": (
            "store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model"
        ),
        "catalogSchema": "joshi.sqlite.v22",
        "programId": program,
        "programRegistrationDigest": _digest("program"),
        "inputCensusBindingId": census,
        "inputCensusDocumentDigest": document["inputCensusDocumentDigest"],
        "sourceOccurrenceId": source,
        "publicationId": publication_id,
        "publicationDigest": publication_digest,
        "headDigest": head_digest,
        "memoryOccurrenceId": memory_id,
        "memoryOccurrenceDigest": document["memoryOccurrenceDigest"],
        "memorySessionId": "g0-session-0001",
        "memorySubjectId": subject,
        "presentationClaimId": presentation_id,
        "presentationClaimDigest": claim["claimDigest"],
        "pairingSessionId": pairing_session,
        "bindingId": binding,
        "documentDigest": qualified_sha256_bytes(_bytes(document)),
        "operatorEvidenceInput": document,
        "acceptedCommitSeq": "21",
        "firstStatus": "accepted",
        "retryStatus": "idempotent",
        "storeResolvedInputCensus": True,
        "storeResolvedMemoryAct": True,
        "storeResolvedBrowserReport": True,
        "scriptedPresentationPath": True,
        "exactRetryClosed": True,
        "restartReverified": True,
        "actPresentationGapRetained": True,
        "presentationRepairsActGap": False,
        "sessionEquivalenceClaimed": False,
        "humanViewingVerified": False,
        "recognitionObserved": False,
        "operatorModelResolved": False,
        "providerIo": False,
        "externalMutation": False,
        "productQualified": False,
        "liveQualified": False,
    }


def _write(path: Path, report: dict[str, Any]) -> None:
    path.write_bytes(_bytes(report) + b"\n")


def _resign(report: dict[str, Any]) -> None:
    document = report["operatorEvidenceInput"]
    memory = document["memoryOccurrence"]
    document["memoryOccurrenceDigest"] = qualified_sha256_bytes(_bytes(memory))
    report["memoryOccurrenceDigest"] = document["memoryOccurrenceDigest"]
    claim = document["presentationClaim"]
    claim.pop("claimDigest", None)
    claim["claimDigest"] = qualified_sha256_bytes(_bytes(claim))
    document["presentationClaimDigest"] = claim["claimDigest"]
    document["presentationClaimBytesDigest"] = qualified_sha256_bytes(_bytes(claim))
    report["presentationClaimDigest"] = claim["claimDigest"]
    report["documentDigest"] = qualified_sha256_bytes(_bytes(document))


def test_exact_v22_packet_is_validated_without_model_or_recognition_promotion(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "operator-input.json"
    _write(report_path, _valid_report())

    packet = validate_store_operator_evidence_report(report_path)

    assert packet.act_kind == "mark"
    assert packet.presentation_gap_reason == "not_mounted"
    assert packet.model_admission_refusal == MODEL_ADMISSION_REFUSAL
    assert not packet.scene_binding_materialized
    assert not packet.replay_materialized
    assert not packet.human_viewing_verified
    assert not packet.recognition_observed
    assert not packet.operator_model_resolved
    assert packet.validation_receipt()["status"] == "valid_nonpromoting"


def test_positive_qualification_or_gap_replacement_is_refused(tmp_path: Path) -> None:
    promoted = _valid_report()
    promoted["humanViewingVerified"] = True
    path = tmp_path / "promoted.json"
    _write(path, promoted)
    with pytest.raises(StoreOperatorEvidenceError, match="humanViewingVerified must be false"):
        validate_store_operator_evidence_report(path)

    repaired = _valid_report()
    repaired["operatorEvidenceInput"]["memoryOccurrence"]["value"]["presentation"] = {
        "status": "occurrence",
        "value": {"occurrenceId": "invented"},
    }
    _resign(repaired)
    path = tmp_path / "repaired.json"
    _write(path, repaired)
    with pytest.raises(StoreOperatorEvidenceError, match="cannot replace the original gap"):
        validate_store_operator_evidence_report(path)


def test_subject_omission_and_scalar_substitution_are_refused(tmp_path: Path) -> None:
    omitted = _valid_report()
    claim = omitted["operatorEvidenceInput"]["presentationClaim"]
    claim["renderedSubjects"] = ["MintB"]
    _resign(omitted)
    path = tmp_path / "omitted.json"
    _write(path, omitted)
    with pytest.raises(StoreOperatorEvidenceError, match="rendered subjects"):
        validate_store_operator_evidence_report(path)

    substituted = _valid_report()
    substituted["publicationDigest"] = _digest("foreign-publication")
    path = tmp_path / "substituted.json"
    _write(path, substituted)
    with pytest.raises(StoreOperatorEvidenceError, match="report scalars differ"):
        validate_store_operator_evidence_report(path)


def test_duplicate_or_reordered_json_never_becomes_exact_store_evidence(tmp_path: Path) -> None:
    report = _valid_report()
    duplicate = _bytes(report).replace(
        b'"status":"useful_partial",',
        b'"status":"useful_partial","status":"useful_partial",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_bytes(duplicate + b"\n")
    with pytest.raises(StoreOperatorEvidenceError, match="duplicate JSON key"):
        validate_store_operator_evidence_report(path)

    reordered = _valid_report()
    document = reordered["operatorEvidenceInput"]
    reordered["operatorEvidenceInput"] = dict(reversed(tuple(document.items())))
    reordered["documentDigest"] = qualified_sha256_bytes(_bytes(reordered["operatorEvidenceInput"]))
    path = tmp_path / "reordered.json"
    _write(path, reordered)
    with pytest.raises(StoreOperatorEvidenceError, match="fields or canonical order differ"):
        validate_store_operator_evidence_report(path)
