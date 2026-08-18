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
KNOWN_TRUTH_SCHEMA = ROOT / "fixtures/wave6/schemas/known_truth_evaluation_v1.json"
MARKET_SCHEMA = ROOT / "fixtures/wave6/schemas/market_atlas_snapshot_v1.json"
PROTOCOL_TRUTH_SCHEMA = ROOT / "fixtures/wave6/schemas/protocol_known_truth_evaluation_v1.json"
RESEARCH_SCHEMA = ROOT / "fixtures/wave6/schemas/research_proposal_v1.json"
PUMP_FIXTURE = ROOT / "fixtures/protocol/pump_quotes.json"
DLMM_FIXTURE = ROOT / "fixtures/protocol/dlmm.json"


def _schemas() -> dict[str, bytes]:
    return {
        "campaign_registration_fixture": CAMPAIGN_SCHEMA.read_bytes(),
        "known_truth_evaluation_fixture": KNOWN_TRUTH_SCHEMA.read_bytes(),
        "market_atlas_fixture": MARKET_SCHEMA.read_bytes(),
        "protocol_known_truth_evaluation_fixture": PROTOCOL_TRUTH_SCHEMA.read_bytes(),
        "research_proposal_fixture": RESEARCH_SCHEMA.read_bytes(),
    }


def _build_packet():
    return build_fixture_research_packet(
        REGISTRATION.read_bytes(),
        _schemas(),
        PUMP_FIXTURE.read_bytes(),
        DLMM_FIXTURE.read_bytes(),
    )


def _validate_packet(packet) -> None:
    packet.validate(_schemas(), PUMP_FIXTURE.read_bytes(), DLMM_FIXTURE.read_bytes())


def test_registered_schema_bytes_are_exact_and_packet_is_deterministic() -> None:
    expected_market = canonical_json_bytes(schema_descriptor(ATLAS_SNAPSHOT_SCHEMA), newline=True)
    assert MARKET_SCHEMA.read_bytes() == expected_market
    assert RESEARCH_SCHEMA.read_bytes() == research_proposal_schema_bytes()
    first = _build_packet()
    second = _build_packet()
    assert first == second
    assert first.authority == FIXTURE_PACKET_AUTHORITY
    assert first.status == "protocol_draft"
    assert first.query_count == 0
    assert not first.executable
    assert len(first.known_truth_evaluation.passed_case_ids) == 8
    assert len(first.protocol_known_truth_evaluation.passed_case_ids) == 7
    assert first.proposal.artifact_descriptors[0].provenance_digest == (
        first.known_truth_evaluation.evaluation_digest
    )
    packet = first.as_dict(_schemas(), PUMP_FIXTURE.read_bytes(), DLMM_FIXTURE.read_bytes())
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
    packet = _build_packet()
    with pytest.raises(ManifestError, match="identity"):
        _validate_packet(replace(packet, packet_digest="sha256:" + "0" * 64))
    with pytest.raises(ManifestError, match="widened"):
        _validate_packet(replace(packet, authority="may_query_and_trade"))
    changed_evaluation = replace(
        packet.known_truth_evaluation, evaluation_digest="sha256:" + "1" * 64
    )
    with pytest.raises(ManifestError, match="known-truth closure"):
        _validate_packet(replace(packet, known_truth_evaluation=changed_evaluation))


def test_packet_refuses_protocol_fixture_or_evaluation_substitution() -> None:
    packet = _build_packet()
    changed_protocol = replace(
        packet.protocol_known_truth_evaluation,
        evaluation_digest="sha256:" + "2" * 64,
    )
    with pytest.raises(ManifestError, match="protocol known-truth closure"):
        _validate_packet(
            replace(packet, protocol_known_truth_evaluation=changed_protocol)
        )

    changed_pump = PUMP_FIXTURE.read_bytes().replace(
        b'"raw_quote_atoms": "501"', b'"raw_quote_atoms": "500"', 1
    )
    with pytest.raises(ManifestError, match="frozen N01 digest"):
        packet.validate(_schemas(), changed_pump, DLMM_FIXTURE.read_bytes())
