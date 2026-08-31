from __future__ import annotations

import inspect
from datetime import UTC, datetime

from solders.pubkey import Pubkey
from solders.signature import Signature

from shitcoims_intelligence.adapters.claudekol import (
    ADAPTER_VERSION,
    ClaudeKolAction,
    ClaudeKolBatch,
)
from shitcoims_intelligence.adapters.common import QuarantinedRecord, SourceProvenance
from shitcoims_intelligence.claudekol_collect import (
    CANONICAL_WALLET,
    CLAIM_KIND,
    SOURCE_ID,
    UNVERIFIED_CONFIDENCE,
    VERIFIED_CONFIDENCE,
    observations_from_batch,
)
from shitcoims_intelligence.models import Finality

NOW = datetime(2026, 8, 12, 18, 8, 23, tzinfo=UTC)
MINT = str(Pubkey.new_unique())
SIGNATURE = str(Signature.default())


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_id=SOURCE_ID,
        source_url="https://claudekol.fun/",
        endpoint_family="public SPA Supabase actions select",
        adapter_version=ADAPTER_VERSION,
        contract_status="reverse_engineered_public_client_unstable",
        observed_at=NOW,
    )


def _action(**overrides: object) -> ClaudeKolAction:
    values: dict[str, object] = {
        "source_event_id": "11111111-1111-4111-8111-111111111111",
        "source_created_at": NOW,
        "kind": "trade_open",
        "title_claim": "APED $GOOD",
        "body_claim": "untrusted narrative",
        "symbol_claim": "GOOD",
        "mint_claim": MINT,
        "canonical_mint": MINT,
        "signature_claim": SIGNATURE,
        "canonical_signature": SIGNATURE,
        "nominal_sol_claim": 1.25,
        "nominal_usd_claim": None,
        "allocation_pct_claim": 4.0,
        "multiple_claim": None,
        "callout_url_claim": None,
        "verification": None,
        "independently_verified": False,
        "conflicts": (),
        "provenance": _provenance(),
    }
    values.update(overrides)
    return ClaudeKolAction(**values)  # type: ignore[arg-type]


def _batch(
    *actions: ClaudeKolAction,
    quarantined: tuple[QuarantinedRecord, ...] = (),
) -> ClaudeKolBatch:
    return ClaudeKolBatch(actions, quarantined, _provenance())


def test_module_is_advisory_and_has_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence import claudekol_collect

    source = inspect.getsource(claudekol_collect)
    assert "shitcoims_sentinel" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source
    assert "cookie" not in source
    assert "session" not in source
    assert "executor" not in source


def test_source_constants_match_the_public_adapter() -> None:
    from shitcoims_intelligence.adapters import claudekol

    assert SOURCE_ID == claudekol.SOURCE_ID == "claudekol_public_actions"
    assert CANONICAL_WALLET == claudekol.CANONICAL_WALLET
    assert CANONICAL_WALLET == "6s5RoARKg1oc4eWvGof1FwTzPuPLkToP4iS1N4Mgqvz"


def test_verified_mint_action_is_a_token_subject_at_higher_confidence() -> None:
    records = observations_from_batch(
        _batch(_action(independently_verified=True, conflicts=("label_claim_conflict:$GOOD,$OTHER",)))
    )

    assert len(records) == 1
    observation = records[0]
    assert observation.source_id == SOURCE_ID
    assert observation.source_native_id == "11111111-1111-4111-8111-111111111111"
    assert observation.kind == CLAIM_KIND == "claudekol_claim"
    assert observation.subject_type == "token"
    assert observation.subject_id == MINT
    assert observation.observed_at == NOW
    assert observation.emitted_at == NOW
    assert observation.confidence == VERIFIED_CONFIDENCE == 0.3
    assert observation.finality is Finality.UNVERIFIED
    assert observation.parser_version == ADAPTER_VERSION
    assert observation.payload["title"] == "APED $GOOD"
    assert observation.payload["summary"] == "APED $GOOD"
    assert observation.payload["mint"] == MINT
    assert observation.payload["signature"] == SIGNATURE
    assert tuple(observation.payload["conflicts"]) == ("label_claim_conflict:$GOOD,$OTHER",)
    assert observation.payload["independently_verified"] is True


def test_unverified_action_without_mint_uses_canonical_wallet() -> None:
    records = observations_from_batch(
        _batch(
            _action(
                source_event_id="22222222-2222-4222-8222-222222222222",
                kind="speech_adjacent",
                title_claim="watching the wallet",
                body_claim="",
                symbol_claim=None,
                mint_claim=None,
                canonical_mint=None,
                signature_claim=None,
                canonical_signature=None,
                independently_verified=False,
            )
        )
    )

    assert len(records) == 1
    observation = records[0]
    assert observation.subject_type == "wallet"
    assert observation.subject_id == CANONICAL_WALLET
    assert observation.confidence == UNVERIFIED_CONFIDENCE == 0.15
    assert observation.finality is Finality.UNVERIFIED
    assert observation.payload["title"] == "watching the wallet"
    assert observation.payload["summary"] == "watching the wallet"
    assert observation.payload["mint"] is None
    assert observation.payload["signature"] is None
    assert observation.payload["conflicts"] == ()
    assert observation.payload["independently_verified"] is False


def test_finality_stays_unverified_when_the_chain_claim_was_corroborated() -> None:
    records = observations_from_batch(_batch(_action(independently_verified=True)))

    assert records[0].payload["independently_verified"] is True
    assert records[0].finality is Finality.UNVERIFIED
    assert records[0].finality.value == "unverified"
    assert records[0].confidence == 0.3


def test_can_execute_never_appears_as_true() -> None:
    records = observations_from_batch(
        _batch(_action(independently_verified=True, can_execute=True))
    )

    observation = records[0]
    assert not hasattr(observation, "can_execute") or observation.can_execute is False
    assert observation.payload.get("can_execute") is not True
    assert "can_execute" not in observation.payload


def test_quarantined_rows_are_not_observations() -> None:
    quarantined = QuarantinedRecord(
        source_id=SOURCE_ID,
        source_event_id="33333333-3333-4333-8333-333333333333",
        reason="schema_or_identity_drift:invalid_mint_claim",
        fingerprint="deadbeef",
    )
    records = observations_from_batch(_batch(quarantined=(quarantined,)))

    assert records == ()


def test_empty_batch_is_empty() -> None:
    assert observations_from_batch(_batch()) == ()


def test_batch_preserves_action_order() -> None:
    first = _action(source_event_id="11111111-1111-4111-8111-111111111111")
    second = _action(
        source_event_id="22222222-2222-4222-8222-222222222222",
        independently_verified=True,
    )
    records = observations_from_batch(_batch(first, second))

    assert [item.source_native_id for item in records] == [
        first.source_event_id,
        second.source_event_id,
    ]
    assert [item.confidence for item in records] == [0.15, 0.3]
