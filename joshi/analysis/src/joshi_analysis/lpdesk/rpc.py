"""A bounded, retaining Solana JSON-RPC session against Helius.

Three properties, enforced structurally rather than by discipline:

* **Bounded.** The session is constructed with a hard call budget; call ``n+1`` past it
  raises :class:`BudgetExhausted` before any socket is opened. A JSON-RPC batch counts as
  as many calls as it carries, so batching saves latency, never budget accounting.
* **Retaining.** Every request's method and params and every response body land verbatim in
  a JSON-lines retention file before the response is returned to the caller, so any number
  derived later points back at retained bytes rather than a memory of a socket.
* **Credential-clean.** The API key is read from its file per request, travels only in the
  URL query, and appears in no retained byte, no exception, and no log — errors are
  re-raised carrying the host name only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .vocabulary import RETENTION_CONTRACT

__all__ = ["BudgetExhausted", "RetainingSession", "RpcError"]

DEFAULT_KEY_PATH = Path.home() / ".helius-key"
_HOST = "mainnet.helius-rpc.com"


class BudgetExhausted(Exception):
    """The declared request budget is spent; the session refuses, it does not stretch."""


class RpcError(Exception):
    """A transport or JSON-RPC failure, with the credential already scrubbed."""


class RetainingSession:
    def __init__(
        self,
        retention_dir: Path,
        budget: int,
        key_path: Path = DEFAULT_KEY_PATH,
        min_interval_s: float = 0.25,
    ) -> None:
        self.retention_dir = Path(retention_dir)
        self.retention_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.spent = 0
        self.key_path = key_path
        self.min_interval_s = min_interval_s
        self._last_call_monotonic = 0.0
        self._log_path = self.retention_dir / "rpc_log.jsonl"
        if not self._log_path.exists():
            header = {
                "contract": RETENTION_CONTRACT,
                "host": _HOST,
                "budget": budget,
                "opened_unix_ms": int(time.time() * 1000),
            }
            self._log_path.write_text(json.dumps(header) + "\n")

    def _key(self) -> str:
        return self.key_path.read_text().strip()

    def _charge(self, calls: int) -> None:
        if self.spent + calls > self.budget:
            raise BudgetExhausted(
                f"budget {self.budget} would be exceeded ({self.spent} spent, {calls} asked)"
            )
        self.spent += calls

    def _post(self, body: bytes) -> dict | list:
        wait = self.min_interval_s - (time.monotonic() - self._last_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(
            f"https://{_HOST}/?api-key={self._key()}",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise RpcError(f"{_HOST} answered HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise RpcError(f"{_HOST} unreachable: {error.reason}") from None
        finally:
            self._last_call_monotonic = time.monotonic()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise RpcError(f"{_HOST} answered non-JSON ({len(raw)} bytes)") from None

    def _retain(self, method: str, params: list, response: dict) -> None:
        row = {
            "seq": self.spent,
            "method": method,
            "params": params,
            "received_unix_ms": int(time.time() * 1000),
            "response": response,
        }
        with self._log_path.open("a") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")

    def call(self, method: str, params: list) -> dict | list | None:
        """One JSON-RPC call: charged, retained, result returned (RPC errors raise)."""
        self._charge(1)
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self.spent, "method": method, "params": params}
        ).encode()
        response = self._post(body)
        if not isinstance(response, dict):
            raise RpcError(f"{_HOST} answered a non-object for a single call")
        self._retain(method, params, response)
        if "error" in response:
            raise RpcError(f"{method} refused: {response['error'].get('message', 'no message')}")
        return response.get("result")

    def batch(self, method: str, params_list: list[list]) -> list:
        """One HTTP round trip of many calls, charged one budget unit per call.

        Results come back in request order; a per-item RPC error is carried as ``None`` in
        that slot (and the full body is retained), because one bad signature must not void
        its whole batch.
        """
        if not params_list:
            return []
        self._charge(len(params_list))
        body = json.dumps(
            [
                {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
                for index, params in enumerate(params_list)
            ]
        ).encode()
        response = self._post(body)
        if not isinstance(response, list):
            raise RpcError(f"{_HOST} answered a non-array for a batch")
        self._retain(method, ["batch", len(params_list), params_list], {"batch": response})
        by_id: dict[int, dict] = {
            item["id"]: item for item in response if isinstance(item.get("id"), int)
        }
        return [
            (by_id.get(index) or {}).get("result") for index in range(len(params_list))
        ]
