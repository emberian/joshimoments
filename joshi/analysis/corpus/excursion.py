"""Crackle-scale census: unsigned price excursions at Ember's timescale, with a denominator.

DEFINITIONS, declared before the numbers.

  series          (mint, venue_owner, price_kind).  A migration changes both the counterparty
                  account and the price object, so it starts a NEW series; no excursion ever
                  spans one.
  priced bar      a UTC minute in which the series had >= 1 trade whose price object exists
                  (and, for AMM fills, cleared the dust floor).
  active minute   a minute with a priced bar.  Nothing is interpolated or forward-filled.
  lifetime        last_active_minute - first_active_minute, in minutes, WITHIN the 10-day
                  corpus window.  Left/right censored series are flagged.
  block           consecutive W-minute tile of the series' life, aligned on its first active
                  minute.  Tiles are disjoint, so counting them counts disjoint opportunities.
  workable block  a block with >= MIN_TRADES priced trades.
  excursion       max(high)/min(low) - 1 inside the block.  UNSIGNED and shape-free: a run-up,
                  a dip-and-recover, and a collapse-and-bounce all count identically.
  qualifying      excursion >= THR.

The price is the LAST-TRADE MARK (chart mark).  It is not an executable quote for any size,
and no claim here says a trader could have captured any part of it.
"""
import json
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

BARS = sys.argv[1] if len(sys.argv) > 1 else f"{SP}/out/bars_min001.parquet"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 30          # block width, minutes
MIN_TRADES = int(sys.argv[3]) if len(sys.argv) > 3 else 4
THR = float(sys.argv[4]) if len(sys.argv) > 4 else 0.08

# the one damaged stretch in the corpus (see coverage census)
GAP_LO, GAP_HI = 1786534980, 1786580700   # 2026-08-12 11:43 .. 2026-08-13 02:25 UTC

con = connect(memory_gb=56, threads=10)
con.execute(f"""
CREATE OR REPLACE TABLE b AS
SELECT mint, venue_owner, price_kind, minute, n_price_trades, n_trades,
       high, low, close, sol_volume_lamports, n_buys, n_sells
FROM read_parquet('{BARS}') WHERE n_price_trades >= 1 AND high IS NOT NULL AND low > 0
""")
con.execute("""
CREATE OR REPLACE TABLE ser AS
SELECT mint, venue_owner, price_kind,
       min(minute) AS first_min, max(minute) AS last_min,
       count(*) AS active_minutes, sum(n_price_trades) AS priced_trades,
       sum(n_trades) AS trades, sum(sol_volume_lamports) AS sol_vol
FROM b GROUP BY 1,2,3
""")
con.execute(f"""
CREATE OR REPLACE TABLE blk AS
SELECT b.mint, b.venue_owner, b.price_kind,
       (b.minute - s.first_min) // (60*{W}) AS blk_id,
       s.first_min + ((b.minute - s.first_min) / (60*{W})) * 60*{W} AS blk_start,
       count(*) AS bars, sum(b.n_price_trades) AS ptrades, sum(b.n_trades) AS trades,
       sum(b.sol_volume_lamports) AS sol_vol,
       max(b.high) AS hi, min(b.low) AS lo,
       max(CASE WHEN b.minute BETWEEN {GAP_LO} AND {GAP_HI} THEN 1 ELSE 0 END) AS touches_gap
FROM b JOIN ser s USING (mint, venue_owner, price_kind)
GROUP BY 1,2,3,4,5
""")
con.execute(f"""
CREATE OR REPLACE TABLE blk2 AS
SELECT *, hi/lo - 1 AS excursion,
       (ptrades >= {MIN_TRADES}) AS workable,
       (ptrades >= {MIN_TRADES} AND hi/lo - 1 >= {THR}) AS qualifying
FROM blk
""")

def one(sql):
    return con.execute(sql).fetchone()

R = {"bars_file": BARS, "W_minutes": W, "MIN_TRADES": MIN_TRADES, "THR": THR}
R["series"] = one("SELECT count(*) FROM ser")[0]
R["mints"] = one("SELECT count(DISTINCT mint) FROM ser")[0]
R["blocks"] = one("SELECT count(*) FROM blk2")[0]
R["workable_blocks"] = one("SELECT count(*) FILTER (workable) FROM blk2")[0]
R["qualifying_blocks"] = one("SELECT count(*) FILTER (qualifying) FROM blk2")[0]
R["qualifying_blocks_8_to_20"] = one(f"SELECT count(*) FILTER (workable AND excursion>={THR} AND excursion<=0.20) FROM blk2")[0]
R["blocks_touching_gap"] = one("SELECT count(*) FILTER (touches_gap=1) FROM blk2")[0]

print(json.dumps(R, indent=1))

print("\n=== universe, by price object ===")
for r in con.execute("""SELECT price_kind, count(*) series, count(DISTINCT mint) mints,
   sum(priced_trades) trades, median(active_minutes) med_active_min,
   median((last_min-first_min)/60) med_lifetime_min
   FROM ser GROUP BY 1 ORDER BY 2 DESC""").fetchall(): print("  ", r)

print("\n=== series that had at least one QUALIFYING block ===")
for r in con.execute("""
 WITH q AS (SELECT mint, venue_owner, price_kind, count(*) FILTER (workable) wb,
                   count(*) FILTER (qualifying) qb, max(excursion) FILTER (workable) maxexc
            FROM blk2 GROUP BY 1,2,3)
 SELECT price_kind, count(*) AS series, count(*) FILTER (wb>0) AS series_with_workable_block,
        count(*) FILTER (qb>0) AS series_with_ge1, count(*) FILTER (qb>=2) AS ge2,
        count(*) FILTER (qb>=5) AS ge5, count(*) FILTER (qb>=10) AS ge10
 FROM q GROUP BY 1 ORDER BY 2 DESC""").fetchall(): print("  ", r)

print("\n=== distribution of qualifying blocks per series (among series with >=1 workable block) ===")
for r in con.execute("""
 WITH q AS (SELECT mint, venue_owner, price_kind, count(*) FILTER (workable) wb,
                   count(*) FILTER (qualifying) qb FROM blk2 GROUP BY 1,2,3)
 SELECT CASE WHEN qb=0 THEN '0' WHEN qb=1 THEN '1' WHEN qb=2 THEN '2' WHEN qb<=4 THEN '3-4'
             WHEN qb<=9 THEN '5-9' WHEN qb<=19 THEN '10-19' ELSE '20+' END AS bucket,
        count(*) n, round(100.0*count(*)/sum(count(*)) OVER (),2) pct
 FROM q WHERE wb>0 GROUP BY 1 ORDER BY min(qb)""").fetchall(): print("  ", r)

print("\n=== hit rate: qualifying / workable blocks, by series lifetime ===")
for r in con.execute("""
 WITH q AS (SELECT mint, venue_owner, price_kind,
                   count(*) FILTER (workable) wb, count(*) FILTER (qualifying) qb FROM blk2 GROUP BY 1,2,3),
      j AS (SELECT q.*, (s.last_min-s.first_min)/60 AS life_min FROM q JOIN ser s USING (mint,venue_owner,price_kind))
 SELECT CASE WHEN life_min < 30 THEN 'a <30m' WHEN life_min < 120 THEN 'b 30m-2h'
             WHEN life_min < 480 THEN 'c 2h-8h' WHEN life_min < 1440 THEN 'd 8h-24h'
             ELSE 'e >24h' END AS life_bucket,
        count(*) series, sum(wb) workable_blocks, sum(qb) qualifying_blocks,
        round(100.0*sum(qb)/nullif(sum(wb),0),2) AS pct_blocks_qualifying,
        round(100.0*count(*) FILTER (qb>0)/count(*),2) AS pct_series_with_ge1,
        round(avg(qb) FILTER (wb>0),2) AS mean_qb
 FROM j WHERE wb>0 GROUP BY 1 ORDER BY 1""").fetchall(): print("  ", r)

print("\n=== excursion magnitude distribution over WORKABLE blocks ===")
print("  quantiles [.5,.75,.9,.95,.99,.999]:",
  con.execute("SELECT quantile_cont(excursion,[0.5,0.75,0.9,0.95,0.99,0.999]) FROM blk2 WHERE workable").fetchone()[0])
for r in con.execute("""SELECT CASE WHEN excursion<0.02 THEN 'a <2%' WHEN excursion<0.05 THEN 'b 2-5%'
   WHEN excursion<0.08 THEN 'c 5-8%' WHEN excursion<0.20 THEN 'd 8-20%' WHEN excursion<0.50 THEN 'e 20-50%'
   WHEN excursion<2.0 THEN 'f 50-200%' ELSE 'g >200%' END AS band, count(*) n,
   round(100.0*count(*)/sum(count(*)) OVER (),2) pct FROM blk2 WHERE workable GROUP BY 1 ORDER BY 1""").fetchall():
    print("  ", r)
con.execute(f"COPY blk2 TO '{SP}/out/blocks_W{W}_T{int(THR*100)}_M{MIN_TRADES}.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
