"""The loader must read both catalog kinds honestly: clocks, dedupe, gaps, floors."""

import json
import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from joshi_analysis.scalplab.run import run_and_write
from joshi_analysis.scalplab.tape import (
    ARRIVAL_NONE,
    ARRIVAL_POLL,
    ARRIVAL_SOCKET,
    TapeError,
    load_tape,
)
from joshi_analysis.scalplab.vocabulary import VERDICT_INSUFFICIENT

_DDL = """
CREATE TABLE source (source_id TEXT);
CREATE TABLE blob (
    blob_id TEXT PRIMARY KEY, storage_mode TEXT, compression TEXT,
    inline_bytes BLOB, relative_path TEXT, content_type TEXT
);
CREATE TABLE observation (
    commit_seq INTEGER, intra_commit_seq INTEGER, observation_kind TEXT,
    received_wall_us INTEGER, parse_disposition TEXT, acquisition_id TEXT, blob_id TEXT
);
CREATE TABLE coverage_gap (
    detected_commit_seq INTEGER, cause_code TEXT, severity TEXT,
    event_lower_us INTEGER, event_upper_us INTEGER
);
"""


def socket_frame(mint, side, sol_pool, tok_pool, sol_amt, tok_amt, sig, trader="T1"):
    return {
        "signature": sig,
        "mint": mint,
        "traderPublicKey": trader,
        "txType": side,
        "tokenAmount": tok_amt,
        "solAmount": sol_amt,
        "tokensInPool": tok_pool,
        "solInPool": sol_pool,
        "marketCapSol": 0.0,
        "pool": "pump-amm",
    }


def build_socket_catalog(root: Path, name: str, frames, gaps=()) -> Path:
    tape_dir = root / name
    tape_dir.mkdir()
    db = sqlite3.connect(tape_dir / "catalog.sqlite")
    db.executescript(_DDL)
    db.execute("INSERT INTO source VALUES ('pumpportal.websocket.data.v1')")
    for i, (received_us, frame) in enumerate(frames):
        body = json.dumps(frame).encode()
        envelope = json.dumps({"envelope_version": "test", "body": list(body)}).encode()
        db.execute(
            "INSERT INTO blob VALUES (?, 'inline', 'identity', ?, NULL,"
            " 'application/vnd.joshi.raw-source-frame+json')",
            (f"b{i}", envelope),
        )
        db.execute(
            "INSERT INTO observation VALUES (?, 0, 'frame', ?, 'opaque', 'a', ?)",
            (i, received_us, f"b{i}"),
        )
    for i, gap in enumerate(gaps):
        db.execute("INSERT INTO coverage_gap VALUES (?, ?, ?, ?, ?)", (i, *gap))
    db.commit()
    db.close()
    return tape_dir


def polled_trade(slot_index_id, tx, timestamp, side, price_sol, base, quote, user="U1"):
    return {
        "slotIndexId": slot_index_id,
        "tx": tx,
        "timestamp": timestamp,
        "userAddress": user,
        "type": side,
        "program": "pump_amm",
        "priceSol": price_sol,
        "amountSol": quote,
        "baseAmount": base,
        "quoteAmount": quote,
        "fillPriceSol": price_sol,
    }


def build_polled_catalog(root: Path, name: str, polls) -> Path:
    """polls: list of (received_wall_us, mint, trades)."""
    tape_dir = root / name
    tape_dir.mkdir()
    (tape_dir / "blobs").mkdir()
    db = sqlite3.connect(tape_dir / "catalog.sqlite")
    db.executescript(_DDL)
    db.execute("INSERT INTO source VALUES ('pump.api.product.v1')")
    for i, (received_us, mint, trades) in enumerate(polls):
        acq = f"acq{i}"
        envelope = json.dumps({"resolvedPublicPath": {"mint": mint}}).encode()
        db.execute(
            "INSERT INTO blob VALUES (?, 'inline', 'identity', ?, NULL,"
            " 'application/vnd.joshi.pump-api-acquisition+json')",
            (f"env{i}", envelope),
        )
        db.execute(
            "INSERT INTO observation VALUES (?, 0, 'response', ?, 'opaque', ?, ?)",
            (i, received_us, acq, f"env{i}"),
        )
        rel = f"public_source/p{i}.blob"
        (tape_dir / "blobs" / "public_source").mkdir(exist_ok=True)
        (tape_dir / "blobs" / rel).write_bytes(json.dumps({"trades": trades}).encode())
        db.execute(
            "INSERT INTO blob VALUES (?, 'external', 'identity', NULL, ?,"
            " 'application/json; charset=utf-8')",
            (f"body{i}", rel),
        )
        db.execute(
            "INSERT INTO observation VALUES (?, 1, 'response', ?, 'decoded', ?, ?)",
            (i, received_us, acq, f"body{i}"),
        )
    db.commit()
    db.close()
    return tape_dir


def test_socket_tape_loads_exact_prices_and_dedupes(tmp_path):
    frames = [
        (1_000_000, socket_frame("MINTA", "buy", 22.5, 450.0, 0.5, 10.0, "sig1")),
        (2_000_000, socket_frame("MINTA", "sell", 22.0, 460.0, 0.5, 10.0, "sig2")),
        (3_000_000, socket_frame("MINTA", "sell", 22.0, 460.0, 0.5, 10.0, "sig2")),  # dup
        (4_000_000, {"message": "control noise"}),
    ]
    tape_dir = build_socket_catalog(
        tmp_path, "sock", frames, gaps=[("provider_refused_subscription", "scope_stopped", 1, 2)]
    )
    tape = load_tape(tape_dir)
    assert tape.provenance.source_kind == "pumpportal_socket"
    assert tape.provenance.arrival_clock == ARRIVAL_SOCKET
    assert tape.provenance.n_events == 2
    assert tape.provenance.coverage_gaps[0].cause_code == "provider_refused_subscription"
    events = tape.events_by_coin["MINTA"]
    assert events[0].price == Decimal("22.5") / Decimal("450.0")
    assert events[0].quote_signed == Decimal("0.5")
    assert events[1].quote_signed == Decimal("-0.5")
    assert events[1].arrival_wall_us == 2_000_000
    assert [e.ordinal for e in events] == [0, 1]


def test_polled_tape_slot_dedupe_and_poll_floor(tmp_path):
    t1 = polled_trade("0004414572670013120000", "tx1", "2026-08-24T18:52:45.000Z", "buy",
                      "0.000000330533181310388603492722236164750739099", "100", "0.03")
    t2 = polled_trade("0004414572680000010000", "tx2", "2026-08-24T18:52:49.000Z", "sell",
                      "0.00000032", "50", "0.016")
    polls = [
        (1_787_597_565_000_000, "MINTB", [t2, t1]),
        (1_787_597_575_000_000, "MINTB", [t2]),  # overlap: dedupe
        (1_787_597_585_000_000, "MINTB", []),
    ]
    tape = load_tape(build_polled_catalog(tmp_path, "polled", polls))
    assert tape.provenance.source_kind == "pump_api_polled"
    assert tape.provenance.arrival_clock == ARRIVAL_POLL
    assert tape.provenance.arrival_floor_us == 10_000_000
    events = tape.events_by_coin["MINTB"]
    assert len(events) == 2
    assert events[0].slot == 441457267
    assert events[0].tx == "tx1"  # slot order, not page order
    assert events[0].price == Decimal("0.000000330533181310388603492722236164750739099")
    assert events[1].arrival_wall_us == 1_787_597_565_000_000  # first-seen poll
    from datetime import UTC, datetime

    expected = int(datetime(2026, 8, 24, 18, 52, 45, tzinfo=UTC).timestamp() * 1_000_000)
    assert events[0].event_time_us == expected


def test_polled_backfill_has_no_live_decision_clock(tmp_path):
    # 200 seconds of market time retained by two polls 3 seconds apart: retrospective.
    trades_a = [
        polled_trade(f"000441457267001{i:07d}", f"tx{i}", "2026-08-24T18:52:45.000Z",
                     "buy", "0.0000003", "1", "0.01")
        for i in range(3)
    ]
    trades_b = [
        polled_trade(f"000441457900001{i:07d}", f"ty{i}", "2026-08-24T18:56:05.000Z",
                     "sell", "0.0000003", "1", "0.01")
        for i in range(3)
    ]
    polls = [
        (9_000_000_000, "MINTC", trades_a),
        (9_003_000_000, "MINTC", trades_b),
    ]
    tape = load_tape(build_polled_catalog(tmp_path, "backfill", polls))
    assert tape.provenance.arrival_clock == ARRIVAL_NONE
    assert tape.provenance.arrival_floor_us is None
    assert "RETROSPECTIVE" in tape.provenance.decision_clock_statement


def test_venue_floor_is_declared_per_tape(tmp_path):
    frames = [(1_000_000, socket_frame("M", "buy", 10.0, 100.0, 0.1, 1.0, "s1"))]
    tape_dir = build_socket_catalog(tmp_path, "floors", frames)
    assert load_tape(tape_dir).provenance.venue_floor_bps == 250
    assert load_tape(tape_dir, venue_floor_bps=190).provenance.venue_floor_bps == 190


def test_missing_catalog_is_refused(tmp_path):
    with pytest.raises(TapeError):
        load_tape(tmp_path / "nope")


def _random_walk_frames(mint, n, seed, start_us=1_000_000):
    rng = random.Random(seed)
    sol, tok = 30.0, 1_000_000.0
    frames = []
    for i in range(n):
        side = "buy" if rng.random() < 0.55 else "sell"
        amount = round(rng.uniform(0.05, 0.4), 6)
        sol = round(sol + (amount if side == "buy" else -amount), 6)
        tok = round(tok * (1 - 0.001 if side == "buy" else 1 + 0.001), 6)
        frames.append(
            (
                start_us + i * 400_000,
                socket_frame(
                    mint, side, sol, tok, amount, 100.0, f"{mint}-sig{i}",
                    trader=f"T{rng.randrange(6)}",
                ),
            )
        )
    return frames


def test_end_to_end_lab_run_yields_insufficient_verdicts_and_no_policies(tmp_path):
    tape_a = build_socket_catalog(
        tmp_path, "tape-a",
        _random_walk_frames("COINA", 150, seed=1) + _random_walk_frames("COINB", 150, seed=2),
    )
    tape_b = build_socket_catalog(tmp_path, "tape-b", _random_walk_frames("COINC", 150, seed=3))
    out = tmp_path / "out"
    run = run_and_write(
        [str(tape_a), str(tape_b)],
        out,
        author_knowledge="synthetic walks built by this test; nothing real",
        venue_floor_bps=30,
        horizons=(5,),
    )
    report = json.loads((out / "lab_report.json").read_text())
    assert report["corpus"]["nCoins"] == 3
    assert report["corpus"]["nEvents"] == 450
    assert report["verdicts"], "every (family, horizon) cell must render a verdict"
    for verdict in report["verdicts"]:
        assert verdict["verdict"] == VERDICT_INSUFFICIENT
        assert "ONE TAPE OF ONE COIN FITS NOTHING" in verdict["honesty"]
    assert not list(out.glob("policy_*.json"))
    assert run.report["labelSummary"]
