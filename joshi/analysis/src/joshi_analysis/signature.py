"""Signature volatility over a retained candle window.

Implements Definition P2 from ``docs/microstructure/trades_quotes_prices/FORMAL_MODEL.md``::

    V(tau)       = E[(p_{t+tau} - p_t)^2]          variogram
    sigma^2(tau) = V(tau) / (tau * pbar^2)         signature volatility

A rising curve indicates net positive serial dependence; a falling curve indicates net mean
reversion. This is why the instrument does not need a timescale chosen in advance: sweep the lag
and read where structure lives, rather than fixing an interval and reporting whatever falls out.

Both readings are computed, because the two clocks genuinely disagree on this data and neither is
privileged. Candle windows from this provider are gap compressed -- intervals in which nothing
traded are omitted entirely -- so an index step is "one traded interval" while an elapsed-time step
is "one interval of wall clock, silence included". No total order over the two is invented; see
FORMAL_MODEL section 1.1.

Prices stay :class:`~decimal.Decimal` end to end. The provider states them as 28-digit decimal
strings and a float conversion silently discards roughly twelve of those digits.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path

EVENT_LAGS = (1, 2, 4, 8, 16, 32, 64, 128)
WALL_LAGS_MS = (1_000, 2_000, 5_000, 15_000, 60_000, 300_000, 900_000)

Bar = tuple[int, Decimal]
Row = tuple[int, Decimal | None, Decimal | None, int]


def bars_from_outcome(path: str | Path) -> tuple[list[Bar], str]:
    """Read (timestamp_ms, close) pairs out of a retained fetch outcome.

    The body is the provider's exact retained bytes: a bare top-level JSON array, not an
    envelope. Closes are kept as strings until :class:`Decimal` takes them.
    """
    with Path(path).open() as handle:
        outcome = json.load(handle)
    attempt = outcome["attempts"][0]
    rows = json.loads(base64.b64decode(attempt["body"]["bytesBase64"]))
    bars = [(int(row["timestamp"]), Decimal(row["close"])) for row in rows]
    return bars, attempt["sourceLocator"]


def _signature(variogram: Decimal, tau: Decimal, mean_price: Decimal) -> Decimal:
    return variogram / (tau * mean_price * mean_price)


def signature_event(bars: list[Bar], lags: tuple[int, ...] = EVENT_LAGS) -> list[Row]:
    """Signature volatility in event time, where a lag is a count of traded intervals."""
    mean_price = sum(price for _, price in bars) / len(bars)
    out: list[Row] = []
    for lag in lags:
        if lag >= len(bars):
            break
        diffs = [bars[i + lag][1] - bars[i][1] for i in range(len(bars) - lag)]
        variogram = sum(d * d for d in diffs) / len(diffs)
        out.append((lag, variogram, _signature(variogram, Decimal(lag), mean_price), len(diffs)))
    return out


def signature_wall(
    bars: list[Bar],
    lags_ms: tuple[int, ...] = WALL_LAGS_MS,
    tolerance: float = 0.25,
) -> list[Row]:
    """Signature volatility in wall time, pairing bars by elapsed milliseconds.

    A lag with no qualifying pair yields ``None`` rather than zero. Zero is a measurement that the
    price did not move; ``None`` is the absence of any measurement, and the two must not be
    confused.
    """
    mean_price = sum(price for _, price in bars) / len(bars)
    out: list[Row] = []
    for target in lags_ms:
        low = target * (1 - tolerance)
        high = target * (1 + tolerance)
        diffs: list[Decimal] = []
        start = 0
        for at, price in bars:
            while start < len(bars) and bars[start][0] - at < low:
                start += 1
            probe = start
            while probe < len(bars) and bars[probe][0] - at <= high:
                diffs.append(bars[probe][1] - price)
                probe += 1
        if not diffs:
            out.append((target, None, None, 0))
            continue
        variogram = sum(d * d for d in diffs) / len(diffs)
        seconds = Decimal(target) / 1000
        out.append((target, variogram, _signature(variogram, seconds, mean_price), len(diffs)))
    return out


def render(bars: list[Bar]) -> str:
    """A text report of both clocks, with pair counts so thin lags are visible as thin."""
    span_minutes = (bars[-1][0] - bars[0][0]) / 1000 / 60
    lines = [f"{len(bars)} bars, {span_minutes:.1f} min wall span"]
    lines += ["", "EVENT TIME (traded-bar lags)"]
    lines.append(f"{'lag':>7} {'sigma^2*1e6':>14} {'pairs':>7}")
    for lag, _, sigma, pairs in signature_event(bars):
        lines.append(f"{lag:>7} {float(sigma) * 1e6:>14.4f} {pairs:>7}")
    lines += ["", "WALL TIME (elapsed lags, +/-25%)"]
    lines.append(f"{'lag_s':>7} {'sigma^2*1e6':>14} {'pairs':>7}")
    for target, _, sigma, pairs in signature_wall(bars):
        cell = f"{float(sigma) * 1e6:>14.4f}" if sigma is not None else f"{'no pairs':>14}"
        lines.append(f"{target // 1000:>7} {cell} {pairs:>7}")
    return "\n".join(lines)
