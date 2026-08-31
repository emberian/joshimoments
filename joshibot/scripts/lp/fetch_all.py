import json
import os
import time
import urllib.request

KEY=open(os.path.expanduser("~/.helius-key")).read().strip()
URL=f"https://mainnet.helius-rpc.com/?api-key={KEY}"
sigs=json.load(open("wallet_sigs.json"))
def post(p,tries=6):
    for a in range(tries):
        try:
            r=urllib.request.Request(URL,data=json.dumps(p).encode(),headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(r,timeout=120) as f: return json.load(f)
        except Exception:
            if a==tries-1: raise
            time.sleep(0.5*2**a)
out={}
for i in range(0,len(sigs),20):
    batch=[{"jsonrpc":"2.0","id":j,"method":"getTransaction",
            "params":[s,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]}
           for j,s in enumerate(sigs[i:i+20])]
    res=post(batch)
    for item in (res if isinstance(res,list) else [res]):
        tx=(item or {}).get("result")
        if tx: out[tx["transaction"]["signatures"][0]]=tx
    time.sleep(0.12)
    if i % 100 == 0: print(f"  {i}/{len(sigs)}", flush=True)
json.dump(out, open("wallet_txs.json","w"))
print(f"cached {len(out)} transactions -> wallet_txs.json")
