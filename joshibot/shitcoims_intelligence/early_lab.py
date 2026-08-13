"""Advisory lab wrapper: record model-free early-coin snapshots as Feature rows.

This module does not fetch, decode, sign, or execute.  The parent collector
supplies already-computed ``EarlyCoinFeatures`` and the observation ids that
justify them.  Amounts stay in the same raw atomic units as ``early_coin``.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime
from typing import Final

from shitcoims_intelligence.early_coin import EarlyCoinFeatures
from shitcoims_intelligence.models import Feature

MODEL_VERSION: Final = "early-coin-lab-v1"
FEATURE_KEY: Final = "early_coin"
MIN_TRADES_TO_COMPUTE: Final = 20
LOW_CONFIDENCE: Final = 0.2
HIGH_CONFIDENCE: Final = 0.4

_SKIP_VALUE_FIELDS: Final = frozenset({"mint", "quality"})


def should_compute(trade_count: int) -> bool:
    """True once a mint has reached the first 20/50/100-style milestone."""

    if not isinstance(trade_count, int) or isinstance(trade_count, bool):
        raise TypeError("trade_count must be an integer")
    if trade_count < 0:
        raise ValueError("trade_count cannot be negative")
    return trade_count >= MIN_TRADES_TO_COMPUTE


def features_to_record(
    features: EarlyCoinFeatures,
    *,
    evidence_observation_ids: tuple[str, ...],
    computed_at: datetime,
) -> Feature:
    """Project one early-coin snapshot into a JSON-safe Feature record."""

    if not isinstance(features, EarlyCoinFeatures):
        raise TypeError("features must be an EarlyCoinFeatures snapshot")
    accepted = features.quality.accepted_trade_count
    return Feature(
        subject_type="token",
        subject_id=features.mint,
        feature_key=FEATURE_KEY,
        value=_feature_value(features),
        computed_at=computed_at,
        model_version=MODEL_VERSION,
        confidence=HIGH_CONFIDENCE if accepted >= MIN_TRADES_TO_COMPUTE else LOW_CONFIDENCE,
        evidence_observation_ids=evidence_observation_ids,
    )


def _feature_value(features: EarlyCoinFeatures) -> dict[str, object]:
    value: dict[str, object] = {}
    for field in dataclasses.fields(features):
        if field.name in _SKIP_VALUE_FIELDS:
            continue
        value[field.name] = _json_safe_number(getattr(features, field.name), field.name)
    value["limitations"] = tuple(features.quality.limitations)
    return value


def _json_safe_number(value: object, name: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} must be a finite number or None")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
