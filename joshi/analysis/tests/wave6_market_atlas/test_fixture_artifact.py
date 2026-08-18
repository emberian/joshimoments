from __future__ import annotations

import json
from pathlib import Path

from joshi_analysis.canonical import canonical_json_bytes, qualified_sha256_bytes
from joshi_analysis.wave6_market_atlas import (
    market_atlas_fixture_bytes,
    market_atlas_fixture_document,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures" / "wave6" / "artifacts" / "market_atlas_snapshot_v1.json"


def test_market_atlas_fixture_is_exact_cross_runtime_material() -> None:
    exact = market_atlas_fixture_bytes()
    assert exact == FIXTURE.read_bytes()
    value = json.loads(exact)
    assert value == market_atlas_fixture_document()
    assert value["row_count"] == "6"
    assert {row["component_kind"] for row in value["rows"]} == {
        "mint_lifecycle",
        "canonical_venue_state",
        "liquidity_topology",
        "wallet_cluster_flow",
        "caller_attention",
        "portfolio_watch",
    }
    material = {key: item for key, item in value.items() if key != "artifact_digest"}
    assert value["artifact_digest"] == qualified_sha256_bytes(canonical_json_bytes(material))
    assert value["authority"] == "caller_fed_unverified_semantic_fixture_only"
    assert value["claim_scope"].endswith("not_scalar_pressure_causal_or_strategy_claim")
