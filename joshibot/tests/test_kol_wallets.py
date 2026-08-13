from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from shitcoims_intelligence.config import KolWatchConfig
from shitcoims_intelligence.helius import WatchlistSnapshot
from shitcoims_intelligence.kol_wallets import (
    KOL_WALLET_CLAIM_CONFIDENCE,
    KOL_WALLET_CLAIM_KIND,
    KOL_WALLET_PRIORITY,
    KOL_WALLET_SOURCE_ID,
    KOL_WALLET_WATCHLIST_ID,
    observations_for_declared_wallets,
    wallets_from_kols,
    watch_entries_for_kols,
    watchlist,
)
from shitcoims_intelligence.models import Finality

NOW = datetime(2026, 8, 12, 15, tzinfo=UTC)
SYSTEM = "11111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"
COMPUTE = "ComputeBudget111111111111111111111111111111"


def kol(handle: str, wallet: str | None, *, label: str | None = None, notes: str = "") -> KolWatchConfig:
    return KolWatchConfig(
        handle=handle,
        label=label or handle,
        wallet=wallet,
        follow_replies=False,
        max_items=8,
        notes=notes,
    )


def test_module_is_advisory_and_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import kol_wallets

    source = inspect.getsource(kol_wallets)
    assert "shitcoims_sentinel.executor" not in source
    assert "shitcoims_sentinel" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source


def test_wallets_from_kols_skips_nulls_and_dedupes_in_first_seen_order() -> None:
    kols = (
        kol("threadguy", None),
        kol("blknoiz06", SYSTEM, label="Ansem"),
        kol("A1lon9", f"  {WSOL}  "),
        kol("MustStopMurad", SYSTEM),
        kol("empty", ""),
        kol("blank", "   "),
    )

    assert wallets_from_kols(kols) == (SYSTEM, WSOL)


def test_wallets_from_kols_rejects_ambiguous_base58_and_wrong_length() -> None:
    too_short = "1" * 31
    too_long = "1" * 45
    for bad in (
        too_short,
        too_long,
        "0" + "1" * 31,
        "O" + "1" * 31,
        "I" + "1" * 31,
        "l" + "1" * 31,
        "not a solana address!!!!!!!!!!!!!!",
        SYSTEM[:-1] + "+",
    ):
        with pytest.raises(ValueError, match="base58"):
            wallets_from_kols((kol("badwallet", bad),))


def test_wallets_from_kols_rejects_base58_that_is_not_a_pubkey() -> None:
    # 32 valid base58 glyphs that do not decode to a 32-byte public key.
    with pytest.raises(ValueError, match="base58"):
        wallets_from_kols((kol("notakey", "x" * 32),))


def test_watch_entries_project_unique_wallets_with_claim_reason() -> None:
    kols = (
        kol("blknoiz06", SYSTEM, label="Ansem"),
        kol("threadguy", None),
        kol("A1lon9", WSOL),
        kol("MustStopMurad", SYSTEM),
    )

    entries = watch_entries_for_kols(kols, now=NOW)

    assert len(entries) == 2
    first, second = entries
    assert first.watchlist_id == KOL_WALLET_WATCHLIST_ID
    assert first.subject_type == "wallet"
    assert first.subject_id == SYSTEM
    assert first.reason == "kol @blknoiz06 declared wallet"
    assert first.added_at == NOW
    assert first.expires_at is None
    assert first.discovery_observation_id is None
    assert first.priority == KOL_WALLET_PRIORITY == 60
    assert second.subject_id == WSOL
    assert second.reason == "kol @A1lon9 declared wallet"
    assert second.priority == 60


def test_watchlist_uses_stable_id_and_aware_timestamp() -> None:
    item = watchlist(NOW)

    assert item.watchlist_id == KOL_WALLET_WATCHLIST_ID == "kol-wallets"
    assert item.name == "KOL declared wallets"
    assert "claim" in item.description.lower()
    assert item.max_entries == 2_000
    assert item.created_at == NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        watchlist(datetime(2026, 8, 12, 15))


def test_observations_are_low_confidence_wallet_claims() -> None:
    kols = (
        kol("blknoiz06", SYSTEM, label="Ansem", notes="cashtags are claims"),
        kol("threadguy", None),
        kol("MustStopMurad", SYSTEM),
    )

    records = observations_for_declared_wallets(kols, now=NOW)

    assert len(records) == 2
    first, second = records
    assert first.source_id == KOL_WALLET_SOURCE_ID == "kol_config_v1"
    assert first.source_native_id == f"blknoiz06:{SYSTEM}"
    assert first.kind == KOL_WALLET_CLAIM_KIND == "kol_wallet_claim"
    assert first.subject_type == "wallet"
    assert first.subject_id == SYSTEM
    assert first.observed_at == NOW
    assert first.confidence == KOL_WALLET_CLAIM_CONFIDENCE == 0.2
    assert first.finality is Finality.UNVERIFIED
    assert first.payload["handle"] == "blknoiz06"
    assert first.payload["label"] == "Ansem"
    assert first.payload["wallet"] == SYSTEM
    assert first.payload["notes"] == "cashtags are claims"
    assert first.payload["classification"] == "claim"
    assert second.source_native_id == f"MustStopMurad:{SYSTEM}"
    assert second.subject_id == SYSTEM
    assert second.payload["handle"] == "MustStopMurad"


def test_declared_wallets_are_helius_snapshot_subjects() -> None:
    kols = (kol("blknoiz06", SYSTEM), kol("A1lon9", WSOL), kol("budget", COMPUTE))
    addresses = wallets_from_kols(kols)

    snapshot = WatchlistSnapshot("kol-wallets-v1", addresses)
    assert snapshot.addresses == (SYSTEM, WSOL, COMPUTE)


def test_empty_kols_produce_empty_projections() -> None:
    assert wallets_from_kols(()) == ()
    assert watch_entries_for_kols((), now=NOW) == ()
    assert observations_for_declared_wallets((), now=NOW) == ()
