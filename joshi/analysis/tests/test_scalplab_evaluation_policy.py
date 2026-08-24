"""The protocol's honesty is structural: splits, gates, verdicts, and the policy contract."""

import random
from decimal import Decimal

import pytest

from joshi_analysis.scalplab.evaluation import (
    CoinSeries,
    FoldResult,
    brier_score,
    calibration_bins,
    prepare_series,
    run_folds,
    threshold_cells,
    verdicts,
    wilson_lower,
)
from joshi_analysis.scalplab.policy import PolicyError, declared_policy, write_policy
from joshi_analysis.scalplab.tape import TapeEvent, TapeProvenance
from joshi_analysis.scalplab.vocabulary import (
    ONE_TAPE_FITS_NOTHING,
    VERDICT_CANDIDATE,
    VERDICT_INSUFFICIENT,
)


def _provenance(floor=10):
    return TapeProvenance(
        tape_path="/synthetic/tape",
        source_kind="pumpportal_socket",
        source_id="pumpportal.websocket.data.v1",
        n_observations=0,
        n_events=0,
        coins=(),
        coverage_gaps=(),
        full_pages_without_overlap=0,
        arrival_clock="socket_arrival",
        arrival_floor_us=0,
        decision_clock_statement="socket arrival clock",
        venue_floor_bps=floor,
    )


def _series(coin, series_id, n, seed):
    rng = random.Random(seed)
    price = 100.0
    events = []
    for i in range(n):
        side = "buy" if rng.random() < 0.5 else "sell"
        price *= 1.0 + rng.gauss(0, 0.002)
        events.append(
            TapeEvent(
                ordinal=i,
                mint=coin,
                side=side,
                price=Decimal(str(round(price, 6))),
                fill_price=None,
                base_signed=Decimal(1),
                quote_signed=Decimal("0.1") if side == "buy" else Decimal("-0.1"),
                trader=f"T{rng.randrange(5)}",
                venue="pump-amm",
                tx=f"{series_id}-{i}",
                slot=None,
                event_time_us=1_000_000 + i * 400_000,
                arrival_wall_us=1_000_000 + i * 400_000,
            )
        )
    return CoinSeries(coin=coin, series_id=series_id, events=events, provenance=_provenance())


def test_leave_one_coin_out_never_trains_on_the_judged_coin():
    prepared = [
        prepare_series(_series("MMM", "MMM@sock", 120, seed=1), horizons=(5,)),
        prepare_series(_series("MMM", "MMM@polled", 120, seed=2), horizons=(5,)),
        prepare_series(_series("NNN", "NNN@sock", 120, seed=3), horizons=(5,)),
    ]
    folds = run_folds(prepared, horizons=(5,), families=("logit",))
    judged_m = [f for f in folds if f.judged_coin == "MMM"]
    judged_n = [f for f in folds if f.judged_coin == "NNN"]
    assert len(judged_m) == 2  # both MMM series judged, separately
    assert all(f.n_train_coins == 1 for f in judged_m)  # NNN only; the sibling series excluded
    expected_m_events = sum(
        len(p.judged(5)[2]) for p in prepared if p.series.coin == "MMM"
    )
    assert judged_n[0].n_train_events == expected_m_events  # both MMM series train NNN's fold
    assert all(not f.gates_passed for f in folds)  # 2 coins can never pass the gates


def test_metric_arithmetic_on_hand_data():
    predictions = [0.1, 0.9, 0.7, 0.3]
    labels = [0, 1, 0, 0]
    assert brier_score(predictions, labels) == pytest.approx(
        (0.01 + 0.01 + 0.49 + 0.09) / 4
    )
    bins = calibration_bins(predictions, labels, n_bins=10)
    assert bins[1].n == 1 and bins[1].observed_rate == 0.0  # 0.1 lands in [0.1, 0.2)
    assert bins[9].n == 1 and bins[9].observed_rate == 1.0  # 0.9 lands in [0.9, 1.0]
    cells = threshold_cells(predictions, labels)
    cell = next(c for c in cells if c.tau == 0.5)
    assert cell.fired == 2 and cell.hits == 1 and cell.precision == 0.5
    assert wilson_lower(0, 0) == 0.0
    assert 0.0 < wilson_lower(8, 10) < 0.8
    assert wilson_lower(80, 100) > wilson_lower(8, 10)  # more evidence, tighter bound


def _fold(family="logit", gates=True, predictions=(), labels=(), failures=()):
    has = bool(predictions)
    return FoldResult(
        family=family,
        horizon_k=25,
        judged_series="X@sock",
        judged_coin="XXX",
        n_train_coins=5,
        n_train_events=6000,
        n_eval_events=len(labels),
        n_eval_pos=sum(labels),
        gates_passed=gates,
        gate_failures=tuple(failures),
        base_rate=sum(labels) / len(labels) if labels else None,
        brier=brier_score(list(predictions), list(labels)) if has else None,
        calibration=tuple(calibration_bins(list(predictions), list(labels))) if has else (),
        cells=tuple(threshold_cells(list(predictions), list(labels))) if has else (),
        predictions=tuple(predictions),
        labels=tuple(labels),
    )


def test_verdict_candidate_when_the_preregistered_rule_clears():
    predictions = [0.9] * 30 + [0.1] * 70
    labels = [1] * 30 + [0] * 70
    fold = _fold(predictions=predictions, labels=labels)
    (verdict,) = verdicts([fold])
    assert verdict.verdict == VERDICT_CANDIDATE
    assert 0.5 in verdict.candidate_taus
    assert verdict.pooled_base_rate == pytest.approx(0.3)


def test_verdict_insufficient_carries_the_harness_vocabulary():
    fold = _fold(gates=False, failures=("train coins 1 < 5 required for logit",))
    (verdict,) = verdicts([fold])
    assert verdict.verdict == VERDICT_INSUFFICIENT
    assert verdict.honesty == ONE_TAPE_FITS_NOTHING
    assert "train coins" in verdict.reason


def _policy_kwargs(**overrides):
    kwargs = {
        "family": "logit",
        "model_params": {"family": "logit", "weights": [0.1], "bias": 0.0},
        "horizon_k": 25,
        "threshold": 0.7,
        "venue_floor_bps": 250,
        "decision_clock": "socket arrival clock",
        "exit_alarm": "CUSUM down-alarm",
        "tape_provenances": [{"tapePath": "/t"}],
        "evaluation": {"verdict": VERDICT_CANDIDATE},
        "author_knowledge": "I watched this coin collapse before writing anything.",
    }
    kwargs.update(overrides)
    return kwargs


def test_policy_contract_roundtrip(tmp_path):
    doc = declared_policy(**_policy_kwargs())
    assert doc["decision"]["executionDelayEvents"] == 1
    assert "r1" in doc["features"]
    path = write_policy(tmp_path / "p.json", doc)
    assert path.exists()


def test_policy_refuses_blank_author_knowledge():
    with pytest.raises(PolicyError):
        declared_policy(**_policy_kwargs(author_knowledge="   "))


def test_policy_refuses_out_of_range_threshold_and_tampered_honesty(tmp_path):
    with pytest.raises(PolicyError):
        declared_policy(**_policy_kwargs(threshold=1.0))
    doc = declared_policy(**_policy_kwargs())
    doc["honesty"]["oneTapeFitsNothing"] = "it is probably fine"
    with pytest.raises(PolicyError):
        write_policy(tmp_path / "never-written.json", doc)
