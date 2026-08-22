import sys
import time

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con=connect(memory_gb=48,threads=10)
F=f"{SP}/out/flow/day=*/flow.parquet"; T=f"{SP}/out/trades/day=*/trades.parquet"
print("total flow rows:", con.execute(f"SELECT count(*) FROM read_parquet('{F}')").fetchone()[0])
print("distinct owners corpus-wide:", con.execute(f"SELECT count(DISTINCT owner) FROM read_parquet('{F}')").fetchone()[0])
print("distinct pump mints:", con.execute(f"SELECT count(DISTINCT mint) FROM read_parquet('{F}')").fetchone()[0])
print("\nunsupported rows: does a venue account participate at all?")
for r in con.execute(f"""SELECT n_venue_cand=0 AS no_venue_present, count(*) AS rows,
   round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
 FROM read_parquet('{T}') WHERE price_kind='unsupported' GROUP BY 1""").fetchall(): print("  ",r)
print("\nmints with NO priced trade at all:")
print(" ", con.execute(f"""SELECT count(*) FROM read_parquet('{SP}/out/mint_meta.parquet')
   WHERE n_amm=0 AND n_curve=0""").fetchone()[0], "of", con.execute(f"SELECT count(*) FROM read_parquet('{SP}/out/mint_meta.parquet')").fetchone()[0])
print("\nbuy/sell transaction counts by price object:")
for r in con.execute(f"""SELECT price_kind, count(*) FILTER (trade_sign=1) AS buys,
   count(*) FILTER (trade_sign=-1) AS sells, count(*) FILTER (trade_sign=0) AS zero
 FROM read_parquet('{T}') WHERE price_kind<>'unsupported' GROUP BY 1""").fetchall(): print("  ",r)
print("\nTOTAL exact SOL volume observed (lamports) and its SOL value:")
r=con.execute(f"SELECT sum(abs(sol_leg_lamports_exact)) FROM read_parquet('{T}')").fetchone()[0]
print("  ", r, "=", float(r)/1e9, "SOL over 10 days")
print("\n=== QUERY DEMO: one mint's ordered event stream ===")
m='EHmZM5QD7NFpu6hm3o8yYSA6EhYYunHL21fzN2ucpump'
t0=time.time()
rows=con.execute(f"""SELECT block_slot, tx_index, block_time, venue_owner, price_kind,
   taker_token_delta_raw, sol_leg_lamports_exact, price_sol_per_token, trade_sign, fee_lamports
 FROM read_parquet('{T}') WHERE mint = '{m}' ORDER BY block_slot, tx_index LIMIT 6""").fetchall()
n=con.execute(f"SELECT count(*) FROM read_parquet('{T}') WHERE mint='{m}'").fetchone()[0]
print(f"  {n:,} events, first 6 (query took {time.time()-t0:.2f}s incl. count):")
for r in rows: print("   ",r)
t0=time.time()
n2=con.execute(f"SELECT count(*) FROM read_parquet('{F}') WHERE mint='{m}'").fetchone()[0]
print(f"  flow rows for the same mint: {n2:,}  ({time.time()-t0:.2f}s)")
