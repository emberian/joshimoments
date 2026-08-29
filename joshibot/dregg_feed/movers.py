"""The pump.fun movers board, polled — and the high-bar detector that turns it into
at most a handful of alerts an hour.

THE ROUTE WE SHIP: `board_movers` — GET https://advanced-indexer.pump.fun/boards/movers
(keyless, anonymous), exactly as the joshi map catalogued it (joshi
crates/joshi-pump-api/src/catalog.rs, measured 2026-08-24; probe re-confirmed live at
ship time). The catalogue's caveats are load-bearing here:

* It is a PERSONALISED recommendation board — POSITION IS NOT RANK, and two clients can
  be served different boards. This detector therefore never reads board position: the
  "top-5" trigger ranks entries by their own `v5` field, and the personalisation
  parameters (userId/session_id/country) are never sent.
* Rows use compact keys, and only some are decoded by pump's own shipped decoder
  (m/n/t = mint/name/symbol, mc = usd market cap, age = SECONDS since creation). The
  volume family (v5/v1h/v24h, vUsd*) and trade counts (tx5/txc) are INFERRED from their
  names, decoded by nothing in pump's app — which is why every number downstream is
  labeled "provider claims" and none of them is ever treated as a measured quantity.
* `limit` is honoured to 150 then silently clamps; a bare call returns 70.

FALLBACK if this route drifts: frontend-api-v3 `/coins` sorted by volume
(`discovery_coins` in the joshi map) can substitute — a config/route change here, with
the same detector on top. Not shipped: board_movers answered at ship time.

THE BAR. A coin alerts only when (with cooldown and a global cap on top):

* ACCEL — its 5m volume `v5` is at least `min_v5_sol` AND at least `accel_ratio` times
  the `v5` we observed for it on the previous poll (so a first sighting can never
  "accelerate": acceleration is measured against our own prior observation, persisted
  in sqlite so a restart does not forget it); or
* TOP5_ENTRY — it newly entered the top-5 of the board ranked by `v5` (it was observed
  outside that top-5 on the previous poll) with `v5 >= top5_min_v5_sol`. Requiring a
  prior observation means a service restart never alerts the whole standing top-5.

Per-coin cooldown (>= 2h), global cap (<= N/hour, DROP-LOWEST by v5), and both are
enforced from sqlite, so they hold across restarts.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from shitcoims_pumpsocial.client import BROWSER_UA, Response, Transport, _urllib_transport

MOVERS_ROUTE_NAME = "board_movers"  # the joshi map's name for what we poll
MOVERS_URL = "https://advanced-indexer.pump.fun/boards/movers"

_BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class MoversError(RuntimeError):
    """The board did not answer with a usable body. Carries no URL (nothing secret in
    one, but the habit from the gate holds: types and short facts, not payloads)."""


@dataclass(frozen=True, slots=True)
class Mover:
    """One board row, wire names kept for the undecoded fields (see module doc)."""

    mint: str
    name: str | None
    symbol: str | None
    v5: float | None        # provider claim: 5m volume, SOL (inferred from key name)
    v1h: float | None       # provider claim: 1h volume, SOL
    v24h: float | None      # provider claim: 24h volume, SOL
    v_usd5: float | None    # provider claim: 5m volume, USD
    tx5: int | None         # provider claim: trades in 5m
    mc_usd: float | None    # decoded by pump's app: usd_market_cap
    age_s: int | None       # decoded by pump's app: seconds since creation


@dataclass(frozen=True, slots=True)
class MoversPage:
    entries: tuple[Mover, ...]
    server_ts: int | None  # provider-stated availability instant, ms
    raw_rows: int


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def parse_movers(body: object) -> MoversPage:
    if not isinstance(body, dict) or not isinstance(body.get("entries"), list):
        raise MoversError("movers body is not the {entries: [...]} envelope")
    raw = body["entries"]
    entries: list[Mover] = []
    seen_mints: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        mint = row.get("m")
        if not isinstance(mint, str) or not _BASE58.match(mint):
            continue
        if mint in seen_mints:
            continue  # a duplicated board row must not become two tiles
        seen_mints.add(mint)
        age = _num(row.get("age"))
        tx5 = _num(row.get("tx5"))
        entries.append(
            Mover(
                mint=mint,
                name=str(row["n"]) if isinstance(row.get("n"), str) else None,
                symbol=str(row["t"]) if isinstance(row.get("t"), str) else None,
                v5=_num(row.get("v5")),
                v1h=_num(row.get("v1h")),
                v24h=_num(row.get("v24h")),
                v_usd5=_num(row.get("vUsd5")),
                tx5=int(tx5) if tx5 is not None else None,
                mc_usd=_num(row.get("mc")),
                age_s=int(age) if age is not None else None,
            )
        )
    server_ts = body.get("serverTs")
    if not isinstance(server_ts, int) or isinstance(server_ts, bool):
        server_ts = None
    return MoversPage(tuple(entries), server_ts, len(raw))


def fetch_movers(transport: Transport | None = None, *, limit: int = 100) -> MoversPage:
    """One keyless GET. `limit` is passed but the provider clamps at 150 silently."""

    send = transport or _urllib_transport
    url = MOVERS_URL + "?" + urllib.parse.urlencode({"limit": limit})
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    response: Response = send("GET", url, headers, None)
    status, _headers, raw = response
    if status != 200:
        raise MoversError(f"movers board answered HTTP {status}")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MoversError(f"movers body is not JSON ({type(exc).__name__})") from None
    return parse_movers(body)


# ---------------------------------------------------------------------------
# durable feed state
# ---------------------------------------------------------------------------


class FeedState:
    """One sqlite file: last-poll observations, alert history, request budget.

    WAL + busy timeout like every other dregg store. No flock: exactly one feed
    service runs per state dir, and nothing else writes here.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5.0)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                mint TEXT PRIMARY KEY,
                v5 REAL,
                seen_at REAL NOT NULL,
                in_top5 INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mint TEXT NOT NULL,
                alerted_at REAL NOT NULL,
                v5 REAL,
                reason TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS alerts_mint_t ON alerts (mint, alerted_at);
            CREATE TABLE IF NOT EXISTS budget (
                day TEXT PRIMARY KEY,
                spent INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        self.db.commit()

    # -- observations ---------------------------------------------------------

    def last_observation(self, mint: str) -> tuple[float | None, float, bool] | None:
        row = self.db.execute(
            "SELECT v5, seen_at, in_top5 FROM observations WHERE mint = ?", (mint,)
        ).fetchone()
        return (row[0], row[1], bool(row[2])) if row else None

    def record_observations(
        self, rows: list[tuple[str, float | None]], top5: set[str], now: float
    ) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO observations (mint, v5, seen_at, in_top5) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(mint) DO UPDATE SET v5 = excluded.v5, "
                "seen_at = excluded.seen_at, in_top5 = excluded.in_top5",
                [(m, v5, now, int(m in top5)) for m, v5 in rows],
            )

    # -- alerts ---------------------------------------------------------------

    def last_alert_at(self, mint: str) -> float | None:
        row = self.db.execute(
            "SELECT MAX(alerted_at) FROM alerts WHERE mint = ?", (mint,)
        ).fetchone()
        return row[0]

    def last_alert_at_any(self) -> float | None:
        """When the last alert batch went out. Every coin in a montage shares one
        `alerted_at`, so this IS the last-montage clock — durable across restarts."""

        row = self.db.execute("SELECT MAX(alerted_at) FROM alerts").fetchone()
        return row[0]

    def alerts_since(self, t: float) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) FROM alerts WHERE alerted_at >= ?", (t,)
        ).fetchone()
        return int(row[0])

    def record_alert(
        self, mint: str, now: float, v5: float | None, reason: str, delivered: bool
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO alerts (mint, alerted_at, v5, reason, delivered) "
                "VALUES (?, ?, ?, ?, ?)",
                (mint, now, v5, reason, int(delivered)),
            )

    # -- budget (every wire request the feed makes, board polls and candles) ---

    def budget_spent(self, day: str) -> int:
        row = self.db.execute("SELECT spent FROM budget WHERE day = ?", (day,)).fetchone()
        return int(row[0]) if row else 0

    def budget_spend(self, day: str, n: int = 1) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO budget (day, spent) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET spent = spent + excluded.spent",
                (day, n),
            )

    def prune(self, now: float, *, keep_observation_s: float = 86_400.0,
              keep_alert_s: float = 14 * 86_400.0) -> None:
        with self.db:
            self.db.execute(
                "DELETE FROM observations WHERE seen_at < ?", (now - keep_observation_s,)
            )
            self.db.execute("DELETE FROM alerts WHERE alerted_at < ?", (now - keep_alert_s,))

    def close(self) -> None:
        self.db.close()


# ---------------------------------------------------------------------------
# the detector
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_v5_sol: float = 250.0        # ACCEL floor: 5m volume, provider-claimed SOL
    accel_ratio: float = 1.6         # v5 must be >= this multiple of our prior observation
    top5_min_v5_sol: float = 400.0   # TOP5_ENTRY floor (higher: entry alone is weaker)
    cooldown_s: float = 7_200.0      # per-coin, >= 2h
    max_alerts_per_hour: int = 6     # global cap; over it, DROP-LOWEST by v5
    prev_max_age_s: float = 360.0    # a prior observation older than this proves nothing


@dataclass(frozen=True, slots=True)
class Alert:
    mint: str
    symbol: str
    name: str | None
    reason: str            # 'accel' | 'top5_entry'
    v5: float
    prev_v5: float | None
    v1h: float | None
    v24h: float | None
    v_usd5: float | None
    tx5: int | None
    mc_usd: float | None
    age_s: int | None
    server_ts: int | None


def detect(state: FeedState, page: MoversPage, now: float, th: Thresholds) -> list[Alert]:
    """Pure-ish: reads prior observations and alert history, WRITES this poll's
    observations, returns the alerts that clear the bar. Recording the alerts
    themselves is the caller's job, done alert-by-alert at delivery time."""

    ranked = sorted(
        (e for e in page.entries if e.v5 is not None), key=lambda e: -(e.v5 or 0.0)
    )
    top5 = {e.mint for e in ranked[:5]}

    candidates: list[Alert] = []
    for entry in ranked:
        v5 = entry.v5
        assert v5 is not None
        prev = state.last_observation(entry.mint)
        prev_fresh = prev is not None and prev[1] >= now - th.prev_max_age_s
        reason: str | None = None
        prev_v5: float | None = None
        if (
            prev_fresh
            and prev is not None
            and prev[0] is not None
            and prev[0] > 0
            and v5 >= th.min_v5_sol
            and v5 >= th.accel_ratio * prev[0]
        ):
            reason, prev_v5 = "accel", prev[0]
        elif (
            entry.mint in top5
            and prev_fresh
            and prev is not None
            and not prev[2]
            and v5 >= th.top5_min_v5_sol
        ):
            reason, prev_v5 = "top5_entry", prev[0]
        if reason is None:
            continue
        last = state.last_alert_at(entry.mint)
        if last is not None and last >= now - th.cooldown_s:
            continue
        candidates.append(
            Alert(
                mint=entry.mint,
                symbol=entry.symbol or "?",
                name=entry.name,
                reason=reason,
                v5=v5,
                prev_v5=prev_v5,
                v1h=entry.v1h,
                v24h=entry.v24h,
                v_usd5=entry.v_usd5,
                tx5=entry.tx5,
                mc_usd=entry.mc_usd,
                age_s=entry.age_s,
                server_ts=page.server_ts,
            )
        )

    # This poll becomes the next poll's baseline — written AFTER the comparisons above.
    state.record_observations([(e.mint, e.v5) for e in page.entries], top5, now)

    # Global cap, drop-lowest: candidates are already sorted by v5 descending.
    room = th.max_alerts_per_hour - state.alerts_since(now - 3_600.0)
    return candidates[: max(room, 0)]


def utc_day(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() if now is None else now))
