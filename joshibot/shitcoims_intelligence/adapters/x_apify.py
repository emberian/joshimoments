"""Bounded Apify X/Twitter search adapter.

Official X API v2 Basic/Pro is closed to new signups. This adapter pays a
pinned Apify actor for recent-search results and keeps only derived fields.

The token is sent as an Authorization bearer header. It is never placed in
the request URL, stored observations, or returned records. Tweets cannot
execute, and cashtags are never treated as mints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from shitcoims_intelligence.models import Finality, Observation

from .common import (
    AdapterDisabled,
    AdvisoryAdapterError,
    QuarantinedRecord,
    SourceProvenance,
    bounded_text,
    read_private_token_file,
    response_json,
    safe_transport_error,
)

SOURCE_ID = "apify_x_kaitoeasyapi_v1"
PINNED_ACTOR = "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest"
ENDPOINT = f"https://api.apify.com/v2/acts/{PINNED_ACTOR}/run-sync-get-dataset-items"
ADAPTER_VERSION = "apify-x-kaitoeasyapi-derived-v1"
MAX_QUERY_CHARS = 512
DEFAULT_MAX_ITEMS = 25
HARD_MAX_ITEMS = 100
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_ITEM_KEYS = 80
AUTHOR_MAX_KEYS = 40
ALLOWED_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_CASHTAG = re.compile(r"(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9]{1,11})\b")
_MENTION = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_]{1,15})\b")
_BASE58 = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
_MINT_URLS = (
    re.compile(rf"https?://(?:www\.)?pump\.fun/(?:coin/)?({_BASE58})(?:[/?#\s]|$)", re.I),
    re.compile(rf"https?://(?:www\.)?dexscreener\.com/solana/({_BASE58})(?:[/?#\s]|$)", re.I),
    re.compile(rf"https?://(?:www\.)?birdeye\.so/token/({_BASE58})(?:[/?#\s]|$)", re.I),
    re.compile(rf"https?://(?:www\.)?axiom\.trade/(?:t/|meme/)?({_BASE58})(?:[/?#\s]|$)", re.I),
)
_TWITTER_TIME = "%a %b %d %H:%M:%S %z %Y"


@dataclass(frozen=True, slots=True)
class XApifyConfig:
    enabled: bool = False
    token_file: Path = Path("~/.apify-token")
    actor_id: str = PINNED_ACTOR
    max_items_per_query: int = DEFAULT_MAX_ITEMS


@dataclass(frozen=True, slots=True)
class XTweet:
    tweet_id: str
    url: str
    kind: str
    text: str
    created_at: datetime | None
    author_username: str
    author_followers: int | None
    author_verified: bool
    like_count: int | None
    retweet_count: int | None
    reply_count: int | None
    quote_count: int | None
    view_count: int | None
    cashtags: tuple[str, ...]
    mentioned_handles: tuple[str, ...]
    mint_candidates: tuple[str, ...]
    conversation_id: str | None
    provenance: SourceProvenance
    policy_effect: str = "observe"
    can_execute: bool = False


@dataclass(frozen=True, slots=True)
class XTweetBatch:
    query: str
    results: tuple[XTweet, ...]
    quarantined: tuple[QuarantinedRecord, ...]
    provenance: SourceProvenance


def normalize_actor_id(value: str) -> str:
    return value.strip().replace("/", "~")


def _digits(value: Any) -> str | None:
    text = bounded_text(value, limit=32)
    if text is None or not text.isdigit():
        return None
    return text


def _nonneg_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 10_000_000_000:
        return None
    return value


def _safe_x_url(value: Any) -> str | None:
    text = bounded_text(value, limit=2_048)
    if text is None:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


def _parse_time(value: Any) -> datetime | None:
    text = bounded_text(value, limit=64)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, _TWITTER_TIME)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _classify(item: MappingLike) -> str:
    if item.get("isRetweet") or item.get("type") == "retweet" or item.get("retweeted_tweet"):
        return "retweet"
    if item.get("isQuote") or item.get("type") == "quote" or item.get("quoted_tweet"):
        return "quote"
    if item.get("isReply") or item.get("inReplyToId") or item.get("in_reply_to_id"):
        return "reply"
    return "tweet"


def _extract_cashtags(text: str) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _CASHTAG.finditer(text):
        tag = match.group(1).upper()
        if tag not in seen:
            seen.append(tag)
        if len(seen) >= 8:
            break
    return tuple(seen)


def _extract_handles(text: str, *, author: str) -> tuple[str, ...]:
    skip = {author.lower()}
    seen: list[str] = []
    for match in _MENTION.finditer(text):
        handle = match.group(1)
        if handle.lower() in skip or handle in seen:
            continue
        seen.append(handle)
        if len(seen) >= 8:
            break
    return tuple(seen)


def _extract_mint_candidates(*texts: str) -> tuple[str, ...]:
    seen: list[str] = []
    for text in texts:
        if not text:
            continue
        for pattern in _MINT_URLS:
            for match in pattern.finditer(text):
                mint = match.group(1)
                if mint not in seen:
                    seen.append(mint)
                if len(seen) >= 8:
                    return tuple(seen)
    return tuple(seen)


def _collect_http_strings(value: Any, acc: list[str], *, depth: int = 0) -> None:
    if depth > 4 or len(acc) >= 32:
        return
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("http://") or text.startswith("https://"):
            acc.append(text[:2_048])
        elif text.startswith(("pump.fun/", "dexscreener.com/", "birdeye.so/")):
            acc.append(f"https://{text[:2_040]}")
        return
    if isinstance(value, dict):
        for child in list(value.values())[:40]:
            _collect_http_strings(child, acc, depth=depth + 1)
        return
    if isinstance(value, list):
        for child in value[:16]:
            _collect_http_strings(child, acc, depth=depth + 1)


def _item_urls(item: MappingLike) -> tuple[str, ...]:
    urls: list[str] = []
    _collect_http_strings(item, urls)
    # Preserve order while dropping exact duplicates.
    return tuple(dict.fromkeys(urls))


MappingLike = dict[str, Any]


def tweet_to_observations(
    tweet: XTweet, *, watched_handle: str | None = None
) -> tuple[Observation, ...]:
    """Project a derived tweet into advisory observations.

    One tweet record is always emitted. Mint and cashtag mentions become
    additional subject-indexed records so dossiers can find them. A watched
    KOL handle adds a ``kol`` subject. Nothing here is an execution instruction.
    """

    observed = tweet.created_at or tweet.provenance.observed_at
    emitted = tweet.provenance.observed_at
    kind = f"x_{tweet.kind}"
    author = tweet.author_username
    title = f"@{author}: {tweet.text[:80]}" if tweet.text else f"@{author}"
    payload = {
        "title": title[:240],
        "summary": tweet.text[:1_000],
        "severity": "info",
        "status": "observed",
        "classification": "claim",
        "url": tweet.url,
        "author_username": author,
        "author_followers": tweet.author_followers,
        "author_verified": tweet.author_verified,
        "cashtags": list(tweet.cashtags),
        "mentioned_handles": list(tweet.mentioned_handles),
        "mint_candidates": list(tweet.mint_candidates),
        "like_count": tweet.like_count,
        "retweet_count": tweet.retweet_count,
        "reply_count": tweet.reply_count,
        "quote_count": tweet.quote_count,
        "view_count": tweet.view_count,
        "tweet_kind": tweet.kind,
        "watched_handle": (watched_handle or "").lower() or None,
    }
    records = [
        Observation(
            source_id=SOURCE_ID,
            source_native_id=tweet.tweet_id,
            kind=kind,
            subject_type="tweet",
            subject_id=tweet.tweet_id,
            observed_at=observed,
            emitted_at=emitted,
            payload=payload,
            confidence=0.35,
            finality=Finality.UNVERIFIED,
            parser_version=ADAPTER_VERSION,
            provenance=(tweet.url,),
        )
    ]
    for mint in tweet.mint_candidates:
        records.append(
            Observation(
                source_id=SOURCE_ID,
                source_native_id=f"{tweet.tweet_id}:{mint}",
                kind="x_mint_mention",
                subject_type="token",
                subject_id=mint,
                observed_at=observed,
                emitted_at=emitted,
                payload={**payload, "title": f"@{author} mentioned a mint", "mint": mint},
                confidence=0.45,
                finality=Finality.UNVERIFIED,
                parser_version=ADAPTER_VERSION,
                provenance=(tweet.url,),
            )
        )
    for tag in tweet.cashtags:
        records.append(
            Observation(
                source_id=SOURCE_ID,
                source_native_id=f"{tweet.tweet_id}:{tag}",
                kind="x_cashtag",
                subject_type="cashtag",
                subject_id=tag,
                observed_at=observed,
                emitted_at=emitted,
                payload={**payload, "title": f"@{author} mentioned ${tag}"},
                confidence=0.25,
                finality=Finality.UNVERIFIED,
                parser_version=ADAPTER_VERSION,
                provenance=(tweet.url,),
            )
        )
    if watched_handle:
        handle = watched_handle.strip().lstrip("@")
        records.append(
            Observation(
                source_id=SOURCE_ID,
                source_native_id=f"{tweet.tweet_id}:kol:{handle}",
                kind="x_kol_post",
                subject_type="kol",
                subject_id=handle,
                observed_at=observed,
                emitted_at=emitted,
                payload={
                    **payload,
                    "title": f"KOL @{handle}: {tweet.text[:80]}" if tweet.text else f"KOL @{handle}",
                },
                confidence=0.55,
                finality=Finality.UNVERIFIED,
                parser_version=ADAPTER_VERSION,
                provenance=(tweet.url,),
            )
        )
    return tuple(records)


class XApifyAdapter:
    def __init__(self, config: XApifyConfig, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http

    def _provenance(self) -> SourceProvenance:
        return SourceProvenance(
            source_id=SOURCE_ID,
            source_url="https://apify.com/kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
            endpoint_family="Apify run-sync-get-dataset-items",
            adapter_version=ADAPTER_VERSION,
            contract_status="paid_third_party_scraper",
        )

    async def search(self, query: str, *, max_items: int | None = None) -> XTweetBatch:
        if not self._config.enabled:
            raise AdapterDisabled("Apify X adapter is disabled")
        actor = normalize_actor_id(self._config.actor_id)
        if actor != PINNED_ACTOR:
            raise AdvisoryAdapterError("Apify X actor is not the pinned search actor")
        query = " ".join(query.split())
        if not 1 <= len(query) <= MAX_QUERY_CHARS:
            raise ValueError(f"query must be between 1 and {MAX_QUERY_CHARS} characters")
        limit = self._config.max_items_per_query if max_items is None else max_items
        if not 1 <= limit <= HARD_MAX_ITEMS:
            raise ValueError(f"max_items must be between 1 and {HARD_MAX_ITEMS}")
        token = read_private_token_file(self._config.token_file)
        provenance = self._provenance()
        try:
            response = await self._http.post(
                ENDPOINT,
                headers={
                    "authorization": f"Bearer {token}",
                    "content-type": "application/json",
                    "accept": "application/json",
                },
                json={
                    "twitterContent": query,
                    "maxItems": limit,
                    "queryType": "Latest",
                },
                follow_redirects=False,
                timeout=httpx.Timeout(90, connect=5),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise safe_transport_error("Apify X", exc) from exc
        body = response_json(response, limit=MAX_RESPONSE_BYTES, source="Apify X")
        if not isinstance(body, list) or len(body) > HARD_MAX_ITEMS + 8:
            raise AdvisoryAdapterError("Apify X response schema changed")

        results: list[XTweet] = []
        quarantined: list[QuarantinedRecord] = []
        for item in body:
            parsed = self._parse_item(item, provenance)
            if isinstance(parsed, XTweet):
                if len(results) < limit:
                    results.append(parsed)
            elif parsed is not None:
                quarantined.append(parsed)
        return XTweetBatch(query, tuple(results), tuple(quarantined), provenance)

    def _parse_item(
        self, item: Any, provenance: SourceProvenance
    ) -> XTweet | QuarantinedRecord | None:
        if not isinstance(item, dict) or len(item) > MAX_ITEM_KEYS:
            return QuarantinedRecord(source_id=SOURCE_ID, reason="result_schema_drift")
        if item.get("noResults") is True:
            return None
        text = bounded_text(
            item.get("text") or item.get("fullText") or item.get("full_text"),
            limit=2_000,
            allow_empty=True,
        ) or ""
        if item.get("type") == "mock_tweet" or text.startswith("From KaitoEasyAPI"):
            return QuarantinedRecord(source_id=SOURCE_ID, reason="advisory_mock_tweet")
        tweet_id = bounded_text(item.get("id") or item.get("id_str"), limit=32)
        if tweet_id is None or not tweet_id.isdigit():
            return QuarantinedRecord(source_id=SOURCE_ID, reason="missing_or_invalid_tweet_id")
        url = _safe_x_url(item.get("url") or item.get("twitterUrl"))
        if url is None:
            return QuarantinedRecord(
                source_id=SOURCE_ID,
                reason="unsafe_or_missing_tweet_url",
                source_event_id=tweet_id,
            )
        author = item.get("author")
        if not isinstance(author, dict) or len(author) > AUTHOR_MAX_KEYS:
            return QuarantinedRecord(
                source_id=SOURCE_ID,
                reason="author_schema_drift",
                source_event_id=tweet_id,
            )
        username = bounded_text(
            author.get("userName") or author.get("username") or author.get("screen_name"),
            limit=15,
        )
        if username is None or not _HANDLE.fullmatch(username):
            return QuarantinedRecord(
                source_id=SOURCE_ID,
                reason="missing_or_invalid_author",
                source_event_id=tweet_id,
            )
        extra_urls = _item_urls(item)
        return XTweet(
            tweet_id=tweet_id,
            url=url,
            kind=_classify(item),
            text=text[:500],
            created_at=_parse_time(item.get("createdAt") or item.get("created_at")),
            author_username=username,
            author_followers=_nonneg_int(author.get("followers") or author.get("followersCount")),
            author_verified=bool(author.get("isBlueVerified") or author.get("isVerified")),
            like_count=_nonneg_int(item.get("likeCount") or item.get("favorite_count")),
            retweet_count=_nonneg_int(item.get("retweetCount") or item.get("retweet_count")),
            reply_count=_nonneg_int(item.get("replyCount") or item.get("reply_count")),
            quote_count=_nonneg_int(item.get("quoteCount") or item.get("quote_count")),
            view_count=_nonneg_int(item.get("viewCount") or item.get("view_count")),
            cashtags=_extract_cashtags(text),
            mentioned_handles=_extract_handles(text, author=username),
            mint_candidates=_extract_mint_candidates(text, *extra_urls),
            conversation_id=_digits(item.get("conversationId") or item.get("conversation_id")),
            provenance=provenance,
        )
