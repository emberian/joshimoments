"""Hourly screen digest -> the gated Telegram group, via the gate bot's outbox.

Run from a systemd timer. Reads the screen's scores JSONL for the trailing window,
composes one digest message, and INSERTs it into the gate's outbox (the gate bot's
poller delivers it). Posting cadence lives HERE, not in the scorer: the raw CLEAN
rate is ~2/minute, which would destroy a channel — the digest is the channel-safe
shape, and a realtime feed can be its own opt-in surface later.

Writes to the gate sqlite the same way approvals.py does (WAL + busy_timeout,
NO GateState construction — its flock guards the poller identity, not this).
Skips silently-with-note when no group is bound yet or there were no events.

Usage: uv run python -m dregg_screen.digest \
    --scores-dir /home/hbox/dregg-data/screen/scores \
    --gate-db /home/hbox/dregg-data/gate/gate.sqlite [--window-min 60]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

MAX_CLEAN_LINES = 6


def load_window(scores_dir: Path, window_min: float) -> list[dict]:
    """Score rows whose scored_at falls inside the trailing window (today + yesterday files)."""
    cutoff = time.time() - window_min * 60.0
    rows: list[dict] = []
    days = {datetime.now(UTC).strftime("%Y-%m-%d"),
            datetime.fromtimestamp(cutoff, UTC).strftime("%Y-%m-%d")}
    for day in sorted(days):
        path = scores_dir / f"{day}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            scored = row.get("t_scored", 0)
            # t_scored is an ISO-8601 string on the wire; tolerate a numeric epoch too.
            try:
                scored_ts = (
                    datetime.fromisoformat(str(scored)).timestamp()
                    if isinstance(scored, str)
                    else float(scored)
                )
            except ValueError:
                continue
            if scored_ts >= cutoff:
                rows.append(row)
    return rows


def compose(rows: list[dict], window_min: float) -> str | None:
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        verdict = str(row.get("verdict", "UNSCORED"))
        counts[verdict] = counts.get(verdict, 0) + 1
    cleans = [r for r in rows if r.get("verdict") == "CLEAN"]
    total = len(rows)
    parts = [
        f"🗞 launch screen — last {window_min:.0f}m: {total} launches scored",
        " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])),
    ]
    if cleans:
        parts.append(f"\nCLEAN admits ({len(cleans)}):")
        for row in cleans[-MAX_CLEAN_LINES:]:
            symbol = row.get("symbol") or "?"
            mint = str(row.get("mint", ""))
            parts.append(f"  ${symbol} {mint[:8]}…{mint[-4:]}")
        if len(cleans) > MAX_CLEAN_LINES:
            parts.append(f"  …and {len(cleans) - MAX_CLEAN_LINES} more")
    parts.append("\nScores rank risk; they do not establish intent.")
    return "\n".join(parts)


def enqueue(gate_db: Path, text: str, dedup_key: str) -> bool:
    """INSERT into the gate outbox iff a group is bound. Returns whether enqueued."""
    connection = sqlite3.connect(gate_db, timeout=10.0)
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'group_id'"
        ).fetchone()
        if row is None:
            return False
        chat_id = int(row[0])
        payload = {"chat_id": chat_id, "text": text}
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at) "
                "VALUES (?, 'sendMessage', ?, ?)",
                (dedup_key, json.dumps(payload, separators=(",", ":")), time.time()),
            )
        return True
    finally:
        connection.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores-dir", type=Path, required=True)
    ap.add_argument("--gate-db", type=Path, required=True)
    ap.add_argument("--window-min", type=float, default=60.0)
    args = ap.parse_args()

    rows = load_window(args.scores_dir, args.window_min)
    text = compose(rows, args.window_min)
    if text is None:
        print(json.dumps({"posted": False, "reason": "no_events_in_window"}))
        return
    hour_key = datetime.now(UTC).strftime("digest-%Y-%m-%dT%H")
    posted = enqueue(args.gate_db, text, hour_key)
    print(json.dumps({"posted": posted, "rows": len(rows),
                      "reason": None if posted else "no_group_bound"}))


if __name__ == "__main__":
    main()
