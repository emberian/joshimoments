"""dregg_wire.visuals: renderer determinism, honest empty panels, the d4m seam,
caption caps, panel assembly, and the gate presenter's hero preview.

Renderers are pure functions of plain dicts, so most fixtures here are dicts built
by hand; the crew-history and d4m paths get real files in tmp dirs. No network, no
clocks, no live Telegram.
"""

from __future__ import annotations

import json
from pathlib import Path

from dregg_wire import visuals
from dregg_wire.facts import callout_facts, screen_facts
from dregg_wire.visuals import (
    build_panels,
    crew_board_data,
    crew_caption,
    crew_day_history,
    desk_caption,
    hero_caption,
    load_d4m_crew_graph,
    render_callout_desk,
    render_crew_board,
    render_day_glance,
)

DAY = "2026-08-29"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def make_facts(**over) -> dict:
    facts = {
        "day": DAY,
        "screen": {
            "source": f"dregg_screen scores/{DAY}.jsonl, UTC day {DAY}",
            "launches_scored": 7,
            "verdicts": {"CLEAN": 3, "KNOWN_CREW": 2, "NOT_CLEAN": 1, "UNSCORED": 1},
            "hourly": {
                "06": {"CLEAN": 2, "NOT_CLEAN": 1},
                "11": {"CLEAN": 1, "KNOWN_CREW": 2, "UNSCORED": 1},
            },
            "hourly_unplaced": 0,
            "validated": {
                "count": 4, "clean": 2, "clean_rate": 0.5,
                "operating_point": {"admit_rate": 0.085, "clean_precision": 1.0,
                                    "validated_span": "2026-08-26..28"},
            },
            "mayhem": {"count": 2, "share": 2 / 7, "definition": "vendor flag"},
            "notable_cleans": [], "crews": [], "crews_note": None,
        },
        "callouts": {
            "source": f"dregg_archive archive.sqlite, callouts on {DAY}",
            "archived_today": 5, "distinct_callers_today": 3, "distinct_mints_today": 4,
            "board_total": 200, "board_callers": 150,
            "top_provider_claim": {"multiple": 292.7, "mint": "M" * 44,
                                   "username": "loudcaller", "thesis": "up only",
                                   "label": "provider-claimed"},
            "anti_signal": {"ret_1h_mean": -0.119, "ret_8h_mean": -0.436,
                            "burst_ret_8h_median": -0.647,
                            "burst_definition": "2+ callers in 10min",
                            "short_source": "callout-edge study, run 2026-08-15",
                            "source": "callout-edge study"},
            "measured": [],
            "top_callers": [],
            "removals": {"today": 0, "total": 0, "note": "armed"},
            "outcomes": {"rows": 7, "final": 0, "priced_1h": 0,
                         "note": "mature at T+25h; cohorts in flight"},
        },
        "archive": {"source": "raw", "fetches_today": 1, "zst_bytes_today": 1,
                    "manifests_anchored": 0, "manifest_note": None},
        "caller_color": {"absent": "not present", "note": "stale"},
    }
    facts.update(over)
    return facts


# -- determinism + honesty -------------------------------------------------------------


def test_day_glance_deterministic_and_data_dependent():
    facts = make_facts()
    first = render_day_glance(facts)
    assert first[:8] == PNG_MAGIC
    assert first == render_day_glance(make_facts())
    other = make_facts()
    other["screen"]["hourly"]["06"]["CLEAN"] = 9
    other["screen"]["verdicts"]["CLEAN"] = 10
    assert render_day_glance(other) != first


def test_day_glance_absent_screen_is_an_honest_empty_panel():
    facts = make_facts(screen={"source": "s", "absent": "no launches scored on " + DAY})
    png = render_day_glance(facts)
    assert png[:8] == PNG_MAGIC
    assert png == render_day_glance(facts)
    assert png != render_day_glance(make_facts())


def test_desk_deterministic_with_claim_and_dumbbells():
    facts = make_facts()
    facts["callouts"]["measured"] = [
        {"callout_id": "c1", "mint": "M" * 44, "username": "seer",
         "claimed_multiple": 12.0, "ret_1h": -0.4, "ret_24h": -0.8, "ret_7d": None,
         "max_close_multiple": 1.6, "final": False},
        {"callout_id": "c2", "mint": "N" * 44, "username": None,
         "claimed_multiple": None, "ret_1h": -0.9, "ret_24h": None, "ret_7d": None,
         "max_close_multiple": None, "final": True},
    ]
    png = render_callout_desk(facts)
    assert png[:8] == PNG_MAGIC and png == render_callout_desk(facts)
    assert png != render_callout_desk(make_facts())


def test_desk_empty_states_render_and_say_why():
    absent = make_facts(callouts={"source": "s", "absent": "archive not present at /x"})
    quiet = make_facts()
    quiet["callouts"].update(
        {"archived_today": 0, "top_provider_claim": None, "measured": []}
    )
    for facts in (absent, quiet):
        png = render_callout_desk(facts)
        assert png[:8] == PNG_MAGIC and png == render_callout_desk(facts)
    assert render_callout_desk(absent) != render_callout_desk(quiet)


# -- facts feeding the hero ------------------------------------------------------------


def test_screen_facts_hourly_binning_and_unplaced():
    rows = [
        {"verdict": "CLEAN", "t_scored": f"{DAY}T06:10:00+00:00"},
        {"verdict": "CLEAN", "t_scored": f"{DAY}T06:59:59+00:00"},
        {"verdict": "NOT_CLEAN", "t_scored": f"{DAY}T23:00:00+00:00"},
        {"verdict": "CLEAN", "t_scored": "not a timestamp"},
        {"verdict": "CLEAN"},  # no t_scored at all
    ]
    screen = screen_facts(rows, DAY)
    assert screen["hourly"] == {"06": {"CLEAN": 2}, "23": {"NOT_CLEAN": 1}}
    assert screen["hourly_unplaced"] == 2


def test_callout_facts_measured_join(tmp_path):
    from dregg_archive.store import Store, day_start_ms

    db_path = tmp_path / "archive.sqlite"
    store = Store(db_path)
    t0 = day_start_ms(DAY) + 3_600_000
    with store.db:
        store.db.execute(
            "INSERT INTO fetches (id, route, url, t_request_ms, t_response_ms, status, sha256,"
            " body_zst) VALUES (1, 'board', 'u', ?, ?, 200, 'aa', x'00')",
            (t0 - 1000, t0),
        )
        store.db.execute(
            "INSERT INTO callouts (callout_id, wallet, mint, t_event_ms, thesis,"
            " callout_price_first, first_seen_fetch, last_seen_fetch, n_sightings,"
            " provider_multiple_last, username_last)"
            " VALUES ('c1', 'W1', 'M1', ?, 'moon', 1e-7, 1, 1, 1, 40.0, 'seer')",
            (t0,),
        )
        store.db.execute(
            "INSERT INTO outcomes (callout_id, method_version, ret_1h, ret_24h,"
            " max_close_multiple, dead_flag, computed_ms) VALUES"
            " ('c1', 'v1', -0.5, -0.9, 2.5, 1, ?)",
            (t0,),
        )
    store.db.close()
    callouts = callout_facts(db_path, DAY)
    (entry,) = callouts["measured"]
    assert entry["claimed_multiple"] == 40.0
    assert entry["max_close_multiple"] == 2.5
    assert entry["final"] is True


# -- the crew board + the d4m seam -----------------------------------------------------


def write_scores(scores_dir: Path, day: str, crews: list[tuple[int, int]]) -> None:
    """crews = [(crew_id, launches)] for one day's ledger."""

    rows = []
    for crew_id, launches in crews:
        for i in range(launches):
            rows.append(
                {
                    "mint": f"{crew_id}x{i}",
                    "verdict": "KNOWN_CREW",
                    "t_scored": f"{day}T0{i % 9}:00:00+00:00",
                    "crew_match": {"crew_id": crew_id, "jaccard": 0.9, "crew_coins": 4,
                                   "crew_rips": 1, "crew_dumps": 2},
                }
            )
    scores_dir.mkdir(parents=True, exist_ok=True)
    (scores_dir / f"{day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_crew_day_history_counts_across_the_window(tmp_path):
    scores = tmp_path / "scores"
    write_scores(scores, DAY, [(7, 2), (9, 1)])
    write_scores(scores, "2026-08-27", [(7, 3)])
    history = crew_day_history(scores, DAY)
    assert history["days"][-1] == DAY and len(history["days"]) == 7
    assert history["counts"][7]["2026-08-27"] == 3
    assert history["counts"][7][DAY] == 2
    assert history["counts"][9][DAY] == 1
    assert history["records"][7]["crew_dumps"] == 2


def test_d4m_artifact_drives_the_graph_and_caps_are_stated(tmp_path):
    d4m = tmp_path / "d4m"
    d4m.mkdir()
    nodes = [{"crew_id": i, "launches_today": 20 - i, "crew_coins": i + 2,
              "crew_rips": 0, "crew_dumps": i % 3} for i in range(14)]
    edges = [{"a": i, "b": (i + 1) % 14, "shared_wallets": 1 + i % 5} for i in range(14)]
    (d4m / f"crew_graph-{DAY}.json").write_text(
        json.dumps({"day": DAY, "nodes": nodes, "edges": edges})
    )
    board = crew_board_data(make_facts(), None, d4m)
    assert board["mode"] == "graph"
    assert len(board["nodes"]) == visuals.MAX_GRAPH_NODES
    assert "showing top 10 of 14 crews" in board["note"]
    assert all(e["a"] in {n["crew_id"] for n in board["nodes"]} for e in board["edges"])
    png = render_crew_board(board)
    assert png[:8] == PNG_MAGIC and png == render_crew_board(board)


def test_d4m_malformed_or_stale_falls_back_to_the_ledger_heatmap(tmp_path):
    scores = tmp_path / "scores"
    write_scores(scores, DAY, [(7, 2)])
    cases = ('{"nodes": "nope"}', "torn{", json.dumps({"day": "2020-01-01", "nodes": []}))
    for case_index, bad in enumerate(cases):
        d4m = tmp_path / f"d4m-{case_index}"
        d4m.mkdir()
        (d4m / "crew_graph.json").write_text(bad)
        board = crew_board_data(make_facts(), scores, d4m)
        assert board["mode"] == "heatmap"
        assert "d4m artifact" in (board["note"] or "")
        png = render_crew_board(board)
        assert png[:8] == PNG_MAGIC and png == render_crew_board(board)


def test_d4m_absent_dir_is_a_clean_miss(tmp_path):
    assert load_d4m_crew_graph(None, DAY) == (None, None)
    assert load_d4m_crew_graph(tmp_path / "nothing", DAY) == (None, None)


def test_crew_board_empty_is_honest(tmp_path):
    board = crew_board_data(make_facts(), tmp_path / "no-scores", None)
    assert board["mode"] == "empty"
    assert "no crew-fingerprint matches" in board["reason"]
    png = render_crew_board(board)
    assert png[:8] == PNG_MAGIC and png == render_crew_board(board)


# -- captions + assembly ---------------------------------------------------------------


def test_captions_are_capped_and_flatten_hostile_strings():
    facts = make_facts()
    facts["callouts"]["top_provider_claim"]["username"] = "evil\nnewline " + "x" * 500
    facts["screen"]["verdicts"] = {f"VERDICT_{i}" + "y" * 40: 1 for i in range(30)}
    hero = hero_caption(facts, 3, "a lede line")
    desk = desk_caption(facts)
    assert len(hero) <= 1024 and len(desk) <= 1024
    assert hero.startswith(f"DREGG WIRE #3 — {DAY}\na lede line")
    assert "evil newline" in desk and "evil\nnewline" not in desk


def test_crew_caption_names_the_top_rows(tmp_path):
    scores = tmp_path / "scores"
    write_scores(scores, DAY, [(7, 2), (9, 1)])
    board = crew_board_data(make_facts(), scores, None)
    caption = crew_caption(board)
    assert caption.splitlines()[0] == f"Crew board — {DAY}"
    assert "#7: 2 today" in caption and len(caption) <= 1024


def test_build_panels_order_names_and_captions(tmp_path):
    scores = tmp_path / "scores"
    write_scores(scores, DAY, [(7, 1)])
    panels = build_panels(make_facts(), 4, "a lede", scores_dir=scores, d4m_dir=None)
    assert [p.name for p in panels] == ["glance", "crews", "desk"]
    assert [p.title for p in panels] == ["the day at a glance", "the crew board", "the callout desk"]
    for panel in panels:
        assert panel.png[:8] == PNG_MAGIC
        assert 0 < len(panel.caption) <= 1024
        assert "parse_mode" not in panel.caption
    again = build_panels(make_facts(), 4, "a lede", scores_dir=scores, d4m_dir=None)
    assert [p.png for p in panels] == [p.png for p in again]  # panel set is deterministic


# -- the approval DM carries the hero --------------------------------------------------


async def test_presenter_dms_the_preview_photo_before_the_buttons(tmp_path):
    from dregg_gate.approvals import enqueue_approval
    from dregg_gate.config import Config
    from dregg_gate.gateway import GateGateway
    from dregg_gate.state import GateState

    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
    )
    hero = tmp_path / "hero.png"
    hero.write_bytes(PNG_MAGIC)
    with_photo = enqueue_approval(
        cfg.db_path, "wire", "daily", "WIRE #0 — panels: …",
        {"day": DAY, "text": "t", "panels": [], "preview_photo_path": str(hero)},
    )
    plain = enqueue_approval(cfg.db_path, "wire", "daily", "text-only wire", {"text": "t"})
    state = GateState(cfg.db_path)
    gateway = GateGateway(cfg, state, None, None, clock=lambda: 1.0)  # type: ignore[arg-type]
    assert gateway.present_approvals() == 2
    items = state.pending()
    methods = [(item.method, item.payload.get("photo_path"), item.payload.get("text")) for item in items]
    # the preview photo rides FIRST, then the buttons DM; the plain approval gets no photo
    assert methods[0][0] == "sendPhoto" and methods[0][1] == str(hero)
    assert methods[1][0] == "sendMessage" and f"Approval #{with_photo}" in methods[1][2]
    assert methods[2][0] == "sendMessage" and f"Approval #{plain}" in methods[2][2]
    assert [item.method for item in items].count("sendPhoto") == 1
    state.close()
