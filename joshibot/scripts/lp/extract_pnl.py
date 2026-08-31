import collections
import datetime
import json

DLMM="LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
FUND="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
txs=json.load(open("wallet_txs.json")); positions=json.load(open("positions.json"))
POSSET=set(positions)
def instrs(tx):
    out=list(tx["transaction"]["message"].get("instructions") or [])
    for inner in (tx["meta"].get("innerInstructions") or []): out+= inner.get("instructions") or []
    return out
# how many positions does each tx touch?
tx_positions=collections.defaultdict(set)
for sig,tx in txs.items():
    for ix in instrs(tx):
        if ix.get("programId")!=DLMM: continue
        for a in (ix.get("accounts") or []):
            if a in POSSET: tx_positions[sig].add(a)
shared=sum(1 for s,p in tx_positions.items() if len(p)>1)
print(f"txs touching a position : {len(tx_positions)}   of which multi-position: {shared}")
clean=[a for a,v in positions.items() if all(len(tx_positions.get(s,()))==1 for s in v["sigs"])]
print(f"positions whose txs are ALL single-position (cleanly attributable): {len(clean)}/{len(positions)}")

def deltas(sig):
    tx=txs[sig]; m=tx["meta"]
    keys=[k["pubkey"] if isinstance(k,dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    sol=0
    if FUND in keys:
        i=keys.index(FUND); sol=m["postBalances"][i]-m["preBalances"][i]
    pre={(b["owner"],b["mint"]):int(b["uiTokenAmount"]["amount"]) for b in (m.get("preTokenBalances") or [])}
    post={(b["owner"],b["mint"]):int(b["uiTokenAmount"]["amount"]) for b in (m.get("postTokenBalances") or [])}
    tok=collections.Counter()
    for k in set(pre)|set(post):
        if k[0]!=FUND: continue
        d=post.get(k,0)-pre.get(k,0)
        if d: tok[k[1]]+=d
    return sol,tok

rows=[]
for a,v in positions.items():
    if a not in clean: continue
    sol=0; tok=collections.Counter()
    for s in v["sigs"]:
        ds,dt=deltas(s); sol+=ds; tok.update(dt)
    dur=(v["closed"]-v["opened"])/3600 if v["closed"] else None
    rows.append((a,v["opened"],dur,sol,dict(tok),len(v["sigs"])))
rows.sort(key=lambda r:r[1])
print(f"\ncleanly-attributable closed positions: {len([r for r in rows if r[2] is not None])}")
print(f"{'position':13} {'opened':11} {'hrs':>6} {'net SOL':>10}  net token deltas")
for a,op,dur,sol,tok,_n in rows:
    d=datetime.datetime.fromtimestamp(op,datetime.UTC)
    ts=" ".join(f"{m[:6]}…{v/1e6:+,.0f}" for m,v in sorted(tok.items(),key=lambda kv:-abs(kv[1]))[:3])
    print(f"{a[:11]}… {d:%m-%d %H:%M} {dur if dur else 0:6.1f} {sol/1e9:+10.4f}  {ts}")
json.dump([{"pos":a,"opened":op,"hours":dur,"sol":sol,"tokens":tok,"txs":n} for a,op,dur,sol,tok,n in rows],
          open("pnl_rows.json","w"))
