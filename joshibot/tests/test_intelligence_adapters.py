from __future__ import annotations

import inspect
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from solders.pubkey import Pubkey
from solders.signature import Signature

from shitcoims_intelligence.adapters import (
    CANONICAL_WALLET,
    PINNED_ACTOR,
    AdapterDisabled,
    AdvisoryAdapterError,
    ClaudeKolAdapter,
    ClaudeKolChainVerification,
    KagiConfig,
    KagiSearchAdapter,
    PumpCalloutsAdapter,
    PumpCalloutsConfig,
    XApifyAdapter,
    XApifyConfig,
    helius_verification_hook,
    tweet_to_observations,
)
from shitcoims_intelligence.adapters.claudekol import ACTIONS_URL
from shitcoims_intelligence.adapters.common import read_private_token_file
from shitcoims_intelligence.adapters.kagi import ENDPOINT as KAGI_ENDPOINT
from shitcoims_intelligence.adapters.pump_callouts import (
    EXPERIMENTAL_ENDPOINT,
    EXPERIMENTAL_SCHEMA,
)
from shitcoims_intelligence.adapters.x_apify import ENDPOINT as X_APIFY_ENDPOINT
from shitcoims_intelligence.config import IntelligenceConfigError, load_intelligence_config
from shitcoims_intelligence.helius import TokenBalanceDelta, WalletTransaction

PUBLIC_ANON_KEY = "eyJ" + ("a" * 120)


def private_env(path: Path, key: str, value: str = "test-token") -> Path:
    path.write_text(f"{key}={value}\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


@pytest.mark.asyncio
async def test_claudekol_validates_chain_claims_and_retains_label_conflict() -> None:
    mint = str(Pubkey.new_unique())
    signature = str(Signature.default())
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.copy_with(query=None)) == ACTIONS_URL
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {PUBLIC_ANON_KEY}"
        assert "cookie" not in request.headers
        assert request.url.params["select"] == "id,kind,title,body,created_at,mint,meta"
        return httpx.Response(
            200,
            json=[
                {
                    "id": first_id,
                    "kind": "trade_open",
                    "title": "APED $GOOD",
                    "body": "untrusted narrative",
                    "created_at": "2026-08-12T18:08:23+00:00",
                    "mint": mint,
                    "meta": {"sig": signature, "sol": 1.25, "pct": 4},
                },
                {
                    "id": second_id,
                    "kind": "callout",
                    "title": "$OTHER CALLOUT",
                    "body": "a conflicting label for the same mint",
                    "created_at": "2026-08-12T18:09:36+00:00",
                    "mint": mint,
                    "meta": {"url": f"https://pump.fun/coin/{mint}"},
                },
            ],
        )

    calls: list[tuple[str, str, str]] = []

    async def verify(wallet: str, claimed_mint: str, claimed_signature: str):
        calls.append((wallet, claimed_mint, claimed_signature))
        return ClaudeKolChainVerification(
            wallet=wallet,
            signature=claimed_signature,
            landed=True,
            succeeded=True,
            mint=claimed_mint,
            token_delta_raw=123,
            slot=42,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        batch = await ClaudeKolAdapter(http, public_anon_key=PUBLIC_ANON_KEY).actions(
            limit=2, verifier=verify
        )

    assert calls == [(CANONICAL_WALLET, mint, signature)]
    assert batch.actions[0].canonical_mint == mint
    assert batch.actions[0].canonical_signature == signature
    assert batch.actions[0].independently_verified is True
    assert batch.actions[0].title_claim == "APED $GOOD"
    assert batch.actions[0].can_execute is False
    assert "label_claim_conflict:$GOOD,$OTHER" in batch.actions[0].conflicts
    assert "label_claim_conflict:$GOOD,$OTHER" in batch.actions[1].conflicts


@pytest.mark.asyncio
async def test_claudekol_quarantines_invalid_mint_and_does_not_infer_execution() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "33333333-3333-4333-8333-333333333333",
                    "kind": "trade_open",
                    "title": "APED $FAKE",
                    "body": "claimed trade",
                    "created_at": "2026-08-12T18:08:23+00:00",
                    "mint": "not-a-mint",
                    "meta": {"sig": "not-a-signature"},
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        batch = await ClaudeKolAdapter(http, public_anon_key=PUBLIC_ANON_KEY).actions(limit=1)

    assert batch.actions == ()
    assert batch.quarantined[0].reason.startswith("schema_or_identity_drift")
    assert batch.quarantined[0].fingerprint


@pytest.mark.asyncio
async def test_kagi_v1_uses_fixed_post_bearer_and_returns_only_derived_results(
    tmp_path: Path,
) -> None:
    env_file = private_env(tmp_path / ".env", "KAGI_CUSTOM_KEY", "secret-value")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == KAGI_ENDPOINT
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer secret-value"
        assert "cookie" not in request.headers
        assert request.content == b'{"query":"solana wallet alpha"}'
        return httpx.Response(
            200,
            json={
                "data": {
                    "search": [
                        {
                            "title": "<strong>Useful</strong> result",
                            "url": "https://example.com/research#tracking",
                            "snippet": "A &amp; B <strong>summary</strong>",
                            "raw_page": "must never be returned",
                        },
                        {
                            "title": "bad",
                            "url": "javascript:alert(1)",
                            "snippet": "unsafe",
                        },
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        batch = await KagiSearchAdapter(
            KagiConfig(env_file=env_file, key_name="KAGI_CUSTOM_KEY"), http
        ).search("  solana   wallet alpha  ", limit=2)

    assert batch.query == "solana wallet alpha"
    assert len(batch.results) == 1
    assert batch.results[0].title == "Useful result"
    assert batch.results[0].snippet == "A & B summary"
    assert batch.results[0].url == "https://example.com/research"
    assert batch.results[0].can_execute is False
    assert batch.quarantined[0].reason == "unsafe_result_url"
    assert not hasattr(batch.results[0], "raw_page")


@pytest.mark.asyncio
async def test_kagi_rejects_public_env_files_and_oversized_responses(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KAGI_API_KEY=secret\n", encoding="utf-8")
    os.chmod(env_file, 0o644)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as http:
        with pytest.raises(AdvisoryAdapterError, match="must be private"):
            await KagiSearchAdapter(KagiConfig(env_file), http).search("query")

    os.chmod(env_file, 0o600)

    async def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (512 * 1024 + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as http:
        with pytest.raises(AdvisoryAdapterError, match="size limit"):
            await KagiSearchAdapter(KagiConfig(env_file), http).search("query")


@pytest.mark.asyncio
async def test_pump_callouts_is_disabled_without_complete_explicit_contract() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("network must not be called"))
    ) as http:
        with pytest.raises(AdapterDisabled, match="disabled"):
            await PumpCalloutsAdapter(PumpCalloutsConfig(), http).fetch()
        with pytest.raises(AdapterDisabled, match="credential"):
            await PumpCalloutsAdapter(
                PumpCalloutsConfig(
                    enabled=True,
                    endpoint=EXPERIMENTAL_ENDPOINT,
                    schema_version=EXPERIMENTAL_SCHEMA,
                ),
                http,
            ).fetch()


@pytest.mark.asyncio
async def test_pump_callouts_never_uses_browser_session_and_quarantines_schema_drift(
    tmp_path: Path,
) -> None:
    env_file = private_env(tmp_path / ".env", "PUMP_TOKEN", "experimental-token")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.copy_with(query=None)) == EXPERIMENTAL_ENDPOINT
        assert request.headers["authorization"] == "Bearer experimental-token"
        assert "cookie" not in request.headers
        return httpx.Response(200, json={"unexpected": []})

    config = PumpCalloutsConfig(
        enabled=True,
        endpoint=EXPERIMENTAL_ENDPOINT,
        schema_version=EXPERIMENTAL_SCHEMA,
        credential_env_file=env_file,
        credential_key_name="PUMP_TOKEN",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        batch = await PumpCalloutsAdapter(config, http).fetch(limit=2)

    assert batch.claims == ()
    assert batch.quarantined[0].reason == "top_level_schema_drift"
    assert batch.provenance.contract_status == "unsupported_reverse_engineered_experimental"


def test_advisory_adapters_have_no_executor_or_signer_imports() -> None:
    from shitcoims_intelligence.adapters import claudekol, kagi, pump_callouts, x_apify

    source = "\n".join(
        inspect.getsource(module) for module in (claudekol, kagi, pump_callouts, x_apify)
    )
    assert "shitcoims_sentinel.executor" not in source
    assert "Keypair" not in source
    assert "signed_transaction" not in source


def token_file(path: Path, value: str = "apify_api_test-token") -> Path:
    path.write_text(f"{value}\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


@pytest.mark.asyncio
async def test_x_apify_is_disabled_until_explicitly_enabled(tmp_path: Path) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("network must not be called"))
    ) as http:
        with pytest.raises(AdapterDisabled, match="disabled"):
            await XApifyAdapter(XApifyConfig(token_file=tmp_path / "missing"), http).search(
                "pump.fun"
            )


@pytest.mark.asyncio
async def test_x_apify_uses_bearer_not_query_token_and_extracts_url_mints_not_cashtags(
    tmp_path: Path,
) -> None:
    secret = token_file(tmp_path / "apify-token")
    mint = "So11111111111111111111111111111111111111112"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == X_APIFY_ENDPOINT
        assert "token=" not in str(request.url)
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer apify_api_test-token"
        assert "cookie" not in request.headers
        assert request.content == (
            b'{"twitterContent":"pump.fun $BONK","maxItems":2,"queryType":"Latest"}'
        )
        return httpx.Response(
            200,
            json=[
                {
                    "type": "tweet",
                    "id": "1846846285917131130",
                    "url": "https://x.com/alpha/status/1846846285917131130?s=20",
                    "text": f"$BONK launching https://pump.fun/coin/{mint} via @insider",
                    "createdAt": "Thu Oct 17 09:30:41 +0000 2024",
                    "likeCount": 12,
                    "retweetCount": 3,
                    "replyCount": 1,
                    "quoteCount": 0,
                    "viewCount": 400,
                    "isReply": False,
                    "isRetweet": False,
                    "isQuote": False,
                    "author": {
                        "userName": "alpha",
                        "followers": 1500,
                        "isBlueVerified": True,
                    },
                    "rawHtml": "must never be returned",
                },
                {
                    "type": "mock_tweet",
                    "id": "1",
                    "text": "From KaitoEasyAPI advisory",
                    "author": {"userName": "kaito"},
                },
                {
                    "id": "2",
                    "url": "javascript:alert(1)",
                    "text": "unsafe",
                    "author": {"userName": "bad"},
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        batch = await XApifyAdapter(
            XApifyConfig(enabled=True, token_file=secret, max_items_per_query=2), http
        ).search("  pump.fun   $BONK  ")

    assert batch.query == "pump.fun $BONK"
    assert len(batch.results) == 1
    tweet = batch.results[0]
    assert tweet.tweet_id == "1846846285917131130"
    assert tweet.url == "https://x.com/alpha/status/1846846285917131130"
    assert tweet.kind == "tweet"
    assert tweet.cashtags == ("BONK",)
    assert tweet.mentioned_handles == ("insider",)
    assert tweet.mint_candidates == (mint,)
    assert tweet.author_username == "alpha"
    assert tweet.author_followers == 1500
    assert tweet.can_execute is False
    assert tweet.policy_effect == "observe"
    assert not hasattr(tweet, "rawHtml")
    assert {record.reason for record in batch.quarantined} == {
        "advisory_mock_tweet",
        "unsafe_or_missing_tweet_url",
    }


@pytest.mark.asyncio
async def test_x_apify_rejects_public_token_files_and_unpinned_actors(tmp_path: Path) -> None:
    secret = tmp_path / "apify-token"
    secret.write_text("apify_api_test-token\n", encoding="utf-8")
    os.chmod(secret, 0o644)

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as http:
        with pytest.raises(AdvisoryAdapterError, match="must be private"):
            await XApifyAdapter(XApifyConfig(enabled=True, token_file=secret), http).search(
                "query"
            )

    os.chmod(secret, 0o600)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("unpinned actor must not be called"))
    ) as http:
        with pytest.raises(AdvisoryAdapterError, match="pinned"):
            await XApifyAdapter(
                XApifyConfig(enabled=True, token_file=secret, actor_id="evil/actor"),
                http,
            ).search("query")


def test_x_apify_token_reader_rejects_symlinks(tmp_path: Path) -> None:
    secret = token_file(tmp_path / "apify-token")
    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(AdvisoryAdapterError, match="symlink"):
        read_private_token_file(link)


def test_x_apify_extracts_mints_from_expanded_tco_entities() -> None:
    from shitcoims_intelligence.adapters.x_apify import _extract_mint_candidates, _item_urls

    mint = "So11111111111111111111111111111111111111112"
    item = {
        "text": "new coin https://t.co/abc",
        "entities": {"urls": [{"url": "https://t.co/abc", "expanded_url": f"https://pump.fun/coin/{mint}"}]},
    }
    assert mint in _extract_mint_candidates(item["text"], *_item_urls(item))


def test_tweet_to_observations_indexes_mints_and_cashtags_separately() -> None:
    from shitcoims_intelligence.adapters.common import SourceProvenance
    from shitcoims_intelligence.adapters.x_apify import SOURCE_ID, XTweet

    mint = "So11111111111111111111111111111111111111112"
    tweet = XTweet(
        tweet_id="1846846285917131130",
        url="https://x.com/alpha/status/1846846285917131130",
        kind="tweet",
        text=f"$BONK launching https://pump.fun/coin/{mint}",
        created_at=datetime(2026, 8, 12, 19, tzinfo=UTC),
        author_username="alpha",
        author_followers=12,
        author_verified=False,
        like_count=1,
        retweet_count=0,
        reply_count=0,
        quote_count=0,
        view_count=9,
        cashtags=("BONK",),
        mentioned_handles=(),
        mint_candidates=(mint,),
        conversation_id="1846846285917131130",
        provenance=SourceProvenance(
            SOURCE_ID,
            "https://apify.com/kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
            "Apify run-sync-get-dataset-items",
            "apify-x-kaitoeasyapi-derived-v1",
            "paid_third_party_scraper",
        ),
    )
    records = tweet_to_observations(tweet)
    kinds = {item.kind: item for item in records}
    assert kinds["x_tweet"].subject_type == "tweet"
    assert kinds["x_mint_mention"].subject_type == "token"
    assert kinds["x_mint_mention"].subject_id == mint
    assert kinds["x_cashtag"].subject_type == "cashtag"
    assert kinds["x_cashtag"].subject_id == "BONK"
    # A thread query returns replies by strangers under the watched handle, so
    # a tweet the KOL did not write must not be filed as that KOL's post.
    watched = {item.kind: item for item in tweet_to_observations(tweet, watched_handle="blknoiz06")}
    assert "x_kol_post" not in watched
    assert watched["x_kol_thread"].subject_type == "kol"
    assert watched["x_kol_thread"].subject_id == "blknoiz06"
    assert watched["x_kol_thread"].payload["authored_by_kol"] is False
    assert watched["x_kol_thread"].payload["author_username"] == "alpha"
    authored = {item.kind: item for item in tweet_to_observations(tweet, watched_handle="Alpha")}
    assert authored["x_kol_post"].subject_type == "kol"
    assert authored["x_kol_post"].subject_id == "Alpha"
    assert authored["x_kol_post"].payload["authored_by_kol"] is True
    assert all(item.can_execute is False for item in records if hasattr(item, "can_execute"))
    assert all(item.finality.value == "unverified" for item in records)


def test_intelligence_config_pins_x_apify_actor(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    config = load_intelligence_config(path)
    assert config.adapters.x_apify.enabled is False
    assert config.adapters.x_apify.actor_id == PINNED_ACTOR
    assert config.adapters.x_apify.max_items_per_query == 8
    assert config.adapters.x_apify.queries == ()
    assert config.adapters.x_apify.kols == ()
    assert config.adapters.x_apify.kol_thread_limit == 3

    path.write_text(
        "version: 1\nadapters:\n  x_apify:\n    actor_id: evil/scraper\n",
        encoding="utf-8",
    )
    with pytest.raises(IntelligenceConfigError, match="pinned"):
        load_intelligence_config(path)


@pytest.mark.asyncio
async def test_helius_hook_derives_verification_from_canonical_balance_delta() -> None:
    mint = str(Pubkey.new_unique())
    signature = str(Signature.default())

    async def lookup(wallet: str, requested_signature: str) -> WalletTransaction | None:
        assert wallet == CANONICAL_WALLET
        assert requested_signature == signature
        return WalletTransaction(
            wallet=wallet,
            signature=requested_signature,
            slot=123,
            transaction_index=4,
            block_time=1_700_000_000,
            succeeded=True,
            fee_lamports=5_000,
            fee_payer=wallet,
            wallet_paid_fee=True,
            sol_delta_lamports=-1_000,
            sol_delta_exact=True,
            token_deltas=(TokenBalanceDelta(mint=mint, raw_delta=77, decimals=6),),
            commitment="finalized",
            observed_at=datetime.now(UTC),
        )

    result = await helius_verification_hook(lookup)(CANONICAL_WALLET, mint, signature)

    assert result.landed is True
    assert result.succeeded is True
    assert result.mint == mint
    assert result.token_delta_raw == 77
    assert result.slot == 123
