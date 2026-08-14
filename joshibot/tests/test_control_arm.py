"""Tests for studies/control_arm.py -- the survival-filter control arm.

The gate this file has to pass is PROGRAM.md section 3.12: BOTH controls, always. An
estimator that reports "no effect" no matter what passes a known-zero test perfectly, so a
green zero-control certifies a broken instrument exactly as readily as a working one. Every
statistical claim here is therefore checked against a world with NO effect *and* a world with
a PLANTED effect, and the planted world must be recovered.

The arithmetic checks are against numbers computable by hand, not against the code's own
output, because a test that asserts what the code does cannot fail when the code is wrong.
"""

from __future__ import annotations

import json
import math
import os
import random

import pytest

from studies.control_arm import (
    AGE_EDGES,
    Cohort,
    Thresholds,
    analyse,
    benjamini_hochberg,
    classify,
    conditional_survival,
    fisher_exact_greater,
    is_pumpfun_mint,
    isotonic_decreasing,
    operator_touches,
    permutation_test_mean_diff,
    picks_needed_fisher,
    picks_needed_perfect,
    poisson_binomial_at_least,
    poisson_binomial_pmf,
    stratified_sample,
    survival_curve,
)

# --------------------------------------------------------------------------------------
# exact tests, against hand-computable values
# --------------------------------------------------------------------------------------


def test_fisher_matches_the_lady_tasting_tea() -> None:
    # Fisher's own example: 8 cups, 4 of each, 3 correctly identified. The one-sided
    # probability of 3-or-better is (C(4,3)C(4,1) + C(4,4)C(4,0)) / C(8,4) = 17/70.
    assert fisher_exact_greater(3, 1, 1, 3) == pytest.approx(17 / 70, rel=1e-12)
    # A perfect 4-for-4 is the single most extreme table: 1/70.
    assert fisher_exact_greater(4, 0, 0, 4) == pytest.approx(1 / 70, rel=1e-12)


def test_fisher_is_one_and_only_one_when_nothing_can_be_more_extreme() -> None:
    # The worst possible arm: every extreme table is at least this good, so p = 1.
    assert fisher_exact_greater(0, 4, 4, 0) == pytest.approx(1.0)
    assert fisher_exact_greater(0, 0, 0, 0) == pytest.approx(1.0)


def test_fisher_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        fisher_exact_greater(-1, 1, 1, 1)


def test_fisher_is_monotone_in_the_arm_record() -> None:
    # More survivors in the picks arm can never make the evidence weaker.
    ps = [fisher_exact_greater(k, 10 - k, 500, 500) for k in range(11)]
    assert all(ps[i] >= ps[i + 1] for i in range(len(ps) - 1))


def test_poisson_binomial_collapses_to_the_binomial_when_p_is_constant() -> None:
    p, n = 0.37, 9
    pmf = poisson_binomial_pmf([p] * n)
    for k in range(n + 1):
        want = math.comb(n, k) * p**k * (1 - p) ** (n - k)
        assert pmf[k] == pytest.approx(want, rel=1e-12)


def test_poisson_binomial_is_a_distribution_with_unequal_p() -> None:
    ps = [0.1, 0.55, 0.9, 0.33, 0.99]
    pmf = poisson_binomial_pmf(ps)
    assert len(pmf) == len(ps) + 1
    assert sum(pmf) == pytest.approx(1.0, rel=1e-12)
    # mean of a sum of Bernoullis is the sum of the p.
    assert sum(k * v for k, v in enumerate(pmf)) == pytest.approx(sum(ps), rel=1e-12)
    assert poisson_binomial_at_least(ps, 0) == pytest.approx(1.0)
    assert poisson_binomial_at_least(ps, len(ps)) == pytest.approx(math.prod(ps), rel=1e-12)


def test_poisson_binomial_rejects_out_of_range_probabilities() -> None:
    with pytest.raises(ValueError):
        poisson_binomial_pmf([0.5, 1.4])


def test_benjamini_hochberg_against_a_worked_example() -> None:
    # m=4. Sorted p = .01 .02 .03 .04; raw BH = .04 .04 .04 .04, then monotone from the top.
    adj = benjamini_hochberg([0.01, 0.02, 0.03, 0.04])
    assert all(a == pytest.approx(0.04) for a in adj)
    # order is preserved, not sorted
    adj2 = benjamini_hochberg([0.9, 0.001])
    assert adj2[1] < adj2[0]


# --------------------------------------------------------------------------------------
# the power number, which is the lane's headline output
# --------------------------------------------------------------------------------------


def test_picks_needed_perfect_is_exactly_the_log_ratio() -> None:
    # A coin-flip null needs 5 straight wins: .5**5 = .03125 <= .05, .5**4 = .0625 > .05.
    assert picks_needed_perfect(0.5, 0.05) == 5
    assert 0.5 ** picks_needed_perfect(0.5, 0.05) <= 0.05
    assert 0.5 ** (picks_needed_perfect(0.5, 0.05) - 1) > 0.05


def test_picks_needed_perfect_blows_up_as_the_null_survival_approaches_one() -> None:
    assert picks_needed_perfect(0.9, 0.05) == 29
    assert picks_needed_perfect(0.99, 0.05) == 299
    # If nothing ever dies in the control, no record length is ever significant.
    assert picks_needed_perfect(1.0, 0.05) is None
    # And a stricter alpha always costs more picks.
    assert picks_needed_perfect(0.9, 0.01) > picks_needed_perfect(0.9, 0.05)


def test_picks_needed_boundary_is_tight_for_every_null_on_a_grid() -> None:
    for p in (0.2, 0.45, 0.6, 0.75, 0.88, 0.95):
        k = picks_needed_perfect(p, 0.05)
        assert p**k <= 0.05 < p ** (k - 1)


def test_picks_needed_against_a_finite_control_costs_more_than_a_known_base_rate() -> None:
    # Estimating the base rate from 200 observations is not the same as knowing it.
    known = picks_needed_perfect(0.5, 0.05)
    finite = picks_needed_fisher(100, 200, 0.05)
    assert finite is not None and finite >= known
    # A control with no deaths cannot ever be beaten.
    assert picks_needed_fisher(200, 200, 0.05) is None


# --------------------------------------------------------------------------------------
# status, survival curve, left truncation
# --------------------------------------------------------------------------------------


def test_classify_boundaries_are_where_the_thresholds_say() -> None:
    th = Thresholds(dead_liq=1000, dead_vol=100, dying_liq=10_000, dying_vol=1000)
    assert classify(None, None, th) == "dead"  # no market at all
    assert classify(999.99, 1e9, th) == "dead"
    assert classify(1000.0, 99.99, th) == "dead"
    assert classify(1000.0, 100.0, th) == "dying"
    assert classify(9999.0, 1e9, th) == "dying"
    assert classify(10_000.0, 999.0, th) == "dying"
    assert classify(10_000.0, 1000.0, th) == "alive"


def test_classify_moves_with_the_threshold_and_that_is_the_point() -> None:
    lax = Thresholds(dead_liq=250, dead_vol=0)
    strict = Thresholds(dead_liq=5000, dead_vol=500)
    assert classify(2000.0, 300.0, lax) != classify(2000.0, 300.0, strict)


def _cohort(age: float, alive: bool) -> Cohort:
    return Cohort(
        mint=f"m{age}{alive}",
        grad_ts=0,
        age_days=age,
        status="alive" if alive else "dead",
        liquidity_usd=1e6 if alive else 0.0,
        volume_24h_usd=1e6 if alive else 0.0,
        mig_sol=85.0,
        curve_days=1.0,
    )


def test_survival_curve_recovers_a_planted_curve() -> None:
    # Plant S: 90% alive at half a day, 50% at 3 days, 20% at 10 days.
    rng = random.Random(7)
    rows = []
    for age, s in ((0.3, 0.9), (2.5, 0.5), (10.5, 0.2)):
        for _ in range(400):
            rows.append(_cohort(age, rng.random() < s))
    curve = survival_curve(rows, strict=False, edges=AGE_EDGES)
    got = {round(a, 3): s for a, n, s in curve if n}
    # bins containing 0.3, 2.5, 10.5 respectively
    vals = sorted(got.items())
    assert vals[0][1] == pytest.approx(0.9, abs=0.05)
    assert vals[1][1] == pytest.approx(0.5, abs=0.06)
    assert vals[2][1] == pytest.approx(0.2, abs=0.05)


def test_survival_curve_reports_empty_bins_rather_than_inventing_them() -> None:
    curve = survival_curve([_cohort(0.3, True)], strict=False, edges=AGE_EDGES)
    empty = [(a, n, s) for a, n, s in curve if n == 0]
    assert empty, "a one-token cohort must leave most bins empty"
    assert all(math.isnan(s) for _, _, s in empty)


def test_each_token_lands_in_exactly_one_bin() -> None:
    rows = [_cohort(a, True) for a in (0.01, 0.5, 3.0, 20.0, 60.0)]
    curve = survival_curve(rows, strict=False, edges=AGE_EDGES)
    assert sum(n for _, n, _ in curve) == len(rows)


def test_isotonic_leaves_an_already_decreasing_curve_alone() -> None:
    vals = [0.9, 0.6, 0.5, 0.2]
    got = isotonic_decreasing(vals, [10.0] * 4)
    assert got == pytest.approx(vals)


def test_isotonic_pools_violations_into_the_weighted_mean() -> None:
    # 0.2 then 0.8 violates monotonicity; with weights 3 and 1 the pooled value is 0.35.
    got = isotonic_decreasing([0.2, 0.8], [3.0, 1.0])
    assert got == pytest.approx([0.35, 0.35])


def test_isotonic_skips_empty_bins_without_shifting_the_rest() -> None:
    got = isotonic_decreasing([0.9, float("nan"), 0.4], [10.0, 0.0, 10.0])
    assert math.isnan(got[1])
    assert got[0] == pytest.approx(0.9)
    assert got[2] == pytest.approx(0.4)


def test_isotonic_rejects_mismatched_weights() -> None:
    with pytest.raises(ValueError):
        isotonic_decreasing([0.1, 0.2], [1.0])


def test_isotonic_is_unbiased_on_a_flat_curve_where_a_running_min_is_not() -> None:
    """The regression that the known-zero world caught.

    A truly flat survival curve, read off noisy bins, must come back near its true level. A
    running minimum settles near the smallest bin instead, which understates the null and
    manufactures an edge for whatever arm is compared against it.
    """
    rng = random.Random(3)
    truth, bins, per_bin = 0.35, 20, 60
    vals, wts = [], []
    for _ in range(bins):
        k = sum(1 for _ in range(per_bin) if rng.random() < truth)
        vals.append(k / per_bin)
        wts.append(float(per_bin))
    fitted = isotonic_decreasing(vals, wts)
    running_min = []
    run = 1.0
    for v in vals:
        run = min(run, v)
        running_min.append(run)
    assert abs(fitted[-1] - truth) < 0.05, fitted[-1]
    assert running_min[-1] < truth - 0.08, running_min[-1]


def test_conditional_survival_is_the_left_truncation_correction() -> None:
    # S: 1.0 -> 0.5 by day 1 -> 0.4 by day 10. Surviving day 1 is most of the battle.
    curve = [(0.5, 100, 1.0), (1.0, 100, 0.5), (10.0, 100, 0.4)]
    unconditional = conditional_survival(curve, 0.0, 10.0)
    seasoned = conditional_survival(curve, 1.0, 10.0)
    assert unconditional == pytest.approx(0.4, abs=1e-9)
    assert seasoned == pytest.approx(0.8, abs=1e-9)
    assert seasoned > unconditional
    # No elapsed time, no risk.
    assert conditional_survival(curve, 3.0, 3.0) == 1.0
    assert conditional_survival(curve, 3.0, 1.0) == 1.0


def test_conditional_survival_never_exceeds_one_on_a_noisy_curve() -> None:
    # A finite cross-section wiggles upward; without the monotone correction this returns
    # a "probability" above 1 and silently breaks the Poisson-binomial null.
    noisy = [(0.5, 50, 0.60), (1.0, 50, 0.40), (2.0, 50, 0.55), (5.0, 50, 0.30)]
    for a in (0.0, 0.5, 1.0, 2.0):
        for b in (1.0, 2.0, 5.0, 50.0):
            q = conditional_survival(noisy, a, b)
            assert 0.0 <= q <= 1.0


def test_conditional_survival_beyond_the_census_gives_the_null_the_benefit() -> None:
    # Past the last measured age the curve is flat, so an old token's null survival is 1:
    # the null predicts it survives, and its surviving is therefore worth no evidence.
    curve = [(0.5, 100, 1.0), (1.0, 100, 0.5), (10.0, 100, 0.4)]
    assert conditional_survival(curve, 200.0, 400.0) == pytest.approx(1.0)


# --------------------------------------------------------------------------------------
# the operator arm: a routing hop is not a pick
# --------------------------------------------------------------------------------------

WALLET = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"


def _tx(ts: int, transfers: list[dict[str, object]], source: str = "JUPITER") -> dict[str, object]:
    return {"timestamp": ts, "source": source, "signature": f"s{ts}", "tokenTransfers": transfers}


def test_a_same_transaction_round_trip_is_not_a_holding() -> None:
    # SOL -> HOP -> target inside one transaction. The wallet never held HOP for any time.
    txs = [
        _tx(
            1000,
            [
                {"mint": "HOP", "toUserAccount": WALLET, "tokenAmount": 5.0},
                {"mint": "HOP", "fromUserAccount": WALLET, "tokenAmount": 5.0},
            ],
        )
    ]
    assert operator_touches(txs)["HOP"].held_seconds == 0.0


def test_a_real_position_accumulates_holding_time() -> None:
    txs = [
        _tx(1000, [{"mint": "TOK", "toUserAccount": WALLET, "tokenAmount": 10.0}]),
        _tx(1000 + 3600, [{"mint": "TOK", "fromUserAccount": WALLET, "tokenAmount": 10.0}]),
    ]
    rec = operator_touches(txs)["TOK"]
    assert rec.held_seconds == pytest.approx(3600.0)
    assert rec.open_balance == pytest.approx(0.0)


def test_an_open_position_is_held_until_the_observation_edge() -> None:
    txs = [
        _tx(1000, [{"mint": "TOK", "toUserAccount": WALLET, "tokenAmount": 10.0}]),
        _tx(5000, [{"mint": "OTHER", "toUserAccount": WALLET, "tokenAmount": 1.0}]),
    ]
    rec = operator_touches(txs)["TOK"]
    assert rec.held_seconds == pytest.approx(4000.0)
    assert rec.open_balance == pytest.approx(10.0)


def test_meteora_transactions_mark_the_dlmm_arm() -> None:
    txs = [
        _tx(1000, [{"mint": "TOK", "toUserAccount": WALLET, "tokenAmount": 1.0}], source="METEORA"),
        _tx(2000, [{"mint": "OTH", "toUserAccount": WALLET, "tokenAmount": 1.0}], source="JUPITER"),
    ]
    touches = operator_touches(txs)
    assert touches["TOK"].dlmm_txs == 1
    assert touches["OTH"].dlmm_txs == 0


def test_pumpfun_mint_detection_is_by_suffix_not_by_symbol() -> None:
    assert is_pumpfun_mint("XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump")
    assert not is_pumpfun_mint("CASHx9KJUStyftLFWGvEVf59SGeG9sh5FfcnZMVPCASH")
    assert not is_pumpfun_mint("Dz9mQ9NzkBcCsuGPFJ3r1bS4wgqKMHBPiVuniW8Mbonk")


# --------------------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------------------


def test_stratified_sample_is_deterministic_and_caps_per_day() -> None:
    grads = [{"mint": f"m{i}", "grad_ts": 1_786_000_000 + (i % 3) * 86_400 + i} for i in range(300)]
    a = stratified_sample(grads, per_day=10, seed=1)
    b = stratified_sample(grads, per_day=10, seed=1)
    c = stratified_sample(grads, per_day=10, seed=2)
    assert [r["mint"] for r in a] == [r["mint"] for r in b]
    assert [r["mint"] for r in a] != [r["mint"] for r in c]
    assert len(a) == 30  # 3 days x 10


def test_permutation_test_is_deterministic_given_the_seed() -> None:
    xs, ys = [1.0, 2.0, 3.0], [10.0, 11.0, 12.0]
    p1 = permutation_test_mean_diff(xs, ys, rounds=500, rng=random.Random(4))[1]
    p2 = permutation_test_mean_diff(xs, ys, rounds=500, rng=random.Random(4))[1]
    assert p1 == p2


def test_permutation_test_separates_a_planted_shift_from_no_shift() -> None:
    rng = random.Random(11)
    same_a = [rng.gauss(0, 1) for _ in range(80)]
    same_b = [rng.gauss(0, 1) for _ in range(80)]
    shifted = [rng.gauss(3, 1) for _ in range(80)]
    _, p_null = permutation_test_mean_diff(same_a, same_b, rounds=1000, rng=random.Random(1))
    _, p_effect = permutation_test_mean_diff(shifted, same_b, rounds=1000, rng=random.Random(1))
    assert p_null > 0.05
    assert p_effect < 0.01


# --------------------------------------------------------------------------------------
# BOTH CONTROLS, end to end through analyse()
# --------------------------------------------------------------------------------------


def _write_world(
    cache: str,
    *,
    n_universe: int,
    universe_survival: float,
    n_picks: int,
    picks_all_survive: bool,
    seed: int,
    entry_age_days: float = 0.0,
) -> None:
    """Fabricate a complete cache: graduation census, outcomes, and an operator wallet.

    `picks_all_survive=False` draws the picks from the SAME distribution as the universe --
    the known-ZERO world. `True` plants a perfect record -- the known-EFFECT world.
    """
    os.makedirs(cache, exist_ok=True)
    rng = random.Random(seed)
    now = 1_786_800_000  # inside the study's observation window
    grads, dex = [], {}
    for i in range(n_universe):
        mint = f"U{i:06d}pump"
        # spread graduations over 20 days so every age bin has tokens in it
        grad_ts = now - int((i % 20) * 86_400 + rng.random() * 86_400)
        grads.append(
            {"mint": mint, "grad_ts": grad_ts, "sig": f"g{i}", "mig_sol": 85.0, "mig_tokens": 2.069e8}
        )
        alive = rng.random() < universe_survival
        dex[mint] = [_pair(mint, alive, grad_ts)]

    txs = []
    chosen = []
    for j in range(n_picks):
        mint = f"P{j:06d}pump"
        grad_ts = now - int(86_400 * (entry_age_days + 12) + j)
        entry_ts = grad_ts + int(entry_age_days * 86_400)
        alive = True if picks_all_survive else rng.random() < universe_survival
        chosen.append(mint)
        dex[mint] = [_pair(mint, alive, grad_ts)]
        # The picks are also part of the population being controlled against.
        grads.append(
            {"mint": mint, "grad_ts": grad_ts, "sig": f"gp{j}", "mig_sol": 85.0, "mig_tokens": 2.069e8}
        )
        txs.append(_tx(entry_ts, [{"mint": mint, "toUserAccount": WALLET, "tokenAmount": 1.0}], "METEORA"))
        txs.append(
            _tx(entry_ts + 7200, [{"mint": mint, "fromUserAccount": WALLET, "tokenAmount": 1.0}], "METEORA")
        )

    with open(os.path.join(cache, "universe_grads.jsonl"), "w") as fh:
        for row in grads:
            fh.write(json.dumps(row) + "\n")
    uni_only = {m: v for m, v in dex.items() if m.startswith("U")}
    op_only = {m: dex[m] for m in chosen}
    _dump(os.path.join(cache, "dexscreener_universe.json"), uni_only)
    _dump(os.path.join(cache, "dexscreener_operator.json"), op_only)
    _dump(os.path.join(cache, "pumpfun_universe.json"), {})
    _dump(os.path.join(cache, "pumpfun_operator.json"), {m: {"complete": True} for m in chosen})
    _dump(os.path.join(cache, "wallet_enh.json"), txs)


def _pair(mint: str, alive: bool, grad_ts: int) -> dict[str, object]:
    liq, vol = (250_000.0, 500_000.0) if alive else (10.0, 0.0)
    return {
        "baseToken": {"address": mint, "symbol": mint[:6]},
        "liquidity": {"usd": liq},
        "volume": {"h24": vol},
        "pairCreatedAt": grad_ts * 1000,
    }


def _dump(path: str, obj: object) -> None:
    with open(path, "w") as fh:
        json.dump(obj, fh)


def test_known_zero_world_does_not_manufacture_a_filter(tmp_path) -> None:
    """Picks drawn from the same population as the control. The instrument must not fire.

    Run over many independent worlds, because a single non-rejection proves nothing: what is
    being asserted is that the false-positive rate is near nominal, not that one draw missed.
    """
    fired = 0
    worlds = 40
    for w in range(worlds):
        cache = str(tmp_path / f"zero{w}")
        _write_world(
            cache,
            n_universe=1200,
            universe_survival=0.35,
            n_picks=14,
            picks_all_survive=False,
            seed=1000 + w,
        )
        res = analyse(cache, seed=7, th=Thresholds(), strict=False)
        primary = next(t for t in res["tests"] if t.get("primary"))
        if primary["p_one_sided"] <= 0.05:
            fired += 1
    # nominal 5% of 40 worlds is 2; allow slack for the discreteness of an n=14 exact test.
    assert fired <= 8, f"false positives in {fired}/{worlds} null worlds"


def test_known_effect_world_is_recovered_when_the_arm_is_big_enough(tmp_path) -> None:
    """A planted perfect record at a sample size the design CAN resolve must be detected.

    This is the control that a constant-zero estimator fails. Without it, the zero-world test
    above is satisfied by an instrument that never fires at all.
    """
    cache = str(tmp_path / "effect")
    _write_world(
        cache, n_universe=1500, universe_survival=0.35, n_picks=40, picks_all_survive=True, seed=99
    )
    res = analyse(cache, seed=7, th=Thresholds(), strict=False)
    primary = next(t for t in res["tests"] if t.get("primary"))
    assert primary["p_one_sided"] < 1e-6, primary
    assert res["verdict"]["label"] == "FILTER-SHOWS-SIGNAL", res["verdict"]


def test_a_perfect_record_that_is_too_short_is_called_unresolvable_not_significant(tmp_path) -> None:
    """The lane's whole point: at a high enough null survival, n=14 CANNOT be significant.

    Here the control survives 92% of the time, so a perfect record needs ceil(ln.05/ln.92)=36
    picks. A 14-pick perfect run must come back UNRESOLVABLE-AT-THIS-N, never SHOWS-SIGNAL.
    """
    cache = str(tmp_path / "short")
    _write_world(
        cache, n_universe=2000, universe_survival=0.92, n_picks=14, picks_all_survive=True, seed=5
    )
    res = analyse(cache, seed=7, th=Thresholds(), strict=False)
    assert res["verdict"]["label"] == "UNRESOLVABLE-AT-THIS-N", res["verdict"]
    assert res["verdict"]["picks_needed"] > 14


def test_analyse_is_deterministic_for_a_fixed_seed(tmp_path) -> None:
    cache = str(tmp_path / "det")
    _write_world(
        cache, n_universe=800, universe_survival=0.4, n_picks=14, picks_all_survive=False, seed=3
    )
    a = analyse(cache, seed=20260814, th=Thresholds(), strict=False)
    b = analyse(cache, seed=20260814, th=Thresholds(), strict=False)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_left_truncation_changes_the_answer(tmp_path) -> None:
    """Buying seasoned tokens must lower the expected survivors demanded of the null.

    If the age matching were a no-op, these two worlds would produce the same expectation and
    the confound the lane exists to find would be invisible.
    """
    fresh = str(tmp_path / "fresh")
    seasoned = str(tmp_path / "seasoned")
    _write_world(
        fresh,
        n_universe=2000,
        universe_survival=0.3,
        n_picks=14,
        picks_all_survive=True,
        seed=17,
        entry_age_days=0.0,
    )
    _write_world(
        seasoned,
        n_universe=2000,
        universe_survival=0.3,
        n_picks=14,
        picks_all_survive=True,
        seed=17,
        entry_age_days=10.0,
    )
    r_fresh = analyse(fresh, seed=7, th=Thresholds(), strict=False)
    r_seasoned = analyse(seasoned, seed=7, th=Thresholds(), strict=False)
    e_fresh = r_fresh["arms"]["graduate"]["matched_null_expected"]
    e_seasoned = r_seasoned["arms"]["graduate"]["matched_null_expected"]
    assert e_seasoned > e_fresh, (e_seasoned, e_fresh)


def test_the_reported_hypothesis_count_covers_every_preregistered_test(tmp_path) -> None:
    cache = str(tmp_path / "multi")
    _write_world(
        cache, n_universe=900, universe_survival=0.4, n_picks=14, picks_all_survive=False, seed=21
    )
    res = analyse(cache, seed=7, th=Thresholds(), strict=False)
    prereg = [t for t in res["tests"] if t["preregistered"]]
    assert res["n_hypotheses"] == len(prereg) >= 4
    assert all(t["p_bonferroni"] >= t["p_one_sided"] for t in prereg)
    # the contaminated top12 exhibit must be excluded from the family
    assert any(not t["preregistered"] for t in res["tests"])
