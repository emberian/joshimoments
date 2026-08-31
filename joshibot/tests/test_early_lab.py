from __future__ import annotations

import dataclasses
import inspect
import math
from datetime import UTC, datetime

import pytest

from shitcoims_intelligence.early_coin import compute_early_coin_features
from shitcoims_intelligence.early_lab import (
    FEATURE_KEY,
    HIGH_CONFIDENCE,
    LOW_CONFIDENCE,
    MIN_TRADES_TO_COMPUTE,
    MODEL_VERSION,
    features_to_record,
    should_compute,
)
from shitcoims_intelligence.models import Feature, canonical_json, thaw_json
from shitcoims_intelligence.pump import AdvisoryPumpEvent, PumpSchemaProvenance
from shitcoims_intelligence.pump_layouts import PUMP_PROGRAM_ID

MINT = "mint-1"
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
EVIDENCE = ("obs_pump_trade_1",)


def _event(program_id: str, event_name: str, **fields: object) -> AdvisoryPumpEvent:
    return AdvisoryPumpEvent(
        program_id=program_id,
        event_name=event_name,
        fields=fields,  # type: ignore[arg-type]
        provenance=PumpSchemaProvenance(
            repository="test",
            commit="test",
            idl_path="test",
            idl_sha256="0" * 64,
            discriminator_hex="0" * 16,
        ),
    )


def _pump_trade(
    timestamp: int,
    wallet: str,
    *,
    is_buy: bool,
    quote: int,
    base: int = 100,
    curve_quote: int = 100,
    curve_base: int = 100,
    mint: str = MINT,
) -> AdvisoryPumpEvent:
    return _event(
        PUMP_PROGRAM_ID,
        "TradeEvent",
        mint=mint,
        user=wallet,
        timestamp=timestamp,
        is_buy=is_buy,
        quote_amount=quote,
        sol_amount=quote,
        token_amount=base,
        virtual_quote_reserves=curve_quote,
        virtual_token_reserves=curve_base,
    )


def _features(*events: AdvisoryPumpEvent):
    return compute_early_coin_features(events, mint=MINT)


def test_should_compute_opens_at_the_twenty_trade_milestone() -> None:
    assert should_compute(0) is False
    assert should_compute(19) is False
    assert should_compute(20) is True
    assert should_compute(50) is True
    assert should_compute(100) is True
    with pytest.raises(TypeError, match="integer"):
        should_compute(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="negative"):
        should_compute(-1)


def test_features_to_record_projects_a_low_confidence_token_feature() -> None:
    features = _features(
        _event(PUMP_PROGRAM_ID, "CreateEvent", mint=MINT, timestamp=90),
        _pump_trade(100, "wallet-a", is_buy=True, quote=100),
        _pump_trade(110, "wallet-a", is_buy=True, quote=300),
        _pump_trade(130, "wallet-b", is_buy=False, quote=200, curve_quote=50),
    )

    record = features_to_record(features, evidence_observation_ids=EVIDENCE, computed_at=NOW)
    payload = thaw_json(record.value)

    assert isinstance(record, Feature)
    assert (
        record.subject_type,
        record.subject_id,
        record.feature_key,
        record.model_version,
    ) == ("token", MINT, FEATURE_KEY, MODEL_VERSION)
    assert record.confidence == LOW_CONFIDENCE
    assert record.evidence_observation_ids == EVIDENCE
    assert record.computed_at == NOW
    assert payload["trade_count"] == 3
    assert payload["buy_quote_volume_atomic"] == 400
    assert payload["limitations"] == list(features.quality.limitations)
    assert all(math.isfinite(value) for value in payload.values() if isinstance(value, float))
    canonical_json(record.value)


def test_twenty_accepted_trades_raise_lab_confidence() -> None:
    events = tuple(
        _pump_trade(100 + index, f"wallet-{index % 4}", is_buy=index % 2 == 0, quote=50 + index)
        for index in range(MIN_TRADES_TO_COMPUTE)
    )
    features = _features(*events)

    record = features_to_record(
        features,
        evidence_observation_ids=("obs_batch",),
        computed_at=NOW,
    )

    assert features.quality.accepted_trade_count == MIN_TRADES_TO_COMPUTE
    assert record.confidence == HIGH_CONFIDENCE
    assert thaw_json(record.value)["trade_count"] == MIN_TRADES_TO_COMPUTE


def test_non_finite_numeric_fields_are_omitted_as_none() -> None:
    features = dataclasses.replace(
        _features(_pump_trade(100, "wallet", is_buy=True, quote=10)),
        trade_price_velocity_per_second=math.nan,
        interarrival_cv=math.inf,
    )

    payload = thaw_json(
        features_to_record(features, evidence_observation_ids=EVIDENCE, computed_at=NOW).value
    )

    assert payload["trade_price_velocity_per_second"] is None
    assert payload["interarrival_cv"] is None
    canonical_json({"value": payload})


def test_feature_requires_evidence_and_timezone_aware_time() -> None:
    features = _features(_pump_trade(100, "wallet", is_buy=True, quote=10))

    with pytest.raises(ValueError, match="evidence"):
        features_to_record(features, evidence_observation_ids=(), computed_at=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        features_to_record(
            features,
            evidence_observation_ids=EVIDENCE,
            computed_at=datetime(2026, 8, 12, 12),
        )
    with pytest.raises(TypeError, match="EarlyCoinFeatures"):
        features_to_record(object(), evidence_observation_ids=EVIDENCE, computed_at=NOW)  # type: ignore[arg-type]


def test_early_lab_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import early_lab

    source = inspect.getsource(early_lab)
    assert "shitcoims_sentinel.executor" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source
