import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=40, threads=10)
T = f"{SP}/out/trades/day=2026-08-14/trades.parquet"
B = f"{SP}/out/boards_curve_state.parquet"
con.execute(f"""CREATE OR REPLACE TABLE m AS
SELECT b.mint, b.t_ingest, b.last_trade_unix, b.virtual_sol_reserves AS v_sol,
       b.virtual_token_reserves AS v_tok, t.block_time, t.venue_token_post_raw AS ata, t.decimals
FROM (SELECT * FROM read_parquet('{B}') WHERE NOT complete AND last_trade_unix IS NOT NULL) b
ASOF JOIN (SELECT mint, block_time, venue_token_post_raw, decimals FROM read_parquet('{T}')
           WHERE price_kind='curve_constant_product_readout') t
  ON b.mint=t.mint AND b.last_trade_unix >= t.block_time
WHERE b.last_trade_unix - t.block_time <= 2""")
print("per-MINT offset (median over that mint's matched observations): top 20 values")
for r in con.execute("""SELECT voff, count(*) AS mints FROM
  (SELECT mint, median(v_tok - ata) AS voff FROM m GROUP BY mint) GROUP BY 1 ORDER BY mints DESC LIMIT 20""").fetchall():
    print("   ", r)
print("\nper-mint offset stability: mints whose offset varies across its own observations:")
print(" ", con.execute("SELECT count(*) FILTER (mn<>mx), count(*) FROM (SELECT mint, min(v_tok-ata) mn, max(v_tok-ata) mx FROM m GROUP BY mint)").fetchone())
print("\nper-mint k (median):")
for r in con.execute("""SELECT round(k/1e24,4) k_e24, count(*) mints FROM
  (SELECT mint, median(CAST(v_sol AS DOUBLE)*CAST(v_tok AS DOUBLE)) k FROM m GROUP BY mint)
  GROUP BY 1 ORDER BY mints DESC LIMIT 15""").fetchall(): print("   ", r)
print("\nDoes 'first ata balance == 1e15' identify the standard config?")
F=f"{SP}/out/flow/day=*/flow.parquet"
con.execute(f"""CREATE OR REPLACE TABLE births AS
 SELECT mint, max(CASE WHEN token_pre_raw=0 AND token_post_raw=1000000000000000 THEN 1 ELSE 0 END) AS std_create
 FROM read_parquet('{F}') GROUP BY mint""")
for r in con.execute("""SELECT b.std_create, count(*) mints,
   count(*) FILTER (abs(o.voff - 73000000000000) <= 1000000) AS off_is_std
 FROM (SELECT mint, median(v_tok-ata) AS voff FROM m GROUP BY mint) o JOIN births b USING (mint)
 GROUP BY 1""").fetchall(): print("   std_create={} mints={} offset_is_standard={}".format(*r))
