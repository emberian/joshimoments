from __future__ import annotations

import math
from collections import defaultdict

import pyarrow as pa

from .canonical import require_qualified_sha256
from .contracts import DECISION_EVALUATION_SCHEMA, PREDICTION_CLAIM_SCOPE, PREDICTION_SCHEMA
from .errors import ManifestError, TemporalLeakageError

EVALUATION_VERSION = "decision-choice-evaluation/v1"


def evaluate_prediction_artifact(predictions: pa.Table, dataset_rows: pa.Table) -> pa.Table:
    """Validate an offline prediction contract and return decision-keyed evaluation rows.

    This is a contract checker, not a trained model or strategy evaluation. In particular it
    requires full witnessed choice-universe coverage and preserves censoring/competing-risk state.
    """

    if not predictions.schema.equals(PREDICTION_SCHEMA, check_metadata=True):
        raise ManifestError("prediction artifact violates its exact Arrow schema")
    dataset = dataset_rows.to_pylist()
    predicted = predictions.to_pylist()
    dataset_by_decision: dict[str, list[dict[str, object]]] = defaultdict(list)
    predictions_by_decision: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in dataset:
        dataset_by_decision[row["decision_id"]].append(row)
    seen_predictions: set[tuple[str, str]] = set()
    model_contracts: set[tuple[object, ...]] = set()
    for row in predicted:
        key = (row["decision_id"], row["candidate_id"])
        if key in seen_predictions:
            raise ManifestError("prediction artifact duplicates a decision candidate")
        seen_predictions.add(key)
        predictions_by_decision[row["decision_id"]].append(row)
        model_contracts.add(
            (
                row["model_id"],
                row["model_version"],
                row["ensemble_id"],
                row["dataset_id"],
                row["score_name"],
                row["calibration_artifact_id"],
                row["calibration_artifact_digest"],
            )
        )
        if not all(
            math.isfinite(row[field])
            for field in ("score_value", "uncertainty_lower", "uncertainty_upper")
        ):
            raise ManifestError("prediction score/uncertainty must be finite")
        if not row["uncertainty_lower"] <= row["score_value"] <= row["uncertainty_upper"]:
            raise ManifestError("prediction score lies outside its uncertainty interval")
        if not 0 < row["uncertainty_level_ppm"] < 1_000_000:
            raise ManifestError("uncertainty level must be an interior ppm probability")
        if row["ensemble_member_count"] < 1:
            raise ManifestError("prediction artifact requires at least one named model member")
        if row["claim_scope"] != PREDICTION_CLAIM_SCOPE:
            raise ManifestError("prediction artifact overstates its offline claim scope")
        try:
            require_qualified_sha256(
                row["calibration_artifact_digest"], "calibration_artifact_digest"
            )
        except ValueError as error:
            raise ManifestError(str(error)) from error
    if len(model_contracts) != 1:
        raise ManifestError(
            "one prediction artifact must bind one model/dataset/calibration contract"
        )
    if set(predictions_by_decision) != set(dataset_by_decision):
        raise ManifestError("prediction artifact decision set differs from the dataset")

    output: list[dict[str, object]] = []
    for decision_id, decision_rows in sorted(dataset_by_decision.items()):
        decision_predictions = predictions_by_decision.get(decision_id, [])
        expected_candidates = {row["candidate_id"] for row in decision_rows}
        actual_candidates = {row["candidate_id"] for row in decision_predictions}
        if actual_candidates != expected_candidates:
            raise ManifestError(
                f"prediction universe differs from witnessed choice set for {decision_id}"
            )
        universe_digests = {row["universe_digest"] for row in decision_rows}
        prediction_digests = {row["universe_digest"] for row in decision_predictions}
        if len(universe_digests) != 1 or prediction_digests != universe_digests:
            raise ManifestError("prediction universe digest does not bind the witnessed set")
        decision_cut = decision_rows[0]["decision_available_at"]
        if any(row["information_cutoff"] != decision_cut for row in decision_predictions):
            raise TemporalLeakageError("prediction information cutoff differs from decision cut")
        selected = next(
            (row for row in decision_rows if row["is_operator_selected"]),
            None,
        )
        ranked = sorted(
            decision_predictions,
            key=lambda row: (-row["score_value"], row["candidate_id"]),
        )
        selected_prediction = (
            next(
                row
                for row in decision_predictions
                if selected is not None and row["candidate_id"] == selected["candidate_id"]
            )
            if selected is not None
            else None
        )
        selected_rank = (
            next(
                rank
                for rank, row in enumerate(ranked, start=1)
                if row["candidate_id"] == selected["candidate_id"]
            )
            if selected is not None
            else None
        )
        output.append(
            {
                "decision_id": decision_id,
                "universe_digest": next(iter(universe_digests)),
                "candidate_count": len(decision_rows),
                "prediction_count": len(decision_predictions),
                "selected_candidate_id": selected["candidate_id"] if selected else None,
                "selected_score": (
                    selected_prediction["score_value"] if selected_prediction else None
                ),
                "selected_score_rank": selected_rank,
                "label_status": selected["label_status"] if selected else "no_selection",
                "event_kind": selected["label_event_kind"] if selected else None,
                "is_censored": selected["label_is_censored"] if selected else None,
                "evaluation_version": EVALUATION_VERSION,
            }
        )
    return pa.Table.from_pylist(output, schema=DECISION_EVALUATION_SCHEMA)
