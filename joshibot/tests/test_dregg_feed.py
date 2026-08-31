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
from dregg_feed.charts import (
    ChartRenderer,
    MontagePanel,
    choose_candle_query,
    panel_from_candles,
    parse_candles,
    render_chart,
    render_montage,
)
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


# -- the montage ----------------------------------------------------------------------


def make_panels(n: int) -> list[MontagePanel]:
    return [
        panel_from_candles(MINTS[i], f"SYM{i}", parse_candles(fixture_candles(12 + i)))
        for i in range(n)
    ]


def test_montage_bytes_are_deterministic_and_depend_on_the_panels() -> None:
    panels = make_panels(6)
    first = render_montage(panels)
    assert first == render_montage(panels)
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    assert render_montage(make_panels(3)) != first


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_montage_packs_any_count_without_blank_padding(n: int) -> None:
    png = render_montage(make_panels(n))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # IHDR carries the dimensions: 1-row layouts are strictly shorter than 2-row ones.
    import struct
    width, height = struct.unpack(">II", png[16:24])
    assert (height < 400) == (n <= 3)
    if n in (5, 6):
        assert width == 1200  # 3x2 grid at 100 dpi


def test_montage_refuses_empty_and_oversize() -> None:
    with pytest.raises(ValueError):
        render_montage([])
    with pytest.raises(ValueError):
        render_montage(make_panels(6) + make_panels(1))


def test_panel_from_candles_measures_a_five_minute_move_when_it_can() -> None:
    candles = parse_candles(fixture_candles(12))  # 5m bars: baseline is one bar back
    panel = panel_from_candles(MINT_A, "AAA", candles)
    assert panel.move == pytest.approx(candles[-1].close / candles[-2].close - 1.0)
    assert panel.move_span_s == pytest.approx(300.0)
    lone = panel_from_candles(MINT_A, "AAA", candles[:1])
    assert lone.move is None and lone.move_span_s is None
    assert render_montage([lone])[:8] == b"\x89PNG\r\n\x1a\n"  # 1-candle panel renders


def test_one_minute_panels_still_measure_the_move_over_five_minutes() -> None:
    t0 = 1_756_390_000_000
    rows = [
        {"timestamp": t0 + i * 60_000, "close": f"{1e-7 * (1 + i / 20):.12f}",
         "volume": "5.0"}
        for i in range(12)
    ]
    panel = panel_from_candles(MINT_A, "AAA", parse_candles(rows), interval="1m")
    # Baseline lands exactly 5 bars back on a 1m series: a five-minute move.
    assert panel.move_span_s == pytest.approx(300.0)
    assert panel.move == pytest.approx((1 + 11 / 20) / (1 + 6 / 20) - 1.0)
    # A coin younger than 5 minutes measures over its whole life and says so.
    baby = panel_from_candles(MINT_A, "AAA", parse_candles(rows[:3]), interval="1m")
    assert baby.move_span_s == pytest.approx(120.0)


def test_panel_staleness_comes_from_the_clock_and_reaches_the_pixels() -> None:
    candles = parse_candles(fixture_candles(12))
    end_ms = candles[-1].ts_ms + 300_000  # the newest bucket's end
    fresh = panel_from_candles(MINT_A, "AAA", candles, now_ms=end_ms + 30_000)
    stale = panel_from_candles(MINT_A, "AAA", candles, now_ms=end_ms + 900_000)
    unclocked = panel_from_candles(MINT_A, "AAA", candles)
    assert fresh.stale_s == pytest.approx(30.0)
    assert stale.stale_s == pytest.approx(900.0)
    assert unclocked.stale_s is None
    # The stale marking is visible: same candles, different bytes...
    assert render_montage([stale]) != render_montage([fresh])
    # ...while a FRESH clock stays out of the image entirely: two different instants
    # inside the two-minute band render byte-identical (the clock is data, not paint).
    fresh2 = panel_from_candles(MINT_A, "AAA", candles, now_ms=end_ms + 31_000)
    assert render_montage([fresh]) == render_montage([fresh2])


def test_revived_coin_windows_clip_to_the_query_span_and_say_thin_tape() -> None:
    t0 = 1_756_390_000_000
    # A 20-day-old coin whose 72 5m bars span days: 70 ancient bars + 2 recent ones.
    rows = [
        {"timestamp": t0 + i * 300_000, "close": "1.0e-7", "volume": "1.0"}
        for i in range(70)
    ] + [
        {"timestamp": t0 + 240 * 3_600_000 + i * 300_000, "close": "2.0e-7", "volume": "9.0"}
        for i in range(2)
    ]
    clipped = panel_from_candles(MINT_A, "AAA", parse_candles(rows), limit=72, young=False)
    assert len(clipped.candles) == 2  # only the bars inside the 6h drawing window
    unclipped = panel_from_candles(MINT_A, "AAA", parse_candles(rows))
    assert len(unclipped.candles) == 72
    # Old + sparse-in-window says "thin tape", never "new"; both render fine.
    assert render_montage([clipped]) != render_montage(
        [panel_from_candles(MINT_A, "AAA", parse_candles(rows[-2:]), young=True)]
    )


def test_candle_query_adapts_to_coin_age() -> None:
    assert choose_candle_query(180) == ("1m", 60)        # 3-minute newborn
    assert choose_candle_query(44 * 60) == ("1m", 60)    # still under 45m
    assert choose_candle_query(45 * 60) == ("5m", 72)    # 45m and older: the 6h window
    assert choose_candle_query(6 * 3600) == ("5m", 72)
    assert choose_candle_query(None) == ("5m", 72)       # age unknown: default
    assert choose_candle_query(120, default_interval="1h", default_limit=24) == ("1m", 60)
    assert choose_candle_query(None, default_interval="1h", default_limit=24) == ("1h", 24)


def test_sparse_panels_draw_dots_and_say_new_instead_of_a_diagonal() -> None:
    rows = fixture_candles(12)
    sparse = panel_from_candles(MINT_A, "AAA", parse_candles(rows[:3]))
    dense = panel_from_candles(MINT_A, "AAA", parse_candles(rows))
    png_sparse = render_montage([sparse])
    assert png_sparse[:8] == b"\x89PNG\r\n\x1a\n"
    assert png_sparse == render_montage([sparse])  # sparse mode stays deterministic
    assert png_sparse != render_montage([dense])
    # The boundary: 5 bars draws the line path, 4 draws the sparse tile.
    four = panel_from_candles(MINT_A, "AAA", parse_candles(rows[:4]))
    five = panel_from_candles(MINT_A, "AAA", parse_candles(rows[:5]))
    assert render_montage([four]) != render_montage([five])


def test_series_gaps_render_as_holes_not_interpolation() -> None:
    rows = fixture_candles(12)
    gapped = parse_candles(rows[:5] + rows[9:])  # a 20-minute hole in the tape
    solid = parse_candles(rows)
    a = render_montage([panel_from_candles(MINT_A, "AAA", gapped)])
    b = render_montage([panel_from_candles(MINT_A, "AAA", solid)])
    assert a != b  # the hole reaches the pixels rather than being drawn across


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


def test_movers_parse_drops_duplicate_mint_rows() -> None:
    page = parse_movers(movers_body([
        entry(MINT_A, 254.3), entry(MINT_A, 999.0), entry(MINT_B, 100.0),
    ]))
    assert [e.mint for e in page.entries] == [MINT_A, MINT_B]
    assert page.entries[0].v5 == pytest.approx(254.3)  # first occurrence wins


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


def test_montage_caption_lists_every_coin_and_ends_with_the_standing_line() -> None:
    items = [
        (sample_alert(), "CLEAN"),
        (sample_alert(mint=MINT_B, symbol="fckstr", v5=263.2), None),
        (sample_alert(mint=MINTS[0], symbol="THIRD", v5=800.0), "KNOWN_CREW"),
    ]
    text = compose.montage_caption(items)
    lines = text.split("\n")
    assert lines[0].startswith("📊 3 movers on pump.fun")
    assert "provider claims" in lines[0]
    assert lines[1] == f"$FROGE  https://pump.fun/coin/{MINT_A} · 5m 254 SOL · birth: CLEAN"
    assert f"https://pump.fun/coin/{MINT_B} · 5m 263 SOL · birth: pre-screen/unscored" in lines[2]
    assert "birth: KNOWN-CREW" in lines[3]
    # a CLEAN in the montage brings the one-line gloss so the tag never reads as
    # a buy call; it rides just above the standing line
    assert lines[-2] == "CLEAN = no known operators at birth, not a price call."
    assert lines[-1] == compose.STANDING_LINE
    assert "🚀" not in text


def test_montage_caption_gloss_only_when_a_clean_appears() -> None:
    no_clean = compose.montage_caption([(sample_alert(), "KNOWN_CREW")])
    assert "no known operators" not in no_clean
    with_clean = compose.montage_caption([(sample_alert(), "CLEAN")])
    assert "CLEAN = no known operators at birth, not a price call." in with_clean
    # the gloss is budgeted into the 1024-char cap math (compose module docstring)
    from dregg_screen.survival import CLEAN_FEED_GLOSS
    assert len(CLEAN_FEED_GLOSS) <= 63


def test_montage_caption_is_plain_text_and_newline_proof() -> None:
    hostile = sample_alert(symbol='<b>&PWN"\nEXTRA LINE')
    text = compose.montage_caption([(hostile, None)])
    # No markup of ours anywhere — provider text is literal-inert in plain text...
    assert "parse_mode" not in text and "<a href" not in text
    # ...and a newline smuggled into a symbol cannot mint an extra caption line.
    assert len(text.split("\n")) == 3  # header, one coin, standing line
    assert '$<b>&PWN"EXTR' in text


def test_montage_caption_stays_under_telegram_cap_with_six_worst_case_coins() -> None:
    items = [
        (
            sample_alert(
                mint=MINTS[i], symbol="W" * 60, v5=999_999_999.9,
            ),
            None,  # the longest verdict rendering
        )
        for i in range(6)
    ]
    text = compose.montage_caption(items)
    assert len(text) <= compose.CAPTION_MAX
    assert text.split("\n")[-1] == compose.STANDING_LINE
    # worst case WITH the CLEAN gloss line and 18-char disambiguated labels: five
    # longest-verdict coins plus one CLEAN, every label at the wide clamp
    items = [
        (sample_alert(mint=MINTS[i], symbol="W" * 60, v5=999_999_999.9),
         "CLEAN" if i == 5 else None)
        for i in range(6)
    ]
    labels = {MINTS[i]: "X" * 60 for i in range(6)}
    text = compose.montage_caption(items, labels=labels)
    assert len(text) <= compose.CAPTION_MAX
    assert "CLEAN = no known operators at birth, not a price call." in text


def test_montage_caption_refuses_empty() -> None:
    with pytest.raises(ValueError):
        compose.montage_caption([])


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


def build_service(
    tmp_path: Path, *, deliver: bool, candle_urls: list[str] | None = None
) -> tuple[FeedService, ServiceClock, Path]:
    gate_db = make_gate_db(tmp_path)
    scores_dir = tmp_path / "scores"
    scores_dir.mkdir()
    import datetime as dt
    day = dt.datetime.fromtimestamp(NOW, dt.UTC).strftime("%Y-%m-%d")
    (scores_dir / f"{day}.jsonl").write_text(
        json.dumps({"mint": MINT_A, "verdict": "CLEAN"}) + "\n"
    )
    # Poll 1 seeds baselines; poll 2 has TWO accelerants (one montage); poll 3, still
    # inside the montage window, has a fresh third qualifier that must be HELD.
    boards = [
        movers_body([entry(MINT_A, 200.0), entry(MINT_B, 300.0), entry(MINTS[0], 260.0)]),
        movers_body([entry(MINT_A, 520.0), entry(MINT_B, 700.0), entry(MINTS[0], 265.0)]),
        movers_body([entry(MINTS[0], 900.0)]),
    ]

    def movers_transport(method, url, headers, body):
        return 200, {}, json.dumps(boards.pop(0) if boards else movers_body([])).encode()

    def candles_transport(method, url, headers, body):
        if candle_urls is not None:
            candle_urls.append(url)
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


def test_service_cycle_preview_mode_batches_a_montage_and_touches_no_outbox(
    tmp_path: Path,
) -> None:
    service, clock, gate_db = build_service(tmp_path, deliver=False)
    beat1 = service.cycle()
    assert beat1["alerts_this_cycle"] == []
    clock.now += 75
    beat2 = service.cycle()
    # Both accelerants ride ONE montage, ordered by v5 (B > A), each with a panel.
    assert [a["mint"] for a in beat2["alerts_this_cycle"]] == [MINT_B, MINT_A]
    assert all(a["reason"] == "accel" and a["chart"] for a in beat2["alerts_this_cycle"])
    assert beat2["alerts_this_cycle"][1]["verdict"] == "CLEAN"
    assert beat2["last_montage"] == {
        "t": beat2["last_montage"]["t"], "coins": 2, "panels": 2, "delivered": False,
    }
    preview = (service.cfg.state_dir / "previews.log").read_text()
    assert preview.count(compose.STANDING_LINE) == 1  # one caption, not one per coin
    count = sqlite3.connect(gate_db).execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    assert count == 0
    # Budget: 2 board polls + 2 candle fetches (one per montage coin).
    from dregg_feed.movers import utc_day
    assert service.state.budget_spent(utc_day(clock.now)) == 4
    # Poll 3: a fresh qualifier inside the 12-min montage window is HELD, unrecorded.
    clock.now += 75
    beat3 = service.cycle()
    assert beat3["alerts_this_cycle"] == []
    assert "held" in (beat3["montage_hold"] or "")
    assert service.state.last_alert_at_any() == pytest.approx(clock.now - 75)
    service.state.close()


def test_service_cycle_deliver_mode_enqueues_one_sendphoto_montage(tmp_path: Path) -> None:
    service, clock, gate_db = build_service(tmp_path, deliver=True)
    service.cycle()
    clock.now += 75
    beat = service.cycle()
    assert all(a["delivered"] for a in beat["alerts_this_cycle"])
    rows = sqlite3.connect(gate_db).execute(
        "SELECT method, payload_json FROM outbox"
    ).fetchall()
    assert [r[0] for r in rows] == ["sendPhoto"]  # ONE photo for the whole batch
    payload = json.loads(rows[0][1])
    assert "parse_mode" not in payload  # plain text, no HTML
    photo = Path(payload["photo_path"])
    assert photo.name.startswith("montage-")
    assert photo.exists() and photo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    caption = payload["caption"]
    assert caption.split("\n")[-1] == compose.STANDING_LINE
    assert "<" not in caption  # nothing markup-shaped of ours
    # Caption line order mirrors panel order: B (higher v5) first, then A.
    assert caption.index(MINT_B) < caption.index(MINT_A)
    assert f"https://pump.fun/coin/{MINT_A} · 5m 520 SOL · birth: CLEAN" in caption
    assert "birth: pre-screen/unscored" in caption  # MINT_B is not in the scores
    service.state.close()


def test_service_disambiguates_colliding_symbols_and_adapts_the_interval(
    tmp_path: Path,
) -> None:
    """Two mints legitimately sharing the ticker "Pepsi" (the measured pump reality)
    get mint-suffixed labels in the caption; the newborn one is charted at 1m."""

    candle_urls: list[str] = []
    service, clock, gate_db = build_service(tmp_path, deliver=True, candle_urls=candle_urls)
    boards = [
        movers_body([
            entry(MINTS[0], 300.0, t="Pepsi", age=9_000),
            entry(MINTS[1], 310.0, t="Pepsi", age=240),
        ]),
        movers_body([
            entry(MINTS[0], 600.0, t="Pepsi", age=9_075),
            entry(MINTS[1], 900.0, t="Pepsi", age=315),
        ]),
    ]
    service._movers_transport = (
        lambda method, url, headers, body: (200, {}, json.dumps(boards.pop(0)).encode())
    )
    service.cycle()
    clock.now += 75
    service.cycle()
    payload = json.loads(
        sqlite3.connect(gate_db).execute("SELECT payload_json FROM outbox").fetchone()[0]
    )
    cap = payload["caption"]
    assert f"$Pepsi·{MINTS[1][:4]}" in cap and f"$Pepsi·{MINTS[0][:4]}" in cap
    assert "$Pepsi " not in cap  # no un-suffixed twin survives
    # Caption order still mirrors tile order: higher v5 (the newborn) leads.
    assert cap.index(MINTS[1]) < cap.index(MINTS[0])
    # The 4-minute-old coin was fetched at 1m; the 2.5h-old one at the 5m default.
    assert any(MINTS[1] in u and "interval=1m" in u for u in candle_urls)
    assert any(MINTS[0] in u and "interval=5m" in u for u in candle_urls)
    service.state.close()


def test_montage_caption_uses_disambiguation_labels_verbatim() -> None:
    items = [
        (sample_alert(mint=MINTS[0], symbol="Pepsi"), "CLEAN"),
        (sample_alert(mint=MINTS[1], symbol="Pepsi", v5=100.0), None),
    ]
    labels = {MINTS[0]: f"Pepsi·{MINTS[0][:4]}", MINTS[1]: f"Pepsi·{MINTS[1][:4]}"}
    text = compose.montage_caption(items, labels=labels)
    assert f"$Pepsi·{MINTS[0][:4]}  https://pump.fun/coin/{MINTS[0]}" in text
    assert f"$Pepsi·{MINTS[1][:4]}  https://pump.fun/coin/{MINTS[1]}" in text
    assert len(text) <= compose.CAPTION_MAX


def test_service_montage_takes_top_by_v5_and_leaves_the_rest_eligible(tmp_path: Path) -> None:
    """8 qualifiers, montage_max=6: the top six by v5 ship, the two dropped coins'
    cooldowns are untouched so the next window can carry them."""

    service, clock, _gate_db = build_service(tmp_path, deliver=True)
    boards = [
        movers_body([entry(MINTS[i], 300.0) for i in range(8)]),
        movers_body([entry(MINTS[i], 600.0 + i) for i in range(8)]),
    ]
    service._movers_transport = (
        lambda method, url, headers, body: (200, {}, json.dumps(boards.pop(0)).encode())
    )
    service.cycle()
    clock.now += 75
    beat = service.cycle()
    sent = [a["mint"] for a in beat["alerts_this_cycle"]]
    assert len(sent) == 6
    assert sent == [MINTS[i] for i in (7, 6, 5, 4, 3, 2)]  # top six by v5, descending
    for dropped in (MINTS[0], MINTS[1]):
        assert service.state.last_alert_at(dropped) is None  # eligible next montage
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
    assert cfg.montage_max == 6
    assert cfg.montage_window_min == 12.0
    # The legacy key must stay ACCEPTED: the deployed hbox config names it, and a
    # restart that refused it would crash-loop the live service.
    assert cfg.max_alerts_per_hour == 6
