"""Events from the three surfaces, and the matching + rendering that turns them into DMs.

SOURCES (all read-only; each producer owns its own writes):

* screen — the live screen's ``<scores dir>/<utc-day>.jsonl`` (dregg_screen.live).
  Tailed with DURABLE byte-offset cursors per day file, the dregg_feed.verdicts
  discipline: never advance past the last complete newline (a torn tail line is read
  again whole next poll), a shrunken file rebuilds from zero, today's and yesterday's
  files are both live (appends land in yesterday's file right after the UTC roll).
* callouts — the archive's ``callouts`` table (dregg_archive.store). New rows are
  paged by ``first_seen_fetch`` (a fetch id: monotone), which IS the "this callout is
  new" signal — later sightings only bump *_last columns and never re-fire.
* feed — the movers detector's ``alerts`` table (dregg_feed.movers), paged by rowid.

FIRST BOOT: every cursor initializes AT THE CURRENT END (file EOF / max id) and emits
nothing. A watch is about the future; replaying 35k historical launches into DMs the
moment the service first starts would be the flood this module exists to prevent.

EVENT KEYS are derived from row CONTENT (mint+t_scored, callout_id, alert rowid), so
they are identical across restarts and replays — that is what makes the sent-table
claim in state.py mean anything.

RENDERED TEXT IS PLAIN — the gate outbox sends it with no parse_mode, so no HTML, no
markdown, bare pump.fun URLs. Provider-derived text (symbols, names, theses,
usernames) is length-clamped and newline-stripped, never escaped-for-markup, because
there is no markup.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .state import Subscription, WatchState

PUMP_COIN_URL = "https://pump.fun/coin/{mint}"

SCREEN_CURSOR_PREFIX = "screen:"
CALLOUT_CURSOR = "archive:first_seen_fetch"
FEED_CURSOR = "feed:alert_id"

_ROW_PAGE = 500  # sqlite tailers page this many rows per poll; the rest wait a cycle


def short(wallet: str) -> str:
    return wallet if len(wallet) <= 12 else f"{wallet[:4]}…{wallet[-4:]}"


def _clean_text(value: object, limit: int) -> str:
    """Provider text into one plain line: newlines collapsed, length clamped."""

    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class Event:
    source: str                # 'screen' | 'callout' | 'feed'
    key: str                   # stable across restarts (content-derived)
    mint: str
    title: str                 # "$SYM" or a mint prefix; already plain text
    facts: tuple[str, ...]     # measured lines for the event-mode DM body
    compact: str               # one-line form for digest batching
    verdict: str | None = None
    deployers: tuple[str, ...] = ()
    crew_ids: tuple[str, ...] = ()
    caller_wallet: str | None = None
    caller_names: tuple[str, ...] = ()  # lowercased, no '@'


# -- screen rows -> events -------------------------------------------------------------


def _score_title(row: dict) -> str:
    symbol = _clean_text(row.get("symbol") or "", 24).strip()
    mint = str(row.get("mint") or "")
    return f"${symbol.lstrip('$')}" if symbol else (mint[:8] or "?")


def event_from_score(row: dict) -> Event | None:
    mint = row.get("mint")
    if not isinstance(mint, str) or not mint:
        return None
    verdict = str(row.get("verdict") or "UNSCORED")
    features = row.get("features") or {}
    history = row.get("deployer_history") or {}

    deployers = tuple(
        w for w in (row.get("deployer"), row.get("creator")) if isinstance(w, str) and w
    )

    # A crew match carries every crew at the tied best score (tied_crew_ids); a watch
    # on ANY of them fires, because the launch's fingerprint fits each equally well.
    # Old rows without the field fall back to the single named id.
    def _ids(match: dict) -> list[str]:
        tied = [str(c) for c in match.get("tied_crew_ids") or [] if c is not None]
        return tied or [str(match["crew_id"])]

    crew_ids: list[str] = []
    crew_line: str | None = None
    crew = row.get("crew_match")
    if isinstance(crew, dict) and crew.get("crew_id") is not None:
        crew_ids.extend(_ids(crew))
        n_tied = len(_ids(crew))
        if n_tied > 1:
            crew_line = (
                f"Crew: matched a fingerprint {n_tied} tracked crews share equally "
                f"(#{crew['crew_id']} shown as one of them) — "
                f"{crew.get('overlap')} shared birth-slot wallets, "
                f"overlap {crew.get('jaccard')} of 1"
            )
        else:
            crew_line = (
                f"Crew: matched fingerprint #{crew['crew_id']} — "
                f"{crew.get('overlap')} shared birth-slot wallets, "
                f"overlap {crew.get('jaccard')} of 1"
            )
    continuity = features.get("crew_continuity_note")
    if isinstance(continuity, dict) and continuity.get("crew_id") is not None:
        for cid in _ids(continuity):
            if cid not in crew_ids:
                crew_ids.append(cid)

    facts: list[str] = []
    bits: list[str] = []
    share = features.get("dev_buy_share")
    if isinstance(share, (int, float)):
        source = "chain-exact" if features.get("dev_buy_source") == "chain_exact" else "vendor estimate"
        bits.append(f"dev buy {100 * share:.2f}% of supply ({source})")
    n_snipers = features.get("n_snipers")
    if row.get("hydrated") and isinstance(n_snipers, int):
        bits.append(f"{n_snipers} birth-slot buyer{'s' if n_snipers != 1 else ''}")
    bits.append(
        f"deployer record {history.get('launches', 0)} launches / "
        f"{history.get('rips', 0)} rips / {history.get('dumps', 0)} dumps"
    )
    facts.append(f"Screen: {verdict.replace('_', '-')} — " + "; ".join(bits))
    if crew_line is not None:
        facts.append(crew_line)

    compact_bits = [b for b in bits[:2]]
    compact = f"{_score_title(row)} {PUMP_COIN_URL.format(mint=mint)}"
    if compact_bits:
        compact += " — " + "; ".join(compact_bits)

    return Event(
        source="screen",
        key=f"screen:{mint}:{row.get('t_scored') or ''}",
        mint=mint,
        title=_score_title(row),
        facts=tuple(facts),
        compact=compact,
        verdict=verdict,
        deployers=deployers,
        crew_ids=tuple(crew_ids),
    )


@dataclass(slots=True)
class TailResult:
    events: list[Event] = field(default_factory=list)
    cursor_updates: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def tail_screen(scores_dir: Path, state: WatchState, now: float, *, first_run: bool) -> TailResult:
    out = TailResult()
    today = datetime.fromtimestamp(now, tz=UTC).date()
    days = [(today - timedelta(days=1)).isoformat(), today.isoformat()]
    keep = {SCREEN_CURSOR_PREFIX + day for day in days}
    state.drop_cursors_except(SCREEN_CURSOR_PREFIX, keep)
    for day in days:
        path = scores_dir / f"{day}.jsonl"
        key = SCREEN_CURSOR_PREFIX + day
        try:
            size = path.stat().st_size
        except OSError:
            continue  # that day's file absent (screen down, or the day just rolled)
        stored = state.cursor(key)
        if stored is None:
            if first_run or day != days[-1]:
                # First boot, or a never-seen YESTERDAY file: a watch is about the
                # future, so skip the backlog — cursor straight to EOF. A never-seen
                # TODAY file starts at 0: it was just born (the day rolled under a
                # running service) or we were briefly down — deliver late, not never.
                out.cursor_updates[key] = str(size)
                continue
            offset = 0
        else:
            offset = int(stored)
        if size < offset:  # truncated/replaced: our offset points at nothing
            offset = 0
        if size == offset:
            continue
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(size - offset)
        except OSError as exc:
            out.errors.append(f"screen:{day}: {type(exc).__name__}")
            continue
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            continue  # only a partial line so far; read it whole next poll
        for line in chunk[: last_newline + 1].splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(row, dict):
                event = event_from_score(row)
                if event is not None:
                    out.events.append(event)
        out.cursor_updates[key] = str(offset + last_newline + 1)
    return out


# -- archive callouts -> events --------------------------------------------------------


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def tail_callouts(archive_db: Path, state: WatchState, *, first_run: bool) -> TailResult:
    out = TailResult()
    if not archive_db.exists():
        return out
    try:
        connection = _read_only(archive_db)
    except sqlite3.Error as exc:
        out.errors.append(f"callouts: {type(exc).__name__}")
        return out
    try:
        stored = state.cursor(CALLOUT_CURSOR)
        if stored is None or first_run:
            row = connection.execute(
                "SELECT COALESCE(MAX(first_seen_fetch), 0) AS m FROM callouts"
            ).fetchone()
            out.cursor_updates[CALLOUT_CURSOR] = str(int(row["m"]))
            return out
        rows = connection.execute(
            "SELECT callout_id, wallet, mint, thesis, provider_multiple_last, "
            "username_last, x_username_last, first_seen_fetch FROM callouts "
            "WHERE first_seen_fetch > ? ORDER BY first_seen_fetch LIMIT ?",
            (int(stored), _ROW_PAGE),
        ).fetchall()
    except sqlite3.Error as exc:
        out.errors.append(f"callouts: {type(exc).__name__}")
        return out
    finally:
        connection.close()
    high = int(stored)
    for row in rows:
        high = max(high, int(row["first_seen_fetch"]))
        wallet = str(row["wallet"])
        names = tuple(
            str(n).lstrip("@").lower()
            for n in (row["username_last"], row["x_username_last"])
            if isinstance(n, str) and n
        )
        display = (
            f"@{_clean_text(row['username_last'], 32)}"
            if isinstance(row["username_last"], str) and row["username_last"]
            else short(wallet)
        )
        facts = [f"Callout by {display} ({short(wallet)})"]
        multiple = row["provider_multiple_last"]
        if isinstance(multiple, (int, float)):
            facts.append(f"Provider claims {multiple:.1f}x at last sighting")
        if isinstance(row["thesis"], str) and row["thesis"].strip():
            facts.append(f"Thesis: {_clean_text(row['thesis'], 160)}")
        mint = str(row["mint"])
        out.events.append(
            Event(
                source="callout",
                key=f"callout:{row['callout_id']}",
                mint=mint,
                title=mint[:8] + "…",
                facts=tuple(facts),
                compact=f"{mint[:8]}… {PUMP_COIN_URL.format(mint=mint)} — {facts[0]}",
                caller_wallet=wallet,
                caller_names=names,
            )
        )
    if rows:
        out.cursor_updates[CALLOUT_CURSOR] = str(high)
    return out


# -- feed momentum alerts -> events ----------------------------------------------------

_FEED_REASON = {"accel": "5m volume acceleration", "top5_entry": "entered the board's top 5 by 5m volume"}


def tail_feed(feed_db: Path, state: WatchState, *, first_run: bool) -> TailResult:
    out = TailResult()
    if not feed_db.exists():
        return out
    try:
        connection = _read_only(feed_db)
    except sqlite3.Error as exc:
        out.errors.append(f"feed: {type(exc).__name__}")
        return out
    try:
        stored = state.cursor(FEED_CURSOR)
        if stored is None or first_run:
            row = connection.execute("SELECT COALESCE(MAX(id), 0) AS m FROM alerts").fetchone()
            out.cursor_updates[FEED_CURSOR] = str(int(row["m"]))
            return out
        rows = connection.execute(
            "SELECT id, mint, v5, reason FROM alerts WHERE id > ? ORDER BY id LIMIT ?",
            (int(stored), _ROW_PAGE),
        ).fetchall()
    except sqlite3.Error as exc:
        out.errors.append(f"feed: {type(exc).__name__}")
        return out
    finally:
        connection.close()
    high = int(stored)
    for row in rows:
        high = max(high, int(row["id"]))
        mint = str(row["mint"])
        reason = _FEED_REASON.get(str(row["reason"]), str(row["reason"]))
        fact = f"Momentum: {reason}"
        if isinstance(row["v5"], (int, float)):
            fact += f" — 5m volume {row['v5']:.0f} SOL (provider-claimed)"
        out.events.append(
            Event(
                source="feed",
                key=f"feed:{row['id']}",
                mint=mint,
                title=mint[:8] + "…",
                facts=(fact,),
                compact=f"{mint[:8]}… {PUMP_COIN_URL.format(mint=mint)} — {fact}",
            )
        )
    if rows:
        out.cursor_updates[FEED_CURSOR] = str(high)
    return out


# -- matching --------------------------------------------------------------------------


def matches(sub: Subscription, event: Event) -> bool:
    if sub.kind == "coin":
        return event.mint == sub.spec
    if sub.kind == "deployer":
        return sub.spec in event.deployers
    if sub.kind == "crew":
        return sub.spec in event.crew_ids
    if sub.kind == "caller":
        return event.source == "callout" and (
            sub.spec == event.caller_wallet or sub.spec.lower() in event.caller_names
        )
    if sub.kind == "clean":
        return event.source == "screen" and event.verdict == "CLEAN"
    return False


def match_all(subs: list[Subscription], event: Event) -> list[Subscription]:
    return [sub for sub in subs if matches(sub, event)]


# -- rendering (plain text, bare URLs, why-it-fired, how-to-stop) ----------------------

_SOURCE_WHY = {
    "screen": "the launch screen scored your watched coin",
    "callout": "your watched coin got a new callout",
    "feed": "your watched coin hit the movers board",
}


def _why(sub: Subscription, event: Event) -> str:
    since = datetime.fromtimestamp(sub.created_at, tz=UTC).date().isoformat()
    if sub.kind == "coin":
        return f"{_SOURCE_WHY[event.source]}; you watched it {since}"
    if sub.kind == "deployer":
        return f"deployer {short(sub.spec)} launched again; you watched them {since}"
    if sub.kind == "crew":
        return (
            f"a fingerprint matching crew #{sub.spec} appeared in this launch; "
            f"you watched that crew {since}"
        )
    if sub.kind == "caller":
        return f"a caller you watch ({short(sub.spec)}) made a new callout; watched {since}"
    return f"CLEAN-verdict launch; you watch all of these ({since})"


def render_dm(sub: Subscription, event: Event) -> str:
    lines = [f"{event.title} — {_why(sub, event)}."]
    lines.extend(event.facts)
    lines.append(PUMP_COIN_URL.format(mint=event.mint))
    lines.append(event.mint)
    lines.append(f"Stop this watch: /unwatch {sub.id}")
    return "\n".join(lines)


def render_digest_line(sub: Subscription, event: Event) -> str:
    return event.compact


def render_digest(lines: list[tuple[int, str]], *, window_min: float, max_lines: int) -> str:
    """One digest DM: grouped by watch id, capped, with an honest overflow count."""

    by_sub: dict[int, list[str]] = {}
    for sub_id, line in lines:
        by_sub.setdefault(sub_id, []).append(line)
    out = [f"Your watch digest — {len(lines)} match(es) in the last ~{window_min:.0f} min."]
    shown = 0
    hidden = 0
    for sub_id in sorted(by_sub):
        batch = by_sub[sub_id]
        out.append("")
        out.append(f"Watch #{sub_id} — {len(batch)} match(es); /unwatch {sub_id} to stop:")
        for line in batch:
            if shown < max_lines:
                out.append(line)
                shown += 1
            else:
                hidden += 1
    if hidden:
        out.append("")
        out.append(f"…and {hidden} more not shown (digest cap).")
    return "\n".join(out)
