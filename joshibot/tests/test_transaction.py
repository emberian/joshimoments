import base64
import struct

import pytest
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from shitcoims_sentinel.domain import TokenHolding
from shitcoims_sentinel.transaction import (
    ASSOCIATED_TOKEN_PROGRAM,
    COMPUTE_BUDGET_PROGRAM,
    JUPITER_V6_PROGRAM,
    TransactionRejected,
    sign_validated_transaction,
    validate_jupiter_exit_transaction,
    validate_simulated_exit,
)


class NoLookupRpc:
    async def account_data(self, _address: str) -> bytes:
        raise AssertionError("test transaction has no lookups")


def encoded_transaction(payer: Keypair, instructions: list[Instruction]) -> str:
    message = MessageV0.try_compile(payer.pubkey(), instructions, [], Hash.new_unique())
    unsigned = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(unsigned)).decode("ascii")


@pytest.mark.asyncio
async def test_validates_and_signs_narrow_jupiter_transaction() -> None:
    shitcoims = Keypair()
    compute_limit = Instruction(
        Pubkey.from_string(COMPUTE_BUDGET_PROGRAM), bytes([2]) + struct.pack("<I", 400_000), []
    )
    compute_price = Instruction(
        Pubkey.from_string(COMPUTE_BUDGET_PROGRAM), bytes([3]) + struct.pack("<Q", 10_000), []
    )
    swap = Instruction(Pubkey.from_string(JUPITER_V6_PROGRAM), b"swap", [])
    validated = await validate_jupiter_exit_transaction(
        encoded=encoded_transaction(shitcoims, [compute_limit, compute_price, swap]),
        shitcoims_pubkey=shitcoims.pubkey(),
        rpc=NoLookupRpc(),
        max_priority_fee_lamports=5_000_000,
    )
    assert validated.priority_fee_lamports == 4_000
    encoded = sign_validated_transaction(validated, shitcoims)
    signed = VersionedTransaction.from_bytes(base64.b64decode(encoded))
    assert signed.verify_with_results() == [True]


@pytest.mark.asyncio
async def test_rejects_unknown_top_level_program() -> None:
    shitcoims = Keypair()
    instruction = Instruction(Pubkey.default(), b"drain", [])
    with pytest.raises(TransactionRejected, match="unexpected top-level program"):
        await validate_jupiter_exit_transaction(
            encoded=encoded_transaction(shitcoims, [instruction]),
            shitcoims_pubkey=shitcoims.pubkey(),
            rpc=NoLookupRpc(),
            max_priority_fee_lamports=5_000_000,
        )


@pytest.mark.asyncio
async def test_rejects_priority_fee_above_cap() -> None:
    shitcoims = Keypair()
    compute_limit = Instruction(
        Pubkey.from_string(COMPUTE_BUDGET_PROGRAM), bytes([2]) + struct.pack("<I", 1_000_000), []
    )
    compute_price = Instruction(
        Pubkey.from_string(COMPUTE_BUDGET_PROGRAM), bytes([3]) + struct.pack("<Q", 9_000_000), []
    )
    swap = Instruction(Pubkey.from_string(JUPITER_V6_PROGRAM), b"swap", [])
    with pytest.raises(TransactionRejected, match="exceeds configured cap"):
        await validate_jupiter_exit_transaction(
            encoded=encoded_transaction(shitcoims, [compute_limit, compute_price, swap]),
            shitcoims_pubkey=shitcoims.pubkey(),
            rpc=NoLookupRpc(),
            max_priority_fee_lamports=5_000_000,
        )


@pytest.mark.asyncio
async def test_rejects_close_account_to_attacker() -> None:
    shitcoims = Keypair()
    token_account = Pubkey.new_unique()
    attacker = Pubkey.new_unique()
    close = Instruction(
        Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
        bytes([9]),
        [
            AccountMeta(token_account, False, True),
            AccountMeta(attacker, False, True),
            AccountMeta(shitcoims.pubkey(), True, False),
        ],
    )
    swap = Instruction(Pubkey.from_string(JUPITER_V6_PROGRAM), b"swap", [])
    with pytest.raises(TransactionRejected, match="return funds to shitcoims"):
        await validate_jupiter_exit_transaction(
            encoded=encoded_transaction(shitcoims, [swap, close]),
            shitcoims_pubkey=shitcoims.pubkey(),
            rpc=NoLookupRpc(),
            max_priority_fee_lamports=5_000_000,
        )


@pytest.mark.asyncio
async def test_rejects_associated_token_account_for_attacker() -> None:
    shitcoims = Keypair()
    attacker = Pubkey.new_unique()
    ata = Instruction(
        Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM),
        b"\x01",
        [
            AccountMeta(shitcoims.pubkey(), True, True),
            AccountMeta(Pubkey.new_unique(), False, True),
            AccountMeta(attacker, False, False),
            AccountMeta(Pubkey.new_unique(), False, False),
        ],
    )
    swap = Instruction(Pubkey.from_string(JUPITER_V6_PROGRAM), b"swap", [])
    with pytest.raises(TransactionRejected, match="created for shitcoims"):
        await validate_jupiter_exit_transaction(
            encoded=encoded_transaction(shitcoims, [ata, swap]),
            shitcoims_pubkey=shitcoims.pubkey(),
            rpc=NoLookupRpc(),
            max_priority_fee_lamports=5_000_000,
        )


def simulated_token_account(amount: int) -> dict:
    raw = bytearray(165)
    struct.pack_into("<Q", raw, 64, amount)
    return {"lamports": 2_039_280, "data": [base64.b64encode(raw).decode(), "base64"]}


def test_simulation_proves_full_target_exit_and_preserves_other_tokens() -> None:
    holdings = [
        TokenHolding("target", 100, 0, ("target-account",), ("program",)),
        TokenHolding("other", 200, 0, ("other-account",), ("program",)),
    ]
    validate_simulated_exit(
        simulation={
            "accounts": [
                {"lamports": 1_090_000_000},
                simulated_token_account(0),
                simulated_token_account(200),
            ]
        },
        holdings=holdings,
        target_mint="target",
        pre_sol_lamports=1_000_000_000,
        minimum_output_lamports=100_000_000,
        max_sol_cost_lamports=20_000_000,
    )


def test_simulation_rejects_non_target_token_change() -> None:
    holdings = [
        TokenHolding("target", 100, 0, ("target-account",), ("program",)),
        TokenHolding("other", 200, 0, ("other-account",), ("program",)),
    ]
    with pytest.raises(TransactionRejected, match="non-target"):
        validate_simulated_exit(
            simulation={
                "accounts": [
                    {"lamports": 1_090_000_000},
                    simulated_token_account(0),
                    simulated_token_account(199),
                ]
            },
            holdings=holdings,
            target_mint="target",
            pre_sol_lamports=1_000_000_000,
            minimum_output_lamports=100_000_000,
            max_sol_cost_lamports=20_000_000,
        )


def test_simulation_accepts_scale_out_leftover() -> None:
    holdings = [TokenHolding("target", 100, 0, ("target-account",), ("program",))]
    validate_simulated_exit(
        simulation={
            "accounts": [
                {"lamports": 1_090_000_000},
                simulated_token_account(70),
            ]
        },
        holdings=holdings,
        target_mint="target",
        pre_sol_lamports=1_000_000_000,
        minimum_output_lamports=100_000_000,
        max_sol_cost_lamports=20_000_000,
        expected_remaining=70,
    )


def test_simulation_rejects_wrong_scale_out_leftover() -> None:
    holdings = [TokenHolding("target", 100, 0, ("target-account",), ("program",))]
    with pytest.raises(TransactionRejected, match="remaining"):
        validate_simulated_exit(
            simulation={
                "accounts": [
                    {"lamports": 1_090_000_000},
                    simulated_token_account(0),
                ]
            },
            holdings=holdings,
            target_mint="target",
            pre_sol_lamports=1_000_000_000,
            minimum_output_lamports=100_000_000,
            max_sol_cost_lamports=20_000_000,
            expected_remaining=70,
        )


def test_simulation_rejects_output_not_returned_to_shitcoims_sol() -> None:
    holdings = [TokenHolding("target", 100, 0, ("target-account",), ("program",))]
    with pytest.raises(TransactionRejected, match="minimum output"):
        validate_simulated_exit(
            simulation={
                "accounts": [
                    {"lamports": 1_050_000_000},
                    simulated_token_account(0),
                ]
            },
            holdings=holdings,
            target_mint="target",
            pre_sol_lamports=1_000_000_000,
            minimum_output_lamports=100_000_000,
            max_sol_cost_lamports=20_000_000,
        )
