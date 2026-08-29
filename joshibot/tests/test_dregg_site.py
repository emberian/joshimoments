"""dregg_site: generation from fixtures, honest absence, no fake numbers, determinism, links.

Offline throughout. The archive fixture goes through ``dregg_archive.store.Store`` (the
real DDL); the score fixtures mirror the scorer's row shape, hostile provider strings
included — a symbol or thesis containing markup must render inert on every page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dregg_archive.store import Store, day_start_ms
from dregg_site import pages as pages_mod
from dregg_site.build import generate, wire_entries
from dregg_site.mdlite import render as md_render

DAY = "2026-08-29"
T0 = day_start_ms(DAY) + 6 * 3_600_000

HOSTILE = "<script>alert(1)</script>"


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
            "is_rip": {
                "admit_rate": 0.085,
                "clean_precision": 1.0,
                "clean_ci95": [0.9995, 1.0],
            },
        },
        "t_scored": f"{DAY}T06:00:00+00:00",
    }
    row.update(over)
    return row


SCORE_ROWS = [
    _score_row(symbol="AAA", mint="A" * 40 + "pump", t_scored=f"{DAY}T05:00:00+00:00"),
    _score_row(symbol="BBB", mint="B" * 40 + "pump", t_scored=f"{DAY}T07:00:00+00:00"),
    _score_row(  # hostile + unvalidated: must render inert AND sort after validated rows
        symbol=HOSTILE,
        mint="E" * 40 + "pump",
        in_validated_population=False,
        t_scored=f"{DAY}T08:00:00+00:00",
    ),
    _score_row(
        verdict="KNOWN_CREW",
        symbol="CRW",
        mint="C" * 40 + "pump",
        crew_match={"crew_id": 7, "jaccard": 0.9, "crew_coins": 4, "crew_rips": 1, "crew_dumps": 3},
    ),
    _score_row(
        verdict="NOT_CLEAN",
        symbol="RUG",
        mint="R" * 40 + "pump",
        in_validated_population=False,
        features={"dev_buy_share": 0.2, "is_mayhem_mode": True},
    ),
]


@pytest.fixture()
def scores_dir(tmp_path: Path) -> Path:
    d = tmp_path / "scores"
    d.mkdir()
    (d / f"{DAY}.jsonl").write_text("\n".join(json.dumps(r) for r in SCORE_ROWS) + "\n")
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
        callouts = [
            ("c1", "W1", "M1" + "m" * 38 + "pump", T0 - 5000, HOSTILE + " thesis", 292.7, HOSTILE),
            ("c2", "W1", "M2" + "m" * 38 + "pump", T0 - 4000, "ok", 12.0, "caller_one"),
            ("c3", "W2", "M1" + "m" * 38 + "pump", T0 - 3000, None, None, "plain"),
        ]
        for cid, wallet, mint, t, thesis, mult, user in callouts:
            db.execute(
                "INSERT INTO callouts (callout_id, wallet, mint, t_event_ms, thesis,"
                " callout_price_first, first_seen_fetch, last_seen_fetch, n_sightings,"
                " provider_multiple_last, username_last) VALUES (?,?,?,?,?,1e-7,1,1,1,?,?)",
                (cid, wallet, mint, t, thesis, mult, user),
            )
        # one measured outcome, below any min-n: the leaderboard must stay an honest slot
        db.execute(
            "INSERT INTO outcomes (callout_id, method_version, ret_1h, computed_ms)"
            " VALUES ('c1', 'v1', -0.5, ?)",
            (T0,),
        )
    db.close()
    return path


@pytest.fixture()
def wire_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wire"
    d.mkdir()
    (d / f"{DAY}.md").write_text(
        f"# DREGG WIRE #0 — {DAY}\n\n*a lede line*\n\n"
        f"![the day at a glance {HOSTILE}]({DAY}-glance.png)\n\n## Launch screen\n\n"
        "| coin | mint |\n|---|---|\n"
        f"| [$OK](https://pump.fun/coin/{'A' * 40}pump) | `{'A' * 40}pump` |\n\n"
        f"**bold** and *italic* and `code` and hostile {HOSTILE} text\n"
        "![evil](ftp://evil.example/x.png)\n"
        "![evil](../escape.png)\n"
    )
    (d / f"{DAY}-glance.png").write_bytes(b"\x89PNG\r\n\x1a\nPANELBYTES")
    (d / "2026-08-28-crews.png").write_bytes(b"\x89PNG\r\n\x1a\nSKIPPEDDAY")
    (d / "2026-08-28.md").write_text("# DREGG WIRE — skipped day\n")
    (d / "wire_state.json").write_text(
        json.dumps({DAY: {"status": "delivered"}, "2026-08-28": {"status": "skipped"}})
    )
    (d / "notes.md").write_text("not a wire artifact\n")
    return d


def _generate(tmp_path, scores_dir, archive_db, wire_dir, name="out") -> tuple[Path, dict]:
    out = tmp_path / name
    manifest = generate(
        day=DAY, scores_dir=scores_dir, archive_db=archive_db, wire_dir=wire_dir, out_dir=out
    )
    return out, manifest


def _read_all(out: Path) -> dict[str, str]:
    return {str(p.relative_to(out)): p.read_text() for p in sorted(out.rglob("*.html"))}


# -- generation against fixtures -------------------------------------------------------


def test_generates_page_set(tmp_path, scores_dir, archive_db, wire_dir):
    out, manifest = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    assert sorted(manifest["pages"]) == sorted(
        ["index.html", "screen.html", "record.html", "research.html",
         "wire/index.html", f"wire/{DAY}.html"]
    )
    html = _read_all(out)
    assert "<b>5</b><span>launches scored</span>" in html["index.html"]
    assert "292.7" in html["record.html"]  # provider claim…
    assert "provider-claimed peaks" in html["record.html"]  # …never without its label


def test_wire_panels_embed_and_copy_only_for_published_days(
    tmp_path, scores_dir, archive_db, wire_dir
):
    out, manifest = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    # the published day's panel PNG is copied beside its page, byte-identical
    assert manifest["assets"] == [f"wire/{DAY}-glance.png"]
    assert (out / "wire" / f"{DAY}-glance.png").read_bytes() == b"\x89PNG\r\n\x1a\nPANELBYTES"
    # the skipped day's panel never ships
    assert not (out / "wire" / "2026-08-28-crews.png").exists()
    page = (out / "wire" / f"{DAY}.html").read_text()
    # the whole-line image ref renders as an <img> on a bare sibling filename,
    # with hostile alt text escaped
    assert f'<img src="{DAY}-glance.png"' in page
    assert HOSTILE not in page
    # non-sibling and remote image refs stay inert text, never tags
    assert 'src="ftp://evil.example/x.png"' not in page
    assert 'src="../escape.png"' not in page
    assert page.count("<img") == 1


def test_skipped_and_foreign_files_stay_out_of_wire_archive(wire_dir):
    entries = wire_entries(wire_dir)
    assert [e["day"] for e in entries] == [DAY]
    assert entries[0]["lede"] == "a lede line"


def test_hostile_strings_render_inert_everywhere(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    for name, text in _read_all(out).items():
        assert HOSTILE not in text, f"unescaped provider string in {name}"
        assert "<script" not in text.lower(), f"script tag in {name}"


def test_screen_sample_orders_validated_first(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    screen = (out / "screen.html").read_text()
    # BBB (validated, newer) before AAA (validated, older); hostile unvalidated row last
    assert screen.index("$BBB") < screen.index("$AAA") < screen.index("&lt;script&gt;")


# -- absence handling ------------------------------------------------------------------


def test_absent_everything_renders_honest_sections(tmp_path):
    out = tmp_path / "out"
    manifest = generate(
        day=DAY,
        scores_dir=tmp_path / "missing-scores",
        archive_db=tmp_path / "missing.sqlite",
        wire_dir=tmp_path / "missing-wire",
        out_dir=out,
    )
    assert manifest["data_through"] is None
    html = _read_all(out)
    assert "no launches scored" in html["index.html"]
    assert "not present" in html["record.html"]
    assert "no wires published yet" in html["wire/index.html"]
    assert "no CLEAN admits" in html["screen.html"]
    for name, text in html.items():
        assert "None" not in text, f"a bare None leaked into {name}"
        assert "data through" not in text, f"{name} stamps an as-of with no data behind it"


def test_empty_leaderboard_is_a_stated_slot(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    record_page = (out / "record.html").read_text()
    assert "still in flight" in record_page  # one outcome row exists; min-n not met
    assert "measured caller leaderboard" in record_page.lower()


# -- no fake numbers: every static figure travels with its window ----------------------


def test_static_claims_always_carry_their_windows(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    corpus = "\n".join(_read_all(out).values())
    for key, (claim, _window) in pages_mod.STATIC_CLAIMS.items():
        # every appearance of the claim text is an appearance of the FULL cite fragment,
        # window included — a registered figure cannot be rendered bare
        assert corpus.count(pages_mod.esc(claim)) == corpus.count(pages_mod.cite(key)), (
            f"claim {key!r} appears somewhere without its window"
        )


def test_cite_binds_claim_and_window_in_one_fragment():
    fragment = pages_mod.cite("crowd")
    claim, window = pages_mod.STATIC_CLAIMS["crowd"]
    assert pages_mod.esc(claim) in fragment and pages_mod.esc(window) in fragment


def test_every_static_claim_is_used_somewhere(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    corpus = "\n".join(_read_all(out).values())
    unused = [k for k in pages_mod.STATIC_CLAIMS if pages_mod.cite(k) not in corpus]
    assert not unused, f"registry entries nothing renders: {unused}"


def test_research_and_screen_carry_survival_and_mayhem_sections(
    tmp_path, scores_dir, archive_db, wire_dir
):
    """The 2026-08-29 studies ship: verdict survival (CLEAN is not a buy signal),
    the mayhem mechanism + refusal to score, and crew-ledger persistence."""

    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    research = (out / "research.html").read_text()
    assert "safety and longevity order in opposite directions" in research
    assert "mayhem mode: the counterparty is the protocol" in research
    assert "4,756 SOL market cap" in research  # the case study, with its window via cite()
    assert "deliberately held" in research  # the CLEAN-vs-KNOWN-CREW hold is stated
    assert "the crew ledger&#x27;s memory holds" in research or "the crew ledger" in research
    screen = (out / "screen.html").read_text()
    assert "not a prediction of upside" in screen
    assert "safety and longevity point in opposite directions" in screen
    assert "mayhem launches are labeled, never scored" in screen
    assert "never a buy signal" in screen


# -- determinism -----------------------------------------------------------------------


def test_deterministic_output(tmp_path, scores_dir, archive_db, wire_dir):
    out1, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir, "out1")
    out2, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir, "out2")
    files1, files2 = _read_all(out1), _read_all(out2)
    assert files1.keys() == files2.keys()
    for name in files1:
        assert files1[name] == files2[name], f"{name} differs between identical runs"


# -- links -----------------------------------------------------------------------------

HREF = re.compile(r'href="([^"]+)"')
ALLOWED_ABS = ("https://pump.fun/coin/", "https://t.me/ltshitcoims_bot", "/sign")


def test_links_are_wellformed_and_expected(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    for name, text in _read_all(out).items():
        for href in HREF.findall(text):
            if href.startswith(("http", "/")):
                assert href.startswith(ALLOWED_ABS), f"unexpected external link {href} in {name}"
                if href.startswith("https://pump.fun/coin/"):
                    mint = href.removeprefix("https://pump.fun/coin/")
                    assert re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", mint), (name, href)
            else:
                target = (out / name).parent / href
                if href.endswith("/"):
                    target = target / "index.html"
                assert target.resolve().is_relative_to(out.resolve()), (name, href)
                assert target.exists(), f"dangling internal link {href} in {name}"


def test_sign_page_is_never_written(tmp_path, scores_dir, archive_db, wire_dir):
    out, _ = _generate(tmp_path, scores_dir, archive_db, wire_dir)
    assert not (out / "sign").exists()
    with pytest.raises(SystemExit):
        generate(
            day=DAY, scores_dir=scores_dir, archive_db=archive_db, wire_dir=wire_dir,
            out_dir=out / "sign",
        )


# -- mdlite ----------------------------------------------------------------------------


def test_mdlite_renders_the_wire_subset():
    html = md_render(
        "# T\n\n*lede*\n\n## S\n\n- **bold** item\n\n| a | b |\n|---|---|\n"
        "| [x](https://pump.fun/coin/abc) | `c` |\n\n---\n\nplain\n"
    )
    assert "<h1>T</h1>" in html and "<h2>S</h2>" in html
    assert "<em>lede</em>" in html and "<strong>bold</strong>" in html
    assert '<a href="https://pump.fun/coin/abc">x</a>' in html
    assert "<table>" in html and "<code>c</code>" in html and "<hr>" in html


def test_mdlite_escapes_hostile_text_and_rejects_non_http_links():
    html = md_render(f"para {HOSTILE} end\n\n[x](javascript:alert(1))\n")
    assert "<script" not in html
    assert "&lt;script&gt;" in html
    assert 'href="javascript' not in html
