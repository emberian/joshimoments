"""The weekly record post: ``compose`` (build + enqueue approval) and ``deliver`` (poll + post).

Mirrors dregg_wire.post's lifecycle exactly — two systemd timers on hbox:

    dregg-record.timer (weekly, e.g. Mon ~13:30 UTC):
        uv run python -m dregg_record.post compose \
            --archive-db /home/hbox/dregg-data/archive/archive.sqlite \
            --gate-db    /home/hbox/dregg-data/gate/gate.sqlite \
            --state-dir  /home/hbox/dregg-data/record \
            [--wallet-parquet /home/hbox/dregg-data/wallets/estimator.parquet]
    dregg-record-deliver.timer (every 10 min):
        uv run python -m dregg_record.post deliver \
            --gate-db   /home/hbox/dregg-data/gate/gate.sqlite \
            --state-dir /home/hbox/dregg-data/record

``compose`` builds THE CALLOUT RECORD over the trailing measurement window (default
30d — posted weekly, measured over a month, stated in the header), writes the markdown
artifact and board json into the state dir, and enqueues ONE approval
(source='record', kind='weekly') whose summary is the exact plain text that would be
sent; the full text rides the payload, immune to the summary's 3500-char cap. An
"empty" board (nobody past the min-n gate yet) still composes — the honest absence is
itself the post, and the operator can reject it. ``deliver`` polls the decision; on
approve it posts to the gated group through the gate bot's outbox (dedup
``record-<week>``, plain text, NO parse_mode); on reject it marks the week skipped;
with no group bound it sticks at 'approved' and retries — an approval is never
silently dropped.

State: ``<state-dir>/record_state.json`` — ``{iso_week: {approval_id, status, ...}}``,
statuses pending -> approved -> delivered, or pending -> skipped. A skipped week may
be recomposed by hand (fresh approval); pending/approved/delivered weeks never
double-enqueue.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from dregg_gate.approvals import enqueue_approval, read_decision
from dregg_screen.digest import enqueue as enqueue_outbox

from .leaderboard import MIN_N, build_leaderboard, render_markdown, render_text
from .records import WINDOW_DAYS

STATE_FILE = "record_state.json"


def load_state(state_dir: Path) -> dict:
    path = state_dir / STATE_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(state_dir: Path, state: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    tmp.replace(state_dir / STATE_FILE)


def iso_week(now: float) -> str:
    stamp = datetime.fromtimestamp(now, UTC)
    return f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"


def compose(args: argparse.Namespace) -> dict:
    now = time.time()
    week = args.week or iso_week(now)
    state = load_state(args.state_dir)
    entry = state.get(week)
    if entry and entry["status"] != "skipped":
        return {"composed": False, "week": week, "reason": f"already {entry['status']}"}
    board = build_leaderboard(
        args.archive_db,
        now_ms=int(now * 1000),
        window_days=args.window_days,
        min_n=args.min_n,
        wallet_parquet=args.wallet_parquet,
    )
    text = render_text(board)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    (args.state_dir / f"{week}.md").write_text(render_markdown(board))
    (args.state_dir / f"{week}.board.json").write_text(
        json.dumps(board, indent=1, sort_keys=True) + "\n"
    )
    approval_id = enqueue_approval(
        args.gate_db, "record", "weekly", text, {"week": week, "text": text}
    )
    state[week] = {"approval_id": approval_id, "status": "pending", "enqueued_at": now}
    save_state(args.state_dir, state)
    return {
        "composed": True,
        "week": week,
        "approval_id": approval_id,
        "chars": len(text),
        "ranked": len(board.get("rows", [])),
    }


def deliver(args: argparse.Namespace) -> dict:
    state = load_state(args.state_dir)
    actionable = {w: e for w, e in state.items() if e.get("status") in ("pending", "approved")}
    if not actionable:
        return {"delivered": [], "skipped": [], "note": "nothing pending"}
    delivered: list[str] = []
    skipped: list[str] = []
    waiting: list[str] = []
    changed = False
    for week, entry in sorted(actionable.items()):
        decision = read_decision(args.gate_db, entry["approval_id"])
        if decision is None:
            waiting.append(week)
            continue
        changed = True
        entry["decided_at"] = decision.decided_at
        if decision.decision == "reject":
            entry["status"] = "skipped"
            skipped.append(week)
            continue
        text = decision.payload.get("text", "")
        if not text:
            entry["status"] = "skipped"
            entry["note"] = "approved but payload carried no text; nothing sendable"
            skipped.append(week)
            continue
        if enqueue_outbox(args.gate_db, text, f"record-{week}"):
            entry["status"] = "delivered"
            entry["delivered_at"] = time.time()
            delivered.append(week)
        else:
            entry["status"] = "approved"
            entry["note"] = "approved; no group bound yet, will retry"
            waiting.append(week)
    if changed:
        save_state(args.state_dir, state)
    return {"delivered": delivered, "skipped": skipped, "waiting": waiting}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dregg_record.post")
    sub = parser.add_subparsers(dest="command", required=True)

    p_compose = sub.add_parser("compose", help="build the week's record and enqueue it for approval")
    p_compose.add_argument("--week", help="ISO week id like 2026-W35 (default: this week)")
    p_compose.add_argument("--archive-db", type=Path, required=True)
    p_compose.add_argument("--gate-db", type=Path, required=True)
    p_compose.add_argument("--state-dir", type=Path, required=True)
    p_compose.add_argument("--wallet-parquet", type=Path, default=None)
    p_compose.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    p_compose.add_argument("--min-n", type=int, default=MIN_N)
    p_compose.set_defaults(run=compose)

    p_deliver = sub.add_parser("deliver", help="act on any decided approvals; exit fast otherwise")
    p_deliver.add_argument("--gate-db", type=Path, required=True)
    p_deliver.add_argument("--state-dir", type=Path, required=True)
    p_deliver.set_defaults(run=deliver)

    args = parser.parse_args(argv)
    print(json.dumps(args.run(args)))


if __name__ == "__main__":
    main()
