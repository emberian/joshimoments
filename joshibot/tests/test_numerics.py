from __future__ import annotations

import inspect

from shitcoims_intelligence import numerics
from shitcoims_intelligence.numerics import (
    benjamini_hochberg,
    concentration,
    deflated_sharpe,
    gini,
    holder_veto,
    nakamoto,
)


def test_equal_balances_are_uncencentrateed() -> None:
    conc = concentration([1.0, 1.0, 1.0, 1.0])
    assert conc.holders == 4
    assert conc.top1 == 0.25
    assert conc.hhi == 0.25
    assert conc.nakamoto == 2
    assert abs(gini([1.0, 1.0, 1.0, 1.0])) < 1e-9
    assert holder_veto(conc) is False


def test_one_whale_is_a_holder_veto() -> None:
    conc = concentration([97.0, 1.0, 1.0, 1.0])
    assert conc.top1 > 0.9
    assert nakamoto([97.0, 1.0, 1.0, 1.0]) == 1
    assert holder_veto(conc) is True


def test_bh_keeps_the_small_p_and_drops_the_rest() -> None:
    keep = benjamini_hochberg([0.001, 0.8, 0.9, 0.85], q=0.05)
    assert keep[0] is True
    assert keep[1:] == (False, False, False)
    assert benjamini_hochberg([]) == ()


def test_dsr_penalizes_many_trials_and_source_is_isolated() -> None:
    one = deflated_sharpe(2.0, trials=1, n_obs=200)
    many = deflated_sharpe(2.0, trials=40, n_obs=200)
    assert one["deflated_sharpe"] > many["deflated_sharpe"]
    source = inspect.getsource(numerics)
    assert "import marketfabric" not in source
    assert "numpy" not in source
    assert "Keypair" not in source
