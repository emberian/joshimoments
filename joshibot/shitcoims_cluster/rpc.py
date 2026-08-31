"""A read-only Helius JSON-RPC client, with the read-only part enforced rather than promised.

Three properties this module is responsible for:

**Read-only is structural.** :data:`READ_METHODS` is a whitelist and
:meth:`HeliusRpc.call` refuses anything outside it. A recorder that grows a
``sendTransaction`` by accident is a code change that raises, not a code change that spends
money.

**The API key never reaches an exception message.** httpx puts request URLs in its transport
errors, and the Helius URL *is* the credential. Every transport failure is re-raised as a
:class:`RpcError` carrying only the exception's class name — the same defence
``shitcoims_sentinel/clients.py`` makes, arrived at for the same reason.

**The key file's permissions are checked before it is read**, following the pattern in
``shitcoims_sentinel/secrets.py``. That module is deliberately *not imported*: this package
must not depend on the live trading sentinel, and a read-only research collector reaching
into the signer's package is exactly the coupling that turns "no live network in tests" into
a hope rather than a fact.

Batching: JSON-RPC array requests. Measured on this endpoint, a batch of 15 ``getTransaction``
calls returns in ~0.3s, so batching is worth roughly an order of magnitude in wall time and,
more importantly, in connection count against the rate limiter.
"""

from __future__ import annotations

import contextlib
import json
import random
import stat
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import httpx

DEFAULT_KEY_FILE: Final[Path] = Path("~/.helius-key")
HELIUS_HOST: Final[str] = "mainnet.helius-rpc.com"

#: The complete set of RPC methods this package may call. Anything not here raises.
READ_METHODS: Final[frozenset[str]] = frozenset(
    {
        "getSignaturesForAddress",
        "getTransaction",
        "getBlockTime",
        "getSlot",
        "getHealth",
        "getTokenAccountsByOwner",
    }
)

#: The SPL Token program. ``getTokenAccountsByOwner`` requires a filter and this is the one
#: that means "every token account this address owns", which is exactly what a pool's vault
#: set is (``shitcoims_cluster.pools``: vaults are the token accounts owned by the pool).
TOKEN_PROGRAM: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
#: Token-2022. A pool can hold a leg in either program, so both are asked for.
TOKEN_2022_PROGRAM: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

#: Helius caps ``getSignaturesForAddress`` at 1000 per call.
MAX_SIGNATURE_LIMIT: Final[int] = 1000
#: The prompt's gentleness budget: 25 transactions per batched call.
DEFAULT_TX_BATCH: Final[int] = 25


class RpcError(RuntimeError):
    """An RPC call failed. Never carries a URL, because the URL carries the API key."""


class SecretError(RuntimeError):
    pass


def read_secret_file(path: Path, *, required: bool = True) -> str | None:
    """Read a secret, refusing a group/world-readable file. Pattern from the sentinel."""

    try:
        info = path.stat()
    except FileNotFoundError:
        if required:
            raise SecretError(f"required secret file is missing: {path}") from None
        return None
    if not stat.S_ISREG(info.st_mode):
        raise SecretError(f"secret path is not a regular file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise SecretError(f"secret file must not be group/world accessible: {path} is {mode:o}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        if required:
            raise SecretError(f"secret file is empty: {path}")
        return None
    return value


def _safe_error(method: str, exc: Exception) -> RpcError:
    return RpcError(f"Helius {method} transport failed ({type(exc).__name__})")


class HeliusRpc:
    """One HTTP client against one Helius endpoint. Synchronous by design.

    A poll loop over six pools does not need an event loop, and a synchronous client is
    testable without a network stub that has to imitate asyncio.
    """

    def __init__(
        self,
        *,
        key_file: Path | None = None,
        commitment: str = "confirmed",
        timeout: float = 60.0,
        max_attempts: int = 6,
        sleep: Any = time.sleep,
        client: httpx.Client | None = None,
    ) -> None:
        path = (key_file if key_file is not None else DEFAULT_KEY_FILE).expanduser()
        key = read_secret_file(path, required=True)
        assert key is not None
        self._url = f"https://{HELIUS_HOST}/?api-key={key}"
        self._commitment = commitment
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._request_id = 0
        self.calls = 0
        self.rate_limit_waits = 0

    # -- lifecycle -------------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HeliusRpc:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def commitment(self) -> str:
        return self._commitment

    # -- transport -------------------------------------------------------------------

    def _post(self, payload: Any, *, method_label: str) -> Any:
        """POST with 429/5xx backoff. Honours ``Retry-After`` when the server sends one."""

        delay = 0.5
        last: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(self._url, json=payload)
            except httpx.HTTPError as exc:
                last = exc
                if attempt == self._max_attempts - 1:
                    raise _safe_error(method_label, exc) from exc
                self._sleep(delay + random.random() * 0.25)
                delay = min(delay * 2, 16.0)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                self.rate_limit_waits += 1
                retry_after = response.headers.get("retry-after")
                wait = delay
                if retry_after:
                    with contextlib.suppress(ValueError):
                        wait = max(wait, float(retry_after))
                if attempt == self._max_attempts - 1:
                    raise RpcError(
                        f"Helius {method_label} still returning {response.status_code} "
                        f"after {self._max_attempts} attempts"
                    )
                # Jitter, so six pools backing off together do not resynchronise.
                self._sleep(wait + random.random() * 0.25)
                delay = min(delay * 2, 16.0)
                continue
            if response.status_code >= 400:
                raise RpcError(f"Helius {method_label} returned HTTP {response.status_code}")
            try:
                return response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                last = exc
                if attempt == self._max_attempts - 1:
                    raise _safe_error(method_label, exc) from exc
                self._sleep(delay)
                delay = min(delay * 2, 16.0)
        assert last is not None  # pragma: no cover - loop always returns or raises
        raise _safe_error(method_label, last)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def call(self, method: str, params: Sequence[Any]) -> Any:
        if method not in READ_METHODS:
            raise RpcError(f"{method} is not a read-only method this package may call")
        self.calls += 1
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": list(params)}
        payload = self._post(body, method_label=method)
        if isinstance(payload, list):  # pragma: no cover - servers do not batch a single object
            payload = payload[0]
        if not isinstance(payload, dict):
            raise RpcError(f"Helius {method} returned a non-object response")
        if payload.get("error") is not None:
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise RpcError(f"Helius {method} returned error {code}")
        if "result" not in payload:
            raise RpcError(f"Helius {method} omitted result")
        return payload["result"]

    def call_batch(self, method: str, params_list: Sequence[Sequence[Any]]) -> list[Any]:
        """One JSON-RPC array request. Results are returned in the order asked for.

        A per-item error becomes ``None`` in the returned list rather than an exception: one
        pruned transaction must not discard the other twenty-four in the batch. The caller
        routes the ``None`` to the defect stream, which is where an unrecoverable row belongs.
        """

        if method not in READ_METHODS:
            raise RpcError(f"{method} is not a read-only method this package may call")
        if not params_list:
            return []
        self.calls += 1
        ids = [self._next_id() for _ in params_list]
        body = [
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": list(params)}
            for rid, params in zip(ids, params_list, strict=True)
        ]
        payload = self._post(body, method_label=method)
        if isinstance(payload, dict):
            # A server that rejects the whole batch answers with a single error object.
            if payload.get("error") is not None:
                error = payload["error"]
                code = error.get("code") if isinstance(error, dict) else "unknown"
                raise RpcError(f"Helius batched {method} returned error {code}")
            raise RpcError(f"Helius batched {method} returned a single object, not an array")
        if not isinstance(payload, list):
            raise RpcError(f"Helius batched {method} returned a non-array response")
        by_id: dict[int, Any] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if isinstance(rid, int):
                by_id[rid] = None if item.get("error") is not None else item.get("result")
        return [by_id.get(rid) for rid in ids]

    # -- typed reads -----------------------------------------------------------------

    def signatures_for_address(
        self,
        address: str,
        *,
        limit: int = MAX_SIGNATURE_LIMIT,
        before: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first page of signatures. Each entry carries ``blockTime`` directly.

        That last clause is the whole reason this collector polls instead of subscribing:
        ``transactionNotification`` on the websocket carries a slot but **no block time**, and
        a recorder that took it anyway produced 169 of 169 live rows with no event clock
        (SWARM.md, Track B). Here the block time arrives in the same response as the
        signature, so it can be made mandatory without a second round trip.
        """

        options: dict[str, Any] = {
            "limit": max(1, min(int(limit), MAX_SIGNATURE_LIMIT)),
            "commitment": self._commitment,
        }
        if before is not None:
            options["before"] = before
        if until is not None:
            options["until"] = until
        result = self.call("getSignaturesForAddress", [address, options])
        if not isinstance(result, list):
            raise RpcError("getSignaturesForAddress returned a non-array result")
        return [item for item in result if isinstance(item, dict)]

    def token_accounts_by_owner(self, owner: str) -> list[dict[str, Any]]:
        """Every SPL token account owned by ``owner``, across both token programs.

        This is how a pool's vault addresses are *discovered* rather than tabulated.
        ``pools.py`` is deliberate that "a pool's vaults are exactly the token accounts whose
        owner is the pool address", and states that a hard-coded per-DEX vault table would be
        a second source of truth that drifts. This asks the chain the same question the
        parser asks of each transaction, so the two cannot disagree.

        Returns one dict per account with ``account``, ``mint``, ``amount`` (raw, as a decimal
        string — never a float) and ``decimals``.
        """

        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            result = self.call(
                "getTokenAccountsByOwner",
                [owner, {"programId": program}, {"encoding": "jsonParsed", "commitment": self._commitment}],
            )
            value = result.get("value") if isinstance(result, dict) else None
            if not isinstance(value, list):
                raise RpcError("getTokenAccountsByOwner returned no account array")
            for item in value:
                if not isinstance(item, dict):
                    continue
                account = str(item.get("pubkey", ""))
                info = (
                    ((item.get("account") or {}).get("data") or {}).get("parsed") or {}
                ).get("info") or {}
                amount = (info.get("tokenAmount") or {}).get("amount")
                if not account or account in seen or not isinstance(info.get("mint"), str):
                    continue
                seen.add(account)
                found.append(
                    {
                        "account": account,
                        "mint": str(info["mint"]),
                        "amount": str(amount) if amount is not None else None,
                        "decimals": (info.get("tokenAmount") or {}).get("decimals"),
                        "token_program": program,
                    }
                )
        return sorted(found, key=lambda a: a["account"])

    def transactions(self, signatures: Sequence[str]) -> list[dict[str, Any] | None]:
        """Fetch transactions in one batched call. ``None`` where the node had nothing."""

        params = [
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": self._commitment,
                },
            ]
            for signature in signatures
        ]
        results = self.call_batch("getTransaction", params)
        return [item if isinstance(item, dict) else None for item in results]
