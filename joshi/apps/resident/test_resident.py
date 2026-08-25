# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Network-free tests for the resident's evidence bytes and tool surface.

Run:  uv run --no-project apps/resident/test_resident.py
(or plain `python3 apps/resident/test_resident.py`). Nothing here touches a
socket: the pairing session is faked, and the canonical-bytes expectations
are frozen against the byte template in
apps/core/src/live_journal.rs::record_focus_bytes (proven live against a
running joshi-core before being frozen here).
"""

from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import joshi_evidence
from resident_tools import ResidentTools, ToolError


GOLDEN_ENTRY = (
    '{"contract":"joshi.operator.command","schemaVersion":1,'
    '"commandId":"command-resident-abc","idempotencyKey":"retry-command-resident-abc",'
    '"clientSessionId":"resident-1","clientCommandSeq":"7",'
    '"scene":{"sceneId":"scene-live-1234","viewDigest":"sha256:'
    + "ab" * 32 + '"},'
    '"issuedAt":"2026-08-22T01:02:03.000456Z",'
    '"clientClock":{"clockId":"resident-clock-1","monotonicNs":"99"},'
    '"commandKind":"record_focus",'
    '"subject":{"kind":"scene","key":"scene-live-1234"},'
    '"payload":{"context":{"uiLabel":"Journal entry","uiLabelVersion":"1",'
    '"confidencePpm":null,"urgency":null,"whyNow":null,'
    '"note":"words worth keeping"},"dwellMilliseconds":null},'
    '"authorityClass":"evidence_only","effectCeiling":"observe_only"}'
).encode()


def golden_kwargs(**overrides):
    kwargs = dict(
        scene_id="scene-live-1234",
        view_digest="sha256:" + "ab" * 32,
        words="words worth keeping",
        command_id="command-resident-abc",
        idempotency_key="retry-command-resident-abc",
        client_session_id="resident-1",
        client_command_seq=7,
        clock_id="resident-clock-1",
        monotonic_ns=99,
        issued_at="2026-08-22T01:02:03.000456Z",
    )
    kwargs.update(overrides)
    return kwargs


class JournalEntryBytes(unittest.TestCase):
    def test_golden_bytes_exact(self):
        self.assertEqual(
            joshi_evidence.journal_entry_command(**golden_kwargs()),
            GOLDEN_ENTRY)

    def test_blank_words_refused(self):
        for blank in ("", "   ", "\n\t"):
            with self.assertRaises(ValueError):
                joshi_evidence.journal_entry_command(**golden_kwargs(words=blank))

    def test_words_are_trimmed_to_the_canonical_form(self):
        trimmed = joshi_evidence.journal_entry_command(
            **golden_kwargs(words="  words worth keeping\n"))
        self.assertEqual(trimmed, GOLDEN_ENTRY)

    def test_oversize_refused_in_utf16_units(self):
        # 2001 astral characters = 4002 UTF-16 units > 4000, though only
        # 2001 Python code points — the frozen contract counts UTF-16.
        words = "\U0001f600" * 2001
        self.assertEqual(joshi_evidence.utf16_units(words), 4002)
        with self.assertRaises(ValueError):
            joshi_evidence.journal_entry_command(**golden_kwargs(words=words))
        joshi_evidence.journal_entry_command(
            **golden_kwargs(words="\U0001f600" * 2000))  # 4000 units: admitted

    def test_non_ascii_words_ride_as_raw_utf8(self):
        body = joshi_evidence.journal_entry_command(
            **golden_kwargs(words="crackle ohne Universalpreis — 好"))
        self.assertIn("— 好".encode(), body)
        self.assertNotIn(b"\\u", body)


class FakeSession:
    """The pair-shaped surface resident_tools drives, minus every socket."""

    def __init__(self):
        self.routes = {}
        self.appended = []
        self.append_response = (202, {"commitSeq": "6", "status": "accepted",
                                      "commandId": "command-x"})

    def get(self, path):
        return self.routes.get(path, (404, b"{}"))

    def append_command(self, body):
        self.appended.append(body)
        return self.append_response


def make_tools():
    session = FakeSession()
    tools = ResidentTools(session, client_session_id="resident-test")
    return session, tools


SCENE_SNAPSHOT = {
    "contract": "joshi.glass.snapshot",
    "snapshotDigest": "sha256:" + "cd" * 32,
    "view": {
        "sceneId": "scene-live-1234",
        "payload": {"candidates": [
            {"id": "cand-1", "symbol": "DREGG",
             "candles": [{"timeUnix": str(1700000000 + i * 60)} for i in range(30)]},
        ]},
    },
}


class ReadScene(unittest.TestCase):
    def test_reports_digest_to_cite(self):
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-1234"] = (
            200, json.dumps(SCENE_SNAPSHOT).encode())
        out = tools.read_scene("scene-live-1234")
        self.assertIn("sha256:" + "cd" * 32, out)
        self.assertIn("cite this sceneId and viewDigest", out)
        self.assertIn("DREGG", out)

    def test_refusal_is_verbatim_not_invented(self):
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-9"] = (
            404, b'{"code":"scene_not_found"}')
        with self.assertRaises(ToolError) as caught:
            tools.read_scene("scene-live-9")
        self.assertIn("scene_not_found", str(caught.exception))
        self.assertIn("404", str(caught.exception))

    def test_oversized_candles_elided_with_exact_counts(self):
        big = json.loads(json.dumps(SCENE_SNAPSHOT))
        bars = [{"timeUnix": str(1700000000 + i), "close": "1"} for i in range(4000)]
        big["view"]["payload"]["candidates"][0]["candles"] = bars
        # Pad the view so it crosses the elision threshold honestly.
        big["view"]["payload"]["padding"] = ["x" * 200] * 700
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-1234"] = (
            200, json.dumps(big).encode())
        out = tools.read_scene("scene-live-1234")
        self.assertIn('"barsElided": 4000', out)
        self.assertIn("4000 bars elided", out)
        self.assertIn(str(1700000000), out)       # first bar retained
        self.assertIn(str(1700000000 + 3999), out)  # last bar retained

    def test_wide_scene_candidates_elided_with_stated_boundaries(self):
        wide = json.loads(json.dumps(SCENE_SNAPSHOT))
        wide["view"]["payload"]["candidates"] = [
            {"id": f"cand-{i}", "symbol": f"C{i}", "blurb": "y" * 6000}
            for i in range(40)
        ]
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-1234"] = (
            200, json.dumps(wide).encode())
        out = tools.read_scene("scene-live-1234")
        self.assertIn('"candidatesKept": 24', out)
        self.assertIn('"count": 16', out)
        self.assertIn('"firstDroppedId": "cand-24"', out)
        self.assertIn('"lastDroppedId": "cand-39"', out)
        self.assertIn("cand-23", out)          # last kept candidate present
        self.assertNotIn('"id": "cand-24"', out)  # dropped body absent


JOURNAL_BODY = {
    "contract": "joshi.core.operator_command_readback",
    "sceneId": "scene-live-1234",
    "sceneRetention": "durable",
    "commands": [{
        "commandId": "command-journal-entry-1",
        "commitSeq": "6",
        "scene": {"sceneId": "scene-live-1234", "viewDigest": "sha256:" + "cd" * 32},
        "clientSessionId": "session-1",
        "clientCommandSeq": "2",
        "idempotencyKey": "retry-x",
        "commandKind": "record_focus",
        "subject": {"kind": "scene", "key": "scene-live-1234"},
        "issuedAt": "2026-08-22T01:00:00.000000Z",
        "receivedAt": "2026-08-22T01:00:00.000001Z",
        "clientClockId": "clock",
        "authorityClass": "evidence_only",
        "effectCeiling": "observe_only",
        "payload": {"context": {"uiLabel": "Journal entry", "uiLabelVersion": "1",
                                "confidencePpm": None, "urgency": None,
                                "whyNow": None, "note": "the words themselves"},
                    "dwellMilliseconds": None},
    }],
}


class ReadJournal(unittest.TestCase):
    def test_words_come_back_verbatim_with_commit_seq(self):
        session, tools = make_tools()
        session.routes["/api/v1/operator/commands?sceneId=scene-live-1234"] = (
            200, json.dumps(JOURNAL_BODY).encode())
        out = json.loads(tools.read_journal("scene-live-1234"))
        self.assertEqual(out["sceneRetention"], "durable")
        self.assertEqual(out["commandCount"], 1)
        entry = out["commands"][0]
        self.assertEqual(entry["commitSeq"], "6")
        self.assertEqual(entry["uiLabel"], "Journal entry")
        self.assertEqual(entry["words"],
                         [{"label": "Note", "words": "the words themselves"}])

    def test_empty_journal_is_a_statement_not_a_blank(self):
        empty = {"sceneId": "scene-live-1234",
                 "sceneRetention": "served_not_yet_durable", "commands": []}
        session, tools = make_tools()
        session.routes["/api/v1/operator/commands?sceneId=scene-live-1234"] = (
            200, json.dumps(empty).encode())
        out = json.loads(tools.read_journal("scene-live-1234"))
        self.assertEqual(out["commandCount"], 0)
        self.assertIn("nothing has been said", out["note"])


class AppendNote(unittest.TestCase):
    def test_posts_canonical_bytes_and_returns_receipt(self):
        session, tools = make_tools()
        out = json.loads(tools.append_note(
            "scene-live-1234", "sha256:" + "cd" * 32, "worth keeping"))
        self.assertTrue(out["durable"])
        self.assertEqual(out["commitSeq"], "6")
        self.assertEqual(len(session.appended), 1)
        posted = json.loads(session.appended[0])
        self.assertEqual(posted["commandKind"], "record_focus")
        self.assertEqual(posted["payload"]["context"]["uiLabel"], "Journal entry")
        self.assertEqual(posted["payload"]["context"]["note"], "worth keeping")
        self.assertEqual(posted["subject"], {"kind": "scene", "key": "scene-live-1234"})
        self.assertEqual(posted["clientCommandSeq"], "1")

    def test_seq_is_monotonic_within_the_process(self):
        session, tools = make_tools()
        tools.append_note("scene-live-1234", "sha256:" + "cd" * 32, "one")
        tools.append_note("scene-live-1234", "sha256:" + "cd" * 32, "two")
        seqs = [json.loads(b)["clientCommandSeq"] for b in session.appended]
        self.assertEqual(seqs, ["1", "2"])

    def test_blank_words_refused_client_side(self):
        session, tools = make_tools()
        with self.assertRaises(ToolError):
            tools.append_note("scene-live-1234", "sha256:" + "cd" * 32, "   ")
        self.assertEqual(session.appended, [])

    def test_digest_shape_checked_client_side(self):
        session, tools = make_tools()
        with self.assertRaises(ToolError):
            tools.append_note("scene-live-1234", "not-a-digest", "words")
        self.assertEqual(session.appended, [])

    def test_server_refusal_reaches_the_resident_verbatim(self):
        session, tools = make_tools()
        session.append_response = (422, {"code": "operator_commit_rejected",
                                         "detail": "scene-bound operator "
                                                   "command was not committed"})
        with self.assertRaises(ToolError) as caught:
            tools.append_note("scene-live-1234", "sha256:" + "cd" * 32, "w")
        self.assertIn("operator_commit_rejected", str(caught.exception))


class ListScenes(unittest.TestCase):
    def test_missing_route_degrades_to_feed_not_served(self):
        _, tools = make_tools()  # FakeSession 404s unrouted paths
        out = json.loads(tools.list_scenes())
        self.assertFalse(out["feedServed"])
        self.assertIn("feed not served", out["note"])

    def test_served_feed_is_bounded_with_total_stated(self):
        session, tools = make_tools()
        feed = {"contract": "joshi.core.scene_feed",
                "scenes": [{"sceneId": f"scene-{i}"} for i in range(40)]}
        session.routes["/api/v1/glass/scenes"] = (200, json.dumps(feed).encode())
        out = json.loads(tools.list_scenes())
        self.assertTrue(out["feedServed"])
        self.assertEqual(out["scenesTotal"], 40)
        self.assertEqual(len(out["newestFirst"]), 15)
        self.assertEqual(out["newestFirst"][0]["sceneId"], "scene-0")
        self.assertIn("newest 15 of 40", out["note"])
        self.assertEqual(out["feedEnvelope"],
                         {"contract": "joshi.core.scene_feed"})

    def test_small_feed_has_no_elision_note(self):
        session, tools = make_tools()
        feed = {"scenes": [{"sceneId": "scene-b"}, {"sceneId": "scene-a"}]}
        session.routes["/api/v1/glass/scenes"] = (200, json.dumps(feed).encode())
        out = json.loads(tools.list_scenes())
        self.assertEqual(out["scenesTotal"], 2)
        self.assertEqual([s["sceneId"] for s in out["newestFirst"]],
                         ["scene-b", "scene-a"])
        self.assertNotIn("note", out)

    def test_other_failures_are_errors_not_absence(self):
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes"] = (500, b'{"code":"reader_unavailable"}')
        with self.assertRaises(ToolError):
            tools.list_scenes()


class SessionLoss(unittest.TestCase):
    def test_401_marks_the_capability_lost(self):
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-1234"] = (
            401, b'{"code":"unauthorized"}')
        with self.assertRaises(ToolError):
            tools.read_scene("scene-live-1234")
        self.assertIsNotNone(tools.session_lost)
        self.assertIn("401", tools.session_lost)

    def test_healthy_reads_do_not_mark_loss(self):
        session, tools = make_tools()
        session.routes["/api/v1/glass/scenes/scene-live-1234"] = (
            200, json.dumps(SCENE_SNAPSHOT).encode())
        tools.read_scene("scene-live-1234")
        self.assertIsNone(tools.session_lost)


if __name__ == "__main__":
    unittest.main(verbosity=2)
