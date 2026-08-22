"""Validate the curve price readout against pump.fun's own reported curve state."""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

CURVE_OFFSET_RAW = 73_000_191_000_000
CURVE_K = 30_000_000_000 * 1_073_000_191_000_000
con = connect(memory_gb=40, threads=10)
T = f"{SP}/out/trades/day=2026-08-14/trades.parquet"
B = f"{SP}/out/boards_curve_state.parquet"
con.execute(f"""CREATE OR REPLACE TABLE bo AS
  SELECT * FROM read_parquet('{B}') WHERE NOT complete AND last_trade_unix IS NOT NULL""")
con.execute(f"""CREATE OR REPLACE TABLE tr AS
  SELECT mint, block_time, block_slot, tx_index, venue_token_post_raw, price_sol_per_token, decimals
  FROM read_parquet('{T}') WHERE price_kind='curve_constant_product_readout'""")
# match a board observation to the LAST corpus trade at or before its reported last_trade_unix,
# and require the two to agree on WHICH trade that was (within 2 s) so the snapshot is not stale.
con.execute("""
CREATE OR REPLACE TABLE m AS
SELECT b.mint, b.t_ingest, b.last_trade_unix, b.virtual_sol_reserves AS v_sol, b.virtual_token_reserves AS v_tok,
       t.block_time, t.venue_token_post_raw AS ata, t.price_sol_per_token AS p_model, t.decimals
FROM bo b ASOF JOIN tr t ON b.mint = t.mint AND b.last_trade_unix >= t.block_time
WHERE b.last_trade_unix - t.block_time <= 2
""")
n = con.execute("SELECT count(*), count(DISTINCT mint) FROM m").fetchone()
print("matched board observations:", n)
print("\noffset  v_tok - curve_ata_balance  (raw units) quantiles [.01,.25,.5,.75,.99]:")
print(" ", con.execute("SELECT quantile_cont(v_tok - ata, [0.01,0.25,0.5,0.75,0.99]) FROM m").fetchone()[0])
print(f"  model constant CURVE_OFFSET_RAW = {CURVE_OFFSET_RAW}")
print("\nfraction with offset EXACTLY the model constant:",
  con.execute(f"SELECT count(*) FILTER (v_tok - ata = {CURVE_OFFSET_RAW})::DOUBLE/count(*) FROM m").fetchone()[0])
print("\nk = v_sol*v_tok quantiles [.01,.25,.5,.75,.99]:")
print(" ", con.execute("SELECT quantile_cont(CAST(v_sol AS DOUBLE)*CAST(v_tok AS DOUBLE), [0.01,0.25,0.5,0.75,0.99]) FROM m").fetchone()[0])
print(f"  model constant CURVE_K = {CURVE_K:.6g}")
print("\nlog10( model price / board price ) quantiles [.001,.01,.1,.25,.5,.75,.9,.99,.999]:")
print(" ", con.execute("""SELECT quantile_cont(
   log10(p_model) - log10( CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE) ),
   [0.001,0.01,0.1,0.25,0.5,0.75,0.9,0.99,0.999]) FROM m""").fetchone()[0])
print("\nrelative price error |model/board - 1| quantiles [.5,.9,.99,.999]:")
print(" ", con.execute("""SELECT quantile_cont(abs(p_model/(CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE)) - 1),
   [0.5,0.9,0.99,0.999]) FROM m""").fetchone()[0])
print("\nfraction of matched observations within 1% of the board price:",
  con.execute("""SELECT count(*) FILTER (abs(p_model/(CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE)) - 1) < 0.01)::DOUBLE/count(*) FROM m""").fetchone()[0])
# what matters for excursions is log-DIFFERENCES; measure the error on consecutive pairs per mint
print("\nerror in log-price DIFFERENCE between consecutive board observations of the same mint:")
print(" quantiles of |dlog_model - dlog_board| [.5,.9,.99,.999]:", con.execute("""
WITH s AS (SELECT mint, block_time, p_model,
                  CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE) AS p_board
           FROM m),
 d AS (SELECT mint,
        ln(p_model) - lag(ln(p_model)) OVER (PARTITION BY mint ORDER BY block_time) AS dm,
        ln(p_board) - lag(ln(p_board)) OVER (PARTITION BY mint ORDER BY block_time) AS db
       FROM s)
SELECT quantile_cont(abs(dm-db),[0.5,0.9,0.99,0.999]) FROM d WHERE dm IS NOT NULL""").fetchone()[0])
