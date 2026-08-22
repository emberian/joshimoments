import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

OFF=73_000_000_000_000; K=30_000_000_000*1_073_000_000_000_000
con=connect(memory_gb=40,threads=10)
T=f"{SP}/out/trades/day=2026-08-14/trades.parquet"; B=f"{SP}/out/boards_curve_state.parquet"
con.execute(f"""CREATE OR REPLACE TABLE lps AS SELECT mint, block_time,
 arg_max(venue_token_post_raw,(block_slot,tx_index)) AS ata, arg_max(decimals,(block_slot,tx_index)) AS decimals,
 count(*) AS n_in_sec FROM read_parquet('{T}') WHERE price_kind='curve_constant_product_readout' GROUP BY 1,2""")
con.execute(f"""CREATE OR REPLACE TABLE m AS SELECT b.mint, b.last_trade_unix, b.virtual_sol_reserves AS v_sol,
 b.virtual_token_reserves AS v_tok, t.block_time, t.ata, t.decimals, t.n_in_sec,
 {K}.0*pow(10,t.decimals-9)/pow(CAST(t.ata AS DOUBLE)+{OFF}.0,2) AS pm,
 CAST(b.virtual_sol_reserves AS DOUBLE)*pow(10,t.decimals-9)/CAST(b.virtual_token_reserves AS DOUBLE) AS pb
FROM (SELECT * FROM read_parquet('{B}') WHERE NOT complete AND last_trade_unix IS NOT NULL) b
ASOF JOIN lps t ON b.mint=t.mint AND b.last_trade_unix>=t.block_time
WHERE b.last_trade_unix-t.block_time<=1""")
con.execute("CREATE OR REPLACE TABLE ex AS SELECT *, abs(pm/pb-1)<1e-6 AS exact FROM m")
print("per-mint fraction of observations that are EXACT (<1e-6):")
for r in con.execute("""SELECT CASE WHEN fr=1 THEN 'all exact' WHEN fr=0 THEN 'none exact'
   WHEN fr>=0.8 THEN '80-99%' WHEN fr>=0.5 THEN '50-80%' ELSE '<50%' END AS bucket,
   count(*) AS mints, sum(n) AS obs FROM (SELECT mint, avg(exact::INT) fr, count(*) n FROM ex GROUP BY mint)
   GROUP BY 1 ORDER BY 2 DESC""").fetchall(): print("   ",r)
print("\nexactness vs number of corpus trades in the matched second:")
for r in con.execute("SELECT least(n_in_sec,5) AS n_in_sec, count(*) AS obs, round(avg(exact::INT),4) AS frac_exact FROM ex GROUP BY 1 ORDER BY 1").fetchall(): print("   ",r)
print("\nexactness vs how busy the mint is (trades that day):")
con.execute(f"""CREATE OR REPLACE TABLE act AS SELECT mint, count(*) AS ntr FROM read_parquet('{T}')
 WHERE price_kind='curve_constant_product_readout' GROUP BY 1""")
for r in con.execute("""SELECT CASE WHEN ntr<10 THEN 'a <10' WHEN ntr<100 THEN 'b 10-99' WHEN ntr<1000 THEN 'c 100-999'
  ELSE 'd 1000+' END AS band, count(*) AS obs, round(avg(exact::INT),4) AS frac_exact
  FROM ex JOIN act USING (mint) GROUP BY 1 ORDER BY 1""").fetchall(): print("   ",r)
F=f"{SP}/out/flow/day=*/flow.parquet"
con.execute(f"""CREATE OR REPLACE TABLE births AS SELECT mint,
 max(CASE WHEN token_pre_raw=0 AND token_post_raw=1000000000000000 THEN 1 ELSE 0 END) AS std_create,
 max(token_post_raw) AS max_ata FROM read_parquet('{F}') GROUP BY mint""")
print("\nall-exact class vs in-corpus std_create flag:")
for r in con.execute("""SELECT b.std_create, count(*) AS mints, sum(CASE WHEN q.fr=1 THEN 1 ELSE 0 END) AS all_exact
  FROM (SELECT mint, avg(exact::INT) fr FROM ex GROUP BY mint) q JOIN births b USING (mint) GROUP BY 1""").fetchall(): print("   ",r)
print("\nall-exact class vs max observed curve ATA balance:")
for r in con.execute("""SELECT CASE WHEN max_ata=1000000000000000 THEN 'exactly 1e15'
   WHEN max_ata>1000000000000000 THEN '>1e15' WHEN max_ata>9e14 THEN '0.9-1e15' ELSE '<0.9e15' END AS band,
   count(*) AS mints, sum(CASE WHEN q.fr=1 THEN 1 ELSE 0 END) AS all_exact
  FROM (SELECT mint, avg(exact::INT) fr FROM ex GROUP BY mint) q JOIN births b USING (mint) GROUP BY 1 ORDER BY 2 DESC""").fetchall(): print("   ",r)

print("\n=== clean subset: exactly ONE corpus trade in the matched second, and a standard-supply mint ===")
print(con.execute("""SELECT count(*) AS obs, count(DISTINCT mint) AS mints,
  round(avg(exact::INT),4) AS frac_exact,
  quantile_cont(abs(pm/pb-1),[0.5,0.9,0.99,0.999,1.0]) AS rel_err_q
 FROM ex JOIN births b USING (mint) WHERE n_in_sec=1 AND b.max_ata<=1000000000000000""").fetchone())
print("\n  ... and, of the residual non-exact ones there, k implied by the board:")
for r in con.execute("""SELECT round(CAST(v_sol AS DOUBLE)*CAST(v_tok AS DOUBLE)/1e25,4) AS k_e25, count(*) AS obs
 FROM ex JOIN births b USING (mint) WHERE n_in_sec=1 AND b.max_ata<=1000000000000000 AND NOT exact
 GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall(): print("   ",r)
print("\n=== how big is the nonstandard-supply population IN THE WHOLE CORPUS? ===")
print(con.execute("""SELECT CASE WHEN max_ata>1000000000000000 THEN 'nonstandard (>1e15 raw)' ELSE 'standard-compatible' END AS band,
  count(*) AS mints FROM births GROUP BY 1""").fetchall())

print("\n=== does offset scale with supply on NONSTANDARD mints?  (offset / max_ata) ===")
for r in con.execute("""SELECT round(CAST(v_tok-ata AS DOUBLE)/CAST(b.max_ata AS DOUBLE),4) AS ratio, count(*) AS obs
 FROM ex JOIN births b USING (mint) WHERE n_in_sec=1 AND b.max_ata>1000000000000000
 GROUP BY 1 ORDER BY 2 DESC LIMIT 10""").fetchall(): print("   ",r)
print("  (standard mints for comparison: 73000000000000/1e15 = 0.0730)")
