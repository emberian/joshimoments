"""Stage 3: early-window geometry, model-free first, with a candle control on the same coins.

TWO FEATURE SETS ARE BUILT FROM ONE EVENT STREAM.  Both are computed from the same curve-account
balance path over the same [0, cutoff) window, so the only thing that differs between them is the
VIEW: a flow view (counts, participants, sizes, imbalance, arrival times, reserve state) against a
candle view (per-minute open/high/low/close of the model price and the statistics a chart shows).
Building the candles from the corpus's own `bars_*.parquet` would have confounded the comparison,
because those bars are keyed on `trades.parquet` rows that survived venue identification and on this
cohort that drops roughly half of the curve's own state changes.  The comparison Ember asked for is
flow-view versus candle-view, not complete-data versus partial-data.

EVERY FEATURE IS A PURE FUNCTION OF EVENTS STRICTLY BEFORE ITS OWN CUTOFF.  Nothing is standardised
against a full-sample mean, no feature uses a later event, and the train/test split in stage 4 is by
birth day.  A feature that needed the future would not be a feature, it would be leakage.

THE IDENTITY TEST COMES FIRST because it decides what the comparison can possibly mean.  On a
bonding curve the model price is p = K/(bal + offset)^2 and the balance is the seed minus cumulative
signed taker flow, so log price is a fixed strictly-monotone transform of cumulative flow.  The test
below measures that rather than asserting it, and stage 4 then asks whether the candle ENCODING of
the same information buys anything a flow encoding does not.  A negative there is a statement about
this venue only: on a pool-priced coin the fill price is an observed exchange rate and the identity
does not hold.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddb import SP, connect

CURVE_OFFSET_RAW = 73_000_000_000_000
STD_SUPPLY = 1_000_000_000_000_000
SELLABLE = 793_100_000_000_000
CUTOFF = int(sys.argv[1]) if len(sys.argv) > 1 else 300  # seconds visible to every feature
OUT = f"{SP}/out/lifecycle"


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
    con.execute(f"CREATE OR REPLACE TABLE coh AS SELECT * FROM read_parquet('{OUT}/cohort.parquet')")
    con.execute(f"CREATE OR REPLACE TABLE cev AS SELECT * FROM read_parquet('{OUT}/cev.parquet')")
    con.execute(f"CREATE OR REPLACE TABLE tow AS SELECT * FROM read_parquet('{OUT}/towner.parquet')")

    print("=" * 100)
    print(f"STAGE 3 - EARLY-WINDOW GEOMETRY, CUTOFF = {CUTOFF}s")
    print("=" * 100)

    # ------------------------------------------------------------------ the identity test
    show(con, "is the model price arithmetic on the reserve? (per-event)", f"""
    SELECT round(regr_slope(logp_post - logp_pre,
                            ln(post + {CURVE_OFFSET_RAW}) - ln(pre + {CURVE_OFFSET_RAW})), 10) AS slope,
           round(regr_r2(logp_post - logp_pre,
                         ln(post + {CURVE_OFFSET_RAW}) - ln(pre + {CURVE_OFFSET_RAW})), 12) AS r2,
           count(*) AS events
    FROM cev WHERE post <> pre""",
         "slope of exactly -2 with r2 of exactly 1 is the definition of the readout, restated on "
         "21M real events.  It is a tautology and it is printed so the next table cannot be "
         "mistaken for an empirical discovery")

    show(con, "is cumulative signed flow the same object as the price move?", f"""
    WITH w AS (
      SELECT mint,
             sum(-d)::DOUBLE AS net_taker_flow_raw,
             arg_max(post, key)::DOUBLE AS bal_at_cutoff,
             arg_min(pre, key)::DOUBLE AS bal_at_open,
             arg_max(logp_post, key) - arg_min(logp_pre, key) AS log_ret
      FROM cev WHERE dt < {CUTOFF} GROUP BY mint)
    SELECT count(*) AS mints,
           count(*) FILTER (abs(net_taker_flow_raw - (bal_at_open - bal_at_cutoff)) < 1) AS telescopes_exactly,
           round(100.0 * count(*) FILTER (abs(net_taker_flow_raw - (bal_at_open - bal_at_cutoff)) < 1)
                 / count(*), 3) AS pct_exact,
           round(corr(log_ret,
                 -2.0 * (ln(bal_at_cutoff + {CURVE_OFFSET_RAW}) - ln(bal_at_open + {CURVE_OFFSET_RAW}))), 12)
               AS corr_logret_vs_reserve
    FROM w""",
         "net signed taker flow telescopes into the reserve displacement exactly, and the reserve "
         "displacement maps into the log return exactly.  A 'price shape' on this venue is a "
         "re-encoding of the flow that produced it and is not independent evidence about it")

    # ------------------------------------------------------------------ flow features
    con.execute(f"""
    CREATE OR REPLACE TABLE fw AS
    SELECT mint, key, dt, pre, post, d, taker_sign, qty_raw, logp_pre, logp_post,
           sol_lamports_curve_model, is_create,
           lag(taker_sign) OVER (PARTITION BY mint ORDER BY dt, key) AS prev_sign,
           lag(dt)         OVER (PARTITION BY mint ORDER BY dt, key) AS prev_dt
    FROM cev WHERE dt < {CUTOFF}""")

    con.execute(f"""
    CREATE OR REPLACE TABLE fflow AS
    SELECT mint,
      count(*)                                                       AS f_n_events,
      count(*) FILTER (dt >= {CUTOFF} - 60)                          AS f_n_events_last60,
      sum((taker_sign = 1)::int)                                     AS f_n_buys,
      sum((taker_sign = -1)::int)                                    AS f_n_sells,
      (sum((taker_sign = 1)::int) - sum((taker_sign = -1)::int)) * 1.0 / count(*) AS f_count_imb,
      (1e15 - arg_max(post, key)) / {SELLABLE}.0                     AS f_sold_frac_at_cut,
      (1e15 - min(post))          / {SELLABLE}.0                     AS f_peak_sold_frac,
      (arg_max(post, key) - min(post)) / nullif(1e15 - min(post), 0) AS f_retrace_at_cut,
      ln(1 + sum(qty_raw) / {SELLABLE}.0)                            AS f_log_gross_frac,
      ln(1 + max(qty_raw) / {SELLABLE}.0)                            AS f_log_max_frac,
      ln(1 + median(qty_raw) / {SELLABLE}.0)                         AS f_log_med_frac,
      ln(1 + sum(abs(sol_lamports_curve_model)) / 1e9)               AS f_log_MODEL_sol_vol,
      avg(CASE WHEN prev_sign IS NOT NULL AND taker_sign = prev_sign THEN 1.0
               WHEN prev_sign IS NOT NULL THEN 0.0 END)              AS f_sign_runrate,
      avg(CASE WHEN prev_dt IS NOT NULL THEN ln(1 + dt - prev_dt) END) AS f_mean_log_gap,
      max(dt)                                                        AS f_last_event_dt
    FROM fw GROUP BY mint""")

    # The exact flow counterpart of a candle drawdown: on this venue a price drawdown IS a reserve
    # recovery, at event resolution rather than minute resolution.
    con.execute("""
    CREATE OR REPLACE TABLE fdd AS
    SELECT mint, max(runmax_logp - logp_post) AS f_max_dd_event
    FROM (SELECT mint, logp_post,
                 max(logp_post) OVER (PARTITION BY mint ORDER BY dt, key
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS runmax_logp
          FROM fw) t
    GROUP BY mint""")

    con.execute(f"""
    CREATE OR REPLACE TABLE fown2 AS
    SELECT mint, count(*) AS f_n_owners,
           sum(power(gross_raw, 2)) / nullif(power(sum(gross_raw), 2), 0) AS f_owner_hhi,
           max(gross_raw) / nullif(sum(gross_raw), 0)                     AS f_top_owner_share
    FROM tow WHERE first_dt < {CUTOFF} GROUP BY mint""")

    # ------------------------------------------------------------------ candle features
    con.execute(f"""
    CREATE OR REPLACE TABLE bars AS
    SELECT mint, dt // 60 AS m,
           arg_min(logp_pre, key)  AS o,
           arg_max(logp_post, key) AS c,
           greatest(max(logp_pre), max(logp_post)) AS h,
           least(min(logp_pre),  min(logp_post))  AS l,
           count(*) AS n
    FROM cev WHERE dt < {CUTOFF} GROUP BY 1, 2""")
    con.execute("""
    CREATE OR REPLACE TABLE barseq AS
    SELECT *, lag(c) OVER (PARTITION BY mint ORDER BY m) AS pc,
              max(c) OVER (PARTITION BY mint ORDER BY m
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS runmax_c
    FROM bars""")
    con.execute(f"""
    CREATE OR REPLACE TABLE fcandle AS
    SELECT mint,
      count(*)                                              AS c_n_bars,
      count(*) * 60.0 / {CUTOFF}                            AS c_bar_coverage,
      arg_max(c, m) - arg_min(o, m)                         AS c_log_ret,
      max(h) - arg_min(o, m)                                AS c_log_max_up,
      min(l) - arg_min(o, m)                                AS c_log_max_dn,
      sum(h - l)                                            AS c_realized_range,
      avg((c > o)::int)                                     AS c_up_bar_frac,
      max(runmax_c - c)                                     AS c_max_drawdown,
      coalesce(stddev_samp(c - pc), 0)                      AS c_close_vol,
      sum(n)                                                AS c_n_trades
    FROM barseq GROUP BY mint""")

    con.execute("""
    CREATE OR REPLACE TABLE feat AS
    SELECT co.mint, co.t0, co.birth_day_idx, co.curve_post0, co.ever_amm,
           co.complete_1h_raw, co.clear_1h, co.complete_24h_raw, co.clear_24h,
           f.*, o.f_n_owners, o.f_owner_hhi, o.f_top_owner_share, dd.f_max_dd_event, cd.*
    FROM coh co JOIN fflow f USING (mint)
    LEFT JOIN fown2 o USING (mint)
    LEFT JOIN fdd dd USING (mint)
    LEFT JOIN fcandle cd USING (mint)""")

    show(con, "feature availability", """
    SELECT count(*) AS mints_with_a_cutoff_window,
           (SELECT count(*) FROM coh) AS cohort,
           count(*) FILTER (f_n_owners IS NULL) AS missing_owner_features,
           count(*) FILTER (c_n_bars IS NULL) AS missing_candle_features,
           round(avg(f_n_events), 2) AS mean_events_in_window,
           round(median(f_n_events), 1) AS med_events_in_window
    FROM feat""",
         f"every mint has at least the create event inside [0, {CUTOFF}s), so the panel is the "
         "whole cohort and there is no activity-based selection into the feature table")

    show(con, "flow-view geometry of the first 5 minutes", """
    SELECT 'q10' AS q, round(quantile_cont(f_n_events,0.1),2) AS n_events,
           round(quantile_cont(f_n_owners,0.1),2) AS n_owners,
           round(quantile_cont(f_sold_frac_at_cut,0.1),4) AS sold_at_cut,
           round(quantile_cont(f_peak_sold_frac,0.1),4) AS peak_sold,
           round(quantile_cont(f_count_imb,0.1),3) AS count_imb,
           round(quantile_cont(f_sign_runrate,0.1),3) AS sign_runrate,
           round(quantile_cont(f_owner_hhi,0.1),3) AS owner_hhi,
           round(quantile_cont(f_mean_log_gap,0.1),3) AS mean_log_gap
    FROM feat
    UNION ALL SELECT 'q25', round(quantile_cont(f_n_events,0.25),2), round(quantile_cont(f_n_owners,0.25),2),
           round(quantile_cont(f_sold_frac_at_cut,0.25),4), round(quantile_cont(f_peak_sold_frac,0.25),4),
           round(quantile_cont(f_count_imb,0.25),3), round(quantile_cont(f_sign_runrate,0.25),3),
           round(quantile_cont(f_owner_hhi,0.25),3), round(quantile_cont(f_mean_log_gap,0.25),3) FROM feat
    UNION ALL SELECT 'q50', round(quantile_cont(f_n_events,0.5),2), round(quantile_cont(f_n_owners,0.5),2),
           round(quantile_cont(f_sold_frac_at_cut,0.5),4), round(quantile_cont(f_peak_sold_frac,0.5),4),
           round(quantile_cont(f_count_imb,0.5),3), round(quantile_cont(f_sign_runrate,0.5),3),
           round(quantile_cont(f_owner_hhi,0.5),3), round(quantile_cont(f_mean_log_gap,0.5),3) FROM feat
    UNION ALL SELECT 'q75', round(quantile_cont(f_n_events,0.75),2), round(quantile_cont(f_n_owners,0.75),2),
           round(quantile_cont(f_sold_frac_at_cut,0.75),4), round(quantile_cont(f_peak_sold_frac,0.75),4),
           round(quantile_cont(f_count_imb,0.75),3), round(quantile_cont(f_sign_runrate,0.75),3),
           round(quantile_cont(f_owner_hhi,0.75),3), round(quantile_cont(f_mean_log_gap,0.75),3) FROM feat
    UNION ALL SELECT 'q90', round(quantile_cont(f_n_events,0.9),2), round(quantile_cont(f_n_owners,0.9),2),
           round(quantile_cont(f_sold_frac_at_cut,0.9),4), round(quantile_cont(f_peak_sold_frac,0.9),4),
           round(quantile_cont(f_count_imb,0.9),3), round(quantile_cont(f_sign_runrate,0.9),3),
           round(quantile_cont(f_owner_hhi,0.9),3), round(quantile_cont(f_mean_log_gap,0.9),3) FROM feat
    ORDER BY 1""",
         "sign_runrate is the share of consecutive event pairs with the same taker sign; 0.5 is "
         "coin-flip, and the pooled lag-1 sign autocorrelation of 0.35 from stage 2 says it is not")

    show(con, "candle-view geometry of the same five minutes", """
    SELECT 'q10' AS q, round(quantile_cont(c_n_bars,0.1),2) AS n_bars,
           round(quantile_cont(c_log_ret,0.1),4) AS log_ret,
           round(quantile_cont(c_log_max_up,0.1),4) AS max_up,
           round(quantile_cont(c_log_max_dn,0.1),4) AS max_dn,
           round(quantile_cont(c_realized_range,0.1),4) AS realized_range,
           round(quantile_cont(c_max_drawdown,0.1),4) AS max_dd,
           round(quantile_cont(c_up_bar_frac,0.1),3) AS up_bar_frac
    FROM feat WHERE c_n_bars IS NOT NULL
    UNION ALL SELECT 'q50', round(quantile_cont(c_n_bars,0.5),2), round(quantile_cont(c_log_ret,0.5),4),
           round(quantile_cont(c_log_max_up,0.5),4), round(quantile_cont(c_log_max_dn,0.5),4),
           round(quantile_cont(c_realized_range,0.5),4), round(quantile_cont(c_max_drawdown,0.5),4),
           round(quantile_cont(c_up_bar_frac,0.5),3) FROM feat WHERE c_n_bars IS NOT NULL
    UNION ALL SELECT 'q90', round(quantile_cont(c_n_bars,0.9),2), round(quantile_cont(c_log_ret,0.9),4),
           round(quantile_cont(c_log_max_up,0.9),4), round(quantile_cont(c_log_max_dn,0.9),4),
           round(quantile_cont(c_realized_range,0.9),4), round(quantile_cont(c_max_drawdown,0.9),4),
           round(quantile_cont(c_up_bar_frac,0.9),3) FROM feat WHERE c_n_bars IS NOT NULL
    ORDER BY 1""",
         "log units; +0.69 is a doubling of the model price")

    show(con, "what the minute bucketing throws away", """
    SELECT count(*) AS mints,
           count(*) FILTER (c_max_drawdown = 0) AS candle_says_no_drawdown,
           count(*) FILTER (c_max_drawdown = 0 AND f_max_dd_event > 0) AS but_events_say_there_was_one,
           round(100.0 * count(*) FILTER (c_max_drawdown = 0 AND f_max_dd_event > 0)
                 / nullif(count(*) FILTER (c_max_drawdown = 0), 0), 2) AS pct_of_flat_candles_hiding_one,
           round(median(c_max_drawdown), 4) AS med_candle_dd,
           round(median(f_max_dd_event), 4) AS med_event_dd,
           round(quantile_cont(f_max_dd_event, 0.9), 4) AS p90_event_dd
    FROM feat WHERE c_n_bars IS NOT NULL""",
         "log units.  The candle drawdown is computed on minute closes, the event drawdown on the "
         "actual reserve path.  Where they disagree the candle is the one that lost the move, which "
         "is the whole reason the Spearman below is not 1")

    con.execute("""
    CREATE OR REPLACE TABLE rk AS
    SELECT mint,
      rank() OVER (ORDER BY c_log_ret)          AS r_cret,
      rank() OVER (ORDER BY f_sold_frac_at_cut) AS r_fsold,
      rank() OVER (ORDER BY c_log_max_up)       AS r_cup,
      rank() OVER (ORDER BY f_peak_sold_frac)   AS r_fpeak,
      rank() OVER (ORDER BY c_max_drawdown)     AS r_cdd,
      rank() OVER (ORDER BY f_max_dd_event)     AS r_fdd,
      rank() OVER (ORDER BY c_n_trades)         AS r_cn,
      rank() OVER (ORDER BY f_n_events)         AS r_fn
    FROM feat WHERE c_n_bars IS NOT NULL""")
    show(con, "each candle feature against its flow counterpart", """
    SELECT 'c_log_ret     vs reserve level at cutoff' AS pair, round(corr(r_cret, r_fsold), 6) AS spearman FROM rk
    UNION ALL SELECT 'c_log_max_up  vs peak reserve depletion', round(corr(r_cup,  r_fpeak), 6) FROM rk
    UNION ALL SELECT 'c_max_drawdown vs event-resolution drawdown', round(corr(r_cdd, r_fdd), 6) FROM rk
    UNION ALL SELECT 'c_n_trades    vs f_n_events',             round(corr(r_cn,   r_fn),    6) FROM rk""",
         "a Spearman of 1 means the candle feature is a strictly monotone relabelling of the flow "
         "feature and cannot separate any pair of coins the flow feature does not already separate")

    show(con, "how many candles does a coin actually have?", """
    WITH b60 AS (SELECT mint, count(DISTINCT dt // 60) AS n60 FROM cev WHERE dt < 3600 GROUP BY mint),
         b5  AS (SELECT mint, count(DISTINCT dt // 60) AS n5  FROM cev WHERE dt < 300  GROUP BY mint)
    SELECT count(*) AS mints,
           round(quantile_cont(n5,  [0.25,0.5,0.75,0.9,0.99])[1], 0) AS bars_5m_q25,
           round(quantile_cont(n5,  [0.25,0.5,0.75,0.9,0.99])[2], 0) AS bars_5m_med,
           round(quantile_cont(n5,  [0.25,0.5,0.75,0.9,0.99])[4], 0) AS bars_5m_p90,
           round(quantile_cont(n60, [0.25,0.5,0.75,0.9,0.99])[2], 0) AS bars_60m_med,
           round(quantile_cont(n60, [0.25,0.5,0.75,0.9,0.99])[4], 0) AS bars_60m_p90,
           round(quantile_cont(n60, [0.25,0.5,0.75,0.9,0.99])[5], 0) AS bars_60m_p99,
           round(100.0 * count(*) FILTER (n60 <= 3) / count(*), 2) AS pct_with_3_or_fewer_bars_in_1h
    FROM b5 JOIN b60 USING (mint)""",
         "a minute with no trade has no bar, matching the corpus convention.  A coin whose whole "
         "first hour is three bars does not have a chart shape to classify")

    show(con, "time to the first full unwind of the curve", """
    WITH below AS (SELECT mint, min(dt) AS dt_below FROM cev WHERE post < 999000000000000 GROUP BY mint),
         back  AS (SELECT c.mint, min(c.dt) AS dt_back, any_value(b.dt_below) AS dt_below
                   FROM cev c JOIN below b USING (mint)
                   WHERE c.post >= 999000000000000 AND c.dt > b.dt_below GROUP BY c.mint)
    SELECT (SELECT count(*) FROM below) AS mints_that_ever_sold_0_1pct_of_supply,
           count(*) AS mints_that_came_all_the_way_back,
           round(100.0 * count(*) / (SELECT count(*) FROM below), 2) AS pct,
           round(quantile_cont(dt_back - dt_below, [0.1,0.25,0.5,0.75,0.9])[1], 0) AS q10_seconds,
           round(quantile_cont(dt_back - dt_below, [0.1,0.25,0.5,0.75,0.9])[2], 0) AS q25,
           round(quantile_cont(dt_back - dt_below, [0.1,0.25,0.5,0.75,0.9])[3], 0) AS med,
           round(quantile_cont(dt_back - dt_below, [0.1,0.25,0.5,0.75,0.9])[4], 0) AS q75,
           round(quantile_cont(dt_back - dt_below, [0.1,0.25,0.5,0.75,0.9])[5], 0) AS q90
    FROM back""",
         "'unwound' = the curve holds >= 99.9% of supply again, i.e. every token bought has been "
         "sold back and the model price is within 0.2% of its launch value")

    con.execute(f"COPY feat TO '{OUT}/feat_{CUTOFF}.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    print(f"\nwrote {OUT}/feat_{CUTOFF}.parquet")
    print("\nDONE")


if __name__ == "__main__":
    main()
