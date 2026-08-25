"""Third pass. Priority order, most protected first:
  1. Ember's own turns — untouched, they are the smallest and most valuable layer.
  2. Deputy briefs and reports — the coordination texture and the primary findings.
  3. The assistant's replies — the most redundant layer, since they restate the reports.
"""
import json, re, uuid as u, os

F = "~/.claude/projects/-Users-you-dev-joshi/8f1bedc9-0a94-40bc-90b0-2e3ac40d6f60.jsonl"
SIGNAL = re.compile(
    r"^\s*(#{1,4}\s|\*\*|[-*]\s+\*\*)"
    r"|\b(pushback|refus|undecidable|corrected|wrong|cannot|never|absent|"
    r"negative|caveat|honest|however)\b", re.IGNORECASE)

def squeeze(text, budget):
    if len(text) <= budget: return text
    lines = [l for l in text.split("\n") if l.strip()]
    head, n = [], 0
    for l in lines:
        head.append(l); n += len(l)+1
        if n > budget*0.45: break
    sig = [l.strip() for l in lines[len(head):] if SIGNAL.search(l) and len(l.strip())>3]
    out = "\n".join(head)
    room = budget - len(out)
    keep = []
    for l in sig:
        if room - len(l) < 0: break
        keep.append(l); room -= len(l)+1
    if keep: out += "\n· " + "\n· ".join(keep)
    return out + f"\n[…{max(0,len(text)-len(out))} elided]"

recs = [json.loads(l) for l in open(F)]
out = []
for d in recs:
    m = d.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        if "task-notification" in c:
            c = squeeze(c, 1250)                 # deputy reports
        # Ember's own turns: left exactly as they are
        d = dict(d); d["message"] = dict(m); d["message"]["content"] = c
        out.append(d); continue
    if isinstance(c, list):
        newc = []
        for b in c:
            t = b.get("type")
            if t == "text":
                b = dict(b); b["text"] = squeeze(b["text"], 520)
            elif t == "tool_use" and b.get("name") == "Agent":
                inp = dict(b.get("input") or {})
                if "prompt" in inp: inp["prompt"] = squeeze(inp["prompt"], 1500)
                b = dict(b); b["input"] = inp
            elif t == "tool_result":
                s = b.get("content")
                if isinstance(s, str) and len(s) > 200:
                    b = dict(b); b["content"] = s[:200] + " […]"
            newc.append(b)
        d = dict(d); d["message"] = dict(m); d["message"]["content"] = newc
        out.append(d); continue
    out.append(d)

prev = None
with open(F, "w") as fh:
    for d in out:
        d["uuid"] = str(u.uuid4()); d["parentUuid"] = prev; prev = d["uuid"]
        fh.write(json.dumps(d) + "\n")

tot = 0
for d in out:
    c = (d.get("message") or {}).get("content")
    tot += len(c) if isinstance(c, str) else len(json.dumps(c))
print(f"records {len(out)}  content {tot/1000:.0f}k chars  ~{tot//4//1000}k tokens  file {os.path.getsize(F)/1e6:.2f} MB")
