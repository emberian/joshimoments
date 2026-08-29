"""Birth-slot hydration via Helius, under a hard daily budget.

WHAT ONE HYDRATION FETCHES, and why exactly that
------------------------------------------------
The screen's expensive features are the birth-slot buyer set (SNIPERS_SQL: net-positive
owners in the create's slot). The websocket event gives the create SIGNATURE but no
slot — PumpPortal carries no event clock at all — so:

  1. ``getTransaction(create_sig)``            -> the birth slot + the create's legs
  2. ``getSignaturesForAddress(mint)``         -> every signature touching the mint,
     newest first; filtered to the birth slot. Called seconds after the create, the
     mint's whole history fits one page. Failed signatures are dropped here — the
     corpus is success-only, and a reverted snipe must not become a phantom sniper.
  3. ``getTransaction`` per extra birth-slot signature, capped at ``max_same_slot_txs``.
     A cap hit means ``n_snipers`` is a FLOOR: the result is marked ``partial`` and the
     scorer refuses to mint a CLEAN from it (a heavily-sniped slot has long since
     failed the bundle gate anyway).

So the floor is 2 requests per hydrated launch, plus one per same-slot transaction
beyond the create — measured on the corpus, launches passing the cheap gates carry a
median of 1 birth-slot buyer, so ~2-3 requests is the working figure.

THE BUDGET
----------
Counted at the transport (every attempt, retries included), guarded before every
request, persisted to disk so a restart cannot forget the morning's spend — the same
discipline as dregg_archive's store. When the ceiling is hit, hydration STOPS and the
launches that would have needed it are emitted honestly as UNSCORED(budget); the cheap
lanes keep scoring. A new UTC day starts fresh.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

LOGGER = logging.getLogger("dregg_screen.hydrate")

HELIUS_KEY_FILE = "~/.helius-key"
HELIUS_URL_TEMPLATE = "https://mainnet.helius-rpc.com/?api-key={api_key}"


class BudgetExhausted(RuntimeError):
    pass


class HydrationFailed(RuntimeError):
    pass


def helius_url(key_file: str = HELIUS_KEY_FILE) -> str:
    key = Path(os.path.expanduser(key_file)).read_text().strip()
    if not key:
        raise ValueError(f"empty Helius key file: {key_file}")
    return HELIUS_URL_TEMPLATE.format(api_key=key)


@dataclass
class DailyBudget:
    """Persisted daily request counter. ``path=None`` keeps it in memory (tests)."""

    ceiling: int
    path: Path | None = None
    day: str = ""
    spent: int = 0

    def __post_init__(self) -> None:
        if self.path is not None and self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                self.day = str(saved.get("day", ""))
                self.spent = int(saved.get("spent", 0))
            except (ValueError, OSError):
                LOGGER.warning("budget state unreadable at %s; starting from zero", self.path)
        self._roll()

    def _roll(self) -> None:
        today = datetime.now(UTC).date().isoformat()
        if self.day != today:
            self.day, self.spent = today, 0

    def guard(self) -> None:
        self._roll()
        if self.spent >= self.ceiling:
            raise BudgetExhausted(f"daily Helius budget {self.ceiling} spent ({self.day})")

    def spend(self, n: int = 1) -> None:
        self._roll()
        self.spent += n
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self.day, "spent": self.spent}))
            os.replace(tmp, self.path)

    @property
    def remaining(self) -> int:
        self._roll()
        return max(self.ceiling - self.spent, 0)


@dataclass(frozen=True, slots=True)
class BirthSlot:
    mint: str
    slot: int
    create_tx: dict[str, Any]
    same_slot_txs: tuple[dict[str, Any], ...]
    partial: bool
    requests: int


@dataclass
class Hydrator:
    """Async Helius JSON-RPC with bounded retries. All I/O through one injected poster
    so tests run fully offline."""

    budget: DailyBudget
    url: str | None = None
    post: Callable[[str, dict[str, Any]], Any] | None = None  # async (url, body) -> dict
    max_attempts: int = 3
    max_same_slot_txs: int = 6
    max_sig_pages: int = 3
    sleep: Callable[[float], Any] = asyncio.sleep
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            self.budget.guard()
            self.budget.spend()
            try:
                if self.post is not None:
                    payload = await self.post(self.url or "", body)
                else:
                    if self._client is None:
                        self._client = httpx.AsyncClient(timeout=20.0)
                    resp = await self._client.post(self.url or helius_url(), json=body)
                    if resp.status_code == 429:
                        raise HydrationFailed("429")
                    resp.raise_for_status()
                    payload = resp.json()
                if "error" in payload:
                    raise HydrationFailed(f"rpc_error:{payload['error'].get('message', '?')}")
                return payload.get("result")
            except (httpx.HTTPError, HydrationFailed, ValueError) as exc:
                last = exc
                delay = 0.5 * (2**attempt) * (3.0 if "429" in str(exc) else 1.0)
                if attempt + 1 < self.max_attempts:
                    await self.sleep(delay)
        raise HydrationFailed(f"{method} failed after {self.max_attempts} attempts: {last}")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def birth_slot(self, mint: str, create_sig: str) -> BirthSlot:
        """Fetch the birth slot's successful mint-touching transactions."""

        n0 = self.budget.spent
        create = await self._rpc(
            "getTransaction",
            [create_sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                          "commitment": "confirmed"}],
        )
        if not create:
            raise HydrationFailed(f"create tx not found: {create_sig}")
        slot = int(create["slot"])

        # Every signature touching the mint, newest first; walk back until the page
        # crosses below the birth slot or the bounded page count runs out.
        extra_sigs: list[str] = []
        before: str | None = None
        reached_birth = False
        for _ in range(self.max_sig_pages):
            params: list[Any] = [mint, {"limit": 1000, "commitment": "confirmed"}]
            if before:
                params[1]["before"] = before
            page = await self._rpc("getSignaturesForAddress", params) or []
            for entry in page:
                if int(entry["slot"]) < slot:
                    reached_birth = True
                    break
                if (
                    int(entry["slot"]) == slot
                    and entry.get("err") is None
                    and entry["signature"] != create_sig
                ):
                    extra_sigs.append(entry["signature"])
            if reached_birth or len(page) < 1000:
                reached_birth = True
                break
            before = page[-1]["signature"]

        partial = not reached_birth
        txs: list[dict[str, Any]] = []
        for sig in extra_sigs[: self.max_same_slot_txs]:
            tx = await self._rpc(
                "getTransaction",
                [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                       "commitment": "confirmed"}],
            )
            if tx:
                txs.append(tx)
        if len(extra_sigs) > self.max_same_slot_txs:
            partial = True

        return BirthSlot(
            mint=mint,
            slot=slot,
            create_tx=create,
            same_slot_txs=tuple(txs),
            partial=partial,
            requests=self.budget.spent - n0,
        )
