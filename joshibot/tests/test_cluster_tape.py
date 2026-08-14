"""Tests for the cluster swap-level flow recorder.

No live network anywhere in this file. The RPC is a fake whose canned responses are shaped
from real ``getTransaction``/``getSignaturesForAddress`` output observed on the six cluster
pools on 2026-08-13, including the three shapes that would have broken a naive parser:

- a Meteora ``RemoveLiquidityByRange2``, where **both** vaults go negative (a "the pool moved,
  so it was a swap" parser records an enormous fabricated fill);
- a routed transaction where the pool appears in ``accountKeys`` with **zero** vault deltas
  because a router merely considered it;
- a multi-hop route carrying two ``swap2`` instructions on two *different* DLMM pairs, which
  is why the leg counter keys on ``accounts[0] == pool`` rather than on the program id.

The anti-mirror gate is explicit: every test that claims schema conformance **imports and
constructs the real** ``shitcoims_tape.schema`` types, so a drifted field name fails here
rather than on integration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from shitcoims_cluster.parse import (
    Attempt,
    ClusterSwap,
    Defect,
    DefectReason,
    PoolReserves,
    RowKind,
    VaultState,
    discriminator_of,
    listing_is_usable,
    parse_failed_signature,
    parse_transaction,
    sort_listing,
)
from shitcoims_cluster.pools import (
    CLUSTER_POOLS,
    DREGG,
    KNOWN_DISCRIMINATORS,
    METEORA_DLMM_PROGRAM,
    NOSIS,
    POOLS_BY_ADDRESS,
    PUMPSWAP_PROGRAM,
    WEAVE,
    WSOL_MINT,
    pool_for,
)
from shitcoims_cluster.record import Collector
from shitcoims_cluster.rpc import READ_METHODS, HeliusRpc, RpcError, read_secret_file
from shitcoims_cluster.tape import ClusterTape
from shitcoims_cluster.watch import PoolWatch

# The real tape contract. Imported, not mirrored.
from shitcoims_tape.schema import (
    Chainstamp,
    Provenance,
    Reserves,
    Side,
    TapeError,
    Trade,
    WatchClose,
    WatchWindow,
)

WEAVE_SOL = "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn"
NOSIS_SOL = "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc"
WEAVE_NOSIS = "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD"
DREGG_NOSIS = "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD"

TRADER = "hnu5iBK8UoHb51UFsH1RYTUAYdrhjHvV5YMTf9T1CYN"
SPONSOR = "HxjwdF326ZunmUwC1iXhfgL3ku78YsksN6n7Rfxzwr6b"
ROUTER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
OTHER_POOL = "77Nm2cKtZfJvcQttySdqoZvH1mbxUkUWQwKsrpyvAebu"

BLOCK_TIME = 1786653771
NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58_encode(raw: bytes) -> str:
    total = int.from_bytes(raw, "big")
    out = ""
    while total:
        total, rem = divmod(total, 58)
        out = _B58[rem] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def anchor_data(name: str, payload: bytes = b"\x00" * 16) -> str:
    disc = hashlib.sha256(f"global:{name}".encode()).digest()[:8]
    return b58_encode(disc + payload)


def sig(seed: str) -> str:
    """An 88-character base58 signature, which is what the real schema validates."""

    body = hashlib.sha256(seed.encode()).hexdigest()
    filler = "".join(_B58[int(c, 16)] for c in body)
    return (filler * 3)[:88]


def _balance(index: int, account_owner: str, mint: str, amount: int, decimals: int) -> dict[str, Any]:
    return {
        "accountIndex": index,
        "mint": mint,
        "owner": account_owner,
        "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "uiTokenAmount": {
            # The RPC returns raw base units as a decimal STRING, and `uiAmount` as an f64.
            # The parser must read `amount`; `uiAmount` is present here so a test would catch
            # a parser that reached for the lossy field.
            "amount": str(amount),
            "decimals": decimals,
            "uiAmount": amount / (10**decimals),
            "uiAmountString": str(amount / (10**decimals)),
        },
    }


def build_tx(
    *,
    signature: str,
    slot: int = 439089347,
    block_time: int | None = BLOCK_TIME,
    fee: int = 19000,
    fee_payer: str = TRADER,
    extra_signers: tuple[str, ...] = (),
    accounts: tuple[str, ...] = (),
    pre_balances: tuple[dict[str, Any], ...] = (),
    post_balances: tuple[dict[str, Any], ...] = (),
    instructions: tuple[dict[str, Any], ...] = (),
    inner: tuple[dict[str, Any], ...] = (),
    err: Any = None,
) -> dict[str, Any]:
    keys = [{"pubkey": fee_payer, "signer": True, "writable": True}]
    keys += [{"pubkey": s, "signer": True, "writable": False} for s in extra_signers]
    keys += [{"pubkey": a, "signer": False, "writable": True} for a in accounts]
    return {
        "slot": slot,
        "blockTime": block_time,
        "version": 0,
        "transaction": {
            "signatures": [signature],
            "message": {"accountKeys": keys, "instructions": list(instructions)},
        },
        "meta": {
            "err": err,
            "fee": fee,
            "computeUnitsConsumed": 84213,
            "preBalances": [10**9] * len(keys),
            "postBalances": [10**9] * len(keys),
            "preTokenBalances": list(pre_balances),
            "postTokenBalances": list(post_balances),
            "innerInstructions": [{"index": 0, "instructions": list(inner)}] if inner else [],
            "logMessages": ["Program log: Instruction: Sell"],
        },
    }


# ---------------------------------------------------------------------------------------
# fixtures: the four shapes that matter
# ---------------------------------------------------------------------------------------

POOL_SOL_VAULT = "BHTp2X464qSdXDk6N3sSfMURHboJZbU9HtrVzXixEJDn"
POOL_TOKEN_VAULT = "BpRFSFaJMRk1x2ZiTQLei4kAHHRzmiSRkXNmFYNW1nyC"
TRADER_TOKEN_ATA = "Tx2n2tDF7aj3nmrbHvCBrc2i8ieeP9pVHvrscYY3hA1"
TRADER_SOL_ATA = "2ACnANaaJHStsu37zx9UWMmyhnLRQXauKQHdYdQGVu1G"
# Three fee recipients that all gain wrapped SOL in the same transaction. They exist in this
# fixture specifically so the counterparty rule has to reject them.
FEE_PROTOCOL = "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL"
FEE_CREATOR = "WmrMUEqeDkqpSk2AfsWThCecLLmSnjxUQmdfJ2CKQmN"
FEE_OTHER = "62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV"

#: Real signature, real numbers: the whole of ``44GNBXvm…`` on the nosis/SOL pool.
SELL_SIGNATURE = (
    "44GNBXvmMWHFf38emXxXpaZqeDEY9U59eZwnUNLZmWcQGnWpi4fJ3fqLLtFNjcXgpHnsbfqQ6ukLVnRX7tTs5J4x"
)


def pumpswap_sell_tx(signature: str = SELL_SIGNATURE, **overrides: Any) -> dict[str, Any]:
    """A direct nosis->SOL sell on the PumpSwap nosis/SOL pool, transcribed from chain.

    The trader sent 24,463,717,163 raw nosis in and the pool paid 75,666,317 lamports out —
    but the trader only received **74,983,955**, because 18,954 + 644,453 + 18,955 was skimmed
    to three fee accounts on the way. That 682,362-lamport wedge is the reason the
    counterparty rule matches a single leg exactly rather than both: on the SOL leg nobody
    mirrors the pool.
    """

    accounts = (
        TRADER_TOKEN_ATA,
        "AktftA98kSWAxn6kVSoqBXBELUArjKu2H9WmKB48ULFY",
        POOL_SOL_VAULT,
        POOL_TOKEN_VAULT,
        "CmTzGiXRWCGiLTtiPK7fXET9qqRnep1UbjRjs51JHTeG",
        TRADER_SOL_ATA,
        "94qWNrtmfn42h3ZjUZwWvK1MEo9uVmmrBPd2hpNjYDjb",
        NOSIS_SOL,
    )
    kwargs: dict[str, Any] = {
        "signature": signature,
        "accounts": accounts,
        "pre_balances": (
            _balance(1, TRADER, NOSIS, 873854517381, 6),
            _balance(2, FEE_PROTOCOL, WSOL_MINT, 1681946223, 9),
            _balance(3, NOSIS_SOL, WSOL_MINT, 285763126530, 9),
            _balance(4, NOSIS_SOL, NOSIS, 97854868653957, 6),
            _balance(5, FEE_CREATOR, WSOL_MINT, 6136756565, 9),
            _balance(6, TRADER, WSOL_MINT, 5033382771377, 9),
            _balance(7, FEE_OTHER, WSOL_MINT, 5855443917596, 9),
        ),
        "post_balances": (
            _balance(1, TRADER, NOSIS, 849390800218, 6),
            _balance(2, FEE_PROTOCOL, WSOL_MINT, 1681965177, 9),
            _balance(3, NOSIS_SOL, WSOL_MINT, 285687460213, 9),
            _balance(4, NOSIS_SOL, NOSIS, 97879332371120, 6),
            _balance(5, FEE_CREATOR, WSOL_MINT, 6137401018, 9),
            _balance(6, TRADER, WSOL_MINT, 5033457755332, 9),
            _balance(7, FEE_OTHER, WSOL_MINT, 5855443936551, 9),
        ),
        "instructions": (
            {
                "programId": PUMPSWAP_PROGRAM,
                "accounts": [NOSIS_SOL, TRADER, POOL_SOL_VAULT, POOL_TOKEN_VAULT],
                "data": anchor_data("sell"),
                "stackHeight": None,
            },
        ),
    }
    kwargs.update(overrides)
    return build_tx(**kwargs)


DLMM_NOSIS_VAULT = "53XFCkbkbZB8QU2FcQGbtYJ5ep6KKHj9wHZowegenSeV"
DLMM_WEAVE_VAULT = "AQhCHHehprVpiQxt1AS2ebVuotDaGzvtwt4pxsAFC3Q1"


def dlmm_routed_swap_tx(signature: str = sig("dlmm-route")) -> dict[str, Any]:
    """A weave/nosis DLMM swap reached through a router, with a second swap on another pair.

    Real numbers from a live route: 2,548,263,091 raw nosis into the pool, 4,326,299,800 raw
    weave out. The trader's net on both mints is zero because the route continued, so the
    counterparty is NOT identifiable and must come back ``None``.
    """

    return build_tx(
        signature=signature,
        fee_payer=SPONSOR,
        accounts=(DLMM_NOSIS_VAULT, DLMM_WEAVE_VAULT, WEAVE_NOSIS, OTHER_POOL, ROUTER),
        pre_balances=(
            _balance(1, WEAVE_NOSIS, NOSIS, 1438588607122, 6),
            _balance(2, WEAVE_NOSIS, WEAVE, 3009317330999, 6),
        ),
        post_balances=(
            _balance(1, WEAVE_NOSIS, NOSIS, 1441136870213, 6),
            _balance(2, WEAVE_NOSIS, WEAVE, 3004991031199, 6),
        ),
        inner=(
            {
                "programId": METEORA_DLMM_PROGRAM,
                "accounts": [WEAVE_NOSIS, METEORA_DLMM_PROGRAM, DLMM_WEAVE_VAULT],
                "data": anchor_data("swap2"),
                "stackHeight": 2,
            },
            {
                # Same program, different pool: must NOT count as a leg on this pair.
                "programId": METEORA_DLMM_PROGRAM,
                "accounts": [
                    OTHER_POOL,
                    METEORA_DLMM_PROGRAM,
                    "7nPHf6gPeqygDTyfQFWYcVqiwKJgRxbyMQMqBB2rDGtY",
                ],
                "data": anchor_data("swap2"),
                "stackHeight": 2,
            },
        ),
    )


DREGG_NOSIS_VAULT_A = "6rXJkLYuXNVLYQx6Q9EPP1o9CY7CyxNvJTLJQBTKjTTV"
DREGG_NOSIS_VAULT_B = "A1zv6sH7B3sBUiVMd4mmVAvQmZjWTqfsWJqQKz9nfKGb"


def dlmm_remove_liquidity_tx(signature: str = sig("dlmm-remove")) -> dict[str, Any]:
    """``RemoveLiquidityByRange2``: BOTH vaults go negative. Real numbers from ``2zzyuBzB…``.

    This is the shape that makes a sign-structure classifier necessary. A parser that treated
    any pool movement as a swap would have booked a 1,632,183,148,906-raw-unit fill here.
    """

    return build_tx(
        signature=signature,
        fee_payer="Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ",
        accounts=(DREGG_NOSIS_VAULT_A, DREGG_NOSIS_VAULT_B, DREGG_NOSIS),
        pre_balances=(
            _balance(1, DREGG_NOSIS, NOSIS, 1632183148906, 6),
            _balance(2, DREGG_NOSIS, DREGG, 10889135408, 6),
        ),
        post_balances=(
            _balance(1, DREGG_NOSIS, NOSIS, 0, 6),
            _balance(2, DREGG_NOSIS, DREGG, 10889135130, 6),
        ),
        instructions=(
            {
                "programId": METEORA_DLMM_PROGRAM,
                "accounts": [DREGG_NOSIS, DREGG_NOSIS_VAULT_A],
                "data": anchor_data("remove_liquidity_by_range2"),
                "stackHeight": None,
            },
        ),
    )


def untouched_pool_tx(signature: str = sig("untouched")) -> dict[str, Any]:
    """The pool is in ``accountKeys`` with zero deltas: a router looked and did not trade."""

    return build_tx(
        signature=signature,
        accounts=(POOL_SOL_VAULT, POOL_TOKEN_VAULT, NOSIS_SOL),
        pre_balances=(
            _balance(1, NOSIS_SOL, WSOL_MINT, 283749633697, 9),
            _balance(2, NOSIS_SOL, NOSIS, 98505527295794, 6),
        ),
        post_balances=(
            _balance(1, NOSIS_SOL, WSOL_MINT, 283749633697, 9),
            _balance(2, NOSIS_SOL, NOSIS, 98505527295794, 6),
        ),
    )


# ---------------------------------------------------------------------------------------
# the universe
# ---------------------------------------------------------------------------------------


WEAVE_SOL_DLMM = "77Nm2cKtZfJvcQttySdqoZvH1mbxUkUWQwKsrpyvAebu"


def test_pool_table_matches_the_seven_addresses_and_their_verified_pairs() -> None:
    assert len(CLUSTER_POOLS) == 7
    assert {p.address for p in CLUSTER_POOLS} == {
        WEAVE_SOL,
        NOSIS_SOL,
        "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
        "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
        WEAVE_NOSIS,
        DREGG_NOSIS,
        # Added after the network map resolved the LP wallet from the tape's own claim_fee
        # payer and found we provide liquidity to an edge the recorder was not watching.
        WEAVE_SOL_DLMM,
    }
    assert pool_for(WEAVE_SOL_DLMM).mints == frozenset({WEAVE, WSOL_MINT})
    assert pool_for(WEAVE_SOL_DLMM).dex == "meteora_dlmm"
    assert pool_for(WEAVE_SOL_DLMM).replay_sufficient_reserves is False
    # Same pair as the pumpswap weave/SOL pool, different venue: the address is the identity,
    # never the pair, or the two would collide in POOLS_BY_ADDRESS.
    assert pool_for(WEAVE_SOL_DLMM).mints == pool_for(WEAVE_SOL).mints
    assert pool_for(WEAVE_SOL_DLMM).address != pool_for(WEAVE_SOL).address
    # The scratchpad behind RESULT_swing_cluster.md has weave and SOLVE transposed; this
    # pairing is the on-chain one, read from each pool's own vault mints.
    assert pool_for(WEAVE_SOL).mints == frozenset({WEAVE, WSOL_MINT})
    assert pool_for(WEAVE_NOSIS).mints == frozenset({WEAVE, NOSIS})
    assert pool_for(DREGG_NOSIS).mints == frozenset({DREGG, NOSIS})
    # Constant product is replay-sufficient from reserves; a DLMM is not.
    assert pool_for(NOSIS_SOL).replay_sufficient_reserves is True
    assert pool_for(WEAVE_NOSIS).replay_sufficient_reserves is False
    assert POOLS_BY_ADDRESS[DREGG_NOSIS].label == "DREGG/nosis"
    with pytest.raises(KeyError):
        pool_for("So11111111111111111111111111111111111111112")


def test_pool_mints_are_real_schema_addresses() -> None:
    """Every address in the table survives the tape schema's decode-based validator."""

    from shitcoims_tape.schema import _mint as schema_mint  # the real validator

    for spec in CLUSTER_POOLS:
        assert schema_mint(spec.address, field="pool") == spec.address
        for mint in spec.mints:
            assert schema_mint(mint) == mint


def test_anchor_discriminators_are_derived_not_guessed() -> None:
    """The table is sha256("global:<name>")[:8]; ``414b…`` is the one seen live."""

    for hex_disc, name in KNOWN_DISCRIMINATORS.items():
        assert hashlib.sha256(f"global:{name}".encode()).digest()[:8].hex() == hex_disc
    assert KNOWN_DISCRIMINATORS["414b3f4ceb5b5b88"] == "swap2"
    assert discriminator_of(anchor_data("swap2")) == "414b3f4ceb5b5b88"
    assert discriminator_of("!!!not base58!!!") == ""


# ---------------------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------------------


def test_pumpswap_sell_parses_to_exact_integer_amounts_and_a_real_trade() -> None:
    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.row_kind == RowKind.SWAP
    assert row.token_in_mint == NOSIS
    assert row.token_in_raw == 24463717163
    assert row.token_out_mint == WSOL_MINT
    assert row.token_out_raw == 75666317
    assert row.side is Side.SELL
    assert row.counterparty == TRADER
    assert row.counterparty_paid_fee is True
    assert row.swap_legs == 1
    assert row.leg_names == ("sell",)

    # ANTI-MIRROR GATE: the REAL Trade type, constructed and validated.
    trade = row.as_trade()
    assert isinstance(trade, Trade)
    assert trade.mint == NOSIS
    assert trade.wallet == TRADER
    assert trade.side is Side.SELL
    # Trader's view is the mirror of the pool's: token out of the wallet, SOL in.
    assert trade.token_delta_raw == -24463717163
    assert trade.sol_delta_lamports == 75666317
    assert trade.pool == NOSIS_SOL
    assert trade.fee_payer == TRADER
    assert trade.signers == (TRADER,)
    # And the real Chainstamp and Provenance, both constructed and therefore validated.
    assert isinstance(row.chain, Chainstamp)
    assert isinstance(row.provenance, Provenance)
    assert row.provenance.fetched_at == row.t_ingest
    assert row.chain.block_time == BLOCK_TIME
    assert row.t_event == "2026-08-13T20:42:51+00:00"
    # The pool-state record is this package's own type, deliberately (see parse's docstring).
    assert isinstance(row.reserves, PoolReserves)
    assert all(isinstance(v, VaultState) for v in row.reserves.vaults)


def test_the_three_fee_recipients_are_not_mistaken_for_the_trader() -> None:
    """All three gain wrapped SOL in the same transaction; none mirrors a leg exactly."""

    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.counterparty not in {FEE_PROTOCOL, FEE_CREATOR, FEE_OTHER}
    assert row.counterparty == TRADER


def test_two_owners_mirroring_the_same_leg_yields_no_attribution() -> None:
    """Ambiguity resolves to ``None``, never to a coin flip between two candidates."""

    tx = pumpswap_sell_tx(signature=sig("ambiguous"))
    decoy = "5cjcW9wEXCbnkNyZUYBnr4wBefkPnFyMwpUgeMwiVUqz"
    tx["meta"]["preTokenBalances"].append(_balance(9, decoy, NOSIS, 24463717163, 6))
    tx["meta"]["postTokenBalances"].append(_balance(9, decoy, NOSIS, 0, 6))
    row = parse_transaction(tx, pool_for(NOSIS_SOL), signature=sig("ambiguous"), t_ingest=NOW)
    assert isinstance(row, ClusterSwap)
    assert row.counterparty is None
    assert row.counterparty_paid_fee is None
    assert row.as_trade() is None


def test_intra_slot_order_is_recorded_as_unknown_rather_than_invented() -> None:
    """``getTransaction`` returns no block index, so ``tx_index`` stays ``None``.

    Not a corner case: 57 of 158 observed slots on nosis/SOL carried more than one
    transaction. Leaving the field ``None`` is what stops a downstream sort from believing an
    order that came out of a dict iteration.
    """

    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.chain.tx_index is None
    assert "tx_index" not in row.chain.to_json()


def test_buy_side_is_derived_from_which_way_sol_moved() -> None:
    """SOL into the pool is a buy. The sign convention is pool-relative and stated once."""

    tx = pumpswap_sell_tx(signature=sig("pumpswap-buy"))
    tx["meta"]["preTokenBalances"], tx["meta"]["postTokenBalances"] = (
        tx["meta"]["postTokenBalances"],
        tx["meta"]["preTokenBalances"],
    )
    row = parse_transaction(tx, pool_for(NOSIS_SOL), signature=sig("pumpswap-buy"), t_ingest=NOW)
    assert isinstance(row, ClusterSwap)
    assert row.token_in_mint == WSOL_MINT
    assert row.side is Side.BUY
    trade = row.as_trade()
    assert isinstance(trade, Trade)
    assert trade.sol_delta_lamports == -75666317
    assert trade.token_delta_raw == 24463717163


def test_token_token_swap_records_both_legs_and_refuses_to_project_onto_trade() -> None:
    """A weave/nosis fill has no SOL leg, so ``Trade`` does not fit and is not forced."""

    row = parse_transaction(
        dlmm_routed_swap_tx(), pool_for(WEAVE_NOSIS), signature=sig("dlmm-route"), t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.row_kind == RowKind.SWAP
    assert row.token_in_mint == NOSIS
    assert row.token_in_raw == 2548263091
    assert row.token_out_mint == WEAVE
    assert row.token_out_raw == 4326299800
    assert row.side is None
    assert row.as_trade() is None
    # A DLMM reserve row is a summary, never a replay input.
    assert row.reserves.replay_sufficient is False
    assert row.as_tape_reserves() is None


def test_routed_swap_leaves_the_counterparty_unidentified_rather_than_guessing() -> None:
    row = parse_transaction(
        dlmm_routed_swap_tx(), pool_for(WEAVE_NOSIS), signature=sig("dlmm-route"), t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.counterparty is None
    # Tri-state, not a fabricated False: we do not know who traded, so we do not know
    # whether they paid. The fee payer is still recorded.
    assert row.counterparty_paid_fee is None
    assert row.fee_payer == SPONSOR


def test_leg_counter_keys_on_the_pool_not_the_program() -> None:
    """Two ``swap2`` instructions, two different pairs — this pool saw exactly one."""

    row = parse_transaction(
        dlmm_routed_swap_tx(), pool_for(WEAVE_NOSIS), signature=sig("dlmm-route"), t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.swap_legs == 1
    assert row.leg_discriminators == ("414b3f4ceb5b5b88",)
    assert row.leg_names == ("swap2",)


def test_liquidity_removal_is_not_recorded_as_a_swap() -> None:
    """Both vaults negative. The sign structure, not the instruction name, decides."""

    row = parse_transaction(
        dlmm_remove_liquidity_tx(), pool_for(DREGG_NOSIS), signature=sig("dlmm-remove"), t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.row_kind == RowKind.LIQUIDITY
    assert row.token_in_mint is None
    assert row.token_out_mint is None
    assert row.token_in_raw == 0
    assert row.side is None
    assert row.leg_names == ("remove_liquidity_by_range2",)
    # The reserves are still recorded: the pool state changed and that is worth having.
    assert row.reserves.vault_for(NOSIS) is not None
    assert row.reserves.vault_for(NOSIS).post_raw == 0  # type: ignore[union-attr]


def test_pool_referenced_with_zero_deltas_is_a_reference_not_liquidity_and_not_flow() -> None:
    """The common case: a router named the pool in a lookup table and filled somewhere else.

    Measured on a live pass, 30 of 39 fetched transactions on nosis/SOL were this. They are
    kept because each is a free reserve reading at that slot, and they are given their own
    ``kind`` so no flow statistic can accidentally count them.
    """

    row = parse_transaction(
        untouched_pool_tx(), pool_for(NOSIS_SOL), signature=sig("untouched"), t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    assert row.row_kind == RowKind.REFERENCE
    assert row.row_kind != RowKind.LIQUIDITY
    assert all(v.delta_raw == 0 for v in row.reserves.vaults)
    # Still a usable state observation: the reserves are present and post == pre.
    sol_vault = row.reserves.vault_for(WSOL_MINT)
    assert sol_vault is not None
    assert sol_vault.post_raw == 283749633697


def test_constant_product_reserves_project_onto_the_real_reserves_type() -> None:
    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    reserves = row.as_tape_reserves()
    assert isinstance(reserves, Reserves)  # the REAL type
    assert reserves.pool == NOSIS_SOL
    assert reserves.real_sol == 285687460213
    assert reserves.real_tokens == 97879332371120
    # Zero virtuals are the exact algebra of a constant-product pool, not a missing value.
    assert reserves.virtual_sol == 0
    assert reserves.virtual_tokens == 0


# ---------------------------------------------------------------------------------------
# defect routing — the Track B bug, pinned
# ---------------------------------------------------------------------------------------


def test_missing_block_time_goes_to_the_defect_stream_never_the_tape() -> None:
    tx = pumpswap_sell_tx(signature=sig("no-time"), block_time=None)
    row = parse_transaction(tx, pool_for(NOSIS_SOL), signature=sig("no-time"), t_ingest=NOW)
    assert isinstance(row, Defect)
    assert row.reason == DefectReason.NO_BLOCK_TIME
    assert row.t_event is None
    assert row.slot == 439089347


def test_block_time_falls_back_to_the_signature_listing_before_defecting() -> None:
    """``getSignaturesForAddress`` carries ``blockTime`` directly — use it rather than lose the row."""

    tx = pumpswap_sell_tx(signature=sig("listing-time"), block_time=None)
    row = parse_transaction(
        tx,
        pool_for(NOSIS_SOL),
        signature=sig("listing-time"),
        t_ingest=NOW,
        listing_block_time=BLOCK_TIME,
    )
    assert isinstance(row, ClusterSwap)
    assert row.chain.block_time == BLOCK_TIME


def test_a_transaction_the_node_cannot_produce_is_a_defect() -> None:
    missing = parse_transaction(None, pool_for(NOSIS_SOL), signature=sig("gone"), t_ingest=NOW)
    assert isinstance(missing, Defect)
    assert missing.reason == DefectReason.TX_MISSING


def test_a_pool_named_without_its_vaults_is_a_reference_with_no_reserves() -> None:
    """Positive evidence of no fill, not a defect.

    A swap cannot move a pool without moving a pool-owned token account, and moving one puts
    it in ``pre/postTokenBalances``. So absent vaults means no fill happened. Treating this as
    a defect produced 134 false defects on DREGG/SOL in a single live pass, which would have
    buried the one defect class that actually matters — the missing block time.
    """

    orphan = build_tx(signature=sig("orphan"), accounts=(NOSIS_SOL,))
    row = parse_transaction(orphan, pool_for(NOSIS_SOL), signature=sig("orphan"), t_ingest=NOW)
    assert isinstance(row, ClusterSwap)
    assert row.row_kind == RowKind.REFERENCE
    assert row.reserves.vaults == ()
    assert row.as_tape_reserves() is None
    assert row.as_trade() is None


def test_unexpected_vault_mint_is_a_defect_not_a_silent_relabel() -> None:
    """If the address in the table is not the pool we think it is, that must be loud."""

    tx = pumpswap_sell_tx(signature=sig("wrong-mint"))
    for entry in tx["meta"]["preTokenBalances"] + tx["meta"]["postTokenBalances"]:
        if entry["owner"] == NOSIS_SOL and entry["mint"] == NOSIS:
            entry["mint"] = DREGG
    row = parse_transaction(tx, pool_for(NOSIS_SOL), signature=sig("wrong-mint"), t_ingest=NOW)
    assert isinstance(row, Defect)
    assert row.reason == DefectReason.MINT_MISMATCH


def test_failed_transactions_become_attempt_rows_from_the_listing_alone() -> None:
    entry = {
        "signature": sig("failed"),
        "slot": 439089138,
        "blockTime": BLOCK_TIME,
        "err": {"InstructionError": [0, {"Custom": 6001}]},
        "confirmationStatus": "finalized",
    }
    row = parse_failed_signature(entry, pool_for(WEAVE_SOL), t_ingest=NOW)
    assert isinstance(row, Attempt)
    assert row.chain.block_time == BLOCK_TIME
    assert "6001" in row.error
    assert row.to_json()["kind"] == RowKind.ATTEMPT


def test_a_listing_entry_without_a_block_time_defects_too() -> None:
    entry = {"signature": sig("no-listing-time"), "slot": 1, "blockTime": None, "err": {"x": 1}}
    row = parse_failed_signature(entry, pool_for(WEAVE_SOL), t_ingest=NOW)
    assert isinstance(row, Defect)
    assert row.reason == DefectReason.NO_BLOCK_TIME
    assert listing_is_usable(entry) is False
    assert listing_is_usable({"signature": sig("ok"), "slot": 1, "blockTime": BLOCK_TIME}) is True


# ---------------------------------------------------------------------------------------
# integers only
# ---------------------------------------------------------------------------------------


def test_no_float_survives_to_disk_and_big_amounts_stay_exact(tmp_path: Path) -> None:
    """f64 loses exactness above 2**53; these pools already hold ~1e14 raw units."""

    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    payload = row.to_json()

    for key in ("token_in_raw", "token_out_raw", "fee_lamports"):
        assert isinstance(payload[key], str)
    for vault in payload["reserves"]["vaults"]:
        for key in ("pre_raw", "post_raw", "delta_raw"):
            assert isinstance(vault[key], str)

    # Round-trip through JSON and back to int: the exact value survives.
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert int(decoded["reserves"]["vaults"][1]["post_raw"]) == 97879332371120

    def assert_no_floats(node: Any, path: str = "$") -> None:
        if isinstance(node, float):
            raise AssertionError(f"float reached the tape at {path}: {node!r}")
        if isinstance(node, dict):
            for key, value in node.items():
                assert_no_floats(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                assert_no_floats(value, f"{path}[{index}]")

    assert_no_floats(payload)


def test_raw_amounts_are_read_from_the_string_field_not_the_ui_float() -> None:
    """A 15-digit raw amount is not representable as an f64-derived ``uiAmount``."""

    tx = pumpswap_sell_tx(signature=sig("big"))
    huge_pre, huge_post = 900719925474099, 900719925474111  # both above 2**53
    tx["meta"]["preTokenBalances"][3]["uiTokenAmount"]["amount"] = str(huge_pre)
    tx["meta"]["preTokenBalances"][3]["uiTokenAmount"]["uiAmount"] = 900719925.474099
    tx["meta"]["postTokenBalances"][3]["uiTokenAmount"]["amount"] = str(huge_post)
    tx["meta"]["postTokenBalances"][3]["uiTokenAmount"]["uiAmount"] = 900719925.474111
    row = parse_transaction(tx, pool_for(NOSIS_SOL), signature=sig("big"), t_ingest=NOW)
    assert isinstance(row, ClusterSwap)
    vault = row.reserves.vault_for(NOSIS)
    assert vault is not None
    assert vault.post_raw == huge_post
    assert vault.delta_raw == 12


def test_the_real_schema_still_refuses_a_float_amount() -> None:
    """Guards the assumption the projection rests on, in the real type."""

    with pytest.raises(TapeError):
        Trade(
            mint=NOSIS,
            wallet=TRADER,
            side=Side.SELL,
            sol_delta_lamports=1.5,  # type: ignore[arg-type]
            token_delta_raw=-1,
            pool=NOSIS_SOL,
        )


# ---------------------------------------------------------------------------------------
# watch windows and gaps
# ---------------------------------------------------------------------------------------


def test_watch_ledger_builds_a_real_watchwindow() -> None:
    watch = PoolWatch(
        pool=NOSIS_SOL, opened_at=NOW, deadline=NOW + timedelta(hours=6), poll_interval=20.0
    )
    window = watch.window()
    assert isinstance(window, WatchWindow)  # the REAL type
    assert window.mint == NOSIS_SOL
    assert window.closed_at is None
    closed = watch.close(NOW + timedelta(hours=1), WatchClose.DEADLINE)
    assert closed["window"]["close_reason"] == "deadline"
    assert watch.is_informatively_censored is False


def test_a_gap_closes_the_window_as_informative_censoring() -> None:
    watch = PoolWatch(
        pool=NOSIS_SOL, opened_at=NOW, deadline=NOW + timedelta(hours=6), poll_interval=20.0
    )
    watch.close(NOW + timedelta(minutes=5), WatchClose.OBSERVER_LOST)
    assert watch.is_informatively_censored is True


def test_poll_gap_is_detected_at_more_than_twice_the_interval() -> None:
    watch = PoolWatch(
        pool=NOSIS_SOL, opened_at=NOW, deadline=NOW + timedelta(hours=6), poll_interval=20.0
    )
    assert watch.note_poll(NOW) is None  # first poll of a process is never a gap
    assert watch.note_poll(NOW + timedelta(seconds=20)) is None
    assert watch.note_poll(NOW + timedelta(seconds=60)) is None  # exactly 2x is jitter, not a gap
    gap = watch.note_poll(NOW + timedelta(seconds=200))
    assert gap is not None
    assert gap.seconds == pytest.approx(140.0)
    assert gap.reason == "poll_interval_exceeded"
    assert len(watch.gaps) == 1


def test_downtime_between_runs_is_a_gap_seeded_from_the_cursor() -> None:
    watch = PoolWatch(
        pool=NOSIS_SOL, opened_at=NOW, deadline=NOW + timedelta(hours=6), poll_interval=20.0
    )
    # A cold start with no prior cursor must NOT report an unbounded gap.
    assert watch.seed_from_cursor(None, NOW) is None
    gap = watch.seed_from_cursor(NOW - timedelta(hours=3), NOW)
    assert gap is not None
    assert gap.reason == "collector_not_running"
    assert gap.seconds == pytest.approx(3 * 3600.0)


def test_a_failed_poll_is_recorded_as_unobserved_time() -> None:
    watch = PoolWatch(
        pool=NOSIS_SOL, opened_at=NOW, deadline=NOW + timedelta(hours=6), poll_interval=20.0
    )
    watch.note_poll(NOW)
    gap = watch.note_failure(NOW + timedelta(seconds=45), "RpcError")
    assert gap.reason == "poll_failed:RpcError"
    assert gap.seconds == pytest.approx(45.0)


# ---------------------------------------------------------------------------------------
# the tape on disk
# ---------------------------------------------------------------------------------------


def test_rows_partition_by_pool_and_chain_day_not_ingest_day(tmp_path: Path) -> None:
    """Ingest order runs backwards against chain order on backfill (Spearman -0.77 measured)."""

    row = parse_transaction(
        pumpswap_sell_tx(),
        pool_for(NOSIS_SOL),
        signature=SELL_SIGNATURE,
        t_ingest=datetime(2026, 8, 20, 3, 0, tzinfo=UTC),  # a week after the event
    )
    assert isinstance(row, ClusterSwap)
    with ClusterTape(tmp_path) as tape:
        assert tape.write_row(row) is True
    written = sorted(p.name for p in (tmp_path / "swaps").iterdir())
    assert written == [f"{NOSIS_SOL}-20260813.jsonl"]  # the day it happened


def test_the_same_signature_is_never_double_counted(tmp_path: Path) -> None:
    row = parse_transaction(
        pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
    )
    assert isinstance(row, ClusterSwap)
    with ClusterTape(tmp_path) as tape:
        assert tape.write_row(row) is True
        assert tape.write_row(row) is False
        assert tape.rows_deduped == 1
    lines = (tmp_path / "swaps" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


def test_defects_go_to_their_own_stream_and_are_not_deduped(tmp_path: Path) -> None:
    defect = parse_transaction(
        pumpswap_sell_tx(block_time=None), pool_for(NOSIS_SOL), signature=sig("d"), t_ingest=NOW
    )
    assert isinstance(defect, Defect)
    with ClusterTape(tmp_path) as tape:
        tape.write_defect(defect)
        tape.write_defect(defect)
    assert not (tmp_path / "swaps").exists()
    body = (tmp_path / "defects" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    assert len(body) == 2
    assert json.loads(body[0])["reason"] == DefectReason.NO_BLOCK_TIME


def test_every_written_row_carries_both_clocks(tmp_path: Path) -> None:
    rows = [
        parse_transaction(
            pumpswap_sell_tx(), pool_for(NOSIS_SOL), signature=SELL_SIGNATURE, t_ingest=NOW
        ),
        parse_failed_signature(
            {"signature": sig("f"), "slot": 1, "blockTime": BLOCK_TIME, "err": {"e": 1}},
            pool_for(NOSIS_SOL),
            t_ingest=NOW,
        ),
    ]
    with ClusterTape(tmp_path) as tape:
        for row in rows:
            assert not isinstance(row, Defect)
            tape.write_row(row)
    for line in (tmp_path / "swaps" / f"{NOSIS_SOL}-20260813.jsonl").read_text().splitlines():
        payload = json.loads(line)
        assert payload["t_event"]
        assert payload["t_ingest"]
        assert payload["chain"]["block_time"] > 0


def test_cursors_round_trip(tmp_path: Path) -> None:
    tape = ClusterTape(tmp_path)
    assert tape.load_cursors() == {}
    tape.save_cursors({NOSIS_SOL: {"last_signature": sig("x"), "last_poll_at": NOW.isoformat()}})
    assert tape.load_cursors()[NOSIS_SOL]["last_signature"] == sig("x")
    tape.close()


# ---------------------------------------------------------------------------------------
# the RPC client — read-only, and no key in an exception
# ---------------------------------------------------------------------------------------


class FakeRpc:
    """Canned responses. No socket is opened anywhere in this file."""

    def __init__(self, listings: dict[str, list[dict[str, Any]]], txs: dict[str, Any]) -> None:
        self.listings = listings
        self.txs = txs
        self.calls: list[tuple[str, Any]] = []
        self.batch_sizes: list[int] = []

    def signatures_for_address(
        self, address: str, *, limit: int = 1000, before: str | None = None, until: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("signatures", address))
        if before is not None:  # single page in these fixtures
            return []
        return list(self.listings.get(address, []))

    def transactions(self, signatures: list[str]) -> list[dict[str, Any] | None]:
        self.calls.append(("transactions", tuple(signatures)))
        self.batch_sizes.append(len(signatures))
        return [self.txs.get(s) for s in signatures]


def test_the_rpc_client_refuses_any_method_outside_the_read_whitelist(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("not-a-real-key")
    key_file.chmod(0o600)
    rpc = HeliusRpc(key_file=key_file)
    try:
        assert "sendTransaction" not in READ_METHODS
        with pytest.raises(RpcError, match="not a read-only method"):
            rpc.call("sendTransaction", [])
        with pytest.raises(RpcError, match="not a read-only method"):
            rpc.call_batch("simulateTransaction", [[]])
    finally:
        rpc.close()


def test_a_group_readable_key_file_is_refused(tmp_path: Path) -> None:
    key_file = tmp_path / "key"
    key_file.write_text("secret")
    key_file.chmod(0o644)
    with pytest.raises(Exception, match="group/world accessible"):
        read_secret_file(key_file)


def test_the_api_key_never_appears_in_a_transport_error(tmp_path: Path) -> None:
    import httpx

    key_file = tmp_path / "key"
    key_file.write_text("SUPERSECRETKEY")
    key_file.chmod(0o600)

    def always_fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed connecting to https://host/?api-key=SUPERSECRETKEY")

    client = httpx.Client(transport=httpx.MockTransport(always_fail))
    rpc = HeliusRpc(key_file=key_file, client=client, max_attempts=2, sleep=lambda _s: None)
    try:
        with pytest.raises(RpcError) as caught:
            rpc.call("getSlot", [])
        assert "SUPERSECRETKEY" not in str(caught.value)
        assert "ConnectError" in str(caught.value)
    finally:
        client.close()


def test_a_429_is_retried_with_backoff_and_then_succeeds(tmp_path: Path) -> None:
    import httpx

    key_file = tmp_path / "key"
    key_file.write_text("k")
    key_file.chmod(0o600)
    seen: list[int] = []
    slept: list[float] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) < 3:
            return httpx.Response(429, headers={"retry-after": "0.01"}, json={})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 12345})

    client = httpx.Client(transport=httpx.MockTransport(flaky))
    rpc = HeliusRpc(key_file=key_file, client=client, sleep=slept.append)
    try:
        assert rpc.call("getSlot", []) == 12345
        assert len(seen) == 3
        assert len(slept) == 2
        assert rpc.rate_limit_waits == 2
    finally:
        client.close()


def test_a_per_item_batch_error_becomes_none_and_does_not_poison_the_batch(tmp_path: Path) -> None:
    import httpx

    key_file = tmp_path / "key"
    key_file.write_text("k")
    key_file.chmod(0o600)

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": body[0]["id"], "result": {"ok": 1}},
                {"jsonrpc": "2.0", "id": body[1]["id"], "error": {"code": -32004}},
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    rpc = HeliusRpc(key_file=key_file, client=client)
    try:
        out = rpc.transactions([sig("a"), sig("b")])
        assert out[0] == {"ok": 1}
        assert out[1] is None
    finally:
        client.close()


# ---------------------------------------------------------------------------------------
# the collector loop, against the fake RPC
# ---------------------------------------------------------------------------------------


def _listing_entry(
    signature: str, slot: int, *, err: Any = None, block_time: int = BLOCK_TIME
) -> dict[str, Any]:
    return {
        "signature": signature,
        "slot": slot,
        "blockTime": block_time,
        "err": err,
        "confirmationStatus": "confirmed",
    }


def test_one_pass_writes_swaps_attempts_and_defects_to_the_right_streams(tmp_path: Path) -> None:
    good, failed, timeless = SELL_SIGNATURE, sig("failed"), sig("timeless")
    listings = {
        NOSIS_SOL: [
            _listing_entry(good, 439089347),
            _listing_entry(failed, 439089346, err={"InstructionError": [0, {"Custom": 6001}]}),
            _listing_entry(timeless, 439089345, block_time=None),
        ]
    }
    rpc = FakeRpc(listings, {good: pumpswap_sell_tx()})
    tape = ClusterTape(tmp_path)
    collector = Collector(
        rpc=rpc,
        tape=tape,
        pools=(pool_for(NOSIS_SOL),),
        poll_seconds=1.0,
        backfill=100,
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    collector.run(minutes=None, once=True)

    stats = collector.stats[NOSIS_SOL]
    assert (stats.swaps, stats.attempts, stats.defects) == (1, 1, 1)
    # The failed transaction cost no getTransaction at all: only the good one was fetched.
    assert rpc.batch_sizes == [1]

    swaps = (tmp_path / "swaps" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    kinds = sorted(json.loads(line)["kind"] for line in swaps)
    assert kinds == ["attempt", "swap"]
    defects = (tmp_path / "defects" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    assert json.loads(defects[0])["reason"] == DefectReason.NO_BLOCK_TIME

    watch_lines = [
        json.loads(line)
        for line in (tmp_path / "watch" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    ]
    assert [row["kind"] for row in watch_lines] == ["watch_open", "watch_close"]
    assert watch_lines[-1]["window"]["close_reason"] == "deadline"
    assert tape.load_cursors()[NOSIS_SOL]["last_signature"] == good


def test_the_cursor_advances_to_the_newest_signature_by_slot(tmp_path: Path) -> None:
    older, newer = sig("older"), sig("newer")
    listings = {NOSIS_SOL: [_listing_entry(newer, 500), _listing_entry(older, 400)]}
    assert [e["signature"] for e in sort_listing(listings[NOSIS_SOL])] == [older, newer]
    rpc = FakeRpc(listings, {})
    tape = ClusterTape(tmp_path)
    Collector(
        rpc=rpc,
        tape=tape,
        pools=(pool_for(NOSIS_SOL),),
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    ).run(minutes=None, once=True)
    assert tape.load_cursors()[NOSIS_SOL]["last_signature"] == newer


def test_restarting_after_downtime_records_the_gap(tmp_path: Path) -> None:
    tape = ClusterTape(tmp_path)
    tape.save_cursors(
        {NOSIS_SOL: {"last_signature": sig("old"), "last_poll_at": (NOW - timedelta(hours=2)).isoformat()}}
    )
    collector = Collector(
        rpc=FakeRpc({}, {}),
        tape=tape,
        pools=(pool_for(NOSIS_SOL),),
        poll_seconds=20.0,
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    collector.run(minutes=None, once=True)
    rows = [
        json.loads(line)
        for line in (tmp_path / "watch" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    ]
    gaps = [r for r in rows if r["kind"] == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "collector_not_running"
    assert gaps[0]["seconds"] == pytest.approx(7200.0)


def test_batches_are_capped_at_the_configured_size(tmp_path: Path) -> None:
    entries = [_listing_entry(sig(f"s{i}"), 400 + i) for i in range(30)]
    rpc = FakeRpc({NOSIS_SOL: entries}, {})
    collector = Collector(
        rpc=rpc,
        tape=ClusterTape(tmp_path),
        pools=(pool_for(NOSIS_SOL),),
        tx_batch=25,
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    collector.run(minutes=None, once=True)
    assert rpc.batch_sizes == [25, 5]
    # Every one came back None from the fake node, so every one is a defect, not a row.
    assert collector.stats[NOSIS_SOL].defects == 30
    assert collector.stats[NOSIS_SOL].swaps == 0


def test_an_rpc_failure_is_recorded_as_unobserved_time_not_as_zero_flow(tmp_path: Path) -> None:
    class BrokenRpc(FakeRpc):
        def signatures_for_address(self, address: str, **kwargs: Any) -> list[dict[str, Any]]:
            raise RpcError("Helius getSignaturesForAddress transport failed (ReadTimeout)")

    collector = Collector(
        rpc=BrokenRpc({}, {}),
        tape=ClusterTape(tmp_path),
        pools=(pool_for(NOSIS_SOL),),
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    collector.run(minutes=None, once=True)
    rows = [
        json.loads(line)
        for line in (tmp_path / "watch" / f"{NOSIS_SOL}-20260813.jsonl").read_text().strip().splitlines()
    ]
    gaps = [r for r in rows if r["kind"] == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["reason"].startswith("poll_failed:")


def test_summary_reports_per_pool_counts(tmp_path: Path) -> None:
    good = SELL_SIGNATURE
    rpc = FakeRpc({NOSIS_SOL: [_listing_entry(good, 439089347)]}, {good: pumpswap_sell_tx()})
    collector = Collector(
        rpc=rpc,
        tape=ClusterTape(tmp_path),
        pools=(pool_for(NOSIS_SOL),),
        clock=lambda: NOW,
        sleep=lambda _s: None,
        log=lambda _m: None,
    )
    collector.run(minutes=None, once=True)
    summary = collector.summary()
    assert summary["pools"]["nosis/SOL"]["swaps"] == 1
    assert summary["pools"]["nosis/SOL"]["address"] == NOSIS_SOL
    assert summary["per_stream"]["swaps"] == 1
