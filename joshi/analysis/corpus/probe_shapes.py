import json
import sys

sys.path.insert(0, "/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, WSOL, connect

con = connect(memory_gb=6, threads=3)
path = f"{DAILY}/2026-08-09.parquet"
rows = con.execute(f"""
SELECT signature, block_slot, tx_index, fee_lamports, pre, post
FROM read_parquet('{path}')
WHERE NOT (list_contains(list_transform(post, x -> x.mint), '{WSOL}')
        OR list_contains(list_transform(pre,  x -> x.mint), '{WSOL}'))
USING SAMPLE 6 ROWS
""").fetchall()
for r in rows:
    print(json.dumps({"sig": r[0], "slot": r[1], "ti": r[2], "fee": r[3],
                      "pre": r[4], "post": r[5]}, default=str)[:2600])
    print("---")
