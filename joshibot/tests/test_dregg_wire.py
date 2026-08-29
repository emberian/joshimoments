"""dregg_wire: facts math, absence handling, compose determinism + escaping, lifecycle.

Everything runs offline against fixtures. The archive fixture is built through
``dregg_archive.store.Store`` (the real DDL, not a copy); the gate fixture carries
the metadata/outbox tables from ``dregg_gate.state`` plus the shared APPROVALS_DDL,
so the round-trip test exercises the same contract the deployed bot serves.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import pytest

from dregg_archive.store import Store, day_start_ms
from dregg_gate.approvals import APPROVALS_DDL
from dregg_wire import post as post_mod
from dregg_wire.facts import build_facts, caller_color, callout_facts, screen_facts
from dregg_wire.wire import compose_markdown, compose_telegram, render

DAY = "2026-08-29"
T0 = day_start_ms(DAY) + 6 * 3_600_000  # 06:00 UTC on the wire day

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


# -- fixtures --------------------------------------------------------------------------


def _score_row(**over) -> dict:
    row = {
        "mint": "Mint111111111111111111111111111111111111pump",
        "verdict": "CLEAN",
        "symbol": "OK",
        "in_validated_population": True,
        "population_notes": [],
        "features": {"dev_buy_share": 0.001},
        "deployer_history": {"launches": 0, "rips": 0, "dumps": 0, "grads": 0},
        "crew_match": None,
        "base_rates": {
            "validated_span": "2026-08-26..28 (seeded history, B1)",
            "is_rip": {"admit_rate": 0.085, "clean_precision": 1.0, "clean_ci95": [0.9995, 1.0]},
        },
        "t_scored": f"{DAY}T06:00:00+00:00",
    }
    row.update(over)
    return row


def _crew(crew_id: int, jaccard: float) -> dict:
    return {
        "crew_id": crew_id,
        "jaccard": jaccard,
        "overlap": 2,
        "crew_coins": 4,
        "crew_rips": 1,
        "crew_dumps": 3,
    }


FIXTURE_ROWS = [
    _score_row(symbol="AAA", mint="A" * 40 + "pump", features={"dev_buy_share": 0.0}),
    _score_row(symbol="BBB", mint="B" * 40 + "pump", features={"dev_buy_share": 0.02}),
    _score_row(
        symbol="<b>&EVIL",  # hostile provider-derived symbol: must render inert
        mint="E" * 40 + "pump",
        in_validated_population=False,
        population_notes=["mint_without_pump_suffix"],
        features={"dev_buy_share": 0.005},
    ),
    _score_row(
        verdict="KNOWN_CREW", symbol="CRW1", mint="C1" + "c" * 38 + "pump",
        crew_match=_crew(7, 1.0),
    ),
    _score_row(
        verdict="KNOWN_CREW", symbol="CRW2", mint="C2" + "c" * 38 + "pump",
        crew_match=_crew(7, 0.8),
    ),
    _score_row(
        verdict="NOT_CLEAN", symbol="RUG", mint="R" * 40 + "pump",
        in_validated_population=False,
        population_notes=["vendor_flag:is_mayhem_mode"],
        features={"dev_buy_share": 0.2, "is_mayhem_mode": True},
    ),
    _score_row(verdict="UNSCORED", symbol="UNK", mint="U" * 40, in_validated_population=False,
               population_notes=["vendor_flag:is_mayhem_mode:curve_unverified"], features={}),
]


@pytest.fixture()
def scores_dir(tmp_path: Path) -> Path:
    d = tmp_path / "scores"
    d.mkdir()
    (d / f"{DAY}.jsonl").write_text("\n".join(json.dumps(r) for r in FIXTURE_ROWS) + "\n")
    return d


@pytest.fixture()
def archive_db(tmp_path: Path) -> Path:
    path = tmp_path / "archive.sqlite"
    store = Store(path)
    db = store.db
    with db:
        db.execute(
            "INSERT INTO fetches (id, route, url, t_request_ms, t_response_ms, status, sha256, body_zst)"
            " VALUES (1, 'board', 'u', ?, ?, 200, 'aa', x'00')",
            (T0 - 1000, T0),
        )
        db.execute(  # yesterday's fetch: its callout must NOT count as archived today
            "INSERT INTO fetches (id, route, url, t_request_ms, t_response_ms, status, sha256, body_zst)"
            " VALUES (2, 'board', 'u', ?, ?, 200, 'bb', x'00')",
            (T0 - 90_000_000, T0 - 86_400_000),
        )
        callouts = [
            ("c1", "WalletCaller1", "M1" + "m" * 38 + "pump", T0 - 5000, "<i>pump it</i>",
             292.7, "evil<script>name", 1),
            ("c2", "WalletCaller1", "M2" + "m" * 38 + "pump", T0 - 4000, "ok", 12.0, "evil<script>name", 1),
            ("c3", "WalletCaller2", "M1" + "m" * 38 + "pump", T0 - 3000, None, None, "plain", 1),
            ("c0", "WalletCaller3", "M3" + "m" * 38 + "pump", T0 - 90_000_000, "old", 999.0, "old", 2),
        ]
        for cid, wallet, mint, t, thesis, mult, user, fetch in callouts:
            db.execute(
                "INSERT INTO callouts (callout_id, wallet, mint, t_event_ms, thesis,"
                " callout_price_first, first_seen_fetch, last_seen_fetch, n_sightings,"
                " provider_multiple_last, username_last) VALUES (?,?,?,?,?,1e-7,?,?,1,?,?)",
                (cid, wallet, mint, t, thesis, fetch, fetch, mult, user),
            )
        db.execute(
            "INSERT INTO outcomes (callout_id, method_version, computed_ms) VALUES ('c0', 'v1', ?)",
            (T0,),
        )
    db.close()
    return path


@pytest.fixture()
def gate_db(tmp_path: Path) -> Path:
    path = tmp_path / "gate.sqlite"
    db = sqlite3.connect(path)
    db.executescript(GATE_AUX_DDL + APPROVALS_DDL)
    db.commit()
    db.close()
    return path


def _facts(scores_dir: Path, archive_db: Path) -> dict:
    return build_facts(DAY, scores_dir, archive_db)


# -- facts math ------------------------------------------------------------------------


def test_screen_facts_math(scores_dir, archive_db):
    screen = _facts(scores_dir, archive_db)["screen"]
    assert screen["launches_scored"] == 7
    assert screen["verdicts"] == {"CLEAN": 3, "KNOWN_CREW": 2, "NOT_CLEAN": 1, "UNSCORED": 1}
    # validated: AAA, BBB, CRW1, CRW2 (4 rows); cleans among them: AAA, BBB
    assert screen["validated"]["count"] == 4
    assert screen["validated"]["clean"] == 2
    assert screen["validated"]["clean_rate"] == pytest.approx(2 / 4)
    assert screen["validated"]["operating_point"]["admit_rate"] == pytest.approx(0.085)
    # mayhem: RUG (feature + note) and UNK (note prefix) = 2 of 7
    assert screen["mayhem"]["count"] == 2
    assert screen["mayhem"]["share"] == pytest.approx(2 / 7)
    # notable cleans: validated first, dev-buy ascending; hostile symbol row is last
    symbols = [c["symbol"] for c in screen["notable_cleans"]]
    assert symbols == ["AAA", "BBB", "<b>&EVIL"]
    # crew watch: one fingerprint, two launches, max jaccard kept
    assert len(screen["crews"]) == 1
    crew = screen["crews"][0]
    assert crew["crew_id"] == 7 and crew["launches_today"] == 2
    assert crew["max_jaccard"] == pytest.approx(1.0)
    assert crew["crew_dumps"] == 3


def test_callout_facts_windows_and_top_claim(archive_db):
    callouts = callout_facts(archive_db, DAY)
    assert callouts["archived_today"] == 3  # c0 was first archived yesterday
    assert callouts["distinct_callers_today"] == 2
    assert callouts["distinct_mints_today"] == 2
    assert callouts["board_total"] == 4 and callouts["board_callers"] == 3
    top = callouts["top_provider_claim"]
    assert top["multiple"] == pytest.approx(292.7)  # 999x was yesterday's, excluded
    assert "not our measurement" in top["label"]
    assert callouts["top_callers"][0] == {
        "wallet": "WalletCaller1", "username": "evil<script>name", "callouts_today": 2,
    }
    # outcomes exist but none priced/final: the note states the absence
    assert callouts["outcomes"]["rows"] == 1
    assert callouts["outcomes"]["priced_1h"] == 0
    assert "mature at T+25h" in callouts["outcomes"]["note"]
    assert "armed" in callouts["removals"]["note"]


def test_archive_facts_counts_today_only(scores_dir, archive_db):
    archive = _facts(scores_dir, archive_db)["archive"]
    assert archive["fetches_today"] == 1
    assert archive["zst_bytes_today"] == 1
    assert archive["manifests_anchored"] == 0
    assert "completed days" in archive["manifest_note"]


# -- absence handling ------------------------------------------------------------------


def test_absent_everything_is_stated_not_zeroed(tmp_path):
    facts = build_facts(DAY, tmp_path / "nope", tmp_path / "missing.sqlite")
    assert "no launches scored" in facts["screen"]["absent"]
    assert "not present" in facts["callouts"]["absent"]
    assert "not present" in facts["archive"]["absent"]
    assert "not present" in facts["caller_color"]["absent"]
    text = compose_telegram(facts, 0)
    assert "no launches scored" in text
    assert "0 launches" not in text and "0.0×" not in text and "0×" not in text  # noqa: RUF001
    # the markdown artifact renders the same absences
    md = compose_markdown(facts, 0)
    assert "no launches scored" in md


def test_screen_facts_empty_rows():
    facts = screen_facts([], DAY)
    assert "absent" in facts and DAY in facts["source"]


def test_caller_color_absent_paths(tmp_path):
    assert "not present" in caller_color(None, ["w"])["absent"]
    assert "not present" in caller_color(tmp_path / "gone.parquet", ["w"])["absent"]


def test_caller_color_join_and_staleness(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    parquet = tmp_path / "estimator.parquet"
    duckdb.execute(
        "COPY (SELECT 'WalletCaller1' AS owner, -12.5 AS net_realized_sol, 0.41 AS win_rate,"
        " 17 AS n_coins_closed, 'LOSS_CUTTER' AS rp_mode, NULL AS guild,"
        " 1786751999 AS updated_through) TO '" + str(parquet) + "' (FORMAT PARQUET)"
    )
    color = caller_color(parquet, ["WalletCaller1", "WalletUnknown"])
    assert color["stale"] is True and color["as_of"] == "2026-08-14"
    joined, missing = color["entries"]
    assert joined["rp_mode"] == "LOSS_CUTTER" and joined["net_realized_sol"] == pytest.approx(-12.5)
    assert "below activity threshold" in missing["absent"]


# -- compose: determinism, links, escaping ---------------------------------------------


def test_compose_is_deterministic(scores_dir, archive_db):
    facts_a = _facts(scores_dir, archive_db)
    facts_b = _facts(scores_dir, archive_db)
    assert facts_a == facts_b
    assert render(facts_a, 0) == render(facts_b, 0)


def test_telegram_links_and_escaping(scores_dir, archive_db):
    text = compose_telegram(_facts(scores_dir, archive_db), 0)
    assert len(text) <= 4096
    # every coin mention is a pump.fun link on the symbol, mint in the href
    assert f"$AAA https://pump.fun/coin/{'A' * 40}pump" in text
    assert 'https://pump.fun/coin/M1' in text  # top provider claim links its mint
    # hostile provider strings render inert (plain text: literal, never interpreted)
    assert "<b>&EVIL" in text
    assert "evil<script>name" in text  # literal, inert in plain text
    # numbers carry their windows
    assert "2026-08-26..28" in text
    assert "run 2026-08-15" in text


def test_telegram_carries_verdict_survival_and_crew_memory(scores_dir, archive_db):
    """The standing verdict footer (survival study ship list) and the crew-memory
    facts (persistence study ship list) ride every wire, windows attached."""

    text = compose_telegram(_facts(scores_dir, archive_db), 0)
    assert "WHAT THE VERDICTS MEAN (all numbers measured 2026-08-26..28)" in text
    assert "CLEAN = safety, not a buy signal (n=8,773)" in text
    assert "the usual outcome is a quiet fade" in text
    assert "collapse 3.89% (130x CLEAN), graduation 13.49% (71x CLEAN)" in text
    assert "KNOWN-CREW = the common case, not a rare alarm (85.7% of 91,505 launches)" in text
    assert "MAYHEM = unscored on purpose" in text
    assert "never a coin score" in text  # stratum facts stay labeled as group facts
    # crew memory, on the crew section
    assert "matched their own crew 48.5% vs 0.59% for strangers" in text
    assert "the danger is the UNSEEN: no-record coins collapsed 1.03% vs 0.57%" in text


def test_telegram_stays_under_cap_when_facts_max_out(scores_dir, archive_db):
    """Five cleans + five crews (the facts caps) plus the standing footer must fit;
    the channel states its cut and the archive edition keeps the full tables."""

    facts = _facts(scores_dir, archive_db)
    clean = dict(facts["screen"]["notable_cleans"][0], symbol="WORSTCASE$$$")
    facts["screen"]["notable_cleans"] = [dict(clean) for _ in range(5)]
    crew = dict(facts["screen"]["crews"][0], symbols=["LONGSYMBOL12"] * 5)
    facts["screen"]["crews"] = [dict(crew) for _ in range(5)]
    text = compose_telegram(facts, 999)
    assert len(text) <= 4096
    assert "…and 2 more in the archive edition." in text
    assert "…and 2 more fingerprints in the archive edition." in text


def test_markdown_carries_the_full_verdict_section(scores_dir, archive_db):
    md = compose_markdown(_facts(scores_dir, archive_db), 0)
    assert "## What the verdicts mean" in md
    assert "CLEAN cohort (2026-08-26..28, n=8,773)" in md
    assert "BUNDLED cohort (2026-08-26..28, n=965)" in md
    # the held CLEAN-vs-KNOWN_CREW comparison is stated as held, not smuggled in
    assert "CLEAN-vs-KNOWN_CREW lifetime comparison missed one registered per-day" in md
    assert "Crew fingerprints are durable" in md
    assert "no record is the risk factor" in md.lower() or "No record is the risk factor" in md


def test_formatting_helpers_never_zero_pretend():
    from dregg_wire.wire import _devbuy, _sym

    assert _devbuy(None) == "0%"
    assert _devbuy(0.0) == "0%"
    assert _devbuy(3.5e-05) == "<0.01%"  # tiny-but-real stays visible
    assert _devbuy(0.0105) == "1.05%"
    assert _sym("$BHC") == "BHC"  # the template adds its own cashtag sigil


def test_markdown_links(scores_dir, archive_db):
    md = compose_markdown(_facts(scores_dir, archive_db), 0)
    assert f"[$AAA](https://pump.fun/coin/{'A' * 40}pump)" in md
    assert "stale" in md  # the wallet-layer note renders even when the join is absent
    assert "](https://pump.fun/coin/M1" in md


# -- approval -> deliver round trip ----------------------------------------------------


def _compose_args(scores_dir, archive_db, gate_db, state_dir, day=DAY, d4m_dir=None):
    return argparse.Namespace(
        day=day, scores_dir=scores_dir, archive_db=archive_db, gate_db=gate_db,
        state_dir=state_dir, wallet_parquet=None, manifest_dir=None, d4m_dir=d4m_dir,
    )


def _decide(gate_db: Path, approval_id: int, decision: str) -> None:
    db = sqlite3.connect(gate_db)
    with db:
        db.execute(
            "UPDATE approvals SET decided_at = ?, decision = ?, decided_by = 'op' WHERE id = ?",
            (time.time(), decision, approval_id),
        )
    db.close()


def test_compose_then_approve_then_deliver(scores_dir, archive_db, gate_db, tmp_path):
    state_dir = tmp_path / "wire"
    args = _compose_args(scores_dir, archive_db, gate_db, state_dir)
    out = post_mod.compose(args)
    assert out["composed"] and out["chars"] > 200
    assert out["panels"] == ["glance", "crews", "desk"]
    approval_id = out["approval_id"]

    # artifact + facts + panel PNGs landed beside the state file, stable names
    assert (state_dir / f"{DAY}.md").exists()
    assert (state_dir / f"{DAY}.facts.json").exists()
    for name in ("glance", "crews", "desk"):
        png = state_dir / f"{DAY}-{name}.png"
        assert png.exists() and png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # the markdown artifact references the panels by bare sibling filename
    markdown = (state_dir / f"{DAY}.md").read_text()
    for name in ("glance", "crews", "desk"):
        assert f"]({DAY}-{name}.png)" in markdown

    # the approval summary names the panels and carries the exact telegram text;
    # the payload carries the text, the panel manifest, and the hero preview path
    db = sqlite3.connect(gate_db)
    row = db.execute(
        "SELECT source, kind, summary, payload_json FROM approvals WHERE id = ?", (approval_id,)
    ).fetchone()
    db.close()
    assert (row[0], row[1]) == ("wire", "daily")
    payload = json.loads(row[3])
    # The operator reads what will post: the summary carries the text verbatim when
    # it fits the approvals DM, and otherwise trims ITSELF with an explicit marker
    # (never the outbox's silent 3500-char mid-word chop).
    if payload["text"] in row[2]:
        assert "[DM cap" not in row[2]
    else:
        assert "[DM cap — trimmed here; posts in full" in row[2]
        assert payload["text"][:800] in row[2]
        assert len(row[2]) <= 3500  # under the outbox clip: our marker survives
    assert "3 panels + the full text" in row[2]
    assert "the crew board" in row[2]
    assert "DREGG WIRE #0" in row[2]
    assert [p["name"] for p in payload["panels"]] == ["glance", "crews", "desk"]
    assert payload["preview_photo_path"].endswith(f"{DAY}-glance.png")
    for panel in payload["panels"]:
        assert len(panel["caption"]) <= 1024

    deliver_args = argparse.Namespace(gate_db=gate_db, state_dir=state_dir)

    # undecided: deliver waits, state stays pending
    assert post_mod.deliver(deliver_args)["waiting"] == [DAY]
    assert post_mod.load_state(state_dir)[DAY]["status"] == "pending"

    # approved but no group bound: sticks at 'approved', never dropped
    _decide(gate_db, approval_id, "approve")
    assert post_mod.deliver(deliver_args)["waiting"] == [DAY]
    assert post_mod.load_state(state_dir)[DAY]["status"] == "approved"

    # bind the group; delivery enqueues the ordered media sequence + closing text
    db = sqlite3.connect(gate_db)
    with db:
        db.execute("INSERT INTO metadata (key, value) VALUES ('group_id', '-100777')")
    db.close()
    assert post_mod.deliver(deliver_args)["delivered"] == [DAY]
    db = sqlite3.connect(gate_db)
    rows = db.execute(
        "SELECT dedup_key, method, payload_json FROM outbox ORDER BY id"
    ).fetchall()
    db.close()
    assert [r[1] for r in rows] == ["sendPhoto", "sendPhoto", "sendPhoto", "sendMessage"]
    assert [r[0] for r in rows] == [
        f"wire-{DAY}-p1-glance", f"wire-{DAY}-p2-crews", f"wire-{DAY}-p3-desk", f"wire-{DAY}",
    ]
    for _dedup, method, payload_json in rows:
        item = json.loads(payload_json)
        assert item["chat_id"] == -100777
        assert "parse_mode" not in item  # plain text everywhere — hard production rule
        if method == "sendPhoto":
            assert Path(item["photo_path"]).exists()
            assert 0 < len(item["caption"]) <= 1024
        else:
            assert item["text"] == payload["text"]

    # compose again: refuses to double-enqueue a delivered day
    again = post_mod.compose(args)
    assert not again["composed"] and "delivered" in again["reason"]

    # deliver with nothing pending exits with a note
    assert post_mod.deliver(deliver_args)["note"] == "nothing pending"


def test_reject_marks_skipped_and_posts_nothing(scores_dir, archive_db, gate_db, tmp_path):
    state_dir = tmp_path / "wire"
    out = post_mod.compose(_compose_args(scores_dir, archive_db, gate_db, state_dir))
    _decide(gate_db, out["approval_id"], "reject")
    result = post_mod.deliver(argparse.Namespace(gate_db=gate_db, state_dir=state_dir))
    assert result["skipped"] == [DAY] and result["delivered"] == []
    assert post_mod.load_state(state_dir)[DAY]["status"] == "skipped"
    db = sqlite3.connect(gate_db)
    assert db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    db.close()
    # a skipped day MAY be recomposed (fresh approval, new id)
    out2 = post_mod.compose(_compose_args(scores_dir, archive_db, gate_db, state_dir))
    assert out2["composed"] and out2["approval_id"] != out["approval_id"]


def test_panel_render_failure_degrades_to_text_only(
    scores_dir, archive_db, gate_db, tmp_path, monkeypatch
):
    """A broken renderer never silences the wire: compose ships text-only, the
    summary says so, and delivery enqueues exactly the one sendMessage."""

    def boom(*_args, **_kwargs):
        raise ValueError("matplotlib exploded")

    monkeypatch.setattr(post_mod, "build_panels", boom)
    state_dir = tmp_path / "wire"
    out = post_mod.compose(_compose_args(scores_dir, archive_db, gate_db, state_dir))
    assert out["composed"] and out["panels"] == []

    db = sqlite3.connect(gate_db)
    summary, payload_json = db.execute(
        "SELECT summary, payload_json FROM approvals WHERE id = ?", (out["approval_id"],)
    ).fetchone()
    payload = json.loads(payload_json)
    assert "text only" in summary and "panel render failed" in summary
    assert payload["panels"] == [] and "preview_photo_path" not in payload
    with db:
        db.execute("INSERT INTO metadata (key, value) VALUES ('group_id', '-100777')")
        db.execute(
            "UPDATE approvals SET decided_at = 1, decision = 'approve', decided_by = 'op'"
        )
    db.close()
    result = post_mod.deliver(argparse.Namespace(gate_db=gate_db, state_dir=state_dir))
    assert result["delivered"] == [DAY]
    db = sqlite3.connect(gate_db)
    rows = db.execute("SELECT dedup_key, method FROM outbox ORDER BY id").fetchall()
    db.close()
    assert rows == [(f"wire-{DAY}", "sendMessage")]
    # the markdown artifact carries no dangling image refs
    assert "](2026" not in (state_dir / f"{DAY}.md").read_text().replace("](https", "")


def test_issue_number_counts_prior_days():
    assert post_mod.issue_number({}, DAY) == 0
    state = {"2026-08-27": {}, "2026-08-28": {}, "2026-08-30": {}}
    assert post_mod.issue_number(state, DAY) == 2
