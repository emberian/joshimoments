"""Tests for the callout->flow ESTIMATOR itself, not for the finding.

The finding on the live store is a null, and a null is only worth reporting if the instrument
that produced it can be shown to work. So every positive test here is paired with a
**falsification**: the same test re-run against a deliberately broken estimator, asserting that
the test FAILS. A test that passes for a broken estimator has no content, and this repo has
already shipped one vacuous green check; ``test_*_has_teeth`` is the guard against a second.

Two synthetic regimes:

* ``KNOWN-ZERO`` -- arrivals are an inhomogeneous Poisson process with a strong diurnal profile
  and no dependence on callouts whatsoever. The pipeline must not find an effect. This is the
  regime where an *unmatched* baseline manufactures one out of time-of-day alone, so it is also
  the test that proves hour matching is doing real work.
* ``KNOWN-EFFECT`` -- the same process with a multiplicative bump applied inside the post window.
  The pipeline must recover the injected log rate ratio.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import pytest

from shitcoims_tape.schema import Callout, Side, Trade
from studies.callout_flow import (
    FDR_Q,
    VERDICT_NULL,
    VERDICT_SUGGESTIVE,
    VERDICT_UNRESOLVABLE,
    CalloutEvent,
    Coverage,
    MintCounts,
    StudyError,
    TradeEvent,
    bh_fdr,
    callout_origin_time,
    count_window,
    partial_pool,
    placebo_p_value,
    pool,
    run_study,
    sample_placebos,
    trade_chain_time,
)

ORIGIN = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
# Base58 excludes 0/O/I/l, and the tape schema enforces it -- so synthetic addresses are built
# from the real alphabet rather than from f"W{index}", which the contract rightly refuses.
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MINTS = [f"{letter}{'1' * 30}pump" for letter in "ABCDEFGH"]
WALLETS = [f"W{_B58[index]}{'1' * 29}pump" for index in range(24)]

# A pronounced diurnal profile. Amplitude ~4x peak-to-trough, matching the 3.6x-5.4x measured in
# this market -- large enough that an unmatched baseline would invent an effect on its own.
def _diurnal(hour: int) -> float:
    return 1.0 + 1.5 * (1.0 + math.cos(2.0 * math.pi * (hour - 20) / 24.0))


def _mint_index(mint: str) -> int:
    return MINTS.index(mint)


def _callout(mint: str, at: datetime) -> CalloutEvent:
    return CalloutEvent(
        at=at,
        ingest_lag_seconds=12.0,
        body=Callout(
            mint=mint,
            platform="synthetic",
            author="synthetic",
            resolved_from="mint_in_text",
            text_sha256="0" * 64,
            author_followers=1000,
            engagement=10,
        ),
        kind="synthetic",
    )


def _trade(mint: str, wallet: str, at: datetime, *, buy: bool = True) -> TradeEvent:
    return TradeEvent(
        at=at,
        body=Trade(
            mint=mint,
            wallet=wallet,
            side=Side.BUY if buy else Side.SELL,
            sol_delta_lamports=0,
            token_delta_raw=1_000_000 if buy else -1_000_000,
        ),
    )


def synthetic_world(
    *,
    seed: int,
    days: int = 14,
    n_mints: int = 6,
    callouts_per_mint: int = 6,
    effect_log_ratio: float = 0.0,
    effect_window: timedelta = timedelta(minutes=30),
    base_rate_per_hour: float = 6.0,
) -> tuple[list[CalloutEvent], list[TradeEvent]]:
    """Poisson arrivals with a diurnal profile, plus an optional multiplicative post-callout bump.

    ``effect_log_ratio == 0`` is the KNOWN-ZERO regime: callout times are drawn independently of
    the arrival process, so any effect the pipeline reports is an artefact of the pipeline.
    """
    rng = random.Random(seed)
    horizon = timedelta(days=days)
    callouts: list[CalloutEvent] = []
    peak = _diurnal(20)
    for mint in MINTS[:n_mints]:
        for _ in range(callouts_per_mint):
            # Callouts are THEMSELVES diurnally clustered -- people post when the market is
            # awake. This is the confound that makes hour matching load-bearing rather than
            # decorative: under uniformly-drawn callouts an unmatched baseline is unbiased and
            # the whole control is untestable. The live store shows exactly this clustering
            # (147 of 316 callouts land in a single UTC hour).
            while True:
                at = ORIGIN + timedelta(seconds=rng.uniform(0, horizon.total_seconds()))
                if rng.random() < (_diurnal(at.hour) / peak) ** 3:
                    break
            callouts.append(_callout(mint, at.replace(microsecond=0)))
    callouts.sort(key=lambda event: (event.at, event.mint))
    by_mint: dict[str, list[datetime]] = {}
    for event in callouts:
        by_mint.setdefault(event.mint, []).append(event.at)

    trades: list[TradeEvent] = []
    step = timedelta(minutes=5)
    multiplier = math.exp(effect_log_ratio)
    for mint in MINTS[:n_mints]:
        # Per-mint level heterogeneity, so partial pooling has something real to shrink.
        level = base_rate_per_hour * (0.5 + 0.35 * _mint_index(mint))
        cursor = ORIGIN
        while cursor < ORIGIN + horizon:
            rate = level * _diurnal(cursor.hour)
            if any(at <= cursor < at + effect_window for at in by_mint.get(mint, [])):
                rate *= multiplier
            expected = rate * step.total_seconds() / 3600.0
            for _ in range(_poisson(rng, expected)):
                moment = cursor + timedelta(seconds=rng.uniform(0, step.total_seconds()))
                trades.append(_trade(mint, WALLETS[rng.randrange(len(WALLETS))], moment))
            cursor += step
    trades.sort(key=lambda event: (event.at, event.mint, event.wallet))
    return callouts, trades


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth. Deterministic given ``rng``; the sample sizes here never reach the overflow regime."""
    if mean <= 0:
        return 0
    limit = math.exp(-mean)
    count, product = 0, 1.0
    while True:
        product *= rng.random()
        if product <= limit:
            return count
        count += 1
        if count > 10_000:
            return count


# =============================================================================================
# Clock handling -- the inversion between kinds is the single most dangerous thing in the store.
# =============================================================================================


def test_trade_chain_time_is_emitted_at_not_observed_at() -> None:
    row = {"observed_at": "2026-08-13T16:05:40+00:00", "emitted_at": "2026-08-12T20:07:49+00:00"}
    assert trade_chain_time(row) == datetime(2026, 8, 12, 20, 7, 49, tzinfo=UTC)


def test_callout_origin_time_is_observed_at_not_emitted_at() -> None:
    row = {"observed_at": "2026-08-12T19:41:07+00:00", "emitted_at": "2026-08-12T19:42:08+00:00"}
    assert callout_origin_time(row) == datetime(2026, 8, 12, 19, 41, 7, tzinfo=UTC)


def test_trade_without_block_time_is_dropped_not_backfilled() -> None:
    assert trade_chain_time({"observed_at": "2026-08-13T16:05:40+00:00", "emitted_at": None}) is None


def test_naive_timestamp_is_refused() -> None:
    with pytest.raises(StudyError):
        callout_origin_time({"observed_at": "2026-08-12T19:41:07"})


# =============================================================================================
# Placebo construction
# =============================================================================================


def _coverage(days: int = 14) -> Coverage:
    return Coverage(start=ORIGIN, end=ORIGIN + timedelta(days=days))


def test_placebos_are_hour_matched() -> None:
    at = ORIGIN + timedelta(days=3, hours=17, minutes=8)
    reps = sample_placebos(
        callouts=[at],
        coverage=_coverage(),
        pre=timedelta(minutes=30),
        post=timedelta(minutes=30),
        replicates=25,
        rng=random.Random(1),
    )
    drawn = [moment for rep in reps for moment in rep]
    assert drawn
    assert all(moment.hour == 17 for moment in drawn)


def test_placebo_separation_uses_max_of_pre_and_post_not_post_alone() -> None:
    """The documented prior-study bug, asserted directly.

    With ``pre`` much larger than ``post``, separating on ``post`` alone admits placebos whose
    pre-windows overlap almost completely. The accepted set must respect ``max(pre, post)``.
    """
    pre, post = timedelta(hours=6), timedelta(minutes=30)
    times = [ORIGIN + timedelta(days=day, hours=11) for day in range(2, 10)]
    reps = sample_placebos(
        callouts=times,
        coverage=_coverage(days=30),
        pre=pre,
        post=post,
        replicates=30,
        rng=random.Random(7),
    )
    separation = max(pre, post).total_seconds()
    assert separation == pre.total_seconds()
    for rep in reps:
        for i, a in enumerate(rep):
            for b in rep[i + 1 :]:
                assert abs((a - b).total_seconds()) >= separation
            # And never inside a real callout's contaminated neighbourhood.
            for real in times:
                assert abs((a - real).total_seconds()) >= separation


def test_placebos_never_leave_the_coverage_window() -> None:
    pre, post = timedelta(minutes=30), timedelta(minutes=60)
    coverage = _coverage(days=5)
    reps = sample_placebos(
        callouts=[ORIGIN + timedelta(days=2, hours=4)],
        coverage=coverage,
        pre=pre,
        post=post,
        replicates=20,
        rng=random.Random(3),
    )
    for rep in reps:
        for moment in rep:
            assert coverage.start <= moment - pre
            assert moment + post <= coverage.end


def test_short_coverage_yields_no_placebos_rather_than_illegal_ones() -> None:
    """A 20-minute coverage window must produce nothing, not a silently overlapping match."""
    coverage = Coverage(start=ORIGIN, end=ORIGIN + timedelta(minutes=20))
    reps = sample_placebos(
        callouts=[ORIGIN + timedelta(minutes=5)],
        coverage=coverage,
        pre=timedelta(minutes=30),
        post=timedelta(minutes=30),
        replicates=10,
        rng=random.Random(5),
    )
    assert all(rep == [] for rep in reps)


# =============================================================================================
# Counting and pooling
# =============================================================================================


def test_count_window_is_half_open_and_respects_side_and_eligibility() -> None:
    at = ORIGIN + timedelta(hours=1)
    legs = [
        _trade(MINTS[0], WALLETS[0], at - timedelta(seconds=1)),
        _trade(MINTS[0], WALLETS[0], at),
        _trade(MINTS[0], WALLETS[1], at + timedelta(minutes=29)),
        _trade(MINTS[0], WALLETS[1], at + timedelta(minutes=30)),
        _trade(MINTS[0], WALLETS[2], at + timedelta(minutes=5), buy=False),
        _trade(MINTS[0], WALLETS[9], at + timedelta(minutes=5)),
    ]
    eligible = frozenset({WALLETS[0], WALLETS[1], WALLETS[2]})
    assert (
        count_window(legs, at=at, post=timedelta(minutes=30), eligible=eligible, outcome="buy_arrivals") == 2
    )
    # WALLETS[0] already held before the window, so it is not a new wallet.
    assert (
        count_window(legs, at=at, post=timedelta(minutes=30), eligible=eligible, outcome="new_wallets") == 1
    )


def test_partial_pool_reproduces_the_unpooled_answer_more_sharply() -> None:
    """PROGRAM.md 1.5: partial pooling gives the same answer as unpooled, several times sharper.

    "Sharper" has to be measured against a commensurable quantity: the uncertainty on the group
    effect from a SINGLE mint, ``sqrt(v)``. Comparing the pooled standard error against the
    between-mint spread compares a mean to a dispersion and is meaningless.
    """
    variance = 0.6
    effects = [(MINTS[i], 0.4 + 0.05 * i, variance) for i in range(6)]
    mu, se, tau = partial_pool(effects)
    thetas = [theta for _, theta, _ in effects]
    unpooled_mean = sum(thetas) / len(thetas)
    assert mu == pytest.approx(unpooled_mean, abs=0.05)
    assert se < math.sqrt(variance)
    assert se == pytest.approx(math.sqrt(variance / len(effects)), rel=0.10)
    assert tau >= 0.0


def test_partial_pool_shrinks_an_outlier_toward_the_group() -> None:
    """The defining behaviour: a noisy outlier is pulled in, an informative one much less."""
    effects = [(MINTS[i], 0.5, 0.05) for i in range(5)] + [(MINTS[5], 3.0, 4.0)]
    mu, _, _ = partial_pool(effects)
    # A fully-pooled precision-weighted mean would sit near 0.5 anyway; the point is that the
    # noisy outlier does not drag the group estimate to its own value.
    assert 0.4 < mu < 0.9
    assert mu < 3.0


def test_partial_pool_is_not_a_no_op_when_mints_genuinely_differ() -> None:
    """tau must grow with real between-mint heterogeneity, or the estimator is just a mean."""
    homogeneous = [(MINTS[i], 0.5, 0.1) for i in range(6)]
    heterogeneous = [(MINTS[i], 0.5 + 0.8 * i, 0.1) for i in range(6)]
    assert partial_pool(homogeneous)[2] < partial_pool(heterogeneous)[2]


def test_fully_pooled_is_dominated_by_the_largest_mint() -> None:
    """Why partial and not pooled: one high-volume mint with the opposite sign flips the answer."""
    counts = [
        MintCounts(MINTS[0], 5, 400, 5 * 1800.0, 50, 200, 50 * 1800.0),  # big, strong positive
        *[MintCounts(MINTS[i], 5, 1, 5 * 1800.0, 50, 40, 50 * 1800.0) for i in range(1, 6)],  # negative
    ]
    estimate = pool(counts)
    assert estimate.fully_pooled > 0.0
    assert estimate.partial_mu < 0.0
    assert estimate.unpooled_mean < 0.0


def test_p_floor_is_the_resolution_and_p_never_goes_below_it() -> None:
    for n in (0, 1, 4, 19, 199):
        draws = [0.0] * n
        p, floor = placebo_p_value(10.0, draws)
        assert floor == pytest.approx(1.0 / (1.0 + n))
        assert p >= floor - 1e-12


def test_bh_fdr_matches_hand_computation() -> None:
    # q=0.10, n=4: sorted p = .001,.02,.09,.5; thresholds .025,.05,.075,.10 -> largest rank passing is 2.
    assert bh_fdr([0.5, 0.02, 0.001, 0.09], q=0.10) == [False, True, True, False]
    assert bh_fdr([], q=0.10) == []
    assert bh_fdr([0.9, 0.95], q=0.10) == [False, False]


# =============================================================================================
# The two headline estimator tests
# =============================================================================================

_REPLICATES = 60
_RUN = {"replicates": _REPLICATES, "pre_minutes": 30, "min_analysable_events": 5}


def _primary(callouts, trades, *, seed: int):  # type: ignore[no-untyped-def]
    result = run_study(callouts, trades, seed=seed, exclude_wallets=frozenset(), **_RUN)
    return result, next(
        h for h in result.hypotheses if h.outcome == "buy_arrivals" and h.window_minutes == 30
    )


def test_known_zero_effect_is_not_detected() -> None:
    """KNOWN-ZERO: strong diurnality, no callout dependence. The pipeline must find nothing."""
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0)
    result, primary = _primary(callouts, trades, seed=101)
    assert result.verdict in {VERDICT_NULL, VERDICT_UNRESOLVABLE}
    assert not primary.fdr_rejected
    assert abs(primary.estimate.partial_mu) < 0.25
    # And the estimate is consistent with zero at two standard errors.
    assert abs(primary.estimate.partial_mu) < 2.0 * primary.estimate.partial_se + 0.05


def test_known_injected_effect_is_recovered() -> None:
    """KNOWN-EFFECT: a 3x post-callout bump must come back as log(3) and survive BH-FDR."""
    injected = math.log(3.0)
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=injected)
    result, primary = _primary(callouts, trades, seed=101)
    assert result.verdict == VERDICT_SUGGESTIVE
    assert primary.fdr_rejected
    assert primary.estimate.partial_mu == pytest.approx(injected, abs=0.35)
    assert primary.p_value <= 0.05


def test_type_one_error_is_calibrated_across_worlds() -> None:
    """One null world proves nothing. Across 8 independent KNOWN-ZERO worlds at q=0.10 the
    estimator must reject at most once, and its estimates must centre on zero.
    """
    mus: list[float] = []
    rejections = 0
    for index in range(8):
        callouts, trades = synthetic_world(
            seed=100 + index, effect_log_ratio=0.0, n_mints=4, days=10
        )
        result = run_study(
            callouts, trades, seed=index, exclude_wallets=frozenset(), replicates=40,
            pre_minutes=30, min_analysable_events=5,
        )
        primary = next(
            h for h in result.hypotheses if h.outcome == "buy_arrivals" and h.window_minutes == 30
        )
        mus.append(primary.estimate.partial_mu)
        rejections += bool(primary.fdr_rejected)
    assert rejections <= 1, f"{rejections}/8 false rejections at q=0.10"
    assert abs(sum(mus) / len(mus)) < 0.10


def test_study_is_deterministic_given_a_seed() -> None:
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=math.log(2.0))
    first = run_study(callouts, trades, seed=77, exclude_wallets=frozenset(), **_RUN)
    second = run_study(callouts, trades, seed=77, exclude_wallets=frozenset(), **_RUN)
    assert first.to_json() == second.to_json()


def test_a_different_seed_moves_the_placebo_draw_but_not_the_verdict() -> None:
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=math.log(3.0))
    verdicts = {
        run_study(callouts, trades, seed=seed, exclude_wallets=frozenset(), **_RUN).verdict
        for seed in (1, 2, 3)
    }
    assert verdicts == {VERDICT_SUGGESTIVE}


# =============================================================================================
# FALSIFICATION -- do the two headline tests actually have teeth?
#
# Each of these re-runs a headline test against a deliberately broken estimator and asserts the
# assertion FAILS. If one of these ever passes trivially, the corresponding headline test has
# stopped testing anything.
# =============================================================================================


def unmatched_placebos(
    *,
    callouts,  # type: ignore[no-untyped-def]
    coverage: Coverage,
    pre: timedelta,
    post: timedelta,
    replicates: int,
    rng: random.Random,
) -> list[list[datetime]]:
    """A BROKEN sampler: uniform over coverage, ignoring hour of day. Never use in production.

    This is the baseline construction the methodology standard forbids, implemented so that the
    forbidding can be checked rather than asserted.
    """
    span = (coverage.end - pre - post - coverage.start).total_seconds()
    out: list[list[datetime]] = []
    for _ in range(replicates):
        out.append(
            [
                coverage.start + pre + timedelta(seconds=rng.uniform(0, max(span, 0.0)))
                for _ in callouts
            ]
        )
    return out


def test_known_zero_test_has_teeth() -> None:
    """The KNOWN-ZERO assertion must FAIL when hour matching is defeated.

    Callouts cluster in busy hours and arrivals follow the same diurnal profile, so a baseline
    drawn uniformly over the coverage window must invent an effect out of time-of-day alone.
    """
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0)
    result = run_study(
        callouts,
        trades,
        seed=101,
        exclude_wallets=frozenset(),
        placebo_sampler=unmatched_placebos,
        **_RUN,
    )
    primary = next(
        h for h in result.hypotheses if h.outcome == "buy_arrivals" and h.window_minutes == 30
    )
    # The broken pipeline does not merely wobble: it manufactures a SIGNIFICANT effect, surviving
    # BH-FDR, on data whose true effect is exactly zero.
    assert abs(primary.estimate.partial_mu) >= 0.25, (
        "defeating hour matching produced no spurious effect, so the KNOWN-ZERO test is vacuous"
    )
    assert primary.fdr_rejected, "the broken pipeline did not even reject; the test has no teeth"
    # The hour-matched pipeline on the SAME data does not.
    honest = next(
        h
        for h in run_study(callouts, trades, seed=101, exclude_wallets=frozenset(), **_RUN).hypotheses
        if h.outcome == "buy_arrivals" and h.window_minutes == 30
    )
    assert not honest.fdr_rejected
    assert abs(honest.estimate.partial_mu) < abs(primary.estimate.partial_mu)


def test_known_effect_test_has_teeth_against_a_blind_estimator() -> None:
    """The KNOWN-EFFECT assertion must FAIL for an estimator that always returns zero."""
    injected = math.log(3.0)
    effects = [(MINTS[i], 0.0, 0.5) for i in range(6)]
    mu, _, _ = partial_pool(effects)
    assert mu != pytest.approx(injected, abs=0.35), (
        "a constant-zero estimator satisfies the recovery assertion, so it is vacuous"
    )


def test_known_effect_test_has_teeth_against_a_window_shuffle() -> None:
    """Recovery must FAIL when the outcome window is decoupled from the callout it belongs to."""
    injected = math.log(3.0)
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=injected)
    # Displace every callout by 12h: the bump is still in the data, but not where we look.
    displaced = [
        CalloutEvent(
            at=event.at + timedelta(hours=12),
            ingest_lag_seconds=event.ingest_lag_seconds,
            body=event.body,
            kind=event.kind,
        )
        for event in callouts
    ]
    result = run_study(displaced, trades, seed=101, exclude_wallets=frozenset(), **_RUN)
    primary = next(
        h for h in result.hypotheses if h.outcome == "buy_arrivals" and h.window_minutes == 30
    )
    assert primary.estimate.partial_mu != pytest.approx(injected, abs=0.35), (
        "the estimator recovers the injected effect from windows that do not contain it"
    )


def test_p_floor_guard_has_teeth() -> None:
    """With 4 replicates the floor is 0.2, so no BH-FDR rejection at q=0.10 is even reachable."""
    _, floor = placebo_p_value(99.0, [0.0] * 4)
    assert floor == pytest.approx(0.2)
    assert not bh_fdr([floor] * 6, q=FDR_Q)[0]


# =============================================================================================
# Degenerate-input behaviour -- the regime the live store is actually in.
# =============================================================================================


def test_zero_eligible_wallets_returns_unresolvable_not_a_number() -> None:
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0)
    only = {event.wallet for event in trades}
    result = run_study(callouts, trades, seed=1, exclude_wallets=frozenset(only), **_RUN)
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert result.hypotheses == ()
    assert "no observable fills" in result.reason


def test_no_temporal_overlap_returns_unresolvable() -> None:
    """Callouts after every observable fill: the honest answer is 'cannot be estimated'."""
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0)
    late = [
        CalloutEvent(
            at=event.at + timedelta(days=400),
            ingest_lag_seconds=event.ingest_lag_seconds,
            body=event.body,
            kind=event.kind,
        )
        for event in callouts
    ]
    result = run_study(late, trades, seed=1, exclude_wallets=frozenset(), **_RUN)
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert result.n_analysable_events == 0


def test_structural_zero_baseline_is_unresolvable_not_a_giant_effect() -> None:
    """The exact trap the live store sets: a responder that ONLY ever trades after a callout.

    That is what our own sentinel looks like, because the callout stream is its input. The naive
    output is a ~240x rate ratio at p = 0.005 on all six hypotheses. It must be refused: with zero
    placebo arrivals the log rate ratio is fixed by the continuity correction and the placebo null
    has no spread, so only a one-sided bound exists.
    """
    callouts, _ = synthetic_world(seed=11, effect_log_ratio=0.0, n_mints=4, days=10)
    responder = WALLETS[0]
    # A wallet that buys once, two minutes after every callout, and never otherwise.
    trades = [_trade(event.mint, responder, event.at + timedelta(minutes=2)) for event in callouts]
    result = run_study(
        callouts, trades, seed=1, exclude_wallets=frozenset(), replicates=40, pre_minutes=30,
        min_analysable_events=5,
    )
    primary = next(
        h for h in result.hypotheses if h.outcome == "buy_arrivals" and h.window_minutes == 30
    )
    # The naive reading really is spectacular -- that is the point.
    assert primary.n_placebo_arrivals == 0
    assert primary.estimate.partial_mu > 3.0
    assert primary.p_value == pytest.approx(primary.p_floor)
    assert primary.null_spread == pytest.approx(0.0)
    # And the verdict refuses it anyway.
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert "structural zero" in result.reason


def test_structural_zero_guard_has_teeth() -> None:
    """Without the guard this scenario would have been reported as SUGGESTIVE."""
    callouts, _ = synthetic_world(seed=11, effect_log_ratio=0.0, n_mints=4, days=10)
    trades = [_trade(e.mint, WALLETS[0], e.at + timedelta(minutes=2)) for e in callouts]
    result = run_study(
        callouts, trades, seed=1, exclude_wallets=frozenset(), replicates=40, pre_minutes=30,
        min_analysable_events=5,
    )
    # Every hypothesis in the family clears BH-FDR; only the structural-zero check stops it.
    assert all(h.fdr_rejected for h in result.hypotheses)
    assert result.verdict != VERDICT_SUGGESTIVE


def test_dropping_the_preregistered_primary_fails_closed() -> None:
    """Running a family without the primary hypothesis must raise, not silently pick another."""
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0, n_mints=4, days=10)
    with pytest.raises(StudyError, match="pre-registered primary"):
        run_study(
            callouts, trades, seed=1, exclude_wallets=frozenset(), replicates=10, pre_minutes=30,
            min_analysable_events=5, windows=(1, 5), outcomes=("buy_arrivals",),
        )


def test_single_eligible_wallet_flags_new_wallets_as_degenerate() -> None:
    callouts, trades = synthetic_world(seed=11, effect_log_ratio=0.0)
    keep = WALLETS[0]
    others = frozenset({event.wallet for event in trades} - {keep})
    result = run_study(callouts, trades, seed=1, exclude_wallets=others, **_RUN)
    assert result.eligible_wallets == (keep,)
    assert any("structurally uninformative" in note for note in result.notes)
