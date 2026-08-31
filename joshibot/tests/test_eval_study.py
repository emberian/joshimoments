from __future__ import annotations

import inspect

from shitcoims_intelligence import eval_study
from shitcoims_intelligence.eval_study import (
    event_study,
    honest_sample_caveat,
    lead_lag,
    leadlag_p_value,
    pearson,
    verdict_histogram,
)


def test_event_study_has_no_lookahead_and_reports_tiny_n() -> None:
    bars = [
        {"ts": 100, "close": 10.0, "volume": 1},
        {"ts": 110, "close": 11.0, "volume": 1},
        {"ts": 120, "close": 12.0, "volume": 1},
        {"ts": 130, "close": 9.0, "volume": 1},
    ]
    # Event at 105 uses bar 110 as t0, horizon 2 -> close[130]/close[110]-1
    result = event_study([105], bars, horizon=2)
    assert result["n"] == 1
    assert result["execution_effect"] == "none"
    assert abs(result["mean_fwd"] - (9.0 / 11.0 - 1)) < 1e-9
    assert "below" in honest_sample_caveat(1)


def test_lead_lag_returns_a_curve_and_a_permutation_p() -> None:
    series = [float(index % 4 == 0) for index in range(24)]
    shifted = series[1:] + series[:1]
    result = lead_lag(series, shifted, max_lag=4)
    assert result["curve"]
    assert result["n"] == 24
    asserted = leadlag_p_value(series, shifted, max_lag=4)
    assert 0 < asserted["p_value"] <= 1
    assert pearson(series, series) == 1.0


def test_eval_study_is_isolated_from_marketfabric_and_signer() -> None:
    source = inspect.getsource(eval_study)
    assert "marketfabric" not in source
    assert "Keypair" not in source
    assert "shitcoims_sentinel.executor" not in source
    hist = verdict_histogram(
        [{"verdict": "skip"}, {"verdict": "veto"}, {"verdict": "skip"}, {"verdict": "nope"}]
    )
    assert hist == {"veto": 1, "watch_exit": 0, "pass": 0, "skip": 2}
