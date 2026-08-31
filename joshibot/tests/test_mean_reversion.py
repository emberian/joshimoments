"""Tests for the mean-reversion study, built the way PROGRAM.md §3.12 demands.

**Both controls, always.** A *known-zero* world (a martingale difference carrying the real
kind of clustered fat tails), a *known-effect* world (an Ornstein-Uhlenbeck log-price with a
stated half-life) and a *known-effect of the opposite sign* (fractionally integrated noise
with H = 0.8). The zero world alone is worthless — a constant estimator passes it perfectly,
and this project has shipped exactly that failure twice.

**And every control is falsified.** For each check below there is a deliberately broken
estimator and a test that the check *fails* against it. Two of the checks were rewritten
because their first version could not be falsified: a bootstrap p-value computed with the
same broken estimator on both sides is self-consistent no matter how wrong the estimator is,
so the zero-world checks now assert where the statistic *sits*, not only that its own null
agrees with it. :func:`test_falsification_matrix_covers_every_control` fails if a control is
added without a mutation.
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
import statistics

import pytest

from studies import mean_reversion as mr

N = 1500
HALF_LIFE = 3.0
#: 4x the half-life: far enough out that a mean-reverting series has fully reverted, so the
#: variance ratio is near its asymptote rather than halfway up the curve.
EFFECT_Q = int(4 * HALF_LIFE)


# --------------------------------------------------------------------------------------
# The three synthetic worlds
# --------------------------------------------------------------------------------------


def _clustered_magnitudes(rng: random.Random, n: int) -> list[float]:
    """Two-state volatility regime, 3x in sigma. A Gaussian control would be too easy: the
    real series are clustered and fat-tailed, and an estimator that only survives Gaussian
    noise has not been tested against anything this desk owns."""

    out: list[float] = []
    hot = False
    for _ in range(n):
        if rng.random() < 0.02:
            hot = not hot
        out.append(abs(rng.gauss(0.0, 0.03 if hot else 0.01)))
    return out


def _fractionally_integrated(n: int, d: float, rng: random.Random, lags: int = 400) -> list[float]:
    """Long-memory noise with ``H = d + 1/2`` — the known-effect world of the opposite sign.

    An AR(1) would not do: its memory dies within a few bars, so DFA over scales of 8-375
    returns 0.5 and the "trending" control would be vacuous. Fractional integration has
    genuine power-law memory, which is the property being detected.
    """

    psi = [1.0]
    for k in range(1, lags + 1):
        psi.append(psi[-1] * (k - 1 + d) / k)
    eps = [rng.gauss(0.0, 1.0) for _ in range(n + lags)]
    return [
        sum(psi[k] * eps[t + lags - k] for k in range(lags + 1)) * 0.02 for t in range(n)
    ]


@pytest.fixture(scope="module")
def worlds() -> dict[str, list[float]]:
    magnitudes = _clustered_magnitudes(random.Random(11), N)
    return {
        "zero": mr.simulate_random_walk(N, magnitudes, random.Random(12)),
        "effect": mr.simulate_ou(N, HALF_LIFE, 0.02, random.Random(13)),
        "trend": _fractionally_integrated(N, 0.3, random.Random(14)),
    }


# --------------------------------------------------------------------------------------
# The checks. Each takes the estimator it exercises as a defaulted argument, so a broken
# variant can be substituted verbatim by the falsification matrix at the bottom.
# --------------------------------------------------------------------------------------


def check_vr_zero_world(worlds, variance_ratio=mr.variance_ratio) -> None:
    """KNOWN-ZERO: the variance ratio of a martingale difference is 1 at every horizon.

    Both halves matter. ``p > 0.05`` alone is a self-consistency check that any estimator
    passes against its own bootstrap; the assertion that the *null itself* is centred on 1 is
    what makes this a statement about the estimator.
    """

    returns = worlds["zero"]
    for q in (2, 5, 20, 50):
        vr = variance_ratio(returns, q)
        rng = random.Random(100 + q)
        null = [variance_ratio(mr.wild_bootstrap(returns, rng), q) for _ in range(250)]
        null_mean = statistics.fmean(null)
        assert abs(null_mean - 1.0) < 0.15, (
            f"q={q}: the variance-ratio null is centred on {null_mean:.3f}, not on 1 — the "
            f"estimator is not a variance ratio"
        )
        p = mr.empirical_p(vr, null)
        assert p > 0.05, f"zero world rejected at q={q}: VR={vr:.3f} p={p:.4f}"


def check_vr_effect_world(worlds, variance_ratio=mr.variance_ratio) -> None:
    """KNOWN-EFFECT: an OU log-price gives VR < 1, and it is detected."""

    returns = worlds["effect"]
    vr = variance_ratio(returns, EFFECT_Q)
    rng = random.Random(200)
    null = [variance_ratio(mr.wild_bootstrap(returns, rng), EFFECT_Q) for _ in range(250)]
    p = mr.empirical_p(vr, null)
    assert vr < 1.0, f"OU world did not produce VR<1: {vr:.3f}"
    assert p < 0.01, f"OU world not detected: VR={vr:.3f} p={p:.4f}"


def check_vr_trend_world(worlds, variance_ratio=mr.variance_ratio) -> None:
    """KNOWN-EFFECT, opposite sign: long memory gives VR > 1, and it is detected."""

    returns = worlds["trend"]
    vr = variance_ratio(returns, EFFECT_Q)
    rng = random.Random(300)
    null = [variance_ratio(mr.wild_bootstrap(returns, rng), EFFECT_Q) for _ in range(250)]
    p = mr.empirical_p(vr, null)
    assert vr > 1.0, f"trending world did not produce VR>1: {vr:.3f}"
    assert p < 0.01, f"trending world not detected: VR={vr:.3f} p={p:.4f}"


def check_hurst_zero_world(worlds, estimator=mr.hurst_dfa) -> None:
    """KNOWN-ZERO: Hurst sits at 1/2, judged against its own simulated null width."""

    returns = worlds["zero"]
    h = estimator(returns)
    rng = random.Random(400)
    null = [estimator(mr.wild_bootstrap(returns, rng)) for _ in range(60)]
    sd = statistics.pstdev([v for v in null if not math.isnan(v)])
    assert abs(h - 0.5) < 4 * sd + 0.05, f"zero world H={h:.3f} against null sd {sd:.3f}"


def check_hurst_effect_world(worlds, estimator=mr.hurst_dfa) -> None:
    """KNOWN-EFFECT: OU pushes Hurst below 1/2 and out of its null band."""

    returns = worlds["effect"]
    h = estimator(returns)
    rng = random.Random(500)
    null = [estimator(mr.wild_bootstrap(returns, rng)) for _ in range(60)]
    p = mr.empirical_p(h, null)
    assert h < 0.5, f"OU world H={h:.3f} is not below 0.5"
    assert p < 0.05, f"OU world H={h:.3f} not distinguished from its null (p={p:.3f})"


def check_hurst_trend_world(worlds, estimator=mr.hurst_dfa) -> None:
    """KNOWN-EFFECT, opposite sign: fractional integration at d=0.3 must read above 1/2."""

    returns = worlds["trend"]
    h = estimator(returns)
    assert h > 0.55, f"trending world (true H=0.80) read H={h:.3f}"


def check_acf_zero_world(worlds, autocorrelation=mr.autocorrelation) -> None:
    returns = worlds["zero"]
    rho = autocorrelation(returns, 1)
    rng = random.Random(600)
    null = [autocorrelation(mr.wild_bootstrap(returns, rng), 1) for _ in range(300)]
    sd = statistics.pstdev([v for v in null if not math.isnan(v)])
    assert abs(rho) < 4 * sd + 0.02, f"zero world rho1={rho:+.4f} against null sd {sd:.4f}"
    assert mr.empirical_p(rho, null) > 0.05, f"zero world rho1={rho:+.4f} rejected"


def check_acf_effect_world(worlds, autocorrelation=mr.autocorrelation) -> None:
    returns = worlds["effect"]
    rho = autocorrelation(returns, 1)
    rng = random.Random(700)
    null = [autocorrelation(mr.wild_bootstrap(returns, rng), 1) for _ in range(300)]
    p = mr.empirical_p(rho, null)
    assert rho < 0.0, f"OU world rho1={rho:+.4f} is not negative"
    assert p < 0.01, f"OU world rho1={rho:+.4f} not detected (p={p:.4f})"


def check_acf_removes_the_mean(autocorrelation=mr.autocorrelation) -> None:
    """A drifting series is still serially uncorrelated. Forgetting to subtract the mean turns
    the drift itself into an autocorrelation of nearly +1 — the most common ACF bug there is,
    and one that would read as "trending" on every series in this study."""

    rng = random.Random(750)
    returns = [0.05 + rng.gauss(0.0, 0.01) for _ in range(1000)]
    rho = autocorrelation(returns, 1)
    assert abs(rho) < 0.15, f"a constant drift produced rho1={rho:+.4f}; the mean is not removed"


def check_wild_bootstrap_preserves_volatility(bootstrap=mr.wild_bootstrap) -> None:
    """The null must keep ``|r_t|`` exactly, or it is not a heteroskedasticity-preserving null
    and the reported null width is the width of some other process."""

    rng = random.Random(800)
    magnitudes = _clustered_magnitudes(random.Random(801), 500)
    returns = [m if rng.random() < 0.5 else -m for m in magnitudes]
    resampled = bootstrap(returns, random.Random(802))
    assert [abs(r) for r in resampled] == [abs(r) for r in returns], (
        "the wild bootstrap changed the magnitude sequence, so volatility clustering and the "
        "empty-bar pattern are no longer preserved under the null"
    )


def check_wild_bootstrap_randomises(bootstrap=mr.wild_bootstrap) -> None:
    """...and it must actually randomise, or every replicate is the estimate and no effect can
    ever be detected."""

    returns = [1.0] * 400
    flipped = bootstrap(returns, random.Random(850))
    negatives = sum(1 for r in flipped if r < 0)
    assert 120 < negatives < 280, f"{negatives}/400 signs flipped; this is not a sign randomisation"


def check_block_bootstrap_preserves_clustering(bootstrap=mr.stationary_block_bootstrap) -> None:
    """A CI bootstrap must keep the clustering an iid resample destroys."""

    magnitudes = _clustered_magnitudes(random.Random(900), 3000)
    signs = random.Random(901)
    returns = [m if signs.random() < 0.5 else -m for m in magnitudes]
    observed = mr.autocorrelation([abs(r) for r in returns], 1)

    # Averaged over draws: an iid resample's |r| autocorrelation is 0 +- 1/sqrt(n), so a
    # single pair of draws decides this check by coin flip about a fifth of the time. That is
    # not a weaker assertion, it is the same assertion actually being measured.
    rng = random.Random(902)
    block_rhos = [
        mr.autocorrelation([abs(r) for r in bootstrap(returns, rng, 50.0)], 1) for _ in range(12)
    ]
    iid_rhos = []
    for _ in range(12):
        iid = [returns[rng.randrange(len(returns))] for _ in range(len(returns))]
        iid_rhos.append(mr.autocorrelation([abs(r) for r in iid], 1))
    block_rho = statistics.fmean(block_rhos)
    iid_rho = statistics.fmean(iid_rhos)

    assert observed > 0.05, "the fixture is not clustered; the check would be vacuous"
    assert block_rho > iid_rho + 0.02, (
        f"block bootstrap retained no more clustering than an iid resample "
        f"({block_rho:.3f} vs {iid_rho:.3f} averaged over 12 draws)"
    )


def check_bh_controls_fdr(procedure=mr.benjamini_hochberg) -> None:
    """Under a complete null the realised discovery count must stay near zero."""

    rng = random.Random(1000)
    discoveries = 0
    trials = 300
    for _ in range(trials):
        pvalues = {f"h{i}": rng.random() for i in range(40)}
        discoveries += sum(1 for o in procedure(pvalues, 0.10) if o.rejected)
    # Every rejection here is false by construction. No correction at all makes ~q*m = 4.
    assert discoveries / trials < 1.0, (
        f"{discoveries / trials:.2f} false discoveries per complete-null trial; the "
        f"multiplicity correction is not doing anything"
    )


def check_bh_rejects_real_effects(procedure=mr.benjamini_hochberg) -> None:
    """...and it must still have power, or "controls FDR" is satisfied by rejecting nothing."""

    pvalues = {f"real{i}": 1e-8 for i in range(10)}
    pvalues.update({f"null{i}": 0.4 + 0.01 * i for i in range(30)})
    rejected = {o.name for o in procedure(pvalues, 0.10) if o.rejected}
    assert rejected == {f"real{i}" for i in range(10)}, f"BH rejected {sorted(rejected)}"


def check_robust_z_beats_homoskedastic(z_statistics=mr._vr_z_statistics) -> None:
    """The reason the robust statistic exists: under heteroskedastic noise with no serial
    dependence at all, ``z`` over-rejects and ``z*`` does not. Measured, not asserted."""

    homo = 0
    robust = 0
    trials = 120
    for i in range(trials):
        rng = random.Random(2000 + i)
        magnitudes = _clustered_magnitudes(rng, 600)
        returns = [m if rng.random() < 0.5 else -m for m in magnitudes]
        vr = mr.variance_ratio(returns, 8)
        z_homo, z_robust = z_statistics(returns, 8, vr)
        homo += abs(z_homo) > 1.96
        if not math.isnan(z_robust):
            robust += abs(z_robust) > 1.96
    homo_rate, robust_rate = homo / trials, robust / trials
    assert robust_rate < homo_rate, (
        f"the robust statistic did not reject less often than the homoskedastic one "
        f"({robust_rate:.3f} vs {homo_rate:.3f}) — it is not doing its job"
    )
    assert robust_rate <= 0.15, f"robust size {robust_rate:.3f} is far above nominal 0.05"


def _level_grid(returns, label="synthetic"):
    """Turn a return series into a Grid whose log price is its cumulative sum."""

    level = [0.0]
    for r in returns:
        level.append(level[-1] + r)
    return mr.Grid(
        label,
        3600,
        tuple(3600 * i for i in range(len(level))),
        tuple(level),
        (False,) * len(level),
    )


def check_ar1_zero_world(worlds, estimator=mr.ar1_level_coefficient) -> None:
    """KNOWN-ZERO for the replication estimator: a random walk's OLS AR(1) coefficient sits
    just below 1, and the study must NOT call it reversion.

    This is the check ``RESULT_swing_cluster.md`` never ran. Its rho_hat = 0.901 was compared
    with 1 by eye, and the OLS coefficient is biased downward on a unit root — so "below 1"
    carries no information until the null has been simulated.
    """

    grid = _level_grid(worlds["zero"])
    rho = estimator(grid.log_price)
    assert 0.9 < rho <= 1.05, f"a random walk's AR(1) coefficient read {rho:.4f}"
    result = mr.replicate_ar1_claim(grid, 200, seed=31, estimator=estimator)
    assert result.p_random_walk > 0.05, (
        f"the replication test rejected a random walk: rho={result.rho_hat:.4f} "
        f"p={result.p_random_walk:.4f}"
    )


def check_ar1_effect_world(worlds, estimator=mr.ar1_level_coefficient) -> None:
    """KNOWN-EFFECT: an OU level with a 3-bar half-life must be rejected against that null, and
    the recovered half-life must be near 3 hours on an hourly grid."""

    grid = _level_grid(worlds["effect"])
    result = mr.replicate_ar1_claim(grid, 200, seed=32, estimator=estimator)
    assert result.rho_hat < 0.95, f"OU level read rho={result.rho_hat:.4f}"
    assert result.p_random_walk < 0.05, (
        f"OU reversion not detected: rho={result.rho_hat:.4f} p={result.p_random_walk:.4f}"
    )
    assert 1.5 < result.half_life_hours < 6.0, (
        f"recovered half-life {result.half_life_hours:.2f}h, true 3.0h"
    )


def _vr_null_means(magnitudes, q, rng, shuffler, draws=150):
    """Return (null mean with the volatility profile IN PLACE, null mean after shuffling)."""

    in_place = [
        mr.variance_ratio([m if rng.random() < 0.5 else -m for m in magnitudes], q)
        for _ in range(draws)
    ]
    shuffled = []
    for _ in range(draws):
        pool = list(magnitudes)
        shuffler(pool, rng)
        shuffled.append(mr.variance_ratio([m if rng.random() < 0.5 else -m for m in pool], q))
    return statistics.fmean(in_place), statistics.fmean(shuffled)


def _shuffle_in_time(pool, rng):
    rng.shuffle(pool)


def check_volatility_profile_diagnostic(shuffler=_shuffle_in_time) -> None:
    """The diagnostic that decides which p-value this study is allowed to use.

    A young memecoin's volatility is front-loaded, and the overlapping variance-ratio estimator
    underweights returns near the sample boundary — so its null drifts BELOW 1 and every
    asymptotic test reads that as mean reversion. The diagnostic is a time-shuffle: identical
    magnitudes, identical marginal distribution, only the temporal profile destroyed. If the
    drift is caused by the profile, shuffling removes it.

    KNOWN-EFFECT here is a front-loaded series (the null must drift down and shuffling must fix
    it) and KNOWN-ZERO is a flat one (neither null may move).
    """

    n, q = 900, 72
    rng = random.Random(5150)
    front_loaded = [abs(rng.gauss(0.0, 30.0 if i < n // 12 else 1.0)) for i in range(n)]
    flat = [abs(rng.gauss(0.0, 1.0)) for _ in range(n)]

    hot_place, hot_shuffled = _vr_null_means(front_loaded, q, random.Random(5151), shuffler)
    assert hot_place < 0.90, (
        f"a front-loaded volatility profile did not bias the variance-ratio null downward "
        f"(null mean {hot_place:.3f}); the diagnostic has nothing to detect"
    )
    assert hot_shuffled > 0.93, (
        f"time-shuffling the SAME magnitudes left the null at {hot_shuffled:.3f}, so the drift "
        f"is not attributable to the volatility profile and the diagnostic is not diagnostic"
    )
    assert hot_shuffled - hot_place > 0.05, (hot_place, hot_shuffled)

    flat_place, flat_shuffled = _vr_null_means(flat, q, random.Random(5152), shuffler)
    assert abs(flat_place - 1.0) < 0.10, f"flat profile null drifted to {flat_place:.3f}"
    assert abs(flat_shuffled - 1.0) < 0.10, f"flat profile shuffled null {flat_shuffled:.3f}"


def check_quote_asset_breakeven_direction(analyse=mr.analyse_quote_asset) -> None:
    """A token engineered to be MORE volatile in SOL must be reported as failing break-even."""

    rng = random.Random(1200)
    n = 1200
    times = tuple(3600 * i for i in range(n))
    sol_lp = [0.0]
    meme_lp = [0.0]
    for _ in range(n - 1):
        # The token's SOL-quoted price moves AGAINST SOL/USD, which is the regime where a
        # stablecoin quote would have been the safer numeraire.
        step = rng.gauss(0.0, 0.01)
        sol_lp.append(sol_lp[-1] + step)
        meme_lp.append(meme_lp[-1] + rng.gauss(0.0, 0.02) - 1.5 * step)
    token = mr.Grid("meme", 3600, times, tuple(meme_lp), (False,) * n)
    sol = mr.Grid("sol", 3600, times, tuple(sol_lp), (False,) * n)
    result = analyse("meme", token, sol, 100, 7, 24.0)
    assert result is not None
    assert not result.passes_breakeven, f"rho={result.rho:.3f} rho*={result.breakeven_rho:.3f}"
    assert result.variance_reduction < 0.0, (
        f"variance in SOL should be HIGHER here; reduction={result.variance_reduction:+.3f}"
    )


def check_quote_asset_identity() -> None:
    """``Var[r_usd] - Var[r_sol] = sigma_SOL^2 + 2 Cov[r_sol, r_SOL/USD]`` must hold exactly.

    This identity is why the study leads with the variance comparison rather than with rho:
    bid-ask-bounce noise sits in both variances and cancels in the difference, while it
    attenuates rho and inflates sigma_meme.
    """

    rng = random.Random(1100)
    r_su = [rng.gauss(0.0, 0.01) for _ in range(2000)]
    r_ms = [rng.gauss(0.0, 0.05) - 0.3 * s for s in r_su]
    r_mu = [a + b for a, b in zip(r_ms, r_su, strict=True)]
    mean_ms = statistics.fmean(r_ms)
    mean_su = statistics.fmean(r_su)
    cov = sum((a - mean_ms) * (b - mean_su) for a, b in zip(r_ms, r_su, strict=True)) / len(r_ms)
    lhs = statistics.pvariance(r_mu) - statistics.pvariance(r_ms)
    rhs = statistics.pvariance(r_su) + 2 * cov
    assert abs(lhs - rhs) < 1e-9, f"identity broken: {lhs:.10f} vs {rhs:.10f}"


# --------------------------------------------------------------------------------------
# The controls, run for real
# --------------------------------------------------------------------------------------


def test_known_zero_variance_ratio(worlds):
    check_vr_zero_world(worlds)


def test_known_effect_variance_ratio(worlds):
    check_vr_effect_world(worlds)


def test_known_effect_opposite_sign_variance_ratio(worlds):
    check_vr_trend_world(worlds)


@pytest.mark.parametrize("estimator", [mr.hurst_dfa, mr.hurst_rs])
def test_known_zero_hurst(worlds, estimator):
    check_hurst_zero_world(worlds, estimator)


@pytest.mark.parametrize("estimator", [mr.hurst_dfa, mr.hurst_rs])
def test_known_effect_hurst(worlds, estimator):
    check_hurst_effect_world(worlds, estimator)


@pytest.mark.parametrize("estimator", [mr.hurst_dfa, mr.hurst_rs])
def test_known_effect_opposite_sign_hurst(worlds, estimator):
    check_hurst_trend_world(worlds, estimator)


def test_known_zero_autocorrelation(worlds):
    check_acf_zero_world(worlds)


def test_known_effect_autocorrelation(worlds):
    check_acf_effect_world(worlds)


def test_autocorrelation_removes_the_mean():
    check_acf_removes_the_mean()


def test_wild_bootstrap_preserves_volatility():
    check_wild_bootstrap_preserves_volatility()


def test_wild_bootstrap_randomises():
    check_wild_bootstrap_randomises()


def test_block_bootstrap_preserves_clustering():
    check_block_bootstrap_preserves_clustering()


def test_bh_controls_fdr():
    check_bh_controls_fdr()


def test_bh_rejects_real_effects():
    check_bh_rejects_real_effects()


def test_robust_z_beats_homoskedastic():
    check_robust_z_beats_homoskedastic()


def test_known_zero_ar1_replication(worlds):
    check_ar1_zero_world(worlds)


def test_known_effect_ar1_replication(worlds):
    check_ar1_effect_world(worlds)


def test_volatility_profile_diagnostic():
    check_volatility_profile_diagnostic()


def test_quote_asset_identity():
    check_quote_asset_identity()


def test_quote_asset_breakeven_direction():
    check_quote_asset_breakeven_direction()


def test_gph_is_the_noisy_estimator():
    """Weron (2002) on our own code: GPH's white-noise spread is several times DFA's and
    R/S's at the same length, which is exactly why a bare GPH number cannot support a claim
    and why this study reports three estimators rather than one."""

    rng = random.Random(1300)
    length = 1024
    spreads = {}
    for name in ("dfa", "rs", "gph"):
        estimator = mr.HURST_FUNCTIONS[name]
        draws = [estimator([rng.gauss(0.0, 1.0) for _ in range(length)]) for _ in range(30)]
        spreads[name] = statistics.pstdev([d for d in draws if not math.isnan(d)])
    assert spreads["gph"] > 2 * max(spreads["dfa"], spreads["rs"]), spreads
    assert 0.02 < spreads["dfa"] < 0.15, spreads
    assert 0.05 < spreads["gph"] < 0.40, spreads


def test_run_controls_reports_both_worlds():
    """The study's own in-run instrument check must pass BOTH worlds, not just the zero one."""

    magnitudes = _clustered_magnitudes(random.Random(1400), 1200)
    returns = mr.simulate_random_walk(1200, magnitudes, random.Random(1401))
    log_price = [0.0]
    for r in returns:
        log_price.append(log_price[-1] + r)
    grid = mr.Grid(
        "synthetic",
        3600,
        tuple(3600 * i for i in range(len(log_price))),
        tuple(log_price),
        (False,) * len(log_price),
    )
    outcomes = mr.run_controls(grid, replicates=250, seed=7, n_worlds=4)
    assert {o.world for o in outcomes} == {"known-zero", "known-effect"}
    assert {o.statistic for o in outcomes} == {"VR(q=12)", "rho(1)", "H_dfa"}
    failures = [o for o in outcomes if not o.passed]
    assert not failures, [
        f"{o.world}/{o.statistic} rejected {o.rejections}/{o.n_worlds} "
        f"median={o.median_value:+.4f} (expected {o.expectation})"
        for o in failures
    ]


# --------------------------------------------------------------------------------------
# Plumbing: the parts that would silently corrupt every number above
# --------------------------------------------------------------------------------------


def test_grid_forward_fill_marks_stale():
    grid = mr.build_grid([mr.Candle(0, 1.0), mr.Candle(60, 2.0), mr.Candle(240, 4.0)], 60, "x")
    assert grid.times == (0, 60, 120, 180, 240)
    assert grid.stale == (False, False, True, True, False)
    assert grid.stale_fraction == pytest.approx(0.4)
    # Forward-filled bars contribute EXACTLY zero return, which is what makes the wild
    # bootstrap's preservation of |r| also a preservation of the missingness pattern.
    assert grid.returns[1] == pytest.approx(0.0)
    assert grid.returns[2] == pytest.approx(0.0)


def test_ratio_grid_is_a_difference_of_logs():
    a = mr.build_grid([mr.Candle(0, 2.0), mr.Candle(60, 8.0)], 60, "a")
    b = mr.build_grid([mr.Candle(0, 1.0), mr.Candle(60, 2.0)], 60, "b")
    ratio = mr.ratio_grid(a, b, "a/b")
    assert ratio.log_price[0] == pytest.approx(math.log(2.0))
    assert ratio.log_price[1] == pytest.approx(math.log(4.0))


def test_ratio_grid_stale_if_either_leg_is_stale():
    a = mr.build_grid([mr.Candle(0, 1.0), mr.Candle(60, 1.0), mr.Candle(120, 1.0)], 60, "a")
    b = mr.build_grid([mr.Candle(0, 1.0), mr.Candle(120, 1.0)], 60, "b")
    assert mr.ratio_grid(a, b, "a/b").stale == (False, True, False)


def test_subrng_is_deterministic_and_order_independent():
    first = mr.subrng(5, "vr", "weave/SOL", 3600, 24).random()
    other = mr.subrng(5, "vr", "DREGG/SOL", 3600, 24).random()
    assert first == mr.subrng(5, "vr", "weave/SOL", 3600, 24).random()
    assert first != other


def test_empirical_p_is_never_zero():
    assert mr.empirical_p(100.0, [0.0] * 50) == pytest.approx(1 / 51)


def test_verdict_is_unresolvable_when_spans_are_thin():
    vr = mr.VarianceRatio(
        q=24, vr=0.4, z_homoskedastic=-9.0, z_robust=-9.0, p_asymptotic=1e-12,
        p_bootstrap=1e-3, null_mean=1.0, null_sd=0.1, null_q05=0.8, null_q95=1.2,
        n_returns=100, independent_spans=100 / 24, mde_vr=0.72,
        mde_half_life_hours=mr.half_life_for_variance_ratio(0.72, 24, 3600),
        shuffled_null_mean=1.0,
    )
    # Overwhelming evidence at a horizon the sample cannot support is still UNRESOLVABLE.
    assert mr.verdict_for(vr, 3600, survives_fdr=True).verdict == mr.UNRESOLVABLE


def test_verdict_is_unresolvable_when_nothing_was_detectable():
    """The subtler trigger: plenty of spans, but the minimum detectable variance ratio sits
    below the estimator's own floor of 1/q, so no reversion of any speed could have been seen.
    Calling that "indistinguishable from a random walk" implies the test had a chance."""

    vr = mr.VarianceRatio(
        q=24, vr=0.53, z_homoskedastic=-1.3, z_robust=-1.1, p_asymptotic=0.28,
        p_bootstrap=0.44, null_mean=0.817, null_sd=0.3315, null_q05=0.35, null_q95=1.42,
        n_returns=245, independent_spans=245 / 24,
        mde_vr=1.0 - mr.MDE_Z * 0.3315 / 0.817,
        mde_half_life_hours=0.0, shuffled_null_mean=1.0,
    )
    assert vr.independent_spans > mr.MIN_INDEPENDENT_SPANS, "the span trigger must not fire"
    verdict = mr.verdict_for(vr, 3600, survives_fdr=False)
    assert verdict.verdict == mr.UNRESOLVABLE, verdict.reason
    assert "floor" in verdict.reason


def test_verdict_is_random_walk_when_the_sample_did_have_power():
    vr = mr.VarianceRatio(
        q=12, vr=0.95, z_homoskedastic=-0.4, z_robust=-0.3, p_asymptotic=0.75,
        p_bootstrap=0.80, null_mean=0.970, null_sd=0.10, null_q05=0.80, null_q95=1.15,
        n_returns=1140, independent_spans=95.0,
        mde_vr=1.0 - mr.MDE_Z * 0.10 / 0.970,
        mde_half_life_hours=4.0, shuffled_null_mean=1.0,
    )
    assert mr.verdict_for(vr, 3600, survives_fdr=False).verdict == mr.RANDOM_WALK


def test_mde_half_life_inverts_the_ar1_variance_ratio():
    """The power statement has to be right or "we could not have seen it" is decoration."""

    for half_life_hours in (2.0, 6.0, 24.0, 100.0):
        phi = 2.0 ** (-1.0 / half_life_hours)
        for q in (12, 24, 48):
            vr = mr.ar1_variance_ratio(phi, q)
            assert mr.half_life_for_variance_ratio(vr, q, 3600) == pytest.approx(
                half_life_hours, rel=1e-6
            )
    assert mr.half_life_for_variance_ratio(1.0, 24, 3600) == math.inf
    assert mr.half_life_for_variance_ratio(0.5, 24, 3600) > 0.0


def test_overall_verdict_ignores_intraday_when_daily_is_unresolvable():
    """The substitution this study exists to avoid: a decisive 2h result reported as though it
    settled the day-to-few-day question."""

    intraday = mr.HorizonVerdict(
        pair="p", horizon_hours=2.0, verdict=mr.REVERTING, vr=0.5, z_robust=-8.0, p=1e-9,
        survives_fdr=True, independent_spans=500.0, reason="",
    )
    daily = mr.HorizonVerdict(
        pair="p", horizon_hours=24.0, verdict=mr.UNRESOLVABLE, vr=0.7, z_robust=-1.0, p=0.3,
        survives_fdr=False, independent_spans=4.0, reason="",
    )
    assert mr.overall_verdict([intraday, daily]) == mr.UNRESOLVABLE


def test_chain_mid_price_is_built_from_integer_reserves(tmp_path):
    path = tmp_path / "chain_mid.jsonl"
    path.write_text(
        json.dumps(
            {
                "kind": "chain_mid",
                "series": "weave_per_sol",
                "quote_raw": "178926813721",
                "quote_decimals": 9,
                "base_raw": "103132910247782",
                "base_decimals": 6,
                "t_event": "2026-08-14T00:00:34+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    loaded = mr.load_chain_mid(path)
    expected = (178926813721 / 10**9) / (103132910247782 / 10**6)
    assert loaded["weave_per_sol"][0][1] == pytest.approx(expected, rel=1e-12)


def test_variance_ratio_refuses_a_horizon_longer_than_the_sample():
    with pytest.raises(ValueError):
        mr.variance_ratio([0.1, -0.1, 0.2], 10)


def test_run_study_end_to_end_corrects_the_bootstrap_p(tmp_path):
    """Integration: the multiplicity correction must be applied to the BOOTSTRAP p-value.

    This is not a style preference. On these series the simulated null is not centred on 1, so
    the asymptotic Lo-MacKinlay reference distribution is the wrong distribution and is
    anti-conservative in the reverting direction. A regression that quietly swapped the two
    back would turn every null in this study into a finding, and nothing else in the suite
    would notice.
    """

    rng = random.Random(4242)
    rows = []
    start = 1_780_000_000 - 1_780_000_000 % 3600
    for series in ("weave_per_sol", "nosis_per_sol", "dregg_per_sol", "solve_per_sol", "sol_per_usd"):
        price = 1.0
        for i in range(400):
            price *= math.exp(rng.gauss(0.0, 0.02))
            rows.append(
                json.dumps(
                    {
                        "kind": "ohlcv",
                        "series": series,
                        "pool": "test",
                        "label": series,
                        "timeframe": "hour",
                        "aggregate": 1,
                        "t_event": start + 3600 * i,
                        "close": repr(price),
                    }
                )
            )
    cache = tmp_path
    (cache / "gt_ohlcv.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = mr.run_study(cache, seed=5, replicates=60, hurst_replicates=16)

    by_name = {o["name"]: o["p"] for o in report["fdr"]["outcomes"]}
    checked = 0
    for pair in report["pairs"]:
        if pair["grid"] != "hour1":
            continue
        for vr in pair["variance_ratios"]:
            name = f"VR|{pair['pair']}|q={vr['q']}h"
            if name not in by_name:
                continue
            checked += 1
            assert by_name[name] == pytest.approx(vr["p_bootstrap"]), (
                f"{name} was corrected on p={by_name[name]:.5f}; the bootstrap p is "
                f"{vr['p_bootstrap']:.5f} and the asymptotic p is {vr['p_asymptotic']:.5f}"
            )
    assert checked >= 20, f"only {checked} variance-ratio hypotheses reached the FDR family"
    # And the run must have produced its own instrument checks rather than skipping them.
    assert report["controls"], "run_study produced no controls"
    assert report["helius_credits_spent"] == 0


def test_hypothesis_family_is_the_pre_registered_size():
    """§3.9 trials accounting: the effective number of hypotheses must be computable from the
    pre-registration, not guessed after the fact."""

    expected = len(mr.CONFIRMATORY_PAIRS) * (
        len(mr.VR_HORIZONS_HOURLY) + len(mr.HURST_ESTIMATORS) + len(mr.ACF_LAGS_HOURLY)
    )
    assert expected == 52


# --------------------------------------------------------------------------------------
# THE FALSIFICATION MATRIX
# --------------------------------------------------------------------------------------


def _vr_always_one(returns, q):
    """The classic vacuous estimator: reports "random walk" whatever the data says."""

    if q < 2 or len(returns) <= q:
        raise ValueError("n > q >= 2")
    return 1.0


def _vr_no_overlap_correction(returns, q):
    """Drops Lo-MacKinlay's ``m = q(n-q+1)(1-q/n)`` correction for the raw block count."""

    n = len(returns)
    mu = sum(returns) / n
    var_1 = sum((r - mu) ** 2 for r in returns) / (n - 1)
    prefix = [0.0]
    for r in returns:
        prefix.append(prefix[-1] + r)
    acc = sum((prefix[t] - prefix[t - q] - q * mu) ** 2 for t in range(q, n + 1))
    return (acc / (n - q + 1)) / var_1


def _hurst_always_half(returns):
    return 0.5


def _dfa_on_prices_not_returns(returns):
    """Feeds the LOG PRICE where the estimator expects returns, so the series is integrated
    twice and H comes back around 1.5.

    This replaced a first attempt that removed DFA's local polynomial detrending. That
    mutation did not falsify anything, and the reason is worth keeping: detrending changes the
    constant in ``F(s)``, not the exponent, so DFA-0 still reads H = 1/2 on a random walk. The
    mutation that actually breaks the zero-world check is the one that changes the order of
    integration — which is also the commonest way to misuse a Hurst estimator in practice."""

    price = []
    total = 0.0
    for r in returns:
        total += r
        price.append(total)
    return mr.hurst_dfa(price)


def _acf_always_negative(returns, lag):
    return -0.5


def _acf_always_zero(returns, lag):
    return 0.0


def _acf_uncentred(returns, lag):
    """Forgets to subtract the mean — turns any drift into an autocorrelation near +1."""

    n = len(returns)
    if lag <= 0 or n <= lag + 1:
        return float("nan")
    denom = sum(r * r for r in returns)
    if denom <= 0.0:
        return float("nan")
    return sum(returns[t] * returns[t - lag] for t in range(lag, n)) / denom


def _ar1_always_one(log_price):
    """Reports a unit root whatever the data says — the vacuous direction for this estimator."""

    return 1.0


def _ar1_always_half(log_price):
    """Reports violent reversion whatever the data says."""

    return 0.5


def _shuffle_nothing(pool, rng):
    """A "shuffle" that leaves the order alone, so the diagnostic can no longer attribute the
    drift to anything."""

    return None


def _bootstrap_identity(returns, rng):
    """A null that does not randomise: every replicate equals the estimate, so nothing is
    ever detectable and every p-value is 1."""

    return list(returns)


def _bootstrap_iid_resample(returns, rng):
    """Resamples with replacement, which destroys the magnitude sequence and with it the
    volatility clustering the null is supposed to preserve."""

    return [returns[rng.randrange(len(returns))] for _ in returns]


def _block_bootstrap_iid(returns, rng, mean_block):
    """Mean block length forced to 1 — exactly the clustering the CI needed."""

    return mr.stationary_block_bootstrap(returns, rng, 1.0)


def _bh_no_correction(pvalues, q):
    return [
        mr.BHOutcome(name=name, p=p, rank=0, threshold=q, rejected=p <= q)
        for name, p in pvalues.items()
    ]


def _bh_reject_nothing(pvalues, q):
    return [
        mr.BHOutcome(name=name, p=p, rank=0, threshold=q, rejected=False)
        for name, p in pvalues.items()
    ]


def _z_homoskedastic_twice(returns, q, vr):
    """Puts the homoskedastic statistic in the robust slot — the exact bug the study warns
    about, and the one that would make every heteroskedastic series look mean-reverting."""

    n = len(returns)
    z = math.sqrt(n) * (vr - 1.0) / math.sqrt(2.0 * (2 * q - 1) * (q - 1) / (3.0 * q))
    return z, z


def _quote_asset_flipped(token_label, token_grid, sol_grid, replicates, seed, mean_block):
    """Compares the break-even the wrong way round: ``rho < rho*`` instead of ``rho > rho*``."""

    result = mr.analyse_quote_asset(token_label, token_grid, sol_grid, replicates, seed, mean_block)
    if result is None:
        return None
    return dataclasses.replace(
        result,
        passes_breakeven=not result.passes_breakeven,
        variance_reduction=-result.variance_reduction,
    )


#: (id, the check it must break, the mutation, what the mutation does).
FALSIFICATIONS = (
    ("vr_vacuous_vs_effect", "check_vr_effect_world", _vr_always_one, "VR hard-coded to 1"),
    ("vr_vacuous_vs_trend", "check_vr_trend_world", _vr_always_one, "VR hard-coded to 1"),
    (
        "vr_missing_overlap_correction",
        "check_vr_zero_world",
        _vr_no_overlap_correction,
        "Lo-MacKinlay's m correction dropped, so the null is no longer centred on 1",
    ),
    (
        "hurst_vacuous_vs_effect",
        "check_hurst_effect_world",
        _hurst_always_half,
        "H hard-coded to 0.5",
    ),
    (
        "hurst_vacuous_vs_trend",
        "check_hurst_trend_world",
        _hurst_always_half,
        "H hard-coded to 0.5",
    ),
    (
        "dfa_fed_prices_not_returns",
        "check_hurst_zero_world",
        _dfa_on_prices_not_returns,
        "log price passed where returns are expected (integrated twice)",
    ),
    (
        "acf_always_negative_vs_zero",
        "check_acf_zero_world",
        _acf_always_negative,
        "rho hard-coded to -0.5",
    ),
    ("acf_vacuous_vs_effect", "check_acf_effect_world", _acf_always_zero, "rho hard-coded to 0"),
    ("acf_uncentred", "check_acf_removes_the_mean", _acf_uncentred, "mean not subtracted"),
    (
        "wild_bootstrap_iid",
        "check_wild_bootstrap_preserves_volatility",
        _bootstrap_iid_resample,
        "resamples with replacement, destroying the magnitude sequence",
    ),
    (
        "wild_bootstrap_identity",
        "check_wild_bootstrap_randomises",
        _bootstrap_identity,
        "does not randomise at all",
    ),
    (
        "block_bootstrap_iid",
        "check_block_bootstrap_preserves_clustering",
        _block_bootstrap_iid,
        "mean block length forced to 1",
    ),
    ("bh_no_correction", "check_bh_controls_fdr", _bh_no_correction, "raw p<=q, no step-up"),
    ("bh_reject_nothing", "check_bh_rejects_real_effects", _bh_reject_nothing, "never rejects"),
    (
        "robust_z_is_homoskedastic",
        "check_robust_z_beats_homoskedastic",
        _z_homoskedastic_twice,
        "robust slot filled with the homoskedastic statistic",
    ),
    (
        "shuffle_that_does_not_shuffle",
        "check_volatility_profile_diagnostic",
        _shuffle_nothing,
        "the time-shuffle leaves the order untouched",
    ),
    ("ar1_vacuous_vs_effect", "check_ar1_effect_world", _ar1_always_one, "AR(1) rho fixed at 1"),
    ("ar1_always_reverting", "check_ar1_zero_world", _ar1_always_half, "AR(1) rho fixed at 0.5"),
    (
        "quote_asset_breakeven_flipped",
        "check_quote_asset_breakeven_direction",
        _quote_asset_flipped,
        "break-even comparison inverted",
    ),
)


@pytest.mark.parametrize(
    ("check_name", "mutation"),
    [(entry[1], entry[2]) for entry in FALSIFICATIONS],
    ids=[entry[0] for entry in FALSIFICATIONS],
)
def test_falsification(worlds, check_name, mutation):
    """Break the estimator; the control that certifies it must now FAIL."""

    check = globals()[check_name]
    with pytest.raises(AssertionError):
        if check_name.endswith("_world"):
            check(worlds, mutation)
        else:
            check(mutation)


def test_falsification_matrix_covers_every_control():
    """A control cannot be added without a mutation that breaks it."""

    checks = {name for name in globals() if name.startswith("check_")}
    covered = {entry[1] for entry in FALSIFICATIONS}
    # An algebraic identity has no estimator to break; it is exact or it is not.
    covered |= {"check_quote_asset_identity"}
    assert not checks - covered, f"controls with no falsification: {sorted(checks - covered)}"
