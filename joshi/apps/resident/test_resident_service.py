# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Network-free tests for the resident service: fences, bench, config, HTTP.

Run:  uv run --no-project apps/resident/test_resident_service.py
(or plain `python3 apps/resident/test_resident_service.py`). Nothing here
needs the claude-agent-sdk or a running core: engines are stubbed, the
analysis bench runs against a synthetic catalog built in a temp dir, and the
HTTP handler is driven over a real loopback socket with a stub service.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import resident_service
from resident_analysis import AnalysisTools
from resident_developer import guard_bash, guard_gate, guard_write_path
from resident_service import ConfigHolder, Handler, Jobs
from resident_tools import ToolError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ----------------------------------------------------------------------
# Fences
# ----------------------------------------------------------------------

class BashGuard(unittest.TestCase):
    WT = Path("/tmp/wt-x")
    REPO = Path("~/dev/joshi")
    STATE = Path("~/dev/joshi/state")

    def refuse(self, command: str) -> str:
        reason = guard_bash(command, self.WT, self.REPO, self.STATE)
        self.assertIsNotNone(reason, f"expected refusal: {command}")
        return reason

    def allow(self, command: str) -> None:
        reason = guard_bash(command, self.WT, self.REPO, self.STATE)
        self.assertIsNone(reason, f"expected allowed: {command} -> {reason}")

    def test_git_history_writes_refused(self):
        for cmd in ("git commit -m x", "git stash", "git checkout main",
                    "git restore .", "git reset --hard", "git add -A",
                    "git rebase main", "git merge x", "git push",
                    "cd sub && git commit -m y", "git worktree add /tmp/z"):
            self.refuse(cmd)

    def test_readonly_git_allowed(self):
        for cmd in ("git status", "git diff", "git log --oneline -5",
                    "git show HEAD", "git grep foo"):
            self.allow(cmd)

    def test_unfiltered_cargo_test_refused_with_house_rule(self):
        reason = self.refuse("cargo test -p joshi-core")
        self.assertIn("never run an unfiltered", reason)
        self.refuse("cargo nextest run -p dregg-circuit")

    def test_filtered_cargo_test_allowed(self):
        self.allow("cargo nextest run -p joshi-core -E 'test(pairing)'")
        self.allow("cargo test --test live_journal")

    def test_primary_tree_and_state_root_fenced(self):
        self.refuse("cat ~/dev/joshi/apps/core/src/main.rs")
        self.refuse("ls ~/dev/joshi/state/keeper")
        self.allow("cargo fmt --check")

    def test_worktree_paths_allowed(self):
        self.assertIsNone(guard_bash(
            f"ls {self.WT}/apps", self.WT, self.REPO, self.STATE))


class WritePathGuard(unittest.TestCase):
    def test_inside_worktree_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            self.assertIsNone(guard_write_path(str(wt / "a/b.rs"), wt))
            self.assertIsNone(guard_write_path("relative/file.py", wt))

    def test_outside_worktree_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            self.assertIsNotNone(
                guard_write_path("~/dev/joshi/README.md", wt))
            self.assertIsNotNone(
                guard_write_path(str(wt / ".." / "escape.txt"), wt))


class GateGuard(unittest.TestCase):
    def test_house_rules_hold_for_gates_too(self):
        self.assertIsNotNone(guard_gate(["cargo", "test", "-p", "joshi-core"]))
        self.assertIsNotNone(guard_gate(["git", "commit", "-m", "x"]))
        self.assertIsNone(guard_gate(["cargo", "fmt", "--check"]))
        self.assertIsNone(guard_gate(
            ["cargo", "nextest", "run", "-E", "test(pairing)"]))
        self.assertIsNone(guard_gate(
            ["uv", "run", "--no-project", "apps/resident/test_resident.py"]))


# ----------------------------------------------------------------------
# Analysis bench against a synthetic catalog
# ----------------------------------------------------------------------

MINT = "TESTMINTxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def build_catalog(path: Path, candle_bytes: bytes | None) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE command (command_id TEXT);
        CREATE TABLE scene (scene_id TEXT);
        CREATE TABLE observation (
            observation_id TEXT, commit_seq INTEGER, acquisition_id TEXT,
            blob_id TEXT, received_wall_us INTEGER, parse_disposition TEXT);
        CREATE TABLE acquisition (
            acquisition_id TEXT, source_locator_redacted TEXT,
            started_wall_us INTEGER);
        CREATE TABLE observation_source_event (
            observation_id TEXT, source_event_id TEXT);
        CREATE TABLE source_event (
            source_event_id TEXT, event_namespace TEXT, natural_key TEXT,
            identified_commit_seq INTEGER);
        CREATE TABLE blob_object (
            blob_id TEXT, storage_mode TEXT, inline_bytes BLOB,
            relative_path TEXT, compression TEXT);
    """)
    if candle_bytes is not None:
        conn.execute("INSERT INTO acquisition VALUES (?,?,?)",
                     ("acq-1", "https://x/v1/coins/{mint}/candles", 111))
        conn.execute("INSERT INTO observation VALUES (?,?,?,?,?,?)",
                     ("obs-1:body", 5, "acq-1", "blob-1", 222, "decoded"))
        conn.execute("INSERT INTO source_event VALUES (?,?,?,?)",
                     (f"mint:pump:{MINT}", "solana.token_mint", MINT, 3))
        conn.execute("INSERT INTO observation_source_event VALUES (?,?)",
                     ("obs-1:body", f"mint:pump:{MINT}"))
        conn.execute("INSERT INTO blob_object VALUES (?,?,?,?,?)",
                     ("blob-1", "inline", candle_bytes, None, "identity"))
    conn.commit()
    conn.close()


def candles(n: int = 64) -> bytes:
    rows = [{"timestamp": 1_700_000_000_000 + i * 1000,
             "close": f"{1.0 + 0.001 * (i % 7):.6f}"} for i in range(n)]
    return json.dumps(rows).encode()


class AnalysisBench(unittest.TestCase):
    def bench(self, candle_bytes: bytes | None) -> AnalysisTools:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        catalog = Path(self.tmp.name) / "catalog.sqlite"
        build_catalog(catalog, candle_bytes)
        return AnalysisTools(REPO_ROOT, {"test": catalog})

    def test_signature_reports_provenance_and_both_clocks(self):
        out = self.bench(candles()).run_signature("test", MINT)
        self.assertIn("obs-1", out)
        self.assertIn("EVENT TIME", out)
        self.assertIn("WALL TIME", out)
        self.assertIn("FORMAL_MODEL.md", out)
        self.assertIn('"bars": 64', out)

    def test_absent_mint_is_absent_retention_not_no_trading(self):
        with self.assertRaises(ToolError) as caught:
            self.bench(candles()).run_signature("test", "OTHERMINT")
        self.assertIn("absence of retention", str(caught.exception))

    def test_unknown_catalog_refused_with_the_known_list(self):
        with self.assertRaises(ToolError) as caught:
            self.bench(None).run_signature("nope", MINT)
        self.assertIn("test", str(caught.exception))

    def test_single_bar_window_refused_not_zeroed(self):
        bench = self.bench(json.dumps(
            [{"timestamp": 1, "close": "1.0"}]).encode())
        with self.assertRaises(ToolError) as caught:
            bench.run_signature("test", MINT)
        self.assertIn("at least 2", str(caught.exception))

    def test_census_counts_and_windows(self):
        out = json.loads(self.bench(candles()).catalog_census("test"))
        self.assertEqual(out["observations"], 1)
        self.assertEqual(out["newestMints"][0]["mint"], MINT)
        self.assertIn("window", out["newestMintsNote"])

    def test_list_catalogs_states_absence(self):
        bench = AnalysisTools(REPO_ROOT, {"gone": Path("/nonexistent/x.sqlite")})
        out = json.loads(bench.list_catalogs())
        self.assertFalse(out["catalogs"][0]["exists"])


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

CONFIG_TEXT = """
repo = ".."
[service]
listen = "127.0.0.1:43290"
state_dir = "{state}"
[core]
listen = "127.0.0.1:43219"
pairing_code_file = "codes"
[analyst.catalogs]
keeper = "cat.sqlite"
"""


class ConfigReread(unittest.TestCase):
    def test_relative_paths_resolve_against_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ops" / "resident.toml"
            path.parent.mkdir()
            path.write_text(CONFIG_TEXT.format(state=tmp))
            holder = ConfigHolder(path)
            config = holder.current()
            self.assertEqual(config.pairing_code_file,
                             (path.parent / "codes").resolve())
            self.assertEqual(config.catalogs["keeper"],
                             (path.parent / "cat.sqlite").resolve())
            self.assertEqual(config.repo, Path(tmp).resolve())

    def test_broken_edit_keeps_last_good_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resident.toml"
            path.write_text(CONFIG_TEXT.format(state=tmp))
            holder = ConfigHolder(path)
            good = holder.current()
            time.sleep(0.02)
            path.write_text("this is [not toml")
            # mtime granularity: force a stat difference
            import os
            os.utime(path, (time.time() + 5, time.time() + 5))
            kept = holder.current()
            self.assertIs(kept, good)
            self.assertIsNotNone(holder.error)
            self.assertIn("keeping last good", holder.error)


# ----------------------------------------------------------------------
# Jobs and HTTP surface (stub service, real socket)
# ----------------------------------------------------------------------

class JobsRegistry(unittest.TestCase):
    def test_lifecycle_and_events_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Jobs(Path(tmp))
            job = jobs.create("turn", {"prompt": "x"})
            jobs.update(job["id"], state="running", started="t1")
            jobs.update(job["id"], state="done", finished="t2", text="hi")
            got = jobs.get(job["id"])
            self.assertEqual(got["state"], "done")
            events, next_seq = jobs.events_since(0)
            kinds = [e["kind"] for e in events]
            self.assertEqual(kinds, ["job_queued", "job_running", "job_done"])
            later, _ = jobs.events_since(next_seq)
            self.assertEqual(later, [])
            # summaries only in listings
            listed = jobs.list("turn")[0]
            self.assertNotIn("text", listed)


class StubService:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = Jobs(Path(self.tmp.name))
        self.token = "tok-123"

    def authorized(self, presented):
        return presented == self.token

    def status(self):
        return {"contract": "joshi.resident.status", "stub": True}

    def submit_analyst(self, body):
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("a turn needs a non-empty prompt")
        job = self.jobs.create("turn", {"prompt": prompt})
        return {"turnId": job["id"], "state": "queued"}

    def submit_developer(self, body):
        raise ValueError("stub refuses developer tasks")


class HttpSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub = StubService()
        Handler.service = cls.stub
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.stub.tmp.cleanup()

    def request(self, method, path, body=None, token="tok-123"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token is not None:
            headers["X-Resident-Token"] = token
        raw = json.dumps(body).encode() if body is not None else None
        if raw:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read() or b"{}")
        conn.close()
        return response.status, data

    def test_no_token_is_401(self):
        status, body = self.request("GET", "/api/v1/status", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")

    def test_wrong_token_is_401(self):
        status, _ = self.request("GET", "/api/v1/status", token="nope")
        self.assertEqual(status, 401)

    def test_status_ok_with_token(self):
        status, body = self.request("GET", "/api/v1/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["contract"], "joshi.resident.status")

    def test_turn_submission_and_readback(self):
        status, body = self.request("POST", "/api/v1/analyst/turns",
                                    {"prompt": "look at the newest scene"})
        self.assertEqual(status, 202)
        turn_id = body["turnId"]
        status, job = self.request("GET", f"/api/v1/analyst/turns/{turn_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job["request"]["prompt"], "look at the newest scene")

    def test_empty_prompt_is_422(self):
        status, body = self.request("POST", "/api/v1/analyst/turns",
                                    {"prompt": "  "})
        self.assertEqual(status, 422)

    def test_unknown_job_is_404(self):
        status, _ = self.request("GET", "/api/v1/analyst/turns/turn-zzz")
        self.assertEqual(status, 404)

    def test_events_cursor(self):
        self.request("POST", "/api/v1/analyst/turns", {"prompt": "x"})
        status, body = self.request("GET", "/api/v1/events?since=0")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(body["next"], 1)
        status, later = self.request(
            "GET", f"/api/v1/events?since={body['next']}")
        self.assertEqual(later["events"], [])

    def test_unserved_route_is_404_not_silence(self):
        status, body = self.request("GET", "/api/v1/nothing")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "route_not_served")


if __name__ == "__main__":
    unittest.main(verbosity=2)
