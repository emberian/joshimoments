"""Enumerate every $DREGG holder on chain, ON HBOX, so the web can be its own front door.

WITHOUT THIS the portal admits only wallets `dregg_gate` already knows — people who ran
/verify in Telegram. That makes the website a second door onto the same room. With it,
someone who has never touched Telegram can sign in with their wallet and read the desk.

    uv run python -m dregg_portal.snapshot --out /home/hbox/dregg-data/portal/holders-snapshot.json

It runs where the Helius key ALREADY IS. Nothing about this puts a provider credential
anywhere new: the anchor receives the finished roster and has no idea a provider exists.

⚠ API SHAPE VERIFIED AGAINST VENDOR DOCS 2026-08-29, NOT CODED FROM MEMORY —
the same rule the signer page's deeplink protocol comment holds itself to.
    https://www.helius.dev/docs/api-reference/das/gettokenaccounts
  request : {"mint": <b58>, "page": <1-based int>, "limit": <int>,
             "options": {"showZeroBalance": false}}
            `owner` is OPTIONAL; a mint-only query is what enumerates every holder.
  response: {"total", "limit", "cursor", "last_indexed_slot",
             "token_accounts": [{"address", "mint", "owner", "amount",
                                 "delegated_amount", "frozen", "burnt"}]}
`amount` is a raw integer in the mint's smallest unit — a JSON NUMBER here, where
`getTokenAccountsByOwner` (which `dregg_gate.helius` uses) returns a decimal STRING for
the same quantity. Both are accepted below and a float is refused: a balance that arrived
as 1.3e15 has already lost digits, and a gate decision made on it would be a guess.

⚠ A PARTIAL SNAPSHOT IS NEVER WRITTEN. This is the same rule as the sweep's "a provider
error never ejects anyone", moved one box upstream. A truncated enumeration does not look
like an error to the portal — it looks like a list in which some real holders are simply
absent, and absence is what closes the door. So any failure, any page cap hit, any
malformed row, and this writes NOTHING and leaves yesterday's snapshot in place. Stale
admits; incomplete refuses. Only one of those is safe to publish.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from dregg_gate.config import DREGG_MINT, read_secret
from dregg_gate.helius import Helius, HeliusError

DAS_METHOD = "getTokenAccounts"
PAGE_LIMIT = 1000
# 1000 accounts a page; a pump.fun token with more than two million token accounts is not
# the thing this was written for, and hitting the cap is a REFUSAL rather than a truncation.
MAX_PAGES = 2000


class SnapshotError(RuntimeError):
    pass


class HolderScan(Helius):
    """`Helius` plus one mint-wide read.

    Subclassed rather than copied: `_rpc` already owns the URL (which carries the API key
    in its query string), the never-stringify-an-exception rule, and the "a provider
    failure is an exception, never a zero" discipline that the whole gate depends on.
    A second RPC envelope here would be a second place for that key to leak.
    """

    async def token_accounts_page(self, mint: str, page: int) -> list[dict]:
        result = await self._rpc(
            DAS_METHOD,
            {
                "mint": mint,
                "page": page,
                "limit": PAGE_LIMIT,
                "options": {"showZeroBalance": False},
            },
        )
        accounts = result.get("token_accounts") if isinstance(result, dict) else None
        if accounts is None and isinstance(result, dict) and result.get("total") == 0:
            return []
        if not isinstance(accounts, list):
            raise HeliusError(f"Helius {DAS_METHOD} returned a malformed token_accounts list")
        return accounts


def _raw_amount(value: object) -> int:
    """A raw integer amount, from either wire form. A float is a refusal, not a round."""

    if isinstance(value, bool):
        raise SnapshotError("token amount is a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise SnapshotError(f"token amount is not an exact integer ({type(value).__name__})")


async def scan(client: HolderScan, mint: str) -> tuple[dict[str, int], int]:
    """owner -> summed raw balance, plus the page count. Raises rather than truncating.

    SUMMED ACROSS ACCOUNTS, because one owner may hold the same mint in several token
    accounts and `dregg_gate.helius.balance_raw` already sums them. A snapshot that read
    only the first account would disagree with the bot about the same wallet — which is
    the exact drift this whole roster design exists to prevent.
    """

    totals: dict[str, int] = {}
    page = 1
    while page <= MAX_PAGES:
        accounts = await client.token_accounts_page(mint, page)
        if not accounts:
            return totals, page - 1
        for entry in accounts:
            if not isinstance(entry, dict):
                raise SnapshotError("token account entry is not an object")
            owner = entry.get("owner")
            if not isinstance(owner, str) or not owner:
                raise SnapshotError("token account entry has no owner")
            totals[owner] = totals.get(owner, 0) + _raw_amount(entry.get("amount"))
        if len(accounts) < PAGE_LIMIT:
            return totals, page
        page += 1
    raise SnapshotError(
        f"the holder enumeration did not finish within {MAX_PAGES} pages — refusing to "
        "publish a partial snapshot, which would read as 'these wallets do not hold'"
    )


def write_snapshot(path: Path, holders: dict[str, int], *, mint: str, now: float, pages: int) -> dict:
    """Write atomically, or not at all. A half-written snapshot is a partial snapshot."""

    payload = {
        "generated_at": now,
        "mint": mint,
        "source": f"Helius {DAS_METHOD}, mint-wide, summed per owner",
        "pages": pages,
        "owners": len(holders),
        # Raw units as STRINGS: these are read back by json.loads on another box and by a
        # human in a terminal, and a 16-digit integer is exactly where a JSON reader with
        # 53-bit numbers starts silently rounding. dregg_portal.publish parses them with int().
        "holders": {owner: str(amount) for owner, amount in sorted(holders.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return {key: value for key, value in payload.items() if key != "holders"}


async def run(*, mint: str, key_file: Path, out: Path, now: float) -> dict:
    async with httpx.AsyncClient() as http:
        client = HolderScan(read_secret(key_file, "Helius key"), http)
        holders, pages = await scan(client, mint)
    if not holders:
        raise SnapshotError(
            "the enumeration returned no holders at all. That is far more likely to be a "
            "provider problem than a token nobody holds, and publishing it would close the "
            "door on everyone. Nothing written."
        )
    return write_snapshot(out, holders, mint=mint, now=now, pages=pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dregg_portal.snapshot", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mint", default=DREGG_MINT)
    parser.add_argument("--helius-key", type=Path, default=Path("~/.helius-key").expanduser())
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(
            run(mint=args.mint, key_file=args.helius_key, out=args.out, now=time.time())
        )
    except (SnapshotError, HeliusError) as exc:
        # The type and our own message only — never the exception's text, which for an
        # httpx failure can carry the request URL, and the URL carries the API key.
        print(f"snapshot refused: {exc}")
        return 2
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
