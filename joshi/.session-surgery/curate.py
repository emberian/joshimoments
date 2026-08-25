"""Compose a curated, resumable session from 5f1f382e.

Keeps the trajectory's tacit content — Ember's turns, the assistant's replies, the
31 deputy briefs (Agent tool calls), and the deputy reports that came back as
task-notifications — and drops build-log noise, harness metadata, images, and old
chain-of-thought.

Also condenses one span. The completed pump.fun sign-in work is summarized in a
single marked turn instead of carried verbatim: it is finished, committed, and
self-documenting in crates/joshi-pump-api/src/auth_session.rs, and a resumed
context does not need its mechanics. The condensation is marked in-line so nobody
mistakes it for a verbatim exchange.
"""
import json, sys, uuid as uuidlib

SRC = "~/.claude/projects/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df.jsonl"
NEW_ID = sys.argv[1] if len(sys.argv) > 1 else str(uuidlib.uuid4())
OUT = f"~/.claude/projects/-Users-you-dev-joshi/{NEW_ID}.jsonl"

CONDENSE_START, CONDENSE_END = 3500, 3616

BRIDGE_USER = (
    "[condensed span — the original exchange here is replaced by this summary]\n\n"
    "Can we reach the authenticated pump.fun routes as me, read-only?"
)
BRIDGE_ASST = (
    "[condensed span — this replaces the working exchange; the implementation is committed "
    "and self-documenting]\n\n"
    "Yes. JOSHI can now hold an authenticated pump.fun session as you, read-only, using the "
    "provider's ordinary sign-in flow. It is implemented in `crates/joshi-pump-api/src/auth_session.rs`, "
    "whose module doc states the boundary: it authenticates and nothing else, it touches read-only "
    "routes only, and credentials are held in redacted types that are never serialized, logged, or "
    "written to disk.\n\n"
    "What it unlocked: the **global callout leaderboard**, which returns 401 to anonymous callers. "
    "That is the fan-out root the callout-science lane needed — top callers, each with their "
    "`topCallouts` carrying `coinMint`, `calloutPrice`, `multiple`, `createdAt` and their `thesis` "
    "in their own words. Community-documented paths for it on other hosts are stale (404).\n\n"
    "Also mapped: `/auth/my-profile`, `/following/{userId}` and `/coins/currently-live` answer 200 "
    "authenticated; `/notifications`, `/watchlist` and `/coins/for-you` are 404 — stale or "
    "app-only. The trust posture is deliberately three-tier: the browser companion touches no auth "
    "material at all, anonymous product reads stay anonymous, and authenticated access is its own "
    "gated lane so 'JOSHI acting as Ember' is never something that happens by accident."
)


def main():
    lines = open(SRC).readlines()
    recs = []
    for i, line in enumerate(lines):
        try:
            recs.append((i, json.loads(line)))
        except json.JSONDecodeError:
            pass

    keep_tool_ids = set()
    for _, d in recs:
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use" and b.get("name") == "Agent":
                    keep_tool_ids.add(b.get("id"))

    out, dropped, condensed_done = [], 0, False
    for i, d in recs:
        t = d.get("type")
        if t not in ("user", "assistant"):
            dropped += 1
            continue

        if CONDENSE_START <= i <= CONDENSE_END:
            if not condensed_done:
                condensed_done = True
                for role, text in (("user", BRIDGE_USER), ("assistant", BRIDGE_ASST)):
                    r = dict(d)
                    r["type"] = role
                    r["message"] = {"role": role, "content": text} if role == "user" else {
                        "role": "assistant", "content": [{"type": "text", "text": text}],
                        "model": d.get("message", {}).get("model", "claude-opus-4-6"),
                    }
                    r.pop("toolUseResult", None)
                    out.append(r)
            else:
                dropped += 1
            continue

        m = d.get("message") or {}
        c = m.get("content")

        if isinstance(c, str):
            out.append(d)
            continue

        if not isinstance(c, list):
            dropped += 1
            continue

        kept = []
        for b in c:
            bt = b.get("type")
            if bt == "text":
                kept.append(b)
            elif bt == "thinking":
                continue
            elif bt == "image":
                continue
            elif bt == "tool_use":
                if b.get("id") in keep_tool_ids:
                    kept.append(b)
            elif bt == "tool_result":
                s = str(b.get("content", ""))
                if b.get("tool_use_id") in keep_tool_ids:
                    kept.append(b)
                elif "task-notification" in s:
                    kept.append({"type": "text", "text": s[:20000]})
            else:
                continue

        if not kept:
            dropped += 1
            continue
        # A user record must not become a bare text block list with no tool_result pairing issue;
        # convert result-only user records that we rewrote into plain text messages.
        if t == "user" and all(b.get("type") == "text" for b in kept):
            r = dict(d)
            r["message"] = {"role": "user", "content": "\n\n".join(b["text"] for b in kept)}
            r.pop("toolUseResult", None)
            out.append(r)
            continue

        r = dict(d)
        r["message"] = dict(m)
        r["message"]["content"] = kept
        r.pop("toolUseResult", None)
        out.append(r)

    prev = None
    with open(OUT, "w") as fh:
        for r in out:
            r["sessionId"] = NEW_ID
            if "session_id" in r:
                r["session_id"] = NEW_ID
            r["uuid"] = str(uuidlib.uuid4())
            r["parentUuid"] = prev
            prev = r["uuid"]
            fh.write(json.dumps(r) + "\n")

    import os
    print(f"new session: {NEW_ID}")
    print(f"records: {len(recs)} -> {len(out)}  (dropped {dropped})")
    print(f"bytes: {os.path.getsize(SRC)/1e6:.2f} MB -> {os.path.getsize(OUT)/1e6:.2f} MB")
    print(f"agent briefs preserved: {len(keep_tool_ids)}")


if __name__ == "__main__":
    main()
