from __future__ import annotations

import pytest

from shitcoims_scout.commands import DENIED, HELP, parse_command
from shitcoims_scout.local_api import render_payload


@pytest.mark.parametrize("command", sorted(DENIED))
def test_control_and_trade_commands_are_explicitly_denied(command: str) -> None:
    parsed = parse_command(f"/{command}")
    assert parsed.kind == "denied"
    assert "read-only" in (parsed.message or "")


@pytest.mark.parametrize(
    "command",
    [
        "/now please",
        "/Now",
        "/help@some_bot",
        "/wallet ../../secret",
        "/token not-a-mint",
        "/why a b",
        "/now\n/sell",
        "hello",
    ],
)
def test_command_grammar_is_strict(command: str) -> None:
    assert parse_command(command).kind == "invalid"


def test_fixed_command_routes_cannot_select_arbitrary_url() -> None:
    parsed = parse_command("/wallet claudekol")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "intel"
    assert parsed.query.path == "/api/intelligence/dossiers/wallet/claudekol"
    assert parsed.query.params == {}

    parsed = parse_command("/portfolio")
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/snapshot"

    desk = parse_command("/desk")
    assert desk.kind == "desk"
    assert desk.query is None
    assert "/desk" in HELP
    assert "/candidates" in HELP
    assert "Delete rule" in HELP

    candidates = parse_command("/candidates")
    assert candidates.kind == "candidates"
    assert candidates.query is None
    assert parse_command("/candidates extra").kind == "invalid"
    assert parse_command("/panic").kind == "denied"


def test_x_and_cashtag_routes_are_fixed_and_read_only() -> None:
    parsed = parse_command("/x")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.path == "/api/intelligence/feed"
    assert parsed.query.params["source"] == "apify_x_kaitoeasyapi_v1"

    parsed = parse_command("/cashtag bonk")
    assert parsed.query is not None
    assert parsed.query.path == "/api/intelligence/dossiers/cashtag/BONK"
    assert parsed.query.action == "cashtag"

    parsed = parse_command("/health")
    assert parsed.query is not None
    assert parsed.query.path == "/api/health"

    parsed = parse_command("/early So11111111111111111111111111111111111111112")
    assert parsed.query is not None
    assert parsed.query.path.endswith("/token/So11111111111111111111111111111111111111112")


def test_kol_follow_commands_are_read_only_fixed_routes() -> None:
    parsed = parse_command("/kols")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "intel"
    assert parsed.query.path == "/api/intelligence/watchlists"
    assert parsed.query.params == {}
    assert parsed.query.action == "kols"

    parsed = parse_command("/kol blknoiz06")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.path == "/api/intelligence/dossiers/kol/blknoiz06"
    assert parsed.query.params == {}
    assert parsed.query.action == "kol"
    assert parsed.query.argument == "blknoiz06"

    parsed = parse_command("/kol @BlkNoiz06")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.path == "/api/intelligence/dossiers/kol/BlkNoiz06"
    assert parsed.query.argument == "BlkNoiz06"

    parsed = parse_command("/kol @bad!")
    assert parsed.kind == "invalid"
    assert parsed.query is None

    parsed = parse_command("/xkol")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.path == "/api/intelligence/feed"
    assert parsed.query.params == {"limit": "10", "kind": "x_kol_post"}
    assert parsed.query.action == "xkol"

    parsed = parse_command("/buy")
    assert parsed.kind == "denied"
    assert parsed.query is None
    assert "read-only" in (parsed.message or "")

    assert "/kols" in HELP
    assert "/kol <handle>" in HELP
    assert "/xkol" in HELP


def test_kols_renderer_lists_x_kol_watchlist_row_when_only_member_count() -> None:
    text = render_payload(
        "🐦 X KOL watches",
        {
            "items": [
                {"id": "x-discovered-mints", "name": "X discovered mints", "member_count": 12},
                {
                    "id": "x-kols",
                    "name": "X KOL watches",
                    "description": "Configured X accounts. Posts are claims, not fills.",
                    "member_count": 3,
                    "member_types": {"kol": 3},
                },
            ]
        },
        action="kols",
    )
    assert "X KOL watches: 3 members" in text
    assert "kol 3" in text
    assert "X discovered mints" not in text


def test_kol_reuses_dossier_renderer_and_xkol_reuses_feed_renderer() -> None:
    dossier = render_payload(
        "🐦 KOL dossier",
        {"dossier": {"id": "blknoiz06", "summary": "Watched KOL", "confidence": 0.8}},
        action="kol",
    )
    assert "blknoiz06" in dossier
    assert "Watched KOL" in dossier
    assert "Confidence: 0.8" in dossier

    feed = render_payload(
        "🐦 Latest X KOLs",
        {"items": [{"kind": "x_kol_post", "subject_id": "blknoiz06", "severity": "info"}]},
        action="xkol",
    )
    assert "x_kol_post: blknoiz06" in feed

    empty = render_payload("🐦 Latest X KOLs", {"items": []}, action="xkol")
    assert "No X KOL posts" in empty


SNAPSHOT = {
    "system": {
        "mode": "dry-run",
        "protection_state": "DRY_RUN",
        "gate_failures": [
            "execution.enabled is false",
            "process was not started with --live",
            "shitcoims live arm file is absent or does not match this wallet",
        ],
    },
    "wallet": {"sol": "1.5", "portfolio_exit_sol": "0.42"},
    "positions": [
        {
            "name": "BONK",
            "ui_amount": "1000",
            "exit_sol": "0.30",
            "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        },
        {
            "name": "EMPTY",
            "ui_amount": "0",
            "exit_sol": None,
            "mint": "11111111111111111111111111111111",
        },
    ],
    "unmonitored": [
        {
            "name": "WIF",
            "ui_amount": "12.5",
            "exit_sol": "0.12",
            "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        },
    ],
}


def test_inventory_is_a_fixed_read_only_snapshot_route() -> None:
    parsed = parse_command("/inventory")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/snapshot"
    assert parsed.query.params == {}
    assert parsed.query.action == "inventory"
    assert parse_command("/inventory extra").kind == "invalid"
    assert "/inventory" in HELP

    text = render_payload("📦 shitcoims inventory", SNAPSHOT, action="inventory")
    assert "SOL: 1.5" in text
    assert "Quoted token exit: 0.42 SOL" in text
    assert "• BONK: 1000 tokens → 0.30 SOL" in text
    assert "• EMPTY: 0 tokens → ? SOL" in text
    assert "• WIF: 12.5 tokens → 0.12 SOL" in text
    assert "Count: 3" in text


def test_panic_preview_is_read_only_and_panic_stays_denied() -> None:
    parsed = parse_command("/panic-preview")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/snapshot"
    assert parsed.query.params == {}
    assert parsed.query.action == "panic_preview"
    assert parse_command("/panic-preview extra").kind == "invalid"

    denied = parse_command("/panic")
    assert denied.kind == "denied"
    assert denied.query is None
    assert "read-only" in (denied.message or "")
    assert parse_command("/buy").kind == "denied"
    assert parse_command("/sell").kind == "denied"
    assert "panic" in DENIED
    assert "panic-preview" not in DENIED
    assert "/panic-preview" in HELP

    text = render_payload("⚠️ Panic preview", SNAPSHOT, action="panic_preview")
    assert text.startswith("⚠️ Panic preview\n\nTHIS IS A PREVIEW. NOTHING WAS SOLD.")
    assert "A panic would attempt to sell:" in text
    assert "• BONK: 1000 tokens → 0.30 SOL" in text
    assert "• WIF: 12.5 tokens → 0.12 SOL" in text
    assert "EMPTY" not in text
    assert "Quoted exit if those sells filled: 0.42 SOL" in text
    assert "execution.enabled is false" in text
    assert "process was not started with --live" in text
    assert "shitcoims live arm file is absent or does not match this wallet" in text
    remainder = text.replace("THIS IS A PREVIEW. NOTHING WAS SOLD.", "")
    assert "SOLD" not in remainder
    assert "sold" not in remainder

    closed = render_payload(
        "⚠️ Panic preview",
        {**SNAPSHOT, "system": {**SNAPSHOT["system"], "gate_failures": []}},
        action="panic_preview",
    )
    assert "all gates closed" in closed
    assert "THIS IS A PREVIEW. NOTHING WAS SOLD." in closed


PERFORMANCE = {
    "native_sol": "1.5",
    "portfolio_exit_sol": "0.42",
    "realized_sol": "0.12",
    "trade_count": 2,
    "protected_positions": 2,
    "observe_only": 1,
    "event_counts": {"info": 4, "warning": 1},
    "last_exit_at": "2026-08-12T12:00:00Z",
    "mode": "dry-run",
    "protection_state": "DRY_RUN",
}

EVENTS = {
    "items": [
        {
            "timestamp": "2026-08-12T12:00:00Z",
            "severity": "warning",
            "category": "rug",
            "message": "liquidity drop on BONK",
        },
        {
            "timestamp": "2026-08-12T11:59:00Z",
            "severity": "info",
            "category": "cycle",
            "message": "snapshot complete",
        },
    ]
}

TRADES = {
    "items": [
        {
            "timestamp": "2026-08-12T12:00:00Z",
            "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
            "name": "BONK",
            "reason": "stop_loss",
            "output_lamports": "300000000",
            "signature": "5sigBONK",
        },
        {
            "timestamp": "2026-08-12T11:00:00Z",
            "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
            "name": "WIF",
            "reason": "take_profit",
            "output_lamports": "120000000",
            "signature": "5sigWIF",
        },
    ]
}


def test_history_routes_are_fixed_read_only_and_panic_stays_denied() -> None:
    parsed = parse_command("/performance")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/performance"
    assert parsed.query.params == {}
    assert parsed.query.action == "performance"
    assert parse_command("/performance extra").kind == "invalid"

    parsed = parse_command("/events")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/events"
    assert parsed.query.params == {"limit": "10"}
    assert parsed.query.action == "events"
    assert parse_command("/events extra").kind == "invalid"

    parsed = parse_command("/trades")
    assert parsed.kind == "query"
    assert parsed.query is not None
    assert parsed.query.source == "sentinel"
    assert parsed.query.path == "/api/trades"
    assert parsed.query.params == {"limit": "10"}
    assert parsed.query.action == "trades"
    assert parse_command("/trades extra").kind == "invalid"

    denied = parse_command("/panic")
    assert denied.kind == "denied"
    assert denied.query is None
    assert "read-only" in (denied.message or "")
    assert parse_command("/buy").kind == "denied"
    assert parse_command("/sell").kind == "denied"
    assert "panic" in DENIED
    assert "performance" not in DENIED
    assert "events" not in DENIED
    assert "trades" not in DENIED
    assert "/performance" in HELP
    assert "/events" in HELP
    assert "/trades" in HELP

    text = render_payload("📊 shitcoims performance", PERFORMANCE, action="performance")
    assert "SOL: 1.5" in text
    assert "Token exit value: 0.42 SOL" in text
    assert "Realized: 0.12 SOL" in text
    assert "Trades: 2" in text
    assert "Protected: 2" in text
    assert "Observe-only: 1" in text
    assert "Last exit: 2026-08-12T12:00:00Z" in text
    assert "Mode: dry-run / DRY_RUN" in text
    assert "info 4" in text
    assert "warning 1" in text

    unsafe = render_payload(
        "📊 shitcoims performance",
        {
            **PERFORMANCE,
            "native_sol": {"nested": True},
            "event_counts": {"info": True, "ok": 3},
            "last_exit_at": None,
        },
        action="performance",
    )
    assert "SOL: unknown" in unsafe
    assert "ok 3" in unsafe
    assert "info True" not in unsafe
    assert "Last exit: never" in unsafe

    events = render_payload("📜 Recent events", EVENTS, action="events")
    assert "[WARNING] rug: liquidity drop on BONK (2026-08-12T12:00:00Z)" in events
    assert "[INFO] cycle: snapshot complete" in events

    empty_events = render_payload("📜 Recent events", {"items": []}, action="events")
    assert "No events recorded." in empty_events

    trades = render_payload("🧾 Recent trades", TRADES, action="trades")
    assert "• BONK: stop_loss → 300000000 lamports" in trades
    assert "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263" in trades
    assert "5sigBONK" in trades
    assert "• WIF: take_profit → 120000000 lamports" in trades

    empty_trades = render_payload("🧾 Recent trades", {"items": []}, action="trades")
    assert "No trades recorded." in empty_trades

    unsafe_trades = render_payload(
        "🧾 Recent trades",
        {
            "items": [
                {
                    "timestamp": {"bad": True},
                    "mint": True,
                    "name": "BONK",
                    "reason": ["nested"],
                    "output_lamports": {"amt": 1},
                    "signature": None,
                }
            ]
        },
        action="trades",
    )
    assert "• BONK: exit → ? lamports" in unsafe_trades
    assert "True" not in unsafe_trades
