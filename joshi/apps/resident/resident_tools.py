"""The resident's whole reach: four read/evidence tools over one paired core.

This module is the jail's inventory. Every capability the resident has is a
method here, every method is a thin wrapper over the loopback routes the
proven plumbing already speaks, and nothing here touches the filesystem,
the network beyond the paired core, or any execution surface. The Agent SDK
engine exposes exactly these through an in-process MCP server and disables
every host tool, so this file IS the resident's world.

Testable network-free: everything routes through the session object's
read_scene / get / append_command, so tests hand in a fake.
"""

from __future__ import annotations

import json
import uuid

import joshi_evidence

# Above this, a scene's candle arrays are elided (with exact counts and the
# bar-time range stated) so one tool result cannot drown a turn. The scene
# route itself is bounded at 4MB; a turn is not the place for all of it.
MAX_SCENE_TEXT = 120_000
# A live board scene can carry ~1000 subjects; candle elision alone leaves it
# megabytes wide. When still over MAX_SCENE_TEXT, candidates beyond this many
# (in served order) are elided with the exact count and boundary ids stated.
MAX_SCENE_CANDIDATES = 24

FEED_ROUTE = "/api/v1/glass/scenes"
SCENE_ROUTE = "/api/v1/glass/scenes/{scene_id}"
CANDIDATE_ROUTE = "/api/v1/glass/scenes/{scene_id}/candidates/{candidate_id}"
JOURNAL_ROUTE = "/api/v1/operator/commands?sceneId={scene_id}"

# The feed accumulates every scene the core ever derived (hundreds on a
# long-lived core) and a turn only ever needs the newest few. Bounded so one
# tool result cannot drown the turn; the total is always stated.
MAX_FEED_SCENES = 15


class ToolError(Exception):
    """A refusal the resident should read verbatim, not a crash."""


class ResidentTools:
    """One paired session plus the client-command identity discipline.

    clientSessionId is minted once per process; clientCommandSeq is a
    monotonic counter (the store refuses a reused seq within a session);
    both are the resident's own writing identity in the ledger.
    """

    def __init__(self, session, *, client_session_id: str | None = None):
        self.session = session
        self.client_session_id = client_session_id or f"resident-{uuid.uuid4().hex}"
        self.clock_id = f"resident-clock-{uuid.uuid4().hex[:12]}"
        self._seq = 0
        # Set when a read/write comes back 401/503: the pairing capability is
        # no longer honored and the driver must re-pair with a fresh code.
        self.session_lost: str | None = None

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _mark_if_lost(self, status: int, raw: bytes) -> None:
        if status in (401, 503):
            detail = raw.decode("utf-8", "replace")[:200]
            self.session_lost = f"HTTP {status}: {detail}"

    # ------------------------------------------------------------------
    # read_scene
    # ------------------------------------------------------------------
    def read_scene(self, scene_id: str) -> str:
        """One immutable scene: the snapshot envelope with its digest.

        Uses the path route (no replay-mode parameter): it serves durable
        scenes and the mounted live surface alike.
        """
        status, raw = self.session.get(SCENE_ROUTE.format(scene_id=scene_id))
        self._mark_if_lost(status, raw)
        if status != 200:
            raise ToolError(_problem_text("scene read refused", status, raw))
        snapshot = json.loads(raw)
        view = snapshot.get("view", {})
        header = {
            "sceneId": view.get("sceneId", scene_id),
            "viewDigest": snapshot.get("snapshotDigest"),
            "note": "cite this sceneId and viewDigest in any journal entry about this scene",
        }
        body = json.dumps(view, indent=1)
        if len(body) > MAX_SCENE_TEXT:
            view, elisions = _elide_candles(view)
            body = json.dumps(view, indent=1)
            header["elided"] = elisions
        if len(body) > MAX_SCENE_TEXT:
            view, kept, dropped = _elide_candidates(view)
            body = json.dumps(view, indent=1)
            header["candidatesElided"] = dropped
            header["candidatesKept"] = kept
        return json.dumps(header, indent=1) + "\n" + body

    # ------------------------------------------------------------------
    # read_candidate
    # ------------------------------------------------------------------
    def read_candidate(self, scene_id: str, candidate_id: str) -> str:
        """One candidate sliced verbatim out of an immutable scene.

        The slice is a read projection: its viewDigest is the FULL view's
        digest, so any journal entry still cites (sceneId, that digest) —
        acts bind to the scene, never to a slice. A 404 carries a meaning
        worth reading exactly: `candidate_not_rendered` states the candidate
        was not rendered in this scene (an elided candidate remains observed
        in the catalog); any other 404/405 means this core predates the
        slice route, and read_scene is the fallback.
        """
        status, raw = self.session.get(CANDIDATE_ROUTE.format(
            scene_id=scene_id, candidate_id=candidate_id))
        self._mark_if_lost(status, raw)
        if status in (404, 405):
            try:
                problem = json.loads(raw)
            except ValueError:
                problem = {}
            if problem.get("code") == "candidate_not_rendered":
                return json.dumps({
                    "rendered": False,
                    "sceneId": scene_id,
                    "candidateId": candidate_id,
                    "problem": problem,
                    "note": ("the core states this candidate was not rendered "
                             "in this scene — an elided candidate remains "
                             "observed in the catalog; this is a render-bound "
                             "statement, not evidence of absence from the "
                             "market"),
                }, indent=1)
            return json.dumps({
                "sliceServed": False,
                "note": ("candidate slice route not served: this joshi-core "
                         "predates it (older core). read_scene is the "
                         "fallback; its wide-scene elisions state exactly "
                         "what they drop."),
            }, indent=1)
        if status != 200:
            raise ToolError(_problem_text("candidate slice read refused",
                                          status, raw))
        slice_doc = json.loads(raw)
        header = {
            "sceneId": slice_doc.get("sceneId", scene_id),
            "viewDigest": slice_doc.get("viewDigest"),
            "renderedOrdinal": slice_doc.get("renderedOrdinal"),
            "renderedCandidateCount": slice_doc.get("renderedCandidateCount"),
            "renderedAt": slice_doc.get("renderedAt"),
            "note": ("viewDigest is the FULL view's digest — cite this "
                     "sceneId and viewDigest in any journal entry; acts bind "
                     "to the scene, never to a slice"),
        }
        candidate = slice_doc.get("candidate") or {}
        body = json.dumps(candidate, indent=1)
        if len(body) > MAX_SCENE_TEXT:
            shell = {"payload": {"candidates": [candidate]}}
            shell, elisions = _elide_candles(shell)
            candidate = shell["payload"]["candidates"][0]
            body = json.dumps(candidate, indent=1)
            header["elided"] = elisions
        return json.dumps(header, indent=1) + "\n" + body

    # ------------------------------------------------------------------
    # read_journal
    # ------------------------------------------------------------------
    def read_journal(self, scene_id: str) -> str:
        """Every durable operator command bound to one scene, in commit order.

        The route serves exact retained payload bytes; this renders them
        without summarizing. sceneRetention is part of the answer: an empty
        list over `served_not_yet_durable` means nothing has been said yet,
        which is a statement, not a blank.
        """
        status, raw = self.session.get(JOURNAL_ROUTE.format(scene_id=scene_id))
        self._mark_if_lost(status, raw)
        if status != 200:
            raise ToolError(_problem_text("journal read refused", status, raw))
        body = json.loads(raw)
        commands = body.get("commands", [])
        out = {
            "sceneId": body.get("sceneId", scene_id),
            "sceneRetention": body.get("sceneRetention"),
            "commandCount": len(commands),
            "commands": [_render_command(c) for c in commands],
        }
        if not commands:
            out["note"] = ("no durable operator command names this scene yet — "
                           "nothing has been said, which is itself the record")
        return json.dumps(out, indent=1)

    # ------------------------------------------------------------------
    # append_note
    # ------------------------------------------------------------------
    def append_note(self, scene_id: str, view_digest: str, words: str) -> str:
        """One journal entry: the resident's words, verbatim, durable.

        Bound to the exact (sceneId, viewDigest) that was read — the server
        refuses a digest that does not match the retained scene bytes, so an
        entry can never claim to be about bytes its author did not see.
        """
        exact = (words or "").strip()
        if not exact:
            raise ToolError("refused client-side: a journal entry with no words "
                            "is not recorded as a blank")
        if not (view_digest or "").startswith("sha256:"):
            raise ToolError("refused client-side: view_digest must be the "
                            "sha256:... digest read_scene reported")
        command_id = f"command-resident-{uuid.uuid4().hex}"
        body = joshi_evidence.journal_entry_command(
            scene_id=scene_id,
            view_digest=view_digest,
            words=exact,
            command_id=command_id,
            idempotency_key=f"retry-{command_id}",
            client_session_id=self.client_session_id,
            client_command_seq=self._next_seq(),
            clock_id=self.clock_id,
            monotonic_ns=joshi_evidence.monotonic_ns(),
            issued_at=joshi_evidence.wire_now(),
        )
        status, receipt = self.session.append_command(body)
        if status in (401, 503):
            self.session_lost = f"HTTP {status}: {json.dumps(receipt)[:200]}"
        if status not in (200, 202):
            raise ToolError(_problem_text("journal entry refused by the core",
                                          status, json.dumps(receipt).encode()))
        return json.dumps({
            "durable": True,
            "commitSeq": receipt.get("commitSeq"),
            "status": receipt.get("status"),
            "commandId": receipt.get("commandId", command_id),
            "sceneId": scene_id,
            "viewDigest": view_digest,
            "words": exact,
        }, indent=1)

    # ------------------------------------------------------------------
    # list_scenes
    # ------------------------------------------------------------------
    def list_scenes(self) -> str:
        """The scene feed, newest first — where the core serves one.

        A sibling lane is landing the feed route; an older core answers 404
        or 405 there, and the honest report is "feed not served", never a
        fabricated list.
        """
        status, raw = self.session.get(FEED_ROUTE)
        self._mark_if_lost(status, raw)
        if status in (404, 405):
            return json.dumps({
                "feedServed": False,
                "note": ("feed not served: this joshi-core does not mount a "
                         "scene feed route (older core). The scene named in "
                         "your turn context is the only scene known here."),
            }, indent=1)
        if status != 200:
            raise ToolError(_problem_text("scene feed read refused", status, raw))
        try:
            body = json.loads(raw)
        except ValueError as error:
            raise ToolError(f"scene feed answered 200 with unparseable bytes: {error}")
        scenes = body.get("scenes")
        if not isinstance(scenes, list):
            return json.dumps({"feedServed": True, "feed": body}, indent=1)
        out = {
            "feedServed": True,
            "scenesTotal": len(scenes),
            "newestFirst": scenes[:MAX_FEED_SCENES],
        }
        if len(scenes) > MAX_FEED_SCENES:
            out["note"] = (f"showing the newest {MAX_FEED_SCENES} of "
                           f"{len(scenes)} scenes; each entry keeps its exact "
                           f"feed fields; older scenes exist and are not shown")
        extra = {key: value for key, value in body.items() if key != "scenes"}
        if extra:
            out["feedEnvelope"] = extra
        return json.dumps(out, indent=1)


# ----------------------------------------------------------------------
# rendering helpers
# ----------------------------------------------------------------------

def _problem_text(what: str, status: int, raw: bytes) -> str:
    detail = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return f"{what} (HTTP {status}): {detail[:600]}"


def _render_command(command: dict) -> dict:
    """One stored command with its verbatim words surfaced, nothing invented.

    The payload rides along in full — it is exact retained bytes and it is
    the resident's memory. `words` just lifts the stated free-text fields so
    a journal reads as a journal.
    """
    payload = command.get("payload") or {}
    context = payload.get("context") or {}
    words = []
    if context.get("whyNow") is not None:
        words.append({"label": "Why now", "words": context["whyNow"]})
    if context.get("note") is not None:
        words.append({"label": "Note", "words": context["note"]})
    return {
        "commitSeq": command.get("commitSeq"),
        "commandKind": command.get("commandKind"),
        "uiLabel": context.get("uiLabel"),
        "subject": command.get("subject"),
        "issuedAt": command.get("issuedAt"),
        "receivedAt": command.get("receivedAt"),
        "commandId": command.get("commandId"),
        "clientSessionId": command.get("clientSessionId"),
        "scene": command.get("scene"),
        "words": words,
        "payload": payload,
    }


def _elide_candidates(view: dict) -> tuple[dict, int, dict]:
    """Keep the first MAX_SCENE_CANDIDATES candidates in served order; state
    exactly what was dropped (count and boundary ids), never silently.

    Returns (view, kept_count, dropped_summary)."""
    view = json.loads(json.dumps(view))  # deep copy; never mutate the caller's
    payload = view.get("payload") or {}
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) <= MAX_SCENE_CANDIDATES:
        return view, len(candidates or []), {"count": 0}
    dropped = candidates[MAX_SCENE_CANDIDATES:]
    dropped_summary = {
        "count": len(dropped),
        "firstDroppedId": (dropped[0] or {}).get("id"),
        "lastDroppedId": (dropped[-1] or {}).get("id"),
        "note": (f"scene too wide for one turn: kept the first "
                 f"{MAX_SCENE_CANDIDATES} candidates in served order, "
                 f"dropped {len(dropped)} — they exist and are not shown; "
                 f"read any one of them in full with read_candidate"),
    }
    payload["candidates"] = candidates[:MAX_SCENE_CANDIDATES]
    return view, MAX_SCENE_CANDIDATES, dropped_summary


def _elide_candles(view: dict) -> tuple[dict, list[dict]]:
    """Replace oversized candle arrays with stated, exact summaries.

    Never fabricates: every elision names the candidate, the bar count, and
    the first/last bar time actually present in the dropped array.
    """
    view = json.loads(json.dumps(view))  # deep copy; never mutate the caller's
    elisions = []
    candidates = (view.get("payload") or {}).get("candidates") or []
    for candidate in candidates:
        candles = candidate.get("candles")
        if not isinstance(candles, list) or len(candles) <= 16:
            continue
        first, last = candles[0], candles[-1]
        elisions.append({
            "candidateId": candidate.get("id"),
            "barsElided": len(candles),
            "firstBar": first,
            "lastBar": last,
        })
        candidate["candles"] = (
            f"[{len(candles)} bars elided for turn size; first and last "
            f"retained in the elision note above]")
    return view, elisions
