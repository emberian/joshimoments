"""Smallest working proof of an embedded JOSHI resident.

It does exactly what the deputy task asked for, in order:
  1. authenticate via the tokeman pattern (joshi_auth) — proves the resident
     could drive an Agent SDK turn on the resident's own subscription;
  2. pair with a running joshi-core the way the cockpit does (joshi_pairing);
  3. read one scene through the cockpit-read route;
  4. write ONE honest annotation through the operator-evidence route, bound to
     the exact scene bytes it just read, and confirm the durable receipt.

No trading authority: the only mutation it can make is an evidence_only /
observe_only operator command, which is all its pairing scope permits.

Usage:
  python3 spike_annotation.py --listen 127.0.0.1:43219 \
      --origin http://127.0.0.1:4173 --scene <sceneId> --code <JOSHI-...>
"""

from __future__ import annotations

import sys
import json
import uuid
import argparse

sys.path.insert(0, "~/dev/joshi/apps/resident")

import joshi_auth
import joshi_evidence
from joshi_pairing import JoshiCoreSession


def opaque(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:4173")
    parser.add_argument("--scene", required=True)
    parser.add_argument("--code", required=True)
    args = parser.parse_args()

    log = lambda *a: print(*a, flush=True)

    # 1. Auth — the resident's own Claude subscription, via tokeman.
    account = joshi_auth.choose_account()
    token = joshi_auth.read_oauth_token(account)
    log(f"[auth] tokeman account={account} oauth_token={'present' if token else 'MISSING'}")
    if not token:
        log("[auth] no subscription token — a real resident could not take a turn.")
        # The spike still proves the JOSHI-side plumbing below; keep going.

    # 2. Pair, exactly like the cockpit.
    session = JoshiCoreSession(args.listen, args.origin)
    descriptor = session.pair(args.code)
    log(f"[pair] session_id={descriptor['sessionId']}")
    log(f"[pair] scopes={session.scopes} authority={descriptor['authority']}")

    # 3. Read the scene through cockpit-read.
    snapshot = session.read_scene(args.scene)
    view = snapshot["view"]
    scene_id = view["sceneId"]
    # The scene reference the command must echo is (sceneId, viewDigest). The view
    # carries no digest of itself; the snapshot envelope's snapshotDigest IS the
    # sha256 over the exact view bytes, which is what the server compares against.
    view_digest = snapshot["snapshotDigest"]
    candidates = view["payload"]["candidates"]
    candidate = candidates[0]
    candidate_id = candidate["id"]
    candles = candidate.get("candles", [])
    log(f"[read] scene={scene_id} digest={view_digest[:23]}...")
    log(f"[read] candidate={candidate_id} symbol={candidate.get('symbol')} bars={len(candles)}")

    # Anchor the annotation at a REAL observed bar time — honest evidence, not a
    # made-up instant. Fall back to now() only if the series is empty.
    if candles:
        mid = candles[len(candles) // 2]
        anchor_at = _bar_instant(mid.get("timeUnix") or mid.get("time_unix"))
        anchor_note = "resident-observed: midpoint of the retained 1m window"
    else:
        anchor_at = joshi_evidence.wire_now()
        anchor_note = "resident-observed: no price series in scene"

    # 4. Write ONE honest annotation through operator-evidence-write.
    context = joshi_evidence.capture_context(
        ui_label="Resident annotation",
        why_now="First embedded-resident evidence write: proving an agent can "
                "record an observation through the same admission route as the cockpit.",
        note=anchor_note,
        confidence_ppm="500000",
        urgency="normal",
    )
    command_id = opaque("command-resident")
    body = joshi_evidence.record_annotation_command(
        scene_id=scene_id,
        view_digest=view_digest,
        candidate_id=candidate_id,
        series_id="observed-price-sol",
        anchor_at=anchor_at,
        context=context,
        annotation_id=opaque("chart-annotation"),
        command_id=command_id,
        idempotency_key=opaque("retry"),
        client_session_id=opaque("resident-session"),
        client_command_seq=1,
        clock_id=opaque("resident-clock"),
        monotonic_ns=joshi_evidence.monotonic_ns(),
        issued_at=joshi_evidence.wire_now(),
    )
    log(f"[write] posting record_annotation ({len(body)} canonical bytes)")
    status, receipt = session.append_command(body)
    log(f"[write] HTTP {status}")
    log(f"[write] receipt: {json.dumps(receipt, indent=2)[:900]}")
    if status not in (200, 202):
        code = receipt.get("code")
        if code == "operator_commit_rejected":
            log("[write] REFUSED at commit (NOT at admission/parse — the canonical")
            log("        bytes were accepted). Known cause when the served scene's only")
            log("        subject is an OPERATOR-ATTESTED candle binding: its evidence id is")
            log("        a synthesized '<obs>:operator-attested-subject' with no backing")
            log("        observation row, and commit_operator_v1 -> validate_glass_view_as_known")
            log("        requires every evidence reference to resolve to a durable observation.")
            log("        The snapshot READ path skips that check, so the scene serves fine.")
            log("        Point this spike at a scene with an OBSERVED (chain-frame) subject to")
            log("        get a durable receipt. This is a scene-content constraint, not auth.")
        else:
            log("[write] REFUSED — see problem above.")
        return 1
    log(f"[write] durable commitSeq={receipt.get('commitSeq')} "
        f"status={receipt.get('status')} commandId={receipt.get('commandId')}")

    # Idempotent replay: exact same bytes must return the same durable closure.
    status2, receipt2 = session.append_command(body)
    log(f"[replay] HTTP {status2} status={receipt2.get('status')} "
        f"commitSeq={receipt2.get('commitSeq')} (unchanged: "
        f"{receipt2.get('commitSeq') == receipt.get('commitSeq')})")
    return 0


def _find_candidates(node):
    if isinstance(node, dict):
        if "candidates" in node and isinstance(node["candidates"], list):
            return node["candidates"]
        for value in node.values():
            found = _find_candidates(value)
            if found:
                return found
    return []


def _bar_instant(time_unix: str) -> str:
    # candle timeUnix is epoch seconds as a string; render as a wire instant.
    from datetime import datetime, timezone
    seconds = int(time_unix)
    dt = datetime.fromtimestamp(seconds, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "000000Z"


if __name__ == "__main__":
    raise SystemExit(main())
