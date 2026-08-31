"""Outcomes from OUR candles, anchored at the callout's own clock, priced in SOL.

The provider's `multiple` is stored on the callout row as THEIR claim — it is a
recomputed-at-read, tick-peak statistic (measured: pump recomputes it when you fetch, and
it marks the best price at any later moment, not a return anyone took). Nothing here
reads it. Every number in the `outcomes` table is computed from candle closes this
service fetched and retained, and the method is versioned (`v1`) so a better method later
is a new set of rows, not a silent rewrite of history.

METHOD v1 — what each field means and when it is allowed to exist
-----------------------------------------------------------------
* baseline: the last close at-or-before `t_event`; failing that (a callout on a coin's
  first candle), the first close within 15 minutes after. No baseline, no outcomes.
* ret_1h / ret_24h / ret_7d: close at-or-before `t_event + h` over baseline, minus one.
  Computed ONLY when some candle fetch happened at-or-after `t_event + h` — pump's
  candles exist only where trades happened, so "the series stops" means "trading
  stopped", and the last close carries forward; but a series whose FETCH predates the
  horizon has simply not seen it yet, and rendering that as a return would be inventing
  data. The finest interval that can answer, answers (5m before 1h); a ratio never mixes
  two intervals' buckets.
* max_close_multiple / max_drawdown: over closes in `[t_event, t_event + 7d]`, gated on a
  fetch at-or-after `t_event + 7d`. Drawdown starts its peak at the baseline. CLOSES,
  deliberately: the provider's peak statistic is tick-high; ours is the close series,
  which is the thing a study can actually mark against.
* dead_flag: no candle strictly after `t_event + 24h`, same +7d gate. NULL until the
  gate passes — "not yet knowable" is never rendered as "alive".

A row is complete exactly when `dead_flag` is non-NULL (the +7d gate passed); until then
the pass recomputes whenever a newer candle fetch for the mint exists.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Sequence

from .crawl import CANDLES_ROUTE
from .store import MS_DAY, MS_HOUR, Store

METHOD_VERSION = "v1"
BASELINE_GRACE_MS = 15 * 60_000
H1 = MS_HOUR
H24 = 24 * MS_HOUR
D7 = 7 * MS_DAY

_INTERVAL_S = {"1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}


@dataclass(frozen=True, slots=True)
class CandleSeries:
    """One interval's merged view: (ts_ms, close) sorted, plus when it was LAST fetched.

    `fetch_t_ms` is the coverage clock: a horizon is only judgeable if some fetch
    happened after it, because an absent tail before that is "not fetched yet", and an
    absent tail after it is "no trades" — different facts, only one of them a price.
    """

    interval_s: int
    fetch_t_ms: int
    points: tuple[tuple[int, float], ...]


@dataclass(frozen=True, slots=True)
class Outcome:
    ret_1h: float | None
    ret_24h: float | None
    ret_7d: float | None
    max_close_multiple: float | None
    max_drawdown: float | None
    dead_flag: bool | None

    @property
    def complete(self) -> bool:
        return self.dead_flag is not None


def _baseline(points: Sequence[tuple[int, float]], t_event_ms: int) -> float | None:
    before = [c for t, c in points if t <= t_event_ms]
    if before:
        return before[-1]
    after = [(t, c) for t, c in points if t_event_ms < t <= t_event_ms + BASELINE_GRACE_MS]
    return after[0][1] if after else None


def _close_at_or_before(points: Sequence[tuple[int, float]], t_ms: int) -> float | None:
    closes = [c for t, c in points if t <= t_ms]
    return closes[-1] if closes else None


def _ret(series: CandleSeries, t_event_ms: int, horizon_ms: int) -> float | None:
    if series.fetch_t_ms < t_event_ms + horizon_ms:
        return None
    base = _baseline(series.points, t_event_ms)
    close = _close_at_or_before(series.points, t_event_ms + horizon_ms)
    if base is None or close is None or base <= 0:
        return None
    return close / base - 1.0


def compute(t_event_ms: int, series: Sequence[CandleSeries]) -> Outcome:
    by_interval = sorted(series, key=lambda s: s.interval_s)

    def first_ret(horizon_ms: int) -> float | None:
        for s in by_interval:
            value = _ret(s, t_event_ms, horizon_ms)
            if value is not None:
                return value
        return None

    ret_1h = first_ret(H1)
    ret_24h = first_ret(H24)
    ret_7d = first_ret(D7)

    max_multiple: float | None = None
    drawdown: float | None = None
    dead: bool | None = None
    gated = [s for s in by_interval if s.fetch_t_ms >= t_event_ms + D7]
    if gated:
        # The coarsest gated series is the one sized to reach 7d; finer ones that
        # somehow also cover would work too, so take the one with the widest reach.
        s = max(gated, key=lambda s: s.points[-1][0] - s.points[0][0] if s.points else 0)
        base = _baseline(s.points, t_event_ms)
        window = [(t, c) for t, c in s.points if t_event_ms <= t <= t_event_ms + D7]
        if base is not None and base > 0 and window:
            max_multiple = max(c for _t, c in window) / base
            peak = base
            dd = 0.0
            for _t, close in window:
                peak = max(peak, close)
                dd = max(dd, (peak - close) / peak)
            drawdown = dd
        dead = not any(t > t_event_ms + H24 for t, _c in s.points)
    return Outcome(ret_1h, ret_24h, ret_7d, max_multiple, drawdown, dead)


# ---------------------------------------------------------------------------
# the store-facing pass
# ---------------------------------------------------------------------------


def _close_value(value: object) -> float | None:
    """swap-api serves OHLCV as DECIMAL STRINGS (measured 2026-08-29), not JSON numbers.

    `studies/imitation_signal.py` never noticed because `float(c["close"])` coerces both;
    a type-checking parser would have silently produced an empty series — the exact shape
    of bug the raw layer exists to make recoverable. Accept number or numeric string;
    anything else derives nothing.
    """

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


def _interval_from_url(url: str) -> int | None:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    raw = (query.get("interval") or [None])[0]
    return _INTERVAL_S.get(raw or "")


def load_series(store: Store, mint: str) -> list[CandleSeries]:
    """Rebuild the mint's candle series from retained bytes — the only source there is.

    Same-interval fetches merge by timestamp with the later fetch winning; different
    intervals stay separate series, because a 5m close and a 1h close at the same bucket
    stamp are closes of different spans and must never share a ratio.
    """

    rows = store.db.execute(
        "SELECT f.id, f.url, f.t_response_ms FROM fetches f"
        " JOIN fetch_windows w ON w.fetch_id = f.id"
        " WHERE w.route = ? AND w.scope = ? AND f.status = 200"
        " ORDER BY f.t_response_ms",
        (CANDLES_ROUTE, mint),
    ).fetchall()
    merged: dict[int, dict[int, float]] = {}
    fetch_t: dict[int, int] = {}
    for fetch_id, url, t_response_ms in rows:
        interval_s = _interval_from_url(url)
        if interval_s is None:
            continue
        try:
            body = json.loads(store.fetch_body(int(fetch_id)))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # retained garbage stays retained; it just derives nothing
        if not isinstance(body, list):
            continue
        points = merged.setdefault(interval_s, {})
        for candle in body:
            if not isinstance(candle, dict):
                continue
            ts = candle.get("timestamp")
            close = _close_value(candle.get("close"))
            if isinstance(ts, int) and not isinstance(ts, bool) and close is not None:
                points[ts] = close
        fetch_t[interval_s] = max(fetch_t.get(interval_s, 0), int(t_response_ms))
    return [
        CandleSeries(interval_s, fetch_t[interval_s], tuple(sorted(points.items())))
        for interval_s, points in merged.items()
    ]


def run_pass(store: Store, now_ms: int, *, max_per_cycle: int = 500) -> dict[str, int]:
    """(Re)compute outcomes for callouts whose candle evidence could have grown.

    A callout is a candidate when its first horizon has elapsed, candle windows exist for
    its mint, and either no outcome row exists or the row is incomplete with a candle
    fetch newer than its `computed_ms`.
    """

    rows = store.db.execute(
        """
        SELECT c.callout_id, c.mint, c.t_event_ms FROM callouts c
        WHERE c.t_event_ms IS NOT NULL
          AND c.t_event_ms + ? <= ?
          AND EXISTS (SELECT 1 FROM fetch_windows w JOIN fetches f ON f.id = w.fetch_id
                      WHERE w.route = ? AND w.scope = c.mint AND f.status = 200)
          AND NOT EXISTS (
            SELECT 1 FROM outcomes o
            WHERE o.callout_id = c.callout_id AND o.method_version = ?
              AND (o.dead_flag IS NOT NULL
                   OR NOT EXISTS (
                     SELECT 1 FROM fetch_windows w2 JOIN fetches f2 ON f2.id = w2.fetch_id
                     WHERE w2.route = ? AND w2.scope = c.mint AND f2.status = 200
                       AND f2.t_response_ms > o.computed_ms)))
        ORDER BY c.t_event_ms LIMIT ?
        """,
        (H1, now_ms, CANDLES_ROUTE, METHOD_VERSION, CANDLES_ROUTE, max_per_cycle),
    ).fetchall()
    cache: dict[str, list[CandleSeries]] = {}
    computed = complete = 0
    for callout_id, mint, t_event_ms in rows:
        if mint not in cache:
            cache[mint] = load_series(store, mint)
        outcome = compute(int(t_event_ms), cache[mint])
        store.upsert_outcome(
            callout_id=callout_id,
            ret_1h=outcome.ret_1h,
            ret_24h=outcome.ret_24h,
            ret_7d=outcome.ret_7d,
            max_close_multiple=outcome.max_close_multiple,
            max_drawdown=outcome.max_drawdown,
            dead_flag=outcome.dead_flag,
            computed_ms=now_ms,
        )
        computed += 1
        complete += int(outcome.complete)
    return {"computed": computed, "complete": complete}
