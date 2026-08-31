"""What may be built. Everything absent from this file is refused.

Two allowlists and one deny list live here.

1. INSTRUCTIONS, by 8-byte Anchor discriminator. Anchor derives a discriminator as
   `sha256("global:" + snake_case_name)[:8]`, so the bytes are a function of the name in the
   on-chain program and cannot be spoofed by a caller choosing a different SDK entry point.
   `ALLOWED_DLMM` is add/remove/claim/close plus the account scaffolding those need. The six
   swap discriminators are in `FORBIDDEN_DLMM` purely so the refusal message can name them --
   the allowlist alone already rejects them, and rejects any instruction Meteora ships in
   future that nobody has read yet.

2. POOLS, by address. An instruction naming a pool that is not here is refused before the
   transaction is built, not after.

3. NON-DLMM PROGRAMS, each with its own opcode restriction. The System program is the
   dangerous one and gets the narrowest rule: a lamport transfer is permitted only when its
   destination is our own wrapped-SOL ATA, which is the only System instruction a DLMM
   deposit legitimately needs. See `guard.py` for enforcement.

The discriminators below were computed from the IDL shipped in `@meteora-ag/dlmm@1.9.14` and
cross-checked against `shitcoims_cluster/pools.py::KNOWN_DISCRIMINATORS`, which was derived
independently while decoding live mainnet transactions. Ten values appear in both files and
all ten agree. `tests/test_lpexec.py` recomputes every one of them from the name, so a typo
in a hex string is a test failure rather than a silent hole in the allowlist.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

# --------------------------------------------------------------------------------------
# Programs.
# --------------------------------------------------------------------------------------

DLMM_PROGRAM: Final[str] = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
COMPUTE_BUDGET_PROGRAM: Final[str] = "ComputeBudget111111111111111111111111111111"
ASSOCIATED_TOKEN_PROGRAM: Final[str] = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
TOKEN_PROGRAM: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SYSTEM_PROGRAM: Final[str] = "11111111111111111111111111111111"
MEMO_PROGRAM: Final[str] = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

WSOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"

ALLOWED_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        DLMM_PROGRAM,
        COMPUTE_BUDGET_PROGRAM,
        ASSOCIATED_TOKEN_PROGRAM,
        TOKEN_PROGRAM,
        TOKEN_2022_PROGRAM,
        SYSTEM_PROGRAM,
        MEMO_PROGRAM,
    }
)


def discriminator(name: str) -> str:
    """The Anchor discriminator for a snake_case instruction name, as lowercase hex."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8].hex()


# --------------------------------------------------------------------------------------
# DLMM instructions.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IxSpec:
    """One allowlisted DLMM instruction and where its checkable accounts sit.

    `lb_pair_index` and `position_index` are positions in the instruction's own account list.
    `signer_index` is the account that must equal our pubkey -- Meteora calls it `sender`,
    `owner`, or `payer` depending on the instruction. `None` means the instruction does not
    carry that account at all (`close_position2` names no pool; `initialize_bin_array` names
    no position and is permissionless, so it has no signer to check beyond the fee payer,
    which `guard.py` checks separately for every transaction).
    """

    name: str
    lb_pair_index: int | None
    position_index: int | None
    signer_index: int | None
    kind: str  # add | remove | claim | close | scaffold


_SPECS: Final[tuple[IxSpec, ...]] = (
    # Deposit. One-sided variants are the ladder; two-sided is a re-center.
    IxSpec("add_liquidity", 1, 0, 11, "add"),
    IxSpec("add_liquidity2", 1, 0, 9, "add"),
    IxSpec("add_liquidity_by_strategy", 1, 0, 11, "add"),
    IxSpec("add_liquidity_by_strategy2", 1, 0, 9, "add"),
    IxSpec("add_liquidity_by_strategy_one_side", 1, 0, 8, "add"),
    IxSpec("add_liquidity_by_weight", 1, 0, 11, "add"),
    IxSpec("add_liquidity_by_weight2", 1, 0, 9, "add"),
    IxSpec("add_liquidity_one_side", 1, 0, 8, "add"),
    IxSpec("add_liquidity_one_side_precise", 1, 0, 8, "add"),
    IxSpec("add_liquidity_one_side_precise2", 1, 0, 6, "add"),
    # Withdraw.
    IxSpec("remove_liquidity", 1, 0, 11, "remove"),
    IxSpec("remove_liquidity2", 1, 0, 9, "remove"),
    IxSpec("remove_liquidity_by_range", 1, 0, 11, "remove"),
    IxSpec("remove_liquidity_by_range2", 1, 0, 9, "remove"),
    IxSpec("remove_all_liquidity", 1, 0, 11, "remove"),
    # Fees.
    IxSpec("claim_fee", 0, 1, 4, "claim"),
    IxSpec("claim_fee2", 0, 1, 2, "claim"),
    # Teardown. Rent comes back here; see `rent.py`.
    IxSpec("close_position", 1, 0, 4, "close"),
    IxSpec("close_position2", None, 0, 1, "close"),
    IxSpec("close_position_if_empty", None, 0, 1, "close"),
    # Scaffolding a deposit cannot avoid.
    IxSpec("initialize_position", 2, 1, 3, "scaffold"),
    IxSpec("initialize_position2", 2, 1, 3, "scaffold"),
    IxSpec("initialize_bin_array", 0, None, None, "scaffold"),
    IxSpec("initialize_bin_array_bitmap_extension", 0, None, None, "scaffold"),
    IxSpec("increase_position_length", 1, 2, 3, "scaffold"),
    IxSpec("increase_position_length2", 1, 2, 3, "scaffold"),
)

ALLOWED_DLMM: Final[dict[str, IxSpec]] = {discriminator(spec.name): spec for spec in _SPECS}

# Named only so a refusal can say WHAT was refused. `go_to_a_bin` is on this list and is not
# a swap: it moves the pool's active bin, i.e. it re-prices the pool without trading, which
# is a market-manipulation primitive and has no place in an inventory tool. `rebalance_liquidity`
# is withdraw-and-redeposit in one instruction -- legitimate, but its effect on which bins hold
# what is not checkable from the instruction data alone, and the playbook does not need it.
# `place_limit_order` is Meteora's own single-bin ladder; it would be a reasonable future
# addition and is refused today because nothing has read its account layout.
_FORBIDDEN_NAMES: Final[tuple[str, ...]] = (
    "swap",
    "swap2",
    "swap_exact_out",
    "swap_exact_out2",
    "swap_with_price_impact",
    "swap_with_price_impact2",
    "go_to_a_bin",
    "rebalance_liquidity",
    "place_limit_order",
    "cancel_limit_order",
    "withdraw_protocol_fee",
    "zap_protocol_fee",
    "update_position_operator",
    "initialize_lb_pair",
    "initialize_lb_pair2",
    "initialize_customizable_permissionless_lb_pair",
    "initialize_customizable_permissionless_lb_pair2",
)

FORBIDDEN_DLMM: Final[dict[str, str]] = {discriminator(n): n for n in _FORBIDDEN_NAMES}

SWAP_DISCRIMINATORS: Final[frozenset[str]] = frozenset(
    discriminator(n)
    for n in (
        "swap",
        "swap2",
        "swap_exact_out",
        "swap_exact_out2",
        "swap_with_price_impact",
        "swap_with_price_impact2",
    )
)


# --------------------------------------------------------------------------------------
# Pools.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PoolSpec:
    address: str
    label: str
    token_x_mint: str
    token_y_mint: str
    bin_step: int
    note: str = ""

    @property
    def mints(self) -> frozenset[str]:
        return frozenset({self.token_x_mint, self.token_y_mint})


_WEAVE: Final[str] = "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"
_NOSIS: Final[str] = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"
_DREGG: Final[str] = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
_SOLVE: Final[str] = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"

# Every entry was read off chain on 2026-08-15 by decoding the `LbPair` account at the
# addresses below: `token_x_mint` at byte offset 88, `token_y_mint` at 120, `active_id` at 76,
# `bin_step` at 80. The two nosis/SOL pools are BOTH listed and only one is usable -- see the
# notes. Discovering them by `getProgramAccounts` rather than trusting a name search is what
# caught that the higher-bin-step one is a decoy with no liquidity in it.
_POOLS: Final[tuple[PoolSpec, ...]] = (
    PoolSpec(
        "48z2a9zvV7rBrMvwn3kE7vbwwiroiaaHm4rx1RwtksRF",
        "nosis/weave",
        _NOSIS,
        _WEAVE,
        200,
        "holds live position E829RTKuqZWXyvwYuJw9WS4LyaCjd1xrDGpYBDkuBpLP; the trim source",
    ),
    PoolSpec(
        "C889ex3M6dDecsxjAAudiLjhdeKgehbLm4zK9wV3nX8N",
        "nosis/SOL",
        _NOSIS,
        WSOL_MINT,
        100,
        "THE liquid nosis/SOL pool: 4.87M nosis + 61.4 SOL. The ask-ladder venue.",
    ),
    PoolSpec(
        "5dUNwg52DTb3S3PyM5tJJMuopGtk2JctioDRfE5dzbWY",
        "nosis/SOL (empty)",
        _NOSIS,
        WSOL_MINT,
        250,
        "EMPTY: 0 nosis, 8e-8 SOL, zero fees at every horizon. Allowlisted so a plan that "
        "names it is refused by the emptiness check with a reason, not by a missing entry.",
    ),
    PoolSpec(
        "9M1oU7cvRKiNo3e6iuCnApVe5RYehQ9RNv5dhtiKTrA7",
        "weave/SOLVE",
        _WEAVE,
        _SOLVE,
        200,
        "holds live position 5nn4dFA5NACTGemgfMMDXa2aDywy25XRgkYp6BCiJQrr",
    ),
    PoolSpec(
        "6RRecgQPELvZfoaDECEbsPQaR2WHnDQAPCvMPoFmsr3X", "weave/SOL", _WEAVE, WSOL_MINT, 200
    ),
    PoolSpec(
        "77Nm2cKtZfJvcQttySdqoZvH1mbxUkUWQwKsrpyvAebu", "weave/SOL", _WEAVE, WSOL_MINT, 100
    ),
    PoolSpec("QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD", "weave/nosis", _WEAVE, _NOSIS, 300),
    PoolSpec("5fJBZY6hCG3ykS2nNCJCXXrFtgcGSDByGccq4ucVea9i", "nosis/weave", _NOSIS, _WEAVE, 300),
    PoolSpec("FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD", "nosis/DREGG", _NOSIS, _DREGG, 200),
    PoolSpec("A8ga6XM3b8EQV1ZD4B5KJTATxKrZm6feKcodTwAogtRG", "weave/DREGG", _WEAVE, _DREGG, 20),
    PoolSpec("GxnCwxTiK1uNQ1GiNutopyaRxH9X14JEvh6uaMwxuDRM", "weave/DREGG", _WEAVE, _DREGG, 200),
    PoolSpec("HE9UXD4abY8dG1QEmyoZkSETZVScef3t2yZqhbWCT9aJ", "SOLVE/DREGG", _SOLVE, _DREGG, 125),
)

POOLS: Final[dict[str, PoolSpec]] = {pool.address: pool for pool in _POOLS}

# The wallet this package exists to manage. Written down so a transaction built for some
# other payer is refused rather than signed by whichever key happens to be on disk.
THA_FUNDS: Final[str] = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"


def pool_for(address: str) -> PoolSpec:
    try:
        return POOLS[address]
    except KeyError:
        raise KeyError(f"{address} is not an allowlisted lpexec pool") from None
