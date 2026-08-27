"""The four candidate settlement rules and the step-0 ground-truth gate.

The gate is the whole point: only a rule that reproduces the REAL settlements (the
collector's terminal-pricing labels) may be counted at scale. If none does, counting would
be counting the wrong thing, and the registered outcome is STOP.
"""

from __future__ import annotations

from .finesol import StepSeries

RULES = ("a", "b", "c", "d")
RULE_TEXT = {
    "a": "whole-window TWAP >= p(open)",
    "b": "twap60(close) >= twap60(open)",
    "c": "p(close) >= p(open)",
    "d": "whole-window TWAP >= twap60(open)",
}
# Fixed by registration: mechanical plausibility, not score.
PRECEDENCE = ("b", "a", "d", "c")
QUALIFY_FRACTION = 0.90


def start_ref(series: StepSeries, t_open: float, rule: str) -> float | None:
    """The rule's start reference: p(open) for a/c, twap60(open) for b/d."""
    if rule in ("a", "c"):
        return series.price_at(t_open)
    return series.twap(t_open - 60.0, t_open)


def final_value(series: StepSeries, t_open: float, t_close: float, rule: str) -> float | None:
    """The rule's end-side value compared against the start reference."""
    if rule in ("a", "d"):
        return series.twap(t_open, t_close)
    if rule == "b":
        return series.twap(t_close - 60.0, t_close)
    return series.price_at(t_close)


def final_margin_bps(series: StepSeries, t_open: float, t_close: float, rule: str) -> float | None:
    """Signed bps of (end-side value vs start reference); None when data-absent."""
    ref = start_ref(series, t_open, rule)
    val = final_value(series, t_open, t_close, rule)
    if ref is None or val is None or ref <= 0:
        return None
    return (val - ref) / ref * 1e4


def settle_up(series: StepSeries, t_open: float, t_close: float, rule: str) -> bool | None:
    """The reconstructed settlement: ties -> Up; None when data-absent."""
    m = final_margin_bps(series, t_open, t_close, rule)
    return None if m is None else m >= 0.0


def gate(
    series_by_venue: dict[str, StepSeries],
    labeled: list[tuple[str, int, int, str]],
) -> dict:
    """Score every rule against every real label on every venue; apply the registered verdict.

    ``labeled`` rows: (event_id, window_open_s, window_close_s, "Up"/"Down").
    """
    scores: dict[str, dict[str, dict]] = {}
    for venue, series in series_by_venue.items():
        scores[venue] = {}
        for rule in RULES:
            matches = total = 0
            rows = []
            for event_id, t_open, t_close, actual in labeled:
                recon = settle_up(series, float(t_open), float(t_close), rule)
                margin = final_margin_bps(series, float(t_open), float(t_close), rule)
                if recon is None:
                    rows.append({"eventId": event_id, "actual": actual, "recon": "data-absent"})
                    continue
                total += 1
                recon_label = "Up" if recon else "Down"
                if recon_label == actual:
                    matches += 1
                rows.append(
                    {
                        "eventId": event_id,
                        "actual": actual,
                        "recon": recon_label,
                        "marginBps": margin,
                        "match": recon_label == actual,
                    }
                )
            scores[venue][rule] = {
                "ruleText": RULE_TEXT[rule],
                "matches": matches,
                "total": total,
                "fraction": (matches / total) if total else None,
                "rows": rows,
            }

    def qualifies(venue: str, rule: str) -> bool:
        s = scores.get(venue, {}).get(rule)
        return bool(
            s and s["total"] and s["fraction"] is not None and s["fraction"] >= QUALIFY_FRACTION
        )

    verdict: dict = {"decision": "STOP", "rule": None}
    kraken_ok = [r for r in PRECEDENCE if qualifies("kraken", r)]
    if not kraken_ok:
        coinbase_ok = [r for r in PRECEDENCE if qualifies("coinbase", r)]
        verdict["reason"] = "no rule reproduces >=90% of real settlements on the kraken series" + (
            f"; {coinbase_ok} qualify on coinbase -> kraken resolution failure"
            if coinbase_ok
            else "; none qualifies on coinbase either -> rule or reference is wrong"
        )
    else:
        chosen = None
        for rule in kraken_ok:
            cb = scores.get("coinbase", {}).get(rule)
            cb_computable = bool(cb and cb["total"])
            if not cb_computable or qualifies("coinbase", rule):
                chosen = rule
                break
        if chosen is None:
            verdict["reason"] = (
                f"rules {kraken_ok} qualify on kraken but each fails the coinbase cross-check"
            )
        else:
            verdict = {"decision": "PROCEED", "rule": chosen, "ruleText": RULE_TEXT[chosen]}
    return {"scores": scores, "verdict": verdict, "labels": len(labeled)}
