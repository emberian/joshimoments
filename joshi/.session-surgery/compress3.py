"""Compression pass for the 2026-08-25 curation.

Priority order, most protected first (unchanged from compress2.py's doctrine):
  1. Ember's own turns — untouched. Smallest layer, highest value.
  2. Deputy briefs and reports — the coordination texture and the primary findings.
  3. The assistant's replies — the most redundant layer, since they restate the reports.

Only outliers are touched; the many short exchanges pass through whole.
"""
import json, os, re, sys, uuid as u

F = sys.argv[1]
SIGNAL = re.compile(
    r"^\s*(#{1,4}\s|\*\*|[-*]\s+\*\*|\|)"
    r"|\b(pushback|refus|undecidable|corrected|wrong|cannot|never|absent|measured|"
    r"negative|caveat|honest|however|verdict|but )\b", re.IGNORECASE)


def squeeze(text, budget):
    if len(text) <= budget:
        return text
    lines = [l for l in text.split("\n") if l.strip()]
    head, n = [], 0
    for l in lines:
        head.append(l)
        n += len(l) + 1
        if n > budget * 0.5:
            break
    sig = [l.strip() for l in lines[len(head):] if SIGNAL.search(l) and len(l.strip()) > 3]
    out = "\n".join(head)
    room = budget - len(out)
    keep = []
    for l in sig:
        if room - len(l) < 0:
            break
        keep.append(l)
        room -= len(l) + 1
    if keep:
        out += "\n· " + "\n· ".join(keep)
    return out + f"\n[…{max(0, len(text) - len(out))} elided]"


recs = [json.loads(l) for l in open(F)]
before = after = 0
out = []
for d in recs:
    m = d.get("message") or {}
    c = m.get("content")
    is_user = d.get("type") == "user"

    if isinstance(c, str):
        before += len(c)
        if "task-notification" in c[:400]:
            c = squeeze(c, 2400)          # deputy report
        elif not is_user and len(c) > 1600:
            c = squeeze(c, 1400)          # assistant prose
        after += len(c)
        d = dict(d); d["message"] = dict(m); d["message"]["content"] = c
        out.append(d); continue

    if isinstance(c, list):
        newc = []
        for b in c:
            before += len(json.dumps(b))
            bt = b.get("type")
            if bt == "text":
                t = b.get("text", "")
                if is_user:
                    if "task-notification" in t[:400]:
                        b = dict(b); b["text"] = squeeze(t, 2400)
                    # else: her words, untouched
                elif len(t) > 1600:
                    b = dict(b); b["text"] = squeeze(t, 1400)
            elif bt == "tool_use" and b.get("name") in ("Agent", "SendMessage"):
                inp = dict(b.get("input") or {})
                for field in ("prompt", "message"):
                    if field in inp and isinstance(inp[field], str):
                        inp[field] = squeeze(inp[field], 2600)   # briefs stay rich
                b = dict(b); b["input"] = inp
            elif bt == "tool_result":
                s = b.get("content")
                if isinstance(s, str) and len(s) > 700:
                    b = dict(b); b["content"] = s[:700] + " […elided]"
            after += len(json.dumps(b))
            newc.append(b)
        d = dict(d); d["message"] = dict(m); d["message"]["content"] = newc
        out.append(d); continue

    out.append(d)

prev = None
with open(F, "w") as fh:
    for d in out:
        d["uuid"] = str(u.uuid4())
        d["parentUuid"] = prev
        prev = d["uuid"]
        fh.write(json.dumps(d) + "\n")

print(f"content {before/1000:.0f}k -> {after/1000:.0f}k chars  (~{before//4//1000}k -> ~{after//4//1000}k tokens)")
print(f"file {os.path.getsize(F)/1e6:.2f} MB")
