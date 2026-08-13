"""Project public ClaudeKOL actions into advisory Observation records.

This module is a pure mapper. It does not reach the network, sign, or
submit anything. The parent runtime will import it later.
"""

from __future__ import annotations

from shitcoims_intelligence.adapters.claudekol import (
    ADAPTER_VERSION,
    CANONICAL_WALLET,
    SOURCE_ID,
    ClaudeKolAction,
    ClaudeKolBatch,
)
from shitcoims_intelligence.models import Finality, Observation

CLAIM_KIND = "claudekol_claim"
VERIFIED_CONFIDENCE = 0.3
UNVERIFIED_CONFIDENCE = 0.15


def _observation_from_action(action: ClaudeKolAction) -> Observation:
    mint = action.canonical_mint
    title = action.title_claim
    return Observation(
        source_id=SOURCE_ID,
        source_native_id=action.source_event_id,
        kind=CLAIM_KIND,
        subject_type="token" if mint else "wallet",
        subject_id=mint or CANONICAL_WALLET,
        observed_at=action.source_created_at,
        emitted_at=action.provenance.observed_at,
        payload={
            "title": title,
            "summary": title,
            "mint": mint,
            "signature": action.canonical_signature,
            "conflicts": list(action.conflicts),
            "independently_verified": action.independently_verified,
            "classification": "claim",
            "severity": "info",
            "status": "observed",
        },
        confidence=(
            VERIFIED_CONFIDENCE if action.independently_verified else UNVERIFIED_CONFIDENCE
        ),
        finality=Finality.UNVERIFIED,
        parser_version=ADAPTER_VERSION,
        provenance=(action.provenance.source_url,),
    )


def observations_from_batch(batch: ClaudeKolBatch) -> tuple[Observation, ...]:
    """One unverified claim Observation per public action.

    Independent chain corroboration only raises confidence. It never changes
    finality and never implies execution. Quarantined rows stay out.
    """

    return tuple(_observation_from_action(action) for action in batch.actions)
