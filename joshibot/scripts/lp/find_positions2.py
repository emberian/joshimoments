import json, collections, datetime
DLMM="LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
FUND="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
txs=json.load(open("wallet_txs.json"))
# A position ACCOUNT IS CREATED: pre-balance 0, post-balance = rent, in some tx.
created={}; closed={}
for sig,tx in txs.items():
    keys=[k["pubkey"] if isinstance(k,dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    pre,post=tx["meta"]["preBalances"],tx["meta"]["postBalances"]
    bt=tx.get("blockTime") or 0
    for i,k in enumerate(keys):
        if pre[i]==0 and 0.05e9 <= post[i] <= 0.07e9:
            created.setdefault(k,(bt,sig))
        if post[i]==0 and 0.05e9 <= pre[i] <= 0.07e9:
            closed.setdefault(k,(bt,sig))
# keep only those that actually appear inside a DLMM instruction
def instrs(tx):
    out=list(tx["transaction"]["message"].get("instructions") or [])
    for inner in (tx["meta"].get("innerInstructions") or []): out+= inner.get("instructions") or []
    return out
dlmm_accts=set()
for sig,tx in txs.items():
    for ix in instrs(tx):
        if ix.get("programId")==DLMM: dlmm_accts.update(ix.get("accounts") or [])
positions={k:v for k,v in created.items() if k in dlmm_accts}
print(f"accounts created with position-sized rent : {len(created)}")
print(f"  ...and referenced by a DLMM instruction : {len(positions)}")
print(f"  ...of those, later closed               : {sum(1 for k in positions if k in closed)}")
# per-position transaction sets
bysig=collections.defaultdict(list)
for sig,tx in txs.items():
    for ix in instrs(tx):
        if ix.get("programId")!=DLMM: continue
        for a in (ix.get("accounts") or []):
            if a in positions: bysig[a].append(sig)
out={}
for a,(bt,sig) in sorted(positions.items(), key=lambda kv: kv[1][0]):
    sigs=sorted(set(bysig[a]), key=lambda s: txs[s].get("blockTime") or 0)
    out[a]={"opened":bt,"closed":closed.get(a,(None,None))[0],"sigs":sigs}
json.dump(out, open("positions.json","w"))
print(f"\n{len(out)} positions, oldest first:")
for a,v in list(out.items()):
    o=datetime.datetime.fromtimestamp(v["opened"],datetime.UTC)
    c=datetime.datetime.fromtimestamp(v["closed"],datetime.UTC) if v["closed"] else None
    life=f"{(v['closed']-v['opened'])/3600:6.1f}h" if v["closed"] else "   open"
    print(f"  {a[:11]}…  {o:%m-%d %H:%M} -> {c.strftime('%m-%d %H:%M') if c else '  (open)  '}  {life}  {len(v['sigs']):3} txs")
