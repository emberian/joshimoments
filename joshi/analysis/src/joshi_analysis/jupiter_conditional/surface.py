"""The conditional-settlement surface and its own falsification (registration v1 + v1.1).

Counting: the signed freeze-now boundary distance d (bps) crossed with time remaining is
the axis — per Ember's step-function insight, the settlement pays the same $1 for a 1 bp
nick as for a 100 bp move, so proximity-to-boundary, not direction, is where the edge
lives. Per cell: P(up), the cross rate (settlement ends opposite the side it currently
sits on), and the convex EV of buying the currently-losing side at HYPOTHETICAL entries
against the fee formula — no live contract prices are involved and no mispricing is
claimed. The trend-day claim ("chop quantized into a victory during a trend") is measured
directly on trend-regime windows. Falsification: temporal 70/30 split, Brier + reliability
+ ECE on the held-out tail; a failed license means the counting itself was wrong.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from joshi_analysis.jupiter_base_rate.study import FEE_FLOOR, wilson_95

from .finesol import StepSeries
from .rules import final_margin_bps
from .state import DecisionState, decision_states, regime

D_BIN_EDGES = (-30.0, -15.0, -8.0, -4.0, -2.0, -1.0, 0.0, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
ABS_D_BANDS = ((0, 1), (1, 2), (2, 4), (4, 8), (8, 15), (15, 30), (30, math.inf))
ENTRY_PRICES = (0.05, 0.15, 0.50, 0.85)
FEE_COEF = 0.070  # dollars per contract ~= FEE_COEF * q * (1-q), pre-round-up (map, DERIVED)
AMBIGUOUS_BAND_BPS = 2.0  # the measured venue-basis floor
THIN_N = 30
CELL_MIN_N_FOR_PREDICTION = 10
SPLIT_FRACTION = 0.70
RELIABILITY_BINS = 10
ECE_LICENSE = 0.10
NEAR_BPS = 4.0
FAR_BPS = 15.0
LATE_FRACTION = 0.1
EARLY_FRACTION = 0.4


def d_bin(d_bps: float) -> int:
    for i, edge in enumerate(D_BIN_EDGES):
        if d_bps <= edge:
            return i
    return len(D_BIN_EDGES)


def d_bin_label(i: int) -> str:
    if i == 0:
        return f"<={D_BIN_EDGES[0]:g}"
    if i == len(D_BIN_EDGES):
        return f">{D_BIN_EDGES[-1]:g}"
    return f"({D_BIN_EDGES[i - 1]:g},{D_BIN_EDGES[i]:g}]"


def abs_band(d_bps: float) -> int:
    a = abs(d_bps)
    for i, (lo, hi) in enumerate(ABS_D_BANDS):
        if lo <= a <= hi if hi != math.inf else a > lo:
            return i
    return len(ABS_D_BANDS) - 1


def abs_band_label(i: int) -> str:
    lo, hi = ABS_D_BANDS[i]
    if hi == math.inf:
        return f">{lo}"
    return f"[0,{hi}]" if lo == 0 else f"({lo},{hi}]"


def breakeven(q: float) -> float:
    """The cross rate a hypothetical entry at q needs to clear price + explicit fee."""
    return q + FEE_COEF * q * (1 - q)


@dataclass(frozen=True)
class WindowSample:
    horizon_s: int
    t_open: int
    label_up: bool
    final_margin_bps: float
    ambiguous: bool
    regime: str
    states: tuple[DecisionState, ...]


def collect_windows(
    series: StepSeries, horizon_s: int, rule: str
) -> tuple[list[WindowSample], dict]:
    """Every grid window of the span with a reconstructable settlement; exclusions counted."""
    lo, hi = series.span
    first = (int(lo) // horizon_s + 1) * horizon_s
    samples: list[WindowSample] = []
    excluded = 0
    t = first
    while t + horizon_s <= hi:
        margin = final_margin_bps(series, float(t), float(t + horizon_s), rule)
        if margin is None:
            excluded += 1
        else:
            samples.append(
                WindowSample(
                    horizon_s=horizon_s,
                    t_open=t,
                    label_up=margin >= 0.0,
                    final_margin_bps=margin,
                    ambiguous=abs(margin) < AMBIGUOUS_BAND_BPS,
                    regime=regime(series, float(t)) or "absent",
                    states=tuple(decision_states(series, float(t), float(t + horizon_s), rule)),
                )
            )
        t += horizon_s
    return samples, {"gridWindows": (t - first) // horizon_s, "excludedDataAbsent": excluded}


def split_temporal(samples: list[WindowSample]) -> tuple[list[WindowSample], list[WindowSample]]:
    if not samples:
        return [], []
    lo = min(s.t_open for s in samples)
    hi = max(s.t_open for s in samples)
    cut = lo + SPLIT_FRACTION * (hi - lo)
    return [s for s in samples if s.t_open < cut], [s for s in samples if s.t_open >= cut]


Key = tuple[int, float]  # (signed d bin, remaining_fraction)


def count_surface(samples: list[WindowSample]) -> dict[Key, list[int]]:
    """{(d_bin, remaining_fraction): [n, up]}; one state per window per remaining value."""
    cells: dict[Key, list[int]] = {}
    for w in samples:
        for st in w.states:
            cell = cells.setdefault((d_bin(st.d_bps), st.remaining_fraction), [0, 0])
            cell[0] += 1
            cell[1] += w.label_up
    return cells


def marginal_by_remaining(samples: list[WindowSample]) -> dict[float, list[int]]:
    out: dict[float, list[int]] = {}
    for w in samples:
        for st in w.states:
            cell = out.setdefault(st.remaining_fraction, [0, 0])
            cell[0] += 1
            cell[1] += w.label_up
    return out


def predict(
    surface: dict[Key, list[int]],
    marginal: dict[float, list[int]],
    base_rate: float,
    st: DecisionState,
) -> float:
    """A-surface cell rate; registered fallback to the remaining-marginal, then base rate."""
    cell = surface.get((d_bin(st.d_bps), st.remaining_fraction))
    if cell and cell[0] >= CELL_MIN_N_FOR_PREDICTION:
        return cell[1] / cell[0]
    marg = marginal.get(st.remaining_fraction)
    if marg and marg[0]:
        return marg[1] / marg[0]
    return base_rate


def cross_ev_surface(samples: list[WindowSample]) -> list[dict]:
    """Per (|d| band, remaining): n, cross rate + CI, side split, EV at hypothetical entries.

    A cross = the settlement ends opposite the side it sits on at the decision state. EV(q) =
    P(cross) - q - fee(q) for buying the currently-losing side at entry q; entries are
    hypothetical (no live prices), breakevens printed beside.
    """
    cells: dict[tuple[int, float], dict] = {}
    for w in samples:
        for st in w.states:
            key = (abs_band(st.d_bps), st.remaining_fraction)
            cell = cells.setdefault(
                key, {"n": 0, "crossed": 0, "sideUp": [0, 0], "sideDown": [0, 0]}
            )
            crossed = w.label_up != st.current_side_up
            cell["n"] += 1
            cell["crossed"] += crossed
            side = cell["sideUp"] if st.current_side_up else cell["sideDown"]
            side[0] += 1
            side[1] += crossed
    out = []
    for (band, frac), cell in sorted(cells.items()):
        n, k = cell["n"], cell["crossed"]
        rate = k / n
        ci = wilson_95(k, n)
        out.append(
            {
                "absDBandBps": abs_band_label(band),
                "remainingFraction": frac,
                "n": n,
                "crossed": k,
                "crossRate": rate,
                "wilson95": list(ci) if ci else None,
                "thin": n < THIN_N,
                "sideUp": {"n": cell["sideUp"][0], "crossed": cell["sideUp"][1]},
                "sideDown": {"n": cell["sideDown"][0], "crossed": cell["sideDown"][1]},
                "evPerEntry": {
                    f"{q:.2f}": {
                        "breakevenCrossRate": breakeven(q),
                        "evPerContract": rate - breakeven(q),
                        "clearsExplicitFee": rate > breakeven(q),
                    }
                    for q in ENTRY_PRICES
                },
            }
        )
    return out


def _state_at(w: WindowSample, fraction: float) -> DecisionState | None:
    for st in w.states:
        if st.remaining_fraction == fraction:
            return st
    return None


def trend_claim(samples: list[WindowSample]) -> list[dict]:
    """Ember's claim, measured: on trend windows, do near-boundary late setups still cross?

    One observation per window per cell (late = the r-fraction 0.1 state, early = 0.4).
    Cells: trend regime x timing x near/far x current-side-agrees-with-trend.
    """
    cells: dict[tuple[str, str, str, str], list[int]] = {}
    for w in samples:
        if w.regime not in ("up", "down"):
            continue
        for timing, fraction in (("late", LATE_FRACTION), ("early", EARLY_FRACTION)):
            st = _state_at(w, fraction)
            if st is None:
                continue
            a = abs(st.d_bps)
            if a <= NEAR_BPS:
                distance = "near"
            elif a > FAR_BPS:
                distance = "far"
            else:
                continue  # the registered bands only; the middle is in the main surface
            agrees = st.current_side_up == (w.regime == "up")
            key = (w.regime, timing, distance, "agree" if agrees else "against")
            cell = cells.setdefault(key, [0, 0])
            cell[0] += 1
            cell[1] += w.label_up != st.current_side_up
    out = []
    for (reg, timing, distance, agreement), (n, k) in sorted(cells.items()):
        ci = wilson_95(k, n)
        out.append(
            {
                "regime": reg,
                "timing": timing,
                "distance": distance,
                "currentSideVsTrend": agreement,
                "n": n,
                "crossed": k,
                "crossRate": k / n,
                "wilson95": list(ci) if ci else None,
                "thin": n < THIN_N,
            }
        )
    return out


def brier_and_reliability(pairs: list[tuple[float, bool]]) -> dict:
    """Brier + 10-bin reliability + ECE for (predicted, outcome) pairs."""
    if not pairs:
        return {"n": 0}
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    bins: list[list] = [[0, 0.0, 0] for _ in range(RELIABILITY_BINS)]
    for p, y in pairs:
        i = min(RELIABILITY_BINS - 1, int(p * RELIABILITY_BINS))
        bins[i][0] += 1
        bins[i][1] += p
        bins[i][2] += y
    curve = [
        {
            "bin": f"[{i / RELIABILITY_BINS:.1f},{(i + 1) / RELIABILITY_BINS:.1f})",
            "n": n,
            "meanPredicted": tot_p / n,
            "observed": ups / n,
        }
        for i, (n, tot_p, ups) in enumerate(bins)
        if n
    ]
    ece = sum(row["n"] * abs(row["observed"] - row["meanPredicted"]) for row in curve) / len(pairs)
    return {"n": len(pairs), "brier": brier, "ece": ece, "reliability": curve}


def build_context(series: StepSeries, horizon_s: int, rule: str) -> dict:
    """Windows, temporal split, and the A-surface for one horizon — shared by report + scoring."""
    samples, coverage = collect_windows(series, horizon_s, rule)
    set_a, set_b = split_temporal(samples)
    return {
        "samples": samples,
        "coverage": coverage,
        "set_a": set_a,
        "set_b": set_b,
        "surface": count_surface(set_a),
        "marginal": marginal_by_remaining(set_a),
        "base_rate": (sum(w.label_up for w in set_a) / len(set_a)) if set_a else 0.5,
    }


def evaluate_horizon(ctx: dict, horizon_s: int) -> dict:
    """Steps 2-4 + amendment v1.1 for one horizon."""
    samples, coverage = ctx["samples"], ctx["coverage"]
    set_a, set_b = ctx["set_a"], ctx["set_b"]
    surface, marginal, base_rate = ctx["surface"], ctx["marginal"], ctx["base_rate"]

    direction_cells = []
    for (b, frac), (n, up) in sorted(surface.items()):
        ci = wilson_95(up, n)
        direction_cells.append(
            {
                "dBin": d_bin_label(b),
                "remainingFraction": frac,
                "remainingSeconds": frac * horizon_s,
                "n": n,
                "up": up,
                "pUp": up / n,
                "wilson95": list(ci) if ci else None,
                "thin": n < THIN_N,
            }
        )

    pairs = [
        (predict(surface, marginal, base_rate, st), w.label_up) for w in set_b for st in w.states
    ]
    pooled = brier_and_reliability(pairs)
    baseline_brier = (
        sum((base_rate - w.label_up) ** 2 for w in set_b for _ in w.states) / len(pairs)
        if pairs
        else None
    )
    licensed = bool(
        pooled.get("n")
        and baseline_brier is not None
        and pooled["ece"] <= ECE_LICENSE
        and pooled["brier"] < baseline_brier
    )
    return {
        "horizonSeconds": horizon_s,
        "coverage": coverage,
        "windows": {
            "total": len(samples),
            "setA": len(set_a),
            "setB": len(set_b),
            "ambiguousAtReferenceResolution": {
                "count": sum(w.ambiguous for w in samples),
                "n": len(samples),
                "bandBps": AMBIGUOUS_BAND_BPS,
            },
            "regimes": {
                reg: sum(1 for w in samples if w.regime == reg)
                for reg in ("down", "flat", "up", "absent")
            },
        },
        "setABaseRate": base_rate,
        "directionSurface": direction_cells,
        "crossEvSurface": cross_ev_surface(set_a),
        "trendClaim": trend_claim(set_a),
        "calibration": {
            "pooled": pooled,
            "baselineBrier": baseline_brier,
            "licensedToContinue": licensed,
            "license": f"ECE <= {ECE_LICENSE} and Brier < baseline (registered)",
        },
        "feeFloor": FEE_FLOOR,
        "entryPricesNote": (
            "EV entries are HYPOTHETICAL prices (no live contract prices in this pass); "
            "breakeven = q + 0.070*q*(1-q) explicit fee only — spread/overround riders on top"
        ),
    }


def score_real_settlements(
    series: StepSeries,
    labeled: list[tuple[str, int, int, str]],
    contexts: dict[int, dict],
    rule: str,
) -> dict:
    """The A-surfaces' predictions against REAL settlement labels (small n, stated)."""
    pairs = []
    rows = []
    for event_id, t_open, t_close, actual in labeled:
        ctx = contexts.get(t_close - t_open)
        if ctx is None:
            continue
        actual_up = actual == "Up"
        for st in decision_states(series, float(t_open), float(t_close), rule):
            p = predict(ctx["surface"], ctx["marginal"], ctx["base_rate"], st)
            pairs.append((p, actual_up))
            rows.append(
                {
                    "eventId": event_id,
                    "remainingS": st.remaining_s,
                    "predictedUp": p,
                    "actual": actual,
                    "dBps": st.d_bps,
                }
            )
    score = brier_and_reliability(pairs)
    return {"rounds": len(labeled), "statePredictions": rows, "score": score}
