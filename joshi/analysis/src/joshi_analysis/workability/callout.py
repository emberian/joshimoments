"""The callout entry-window measurement at census scale (STUDY.md section 6).

This is the callout_entry_window study's ``excursion.measure`` method carried over onto the
scalplab event frame, so the n~100 numbers are comparable with the registered n=6 study:
anchor = first trade at or after the callout's ``createdAt``; unsigned excursions from the
anchor; the dip below the anchor with its depth, trough timing, and recovery; and the two
would-quote arithmetics (enter at the anchor vs at the trough), each as lift to the in-window
peak net of the coin's declared floor. No fills, no PnL, no landing.

THE CONFOUND, on every row: ``createdAt`` is an OCCURRENCE time. Nothing states when the
callout became visible, so short-lag structure mixes reaction-to-callout with
whatever-the-callout-reacted-to, and this measurement does not pretend to separate them.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from joshi_analysis.scalplab.tape import TapeEvent

WINDOW_MINUTES = 30
ENTRY_LAG_CAP_MS = 120_000


def measure_entry_window(
    events: Sequence[TapeEvent],
    t0_ms: int,
    floor_bps: int,
    window_minutes: int = WINDOW_MINUTES,
) -> dict | None:
    """One callout's entry window from one coin's deduplicated events. None without tape.

    ``entry_covered`` is the same gate as the n=6 study: the tape must hold a trade at or
    before t0, or the anchor must sit within two minutes of it — otherwise the window is
    tail-only (busy-coin coverage bias) and the caller excludes it from the dip distribution.
    """
    timed = [
        event
        for event in events
        if event.event_time_us is not None and float(event.price) > 0
    ]
    if not timed:
        return None
    window_end_ms = t0_ms + window_minutes * 60_000
    in_window = [
        event for event in timed if t0_ms <= event.event_time_us // 1000 <= window_end_ms
    ]
    if not in_window:
        return None
    oldest_ms = min(event.event_time_us for event in timed) // 1000

    def price_of(event: TapeEvent) -> float:
        # The fill a taker actually paid is the honest mark for a would-be entrant; the pool
        # price is the fallback, exactly as the n=6 study read its rows.
        return float(event.fill_price if event.fill_price else event.price)

    anchor_event = in_window[0]
    anchor = price_of(anchor_event)
    anchor_ms = anchor_event.event_time_us // 1000
    if anchor <= 0:
        return None
    entry_covered = oldest_ms <= t0_ms or (anchor_ms - t0_ms) <= ENTRY_LAG_CAP_MS

    logs = [
        (event.event_time_us // 1000, math.log(price_of(event) / anchor))
        for event in in_window
    ]
    up = max(value for _, value in logs)
    down = min(value for _, value in logs)
    trough_ms, trough_log = min(logs, key=lambda pair: pair[1])
    peak_ms, peak_log = max(logs, key=lambda pair: pair[1])

    dipped = down < 0
    recovery_min = None
    if dipped:
        for stamp, value in logs:
            if stamp > trough_ms and value >= 0:
                recovery_min = (stamp - trough_ms) / 60_000
                break

    hurdle = floor_bps / 10_000
    peak_ret = math.expm1(peak_log)
    trough_entry_ret = math.expm1(peak_log - trough_log)
    return {
        "window_trades": len(in_window),
        "anchor_lag_ms": anchor_ms - t0_ms,
        "entry_covered": entry_covered,
        "floor_bps": floor_bps,
        "max_up_pct": round(100 * math.expm1(up), 2),
        "max_down_pct": round(100 * math.expm1(down), 2),
        "excursion_span_pct": round(100 * math.expm1(up - down), 2),
        "dipped_below_anchor": dipped,
        "dip_depth_pct": round(100 * math.expm1(down), 2) if dipped else 0.0,
        "time_to_trough_min": round((trough_ms - anchor_ms) / 60_000, 1) if dipped else None,
        "recovery_min": round(recovery_min, 1) if recovery_min is not None else None,
        "recovered_in_window": recovery_min is not None,
        "peak_min": round((peak_ms - anchor_ms) / 60_000, 1),
        "wouldquote_anchor_to_peak_pct": round(100 * peak_ret, 2),
        "wouldquote_trough_to_peak_pct": round(100 * trough_entry_ret, 2),
        "clears_hurdle_from_anchor": peak_ret > hurdle,
        "clears_hurdle_from_trough": trough_entry_ret > hurdle,
        "confound": "createdAt is occurrence time; short lags mix reaction with cause",
    }
