import json, os, time, urllib.request
KEY=open(os.path.expanduser("~/.helius-key")).read().strip()
URL=f"https://mainnet.helius-rpc.com/?api-key={KEY}"
FUND="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
def post(p,tries=5):
    for a in range(tries):
        try:
            r=urllib.request.Request(URL,data=json.dumps(p).encode(),headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(r,timeout=90) as f: return json.load(f)
        except Exception as e:
            if a==tries-1: raise
            time.sleep(0.4*2**a)
sigs=[]; before=None
while True:
    p={"limit":1000}
    if before: p["before"]=before
    got=post({"jsonrpc":"2.0","id":1,"method":"getSignaturesForAddress","params":[FUND,p]})["result"]
    if not got: break
    sigs+=got; before=got[-1]["signature"]
    if len(got)<1000: break
ok=[s for s in sigs if not s.get("err")]
import datetime
bt=[s["blockTime"] for s in sigs if s.get("blockTime")]
print(f"total signatures : {len(sigs)}  (successful {len(ok)}, failed {len(sigs)-len(ok)})")
if bt:
    print(f"oldest           : {datetime.datetime.fromtimestamp(min(bt),datetime.UTC):%Y-%m-%d %H:%M}")
    print(f"newest           : {datetime.datetime.fromtimestamp(max(bt),datetime.UTC):%Y-%m-%d %H:%M}")
    print(f"span             : {(max(bt)-min(bt))/86400:.1f} days")
json.dump([s["signature"] for s in ok], open("wallet_sigs.json","w"))
print("wrote wallet_sigs.json")
