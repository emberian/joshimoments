import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

con = connect(memory_gb=48, threads=10)
F = f"{SP}/out/flow/day=*/flow.parquet"
# venue set: per mint, owners whose participation >= 0.5 (windowwide)
con.execute(f"""
CREATE OR REPLACE TABLE vset AS
SELECT mint, owner, participation, n_rows, n_wsol_paired
FROM read_parquet('{SP}/out/venue.parquet') WHERE participation >= 0.50
""")
print("venue-set rows (participation>=0.5):", con.execute("SELECT count(*) FROM vset").fetchone()[0])
for r in con.execute("SELECT n, count(*) FROM (SELECT mint, count(*) n FROM vset GROUP BY mint) GROUP BY 1 ORDER BY 1 LIMIT 8").fetchall():
    print("   venue owners per mint:", r)

# truth set = one day, txs with exactly one wsol-paired side
D = f"{SP}/out/flow/day=2026-08-09/flow.parquet"
con.execute(f"CREATE OR REPLACE VIEW f AS SELECT * FROM read_parquet('{D}')")
con.execute("""
CREATE OR REPLACE TABLE truth AS
WITH s AS (
 SELECT mint, block_slot, tx_index,
   count(*) FILTER (owner_has_wsol_leg AND wsol_delta_raw<>0 AND sign(wsol_delta_raw)=-sign(token_delta_raw)) AS n_amm,
   count(*) AS n_rows
 FROM f GROUP BY 1,2,3)
SELECT f.mint, f.block_slot, f.tx_index, f.owner,
       (f.owner_has_wsol_leg AND f.wsol_delta_raw<>0 AND sign(f.wsol_delta_raw)=-sign(f.token_delta_raw)) AS is_pool,
       f.token_post_raw
FROM f JOIN s USING (mint, block_slot, tx_index) WHERE s.n_amm=1 AND s.n_rows>=2
""")
r = con.execute("""
SELECT count(DISTINCT (mint, block_slot, tx_index)) FROM truth
""").fetchone()[0]
agree = con.execute("""
WITH j AS (SELECT t.*, (v.owner IS NOT NULL) AS in_vset FROM truth t LEFT JOIN vset v USING (mint, owner))
SELECT count(*) FROM (
  SELECT mint, block_slot, tx_index,
     sum(CASE WHEN in_vset THEN 1 ELSE 0 END) AS n_v,
     sum(CASE WHEN in_vset AND is_pool THEN 1 ELSE 0 END) AS n_vp
  FROM j GROUP BY 1,2,3) WHERE n_v=1 AND n_vp=1
""").fetchone()[0]
one_v = con.execute("""
WITH j AS (SELECT t.*, (v.owner IS NOT NULL) AS in_vset FROM truth t LEFT JOIN vset v USING (mint, owner))
SELECT count(*) FROM (
  SELECT mint, block_slot, tx_index, sum(CASE WHEN in_vset THEN 1 ELSE 0 END) AS n_v
  FROM j GROUP BY 1,2,3) WHERE n_v=1
""").fetchone()[0]
print(f"\ntruth txs: {r:,}")
print(f"  exactly one venue-set member present: {one_v:,} ({100*one_v/r:.2f}%)")
print(f"  and that member IS the pool:          {agree:,} ({100*agree/one_v:.3f}% of those, {100*agree/r:.2f}% of truth)")
