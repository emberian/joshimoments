"""Helius RPC for the gate: mint decimals and raw token balances.

Two rules, both load-bearing:
- The API key rides in the URL. Exceptions are never stringified into logs or
  user-visible text — only type names.
- A provider failure is ALWAYS an exception, never a zero. The sweep's
  never-kick-on-outage guarantee depends on this distinction: an empty (but
  well-formed) token-account list is a real zero; anything malformed is not.
"""

from __future__ import annotations

import httpx


class HeliusError(RuntimeError):
    pass


class Helius:
    def __init__(self, api_key: str, http: httpx.AsyncClient):
        self._url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"
        self.http = http

    async def _rpc(self, method: str, params: list) -> object:
        try:
            response = await self.http.post(
                self._url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=httpx.Timeout(20, connect=5),
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise HeliusError(f"Helius {method} failed ({type(exc).__name__})") from None
        if not isinstance(body, dict) or "error" in body or "result" not in body:
            raise HeliusError(f"Helius {method} returned an error or malformed body")
        return body["result"]

    async def mint_decimals(self, mint: str) -> int:
        """On-chain decimals via getTokenSupply — never assumed."""

        result = await self._rpc("getTokenSupply", [mint])
        value = result.get("value") if isinstance(result, dict) else None
        decimals = value.get("decimals") if isinstance(value, dict) else None
        if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 18:
            raise HeliusError("Helius getTokenSupply returned no usable decimals")
        return decimals

    async def balance_raw(self, owner: str, mint: str) -> int:
        """Sum of raw units across ALL of the owner's token accounts for this mint."""

        result = await self._rpc(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
        )
        accounts = result.get("value") if isinstance(result, dict) else None
        if not isinstance(accounts, list):
            raise HeliusError("Helius getTokenAccountsByOwner returned a malformed account list")
        total = 0
        for entry in accounts:
            try:
                amount = entry["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]
            except (KeyError, TypeError):
                raise HeliusError("Helius token account entry is malformed") from None
            if not isinstance(amount, str) or not amount.isdigit():
                raise HeliusError("Helius token amount is not a raw integer string")
            total += int(amount)
        return total
