from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any

import pyarrow as pa

from ..canonical import (
    canonical_json_bytes,
    iso_utc,
    logical_table_sha256,
    qualified_sha256_bytes,
)
from ..errors import CoverageError, ManifestError, TemporalLeakageError
from .contracts import (
    CANDIDATE_CLAIM_SCOPE,
    CANDIDATE_DIAGNOSTIC_SCHEMA,
    KERNEL_CHOICE_MEMBER_SCHEMA,
    KERNEL_CLAIM_SCOPE,
    KERNEL_ESTIMATE_SCHEMA,
    KERNEL_OBSERVATION_SCHEMA,
    RISK_COHORT_SCHEMA,
)

ESTIMATOR_ID = "marked_wallet_cluster_response_kernel"
ESTIMATOR_VERSION = "1"
CONFIGURATION = {
    "estimator": "equal_weight_wallet_cluster_mean",
    "interval": "normal_approximation_over_wallet_means",
    "interval_level_ppm": "950000",
    "minimum_wallets_for_overlap": "2",
    "minimum_coverage_ppm": "800000",
    "hawkes_screen_window_us": "1800000000",
    "risk_estimator": "aalen_johansen_candidate_screen",
}
CONFIGURATION_DIGEST = qualified_sha256_bytes(canonical_json_bytes(CONFIGURATION))
RESPONSE_UNITS = {
    "trade_intensity_delta": "events_per_minute_ppm",
    "signed_flow": "base_asset_atoms",
    "liquidity_response": "quote_asset_atoms",
    "attention_response": "attention_events_per_minute_ppm",
    "price_response": "return_ppm",
}


def _digest_record(row: dict[str, Any], occurrence_field: str) -> str:
    material = {
        key: iso_utc(value) if isinstance(value, datetime) else value
        for key, value in row.items()
        if key != occurrence_field
    }
    return qualified_sha256_bytes(canonical_json_bytes(material))


def kernel_input_identity(
    observations: pa.Table, choice_members: pa.Table, risk_cohorts: pa.Table
) -> tuple[str, str]:
    components = {
        "observations": logical_table_sha256(observations, ["kernel_observation_id"]),
        "choice_members": logical_table_sha256(
            choice_members, ["decision_id", "candidate_id", "set_kind"]
        ),
        "risk_cohorts": logical_table_sha256(risk_cohorts, ["cohort_id"]),
    }
    logical_digest = qualified_sha256_bytes(canonical_json_bytes(components))
    snapshot_id = qualified_sha256_bytes(
        canonical_json_bytes(
            {
                "fixture_contract": "joshi.analysis.kernel-synthetic-input/v1",
                "logical_digest": logical_digest,
            }
        )
    )
    return snapshot_id, logical_digest


def _eligible_input_identity(
    eligible: list[dict[str, Any]],
    choice_members: pa.Table,
    eligible_risks: list[dict[str, Any]],
    fit_cutoff: datetime,
) -> tuple[str, str]:
    observations = pa.Table.from_pylist(eligible, schema=KERNEL_OBSERVATION_SCHEMA)
    choices = pa.Table.from_pylist(
        [row for row in choice_members.to_pylist() if row["available_at"] <= fit_cutoff],
        schema=KERNEL_CHOICE_MEMBER_SCHEMA,
    )
    risks = pa.Table.from_pylist(eligible_risks, schema=RISK_COHORT_SCHEMA)
    return kernel_input_identity(observations, choices, risks)


def _context_key(row: dict[str, Any]) -> str:
    if row["context_status"] != "selected_as_known_version":
        return f"context_status={row['context_status']}"
    community = row["community_id"] if row["community_id"] is not None else "<absent>"
    return (
        f"territory={row['territory_id']}|community={community}|venue={row['venue_id']}|"
        f"lifecycle={row['lifecycle_state']}"
    )


def _risk_context_key(row: dict[str, Any]) -> str:
    caller = row["caller_class"] if row["caller_class"] is not None else "<unattributed>"
    territory = row["territory_id"] if row["territory_id"] is not None else "<unassigned>"
    return f"caller={caller}|territory={territory}"


def _validate_choice_sets(choice_members: pa.Table) -> dict[str, dict[str, Any]]:
    if not choice_members.schema.equals(KERNEL_CHOICE_MEMBER_SCHEMA, check_metadata=True):
        raise ManifestError("kernel choice members violate their exact Arrow schema")
    by_decision: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in choice_members.to_pylist():
        if row["set_kind"] != "eligible":
            raise ManifestError("kernel fixture accepts only explicit eligible choice members")
        by_decision[row["decision_id"]].append(row)
    closure: dict[str, dict[str, Any]] = {}
    for decision_id, rows in by_decision.items():
        candidates = sorted(row["candidate_id"] for row in rows)
        if len(candidates) != len(set(candidates)):
            raise ManifestError("witnessed choice set duplicates a candidate")
        expected_digest = qualified_sha256_bytes(canonical_json_bytes(candidates))
        if {row["universe_digest"] for row in rows} != {expected_digest}:
            raise ManifestError("witnessed choice universe digest is incomplete or false")
        if len({row["choice_set_id"] for row in rows}) != 1:
            raise ManifestError("one decision maps to multiple witnessed choice sets")
        closure[decision_id] = {
            "choice_set_id": rows[0]["choice_set_id"],
            "universe_digest": expected_digest,
            "candidates": set(candidates),
            "available_at": max(row["available_at"] for row in rows),
        }
    return closure


def _validate_context_version(row: dict[str, Any], event_time: datetime, cutoff: datetime) -> None:
    regime_status = row["regime_topology_status"]
    regime_fields = (
        "regime_epoch",
        "regime_version_id",
        "topology_epoch",
        "topology_version_id",
    )
    if regime_status != "selected_as_known_version":
        if any(row[field] is not None for field in regime_fields):
            raise ManifestError("unsupported regime/topology cannot carry sentinel identities")
        return
    if any(row[field] in {None, ""} for field in regime_fields):
        raise ManifestError("regime/topology estimates require selected version identities")
    status = row.get("context_status", "selected_as_known_version")
    if status != "selected_as_known_version":
        return
    if row["context_valid_lower"] is None or row["context_valid_upper"] is None:
        raise ManifestError("selected context version lacks a valid-time interval")
    if not row["context_valid_lower"] <= event_time < row["context_valid_upper"]:
        raise TemporalLeakageError("selected context version is not valid at the event")
    if row["context_available_at"] is None or row["context_available_at"] > cutoff:
        raise TemporalLeakageError("selected context version was unavailable at the as-known cut")
    if row["context_retracted_at"] is not None and row["context_retracted_at"] <= cutoff:
        raise TemporalLeakageError("selected context version was retracted by the as-known cut")
    version_pairs = (
        ("territory_id", "territory_version_id"),
        ("community_id", "community_version_id"),
        ("lifecycle_state", "lifecycle_version_id"),
    )
    for value_field, version_field in version_pairs:
        if row.get(value_field) is not None and row.get(version_field) is None:
            raise ManifestError(f"{value_field} lacks its selected version identity")


def _validate_inputs(
    observations: pa.Table,
    choice_members: pa.Table,
    risk_cohorts: pa.Table,
    fit_cutoff: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not observations.schema.equals(KERNEL_OBSERVATION_SCHEMA, check_metadata=True):
        raise ManifestError("kernel observations violate their exact Arrow schema")
    if not risk_cohorts.schema.equals(RISK_COHORT_SCHEMA, check_metadata=True):
        raise ManifestError("risk cohorts violate their exact Arrow schema")
    choice_closure = _validate_choice_sets(choice_members)
    rows = observations.to_pylist()
    ids = [row["kernel_observation_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ManifestError("kernel observations duplicate occurrence identity")
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if row["event_time_status"] != "exact":
            raise ManifestError("kernel observation v1 is scoped to exact event times")
        if not row["event_valid_lower"] <= row["event_time"] < row["event_valid_upper"]:
            raise ManifestError("marked event falls outside its valid-time interval")
        slots = (row["event_slot_lower"], row["event_slot_upper"])
        if (slots[0] is None) != (slots[1] is None) or (
            slots[0] is not None and slots[0] >= slots[1]
        ):
            raise ManifestError("event slot interval must be absent or nonempty")
        if row["event_time"] > row["event_available_at"]:
            raise TemporalLeakageError("marked event became available before it occurred")
        if row["response_time"] != row["event_time"] + timedelta(microseconds=row["horizon_us"]):
            raise ManifestError("kernel response time differs from its registered horizon")
        if row["response_time"] > row["response_available_at"]:
            raise TemporalLeakageError("response became available before its response time")
        if row["choice_context_status"] == "scene_choice_complete":
            required = (
                "decision_id",
                "choice_set_id",
                "scene_id",
                "scene_view_digest",
                "universe_digest",
            )
            if any(row[field] is None for field in required):
                raise ManifestError("witnessed response row lacks exact scene/choice identity")
            closure = choice_closure.get(row["decision_id"])
            if (
                closure is None
                or row["choice_set_id"] != closure["choice_set_id"]
                or row["universe_digest"] != closure["universe_digest"]
                or row["candidate_id"] not in closure["candidates"]
            ):
                raise ManifestError("response row is outside its complete witnessed choice set")
            if closure["available_at"] > row["information_cutoff"]:
                raise TemporalLeakageError("choice universe was unavailable at decision time")
        if row["event_available_at"] > row["information_cutoff"]:
            raise TemporalLeakageError("mark was unavailable at its decision cut")
        if row["caller_attribution_status"] == "known_wallet" and any(
            row[field] is None
            for field in ("caller_identity_version_id", "caller_wallet_id", "caller_class")
        ):
            raise ManifestError("known caller attribution lacks version/wallet/class")
        if row["mark_size_status"] == "known_exact":
            if any(
                row[field] is None
                for field in ("mark_size_bucket", "mark_size_atoms", "mark_asset_id")
            ):
                raise ManifestError("known exact mark size lacks amount/unit/bucket")
        elif any(
            row[field] is not None
            for field in ("mark_size_bucket", "mark_size_atoms", "mark_asset_id")
        ):
            raise ManifestError("unknown mark size cannot contain fabricated zero/sentinel values")
        _validate_context_version(row, row["event_time"], row["information_cutoff"])
        if RESPONSE_UNITS.get(row["observable_kind"]) != row["response_unit"]:
            raise ManifestError("kernel v1 requires a registered signed-int64 observable/unit pair")
        if row["coverage_status"] == "observed":
            if row["response_value"] is None or row["coverage_gap_id"] is not None:
                raise CoverageError("observed kernel response lacks a value or cites a gap")
        elif row["coverage_status"] == "gap":
            if row["response_value"] is not None or row["coverage_gap_id"] is None:
                raise CoverageError("kernel gap must retain null response and exact gap identity")
        else:
            raise CoverageError("unknown kernel response coverage status")
        if (
            row["response_available_at"] <= fit_cutoff
            and row["regime_topology_status"] == "selected_as_known_version"
        ):
            eligible.append(row)

    risk_rows = risk_cohorts.to_pylist()
    risk_ids = [row["cohort_id"] for row in risk_rows]
    if len(risk_ids) != len(set(risk_ids)):
        raise ManifestError("risk cohorts duplicate occurrence identity")
    eligible_risks: list[dict[str, Any]] = []
    for row in risk_rows:
        if row["choice_context_status"] == "scene_choice_complete":
            closure = choice_closure.get(row["decision_id"])
            if (
                closure is None
                or row["choice_set_id"] != closure["choice_set_id"]
                or row["universe_digest"] != closure["universe_digest"]
                or row["candidate_id"] not in closure["candidates"]
            ):
                raise ManifestError("risk cohort is outside its complete witnessed choice set")
        _validate_context_version(row, row["anchor_time"], row["anchor_available_at"])
        if not row["risk_entry_time"] <= row["risk_exit_time"]:
            raise ManifestError("risk interval is reversed")
        if row["censoring_kind"] in {"right_administrative", "right_source_loss"}:
            if not row["right_censored"]:
                raise ManifestError("right censoring kind requires right_censored=true")
            if row["event_kind"] is not None or row["event_time"] is not None:
                raise ManifestError("right-censored cohort cannot manufacture a no-event outcome")
            if row["event_time_lower"] is not None or row["event_time_upper"] is not None:
                raise ManifestError("right-censored cohort cannot carry event-time bounds")
            if row["censoring_reason"] is None:
                raise CoverageError("right-censored cohort requires a typed reason")
            if row["censoring_kind"] == "right_source_loss" and row["coverage_gap_id"] is None:
                raise CoverageError("source-loss censoring requires exact coverage gap")
            if (
                row["censoring_kind"] == "right_administrative"
                and row["coverage_gap_id"] is not None
            ):
                raise CoverageError("administrative censoring cannot cite a source gap")
        elif row["censoring_kind"] == "exact_event":
            if row["right_censored"]:
                raise ManifestError("exact event cannot be right-censored")
            if row["event_kind"] is None or row["event_time"] is None:
                raise ManifestError("observed competing event requires kind and time")
            if not row["risk_entry_time"] <= row["event_time"] < row["risk_exit_time"]:
                raise ManifestError("competing event escapes its risk interval")
            if not (
                row["event_time_lower"] == row["event_time"]
                and row["event_time_upper"] == row["event_time"] + timedelta(microseconds=1)
            ):
                raise ManifestError("exact event requires a one-microsecond half-open bound")
            if row["outcome_known_at"] < row["event_time"]:
                raise TemporalLeakageError("outcome became known before its event")
        else:
            raise ManifestError("unsupported competing-risk censoring kind")
        if (
            row["outcome_known_at"] <= fit_cutoff
            and row["regime_topology_status"] == "selected_as_known_version"
        ):
            eligible_risks.append(row)
    if not eligible:
        raise ManifestError("fit cutoff leaves no point-in-time kernel observations")
    return eligible, eligible_risks, choice_closure


def _mean_se(values: list[float]) -> tuple[float, float, float, float]:
    estimate = fmean(values)
    if len(values) < 2:
        standard_error = 0.0
    else:
        variance = sum((value - estimate) ** 2 for value in values) / (len(values) - 1)
        standard_error = math.sqrt(variance / len(values))
    radius = 1.96 * standard_error
    return estimate, standard_error, estimate - radius, estimate + radius


def estimate_response_kernels(
    observations: pa.Table,
    choice_members: pa.Table,
    risk_cohorts: pa.Table,
    fit_cutoff: datetime,
) -> pa.Table:
    eligible, eligible_risks, _ = _validate_inputs(
        observations, choice_members, risk_cohorts, fit_cutoff
    )
    input_snapshot_id, input_digest = _eligible_input_identity(
        eligible, choice_members, eligible_risks, fit_cutoff
    )
    group_fields = (
        "caller_class",
        "mark_family",
        "mark_direction",
        "mark_size_bucket",
        "regime_epoch",
        "topology_epoch",
        "horizon_us",
        "observable_kind",
        "response_unit",
    )
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    context_totals: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in eligible:
        context = _context_key(row)
        key = (*[row[field] for field in group_fields], context)
        groups[key].append(row)
        context_key = (
            context,
            row["regime_epoch"],
            row["topology_epoch"],
            row["horizon_us"],
            row["observable_kind"],
        )
        context_totals[context_key] += 1

    raw_outputs: list[dict[str, Any]] = []
    for ordinal, (key, rows) in enumerate(sorted(groups.items(), key=lambda item: str(item[0])), 1):
        (
            caller_class,
            mark_family,
            mark_direction,
            mark_size_bucket,
            regime,
            topology,
            horizon_us,
            observable,
            response_unit,
            context,
        ) = key
        observed = [row for row in rows if row["coverage_status"] == "observed"]
        gaps = [row for row in rows if row["coverage_status"] == "gap"]
        wallet_values: dict[str, list[float]] = defaultdict(list)
        for row in observed:
            cluster = (
                row["caller_wallet_id"] or row["caller_identity_version_id"] or row["event_id"]
            )
            wallet_values[cluster].append(float(row["response_value"]))
        wallet_means = [fmean(values) for _, values in sorted(wallet_values.items())]
        estimate, standard_error, lower, upper = (
            _mean_se(wallet_means) if wallet_means else (None, None, None, None)
        )
        context_group = (context, regime, topology, horizon_us, observable)
        context_count = context_totals[context_group]
        coverage_ppm = len(observed) * 1_000_000 // len(rows)
        overlap = (
            "adequate"
            if len(wallet_means) >= 2 and coverage_ppm >= 800_000
            else "no_observed_support"
            if not wallet_means
            else "low_overlap_or_coverage"
        )
        interaction_key = (
            f"caller={caller_class}|family={mark_family}|direction={mark_direction}|"
            f"size={mark_size_bucket}|{context}"
        )
        raw_outputs.append(
            {
                "kernel_estimate_occurrence_id": f"kernel-estimate:{ordinal:04d}",
                "estimator_id": ESTIMATOR_ID,
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": input_snapshot_id,
                "input_logical_digest": input_digest,
                "training_lower_available_at": min(
                    row["response_available_at"] for row in eligible
                ),
                "fit_cutoff": fit_cutoff,
                "maximum_training_available_at": max(
                    row["response_available_at"] for row in eligible
                ),
                "as_of_commit_seq": max(row["available_commit_seq"] for row in eligible),
                "caller_class": caller_class,
                "mark_family": mark_family,
                "mark_direction": mark_direction,
                "mark_size_bucket": mark_size_bucket,
                "context_key": context,
                "interaction_key": interaction_key,
                "regime_epoch": regime,
                "topology_epoch": topology,
                "horizon_us": horizon_us,
                "observable_kind": observable,
                "response_unit": response_unit,
                "estimate": estimate,
                "standard_error": standard_error,
                "interval_lower": lower,
                "interval_upper": upper,
                "uncertainty_method": "wallet_cluster_normal_approximation",
                "event_count": len({row["event_id"] for row in observed}),
                "wallet_count": len(wallet_means),
                "effective_sample_size": float(len(wallet_means)),
                "observed_count": len(observed),
                "gap_count": len(gaps),
                "coverage_ratio_ppm": coverage_ppm,
                "coverage_window_ids": sorted(
                    {
                        row["coverage_window_id"]
                        for row in rows
                        if row["coverage_window_id"] is not None
                    }
                ),
                "coverage_gap_ids": sorted(
                    row["coverage_gap_id"] for row in gaps if row["coverage_gap_id"] is not None
                ),
                "context_event_count": context_count,
                "mark_share_ppm": len(rows) * 1_000_000 // context_count,
                "overlap_status": overlap,
                "nonstationarity_reference_epoch": None,
                "nonstationarity_delta": None,
                "topology_boundary_status": "within_topology",
                "claim_scope": KERNEL_CLAIM_SCOPE,
            }
        )

    reference_fields = (
        "caller_class",
        "mark_family",
        "mark_direction",
        "mark_size_bucket",
        "context_key",
        "topology_epoch",
        "horizon_us",
        "observable_kind",
    )
    for row in raw_outputs:
        prior_same_topology = [
            candidate
            for candidate in raw_outputs
            if all(candidate[field] == row[field] for field in reference_fields)
            and candidate["regime_epoch"] < row["regime_epoch"]
        ]
        if prior_same_topology:
            reference = max(prior_same_topology, key=lambda item: item["regime_epoch"])
            row["nonstationarity_reference_epoch"] = reference["regime_epoch"]
            if row["estimate"] is not None and reference["estimate"] is not None:
                row["nonstationarity_delta"] = row["estimate"] - reference["estimate"]
        else:
            cross_topology_prior = any(
                candidate["topology_epoch"] != row["topology_epoch"]
                and candidate["regime_epoch"] < row["regime_epoch"]
                and all(
                    candidate[field] == row[field]
                    for field in reference_fields
                    if field != "topology_epoch"
                )
                for candidate in raw_outputs
            )
            if cross_topology_prior:
                row["topology_boundary_status"] = "changed_topology_no_direct_delta"
        row["kernel_estimate_digest"] = _digest_record(row, "kernel_estimate_occurrence_id")
    return pa.Table.from_pylist(raw_outputs, schema=KERNEL_ESTIMATE_SCHEMA)


def _aalen_johansen(rows: list[dict[str, Any]], causes: list[str]) -> dict[str, float]:
    survival = 1.0
    cumulative = {cause: 0.0 for cause in causes}
    event_times = sorted({row["event_time"] for row in rows if not row["right_censored"]})
    for event_time in event_times:
        at_risk = sum(row["risk_exit_time"] >= event_time for row in rows)
        if at_risk == 0:
            continue
        counts = {
            cause: sum(
                not row["right_censored"]
                and row["event_time"] == event_time
                and row["event_kind"] == cause
                for row in rows
            )
            for cause in causes
        }
        for cause in causes:
            cumulative[cause] += survival * counts[cause] / at_risk
        survival *= 1.0 - sum(counts.values()) / at_risk
    return cumulative


def screen_candidate_models(
    observations: pa.Table,
    choice_members: pa.Table,
    risk_cohorts: pa.Table,
    fit_cutoff: datetime,
) -> pa.Table:
    eligible, eligible_risks, _ = _validate_inputs(
        observations, choice_members, risk_cohorts, fit_cutoff
    )
    input_snapshot_id, input_digest = _eligible_input_identity(
        eligible, choice_members, eligible_risks, fit_cutoff
    )
    unique_events: dict[str, dict[str, Any]] = {}
    for row in eligible:
        unique_events.setdefault(row["event_id"], row)
    event_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in unique_events.values():
        event_groups[(_context_key(row), row["regime_epoch"], row["topology_epoch"])].append(row)
    outputs: list[dict[str, Any]] = []
    window_us = int(CONFIGURATION["hawkes_screen_window_us"])
    for context_group, events in sorted(event_groups.items()):
        context, regime, topology = context_group
        before = 0
        after = 0
        for anchor in events:
            for candidate in events:
                if anchor["event_id"] == candidate["event_id"] or (
                    anchor["candidate_id"] != candidate["candidate_id"]
                ):
                    continue
                delta_us = int(
                    (candidate["event_time"] - anchor["event_time"]).total_seconds() * 1_000_000
                )
                if -window_us <= delta_us < 0:
                    before += 1
                elif 0 < delta_us <= window_us:
                    after += 1
        estimate = math.log((after + 0.5) / (before + 0.5))
        standard_error = math.sqrt(1 / (after + 0.5) + 1 / (before + 0.5))
        row = {
            "diagnostic_occurrence_id": f"hawkes-screen:{regime}:{topology}:{len(outputs):04d}",
            "diagnostic_family": "hawkes_window_excitation_candidate",
            "estimator_configuration_digest": CONFIGURATION_DIGEST,
            "input_snapshot_id": input_snapshot_id,
            "input_logical_digest": input_digest,
            "target_kind": "same_candidate_event_arrival_log_rate_ratio",
            "context_key": context,
            "regime_epoch": regime,
            "topology_epoch": topology,
            "horizon_us": window_us,
            "estimate": estimate,
            "interval_lower": estimate - 1.96 * standard_error,
            "interval_upper": estimate + 1.96 * standard_error,
            "event_count": len(events),
            "censored_count": 0,
            "coverage_ratio_ppm": 1_000_000,
            "coverage_window_ids": sorted(
                {
                    event["coverage_window_id"]
                    for event in events
                    if event["coverage_window_id"] is not None
                }
            ),
            "coverage_gap_ids": sorted(
                {
                    event["coverage_gap_id"]
                    for event in events
                    if event["coverage_gap_id"] is not None
                }
            ),
            "fit_cutoff": fit_cutoff,
            "maximum_training_available_at": max(event["event_available_at"] for event in events),
            "assumptions": (
                "symmetric fixed window screen; not a Hawkes likelihood, branching ratio, "
                "counterfactual, or causal effect"
            ),
            "claim_scope": CANDIDATE_CLAIM_SCOPE,
        }
        row["diagnostic_digest"] = _digest_record(row, "diagnostic_occurrence_id")
        outputs.append(row)

    risk_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_risks:
        risk_groups[(_risk_context_key(row), row["regime_epoch"], row["topology_epoch"])].append(
            row
        )
    causes = ["drawdown", "liquidity_exit", "send"]
    for (context, regime, topology), rows in sorted(risk_groups.items()):
        cumulative = _aalen_johansen(rows, causes)
        coverage_ppm = (
            sum(row["coverage_status"] == "observed" for row in rows) * 1_000_000 // len(rows)
        )
        for cause in causes:
            estimate = cumulative[cause]
            standard_error = math.sqrt(max(0.0, estimate * (1.0 - estimate) / len(rows)))
            row = {
                "diagnostic_occurrence_id": (
                    f"competing-risk:{regime}:{topology}:{cause}:{len(outputs):04d}"
                ),
                "diagnostic_family": "competing_risk_cumulative_incidence_candidate",
                "estimator_configuration_digest": CONFIGURATION_DIGEST,
                "input_snapshot_id": input_snapshot_id,
                "input_logical_digest": input_digest,
                "target_kind": cause,
                "context_key": context,
                "regime_epoch": regime,
                "topology_epoch": topology,
                "horizon_us": rows[0]["horizon_us"],
                "estimate": estimate,
                "interval_lower": max(0.0, estimate - 1.96 * standard_error),
                "interval_upper": min(1.0, estimate + 1.96 * standard_error),
                "event_count": sum(row["event_kind"] == cause for row in rows),
                "censored_count": sum(row["right_censored"] for row in rows),
                "coverage_ratio_ppm": coverage_ppm,
                "coverage_window_ids": sorted(
                    {
                        row["coverage_window_id"]
                        for row in rows
                        if row["coverage_window_id"] is not None
                    }
                ),
                "coverage_gap_ids": sorted(
                    {row["coverage_gap_id"] for row in rows if row["coverage_gap_id"] is not None}
                ),
                "fit_cutoff": fit_cutoff,
                "maximum_training_available_at": max(row["outcome_known_at"] for row in rows),
                "assumptions": (
                    "Aalen-Johansen candidate over fixture risk sets; observational association, "
                    "not intervention effect or strategy value"
                ),
                "claim_scope": CANDIDATE_CLAIM_SCOPE,
            }
            row["diagnostic_digest"] = _digest_record(row, "diagnostic_occurrence_id")
            outputs.append(row)
    return pa.Table.from_pylist(outputs, schema=CANDIDATE_DIAGNOSTIC_SCHEMA)
