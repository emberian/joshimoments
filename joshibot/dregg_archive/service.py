"""The long-running loop: crawl, sweep, judge, compute, attest, report — every 10 minutes.

WHAT ONE CYCLE DOES, IN ORDER
-----------------------------
1. Re-read config. A broken edit keeps the LAST GOOD config and says so in the heartbeat
   — a typo in a TOML file must degrade to "yesterday's settings", never to a crash loop
   or a default nobody chose.
2. Walk the firehose back to `hwm - overlap` (raw retention + derivation in one pass).
3. Enqueue due work born from newly seen callouts: `callout_top` at T+25h and T+7d per
   (mint, day); candle fetches anchored to the callout's UTC DAY (see the deviation note
   on `_enqueue_sweeps`); caller-stats rotation.
4. Execute due work, throttled to >= 1 s between sweep requests ON TOP of the client's
   per-host pacing, inside the budget guard.
5. Deletion pass (offline — reads only our own tables), then enqueue confirmation probes
   for single-surface absences.
6. Outcomes pass (offline — decompresses retained candle bodies).
7. Manifests for completed days; heartbeat JSON, atomically.

BUDGET
------
Hard daily ceiling, spent counted at the transport (every attempt, retries included),
guarded before every logical request, stop recorded durably in sqlite. A restart on a
stopped day stays stopped; a new UTC day starts fresh. Offline passes (5-7) keep running
during a stop — the archive keeps thinking when it cannot ask.

429 storms on coin-communities are WEATHER, not errors: its budget is global across all
consumers and saturates at US prime time. A sweep item that hits the storm is deferred
with backoff and tried again next cycle; only repeated failure parks it with a note.
"""

from __future__ import annotations

import json
import signal
import time
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from shitcoims_pumpsocial.client import NotFound, PumpSocialClient, PumpSocialError, Transport

from . import deletion, manifest, outcomes
from .client import RecordingTransport
from .crawl import (
    CANDLES_ROUTE,
    LIST_ROUTE,
    TOP_ROUTE,
    WalkSummary,
    candle_window,
    derive_callout_rows,
    walk_firehose,
)
from .store import MS_DAY, MS_HOUR, BudgetExhausted, Store, day_start_ms, iso, utc_day

MS_MIN = 60_000


@dataclass(frozen=True, slots=True)
class Config:
    db_path: Path
    heartbeat_path: Path
    manifest_dir: Path
    cadence_s: int = 600
    overlap_min: int = 30
    initial_lookback_min: int = 60
    walk_limit: int = 50
    walk_max_pages: int = 30
    daily_budget: int = 2500
    sweep_gap_s: float = 1.0
    sweep_batch_max: int = 60
    caller_stats_per_day: int = 300
    caller_stats_per_cycle: int = 3
    active_caller_days: int = 7
    list_probes_per_cycle: int = 5
    deletion_horizon_h: int = 48
    # THE DARK-FIREHOSE FALLBACK (added after the 2026-08-29 drift measurement, when
    # /callout/recent went 400 platform-wide): while the firehose fails, each cycle
    # re-walks `callout_list/{mint}` for the archive's most recently active mints plus
    # any seeds below, deduped hourly per mint. This preserves continuity for coins the
    # archive already knows — it does NOT conjure a global feed, and a fresh archive
    # during an outage honestly collects nothing but the outage itself.
    fallback_list_mints: int = 10
    fallback_seed_mints: tuple[str, ...] = ()
    # Candle sweeps are DAY-anchored, so limits are sized to cover a whole UTC day of
    # callouts from one fetch. 5m x 600 = 50 h from a fetch at day_end+25h reaches back
    # to day_start-1h; 1h x 200 = 200 h from day_end+7d reaches back to day_start-8h.
    # The plan's per-callout numbers (310/180) cannot survive its own (mint, day) dedupe
    # — see _enqueue_sweeps.
    candles_25h_interval: str = "5m"
    candles_25h_limit: int = 600
    candles_7d_interval: str = "1h"
    candles_7d_limit: int = 200

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = tomllib.loads(path.read_text())
        base = path.resolve().parent

        def _path(section: dict[str, Any], key: str, default: str) -> Path:
            value = Path(str(section.get(key, default)))
            return value if value.is_absolute() else base / value

        paths = raw.get("paths", {})
        service = raw.get("service", {})
        candles = raw.get("candles", {})
        cfg = cls(
            db_path=_path(paths, "db", "state/dregg_archive/archive.sqlite"),
            heartbeat_path=_path(paths, "heartbeat", "state/dregg_archive/heartbeat.json"),
            manifest_dir=_path(paths, "manifests", "state/dregg_archive/manifests"),
        )
        for key, value in {**service, **candles}.items():
            if not hasattr(cfg, key):
                raise ValueError(f"unknown config key {key!r}")
            current = getattr(cfg, key)
            if isinstance(current, tuple):
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError(f"config key {key!r}: expected an array of strings")
                cfg = replace(cfg, **{key: tuple(value)})
            elif not isinstance(current, Path):
                if not isinstance(value, type(current)) and not (
                    isinstance(current, float) and isinstance(value, int)
                ):
                    raise ValueError(f"config key {key!r}: expected {type(current).__name__}")
                cfg = replace(cfg, **{key: type(current)(value)})
        for bound_key in ("cadence_s", "daily_budget", "walk_limit", "walk_max_pages"):
            if getattr(cfg, bound_key) <= 0:
                raise ValueError(f"config key {bound_key!r} must be positive")
        return cfg


class Service:
    def __init__(
        self,
        config_path: str | Path,
        *,
        transport: Transport | None = None,
        clock_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
        client_sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.cfg = Config.load(self.config_path)  # boot REQUIRES a valid config
        self.cfg_status = "ok"
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.sleep = sleep or time.sleep
        self.store = Store(self.cfg.db_path)
        self.recorder = RecordingTransport(transport, self.store, self.clock_ms)
        self.client = PumpSocialClient(transport=self.recorder, sleep=client_sleep or time.sleep)
        self.cycle_n = 0
        self.last_errors: list[str] = []
        self._last_sweep_monotonic: float | None = None
        self._walk_since: int | None = None
        self._stopping = False

    # -- config ------------------------------------------------------------------

    def _reload_config(self) -> None:
        """Keep-last-good: the running config only changes when the file parses whole."""

        try:
            fresh = Config.load(self.config_path)
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            status = f"kept_last_good: {exc}"
            if self.cfg_status != status:
                self.store.note(self.clock_ms(), "config_kept_last_good", str(exc)[:300])
            self.cfg_status = status
            return
        if fresh.db_path != self.cfg.db_path:
            # The store is already open; repointing it mid-flight would split the archive.
            self.cfg_status = "kept_last_good: db_path cannot change while running"
            return
        self.cfg = fresh
        self.cfg_status = "ok"

    # -- request plumbing ----------------------------------------------------------

    def _guard(self) -> None:
        self.store.budget_guard(self.clock_ms(), self.cfg.daily_budget)

    def _throttle_sweep(self) -> None:
        now = time.monotonic()
        if self._last_sweep_monotonic is not None:
            wait = self.cfg.sweep_gap_s - (now - self._last_sweep_monotonic)
            if wait > 0:
                self.sleep(wait)
        self._last_sweep_monotonic = time.monotonic()

    def _error(self, label: str, exc: Exception) -> None:
        line = f"{label}: {type(exc).__name__}: {exc}"[:300]
        self.last_errors = [*self.last_errors, line][-10:]
        self.store.note(self.clock_ms(), "error", line)

    # -- the walk ------------------------------------------------------------------

    def _walk(self) -> WalkSummary:
        now = self.clock_ms()
        hwm = self.store.hwm_ms()
        lookback = now - self.cfg.initial_lookback_min * MS_MIN
        since = hwm - self.cfg.overlap_min * MS_MIN if hwm else lookback
        summary = walk_firehose(
            self.client, self.recorder, self.store,
            since_ms=since, limit=self.cfg.walk_limit, max_pages=self.cfg.walk_max_pages,
            guard=self._guard,
        )
        if summary.newest_ms is not None and summary.newest_ms > (hwm or 0):
            self.store.set_hwm_ms(summary.newest_ms)
        if summary.failed:
            self.store.note(now, "walk_failed", summary.failed[:300])
        if summary.truncated and not summary.reached_since:
            # The gap is a fact with two bounds. Recorded, and the hwm still advances —
            # re-walking forever would not recover rows the feed no longer serves.
            self.store.note(
                now, "walk_gap",
                f"walk stopped ({summary.truncated}) at {summary.oldest_ms} before reaching"
                f" since={since}; rows in between were never witnessed",
            )
        self._walk_since = since
        return summary

    # -- sweep scheduling ----------------------------------------------------------

    def _enqueue_sweeps(self, new_callouts: list[tuple[str, str, str, int | None]]) -> int:
        """Queue the follow-up work a newly seen callout creates.

        DEVIATION FROM THE PLAN, deliberate: candle fetches are anchored to the callout's
        UTC DAY, not to `t_event + 25h`, because the plan's own (mint, day) dedupe makes
        per-callout anchoring unsound — the first callout of the day would claim the
        fetch and every later same-day callout on that mint would find candles that stop
        a full day short of its horizon. Day-anchoring with day-sized limits (see Config)
        covers EVERY callout of that (mint, day) from the same single fetch. The cost is
        latency, not correctness: an early-morning callout's 24 h numbers arrive up to a
        day later than the plan promised.
        """

        queued = 0
        for _callout_id, mint, _wallet, t_event_ms in new_callouts:
            if t_event_ms is None:
                self.store.note(self.clock_ms(), "sweep_skipped", f"{mint}: callout without createdAt")
                continue
            day = utc_day(t_event_ms)
            day_end = day_start_ms(day) + MS_DAY
            for kind, due in (
                ("top25h", t_event_ms + 25 * MS_HOUR),
                ("top7d", t_event_ms + 7 * MS_DAY),
                ("candles25h", day_end + 25 * MS_HOUR),
                ("candles7d", day_end + 7 * MS_DAY),
            ):
                queued += self.store.enqueue(kind=kind, key=mint, due_ms=due, dedupe=f"{kind}:{day}:{mint}")
        return queued

    def _enqueue_fallback_lists(self) -> int:
        """The dark-firehose lane: per-mint re-walks while /callout/recent fails.

        Two surfaces per mint, deduped hourly: `callout_list` (a deletion-surface window,
        measured razor-thin — usually empty) and `callout_top` (NOT a deletion surface,
        but measured to carry the real rows: full per-mint callout history with username
        and the new inline `user_uuid`). A day-long outage costs each active mint at most
        48 one-page fetches — bounded, inside the same budget.
        """

        now = self.clock_ms()
        day = utc_day(now)
        hour = int(now % MS_DAY) // MS_HOUR
        mints = list(self.cfg.fallback_seed_mints) + self.store.active_mints(
            since_ms=now - MS_DAY, limit=self.cfg.fallback_list_mints
        )
        queued = 0
        seen: set[str] = set()
        for mint in mints:
            if mint in seen:
                continue
            seen.add(mint)
            if len(seen) > self.cfg.fallback_list_mints:
                break
            queued += self.store.enqueue(
                kind="list_probe", key=mint, due_ms=now,
                dedupe=f"list_fb:{day}T{hour:02d}:{mint}",
            )
            queued += self.store.enqueue(
                kind="top_fb", key=mint, due_ms=now,
                dedupe=f"top_fb:{day}T{hour:02d}:{mint}",
            )
        return queued

    def _enqueue_caller_stats(self) -> int:
        now = self.clock_ms()
        day = utc_day(now)
        room = self.cfg.caller_stats_per_day - self.store.enqueued_today("caller_stats", day)
        take = min(self.cfg.caller_stats_per_cycle, max(room, 0))
        if take <= 0:
            return 0
        queued = 0
        wallets = self.store.callers_for_stats(
            active_since_ms=now - self.cfg.active_caller_days * MS_DAY, limit=take
        )
        for wallet in wallets:
            queued += self.store.enqueue(
                kind="caller_stats", key=wallet, due_ms=now, dedupe=f"caller_stats:{day}:{wallet}"
            )
        return queued

    def _enqueue_list_probes(self, mints: list[str]) -> int:
        now = self.clock_ms()
        queued = 0
        for mint in mints[: self.cfg.list_probes_per_cycle]:
            queued += self.store.enqueue(
                kind="list_probe", key=mint, due_ms=now, dedupe=deletion.probe_dedupe(mint, now)
            )
        return queued

    # -- sweep execution -----------------------------------------------------------

    def _run_due(self) -> dict[str, int]:
        stats = {"executed": 0, "deferred": 0, "parked": 0}
        items = self.store.due_items(self.clock_ms(), self.cfg.sweep_batch_max)
        for item_id, kind, key, attempts in items:
            try:
                self._guard()
            except BudgetExhausted:
                break
            self._throttle_sweep()
            try:
                self._execute_item(item_id, kind, key)
                stats["executed"] += 1
            except NotFound:
                # A measured 404 is an ANSWER; the fetch row already holds it. For the
                # stats rotation it also counts as fetched, or a wallet with no record
                # would eat a rotation slot every single day.
                if kind == "caller_stats":
                    self.store.mark_caller_stats_fetched(key, self.clock_ms())
                self.store.mark_done(
                    item_id, done_ms=self.clock_ms(),
                    fetch_id=self.recorder.last_fetch_id, note="404_absent",
                )
                stats["executed"] += 1
            except PumpSocialError as exc:
                if attempts >= 4:
                    self.store.mark_done(
                        item_id, done_ms=self.clock_ms(), fetch_id=None,
                        note=f"parked_after_{attempts + 1}_attempts: {exc}"[:200],
                    )
                    stats["parked"] += 1
                    self._error(f"due:{kind}:{key[:8]}", exc)
                else:
                    weather = exc.status == 429
                    backoff = (30 if weather else 60) * MS_MIN * (attempts + 1)
                    self.store.defer(
                        item_id, until_ms=self.clock_ms() + backoff,
                        note=f"{'429_weather' if weather else 'error'}: {exc}"[:200],
                    )
                    stats["deferred"] += 1
        return stats

    def _execute_item(self, item_id: int, kind: str, key: str) -> None:
        cfg = self.cfg
        derived = None
        if kind in ("top25h", "top7d", "top_fb"):
            self.recorder.route = TOP_ROUTE
            rows, _prov = self.client.top_callouts(key, limit=50)
            fetch_id = self.recorder.last_fetch_id
            assert fetch_id is not None
            derived = derive_callout_rows(
                self.store, fetch_id=fetch_id, route=TOP_ROUTE, rows=rows, scope=key,
                truncated=len(rows) >= 50,
            )
        elif kind == "list_probe":
            self.recorder.route = LIST_ROUTE
            rows, next_token, _prov = self.client.mint_callouts(key, limit=50)
            fetch_id = self.recorder.last_fetch_id
            assert fetch_id is not None
            derived = derive_callout_rows(
                self.store, fetch_id=fetch_id, route=LIST_ROUTE, rows=rows, scope=key,
                truncated=bool(next_token) or len(rows) >= 50,
            )
        elif kind in ("candles25h", "candles7d"):
            interval = cfg.candles_25h_interval if kind == "candles25h" else cfg.candles_7d_interval
            limit = cfg.candles_25h_limit if kind == "candles25h" else cfg.candles_7d_limit
            self.recorder.route = CANDLES_ROUTE
            data, _prov = self.client.request(
                "swap_candles", path_params={"mint": key},
                query={"interval": interval, "limit": limit, "currency": "SOL"},
            )
            fetch_id = self.recorder.last_fetch_id
            assert fetch_id is not None
            candles = data if isinstance(data, list) else []
            candle_window(self.store, fetch_id=fetch_id, mint=key, candles=candles)
        elif kind == "caller_stats":
            self.recorder.route = "wallet_callout_stats"
            self.client.wallet_callout_stats(key)
            self.store.mark_caller_stats_fetched(key, self.clock_ms())
        else:
            self.store.mark_done(item_id, done_ms=self.clock_ms(), fetch_id=None,
                                 note=f"unknown_kind:{kind}")
            return
        self.store.mark_done(item_id, done_ms=self.clock_ms(), fetch_id=self.recorder.last_fetch_id)
        # A sweep fetch can be the FIRST sighting of a callout (measured reality while
        # the firehose is dark: `callout_top` is the only surface serving rows). Those
        # callouts need their own follow-up sweeps or they never get candles/outcomes;
        # newly enqueued past-due items run next cycle, so this cannot loop.
        if derived is not None and derived.new_callouts:
            self._enqueue_sweeps(derived.new_callouts)

    # -- the cycle -----------------------------------------------------------------

    def cycle(self) -> dict[str, Any]:
        self.cycle_n += 1
        self._reload_config()
        now = self.clock_ms()
        day = utc_day(now)
        spent, stopped = self.store.budget(day)
        walk: WalkSummary | None = None
        budget_idle = False
        self._walk_since = None

        if spent >= self.cfg.daily_budget:
            budget_idle = True
            if not stopped:
                self.store.budget_stop(day)
                self.store.note(now, "budget_stop",
                                f"day {day}: {spent} requests >= ceiling {self.cfg.daily_budget}")
        else:
            try:
                walk = self._walk()
                self._enqueue_sweeps(walk.new_callouts)
                self._enqueue_caller_stats()
                if walk.failed:
                    self._enqueue_fallback_lists()
            except BudgetExhausted:
                budget_idle = True
            except Exception as exc:  # the loop must outlive any one cycle
                self._error("walk", exc)

        sweep_stats = {"executed": 0, "deferred": 0, "parked": 0}
        if not budget_idle:
            try:
                sweep_stats = self._run_due()
            except BudgetExhausted:
                budget_idle = True
            except Exception as exc:  # same: record, keep going
                self._error("sweeps", exc)

        # Offline lanes: these read only our own tables and bytes, so a budget stop
        # never idles them — the archive keeps judging while it cannot ask.
        deletion_summary = None
        try:
            deletion_summary = deletion.run_pass(
                self.store, self.clock_ms(), horizon_ms=self.cfg.deletion_horizon_h * MS_HOUR
            )
            self._enqueue_list_probes(deletion_summary.confirm_mints)
        except Exception as exc:  # same: record, keep going
            self._error("deletion", exc)

        outcome_stats = {"computed": 0, "complete": 0}
        try:
            outcome_stats = outcomes.run_pass(self.store, self.clock_ms())
        except Exception as exc:  # same: record, keep going
            self._error("outcomes", exc)

        try:
            manifest.write_pending(self.store, self.cfg.manifest_dir, today=day)
        except Exception as exc:  # same: record, keep going
            self._error("manifest", exc)

        heartbeat = self._heartbeat(day, walk, budget_idle, sweep_stats, deletion_summary, outcome_stats)
        return heartbeat

    def _heartbeat(
        self,
        day: str,
        walk: WalkSummary | None,
        budget_idle: bool,
        sweep_stats: dict[str, int],
        deletion_summary: Any,
        outcome_stats: dict[str, int],
    ) -> dict[str, Any]:
        now = self.clock_ms()
        spent, stopped = self.store.budget(day)
        hwm = self.store.hwm_ms()
        payload: dict[str, Any] = {
            "t": iso(now),
            "t_ms": now,
            "cycle": self.cycle_n,
            "config_status": self.cfg_status,
            "hwm_ms": hwm,
            "hwm": iso(hwm) if hwm else None,
            "walk_since_ms": self._walk_since,
            "budget": {
                "day": day, "spent": spent, "ceiling": self.cfg.daily_budget,
                "stopped": stopped or budget_idle,
                "note": "idle: daily ceiling reached; offline lanes still running"
                        if (stopped or budget_idle) else None,
            },
            "walk": None if walk is None else {
                "pages": walk.pages, "rows": walk.rows, "sightings": walk.sightings,
                "new_callouts": len(walk.new_callouts), "quarantined": walk.quarantined,
                "reached_since": walk.reached_since, "truncated": walk.truncated,
                "failed": walk.failed,
            },
            "sweeps": sweep_stats,
            "deletion": None if deletion_summary is None else {
                "evaluated": deletion_summary.evaluated, "removed": deletion_summary.removed,
                "unknown_absent": deletion_summary.unknown_absent,
                "cleared": deletion_summary.cleared,
                "confirm_mints": len(deletion_summary.confirm_mints),
            },
            "outcomes": outcome_stats,
            "counts": self.store.counts(),
            "client": self.client.stats.line(),
            "last_errors": self.last_errors,
        }
        self.cfg.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cfg.heartbeat_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n")
        tmp.rename(self.cfg.heartbeat_path)
        return payload

    # -- the loop ------------------------------------------------------------------

    def run(self) -> None:
        def _stop(_signum: int, _frame: Any) -> None:
            self._stopping = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        while not self._stopping:
            started = time.monotonic()
            self.cycle()
            if self._stopping:
                break
            elapsed = time.monotonic() - started
            remaining = max(self.cfg.cadence_s - elapsed, 1.0)
            # Sleep in short slices so a SIGTERM lands within a second, not a cadence.
            deadline = time.monotonic() + remaining
            while not self._stopping and time.monotonic() < deadline:
                self.sleep(min(1.0, deadline - time.monotonic()))
