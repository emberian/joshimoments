"""Talk to the Node builder. One subprocess per request, no daemon, no port.

WHY A REAL SDK AND WHY A SIDECAR.

The alternative was hand-writing Meteora's instruction layouts in Python. That would have
meant reimplementing: the Q64.64 bin price ladder, `binIdToBinArrayIndex` and the bin-array
PDA coverage rules, the three liquidity strategy parameter encodings, bin-array bitmap
extension handling, position resizing for ranges over 70 bins, the token-2022 transfer-hook
extra-account resolution, and the exact account ordering of ten add/remove variants. Every
one of those is version-coupled to an on-chain program that ships new instruction variants
regularly -- `add_liquidity2`, `remove_liquidity_by_range2` and `claim_fee2` all postdate
the original SDK. A hand-rolled port is a permanent, silent divergence risk against a
program that moves, and the repo's own instruction is not to build the debt hole. The
operator prefers a real dependency; this is a case where the preference and the engineering
agree.

The sidecar shape is what makes the dependency safe to take. The SDK is a large transitive
tree (153 packages) doing arithmetic we cannot audit line by line, so it runs where a
compromise is inert: a subprocess with no key material, whose only output is bytes that
`guard.py` then refuses unless every instruction is on an allowlist the SDK cannot
influence. Trust is replaced by verification at a boundary eight bytes wide.

Process-per-request rather than a long-lived daemon: an LP desk does a handful of
transactions a day, the SDK's own RPC caching is per-instance and would go stale anyway
between them, and a daemon is a thing that can be alive with the wrong version of the world
in it. ~1.5s of startup is not a cost worth optimising against a 400ms block time.

The RPC URL carries the Helius key, so it goes over the argv-free path (stdin JSON) and
never appears in a process listing, a log line, or an exception message.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 120.0


class SidecarError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Sidecar:
    directory: Path
    rpc_url: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    node: str = "node"

    @property
    def script(self) -> Path:
        return self.directory / "builder.cjs"

    def available(self) -> tuple[bool, str]:
        """Is the builder installed? Reported, never raised, so `--plan` degrades politely."""
        if not self.script.exists():
            return False, f"builder is missing at {self.script}"
        if not (self.directory / "node_modules" / "@meteora-ag" / "dlmm").exists():
            return False, f"@meteora-ag/dlmm is not installed; run `npm install` in {self.directory}"
        return True, "ok"

    def call(self, op: str, **payload: Any) -> dict[str, Any]:
        ready, reason = self.available()
        if not ready:
            raise SidecarError(reason)
        request = json.dumps({"op": op, "rpc_url": self.rpc_url, **payload})
        try:
            completed = subprocess.run(
                [self.node, str(self.script)],
                input=request,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.directory),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SidecarError(f"builder timed out after {self.timeout}s on op {op}") from exc
        except FileNotFoundError as exc:
            raise SidecarError(f"`{self.node}` is not on PATH") from exc
        if completed.returncode != 0:
            # stderr can contain the RPC url on some SDK failures; report the code only.
            raise SidecarError(f"builder exited {completed.returncode} on op {op}")
        try:
            body = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SidecarError(f"builder returned non-JSON on op {op}") from exc
        if not isinstance(body, dict):
            raise SidecarError(f"builder returned a non-object on op {op}")
        if not body.get("ok"):
            raise SidecarError(f"builder refused op {op}: {body.get('error')}")
        result = body.get("result")
        if not isinstance(result, dict):
            raise SidecarError(f"builder returned no result for op {op}")
        return result

    # -- the five operations -------------------------------------------------------------

    def pool_state(self, pool: str) -> dict[str, Any]:
        return self.call("pool_state", pool=pool)

    def positions(self, pool: str, user: str) -> dict[str, Any]:
        return self.call("positions", pool=pool, user=user)

    def remove_liquidity(
        self,
        *,
        pool: str,
        user: str,
        position: str,
        from_bin_id: int,
        to_bin_id: int,
        bps: int,
        claim_and_close: bool = False,
        cu_limit: int | None = None,
        cu_price: int | None = None,
    ) -> dict[str, Any]:
        return self.call(
            "remove_liquidity",
            pool=pool,
            user=user,
            position=position,
            from_bin_id=from_bin_id,
            to_bin_id=to_bin_id,
            bps=bps,
            claim_and_close=claim_and_close,
            cu_limit=cu_limit,
            cu_price=cu_price,
        )

    def add_one_sided(
        self,
        *,
        pool: str,
        user: str,
        position: str,
        min_bin_id: int,
        max_bin_id: int,
        total_x: int = 0,
        total_y: int = 0,
        slippage_pct: float = 1.0,
        cu_limit: int | None = None,
        cu_price: int | None = None,
    ) -> dict[str, Any]:
        return self.call(
            "add_one_sided",
            pool=pool,
            user=user,
            position=position,
            min_bin_id=min_bin_id,
            max_bin_id=max_bin_id,
            total_x=str(total_x),
            total_y=str(total_y),
            slippage_pct=slippage_pct,
            cu_limit=cu_limit,
            cu_price=cu_price,
        )

    def quote_rent(self, *, pool: str, min_bin_id: int, max_bin_id: int) -> dict[str, Any]:
        return self.call("quote_rent", pool=pool, min_bin_id=min_bin_id, max_bin_id=max_bin_id)
