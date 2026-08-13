import os
from pathlib import Path

import httpx
import pytest

from shitcoims_sentinel.clients import ExternalServiceError, JupiterClient, PumpMetadataClient
from shitcoims_sentinel.config import JupiterConfig
from shitcoims_sentinel.domain import WSOL_MINT


def jupiter_config(tmp_path: Path) -> JupiterConfig:
    secret = tmp_path / "jupiter"
    secret.write_text("test-key", encoding="utf-8")
    os.chmod(secret, 0o600)
    return JupiterConfig(
        secret,
        "https://api.jup.ag/swap/v2",
        1500,
        5_000_000,
        ("jupiterz", "dflow", "okx"),
    )


@pytest.mark.asyncio
async def test_jupiter_quote_uses_execution_router_constraints(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["excludeRouters"] == "jupiterz,dflow,okx"
        return httpx.Response(
            200,
            json={
                "inputMint": "mint",
                "outputMint": WSOL_MINT,
                "inAmount": "100",
                "outAmount": "10",
                "otherAmountThreshold": "8",
                "router": "metis",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        quote = await JupiterClient(jupiter_config(tmp_path), http).quote_exit("mint", 100)
    assert quote.out_lamports == 10


@pytest.mark.asyncio
async def test_jupiter_quote_rejects_metadata_mismatch(tmp_path: Path) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "inputMint": "attacker",
                "outputMint": WSOL_MINT,
                "inAmount": "100",
                "outAmount": "10",
                "otherAmountThreshold": "8",
                "router": "metis",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ExternalServiceError, match="does not match"):
            await JupiterClient(jupiter_config(tmp_path), http).quote_exit("mint", 100)


@pytest.mark.asyncio
async def test_pump_metadata_is_bounded_and_advisory() -> None:
    mint = "mint"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "frontend-api-v3.pump.fun"
        return httpx.Response(
            200,
            json={
                "mint": mint,
                "name": "A" * 500,
                "symbol": "TOK",
                "creator": "creator",
                "complete": False,
                "market_cap": 12.5,
                "usd_market_cap": 2500,
                "created_timestamp": 1_700_000_000_000,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        metadata = await PumpMetadataClient(http, cache_seconds=60).token(mint)
    assert metadata is not None
    assert len(metadata.name or "") == 160
    assert metadata.complete is False
