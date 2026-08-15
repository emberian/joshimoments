"""The bulk-history tool's offline paths. No BigQuery, no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# scripts/ is not a package, so load the module by path rather than inventing an __init__.py.
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bulk_history.py"
_SPEC = importlib.util.spec_from_file_location("bulk_history_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
bh = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bh
_SPEC.loader.exec_module(bh)

pa = pytest.importorskip("pyarrow", reason="parquet lives in the research dependency group")
pq = pytest.importorskip("pyarrow.parquet")


def bulk_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "row_id": "abc123",
        "schema": "bulk_history.v2",
        "kind": "swap",
        "grade": "replay",
        "pool": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
        "label": "DREGG/SOL",
        "dex": "pumpswap",
        "t_event": "2026-07-13T00:03:27+00:00",
        "chain": {
            "block_time": 1783901007,
            "signature": "dxgzVexgzvWcjtnjc7xp2sKFvFfRYGE2p3PAG7UQ",
            "slot": 432534407,
            "tx_index": 170,
        },
        "compute_units": 98950,
        "err": None,
        "fee_lamports": "23090",
        "token_in_mint": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
        "token_in_raw": "68309788920",
        "token_out_mint": "So11111111111111111111111111111111111111112",
        "token_out_raw": "202652719",
        "provenance": {"cursor": "bqjob_r7b0", "source": "bigquery", "fetched_at": "x"},
        "reserves": {
            "pool": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
            "dex": "pumpswap",
            "replay_sufficient": True,
            "vaults": [
                {
                    "mint": "So11111111111111111111111111111111111111112",
                    "decimals": 9,
                    "pre_raw": "273543444109",
                    "post_raw": "273340791390",
                    "delta_raw": "-202652719",
                },
            ],
        },
    }
    row.update(overrides)
    return row


def write_day(out: Path, stamp: str, rows: list[dict[str, Any]]) -> None:
    path = out / "swaps" / f"{stamp}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_parquet_keeps_every_raw_amount_a_string(tmp_path: Path) -> None:
    """The 2**53 cliff is the whole reason. A 1e9-supply 6-decimal token is 1e15 raw units."""

    write_day(tmp_path, "20260713", [bulk_row()])
    assert bh.to_parquet(tmp_path) == 0
    table = pq.read_table(tmp_path / "parquet" / "20260713.parquet")
    schema = table.schema
    for column in ("fee_lamports", "token_in_raw", "token_out_raw"):
        assert schema.field(column).type == pa.string(), column
    vault_struct = schema.field("vaults").type.value_type
    for column in ("pre_raw", "post_raw", "delta_raw"):
        assert vault_struct.field(column).type == pa.string(), column

    row = table.to_pylist()[0]
    assert row["token_in_raw"] == "68309788920"
    assert row["vaults"][0]["pre_raw"] == "273543444109"
    assert row["vaults"][0]["decimals"] == 9


def test_parquet_types_t_event_as_a_real_timestamp(tmp_path: Path) -> None:
    write_day(tmp_path, "20260713", [bulk_row()])
    bh.to_parquet(tmp_path)
    table = pq.read_table(tmp_path / "parquet" / "20260713.parquet")
    assert table.schema.field("t_event").type == pa.timestamp("us", tz="UTC")
    assert table.to_pylist()[0]["t_event"] == datetime(2026, 7, 13, 0, 3, 27, tzinfo=UTC)


def test_the_schema_is_declared_not_inferred(tmp_path: Path) -> None:
    """Two days whose rows differ must produce ONE schema, not two.

    `err` is null on ~97% of rows, so inference would type it from whichever day was read
    first and then fail — or silently coerce — on the day that has one.
    """

    write_day(tmp_path, "20260713", [bulk_row()])
    write_day(tmp_path, "20260714", [bulk_row(
        row_id="def456", kind="failed", grade="summary", err={"InstructionError": [3, {}]},
        token_in_mint=None, token_in_raw=None, token_out_mint=None, token_out_raw=None,
    )])
    assert bh.to_parquet(tmp_path) == 0
    first = pq.read_table(tmp_path / "parquet" / "20260713.parquet")
    second = pq.read_table(tmp_path / "parquet" / "20260714.parquet")
    assert first.schema == second.schema
    failed = second.to_pylist()[0]
    assert failed["kind"] == "failed"
    assert json.loads(failed["err"]) == {"InstructionError": [3, {}]}
    assert failed["token_in_raw"] is None
    # And the two concatenate, which is the point of a stable schema.
    assert pa.concat_tables([first, second]).num_rows == 2


def test_parquet_is_idempotent_and_rebuilds_only_what_changed(tmp_path: Path) -> None:
    write_day(tmp_path, "20260713", [bulk_row()])
    bh.to_parquet(tmp_path)
    target = tmp_path / "parquet" / "20260713.parquet"
    first_mtime = target.stat().st_mtime

    bh.to_parquet(tmp_path)  # nothing changed
    assert target.stat().st_mtime == first_mtime

    # A newer JSONL rebuilds it; the JSONL stays the source of truth.
    write_day(tmp_path, "20260713", [bulk_row(), bulk_row(row_id="second")])
    import os

    os.utime(tmp_path / "swaps" / "20260713.jsonl", (first_mtime + 10, first_mtime + 10))
    bh.to_parquet(tmp_path)
    assert pq.read_table(target).num_rows == 2


def test_an_interrupted_convert_leaves_no_half_written_parquet(tmp_path: Path) -> None:
    """A short parquet that reads as a complete day is worse than no parquet."""

    write_day(tmp_path, "20260713", [bulk_row()])
    bh.to_parquet(tmp_path)
    assert not list((tmp_path / "parquet").glob("*.partial"))


def test_a_truncated_bq_result_raises_instead_of_recording_a_short_day() -> None:
    """`bq --max_rows` truncates SILENTLY, and the day would be marked complete."""

    calls: list[list[str]] = []

    class Fake(bh.BigQuery):
        def estimate(self, sql: str) -> int:
            return 1000

    bq = Fake(project="p", max_bytes=10**12)
    import subprocess

    def run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, json.dumps([{"a": 1}, {"a": 2}]), "")

    original = subprocess.run
    subprocess.run = run  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="truncated"):
            bq.run("SELECT 1", max_rows=2)
    finally:
        subprocess.run = original  # type: ignore[assignment]
    # And the cap really was passed to bq, so the spend guard is on every query.
    assert any(a.startswith("--maximum_bytes_billed=") for a in calls[0])


def test_a_dry_run_reports_the_bytes_it_would_bill(monkeypatch) -> None:
    """Returning 0 here printed "$0.00" for what was in fact a ~$50 pull."""

    class Fake(bh.BigQuery):
        def estimate(self, sql: str) -> int:
            return 263_127_564_288

    bq = Fake(project="p", dry_run=True)
    rows, stats = bq.run("SELECT 1")
    assert rows == []
    assert stats["total_bytes_billed"] == 263_127_564_288
    assert stats["estimate_only"] is True
