"""Tests for the conditional-settlement study — synthetic tapes only, no network."""

from __future__ import annotations

import math

from joshi_analysis.jupiter_conditional import rules, state, surface
from joshi_analysis.jupiter_conditional.finesol import StepSeries


def flat(price: float, start: float, end: float, step: float = 1.0) -> StepSeries:
    times = []
    t = start
    while t <= end:
        times.append(t)
        t += step
    return StepSeries(times, [price] * len(times))


def concat(*series: StepSeries) -> StepSeries:
    times: list[float] = []
    prices: list[float] = []
    for s in series:
        times += s.times
        prices += s.prices
    order = sorted(range(len(times)), key=lambda i: times[i])
    return StepSeries([times[i] for i in order], [prices[i] for i in order])


def test_step_integral_and_twap():
    s = StepSeries([0.0, 10.0, 20.0], [100.0, 110.0, 90.0])
    assert s.integral(0, 30) == 100 * 10 + 110 * 10 + 90 * 10
    assert s.twap(0, 30) == 100.0
    assert s.integral(5, 15) == 100 * 5 + 110 * 5
    assert s.price_at(9.99) == 100.0 and s.price_at(10.0) == 110.0
    assert s.price_at(-1) is None
    assert s.price_at(500.0) is None  # staleness beyond 120s


def test_rules_disagree_on_dip_recover_path():
    # [0, 300): price 100 until 150, then 90 until 295, then 104 at the close.
    tape = concat(flat(100.0, -120, 149), flat(90.0, 150, 294), flat(104.0, 295, 300))
    up = {r: rules.settle_up(tape, 0.0, 300.0, r) for r in rules.RULES}
    assert up["c"] is True  # endpoint 104 >= 100
    assert up["a"] is False  # whole-window twap ~95 < 100
    assert up["b"] is False  # twap60(300) ~= (55*90+5*104)/60 < twap60(0) = 100
    assert up["d"] is False


def test_rule_b_locked_last_minute_math():
    # flat 100, then the last 30 s spike to 106: twap60(C) = (30*100+30*106)/60 = 103 > 100.
    tape = concat(flat(100.0, -120, 269), flat(106.0, 270, 300))
    assert rules.settle_up(tape, 0.0, 300.0, "b") is True
    m = rules.final_margin_bps(tape, 0.0, 300.0, "b")
    assert abs(m - 300.0) < 1.0  # ~3% of 100 in bps... no: 3/100 = 300 bps
    # and a tie resolves Up: constant tape.
    assert rules.settle_up(flat(100.0, -120, 300), 0.0, 300.0, "b") is True


def test_state_no_leakage_and_margin_mechanics():
    tape = concat(flat(100.0, -3700, 149), flat(98.0, 150, 400))
    t = 240.0
    st_full = state.decision_state(tape, 0.0, 300.0, t, "a")
    st_trunc = state.decision_state(tape.truncated(t), 0.0, 300.0, t, "a")
    assert st_full == st_trunc  # bit-identical despite the future being removed
    # mechanics: elapsed twap = (150*100 + 90*98)/240 = 99.25; a1 = -75 bps; a2 = -200 bps.
    assert abs(st_full.a1_bps - (-75.0)) < 1e-6
    assert abs(st_full.a2_bps - (-200.0)) < 1e-6
    assert abs(st_full.gap_bps - (-125.0)) < 1e-6
    # m = a2 + (e/r)*a1 = -200 + 4*(-75) = -500 = bps(98) - bps(req): the last 60 s must
    # average req = 103 to tie (bps(103) = +300; -200 - 300 = -500).
    assert abs(st_full.m_bps - (-500.0)) < 1e-6
    req_avg = (300 * 100.0 - tape.integral(0.0, t)) / 60.0
    assert abs(req_avg - 103.0) < 1e-9
    # d (v1.1 primary axis): freeze-now settlement = (e*a1 + r*a2)/H = -100 bps, Down side.
    assert abs(st_full.d_bps - (-100.0)) < 1e-6
    assert st_full.current_side_up is False


def test_margin_zero_is_exactly_the_tie_boundary():
    # remainder at exactly the required average -> tie -> Up under rule (a).
    head = concat(flat(100.0, -120, 149), flat(98.0, 150, 239))
    st = state.decision_state(head, 0.0, 300.0, 240.0, "a")
    assert st.m_bps < 0
    tie_tape = concat(head, flat(103.0, 240.0, 300))  # avg of last 60 s = 103 = required
    assert rules.settle_up(tie_tape, 0.0, 300.0, "a") is True  # exact tie -> Up
    below = concat(head, flat(102.9, 240.0, 300))
    assert rules.settle_up(below, 0.0, 300.0, "a") is False


def test_gate_verdict_precedence_and_stop():
    tape = concat(flat(100.0, -120, 149), flat(90.0, 150, 294), flat(104.0, 295, 300))
    labeled = [("E1", 0, 300, "Down")]  # matches a/b/d, not c
    report = rules.gate({"kraken": tape}, labeled)
    assert report["verdict"]["decision"] == "PROCEED"
    assert report["verdict"]["rule"] == "b"  # precedence, not score
    report2 = rules.gate({"kraken": tape}, [("E1", 0, 300, "Up")])  # only c matches
    assert report2["verdict"]["rule"] == "c"
    stop = rules.gate({"kraken": StepSeries([], [])}, labeled)
    assert stop["verdict"]["decision"] == "STOP"


def test_d_bins_and_abs_bands_cover_the_line():
    edges_hit = {surface.d_bin(x) for x in (-100, -30, -10, -2, -1.5, 0, 0.5, 3, 9, 20, 31)}
    assert surface.d_bin(0.0) == 6  # (-1, 0]
    assert surface.d_bin(0.4) == 7
    assert min(edges_hit) == 0 and max(edges_hit) == len(surface.D_BIN_EDGES)
    assert surface.d_bin_label(0).startswith("<=") and surface.d_bin_label(13).startswith(">")
    assert surface.abs_band(0.5) == 0 and surface.abs_band(-0.5) == 0
    assert surface.abs_band(1.0) == 0  # [0,1]
    assert surface.abs_band(-1.5) == 1 and surface.abs_band(31.0) == len(surface.ABS_D_BANDS) - 1
    assert surface.abs_band_label(0) == "[0,1]" and surface.abs_band_label(6) == ">30"


def _state(d_bps: float, frac: float) -> state.DecisionState:
    return state.DecisionState(
        t=0.0,
        remaining_s=frac * 300,
        remaining_fraction=frac,
        a1_bps=0.0,
        a2_bps=0.0,
        gap_bps=0.0,
        m_bps=d_bps,
        d_bps=d_bps,
        vol_bps=None,
    )


def _window(label_up: bool, reg: str, states: list[state.DecisionState]) -> surface.WindowSample:
    return surface.WindowSample(
        horizon_s=300,
        t_open=0,
        label_up=label_up,
        final_margin_bps=10.0 if label_up else -10.0,
        ambiguous=False,
        regime=reg,
        states=tuple(states),
    )


def test_cross_ev_surface_counts_crosses_and_breakevens():
    # 10 windows sitting Down (d=-2) late; 3 settle Up (= 3 crosses).
    windows = [_window(i < 3, "flat", [_state(-2.0, 0.1)]) for i in range(10)]
    rows = surface.cross_ev_surface(windows)
    assert len(rows) == 1
    row = rows[0]
    assert row["absDBandBps"] == "(1,2]" and row["n"] == 10 and row["crossed"] == 3
    assert row["sideDown"] == {"n": 10, "crossed": 3}
    ev15 = row["evPerEntry"]["0.15"]
    assert abs(ev15["breakevenCrossRate"] - 0.158925) < 1e-9
    assert ev15["clearsExplicitFee"] is True  # 0.30 > 0.158925
    assert abs(ev15["evPerContract"] - (0.3 - 0.158925)) < 1e-9
    assert row["evPerEntry"]["0.50"]["clearsExplicitFee"] is False


def test_trend_claim_cells_one_observation_per_window():
    windows = []
    # up-trend, current side agrees (d>0), near boundary, late: 2 of 5 cross.
    for i in range(5):
        windows.append(_window(i >= 2, "up", [_state(3.0, 0.1), _state(3.0, 0.4)]))
    # up-trend, far from boundary late, none cross.
    for _ in range(4):
        windows.append(_window(True, "up", [_state(40.0, 0.1)]))
    rows = surface.trend_claim(windows)
    near = [r for r in rows if r["distance"] == "near" and r["timing"] == "late"]
    far = [r for r in rows if r["distance"] == "far" and r["timing"] == "late"]
    assert near[0]["currentSideVsTrend"] == "agree"
    assert near[0]["n"] == 5 and near[0]["crossed"] == 2  # label_up False = cross for d>0
    assert far[0]["n"] == 4 and far[0]["crossed"] == 0
    # the 0.4 state produced an "early" cell, not a second late observation
    assert all(r["n"] == 5 for r in rows if r["timing"] == "early")


def test_surface_counts_and_calibration_license():
    # deterministic tape: alternate up/down drifts per window so labels vary.
    parts = []
    for w in range(40):
        base = 100.0 + (0.5 if w % 2 else -0.5)
        parts.append(flat(base, w * 300.0 - 0.5, (w + 1) * 300.0 - 1.0, step=5.0))
    tape = concat(flat(100.0, -3700, -1), *parts)
    ctx = surface.build_context(tape, 300, "a")
    assert ctx["samples"] and ctx["set_a"] and ctx["set_b"]
    report = surface.evaluate_horizon(ctx, 300)
    assert report["windows"]["total"] == len(ctx["samples"])
    pooled = report["calibration"]["pooled"]
    assert pooled["n"] == sum(len(w.states) for w in ctx["set_b"])
    assert 0.0 <= pooled["brier"] <= 1.0
    for row in report["directionSurface"]:
        assert row["n"] >= row["up"] >= 0 and row["wilson95"] is not None
    assert report["crossEvSurface"], "cross/EV surface must be populated"


def test_brier_and_reliability_on_known_probabilities():
    pairs = [(0.9, True)] * 9 + [(0.9, False)] + [(0.1, False)] * 9 + [(0.1, True)]
    score = surface.brier_and_reliability(pairs)
    assert score["n"] == 20
    assert math.isclose(score["ece"], 0.0, abs_tol=1e-9)  # observed matches predicted per bin
    assert math.isclose(score["brier"], (9 * 0.01 + 0.81 + 9 * 0.01 + 0.81) / 20)


def test_regime_buckets():
    tape = concat(flat(100.0, -3700, -1), flat(101.0, 0, 400))
    assert state.regime(tape, 300.0) == "up"  # +100 bps over the hour
    assert state.regime(flat(100.0, -3700, 400), 300.0) == "flat"
    assert state.regime(flat(100.0, 0, 400), 300.0) is None  # no 1h lookback -> absent
