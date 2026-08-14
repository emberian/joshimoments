"""Does the price ratio between the operator's frentokens mean-revert at a day-to-few-day horizon?

The whole LP thesis rests on this premise and nobody has ever measured it for a memecoin
population (``studies/RESULT_lp_literature.md`` §6.5: "the day-to-day mean-reversion premise
is neither supported nor refuted; it is untested"). This module measures it.

Run it::

    uv run python studies/mean_reversion.py                 # full run, writes results.json
    uv run python studies/mean_reversion.py --quick         # fewer replicates, same code path

It is deterministic given ``--seed`` and opens no socket. The cache it reads is materialised
by ``scripts/fetch_mean_reversion_data.py``.

---------------------------------------------------------------------------------------
WHAT IS ACTUALLY BEING TESTED, AND WHY EACH PIECE IS SHAPED THE WAY IT IS
---------------------------------------------------------------------------------------

**The binding constraint is span, not resolution.** The oldest pool in the cluster is 48 days
old and the youngest is 5. A "day-to-few-day horizon" statistic has at most ``span/horizon``
independent observations no matter how finely the price is sampled, so sampling every second
would not buy a single extra independent day. Every verdict below therefore carries the
horizon it was measured at, and the ones that cannot be resolved say so rather than
reporting a number with a confidence interval wide enough to drive a bus through.

**Variance ratio** (Lo & MacKinlay 1988). ``VR(q) = Var[q-period return] / (q · Var[1-period
return])``. Under a martingale difference it is 1 at every ``q``; below 1 is reversion, above
1 is trending. Both the homoskedastic statistic ``z(q)`` and the heteroskedasticity-robust
``z*(q)`` (their equations 20-22) are computed, because these series are violently
heteroskedastic and the homoskedastic version over-rejects — reporting only the point
estimate, or only ``z``, would manufacture reversion out of volatility clustering.

**Hurst exponent** by three estimators (DFA, R/S, GPH) because they disagree and the
disagreement is the finding. Weron (2002, Physica A 312:285) measured the small-sample null:
at L=1024 the standard deviation of Ĥ on *pure white noise* is 0.05-0.07 for R/S and DFA and
0.14 for GPH. So a point estimate is meaningless without its own null, and every Ĥ here is
reported against a simulated null at its own L.

**Return autocorrelation** at 1h/6h/24h, the horizons a ladder actually operates on, with
bands from a bootstrap that preserves volatility clustering.

**Two nulls, always** (PROGRAM.md §3.13):

* *wild bootstrap* — multiply each observed return by an independent Rademacher sign. This
  preserves the ``|r_t|`` sequence exactly, so volatility clustering and the zero-return
  pattern induced by empty bars survive untouched, while every odd-order serial dependence is
  destroyed. It is the null of "a martingale difference with exactly this volatility path".
* *white noise at matched L* — iid Gaussian of the same length. This is the null Weron
  tabulated, and it is what makes an Ĥ comparable to the published small-sample figures.

They answer different questions and are reported side by side.

**Two controls, always** (PROGRAM.md §3.12 — a zero-control alone certifies a broken
estimator as readily as a working one):

* *known-zero* — a random walk whose increments are a permutation of the real series'
  increments, so it has the real heteroskedasticity and the real empty bars but no serial
  structure. Every estimator must fail to reject.
* *known-effect* — an Ornstein-Uhlenbeck log-price with a stated half-life. Every estimator
  must reject in the reverting direction, and must recover roughly the right half-life.

**The microstructure control.** GeckoTerminal closes are *trade* prices, and a trade price
bounces between the two sides of the fee. That bounce is negative serial correlation that no
amount of statistics can distinguish from real reversion — it is the single most likely way
this study could produce a false positive. ``state/cluster_tape/`` records exact post-swap
vault balances, and a constant-product pool's *marginal* price is a state variable with no
bounce at all. The overlap is only ~1.5 days, but it is enough to size the contamination:
:func:`bounce_control` runs the same first-order autocorrelation on both and reports the gap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_CACHE: Final[Path] = REPO / "studies" / "data" / "mean_reversion"

# --------------------------------------------------------------------------------------
# Pre-registration. These are fixed before the data is looked at; the effective number of
# hypotheses in PROGRAM.md §3.9's sense is the size of this grid, and it is computable rather
# than guessed.
# --------------------------------------------------------------------------------------

#: The pairs the operator actually trades. Each is (label, numerator series, denominator
#: series or None for a SOL-quoted pool whose price is already the ratio).
CONFIRMATORY_PAIRS: Final[tuple[tuple[str, str, str | None], ...]] = (
    ("weave/SOL", "weave_per_sol", None),
    ("weave/nosis", "weave_per_sol", "nosis_per_sol"),
    ("weave/SOLVE", "weave_per_sol", "solve_per_sol"),
    ("DREGG/SOL", "dregg_per_sol", None),
)

#: Variance-ratio horizons, in units of the analysis grid step. On the hourly grid these are
#: 2h through 72h, which brackets the "day-to-few-day" claim on both sides.
VR_HORIZONS_HOURLY: Final[tuple[int, ...]] = (2, 3, 6, 12, 24, 48, 72)
#: On the 5-minute grid: 10 minutes through 24 hours.
VR_HORIZONS_5MIN: Final[tuple[int, ...]] = (2, 3, 6, 12, 36, 72, 144, 288)

#: Autocorrelation lags in hours — the horizons a ladder is actually rebalanced on.
ACF_LAGS_HOURLY: Final[tuple[int, ...]] = (1, 6, 24)

HURST_ESTIMATORS: Final[tuple[str, ...]] = ("dfa", "rs", "gph")

#: Not part of the confirmatory family and not one of the pairs the operator trades: this is
#: the pair ``studies/RESULT_swing_cluster.md`` called "robust reversion" on an AR(1) fit with
#: no null. Both legs are already in the cache, so re-running that claim against a simulated
#: unit-root null costs nothing and is the highest-value check available on a prior belief.
REPLICATION_PAIRS: Final[tuple[tuple[str, str, str], ...]] = (
    ("DREGG/SOLVE", "dregg_per_sol", "solve_per_sol"),
)

#: Benjamini-Hochberg level. Stated up front so it is not chosen after seeing the p-values.
FDR_Q: Final[float] = 0.10

#: Below this many independent horizon-length observations, a statistic at that horizon is
#: reported UNRESOLVABLE rather than given a verdict. 8 is deliberately generous — Fama-French
#: flag 8 monthly observations as a tail-bias source and that is the floor of the published
#: literature, not a comfortable sample.
MIN_INDEPENDENT_SPANS: Final[int] = 8


def subrng(seed: int, *tags: object) -> random.Random:
    """A deterministic sub-generator keyed by name, so results never depend on call order.

    ``hash()`` is salted per process in Python, so a stable digest is used instead. Without
    this, adding one pair to the grid would silently change every other pair's null draws and
    a rerun would not reproduce.
    """

    key = "|".join(str(t) for t in tags).encode()
    digest = hashlib.blake2b(key, digest_size=8, key=str(seed).encode()[:64]).digest()
    return random.Random(int.from_bytes(digest, "big"))


# --------------------------------------------------------------------------------------
# Loading and grid construction
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candle:
    t: int
    close: float


@dataclass(frozen=True, slots=True)
class Grid:
    """A regularly-spaced log-price series, plus an honest account of what was made up.

    ``stale`` marks bars carried forward from an earlier trade. A memecoin pool does not
    trade every minute, and a forward-filled bar contributes a zero return that is a fact
    about the venue rather than about the price. The wild bootstrap preserves those zeros
    exactly, so the null distribution absorbs the artifact instead of the estimate having to
    be corrected for it.
    """

    label: str
    step_s: int
    times: tuple[int, ...]
    log_price: tuple[float, ...]
    stale: tuple[bool, ...]

    @property
    def n(self) -> int:
        return len(self.log_price)

    @property
    def returns(self) -> tuple[float, ...]:
        lp = self.log_price
        return tuple(lp[i] - lp[i - 1] for i in range(1, len(lp)))

    @property
    def stale_fraction(self) -> float:
        return sum(self.stale) / len(self.stale) if self.stale else 0.0

    @property
    def span_days(self) -> float:
        return (self.times[-1] - self.times[0]) / 86400.0 if self.times else 0.0


def load_gt_cache(path: Path) -> dict[tuple[str, str], list[Candle]]:
    """Read the GeckoTerminal cache into ``(series, grid) -> candles``, oldest first.

    The cache is written in append mode across several fetch runs, so the *last* line can be a
    torn write if a run was interrupted. That one line is tolerated; a malformed line anywhere
    earlier is corruption and raises, because silently dropping rows from the middle of a
    price series would shorten a span without saying so.
    """

    out: dict[tuple[str, str], dict[int, float]] = {}
    with path.open(encoding="utf-8") as handle:
        lines = handle.readlines()
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
        if row.get("kind") != "ohlcv":
            continue
        key = (row["series"], f"{row['timeframe']}{row['aggregate']}")
        # Pages overlap by design (the venue is paged backwards by timestamp); a dict keyed
        # on chain time makes the de-duplication exact rather than approximate.
        out.setdefault(key, {})[int(row["t_event"])] = float(row["close"])
    return {k: [Candle(t, c) for t, c in sorted(v.items())] for k, v in out.items()}


def build_grid(candles: Sequence[Candle], step_s: int, label: str) -> Grid:
    """Forward-fill sparse candles onto a regular grid anchored on chain time.

    Chain time is the origin (PROGRAM.md §3.8) — these timestamps are candle-bucket starts
    derived from block times, never ingest time.
    """

    if len(candles) < 2:
        return Grid(label=label, step_s=step_s, times=(), log_price=(), stale=())
    start = candles[0].t - candles[0].t % step_s
    end = candles[-1].t
    by_bucket: dict[int, float] = {}
    for candle in candles:
        by_bucket[candle.t - candle.t % step_s] = candle.close  # last close in the bucket wins

    times: list[int] = []
    log_price: list[float] = []
    stale: list[bool] = []
    last: float | None = None
    bucket = start
    while bucket <= end:
        price = by_bucket.get(bucket)
        if price is None:
            if last is None:
                bucket += step_s
                continue
            price, is_stale = last, True
        else:
            is_stale = False
        if price <= 0.0:
            bucket += step_s
            continue
        times.append(bucket)
        log_price.append(math.log(price))
        stale.append(is_stale)
        last = price
        bucket += step_s
    return Grid(label, step_s, tuple(times), tuple(log_price), tuple(stale))


def ratio_grid(numerator: Grid, denominator: Grid, label: str) -> Grid:
    """Log-ratio of two grids on their common timestamps.

    The ratio is formed from the two *deep* SOL pools rather than from the thin direct
    token-token pool. That is a deliberate trade: the direct pool is the venue the LP position
    actually sits in, but it is hours old and carries a handful of trades, whereas the ratio
    of two SOL legs is exactly the price a router would arbitrage the direct pool to.
    """

    a = dict(zip(numerator.times, numerator.log_price, strict=True))
    a_stale = dict(zip(numerator.times, numerator.stale, strict=True))
    b = dict(zip(denominator.times, denominator.log_price, strict=True))
    b_stale = dict(zip(denominator.times, denominator.stale, strict=True))
    common = sorted(set(a) & set(b))
    return Grid(
        label=label,
        step_s=numerator.step_s,
        times=tuple(common),
        log_price=tuple(a[t] - b[t] for t in common),
        # A bar is stale if EITHER leg is stale: the ratio did not move because neither did.
        stale=tuple(a_stale[t] or b_stale[t] for t in common),
    )


# --------------------------------------------------------------------------------------
# Variance ratio
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VarianceRatio:
    q: int
    vr: float
    z_homoskedastic: float
    z_robust: float
    p_asymptotic: float
    p_bootstrap: float
    null_mean: float
    null_sd: float
    null_q05: float
    null_q95: float
    n_returns: int
    independent_spans: float
    #: The smallest ``VR < 1`` this sample could have detected at 80% power, and the AR(1)
    #: half-life that corresponds to. This is what turns "we found nothing" into a statement
    #: with content: reversion slower than ``mde_half_life_hours`` is invisible here, and no
    #: amount of re-analysis of this sample will make it visible.
    mde_vr: float
    mde_half_life_hours: float
    #: The same null, recomputed with the magnitude sequence PERMUTED IN TIME. Identical
    #: magnitudes, identical marginal distribution, only the temporal profile of volatility
    #: destroyed. If ``null_mean`` is below 1 and this is at 1, the gap is caused by *where*
    #: the volatility sits in the sample and by nothing else. See :func:`analyse_variance_ratios`.
    shuffled_null_mean: float


#: 1.96 + 0.84: two-sided 5% test at 80% power, in units of the null's standard deviation.
MDE_Z: Final[float] = 2.80


def ar1_variance_ratio(phi: float, q: int) -> float:
    """``VR(q)`` of a log-price following a stationary AR(1) with coefficient ``phi``.

    ``Var[x_t - x_{t-q}] = 2 s^2 (1 - phi^q)``, so ``VR(q) = (1 - phi^q) / (q(1 - phi))``.
    Monotone increasing in ``phi``, with ``VR -> 1/q`` as ``phi -> 0`` and ``VR -> 1`` as
    ``phi -> 1``, which is what makes the inversion below well posed.
    """

    if not 0.0 < phi < 1.0:
        raise ValueError("phi must lie strictly inside (0, 1)")
    return (1.0 - phi**q) / (q * (1.0 - phi))


def half_life_for_variance_ratio(target_vr: float, q: int, step_s: int) -> float:
    """Invert :func:`ar1_variance_ratio` for the mean-reversion half-life, in hours.

    Returns ``inf`` when the target is at or above 1 (no reversion is implied) and ``0.0``
    when it is below ``1/q`` (faster than one bar — outside what this grid can express).
    """

    if target_vr >= 1.0:
        return float("inf")
    if target_vr <= 1.0 / q:
        return 0.0
    lo, hi = 1e-9, 1.0 - 1e-12
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if ar1_variance_ratio(mid, q) < target_vr:
            lo = mid
        else:
            hi = mid
    phi = 0.5 * (lo + hi)
    return -math.log(2.0) / math.log(phi) * step_s / 3600.0


def variance_ratio(returns: Sequence[float], q: int) -> float:
    """Lo-MacKinlay overlapping variance ratio, unbiased in both variance estimators."""

    n = len(returns)
    if q < 2 or n <= q:
        raise ValueError(f"variance ratio needs n > q >= 2; got n={n}, q={q}")
    mu = sum(returns) / n
    var_1 = sum((r - mu) ** 2 for r in returns) / (n - 1)
    if var_1 <= 0.0:
        raise ValueError("one-period variance is zero; the series never moves")
    # Overlapping q-period sums. A prefix sum makes this O(n) rather than O(nq).
    prefix = [0.0]
    for r in returns:
        prefix.append(prefix[-1] + r)
    m = q * (n - q + 1) * (1.0 - q / n)
    acc = 0.0
    for t in range(q, n + 1):
        acc += (prefix[t] - prefix[t - q] - q * mu) ** 2
    var_q = acc / m
    return var_q / var_1


def _vr_z_statistics(returns: Sequence[float], q: int, vr: float) -> tuple[float, float]:
    """Return ``(z_homoskedastic, z_robust)`` — Lo & MacKinlay (1988) eqs. 18 and 20-22.

    The robust one is the number that matters. ``z`` assumes constant variance; a memecoin
    return series has volatility clustering that inflates the apparent dispersion of q-period
    sums, so ``z`` over-rejects and would hand back trending or reversion that is nothing but
    the volatility path.

    Note the scaling, which is easy to get wrong and was got wrong here first::

        delta_j = sum_t dev2_t dev2_{t-j} / (sum_t dev2_t)^2      ~ 1/n under iid
        theta   = sum_j [2(q-j)/q]^2 delta_j                      ~ V_homo / n
        z*      = (VR - 1) / sqrt(theta)

    ``delta_j`` already carries the ``1/n``, so multiplying by ``sqrt(n)`` on top — the shape
    the homoskedastic statistic has — inflates ``z*`` by a factor of ``sqrt(n)``. The
    known-zero control caught it: the robust statistic was rejecting a pure martingale
    difference **94.2%** of the time, against 7.5% for the homoskedastic one it is supposed to
    be more conservative than. The sanity anchor is that on iid data ``theta -> V_homo/n`` and
    ``z*`` collapses onto ``z``.
    """

    n = len(returns)
    mu = sum(returns) / n
    dev2 = [(r - mu) ** 2 for r in returns]
    denom = sum(dev2)
    z_homo = math.sqrt(n) * (vr - 1.0) / math.sqrt(2.0 * (2 * q - 1) * (q - 1) / (3.0 * q))
    if denom <= 0.0:
        return z_homo, float("nan")
    theta = 0.0
    for j in range(1, q):
        num = sum(dev2[t] * dev2[t - j] for t in range(j, n))
        theta += ((2.0 * (q - j)) / q) ** 2 * (num / (denom * denom))
    if theta <= 0.0:
        return z_homo, float("nan")
    return z_homo, (vr - 1.0) / math.sqrt(theta)


def normal_two_sided_p(z: float) -> float:
    if math.isnan(z):
        return float("nan")
    return math.erfc(abs(z) / math.sqrt(2.0))


# --------------------------------------------------------------------------------------
# Hurst exponents
# --------------------------------------------------------------------------------------


def _log_scales(n: int, smallest: int, largest_fraction: float, count: int) -> list[int]:
    largest = max(smallest + 1, int(n * largest_fraction))
    if largest <= smallest:
        return [smallest]
    ratio = (largest / smallest) ** (1.0 / max(1, count - 1))
    scales = sorted({round(smallest * ratio**i) for i in range(count)})
    return [s for s in scales if smallest <= s <= largest]


def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0.0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx


def hurst_dfa(returns: Sequence[float]) -> float:
    """Detrended fluctuation analysis, order 1. ``F(s) ~ s^H``."""

    n = len(returns)
    if n < 32:
        return float("nan")
    mean = sum(returns) / n
    profile = [0.0]
    for r in returns:
        profile.append(profile[-1] + (r - mean))
    profile = profile[1:]
    scales = _log_scales(n, smallest=8, largest_fraction=0.25, count=12)
    xs: list[float] = []
    ys: list[float] = []
    for s in scales:
        blocks = n // s
        if blocks < 2:
            continue
        total = 0.0
        used = 0
        # Both directions, so the tail of the profile is not silently discarded.
        for direction in (0, 1):
            offset = 0 if direction == 0 else n - blocks * s
            for b in range(blocks):
                seg = profile[offset + b * s : offset + (b + 1) * s]
                ts = list(range(s))
                slope = _ols_slope(ts, seg)
                if math.isnan(slope):
                    continue
                mt = (s - 1) / 2.0
                ms = sum(seg) / s
                intercept = ms - slope * mt
                total += sum((seg[i] - (slope * i + intercept)) ** 2 for i in range(s)) / s
                used += 1
        if used == 0:
            continue
        f = math.sqrt(total / used)
        if f <= 0.0:
            continue
        xs.append(math.log(s))
        ys.append(math.log(f))
    if len(xs) < 3:
        return float("nan")
    return _ols_slope(xs, ys)


def hurst_rs(returns: Sequence[float]) -> float:
    """Classic rescaled-range analysis over non-overlapping windows."""

    n = len(returns)
    if n < 32:
        return float("nan")
    scales = _log_scales(n, smallest=8, largest_fraction=0.25, count=12)
    xs: list[float] = []
    ys: list[float] = []
    for s in scales:
        blocks = n // s
        if blocks < 2:
            continue
        ratios: list[float] = []
        for b in range(blocks):
            seg = returns[b * s : (b + 1) * s]
            mean = sum(seg) / s
            cumulative = 0.0
            lo = math.inf
            hi = -math.inf
            for value in seg:
                cumulative += value - mean
                lo = min(lo, cumulative)
                hi = max(hi, cumulative)
            spread = hi - lo
            sd = statistics.pstdev(seg)
            if sd <= 0.0 or spread <= 0.0:
                continue
            ratios.append(spread / sd)
        if not ratios:
            continue
        xs.append(math.log(s))
        ys.append(math.log(sum(ratios) / len(ratios)))
    if len(xs) < 3:
        return float("nan")
    return _ols_slope(xs, ys)


def hurst_gph(returns: Sequence[float], bandwidth: int | None = None) -> float:
    """Geweke-Porter-Hudak log-periodogram regression. ``H = d + 1/2``.

    Only the lowest ``m ~ sqrt(n)`` Fourier frequencies are needed, so the periodogram is
    evaluated directly at those frequencies rather than by a full transform. This is the
    estimator Weron measured a white-noise standard deviation of **0.14** for at L=1024 — it
    is included precisely because it is the noisy one, and its disagreement with DFA/RS is
    information about the sample, not a defect.
    """

    n = len(returns)
    if n < 64:
        return float("nan")
    m = bandwidth if bandwidth is not None else int(math.sqrt(n))
    m = max(4, min(m, n // 2 - 1))
    mean = sum(returns) / n
    centred = [r - mean for r in returns]
    xs: list[float] = []
    ys: list[float] = []
    for j in range(1, m + 1):
        lam = 2.0 * math.pi * j / n
        re = 0.0
        im = 0.0
        for t, value in enumerate(centred):
            angle = lam * t
            re += value * math.cos(angle)
            im += value * math.sin(angle)
        power = (re * re + im * im) / (2.0 * math.pi * n)
        if power <= 0.0:
            continue
        regressor = math.log(4.0 * math.sin(lam / 2.0) ** 2)
        xs.append(regressor)
        ys.append(math.log(power))
    if len(xs) < 4:
        return float("nan")
    d = -_ols_slope(xs, ys)
    return d + 0.5


HURST_FUNCTIONS: Final[dict[str, Any]] = {"dfa": hurst_dfa, "rs": hurst_rs, "gph": hurst_gph}


# --------------------------------------------------------------------------------------
# Autocorrelation
# --------------------------------------------------------------------------------------


def autocorrelation(returns: Sequence[float], lag: int) -> float:
    n = len(returns)
    if lag <= 0 or n <= lag + 1:
        return float("nan")
    mean = sum(returns) / n
    denom = sum((r - mean) ** 2 for r in returns)
    if denom <= 0.0:
        return float("nan")
    num = sum((returns[t] - mean) * (returns[t - lag] - mean) for t in range(lag, n))
    return num / denom


# --------------------------------------------------------------------------------------
# Resampling
# --------------------------------------------------------------------------------------


def wild_bootstrap(returns: Sequence[float], rng: random.Random) -> list[float]:
    """Rademacher sign-flip. Preserves ``|r_t|`` exactly, hence volatility clustering and the
    zero-return pattern of empty bars; destroys every odd-order serial dependence."""

    return [r if rng.random() < 0.5 else -r for r in returns]


def stationary_block_bootstrap(
    returns: Sequence[float], rng: random.Random, mean_block: float
) -> list[float]:
    """Politis-Romano stationary bootstrap: geometric block lengths, circular wrap.

    Used for confidence intervals *around* an estimate, where the dependence structure must
    be preserved rather than destroyed. The wild bootstrap is the wrong tool there — it
    imposes the null and so would report the null's width as the estimate's width.
    """

    n = len(returns)
    if n == 0:
        return []
    p = 1.0 / max(1.0, mean_block)
    out: list[float] = []
    index = rng.randrange(n)
    while len(out) < n:
        out.append(returns[index])
        index = rng.randrange(n) if rng.random() < p else (index + 1) % n
    return out


def simulate_ou(
    n: int, half_life: float, sigma: float, rng: random.Random, stale: Sequence[bool] | None = None
) -> list[float]:
    """Increments of an OU log-price with a stated half-life — the KNOWN-EFFECT control.

    ``x_{t+1} = phi x_t + eps``, ``phi = 2^(-1/half_life)``. Returns are ``x_{t+1} - x_t``,
    which is the object every estimator here consumes. If ``stale`` is supplied the same
    empty-bar pattern is imposed, so the control is a like-for-like of the real series and a
    green control cannot be an artifact of the real series' missingness.
    """

    phi = 2.0 ** (-1.0 / half_life)
    level = 0.0
    out: list[float] = []
    for i in range(n):
        if stale is not None and i < len(stale) and stale[i]:
            out.append(0.0)
            continue
        new = phi * level + rng.gauss(0.0, sigma)
        out.append(new - level)
        level = new
    return out


def simulate_random_walk(
    n: int, magnitudes: Sequence[float], rng: random.Random
) -> list[float]:
    """KNOWN-ZERO control: a permutation of the real magnitudes with random signs.

    This keeps the real fat tails, the real empty bars (a zero magnitude stays zero under any
    sign) and the real marginal distribution, and removes only the serial structure. A
    Gaussian random walk would be a weaker control because failing to reject on it could just
    mean the estimator is confused by tails.
    """

    pool = list(magnitudes)
    rng.shuffle(pool)
    return [m if rng.random() < 0.5 else -m for m in pool[:n]]


# --------------------------------------------------------------------------------------
# Multiple testing
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BHOutcome:
    name: str
    p: float
    rank: int
    threshold: float
    rejected: bool


def benjamini_hochberg(pvalues: dict[str, float], q: float) -> list[BHOutcome]:
    """BH-FDR. Returns every hypothesis, rejected or not — a null is a result (§3)."""

    usable = {k: v for k, v in pvalues.items() if not math.isnan(v)}
    ordered = sorted(usable.items(), key=lambda kv: kv[1])
    m = len(ordered)
    cutoff_rank = 0
    for i, (_, p) in enumerate(ordered, start=1):
        if p <= q * i / m:
            cutoff_rank = i
    out = [
        BHOutcome(name=name, p=p, rank=i, threshold=q * i / m, rejected=i <= cutoff_rank)
        for i, (name, p) in enumerate(ordered, start=1)
    ]
    for name, p in pvalues.items():
        if math.isnan(p):
            out.append(BHOutcome(name=name, p=p, rank=0, threshold=float("nan"), rejected=False))
    return out


# --------------------------------------------------------------------------------------
# The analyses
# --------------------------------------------------------------------------------------


def empirical_p(observed: float, null: Sequence[float]) -> float:
    """Two-sided bootstrap p-value with the +1 correction (never reports exactly zero)."""

    clean = [v for v in null if not math.isnan(v)]
    if not clean:
        return float("nan")
    centre = statistics.median(clean)
    extreme = sum(1 for v in clean if abs(v - centre) >= abs(observed - centre))
    return (extreme + 1) / (len(clean) + 1)


def _mean_clean(values: Sequence[float]) -> float:
    clean = [v for v in values if not math.isnan(v)]
    return statistics.fmean(clean) if clean else float("nan")


def _sd_clean(values: Sequence[float]) -> float:
    clean = [v for v in values if not math.isnan(v)]
    return statistics.pstdev(clean) if len(clean) > 1 else float("nan")


def quantile(values: Sequence[float], q: float) -> float:
    clean = sorted(v for v in values if not math.isnan(v))
    if not clean:
        return float("nan")
    pos = q * (len(clean) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(clean) - 1)
    return clean[lo] + (clean[hi] - clean[lo]) * (pos - lo)


def analyse_variance_ratios(
    grid: Grid, horizons: Sequence[int], replicates: int, seed: int
) -> list[VarianceRatio]:
    returns = grid.returns
    n = len(returns)
    out: list[VarianceRatio] = []
    for q in horizons:
        if n <= q + 2:
            continue
        vr = variance_ratio(returns, q)
        z_homo, z_robust = _vr_z_statistics(returns, q, vr)
        rng = subrng(seed, "vr", grid.label, grid.step_s, q)
        null = []
        for _ in range(replicates):
            try:
                null.append(variance_ratio(wild_bootstrap(returns, rng), q))
            except ValueError:
                continue
        null_sd = _sd_clean(null)
        null_mean = _mean_clean(null)
        # Time-shuffled null: same magnitudes, same signs process, volatility profile destroyed.
        shuffle_rng = subrng(seed, "vr-shuffled", grid.label, grid.step_s, q)
        magnitudes = [abs(r) for r in returns]
        shuffled = []
        for _ in range(max(100, replicates // 4)):
            pool = list(magnitudes)
            shuffle_rng.shuffle(pool)
            try:
                shuffled.append(
                    variance_ratio(
                        [m if shuffle_rng.random() < 0.5 else -m for m in pool], q
                    )
                )
            except ValueError:
                continue
        # The MDE is measured from where the null actually sits, not from 1. The estimator is
        # biased multiplicatively here (a true VR of v is observed near v * null_mean), so the
        # smallest TRUE variance ratio distinguishable from a random walk at 80% power is
        # 1 - z * sd / null_mean. Centring this on 1 instead — which is what the asymptotic
        # statistic does — overstates the sample's reach by exactly the size of the bias.
        mde_vr = (
            1.0 - MDE_Z * null_sd / null_mean
            if not math.isnan(null_sd) and not math.isnan(null_mean) and null_mean > 0
            else float("nan")
        )
        out.append(
            VarianceRatio(
                q=q,
                vr=vr,
                z_homoskedastic=z_homo,
                z_robust=z_robust,
                p_asymptotic=normal_two_sided_p(z_robust),
                p_bootstrap=empirical_p(vr, null),
                null_mean=null_mean,
                null_sd=null_sd,
                null_q05=quantile(null, 0.05),
                null_q95=quantile(null, 0.95),
                n_returns=n,
                independent_spans=n / q,
                mde_vr=mde_vr,
                mde_half_life_hours=(
                    float("nan")
                    if math.isnan(mde_vr)
                    else half_life_for_variance_ratio(mde_vr, q, grid.step_s)
                ),
                shuffled_null_mean=_mean_clean(shuffled),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class HurstResult:
    estimator: str
    h: float
    wild_null_mean: float
    wild_null_sd: float
    wild_p: float
    white_null_mean: float
    white_null_sd: float
    white_p: float
    n_returns: int
    #: The smallest departure from 1/2 detectable at 80% power against the wild null. Weron's
    #: point, made for OUR sample: below this, an estimate is a coin toss.
    mde_h: float


def analyse_hurst(grid: Grid, replicates: int, seed: int) -> list[HurstResult]:
    returns = grid.returns
    n = len(returns)
    sigma = statistics.pstdev(returns) if n > 1 else 0.0
    out: list[HurstResult] = []
    for name in HURST_ESTIMATORS:
        estimator = HURST_FUNCTIONS[name]
        h = estimator(returns)
        rng = subrng(seed, "hurst", grid.label, grid.step_s, name)
        # Null 1: wild bootstrap. Keeps |r_t| exactly, so the real fat tails, the real
        # volatility clustering and the real empty bars are all still there under the null.
        wild = [estimator(wild_bootstrap(returns, rng)) for _ in range(replicates)]
        # Null 2: iid Gaussian at matched length. This is Weron's setting exactly, which is
        # what lets our spread be compared with his published 0.05-0.07 (DFA/RS) and 0.14 (GPH).
        white = [
            estimator([rng.gauss(0.0, sigma or 1.0) for _ in range(n)]) for _ in range(replicates)
        ]
        out.append(
            HurstResult(
                estimator=name,
                h=h,
                wild_null_mean=_mean_clean(wild),
                wild_null_sd=_sd_clean(wild),
                wild_p=empirical_p(h, wild),
                white_null_mean=_mean_clean(white),
                white_null_sd=_sd_clean(white),
                white_p=empirical_p(h, white),
                n_returns=n,
                mde_h=MDE_Z * _sd_clean(wild),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class AcfResult:
    lag: int
    rho: float
    mde_rho: float
    null_q025: float
    null_q975: float
    null_sd: float
    p_bootstrap: float
    ci_low: float
    ci_high: float
    n_returns: int
    independent_spans: float


def analyse_autocorrelation(
    grid: Grid, lags: Sequence[int], replicates: int, seed: int, mean_block: float
) -> list[AcfResult]:
    returns = grid.returns
    n = len(returns)
    out: list[AcfResult] = []
    for lag in lags:
        if n <= lag + 2:
            continue
        rho = autocorrelation(returns, lag)
        rng = subrng(seed, "acf", grid.label, grid.step_s, lag)
        null = [autocorrelation(wild_bootstrap(returns, rng), lag) for _ in range(replicates)]
        boot = [
            autocorrelation(stationary_block_bootstrap(returns, rng, mean_block), lag)
            for _ in range(replicates)
        ]
        out.append(
            AcfResult(
                lag=lag,
                rho=rho,
                mde_rho=MDE_Z * _sd_clean(null),
                null_q025=quantile(null, 0.025),
                null_q975=quantile(null, 0.975),
                null_sd=_sd_clean(null),
                p_bootstrap=empirical_p(rho, null),
                ci_low=quantile(boot, 0.025),
                ci_high=quantile(boot, 0.975),
                n_returns=n,
                independent_spans=n / lag,
            )
        )
    return out


# --------------------------------------------------------------------------------------
# The memecoin-SOL correlation and the quote-asset break-even
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QuoteAssetResult:
    token: str
    n: int
    span_days: float
    rho: float
    rho_ci_low: float
    rho_ci_high: float
    sigma_meme_hourly: float
    sigma_sol_hourly: float
    sigma_meme_annual: float
    sigma_sol_annual: float
    breakeven_rho: float
    passes_breakeven: bool
    var_in_sol: float
    var_in_usd: float
    variance_reduction: float
    variance_reduction_ci_low: float
    variance_reduction_ci_high: float


def analyse_quote_asset(
    token_label: str,
    token_grid: Grid,
    sol_grid: Grid,
    replicates: int,
    seed: int,
    mean_block: float,
) -> QuoteAssetResult | None:
    """Does quoting against SOL rather than a stablecoin reduce adverse selection?

    ``sigma^2_ratio = sigma_A^2 + sigma_B^2 - 2 rho sigma_A sigma_B`` and LVR is proportional
    to it, so SOL-quoting wins iff ``rho > sigma_SOL / (2 sigma_meme)``.

    That inequality is reported, and so is its algebraically identical direct form. Write
    ``r_ms`` for the token's return quoted in SOL and ``r_su`` for SOL/USD; then
    ``r_mu = r_ms + r_su`` exactly, and

        Var[r_mu] - Var[r_ms] = sigma_SOL^2 + 2 Cov[r_ms, r_su],

    so the question is simply **is the token less volatile quoted in SOL than in dollars**.
    The two are the same test written twice — if they ever disagree, the code is wrong, which
    is worth having as a free internal check.

    **What the bounce does to each.** Write the observed SOL-quoted return as
    ``r_ms + e``, ``e`` the fee bounce. Then ``Var[r_mu] - Var[r_ms]`` is unaffected: the
    ``Var[e]`` sits in both variances and cancels. In the correlation form, ``rho`` is
    attenuated by ``1/sqrt(1 + Var[e]/Var[r_mu])`` and the break-even ``rho*`` is divided by
    exactly the same factor, so **the decision is bounce-robust but the reported rho is a
    lower bound on the true correlation** — and so is the break-even it is being compared
    against. Neither number should be quoted on its own; the gap between them is the result.
    """

    token_map = dict(zip(token_grid.times, token_grid.log_price, strict=True))
    sol_map = dict(zip(sol_grid.times, sol_grid.log_price, strict=True))
    common = sorted(set(token_map) & set(sol_map))
    if len(common) < 48:
        return None
    r_ms = [token_map[common[i]] - token_map[common[i - 1]] for i in range(1, len(common))]
    r_su = [sol_map[common[i]] - sol_map[common[i - 1]] for i in range(1, len(common))]
    n = len(r_ms)

    def stats(ms: Sequence[float], su: Sequence[float]) -> tuple[float, float, float, float, float]:
        mu = [a + b for a, b in zip(ms, su, strict=True)]
        sd_m = statistics.pstdev(mu)
        sd_s = statistics.pstdev(su)
        mean_m = statistics.fmean(mu)
        mean_s = statistics.fmean(su)
        cov = sum((a - mean_m) * (b - mean_s) for a, b in zip(mu, su, strict=True)) / len(mu)
        rho = cov / (sd_m * sd_s) if sd_m > 0 and sd_s > 0 else float("nan")
        var_sol = statistics.pvariance(ms)
        var_usd = statistics.pvariance(mu)
        return rho, sd_m, sd_s, var_sol, var_usd

    rho, sd_m, sd_s, var_sol, var_usd = stats(r_ms, r_su)

    # Block bootstrap in PAIRS: the two legs must be resampled on the same index sequence or
    # the covariance being estimated is destroyed by the resampling itself.
    rng = subrng(seed, "quote", token_label)
    rhos: list[float] = []
    reductions: list[float] = []
    p = 1.0 / max(1.0, mean_block)
    for _ in range(replicates):
        idx: list[int] = []
        cursor = rng.randrange(n)
        while len(idx) < n:
            idx.append(cursor)
            cursor = rng.randrange(n) if rng.random() < p else (cursor + 1) % n
        bms = [r_ms[i] for i in idx]
        bsu = [r_su[i] for i in idx]
        b_rho, _, _, b_var_sol, b_var_usd = stats(bms, bsu)
        rhos.append(b_rho)
        if b_var_usd > 0:
            reductions.append(1.0 - b_var_sol / b_var_usd)

    per_year = math.sqrt(365.25 * 24.0 * 3600.0 / token_grid.step_s)
    breakeven = sd_s / (2.0 * sd_m) if sd_m > 0 else float("nan")
    return QuoteAssetResult(
        token=token_label,
        n=n,
        span_days=(common[-1] - common[0]) / 86400.0,
        rho=rho,
        rho_ci_low=quantile(rhos, 0.025),
        rho_ci_high=quantile(rhos, 0.975),
        sigma_meme_hourly=sd_m,
        sigma_sol_hourly=sd_s,
        sigma_meme_annual=sd_m * per_year,
        sigma_sol_annual=sd_s * per_year,
        breakeven_rho=breakeven,
        passes_breakeven=bool(rho > breakeven),
        var_in_sol=var_sol,
        var_in_usd=var_usd,
        variance_reduction=1.0 - var_sol / var_usd if var_usd > 0 else float("nan"),
        variance_reduction_ci_low=quantile(reductions, 0.025),
        variance_reduction_ci_high=quantile(reductions, 0.975),
    )


# --------------------------------------------------------------------------------------
# The bid-ask-bounce control
# --------------------------------------------------------------------------------------


def load_chain_mid(path: Path) -> dict[str, list[tuple[int, float]]]:
    """Marginal price from exact integer vault balances — no bid-ask bounce by construction."""

    out: dict[str, list[tuple[int, float]]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("kind") != "chain_mid":
                continue
            quote_raw = int(row["quote_raw"])
            base_raw = int(row["base_raw"])
            # base units per quote unit, both scaled out of raw integers only at the last step
            price = (quote_raw / 10 ** int(row["quote_decimals"])) / (
                base_raw / 10 ** int(row["base_decimals"])
            )
            ts = int(datetime.fromisoformat(row["t_event"]).timestamp())
            out.setdefault(row["series"], []).append((ts, price))
    for series in out:
        out[series].sort()
    return out


@dataclass(frozen=True, slots=True)
class BounceControl:
    series: str
    step_s: int
    n_trade_price: int
    n_chain_mid: int
    rho1_trade_price: float
    rho1_chain_mid: float
    implied_bounce_share: float


def bounce_control(
    gt_candles: Sequence[Candle], chain: Sequence[tuple[int, float]], series: str, step_s: int
) -> BounceControl | None:
    """Compare first-order autocorrelation on trade prices vs chain marginal prices.

    Roll's model: a trade price bouncing across an effective spread ``s`` contributes
    ``-s^2/4`` to the first return autocovariance. If the trade-price series is materially
    more negatively autocorrelated than the marginal-price series over the same window, the
    reversion this study might otherwise report is microstructure and not a tradeable ratio.
    """

    if not chain or len(gt_candles) < 8:
        return None
    lo = max(min(t for t, _ in chain), gt_candles[0].t)
    hi = min(max(t for t, _ in chain), gt_candles[-1].t)
    if hi - lo < 4 * step_s:
        return None
    window_gt = [c for c in gt_candles if lo <= c.t <= hi]
    window_chain = [Candle(t, p) for t, p in chain if lo <= t <= hi]
    if len(window_gt) < 8 or len(window_chain) < 8:
        return None
    grid_gt = build_grid(window_gt, step_s, f"{series}:trade")
    grid_chain = build_grid(window_chain, step_s, f"{series}:mid")
    if grid_gt.n < 8 or grid_chain.n < 8:
        return None
    rho_trade = autocorrelation(grid_gt.returns, 1)
    rho_mid = autocorrelation(grid_chain.returns, 1)
    share = float("nan")
    if not math.isnan(rho_trade) and not math.isnan(rho_mid) and rho_trade < 0:
        share = max(0.0, (rho_mid - rho_trade)) / abs(rho_trade)
    return BounceControl(
        series=series,
        step_s=step_s,
        n_trade_price=grid_gt.n,
        n_chain_mid=grid_chain.n,
        rho1_trade_price=rho_trade,
        rho1_chain_mid=rho_mid,
        implied_bounce_share=share,
    )


# --------------------------------------------------------------------------------------
# Replication of the desk's one prior positive reversion claim
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ar1Replication:
    pair: str
    n: int
    span_days: float
    rho_hat: float
    rho_debiased: float
    half_life_hours: float
    null_mean: float
    null_q05: float
    null_q50: float
    p_random_walk: float
    verdict: str


def ar1_level_coefficient(log_price: Sequence[float]) -> float:
    """OLS AR(1) on the log-ratio LEVEL — the statistic ``RESULT_swing_cluster.md`` reported."""

    n = len(log_price)
    if n < 8:
        return float("nan")
    x = log_price[:-1]
    y = log_price[1:]
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0.0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sxx


def replicate_ar1_claim(
    grid: Grid,
    replicates: int,
    seed: int,
    estimator: Any = ar1_level_coefficient,
) -> Ar1Replication:
    """Re-run ``RESULT_swing_cluster.md``'s AR(1) half-life against a simulated null.

    That study reported DREGG/SOLVE at ``rho_hat = 0.901``, Kendall-debiased to 0.908, a
    half-life of 6.6 -> 7.2 hours, and called it "robust reversion" — the only positive
    reversion result this desk has. It had no null: ``rho_hat`` was compared with 1 by eye.

    But **the OLS AR(1) coefficient is biased downward on a random walk**, severely and
    asymmetrically, which is the entire content of the Dickey-Fuller literature. A number
    below 1 is therefore not evidence of anything until you know what a unit root would have
    produced at this ``n``. The null here is a random walk built by cumulating
    wild-bootstrapped increments of the real series, so it carries the real volatility path
    and the real empty bars, and differs from the observed series only in having no reversion
    at all.

    One direction has to be flagged: observation noise (the fee bounce) biases the AR(1)
    coefficient *down*, and this null has none, so it is **anti-conservative** — it makes
    reversion easier to claim, not harder. The size of that bias is measured separately by
    :func:`bounce_control`.
    """

    rho = estimator(grid.log_price)
    n = grid.n
    # Kendall's small-sample debias, exactly as the prior study applied it.
    debiased = rho + (1.0 + 3.0 * rho) / n if n > 0 else float("nan")
    half_life = (
        -math.log(2.0) / math.log(rho) * grid.step_s / 3600.0 if 0.0 < rho < 1.0 else float("inf")
    )
    rng = subrng(seed, "ar1-replication", grid.label)
    returns = grid.returns
    null: list[float] = []
    for _ in range(replicates):
        increments = wild_bootstrap(returns, rng)
        level = [grid.log_price[0]]
        for step in increments:
            level.append(level[-1] + step)
        null.append(estimator(level))
    clean = [v for v in null if not math.isnan(v)]
    # One-sided: the claim is that rho is BELOW what a random walk would give.
    p = (sum(1 for v in clean if v <= rho) + 1) / (len(clean) + 1) if clean else float("nan")
    return Ar1Replication(
        pair=grid.label,
        n=n,
        span_days=grid.span_days,
        rho_hat=rho,
        rho_debiased=debiased,
        half_life_hours=half_life,
        null_mean=_mean_clean(null),
        null_q05=quantile(null, 0.05),
        null_q50=quantile(null, 0.50),
        p_random_walk=p,
        verdict="REVERTING" if p < 0.05 else "INDISTINGUISHABLE-FROM-RANDOM-WALK",
    )


# --------------------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------------------

TRENDING: Final[str] = "TRENDING"
REVERTING: Final[str] = "REVERTING"
RANDOM_WALK: Final[str] = "INDISTINGUISHABLE-FROM-RANDOM-WALK"
UNRESOLVABLE: Final[str] = "UNRESOLVABLE-AT-THIS-N"


@dataclass(frozen=True, slots=True)
class HorizonVerdict:
    pair: str
    horizon_hours: float
    verdict: str
    vr: float
    z_robust: float
    p: float
    survives_fdr: bool
    independent_spans: float
    reason: str


def verdict_for(vr: VarianceRatio, step_s: int, survives_fdr: bool) -> HorizonVerdict:
    """One verdict per horizon.

    UNRESOLVABLE fires on either of two conditions, and the second matters more than the first.
    Too few non-overlapping spans is the obvious one. The subtle one is that the minimum
    detectable variance ratio can fall **below the estimator's own floor** of ``1/q`` — the
    value a perfectly reverting AR(1) would produce — in which case no mean reversion of any
    speed was detectable and "indistinguishable from a random walk" would be a false comfort.
    It implies the test had a chance. It did not.
    """

    horizon_hours = vr.q * step_s / 3600.0
    floor = 1.0 / vr.q
    if vr.independent_spans < MIN_INDEPENDENT_SPANS:
        label = UNRESOLVABLE
        reason = (
            f"only {vr.independent_spans:.1f} non-overlapping {horizon_hours:.1f}h spans exist "
            f"in the sample; below the pre-registered floor of {MIN_INDEPENDENT_SPANS}"
        )
    elif math.isnan(vr.mde_vr) or vr.mde_vr <= floor:
        label = UNRESOLVABLE
        reason = (
            f"the smallest detectable variance ratio at 80% power is {vr.mde_vr:.3f}, at or "
            f"below the estimator's floor of 1/q = {floor:.3f} — no mean reversion of ANY "
            f"speed would have been visible at this horizon (null centred on "
            f"{vr.null_mean:.3f}, sd {vr.null_sd:.3f})"
        )
    elif math.isnan(vr.z_robust):
        label = UNRESOLVABLE
        reason = "the heteroskedasticity-robust variance estimate is degenerate"
    elif not survives_fdr:
        label = RANDOM_WALK
        reason = (
            f"VR={vr.vr:.3f} against a null centred on {vr.null_mean:.3f}, robust z="
            f"{vr.z_robust:+.2f}, bootstrap p={vr.p_bootstrap:.3f}; does not survive BH-FDR "
            f"at q={FDR_Q}"
        )
    elif vr.vr < 1.0:
        label = REVERTING
        reason = f"VR={vr.vr:.3f} < 1, robust z={vr.z_robust:+.2f}, survives BH-FDR"
    else:
        label = TRENDING
        reason = f"VR={vr.vr:.3f} > 1, robust z={vr.z_robust:+.2f}, survives BH-FDR"
    return HorizonVerdict(
        pair="",
        horizon_hours=horizon_hours,
        verdict=label,
        vr=vr.vr,
        z_robust=vr.z_robust,
        p=vr.p_bootstrap,
        survives_fdr=survives_fdr,
        independent_spans=vr.independent_spans,
        reason=reason,
    )


def overall_verdict(horizon_verdicts: Sequence[HorizonVerdict], day_scale_hours: float = 24.0) -> str:
    """One verdict per pair, decided on the horizons the LP thesis is actually about.

    The claim under test is day-to-few-day reversion, so a 2-hour result cannot settle it in
    either direction. If every day-scale horizon is unresolvable the pair is UNRESOLVABLE even
    when the intraday horizons are decisive — reporting the intraday answer as though it
    settled the daily question is precisely the substitution this study exists to avoid.
    """

    day_scale = [v for v in horizon_verdicts if v.horizon_hours >= day_scale_hours]
    if not day_scale or all(v.verdict == UNRESOLVABLE for v in day_scale):
        return UNRESOLVABLE
    resolved = [v for v in day_scale if v.verdict != UNRESOLVABLE]
    if any(v.verdict == REVERTING for v in resolved) and not any(
        v.verdict == TRENDING for v in resolved
    ):
        return REVERTING
    if any(v.verdict == TRENDING for v in resolved) and not any(
        v.verdict == REVERTING for v in resolved
    ):
        return TRENDING
    if any(v.verdict in (REVERTING, TRENDING) for v in resolved):
        return "MIXED-BY-HORIZON"
    return RANDOM_WALK


# --------------------------------------------------------------------------------------
# Instrument checks: both controls, run every time
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    world: str
    statistic: str
    n_worlds: int
    rejections: int
    rejection_rate: float
    median_value: float
    correct_direction: int
    expectation: str
    passed: bool


#: The instrument check is a SIZE-AND-POWER check over several independent draws, not a single
#: draw. One draw at alpha=0.05 across three statistics cries wolf about once in seven runs,
#: which makes a flaky control worse than none; and a single non-rejection is not evidence of
#: correct size either. Five worlds at alpha=0.05: P(>=2 rejections | true null) = 1.2%.
CONTROL_WORLDS: Final[int] = 5
CONTROL_ALPHA: Final[float] = 0.05
#: Known-zero passes if at most this fraction of draws reject; known-effect if at least
#: ``CONTROL_MIN_POWER`` do, with the sign right every time.
CONTROL_MAX_SIZE: Final[float] = 0.2
CONTROL_MIN_POWER: Final[float] = 0.8


def run_controls(
    template: Grid,
    replicates: int,
    seed: int,
    half_life_bars: float = 3.0,
    n_worlds: int = CONTROL_WORLDS,
) -> list[ControlOutcome]:
    """Known-ZERO and known-EFFECT worlds, both shaped like the real series.

    PROGRAM.md §3.12: an estimator that detects nothing passes a zero-control perfectly, so a
    green zero-control certifies a broken estimator exactly as readily as a working one. This
    project has been bitten twice. Both worlds therefore run every time, in the study itself
    and not only in the test suite, and each is judged on a rejection *rate* over several
    independent draws rather than on one coin flip.

    The zero world is a permutation of the real magnitudes with random signs: it keeps the
    real fat tails and the real empty bars (a zero magnitude stays zero under any sign) and
    removes only the serial structure. The effect world is an OU log-price with the real
    empty-bar pattern imposed, so a green effect control cannot be an artifact of missingness.
    """

    returns = template.returns
    n = len(returns)
    magnitudes = [abs(r) for r in returns]
    sigma = statistics.pstdev(returns) if n > 1 else 0.01
    stale = template.stale[1:]
    # Four half-lives out: far enough that a reverting series has fully reverted, so the
    # variance ratio is near its asymptote rather than halfway up the curve.
    q = max(2, round(4 * half_life_bars))
    null_draws = max(100, replicates // 4)
    hurst_draws = max(48, replicates // 16)

    statistics_under_test: tuple[tuple[str, Any, Any, int], ...] = (
        (f"VR(q={q})", lambda r: variance_ratio(r, q), lambda v: v < 1.0, null_draws),
        ("rho(1)", lambda r: autocorrelation(r, 1), lambda v: v < 0.0, null_draws),
        ("H_dfa", hurst_dfa, lambda v: v < 0.5, hurst_draws),
    )

    out: list[ControlOutcome] = []
    for world, expect_reject in (("known-zero", False), ("known-effect", True)):
        for name, estimator, is_reverting, draws in statistics_under_test:
            rejections = 0
            correct = 0
            values: list[float] = []
            for w in range(n_worlds):
                rng = subrng(seed, "control", template.label, world, name, w)
                series = (
                    simulate_random_walk(n, magnitudes, rng)
                    if world == "known-zero"
                    else simulate_ou(n, half_life_bars, sigma, rng, stale=stale)
                )
                value = estimator(series)
                null = [estimator(wild_bootstrap(series, rng)) for _ in range(draws)]
                p = empirical_p(value, null)
                values.append(value)
                if p < CONTROL_ALPHA:
                    rejections += 1
                    if is_reverting(value):
                        correct += 1
            rate = rejections / n_worlds
            passed = (
                rate >= CONTROL_MIN_POWER and correct == rejections
                if expect_reject
                else rate <= CONTROL_MAX_SIZE
            )
            out.append(
                ControlOutcome(
                    world=world,
                    statistic=name,
                    n_worlds=n_worlds,
                    rejections=rejections,
                    rejection_rate=rate,
                    median_value=statistics.median(values),
                    correct_direction=correct,
                    expectation=(
                        f"reject in >={CONTROL_MIN_POWER:.0%} of draws, reverting sign"
                        if expect_reject
                        else f"reject in <={CONTROL_MAX_SIZE:.0%} of draws"
                    ),
                    passed=passed,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


@dataclass
class PairReport:
    pair: str
    grid: str
    step_s: int
    n_bars: int
    n_returns: int
    span_days: float
    stale_fraction: float
    variance_ratios: list[VarianceRatio] = field(default_factory=list)
    hurst: list[HurstResult] = field(default_factory=list)
    autocorrelation: list[AcfResult] = field(default_factory=list)
    horizon_verdicts: list[HorizonVerdict] = field(default_factory=list)
    verdict: str = UNRESOLVABLE


def build_series_grids(
    candles: dict[tuple[str, str], list[Candle]], grid_name: str, step_s: int
) -> dict[str, Grid]:
    return {
        series: build_grid(rows, step_s, series)
        for (series, name), rows in candles.items()
        if name == grid_name
    }


def run_study(
    cache: Path, seed: int, replicates: int, hurst_replicates: int
) -> dict[str, Any]:
    candles = load_gt_cache(cache / "gt_ohlcv.jsonl")
    chain = load_chain_mid(cache / "chain_mid.jsonl")

    report: dict[str, Any] = {
        "seed": seed,
        "replicates": replicates,
        "hurst_replicates": hurst_replicates,
        "fdr_q": FDR_Q,
        "helius_credits_spent": 0,
        "grids": {},
        "pairs": [],
        "quote_asset": [],
        "bounce_control": [],
        "controls": [],
        "replication": [],
        "fdr": {},
    }

    grids_1h = build_series_grids(candles, "hour1", 3600)
    grids_5m = build_series_grids(candles, "minute5", 300)
    grids_1m = build_series_grids(candles, "minute1", 60)

    for name, grids in (("hour1", grids_1h), ("minute5", grids_5m), ("minute1", grids_1m)):
        report["grids"][name] = {
            series: {
                "bars": grid.n,
                "span_days": round(grid.span_days, 3),
                "stale_fraction": round(grid.stale_fraction, 4),
                "first": grid.times[0] if grid.times else None,
                "last": grid.times[-1] if grid.times else None,
            }
            for series, grid in sorted(grids.items())
        }

    confirmatory_p: dict[str, float] = {}
    #: The 5-minute grid is EXPLORATORY and corrected separately. Folding it into the
    #: confirmatory family would let an intraday microstructure effect — which is what a
    #: 10-minute variance ratio on a fee-bounced trade price mostly measures — buy or spend
    #: multiplicity budget belonging to the day-scale question that was actually asked.
    exploratory_p: dict[str, float] = {}
    pair_reports: list[PairReport] = []

    for grid_name, grids, horizons, step_s in (
        ("hour1", grids_1h, VR_HORIZONS_HOURLY, 3600),
        ("minute5", grids_5m, VR_HORIZONS_5MIN, 300),
    ):
        for label, numerator, denominator in CONFIRMATORY_PAIRS:
            if numerator not in grids or (denominator is not None and denominator not in grids):
                continue
            grid = (
                grids[numerator]
                if denominator is None
                else ratio_grid(grids[numerator], grids[denominator], label)
            )
            if grid.n < 64:
                continue
            grid = Grid(label, grid.step_s, grid.times, grid.log_price, grid.stale)
            hourly = grid_name == "hour1"
            # The 5-minute grid carries ~12x the bars, so its null quantiles are far tighter
            # at the same replicate count; a smaller budget there buys the same precision on
            # the quantities that decide anything. Hurst and the autocorrelation bands are
            # computed on the hourly grid only — the day-scale question is the one being
            # asked, and a Hurst exponent fitted over 5-minute scales is a statement about
            # microstructure that the bounce control already answers more directly.
            vrs = analyse_variance_ratios(
                grid, horizons, replicates if hourly else max(250, replicates // 8), seed
            )
            hursts = analyse_hurst(grid, hurst_replicates, seed) if hourly else []
            acfs = (
                analyse_autocorrelation(grid, ACF_LAGS_HOURLY, replicates, seed, mean_block=24.0)
                if hourly
                else []
            )
            pr = PairReport(
                pair=label,
                grid=grid_name,
                step_s=step_s,
                n_bars=grid.n,
                n_returns=grid.n - 1,
                span_days=grid.span_days,
                stale_fraction=grid.stale_fraction,
                variance_ratios=vrs,
                hurst=hursts,
                autocorrelation=acfs,
            )
            pair_reports.append(pr)
            family = confirmatory_p if grid_name == "hour1" else exploratory_p
            unit = "h" if grid_name == "hour1" else "x5min"
            for vr in vrs:
                # The BOOTSTRAP p, not the asymptotic one. On these series the simulated null
                # is not centred on 1 (see VarianceRatio.shuffled_null_mean), so the asymptotic
                # reference distribution is simply the wrong distribution and is
                # anti-conservative in the reverting direction. Reported side by side; only
                # this one is corrected and only this one decides a verdict.
                family[f"VR|{label}|q={vr.q}{unit}"] = vr.p_bootstrap
            for h in hursts:
                family[f"H|{label}|{h.estimator}|{grid_name}"] = h.wild_p
            for a in acfs:
                family[f"ACF|{label}|lag={a.lag}h"] = a.p_bootstrap

    # The desk's one prior positive reversion claim, re-run with a null. NOT pre-registered
    # and NOT one of the pairs the operator trades: it is here to test a belief that already
    # existed, and it is corrected separately for exactly that reason.
    replication_p: dict[str, float] = {}
    for label, numerator, denominator in REPLICATION_PAIRS:
        if numerator not in grids_1h or denominator not in grids_1h:
            continue
        grid = ratio_grid(grids_1h[numerator], grids_1h[denominator], label)
        if grid.n < 64:
            continue
        replication = replicate_ar1_claim(grid, replicates, seed)
        report["replication"].append(asdict(replication))
        replication_p[f"AR1-level|{label}"] = replication.p_random_walk
        rep_vrs = analyse_variance_ratios(grid, VR_HORIZONS_HOURLY, replicates, seed)
        report["replication_vr"] = [asdict(v) for v in rep_vrs]
        for vr in rep_vrs:
            replication_p[f"VR|{label}|q={vr.q}h"] = vr.p_bootstrap

    bh = benjamini_hochberg(confirmatory_p, FDR_Q)
    rejected = {o.name for o in bh if o.rejected}
    bh_exploratory = benjamini_hochberg(exploratory_p, FDR_Q)
    rejected |= {o.name for o in bh_exploratory if o.rejected}
    report["fdr"] = {
        "family": "confirmatory (hourly grid): 4 pairs x (7 VR horizons + 3 Hurst + 3 ACF)",
        "n_hypotheses": len(confirmatory_p),
        "q": FDR_Q,
        "n_rejected": sum(1 for o in bh if o.rejected),
        "outcomes": [asdict(o) for o in sorted(bh, key=lambda o: (o.rank == 0, o.rank))],
    }
    report["fdr_exploratory"] = {
        "family": "exploratory (5-minute grid): 4 pairs x 8 VR horizons",
        "n_hypotheses": len(exploratory_p),
        "q": FDR_Q,
        "n_rejected": sum(1 for o in bh_exploratory if o.rejected),
        "outcomes": [
            asdict(o) for o in sorted(bh_exploratory, key=lambda o: (o.rank == 0, o.rank))
        ],
    }

    bh_replication = benjamini_hochberg(replication_p, FDR_Q)
    # The strictest reading available: charge the replication to the confirmatory family's
    # multiplicity budget as though it had been pre-registered alongside it. If a result
    # survives THAT, the "it was not pre-registered" objection is the only one left.
    bh_combined = benjamini_hochberg({**confirmatory_p, **replication_p}, FDR_Q)
    report["fdr_replication"] = {
        "family": "replication (not pre-registered): DREGG/SOLVE, 7 VR horizons + 1 AR(1) level",
        "n_hypotheses": len(replication_p),
        "q": FDR_Q,
        "n_rejected": sum(1 for o in bh_replication if o.rejected),
        "outcomes": [asdict(o) for o in sorted(bh_replication, key=lambda o: (o.rank == 0, o.rank))],
    }
    report["fdr_combined"] = {
        "family": "confirmatory + replication charged to one budget",
        "n_hypotheses": len(confirmatory_p) + len(replication_p),
        "q": FDR_Q,
        "n_rejected": sum(1 for o in bh_combined if o.rejected),
        "rejected": sorted(o.name for o in bh_combined if o.rejected),
    }

    for pr in pair_reports:
        verdicts: list[HorizonVerdict] = []
        unit = "h" if pr.grid == "hour1" else "x5min"
        for vr in pr.variance_ratios:
            key = f"VR|{pr.pair}|q={vr.q}{unit}"
            hv = verdict_for(vr, pr.step_s, key in rejected)
            verdicts.append(
                HorizonVerdict(
                    pair=pr.pair,
                    horizon_hours=hv.horizon_hours,
                    verdict=hv.verdict,
                    vr=hv.vr,
                    z_robust=hv.z_robust,
                    p=hv.p,
                    survives_fdr=hv.survives_fdr,
                    independent_spans=hv.independent_spans,
                    reason=hv.reason,
                )
            )
        pr.horizon_verdicts = verdicts
        pr.verdict = overall_verdict(verdicts)
        report["pairs"].append(asdict(pr))

    # Quote-asset break-even, on the hourly grid where the SOL leg is dense.
    sol_grid = grids_1h.get("sol_per_usd")
    if sol_grid is not None:
        for token_label, series in (
            ("weave", "weave_per_sol"),
            ("nosis", "nosis_per_sol"),
            ("DREGG", "dregg_per_sol"),
            ("SOLVE", "solve_per_sol"),
        ):
            grid = grids_1h.get(series)
            if grid is None:
                continue
            result = analyse_quote_asset(token_label, grid, sol_grid, replicates, seed, 24.0)
            if result is not None:
                report["quote_asset"].append(asdict(result))

    # Microstructure control against the chain marginal price.
    for series, rows in sorted(chain.items()):
        for grid_name, step_s in (("minute1", 60), ("minute5", 300)):
            gt = candles.get((series, grid_name))
            if not gt:
                continue
            control = bounce_control(gt, rows, series, step_s)
            if control is not None:
                report["bounce_control"].append(asdict(control))

    # Instrument checks, shaped like the longest real series available.
    template = grids_1h.get("dregg_per_sol")
    if template is not None and template.n > 64:
        report["controls"] = [asdict(c) for c in run_controls(template, replicates, seed)]

    return report


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("=" * 100)
    add("MEAN REVERSION IN THE CLUSTER RATIOS")
    add(f"seed={report['seed']}  replicates={report['replicates']}  BH-FDR q={report['fdr_q']}")
    add("=" * 100)

    add("\n-- grids (n at every stage) " + "-" * 60)
    for grid_name, series in report["grids"].items():
        add(f"  {grid_name}:")
        for name, info in series.items():
            add(
                f"    {name:16s} bars={info['bars']:6d}  span={info['span_days']:7.2f}d  "
                f"stale={info['stale_fraction']:6.1%}"
            )

    add("\n-- controls (both worlds, every run) " + "-" * 50)
    for control in report["controls"]:
        mark = "PASS" if control["passed"] else "FAIL"
        add(
            f"  [{mark}] {control['world']:13s} {control['statistic']:10s} "
            f"rejected {control['rejections']}/{control['n_worlds']} draws  "
            f"median={control['median_value']:+.4f}  right sign in {control['correct_direction']}"
            f"  expected: {control['expectation']}"
        )

    add("\n-- variance ratios, hourly grid " + "-" * 55)
    for pair in report["pairs"]:
        if pair["grid"] != "hour1":
            continue
        add(
            f"\n  {pair['pair']}  n={pair['n_returns']} returns  span={pair['span_days']:.2f}d  "
            f"stale={pair['stale_fraction']:.1%}   VERDICT: {pair['verdict']}"
        )
        add(
            f"    {'q(h)':>5s} {'VR':>7s} {'null mu':>8s} {'shuf mu':>8s} {'z_homo':>7s} "
            f"{'z_rob':>6s} {'p_asym':>7s} {'p_boot':>7s} {'spans':>7s} {'MDE VR':>7s} "
            f"{'HL seen':>9s}  verdict"
        )
        for vr, hv in zip(pair["variance_ratios"], pair["horizon_verdicts"], strict=True):
            half_life = vr["mde_half_life_hours"]
            hl = (
                "none"
                if vr["mde_vr"] <= 0
                else ("instant" if half_life == 0 else f"{half_life:.1f}h")
            )
            add(
                f"    {vr['q']:5d} {vr['vr']:7.3f} {vr['null_mean']:8.3f} "
                f"{vr['shuffled_null_mean']:8.3f} {vr['z_homoskedastic']:+7.2f} "
                f"{vr['z_robust']:+6.2f} {vr['p_asymptotic']:7.4f} {vr['p_bootstrap']:7.4f} "
                f"{vr['independent_spans']:7.1f} {vr['mde_vr']:7.3f} {hl:>9s}  {hv['verdict']}"
            )

    add("\n-- Hurst, hourly grid (with the null at THIS L) " + "-" * 40)
    for pair in report["pairs"]:
        if pair["grid"] != "hour1":
            continue
        add(f"\n  {pair['pair']}  (L={pair['n_returns']})")
        for h in pair["hurst"]:
            add(
                f"    {h['estimator']:4s} H={h['h']:6.3f}   wild null {h['wild_null_mean']:6.3f}"
                f"+-{h['wild_null_sd']:5.3f} p={h['wild_p']:.3f}   white null "
                f"{h['white_null_mean']:6.3f}+-{h['white_null_sd']:5.3f} p={h['white_p']:.3f}"
                f"   detectable only beyond +-{h['mde_h']:.3f}"
            )

    add("\n-- return autocorrelation " + "-" * 62)
    for pair in report["pairs"]:
        if pair["grid"] != "hour1":
            continue
        add(f"\n  {pair['pair']}")
        for a in pair["autocorrelation"]:
            add(
                f"    lag={a['lag']:3d}h  rho={a['rho']:+.4f}  "
                f"null 95% [{a['null_q025']:+.4f},{a['null_q975']:+.4f}]  "
                f"block-boot CI [{a['ci_low']:+.4f},{a['ci_high']:+.4f}]  p={a['p_bootstrap']:.4f}  "
                f"spans={a['independent_spans']:.1f}  MDE=+-{a['mde_rho']:.3f}"
            )

    add("\n-- FDR " + "-" * 80)
    add(
        f"  {report['fdr']['n_hypotheses']} confirmatory hypotheses, BH at q={report['fdr']['q']}: "
        f"{report['fdr']['n_rejected']} rejected"
    )
    for outcome in report["fdr"]["outcomes"][:12]:
        mark = "REJECT" if outcome["rejected"] else "      "
        add(
            f"    {mark} rank {outcome['rank']:3d}  p={outcome['p']:.5f}  "
            f"thr={outcome['threshold']:.5f}  {outcome['name']}"
        )
    exploratory = report.get("fdr_exploratory")
    if exploratory:
        add(
            f"\n  {exploratory['n_hypotheses']} exploratory hypotheses (5-minute grid), BH at "
            f"q={exploratory['q']}: {exploratory['n_rejected']} rejected"
        )
        for outcome in exploratory["outcomes"][:12]:
            mark = "REJECT" if outcome["rejected"] else "      "
            add(
                f"    {mark} rank {outcome['rank']:3d}  p={outcome['p']:.5f}  "
                f"thr={outcome['threshold']:.5f}  {outcome['name']}"
            )

    add("\n-- variance ratios, 5-minute grid (exploratory) " + "-" * 40)
    for pair in report["pairs"]:
        if pair["grid"] != "minute5":
            continue
        add(
            f"\n  {pair['pair']}  n={pair['n_returns']} returns  span={pair['span_days']:.2f}d  "
            f"stale={pair['stale_fraction']:.1%}"
        )
        for vr, hv in zip(pair["variance_ratios"], pair["horizon_verdicts"], strict=True):
            add(
                f"    q={vr['q'] * 5:5d}min  VR={vr['vr']:6.3f}  null mu={vr['null_mean']:6.3f}  "
                f"shuf mu={vr['shuffled_null_mean']:6.3f}  z_rob={vr['z_robust']:+6.2f}  "
                f"p_asym={vr['p_asymptotic']:7.4f}  p_boot={vr['p_bootstrap']:7.4f}  {hv['verdict']}"
            )

    add("\n-- quote asset: SOL vs a stablecoin " + "-" * 52)
    add(
        f"    {'token':8s} {'n':>5s} {'span':>7s} {'rho':>7s} {'rho CI':>18s} {'rho*':>7s} "
        f"{'sd_meme':>9s} {'sd_SOL':>8s} {'var cut':>9s}  side"
    )
    for q in report["quote_asset"]:
        side = "PASSES" if q["passes_breakeven"] else "FAILS"
        add(
            f"    {q['token']:8s} {q['n']:5d} {q['span_days']:6.1f}d {q['rho']:+7.3f} "
            f"[{q['rho_ci_low']:+.3f},{q['rho_ci_high']:+.3f}] {q['breakeven_rho']:7.3f} "
            f"{q['sigma_meme_annual']:8.1%} {q['sigma_sol_annual']:7.1%} "
            f"{q['variance_reduction']:+8.1%}  {side}"
        )

    add("\n-- replication: RESULT_swing_cluster.md's AR(1) reversion claim " + "-" * 22)
    for rep in report.get("replication", []):
        add(
            f"    {rep['pair']:14s} n={rep['n']:5d} ({rep['span_days']:.1f}d)  "
            f"rho_hat={rep['rho_hat']:.4f} (debiased {rep['rho_debiased']:.4f})  "
            f"half-life={rep['half_life_hours']:.1f}h"
        )
        add(
            f"    {'':14s} random-walk null: median {rep['null_q50']:.4f}, 5th pct "
            f"{rep['null_q05']:.4f}   one-sided p={rep['p_random_walk']:.4f}   {rep['verdict']}"
        )
    rejected_rep = set(report.get("fdr_combined", {}).get("rejected", ()))
    for vr in report.get("replication_vr", []):
        mark = "SURVIVES-COMBINED-FDR" if f"VR|DREGG/SOLVE|q={vr['q']}h" in rejected_rep else ""
        add(
            f"      VR(q={vr['q']:3d}h)={vr['vr']:6.3f}  z_rob={vr['z_robust']:+6.2f}  "
            f"p={vr['p_asymptotic']:.4f}  p_boot={vr['p_bootstrap']:.4f}  "
            f"spans={vr['independent_spans']:7.1f}  {mark}"
        )
    rep_fdr = report.get("fdr_replication")
    if rep_fdr:
        add(
            f"      BH within the replication family ({rep_fdr['n_hypotheses']} tests): "
            f"{rep_fdr['n_rejected']} rejected"
        )
    combined = report.get("fdr_combined")
    if combined:
        add(
            f"      BH charged to the confirmatory budget ({combined['n_hypotheses']} tests): "
            f"{combined['n_rejected']} rejected -> {combined['rejected']}"
        )

    add("\n-- bid-ask-bounce control (trade price vs chain marginal price) " + "-" * 20)
    for control in report["bounce_control"]:
        add(
            f"    {control['series']:16s} step={control['step_s']:4d}s  "
            f"rho1(trade)={control['rho1_trade_price']:+.4f} (n={control['n_trade_price']})  "
            f"rho1(mid)={control['rho1_chain_mid']:+.4f} (n={control['n_chain_mid']})"
        )

    add("\n-- verdicts " + "-" * 76)
    for pair in report["pairs"]:
        if pair["grid"] != "hour1":
            continue
        add(f"    {pair['pair']:14s} {pair['verdict']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--replicates", type=int, default=2000)
    parser.add_argument("--hurst-replicates", type=int, default=400)
    parser.add_argument("--quick", action="store_true", help="200/64 replicates; same code path")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    replicates = 200 if args.quick else args.replicates
    hurst_replicates = 64 if args.quick else args.hurst_replicates

    if not (args.cache / "gt_ohlcv.jsonl").exists():
        parser.error(
            f"no price cache at {args.cache}. Run: "
            "uv run python scripts/fetch_mean_reversion_data.py"
        )

    report = run_study(args.cache, args.seed, replicates, hurst_replicates)
    out = args.out or (args.cache / "results.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(format_report(report))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
