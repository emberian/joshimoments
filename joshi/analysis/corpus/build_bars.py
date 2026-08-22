"""Minute bars per (mint, venue epoch), from the trade table.

A bar is keyed by (mint, venue_owner, price_kind, minute).  A migration changes BOTH the
counterparty account and the price object, so it starts a new series rather than continuing
one.  Nothing here interpolates, forward-fills, or spans a minute with no trade.

MIN_SOL is a NOTIONAL floor on which trades may set a bar's high/low.  For an AMM fill the
notional is observed exactly; for a curve trade it is the SAME MODEL as the price, so the floor
is a model quantity there and is labelled as such.  The census reports the sensitivity to it.
"""
import sys
import time

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

MIN_SOL_LAMPORTS = int(sys.argv[1]) if len(sys.argv) > 1 else 0
tag = sys.argv[2] if len(sys.argv) > 2 else "sol0"
con = connect(memory_gb=56, threads=10)
T = f"{SP}/out/trades/day=*/trades.parquet"
out = f"{SP}/out/bars_{tag}.parquet"
t0 = time.time()
con.execute(f"""
CREATE OR REPLACE TABLE bars AS
SELECT
  mint, venue_owner, price_kind, (block_time // 60) * 60 AS minute,
  count(*)                                   AS n_trades,
  count(*) FILTER (trade_sign = 1)           AS n_buys,
  count(*) FILTER (trade_sign = -1)          AS n_sells,
  sum(abs(taker_token_delta_raw))            AS token_volume_raw,
  sum(taker_token_delta_raw)                 AS signed_token_flow_raw,
  sum(abs(sol_leg_lamports_exact))           AS sol_volume_lamports_exact,
  sum(-sol_leg_lamports_exact)               AS signed_sol_flow_lamports_exact,
  sum(abs(sol_leg_lamports_curve_model))     AS sol_volume_lamports_curve_model,
  count(*) FILTER (sol_leg_quality='exact_pool_vault')  AS n_sol_exact,
  count(*) FILTER (price_ok)                 AS n_price_trades,
  min(price_sol_per_token) FILTER (price_ok) AS low,
  max(price_sol_per_token) FILTER (price_ok) AS high,
  arg_min(price_sol_per_token, (block_slot, tx_index)) FILTER (price_ok) AS open,
  arg_max(price_sol_per_token, (block_slot, tx_index)) FILTER (price_ok) AS close
FROM (
  SELECT *,
    (price_sol_per_token IS NOT NULL AND price_sol_per_token > 0
     AND coalesce(abs(sol_leg_lamports_exact), abs(sol_leg_lamports_curve_model), 0)
         >= {MIN_SOL_LAMPORTS}) AS price_ok
  FROM read_parquet('{T}') WHERE price_kind <> 'unsupported'
)
GROUP BY 1,2,3,4
""")
print("bar rows", con.execute("SELECT count(*) FROM bars").fetchone()[0], round(time.time()-t0,1), flush=True)
con.execute(f"""COPY (SELECT * FROM bars ORDER BY mint, venue_owner, minute)
  TO '{out}' (FORMAT PARQUET, COMPRESSION zstd, ROW_GROUP_SIZE 200000)""")
print("wrote", out, round(time.time()-t0,1))
