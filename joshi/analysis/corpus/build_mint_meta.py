"""Per-mint metadata needed to scope claims: curve configuration class, birth, censoring."""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=48, threads=10)
F = f"{SP}/out/flow/day=*/flow.parquet"
T = f"{SP}/out/trades/day=*/trades.parquet"
WIN_LO, WIN_HI = 1785888000, 1786751999
con.execute(f"""
CREATE OR REPLACE TABLE mint_meta AS
WITH f AS (
  SELECT mint,
    min(block_time) AS first_bt, max(block_time) AS last_bt,
    count(DISTINCT owner) AS distinct_owners,
    max(CASE WHEN token_pre_raw = 0 AND token_post_raw = 1000000000000000 THEN 1 ELSE 0 END) AS std_create,
    max(token_post_raw) AS max_balance_raw
  FROM read_parquet('{F}') GROUP BY mint),
t AS (
  SELECT mint,
    count(*) AS n_tx,
    count(*) FILTER (price_kind='amm_pool_vault_fill')            AS n_amm,
    count(*) FILTER (price_kind='curve_constant_product_readout') AS n_curve,
    count(*) FILTER (price_kind='unsupported')                    AS n_unsupported,
    max(CASE WHEN price_kind='curve_constant_product_readout' THEN venue_token_post_raw END) AS max_curve_ata
  FROM read_parquet('{T}') GROUP BY mint)
SELECT f.*, t.n_tx, t.n_amm, t.n_curve, t.n_unsupported, t.max_curve_ata,
   (t.max_curve_ata IS NULL OR t.max_curve_ata <= 1050000000000000) AS curve_supply_standard,
   (f.first_bt <= {WIN_LO} + 60) AS left_censored,
   (f.last_bt  >= {WIN_HI} - 60) AS right_censored
FROM f JOIN t USING (mint)
""")
print("mints", con.execute("SELECT count(*) FROM mint_meta").fetchone()[0])
for r in con.execute("""SELECT curve_supply_standard, count(*) FROM mint_meta GROUP BY 1""").fetchall(): print("  curve_supply_standard:", r)
for r in con.execute("""SELECT std_create, count(*) FROM mint_meta GROUP BY 1""").fetchall(): print("  std_create (born in window, 1e15 seed):", r)
for r in con.execute("""SELECT left_censored, right_censored, count(*) FROM mint_meta GROUP BY 1,2 ORDER BY 3 DESC""").fetchall(): print("  censoring:", r)
con.execute(f"COPY mint_meta TO '{SP}/out/mint_meta.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
