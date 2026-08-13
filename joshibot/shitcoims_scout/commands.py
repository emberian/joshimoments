from __future__ import annotations

import re
from dataclasses import dataclass

from .local_api import Query

HELP = """🔭 shitcoims Scout

/desk — bags and YAML policy buttons (cannot sell). Delete rule removes YAML only.
/candidates — intelligence candidates (cannot sell)
/now — urgent intelligence and feed health
/x — latest X/Twitter observations
/xkol — latest X KOL posts
/health — intelligence daemon health
/mints — mints discovered from X URLs
/kols — watched X KOL accounts
/portfolio — current shitcoims portfolio
/positions — current positions
/inventory — current shitcoims inventory
/panic-preview — preview what a panic would attempt to sell (nothing is sold)
/risks — current protection and rug risks
/performance — desk performance and realized exits
/events — recent sentinel events
/trades — recent executed exits
/sources — intelligence source health
/wallet <address|label> — wallet dossier
/token <mint> — token dossier
/cashtag <TICKER> — cashtag dossier (label, not a mint)
/kol <handle> — KOL dossier
/why <signal-id> — evidence for a signal
/digest — latest intelligence digest

Scout can write local exit rules. Delete rule removes a YAML rule. Scout cannot sell, arm, panic, or sign."""

DENIED = {
    "buy",
    "sell",
    "swap",
    "panic",
    "arm",
    "disarm",
    "execute",
    "sign",
    "withdraw",
    "transfer",
    "liquidate",
    "live",
    "secret",
    "key",
}

NO_ARGUMENT = {
    "start": None,
    "help": None,
    "now": Query("intel", "/api/intelligence/feed", {"limit": "10"}, "🔭 Now", "now"),
    "x": Query(
        "intel",
        "/api/intelligence/feed",
        {"limit": "10", "source": "apify_x_kaitoeasyapi_v1"},
        "🐦 Latest X",
        "x",
    ),
    "xkol": Query(
        "intel",
        "/api/intelligence/feed",
        {"limit": "10", "kind": "x_kol_post"},
        "🐦 Latest X KOLs",
        "xkol",
    ),
    "health": Query("intel", "/api/health", {}, "🩺 Intelligence health", "health"),
    "mints": Query("intel", "/api/intelligence/watchlists", {}, "🪙 Discovered mints", "mints"),
    "kols": Query("intel", "/api/intelligence/watchlists", {}, "🐦 X KOL watches", "kols"),
    "watch": Query("intel", "/api/intelligence/watchlists", {}, "👁 Watchlists", "mints"),
    "portfolio": Query("sentinel", "/api/snapshot", {}, "💼 shitcoims portfolio", "portfolio"),
    "positions": Query("sentinel", "/api/snapshot", {}, "📍 shitcoims positions", "positions"),
    "inventory": Query("sentinel", "/api/snapshot", {}, "📦 shitcoims inventory", "inventory"),
    "panic-preview": Query(
        "sentinel", "/api/snapshot", {}, "⚠️ Panic preview", "panic_preview"
    ),
    "risks": Query("sentinel", "/api/snapshot", {}, "⚠️ Current risks", "risks"),
    "performance": Query(
        "sentinel", "/api/performance", {}, "📊 shitcoims performance", "performance"
    ),
    "events": Query(
        "sentinel", "/api/events", {"limit": "10"}, "📜 Recent events", "events"
    ),
    "trades": Query(
        "sentinel", "/api/trades", {"limit": "10"}, "🧾 Recent trades", "trades"
    ),
    "sources": Query("intel", "/api/intelligence/sources", {}, "📡 Source health", "sources"),
    "digest": Query("intel", "/api/intelligence/digests", {"limit": "1"}, "🗞 Intelligence digest", "digest"),
    "desk": None,
    "candidates": None,
}

ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
CASHTAG = re.compile(r"[A-Za-z][A-Za-z0-9]{1,11}\Z")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")
SIGNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
COMMAND = re.compile(r"/([a-z]+(?:-[a-z]+)*)(?: ([^\s]+))?\Z")


@dataclass(frozen=True)
class ParsedCommand:
    kind: str
    query: Query | None = None
    message: str | None = None


def parse_command(text: object) -> ParsedCommand:
    if not isinstance(text, str) or len(text) > 160 or "\n" in text or "\r" in text:
        return ParsedCommand("invalid", message="Use /help for Scout's read-only commands.")
    match = COMMAND.fullmatch(text)
    if match is None:
        return ParsedCommand("invalid", message="Use /help for Scout's read-only commands.")
    command, argument = match.groups()
    if command in DENIED:
        return ParsedCommand(
            "denied",
            message="⛔ Scout is read-only. Trade, execution, and configuration controls are rejected.",
        )
    if command in NO_ARGUMENT:
        if argument is not None:
            return ParsedCommand("invalid", message=f"/{command} does not accept an argument.")
        if command in {"start", "help"}:
            return ParsedCommand("help", message=HELP)
        if command in {"desk", "candidates"}:
            return ParsedCommand(command)
        return ParsedCommand("query", query=NO_ARGUMENT[command])
    if command == "wallet":
        if argument is None or not (ADDRESS.fullmatch(argument) or LABEL.fullmatch(argument)):
            return ParsedCommand("invalid", message="Usage: /wallet <address|label>")
        return ParsedCommand(
            "query",
            query=Query(
                "intel",
                f"/api/intelligence/dossiers/wallet/{argument}",
                {},
                "👛 Wallet dossier",
                "wallet",
                argument,
            ),
        )
    if command in {"token", "early"}:
        if argument is None or ADDRESS.fullmatch(argument) is None:
            return ParsedCommand("invalid", message=f"Usage: /{command} <mint>")
        return ParsedCommand(
            "query",
            query=Query(
                "intel",
                f"/api/intelligence/dossiers/token/{argument}",
                {},
                "🪙 Token dossier",
                "token",
                argument,
            ),
        )
    if command == "cashtag":
        if argument is None or CASHTAG.fullmatch(argument) is None:
            return ParsedCommand("invalid", message="Usage: /cashtag <TICKER>")
        return ParsedCommand(
            "query",
            query=Query(
                "intel",
                f"/api/intelligence/dossiers/cashtag/{argument.upper()}",
                {},
                f"🏷 ${argument.upper()} mentions",
                "cashtag",
                argument.upper(),
            ),
        )
    if command == "kol":
        handle = None if argument is None else argument.lstrip("@")
        if handle is None or HANDLE.fullmatch(handle) is None:
            return ParsedCommand("invalid", message="Usage: /kol <handle>")
        return ParsedCommand(
            "query",
            query=Query(
                "intel",
                f"/api/intelligence/dossiers/kol/{handle}",
                {},
                "🐦 KOL dossier",
                "kol",
                handle,
            ),
        )
    if command == "why":
        if argument is None or SIGNAL_ID.fullmatch(argument) is None:
            return ParsedCommand("invalid", message="Usage: /why <signal-id>")
        return ParsedCommand(
            "query",
            query=Query(
                "intel",
                f"/api/intelligence/items/{argument}",
                {},
                "🔎 Signal evidence",
                "why",
                argument,
            ),
        )
    return ParsedCommand("invalid", message="Unknown command. Use /help.")
