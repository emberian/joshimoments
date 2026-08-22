"""Build the signed-flow event stream for one UTC day of the bulk_pump corpus.

GRAIN: one row per (transaction, owner, pump-mint) whose token balance CHANGED.
Amounts are exact integers in the mint's raw base units; never floats.
"""
import sys
import time

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, SP, WSOL, connect

day = sys.argv[1]
mem = int(sys.argv[2]) if len(sys.argv) > 2 else 40
con = connect(memory_gb=mem, threads=10)
src = f"{DAILY}/{day}.parquet"
out = f"{SP}/out/flow/day={day}"
t0 = time.time()

con.execute(f"""
CREATE OR REPLACE VIEW legs AS
  SELECT block_slot, tx_index, block_time,
         CAST(fee_lamports AS BIGINT) AS fee_lamports,
         CAST(compute_units AS BIGINT) AS compute_units,
         u.owner AS owner, u.mint AS mint, u.decimals AS decimals,
         CAST(u.amount AS HUGEINT) AS amt, 0::TINYINT AS side
  FROM read_parquet('{src}'), UNNEST(pre) AS t(u)
  UNION ALL
  SELECT block_slot, tx_index, block_time,
         CAST(fee_lamports AS BIGINT), CAST(compute_units AS BIGINT),
         u.owner, u.mint, u.decimals, CAST(u.amount AS HUGEINT), 1::TINYINT
  FROM read_parquet('{src}'), UNNEST(post) AS t(u)
""")

# (tx, owner, mint) balance levels, summed over that owner's token ACCOUNTS for the mint.
con.execute("""
CREATE OR REPLACE TABLE bal AS
SELECT block_slot, tx_index,
       max(block_time)    AS block_time,
       max(fee_lamports)  AS fee_lamports,
       max(compute_units) AS compute_units,
       owner, mint, max(decimals) AS decimals,
       SUM(CASE WHEN side=0 THEN amt ELSE 0 END) AS pre_raw,
       SUM(CASE WHEN side=1 THEN amt ELSE 0 END) AS post_raw,
       -- how many distinct token ACCOUNTS this owner holds for this mint in this transaction.
       -- >1 means the balance is a SUM over several accounts and a two-leg pairing is ambiguous
       -- (shared-authority venues such as the Raydium AMM authority own many pools' vaults).
       greatest(count(*) FILTER (side=0), count(*) FILTER (side=1))::SMALLINT AS n_accounts
FROM legs
GROUP BY block_slot, tx_index, owner, mint
""")
print("bal rows", con.execute("SELECT count(*) FROM bal").fetchone()[0], round(time.time()-t0,1), flush=True)

# per-(tx,owner) SOL-side (wrapped SOL) leg, exact
con.execute(f"""
CREATE OR REPLACE TABLE wsol AS
SELECT block_slot, tx_index, owner,
       pre_raw AS wsol_pre_raw, post_raw AS wsol_post_raw,
       post_raw - pre_raw AS wsol_delta_raw, n_accounts AS wsol_n_accounts
FROM bal WHERE mint = '{WSOL}'
""")

# per-transaction shape facts
con.execute(f"""
CREATE OR REPLACE TABLE txfacts AS
SELECT block_slot, tx_index,
       count(*) FILTER (mint = '{WSOL}') > 0                          AS tx_has_wsol,
       count(DISTINCT mint) FILTER (mint LIKE '%pump')                AS tx_n_pump_mints,
       count(*) FILTER (mint <> '{WSOL}' AND mint NOT LIKE '%pump') > 0 AS tx_has_other_mint,
       count(DISTINCT owner)                                          AS tx_n_owners
FROM bal GROUP BY block_slot, tx_index
""")

con.execute("""
CREATE OR REPLACE TABLE flow AS
SELECT
  b.mint,
  b.block_slot,
  b.tx_index,
  b.block_time,
  b.owner,
  b.decimals::TINYINT                       AS decimals,
  CAST(b.pre_raw  AS DECIMAL(38,0))         AS token_pre_raw,
  CAST(b.post_raw AS DECIMAL(38,0))         AS token_post_raw,
  CAST(b.post_raw - b.pre_raw AS DECIMAL(38,0)) AS token_delta_raw,
  CAST(w.wsol_pre_raw   AS DECIMAL(38,0))   AS wsol_pre_raw,
  CAST(w.wsol_post_raw  AS DECIMAL(38,0))   AS wsol_post_raw,
  CAST(w.wsol_delta_raw AS DECIMAL(38,0))   AS wsol_delta_raw,
  (w.owner IS NOT NULL)                     AS owner_has_wsol_leg,
  b.n_accounts                              AS token_n_accounts,
  w.wsol_n_accounts                         AS wsol_n_accounts,
  b.fee_lamports,
  b.compute_units,
  f.tx_has_wsol,
  f.tx_n_pump_mints::SMALLINT               AS tx_n_pump_mints,
  f.tx_has_other_mint,
  f.tx_n_owners::SMALLINT                   AS tx_n_owners
FROM bal b
LEFT JOIN wsol w USING (block_slot, tx_index, owner)
JOIN txfacts f USING (block_slot, tx_index)
WHERE b.mint LIKE '%pump' AND b.post_raw <> b.pre_raw
""")
n = con.execute("SELECT count(*) FROM flow").fetchone()[0]
print("flow rows", n, round(time.time()-t0,1), flush=True)

import os

os.makedirs(out, exist_ok=True)
con.execute(f"""
COPY (SELECT * FROM flow ORDER BY mint, block_slot, tx_index)
TO '{out}/flow.parquet'
(FORMAT PARQUET, COMPRESSION zstd, ROW_GROUP_SIZE 200000)
""")
print("wrote", out, round(time.time()-t0,1), flush=True)
