"""The all-pump tape's repack and its cross-check against the live cluster tape."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "pump_history.py"
_SPEC = importlib.util.spec_from_file_location("pump_history_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
ph = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = ph
_SPEC.loader.exec_module(ph)

pa = pytest.importorskip("pyarrow", reason="parquet lives in the research dependency group")
pq = pytest.importorskip("pyarrow.parquet")

POOL = "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc"
NOSIS = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"
WSOL = "So11111111111111111111111111111111111111112"
DAY = "2026-08-13"


def leg(owner: str, mint: str, amount: str, index: int) -> dict[str, Any]:
    return {"owner": owner, "mint": mint, "amount": amount, "decimals": 6, "account_index": index}


def export_row(signature: str, *, pre: list, post: list) -> dict[str, Any]:
    return {
        "signature": signature,
        "block_slot": 439117645,
        "block_time": 1786665565,
        "tx_index": 910,
        "fee_lamports": "1004000",
        # Empty string, NOT null — this is the trap the module docstring calls out.
        "err": "",
        "compute_units": "66100",
        "pre": pre,
        "post": post,
        "schema_version": "bulk_pump.v1",
        "provenance_source": "bigquery.crypto_solana_mainnet_us.Transactions",
        "provenance_extracted_at": datetime(2026, 8, 15, 6, 20, tzinfo=UTC),
        "provenance_query_sha256": "deadbeef",
        "provenance_day": datetime(2026, 8, 13).date(),
    }


def write_shards(root: Path, day: str, rows: list[dict[str, Any]], *, shards: int = 3) -> None:
    day_dir = root / "raw" / f"day={day}"
    day_dir.mkdir(parents=True, exist_ok=True)
    for i in range(shards):
        chunk = rows[i::shards]
        if not chunk:
            chunk = []
        table = pa.Table.from_pylist(chunk, schema=pa.Table.from_pylist(rows).schema)
        pq.write_table(table, day_dir / f"part-{i:012d}.parquet", compression="zstd")


def live_swap(tmp: Path, signature: str, *, pre: tuple[str, str], post: tuple[str, str]) -> None:
    path = tmp / "state" / "cluster_tape" / "swaps" / f"{POOL}-20260813.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "kind": "swap",
        "row_id": signature,
        "pool": POOL,
        "label": "nosis/SOL",
        "t_event": f"{DAY}T04:00:00+00:00",
        "chain": {"signature": signature},
        "reserves": {
            "vaults": [
                {"mint": NOSIS, "pre_raw": pre[0], "post_raw": post[0]},
                {"mint": WSOL, "pre_raw": pre[1], "post_raw": post[1]},
            ]
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


@pytest.fixture
def tape(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(ph, "LIVE_TAPE", tmp_path / "state" / "cluster_tape" / "swaps")
    return tmp_path


def test_repack_folds_every_shard_and_loses_no_rows(tape: Path) -> None:
    rows = [
        export_row(f"sig{i:03d}",
                   pre=[leg(POOL, NOSIS, "100", 1), leg(POOL, WSOL, "200", 2)],
                   post=[leg(POOL, NOSIS, "150", 1), leg(POOL, WSOL, "180", 2)])
        for i in range(30)
    ]
    write_shards(tape, DAY, rows, shards=7)
    assert ph.repack(tape) == 0
    table = pq.read_table(tape / "daily" / f"{DAY}.parquet")
    assert table.num_rows == 30
    assert set(table.column("signature").to_pylist()) == {f"sig{i:03d}" for i in range(30)}
    # Streamed in batches, so this must still come out as ONE file, not one per batch.
    assert len(list((tape / "daily").glob("*.parquet"))) == 1
    assert not list((tape / "daily").glob("*.partial"))


def test_repack_is_idempotent_unless_forced(tape: Path) -> None:
    write_shards(tape, DAY, [export_row("sig000", pre=[], post=[])])
    ph.repack(tape)
    target = tape / "daily" / f"{DAY}.parquet"
    first = target.stat().st_mtime_ns
    ph.repack(tape)
    assert target.stat().st_mtime_ns == first


def test_verify_matches_both_vault_legs_including_the_non_pump_one(tape: Path, capsys) -> None:
    """The arrays are narrowed by OWNER, not by mint, and this is what proves it matters.

    A pool's quote leg is WSOL, whose mint does not end in 'pump'. Narrowing by mint would
    drop it and make the fill unreconstructible; narrowing by owner keeps it.
    """

    write_shards(tape, DAY, [export_row(
        "sigAAA",
        pre=[leg(POOL, NOSIS, "745708166270", 1), leg(POOL, WSOL, "285763126530", 2)],
        post=[leg(POOL, NOSIS, "726574810760", 1), leg(POOL, WSOL, "285687460213", 2)],
    )])
    ph.repack(tape)
    live_swap(tape, "sigAAA",
              pre=("745708166270", "285763126530"),
              post=("726574810760", "285687460213"))
    assert ph.verify(tape) == 0
    out = capsys.readouterr().out
    assert "exact pre+post vault match on both legs   : 1" in out
    assert "disagreed                                 : 0" in out


def test_verify_flags_a_real_disagreement(tape: Path, capsys) -> None:
    write_shards(tape, DAY, [export_row(
        "sigBBB",
        pre=[leg(POOL, NOSIS, "1", 1), leg(POOL, WSOL, "2", 2)],
        post=[leg(POOL, NOSIS, "3", 1), leg(POOL, WSOL, "4", 2)],
    )])
    ph.repack(tape)
    live_swap(tape, "sigBBB", pre=("1", "2"), post=("999", "4"))
    assert ph.verify(tape) == 1
    assert "disagreed                                 : 1" in capsys.readouterr().out


def test_verify_counts_and_locates_an_absence(tape: Path, capsys) -> None:
    """An absence concentrated in one (day, pool) is an upstream hole, not a parser bug."""

    write_shards(tape, DAY, [export_row("sigPRESENT", pre=[], post=[])])
    ph.repack(tape)
    live_swap(tape, "sigMISSING", pre=("1", "2"), post=("3", "4"))
    ph.verify(tape)
    out = capsys.readouterr().out
    assert "absent from the pump export               : 1" in out
    assert "nosis/SOL" in out


def test_other_owners_legs_are_never_read_as_the_pools(tape: Path, capsys) -> None:
    """A transaction carries many accounts; only the pool's own vaults are its reserves."""

    trader = "hnu5iBK8UoHb51UFsH1RYTUAYdrhjHvV5YMTf9T1CYN"
    write_shards(tape, DAY, [export_row(
        "sigCCC",
        pre=[leg(POOL, NOSIS, "10", 1), leg(POOL, WSOL, "20", 2), leg(trader, NOSIS, "999", 3)],
        post=[leg(POOL, NOSIS, "11", 1), leg(POOL, WSOL, "21", 2), leg(trader, NOSIS, "888", 3)],
    )])
    ph.repack(tape)
    live_swap(tape, "sigCCC", pre=("10", "20"), post=("11", "21"))
    assert ph.verify(tape) == 0
    assert "exact pre+post vault match on both legs   : 1" in capsys.readouterr().out


def test_amounts_stay_strings_through_the_repack(tape: Path) -> None:
    """A 1e9-supply 6-decimal token is 1e15 raw units — inside one order of 2**53."""

    huge = "998214642262896"
    write_shards(tape, DAY, [export_row(
        "sigDDD", pre=[leg(POOL, NOSIS, huge, 1)], post=[leg(POOL, NOSIS, huge, 1)])])
    ph.repack(tape)
    table = pq.read_table(tape / "daily" / f"{DAY}.parquet")
    vault_struct = table.schema.field("post").type.value_type
    assert vault_struct.field("amount").type == pa.string()
    assert table.to_pylist()[0]["post"][0]["amount"] == huge


def test_err_is_an_empty_string_for_success_not_null(tape: Path) -> None:
    """`WHERE err IS NULL` matches nothing, ever. Pinned so nobody rediscovers it."""

    write_shards(tape, DAY, [export_row("sigEEE", pre=[], post=[])])
    ph.repack(tape)
    row = pq.read_table(tape / "daily" / f"{DAY}.parquet").to_pylist()[0]
    assert row["err"] == ""
    assert row["err"] is not None
