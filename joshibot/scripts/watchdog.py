#!/usr/bin/env python3
"""One supervisor for every collector. ``uv run python scripts/watchdog.py``

WHY THIS EXISTS
---------------
The operator's complaint is "we didn't collect enough data", and every cause of it this week
was structural rather than analytical: collectors were started with ``--minutes N`` on a laptop
that sleeps, two daemons died silently for ~24 hours (a DNS error killed ``inteld`` and nobody
noticed), the cluster tape sat ~24 hours stale, and every tape carries multi-hour holes. None
of that is visible from inside a collector — a dead process reports nothing, which is exactly
what a healthy quiet one also reports.

So the supervisor's whole job is to make **"quiet" and "dead" different observations**, and the
only honest way to do that is to read each collector's own liveness row rather than its event
rows. A tape with no swaps for an hour is information when a heartbeat sits beside it and is
nothing at all when it does not. :data:`COLLECTORS` therefore records, per collector, *which
row proves aliveness* and how good that proof is:

``PROOF_HEARTBEAT``
    The collector writes a row on a fixed clock whether or not the market did anything.
    Silence is then genuinely diagnostic: the process is gone or wedged.
``PROOF_EVENT``
    The freshest thing available is driven by market activity. A quiet market and a dead
    socket look the same, so the staleness budget must be set from the *observed* event rate
    and an alert says "possibly quiet" rather than "dead". This is a weaker instrument and is
    labelled as one instead of being quietly rounded up to a heartbeat.
``PROOF_MTIME``
    Only a file mtime. Weakest of all; used where a collector has nothing better.

WHAT IT DOES, IN ORDER
----------------------
1. Probe every collector's freshness against its own cadence (``stale_after`` = cadence x
   grace, floored at :data:`MIN_GRACE_SECONDS` so a 30-second cadence does not alarm on a
   one-second scheduling jitter).
2. Restart a stale collector via ``launchctl kickstart -k``, bootstrapping the job first if it
   is not loaded at all. Restarts are rate-limited (:data:`DEFAULT_RESTART_COOLDOWN`, and at
   most :data:`DEFAULT_MAX_RESTARTS_PER_HOUR`) because a crash-looping collector that talks to
   a metered RPC is more expensive than a stopped one.
3. SCREAM when restarting does not fix it — Telegram, deduped, escalating to critical. Delivery
   uses the sentinel's mechanism but **not the sentinel's code**: see :class:`Telegram` below.

IDEMPOTENCE
-----------
Every pass takes an exclusive ``flock`` on ``state/watchdog/watchdog.lock`` and exits 0 without
doing anything if another pass holds it. launchd firing while a cron entry also fires, or a
``StartInterval`` landing on top of a slow pass, is therefore harmless by construction rather
than by timing luck.

THE WATCHDOG'S OWN HEARTBEAT
----------------------------
It writes one row per pass to ``state/watchdog/journal.jsonl``, which is the same instrument it
demands of everything else — if the supervisor dies, its own tape says so, and the operator can
diff the journal against the collectors' tapes to date a hole to the minute.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
STATE_DIR: Final[Path] = REPO_ROOT / "state" / "watchdog"
LOCK_PATH: Final[Path] = STATE_DIR / "watchdog.lock"
STATE_PATH: Final[Path] = STATE_DIR / "state.json"
JOURNAL_PATH: Final[Path] = STATE_DIR / "journal.jsonl"
OPS_DIR: Final[Path] = REPO_ROOT / "ops"
CONFIG_PATH: Final[Path] = REPO_ROOT / "config.yaml"

#: How good the aliveness proof is. Recorded per collector and carried into every alert, so a
#: weak signal never gets reported with the confidence of a strong one.
PROOF_HEARTBEAT: Final[str] = "heartbeat"
PROOF_EVENT: Final[str] = "event"
PROOF_MTIME: Final[str] = "mtime"

#: A cadence times its grace can still be a very short absolute window; below this a normal
#: scheduling hiccup would read as death.
MIN_GRACE_SECONDS: Final[float] = 90.0
#: A restarted collector needs time to connect and write its first heartbeat. Restarting again
#: inside this window would just be a loop that never lets it succeed.
DEFAULT_RESTART_COOLDOWN: Final[float] = 180.0
DEFAULT_MAX_RESTARTS_PER_HOUR: Final[int] = 5
#: Consecutive restarts that did not restore freshness before this becomes a critical alert.
DEFAULT_ALERT_AFTER_RESTARTS: Final[int] = 2
#: Telegram dedupe window per (collector, condition).
DEFAULT_ALERT_INTERVAL: Final[float] = 1800.0

OK: Final[str] = "ok"
STALE: Final[str] = "stale"
RESTARTED: Final[str] = "restarted"
GIVING_UP: Final[str] = "giving_up"
SKIPPED: Final[str] = "skipped"
COOLDOWN: Final[str] = "cooldown"


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


# --------------------------------------------------------------------------------------
# Freshness probes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Freshness:
    """When a collector last proved it was alive, and what the proof was."""

    seen_at: datetime | None
    detail: str
    #: Set when the collector's artefacts do not exist at all (never started, or a
    #: not-yet-built component like paperdesk). Distinct from "exists but is stale".
    absent: bool = False

    def age_seconds(self, now: datetime) -> float | None:
        if self.seen_at is None:
            return None
        return (now - self.seen_at).total_seconds()


def _parse_moment(value: Any) -> datetime | None:
    """ISO-8601 string or epoch seconds, whichever the tape uses. Naive means UTC."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Tapes here stamp seconds; a millisecond stamp would date to the year 57000.
        seconds = float(value)
        if seconds > 1e11:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def tail_lines(path: Path, *, budget_bytes: int = 4 * 1024 * 1024) -> Iterable[str]:
    """Yield lines from the end of a file backwards, reading at most ``budget_bytes``.

    The boards tape is 150+ MB per day and this runs once a minute; reading forwards would
    make the supervisor more expensive than the thing it supervises.
    """

    block = 256 * 1024
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        floor = max(0, position - budget_bytes)
        carry = b""
        while position > floor:
            step = min(block, position - floor)
            position -= step
            handle.seek(position)
            chunk = handle.read(step) + carry
            pieces = chunk.split(b"\n")
            carry = pieces[0]
            for piece in reversed(pieces[1:]):
                if piece.strip():
                    yield piece.decode("utf-8", "replace")
        if carry.strip() and position == 0:
            yield carry.decode("utf-8", "replace")


@dataclass(frozen=True, slots=True)
class JsonlProbe:
    """Newest row in the newest matching JSONL whose ``kind`` is one we accept as proof."""

    #: Directory to search, and a glob within it. The newest few files are scanned so a UTC
    #: day rollover (or a collector that stamped the day once at start) cannot read as death.
    root: Path
    pattern: str
    kinds: frozenset[str] | None
    time_fields: tuple[str, ...]
    kind_field: str = "kind"
    files_to_scan: int = 3

    def __call__(self) -> Freshness:
        if not self.root.is_dir():
            return Freshness(None, f"{self.root} does not exist", absent=True)
        files = sorted(self.root.glob(self.pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return Freshness(None, f"no file matches {self.root}/{self.pattern}", absent=True)
        for path in files[: self.files_to_scan]:
            for line in tail_lines(path):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if self.kinds is not None and str(row.get(self.kind_field)) not in self.kinds:
                    continue
                for field_name in self.time_fields:
                    moment = _parse_moment(row.get(field_name))
                    if moment is not None:
                        wanted = "any row" if self.kinds is None else "/".join(sorted(self.kinds))
                        return Freshness(moment, f"{path.name}: {wanted} at {field_name}")
        return Freshness(None, f"no usable row in the last {self.files_to_scan} file(s)")


@dataclass(frozen=True, slots=True)
class JsonFieldProbe:
    """One timestamp field out of one small JSON object."""

    path: Path
    field: str

    def __call__(self) -> Freshness:
        if not self.path.exists():
            return Freshness(None, f"{self.path} does not exist", absent=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Freshness(None, f"{self.path.name} unreadable ({type(exc).__name__})")
        moment = _parse_moment(payload.get(self.field) if isinstance(payload, dict) else None)
        if moment is None:
            return Freshness(None, f"{self.path.name} carries no {self.field}")
        phase = payload.get("phase") if isinstance(payload, dict) else None
        return Freshness(moment, f"{self.path.name}: {self.field}"
                                 + (f" (phase={phase})" if phase else ""))


@dataclass(frozen=True, slots=True)
class JsonMaxFieldProbe:
    """Newest value of a field across the top-level entries of a JSON object.

    The cluster recorder's ``cursors.json`` is rewritten every tick, so the newest
    ``last_poll_at`` across its pools is a per-poll liveness signal that costs nothing.
    """

    path: Path
    field: str

    def __call__(self) -> Freshness:
        if not self.path.exists():
            return Freshness(None, f"{self.path} does not exist", absent=True)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Freshness(None, f"{self.path.name} unreadable ({type(exc).__name__})")
        best: datetime | None = None
        if isinstance(payload, dict):
            for entry in payload.values():
                if isinstance(entry, dict):
                    moment = _parse_moment(entry.get(self.field))
                    if moment is not None and (best is None or moment > best):
                        best = moment
        if best is None:
            return Freshness(None, f"{self.path.name} carries no {self.field}")
        return Freshness(best, f"{self.path.name}: newest {self.field}")


@dataclass(frozen=True, slots=True)
class SqliteProbe:
    """Newest timestamp returned by a read-only query against a collector's SQLite store."""

    path: Path
    sql: str

    def __call__(self) -> Freshness:
        if not self.path.exists():
            return Freshness(None, f"{self.path} does not exist", absent=True)
        try:
            # Read-only URI: the supervisor must never be able to write a collector's store,
            # and must never take a write lock that could stall the collector itself.
            uri = f"file:{self.path}?mode=ro&immutable=0"
            with sqlite3.connect(uri, uri=True, timeout=5.0) as connection:
                row = connection.execute(self.sql).fetchone()
        except sqlite3.Error as exc:
            return Freshness(None, f"{self.path.name} query failed ({type(exc).__name__})")
        moment = _parse_moment(row[0]) if row else None
        if moment is None:
            return Freshness(None, f"{self.path.name} returned no timestamp")
        return Freshness(moment, f"{self.path.name}: {self.sql.split()[1][:40]}")


@dataclass(frozen=True, slots=True)
class MtimeProbe:
    path: Path
    pattern: str | None = None

    def __call__(self) -> Freshness:
        if self.pattern is not None:
            if not self.path.is_dir():
                return Freshness(None, f"{self.path} does not exist", absent=True)
            files = sorted(self.path.glob(self.pattern), key=lambda p: p.stat().st_mtime)
            if not files:
                return Freshness(None, f"no file matches {self.pattern}", absent=True)
            target = files[-1]
        else:
            if not self.path.exists():
                return Freshness(None, f"{self.path} does not exist", absent=True)
            target = self.path
        return Freshness(datetime.fromtimestamp(target.stat().st_mtime, UTC), f"{target.name} mtime")


# --------------------------------------------------------------------------------------
# The collector table
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CollectorSpec:
    name: str
    #: launchd label, or ``None`` for something the watchdog watches but does not own.
    label: str | None
    probe: Callable[[], Freshness]
    #: How often the collector is *supposed* to prove liveness.
    cadence_seconds: float
    #: Multiplier on the cadence before the collector is called stale.
    grace: float = 3.0
    proof: str = PROOF_HEARTBEAT
    #: True when absence of the artefacts entirely is expected (component not built yet).
    optional: bool = False
    #: False for things the watchdog reports on but must not restart (live money).
    restartable: bool = True
    note: str = ""

    @property
    def stale_after(self) -> float:
        return max(self.cadence_seconds * self.grace, MIN_GRACE_SECONDS)

    @property
    def plist(self) -> Path | None:
        return None if self.label is None else OPS_DIR / f"{self.label}.plist"


def default_collectors(root: Path = REPO_ROOT) -> tuple[CollectorSpec, ...]:
    state = root / "state"
    return (
        CollectorSpec(
            name="boards",
            label="com.shitcoims.boards",
            # `board_snapshot` is written on EVERY successful poll of every board, market
            # quiet or not (shitcoims_scalper/boards.py), so it is a true heartbeat even
            # though the recorder does not call it one. `board_entry`/`board_exit` are the
            # event rows and are deliberately NOT accepted as proof.
            probe=JsonlProbe(
                root=state / "boards",
                pattern="boards-*.jsonl",
                kinds=frozenset({"board_snapshot", "watch_open"}),
                time_fields=("t_ingest",),
            ),
            cadence_seconds=30.0,
            grace=4.0,
            proof=PROOF_HEARTBEAT,
            note="5 boards per 30s poll; every poll writes a snapshot row",
        ),
        CollectorSpec(
            name="firehose",
            label="com.shitcoims.firehose",
            # The firehose writes an explicit `heartbeat` row every 30s into its ledger
            # partition, carrying `connected` and `silent_seconds`. This is the strongest
            # liveness proof in the tree.
            probe=JsonlProbe(
                root=state / "firehose" / "ledger",
                pattern="*.jsonl",
                kinds=frozenset({"heartbeat", "watch_open"}),
                time_fields=("t_ingest",),
            ),
            cadence_seconds=30.0,
            grace=4.0,
            proof=PROOF_HEARTBEAT,
            note="pumpportal websocket; 30s heartbeat even while silent",
        ),
        CollectorSpec(
            name="cluster",
            label="com.shitcoims.cluster",
            # PROCESS liveness, not pool progress. `cursors.json` advances per pool and a
            # single pool resuming from a day-old cursor holds the loop for minutes, so a
            # per-pool clock reads as death during exactly the backfill a supervisor must
            # not interrupt — observed on the first install, where the recorder was 3.5
            # minutes into a legitimate catch-up. `heartbeat.json` is stamped at every
            # listing page and every getTransaction batch, so it ticks on work.
            probe=JsonFieldProbe(state / "cluster_tape" / "heartbeat.json", "t"),
            cadence_seconds=20.0,
            grace=9.0,
            proof=PROOF_HEARTBEAT,
            note="Helius poller, the only credit-consuming collector",
        ),
        CollectorSpec(
            name="inteld",
            label="com.shitcoims.inteld",
            # One `source_health` upsert per ingest cycle regardless of yield. The cycle is
            # nominally 600s but overruns to ~30min in practice, so the budget is generous
            # and set from observation rather than from the configured interval.
            probe=SqliteProbe(
                root / "intelligence_state" / "intelligence.sqlite3",
                "SELECT MAX(checked_at) FROM source_health_history",
            ),
            cadence_seconds=1800.0,
            grace=2.5,
            proof=PROOF_HEARTBEAT,
            note="per-cycle source_health write; cycle overruns its 600s budget routinely",
        ),
        CollectorSpec(
            name="paperdesk",
            label="com.shitcoims.paperdesk",
            probe=JsonlProbe(
                root=state / "paperdesk",
                pattern="*.jsonl",
                # The desk's ledger discriminates rows on `row`, not `kind`, and emits a
                # heartbeat row every ~60s regardless of market activity — so this is a
                # true HEARTBEAT-grade signal: silence means dead-or-wedged, never quiet.
                kinds=frozenset({"heartbeat"}),
                kind_field="row",
                time_fields=("t", "t_ingest", "timestamp"),
            ),
            cadence_seconds=60.0,
            grace=5.0,
            # Upgraded 2026-08-15 after the desk died exactly the way this file predicts:
            # it was bounced for a code fix on the assumption "the watchdog will revive
            # it", and the watchdog could not, because report-only with no plist. The
            # plist is ops/com.shitcoims.paperdesk.plist; the watchdog now restarts it
            # like boards/firehose/cluster.
            proof=PROOF_HEARTBEAT,
            optional=True,
            restartable=True,
            note="standing paper desk; heartbeat row every minute is the liveness proof",
        ),
        CollectorSpec(
            name="sentinel",
            label=None,
            # LIVE MONEY. Reported, never restarted: a supervisor that can start a trading
            # daemon is a supervisor that can start it at the wrong moment.
            probe=JsonlProbe(
                root=state,
                pattern="events.jsonl",
                kinds=None,
                time_fields=("timestamp",),
            ),
            cadence_seconds=6 * 3600.0,
            grace=1.5,
            proof=PROOF_EVENT,
            optional=True,
            restartable=False,
            note="live trading; watchdog REPORTS only and never starts or stops it",
        ),
    )


# --------------------------------------------------------------------------------------
# launchd
# --------------------------------------------------------------------------------------


class LaunchCtl:
    """The bit that actually restarts things. Injectable so tests never touch launchd."""

    def __init__(self, runner: Callable[[Sequence[str]], subprocess.CompletedProcess] | None = None):
        self._run = runner or self._subprocess

    @staticmethod
    def _subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess:
        """Run, and turn a hang into a failed result rather than an exception.

        ``launchctl kickstart -k`` blocks until the old instance is gone, and a collector that
        drains work on SIGTERM can outlast the timeout. Raising there aborted the whole
        supervisor pass — so every OTHER collector went unchecked because one was slow to
        stop, which is precisely the single-point-of-failure a supervisor must not have.
        """

        try:
            return subprocess.run(
                list(argv), capture_output=True, text=True, check=False, timeout=30
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(list(argv), 124, "", "timed out after 30s")
        except OSError as exc:
            return subprocess.CompletedProcess(list(argv), 127, "", type(exc).__name__)

    @property
    def domain(self) -> str:
        return f"gui/{os.getuid()}"

    def is_loaded(self, label: str) -> bool:
        return self._run(["launchctl", "print", f"{self.domain}/{label}"]).returncode == 0

    def bootstrap(self, label: str, plist: Path) -> tuple[bool, str]:
        """Install and load a job that is not currently known to launchd."""

        target = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(plist.read_bytes())
            target.chmod(0o600)
        except OSError as exc:
            return False, f"could not install {target.name} ({type(exc).__name__})"
        result = self._run(["launchctl", "bootstrap", self.domain, str(target)])
        if result.returncode != 0:
            return False, f"bootstrap failed: {(result.stderr or result.stdout).strip()[:200]}"
        self._run(["launchctl", "enable", f"{self.domain}/{label}"])
        return True, f"bootstrapped {label}"

    def restart(self, label: str, plist: Path | None) -> tuple[bool, str]:
        """Bring a job back. Bootstraps it first when launchd has never heard of it.

        The ``-k`` is conditional and that matters. A job just bootstrapped with
        ``RunAtLoad`` is ALREADY running, so ``kickstart -k`` would SIGTERM the process
        bootstrap had started one instant earlier and then block waiting for it to die —
        which timed out at 30s against the cluster recorder and failed a restart that had in
        fact succeeded. ``-k`` is for the job that was loaded but wedged; a job that was
        absent only needs starting.
        """

        booted = ""
        if not self.is_loaded(label):
            if plist is None or not plist.exists():
                return False, f"{label} is not loaded and {plist} is missing"
            ok, detail = self.bootstrap(label, plist)
            if not ok:
                return False, detail
            booted = detail + "; "
            argv = ["launchctl", "kickstart", f"{self.domain}/{label}"]
        else:
            argv = ["launchctl", "kickstart", "-k", f"{self.domain}/{label}"]
        result = self._run(argv)
        if result.returncode != 0:
            return False, f"{booted}kickstart failed: {(result.stderr or result.stdout).strip()[:200]}"
        return True, f"{booted}kickstarted {label}"


# --------------------------------------------------------------------------------------
# Telegram — the sentinel's MECHANISM, deliberately not the sentinel's CODE
# --------------------------------------------------------------------------------------


class Telegram:
    """Minimal Telegram sender, reimplemented rather than imported.

    ``shitcoims_sentinel/notifier.py`` does this already and is the reference for the wire
    format, but importing it would make a research supervisor a dependency of the live
    trading package (and vice versa) — the same coupling ``shitcoims_cluster/rpc.py`` refuses
    for ``secrets.py``. Two rules carried over verbatim because they are load-bearing:

    * **The bot token is inside the request URL**, so an exception is never stringified —
      only its class name is ever logged.
    * A delivery failure is logged and the pass continues. Losing an alert must not lose the
      restart that the alert was about.
    """

    def __init__(self, token: str | None, chat_id: str | None, *, sender: Callable[..., Any] | None = None):
        self.token = token
        self.chat_id = chat_id
        self._sender = sender
        self.last_error_type: str | None = None
        self.sent = 0

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.configured:
            return False
        try:
            if self._sender is not None:
                self._sender(self.token, self.chat_id, text)
            else:
                import httpx

                response = httpx.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text},
                    timeout=15.0,
                )
                response.raise_for_status()
                if response.json().get("ok") is not True:
                    raise ValueError("Telegram rejected the message")
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            print(f"[watchdog] Telegram delivery failed ({type(exc).__name__})", file=sys.stderr)
            return False
        self.sent += 1
        self.last_error_type = None
        return True


def _scalar(text: str, key: str, section: str | None = None) -> str | None:
    """Pull one scalar out of config.yaml without importing yaml.

    The supervisor must start even when the research extras are not installed, and it needs
    exactly two strings out of one known-shape block.
    """

    if section is not None:
        match = re.search(rf"^{re.escape(section)}:\s*$", text, re.MULTILINE)
        if match is None:
            return None
        rest = text[match.end() :]
        end = re.search(r"^\S", rest, re.MULTILINE)
        text = rest[: end.start()] if end else rest
    found = re.search(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if found is None:
        return None
    return found.group(1).strip().strip("'\"")


def telegram_from_config(config_path: Path = CONFIG_PATH, **kwargs: Any) -> Telegram:
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return Telegram(None, None, **kwargs)
    token_file = _scalar(text, "telegram_bot_token_file", "notifications")
    chat_id = _scalar(text, "telegram_chat_id", "notifications")
    token: str | None = None
    if token_file:
        try:
            path = Path(token_file).expanduser()
            info = path.stat()
            if info.st_mode & 0o077:
                print(f"[watchdog] refusing group/world-readable secret {path}", file=sys.stderr)
            else:
                token = path.read_text(encoding="utf-8").strip() or None
        except OSError:
            token = None
    return Telegram(token, chat_id, **kwargs)


# --------------------------------------------------------------------------------------
# The supervisor
# --------------------------------------------------------------------------------------


@dataclass
class Verdict:
    name: str
    status: str
    age_seconds: float | None
    stale_after: float
    proof: str
    detail: str
    action: str = ""
    alerted: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "collector": self.name,
            "status": self.status,
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 3),
            "stale_after_seconds": round(self.stale_after, 3),
            "proof": self.proof,
            "detail": self.detail,
            "action": self.action,
            "alerted": self.alerted,
        }


@dataclass
class Supervisor:
    collectors: Sequence[CollectorSpec]
    launchctl: LaunchCtl
    telegram: Telegram
    state_path: Path = STATE_PATH
    journal_path: Path = JOURNAL_PATH
    clock: Callable[[], datetime] = utc_now
    restart_cooldown: float = DEFAULT_RESTART_COOLDOWN
    max_restarts_per_hour: int = DEFAULT_MAX_RESTARTS_PER_HOUR
    alert_after_restarts: int = DEFAULT_ALERT_AFTER_RESTARTS
    alert_interval: float = DEFAULT_ALERT_INTERVAL
    dry_run: bool = False
    state: dict[str, Any] = field(default_factory=dict)

    # -- state -----------------------------------------------------------------------

    def load_state(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        self.state = payload if isinstance(payload, dict) else {}

    def save_state(self) -> None:
        if self.dry_run:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.state, indent=1, sort_keys=True), encoding="utf-8")
        temp.replace(self.state_path)

    def _entry(self, name: str) -> dict[str, Any]:
        entry = self.state.setdefault(name, {})
        entry.setdefault("restarts", [])
        entry.setdefault("consecutive_restarts", 0)
        entry.setdefault("last_restart_at", None)
        entry.setdefault("alerts", {})
        return entry

    def _recent_restarts(self, entry: dict[str, Any], now: datetime) -> list[str]:
        cutoff = now - timedelta(hours=1)
        kept = [
            stamp
            for stamp in entry["restarts"]
            if (parsed := _parse_moment(stamp)) is not None and parsed >= cutoff
        ]
        entry["restarts"] = kept
        return kept

    # -- alerting --------------------------------------------------------------------

    def alert(self, name: str, key: str, text: str, now: datetime) -> bool:
        entry = self._entry(name)
        last = _parse_moment(entry["alerts"].get(key))
        if last is not None and (now - last).total_seconds() < self.alert_interval:
            return False
        entry["alerts"][key] = iso(now)
        print(f"[watchdog] ALERT {name}/{key}: {text}", file=sys.stderr)
        if not self.dry_run:
            self.telegram.send(text)
        return True

    def clear_alerts(self, name: str) -> None:
        self._entry(name)["alerts"] = {}

    # -- the pass --------------------------------------------------------------------

    def check(self, spec: CollectorSpec) -> Verdict:
        now = self.clock()
        entry = self._entry(spec.name)
        try:
            freshness = spec.probe()
        except Exception as exc:
            return Verdict(spec.name, STALE, None, spec.stale_after, spec.proof,
                           f"probe raised {type(exc).__name__}")

        age = freshness.age_seconds(now)
        verdict = Verdict(spec.name, OK, age, spec.stale_after, spec.proof, freshness.detail)

        if freshness.absent and spec.optional:
            verdict.status = SKIPPED
            return verdict
        if age is not None and age <= spec.stale_after:
            entry["consecutive_restarts"] = 0
            entry["last_fresh_at"] = iso(now)
            self.clear_alerts(spec.name)
            return verdict

        verdict.status = STALE
        aged = "never" if age is None else f"{age / 60:.1f} min"
        # A weaker proof means a weaker claim. Say which one this is in the alert itself.
        claim = {
            PROOF_HEARTBEAT: "its heartbeat stopped, so this is a dead or wedged process",
            PROOF_EVENT: "only event rows are available, so a genuinely quiet market cannot "
            "be ruled out",
            PROOF_MTIME: "only a file mtime is available; this is the weakest signal here",
        }[spec.proof]

        if not spec.restartable or spec.label is None:
            verdict.action = "report only"
            verdict.alerted = self.alert(
                spec.name,
                "stale-noauto",
                f"⚠️ {spec.name} is stale ({aged} since last row, budget "
                f"{spec.stale_after / 60:.1f} min) — {claim}. The watchdog does NOT restart "
                f"this one. {freshness.detail}",
                now,
            )
            return verdict

        last_restart = _parse_moment(entry["last_restart_at"])
        if last_restart is not None and (now - last_restart).total_seconds() < self.restart_cooldown:
            verdict.status = COOLDOWN
            verdict.action = "waiting out the restart cooldown"
            return verdict

        recent = self._recent_restarts(entry, now)
        if len(recent) >= self.max_restarts_per_hour:
            verdict.status = GIVING_UP
            verdict.action = "restart budget exhausted"
            verdict.alerted = self.alert(
                spec.name,
                "restart-budget",
                f"🚨 {spec.name} has been restarted {len(recent)}x in the last hour and is "
                f"STILL stale ({aged}). The watchdog has stopped restarting it to avoid a "
                f"crash loop against a metered API. This needs a human. {freshness.detail}",
                now,
            )
            return verdict

        if self.dry_run:
            verdict.status = RESTARTED
            verdict.action = "would restart (dry run)"
            return verdict

        ok, detail = self.launchctl.restart(spec.label, spec.plist)
        entry["last_restart_at"] = iso(now)
        entry["restarts"].append(iso(now))
        entry["consecutive_restarts"] = int(entry["consecutive_restarts"]) + 1
        verdict.action = detail
        if not ok:
            verdict.status = GIVING_UP
            verdict.alerted = self.alert(
                spec.name, "restart-failed",
                f"🚨 {spec.name} is stale ({aged}) and the watchdog COULD NOT restart it: "
                f"{detail}",
                now,
            )
            return verdict

        verdict.status = RESTARTED
        if entry["consecutive_restarts"] >= self.alert_after_restarts:
            verdict.alerted = self.alert(
                spec.name, "repeat-restart",
                f"🚨 {spec.name} has needed {entry['consecutive_restarts']} restarts in a row "
                f"and keeps going stale ({aged} at the last check) — {claim}. {detail}",
                now,
            )
        return verdict

    def run_once(self) -> list[Verdict]:
        self.load_state()
        verdicts = [self.check(spec) for spec in self.collectors]
        now = self.clock()
        self.state["_watchdog"] = {"last_pass_at": iso(now), "passes": int(
            (self.state.get("_watchdog") or {}).get("passes", 0)) + 1}
        self.save_state()
        self.write_journal(verdicts, now)
        return verdicts

    def write_journal(self, verdicts: Sequence[Verdict], now: datetime) -> None:
        """The supervisor's own heartbeat: one row per pass, whatever the pass found."""

        if self.dry_run:
            return
        row = {
            "kind": "watchdog_pass",
            "t": iso(now),
            "telegram_configured": self.telegram.configured,
            "collectors": [v.to_json() for v in verdicts],
        }
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            print(f"[watchdog] journal write failed ({type(exc).__name__})", file=sys.stderr)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


class AlreadyRunning(RuntimeError):
    pass


def acquire_lock(path: Path | None = None):
    """Exclusive, non-blocking. This is what makes a double-fire harmless.

    ``path`` resolves :data:`LOCK_PATH` at CALL time rather than binding it as a default at
    import time. That is not a style preference: with the default bound, a test that
    monkeypatched ``LOCK_PATH`` still took the real repo lock, ran a real supervisor pass and
    restarted live daemons out of the test suite — which is exactly what happened, twice, and
    then collided with a restart demo running in another window.
    """

    path = LOCK_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise AlreadyRunning(f"another watchdog pass holds {path}") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {iso(utc_now())}\n")
    handle.flush()
    return handle


def render(verdicts: Sequence[Verdict]) -> str:
    lines = [f"{'collector':<11} {'status':<10} {'age':>10} {'budget':>9} {'proof':<10} detail"]
    for v in verdicts:
        age = "never" if v.age_seconds is None else f"{v.age_seconds / 60:.1f}m"
        lines.append(
            f"{v.name:<11} {v.status:<10} {age:>10} {v.stale_after / 60:>8.1f}m "
            f"{v.proof:<10} {v.detail}"
            + (f" -> {v.action}" if v.action else "")
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watchdog", description="Supervise every shitcoims collector: freshness, restart, scream."
    )
    parser.add_argument("--interval", type=float, default=0.0,
                        help="loop forever with this many seconds between passes "
                             "(default 0: one pass, which is what launchd StartInterval wants)")
    parser.add_argument("--only", action="append", default=None,
                        help="restrict to one collector by name; repeatable")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe and report, but never restart, alert or write state")
    parser.add_argument("--no-telegram", action="store_true", help="stdout/stderr alerts only")
    parser.add_argument("--json", action="store_true", help="machine-readable verdicts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    collectors = default_collectors()
    if args.only:
        wanted = set(args.only)
        collectors = tuple(c for c in collectors if c.name in wanted)
        if not collectors:
            raise SystemExit(f"no collector matches {sorted(wanted)}")

    try:
        lock = acquire_lock()
    except AlreadyRunning as exc:
        # Not an error: this is the double-fire case working as designed.
        print(f"[watchdog] {exc}; this pass is a no-op", file=sys.stderr)
        return 0

    telegram = Telegram(None, None) if args.no_telegram else telegram_from_config()
    if not telegram.configured and not args.no_telegram:
        print("[watchdog] Telegram is not configured; alerts go to stderr only", file=sys.stderr)

    supervisor = Supervisor(
        collectors=collectors,
        launchctl=LaunchCtl(),
        telegram=telegram,
        dry_run=args.dry_run,
    )

    try:
        while True:
            verdicts = supervisor.run_once()
            if args.json:
                print(json.dumps([v.to_json() for v in verdicts], indent=1, sort_keys=True))
            else:
                print(render(verdicts), flush=True)
            if args.interval <= 0:
                break
            time.sleep(args.interval)
    finally:
        lock.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
