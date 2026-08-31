from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from shitcoims_intelligence.models import (
    Finality,
    Observation,
    StoredObservation,
)
from shitcoims_intelligence.wallet_markout import (
    LAMPORTS_PER_SOL,
    WalletMarkout,
    summarize,
)

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
WALLET = "11111111111111111111111111111111"
MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def payload(
    *,
    signature: str = "sig",
    slot: int = 10,
    succeeded: bool = True,
    fee_lamports: int | None = 5_000,
    sol_delta_lamports: int | None = -1_000_005_000,
    sol_delta_exact: bool = True,
    token_deltas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "signature": signature,
        "slot": slot,
        "succeeded": succeeded,
        "fee_lamports": fee_lamports,
        "sol_delta_lamports": sol_delta_lamports,
        "sol_delta_exact": sol_delta_exact,
        "token_deltas": (
            [{"mint": MINT_A, "raw_delta": 100, "decimals": 6}]
            if token_deltas is None
            else token_deltas
        ),
    }


def observation(native_id: str = "sig:wallet", **fields: Any) -> Observation:
    return Observation(
        source_id="helius",
        source_native_id=native_id,
        kind="wallet_transaction",
        subject_type="wallet",
        subject_id=WALLET,
        observed_at=NOW,
        payload=payload(**fields),
        confidence=1.0,
        finality=Finality.FINALIZED,
        parser_version="helius-v1",
    )


def stored(**fields: Any) -> StoredObservation:
    body = payload(**fields)
    return StoredObservation(
        sequence=1,
        observation_id="obs_wallet_tx_1",
        event_key="helius:sig:wallet",
        source_id="helius",
        source_native_id="sig:wallet",
        kind="wallet_transaction",
        subject_type="wallet",
        subject_id=WALLET,
        observed_at=NOW,
        emitted_at=NOW,
        payload=body,
        content_hash="a" * 64,
        confidence=1.0,
        finality=Finality.FINALIZED,
        parser_version="helius-v1",
        provenance=("helius:getTransactionsForAddress",),
        retention_class="chain_evidence",
    )


def test_module_is_advisory_and_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import wallet_markout

    source = inspect.getsource(wallet_markout)
    assert "shitcoims_sentinel.executor" not in source
    assert "shitcoims_sentinel" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source


def test_summarize_thawed_payloads_sums_exact_succeeded_sol_and_fees() -> None:
    observations = [
        payload(
            signature="buy",
            slot=11,
            sol_delta_lamports=-1_000_000_000,
            token_deltas=[{"mint": MINT_A, "raw_delta": 100, "decimals": 6}],
        ),
        payload(
            signature="sell",
            slot=20,
            fee_lamports=7_000,
            sol_delta_lamports=500_000_000,
            token_deltas=[{"mint": MINT_A, "raw_delta": -50, "decimals": 6}],
        ),
    ]

    result = summarize(WALLET, observations)

    assert result.wallet == WALLET
    assert result.tx_count == 2
    assert result.succeeded == 2
    assert result.net_sol == pytest.approx(-0.5)
    assert result.fees_sol == pytest.approx(12_000 / LAMPORTS_PER_SOL)
    assert result.token_mints_touched == 1
    assert result.last_slot == 20


def test_summarize_reads_observation_payloads_and_stored_records() -> None:
    mixed = [
        observation(native_id="buy:wallet", signature="buy", slot=4, sol_delta_lamports=-2_000_000_000),
        stored(signature="sell", slot=9, fee_lamports=9_000, sol_delta_lamports=1_500_000_000),
        payload(signature="tip", slot=7, sol_delta_lamports=-1_000_000, token_deltas=[]),
    ]

    result = summarize(WALLET, mixed)

    assert result.tx_count == 3
    assert result.succeeded == 3
    assert result.net_sol == pytest.approx(-501_000_000 / LAMPORTS_PER_SOL)
    assert result.fees_sol == pytest.approx(19_000 / LAMPORTS_PER_SOL)
    assert result.token_mints_touched == 1
    assert result.last_slot == 9


def test_failed_transactions_are_excluded_from_net_sol_but_fees_still_count() -> None:
    observations = [
        payload(signature="fill", slot=5, sol_delta_lamports=-1_000_000_000, fee_lamports=5_000),
        payload(
            signature="fail",
            slot=8,
            succeeded=False,
            fee_lamports=8_000,
            sol_delta_lamports=-8_000,
            sol_delta_exact=True,
            token_deltas=[{"mint": MINT_B, "raw_delta": 0, "decimals": 6}],
        ),
    ]

    result = summarize(WALLET, observations)

    assert result.tx_count == 2
    assert result.succeeded == 1
    # Failed fill is not a trade: its -8000 lamports do not enter net_sol.
    assert result.net_sol == pytest.approx(-1.0)
    assert result.fees_sol == pytest.approx(13_000 / LAMPORTS_PER_SOL)
    assert result.token_mints_touched == 2
    assert result.last_slot == 8


def test_inexact_succeeded_sol_delta_nulls_net_sol_without_dropping_counts() -> None:
    observations = [
        payload(signature="exact", slot=1, sol_delta_lamports=-100_000_000),
        payload(
            signature="partial",
            slot=3,
            sol_delta_lamports=-50_000_000,
            sol_delta_exact=False,
        ),
    ]

    result = summarize(WALLET, observations)

    assert result.tx_count == 2
    assert result.succeeded == 2
    assert result.net_sol is None
    assert result.fees_sol == pytest.approx(10_000 / LAMPORTS_PER_SOL)
    assert result.last_slot == 3


def test_failed_inexact_delta_does_not_taint_succeeded_net_sol() -> None:
    observations = [
        payload(signature="fill", slot=2, sol_delta_lamports=250_000_000),
        payload(
            signature="fail",
            slot=1,
            succeeded=False,
            sol_delta_exact=False,
            sol_delta_lamports=None,
            fee_lamports=4_000,
            token_deltas=[],
        ),
    ]

    result = summarize(WALLET, observations)

    assert result.succeeded == 1
    assert result.net_sol == pytest.approx(0.25)
    assert result.fees_sol == pytest.approx(9_000 / LAMPORTS_PER_SOL)
    assert result.last_slot == 2


def test_missing_fee_lamports_is_skipped_and_missing_exact_delta_nulls_net_sol() -> None:
    observations = [
        payload(signature="no-fee", fee_lamports=None, sol_delta_lamports=-10),
        payload(
            signature="no-delta",
            slot=12,
            fee_lamports=1_000,
            sol_delta_lamports=None,
            sol_delta_exact=True,
            token_deltas=[],
        ),
    ]

    result = summarize(WALLET, observations)

    assert result.tx_count == 2
    assert result.succeeded == 2
    assert result.net_sol is None
    assert result.fees_sol == pytest.approx(1_000 / LAMPORTS_PER_SOL)
    assert result.token_mints_touched == 1
    assert result.last_slot == 12


def test_empty_observations_are_an_exact_zero_summary() -> None:
    result = summarize(WALLET, [])

    assert result == WalletMarkout(
        wallet=WALLET,
        tx_count=0,
        succeeded=0,
        net_sol=0.0,
        fees_sol=0.0,
        token_mints_touched=0,
        last_slot=None,
    )


def test_unique_mints_and_missing_slots() -> None:
    observations = [
        payload(
            signature="a",
            slot=None,  # type: ignore[arg-type]
            token_deltas=[
                {"mint": MINT_A, "raw_delta": 1, "decimals": 6},
                {"mint": MINT_B, "raw_delta": -1, "decimals": 6},
                {"mint": MINT_A, "raw_delta": 2, "decimals": 6},
                {"raw_delta": 3, "decimals": 6},
            ],
        ),
        payload(signature="b", slot=3, token_deltas=[{"mint": MINT_B, "raw_delta": 4, "decimals": 6}]),
    ]

    result = summarize(WALLET, observations)

    assert result.token_mints_touched == 2
    assert result.last_slot == 3


def test_markout_is_frozen() -> None:
    result = summarize(WALLET, [payload()])
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.tx_count = 99  # type: ignore[misc]


def test_summarize_rejects_non_payload_items() -> None:
    with pytest.raises(TypeError, match="Observation"):
        summarize(WALLET, [object()])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="wallet"):
        summarize(12, [])  # type: ignore[arg-type]
