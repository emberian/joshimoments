"""The Kraken tick tape with size and taker side — the flow data the strawman never used.

``finesol.load_kraken`` keeps (time, price) only; flow features need size, aggressor side,
and the market/limit taker flag, all present in the retained verbatim pages
(row = [price, volume, time, side b/s, ordertype m/l, misc, trade_id]). Everything here is
strictly causal by construction: window queries take trades with timestamp STRICTLY before
the query instant t (registration v1.4), and ``truncated`` is the unit-test hook — a tape
truncated at t (exclusive) must yield bit-identical features at t.
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path

MAX_STALE_S = 120.0


@dataclass
class FlowTape:
    """Sorted trade tape: times, prices, sizes, taker signs (+1 buy / -1 sell), mo flags."""

    times: list[float]
    prices: list[float]
    sizes: list[float]
    signs: list[int]
    market_order: list[int]
    _cum: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        cum_sv = [0.0]  # signed volume
        cum_v = [0.0]  # total volume
        cum_b = [0]  # taker-buy count
        cum_mo = [0]  # market-order count
        for s, g, mo in zip(self.sizes, self.signs, self.market_order, strict=True):
            cum_sv.append(cum_sv[-1] + g * s)
            cum_v.append(cum_v[-1] + s)
            cum_b.append(cum_b[-1] + (g > 0))
            cum_mo.append(cum_mo[-1] + mo)
        self._cum = {"sv": cum_sv, "v": cum_v, "b": cum_b, "mo": cum_mo}

    @property
    def span(self) -> tuple[float, float]:
        return self.times[0], self.times[-1]

    def window(self, t: float, w: float) -> tuple[int, int]:
        """Index range [i, j) of trades in the open window (t - w, t): strictly before t."""
        return bisect_right(self.times, t - w), bisect_left(self.times, t)

    def window_sums(self, t: float, w: float) -> dict:
        """Causal aggregates over (t - w, t) from prefix sums."""
        i, j = self.window(t, w)
        c = self._cum
        return {
            "count": j - i,
            "signedVol": c["sv"][j] - c["sv"][i],
            "vol": c["v"][j] - c["v"][i],
            "buys": c["b"][j] - c["b"][i],
            "marketOrders": c["mo"][j] - c["mo"][i],
        }

    def sizes_in(self, t: float, w: float) -> list[float]:
        i, j = self.window(t, w)
        return self.sizes[i:j]

    def price_before(self, s: float, max_stale_s: float = MAX_STALE_S) -> float | None:
        """Last trade price STRICTLY before s; None when staler than max_stale_s."""
        i = bisect_left(self.times, s) - 1
        if i < 0 or s - self.times[i] > max_stale_s:
            return None
        return self.prices[i]

    def truncated(self, t: float) -> FlowTape:
        """The tape as it stood strictly before t — the no-leakage tool (t itself excluded)."""
        i = bisect_left(self.times, t)
        return FlowTape(
            self.times[:i], self.prices[:i], self.sizes[:i], self.signs[:i],
            self.market_order[:i],
        )


def load_kraken_flow(fine_dir: Path) -> FlowTape:
    """All retained Kraken pages -> deduped (by trade id), sorted FlowTape."""
    seen: dict[int, tuple[float, float, float, int, int]] = {}
    for path in sorted(fine_dir.glob("fine-kraken-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("kind") != "trades":
                    continue
                for row in json.loads(rec["bodyText"])["result"]["SOLUSD"]:
                    seen[int(row[6])] = (
                        float(row[2]),
                        float(row[0]),
                        float(row[1]),
                        1 if row[3] == "b" else -1,
                        1 if row[4] == "m" else 0,
                    )
    ordered = sorted(seen.values())
    return FlowTape(
        [r[0] for r in ordered],
        [r[1] for r in ordered],
        [r[2] for r in ordered],
        [r[3] for r in ordered],
        [r[4] for r in ordered],
    )
