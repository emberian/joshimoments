from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, qualified_sha256_bytes
from .errors import ManifestError


@dataclass(frozen=True, slots=True)
class SpecBundle:
    dataset: dict[str, Any]
    feature: dict[str, Any]
    label: dict[str, Any]
    dataset_digest: str
    feature_digest: str
    label_digest: str


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON key in spec: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ManifestError(f"non-finite JSON number is forbidden in spec: {value}")


def _load(path: str | Path, expected_keys: set[str], contract: str) -> tuple[dict[str, Any], str]:
    spec_path = Path(path)
    raw = spec_path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ManifestError(f"spec exceeds 1 MiB: {spec_path}")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError(f"spec is not valid UTF-8 JSON: {spec_path}") from error
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ManifestError(f"spec has a non-canonical shape: {spec_path}")
    if value["contract"] != contract:
        raise ManifestError(f"unsupported spec contract: {value['contract']!r}")
    return value, qualified_sha256_bytes(canonical_json_bytes(value))


def load_spec_bundle(
    dataset_path: str | Path, feature_path: str | Path, label_path: str | Path
) -> SpecBundle:
    feature, feature_digest = _load(
        feature_path,
        {
            "contract",
            "spec_id",
            "version",
            "entity_unit",
            "feature_cutoff",
            "features",
            "post_cut_fields_forbidden",
            "missingness_states",
            "claim_scope",
        },
        "joshi.analysis.feature_spec/v1",
    )
    label, label_digest = _load(
        label_path,
        {
            "contract",
            "spec_id",
            "version",
            "at_risk_unit",
            "horizon_minutes",
            "competing_risks",
            "censoring_semantics",
            "label_observation_cutoff",
        },
        "joshi.analysis.label_spec/v1",
    )
    dataset, dataset_digest = _load(
        dataset_path,
        {
            "contract",
            "spec_id",
            "version",
            "row_unit",
            "choice_set_kind",
            "feature_spec_id",
            "label_spec_id",
            "train_before",
            "validation_start",
            "validation_end",
            "embargo_policy",
        },
        "joshi.analysis.dataset_spec/v1",
    )
    if (
        feature["entity_unit"] != "decision_candidate"
        or feature["feature_cutoff"] != "decision_available_at"
        or feature["claim_scope"] != "descriptive_only_not_predictive_or_strategy_claim"
    ):
        raise ManifestError("feature spec weakens the decision-time descriptive boundary")
    if (
        label["at_risk_unit"] != "selected_decision_candidate"
        or label["censoring_semantics"] != "right_censored_is_unknown_not_no_event"
        or set(label["competing_risks"]) != {"drawdown_stop", "liquidity_exit", "profit_target"}
    ):
        raise ManifestError("label spec collapses risk sets or censoring semantics")
    if (
        dataset["row_unit"] != "decision_candidate"
        or dataset["choice_set_kind"] != "eligible"
        or dataset["feature_spec_id"] != feature["spec_id"]
        or dataset["label_spec_id"] != label["spec_id"]
    ):
        raise ManifestError("dataset spec does not close its feature/label references")
    train_before = _timestamp(dataset["train_before"], "train_before")
    validation_start = _timestamp(dataset["validation_start"], "validation_start")
    validation_end = _timestamp(dataset["validation_end"], "validation_end")
    _timestamp(label["label_observation_cutoff"], "label_observation_cutoff")
    if not train_before <= validation_start < validation_end:
        raise ManifestError("temporal train/validation partition is not ordered")
    return SpecBundle(
        dataset=dataset,
        feature=feature,
        label=label,
        dataset_digest=dataset_digest,
        feature_digest=feature_digest,
        label_digest=label_digest,
    )


def _timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) != 27:
        raise ManifestError(f"{context} must be canonical microsecond UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ManifestError(f"{context} is invalid") from error
