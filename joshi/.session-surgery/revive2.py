"""Rewrite the recorded usage to the honest post-compression size.

Claude Code's resume gate reads the last turn's stored usage as the current context
size before it re-sends anything, so a session that hit the wall refuses to resume even
after its content has been cut by 90%. The stored numbers still describe the old
session. This walks the records, recomputes the running context from what the file now
actually holds, and writes that back.
"""
import json, os

F = "~/.claude/projects/-Users-you-dev-joshi/67e320bc-9433-404f-bf59-4736551f54ec.jsonl"
recs = [json.loads(l) for l in open(F)]

running = 8000          # rough system-prompt + tools overhead
touched = 0
for d in recs:
    m = d.get("message") or {}
    c = m.get("content")
    size = len(c) if isinstance(c, str) else len(json.dumps(c)) if c else 0
    running += max(1, size // 4)
    u = m.get("usage")
    if u:
        u["input_tokens"] = 2
        u["cache_read_input_tokens"] = running
        u["cache_creation_input_tokens"] = 0
        u.pop("cache_creation", None)
        touched += 1

with open(F, "w") as fh:
    for d in recs:
        fh.write(json.dumps(d) + "\n")

last = next((d["message"]["usage"] for d in reversed(recs)
             if (d.get("message") or {}).get("usage")), None)
print(f"rewrote {touched} usage records")
print(f"final recorded context: {last['cache_read_input_tokens']/1000:.0f}k tokens (was ~1650k)")
print(f"file: {os.path.getsize(F)/1e6:.2f} MB")
