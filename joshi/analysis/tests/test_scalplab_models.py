"""Each zoo member must earn its place on synthetic data with known answers."""

import math
import random
from itertools import pairwise

import pytest

from joshi_analysis.scalplab.analog import fit_analog
from joshi_analysis.scalplab.changepoint import cusum_trace
from joshi_analysis.scalplab.hawkes import (
    HawkesParams,
    dither_times,
    fit_hawkes,
    fit_hawkes_classifier,
    hawkes_loglik,
)
from joshi_analysis.scalplab.logit import fit_logistic

# --- CUSUM --------------------------------------------------------------------------------------


def test_cusum_alarms_after_a_mean_shift_not_before():
    rng = random.Random(7)
    returns = [rng.gauss(0, 1) for _ in range(250)] + [rng.gauss(2.5, 1) for _ in range(40)]
    trace = cusum_trace(returns)
    early_alarms = [i for i, p in enumerate(trace[:250]) if p.alarm_up]
    late_alarms = [i for i, p in enumerate(trace) if p.alarm_up and i >= 250]
    assert not early_alarms
    assert late_alarms and late_alarms[0] < 265


# --- logistic -----------------------------------------------------------------------------------


def _logit_data(n, seed):
    rng = random.Random(seed)
    vectors, labels = [], []
    for _ in range(n):
        x = [rng.gauss(0, 1) for _ in range(3)]
        p = 1.0 / (1.0 + math.exp(-(2.0 * x[0] - x[1])))
        vectors.append(x)
        labels.append(1 if rng.random() < p else 0)
    return vectors, labels


def test_logistic_recovers_a_separable_signal():
    vectors, labels = _logit_data(1200, seed=3)
    model = fit_logistic(vectors, labels)
    assert model.converged
    predictions = model.predict_proba(vectors)
    brier = sum((p - y) ** 2 for p, y in zip(predictions, labels, strict=True)) / len(labels)
    assert brier < 0.2
    # the informative weight dominates and points the right way (standardized space)
    assert model.weights[0] > 0 and abs(model.weights[0]) > abs(model.weights[2])


def test_logistic_survives_single_class_training():
    vectors = [[float(i), 1.0] for i in range(40)]
    model = fit_logistic(vectors, [0] * 40)
    assert max(model.predict_proba(vectors)) < 0.2


# --- analog -------------------------------------------------------------------------------------


def test_analog_forecast_is_the_neighbourhood_label_rate():
    rng = random.Random(5)
    vectors = [[rng.gauss(2, 0.3)] for _ in range(200)] + [[rng.gauss(-2, 0.3)] for _ in range(200)]
    labels = [1] * 200 + [0] * 200
    model = fit_analog(vectors, labels, k=25)
    high, low = model.forecast([[2.0], [-2.0]])
    assert high.probability > 0.9
    assert low.probability < 0.1
    assert high.neighbours == 25


def test_analog_memory_cap_thins_deterministically():
    vectors = [[float(i)] for i in range(1000)]
    labels = [i % 2 for i in range(1000)]
    model = fit_analog(vectors, labels, k=5, cap=100)
    assert len(model.memory) == 100
    again = fit_analog(vectors, labels, k=5, cap=100)
    assert model.memory == again.memory


# --- hawkes -------------------------------------------------------------------------------------


def _poisson_sequence(rate, n, seed):
    rng = random.Random(seed)
    t = 0.0
    times, marks = [], []
    for _ in range(n):
        t += rng.expovariate(rate)
        times.append(t)
        marks.append(rng.randrange(2))
    return times, marks


def _hawkes_sequence(mu_total, branching, beta, n, seed):
    """Ogata thinning for the symmetric bivariate case (branching matrix all = a/2)."""
    rng = random.Random(seed)
    times, marks = [], []
    t = 0.0
    g = 0.0  # total decayed count, shared because the matrix is symmetric
    last = 0.0
    while len(times) < n:
        lam_max = mu_total + branching * beta * g
        t += rng.expovariate(lam_max)
        g_now = g * math.exp(-beta * (t - last))
        lam_now = mu_total + branching * beta * g_now
        if rng.random() * lam_max <= lam_now:
            times.append(t)
            marks.append(rng.randrange(2))
            g = g_now + 1.0
            last = t
    return times, marks


def test_branching_ratio_closed_form():
    params = HawkesParams(0.1, 0.1, 0.3, 0.3, 0.3, 0.3, 1.0)
    assert params.branching_ratio() == pytest.approx(0.6)


def test_hawkes_mle_separates_exciting_from_poisson():
    exciting = _hawkes_sequence(mu_total=1.0, branching=0.65, beta=2.0, n=600, seed=11)
    poisson = _poisson_sequence(rate=2.0, n=600, seed=12)
    fit_exciting = fit_hawkes([exciting])
    fit_poisson = fit_hawkes([poisson])
    assert fit_exciting.params.branching_ratio() > fit_poisson.params.branching_ratio() + 0.15
    assert fit_poisson.params.branching_ratio() < 0.35


def test_hawkes_loglik_prefers_truth_over_nonsense_on_its_own_data():
    sequence = _hawkes_sequence(mu_total=1.0, branching=0.6, beta=2.0, n=400, seed=21)
    truth = HawkesParams(0.5, 0.5, 0.3, 0.3, 0.3, 0.3, 2.0)
    nonsense = HawkesParams(5.0, 5.0, 0.01, 0.01, 0.01, 0.01, 0.1)
    assert hawkes_loglik(sequence, truth) > hawkes_loglik(sequence, nonsense)


def test_dither_makes_times_strictly_increasing():
    dithered = dither_times([1.0, 1.0, 1.0, 2.0, 2.0])
    assert all(b > a for a, b in pairwise(dithered))
    assert dithered[0] == 1.0


def test_hawkes_classifier_is_causal_and_bounded():
    times, marks = _hawkes_sequence(mu_total=1.0, branching=0.5, beta=2.0, n=300, seed=31)
    labels = [1 if marks[i] == 0 else 0 for i in range(100, 200)]
    classifier = fit_hawkes_classifier([((times, marks), list(range(100, 200)), labels)])
    probabilities = classifier.predict_proba((times, marks), list(range(100, 200)))
    assert len(probabilities) == 100
    assert all(0.0 < p < 1.0 for p in probabilities)
