from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import JupiterConfig, RpcConfig
from .domain import (
    PUMP_AMM_PROGRAM,
    PUMP_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    WSOL_MINT,
    ExitQuote,
    MintSafety,
    PoolSnapshot,
    PumpTokenMetadata,
    TokenHolding,
    decimal_from,
    utc_now,
)
from .secrets import read_secret_file

# Helius puts its credential in the query string; transport request logs are secrets.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class ExternalServiceError(RuntimeError):
    pass


def _safe_transport_error(service: str, exc: Exception) -> ExternalServiceError:
    # httpx exceptions can include request URLs. Helius URLs contain the API key.
    return ExternalServiceError(f"{service} transport failed ({type(exc).__name__})")


class SolanaRpc:
    def __init__(self, config: RpcConfig, http: httpx.AsyncClient):
        key = read_secret_file(config.helius_api_key_file, required=True)
        assert key is not None
        self._url = config.http_url_template.format(api_key=key)
        self._websocket_url = config.websocket_url_template.format(api_key=key)
        self._commitment = config.commitment
        self._http = http
        self._request_id = 0

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }
        body = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._http.post(self._url, json=payload)
                response.raise_for_status()
                body = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(0.25 * (2**attempt))
        if body is None:
            assert last_exc is not None
            raise _safe_transport_error("Helius RPC", last_exc) from last_exc
        if body.get("error") is not None:
            error = body["error"]
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise ExternalServiceError(f"Helius RPC {method} returned error {code}")
        if "result" not in body:
            raise ExternalServiceError(f"Helius RPC {method} omitted result")
        return body["result"]

    async def health(self) -> bool:
        return await self.call("getHealth") == "ok"

    async def sol_balance(self, owner: str) -> int:
        result = await self.call("getBalance", [owner, {"commitment": self._commitment}])
        return int(result["value"])

    async def confirmed_slot(self) -> int:
        result = await self.call("getSlot", [{"commitment": self._commitment}])
        try:
            slot = int(result)
        except (TypeError, ValueError) as exc:
            raise ExternalServiceError("Helius returned a malformed confirmed slot") from exc
        if slot < 0:
            raise ExternalServiceError("Helius returned a malformed confirmed slot")
        return slot

    async def token_holdings(self, owner: str) -> list[TokenHolding]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"amount": 0, "decimals": None, "accounts": [], "programs": []}
        )
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            result = await self.call(
                "getTokenAccountsByOwner",
                [
                    owner,
                    {"programId": program},
                    {"commitment": self._commitment, "encoding": "jsonParsed"},
                ],
            )
            for keyed in result.get("value", []):
                try:
                    info = keyed["account"]["data"]["parsed"]["info"]
                    token_amount = info["tokenAmount"]
                    mint = str(info["mint"])
                    amount = int(token_amount["amount"])
                    decimals = int(token_amount["decimals"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ExternalServiceError("Helius returned malformed token account data") from exc
                if amount == 0 or mint == WSOL_MINT:
                    continue
                entry = grouped[mint]
                if entry["decimals"] not in (None, decimals):
                    raise ExternalServiceError(f"inconsistent decimals across token accounts for {mint}")
                entry["amount"] += amount
                entry["decimals"] = decimals
                entry["accounts"].append(str(keyed["pubkey"]))
                entry["programs"].append(program)
        return [
            TokenHolding(
                mint=mint,
                amount=value["amount"],
                decimals=value["decimals"],
                token_accounts=tuple(value["accounts"]),
                program_ids=tuple(sorted(set(value["programs"]))),
            )
            for mint, value in sorted(grouped.items())
        ]

    async def mint_safety(self, mint: str) -> MintSafety:
        result = await self.call(
            "getAccountInfo",
            [mint, {"commitment": self._commitment, "encoding": "jsonParsed"}],
        )
        value = result.get("value")
        try:
            parsed = value["data"]["parsed"]
            info = parsed["info"]
            return MintSafety(
                mint_authority=info.get("mintAuthority"),
                freeze_authority=info.get("freezeAuthority"),
                supply=int(info["supply"]),
                decimals=int(info["decimals"]),
                token_program=str(value["owner"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError(f"cannot parse mint account {mint}") from exc

    async def account_data(self, address: str) -> bytes:
        import base64

        result = await self.call(
            "getAccountInfo",
            [address, {"commitment": self._commitment, "encoding": "base64"}],
        )
        try:
            encoded = result["value"]["data"][0]
            return base64.b64decode(encoded, validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError(f"cannot decode account {address}") from exc

    async def signature_confirmed(self, signature: str) -> bool:
        result = await self.call(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": True}],
        )
        values = result.get("value") if isinstance(result, dict) else None
        if not isinstance(values, list) or len(values) != 1:
            raise ExternalServiceError("Helius returned malformed signature status data")
        status = values[0]
        if status is None or status.get("err") is not None:
            return False
        return status.get("confirmationStatus") in {"confirmed", "finalized"}

    async def simulate_transaction_accounts(
        self, encoded: str, addresses: list[str]
    ) -> dict[str, Any]:
        if not addresses or len(addresses) > 32 or len(addresses) != len(set(addresses)):
            raise ExternalServiceError("simulation account set is invalid or too large")
        result = await self.call(
            "simulateTransaction",
            [
                encoded,
                {
                    "commitment": self._commitment,
                    "encoding": "base64",
                    "sigVerify": True,
                    "innerInstructions": True,
                    "accounts": {"encoding": "base64", "addresses": addresses},
                },
            ],
        )
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise ExternalServiceError("Helius returned malformed simulation data")
        if value.get("err") is not None:
            raise ExternalServiceError("exit transaction simulation failed")
        accounts = value.get("accounts")
        if not isinstance(accounts, list) or len(accounts) != len(addresses):
            raise ExternalServiceError("exit transaction simulation omitted requested accounts")
        return {"accounts": accounts, "units_consumed": value.get("unitsConsumed")}

    async def wallet_activity_stream(self, owner: str):
        """Yield sanitized wallet transaction notices from the standard Solana WS API."""
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:  # pragma: no cover - dependency is installed in production.
            raise ExternalServiceError("wallet activity stream dependency unavailable") from exc

        try:
            async with connect(
                self._websocket_url,
                open_timeout=5,
                close_timeout=3,
                ping_interval=30,
                ping_timeout=15,
                max_size=1_048_576,
                logger=logging.getLogger("shitcoims.websocket.transport"),
            ) as socket:
                self._request_id += 1
                request_id = self._request_id
                await socket.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "logsSubscribe",
                            "params": [
                                {"mentions": [owner]},
                                {"commitment": self._commitment},
                            ],
                        }
                    )
                )
                response = json.loads(await socket.recv())
                if response.get("id") != request_id or not isinstance(response.get("result"), int):
                    raise ExternalServiceError("Helius wallet activity subscription was rejected")
                yield {"type": "ready", "received_at": utc_now().isoformat()}
                async for raw in socket:
                    body = json.loads(raw)
                    if body.get("method") != "logsNotification":
                        continue
                    try:
                        result = body["params"]["result"]
                        value = result["value"]
                        signature = str(value["signature"])
                        slot = int(result["context"]["slot"])
                        failed = value.get("err") is not None
                        logs = value.get("logs") or []
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ExternalServiceError(
                            "Helius wallet activity notification was malformed"
                        ) from exc
                    if len(signature) > 100:
                        raise ExternalServiceError(
                            "Helius wallet activity signature exceeded its size limit"
                        )
                    yield {
                        "type": "activity",
                        "signature": signature,
                        "slot": slot,
                        "failed": failed,
                        "pump_program": any(
                            isinstance(line, str) and PUMP_PROGRAM in line for line in logs[:200]
                        ),
                        "pump_amm_program": any(
                            isinstance(line, str) and PUMP_AMM_PROGRAM in line
                            for line in logs[:200]
                        ),
                        "received_at": utc_now().isoformat(),
                    }
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise _safe_transport_error("Helius wallet activity stream", exc) from exc


class JupiterClient:
    def __init__(self, config: JupiterConfig, http: httpx.AsyncClient):
        self.config = config
        self._http = http
        self._api_key = read_secret_file(config.api_key_file, required=False)

    @property
    def ready(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ExternalServiceError(
                "Jupiter API key missing; put it in the configured mode-0600 file"
            )
        return {"x-api-key": self._api_key}

    async def _get_order(self, params: dict[str, str]) -> dict[str, Any]:
        body = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._http.get(
                    f"{self.config.base_url}/order",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(0.25 * (2**attempt))
        if body is None:
            assert last_exc is not None
            raise _safe_transport_error("Jupiter", last_exc) from last_exc
        if not isinstance(body, dict) or body.get("errorCode"):
            code = body.get("errorCode", "malformed") if isinstance(body, dict) else "malformed"
            raise ExternalServiceError(f"Jupiter order failed with code {code}")
        return body

    async def quote_exit(self, mint: str, amount: int) -> ExitQuote:
        params = {
            "inputMint": mint,
            "outputMint": WSOL_MINT,
            "amount": str(amount),
            "slippageBps": str(self.config.slippage_bps),
        }
        if self.config.excluded_routers:
            params["excludeRouters"] = ",".join(self.config.excluded_routers)
        body = await self._get_order(params)
        try:
            out_amount = int(body["outAmount"])
            threshold_raw = body.get("otherAmountThreshold")
            impact_raw = body.get("priceImpactPct")
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError("Jupiter returned a malformed quote") from exc
        if (
            str(body.get("inputMint")) != mint
            or str(body.get("outputMint")) != WSOL_MINT
            or int(body.get("inAmount", -1)) != amount
        ):
            raise ExternalServiceError("Jupiter quote does not match the exit intent")
        if body.get("router") != "metis":
            raise ExternalServiceError("Jupiter quote did not use the required Metis router")
        if threshold_raw is None or not 0 < int(threshold_raw) <= out_amount:
            raise ExternalServiceError("Jupiter quote returned an invalid minimum output")
        return ExitQuote(
            input_mint=mint,
            input_amount=amount,
            out_lamports=out_amount,
            minimum_out_lamports=(int(threshold_raw) if threshold_raw is not None else None),
            price_impact_pct=(
                decimal_from(impact_raw, field="priceImpactPct") if impact_raw is not None else None
            ),
            router=(str(body["router"]) if body.get("router") else None),
            received_at=utc_now(),
        )

    async def executable_order(self, mint: str, amount: int, taker: str) -> dict[str, Any]:
        params = {
            "inputMint": mint,
            "outputMint": WSOL_MINT,
            "amount": str(amount),
            "taker": taker,
            "slippageBps": str(self.config.slippage_bps),
        }
        if self.config.excluded_routers:
            params["excludeRouters"] = ",".join(self.config.excluded_routers)
        body = await self._get_order(params)
        if not body.get("transaction") or not body.get("requestId"):
            raise ExternalServiceError("Jupiter quoted but did not produce an executable transaction")
        if (
            str(body.get("inputMint")) != mint
            or str(body.get("outputMint")) != WSOL_MINT
            or int(body.get("inAmount", -1)) != amount
        ):
            raise ExternalServiceError("Jupiter executable order does not match the exit intent")
        if body.get("router") != "metis":
            raise ExternalServiceError("Jupiter executable order did not use the required Metis router")
        try:
            out_amount = int(body["outAmount"])
            minimum_output = int(body["otherAmountThreshold"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError("Jupiter executable order omitted output constraints") from exc
        if not 0 < minimum_output <= out_amount:
            raise ExternalServiceError("Jupiter executable order returned invalid output constraints")
        return body

    async def execute(self, *, signed_transaction: str, request_id: str) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{self.config.base_url}/execute",
                headers={**self._headers(), "content-type": "application/json"},
                json={"signedTransaction": signed_transaction, "requestId": request_id},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _safe_transport_error("Jupiter execute", exc) from exc
        if not isinstance(body, dict):
            raise ExternalServiceError("Jupiter execute returned malformed data")
        return body


class PumpMetadataClient:
    """Best-effort, advisory-only Pump.fun metadata. It has no execution capability."""

    BASE_URL = "https://frontend-api-v3.pump.fun"
    MAX_BODY_BYTES = 128_000

    def __init__(self, http: httpx.AsyncClient, *, cache_seconds: float):
        self._http = http
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, PumpTokenMetadata | None]] = {}
        self.health = "unknown"
        self.last_sample_at: str | None = None
        self.last_error_type: str | None = None
        self.requests = 0
        self.successes = 0

    @staticmethod
    def _bounded_text(value: Any, *, limit: int = 160) -> str | None:
        if value is None:
            return None
        text = str(value).replace("\x00", "").strip()
        return text[:limit] or None

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _decimal_optional(value: Any, field: str):
        if value is None:
            return None
        try:
            return decimal_from(value, field=field)
        except ValueError:
            return None

    async def token(self, mint: str) -> PumpTokenMetadata | None:
        cached = self._cache.get(mint)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        self.requests += 1
        try:
            response = await self._http.get(
                f"{self.BASE_URL}/coins-v2/{mint}",
                headers={"accept": "application/json", "origin": "https://pump.fun"},
                timeout=httpx.Timeout(5, connect=3),
            )
            if response.status_code == 404:
                result = None
            else:
                response.raise_for_status()
                if len(response.content) > self.MAX_BODY_BYTES:
                    raise ExternalServiceError("Pump.fun metadata response exceeded size limit")
                body = response.json()
                if not isinstance(body, dict) or str(body.get("mint")) != mint:
                    raise ExternalServiceError("Pump.fun metadata did not match the requested mint")
                complete = body.get("complete")
                mayhem = body.get("mayhem_mode")
                result = PumpTokenMetadata(
                    mint=mint,
                    name=self._bounded_text(body.get("name")),
                    symbol=self._bounded_text(body.get("symbol"), limit=40),
                    creator=self._bounded_text(body.get("creator"), limit=64),
                    complete=complete if isinstance(complete, bool) else None,
                    pool_address=self._bounded_text(body.get("raydium_pool"), limit=64),
                    quote_mint=self._bounded_text(body.get("quote_mint"), limit=64),
                    token_program=self._bounded_text(body.get("token_program"), limit=64),
                    market_cap_sol=self._decimal_optional(body.get("market_cap"), "market_cap"),
                    market_cap_usd=self._decimal_optional(
                        body.get("usd_market_cap"), "usd_market_cap"
                    ),
                    created_at=self._timestamp(body.get("created_timestamp")),
                    last_trade_at=self._timestamp(body.get("last_trade_timestamp")),
                    mayhem_mode=mayhem if isinstance(mayhem, bool) else None,
                    received_at=utc_now(),
                )
            self.successes += 1
            self.health = "healthy"
            self.last_sample_at = utc_now().isoformat()
            self.last_error_type = None
            self._cache[mint] = (now + self._cache_seconds, result)
            return result
        except ExternalServiceError:
            self.health = "degraded"
            self.last_error_type = "ExternalServiceError"
            raise
        except (httpx.HTTPError, ValueError) as exc:
            self.health = "degraded"
            self.last_error_type = type(exc).__name__
            raise _safe_transport_error("Pump.fun metadata", exc) from exc

    def status(self) -> dict[str, Any]:
        success_rate = self.successes / self.requests if self.requests else None
        return {
            "health": self.health,
            "last_sample_at": self.last_sample_at,
            "last_error_type": self.last_error_type,
            "requests": self.requests,
            "successes": self.successes,
            "success_rate": success_rate,
        }

class DexScreenerClient:
    BASE_URL = "https://api.dexscreener.com"

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def _get_json(self, path: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._http.get(
                    f"{self.BASE_URL}{path}", headers={"accept": "application/json"}
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_exc is not None
        raise _safe_transport_error("DexScreener", last_exc) from last_exc

    @staticmethod
    def _snapshot(pair: dict[str, Any], mint: str) -> PoolSnapshot:
        try:
            base_mint = str(pair["baseToken"]["address"])
            quote_mint = str(pair["quoteToken"]["address"])
            liquidity = pair.get("liquidity") or {}
            liquidity_usd = decimal_from(liquidity.get("usd", 0), field="liquidity.usd")
            if base_mint == WSOL_MINT:
                reserve = decimal_from(liquidity.get("base", 0), field="liquidity.base")
                unit = "SOL"
            elif quote_mint == WSOL_MINT:
                reserve = decimal_from(liquidity.get("quote", 0), field="liquidity.quote")
                unit = "SOL"
            else:
                reserve = liquidity_usd
                unit = "USD"
            price_raw = pair.get("priceNative")
            token = pair["baseToken"] if base_mint == mint else pair["quoteToken"]
            return PoolSnapshot(
                pair_address=str(pair["pairAddress"]),
                dex_id=str(pair.get("dexId", "unknown")),
                base_mint=base_mint,
                quote_mint=quote_mint,
                liquidity_usd=liquidity_usd,
                reserve_value=reserve,
                reserve_unit=unit,
                price_native=(
                    decimal_from(price_raw, field="priceNative") if price_raw is not None else None
                ),
                observed_at=utc_now(),
                token_name=(str(token["name"]) if token.get("name") else None),
                token_symbol=(str(token["symbol"]) if token.get("symbol") else None),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError(f"DexScreener returned malformed pool data for {mint}") from exc

    async def discover_primary_pool(self, mint: str) -> PoolSnapshot | None:
        body = await self._get_json(f"/token-pairs/v1/solana/{mint}")
        if not isinstance(body, list):
            raise ExternalServiceError("DexScreener token-pairs returned malformed data")
        candidates = [
            pair
            for pair in body
            if pair.get("chainId") == "solana"
            and mint
            in {
                str((pair.get("baseToken") or {}).get("address")),
                str((pair.get("quoteToken") or {}).get("address")),
            }
        ]
        if not candidates:
            return None

        def rank(pair: dict[str, Any]) -> tuple[float, int]:
            pair_mints = {
                str((pair.get("baseToken") or {}).get("address")),
                str((pair.get("quoteToken") or {}).get("address")),
            }
            direct_sol = int(WSOL_MINT in pair_mints)
            liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
            # Economic relevance dominates denomination. A tiny attacker-created
            # SOL pool must not outrank the token's real liquid venue.
            return liquidity, direct_sol

        return self._snapshot(max(candidates, key=rank), mint)

    async def pool(self, mint: str, pair_address: str) -> PoolSnapshot | None:
        body = await self._get_json(f"/latest/dex/pairs/solana/{pair_address}")
        pairs = body.get("pairs") if isinstance(body, dict) else None
        if not pairs:
            return None
        matching = [pair for pair in pairs if str(pair.get("pairAddress")) == pair_address]
        return self._snapshot(matching[0], mint) if matching else None
