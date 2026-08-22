import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=30, threads=8)
T=f"{SP}/out/trades/day=2026-08-09/trades.parquet"
con.execute(f"CREATE OR REPLACE VIEW t AS SELECT * FROM read_parquet('{T}')")
print("price_kind:")
for r in con.execute("SELECT price_kind, count(*) c, round(100.0*count(*)/sum(count(*)) OVER (),2) pct FROM t GROUP BY 1 ORDER BY c DESC").fetchall(): print("  ",r)
print("\nunsupported reasons:")
for r in con.execute("""SELECT venue_identified, n_venue_cand, n_wsol_paired, tx_has_wsol, n_parties, count(*) c
   FROM t WHERE price_kind='unsupported' GROUP BY 1,2,3,4,5 ORDER BY c DESC LIMIT 12""").fetchall(): print("  ",r)
print("\ntrade_sign:")
for r in con.execute("SELECT trade_sign, count(*) FROM t GROUP BY 1 ORDER BY 1").fetchall(): print("  ",r)
print("\nsol leg exactness:")
print(" ", con.execute("SELECT count(*) FILTER (sol_leg_lamports_exact IS NOT NULL) AS exact, count(*) AS total FROM t").fetchone())
print("\nprice quantiles by kind (SOL per whole token):")
for k in ['amm_pool_vault_fill','curve_constant_product_readout']:
    print(" ",k, con.execute(f"SELECT quantile_cont(price_sol_per_token,[0.01,0.1,0.5,0.9,0.99]) FROM t WHERE price_kind='{k}'").fetchone()[0])
print("\ncurve price at a FRESH curve (v_tok_post=1e15):",
  con.execute("SELECT median(price_sol_per_token) FROM t WHERE price_kind='curve_constant_product_readout' AND venue_token_post_raw BETWEEN 999000000000000 AND 1000000000000000").fetchone())
print("\nmints per price_kind:")
for r in con.execute("SELECT price_kind, count(DISTINCT mint) FROM t GROUP BY 1").fetchall(): print("  ",r)
print("\nsanity: AMM fill price vs pool vault ratio (post levels), log10 diff quantiles:")
print(con.execute("""SELECT quantile_cont(d,[0.01,0.25,0.5,0.75,0.99]) FROM (
  SELECT log10(price_sol_per_token) - log10( CAST(venue_wsol_post_raw AS DOUBLE)*pow(10,decimals-9)/CAST(venue_token_post_raw AS DOUBLE)) AS d
  FROM t WHERE price_kind='amm_pool_vault_fill' AND venue_token_post_raw>0 AND venue_wsol_post_raw>0)""").fetchone()[0])
