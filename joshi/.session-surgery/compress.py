"""Second pass: compress the curated session to a size that actually resumes.

Ember's own turns are never touched. Everything else is reduced by keeping the parts
that carry meaning — the opening claim, section headers, bolded findings, and any line
that reads as a refusal or a correction — and dropping the file lists, gate output, and
tables that a resumed context does not need.
"""
import json, re, sys

F = "~/.claude/projects/-Users-you-dev-joshi/8f1bedc9-0a94-40bc-90b0-2e3ac40d6f60.jsonl"

# Records that are pure harness/skill noise, not conversation.
NOISE = ("Base directory for this skill:", "<system-reminder>", "Caveat: The messages below")

SIGNAL = re.compile(
    r"^\s*(#{1,4}\s|\*\*|[-*]\s+\*\*|\|)"          # headers, bold, bold bullets, tables
    r"|\b(pushback|refus|undecidable|correct|wrong|cannot|never|absent|"
    r"negative result|caveat|honest|but |however)\b",
    re.IGNORECASE,
)

def compress(text, budget):
    if len(text) <= budget:
        return text
    lines = text.split("\n")
    head = []
    n = 0
    for ln in lines:                      # always keep the opening — it carries the claim
        head.append(ln); n += len(ln) + 1
        if n > budget * 0.35: break
    rest = lines[len(head):]
    kept, n2 = [], 0
    for ln in rest:
        if SIGNAL.search(ln) and len(ln.strip()) > 3:
            kept.append(ln.strip()); n2 += len(ln) + 1
            if n2 > budget * 0.55: break
    out = "\n".join(head)
    if kept:
        out += "\n\n[compressed — signal lines retained]\n" + "\n".join(kept)
    return out + f"\n\n[…{len(text)-len(out)} chars elided]"

def main():
    recs = [json.loads(l) for l in open(F)]
    before = after = 0
    out = []
    for d in recs:
        m = d.get("message") or {}
        c = m.get("content")

        if isinstance(c, str):
            before += len(c)
            if any(s in c[:400] for s in NOISE) and len(c) > 4000:
                continue                                    # drop skill/system dumps
            if "task-notification" in c:
                c = compress(c, 2600)                       # deputy reports
            elif len(c) > 6000:
                c = compress(c, 2600)                       # long pasted user text
            # short human turns fall through untouched
            after += len(c)
            d = dict(d); d["message"] = dict(m); d["message"]["content"] = c
            out.append(d); continue

        if isinstance(c, list):
            newc = []
            for b in c:
                before += len(json.dumps(b))
                if b.get("type") == "text":
                    b = dict(b); b["text"] = compress(b["text"], 2200)
                elif b.get("type") == "tool_use" and b.get("name") == "Agent":
                    inp = dict(b.get("input") or {})
                    if "prompt" in inp:
                        inp["prompt"] = compress(inp["prompt"], 3200)   # keep briefs richer
                    b = dict(b); b["input"] = inp
                elif b.get("type") == "tool_result":
                    s = b.get("content")
                    if isinstance(s, str) and len(s) > 900:
                        b = dict(b); b["content"] = s[:900] + " […elided]"
                after += len(json.dumps(b))
                newc.append(b)
            d = dict(d); d["message"] = dict(m); d["message"]["content"] = newc
            out.append(d); continue

        out.append(d)

    import uuid as u, os
    prev = None
    with open(F, "w") as fh:
        for d in out:
            d["uuid"] = str(u.uuid4()); d["parentUuid"] = prev; prev = d["uuid"]
            fh.write(json.dumps(d) + "\n")
    print(f"records {len(recs)} -> {len(out)}")
    print(f"content {before/1000:.0f}k -> {after/1000:.0f}k chars  (~{before//4//1000}k -> ~{after//4//1000}k tokens)")
    print(f"file {os.path.getsize(F)/1e6:.2f} MB")

main()
