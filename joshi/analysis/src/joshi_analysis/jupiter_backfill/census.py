"""The opportunity census on backfilled rounds — decision-time causal, no hindsight.

Registered frame: jupiter_conditional REGISTRATION.md amendment v1.3 (three strategy
types; RATE + EDGE SIZE + REALIZED P&L incl. losers, regime-split, fee floor beside,
fillability stated). This pass replaces the oracle-window leg-in bound (legin.py) with
DECISION-TIME rules: at every candidate moment t, only information at or before t is
used; every position is then scored by the round's REAL settlement label.

MECHANICAL RULES, FIXED HERE BEFORE THE RUN (no tuning after seeing results):

1. NEAR-BOUNDARY FADE. At the registered remaining-fraction grid (state.REMAINING_
   FRACTIONS), the causal state d(t) comes from the Kraken reference (jupiter_conditional
   decision_state, gated rule); the model P(up) is the A-surface prediction
   (surface.predict, registered fallbacks). The takeable price of a side at t is its
   LAST FILL at or before t, at most QUOTE_STALE_S old (no fill that fresh = no quote =
   no setup; counted). Flag iff model P(side) - q - fee(q) > 0. The position rule takes
   the FIRST flagged setup per round (larger edge on a same-instant tie), 1 contract.
   Causality: each horizon scores ONLY rounds starting at/after that horizon's A/B
   temporal cutoff — the surface is counted strictly before every scored round.

2. LEG-IN, decision-time. In-window fills, ascending. Leg 1: the first fill (either
   side) priced <= X buys that side at that price. Leg 2: the first STRICTLY LATER fill
   on the other side priced <= Y buys it. Both legs -> book pays exactly $1: P&L =
   1 - (q1 + q2 + fees), locked iff positive. No leg 2 -> NAKED: P&L = settle(side1)
   - q1 - fee. Trigger pairs (X, Y), fixed: (0.15, 0.75), (0.25, 0.65), (0.35, 0.55),
   (0.45, 0.45). The oracle bound is recomputed on the same rounds for the
   hindsight-vs-decision-time gap.

3. BUY-AHEAD. Pre-window fills (t < windowStart) priced inside the stale band
   [0.40, 0.60]. Regime at fill time = trailing-1h Kraken return (registered ±50 bps
   bands). The rule buys the trend-ALIGNED side on the first in-band pre-window fill in
   a trend regime; counter-trend takes and the flat-regime pool are reported as
   contrast, never pooled in.

HONESTY (permanent): fills are realistic TRANSACTED prices, never guaranteed fillable
size; taking the last fill as the takeable price is a price approximation (the book may
have moved). The Kraken reference is a ~2 bp venue-basis approximation of the Chainlink
settlement stream. Fee = 0.070·q(1-q) per leg (corroborated by the venue's own
feeSchedule); the round-up-to-cent rider is stated, not applied; spread/overround riders
sit on top. Data-absent moments and no-quote moments are counted, never imputed.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from joshi_analysis.jupiter_base_rate.study import wilson_95
from joshi_analysis.jupiter_conditional import finesol, surface
from joshi_analysis.jupiter_conditional.__main__ import run_gate
from joshi_analysis.jupiter_conditional.state import (
    REMAINING_FRACTIONS,
    decision_states,
    regime,
)

from . import reads
from .legin import MIN_SIDE_OBS, fee

STATE = Path("~/dev/joshi/state/prediction")
QUOTE_STALE_S = 60.0
LEG_PAIRS = ((0.15, 0.75), (0.25, 0.65), (0.35, 0.55), (0.45, 0.45))
AHEAD_BAND = (0.40, 0.60)
FLIP_FRACTIONS = (0.2, 0.15, 0.1, 0.05)
HORIZON_S = {"5m": 300, "15m": 900}


@dataclass(frozen=True)
class Round:
    key: str
    horizon: str
    open_s: int
    close_s: int
    label: str  # "Up" | "Down"
    rows: tuple  # slim fills [t, outcomeIndex, price, size, side], ascending t

    @property
    def up_won(self) -> bool:
        return self.label == "Up"

    def side_won(self, side: int) -> bool:
        return self.up_won if side == 0 else not self.up_won


def load_labeled_rounds(paths: list[Path]) -> list[Round]:
    out: dict[str, Round] = {}
    for path in paths:
        for rec in reads.load_rounds(path):
            label = (rec.get("settlement") or {}).get("label")
            if label not in ("Up", "Down"):
                continue
            out[rec["roundKey"]] = Round(
                key=rec["roundKey"],
                horizon=rec["horizon"],
                open_s=rec["windowStartUnix"],
                close_s=rec["closeTimeUnix"],
                label=label,
                rows=tuple(rec.get("trades", {}).get("rows") or []),
            )
    return sorted(out.values(), key=lambda r: (r.horizon, r.open_s))


def last_fill_at(rows: tuple, side: int, t: float, stale_s: float = QUOTE_STALE_S):
    """The side's most recent fill price at/before t, if fresh enough. Causal by index."""
    times = [r[0] for r in rows]
    i = bisect_right(times, t) - 1
    while i >= 0:
        row = rows[i]
        if t - row[0] > stale_s:
            return None
        if row[1] == side and row[2] is not None:
            return float(row[2])
        i -= 1
    return None


def position_pnl(q: float, won: bool) -> float:
    return (1.0 if won else 0.0) - q - fee(q)


# ---------------------------------------------------------------- strategy 1: fade
def fade_edges(p_up: float, q_up: float | None, q_down: float | None) -> list[dict]:
    """Net edges of buying each side at its takeable price against the model P. Pure."""
    out = []
    for side, p_s, q in ((0, p_up, q_up), (1, 1.0 - p_up, q_down)):
        if q is None:
            continue
        edge = p_s - q - fee(q)
        out.append({"side": side, "q": q, "modelP": p_s, "edgeNet": edge})
    return out


def fade_round(
    rnd: Round, series, rule: str, ctx: dict, stale_s: float = QUOTE_STALE_S
) -> dict:
    states = decision_states(series, float(rnd.open_s), float(rnd.close_s), rule)
    setups = []
    absent = len(REMAINING_FRACTIONS) - len(states)
    no_quote = 0
    for st in states:
        p_up = surface.predict(ctx["surface"], ctx["marginal"], ctx["base_rate"], st)
        q_up = last_fill_at(rnd.rows, 0, st.t, stale_s)
        q_down = last_fill_at(rnd.rows, 1, st.t, stale_s)
        if q_up is None and q_down is None:
            no_quote += 1
            continue
        for e in fade_edges(p_up, q_up, q_down):
            if e["edgeNet"] > 0.0:
                setups.append(
                    {**e, "t": st.t, "remainingFraction": st.remaining_fraction,
                     "dBps": st.d_bps, "flip": st.remaining_fraction in FLIP_FRACTIONS}
                )
    first = None
    if setups:
        first = min(setups, key=lambda s: (s["t"], -s["edgeNet"]))
        first = {**first, "pnl": position_pnl(first["q"], rnd.side_won(first["side"]))}
    return {"setups": setups, "first": first, "statesAbsent": absent, "noQuote": no_quote}


# ---------------------------------------------------------------- strategy 2: leg-in
def leg_in_causal(rnd: Round, x: float, y: float) -> dict:
    """The decision-time leg-in walk. Pure; in-window fills only; leg 2 strictly later."""
    in_window = [r for r in rnd.rows if rnd.open_s <= r[0] < rnd.close_s and r[2] is not None]
    leg1 = next((r for r in in_window if float(r[2]) <= x), None)
    if leg1 is None:
        return {"outcome": "no-trigger"}
    t1, s1, q1 = leg1[0], int(leg1[1]), float(leg1[2])
    leg2 = next(
        (r for r in in_window if r[0] > t1 and int(r[1]) != s1 and float(r[2]) <= y),
        None,
    )
    if leg2 is None:
        pnl = position_pnl(q1, rnd.side_won(s1))
        return {"outcome": "naked", "side": s1, "q1": q1, "pnl": pnl}
    q2 = float(leg2[2])
    combined_net = q1 + fee(q1) + q2 + fee(q2)
    return {
        "outcome": "completed",
        "q1": q1,
        "q2": q2,
        "combinedNet": combined_net,
        "locked": combined_net < 1.0,
        "pnl": 1.0 - combined_net,
    }


def oracle_lock(rnd: Round) -> bool | None:
    """The hindsight bound on the same fills (legin.py semantics), for the gap number."""
    ups = [float(r[2]) for r in rnd.rows
           if rnd.open_s <= r[0] < rnd.close_s and r[1] == 0 and r[2] is not None]
    downs = [float(r[2]) for r in rnd.rows
             if rnd.open_s <= r[0] < rnd.close_s and r[1] == 1 and r[2] is not None]
    if len(ups) < MIN_SIDE_OBS or len(downs) < MIN_SIDE_OBS:
        return None
    mu, md = min(ups), min(downs)
    return mu + fee(mu) + md + fee(md) < 1.0


# ---------------------------------------------------------------- strategy 3: buy-ahead
def buy_ahead_take(rnd: Round, series) -> dict:
    """First pre-window in-band fill on the trend-aligned side; contrasts recorded. Pure
    given the reference series (regime at fill time is trailing-1h, causal)."""
    takes: dict[str, dict | None] = {"aligned": None, "against": None}
    flat = 0
    no_regime = 0
    lo, hi = AHEAD_BAND
    for r in rnd.rows:
        if r[0] >= rnd.open_s or r[2] is None or not (lo <= float(r[2]) <= hi):
            continue
        reg = regime(series, float(r[0]))
        if reg is None:
            no_regime += 1
            continue
        if reg == "flat":
            flat += 1
            continue
        aligned_side = 0 if reg == "up" else 1
        side, q = int(r[1]), float(r[2])
        kind = "aligned" if side == aligned_side else "against"
        if takes[kind] is None:
            takes[kind] = {
                "t": r[0], "side": side, "q": q, "regime": reg,
                "aheadS": rnd.open_s - r[0],
                "pnl": position_pnl(q, rnd.side_won(side)),
            }
    return {"takes": takes, "flatFills": flat, "noRegimeFills": no_regime}


# ---------------------------------------------------------------- aggregation
def pnl_block(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0}
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": len(pnls),
        "totalPnl": sum(pnls),
        "meanPnl": sum(pnls) / len(pnls),
        "winners": wins,
        "losers": len(pnls) - wins,
        "quantiles": _quantiles(pnls),
    }


def _quantiles(vals: list[float]) -> dict:
    s = sorted(vals)
    return {
        f"p{int(q * 100)}": s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]
        for q in (0.10, 0.25, 0.50, 0.75, 0.90)
    }


def by_regime(rows: list[tuple[str, float]]) -> dict:
    out: dict[str, list[float]] = {}
    for reg, pnl in rows:
        out.setdefault(reg, []).append(pnl)
    return {reg: pnl_block(v) for reg, v in sorted(out.items())}


def main() -> None:
    ap = argparse.ArgumentParser(prog="joshi_analysis.jupiter_backfill.census")
    ap.add_argument("--rounds", type=Path, nargs="+", required=True)
    ap.add_argument("--fine", type=Path, default=STATE / "fine")
    ap.add_argument("--collect", type=Path, default=STATE)
    ap.add_argument("--out-dir", type=Path, default=STATE / "study")
    ap.add_argument(
        "--quote-stale-s", type=float, default=QUOTE_STALE_S,
        help="fade takeable-quote staleness cap; 60 is the registered default, other "
             "values are SENSITIVITY runs (stated in the output)",
    )
    args = ap.parse_args()

    gate_report = run_gate(args.fine, args.collect)
    if gate_report["verdict"]["decision"] != "PROCEED":
        print("GATE SAYS STOP — the census would count the wrong thing. Not counting.")
        return
    rule = gate_report["verdict"]["rule"]
    series = finesol.load_kraken(args.fine)
    rounds = load_labeled_rounds(args.rounds)
    contexts = {h: surface.build_context(series, HORIZON_S[h], rule) for h in HORIZON_S}
    cutoffs = {
        h: (min((w.t_open for w in ctx["set_b"]), default=None))
        for h, ctx in contexts.items()
    }
    round_regime = {r.key: regime(series, float(r.open_s)) or "absent" for r in rounds}

    result: dict = {
        "contract": "joshi.jupiter_backfill.census.v1",
        "registration": "joshi.jupiter_conditional.registration.v1 amendment v1.3",
        "rule": rule,
        "computedFrom": [str(p) for p in args.rounds],
        "gateLabels": gate_report["labels"],
        "quoteStaleSeconds": args.quote_stale_s,
        "quoteStaleNote": (
            "registered default 60s"
            if args.quote_stale_s == QUOTE_STALE_S
            else f"SENSITIVITY run at {args.quote_stale_s}s (registered default 60s)"
        ),
        "feePerLeg": "0.070*q*(1-q) explicit taker fee; round-up-to-cent rider stated"
                     " not applied; spread/overround riders on top",
        "feeFloorMidpointUsd": 0.0175,
        "caveats": [
            "fills = realistic transacted prices, NEVER guaranteed fillable size",
            "takeable price at t = last fill <= 60s old: a price approximation",
            "Kraken reference ~2bp venue basis vs the Chainlink settlement stream",
            "every provider price/timestamp is a provider claim in declared units",
        ],
    }

    # ---- strategy 1
    fade_out: dict = {}
    for h in HORIZON_S:
        cut = cutoffs[h]
        scored = [r for r in rounds if r.horizon == h and cut and r.open_s >= cut]
        per = [
            (r, fade_round(r, series, rule, contexts[h], args.quote_stale_s))
            for r in scored
        ]
        all_setups = [s for _, f in per for s in f["setups"]]
        firsts = [(r, f["first"]) for r, f in per if f["first"]]
        span_h = ((max(r.close_s for r in scored) - min(r.open_s for r in scored)) / 3600
                  if scored else 0)
        fade_out[h] = {
            "aBCutoffUnix": cut,
            "scoredRounds": len(scored),
            "spanHours": span_h,
            "statesAbsent": sum(f["statesAbsent"] for _, f in per),
            "noQuoteStates": sum(f["noQuote"] for _, f in per),
            "setupStates": len(all_setups),
            "setupStatesFlipZone": sum(1 for s in all_setups if s["flip"]),
            "roundsWithSetup": len(firsts),
            "roundsWithSetupPerHour": len(firsts) / span_h if span_h else None,
            "edgeNetQuantiles": _quantiles([s["edgeNet"] for s in all_setups])
            if all_setups else {},
            "realized": pnl_block([f["pnl"] for _, f in firsts]),
            "realizedByRegime": by_regime(
                [(round_regime[r.key], f["pnl"]) for r, f in firsts]
            ),
            "positionRule": "first flagged setup per round, 1 contract",
        }
    result["nearBoundaryFade"] = fade_out

    # ---- strategy 2
    leg_out: dict = {}
    for h in HORIZON_S:
        rs = [r for r in rounds if r.horizon == h]
        oracle = [oracle_lock(r) for r in rs]
        oracle_known = [o for o in oracle if o is not None]
        pairs_out = {}
        for x, y in LEG_PAIRS:
            walks = [(r, leg_in_causal(r, x, y)) for r in rs]
            trig = [(r, w) for r, w in walks if w["outcome"] != "no-trigger"]
            comp = [(r, w) for r, w in trig if w["outcome"] == "completed"]
            naked = [(r, w) for r, w in trig if w["outcome"] == "naked"]
            locked = [w for _, w in comp if w["locked"]]
            pnls = [(round_regime[r.key], w["pnl"]) for r, w in trig]
            pairs_out[f"x{x:.2f}-y{y:.2f}"] = {
                "rounds": len(rs),
                "triggered": len(trig),
                "completed": len(comp),
                "naked": len(naked),
                "trueLockRounds": len(locked),
                "trueLockRateOfRounds": len(locked) / len(rs) if rs else None,
                "trueLockRateOfTriggered": len(locked) / len(trig) if trig else None,
                "nakedPnl": pnl_block([w["pnl"] for _, w in naked]),
                "realized": pnl_block([p for _, p in pnls]),
                "realizedByRegime": by_regime(pnls),
            }
        leg_out[h] = {
            "pairs": pairs_out,
            "oracleLockRate": (sum(oracle_known) / len(oracle_known))
            if oracle_known else None,
            "oracleCovered": len(oracle_known),
            "hindsightNote": "oracleLockRate is the legin.py min-over-window bound on the"
                             " SAME rounds; the gap to trueLockRate* is hindsight",
        }
    result["legIn"] = leg_out

    # ---- strategy 3
    ahead_out: dict = {}
    for h in HORIZON_S:
        rs = [r for r in rounds if r.horizon == h]
        per = [(r, buy_ahead_take(r, series)) for r in rs]
        aligned = [(r, b["takes"]["aligned"]) for r, b in per if b["takes"]["aligned"]]
        against = [(r, b["takes"]["against"]) for r, b in per if b["takes"]["against"]]
        covered_hours = sum(
            1 for r in rs
            if any(row[0] < r.open_s for row in r.rows)
        )
        span_h = ((max(r.close_s for r in rs) - min(r.open_s for r in rs)) / 3600
                  if rs else 0)
        ahead_out[h] = {
            "rounds": len(rs),
            "roundsWithAnyPreWindowFill": covered_hours,
            "spanHours": span_h,
            "alignedTakes": len(aligned),
            "alignedTakesPerHour": len(aligned) / span_h if span_h else None,
            "alignedRealized": pnl_block([t["pnl"] for _, t in aligned]),
            "alignedByRegime": by_regime(
                [(t["regime"], t["pnl"]) for _, t in aligned]
            ),
            "alignedWinRate": (
                {
                    "wins": sum(1 for _, t in aligned if t["pnl"] > 0),
                    "n": len(aligned),
                    "wilson95": list(
                        wilson_95(sum(1 for _, t in aligned if t["pnl"] > 0),
                                  len(aligned)) or []
                    ),
                }
                if aligned else None
            ),
            "againstContrast": pnl_block([t["pnl"] for _, t in against]),
            "flatFillsSkipped": sum(b["flatFills"] for _, b in per),
            "noRegimeFillsSkipped": sum(b["noRegimeFills"] for _, b in per),
            "band": list(AHEAD_BAND),
        }
    result["buyAhead"] = ahead_out

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = reads.utc_stamp()
    out = args.out_dir / f"backfill-census-{stamp}.json"
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
