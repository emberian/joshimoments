"""Build canonical evidence-only operator commands for joshi-core.

The server admits a command only if its bytes are the ONE canonical
representation (ValidatedOperatorCommandV1::parse_exact refuses non-canonical
bytes). So the JSON here is emitted in the exact struct field order that
apps/core / joshi-operator re-serialize, with compact separators and no key
sorting — matching serde_json's output for CanonicalCommand.

Field order is load-bearing and comes straight from
crates/joshi-operator/src/command.rs::CanonicalCommand.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone


def wire_now() -> str:
    """joshi-domain wire timestamp: microsecond precision, always 6 digits, Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def capture_context(*, ui_label: str, why_now: str, note: str,
                    confidence_ppm: str | None = None,
                    urgency: str | None = None) -> dict:
    # CaptureContext field order: uiLabel, uiLabelVersion, confidencePpm, urgency, whyNow, note.
    return {
        "uiLabel": ui_label,
        "uiLabelVersion": "1",
        "confidencePpm": confidence_ppm,
        "urgency": urgency,
        "whyNow": why_now,
        "note": note,
    }


def record_annotation_command(*, scene_id: str, view_digest: str,
                              candidate_id: str, series_id: str,
                              anchor_at: str, context: dict,
                              annotation_id: str, command_id: str,
                              idempotency_key: str, client_session_id: str,
                              client_command_seq: int, clock_id: str,
                              monotonic_ns: int, issued_at: str) -> bytes:
    """Canonical bytes for one record_annotation act bound to an exact scene."""
    # Order mirrors CanonicalCommand exactly; do not sort keys.
    command = {
        "contract": "joshi.operator.command",
        "schemaVersion": 1,
        "commandId": command_id,
        "idempotencyKey": idempotency_key,
        "clientSessionId": client_session_id,
        "clientCommandSeq": str(client_command_seq),
        "scene": {"sceneId": scene_id, "viewDigest": view_digest},
        "issuedAt": issued_at,
        "clientClock": {"clockId": clock_id, "monotonicNs": str(monotonic_ns)},
        "commandKind": "record_annotation",
        "subject": {"kind": "candidate", "key": candidate_id},
        "payload": {
            "context": context,
            "annotationId": annotation_id,
            "chart": {
                "candidateId": candidate_id,
                "seriesId": series_id,
                "anchor": {"anchorKind": "time", "at": anchor_at},
            },
        },
        "authorityClass": "evidence_only",
        "effectCeiling": "observe_only",
    }
    # separators without spaces == serde_json compact; ensure_ascii off so any
    # non-ASCII note bytes match serde's raw UTF-8 (our text here is ASCII).
    return json.dumps(command, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def monotonic_ns() -> int:
    return time.monotonic_ns()


# -- the exocortex journal entry -----------------------------------------
#
# A journal entry is an ordinary record_focus command whose words travel
# verbatim in the frozen capture context. The label is the WHOLE
# discriminator between an entry and any other focus record, so it is
# frozen here and mirrored byte for byte by JOURNAL_UI_LABEL in
# apps/core/src/live_journal.rs and apps/glass/src/operator/journal.ts.

JOURNAL_UI_LABEL = "Journal entry"
JOURNAL_UI_LABEL_VERSION = "1"
# The frozen operator context bounds a note at 4000 UTF-16 units
# (joshi-operator command.rs::validate_context).
MAX_JOURNAL_ENTRY_LENGTH = 4_000


def utf16_units(words: str) -> int:
    """Length in UTF-16 code units — the unit the frozen contract counts."""
    return len(words.encode("utf-16-le")) // 2


def journal_entry_command(*, scene_id: str, view_digest: str, words: str,
                          command_id: str, idempotency_key: str,
                          client_session_id: str, client_command_seq: int,
                          clock_id: str, monotonic_ns: int,
                          issued_at: str) -> bytes:
    """Canonical bytes for one journal entry over an exact served scene.

    The subject is the scene itself ({kind: "scene", key: sceneId}): an
    entry is usually about the composition on screen, not one coin. Empty
    words are refused here, client-side, because a blank where words belong
    reads later as "nothing was said".

    Mirrors apps/core/src/live_journal.rs::record_focus_bytes exactly.
    """
    exact = words.strip()
    if not exact:
        raise ValueError("a journal entry with no words is refused, not recorded as a blank")
    if utf16_units(exact) > MAX_JOURNAL_ENTRY_LENGTH:
        raise ValueError(
            f"a journal entry is limited to {MAX_JOURNAL_ENTRY_LENGTH} UTF-16 "
            f"units by the frozen operator context")
    command = {
        "contract": "joshi.operator.command",
        "schemaVersion": 1,
        "commandId": command_id,
        "idempotencyKey": idempotency_key,
        "clientSessionId": client_session_id,
        "clientCommandSeq": str(client_command_seq),
        "scene": {"sceneId": scene_id, "viewDigest": view_digest},
        "issuedAt": issued_at,
        "clientClock": {"clockId": clock_id, "monotonicNs": str(monotonic_ns)},
        "commandKind": "record_focus",
        "subject": {"kind": "scene", "key": scene_id},
        "payload": {
            "context": {
                "uiLabel": JOURNAL_UI_LABEL,
                "uiLabelVersion": JOURNAL_UI_LABEL_VERSION,
                # Nothing beyond the words is asked for. Structure, if it
                # ever exists, is derived later from the words; it is never
                # demanded at the moment of saying them.
                "confidencePpm": None,
                "urgency": None,
                "whyNow": None,
                "note": exact,
            },
            "dwellMilliseconds": None,
        },
        "authorityClass": "evidence_only",
        "effectCeiling": "observe_only",
    }
    return json.dumps(command, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
