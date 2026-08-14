"""The cluster universe: six pools, verified against chain on 2026-08-13.

**The addresses were verified, not copied.** ``studies/RESULT_swing_cluster.md`` cites its
pool addresses to a session scratchpad, and that scratchpad
(``cluster_pools.py``/``cluster_pools.json``) has **weave and SOLVE transposed** against the
committed table: it labels ``8PecVcCG…`` as SOLVE and ``GwyWFsDK…`` as WEAVE, while the
RESULT table's own FDV/liquidity columns ($128k/$28k for weave, $44k/$16k for SOLVE) match
the opposite assignment. Rather than pick a side, every pool below was resolved on chain by
reading the mints of the token accounts the pool itself owns:

===========================================  ==========================  ============
pool                                         vault mints                 pair
===========================================  ==========================  ============
GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn 8PecVcCG… + So1111…112      weave / SOL
7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc FPfi9q1A… + So1111…112      nosis / SOL
2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU XkeTXo11… + So1111…112      DREGG / SOL
BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr GwyWFsDK… + So1111…112      SOLVE / SOL
QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD  8PecVcCG… + FPfi9q1A…       weave / nosis
FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD XkeTXo11… + FPfi9q1A…       DREGG / nosis
===========================================  ==========================  ============

That reproduces the prompt's pairing exactly and refutes the scratchpad's. The symbols below
are therefore *labels for humans*; nothing in the parser trusts them. Mints and decimals are
read from each transaction's token-balance records, and :func:`PoolSpec.mint_mismatch` turns a
disagreement between this table and the chain into a defect rather than a silent relabel.

**Vault discovery is protocol-agnostic and deliberately so.** A pool's vaults are exactly the
token accounts whose ``owner`` is the pool address, which is true of a PumpSwap AMM pool and
of a Meteora DLMM ``lb_pair`` alike. Hard-coding vault addresses per DEX would be a second
source of truth to keep in sync; reading the owner field is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Wrapped SOL. Both DEXes hold the "SOL" side of a pool as an SPL token account, so the SOL
#: leg of a swap shows up in ``pre/postTokenBalances`` like any other token and needs no
#: separate lamport reconstruction.
WSOL_MINT: Final[str] = "So11111111111111111111111111111111111111112"

PUMPSWAP_PROGRAM: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
METEORA_DLMM_PROGRAM: Final[str] = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"

#: Anchor instruction discriminators are ``sha256("global:" + snake_case_name)[:8]``, so this
#: table is *derived*, not scraped from an IDL that could drift. Verified against live data:
#: ``414b3f4ceb5b5b88`` decoded from a Meteora inner instruction is exactly ``global:swap2``.
#: A discriminator not in this table is recorded as raw hex — never guessed at.
KNOWN_DISCRIMINATORS: Final[dict[str, str]] = {
    # Meteora DLMM
    "f8c69e91e17587c8": "swap",
    "414b3f4ceb5b5b88": "swap2",
    "fa49652126cf4bb8": "swap_exact_out",
    "2bd7f784893cf351": "swap_exact_out2",
    "38ade6d0ade49ccd": "swap_with_price_impact",
    "4a62c0d6b1334b33": "swap_with_price_impact2",
    "b59d59438fb63448": "add_liquidity",
    "5055d14818ceb16c": "remove_liquidity",
    "cc02c391359191cd": "remove_liquidity_by_range2",
    "70bf65ab1c907fbb": "claim_fee2",
    # PumpSwap
    "66063d1201daebea": "buy",
    "33e685a4017f83ad": "sell",
    "c62e1552b4d9e870": "buy_exact_quote_in",
    "74e8b6e6c2ae1e5f": "sell_exact_base_in",
}


@dataclass(frozen=True, slots=True)
class PoolSpec:
    """One watched pool. ``mints`` is the expectation, chain is the authority."""

    address: str
    dex: str
    program: str
    label: str
    #: Expected vault mints, order-insensitive. Used only to detect a mis-specified address.
    mints: frozenset[str]
    #: True when the fill is an exact function of the two vault balances (constant product).
    #: False for a DLMM, whose fill depends on the active bin and the per-bin liquidity
    #: distribution, neither of which is recoverable from vault totals. See
    #: :mod:`shitcoims_cluster.parse`.
    replay_sufficient_reserves: bool

    @property
    def is_sol_quoted(self) -> bool:
        return WSOL_MINT in self.mints

    def mint_mismatch(self, observed: frozenset[str]) -> str | None:
        """Return a defect reason when the chain disagrees with this table, else ``None``."""

        if not observed:
            return None
        if not observed <= self.mints:
            unexpected = sorted(observed - self.mints)
            return f"pool {self.address} holds unexpected vault mints {unexpected}"
        return None


def _pumpswap(address: str, label: str, token_mint: str) -> PoolSpec:
    return PoolSpec(
        address=address,
        dex="pumpswap",
        program=PUMPSWAP_PROGRAM,
        label=label,
        mints=frozenset({token_mint, WSOL_MINT}),
        replay_sufficient_reserves=True,
    )


def _meteora(address: str, label: str, mint_a: str, mint_b: str) -> PoolSpec:
    return PoolSpec(
        address=address,
        dex="meteora_dlmm",
        program=METEORA_DLMM_PROGRAM,
        label=label,
        mints=frozenset({mint_a, mint_b}),
        replay_sufficient_reserves=False,
    )


WEAVE: Final[str] = "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"
NOSIS: Final[str] = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"
DREGG: Final[str] = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
SOLVE: Final[str] = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"

CLUSTER_POOLS: Final[tuple[PoolSpec, ...]] = (
    _pumpswap("GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn", "weave/SOL", WEAVE),
    _pumpswap("7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc", "nosis/SOL", NOSIS),
    _pumpswap("2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU", "DREGG/SOL", DREGG),
    _pumpswap("BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr", "SOLVE/SOL", SOLVE),
    _meteora("QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD", "weave/nosis", WEAVE, NOSIS),
    _meteora("FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD", "DREGG/nosis", DREGG, NOSIS),
    # Added 2026-08-13: the network map found this one by resolving the LP wallet from the
    # tape's own claim_fee payer and asking the Meteora API what else it holds. It is an edge
    # WE PROVIDE LIQUIDITY TO that the recorder was not watching — so its flow rendered as
    # "not watching", an unknown rather than a zero. An unwatched edge of ours is the worst
    # blind spot available: we earn the diode drop on it and could not see the current.
    _meteora("77Nm2cKtZfJvcQttySdqoZvH1mbxUkUWQwKsrpyvAebu", "weave/SOL (DLMM)", WEAVE, WSOL_MINT),
    # Added 2026-08-14: the edge-creation study found four MORE pools the desk has opened or
    # traded that this table did not contain — the same blind spot as the weave/SOL DLMM above,
    # four times over. Pair and fee tier resolved from the Meteora pool API per address.
    # A8ga6XM3 is the instructive one: weave/DREGG at 0.20%, eleven times CHEAPER than the
    # two-hop route it was meant to undercut, and it captured zero direct trades and now shows
    # no volume. Cheapness is not what makes a token-token pool earn.
    _meteora("5fJBZY6hCG3ykS2nNCJCXXrFtgcGSDByGccq4ucVea9i", "nosis/weave (2nd)", NOSIS, WEAVE),
    _meteora("9M1oU7cvRKiNo3e6iuCnApVe5RYehQ9RNv5dhtiKTrA7", "weave/SOLVE", WEAVE, SOLVE),
    _meteora("A8ga6XM3b8EQV1ZD4B5KJTATxKrZm6feKcodTwAogtRG", "weave/DREGG (0.2%)", WEAVE, DREGG),
    _meteora("GxnCwxTiK1uNQ1GiNutopyaRxH9X14JEvh6uaMwxuDRM", "weave/DREGG (5%)", WEAVE, DREGG),
)

POOLS_BY_ADDRESS: Final[dict[str, PoolSpec]] = {p.address: p for p in CLUSTER_POOLS}


def pool_for(address: str) -> PoolSpec:
    try:
        return POOLS_BY_ADDRESS[address]
    except KeyError:
        raise KeyError(f"{address} is not a cluster pool") from None
