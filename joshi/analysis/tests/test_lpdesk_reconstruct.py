"""The ledger and the panel: exact Decimal arithmetic on synthetic retained bytes."""

import base64
from decimal import Decimal

from joshi_analysis.lpdesk.events import EVENT_FIELDS, anchor_event_discriminator
from joshi_analysis.lpdesk.reconstruct import PoolIdentity, build_ledger, reconstruct

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(raw: bytes) -> str:
    value = int.from_bytes(raw, "big")
    out = []
    while value:
        value, rem = divmod(value, 58)
        out.append(_ALPHABET[rem])
    for byte in raw:
        if byte != 0:
            break
        out.append(_ALPHABET[0])
    return "".join(reversed(out))


def _b58decode(text: str) -> bytes:
    value = 0
    for char in text:
        value = value * 58 + _ALPHABET.index(char)
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip(_ALPHABET[0]))
    return (b"\x00" * pad + raw).rjust(32, b"\x00")


POOL = _b58encode(bytes([9]) + bytes(31))
WALLET = _b58encode(bytes([1]) + bytes(31))
POS = _b58encode(bytes([2]) + bytes(31))
RESERVE_X = _b58encode(bytes([3]) + bytes(31))
RESERVE_Y = _b58encode(bytes([4]) + bytes(31))

# bin_step 0 would be degenerate; use 10 so bin 0 prices X at exactly 1000 quote (9 vs 6
# decimals). At bin 0 the atom ratio is exactly 1, so values are exact by construction.
IDENTITY = PoolIdentity(
    address=POOL,
    bin_step=10,
    token_x_mint="X",
    token_y_mint="Y",
    reserve_x=RESERVE_X,
    reserve_y=RESERVE_Y,
    x_decimals=9,
    y_decimals=6,
    quote_is_y=True,
)


def _encode_event(name: str, values: dict) -> str:
    sizes = {"p": 32, "i4": 4, "u8b": 8, "u16b": 16, "i2": 2, "b": 1}
    out = bytearray(anchor_event_discriminator(name))
    for field_name, kind in EVENT_FIELDS[name]:
        value = values[field_name]
        if kind == "p":
            out += _b58decode(value)
        elif kind == "b":
            out += bytes([1 if value else 0])
        elif kind in ("i4", "i2"):
            out += value.to_bytes(sizes[kind], "little", signed=True)
        else:
            out += value.to_bytes(sizes[kind], "little")
    return "Program data: " + base64.b64encode(bytes(out)).decode()


def _transaction(
    signature: str,
    slot: int,
    block_time: int,
    events: list[str],
    reserve_x_delta: int = 0,
    reserve_y_delta: int = 0,
    fee_lamports: int = 5_000,
    err=None,
):
    base_x = 10**12
    base_y = 10**10
    return {
        "slot": slot,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET}, {"pubkey": POS},
                    {"pubkey": RESERVE_X}, {"pubkey": RESERVE_Y},
                ]
            },
        },
        "meta": {
            "err": err,
            "fee": fee_lamports,
            "preBalances": [10**9, 0, 0, 0],
            "postBalances": [10**9 - fee_lamports, 0, 0, 0],
            "preTokenBalances": [
                {"accountIndex": 2, "uiTokenAmount": {"amount": str(base_x)}},
                {"accountIndex": 3, "uiTokenAmount": {"amount": str(base_y)}},
            ],
            "postTokenBalances": [
                {"accountIndex": 2, "uiTokenAmount": {"amount": str(base_x + reserve_x_delta)}},
                {"accountIndex": 3, "uiTokenAmount": {"amount": str(base_y + reserve_y_delta)}},
            ],
            "logMessages": events,
        },
    }


def test_a_reconciled_deposit_claim_withdraw_cycle_is_exact():
    # Deposit 1 SOL + 1000 USDC at bin 0 (price exactly 1000): 2000 USDC in.
    deposit = _transaction(
        "sig-deposit", 100, 1_000_000,
        [
            _encode_event("PositionCreate", {"lb_pair": POOL, "position": POS, "owner": WALLET}),
            _encode_event("AddLiquidity", {
                "lb_pair": POOL, "from": WALLET, "position": POS,
                "amount_x": 10**9, "amount_y": 10**9, "active_bin_id": 0,
            }),
        ],
        reserve_x_delta=10**9, reserve_y_delta=10**9,
    )
    # Claim 2 USDC of fees at the same price.
    claim = _transaction(
        "sig-claim", 200, 1_043_200,
        [_encode_event("ClaimFee", {
            "lb_pair": POOL, "position": POS, "owner": WALLET,
            "fee_x": 0, "fee_y": 2_000_000,
        })],
        reserve_y_delta=-2_000_000,
    )
    # Withdraw everything as 2 SOL + 0 USDC (price moved down through the band and the
    # inventory converted), still valued at bin 0 for exactness: 2000 USDC out.
    withdraw = _transaction(
        "sig-withdraw", 300, 1_086_400,
        [
            _encode_event("RemoveLiquidity", {
                "lb_pair": POOL, "from": WALLET, "position": POS,
                "amount_x": 2 * 10**9, "amount_y": 0, "active_bin_id": 0,
            }),
            _encode_event("PositionClose", {"position": POS, "owner": WALLET}),
        ],
        reserve_x_delta=-2 * 10**9,
    )
    ledger = build_ledger([deposit, claim, withdraw], IDENTITY, WALLET)
    assert [e.kind for e in ledger] == ["create", "deposit", "claim", "withdraw", "close"]
    assert all(e.reconciled for e in ledger)

    panel = reconstruct(
        ledger, IDENTITY,
        now_unix=1_086_400,
        open_position_values={},
        pending_fees=(0, 0, 1_086_400),
        sol_is_base=True,
    )
    assert panel.anchored_positions == 1
    assert panel.unanchored_positions == 0
    assert panel.deposits_quote == Decimal(2000)
    assert panel.fees_claimed_quote == Decimal(2)
    assert panel.withdrawals_quote == Decimal(2000)
    # Exit legs (2 SOL, 0 USDC) at bin 0 equal entry legs (1 SOL, 1000 USDC) in value.
    assert panel.realized_shift_quote == Decimal(0)
    assert panel.elapsed_days == Decimal(1)
    assert panel.time_weighted_deployed_quote == Decimal(2000)
    assert panel.gross_fee_rate_per_day == Decimal(2) / Decimal(2000)
    # Costs: 3 transactions x 5000 lamports at 1000 quote/SOL, each converted at its own
    # transaction's active bin.
    assert panel.tx_fees_quote == Decimal("0.015")
    assert panel.withdraw_transactions == 1
    assert panel.unreconciled_transactions == 0


def test_an_unreconciled_transaction_is_flagged_never_averaged():
    deposit = _transaction(
        "sig-bad", 100, 1_000_000,
        [_encode_event("AddLiquidity", {
            "lb_pair": POOL, "from": WALLET, "position": POS,
            "amount_x": 10**9, "amount_y": 0, "active_bin_id": 0,
        })],
        reserve_x_delta=10**9 - 1,  # one atom short
    )
    ledger = build_ledger([deposit], IDENTITY, WALLET)
    assert len(ledger) == 1
    assert not ledger[0].reconciled
    assert "disagree" in ledger[0].note
    panel = reconstruct(
        ledger, IDENTITY, now_unix=1_086_400,
        open_position_values={}, pending_fees=None, sol_is_base=True,
    )
    assert panel.unreconciled_transactions == 1
    # No create in the window: the position is unanchored and outside every rate.
    assert panel.unanchored_positions == 1
    assert panel.deposits_quote == Decimal(0)
    assert panel.unanchored_in_quote == Decimal(1000)


def test_a_rebalance_event_realizes_the_inventory_shift_and_counts_costs():
    deposit = _transaction(
        "sig-open", 100, 1_000_000,
        [
            _encode_event("PositionCreate", {"lb_pair": POOL, "position": POS, "owner": WALLET}),
            _encode_event("AddLiquidity", {
                "lb_pair": POOL, "from": WALLET, "position": POS,
                "amount_x": 10**9, "amount_y": 10**9, "active_bin_id": 0,
            }),
        ],
        reserve_x_delta=10**9, reserve_y_delta=10**9,
    )
    # Price fell ~10 bins; the whole band converted to SOL. She rebalances: withdraws
    # 2 SOL + 0 USDC, redeposits the same, claims 1 USDC of fees, at bin -10.
    rebalance = _transaction(
        "sig-rebalance", 200, 1_086_400,
        [_encode_event("Rebalancing", {
            "lb_pair": POOL, "position": POS, "owner": WALLET, "active_bin_id": -10,
            "x_withdrawn_amount": 2 * 10**9, "x_added_amount": 2 * 10**9,
            "y_withdrawn_amount": 0, "y_added_amount": 0,
            "x_fee_amount": 0, "y_fee_amount": 1_000_000,
            "old_min_id": -5, "old_max_id": 5, "new_min_id": -15, "new_max_id": -5,
            "reward_0": 0, "reward_1": 0,
        })],
        reserve_y_delta=-1_000_000,
    )
    ledger = build_ledger([deposit, rebalance], IDENTITY, WALLET)
    assert [e.kind for e in ledger] == ["create", "deposit", "rebalance"]
    assert all(e.reconciled for e in ledger)
    panel = reconstruct(
        ledger, IDENTITY, now_unix=1_086_400,
        open_position_values={POS: (2 * 10**9, 0, 1_086_400)},
        pending_fees=(0, 0, 1_086_400),
        sol_is_base=True,
    )
    price_down = IDENTITY.quote_per_base_display(-10)
    # Open shift: exits (2 SOL) plus NAV (2 SOL) versus all deposited legs
    # (1+2 SOL, 1000 USDC), every term at bin -10: p - 1000.
    expected = 4 * price_down - (3 * price_down + 1000)
    assert abs(panel.open_shift_quote - expected) < Decimal("1e-18")
    assert panel.realized_shift_quote == Decimal(0)
    assert panel.fees_claimed_quote == Decimal(1)
    assert panel.rebalance_transactions == 1


def test_a_failed_transaction_contributes_its_fee_and_nothing_else():
    deposit = _transaction(
        "sig-open", 100, 1_000_000,
        [_encode_event("AddLiquidity", {
            "lb_pair": POOL, "from": WALLET, "position": POS,
            "amount_x": 0, "amount_y": 10**9, "active_bin_id": 0,
        })],
        reserve_y_delta=10**9,
    )
    failed = _transaction("sig-failed", 200, 1_043_200, [], fee_lamports=7_000,
                          err={"InstructionError": [2, "custom"]})
    ledger = build_ledger([deposit, failed], IDENTITY, WALLET)
    kinds = {e.kind for e in ledger}
    assert kinds == {"deposit", "failed"}
    panel = reconstruct(
        ledger, IDENTITY, now_unix=1_086_400,
        open_position_values={}, pending_fees=None, sol_is_base=True,
    )
    # 5000 + 7000 lamports at 1000 quote per SOL.
    assert panel.tx_fees_quote == Decimal("0.012")


def test_events_for_a_different_pool_are_ignored():
    other_pool = _b58encode(bytes([8]) + bytes(31))
    stray = _transaction(
        "sig-stray", 100, 1_000_000,
        [_encode_event("AddLiquidity", {
            "lb_pair": other_pool, "from": WALLET, "position": POS,
            "amount_x": 10**9, "amount_y": 0, "active_bin_id": 0,
        })],
    )
    assert build_ledger([stray], IDENTITY, WALLET) == []
