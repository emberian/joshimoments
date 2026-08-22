"""Do coins worth working have a distinguishable price-dynamics signature?

Applies Definition P2 (signature volatility) from the microstructure corpus to real series from the
ten-day corpus and answers two questions that were open.

  1. Does the signature slope separate coins that repeatedly produce large excursions from coins
     that trade just as often and do not?

     NO. Worked series (>=50% of workable half-hours carrying an >=8% unsigned range) and quiet ones
     (<=10%) had medians of 1.256 and 1.265 and rose in 25/39 and 24/38. Indistinguishable.

     That is partly a badly posed question, and the honest conclusion is narrower than the test
     looks: the bands are defined by AMPLITUDE and sigma^2 normalises amplitude out by construction.
     It measures shape. Tradeability is not readable from dynamics, and P2 was never the instrument
     for that.

  2. Are there DISCRETE dynamic regimes -- evidence that Ember's "2-5 types of crackle" are types
     rather than retrospective stories?

     NOT ON THIS AXIS. The distribution is broad and continuous: 22% mean-reverting, 34%
     flat/diffusive, 44% trending, median 1.234, interquartile range 0.79 to 1.82. The three largest
     gaps in the sorted sequence all sit in the sparse trending tail above 2.8 rather than between
     modes. One statistic cannot refute a multi-dimensional taxonomy, so this is evidence against
     types being visible HERE, not evidence against types.

The finding that matters is neither. The SPREAD is large and real: on the same market, in the same
window, some coins mean-revert strongly and others trend strongly. A rule assuming dip-and-recover
is wrong on the ~44% that trend; a momentum rule is wrong on the ~22% that revert.
Direction-agnostic extraction is not a nicety -- one rule cannot serve both populations.

SCOPE. Graduated AMM pools only. The bonding curve carries 79% of qualifying half-hours corpus-wide
and is deliberately excluded, because its price object is a validated model rather than an observed
ratio of two integers, and mixing them would confound dynamics with price construction. Study M0
separately found graduated pools carry roughly 50x the tradeable clip, so this is also the
population where a rule could actually be acted on.

Usage: uv run --offline python analysis/corpus/signature_regimes.py <corpus-dir>
"""

from __future__ import annotations

import statistics as st
import sys

import duckdb

LAGS = (1, 2, 4, 8, 16, 32)
MIN_TRADES = 400
MIN_WORKABLE = 20
QUALIFY_RANGE = 0.08
MIN_TRADES_PER_BLOCK = 4
SAMPLE_PER_BAND = 40


def signature_slope(prices: list[float]) -> float | None:
    """sigma^2(32) / sigma^2(1). Above 1 is net trending; below 1 is net mean reverting."""
    if len(prices) < MIN_TRADES:
        return None
    mean_price = sum(prices) / len(prices)
    curve = {}
    for lag in LAGS:
        diffs = [prices[i + lag] - prices[i] for i in range(len(prices) - lag)]
        curve[lag] = sum(d * d for d in diffs) / len(diffs) / (lag * mean_price * mean_price)
    return None if curve[1] <= 0 else curve[32] / curve[1]


def main() -> None:
    corpus = sys.argv[1]
    con = duckdb.connect()
    con.execute("SET memory_limit='10GB'")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE srs AS
        WITH blk AS (
          SELECT mint, block_time // 1800 AS blk, count(*) n,
                 max(price_sol_per_token) hi, min(price_sol_per_token) lo
          FROM read_parquet('{corpus}/out/trades/day=*/trades.parquet')
          WHERE price_sol_per_token IS NOT NULL AND price_kind = 'amm_pool_vault_fill'
          GROUP BY 1, 2
        )
        SELECT mint, count(*) workable,
               sum(CASE WHEN n >= {MIN_TRADES_PER_BLOCK}
                         AND hi / lo - 1 >= {QUALIFY_RANGE} THEN 1 ELSE 0 END) qual
        FROM blk WHERE n >= {MIN_TRADES_PER_BLOCK}
        GROUP BY 1 HAVING count(*) >= {MIN_WORKABLE}
    """)

    picked = {}
    bands = (("worked", "qual * 1.0 / workable >= 0.5"), ("quiet", "qual * 1.0 / workable <= 0.1"))
    for band, predicate in bands:
        query = (
            f"SELECT mint FROM srs WHERE {predicate} "
            f"ORDER BY hash(mint) LIMIT {SAMPLE_PER_BAND}"
        )
        picked[band] = [r[0] for r in con.execute(query).fetchall()]

    quoted = ", ".join(f"'{m}'" for m in picked["worked"] + picked["quiet"])
    rows = con.execute(f"""
        SELECT mint, price_sol_per_token
        FROM read_parquet('{corpus}/out/trades/day=*/trades.parquet')
        WHERE price_sol_per_token IS NOT NULL AND price_kind = 'amm_pool_vault_fill'
          AND mint IN ({quoted})
        ORDER BY mint, block_slot, tx_index
    """).fetchall()

    by_mint: dict[str, list[float]] = {}
    for mint, price in rows:
        by_mint.setdefault(mint, []).append(price)

    worked = set(picked["worked"])
    slopes = [
        (slope, "worked" if mint in worked else "quiet")
        for mint, prices in by_mint.items()
        if (slope := signature_slope(prices)) is not None
    ]

    for band in ("worked", "quiet"):
        vals = sorted(s for s, b in slopes if b == band)
        if vals:
            rising = sum(1 for v in vals if v > 1)
            median = st.median(vals)
            print(f"{band:>7}: n={len(vals):>3} median={median:.3f} rising={rising}/{len(vals)}")

    print()
    total = len(slopes)
    for low, high, name in ((0.0, 0.25, "strongly reverting"), (0.25, 0.75, "reverting"),
                            (0.75, 1.33, "flat / diffusive"), (1.33, 3.0, "trending"),
                            (3.0, float("inf"), "strongly trending")):
        n = sum(1 for s, _ in slopes if low <= s < high)
        print(f"  {name:<20} {n:>3} ({100 * n / total:>4.1f}%)")


if __name__ == "__main__":
    main()
