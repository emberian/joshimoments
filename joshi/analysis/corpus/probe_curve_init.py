import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=40, threads=10)
F=f"{SP}/out/flow/day=*/flow.parquet"
print("modal FIRST post_raw for a mint's very first flow row (curve seeding):")
for r in con.execute(f"""
WITH first_row AS (
  SELECT mint, block_slot, tx_index, owner, token_pre_raw, token_post_raw,
     row_number() OVER (PARTITION BY mint ORDER BY block_slot, tx_index, token_post_raw DESC) rk
  FROM read_parquet('{F}'))
SELECT token_post_raw, count(*) c FROM first_row WHERE rk=1 AND token_pre_raw=0
GROUP BY 1 ORDER BY c DESC LIMIT 12""").fetchall(): print("  ", r)
