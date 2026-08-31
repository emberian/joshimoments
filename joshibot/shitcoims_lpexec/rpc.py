"""Helius, read-and-simulate only.

The method allowlist is the same device `shitcoims_cluster/rpc.py` uses: a frozenset checked
before the request is built, so "this client cannot broadcast" is a property of the code
rather than a promise in a docstring. `sendTransaction` is not in it. When live sending is
eventually wired up it will need a deliberate edit here, visible in a diff, rather than a
caller passing a different method name.

THE KEY NEVER REACHES AN EXCEPTION MESSAGE. httpx puts the request URL in its transport
errors and the Helius URL *is* the credential, so every transport failure is re-raised
carrying only the exception's class name. Same defence, same reason, as the two packages
that arrived at it before this one.
"""

from __future__ import annotations

import base64
import random
import struct
import time
from pathlib import Path
from typing import Any, Final

import httpx
from solders.pubkey import Pubkey

from .allowlist import DLMM_PROGRAM
from .secrets import read_secret_file

HELIUS_HOST: Final[str] = "mainnet.helius-rpc.com"
DEFAULT_KEY_FILE: Final[Path] = Path("~/.helius-key")

READ_METHODS: Final[frozenset[str]] = frozenset(
    {
        "getAccountInfo",
        "getMultipleAccounts",
        "getBalance",
        "getTokenAccountsByOwner",
        "getLatestBlockhash",
        "getSlot",
        "getBlockHeight",
        "getSignatureStatuses",
        "isBlockhashValid",
        "simulateTransaction",
    }
)

_DLMM_KEY: Final[Pubkey] = Pubkey.from_string(DLMM_PROGRAM)
LBPAIR_ACCOUNT_SIZE: Final[int] = 904
# Offsets confirmed by decoding the live nosis/weave LbPair on 2026-08-15 and matching the
# result against the datapi's own report of the same pool: active bin 17, bin step 200,
# token X nosis, token Y weave. A layout you have not checked against chain is a guess.
LBPAIR_ACTIVE_ID_OFFSET: Final[int] = 76
LBPAIR_BIN_STEP_OFFSET: Final[int] = 80
LBPAIR_TOKEN_X_OFFSET: Final[int] = 88
LBPAIR_TOKEN_Y_OFFSET: Final[int] = 120


class RpcError(RuntimeError):
    pass


def bin_array_key(lb_pair: str, index: int) -> Pubkey:
    """PDA for a shared bin array. Seeds `["bin_array", lb_pair, i64_le(index)]`.

    Cross-checked against `@meteora-ag/dlmm`'s own `deriveBinArray` for indexes 0, 1 and -9
    in the test suite, because a wrong seed here would silently report every bin array as
    virgin and over-price every plan by 0.071 SOL a pop.
    """
    key, _bump = Pubkey.find_program_address(
        [b"bin_array", bytes(Pubkey.from_string(lb_pair)), struct.pack("<q", index)],
        _DLMM_KEY,
    )
    return key


class HeliusRpc:
    def __init__(
        self,
        *,
        key_file: Path | None = None,
        commitment: str = "confirmed",
        timeout: float = 60.0,
        max_attempts: int = 5,
        client: httpx.Client | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        path = (key_file if key_file is not None else DEFAULT_KEY_FILE).expanduser()
        key = read_secret_file(path, required=True)
        assert key is not None
        self._url = f"https://{HELIUS_HOST}/?api-key={key}"
        self._commitment = commitment
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._owned = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._id = 0
        self.calls = 0

    def __enter__(self) -> HeliusRpc:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in READ_METHODS:
            raise RpcError(f"{method} is not a method this package may call")
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        delay = 0.5
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(self._url, json=payload)
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts - 1:
                    raise RpcError(f"Helius {method} transport failed ({type(exc).__name__})") from None
                self._sleep(delay + random.random() * 0.25)
                delay = min(delay * 2, 16.0)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self._max_attempts - 1:
                    raise RpcError(f"Helius {method} still returning {response.status_code}")
                self._sleep(delay + random.random() * 0.25)
                delay = min(delay * 2, 16.0)
                continue
            if response.status_code >= 400:
                raise RpcError(f"Helius {method} returned HTTP {response.status_code}")
            self.calls += 1
            body = response.json()
            if not isinstance(body, dict):
                raise RpcError(f"Helius {method} returned a non-object response")
            if body.get("error") is not None:
                code = body["error"].get("code") if isinstance(body["error"], dict) else "?"
                message = body["error"].get("message") if isinstance(body["error"], dict) else ""
                raise RpcError(f"Helius {method} returned error {code}: {message}")
            if "result" not in body:
                raise RpcError(f"Helius {method} omitted result")
            return body["result"]
        raise RpcError(f"Helius {method} exhausted {self._max_attempts} attempts")

    # -- reads ---------------------------------------------------------------------------

    def account_data(self, address: str) -> bytes:
        result = self.call("getAccountInfo", [address, {"encoding": "base64"}])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise RpcError(f"account {address} does not exist")
        return base64.b64decode(value["data"][0])

    def accounts_exist(self, addresses: list[str]) -> dict[str, bool]:
        """Which of these accounts are on chain. One call; order preserved by the RPC."""
        if not addresses:
            return {}
        result = self.call("getMultipleAccounts", [addresses, {"encoding": "base64"}])
        values = result.get("value") if isinstance(result, dict) else None
        if not isinstance(values, list) or len(values) != len(addresses):
            raise RpcError("getMultipleAccounts returned a mismatched value list")
        return {address: value is not None for address, value in zip(addresses, values, strict=True)}

    def existing_bin_arrays(self, lb_pair: str, indexes: list[int]) -> frozenset[int]:
        """Which of these bin arrays already exist, i.e. which ones we do NOT have to pay for."""
        if not indexes:
            return frozenset()
        keys = {index: str(bin_array_key(lb_pair, index)) for index in indexes}
        present = self.accounts_exist(list(keys.values()))
        return frozenset(index for index, key in keys.items() if present.get(key))

    def sol_balance(self, address: str) -> int:
        result = self.call("getBalance", [address, {"commitment": self._commitment}])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, int):
            raise RpcError("getBalance returned no lamport value")
        return value

    def lb_pair_state(self, address: str) -> dict[str, Any]:
        raw = self.account_data(address)
        if len(raw) != LBPAIR_ACCOUNT_SIZE:
            raise RpcError(f"{address} is not a {LBPAIR_ACCOUNT_SIZE}-byte LbPair account")
        return {
            "address": address,
            "active_id": struct.unpack_from("<i", raw, LBPAIR_ACTIVE_ID_OFFSET)[0],
            "bin_step": struct.unpack_from("<H", raw, LBPAIR_BIN_STEP_OFFSET)[0],
            "token_x_mint": str(Pubkey.from_bytes(raw[LBPAIR_TOKEN_X_OFFSET : LBPAIR_TOKEN_X_OFFSET + 32])),
            "token_y_mint": str(Pubkey.from_bytes(raw[LBPAIR_TOKEN_Y_OFFSET : LBPAIR_TOKEN_Y_OFFSET + 32])),
        }

    def latest_blockhash(self) -> tuple[str, int]:
        result = self.call("getLatestBlockhash", [{"commitment": self._commitment}])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise RpcError("getLatestBlockhash returned no value")
        return str(value["blockhash"]), int(value["lastValidBlockHeight"])

    def simulate(
        self, encoded: str, *, sig_verify: bool = False, addresses: list[str] | None = None
    ) -> dict[str, Any]:
        """Simulate, and return the decoded effect rather than the raw envelope.

        `sig_verify=False` with `replaceRecentBlockhash=True` is what lets an UNSIGNED
        transaction be simulated -- which is the whole dry-run story: the plan is proven
        against live chain state on a machine that has never held the key.
        `studies/RESULT_execution_landing.md` §8 requires the replace-blockhash form for the
        compute-unit reading to be usable.
        """
        options: dict[str, Any] = {
            "commitment": self._commitment,
            "encoding": "base64",
            "sigVerify": sig_verify,
            "replaceRecentBlockhash": not sig_verify,
            "innerInstructions": False,
        }
        if addresses:
            options["accounts"] = {"encoding": "base64", "addresses": addresses}
        result = self.call("simulateTransaction", [encoded, options])
        value = result.get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise RpcError("simulateTransaction returned malformed data")
        return {
            "err": value.get("err"),
            "units_consumed": value.get("unitsConsumed"),
            "logs": value.get("logs") or [],
            "accounts": value.get("accounts"),
        }
