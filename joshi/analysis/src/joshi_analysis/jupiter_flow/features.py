"""The registered v1.4 feature set, computed causally at each decision instant.

Causality contract (registration v1.4): every FLOW feature at t is a function of tape
trades with timestamp STRICTLY BEFORE t; the unit test computes the vector on
``tape.truncated(t)`` and requires bit-identity. Price-anchored features (returns, vols)
are None when an anchor price is data-absent (no trade within 120 s of the anchor) — the
instant is then EXCLUDED and counted, never imputed. Pure count/volume features are total
functions: an empty window is genuinely zero flow.

The PRICE/STATE set is the strawman's information done properly (the ablation control);
the FLOW set is the new information. d_bps/gap_bps/rem_* join from the registered v1
DecisionState (at-or-before-t semantics, stated) in the census builder.
"""

from __future__ import annotations

from math import asinh, log, sqrt
from statistics import median

from .hawkes import Excitation
from .tape import FlowTape

OFI_WINDOWS = (30.0, 60.0, 120.0, 300.0, 900.0)
SV_WINDOWS = (60.0, 300.0)
RATE_WINDOWS = (30.0, 60.0, 300.0)
ACI_WINDOWS = (60.0, 300.0)
RET_WINDOWS = (60.0, 300.0, 900.0, 3600.0)
ACCEL_EPS = 1.0 / 300.0
BIG_WINDOW_S = 300.0
BIG_MEDIAN_LOOKBACK_S = 3600.0
BIG_SIZE_MULTIPLE = 5.0
HX_TIMESCALES_S = (10.0, 60.0)

PRICE_FEATURES = (
    "rem_frac", "rem_s", "is_15m", "d_bps", "gap_bps",
    "ret_60", "ret_300", "ret_900", "ret_3600", "vol_fast", "vol_slow",
)
FLOW_FEATURES = (
    "ofi_30", "ofi_60", "ofi_120", "ofi_300", "ofi_900",
    "sv_60", "sv_300",
    "rate_30", "rate_60", "rate_300", "accel",
    "aci_60", "aci_300", "mo_frac_300",
    "big_ratio_300", "big_count_300",
    "hx_10", "hx_60",
)
ALL_FEATURES = PRICE_FEATURES + FLOW_FEATURES

FEATURE_SETS = {
    "P": PRICE_FEATURES,
    "F": FLOW_FEATURES,
    "P+F": ALL_FEATURES,
}


def make_excitations(tape: FlowTape) -> tuple[Excitation, Excitation]:
    return tuple(Excitation(tape.times, 1.0 / ts) for ts in HX_TIMESCALES_S)


def flow_features(tape: FlowTape, excitations: tuple[Excitation, ...], t: float) -> dict:
    """The FLOW set at instant t — total functions of the strictly-before-t tape."""
    out: dict[str, float] = {}
    for w in OFI_WINDOWS:
        s = tape.window_sums(t, w)
        out[f"ofi_{w:.0f}"] = s["signedVol"] / s["vol"] if s["vol"] > 0 else 0.0
    for w in SV_WINDOWS:
        out[f"sv_{w:.0f}"] = asinh(tape.window_sums(t, w)["signedVol"])
    rates = {}
    for w in RATE_WINDOWS:
        rates[w] = tape.window_sums(t, w)["count"] / w
        out[f"rate_{w:.0f}"] = rates[w]
    out["accel"] = log((rates[30.0] + ACCEL_EPS) / (rates[300.0] + ACCEL_EPS))
    for w in ACI_WINDOWS:
        s = tape.window_sums(t, w)
        out[f"aci_{w:.0f}"] = (2 * s["buys"] - s["count"]) / s["count"] if s["count"] else 0.0
    s300 = tape.window_sums(t, BIG_WINDOW_S)
    out["mo_frac_300"] = s300["marketOrders"] / s300["count"] if s300["count"] else 0.0
    recent = tape.sizes_in(t, BIG_WINDOW_S)
    lookback = tape.sizes_in(t, BIG_MEDIAN_LOOKBACK_S)
    med = median(lookback) if lookback else 0.0
    if recent and med > 0:
        out["big_ratio_300"] = log(1.0 + max(recent) / med)
        cut = BIG_SIZE_MULTIPLE * med
        out["big_count_300"] = float(sum(1 for s in recent if s >= cut))
    else:
        out["big_ratio_300"] = 0.0
        out["big_count_300"] = 0.0
    for ts, exc in zip(HX_TIMESCALES_S, excitations, strict=True):
        out[f"hx_{ts:.0f}"] = exc.at(t)
    return out


def price_features(tape: FlowTape, t: float) -> dict | None:
    """Returns and vols at t (strictly-before anchors); None when any anchor is absent."""
    p_now = tape.price_before(t)
    if p_now is None or p_now <= 0:
        return None
    out: dict[str, float] = {}
    for w in RET_WINDOWS:
        p_then = tape.price_before(t - w)
        if p_then is None or p_then <= 0:
            return None
        out[f"ret_{w:.0f}"] = log(p_now / p_then) * 1e4
    fast = _grid_vol_bps(tape, t, lookback_s=120.0, step_s=5.0)
    slow = _grid_vol_bps(tape, t, lookback_s=600.0, step_s=30.0)
    if fast is None or slow is None:
        return None
    out["vol_fast"] = fast
    out["vol_slow"] = slow
    return out


def _grid_vol_bps(tape: FlowTape, t: float, *, lookback_s: float, step_s: float) -> float | None:
    points = []
    s = t - lookback_s
    while s <= t + 1e-9:
        p = tape.price_before(s)
        if p is None or p <= 0:
            return None
        points.append(p)
        s += step_s
    rets = [log(points[i + 1] / points[i]) * 1e4 for i in range(len(points) - 1)]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    return sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
