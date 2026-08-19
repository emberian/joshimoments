"""Strict cross-runtime admission for the store-resolved V22 operator-evidence packet.

The packet joins durable evidence; it does not repair the original presentation gap or mint a
Wave 6 ``SceneBinding``, replay receipt, recognition response, or operator-model result.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.wave6_market_atlas.store_input import (
    StoreInputCensusError,
    validate_embedded_store_input_census_document,
)

from .contracts import OperatorModelError

CORE_REPORT_CONTRACT = "joshi.core.wave6_operator_evidence_input_report.v1"
STORE_INPUT_CONTRACT = "joshi.store.wave6.operator-evidence-input.v1"
STORE_AUTHORITY = "read_record_replay_propose_shadow_only"
STORE_CEILING = "store_resolved_operator_evidence_input_only"
STORE_CLAIM_SCOPE = (
    "store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model"
)
MODEL_ADMISSION_REFUSAL = "unrepaired_w5_presentation_gap_and_no_recognition_response"
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024

_DECIMAL = re.compile(r"[1-9][0-9]*\Z")
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
    "inputCensusBindingId",
    "inputCensusDocumentDigest",
    "inputCensus",
    "sourceOccurrenceId",
    "publicationId",
    "publicationDigest",
    "headDigest",
    "memoryOccurrenceId",
    "memoryOccurrenceDigest",
    "memorySessionId",
    "memorySubjectId",
    "presentationClaimId",
    "presentationClaimDigest",
    "pairingSessionId",
    "bindingId",
    "documentDigest",
    "operatorEvidenceInput",
    "acceptedCommitSeq",
    "firstStatus",
    "retryStatus",
    "storeResolvedInputCensus",
    "storeResolvedMemoryAct",
    "storeResolvedBrowserReport",
    "scriptedPresentationPath",
    "exactRetryClosed",
    "restartReverified",
    "actPresentationGapRetained",
    "presentationRepairsActGap",
    "sessionEquivalenceClaimed",
    "humanViewingVerified",
    "recognitionObserved",
    "operatorModelResolved",
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
    "inputCensusBindingId",
    "inputCensusDocumentDigest",
    "inputCensusCommitSeq",
    "sourceOccurrenceId",
    "publicationId",
    "publicationDigest",
    "publicationBytesDigest",
    "publicationCommitSeq",
    "headDigest",
    "headBytesDigest",
    "headCommitSeq",
    "memoryOccurrenceId",
    "memoryOccurrenceDigest",
    "memoryCommitSeq",
    "memoryQueueGeneration",
    "memoryOccurrence",
    "presentationClaimId",
    "presentationClaimDigest",
    "presentationClaimBytesDigest",
    "presentationCommitSeq",
    "pairingSessionId",
    "presentationClaim",
    "subjectId",
    "actPresentationGapRetained",
    "presentationRepairsActGap",
    "sessionEquivalenceClaimed",
    "humanViewingVerified",
    "recognitionObserved",
    "operatorModelResolved",
    "authority",
    "claimScope",
    "semanticCeiling",
)
_ACT_KEYS = (
    "actId",
    "sessionId",
    "occurredAt",
    "scene",
    "presentation",
    "kind",
    "subject",
    "assertion",
)
_SCENE_KEYS = ("sceneId", "sceneDigest", "catalogCutoff")
_GAP_KEYS = ("gapId", "scene", "reason", "detectedAt")
_CLAIM_KEYS = (
    "contract",
    "schemaVersion",
    "idempotencyKey",
    "clientPresentationId",
    "browserPageId",
    "presentationSeq",
    "publication",
    "head",
    "sourceOccurrenceId",
    "renderedSubjects",
    "renderedSubjectCount",
    "mountedAt",
    "clientClockId",
    "monotonicNs",
    "viewport",
    "documentVisibility",
    "documentHasFocus",
    "authority",
    "ceiling",
    "claimDigest",
)
_PUBLICATION_KEYS = (
    "publicationId",
    "publicationDigest",
    "publicationBytesDigest",
    "publicationCommitSeq",
)
_HEAD_KEYS = ("headDigest", "headBytesDigest", "headCommitSeq")
_VIEWPORT_KEYS = ("widthCssPx", "heightCssPx", "devicePixelRatioMilli")
_ACT_KINDS = {
    "notice",
    "inspect",
    "compare",
    "mark",
    "watch_flat",
    "arm_shadow",
    "declare_take_some",
    "declare_keep_remainder",
    "zap_intent",
    "declare_reentry",
    "declare_close",
    "correct",
}
_GAP_REASONS = {"not_mounted", "capture_failed", "navigation_unknown", "restart", "unavailable"}


class StoreOperatorEvidenceError(OperatorModelError):
    """The V22 report or its embedded exact store document is malformed or overclaims."""


@dataclass(frozen=True, slots=True)
class _StoreResolvedOperatorEvidenceInput:
    """Validated evidence packet that remains deliberately inadmissible as a model result."""

    report_digest: str
    document_digest: str
    document_bytes: bytes
    binding_id: str
    program_id: str
    input_census_binding_id: str
    source_occurrence_id: str
    publication_id: str
    memory_occurrence_id: str
    memory_session_id: str
    subject_id: str
    act_kind: str
    act_logical_tick: int
    presentation_gap_id: str
    presentation_gap_reason: str
    presentation_claim_id: str
    pairing_session_id: str
    browser_reported_at: datetime
    accepted_commit_seq: int
    model_admission_refusal: str = MODEL_ADMISSION_REFUSAL
    scene_binding_materialized: bool = False
    replay_materialized: bool = False
    human_viewing_verified: bool = False
    recognition_observed: bool = False
    operator_model_resolved: bool = False

    def __post_init__(self) -> None:
        _digest(self.report_digest, "validated report digest")
        _digest(self.document_digest, "validated document digest")
        if qualified_sha256_bytes(self.document_bytes) != self.document_digest:
            raise StoreOperatorEvidenceError("validated packet bytes differ from document digest")
        for value, context in (
            (self.binding_id, "validated binding id"),
            (self.program_id, "validated program id"),
            (self.input_census_binding_id, "validated census id"),
            (self.source_occurrence_id, "validated source occurrence id"),
            (self.publication_id, "validated publication id"),
            (self.memory_occurrence_id, "validated memory occurrence id"),
            (self.memory_session_id, "validated memory session id"),
            (self.subject_id, "validated subject id"),
            (self.presentation_gap_id, "validated presentation gap id"),
            (self.presentation_claim_id, "validated presentation claim id"),
            (self.pairing_session_id, "validated pairing session id"),
        ):
            _text(value, context)
        if (
            self.model_admission_refusal != MODEL_ADMISSION_REFUSAL
            or self.scene_binding_materialized
            or self.replay_materialized
            or self.human_viewing_verified
            or self.recognition_observed
            or self.operator_model_resolved
        ):
            raise StoreOperatorEvidenceError("validated store packet cannot self-promote")

    def validation_receipt(self) -> dict[str, Any]:
        """Return a compact non-promoting cross-runtime validation receipt."""

        return {
            "contract": "joshi.analysis.wave6-operator-evidence-validation/v1",
            "schemaVersion": 1,
            "status": "valid_nonpromoting",
            "authority": STORE_AUTHORITY,
            "semanticCeiling": "cross_runtime_store_input_validated_not_model_admitted",
            "reportDigest": self.report_digest,
            "documentDigest": self.document_digest,
            "bindingId": self.binding_id,
            "programId": self.program_id,
            "sourceOccurrenceId": self.source_occurrence_id,
            "publicationId": self.publication_id,
            "memoryOccurrenceId": self.memory_occurrence_id,
            "presentationClaimId": self.presentation_claim_id,
            "acceptedCommitSeq": str(self.accepted_commit_seq),
            "modelAdmissionRefusal": self.model_admission_refusal,
            "sceneBindingMaterialized": self.scene_binding_materialized,
            "replayMaterialized": self.replay_materialized,
            "humanViewingVerified": self.human_viewing_verified,
            "recognitionObserved": self.recognition_observed,
            "operatorModelResolved": self.operator_model_resolved,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StoreOperatorEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise StoreOperatorEvidenceError(f"non-finite JSON scalar is forbidden: {value}")


def _exact_json(raw: bytes, context: str, *, allow_newline: bool) -> dict[str, Any]:
    body = raw[:-1] if allow_newline and raw.endswith(b"\n") else raw
    if not body or body != body.strip() or (allow_newline and raw not in {body, body + b"\n"}):
        raise StoreOperatorEvidenceError(f"{context} is not exact compact JSON")
    try:
        value = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreOperatorEvidenceError(f"{context} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise StoreOperatorEvidenceError(f"{context} must be a JSON object")
    if _ordered_json_bytes(value) != body:
        raise StoreOperatorEvidenceError(f"{context} is not canonical ordered JSON")
    return value


def _ordered_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StoreOperatorEvidenceError(f"{context} must be an object")
    return value


def _keys(value: dict[str, Any], expected: tuple[str, ...], context: str) -> None:
    if tuple(value) != expected:
        raise StoreOperatorEvidenceError(f"{context} fields or canonical order differ")


def _text(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value.encode("utf-8")) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise StoreOperatorEvidenceError(f"{context} must be bounded non-control text")
    return value


def _digest(value: Any, context: str) -> str:
    text = _text(value, context)
    if (
        len(text) != 71
        or not text.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise StoreOperatorEvidenceError(f"{context} must be sha256:<64 lowercase hex>")
    return text


def _positive_decimal(value: Any, context: str) -> int:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise StoreOperatorEvidenceError(f"{context} must be a positive canonical decimal string")
    parsed = int(value)
    if parsed > (1 << 64) - 1:
        raise StoreOperatorEvidenceError(f"{context} exceeds u64")
    return parsed


def _exact_bool(value: Any, expected: bool, context: str) -> None:
    if value is not expected:
        raise StoreOperatorEvidenceError(f"{context} must be {str(expected).lower()}")


def _utc(value: Any, context: str) -> datetime:
    text = _text(value, context)
    if not text.endswith("Z"):
        raise StoreOperatorEvidenceError(f"{context} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise StoreOperatorEvidenceError(f"{context} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.astimezone(UTC) != parsed:
        raise StoreOperatorEvidenceError(f"{context} must be UTC")
    return parsed


def _validate_act_kind(value: Any) -> str:
    if isinstance(value, str) and value in _ACT_KINDS:
        return value
    if isinstance(value, dict) and tuple(value) == ("external_manual_execution_escape",):
        detail = _object(value["external_manual_execution_escape"], "manual escape")
        _keys(detail, ("reason",), "manual escape")
        _text(detail["reason"], "manual escape reason")
        return "external_manual_execution_escape"
    raise StoreOperatorEvidenceError("operator act kind is not in the frozen W5 vocabulary")


def _validate_document(document: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    _keys(document, _DOCUMENT_KEYS, "operator-evidence document")
    if document["contract"] != STORE_INPUT_CONTRACT or document["schemaVersion"] != 1:
        raise StoreOperatorEvidenceError("operator-evidence document contract differs")
    if (
        document["authority"] != STORE_AUTHORITY
        or document["claimScope"] != STORE_CLAIM_SCOPE
        or document["semanticCeiling"] != STORE_CEILING
    ):
        raise StoreOperatorEvidenceError("operator-evidence document crosses its authority ceiling")
    _exact_bool(document["actPresentationGapRetained"], True, "actPresentationGapRetained")
    for key in (
        "presentationRepairsActGap",
        "sessionEquivalenceClaimed",
        "humanViewingVerified",
        "recognitionObserved",
        "operatorModelResolved",
    ):
        _exact_bool(document[key], False, key)

    for key in (
        "inputCensusDocumentDigest",
        "publicationDigest",
        "publicationBytesDigest",
        "headDigest",
        "headBytesDigest",
        "memoryOccurrenceDigest",
        "presentationClaimDigest",
        "presentationClaimBytesDigest",
    ):
        _digest(document[key], key)
    for key in (
        "bindingId",
        "programId",
        "inputCensusBindingId",
        "sourceOccurrenceId",
        "publicationId",
        "memoryOccurrenceId",
        "presentationClaimId",
        "pairingSessionId",
        "subjectId",
    ):
        _text(document[key], key)

    census_commit = _positive_decimal(document["inputCensusCommitSeq"], "input census commit")
    publication_commit = _positive_decimal(document["publicationCommitSeq"], "publication commit")
    head_commit = _positive_decimal(document["headCommitSeq"], "head commit")
    memory_commit = _positive_decimal(document["memoryCommitSeq"], "memory commit")
    _positive_decimal(document["memoryQueueGeneration"], "memory queue generation")
    presentation_commit = _positive_decimal(
        document["presentationCommitSeq"], "presentation commit"
    )
    accepted_commit = _positive_decimal(report["acceptedCommitSeq"], "accepted commit")
    if not publication_commit < head_commit < memory_commit < presentation_commit < accepted_commit:
        raise StoreOperatorEvidenceError("operator-evidence commit order is not strictly closed")
    if census_commit >= accepted_commit:
        raise StoreOperatorEvidenceError("input census was not committed before operator input")

    memory = _object(document["memoryOccurrence"], "memory occurrence")
    _keys(memory, ("kind", "value"), "memory occurrence")
    if memory["kind"] != "operator_act":
        raise StoreOperatorEvidenceError("operator-evidence packet requires an operator_act")
    act = _object(memory["value"], "operator act")
    _keys(act, _ACT_KEYS, "operator act")
    act_id = _text(act["actId"], "act id")
    _text(act["sessionId"], "act session id")
    _positive_decimal(act["occurredAt"], "act logical tick")
    act_kind = _validate_act_kind(act["kind"])
    subject = _text(act["subject"], "act subject")
    if act["assertion"] is not None:
        raise StoreOperatorEvidenceError("V22 operator input must not invent an assertion")
    if document["memoryOccurrenceId"] != f"act:{act_id}":
        raise StoreOperatorEvidenceError("memory occurrence identity differs from the exact act")
    if document["subjectId"] != subject:
        raise StoreOperatorEvidenceError("operator-evidence subject differs from the exact act")
    if qualified_sha256_bytes(_ordered_json_bytes(memory)) != document["memoryOccurrenceDigest"]:
        raise StoreOperatorEvidenceError("embedded memory occurrence digest differs")

    scene_envelope = _object(act["scene"], "act scene")
    _keys(scene_envelope, ("status", "value"), "act scene")
    if scene_envelope["status"] != "committed":
        raise StoreOperatorEvidenceError("operator act lacks a committed scene")
    scene = _object(scene_envelope["value"], "committed scene")
    _keys(scene, _SCENE_KEYS, "committed scene")
    if (
        scene["sceneId"] != document["publicationId"]
        or scene["sceneDigest"] != document["publicationDigest"]
        or _positive_decimal(scene["catalogCutoff"], "scene catalog cutoff") != publication_commit
    ):
        raise StoreOperatorEvidenceError("committed scene differs from headed publication")

    presentation = _object(act["presentation"], "act presentation")
    _keys(presentation, ("status", "value"), "act presentation")
    if presentation["status"] != "gap":
        raise StoreOperatorEvidenceError("later browser report cannot replace the original gap")
    gap = _object(presentation["value"], "presentation gap")
    _keys(gap, _GAP_KEYS, "presentation gap")
    _text(gap["gapId"], "presentation gap id")
    if gap["scene"] != scene:
        raise StoreOperatorEvidenceError("presentation gap scene differs from act scene")
    if gap["reason"] not in _GAP_REASONS:
        raise StoreOperatorEvidenceError("presentation gap reason is not recognized")
    _positive_decimal(gap["detectedAt"], "presentation gap logical tick")

    claim = _object(document["presentationClaim"], "presentation claim")
    _keys(claim, _CLAIM_KEYS, "presentation claim")
    if (
        claim["contract"] != "joshi.cockpit.v2.browser_presentation_claim"
        or claim["schemaVersion"] != 1
        or claim["authority"] != "read_only_no_execution"
        or claim["ceiling"] != "browser_reported_not_pixel_verified"
    ):
        raise StoreOperatorEvidenceError("browser report crosses its authority-free contract")
    page_id = _text(claim["browserPageId"], "browser page id")
    presentation_seq = _positive_decimal(claim["presentationSeq"], "presentation sequence")
    if claim["idempotencyKey"] != f"browser-presentation:{page_id}:{presentation_seq}":
        raise StoreOperatorEvidenceError("browser report idempotency identity differs")
    if claim["clientPresentationId"] != document["presentationClaimId"]:
        raise StoreOperatorEvidenceError("browser report identity differs from document")

    publication = _object(claim["publication"], "presented publication")
    _keys(publication, _PUBLICATION_KEYS, "presented publication")
    if publication != {
        "publicationId": document["publicationId"],
        "publicationDigest": document["publicationDigest"],
        "publicationBytesDigest": document["publicationBytesDigest"],
        "publicationCommitSeq": document["publicationCommitSeq"],
    }:
        raise StoreOperatorEvidenceError("browser report publication differs from document")
    head = _object(claim["head"], "presented head")
    _keys(head, _HEAD_KEYS, "presented head")
    if head != {
        "headDigest": document["headDigest"],
        "headBytesDigest": document["headBytesDigest"],
        "headCommitSeq": document["headCommitSeq"],
    }:
        raise StoreOperatorEvidenceError("browser report head differs from document")
    if claim["sourceOccurrenceId"] != document["sourceOccurrenceId"]:
        raise StoreOperatorEvidenceError("browser report source differs from document")

    rendered = claim["renderedSubjects"]
    if (
        not isinstance(rendered, list)
        or not rendered
        or any(not isinstance(item, str) for item in rendered)
        or rendered != sorted(set(rendered))
        or _positive_decimal(claim["renderedSubjectCount"], "rendered subject count")
        != len(rendered)
        or subject not in rendered
    ):
        raise StoreOperatorEvidenceError("browser report does not close its rendered subjects")
    for rendered_subject in rendered:
        _text(rendered_subject, "rendered subject")
    mounted_at = _utc(claim["mountedAt"], "browser mountedAt")
    _text(claim["clientClockId"], "client clock id")
    _positive_decimal(claim["monotonicNs"], "browser monotonic clock")
    viewport = _object(claim["viewport"], "browser viewport")
    _keys(viewport, _VIEWPORT_KEYS, "browser viewport")
    width = _positive_decimal(viewport["widthCssPx"], "viewport width")
    height = _positive_decimal(viewport["heightCssPx"], "viewport height")
    ratio = _positive_decimal(viewport["devicePixelRatioMilli"], "viewport ratio")
    if width > 32_768 or height > 32_768 or not 100 <= ratio <= 10_000:
        raise StoreOperatorEvidenceError("browser viewport exceeds its bounded contract")
    if claim["documentVisibility"] not in {"visible", "hidden"}:
        raise StoreOperatorEvidenceError("browser document visibility is not recognized")
    if not isinstance(claim["documentHasFocus"], bool):
        raise StoreOperatorEvidenceError("browser focus claim must be boolean")
    if claim["claimDigest"] != document["presentationClaimDigest"]:
        raise StoreOperatorEvidenceError("browser semantic digest differs from document")
    claim_material = {key: value for key, value in claim.items() if key != "claimDigest"}
    if qualified_sha256_bytes(_ordered_json_bytes(claim_material)) != claim["claimDigest"]:
        raise StoreOperatorEvidenceError("browser report self-digest differs")
    if (
        qualified_sha256_bytes(_ordered_json_bytes(claim))
        != document["presentationClaimBytesDigest"]
    ):
        raise StoreOperatorEvidenceError("browser report physical bytes digest differs")

    identity_material = [
        "joshi.store.wave6_operator_evidence_input_identity.v1",
        document["programId"],
        document["inputCensusBindingId"],
        document["memoryOccurrenceId"],
        document["presentationClaimId"],
    ]
    expected_binding = (
        "wave6-operator-input:"
        + qualified_sha256_bytes(canonical_json_bytes(identity_material))[7:]
    )
    if document["bindingId"] != expected_binding:
        raise StoreOperatorEvidenceError("operator-evidence binding identity differs")

    return {
        "act": act,
        "act_kind": act_kind,
        "gap": gap,
        "claim": claim,
        "mounted_at": mounted_at,
        "accepted_commit": accepted_commit,
    }


def validate_store_operator_evidence_report(
    report_path: str | Path,
) -> _StoreResolvedOperatorEvidenceInput:
    """Validate one exact Core V22 report without promoting it into the operator model."""

    path = Path(report_path)
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise StoreOperatorEvidenceError("operator-evidence report is empty or oversized")
    report = _exact_json(raw, "operator-evidence report", allow_newline=True)
    _keys(report, _REPORT_KEYS, "operator-evidence report")
    if (
        report["contract"] != CORE_REPORT_CONTRACT
        or report["schemaVersion"] != 1
        or report["status"] != "useful_partial"
        or report["authority"] != STORE_AUTHORITY
        or report["semanticCeiling"] != STORE_CEILING
        or report["claimScope"] != STORE_CLAIM_SCOPE
        or report["catalogSchema"] != "joshi.sqlite.v22"
    ):
        raise StoreOperatorEvidenceError("Core operator-evidence report contract differs")
    for key in (
        "storeResolvedInputCensus",
        "storeResolvedMemoryAct",
        "storeResolvedBrowserReport",
        "scriptedPresentationPath",
        "exactRetryClosed",
        "restartReverified",
        "actPresentationGapRetained",
    ):
        _exact_bool(report[key], True, key)
    for key in (
        "presentationRepairsActGap",
        "sessionEquivalenceClaimed",
        "humanViewingVerified",
        "recognitionObserved",
        "operatorModelResolved",
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
        raise StoreOperatorEvidenceError("Core report does not close exact retry")
    for key in (
        "programRegistrationDigest",
        "inputCensusDocumentDigest",
        "publicationDigest",
        "headDigest",
        "memoryOccurrenceDigest",
        "presentationClaimDigest",
        "documentDigest",
    ):
        _digest(report[key], key)
    for key in (
        "programId",
        "inputCensusBindingId",
        "sourceOccurrenceId",
        "publicationId",
        "memoryOccurrenceId",
        "memorySessionId",
        "memorySubjectId",
        "presentationClaimId",
        "pairingSessionId",
        "bindingId",
    ):
        _text(report[key], key)

    document = _object(report["operatorEvidenceInput"], "embedded operator-evidence input")
    document_bytes = _ordered_json_bytes(document)
    if len(document_bytes) > MAX_DOCUMENT_BYTES:
        raise StoreOperatorEvidenceError("embedded operator-evidence document is oversized")
    if qualified_sha256_bytes(document_bytes) != report["documentDigest"]:
        raise StoreOperatorEvidenceError("embedded operator-evidence document digest differs")
    resolved = _validate_document(document, report)
    try:
        census = validate_embedded_store_input_census_document(
            report["inputCensus"], document["inputCensusDocumentDigest"]
        )
    except StoreInputCensusError as error:
        raise StoreOperatorEvidenceError(f"embedded input census is invalid: {error}") from error
    census_commit = _positive_decimal(document["inputCensusCommitSeq"], "input census commit")
    if (
        census.binding_id != document["inputCensusBindingId"]
        or census.program_id != document["programId"]
        or census.source_occurrence_id != document["sourceOccurrenceId"]
        or census.source_created_commit_seq >= census_commit
        or census_commit >= resolved["accepted_commit"]
    ):
        raise StoreOperatorEvidenceError(
            "embedded input census differs from the operator-evidence lineage"
        )

    exact_pairs = (
        ("programId", "programId"),
        ("inputCensusBindingId", "inputCensusBindingId"),
        ("inputCensusDocumentDigest", "inputCensusDocumentDigest"),
        ("sourceOccurrenceId", "sourceOccurrenceId"),
        ("publicationId", "publicationId"),
        ("publicationDigest", "publicationDigest"),
        ("headDigest", "headDigest"),
        ("memoryOccurrenceId", "memoryOccurrenceId"),
        ("memoryOccurrenceDigest", "memoryOccurrenceDigest"),
        ("presentationClaimId", "presentationClaimId"),
        ("presentationClaimDigest", "presentationClaimDigest"),
        ("pairingSessionId", "pairingSessionId"),
        ("bindingId", "bindingId"),
    )
    if any(report[outer] != document[inner] for outer, inner in exact_pairs):
        raise StoreOperatorEvidenceError("Core report scalars differ from embedded store document")
    act = resolved["act"]
    if report["memorySessionId"] != act["sessionId"] or report["memorySubjectId"] != act["subject"]:
        raise StoreOperatorEvidenceError("Core report act lineage differs from embedded act")

    gap = resolved["gap"]
    return _StoreResolvedOperatorEvidenceInput(
        report_digest=qualified_sha256_bytes(raw),
        document_digest=report["documentDigest"],
        document_bytes=document_bytes,
        binding_id=document["bindingId"],
        program_id=document["programId"],
        input_census_binding_id=document["inputCensusBindingId"],
        source_occurrence_id=document["sourceOccurrenceId"],
        publication_id=document["publicationId"],
        memory_occurrence_id=document["memoryOccurrenceId"],
        memory_session_id=act["sessionId"],
        subject_id=document["subjectId"],
        act_kind=resolved["act_kind"],
        act_logical_tick=_positive_decimal(act["occurredAt"], "act logical tick"),
        presentation_gap_id=gap["gapId"],
        presentation_gap_reason=gap["reason"],
        presentation_claim_id=document["presentationClaimId"],
        pairing_session_id=document["pairingSessionId"],
        browser_reported_at=resolved["mounted_at"],
        accepted_commit_seq=resolved["accepted_commit"],
    )
