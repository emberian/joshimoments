"""The Python decoders must reproduce what meteora.rs pinned, byte for byte."""

import base64
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from joshi_analysis.lpdesk.layouts import (
    METEORA_DLMM_PROGRAM_ID,
    LayoutError,
    PositionV2,
    anchor_account_discriminator,
    bin_price_ratio,
    decode_bin_array_liquidity,
    decode_lb_pair,
    decode_oracle,
    decode_position_v2,
    position_composition,
)

REPO = Path(__file__).resolve().parents[2]
SOURCES_FIXTURES = REPO / "crates" / "joshi-sources" / "fixtures"
PROTOCOL_VECTORS = REPO / "fixtures" / "protocol" / "dlmm.json"

PAIR = "HE9UXD4abY8dG1QEmyoZkSETZVScef3t2yZqhbWCT9aJ"
POSITION = "CMgNgzL5i5ECiuyyFg8apB52KcM1yinNvCh2bs6TbuE9"
CREATOR = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"


def _value(path: Path) -> dict:
    return json.loads(path.read_text())["result"]["value"]


def test_discriminators_are_recomputed_not_transcribed():
    assert anchor_account_discriminator("LbPair") == bytes(
        [0x21, 0x0B, 0x31, 0x62, 0xB5, 0x65, 0xB1, 0x0D]
    )
    assert anchor_account_discriminator("PositionV2") == bytes(
        [0x75, 0xB0, 0xD4, 0xC7, 0xF5, 0xB4, 0x85, 0xB6]
    )


def test_the_retained_mainnet_pair_decodes_to_what_meteora_rs_pinned():
    pair = decode_lb_pair(_value(SOURCES_FIXTURES / "meteora_dlmm_lbpair_mainnet.json"), PAIR)
    assert pair.bin_step == 125
    assert pair.base_factor == 40_000
    assert pair.base_fee_power_factor == 0
    assert pair.protocol_share == 1_000
    assert pair.variable_fee_control == 7_500
    assert pair.max_volatility_accumulator == 150_000
    assert pair.active_id == -126
    assert pair.status == 0
    assert pair.token_x_mint == "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"
    assert pair.token_y_mint == "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
    assert pair.reserve_x == "ELy19v2TigCQmgyj8MEZYzjpM9vLQ6GGLg3x6MLnEmZB"
    assert pair.reserve_y == "3dzF5omWG3bpAfGnZfiixh8tSAjmMp9KNtwfMdQNAPUZ"
    assert pair.protocol_fee_x_atoms == 0
    assert pair.protocol_fee_y_atoms == 10_786_133_760
    assert pair.volatility_last_update_unix_s == 1_786_849_045
    assert pair.base_fee_rate_per_1e9() == 50_000_000
    assert pair.max_variable_fee_rate_per_1e9() == 26_367_188


def test_the_active_bin_price_reproduces_the_externally_quoted_pool_price():
    price = bin_price_ratio(125, -126)
    assert abs(price - Decimal("0.209038")) < Decimal("0.000001")


def test_the_retained_mainnet_position_decodes_with_the_extension_reconciled():
    position = decode_position_v2(
        _value(SOURCES_FIXTURES / "meteora_dlmm_position_mainnet.json"), POSITION
    )
    assert position.lb_pair == PAIR
    assert position.owner == CREATOR
    assert position.lower_bin_id == -157
    assert position.upper_bin_id == -87
    assert position.bin_count() == 71
    assert position.extension_records == 1
    assert position.total_claimed_fee_x_atoms == 0
    assert position.total_claimed_fee_y_atoms == 0
    assert position.pending_fee_x_atoms_fixed_slots == 0
    assert position.pending_fee_y_atoms_fixed_slots == 0
    assert all(share > 0 for share in position.liquidity_shares)


def test_a_wrong_owner_and_a_flipped_discriminator_refuse():
    value = _value(SOURCES_FIXTURES / "meteora_dlmm_lbpair_mainnet.json")
    wrong_owner = dict(value, owner="pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")
    with pytest.raises(LayoutError, match="owned by"):
        decode_lb_pair(wrong_owner, PAIR)
    raw = bytearray(base64.b64decode(value["data"][0]))
    raw[0] ^= 0x01
    flipped = dict(value, data=[base64.b64encode(bytes(raw)).decode(), "base64"])
    with pytest.raises(LayoutError, match="discriminator"):
        decode_lb_pair(flipped, PAIR)


def _oracle_account(idx: int, length: int, observations: list[tuple[int, int, int]]) -> dict:
    body = bytearray()
    body += hashlib.sha256(b"account:Oracle").digest()[:8]
    body += idx.to_bytes(8, "little")
    body += (0).to_bytes(8, "little")
    body += length.to_bytes(8, "little")
    slots = {slot: obs for slot, obs in enumerate(observations)}
    for slot in range(length):
        cumulative, created, updated = slots.get(slot, (0, 0, 0))
        body += cumulative.to_bytes(16, "little", signed=True)
        body += created.to_bytes(8, "little", signed=True)
        body += updated.to_bytes(8, "little", signed=True)
    return {
        "data": [base64.b64encode(bytes(body)).decode(), "base64"],
        "owner": METEORA_DLMM_PROGRAM_ID,
    }


def test_the_oracle_ring_unrolls_oldest_first_and_skips_uninitialized_slots():
    # idx=1 is the most recent write; slot 2 is uninitialized; oldest is slot 2 -> 0 -> 1.
    account = _oracle_account(1, 3, [(100, 10, 20), (300, 10, 30), (0, 0, 0)])
    observations = decode_oracle(account, "OracleAddr")
    assert [o.last_updated_at for o in observations] == [20, 30]
    assert [o.cumulative_active_bin_id for o in observations] == [100, 300]


def test_an_oracle_whose_ring_does_not_unroll_monotonically_is_refused():
    account = _oracle_account(1, 2, [(100, 10, 50), (300, 10, 30)])
    with pytest.raises(LayoutError, match="nondecreasing"):
        decode_oracle(account, "OracleAddr")


def test_an_oracle_with_a_partial_record_allocation_is_refused():
    account = _oracle_account(0, 2, [(1, 1, 1), (2, 2, 2)])
    raw = bytearray(base64.b64decode(account["data"][0]))[:-1]
    broken = dict(account, data=[base64.b64encode(bytes(raw)).decode(), "base64"])
    with pytest.raises(LayoutError, match="record bytes"):
        decode_oracle(broken, "OracleAddr")


def _bin_array_account(index: int, bins: list[tuple[int, int, int]]) -> dict:
    body = bytearray()
    body += hashlib.sha256(b"account:BinArray").digest()[:8]
    body += index.to_bytes(8, "little", signed=True)
    body += bytes(8)  # version + padding
    body += bytes(32)  # lb_pair, irrelevant to the decode
    for slot in range(70):
        amount_x, amount_y, supply = bins[slot] if slot < len(bins) else (0, 0, 0)
        record = bytearray(144)
        record[0:8] = amount_x.to_bytes(8, "little")
        record[8:16] = amount_y.to_bytes(8, "little")
        record[32:48] = supply.to_bytes(16, "little")
        body += record
    return {
        "data": [base64.b64encode(bytes(body)).decode(), "base64"],
        "owner": METEORA_DLMM_PROGRAM_ID,
    }


def test_position_composition_reproduces_the_protocol_fixture_vector():
    """The repo's own DLMM position vector: quarter share of a 1000/2000 bin -> 250/500."""
    vector = json.loads(PROTOCOL_VECTORS.read_text())["position_vectors"][0]
    assert vector["id"] == "single_bin_quarter_share"
    bin_id = int(vector["bin_id"])
    array_index = bin_id // 70
    slot = bin_id - array_index * 70
    bins = [(0, 0, 0)] * 70
    bins[slot] = (
        int(vector["pool_x_atoms"]),
        int(vector["pool_y_atoms"]),
        int(vector["liquidity_supply"]),
    )
    array = decode_bin_array_liquidity(_bin_array_account(array_index, bins), "BinArrayAddr")
    shares = [0] * 70
    shares[0] = int(vector["position_share"])
    position = PositionV2(
        address="PosAddr",
        lb_pair="Pair",
        owner="Owner",
        lower_bin_id=bin_id,
        upper_bin_id=bin_id,
        last_updated_at=0,
        total_claimed_fee_x_atoms=0,
        total_claimed_fee_y_atoms=0,
        liquidity_shares=tuple(shares),
        pending_fee_x_atoms_fixed_slots=0,
        pending_fee_y_atoms_fixed_slots=0,
        extension_records=0,
    )
    x_atoms, y_atoms = position_composition(position, [array])
    assert x_atoms == int(vector["expected_position_x_atoms"])
    assert y_atoms == int(vector["expected_position_y_atoms"])


def test_a_position_bin_without_its_array_is_refused_not_skipped():
    position = PositionV2(
        address="PosAddr", lb_pair="Pair", owner="Owner",
        lower_bin_id=5, upper_bin_id=5, last_updated_at=0,
        total_claimed_fee_x_atoms=0, total_claimed_fee_y_atoms=0,
        liquidity_shares=tuple([7] + [0] * 69),
        pending_fee_x_atoms_fixed_slots=0, pending_fee_y_atoms_fixed_slots=0,
        extension_records=0,
    )
    with pytest.raises(LayoutError, match="not supplied"):
        position_composition(position, [])
