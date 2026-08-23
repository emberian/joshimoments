# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-agent-sdk>=0.2.128"]
# ///
"""The JOSHI resident: a long-running inhabitant of one paired joshi-core.

Run it against a live core (e.g. `joshi-core live-surface-inspect ...`, which
prints a one-time pairing code):

    uv run apps/resident/resident.py \
        --listen 127.0.0.1:43119 --origin http://127.0.0.1:4173 \
        --code JOSHI-....  --scene scene-live-...

Turns are triggered two ways:
  (a) an interval — "look at the newest scene, read the journal, note anything
      worth noting — and say nothing when there is nothing; an empty turn is a
      valid turn";
  (b) stdin lines from Ember — a conversation: her line becomes the turn's
      prompt; the resident may answer in text AND may journal what deserves
      durability. Text is ephemeral; the journal is the record.

Stdin also accepts:  /pair JOSHI-...   re-pair with a fresh one-time code
                     /scene <sceneId>  repoint the turn context at a scene
                     /quit             graceful shutdown

Pairing codes are one-time. When the capability dies (401/503), the resident
re-pairs from --code-file the next time that file holds a code it has not yet
consumed, or from a /pair line; until then it waits and says so.
"""

from __future__ import annotations

import sys
import json
import time
import queue
import signal
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))

from joshi_pairing import JoshiCoreSession, PairingError
from resident_tools import ResidentTools
from resident_engine import DEFAULT_MODEL, ResidentEngine

logger = logging.getLogger("resident")

INTERVAL_PROMPT = (
    "[interval turn] Look at the newest scene (try list_scenes; if the feed "
    "is not served, the scene in the context line is the newest you can "
    "know), read its journal, and note anything worth noting. Say nothing "
    "when there is nothing — an empty turn is a valid turn."
)


def _context_line(scene: str | None, listen: str) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    known = scene if scene else "none configured — ask list_scenes"
    return f"[context] time={now} pairedCore={listen} scene={known}"


class Resident:
    def __init__(self, args):
        self.args = args
        self.state_dir = Path(args.state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.scene: str | None = args.scene
        self.session = JoshiCoreSession(args.listen, args.origin)
        self.tools = ResidentTools(self.session)
        self.engine = ResidentEngine(self.tools, self.state_dir,
                                     model=args.model)
        self.stop = threading.Event()
        self.lines: queue.Queue[str] = queue.Queue()
        self.consumed_codes: set[str] = set()
        self._restore_session()

    # -- session persistence (SDK session only; the client command
    #    identity is minted fresh per process on purpose: the store refuses
    #    a reused clientCommandSeq within a clientSessionId) --------------
    def _session_file(self) -> Path:
        return self.state_dir / "session.json"

    def _restore_session(self) -> None:
        try:
            data = json.loads(self._session_file().read_text())
            self.engine.sdk_session_id = data.get("sdkSessionId") or None
            if self.engine.sdk_session_id:
                logger.info(f"resuming SDK session {self.engine.sdk_session_id}")
        except (OSError, ValueError):
            pass

    def _persist_session(self) -> None:
        try:
            self._session_file().write_text(json.dumps(
                {"sdkSessionId": self.engine.sdk_session_id}) + "\n")
        except OSError as error:
            logger.debug(f"session persist failed: {error}")

    # -- pairing ---------------------------------------------------------
    def pair(self, code: str) -> bool:
        code = code.strip()
        if not code:
            return False
        try:
            descriptor = self.session.pair(code)
        except (PairingError, OSError) as error:
            logger.error(f"pairing refused: {error}")
            return False
        self.consumed_codes.add(code)
        self.tools.session_lost = None
        logger.info(f"paired: session={descriptor.get('sessionId')} "
                    f"scopes={descriptor.get('scopes')} "
                    f"authority={descriptor.get('authority')}")
        return True

    def _fresh_code_from_file(self) -> str | None:
        if not self.args.code_file:
            return None
        try:
            code = Path(self.args.code_file).read_text().strip().splitlines()
        except OSError:
            return None
        for line in code:
            line = line.strip()
            if line and line not in self.consumed_codes:
                return line
        return None

    def ensure_paired(self) -> bool:
        """True when a turn can reach the core. Never fakes it."""
        if self.session.paired and not self.tools.session_lost:
            return True
        if self.tools.session_lost:
            logger.warning(f"pairing capability lost ({self.tools.session_lost}); "
                           f"a fresh one-time code is needed")
        fresh = self._fresh_code_from_file()
        if fresh and self.pair(fresh):
            return True
        logger.warning(
            "not paired: provide a fresh code via /pair JOSHI-... on stdin"
            + (f" or in {self.args.code_file}" if self.args.code_file else ""))
        return False

    # -- turns -----------------------------------------------------------
    def take_turn(self, prompt: str, spoken: bool) -> None:
        if not self.ensure_paired():
            return
        full = _context_line(self.scene, self.args.listen) + "\n\n" + prompt
        started = time.monotonic()
        result = self.engine.turn(full)
        elapsed = time.monotonic() - started
        self._persist_session()
        used = ", ".join(c["tool"] for c in result.tool_calls) or "no tools"
        logger.info(f"turn finished in {elapsed:.0f}s ({used})")
        if result.is_error:
            print(f"[resident error] {result.text}", flush=True)
            return
        if result.text:
            prefix = "[resident]" if spoken else "[resident, interval]"
            print(f"{prefix} {result.text}", flush=True)
        elif spoken:
            print("[resident] (said nothing)", flush=True)
        if self.tools.session_lost:
            logger.warning("the pairing capability died during that turn; "
                           "re-pair before the next one")

    # -- stdin -----------------------------------------------------------
    def _stdin_loop(self) -> None:
        for line in sys.stdin:
            self.lines.put(line.rstrip("\n"))
        # EOF just ends the conversation; interval turns keep going.

    # -- main loop -------------------------------------------------------
    def run(self) -> int:
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        if self.args.code:
            self.pair(self.args.code)
        self.ensure_paired()

        if self.args.once:
            self.take_turn(INTERVAL_PROMPT, spoken=False)
            return 0

        threading.Thread(target=self._stdin_loop, daemon=True).start()
        interval = self.args.interval
        next_interval_turn = (time.monotonic() + interval) if interval else None
        logger.info(
            f"resident up: interval="
            f"{f'{interval}s' if interval else 'off'}, stdin open")
        while not self.stop.is_set():
            timeout = 1.0
            if next_interval_turn is not None:
                timeout = max(0.0, min(timeout, next_interval_turn - time.monotonic()))
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                line = None
            if self.stop.is_set():
                break
            if line is not None:
                if not self._handle_line(line):
                    break
                continue
            if next_interval_turn is not None and time.monotonic() >= next_interval_turn:
                self.take_turn(INTERVAL_PROMPT, spoken=False)
                next_interval_turn = time.monotonic() + interval
        logger.info("resident stopping (current turn was allowed to finish)")
        return 0

    def _handle_line(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return True
        if line == "/quit":
            self.stop.set()
            return False
        if line.startswith("/pair "):
            self.pair(line[len("/pair "):])
            return True
        if line.startswith("/scene "):
            self.scene = line[len("/scene "):].strip()
            logger.info(f"turn context now points at {self.scene}")
            return True
        self.take_turn(f"[Ember, at the terminal] {line}", spoken=True)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True,
                        help="joshi-core socket, e.g. 127.0.0.1:43119")
    parser.add_argument("--origin", default="http://127.0.0.1:4173",
                        help="the pairing coordinator's configured browser origin")
    parser.add_argument("--code", help="one-time pairing code")
    parser.add_argument("--code-file",
                        help="file holding one-time pairing codes, one per "
                             "line; re-pairing reads the first unconsumed one")
    parser.add_argument("--scene",
                        help="scene the turn context names when no feed route "
                             "is served")
    parser.add_argument("--interval", type=float, default=300.0,
                        help="seconds between interval turns; 0 disables")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--state-dir", default="~/.local/state/joshi-resident",
                        help="session, logs, and tool activity live here — "
                             "never in the repo")
    parser.add_argument("--once", action="store_true",
                        help="take one interval turn and exit")
    args = parser.parse_args()
    if not args.code and not args.code_file:
        parser.error("one of --code or --code-file is required")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    state_dir = Path(args.state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(state_dir / "resident.log")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)

    return Resident(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
