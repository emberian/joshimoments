#!/usr/bin/env python3
"""Seasonality: an OPERATIONS CALENDAR, not a trading rule.

THE OPERATOR'S FRAMING, WHICH IS THE RIGHT ONE
-----------------------------------------------
"any hypothesis simple enough to phrase likely isn't predictive. we should still look
anyway the best we can."

Both halves are load-bearing. A diurnal pattern in a market that anyone can see is not a
trading edge -- if pump.fun coins were reliably cheap at 06:00 UTC, they would not be. But
the same pattern is still worth a great deal for OPERATIONS, because operations are not
adversarial: nobody arbitrages away the fact that the chain is congested at a particular
hour, or that fee income accrues faster in one part of the day, or that our own harvest
windows are worth staffing at one time and not another. So the deliverable here is a
calendar with confidence intervals and an explicit falsifier per row, and no rule that
says buy.

WHAT IS MEASURED, AND OUT OF WHAT
----------------------------------
* ``state/bulk_pump/daily/`` -- 106,639,238 transactions, **ten UTC days** (2026-08-05 ..
  2026-08-14), every pump.fun coin. Chain activity, launch rate, fee level, compute load,
  and the wiggle cohort.
* ``state/bulk_history/parquet/`` -- our own 9 pools, **48 days** (2026-06-27 .. 08-13),
  including the 922,432 failures. Landing rate, depth, and the only series long enough to
  say anything at all about a WEEK.
* ``.cache/position_history/ledger.json`` -- the operator's claim receipts, used to
  correct the brief rather than to answer it (see §5).

TEN DAYS. SAY IT OUT LOUD, EVERY TIME.
---------------------------------------
Ten days is 1.43 weeks. **No weekly claim from the corpus is inference; it is description
of two Saturdays.** Only DREGG/SOL, at 48 days, gets a weekly test at all, and 6.9 weeks
of one pool is still weak. Every table below states its unit count.

THE NULL, AND WHY THE OBVIOUS ONE IS WRONG
-------------------------------------------
The tempting null is a circular rotation of the whole series. It is **useless here**: a
genuine 24 h cycle survives rotation with its amplitude intact and only its phase moved,
so the null would reproduce the effect and nothing could ever be rejected.

The null this study uses instead **rotates each day independently by its own random
offset**. Within-day autocorrelation and each day's own shape survive; what is destroyed is
the ALIGNMENT of the phase across days, which is exactly and only what "the pattern is
locked to the clock" asserts. The statistic is the dispersion of the day-demeaned
hour-of-day profile. Demeaning within day matters: without it, a single busy day tilts the
profile and the ten-day trend is read as a time-of-day effect.

Confidence intervals resample DAYS (or, for the weekly panel, WEEKS), because a day is the
unit that repeats. Hours inside a day are not independent and treating them as such would
shrink every interval by a factor of five for free.

Multiplicity: eleven diurnal hypotheses are tested, Benjamini-Yekutieli at q = 0.10.

AND THE ANSWER, SO THE MODULE STATES ITS OWN RESULT
----------------------------------------------------
Six of eleven survive, and the split is the finding: **every survivor measures how MUCH is
happening (volume, launches, fees, compute) and every null measures how GOOD the opportunity
is (wiggle quality, spread, landing odds)** -- the latter on 47 days of data against the
former's 10. The operator's prior, that a hypothesis simple enough to phrase is unlikely to be
predictive, is what the data says.

Reproduce::

    uv run --group research python studies/seasonality.py all

Sections: ``calibrate chain launch wiggle_pools landing fees calendar``. ``wiggle`` -- the
sampled corpus cohort -- is NOT in ``all``: it is a ten-day corpus fold and this machine is
shared, so run it alone or on persvati. Heavy intermediates cache to
``studies/data/seasonality/``, per day and atomically, so a kill costs one day.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Final, Sequence

REPO: Final[Path] = Path(__file__).resolve().parent.parent

# ``python studies/seasonality.py`` puts studies/ on sys.path, not the repo root, so
# ``from studies.callout_volatility import ...`` -- the whole point of reusing that module's
# zigzag and friction machinery rather than restating it -- fails with ModuleNotFoundError
# forty minutes into a run, after the expensive part. Fixed here rather than by telling
# everyone to use ``python -m``.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
BULK: Final[Path] = REPO / "state" / "bulk_pump" / "daily"
HIST: Final[Path] = REPO / "state" / "bulk_history" / "parquet"
DATA: Final[Path] = REPO / "studies" / "data" / "seasonality"

WSOL: Final[str] = "So11111111111111111111111111111111111111112"
HOUR: Final[int] = 3600
DAY: Final[int] = 86_400

# The wiggle cohort. Sampled, and the sample is the whole reason this section is possible
# at all: the corpus is 106.6M rows and the previous attempt to materialise every mint's
# price path took 20 GB of RSS and was killed. A random sample of mints costs nothing in
# validity -- hour-of-day is estimated across mints, not within one -- and the inference
# is clustered on the mint anyway.
COHORT_MINTS: Final[int] = 3000
COHORT_MIN_PRINTS: Final[int] = 200
CLIP_LAMPORTS: Final[int] = 100_000_000

NULL_DRAWS: Final[int] = 2000
FDR_Q: Final[float] = 0.10

# RESOURCE CEILING, and it is not a suggestion. This laptop has run four corpus folds at
# once and the operator had to kill a 23 GB python to get it back. Rules followed here:
# the corpus is NEVER loaded into pandas whole -- every pass over it is a DuckDB aggregate
# that returns hours or mints, never rows -- each connection is capped, and the sections
# are designed to run one at a time.
MEM_LIMIT: Final[str] = "6GB"
CORPUS_MEM: Final[str] = "4GB"  # see _duckdb: measured, not guessed
CORPUS_THREADS: Final[int] = 1


def _duckdb(*, corpus: bool = False) -> Any:
    """A capped connection. ``corpus=True`` for anything that UNNESTs the 106.6M-row tape.

    The corpus settings are MEASURED, not guessed. Folding one day's mint census:

        threads=6, memory_limit=6GB  ->  peak RSS 8.6 GB    killed, over the ceiling
        threads=2, memory_limit=3GB  ->  peak RSS 4.7 GB    OK on a median day, then
                                        OutOfMemoryException on 2026-08-10, the
                                        largest (12.08M rows)
        threads=1, memory_limit=4GB  ->  peak RSS 5.6 GB standalone, 111 s, OK on that
                                        same day -- but 6.4 GB inside the full run,
                                        because the interpreter and the accumulated
                                        day partials sit on top of DuckDB's budget
        threads=1, memory_limit=3500MB -> WORSE ON BOTH AXES, and this is the
                                        counter-intuitive one: dropping the budget by
                                        500 MB fell off a spill cliff. Days that took
                                        ~2 min took >20, /tmp grew past 5.6 GB, and
                                        peak RSS went UP to 6.7 GB, because the
                                        re-read traffic costs more memory than the
                                        buffer it was meant to save. Tightening a
                                        memory limit is not monotonically safer.

    4GB is the setting shipped. It is the only one measured to COMPLETE the largest day.

    The blowup is UNNEST, not the aggregate: expanding a 3-GB list column runs one buffer
    per thread, so THREADS is the memory knob here and ``memory_limit`` alone will not save
    you -- it governs DuckDB's buffer manager and not the operator's own expansion, which is
    how a 6 GB limit produced 8.6 GB of resident set. Note both failure modes are real:
    too GENEROUS a limit blows the machine ceiling, too TIGHT a one raises
    OutOfMemoryException inside DuckDB. The settings above are the measured middle, and
    they are calibrated on the LARGEST day rather than a typical one.
    """
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - declared in the research group
        raise SystemExit("duckdb is required: run with `uv run --group research`") from exc
    con = duckdb.connect()
    con.execute(f"SET threads TO {CORPUS_THREADS if corpus else 6}")
    con.execute(f"SET memory_limit='{CORPUS_MEM if corpus else MEM_LIMIT}'")
    con.execute("SET temp_directory='/tmp/duckdb-seasonality'")  # spill, do not swap the Mac
    con.execute("SET preserve_insertion_order=false")
    with contextlib.suppress(Exception):  # pragma: no cover
        con.execute("PRAGMA disable_progress_bar")
    return con


def bulk_files() -> list[Path]:
    return sorted(BULK.glob("*.parquet"))


def per_day(name: str, sql: Callable[[str], str], *, echo: Callable[[str], None] = print) -> Any:
    """Run one aggregate per corpus DAY and concatenate the small results. Resumable.

    This exists because the whole-corpus version of the same query reached **14.3 GB of RSS
    despite `SET memory_limit='6GB'`** and had to be killed. DuckDB's limit governs its own
    buffer manager; it does not govern the UNNEST expansion of a 3-GB list column, nor the
    Arrow->pandas materialisation on the way out. The only reliable ceiling is to never ask
    it for the whole corpus at once. One day is ~10.7M rows and ~36M legs, which folds in
    seconds inside the cap, and each day's partial is cached so a kill costs one day.
    """
    import pandas as pd

    part_dir = DATA / "parts" / name
    part_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for path in bulk_files():
        part = part_dir / (path.stem + ".parquet")
        # A part is only trusted if it is non-empty. Killing a fold mid-COPY leaves a
        # zero-byte file behind, and an existence check alone then hands the next run a
        # corrupt cache entry that fails in pyarrow with a message about a <Buffer>, three
        # frames deep, nowhere near the actual cause. Write to a temp name and rename:
        # rename is atomic, so a part is either absent or complete and never in between.
        if not part.exists() or part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            tmp = part.with_suffix(".parquet.partial")
            tmp.unlink(missing_ok=True)
            con = _duckdb(corpus=True)
            try:
                con.execute(f"COPY ({sql(str(path))}) TO '{tmp}' (FORMAT PARQUET)")
            finally:
                con.close()
            tmp.rename(part)
            echo(f"     {name}: folded {path.stem}")
        frames.append(pd.read_parquet(part))
    return pd.concat(frames, ignore_index=True)


def by_fdr(pvalues: Sequence[float], q: float = FDR_Q) -> list[bool]:
    """Benjamini-Yekutieli step-up; holds under arbitrary dependence, which these have."""
    m = len(pvalues)
    if m == 0:
        return []
    c_m = sum(1.0 / i for i in range(1, m + 1))
    order = sorted(range(m), key=lambda i: pvalues[i])
    keep = [False] * m
    cut = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= (rank / (m * c_m)) * q:
            cut = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= cut:
            keep[idx] = True
    return keep


# ======================================================================= the diurnal test


class Diurnal:
    """A day x 24 matrix, its day-demeaned hour-of-day profile, and the phase-scramble null.

    ``matrix`` is (n_days, 24) of whatever quantity is being profiled. Missing hours are
    NaN and are carried as NaN rather than zero: an hour with no observation is not an hour
    with no activity, and the two have opposite signs in every metric here.
    """

    def __init__(self, matrix: Any, *, name: str, unit: str = "", relative: bool = True) -> None:
        import numpy as np

        self.name = name
        self.unit = unit
        self.matrix = np.asarray(matrix, dtype=float)
        self.relative = relative
        self.n_days = int(self.matrix.shape[0])
        with np.errstate(invalid="ignore"):
            day_mean = np.nanmean(self.matrix, axis=1, keepdims=True)
            if relative:
                # Ratio to the day's own level: a metric that doubles in absolute size
                # over the window would otherwise let its late days dominate the profile.
                self.dev = self.matrix / np.where(day_mean == 0, np.nan, day_mean)
            else:
                self.dev = self.matrix - day_mean
        self.profile = np.nanmean(self.dev, axis=0)

    @staticmethod
    def _stat(profile: Any) -> float:
        import numpy as np

        return float(np.nanstd(profile))

    def observed(self) -> float:
        return self._stat(self.profile)

    def null_p(self, *, draws: int = NULL_DRAWS, seed: int = 17) -> float:
        """Each day independently re-phased. Destroys clock alignment, keeps day shape."""
        import numpy as np

        rng = np.random.default_rng(seed)
        obs = self.observed()
        hits = 0
        for _ in range(draws):
            rolled = np.empty_like(self.dev)
            for d in range(self.n_days):
                rolled[d] = np.roll(self.dev[d], int(rng.integers(0, 24)))
            if self._stat(np.nanmean(rolled, axis=0)) >= obs:
                hits += 1
        return (hits + 1) / (draws + 1)

    def ci(self, *, draws: int = 2000, seed: int = 23) -> tuple[Any, Any]:
        """Percentile bootstrap over DAYS -- the unit that repeats."""
        import numpy as np

        rng = np.random.default_rng(seed)
        boots = np.empty((draws, 24))
        for b in range(draws):
            idx = rng.integers(0, self.n_days, self.n_days)
            boots[b] = np.nanmean(self.dev[idx], axis=0)
        return np.nanquantile(boots, 0.025, axis=0), np.nanquantile(boots, 0.975, axis=0)

    def peak(self) -> tuple[int, int]:
        import numpy as np

        return int(np.nanargmax(self.profile)), int(np.nanargmin(self.profile))

    def peak_ci(self, *, draws: int = 2000, seed: int = 29) -> tuple[float, float]:
        """How reproducible is the peak hour across resampled days? Reported as a SPREAD.

        A peak-hour "confidence interval" on circular data is not a real interval, so what
        is printed is the interquartile spread of the bootstrap peak, in hours, on the
        circle. Small = the peak is a fact; large = the profile is flat and the argmax is
        picking noise.
        """
        import numpy as np

        rng = np.random.default_rng(seed)
        peaks = []
        for _ in range(draws):
            idx = rng.integers(0, self.n_days, self.n_days)
            prof = np.nanmean(self.dev[idx], axis=0)
            peaks.append(int(np.nanargmax(prof)))
        base = int(np.nanargmax(self.profile))
        offs = [((p - base + 12) % 24) - 12 for p in peaks]
        return float(np.quantile(offs, 0.25)), float(np.quantile(offs, 0.75))

    def render(self, echo: Callable[[str], None] = print, *, width: int = 46) -> None:
        import numpy as np

        lo, hi = self.ci()
        centre = 1.0 if self.relative else 0.0
        vals = self.profile
        span = float(np.nanmax(np.abs(vals - centre))) or 1.0
        echo(f"   {self.name} -- {self.n_days} days, day-{'normalised' if self.relative else 'demeaned'}")
        for h in range(24):
            v = vals[h]
            if not np.isfinite(v):
                echo(f"     {h:02d}h  (no data)")
                continue
            n = round(abs(v - centre) / span * width)
            bar = ("+" if v >= centre else "-") * max(n, 1)
            sig = "*" if (lo[h] > centre or hi[h] < centre) else " "
            echo(f"     {h:02d}h {v:8.3f} {sig} {bar}")


def calibrate(*, sims: int = 60, draws: int = 200, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Does the phase-scramble null have the right size AND the right blind spot?

    A null is worth nothing until you have shown it rejects what it should and tolerates what
    it should. Three synthetic worlds, each run through the identical machinery:

    * ``flat``   -- i.i.d. noise. Nothing to find; rejection rate should be ~alpha.
    * ``ar``     -- strongly autocorrelated WITHIN each day, phases independent ACROSS days.
                    This is the confound the study exists to survive: a metric can be smooth
                    and bursty without being locked to the clock, and a naive null would call
                    that seasonality. Rejection rate should still be ~alpha.
    * ``cycle``  -- a true 24 h sinusoid at amplitude 0.15, which is the amplitude actually
                    observed in section 1. Rejection rate should be ~1.
    """
    import numpy as np

    echo("")
    echo("=" * 100)
    echo("0. NULL CALIBRATION -- size against autocorrelation, power against a real cycle")
    echo("=" * 100)
    rng = np.random.default_rng(0)
    out: dict[str, Any] = {}
    for kind, n_days in (("flat", 10), ("ar", 10), ("cycle", 10), ("cycle", 48)):
        ps = []
        for _ in range(sims):
            if kind == "flat":
                m = rng.normal(1, 0.2, (n_days, 24))
            elif kind == "ar":
                m = np.empty((n_days, 24))
                for d in range(n_days):
                    x = np.zeros(24)
                    e = rng.normal(0, 0.3, 24)
                    for i in range(1, 24):
                        x[i] = 0.85 * x[i - 1] + e[i]
                    m[d] = 1 + x
            else:
                h = np.arange(24)
                m = 1 + 0.15 * np.sin(2 * np.pi * h / 24)[None, :] + rng.normal(0, 0.2, (n_days, 24))
            ps.append(Diurnal(m, name=kind).null_p(draws=draws))
        arr = np.asarray(ps)
        rate = float((arr < 0.05).mean())
        out[f"{kind}_{n_days}"] = dict(reject_at_05=rate, median_p=float(np.median(arr)))
        echo(
            f"   {kind:<6} {n_days:>3} days   rejects at 0.05: {100 * rate:>5.1f}%   "
            f"median p {np.median(arr):.3f}"
        )
    echo("")
    echo("   The `ar` row is the one that matters: within-day autocorrelation as strong as")
    echo("   rho = 0.85 does NOT get called seasonality. Size is mildly liberal (~8% at a")
    echo("   nominal 5%, within ~1 SE of nominal at 60 simulations), which is one more reason")
    echo("   the calendar is reported after BY-FDR rather than test by test.")
    return out


def hour_matrix(pairs: Sequence[tuple[int, float]]) -> Any:
    """[(unix_hour, value)] -> (n_days, 24), NaN where an hour is missing."""
    import numpy as np

    if not pairs:
        return np.zeros((0, 24))
    by_hour = {int(h): float(v) for h, v in pairs}
    hours = sorted(by_hour)
    d0 = hours[0] // 24
    d1 = hours[-1] // 24
    mat = np.full((d1 - d0 + 1, 24), np.nan)
    for h, v in by_hour.items():
        mat[h // 24 - d0, h % 24] = v
    # A day missing more than a third of its hours cannot contribute a shape.
    keep = np.isfinite(mat).sum(axis=1) >= 16
    return mat[keep]


# ============================================================================ 1. the chain


def chain(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Chain-wide activity, congestion price and compute load, hour by hour."""
    import numpy as np

    echo("")
    echo("=" * 100)
    echo("1. THE CHAIN -- activity, fee level and compute load across the day")
    echo("=" * 100)
    cache = DATA / "chain_hourly.parquet"
    if cache.exists():
        import pandas as pd

        frame = pd.read_parquet(cache)
    else:
        frame = per_day(
            "chain",
            lambda f: f"""
            SELECT block_time // {HOUR} AS h,
                   COUNT(*) AS n_tx,
                   SUM(TRY_CAST(fee_lamports AS BIGINT)) AS fee_sum,
                   approx_quantile(TRY_CAST(fee_lamports AS BIGINT), 0.5) AS fee_med,
                   approx_quantile(TRY_CAST(fee_lamports AS BIGINT), 0.9) AS fee_p90,
                   SUM(TRY_CAST(compute_units AS BIGINT)) AS cu_sum
            FROM read_parquet('{f}')
            GROUP BY 1 ORDER BY 1
            """,
            echo=echo,
        )
        frame = frame.groupby("h", as_index=False).agg(
            n_tx=("n_tx", "sum"),
            fee_sum=("fee_sum", "sum"),
            fee_med=("fee_med", "median"),
            fee_p90=("fee_p90", "median"),
            cu_sum=("cu_sum", "sum"),
        )
        DATA.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(cache, index=False)
    echo(
        f"   {frame['n_tx'].sum():,} transactions over {len(frame)} hours "
        f"({len(frame) / 24:.1f} days), {frame['n_tx'].mean():,.0f}/hour on average"
    )

    out: dict[str, Any] = {}
    for col, name, unit in (
        ("n_tx", "transactions per hour", "x day mean"),
        ("fee_med", "median fee paid (lamports)", "x day mean"),
        ("fee_p90", "p90 fee paid (lamports)", "x day mean"),
        ("cu_sum", "compute units consumed", "x day mean"),
    ):
        d = Diurnal(hour_matrix(list(zip(frame["h"], frame[col], strict=False))), name=name, unit=unit)
        p = d.null_p()
        hi, lo = d.peak()
        spread = d.peak_ci()
        out[col] = dict(
            name=name,
            amp=d.observed(),
            p=p,
            peak=hi,
            trough=lo,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        )
        echo("")
        d.render(echo=echo)
        echo(
            f"     peak {hi:02d}h UTC (bootstrap spread {spread[0]:+.0f}..{spread[1]:+.0f} h), "
            f"trough {lo:02d}h, range {100 * (np.nanmax(d.profile) - np.nanmin(d.profile)):.1f}% "
            f"of the day mean, phase-scramble p = {p:.4f}"
        )
        echo("     (* marks hours whose 95% day-bootstrap interval excludes the day mean)")
    return out


# =========================================================================== 2. the launch


def launch(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """New coins per hour. The one clock that is entirely human: somebody launches these."""
    import numpy as np
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("2. THE LAUNCH CLOCK -- when are coins born")
    echo("=" * 100)
    cache = DATA / "mint_first_seen.parquet"
    if cache.exists():
        first = pd.read_parquet(cache)
    else:
        daily = per_day(
            "mint_day",
            lambda f: f"""
            SELECT u.mint AS mint, MIN(t.block_time) AS first_seen, COUNT(*) AS prints
            FROM read_parquet('{f}') t, UNNEST(t.post) s(u)
            WHERE u.mint LIKE '%pump'
            GROUP BY 1
            """,
            echo=echo,
        )
        first = daily.groupby("mint", as_index=False).agg(
            first_seen=("first_seen", "min"), prints=("prints", "sum")
        )
        DATA.mkdir(parents=True, exist_ok=True)
        first.to_parquet(cache, index=False)
    echo(f"   {len(first):,} distinct pump mints in the corpus")

    # The first corpus day cannot distinguish "born today" from "already alive", so it is
    # dropped rather than counted -- otherwise day 1 shows a launch spike that is really
    # the entire back catalogue arriving at once.
    t0 = int(first["first_seen"].min())
    cut = ((t0 // DAY) + 1) * DAY
    born = first[first["first_seen"] >= cut]
    echo(
        f"   dropping the first corpus day (left-censored: a coin's first SIGHTING is not "
        f"its birth) leaves {len(born):,} coins with an observed launch"
    )
    per_hour = born.groupby(born["first_seen"] // HOUR).size()
    d = Diurnal(hour_matrix(list(per_hour.items())), name="new coins per hour")
    p = d.null_p()
    hi, lo = d.peak()
    spread = d.peak_ci()
    echo("")
    d.render(echo=echo)
    echo(
        f"     {per_hour.mean():.0f} launches/hour on average; peak {hi:02d}h UTC "
        f"(spread {spread[0]:+.0f}..{spread[1]:+.0f} h), trough {lo:02d}h, "
        f"range {100 * (np.nanmax(d.profile) - np.nanmin(d.profile)):.1f}%, p = {p:.4f}"
    )

    # Survival of the newborn by hour of birth: a real operational question, because a
    # launch nobody is awake for should die faster.
    born = born.assign(hour=(born["first_seen"] % DAY) // HOUR)
    echo("")
    echo("   Does the hour of birth predict how long a coin keeps trading?")
    echo(f"   {'birth hour':<12}{'coins':>9}{'median prints':>15}{'>=200 prints':>14}")
    surv = []
    for h, g in born.groupby("hour"):
        surv.append((int(h), len(g), float(g["prints"].median()), float((g["prints"] >= 200).mean())))
    for h, n, med, big in surv:
        if h % 3 == 0:
            echo(f"   {h:02d}h{'':<9}{n:>9,}{med:>15.0f}{100 * big:>13.1f}%")
    shares = np.array([s[3] for s in surv])
    echo(
        f"   share reaching 200 prints ranges {100 * shares.min():.1f}%..{100 * shares.max():.1f}% "
        f"across birth hours (mean {100 * shares.mean():.1f}%)"
    )
    return dict(
        launches=dict(
            name="new coins per hour",
            amp=d.observed(),
            p=p,
            peak=hi,
            trough=lo,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        ),
        survival_by_hour=surv,
    )


# ============================================================================ 3. the wiggle


def build_cohort(*, echo: Callable[[str], None] = print) -> Path:
    """A sampled per-mint price tape, memory-bounded by construction."""
    import numpy as np
    import pandas as pd

    out = DATA / "cohort_prints.parquet"
    if out.exists():
        return out
    first = pd.read_parquet(DATA / "mint_first_seen.parquet")
    pool = first[first["prints"] >= COHORT_MIN_PRINTS]
    echo(f"   {len(pool):,} mints have >= {COHORT_MIN_PRINTS} prints; sampling {COHORT_MINTS:,}")
    rng = np.random.default_rng(41)
    take = pool.iloc[rng.choice(len(pool), size=min(COHORT_MINTS, len(pool)), replace=False)]
    mints = sorted(str(m) for m in take["mint"])
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "cohort_mints.json").write_text(json.dumps(mints))

    from studies.callout_volatility import CURVE_K, CURVE_TOKEN_OFFSET

    listed = "[" + ",".join(f"'{m}'" for m in mints) + "]"
    # One day at a time, and the counterparty is re-identified within each day. That is not a
    # compromise: the counterparty is the owner appearing in most of a mint's transactions --
    # the bonding curve before migration, the pool after -- and identifying it per day makes
    # a coin that migrates mid-window price correctly on both sides of the migration instead
    # of averaging two incompatible price bases. Same identification as
    # ``callout_volatility.build_panel``, restated because that version materialises all
    # 140,948 mints at once and this one must not.
    part_dir = DATA / "parts" / "cohort"
    part_dir.mkdir(parents=True, exist_ok=True)
    price = f"""CASE WHEN c.is_pool AND w.wsol > 0 AND c.tok > 0 THEN ln(w.wsol) - ln(c.tok)
                     WHEN NOT c.is_pool AND c.tok + {CURVE_TOKEN_OFFSET} > 0
                       THEN ln({CURVE_K}) - 2 * ln(c.tok + {CURVE_TOKEN_OFFSET}) END"""
    for path in bulk_files():
        part = part_dir / (path.stem + ".parquet")
        if part.exists():
            continue
        con = _duckdb(corpus=True)
        try:
            con.execute(
                f"""
                CREATE OR REPLACE TABLE legs AS
                SELECT t.block_time, t.block_slot, t.tx_index, u.owner AS owner, u.mint AS mint,
                       CAST(u.amount AS HUGEINT) AS amt
                FROM read_parquet('{path}') t, UNNEST(t.post) s(u)
                WHERE u.mint IN {listed} OR u.mint = '{WSOL}'
                """
            )
            con.execute(
                f"""
                CREATE OR REPLACE TABLE cpk AS
                WITH per_owner AS (
                  SELECT mint, owner, COUNT(*) n, MAX(amt) mx FROM legs
                  WHERE mint IN {listed} GROUP BY 1, 2
                ), ranked AS (
                  SELECT *, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY n DESC, mx DESC) rk
                  FROM per_owner
                ), cp AS (SELECT mint, owner AS cp_owner FROM ranked WHERE rk = 1)
                SELECT c.*, EXISTS (
                    SELECT 1 FROM legs l WHERE l.owner = c.cp_owner AND l.mint = '{WSOL}'
                ) AS is_pool FROM cp c
                """
            )
            con.execute(
                f"""
                COPY (
                  WITH cur AS (
                    SELECT l.mint, l.block_time, l.block_slot, l.tx_index,
                           CAST(l.amt AS DOUBLE) AS tok, k.is_pool
                    FROM legs l JOIN cpk k ON l.mint = k.mint AND l.owner = k.cp_owner
                  ), w AS (
                    SELECT l.block_slot, l.tx_index, k.mint, CAST(l.amt AS DOUBLE) AS wsol
                    FROM legs l JOIN cpk k ON l.owner = k.cp_owner
                    WHERE l.mint = '{WSOL}' AND k.is_pool
                  )
                  SELECT c.mint, c.block_time, {price} AS logp,
                         CASE WHEN c.is_pool THEN w.wsol / 1e9
                              ELSE {CURVE_K} / (c.tok + {CURVE_TOKEN_OFFSET}) / 1e9 END AS pool_sol
                  FROM cur c LEFT JOIN w ON c.mint = w.mint AND c.block_slot = w.block_slot
                                        AND c.tx_index = w.tx_index
                  WHERE ({price}) IS NOT NULL
                  ORDER BY mint, block_slot, tx_index
                ) TO '{part}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
        finally:
            con.close()
        echo(f"     cohort: folded {path.stem}")
    con = _duckdb()
    try:
        con.execute(
            f"""COPY (SELECT * FROM read_parquet('{part_dir}/*.parquet') ORDER BY mint, block_time)
                TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
        )
    finally:
        con.close()
    echo(f"   wrote {out}")
    return out


def wiggle(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """When is a wiggle worth harvesting? Oscillations that clear the coin's own friction."""
    import numpy as np
    import pandas as pd

    from studies.callout_volatility import round_trip_threshold, zigzag

    echo("")
    echo("=" * 100)
    echo("3. THE WIGGLE CLOCK -- when do oscillations clear friction")
    echo("=" * 100)
    echo("   The threshold is the coin's OWN round-trip cost at the operator's 0.1 SOL clip,")
    echo("   from `shitcoims_paperdesk.friction` -- the same module the desk trades on, so a")
    echo("   number here is comparable with a number there. It is an ORACLE bound: it assumes")
    echo("   turns at the exact extremes, which no live rule achieves. A null on the bound is")
    echo("   a null on every rule inside it; a positive is an upper limit, not a forecast.")

    path = build_cohort(echo=echo)
    frame = pd.read_parquet(path)
    echo(f"   cohort: {frame['mint'].nunique():,} mints, {len(frame):,} priced prints")

    rows: list[tuple[str, int, float, float, float, int]] = []
    for mint, g in frame.groupby("mint", sort=False):
        t = g["block_time"].to_numpy()
        lp = g["logp"].to_numpy()
        depth = g["pool_sol"].to_numpy()
        hours = t // HOUR
        edges = np.flatnonzero(np.diff(hours)) + 1
        for lo, hi in zip(np.r_[0, edges], np.r_[edges, len(t)], strict=False):
            if hi - lo < 8:
                continue
            seg = lp[lo:hi]
            d = float(np.nanmedian(depth[lo:hi]))
            thr = round_trip_threshold(d, take_bps=25)
            if not math.isfinite(thr):
                continue
            n_sw, amp = zigzag(seg, thr)
            rv = float(np.sum(np.diff(seg) ** 2))
            rows.append((str(mint), int(hours[lo]), amp - n_sw * thr, rv, thr, n_sw))
    panel = pd.DataFrame(rows, columns=["mint", "h", "wiggle_net", "rv", "thr", "swings"])
    echo(
        f"   {len(panel):,} coin-hours with >= 8 prints; {100 * float((panel['swings'] > 0).mean()):.1f}% "
        f"contain at least one friction-clearing swing"
    )
    echo(
        f"   median wiggle_net {panel['wiggle_net'].median():.4f} log units "
        f"({100 * float(np.expm1(panel['wiggle_net'].median())):.2f}% per coin-hour), "
        f"mean {panel['wiggle_net'].mean():.4f}"
    )

    out: dict[str, Any] = {}
    for col, name in (
        ("wiggle_net", "wiggle_net per active coin-hour (oracle)"),
        ("rv", "realised variance per active coin-hour"),
        ("swings", "friction-clearing swings per coin-hour"),
    ):
        per_hour = panel.groupby("h")[col].mean()
        d = Diurnal(hour_matrix(list(per_hour.items())), name=name, relative=(col != "wiggle_net"))
        p = d.null_p()
        hi_h, lo_h = d.peak()
        spread = d.peak_ci()
        echo("")
        d.render(echo=echo)
        echo(
            f"     peak {hi_h:02d}h UTC (spread {spread[0]:+.0f}..{spread[1]:+.0f} h), "
            f"trough {lo_h:02d}h, phase-scramble p = {p:.4f}"
        )
        out[col] = dict(
            name=name,
            amp=d.observed(),
            p=p,
            peak=hi_h,
            trough=lo_h,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        )
    out["coin_hours"] = len(panel)
    out["mints"] = int(panel["mint"].nunique())
    return out


def wiggle_pools(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """The same wiggle question on OUR nine pools, over 48 days instead of ten.

    Two reasons this exists beside the cohort version rather than instead of it. First
    POWER: the phase-scramble null averages ten independently-phased days in the corpus and
    forty-eight here, and the null's spread falls like 1/sqrt(days) -- a diurnal shape that
    ten days cannot separate from noise, forty-eight can. Second INDEPENDENCE: it is a
    different price construction (exact integer vault reserves, no bonding-curve identity
    and no offset constant) on a different population, so agreement between the two is
    evidence and disagreement is a finding.

    What it is NOT is a substitute. Nine pools we are long is not the coin population the
    operator would harvest, and the cohort version is the one that generalises.
    """
    import numpy as np
    import pandas as pd

    from studies.callout_volatility import round_trip_threshold, zigzag

    echo("")
    echo("=" * 100)
    echo("3b. THE WIGGLE CLOCK on our own pools -- 48 days, exact reserves")
    echo("=" * 100)
    con = _duckdb()
    files = "[" + ",".join(f"'{p}'" for p in sorted(HIST.glob("*.parquet"))) + "]"
    try:
        frame = con.execute(
            f"""
            SELECT pool, any_value(label) AS label, block_time, slot, tx_index,
                   vaults[1].mint AS m1, TRY_CAST(vaults[1].post_raw AS BIGINT) AS v1,
                   vaults[2].mint AS m2, TRY_CAST(vaults[2].post_raw AS BIGINT) AS v2
            FROM read_parquet({files})
            WHERE len(vaults) = 2 AND kind IN ('swap', 'reference', 'failed')
            GROUP BY pool, block_time, slot, tx_index, m1, v1, m2, v2
            ORDER BY pool, slot, tx_index
            """
        ).df()
    finally:
        con.close()
    q_is_1 = frame["m1"].to_numpy() == WSOL
    quote = np.where(q_is_1, frame["v1"], frame["v2"]).astype("float64")
    base = np.where(q_is_1, frame["v2"], frame["v1"]).astype("float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        frame["logp"] = np.log(quote) - np.log(base)
    frame["pool_sol"] = quote / 1e9
    # Only the WSOL-quoted pools: a token/token DLMM pool has no SOL leg, so its depth is
    # not a SOL depth and the friction model would be priced in the wrong unit.
    frame = frame[(q_is_1 | (frame["m2"].to_numpy() == WSOL)) & np.isfinite(frame["logp"])]
    echo(f"   {len(frame):,} priced prints on {frame['pool'].nunique()} SOL-quoted pools")

    rows = []
    for _pool, g in frame.groupby("pool", sort=False):
        t = g["block_time"].to_numpy()
        lp = g["logp"].to_numpy()
        depth = g["pool_sol"].to_numpy()
        label = str(g["label"].iloc[0])
        hours = t // HOUR
        edges = np.flatnonzero(np.diff(hours)) + 1
        for lo, hi in zip(np.r_[0, edges], np.r_[edges, len(t)], strict=False):
            if hi - lo < 8:
                continue
            thr = round_trip_threshold(float(np.nanmedian(depth[lo:hi])), take_bps=25)
            if not math.isfinite(thr):
                continue
            n_sw, amp = zigzag(lp[lo:hi], thr)
            rows.append((label, int(hours[lo]), amp - n_sw * thr, n_sw))
    panel = pd.DataFrame(rows, columns=["label", "h", "wiggle_net", "swings"])
    echo(
        f"   {len(panel):,} pool-hours with >= 8 prints; "
        f"{100 * float((panel['swings'] > 0).mean()):.1f}% contain a friction-clearing swing"
    )
    out: dict[str, Any] = {}
    for col, name in (
        ("wiggle_net", "wiggle_net per pool-hour, our pools (oracle)"),
        ("swings", "friction-clearing swings per pool-hour"),
    ):
        per_hour = panel.groupby("h")[col].mean()
        d = Diurnal(hour_matrix(list(per_hour.items())), name=name, relative=(col != "wiggle_net"))
        p = d.null_p()
        hi_h, lo_h = d.peak()
        spread = d.peak_ci()
        echo("")
        d.render(echo=echo)
        echo(
            f"     peak {hi_h:02d}h UTC (spread {spread[0]:+.0f}..{spread[1]:+.0f} h), "
            f"trough {lo_h:02d}h, {d.n_days} days, phase-scramble p = {p:.4f}"
        )
        out[col] = dict(
            name=name,
            amp=d.observed(),
            p=p,
            peak=hi_h,
            trough=lo_h,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        )
    return out


# =========================================================================== 4. the landing


def landing(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Congestion on OUR pools -- 48 days, and the only series long enough for a week."""
    import numpy as np
    import pandas as pd

    echo("")
    echo("=" * 100)
    echo("4. THE CONGESTION CLOCK -- failure share and depth on our own pools, 48 days")
    echo("=" * 100)
    con = _duckdb()
    files = "[" + ",".join(f"'{p}'" for p in sorted(HIST.glob('*.parquet'))) + "]"
    frame = con.execute(
        f"""
        SELECT pool, any_value(label) AS label, block_time // {HOUR} AS h,
               COUNT(*) AS n, SUM(CASE WHEN kind = 'failed' THEN 1 ELSE 0 END) AS n_fail,
               SUM(CASE WHEN kind = 'swap' THEN 1 ELSE 0 END) AS n_swap,
               approx_quantile(TRY_CAST(fee_lamports AS BIGINT), 0.5) AS fee_med,
               -- Depth is the SPREAD on an AMM. There is no order book and no quoted
               -- spread; what a taker pays above mid is entirely price impact, and impact
               -- is a function of the quote reserve. So the quote vault IS the spread
               -- series, and calling it "depth" rather than "spread" is only naming.
               median(CASE WHEN vaults[1].mint = '{WSOL}' THEN TRY_CAST(vaults[1].post_raw AS BIGINT)
                           WHEN vaults[2].mint = '{WSOL}' THEN TRY_CAST(vaults[2].post_raw AS BIGINT)
                      END) / 1e9 AS depth_sol
        FROM read_parquet({files})
        WHERE len(vaults) = 2
        GROUP BY 1, 3 ORDER BY 1, 3
        """
    ).df()
    con.close()
    echo(f"   {len(frame):,} pool-hours, {frame['n'].sum():,} transactions")

    agg = frame.groupby("h").agg(
        n=("n", "sum"), n_fail=("n_fail", "sum"), fee=("fee_med", "median"),
        depth=("depth_sol", "median"),
    )
    agg["fail_share"] = agg["n_fail"] / agg["n"]
    out: dict[str, Any] = {}
    for col, name, rel in (
        ("fail_share", "failure share of pool traffic", False),
        ("fee", "median fee on our pools (lamports)", True),
        ("depth", "pool depth = the AMM's spread (SOL)", True),
    ):
        d = Diurnal(hour_matrix(list(zip(agg.index, agg[col], strict=False))), name=name, relative=rel)
        p = d.null_p()
        hi_h, lo_h = d.peak()
        spread = d.peak_ci()
        echo("")
        d.render(echo=echo)
        echo(
            f"     peak {hi_h:02d}h UTC (spread {spread[0]:+.0f}..{spread[1]:+.0f} h), "
            f"trough {lo_h:02d}h, {d.n_days} days, phase-scramble p = {p:.4f}"
        )
        out[col] = dict(
            name=name,
            amp=d.observed(),
            p=p,
            peak=hi_h,
            trough=lo_h,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        )

    # --- the week, on the only pool that has one ---------------------------------
    echo("")
    echo("   THE WEEK. DREGG/SOL is the only series with more than one week in it, and it has")
    echo("   6.9. This is DESCRIPTION of seven weekdays, not inference about a weekly cycle.")
    dregg = frame[frame["label"].astype(str).str.startswith("DREGG/SOL")]
    if len(dregg):
        dregg = dregg.assign(
            dow=pd.to_datetime(dregg["h"] * HOUR, unit="s").dt.dayofweek,
            week=(dregg["h"] // (24 * 7)),
        )
        wk = dregg.groupby(["week", "dow"]).agg(n=("n", "sum"), f=("n_fail", "sum")).reset_index()
        wk["share"] = wk["f"] / wk["n"]
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        echo(f"   {'day':<7}{'weeks':>7}{'mean fail share':>18}{'sd across weeks':>18}{'mean tx/day':>14}")
        rows = []
        for dow, g in wk.groupby("dow"):
            rows.append((names[int(dow)], len(g), g["share"].mean(), g["share"].std(), g["n"].mean()))
            echo(
                f"   {names[int(dow)]:<7}{len(g):>7}{100 * g['share'].mean():>17.1f}%"
                f"{100 * g['share'].std():>17.1f}%{g['n'].mean():>14,.0f}"
            )
        spread = max(r[2] for r in rows) - min(r[2] for r in rows)
        sds = float(np.nanmean([r[3] for r in rows]))
        echo(
            f"   weekday spread {100 * spread:.1f} pp against a within-weekday sd of "
            f"{100 * sds:.1f} pp across weeks -- {'NOT ' if spread < sds else ''}separable"
        )
        out["weekday"] = dict(rows=rows, spread=float(spread), sd=sds)
    return out


# =============================================================================== 5. income


def fees(*, echo: Callable[[str], None] = print) -> dict[str, Any]:
    """Creator-fee ACCRUAL by hour -- and why the claim ledger cannot answer this."""
    import numpy as np

    echo("")
    echo("=" * 100)
    echo("5. THE INCOME CLOCK -- when fees accrue, which is not when they are claimed")
    echo("=" * 100)
    echo("   The brief asks for 'fee income arrival (the DREGG claims ledger)'. The claims")
    echo("   ledger CANNOT answer it. A claim is a transaction the OPERATOR sends; its")
    echo("   timestamp is the operator's sleep schedule, not the market's clock, and there")
    echo("   are ~213 of them against 96,414 swaps. What the desk actually wants to know is")
    echo("   when the fee ACCRUES, and that is a deterministic function of swap volume, which")
    echo("   the 48-day tape carries exactly. So: accrual from volume, claims for validation.")

    con = _duckdb()
    files = "[" + ",".join(f"'{p}'" for p in sorted(HIST.glob('*.parquet'))) + "]"
    vol = con.execute(
        f"""
        WITH legs AS (
          SELECT label, block_time, UNNEST(vaults) AS v FROM read_parquet({files}) WHERE kind = 'swap'
        )
        -- The WSOL leg alone IS the SOL flow; there is no halving, because the other leg is
        -- the token and is not being summed. (Halving would be right only if both legs were
        -- in the sum, which is the mistake this comment exists to stop.)
        SELECT label, block_time // {HOUR} AS h,
               SUM(ABS(TRY_CAST(v.delta_raw AS HUGEINT))) / 1e9 AS sol_flow, COUNT(*) AS legs
        FROM legs WHERE v.mint = '{WSOL}' GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).df()
    con.close()
    tot = vol.groupby("label")["sol_flow"].sum().sort_values(ascending=False)
    echo("")
    echo("   Quote-leg flow by pool over the 48 days (SOL):")
    for label, v in tot.items():
        echo(f"     {str(label)[:22]:<24}{v:>14,.1f}")

    dregg = vol[vol["label"].astype(str).str.startswith("DREGG/SOL")]
    per_hour = dregg.groupby("h")["sol_flow"].sum()
    d = Diurnal(hour_matrix(list(per_hour.items())), name="DREGG/SOL quote-leg flow per hour")
    p = d.null_p()
    hi_h, lo_h = d.peak()
    spread = d.peak_ci()
    echo("")
    d.render(echo=echo)
    echo(
        f"     peak {hi_h:02d}h UTC (spread {spread[0]:+.0f}..{spread[1]:+.0f} h), trough {lo_h:02d}h, "
        f"{d.n_days} days, phase-scramble p = {p:.4f}"
    )
    echo("     Creator fee is a fixed share of this, so its hour-of-day shape is identical:")
    echo("     the fee clock IS the volume clock, and there is nothing else in it.")

    out = dict(
        flow=dict(
            name="DREGG/SOL quote-leg flow per hour",
            amp=d.observed(),
            p=p,
            peak=hi_h,
            trough=lo_h,
            peak_spread=spread,
            profile=[float(x) for x in d.profile],
            n_days=d.n_days,
        )
    )

    ledger = REPO / ".cache" / "position_history" / "ledger.json"
    if ledger.exists():
        try:
            from studies.dregg_boundary import claim_receipts

            claims = claim_receipts()
        except Exception as exc:  # pragma: no cover - the ledger is a cache, not a contract
            echo(f"   (claim ledger present but unreadable: {type(exc).__name__})")
            claims = []
        if claims:
            hours = np.array([(t % DAY) // HOUR for t, _a, _s in claims])
            counts = np.bincount(hours, minlength=24)
            echo("")
            echo(f"   {len(claims)} claim receipts, by hour of day -- the OPERATOR's clock:")
            busiest = int(np.argmax(counts))
            echo(
                f"     {counts.tolist()}\n     mode {busiest:02d}h UTC; "
                f"{100 * counts[busiest] / counts.sum():.0f}% of claims in one hour, and the "
                f"quietest six hours hold {100 * np.sort(counts)[:6].sum() / counts.sum():.0f}%"
            )
            echo("     This is a human's calendar. It is reported so that nobody mistakes it")
            echo("     for the market's, which is what reading seasonality out of claims would do.")
            out["claim_hours"] = counts.tolist()
    return out


# ============================================================================= 6. calendar


def calendar(state: dict[str, Any], *, echo: Callable[[str], None] = print) -> None:
    """Assemble, control for multiplicity, and state what would falsify each row."""
    echo("")
    echo("=" * 100)
    echo("6. THE OPERATIONS CALENDAR -- what survives multiplicity, and its falsifier")
    echo("=" * 100)
    items: list[dict[str, Any]] = []
    for section in ("chain", "launch", "wiggle_pools", "wiggle", "landing", "fees"):
        for key, val in (state.get(section) or {}).items():
            if isinstance(val, dict) and "p" in val:
                items.append({**val, "section": section, "key": key})
    keep = by_fdr([i["p"] for i in items], FDR_Q)
    echo("")
    echo(f"   {len(items)} diurnal hypotheses, Benjamini-Yekutieli at q = {FDR_Q}")
    echo("")
    echo(f"   {'metric':<44}{'days':>6}{'peak':>7}{'trough':>8}{'amp':>9}{'p':>10}{'BY':>5}")
    for i, k in zip(items, keep, strict=False):
        i["by"] = bool(k)
        echo(
            f"   {i['name'][:42]:<44}{i['n_days']:>6}{i['peak']:>6}h{i['trough']:>7}h"
            f"{i['amp']:>9.3f}{i['p']:>10.4f}{'yes' if k else '.':>5}"
        )
    survivors = [i for i, k in zip(items, keep, strict=False) if k]
    echo("")
    if not survivors:
        echo("   NOTHING SURVIVES. The null is the calendar: on this window, no metric's")
        echo("   hour-of-day profile is distinguishable from ten independently-phased days.")
    else:
        echo(f"   {len(survivors)} of {len(items)} survive. Ranked by amplitude:")
        for i in sorted(survivors, key=lambda x: -x["amp"]):
            lo, hi = i["peak_spread"]
            echo(
                f"     {i['name'][:52]:<54} peak {i['peak']:02d}h UTC "
                f"(bootstrap spread {lo:+.0f}..{hi:+.0f} h)"
            )
    echo("")
    echo("   FALSIFIERS. Each survivor is a claim about the NEXT ten days, and the nightly")
    echo("   top-up path already collects them. Each is falsified if, on the next ten days:")
    for i in sorted(survivors, key=lambda x: -x["amp"]):
        echo(
            f"     - `{i['name'][:48]}` peaks more than 4 hours from {i['peak']:02d}h UTC, "
            f"or its phase-scramble p exceeds {FDR_Q}."
        )
    if not survivors:
        echo("     - any metric above reaches a phase-scramble p below 0.01 on the next ten")
        echo("       days with the SAME peak hour. One re-run cannot resurrect a null; a")
        echo("       consistent peak across two disjoint windows would.")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "state.json").write_text(json.dumps(state, indent=1, default=str))


# ================================================================================== main


SECTIONS: Final[tuple[str, ...]] = (
    "calibrate", "chain", "launch", "wiggle_pools", "landing", "fees", "calendar",
)
# ``wiggle`` (the corpus cohort) is NOT in the default set: it is a ten-day corpus fold
# and this machine is shared. Run it explicitly, alone, or on persvati.


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sections", nargs="*", default=["all"])
    args = ap.parse_args(argv)
    want = list(SECTIONS) if "all" in args.sections or not args.sections else args.sections
    state: dict[str, Any] = {}
    cached = DATA / "state.json"
    if cached.exists():
        with contextlib.suppress(json.JSONDecodeError):
            state = json.loads(cached.read_text())
    if "calibrate" in want:
        state["calibrate"] = calibrate()
    if "chain" in want:
        state["chain"] = chain()
    if "launch" in want:
        state["launch"] = launch()
    if "wiggle_pools" in want:
        state["wiggle_pools"] = wiggle_pools()
    if "wiggle" in want:
        state["wiggle"] = wiggle()
    if "landing" in want:
        state["landing"] = landing()
    if "fees" in want:
        state["fees"] = fees()
    if "calendar" in want:
        calendar(state)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "state.json").write_text(json.dumps(state, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
