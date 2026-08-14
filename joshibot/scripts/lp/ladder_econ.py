import json, collections, datetime
rows=json.load(open("pnl_rows.json"))
SYM={"XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump":"DREGG",
     "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump":"weave",
     "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump":"nosis",
     "5pVQnF"  :"?", "GwyWFs":"?"}
def sym(m): return SYM.get(m, m[:6])
LAM=1e9; UNIT=1e6
# SOL-quoted legs only: exactly one token moved and SOL moved the other way.
legs=collections.defaultdict(lambda: {"buy_sol":0.0,"buy_tok":0.0,"sell_sol":0.0,"sell_tok":0.0,
                                      "n_buy":0,"n_sell":0})
skipped=[]
for r in rows:
    if r["hours"] is None: continue          # still open
    toks={m:v for m,v in r["tokens"].items() if abs(v)>1000}
    sol=r["sol"]/LAM
    if len(toks)!=1 or abs(sol)<0.02:
        skipped.append(r); continue
    mint,dv=next(iter(toks.items())); dv/=UNIT
    L=legs[mint]
    if sol<0 and dv>0:  L["buy_sol"]+=-sol; L["buy_tok"]+=dv;  L["n_buy"]+=1
    elif sol>0 and dv<0: L["sell_sol"]+=sol; L["sell_tok"]+=-dv; L["n_sell"]+=1
    else: skipped.append(r)
print("SOL-QUOTED LADDER ECONOMICS (closed, cleanly attributable, single-token legs)\n")
tot_real=0.0
for mint,L in legs.items():
    bp = L["buy_sol"]/L["buy_tok"] if L["buy_tok"] else 0
    sp = L["sell_sol"]/L["sell_tok"] if L["sell_tok"] else 0
    matched=min(L["buy_tok"],L["sell_tok"])
    realised=(sp-bp)*matched if bp and sp else 0
    tot_real+=realised
    print(f"{sym(mint):>6}  buys {L['n_buy']:2} → {L['buy_tok']:>12,.0f} tok for {L['buy_sol']:7.3f} SOL  (avg {bp*1e6:8.4f} µSOL/tok)")
    print(f"        sells{L['n_sell']:2} ← {L['sell_tok']:>12,.0f} tok for {L['sell_sol']:7.3f} SOL  (avg {sp*1e6:8.4f} µSOL/tok)")
    if bp and sp:
        print(f"        spread {(sp/bp-1)*100:+.1f}%   on {matched:,.0f} matched tokens → {realised:+.3f} SOL realised")
    print(f"        inventory left: {L['buy_tok']-L['sell_tok']:+,.0f} tok\n")
print(f"TOTAL REALISED ON MATCHED ROUND TRIPS: {tot_real:+.3f} SOL")
print(f"\n({len(skipped)} positions excluded: coin/coin pairs, dust, or same-sign flows)")
