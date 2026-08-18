from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from joshi_analysis.canonical import canonical_json_bytes, schema_descriptor
from joshi_analysis.errors import ManifestError
from joshi_analysis.wave6_market_atlas.contracts import ATLAS_SNAPSHOT_SCHEMA
from joshi_analysis.wave6_research_desk import (
    FIXTURE_PACKET_AUTHORITY,
    build_fixture_research_packet,
    parse_fixture_program_registration_exact,
)
from joshi_analysis.wave6_research_desk.fixture_packet import research_proposal_schema_bytes

ROOT = Path(__file__).resolve().parents[3]
REGISTRATION = ROOT / "fixtures/wave6/program_registration_v1.json"
CAMPAIGN_SCHEMA = ROOT / "fixtures/wave6/schemas/campaign_registration_v1.json"
MARKET_SCHEMA = ROOT / "fixtures/wave6/schemas/market_atlas_snapshot_v1.json"
RESEARCH_SCHEMA = ROOT / "fixtures/wave6/schemas/research_proposal_v1.json"


def _schemas() -> dict[str, bytes]:
    return {
        "campaign_registration_fixture": CAMPAIGN_SCHEMA.read_bytes(),
        "market_atlas_fixture": MARKET_SCHEMA.read_bytes(),
        "research_proposal_fixture": RESEARCH_SCHEMA.read_bytes(),
    }


def test_registered_schema_bytes_are_exact_and_packet_is_deterministic() -> None:
    expected_market = canonical_json_bytes(schema_descriptor(ATLAS_SNAPSHOT_SCHEMA), newline=True)
    assert MARKET_SCHEMA.read_bytes() == expected_market
    assert RESEARCH_SCHEMA.read_bytes() == research_proposal_schema_bytes()
    first = build_fixture_research_packet(REGISTRATION.read_bytes(), _schemas())
    second = build_fixture_research_packet(REGISTRATION.read_bytes(), _schemas())
    assert first == second
    assert first.authority == FIXTURE_PACKET_AUTHORITY
    assert first.status == "protocol_draft"
    assert first.query_count == 0
    assert not first.executable
    assert len(first.known_truth_evaluation.passed_case_ids) == 8
    assert first.proposal.artifact_descriptors[0].provenance_digest == (
        first.known_truth_evaluation.evaluation_digest
    )
    packet = first.as_dict(_schemas())
    assert packet["claim_scope"].endswith("not_result_release_or_live_decision")
    assert packet["proposal"]["specification"]["experiments"][0]["query_count"] == 0


def test_python_independently_reparses_rust_registration_and_schema_closure() -> None:
    registration = parse_fixture_program_registration_exact(REGISTRATION.read_bytes(), _schemas())
    assert registration.program_id == "w6-program-fixture-001"
    assert registration.document["consumedWave5Gates"] == []
    assert registration.document["budgets"]["providerUnits"] == "0"
    assert registration.document["budgets"]["externalMutationUnits"] == "0"

    wrong = _schemas() | {"research_proposal_fixture": b"{}\n"}
    with pytest.raises(ManifestError, match="schema bytes"):
        parse_fixture_program_registration_exact(REGISTRATION.read_bytes(), wrong)


def test_registration_unknown_field_reordering_and_budget_widening_refuse() -> None:
    exact = REGISTRATION.read_bytes()
    unknown = exact[:-2] + b',"durableReceipt":{"commitSeq":"1"}}\n'
    with pytest.raises(ManifestError, match="keys/order"):
        parse_fixture_program_registration_exact(unknown, _schemas())

    document = REGISTRATION.read_text()
    reordered = document.replace(
        '"programId":"w6-program-fixture-001","programFamilyId"',
        '"programFamilyId":"reflexive-field-lab-fixture","programId":"w6-program-fixture-001","discarded"',
        1,
    )
    with pytest.raises(ManifestError):
        parse_fixture_program_registration_exact(reordered.encode(), _schemas())

    widened = exact.replace(b'"providerUnits":"0"', b'"providerUnits":"1"')
    with pytest.raises(ManifestError, match="self-digest mismatch"):
        parse_fixture_program_registration_exact(widened, _schemas())


def test_packet_proposal_evaluation_authority_and_digest_substitution_refuse() -> None:
    packet = build_fixture_research_packet(REGISTRATION.read_bytes(), _schemas())
    with pytest.raises(ManifestError, match="identity"):
        replace(packet, packet_digest="sha256:" + "0" * 64).validate(_schemas())
    with pytest.raises(ManifestError, match="widened"):
        replace(packet, authority="may_query_and_trade").validate(_schemas())
    changed_evaluation = replace(
        packet.known_truth_evaluation, evaluation_digest="sha256:" + "1" * 64
    )
    with pytest.raises(ManifestError, match="known-truth closure"):
        replace(packet, known_truth_evaluation=changed_evaluation).validate(_schemas())
