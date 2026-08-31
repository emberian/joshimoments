"""Declared KOL wallets as advisory watch entries and Helius subjects.

A ``KolWatchConfig.wallet`` is an optional claim that a configured X handle
owns a Solana address.  This module projects those claims into the storage
watchlist contract and a unique address tuple that a Helius
``WatchlistSnapshot`` can accept.  Ownership is never verified here.

The module is deliberately advisory.  It has no network, keypair, or executor
dependency, and it never signs or submits anything.
"""

from __future__ import annotations

import re
from datetime import datetime

from solders.pubkey import Pubkey

from shitcoims_intelligence.config import KolWatchConfig
from shitcoims_intelligence.models import Finality, Observation, WatchEntry, Watchlist

KOL_WALLET_WATCHLIST_ID = "kol-wallets"
KOL_WALLET_SOURCE_ID = "kol_config_v1"
KOL_WALLET_CLAIM_KIND = "kol_wallet_claim"
KOL_WALLET_PARSER_VERSION = "kol_config_v1"
KOL_WALLET_PRIORITY = 60
KOL_WALLET_CLAIM_CONFIDENCE = 0.2

# Bitcoin-style base58: digits 0, O, I, and l are excluded because they are
# visually ambiguous.  Length matches a Solana public key encoding.
_WALLET_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _optional_wallet(wallet: str | None) -> str | None:
    if wallet is None:
        return None
    candidate = wallet.strip()
    if not candidate:
        return None
    return _validate_wallet(candidate)


def _validate_wallet(wallet: str) -> str:
    if not _WALLET_RE.fullmatch(wallet):
        raise ValueError("KOL wallet must be a 32-44 character base58 Solana address")
    try:
        Pubkey.from_string(wallet)
    except ValueError:
        raise ValueError("KOL wallet must be a 32-44 character base58 Solana address") from None
    return wallet


def _declared(kols: tuple[KolWatchConfig, ...]) -> tuple[tuple[KolWatchConfig, str], ...]:
    declared: list[tuple[KolWatchConfig, str]] = []
    for kol in kols:
        wallet = _optional_wallet(kol.wallet)
        if wallet is not None:
            declared.append((kol, wallet))
    return tuple(declared)


def wallets_from_kols(kols: tuple[KolWatchConfig, ...]) -> tuple[str, ...]:
    """Unique non-null declared wallets, first-seen order, Helius-ready."""

    unique: list[str] = []
    seen: set[str] = set()
    for _kol, wallet in _declared(kols):
        if wallet in seen:
            continue
        seen.add(wallet)
        unique.append(wallet)
    return tuple(unique)


def watchlist(now: datetime) -> Watchlist:
    """Stable catalog for declared KOL wallets.  Empty until entries are added."""

    return Watchlist(
        watchlist_id=KOL_WALLET_WATCHLIST_ID,
        name="KOL declared wallets",
        description=(
            "Optional Solana addresses declared on configured KOL watches. "
            "Each address is a claim that the handle owns that wallet, not a "
            "chain-verified identity."
        ),
        max_entries=2_000,
        created_at=now,
    )


def watch_entries_for_kols(
    kols: tuple[KolWatchConfig, ...],
    *,
    now: datetime,
) -> tuple[WatchEntry, ...]:
    """One wallet watch per unique declared address.  First handle keeps the reason."""

    entries: list[WatchEntry] = []
    seen: set[str] = set()
    for kol, wallet in _declared(kols):
        if wallet in seen:
            continue
        seen.add(wallet)
        entries.append(
            WatchEntry(
                watchlist_id=KOL_WALLET_WATCHLIST_ID,
                subject_type="wallet",
                subject_id=wallet,
                reason=f"kol @{kol.handle} declared wallet",
                added_at=now,
                expires_at=None,
                discovery_observation_id=None,
                priority=KOL_WALLET_PRIORITY,
            )
        )
    return tuple(entries)


def observations_for_declared_wallets(
    kols: tuple[KolWatchConfig, ...],
    *,
    now: datetime,
) -> tuple[Observation, ...]:
    """One low-confidence claim per handle that declared a wallet.

    Config is the source.  The fact recorded is only that the operator attached
    this address to this handle, not that the handle controls it.
    """

    records: list[Observation] = []
    for kol, wallet in _declared(kols):
        records.append(
            Observation(
                source_id=KOL_WALLET_SOURCE_ID,
                source_native_id=f"{kol.handle}:{wallet}",
                kind=KOL_WALLET_CLAIM_KIND,
                subject_type="wallet",
                subject_id=wallet,
                observed_at=now,
                payload={
                    "title": f"declared wallet for @{kol.handle}",
                    "summary": f"{kol.label} wallet claim {wallet}",
                    "handle": kol.handle,
                    "label": kol.label,
                    "wallet": wallet,
                    "notes": kol.notes,
                    "classification": "claim",
                    "severity": "info",
                    "status": "observed",
                },
                confidence=KOL_WALLET_CLAIM_CONFIDENCE,
                finality=Finality.UNVERIFIED,
                parser_version=KOL_WALLET_PARSER_VERSION,
                provenance=(f"config:kol:{kol.handle}",),
            )
        )
    return tuple(records)
