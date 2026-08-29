"""dregg_record: aggregation math, min-n gating, absences, gap table, plain-text guard,
lookup gating, approval round trip.

Everything runs offline. The archive fixture is built through ``dregg_archive.store.Store``
(the real DDL, not a copy); the gate fixture carries the metadata/outbox tables from
``dregg_gate.state`` plus the shared APPROVALS_DDL, so the round-trip test exercises the
same contract the deployed bot serves.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import pytest

from dregg_archive.store import MS_DAY, MS_HOUR, Store, day_start_ms
from dregg_gate.approvals import APPROVALS_DDL
from dregg_gate.config import Config
from dregg_gate.state import GateState
from dregg_record import post as post_mod
from dregg_record.leaderboard import (
    STANDING_LINE,
    build_leaderboard,
    render_markdown,
    render_text,
)
from dregg_record.lookup import CallerLookup, render_card
from dregg_record.records import caller_record, flat, handle, last_calls, resolve_caller

NOW_MS = day_start_ms("2026-08-29") + 12 * MS_HOUR

WALLET_A = "A" * 44
WALLET_B = "B" * 44
WALLET_C = "C" * 44
WALLET_D = "D" * 44  # roster-only: known caller, zero archived callouts
WALLET_E = "E" * 44  # roster-only, shares D's username
WALLET_F = "F" * 44  # callouts but no roster row (resolution falls back)

GATE_AUX_DDL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error_type TEXT
);
"""


def mint(ch: str) -> str:
    return f"A{ch}" + "m" * 38 + "pump"


def _callout(db, cid, wallet, m, t, claim, username=None, x_username=None):
    db.execute(
        "INSERT INTO callouts (callout_id, wallet, mint, t_event_ms, thesis,"
        " callout_price_first, first_seen_fetch, last_seen_fetch, n_sightings,"
        " provider_multiple_last, username_last, x_username_last)"
        " VALUES (?,?,?,?,NULL,1e-7,1,1,1,?,?,?)",
        (cid, wallet, m, t, claim, username, x_username),
    )


@pytest.fixture()
def archive_db(tmp_path: Path) -> Path:
    path = tmp_path / "archive.sqlite"
    store = Store(path)
    db = store.db
    with db:
        db.execute(
            "INSERT INTO fetches (id, route, url, t_request_ms, t_response_ms, status, sha256, body_zst)"
            " VALUES (1, 'board', 'u', ?, ?, 200, 'aa', x'00')",
            (NOW_MS - 1000, NOW_MS),
        )
    day = MS_DAY
    hostile = "Alpha Wolf\n#1"  # provider text: space + newline; must render flattened
    # Caller A: 6 dated in-window calls + 1 older, outcomes measured method v1.
    a_rows = [
        ("a1", mint("a"), NOW_MS - 2 * day, 2.0),
        ("a2", mint("a"), NOW_MS - 3 * day, 130.0),
        ("a3", mint("b"), NOW_MS - 4 * day, 1.5),
        ("a4", mint("c"), NOW_MS - 5 * day, 3.0),
        ("a5", mint("d"), NOW_MS - 6 * day, None),
        ("a6", mint("e"), NOW_MS - 7 * day, 12.0),
        ("a0", mint("f"), NOW_MS - 40 * day, None),  # out of window, no outcome row
    ]
    with db:
        for cid, m, t, claim in a_rows:
            _callout(db, cid, WALLET_A, m, t, claim, hostile, "alpha_x")
        # Caller B: 4 measured winners — below the min-n gate, must NOT rank.
        for i, ch in enumerate("aghi"):
            _callout(db, f"b{i}", WALLET_B, mint(ch), NOW_MS - int((2.5 + i) * day), None, "bee")
        # Caller C: callouts, zero outcomes — absences must be stated strings.
        _callout(db, "c1", WALLET_C, mint("j"), NOW_MS - 2 * day, None, "cee")
        _callout(db, "c2", WALLET_C, mint("k"), NOW_MS - 3 * day, None, "cee")
        # Caller F: one callout, roster row absent — username resolution falls back.
        _callout(db, "f1", WALLET_F, mint("g"), NOW_MS - 2 * day, None, "ghost")

    outcome = {
        "a1": (-0.1, -0.5, -0.7, 1.1, 0.9, True),
        "a2": (-0.2, -0.2, -0.5, 1.6, 0.7, False),
        "a3": (0.05, 0.1, None, None, None, None),
        "a4": (-0.4, -0.8, -0.9, 1.0, 0.95, True),
        "a5": (None, -0.4, -0.6, 1.2, None, False),
        "a6": (None, 0.6, None, None, None, None),
        "b0": (None, 1.0, None, None, None, None),
        "b1": (None, 1.0, None, None, None, None),
        "b2": (None, 1.0, None, None, None, None),
        "b3": (None, 1.0, None, None, None, None),
    }
    for cid, (r1, r24, r7, mcm, dd, dead) in outcome.items():
        store.upsert_outcome(
            callout_id=cid, ret_1h=r1, ret_24h=r24, ret_7d=r7, max_close_multiple=mcm,
            max_drawdown=dd, dead_flag=dead, computed_ms=NOW_MS,
        )
    # A different method version must be invisible to v1 aggregation.
    store.upsert_outcome(
        callout_id="a1", ret_1h=None, ret_24h=99.0, ret_7d=None, max_close_multiple=None,
        max_drawdown=None, dead_flag=None, computed_ms=NOW_MS, method_version="v0",
    )
    # Removals: a2 published (counts, stays in stats); a3 unpublished (invisible).
    store.upsert_verdict(callout_id="a2", t_verdict_ms=NOW_MS, verdict="removed",
                         evidence_fetch_ids=[1])
    store.upsert_verdict(callout_id="a3", t_verdict_ms=NOW_MS, verdict="removed",
                         evidence_fetch_ids=[1])
    with db:
        db.execute("UPDATE removal_verdicts SET published=1 WHERE callout_id='a2'")
    # Roster rows (resolution + first/last seen). F deliberately missing.
    store.upsert_caller(wallet=WALLET_A, username="AlphaWolf", x_username="alpha_x",
                        seen_ms=NOW_MS - 40 * day)
    store.upsert_caller(wallet=WALLET_A, username=None, x_username=None, seen_ms=NOW_MS - 2 * day)
    store.upsert_caller(wallet=WALLET_B, username="bee", x_username=None, seen_ms=NOW_MS - 3 * day)
    store.upsert_caller(wallet=WALLET_C, username="cee", x_username=None, seen_ms=NOW_MS - 2 * day)
    store.upsert_caller(wallet=WALLET_D, username="dupe", x_username=None, seen_ms=NOW_MS - 5 * day)
    store.upsert_caller(wallet=WALLET_E, username="dupe", x_username=None, seen_ms=NOW_MS - 4 * day)
    store.close()
    return path


@pytest.fixture()
def gate_db(tmp_path: Path) -> Path:
    path = tmp_path / "gate.sqlite"
    db = sqlite3.connect(path)
    db.executescript(GATE_AUX_DDL + APPROVALS_DDL)
    db.commit()
    db.close()
    return path


# -- records: aggregation math ---------------------------------------------------------


def test_caller_record_math(archive_db):
    record = caller_record(archive_db, WALLET_A, now_ms=NOW_MS)
    counts = record["callouts"]
    assert counts["lifetime"] == 7 and counts["window"] == 6 and counts["undated"] == 0
    assert counts["distinct_mints"] == 6

    measured = record["measured"]
    assert measured["ret_24h"] == {
        "n": 6, "median": pytest.approx(-0.3), "mean": pytest.approx(-0.2)}
    assert measured["ret_1h"]["n"] == 4
    assert measured["ret_1h"]["median"] == pytest.approx(-0.15)
    assert measured["ret_7d"]["n"] == 4
    assert measured["ret_7d"]["median"] == pytest.approx(-0.65)
    assert measured["hits_24h"] == {"n": 6, "above_0": 2, "above_50": 1}
    assert measured["drawdown"] == {"n": 3, "median": pytest.approx(0.9)}
    assert measured["dead"] == {"n_final": 4, "n_dead": 2, "rate": pytest.approx(0.5)}

    claim = record["provider_claim"]
    assert claim["n"] == 5
    assert claim["median_multiple"] == pytest.approx(3.0)
    assert claim["max_multiple"] == pytest.approx(130.0)
    assert "their" in claim["label"] and "never our measurement" in claim["label"]

    identity = record["identity"]
    assert identity["first_seen"] == "2026-07-20"  # 40d before the 29th
    assert identity["last_seen"] == "2026-08-27"


def test_caller_record_absences_are_stated_strings(archive_db, tmp_path):
    # C has callouts but zero outcome rows: measured is a stated absence, not zeros.
    record = caller_record(archive_db, WALLET_C, now_ms=NOW_MS)
    assert "mature at T+25h" in record["measured"]["absent"]
    assert record["provider_claim"]["n"] == 0
    assert "no multiple" in record["provider_claim"]["absent"]
    assert record["wallet_layer"]["absent"]  # no parquet passed: stated, with the note
    # unknown wallet, and missing archive
    assert "no archived callouts" in caller_record(archive_db, "Z" * 44, now_ms=NOW_MS)["absent"]
    gone = caller_record(tmp_path / "gone.sqlite", WALLET_A, now_ms=NOW_MS)
    assert "not present" in gone["absent"]


def test_removals_count_published_only_and_never_subtract(archive_db):
    record = caller_record(archive_db, WALLET_A, now_ms=NOW_MS)
    removals = record["removals"]
    assert removals["published_removed"] == 1  # a2 published; a3's verdict is not
    assert removals["published_unknown_absent"] == 0
    assert "STAY on this record" in removals["note"]
    # the removed callout's outcome is still inside the aggregates (n=6 includes a2)
    assert record["measured"]["ret_24h"]["n"] == 6
    calls = last_calls(archive_db, WALLET_A)
    by_id = {c["callout_id"]: c for c in calls}
    assert by_id["a2"]["removal"] == "removed"
    assert by_id["a2"]["ret_24h"] == pytest.approx(-0.2)
    assert by_id["a3"]["removal"] is None  # unpublished verdict is not public


def test_last_calls_shape(archive_db):
    calls = last_calls(archive_db, WALLET_A)
    assert [c["callout_id"] for c in calls] == ["a1", "a2", "a3", "a4", "a5"]
    assert calls[0]["dead"] is True and calls[0]["day"] == "2026-08-27"
    assert calls[2]["ret_7d"] is None  # immature stays None, renderer says pending


def test_resolve_caller(archive_db, tmp_path):
    assert resolve_caller(archive_db, WALLET_A) == [WALLET_A]
    assert resolve_caller(archive_db, "@ALPHAWOLF") == [WALLET_A]
    assert resolve_caller(archive_db, "alpha_x") == [WALLET_A]
    # names are provider text, not identity: both wallets return, newest first
    assert resolve_caller(archive_db, "dupe") == [WALLET_E, WALLET_D]
    # roster miss falls back to the callouts themselves
    assert resolve_caller(archive_db, "ghost") == [WALLET_F]
    assert resolve_caller(archive_db, "nobody") == []
    assert resolve_caller(archive_db, "Z" * 44) == []
    assert resolve_caller(archive_db, "@") == []
    assert resolve_caller(tmp_path / "gone.sqlite", "alpha") == []


# -- leaderboard: gating, ranking, tables ----------------------------------------------


def test_leaderboard_min_n_gate_and_measured_ranking(archive_db):
    board = build_leaderboard(archive_db, now_ms=NOW_MS)
    # B's four +100% calls would top any claim- or mean-chasing board; the n>=5 gate
    # holds them out, so only A ranks — by OUR median, not the provider's 130x claim.
    assert [row["wallet"] for row in board["rows"]] == [WALLET_A]
    row = board["rows"][0]
    assert row["rank"] == 1
    assert row["n_measured"] == 6
    assert row["median_ret_24h"] == pytest.approx(-0.3)
    assert row["above_0"] == 2
    assert row["dead"] == {"n_final": 4, "n_dead": 2}
    assert row["removals_published"] == 1
    assert row["claim"]["median_multiple"] == pytest.approx(3.0)
    assert board["excluded_thin"] == 3  # B (4 measured), C (0), F (0)
    cov = board["coverage"]
    assert cov["n_callouts"] == 13 and cov["n_callers"] == 4 and cov["n_measured_24h"] == 10


def test_leaderboard_most_called_and_gap_tables(archive_db):
    board = build_leaderboard(archive_db, now_ms=NOW_MS)
    # only repeat-called mints list (singles are noise): mint('a') x3, mint('g') x2
    assert [c["mint"] for c in board["coins"]] == [mint("a"), mint("g")]
    top_coin = board["coins"][0]
    assert top_coin["mint"] == mint("a")
    assert top_coin["n_callouts"] == 3 and top_coin["n_callers"] == 2
    assert top_coin["measured_24h"]["n"] == 3
    assert top_coin["measured_24h"]["median"] == pytest.approx(-0.2)
    gap = board["gaps"][0]
    assert gap["wallet"] == WALLET_A and gap["mint"] == mint("a")
    assert gap["claimed_multiple"] == pytest.approx(130.0)
    assert gap["measured_close_multiple"] == pytest.approx(1.6)
    assert gap["gap_ratio"] == pytest.approx(130.0 / 1.6)
    assert gap["ret_24h"] == pytest.approx(-0.2)


def test_leaderboard_absences(archive_db, tmp_path):
    gone = build_leaderboard(tmp_path / "gone.sqlite", now_ms=NOW_MS)
    assert "not present" in gone["absent"]
    assert STANDING_LINE in render_text(gone)
    # a window with no callouts is a stated absence, not an empty table
    empty = build_leaderboard(archive_db, now_ms=NOW_MS + 200 * MS_DAY, window_days=30)
    assert "no dated callouts" in empty["absent"]
    # rows below the gate but a live window: rows_note states why nobody ranks
    strict = build_leaderboard(archive_db, now_ms=NOW_MS, min_n=50)
    assert strict["rows"] == []
    assert "needs evidence" in strict["rows_note"]
    assert strict["rows_note"] in render_text(strict)


# -- renderers: plain text, flattened names, standing line -----------------------------


def test_render_text_is_plain_and_carries_the_standing_line(archive_db):
    board = build_leaderboard(archive_db, now_ms=NOW_MS)
    text = render_text(board)
    assert len(text) <= 4096
    assert text.endswith(STANDING_LINE)
    assert "Deleting a callout changes nothing" in text
    # bare URLs, no HTML markup of ours anywhere
    assert f"https://pump.fun/coin/{mint('a')}" in text
    assert "<a " not in text and "<b>" not in text and "parse_mode" not in text
    # hostile provider name renders flattened: no space variant, no injected line
    assert "@AlphaWolf#1" in text
    assert "Alpha Wolf" not in text
    assert not any(line.startswith("#1") for line in text.splitlines())
    # measured and claimed stay labeled apart
    assert "median 24h -30.0% (n=6)" in text
    assert "claimed median 3.0x (their number, n=5)" in text
    assert "removals on record: 1" in text


def test_render_markdown(archive_db):
    board = build_leaderboard(archive_db, now_ms=NOW_MS)
    md = render_markdown(board)
    assert "| 1 | @AlphaWolf#1" in md
    assert STANDING_LINE in md
    assert "## Claimed vs measured" in md
    assert "claimed 130.0x vs measured close-peak 1.6x" in md
    assert "stale" in md.lower()


def test_flat_and_handle_clamp_hostile_names():
    assert flat("evil\nname with spaces") == "evilnamewithspaces"
    assert len(flat("x" * 100)) == 24
    assert handle(None, None, WALLET_A) == "AAAA…AAAA"
    assert handle(None, "xn", WALLET_A) == "@xn"


# -- /caller card ----------------------------------------------------------------------


def test_caller_card_content(archive_db):
    record = caller_record(archive_db, WALLET_A, now_ms=NOW_MS)
    card = render_card(record, last_calls(archive_db, WALLET_A))
    assert card.endswith(
        "Records are measurements, not endorsements; the callout feed was measured as an "
        "anti-signal (see /help)."
    )
    assert WALLET_A in card
    assert "Callouts: 7 lifetime · 6 in last 30d" in card
    assert "24h: median -30.0% · mean -20.0% (n=6)" in card
    assert "above +50%: 1/6" in card
    assert "median max drawdown 90% (n=3)" in card and "dead by 7d: 2/4" in card
    assert "their number, never ours" in card
    assert "REMOVED from the provider's board (still counted)" in card
    assert "LAST 5 CALLS" in card
    assert f"https://pump.fun/coin/{mint('a')}" in card
    assert "pending" in card  # immature horizons say so, never 0
    assert len(card) <= 4096


def test_caller_card_absence_paths(archive_db):
    record = caller_record(archive_db, WALLET_C, now_ms=NOW_MS)
    card = render_card(record, last_calls(archive_db, WALLET_C))
    assert "Measured: no measured outcomes yet" in card
    assert "no multiple" in card
    assert "Removals: none on record." in card
    assert "Wallet layer:" in card and "not present" in card


def test_wallet_layer_join_stamps_staleness(archive_db, tmp_path):
    duckdb = pytest.importorskip("duckdb")
    parquet = tmp_path / "estimator.parquet"
    duckdb.execute(
        f"COPY (SELECT '{WALLET_A}' AS owner, -12.5 AS net_realized_sol, 0.41 AS win_rate,"
        " 17 AS n_coins_closed, 'LOSS_CUTTER' AS rp_mode, NULL AS guild,"
        f" 1786751999 AS updated_through) TO '{parquet}' (FORMAT PARQUET)"
    )
    record = caller_record(archive_db, WALLET_A, now_ms=NOW_MS, wallet_parquet=parquet)
    layer = record["wallet_layer"]
    assert layer["stale"] is True and layer["as_of"] == "2026-08-14"
    assert layer["rp_mode"] == "LOSS_CUTTER"
    card = render_card(record, [])
    assert "Wallet layer (as of 2026-08-14, STALE)" in card
    assert "realized -12.5 SOL" in card and "win rate 41% over 17 closed" in card


# -- the gated handler -----------------------------------------------------------------


class Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_config(tmp_path: Path, archive_db: Path, **overrides) -> Config:
    from dataclasses import replace

    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
        screen_scores_dir=tmp_path / "scores",
        archive_db=archive_db,
        wallet_parquet=tmp_path / "estimator.parquet",  # absent: stated in the card
    )
    return replace(cfg, **overrides) if overrides else cfg


def test_lookup_gating_rate_limit_and_resolution(archive_db, tmp_path):
    cfg = make_config(tmp_path, archive_db, screen_rate_per_minute=2)
    state = GateState(cfg.db_path)
    clock = Clock(NOW_MS / 1000)
    lookup = CallerLookup(lambda: cfg, state, clock=clock)

    teaser, mode = lookup.reply(555, "alphawolf")
    assert mode is None and "holder perk" in teaser and "888,888" in teaser

    state.record_verification(777, "W" * 44, 10**12, clock())
    card, mode = lookup.reply(777, "@alphawolf")
    assert mode is None
    assert "CALLER RECORD" in card and WALLET_A in card
    assert "(see /help)" in card

    # second lookup admitted, third rate-limited (per_minute=2)
    assert "CALLER RECORD" in lookup.reply(777, WALLET_A)[0]
    assert "capped at 2 lookups" in lookup.reply(777, WALLET_A)[0]
    clock.now += 61  # the window rolls; the limiter admits BEFORE parsing, like /screen
    assert "Usage: /caller" in lookup.reply(777, None)[0]
    assert "Usage: /caller" in lookup.reply(777, "@")[0]
    clock.now += 61
    assert "No archived record" in lookup.reply(777, "nobody")[0]
    ambiguous, _ = lookup.reply(777, "dupe")
    assert WALLET_D in ambiguous and WALLET_E in ambiguous and "Pick one" in ambiguous
    clock.now += 61
    roster_only, _ = lookup.reply(777, WALLET_D)
    assert "no archived callouts yet" in roster_only

    state.set_member_status(777, "ejected", None)
    assert "seat lapsed" in lookup.reply(777, "alphawolf")[0]
    state.close()


async def test_gateway_routes_caller_command(archive_db, tmp_path):
    from dregg_gate.gateway import GateGateway

    cfg = make_config(tmp_path, archive_db)
    state = GateState(cfg.db_path)
    clock = Clock(NOW_MS / 1000)
    state.record_verification(777, "W" * 44, 10**12, clock())
    gateway = GateGateway(cfg, state, None, None, clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(
        {
            "update_id": 1,
            "message": {
                "date": clock() - 5,
                "text": "/caller @alphawolf",
                "chat": {"id": 777, "type": "private"},
                "from": {"id": 777, "is_bot": False},
            },
        }
    )
    payloads = [item.payload for item in state.pending() if item.method == "sendMessage"]
    assert len(payloads) == 1
    assert "CALLER RECORD" in payloads[0]["text"]
    assert "parse_mode" not in payloads[0]
    state.close()


# -- weekly post: approval round trip --------------------------------------------------


def _compose_args(archive_db, gate_db, state_dir, week=None):
    return argparse.Namespace(
        week=week, archive_db=archive_db, gate_db=gate_db, state_dir=state_dir,
        wallet_parquet=None, window_days=30, min_n=5,
    )


def _decide(gate_db: Path, approval_id: int, decision: str) -> None:
    db = sqlite3.connect(gate_db)
    with db:
        db.execute(
            "UPDATE approvals SET decided_at = ?, decision = ?, decided_by = 'op' WHERE id = ?",
            (time.time(), decision, approval_id),
        )
    db.close()


def test_compose_then_approve_then_deliver(archive_db, gate_db, tmp_path):
    state_dir = tmp_path / "record"
    args = _compose_args(archive_db, gate_db, state_dir, week="2026-W35")
    out = post_mod.compose(args)
    assert out["composed"] and out["week"] == "2026-W35" and out["ranked"] == 1

    assert (state_dir / "2026-W35.md").exists()
    assert (state_dir / "2026-W35.board.json").exists()

    db = sqlite3.connect(gate_db)
    row = db.execute(
        "SELECT source, kind, summary, payload_json FROM approvals WHERE id = ?",
        (out["approval_id"],),
    ).fetchone()
    db.close()
    assert (row[0], row[1]) == ("record", "weekly")
    assert json.loads(row[3])["text"] == row[2]
    assert "THE CALLOUT RECORD" in row[2]
    assert row[2].endswith(STANDING_LINE)

    deliver_args = argparse.Namespace(gate_db=gate_db, state_dir=state_dir)
    assert post_mod.deliver(deliver_args)["waiting"] == ["2026-W35"]

    _decide(gate_db, out["approval_id"], "approve")
    # approved but no group bound: sticks, never dropped
    assert post_mod.deliver(deliver_args)["waiting"] == ["2026-W35"]
    assert post_mod.load_state(state_dir)["2026-W35"]["status"] == "approved"

    db = sqlite3.connect(gate_db)
    with db:
        db.execute("INSERT INTO metadata (key, value) VALUES ('group_id', '-100777')")
    db.close()
    assert post_mod.deliver(deliver_args)["delivered"] == ["2026-W35"]
    db = sqlite3.connect(gate_db)
    dedup, method, payload_json = db.execute(
        "SELECT dedup_key, method, payload_json FROM outbox"
    ).fetchone()
    db.close()
    payload = json.loads(payload_json)
    assert (dedup, method) == ("record-2026-W35", "sendMessage")
    assert payload["chat_id"] == -100777
    assert "parse_mode" not in payload  # plain text, bare auto-linked URLs
    assert payload["text"] == row[2]

    again = post_mod.compose(args)
    assert not again["composed"] and "delivered" in again["reason"]
    assert post_mod.deliver(deliver_args)["note"] == "nothing pending"


def test_reject_marks_skipped_and_recompose_allowed(archive_db, gate_db, tmp_path):
    state_dir = tmp_path / "record"
    out = post_mod.compose(_compose_args(archive_db, gate_db, state_dir, week="2026-W36"))
    _decide(gate_db, out["approval_id"], "reject")
    result = post_mod.deliver(argparse.Namespace(gate_db=gate_db, state_dir=state_dir))
    assert result["skipped"] == ["2026-W36"] and result["delivered"] == []
    db = sqlite3.connect(gate_db)
    assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    db.close()
    out2 = post_mod.compose(_compose_args(archive_db, gate_db, state_dir, week="2026-W36"))
    assert out2["composed"] and out2["approval_id"] != out["approval_id"]


def test_iso_week_shape():
    assert post_mod.iso_week(time.mktime((2026, 8, 29, 12, 0, 0, 0, 0, 0))).startswith("2026-W")
