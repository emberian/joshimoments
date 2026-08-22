"""Per-day honest characterization of one bulk_pump daily parquet."""
import json
import sys
import time

sys.path.insert(0, "/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, WSOL, connect

day = sys.argv[1]
path = f"{DAILY}/{day}.parquet"
con = connect(memory_gb=28, threads=8)
t0 = time.time()

# ---- transaction-level facts
tx = con.execute(f"""
SELECT
  count(*)                                   AS rows,
  count(DISTINCT signature)                  AS distinct_signatures,
  count(DISTINCT block_slot)                 AS distinct_slots,
  min(block_slot)                            AS min_slot,
  max(block_slot)                            AS max_slot,
  min(block_time)                            AS min_block_time,
  max(block_time)                            AS max_block_time,
  sum(CASE WHEN err IS NULL THEN 1 ELSE 0 END)      AS err_null,
  sum(CASE WHEN err = '' THEN 1 ELSE 0 END)         AS err_empty,
  sum(CASE WHEN err <> '' THEN 1 ELSE 0 END)        AS err_nonempty,
  count(DISTINCT schema_version)             AS n_schema_version,
  min(schema_version)                        AS schema_version,
  count(DISTINCT provenance_source)          AS n_prov_source,
  min(provenance_source)                     AS prov_source,
  count(DISTINCT provenance_query_sha256)    AS n_query_sha,
  min(provenance_query_sha256)               AS query_sha,
  min(provenance_extracted_at)               AS extracted_min,
  max(provenance_extracted_at)               AS extracted_max,
  count(DISTINCT provenance_day)             AS n_prov_day,
  min(provenance_day)                        AS prov_day,
  sum(CASE WHEN fee_lamports IS NULL OR fee_lamports='' THEN 1 ELSE 0 END) AS fee_missing,
  sum(CASE WHEN compute_units IS NULL OR compute_units='' THEN 1 ELSE 0 END) AS cu_missing,
  sum(len(pre))                              AS pre_legs,
  sum(len(post))                             AS post_legs,
  sum(CASE WHEN len(pre)=0 THEN 1 ELSE 0 END) AS zero_pre_rows,
  sum(CASE WHEN len(post)=0 THEN 1 ELSE 0 END) AS zero_post_rows
FROM read_parquet('{path}')
""").fetchone()
cols = [d[0] for d in con.description]
out = dict(zip(cols, tx))
out["day"] = day
out["_t_tx_s"] = round(time.time()-t0, 1)

# ---- leg-level facts (union pre/post, one pass)
t1 = time.time()
leg = con.execute(f"""
WITH legs AS (
  SELECT u.mint AS mint, u.owner AS owner, u.decimals AS dec
  FROM read_parquet('{path}'), UNNEST(pre) AS t(u)
  UNION ALL
  SELECT u.mint, u.owner, u.decimals
  FROM read_parquet('{path}'), UNNEST(post) AS t(u)
)
SELECT
  count(*)                                        AS total_legs,
  count(DISTINCT mint)                            AS distinct_mints,
  count(DISTINCT owner)                           AS distinct_owners,
  count(DISTINCT CASE WHEN mint LIKE '%pump' THEN mint END) AS distinct_pump_mints,
  sum(CASE WHEN mint LIKE '%pump' THEN 1 ELSE 0 END)        AS pump_legs,
  sum(CASE WHEN mint = '{WSOL}' THEN 1 ELSE 0 END)          AS wsol_legs,
  sum(CASE WHEN mint <> '{WSOL}' AND mint NOT LIKE '%pump' THEN 1 ELSE 0 END) AS other_legs,
  count(DISTINCT CASE WHEN mint <> '{WSOL}' AND mint NOT LIKE '%pump' THEN mint END) AS distinct_other_mints
FROM legs
""").fetchone()
cols = [d[0] for d in con.description]
out.update(dict(zip(cols, leg)))
out["_t_leg_s"] = round(time.time()-t1, 1)

# ---- how many transactions carry a wSOL leg at all
t2 = time.time()
w = con.execute(f"""
SELECT
  count(*) AS rows,
  sum(CASE WHEN has_wsol THEN 1 ELSE 0 END) AS rows_with_wsol,
  sum(CASE WHEN n_pump_mints = 1 THEN 1 ELSE 0 END) AS rows_one_pump_mint,
  sum(CASE WHEN n_pump_mints > 1 THEN 1 ELSE 0 END) AS rows_multi_pump_mint,
  sum(CASE WHEN has_other THEN 1 ELSE 0 END) AS rows_with_other_mint
FROM (
  SELECT
    list_contains(list_transform(post, x -> x.mint), '{WSOL}')
      OR list_contains(list_transform(pre, x -> x.mint), '{WSOL}') AS has_wsol,
    len(list_distinct(list_filter(
        list_transform(post, x -> x.mint) || list_transform(pre, x -> x.mint),
        m -> m LIKE '%pump'))) AS n_pump_mints,
    len(list_filter(
        list_transform(post, x -> x.mint) || list_transform(pre, x -> x.mint),
        m -> m <> '{WSOL}' AND m NOT LIKE '%pump')) > 0 AS has_other
  FROM read_parquet('{path}')
)
""").fetchone()
cols = [d[0] for d in con.description]
out.update({("tx_"+c if c=="rows" else c): v for c, v in zip(cols, w)})
out["_t_wsol_s"] = round(time.time()-t2, 1)

print(json.dumps(out, default=str))
