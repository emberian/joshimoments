"""The watch matcher loop: tail three surfaces, match subscriptions, DM through the gate.

Each cycle (default every 10s — the sources are local files, polling is nearly free):

1. Re-read config (keep-last-good: a broken edit keeps the running settings and says
   so in the heartbeat — the archive/feed discipline, verbatim).
2. Read the verified-member set from the gate db (read-only). If the gate db cannot
   be read, the WHOLE cycle stands down — cursors do not advance, so no event is ever
   consumed while nobody could be told about it.
3. Tail screen scores / archive callouts / feed alerts (matcher.py; durable cursors,
   first boot starts AT the present and emits nothing).
4. For each event x matching subscription (owner must be a current member, 'ok' or
   'grace'): claim (sub, event) in the sent table — the never-double-send gate — then
   either enqueue one plain-text DM into the gate outbox, or fold the line into the
   digest queue (digest-mode subs, and any event-mode sub whose owner is over the
   per-user hourly DM ceiling: over the ceiling means BATCHED LATER, never dropped).
5. Advance cursors — only now, so a crash mid-cycle replays into claims, not silence.
6. Flush digests every digest_every_min: stamp pending lines durably, enqueue one DM
   per user keyed by the stamp, delete. A crash mid-flush recovers by re-running the
   SAME stamp (same outbox dedup key) — idempotent, both directions.

DELIVERY: `deliver = false` (the shipped default) writes every would-be DM to
`<state>/previews.log` instead of the outbox — full pipeline, zero sends — and still
claims/logs, so flipping to true never replays the preview period as real DMs. The
operator flips `deliver = true` in the config; the running service picks it up next
cycle. DMs go to chat_id == tg_user_id (Telegram: a user's private chat id IS their
user id); users who blocked the bot are dropped by the gate's own outbox 403 handling.

Systemd-ready: `uv run python -m dregg_watch.service --config <toml>` runs forever,
exits promptly on SIGTERM/SIGINT, writes heartbeat.json atomically every cycle.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sqlite3
import time
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from . import matcher
from .state import Subscription, WatchState

LOGGER = logging.getLogger("dregg_watch.service")

REPO_ROOT = Path(__file__).resolve().parent.parent

INIT_CURSOR = "init"
LAST_FLUSH_CURSOR = "digest:last_flush"


@dataclass(frozen=True, slots=True)
class Config:
    state_dir: Path = REPO_ROOT / "state" / "dregg_watch"
    watch_db: Path = REPO_ROOT / "state" / "dregg_watch" / "watch.sqlite"
    gate_db: Path | None = None      # the gate's sqlite; None means nowhere to deliver
    scores_dir: Path | None = None   # dregg_screen.live's <day>.jsonl dir
    archive_db: Path | None = None   # dregg_archive's sqlite (callouts table)
    feed_db: Path | None = None      # dregg_feed's sqlite (alerts table)
    deliver: bool = False            # the operator flips this on; default is preview
    poll_s: float = 10.0
    digest_every_min: float = 30.0
    max_dms_per_hour: int = 20       # per user; overflow rides the next digest
    digest_max_lines: int = 15       # lines shown per digest DM (count stays honest)

    _PATH_KEYS = ("state_dir", "watch_db", "gate_db", "scores_dir", "archive_db", "feed_db")

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        cfg = cls()
        if path is None:
            return cfg
        raw = tomllib.loads(path.read_text())
        for key, value in raw.items():
            if not hasattr(cfg, key) or key.startswith("_"):
                raise ValueError(f"unknown config key {key!r}")
            if key in cls._PATH_KEYS:
                value = Path(str(value)).expanduser()
                if not value.is_absolute():
                    value = REPO_ROOT / value
            else:
                current = getattr(cfg, key)
                if isinstance(current, bool):
                    if not isinstance(value, bool):
                        raise ValueError(f"config key {key!r}: expected bool")
                elif isinstance(current, int):
                    value = int(value)
                elif isinstance(current, float):
                    value = float(value)
            cfg = replace(cfg, **{key: value})
        if cfg.poll_s <= 0:
            raise ValueError("poll_s must be positive")
        if cfg.digest_every_min < 1.0:
            raise ValueError("digest_every_min below 1 minute is a firehose, not a digest")
        if cfg.max_dms_per_hour < 1:
            raise ValueError("max_dms_per_hour must be positive")
        if cfg.digest_max_lines < 1:
            raise ValueError("digest_max_lines must be positive")
        return cfg


# -- gate-db touchpoints (raw sqlite, the dregg_feed/dregg_screen.digest pattern) ------


def enqueue_dm(gate_db: Path, *, dedup_key: str, chat_id: int, text: str) -> None:
    """INSERT one plain-text DM into the gate outbox. No parse_mode, ever — the whole
    module composes for the no-markup lane."""

    connection = sqlite3.connect(gate_db, timeout=10.0)
    try:
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (dedup_key, "sendMessage", json.dumps(payload, separators=(",", ":")), time.time()),
            )
    finally:
        connection.close()


def current_members(gate_db: Path) -> set[int]:
    """tg user ids still holding a seat ('ok' or 'grace' — grace is still in the group)."""

    connection = sqlite3.connect(f"file:{gate_db}?mode=ro", uri=True, timeout=5.0)
    try:
        rows = connection.execute(
            "SELECT tg_user_id FROM members WHERE status IN ('ok', 'grace')"
        ).fetchall()
        return {int(row[0]) for row in rows}
    finally:
        connection.close()


# -- the service -----------------------------------------------------------------------


class WatchService:
    def __init__(
        self,
        config_path: Path | None,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config_path = config_path
        self.cfg = Config.load(config_path)  # boot REQUIRES a valid config
        self.cfg_status = "ok"
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.cfg.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state = WatchState(self.cfg.watch_db)
        self.cycle_n = 0
        self.last_errors: list[str] = []
        self.last_cycle: dict[str, Any] = {}
        self._stopping = False

    # -- config (keep-last-good) ---------------------------------------------------

    def _reload_config(self) -> None:
        if self.config_path is None:
            return
        try:
            fresh = Config.load(self.config_path)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            self.cfg_status = f"kept_last_good: {exc}"
            return
        if fresh.watch_db != self.cfg.watch_db or fresh.state_dir != self.cfg.state_dir:
            self.cfg_status = "kept_last_good: watch_db/state_dir cannot change while running"
            return
        self.cfg = fresh
        self.cfg_status = "ok"

    def _error(self, label: str, detail: str) -> None:
        line = f"{label}: {detail}"[:300]
        self.last_errors = [*self.last_errors, line][-10:]
        LOGGER.error("%s", line)

    # -- delivery (one seam for the deliver switch) -----------------------------------

    def _send(self, uid: int, dedup_key: str, text: str) -> bool:
        """True when handed off (outbox or preview). Raises nothing to the caller."""

        if self.cfg.deliver and self.cfg.gate_db is not None:
            try:
                enqueue_dm(self.cfg.gate_db, dedup_key=dedup_key, chat_id=uid, text=text)
                return True
            except sqlite3.Error as exc:
                self._error("enqueue", f"{type(exc).__name__}: {exc}")
                return False
        preview = self.cfg.state_dir / "previews.log"
        try:
            with preview.open("a") as fh:
                stamp = datetime.fromtimestamp(self.clock(), UTC).isoformat()
                fh.write(f"--- {stamp} to={uid} dedup={dedup_key}\n{text}\n")
        except OSError as exc:
            self._error("preview", f"{type(exc).__name__}: {exc}")
        return True  # preview parity: claims and rate logs behave as if sent

    # -- one cycle ---------------------------------------------------------------------

    def cycle(self) -> dict[str, Any]:
        self.cycle_n += 1
        self._reload_config()
        now = self.clock()
        stats: dict[str, Any] = {
            "events": {"screen": 0, "callout": 0, "feed": 0},
            "dms": 0, "digest_queued": 0, "rate_diverted": 0, "digests_sent": 0,
        }

        members: set[int] | None = None
        if self.cfg.gate_db is not None and self.cfg.gate_db.exists():
            try:
                members = current_members(self.cfg.gate_db)
            except sqlite3.Error as exc:
                self._error("members", f"{type(exc).__name__}: {exc}")
        if members is None:
            # No member set means no way to gate delivery — stand down whole, advance
            # nothing, so the events are still there when the gate db is back.
            stats["stood_down"] = "gate db unreadable or unconfigured"
            return self._finish(now, stats)

        first_run = self.state.cursor(INIT_CURSOR) is None
        results: list[matcher.TailResult] = []
        if self.cfg.scores_dir is not None:
            results.append(
                matcher.tail_screen(self.cfg.scores_dir, self.state, now, first_run=first_run)
            )
        if self.cfg.archive_db is not None:
            results.append(matcher.tail_callouts(self.cfg.archive_db, self.state, first_run=first_run))
        if self.cfg.feed_db is not None:
            results.append(matcher.tail_feed(self.cfg.feed_db, self.state, first_run=first_run))

        subs = [s for s in self.state.all_subs() if s.tg_user_id in members]
        cursor_updates: dict[str, str] = {}
        for result in results:
            for error in result.errors:
                self._error("tail", error)
            cursor_updates.update(result.cursor_updates)
            for event in result.events:
                stats["events"][event.source] = stats["events"].get(event.source, 0) + 1
                for sub in matcher.match_all(subs, event):
                    self._dispatch(sub, event, now, stats)

        # Cursors advance LAST: a crash above replays into sent-table claims, not silence.
        cursor_updates[INIT_CURSOR] = "1"
        self.state.set_cursors(cursor_updates)

        self._flush_digests(now, stats)
        try:
            self.state.prune(now)
        except sqlite3.Error as exc:
            self._error("prune", f"{type(exc).__name__}: {exc}")
        return self._finish(now, stats)

    def _dispatch(
        self, sub: Subscription, event: matcher.Event, now: float, stats: dict[str, Any]
    ) -> None:
        if not self.state.claim(sub.id, event.key, now):
            return  # already sent (or queued) for this (sub, event) — ever
        if sub.mode == "digest":
            self.state.queue_digest(sub.id, sub.tg_user_id, matcher.render_digest_line(sub, event), now)
            stats["digest_queued"] += 1
            return
        if self.state.dms_last_hour(sub.tg_user_id, now) >= self.cfg.max_dms_per_hour:
            # Over the ceiling: batched later, never dropped — the digest is the overflow.
            self.state.queue_digest(sub.id, sub.tg_user_id, matcher.render_digest_line(sub, event), now)
            stats["rate_diverted"] += 1
            return
        text = matcher.render_dm(sub, event)
        if self._send(sub.tg_user_id, f"dregg-watch:{sub.id}:{event.key}", text):
            self.state.log_dm(sub.tg_user_id, now)
            stats["dms"] += 1
        else:
            self.state.unclaim(sub.id, event.key)  # transient gate-db failure: retry next cycle

    # -- digests -----------------------------------------------------------------------

    def _flush_digests(self, now: float, stats: dict[str, Any]) -> None:
        # Recovery first: stamps left by a crash mid-flush re-run with their own key.
        pending = self.state.stamped_flushes()
        last_raw = self.state.cursor(LAST_FLUSH_CURSOR)
        due = last_raw is None or now - float(last_raw) >= self.cfg.digest_every_min * 60.0
        if due:
            pending += self.state.stamp_flush(now)
            self.state.set_cursor(LAST_FLUSH_CURSOR, str(now))
        for uid, stamp in pending:
            lines = self.state.flush_lines(uid, stamp)
            if not lines:
                self.state.clear_flush(uid, stamp)
                continue
            text = matcher.render_digest(
                lines, window_min=self.cfg.digest_every_min, max_lines=self.cfg.digest_max_lines
            )
            if self._send(uid, f"dregg-watch:digest:{uid}:{stamp}", text):
                self.state.clear_flush(uid, stamp)
                self.state.log_dm(uid, now)
                stats["digests_sent"] += 1
            # on failure the stamp stays; next cycle re-runs the SAME flush (same key)

    # -- heartbeat ---------------------------------------------------------------------

    def _finish(self, now: float, stats: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "t": datetime.fromtimestamp(now, UTC).isoformat(),
            "cycle": self.cycle_n,
            "config_status": self.cfg_status,
            "deliver": self.cfg.deliver,
            "subscriptions": len(self.state.all_subs()),
            "digest_pending": self.state.pending_digest_count(),
            **stats,
            "last_errors": self.last_errors,
        }
        self.last_cycle = payload
        path = self.cfg.state_dir / "heartbeat.json"
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=1) + "\n")
            tmp.rename(path)
        except OSError as exc:
            self._error("heartbeat", f"{type(exc).__name__}: {exc}")
        return payload

    # -- the loop ----------------------------------------------------------------------

    def run(self) -> None:
        def _stop(_signum: int, _frame: Any) -> None:
            self._stopping = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        while not self._stopping:
            started = time.monotonic()
            try:
                self.cycle()
            except Exception as exc:  # the loop outlives any one cycle
                self._error("cycle", f"{type(exc).__name__}: {exc}")
            elapsed = time.monotonic() - started
            deadline = time.monotonic() + max(self.cfg.poll_s - elapsed, 0.5)
            while not self._stopping and time.monotonic() < deadline:
                self.sleep(min(1.0, deadline - time.monotonic()))
        self.state.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="dregg_watch: personal alerts for verified holders")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--once", action="store_true", help="one cycle, print the heartbeat, exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    service = WatchService(args.config)
    if args.once:
        print(json.dumps(service.cycle(), indent=1))
        service.state.close()
        return
    service.run()


if __name__ == "__main__":
    main()
