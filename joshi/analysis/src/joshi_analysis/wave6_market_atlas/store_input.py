"""Cross-runtime assessment of the real W5 discovery census at the market-atlas gate.

The V20 census proves mint discovery presence only. It does not contain lifecycle state/version or
registered coverage for the other atlas strata, so this module validates it and refuses atlas
materialization rather than manufacturing observed, unknown, or gap rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.snapshot import ManifestError

from .contracts import COMPONENT_KINDS

REPORT_CONTRACT = "joshi.core.wave6_store_input_census_report.v1"
DOCUMENT_CONTRACT = "joshi.store.wave6.input-census.v1"
AUTHORITY = "read_record_replay_propose_shadow_only"
DOCUMENT_CEILING = "store_resolved_offline_fixture_input_census_only"
DOCUMENT_CLAIM_SCOPE = (
    "mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution"
)
ATLAS_ADMISSION_REFUSAL = (
    "mint_discovery_is_not_mint_lifecycle_and_other_atlas_strata_are_uncovered"
)
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_DECIMAL = re.compile(r"[1-9][0-9]*\Z")
_NATURAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")

_REPORT_KEYS = (
    "contract",
    "schemaVersion",
    "status",
    "authority",
    "semanticCeiling",
    "claimScope",
    "catalogSchema",
    "programId",
    "programRegistrationDigest",
    "sourceOccurrenceId",
    "sourceDescriptorDigest",
    "sourceCreatedCommitSeq",
    "sourceKnownThroughCommitSeq",
    "bindingId",
    "documentDigest",
    "storeInputCensus",
    "acceptedCommitSeq",
    "firstStatus",
    "retryStatus",
    "factCount",
    "eligibleSubjectCount",
    "membershipCount",
    "coverageCount",
    "gapCount",
    "hotSubjectCount",
    "coldControlSubjectCount",
    "storeResolvedSource",
    "exactRetryClosed",
    "restartReverified",
    "storeResolvedMarketAtlas",
    "fieldRelease",
    "empiricalClaim",
    "causalClaim",
    "strategyClaim",
    "providerIo",
    "externalMutation",
    "productQualified",
    "liveQualified",
)
_DOCUMENT_KEYS = (
    "contract",
    "schemaVersion",
    "bindingId",
    "programId",
    "sourceDescriptorDigest",
    "sourceCreatedCommitSeq",
    "sourceOccurrence",
    "factCount",
    "eligibleSubjectCount",
    "membershipCount",
    "coverageCount",
    "gapCount",
    "hotSubjectCount",
    "coldControlSubjectCount",
    "storeResolvedSource",
    "marketAtlasResolved",
    "authority",
    "claimScope",
    "semanticCeiling",
)
_SOURCE_KEYS = (
    "contract",
    "schemaVersion",
    "sourceOccurrenceId",
    "runRegistrationId",
    "catalogAdmissionId",
    "sourceReceiptDigest",
    "sourceId",
    "surfaceProfile",
    "facts",
    "eligibleSubjects",
    "memberships",
    "coverage",
    "gaps",
    "renderedSubjects",
    "omissions",
    "knownThroughCommitSeq",
    "maximumInputAvailableAt",
    "protection",
    "authority",
)
_FACT_KEYS = (
    "factId",
    "factDigest",
    "surfaceId",
    "sourceId",
    "subject",
    "field",
    "protection",
    "observedAt",
    "knownAt",
    "commitSeq",
)
_MEMBERSHIP_KEYS = ("subject", "membership", "observedAt", "evidenceDigest")
_COVERAGE_KEYS = (
    "surfaceId",
    "sourceId",
    "subject",
    "field",
    "factIds",
    "state",
    "coverageDigest",
)
_OMISSION_KEYS = ("subject", "reason", "membership")


class StoreInputCensusError(ManifestError):
    """The Core census report is malformed, substituted, or claims atlas admission."""


@dataclass(frozen=True, slots=True)
class _StoreInputCensusAssessment:
    report_digest: str
    document_digest: str
    document_bytes: bytes
    binding_id: str
    program_id: str
    source_occurrence_id: str
    source_descriptor_digest: str
    eligible_subjects: tuple[str, ...]
    hot_subjects: tuple[str, ...]
    cold_control_subjects: tuple[str, ...]
    accepted_commit_seq: int
    available_evidence_kinds: tuple[str, ...] = ("mint_discovery_presence",)
    admitted_atlas_strata: tuple[str, ...] = ()
    missing_atlas_strata: tuple[str, ...] = COMPONENT_KINDS
    atlas_admission_refusal: str = ATLAS_ADMISSION_REFUSAL
    market_atlas_materialized: bool = False
    field_release: bool = False
    empirical_claim: bool = False
    causal_claim: bool = False
    strategy_claim: bool = False

    def __post_init__(self) -> None:
        _digest(self.report_digest, "validated census report digest")
        _digest(self.document_digest, "validated census document digest")
        if qualified_sha256_bytes(self.document_bytes) != self.document_digest:
            raise StoreInputCensusError("validated census bytes differ from document digest")
        if (
            self.available_evidence_kinds != ("mint_discovery_presence",)
            or self.admitted_atlas_strata
            or self.missing_atlas_strata != COMPONENT_KINDS
            or self.atlas_admission_refusal != ATLAS_ADMISSION_REFUSAL
            or self.market_atlas_materialized
            or self.field_release
            or self.empirical_claim
            or self.causal_claim
            or self.strategy_claim
        ):
            raise StoreInputCensusError("validated census assessment cannot self-promote")

    def validation_receipt(self) -> dict[str, Any]:
        """Return the explicit non-atlas assessment receipt."""

        return {
            "contract": "joshi.analysis.wave6-market-atlas-input-assessment/v1",
            "schemaVersion": 1,
            "status": "valid_refused_atlas_admission",
            "authority": AUTHORITY,
            "semanticCeiling": "cross_runtime_store_census_validated_not_market_atlas",
            "reportDigest": self.report_digest,
            "documentDigest": self.document_digest,
            "bindingId": self.binding_id,
            "programId": self.program_id,
            "sourceOccurrenceId": self.source_occurrence_id,
            "sourceDescriptorDigest": self.source_descriptor_digest,
            "eligibleSubjects": list(self.eligible_subjects),
            "hotSubjects": list(self.hot_subjects),
            "coldControlSubjects": list(self.cold_control_subjects),
            "acceptedCommitSeq": str(self.accepted_commit_seq),
            "availableEvidenceKinds": list(self.available_evidence_kinds),
            "admittedAtlasStrata": [],
            "missingAtlasStrata": list(self.missing_atlas_strata),
            "atlasAdmissionRefusal": self.atlas_admission_refusal,
            "marketAtlasMaterialized": False,
            "fieldRelease": False,
            "empiricalClaim": False,
            "causalClaim": False,
            "strategyClaim": False,
        }


@dataclass(frozen=True, slots=True)
class _EmbeddedCensusValidation:
    document_bytes: bytes
    document_digest: str
    binding_id: str
    program_id: str
    source_occurrence_id: str
    source_descriptor_digest: str
    source_created_commit_seq: int
    source_known_through_commit_seq: int
    eligible_subjects: tuple[str, ...]
    hot_subjects: tuple[str, ...]
    cold_control_subjects: tuple[str, ...]
    counts: dict[str, int]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StoreInputCensusError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise StoreInputCensusError(f"non-finite JSON scalar is forbidden: {value}")


def _wire_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _exact_json(raw: bytes) -> dict[str, Any]:
    body = raw[:-1] if raw.endswith(b"\n") else raw
    if not body or body != body.strip() or raw not in {body, body + b"\n"}:
        raise StoreInputCensusError("census report is not exact compact JSON")
    try:
        value = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreInputCensusError("census report is not strict UTF-8 JSON") from error
    if not isinstance(value, dict) or _wire_bytes(value) != body:
        raise StoreInputCensusError("census report is not canonical ordered JSON")
    return value


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StoreInputCensusError(f"{context} must be an object")
    return value


def _keys(value: dict[str, Any], expected: tuple[str, ...], context: str) -> None:
    if tuple(value) != expected:
        raise StoreInputCensusError(f"{context} fields or canonical order differ")


def _text(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise StoreInputCensusError(f"{context} must be bounded non-control text")
    return value


def _digest(value: Any, context: str) -> str:
    text = _text(value, context)
    if (
        len(text) != 71
        or not text.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise StoreInputCensusError(f"{context} must be sha256:<64 lowercase hex>")
    return text


def _positive(value: Any, context: str) -> int:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise StoreInputCensusError(f"{context} must be a positive canonical decimal string")
    parsed = int(value)
    if parsed > (1 << 63) - 1:
        raise StoreInputCensusError(f"{context} exceeds signed store commit range")
    return parsed


def _nonnegative(value: Any, context: str) -> int:
    if not isinstance(value, str) or _NATURAL.fullmatch(value) is None:
        raise StoreInputCensusError(f"{context} must be a canonical nonnegative decimal string")
    parsed = int(value)
    if parsed > (1 << 63) - 1:
        raise StoreInputCensusError(f"{context} exceeds signed store range")
    return parsed


def _utc(value: Any, context: str) -> datetime:
    text = _text(value, context)
    if not text.endswith("Z"):
        raise StoreInputCensusError(f"{context} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise StoreInputCensusError(f"{context} is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.astimezone(UTC) != parsed:
        raise StoreInputCensusError(f"{context} must be UTC")
    return parsed


def _exact_bool(value: Any, expected: bool, context: str) -> None:
    if value is not expected:
        raise StoreInputCensusError(f"{context} must be {str(expected).lower()}")


def _sorted_unique_strings(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise StoreInputCensusError(f"{context} must be nonempty")
    result = tuple(_text(item, context) for item in value)
    if result != tuple(sorted(set(result))):
        raise StoreInputCensusError(f"{context} must be sorted and unique")
    return result


def _validate_source(source: dict[str, Any]) -> dict[str, Any]:
    _keys(source, _SOURCE_KEYS, "W5 source occurrence")
    if (
        source["contract"] != "joshi.store.wave5.source_occurrence.v1"
        or source["schemaVersion"] != 1
        or source["protection"] != "public"
        or source["authority"] != "read_only_no_execution"
    ):
        raise StoreInputCensusError("W5 source occurrence contract differs")
    source_id = _text(source["sourceId"], "source id")
    source_occurrence_id = _text(source["sourceOccurrenceId"], "source occurrence id")
    receipt_digest = _digest(source["sourceReceiptDigest"], "source receipt digest")
    if source_occurrence_id != f"source-c0:{receipt_digest[7:]}":
        raise StoreInputCensusError("source occurrence identity differs from its receipt digest")
    _text(source["runRegistrationId"], "run registration id")
    _text(source["catalogAdmissionId"], "catalog admission id")

    profile = _object(source["surfaceProfile"], "surface profile")
    _keys(profile, ("profileId", "profileDigest", "fieldCells"), "surface profile")
    _text(profile["profileId"], "surface profile id")
    _digest(profile["profileDigest"], "surface profile digest")
    cells = profile["fieldCells"]
    if not isinstance(cells, list) or len(cells) != 1:
        raise StoreInputCensusError("discovery census must retain one exact field cell")
    cell = _object(cells[0], "surface field cell")
    _keys(cell, ("surfaceId", "sourceId", "field"), "surface field cell")
    surface_id = _text(cell["surfaceId"], "surface id")
    if cell["sourceId"] != source_id or cell["field"] != "mint":
        raise StoreInputCensusError("source census is not the exact mint-discovery field cell")

    eligible = _sorted_unique_strings(source["eligibleSubjects"], "eligible subjects")
    if len(eligible) != 2:
        raise StoreInputCensusError("offline fixture census requires two eligible subjects")
    facts = source["facts"]
    if not isinstance(facts, list) or len(facts) != len(eligible):
        raise StoreInputCensusError("mint-discovery facts must exactly cover the denominator")
    fact_by_id: dict[str, dict[str, Any]] = {}
    fact_subjects: list[str] = []
    known_times: list[datetime] = []
    fact_commits: list[int] = []
    for fact_value in facts:
        fact = _object(fact_value, "source fact")
        _keys(fact, _FACT_KEYS, "source fact")
        fact_id = _text(fact["factId"], "fact id")
        if fact_id in fact_by_id:
            raise StoreInputCensusError("source fact IDs must be unique")
        _digest(fact["factDigest"], "fact digest")
        subject = _text(fact["subject"], "fact subject")
        observed = _utc(fact["observedAt"], "fact observedAt")
        known = _utc(fact["knownAt"], "fact knownAt")
        if (
            fact["surfaceId"] != surface_id
            or fact["sourceId"] != source_id
            or fact["field"] != "mint"
            or fact["protection"] != "public"
            or subject not in eligible
            or known < observed
        ):
            raise StoreInputCensusError("source fact differs from mint-discovery semantics")
        fact_by_id[fact_id] = fact
        fact_subjects.append(subject)
        known_times.append(known)
        fact_commits.append(_positive(fact["commitSeq"], "fact commit"))
    if tuple(fact_subjects) != eligible:
        raise StoreInputCensusError("source facts must follow the exact eligible denominator")

    memberships = source["memberships"]
    if not isinstance(memberships, list) or len(memberships) != len(eligible):
        raise StoreInputCensusError("memberships must exactly cover eligible subjects")
    membership_by_subject: dict[str, str] = {}
    for membership_value in memberships:
        membership = _object(membership_value, "subject membership")
        _keys(membership, _MEMBERSHIP_KEYS, "subject membership")
        subject = _text(membership["subject"], "membership subject")
        kind = membership["membership"]
        _utc(membership["observedAt"], "membership observedAt")
        _digest(membership["evidenceDigest"], "membership evidence digest")
        if (
            subject in membership_by_subject
            or subject not in eligible
            or kind
            not in {
                "hot",
                "cold_control",
            }
        ):
            raise StoreInputCensusError("membership partition is not exact hot/cold-control")
        membership_by_subject[subject] = kind
    if tuple(membership_by_subject) != eligible or set(membership_by_subject.values()) != {
        "hot",
        "cold_control",
    }:
        raise StoreInputCensusError("membership partition lacks hot or cold control")

    coverage = source["coverage"]
    if not isinstance(coverage, list) or len(coverage) != len(eligible):
        raise StoreInputCensusError("coverage must exactly close the mint denominator")
    covered_subjects: list[str] = []
    for coverage_value in coverage:
        row = _object(coverage_value, "coverage row")
        _keys(row, _COVERAGE_KEYS, "coverage row")
        subject = _text(row["subject"], "coverage subject")
        fact_ids = row["factIds"]
        if (
            row["surfaceId"] != surface_id
            or row["sourceId"] != source_id
            or row["field"] != "mint"
            or row["state"] != "partial"
            or not isinstance(fact_ids, list)
            or len(fact_ids) != 1
            or fact_ids[0] not in fact_by_id
            or fact_by_id[fact_ids[0]]["subject"] != subject
        ):
            raise StoreInputCensusError("coverage row does not close one partial mint fact")
        _digest(row["coverageDigest"], "coverage digest")
        covered_subjects.append(subject)
    if tuple(covered_subjects) != eligible:
        raise StoreInputCensusError("coverage rows must follow the eligible denominator")
    if source["gaps"] != []:
        raise StoreInputCensusError("offline discovery fixture unexpectedly carries source gaps")

    rendered = _sorted_unique_strings(source["renderedSubjects"], "rendered subjects")
    hot = tuple(subject for subject in eligible if membership_by_subject[subject] == "hot")
    cold = tuple(
        subject for subject in eligible if membership_by_subject[subject] == "cold_control"
    )
    if rendered != hot:
        raise StoreInputCensusError("rendered subjects must equal the exact hot partition")
    omissions = source["omissions"]
    if not isinstance(omissions, list) or len(omissions) != len(cold):
        raise StoreInputCensusError("omissions must exactly retain the cold-control partition")
    omitted: list[str] = []
    for omission_value in omissions:
        omission = _object(omission_value, "omission")
        _keys(omission, _OMISSION_KEYS, "omission")
        if (
            omission["reason"] != "cold_control_not_rendered"
            or omission["membership"] != "cold_control"
        ):
            raise StoreInputCensusError("cold-control omission semantics differ")
        omitted.append(_text(omission["subject"], "omitted subject"))
    if tuple(omitted) != cold:
        raise StoreInputCensusError("omissions differ from cold-control membership")

    known_through = _positive(source["knownThroughCommitSeq"], "source known-through commit")
    if known_through != max(fact_commits):
        raise StoreInputCensusError("source known-through commit differs from exact facts")
    if _utc(source["maximumInputAvailableAt"], "maximum input availability") != max(known_times):
        raise StoreInputCensusError("maximum input availability differs from exact facts")
    return {
        "eligible": eligible,
        "hot": hot,
        "cold": cold,
        "known_through": known_through,
    }


def validate_embedded_store_input_census_document(
    document_value: Any,
    expected_document_digest: Any,
) -> _EmbeddedCensusValidation:
    """Validate embedded V20 bytes only; this pure check confers no store authority."""

    expected_digest = _digest(expected_document_digest, "embedded census document digest")
    document = _object(document_value, "embedded store input census")
    document_bytes = _wire_bytes(document)
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise StoreInputCensusError("embedded store input census is oversized")
    if qualified_sha256_bytes(document_bytes) != expected_digest:
        raise StoreInputCensusError("embedded store input census digest differs")
    _keys(document, _DOCUMENT_KEYS, "store input census document")
    if (
        document["contract"] != DOCUMENT_CONTRACT
        or document["schemaVersion"] != 1
        or document["authority"] != AUTHORITY
        or document["claimScope"] != DOCUMENT_CLAIM_SCOPE
        or document["semanticCeiling"] != DOCUMENT_CEILING
    ):
        raise StoreInputCensusError("store input census document contract differs")
    _exact_bool(document["storeResolvedSource"], True, "storeResolvedSource")
    _exact_bool(document["marketAtlasResolved"], False, "marketAtlasResolved")
    source_commit = _positive(document["sourceCreatedCommitSeq"], "source created commit")
    _digest(document["sourceDescriptorDigest"], "source descriptor digest")
    for key in ("bindingId", "programId"):
        _text(document[key], key)

    source = _object(document["sourceOccurrence"], "embedded W5 source occurrence")
    resolved = _validate_source(source)
    if resolved["known_through"] > source_commit:
        raise StoreInputCensusError("source knowledge cutoff exceeds its store commit")
    counts = {
        "factCount": len(source["facts"]),
        "eligibleSubjectCount": len(resolved["eligible"]),
        "membershipCount": len(source["memberships"]),
        "coverageCount": len(source["coverage"]),
        "gapCount": len(source["gaps"]),
        "hotSubjectCount": len(resolved["hot"]),
        "coldControlSubjectCount": len(resolved["cold"]),
    }
    for key, expected in counts.items():
        if _nonnegative(document[key], f"document {key}") != expected:
            raise StoreInputCensusError(f"document {key} differs from exact source")
    if document["gapCount"] != "0":
        raise StoreInputCensusError("zero gap count must use canonical string zero")

    identity = [
        "joshi.store.wave6_input_census_identity.v1",
        document["programId"],
        source["sourceOccurrenceId"],
    ]
    expected_binding = (
        "wave6-input-census:" + qualified_sha256_bytes(canonical_json_bytes(identity))[7:]
    )
    if document["bindingId"] != expected_binding:
        raise StoreInputCensusError("store input census binding identity differs")
    return _EmbeddedCensusValidation(
        document_bytes=document_bytes,
        document_digest=expected_digest,
        binding_id=document["bindingId"],
        program_id=document["programId"],
        source_occurrence_id=source["sourceOccurrenceId"],
        source_descriptor_digest=document["sourceDescriptorDigest"],
        source_created_commit_seq=source_commit,
        source_known_through_commit_seq=resolved["known_through"],
        eligible_subjects=resolved["eligible"],
        hot_subjects=resolved["hot"],
        cold_control_subjects=resolved["cold"],
        counts=counts,
    )


def validate_store_input_census_report(report_path: str | Path) -> _StoreInputCensusAssessment:
    """Validate the exact Core report and return an explicit market-atlas refusal."""

    raw = Path(report_path).read_bytes()
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise StoreInputCensusError("store input census report is empty or oversized")
    report = _exact_json(raw)
    _keys(report, _REPORT_KEYS, "store input census report")
    if (
        report["contract"] != REPORT_CONTRACT
        or report["schemaVersion"] != 1
        or report["status"] != "useful_partial"
        or report["authority"] != AUTHORITY
        or report["semanticCeiling"] != DOCUMENT_CEILING
        or report["claimScope"] != DOCUMENT_CLAIM_SCOPE
        or report["catalogSchema"] != "joshi.sqlite.v22"
    ):
        raise StoreInputCensusError("Core input-census report contract differs")
    for key in ("storeResolvedSource", "exactRetryClosed", "restartReverified"):
        _exact_bool(report[key], True, key)
    for key in (
        "storeResolvedMarketAtlas",
        "fieldRelease",
        "empiricalClaim",
        "causalClaim",
        "strategyClaim",
        "providerIo",
        "externalMutation",
        "productQualified",
        "liveQualified",
    ):
        _exact_bool(report[key], False, key)
    if (
        report["firstStatus"] not in {"accepted", "idempotent"}
        or report["retryStatus"] != "idempotent"
    ):
        raise StoreInputCensusError("Core input-census report does not close exact retry")
    for key in ("programRegistrationDigest", "sourceDescriptorDigest", "documentDigest"):
        _digest(report[key], key)
    for key in ("programId", "sourceOccurrenceId", "bindingId"):
        _text(report[key], key)

    embedded = validate_embedded_store_input_census_document(
        report["storeInputCensus"], report["documentDigest"]
    )
    accepted_commit = _positive(report["acceptedCommitSeq"], "census accepted commit")
    if embedded.source_created_commit_seq >= accepted_commit:
        raise StoreInputCensusError("source occurrence was not prior to input census")
    document = report["storeInputCensus"]
    source = document["sourceOccurrence"]
    for key, expected in embedded.counts.items():
        if _nonnegative(report[key], f"report {key}") != expected:
            raise StoreInputCensusError(f"report {key} differs from exact source")
    if report["gapCount"] != "0":
        raise StoreInputCensusError("zero gap count must use canonical string zero")

    exact_pairs = (
        ("programId", "programId"),
        ("sourceOccurrenceId", "sourceOccurrenceId"),
        ("sourceDescriptorDigest", "sourceDescriptorDigest"),
        ("sourceCreatedCommitSeq", "sourceCreatedCommitSeq"),
        ("bindingId", "bindingId"),
    )
    if any(
        report[report_key]
        != (
            source[document_key] if document_key == "sourceOccurrenceId" else document[document_key]
        )
        for report_key, document_key in exact_pairs
    ):
        raise StoreInputCensusError("Core report scalars differ from embedded store census")
    if report["sourceKnownThroughCommitSeq"] != source["knownThroughCommitSeq"]:
        raise StoreInputCensusError("Core report source cutoff differs from embedded source")

    return _StoreInputCensusAssessment(
        report_digest=qualified_sha256_bytes(raw),
        document_digest=embedded.document_digest,
        document_bytes=embedded.document_bytes,
        binding_id=embedded.binding_id,
        program_id=embedded.program_id,
        source_occurrence_id=embedded.source_occurrence_id,
        source_descriptor_digest=embedded.source_descriptor_digest,
        eligible_subjects=embedded.eligible_subjects,
        hot_subjects=embedded.hot_subjects,
        cold_control_subjects=embedded.cold_control_subjects,
        accepted_commit_seq=accepted_commit,
    )
