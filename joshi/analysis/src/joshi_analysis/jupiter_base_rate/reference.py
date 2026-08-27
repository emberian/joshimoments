"""The reference SOL/USD series — an approximation of the settlement object, labeled as such.

What actually settles the contracts (from the captured ``rulesPrimary`` text) is a Chainlink
SOL/USD **data stream**: current rounds the ``sol-usd-twap-60s-streams`` TWAP product, an older
captured round the point ``sol-usd`` stream. Both are pull-based, signed, credentialed products.
The settlement-exact series therefore requires **Chainlink Data Streams API access** (an account
with API key/secret; historical report retrieval by feed id and timestamp). JOSHI does not hold
those credentials, so nothing in this module is settlement-exact and nothing downstream may quote
it as if it were.

What this module fetches instead, as the best freely available approximation:

- **Coinbase Exchange SOL-USD 1-minute candles** (public, keyless, quoted in USD, arbitrary
  history). Chosen over the on-chain Chainlink data *feed* (push-based, deviation/heartbeat
  cadence — a coarser, laggier object than the stream, and with no cheap historical backfill) and
  over Pyth (a different oracle family, and per-boundary point queries cost ~60x the requests for
  the same span).
- **Kraken SOLUSD 1-minute OHLC** for the available overlap (~720 minutes), used only to measure
  cross-venue dispersion — a bound on the venue half of the basis risk, not on the aggregation
  half.

Declared basis risks (carried into every result): single-venue last-trade spot vs Chainlink's
multi-venue aggregate (the rule text explicitly says "not according to other sources or spot
markets"); minute-close sampling vs a continuous 60 s TWAP; candle-open-at-or-after-T vs the
stream value at T.

Storage is verbatim: each request's raw response body is retained untouched, with both local
clocks and the request parameters; parsing happens at load time with ``Decimal`` so the
provider's decimal literals survive exactly. A failed request is a durable gap line, never a
silent skip.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REFERENCE_LABEL = (
    "coinbase-1m-approx — NOT settlement-exact; settlement is the Chainlink SOL/USD "
    "data stream (TWAP variant on current rounds), credentialed"
)
SETTLEMENT_EXACT_REQUIRES = (
    "Chainlink Data Streams API access (credentialed): historical report retrieval for "
    "stream sol-usd-twap-60s-streams (current TWAP-rule rounds) and sol-usd "
    "(endpoint-rule rounds), https://data.chain.link/streams/sol-usd-twap-60s-streams"
)

COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/SOL-USD/candles"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC?pair=SOLUSD&interval=1"
UA = "joshi-base-rate-reference/1 (read-only study)"
CANDLES_PER_REQUEST = 300
GRANULARITY_S = 60


@dataclass(frozen=True)
class Candle:
    """One 1-minute candle; every price field is the provider's exact decimal literal."""

    time_s: int
    low: Decimal
    high: Decimal
    open: Decimal
    close: Decimal
    volume: Decimal


def _now_us() -> int:
    return int(time.time() * 1_000_000)


def _iso(unix_s: float) -> str:
    return datetime.fromtimestamp(unix_s, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_text(url: str, timeout: float = 20.0) -> tuple[int, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def fetch_reference(
    start_s: int,
    end_s: int,
    out_dir: Path,
    *,
    max_requests: int = 200,
    pause_s: float = 0.35,
) -> Path:
    """Fetch [start_s, end_s] of Coinbase 1m candles plus a Kraken overlap, verbatim, receipted.

    Bounded: at most ``max_requests`` HTTP requests, ~3/s. Returns the receipt path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    samples = out_dir / f"reference-{stamp}.jsonl"
    receipt = out_dir / f"reference-{stamp}.receipt.json"
    counts = {"requests": 0, "gaps": 0, "coinbaseRows": 0, "krakenRows": 0}

    def emit(record: dict) -> None:
        record["arrivalWall"] = _iso(_now_us() / 1e6)
        record["arrivalUnixUs"] = _now_us()
        record["arrivalMonotonicNs"] = time.monotonic_ns()
        with samples.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
            fh.flush()

    chunk = CANDLES_PER_REQUEST * GRANULARITY_S
    t = start_s
    while t <= end_s and counts["requests"] < max_requests:
        chunk_end = min(t + chunk - GRANULARITY_S, end_s)
        url = (
            f"{COINBASE_CANDLES}?granularity={GRANULARITY_S}&start={_iso(t)}&end={_iso(chunk_end)}"
        )
        status, body = _get_text(url)
        counts["requests"] += 1
        if status != 200 or body is None:
            counts["gaps"] += 1
            emit(
                {
                    "kind": "gap",
                    "venue": "coinbase",
                    "httpStatus": status,
                    "requestStartUnixS": t,
                    "requestEndUnixS": chunk_end,
                }
            )
        else:
            rows = json.loads(body)
            counts["coinbaseRows"] += len(rows) if isinstance(rows, list) else 0
            emit(
                {
                    "kind": "candles",
                    "venue": "coinbase",
                    "productId": "SOL-USD",
                    "granularitySeconds": GRANULARITY_S,
                    "requestStartUnixS": t,
                    "requestEndUnixS": chunk_end,
                    "bodyText": body,
                }
            )
        t = chunk_end + GRANULARITY_S
        time.sleep(pause_s)

    if counts["requests"] < max_requests:
        status, body = _get_text(KRAKEN_OHLC)
        counts["requests"] += 1
        if status != 200 or body is None:
            counts["gaps"] += 1
            emit({"kind": "gap", "venue": "kraken", "httpStatus": status})
        else:
            try:
                parsed = json.loads(body)
                counts["krakenRows"] = len(parsed.get("result", {}).get("SOLUSD", []))
            except (json.JSONDecodeError, AttributeError):
                counts["krakenRows"] = 0
            emit({"kind": "kraken_ohlc", "venue": "kraken", "pair": "SOLUSD", "bodyText": body})

    receipt.write_text(
        json.dumps(
            {
                "contract": "joshi.jupiter_base_rate.reference_receipt.v1",
                "authority": "read_only_no_execution",
                "referenceLabel": REFERENCE_LABEL,
                "settlementExactRequires": SETTLEMENT_EXACT_REQUIRES,
                "spanUnixS": [start_s, end_s],
                "spanIso": [_iso(start_s), _iso(end_s)],
                "counts": counts,
                "budgetMaxRequests": max_requests,
                "finishedWall": _iso(time.time()),
            },
            indent=1,
        )
    )
    return receipt


def load_coinbase(ref_dir: Path) -> dict[int, Candle]:
    """Parse every retained Coinbase response in ``ref_dir`` into {minute_ts: Candle}.

    Floats in the provider JSON are parsed straight to ``Decimal`` so the textual literals
    survive exactly. Duplicate timestamps across overlapping fetches keep the later file's row
    (they are re-reads of the same closed candle).
    """
    out: dict[int, Candle] = {}
    for path in sorted(ref_dir.glob("reference-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("kind") != "candles" or rec.get("venue") != "coinbase":
                    continue
                rows = json.loads(rec["bodyText"], parse_float=Decimal, parse_int=Decimal)
                for row in rows:
                    t, low, high, opn, close, vol = row
                    out[int(t)] = Candle(
                        time_s=int(t),
                        low=Decimal(low),
                        high=Decimal(high),
                        open=Decimal(opn),
                        close=Decimal(close),
                        volume=Decimal(vol),
                    )
    return out


def load_kraken_closes(ref_dir: Path) -> dict[int, Decimal]:
    """{minute_ts: close} from every retained Kraken OHLC response (string literals → Decimal)."""
    out: dict[int, Decimal] = {}
    for path in sorted(ref_dir.glob("reference-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                rec = json.loads(line)
                if rec.get("kind") != "kraken_ohlc":
                    continue
                body = json.loads(rec["bodyText"])
                for row in body.get("result", {}).get("SOLUSD", []):
                    out[int(row[0])] = Decimal(str(row[4]))
    return out


def venue_dispersion(
    coinbase: dict[int, Candle], kraken: dict[int, Decimal]
) -> dict[str, float | int]:
    """Cross-venue |relative close difference| over the timestamp overlap: median, p95, max, n."""
    diffs = sorted(
        float(abs(kraken[t] - coinbase[t].close) / coinbase[t].close)
        for t in kraken.keys() & coinbase.keys()
        if coinbase[t].close != 0
    )
    if not diffs:
        return {"n": 0}
    return {
        "n": len(diffs),
        "medianAbsRel": diffs[len(diffs) // 2],
        "p95AbsRel": diffs[min(len(diffs) - 1, int(0.95 * len(diffs)))],
        "maxAbsRel": diffs[-1],
    }
