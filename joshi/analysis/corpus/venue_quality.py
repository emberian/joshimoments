"""Is a coin a VENUE you can work repeatedly, or a one-shot?  Rates with their denominators."""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con=connect(memory_gb=48,threads=10)
B=f"{SP}/out/blocks_headline_W30_T8_M4.parquet"
con.execute(f"""CREATE OR REPLACE TABLE s AS
SELECT mint, venue_owner, price_kind,
   count(*) AS blocks, count(*) FILTER (workable) AS wb, count(*) FILTER (qualifying) AS qb,
   count(*) FILTER (workable AND coalesce(sol_exact,sol_model)>=1e10) AS wb10,
   count(*) FILTER (qualifying AND coalesce(sol_exact,sol_model)>=1e10) AS qb10,
   sum(coalesce(sol_exact,sol_model))/1e9 AS sol, sum(ptrades) AS trades
FROM read_parquet('{B}') GROUP BY 1,2,3""")
print("=== how much of a series' LIFE is even active?  (workable half-hours / half-hours spanned) ===")
for r in con.execute("""SELECT CASE WHEN blocks=1 THEN 'a 1 block (<30m)' WHEN blocks<=4 THEN 'b 2-4'
   WHEN blocks<=16 THEN 'c 5-16 (<8h)' WHEN blocks<=48 THEN 'd 17-48 (<24h)'
   WHEN blocks<=144 THEN 'e 49-144 (<3d)' ELSE 'f >144 (>3d)' END AS span,
   count(*) AS series, round(avg(wb),2) AS mean_workable_blocks, round(avg(qb),2) AS mean_qualifying,
   round(100.0*sum(qb)/nullif(sum(wb),0),2) AS pct_workable_that_qualify,
   round(100.0*count(*) FILTER (qb>=1)/count(*),2) AS pct_series_ge1,
   round(100.0*count(*) FILTER (qb>=3)/count(*),2) AS pct_series_ge3,
   round(100.0*count(*) FILTER (qb>=10)/count(*),2) AS pct_series_ge10
 FROM s GROUP BY 1 ORDER BY 1""").fetchall(): print("   ",r)
print("\n=== among series with >= 8 workable half-hours (a coin with a real life), repeat count ===")
for r in con.execute("""SELECT CASE WHEN qb=0 THEN '0' WHEN qb<=2 THEN '1-2' WHEN qb<=4 THEN '3-4'
   WHEN qb<=9 THEN '5-9' WHEN qb<=19 THEN '10-19' WHEN qb<=49 THEN '20-49' ELSE '50+' END AS qualifying,
   count(*) AS series, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM s WHERE wb>=8 GROUP BY 1 ORDER BY min(qb)""").fetchall(): print("   ",r)
print("  denominator (series with >=8 workable half-hours):",
      con.execute("SELECT count(*), count(DISTINCT mint) FROM s WHERE wb>=8").fetchone())
print("\n=== the same, requiring >=10 SOL of notional in the half-hour ===")
for r in con.execute("""SELECT CASE WHEN qb10=0 THEN '0' WHEN qb10<=2 THEN '1-2' WHEN qb10<=4 THEN '3-4'
   WHEN qb10<=9 THEN '5-9' WHEN qb10<=19 THEN '10-19' WHEN qb10<=49 THEN '20-49' ELSE '50+' END AS qualifying,
   count(*) AS series, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM s WHERE wb10>=8 GROUP BY 1 ORDER BY min(qb10)""").fetchall(): print("   ",r)
print("  denominator (series with >=8 workable half-hours of >=10 SOL):",
      con.execute("SELECT count(*), count(DISTINCT mint) FROM s WHERE wb10>=8").fetchone())
print("\n=== total qualifying half-hours available per DAY, market-wide ===")
print(con.execute("""SELECT round(sum(qb)/10.0,0) AS qualifying_halfhours_per_day,
    round(sum(qb10)/10.0,0) AS with_ge10_SOL, round(sum(wb)/10.0,0) AS workable_halfhours_per_day
  FROM s""").fetchone())
