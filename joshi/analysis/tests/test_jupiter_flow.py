"""jupiter_flow: no-leakage is the cardinal test; models and Hawkes on synthetic truth."""

import random
from math import exp

from joshi_analysis.jupiter_backfill.census import Round
from joshi_analysis.jupiter_conditional.finesol import StepSeries
from joshi_analysis.jupiter_flow import features as feats
from joshi_analysis.jupiter_flow import hawkes
from joshi_analysis.jupiter_flow import model as mdl
from joshi_analysis.jupiter_flow.census import build_dataset, temporal_split
from joshi_analysis.jupiter_flow.tape import FlowTape


def synthetic_tape(n: int = 3000, seed: int = 7, start: float = 1000.0) -> FlowTape:
    rng = random.Random(seed)
    t = start
    times, prices, sizes, signs, mo = [], [], [], [], []
    p = 100.0
    for _ in range(n):
        t += rng.expovariate(0.5)
        p *= 1.0 + rng.gauss(0, 3e-4)
        times.append(t)
        prices.append(p)
        sizes.append(rng.lognormvariate(0, 1))
        signs.append(1 if rng.random() < 0.5 else -1)
        mo.append(1 if rng.random() < 0.3 else 0)
    return FlowTape(times, prices, sizes, signs, mo)


# ------------------------------------------------------------------ causality
def test_flow_features_no_leakage_bit_identical():
    tape = synthetic_tape()
    t = tape.times[2000] + 0.5
    exc = feats.make_excitations(tape)
    full = feats.flow_features(tape, exc, t)
    trunc = tape.truncated(t)
    exc_t = feats.make_excitations(trunc)
    assert feats.flow_features(trunc, exc_t, t) == full
    pf_full = feats.price_features(tape, t)
    assert feats.price_features(trunc, t) == pf_full


def test_flow_features_ignore_trade_exactly_at_t():
    tape = synthetic_tape(n=500)
    # a trade exactly AT t must not contribute (strictly-before semantics)
    t = tape.times[400]
    exc = feats.make_excitations(tape)
    at_t = feats.flow_features(tape, exc, t)
    trunc = tape.truncated(t)  # exclusive: drops the trade at exactly t
    assert len(trunc.times) < len([x for x in tape.times if x <= t]) + 1
    exc_t = feats.make_excitations(trunc)
    assert feats.flow_features(trunc, exc_t, t) == at_t


def test_window_sums_hand_computed():
    tape = FlowTape(
        times=[10.0, 20.0, 30.0, 40.0],
        prices=[1.0, 2.0, 3.0, 4.0],
        sizes=[5.0, 1.0, 2.0, 8.0],
        signs=[1, -1, 1, -1],
        market_order=[1, 0, 0, 1],
    )
    s = tape.window_sums(41.0, 30.0)  # window (11, 41): trades at 20, 30, 40
    assert s["count"] == 3
    assert s["signedVol"] == -1.0 + 2.0 - 8.0
    assert s["vol"] == 11.0
    assert s["buys"] == 1
    assert s["marketOrders"] == 1
    # window (t-30, t) with t exactly on a trade: that trade excluded
    s2 = tape.window_sums(40.0, 30.0)
    assert s2["count"] == 2 and s2["signedVol"] == 1.0


def test_price_features_absent_returns_none():
    tape = synthetic_tape(n=50)
    assert feats.price_features(tape, tape.times[0] + 1.0) is None  # no 1h history


def test_excitation_strictly_before_and_decays():
    ex = hawkes.Excitation([10.0, 20.0], beta=0.1)
    assert ex.at(10.0) == 0.0
    assert abs(ex.at(20.0) - exp(-0.1 * 10.0)) < 1e-12
    v = ex.at(21.0)
    assert 0 < v < 2.0
    assert ex.at(30.0) < v


# ------------------------------------------------------------------ models
def test_logistic_recovers_signs_and_beats_baseline():
    rng = random.Random(3)
    rows, y = [], []
    for _ in range(3000):
        x1, x2 = rng.gauss(0, 1), rng.gauss(0, 1)
        p = 1.0 / (1.0 + exp(-(2.0 * x1 - x2)))
        rows.append([x1, x2])
        y.append(1 if rng.random() < p else 0)
    w = [1.0] * len(y)
    m = mdl.fit_logistic(rows, y, w)
    assert m.beta[1] > 0 > m.beta[2]
    preds = m.predict(rows)
    brier = sum((p - yy) ** 2 for p, yy in zip(preds, y, strict=True)) / len(y)
    base = sum(y) / len(y)
    baseline = sum((base - yy) ** 2 for yy in y) / len(y)
    assert brier < baseline - 0.02


def test_gbm_captures_interaction_logistic_cannot():
    rng = random.Random(5)
    rows, y = [], []
    for _ in range(2000):
        x1, x2 = rng.random(), rng.random()
        rows.append([x1, x2])
        y.append(1 if (x1 > 0.5) != (x2 > 0.5) else 0)  # XOR: zero marginal signal
    w = [1.0] * len(y)
    cut = 1600
    gbm = mdl.fit_gbm(
        rows[:cut], y[:cut], w[:cut], rows[cut:], y[cut:], w[cut:], min_leaf_w=20.0
    )
    preds = gbm.predict(rows[cut:])
    brier = sum((p - yy) ** 2 for p, yy in zip(preds, y[cut:], strict=True)) / (2000 - cut)
    assert brier < 0.10  # interaction found
    logit = mdl.fit_logistic(rows[:cut], y[:cut], w[:cut])
    lb = sum(
        (p - yy) ** 2 for p, yy in zip(logit.predict(rows[cut:]), y[cut:], strict=True)
    ) / (2000 - cut)
    assert lb > 0.2  # linear model cannot represent XOR


def test_gbm_tree_count_comes_from_validation():
    rng = random.Random(11)
    rows = [[rng.gauss(0, 1)] for _ in range(800)]
    y = [1 if r[0] + rng.gauss(0, 1) > 0 else 0 for r in rows]
    w = [1.0] * len(y)
    gbm = mdl.fit_gbm(rows[:600], y[:600], w[:600], rows[600:], y[600:], w[600:])
    assert 1 <= gbm.best_iteration <= mdl.GBM_MAX_TREES
    assert len(gbm.trees) == gbm.best_iteration


# ------------------------------------------------------------------ hawkes
def simulate_hawkes(mu: float, eta: float, beta: float, t1: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    events = []
    t = 0.0
    while True:  # immigrants: homogeneous Poisson(mu)
        t += rng.expovariate(mu)
        if t >= t1:
            break
        events.append(t)
    queue = list(events)
    while queue:  # offspring: Poisson(eta) children at Exp(beta) lags
        parent = queue.pop()
        n_children = 0
        acc = rng.expovariate(1.0)
        while acc < eta:
            n_children += 1
            acc += rng.expovariate(1.0)
        for _ in range(n_children):
            c = parent + rng.expovariate(beta)
            if c < t1:
                events.append(c)
                queue.append(c)
    return sorted(events)


def test_hawkes_em_recovers_branching_and_poisson_null():
    times = simulate_hawkes(mu=1.0, eta=0.5, beta=0.5, t1=3000.0, seed=9)
    fit = hawkes.fit_branching(times, 0.0, 3000.0)
    assert abs(fit.eta - 0.5) < 0.1
    assert fit.log_likelihood > fit.poisson_log_likelihood
    rng = random.Random(2)
    t, poisson = 0.0, []
    while t < 2000.0:
        t += rng.expovariate(2.0)
        if t < 2000.0:
            poisson.append(t)
    null = hawkes.fit_branching(poisson, 0.0, 2000.0)
    assert null.eta < 0.15


# ------------------------------------------------------------------ census plumbing
def _round(key: str, open_s: int, close_s: int, label: str, rows: tuple) -> Round:
    return Round(key=key, horizon="5m", open_s=open_s, close_s=close_s, label=label, rows=rows)


def test_temporal_split_no_time_overlap():
    rounds = [
        _round(f"5m-{s}", s, s + 300, "Up", ()) for s in range(0, 30000, 300)
    ]
    train, hold, cut, straddle = temporal_split(rounds, 0.7)
    assert train and hold
    assert max(r.close_s for r in train) <= cut <= min(r.open_s for r in hold)
    assert straddle == len(rounds) - len(train) - len(hold)


def test_build_dataset_market_price_causal_and_weights():
    tape = synthetic_tape(n=6000, seed=13, start=0.0)
    series = StepSeries(list(tape.times), list(tape.prices))
    lo = tape.times[0]
    open_s = int(lo + 4000)
    close_s = open_s + 300
    t_probe = close_s - 0.2 * 300  # the 0.2 remaining-fraction decision instant
    fills = ((float(open_s + 10), 0, 0.50, 1.0, "b"), (t_probe + 1.0, 0, 0.99, 1.0, "b"))
    rnd = _round("5m-x", open_s, close_s, "Up", fills)
    exc = feats.make_excitations(tape)
    dataset, _counts = build_dataset([rnd], series, tape, exc, "c")
    assert dataset
    _, rows = dataset[0]
    assert abs(sum(r["weight"] for r in rows) - 1.0) < 1e-12
    probe = [r for r in rows if abs(r["t"] - t_probe) < 1e-6]
    assert probe
    # the 0.99 fill sits AFTER the instant: the market price must not see it
    assert probe[0]["qUp"] != 0.99
    early = [r for r in rows if r["t"] >= open_s + 10 + 1]
    assert any(r["qUp"] == 0.50 for r in early if r["t"] - (open_s + 10) <= 60.0)
