"""Differential tests: the Python fast path against the Lean artifact.

These are engineering discipline against drift, NOT verification. They prove nothing about
all inputs — the theorems live in `kernel/Joshi/Fill.lean` and are about the Lean definition.
What they catch is the Python transcription drifting away from it, which is the realistic
failure mode when a later agent "optimises" the arithmetic.

Skipped, loudly, when the oracle binary is absent. Never silently satisfied by comparing the
fast path against itself.
"""

from __future__ import annotations

import random

import pytest

from shitcoims_kernel import LeanOracle, OracleUnavailable, Reserves, accepts, sell_out
from shitcoims_kernel.fill import FillError, minimum_out


@pytest.fixture(scope="module")
def oracle():
    try:
        with LeanOracle() as handle:
            yield handle
    except OracleUnavailable as exc:
        pytest.skip(f"lean oracle unavailable: {exc}")


# Sizes chosen to straddle the places integer arithmetic actually breaks: the f64 exactness
# cliff at 2**53, the u64 boundary, and the degenerate empty pool.
ADVERSARIAL = [
    (0, 0, 0),
    (0, 0, 5),
    (1, 1, 1),
    (10**6, 5 * 10**5, 25 * 10**4),
    (10**15, 10**9, 10**15),
    (2**53 + 1, 2**53 + 1, 2**53 + 1),
    (2**53 - 1, 2**64 - 1, 2**53 - 1),
    (10**15, 6 * 10**17, 1),
    (1, 10**18, 10**15),
]


@pytest.mark.parametrize(("token_raw", "sol_lamports", "amount"), ADVERSARIAL)
def test_fast_path_matches_the_lean_artifact_on_adversarial_sizes(
    oracle, token_raw: int, sol_lamports: int, amount: int
) -> None:
    expected = oracle.sell_out(token_raw, sol_lamports, amount)
    assert sell_out(Reserves(token_raw, sol_lamports), amount) == expected


def test_fast_path_matches_the_lean_artifact_on_random_pools(oracle) -> None:
    rng = random.Random(20260813)
    for _ in range(400):
        token_raw = rng.randrange(0, 10**16)
        sol_lamports = rng.randrange(0, 10**12)
        amount = rng.randrange(0, 10**16)
        assert sell_out(Reserves(token_raw, sol_lamports), amount) == oracle.sell_out(
            token_raw, sol_lamports, amount
        )


def test_acceptance_matches_the_lean_artifact(oracle) -> None:
    rng = random.Random(11)
    for _ in range(200):
        token_raw = rng.randrange(1, 10**12)
        sol_lamports = rng.randrange(1, 10**12)
        amount = rng.randrange(1, 10**12)
        floor = rng.randrange(0, 10**11)
        assert accepts(Reserves(token_raw, sol_lamports), amount, floor) == oracle.accepts(
            token_raw, sol_lamports, amount, floor
        )


def test_payout_never_exceeds_the_reserve_on_the_fast_path() -> None:
    """The Lean theorem `sellOut_le_reserve`, spot-checked on the transcription."""
    rng = random.Random(7)
    for _ in range(2000):
        sol = rng.randrange(0, 10**14)
        r = Reserves(rng.randrange(0, 10**14), sol)
        assert sell_out(r, rng.randrange(0, 10**16)) <= sol


def test_payout_is_monotone_in_size_on_the_fast_path() -> None:
    """The Lean theorem `sellOut_mono`, spot-checked: a bigger clip never looks cheaper."""
    rng = random.Random(8)
    for _ in range(2000):
        r = Reserves(rng.randrange(0, 10**14), rng.randrange(0, 10**14))
        a = rng.randrange(0, 10**14)
        b = a + rng.randrange(0, 10**14)
        assert sell_out(r, a) <= sell_out(r, b)


def test_a_float_reserve_is_refused_rather_than_truncated() -> None:
    with pytest.raises(FillError):
        Reserves(1.5, 10)  # type: ignore[arg-type]
    with pytest.raises(FillError):
        sell_out(Reserves(10, 10), 1.5)  # type: ignore[arg-type]


def test_minimum_out_is_derived_from_reserves_not_from_a_tolerance() -> None:
    """250bps off a computed expectation, in integer lamports."""
    r = Reserves(1_000_000, 500_000)
    expected = sell_out(r, 250_000)
    assert minimum_out(r, 250_000, slippage_bps=250) == expected * 9750 // 10_000
    assert minimum_out(r, 250_000, slippage_bps=0) == expected
    with pytest.raises(FillError):
        minimum_out(r, 1, slippage_bps=10_001)
