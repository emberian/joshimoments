"""Bundle hypothesizer: which coordination SHAPE does a wallet set exhibit?

Not a same-slot detector. The operator's framing, verbatim: "well it isn't just the same
slot one entity. there may be less obvious strats, this one was just really obvious and
easy to find."

THE MOTIVATING MEASUREMENT (do not re-derive; this module is built to explain it).
A caller's buys were compared against four wallets over ten days:

    wallet          pairs +-4 slots   share at d_slot=0   shared-coin breadth
    6Eegkyd2...            2,639            52.8%         352/355  = 99.2%
    DkWzWsQT...            2,511            53.1%         338/342  = 98.8%
    D7xK1ZLz...            2,037            48.9%         275/276  = 99.6%
    FBvxneTq...  (control)   262            42.7%         247/17,908 = 1.4%

The control -- a universal sniper that touches 17,908 coins -- ALSO sits at 42.7%
same-slot. Same-slot co-occurrence is what LAUNCH SNIPING looks like: everybody racing a
new mint lands in the same few slots. It is not evidence of coordination. What separated
the three was PORTFOLIO SPECIFICITY (99% vs 1.4%), which contains no timing at all.

Hence the organising idea of this module: RANK CHANNELS BY EVASION COST. A coordinator
can jitter timing for free. They cannot cheaply change which coins they are obliged to
trade. So:

    channel                       evasion cost   what it would take to fake
    1 portfolio specificity       EXPENSIVE      trade coins you do not want to trade
    2 lifecycle coupling          EXPENSIVE      stagger wallet birth/retirement
    3 size choreography           MODERATE       randomise the size generator
    4 accumulate/dump asymmetry   STRUCTURAL     give up the multi-wallet accumulation
    5 timing                      CHEAP          add jitter. treat as corroborating ONLY.
    6 sequential / relay          --             (this is the EVASION of channel 5)
    7 supply parking / spray      EXPENSIVE      stop moving supply off the buying wallet
    8 wallet rotation             --             (this is the EVASION of channel 1)
    9 wash trading                MODERATE       stop manufacturing volume

The output is a HYPOTHESIS, not a verdict: "consistent with shape X, inconsistent with Y,
undecidable between Z and W given this corpus." Which channels could not fire because the
data cannot see them is part of the product.

NULLS. This repo has been burned FOUR times by naive nulls manufacturing effects
(RESULT_flow_signals; RESULT_copytrading 73x -> 0.98x; RESULT_caller_wallets 2.1
20x -> 1.20x; RESULT_cluster_callers 5 killed SOLVE). PROGRAM.md 3.13 therefore requires
TWO nulls compared at matched density, and 3.12 requires BOTH controls -- a known-ZERO
world AND a known-EFFECT world. Both are implemented. A naive null appears in the output
ONLY beside the structure-preserving one, to show the size of the trap.

DECLARED GAP, stated plainly because it bounds every conclusion below: the corpus carries
TOKEN balances only. There is no fee-payer column and no native-SOL transfer view in
state/bulk_pump/, and state/bulk_history/ (which does reach back to 2026-06-27) has no
owner column at all. Therefore FUNDING-ANCESTRY LINKAGE -- PROGRAM.md signal #2's
"first-funder + deposit-address reuse", which MELT reports as its single most productive
edge source -- IS NOT COMPUTABLE ON THIS MACHINE. It is not faked here. wSOL legs exist
(AMM trades expose them; pump.fun bonding-curve trades do not, the curve holds native SOL)
and are the only partial substitute.

WHAT ACTUALLY FIRED (2026-08-15 run, 145-wallet universe, 10-day corpus):

  ch1 portfolio specificity  FIRES   99.5% vs 6.3% control. The only channel that
                                     separates on its own. Gate: 3/3 positives, 0/1
                                     control, 0/40 HARD negatives, 1/100 randoms (a
                                     discovery, not a false positive -- see below).
  ch2 lifecycle coupling     FIRES   two of the three share a first slot EXACTLY
                                     (437,325,417); 0 of 2,556 background pairs tie.
                                     Partly confounded with ch1 -- they share the mint.
  ch3 size choreography      FIRES   on the CROSS-WALLET statistic only (log-size-ratio
                                     sd 0.64-0.77 vs background 2.32). The self-CV
                                     statistic from RESULT_caller_wallets 6.1 does NOT
                                     separate here.
  ch4 accumulate/dump        NO      and worse, CONFOUNDED with ch1 -- see channel4.
                                     Marino's asymmetry is ABSENT: this set accumulates
                                     AND distributes multi-wallet, symmetrically.
  ch5 timing                 WEAK    separates by effect size (ROT 16x vs 2.3x) but the
                                     p-value is at the MC floor for every arm including
                                     the control. NOT an atomic bundle: tx_index median
                                     offset 6, only ~13% adjacent, fees NOT elevated.
  ch6 sequential/relay       NO      the positives are CO-timed (IoU 0.86-0.93), not a
                                     relay. Channel implemented, found nothing here.
  ch7 supply parking         NO      on the caller set. On the operator's coins it found
                                     a distributor, not parked supply -- see cmd_operator.
  ch8 wallet rotation        NO      zero rotation links in this universe.
  ch9 wash trading           CEILING 2.38% of the set's volume could be internal. Not
                                     evidence -- a market maker leaves the same trace.

THE DUST CORRECTION, which changes how the control should be described: 15,671 of the
control's 17,908 "coins" are mints it NEVER TRADED -- inbound airdrop dust it received
and ignored (24,699 inbound transfer legs, ZERO outbound). Its real traded book is 2,237
coins, so its true specificity is 6.3%, not 1.4%. The separation is 99.6% vs 6.3%
rather than 99.2% vs 1.4%. Still decisive, and now for the right reason.

SHAPE, which is the actual product. The containment matrix is NESTED, not merely
overlapping: D7xK (277) subset-of DkWz (343) subset-of 6Eeg (355) subset-of CALLER (494),
each at 98-99.6%, AND the three are 95.8-99.6% contained in EACH OTHER. Three independent
copy bots following one caller would each be contained in the caller and NOT in each
other. So the hypothesis this set supports is ONE FLEET with a breadth hierarchy, not
three copiers. A fourth wallet, 7uyGRgoCRKfynPbB35kWQwEGz9pmRvUyNFunV939mXpN (53 coins,
96.2% contained), is proposed as a member and was found by the framework, not by hand.

WHAT THIS METHOD STILL CANNOT SEPARATE, stated because the operator needs the limit:
one entity's wallets vs a co-located fleet renting the same signal. Both produce nested
portfolios and symmetric same-slot timing. Separating them needs funding ancestry, and
funding ancestry is not computable here (see the DECLARED GAP above).

Run order (every number in this docstring reproduces from these, in this order):
    uv run python -m studies.bundle_hypothesizer pop        # ~7 min, coin popularity
    uv run python -m studies.bundle_hypothesizer universe   # picks the 145-wallet universe
    uv run python -m studies.bundle_hypothesizer extract    # ~3 min, wallet-anchored
    uv run python -m studies.bundle_hypothesizer coins      # ~2 min, the operator's four
    uv run python -m studies.bundle_hypothesizer channel1   # the load-bearing channel
    uv run python -m studies.bundle_hypothesizer validate   # THE GATE
    uv run python -m studies.bundle_hypothesizer matched    # two nulls, matched density
    uv run python -m studies.bundle_hypothesizer controls   # known-ZERO and known-EFFECT
    uv run python -m studies.bundle_hypothesizer channels   # channels 2-9
    uv run python -m studies.bundle_hypothesizer operator   # the payoff
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(REPO, "state", "bulk_pump", "daily")
CACHE = os.path.join(REPO, ".cache", "bundle")
OUT = os.path.join(REPO, "state", "crime")
PANEL = os.path.join(REPO, ".cache", "jackduval", "panel-legs.parquet")

# ---------------------------------------------------------------------------
# the known world. These are inputs to the VALIDATION GATE, not tuned parameters.
# ---------------------------------------------------------------------------

CALLER = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh"

# the known positive: three wallets the operator found trading in the caller's slots
POSITIVE = [
    "6Eegkyd2qNzxSzZz3PH3jiDyqL5HFcHdcsb9zfMzWHKB",
    "DkWzWsQT9ZThfkFfdZqzNT59dZMiJXp81oob8QBG9UcT",
    "D7xK1ZLz8KQNWN8aU1jbzNAuT5xwqgFrCUUYodVU4G42",
]

# the negative control: a universal sniper. 17,908 coins, 42.7% same-slot with the caller.
# If a channel cannot tell this apart from POSITIVE, that channel is measuring sniping.
CONTROL = "FBvxneTq8dY7WKxj924CseuveWzDL5tN9JuSW3S9nJkN"

WSOL = "So11111111111111111111111111111111111111112"

OPERATOR_COINS = {
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
}

# Launch dates vs corpus coverage. bulk_pump spans 2026-08-05..2026-08-14 ONLY.
# DREGG (2026-06-27) and SOLVE (2026-07-20) launched BEFORE the corpus starts, and the one
# tape that reaches back (state/bulk_history) has no owner column. Their LAUNCH bundling is
# therefore not answerable here and this module refuses to answer it.
COIN_LAUNCH = {
    "nosis": ("2026-08-09", "IN CORPUS -- launch window visible"),
    "weave": ("2026-08-03", "PARTIAL -- launched 2 days before corpus start; "
                            "post-launch accumulation visible, create-slot bundle is NOT"),
    "SOLVE": ("2026-07-20", "OUT OF CORPUS -- no launch verdict possible"),
    "DREGG": ("2026-06-27", "OUT OF CORPUS -- no launch verdict possible"),
}


def _duck(threads: int = 3, mem: str = "4GB"):
    """Shared-machine settings. Other agents are on this box; do not raise these.

    UNNEST over a full day's `post` materialises ~100M struct rows and segfaulted this box
    at higher limits. Every query below filters FIRST and unnests the small result.
    """
    import duckdb

    con = duckdb.connect()
    for pragma in (
        f"PRAGMA threads={threads}",
        f"SET memory_limit='{mem}'",
        "SET preserve_insertion_order=false",
        "PRAGMA disable_progress_bar",
    ):
        con.execute(pragma)
    return con


def _sqlist(vals) -> str:
    return ",".join("'" + str(v).replace("'", "") + "'" for v in vals)


def _days() -> list[str]:
    return sorted(glob.glob(os.path.join(DAILY, "*.parquet")))


# ===========================================================================
# STAGE 1 -- universe selection
# ===========================================================================

def cmd_universe(n_hard: int = 40, n_random: int = 100, seed: int = 20260815) -> int:
    """Pick the wallet universe: known positives, the control, HARD negatives, randoms.

    The hard negatives matter more than the randoms. `64hP97Bwr5Pub...` shares 302 of the
    caller's mints -- MORE than known-positive D7xK1ZLz's 275. So raw shared-coin COUNT
    cannot possibly be the discriminator, and a gate built only against random co-traders
    would be trivially passable. The hard negatives are what make the gate mean something.
    """
    import numpy as np
    import pandas as pd

    os.makedirs(CACHE, exist_ok=True)
    rng = np.random.default_rng(seed)
    con = _duck()

    caller_mints = con.execute(
        f"SELECT DISTINCT mint FROM read_parquet('{PANEL}') WHERE owner='{CALLER}'"
    ).df()["mint"].tolist()

    co = con.execute(f"""
        SELECT owner, count(DISTINCT mint) AS shared, count(*) AS legs
        FROM read_parquet('{PANEL}')
        WHERE mint IN ({_sqlist(caller_mints)}) AND delta <> 0
        GROUP BY 1
    """).df()

    known = set(POSITIVE) | {CALLER, CONTROL}
    pool = co[~co.owner.isin(known)].copy()

    hard = pool.nlargest(n_hard, "shared")
    rest = pool[~pool.owner.isin(set(hard.owner))]

    # stratify the randoms across shared-count bands so the background spans the degree
    # range. A background drawn uniformly would be ~all 1-coin wallets (median shared = 1)
    # and would make any of the candidates look extraordinary for trivial reasons.
    bands = [(1, 1), (2, 4), (5, 19), (20, 49), (50, 10_000)]
    per = max(1, n_random // len(bands))
    picks = []
    for lo, hi in bands:
        sub = rest[(rest.shared >= lo) & (rest.shared <= hi)]
        take = min(per, len(sub))
        if take:
            picks.append(sub.iloc[rng.choice(len(sub), take, replace=False)])
    rand = pd.concat(picks) if picks else rest.head(0)

    universe = {
        "caller": CALLER,
        "positive": POSITIVE,
        "control": CONTROL,
        "hard_negative": hard.owner.tolist(),
        "random_cotrader": rand.owner.tolist(),
        "caller_mints": caller_mints,
        "shared_counts": dict(zip(co.owner, co.shared.astype(int))),
    }
    wallets = sorted(
        {CALLER, CONTROL} | set(POSITIVE) | set(universe["hard_negative"])
        | set(universe["random_cotrader"])
    )
    universe["wallets"] = wallets

    with open(os.path.join(CACHE, "universe.json"), "w") as fh:
        json.dump(universe, fh)

    print(f"caller mints (panel)      : {len(caller_mints)}")
    print(f"co-traders on those mints : {len(co):,}")
    print(f"  hard negatives (top {n_hard} by shared) : {len(hard)} "
          f"[shared {hard.shared.min()}..{hard.shared.max()}]")
    print(f"  random co-traders, stratified          : {len(rand)}")
    print(f"UNIVERSE WALLETS: {len(wallets)}")
    return 0


# ===========================================================================
# STAGE 2 -- wallet-anchored corpus extraction
# ===========================================================================

_EXTRACT_SQL = """
WITH hit AS (
  SELECT signature, block_slot, block_time, tx_index, fee_lamports, pre, post
  FROM read_parquet('{day}')
  WHERE (err IS NULL OR err = '')
    AND list_has_any(list_transform(post, x -> x.owner), {wl})
),
po AS (
  SELECT signature, block_slot, block_time, tx_index, fee_lamports,
         u.p.owner AS owner, u.p.mint AS mint, u.p.account_index AS ai,
         TRY_CAST(u.p.amount AS DOUBLE) AS amt
  FROM hit, UNNEST(hit.post) AS u(p)
),
pr AS (
  SELECT signature, u.p.owner AS owner, u.p.mint AS mint,
         u.p.account_index AS ai, TRY_CAST(u.p.amount AS DOUBLE) AS amt
  FROM hit, UNNEST(hit.pre) AS u(p)
)
SELECT po.signature, po.block_slot, po.block_time, po.tx_index, po.fee_lamports,
       po.owner, po.mint, po.amt - COALESCE(pr.amt, 0) AS delta
FROM po LEFT JOIN pr USING (signature, owner, mint, ai)
WHERE po.amt - COALESCE(pr.amt, 0) <> 0
"""


def cmd_extract(threads: int = 3) -> int:
    """Full-corpus, wallet-anchored. Emits EVERY leg of every tx touching a universe wallet.

    Keeping the non-universe legs is deliberate and load-bearing: the counterparty of a leg
    is what separates a TRADE (counterparty is the mint's bonding curve / AMM pool) from a
    TRANSFER (counterparty is an ordinary wallet, and the curve does not move). Channel 7
    (supply parking) is built entirely on that distinction and cannot be computed from the
    universe wallets' own legs alone.
    """
    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    wl = "[" + _sqlist(uni["wallets"]) + "]"
    dst_dir = os.path.join(CACHE, "wallet_legs")
    os.makedirs(dst_dir, exist_ok=True)
    con = _duck(threads=threads)

    for day in _days():
        tag = os.path.basename(day)[:10]
        dst = os.path.join(dst_dir, f"{tag}.parquet")
        if os.path.exists(dst):
            print(f"skip {tag}", flush=True)
            continue
        t0 = time.time()
        sql = _EXTRACT_SQL.format(day=day, wl=wl)
        con.execute(f"COPY ({sql}) TO '{dst}' (FORMAT PARQUET)")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{dst}')").fetchone()[0]
        print(f"done {tag}  {n:,} legs  {time.time() - t0:.0f}s", flush=True)
    print("EXTRACT COMPLETE", flush=True)
    return 0


def cmd_pop(threads: int = 3) -> int:
    """Corpus-wide coin popularity: the weight vector the POP null needs.

    This is the ONE query in the module that unnests a whole day without a wallet or mint
    prefilter, and it is only survivable because it aggregates immediately and uses
    approx_count_distinct (HyperLogLog) instead of an exact distinct over ~400k owners.
    ~30-60s per day at threads=3 / 4GB. A plain `SELECT ... FROM parquet, UNNEST(post)`
    without the GROUP BY materialises ~100M struct rows per day and segfaults the box.
    """
    dst_dir = os.path.join(CACHE, "mint_pop")
    os.makedirs(dst_dir, exist_ok=True)
    con = _duck(threads=threads)
    for day in _days():
        tag = os.path.basename(day)[:10]
        dst = os.path.join(dst_dir, f"{tag}.parquet")
        if os.path.exists(dst):
            print(f"skip {tag}", flush=True)
            continue
        t0 = time.time()
        con.execute(f"""COPY (
          SELECT u.p.mint AS mint,
                 approx_count_distinct(u.p.owner) AS traders,
                 count(*) AS legs,
                 min(t.block_slot) AS first_slot,
                 max(t.block_slot) AS last_slot
          FROM read_parquet('{day}') t, UNNEST(t.post) AS u(p)
          WHERE (t.err IS NULL OR t.err = '')
          GROUP BY 1
        ) TO '{dst}' (FORMAT PARQUET)""")
        print(f"done {tag}  {time.time() - t0:.0f}s", flush=True)
    print("POP COMPLETE", flush=True)
    return 0


def cmd_coins(threads: int = 3) -> int:
    """Coin-anchored extraction for the operator's four mints: every leg, every holder."""
    mints = "[" + _sqlist(OPERATOR_COINS.values()) + "]"
    dst_dir = os.path.join(CACHE, "operator_legs")
    os.makedirs(dst_dir, exist_ok=True)
    con = _duck(threads=threads)

    sql_tpl = """
    WITH hit AS (
      SELECT signature, block_slot, block_time, tx_index, fee_lamports, pre, post
      FROM read_parquet('{day}')
      WHERE (err IS NULL OR err = '')
        AND list_has_any(list_transform(post, x -> x.mint), {mints})
    ),
    po AS (
      SELECT signature, block_slot, block_time, tx_index, fee_lamports,
             u.p.owner AS owner, u.p.mint AS mint, u.p.account_index AS ai,
             TRY_CAST(u.p.amount AS DOUBLE) AS amt
      FROM hit, UNNEST(hit.post) AS u(p)
    ),
    pr AS (
      SELECT signature, u.p.owner AS owner, u.p.mint AS mint,
             u.p.account_index AS ai, TRY_CAST(u.p.amount AS DOUBLE) AS amt
      FROM hit, UNNEST(hit.pre) AS u(p)
    )
    SELECT po.signature, po.block_slot, po.block_time, po.tx_index, po.fee_lamports,
           po.owner, po.mint, po.amt - COALESCE(pr.amt, 0) AS delta, po.amt AS post_amt
    FROM po LEFT JOIN pr USING (signature, owner, mint, ai)
    WHERE po.amt - COALESCE(pr.amt, 0) <> 0
    """
    # post_amt is an ABSOLUTE on-chain balance, so holder CONCENTRATION is computable for
    # all four coins even where the corpus does not reach their launch. What is truncated
    # for DREGG/SOLVE is the TRANSFER HISTORY, which makes their bundle-adjusted delta a
    # LOWER BOUND (pre-2026-08-05 spray is invisible), not a wrong number.
    for day in _days():
        tag = os.path.basename(day)[:10]
        dst = os.path.join(dst_dir, f"{tag}.parquet")
        if os.path.exists(dst):
            print(f"skip {tag}", flush=True)
            continue
        t0 = time.time()
        con.execute(f"COPY ({sql_tpl.format(day=day, mints=mints)}) TO '{dst}' (FORMAT PARQUET)")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{dst}')").fetchone()[0]
        print(f"done {tag}  {n:,} legs  {time.time() - t0:.0f}s", flush=True)
    print("COINS COMPLETE", flush=True)
    return 0


# ---------------------------------------------------------------------------
# Firing thresholds. Declared ONCE, here, in null units -- never per case.
#
# MIN_PORTFOLIO is a POWER FLOOR, not a filter. A wallet that traded exactly one coin,
# and that coin happens to be the caller's, scores 100% specificity and a curveball ratio
# of 1e9. That is not evidence; it is n=1. Wallets below the floor are reported as
# UNDECIDABLE and counted, never as negatives -- the RESULT_cluster_callers lesson that
# "SOLVE is underpowered, not cleanly null".
# ---------------------------------------------------------------------------
MIN_PORTFOLIO = 20        # coins a wallet must trade before channel 1 can fire at all
FIRE_SPEC = 0.60          # |X n anchor| / |X|
FIRE_POP_Z = 5.0          # sigmas over the popularity-weighted configuration model
FIRE_CB_RATIO = 3.0       # x over the degree-preserving curveball expectation
FIRE_CB_P = 0.01
HUB_DEGREE = 20           # transfer fan-out at which an address is a DISTRIBUTOR, not a
                          # member -- see the hub-exclusion note in cmd_operator

TRIALS = {
    "channels_preregistered": 9,
    "nulls_per_channel": 2,
    "threshold_sets_tried": 1,
    "note": "One threshold set, declared before the gate was run, applied unchanged to "
            "positives, control, hard negatives and randoms. PROGRAM.md 3.9: past ~7 "
            "independent configurations an in-sample Sharpe of 1 is an OOS zero. The "
            "count that matters here is 9 channels x 2 nulls = 18 tests against one "
            "known positive set, so a Bonferroni-flavoured read of any single channel's "
            "p should divide by 18.",
}


# ===========================================================================
# NULLS. Two of them, per PROGRAM.md 3.13 -- "a single null is a knob, not a test".
# ===========================================================================

def _curveball(rows: list[set], n_iter: int, rng) -> list[set]:
    """Degree-preserving bipartite randomisation, Strona et al.

    Lifted from studies/operator_crime.py:902 rather than reinvented. Trades the
    non-shared elements of two rows, so EVERY wallet's coin count and EVERY coin's
    wallet count is exactly preserved. This is the null the SVN study had to adopt after
    the hypergeometric one validated ~99 pairs out of nothing.
    """
    out = [set(r) for r in rows]
    n = len(out)
    if n < 2:
        return out
    for _ in range(n_iter):
        i, j = int(rng.integers(0, n)), int(rng.integers(0, n))
        if i == j:
            continue
        a, b = out[i], out[j]
        common = a & b
        pool = list((a | b) - common)
        if not pool:
            continue
        rng.shuffle(pool)
        k = len(a) - len(common)
        out[i] = common | set(pool[:k])
        out[j] = common | set(pool[k:])
    return out


def _pop_null_moments(nx: int, ny: int, weights):
    """Analytic popularity-weighted configuration model for |X n Y|.

    Each coin c is in wallet X's portfolio independently with probability
    p_c(X) = 1 - (1 - w_c)^nx, where w_c is c's share of all corpus trader-slots. This
    holds each wallet's DEGREE fixed (in expectation) and each coin's POPULARITY fixed --
    the two things a naive hypergeometric null throws away, which is exactly how the
    hypergeometric null in RESULT_svn_cotrading validated 99 pairs out of nothing.

    |X n Y| is then a Poisson-binomial, so its mean and variance are exact and no Monte
    Carlo is needed -- which is what makes this affordable across ~10k pairs.
    """
    import numpy as np

    px = -np.expm1(nx * np.log1p(-weights))
    py = -np.expm1(ny * np.log1p(-weights))
    # renormalise so the degrees come out right despite the independence approximation
    px *= nx / max(px.sum(), 1e-12)
    py *= ny / max(py.sum(), 1e-12)
    np.clip(px, 0.0, 1.0, out=px)
    np.clip(py, 0.0, 1.0, out=py)
    q = px * py
    return float(q.sum()), float((q * (1.0 - q)).sum())


def _hypergeom_mean(nx: int, ny: int, N: int) -> float:
    """The NAIVE null. Reported ONLY beside the structure-preserving ones, to show the
    size of the trap -- the house rule after four separate headline collapses."""
    return nx * ny / max(N, 1)


# ===========================================================================
# CHANNEL 1 -- PORTFOLIO SPECIFICITY (expensive to evade; the load-bearing channel)
# ===========================================================================

@dataclass
class PairScore:
    a: str
    b: str
    n_a: int
    n_b: int
    inter: int
    spec_a: float          # |A n B| / |A|  -- "how much of A's book is B's book"
    spec_b: float
    naive_ratio: float     # observed / hypergeometric expectation  (THE TRAP)
    pop_ratio: float       # observed / popularity-weighted expectation
    pop_z: float
    cb_ratio: float = float("nan")   # observed / curveball expectation
    cb_p: float = float("nan")
    label: str = ""


def _load_portfolios():
    import pandas as pd

    df = pd.read_parquet(os.path.join(CACHE, "portfolios.parquet"))
    return {w: set(g["mint"]) for w, g in df.groupby("owner")}


def _load_weights(mints):
    """Corpus-wide coin popularity -> the weight vector for the POP null."""
    import numpy as np

    con = _duck(threads=2, mem="3GB")
    pop = con.execute(f"""
        SELECT mint, sum(traders) AS traders
        FROM read_parquet('{os.path.join(CACHE, 'mint_pop', '*.parquet')}')
        GROUP BY 1
    """).df()
    total_mints = len(pop)
    lut = dict(zip(pop["mint"], pop["traders"].astype(float)))
    w = np.array([lut.get(m, 1.0) for m in mints], dtype=float)
    w /= w.sum()
    return w, total_mints, lut


def channel1_portfolio(portfolios, pairs, *, n_null: int = 200, burn: int = 30_000,
                       thin: int = 1_000, seed: int = 20260815, verbose: bool = True):
    """Both directions matter and both are reported: containment is ASYMMETRIC.

    D7xK's 276-coin book is 99.6% inside the caller's, but the caller's 494-coin book is
    only 56% inside D7xK's. A symmetric statistic (Jaccard) averages those into mush and
    would rank hard negatives above true members.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    wallets = sorted(portfolios)
    idx = {w: i for i, w in enumerate(wallets)}
    all_mints = sorted({m for s in portfolios.values() for m in s})
    weights, n_corpus_mints, _ = _load_weights(all_mints)

    rows = [portfolios[w] for w in wallets]
    want = {(a, b) for a, b in pairs}

    # --- structure-preserving null #2: curveball MCMC on the real incidence.
    # One long chain with thinning rather than n_null independent chains -- 200 fresh
    # chains at this degree spread (1 .. 18,811 coins) would not finish.
    cb_counts = {p: [] for p in want}
    state = [set(r) for r in rows]
    state = _curveball(state, burn, rng)
    for s in range(n_null):
        state = _curveball(state, thin, rng)
        for (a, b) in want:
            cb_counts[(a, b)].append(len(state[idx[a]] & state[idx[b]]))
        if verbose and (s + 1) % 50 == 0:
            print(f"    curveball sample {s + 1}/{n_null}", flush=True)

    out = []
    for (a, b) in pairs:
        A, B = portfolios[a], portfolios[b]
        na, nb, inter = len(A), len(B), len(A & B)
        pop_mu, pop_var = _pop_null_moments(na, nb, weights)
        naive_mu = _hypergeom_mean(na, nb, n_corpus_mints)
        draws = np.array(cb_counts[(a, b)], dtype=float)
        cb_mu = float(draws.mean())
        # p-floor 1/(B+1), per svn_cotrading's NullDraw -- a Monte Carlo null can never
        # report a p smaller than its own resolution and must not pretend otherwise.
        cb_p = float((draws >= inter).sum() + 1) / (n_null + 1)
        out.append(PairScore(
            a=a, b=b, n_a=na, n_b=nb, inter=inter,
            spec_a=inter / max(na, 1), spec_b=inter / max(nb, 1),
            naive_ratio=inter / max(naive_mu, 1e-9),
            pop_ratio=inter / max(pop_mu, 1e-9),
            pop_z=(inter - pop_mu) / max(pop_var ** 0.5, 1e-9),
            cb_ratio=inter / max(cb_mu, 1e-9), cb_p=cb_p,
        ))
    return out, n_corpus_mints


# ===========================================================================
# The leg table every remaining channel reads.
# ===========================================================================

def _legs(universe_only: bool = True):
    """Universe wallets' own legs, corpus-wide, trades and transfers alike."""
    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    con = _duck(threads=2, mem="3GB")
    where = f"AND owner IN ({_sqlist(uni['wallets'])})" if universe_only else ""
    return con.execute(f"""
        SELECT signature, block_slot, block_time, tx_index,
               TRY_CAST(fee_lamports AS BIGINT) AS fee_lamports, owner, mint, delta
        FROM read_parquet('{os.path.join(CACHE, 'wallet_legs', '*.parquet')}')
        WHERE mint <> '{WSOL}' AND delta <> 0 {where}
    """).df()


def _corpus_slot_bounds():
    con = _duck(threads=2, mem="3GB")
    lo, hi = con.execute(
        f"SELECT min(block_slot), max(block_slot) "
        f"FROM read_parquet('{os.path.join(CACHE, 'wallet_legs', '*.parquet')}')"
    ).fetchone()
    return int(lo), int(hi)


# ===========================================================================
# CHANNEL 2 -- LIFECYCLE COUPLING (expensive to evade)
# ===========================================================================

def channel2_lifecycle(legs, uni):
    """Wallets born together and retired together.

    THE CONFOUND, stated before the number: if a set's first activity is all sniping the
    SAME launch, an identical first slot is a restatement of channel 1, not independent
    evidence. This function therefore reports the FIRST-SEEN MINT alongside the first
    slot, and marks the channel CONFOUNDED whenever the set shares it.

    CENSORING: a wallet whose first leg lands on the corpus's first slot existed before
    the corpus. Those are LEFT-CENSORED and counted, not silently dropped.
    """
    import numpy as np

    lo, hi = _corpus_slot_bounds()
    g = legs.sort_values("block_slot").groupby("owner")
    life = g.agg(first_slot=("block_slot", "min"), last_slot=("block_slot", "max"),
                 legs=("block_slot", "size")).reset_index()
    firstmint = g.head(1).set_index("owner")["mint"].to_dict()
    lastmint = g.tail(1).set_index("owner")["mint"].to_dict()
    life["first_mint"] = life.owner.map(firstmint)
    life["last_mint"] = life.owner.map(lastmint)
    life["label"] = [_label_of(w, uni) for w in life.owner]
    # censoring windows: within ~1 slot-hour (9000 slots) of a corpus edge
    life["left_censored"] = life.first_slot <= lo + 9_000
    life["right_censored"] = life.last_slot >= hi - 9_000

    pos = life[life.label.isin(["POSITIVE"])]
    out = {
        "corpus_slot_lo": lo, "corpus_slot_hi": hi,
        "left_censored_n": int(life.left_censored.sum()),
        "right_censored_n": int(life.right_censored.sum()),
        "n_wallets": len(life),
        "positive_first_slots": dict(zip(pos.owner, pos.first_slot.astype(int))),
        "positive_first_mints": dict(zip(pos.owner, pos.first_mint)),
        "positive_last_slots": dict(zip(pos.owner, pos.last_slot.astype(int))),
        "positive_last_mints": dict(zip(pos.owner, pos.last_mint)),
    }
    # null: how often do two BACKGROUND wallets share a first slot this closely?
    bg = life[life.label.isin(["random", "hard_neg"]) & ~life.left_censored]
    fs = bg.first_slot.to_numpy()
    if len(fs) > 2:
        d = np.abs(fs[:, None] - fs[None, :])
        iu = np.triu_indices(len(fs), 1)
        gaps = d[iu]
        out["bg_first_slot_gap_median"] = float(np.median(gaps))
        out["bg_pairs_exact_same_first_slot"] = int((gaps == 0).sum())
        out["bg_pairs"] = len(gaps)
        out["bg_p_exact_tie"] = float((gaps == 0).sum() + 1) / (len(gaps) + 1)
    ps = sorted(out["positive_first_slots"].values())
    out["positive_first_slot_spread"] = int(ps[-1] - ps[0]) if ps else None
    out["positive_shares_first_mint"] = len(set(out["positive_first_mints"].values())) == 1
    ls = sorted(out["positive_last_slots"].values())
    out["positive_last_slot_spread"] = int(ls[-1] - ls[0]) if ls else None
    out["positive_shares_last_mint"] = len(set(out["positive_last_mints"].values())) == 1
    return out, life


# ===========================================================================
# CHANNEL 3 -- SIZE CHOREOGRAPHY (moderate evasion cost)
# ===========================================================================

def channel3_size(legs, uni, anchor, min_buys: int = 20, cv_gate: float = 0.25):
    """Two statistics, because they answer different questions.

    (a) SELF-UNIFORMITY -- a wallet's own buys on one coin at CV < 0.25, the
        RESULT_caller_wallets 6.1 measure (258 of 3,606 legs there, 7.2%). Inherited
        caveat, VERBATIM, because it applies here unchanged: "A market maker and a
        wash-trader leave the same trace and nothing here separates them." So this is a
        CEILING on machinery, never evidence of bundling.

    (b) CROSS-WALLET RATIO STABILITY -- for a pair co-buying many coins, the CV of the
        size ratio ACROSS coins. A fleet splitting one target notional by fixed weights
        holds that ratio stable; two independent traders do not. This is the statistic
        that is actually about coordination rather than about machinery, and it is the
        one (a) cannot give you.
    """
    import numpy as np

    buys = legs[legs.delta > 0]
    rows = []
    for (w, m), g in buys.groupby(["owner", "mint"]):
        if len(g) < min_buys:
            continue
        v = g.delta.to_numpy()
        mu = v.mean()
        if mu > 0:
            rows.append((w, m, len(v), float(v.std() / mu)))
    self_cv = {}
    for w, _m, _n, cv in rows:
        self_cv.setdefault(w, []).append(cv)
    self_stat = {w: {"legs_ge_min_buys": len(c),
                     "uniform_legs": int(sum(x < cv_gate for x in c)),
                     "median_cv": float(np.median(c))} for w, c in self_cv.items()}

    # (b) ratio stability against the anchor
    med = buys.groupby(["owner", "mint"]).delta.median().unstack(0)
    ratio_stat = {}
    if anchor in med.columns:
        a = med[anchor]
        for w in med.columns:
            if w == anchor:
                continue
            both = np.log(med[w] / a).replace([np.inf, -np.inf], np.nan).dropna()
            if len(both) >= 20:
                ratio_stat[w] = {"n_coins": len(both),
                                 "log_ratio_sd": float(both.std()),
                                 "log_ratio_median": float(both.median())}
    return self_stat, ratio_stat, len(rows)


# ===========================================================================
# CHANNEL 4 -- ACCUMULATE / DUMP ASYMMETRY (structural; needs no timing at all)
# ===========================================================================

def channel4_asymmetry(legs, uni, members):
    """Marino VIII: "accumulation is often executed through multiple wallets, and it is
    common for the subsequent dump to be carried out by a single one."

    So the statistic is a WALLET-COUNT asymmetry between the accumulation and the
    distribution leg, per mint, measured inside the candidate set and compared with
    same-size background sets on the same mints. This is the scale-free form
    crime_signatures.choreography() uses -- buy-side minus sell-side concentration --
    restricted here to a candidate set instead of a whole pool.

    MEASURED RESULT AND ITS CONFOUND, recorded here so the number is not read as support
    it does not give. multi_wallet_accum_share came out 0.977 observed against 0.030
    background at p = 0.016 -- which IS the Monte Carlo floor at 60 draws (1/61 = 0.0164),
    so the p adds nothing. Worse, the statistic is near-TAUTOLOGICAL: a candidate set is
    selected for trading the same coins, so of course more than one member buys each coin,
    while random background wallets barely co-occur at all. This channel RESTATES channel
    1; it does not corroborate it, and it should not be counted as a second witness.

    What IS independent here, and is a genuine negative: Marino's asymmetry is ABSENT.
    mean_buy_wallets and mean_sell_wallets both came out 2.746 -- identical -- so this set
    accumulates multi-wallet AND distributes multi-wallet. single_wallet_dump_share is
    0.023 observed against 0.984 background. Whatever this fleet is, it is not the
    accumulate-many / dump-one shape Marino describes.
    """
    import numpy as np

    def hhi(x):
        s = np.abs(np.asarray(x, dtype=float))
        t = s.sum()
        return float(((s / t) ** 2).sum()) if t > 0 else float("nan")

    def stat_for(ws):
        ws = set(ws)
        sub = legs[legs.owner.isin(ws)]
        per = []
        for m, g in sub.groupby("mint"):
            b = g[g.delta > 0].groupby("owner").delta.sum()
            s = (-g[g.delta < 0].groupby("owner").delta.sum())
            if len(b) == 0 or len(s) == 0:
                continue
            per.append((m, len(b), len(s), hhi(b), hhi(s)))
        if not per:
            return None
        arr = np.array([(p[1], p[2], p[3], p[4]) for p in per], dtype=float)
        return {
            "mints": len(per),
            "mean_buy_wallets": float(arr[:, 0].mean()),
            "mean_sell_wallets": float(arr[:, 1].mean()),
            "wallet_asymmetry": float((arr[:, 0] - arr[:, 1]).mean()),
            "hhi_buy_minus_sell": float(np.nanmean(arr[:, 2] - arr[:, 3])),
            "single_wallet_dump_share": float((arr[:, 1] == 1).mean()),
            "multi_wallet_accum_share": float((arr[:, 0] > 1).mean()),
        }

    obs = stat_for(members)
    # background: random same-size sets drawn from the non-member universe
    rng = np.random.default_rng(20260815)
    pool = [w for w in uni["wallets"] if w not in set(members)]
    bg = []
    for _ in range(60):
        pick = rng.choice(pool, size=min(len(members), len(pool)), replace=False)
        s = stat_for(list(pick))
        if s:
            bg.append(s)
    return obs, bg


# ===========================================================================
# CHANNEL 5 -- TIMING (CHEAP to evade -- corroborating only, never load-bearing)
# ===========================================================================

def channel5_timing(legs, anchor, cands, max_off: int = 4):
    """Slot-offset profile, its SYMMETRY, tx_index adjacency, and fee elevation.

    Three sub-signatures that the operator's original same-slot observation conflates:

      * mere same-slot co-occurrence -- what LAUNCH SNIPING looks like. The negative
        control sits at 42.7% here, so on its own this measures nothing.
      * offset SYMMETRY (d=-1 vs d=+1) -- a reactive COPY BOT is asymmetric by
        construction (it can only follow). Symmetry argues for a simultaneous fleet.
      * ATOMIC BUNDLE -- same slot AND near-consecutive tx_index AND elevated
        fee_lamports (a Jito tip). Reported separately from same-slot co-occurrence
        because PROGRAM.md 4 signal 4 requires excluding same-slot atomics: MEV is the
        dominant false positive.

    Null: ROT, a circular shift of the candidate's slot sequence within each mint,
    which preserves the candidate's own burst structure and the anchor's timing exactly.
    RESULT_copytrading is the precedent -- its naive rate-x-uniform null turned a flat
    0.98x into a 73x headline, so the naive number appears here only as the trap.
    """
    import numpy as np

    a = legs[legs.owner == anchor][["mint", "block_slot", "tx_index", "fee_lamports"]]
    # Precompute the anchor's slots per mint ONCE. The first version rebuilt this inside
    # the 50-rep ROT loop, which for the 17,908-mint control meant ~900k pandas groupby
    # iterations and never returned.
    a_slots = {m: g.block_slot.to_numpy() for m, g in a.groupby("mint")}
    out = {}
    rng = np.random.default_rng(20260815)
    for w in cands:
        b = legs[legs.owner == w][["mint", "block_slot", "tx_index", "fee_lamports"]]
        j = a.merge(b, on="mint", suffixes=("_a", "_b"))
        if j.empty:
            out[w] = None
            continue
        # only SHARED mints can ever contribute a co-occurrence, so the null runs on those
        b_slots = {m: g.block_slot.to_numpy()
                   for m, g in b[b.mint.isin(a_slots)].groupby("mint")}
        d = (j.block_slot_b - j.block_slot_a).to_numpy()
        near = j[np.abs(d) <= max_off]
        dn = d[np.abs(d) <= max_off]
        hist = {int(k): int((dn == k).sum()) for k in range(-max_off, max_off + 1)}
        same = near[near.block_slot_b == near.block_slot_a]
        dtx = np.abs((same.tx_index_b - same.tx_index_a).to_numpy()) if len(same) else np.array([])
        # symmetry: total at negative offsets vs positive offsets
        neg = sum(v for k, v in hist.items() if k < 0)
        pos = sum(v for k, v in hist.items() if k > 0)
        # ROT null: rotate the candidate's slots within each mint
        # ROT: shift the candidate's slots on each shared mint by a random offset drawn
        # from that mint's own observed slot span. A pure np.roll would be a no-op here --
        # the candidate usually has only 1-2 legs per mint, so rolling a length-1 array
        # returns it unchanged and the "null" would reproduce the observation exactly.
        # Shifting within the mint's active span is what actually destroys the alignment
        # while preserving how many times each wallet traded each mint.
        span = {m: (int(s.min()), int(s.max())) for m, s in a_slots.items()}
        rot_same = []
        for _ in range(50):
            c = 0
            for m, sb in b_slots.items():
                lo_m, hi_m = span[m]
                width = max(hi_m - lo_m, 1)
                shifted = lo_m + (sb - lo_m + rng.integers(0, width)) % width
                c += int(np.isin(shifted, a_slots[m]).sum())
            rot_same.append(c)
        obs_same = int(hist.get(0, 0))
        rot_mu = float(np.mean(rot_same)) if rot_same else float("nan")
        out[w] = {
            "pairs_within": len(dn),
            "share_same_slot": float(hist.get(0, 0) / max(len(dn), 1)),
            "hist": hist,
            "sym_neg": neg, "sym_pos": pos,
            "sym_ratio": float(min(neg, pos) / max(max(neg, pos), 1)),
            "same_slot_txidx_median": float(np.median(dtx)) if len(dtx) else float("nan"),
            "same_slot_txidx_adjacent_share": float((dtx <= 1).mean()) if len(dtx) else float("nan"),
            "same_slot_fee_median": float(same.fee_lamports_b.median()) if len(same) else float("nan"),
            "all_fee_median": float(b.fee_lamports.median()) if len(b) else float("nan"),
            "rot_expected_same_slot": rot_mu,
            "rot_ratio": float(obs_same / rot_mu) if rot_mu and rot_mu > 0 else float("nan"),
            "rot_p": float((np.array(rot_same) >= obs_same).sum() + 1) / 51.0,
        }
    return out


# ===========================================================================
# CHANNEL 6 -- SEQUENTIAL / RELAY (co-membership WITHOUT co-timing)
# ===========================================================================

def channel6_relay(legs, anchor, cands, gap_slots: int = 900):
    """The non-obvious shape: wallets that never overlap in time but whose union covers a
    mint's accumulation continuously, and whose SET recurs across mints.

    Anti-correlated timing is exactly as unlikely under independence as correlated timing,
    and it is what a coordinator evading a same-slot detector produces. So the statistic
    is: high co-membership (they appear on the same mints) with LOW temporal overlap
    (their active intervals tile rather than coincide).

    A relay pair looks like: recurrence high, overlap fraction near zero, and the union of
    intervals contiguous. A same-slot fleet looks like: recurrence high, overlap near one.
    """
    import numpy as np

    def spans(w):
        d = legs[legs.owner == w]
        return {m: (int(g.block_slot.min()), int(g.block_slot.max()))
                for m, g in d.groupby("mint")}

    A = spans(anchor)
    out = {}
    for w in cands:
        B = spans(w)
        shared = set(A) & set(B)
        if len(shared) < 10:
            out[w] = None
            continue
        ov, tile, cover = 0, 0, []
        for m in shared:
            a0, a1 = A[m]
            b0, b1 = B[m]
            inter = max(0, min(a1, b1) - max(a0, b0))
            union = max(a1, b1) - min(a0, b0)
            ov += 1 if inter > 0 else 0
            # tiling: disjoint but the gap between them is small relative to the union
            if inter == 0:
                g = max(b0 - a1, a0 - b1)
                if g <= gap_slots:
                    tile += 1
            cover.append(inter / union if union > 0 else 1.0)
        out[w] = {
            "shared_mints": len(shared),
            "temporal_overlap_share": ov / len(shared),
            "disjoint_but_contiguous_share": tile / len(shared),
            "mean_interval_iou": float(np.mean(cover)),
        }
    return out


# ===========================================================================
# CHANNEL 7 -- SUPPLY PARKING / TOKEN SPRAY (expensive to evade; drives concentration)
# ===========================================================================

def transfer_legs(df, min_infra_sigs: int = 50, two_sided: float = 0.15,
                  passthrough: float = 0.05):
    """Split legs into TRADES and TRANSFERS with no timing input whatsoever.

    THE FIRST VERSION OF THIS FUNCTION WAS WRONG AND THE WRONGNESS IS INSTRUCTIVE, so it
    is recorded here rather than quietly deleted. It identified ONE pool per mint (the
    owner on the most distinct signatures) and called every leg without that pool a
    transfer. On a pre-graduation pump.fun mint that is correct -- the bonding curve is on
    every swap, 477 signatures against 16 for the runner-up. On a GRADUATED mint it is a
    disaster: nosis has a 81,452-signature pool AND a 21,588-signature second pool AND a
    stack of routers, so 17% of its legs were misfiled as transfers, which built a
    686-wallet connected component and reported a +44.4pp bundle-adjusted top-10 delta.
    That number was an artifact of union-find on garbage edges -- exactly the giant
    component that svn_cotrading prints `giant_component_share` next to, and exactly the
    "reports a triumph" failure the repo keeps paying for.

    The corrected discriminator uses two independent tests, either of which makes a leg a
    trade:

      (a) THE wSOL TEST. If the transaction contains a wSOL leg, value was exchanged and
          this is a swap, whatever the routing looked like. 94,411 of nosis's 98,435
          signatures pass this, which is what exposed the bug.
      (b) THE INFRASTRUCTURE TEST. Pre-graduation pump.fun swaps hold NATIVE SOL, not
          wSOL, so (a) cannot see them. An infrastructure account is identified
          structurally, never by a hardcoded address list: it appears on many of the
          mint's signatures AND is two-sided (it both receives and sends) OR it is a pure
          pass-through (|net| / gross below `passthrough`). A retail holder is not on 50+
          signatures with 15%+ of its legs on each side; a curve, an AMM vault and a
          router all are.

    Only what survives BOTH is a transfer: a token balance moved between two ordinary
    owners while no value changed hands. That is the supply-parking mechanism -- buy
    through the curve on one wallet, spray the supply to N wallets, and naive top-N holder
    concentration reads healthy while one entity still controls the float.

    Returns (df_with_flags, infra_by_mint).
    """
    df = df.copy()
    per = df.groupby(["mint", "owner"]).agg(
        sigs=("signature", "nunique"),
        gross=("delta", lambda x: float(x.abs().sum())),
        net=("delta", "sum"),
        n_in=("delta", lambda x: int((x > 0).sum())),
        n_out=("delta", lambda x: int((x < 0).sum())),
    ).reset_index()
    per["legs"] = per.n_in + per.n_out
    per["side_bal"] = per[["n_in", "n_out"]].min(axis=1) / per.legs.clip(lower=1)
    per["pass"] = per.net.abs() / per.gross.clip(lower=1e-9)
    per["infra"] = (per.sigs >= min_infra_sigs) & (
        (per.side_bal >= two_sided) | (per["pass"] <= passthrough))
    infra = {m: set(g[g.infra]["owner"]) for m, g in per.groupby("mint")}

    key = set(zip(per[per.infra]["mint"], per[per.infra]["owner"]))
    df["is_pool"] = [(m, o) in key for m, o in zip(df["mint"], df["owner"])]

    # (a) wSOL present anywhere in the transaction -> a swap
    swap_sigs = set(df[df.mint == WSOL].signature)
    # (b) an infrastructure account moved on this mint in this transaction
    infra_moved = set(map(tuple, df[df.is_pool][["signature", "mint"]].drop_duplicates().values))

    df["kind"] = [
        "trade" if (s in swap_sigs or (s, m) in infra_moved) else "transfer"
        for s, m in zip(df["signature"], df["mint"])
    ]
    return df, infra


def concentration(balances, top_n: int = 10):
    """Naive top-N supply share and Gini over the address set AS PRESENTED."""
    import numpy as np

    v = np.sort(np.asarray([b for b in balances if b > 0], dtype=float))[::-1]
    if v.size == 0:
        return {"holders": 0, "top_n_share": float("nan"), "gini": float("nan")}
    tot = v.sum()
    s = np.sort(v)
    n = len(s)
    g = float((2 * np.arange(1, n + 1) @ s) / (n * s.sum()) - (n + 1) / n)
    return {"holders": n, "top_n_share": float(v[:top_n].sum() / tot), "gini": g,
            "total": float(tot)}


def _components(edges, nodes):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comp = {}
    for n in nodes:
        comp.setdefault(find(n), []).append(n)
    return comp


# ===========================================================================
# CHANNEL 8 -- WALLET ROTATION (the natural evasion of channel 1)
# ===========================================================================

def channel8_rotation(life, legs, window: int = 20_000, min_inherit: float = 0.30):
    """Retire a wallet, spin up a fresh one, continue. Defeats portfolio overlap between
    any FIXED pair, because the pair never coexists.

    A rotation link is: B's first slot lands within `window` slots of A's last slot, AND
    B's early portfolio inherits A's late portfolio. The inheritance test is what keeps
    this from firing on every pair of wallets that happen to be adjacent in time -- on a
    corpus with thousands of wallets, temporal adjacency alone is guaranteed.
    """

    early, late = {}, {}
    for w, g in legs.sort_values("block_slot").groupby("owner"):
        k = max(5, len(g) // 4)
        early[w] = set(g.head(k)["mint"])
        late[w] = set(g.tail(k)["mint"])
    L = life.set_index("owner")
    links = []
    for a in L.index:
        for b in L.index:
            if a == b:
                continue
            gap = int(L.at[b, "first_slot"] - L.at[a, "last_slot"])
            if not (0 <= gap <= window):
                continue
            la, eb = late.get(a, set()), early.get(b, set())
            if not la or not eb:
                continue
            inh = len(la & eb) / len(eb)
            if inh >= min_inherit:
                links.append({"a": a, "b": b, "gap_slots": gap, "inherit": float(inh),
                              "n_late_a": len(la), "n_early_b": len(eb)})
    return links


# ===========================================================================
# CHANNEL 9 -- WASH TRADING between coordinated wallets (moderate evasion cost)
# ===========================================================================

def channel9_wash(legs, members, max_slot_gap: int = 2, tol: float = 0.05):
    """A sells, B buys near-identical size on the same mint within a slot or two, so the
    ENTITY's net position is unchanged while volume and holder count are manufactured.

    Caveat inherited VERBATIM from RESULT_caller_wallets 6.1 because nothing here improves
    on it: "A market maker and a wash-trader leave the same trace and nothing here
    separates them." This is reported as a CEILING on manufactured volume, never as proof
    of wash trading.
    """
    import numpy as np

    sub = legs[legs.owner.isin(set(members))]
    matched, matched_vol, total_vol = 0, 0.0, float(np.abs(sub.delta).sum())
    for _m, g in sub.groupby("mint"):
        sells = g[g.delta < 0]
        buys = g[g.delta > 0]
        if sells.empty or buys.empty:
            continue
        bs = buys.block_slot.to_numpy()
        bd = buys.delta.to_numpy()
        bo = buys.owner.to_numpy()
        for s_slot, s_amt, s_own in zip(sells.block_slot, -sells.delta, sells.owner):
            k = (np.abs(bs - s_slot) <= max_slot_gap) & (bo != s_own) & \
                (np.abs(bd - s_amt) <= tol * np.maximum(bd, s_amt))
            if k.any():
                matched += 1
                matched_vol += float(s_amt)
    return {
        "sell_legs_with_internal_match": matched,
        "matched_volume": matched_vol,
        "total_volume": total_vol,
        "ceiling_manufactured_share": matched_vol / total_vol if total_vol else float("nan"),
        "caveat": "A market maker and a wash-trader leave the same trace and nothing "
                  "here separates them. This is a CEILING, not evidence.",
    }


def _label_of(w: str, uni) -> str:
    if w == uni["caller"]:
        return "CALLER"
    if w in set(uni["positive"]):
        return "POSITIVE"
    if w == uni["control"]:
        return "CONTROL"
    if w in set(uni["hard_negative"]):
        return "hard_neg"
    return "random"


def cmd_channel1(n_null: int = 200, burn: int = 8_000, thin: int = 400,
                 seed: int = 20260815) -> int:
    """Channel 1 against the anchor (the caller), for every universe wallet."""

    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    portfolios = _load_portfolios()
    anchor = uni["caller"]
    others = [w for w in sorted(portfolios) if w != anchor]
    pairs = [(anchor, w) for w in others]

    t0 = time.time()
    scores, n_corpus = channel1_portfolio(
        portfolios, pairs, n_null=n_null, burn=burn, thin=thin, seed=seed)
    for s in scores:
        s.label = _label_of(s.b, uni)
    print(f"  [{time.time() - t0:.0f}s, corpus mints N={n_corpus:,}]")

    rows = [{
        "wallet": s.b, "label": s.label, "n_wallet": s.n_b, "n_anchor": s.n_a,
        "inter": s.inter, "spec_wallet": s.spec_b, "spec_anchor": s.spec_a,
        "naive_ratio": s.naive_ratio, "pop_ratio": s.pop_ratio, "pop_z": s.pop_z,
        "cb_ratio": s.cb_ratio, "cb_p": s.cb_p,
    } for s in scores]
    import pandas as pd

    df = pd.DataFrame(rows).sort_values("spec_wallet", ascending=False)
    os.makedirs(OUT, exist_ok=True)
    df.to_parquet(os.path.join(OUT, "bundle_channel1.parquet"))

    print("\n=== CHANNEL 1: portfolio specificity vs the caller ===")
    print(f"{'label':9} {'wallet':12} {'|P|':>7} {'inter':>6} {'spec':>7} "
          f"{'NAIVE x':>9} {'POP x':>8} {'POP z':>8} {'CB x':>7} {'CB p':>7}")
    show = list(df[df.label.isin(["POSITIVE", "CONTROL"])].itertuples()) + \
        list(df[df.label == "hard_neg"].head(8).itertuples()) + \
        list(df[df.label == "random"].head(5).itertuples())
    for r in show:
        print(f"{r.label:9} {r.wallet[:10]:12} {r.n_wallet:>7,} {r.inter:>6,} "
              f"{r.spec_wallet:>6.1%} {r.naive_ratio:>9,.0f} {r.pop_ratio:>8.1f} "
              f"{r.pop_z:>8.1f} {r.cb_ratio:>7.1f} {r.cb_p:>7.4f}")

    print("\n  -- group medians --")
    g = df.groupby("label").agg(
        n=("wallet", "size"), spec=("spec_wallet", "median"),
        naive=("naive_ratio", "median"), pop=("pop_ratio", "median"),
        cb=("cb_ratio", "median"))
    print(g.to_string())
    print("\n  NAIVE x is the hypergeometric ratio and is reported ONLY to show the trap:")
    print(f"  it treats all {n_corpus:,} corpus mints as equally likely, so a launch sniper")
    print("  and a coordinated wallet both look astronomically significant under it.")
    return 0


def _fires(spec, pop_z, cb_ratio, cb_p, n):
    if n < MIN_PORTFOLIO:
        return "UNDECIDABLE(underpowered)"
    ok = (spec >= FIRE_SPEC and pop_z >= FIRE_POP_Z
          and cb_ratio >= FIRE_CB_RATIO and cb_p <= FIRE_CB_P)
    return "FIRE" if ok else "no"


# ===========================================================================
# BOTH CONTROLS, per PROGRAM.md 3.12: "a null control alone is worthless".
# ===========================================================================

def cmd_controls(seed: int = 20260815, n_null: int = 200) -> int:
    """A known-ZERO world and a known-EFFECT world, through the SAME channel-1 code.

    An estimator that detects nothing passes a false-positive test perfectly, so a green
    zero-control certifies a broken instrument exactly as readily as a working one. Both
    arms are therefore mandatory.
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    real = _load_portfolios()
    anchor = uni["caller"]
    all_mints = sorted({m for s in real.values() for m in s})
    weights, _, _ = _load_weights(all_mints)

    # ---- known-ZERO: resample every portfolio from coin popularity at its own degree.
    # No coordination exists by construction; anything that fires is the instrument.
    zero = {}
    p = weights / weights.sum()
    for w, s in real.items():
        k = min(len(s), len(all_mints))
        zero[w] = set(rng.choice(len(all_mints), size=k, replace=False, p=p))
    zero = {w: {all_mints[i] for i in s} for w, s in zero.items()}

    # ---- known-EFFECT: plant three wallets whose books are 95% inside the anchor's.
    effect = {w: set(s) for w, s in zero.items()}
    base = list(effect[anchor])
    planted = []
    for _i, w in enumerate(uni["positive"]):
        k = int(0.95 * len(real[w]))
        book = set(rng.choice(base, size=min(k, len(base)), replace=False))
        book |= set(rng.choice(len(all_mints), size=len(real[w]) - len(book),
                               replace=False, p=p).tolist())
        effect[w] = {m if isinstance(m, str) else all_mints[m] for m in book}
        planted.append(w)

    for name, pf in (("known-ZERO", zero), ("known-EFFECT", effect)):
        cands = uni["positive"] + [uni["control"]] + uni["hard_negative"][:10] + \
            uni["random_cotrader"][:20]
        cands = [c for c in cands if c in pf and c != anchor]
        sc, _ = channel1_portfolio(pf, [(anchor, c) for c in cands],
                                   n_null=n_null, burn=4_000, thin=200,
                                   seed=seed, verbose=False)
        fired = [s for s in sc
                 if _fires(s.spec_b, s.pop_z, s.cb_ratio, s.cb_p, s.n_b) == "FIRE"]
        print(f"\n=== CONTROL ARM: {name} ===")
        print(f"  candidates tested : {len(sc)}")
        print(f"  FIRED             : {len(fired)}  {[f.b[:8] for f in fired]}")
        if name == "known-ZERO":
            print(f"  -> false positive rate {len(fired) / max(len(sc), 1):.1%} "
                  f"(want 0%)")
        else:
            hit = sum(1 for f in fired if f.b in planted)
            print(f"  -> recovered {hit}/{len(planted)} planted wallets "
                  f"(want {len(planted)}/{len(planted)})")
    return 0


def cmd_channels(n_null: int = 200) -> int:
    """Run every channel on the known positive set and the control, side by side."""
    import numpy as np

    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    anchor = uni["caller"]
    legs = _legs()
    portfolios = _load_portfolios()
    report = {"trials": TRIALS}

    focus = uni["positive"] + [uni["control"]]

    print("=== CHANNEL 2: lifecycle coupling ===")
    c2, life = channel2_lifecycle(legs, uni)
    report["channel2"] = c2
    print(f"  corpus slots {c2['corpus_slot_lo']:,}..{c2['corpus_slot_hi']:,}")
    print(f"  left-censored wallets (existed before the corpus) : "
          f"{c2['left_censored_n']}/{c2['n_wallets']}")
    print(f"  right-censored (still active at corpus end)       : "
          f"{c2['right_censored_n']}/{c2['n_wallets']}")
    for w, s in c2["positive_first_slots"].items():
        print(f"  {w[:10]}  first_slot={s:,} on {c2['positive_first_mints'][w][:10]}  "
              f"last_slot={c2['positive_last_slots'][w]:,} on "
              f"{c2['positive_last_mints'][w][:10]}")
    print(f"  positive first-slot spread : {c2['positive_first_slot_spread']:,} slots")
    print(f"  positive last-slot  spread : {c2['positive_last_slot_spread']:,} slots")
    print(f"  all three share first mint : {c2['positive_shares_first_mint']}  "
          f"<-- if True this channel is CONFOUNDED with channel 1")
    print(f"  all three share last  mint : {c2['positive_shares_last_mint']}")
    print(f"  background pairs with an EXACT first-slot tie : "
          f"{c2.get('bg_pairs_exact_same_first_slot')}/{c2.get('bg_pairs')} "
          f"(p={c2.get('bg_p_exact_tie'):.4g})")

    print("\n=== CHANNEL 3: size choreography ===")
    self_cv, ratio, n_legs = channel3_size(legs, uni, anchor)
    report["channel3"] = {"self": {k: v for k, v in self_cv.items() if k in focus},
                          "ratio": {k: v for k, v in ratio.items() if k in focus},
                          "legs_ge_20_buys": n_legs}
    print(f"  (wallet,coin) legs with >=20 buys : {n_legs}")
    for w in focus:
        s = self_cv.get(w)
        r = ratio.get(w)
        print(f"  {w[:10]:11} self: {s if s else 'n/a'}")
        print(f"  {'':11} ratio-vs-anchor: {r if r else 'n/a (<20 shared coins with sizes)'}")
    rs = [v["log_ratio_sd"] for k, v in ratio.items() if k not in focus]
    if rs:
        print(f"  background log-ratio-sd median : {np.median(rs):.3f} (n={len(rs)})")

    print("\n=== CHANNEL 4: accumulate/dump asymmetry ===")
    obs, bg = channel4_asymmetry(legs, uni, uni["positive"])
    report["channel4"] = {"observed": obs, "background_n": len(bg)}
    if obs and bg:
        for k in ("mean_buy_wallets", "mean_sell_wallets", "wallet_asymmetry",
                  "hhi_buy_minus_sell", "single_wallet_dump_share",
                  "multi_wallet_accum_share"):
            b = np.array([x[k] for x in bg], dtype=float)
            p = (float((b >= obs[k]).sum()) + 1) / (len(b) + 1)
            print(f"  {k:28} obs={obs[k]:8.3f}  bg={np.nanmedian(b):8.3f}  p={p:.3f}")
            report["channel4"].setdefault("p", {})[k] = p

    print("\n=== CHANNEL 5: timing (CHEAP to evade -- corroborating only) ===")
    c5 = channel5_timing(legs, anchor, focus)
    report["channel5"] = c5
    print(f"  {'wallet':11} {'pairs':>6} {'d=0':>7} {'sym':>6} {'txidx':>7} {'adj':>6} "
          f"{'fee0':>10} {'feeAll':>10} {'ROTx':>6} {'ROTp':>6}")
    for w in focus:
        v = c5.get(w)
        if not v:
            continue
        print(f"  {w[:10]:11} {v['pairs_within']:>6,} {v['share_same_slot']:>6.1%} "
              f"{v['sym_ratio']:>6.2f} {v['same_slot_txidx_median']:>7.1f} "
              f"{v['same_slot_txidx_adjacent_share']:>6.1%} "
              f"{v['same_slot_fee_median']:>10,.0f} {v['all_fee_median']:>10,.0f} "
              f"{v['rot_ratio']:>6.2f} {v['rot_p']:>6.3f}")

    print("\n=== CHANNEL 6: sequential / relay ===")
    c6 = channel6_relay(legs, anchor, focus)
    report["channel6"] = c6
    for w in focus:
        print(f"  {w[:10]:11} {c6.get(w)}")

    print("\n=== CHANNEL 7: supply parking / token spray (on the candidate set) ===")
    flagged, _pools = transfer_legs(_legs(universe_only=False))
    mine = flagged[flagged.owner.isin(set(uni["positive"]) | {anchor, uni["control"]})]
    c7 = {}
    for w, g in mine.groupby("owner"):
        t = g[g.kind == "transfer"]
        c7[w] = {"legs": len(g), "transfer_legs": len(t),
                 "transfer_share": float(len(t) / max(len(g), 1)),
                 "outbound_transfers": int((t.delta < 0).sum()),
                 "inbound_transfers": int((t.delta > 0).sum()),
                 "distinct_transfer_mints": int(t.mint.nunique())}
    report["channel7"] = c7
    for w in [anchor] + focus:
        print(f"  {w[:10]:11} {c7.get(w)}")

    print("\n=== CHANNEL 8: wallet rotation ===")
    c8 = channel8_rotation(life, legs)
    report["channel8"] = c8[:50]
    print(f"  rotation links found : {len(c8)}")
    for l in sorted(c8, key=lambda x: -x["inherit"])[:8]:
        print(f"    {l['a'][:9]} -> {l['b'][:9]}  gap={l['gap_slots']:,} slots  "
              f"inherit={l['inherit']:.1%}")

    print("\n=== CHANNEL 9: wash trading (CEILING only) ===")
    c9 = channel9_wash(legs, uni["positive"] + [anchor])
    report["channel9"] = c9
    print(f"  sell legs with an internal size-matched counterparty : "
          f"{c9['sell_legs_with_internal_match']}")
    print(f"  ceiling on manufactured share of the set's volume    : "
          f"{c9['ceiling_manufactured_share']:.2%}")
    print(f"  {c9['caveat']}")

    with open(os.path.join(OUT, "bundle_channels.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"\nwrote {os.path.join(OUT, 'bundle_channels.json')}")
    return 0


def cmd_validate() -> int:
    """THE GATE. One threshold set, applied unchanged to every arm."""
    import pandas as pd

    uni = json.load(open(os.path.join(CACHE, "universe.json")))
    df = pd.read_parquet(os.path.join(OUT, "bundle_channel1.parquet"))
    df["verdict"] = [_fires(r.spec_wallet, r.pop_z, r.cb_ratio, r.cb_p, r.n_wallet)
                     for r in df.itertuples()]

    print("=== VALIDATION GATE (channel 1) ===")
    print(f"thresholds, declared once: spec>={FIRE_SPEC}, pop_z>={FIRE_POP_Z}, "
          f"cb_ratio>={FIRE_CB_RATIO}, cb_p<={FIRE_CB_P}, |P|>={MIN_PORTFOLIO}")
    for lab in ("POSITIVE", "CONTROL", "hard_neg", "random"):
        sub = df[df.label == lab]
        f = (sub.verdict == "FIRE").sum()
        u = (sub.verdict.str.startswith("UNDECIDABLE")).sum()
        print(f"  {lab:9} n={len(sub):>4}  FIRE={f:>3}  no={len(sub) - f - u:>3}  "
              f"UNDECIDABLE={u:>3}")
    print("\n  every wallet that fired:")
    for r in df[df.verdict == "FIRE"].sort_values("spec_wallet", ascending=False).itertuples():
        print(f"    {r.label:9} {r.wallet}  |P|={r.n_wallet:>6,} spec={r.spec_wallet:>6.1%} "
              f"pop_z={r.pop_z:>6.1f} cb={r.cb_ratio:>5.1f} p={r.cb_p:.4f}")
    df.to_parquet(os.path.join(OUT, "bundle_gate.parquet"))
    return 0


def cmd_matched() -> int:
    """PROGRAM.md 3.13: two nulls, compared AT MATCHED DENSITY, hand only the intersection.

    "Validated-link density varies by an order of magnitude across null models at the same
    p-value, so a single null is a knob, not a test." So the two nulls are compared by
    taking the SAME NUMBER of top-ranked wallets from each and measuring how much they
    agree -- not by comparing p-values, which are not commensurable across nulls.
    """
    import pandas as pd

    df = pd.read_parquet(os.path.join(OUT, "bundle_channel1.parquet"))
    df = df[df.n_wallet >= MIN_PORTFOLIO]
    print("=== TWO NULLS AT MATCHED DENSITY (channel 1) ===")
    print(f"  eligible wallets (|P| >= {MIN_PORTFOLIO}): {len(df)}")
    print(f"  {'k':>4} {'POP-only':>9} {'CB-only':>8} {'both':>6} {'Jaccard':>8}  intersection")
    for k in (3, 5, 10, 20):
        pop = set(df.nlargest(k, "pop_z").wallet)
        cb = set(df.nlargest(k, "cb_ratio").wallet)
        inter = pop & cb
        jac = len(inter) / max(len(pop | cb), 1)
        print(f"  {k:>4} {len(pop - cb):>9} {len(cb - pop):>8} {len(inter):>6} {jac:>8.3f}  "
              f"{sorted(w[:8] for w in inter)}")
    print("\n  Only the intersection is handed downstream. Where the two nulls disagree,")
    print("  the disagreement IS the finding -- it is the size of the knob.")
    return 0


def cmd_operator(top_n: int = 10) -> int:
    """The payoff: were the operator's coins bundled, and what is the bundle-adjusted
    holder concentration?

    PROGRAM.md 1.1: the signal is the BUNDLE-ADJUSTED MINUS NAIVE top-10 delta
    (+24pp high-risk vs +6pp low-risk), not raw top-10 share -- which PROGRAM.md 4 lists
    under Known anti-signals. This produces the input that would let
    shitcoims_intelligence/numerics.py:29 be bundle-corrected; it does NOT edit that file.
    """

    con = _duck(threads=2, mem="3GB")
    raw = con.execute(f"""
        SELECT signature, block_slot, tx_index, fee_lamports, owner, mint, delta, post_amt
        FROM read_parquet('{os.path.join(CACHE, 'operator_legs', '*.parquet')}')
        WHERE delta <> 0
    """).df()
    flagged, pools = transfer_legs(raw)
    out = {}
    print("=== OPERATOR COINS ===")
    for name, mint in OPERATOR_COINS.items():
        d = flagged[flagged.mint == mint]
        launch, cov = COIN_LAUNCH[name]
        print(f"\n--- {name} ({mint[:12]}...)  launched {launch}")
        print(f"    corpus coverage: {cov}")
        if d.empty:
            print("    NO LEGS IN CORPUS")
            out[name] = {"coverage": cov, "legs": 0}
            continue
        pool = sorted(pools.get(mint, set()))
        holders = d[~d.is_pool]
        # balance = last observed post_amt per owner
        bal = (holders.sort_values(["block_slot", "tx_index"])
               .groupby("owner").post_amt.last())
        bal = bal[bal > 0]
        naive = concentration(bal.values, top_n)

        # transfer graph -> components -> collapse
        tr = d[(d.kind == "transfer") & (~d.is_pool)]
        raw_edges = []
        for _sig, g in tr.groupby("signature"):
            src = g[g.delta < 0].owner.tolist()
            dst = g[g.delta > 0].owner.tolist()
            for a in src:
                for b in dst:
                    if a != b:
                        raw_edges.append((a, b))

        # HUB EXCLUSION, structural -- by fan-out degree, never by a curated address list,
        # following entity_resolution.py's `hub_degree`. WHY THIS IS NOT OPTIONAL: nosis's
        # transfer graph is a star on 2ZijVFYr..., which made ZERO curve buys and 703
        # outbound transfers to 168 addresses. 136 of those 168 then BOUGHT on the curve
        # and 133 SOLD -- they trade independently, so they are a distributor's audience,
        # not one entity's wallets. Union-find across a hub merges independent traders and
        # manufactured a +37.2pp "bundle-adjusted" delta out of an airdrop. Supply parking
        # and a faucet look identical edge-by-edge; only fan-out separates them.
        fan = {}
        for a, b in raw_edges:
            fan.setdefault(a, set()).add(b)
            fan.setdefault(b, set()).add(a)
        hubs = {n for n, v in fan.items() if len(v) >= HUB_DEGREE}
        edges = [(a, b) for a, b in raw_edges if a not in hubs and b not in hubs]
        comp = _components(edges, list(bal.index))
        collapsed = {}
        for root, members in comp.items():
            collapsed[root] = float(sum(bal.get(m, 0.0) for m in members))
        adj = concentration(list(collapsed.values()), top_n)
        multi = {r: m for r, m in comp.items() if len(m) > 1}

        # GIANT-COMPONENT TRIPWIRE. svn_cotrading prints giant_component_share beside every
        # clustering number because union-find on this kind of graph collapses to one
        # component and reports a triumph. The first run of this study did exactly that
        # (a 686-wallet component off misclassified swap legs), so the diagnostic is
        # printed unconditionally and a star-shaped component is called out as a HUB --
        # one address spraying to N wallets is a distributor, and it is only one entity
        # if the recipients are actually controlled, which this corpus cannot confirm.
        biggest = set(max(comp.values(), key=len)) if comp else set()
        nbr = {}
        for a, b in edges:
            if a in biggest and b in biggest:
                nbr.setdefault(a, set()).add(b)
                nbr.setdefault(b, set()).add(a)
        hub_share = (max((len(v) for v in nbr.values()), default=0)
                     / max(len(biggest) - 1, 1)) if len(biggest) > 1 else 0.0
        hub_node = max(nbr, key=lambda k: len(nbr[k])) if nbr else None

        rec = {
            "coverage": cov, "launch": launch, "legs": len(d),
            "pool": pool,
            "giant_component_share": len(biggest) / max(len(bal), 1),
            "giant_component_hub_share": float(hub_share),
            "giant_component_hub": hub_node,
            "giant_component_size": len(biggest),
            "giant_component_supply_share": float(
                sum(bal.get(m, 0.0) for m in biggest) / max(bal.sum(), 1e-9)),
            "holders_naive": naive["holders"], "holders_collapsed": adj["holders"],
            "naive_top_n": naive["top_n_share"], "adjusted_top_n": adj["top_n_share"],
            "delta_pp": (adj["top_n_share"] - naive["top_n_share"]) * 100,
            "naive_gini": naive["gini"], "adjusted_gini": adj["gini"],
            "transfer_legs": len(tr), "transfer_edges": len(edges),
            "transfer_edges_before_hub_exclusion": len(raw_edges),
            "hubs_excluded": sorted(hubs),
            "multi_wallet_components": len(multi),
            "largest_component": max((len(m) for m in comp.values()), default=0),
            "wallets_in_multi_components": int(sum(len(m) for m in multi.values())),
        }
        out[name] = rec
        print(f"    legs={rec['legs']:,}  transfer legs={rec['transfer_legs']:,}  "
              f"transfer edges={len(raw_edges):,} -> {len(edges):,} after excluding "
              f"{len(hubs)} hub(s) with fan-out >= {HUB_DEGREE}")
        print(f"    holders  naive={naive['holders']:,} -> collapsed={adj['holders']:,}  "
              f"({len(multi)} multi-wallet components, largest={rec['largest_component']})")
        print(f"    top-{top_n} share   naive={naive['top_n_share']:.1%} -> "
              f"bundle-adjusted={adj['top_n_share']:.1%}   "
              f"DELTA = {rec['delta_pp']:+.1f}pp")
        print(f"    gini            naive={naive['gini']:.4f} -> "
              f"bundle-adjusted={adj['gini']:.4f}")
        print(f"    TRIPWIRE  giant component = {len(biggest)} wallets "
              f"({rec['giant_component_share']:.1%} of holders, "
              f"{rec['giant_component_supply_share']:.1%} of supply); its top node "
              f"reaches {hub_share:.0%} of it"
              f"{'   <-- STAR/HUB: a distributor, NOT proof of one entity' if (hub_share > 0.5 and len(biggest) >= 10) else ''}")
        if hub_node and len(biggest) >= 10:
            print(f"              hub = {hub_node}")

        # launch-window bundling, only where the corpus can see it
        if cov.startswith("IN CORPUS"):
            first = int(d.block_slot.min())
            win = d[(d.block_slot <= first + 30) & (~d.is_pool) & (d.delta > 0)]
            per_slot = win.groupby("block_slot").owner.nunique()
            print(f"    LAUNCH: first slot {first:,}; buyers in first 30 slots = "
                  f"{win.owner.nunique()}; busiest slot has {int(per_slot.max())} "
                  f"distinct buyers")
            rec["launch_first_slot"] = first
            rec["launch_buyers_30slots"] = int(win.owner.nunique())
            rec["launch_max_buyers_one_slot"] = int(per_slot.max())
        else:
            print("    LAUNCH: NOT ANSWERABLE -- launch predates the corpus and the only "
                  "tape that reaches back (state/bulk_history) has no owner column.")

    with open(os.path.join(OUT, "bundle_operator.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(f"\nwrote {os.path.join(OUT, 'bundle_operator.json')}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    kw = {}
    for arg in argv[2:]:
        if arg.startswith("--"):
            k, _, v = arg[2:].partition("=")
            kw[k.replace("-", "_")] = int(v) if v.isdigit() else v
    fn = globals().get(f"cmd_{cmd}")
    if fn is None:
        print(f"unknown command {cmd}")
        return 2
    return fn(**kw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
