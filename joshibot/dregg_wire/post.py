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

``compose`` builds the day's facts, renders the wire's PANELS (dregg_wire.visuals:
the day-at-a-glance hero, the crew board, the callout desk) as PNGs beside the
markdown artifact and facts json in the state dir, and enqueues ONE approval
(source='wire', kind='daily') whose summary names the panels and carries the exact
Telegram text, so the operator approves verbatim what would be sent; the payload
carries the full text plus the panel manifest (paths + captions), and the gate's
presenter DMs the hero image alongside the approve/reject buttons so nobody approves
blind. A panel render failure downgrades to the text-only wire, never silence.

``deliver`` exits instantly when nothing is pending; on approve it posts the wire as
an ORDERED MEDIA SEQUENCE through the gate bot's outbox — one sendPhoto per panel
(dedup ``wire-<day>-pN-<name>``, plain-text caption, no parse_mode), then the full
text as the final sendMessage (dedup ``wire-<day>``) — enqueued in one transaction
so a retry can never post half a wire twice; the outbox's strict ordering keeps the
sequence intact and its drop-not-dam rule means one lost PNG cannot silence the
text. On reject it marks the day skipped. If no group is bound yet the entry sticks
at 'approved' and delivery retries next tick — an approval is never silently
dropped.

State: ``<state-dir>/wire_state.json`` — ``{day: {approval_id, status, ...}}`` with
statuses pending -> approved -> delivered, or pending -> skipped. Written atomically.
A skipped day may be recomposed by hand (a fresh approval); pending/approved/
delivered days are never double-enqueued.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from dregg_gate.approvals import enqueue_approval, read_decision
from dregg_wire.facts import build_facts
from dregg_wire.visuals import build_panels
from dregg_wire.wire import lede, render, write_artifact

STATE_FILE = "wire_state.json"
#: Keep our own summary under the approvals outbox's silent 3500-char clip, with room
#: for the trim marker — a clipped summary must always SAY it is clipped.
SUMMARY_MAX = 3400


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
    issue = issue_number(state, day)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    panel_note: str | None = None
    panel_rows: list[dict] = []
    images: dict[str, str] = {}
    try:
        panels = build_panels(
            facts, issue, lede(facts), scores_dir=args.scores_dir, d4m_dir=args.d4m_dir
        )
    except (ValueError, OSError) as exc:
        # A render failure downgrades to the text-only wire, never silence.
        panels = []
        panel_note = f"panel render failed ({type(exc).__name__}); wire degrades to text-only"
    for panel in panels:
        path = args.state_dir / f"{day}-{panel.name}.png"
        path.write_bytes(panel.png)
        images[panel.name] = path.name
        panel_rows.append(
            {"name": panel.name, "title": panel.title, "path": str(path), "caption": panel.caption}
        )
    telegram_text, markdown = render(facts, issue, images)
    write_artifact(args.state_dir, day, markdown)
    (args.state_dir / f"{day}.facts.json").write_text(
        json.dumps(facts, indent=1, sort_keys=True) + "\n"
    )
    if panel_rows:
        shape = f"posts as {len(panel_rows)} panels + the full text below"
        shape += "\npanels: " + " · ".join(p["title"] for p in panel_rows)
    else:
        shape = f"posts as text only — {panel_note or 'no panels rendered'}"
    header = f"WIRE #{issue} — {day} · {shape}"
    summary = f"{header}\n\n{telegram_text}"
    if len(summary) > SUMMARY_MAX:
        # The approvals outbox clips summaries at 3500 SILENTLY (mid-word); trim
        # ourselves, say so, and say what still posts — the payload text is always
        # the exact message, and the operator is told where the DM stops short.
        marker = (
            f"\n\n[DM cap — trimmed here; posts in full "
            f"({len(telegram_text)} chars) exactly as approved]"
        )
        keep = SUMMARY_MAX - len(header) - len(marker) - 2
        summary = f"{header}\n\n{telegram_text[:keep]}{marker}"
    payload: dict = {"day": day, "text": telegram_text, "panels": panel_rows}
    if panel_rows:
        payload["preview_photo_path"] = panel_rows[0]["path"]  # the hero rides the approval DM
    approval_id = enqueue_approval(args.gate_db, "wire", "daily", summary, payload)
    state[day] = {
        "approval_id": approval_id,
        "status": "pending",
        "enqueued_at": time.time(),
        "panels": [p["name"] for p in panel_rows],
    }
    if panel_note:
        state[day]["note"] = panel_note
    save_state(args.state_dir, state)
    return {
        "composed": True,
        "day": day,
        "approval_id": approval_id,
        "chars": len(telegram_text),
        "panels": [p["name"] for p in panel_rows],
    }


def _enqueue_wire(gate_db: Path, day: str, panels: list[dict], text: str) -> bool:
    """INSERT the wire's ordered media sequence into the gate outbox iff a group is
    bound — dregg_screen.digest's pattern, extended to a photo sequence and made
    ATOMIC (one transaction) so a crash-retry can never enqueue half a wire. Dedup:
    ``wire-<day>-pN-<name>`` per photo, ``wire-<day>`` for the closing text."""

    connection = sqlite3.connect(gate_db, timeout=10.0)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key = 'group_id'").fetchone()
        if row is None:
            return False
        chat_id = int(row[0])
        now = time.time()
        with connection:
            for index, panel in enumerate(panels, start=1):
                payload = {
                    "chat_id": chat_id,
                    "photo_path": str(panel.get("path", "")),
                    # Plain text, no parse_mode — the gate's hard production rule.
                    # The cap is enforced at compose; the clamp here is the belt.
                    "caption": str(panel.get("caption", ""))[:1024],
                }
                connection.execute(
                    "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at)"
                    " VALUES (?, 'sendPhoto', ?, ?)",
                    (
                        f"wire-{day}-p{index}-{panel.get('name', 'panel')}",
                        json.dumps(payload, separators=(",", ":")),
                        now,
                    ),
                )
            connection.execute(
                "INSERT OR IGNORE INTO outbox (dedup_key, method, payload_json, created_at)"
                " VALUES (?, 'sendMessage', ?, ?)",
                (
                    f"wire-{day}",
                    json.dumps({"chat_id": chat_id, "text": text}, separators=(",", ":")),
                    now,
                ),
            )
        return True
    finally:
        connection.close()


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
        panels = [p for p in decision.payload.get("panels") or [] if isinstance(p, dict)]
        if _enqueue_wire(args.gate_db, day, panels, text):
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
    p_compose.add_argument(
        "--d4m-dir", type=Path, default=Path("state/dregg_d4m"),
        help="dregg_d4m crew-graph artifact dir; missing/mis-shaped artifacts fall back cleanly",
    )
    p_compose.set_defaults(run=compose)

    p_deliver = sub.add_parser("deliver", help="act on any decided approvals; exit fast otherwise")
    p_deliver.add_argument("--gate-db", type=Path, required=True)
    p_deliver.add_argument("--state-dir", type=Path, required=True)
    p_deliver.set_defaults(run=deliver)

    args = parser.parse_args(argv)
    print(json.dumps(args.run(args)))


if __name__ == "__main__":
    main()
