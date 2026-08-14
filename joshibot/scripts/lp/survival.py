import collections
import json
import time
import urllib.request

txs=json.load(open("wallet_txs.json"))
mints=collections.Counter()
for tx in txs.values():
    for b in (tx["meta"].get("preTokenBalances") or [])+(tx["meta"].get("postTokenBalances") or []):
        if b.get("mint"): mints[b["mint"]]+=1
SKIP={"So11111111111111111111111111111111111111112","EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
cands=[m for m,_ in mints.most_common(20) if m not in SKIP][:12]
print(f"{'mint':14} {'sym':>8} {'price':>12} {'liquidity':>12} {'24h vol':>11} {'FDV':>11}  status")
for m in cands:
    try:
        req=urllib.request.Request(f"https://api.dexscreener.com/latest/dex/tokens/{m}",
                                   headers={"User-Agent":"joshibot/1.0"})
        with urllib.request.urlopen(req,timeout=25) as r: prs=json.load(r).get("pairs") or []
    except Exception as e:
        print(f"{m[:12]}…  fetch failed {type(e).__name__}"); continue
    if not prs:
        print(f"{m[:12]}…  {'?':>8} {'—':>12} {'—':>12} {'—':>11} {'—':>11}  NO PAIRS (delisted/dead)"); continue
    p=max(prs,key=lambda x: float((x.get('liquidity') or {}).get('usd') or 0))
    liq=float((p.get('liquidity') or {}).get('usd') or 0); vol=float((p.get('volume') or {}).get('h24') or 0)
    fdv=float(p.get('fdv') or 0); sym=p['baseToken']['symbol'][:8]
    status = "DEAD" if liq<1000 else ("dying" if liq<10000 or vol<1000 else "alive")
    print(f"{m[:12]}… {sym:>8} {p.get('priceUsd','?'):>12} ${liq:>11,.0f} ${vol:>10,.0f} ${fdv:>10,.0f}  {status}")
    time.sleep(0.3)
