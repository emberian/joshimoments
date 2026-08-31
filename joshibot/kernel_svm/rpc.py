"""Read-only mainnet RPC, keyed from ~/.helius-key.

The key never appears in a return value, an exception message, or a log line: every error
carries the *method* and the redacted host, never the URL. Callers that want to print what
went wrong can print the exception without leaking the credential into a transcript.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_KEY_PATH = Path.home() / ".helius-key"
_HOST = "mainnet.helius-rpc.com"


class RpcUnavailable(RuntimeError):
    """No usable RPC endpoint. Never carries the URL or the key."""


def _endpoint() -> str:
    if not _KEY_PATH.exists():
        raise RpcUnavailable(f"{_KEY_PATH} is missing; this harness needs a read-only mainnet RPC")
    key = _KEY_PATH.read_text().strip()
    if not key:
        raise RpcUnavailable(f"{_KEY_PATH} is empty")
    return f"https://{_HOST}/?api-key={key}"


def rpc(method: str, params: list[Any], *, retries: int = 4, timeout: float = 60.0) -> Any:
    """One JSON-RPC call. Raises RpcUnavailable on transport failure, RuntimeError on an RPC error."""
    url = _endpoint()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.load(resp)
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt == retries - 1:
                raise RpcUnavailable(f"{method} failed against {_HOST}: {type(exc).__name__}") from None
            time.sleep(0.6 * (2**attempt))
    else:  # pragma: no cover - loop always breaks or raises
        raise RpcUnavailable(f"{method} failed against {_HOST}: {last!r}")

    if "error" in payload:
        raise RuntimeError(f"{method} returned an RPC error: {payload['error']}")
    return payload["result"]


def get_account(pubkey: str) -> dict[str, Any] | None:
    return rpc("getAccountInfo", [pubkey, {"encoding": "base64", "commitment": "confirmed"}])["value"]


def get_multiple_accounts_at_slot(pubkeys: list[str]) -> tuple[int, list[dict[str, Any] | None]]:
    """One getMultipleAccounts call, returning the slot the RPC read them at.

    Deliberately not chunked. Chunking would read different keys at different slots, and a
    snapshot stitched across slots is not a state any validator ever held -- replaying a
    recorded swap against it would compare the program to a fiction. Callers must keep the
    account set under the 100-key RPC limit; exceeding it raises rather than splitting.
    """
    if len(pubkeys) > 100:
        raise RuntimeError(
            f"{len(pubkeys)} keys exceeds the 100-key limit; a chunked read would straddle slots"
        )
    params = [pubkeys, {"encoding": "base64", "commitment": "confirmed"}]
    result = rpc("getMultipleAccounts", params)
    return int(result["context"]["slot"]), result["value"]


def get_multiple_accounts(pubkeys: list[str]) -> list[dict[str, Any] | None]:
    """getMultipleAccounts, chunked at the 100-key RPC limit, order preserved.

    Use only where slot-consistency does not matter (e.g. probing which PDAs exist).
    """
    out: list[dict[str, Any] | None] = []
    for i in range(0, len(pubkeys), 100):
        chunk = pubkeys[i : i + 100]
        params = [chunk, {"encoding": "base64", "commitment": "confirmed"}]
        out.extend(rpc("getMultipleAccounts", params)["value"])
    return out


def get_slot() -> int:
    return int(rpc("getSlot", [{"commitment": "confirmed"}]))
