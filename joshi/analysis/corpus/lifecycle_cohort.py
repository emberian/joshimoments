"""Stage 1 of the birth-aligned lifecycle study: build the cohort and its event streams.

THE METHODOLOGICAL POINT.  Coin histories are not comparable on wall-clock time.  Every mint here
is re-indexed onto its own `dt = block_time - t0`, so "what does minute 3 look like" becomes a
question with a denominator.  In this corpus there is no callout tape, so the only available origin
is on-chain birth; the callout-aligned version of this same study is the sequel and needs capture we
do not retain.

t0 IS BIRTH, NOT FIRST TRADE.  For a mint whose bonding curve is seeded inside the window we observe
the create transaction itself, which is a stronger origin than "first trade I happened to see" and
is exactly Ember's "first day of a coin's life".  `first_trade_dt` is then a MEASURED quantity
rather than a definitional zero, and stage 2 reports its distribution.

MEMBERSHIP is three predicates, each of which throws away mints for a stated reason:

  1. SEED OBSERVED.  Some flow row has `token_pre_raw = 0 AND token_post_raw >= 5e14` at the mint's
     first observed transaction.  Without it the mint is LEFT TRUNCATED -- it existed before the
     window -- and no birth-aligned statement about it is possible.
  2. IDENTIFIED BONDING CURVE.  At least one trade priced `curve_constant_product_readout` with
     `venue_identified`.  This is the corpus's own venue evidence, validated against pump.fun's
     `virtual_*_reserves` to a median 4.8e-9 relative error, and it is what distinguishes a real
     bonding-curve market from a `%pump`-suffixed mint that merely has the vanity suffix.
  3. STANDARD SUPPLY.  The curve account's balance never exceeds 1.001e15 raw.  A mint launched on a
     different supply has a different K, and while K cancels out of any log-difference it does not
     cancel out of a level, so those mints are excluded rather than silently pooled.

THE EVENT STREAM IS THE CURVE ACCOUNT'S BALANCE PATH, not `trades.parquet`.  Venue identification in
`trades.parquet` is per (mint, owner) and a transaction can still land as `unsupported` when it is
multi-venue or the wSOL pairing is ambiguous; on a quarter of these mints half the curve's own
balance changes are unpriced there.  Reading the curve account's flow rows directly recovers every
state change.  Price is then applied as the documented MODEL, and is labelled as one.

PRICE IS A READOUT OF FLOW ON THIS VENUE.  p = K/(bal + offset)^2 is arithmetic on the one state
variable.  Nothing here treats a price shape as evidence independent of the flow that produced it;
stage 3 measures exactly how tight that identity is instead of assuming it.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ddb import SP, connect

# Validated in build_trades.py against pump.fun's own board tape.  A readout, not an observation.
CURVE_OFFSET_RAW = 73_000_000_000_000
CURVE_K = 30_000_000_000 * 1_073_000_000_000_000
STD_SUPPLY_RAW = 1_000_000_000_000_000
SUPPLY_TOL_RAW = 1_001_000_000_000_000
SEED_MIN_RAW = 500_000_000_000_000

WIN_LO, WIN_HI = 1785888000, 1786751999
H7 = 7 * 86400
OUT = f"{SP}/out/lifecycle"

F = f"read_parquet('{SP}/out/flow/day=*/flow.parquet')"
T = f"read_parquet('{SP}/out/trades/day=*/trades.parquet')"
MM = f"read_parquet('{SP}/out/mint_meta.parquet')"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    con = connect(memory_gb=32, threads=8)
    t0 = time.time()

    def step(name: str, sql: str) -> None:
        s = time.time()
        con.execute(sql)
        print(f"[{time.time() - t0:7.1f}s] {name} ({time.time() - s:.1f}s)", flush=True)

    # ---- the coverage hole.  A mint whose early window falls inside it looks dead when it is
    # ---- merely unobserved.  An absent row is an absent record, so the window is excluded.
    # `minutes.minute` is an epoch second truncated to the minute, so a normal step is 60.
    hole_lo, hole_hi, missing = con.execute(f"""
        WITH g AS (SELECT minute, lead(minute) OVER (ORDER BY minute) nxt
                   FROM read_parquet('{SP}/out/minutes.parquet'))
        SELECT min(minute), max(nxt), sum(nxt - minute - 60) / 60 FROM g WHERE nxt - minute > 60
    """).fetchone()
    print(f"coverage hole hull [{hole_lo}, {hole_hi}] = {(hole_hi - hole_lo) / 3600:.2f} h "
          f"containing {missing:.0f} absent minutes of 14400", flush=True)

    # ---- 1. seed: the mint's first observed transaction seeds an account with (nearly) all supply
    step("seed", f"""
    CREATE OR REPLACE TABLE seed AS
    WITH cand AS (
      SELECT mint, block_slot*1000000 + tx_index AS key, block_time, owner, token_post_raw
      FROM {F} WHERE token_pre_raw = 0 AND token_post_raw >= {SEED_MIN_RAW}),
    fk AS (SELECT mint, min(key) AS key0 FROM cand GROUP BY mint)
    SELECT c.mint, fk.key0 AS seed_key, any_value(c.block_time) AS seed_bt,
           max(c.token_post_raw) AS seed_post
    FROM cand c JOIN fk ON c.mint = fk.mint AND c.key = fk.key0
    GROUP BY c.mint, fk.key0""")

    # ---- 2. the identified bonding-curve account, from the corpus's own venue evidence
    # Ties are broken on the owner string so the cohort is byte-identical between runs; `mode()`
    # is not deterministic under a tie and moved two mints in and out between builds.
    step("curve_venue", f"""
    CREATE OR REPLACE TABLE curve_venue AS
    WITH c AS (
      SELECT mint, venue_owner, count(*) AS n FROM {T}
      WHERE price_kind = 'curve_constant_product_readout' AND venue_identified
      GROUP BY 1, 2)
    SELECT mint, first(venue_owner ORDER BY n DESC, venue_owner) AS curve_owner,
           sum(n) AS n_curve_px
    FROM c GROUP BY mint""")

    # ---- 3. the curve account's complete balance path
    step("cflow_all", f"""
    CREATE OR REPLACE TABLE cflow_all AS
    SELECT f.mint, f.block_slot*1000000 + f.tx_index AS key, f.block_time,
           f.token_pre_raw AS pre, f.token_post_raw AS post, f.token_delta_raw AS d,
           f.tx_has_wsol, f.tx_n_pump_mints, f.tx_n_owners, f.fee_lamports
    FROM {F} f
    JOIN curve_venue cv ON f.mint = cv.mint AND f.owner = cv.curve_owner""")

    step("bounds", """
    CREATE OR REPLACE TABLE cbounds AS
    SELECT mint, max(post) AS max_bal, min(post) AS min_bal, count(*) AS n_cev,
           max(block_time) AS last_cev_bt, min(key) AS first_key,
           arg_min(post, key) AS curve_post0, arg_min(pre, key) AS curve_pre0
    FROM cflow_all GROUP BY mint""")

    # ---- cohort
    excl = con.execute(f"""
      SELECT
        (SELECT count(*) FROM {MM})                                     AS all_pump_mints,
        (SELECT count(*) FROM seed)                                     AS seed_observed,
        (SELECT count(*) FROM seed s JOIN curve_venue c USING (mint))   AS seed_and_curve,
        (SELECT count(*) FROM seed s JOIN curve_venue c USING (mint)
           JOIN cbounds b USING (mint) WHERE b.max_bal <= {SUPPLY_TOL_RAW}) AS std_supply,
        (SELECT count(*) FROM seed s JOIN curve_venue c USING (mint)
           JOIN cbounds b USING (mint) WHERE b.max_bal <= {SUPPLY_TOL_RAW}
             AND b.first_key = s.seed_key AND b.curve_pre0 = 0) AS cohort
    """).fetchone()
    print("membership funnel:", dict(zip([d[0] for d in con.description], excl, strict=True)), flush=True)

    step("cohort", f"""
    CREATE OR REPLACE TABLE cohort AS
    SELECT s.mint, s.seed_bt AS t0, s.seed_key, s.seed_post, cv.curve_owner, cv.n_curve_px,
           b.n_cev, b.min_bal, b.max_bal, b.last_cev_bt, b.curve_post0,
           (s.seed_bt - {WIN_LO}) // 86400                       AS birth_day_idx,
           {WIN_HI} - s.seed_bt                                  AS obs_seconds,
           m.n_amm > 0                                           AS ever_amm,
           m.distinct_owners,
           -- horizon completeness: was the whole horizon inside the observed window, and clear of
           -- the one upstream coverage hole?
           (s.seed_bt + 3600  <= {WIN_HI}) AS complete_1h_raw,
           (s.seed_bt + 86400 <= {WIN_HI}) AS complete_24h_raw,
           (s.seed_bt + {H7}  <= {WIN_HI}) AS complete_7d_raw,
           NOT (s.seed_bt < {hole_hi} AND s.seed_bt + 3600  > {hole_lo}) AS clear_1h,
           NOT (s.seed_bt < {hole_hi} AND s.seed_bt + 86400 > {hole_lo}) AS clear_24h,
           NOT (s.seed_bt < {hole_hi} AND s.seed_bt + {H7}  > {hole_lo}) AS clear_7d
    FROM seed s
    JOIN curve_venue cv USING (mint)
    JOIN cbounds b USING (mint)
    JOIN {MM} m USING (mint)
    WHERE b.max_bal <= {SUPPLY_TOL_RAW}
      AND b.first_key = s.seed_key AND b.curve_pre0 = 0""")

    # ---- event stream, birth-aligned, first seven days, with the MODEL price attached
    # The create transaction IS the first trade whenever it carries an atomic creator buy, and on
    # 100% of this cohort it does.  Dropping it would remove the single largest early buy on the
    # median mint (~3.4% of the sellable curve against a 0.4% median trade) and would leave every
    # first-hour flow imbalance biased toward selling.  Its `pre` is the raw 0 of an account being
    # created, so the economically meaningful pre-state -- full supply on the curve -- is
    # substituted for that one row.
    step("cev", f"""
    CREATE OR REPLACE TABLE cev AS
    WITH e AS (
      SELECT c.mint, f.key, f.block_time - c.t0 AS dt,
             CASE WHEN f.key = c.seed_key THEN {STD_SUPPLY_RAW}::DECIMAL(38,0) ELSE f.pre END AS pre,
             f.post,
             CASE WHEN f.key = c.seed_key THEN f.post - {STD_SUPPLY_RAW} ELSE f.d END AS d,
             f.tx_has_wsol, f.tx_n_pump_mints, f.tx_n_owners, f.fee_lamports,
             (f.key = c.seed_key) AS is_create
      FROM cflow_all f JOIN cohort c USING (mint)
      WHERE f.block_time - c.t0 <= {H7} AND f.key >= c.seed_key)
    SELECT mint, key, dt, pre, post, d, is_create,
           CASE WHEN d < 0 THEN 1 WHEN d > 0 THEN -1 ELSE 0 END AS taker_sign,
           abs(d)::DOUBLE AS qty_raw,
           tx_has_wsol, tx_n_pump_mints, tx_n_owners, fee_lamports,
           -- MODEL, not an observation: the constant-product readout.  log price up to an additive
           -- constant that cancels from every difference.
           -2.0 * ln(post + {CURVE_OFFSET_RAW}) AS logp_post,
           -2.0 * ln(pre  + {CURVE_OFFSET_RAW}) AS logp_pre,
           -- MODEL SOL leg: the exact constant-product integral over the traversed reserve interval.
           {CURVE_K} * (1.0/(post + {CURVE_OFFSET_RAW}) - 1.0/(pre + {CURVE_OFFSET_RAW}))
               AS sol_lamports_curve_model
    FROM e""")

    # ---- taker side: who showed up, and when.  Curve account excluded by construction.
    step("towner", f"""
    CREATE OR REPLACE TABLE towner AS
    SELECT c.mint, f.owner, min(f.block_time - c.t0) AS first_dt, count(*) AS n_ev,
           sum(CASE WHEN f.token_delta_raw > 0 THEN 1 ELSE 0 END) AS n_buy_ev,
           sum(f.token_delta_raw)::DOUBLE AS net_raw,
           sum(abs(f.token_delta_raw))::DOUBLE AS gross_raw
    FROM {F} f JOIN cohort c ON f.mint = c.mint AND f.owner <> c.curve_owner
    WHERE f.block_time - c.t0 <= 86400 AND f.block_time >= c.t0
    GROUP BY 1, 2""")

    for tbl in ("cohort", "cev", "towner"):
        n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        con.execute(f"COPY {tbl} TO '{OUT}/{tbl}.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
        print(f"wrote {tbl}: {n:,} rows", flush=True)
    print(f"total {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
