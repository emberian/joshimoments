"""Bounded, read-only Helius wallet intelligence clients.

This module deliberately has no dependency on the sentinel executor or wallet
keypair.  The only credential it reads is a Helius API key from the configured
private file.  Provider URLs are never exposed through public attributes,
exceptions, or logs because the URL query string contains that credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import stat
from collections import OrderedDict, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from solders.pubkey import Pubkey

LOGGER = logging.getLogger("shitcoims.intelligence.helius")

# Helius credentials are URL query parameters.  Keep lower-level request logs
# quiet so an operator cannot accidentally enable ordinary INFO logging and
# write a credential to disk.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9:_-]{1,160}$")
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
HELIUS_HISTORY_PARSER_VERSION = "helius-full-jsonparsed-v1"
HELIUS_STREAM_PARSER_VERSION = "helius-transaction-subscribe-v1"


class HeliusIntelligenceError(RuntimeError):
    """A sanitized Helius source or data-quality failure."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _read_helius_key(path: Path) -> str:
    path = path.expanduser()
    try:
        info = path.stat()
    except FileNotFoundError:
        raise HeliusIntelligenceError(f"Helius API key file is missing: {path}") from None
    if not stat.S_ISREG(info.st_mode):
        raise HeliusIntelligenceError(f"Helius API key path is not a regular file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise HeliusIntelligenceError(
            f"Helius API key file must be private (0600 or stricter): {path} is {mode:o}"
        )
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise HeliusIntelligenceError(f"Helius API key file is empty: {path}")
    if len(value) > 512 or any(character.isspace() for character in value):
        raise HeliusIntelligenceError("Helius API key has an invalid format")
    return value


def _credentialed_endpoint(template: str, key: str, *, websocket: bool) -> str:
    if template.count("{api_key}") != 1:
        raise HeliusIntelligenceError("Helius endpoint template must contain one {api_key}")
    try:
        endpoint = template.format(api_key=quote(key, safe=""))
    except (KeyError, ValueError) as exc:
        raise HeliusIntelligenceError("Helius endpoint template is invalid") from exc
    parsed = urlsplit(endpoint)
    query = parse_qs(parsed.query, keep_blank_values=True)
    expected_scheme = "wss" if websocket else "https"
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != expected_scheme
        or not (host == "helius-rpc.com" or host.endswith(".helius-rpc.com"))
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or query.get("api-key") != [key]
    ):
        raise HeliusIntelligenceError("Helius endpoint template is not an approved Helius origin")
    return endpoint


def _validate_pubkey(value: str) -> str:
    if not _PUBKEY_RE.fullmatch(value):
        raise ValueError("wallet address must be a base58 Solana public key")
    try:
        Pubkey.from_string(value)
    except ValueError:
        raise ValueError("wallet address must be a base58 Solana public key") from None
    return value


def _validate_cursor(value: str | None) -> str | None:
    if value is not None and not _CURSOR_RE.fullmatch(value):
        raise ValueError("Helius pagination cursor has an invalid format")
    return value


def _token_ui_amount(item: Any) -> float | None:
    """Parse one ``getTokenLargestAccounts`` row into a ui amount."""

    if not isinstance(item, dict):
        return None
    nested = item.get("uiTokenAmount")
    if isinstance(nested, dict):
        parsed = _token_ui_amount(nested)
        if parsed is not None:
            return parsed
    ui = item.get("uiAmount")
    if isinstance(ui, bool):
        return None
    if isinstance(ui, int | float) and math.isfinite(float(ui)):
        return float(ui)
    amount = item.get("amount")
    decimals = item.get("decimals")
    try:
        raw = int(str(amount))
        places = int(decimals)
    except (TypeError, ValueError):
        return None
    if places < 0 or places > 255:
        return None
    return raw / (10**places)


@dataclass(frozen=True, slots=True)
class TokenBalanceDelta:
    mint: str
    raw_delta: int
    decimals: int


@dataclass(frozen=True, slots=True)
class WalletTransaction:
    """Canonical wallet-local facts extracted from one full chain transaction."""

    wallet: str
    signature: str
    slot: int
    transaction_index: int | None
    block_time: int | None
    succeeded: bool
    fee_lamports: int | None
    fee_payer: str | None
    wallet_paid_fee: bool | None
    sol_delta_lamports: int | None
    sol_delta_exact: bool
    token_deltas: tuple[TokenBalanceDelta, ...]
    commitment: Literal["confirmed", "finalized"]
    token_deltas_exact: bool = True
    source: str = "helius"
    observed_at: datetime = field(default_factory=_utc_now)
    raw_blob_ids: tuple[str, ...] = ()
    parser_version: str = HELIUS_HISTORY_PARSER_VERSION


@dataclass(frozen=True, slots=True)
class HistoryBounds:
    """Finite history request bounds; no collector call is allowed to be open-ended."""

    max_pages: int
    max_transactions: int
    max_estimated_credits: int
    page_size: int = 100
    estimated_credits_per_page: int = 50
    sort_order: Literal["asc", "desc"] = "desc"
    commitment: Literal["confirmed", "finalized"] = "finalized"
    min_slot: int | None = None
    max_slot: int | None = None
    min_block_time: int | None = None
    max_block_time: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_pages <= 10_000:
            raise ValueError("max_pages must be between 1 and 10000")
        if not 1 <= self.max_transactions <= 1_000_000:
            raise ValueError("max_transactions must be between 1 and 1000000")
        if not 1 <= self.max_estimated_credits <= 1_000_000_000:
            raise ValueError("max_estimated_credits must be between 1 and 1000000000")
        if not 1 <= self.estimated_credits_per_page <= 1_000_000:
            raise ValueError("estimated_credits_per_page must be between 1 and 1000000")
        if not 1 <= self.page_size <= 100:
            raise ValueError("full-transaction page_size must be between 1 and 100")
        for name in ("min_slot", "max_slot", "min_block_time", "max_block_time"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")
        if (
            self.min_slot is not None
            and self.max_slot is not None
            and self.min_slot > self.max_slot
        ):
            raise ValueError("min_slot cannot exceed max_slot")
        if (
            self.min_block_time is not None
            and self.max_block_time is not None
            and self.min_block_time > self.max_block_time
        ):
            raise ValueError("min_block_time cannot exceed max_block_time")


@dataclass(frozen=True, slots=True)
class HistoryResult:
    transactions: tuple[WalletTransaction, ...]
    next_cursor: str | None
    source_exhausted: bool
    bound_reached: bool
    pages_fetched: int
    duplicate_count: int
    estimated_credits: int


@dataclass(frozen=True, slots=True)
class WatchlistSnapshot:
    version: str
    addresses: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 128:
            raise ValueError("watchlist version must be 1-128 characters")
        if not self.addresses:
            raise ValueError("watchlist cannot be empty")
        if len(self.addresses) != len(set(self.addresses)):
            raise ValueError("watchlist addresses must be unique")
        for address in self.addresses:
            _validate_pubkey(address)


SourceStatus = Literal["connecting", "healthy", "degraded", "stopped"]
StreamKind = Literal["source_health", "gap", "transaction"]


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """A transaction or an explicit statement about source continuity."""

    kind: StreamKind
    watchlist_version: str
    observed_at: datetime = field(default_factory=_utc_now)
    status: SourceStatus | None = None
    reason: str | None = None
    last_observed_slot: int | None = None
    transaction: WalletTransaction | None = None


class WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def ping(self) -> Any: ...


class AsyncContextManagerLike(Protocol):
    async def __aenter__(self) -> WebSocketLike: ...

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any: ...


WebSocketFactory = Callable[..., AsyncContextManagerLike]
WatchlistProvider = Callable[[], Awaitable[WatchlistSnapshot]]


@dataclass(frozen=True, slots=True)
class RawHistoryPage:
    """Credential-free raw page envelope for an idempotent evidence cache."""

    wallet: str
    requested_cursor: str | None
    request_fingerprint: str
    content_hash: str
    idempotency_key: str
    body: bytes
    observed_at: datetime
    parser_version: str = HELIUS_HISTORY_PARSER_VERSION


RawHistoryPageSink = Callable[[RawHistoryPage], Awaitable[str | None]]


def _account_keys(item: dict[str, Any]) -> list[str]:
    transaction = item.get("transaction")
    if not isinstance(transaction, dict):
        return []
    message = transaction.get("message")
    if not isinstance(message, dict):
        return []
    keys: list[str] = []
    for value in message.get("accountKeys") or []:
        key = value.get("pubkey") if isinstance(value, dict) else value
        if isinstance(key, str):
            keys.append(key)

    meta = item.get("meta")
    if not isinstance(meta, dict):
        return keys
    pre_balances = meta.get("preBalances")
    expected = len(pre_balances) if isinstance(pre_balances, list) else 0
    if len(keys) < expected:
        loaded = meta.get("loadedAddresses")
        if isinstance(loaded, dict):
            candidates = list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
            keys.extend(str(value) for value in candidates[: expected - len(keys)])
    return keys


def _owned_token_balances(
    values: Any, wallet: str
) -> tuple[dict[tuple[int, str], tuple[int, int]], bool]:
    if values is None:
        return {}, True
    if not isinstance(values, list):
        raise HeliusIntelligenceError("Helius token balances were malformed")
    balances: dict[tuple[int, str], tuple[int, int]] = {}
    complete_owner_metadata = True
    for value in values:
        if not isinstance(value, dict):
            raise HeliusIntelligenceError("Helius token balance entry was malformed")
        if value.get("owner") is None:
            complete_owner_metadata = False
        if value.get("owner") != wallet:
            continue
        try:
            ui = value["uiTokenAmount"]
            account_index = int(value["accountIndex"])
            mint = str(value["mint"])
            amount = int(str(ui["amount"]))
            decimals = int(ui["decimals"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HeliusIntelligenceError("Helius owned token balance was malformed") from exc
        try:
            _validate_pubkey(mint)
        except ValueError:
            raise HeliusIntelligenceError("Helius owned token balance was invalid") from None
        if account_index < 0 or not 0 <= decimals <= 255:
            raise HeliusIntelligenceError("Helius owned token balance was invalid")
        balances[(account_index, mint)] = (amount, decimals)
    return balances, complete_owner_metadata


def normalize_wallet_transaction(
    item: dict[str, Any],
    wallet: str,
    *,
    commitment: Literal["confirmed", "finalized"],
    signature_override: str | None = None,
    parser_version: str = HELIUS_HISTORY_PARSER_VERSION,
) -> WalletTransaction:
    """Normalize one Helius full transaction into wallet-local balance facts."""

    _validate_pubkey(wallet)
    try:
        transaction = item["transaction"]
        meta = item["meta"]
        signatures = transaction.get("signatures") if isinstance(transaction, dict) else None
        signature = signature_override or str(signatures[0])
        slot = int(item["slot"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HeliusIntelligenceError("Helius full transaction omitted its identity") from exc
    if not 32 <= len(signature) <= 128 or slot < 0 or not isinstance(meta, dict):
        raise HeliusIntelligenceError("Helius full transaction identity was invalid")

    transaction_index_value = item.get("transactionIndex")
    try:
        transaction_index = (
            None if transaction_index_value is None else int(transaction_index_value)
        )
        block_time_value = item.get("blockTime")
        block_time = None if block_time_value is None else int(block_time_value)
        fee_value = meta.get("fee")
        fee = None if fee_value is None else int(fee_value)
    except (TypeError, ValueError) as exc:
        raise HeliusIntelligenceError("Helius full transaction metadata was malformed") from exc
    if transaction_index is not None and transaction_index < 0:
        raise HeliusIntelligenceError("Helius transaction index was invalid")
    if block_time is not None and block_time < 0:
        raise HeliusIntelligenceError("Helius block time was invalid")
    if fee is not None and fee < 0:
        raise HeliusIntelligenceError("Helius transaction fee was invalid")

    keys = _account_keys(item)
    fee_payer = keys[0] if keys else None
    pre_balances = meta.get("preBalances")
    post_balances = meta.get("postBalances")
    sol_delta: int | None = None
    sol_delta_exact = False
    if wallet in keys:
        wallet_index = keys.index(wallet)
        if not isinstance(pre_balances, list) or not isinstance(post_balances, list):
            raise HeliusIntelligenceError("Helius native balances were malformed")
        try:
            sol_delta = int(post_balances[wallet_index]) - int(pre_balances[wallet_index])
        except (IndexError, TypeError, ValueError) as exc:
            raise HeliusIntelligenceError("Helius native balance vectors were malformed") from exc
        sol_delta_exact = True

    pre_tokens, pre_owner_metadata = _owned_token_balances(
        meta.get("preTokenBalances"), wallet
    )
    post_tokens, post_owner_metadata = _owned_token_balances(
        meta.get("postTokenBalances"), wallet
    )
    by_mint: defaultdict[str, int] = defaultdict(int)
    decimals_by_mint: dict[str, int] = {}
    for account_mint in pre_tokens.keys() | post_tokens.keys():
        before, before_decimals = pre_tokens.get(account_mint, (0, -1))
        after, after_decimals = post_tokens.get(account_mint, (0, -1))
        if before_decimals >= 0 and after_decimals >= 0 and before_decimals != after_decimals:
            raise HeliusIntelligenceError("Helius token decimals changed within one transaction")
        decimals = after_decimals if after_decimals >= 0 else before_decimals
        mint = account_mint[1]
        by_mint[mint] += after - before
        if mint in decimals_by_mint and decimals_by_mint[mint] != decimals:
            raise HeliusIntelligenceError("Helius token accounts disagree on mint decimals")
        decimals_by_mint[mint] = decimals
    token_deltas = tuple(
        TokenBalanceDelta(mint=mint, raw_delta=delta, decimals=decimals_by_mint[mint])
        for mint, delta in sorted(by_mint.items())
        if delta != 0
    )

    return WalletTransaction(
        wallet=wallet,
        signature=signature,
        slot=slot,
        transaction_index=transaction_index,
        block_time=block_time,
        succeeded=meta.get("err") is None,
        fee_lamports=fee,
        fee_payer=fee_payer,
        wallet_paid_fee=None if fee_payer is None else fee_payer == wallet,
        sol_delta_lamports=sol_delta,
        sol_delta_exact=sol_delta_exact,
        token_deltas=token_deltas,
        token_deltas_exact=pre_owner_metadata and post_owner_metadata,
        commitment=commitment,
        parser_version=parser_version,
    )


class HeliusHistoryClient:
    """Finite cursor-pagination client for ``getTransactionsForAddress``."""

    def __init__(
        self,
        *,
        api_key_file: Path,
        http_url_template: str,
        http: httpx.AsyncClient,
        max_attempts: int = 3,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        raw_page_sink: RawHistoryPageSink | None = None,
    ) -> None:
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        key = _read_helius_key(api_key_file)
        self._url = _credentialed_endpoint(http_url_template, key, websocket=False)
        self._http = http
        self._max_attempts = max_attempts
        self._sleeper = sleeper
        self._raw_page_sink = raw_page_sink
        self._request_id = 0

    async def _rpc(
        self, wallet: str, options: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "getTransactionsForAddress",
            "params": [wallet, options],
        }
        for attempt in range(self._max_attempts):
            try:
                response = await self._http.post(self._url, json=payload)
                if len(response.content) > _MAX_RESPONSE_BYTES:
                    raise HeliusIntelligenceError("Helius history response exceeded its size limit")
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("non-object JSON-RPC response")
            except HeliusIntelligenceError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if attempt + 1 < self._max_attempts:
                    await self._sleeper(min(0.25 * (2**attempt), 2.0))
                    continue
                raise HeliusIntelligenceError(
                    f"Helius history transport failed ({type(exc).__name__})"
                ) from None
            error = body.get("error")
            if error is not None:
                code = error.get("code") if isinstance(error, dict) else "unknown"
                raise HeliusIntelligenceError(f"Helius history RPC returned error {code}")
            result = body.get("result")
            if not isinstance(result, dict):
                raise HeliusIntelligenceError("Helius history RPC omitted its result")
            raw_blob_id: str | None = None
            if self._raw_page_sink is not None:
                canonical_request = json.dumps(
                    {
                        "method": "getTransactionsForAddress",
                        "params": [wallet, options],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                request_fingerprint = hashlib.sha256(canonical_request).hexdigest()
                content_hash = hashlib.sha256(response.content).hexdigest()
                page = RawHistoryPage(
                    wallet=wallet,
                    requested_cursor=options.get("paginationToken"),
                    request_fingerprint=request_fingerprint,
                    content_hash=content_hash,
                    idempotency_key=hashlib.sha256(
                        f"{request_fingerprint}:{content_hash}".encode()
                    ).hexdigest(),
                    body=bytes(response.content),
                    observed_at=_utc_now(),
                )
                try:
                    # Called exactly once for this successful transport response,
                    # before any transaction is normalized. The sink provides
                    # durable exactly-once semantics using idempotency_key.
                    raw_blob_id = await self._raw_page_sink(page)
                except Exception:
                    raise HeliusIntelligenceError(
                        "Helius raw history cache rejected a page"
                    ) from None
                if raw_blob_id is not None and (
                    not raw_blob_id or len(raw_blob_id) > 128
                ):
                    raise HeliusIntelligenceError(
                        "Helius raw history cache returned an invalid blob id"
                    )
            return result, raw_blob_id
        raise AssertionError("unreachable")

    async def _jsonrpc(self, method: str, params: list[Any]) -> Any:
        """POST one JSON-RPC method to the credentialed Helius URL.

        Errors are sanitized: the URL (and therefore the API key) is never
        placed on the exception or its cause.
        """

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        for attempt in range(self._max_attempts):
            try:
                response = await self._http.post(self._url, json=payload)
                if len(response.content) > _MAX_RESPONSE_BYTES:
                    raise HeliusIntelligenceError("Helius RPC response exceeded its size limit")
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("non-object JSON-RPC response")
            except HeliusIntelligenceError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if attempt + 1 < self._max_attempts:
                    await self._sleeper(min(0.25 * (2**attempt), 2.0))
                    continue
                raise HeliusIntelligenceError(
                    f"Helius RPC transport failed ({type(exc).__name__})"
                ) from None
            error = body.get("error")
            if error is not None:
                code = error.get("code") if isinstance(error, dict) else "unknown"
                raise HeliusIntelligenceError(f"Helius RPC returned error {code}")
            if "result" not in body:
                raise HeliusIntelligenceError("Helius RPC omitted its result")
            return body.get("result")
        raise AssertionError("unreachable")

    async def token_largest_accounts(self, mint: str) -> tuple[float, ...]:
        """``getTokenLargestAccounts`` → positive ui amounts, largest first."""

        mint = _validate_pubkey(mint)
        result = await self._jsonrpc("getTokenLargestAccounts", [mint])
        if result is None:
            raise HeliusIntelligenceError("Helius token largest-accounts omitted its result")
        if isinstance(result, dict):
            value = result.get("value")
        elif isinstance(result, list):
            value = result
        else:
            raise HeliusIntelligenceError("Helius token largest-accounts result was malformed")
        if value is None:
            return ()
        if not isinstance(value, list):
            raise HeliusIntelligenceError("Helius token largest-accounts value was malformed")
        amounts: list[float] = []
        for item in value:
            amount = _token_ui_amount(item)
            if amount is not None and amount > 0:
                amounts.append(amount)
        return tuple(amounts)

    async def mint_enhanced_page(self, mint: str, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        """One ``getTransactionsForAddress`` page with the mint as the address."""

        mint = _validate_pubkey(mint)
        if not 1 <= limit <= 100:
            raise ValueError("mint history limit must be between 1 and 100")
        options: dict[str, Any] = {
            "transactionDetails": "full",
            "sortOrder": "desc",
            "commitment": "finalized",
            "limit": limit,
            "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 0,
        }
        result, _raw_blob_id = await self._rpc(mint, options)
        data = result.get("data")
        if data is None:
            data = result.get("transactions")
        if not isinstance(data, list):
            raise HeliusIntelligenceError("Helius returned an invalid mint history page")
        if len(data) > limit:
            raise HeliusIntelligenceError("Helius returned an invalid or over-limit history page")
        page: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise HeliusIntelligenceError("Helius history page contained a non-object record")
            page.append(item)
        return tuple(page)

    @staticmethod
    def _filters(bounds: HistoryBounds) -> dict[str, Any]:
        filters: dict[str, Any] = {"status": "any", "tokenAccounts": "balanceChanged"}
        slot: dict[str, int] = {}
        if bounds.min_slot is not None:
            slot["gte"] = bounds.min_slot
        if bounds.max_slot is not None:
            slot["lte"] = bounds.max_slot
        if slot:
            filters["slot"] = slot
        block_time: dict[str, int] = {}
        if bounds.min_block_time is not None:
            block_time["gte"] = bounds.min_block_time
        if bounds.max_block_time is not None:
            block_time["lte"] = bounds.max_block_time
        if block_time:
            filters["blockTime"] = block_time
        return filters

    async def fetch(
        self,
        wallet: str,
        bounds: HistoryBounds,
        *,
        cursor: str | None = None,
    ) -> HistoryResult:
        wallet = _validate_pubkey(wallet)
        cursor = _validate_cursor(cursor)
        seen_cursors: set[str] = set()
        seen_signatures: set[str] = set()
        transactions: list[WalletTransaction] = []
        pages = 0
        duplicate_count = 0
        source_exhausted = False
        estimated_credits = 0

        while (
            pages < bounds.max_pages
            and len(transactions) < bounds.max_transactions
            and estimated_credits + bounds.estimated_credits_per_page
            <= bounds.max_estimated_credits
        ):
            request_limit = min(bounds.page_size, bounds.max_transactions - len(transactions))
            options: dict[str, Any] = {
                "transactionDetails": "full",
                "sortOrder": bounds.sort_order,
                "commitment": bounds.commitment,
                "limit": request_limit,
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "filters": self._filters(bounds),
            }
            if cursor is not None:
                options["paginationToken"] = cursor
            result, raw_blob_id = await self._rpc(wallet, options)
            estimated_credits += bounds.estimated_credits_per_page
            data = result.get("data")
            if not isinstance(data, list) or len(data) > request_limit:
                raise HeliusIntelligenceError("Helius returned an invalid or over-limit history page")
            pages += 1
            for item in data:
                if not isinstance(item, dict):
                    raise HeliusIntelligenceError("Helius history page contained a non-object record")
                transaction = normalize_wallet_transaction(
                    item,
                    wallet,
                    commitment=bounds.commitment,
                )
                if raw_blob_id is not None:
                    transaction = replace(transaction, raw_blob_ids=(raw_blob_id,))
                if transaction.signature in seen_signatures:
                    duplicate_count += 1
                    continue
                seen_signatures.add(transaction.signature)
                transactions.append(transaction)
                if len(transactions) >= bounds.max_transactions:
                    break

            next_cursor_value = result.get("paginationToken")
            if next_cursor_value is None or next_cursor_value == "":
                cursor = None
                source_exhausted = True
                break
            if not isinstance(next_cursor_value, str):
                raise HeliusIntelligenceError("Helius history cursor was malformed")
            next_cursor = _validate_cursor(next_cursor_value)
            assert next_cursor is not None
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise HeliusIntelligenceError("Helius history pagination cursor repeated")
            if cursor is not None:
                seen_cursors.add(cursor)
            cursor = next_cursor

        return HistoryResult(
            transactions=tuple(transactions),
            next_cursor=cursor,
            source_exhausted=source_exhausted,
            bound_reached=not source_exhausted,
            pages_fetched=pages,
            duplicate_count=duplicate_count,
            estimated_credits=estimated_credits,
        )


class HeliusTransactionStream:
    """Reconnectable confirmed ``transactionSubscribe`` wallet stream.

    Reconnection and watchlist replacement are reported as explicit ``gap``
    events.  Callers can then schedule bounded HTTP backfill rather than assume
    that a WebSocket was continuously authoritative.
    """

    def __init__(
        self,
        *,
        api_key_file: Path,
        websocket_url_template: str,
        websocket_factory: WebSocketFactory | None = None,
        keepalive_seconds: float = 30.0,
        reconnect_seconds: float = 1.0,
        max_addresses: int = 2_000,
        dedupe_size: int = 50_000,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not 5 <= keepalive_seconds <= 300:
            raise ValueError("keepalive_seconds must be between 5 and 300")
        if not 0 <= reconnect_seconds <= 300:
            raise ValueError("reconnect_seconds must be between 0 and 300")
        if not 1 <= max_addresses <= 50_000:
            raise ValueError("max_addresses must be between 1 and 50000")
        if not 1 <= dedupe_size <= 1_000_000:
            raise ValueError("dedupe_size must be between 1 and 1000000")
        key = _read_helius_key(api_key_file)
        self._url = _credentialed_endpoint(websocket_url_template, key, websocket=True)
        self._factory = websocket_factory
        self._keepalive_seconds = keepalive_seconds
        self._reconnect_seconds = reconnect_seconds
        self._max_addresses = max_addresses
        self._dedupe_size = dedupe_size
        self._sleeper = sleeper
        self._request_id = 0
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()

    def subscription_request(self, snapshot: WatchlistSnapshot) -> dict[str, Any]:
        if len(snapshot.addresses) > self._max_addresses:
            raise ValueError(
                f"watchlist has {len(snapshot.addresses)} addresses; limit is {self._max_addresses}"
            )
        self._request_id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "transactionSubscribe",
            "params": [
                {
                    "vote": False,
                    "accountInclude": list(snapshot.addresses),
                    "tokenAccounts": "balanceChanged",
                },
                {
                    "commitment": "confirmed",
                    "encoding": "jsonParsed",
                    "transactionDetails": "full",
                    "showRewards": False,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }

    async def _factory_for_connection(self) -> AsyncContextManagerLike:
        if self._factory is not None:
            return self._factory(
                self._url,
                open_timeout=10,
                close_timeout=5,
                ping_interval=None,
                max_size=_MAX_RESPONSE_BYTES,
                logger=logging.getLogger("shitcoims.intelligence.helius.transport"),
            )
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:  # pragma: no cover - installed with uvicorn[standard].
            raise HeliusIntelligenceError("Helius stream dependency is unavailable") from exc
        return connect(
            self._url,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
            max_size=_MAX_RESPONSE_BYTES,
            logger=logging.getLogger("shitcoims.intelligence.helius.transport"),
        )

    @staticmethod
    def _notification_item(result: dict[str, Any]) -> tuple[dict[str, Any], str]:
        try:
            wrapper = result["transaction"]
            transaction = wrapper["transaction"]
            meta = wrapper["meta"]
            signature = str(result["signature"])
            item = {
                "slot": result["slot"],
                "transactionIndex": result.get("transactionIndex"),
                "blockTime": None,
                "transaction": transaction,
                "meta": meta,
            }
        except (KeyError, TypeError) as exc:
            raise HeliusIntelligenceError("Helius transaction notification was malformed") from exc
        if not isinstance(transaction, dict) or not isinstance(meta, dict):
            raise HeliusIntelligenceError(
                "Helius transaction notification was not full jsonParsed data"
            )
        return item, signature

    def _remember(self, wallet: str, signature: str) -> bool:
        key = (wallet, signature)
        if key in self._seen:
            self._seen.move_to_end(key)
            return False
        self._seen[key] = None
        while len(self._seen) > self._dedupe_size:
            self._seen.popitem(last=False)
        return True

    async def events(
        self,
        watchlist_provider: WatchlistProvider,
        *,
        stop: asyncio.Event | None = None,
    ) -> AsyncIterator[StreamEvent]:
        last_slot: int | None = None
        while stop is None or not stop.is_set():
            snapshot = await watchlist_provider()
            reconfigure = False
            if len(snapshot.addresses) > self._max_addresses:
                raise ValueError(
                    f"watchlist has {len(snapshot.addresses)} addresses; limit is {self._max_addresses}"
                )
            yield StreamEvent(
                kind="source_health",
                watchlist_version=snapshot.version,
                status="connecting",
                last_observed_slot=last_slot,
            )
            try:
                context = await self._factory_for_connection()
                async with context as socket:
                    request = self.subscription_request(snapshot)
                    await socket.send(json.dumps(request, separators=(",", ":")))
                    raw_ack = await asyncio.wait_for(socket.recv(), timeout=10)
                    ack = json.loads(raw_ack)
                    subscription_id = ack.get("result") if isinstance(ack, dict) else None
                    if ack.get("id") != request["id"] or not isinstance(subscription_id, int):
                        raise HeliusIntelligenceError(
                            "Helius transaction subscription was rejected"
                        )
                    yield StreamEvent(
                        kind="source_health",
                        watchlist_version=snapshot.version,
                        status="healthy",
                        last_observed_slot=last_slot,
                    )

                    while stop is None or not stop.is_set():
                        current = await watchlist_provider()
                        if current != snapshot:
                            reconfigure = True
                            yield StreamEvent(
                                kind="gap",
                                watchlist_version=current.version,
                                reason="watchlist_changed",
                                last_observed_slot=last_slot,
                            )
                            break
                        try:
                            raw = await asyncio.wait_for(
                                socket.recv(), timeout=self._keepalive_seconds
                            )
                        except TimeoutError:
                            pong_waiter = await socket.ping()
                            if isinstance(pong_waiter, Awaitable):
                                await asyncio.wait_for(pong_waiter, timeout=10)
                            continue
                        body = json.loads(raw)
                        if not isinstance(body, dict) or body.get("method") != "transactionNotification":
                            continue
                        params = body.get("params")
                        if not isinstance(params, dict) or params.get("subscription") != subscription_id:
                            continue
                        result = params.get("result")
                        if not isinstance(result, dict):
                            raise HeliusIntelligenceError(
                                "Helius transaction notification omitted its result"
                            )
                        item, signature = self._notification_item(result)
                        event_slot = int(result["slot"])
                        last_slot = max(last_slot or event_slot, event_slot)
                        for wallet in snapshot.addresses:
                            transaction = normalize_wallet_transaction(
                                item,
                                wallet,
                                commitment="confirmed",
                                signature_override=signature,
                                parser_version=HELIUS_STREAM_PARSER_VERSION,
                            )
                            # accountInclude/tokenAccounts expansion should make at least
                            # one watched wallet relevant. Do not manufacture no-op rows
                            # for the other addresses sharing this subscription.
                            if (
                                not transaction.sol_delta_exact
                                and not transaction.token_deltas
                            ):
                                continue
                            if not self._remember(wallet, signature):
                                continue
                            yield StreamEvent(
                                kind="transaction",
                                watchlist_version=snapshot.version,
                                last_observed_slot=last_slot,
                                transaction=transaction,
                            )
                    else:
                        yield StreamEvent(
                            kind="source_health",
                            watchlist_version=snapshot.version,
                            status="stopped",
                            last_observed_slot=last_slot,
                        )
                        return
            except asyncio.CancelledError:
                raise
            except HeliusIntelligenceError as exc:
                reason = str(exc)
            except Exception as exc:
                reason = f"Helius transaction stream failed ({type(exc).__name__})"

            # A changed subscription has already emitted a precise gap. Otherwise
            # report both degraded health and a recovery cursor for bounded backfill.
            if reconfigure:
                continue
            yield StreamEvent(
                kind="source_health",
                watchlist_version=snapshot.version,
                status="degraded",
                reason=reason,
                last_observed_slot=last_slot,
            )
            yield StreamEvent(
                kind="gap",
                watchlist_version=snapshot.version,
                reason="stream_disconnected",
                last_observed_slot=last_slot,
            )
            if stop is not None and stop.is_set():
                return
            await self._sleeper(self._reconnect_seconds)


def sort_transactions(
    transactions: Sequence[WalletTransaction],
) -> tuple[WalletTransaction, ...]:
    """Stable Solana ordering with signatures as the final deterministic tie-breaker."""

    return tuple(
        sorted(
            transactions,
            key=lambda item: (
                item.slot,
                item.transaction_index if item.transaction_index is not None else 2**63 - 1,
                item.signature,
                item.wallet,
            ),
        )
    )
