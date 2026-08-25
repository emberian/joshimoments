# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk==0.2.144"]
# ///
"""The JOSHI resident core: one loopback service, two lanes, one auth substrate.

    uv run apps/resident/resident_service.py --config ops/resident.toml

Lanes:
  ANALYST — a jailed claude-agent-sdk session (resident_engine) whose whole
    world is the paired joshi-core (cockpit_read + operator_evidence_write,
    exactly the cockpit's own admission path) plus a read-only analysis bench
    (resident_analysis) over the durable catalogs. Its only write anywhere is
    the scene-bound journal entry — subject {kind: "scene"} — which the
    selection instrument excludes by construction (see
    analysis/src/joshi_analysis/selection/events.py: only subject_kind
    "candidate" scores; everything else is EXCLUSION_ACT_NOT_SUBJECT_BOUND).
  DEVELOPER — explicitly gated Claude Code sessions fenced inside git
    worktrees (resident_developer). Leaves resident/<task-id> branches for
    the primary to review and land; never touches main or state/.

Service surface (loopback only, token-authed):
  POST /api/v1/analyst/turns        {"prompt": "..."}          -> 202 {turnId}
  GET  /api/v1/analyst/turns[/id]                              -> job(s)
  POST /api/v1/developer/tasks      {"task": "...", "gates": [[...]], "base"?}
  GET  /api/v1/developer/tasks[/id]                            -> job(s)
  GET  /api/v1/status
  GET  /api/v1/events?since=N       poll cursor; {"events": [...], "next": N}

Auth model, stated plainly: the service binds 127.0.0.1 and requires
`X-Resident-Token: <token>` on every request, where the token is minted on
first boot into <state_dir>/service-token, mode 0600. That is local-user
authentication (whoever can read the file can drive the service), which is
the same trust boundary the pairing-code file already draws. Toward the core
the service holds an ordinary pairing capability obtained from the same
one-time-code file the cockpit uses; a consumed code file is deleted so the
core mints a fresh one (apps/core/src/main.rs's documented re-pair loop).
Polling was chosen over SSE on purpose: a Glass pane polling /events with a
cursor is one fetch loop, works through the vite proxy unchanged, and keeps
this file stdlib-only; SSE is an additive change if the pane ever wants push.

Config: ops/resident.toml, re-read by mtime on every request (keeper
discipline: a broken edit keeps the last good config and says so in /status).
listen and state_dir apply at boot; lane settings apply to new jobs.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import queue
import re
import secrets
import sys
import threading
import time
import tomllib
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import joshi_auth
from joshi_pairing import JoshiCoreSession, PairingError
from resident_analysis import ANALYST_PROMPT_EXTRA, AnalysisTools
from resident_developer import DeveloperEngine
from resident_engine import ResidentEngine
from resident_tools import ResidentTools

logger = logging.getLogger("resident_service")

MAX_BODY_BYTES = 1_000_000
MAX_LISTED_JOBS = 50
EVENT_RING = 1000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

class Config:
    """ops/resident.toml, with relative paths resolved against its directory."""

    def __init__(self, path: Path, data: dict):
        base = path.resolve().parent

        def respath(text: str | None, default: Path | None = None) -> Path | None:
            if not text:
                return default
            p = Path(text).expanduser()
            return p if p.is_absolute() else (base / p).resolve()

        service = data.get("service", {})
        core = data.get("core", {})
        analyst = data.get("analyst", {})
        developer = data.get("developer", {})

        self.listen: str = service.get("listen", "127.0.0.1:43290")
        self.state_dir: Path = respath(service.get("state_dir"),
                                       Path.home() / ".local/state/joshi-resident-service")
        self.token_file: Path = respath(service.get("token_file"),
                                        self.state_dir / "service-token")

        self.core_listen: str = core.get("listen", "127.0.0.1:43219")
        self.core_origin: str = core.get("origin", "http://127.0.0.1:4173")
        self.pairing_code_file: Path | None = respath(core.get("pairing_code_file"))

        self.analyst_model: str = analyst.get("model", "claude-opus-5")
        self.repo: Path = respath(data.get("repo", ".."), base / "..")
        self.catalogs: dict[str, Path] = {
            name: respath(text)
            for name, text in (analyst.get("catalogs") or {}).items()
        }

        self.developer_model: str = developer.get("model", "claude-opus-5")
        self.worktree_root: Path = respath(developer.get("worktree_root"),
                                           self.state_dir / "worktrees")
        self.developer_base: str = developer.get("base", "main")
        self.developer_max_turns: int = int(developer.get("max_turns", 40))
        self.state_root: Path | None = respath(core.get("state_root"))


class ConfigHolder:
    """mtime-checked re-read; a broken edit keeps the last good config."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.error: str | None = None
        self.loaded_at: str = ""
        self._mtime: float = 0.0
        self.config = self._load(required=True)

    def _load(self, required: bool = False) -> Config:
        try:
            stat = self.path.stat()
            with open(self.path, "rb") as handle:
                data = tomllib.load(handle)
            config = Config(self.path, data)
            self._mtime = stat.st_mtime
            self.loaded_at = now_iso()
            self.error = None
            return config
        except (OSError, tomllib.TOMLDecodeError, ValueError, TypeError) as error:
            if required:
                raise
            self.error = f"config re-read failed, keeping last good: {error}"
            logger.warning(self.error)
            return self.config

    def current(self) -> Config:
        try:
            if self.path.stat().st_mtime != self._mtime:
                self.config = self._load()
        except OSError as error:
            self.error = f"config unreadable, keeping last good: {error}"
        return self.config


# ----------------------------------------------------------------------
# Jobs and events
# ----------------------------------------------------------------------

class Jobs:
    def __init__(self, state_dir: Path):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._events: list[dict] = []
        self._seq = 0
        self._dir = state_dir / "jobs"
        self._dir.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **body) -> None:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "ts": now_iso(), "kind": kind, **body}
            self._events.append(entry)
            if len(self._events) > EVENT_RING:
                del self._events[:len(self._events) - EVENT_RING]
        try:
            with open(self._dir.parent / "service-events.jsonl", "a",
                      encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def events_since(self, since: int) -> tuple[list[dict], int]:
        with self._lock:
            out = [e for e in self._events if e["seq"] > since]
            return out, self._seq

    def create(self, kind: str, request: dict) -> dict:
        job_id = f"{kind}-{uuid.uuid4().hex[:12]}"
        job = {"id": job_id, "kind": kind, "state": "queued",
               "created": now_iso(), "request": request}
        with self._lock:
            self._jobs[job_id] = job
        self.event("job_queued", jobId=job_id, jobKind=kind)
        return dict(job)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            snapshot = dict(job)
        try:
            (self._dir / f"{job_id}.json").write_text(
                json.dumps(snapshot, indent=1, default=str) + "\n")
        except OSError:
            pass
        self.event("job_" + fields.get("state", "updated"), jobId=job_id)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self, kind: str) -> list[dict]:
        with self._lock:
            rows = [dict(j) for j in self._jobs.values() if j["kind"] == kind]
        rows.sort(key=lambda j: j["created"], reverse=True)
        # Listings are summaries; full records live at /…/<id>.
        return [{k: v for k, v in row.items()
                 if k in ("id", "kind", "state", "created", "started",
                          "finished", "error")}
                for row in rows[:MAX_LISTED_JOBS]]


# ----------------------------------------------------------------------
# The service
# ----------------------------------------------------------------------

class ResidentService:
    def __init__(self, holder: ConfigHolder):
        self.holder = holder
        config = holder.current()
        self.state_dir = config.state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.token = self._ensure_token(config.token_file)
        self.jobs = Jobs(self.state_dir)
        self.started = now_iso()

        # -- core pairing (one session for the analyst lane) -------------
        self.session = JoshiCoreSession(config.core_listen, config.core_origin)
        self.tools = ResidentTools(self.session)
        self.pair_descriptor: dict | None = None

        # -- analyst engine ----------------------------------------------
        analysis = AnalysisTools(config.repo, config.catalogs)
        extra_specs = [
            ("list_catalogs",
             "List the durable read-only catalogs the analysis bench can "
             "read (names, paths, existence). Everything is sqlite mode=ro.",
             {},
             analysis.list_catalogs),
            ("catalog_census",
             "Bounded counts for one catalog: commands, scenes, "
             "observations, acquisitions, source events, the newest "
             "observation's clock, and a 20-row window of newest mints "
             "(a window, never a census of all mints).",
             {"catalog": str},
             analysis.catalog_census),
            ("run_signature",
             "Signature volatility (FORMAL_MODEL.md Definition P2) on the "
             "newest retained candle window for one mint, computed from the "
             "provider's exact durable bytes in the named catalog. Reports "
             "both clocks (event time and wall time) with full provenance. "
             "Absent lags stay absent, never zero.",
             {"catalog": str, "mint": str},
             analysis.run_signature),
        ]
        self.engine = ResidentEngine(
            self.tools, self.state_dir / "analyst",
            model=config.analyst_model,
            extra_specs=extra_specs,
            system_prompt_extra=ANALYST_PROMPT_EXTRA)
        self._restore_analyst_session()

        # -- developer engine --------------------------------------------
        self.developer = DeveloperEngine(
            repo=config.repo,
            worktree_root=config.worktree_root,
            state_dir=self.state_dir / "developer",
            model=config.developer_model,
            state_root=config.state_root,
            max_turns=config.developer_max_turns)

        # -- one worker per lane: turns and tasks are serialized ---------
        self._analyst_queue: queue.Queue[dict] = queue.Queue()
        self._developer_queue: queue.Queue[dict] = queue.Queue()
        threading.Thread(target=self._analyst_worker, daemon=True,
                         name="analyst").start()
        threading.Thread(target=self._developer_worker, daemon=True,
                         name="developer").start()

    # -- token -----------------------------------------------------------
    @staticmethod
    def _ensure_token(path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            token = path.read_text().strip()
            if token:
                return token
        token = secrets.token_hex(32)
        path.write_text(token + "\n")
        path.chmod(0o600)
        return token

    def authorized(self, presented: str | None) -> bool:
        return bool(presented) and hmac.compare_digest(presented, self.token)

    # -- analyst session persistence -------------------------------------
    def _analyst_session_file(self) -> Path:
        return self.state_dir / "analyst" / "session.json"

    def _restore_analyst_session(self) -> None:
        try:
            data = json.loads(self._analyst_session_file().read_text())
            self.engine.sdk_session_id = data.get("sdkSessionId") or None
        except (OSError, ValueError):
            pass

    def _persist_analyst_session(self) -> None:
        try:
            self._analyst_session_file().write_text(json.dumps(
                {"sdkSessionId": self.engine.sdk_session_id}) + "\n")
        except OSError:
            pass

    # -- pairing ----------------------------------------------------------
    def ensure_paired(self) -> str | None:
        """None when paired; otherwise the honest reason a turn cannot run.

        Consumes the one-time code from the configured code file and DELETES
        the file afterward — the core's documented signal to mint a fresh
        code for the next local client. A refused (stale) code file is also
        deleted, for the same reason.
        """
        if self.session.paired and not self.tools.session_lost:
            return None
        config = self.holder.current()
        code_file = config.pairing_code_file
        if code_file is None or not code_file.is_file():
            return ("not paired and no pairing code available at "
                    f"{code_file}; is joshi-core running with "
                    f"--pairing-code-file?")
        code = code_file.read_text().strip()
        try:
            descriptor = self.session.pair(code)
        except (PairingError, OSError) as error:
            try:
                code_file.unlink()  # consumed/stale either way; core re-mints
            except OSError:
                pass
            return f"pairing refused ({error}); asked the core for a fresh code"
        try:
            code_file.unlink()
        except OSError:
            pass
        self.tools.session_lost = None
        self.pair_descriptor = descriptor
        self.jobs.event("paired", sessionId=descriptor.get("sessionId"),
                        scopes=descriptor.get("scopes"))
        logger.info(f"paired: {descriptor.get('sessionId')} "
                    f"scopes={descriptor.get('scopes')}")
        return None

    # -- workers ----------------------------------------------------------
    def _analyst_worker(self) -> None:
        while True:
            job = self._analyst_queue.get()
            job_id = job["id"]
            self.jobs.update(job_id, state="running", started=now_iso())
            refusal = self.ensure_paired()
            if refusal:
                self.jobs.update(job_id, state="failed", error=refusal,
                                 finished=now_iso())
                continue
            prompt = (f"[context] time={now_iso()} "
                      f"pairedCore={self.holder.current().core_listen}\n\n"
                      f"{job['request']['prompt']}")
            try:
                result = self.engine.turn(prompt)
                self._persist_analyst_session()
                self.jobs.update(
                    job_id,
                    state="failed" if result.is_error else "done",
                    finished=now_iso(),
                    text=result.text,
                    error=result.limit_reason if result.is_error else None,
                    sdkSessionId=result.session_id,
                    toolCalls=result.tool_calls)
            except Exception as error:  # noqa: BLE001
                logger.exception("analyst turn crashed")
                self.jobs.update(job_id, state="failed", error=str(error),
                                 finished=now_iso())
            if self.tools.session_lost:
                self.jobs.event("pairing_lost",
                                detail=self.tools.session_lost)

    def _developer_worker(self) -> None:
        while True:
            job = self._developer_queue.get()
            job_id = job["id"]
            self.jobs.update(job_id, state="running", started=now_iso())
            request = job["request"]
            try:
                result = self.developer.run_task(
                    task_id=job_id,
                    task_text=request["task"],
                    gates=request.get("gates"),
                    base=request.get("base",
                                     self.holder.current().developer_base))
                failed = bool(result.session_error)
                self.jobs.update(
                    job_id,
                    state="failed" if failed else "done",
                    finished=now_iso(),
                    error=result.session_error,
                    result=result.to_json_obj())
            except Exception as error:  # noqa: BLE001
                logger.exception("developer task crashed")
                self.jobs.update(job_id, state="failed", error=str(error),
                                 finished=now_iso())

    # -- request handling --------------------------------------------------
    def status(self) -> dict:
        config = self.holder.current()
        return {
            "contract": "joshi.resident.status",
            "started": self.started,
            "listen": config.listen,
            "stateDir": str(self.state_dir),
            "config": {"path": str(self.holder.path),
                       "loadedAt": self.holder.loaded_at,
                       "error": self.holder.error},
            "pairing": {
                "paired": self.session.paired and not self.tools.session_lost,
                "sessionId": (self.pair_descriptor or {}).get("sessionId"),
                "scopes": (self.pair_descriptor or {}).get("scopes"),
                "lost": self.tools.session_lost,
                "core": config.core_listen,
            },
            "tokeman": {"account": joshi_auth.sticky_account()},
            "analyst": {"model": config.analyst_model,
                        "sdkSessionId": self.engine.sdk_session_id,
                        "clientSessionId": self.tools.client_session_id},
            "developer": {"model": config.developer_model,
                          "worktreeRoot": str(config.worktree_root),
                          "base": config.developer_base},
        }

    def submit_analyst(self, body: dict) -> dict:
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("a turn needs a non-empty prompt")
        job = self.jobs.create("turn", {"prompt": prompt})
        self._analyst_queue.put(job)
        return {"turnId": job["id"], "state": "queued"}

    def submit_developer(self, body: dict) -> dict:
        task = (body.get("task") or "").strip()
        if not task:
            raise ValueError("a developer task needs a non-empty task")
        gates = body.get("gates")
        if gates is not None and not (
                isinstance(gates, list)
                and all(isinstance(g, list)
                        and all(isinstance(a, str) for a in g)
                        for g in gates)):
            raise ValueError("gates must be a list of argv lists of strings")
        request = {"task": task, "gates": gates}
        if body.get("base"):
            request["base"] = str(body["base"])
        job = self.jobs.create("task", request)
        self._developer_queue.put(job)
        return {"taskId": job["id"], "state": "queued"}


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------

ROUTE_JOB = re.compile(r"^/api/v1/(analyst/turns|developer/tasks)(?:/([\w-]+))?$")


class Handler(BaseHTTPRequestHandler):
    service: ResidentService  # set by serve()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; the jobs log is the record
        logger.debug("http " + fmt % args)

    def _reply(self, status: int, body: dict) -> None:
        raw = json.dumps(body, indent=1, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self) -> bool:
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._reply(403, {"code": "loopback_only"})
            return False
        if not self.service.authorized(self.headers.get("X-Resident-Token")):
            self._reply(401, {"code": "unauthorized",
                              "detail": "X-Resident-Token required; the "
                                        "token lives in the service's "
                                        "state dir, mode 0600"})
            return False
        return True

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError(f"body over {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        parsed = json.loads(raw or b"{}")
        if not isinstance(parsed, dict):
            raise ValueError("body must be a JSON object")
        return parsed

    def do_GET(self) -> None:  # noqa: N802
        if not self._authed():
            return
        split = urlsplit(self.path)
        path = split.path
        if path == "/api/v1/status":
            self._reply(200, self.service.status())
            return
        if path == "/api/v1/events":
            since = 0
            query = parse_qs(split.query)
            if "since" in query:
                try:
                    since = int(query["since"][0])
                except ValueError:
                    self._reply(400, {"code": "bad_cursor"})
                    return
            events, next_seq = self.service.jobs.events_since(since)
            self._reply(200, {"events": events, "next": next_seq})
            return
        match = ROUTE_JOB.match(path)
        if match:
            kind = "turn" if match.group(1) == "analyst/turns" else "task"
            job_id = match.group(2)
            if job_id is None:
                self._reply(200, {"jobs": self.service.jobs.list(kind)})
                return
            job = self.service.jobs.get(job_id)
            if job is None or job["kind"] != kind:
                self._reply(404, {"code": "job_not_found", "id": job_id})
                return
            self._reply(200, job)
            return
        self._reply(404, {"code": "route_not_served", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authed():
            return
        path = urlsplit(self.path).path
        try:
            body = self._body()
        except ValueError as error:
            self._reply(400, {"code": "bad_body", "detail": str(error)})
            return
        try:
            if path == "/api/v1/analyst/turns":
                self._reply(202, self.service.submit_analyst(body))
                return
            if path == "/api/v1/developer/tasks":
                self._reply(202, self.service.submit_developer(body))
                return
        except ValueError as error:
            self._reply(422, {"code": "request_refused", "detail": str(error)})
            return
        self._reply(404, {"code": "route_not_served", "path": path})


def serve(config_path: Path) -> int:
    holder = ConfigHolder(config_path)
    service = ResidentService(holder)
    Handler.service = service
    host, _, port = holder.current().listen.partition(":")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"refusing non-loopback listen address {host!r}")
    server = ThreadingHTTPServer((host, int(port)), Handler)
    logger.info(f"resident service up on {holder.current().listen}; "
                f"token at {holder.current().token_file}")
    service.jobs.event("service_up", listen=holder.current().listen)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True,
                        help="path to ops/resident.toml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return serve(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
