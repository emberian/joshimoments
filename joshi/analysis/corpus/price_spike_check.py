import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con=connect(memory_gb=48,threads=10)
T=f"{SP}/out/trades/day=*/trades.parquet"
con.execute(f"""CREATE OR REPLACE TABLE p AS
SELECT mint, venue_owner, price_kind, block_slot, tx_index,
  ln(price_sol_per_token) AS lp,
  abs(coalesce(sol_leg_lamports_exact, sol_leg_lamports_curve_model)) AS sol
FROM read_parquet('{T}') WHERE price_kind<>'unsupported' AND price_sol_per_token>0""")
con.execute("""CREATE OR REPLACE TABLE d AS
SELECT *, lp - lag(lp) OVER w AS d1, lead(lp) OVER w - lp AS d2
FROM p WINDOW w AS (PARTITION BY mint, venue_owner, price_kind ORDER BY block_slot, tx_index)""")
print("=== per-trade log-price change |dlog| quantiles, by price object ===")
for r in con.execute("""SELECT price_kind, count(*) AS n,
  quantile_cont(abs(d1),[0.5,0.9,0.99,0.999]) AS q FROM d WHERE d1 IS NOT NULL GROUP BY 1""").fetchall(): print("  ",r)
print("\n=== SPIKE-AND-REVERT signature: |d1|>ln(3) and d2 ~= -d1 (within 10%) ===")
for r in con.execute("""SELECT price_kind, count(*) AS n_pairs,
  count(*) FILTER (abs(d1)>1.0986 AND abs(d1+d2)<0.1*abs(d1)) AS spike_revert,
  round(100.0*count(*) FILTER (abs(d1)>1.0986 AND abs(d1+d2)<0.1*abs(d1))/count(*),4) AS pct
 FROM d WHERE d1 IS NOT NULL AND d2 IS NOT NULL GROUP BY 1""").fetchall(): print("  ",r)
print("\n=== same, restricted to trades with >= 0.01 SOL notional ===")
for r in con.execute("""SELECT price_kind, count(*) AS n_pairs,
  count(*) FILTER (abs(d1)>1.0986 AND abs(d1+d2)<0.1*abs(d1)) AS spike_revert,
  round(100.0*count(*) FILTER (abs(d1)>1.0986 AND abs(d1+d2)<0.1*abs(d1))/count(*),4) AS pct
 FROM d WHERE d1 IS NOT NULL AND d2 IS NOT NULL AND sol>=1e7 GROUP BY 1""").fetchall(): print("  ",r)
