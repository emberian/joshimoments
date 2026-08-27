"""Finer-than-1m SOL/USD: trade-level series, verbatim retention, step-function price math.

Sources fixed by the registration's measured budget: Kraken SOLUSD trades (since-walk,
~35k trades/day — carries the 10-day surface AND the gate) and Coinbase SOL-USD trades
(~950k/day — too heavy for a long span; fetched over the labeled-rounds span only as the
denser gate cross-check). Both remain approximations of the Chainlink settlement stream;
the improvement over v1 is RESOLUTION (seconds vs minutes), not basis.

The price function is the last-trade step function p(s) = price of the last trade at or
before s. A boundary lookup with no trade in the preceding ``MAX_STALE_S`` is data-absent
(None — counted by callers, never imputed). Interior gaps are the step function's stated
semantics: a quiet stretch holds the last price. Arithmetic is float64 per the
registration (relative error <1e-9, far below the ~2 bp venue basis).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log, sqrt
from pathlib import Path

KRAKEN_TRADES = "https://api.kraken.com/0/public/Trades"
COINBASE_TRADES = "https://api.exchange.coinbase.com/products/SOL-USD/trades"
UA = "joshi-conditional-fine/1 (read-only study)"
MAX_STALE_S = 120.0


def _now_us() -> int:
    return int(time.time() * 1_000_000)


def _get(url: str, timeout: float = 20.0) -> tuple[int, str | None, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, None, {}
    except Exception:
        return 0, None, {}


def _emit(path: Path, record: dict) -> None:
    record["arrivalUnixUs"] = _now_us()
    record["arrivalMonotonicNs"] = time.monotonic_ns()
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()


def fetch_kraken(
    start_s: int, end_s: int, out_dir: Path, *, max_requests: int = 500, pause_s: float = 1.2
) -> Path:
    """Since-walk Kraken SOLUSD trades over [start_s, end_s]; verbatim pages; receipted."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    samples = out_dir / f"fine-kraken-{stamp}.jsonl"
    receipt = out_dir / f"fine-kraken-{stamp}.receipt.json"
    counts = {"requests": 0, "gaps": 0, "rows": 0}
    since = str(int(start_s) * 1_000_000_000)
    reached = start_s
    while counts["requests"] < max_requests and reached < end_s:
        url = f"{KRAKEN_TRADES}?pair=SOLUSD&count=1000&since={since}"
        status, body, _ = _get(url)
        counts["requests"] += 1
        if status != 200 or body is None:
            counts["gaps"] += 1
            _emit(samples, {"kind": "gap", "venue": "kraken", "httpStatus": status, "since": since})
            time.sleep(pause_s)
            continue
        try:
            result = json.loads(body)["result"]
            rows = result["SOLUSD"]
            nxt = result["last"]
        except (KeyError, json.JSONDecodeError):
            counts["gaps"] += 1
            _emit(samples, {"kind": "gap", "venue": "kraken", "httpStatus": status, "since": since})
            time.sleep(pause_s)
            continue
        counts["rows"] += len(rows)
        _emit(samples, {"kind": "trades", "venue": "kraken", "since": since, "bodyText": body})
        if rows:
            reached = float(rows[-1][2])
        if not rows or nxt == since:
            break
        since = nxt
        time.sleep(pause_s)
    receipt.write_text(
        json.dumps(
            {
                "contract": "joshi.jupiter_conditional.fine_receipt.v1",
                "authority": "read_only_no_execution",
                "venue": "kraken",
                "spanUnixS": [start_s, end_s],
                "reachedUnixS": reached,
                "counts": counts,
                "budgetMaxRequests": max_requests,
            },
            indent=1,
        )
    )
    return receipt


def fetch_coinbase(
    start_s: int, out_dir: Path, *, max_requests: int = 150, pause_s: float = 0.25
) -> Path:
    """Backwalk Coinbase SOL-USD trades from now until before start_s; verbatim; receipted."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    samples = out_dir / f"fine-coinbase-{stamp}.jsonl"
    receipt = out_dir / f"fine-coinbase-{stamp}.receipt.json"
    counts = {"requests": 0, "gaps": 0, "rows": 0}
    cursor: str | None = None
    oldest = time.time()
    while counts["requests"] < max_requests and oldest >= start_s:
        url = f"{COINBASE_TRADES}?limit=1000" + (f"&after={cursor}" if cursor else "")
        status, body, headers = _get(url)
        counts["requests"] += 1
        if status != 200 or body is None:
            counts["gaps"] += 1
            _emit(
                samples, {"kind": "gap", "venue": "coinbase", "httpStatus": status, "after": cursor}
            )
            time.sleep(pause_s)
            continue
        rows = json.loads(body)
        counts["rows"] += len(rows)
        _emit(samples, {"kind": "trades", "venue": "coinbase", "after": cursor, "bodyText": body})
        if rows:
            t = rows[-1]["time"].replace("Z", "+00:00")
            oldest = datetime.fromisoformat(t).timestamp()
        nxt = headers.get("cb-after") or headers.get("Cb-After")
        if not rows or not nxt:
            break
        cursor = nxt
        time.sleep(pause_s)
    receipt.write_text(
        json.dumps(
            {
                "contract": "joshi.jupiter_conditional.fine_receipt.v1",
                "authority": "read_only_no_execution",
                "venue": "coinbase",
                "backwalkToUnixS": start_s,
                "oldestReachedUnixS": oldest,
                "counts": counts,
                "budgetMaxRequests": max_requests,
            },
            indent=1,
        )
    )
    return receipt


@dataclass
class StepSeries:
    """Sorted trade tape as a last-trade step function."""

    times: list[float]
    prices: list[float]

    @property
    def span(self) -> tuple[float, float]:
        return self.times[0], self.times[-1]

    def price_at(self, s: float, max_stale_s: float = MAX_STALE_S) -> float | None:
        i = bisect_right(self.times, s) - 1
        if i < 0 or s - self.times[i] > max_stale_s:
            return None
        return self.prices[i]

    def integral(self, x: float, y: float) -> float | None:
        """∫ p ds over [x, y]; None if the start boundary is data-absent."""
        if y <= x or self.price_at(x) is None:
            return None
        i = bisect_right(self.times, x) - 1
        total = 0.0
        while i < len(self.times):
            seg_start = max(self.times[i], x)
            seg_end = y if i + 1 >= len(self.times) else min(self.times[i + 1], y)
            if seg_end > seg_start:
                total += self.prices[i] * (seg_end - seg_start)
            if i + 1 >= len(self.times) or self.times[i + 1] >= y:
                break
            i += 1
        return total

    def twap(self, x: float, y: float) -> float | None:
        area = self.integral(x, y)
        return None if area is None else area / (y - x)

    def truncated(self, t: float) -> StepSeries:
        """The series as it stood at time t — the no-leakage tool."""
        i = bisect_right(self.times, t)
        return StepSeries(self.times[:i], self.prices[:i])

    def vol_bps(self, t: float, lookback_s: float = 120.0, step_s: float = 5.0) -> float | None:
        """Std of step_s log-returns over [t - lookback_s, t], in bps; None on absent data."""
        points = []
        s = t - lookback_s
        while s <= t + 1e-9:
            p = self.price_at(s)
            if p is None:
                return None
            points.append(p)
            s += step_s
        rets = [log(points[i + 1] / points[i]) * 1e4 for i in range(len(points) - 1)]
        if len(rets) < 2:
            return None
        mean = sum(rets) / len(rets)
        return sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))


def load_kraken(fine_dir: Path) -> StepSeries:
    """All retained Kraken pages -> deduped (by trade id), sorted StepSeries."""
    seen: dict[int, tuple[float, float]] = {}
    for path in sorted(fine_dir.glob("fine-kraken-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("kind") != "trades":
                    continue
                for row in json.loads(rec["bodyText"])["result"]["SOLUSD"]:
                    seen[int(row[6])] = (float(row[2]), float(row[0]))
    ordered = sorted(seen.values())
    return StepSeries([t for t, _ in ordered], [p for _, p in ordered])


def load_coinbase(fine_dir: Path) -> StepSeries:
    """All retained Coinbase pages -> deduped (by trade_id), sorted StepSeries."""
    seen: dict[int, tuple[float, float]] = {}
    for path in sorted(fine_dir.glob("fine-coinbase-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("kind") != "trades":
                    continue
                for row in json.loads(rec["bodyText"]):
                    t = datetime.fromisoformat(row["time"].replace("Z", "+00:00")).timestamp()
                    seen[int(row["trade_id"])] = (t, float(row["price"]))
    ordered = sorted(seen.values())
    return StepSeries([t for t, _ in ordered], [p for _, p in ordered])


def gap_profile(series: StepSeries, x: float, y: float) -> dict:
    """Inter-trade gap stats inside [x, y]: n, median, p90, max (seconds)."""
    i = bisect_right(series.times, x)
    j = bisect_right(series.times, y)
    gaps = sorted(series.times[k + 1] - series.times[k] for k in range(i, j - 1) if j - i >= 2)
    if not gaps:
        return {"trades": max(0, j - i), "gaps": 0}
    return {
        "trades": j - i,
        "gaps": len(gaps),
        "medianGapS": gaps[len(gaps) // 2],
        "p90GapS": gaps[min(len(gaps) - 1, int(0.9 * len(gaps)))],
        "maxGapS": gaps[-1],
    }
