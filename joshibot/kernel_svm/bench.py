"""What one swap costs. This decides whether the Lean model can be validated against the
whole recorded corpus or only a sample, so it is measured rather than estimated.

Three costs are separated, because they amortise very differently:

  * loading a snapshot (JSON parse, ELF verification, account writes) -- paid once per pool
  * executing a swap -- paid per swap
  * fetching a snapshot from mainnet -- paid once per pool, and only when capturing

A corpus replayed pool-by-pool pays the load cost once and the swap cost N times. A corpus
replayed in recorded order, hopping between pools, pays the load cost far more often, so the
two numbers imply different harness designs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from oracle import DlmmOracle, OracleOutOfRange, OracleRejected, SwapRequest


def bench(path: Path, iterations: int) -> dict[str, object]:
    raw = path.read_text()
    fixture = json.loads(raw)
    is_fixture = "snapshot" in fixture
    snap = fixture["snapshot"] if is_fixture else fixture

    load_times = []
    for _ in range(5):
        started = time.perf_counter()
        oracle = DlmmOracle(json.loads(json.dumps(snap)))
        load_times.append(time.perf_counter() - started)

    if is_fixture:
        request = SwapRequest(
            amount_in=fixture["input"]["amount_in"],
            swap_for_y=fixture["input"]["swap_for_y"],
            unix_timestamp=fixture["input"]["unix_timestamp"],
            slot=fixture["input"].get("slot"),
        )
    else:
        request = SwapRequest(amount_in=10**9, swap_for_y=True, unix_timestamp=snap["block_time"])

    # Warm once so the first-call cost does not land in the distribution.
    try:
        oracle.answer(request)
    except (OracleRejected, OracleOutOfRange) as exc:
        return {"file": path.name, "error": str(exc)[:120]}

    swap_times = []
    for _ in range(iterations):
        started = time.perf_counter()
        oracle.answer(request)
        swap_times.append(time.perf_counter() - started)

    swap_times.sort()
    return {
        "file": path.name,
        "pool": snap["pool"][:8],
        "bin_step": snap["lb_pair"]["bin_step"],
        "snapshot_bytes": len(raw),
        "load_ms": round(statistics.median(load_times) * 1e3, 1),
        "swap_ms_median": round(statistics.median(swap_times) * 1e3, 3),
        "swap_ms_p95": round(swap_times[int(0.95 * (len(swap_times) - 1))] * 1e3, 3),
        "swap_ms_min": round(swap_times[0] * 1e3, 3),
        "swaps_per_second": round(1.0 / statistics.median(swap_times)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="measure per-swap oracle cost")
    ap.add_argument("--iterations", type=int, default=300)
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    targets = sorted((here / "fixtures").glob("*.json")) or sorted((here / "snapshots").glob("*.json"))
    if not targets:
        raise SystemExit("no fixtures or snapshots to benchmark")

    rows = [bench(p, args.iterations) for p in targets]
    print(json.dumps(rows, indent=2))

    rates = [r["swaps_per_second"] for r in rows if "swaps_per_second" in r]
    if rates:
        rate = statistics.median(rates)
        print(f"\nmedian {rate:.0f} swaps/s single-threaded")
        for n, label in ((100_000, "100k"), (1_000_000, "1M")):
            print(f"  {label} swaps: {n / rate / 60:.1f} min single-threaded")


if __name__ == "__main__":
    main()
