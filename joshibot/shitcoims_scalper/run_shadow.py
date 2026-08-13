"""Shadow scalper runner: feed -> jittered filter -> size -> deadline heap -> forced exit.

Shadow only. No keys, no signer, no imports from shitcoims_sentinel. Writes three
JSONL streams under state/scalper/ (gitignored):

  decisions.jsonl   one line per candidate seen: PropensityRecord-conformant core
                    plus thresholds drawn, features, size — INCLUDING every skip,
                    because rejected candidates cost nothing in shadow and buy the
                    selection-vs-luck decomposition.
  closes.jsonl      one line per shadow position closed (deadline or feed_lost),
                    with pessimistic pnl in lamports.
  heartbeat.jsonl   one line per minute: book state, breaker state, counters.

Run:  uv run python -m shitcoims_scalper.run_shadow --minutes 10
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from shitcoims_scalper.book import Book, OpenPosition
from shitcoims_scalper.feed import poll_listing, poll_mint
from shitcoims_scalper.policy import ScalperPolicy
from shitcoims_scalper.shadow import ShadowMarker

STATE_DIR = Path(__file__).resolve().parent.parent / "state" / "scalper"

DECISION_COOLDOWN_S = 120.0  # do not re-decide the same mint more often than this


def utc_iso(unix: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(unix)) + "+00:00"


def append(path: Path, record: dict) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def _close_record(close, run_id: str, reason: str) -> dict:
    """The ONE shape a close record takes, whatever ended the position.

    Every field every consumer needs, always present. See the drain-path comment: a
    record missing `spend_lamports` reads as a real observation and poisons every ratio
    computed over the file.
    """
    return {
        "run_id": run_id,
        "decision_id": close.decision_id,
        "mint": close.mint,
        "spend_lamports": close.spend_lamports,
        "proceeds_lamports": close.proceeds_lamports,
        "priority_fees_lamports": close.priority_fees_lamports,
        "pnl_lamports": close.pnl_lamports,
        "entry_t": close.entry_t,
        "exit_t": close.exit_t,
        "exit_reason": reason,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--poll-seconds", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Every record carries a run_id. Without one, records from different runs (different
    # seeds, thresholds, code) pool silently in one file and are averaged together.
    run_id = f"{int(time.time())}-s{args.seed}"
    decisions_path = STATE_DIR / "decisions.jsonl"
    closes_path = STATE_DIR / "closes.jsonl"
    heartbeat_path = STATE_DIR / "heartbeat.jsonl"

    policy = ScalperPolicy(seed=args.seed)
    book = Book()
    marker = ShadowMarker()
    positions: dict[str, OpenPosition] = {}
    last_decided: dict[str, float] = {}
    counters = {"snapshots": 0, "decisions": 0, "enters": 0, "closes": 0, "feed_lost": 0}

    t_end = time.time() + args.minutes * 60
    last_heartbeat = 0.0

    while time.time() < t_end:
        now = time.time()

        # 1. Feed: newest coins; every snapshot may fill a pending entry (next-observation rule).
        batch = poll_listing()
        counters["snapshots"] += len(batch)
        for snap in batch:
            for fill in marker.on_observation(snap.mint, snap.curve):
                pos = positions.get(fill.decision_id)
                if pos is None:  # filled but book state was lost; should not happen
                    continue

            # 2. Decide, at most once per cooldown per mint, and never on a completed curve.
            if snap.complete or now - last_decided.get(snap.mint, 0.0) < DECISION_COOLDOWN_S:
                continue
            last_decided[snap.mint] = now
            decision = policy.decide(
                mint=snap.mint,
                features=snap.features(),
                now_unix=now,
                decided_at=utc_iso(now),
            )
            counters["decisions"] += 1
            record = decision.propensity_record_json()
            record.update(
                run_id=run_id,
                verdict_pass=decision.verdict_pass,
                explored=decision.explored,
                thresholds=decision.thresholds.to_json(),
                features=decision.features,
                size_lamports=decision.size_lamports,
                deadline_unix=decision.deadline_unix,
            )
            append(decisions_path, record)

            if decision.action == "enter" and book.admits(
                mint=snap.mint, size_lamports=decision.size_lamports, now_unix=now
            ):
                pos = OpenPosition(
                    decision_id=decision.decision_id,
                    mint=snap.mint,
                    size_lamports=decision.size_lamports,
                    deadline_unix=decision.deadline_unix,
                )
                book.open(pos)
                positions[decision.decision_id] = pos
                marker.submit(decision.decision_id, snap.mint, decision.size_lamports)
                counters["enters"] += 1

        # 3. Refresh tracked mints so entries fill and exits can mark.
        for pos in list(positions.values()):
            snap = poll_mint(pos.mint)
            if snap is not None:
                marker.on_observation(pos.mint, snap.curve)

        # 4. Forced exits: pop everything past deadline, mark at the freshest observation.
        for pos in book.heap.due(now):
            snap = poll_mint(pos.mint)
            close = marker.close(pos.decision_id, snap.curve if snap else None)
            positions.pop(pos.decision_id, None)
            if close is None:
                continue
            book.close(pos, close.pnl_lamports, now)
            counters["closes"] += 1
            if close.exit_reason == "feed_lost":
                counters["feed_lost"] += 1
            append(closes_path, _close_record(close, run_id, close.exit_reason))

        if now - last_heartbeat >= 60.0:
            last_heartbeat = now
            append(
                heartbeat_path,
                {
                    "run_id": run_id,
                    "t": utc_iso(now),
                    "open_positions": len(book.heap),
                    "exposure_lamports": book.heap.exposure_lamports(),
                    "breaker_paused": book.breaker.paused(now),
                    **counters,
                },
            )

        time.sleep(max(0.0, args.poll_seconds - (time.time() - now)))

    # Drain: close whatever is still open at the horizon, pessimistically.
    #
    # This writes the FULL record. An earlier version emitted only decision_id/mint/pnl,
    # which silently broke every downstream ratio: the report divided ten positions' PnL by
    # one position's spend and printed -151%. A partial row is worse than no row, because it
    # looks like data. Any close record must carry the same fields whatever ended it.
    for pos in list(positions.values()):
        snap = poll_mint(pos.mint)
        close = marker.close(pos.decision_id, snap.curve if snap else None, reason="drain")
        if close is not None:
            append(closes_path, _close_record(close, run_id, "drain"))
    print(json.dumps(counters, indent=1))


if __name__ == "__main__":
    main()
