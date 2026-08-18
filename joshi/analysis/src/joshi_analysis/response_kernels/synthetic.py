from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pyarrow as pa

from ..canonical import canonical_json_bytes, qualified_sha256_bytes
from .contracts import KERNEL_CHOICE_MEMBER_SCHEMA, KERNEL_OBSERVATION_SCHEMA, RISK_COHORT_SCHEMA

OBSERVABLES = {
    "trade_intensity_delta": "events_per_minute_ppm",
    "signed_flow": "base_asset_atoms",
    "liquidity_response": "quote_asset_atoms",
    "attention_response": "attention_events_per_minute_ppm",
    "price_response": "return_ppm",
}


def _universe_digest(candidates: list[str]) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(sorted(candidates)))


def _response(
    observable: str,
    *,
    direction: str,
    size_bucket: str,
    context_index: int,
    regime_index: int,
    horizon_index: int,
    wallet_offset: int,
) -> int:
    sign = 1 if direction == "buy" else -1
    size = 1 if size_bucket == "large" else 0
    horizon = horizon_index + 1
    if observable == "trade_intensity_delta":
        return (
            100_000 * horizon
            + 10_000 * regime_index
            + 20_000 * size
            + 5_000 * context_index
            + 100 * wallet_offset
        )
    if observable == "signed_flow":
        return (
            sign * (500 * horizon + 50 * regime_index + 100 * size + 25 * context_index)
            + wallet_offset
        )
    if observable == "liquidity_response":
        return -(200 * horizon + 20 * regime_index + 50 * size) + wallet_offset
    if observable == "attention_response":
        return (
            50_000 * horizon + 5_000 * regime_index + 10_000 * context_index + 100 * wallet_offset
        )
    if observable == "price_response":
        return (
            sign * (40_000 * horizon + 4_000 * regime_index + 8_000 * size + 2_000 * context_index)
            + 100 * wallet_offset
        )
    raise ValueError(f"unknown synthetic observable: {observable}")


def synthetic_kernel_inputs() -> tuple[pa.Table, pa.Table, pa.Table, datetime]:
    wallets = [
        ("wallet-1", "ecology_wallet", -15),
        ("wallet-2", "ecology_wallet", -5),
        ("wallet-3", "creator_linked", 5),
        ("wallet-4", "creator_linked", 15),
    ]
    contexts = [
        ("territory-trend", None, "venue:pump-amm", "fresh", "candidate-a"),
        (
            "territory-community",
            "community-fixture",
            "venue:pumpswap",
            "migrated",
            "candidate-c",
        ),
    ]
    regimes = [
        ("regime-1", "topology-1", datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        ("regime-2", "topology-1", datetime(2026, 8, 11, 12, 0, tzinfo=UTC)),
        ("regime-3", "topology-2", datetime(2026, 8, 12, 12, 0, tzinfo=UTC)),
    ]
    horizons = [60_000_000, 300_000_000]
    universe = ["candidate-a", "candidate-b", "candidate-c"]
    universe_digest = _universe_digest(universe)
    observations: list[dict[str, object]] = []
    choices: list[dict[str, object]] = []
    risks: list[dict[str, object]] = []
    event_ordinal = 0
    commit = 1_000
    for regime_index, (regime, topology, regime_start) in enumerate(regimes, start=1):
        for context_index, (
            territory,
            community,
            venue,
            lifecycle,
            selected_candidate,
        ) in enumerate(contexts):
            for direction in ("buy", "sell"):
                for size_bucket in ("small", "large"):
                    for wallet_index, (wallet, caller_class, wallet_offset) in enumerate(wallets):
                        event_ordinal += 1
                        event_time = regime_start + timedelta(minutes=3 * event_ordinal)
                        event_available = event_time + timedelta(seconds=2)
                        decision_time = event_time + timedelta(seconds=5)
                        event_id = f"synthetic-event-{event_ordinal:03d}"
                        decision_id = f"synthetic-decision-{event_ordinal:03d}"
                        choice_set_id = f"synthetic-choice-{event_ordinal:03d}"
                        scene_id = f"synthetic-scene-{event_ordinal:03d}"
                        view_digest = qualified_sha256_bytes(f"view:{scene_id}".encode())
                        for rank, candidate_id in enumerate(universe, start=1):
                            choices.append(
                                {
                                    "decision_id": decision_id,
                                    "choice_set_id": choice_set_id,
                                    "candidate_id": candidate_id,
                                    "set_kind": "eligible",
                                    "source_rank": rank,
                                    "universe_digest": universe_digest,
                                    "available_at": event_time + timedelta(seconds=1),
                                }
                            )
                        for horizon_index, horizon_us in enumerate(horizons):
                            response_time = event_time + timedelta(microseconds=horizon_us)
                            response_available = response_time + timedelta(seconds=3)
                            for observable, unit in OBSERVABLES.items():
                                is_gap = (
                                    regime == "regime-2"
                                    and territory == "territory-community"
                                    and direction == "sell"
                                    and size_bucket == "large"
                                    and wallet == "wallet-1"
                                    and horizon_us == 300_000_000
                                    and observable == "liquidity_response"
                                )
                                observation_id = (
                                    f"kernel-observation:{event_id}:{horizon_us}:{observable}"
                                )
                                observations.append(
                                    {
                                        "kernel_observation_id": observation_id,
                                        "event_id": event_id,
                                        "event_time_status": "exact",
                                        "choice_context_status": "scene_choice_complete",
                                        "decision_id": decision_id,
                                        "choice_set_id": choice_set_id,
                                        "scene_id": scene_id,
                                        "scene_view_digest": view_digest,
                                        "universe_digest": universe_digest,
                                        "candidate_id": selected_candidate,
                                        "caller_attribution_status": "known_wallet",
                                        "caller_identity_version_id": (
                                            f"caller-identity:{wallet}:v1"
                                        ),
                                        "caller_wallet_id": wallet,
                                        "caller_class": caller_class,
                                        "mark_family": "trade",
                                        "mark_direction": direction,
                                        "mark_size_status": "known_exact",
                                        "mark_size_bucket": size_bucket,
                                        "mark_size_atoms": Decimal(
                                            1_000 if size_bucket == "small" else 10_000
                                        ),
                                        "mark_asset_id": "asset:solana:native:SOL",
                                        "context_status": "selected_as_known_version",
                                        "territory_id": territory,
                                        "territory_version_id": f"territory-version:{territory}:v1",
                                        "community_id": community,
                                        "community_version_id": (
                                            f"community-version:{community}:v1"
                                            if community is not None
                                            else None
                                        ),
                                        "venue_id": venue,
                                        "lifecycle_state": lifecycle,
                                        "lifecycle_version_id": (
                                            f"lifecycle-version:{selected_candidate}:{regime}"
                                        ),
                                        "regime_topology_status": "selected_as_known_version",
                                        "regime_epoch": regime,
                                        "regime_version_id": f"regime-version:{regime}",
                                        "topology_epoch": topology,
                                        "topology_version_id": f"topology-version:{topology}",
                                        "event_time": event_time,
                                        "event_valid_lower": event_time,
                                        "event_valid_upper": event_time + timedelta(microseconds=1),
                                        "event_slot_lower": 348_000_000 + event_ordinal,
                                        "event_slot_upper": 348_000_001 + event_ordinal,
                                        "event_available_at": event_available,
                                        "context_valid_lower": regime_start,
                                        "context_valid_upper": regime_start + timedelta(days=1),
                                        "context_available_at": regime_start - timedelta(hours=1),
                                        "context_retracted_at": None,
                                        "information_cutoff": decision_time,
                                        "response_time": response_time,
                                        "response_available_at": response_available,
                                        "horizon_us": horizon_us,
                                        "observable_kind": observable,
                                        "response_value": (
                                            None
                                            if is_gap
                                            else _response(
                                                observable,
                                                direction=direction,
                                                size_bucket=size_bucket,
                                                context_index=context_index,
                                                regime_index=regime_index,
                                                horizon_index=horizon_index,
                                                wallet_offset=wallet_offset,
                                            )
                                        ),
                                        "response_unit": unit,
                                        "coverage_status": "gap" if is_gap else "observed",
                                        "coverage_scope_id": f"scope:{venue}:{selected_candidate}",
                                        "coverage_window_id": f"window:{event_id}",
                                        "coverage_gap_id": (
                                            f"gap:{observation_id}" if is_gap else None
                                        ),
                                        "available_commit_seq": commit,
                                    }
                                )
                                commit += 1
                        risk_selector = (
                            event_ordinal + wallet_index + context_index + regime_index
                        ) % 4
                        risk_horizon_us = 1_200_000_000
                        risk_exit = event_time + timedelta(microseconds=risk_horizon_us)
                        risk_kinds = ["send", "drawdown", "liquidity_exit"]
                        right_censored = risk_selector == 3
                        event_kind = None if right_censored else risk_kinds[risk_selector]
                        risk_event_time = (
                            None
                            if right_censored
                            else event_time + timedelta(minutes=4 + 2 * risk_selector)
                        )
                        risks.append(
                            {
                                "cohort_id": f"risk:{event_id}",
                                "choice_context_status": "scene_choice_complete",
                                "decision_id": decision_id,
                                "choice_set_id": choice_set_id,
                                "universe_digest": universe_digest,
                                "candidate_id": selected_candidate,
                                "caller_attribution_status": "known_wallet",
                                "caller_class": caller_class,
                                "territory_id": territory,
                                "territory_version_id": f"territory-version:{territory}:v1",
                                "regime_topology_status": "selected_as_known_version",
                                "regime_epoch": regime,
                                "regime_version_id": f"regime-version:{regime}",
                                "topology_epoch": topology,
                                "topology_version_id": f"topology-version:{topology}",
                                "anchor_time": event_time,
                                "anchor_slot": 348_000_000 + event_ordinal,
                                "anchor_available_at": event_available,
                                "context_valid_lower": regime_start,
                                "context_valid_upper": regime_start + timedelta(days=1),
                                "context_available_at": regime_start - timedelta(hours=1),
                                "context_retracted_at": None,
                                "risk_entry_time": event_time,
                                "risk_exit_time": (
                                    event_time + timedelta(minutes=9)
                                    if right_censored
                                    else risk_exit
                                ),
                                "horizon_us": risk_horizon_us,
                                "event_kind": event_kind,
                                "event_time": risk_event_time,
                                "event_time_lower": risk_event_time,
                                "event_time_upper": (
                                    None
                                    if risk_event_time is None
                                    else risk_event_time + timedelta(microseconds=1)
                                ),
                                "outcome_known_at": (
                                    event_time + timedelta(minutes=9, seconds=3)
                                    if right_censored
                                    else risk_event_time + timedelta(seconds=3)
                                ),
                                "right_censored": right_censored,
                                "censoring_kind": (
                                    "right_source_loss" if right_censored else "exact_event"
                                ),
                                "censoring_reason": (
                                    "fixture_followup_gap" if right_censored else None
                                ),
                                "coverage_status": "gap" if right_censored else "observed",
                                "coverage_window_id": f"risk-window:{event_id}",
                                "coverage_gap_id": (
                                    f"risk-gap:{event_id}" if right_censored else None
                                ),
                            }
                        )
    fit_cutoff = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    return (
        pa.Table.from_pylist(observations, schema=KERNEL_OBSERVATION_SCHEMA),
        pa.Table.from_pylist(choices, schema=KERNEL_CHOICE_MEMBER_SCHEMA),
        pa.Table.from_pylist(risks, schema=RISK_COHORT_SCHEMA),
        fit_cutoff,
    )
