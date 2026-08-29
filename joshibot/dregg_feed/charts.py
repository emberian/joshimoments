"""Compact price-chart PNGs from swap-api candles, deterministic given the candles.

ROUTE AND PARSING ARE REUSED, NOT RE-DERIVED. The candles come through
`shitcoims_pumpsocial`'s catalogued `swap_candles` endpoint with the exact query the
archive's sweeps use (`interval`/`limit`/`currency=SOL`), and the value parser is
`dregg_archive.outcomes._close_value` — the measured decimal-string-tolerant coercion
(swap-api serves OHLCV as DECIMAL STRINGS, measured 2026-08-29; a type-checking parser
silently produces an empty series). A candle exists only where trades happened, so the
series ends at the last trade, not at "now" — an empty tail is data, not a gap.

RENDERING is matplotlib on Agg, pyplot-free (no global state), with the PNG `Software`
metadata pinned so the bytes are a pure function of (candles, symbol, window label).
Design follows the dataviz rules that survive shrinking to a Telegram photo: one axis
per panel (price and volume are two stacked panels, never a dual axis), thin recessive
marks, text in ink tokens rather than the series color, direction restated in text so
color is never the only carrier, and a single direct label (the last close) instead of
a number on every point.

BOUNDED: `ChartRenderer` makes at most one candles request per render, and a small LRU
keyed by (mint, half-hour) means repeated renders inside the window cost nothing.
"""

from __future__ import annotations

import io
import itertools
import logging
from collections import OrderedDict
from typing import NamedTuple

import matplotlib

matplotlib.use("Agg")

from matplotlib import ticker
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from dregg_archive.outcomes import _close_value  # the measured decimal-string parser
from shitcoims_pumpsocial.client import PumpSocialClient, PumpSocialError

log = logging.getLogger(__name__)

INTERVAL_S = {"1m": 60, "5m": 300, "1h": 3600}

# Dark surface + ink tokens. The price line's hue carries window direction (up/down),
# which the header also states as a signed percentage — never color alone.
SURFACE = "#10141b"
INK = "#e6e9ee"
INK_MUTED = "#8b94a1"
GRID = "#232a35"
PRICE_UP = "#4ade80"
PRICE_DOWN = "#f87171"
PRICE_FLAT = "#8fa3b8"
VOLUME = "#3d4757"


class Candle(NamedTuple):
    ts_ms: int
    close: float
    volume: float


def parse_candles(body: object) -> list[Candle]:
    """swap-api body -> sorted (ts, close, volume). Tolerates decimal strings; a row
    that derives nothing is dropped, not guessed at."""

    if not isinstance(body, list):
        return []
    out: list[Candle] = []
    for row in body:
        if not isinstance(row, dict):
            continue
        ts = row.get("timestamp")
        close = _close_value(row.get("close"))
        volume = _close_value(row.get("volume"))
        if isinstance(ts, int) and not isinstance(ts, bool) and ts > 0 and close is not None:
            out.append(Candle(ts, close, volume if volume is not None else 0.0))
    out.sort(key=lambda c: c.ts_ms)
    return out


def fetch_candles(
    client: PumpSocialClient, mint: str, *, interval: str = "5m", limit: int = 72
) -> list[Candle]:
    """One catalogued `swap_candles` request, priced in SOL like everything we study."""

    data, _prov = client.request(
        "swap_candles",
        path_params={"mint": mint},
        query={"interval": interval, "limit": limit, "currency": "SOL"},
    )
    return parse_candles(data)


def _fmt_price(value: float) -> str:
    return f"{value:.3g}"


def render_chart(candles: list[Candle], symbol: str, window_label: str) -> bytes:
    """PNG bytes, a pure function of its arguments (no clocks, pinned metadata)."""

    if not candles:
        raise ValueError("no candles to render")
    last_ms = candles[-1].ts_ms
    xs = [(c.ts_ms - last_ms) / 3_600_000 for c in candles]  # hours before last trade
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    change = closes[-1] / closes[0] - 1.0 if closes[0] > 0 else 0.0
    line = PRICE_UP if change > 0 else PRICE_DOWN if change < 0 else PRICE_FLAT

    fig = Figure(figsize=(8.0, 4.5), dpi=100, facecolor=SURFACE)
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(
        2, 1, height_ratios=[3.1, 1.0], hspace=0.10,
        left=0.075, right=0.90, top=0.855, bottom=0.115,
    )
    ax_price = fig.add_subplot(grid[0])
    ax_volume = fig.add_subplot(grid[1], sharex=ax_price)

    for ax in (ax_price, ax_volume):
        ax.set_facecolor(SURFACE)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(colors=INK_MUTED, labelsize=7.5, length=0)

    ax_price.plot(xs, closes, color=line, linewidth=1.8, solid_capstyle="round")
    ax_price.fill_between(xs, closes, min(closes), color=line, alpha=0.10, linewidth=0)
    ax_price.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.8)
    ax_price.margins(x=0.01, y=0.08)
    ax_price.tick_params(labelbottom=False)
    ax_price.yaxis.tick_right()
    ax_price.yaxis.set_major_formatter(lambda v, _pos: _fmt_price(v))
    ax_price.yaxis.set_major_locator(ticker.MaxNLocator(4))
    ax_price.annotate(
        _fmt_price(closes[-1]), (xs[-1], closes[-1]), xytext=(6, 0),
        textcoords="offset points", ha="left", va="center", color=INK, fontsize=8,
    )

    if len(xs) > 1:
        gaps = sorted(b - a for a, b in itertools.pairwise(xs))
        width = 0.8 * gaps[len(gaps) // 2]
    else:
        width = 0.05
    ax_volume.bar(xs, volumes, width=width, color=VOLUME, linewidth=0)
    ax_volume.set_yticks([])
    ax_volume.margins(x=0.01)
    ax_volume.xaxis.set_major_locator(ticker.MaxNLocator(5))
    # Young coins have minutes of history, not hours; hour-granular ticks would all
    # render "-0h". Pick the unit from the actual span.
    span_h = xs[-1] - xs[0]
    if span_h >= 1.5:
        fmt = lambda v, _pos: "last trade" if v == 0 else f"{v:+.0f}h"  # noqa: E731
    else:
        fmt = lambda v, _pos: "last trade" if v == 0 else f"{v * 60:+.0f}m"  # noqa: E731
    ax_volume.xaxis.set_major_formatter(fmt)
    if max(volumes, default=0) > 0:
        ax_volume.annotate(
            "vol " + _fmt_price(max(volumes)), (0.0, 1.0), xycoords="axes fraction",
            xytext=(2, -2), textcoords="offset points", ha="left", va="top",
            color=INK_MUTED, fontsize=7,
        )

    fig.text(0.075, 0.925, f"${symbol}", color=INK, fontsize=13, fontweight="bold")
    fig.text(
        0.90, 0.930, f"{window_label} · {change:+.1%}",
        color=INK_MUTED, fontsize=9, ha="right",
    )
    fig.text(
        0.5, 0.018, "source: pump.fun swap-api candles (SOL) · awareness, not advice",
        color=INK_MUTED, fontsize=7.5, ha="center",
    )

    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", facecolor=SURFACE,
        metadata={"Software": "dregg_feed.charts v1"},  # pinned: bytes stay deterministic
    )
    return buf.getvalue()


class ChartRenderer:
    """One candles request per render, half-hour LRU per mint, errors degrade to None."""

    def __init__(self, client: PumpSocialClient, *, cache_max: int = 64):
        self.client = client
        self.cache_max = cache_max
        self._cache: OrderedDict[tuple[str, int], bytes | None] = OrderedDict()
        self.last_error: str | None = None

    def render(
        self, mint: str, symbol: str, now: float, *, interval: str = "5m", limit: int = 72
    ) -> bytes | None:
        key = (mint, int(now // 1800))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        png: bytes | None = None
        try:
            candles = fetch_candles(self.client, mint, interval=interval, limit=limit)
            if candles:
                # Label the span the candles ACTUALLY cover — a minutes-old coin gets
                # "last 15m", never a claimed 6h it has not lived.
                seconds = INTERVAL_S.get(interval, 300)
                span_h = (candles[-1].ts_ms - candles[0].ts_ms) / 3_600_000 + seconds / 3600
                label = (
                    f"last {span_h * 60:.0f}m · {interval} closes"
                    if span_h < 1.0
                    else f"last {span_h:.1f}h · {interval} closes"
                )
                png = render_chart(candles, symbol, label)
            else:
                self.last_error = f"{mint[:8]}: no candles (no trades in window)"
        except (PumpSocialError, ValueError) as exc:
            # A failed fetch is cached as None for the half-hour: bounded, and a
            # chartless alert still goes out as text.
            self.last_error = f"{mint[:8]}: {type(exc).__name__}"
            log.warning("chart render failed for %s (%s)", mint[:8], type(exc).__name__)
        self._cache[key] = png
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return png
