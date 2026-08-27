"""Jupiter SOL up/down prediction-market collector — minimal, read-only, honest.

Started by the primary agent 2026-08-27 to stop data loss while the fuller
foundation lane waits on credits. The mispricing dataset ONLY accrues from
turn-on: contract prices are ephemeral (a round's pricing is null once it
closes), so every hour not collecting is permanently gone. This records the
live SOL 5m and 15m rounds' implied-price path across each window, plus each
round's settlement after close, so every round becomes a labeled example.

HARD BOUNDARY: read-only. No order is constructed, signed, or submitted. Only
GET requests to the keyless Jupiter prediction REST API. Bounded cadence.

Every sample carries BOTH clocks: the local arrival instant (wall + monotonic)
and the provider's own timestamps VERBATIM in their declared units (openTime /
closeTime / resolveAt are provider epoch seconds; pricing is micro-USD, 1e6 =
$1). Nothing is normalized here — the analysis layer reads verbatim and states
its own conversions. A failed cycle is a durable gap line, never a silent skip.

Run:
    cd analysis && uv run --offline python -m joshi_analysis.jupiter_collect.collect \
        --minutes 180 --out ~/dev/joshi/state/prediction
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://api.jup.ag/prediction/v1"
UA = "joshi-prediction-collector/1 (read-only study)"


def now_wall_us() -> int:
    return int(time.time() * 1_000_000)


def now_mono_ns() -> int:
    return time.monotonic_ns()


def iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1_000_000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def get(path: str, timeout: float = 15.0) -> tuple[int, dict | list | None]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    req = urllib.request.Request(f"{BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def unwrap(body: dict | list | None) -> list | dict | None:
    if isinstance(body, dict):
        return body.get("data", body)
    return body


def live_sol_rounds() -> tuple[int, list[dict]]:
    """The current live SOL up/down rounds (5m and 15m), from search. (status, rows)."""
    q = urllib.parse.quote("Solana Up or Down")
    status, body = get(f"/events/search?query={q}")
    rows = unwrap(body)
    if not isinstance(rows, list):
        return status, []
    out = []
    for e in rows:
        if not isinstance(e, dict) or not e.get("isLive"):
            continue
        tags = [str(t).lower() for t in (e.get("tags") or [])]
        horizon = "5m" if "5m" in tags else "15m" if "15m" in tags else None
        title = (e.get("metadata") or {}).get("title") or ""
        # up-or-down rounds only: the recurring 5m/15m, not the yearly/ath price markets
        if horizon and "up or down" in str(title).lower():
            out.append({"eventId": e.get("eventId"), "horizon": horizon, "title": title})
    return status, out


def sample_round(event_id: str) -> tuple[int, dict | None]:
    """Hydrate one round's markets with their pricing/times/status/result."""
    status, body = get(f"/events/{urllib.parse.quote(str(event_id))}")
    e = unwrap(body)
    if not isinstance(e, dict):
        return status, None
    markets = []
    for m in e.get("markets") or []:
        markets.append(
            {
                "marketId": m.get("marketId"),
                "outcomes": m.get("outcomes"),
                "openTime": m.get("openTime"),
                "closeTime": m.get("closeTime"),
                "resolveAt": m.get("resolveAt"),
                "status": m.get("status"),
                "result": m.get("result"),
                "pricing": m.get("pricing"),
                "clobTokenIds": m.get("clobTokenIds"),
                "provider": m.get("provider"),
            }
        )
    return status, {
        "eventId": e.get("eventId"),
        "isLive": e.get("isLive"),
        "rulesPrimary": (e.get("markets") or [{}])[0].get("rulesPrimary"),
        "markets": markets,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=180.0)
    ap.add_argument("--cadence", type=float, default=20.0, help="seconds between poll cycles")
    ap.add_argument("--out", type=Path, default=Path("~/dev/joshi/state/prediction"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    samples_path = args.out / f"collect-{stamp}.jsonl"
    receipt_path = args.out / f"collect-{stamp}.receipt.json"
    rules_seen: dict[str, str] = {}
    settled: set[str] = set()
    counts = {"cycles": 0, "samples": 0, "gaps": 0, "settlements": 0, "requests": 0}
    deadline = time.monotonic() + args.minutes * 60

    def emit(record: dict) -> None:
        record["arrivalWall"] = iso(now_wall_us())
        record["arrivalUnixUs"] = now_wall_us()
        record["arrivalMonotonicNs"] = now_mono_ns()
        with samples_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
            fh.flush()

    print(
        f"jupiter collector armed: {samples_path.name}, "
        f"{args.minutes:.0f} min, cadence {args.cadence:.0f}s",
        flush=True,
    )
    while time.monotonic() < deadline:
        counts["cycles"] += 1
        status, rounds = live_sol_rounds()
        counts["requests"] += 1
        if status != 200:
            counts["gaps"] += 1
            emit({"kind": "gap", "phase": "search", "httpStatus": status})
            time.sleep(args.cadence)
            continue
        for r in rounds:
            st, hydrated = sample_round(r["eventId"])
            counts["requests"] += 1
            if st != 200 or hydrated is None:
                counts["gaps"] += 1
                emit({"kind": "gap", "phase": "hydrate", "eventId": r["eventId"], "httpStatus": st})
                continue
            # capture the settlement rule once per round (verbatim)
            rp = hydrated.get("rulesPrimary")
            if rp and r["eventId"] not in rules_seen:
                rules_seen[r["eventId"]] = rp
                emit({"kind": "rules", "eventId": r["eventId"], "horizon": r["horizon"],
                      "title": r["title"], "rulesPrimary": rp})
            emit({"kind": "sample", "eventId": r["eventId"], "horizon": r["horizon"],
                  "title": r["title"], "markets": hydrated["markets"]})
            counts["samples"] += 1
            # settlement: any market with a populated result / resolved status
            for m in hydrated["markets"]:
                key = f"{r['eventId']}:{m.get('marketId')}"
                resolved = str(m.get("status")).lower() in ("resolved", "settled", "closed")
                if key not in settled and (m.get("result") is not None or resolved):
                    settled.add(key)
                    counts["settlements"] += 1
                    emit({"kind": "settlement", "eventId": r["eventId"], "horizon": r["horizon"],
                          "marketId": m.get("marketId"), "result": m.get("result"),
                          "status": m.get("status"), "closeTime": m.get("closeTime"),
                          "resolveAt": m.get("resolveAt"), "finalPricing": m.get("pricing")})
        receipt_path.write_text(json.dumps({
            "contract": "joshi.jupiter_collect.receipt.v1",
            "authority": "read_only_no_execution",
            "startedStamp": stamp, "updatedWall": iso(now_wall_us()),
            "counts": counts, "roundsRulesCaptured": len(rules_seen),
        }, indent=1))
        time.sleep(args.cadence)
    print(f"collector done: {json.dumps(counts)} -> {samples_path.name}", flush=True)


if __name__ == "__main__":
    main()
