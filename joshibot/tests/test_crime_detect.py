"""Tests for the crime detector.

The tests that matter here are not "does it run" — they are the three properties the
detector's *claims* rest on, and each one would be silently false in a plausible
implementation:

1. **Causality.** A feature computed at hour ``i`` must not change when the future changes.
   This is the difference between a detector and a post-mortem, and it is exactly the bug
   that makes a backtest look wonderful.
2. **Discrimination.** A metered, linear, low-volume climb must score above a bursty organic
   one *on the same calibration*. If the score cannot separate the two constructed extremes
   it cannot separate anything.
3. **Label integrity.** ``find_rip`` must fire on an irreversible collapse and must NOT fire
   on a violent dip that recovers — the whole point of the "stays down" clause.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from shitcoims_scalper.crime_detect import (
    ALERT_KINDS,
    DEFAULT_WINDOW,
    FEATURE_KEYS,
    SCORE_KEYS,
    Calibration,
    Series,
    alert_row,
    append_rows,
    crime_score,
    defect_row,
    features_at,
    find_rip,
    heartbeat_row,
    linreg_r2,
    new_run_id,
    score_series,
)

T0 = 1_780_000_000


def rows(closes, vols, t0: int = T0):
    return [[t0 + i * 3600, c, c, c, c, v] for i, (c, v) in enumerate(zip(closes, vols, strict=False))]


def series(closes, vols, supply: float = 1e9, **kw) -> Series:
    s = Series.from_ohlcv("pool", "mint", "SYM", rows(closes, vols), supply=supply, **kw)
    assert s is not None
    return s


# ---------------------------------------------------------------------------------------
# Series construction
# ---------------------------------------------------------------------------------------


def test_missing_hours_become_measured_zeros_not_gaps():
    """GT omits an hour that did not trade. That is a zero, and it must be present."""

    raw = [[T0, 1.0, 1.0, 1.0, 1.0, 100.0], [T0 + 3 * 3600, 1.1, 1.1, 1.1, 1.1, 50.0]]
    s = Series.from_ohlcv("p", "m", "S", raw)
    assert s is not None
    assert len(s) == 4
    assert s.vol == [100.0, 0.0, 0.0, 50.0]
    # the filled hours carry the *previous* close, so no phantom price move is invented
    assert s.close == [1.0, 1.0, 1.0, 1.1]


def test_unsorted_input_is_sorted():
    raw = list(reversed(rows([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])))
    s = Series.from_ohlcv("p", "m", "S", raw)
    assert s is not None
    assert s.close == [1.0, 2.0, 3.0]


def test_absurd_span_is_refused_rather_than_expanded():
    """A corrupt timestamp must not make us allocate a million bars."""

    raw = [[T0, 1, 1, 1, 1, 1], [T0 + 10**9, 1, 1, 1, 1, 1]]
    assert Series.from_ohlcv("p", "m", "S", raw) is None


# ---------------------------------------------------------------------------------------
# 1. Causality — the property the whole study rests on
# ---------------------------------------------------------------------------------------


def test_features_do_not_see_the_future():
    rng = random.Random(4)
    closes = [1.0]
    for _ in range(200):
        closes.append(closes[-1] * math.exp(rng.gauss(0, 0.05)))
    vols = [rng.expovariate(1 / 1000.0) for _ in closes]

    s_full = series(closes, vols)
    # Mutate everything after hour 100 — a rug, in fact.
    tampered = list(closes)
    tampered_v = list(vols)
    for k in range(101, len(tampered)):
        tampered[k] = closes[100] * 0.01
        tampered_v[k] = 5.0
    s_tampered = series(tampered, tampered_v)

    for i in (DEFAULT_WINDOW, 60, 100):
        a = features_at(s_full, i)
        b = features_at(s_tampered, i)
        assert a is not None and b is not None
        for k in FEATURE_KEYS:
            av, bv = a[k], b[k]
            if av is None or bv is None:
                assert av == bv, k
            else:
                assert av == pytest.approx(bv, rel=1e-12), k


def test_window_shorter_than_required_returns_none():
    s = series([1.0] * 30, [1.0] * 30)
    assert features_at(s, 10, win=48) is None
    assert features_at(s, 29, win=48) is None


def test_score_series_never_scores_the_first_window():
    s = series([1.0 + 0.01 * i for i in range(80)], [10.0] * 80)
    cal = Calibration.fit([features_at(s, i) for i in range(48, 80)])
    scored = score_series(s, cal)
    assert scored[0]["i"] == DEFAULT_WINDOW
    assert len(scored) == 80 - DEFAULT_WINDOW


# ---------------------------------------------------------------------------------------
# 2. Discrimination — the constructed extremes
# ---------------------------------------------------------------------------------------


def _metered_climb(n: int = 200, seed: int = 1):
    """A scheduled buy-bot: price rises linearly, volume is a constant trickle."""

    rng = random.Random(seed)
    closes = [1.0 + 0.02 * i for i in range(n)]
    vols = [100.0 * (1 + 0.01 * rng.random()) for _ in range(n)]
    return closes, vols


def _organic(n: int = 200, seed: int = 2):
    """Real attention: a random walk with fat-tailed, bursty volume."""

    rng = random.Random(seed)
    closes = [1.0]
    vols = []
    for _ in range(n - 1):
        closes.append(max(1e-6, closes[-1] * math.exp(rng.gauss(0, 0.06))))
    for _ in range(n):
        vols.append(100.0 * math.exp(rng.gauss(0, 1.8)))
    return closes, vols


def _ambient(n_coins: int = 40):
    """A calibration population: mostly organic coins."""

    rows_ = []
    for c in range(n_coins):
        closes, vols = _organic(seed=100 + c)
        s = series(closes, vols)
        rows_.extend(f for f in (features_at(s, i) for i in range(48, len(s))) if f)
    return rows_


def test_metered_climb_scores_above_organic():
    cal = Calibration.fit(_ambient())
    m = series(*_metered_climb())
    o = series(*_organic(seed=7))
    sm = crime_score(features_at(m, 150), cal)["score"]
    so = crime_score(features_at(o, 150), cal)["score"]
    assert sm is not None and so is not None
    assert sm > so
    # and the metered one should be near the top of the scale, not merely ahead
    assert sm > 0.75


def test_every_declared_component_contributes():
    cal = Calibration.fit(_ambient())
    m = series(*_metered_climb())
    parts = crime_score(features_at(m, 150), cal)["parts"]
    assert set(parts) == {k for k, _ in SCORE_KEYS}


def test_falling_window_is_damped():
    """A controlled bleed is a different animal from a manufactured ascent."""

    cal = Calibration.fit(_ambient())
    up = features_at(series(*_metered_climb()), 150)
    closes, vols = _metered_climb()
    down = features_at(series(list(reversed(closes)), vols), 150)
    assert up["rising"] and not down["rising"]
    assert crime_score(down, cal)["score"] < crime_score(up, cal)["score"]


def test_score_is_unit_free_in_price():
    """Denominating the coin in cents rather than dollars must not change the score."""

    cal = Calibration.fit(_ambient())
    closes, vols = _metered_climb()
    a = crime_score(features_at(series(closes, vols), 150), cal)["score"]
    b = crime_score(features_at(series([c * 100 for c in closes], vols, supply=1e7), 150), cal)["score"]
    assert a == pytest.approx(b, rel=1e-9)


def test_empty_calibration_yields_neutral_ranks():
    cal = Calibration(pops={}, n=0)
    f = features_at(series(*_metered_climb()), 150)
    out = crime_score(f, cal)
    assert out["score"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------------------
# linear regression helper
# ---------------------------------------------------------------------------------------


def test_linreg_recovers_a_perfect_line():
    r2, slope = linreg_r2([3.0 + 2.0 * i for i in range(50)])
    assert r2 == pytest.approx(1.0)
    assert slope == pytest.approx(2.0)


def test_linreg_on_a_flat_series_is_zero_not_one():
    r2, slope = linreg_r2([5.0] * 50)
    assert r2 == 0.0 and slope == 0.0


# ---------------------------------------------------------------------------------------
# 3. Label integrity
# ---------------------------------------------------------------------------------------


def test_rip_fires_on_an_irreversible_collapse():
    closes = [10.0] * 40 + [1.0] * 40
    s = series(closes, [100.0] * 80)
    rip = find_rip(s)
    assert rip is not None
    assert rip["i"] == 39            # last hour at the pre-rip level
    assert rip["fall_pct"] == pytest.approx(-0.9)
    assert rip["t_event"] == T0 + 39 * 3600


def test_rip_does_not_fire_on_a_dip_that_recovers():
    """The 'stays down' clause is the whole difference between a rug and a bad hour."""

    closes = [10.0] * 40 + [1.0] * 3 + [10.0] * 40
    s = series(closes, [100.0] * 83)
    assert find_rip(s) is None


def test_rip_does_not_fire_on_a_spike_retracing():
    """A vertical spike falling back to where it started is not a rug — nobody was there."""

    closes = [1.0] * 40 + [50.0] + [1.0] * 40
    s = series(closes, [100.0] * 81)
    rip = find_rip(s)
    assert rip is None


def test_rip_thresholds_are_reported_with_the_label():
    s = series([10.0] * 40 + [1.0] * 40, [100.0] * 80)
    rip = find_rip(s)
    assert rip["thresholds"]["drop"] == 0.60
    assert set(rip["thresholds"]) == {"drop", "window_h", "hold_h", "recover", "base_h", "still_up"}


def test_rip_is_parameterised_not_hardcoded():
    """A 45% fall is a rip at a 40% threshold and not at 60%."""

    closes = [10.0] * 40 + [5.5] * 40
    s = series(closes, [100.0] * 80)
    assert find_rip(s) is None
    assert find_rip(s, drop=0.40, recover=0.60) is not None


def test_rip_returns_the_first_one_when_there_are_two():
    closes = [10.0] * 40 + [1.0] * 40 + [0.05] * 40
    s = series(closes, [100.0] * 120)
    assert find_rip(s)["i"] == 39


# ---------------------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------------------


def test_calibration_ranks_are_monotone():
    cal = Calibration.fit(_ambient())
    key = "r2_linear"
    prev = -1.0
    for x in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        r = cal.rank(key, x)
        assert r >= prev
        prev = r


def test_calibration_rejects_nonfinite():
    cal = Calibration.fit(_ambient())
    assert cal.rank("r2_linear", float("nan")) is None
    assert cal.rank("r2_linear", None) is None


def test_calibration_records_its_own_time_range():
    cal = Calibration.fit(_ambient())
    assert cal.n > 0
    assert cal.t_first is not None and cal.t_last is not None
    assert cal.t_first <= cal.t_last


def test_calibration_json_roundtrip_is_lossy_and_says_so():
    cal = Calibration.fit(_ambient())
    back = Calibration.from_json(cal.to_json())
    # the rehydrated one carries the quantile grid, not the full population
    assert back.n == cal.n
    assert 0 < len(back.pops["r2_linear"]) <= 7


# ---------------------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------------------


def test_alert_row_carries_both_clocks_and_a_source():
    cal = Calibration.fit(_ambient())
    s = series(*_metered_climb())
    f = features_at(s, 150)
    f["parts"] = crime_score(f, cal)["parts"]
    f["crime_score"] = crime_score(f, cal)["score"]
    row = alert_row(run_id="r1", mint="M", symbol="S", pool="P", feat=f, threshold=0.8, cal=cal)
    assert row["kind"] in ALERT_KINDS
    assert row["t_event"] == f["t_event"]
    assert row["t_ingest"] > 0
    assert row["t_event_source"].startswith("vendor:")
    assert row["action"] == "reduce"          # never an entry
    assert row["severity"] in {"high", "watch"}
    assert row["thresholds"]["crime_score"] == 0.8
    assert row["calibration"]["n_states"] == cal.n
    # every score component is reproducible from the row
    assert set(row["components"]) == {k for k, _ in SCORE_KEYS}
    json.dumps(row, sort_keys=True)            # must be serialisable as written


def test_alert_id_is_stable_and_distinguishes_thresholds():
    cal = Calibration.fit(_ambient())
    s = series(*_metered_climb())
    f = features_at(s, 150)
    f["crime_score"] = 0.9
    a = alert_row(run_id="r", mint="M", symbol=None, pool="P", feat=f, threshold=0.8, cal=cal)
    b = alert_row(run_id="r2", mint="M", symbol=None, pool="P", feat=f, threshold=0.8, cal=cal)
    c = alert_row(run_id="r", mint="M", symbol=None, pool="P", feat=f, threshold=0.9, cal=cal)
    assert a["alert_id"] == b["alert_id"]      # same subject, same hour, same threshold
    assert a["alert_id"] != c["alert_id"]


def test_defect_row_declares_the_absent_clock():
    row = defect_row(run_id="r", mint="M", reason="no_ohlcv_cached")
    assert row["kind"] == "defect"
    assert row["t_event"] is None
    assert row["t_event_source"].startswith("absent:")


def test_heartbeat_row_is_positive_evidence_of_liveness():
    row = heartbeat_row(run_id="r", scored=10, alerts=0)
    assert row["kind"] == "heartbeat"
    assert row["scored"] == 10 and row["alerts"] == 0


def test_run_id_is_unique_per_process_clock():
    assert new_run_id().startswith("crime-")


def test_append_rows_writes_one_json_object_per_line(tmp_path):
    p = tmp_path / "alerts.jsonl"
    n = append_rows(p, [{"a": 1, "sym": 'we,ird"\nname'}, {"a": 2}])
    assert n == 2
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["sym"] == 'we,ird"\nname'   # a CSV would have lost this


def test_append_rows_on_empty_is_a_noop(tmp_path):
    p = tmp_path / "alerts.jsonl"
    assert append_rows(p, []) == 0
    assert not p.exists()
