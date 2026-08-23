"""Compose a callout population and its entry-window tape, through the admission path.

Every provider request this script causes goes through one of two audited binaries:

* ``joshi-pump-product-read`` for the callout and discovery routes, with the row-projection
  review as the gate, so every page is retained and either promoted or refused in writing.
* ``joshi-pump-trades-backfill`` for the trades tape, seeking each callout's ``createdAt``
  through the measured all-zero-prefix cursor seek, with the reviewed trades schema as the gate.

A hard self-enforced request budget covers the whole study. Every request lands in a ledger
before its result is read, and the script refuses to start a request that would cross the
budget. Nothing here signs, submits, or constructs anything; every reach is a GET.

Usage (each subcommand is one phase, run in order):

    uv run --offline python gather.py --root <scratch> discovery
    uv run --offline python gather.py --root <scratch> callout-top --max 80
    uv run --offline python gather.py --root <scratch> callout-by-user --max-users 15
    uv run --offline python gather.py --root <scratch> tape --plan <plan.json>
    uv run --offline python gather.py --root <scratch> status
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PRODUCT_READ = REPO / "target" / "debug" / "joshi-pump-product-read"
TRADES_BACKFILL = REPO / "target" / "debug" / "joshi-pump-trades-backfill"
PUMP_API = REPO / "target" / "debug" / "joshi-pump-api"
FIXTURES = REPO / "crates" / "joshi-pump-api" / "fixtures"

REVIEWS = {
    "discovery_coins": FIXTURES / "row_projection_discovery_coins_v1.json",
    "currently_live": FIXTURES / "row_projection_currently_live_v1.json",
    "callout_top": FIXTURES / "row_projection_callout_top_v1.json",
    "callout_by_user": FIXTURES / "row_projection_callout_by_user_v1.json",
    "trades": FIXTURES / "schema_review_trades_v1.json",
}

HARD_BUDGET = 300
PACING_SECONDS = 2.5


def utc_of_millis(millis: int) -> str:
    """Render epoch milliseconds as the canonical six-digit UTC wire instant."""
    stamp = dt.datetime.fromtimestamp(millis / 1000.0, tz=dt.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class Ledger:
    """Append-only request ledger with the budget check in front of every spend."""

    def __init__(self, root: Path, budget: int) -> None:
        self.path = root / "ledger.jsonl"
        self.budget = budget

    def spent(self) -> int:
        if not self.path.exists():
            return 0
        total = 0
        with self.path.open() as handle:
            for line in handle:
                total += json.loads(line).get("requests", 0)
        return total

    def reserve(self, expected: int) -> None:
        spent = self.spent()
        if spent + expected > self.budget:
            raise SystemExit(
                f"REFUSED: {spent} requests spent, {expected} more would cross the "
                f"budget of {self.budget}. This refusal is the deliverable, not a failure."
            )

    def record(self, entry: dict) -> None:
        entry = {"at": dt.datetime.now(dt.UTC).isoformat(), **entry}
        with self.path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")


def body_of_outcome(outcome_path: Path) -> tuple[dict | list | None, int | None]:
    """Decode the exact retained bytes of the last attempt in a fetch outcome."""
    outcome = json.loads(outcome_path.read_text())
    attempts = outcome.get("attempts", [])
    if not attempts:
        return None, None
    attempt = attempts[-1]
    status = attempt.get("httpStatus")
    body = attempt.get("body", {})
    if body.get("status") != "exact":
        return None, status
    raw = base64.b64decode(body["bytesBase64"])
    try:
        return json.loads(raw), status
    except json.JSONDecodeError:
        return None, status


def product_read(
    ledger: Ledger,
    root: Path,
    tag: str,
    route: str,
    *,
    paths: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
) -> dict:
    """One admitted product read. Returns a summary with the receipt and decoded body."""
    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    outcome_path = out_dir / f"{tag}.outcome.json"
    receipt_path = out_dir / f"{tag}.receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        body, status = body_of_outcome(outcome_path)
        return {"tag": tag, "cached": True, "receipt": receipt, "body": body, "status": status}
    ledger.reserve(1)
    cmd = [
        str(PRODUCT_READ),
        "--route",
        route,
        "--state-dir",
        str(root / "admit"),
        "--review",
        str(REVIEWS[route]),
        "--emit-outcome",
        str(outcome_path),
        "--request-budget",
        "1",
    ]
    for name, value in (paths or {}).items():
        flag = "--mint" if name == "mint" else "--path"
        cmd.extend([flag, value if name == "mint" else f"{name}={value}"])
    for name, value in (query or {}).items():
        cmd.extend(["--query", f"{name}={value}"])
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    ledger.record(
        {
            "phase": route,
            "tag": tag,
            "requests": 1,
            "exit": proc.returncode,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    )
    if proc.returncode != 0:
        (out_dir / f"{tag}.stderr.txt").write_text(proc.stderr)
        return {"tag": tag, "cached": False, "error": proc.stderr.strip()[-500:], "receipt": None}
    receipt = json.loads(proc.stdout)
    receipt_path.write_text(json.dumps(receipt, indent=1))
    body, status = body_of_outcome(outcome_path)
    time.sleep(PACING_SECONDS)
    return {"tag": tag, "cached": False, "receipt": receipt, "body": body, "status": status}


def tape_walk(
    ledger: Ledger,
    root: Path,
    tag: str,
    mint: str,
    *,
    seek: str | None,
    stop_before: str | None,
    max_pages: int,
) -> dict:
    """One bounded backwards trade walk, seeded at a wall-clock seek instant."""
    out_dir = root / "tape"
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / f"{tag}.receipt.json"
    if receipt_path.exists():
        return {"tag": tag, "cached": True, "receipt": json.loads(receipt_path.read_text())}
    ledger.reserve(max_pages)
    cmd = [
        str(TRADES_BACKFILL),
        "--mint",
        mint,
        "--state-dir",
        str(root / "tape" / "state"),
        "--review",
        str(REVIEWS["trades"]),
        "--page-limit",
        "100",
        "--request-budget",
        str(max_pages),
        "--max-pages",
        str(max_pages),
        "--wall-budget-seconds",
        "90",
    ]
    if seek:
        cmd.extend(["--seek", seek])
    if stop_before:
        cmd.extend(["--stop-before", stop_before])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0:
        # The walk died without a receipt; the requests it may have spent cannot be read back,
        # so the whole ceiling is counted as spent. Conservative in the budget's favour.
        ledger.record({"phase": "tape", "tag": tag, "requests": max_pages, "exit": 2})
        (out_dir / f"{tag}.stderr.txt").write_text(proc.stderr)
        return {"tag": tag, "cached": False, "error": proc.stderr.strip()[-500:], "receipt": None}
    receipt = json.loads(proc.stdout)
    used = int(receipt["walk"]["requestsUsed"])
    ledger.record({"phase": "tape", "tag": tag, "requests": used, "exit": 0})
    receipt_path.write_text(json.dumps(receipt, indent=1))
    time.sleep(PACING_SECONDS)
    return {"tag": tag, "cached": False, "receipt": receipt}


def cmd_discovery(ledger: Ledger, root: Path) -> None:
    """Three pages of the most-recently-traded feed plus one currently-live page."""
    mints: dict[str, dict] = {}
    for offset in (0, 70, 140):
        result = product_read(
            ledger,
            root,
            f"disc_lt_off{offset}",
            "discovery_coins",
            query={
                "limit": "70",
                "offset": str(offset),
                "sort": "last_trade_timestamp",
                "order": "DESC",
            },
        )
        for row in result.get("body") or []:
            mint = row.get("mint")
            if mint and mint not in mints:
                mints[mint] = {
                    "mint": mint,
                    "source": f"discovery_last_trade_off{offset}",
                    "usd_market_cap": row.get("usd_market_cap"),
                    "created_timestamp": row.get("created_timestamp"),
                }
    live = product_read(ledger, root, "live_0", "currently_live", query={"limit": "50"})
    for row in live.get("body") or []:
        mint = row.get("mint")
        if mint and mint not in mints:
            mints[mint] = {
                "mint": mint,
                "source": "currently_live",
                "usd_market_cap": row.get("usd_market_cap"),
                "created_timestamp": row.get("created_timestamp"),
            }
    out = root / "mints.json"
    out.write_text(json.dumps(sorted(mints.values(), key=lambda m: str(m["mint"])), indent=1))
    print(f"{len(mints)} distinct mints -> {out}")


def cmd_callout_top(ledger: Ledger, root: Path, mints_file: Path, maximum: int) -> None:
    """One callout_top read per mint, largest market caps first, through the row gate."""
    mints = json.loads(mints_file.read_text())

    def cap_of(entry: dict) -> float:
        try:
            return float(entry.get("usd_market_cap") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(mints, key=cap_of, reverse=True)[:maximum]
    rows_path = root / "callout_rows_top.jsonl"
    seen: set[str] = set()
    if rows_path.exists():
        with rows_path.open() as handle:
            seen = {json.loads(line)["mint"] for line in handle}
    promoted = refused = empty = 0
    with rows_path.open("a") as sink:
        for entry in ranked:
            mint = entry["mint"]
            if mint in seen:
                continue
            result = product_read(
                ledger,
                root,
                f"ct_{mint[:12]}",
                "callout_top",
                paths={"mint": mint},
                query={"limit": "50"},
            )
            receipt = result.get("receipt")
            if receipt is None:
                continue
            outcome = receipt["schemaTrustOutcome"]
            body = result.get("body") or {}
            callouts = body.get("callouts", []) if isinstance(body, dict) else []
            record = {
                "mint": mint,
                "source": entry.get("source"),
                "trust": outcome,
                "trust_reason": receipt["schemaTrustReason"],
                "http_status": result.get("status"),
                "row_count": len(callouts),
                "rows": callouts if outcome == "promoted" else [],
            }
            sink.write(json.dumps(record) + "\n")
            if outcome == "promoted":
                promoted += 1
                if not callouts:
                    empty += 1
            else:
                refused += 1
    print(f"callout_top: {promoted} promoted ({empty} empty), {refused} refused -> {rows_path}")


def cmd_callout_by_user(
    ledger: Ledger, root: Path, max_users: int, pages: int, seed_file: Path | None
) -> None:
    """Fan out through callers: either the leaderboard seeds, or the callout_top sweep's callers.

    callout_by_user is an anonymous observed route, so it takes each caller's on-chain wallet as
    the path segment. Leaderboard callers are addressed by the base58 member of their wallets
    array (never the userId, which may be a 0x Privy id).
    """
    if seed_file is not None:
        seeds = json.loads(seed_file.read_text())
        ranked = [
            (caller["solWallets"][0], caller.get("totalCallouts", 0))
            for caller in seeds
            if caller.get("solWallets")
        ][:max_users]
    else:
        counts: dict[str, int] = {}
        rows_path = root / "callout_rows_top.jsonl"
        with rows_path.open() as handle:
            for line in handle:
                for row in json.loads(line)["rows"]:
                    user = row.get("userId")
                    if user:
                        counts[user] = counts.get(user, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max_users]
    out_path = root / "callout_rows_by_user.jsonl"
    seen: set[str] = set()
    if out_path.exists():
        with out_path.open() as handle:
            seen = {json.loads(line)["tag"] for line in handle}
    with out_path.open("a") as sink:
        for user, seen_count in ranked:
            token: str | None = None
            for page in range(pages):
                tag = f"cu_{user[:12]}_p{page}"
                if tag in seen:
                    continue
                query = {"limit": "50"}
                if token:
                    query["pageToken"] = token
                result = product_read(
                    ledger, root, tag, "callout_by_user", paths={"user": user}, query=query
                )
                receipt = result.get("receipt")
                if receipt is None:
                    break
                body = result.get("body") or {}
                callouts = body.get("callouts", []) if isinstance(body, dict) else []
                record = {
                    "tag": tag,
                    "user": user,
                    "page": page,
                    "seen_in_top": seen_count,
                    "trust": receipt["schemaTrustOutcome"],
                    "trust_reason": receipt["schemaTrustReason"],
                    "row_count": len(callouts),
                    "rows": callouts if receipt["schemaTrustOutcome"] == "promoted" else [],
                }
                sink.write(json.dumps(record) + "\n")
                token = body.get("nextPageToken") if isinstance(body, dict) else None
                if not token or not callouts:
                    break
    print(f"callout_by_user fan-out done -> {out_path}")


def cmd_redecide(root: Path, corpus_name: str) -> None:
    """Re-run the row gate offline, with the current review, over refused retained bytes.

    No network I/O and no ledger spend: this applies an amended review to bytes already
    retained, exactly what the ``row-gate`` subcommand of ``joshi-pump-api`` exists for.
    The original at-acquisition decision stays in the store untouched.
    """
    corpus = root / corpus_name
    records = [json.loads(line) for line in corpus.open()]
    flipped = 0
    for record in records:
        if record["trust"] == "promoted" or "missing_required_leaf" not in record["trust_reason"]:
            continue
        tag = record.get("tag") or f"ct_{record['mint'][:12]}"
        outcome_path = root / "out" / f"{tag}.outcome.json"
        route = "callout_top" if tag.startswith("ct_") else "callout_by_user"
        proc = subprocess.run(
            [str(PUMP_API), "row-gate", str(outcome_path), str(REVIEWS[route])],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            print(f"{tag}: row-gate failed: {proc.stderr.strip()[-200:]}")
            continue
        decision = json.loads(proc.stdout)
        if decision["outcome"] == "promoted":
            body, _ = body_of_outcome(outcome_path)
            callouts = body.get("callouts", []) if isinstance(body, dict) else []
            record["trust"] = "promoted"
            record["trust_reason"] = f"re_decided_offline:{decision['reviewId']}"
            record["row_count"] = len(callouts)
            record["rows"] = callouts
            flipped += 1
        else:
            record["trust_reason"] = f"still_refused:{decision['reasonCode']}"
    with corpus.open("w") as sink:
        for record in records:
            sink.write(json.dumps(record) + "\n")
    print(f"redecide: {flipped} responses promoted under the amended review -> {corpus}")


def cmd_tape(ledger: Ledger, root: Path, plan_file: Path) -> None:
    """Seek the tape to each planned callout and cover its entry window backwards."""
    plan = json.loads(plan_file.read_text())
    for item in plan:
        callout = item["calloutId"]
        mint = item["mint"]
        t0 = int(item["createdAt"])
        window_end = utc_of_millis(t0 + 30 * 60 * 1000)
        baseline_floor = utc_of_millis(t0 - 5 * 60 * 1000)
        walk_b = tape_walk(
            ledger,
            root,
            f"{callout[:18]}_B",
            mint,
            seek=window_end,
            stop_before=baseline_floor,
            max_pages=int(item.get("maxPages", 8)),
        )
        receipt = walk_b.get("receipt")
        reached = False
        if receipt is not None:
            oldest = receipt["walk"].get("oldestEventTime")
            stop = receipt["walk"]["stop"]
            reached = stop in ("horizon_reached", "provider_reported_no_more") or (
                oldest is not None and oldest <= utc_of_millis(t0)
            )
            print(f"{callout[:18]} B: stop={stop} oldest={oldest} reached_t0={reached}")
        if not reached:
            walk_a = tape_walk(
                ledger,
                root,
                f"{callout[:18]}_A",
                mint,
                seek=utc_of_millis(t0 + 1000),
                stop_before=None,
                max_pages=1,
            )
            if walk_a.get("receipt") is not None:
                print(f"{callout[:18]} A: baseline page fetched")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=HARD_BUDGET)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discovery")
    top = sub.add_parser("callout-top")
    top.add_argument("--mints", type=Path, default=None)
    top.add_argument("--max", type=int, default=80)
    fan = sub.add_parser("callout-by-user")
    fan.add_argument("--max-users", type=int, default=15)
    fan.add_argument("--pages", type=int, default=2)
    fan.add_argument("--seed-file", type=Path, default=None)
    tape = sub.add_parser("tape")
    tape.add_argument("--plan", type=Path, required=True)
    redecide = sub.add_parser("redecide")
    redecide.add_argument("--corpus", default="callout_rows_top.jsonl")
    sub.add_parser("status")
    args = parser.parse_args()

    args.root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.root, args.budget)
    if args.command == "status":
        print(f"{ledger.spent()} of {ledger.budget} requests spent")
        return
    for binary in (PRODUCT_READ, TRADES_BACKFILL):
        if not binary.exists():
            sys.exit(f"missing binary {binary}; build with cargo build --offline")
    if args.command == "discovery":
        cmd_discovery(ledger, args.root)
    elif args.command == "callout-top":
        cmd_callout_top(ledger, args.root, args.mints or (args.root / "mints.json"), args.max)
    elif args.command == "callout-by-user":
        cmd_callout_by_user(ledger, args.root, args.max_users, args.pages, args.seed_file)
    elif args.command == "tape":
        cmd_tape(ledger, args.root, args.plan)
    elif args.command == "redecide":
        cmd_redecide(args.root, args.corpus)


if __name__ == "__main__":
    main()
