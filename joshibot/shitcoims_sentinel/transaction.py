from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import Any

from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from .clients import SolanaRpc
from .domain import TOKEN_2022_PROGRAM, TOKEN_PROGRAM, TokenHolding

COMPUTE_BUDGET_PROGRAM = "ComputeBudget111111111111111111111111111111"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
JUPITER_V6_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
ALLOWED_TOP_LEVEL_PROGRAMS = {
    COMPUTE_BUDGET_PROGRAM,
    ASSOCIATED_TOKEN_PROGRAM,
    JUPITER_V6_PROGRAM,
    MEMO_PROGRAM,
    TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
}


class TransactionRejected(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedTransaction:
    transaction: VersionedTransaction
    top_level_programs: tuple[str, ...]
    priority_fee_lamports: int


def _decode_transaction(encoded: str) -> VersionedTransaction:
    try:
        raw = base64.b64decode(encoded, validate=True)
        tx = VersionedTransaction.from_bytes(raw)
        tx.sanitize()
        return tx
    except Exception as exc:
        raise TransactionRejected("Jupiter transaction is not valid canonical base64/v0 data") from exc


def _lookup_addresses(data: bytes) -> list[Pubkey]:
    # Solana Address Lookup Table account data has a fixed 56-byte metadata header.
    if len(data) < 56 or (len(data) - 56) % 32 != 0:
        raise TransactionRejected("address lookup table account has invalid length")
    return [Pubkey.from_bytes(data[offset : offset + 32]) for offset in range(56, len(data), 32)]


async def _resolve_keys(message: MessageV0, rpc: SolanaRpc) -> list[Pubkey]:
    writable: list[Pubkey] = []
    readonly: list[Pubkey] = []
    for lookup in message.address_table_lookups:
        addresses = _lookup_addresses(await rpc.account_data(str(lookup.account_key)))
        try:
            writable.extend(addresses[index] for index in lookup.writable_indexes)
            readonly.extend(addresses[index] for index in lookup.readonly_indexes)
        except IndexError as exc:
            raise TransactionRejected("address lookup table index is out of bounds") from exc
    return [*message.account_keys, *writable, *readonly]


def _instruction_keys(instruction: Any, keys: list[Pubkey]) -> list[Pubkey]:
    try:
        return [keys[index] for index in instruction.accounts]
    except IndexError as exc:
        raise TransactionRejected("instruction account index is out of bounds") from exc


def _validate_token_instruction(
    data: bytes, instruction_keys: list[Pubkey], shitcoims_pubkey: Pubkey
) -> None:
    # A token->SOL Jupiter exit may close/sync a temporary wSOL account. Direct
    # top-level transfers, approvals, authority changes, minting, and burns are rejected.
    if not data or data[0] not in {9, 17}:  # CloseAccount, SyncNative
        opcode = data[0] if data else None
        raise TransactionRejected(f"unexpected top-level SPL Token opcode {opcode}")
    if data[0] == 9:
        if len(instruction_keys) < 3:
            raise TransactionRejected("SPL Token CloseAccount omitted required accounts")
        destination = instruction_keys[1]
        authority = instruction_keys[2]
        if destination != shitcoims_pubkey or authority != shitcoims_pubkey:
            raise TransactionRejected(
                "SPL Token CloseAccount must return funds to shitcoims under shitcoims authority"
            )


def _validate_associated_token_instruction(
    data: bytes, instruction_keys: list[Pubkey], shitcoims_pubkey: Pubkey
) -> None:
    # Create and CreateIdempotent only. Payer and ATA owner must both be shitcoims.
    if data not in {b"", b"\x01"} or len(instruction_keys) < 4:
        raise TransactionRejected("unexpected associated-token instruction")
    if instruction_keys[0] != shitcoims_pubkey or instruction_keys[2] != shitcoims_pubkey:
        raise TransactionRejected("associated-token account must be created for shitcoims")


def _compute_budget_fee(instructions: list[tuple[str, bytes]], max_lamports: int) -> int:
    unit_limit = 200_000
    unit_price = 0
    for program, data in instructions:
        if program != COMPUTE_BUDGET_PROGRAM or not data:
            continue
        if data[0] == 2 and len(data) == 5:
            unit_limit = struct.unpack_from("<I", data, 1)[0]
        elif data[0] == 3 and len(data) == 9:
            unit_price = struct.unpack_from("<Q", data, 1)[0]
    fee = (unit_limit * unit_price + 999_999) // 1_000_000
    if fee > max_lamports:
        raise TransactionRejected(f"priority fee {fee} exceeds configured cap {max_lamports}")
    return fee


async def validate_jupiter_exit_transaction(
    *,
    encoded: str,
    shitcoims_pubkey: Pubkey,
    rpc: SolanaRpc,
    max_priority_fee_lamports: int,
) -> ValidatedTransaction:
    tx = _decode_transaction(encoded)
    if not isinstance(tx.message, MessageV0):
        raise TransactionRejected("legacy transactions are not accepted")
    message = tx.message
    if message.header.num_required_signatures != 1:
        raise TransactionRejected("exit transaction must require exactly the shitcoims signer")
    if not message.account_keys or message.account_keys[0] != shitcoims_pubkey:
        raise TransactionRejected("shitcoims must be the sole signer and fee payer")
    if len(tx.signatures) != 1 or tx.signatures[0] != Signature.default():
        raise TransactionRejected("Jupiter exit must arrive unsigned")

    keys = await _resolve_keys(message, rpc)
    decoded_instructions: list[tuple[str, bytes]] = []
    saw_jupiter = False
    for instruction in message.instructions:
        try:
            program = str(keys[instruction.program_id_index])
        except IndexError as exc:
            raise TransactionRejected("instruction program index is out of bounds") from exc
        if program not in ALLOWED_TOP_LEVEL_PROGRAMS:
            raise TransactionRejected(f"unexpected top-level program {program}")
        data = bytes(instruction.data)
        decoded_instructions.append((program, data))
        instruction_keys = _instruction_keys(instruction, keys)
        if program in {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
            _validate_token_instruction(data, instruction_keys, shitcoims_pubkey)
        if program == ASSOCIATED_TOKEN_PROGRAM:
            _validate_associated_token_instruction(data, instruction_keys, shitcoims_pubkey)
        if program == JUPITER_V6_PROGRAM:
            saw_jupiter = True
    if not saw_jupiter:
        raise TransactionRejected("transaction contains no Jupiter swap instruction")
    fee = _compute_budget_fee(decoded_instructions, max_priority_fee_lamports)
    return ValidatedTransaction(tx, tuple(program for program, _ in decoded_instructions), fee)


def sign_validated_transaction(validated: ValidatedTransaction, keypair: Keypair) -> str:
    message_bytes = to_bytes_versioned(validated.transaction.message)
    signature = keypair.sign_message(message_bytes)
    signed = VersionedTransaction.populate(validated.transaction.message, [signature])
    if signed.verify_with_results() != [True]:
        raise TransactionRejected("locally signed transaction did not verify")
    return base64.b64encode(bytes(signed)).decode("ascii")


def _simulated_token_amount(account: object) -> int:
    if account is None:
        return 0
    if not isinstance(account, dict):
        raise TransactionRejected("simulated token account was malformed")
    data = account.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        raise TransactionRejected("simulated token account data was malformed")
    try:
        raw = base64.b64decode(data[0], validate=True)
    except ValueError as exc:
        raise TransactionRejected("simulated token account data was not base64") from exc
    if len(raw) < 72:
        raise TransactionRejected("simulated token account data was too short")
    return int(struct.unpack_from("<Q", raw, 64)[0])


def validate_simulated_exit(
    *,
    simulation: dict,
    holdings: list[TokenHolding],
    target_mint: str,
    pre_sol_lamports: int,
    minimum_output_lamports: int,
    max_sol_cost_lamports: int,
    expected_remaining: int = 0,
) -> None:
    """Bind a signed transaction to the intended remaining target balance.

    Full exits pass ``expected_remaining=0``. Scale-outs pass the leftover
    raw amount. Other owned tokens must be untouched.
    """
    accounts = simulation.get("accounts")
    expected_accounts = 1 + sum(len(holding.token_accounts) for holding in holdings)
    if not isinstance(accounts, list) or len(accounts) != expected_accounts:
        raise TransactionRejected("simulation account set did not match shitcoims holdings")
    wallet = accounts[0]
    if not isinstance(wallet, dict) or not isinstance(wallet.get("lamports"), int):
        raise TransactionRejected("simulation omitted the shitcoims SOL account")
    minimum_wallet_lamports = (
        pre_sol_lamports + minimum_output_lamports - max_sol_cost_lamports
    )
    if int(wallet["lamports"]) < minimum_wallet_lamports:
        raise TransactionRejected(
            "simulated transaction does not return minimum output to the shitcoims SOL account"
        )

    offset = 1
    saw_target = False
    for holding in holdings:
        count = len(holding.token_accounts)
        post_amount = sum(
            _simulated_token_amount(account) for account in accounts[offset : offset + count]
        )
        offset += count
        if holding.mint == target_mint:
            saw_target = True
            if expected_remaining < 0:
                raise TransactionRejected("simulated exit remaining amount is negative")
            if post_amount != expected_remaining:
                if expected_remaining == 0:
                    raise TransactionRejected("simulated exit did not sell the complete target balance")
                raise TransactionRejected(
                    "simulated scale-out did not leave the intended remaining balance"
                )
        elif post_amount != holding.amount:
            raise TransactionRejected("simulated exit modified a non-target shitcoims token")
    if not saw_target:
        raise TransactionRejected("simulated exit target is not a current shitcoims holding")
