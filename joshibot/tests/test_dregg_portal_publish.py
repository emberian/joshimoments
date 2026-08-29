"""The hbox half: what the bundle contains, what it must never contain, and determinism.

The load-bearing assertions here are about SUBTRACTION. The publisher reads the one
database that links a wallet to a Telegram account, and the whole design depends on that
linkage not surviving the trip to the public box. So the bundle is searched for Telegram
identifiers directly, rather than trusted to have dropped them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dregg_portal import FRESHNESS_MARKER, SCHEMA_MANIFEST, SCHEMA_ROSTER
from dregg_portal.publish import PublishError, generate, read_gate, read_snapshot
from dregg_portal.roster import parse as parse_roster

NOW = 1_760_000_000.0
DAY = "2026-08-29"
DECIMALS = 6
THRESHOLD = 888_888
NEED = THRESHOLD * 10**DECIMALS
TG_ID = 6913902526
WALLET_OK = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
WALLET_SHORT = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
WALLET_CHAIN = "So11111111111111111111111111111111111111112"


def make_gate_db(path: Path, *, decimals: int | None = DECIMALS) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE members (
            tg_user_id INTEGER PRIMARY KEY, wallet TEXT NOT NULL UNIQUE, verified_at REAL NOT NULL,
            status TEXT NOT NULL, grace_until REAL, last_checked_at REAL, last_balance_raw TEXT);
        """
    )
    if decimals is not None:
        connection.execute("INSERT INTO metadata VALUES('mint_decimals', ?)", (str(decimals),))
    connection.execute("INSERT INTO metadata VALUES('last_sweep_day', ?)", (DAY,))
    connection.execute(
        "INSERT INTO members VALUES(?,?,?,?,?,?,?)",
        (TG_ID, WALLET_OK, NOW - 86_400, "ok", None, NOW - 3600, str(NEED + 10**DECIMALS)),
    )
    connection.execute(
        "INSERT INTO members VALUES(?,?,?,?,?,?,?)",
        (TG_ID + 1, WALLET_SHORT, NOW - 86_400, "grace", NOW + 3600, NOW - 3600, str(NEED - 10**DECIMALS)),
    )
    connection.commit()
    connection.close()


def make_watch_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tg_user_id INTEGER NOT NULL, kind TEXT NOT NULL,
            spec TEXT NOT NULL, mode TEXT NOT NULL, created_at REAL NOT NULL);
        """
    )
    connection.execute(
        "INSERT INTO subscriptions(tg_user_id, kind, spec, mode, created_at) VALUES(?,?,?,?,?)",
        (TG_ID, "coin", WALLET_CHAIN, "event", NOW),
    )
    connection.commit()
    connection.close()


def make_scores(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "mint": WALLET_CHAIN,
            "verdict": "CLEAN",
            "symbol": "<script>alert(1)</script>",
            "name": "hostile",
            "reasons": ["dev buy under 2%"],
            "features": {"dev_buy_share": 0.011},
            "deployer_history": {"launches": 3, "rips": 0, "dumps": 0, "grads": 1},
            "in_validated_population": True,
            "t_scored": f"{DAY}T12:34:56+00:00",
        },
        {
            "mint": WALLET_OK,
            "verdict": "KNOWN_CREW",
            "symbol": "RUG",
            "reasons": ["crew overlap"],
            "features": {"dev_buy_share": 0.42},
            "deployer_history": {"launches": 9, "rips": 6, "dumps": 4, "grads": 0},
            "in_validated_population": True,
            "t_scored": f"{DAY}T13:00:00+00:00",
        },
    ]
    (directory / f"{DAY}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


@pytest.fixture
def desk(tmp_path: Path) -> dict:
    gate_db = tmp_path / "gate.sqlite"
    watch_db = tmp_path / "watch.sqlite"
    scores = tmp_path / "scores"
    make_gate_db(gate_db)
    make_watch_db(watch_db)
    make_scores(scores)
    return {
        "gate_db": gate_db,
        "watch_db": watch_db,
        "scores_dir": scores,
        "archive_db": tmp_path / "absent-archive.sqlite",
    }


def build(desk: dict, out: Path, **overrides) -> dict:
    kwargs = {
        "day": DAY,
        "now": NOW,
        "out_dir": out,
        "gate_db": desk["gate_db"],
        "scores_dir": desk["scores_dir"],
        "archive_db": desk["archive_db"],
        "watch_db": desk["watch_db"],
    }
    kwargs.update(overrides)
    return generate(**kwargs)


# -- the roster ----------------------------------------------------------------------


def test_roster_carries_the_gates_own_decision_including_grace(desk, tmp_path: Path):
    build(desk, tmp_path / "bundle")
    roster = parse_roster(json.loads((tmp_path / "bundle" / "roster.json").read_text()))
    assert roster.decimals == DECIMALS
    assert roster.threshold_tokens == THRESHOLD
    assert roster.holdings[WALLET_OK].standing == "ok"
    assert roster.holdings[WALLET_SHORT].standing == "grace"
    assert roster.holdings[WALLET_SHORT].grace_until == NOW + 3600
    assert roster.sweep_day == DAY


def test_roster_refuses_to_guess_the_mint_decimals(tmp_path: Path):
    gate_db = tmp_path / "gate.sqlite"
    make_gate_db(gate_db, decimals=None)
    scores = tmp_path / "scores"
    make_scores(scores)
    with pytest.raises(PublishError, match="decimals"):
        generate(
            day=DAY,
            now=NOW,
            out_dir=tmp_path / "bundle",
            gate_db=gate_db,
            scores_dir=scores,
            archive_db=tmp_path / "none.sqlite",
        )


def test_a_threshold_override_rides_into_the_roster_per_member(desk, tmp_path: Path):
    build(desk, tmp_path / "bundle", overrides={str(TG_ID + 1): 1})
    roster = parse_roster(json.loads((tmp_path / "bundle" / "roster.json").read_text()))
    assert roster.holdings[WALLET_SHORT].threshold_tokens == 1
    assert roster.holdings[WALLET_OK].threshold_tokens == THRESHOLD


def test_a_chain_snapshot_admits_wallets_the_bot_has_never_met(desk, tmp_path: Path):
    snapshot = tmp_path / "holders.json"
    snapshot.write_text(
        json.dumps({"generated_at": NOW, "holders": {WALLET_CHAIN: str(NEED * 2), "junk": "5"}})
    )
    build(desk, tmp_path / "bundle", snapshot=snapshot)
    roster = parse_roster(json.loads((tmp_path / "bundle" / "roster.json").read_text()))
    assert roster.holdings[WALLET_CHAIN].standing == "ok"
    assert roster.holdings[WALLET_CHAIN].origin == "snapshot"
    assert "junk" not in roster.holdings


def test_the_gate_wins_over_the_snapshot_on_a_collision(desk, tmp_path: Path):
    """A grace clock and a comped threshold are facts a chain snapshot cannot see."""

    snapshot = tmp_path / "holders.json"
    snapshot.write_text(json.dumps({"generated_at": NOW, "holders": {WALLET_SHORT: "0"}}))
    build(desk, tmp_path / "bundle", snapshot=snapshot)
    roster = parse_roster(json.loads((tmp_path / "bundle" / "roster.json").read_text()))
    assert roster.holdings[WALLET_SHORT].origin == "gate"
    assert roster.holdings[WALLET_SHORT].standing == "grace"


def test_snapshot_wallets_are_never_marked_ejected(tmp_path: Path):
    """'ejected' is a gate verdict; it is not invented for someone the gate never met."""

    snapshot = tmp_path / "holders.json"
    snapshot.write_text(json.dumps({"generated_at": NOW, "holders": {WALLET_CHAIN: "1"}}))
    entries = read_snapshot(snapshot, threshold_tokens=THRESHOLD, decimals=DECIMALS)
    assert entries[WALLET_CHAIN]["standing"] == "short"


# -- what must not leave hbox --------------------------------------------------------


def test_no_telegram_identifier_appears_anywhere_in_the_bundle(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out)
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert str(TG_ID) not in text, path
        assert "tg_user_id" not in text, path


def test_the_watchlist_is_attached_to_the_wallet_not_the_account(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out)
    view = json.loads((out / "holders" / f"{WALLET_OK}.json").read_text())
    assert [item["spec"] for item in view["watchlist"]] == [WALLET_CHAIN]
    assert not (out / "holders" / f"{TG_ID}.json").exists()


def test_bundle_files_are_written_private(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out)
    assert oct(out.stat().st_mode)[-3:] == "700"
    for name in ("roster.json", "manifest.json", "gated/screen.html"):
        assert oct((out / name).stat().st_mode)[-3:] == "600", name


# -- the pages -----------------------------------------------------------------------


def test_every_gated_page_carries_the_freshness_marker(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    manifest = build(desk, out)
    assert manifest["schema"] == SCHEMA_MANIFEST
    pages = list((out / "gated").rglob("*.html"))
    assert pages
    for page in pages:
        assert FRESHNESS_MARKER in page.read_text(encoding="utf-8"), page


def test_hostile_provider_strings_render_inert(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out)
    screen = (out / "gated" / "screen.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in screen
    assert "&lt;script&gt;" in screen


def test_the_screen_page_filters_without_any_javascript(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out)
    screen = (out / "gated" / "screen.html").read_text(encoding="utf-8")
    assert "<script" not in screen
    assert 'id="vf-CLEAN"' in screen
    assert "#vf-CLEAN:checked ~ .feed tr.row:not(.v-CLEAN)" in screen


def test_absent_inputs_become_stated_absences_not_zeroes(tmp_path: Path):
    gate_db = tmp_path / "gate.sqlite"
    make_gate_db(gate_db)
    empty_scores = tmp_path / "scores"
    empty_scores.mkdir()
    out = tmp_path / "bundle"
    generate(
        day=DAY,
        now=NOW,
        out_dir=out,
        gate_db=gate_db,
        scores_dir=empty_scores,
        archive_db=tmp_path / "none.sqlite",
    )
    screen = (out / "gated" / "screen.html").read_text(encoding="utf-8")
    assert "absence of a FILE" in screen
    assert "None" not in screen.replace("None</", "")  # no bare python None leaks


def test_the_wire_archive_is_linked_not_regated(desk, tmp_path: Path):
    out = tmp_path / "bundle"
    build(desk, out, latest_wire="/wire/2026-08-29.html")
    index = (out / "gated" / "index.html").read_text(encoding="utf-8")
    assert 'href="/wire/"' in index
    assert "not re-gated here" in index
    assert not (out / "gated" / "wire").exists()


# -- determinism ---------------------------------------------------------------------


def test_same_inputs_and_same_now_produce_the_same_bytes(desk, tmp_path: Path):
    first, second = tmp_path / "one", tmp_path / "two"
    manifest_one = build(desk, first)
    manifest_two = build(desk, second)
    assert manifest_one == manifest_two
    names_one = sorted(p.relative_to(first).as_posix() for p in first.rglob("*") if p.is_file())
    names_two = sorted(p.relative_to(second).as_posix() for p in second.rglob("*") if p.is_file())
    assert names_one == names_two
    for name in names_one:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_the_clock_is_the_only_thing_that_moves(desk, tmp_path: Path):
    """A different `now` changes the stamps and NOTHING else — the pages are pure."""

    first, second = tmp_path / "one", tmp_path / "two"
    build(desk, first)
    build(desk, second, now=NOW + 9_999.0)
    assert (first / "gated" / "screen.html").read_bytes() == (second / "gated" / "screen.html").read_bytes()
    assert (first / "roster.json").read_bytes() != (second / "roster.json").read_bytes()


def test_read_gate_never_writes_to_the_live_database(desk):
    before = desk["gate_db"].stat().st_mtime_ns
    read_gate(desk["gate_db"], threshold_tokens=THRESHOLD, overrides={})
    assert desk["gate_db"].stat().st_mtime_ns == before
    # And nothing may be created beside it: a -wal/-shm pair would mean a write handle.
    assert not desk["gate_db"].with_name(desk["gate_db"].name + "-wal").exists()


def test_roster_schema_is_pinned(desk, tmp_path: Path):
    build(desk, tmp_path / "bundle")
    raw = json.loads((tmp_path / "bundle" / "roster.json").read_text())
    assert raw["schema"] == SCHEMA_ROSTER


def test_one_unrenderable_dossier_row_does_not_cost_the_roster(desk, tmp_path: Path, monkeypatch):
    """The roster is the AUTH DATA. Losing a coin page is an absence; losing it is an outage."""

    from dregg_portal import publish

    good, bad = WALLET_CHAIN, WALLET_OK

    class FakeDossier:
        def __init__(self, path):
            self.meta = {"corpus_span": ["2026-05-01", "2026-08-14"], "updated_through": NOW - 86_400}

        def coin(self, mint):
            # A shape the renderer chokes on for exactly one mint, as a malformed index row
            # would: a string where the schema promises a number.
            return {"comp": {"n_traders": "not a number" if mint == bad else 5, "n_profiled": 5}}

        def wallet(self, owner):
            return None

        def close(self):
            pass

    index = tmp_path / "dossier.sqlite"
    index.write_text("not really a dossier; FakeDossier ignores it")
    monkeypatch.setattr(publish, "Dossier", FakeDossier)
    out = tmp_path / "bundle"
    manifest = build(desk, out, dossier_index=index)

    assert (out / "roster.json").exists()
    assert (out / "gated" / "index.html").exists()
    assert (out / "gated" / "coin" / f"{good}.html").exists()
    assert not (out / "gated" / "coin" / f"{bad}.html").exists()
    assert any(entry.startswith(f"coin/{bad}") for entry in manifest["render_failures"])
    assert manifest["coin_pages"] == 1
