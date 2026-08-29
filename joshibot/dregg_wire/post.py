"""The wire's lifecycle: ``compose`` (build + enqueue approval) and ``deliver`` (poll + post).

Designed for two systemd timers on hbox:

    dregg-wire.timer (daily ~13:00 UTC):
        uv run python -m dregg_wire.post compose \
            --scores-dir /home/hbox/dregg-data/screen/scores \
            --archive-db /home/hbox/dregg-data/archive/archive.sqlite \
            --gate-db    /home/hbox/dregg-data/gate/gate.sqlite \
            --state-dir  /home/hbox/dregg-data/wire
    dregg-wire-deliver.timer (every 10 min):
        uv run python -m dregg_wire.post deliver \
            --gate-db   /home/hbox/dregg-data/gate/gate.sqlite \
            --state-dir /home/hbox/dregg-data/wire

``compose`` builds the day's facts, writes the markdown artifact and facts json into
the state dir, and enqueues ONE approval (source='wire', kind='daily') whose summary
is the exact Telegram text — HTML source and all, so the operator approves verbatim
what would be sent. The full text also rides the payload, immune to the summary's
3500-char cap. ``deliver`` exits instantly when nothing is pending; on approve it
posts to the gated group through the gate bot's outbox (dedup ``wire-<day>``,
parse_mode HTML); on reject it marks the day skipped. If no group is bound yet the
entry sticks at 'approved' and delivery retries next tick — an approval is never
silently dropped.

State: ``<state-dir>/wire_state.json`` — ``{day: {approval_id, status, ...}}`` with
statuses pending -> approved -> delivered, or pending -> skipped. Written atomically.
A skipped day may be recomposed by hand (a fresh approval); pending/approved/
delivered days are never double-enqueued.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from dregg_gate.approvals import enqueue_approval, read_decision
from dregg_screen.digest import enqueue as enqueue_outbox
from dregg_wire.facts import build_facts
from dregg_wire.wire import render, write_artifact

STATE_FILE = "wire_state.json"


def load_state(state_dir: Path) -> dict:
    path = state_dir / STATE_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(state_dir: Path, state: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    tmp.replace(state_dir / STATE_FILE)


def issue_number(state: dict, day: str) -> int:
    """WIRE #N: N = how many earlier days were ever composed. Deterministic, starts at 0."""

    return sum(1 for other in state if other < day)


def compose(args: argparse.Namespace) -> dict:
    day = args.day or datetime.now(UTC).strftime("%Y-%m-%d")
    state = load_state(args.state_dir)
    entry = state.get(day)
    if entry and entry["status"] != "skipped":
        return {"composed": False, "day": day, "reason": f"already {entry['status']}"}
    facts = build_facts(
        day,
        scores_dir=args.scores_dir,
        archive_db=args.archive_db,
        wallet_parquet=args.wallet_parquet,
        manifest_dir=args.manifest_dir,
    )
    telegram_text, markdown = render(facts, issue_number(state, day))
    write_artifact(args.state_dir, day, markdown)
    (args.state_dir / f"{day}.facts.json").write_text(
        json.dumps(facts, indent=1, sort_keys=True) + "\n"
    )
    approval_id = enqueue_approval(
        args.gate_db, "wire", "daily", telegram_text, {"day": day, "text": telegram_text}
    )
    state[day] = {"approval_id": approval_id, "status": "pending", "enqueued_at": time.time()}
    save_state(args.state_dir, state)
    return {"composed": True, "day": day, "approval_id": approval_id, "chars": len(telegram_text)}


def deliver(args: argparse.Namespace) -> dict:
    state = load_state(args.state_dir)
    actionable = {d: e for d, e in state.items() if e.get("status") in ("pending", "approved")}
    if not actionable:
        return {"delivered": [], "skipped": [], "note": "nothing pending"}
    delivered: list[str] = []
    skipped: list[str] = []
    waiting: list[str] = []
    changed = False
    for day, entry in sorted(actionable.items()):
        decision = read_decision(args.gate_db, entry["approval_id"])
        if decision is None:
            waiting.append(day)
            continue
        changed = True
        entry["decided_at"] = decision.decided_at
        if decision.decision == "reject":
            entry["status"] = "skipped"
            skipped.append(day)
            continue
        text = decision.payload.get("text", "")
        if not text:
            entry["status"] = "skipped"
            entry["note"] = "approved but payload carried no text; nothing sendable"
            skipped.append(day)
            continue
        if enqueue_outbox(args.gate_db, text, f"wire-{day}", parse_mode="HTML"):
            entry["status"] = "delivered"
            entry["delivered_at"] = time.time()
            delivered.append(day)
        else:
            entry["status"] = "approved"
            entry["note"] = "approved; no group bound yet, will retry"
            waiting.append(day)
    if changed:
        save_state(args.state_dir, state)
    return {"delivered": delivered, "skipped": skipped, "waiting": waiting}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dregg_wire.post")
    sub = parser.add_subparsers(dest="command", required=True)

    p_compose = sub.add_parser("compose", help="build the day's wire and enqueue it for approval")
    p_compose.add_argument("--day", help="UTC day YYYY-MM-DD (default: today)")
    p_compose.add_argument("--scores-dir", type=Path, required=True)
    p_compose.add_argument("--archive-db", type=Path, required=True)
    p_compose.add_argument("--gate-db", type=Path, required=True)
    p_compose.add_argument("--state-dir", type=Path, required=True)
    p_compose.add_argument("--wallet-parquet", type=Path, default=None)
    p_compose.add_argument("--manifest-dir", type=Path, default=None)
    p_compose.set_defaults(run=compose)

    p_deliver = sub.add_parser("deliver", help="act on any decided approvals; exit fast otherwise")
    p_deliver.add_argument("--gate-db", type=Path, required=True)
    p_deliver.add_argument("--state-dir", type=Path, required=True)
    p_deliver.set_defaults(run=deliver)

    args = parser.parse_args(argv)
    print(json.dumps(args.run(args)))


if __name__ == "__main__":
    main()
