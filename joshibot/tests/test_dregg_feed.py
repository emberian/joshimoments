"""Offline tests for dregg_feed: chart determinism, the detector's bar, composition
escaping, the verdict index, and a full service cycle against fake transports.

No network anywhere: the movers board and swap-api are canned bodies driven through
the same Transport seam the live code uses.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dregg_feed import compose
from dregg_feed.charts import ChartRenderer, parse_candles, render_chart
from dregg_feed.movers import (
    Alert,
    FeedState,
    MoversError,
    MoversPage,
    Thresholds,
    detect,
    parse_movers,
)
from dregg_feed.service import Config, FeedService, enqueue_alert
from dregg_feed.verdicts import VerdictIndex
from dregg_gate.state import GateState
from shitcoims_pumpsocial.client import PumpSocialClient

NOW = 1_756_400_000.0
MINT_A = "DCop3mFzWn1wJL9J9cTZ2K8xF7YH14q7LaUhsuyQpump"
MINT_B = "5dkPngQmeqTUN57RqhxdA6xCaz7AKdzQoHLdk9xhpump"
MINTS = [f"{chr(ord('A') + n)}{'x' * 30}{'pump'}" for n in range(8)]  # base58-safe


def fixture_candles(n: int = 24, t0: int = 1_756_390_000_000) -> list[dict]:
    """swap-api shape, DECIMAL STRINGS for the numerics (measured 2026-08-29)."""

    return [
        {
            "timestamp": t0 + i * 300_000,
            "open": f"{1.0e-7 * (1 + i / 40):.12f}",
            "high": f"{1.1e-7 * (1 + i / 40):.12f}",
            "low": f"{0.9e-7 * (1 + i / 40):.12f}",
            "close": f"{1.05e-7 * (1 + i / 40):.12f}",
            "volume": f"{10.5 + i:.6f}",
        }
        for i in range(n)
    ]


def movers_body(entries: list[dict]) -> dict:
    return {"board": "movers", "version": 0, "serverTs": 1_756_400_000_123, "entries": entries}


def entry(mint: str, v5: float, **extra) -> dict:
    row = {
        "m": mint, "n": f"coin {mint[:4]}", "t": mint[:4], "v5": v5,
        "v1h": v5 * 8, "v24h": v5 * 40, "vUsd5": v5 * 100, "tx5": 100,
        "mc": 250_000.0, "age": 9_000,
    }
    row.update(extra)
    return row


# -- charts ---------------------------------------------------------------------------


def test_candle_parse_tolerates_decimal_strings_and_drops_garbage() -> None:
    body = [*fixture_candles(3), {"timestamp": "nope", "close": "1.0"},
            {"timestamp": 5, "close": "not-a-number"}, "junk"]
    candles = parse_candles(body)
    assert len(candles) == 3
    assert candles[0].close == pytest.approx(1.05e-7)
    assert candles[0].volume == pytest.approx(10.5)
    assert candles == sorted(candles, key=lambda c: c.ts_ms)


def test_chart_bytes_are_deterministic_and_png() -> None:
    candles = parse_candles(fixture_candles())
    first = render_chart(candles, "TEST", "last 6h · 5m closes")
    second = render_chart(candles, "TEST", "last 6h · 5m closes")
    assert first == second
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    # A different series is a different image — the bytes actually depend on the data.
    other = parse_candles(fixture_candles(12))
    assert render_chart(other, "TEST", "last 6h · 5m closes") != first


def test_chart_renderer_caches_per_mint_half_hour() -> None:
    calls: list[str] = []

    def transport(method, url, headers, body):
        calls.append(url)
        return 200, {}, json.dumps(fixture_candles()).encode()

    client = PumpSocialClient(transport=transport, sleep=lambda s: None)
    renderer = ChartRenderer(client)
    png1 = renderer.render(MINT_A, "AAA", NOW)
    png2 = renderer.render(MINT_A, "AAA", NOW + 60)  # same half-hour bucket
    assert png1 is not None and png1 == png2
    assert len(calls) == 1
    renderer.render(MINT_B, "BBB", NOW)
    assert len(calls) == 2
    renderer.render(MINT_A, "AAA", NOW + 1800)  # next bucket refetches
    assert len(calls) == 3
    assert "interval=5m" in calls[0] and "currency=SOL" in calls[0]


def test_chart_renderer_degrades_to_none_on_empty_or_error() -> None:
    bodies = [b"[]", b"{bad"]

    def transport(method, url, headers, body):
        return 200, {}, bodies.pop(0)

    client = PumpSocialClient(transport=transport, sleep=lambda s: None)
    renderer = ChartRenderer(client)
    assert renderer.render(MINT_A, "AAA", NOW) is None          # no trades: no chart
    assert renderer.render(MINT_B, "BBB", NOW) is None          # broken body: no chart
    assert renderer.render(MINT_A, "AAA", NOW + 60) is None     # cached, no refetch
    assert bodies == []


# -- movers parsing -------------------------------------------------------------------


def test_movers_parse_keeps_wire_claims_and_gates_mints() -> None:
    page = parse_movers(movers_body([
        entry(MINT_A, 254.31),
        entry("not-base58!!", 999.0),
        {"m": MINT_B, "v5": "263.2"},  # tolerate a stringly number
        "junk",
    ]))
    assert [e.mint for e in page.entries] == [MINT_A, MINT_B]
    assert page.entries[0].v5 == pytest.approx(254.31)
    assert page.entries[1].v5 == pytest.approx(263.2)
    assert page.entries[1].symbol is None
    assert page.server_ts == 1_756_400_000_123
    assert page.raw_rows == 4


def test_movers_parse_refuses_non_envelope() -> None:
    with pytest.raises(MoversError):
        parse_movers([1, 2, 3])


# -- the detector's bar ---------------------------------------------------------------


def page_of(*rows: dict) -> MoversPage:
    return parse_movers(movers_body(list(rows)))


def test_first_sighting_never_alerts_and_acceleration_needs_the_floor(tmp_path: Path) -> None:
    state = FeedState(tmp_path / "feed.sqlite")
    th = Thresholds()
    # Poll 1: no prior observation -> nothing can alert, however big.
    assert detect(state, page_of(entry(MINT_A, 5_000.0)), NOW, th) == []
    # Poll 2: doubled but below the SOL floor -> silent.
    assert detect(state, page_of(entry(MINT_A, 240.0)), NOW + 75, th) == []
    # Poll 3: above floor but not accelerating (ratio < 1.6) -> silent.
    assert detect(state, page_of(entry(MINT_A, 300.0)), NOW + 150, th) == []
    # Poll 4: above floor AND >= 1.6x the prior poll -> alerts, with prev recorded.
    alerts = detect(state, page_of(entry(MINT_A, 520.0)), NOW + 225, th)
    assert [a.reason for a in alerts] == ["accel"]
    assert alerts[0].prev_v5 == pytest.approx(300.0)
    state.close()


def test_stale_previous_observation_proves_nothing(tmp_path: Path) -> None:
    state = FeedState(tmp_path / "feed.sqlite")
    th = Thresholds(prev_max_age_s=360.0)
    detect(state, page_of(entry(MINT_A, 100.0)), NOW, th)
    # 20 minutes later the old v5 is weather, not a baseline.
    assert detect(state, page_of(entry(MINT_A, 900.0)), NOW + 1200, th) == []
    state.close()


def test_top5_entry_requires_prior_outsider_status_and_its_own_floor(tmp_path: Path) -> None:
    state = FeedState(tmp_path / "feed.sqlite")
    th = Thresholds()
    # MINT_A's v5 never grows >= accel_ratio between polls, so only top5 is in play.
    board1 = [entry(MINTS[i], 1_000.0 - i) for i in range(5)] + [entry(MINT_A, 350.0)]
    detect(state, page_of(*board1), NOW, th)  # restart-shaped first poll: silence
    # MINT_A displaces a leader but lands under the top5 floor -> silent.
    board2 = [entry(MINTS[i], 1_000.0 - i) for i in range(4)] + [entry(MINT_A, 399.0)]
    assert detect(state, page_of(*board2), NOW + 75, th) == []
    detect(state, page_of(*board1), NOW + 150, th)  # back outside
    board3 = [entry(MINTS[i], 1_000.0 - i) for i in range(4)] + [entry(MINT_A, 450.0)]
    alerts = detect(state, page_of(*board3), NOW + 225, th)
    assert [a.reason for a in alerts] == ["top5_entry"]
    state.close()


def test_cooldown_suppresses_and_survives_restart(tmp_path: Path) -> None:
    th = Thresholds()
    state = FeedState(tmp_path / "feed.sqlite")
    detect(state, page_of(entry(MINT_A, 300.0)), NOW, th)
    state.record_alert(MINT_A, NOW + 70, 500.0, "accel", delivered=True)
    state.close()
    # A NEW process on the same state still remembers the alert AND the observation.
    state = FeedState(tmp_path / "feed.sqlite")
    assert detect(state, page_of(entry(MINT_A, 520.0)), NOW + 75, th) == []
    # Past the cooldown the same shape alerts again.
    state.db.execute("UPDATE alerts SET alerted_at = ?", (NOW - 7300,))
    state.db.commit()
    assert len(detect(state, page_of(entry(MINT_A, 900.0)), NOW + 150, th)) == 1
    state.close()


def test_global_cap_drops_lowest(tmp_path: Path) -> None:
    state = FeedState(tmp_path / "feed.sqlite")
    th = Thresholds(max_alerts_per_hour=6)
    for n in range(5):
        state.record_alert(MINTS[n], NOW - 100 - n, 400.0, "accel", delivered=True)
    detect(state, page_of(entry(MINT_A, 300.0), entry(MINT_B, 310.0)), NOW, th)
    # Two qualifying candidates, one slot left: the HIGHER v5 wins.
    alerts = detect(state, page_of(entry(MINT_A, 600.0), entry(MINT_B, 800.0)), NOW + 75, th)
    assert [a.mint for a in alerts] == [MINT_B]
    state.close()


# -- composition ----------------------------------------------------------------------


def sample_alert(**overrides) -> Alert:
    base = dict(
        mint=MINT_A, symbol="FROGE", name="FrogeCoin", reason="accel",
        v5=254.3, prev_v5=131.2, v1h=4681.6, v24h=13102.1, v_usd5=24836.5,
        tx5=533, mc_usd=279_787.6, age_s=9_516, server_ts=1_756_400_000_123,
    )
    base.update(overrides)
    return Alert(**base)


def test_caption_carries_link_claims_verdict_and_the_standing_line() -> None:
    text = compose.caption(sample_alert(), "CLEAN")
    assert "FrogeCoin" in text and f"https://pump.fun/coin/{MINT_A}" in text
    assert "provider claims: 5m 254.3 SOL · 1h 4,681.6 SOL" in text
    assert "screen said CLEAN at birth" in text
    assert "254.3 SOL vs 131.2 one poll earlier" in text
    assert text.rstrip().endswith(compose.STANDING_LINE)
    assert "🚀" not in text


def test_caption_renders_hostile_names_inert_and_handles_unscored() -> None:
    hostile = sample_alert(symbol='<b>&PWN"', name='<script>alert("x")</script>')
    text = compose.caption(hostile, None)
    assert "<script>" in text and '<b>&PWN"' in text  # literal, inert in plain text
    assert "born before the screen / unscored" in text
    assert len(text) <= compose.CAPTION_MAX


def test_caption_stays_under_telegram_cap_with_worst_case_inputs() -> None:
    worst = sample_alert(symbol="<" * 60, name="&" * 500)
    assert len(compose.caption(worst, "KNOWN_CREW")) <= compose.CAPTION_MAX


# -- the verdict index ----------------------------------------------------------------


def test_verdict_index_reads_incrementally_and_windows_by_day(tmp_path: Path) -> None:
    day_file = tmp_path / "2026-08-28.jsonl"
    day_file.write_text(json.dumps({"mint": MINT_A, "verdict": "CLEAN"}) + "\n")
    old_file = tmp_path / "2026-08-20.jsonl"
    old_file.write_text(json.dumps({"mint": MINT_B, "verdict": "BUNDLED"}) + "\n")
    # A now whose 2-day window is {08-29, 08-28, 08-27}: the 08-28 file is in, 08-20 out.
    import datetime as dt
    now = dt.datetime(2026, 8, 29, 12, tzinfo=dt.UTC).timestamp()
    index = VerdictIndex(tmp_path, days=2)
    assert index.verdict(MINT_A, now) == "CLEAN"
    assert index.verdict(MINT_B, now) is None  # 9 days old: outside the window
    # Appends are picked up without a rebuild; a partial line is not consumed.
    with day_file.open("a") as fh:
        fh.write(json.dumps({"mint": MINT_B, "verdict": "KNOWN_CREW"}) + "\n")
        fh.write('{"mint": "half')  # torn write in progress
    assert index.verdict(MINT_B, now) == "KNOWN_CREW"
    # A newer day's re-score wins over an older day's.
    (tmp_path / "2026-08-29.jsonl").write_text(
        json.dumps({"mint": MINT_A, "verdict": "NOT_CLEAN"}) + "\n"
    )
    assert index.verdict(MINT_A, now) == "NOT_CLEAN"


# -- gate enqueue + a full service cycle ----------------------------------------------


def make_gate_db(tmp_path: Path, *, bind: bool = True) -> Path:
    path = tmp_path / "gate.sqlite"
    state = GateState(path)
    if bind:
        state.bind_group(-100_123)
    state.close()
    return path


def test_enqueue_alert_writes_sendphoto_and_respects_unbound_gate(tmp_path: Path) -> None:
    unbound = tmp_path / "unbound"
    unbound.mkdir()
    assert enqueue_alert(
        make_gate_db(unbound, bind=False),
        dedup_key="k1", caption="hi", photo_path=tmp_path / "c.png",
    ) is False
    gate_db = make_gate_db(tmp_path)
    assert enqueue_alert(
        gate_db, dedup_key="k1", caption="hi <b>there</b>", photo_path=tmp_path / "c.png"
    )
    assert enqueue_alert(gate_db, dedup_key="k2", caption="text only", photo_path=None)
    rows = sqlite3.connect(gate_db).execute(
        "SELECT method, payload_json FROM outbox ORDER BY id"
    ).fetchall()
    assert [r[0] for r in rows] == ["sendPhoto", "sendMessage"]
    photo_payload = json.loads(rows[0][1])
    assert photo_payload["photo_path"].endswith("c.png")
    assert "parse_mode" not in photo_payload  # plain caption
    assert json.loads(rows[1][1])["disable_web_page_preview"] is True


def write_feed_config(tmp_path: Path, gate_db: Path, scores_dir: Path, *, deliver: bool) -> Path:
    cfg = tmp_path / "feed.toml"
    cfg.write_text(
        f'state_dir = "{tmp_path / "feed-state"}"\n'
        f'gate_db = "{gate_db}"\n'
        f'scores_dir = "{scores_dir}"\n'
        f"deliver = {'true' if deliver else 'false'}\n"
    )
    return cfg


class ServiceClock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


def build_service(tmp_path: Path, *, deliver: bool) -> tuple[FeedService, ServiceClock, Path]:
    gate_db = make_gate_db(tmp_path)
    scores_dir = tmp_path / "scores"
    scores_dir.mkdir()
    import datetime as dt
    day = dt.datetime.fromtimestamp(NOW, dt.UTC).strftime("%Y-%m-%d")
    (scores_dir / f"{day}.jsonl").write_text(
        json.dumps({"mint": MINT_A, "verdict": "CLEAN"}) + "\n"
    )
    boards = [
        movers_body([entry(MINT_A, 200.0)]),
        movers_body([entry(MINT_A, 520.0)]),
    ]

    def movers_transport(method, url, headers, body):
        return 200, {}, json.dumps(boards.pop(0) if boards else movers_body([])).encode()

    def candles_transport(method, url, headers, body):
        return 200, {}, json.dumps(fixture_candles()).encode()

    clock = ServiceClock()
    service = FeedService(
        write_feed_config(tmp_path, gate_db, scores_dir, deliver=deliver),
        movers_transport=movers_transport,
        candles_transport=candles_transport,
        clock=clock,
        sleep=lambda s: None,
    )
    return service, clock, gate_db


def test_service_cycle_preview_mode_touches_no_outbox(tmp_path: Path) -> None:
    service, clock, gate_db = build_service(tmp_path, deliver=False)
    beat1 = service.cycle()
    assert beat1["alerts_this_cycle"] == []
    clock.now += 75
    beat2 = service.cycle()
    assert [a["reason"] for a in beat2["alerts_this_cycle"]] == ["accel"]
    assert beat2["alerts_this_cycle"][0]["verdict"] == "CLEAN"
    assert beat2["alerts_this_cycle"][0]["chart"] is True
    assert beat2["alerts_this_cycle"][0]["delivered"] is False
    preview = (service.cfg.state_dir / "previews.log").read_text()
    assert compose.STANDING_LINE in preview
    count = sqlite3.connect(gate_db).execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    assert count == 0
    # Budget: 2 board polls + 1 candle fetch.
    from dregg_feed.movers import utc_day
    assert service.state.budget_spent(utc_day(clock.now)) == 3
    assert (service.cfg.state_dir / "heartbeat.json").exists()
    service.state.close()


def test_service_cycle_deliver_mode_enqueues_sendphoto_with_spooled_png(tmp_path: Path) -> None:
    service, clock, gate_db = build_service(tmp_path, deliver=True)
    service.cycle()
    clock.now += 75
    beat = service.cycle()
    assert beat["alerts_this_cycle"][0]["delivered"] is True
    row = sqlite3.connect(gate_db).execute(
        "SELECT method, payload_json FROM outbox"
    ).fetchone()
    assert row[0] == "sendPhoto"
    payload = json.loads(row[1])
    photo = Path(payload["photo_path"])
    assert photo.exists() and photo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert compose.STANDING_LINE in payload["caption"]
    assert "screen said CLEAN at birth" in payload["caption"]
    service.state.close()


def test_config_refuses_unknown_keys_and_soft_cooldowns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("cooldwon_h = 3\n")
    with pytest.raises(ValueError, match="unknown config key"):
        Config.load(bad)
    soft = tmp_path / "soft.toml"
    soft.write_text("cooldown_h = 0.5\n")
    with pytest.raises(ValueError, match="cooldown_h"):
        Config.load(soft)


def test_example_config_parses_and_ships_delivery_off() -> None:
    example = Path(__file__).resolve().parent.parent / "dregg_feed" / "config.example.toml"
    cfg = Config.load(example)
    assert cfg.deliver is False
    assert cfg.daily_budget == 1200
    assert cfg.cooldown_h >= 2.0
    assert cfg.max_alerts_per_hour <= 6
