import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, SP, connect

con=connect(memory_gb=30,threads=8)
p=f"{DAILY}/2026-08-09.parquet"
con.execute(f"""CREATE OR REPLACE TABLE legs AS
 SELECT block_slot, tx_index, u.owner AS owner, u.mint AS mint, 1 AS s FROM read_parquet('{p}'), UNNEST(post) t(u)""")
print("post-side accounts per (tx, owner, mint):")
for r in con.execute("""SELECT least(n,4) AS n_accounts, count(*) AS pairs FROM
  (SELECT block_slot,tx_index,owner,mint,count(*) n FROM legs GROUP BY 1,2,3,4) GROUP BY 1 ORDER BY 1""").fetchall(): print("  ",r)
print("\ntop owners by number of (tx) appearances with >1 account of one mint:")
for r in con.execute("""SELECT owner, count(*) AS multi_acct_txs FROM
  (SELECT block_slot,tx_index,owner,mint,count(*) n FROM legs GROUP BY 1,2,3,4) WHERE n>1
  GROUP BY 1 ORDER BY 2 DESC LIMIT 6""").fetchall(): print("  ",r)
print("\ntop venue_owners in the trade table (whole corpus):")
T=f"{SP}/out/trades/day=*/trades.parquet"
for r in con.execute(f"""SELECT venue_owner, count(*) AS trades, count(DISTINCT mint) AS mints
  FROM read_parquet('{T}') WHERE price_kind='amm_pool_vault_fill' GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall(): print("  ",r)
