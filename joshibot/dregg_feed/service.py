"""The feed loop: poll movers ~75s, detect, emit ONE MONTAGE, enqueue into the GATE.

DISPATCH IS A MONTAGE (2026-08-29 densification): qualifying movers in a cycle go out
as ONE image — up to `montage_max` (6) mini charts in a grid — with one plain-text
caption listing every coin's link, 5m volume and birth verdict. When more than six
qualify, the top six by v5 ship and the rest are NOT marked alerted (drop-lowest:
they can make the next montage if they still qualify then). The per-coin 2h cooldown
is unchanged — a montage appearance consumes it. The global cap is now a MONTAGE
WINDOW: at most one montage per `montage_window_min` (default 12), enforced from the
alerts table's own clock so it survives restarts; a cycle inside the window records
nothing, so held coins stay eligible.

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
daily ceiling (default 1,200). At 75s cadence the board alone is ~1,152/day; candle
fetches ride in the remainder (≤ montage_max per montage, half-hour cached, and the
montage window bounds montages to ≤ 60/window_min per hour). When the ceiling is hit
the loop idles until the next UTC day, visibly in the heartbeat; a montage whose
candle budget runs out mid-batch ships with the panels it got (text lines for the
rest), never nothing.

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
import math
import signal
import sqlite3
import time
import tomllib
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from shitcoims_pumpsocial.client import PumpSocialClient, Transport

from . import compose
from .charts import (
    ChartRenderer,
    MontagePanel,
    choose_candle_query,
    panel_from_candles,
    render_montage,
)
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
    # LEGACY, accepted-but-inert since the montage densification: the deployed config
    # names it, and refusing it at boot would crash-loop the restart. The montage
    # window below is what actually rate-limits the group now.
    max_alerts_per_hour: int = 6
    montage_max: int = 6              # coins per montage image (drop-lowest beyond)
    montage_window_min: float = 12.0  # at most one montage per this many minutes
    prev_max_age_s: float = 360.0
    chart_interval: str = "5m"
    chart_limit: int = 72             # 72 x 5m = 6h window
    spool_keep_h: float = 48.0
    verdict_days: int = 2

    @property
    def thresholds(self) -> Thresholds:
        # The detector's hourly clamp is a SAFETY VALVE derived from the montage
        # settings (full montages at the window rate, plus one window of headroom) —
        # never the legacy max_alerts_per_hour, which would strangle montages at 6
        # coin-rows/hour. The montage window in cycle() is the real cap.
        per_hour = self.montage_max * (math.ceil(60.0 / self.montage_window_min) + 1)
        return Thresholds(
            min_v5_sol=self.min_v5_sol,
            accel_ratio=self.accel_ratio,
            top5_min_v5_sol=self.top5_min_v5_sol,
            cooldown_s=self.cooldown_h * 3600.0,
            max_alerts_per_hour=per_hour,
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
        if not 1 <= cfg.montage_max <= 6:
            raise ValueError("montage_max must be 1..6 (the grid and the caption cap)")
        if cfg.montage_window_min < 1.0:
            raise ValueError("montage_window_min below 1 minute is a firehose, not a feed")
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
            }
        else:
            method = "sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": caption,
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
        self.last_montage: dict[str, Any] | None = None
        self.montage_hold: str | None = None
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

    # -- one montage out -------------------------------------------------------------

    @staticmethod
    def _display_labels(alerts: list[Alert]) -> dict[str, str]:
        """mint -> tile/caption name. Symbols legitimately collide on pump (ticker
        waves); a colliding one gets a short mint suffix so two "$Pepsi" tiles stay
        tellable apart. The SAME mapping titles the tiles and the caption lines."""

        flat = {a.mint: ("".join((a.symbol or "?").split()) or "?")[:12] for a in alerts}
        counts = Counter(flat.values())
        return {
            mint: (name if counts[name] == 1 else f"{name}·{mint[:4]}")
            for mint, name in flat.items()
        }

    def _emit_montage(self, alerts: list[Alert], now: float, day: str) -> None:
        """One image, one caption, for the whole batch. Coins WITH candles come first
        (their caption lines mirror the tiles in reading order); coins whose candles
        were unavailable trail as caption-only lines. Every coin in the batch consumes
        its cooldown at the same `now` — that shared stamp is the montage clock."""

        labels = self._display_labels(alerts)
        with_chart: list[tuple[Alert, str | None]] = []
        without_chart: list[tuple[Alert, str | None]] = []
        panels: list[MontagePanel] = []
        for alert in alerts:
            verdict = None
            if self.verdicts is not None:
                try:
                    verdict = self.verdicts.verdict(alert.mint, now)
                except Exception as exc:  # a broken scores file must not kill the batch
                    self._error("verdict", exc)
            # A minutes-old mover has no 5m history worth drawing: pick the interval
            # from the coin's (provider-claimed) age so the tile has shape.
            interval, limit = choose_candle_query(
                alert.age_s,
                default_interval=self.cfg.chart_interval,
                default_limit=self.cfg.chart_limit,
            )
            candles = None
            if self.state.budget_spent(day) < self.cfg.daily_budget:
                before = self.client.stats.requests
                candles = self.renderer.candles_cached(
                    alert.mint, now, interval=interval, limit=limit
                )
                spent = self.client.stats.requests - before
                if spent:
                    self.state.budget_spend(day, spent)
            if candles:
                panels.append(
                    panel_from_candles(
                        alert.mint, labels[alert.mint], candles,
                        interval=interval,
                        now_ms=int(now * 1000),  # so a frozen series is marked stale
                        limit=limit,             # clip the DRAWN window to the query's span
                        young=alert.age_s is not None and alert.age_s < 45 * 60,
                    )
                )
                with_chart.append((alert, verdict))
            else:
                without_chart.append((alert, verdict))

        ordered = with_chart + without_chart
        photo_path: Path | None = None
        if panels:
            try:
                png = render_montage(panels)
                photo_path = self.spool_dir / f"montage-{int(now)}.png"
                photo_path.write_bytes(png)
            except (ValueError, OSError) as exc:
                # A render failure downgrades to a text-only alert, never silence.
                self._error("montage_render", exc)
                photo_path = None
        text = compose.montage_caption(ordered, labels=labels)

        delivered = False
        if self.cfg.deliver and self.cfg.gate_db is not None:
            try:
                delivered = enqueue_alert(
                    self.cfg.gate_db,
                    dedup_key=f"dregg-feed:montage:{int(now)}",
                    caption=text,
                    photo_path=photo_path,
                )
            except sqlite3.Error as exc:
                self._error("enqueue", exc)
        else:
            preview = self.cfg.state_dir / "previews.log"
            with preview.open("a") as fh:
                fh.write(f"--- {datetime.fromtimestamp(now, UTC).isoformat()} "
                         f"panels={len(panels)}/{len(alerts)}\n{text}\n")
        for alert, verdict in ordered:
            self.state.record_alert(alert.mint, now, alert.v5, alert.reason, delivered)
            self.alerts_this_cycle.append(
                {
                    "mint": alert.mint,
                    "symbol": alert.symbol,
                    "reason": alert.reason,
                    "v5": alert.v5,
                    "verdict": verdict,
                    "chart": any(p.mint == alert.mint for p in panels),
                    "delivered": delivered,
                }
            )
        self.last_montage = {
            "t": datetime.fromtimestamp(now, UTC).isoformat(),
            "coins": len(ordered),
            "panels": len(panels),
            "delivered": delivered,
        }

    # -- the cycle -------------------------------------------------------------------

    def cycle(self) -> dict[str, Any]:
        self.cycle_n += 1
        self._reload_config()
        self.alerts_this_cycle = []
        self.montage_hold = None
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
                candidates = detect(self.state, page, now, self.cfg.thresholds)
                if candidates:
                    last = self.state.last_alert_at_any()
                    window_s = self.cfg.montage_window_min * 60.0
                    if last is not None and now - last < window_s:
                        # Inside the montage window: hold, record nothing — held
                        # coins stay eligible for the next montage if they still
                        # qualify (their cooldowns were never consumed).
                        self.montage_hold = (
                            f"{len(candidates)} qualifier(s) held; last montage "
                            f"{now - last:.0f}s ago < {window_s:.0f}s window"
                        )
                    else:
                        self.montage_hold = None
                        try:
                            self._emit_montage(candidates[: self.cfg.montage_max], now, day)
                        except Exception as exc:  # one montage must not kill the loop
                            self._error("emit_montage", exc)

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
            "last_montage": self.last_montage,
            "montage_hold": self.montage_hold,
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
