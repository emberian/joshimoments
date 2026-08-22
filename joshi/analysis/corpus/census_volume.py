import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con=connect(memory_gb=48,threads=10)
B=f"{SP}/out/blocks_headline_W30_T8_M4.parquet"
con.execute(f"CREATE OR REPLACE VIEW blk2 AS SELECT *, coalesce(sol_exact, sol_model) AS sol_notional FROM read_parquet('{B}')")
print("=== SOL notional traded inside a QUALIFYING 30-min block ===")
print("  (exact for AMM blocks; the SAME curve model as the price for curve blocks)")
for r in con.execute("""SELECT CASE WHEN sol_notional IS NULL THEN 'unknown'
   WHEN sol_notional < 1e8 THEN 'a <0.1 SOL' WHEN sol_notional < 1e9 THEN 'b 0.1-1'
   WHEN sol_notional < 1e10 THEN 'c 1-10' WHEN sol_notional < 1e11 THEN 'd 10-100'
   ELSE 'e >100 SOL' END AS notional_band, count(*) AS blocks,
   round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM blk2 WHERE qualifying GROUP BY 1 ORDER BY 1""").fetchall(): print("   ",r)
print("\n=== qualifying blocks with >= 10 SOL of notional, by price object ===")
for r in con.execute("""SELECT price_kind,
   count(*) FILTER (workable) AS workable,
   count(*) FILTER (workable AND sol_notional>=1e10) AS workable_ge10sol,
   count(*) FILTER (qualifying AND sol_notional>=1e10) AS qualifying_ge10sol,
   round(100.0*count(*) FILTER (qualifying AND sol_notional>=1e10)
        /nullif(count(*) FILTER (workable AND sol_notional>=1e10),0),2) AS pct
 FROM blk2 GROUP BY 1""").fetchall(): print("   ",r)
print("\n=== repeat rate restricted to blocks with >= 10 SOL notional ===")
for r in con.execute("""WITH q AS (SELECT mint, venue_owner, price_kind,
   count(*) FILTER (workable AND sol_notional>=1e10) AS wb,
   count(*) FILTER (qualifying AND sol_notional>=1e10) AS qb FROM blk2 GROUP BY 1,2,3)
 SELECT CASE WHEN qb=0 THEN '0' WHEN qb=1 THEN '1' WHEN qb=2 THEN '2' WHEN qb<=4 THEN '3-4'
   WHEN qb<=9 THEN '5-9' WHEN qb<=19 THEN '10-19' WHEN qb<=49 THEN '20-49' ELSE '50+' END AS qblocks,
   count(*) AS series, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM q WHERE wb>0 GROUP BY 1 ORDER BY min(qb)""").fetchall(): print("   ",r)
print("\n  series with >=1 workable >=10-SOL block:",
  con.execute("""WITH q AS (SELECT mint, venue_owner, price_kind,
   count(*) FILTER (workable AND sol_notional>=1e10) AS wb,
   count(*) FILTER (qualifying AND sol_notional>=1e10) AS qb FROM blk2 GROUP BY 1,2,3)
   SELECT count(*) FILTER (wb>0), count(*) FILTER (qb>0), count(DISTINCT mint) FILTER (qb>0) FROM q""").fetchone())
print("\n=== a worked example: the series with the most qualifying blocks ===")
for r in con.execute("""SELECT mint, venue_owner, price_kind, count(*) FILTER (workable) AS wb,
   count(*) FILTER (qualifying) AS qb, round(sum(sol_notional)/1e9,1) AS sol
 FROM blk2 GROUP BY 1,2,3 ORDER BY qb DESC LIMIT 5""").fetchall(): print("   ",r)
