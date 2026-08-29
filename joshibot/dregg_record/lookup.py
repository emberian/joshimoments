"""/caller <wallet-or-username>: one caller's record as a DM card. Gated, rate-limited, plain.

The BOT side of the callout record, shaped exactly like dregg_gate.lookup's /screen
handler so the gateway wires it in as one line per command:

* GATED — a holder perk. Unverified users get an honest teaser (the shape, no data);
  ejected members are pointed back at /verify.
* RATE-LIMITED per user with the same window discipline as /screen (its own bucket,
  same ``gate.screen_rate_per_minute`` ceiling), so the DM lane never becomes a free
  records API.
* PLAIN TEXT, bare URLs, NO parse_mode — the dregg_feed.compose discipline. Provider
  usernames are whitespace-flattened and clamped before rendering, so a hostile
  handle cannot add lines; everything else is literal-inert in plain text.
* Reads the archive read-only via dregg_record.records; the archive service owns all
  writes. Wallet-layer color is stale-stamped per JOIN_CONTRACT.md.
* The standing line is a constant appended by the renderer — no card ships without it.

Config keys consumed (duck-typed off dregg_gate.config.Config): ``archive_db``,
``wallet_parquet``, ``screen_rate_per_minute``, ``threshold_tokens``.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path

from .records import (
    LAST_CALLS,
    caller_record,
    fmt_mult,
    fmt_pct,
    handle,
    last_calls,
    resolve_caller,
    short_wallet,
)

RATE_WINDOW_SECONDS = 60.0
TELEGRAM_MAX = 4096
PUMP_COIN_URL = "https://pump.fun/coin/{mint}"

STANDING_LINE = (
    "Records are measurements, not endorsements; the callout feed was measured as an "
    "anti-signal (see /help)."
)

USAGE_TEXT = (
    "Usage: /caller <wallet or @username> — a caller's wallet address (base58) or their "
    "exact board/X name, right after the command."
)

EJECTED_TEXT = (
    "Your seat lapsed (the wallet dropped below the gate), so /caller is locked. "
    "/verify <wallet> again to restore it."
)


def teaser_text(threshold_tokens: int) -> str:
    return (
        "/caller is a holder perk — verify to unlock.\n\n"
        "Verified members can pull any caller's measured record: every archived callout, "
        "how each call actually went at 1h/24h/7d by our own candles, what the provider "
        "claimed beside it, and what quietly vanished from their board. Deleted calls stay "
        "on the record.\n\n"
        f"Hold {threshold_tokens:,} $DREGG and send /verify <wallet> to get in."
    )


def rate_limited_text(per_minute: int) -> str:
    return (
        f"Easy — /caller is capped at {per_minute} lookups a minute per member, so the "
        "bot stays a bot and not an API. Try again in a moment."
    )


def not_found_text(query: str) -> str:
    return (
        f"No archived record matches {query!r}. I match a caller's wallet address "
        "(32-44 base58 characters) or their exact board/X username (@name works). "
        "The record covers callers seen on the board since the archive went live — "
        "someone who has never appeared there has no record here."
    )


def ambiguous_text(query: str, wallets: list[str]) -> str:
    listing = "\n".join(f"  {w}" for w in wallets)
    return (
        f"{query!r} names {len(wallets)} different wallets (names are provider text, "
        f"not identity):\n{listing}\n\nPick one with /caller <wallet>."
    )


# -- the card --------------------------------------------------------------------------


def _measured_lines(measured: dict) -> list[str]:
    if "absent" in measured:
        return [f"Measured: {measured['absent']}"]
    lines = ["Measured (our candles, close-to-close, "
             f"{measured['n_with_outcomes']} calls with outcome rows):"]
    r24 = measured["ret_24h"]
    if r24["n"]:
        lines.append(
            f"  24h: median {fmt_pct(r24['median'])} · mean {fmt_pct(r24['mean'])} (n={r24['n']})"
        )
    else:
        lines.append(f"  24h: {r24['absent']}")
    r1, r7 = measured["ret_1h"], measured["ret_7d"]
    h1 = f"median {fmt_pct(r1['median'])} (n={r1['n']})" if r1["n"] else r1["absent"]
    d7 = f"median {fmt_pct(r7['median'])} (n={r7['n']})" if r7["n"] else r7["absent"]
    lines.append(f"  1h: {h1} · 7d: {d7}")
    hits = measured["hits_24h"]
    if hits["n"]:
        lines.append(
            f"  24h above 0%: {hits['above_0']}/{hits['n']} · above +50%: {hits['above_50']}/{hits['n']}"
        )
    dd, dead = measured["drawdown"], measured["dead"]
    dd_bit = f"median max drawdown {dd['median']:.0%} (n={dd['n']})" if dd["n"] else dd["absent"]
    dead_bit = (
        f"dead by 7d: {dead['n_dead']}/{dead['n_final']}"
        if dead.get("n_final")
        else dead["absent"]
    )
    lines.append(f"  {dd_bit} · {dead_bit}")
    return lines


def _wallet_layer_line(layer: dict) -> str:
    if "absent" in layer:
        return f"Wallet layer: {layer['absent']}"
    win = layer.get("win_rate")
    bits = [f"realized {layer.get('net_realized_sol'):+,.1f} SOL"]
    if win is not None:
        bits.append(f"win rate {win:.0%} over {layer.get('n_coins_closed')} closed")
    if layer.get("rp_mode"):
        bits.append(str(layer["rp_mode"]))
    bits.append(f"guild {layer['guild']}" if layer.get("guild") is not None else "no guild")
    return f"Wallet layer (as of {layer.get('as_of')}, STALE): " + " · ".join(bits)


def _call_line(call: dict) -> str:
    day = call["day"] or "undated"
    r24 = fmt_pct(call["ret_24h"]) if call["ret_24h"] is not None else "pending"
    r7 = fmt_pct(call["ret_7d"]) if call["ret_7d"] is not None else "pending"
    claim = (
        f"claimed {fmt_mult(call['claimed_multiple'])}"
        if call["claimed_multiple"] is not None
        else "no claim"
    )
    line = (
        f"{day} {PUMP_COIN_URL.format(mint=call['mint'])} · 24h {r24} · 7d {r7} · {claim}"
    )
    if call["dead"]:
        line += " · dead by 7d"
    if call["removal"] == "removed":
        line += " · REMOVED from the provider's board (still counted)"
    elif call["removal"] == "unknown-absent":
        line += " · absent from the provider's board (verdict: unknown-absent)"
    return line


def render_card(record: dict, calls: list[dict]) -> str:
    """One caller, one plain-text card, standing line last."""

    identity = record["identity"]
    counts = record["callouts"]
    head = (
        f"📇 CALLER RECORD — {handle(identity['username'], identity['x_username'], record['wallet'])} "
        f"({record['wallet']})"
    )
    seen = (
        f"first archived {identity['first_seen']} · last seen {identity['last_seen']}"
        if identity["first_seen"]
        else f"dates unknown — {identity['seen_note']}"
    )
    count_line = (
        f"Callouts: {counts['lifetime']} lifetime · {counts['window']} in last "
        f"{counts['window_days']}d · {counts['distinct_mints']} distinct coins"
    )
    if counts["undated"]:
        count_line += f" · {counts['undated']} undated (provider served no timestamp)"

    claim = record["provider_claim"]
    claim_line = (
        f"Provider's claimed multiples (their number, never ours): median "
        f"{fmt_mult(claim['median_multiple'])} · best {fmt_mult(claim['max_multiple'])} (n={claim['n']})"
        if claim["n"]
        else f"Provider's claimed multiples: {claim['absent']}"
    )
    removals = record["removals"]
    n_removed = removals["published_removed"] + removals["published_unknown_absent"]
    removal_line = (
        f"Removals: {n_removed} callout(s) vanished from the provider's board "
        f"({removals['published_removed']} removed, {removals['published_unknown_absent']} "
        "unknown-absent; published verdicts) — they stay counted above."
        if n_removed
        else "Removals: none on record."
    )

    lines = [head, seen, "", count_line, *_measured_lines(record["measured"]), claim_line,
             removal_line, _wallet_layer_line(record["wallet_layer"])]
    if calls:
        lines += ["", f"LAST {len(calls)} CALLS", *(_call_line(c) for c in calls)]
    lines += ["", STANDING_LINE]
    text = "\n".join(lines)
    assert len(text) <= TELEGRAM_MAX, "/caller card exceeded Telegram's cap"
    return text


# -- the handler -----------------------------------------------------------------------


class CallerLookup:
    """/caller state: per-user rate window. Config comes through a getter so the
    service's keep-last-good reload reaches lookups without extra wiring."""

    def __init__(
        self,
        config_getter: Callable[[], object],
        state,
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
        """The full /caller decision: (reply text, parse_mode — always None: plain)."""

        cfg = self._config()
        member = self.state.member(uid)
        if member is None:
            return teaser_text(cfg.threshold_tokens), None
        if member.status == "ejected":
            return EJECTED_TEXT, None
        if not self._admit(uid, cfg.screen_rate_per_minute):
            return rate_limited_text(cfg.screen_rate_per_minute), None
        if arg is None or not arg.strip().lstrip("@"):
            return USAGE_TEXT, None
        archive_db: Path = cfg.archive_db
        wallets = resolve_caller(archive_db, arg)
        if not wallets:
            return not_found_text(arg[:64]), None
        if len(wallets) > 1:
            return ambiguous_text(arg[:64], wallets), None
        wallet = wallets[0]
        record = caller_record(
            archive_db,
            wallet,
            now_ms=int(self.clock() * 1000),
            wallet_parquet=cfg.wallet_parquet,
        )
        if "absent" in record:
            # A callers-roster hit with zero archived callouts: state it, don't shrug.
            return (
                f"{short_wallet(wallet)} is known to the roster but has no archived "
                f"callouts yet ({record['absent']}).",
                None,
            )
        return render_card(record, last_calls(archive_db, wallet, limit=LAST_CALLS)), None
