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

MAX_CLEAN_LINES = 10

#: What each verdict means to a trader, in the words the /screen card uses.
VERDICT_GLOSS = {
    "CLEAN": "passed every gate",
    "KNOWN_CREW": "birth-slot wallets or deployer match a tracked crew record",
    "BUNDLED": "multiple wallets bought in the very slot the coin was born",
    "NOT_CLEAN": "dev's own buy over the 2% line",
    "UNSCORED": "couldn't be fully read, so no verdict",
}


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


def _flat_symbol(row: dict) -> str:
    """Whitespace-flattened + clamped: a hostile provider name cannot add lines."""

    return ("".join(str(row.get("symbol") or "?").split()) or "?")[:12]


def _labels(cleans: list[dict]) -> dict[str, str]:
    """mint -> display label; colliding tickers get a mint-prefix suffix (the feed
    lane's fix: three $Lyra in one message must stay tellable apart)."""

    flat = {str(r.get("mint", "")): _flat_symbol(r) for r in cleans}
    counts: dict[str, int] = {}
    for name in flat.values():
        counts[name] = counts.get(name, 0) + 1
    return {
        mint: (name if counts[name] == 1 else f"{name}·{mint[:4]}")
        for mint, name in flat.items()
    }


def _clean_line(row: dict, label: str) -> str:
    """One admit with the numbers that made it clean — intelligence, not a roll call."""

    mint = str(row.get("mint", ""))
    features = row.get("features") or {}
    bits = []
    share = features.get("dev_buy_share")
    if isinstance(share, (int, float)):
        bits.append(f"dev buy {100 * share:.2f}%")
    history = row.get("deployer_history") or {}
    launches = int(history.get("launches") or 0)
    if launches:
        record = f"deployer launched {launches} before, no rips or dumps on record"
        grads = int(history.get("grads") or 0)
        if grads:
            record += f", {grads} graduated"
        bits.append(record)
    else:
        bits.append("first launch from this deployer")
    if not row.get("in_validated_population", True):
        bits.append("unusual launch type — screen accuracy unmeasured here")
    detail = " · ".join(bits)
    return f"  ${label} https://pump.fun/coin/{mint} — {detail}"


def _rate_line(rows: list[dict]) -> str:
    """The number that makes the hour meaningful: this window's CLEAN rate on
    standard launches, against the screen's stamped long-run operating point."""

    pop = [r for r in rows if r.get("in_validated_population")]
    if not pop:
        return ("None of these launches were the standard type the screen's "
                "accuracy was measured on.")
    pop_clean = sum(1 for r in pop if r.get("verdict") == "CLEAN")
    rate = f"{100 * pop_clean / len(pop):.0f}%"
    head = (f"Pass rate: {pop_clean} of {len(pop)} standard-type launches "
            f"came out CLEAN ({rate})")
    for row in reversed(rows):
        rip = (row.get("base_rates") or {}).get("is_rip") or {}
        if rip.get("admit_rate") is not None:
            span = str((row.get("base_rates") or {}).get("validated_span") or "?").split(" (")[0]
            return (f"{head} vs the screen's long-run {100 * rip['admit_rate']:.1f}% "
                    f"(measured {span}).")
    return f"{head}; no long-run baseline was stamped in this window's scores."


def compose(rows: list[dict], window_min: float) -> str | None:
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        verdict = str(row.get("verdict", "UNSCORED"))
        counts[verdict] = counts.get(verdict, 0) + 1
    cleans = [r for r in rows if r.get("verdict") == "CLEAN"]
    total = len(rows)
    parts = [f"🗞 launch screen — last {window_min:.0f} min: {total} launches scored"]
    # CLEAN leads (it's the money line); the rest by count. Enum names render
    # hyphenated, each with its plain meaning — the counts line is not a log line.
    ordered = sorted(counts.items(), key=lambda kv: (kv[0] != "CLEAN", -kv[1], kv[0]))
    for verdict, n in ordered:
        gloss = VERDICT_GLOSS.get(verdict, "unrecognized verdict")
        parts.append(f"{verdict.replace('_', '-')} {n} — {gloss}")
    parts.append("")
    parts.append(_rate_line(rows))
    if cleans:
        shown = cleans[-MAX_CLEAN_LINES:]
        labels = _labels(shown)
        parts.append(f"\nCLEAN admits ({len(cleans)}):")
        for row in shown:
            mint = str(row.get("mint", ""))
            parts.append(_clean_line(row, labels.get(mint, "?")))
        if len(cleans) > MAX_CLEAN_LINES:
            parts.append(
                f"  …and {len(cleans) - MAX_CLEAN_LINES} earlier this window "
                "(newest shown). /watch clean DMs you every one."
            )
    parts.append("\nDM me /screen <mint> for any launch's full card.")
    parts.append("Scores rank risk; they do not establish intent.")
    return "\n".join(parts)


def enqueue(gate_db: Path, text: str, dedup_key: str) -> bool:
    """INSERT into the gate outbox iff a group is bound. Returns whether enqueued.

    Plain text only, by construction: every group surface (this digest, the wire,
    the record post) rides this function, and none of them may carry a parse_mode —
    bare URLs auto-link, provider strings stay literal-inert.
    """
    connection = sqlite3.connect(gate_db, timeout=10.0)
    try:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'group_id'"
        ).fetchone()
        if row is None:
            return False
        chat_id = int(row[0])
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
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
