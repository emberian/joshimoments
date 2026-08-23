"""The entry-window measurement: what the tape does in the 30 minutes after a callout.

For each callout in the tape plan, this reads the exact retained trade-page bytes the seek walk
committed to the store, reconstructs the price path in the window ``[createdAt, createdAt+30min]``,
and measures — shape-free and direction-agnostic — the excursion the coin offered a watcher who
started at the callout:

* the callout-price anchor: the fill price of the first trade at or after ``createdAt`` (a
  would-quote reference, NOT a fill — the corpus cannot score landing and this never claims to);
* unsigned excursion magnitude: max upward and max downward log-move from the anchor;
* the dip: whether price traded BELOW the anchor, how deep, and how long until the trough;
* time to recovery: minutes from the trough back to the anchor, if it recovered in-window;
* the two would-quote arithmetics Ember asked to compare: entering at the anchor versus entering
  at the trough, each expressed as the lift still available to the in-window maximum, net of the
  measured pump/pool fee floor. No fills, no PnL, no landing.

THE CONFOUND, stated on every row: a callout's ``createdAt`` is an OCCURRENCE time. Nothing tells
us when the callout became visible, so the first minutes after ``createdAt`` mix the coin's
reaction TO the callout with whatever the callout was reacting to. At short lags the two cannot be
separated, and this measurement does not pretend to.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# Fee floors measured in Study M0 (round-trip, venue fees only). The pump bonding curve floor is
# the conservative default; a graduated pool is cheaper but the program-fee tier is selected by
# market cap and is not readable from a trade row alone, so the curve floor is used as the hurdle
# a lift must clear and is named as such.
CURVE_ROUND_TRIP_BPS = 247.0


def blob_path(state_dir: Path, blob_id: str) -> Path:
    digest = blob_id.removeprefix("sha256:")
    return (
        state_dir
        / "blobs"
        / "public_source"
        / "sha256"
        / digest[0:2]
        / digest[2:4]
        / f"{digest}.blob"
    )


def load_window_trades(receipt: dict, state_dir: Path) -> list[dict]:
    """All trade rows across the walk's promoted pages, oldest-first, deduped by slotIndexId."""
    rows: dict[str, dict] = {}
    for page in receipt["walk"]["pages"]:
        if page["schemaTrustOutcome"] != "promoted" or not page.get("bodyBlobId"):
            continue
        path = blob_path(state_dir, page["bodyBlobId"])
        if not path.exists():
            continue
        body = json.loads(path.read_bytes())
        for trade in body.get("trades", []):
            rows[trade["slotIndexId"]] = trade
    return sorted(rows.values(), key=lambda t: t["slotIndexId"])


def ms_of(iso: str) -> int:
    import datetime as dt

    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def measure(item: dict, receipt: dict, state_dir: Path) -> dict | None:
    """Reconstruct one callout's entry window from the tape; None when tape misses it."""
    t0 = int(item["createdAt"])
    window_end = t0 + 30 * 60 * 1000
    trades = load_window_trades(receipt, state_dir)
    if not trades:
        return None

    # The fill price a taker actually paid is the honest mark for a would-be entrant; fall back to
    # the pool price only if a row lacks it. Both are provider assertions in SOL, carrying the
    # read-time SOL divisor, so ratios between rows of one coin are clean but SOL levels are not.
    def price(trade: dict) -> float:
        for key in ("fillPriceSol", "priceSol"):
            value = trade.get(key)
            if value is not None:
                return float(value)
        raise KeyError("trade row carries no SOL price")

    # COVERAGE GATE. The seek walks BACKWARD from the window end, so a busy coin whose 30-minute
    # window holds more trades than the walk's page budget retains leaves the walk stopped well
    # short of t0: its earliest retained in-window trade is minutes-to-tens-of-minutes AFTER the
    # callout, and taking that as the entry anchor would measure the window's tail, not its entry.
    # The window is "entry-covered" only when the walk retained a trade at or before t0 — i.e. the
    # earliest in-window trade sits within a short lag of t0. Everything else is tail-only and is
    # reported as an uncovered window, never folded into the dip distribution.
    oldest_ms = ms_of(trades[0]["timestamp"])
    in_window = [t for t in trades if t0 <= ms_of(t["timestamp"]) <= window_end]
    if not in_window:
        return None
    anchor = price(in_window[0])
    anchor_ms = ms_of(in_window[0]["timestamp"])
    if anchor <= 0:
        return None
    entry_covered = oldest_ms <= t0 or (anchor_ms - t0) <= 120_000

    logs = [(ms_of(t["timestamp"]), math.log(price(t) / anchor)) for t in in_window if price(t) > 0]
    up = max(value for _, value in logs)
    down = min(value for _, value in logs)
    trough_ms, trough_log = min(logs, key=lambda pair: pair[1])
    peak_ms, peak_log = max(logs, key=lambda pair: pair[1])

    dipped = down < 0
    time_to_trough_min = (trough_ms - anchor_ms) / 60000 if dipped else None
    # Recovery: first time after the trough that price returns to the anchor.
    recovery_min = None
    if dipped:
        for stamp, value in logs:
            if stamp > trough_ms and value >= 0:
                recovery_min = (stamp - trough_ms) / 60000
                break

    # Would-quote arithmetic, as lift-to-in-window-peak, net of the curve fee floor. Entering at
    # the anchor pays the whole distance from 0; entering at the trough starts `trough_log` lower,
    # so it has that much more headroom to the same peak — this is the arithmetic advantage of
    # "waiting for the dip", with NO claim that the dip is catchable or that a fill lands.
    hurdle = CURVE_ROUND_TRIP_BPS / 10000.0
    peak_ret = math.expm1(peak_log)
    trough_entry_ret = math.expm1(peak_log - trough_log)
    return {
        "calloutId": item["calloutId"],
        "mint": item["mint"],
        "bin": item["bin"],
        "multiple_asserted": item.get("multiple_asserted"),
        "age_hours": item.get("age_hours"),
        "window_trades": len(in_window),
        "anchor_lag_ms": anchor_ms - t0,
        "entry_covered": entry_covered,
        "max_up_pct": round(100 * math.expm1(up), 2),
        "max_down_pct": round(100 * math.expm1(down), 2),
        "excursion_span_pct": round(100 * math.expm1(up - down), 2),
        "dipped_below_anchor": dipped,
        "dip_depth_pct": round(100 * math.expm1(down), 2) if dipped else 0.0,
        "time_to_trough_min": round(time_to_trough_min, 1) if time_to_trough_min else None,
        "recovery_min": round(recovery_min, 1) if recovery_min is not None else None,
        "recovered_in_window": recovery_min is not None,
        "peak_min": round((peak_ms - anchor_ms) / 60000, 1),
        "wouldquote_anchor_to_peak_pct": round(100 * peak_ret, 2),
        "wouldquote_trough_to_peak_pct": round(100 * trough_entry_ret, 2),
        "clears_hurdle_from_anchor": peak_ret > hurdle,
        "clears_hurdle_from_trough": trough_entry_ret > hurdle,
    }


def quantile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def cmd_run(root: Path, plan_file: Path) -> None:
    plan = json.loads(plan_file.read_text())
    state_dir = root / "tape" / "state"
    results = []
    no_tape = 0
    for item in plan:
        tag = f"{item['calloutId'][:18]}_B"
        receipt_path = root / "tape" / f"{tag}.receipt.json"
        if not receipt_path.exists():
            no_tape += 1
            continue
        receipt = json.loads(receipt_path.read_text())
        row = measure(item, receipt, state_dir)
        if row is None:
            no_tape += 1
            continue
        results.append(row)
    out = root / "excursions.jsonl"
    with out.open("w") as sink:
        for row in results:
            sink.write(json.dumps(row) + "\n")

    covered = [r for r in results if r["entry_covered"]]
    tail_only = [r for r in results if not r["entry_covered"]]
    print(f"reconstructed {len(results)} callout windows; {no_tape} had no in-window tape")
    print(
        f"  entry-covered (walk reached back to the callout instant): {len(covered)}\n"
        f"  tail-only (busy coin; walk's page budget stopped short of t0, "
        f"so the entry is not observed): {len(tail_only)} — EXCLUDED from the dip distribution"
    )
    print("\nCONFOUND: createdAt is occurrence time; the first minutes mix reaction-to-callout")
    print("with what-the-callout-reacted-to. Short-lag numbers cannot separate them.")
    print(
        "COVERAGE BIAS: entry-coverage requires the 30-min window to hold few enough trades that "
        "the\nwalk's page budget spanned it, so the covered set skews toward quieter coins. "
        "Stated, not hidden.\n"
    )
    results = covered
    if not results:
        print("no ENTRY-COVERED windows to summarize; the entry-window question is REFUSED here")
        print("for want of tape that reaches the callout instant on these coins.")
        return

    dipped = [r for r in results if r["dipped_below_anchor"]]
    print(f"dip below the callout-price anchor: {len(dipped)}/{len(results)} callouts")
    depths = [-r["dip_depth_pct"] for r in dipped]
    if depths:
        print(
            f"  dip depth %% (of dippers): p25={quantile(depths, 0.25):.1f} "
            f"median={quantile(depths, 0.5):.1f} p75={quantile(depths, 0.75):.1f} "
            f"max={max(depths):.1f}"
        )
        ttt = [r["time_to_trough_min"] for r in dipped if r["time_to_trough_min"] is not None]
        print(
            f"  time-to-trough min: median={quantile(ttt, 0.5):.1f} p75={quantile(ttt, 0.75):.1f}"
        )
        recovered = [r for r in dipped if r["recovered_in_window"]]
        print(f"  recovered to anchor in-window: {len(recovered)}/{len(dipped)}")

    spans = [r["excursion_span_pct"] for r in results]
    print(
        f"\nunsigned excursion span %% (peak-to-trough, all): median={quantile(spans, 0.5):.1f} "
        f"p75={quantile(spans, 0.75):.1f} p90={quantile(spans, 0.9):.1f}"
    )
    ups = [r["max_up_pct"] for r in results]
    downs = [r["max_down_pct"] for r in results]
    print(
        f"max up %% from anchor: median={quantile(ups, 0.5):.1f} p90={quantile(ups, 0.9):.1f}; "
        f"max down %%: median={quantile(downs, 0.5):.1f} p10={quantile(downs, 0.1):.1f}"
    )

    print("\nwould-quote arithmetic (lift to in-window peak, NOT a fill, NOT PnL):")
    anchor_clears = sum(r["clears_hurdle_from_anchor"] for r in results)
    trough_clears = sum(r["clears_hurdle_from_trough"] for r in results)
    n = len(results)
    print(
        f"  clears the {CURVE_ROUND_TRIP_BPS:.0f} bps curve hurdle from the anchor: "
        f"{anchor_clears}/{n}"
    )
    print(f"  clears it entering at the trough instead:                {trough_clears}/{n}")
    aq = [r["wouldquote_anchor_to_peak_pct"] for r in results]
    tq = [r["wouldquote_trough_to_peak_pct"] for r in results]
    print(
        f"  median lift-to-peak from anchor: {quantile(aq, 0.5):.1f}%  "
        f"from trough: {quantile(tq, 0.5):.1f}%"
    )

    print("\nby bin (n, dip rate, median span %, median lift-from-anchor %):")
    for name in ("no_peak_yet", "floor_eq_1", "1_to_2", "2_to_5", "5_to_20", "over_20"):
        rows = [r for r in results if r["bin"] == name]
        if not rows:
            continue
        dip_rate = 100 * sum(r["dipped_below_anchor"] for r in rows) / len(rows)
        span = quantile([r["excursion_span_pct"] for r in rows], 0.5)
        lift = quantile([r["wouldquote_anchor_to_peak_pct"] for r in rows], 0.5)
        print(
            f"  {name:11s} n={len(rows):2d}  dip={dip_rate:4.0f}%  "
            f"span={span:6.1f}%  lift={lift:6.1f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    cmd_run(args.root, args.plan)


if __name__ == "__main__":
    main()
