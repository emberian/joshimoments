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


def _valid_input_census(
    program: str,
    source_occurrence_id: str,
    receipt: str,
) -> dict[str, Any]:
    source_id = "pump.api.product.v1"
    surface_id = "pump.discovery.public_c0"
    subjects = ("MintA", "MintB")
    fact_ids = (
        "fact:source:mint-a:" + "1" * 64,
        "fact:source:mint-b:" + "2" * 64,
    )
    facts = [
        {
            "factId": fact_id,
            "factDigest": _digest(f"fact-{subject}"),
            "surfaceId": surface_id,
            "sourceId": source_id,
            "subject": subject,
            "field": "mint",
            "protection": "public",
            "observedAt": "2026-08-17T12:00:00.010000Z",
            "knownAt": "2026-08-17T12:00:00.020000Z",
            "commitSeq": "8",
        }
        for subject, fact_id in zip(subjects, fact_ids, strict=True)
    ]
    source = {
        "contract": "joshi.store.wave5.source_occurrence.v1",
        "schemaVersion": 1,
        "sourceOccurrenceId": source_occurrence_id,
        "runRegistrationId": "wave5-ignition-fixture-0001",
        "catalogAdmissionId": "catalog-admission:wave5-g0-source-publication-0001",
        "sourceReceiptDigest": receipt,
        "sourceId": source_id,
        "surfaceProfile": {
            "profileId": "daily-surface:wave5-ignition-fixture-0001",
            "profileDigest": _digest("surface-profile"),
            "fieldCells": [{"surfaceId": surface_id, "sourceId": source_id, "field": "mint"}],
        },
        "facts": facts,
        "eligibleSubjects": list(subjects),
        "memberships": [
            {
                "subject": "MintA",
                "membership": "hot",
                "observedAt": "2026-08-17T12:00:00.020000Z",
                "evidenceDigest": _digest("membership-a"),
            },
            {
                "subject": "MintB",
                "membership": "cold_control",
                "observedAt": "2026-08-17T12:00:00.020000Z",
                "evidenceDigest": _digest("membership-b"),
            },
        ],
        "coverage": [
            {
                "surfaceId": surface_id,
                "sourceId": source_id,
                "subject": subject,
                "field": "mint",
                "factIds": [fact_id],
                "state": "partial",
                "coverageDigest": _digest(f"coverage-{subject}"),
            }
            for subject, fact_id in zip(subjects, fact_ids, strict=True)
        ],
        "gaps": [],
        "renderedSubjects": ["MintA"],
        "omissions": [
            {
                "subject": "MintB",
                "reason": "cold_control_not_rendered",
                "membership": "cold_control",
            }
        ],
        "knownThroughCommitSeq": "8",
        "maximumInputAvailableAt": "2026-08-17T12:00:00.020000Z",
        "protection": "public",
        "authority": "read_only_no_execution",
    }
    identity = [
        "joshi.store.wave6_input_census_identity.v1",
        program,
        source_occurrence_id,
    ]
    binding = "wave6-input-census:" + qualified_sha256_bytes(canonical_json_bytes(identity))[7:]
    return {
        "contract": "joshi.store.wave6.input-census.v1",
        "schemaVersion": 1,
        "bindingId": binding,
        "programId": program,
        "sourceDescriptorDigest": _digest("source-descriptor"),
        "sourceCreatedCommitSeq": "9",
        "sourceOccurrence": source,
        "factCount": "2",
        "eligibleSubjectCount": "2",
        "membershipCount": "2",
        "coverageCount": "2",
        "gapCount": "0",
        "hotSubjectCount": "1",
        "coldControlSubjectCount": "1",
        "storeResolvedSource": True,
        "marketAtlasResolved": False,
        "authority": "read_record_replay_propose_shadow_only",
        "claimScope": (
            "mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution"
        ),
        "semanticCeiling": "store_resolved_offline_fixture_input_census_only",
    }


def _valid_report() -> dict[str, Any]:
    program = "w6-program-fixture-001"
    source_receipt = _digest("source-receipt")
    source = f"source-c0:{source_receipt[7:]}"
    input_census = _valid_input_census(program, source, source_receipt)
    census = input_census["bindingId"]
    census_digest = qualified_sha256_bytes(_bytes(input_census))
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
        "inputCensusDocumentDigest": census_digest,
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
        "inputCensus": input_census,
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
    census_digest = qualified_sha256_bytes(_bytes(report["inputCensus"]))
    document["inputCensusDocumentDigest"] = census_digest
    report["inputCensusDocumentDigest"] = census_digest
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


def test_embedded_census_cannot_be_relabeled_behind_resigned_outer_bytes(
    tmp_path: Path,
) -> None:
    relabeled = _valid_report()
    cell = relabeled["inputCensus"]["sourceOccurrence"]["surfaceProfile"]["fieldCells"][0]
    cell["field"] = "lifecycle_state"
    _resign(relabeled)
    path = tmp_path / "relabeled-census.json"
    _write(path, relabeled)

    with pytest.raises(StoreOperatorEvidenceError, match="mint-discovery field cell"):
        validate_store_operator_evidence_report(path)

    future_cut = _valid_report()
    future_source = future_cut["inputCensus"]["sourceOccurrence"]
    future_source["knownThroughCommitSeq"] = "10"
    for fact in future_source["facts"]:
        fact["commitSeq"] = "10"
    _resign(future_cut)
    path = tmp_path / "future-census-cut.json"
    _write(path, future_cut)
    with pytest.raises(StoreOperatorEvidenceError, match="knowledge cutoff exceeds"):
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
