"""Crime detection: is this price path manufactured, and should we be getting out?

The operator's description of the pattern, verbatim:

    "'criming' a token... one thing i've seen is a token that shoots to millions mcap,
    crawls ~linearly up to 20M with small amount of real trading activity (extremely
    small) and then the rug rips."

This module is the **production** half. It holds the pure functions — features, calibration,
score, the mechanical rip label, the alert row — and nothing that needs a network, a cohort
or a research dependency. ``studies/crime_signatures.py`` imports from here rather than
reimplementing, so the thing that was measured and the thing that runs are the same code.

The direction of the signal is fixed and non-negotiable
-------------------------------------------------------
Every alert this module emits carries ``action: "reduce"``. A high crime score is a reason
to leave, never a reason to arrive. The temptation to invert it — "if I can spot the
manufactured pump early I can ride it" — is the exact trade this detector exists to make
harder, because the pattern's defining feature is that the exit is controlled by somebody
else. The score is an estimate of *how thoroughly somebody else owns the order book*.

Why price alone can carry the signal — the conservation law
-----------------------------------------------------------
In the project's circuit frame (``PROGRAM.md`` §8, formalised in
``studies/RESULT_circuit_model.md``) a CFMM pool is a nonlinear capacitor: reserves are
charge, marginal price is voltage, and ``C = w_x·w_y·TVL`` exactly. So

    ΔV = ΔQ / C

is an identity, not a model: **the price cannot move without flow through the curve.** A
climb on tiny volume is therefore not a description of sentiment, it is a statement that
either the flow is being supplied by someone who gets it back (self-matching), or supply is
being metered by a controller who is the only seller. Both are adversarial, and both are
measurable from price and volume alone.

The four signatures
-------------------
S1 **displacement decoupled from flow** — ``|Δ ln p| / turnover``. Large means each dollar
   of volume moved the price further than the ambient market's dollar does.
S2 **linearity** — a schedule is a straight line. Rolling R² against wall clock, drift/vol
   ratio, and the *regularity of the flow itself* (CV of hourly volume; CV of inter-trade
   gaps where a swap tape exists, whose reference value is 1.0 for a memoryless process and
   needs no fitting).
S3 **concentration and choreography** — needs signers, so it lives in the study where the
   cluster tape does. It is deliberately **not** part of the score: it is measurable on
   eleven pools and would not generalise.
S4 **the terminal event** — :func:`find_rip`, an *irreversible* collapse. Post-mortem by
   construction (it needs a forward window), which is exactly why it is a label and not a
   feature.

Thresholds
----------
Nothing here asserts a level. :class:`Calibration` turns every feature into a percentile of
an ambient population fitted elsewhere, so the score is unit-free and re-calibrates as the
regime moves. The only fixed numbers in this file are the rip label's, and those are
reported against their measured distribution in ``studies/RESULT_crime_signatures.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "ALERTS_PATH",
    "ALERT_KINDS",
    "DEFAULT_WINDOW",
    "FEATURE_KEYS",
    "SCHEMA",
    "SCORE_KEYS",
    "Bar",
    "Calibration",
    "Series",
    "alert_id",
    "alert_row",
    "append_rows",
    "crime_score",
    "defect_row",
    "features_at",
    "find_rip",
    "heartbeat_row",
    "linreg_r2",
    "new_run_id",
    "score_series",
]

HOUR = 3600.0

#: 48 hours. Two days is the shortest window in which "crawls linearly" is a statement
#: about a path rather than about noise, and the longest that still leaves useful lead time
#: on a coin whose whole life is a week. It is a parameter everywhere it is used.
DEFAULT_WINDOW = 48


@dataclass(frozen=True, slots=True)
class Bar:
    """One hourly bar. ``t`` is the **vendor's** clock (candle open, unix seconds)."""

    t: int
    open: float
    high: float
    low: float
    close: float
    volume_usd: float


@dataclass(slots=True)
class Series:
    """A regular hourly grid for one pool, ascending in time.

    The grid is *regular*: an hour with no trades is present with the previous close and
    zero volume. That is a measured zero and not a missing observation — collapsing those
    hours would delete exactly the "extremely small trading activity" the pattern is made
    of. Callers that cannot distinguish "no trades" from "not watching" must say so; this
    class assumes the former, which is true of an exchange's own candle feed.
    """

    pool: str
    mint: str
    symbol: str | None
    bars: list[Bar]
    supply: float | None = None

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def t(self) -> list[int]:
        return [b.t for b in self.bars]

    @property
    def close(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def vol(self) -> list[float]:
        return [b.volume_usd for b in self.bars]

    def mcap(self, i: int) -> float | None:
        return None if self.supply is None else self.supply * self.bars[i].close

    @classmethod
    def from_ohlcv(cls, pool: str, mint: str, symbol: str | None,
                   rows: Sequence[Sequence[float]], supply: float | None = None,
                   max_hours: int = 4000) -> "Series | None":
        """Build from GeckoTerminal-shaped ``[ts, o, h, l, c, vol]`` rows, in any order."""

        rows = sorted((r for r in rows if r and len(r) >= 6), key=lambda r: r[0])
        if len(rows) < 2:
            return None
        by_t = {int(r[0]): r for r in rows}
        t0, t1 = int(rows[0][0]), int(rows[-1][0])
        if (t1 - t0) // 3600 + 1 > max_hours:
            return None
        bars: list[Bar] = []
        last = float(rows[0][4])
        for ti in range(t0, t1 + 1, 3600):
            r = by_t.get(ti)
            if r is None:
                bars.append(Bar(ti, last, last, last, last, 0.0))
                continue
            last = float(r[4])
            bars.append(Bar(ti, float(r[1]), float(r[2]), float(r[3]), last, float(r[5])))
        return cls(pool=pool, mint=mint, symbol=symbol, bars=bars, supply=supply)


# ---------------------------------------------------------------------------------------
# S4 — the terminal event
# ---------------------------------------------------------------------------------------
#
# `config.yaml`'s rug_detector names thresholds somebody already chose — a 40% liquidity
# drop, a 20% quote collapse, 5% mint-supply growth. Those are *live* thresholds on
# quantities with no keyless history (`studies/RESULT_deterioration.md` §2.1), so they
# cannot label a historical cohort. The label below is re-derived from price and volume and
# the config's numbers are reported against its measured distribution rather than adopted.
#
# The defining property is IRREVERSIBILITY, because that is what matters to somebody holding
# the bag: a drop that stays down. That clause needs a forward window, so the label is a
# post-mortem and the score is not. The asymmetry is the point.

RIP_DROP = 0.60        #: peak-to-trough fall inside the window
RIP_WINDOW_H = 6       #: hours the fall may take
RIP_HOLD_H = 24        #: hours it must stay down afterwards
RIP_RECOVER = 0.40     #: "stays down" — never recovers past this fraction of the pre-rip level
RIP_BASE_H = 6         #: hours the pre-rip level must have been sustained
RIP_STILL_UP = 0.90    #: "still at the pre-rip level" — within this fraction of the reference


def find_rip(s: Series, *, drop: float = RIP_DROP, window_h: int = RIP_WINDOW_H,
             hold_h: int = RIP_HOLD_H, recover: float = RIP_RECOVER,
             base_h: int = RIP_BASE_H, still_up: float = RIP_STILL_UP) -> dict | None:
    """First irreversible collapse, or ``None``.

    The returned ``i`` is the **last hour at which the price was still up** — the last
    moment an exit was possible at the pre-rip price. Every lead time in this study is
    measured against it, which is the conservative choice: measuring against the trough
    would credit the detector for hours during which the price was already gone.

    The refinement step earns its place. A naive scan reports the *earliest* hour from which
    a 60% fall is reachable inside the window, which on a flat-then-cliff path is up to
    ``window_h`` hours before anything happened — the label would sit on a bar where the
    coin was still at its high. A test on a synthetic cliff caught it firing five hours
    early. So once a candidate fall is found, the reference hour is walked forward to the
    last bar still within ``still_up`` of the pre-fall level, and the conditions are
    re-checked against that bar.
    """

    c = s.close
    n = len(c)
    for i in range(n - 1):
        ref = c[i]
        if ref <= 0:
            continue
        trough, trough_j = ref, None
        for j in range(i + 1, min(n, i + window_h + 1)):
            if c[j] < trough:
                trough, trough_j = c[j], j
        if trough_j is None or trough > ref * (1 - drop):
            continue
        # Walk the reference forward to the last bar that was still up.
        k = i
        for m in range(i, trough_j):
            if c[m] >= ref * still_up:
                k = m
        ref2 = c[k]
        if trough > ref2 * (1 - drop):
            continue
        tail = c[trough_j : min(n, trough_j + hold_h + 1)]
        if not tail or max(tail) > ref2 * recover:
            continue
        # `ref2` must be a level, not the tip of a spike we are watching retrace.
        base = c[max(0, k - base_h) : k + 1]
        if statistics.median(base) < ref2 * 0.5:
            continue
        return {
            "i": k, "t_event": s.bars[k].t,
            "ref_price": ref2, "trough_price": trough, "trough_i": trough_j,
            "fall_hours": trough_j - k, "fall_pct": trough / ref2 - 1.0,
            "ref_mcap": s.mcap(k),
            "thresholds": {"drop": drop, "window_h": window_h, "hold_h": hold_h,
                           "recover": recover, "base_h": base_h, "still_up": still_up},
        }
    return None


# ---------------------------------------------------------------------------------------
# S1 / S2 — the in-flight feature set
# ---------------------------------------------------------------------------------------
#
# Every function here takes a RIGHT EDGE and cannot see past it. That is what makes this a
# detector rather than a post-mortem, and it is enforced by the signatures rather than by
# anybody remembering to be careful.


def linreg_r2(ys: Sequence[float]) -> tuple[float, float]:
    """R² and slope of ``y`` against its own index."""

    n = len(ys)
    if n < 3:
        return 0.0, 0.0
    mx = (n - 1) / 2.0
    my = sum(ys) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (ys[i] - my) for i in range(n))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0, 0.0
    return max(0.0, min(1.0, (sxy * sxy) / (sxx * syy))), sxy / sxx


def features_at(s: Series, i: int, win: int = DEFAULT_WINDOW) -> dict | None:
    """Every feature, computed from ``s[:i+1]`` only. ``None`` when the window is short."""

    if i < win or i >= len(s):
        return None
    lo = i - win + 1
    c = s.close[lo : i + 1]
    v = s.vol[lo : i + 1]
    if min(c) <= 0:
        return None
    lc = [math.log(x) for x in c]
    rets = [lc[k] - lc[k - 1] for k in range(1, len(lc))]
    if not rets:
        return None

    mcap = s.mcap(i)
    disp = lc[-1] - lc[0]
    path = sum(abs(r) for r in rets)
    vol_usd = sum(v)
    rv = math.sqrt(sum(r * r for r in rets) / len(rets))

    # S1. Turnover is volume as a fraction of market cap — the share of the float that
    # changed hands. `disp / turnover` is ΔV per unit ΔQ made dimensionless: the circuit
    # frame's own quantity. High means the price moved further per dollar than the ambient
    # market's dollar moves it, which on a CFMM means the pool is thin, the flow is
    # one-directional, or both — and both are the setup for the rip.
    turnover = (vol_usd / mcap) if (mcap and mcap > 0) else None
    disp_per_turnover = (abs(disp) / turnover) if (turnover and turnover > 0) else None
    path_per_turnover = (path / turnover) if (turnover and turnover > 0) else None

    # S2. Two linearities, because they separate two manipulator strategies: a bot buying a
    # fixed *dollar* amount per interval walks the price up linearly in LEVEL; one buying a
    # fixed *percentage* walks it linearly in LOG. Measuring both tells them apart, and the
    # operator's sentence ("crawls ~linearly up to 20M") is a statement about level.
    r2_linear, slope_linear = linreg_r2(c)
    r2_log, _slope_log = linreg_r2(lc)
    drift_vol = (disp / (rv * math.sqrt(len(rets)))) if rv > 0 else None

    # Flow regularity. A scheduler collapses the dispersion of hourly volume; real attention
    # is bursty and fat-tailed. `top_hour_share` is the crudest and most robust version:
    # organic tapes put a large share of their volume in one hour, metered tapes do not.
    mv = vol_usd / len(v)
    var_v = statistics.pvariance(v) if len(v) > 1 else 0.0
    return {
        "i": i,
        "t_event": s.bars[i].t,
        "price": s.bars[i].close,
        "mcap": mcap,
        "win": win,
        "disp_log": disp,
        "path_log": path,
        "vol_usd": vol_usd,
        "turnover": turnover,
        "disp_per_turnover": disp_per_turnover,
        "path_per_turnover": path_per_turnover,
        "r2_linear": r2_linear,
        "r2_log": r2_log,
        "slope_linear_per_h": slope_linear,
        "drift_vol": drift_vol,
        "rv_hourly": rv,
        "fano_vol": (var_v / mv) if mv > 0 else None,
        "cv_vol": (math.sqrt(var_v) / mv) if mv > 0 else None,
        "dead_hour_frac": sum(1 for x in v if x <= 0) / len(v),
        "top_hour_share": (max(v) / vol_usd) if vol_usd > 0 else None,
        "rising": disp > 0,
    }


#: The declared feature family. Fixed before any number was looked at; used for the
#: calibration and for the multiplicity correction in the study.
FEATURE_KEYS: tuple[str, ...] = (
    "disp_per_turnover", "path_per_turnover", "r2_linear", "r2_log", "drift_vol",
    "cv_vol", "fano_vol", "top_hour_share", "dead_hour_frac", "turnover", "rv_hourly",
)

#: The score's components and their polarity. ``True`` = a high value is suspicious.
#:
#: These five, and their equal weights, were chosen from the operator's sentence *before*
#: any performance number existed, and they are not fitted. A fitted weight vector over
#: eleven features and a few dozen ripped coins is the overfit ``RESULT_bandit_search.md``
#: already paid for once (a +21.77% board-entry edge that became +0.0012 when the
#: survivorship was removed). An unweighted mean of five ranks cannot overfit; it can only
#: be right or wrong, which is the property worth having.
SCORE_KEYS: tuple[tuple[str, bool], ...] = (
    ("disp_per_turnover", True),   # S1 — displacement decoupled from flow
    ("r2_linear", True),           # S2 — the crawl is a straight line
    ("drift_vol", True),           # S2 — drift dominates noise
    ("cv_vol", False),             # S2 — flow is *too regular*
    ("top_hour_share", False),     # S2 — no bursts
)


def _pct_rank(x: float, pop: Sequence[float]) -> float:
    if not pop:
        return 0.5
    lo, hi = 0, len(pop)
    while lo < hi:
        mid = (lo + hi) // 2
        if pop[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(pop)


@dataclass
class Calibration:
    """Percentile lookups per feature, fitted on a reference population.

    No threshold in this module is asserted. Each feature becomes its rank within an ambient
    cohort, which makes the score unit-free and lets it track a regime that shifts in weeks
    (``PROGRAM.md`` §3 rule 6). A calibration is a *dated artifact*: it carries the number of
    states it saw and the time range they covered, so a consumer can refuse a stale one.
    """

    pops: dict[str, list[float]] = field(default_factory=dict)
    n: int = 0
    t_first: int | None = None
    t_last: int | None = None

    @classmethod
    def fit(cls, rows: Iterable[dict], keys: Sequence[str] = FEATURE_KEYS) -> "Calibration":
        pops: dict[str, list[float]] = {k: [] for k in keys}
        n, t0, t1 = 0, None, None
        for r in rows:
            n += 1
            t = r.get("t_event")
            if isinstance(t, (int, float)):
                t0 = int(t) if t0 is None else min(t0, int(t))
                t1 = int(t) if t1 is None else max(t1, int(t))
            for k in keys:
                x = r.get(k)
                if isinstance(x, (int, float)) and math.isfinite(x):
                    pops[k].append(float(x))
        for k in pops:
            pops[k].sort()
        return cls(pops=pops, n=n, t_first=t0, t_last=t1)

    def rank(self, key: str, x: Any) -> float | None:
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            return None
        return _pct_rank(float(x), self.pops.get(key, []))

    def quantile(self, key: str, p: float) -> float | None:
        pop = self.pops.get(key) or []
        if not pop:
            return None
        return pop[min(len(pop) - 1, max(0, int(p * len(pop))))]

    def to_json(self) -> dict:
        return {
            "n_states": self.n, "t_first": self.t_first, "t_last": self.t_last,
            "quantiles": {k: {f"{p:.2f}": self.quantile(k, p)
                              for p in (0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)}
                          for k in sorted(self.pops)},
        }

    @classmethod
    def from_json(cls, payload: dict) -> "Calibration":
        """Rehydrate from stored *quantiles*, which is lossy and says so.

        A calibration serialised as quantiles can rank a value only to the resolution of the
        stored grid. That is fine for an operating threshold and wrong for a study, so the
        study always refits from states.
        """

        pops = {k: sorted(v for v in q.values() if isinstance(v, (int, float)))
                for k, q in (payload.get("quantiles") or {}).items()}
        return cls(pops=pops, n=int(payload.get("n_states") or 0),
                   t_first=payload.get("t_first"), t_last=payload.get("t_last"))


#: A falling window with the same statistics is a controlled bleed — a different animal from
#: the manufactured ascent the operator described. It is damped rather than zeroed, because
#: "the crawl already turned over" is still information.
FALLING_DAMP = 0.5


def crime_score(feat: dict, cal: Calibration) -> dict:
    """Unweighted mean of the components' percentile ranks. ``None`` if nothing ranked."""

    parts: dict[str, float] = {}
    for key, high_is_bad in SCORE_KEYS:
        r = cal.rank(key, feat.get(key))
        if r is None:
            continue
        parts[key] = r if high_is_bad else 1.0 - r
    if not parts:
        return {"score": None, "parts": {}, "n_parts": 0}
    score = sum(parts.values()) / len(parts)
    if not feat.get("rising"):
        score *= FALLING_DAMP
    return {"score": score, "parts": parts, "n_parts": len(parts)}


def score_series(s: Series, cal: Calibration, win: int = DEFAULT_WINDOW) -> list[dict]:
    """Score every hour of a series in flight. Each row sees only its own past."""

    out = []
    for i in range(win, len(s)):
        f = features_at(s, i, win=win)
        if f is None:
            continue
        r = crime_score(f, cal)
        f["crime_score"] = r["score"]
        f["parts"] = r["parts"]
        out.append(f)
    return out


# ---------------------------------------------------------------------------------------
# The output contract
# ---------------------------------------------------------------------------------------
#
# House style, from `state/swarms/events.jsonl` (a detector firing on a coin) and
# `shitcoims_paperdesk/ledger.py`: both clocks with a mandatory `t_event_source`; a stable
# `alert_id` and a `run_id` so two runs never pool silently; every threshold that produced
# the row emitted *with* the row (PROGRAM.md §3.7); the feature values behind the score so a
# consumer can overrule it; and a `defect` kind instead of an imputed number.
#
# Consumers: the sentinel's advisory layer and the paperdesk. Neither is edited from here —
# the contract is published and they adopt it.

ALERTS_PATH = Path("state/crime/alerts.jsonl")

#: Closed set, so a consumer may switch on ``kind`` exhaustively.
ALERT_KINDS = frozenset({
    "crime_alert",   # a scored state, severity in {watch, high}
    "crime_clear",   # a previously-high coin fell back below threshold
    "defect",        # something we could not price and refused to guess at
    "watch_open", "watch_close", "heartbeat",
})

SCHEMA = "crime.alert.v1"


def new_run_id() -> str:
    return f"crime-{int(time.time())}-{os.getpid()}"


def alert_id(mint: str, t_event: int, threshold: float) -> str:
    return "ca-" + hashlib.sha256(f"{mint}|{t_event}|{threshold:.4f}".encode()).hexdigest()[:16]


def alert_row(*, run_id: str, mint: str, symbol: str | None, pool: str, feat: dict,
              threshold: float, cal: Calibration, arm: str = "live",
              p_rip_h24: float | None = None,
              t_event_source: str = "vendor:geckoterminal.ohlcv.hour") -> dict:
    """One scored alert.

    ``severity`` is a band, never a probability. ``p_rip_h24`` is the calibrated hazard and
    is populated only when an evaluation that produced one is on disk; a consumer finding it
    null must not substitute a guess.
    """

    score = feat.get("crime_score")
    return {
        "schema": SCHEMA,
        "kind": "crime_alert",
        "run_id": run_id,
        "alert_id": alert_id(mint, int(feat["t_event"]), threshold),
        "t_ingest": time.time(),
        "t_event": int(feat["t_event"]),
        "t_event_source": t_event_source,
        "mint": mint,
        "symbol": symbol,
        "pool": pool,
        "crime_score": score,
        "severity": "high" if (score is not None and score >= threshold) else "watch",
        "p_rip_h24": p_rip_h24,
        "action": "reduce",
        "arm": arm,
        "mcap_usd": feat.get("mcap"),
        "thresholds": {
            "crime_score": threshold,
            "window_hours": feat.get("win"),
            "rip_drop": RIP_DROP, "rip_window_h": RIP_WINDOW_H,
            "rip_hold_h": RIP_HOLD_H, "rip_recover": RIP_RECOVER,
        },
        "components": feat.get("parts") or {},
        "evidence": {k: feat.get(k) for k in (
            "disp_per_turnover", "r2_linear", "drift_vol", "cv_vol", "top_hour_share",
            "turnover", "dead_hour_frac", "rv_hourly", "disp_log", "vol_usd")},
        "calibration": {"n_states": cal.n, "t_first": cal.t_first, "t_last": cal.t_last,
                        "keys": [k for k, _ in SCORE_KEYS]},
    }


def defect_row(*, run_id: str, mint: str, reason: str, detail: Any = None) -> dict:
    """Something the detector could not price and refused to guess at."""

    return {
        "schema": SCHEMA, "kind": "defect", "run_id": run_id,
        "t_ingest": time.time(), "t_event": None,
        "t_event_source": "absent:local_row_has_no_source_clock",
        "mint": mint, "reason": reason, "detail": detail,
    }


def heartbeat_row(*, run_id: str, scored: int, alerts: int, watched: Sequence[str] = ()) -> dict:
    """Positive evidence of liveness. Absence of alerts means nothing without one of these."""

    return {
        "schema": SCHEMA, "kind": "heartbeat", "run_id": run_id,
        "t_ingest": time.time(), "t_event": None,
        "t_event_source": "absent:local_row_has_no_source_clock",
        "scored": scored, "alerts": alerts, "watched": list(watched),
    }


def append_rows(path: Path, rows: Iterable[dict]) -> int:
    """Append JSONL, one object per line, keys sorted. Never CSV — memecoin symbols
    contain commas, quotes and newlines by design (``PROGRAM.md`` §3.11)."""

    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return len(rows)
