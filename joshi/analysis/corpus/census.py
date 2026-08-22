"""Crackle-scale census over the whole corpus. Unsigned, shape-free, with a denominator.

DEFINITIONS (declared before any number):
  series          (mint, venue_owner, price_kind).  A migration changes both the counterparty
                  account and the price object, so it starts a NEW series; no excursion spans one.
  active minute   a UTC minute with >= 1 priced trade for the series.  Nothing is interpolated.
  block           a disjoint W-minute tile of the series' life, aligned on its first active
                  minute.  Disjoint, so counting blocks counts non-overlapping opportunities.
  workable block  a block with >= MIN_TRADES priced trades.
  excursion       max(high)/min(low) - 1 within the block.  UNSIGNED: a run-up, a dip-and-recover
                  and a collapse-and-bounce all count identically. No direction, no shape.
  qualifying      workable AND excursion >= THR.
The price is the LAST-TRADE MARK.  It is not an executable quote at any size and nothing here
claims a trader could have captured any part of an excursion.
"""
import json
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import SP, connect

GAP_LO, GAP_HI = 1786534980, 1786580700   # the one damaged stretch, from the coverage census

def build(con, bars, W, MIN_TRADES, THR):
    con.execute(f"""CREATE OR REPLACE TABLE b AS
      SELECT r.mint, r.venue_owner, r.price_kind, r.minute, r.n_price_trades, r.n_trades,
             r.high, r.low, r.sol_volume_lamports_exact, r.sol_volume_lamports_curve_model,
             m.curve_supply_standard, m.std_create
      FROM read_parquet('{bars}') r JOIN read_parquet('{SP}/out/mint_meta.parquet') m USING (mint)
      WHERE r.n_price_trades >= 1 AND r.high IS NOT NULL AND r.low > 0""")
    con.execute("""CREATE OR REPLACE TABLE ser AS
      SELECT mint, venue_owner, price_kind, any_value(curve_supply_standard) AS curve_supply_standard,
             any_value(std_create) AS std_create,
             min(minute) AS first_min, max(minute) AS last_min, count(*) AS active_minutes,
             sum(n_price_trades) AS priced_trades
      FROM b GROUP BY 1,2,3""")
    con.execute(f"""CREATE OR REPLACE TABLE blk AS
      SELECT b.mint, b.venue_owner, b.price_kind, s.curve_supply_standard,
             (b.minute - s.first_min) // (60*{W}) AS blk_id,
             count(*) AS bars, sum(b.n_price_trades) AS ptrades,
             sum(b.sol_volume_lamports_exact) AS sol_exact,
             sum(b.sol_volume_lamports_curve_model) AS sol_model,
             max(b.high) AS hi, min(b.low) AS lo,
             max(CASE WHEN b.minute BETWEEN {GAP_LO} AND {GAP_HI} THEN 1 ELSE 0 END) AS touches_gap
      FROM b JOIN ser s USING (mint, venue_owner, price_kind) GROUP BY 1,2,3,4,5""")
    con.execute(f"""CREATE OR REPLACE TABLE blk2 AS
      SELECT *, hi/lo - 1 AS excursion, (ptrades >= {MIN_TRADES}) AS workable,
             (ptrades >= {MIN_TRADES} AND hi/lo - 1 >= {THR}) AS qualifying FROM blk""")

def summary(con, bars, W, MIN_TRADES, THR, where=""):
    w = f"WHERE {where}" if where else ""
    r = con.execute(f"""SELECT count(*) AS blocks, count(*) FILTER (workable) AS workable,
        count(*) FILTER (qualifying) AS qualifying,
        count(*) FILTER (workable AND excursion BETWEEN {THR} AND 0.20) AS q_8_20,
        count(DISTINCT mint) AS mints FROM blk2 {w}""").fetchone()
    q = con.execute(f"""WITH q AS (SELECT mint, venue_owner, price_kind,
          count(*) FILTER (workable) AS wb, count(*) FILTER (qualifying) AS qb FROM blk2 {w} GROUP BY 1,2,3)
        SELECT count(*) FILTER (wb>0) AS series_workable, count(*) FILTER (qb>0) AS series_ge1,
               count(*) FILTER (qb>=3) AS series_ge3, count(*) FILTER (qb>=10) AS series_ge10,
               count(DISTINCT mint) FILTER (qb>0) AS mints_ge1 FROM q""").fetchone()
    return {"bars": bars.rsplit("/",1)[-1], "W": W, "MIN_TRADES": MIN_TRADES, "THR": THR,
            "blocks": r[0], "workable_blocks": r[1], "qualifying_blocks": r[2],
            "qualifying_in_8_to_20_band": r[3],
            "series_with_workable_block": q[0], "series_with_ge1_qualifying": q[1],
            "series_ge3": q[2], "series_ge10": q[3], "mints_with_ge1_qualifying": q[4]}

if __name__ == "__main__":
    con = connect(memory_gb=56, threads=10)
    mode = sys.argv[1] if len(sys.argv) > 1 else "headline"
    if mode == "grid":
        out = []
        for bars in ["sol0", "sol01", "sol1"]:
            for W in [5, 10, 30]:
                for THR in [0.05, 0.08, 0.15]:
                    p = f"{SP}/out/bars_{bars}.parquet"
                    build(con, p, W, 4, THR)
                    s = summary(con, p, W, 4, THR)
                    out.append(s); print(json.dumps(s), flush=True)
        with open(f"{SP}/out/census_grid.json", "w") as handle:
            json.dump(out, handle, indent=1)
    else:
        bars = f"{SP}/out/bars_sol01.parquet"; W, MT, THR = 30, 4, 0.08
        build(con, bars, W, MT, THR)
        print("HEADLINE:", json.dumps(summary(con, bars, W, MT, THR), indent=1))
        print("\nexcluding blocks that touch the damaged 2026-08-12/13 stretch:")
        print(json.dumps(summary(con, bars, W, MT, THR, "touches_gap = 0"), indent=1))
        print("\nrestricted to standard-supply curve configuration:")
        print(json.dumps(summary(con, bars, W, MT, THR, "curve_supply_standard"), indent=1))
        print("\n=== universe by price object ===")
        for r in con.execute("""SELECT price_kind, count(*) AS series, count(DISTINCT mint) AS mints,
              sum(priced_trades) AS priced_trades, median(active_minutes) AS med_active_min,
              median((last_min-first_min)/60) AS med_life_min, max((last_min-first_min)/60) AS max_life_min
            FROM ser GROUP BY 1 ORDER BY 2 DESC""").fetchall(): print("  ", r)
        print("\n=== REPEAT RATE: qualifying blocks per series (series with >=1 workable block) ===")
        for r in con.execute("""WITH q AS (SELECT mint, venue_owner, price_kind,
              count(*) FILTER (workable) AS wb, count(*) FILTER (qualifying) AS qb FROM blk2 GROUP BY 1,2,3)
            SELECT CASE WHEN qb=0 THEN '0' WHEN qb=1 THEN '1' WHEN qb=2 THEN '2' WHEN qb<=4 THEN '3-4'
                        WHEN qb<=9 THEN '5-9' WHEN qb<=19 THEN '10-19' WHEN qb<=49 THEN '20-49'
                        ELSE '50+' END AS qualifying_blocks, count(*) AS series,
                   round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct
            FROM q WHERE wb>0 GROUP BY 1 ORDER BY min(qb)""").fetchall(): print("  ", r)
        print("\n=== RATE vs ACTIVE LIFETIME (Ember's 'keeps producing after I stop watching') ===")
        for r in con.execute("""WITH q AS (SELECT mint, venue_owner, price_kind,
              count(*) FILTER (workable) AS wb, count(*) FILTER (qualifying) AS qb FROM blk2 GROUP BY 1,2,3),
             j AS (SELECT q.*, (s.last_min-s.first_min)/60 AS life_min FROM q JOIN ser s USING (mint,venue_owner,price_kind))
            SELECT CASE WHEN life_min<30 THEN 'a <30m' WHEN life_min<120 THEN 'b 30m-2h'
                        WHEN life_min<480 THEN 'c 2h-8h' WHEN life_min<1440 THEN 'd 8h-24h'
                        WHEN life_min<4320 THEN 'e 1-3d' ELSE 'f >3d' END AS life,
                   count(*) AS series, sum(wb) AS workable_blocks, sum(qb) AS qualifying_blocks,
                   round(100.0*sum(qb)/nullif(sum(wb),0),2) AS pct_blocks_qualifying,
                   round(100.0*count(*) FILTER (qb>0)/count(*),2) AS pct_series_ge1,
                   round(avg(qb),2) AS mean_qb, round(median(qb),2) AS median_qb
            FROM j WHERE wb>0 GROUP BY 1 ORDER BY 1""").fetchall(): print("  ", r)
        print("\n=== excursion magnitude over WORKABLE blocks ===")
        print("  quantiles [.25,.5,.75,.9,.95,.99]:",
          con.execute("SELECT quantile_cont(excursion,[0.25,0.5,0.75,0.9,0.95,0.99]) FROM blk2 WHERE workable").fetchone()[0])
        for r in con.execute("""SELECT CASE WHEN excursion<0.02 THEN 'a <2%' WHEN excursion<0.05 THEN 'b 2-5%'
              WHEN excursion<0.08 THEN 'c 5-8%' WHEN excursion<0.20 THEN 'd 8-20%' WHEN excursion<0.50 THEN 'e 20-50%'
              WHEN excursion<2.0 THEN 'f 50-200%' ELSE 'g >200%' END AS band, count(*) AS blocks,
              round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct FROM blk2 WHERE workable GROUP BY 1 ORDER BY 1""").fetchall():
            print("  ", r)
        print("\n=== by price object ===")
        for r in con.execute("""SELECT price_kind, count(*) FILTER (workable) AS workable,
              count(*) FILTER (qualifying) AS qualifying,
              round(100.0*count(*) FILTER (qualifying)/nullif(count(*) FILTER (workable),0),2) AS pct
            FROM blk2 GROUP BY 1""").fetchall(): print("  ", r)
        con.execute(f"COPY blk2 TO '{SP}/out/blocks_headline_W30_T8_M4.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
