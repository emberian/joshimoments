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

BOUNDED: `ChartRenderer` makes at most one candles request per coin, and its LRU —
keyed (mint, half-hour), holding PARSED CANDLES rather than pixels — is shared by the
single chart and `render_montage`, so a coin appearing in successive montages inside
the window costs no refetch.

THE MONTAGE (2026-08-29 densification, momentum grammar in v2): `render_montage`
packs up to six mini charts into one PNG — 3x2 for 5-6 panels (five centers its short
row), 2x2 for four, one row for fewer; never a blank tile. Each tile is built to read
PRESENT momentum at thumbnail size — see `_draw_panel` for the grammar (recency
weight, the prior-window volume ghost, the live-edge dot with stale marking, the
direction-tinted background). Reading order (left-right, top-bottom) is the caption's
line order. Deterministic bytes: the render clock enters only as `MontagePanel.stale_s`
DATA, so the image stays a pure function of its panels.
"""

from __future__ import annotations

import io
import itertools
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple

import matplotlib

matplotlib.use("Agg")

from matplotlib import ticker
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
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
#: Momentum-panel tokens: faint direction washes for the tile background (the 2x3
#: grid reads as a heat mosaic), a bright neutral for the CURRENT 5m volume bar
#: (volume has no direction; brightness marks "now"), and amber for the stale tag
#: (always paired with the word "stale" — never color alone).
TINT_UP = "#12241c"
TINT_DOWN = "#241719"
VOLUME_NOW = "#8fa3b8"
AMBER = "#d9a44a"

#: How many trailing bars count as "now" (3 x 5m = the last quarter hour).
RECENT_BARS = 3
#: A hole in the series bigger than this many intervals is drawn as a hole.
GAP_FACTOR = 1.6


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


#: Below this many candles a tile draws dots + "new — N bars" instead of a line:
#: a straight diagonal between two points reads as a rendering bug and says nothing
#: about momentum.
SPARSE_BARS = 5


def choose_candle_query(
    age_s: int | None, *, default_interval: str = "5m", default_limit: int = 72
) -> tuple[str, int]:
    """Pick (interval, limit) from the coin's age so the tile has SHAPE.

    A minutes-old mover has only 2-3 five-minute bars — honest, but a two-point
    diagonal destroys the momentum read. Target >= ~20 bars where the coin's life
    allows (soft goal: a 3-minute-old coin genuinely has 3 bars):

    * age < 45m  -> 1m bars covering the whole life (limit 60)
    * otherwise  -> the default window (5m x 72 = the last 6h), which also serves
      age-unknown, since the provider returns only the bars that exist anyway.
    """

    if age_s is not None and 0 <= age_s < 45 * 60:
        return "1m", 60
    return default_interval, default_limit


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


def _span_label(candles: list[Candle], interval: str) -> str:
    """Label the span the candles ACTUALLY cover — a minutes-old coin gets
    "last 15m", never a claimed 6h it has not lived."""

    seconds = INTERVAL_S.get(interval, 300)
    span_h = (candles[-1].ts_ms - candles[0].ts_ms) / 3_600_000 + seconds / 3600
    if span_h < 1.0:
        return f"last {span_h * 60:.0f}m · {interval} closes"
    return f"last {span_h:.1f}h · {interval} closes"


class ChartRenderer:
    """One candles request per coin per half-hour: the LRU caches PARSED CANDLES (not
    pixels), so the single chart and the montage share fetches; errors degrade to None."""

    def __init__(self, client: PumpSocialClient, *, cache_max: int = 64):
        self.client = client
        self.cache_max = cache_max
        self._cache: OrderedDict[tuple[str, str, int, int], list[Candle] | None] = OrderedDict()
        self.last_error: str | None = None

    def candles_cached(
        self, mint: str, now: float, *, interval: str = "5m", limit: int = 72
    ) -> list[Candle] | None:
        """The mint's candles, fetched at most once per (mint, query, half-hour) —
        the query is in the key because the age-adaptive chooser can ask for the same
        mint at 1m early in its life and 5m later. None means "no trades" or a failed
        fetch — both cached so retries stay bounded."""

        key = (mint, interval, limit, int(now // 1800))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        candles: list[Candle] | None = None
        try:
            fetched = fetch_candles(self.client, mint, interval=interval, limit=limit)
            if fetched:
                candles = fetched
            else:
                self.last_error = f"{mint[:8]}: no candles (no trades in window)"
        except (PumpSocialError, ValueError) as exc:
            self.last_error = f"{mint[:8]}: {type(exc).__name__}"
            log.warning("candle fetch failed for %s (%s)", mint[:8], type(exc).__name__)
        self._cache[key] = candles
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return candles

    def render(
        self, mint: str, symbol: str, now: float, *, interval: str = "5m", limit: int = 72
    ) -> bytes | None:
        candles = self.candles_cached(mint, now, interval=interval, limit=limit)
        if not candles:
            return None
        return render_chart(candles, symbol, _span_label(candles, interval))


# ---------------------------------------------------------------------------
# the montage: up to six movers in one image
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MontagePanel:
    """One montage tile. `move` is the close-over-close move across `move_span_s`
    seconds — as close to 5 minutes as the series allows (computed from OUR candles;
    the board has no price-change field) — so 1m-interval newborn tiles stay
    comparable with 5m ones, and the title's "/Nm" tag states the span actually
    measured. `stale_s` is how far the newest bar's END trails the render clock —
    carried as DATA so the rendering stays a pure function of the panel (the
    determinism contract), while a frozen series can still be marked frozen."""

    mint: str
    symbol: str
    candles: tuple[Candle, ...]
    move: float | None
    move_span_s: float | None
    interval: str = "5m"
    stale_s: float | None = None
    #: Drives the sparse-tile wording: a YOUNG coin with 4 bars is "new — 4 bars";
    #: an old coin whose visible window holds 4 bars is "thin tape — 4 bars".
    young: bool = True


def panel_from_candles(
    mint: str, symbol: str, candles: list[Candle], *, interval: str = "5m",
    now_ms: int | None = None, limit: int | None = None, young: bool = True,
) -> MontagePanel:
    if limit is not None and candles:
        # Candles exist only where trades happened, so `limit` bars can span DAYS on
        # a sparsely-traded revived coin — and a time-proportional x-axis would then
        # crush "now" into a sliver. Clip the DRAWN window to the span the query was
        # sized for (limit x interval); the span label stays truthful to what shows.
        window_ms = limit * INTERVAL_S.get(interval, 300) * 1000
        candles = [c for c in candles if c.ts_ms >= candles[-1].ts_ms - window_ms]
    move = span_s = None
    if len(candles) >= 2:
        target = candles[-1].ts_ms - 300_000  # aim the baseline ~5 minutes back
        base = candles[0]
        for c in candles[:-1]:
            if c.ts_ms <= target:
                base = c
        if base.close > 0 and base.ts_ms < candles[-1].ts_ms:
            move = candles[-1].close / base.close - 1.0
            span_s = (candles[-1].ts_ms - base.ts_ms) / 1000.0
    stale = None
    if now_ms is not None and candles:
        bucket_end = candles[-1].ts_ms + INTERVAL_S.get(interval, 300) * 1000
        stale = max(0.0, (now_ms - bucket_end) / 1000.0)
    return MontagePanel(mint, symbol, tuple(candles), move, span_s, interval, stale, young)


def _gap_broken(
    xs: list[float], ys: list[float], max_gap_h: float
) -> tuple[list[float], list[float]]:
    """Insert NaN breaks where consecutive points are further apart than a bucket
    should be: a stretch with no trades is drawn as a HOLE, never interpolated."""

    out_x: list[float] = []
    out_y: list[float] = []
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        if i and x - xs[i - 1] > max_gap_h:
            out_x.append((x + xs[i - 1]) / 2)
            out_y.append(float("nan"))
        out_x.append(x)
        out_y.append(y)
    return out_x, out_y


def _draw_panel(fig: Figure, sub, panel: MontagePanel) -> None:
    """One momentum tile. The visual grammar, in priority order:

    * RECENCY — the last RECENT_BARS intervals draw at full weight (bright, thick,
      brighter fill); everything older recedes (thin, ~40% alpha). The eye lands on
      now, history stays as context.
    * ACCELERATION — the current 5m volume bar is the bright one, and the PRIOR
      window's height is overlaid on it as a hollow ghost outline: "now vs the last
      window" is a shape comparison, no reading required.
    * LIVE EDGE — a ring-edged dot on the last close. If the newest bar's end trails
      the render clock by over two minutes the tile says "stale Nm" in amber next to
      a hollow (not filled) dot — a frozen series never gets to look live.
    * DIRECTION — the tile background carries a faint wash for the 5m move's sign,
      so the whole grid reads as a heat mosaic before any text is read.
    * HONESTY — series holes stay holes (`_gap_broken`), the line's own color still
      encodes the WINDOW's direction (a green hour with a red tint IS the story
      "ran up, dumping right now"), and the title keeps $SYMBOL + the 5m move.
    """

    ax_price = fig.add_subplot(sub[0])
    ax_volume = fig.add_subplot(sub[1], sharex=ax_price)
    candles = list(panel.candles)
    xs = [(c.ts_ms - candles[-1].ts_ms) / 3_600_000 for c in candles]
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    change = closes[-1] / closes[0] - 1.0 if closes[0] > 0 else 0.0
    line = PRICE_UP if change > 0 else PRICE_DOWN if change < 0 else PRICE_FLAT
    move = panel.move
    move_color = (
        PRICE_FLAT if move is None else PRICE_UP if move > 0 else PRICE_DOWN if move < 0 else PRICE_FLAT
    )
    tint = SURFACE if move is None else TINT_UP if move > 0 else TINT_DOWN if move < 0 else SURFACE
    stale = panel.stale_s is not None and panel.stale_s > 120.0

    for ax in (ax_price, ax_volume):
        ax.set_facecolor(tint)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])

    max_gap_h = GAP_FACTOR * INTERVAL_S.get(panel.interval, 300) / 3600
    split = max(len(xs) - 1 - RECENT_BARS, 0)
    if len(xs) < SPARSE_BARS:
        # Too few points for a path to mean anything: a two-point diagonal reads as
        # a rendering bug and says nothing about momentum. Dots plus the honest
        # label — the adaptive interval upstream makes this the newborn-only case.
        if len(xs) > 1:
            ax_price.plot(
                xs[:-1], closes[:-1], linestyle="none", marker="o", markersize=3,
                markerfacecolor=line, markeredgewidth=0, alpha=0.8,
            )
        kind = "new" if panel.young else "thin tape"
        ax_price.text(
            0.5, 0.5, f"{kind} — {len(xs)} bar{'s' if len(xs) != 1 else ''}",
            transform=ax_price.transAxes, color=INK_MUTED, fontsize=8,
            ha="center", va="center",
        )
    elif len(xs) > 1:
        floor = min(closes)
        if split > 0:  # the receding history, thin and faded
            hx, hy = _gap_broken(xs[: split + 1], closes[: split + 1], max_gap_h)
            ax_price.plot(hx, hy, color=line, linewidth=1.1, alpha=0.40,
                          solid_capstyle="round")
            ax_price.fill_between(hx, hy, floor, color=line, alpha=0.05, linewidth=0)
        rx, ry = _gap_broken(xs[split:], closes[split:], max_gap_h)
        ax_price.plot(rx, ry, color=line, linewidth=2.0, solid_capstyle="round")
        ax_price.fill_between(rx, ry, floor, color=line, alpha=0.16, linewidth=0)
    # The live-edge dot: filled when fresh, hollow when the series is stale.
    ax_price.plot(
        [xs[-1]], [closes[-1]], marker="o", markersize=5,
        markerfacecolor=SURFACE if stale else move_color,
        markeredgecolor=move_color if stale else SURFACE,
        markeredgewidth=1.2, zorder=5,
    )
    if stale and panel.stale_s is not None:
        ax_price.text(
            0.985, 0.05, f"stale {panel.stale_s / 60:.0f}m", transform=ax_price.transAxes,
            color=AMBER, fontsize=6.5, ha="right", va="bottom",
        )
    ax_price.margins(x=0.03, y=0.12)

    if len(xs) > 1:
        gaps = sorted(b - a for a, b in itertools.pairwise(xs))
        width = 0.8 * gaps[len(gaps) // 2]
    else:
        width = 0.05
    if len(xs) > 1:
        # History bars recede in two steps; the current window's bar is the bright one.
        bar_colors = [
            to_rgba(VOLUME, 0.40 if i < split else 0.75) for i in range(len(xs) - 1)
        ]
        ax_volume.bar(xs[:-1], volumes[:-1], width=width, color=bar_colors, linewidth=0)
    ax_volume.bar([xs[-1]], [volumes[-1]], width=width, color=VOLUME_NOW, linewidth=0, zorder=3)
    if len(volumes) >= 2 and volumes[-2] > 0:
        # The prior window as a ghost outline on the current bar: acceleration is
        # the filled bar clearing (or hiding inside) the hollow one.
        ax_volume.bar(
            [xs[-1]], [volumes[-2]], width=width, fill=False,
            edgecolor=INK_MUTED, linewidth=1.0, zorder=4,
        )
    ax_volume.margins(x=0.03)
    ax_volume.set_ylim(bottom=0)

    # Title: symbol in ink; the 5m move in direction color, sign carried in text.
    # Clamp is 18, not 12: a montage-level disambiguator ("Pepsi·6AmL") must survive.
    symbol = ("".join(panel.symbol.split()) or "?")[:18]
    ax_price.text(
        0.0, 1.07, f"${symbol}", transform=ax_price.transAxes,
        color=INK, fontsize=10.5, fontweight="bold", va="bottom",
    )
    if move is not None and panel.move_span_s is not None:
        # The span tag states what was MEASURED: "/5m" for a five-minute move, but a
        # 3-minute-old coin shows "/3m" — never a claimed window it has not lived.
        span_min = max(round(panel.move_span_s / 60), 1)
        ax_price.text(
            1.0, 1.07, f"{move:+.0%}/{span_min}m", transform=ax_price.transAxes,
            color=move_color, fontsize=9.5, ha="right", va="bottom",
        )
    ax_volume.text(
        1.0, -0.28, _span_label(candles, panel.interval).removesuffix(" closes"),
        transform=ax_volume.transAxes, color=INK_MUTED, fontsize=6.5,
        ha="right", va="top",
    )


def _montage_slots(n: int) -> tuple[int, int, list[tuple[int, int]]]:
    """(rows, unit_columns, [(row, unit_col_start)]); every panel spans 2 units.
    The grid packs what it has — 5 panels center the short row, never a blank tile."""

    if n <= 3:
        return 1, 2 * n, [(0, 2 * i) for i in range(n)]
    if n == 4:
        return 2, 4, [(0, 0), (0, 2), (1, 0), (1, 2)]
    if n == 5:
        return 2, 6, [(0, 0), (0, 2), (0, 4), (1, 1), (1, 3)]
    return 2, 6, [(0, 0), (0, 2), (0, 4), (1, 0), (1, 2), (1, 4)]


def render_montage(panels: list[MontagePanel]) -> bytes:
    """Up to six mini charts in one PNG, reading order = caption order. Pure function
    of its arguments; per-panel: price line + volume strip, title, span — no axes."""

    if not panels:
        raise ValueError("no panels to render")
    if len(panels) > 6:
        raise ValueError("a montage holds at most six panels")
    rows, unit_cols, slots = _montage_slots(len(panels))
    unit_w = 3.0 if len(panels) == 1 else 2.0
    fig_w = unit_cols * unit_w
    # The header band (0.62in) must clear the first row's panel titles, which extend
    # ~0.2in above their axes; the footer band holds the source line and the span
    # labels that hang below each volume strip.
    fig_h = 0.62 + rows * 2.10 + 0.38
    fig = Figure(figsize=(fig_w, fig_h), dpi=100, facecolor=SURFACE)
    FigureCanvasAgg(fig)
    grid = fig.add_gridspec(
        rows, unit_cols,
        left=0.02, right=0.98, top=1 - 0.62 / fig_h, bottom=0.38 / fig_h,
        wspace=0.30, hspace=0.55,
    )

    for panel, (row, col) in zip(panels, slots, strict=True):
        sub = grid[row, col : col + 2].subgridspec(2, 1, height_ratios=[3.0, 0.95], hspace=0.10)
        _draw_panel(fig, sub, panel)

    fig.text(0.02, 1 - 0.24 / fig_h, "pump.fun movers · right now",
             color=INK, fontsize=12, fontweight="bold", va="center")
    fig.text(0.98, 1 - 0.24 / fig_h, f"{len(panels)} coin{'s' if len(panels) != 1 else ''}",
             color=INK_MUTED, fontsize=9.5, ha="right", va="center")
    fig.text(
        0.5, 0.10 / fig_h, "source: pump.fun swap-api candles (SOL) · awareness, not advice",
        color=INK_MUTED, fontsize=7.5, ha="center",
    )
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", facecolor=SURFACE,
        metadata={"Software": "dregg_feed.charts montage v2"},  # pinned: deterministic
    )
    return buf.getvalue()
