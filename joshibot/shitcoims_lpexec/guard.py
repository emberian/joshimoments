"""The refusal. Every transaction passes through here before a signature exists.

The builder (`sidecar.py`, Meteora's TypeScript SDK) is UNTRUSTED. It is a subprocess with
no key, and this module treats its output as hostile bytes: decode, resolve lookup tables,
walk every top-level instruction, and refuse on the first thing that is not explicitly
permitted. Nothing is permitted by default; a DLMM instruction Meteora ships next week is
refused because its discriminator is not in `allowlist.ALLOWED_DLMM`.

WHAT MAKES THE SWAP UNREACHABLE. Three independent layers would each have to fail:

  1. `sidecar.py` never calls a swap method -- weak, it is just code.
  2. `ALLOWED_DLMM` has no swap discriminator in it -- strong, it is data, and the
     discriminator is `sha256("global:swap")[:8]`, which the builder cannot influence.
  3. Even a permitted instruction is refused if its `lb_pair` account is not in the pool
     allowlist AND not in the set the PLAN said it would touch (`expected_pools`).

Layer 2 is the one that matters and it is eight bytes of comparison. `guard_refuses_swap`
in the tests builds a real swap instruction with real solders and asserts the refusal, so
the claim is tested rather than asserted.

THE OTHER PROGRAMS. A DLMM deposit unavoidably drags in compute-budget, ATA creation, and
sometimes wrapped-SOL handling. Each gets its own opcode restriction rather than a blanket
program allowlist, because "the SPL Token program is allowed" would permit `Transfer` and
that is a drain. The System program gets the narrowest rule in the file: a lamport transfer
is permitted only to our own wrapped-SOL ATA, an address this module derives itself rather
than accepting from the builder.

Modelled on `shitcoims_sentinel/transaction.py`, which validates Jupiter's output the same
way and for the same reason. Copied, not imported: that package guards a different wallet
under a different mandate, and its refactor must not be able to move this one's boundary.
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Final

from solders.instruction import CompiledInstruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from .allowlist import (
    ALLOWED_DLMM,
    ALLOWED_PROGRAMS,
    ASSOCIATED_TOKEN_PROGRAM,
    COMPUTE_BUDGET_PROGRAM,
    DLMM_PROGRAM,
    FORBIDDEN_DLMM,
    MEMO_PROGRAM,
    POOLS,
    SWAP_DISCRIMINATORS,
    SYSTEM_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    WSOL_MINT,
    IxSpec,
)

DEFAULT_COMPUTE_UNIT_LIMIT: Final[int] = 200_000

# `studies/RESULT_execution_landing.md` §8: bid `clamp(pool p75 of landed bids, 100_000,
# 3_000_000)` microlamports/CU, limit `ceil(simulated x 1.15)` with a 160,000 static
# fallback. The floor here is the study's floor; the mandate's "max(pool p75, 50k)" is the
# older Jupiter-cliff number and the study supersedes it upward.
LANDING_BID_FLOOR_MICRO_LAMPORTS: Final[int] = 100_000
LANDING_BID_CEILING_MICRO_LAMPORTS: Final[int] = 3_000_000
CU_LIMIT_SIMULATION_MULTIPLIER: Final[float] = 1.15
CU_LIMIT_STATIC_FALLBACK: Final[int] = 160_000

# SPL Token opcodes we tolerate. 9 = CloseAccount (reclaim wSOL rent), 17 = SyncNative
# (make a wrapped-SOL deposit visible). Transfer (3) and TransferChecked (12) are absent
# and that absence is the point.
TOKEN_CLOSE_ACCOUNT: Final[int] = 9
TOKEN_SYNC_NATIVE: Final[int] = 17
SYSTEM_TRANSFER: Final[int] = 2

_ATA_PROGRAM_KEY: Final[Pubkey] = Pubkey.from_string(ASSOCIATED_TOKEN_PROGRAM)


class TransactionRefused(RuntimeError):
    """The builder produced something we will not sign. Never caught to retry."""


@dataclass(frozen=True, slots=True)
class DecodedInstruction:
    index: int
    program: str
    name: str
    lb_pair: str | None
    position: str | None
    kind: str


@dataclass(frozen=True, slots=True)
class GuardedTransaction:
    """A transaction that has been read and may be signed. Nothing else may be."""

    transaction: VersionedTransaction
    instructions: tuple[DecodedInstruction, ...]
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    priority_fee_lamports: int
    pools_touched: frozenset[str] = field(default_factory=frozenset)
    positions_touched: frozenset[str] = field(default_factory=frozenset)

    @property
    def bid_below_landing_floor(self) -> bool:
        return self.compute_unit_price_micro_lamports < LANDING_BID_FLOOR_MICRO_LAMPORTS

    def summary(self) -> str:
        return ", ".join(f"{ix.name}" for ix in self.instructions)


def associated_token_address(owner: Pubkey, mint: Pubkey, *, token_program: str = TOKEN_PROGRAM) -> Pubkey:
    """Derive an ATA ourselves. Never accept one from the builder and compare it to itself."""
    address, _bump = Pubkey.find_program_address(
        [bytes(owner), bytes(Pubkey.from_string(token_program)), bytes(mint)],
        _ATA_PROGRAM_KEY,
    )
    return address


def decode_unsigned(encoded: str) -> VersionedTransaction:
    try:
        raw = base64.b64decode(encoded, validate=True)
        tx = VersionedTransaction.from_bytes(raw)
        tx.sanitize()
        return tx
    except Exception as exc:
        raise TransactionRefused("builder output is not canonical base64 v0 transaction data") from exc


def _resolve_keys(message: MessageV0, account_data: Callable[[str], bytes]) -> list[str]:
    """Static keys plus every address the lookup tables contribute, writable then readonly.

    A transaction can hide an instruction's real accounts behind an address lookup table. If
    we validated only the static keys we would be checking a transaction we had not read, so
    the tables are fetched and expanded before any account comparison happens.
    """
    keys = [str(key) for key in message.account_keys]
    writable: list[str] = []
    readonly: list[str] = []
    for lookup in message.address_table_lookups:
        addresses = _lookup_addresses(account_data(str(lookup.account_key)))
        for index in lookup.writable_indexes:
            if index >= len(addresses):
                raise TransactionRefused("lookup table index is out of range")
            writable.append(addresses[index])
        for index in lookup.readonly_indexes:
            if index >= len(addresses):
                raise TransactionRefused("lookup table index is out of range")
            readonly.append(addresses[index])
    return keys + writable + readonly


def _lookup_addresses(data: bytes) -> list[str]:
    if len(data) < 56 or (len(data) - 56) % 32 != 0:
        raise TransactionRefused("address lookup table account is malformed")
    return [str(Pubkey.from_bytes(data[offset : offset + 32])) for offset in range(56, len(data), 32)]


def _key(keys: list[str], index: int, *, what: str) -> str:
    if index >= len(keys):
        raise TransactionRefused(f"instruction references account {index} beyond the key set ({what})")
    return keys[index]


def _compute_budget(programs: Iterable[tuple[str, bytes]], max_lamports: int) -> tuple[int, int, int]:
    """Read the bid rather than assume it. Same wire format the sentinel parses."""
    unit_limit = DEFAULT_COMPUTE_UNIT_LIMIT
    unit_price = 0
    for program, data in programs:
        if program != COMPUTE_BUDGET_PROGRAM or not data:
            continue
        if data[0] == 2 and len(data) == 5:
            unit_limit = struct.unpack_from("<I", data, 1)[0]
        elif data[0] == 3 and len(data) == 9:
            unit_price = struct.unpack_from("<Q", data, 1)[0]
        elif data[0] in (0, 1):
            # RequestUnits (deprecated) / RequestHeapFrame. Neither is something our builder
            # emits, and a heap request is a CU-cost surprise, so refuse rather than ignore.
            raise TransactionRefused(f"unexpected compute budget opcode {data[0]}")
    fee = (unit_limit * unit_price + 999_999) // 1_000_000
    if fee > max_lamports:
        raise TransactionRefused(f"priority fee {fee} lamports exceeds the configured cap {max_lamports}")
    return fee, unit_limit, unit_price


def _check_dlmm(
    spec: IxSpec,
    ix: CompiledInstruction,
    keys: list[str],
    *,
    owner: str,
    expected_pools: frozenset[str],
    expected_positions: frozenset[str],
) -> tuple[str | None, str | None]:
    accounts = list(ix.accounts)

    lb_pair: str | None = None
    if spec.lb_pair_index is not None:
        if spec.lb_pair_index >= len(accounts):
            raise TransactionRefused(f"{spec.name} is missing its lb_pair account")
        lb_pair = _key(keys, accounts[spec.lb_pair_index], what=f"{spec.name}.lb_pair")
        if lb_pair not in POOLS:
            raise TransactionRefused(
                f"{spec.name} names pool {lb_pair}, which is not in the lpexec pool allowlist"
            )
        if expected_pools and lb_pair not in expected_pools:
            raise TransactionRefused(
                f"{spec.name} names allowlisted pool {lb_pair}, but the plan authorised only "
                f"{sorted(expected_pools)}"
            )

    position: str | None = None
    if spec.position_index is not None:
        if spec.position_index >= len(accounts):
            raise TransactionRefused(f"{spec.name} is missing its position account")
        position = _key(keys, accounts[spec.position_index], what=f"{spec.name}.position")
        if expected_positions and position not in expected_positions:
            raise TransactionRefused(
                f"{spec.name} names position {position}, which the plan did not authorise"
            )

    if spec.signer_index is not None:
        if spec.signer_index >= len(accounts):
            raise TransactionRefused(f"{spec.name} is missing its signer account")
        signer = _key(keys, accounts[spec.signer_index], what=f"{spec.name}.sender")
        if signer != owner:
            raise TransactionRefused(
                f"{spec.name} would act for {signer}, not for tha funds ({owner})"
            )

    return lb_pair, position


def _check_ata(ix: CompiledInstruction, keys: list[str], *, owner: str) -> None:
    if bytes(ix.data) not in (b"", b"\x01"):
        raise TransactionRefused("only ATA Create and CreateIdempotent are permitted")
    accounts = list(ix.accounts)
    if len(accounts) < 3:
        raise TransactionRefused("ATA instruction has too few accounts to check")
    payer = _key(keys, accounts[0], what="ata.payer")
    ata_owner = _key(keys, accounts[2], what="ata.owner")
    if payer != owner or ata_owner != owner:
        raise TransactionRefused("an ATA may only be created by us, for us")


def _check_token(ix: CompiledInstruction, keys: list[str], *, owner: str) -> None:
    data = bytes(ix.data)
    if not data:
        raise TransactionRefused("empty SPL Token instruction")
    opcode = data[0]
    if opcode not in (TOKEN_CLOSE_ACCOUNT, TOKEN_SYNC_NATIVE):
        raise TransactionRefused(
            f"SPL Token opcode {opcode} is not permitted; only CloseAccount and SyncNative are"
        )
    accounts = list(ix.accounts)
    if opcode == TOKEN_CLOSE_ACCOUNT:
        if len(accounts) < 3:
            raise TransactionRefused("CloseAccount is missing accounts")
        destination = _key(keys, accounts[1], what="token.close.destination")
        authority = _key(keys, accounts[2], what="token.close.authority")
        if destination != owner or authority != owner:
            raise TransactionRefused("a token account may only be closed by us, to us")


def _check_system(ix: CompiledInstruction, keys: list[str], *, owner: str, wsol_ata: str) -> int:
    """Permit exactly one thing: funding our own wrapped-SOL account.

    This is the instruction that could drain the wallet, so it is the one with the tightest
    rule. `SystemProgram::Transfer` moves lamports to an arbitrary destination; we accept it
    only when the destination is the wSOL ATA we derived ourselves for our own pubkey. The
    worst outcome is that our own SOL becomes our own wrapped SOL.
    """
    data = bytes(ix.data)
    if len(data) < 4:
        raise TransactionRefused("System instruction is too short to classify")
    opcode = struct.unpack_from("<I", data, 0)[0]
    if opcode != SYSTEM_TRANSFER:
        raise TransactionRefused(
            f"System program opcode {opcode} is not permitted; only Transfer to our own wSOL account is"
        )
    if len(data) != 12:
        raise TransactionRefused("System Transfer has an unexpected payload length")
    lamports = struct.unpack_from("<Q", data, 4)[0]
    accounts = list(ix.accounts)
    if len(accounts) < 2:
        raise TransactionRefused("System Transfer is missing accounts")
    source = _key(keys, accounts[0], what="system.transfer.from")
    destination = _key(keys, accounts[1], what="system.transfer.to")
    if source != owner:
        raise TransactionRefused("System Transfer must be funded by us")
    if destination != wsol_ata:
        raise TransactionRefused(
            f"System Transfer would send {lamports} lamports to {destination}; the only permitted "
            f"destination is our own wSOL account {wsol_ata}"
        )
    return lamports


def guard_transaction(
    *,
    encoded: str,
    owner: Pubkey,
    account_data: Callable[[str], bytes],
    max_priority_fee_lamports: int,
    expected_pools: Iterable[str] = (),
    expected_positions: Iterable[str] = (),
    extra_signers: Iterable[str] = (),
    max_wrap_lamports: int = 0,
) -> GuardedTransaction:
    """Refuse, or return something signable. There is no third outcome.

    `account_data` fetches raw account bytes and exists only to expand address lookup tables;
    it is the sole network dependency and tests pass a fake that asserts it is never called.
    `expected_pools` / `expected_positions` bind the transaction to the PLAN that produced it,
    so a builder that silently retargets a different allowlisted pool is still refused.
    """
    owner_str = str(owner)
    pools = frozenset(expected_pools)
    positions = frozenset(expected_positions)
    extras = frozenset(extra_signers)

    tx = decode_unsigned(encoded)
    message = tx.message
    if not isinstance(message, MessageV0):
        raise TransactionRefused("only v0 transactions are accepted; a legacy message was returned")

    # Opening a DLMM position needs the NEW position account to sign, so exactly one extra
    # signature is tolerated -- and only for a key the PLAN generated on this side of the
    # trust boundary and passed in as `extra_signers`. An ephemeral position keypair holds
    # nothing and authorises nothing beyond its own creation; a second signer we did not
    # create is a co-signed transaction and is refused.
    required = message.header.num_required_signatures
    if required < 1 or required > 2:
        raise TransactionRefused(
            f"transaction requires {required} signatures; only 1, or 2 with a plan-generated "
            "position key, is allowed"
        )
    if str(message.account_keys[0]) != owner_str:
        raise TransactionRefused(
            f"fee payer is {message.account_keys[0]}, not tha funds ({owner_str})"
        )
    if required == 2:
        second = str(message.account_keys[1])
        if second not in extras:
            raise TransactionRefused(
                f"transaction wants a second signature from {second}, which this plan did not create"
            )
    if len(tx.signatures) != required or any(sig != Signature.default() for sig in tx.signatures):
        raise TransactionRefused("builder returned a transaction that is already signed")

    keys = _resolve_keys(message, account_data)
    wsol_ata = str(associated_token_address(owner, Pubkey.from_string(WSOL_MINT)))

    decoded: list[DecodedInstruction] = []
    budget_inputs: list[tuple[str, bytes]] = []
    pools_touched: set[str] = set()
    positions_touched: set[str] = set()
    wrapped_lamports = 0
    saw_dlmm = False

    for index, ix in enumerate(message.instructions):
        program = _key(keys, ix.program_id_index, what=f"instruction {index} program")
        data = bytes(ix.data)
        budget_inputs.append((program, data))

        if program not in ALLOWED_PROGRAMS:
            raise TransactionRefused(
                f"instruction {index} calls {program}, which is not an allowlisted program"
            )

        if program == DLMM_PROGRAM:
            if len(data) < 8:
                raise TransactionRefused(f"instruction {index} has no DLMM discriminator")
            disc = data[:8].hex()
            if disc in SWAP_DISCRIMINATORS:
                raise TransactionRefused(
                    f"instruction {index} is a DLMM SWAP ({FORBIDDEN_DLMM[disc]}). This package "
                    "cannot swap; inventory is converted by other people's flow through a "
                    "one-sided ladder, never by a trade we sign."
                )
            if disc in FORBIDDEN_DLMM:
                raise TransactionRefused(
                    f"instruction {index} is DLMM {FORBIDDEN_DLMM[disc]}, which is not LP management"
                )
            spec = ALLOWED_DLMM.get(disc)
            if spec is None:
                raise TransactionRefused(
                    f"instruction {index} is DLMM discriminator {disc}, which is not on the allowlist"
                )
            lb_pair, position = _check_dlmm(
                spec,
                ix,
                keys,
                owner=owner_str,
                expected_pools=pools,
                expected_positions=positions,
            )
            saw_dlmm = True
            if lb_pair is not None:
                pools_touched.add(lb_pair)
            if position is not None:
                positions_touched.add(position)
            decoded.append(DecodedInstruction(index, program, spec.name, lb_pair, position, spec.kind))
            continue

        if program == COMPUTE_BUDGET_PROGRAM:
            decoded.append(DecodedInstruction(index, program, "compute_budget", None, None, "scaffold"))
        elif program == ASSOCIATED_TOKEN_PROGRAM:
            _check_ata(ix, keys, owner=owner_str)
            decoded.append(DecodedInstruction(index, program, "create_ata", None, None, "scaffold"))
        elif program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            _check_token(ix, keys, owner=owner_str)
            decoded.append(DecodedInstruction(index, program, "spl_token", None, None, "scaffold"))
        elif program == SYSTEM_PROGRAM:
            wrapped_lamports += _check_system(ix, keys, owner=owner_str, wsol_ata=wsol_ata)
            decoded.append(DecodedInstruction(index, program, "wrap_sol", None, None, "scaffold"))
        elif program == MEMO_PROGRAM:
            decoded.append(DecodedInstruction(index, program, "memo", None, None, "scaffold"))

    if not saw_dlmm:
        raise TransactionRefused("transaction contains no DLMM instruction; there is nothing to do")
    if wrapped_lamports > max_wrap_lamports:
        raise TransactionRefused(
            f"transaction would wrap {wrapped_lamports} lamports; the plan authorised {max_wrap_lamports}"
        )

    fee, unit_limit, unit_price = _compute_budget(budget_inputs, max_priority_fee_lamports)
    return GuardedTransaction(
        transaction=tx,
        instructions=tuple(decoded),
        compute_unit_limit=unit_limit,
        compute_unit_price_micro_lamports=unit_price,
        priority_fee_lamports=fee,
        pools_touched=frozenset(pools_touched),
        positions_touched=frozenset(positions_touched),
    )
