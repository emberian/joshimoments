"""The outcome census over the gathered callout corpus, and the tape sampling plan.

Reads only retained bytes (the jsonl corpora ``gather.py`` wrote from promoted pages).
Every number printed carries its denominator. Two structural caveats govern everything:

* ``/callout/top/{mint}`` is a leaderboard, not a census: its ordering is the provider's
  retrospective score and its row cap measured at 50. A response at the cap is a TRUNCATED,
  score-biased view of that mint's callouts; responses under the cap are plausibly complete
  but nothing the provider says confirms it. The census is therefore reported in two strata.
* ``multiple`` is a provider assertion, floored at 1 (never below), rounded to one decimal,
  and retrospective as of the read. ``multiple == 1`` therefore means "never rose more than
  ~5 percent above the callout price as of the read", not "missing". Rows that omit
  ``peakTimestamp`` entirely have no peak yet as of the read and are their own bin.
* ``createdAt`` is an OCCURRENCE time. No availability time exists anywhere on these routes,
  so nothing here can say when a callout became visible to any reader.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
from collections import Counter
from pathlib import Path

WINDOW_MINUTES = 30
BASELINE_MINUTES = 5


# Each corpus file, with how biased its sampling of a coin/caller's callouts is:
#   callout_by_user  — one caller's own timeline, newest-first, so an UNBIASED sample of that
#                      caller's recent calls (subject to the 50-row page cap).
#   callout_top      — a per-mint leaderboard; under the 50 cap it is plausibly that mint's whole
#                      callout set, at the cap it is a score-truncated top slice.
#   callout_leaderboard — the topCallouts teaser is the provider's TOP-3 per caller, the most
#                      survivorship-biased sampling of all; kept out of the outcome distribution.
CORPUS_FILES = (
    ("callout_rows_by_user.jsonl", "callout_by_user"),
    ("callout_rows_top.jsonl", "callout_top"),
    ("callout_rows_leaderboard.jsonl", "callout_leaderboard"),
)


def load_corpus(root: Path) -> list[dict]:
    """Callout rows from promoted pages, deduplicated by calloutId, provenance kept.

    Provenance is the origin with the LEAST biased sampling among the pages a callout appeared on,
    so a callout seen both in a caller's own timeline and in a top-3 teaser is credited to the
    timeline. That keeps the outcome distribution off the survivorship-biased pages.
    """
    rank = {"callout_by_user": 0, "callout_top": 1, "callout_leaderboard": 2}
    seen: dict[str, dict] = {}
    for name, origin in CORPUS_FILES:
        path = root / name
        if not path.exists():
            continue
        with path.open() as handle:
            for line in handle:
                record = json.loads(line)
                if record["trust"] != "promoted":
                    continue
                capped = origin == "callout_top" and record["row_count"] >= 50
                for row in record["rows"]:
                    entry = seen.get(row["calloutId"])
                    if entry is None:
                        seen[row["calloutId"]] = {
                            "row": row,
                            "origin": origin,
                            "origins": [origin],
                            "capped_page": capped,
                        }
                        continue
                    entry["origins"].append(origin)
                    if rank[origin] < rank[entry["origin"]]:
                        entry["origin"] = origin
                        entry["capped_page"] = capped
                    # The by_user / leaderboard rows carry the USD twins; merge them in.
                    entry["row"] = {**row, **entry["row"]}
    return list(seen.values())


def peak_multiple(row: dict) -> float | None:
    """The floored-at-1 PEAK multiple, route-consistently.

    THE TRAP, measured 2026-08-23 and the reason this helper exists: the field named `multiple`
    does NOT mean the same thing on the two callout routes. On /callout/top it is the PEAK multiple
    and is floored at 1 (min 1.000 over the sweep). On /callout/list (by_user) `multiple` is the
    CURRENT multiple as of the read — price-now over callout price — and is BELOW 1 on 89% of rows
    for coins that fell back, while that route's floored peak lives in a separate `maxMultiplier`
    field. Binning a mixed corpus on `multiple` alone would read a caller's faded winners as
    fresh sub-2x calls. So the peak is taken from `maxMultiplier` when the row carries it and from
    `multiple` otherwise, which is each route's own floored peak.
    """
    peak = row.get("maxMultiplier")
    if peak is None:
        peak = row.get("multiple")
    return peak


def multiple_bin(row: dict) -> str:
    if "peakTimestamp" not in row and "maxMultiplierAt" not in row:
        return "no_peak_yet"
    peak = peak_multiple(row)
    if peak is None:
        return "no_peak_yet"
    if peak <= 1.0:
        return "floor_eq_1"
    if peak <= 2:
        return "1_to_2"
    if peak <= 5:
        return "2_to_5"
    if peak <= 20:
        return "5_to_20"
    return "over_20"


def quantiles(values: list[float]) -> str:
    if not values:
        return "n=0"
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]

    return (
        f"n={len(ordered)} p10={at(0.1):.1f} p25={at(0.25):.1f} median={at(0.5):.1f} "
        f"p75={at(0.75):.1f} p90={at(0.9):.1f}"
    )


def cmd_census(root: Path) -> None:
    entries = load_corpus(root)
    now_ms = dt.datetime.now(dt.UTC).timestamp() * 1000
    print(f"corpus: {len(entries)} distinct callouts")
    for stratum, keep in (
        (
            "caller-timeline sample (callout_by_user, newest-first, least biased)",
            lambda e: e["origin"] == "callout_by_user",
        ),
        (
            "per-mint under-cap pages (callout_top, plausibly complete per mint)",
            lambda e: e["origin"] == "callout_top" and not e["capped_page"],
        ),
        (
            "per-mint capped pages (callout_top, score-truncated top-50)",
            lambda e: e["origin"] == "callout_top" and e["capped_page"],
        ),
        (
            "leaderboard top-3 teaser (survivorship-biased; NOT a distribution)",
            lambda e: e["origin"] == "callout_leaderboard",
        ),
    ):
        rows = [e["row"] for e in entries if keep(e)]
        if not rows:
            continue
        bins = Counter(multiple_bin(r) for r in rows)
        print(f"\n[{stratum}] n={len(rows)}")
        for name in ("no_peak_yet", "floor_eq_1", "1_to_2", "2_to_5", "5_to_20", "over_20"):
            count = bins.get(name, 0)
            print(f"  peak-mult {name:11s} {count:5d}  ({100 * count / len(rows):5.1f}%)")
        peaked = [
            (r["peakTimestamp"] - r["createdAt"]) / 60000
            for r in rows
            if r.get("peakTimestamp") and (peak_multiple(r) or 1) > 1
        ]
        print(f"  time-to-peak minutes (peaked rows): {quantiles(peaked)}")
        for horizon, label in ((10, "<=10min"), (60, "<=60min"), (1440, "<=24h")):
            if peaked:
                share = 100 * sum(1 for t in peaked if t <= horizon) / len(peaked)
                print(f"    peak {label}: {share:.1f}% of {len(peaked)}")
        ages = [(now_ms - r["createdAt"]) / 3600000 for r in rows]
        print(f"  callout age hours: {quantiles(ages)}")

    print("\ncaller concentration (denominator: whole corpus):")
    callers = Counter(e["row"]["userId"] for e in entries)
    print(f"  {len(callers)} distinct callers over {len(entries)} callouts")
    repeat = sum(1 for c in callers.values() if c > 1)
    print(f"  callers appearing more than once in-corpus: {repeat}")


def cmd_callers(root: Path) -> None:
    """Descriptive per-caller outcomes from their own histories. No significance claims."""
    path = root / "callout_rows_by_user.jsonl"
    if not path.exists():
        print("no by_user corpus yet")
        return
    per_user: dict[str, list[dict]] = {}
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            if record["trust"] != "promoted":
                continue
            per_user.setdefault(record["user"], []).extend(record["rows"])
    print("Per-caller from their OWN timeline (by_user). peak = maxMultiplier (floored at 1);")
    print("current = multiple (price-now / callout-price). Descriptive only, no inference.\n")
    print("caller | uniq | peak<=1|no-peak | med PEAK | med CURRENT | med min-to-peak")
    for user, rows in sorted(per_user.items(), key=lambda kv: -len(kv[1])):
        uniq = list({r["calloutId"]: r for r in rows}.values())
        peaks = [peak_multiple(r) for r in uniq if peak_multiple(r) is not None]
        currents = [r["multiple"] for r in uniq if r.get("multiple") is not None]
        floor = sum(1 for r in uniq if multiple_bin(r) in ("floor_eq_1", "no_peak_yet"))
        peaked = [
            (dt.datetime.fromisoformat(r["maxMultiplierAt"]).timestamp() * 1000 - r["createdAt"])
            / 60000
            for r in uniq
            if r.get("maxMultiplierAt") and (peak_multiple(r) or 1) > 1
        ]
        med_peak_mult = statistics.median(peaks) if peaks else None
        med_current = statistics.median(currents) if currents else None
        med_ttp = statistics.median(peaked) if peaked else None
        print(
            f"{user[:16]:16s} | n={len(uniq):3d} | {floor:3d} ({100 * floor / len(uniq):4.0f}%)"
            f" | {f'{med_peak_mult:.2f}' if med_peak_mult is not None else '-':>6}"
            f" | {f'{med_current:.2f}' if med_current is not None else '-':>6}"
            f" | {f'{med_ttp:.0f}' if med_ttp is not None else '-':>7}"
        )


def cmd_plan(root: Path, per_bin: int, max_age_hours: float, out: Path) -> None:
    """Sample callouts for the tape phase: spread over multiple bins, complete windows only."""
    entries = load_corpus(root)
    now_ms = dt.datetime.now(dt.UTC).timestamp() * 1000
    eligible = [
        e
        for e in entries
        if (now_ms - e["row"]["createdAt"]) >= (WINDOW_MINUTES + 10) * 60000
        and (now_ms - e["row"]["createdAt"]) <= max_age_hours * 3600000
    ]
    by_bin: dict[str, list[dict]] = {}
    for entry in eligible:
        by_bin.setdefault(multiple_bin(entry["row"]), []).append(entry)
    plan: list[dict] = []
    used_mints: set[str] = set()
    for name in ("no_peak_yet", "floor_eq_1", "1_to_2", "2_to_5", "5_to_20", "over_20"):
        pool = sorted(by_bin.get(name, []), key=lambda e: -e["row"]["createdAt"])
        taken = 0
        for entry in pool:
            if taken >= per_bin:
                break
            mint = entry["row"]["coinMint"]
            if mint in used_mints:
                continue
            used_mints.add(mint)
            row = entry["row"]
            plan.append(
                {
                    "calloutId": row["calloutId"],
                    "mint": mint,
                    "createdAt": row["createdAt"],
                    "bin": name,
                    "userId": row["userId"],
                    "multiple_asserted": row.get("multiple"),
                    "peak_multiple_asserted": peak_multiple(row),
                    "marketCap_asserted": row.get("marketCap"),
                    "calloutPriceUsd_asserted": row.get("calloutPriceUsd"),
                    "age_hours": round((now_ms - row["createdAt"]) / 3600000, 1),
                }
            )
            taken += 1
        print(f"bin {name}: {taken} sampled of {len(pool)} eligible")
    out.write_text(json.dumps(plan, indent=1))
    print(f"{len(plan)} callouts -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("census")
    sub.add_parser("callers")
    plan = sub.add_parser("plan")
    plan.add_argument("--per-bin", type=int, default=5)
    plan.add_argument("--max-age-hours", type=float, default=96.0)
    plan.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "census":
        cmd_census(args.root)
    elif args.command == "callers":
        cmd_callers(args.root)
    elif args.command == "plan":
        cmd_plan(args.root, args.per_bin, args.max_age_hours, args.out)


if __name__ == "__main__":
    main()
