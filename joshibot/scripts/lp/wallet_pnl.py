import datetime
import json

FUND="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
DLMM="LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
txs=json.load(open("wallet_txs.json"))
ordered=sorted(txs.values(), key=lambda t: t.get("blockTime") or 0)
first,last=ordered[0],ordered[-1]
def bal(tx,which):
    keys=[k["pubkey"] if isinstance(k,dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    i=keys.index(FUND); return tx["meta"][which][i]
start=bal(first,"preBalances"); end=bal(last,"postBalances")
print(f"window: {datetime.datetime.fromtimestamp(first['blockTime'],datetime.UTC):%Y-%m-%d} "
      f"→ {datetime.datetime.fromtimestamp(last['blockTime'],datetime.UTC):%Y-%m-%d}  ({len(txs)} txs)")
print(f"SOL balance  start {start/1e9:.4f}   end {end/1e9:.4f}   change {(end-start)/1e9:+.4f}\n")
# large plain SOL transfers in/out (external funding), i.e. system-program transfers
ext_in=[]; ext_out=[]
for tx in ordered:
    for ix in (tx["transaction"]["message"].get("instructions") or []):
        p=ix.get("parsed")
        if not isinstance(p,dict) or p.get("type")!="transfer": continue
        info=p.get("info") or {}
        lam=int(info.get("lamports") or 0)
        if lam < 0.02e9: continue
        if info.get("destination")==FUND: ext_in.append((tx["blockTime"],lam,info.get("source")))
        if info.get("source")==FUND: ext_out.append((tx["blockTime"],lam,info.get("destination")))
print(f"plain SOL transfers IN  : {len(ext_in):3}  total {sum(l for _,l,_ in ext_in)/1e9:8.3f} SOL")
for t,l,s in sorted(ext_in,key=lambda x:-x[1])[:5]:
    print(f"    {datetime.datetime.fromtimestamp(t,datetime.UTC):%m-%d %H:%M}  {l/1e9:8.3f} from {s[:12]}…")
print(f"plain SOL transfers OUT : {len(ext_out):3}  total {sum(l for _,l,_ in ext_out)/1e9:8.3f} SOL")
for t,l,d in sorted(ext_out,key=lambda x:-x[1])[:5]:
    print(f"    {datetime.datetime.fromtimestamp(t,datetime.UTC):%m-%d %H:%M}  {l/1e9:8.3f} to   {d[:12]}…")
