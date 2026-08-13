from __future__ import annotations

from shitcoims_intelligence.candidates import EXECUTION_EFFECT, build_candidates
from shitcoims_intelligence.sieve import VERDICT_VETO

MINT = "So11111111111111111111111111111111111111112"


def test_mint_tape_whale_holder_vetoes() -> None:
    cards = build_candidates(
        observations=[
            {
                "kind": "mint_tape",
                "subject_type": "token",
                "subject_id": MINT,
                "payload": {
                    "mint": MINT,
                    "holder_count": 8,
                    "holder_top1": 0.5,
                    "holder_hhi": 0.3,
                    "holder_nakamoto": 2,
                },
            }
        ]
    )
    assert cards
    assert cards[0]["mint"] == MINT
    assert cards[0]["verdict"] == VERDICT_VETO
    assert cards[0]["execution_effect"] == EXECUTION_EFFECT
    assert cards[0]["execution_effect"] == "none"
