"""Extract curve-state observations from the joshibot boards tape (READ ONLY).

The boards snapshots carry pump.fun's own `virtual_sol_reserves` / `virtual_token_reserves`
for non-migrated mints.  That is an INDEPENDENT observation of the exact curve state, from a
different collector, and it is what lets the curve price readout in this corpus be validated
instead of asserted.
"""
import json

import pyarrow as pa
import pyarrow.parquet as pq

SRC = "~/dev/joshibot/state/boards/boards-20260814.jsonl"
OUT = "/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/out/boards_curve_state.parquet"

mint=[]; t=[]; vs=[]; vt=[]; lt=[]; comp=[]
seen=set()
for line in open(SRC):
    d = json.loads(line)
    if d.get("kind") != "board_snapshot":
        continue
    ti = d["t_ingest"]
    for m in d.get("members", []):
        v_s = m.get("virtual_sol_reserves"); v_t = m.get("virtual_token_reserves")
        if v_s is None or v_t is None or not v_t:
            continue
        key = (m["mint"], m.get("last_trade_unix"), v_t)
        if key in seen:            # the same state re-observed across boards/snapshots
            continue
        seen.add(key)
        mint.append(m["mint"]); t.append(float(ti)); vs.append(int(v_s)); vt.append(int(v_t))
        lt.append(float(m["last_trade_unix"]) if m.get("last_trade_unix") else None)
        comp.append(bool(m.get("complete")))
tbl = pa.table({"mint": mint, "t_ingest": t, "virtual_sol_reserves": vs,
                "virtual_token_reserves": vt, "last_trade_unix": lt, "complete": comp})
pq.write_table(tbl, OUT, compression="zstd")
print("rows", tbl.num_rows, "distinct mints", len(set(mint)))
