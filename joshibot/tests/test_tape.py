from __future__ import annotations

import inspect

from shitcoims_intelligence import tape
from shitcoims_intelligence.numerics import concentration, holder_veto
from shitcoims_intelligence.sieve import VERDICT_VETO, holder_verdict, organic_verdict
from shitcoims_intelligence.tape import (
    features_from_prints,
    holder_features,
    prints_from_enhanced_tx,
    prints_from_history_tx,
    prints_from_wallet_payload,
)

MINT = "So11111111111111111111111111111111111111112"


def test_wallet_payload_buy_and_sell_become_prints() -> None:
    buys = prints_from_wallet_payload(
        {
            "succeeded": True,
            "slot": 10,
            "sol_delta_lamports": -100_000_000,
            "token_deltas": [{"mint": MINT, "raw_delta": 1_000_000, "decimals": 6}],
        },
        wallet="WalletA",
    )
    assert len(buys) == 1
    assert buys[0].side == "buy"
    assert buys[0].quote_sol == 0.1
    sells = prints_from_wallet_payload(
        {
            "succeeded": True,
            "slot": 11,
            "sol_delta_lamports": 50_000_000,
            "token_deltas": [{"mint": MINT, "raw_delta": -500_000, "decimals": 6}],
        },
        wallet="WalletA",
    )
    assert sells[0].side == "sell"
    assert prints_from_wallet_payload({"succeeded": False, "token_deltas": []}, wallet="x") == ()


def test_enhanced_tx_matches_roommate_side_rule() -> None:
    tx = {
        "timestamp": 1_700_000_000,
        "feePayer": "Trader",
        "tokenTransfers": [
            {"mint": MINT, "tokenAmount": 10, "toUserAccount": "Trader", "fromUserAccount": "Pool"}
        ],
        "nativeTransfers": [{"amount": 200_000_000, "fromUserAccount": "Trader", "toUserAccount": "Pool"}],
    }
    prints = prints_from_enhanced_tx(tx, mint=MINT, pool="Pool")
    assert prints[0].side == "buy"
    assert prints[0].quote_sol == 0.2


def test_history_tx_fee_payer_buy_becomes_a_print() -> None:
    wallet = "11111111111111111111111111111111"
    tx = {
        "slot": 42,
        "blockTime": 1_700_000_042,
        "transaction": {
            "signatures": ["5" * 64],
            "message": {
                "accountKeys": [
                    {"pubkey": wallet, "signer": True, "writable": True},
                ],
            },
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [1_000_000],
            "postBalances": [895_000],
            "preTokenBalances": [
                {
                    "accountIndex": 2,
                    "mint": MINT,
                    "owner": wallet,
                    "uiTokenAmount": {"amount": "100", "decimals": 6},
                }
            ],
            "postTokenBalances": [
                {
                    "accountIndex": 2,
                    "mint": MINT,
                    "owner": wallet,
                    "uiTokenAmount": {"amount": "250", "decimals": 6},
                }
            ],
        },
    }
    prints = prints_from_history_tx(tx, mint=MINT)
    assert len(prints) == 1
    assert prints[0].side == "buy"
    assert prints[0].wallet == wallet
    assert prints[0].base == 0.00015
    assert prints[0].quote_sol == 0.000105


def test_holder_features_equal_book_is_not_a_veto_shape() -> None:
    bag = holder_features([1.0, 1.0, 1.0, 1.0])
    assert bag["holder_count"] == 4
    assert bag["holder_top1"] == 0.25
    assert bag["holder_nakamoto"] > 1
    assert holder_verdict(bag) != VERDICT_VETO
    assert holder_veto(concentration([1.0, 1.0, 1.0, 1.0])) is False
    assert holder_features([]) == {"holder_count": 0}


def test_holder_features_one_whale_is_a_veto_shape() -> None:
    bag = holder_features([40.0, 20.0, 20.0, 20.0])
    assert bag["holder_top1"] == 0.4
    assert holder_verdict(bag) == VERDICT_VETO
    assert holder_veto(concentration([40.0, 20.0, 20.0, 20.0])) is True


def test_wash_tape_vetoes_organic_sieve() -> None:
    from shitcoims_intelligence.tape import TapePrint

    prints = [
        TapePrint(ts=i, mint=MINT, wallet="Whale", side="buy", quote_sol=1.0, base=1.0)
        for i in range(25)
    ]
    features = features_from_prints(prints)
    assert features["trade_count"] == 25
    assert features["unique_wallet_count"] == 1
    assert features["top_wallet_quote_share"] == 1.0
    assert organic_verdict(features) == VERDICT_VETO


def test_tape_source_does_not_import_marketfabric() -> None:
    source = inspect.getsource(tape)
    assert "marketfabric" not in source
    assert "Keypair" not in source


def test_a_multi_leg_transaction_is_refused_rather_than_split_evenly() -> None:
    """One native SOL delta cannot be attributed across several mints.

    Splitting it evenly invents a per-leg price for every leg, and a study cannot tell a
    fabricated price from a measured one — it looks like a trade. Refusing keeps the
    ambiguity visible as a smaller n instead of turning it into confident noise.
    """
    payload = {
        "succeeded": True,
        "slot": 100,
        "sol_delta_lamports": -1_000_000_000,
        "token_deltas": [
            {"mint": "A" * 32, "raw_delta": 5_000, "decimals": 6},
            {"mint": "B" * 32, "raw_delta": -7_000, "decimals": 6},
        ],
    }
    assert tape.prints_from_wallet_payload(payload, wallet="W" * 32) == ()


def test_a_single_leg_transaction_keeps_the_whole_sol_delta() -> None:
    """The unambiguous case must still price at the FULL delta, not a fraction of it."""
    payload = {
        "succeeded": True,
        "slot": 100,
        "sol_delta_lamports": -2_000_000_000,
        "token_deltas": [{"mint": "A" * 32, "raw_delta": 5_000, "decimals": 6}],
    }
    result = tape.prints_from_wallet_payload(payload, wallet="W" * 32)
    assert len(result) == 1
    assert result[0].quote_sol == 2.0
