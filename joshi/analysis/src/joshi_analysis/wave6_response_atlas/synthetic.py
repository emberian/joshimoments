from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa

from .contracts import (
    RESPONSE_COMPONENT_OBSERVATION_SCHEMA,
    RESPONSE_COMPONENTS,
    RISK_OUTCOME_SCHEMA,
)


def synthetic_response_atlas_inputs() -> tuple[pa.Table, pa.Table, datetime]:
    fit_cutoff = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    contexts = (
        (
            "venue:pump-amm",
            "fresh",
            "lifecycle:pump:fresh:v1",
            "topology-1",
            "topology:1:v1",
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            "buy",
            "small",
            100,
            0,
            1_000,
            (
                ("wallet-a", "wallet:a:v1", "cluster-alpha", "organic"),
                ("wallet-a", "wallet:a:v1", "cluster-alpha", "organic"),
                ("wallet-b", "wallet:b:v1", "cluster-alpha", "organic"),
                ("wallet-b", "wallet:b:v1", "cluster-alpha", "organic"),
            ),
        ),
        (
            "venue:pumpswap",
            "migrated",
            "lifecycle:swap:migrated:v1",
            "topology-2",
            "topology:2:v1",
            datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            "sell",
            "large",
            5_000,
            1_000,
            10_000,
            (
                ("wallet-c", "wallet:c:v1", "cluster-beta", "creator_linked"),
                ("wallet-c", "wallet:c:v1", "cluster-beta", "creator_linked"),
                ("wallet-d", "wallet:d:v1", "cluster-beta", "creator_linked"),
                ("wallet-d", "wallet:d:v1", "cluster-beta", "creator_linked"),
            ),
        ),
    )
    horizon_values = (60_000_000, 300_000_000)
    risk_modes = (
        "migration",
        "right_administrative",
        "liquidity_exhaustion",
        "right_source_gap",
        "venue_exit",
        "right_administrative",
        "migration",
        "right_source_gap",
    )
    observations: list[dict[str, object]] = []
    risks: list[dict[str, object]] = []
    ordinal = 0
    commit = 7_000
    for (
        venue,
        lifecycle,
        lifecycle_version,
        topology,
        topology_version,
        context_start,
        direction,
        size_bucket,
        size_atoms,
        size_lower,
        size_upper,
        wallets,
    ) in contexts:
        for wallet_id, wallet_version, cluster_id, caller_class in wallets:
            ordinal += 1
            event_id = f"atlas-event-{ordinal:03d}"
            event_time = context_start + timedelta(minutes=10 * ordinal)
            event_available_at = event_time + timedelta(seconds=2)
            information_cutoff = event_time + timedelta(seconds=5)
            for horizon_index, horizon_us in enumerate(horizon_values):
                response_time = event_time + timedelta(microseconds=horizon_us)
                response_available_at = response_time + timedelta(seconds=2)
                for component_index, component in enumerate(RESPONSE_COMPONENTS, start=1):
                    commit += 1
                    is_gap = ordinal == 4 and horizon_index == 1 and component == "external"
                    direction_sign = 1 if direction == "buy" else -1
                    component_value = direction_sign * (
                        component_index * 10 + ordinal + horizon_index * 100
                    )
                    component_id = f"atlas-component:{event_id}:{horizon_us}:{component}"
                    observations.append(
                        {
                            "component_observation_id": component_id,
                            "event_id": event_id,
                            "base_asset_id": "asset:solana:fixture:BASE",
                            "venue_id": venue,
                            "lifecycle_state": lifecycle,
                            "lifecycle_version_id": lifecycle_version,
                            "lifecycle_valid_lower": context_start - timedelta(hours=1),
                            "lifecycle_valid_upper": context_start + timedelta(days=2),
                            "lifecycle_available_at": context_start - timedelta(hours=2),
                            "lifecycle_retracted_at": None,
                            "wallet_id": wallet_id,
                            "wallet_identity_version_id": wallet_version,
                            "cluster_id": cluster_id,
                            "cluster_version_id": f"cluster:{cluster_id}:v1",
                            "caller_class": caller_class,
                            "caller_class_version_id": f"caller-class:{caller_class}:v1",
                            "caller_context_valid_lower": context_start - timedelta(hours=1),
                            "caller_context_valid_upper": context_start + timedelta(days=2),
                            "caller_context_available_at": context_start - timedelta(hours=2),
                            "caller_context_retracted_at": None,
                            "mark_direction": direction,
                            "mark_size_bucket": size_bucket,
                            "mark_size_atoms": size_atoms,
                            "mark_size_lower_atoms": size_lower,
                            "mark_size_upper_atoms": size_upper,
                            "mark_size_unit": "base_asset_atoms",
                            "topology_epoch": topology,
                            "topology_version_id": topology_version,
                            "topology_valid_lower": context_start - timedelta(hours=1),
                            "topology_valid_upper": context_start + timedelta(days=2),
                            "topology_available_at": context_start - timedelta(hours=2),
                            "topology_retracted_at": None,
                            "event_time": event_time,
                            "event_available_at": event_available_at,
                            "information_cutoff": information_cutoff,
                            "horizon_us": horizon_us,
                            "response_time": response_time,
                            "response_available_at": response_available_at,
                            "component_kind": component,
                            "response_signed_flow_atoms": None if is_gap else component_value,
                            "response_unit": "base_asset_atoms",
                            "coverage_status": "gap" if is_gap else "observed",
                            "coverage_window_id": f"coverage:{event_id}:{horizon_us}",
                            "coverage_gap_id": f"gap:{component_id}" if is_gap else None,
                            "available_commit_seq": commit,
                        }
                    )

                mode = risk_modes[ordinal - 1]
                commit += 1
                if mode in {"migration", "liquidity_exhaustion", "venue_exit"}:
                    censoring_kind = "exact_event"
                    outcome_time = event_time + timedelta(microseconds=horizon_us // 2)
                    event_kind: str | None = mode
                    event_at = outcome_time
                    coverage_status = "observed"
                    gap_id = None
                elif mode == "right_administrative":
                    censoring_kind = mode
                    outcome_time = response_time
                    event_kind = None
                    event_at = None
                    coverage_status = "observed"
                    gap_id = None
                else:
                    censoring_kind = mode
                    outcome_time = event_time + timedelta(microseconds=horizon_us // 2)
                    event_kind = None
                    event_at = None
                    coverage_status = "gap"
                    gap_id = f"risk-gap:{event_id}:{horizon_us}"
                risks.append(
                    {
                        "risk_outcome_id": f"atlas-risk:{event_id}:{horizon_us}",
                        "event_id": event_id,
                        "horizon_us": horizon_us,
                        "risk_entry_time": event_time,
                        "risk_horizon_end": response_time,
                        "outcome_time": outcome_time,
                        "event_kind": event_kind,
                        "event_time": event_at,
                        "outcome_known_at": outcome_time + timedelta(seconds=3),
                        "censoring_kind": censoring_kind,
                        "coverage_status": coverage_status,
                        "coverage_window_id": f"risk-coverage:{event_id}:{horizon_us}",
                        "coverage_gap_id": gap_id,
                        "available_commit_seq": commit,
                    }
                )
    return (
        pa.Table.from_pylist(observations, schema=RESPONSE_COMPONENT_OBSERVATION_SCHEMA),
        pa.Table.from_pylist(risks, schema=RISK_OUTCOME_SCHEMA),
        fit_cutoff,
    )
