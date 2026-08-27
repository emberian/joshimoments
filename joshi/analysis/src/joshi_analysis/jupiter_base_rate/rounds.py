"""Inventory of collector-captured rounds, with the stale-``isLive`` filter.

Reads ``state/prediction/collect-*.jsonl`` (the live collector's output — see
``joshi_analysis.jupiter_collect``). Two provider quirks this layer absorbs, both observed
2026-08-27:

- ``/events/search`` sometimes flags long-dead rounds as ``isLive`` (an August 5 round surfaced
  live on August 27), so the collector records a few extras. A round is **genuine** here iff its
  ``closeTime`` falls inside the collection file's own arrival span, padded by one horizon on
  each side.
- On these Polymarket-CLOB rounds ``openTime`` is the *listing* time (~24 h before close), not
  the window start; ``closeTime`` sits on the 300 s wall-clock grid. The true window is
  ``[closeTime - horizon, closeTime]`` and that is what this module reports.

One settlement inference IS made, and is labeled as one: the API keeps ``status: "open"`` and
``result: null`` even long after close (observed on a weeks-old round), so the collector's
status/result-based settlement lines cannot fire against this provider. What the API does do is
pin the winning side's post-close pricing to $1.000000 (micro-USD 1000000) and the loser's to
~$0.001 — the same inference the reconnaissance map used. ``Round.terminal_label`` reads that
pin out of post-close samples. The winner→side mapping (marketId suffix ``-0`` = Up, ``-1`` =
Down, matching the ``outcomes`` list order) is itself an inference, corroborated by a 3-of-4
reference-series spot check on 2026-08-27 settlements.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HORIZON_S = {"5m": 300, "15m": 900}
PIN_WIN_MICRO = 990_000  # post-close buyYes at/above this => that side won
PIN_LOSE_MICRO = 10_000  # post-close buyYes at/below this => that side lost


@dataclass
class Round:
    event_id: str
    horizon: str
    title: str
    rule_variant: str | None = None  # "twap" | "endpoint" | None (rules line not captured)
    close_time_s: int | None = None
    listing_open_time_s: int | None = None
    samples: int = 0
    genuine: bool = False
    settlements: list[dict] = field(default_factory=list)
    post_close_buy_yes: dict[str, int] = field(default_factory=dict)  # marketId -> micro-USD

    @property
    def window(self) -> tuple[int, int] | None:
        if self.close_time_s is None:
            return None
        return self.close_time_s - HORIZON_S[self.horizon], self.close_time_s

    @property
    def terminal_label(self) -> str | None:
        """ "Up"/"Down" inferred from post-close pinned pricing; None until the pin is seen."""
        winners = [m for m, p in self.post_close_buy_yes.items() if p >= PIN_WIN_MICRO]
        losers = [m for m, p in self.post_close_buy_yes.items() if p <= PIN_LOSE_MICRO]
        if len(winners) != 1 or len(losers) != 1:
            return None
        if winners[0].endswith("-0"):
            return "Up"
        return "Down" if winners[0].endswith("-1") else None


def classify_rule(rules_primary: str) -> str:
    """The settlement-rule variant, from the verbatim rules text."""
    return "twap" if "TWAP" in rules_primary else "endpoint"


def read_rounds(collect_dir: Path) -> tuple[dict[str, Round], dict[str, int]]:
    """Parse every collect-*.jsonl into rounds keyed by eventId, plus file-level counts.

    The genuine flag is computed per file span; a round genuine in any file stays genuine.
    """
    rounds: dict[str, Round] = {}
    totals = {"files": 0, "samples": 0, "gaps": 0, "settlementLines": 0}
    for path in sorted(collect_dir.glob("collect-*.jsonl")):
        totals["files"] += 1
        records = []
        span_lo_us: int | None = None
        span_hi_us: int | None = None
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                records.append(rec)
                us = rec.get("arrivalUnixUs")
                if isinstance(us, int):
                    span_lo_us = us if span_lo_us is None else min(span_lo_us, us)
                    span_hi_us = us if span_hi_us is None else max(span_hi_us, us)
        for rec in records:
            kind = rec.get("kind")
            eid = rec.get("eventId")
            if kind == "gap":
                totals["gaps"] += 1
                continue
            if eid is None:
                continue
            rnd = rounds.get(eid)
            if rnd is None:
                horizon = rec.get("horizon")
                if horizon not in HORIZON_S:
                    continue
                rnd = rounds[eid] = Round(
                    event_id=eid, horizon=horizon, title=rec.get("title") or ""
                )
            if kind == "rules":
                rnd.rule_variant = classify_rule(rec.get("rulesPrimary") or "")
            elif kind == "sample":
                totals["samples"] += 1
                rnd.samples += 1
                arrival_us = rec.get("arrivalUnixUs")
                for m in rec.get("markets") or []:
                    if isinstance(m.get("closeTime"), int):
                        rnd.close_time_s = m["closeTime"]
                    if isinstance(m.get("openTime"), int):
                        rnd.listing_open_time_s = m["openTime"]
                    buy_yes = (m.get("pricing") or {}).get("buyYesPriceUsd")
                    if (
                        isinstance(arrival_us, int)
                        and isinstance(rnd.close_time_s, int)
                        and arrival_us / 1e6 > rnd.close_time_s
                        and isinstance(buy_yes, int)
                        and isinstance(m.get("marketId"), str)
                    ):
                        rnd.post_close_buy_yes[m["marketId"]] = buy_yes
            elif kind == "settlement":
                totals["settlementLines"] += 1
                rnd.settlements.append(rec)
            if rnd.close_time_s is not None and span_lo_us is not None and span_hi_us is not None:
                pad = HORIZON_S[rnd.horizon]
                lo = span_lo_us / 1e6 - pad
                hi = span_hi_us / 1e6 + pad
                if lo <= rnd.close_time_s <= hi:
                    rnd.genuine = True
    return rounds, totals


def inventory(rounds: dict[str, Round]) -> dict:
    """The registered §3.7 inventory: genuine vs stale, per horizon, rule variants, settlements."""
    genuine = [r for r in rounds.values() if r.genuine]
    stale = [r for r in rounds.values() if not r.genuine]
    return {
        "roundsSeen": len(rounds),
        "genuine": {
            "total": len(genuine),
            "5m": sum(1 for r in genuine if r.horizon == "5m"),
            "15m": sum(1 for r in genuine if r.horizon == "15m"),
            "ruleVariants": {
                v: sum(1 for r in genuine if r.rule_variant == v) for v in ("twap", "endpoint")
            },
            "withSettlementLine": sum(1 for r in genuine if r.settlements),
            "terminalLabeled": sum(1 for r in genuine if r.terminal_label),
            "terminalLabels": {
                r.event_id: {
                    "horizon": r.horizon,
                    "label": r.terminal_label,
                    "windowUnixS": list(r.window) if r.window else None,
                }
                for r in sorted(genuine, key=lambda r: r.close_time_s or 0)
                if r.terminal_label
            },
        },
        "staleFilteredOut": {
            "total": len(stale),
            "eventIds": sorted(r.event_id for r in stale),
        },
    }
