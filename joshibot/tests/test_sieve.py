from __future__ import annotations

import inspect

import pytest

from shitcoims_intelligence import sieve
from shitcoims_intelligence.sieve import (
    EXECUTION_EFFECT_NONE,
    VERDICT_PASS,
    VERDICT_SKIP,
    VERDICT_VETO,
    VERDICT_WATCH_EXIT,
    SieveCard,
    attention_exit_mints,
    combine_verdicts,
    deployer_verdict,
    holder_verdict,
    organic_verdict,
    rank_cards,
    score_mention_quality,
)


def _card(
    mint: str,
    verdict: str,
    *,
    name: str | None = None,
    reasons: tuple[str, ...] = ("look",),
    scores: dict[str, float | None] | None = None,
) -> SieveCard:
    return SieveCard(
        mint=mint,
        name=name,
        verdict=verdict,
        reasons=reasons,
        scores={} if scores is None else scores,
    )


def test_farm_duplicate_text_scores_much_lower_than_original() -> None:
    original = score_mention_quality(
        text="the tape here is just a few wallets passing the same bag",
        followers=420,
        verified=False,
        likes=3,
        skeleton_dupes=0,
    )
    farm = score_mention_quality(
        text="i just voted yes for this to get listed family wagmi send it",
        followers=40,
        verified=True,
        likes=0,
        skeleton_dupes=12,
    )
    assert 0.0 <= farm < 0.2
    assert original > 0.5
    assert original - farm >= 0.4
    assert original <= 1.0


def test_deployer_two_siblings_vetoes_zero_siblings_passes_missing_creator_skips() -> None:
    subject = "mint-subject"
    assert (
        deployer_verdict(
            creator="deployer-serial",
            sibling_mints=("mint-a", "mint-b"),
            subject_mint=subject,
        )
        == VERDICT_VETO
    )
    assert (
        deployer_verdict(
            creator="deployer-one-shot",
            sibling_mints=(),
            subject_mint=subject,
        )
        == VERDICT_PASS
    )
    assert (
        deployer_verdict(
            creator="deployer-one-shot",
            sibling_mints=(subject,),
            subject_mint=subject,
        )
        == VERDICT_PASS
    )
    assert (
        deployer_verdict(creator=None, sibling_mints=("mint-a", "mint-b"), subject_mint=subject)
        == VERDICT_SKIP
    )
    assert (
        deployer_verdict(creator="  ", sibling_mints=("mint-a", "mint-b"), subject_mint=subject)
        == VERDICT_SKIP
    )


def test_holder_verdict_skips_missing_vetoes_cabal() -> None:
    assert holder_verdict({}) == VERDICT_SKIP
    assert holder_verdict({"holder_count": 0}) == VERDICT_SKIP
    assert (
        holder_verdict(
            {
                "holder_count": 8,
                "holder_top1": 0.20,
                "holder_hhi": 0.12,
                "holder_nakamoto": 4,
            }
        )
        == VERDICT_PASS
    )
    assert (
        holder_verdict(
            {
                "holder_count": 4,
                "holder_top1": 0.40,
                "holder_hhi": 0.22,
                "holder_nakamoto": 3,
            }
        )
        == VERDICT_VETO
    )
    assert (
        holder_verdict(
            {
                "holder_count": 3,
                "holder_top1": 0.20,
                "holder_hhi": 0.18,
                "holder_nakamoto": 1,
            }
        )
        == VERDICT_VETO
    )


def test_organic_wash_vetoes_thin_sample_skips() -> None:
    assert (
        organic_verdict(
            {
                "trade_count": 40,
                "top_wallet_quote_share": 0.70,
                "wallet_volume_hhi": 0.20,
                "unique_wallet_count": 12,
                "returning_wallet_ratio": 0.1,
            }
        )
        == VERDICT_VETO
    )
    assert (
        organic_verdict(
            {
                "trade_count": 40,
                "top_wallet_quote_share": 0.20,
                "wallet_volume_hhi": 0.50,
                "unique_wallet_count": 12,
            }
        )
        == VERDICT_VETO
    )
    assert (
        organic_verdict(
            {
                "trade_count": 40,
                "top_wallet_quote_share": 0.20,
                "wallet_volume_hhi": 0.10,
                "unique_wallet_count": 3,
            }
        )
        == VERDICT_VETO
    )
    assert (
        organic_verdict(
            {
                "trade_count": 19,
                "top_wallet_quote_share": 0.99,
                "wallet_volume_hhi": 0.99,
                "unique_wallet_count": 1,
            }
        )
        == VERDICT_SKIP
    )
    assert organic_verdict({}) == VERDICT_SKIP
    assert (
        organic_verdict(
            {
                "trade_count": 40,
                "top_wallet_quote_share": 0.20,
                "wallet_volume_hhi": 0.10,
                "unique_wallet_count": 20,
                "returning_wallet_ratio": 0.25,
            }
        )
        == VERDICT_PASS
    )


def test_attention_exit_is_held_mentioned_intersection() -> None:
    held = {"mint-held", "mint-quiet", "mint-also"}
    mentioned = ["mint-held", "mint-noise", "mint-also", "mint-held"]
    assert attention_exit_mints(held_mints=held, mentioned_mints=mentioned) == frozenset(
        {"mint-held", "mint-also"}
    )
    assert attention_exit_mints(held_mints=held, mentioned_mints=()) == frozenset()
    assert attention_exit_mints(held_mints=set(), mentioned_mints=mentioned) == frozenset()


def test_rank_cards_orders_veto_watch_exit_pass_skip_and_is_stable() -> None:
    skip_a = _card("skip-a", VERDICT_SKIP, reasons=("thin",))
    veto = _card("veto-1", VERDICT_VETO, reasons=("serial deployer",))
    pass_a = _card("pass-a", VERDICT_PASS, reasons=("open tape",))
    watch = _card("watch-1", VERDICT_WATCH_EXIT, reasons=("kol named a held mint",))
    pass_b = _card("pass-b", VERDICT_PASS, reasons=("also open",))
    skip_b = _card("skip-b", VERDICT_SKIP, reasons=("still thin",))

    ranked = rank_cards((skip_a, veto, pass_a, watch, pass_b, skip_b))
    assert [card.mint for card in ranked] == [
        "veto-1",
        "watch-1",
        "pass-a",
        "pass-b",
        "skip-a",
        "skip-b",
    ]
    assert all(card.execution_effect == EXECUTION_EFFECT_NONE for card in ranked)


def test_combine_verdicts_picks_most_severe() -> None:
    assert combine_verdicts(VERDICT_PASS, VERDICT_SKIP) == VERDICT_SKIP
    assert combine_verdicts(VERDICT_SKIP, VERDICT_WATCH_EXIT, VERDICT_PASS) == VERDICT_WATCH_EXIT
    assert combine_verdicts(VERDICT_PASS, VERDICT_VETO, VERDICT_WATCH_EXIT) == VERDICT_VETO
    assert combine_verdicts(VERDICT_PASS) == VERDICT_PASS
    with pytest.raises(ValueError, match="at least one"):
        combine_verdicts()
    with pytest.raises(ValueError, match="unknown verdict"):
        combine_verdicts("looks_fine")


def test_every_card_execution_effect_is_none() -> None:
    cards = (
        _card("a", VERDICT_PASS),
        _card("b", VERDICT_VETO),
        _card("c", VERDICT_WATCH_EXIT),
        _card("d", VERDICT_SKIP),
    )
    assert all(card.execution_effect == "none" for card in cards)
    assert all(card.execution_effect == "none" for card in rank_cards(cards))
    with pytest.raises(ValueError, match="always 'none'"):
        SieveCard(
            mint="x",
            name=None,
            verdict=VERDICT_PASS,
            reasons=("nope",),
            scores={},
            execution_effect="submit",
        )


def test_sieve_source_has_no_marketfabric_executor_or_keypair() -> None:
    source = inspect.getsource(sieve)
    assert "marketfabric" not in source
    assert "executor" not in source
    assert "Keypair" not in source
    assert "LIVE_ARMED" not in source
    assert "shitcoims_sentinel" not in source
