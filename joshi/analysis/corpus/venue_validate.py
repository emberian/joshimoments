"""Cross-validate counterparty identification rules on the AMM case, where truth is observable."""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=40, threads=10)
F = f"{SP}/out/flow/day=2026-08-09/flow.parquet"
con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM read_parquet('{F}')")
con.execute(f"CREATE OR REPLACE TABLE mo AS SELECT * FROM read_parquet('{SP}/out/mint_owner_top.parquet')" ) if False else None

# per (mint, tx) shape
con.execute("""
CREATE OR REPLACE TABLE shape AS
SELECT mint, block_slot, tx_index,
  count(*) AS n_rows,
  count(*) FILTER (token_delta_raw > 0) AS n_pos,
  count(*) FILTER (token_delta_raw < 0) AS n_neg,
  count(*) FILTER (owner_has_wsol_leg AND wsol_delta_raw <> 0
                   AND sign(wsol_delta_raw) = -sign(token_delta_raw)) AS n_amm,
  any_value(tx_has_wsol) AS tx_has_wsol,
  any_value(tx_n_pump_mints) AS tx_n_pump_mints
FROM f GROUP BY mint, block_slot, tx_index
""")
print("mint-tx pairs:", con.execute("SELECT count(*) FROM shape").fetchone()[0])
print("\nshape breakdown (n_rows, n_pos, n_neg, n_amm) top 15:")
for r in con.execute("""SELECT n_rows,n_pos,n_neg,n_amm,count(*) c FROM shape GROUP BY 1,2,3,4
                        ORDER BY c DESC LIMIT 15""").fetchall(): print("  ", r)
print("\nn_amm distribution:")
for r in con.execute("SELECT n_amm, count(*) FROM shape GROUP BY 1 ORDER BY 1").fetchall(): print("  ", r)

# On txs with exactly one AMM side, does 'max |token_post_raw|' pick the same owner?
con.execute("""
CREATE OR REPLACE TABLE amm1 AS
SELECT f.* , s.n_rows FROM f JOIN shape s USING (mint, block_slot, tx_index) WHERE s.n_amm = 1 AND s.n_rows >= 2
""")
r = con.execute("""
WITH ranked AS (
  SELECT *, row_number() OVER (PARTITION BY mint, block_slot, tx_index ORDER BY abs(token_post_raw) DESC) AS rk,
         (owner_has_wsol_leg AND wsol_delta_raw <> 0 AND sign(wsol_delta_raw) = -sign(token_delta_raw)) AS is_pool
  FROM amm1)
SELECT count(*) AS n, sum(CASE WHEN rk=1 AND is_pool THEN 1 ELSE 0 END) AS maxpost_is_pool
FROM ranked WHERE rk = 1
""").fetchone()
print(f"\nAMM txs with a unique pool side: {r[0]:,}; max|post| picks the pool in {r[1]:,} ({100*r[1]/r[0]:.2f}%)")
