"""The execution-facing client primitives: signature resolution and minimum output."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from shitcoims_sentinel.clients import (
    SIMULATION_ADDRESS_LIMIT,
    ExternalServiceError,
    JupiterClient,
    SolanaRpc,
    exit_slippage_bps,
    minimum_output_floor,
)
from shitcoims_sentinel.config import JupiterConfig, RpcConfig
from shitcoims_sentinel.domain import WSOL_MINT


def jupiter_config(tmp_path: Path, *, slippage_bps: int = 1500) -> JupiterConfig:
    secret = tmp_path / "jupiter"
    secret.write_text("test-key", encoding="utf-8")
    os.chmod(secret, 0o600)
    return JupiterConfig(
        secret,
        "https://api.jup.ag/swap/v2",
        slippage_bps,
        5_000_000,
        ("jupiterz", "dflow", "okx"),
    )


def rpc_config(tmp_path: Path) -> RpcConfig:
    secret = tmp_path / "helius"
    secret.write_text("helius-key", encoding="utf-8")
    os.chmod(secret, 0o600)
    return RpcConfig(
        secret,
        "https://mainnet.helius-rpc.com/?api-key={api_key}",
        "wss://mainnet.helius-rpc.com/?api-key={api_key}",
        "confirmed",
    )


def rpc_responder(results: list[Any]) -> Any:
    calls: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        calls.append(payload)
        index = min(len(calls) - 1, len(results) - 1)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": results[index]})

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


def order_body(*, out_amount: int, threshold: int, mint: str = "mint", amount: int = 100) -> dict:
    return {
        "transaction": "dHg=",
        "requestId": "request-1",
        "inputMint": mint,
        "outputMint": WSOL_MINT,
        "inAmount": str(amount),
        "outAmount": str(out_amount),
        "otherAmountThreshold": str(threshold),
        "router": "metis",
    }


def test_minimum_output_floor_is_integer_math_on_lamports() -> None:
    assert minimum_output_floor(1_000_000_000, 250) == 975_000_000
    assert minimum_output_floor(1_000_000_000, 1500) == 850_000_000
    # No float rounding may push the floor above the honest value.
    assert minimum_output_floor(3, 250) == 2


def test_exit_slippage_is_tight_for_ordinary_exits_and_wide_only_on_panic(
    tmp_path: Path,
) -> None:
    config = jupiter_config(tmp_path, slippage_bps=1500)

    assert exit_slippage_bps("exit_trail", config) == 250
    assert exit_slippage_bps("exit_stop", config) == 250
    assert exit_slippage_bps("exit_scale", config) == 250
    assert exit_slippage_bps("exit_dispose", config) == 250
    assert exit_slippage_bps("panic", config) == 1500
    assert exit_slippage_bps("exit_rug", config) == 1500


def test_configured_slippage_stays_the_ceiling_for_ordinary_exits(tmp_path: Path) -> None:
    tight = jupiter_config(tmp_path, slippage_bps=100)
    assert exit_slippage_bps("exit_trail", tight) == 100
    assert exit_slippage_bps("panic", tight) == 100


@pytest.mark.asyncio
async def test_executable_order_sends_the_requested_slippage(tmp_path: Path) -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["slippageBps"])
        return httpx.Response(200, json=order_body(out_amount=1_000_000, threshold=975_000))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = JupiterClient(jupiter_config(tmp_path), http)
        await client.executable_order("mint", 100, "taker", slippage_bps=250)
        await client.executable_order("mint", 100, "taker")

    assert seen == ["250", "1500"]


@pytest.mark.asyncio
async def test_executable_order_rejects_a_threshold_below_the_computed_floor(
    tmp_path: Path,
) -> None:
    """A router that ignores our slippage must not be able to pay away the exit."""

    async def handler(_request: httpx.Request) -> httpx.Response:
        # 15% haircut returned for a 2.5% request.
        return httpx.Response(200, json=order_body(out_amount=1_000_000, threshold=850_000))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = JupiterClient(jupiter_config(tmp_path), http)
        with pytest.raises(ExternalServiceError, match="below the 250bps floor"):
            await client.executable_order("mint", 100, "taker", slippage_bps=250)


@pytest.mark.asyncio
async def test_signature_status_separates_unknown_failed_pending_and_confirmed(
    tmp_path: Path,
) -> None:
    handler = rpc_responder(
        [
            {"value": [None]},
            {"value": [{"err": {"InstructionError": [3, "custom"]}}]},
            {"value": [{"err": None, "confirmationStatus": "processed"}]},
            {"value": [{"err": None, "confirmationStatus": "finalized"}]},
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rpc = SolanaRpc(rpc_config(tmp_path), http)
        assert await rpc.signature_status("sig") == "unknown"
        assert await rpc.signature_status("sig") == "failed"
        assert await rpc.signature_status("sig") == "pending"
        assert await rpc.signature_status("sig") == "confirmed"


@pytest.mark.asyncio
async def test_signature_confirmed_still_means_only_confirmed(tmp_path: Path) -> None:
    handler = rpc_responder([{"value": [{"err": None, "confirmationStatus": "processed"}]}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rpc = SolanaRpc(rpc_config(tmp_path), http)
        assert await rpc.signature_confirmed("sig") is False


@pytest.mark.asyncio
async def test_blockhash_validity_is_read_as_a_boolean(tmp_path: Path) -> None:
    handler = rpc_responder([{"value": False}, {"value": True}, {"value": "maybe"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rpc = SolanaRpc(rpc_config(tmp_path), http)
        assert await rpc.blockhash_valid("hash") is False
        assert await rpc.blockhash_valid("hash") is True
        with pytest.raises(ExternalServiceError, match="blockhash validity"):
            await rpc.blockhash_valid("hash")


@pytest.mark.asyncio
async def test_oversized_simulation_set_is_rejected_with_an_explicit_ceiling(
    tmp_path: Path,
) -> None:
    handler = rpc_responder([{"value": {}}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rpc = SolanaRpc(rpc_config(tmp_path), http)
        addresses = [f"account-{index}" for index in range(SIMULATION_ADDRESS_LIMIT + 1)]
        with pytest.raises(ExternalServiceError, match="exceeds the 32-address ceiling"):
            await rpc.simulate_transaction_accounts("tx", addresses)
        with pytest.raises(ExternalServiceError, match="duplicate"):
            await rpc.simulate_transaction_accounts("tx", ["a", "a"])
        with pytest.raises(ExternalServiceError, match="empty"):
            await rpc.simulate_transaction_accounts("tx", [])
    assert handler.calls == []  # type: ignore[attr-defined]
