"""Offline tests for dregg_watch: subscription CRUD, every matcher kind, dedup across
restart, digest batching + crash recovery, the rate ceiling, and the plain-text guard.

No live Telegram, no network. The screen's score files are written in the live
service's exact JSONL shape; the archive db comes from dregg_archive.store.Store
itself and the feed db from dregg_feed.movers.FeedState, so the tailers are exercised
against the real producers' schemas, not reconstructions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dregg_archive.store import Store
from dregg_feed.movers import FeedState
from dregg_gate.state import GateState
from dregg_watch.commands import WatchCommands
from dregg_watch.matcher import event_from_score
from dregg_watch.service import Config, WatchService
from dregg_watch.state import WatchState

NOW = 1_756_500_000.0  # 2025-08-29 21:20 UTC
TODAY = datetime.fromtimestamp(NOW, tz=UTC).date().isoformat()

HOLDER = 1001
OTHER = 1002
WALLET_A = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
WALLET_B = "9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT"
MINT_1 = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
MINT_2 = "6jxKG71sxNgVpEXpz3TTpzyNhUxtZW6RJtbxytNBPQfF"


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


# -- fixtures --------------------------------------------------------------------------


def make_gate(tmp_path: Path) -> GateState:
    gate = GateState(tmp_path / "gate.sqlite")
    gate.record_verification(HOLDER, WALLET_A, 10**12, NOW - 86_400)
    return gate


def score_row(
    mint: str = MINT_1,
    verdict: str = "CLEAN",
    *,
    creator: str = WALLET_B,
    deployer: str | None = None,
    crew_id: int | None = None,
    continuity_crew_id: int | None = None,
    symbol: str = "FOO",
    t_scored: str = "2026-08-29T12:00:00+00:00",
) -> dict:
    features: dict = {"dev_buy_share": 0.012, "dev_buy_source": "chain_exact", "n_snipers": 1}
    if continuity_crew_id is not None:
        features["crew_continuity_note"] = {"crew_id": continuity_crew_id, "jaccard": 0.2}
    return {
        "mint": mint,
        "verdict": verdict,
        "reasons": ["all_gates_passed"],
        "name": "Foo Coin",
        "symbol": symbol,
        "creator": creator,
        "deployer": deployer,
        "hydrated": True,
        "in_validated_population": True,
        "population_notes": [],
        "features": features,
        "crew_match": (
            {"crew_id": crew_id, "jaccard": 0.42, "overlap": 3, "crew_coins": 9,
             "crew_rips": 2, "crew_dumps": 1, "dirty": True}
            if crew_id is not None
            else None
        ),
        "deployer_history": {"launches": 4, "rips": 2, "dumps": 1, "grads": 0},
        "t_scored": t_scored,
    }


def append_scores(tmp_path: Path, *rows: dict, day: str = TODAY) -> None:
    scores = tmp_path / "scores"
    scores.mkdir(exist_ok=True)
    with (scores / f"{day}.jsonl").open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def add_callout(tmp_path: Path, *, callout_id: str, wallet: str, mint: str,
                username: str | None = None, fetch_seed: bytes = b"x") -> None:
    store = Store(tmp_path / "archive.sqlite")
    fetch_id = store.record_fetch(
        route="firehose", url="https://example.invalid/", t_request_ms=1, t_response_ms=2,
        status=200, body=fetch_seed,
    )
    store.upsert_callout(
        callout_id=callout_id, wallet=wallet, mint=mint, t_event_ms=int(NOW * 1000),
        thesis="to the moon", callout_price=None, market_cap=None, fetch_id=fetch_id,
        provider_multiple=3.2, provider_peak_t_ms=None, username=username, x_username=None,
    )
    store.close()


def add_feed_alert(tmp_path: Path, *, mint: str, reason: str = "accel", v5: float = 412.0) -> None:
    feed = FeedState(tmp_path / "feed.sqlite")
    feed.record_alert(mint, NOW - 30, v5, reason, True)
    feed.close()


def write_service_config(tmp_path: Path, **overrides) -> Path:
    values: dict = {
        "state_dir": str(tmp_path / "watch-state"),
        "watch_db": str(tmp_path / "watch.sqlite"),
        "gate_db": str(tmp_path / "gate.sqlite"),
        "scores_dir": str(tmp_path / "scores"),
        "archive_db": str(tmp_path / "archive.sqlite"),
        "feed_db": str(tmp_path / "feed.sqlite"),
        "deliver": True,
        "poll_s": 1.0,
        "digest_every_min": 30.0,
        "max_dms_per_hour": 20,
        "digest_max_lines": 3,
    }
    values.update(overrides)
    lines = []
    for key, value in values.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f'{key} = "{value}"')
    path = tmp_path / "watch.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def outbox_rows(tmp_path: Path) -> list[tuple[str, dict]]:
    connection = sqlite3.connect(tmp_path / "gate.sqlite")
    try:
        rows = connection.execute(
            "SELECT dedup_key, payload_json FROM outbox ORDER BY id"
        ).fetchall()
        return [(row[0], json.loads(row[1])) for row in rows]
    finally:
        connection.close()


def drain_outbox(tmp_path: Path) -> None:
    """Simulate the gate delivering and pruning: rows gone, dedup keys reusable."""

    connection = sqlite3.connect(tmp_path / "gate.sqlite")
    try:
        with connection:
            connection.execute("DELETE FROM outbox")
    finally:
        connection.close()


def commands_for(tmp_path: Path, gate: GateState, **kwargs) -> WatchCommands:
    cfg = SimpleNamespace(threshold_tokens=888_888, watch_db_path=tmp_path / "watch.sqlite")
    return WatchCommands(
        lambda: cfg, gate, clock=Clock(),
        watch_state=WatchState(tmp_path / "watch.sqlite"), **kwargs,
    )


def bootstrap_service(tmp_path: Path, clock: Clock, **config_overrides) -> WatchService:
    """A service whose FIRST cycle (cursor init, no emissions) has already run.
    The archive and feed dbs exist (empty is fine) BEFORE that cycle, so their
    cursors initialize at bootstrap — a db that only appears later starts at its
    then-current end, exactly like a first boot."""

    Store(tmp_path / "archive.sqlite").close()
    FeedState(tmp_path / "feed.sqlite").close()
    config = write_service_config(tmp_path, **config_overrides)
    service = WatchService(config, clock=clock)
    service.cycle()
    return service


# -- subscription CRUD ------------------------------------------------------------------


def test_crud_caps_and_normalization(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    commands = commands_for(tmp_path, gate, rate_per_minute=100)  # CRUD test, not a rate test

    assert "watchlist" in commands.reply(HOLDER, "/watch", [])
    reply = commands.reply(HOLDER, "/watch", ["coin", MINT_1])
    assert "watch #1" in reply and MINT_1 in reply
    assert "Already watching" in commands.reply(HOLDER, "/watch", ["coin", MINT_1])
    assert "watch #2" in commands.reply(HOLDER, "/watch", ["deployer", WALLET_B])
    assert "crew #81422" in commands.reply(HOLDER, "/watch", ["crew", "#81422"])
    assert "watch #4" in commands.reply(HOLDER, "/watch", ["caller", "@SomeCaller"])
    clean = commands.reply(HOLDER, "/watch", ["clean"])
    assert "digest" in clean and "thousands" in clean

    subs = {(s.kind, s.spec, s.mode) for s in commands.state.subs_for_user(HOLDER)}
    assert ("crew", "81422", "event") in subs           # '#' stripped, digits kept
    assert ("caller", "somecaller", "event") in subs    # lowercased, '@' stripped
    assert ("clean", "", "digest") in subs              # clean defaults to digest

    listing = commands.reply(HOLDER, "/watch", ["list"])
    assert "5 of 25" in listing and "(digest)" in listing

    assert "stopped" in commands.reply(HOLDER, "/unwatch", ["3"])
    assert "No watch #3" in commands.reply(HOLDER, "/unwatch", ["3"])
    assert "/verify" in commands.reply(OTHER, "/unwatch", ["1"])  # unverified can't unwatch
    assert commands.state.count_for_user(HOLDER) == 4  # ...and #1 survived the attempt

    # Bad specs never create rows.
    assert "doesn't parse" in commands.reply(HOLDER, "/watch", ["coin", "not-a-mint"])
    assert "Crew ids are numbers" in commands.reply(HOLDER, "/watch", ["crew", "abc"])
    assert "wallet address" in commands.reply(HOLDER, "/watch", ["caller", "???!!"])
    assert commands.state.count_for_user(HOLDER) == 4

    gate.close()


def test_cap_enforced(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    commands = commands_for(tmp_path, gate, max_subs=2)
    commands.reply(HOLDER, "/watch", ["coin", MINT_1])
    commands.reply(HOLDER, "/watch", ["coin", MINT_2])
    assert "at the cap (2" in commands.reply(HOLDER, "/watch", ["deployer", WALLET_B])
    assert commands.state.count_for_user(HOLDER) == 2
    gate.close()


def test_unverified_and_ejected_rejected(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    commands = commands_for(tmp_path, gate)
    teaser = commands.reply(OTHER, "/watch", ["coin", MINT_1])
    assert "/verify" in teaser and commands.state.count_for_user(OTHER) == 0
    gate.set_member_status(HOLDER, "ejected", None)
    assert "lapsed" in commands.reply(HOLDER, "/watch", ["coin", MINT_1])
    assert commands.state.count_for_user(HOLDER) == 0
    gate.close()


def test_command_rate_limit(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    commands = commands_for(tmp_path, gate, rate_per_minute=2)
    commands.reply(HOLDER, "/watch", ["list"])
    commands.reply(HOLDER, "/watch", ["list"])
    assert "capped" in commands.reply(HOLDER, "/watch", ["list"])
    gate.close()


# -- matcher kinds ----------------------------------------------------------------------


def test_first_boot_emits_nothing(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    append_scores(tmp_path, score_row(mint=MINT_1))
    add_callout(tmp_path, callout_id="c1", wallet=WALLET_B, mint=MINT_1)
    add_feed_alert(tmp_path, mint=MINT_1)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "coin", MINT_1, "event", NOW - 60)
    state.close()

    clock = Clock()
    service = bootstrap_service(tmp_path, clock)
    assert outbox_rows(tmp_path) == []  # the pre-existing world is not a flood
    gate.close()
    service.state.close()


def test_coin_matches_all_three_surfaces(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    sub_id, _ = state.add(HOLDER, "coin", MINT_1, "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    append_scores(tmp_path, score_row(mint=MINT_1), score_row(mint=MINT_2))  # MINT_2: no sub
    add_callout(tmp_path, callout_id="c1", wallet=WALLET_B, mint=MINT_1, username="alpha")
    add_feed_alert(tmp_path, mint=MINT_1)
    clock.now += 10
    service.cycle()

    rows = outbox_rows(tmp_path)
    assert len(rows) == 3
    texts = [payload["text"] for _, payload in rows]
    assert any("launch screen scored your watched coin" in t for t in texts)
    assert any("new callout" in t for t in texts)
    assert any("movers board" in t for t in texts)
    for _, payload in rows:
        assert payload["chat_id"] == HOLDER
        assert f"https://pump.fun/coin/{MINT_1}" in payload["text"]
        assert f"/unwatch {sub_id}" in payload["text"]
    gate.close()
    service.state.close()


def test_deployer_matches_creator_and_deployer_fields(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "deployer", WALLET_B, "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    # Unhydrated live rows carry deployer=null but always know the creator; a
    # hydrated corpus-rule row carries the deployer field. BOTH must fire.
    append_scores(
        tmp_path,
        score_row(mint=MINT_1, creator=WALLET_B, deployer=None,
                  t_scored="2026-08-29T12:00:01+00:00"),
        score_row(mint=MINT_2, creator=WALLET_A, deployer=WALLET_B,
                  t_scored="2026-08-29T12:00:02+00:00"),
    )
    clock.now += 10
    service.cycle()

    rows = outbox_rows(tmp_path)
    assert len(rows) == 2
    for _, payload in rows:
        assert "launched again" in payload["text"]
        assert "you watched them" in payload["text"]
        assert "deployer record 4 launches / 2 rips / 1 dumps" in payload["text"]
    gate.close()
    service.state.close()


def test_crew_matches_fingerprint_and_continuity(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "crew", "81422", "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    append_scores(
        tmp_path,
        score_row(mint=MINT_1, verdict="KNOWN_CREW", crew_id=81422,
                  t_scored="2026-08-29T12:00:01+00:00"),
        score_row(mint=MINT_2, continuity_crew_id=81422,
                  t_scored="2026-08-29T12:00:02+00:00"),
        score_row(mint=MINT_2, crew_id=99999,
                  t_scored="2026-08-29T12:00:03+00:00"),  # different crew: no match
    )
    clock.now += 10
    service.cycle()

    rows = outbox_rows(tmp_path)
    assert len(rows) == 2
    assert all("crew #81422" in payload["text"] for _, payload in rows)
    gate.close()
    service.state.close()


def test_caller_matches_wallet_and_username(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "caller", WALLET_B, "event", NOW - 60)
    state.add(HOLDER, "caller", "alphacaller", "event", NOW - 60)  # stored normalized
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    add_callout(tmp_path, callout_id="c1", wallet=WALLET_B, mint=MINT_1)
    add_callout(tmp_path, callout_id="c2", wallet=WALLET_A, mint=MINT_2,
                username="@AlphaCaller", fetch_seed=b"y")
    clock.now += 10
    service.cycle()

    rows = outbox_rows(tmp_path)
    assert len(rows) == 2
    assert all("made a new callout" in payload["text"] for _, payload in rows)
    assert any("Thesis: to the moon" in payload["text"] for _, payload in rows)
    gate.close()
    service.state.close()


def test_clean_rides_the_digest(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    sub_id, _ = state.add(HOLDER, "clean", "", "digest", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    rows = [
        score_row(mint=MINT_1, t_scored=f"2026-08-29T12:00:0{n}+00:00") for n in range(5)
    ]
    append_scores(tmp_path, *rows)
    clock.now += 10
    service.cycle()
    assert outbox_rows(tmp_path) == []  # queued, not sent: digest mode never fires per-event
    assert service.state.pending_digest_count() == 5

    clock.now += 31 * 60  # past digest_every_min
    service.cycle()
    out = outbox_rows(tmp_path)
    assert len(out) == 1
    text = out[0][1]["text"]
    assert f"Watch #{sub_id} — 5 match(es)" in text
    assert "2 more not shown" in text  # digest_max_lines = 3 in the fixture config
    assert f"/unwatch {sub_id}" in text
    assert service.state.pending_digest_count() == 0
    gate.close()
    service.state.close()


# -- dedup, rate ceiling, digest recovery ------------------------------------------------


def test_dedup_across_restart_and_replay(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "coin", MINT_1, "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    append_scores(tmp_path, score_row(mint=MINT_1))
    clock.now += 10
    service.cycle()
    assert len(outbox_rows(tmp_path)) == 1
    service.state.close()

    # The gate delivers and prunes; then a crash-replay: a NEW service process whose
    # screen cursor is rewound to zero re-reads the same rows.
    drain_outbox(tmp_path)
    replay = WatchService(tmp_path / "watch.toml", clock=clock)
    replay.state.set_cursor(f"screen:{TODAY}", "0")
    clock.now += 10
    replay.cycle()
    assert outbox_rows(tmp_path) == []  # the sent-table claim held: never double-sent
    gate.close()
    replay.state.close()


def test_rate_ceiling_diverts_to_digest(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "deployer", WALLET_B, "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock, max_dms_per_hour=2)

    append_scores(
        tmp_path,
        *[score_row(mint=MINT_1, creator=WALLET_B,
                    t_scored=f"2026-08-29T12:00:0{n}+00:00") for n in range(4)],
    )
    clock.now += 10
    heartbeat = service.cycle()
    assert len(outbox_rows(tmp_path)) == 2         # the ceiling
    assert heartbeat["rate_diverted"] == 2         # the rest are batched, not dropped
    assert service.state.pending_digest_count() == 2
    gate.close()
    service.state.close()


def test_digest_flush_crash_recovery_is_idempotent(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "clean", "", "digest", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    append_scores(tmp_path, score_row(mint=MINT_1))
    clock.now += 10
    service.cycle()
    # Crash simulation: the flush stamped its rows durably, then died before enqueue.
    stamped = service.state.stamp_flush(clock.now)
    assert stamped
    service.state.close()

    recovered = WatchService(tmp_path / "watch.toml", clock=clock)
    clock.now += 10
    recovered.cycle()  # recovery path runs the stamped flush even though none is due
    out = outbox_rows(tmp_path)
    assert len(out) == 1 and out[0][0] == f"dregg-watch:digest:{HOLDER}:{stamped[0][1]}"
    assert recovered.state.pending_digest_count() == 0

    clock.now += 10
    recovered.cycle()  # and running again re-sends nothing
    assert len(outbox_rows(tmp_path)) == 1
    gate.close()
    recovered.state.close()


# -- gating and hygiene ------------------------------------------------------------------


def test_ejected_owner_gets_nothing(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "coin", MINT_1, "event", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    gate.set_member_status(HOLDER, "ejected", None)
    append_scores(tmp_path, score_row(mint=MINT_1))
    clock.now += 10
    service.cycle()
    assert outbox_rows(tmp_path) == []
    gate.close()
    service.state.close()


def test_unreadable_gate_db_stands_down_whole(tmp_path: Path) -> None:
    append_scores(tmp_path, score_row(mint=MINT_1))
    config = write_service_config(tmp_path, gate_db=str(tmp_path / "missing.sqlite"))
    clock = Clock()
    service = WatchService(config, clock=clock)
    heartbeat = service.cycle()
    assert "stood_down" in heartbeat
    assert service.state.cursor("init") is None  # nothing consumed while nobody could hear
    service.state.close()


def test_dms_are_plain_text(tmp_path: Path) -> None:
    gate = make_gate(tmp_path)
    state = WatchState(tmp_path / "watch.sqlite")
    state.add(HOLDER, "coin", MINT_1, "event", NOW - 60)
    state.add(HOLDER, "clean", "", "digest", NOW - 60)
    state.close()
    clock = Clock()
    service = bootstrap_service(tmp_path, clock)

    append_scores(tmp_path, score_row(mint=MINT_1, symbol="<b>FOO</b>"))
    clock.now += 10
    service.cycle()
    clock.now += 31 * 60
    service.cycle()

    rows = outbox_rows(tmp_path)
    assert rows
    for _, payload in rows:
        assert "parse_mode" not in payload            # the no-markup lane, always
        assert payload["disable_web_page_preview"] is True
        assert "https://pump.fun/coin/" in payload["text"]
    gate.close()
    service.state.close()


def test_event_from_score_handles_live_row_shape() -> None:
    """The exact row the live screen emitted 2026-08-29 (abridged) parses cleanly."""

    row = {
        "mint": "6jxKG71sxNgVpEXpz3TTpzyNhUxtZW6RJtbxytNBPQfF",
        "verdict": "KNOWN_CREW",
        "reasons": ["deployer_record:launches=1,rips=0,dumps=1"],
        "name": "EM", "symbol": "solana",
        "creator": "6k4YCFwmCFswWZK5ziRtdvoCwVnoiYTLycEk5b6f5XRv",
        "deployer": None, "hydrated": False,
        "features": {"dev_buy_raw": 0, "dev_buy_share": 0.0,
                     "dev_buy_source": "ws_vendor_float", "is_mayhem_mode": True},
        "crew_match": None,
        "deployer_history": {"launches": 1, "rips": 0, "dumps": 1, "grads": 0},
        "t_scored": "2026-08-29T11:14:25.976450+00:00",
    }
    event = event_from_score(row)
    assert event is not None
    assert event.deployers == ("6k4YCFwmCFswWZK5ziRtdvoCwVnoiYTLycEk5b6f5XRv",)
    assert event.crew_ids == ()
    assert event.verdict == "KNOWN_CREW"
    assert "vendor estimate" in event.facts[0]


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text('nonsense_key = 1\n')
    try:
        Config.load(path)
    except ValueError as exc:
        assert "nonsense_key" in str(exc)
    else:
        raise AssertionError("unknown config key was accepted")
