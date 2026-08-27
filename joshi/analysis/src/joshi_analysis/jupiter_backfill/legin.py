"""Leg-in / min-combined-cost estimand over backfilled rounds — the census first pass.

Registered as jupiter_conditional REGISTRATION.md amendment v1.2 (absorbed into the v1.3
opportunity census as strategy 3). This module is the FILLS-BASED ANALOG of the registered
quoted-price estimand, run on backfill data to prove the pipeline end-to-end:

- v1.2(a) defined min-combined-cost on the collector's QUOTED buy prices. Backfill has
  tick-level FILLS: the per-side minimum here is the cheapest price at which that side
  ACTUALLY TRANSACTED in-window — a realistic transacted price, never a quoted level and
  never a guaranteed fillable size. This is stated in every output.
- The oracle-window caveat carries over: min-so-far over the whole window is a
  feasibility bound on what legging could have achieved, not a live-executable claim.
- Fees: explicit taker fee 0.070*q*(1-q) per leg (the constant DERIVED in
  docs/reference/JUPITER_PREDICTION_MAP.md SS4 and independently CORROBORATED by
  Polymarket's own feeSchedule {rate: 0.07, takerOnly: true} on these markets). The
  round-up-to-nearest-cent rider is stated, not applied. Spread/overround riders per the
  map sit on top.

Pure compute, no network. Coverage rule (fixed here, before any real round was computed):
a round is covered iff BOTH sides have >= MIN_SIDE_OBS in-window price observations
(fills, topped up with 1-min history points when the round was thin). Fewer = counted
insufficient-coverage, never imputed. This is the backfill analog of v1.2's >=10-sample
gate, which was written for the live collector's ~20 s quote sampling.
"""

from __future__ import annotations

from . import reads

MIN_SIDE_OBS = 5
FEE_RATE = 0.070


def fee(q: float) -> float:
    """Explicit per-contract taker fee in dollars, before the round-up-to-cent rider."""
    return FEE_RATE * q * (1.0 - q)


def side_observations(rec: dict) -> tuple[list[float], list[float], str]:
    """In-window price observations per side: fills primary, 1-min history top-up.

    Returns (up_prices, down_prices, source_tag). History points are only added for a
    side when that side's fill count is under MIN_SIDE_OBS (the thin trigger), matching
    how the fetcher decided to spend the history requests.
    """
    zones = reads.split_zones(
        rec.get("trades", {}).get("rows") or [],
        rec["windowStartUnix"],
        rec["closeTimeUnix"],
    )
    up = [float(r[2]) for r in zones.in_window_up if r[2] is not None]
    down = [float(r[2]) for r in zones.in_window_down if r[2] is not None]
    source = "fills"
    hist = rec.get("priceHistory") or {}
    if hist.get("fetched"):
        start, close = rec["windowStartUnix"], rec["closeTimeUnix"]
        for side, sink in (("up", up), ("down", down)):
            if len(sink) >= MIN_SIDE_OBS:
                continue
            pts = [
                float(p)
                for t, p in (hist.get(side) or [])
                if t is not None and p is not None and start <= t < close
            ]
            if pts:
                sink.extend(pts)
                source = "fills+1min-history"
    return up, down, source


def leg_in_round(rec: dict) -> dict:
    """v1.2(a)/(b) for one round: min combined cost of the two legs, net of explicit fee."""
    up, down, source = side_observations(rec)
    base = {
        "roundKey": rec["roundKey"],
        "horizon": rec["horizon"],
        "ruleEra": rec.get("ruleEra"),
        "nUp": len(up),
        "nDown": len(down),
        "source": source,
        "settlementLabel": (rec.get("settlement") or {}).get("label"),
        "labelSource": (rec.get("settlement") or {}).get("labelSource"),
    }
    if len(up) < MIN_SIDE_OBS or len(down) < MIN_SIDE_OBS:
        return {**base, "covered": False, "reason": "insufficient-coverage"}
    min_up, min_down = min(up), min(down)
    combined = min_up + min_down
    net = combined + fee(min_up) + fee(min_down)
    return {
        **base,
        "covered": True,
        "minUp": min_up,
        "minDown": min_down,
        "combined": combined,
        "feeUp": fee(min_up),
        "feeDown": fee(min_down),
        "combinedNetFee": net,
        "lockedNetFee": net < 1.0,
        "lockedGross": combined < 1.0,
    }


def quantiles(values: list[float], qs: tuple[float, ...]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    out = {}
    for q in qs:
        idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
        out[f"p{int(q * 100)}"] = s[idx]
    return out


def summarize(per_round: list[dict]) -> dict:
    """Aggregate the estimand by horizon (and rule era), fee floor printed beside."""
    horizons: dict[str, dict] = {}
    for horizon in sorted({r["horizon"] for r in per_round}):
        rows = [r for r in per_round if r["horizon"] == horizon]
        cov = [r for r in rows if r["covered"]]
        combined = [r["combined"] for r in cov]
        net = [r["combinedNetFee"] for r in cov]
        by_era: dict[str, dict] = {}
        for era in sorted({r["ruleEra"] or "unknown" for r in cov}):
            era_rows = [r for r in cov if (r["ruleEra"] or "unknown") == era]
            by_era[era] = {
                "covered": len(era_rows),
                "lockRateNetFee": (
                    sum(1 for r in era_rows if r["lockedNetFee"]) / len(era_rows)
                    if era_rows
                    else None
                ),
            }
        horizons[horizon] = {
            "rounds": len(rows),
            "covered": len(cov),
            "insufficientCoverage": len(rows) - len(cov),
            "combinedQuantiles": quantiles(combined, (0.10, 0.25, 0.50, 0.75, 0.90)),
            "combinedNetFeeQuantiles": quantiles(net, (0.10, 0.25, 0.50, 0.75, 0.90)),
            "lockedNetFee": sum(1 for r in cov if r["lockedNetFee"]),
            "lockRateNetFee": (
                sum(1 for r in cov if r["lockedNetFee"]) / len(cov) if cov else None
            ),
            "lockedGross": sum(1 for r in cov if r["lockedGross"]),
            "byRuleEra": by_era,
        }
    return {
        "estimand": "leg-in min-combined-cost (v1.2a/b, fills-based analog)",
        "registration": "joshi.jupiter_conditional.registration.v1 amendments v1.2/v1.3",
        "feePerLeg": "0.070*q*(1-q), taker, corroborated by gamma feeSchedule rate=0.07",
        "feeFloorMidpointUsd": 0.0175,
        "roundUpToCentRider": "stated, not applied; dominates cheap legs (map SS4)",
        "coverageRule": f"both sides >= {MIN_SIDE_OBS} in-window observations",
        "caveats": [
            "fills-based: per-side minima are realistic transacted prices, not quotes;"
            " no fillable size is guaranteed at those prices",
            "oracle-window bound: min-so-far over the whole window is feasibility,"
            " not a live-executable claim",
            "prices/timestamps are provider claims; nothing is settlement-exact;"
            " the SOL reference the census joins against is a ~2bp approximation",
            "spread/overround riders (map SS4) sit on top of the explicit fee",
        ],
        "byHorizon": horizons,
    }
