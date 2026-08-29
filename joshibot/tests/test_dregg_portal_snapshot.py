"""The holder enumeration: sums like the bot does, and refuses rather than truncates.

The assertion that matters is the refusal. A partial holder list does not look like an
error downstream — it looks like a list some real holders are simply missing from, and
missing is what closes the door. Every failure path here must leave the previous snapshot
untouched on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from dregg_portal.snapshot import (
    PAGE_LIMIT,
    HolderScan,
    SnapshotError,
    _raw_amount,
    run,
    scan,
    write_snapshot,
)

MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
NOW = 1_760_000_000.0


def transport(pages: list[list[dict]] | Exception, *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(pages, Exception):
            raise pages
        body = json.loads(request.content)
        page = body["params"]["page"]
        assert body["method"] == "getTokenAccounts"
        assert body["params"]["mint"] == MINT
        assert body["params"]["limit"] == PAGE_LIMIT
        assert body["params"]["options"] == {"showZeroBalance": False}
        accounts = pages[page - 1] if page - 1 < len(pages) else []
        return httpx.Response(
            status,
            json={"jsonrpc": "2.0", "id": 1, "result": {"total": len(accounts), "token_accounts": accounts}},
        )

    return httpx.MockTransport(handler)


def account(owner: str, amount) -> dict:
    return {"address": f"ta-{owner}", "mint": MINT, "owner": owner, "amount": amount, "frozen": False}


async def scan_with(pages) -> tuple[dict[str, int], int]:
    async with httpx.AsyncClient(transport=transport(pages)) as http:
        return await scan(HolderScan("k3y", http), MINT)


async def test_one_owner_with_several_token_accounts_is_summed_like_the_bot_sums():
    """`dregg_gate.helius.balance_raw` sums every account; a snapshot that did not would
    disagree with the bot about the same wallet."""

    totals, pages = await scan_with([[account("A", 400), account("A", 600), account("B", 5)]])
    assert totals == {"A": 1000, "B": 5}
    assert pages == 1


async def test_pagination_continues_while_a_page_is_full_and_stops_when_it_is_not():
    full = [account(f"W{i}", 1) for i in range(PAGE_LIMIT)]
    totals, pages = await scan_with([full, [account("last", 7)]])
    assert pages == 2
    assert totals["last"] == 7
    assert len(totals) == PAGE_LIMIT + 1


async def test_an_empty_first_page_is_an_honest_empty_result_not_a_hang():
    totals, pages = await scan_with([[]])
    assert totals == {}
    assert pages == 0


async def test_amounts_arrive_as_either_a_number_or_a_digit_string():
    """DAS returns a JSON number; getTokenAccountsByOwner returns a decimal string."""

    totals, _ = await scan_with([[account("A", 1_300_888_000_000), account("B", "888888000000")]])
    assert totals == {"A": 1_300_888_000_000, "B": 888_888_000_000}


def test_a_float_amount_is_refused_rather_than_rounded():
    with pytest.raises(SnapshotError):
        _raw_amount(1.3e15)
    with pytest.raises(SnapshotError):
        _raw_amount(True)
    with pytest.raises(SnapshotError):
        _raw_amount("1.5")


async def test_hitting_the_page_cap_refuses_instead_of_truncating(monkeypatch):
    from dregg_portal import snapshot

    monkeypatch.setattr(snapshot, "MAX_PAGES", 2)
    full = [account(f"W{i}", 1) for i in range(PAGE_LIMIT)]
    with pytest.raises(SnapshotError, match="partial snapshot"):
        await scan_with([full, full, full])


async def test_a_provider_error_mid_enumeration_writes_nothing(tmp_path: Path):
    from dregg_gate.helius import HeliusError

    out = tmp_path / "holders-snapshot.json"
    out.write_text(json.dumps({"generated_at": 1.0, "holders": {"OLD": "1"}}))
    key = tmp_path / "helius.key"
    key.write_text("k3y")
    key.chmod(0o600)

    def explode(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream is unwell")

    import dregg_portal.snapshot as snapshot

    async def failing_run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as http:
            return await snapshot.scan(snapshot.HolderScan("k3y", http), MINT)

    with pytest.raises(HeliusError):
        await failing_run()
    # THE POINT: yesterday's snapshot is still there, intact, and still admits its holders.
    assert json.loads(out.read_text())["holders"] == {"OLD": "1"}


async def test_an_empty_enumeration_is_refused_rather_than_published(tmp_path: Path):
    """Zero holders is far likelier to be a provider problem than a token nobody holds."""

    out = tmp_path / "holders-snapshot.json"
    key = tmp_path / "helius.key"
    key.write_text("k3y")
    key.chmod(0o600)

    import dregg_portal.snapshot as snapshot

    class EmptyScan(snapshot.HolderScan):
        async def token_accounts_page(self, mint, page):
            return []

    snapshot_scan = snapshot.HolderScan
    snapshot.HolderScan = EmptyScan
    try:
        with pytest.raises(SnapshotError, match="no holders at all"):
            await run(mint=MINT, key_file=key, out=out, now=NOW)
    finally:
        snapshot.HolderScan = snapshot_scan
    assert not out.exists()


def test_the_written_snapshot_is_what_publish_reads(tmp_path: Path):
    """Round-trip through the format the two modules actually agree on."""

    from dregg_portal.publish import read_snapshot

    rich = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
    poor = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
    out = tmp_path / "holders-snapshot.json"
    summary = write_snapshot(out, {rich: 1_300_888_000_000, poor: 1}, mint=MINT, now=NOW, pages=3)
    assert summary["owners"] == 2
    assert oct(out.stat().st_mode)[-3:] == "600"
    # Amounts are STRINGS on the wire so a 16-digit integer cannot be silently rounded.
    assert json.loads(out.read_text())["holders"][rich] == "1300888000000"

    entries = read_snapshot(out, threshold_tokens=888_888, decimals=6)
    assert entries[rich]["standing"] == "ok"
    assert entries[rich]["balance_raw"] == 1_300_888_000_000
    assert entries[poor]["standing"] == "short"


def test_publish_drops_a_snapshot_row_that_is_not_a_solana_address(tmp_path: Path):
    """A hostile or corrupt key must not become a roster entry a session could match."""

    from dregg_portal.publish import read_snapshot

    out = tmp_path / "holders-snapshot.json"
    out.write_text(json.dumps({"generated_at": NOW, "holders": {"A": "9" * 15, "../etc": "1"}}))
    assert read_snapshot(out, threshold_tokens=888_888, decimals=6) == {}


def test_the_api_shape_is_cited_rather_than_remembered():
    """This repo does not code a vendor protocol from memory; the citation is the proof."""

    source = Path("dregg_portal/snapshot.py").read_text(encoding="utf-8")
    assert "helius.dev/docs/api-reference/das/gettokenaccounts" in source
    assert "VERIFIED AGAINST VENDOR DOCS" in source


def test_the_snapshot_module_is_not_in_the_anchors_deploy_set():
    """It holds a provider key. It must never appear on the public box."""

    deploy_script = Path("../dregg-infra/edge/portal/deploy-portal.sh")
    if not deploy_script.exists():
        pytest.skip("dregg-infra is not checked out beside this repo")
    assert "dregg_portal/snapshot.py" not in deploy_script.read_text(encoding="utf-8")
