"""Stage 4: is anything about the first five minutes informative about what follows?

DECLARED BEFORE LOOKING, and not changed afterwards.

  cutoff    300 seconds of a coin's life.  Every feature is a pure function of curve events with
            dt < 300; none of them can see a later event.
  targets   T1  ALIVE_1H     -- at least one curve event in (300s, 3600s]
            T2  ALIVE_24H    -- at least one curve event in (300s, 86400s]
            T3  GRADUATE     -- the mint is ever seen trading against an AMM pool
            All three are CHARACTERISATION targets.  None of them has an action attached, none is a
            return, and nothing here is a trading rule.  "Will this coin still be transacting" is
            the thing Ember's "sooooo many coins just go to zero" is actually asking.
  split     By BIRTH DAY, earlier trains and later tests, with a one-day buffer so that no training
            coin's outcome window overlaps a test coin's birth.  A random split would leak, because
            launches are correlated within a day through platform-wide attention.
  baselines base rate (a constant, AUC 0.5 by construction), the PERSISTENCE baseline (how many
            events landed in the last minute before the cutoff -- the random-walk/seasonal-intensity
            analogue for a point process), and the EXACT CURVE baseline (the deterministic protocol
            state, the reserve level at the cutoff).  A model has to beat those, not the constant.

THE COMPARISON EMBER ASKED FOR is set A against set B.

  set A  CANDLE / PRICE SHAPE  -- log return, maximum excursion up and down, realised range.  What a
         chart shows.  On this venue each of these is a monotone transform of the cumulative reserve
         displacement, which stage 3 measured rather than assumed.
  set B  FLOW STRUCTURE        -- participant count, event count, sign imbalance, sign run rate,
         owner concentration, inter-arrival, largest trade.  None of these is visible on a chart.

Set A plus B is fitted too.  If A adds nothing over B the conclusion is scoped to the bonding curve and
does not transfer to pool-priced coins, where the fill price is an observed exchange rate rather
than arithmetic on one state variable.

THE MODEL IS DELIBERATELY STUPID: quartile bins from the TRAINING fold only, one shrunk cell mean
per bin combination, no fitting beyond that.  The question is whether the information exists, not
whether a large model can find it, and a cell model cannot manufacture a signal that is not there.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddb import SP, connect

OUT = f"{SP}/out/lifecycle"
CUTOFF = int(sys.argv[1]) if len(sys.argv) > 1 else 300
PRIOR_M = 20.0  # pseudo-count shrinking each cell toward the training base rate

SET_A = ["c_log_ret", "c_log_max_up", "c_log_max_dn", "c_realized_range"]
SET_B = ["f_n_events", "f_n_owners", "f_count_imb", "f_sign_runrate",
         "f_owner_hhi", "f_mean_log_gap", "f_log_max_frac"]
ALL_FEATURES = SET_A + SET_B + ["f_sold_frac_at_cut", "f_peak_sold_frac", "f_n_events_last60",
                                "f_max_dd_event", "c_up_bar_frac", "c_max_drawdown", "c_n_bars",
                                "f_log_MODEL_sol_vol", "f_top_owner_share", "f_retrace_at_cut"]

TARGETS = {
    "T1_ALIVE_1H":  dict(train=(0, 5), test=(7, 9), filt="complete_1h_raw AND clear_1h"),
    "T2_ALIVE_24H": dict(train=(0, 3), test=(5, 5), filt="complete_24h_raw AND clear_24h"),
    "T3_GRADUATE":  dict(train=(0, 5), test=(7, 9), filt="complete_1h_raw AND clear_1h"),
    "T4_TRACTION":  dict(train=(0, 3), test=(5, 5), filt="complete_24h_raw AND clear_24h"),
    # the sweep target.  Its outcome window starts at 1800s regardless of the cutoff, so the same
    # question is being asked of 1, 5 and 30 minutes of watching.
    "T5_ALIVE_24H_FIXED": dict(train=(0, 3), test=(5, 5), filt="complete_24h_raw AND clear_24h"),
}


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


def auc(con, table, score_expr):
    """Rank-based AUC with average ranks for ties.  Equivalent to Mann-Whitney U / (n1 n0)."""
    return con.execute(f"""
    WITH s AS (SELECT y, {score_expr} AS sc FROM {table}),
         r AS (SELECT y, rank() OVER (ORDER BY sc)
                        + (count(*) OVER (PARTITION BY sc) - 1) / 2.0 AS ar FROM s)
    SELECT count(*) FILTER (y = 1) AS n1, count(*) FILTER (y = 0) AS n0,
           (sum(ar) FILTER (y = 1) - count(*) FILTER (y = 1) * (count(*) FILTER (y = 1) + 1) / 2.0)
             / nullif(count(*) FILTER (y = 1)::DOUBLE * count(*) FILTER (y = 0), 0) AS auc
    FROM r""").fetchone()


def main() -> None:
    con = connect(memory_gb=32, threads=8)
    con.execute(f"CREATE OR REPLACE TABLE feat AS SELECT * FROM read_parquet('{OUT}/feat_{CUTOFF}.parquet')")
    con.execute(f"CREATE OR REPLACE TABLE cev AS SELECT * FROM read_parquet('{OUT}/cev.parquet')")
    con.execute(f"""
    CREATE OR REPLACE TABLE y AS
    SELECT f.mint,
           (SELECT count(*) FROM cev e WHERE e.mint = f.mint AND e.dt > {CUTOFF} AND e.dt <= 3600) > 0
               AS T1_ALIVE_1H,
           (SELECT count(*) FROM cev e WHERE e.mint = f.mint AND e.dt > {CUTOFF} AND e.dt <= 86400) > 0
               AS T2_ALIVE_24H,
           f.ever_amm AS T3_GRADUATE,
           (SELECT count(*) FROM cev e WHERE e.mint = f.mint AND e.dt > {CUTOFF} AND e.dt <= 86400) >= 100
               AS T4_TRACTION,
           -- fixed absolute outcome window, so the cutoff sweep compares like with like
           (SELECT count(*) FROM cev e WHERE e.mint = f.mint AND e.dt > 1800 AND e.dt <= 86400) > 0
               AS T5_ALIVE_24H_FIXED
    FROM feat f""")
    con.execute("""
    CREATE OR REPLACE TABLE ds AS
    SELECT f.*, y.T1_ALIVE_1H, y.T2_ALIVE_24H, y.T3_GRADUATE, y.T4_TRACTION, y.T5_ALIVE_24H_FIXED
    FROM feat f JOIN y USING (mint)""")
    for f in ALL_FEATURES:
        con.execute(f"UPDATE ds SET {f} = coalesce({f}, 0)")

    print("=" * 100)
    print(f"STAGE 4 - PREDICTION FROM THE FIRST {CUTOFF} SECONDS")
    print("=" * 100)

    show(con, "base rates by birth day (is the population stationary across the split?)", """
    SELECT birth_day_idx AS day, count(*) AS mints,
           round(100.0 * avg(T1_ALIVE_1H::int), 2)  AS pct_alive_1h,
           round(100.0 * avg(T2_ALIVE_24H::int), 2) AS pct_alive_24h,
           round(100.0 * avg(T3_GRADUATE::int), 3)  AS pct_graduate,
           round(100.0 * avg(T4_TRACTION::int), 2)  AS pct_traction
    FROM ds GROUP BY 1 ORDER BY 1""",
         "day 7 is the day of the coverage hole; its 24h numbers are not comparable and its mints "
         "are excluded from every 24h panel by the clear_24h filter")

    show(con, "the accounting identity behind the strongest predictor", """
    SELECT CASE WHEN f_sold_frac_at_cut <= 0 THEN 'curve fully unwound at 5 min (nobody holds)'
                ELSE 'tokens still outstanding at 5 min' END AS state_at_cutoff,
           count(*) AS mints, round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_of_cohort,
           round(100.0 * avg(T1_ALIVE_1H::int), 2)  AS pct_alive_1h,
           round(100.0 * avg(T2_ALIVE_24H::int), 2) AS pct_alive_24h,
           round(100.0 * avg(T3_GRADUATE::int), 3)  AS pct_graduate
    FROM ds GROUP BY 1 ORDER BY 1""",
         "a coin nobody holds cannot produce a sell, and a sell is the event being predicted.  The "
         "0.89 AUC of the reserve level is mostly this identity, which is why the ablation below "
         "conditions on it before asking whether anything else survives")

    for tname, cfg in TARGETS.items():
        tr_lo, tr_hi = cfg["train"]
        te_lo, te_hi = cfg["test"]
        filt = cfg["filt"]
        con.execute(f"""CREATE OR REPLACE TABLE tr AS
            SELECT *, {tname}::int AS y, random() AS rnd FROM ds
            WHERE {filt} AND birth_day_idx BETWEEN {tr_lo} AND {tr_hi}""")
        con.execute(f"""CREATE OR REPLACE TABLE te AS
            SELECT *, {tname}::int AS y, random() AS rnd FROM ds
            WHERE {filt} AND birth_day_idx BETWEEN {te_lo} AND {te_hi}""")
        ntr, ytr = con.execute("SELECT count(*), avg(y) FROM tr").fetchone()
        nte, yte = con.execute("SELECT count(*), avg(y) FROM te").fetchone()
        print(f"\n{'=' * 100}\n{tname}   train days {tr_lo}-{tr_hi}: n={ntr:,} base={ytr:.4f}   "
              f"test days {te_lo}-{te_hi}: n={nte:,} base={yte:.4f}\n{'=' * 100}")

        # ---- single-feature AUC, train and test, so overfitting is visible per feature
        rows = []
        for f in ALL_FEATURES:
            _, _, a_tr = auc(con, "tr", f)
            _, _, a_te = auc(con, "te", f)
            grp = "A candle" if f in SET_A else ("B flow" if f in SET_B else "- other")
            rows.append((f, grp, round(a_tr or 0.5, 4), round(a_te or 0.5, 4)))
        rows.sort(key=lambda r: -abs((r[3] or 0.5) - 0.5))
        print("\n### single-feature AUC (a feature below 0.5 separates in the other direction)")
        print("    feature                 group     auc_train  auc_test")
        for f, g, a, b in rows:
            print(f"    {f:<23} {g:<9} {a:<10} {b}")

        # ---- baselines
        print("\n### baselines")
        for label, expr in (("base rate (constant)", "0.0"),
                            ("persistence: events in the last minute", "f_n_events_last60"),
                            ("exact curve: reserve level at cutoff", "f_sold_frac_at_cut")):
            _, _, a = auc(con, "te", expr)
            print(f"    {label:<42} test AUC {a if a is not None else 0.5:.4f}")

        # ---- cell models
        def cell_model(name, feats, nbins=4):
            cuts = {}
            for f in feats:
                qs = [i / nbins for i in range(1, nbins)]
                cuts[f] = con.execute(
                    f"SELECT quantile_cont({f}, {qs}) FROM tr").fetchone()[0]
            def binexpr(f):
                c = cuts[f]
                e = "CASE "
                for i, v in enumerate(c):
                    e += f"WHEN {f}::DOUBLE <= {float(v)} THEN {i} "
                return e + f"ELSE {len(c)} END"
            key = " || '|' || ".join(f"({binexpr(f)})::VARCHAR" for f in feats)
            con.execute(f"CREATE OR REPLACE TABLE cells AS "
                        f"SELECT {key} AS cell, count(*) AS n, avg(y)::DOUBLE AS p FROM tr GROUP BY 1")
            base = float(con.execute("SELECT avg(y)::DOUBLE FROM tr").fetchone()[0])
            con.execute(f"""CREATE OR REPLACE TABLE scored AS
                SELECT t.y, coalesce((c.p::DOUBLE * c.n::DOUBLE
                                      + {PRIOR_M}::DOUBLE * CAST('{base!r}' AS DOUBLE))
                                     / (c.n::DOUBLE + {PRIOR_M}::DOUBLE),
                                     CAST('{base!r}' AS DOUBLE)) AS sc
                FROM (SELECT *, {key} AS cell FROM te) t LEFT JOIN cells c USING (cell)""")
            _, _, a = auc(con, "scored", "sc")
            brier = con.execute("SELECT avg(power(y - sc, 2))::DOUBLE FROM scored").fetchone()[0]
            ncell, unseen = con.execute(f"""
                SELECT (SELECT count(*) FROM cells),
                       (SELECT count(*) FROM te) - count(*)
                FROM (SELECT *, {key} AS cell FROM te) t JOIN cells c USING (cell)""").fetchone()
            return name, a, brier, ncell, unseen

        base = float(con.execute("SELECT avg(y)::DOUBLE FROM tr").fetchone()[0])
        b_brier = con.execute(
            f"SELECT avg(power(y - CAST('{base!r}' AS DOUBLE), 2))::DOUBLE FROM te").fetchone()[0]
        print("\n### cell models (quartile bins from the training fold only)")
        print(f"    {'model':<46} {'test AUC':<10} {'test Brier':<12} cells  test rows in an unseen cell")
        print(f"    {'constant = training base rate':<46} {'0.5000':<10} {b_brier:<12.5f} 1      0")
        for name, feats in (
                ("state only: reserve level at cutoff",
                 ["f_sold_frac_at_cut"]),
                ("A candle only, price shape",
                 ["c_log_ret", "c_log_max_up", "c_log_max_dn", "c_realized_range"]),
                ("B flow only, no price information",
                 ["f_n_events", "f_n_owners", "f_count_imb", "f_sign_runrate"]),
                ("state + A: does chart shape add to the state?",
                 ["f_sold_frac_at_cut", "c_log_max_up", "c_realized_range", "c_max_drawdown"]),
                ("state + B: does flow structure add to the state?",
                 ["f_sold_frac_at_cut", "f_n_owners", "f_n_events", "f_count_imb"]),
                ("state + A + B",
                 ["f_sold_frac_at_cut", "c_realized_range", "f_n_owners", "f_n_events"])):
            n, a, br, nc, un = cell_model(name, feats)
            print(f"    {n:<46} {a:<10.4f} {br:<12.5f} {nc:<6} {un}")
            if name.startswith("state + B"):
                con.execute("CREATE OR REPLACE TABLE best AS SELECT * FROM scored")
        n, a, br, nc, un = cell_model("negative control", ["rnd"])
        print(f"    {'negative control: uniform random score':<46} {a:<10.4f} {br:<12.5f} {nc:<6} {un}")

        # ---- calibration of the best flow model, so AUC is not the only claim
        show(con, "calibration on the test fold of the state + B flow-structure model", """
        WITH b AS (SELECT ntile(10) OVER (ORDER BY sc) AS d, y, sc FROM best)
        SELECT d AS decile, count(*) AS n, round(avg(sc), 4) AS predicted, round(avg(y), 4) AS observed
        FROM b GROUP BY 1 ORDER BY 1""",
             "predicted against observed; a model whose deciles separate the outcome but whose "
             "columns disagree is ranking well and calibrated badly, and only the first of those "
             "is what AUC reports")

    print("\nDONE")


if __name__ == "__main__":
    main()
