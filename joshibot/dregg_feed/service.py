"""The feed loop: poll movers ~75s, detect, render the chart, enqueue into the GATE.

DELIVERY IS OFF BY DEFAULT. `deliver = false` composes everything and appends the
would-be alerts to `<state>/previews.log` (and the heartbeat) without touching the
gate outbox — the operator flips `deliver = true` in the config file and the running
service picks it up on the next cycle (keep-last-good reload, same as the archive:
a broken edit keeps yesterday's settings and says so in the heartbeat, never a crash
loop). Alerts go through dregg_gate's outbox ONLY — one bot, one group, one queue —
using the same raw-INSERT pattern as dregg_screen.digest (WAL + busy_timeout, no
GateState: its flock guards the poller identity, not writers).

BUDGET: every wire request this service makes — board polls AND candle fetches,
retries included (counted from the client's own stats) — spends from one durable
daily ceiling (default 1,200). At 75s cadence the board alone is ~1,152/day; charts
ride in the remainder because alerts are rare by design. When the ceiling is hit the
loop idles until the next UTC day, visibly in the heartbeat.

CHART SPOOL: PNGs land in `<state>/spool/` and the outbox row carries the PATH (the
gate reads the bytes at delivery time; a lost file is a definitive drop there, never a
dam). The spool self-prunes after `spool_keep_h`.

Systemd-ready: `uv run python -m dregg_feed.service --config <toml>` runs forever,
exits promptly on SIGTERM/SIGINT, writes `heartbeat.json` atomically every cycle.
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

from shitcoims_pumpsocial.client import PumpSocialClient, Transport

from . import compose
from .charts import ChartRenderer
from .movers import Alert, FeedState, MoversPage, Thresholds, detect, fetch_movers, utc_day
from .verdicts import VerdictIndex

LOGGER = logging.getLogger("dregg_feed.service")

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Config:
    state_dir: Path = REPO_ROOT / "state" / "dregg_feed"
    gate_db: Path | None = None       # the gate's sqlite; None means nowhere to deliver
    scores_dir: Path | None = None    # the screen's scores JSONL dir; None -> unscored
    poll_s: float = 75.0
    board_limit: int = 100            # provider clamps at 150 silently
    daily_budget: int = 1200          # board polls + candle fetches, retries included
    deliver: bool = False             # the operator flips this on; default is preview
    min_v5_sol: float = 250.0
    accel_ratio: float = 1.6
    top5_min_v5_sol: float = 400.0
    cooldown_h: float = 2.0
    max_alerts_per_hour: int = 6
    prev_max_age_s: float = 360.0
    chart_interval: str = "5m"
    chart_limit: int = 72             # 72 x 5m = 6h window
    spool_keep_h: float = 48.0
    verdict_days: int = 2

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(
            min_v5_sol=self.min_v5_sol,
            accel_ratio=self.accel_ratio,
            top5_min_v5_sol=self.top5_min_v5_sol,
            cooldown_s=self.cooldown_h * 3600.0,
            max_alerts_per_hour=self.max_alerts_per_hour,
            prev_max_age_s=self.prev_max_age_s,
        )

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        cfg = cls()
        if path is None:
            return cfg
        raw = tomllib.loads(path.read_text())
        for key, value in raw.items():
            if not hasattr(cfg, key) or key == "thresholds":
                raise ValueError(f"unknown config key {key!r}")
            current = getattr(cfg, key)
            if isinstance(current, Path) or (current is None and key in ("gate_db", "scores_dir")):
                value = Path(str(value)).expanduser()
                if not value.is_absolute():
                    value = REPO_ROOT / value
            elif isinstance(current, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"config key {key!r}: expected bool")
            elif isinstance(current, int):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            elif isinstance(current, str):
                value = str(value)
            cfg = replace(cfg, **{key: value})
        if cfg.poll_s <= 0 or cfg.daily_budget <= 0:
            raise ValueError("poll_s and daily_budget must be positive")
        if cfg.cooldown_h < 2.0:
            raise ValueError("cooldown_h below 2 is out of bounds for this product")
        return cfg


def enqueue_alert(
    gate_db: Path, *, dedup_key: str, caption: str, photo_path: Path | None
) -> bool:
    """INSERT into the gate outbox iff a group is bound — dregg_screen.digest's exact
    pattern, extended to sendPhoto. Returns whether enqueued."""

    connection = sqlite3.connect(gate_db, timeout=10.0)
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'group_id'"
        ).fetchone()
        if row is None:
            return False
        chat_id = int(row[0])
        if photo_path is not None:
            method = "sendPhoto"
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "photo_path": str(photo_path),
                "caption": caption,
                "parse_mode": "HTML",
            }
        else:
            method = "sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (dedup_key, method, json.dumps(payload, separators=(",", ":")), time.time()),
            )
        return True
    finally:
        connection.close()


class FeedService:
    def __init__(
        self,
        config_path: Path | None,
        *,
        movers_transport: Transport | None = None,
        candles_transport: Transport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config_path = config_path
        self.cfg = Config.load(config_path)  # boot REQUIRES a valid config
        self.cfg_status = "ok"
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self._movers_transport = movers_transport
        self.cfg.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.spool_dir = self.cfg.state_dir / "spool"
        self.spool_dir.mkdir(mode=0o700, exist_ok=True)
        self.state = FeedState(self.cfg.state_dir / "feed.sqlite")
        self.client = PumpSocialClient(transport=candles_transport, sleep=self.sleep)
        self.renderer = ChartRenderer(self.client)
        self.verdicts = (
            VerdictIndex(self.cfg.scores_dir, days=self.cfg.verdict_days)
            if self.cfg.scores_dir
            else None
        )
        self.cycle_n = 0
        self.alerts_this_cycle: list[dict[str, Any]] = []
        self.last_errors: list[str] = []
        self.last_board: dict[str, Any] | None = None
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
        if fresh.state_dir != self.cfg.state_dir:
            self.cfg_status = "kept_last_good: state_dir cannot change while running"
            return
        if fresh.scores_dir != self.cfg.scores_dir:
            self.verdicts = (
                VerdictIndex(fresh.scores_dir, days=fresh.verdict_days)
                if fresh.scores_dir
                else None
            )
        self.cfg = fresh
        self.cfg_status = "ok"

    def _error(self, label: str, exc: Exception) -> None:
        line = f"{label}: {type(exc).__name__}: {exc}"[:300]
        self.last_errors = [*self.last_errors, line][-10:]
        LOGGER.error("%s", line)

    # -- one alert out ---------------------------------------------------------------

    def _emit(self, alert: Alert, now: float, day: str) -> None:
        verdict = None
        if self.verdicts is not None:
            try:
                verdict = self.verdicts.verdict(alert.mint, now)
            except Exception as exc:  # a broken scores file must not kill the alert
                self._error("verdict", exc)

        png: bytes | None = None
        if self.state.budget_spent(day) < self.cfg.daily_budget:
            before = self.client.stats.requests
            png = self.renderer.render(
                alert.mint, alert.symbol, now,
                interval=self.cfg.chart_interval, limit=self.cfg.chart_limit,
            )
            spent = self.client.stats.requests - before
            if spent:
                self.state.budget_spend(day, spent)

        photo_path: Path | None = None
        if png is not None:
            photo_path = self.spool_dir / f"{alert.mint[:12]}-{int(now)}.png"
            photo_path.write_bytes(png)

        text = compose.caption(alert, verdict)
        delivered = False
        if self.cfg.deliver and self.cfg.gate_db is not None:
            try:
                delivered = enqueue_alert(
                    self.cfg.gate_db,
                    dedup_key=f"dregg-feed:{alert.mint}:{int(now)}",
                    caption=text,
                    photo_path=photo_path,
                )
            except sqlite3.Error as exc:
                self._error("enqueue", exc)
        else:
            preview = self.cfg.state_dir / "previews.log"
            with preview.open("a") as fh:
                fh.write(f"--- {datetime.fromtimestamp(now, UTC).isoformat()} "
                         f"chart={'yes' if png else 'no'}\n{text}\n")
        self.state.record_alert(alert.mint, now, alert.v5, alert.reason, delivered)
        self.alerts_this_cycle.append(
            {
                "mint": alert.mint,
                "symbol": alert.symbol,
                "reason": alert.reason,
                "v5": alert.v5,
                "verdict": verdict,
                "chart": png is not None,
                "delivered": delivered,
            }
        )

    # -- the cycle -------------------------------------------------------------------

    def cycle(self) -> dict[str, Any]:
        self.cycle_n += 1
        self._reload_config()
        self.alerts_this_cycle = []
        now = self.clock()
        day = utc_day(now)
        budget_idle = self.state.budget_spent(day) >= self.cfg.daily_budget

        if not budget_idle:
            self.state.budget_spend(day, 1)  # counted before the attempt, like the archive
            try:
                page: MoversPage | None = fetch_movers(
                    self._movers_transport, limit=self.cfg.board_limit
                )
            except Exception as exc:
                page = None
                self._error("movers_poll", exc)
            if page is not None:
                ranked = sorted(
                    (e for e in page.entries if e.v5 is not None),
                    key=lambda e: -(e.v5 or 0.0),
                )
                self.last_board = {
                    "entries": len(page.entries),
                    "server_ts": page.server_ts,
                    "top_v5": [
                        {"mint": e.mint, "symbol": e.symbol, "v5": e.v5} for e in ranked[:5]
                    ],
                }
                for alert in detect(self.state, page, now, self.cfg.thresholds):
                    try:
                        self._emit(alert, now, day)
                    except Exception as exc:  # one alert must not kill the batch
                        self._error(f"emit:{alert.mint[:8]}", exc)

        try:
            self.state.prune(now)
            self._prune_spool(now)
        except Exception as exc:
            self._error("prune", exc)
        return self._heartbeat(now, day, budget_idle)

    def _prune_spool(self, now: float) -> None:
        horizon = now - self.cfg.spool_keep_h * 3600.0
        for path in self.spool_dir.glob("*.png"):
            try:
                if path.stat().st_mtime < horizon:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    def _heartbeat(self, now: float, day: str, budget_idle: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "t": datetime.fromtimestamp(now, UTC).isoformat(),
            "cycle": self.cycle_n,
            "config_status": self.cfg_status,
            "deliver": self.cfg.deliver,
            "route": "board_movers (advanced-indexer.pump.fun/boards/movers)",
            "budget": {
                "day": day,
                "spent": self.state.budget_spent(day),
                "ceiling": self.cfg.daily_budget,
                "idle": budget_idle,
            },
            "board": self.last_board,
            "alerts_this_cycle": self.alerts_this_cycle,
            "alerts_last_24h": self.state.alerts_since(now - 86_400.0),
            "chart_last_error": self.renderer.last_error,
            "last_errors": self.last_errors,
        }
        path = self.cfg.state_dir / "heartbeat.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n")
        tmp.rename(path)
        return payload

    # -- the loop --------------------------------------------------------------------

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
                self._error("cycle", exc)
            elapsed = time.monotonic() - started
            deadline = time.monotonic() + max(self.cfg.poll_s - elapsed, 1.0)
            while not self._stopping and time.monotonic() < deadline:
                self.sleep(min(1.0, deadline - time.monotonic()))
        self.state.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="dregg_feed: movers awareness into the gated group")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--once", action="store_true", help="one cycle, print the heartbeat, exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    service = FeedService(args.config)
    if args.once:
        print(json.dumps(service.cycle(), indent=1))
        service.state.close()
        return
    service.run()


if __name__ == "__main__":
    main()
