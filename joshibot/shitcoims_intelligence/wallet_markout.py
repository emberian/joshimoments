"""Advisory wallet markout / SOL-flow summary from stored observations.

This module is deliberately advisory.  It reads already-stored
``wallet_transaction`` payloads (see ``collector.wallet_transaction_observation``)
and folds them into a desk-facing count.  It does not import the sentinel
executor, read a keypair, quote, sign, or submit anything.

Failed transactions are excluded from ``net_sol``: they are not fills, and their
only typical SOL impact is the network fee, which is already reported in
``fees_sol``.  Fees are summed whenever ``fee_lamports`` is present, succeeded or
not.  ``net_sol`` is the succeeded-tx lamport sum divided by 1e9 only when every
succeeded observation has ``sol_delta_exact is True`` and an integer
``sol_delta_lamports``; otherwise it is ``None``.  Inputs are not deduplicated.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from shitcoims_intelligence.models import Observation, StoredObservation, thaw_json

LAMPORTS_PER_SOL = 1_000_000_000

_OBSERVATION_TYPES = (Observation, StoredObservation)


@dataclass(frozen=True, slots=True)
class WalletMarkout:
    wallet: str
    tx_count: int
    succeeded: int
    net_sol: float | None  # lamports/1e9 if all succeeded sol_delta_exact else None
    fees_sol: float
    token_mints_touched: int
    last_slot: int | None


def summarize(
    wallet: str,
    observations: Sequence[Observation | StoredObservation | Mapping[str, Any]],
) -> WalletMarkout:
    """Fold wallet_transaction observations or thawed payloads into a markout.

    ``observations`` may be ``Observation`` / ``StoredObservation`` records
    (payload is thawed) or already-thawed collector payload dicts.  Failed
    transactions count toward ``tx_count``, ``fees_sol``, ``token_mints_touched``,
    and ``last_slot``, but not ``net_sol``.
    """

    if not isinstance(wallet, str):
        raise TypeError("wallet must be a string")

    tx_count = 0
    succeeded_count = 0
    net_lamports = 0
    net_exact = True
    fee_lamports_total = 0
    mints: set[str] = set()
    last_slot: int | None = None

    for item in observations:
        payload = _as_payload(item)
        tx_count += 1

        slot = payload.get("slot")
        if _is_int(slot):
            last_slot = slot if last_slot is None else max(last_slot, slot)

        fee_lamports = payload.get("fee_lamports")
        if _is_int(fee_lamports):
            fee_lamports_total += fee_lamports

        for mint in _token_mints(payload.get("token_deltas")):
            mints.add(mint)

        if payload.get("succeeded") is not True:
            continue
        succeeded_count += 1

        sol_delta = payload.get("sol_delta_lamports")
        if payload.get("sol_delta_exact") is not True or not _is_int(sol_delta):
            net_exact = False
            continue
        net_lamports += sol_delta

    return WalletMarkout(
        wallet=wallet,
        tx_count=tx_count,
        succeeded=succeeded_count,
        net_sol=(net_lamports / LAMPORTS_PER_SOL) if net_exact else None,
        fees_sol=fee_lamports_total / LAMPORTS_PER_SOL,
        token_mints_touched=len(mints),
        last_slot=last_slot,
    )


def _as_payload(item: object) -> Mapping[str, Any]:
    if isinstance(item, _OBSERVATION_TYPES):
        payload = thaw_json(item.payload)
    elif isinstance(item, Mapping):
        payload = thaw_json(item)
    else:
        raise TypeError(
            "observations must be Observation records or thawed wallet_transaction payloads"
        )
    if not isinstance(payload, Mapping):
        raise TypeError("wallet_transaction payload must be a mapping")
    return payload


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _token_mints(token_deltas: object) -> tuple[str, ...]:
    if not isinstance(token_deltas, list | tuple):
        return ()
    mints: list[str] = []
    for delta in token_deltas:
        if not isinstance(delta, Mapping):
            continue
        mint = delta.get("mint")
        if isinstance(mint, str) and mint:
            mints.append(mint)
    return tuple(mints)
