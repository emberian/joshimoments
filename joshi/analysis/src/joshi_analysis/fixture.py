from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .canonical import canonical_json_bytes, qualified_sha256_bytes
from .contracts import TABLE_CONTRACTS
from .errors import ImmutableOutputError
from .snapshot import make_snapshot_manifest

FIXTURE_CREATED_AT = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)


def _digest(label: str) -> str:
    return qualified_sha256_bytes(label.encode("utf-8"))


def _scene_specs() -> list[dict[str, Any]]:
    return [
        {
            "scene_id": "scene-001",
            "decision_id": "decision-001",
            "choice_set_id": "choice-set-001",
            "episode_id": "episode-runner",
            "candidate_id": "candidate-a",
            "territory_id": "territory-trend",
            "start": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
            "decision": datetime(2026, 8, 14, 12, 5, tzinfo=UTC),
            "prices": [1000, 1020, 980, 1010, 1040],
            "buys": [12, 15, 8, 19, 23],
            "sells": [6, 7, 21, 9, 10],
            "states": ["flat_watch", "exposed", "exposed", "exposed", "runner"],
            "gap_index": None,
            "commit": 40,
        },
        {
            "scene_id": "scene-002",
            "decision_id": "decision-002",
            "choice_set_id": "choice-set-002",
            "episode_id": "episode-downpath",
            "candidate_id": "candidate-c",
            "territory_id": "territory-community",
            "start": datetime(2026, 8, 14, 13, 0, tzinfo=UTC),
            "decision": datetime(2026, 8, 14, 13, 5, tzinfo=UTC),
            "prices": [1000, 970, 930, 950, 920],
            "buys": [11, 7, 4, 12, 3],
            "sells": [5, 16, 18, 8, 20],
            "states": ["exposed", "exposed", "exposed", "exposed", "exposed"],
            "gap_index": None,
            "commit": 60,
        },
        {
            "scene_id": "scene-003",
            "decision_id": "decision-003",
            "choice_set_id": "choice-set-003",
            "episode_id": "episode-reentry",
            "candidate_id": "candidate-b",
            "territory_id": "territory-trend",
            "start": datetime(2026, 8, 15, 14, 0, tzinfo=UTC),
            "decision": datetime(2026, 8, 15, 14, 5, tzinfo=UTC),
            "prices": [1000, 1010, None, 995, 1030],
            "buys": [8, 9, None, 12, 18],
            "sells": [7, 5, None, 14, 6],
            "states": ["flat_watch", "flat_watch", "unknown", "exposed", "runner"],
            "gap_index": 2,
            "commit": 80,
        },
        {
            "scene_id": "scene-004",
            "decision_id": "decision-004",
            "choice_set_id": "choice-set-004",
            "episode_id": "episode-validation",
            "candidate_id": "candidate-d",
            "territory_id": "territory-trend",
            "start": datetime(2026, 8, 16, 14, 0, tzinfo=UTC),
            "decision": datetime(2026, 8, 16, 14, 5, tzinfo=UTC),
            "prices": [1000, 990, 1015, None, 1025],
            "buys": [10, 11, 16, None, 20],
            "sells": [8, 12, 7, None, 9],
            "states": ["flat_watch", "exposed", "exposed", "unknown", "runner"],
            "gap_index": 3,
            "commit": 100,
        },
    ]


def fixture_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scene in _scene_specs():
        view_digest = _digest(f"view:{scene['scene_id']}:v1")
        for sample_index, price in enumerate(scene["prices"]):
            event_time = scene["start"] + timedelta(minutes=sample_index)
            is_gap = price is None
            rows.append(
                {
                    "scene_id": scene["scene_id"],
                    "scene_mode": "witnessed",
                    "scene_view_digest": view_digest,
                    "decision_id": scene["decision_id"],
                    "episode_id": scene["episode_id"],
                    "candidate_id": scene["candidate_id"],
                    "territory_id": scene["territory_id"],
                    "base_asset_id": f"asset:solana:mint:{scene['candidate_id']}",
                    "quote_asset_id": "asset:solana:native:SOL",
                    "sample_index": sample_index,
                    "expected_sample_count": len(scene["prices"]),
                    "event_time": event_time,
                    "observed_at": event_time + timedelta(seconds=2),
                    "available_at": event_time + timedelta(seconds=4),
                    "decision_available_at": scene["decision"],
                    "price_base_atoms": None if is_gap else Decimal(1_000_000),
                    "price_quote_atoms": None if is_gap else Decimal(price),
                    "buy_volume_base_atoms": (
                        None if is_gap else Decimal(scene["buys"][sample_index])
                    ),
                    "sell_volume_base_atoms": (
                        None if is_gap else Decimal(scene["sells"][sample_index])
                    ),
                    "position_state": scene["states"][sample_index],
                    "coverage_status": "gap" if is_gap else "observed",
                    "coverage_scope_id": f"scope:chart:{scene['candidate_id']}",
                    "coverage_window_id": f"coverage-window:{scene['scene_id']}",
                    "coverage_gap_id": f"coverage-gap:{scene['scene_id']}" if is_gap else None,
                    # One assertion can support a projected series; it is provenance, not a row ID.
                    "source_assertion_id": (
                        None if is_gap else f"assertion:market:{scene['scene_id']}"
                    ),
                    "source_observation_id": (
                        None if is_gap else f"observation:assertion:market:{scene['scene_id']}"
                    ),
                    "available_commit_seq": scene["commit"] - 2 + sample_index // 3,
                }
            )
    return rows


def fixture_tables() -> dict[str, pa.Table]:
    scenes = _scene_specs()
    territories = [
        {
            "territory_id": "territory-community",
            "territory_kind": "creator_community",
            "description": "fixture creator/community territory",
            "first_available_at": datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            "available_commit_seq": 10,
            "source_assertion_id": "assertion:territory:community",
            "source_observation_id": "observation:assertion:territory:community",
        },
        {
            "territory_id": "territory-trend",
            "territory_kind": "attention_trend",
            "description": "fixture attention/trend territory",
            "first_available_at": datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            "available_commit_seq": 10,
            "source_assertion_id": "assertion:territory:trend",
            "source_observation_id": "observation:assertion:territory:trend",
        },
    ]
    candidate_specs = [
        ("candidate-a", "territory-trend", datetime(2026, 8, 14, 10, 10, tzinfo=UTC), 12),
        ("candidate-b", "territory-trend", datetime(2026, 8, 14, 10, 20, tzinfo=UTC), 13),
        ("candidate-c", "territory-community", datetime(2026, 8, 14, 10, 30, tzinfo=UTC), 14),
        ("candidate-d", "territory-trend", datetime(2026, 8, 14, 10, 40, tzinfo=UTC), 15),
        ("candidate-e", "territory-community", datetime(2026, 8, 14, 10, 50, tzinfo=UTC), 16),
    ]
    candidates = [
        {
            "candidate_id": candidate_id,
            "mint_asset_id": f"asset:solana:mint:{candidate_id}",
            "territory_id": territory_id,
            "created_at": created_at,
            "first_available_at": created_at + timedelta(seconds=5),
            "available_commit_seq": commit,
            "source_assertion_id": f"assertion:candidate:{candidate_id}",
            "source_observation_id": f"observation:assertion:candidate:{candidate_id}",
        }
        for candidate_id, territory_id, created_at, commit in candidate_specs
    ]
    social = [
        {
            "social_assertion_id": "social:candidate-a:creator",
            "candidate_id": "candidate-a",
            "identity_kind": "creator_account",
            "identity_key": "fixture-creator-a",
            "event_time": datetime(2026, 8, 14, 10, 15, tzinfo=UTC),
            "observed_at": datetime(2026, 8, 14, 10, 15, 2, tzinfo=UTC),
            "available_at": datetime(2026, 8, 14, 10, 15, 4, tzinfo=UTC),
            "available_commit_seq": 17,
            "source_assertion_id": "assertion:social:candidate-a",
            "source_observation_id": "observation:assertion:social:candidate-a",
        },
        {
            # The event predates decision-004, but this identity was learned afterward.
            "social_assertion_id": "social:candidate-d:creator-late",
            "candidate_id": "candidate-d",
            "identity_kind": "creator_account",
            "identity_key": "fixture-creator-d-later-confirmed",
            "event_time": datetime(2026, 8, 16, 13, 0, tzinfo=UTC),
            "observed_at": datetime(2026, 8, 16, 15, 0, tzinfo=UTC),
            "available_at": datetime(2026, 8, 16, 15, 0, 4, tzinfo=UTC),
            "available_commit_seq": 115,
            "source_assertion_id": "assertion:social:candidate-d",
            "source_observation_id": "observation:assertion:social:candidate-d",
        },
    ]

    scene_rows = [
        {
            "scene_id": scene["scene_id"],
            "scene_mode": "witnessed",
            "view_contract": "joshi.glass.snapshot",
            "view_contract_version": "1",
            "view_digest": _digest(f"view:{scene['scene_id']}:v1"),
            "source_mode": "offline_fixture",
            "rendered_at": scene["decision"] - timedelta(seconds=10),
            "decision_available_at": scene["decision"],
            "knowledge_commit_seq": scene["commit"],
            "available_commit_seq": scene["commit"],
        }
        for scene in scenes
    ]
    decisions = [
        {
            "decision_id": scene["decision_id"],
            "scene_id": scene["scene_id"],
            "choice_set_id": scene["choice_set_id"],
            "selected_candidate_id": scene["candidate_id"],
            "episode_id": scene["episode_id"],
            "operator_action": "entered_or_continued_exposure",
            "selection_gesture_id": f"gesture:select:{scene['decision_id']}",
            "decision_available_at": scene["decision"],
            "available_commit_seq": scene["commit"] + 1,
        }
        for scene in scenes
    ]
    universes = {
        "decision-001": ["candidate-a", "candidate-b"],
        "decision-002": ["candidate-a", "candidate-c", "candidate-d"],
        "decision-003": ["candidate-b", "candidate-c"],
        "decision-004": ["candidate-a", "candidate-d", "candidate-e"],
    }
    choices: list[dict[str, Any]] = []
    for scene in scenes:
        for rank, candidate_id in enumerate(universes[scene["decision_id"]], start=1):
            choices.append(
                {
                    "choice_set_id": scene["choice_set_id"],
                    "decision_id": scene["decision_id"],
                    "scene_id": scene["scene_id"],
                    "candidate_id": candidate_id,
                    "set_kind": "eligible",
                    "source_rank": rank,
                    "rendered_ordinal": rank if rank <= 2 else None,
                    "in_viewport": rank <= 2,
                    "interacted": candidate_id == scene["candidate_id"],
                    "evidence_assertion_id": f"assertion:market:{scene['scene_id']}",
                    "evidence_observation_id": (
                        f"observation:assertion:market:{scene['scene_id']}"
                    ),
                    "available_at": scene["decision"] - timedelta(seconds=12),
                    "available_commit_seq": scene["commit"] - 1,
                }
            )
    episodes = [
        {
            "episode_id": scene["episode_id"],
            "decision_id": scene["decision_id"],
            "candidate_id": scene["candidate_id"],
            "territory_id": scene["territory_id"],
            "opened_at": scene["decision"] - timedelta(seconds=3),
            "closed_at": (
                None
                if scene["decision_id"] == "decision-004"
                else scene["decision"] + timedelta(minutes=12)
            ),
            "status": "open" if scene["decision_id"] == "decision-004" else "closed",
            "reentry_of_episode_id": (
                "episode-runner" if scene["decision_id"] == "decision-003" else None
            ),
            "operator_disposition": (
                "reenter_after_exit" if scene["decision_id"] == "decision-003" else "crackle"
            ),
            "available_commit_seq": scene["commit"] + 2,
        }
        for scene in scenes
    ]
    gestures: list[dict[str, Any]] = []
    for scene in scenes:
        gestures.extend(
            [
                {
                    "gesture_id": f"gesture:inspect:{scene['decision_id']}",
                    "decision_id": scene["decision_id"],
                    "scene_id": scene["scene_id"],
                    "scene_view_digest": _digest(f"view:{scene['scene_id']}:v1"),
                    "candidate_id": scene["candidate_id"],
                    "episode_id": None,
                    "gesture_kind": "inspect_candidate",
                    "issued_at": scene["decision"] - timedelta(seconds=8),
                    "received_at": scene["decision"] - timedelta(seconds=7),
                    "available_at": scene["decision"] - timedelta(seconds=6),
                    "command_payload_digest": _digest(f"gesture:inspect:{scene['decision_id']}"),
                    "available_commit_seq": scene["commit"] - 1,
                },
                {
                    "gesture_id": f"gesture:select:{scene['decision_id']}",
                    "decision_id": scene["decision_id"],
                    "scene_id": scene["scene_id"],
                    "scene_view_digest": _digest(f"view:{scene['scene_id']}:v1"),
                    "candidate_id": scene["candidate_id"],
                    "episode_id": scene["episode_id"],
                    "gesture_kind": "mark_enter_or_continue",
                    "issued_at": scene["decision"] - timedelta(seconds=3),
                    "received_at": scene["decision"] - timedelta(seconds=2),
                    "available_at": scene["decision"] - timedelta(seconds=1),
                    "command_payload_digest": _digest(f"gesture:select:{scene['decision_id']}"),
                    "available_commit_seq": scene["commit"],
                },
            ]
        )
    gestures.append(
        {
            "gesture_id": "gesture:partial-exit:decision-001",
            "decision_id": "decision-001",
            "scene_id": "scene-001",
            "scene_view_digest": _digest("view:scene-001:v1"),
            "candidate_id": "candidate-a",
            "episode_id": "episode-runner",
            "gesture_kind": "mark_partial_exit_runner",
            "issued_at": datetime(2026, 8, 14, 12, 9, tzinfo=UTC),
            "received_at": datetime(2026, 8, 14, 12, 9, 1, tzinfo=UTC),
            "available_at": datetime(2026, 8, 14, 12, 9, 2, tzinfo=UTC),
            "command_payload_digest": _digest("gesture:partial-exit:decision-001"),
            "available_commit_seq": 48,
        }
    )
    interviews = [
        {
            "interview_id": "interview:decision-001:post",
            "decision_id": "decision-001",
            "scene_id": "scene-001",
            "episode_id": "episode-runner",
            "elicited_at": datetime(2026, 8, 14, 12, 30, tzinfo=UTC),
            "available_at": datetime(2026, 8, 14, 12, 31, tzinfo=UTC),
            "prompt_version": "operator-debrief/v1",
            "transcript_blob_id": _digest("transcript:decision-001"),
            "operator_disposition": "runner_possible",
            "crackle_type": "microdip_then_hold_remainder",
            "confidence_ppm": 650_000,
            "outcome_visible_before_elicitation": True,
            "available_commit_seq": 52,
        },
        {
            "interview_id": "interview:decision-004:post",
            "decision_id": "decision-004",
            "scene_id": "scene-004",
            "episode_id": "episode-validation",
            "elicited_at": datetime(2026, 8, 16, 15, 20, tzinfo=UTC),
            "available_at": datetime(2026, 8, 16, 15, 21, tzinfo=UTC),
            "prompt_version": "operator-debrief/v1",
            "transcript_blob_id": _digest("transcript:decision-004"),
            "operator_disposition": "uncertain_due_to_gap",
            "crackle_type": None,
            "confidence_ppm": 300_000,
            "outcome_visible_before_elicitation": True,
            "available_commit_seq": 118,
        },
    ]
    outcomes = [
        {
            "decision_id": "decision-001",
            "candidate_id": "candidate-a",
            "episode_id": "episode-runner",
            "event_kind": "profit_target",
            "event_time": datetime(2026, 8, 14, 12, 12, tzinfo=UTC),
            "outcome_known_at": datetime(2026, 8, 14, 12, 26, tzinfo=UTC),
            "horizon_end": datetime(2026, 8, 14, 12, 25, tzinfo=UTC),
            "is_censored": False,
            "censoring_reason": None,
            "competing_risk_set": "crackle_20m/v1",
            "available_commit_seq": 50,
        },
        {
            "decision_id": "decision-002",
            "candidate_id": "candidate-c",
            "episode_id": "episode-downpath",
            "event_kind": "drawdown_stop",
            "event_time": datetime(2026, 8, 14, 13, 10, tzinfo=UTC),
            "outcome_known_at": datetime(2026, 8, 14, 13, 26, tzinfo=UTC),
            "horizon_end": datetime(2026, 8, 14, 13, 25, tzinfo=UTC),
            "is_censored": False,
            "censoring_reason": None,
            "competing_risk_set": "crackle_20m/v1",
            "available_commit_seq": 70,
        },
        {
            "decision_id": "decision-003",
            "candidate_id": "candidate-b",
            "episode_id": "episode-reentry",
            "event_kind": "liquidity_exit",
            "event_time": datetime(2026, 8, 15, 14, 9, tzinfo=UTC),
            "outcome_known_at": datetime(2026, 8, 15, 14, 26, tzinfo=UTC),
            "horizon_end": datetime(2026, 8, 15, 14, 25, tzinfo=UTC),
            "is_censored": False,
            "censoring_reason": None,
            "competing_risk_set": "crackle_20m/v1",
            "available_commit_seq": 90,
        },
        {
            "decision_id": "decision-004",
            "candidate_id": "candidate-d",
            "episode_id": "episode-validation",
            "event_kind": None,
            "event_time": None,
            "outcome_known_at": datetime(2026, 8, 16, 14, 12, tzinfo=UTC),
            "horizon_end": datetime(2026, 8, 16, 14, 25, tzinfo=UTC),
            "is_censored": True,
            "censoring_reason": "coverage_gap:coverage-gap:scene-004",
            "competing_risk_set": "crackle_20m/v1",
            "available_commit_seq": 108,
        },
    ]
    coverage_windows = [
        {
            "coverage_window_id": f"coverage-window:{scene['scene_id']}",
            "coverage_scope_id": f"scope:chart:{scene['candidate_id']}",
            "source_id": "source:fixture:pump",
            "lower_time": scene["start"],
            "upper_time": scene["decision"],
            "coverage_kind": "expected_minute_samples",
            "available_commit_seq": scene["commit"] - 4,
        }
        for scene in scenes
    ]
    coverage_gaps = []
    for scene in scenes:
        if scene["gap_index"] is None:
            continue
        opened = scene["start"] + timedelta(minutes=scene["gap_index"])
        coverage_gaps.append(
            {
                "coverage_gap_id": f"coverage-gap:{scene['scene_id']}",
                "coverage_window_id": f"coverage-window:{scene['scene_id']}",
                "coverage_scope_id": f"scope:chart:{scene['candidate_id']}",
                "gap_class": "source_sample_missing",
                "opened_at": opened,
                "detected_at": opened + timedelta(seconds=2),
                "available_at": opened + timedelta(seconds=4),
                "recovered_at": opened + timedelta(minutes=1),
                "recovery_known_at": opened + timedelta(minutes=1, seconds=4),
                "available_commit_seq": scene["commit"] - 1,
            }
        )

    assertion_specs: dict[str, tuple[str, datetime, int, str]] = {}
    for row in territories:
        assertion_specs[row["source_assertion_id"]] = (
            "source:fixture:pump",
            row["first_available_at"],
            row["available_commit_seq"],
            f"territory:{row['territory_id']}",
        )
    for row in candidates:
        assertion_specs[row["source_assertion_id"]] = (
            "source:fixture:chain",
            row["first_available_at"],
            row["available_commit_seq"],
            f"candidate:{row['candidate_id']}",
        )
    for row in social:
        assertion_specs[row["source_assertion_id"]] = (
            "source:fixture:pump",
            row["available_at"],
            row["available_commit_seq"],
            f"social:{row['candidate_id']}",
        )
    for scene in scenes:
        assertion_specs[f"assertion:market:{scene['scene_id']}"] = (
            "source:fixture:pump",
            scene["decision"] - timedelta(seconds=11),
            scene["commit"] - 2,
            f"market:{scene['scene_id']}",
        )
    provenance = [
        {
            "source_assertion_id": assertion_id,
            "source_observation_id": f"observation:{assertion_id}",
            "source_id": source_id,
            "semantic_key": semantic_key,
            "value_digest": _digest(f"value:{assertion_id}"),
            "observed_at": available_at - timedelta(seconds=1),
            "available_at": available_at,
            "available_commit_seq": commit,
        }
        for assertion_id, (source_id, available_at, commit, semantic_key) in sorted(
            assertion_specs.items()
        )
    ]

    rows_by_name: dict[str, list[dict[str, Any]]] = {
        "scenes": scene_rows,
        "territories": territories,
        "candidates": candidates,
        "candidate_social_assertions": social,
        "decisions": decisions,
        "choice_members": choices,
        "episodes": episodes,
        "chart_samples": fixture_rows(),
        "operator_gestures": gestures,
        "operator_interviews": interviews,
        "outcomes": outcomes,
        "provenance_assertions": provenance,
        "coverage_windows": coverage_windows,
        "coverage_gaps": coverage_gaps,
    }
    return {
        name: pa.Table.from_pylist(rows_by_name[name], schema=contract.schema)
        for name, contract in TABLE_CONTRACTS.items()
    }


def fixture_catalog() -> dict[str, Any]:
    projection_digest = _digest("projection:research-export:fixture-v1")
    return {
        "catalog_id": "catalog:joshi:offline-fixture",
        "catalog_schema": "joshi.store.catalog/v5",
        "from_commit_seq": "1",
        "through_commit_seq": "120",
        "as_of": {
            "catalog_commit": "120",
            "sources": [
                {
                    "source_id": "source:fixture:chain",
                    "delivered_through": "116",
                    "scoped_cursors": [
                        {
                            "family": "chain",
                            "subject": None,
                            "cursor_kind": "slot",
                            "value": "348000001",
                            "advanced_through": "116",
                        }
                    ],
                    "received_through": "2026-08-16T17:30:00.000000Z",
                },
                {
                    "source_id": "source:fixture:pump",
                    "delivered_through": "118",
                    "scoped_cursors": [
                        {
                            "family": "attention",
                            "subject": None,
                            "cursor_kind": "fixture_epoch",
                            "value": "fixture-v1",
                            "advanced_through": "118",
                        }
                    ],
                    "received_through": "2026-08-16T17:45:00.000000Z",
                },
            ],
            "chain": {
                "cluster": "solana:mainnet-beta",
                "slot": "348000001",
                "finality": "finalized",
            },
            "projections": [
                {
                    "name": "research_exocortex",
                    "version": "1",
                    "state_digest": projection_digest,
                    "delivered_through": "120",
                }
            ],
            "rendered_at": "2026-08-16T18:00:00.000000Z",
        },
    }


def write_fixture_snapshot(
    destination: str | Path,
    *,
    rows: list[dict[str, Any]] | None = None,
    table_overrides: dict[str, pa.Table] | None = None,
) -> Path:
    destination_path = Path(destination)
    if destination_path.exists():
        raise ImmutableOutputError(f"refusing to overwrite fixture snapshot: {destination_path}")
    destination_path.mkdir(parents=True)
    tables = fixture_tables()
    if rows is not None:
        tables["chart_samples"] = pa.Table.from_pylist(
            rows, schema=TABLE_CONTRACTS["chart_samples"].schema
        )
    if table_overrides:
        tables.update(table_overrides)
    table_paths: dict[str, Path] = {}
    for name, table in tables.items():
        table_path = destination_path / f"{name}.parquet"
        pq.write_table(
            table,
            table_path,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
            data_page_version="1.0",
            version="2.6",
            row_group_size=max(1, table.num_rows),
        )
        table_paths[name] = table_path
    projection_digest = _digest("projection:research-export:fixture-v1")
    manifest = make_snapshot_manifest(
        table_paths,
        tables,
        created_at=FIXTURE_CREATED_AT,
        producer={
            "build": "joshi-fixture-exporter/1",
            "projection_name": "research_exocortex",
            "projection_version": "1",
            "projection_state_digest": projection_digest,
        },
        catalog=fixture_catalog(),
        maximum_decision_available_at=max(scene["decision"] for scene in _scene_specs()),
    )
    (destination_path / "manifest.json").write_bytes(canonical_json_bytes(manifest, newline=True))
    return destination_path
