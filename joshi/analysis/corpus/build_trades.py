"""Collapse the (tx, owner, mint) flow stream to one row per (mint, transaction).

Identifies the VENUE side (bonding-curve ATA or PumpSwap pool vault) from evidence, derives
the SOL leg exactly where it is observable, and LABELS IT UNSUPPORTED where it is not.

PRICE OBJECTS (never a bare `price`):
  price_kind = 'amm_pool_vault_fill'
      |wsol_delta| / |token_delta| at the pool's own two vaults.  Exact integer ratio of two
      observed balance changes.  It is the POOL VAULT EXCHANGE RATE realised by this
      transaction -- not the taker's all-in cost (protocol/creator fees that leave to other
      accounts are outside these two legs), and not a quote for any other size.
  price_kind = 'curve_constant_product_readout'
      MODEL.  The pump.fun bonding curve holds SOL as native lamports, which this export does
      not carry, so no SOL amount is observed.  Under the standard launch configuration
      (virtual token reserves 1_073_000_191e6 raw, virtual SOL reserves 30e9 lamports, and an
      initial curve ATA balance of exactly 1e15 raw -- the modal create in this corpus, 112,617
      mints) the marginal price is arithmetic on the curve ATA balance alone:
          v_tok      = curve_ata_balance + CURVE_OFFSET_RAW
          p(lamports per raw token) = CURVE_K / v_tok^2
      A mint launched on a different configuration has a different K (a constant scale factor,
      which cancels out of every log-difference) and a different offset (a <=1.5% perturbation
      of the log-difference).  This is a readout, not an observation.
"""
import os
import sys
import time

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

# MEASURED, not assumed: validated against pump.fun's own `virtual_token_reserves` in the
# joshibot boards tape.  On cleanly matched observations of standard-supply mints (one corpus
# trade in the board's 1-second last-trade stamp), 99.23% of 6,115 observations across 2,086
# mints reproduce the board price to < 1e-6 relative; median relative error 4.8e-9.
# v_tok - curve_ata_balance = 73_000_000_000_000 EXACTLY on 99.73% of stable-offset mints.
CURVE_OFFSET_RAW = 73_000_000_000_000
CURVE_K = 30_000_000_000 * 1_073_000_000_000_000  # = 3.219e25 lamports * raw tokens

day = sys.argv[1]
con = connect(memory_gb=40, threads=10)
F = f"{SP}/out/flow/day={day}/flow.parquet"
out = f"{SP}/out/trades/day={day}"
os.makedirs(out, exist_ok=True)
t0 = time.time()

con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM read_parquet('{F}')")
con.execute(f"""CREATE OR REPLACE TABLE vset AS
  SELECT mint, owner FROM read_parquet('{SP}/out/venue.parquet') WHERE participation >= 0.50""")

con.execute("""
CREATE OR REPLACE TABLE tagged AS
SELECT f.*,
  (v.owner IS NOT NULL) AS in_vset,
  (f.owner_has_wsol_leg AND f.wsol_delta_raw <> 0
     AND sign(f.wsol_delta_raw) = -sign(f.token_delta_raw)
     -- unambiguous two-leg pairing only: one token account and one wSOL account for this owner
     AND f.token_n_accounts = 1 AND f.wsol_n_accounts = 1) AS wsol_paired
FROM f LEFT JOIN vset v USING (mint, owner)
""")

con.execute("""
CREATE OR REPLACE TABLE agg AS
SELECT mint, block_slot, tx_index,
  max(block_time)     AS block_time,
  max(fee_lamports)   AS fee_lamports,
  max(compute_units)  AS compute_units,
  max(decimals)       AS decimals,
  count(*)            AS n_parties,
  count(*) FILTER (in_vset)      AS n_venue_cand,
  count(*) FILTER (wsol_paired)  AS n_wsol_paired,
  any_value(tx_has_wsol)      AS tx_has_wsol,
  any_value(tx_n_pump_mints)  AS tx_n_pump_mints,
  any_value(tx_has_other_mint) AS tx_has_other_mint,
  sum(token_delta_raw) FILTER (token_delta_raw > 0) AS tot_in_raw,
  sum(token_delta_raw) FILTER (token_delta_raw < 0) AS tot_out_raw,
  -- venue row, chosen: unique venue-set member, else unique wsol-paired row
  arg_max(owner,           CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS venue_owner,
  arg_max(token_pre_raw,   CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_tok_pre,
  arg_max(token_post_raw,  CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_tok_post,
  arg_max(wsol_pre_raw,    CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_wsol_pre,
  arg_max(wsol_post_raw,   CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_wsol_post,
  arg_max(wsol_paired,     CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_wsol_paired,
  arg_max(owner_has_wsol_leg, CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_has_wsol_leg,
  arg_max(token_n_accounts, CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_tok_naccts,
  arg_max(coalesce(wsol_n_accounts,0), CASE WHEN in_vset THEN 2 WHEN wsol_paired THEN 1 ELSE 0 END) AS v_wsol_naccts
FROM tagged GROUP BY mint, block_slot, tx_index
""")

con.execute(f"""
CREATE OR REPLACE TABLE trades AS
SELECT
  mint, block_slot, tx_index, block_time, decimals,
  venue_owner,
  CASE WHEN n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1) THEN true ELSE false END
     AS venue_identified,
  v_tok_pre  AS venue_token_pre_raw,
  v_tok_post AS venue_token_post_raw,
  (v_tok_post - v_tok_pre) AS venue_token_delta_raw,
  v_wsol_pre  AS venue_wsol_pre_raw,
  v_wsol_post AS venue_wsol_post_raw,
  (v_wsol_post - v_wsol_pre) AS venue_wsol_delta_raw,
  -- taker-side signed flow: +1 the takers acquired the token (BUY), -1 they released it (SELL)
  (v_tok_pre - v_tok_post) AS taker_token_delta_raw,
  CASE WHEN NOT (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1)) THEN NULL
       WHEN v_tok_post < v_tok_pre THEN 1 WHEN v_tok_post > v_tok_pre THEN -1 ELSE 0 END::TINYINT
     AS trade_sign,
  v_wsol_paired AS venue_wsol_paired, v_has_wsol_leg AS venue_has_wsol_leg,
  v_tok_naccts AS venue_token_n_accounts, v_wsol_naccts AS venue_wsol_n_accounts,
  n_parties, n_venue_cand, n_wsol_paired, tot_in_raw, tot_out_raw,
  tx_has_wsol, tx_n_pump_mints, tx_has_other_mint,
  fee_lamports, compute_units,
  CASE
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND v_wsol_paired AND v_wsol_post <> v_wsol_pre AND v_tok_post <> v_tok_pre
      THEN 'amm_pool_vault_fill'
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND NOT v_has_wsol_leg AND v_tok_naccts = 1
         AND v_tok_post <> v_tok_pre AND v_tok_post > 0
      THEN 'curve_constant_product_readout'
    ELSE 'unsupported'
  END AS price_kind,
  -- exact SOL leg, ONLY where two observed vault legs give it
  CASE WHEN v_wsol_paired AND v_wsol_post <> v_wsol_pre
       THEN (v_wsol_post - v_wsol_pre) ELSE NULL END AS sol_leg_lamports_exact,
  -- MODEL, curve only: the SOL the curve took in / paid out under the standard config.
  -- Never mix this with sol_leg_lamports_exact without saying so; sol_leg_quality names which.
  CASE
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND NOT v_has_wsol_leg AND v_tok_naccts = 1
         AND v_tok_post <> v_tok_pre AND v_tok_post > 0 AND v_tok_pre > 0
      THEN {CURVE_K}.0 / (CAST(v_tok_pre AS DOUBLE) + {CURVE_OFFSET_RAW}.0)
         - {CURVE_K}.0 / (CAST(v_tok_post AS DOUBLE) + {CURVE_OFFSET_RAW}.0)
    ELSE NULL END AS sol_leg_lamports_curve_model,
  CASE
    WHEN v_wsol_paired AND v_wsol_post <> v_wsol_pre THEN 'exact_pool_vault'
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND NOT v_has_wsol_leg AND v_tok_naccts = 1
         AND v_tok_post <> v_tok_pre AND v_tok_post > 0 AND v_tok_pre > 0
      THEN 'curve_model_native_sol_not_observed'
    ELSE 'unsupported' END AS sol_leg_quality,
  CASE
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND v_wsol_paired AND v_wsol_post <> v_wsol_pre AND v_tok_post <> v_tok_pre
      THEN abs(CAST(v_wsol_post - v_wsol_pre AS DOUBLE)) * pow(10, decimals - 9)
           / abs(CAST(v_tok_post - v_tok_pre AS DOUBLE))
    WHEN (n_venue_cand = 1 OR (n_venue_cand = 0 AND n_wsol_paired = 1))
         AND NOT v_has_wsol_leg AND v_tok_naccts = 1
         AND v_tok_post <> v_tok_pre AND v_tok_post > 0
      THEN {CURVE_K}.0 * pow(10, decimals - 9)
           / pow(CAST(v_tok_post AS DOUBLE) + {CURVE_OFFSET_RAW}.0, 2)
    ELSE NULL
  END AS price_sol_per_token
FROM agg
""")
n = con.execute("SELECT count(*) FROM trades").fetchone()[0]
print(day, "trade rows", n, round(time.time()-t0,1), flush=True)
con.execute(f"""COPY (SELECT * FROM trades ORDER BY mint, block_slot, tx_index)
 TO '{out}/trades.parquet' (FORMAT PARQUET, COMPRESSION zstd, ROW_GROUP_SIZE 200000)""")
print(day, "written", round(time.time()-t0,1), flush=True)
