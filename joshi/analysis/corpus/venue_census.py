"""Per-mint venue (counterparty) census, from the flow stream. Evidence, not assumption.

A pump.fun mint trades against exactly one counterparty account at a time: the bonding-curve
ATA before migration, a PumpSwap pool vault after. That account is on the opposite side of
essentially every trade, so it is identifiable by PARTICIPATION SHARE, and the share itself is
reported so the identification can be judged rather than trusted.
"""
import sys
import time

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=48, threads=10)
FLOW = f"{SP}/out/flow/day=*/flow.parquet"
t0=time.time()

con.execute(f"""
CREATE OR REPLACE TABLE mint_tx AS
SELECT mint, count(DISTINCT (block_slot, tx_index)) AS n_tx,
       min(block_time) AS first_bt, max(block_time) AS last_bt
FROM read_parquet('{FLOW}') GROUP BY mint
""")
print("mints", con.execute("SELECT count(*) FROM mint_tx").fetchone()[0], round(time.time()-t0,1), flush=True)

con.execute(f"""
CREATE OR REPLACE TABLE mint_owner AS
SELECT mint, owner,
       count(*) AS n_rows,
       count(*) FILTER (owner_has_wsol_leg AND wsol_delta_raw <> 0) AS n_wsol_paired,
       max(abs(token_post_raw)) AS max_post_raw,
       sum(CASE WHEN token_delta_raw > 0 THEN 1 ELSE 0 END) AS n_in,
       sum(CASE WHEN token_delta_raw < 0 THEN 1 ELSE 0 END) AS n_out
FROM read_parquet('{FLOW}') GROUP BY mint, owner
""")
print("mint_owner", con.execute("SELECT count(*) FROM mint_owner").fetchone()[0], round(time.time()-t0,1), flush=True)

# venue candidates: owners on >=20% of the mint's transactions
con.execute("""
CREATE OR REPLACE TABLE venue AS
SELECT mo.mint, mo.owner, mo.n_rows, mo.n_wsol_paired, mo.max_post_raw,
       mt.n_tx, mo.n_rows::DOUBLE / mt.n_tx AS participation
FROM mint_owner mo JOIN mint_tx mt USING (mint)
WHERE mo.n_rows::DOUBLE / mt.n_tx >= 0.20
""")
con.execute(f"COPY venue TO '{SP}/out/venue.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
con.execute(f"COPY mint_tx TO '{SP}/out/mint_tx.parquet' (FORMAT PARQUET, COMPRESSION zstd)")

print("venue rows", con.execute("SELECT count(*) FROM venue").fetchone()[0])
print("\nvenue candidates per mint:")
for r in con.execute("""SELECT n_cand, count(*) FROM (SELECT mint, count(*) n_cand FROM venue GROUP BY mint)
                        GROUP BY 1 ORDER BY 1""").fetchall(): print("  ", r)
print("\nmints with NO venue candidate:",
      con.execute("SELECT count(*) FROM mint_tx WHERE mint NOT IN (SELECT mint FROM venue)").fetchone()[0])
print("\ntop-candidate participation quantiles:")
print(con.execute("""SELECT quantile_cont(p,[0.01,0.05,0.25,0.5,0.75,0.95,0.99]) FROM
   (SELECT mint, max(participation) p FROM venue GROUP BY mint)""").fetchone()[0])
print("\ncoverage of tx by venue rows: see next step")
print("elapsed", round(time.time()-t0,1))
