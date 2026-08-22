import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, connect

con = connect(memory_gb=10, threads=4)
p = f"{DAILY}/2026-08-09.parquet"
print(con.execute(f"""
SELECT count(*) AS n_rows, count(DISTINCT (block_slot, tx_index)) slot_ti,
       max(tx_index) max_ti, max(CAST(fee_lamports AS HUGEINT)) max_fee,
       max(CAST(compute_units AS HUGEINT)) max_cu
FROM read_parquet('{p}')""").fetchall())
# duplicate (owner,mint) within one post array?
print("dupe (owner,mint) in post:", con.execute(f"""
SELECT count(*) FROM (
  SELECT signature FROM read_parquet('{p}'), UNNEST(post) AS t(u)
  GROUP BY signature, u.owner, u.mint HAVING count(*)>1) """).fetchone())
# max raw amount magnitude
print("max amount len:", con.execute(f"""
SELECT max(len(u.amount)) FROM read_parquet('{p}'), UNNEST(post) AS t(u)""").fetchone())
# decimals distribution
print(con.execute(f"""
SELECT u.decimals d, count(*) n FROM read_parquet('{p}'), UNNEST(post) AS t(u)
GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall())
