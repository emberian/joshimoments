from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pyarrow as pa

from .contracts import GRAPH_EDGE_SCHEMA, VENUE_RESPONSE_SCHEMA


def synthetic_field_inputs() -> tuple[pa.Table, pa.Table, datetime]:
    start = datetime(2026, 8, 10, 12, tzinfo=UTC)
    edge_specs = [
        ("wallet_flow", "topology-1", "A", "B", 30, "cycle-abc", 1, False),
        ("wallet_flow", "topology-1", "B", "C", 30, "cycle-abc", 1, False),
        ("wallet_flow", "topology-1", "C", "A", 30, "cycle-abc", 1, False),
        ("attention_flow", "topology-1", "A", "B", 10, "cycle-abc", 1, False),
        ("attention_flow", "topology-1", "B", "C", 0, "cycle-abc", 1, False),
        ("attention_flow", "topology-1", "C", "A", 0, "cycle-abc", 1, False),
        ("wallet_flow", "topology-2", "A", "B", 12, None, None, False),
        ("wallet_flow", "topology-2", "B", "D", 5, None, None, False),
        ("wallet_flow", "topology-2", "D", "A", 7, None, None, False),
        ("attention_flow", "topology-2", "A", "D", 0, None, None, True),
    ]
    edges = []
    for ordinal, (layer, topology, source, target, flow, cycle, orientation, gap) in enumerate(
        edge_specs, 1
    ):
        observed = start + timedelta(days=0 if topology == "topology-1" else 1)
        topology_lower = start if topology == "topology-1" else start + timedelta(days=1)
        topology_upper = topology_lower + timedelta(days=1)
        edges.append(
            {
                "edge_observation_id": f"field-edge:{ordinal:03d}",
                "layer_kind": layer,
                "topology_epoch": topology,
                "topology_version_id": f"topology-version:{topology}",
                "edge_id": f"{topology}:{layer}:{source}->{target}",
                "source_node_id": source,
                "target_node_id": target,
                "flow_value": None if gap else flow,
                "flow_unit": "marked_flow_atoms",
                "carrier_kind": "asset" if layer == "wallet_flow" else "attention_event",
                "carrier_id": "asset:fixture:base" if layer == "wallet_flow" else "attention:count",
                "cycle_id": cycle,
                "cycle_orientation": orientation,
                "observed_at": observed,
                "valid_lower": observed,
                "valid_upper": observed + timedelta(microseconds=1),
                "available_at": observed + timedelta(seconds=2),
                "topology_valid_lower": topology_lower,
                "topology_valid_upper": topology_upper,
                "topology_available_at": topology_lower - timedelta(hours=1),
                "topology_retracted_at": None,
                "information_cutoff": observed + timedelta(seconds=5),
                "coverage_status": "gap" if gap else "observed",
                "coverage_window_id": f"field-window:{topology}:{layer}",
                "coverage_gap_id": f"field-gap:{ordinal:03d}" if gap else None,
                "available_commit_seq": 2_000 + ordinal,
            }
        )
    venues = []
    for ordinal, (
        topology,
        base,
        quote,
        shock_base,
        shock_quote,
        rec_base,
        rec_quote,
        flow,
    ) in enumerate(
        [
            ("topology-1", 1_000, 2_000, 900, 2_200, 980, 2_020, -100),
            ("topology-2", 2_000, 2_000, 2_100, 1_900, 2_020, 1_980, 100),
        ],
        1,
    ):
        observed = start + timedelta(days=ordinal - 1, minutes=10)
        topology_lower = start + timedelta(days=ordinal - 1)
        venues.append(
            {
                "venue_response_id": f"venue-response:{ordinal}",
                "venue_id": "venue:fixture-amm",
                "candidate_id": "candidate-a",
                "topology_epoch": topology,
                "topology_version_id": f"topology-version:{topology}",
                "liquidity_model": "synthetic_constant_product_xy_eq_k",
                "formula_version": "synthetic_cpmm/v1",
                "reserve_state_digest": f"sha256:{ordinal:064x}",
                "base_asset_id": "asset:fixture:base",
                "quote_asset_id": "asset:fixture:quote",
                "baseline_base_atoms": Decimal(base),
                "baseline_quote_atoms": Decimal(quote),
                "shock_base_atoms": Decimal(shock_base),
                "shock_quote_atoms": Decimal(shock_quote),
                "recovery_base_atoms": Decimal(rec_base),
                "recovery_quote_atoms": Decimal(rec_quote),
                "signed_flow_base_atoms": flow,
                "observed_at": observed,
                "valid_lower": observed,
                "valid_upper": observed + timedelta(microseconds=1),
                "available_at": observed + timedelta(seconds=4),
                "topology_valid_lower": topology_lower,
                "topology_valid_upper": topology_lower + timedelta(days=1),
                "topology_available_at": topology_lower - timedelta(hours=1),
                "topology_retracted_at": None,
                "information_cutoff": observed + timedelta(seconds=5),
                "coverage_status": "observed",
                "coverage_window_id": f"venue-window:{topology}",
                "coverage_gap_id": None,
                "available_commit_seq": 3_000 + ordinal,
            }
        )
    cutoff = datetime(2026, 8, 13, tzinfo=UTC)
    return (
        pa.Table.from_pylist(edges, schema=GRAPH_EDGE_SCHEMA),
        pa.Table.from_pylist(venues, schema=VENUE_RESPONSE_SCHEMA),
        cutoff,
    )
