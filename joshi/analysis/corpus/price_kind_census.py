import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con=connect(memory_gb=40,threads=10)
T=f"{SP}/out/trades/day=*/trades.parquet"
print("price_kind over the whole corpus:")
for r in con.execute(f"SELECT price_kind, count(*) c, round(100.0*count(*)/sum(count(*)) OVER (),2) pct, count(DISTINCT mint) mints FROM read_parquet('{T}') GROUP BY 1 ORDER BY c DESC").fetchall(): print("  ",r)
print("\ntrade_sign on supported rows:")
for r in con.execute(f"SELECT trade_sign, count(*) FROM read_parquet('{T}') WHERE price_kind<>'unsupported' GROUP BY 1 ORDER BY 1").fetchall(): print("  ",r)
print("\nSOL leg exactness over corpus:")
print(con.execute(f"SELECT count(*) FILTER (sol_leg_lamports_exact IS NOT NULL) exact_sol, count(*) total FROM read_parquet('{T}')").fetchone())
print("\nunsupported: top shapes")
for r in con.execute(f"""SELECT n_venue_cand, n_wsol_paired, venue_has_wsol_leg, tx_has_wsol, n_parties, count(*) c
  FROM read_parquet('{T}') WHERE price_kind='unsupported' GROUP BY 1,2,3,4,5 ORDER BY c DESC LIMIT 12""").fetchall(): print("  ",r)
