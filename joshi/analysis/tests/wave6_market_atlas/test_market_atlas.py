from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest

from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_market_atlas import AtlasCut, MarketAtlasInputs, build_market_atlas
from joshi_analysis.wave6_market_atlas.contracts import (
    ATLAS_SNAPSHOT_SCHEMA,
    ATLAS_TRAJECTORY_SCHEMA,
    CALLER_ATTENTION_SCHEMA,
    CANONICAL_VENUE_STATE_SCHEMA,
    LIQUIDITY_TOPOLOGY_SCHEMA,
    MINT_LIFECYCLE_SCHEMA,
    PORTFOLIO_WATCH_SCHEMA,
    WALLET_CLUSTER_FLOW_SCHEMA,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _common(
    record_id: str,
    component_id: str,
    version: str,
    *,
    lower: datetime = T0,
    upper: datetime = T0 + timedelta(hours=1),
    available: datetime = T0,
    retracted: datetime | None = None,
    status: str = "observed",
    source_version: str = "source:v1",
    native_event: str | None = None,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_id": "source:fixture",
        "source_version_id": source_version,
        "native_event_id": native_event or f"event:{record_id}",
        "subject_id": "mint:one",
        "component_id": component_id,
        "component_version_id": version,
        "valid_lower": lower,
        "valid_upper": upper,
        "available_at": available,
        "retracted_at": retracted,
        "available_commit_seq": 4,
        "coverage_status": status,
        "coverage_window_id": "coverage:healthy" if status == "observed" else None,
        "coverage_gap_id": None if status == "observed" else "gap:declared",
    }


def _inputs(
    *, correction_available: datetime | None = None, unknown_attention: bool = False
) -> MarketAtlasInputs:
    lifecycle = _common("life:1", "mint:one", "life:v1") | {
        "mint_id": "mint:one",
        "lifecycle_version_id": "life:v1",
        "lifecycle_state": "bonding_curve",
        "canonical_venue_id": "venue:curve",
        "lifecycle_transition_kind": "launch",
    }
    venue = _common(
        "venue:original",
        "venue:curve",
        "venue:v1",
        retracted=T0 + timedelta(minutes=30) if correction_available else None,
    ) | {
        "venue_id": "venue:curve",
        "venue_profile_id": "profile:curve-v1",
        "venue_state_version_id": "venue:v1",
        "venue_state_kind": "reserve_state",
        "base_asset_id": "mint:one",
        "quote_asset_id": "asset:sol",
        "price_carrier_kind": "quote_atoms_per_base_atom",
        "price_numerator_atoms": 10,
        "price_denominator_atoms": 2,
        "price_numerator_unit": "quote_asset_atoms",
        "price_denominator_unit": "base_asset_atoms",
    }
    venue_rows = [venue]
    if correction_available:
        venue_rows.append(
            _common(
                "venue:corrected",
                "venue:curve",
                "venue:v2",
                available=correction_available,
                source_version="source:v2",
                native_event="event:venue:original",
            )
            | (
                venue
                | {
                    "record_id": "venue:corrected",
                    "component_version_id": "venue:v2",
                    "venue_state_version_id": "venue:v2",
                    "available_at": correction_available,
                    "source_version_id": "source:v2",
                    "native_event_id": "event:venue:original",
                    "retracted_at": None,
                    "price_numerator_atoms": 12,
                }
            )
        )
    liquidity = _common("topology:1", "bin:12", "topology:v1") | {
        "venue_id": "venue:curve",
        "topology_epoch": "topology:curve",
        "topology_version_id": "topology:v1",
        "topology_element_id": "bin:12",
        "topology_element_kind": "reserve",
        "liquidity_measure_kind": "base_reserve",
        "liquidity_atoms": 500,
        "liquidity_unit": "base_asset_atoms",
    }
    wallet = _common("flow:1", "wallet:alice", "wallet:v1") | {
        "wallet_id": "wallet:alice",
        "wallet_identity_version_id": "wallet:v1",
        "cluster_id": "cluster:one",
        "cluster_version_id": "cluster:v1",
        "flow_direction": "buy",
        "signed_flow_atoms": 13,
        "flow_unit": "base_asset_atoms",
    }
    attention = _common(
        "attention:1",
        "caller:one",
        "caller:v1",
        status="unknown" if unknown_attention else "observed",
    ) | {
        "caller_id": None if unknown_attention else "caller:one",
        "caller_identity_version_id": None if unknown_attention else "caller:v1",
        "attention_stage": None if unknown_attention else "rendered",
        "attention_count": None if unknown_attention else 2,
        "attention_unit": None if unknown_attention else "events",
        "surface_version_id": None if unknown_attention else "surface:v1",
    }
    portfolio = _common("watch:1", "episode:one", "watch:v1") | {
        "episode_id": "episode:one",
        "inventory_epoch_id": None,
        "portfolio_watch_version_id": "watch:v1",
        "portfolio_state": "flat",
        "watch_state": "watching_flat",
        "base_asset_atoms": 0,
        "base_asset_unit": "base_asset_atoms",
    }
    return MarketAtlasInputs(
        mint_lifecycle=pa.Table.from_pylist([lifecycle], schema=MINT_LIFECYCLE_SCHEMA),
        canonical_venue_state=pa.Table.from_pylist(venue_rows, schema=CANONICAL_VENUE_STATE_SCHEMA),
        liquidity_topology=pa.Table.from_pylist([liquidity], schema=LIQUIDITY_TOPOLOGY_SCHEMA),
        wallet_cluster_flow=pa.Table.from_pylist([wallet], schema=WALLET_CLUSTER_FLOW_SCHEMA),
        caller_attention=pa.Table.from_pylist([attention], schema=CALLER_ATTENTION_SCHEMA),
        portfolio_watch=pa.Table.from_pylist([portfolio], schema=PORTFOLIO_WATCH_SCHEMA),
    )


def _cut(
    name: str,
    *,
    state: datetime = T0 + timedelta(minutes=10),
    known: datetime = T0 + timedelta(minutes=20),
) -> AtlasCut:
    return AtlasCut(name, state, known, 4)


def test_atlas_preserves_all_native_strata_and_exact_point_in_time_closure() -> None:
    atlas = build_market_atlas(_inputs(), [_cut("cut:one")])
    assert atlas.snapshots.schema.equals(ATLAS_SNAPSHOT_SCHEMA, check_metadata=True)
    assert atlas.trajectories.schema.equals(ATLAS_TRAJECTORY_SCHEMA, check_metadata=True)
    rows = atlas.snapshots.to_pylist()
    assert {row["component_kind"] for row in rows} == {
        "mint_lifecycle",
        "canonical_venue_state",
        "liquidity_topology",
        "wallet_cluster_flow",
        "caller_attention",
        "portfolio_watch",
    }
    assert len({row["atlas_snapshot_id"] for row in rows}) == 1
    assert {row["semantic_ceiling"] for row in rows} == {
        "caller_fed_unverified_semantic_fixture_only"
    }
    assert all(
        row["source_id"] == "source:fixture" and row["native_event_id"].startswith("event:")
        for row in rows
    )
    assert all("not_scalar_pressure_causal_or_strategy_claim" in row["claim_scope"] for row in rows)


def test_future_known_correction_does_not_rewrite_earlier_cut() -> None:
    inputs = _inputs(correction_available=T0 + timedelta(minutes=40))
    earlier = build_market_atlas(inputs, [_cut("cut:early")])
    later = build_market_atlas(
        inputs,
        [_cut("cut:late", state=T0 + timedelta(minutes=45), known=T0 + timedelta(minutes=50))],
    )
    early_venue = next(
        row
        for row in earlier.snapshots.to_pylist()
        if row["component_kind"] == "canonical_venue_state"
    )
    late_venue = next(
        row
        for row in later.snapshots.to_pylist()
        if row["component_kind"] == "canonical_venue_state"
    )
    assert early_venue["record_id"] == "venue:original"
    assert late_venue["record_id"] == "venue:corrected"


def test_topology_change_forms_a_trajectory_without_crossing_versions() -> None:
    inputs = _inputs()
    rows = inputs.liquidity_topology.to_pylist()
    rows[0]["valid_upper"] = T0 + timedelta(minutes=30)
    later = dict(rows[0])
    later.update(
        {
            "record_id": "topology:2",
            "component_version_id": "topology:v2",
            "valid_lower": T0 + timedelta(minutes=30),
            "valid_upper": T0 + timedelta(hours=1),
            "topology_epoch": "topology:amm",
            "topology_version_id": "topology:v2",
        }
    )
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "liquidity_topology": pa.Table.from_pylist(
                [*rows, later], schema=LIQUIDITY_TOPOLOGY_SCHEMA
            ),
        }
    )
    atlas = build_market_atlas(
        changed,
        [
            _cut("cut:before"),
            _cut("cut:after", state=T0 + timedelta(minutes=40), known=T0 + timedelta(minutes=45)),
        ],
    )
    path = next(
        row
        for row in atlas.trajectories.to_pylist()
        if row["component_kind"] == "liquidity_topology"
    )
    assert path["record_ids"] == ["topology:1", "topology:2"]


def test_unknown_attention_is_retained_as_unknown_not_empty_or_zero() -> None:
    atlas = build_market_atlas(_inputs(unknown_attention=True), [_cut("cut:one")])
    row = next(
        row for row in atlas.snapshots.to_pylist() if row["component_kind"] == "caller_attention"
    )
    path = next(
        row for row in atlas.trajectories.to_pylist() if row["component_kind"] == "caller_attention"
    )
    assert row["coverage_status"] == "unknown"
    assert row["coverage_gap_id"] == "gap:declared"
    assert path["trajectory_status"] == "path_with_declared_nonobservation"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("price_denominator_atoms", None, "complete typed price carrier"),
        ("price_denominator_unit", "quote_asset_atoms", "mixed or unsupported price units"),
        ("price_carrier_kind", "last_trade", "price carrier"),
    ],
)
def test_price_carriers_and_units_fail_closed(field: str, value: object, message: str) -> None:
    inputs = _inputs()
    rows = inputs.canonical_venue_state.to_pylist()
    rows[0][field] = value
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "canonical_venue_state": pa.Table.from_pylist(
                rows, schema=CANONICAL_VENUE_STATE_SCHEMA
            ),
        }
    )
    with pytest.raises(ManifestError, match=message):
        build_market_atlas(changed, [_cut("cut:one")])


def test_future_null_semantic_index_is_inert_earlier_and_refuses_when_known() -> None:
    inputs = _inputs()
    future = dict(inputs.canonical_venue_state.to_pylist()[0])
    future.update(
        {
            "record_id": "venue:future-malformed",
            "source_version_id": "source:future",
            "native_event_id": "event:venue:future",
            "component_version_id": "venue:future",
            "venue_state_version_id": "venue:future",
            "valid_lower": None,
            "valid_upper": T0 + timedelta(hours=3),
            "available_at": T0 + timedelta(hours=2),
            "available_commit_seq": 99,
            "price_denominator_atoms": None,
        }
    )
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "canonical_venue_state": pa.Table.from_pylist(
                [*inputs.canonical_venue_state.to_pylist(), future],
                schema=CANONICAL_VENUE_STATE_SCHEMA,
            ),
        }
    )
    baseline = build_market_atlas(inputs, [_cut("cut:one")])
    unaffected = build_market_atlas(changed, [_cut("cut:one")])
    assert unaffected.snapshots.to_pylist() == baseline.snapshots.to_pylist()
    assert unaffected.trajectories.to_pylist() == baseline.trajectories.to_pylist()
    with pytest.raises(ManifestError, match=r"canonical_venue_state\.valid_lower"):
        build_market_atlas(
            changed,
            [
                AtlasCut(
                    "cut:future",
                    T0 + timedelta(hours=2, minutes=30),
                    T0 + timedelta(hours=2, minutes=30),
                    99,
                )
            ],
        )


def test_native_component_and_source_version_substitution_refuse() -> None:
    inputs = _inputs()
    divergent = inputs.wallet_cluster_flow.to_pylist()
    divergent[0].update(
        {
            "wallet_id": "wallet:identity-b",
            "wallet_identity_version_id": "wallet:b:v99",
        }
    )
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "wallet_cluster_flow": pa.Table.from_pylist(
                divergent, schema=WALLET_CLUSTER_FLOW_SCHEMA
            ),
        }
    )
    with pytest.raises(ManifestError, match="component identity diverges"):
        build_market_atlas(changed, [_cut("cut:one")])

    substituted = dict(inputs.wallet_cluster_flow.to_pylist()[0])
    substituted.update(
        {
            "record_id": "flow:substituted",
            "valid_upper": T0 + timedelta(hours=2),
            "signed_flow_atoms": 999,
        }
    )
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "wallet_cluster_flow": pa.Table.from_pylist(
                [*inputs.wallet_cluster_flow.to_pylist(), substituted],
                schema=WALLET_CLUSTER_FLOW_SCHEMA,
            ),
        }
    )
    with pytest.raises(ManifestError, match="duplicate native event/source-version semantics"):
        build_market_atlas(changed, [_cut("cut:one")])


def test_duplicate_identities_and_selected_versions_fail_closed() -> None:
    inputs = _inputs()
    duplicate = inputs.wallet_cluster_flow.to_pylist() * 2
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "wallet_cluster_flow": pa.Table.from_pylist(
                duplicate, schema=WALLET_CLUSTER_FLOW_SCHEMA
            ),
        }
    )
    with pytest.raises(ManifestError, match="duplicate occurrence identity"):
        build_market_atlas(changed, [_cut("cut:one")])

    venue_rows = inputs.canonical_venue_state.to_pylist()
    competing = dict(venue_rows[0])
    competing.update(
        {
            "record_id": "venue:conflict",
            "source_version_id": "source:other",
            "component_version_id": "venue:other",
            "venue_state_version_id": "venue:other",
        }
    )
    changed = MarketAtlasInputs(
        **{
            **inputs.__dict__,
            "canonical_venue_state": pa.Table.from_pylist(
                [*venue_rows, competing], schema=CANONICAL_VENUE_STATE_SCHEMA
            ),
        }
    )
    with pytest.raises(ManifestError, match="conflicting canonical_venue_state"):
        build_market_atlas(changed, [_cut("cut:one")])


def test_artifacts_are_permutation_stable() -> None:
    inputs = _inputs()
    reversed_inputs = MarketAtlasInputs(
        **{
            name: table.take(pa.array(list(reversed(range(table.num_rows))), type=pa.int64()))
            for name, table in inputs.__dict__.items()
        }
    )
    cuts = [_cut("cut:one")]
    baseline = build_market_atlas(inputs, cuts)
    permuted = build_market_atlas(reversed_inputs, cuts)
    assert baseline.snapshots.to_pylist() == permuted.snapshots.to_pylist()
    assert baseline.trajectories.to_pylist() == permuted.trajectories.to_pylist()
