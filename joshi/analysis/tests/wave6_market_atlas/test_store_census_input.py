"""Cross-runtime refusal tests for the W5 discovery-census input."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.wave6_market_atlas import (
    ATLAS_ADMISSION_REFUSAL,
    StoreInputCensusError,
    validate_store_input_census_report,
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
    receipt = _digest("source-receipt")
    source_occurrence_id = f"source-c0:{receipt[7:]}"
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
            "commitSeq": "21",
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
        "knownThroughCommitSeq": "21",
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
    document = {
        "contract": "joshi.store.wave6.input-census.v1",
        "schemaVersion": 1,
        "bindingId": binding,
        "programId": program,
        "sourceDescriptorDigest": _digest("source-descriptor"),
        "sourceCreatedCommitSeq": "23",
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
    return {
        "contract": "joshi.core.wave6_store_input_census_report.v1",
        "schemaVersion": 1,
        "status": "useful_partial",
        "authority": "read_record_replay_propose_shadow_only",
        "semanticCeiling": "store_resolved_offline_fixture_input_census_only",
        "claimScope": (
            "mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution"
        ),
        "catalogSchema": "joshi.sqlite.v22",
        "programId": program,
        "programRegistrationDigest": _digest("program"),
        "sourceOccurrenceId": source_occurrence_id,
        "sourceDescriptorDigest": document["sourceDescriptorDigest"],
        "sourceCreatedCommitSeq": "23",
        "sourceKnownThroughCommitSeq": "21",
        "bindingId": binding,
        "documentDigest": qualified_sha256_bytes(_bytes(document)),
        "storeInputCensus": document,
        "acceptedCommitSeq": "24",
        "firstStatus": "accepted",
        "retryStatus": "idempotent",
        "factCount": "2",
        "eligibleSubjectCount": "2",
        "membershipCount": "2",
        "coverageCount": "2",
        "gapCount": "0",
        "hotSubjectCount": "1",
        "coldControlSubjectCount": "1",
        "storeResolvedSource": True,
        "exactRetryClosed": True,
        "restartReverified": True,
        "storeResolvedMarketAtlas": False,
        "fieldRelease": False,
        "empiricalClaim": False,
        "causalClaim": False,
        "strategyClaim": False,
        "providerIo": False,
        "externalMutation": False,
        "productQualified": False,
        "liveQualified": False,
    }


def _write(path: Path, report: dict[str, Any]) -> None:
    path.write_bytes(_bytes(report) + b"\n")


def _resign(report: dict[str, Any]) -> None:
    report["documentDigest"] = qualified_sha256_bytes(_bytes(report["storeInputCensus"]))


def test_exact_discovery_census_is_validated_and_explicitly_refused_at_atlas_gate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "census.json"
    _write(path, _valid_report())

    assessment = validate_store_input_census_report(path)

    assert assessment.available_evidence_kinds == ("mint_discovery_presence",)
    assert assessment.admitted_atlas_strata == ()
    assert assessment.atlas_admission_refusal == ATLAS_ADMISSION_REFUSAL
    assert len(assessment.missing_atlas_strata) == 6
    assert not assessment.market_atlas_materialized
    assert not assessment.field_release
    assert not assessment.empirical_claim
    receipt = assessment.validation_receipt()
    assert receipt["status"] == "valid_refused_atlas_admission"
    assert receipt["admittedAtlasStrata"] == []


def test_market_atlas_promotion_or_lifecycle_relabeling_is_refused(tmp_path: Path) -> None:
    promoted = _valid_report()
    promoted["storeResolvedMarketAtlas"] = True
    path = tmp_path / "promoted.json"
    _write(path, promoted)
    with pytest.raises(StoreInputCensusError, match="storeResolvedMarketAtlas must be false"):
        validate_store_input_census_report(path)

    relabeled = _valid_report()
    cell = relabeled["storeInputCensus"]["sourceOccurrence"]["surfaceProfile"]["fieldCells"][0]
    cell["field"] = "lifecycle_state"
    _resign(relabeled)
    path = tmp_path / "relabeled.json"
    _write(path, relabeled)
    with pytest.raises(StoreInputCensusError, match="mint-discovery field cell"):
        validate_store_input_census_report(path)


def test_denominator_membership_and_report_substitution_are_refused(tmp_path: Path) -> None:
    narrowed = _valid_report()
    source = narrowed["storeInputCensus"]["sourceOccurrence"]
    source["memberships"][1]["membership"] = "hot"
    _resign(narrowed)
    path = tmp_path / "narrowed.json"
    _write(path, narrowed)
    with pytest.raises(StoreInputCensusError, match="lacks hot or cold control"):
        validate_store_input_census_report(path)

    substituted = _valid_report()
    substituted["sourceDescriptorDigest"] = _digest("foreign-descriptor")
    path = tmp_path / "substituted.json"
    _write(path, substituted)
    with pytest.raises(StoreInputCensusError, match="report scalars differ"):
        validate_store_input_census_report(path)


def test_duplicate_or_reordered_census_json_is_refused(tmp_path: Path) -> None:
    report = _valid_report()
    duplicate = _bytes(report).replace(
        b'"status":"useful_partial",',
        b'"status":"useful_partial","status":"useful_partial",',
        1,
    )
    path = tmp_path / "duplicate.json"
    path.write_bytes(duplicate + b"\n")
    with pytest.raises(StoreInputCensusError, match="duplicate JSON key"):
        validate_store_input_census_report(path)

    reordered = _valid_report()
    document = copy.deepcopy(reordered["storeInputCensus"])
    reordered["storeInputCensus"] = dict(reversed(tuple(document.items())))
    _resign(reordered)
    path = tmp_path / "reordered.json"
    _write(path, reordered)
    with pytest.raises(StoreInputCensusError, match="fields or canonical order differ"):
        validate_store_input_census_report(path)
