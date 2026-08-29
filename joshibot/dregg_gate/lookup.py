"""On-demand launch-screen lookups: /screen <mint>, plus the /start front-door copy.

The live screen (dregg_screen.live) scores every pump.fun launch within seconds and
appends one JSON row per launch to ``<scores dir>/<utc-day>.jsonl``. This module is
the BOT side of that artifact: a verified member DMs ``/screen <mint>`` and gets the
launch's verdict card back. Design points:

* GATED — the card is a holder perk. Unverified users get an honest teaser (one
  redacted sample line), never data. Ejected members are pointed back at /verify.
* RATE-LIMITED per user (config ``gate.screen_rate_per_minute``, default 10/min)
  so nobody scripts the DM lane into a free screening API.
* TWO-DAY WINDOW — today's and yesterday's score files are searched, newest score
  wins; anything older gets an honest "not seen" naming the screen's go-live date
  (2026-08-29) rather than a shrug.
* READ-ONLY over the score files; the screen service owns all writes. Lines are
  substring-prefiltered before JSON parsing, so a lookup is one streaming pass and
  a torn tail line (mid-append) is skipped, not fatal.
* PLAIN TEXT ONLY — no parse_mode, ever. Bare pump.fun URLs auto-link, and plain
  text keeps provider-derived strings (symbol, name) literal-inert; the mint is only
  used after it parses as a base58 pubkey. The scorer's machine reason codes are
  translated to plain language at render time (never shown raw), with the honesty
  intact: same facts, readable words.

The gateway wires this in as one line per command; the copy and logic live here so
the gateway diff stays minimal (a concurrent deputy owns the challenge/help copy
there).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Config
from .state import GateState
from .verify import parse_pubkey

SCREEN_LIVE_DATE = "2026-08-29"  # first UTC day the live screen wrote score files
RATE_WINDOW_SECONDS = 60.0
PUMP_COIN_URL = "https://pump.fun/coin/{mint}"

_BADGE = {
    "CLEAN": "🟢",
    "KNOWN_CREW": "🔴",
    "BUNDLED": "🟠",
    "NOT_CLEAN": "🟠",
    "UNSCORED": "⚪",
}

FOOTER = "Scores rank risk; they do not establish intent."


# -- copy (front door + /screen's plain-text branches) --------------------------------


def start_text(threshold_tokens: int) -> str:
    """The cold-DM front door: what this is, what you get, how in, and the one rule."""

    return (
        "This is the dregg wire: measured pump.fun intelligence for $DREGG holders.\n\n"
        "Inside the holders group:\n"
        "• hourly launch-screen digests — every new launch scored for bundles, dev "
        "buys, and known crews\n"
        "• the daily wire — the day's tape, with numbers attached\n"
        "• caller records — who called what, and how it actually went\n"
        "Plus, right here in DM: /screen <mint> pulls the screen's verdict on any "
        "recent launch.\n\n"
        f"To join: hold {threshold_tokens:,} $DREGG, then send /verify <your wallet "
        "address>. I reply with a short text message; sign it with your wallet's "
        "signMessage and paste the signature back. That's the whole flow.\n\n"
        "🛡 One rule that never bends: I will NEVER ask you to sign a transaction, "
        "connect your wallet to a site, or send funds anywhere. Verification is "
        "signing a plain text message — nothing else. Anyone asking for more is a "
        "phisher, not this bot.\n\n"
        "/help lists every command."
    )


def teaser_text(threshold_tokens: int) -> str:
    """What an unverified user sees instead of a card: the shape, not the data."""

    return (
        "/screen is a holder perk — verify to unlock.\n\n"
        "Verified members can pull the screen's verdict card for any recent pump.fun "
        "launch. A taste of what they see:\n\n"
        "CLEAN $░░░░ ░░░░░░░░…pump — no bundle (1 birth-slot buyer), dev buy 0.░░%, "
        "deployer record ░ launches / 0 rips / 0 dumps, no crew overlap.\n\n"
        f"Hold {threshold_tokens:,} $DREGG and send /verify <wallet> to get in."
    )


EJECTED_TEXT = (
    "Your seat lapsed (the wallet dropped below the gate), so /screen is locked. "
    "/verify <wallet> again to restore it."
)

USAGE_TEXT = (
    "Usage: /screen <mint> — paste the launch's mint address "
    "(32-44 base58 characters, usually ending in \"pump\")."
)


def rate_limited_text(per_minute: int) -> str:
    return (
        f"Easy — /screen is capped at {per_minute} lookups a minute per member, so "
        "the bot stays a bot and not an API. Try again in a moment."
    )


def not_found_text(mint: str) -> str:
    """Honest miss (plain text), with the coin's pump.fun link anyway."""

    url = PUMP_COIN_URL.format(mint=mint)
    return (
        f"No screen record for {mint} ({url}) in the last two days.\n\n"
        f"I keep today's and yesterday's scores on tap; the screen went live "
        f"{SCREEN_LIVE_DATE}, so nothing before that exists. If this launch is "
        "seconds old, give it a beat and ask again — every new launch is scored "
        "moments after its create event."
    )


def screen_down_text(mint: str) -> str:
    """Neither day file exists: the screen itself is unreachable — say so, don't
    imply the launch was never scored."""

    return (
        f"I can't reach the screen's score files right now, so I can't say whether "
        f"{mint} was scored — that's a problem on our side, not something you did. "
        "Try /screen again in a few minutes."
    )


# -- score-file lookup ----------------------------------------------------------------


def score_days(now: float) -> tuple[str, str]:
    """Yesterday and today, UTC — the two files a lookup may touch."""

    today = datetime.fromtimestamp(now, tz=UTC).date()
    return ((today - timedelta(days=1)).isoformat(), today.isoformat())


def find_score(scores_dir: Path, mint: str, now: float) -> dict[str, Any] | None:
    """Latest score row for ``mint`` across yesterday's and today's files, or None.

    A launch is scored once, but a re-run (backfill, operator replay) may append a
    newer row for the same mint — the LAST one found is the current verdict.
    """

    found: dict[str, Any] | None = None
    for day in score_days(now):
        path = scores_dir / f"{day}.jsonl"
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if mint not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # torn tail line mid-append; the next flush completes it
                    if isinstance(row, dict) and row.get("mint") == mint:
                        found = row
        except OSError:
            continue  # that day's file absent (screen down, or the day just rolled)
    return found


# -- the verdict card (plain text) ----------------------------------------------------


def _plain_reason(reason: str) -> str | None:
    """One scorer reason code -> one plain-language clause; None drops the code.

    The codes are the scorer's mechanism trail (dregg_screen.score); the card owes the
    user the same fact in words. Anything unrecognized is de-coded generically rather
    than leaked raw — a new code must never surface as machine text.
    """

    if reason == "all_gates_passed":
        return None  # the CLEAN card's measured lines already say it
    if reason.startswith("dev_buy_share="):
        return "the dev's own buy is over the 2% line"
    if reason.startswith("crew_fingerprint:"):
        return "its birth-slot buyers match a known crew's fingerprint"
    if reason.startswith("deployer_record:"):
        return "this deployer's earlier launches include rips or insider dumps"
    if reason.startswith("recidivist_sniper:"):
        prior = reason.rsplit("=", 1)[-1]
        n = prior if prior.isdigit() else "multiple"
        return f"a birth-slot buyer here was in the birth slot of {n} earlier launches"
    if reason.startswith("bundled_at_birth:"):
        return "multiple wallets bought in the very slot the coin was born"
    if reason.startswith("nonstandard_curve:"):
        return "it minted a nonstandard bonding curve, which this screen was not built to score"
    if reason == "not_hydrated":
        return "the birth slot couldn't be read in time"
    if reason == "cheap_gates_passed":
        return "every check that could still run passed"
    if reason == "birth_slot_partial":
        return "only part of the birth slot could be read, and a partial read can hide a bundle"
    if reason.startswith("policy:") or reason.startswith("budget:"):
        return "the screen chose not to spend a full birth-slot read on this launch"
    # Unknown code: humanize, never leak machine syntax.
    return reason.split(":", 1)[0].split("=", 1)[0].replace("_", " ")


_PLAIN_POPULATION_NOTE = {
    "mint_without_pump_suffix": "its mint address doesn't end in \"pump\"",
}


def _plain_population_note(note: str) -> str:
    if note.startswith("vendor_flag:is_mayhem_mode"):
        return "it launched in pump's mayhem mode"
    if note.startswith("no_dev_buy"):
        return "it launched with no dev buy at all"
    return _PLAIN_POPULATION_NOTE.get(note, note.split(":", 1)[0].replace("_", " "))


def render_card(row: dict[str, Any]) -> str:
    """One launch, one plain-text card. Links the pump.fun page; ends on the honesty
    footer, with a next-step line just above it."""

    verdict = str(row.get("verdict") or "UNSCORED")
    features = row.get("features") or {}
    hydrated = bool(row.get("hydrated"))
    mint = str(row.get("mint") or "")
    
    symbol = str(row.get("symbol") or "").strip()
    name = str(row.get("name") or "").strip()
    title = f"${symbol.lstrip('$')}" if symbol else (mint[:8] or "?")
    if name and name != symbol:
        title += f" — {name}"
    url = PUMP_COIN_URL.format(mint=mint)
    head = f"{_BADGE.get(verdict, '⚪')} {verdict.replace('_', '-')} · {title}"
    lines = [head, url, mint, ""]

    reasons = [str(reason) for reason in row.get("reasons") or []]
    share = features.get("dev_buy_share")
    if isinstance(share, (int, float)):
        exact = features.get("dev_buy_source") == "chain_exact"
        source = "chain-exact" if exact else "vendor estimate"
        if any(reason.startswith("nonstandard_curve") for reason in reasons):
            # The share's denominator assumes the standard 1e15 curve; this launch
            # minted something else, so the number is a ratio, not a supply share.
            source += "; assumes the standard curve, and this launch's curve is NOT standard"
        lines.append(f"Dev buy: {100 * share:.2f}% of supply ({source}; gate is <2%)")

    n_snipers = features.get("n_snipers")
    if hydrated and isinstance(n_snipers, int):
        if n_snipers >= 2:
            lines.append(f"Bundle: YES — {n_snipers} buyers in the birth slot")
        else:
            plural = "s" if n_snipers != 1 else ""
            lines.append(f"Bundle: none seen ({n_snipers} birth-slot buyer{plural})")
    else:
        lines.append("Bundle: unknown — birth slot not read")

    history = row.get("deployer_history") or {}
    record = (
        f"Deployer record: {history.get('launches', 0)} launches / "
        f"{history.get('rips', 0)} rips / {history.get('dumps', 0)} dumps"
    )
    if history.get("grads"):
        record += f" / {history['grads']} graduations"
    lines.append(record)

    crew = row.get("crew_match")
    if isinstance(crew, dict):
        lines.append(
            f"Crew: matched fingerprint #{crew.get('crew_id')} — "
            f"{crew.get('overlap')} shared birth-slot wallets, overlap {crew.get('jaccard')} "
            f"of 1 (that crew's {crew.get('crew_coins')} tracked coins carry "
            f"{crew.get('crew_rips')} rips / {crew.get('crew_dumps')} insider dumps)"
        )
    elif hydrated:
        lines.append("Crew: no fingerprint match")

    why = [text for text in (_plain_reason(str(r)) for r in reasons) if text]
    if why:
        lines.append("Why this verdict: " + "; ".join(why) + ".")

    scored_at = str(row.get("t_scored") or "")
    if len(scored_at) >= 16:
        lines.append(f"Scored: {scored_at[:16].replace('T', ' ')} UTC")

    lines.append("")
    if not row.get("in_validated_population", True):
        notes = "; ".join(
            _plain_population_note(str(note)) for note in row.get("population_notes") or []
        )
        lines.append(
            f"⚠️ Unusual launch type ({notes or 'an unflagged shape'}) — the screen's "
            "accuracy was measured on standard launches, and this isn't one. The verdict "
            "stands, but its measured hit rate doesn't carry over."
        )
    next_steps = f"Next: /coin {mint} — who's in it · /watch coin {mint} — DM alerts"
    deployer = row.get("deployer") or row.get("creator")
    if isinstance(deployer, str) and deployer:
        next_steps += f"\nTheir next launch: /watch deployer {deployer}"
    lines.append(next_steps)
    lines.append(FOOTER)
    return "\n".join(lines)


# -- the handler ----------------------------------------------------------------------


class ScreenLookup:
    """/screen state: per-user rate window. Config comes through a getter so the
    service's keep-last-good reload reaches lookups without extra wiring."""

    def __init__(
        self,
        config_getter: Callable[[], Config],
        state: GateState,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self._config = config_getter
        self.state = state
        self.clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def _admit(self, uid: int, per_minute: int) -> bool:
        now = self.clock()
        hits = self._hits[uid]
        while hits and now - hits[0] >= RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= per_minute:
            return False
        hits.append(now)
        return True

    def reply(self, uid: int, arg: str | None) -> tuple[str, str | None]:
        """The full /screen decision: (reply text, parse_mode or None)."""

        cfg = self._config()
        member = self.state.member(uid)
        if member is None:
            return teaser_text(cfg.threshold_tokens), None
        if member.status == "ejected":
            return EJECTED_TEXT, None
        if not self._admit(uid, cfg.screen_rate_per_minute):
            return rate_limited_text(cfg.screen_rate_per_minute), None
        if arg is None or parse_pubkey(arg) is None:
            return USAGE_TEXT, None
        now = self.clock()
        row = find_score(cfg.screen_scores_dir, arg, now)
        if row is None:
            days_present = any(
                (cfg.screen_scores_dir / f"{day}.jsonl").exists() for day in score_days(now)
            )
            if not days_present:
                return screen_down_text(arg), None
            return not_found_text(arg), None
        return render_card(row), None
