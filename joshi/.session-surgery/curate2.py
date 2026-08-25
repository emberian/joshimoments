"""Compose a curated, resumable session from 8f1bedc9 (the 2026-08-24/25 arc).

Second generation of the surgery in curate.py. Same principle, stated by Ember when she
asked for the first one: "you can put together a new session transcript that is only the
good stuff."

KEPT — the layers a summary cannot carry:
  1. Ember's own turns, verbatim and untouched.
  2. Deputy briefs (Agent tool calls) and the reports that came back (task-notifications).
     This arc ran 48 briefs and 9 SendMessage redirects; the coordination texture IS the
     trajectory.
  3. The assistant's replies — the reasoning and the corrections.

DROPPED — recoverable from the repo, or noise:
  build logs, gate output, file payloads, Bash/Edit/Read/Write calls, images, and old
  chain-of-thought.

A framing note is prepended, and the standing instructions that were NOT yet executed when
the arc ended are appended so they cannot be lost in the seam.
"""
import json, os, sys, uuid as uuidlib

SRC = "~/.claude/projects/-Users-you-dev-joshi/8f1bedc9-0a94-40bc-90b0-2e3ac40d6f60.jsonl"
NEW_ID = sys.argv[1] if len(sys.argv) > 1 else str(uuidlib.uuid4())
OUT = f"~/.claude/projects/-Users-you-dev-joshi/{NEW_ID}.jsonl"

KEEP_TOOLS = ("Agent", "SendMessage")

HEAD_NOTE = """[This session is a curated continuation, composed 2026-08-25 from the working
trajectory of the session before it, which filled its context window. It is not verbatim.

What was kept: Ember's turns, the assistant's replies, all 48 deputy briefs (Agent tool
calls), the 9 mid-flight SendMessage redirects, and the deputy reports that came back —
i.e. the reasoning and the agent-coordination texture, which is the part a summary cannot
carry.

What was dropped: build logs, gate output, tool payloads, screenshots, and old
chain-of-thought.

Orientation lives in HANDOFF.md and GOAL.md at the repo root; docs/planning/REORIENTATION.md
holds the forward program and docs/reference/PUMP_API_MAP.md the provider surface. The repo
is the source of truth. Everything below is real work that actually happened, in the order
it happened.]"""

TAIL_NOTE = """[Appended 2026-08-25 during the curation, so the seam cannot swallow them.
These are STANDING and UNEXECUTED — read them before picking up work.]

1. THE COPY PASS — DONE at the seam, and the principle stands for all future copy.
   Her words: "do you see how EVERY SENTENCE IS DISCLAIMING 'IS NOT IS NOT'? ... PLEASE do
   a pass over all copy and just omit all of that. it's so needless." 41 strings across 16
   files were trimmed; capability boundaries, consequences, and staleness facts were kept.
   Honesty belongs in STRUCTURE — the dash for absent, the chip, provenance one hover away
   — never in a sentence narrating what the screen does not claim. Write new copy that way.

2. THE BLOCKING BUG: a `;` hold on a live board candidate is refused by core with 422
   ("operator command append failed"), and the session's pairing store holds ZERO committed
   acts. The client path works; core refuses. Two candidate codes — `invalid_operator_command`
   (wire validation) and `operator_commit_rejected` (store admission); the detail string
   decides. Because no act commits, the `'` inspect → hot-taps → candles loop cannot fire
   either, which is why she pressed `'` and saw no candles. Fix this first: it is the thing
   standing between her and the chair. HANDOFF.md carries the reproduction recipe.

3. Two smaller live gaps: presentation append 404 in follow mode (scope now granted, route
   not mounted — feature-detect or wire it), and venue-readout NetworkError on held coins.

4. In flight when the arc ended, harvestable via cv: the LP desk's floor-free both-sides
   recount (her chart-based pushback) plus a measured DAMMv2 arm; the workability census
   (her design: ~300 mints + ~100 callouts, statistics → autostrat-harvest interaction
   test); and a coin-communities auth deputy holding at its boundary gate, having proven the
   handshake signs a TEXT CHALLENGE, never a transaction, and asking whether to proceed.

5. Tapes from this arc live in the session scratchpad under /private/tmp — duck-tape,
   kylie-backfill, fleet-tape-1, the grid panels, scalplab-v1-run. tmp evaporates; move what
   the lab needs somewhere durable."""


def synth(template, role, text):
    r = dict(template)
    r["type"] = role
    r.pop("toolUseResult", None)
    if role == "user":
        r["message"] = {"role": "user", "content": text}
    else:
        r["message"] = {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "model": (template.get("message") or {}).get("model", "claude-opus-4-6"),
        }
    return r


def main():
    recs = []
    for line in open(SRC):
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    keep_ids = set()
    for d in recs:
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use" and b.get("name") in KEEP_TOOLS:
                    keep_ids.add(b.get("id"))

    out, dropped = [], 0
    for d in recs:
        if d.get("type") not in ("user", "assistant"):
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
            elif bt in ("thinking", "image"):
                continue
            elif bt == "tool_use":
                if b.get("id") in keep_ids:
                    kept.append(b)
            elif bt == "tool_result":
                s = str(b.get("content", ""))
                if b.get("tool_use_id") in keep_ids:
                    kept.append(b)
                elif "task-notification" in s:
                    kept.append({"type": "text", "text": s[:20000]})

        if not kept:
            dropped += 1
            continue

        # A user record whose kept blocks are all text becomes a plain text message, so no
        # tool_result dangles without its call.
        if d.get("type") == "user" and all(b.get("type") == "text" for b in kept):
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

    first = out[0] if out else recs[0]
    out.insert(0, synth(first, "user", HEAD_NOTE))
    out.append(synth(first, "user", TAIL_NOTE))

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

    print(f"new session: {NEW_ID}")
    print(f"records: {len(recs)} -> {len(out)}  (dropped {dropped})")
    print(f"bytes: {os.path.getsize(SRC)/1e6:.2f} MB -> {os.path.getsize(OUT)/1e6:.2f} MB")
    print(f"briefs + redirects preserved: {len(keep_ids)}")


if __name__ == "__main__":
    main()
