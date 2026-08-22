"""Stage 2: describe the birth-aligned cohort before predicting anything about it.

Everything here is a denominator-carrying description of the first hour, first day and first week of
a coin's life, plus the survival and outcome base rates that "sooooo many coins just go to zero"
actually decomposes into.

THE DEATH DEFINITION IS EARNED, NOT PICKED.  A silence threshold is chosen by measuring the
resurrection hazard -- among silences of at least g seconds that we could have observed ending, what
fraction did end -- and taking the g at which that falls below 5%.  The whole curve is printed so
the choice can be argued with.

RIGHT CENSORING IS A DENOMINATOR, NOT A DEATH.  Every horizon statistic is restricted to mints whose
whole horizon lay inside the observed window and clear of the one upstream coverage hole; the
excluded counts are printed beside the included ones.  A coin still trading when the tape stops is
`alive_censored`, never `dead`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddb import SP, connect

WIN_HI = 1786751999
STD_SUPPLY = 1_000_000_000_000_000
SELLABLE = 793_100_000_000_000  # 1e15 curve seed minus the 206.9e12 reserved for migration
OUT = f"{SP}/out/lifecycle"

COH = f"read_parquet('{OUT}/cohort.parquet')"
CEV = f"read_parquet('{OUT}/cev.parquet')"
TOW = f"read_parquet('{OUT}/towner.parquet')"


def show(con, label, sql, note=None):
    rows = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    print(f"\n### {label}")
    if note:
        print(f"    {note}")
    w = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
         for i, c in enumerate(cols)]
    print("    " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in rows:
        print("    " + "  ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))


def main() -> None:
    con = connect(memory_gb=32, threads=8)
    con.execute(f"CREATE OR REPLACE TABLE coh AS SELECT * FROM {COH}")
    con.execute(f"CREATE OR REPLACE TABLE cev AS SELECT * FROM {CEV}")

    print("=" * 100)
    print("STAGE 2 - BIRTH-ALIGNED DESCRIPTION OF THE PUMP COHORT")
    print("=" * 100)

    show(con, "cohort size and censoring", """
    SELECT count(*) AS mints,
           sum(complete_1h_raw::int) AS h1_inwindow, sum((complete_1h_raw AND clear_1h)::int) AS h1_usable,
           sum(complete_24h_raw::int) AS d1_inwindow, sum((complete_24h_raw AND clear_24h)::int) AS d1_usable,
           sum(complete_7d_raw::int) AS d7_inwindow, sum((complete_7d_raw AND clear_7d)::int) AS d7_usable
    FROM coh""",
         "usable = whole horizon inside the window AND clear of the 14.7h coverage hole")

    show(con, "births per corpus day", """
    SELECT c.birth_day_idx AS day, count(*) AS births,
           count(*) FILTER (k.mint IS NULL) AS never_traded_after_create,
           round(avg(c.curve_post0) / 1e15, 5) AS mean_curve_frac_left_after_create
    FROM coh c LEFT JOIN (SELECT DISTINCT mint FROM cev WHERE NOT is_create) k USING (mint)
    GROUP BY 1 ORDER BY 1""",
         "day 0 = 2026-08-05 UTC; the create tx leaves less than full supply on the curve whenever "
         "it carries an atomic creator buy, which it does on every mint in this cohort")

    show(con, "atomic creator buy inside the create transaction", f"""
    SELECT count(*) FILTER (curve_post0 >= 999999999999999) AS no_atomic_buy,
           count(*) FILTER (curve_post0 <  999999999999999) AS atomic_buy,
           round(quantile_cont((1e15 - curve_post0) / {SELLABLE}.0, [0.25,0.5,0.75,0.9,0.99])[1], 4) AS q25,
           round(quantile_cont((1e15 - curve_post0) / {SELLABLE}.0, [0.25,0.5,0.75,0.9,0.99])[2], 4) AS med,
           round(quantile_cont((1e15 - curve_post0) / {SELLABLE}.0, [0.25,0.5,0.75,0.9,0.99])[3], 4) AS q75,
           round(quantile_cont((1e15 - curve_post0) / {SELLABLE}.0, [0.25,0.5,0.75,0.9,0.99])[5], 4) AS q99
    FROM coh""",
         "as a fraction of the sellable curve; compare with the 0.004 median ordinary trade below")

    # ---- how soon after birth does the first non-create trade land
    show(con, "seconds from birth to the first post-create curve event", """
    WITH f AS (SELECT mint, min(dt) AS first_dt FROM cev WHERE NOT is_create GROUP BY mint)
    SELECT count(*) AS mints_with_a_later_event,
           (SELECT count(*) FROM coh) - count(*) AS mints_with_none,
           quantile_cont(first_dt, [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]) AS q
    FROM f""",
         "the choice of birth vs first-trade as t=0 moves the clock by this much")

    # ---- ARRIVAL INTENSITY.  at-risk denominators, log-spaced buckets
    con.execute("""
    CREATE OR REPLACE TABLE buckets AS
    WITH b(lo, hi) AS (VALUES
      (0,10),(10,30),(30,60),(60,120),(120,300),(300,600),(600,1200),(1200,1800),
      (1800,3600),(3600,7200),(7200,14400),(14400,28800),(28800,43200),(43200,86400),
      (86400,172800),(172800,345600),(345600,604800))
    SELECT lo, hi FROM b""")
    show(con, "trade arrival intensity by age (events per mint per minute, at-risk denominator)", f"""
    WITH atrisk AS (
      SELECT b.lo, b.hi, count(*) AS n_at_risk
      FROM coh c, buckets b
      WHERE c.t0 + b.hi <= {WIN_HI}
        AND NOT (c.t0 < 1786587960 AND c.t0 + b.hi > 1786534920)
      GROUP BY 1, 2),
    ev AS (
      SELECT b.lo, b.hi, count(*) AS n_ev, count(DISTINCT e.mint) AS n_active
      FROM cev e JOIN coh c USING (mint), buckets b
      WHERE e.dt >= b.lo AND e.dt < b.hi
        AND c.t0 + b.hi <= {WIN_HI}
        AND NOT (c.t0 < 1786587960 AND c.t0 + b.hi > 1786534920)
      GROUP BY 1, 2)
    SELECT a.lo AS age_lo_s, a.hi AS age_hi_s, a.n_at_risk,
           coalesce(e.n_ev, 0) AS events,
           coalesce(e.n_active, 0) AS mints_active,
           round(coalesce(e.n_active, 0) * 100.0 / a.n_at_risk, 2) AS pct_mints_active,
           round(coalesce(e.n_ev, 0) * 60.0 / (a.n_at_risk * (a.hi - a.lo)), 4) AS ev_per_mint_per_min,
           round(coalesce(e.n_ev, 0) * 60.0 / (coalesce(e.n_active, 1) * (a.hi - a.lo)), 4)
               AS ev_per_ACTIVE_mint_per_min
    FROM atrisk a LEFT JOIN ev e ON a.lo = e.lo ORDER BY a.lo""")

    show(con, "log-log decay of arrival intensity (Omori-style fit, 30s to 12h)", f"""
    WITH atrisk AS (
      SELECT b.lo, b.hi, count(*) AS n_at_risk FROM coh c, buckets b
      WHERE c.t0 + b.hi <= {WIN_HI} AND NOT (c.t0 < 1786587960 AND c.t0 + b.hi > 1786534920)
      GROUP BY 1, 2),
    ev AS (
      SELECT b.lo, b.hi, count(*) AS n_ev FROM cev e JOIN coh c USING (mint), buckets b
      WHERE e.dt >= b.lo AND e.dt < b.hi AND c.t0 + b.hi <= {WIN_HI}
        AND NOT (c.t0 < 1786587960 AND c.t0 + b.hi > 1786534920) GROUP BY 1, 2),
    pts AS (
      SELECT ln(sqrt(a.lo::DOUBLE * a.hi)) AS lt,
             ln(coalesce(e.n_ev,0) * 60.0 / (a.n_at_risk * (a.hi - a.lo))) AS li
      FROM atrisk a LEFT JOIN ev e ON a.lo = e.lo
      WHERE a.lo >= 30 AND a.hi <= 43200 AND coalesce(e.n_ev, 0) > 0)
    SELECT round(regr_slope(li, lt), 4) AS slope_p,
           round(regr_r2(li, lt), 5) AS r2, count(*) AS n_buckets
    FROM pts""",
         "intensity ~ t^slope.  slope near -1 is the Omori/Hawkes-aftershock shape; this is a "
         "description of the decay, not a fitted point process")

    # ---- RESURRECTION HAZARD, to earn the death threshold
    con.execute(f"""
    CREATE OR REPLACE TABLE gaps AS
    SELECT e.mint, e.dt, c.t0,
           lead(e.dt) OVER (PARTITION BY e.mint ORDER BY e.dt, e.key) AS nxt_dt,
           {WIN_HI} - (c.t0 + e.dt) AS obs_left
    FROM cev e JOIN coh c USING (mint)""")
    show(con, "resurrection hazard: does a silent coin come back?", """
    WITH g(sec) AS (VALUES (60),(300),(900),(1800),(3600),(7200),(21600),(43200),(86400))
    SELECT g.sec AS silence_s,
           count(*) FILTER (nxt_dt IS NOT NULL AND nxt_dt - dt > g.sec)
             + count(*) FILTER (nxt_dt IS NULL AND obs_left > g.sec) AS silences_observed,
           count(*) FILTER (nxt_dt IS NOT NULL AND nxt_dt - dt > g.sec) AS ended_in_a_trade,
           round(100.0 * count(*) FILTER (nxt_dt IS NOT NULL AND nxt_dt - dt > g.sec)
                 / nullif(count(*) FILTER (nxt_dt IS NOT NULL AND nxt_dt - dt > g.sec)
                        + count(*) FILTER (nxt_dt IS NULL AND obs_left > g.sec), 0), 2) AS pct_resurrected,
           count(*) FILTER (nxt_dt IS NULL AND obs_left <= g.sec) AS not_evaluable_censored
    FROM gaps, g GROUP BY 1 ORDER BY 1""",
         "a silence of g is 'observed' only if the tape ran at least g longer; the last tail of a "
         "mint that is still trading at corpus end is dropped, not counted as death")

    # ---- SURVIVAL.  The survival function of the LAST observed curve event needs no threshold at
    # ---- all; the resurrection hazard above is what licenses reading "last event" as death.
    show(con, "survival: P(the coin's last curve event is at age >= A)", f"""
    WITH last AS (SELECT mint, max(dt) AS last_dt FROM cev GROUP BY mint),
    lastr AS (SELECT mint, max(dt) AS last_dt FROM cev WHERE NOT is_create GROUP BY mint),
    h(sec, nm) AS (VALUES (1,'1s'),(10,'10s'),(30,'30s'),(60,'1m'),(300,'5m'),(900,'15m'),
                          (1800,'30m'),(3600,'1h'),(10800,'3h'),(21600,'6h'),(43200,'12h'),
                          (86400,'24h'),(172800,'2d'),(259200,'3d'),(518400,'6d'))
    SELECT h.nm AS age,
           count(*) FILTER (c.t0 + h.sec <= {WIN_HI}
                            AND NOT (c.t0 < 1786587960 AND c.t0 + h.sec > 1786534920)) AS evaluable,
           round(100.0 * count(*) FILTER (coalesce(l.last_dt, -1) >= h.sec
                            AND c.t0 + h.sec <= {WIN_HI}
                            AND NOT (c.t0 < 1786587960 AND c.t0 + h.sec > 1786534920))
                 / nullif(count(*) FILTER (c.t0 + h.sec <= {WIN_HI}
                            AND NOT (c.t0 < 1786587960 AND c.t0 + h.sec > 1786534920)), 0), 2)
               AS pct_alive_incl_create,
           round(100.0 * count(*) FILTER (coalesce(r.last_dt, -1) >= h.sec
                            AND c.t0 + h.sec <= {WIN_HI}
                            AND NOT (c.t0 < 1786587960 AND c.t0 + h.sec > 1786534920))
                 / nullif(count(*) FILTER (c.t0 + h.sec <= {WIN_HI}
                            AND NOT (c.t0 < 1786587960 AND c.t0 + h.sec > 1786534920)), 0), 2)
               AS pct_alive_excl_create
    FROM coh c LEFT JOIN last l USING (mint) LEFT JOIN lastr r USING (mint), h
    GROUP BY h.nm, h.sec ORDER BY h.sec""",
         "no silence threshold enters this table.  A mint contributes to the denominator only for "
         "ages its own observation window covers, so the columns are not a single fixed panel.  "
         "excl_create ignores the atomic creator buy, so a coin that only ever had that one event "
         "is already dead at age 0")

    # ---- OUTCOME VOCABULARY
    con.execute("""
    CREATE OR REPLACE TABLE path AS
    SELECT e.mint,
           min(e.dt) AS first_dt, max(e.dt) AS last_dt, count(*) AS n_ev,
           min(e.post) AS min_bal,
           arg_min(e.dt, e.post) AS dt_min_bal,
           arg_max(e.post, e.key) AS final_bal,
           sum(CASE WHEN e.d < 0 THEN 1 ELSE 0 END) AS n_buys,
           sum(CASE WHEN e.d > 0 THEN 1 ELSE 0 END) AS n_sells
    FROM cev e GROUP BY e.mint""")
    show(con, "outcome vocabulary at 24h (mints whose full 24h is usable)", f"""
    WITH c AS (
      SELECT c.*, p.n_ev AS pn, p.last_dt, p.min_bal AS pmin, p.final_bal
      FROM coh c LEFT JOIN path p USING (mint)
      WHERE c.complete_24h_raw AND c.clear_24h)
    SELECT CASE
        WHEN pn IS NULL OR pn <= 1                        THEN 'A never traded after create'
        WHEN ever_amm                                     THEN 'B graduated to a pool'
        WHEN pmin <= 206900000000000                      THEN 'C curve exhausted, no pool seen'
        WHEN last_dt <  86400 - 21600                     THEN 'D traded then silent inside 24h'
        ELSE                                                   'E still transacting at 24h'
      END AS outcome,
      count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
      round(median(coalesce(pn, 0)), 1) AS med_events,
      round(median((1e15 - coalesce(pmin, 1e15)) / {SELLABLE}.0), 4) AS med_peak_curve_sold_frac
    FROM c GROUP BY 1 ORDER BY 2 DESC""",
         "'silent' uses the 6h threshold earned above; E is NOT censored - the tape continued. "
         "peak_sold of 1.2609 means the curve went to a zero balance: 1e15 raw drained against a "
         "793.1e12 sellable curve, so the 206.9e12 migration reserve left too")

    show(con, "outcome vocabulary at 7d (mints whose full 7d is usable)", """
    WITH c AS (
      SELECT c.*, p.n_ev AS pn, p.last_dt, p.min_bal AS pmin
      FROM coh c LEFT JOIN path p USING (mint)
      WHERE c.complete_7d_raw AND c.clear_7d)
    SELECT CASE
        WHEN pn IS NULL OR pn <= 1                        THEN 'A never traded after create'
        WHEN ever_amm                                     THEN 'B graduated to a pool'
        WHEN pmin <= 206900000000000                      THEN 'C curve exhausted, no pool seen'
        WHEN last_dt <  604800 - 21600                    THEN 'D traded then silent inside 7d'
        ELSE                                                   'E still transacting at 7d'
      END AS outcome,
      count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
    FROM c GROUP BY 1 ORDER BY 2 DESC""")

    show(con, "how far does the curve actually get sold, and when", f"""
    WITH c AS (SELECT c.mint, p.min_bal, p.dt_min_bal, p.final_bal, p.n_ev
               FROM coh c JOIN path p USING (mint) WHERE c.complete_24h_raw AND c.clear_24h)
    SELECT CASE
        WHEN (1e15 - min_bal) / {SELLABLE}.0 < 0.01 THEN 'a <1% of curve'
        WHEN (1e15 - min_bal) / {SELLABLE}.0 < 0.05 THEN 'b 1-5%'
        WHEN (1e15 - min_bal) / {SELLABLE}.0 < 0.20 THEN 'c 5-20%'
        WHEN (1e15 - min_bal) / {SELLABLE}.0 < 0.50 THEN 'd 20-50%'
        WHEN (1e15 - min_bal) / {SELLABLE}.0 < 0.95 THEN 'e 50-95%'
        ELSE 'f >=95% (migration reachable)' END AS peak_curve_sold,
      count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
      round(median(dt_min_bal), 0) AS med_seconds_to_peak,
      round(median(n_ev), 0) AS med_events,
      round(100.0 * median((final_bal - min_bal) / nullif(1e15 - min_bal, 0)), 1) AS med_pct_retraced
    FROM c GROUP BY 1 ORDER BY 1""",
         "peak = deepest curve depletion reached = highest model price reached; retrace = how much "
         "of that depletion was sold back into the curve by the end of the observation")

    # ---- SIGNED FLOW: imbalance and persistence, in event time
    show(con, "signed flow imbalance in the first hour", """
    WITH e AS (SELECT mint, sum((d<0)::int) nb, sum((d>0)::int) ns, count(*) n,
                      sum(-d) net, sum(abs(d)) gross
               FROM cev WHERE dt < 3600 GROUP BY mint HAVING count(*) >= 10)
    SELECT count(*) AS mints_with_10plus_events_in_1h,
           round(quantile_cont((nb - ns) * 1.0 / n, [0.05,0.25,0.5,0.75,0.95])[1], 3) AS q05_count_imbalance,
           round(quantile_cont((nb - ns) * 1.0 / n, [0.05,0.25,0.5,0.75,0.95])[3], 3) AS q50,
           round(quantile_cont((nb - ns) * 1.0 / n, [0.05,0.25,0.5,0.75,0.95])[5], 3) AS q95,
           round(quantile_cont(net * 1.0 / gross, [0.05,0.25,0.5,0.75,0.95])[1], 3) AS q05_size_imbalance,
           round(quantile_cont(net * 1.0 / gross, [0.05,0.25,0.5,0.75,0.95])[3], 3) AS q50_size,
           round(quantile_cont(net * 1.0 / gross, [0.05,0.25,0.5,0.75,0.95])[5], 3) AS q95_size
    FROM e""",
         "count imbalance (n_buy - n_sell)/n and size imbalance net/gross, per mint, first 3600s")

    show(con, "trade-sign persistence in event time (first hour, pooled over cohort)", """
    WITH s AS (
      SELECT mint, taker_sign AS x,
             lag(taker_sign, 1) OVER (PARTITION BY mint ORDER BY dt, key) AS l1,
             lag(taker_sign, 2) OVER (PARTITION BY mint ORDER BY dt, key) AS l2,
             lag(taker_sign, 5) OVER (PARTITION BY mint ORDER BY dt, key) AS l5,
             lag(taker_sign,10) OVER (PARTITION BY mint ORDER BY dt, key) AS l10
      FROM cev WHERE dt < 3600 AND taker_sign <> 0)
    SELECT round(corr(x, l1), 4) AS acf_lag1, round(corr(x, l2), 4) AS acf_lag2,
           round(corr(x, l5), 4) AS acf_lag5, round(corr(x, l10), 4) AS acf_lag10,
           count(*) AS n_pairs, round(avg(x), 4) AS mean_sign
    FROM s WHERE l1 IS NOT NULL""",
         "positive = a buy is more likely to follow a buy; mean_sign>0 = buy-heavy population")

    show(con, "trade size distribution, as a fraction of the sellable curve", f"""
    SELECT CASE WHEN dt < 300 THEN '1 first 5m' WHEN dt < 3600 THEN '2 5m-1h'
                WHEN dt < 86400 THEN '3 1h-24h' ELSE '4 24h-7d' END AS age_band,
           count(*) AS events,
           round(quantile_cont(qty_raw / {SELLABLE}.0, [0.5, 0.9, 0.99])[1], 6) AS med_frac_curve,
           round(quantile_cont(qty_raw / {SELLABLE}.0, [0.5, 0.9, 0.99])[2], 6) AS p90,
           round(quantile_cont(qty_raw / {SELLABLE}.0, [0.5, 0.9, 0.99])[3], 6) AS p99,
           round(quantile_cont(abs(sol_lamports_curve_model) / 1e9, [0.5, 0.9, 0.99])[1], 5) AS med_MODEL_sol,
           round(quantile_cont(abs(sol_lamports_curve_model) / 1e9, [0.5, 0.9, 0.99])[3], 5) AS p99_MODEL_sol
    FROM cev GROUP BY 1 ORDER BY 1""",
         "MODEL_sol is the constant-product integral, NOT an observed SOL amount")

    show(con, "unique taker owners by age", f"""
    WITH k AS (
      SELECT mint,
             count(*) FILTER (first_dt < 300)   AS n5m,
             count(*) FILTER (first_dt < 3600)  AS n1h,
             count(*) FILTER (first_dt < 21600) AS n6h,
             count(*)                           AS n24h
      FROM {TOW} GROUP BY mint)
    SELECT 'owners seen by age' AS stat, count(*) AS mints,
           round(avg(n5m), 2) AS mean_5m, round(avg(n1h), 2) AS mean_1h,
           round(avg(n6h), 2) AS mean_6h, round(avg(n24h), 2) AS mean_24h,
           round(quantile_cont(n5m, 0.5), 0) AS med_5m, round(quantile_cont(n1h, 0.5), 0) AS med_1h,
           round(quantile_cont(n24h, 0.5), 0) AS med_24h,
           round(quantile_cont(n24h, 0.99), 0) AS p99_24h
    FROM k""",
         "an owner is any non-curve token-account owner touched by the mint; a router or a program "
         "PDA counts as one, so this is an account count, not a person count")

    show(con, "where the curve balance ends up, relative to full supply", f"""
    WITH c AS (SELECT c.mint, p.final_bal, p.min_bal FROM coh c JOIN path p USING (mint)
               WHERE c.complete_24h_raw AND c.clear_24h)
    SELECT CASE WHEN final_bal >= 999000000000000 THEN 'a >=99.9% of supply back on the curve'
                WHEN final_bal >= 990000000000000 THEN 'b 99-99.9%'
                WHEN final_bal >= 950000000000000 THEN 'c 95-99%'
                WHEN final_bal >= 800000000000000 THEN 'd 80-95%'
                WHEN final_bal >  206900000000000 THEN 'e 20.7-80%'
                ELSE 'f at or below the migration floor' END AS ends_at,
           count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
           round(median((1e15 - min_bal) / {SELLABLE}.0), 4) AS med_peak_sold_frac
    FROM c GROUP BY 1 ORDER BY 1""",
         "the curve balance returning to full supply means every token bought was sold back into "
         "the curve, which puts the model price back at its launch value")

    show(con, "outcome vocabulary at 7d, LENIENT censoring (horizon in window, hole NOT excluded)", """
    WITH c AS (
      SELECT c.*, p.n_ev AS pn, p.last_dt, p.min_bal AS pmin
      FROM coh c LEFT JOIN path p USING (mint) WHERE c.complete_7d_raw)
    SELECT CASE
        WHEN pn IS NULL OR pn <= 1                        THEN 'A never traded after create'
        WHEN ever_amm                                     THEN 'B graduated to a pool'
        WHEN pmin <= 206900000000000                      THEN 'C curve exhausted, no pool seen'
        WHEN last_dt <  604800 - 21600                    THEN 'D traded then silent inside 7d'
        ELSE                                                   'E still transacting at 7d'
      END AS outcome,
      count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
    FROM c GROUP BY 1 ORDER BY 2 DESC""",
         "the strict 7d panel is only 9,169 mints all born inside one 11.7-hour stretch, because "
         "any 7-day window from a later birth runs into the 2026-08-12 coverage hole.  This lenient "
         "panel keeps 64,330 mints and accepts that 234 of their minutes are unobserved.  Both are "
         "shown; neither is load-bearing on its own")

    print("\nDONE")


if __name__ == "__main__":
    main()
