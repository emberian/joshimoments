"""Pure parsing, settlement labeling, and round-record helpers for the backfill.

No network here. Everything operates on provider objects already fetched (or synthetic
test fixtures shaped like them). Provider values are claims in their declared units:
Gamma prices are decimal strings of dollars-per-share, trade prices are floats in
[0, 1] dollars-per-share, timestamps are provider epoch seconds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

HORIZON_SECONDS = {"5m": 300, "15m": 900}

# Settlement-rule eras. Polymarket switched the SOL up/down resolution source from the
# raw SOL/USD stream (endpoint rule: close >= open) to the 60 s-TWAP stream (the rule the
# jupiter_conditional step-0 gate proved 15/15 on 2026-08-27 rounds). The era is read off
# each round's own resolutionSource, never assumed.
ERA_TWAP60 = "twap60"
ERA_ENDPOINT = "endpoint"
ERA_UNKNOWN = "unknown"

# Terminal-pin thresholds: winner pinned at/above, loser at/below. The conditional deputy
# corroborated the pin against Chainlink-reference reconstructions (3/4) and the map
# records winner ~1.0 / loser ~0.001 on resolved rounds.
PIN_WIN = 0.90
PIN_LOSE = 0.10


def parse_window_start(slug: str) -> int | None:
    """Window-start unix seconds from a slug like sol-updown-5m-1787845500.

    The slug suffix is the round's true window start (closeTime - horizon) on the 300 s
    grid — openTime in the Jupiter API is LISTING time, not window start.
    """
    tail = slug.rsplit("-", 1)[-1]
    if not tail.isdigit():
        return None
    ts = int(tail)
    return ts if ts % 300 == 0 else None


def classify_era(resolution_source: str | None) -> str:
    if not resolution_source:
        return ERA_UNKNOWN
    if "twap" in resolution_source.lower():
        return ERA_TWAP60
    if "sol-usd" in resolution_source.lower():
        return ERA_ENDPOINT
    return ERA_UNKNOWN


def iso_to_unix(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def json_list(text: object) -> list:
    """Gamma encodes list fields (outcomes, clobTokenIds, outcomePrices) as JSON strings."""
    if isinstance(text, list):
        return text
    if isinstance(text, str):
        try:
            val = json.loads(text)
        except json.JSONDecodeError:
            return []
        return val if isinstance(val, list) else []
    return []


def label_from_gamma(
    closed: bool, outcomes: list[str], outcome_prices: list[str]
) -> str | None:
    """Polymarket's own resolution: a closed round with outcomePrices set to exact 1/0.

    Requires closed=True and the formal 1/0 split (tolerance for float artifacts only).
    A near-pin like 0.9995/0.0005 is last-trade pricing, NOT a resolution — it stays
    unlabeled by this source (the terminal-pin labeler handles pins, and says so).
    """
    if not closed or len(outcomes) != 2 or len(outcome_prices) != 2:
        return None
    try:
        prices = [float(p) for p in outcome_prices]
    except (TypeError, ValueError):
        return None
    hi = max(prices)
    lo = min(prices)
    if hi >= 0.9999 and lo <= 0.0001 and prices[0] != prices[1]:
        return outcomes[prices.index(hi)]
    return None


def label_from_pin(
    rows: list[list], outcomes: list[str], close_unix: int
) -> str | None:
    """Terminal-pin label from post-close trades: winner trades ~$1, loser ~$0.

    rows are slim trade rows [timestamp, outcomeIndex, price, size, side] (ascending t).
    Uses the LAST post-close trade per side. Requires the pinned side to clear PIN_WIN
    and, when the other side traded post-close, that side to sit under PIN_LOSE —
    a conflicted pin is None.
    """
    if len(outcomes) != 2:
        return None
    last: dict[int, float] = {}
    for t, oi, price, _size, _side in rows:
        if t >= close_unix and oi in (0, 1):
            last[oi] = float(price)
    if not last:
        return None
    winners = [oi for oi, p in last.items() if p >= PIN_WIN]
    losers = [oi for oi, p in last.items() if p <= PIN_LOSE]
    if len(winners) == 1 and len(losers) == len(last) - 1:
        return outcomes[winners[0]]
    return None


def settle_labels(round_rec: dict) -> dict:
    """The settlement block for a round record: both sources, verbatim disagreements kept."""
    outcomes = round_rec["outcomes"]
    gamma = round_rec["gammaResolution"]
    label_gamma = label_from_gamma(
        bool(gamma.get("closed")), outcomes, gamma.get("outcomePrices") or []
    )
    label_pin = label_from_pin(
        round_rec.get("trades", {}).get("rows") or [],
        outcomes,
        round_rec["closeTimeUnix"],
    )
    if label_gamma is not None:
        source = "gamma-resolution"
        label = label_gamma
        if label_pin is not None and label_pin != label_gamma:
            source = "gamma-resolution-pin-disagrees"
    elif label_pin is not None:
        source = "terminal-pin"
        label = label_pin
    else:
        source = "unlabeled"
        label = None
    return {
        "label": label,
        "labelSource": source,
        "labelGamma": label_gamma,
        "labelPin": label_pin,
        "gamma": gamma,
    }


@dataclass(frozen=True)
class TradeZones:
    """In-window / pre-window / post-close split of a round's slim trade rows."""

    in_window_up: list[list]
    in_window_down: list[list]
    pre_window: int
    post_close: int

    @property
    def counts(self) -> dict:
        return {
            "up": len(self.in_window_up),
            "down": len(self.in_window_down),
            "preWindow": self.pre_window,
            "postClose": self.post_close,
        }


def split_zones(rows: list[list], window_start: int, close_unix: int) -> TradeZones:
    """Window is [start, close): a trade at exactly close is settlement-pin zone."""
    up: list[list] = []
    down: list[list] = []
    pre = 0
    post = 0
    for row in rows:
        t, oi = row[0], row[1]
        if t < window_start:
            pre += 1
        elif t >= close_unix:
            post += 1
        elif oi == 0:
            up.append(row)
        elif oi == 1:
            down.append(row)
    return TradeZones(up, down, pre, post)


def load_rounds(path) -> list[dict]:
    """Read a backfill rounds.jsonl file. Lines that fail to parse are counted as gaps."""
    rounds: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("contract") == "joshi.jupiter_backfill.round.v1":
                rounds.append(rec)
    return rounds


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
