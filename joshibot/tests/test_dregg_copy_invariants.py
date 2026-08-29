"""Copy invariants across every Telegram-bound $DREGG surface.

The product promise is measured honesty in language a trader actually reads. These
tests hold the line from both ends:

* NO JARGON LEAKS — the scorer's machine reason codes, population-note codes, and the
  method vocabulary ("validated population", "operating point", "corpus", "Jaccard",
  raw enum glue) must never reach a Telegram surface. The markdown artifacts (wire,
  leaderboard) are the methodology record and are exempt.
* EVERY ERROR NAMES A NEXT STEP — a dead end must say what happened and hand the user
  a command or an explicit retry.
* PLAIN TEXT, ALWAYS — no HTML tags of ours, no entities, no parse_mode anywhere in a
  rendered string (the hard rule, learned in production).
* UNDER THE CAP — worst-case renders stay inside Telegram's 4096-char message limit.

Renders are built from hand-made rows in each producer's exact shape, so the tests
exercise the real renderers, not copies of their output.
"""

from __future__ import annotations

from dregg_dossier import cards
from dregg_dossier.lookup import (
    COIN_USAGE_TEXT,
    UNAVAILABLE_TEXT,
    WALLET_USAGE_TEXT,
)
from dregg_dossier.lookup import EJECTED_TEXT as DOSSIER_EJECTED
from dregg_dossier.lookup import rate_limited_text as dossier_rate_limited
from dregg_dossier.lookup import teaser_text as dossier_teaser
from dregg_gate import lookup as gate_lookup
from dregg_gate.gateway import HELP_TEXT, unknown_command_text
from dregg_gate.lookup import (
    EJECTED_TEXT,
    USAGE_TEXT,
    not_found_text,
    rate_limited_text,
    render_card,
    screen_down_text,
    start_text,
    teaser_text,
)
from dregg_record.leaderboard import render_text as render_board_text
from dregg_record.lookup import USAGE_TEXT as CALLER_USAGE
from dregg_record.lookup import (
    ambiguous_text,
)
from dregg_record.lookup import not_found_text as caller_not_found
from dregg_record.lookup import (
    render_card as render_caller_card,
)
from dregg_screen.digest import compose as compose_digest
from dregg_watch import matcher
from dregg_watch.commands import (
    BAD_CALLER_TEXT,
    BAD_CREW_TEXT,
    BAD_WALLET_TEXT,
    cap_text,
)
from dregg_watch.commands import (
    USAGE_TEXT as WATCH_USAGE,
)
from dregg_watch.state import Subscription
from dregg_wire.wire import compose_telegram

NOW = 1_787_000_000.0  # 2026-08-17-ish; only used for staleness arithmetic
MINT = "M1nt111111111111111111111111111111111111pump"
MINT_B = "M1nt222222222222222222222222222222222222pump"
WALLET = "Wa11et11111111111111111111111111111111111111"
DEPLOYER = "Dep1oyer111111111111111111111111111111111111"

# The blacklist: machine codes and method vocabulary that must never reach Telegram.
JARGON = (
    # raw scorer reason codes
    "dev_buy_share=",
    "crew_fingerprint:",
    "deployer_record:",
    "recidivist_sniper",
    "bundled_at_birth",
    "nonstandard_curve:",
    "not_hydrated",
    "cheap_gates_passed",
    "birth_slot_partial",
    "all_gates_passed",
    # raw population-note codes
    "vendor_flag",
    "mint_without_pump_suffix",
    "no_dev_buy:",
    "in_validated_population",
    # method vocabulary that belongs in the markdown artifacts, not the channel
    "validated population",
    "operating point",
    "seeded history",
    "method v1",
    "outcomes method",
    "unknown-absent",
    "priced legs",
    "batch layer",
    "corpus",
    "Jaccard",
    "wallet layer",
    "timing q=",
    "unvalidated",
)

MARKUP = ("<a ", "</a>", "<b>", "<code>", "<pre>", "&lt;", "&#", "parse_mode")


def assert_reads_plain(text: str, *, where: str) -> None:
    for token in JARGON:
        assert token not in text, f"jargon {token!r} leaked into {where}:\n{text}"
    for token in MARKUP:
        assert token not in text, f"markup {token!r} in {where} (plain text only):\n{text}"


# -- fixture rows in each producer's exact shape ---------------------------------------


def score_row(mint: str = MINT, **overrides) -> dict:
    row = {
        "mint": mint,
        "verdict": "CLEAN",
        "reasons": ["all_gates_passed"],
        "name": "test coin",
        "symbol": "TEST",
        "creator": DEPLOYER,
        "deployer": DEPLOYER,
        "hydrated": True,
        "in_validated_population": True,
        "population_notes": [],
        "features": {"dev_buy_share": 0.009, "dev_buy_source": "chain_exact", "n_snipers": 1},
        "crew_match": None,
        "deployer_history": {"launches": 2, "rips": 0, "dumps": 0, "grads": 1},
        "base_rates": {
            "validated_span": "2026-08-26..28 (seeded history, B1)",
            "is_rip": {"admit_rate": 0.085, "clean_precision": 0.995},
        },
        "t_scored": "2026-08-17T02:20:00.000000+00:00",
    }
    row.update(overrides)
    return row


def nasty_screen_rows() -> list[dict]:
    """Every reason code and population note the scorer can emit, in one batch."""

    return [
        score_row(),
        score_row(
            MINT_B,
            verdict="KNOWN_CREW",
            symbol="RUN",
            reasons=[
                "crew_fingerprint:#81422:jaccard=0.31:overlap=4",
                "deployer_record:launches=6,rips=2,dumps=1",
                "recidivist_sniper:prior_coins=3",
            ],
            in_validated_population=False,
            population_notes=["vendor_flag:is_mayhem_mode:curve_unverified"],
            crew_match={
                "crew_id": 81422, "jaccard": 0.31, "overlap": 4,
                "crew_coins": 9, "crew_rips": 3, "crew_dumps": 2, "dirty": True,
            },
            deployer_history={"launches": 6, "rips": 2, "dumps": 1, "grads": 0},
        ),
        score_row(
            "M1nt333333333333333333333333333333333333pump",
            verdict="UNSCORED",
            reasons=["nonstandard_curve:minted_raw=2000000000000000,decimals=6"],
            hydrated=True,
            in_validated_population=False,
            population_notes=["mint_without_pump_suffix", "no_dev_buy:outside_validated_population"],
        ),
        score_row(
            "M1nt444444444444444444444444444444444444pump",
            verdict="UNSCORED",
            reasons=["policy:mayhem_flag_nonstandard_curve", "cheap_gates_passed"],
            hydrated=False,
        ),
        score_row(
            "M1nt555555555555555555555555555555555555pump",
            verdict="UNSCORED",
            reasons=["birth_slot_partial"],
        ),
        score_row(
            "M1nt666666666666666666666666666666666666pump",
            verdict="NOT_CLEAN",
            reasons=["dev_buy_share=0.1249>= 0.02"],
            hydrated=False,
            features={"dev_buy_share": 0.1249, "dev_buy_source": "ws_vendor_float"},
        ),
        score_row(
            "M1nt777777777777777777777777777777777777pump",
            verdict="BUNDLED",
            reasons=["bundled_at_birth:n_snipers=4"],
            features={"dev_buy_share": 0.001, "dev_buy_source": "chain_exact", "n_snipers": 4},
        ),
    ]


DOSSIER_META = {
    "corpus_span": ["2026-07-15", "2026-08-14"],
    "updated_through": NOW - 3 * 86400,
    "n_wallets": 728_017,
    "guild_stats": {"FLASH": {"n": 1000, "median_net_sol": -0.4, "breakeven_preset_rate": 0.31}},
    "crowd": {"net_realized_sol_sum": -120_000.0, "frac_positive": 0.312},
    "comp_source": "holders",
    "crew_ledger": {"crews": 3},
}

DOSSIER_WALLET_ROW = {
    "owner": WALLET,
    "guild": "FLASH",
    "guild_cluster": "c17",
    "rp_mode": "BREAKEVEN_PRESET",
    "net_realized_sol": 1.5,
    "n_coins": 40,
    "n_legs": 200,
    "active_days": 9,
    "n_coins_closed": 5,
    "n_coins_win": 4,
    "median_realized_sol_closed": 0.02,
    "median_hold_s": 42.0,
    "p90_hold_s": 1200.0,
    "median_entry_latency_s": 8.0,
    "on_ladder": 1,
    "in_rotation": 1,
    "rotation_hours": 31,
    "rp_frac_breakeven": 0.44,
}

DOSSIER_COIN_VIEW = {
    "comp": {
        "n_traders": 40, "n_profiled": 30, "n_harvester": 10, "n_flash": 8,
        "n_slow": 6, "n_accumulator": 4, "n_aftermarket": 2,
        "n_breakeven_preset": 3, "n_in_rotation": 12, "n_on_ladder": 2,
        "n_net_positive": 9,
    },
    "crews": [
        {"crew_id": 7, "launched_by": 1, "dirty": 1, "n_overlap": None,
         "crew_coins": 12, "crew_rips": 2, "crew_dumps": 5},
        {"crew_id": 9, "launched_by": 0, "dirty": 0, "n_overlap": 3,
         "crew_coins": 4, "crew_rips": 0, "crew_dumps": 0},
    ],
    "exit": {"n_timing_pass": 1, "any_recent": 1, "n_distributors": 2},
    "icebergs": [
        {"owner": WALLET, "dist_sold_sol": 84.0, "n_dist_sells": 12,
         "duration_s": 7200.0, "drawdown": 0.8, "resilience": 0.1,
         "timing_q": 0.82, "last_dist_t": NOW - 86400},
    ],
}

CALLER_RECORD = {
    "wallet": WALLET,
    "identity": {"username": "AlphaWolf", "x_username": None,
                 "first_seen": "2026-07-20", "last_seen": "2026-08-15", "seen_note": None},
    "callouts": {"lifetime": 7, "window": 6, "window_days": 30, "undated": 1,
                 "distinct_mints": 5},
    "measured": {
        "n_with_outcomes": 6,
        "ret_1h": {"n": 6, "median": -0.1, "mean": -0.05},
        "ret_24h": {"n": 6, "median": -0.3, "mean": -0.2},
        "ret_7d": {"n": 4, "median": -0.5, "mean": -0.4},
        "hits_24h": {"n": 6, "above_0": 2, "above_50": 1},
        "drawdown": {"n": 3, "median": -0.9},
        "dead": {"n_final": 4, "n_dead": 2, "rate": 0.5},
    },
    "provider_claim": {"n": 5, "median_multiple": 3.0, "max_multiple": 130.0, "label": "x"},
    "removals": {"published_removed": 1, "published_unknown_absent": 1, "note": "x"},
    "wallet_layer": {"as_of": "2026-08-14", "stale": True, "note": "x",
                     "net_realized_sol": -12.5, "win_rate": 0.41,
                     "n_coins_closed": 17, "rp_mode": "LOSS_CUTTER", "guild": None},
}

CALLER_CALLS = [
    {"day": "2026-08-15", "mint": MINT, "ret_24h": -0.3, "ret_7d": None,
     "claimed_multiple": 130.0, "dead": False, "removal": "removed"},
    {"day": "2026-08-14", "mint": MINT_B, "ret_24h": None, "ret_7d": None,
     "claimed_multiple": None, "dead": None, "removal": "unknown-absent"},
]

BOARD = {
    "window_days": 30, "window_start": "2026-07-18", "window_end": "2026-08-17",
    "min_n": 5, "method_version": "v1",
    "coverage": {"n_callouts": 40, "n_callers": 9, "n_measured_24h": 22, "note": None},
    "rows": [{
        "rank": 1, "handle": "@AlphaWolf", "wallet": WALLET, "n_callouts": 7,
        "n_measured": 6, "median_ret_24h": -0.3, "mean_ret_24h": -0.2, "above_0": 2,
        "dead": {"n_final": 4, "n_dead": 2}, "removals_published": 1,
        "claim": {"n": 5, "median_multiple": 3.0},
    }],
    "rows_note": None, "excluded_thin": 3,
    "coins": [{"mint": MINT, "n_callouts": 3, "n_callers": 2,
               "measured_24h": {"n": 2, "median": -0.2}}],
    "coins_note": None,
    "gaps": [{"handle": "@AlphaWolf", "wallet": WALLET, "mint": MINT,
              "claimed_multiple": 130.0, "measured_close_multiple": 1.6,
              "ret_24h": -0.2, "gap_ratio": 81.25}],
    "gaps_note": None,
    "caller_color": {"as_of": "2026-08-14", "stale": True, "note": "x", "entries": [
        {"wallet": WALLET, "net_realized_sol": -12.5, "win_rate": 0.41,
         "n_coins_closed": 17, "rp_mode": "LOSS_CUTTER", "guild": None},
    ]},
}

WIRE_FACTS = {
    "day": "2026-08-17",
    "screen": {
        "source": "s",
        "launches_scored": 7,
        "verdicts": {"KNOWN_CREW": 3, "CLEAN": 2, "NOT_CLEAN": 1, "UNSCORED": 1},
        "validated": {
            "count": 4, "clean": 2, "clean_rate": 0.5,
            "operating_point": {"admit_rate": 0.085, "clean_precision": 0.995,
                                "validated_span": "2026-08-26..28 (seeded history, B1)"},
        },
        "mayhem": {"count": 2, "share": 2 / 7, "definition": "d"},
        "notable_cleans": [{
            "symbol": "AAA", "mint": MINT, "dev_buy_share": 0.004,
            "deployer_history": {"launches": 2, "rips": 0, "dumps": 0},
            "in_validated_population": False,
        }],
        "crews": [{"crew_id": 7, "launches_today": 2, "symbols": ["AAA", "BBB"],
                   "max_jaccard": 0.44, "crew_coins": 12, "crew_rips": 2, "crew_dumps": 5}],
        "crews_note": None,
    },
    "callouts": {
        "source": "s", "archived_today": 3, "distinct_callers_today": 2,
        "distinct_mints_today": 2, "board_total": 40, "board_callers": 9,
        "top_provider_claim": {"multiple": 292.7, "mint": MINT, "username": "AlphaWolf",
                               "thesis": "t", "label": "x"},
        "anti_signal": {"ret_1h_mean": -0.119, "ret_8h_mean": -0.436,
                        "burst_ret_8h_median": -0.647,
                        "burst_definition": "2+ callers within 10 minutes",
                        "source": "callout-edge study", "short_source": "callout-edge study, run 2026-08-15"},
        "top_callers": [{"wallet": WALLET, "username": "AlphaWolf", "callouts_today": 2}],
        "removals": {"today": 1, "total": 2, "note": None},
        "outcomes": {"rows": 40, "final": 12, "priced_1h": 22, "note": None},
    },
    "archive": {"source": "s", "fetches_today": 100, "zst_bytes_today": 200_000,
                "manifests_anchored": 3, "manifest_note": None},
    "caller_color": {"as_of": "2026-08-14", "stale": True, "note": "n", "entries": [
        {"wallet": WALLET, "net_realized_sol": -12.5, "win_rate": 0.41,
         "n_coins_closed": 17, "rp_mode": "LOSS_CUTTER", "guild": None},
    ]},
}


def all_telegram_surfaces() -> list[tuple[str, str]]:
    """(name, rendered text) for every Telegram-bound surface, worst-case inputs."""

    sub = Subscription(id=3, tg_user_id=7, kind="coin", spec=MINT, mode="event",
                       created_at=NOW - 86400)
    screen_event = matcher.event_from_score(nasty_screen_rows()[1])
    assert screen_event is not None
    surfaces = [
        ("start", start_text(888_888)),
        ("help", HELP_TEXT),
        ("screen teaser", teaser_text(888_888)),
        ("screen not-found", not_found_text(MINT)),
        ("screen down", screen_down_text(MINT)),
        ("screen rate-limited", rate_limited_text(10)),
        ("digest", compose_digest(nasty_screen_rows(), 60.0) or ""),
        ("wallet card", cards.wallet_card(DOSSIER_WALLET_ROW, DOSSIER_META, NOW)),
        ("wallet miss", cards.wallet_miss(WALLET, DOSSIER_META, NOW)),
        ("coin card", cards.coin_card(MINT, DOSSIER_COIN_VIEW, DOSSIER_META, NOW)),
        ("coin miss", cards.coin_miss(MINT, DOSSIER_META, NOW)),
        ("dossier teaser", dossier_teaser(888_888)),
        ("caller card", render_caller_card(CALLER_RECORD, CALLER_CALLS)),
        ("caller not-found", caller_not_found("nobody")),
        ("caller ambiguous", ambiguous_text("name", [WALLET, DEPLOYER])),
        ("leaderboard", render_board_text(BOARD)),
        ("wire", compose_telegram(WIRE_FACTS, 3)),
        ("watch usage", WATCH_USAGE),
        ("watch dm", matcher.render_dm(sub, screen_event)),
        ("watch digest", matcher.render_digest([(3, screen_event.compact)] * 4,
                                               window_min=30, max_lines=3)),
    ]
    surfaces += [(f"screen card {row['verdict']}", render_card(row))
                 for row in nasty_screen_rows()]
    return surfaces


# -- the invariants --------------------------------------------------------------------


def test_no_jargon_or_markup_reaches_any_telegram_surface():
    for name, text in all_telegram_surfaces():
        assert text, f"surface {name} rendered empty"
        assert_reads_plain(text, where=name)


def test_every_surface_fits_telegram_cap():
    for name, text in all_telegram_surfaces():
        assert len(text) <= 4096, f"surface {name} is {len(text)} chars (cap 4096)"


def test_every_error_and_refusal_names_a_next_step():
    """A dead end must hand the user a command or an explicit retry."""

    errors = [
        USAGE_TEXT, EJECTED_TEXT, not_found_text(MINT), screen_down_text(MINT),
        rate_limited_text(10), teaser_text(888_888),
        WALLET_USAGE_TEXT, COIN_USAGE_TEXT, UNAVAILABLE_TEXT, DOSSIER_EJECTED,
        dossier_rate_limited(6), dossier_teaser(888_888),
        CALLER_USAGE, caller_not_found("x"), ambiguous_text("x", [WALLET]),
        BAD_WALLET_TEXT, BAD_CREW_TEXT, BAD_CALLER_TEXT, cap_text(25),
        unknown_command_text("/nope"),
        cards.wallet_miss(WALLET, DOSSIER_META, NOW),
        cards.coin_miss(MINT, DOSSIER_META, NOW),
    ]
    for text in errors:
        has_command = "/" in text
        has_retry = "again" in text.lower() or "try" in text.lower() or "poke" in text.lower()
        assert has_command or has_retry, f"error copy offers no next step:\n{text}"


def test_unknown_command_suggests_the_closest_real_one():
    assert "did you mean /screen?" in unknown_command_text("/screne")
    assert "did you mean /verify?" in unknown_command_text("/verfy")
    assert "did you mean /watch?" in unknown_command_text("/wach")
    fallback = unknown_command_text("/xyzzy")
    assert "/help" in fallback and "did you mean" not in fallback
    # a hostile 4000-char "command" is clamped, not echoed whole
    assert len(unknown_command_text("/" + "a" * 4000)) < 200


def test_screen_card_translates_every_reason_code():
    """Belt for the translator itself: no code path returns machine text."""

    for row in nasty_screen_rows():
        card = render_card(row)
        for reason in row["reasons"]:
            assert reason not in card
        for note in row["population_notes"]:
            assert note not in card
        assert "Scores rank risk; they do not establish intent." in card
        # the next-step block is always present, with real copyable values
        assert f"/watch coin {row['mint']}" in card
        assert f"/coin {row['mint']}" in card


def test_digest_reads_like_a_desk_note():
    rows = nasty_screen_rows()
    # collide two CLEAN tickers so disambiguation must kick in
    rows.append(score_row(MINT_B, symbol="TEST"))
    text = compose_digest(rows, 60.0)
    assert text is not None
    # 1. full links, never truncated mints
    assert f"https://pump.fun/coin/{MINT}" in text
    assert "…pump" not in text  # no truncated, uncopyable mint labels
    # 2. each admit carries the numbers that made it clean
    assert "dev buy 0.90%" in text
    assert "deployer launched 2 before, no rips or dumps on record, 1 graduated" in text
    # 3. enum names carry their meaning, hyphenated
    assert "KNOWN-CREW 1 — birth-slot wallets or deployer match a tracked crew record" in text
    assert "NOT-CLEAN 1 — dev's own buy over the 2% line" in text
    assert "UNSCORED 3 — couldn't be fully read, so no verdict" in text
    # 5. colliding tickers stay tellable apart
    assert "$TEST·M1nt" in text
    # 6. the window's pass rate is measured against the stamped long-run rate
    assert "vs the screen's long-run 8.5% (measured 2026-08-26..28)" in text
    # 7. affordances: the full card and the honesty line
    assert "DM me /screen <mint> for any launch's full card." in text
    assert text.endswith("Scores rank risk; they do not establish intent.")


def test_digest_overflow_states_the_cut_and_points_at_watch_clean():
    rows = [score_row(f"M1nt{n:03d}5555555555555555555555555555555pump", symbol=f"C{n}")
            for n in range(25)]
    text = compose_digest(rows, 60.0)
    assert text is not None
    assert "…and 15 earlier this window (newest shown). /watch clean DMs you every one." in text
    assert len(text) <= 4096


def test_digest_without_baseline_says_so_plainly():
    rows = [score_row(base_rates={})]
    text = compose_digest(rows, 60.0)
    assert text is not None
    assert "no long-run baseline was stamped in this window's scores" in text
    rows = [score_row(in_validated_population=False, population_notes=["mint_without_pump_suffix"])]
    text = compose_digest(rows, 60.0)
    assert text is not None
    assert "None of these launches were the standard type" in text


def test_screen_lookup_docstring_matches_reality():
    """The module docs promised HTML once; the code is plain text. Keep them honest."""

    assert "PLAIN TEXT" in (gate_lookup.__doc__ or "")
    assert "HTML" not in (gate_lookup.__doc__ or "")
