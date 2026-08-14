import json, collections, datetime
FUND="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
txs=json.load(open("wallet_txs.json"))
SYM={"XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump":"DREGG",
     "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump":"weave",
     "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump":"nosis"}
def sym(m): return SYM.get(m,m[:8])
inflow=collections.Counter(); outflow=collections.Counter(); srcs=collections.Counter()
for tx in sorted(txs.values(), key=lambda t:t.get("blockTime") or 0):
    for ix in (tx["transaction"]["message"].get("instructions") or []) + \
              [i for g in (tx["meta"].get("innerInstructions") or []) for i in (g.get("instructions") or [])]:
        p=ix.get("parsed")
        if not isinstance(p,dict): continue
        if p.get("type") not in ("transfer","transferChecked"): continue
        info=p.get("info") or {}
        mint=info.get("mint")
        if not mint: continue
        amt=info.get("tokenAmount") or {}
        raw=int(amt.get("amount") or info.get("amount") or 0)
        if not raw: continue
        # authority/owner based direction
        if info.get("authority")==FUND or info.get("owner")==FUND: outflow[mint]+=raw
        else: inflow[mint]+=raw; srcs[info.get("authority") or info.get("source","?")]+=1
print("TOKEN inflows to the fund wallet (raw units, /1e6):")
for m,v in inflow.most_common(6): print(f"   {sym(m):>8} {v/1e6:+15,.0f}")
print("\nTOKEN outflows from the fund wallet:")
for m,v in outflow.most_common(6): print(f"   {sym(m):>8} {v/1e6:+15,.0f}")
print("\ntop inbound token senders:")
for s,n in srcs.most_common(6): print(f"   {n:4}x  {s}")
