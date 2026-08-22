"""Validate the curve readout against pump.fun's own reported curve state (boards tape).

Match care: `last_trade_unix` has 1-second resolution and a mint often trades several times in
one second, so the corpus side is first collapsed to the LAST trade of each (mint, second) by
(block_slot, tx_index) before the as-of join.  Without that the join silently pairs a snapshot
with a mid-second trade and manufactures disagreement.
"""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

OFF_STD = 73_000_000_000_000
K_STD   = 30_000_000_000 * 1_073_000_000_000_000
con = connect(memory_gb=40, threads=10)
T = f"{SP}/out/trades/day=2026-08-14/trades.parquet"
B = f"{SP}/out/boards_curve_state.parquet"
con.execute(f"""CREATE OR REPLACE TABLE last_per_sec AS
SELECT mint, block_time,
       arg_max(venue_token_post_raw, (block_slot, tx_index)) AS ata,
       arg_max(decimals, (block_slot, tx_index)) AS decimals
FROM read_parquet('{T}') WHERE price_kind='curve_constant_product_readout'
GROUP BY mint, block_time""")
con.execute(f"""CREATE OR REPLACE TABLE m AS
SELECT b.mint, b.last_trade_unix, b.virtual_sol_reserves AS v_sol, b.virtual_token_reserves AS v_tok,
       t.block_time, t.ata, t.decimals
FROM (SELECT * FROM read_parquet('{B}') WHERE NOT complete AND last_trade_unix IS NOT NULL) b
ASOF JOIN last_per_sec t ON b.mint=t.mint AND b.last_trade_unix >= t.block_time
WHERE b.last_trade_unix - t.block_time <= 1""")
print("matched observations / mints:", con.execute("SELECT count(*), count(DISTINCT mint) FROM m").fetchone())
con.execute("""CREATE OR REPLACE TABLE per_mint AS
SELECT mint, count(*) AS n_obs, min(v_tok-ata) AS off_lo, max(v_tok-ata) AS off_hi,
       median(v_tok-ata) AS off_med, median(CAST(v_sol AS DOUBLE)*CAST(v_tok AS DOUBLE)) AS k_med
FROM m GROUP BY mint""")
print("\nmints by offset stability (n_obs>=2):")
print(" ", con.execute("SELECT count(*) FILTER (off_lo=off_hi) AS stable, count(*) AS total FROM per_mint WHERE n_obs>=2").fetchone())
print("\namong STABLE-offset mints (n_obs>=2), the offset value:")
for r in con.execute("""SELECT off_med AS offset_raw, count(*) AS mints,
   round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM per_mint WHERE n_obs>=2 AND off_lo=off_hi GROUP BY 1 ORDER BY mints DESC LIMIT 10""").fetchall(): print("   ", r)
print("\namong STABLE-offset mints, k:")
for r in con.execute("""SELECT round(k_med/1e25,6) AS k_e25, count(*) AS mints FROM per_mint
   WHERE n_obs>=2 AND off_lo=off_hi GROUP BY 1 ORDER BY mints DESC LIMIT 6""").fetchall(): print("   ", r)
print(f"\nmodel constants: OFFSET={OFF_STD}  K={K_STD:.7g}")
print("\nrelative price error of the readout, restricted to stable-offset mints:")
print(" ", con.execute(f"""SELECT quantile_cont(abs(pm/pb - 1), [0.5,0.9,0.99,0.999,1.0]) FROM (
  SELECT {K_STD}.0*pow(10,m.decimals-9)/pow(CAST(m.ata AS DOUBLE)+{OFF_STD}.0,2) AS pm,
         CAST(m.v_sol AS DOUBLE)*pow(10,m.decimals-9)/CAST(m.v_tok AS DOUBLE) AS pb
  FROM m JOIN per_mint p USING (mint) WHERE p.n_obs>=2 AND p.off_lo=p.off_hi)""").fetchone()[0])
print("\nsame, ALL matched observations (no stability restriction):")
print(" ", con.execute(f"""SELECT quantile_cont(abs(pm/pb - 1), [0.5,0.9,0.99,0.999]) FROM (
  SELECT {K_STD}.0*pow(10,decimals-9)/pow(CAST(ata AS DOUBLE)+{OFF_STD}.0,2) AS pm,
         CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE) AS pb FROM m)""").fetchone()[0])
print("\nfraction of ALL matched observations within 1% / 0.1% of the board price:")
print(" ", con.execute(f"""SELECT
  count(*) FILTER (abs(pm/pb-1)<0.01)::DOUBLE/count(*), count(*) FILTER (abs(pm/pb-1)<0.001)::DOUBLE/count(*), count(*)
 FROM (SELECT {K_STD}.0*pow(10,decimals-9)/pow(CAST(ata AS DOUBLE)+{OFF_STD}.0,2) AS pm,
        CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE) AS pb FROM m)""").fetchone())

print("\n=== THE TEST THAT MATTERS FOR EXCURSIONS ===")
print("consecutive board observations of the SAME mint; does the ata-only readout reproduce")
print("the board's own log-price CHANGE?  |dlog_model - dlog_board| quantiles [.5,.9,.99,.999,1.0]:")
print(" ", con.execute(f"""
WITH s AS (SELECT mint, block_time,
    ln({K_STD}.0*pow(10,decimals-9)/pow(CAST(ata AS DOUBLE)+{OFF_STD}.0,2)) AS lm,
    ln(CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE)) AS lb
  FROM m),
 u AS (SELECT DISTINCT mint, block_time, lm, lb FROM s),
 d AS (SELECT mint, lm - lag(lm) OVER w AS dm, lb - lag(lb) OVER w AS db
       FROM u WINDOW w AS (PARTITION BY mint ORDER BY block_time))
SELECT quantile_cont(abs(dm-db),[0.5,0.9,0.99,0.999,1.0]), count(*) FROM d WHERE dm IS NOT NULL""").fetchone())
print("\nsame, restricted to consecutive observations whose board log-move is itself >= 8%:")
print(" ", con.execute(f"""
WITH s AS (SELECT mint, block_time,
    ln({K_STD}.0*pow(10,decimals-9)/pow(CAST(ata AS DOUBLE)+{OFF_STD}.0,2)) AS lm,
    ln(CAST(v_sol AS DOUBLE)*pow(10,decimals-9)/CAST(v_tok AS DOUBLE)) AS lb FROM m),
 u AS (SELECT DISTINCT mint, block_time, lm, lb FROM s),
 d AS (SELECT mint, lm - lag(lm) OVER w AS dm, lb - lag(lb) OVER w AS db
       FROM u WINDOW w AS (PARTITION BY mint ORDER BY block_time))
SELECT quantile_cont(abs(dm-db),[0.5,0.9,0.99,1.0]), count(*) FROM d WHERE dm IS NOT NULL AND abs(db)>=0.077""").fetchone())
