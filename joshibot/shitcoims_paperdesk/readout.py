"""Resolve what the operator typed, then reflect back everything measurable in under 2 s.

THE TWO JOBS, AND WHY THEY LIVE TOGETHER
----------------------------------------
The operator types ``hunch CALICO "gonna wiggle for a bit"``. Two things have to happen
before that sentence is worth anything:

1. **Resolution.** ``CALICO`` has to become a 32-byte mint, or the whole tape is worthless
   and the paper position is on the wrong coin. This module resolves against the freshest
   things on disk -- the boards tape's live members, today's firehose launches, the last
   hour of callouts, and the bags the desk and the sentinel are actually holding -- and
   **refuses rather than guesses**. Two mints matching means two mints listed and a nonzero
   exit. The address-fabrication scars in this repo were all one component deciding it knew
   which address was meant.
2. **Readback.** Everything the desk can measure about that coin, printed immediately, so
   the gesture and the instrument arrive together. The operator's intuition is the signal
   being amplified; the amplification is that they see, at the moment they commit, what the
   machine sees -- depth, drawdown, recency, their own exit impact, the wiggle the tape has
   already recorded.

Both read the same files, so they are the same module.

NEVER BLOCK THE CAPTURE
-----------------------
The readout has a hard deadline and every slow source runs inside it on its own thread. A
source that misses the deadline is reported ABSENT WITH A REASON. It is never reported as
zero, never silently omitted, and never allowed to delay the row -- the CLI has already
fsynced the hunch before this module is called, so the worst case of a dead vendor is a
thinner printout, not a lost fact.

"Absent" and "zero" being different states is the same rule ``drawdown_from_ath = -1.0``
exists for, and the same one ``Measured<T>`` will carry into the glass.
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final

from shitcoims_paperdesk.feeds import DRAWDOWN_UNKNOWN, STATE, MintObservation
from shitcoims_paperdesk.friction import Friction
from shitcoims_paperdesk.policy import WigglePolicy
from shitcoims_paperdesk.wiggle import WiggleWatch, ghost_town_impact

__all__ = [
    "BOARDS_TAIL_BYTES",
    "READOUT_DEADLINE_S",
    "Candidate",
    "Readout",
    "Resolution",
    "board_candidates",
    "board_path_for",
    "is_mint",
    "parse_iso",
    "readout",
    "render_readout",
    "resolve",
]

#: How much of the boards tape the resolver and the price-path reader look at. The file runs
#: ~177 MB/day, i.e. ~7 MB/hour, so this is roughly the last three hours -- more than the
#: hour any of these statistics are computed over, and small enough that the read is a
#: fraction of the deadline. A byte-substring prefilter runs before any JSON parsing, so the
#: cost of the window is the read, not the decode.
BOARDS_TAIL_BYTES: Final[int] = 24 * 1024 * 1024

#: Today's firehose is ~15 MB of launches; the tail is where the live ones are.
FIREHOSE_TAIL_BYTES: Final[int] = 8 * 1024 * 1024

#: The whole readout, wall clock. Past this, whatever has not arrived is ABSENT.
READOUT_DEADLINE_S: Final[float] = 2.0

#: The window every flow statistic here is computed over, matching
#: ``wiggle.CALLOUT_WINDOW_S`` so "last hour" means one thing on this desk.
FLOW_WINDOW_S: Final[float] = 3_600.0

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}


def is_mint(text: str) -> bool:
    """A real Solana address: base58 that DECODES to 32 bytes.

    Same test as ``shitcoims_intelligence.adapters.x_apify.is_solana_mint`` and
    ``shitcoims_tape.schema._mint``, inlined here only so that the CLI's resolver does not
    drag the intelligence package's import graph into a command that must start fast. The
    property being tested is a fact about base58, not a policy, so it cannot drift.
    """
    if not 32 <= len(text) <= 44:
        return False
    value = 0
    for char in text:
        index = _B58_INDEX.get(char)
        if index is None:
            return False
        value = value * 58 + index
    leading = len(text) - len(text.lstrip("1"))
    return leading + (value.bit_length() + 7) // 8 == 32


# ---------------------------------------------------------------------- candidates


@dataclass(frozen=True, slots=True)
class Candidate:
    """One coin the operator could plausibly have meant, and where we saw it."""

    mint: str
    symbol: str | None
    name: str | None
    source: str
    t_seen_unix: float
    detail: str = ""

    @property
    def label(self) -> str:
        return self.symbol or self.name or (self.mint[:6] + "…")


#: Tier order for a SYMBOL match. A coin sitting on a live board right now is what somebody
#: staring at a screen means by its ticker; a launch from six hours ago that happens to
#: share the ticker is not. The tier only ever picks between sources -- WITHIN the winning
#: tier, two mints is still an ambiguity and still a refusal.
SYMBOL_TIERS: Final[tuple[str, ...]] = ("boards", "held", "firehose", "callouts")


def _read_tail(path: Path, limit: int) -> list[bytes]:
    """The last ``limit`` bytes as whole lines. A leading partial line is dropped."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    start = max(0, size - limit)
    try:
        with path.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(size - start)
    except OSError:
        return []
    lines = chunk.split(b"\n")
    if start > 0 and lines:
        lines.pop(0)  # the window opened mid-row
    return [ln for ln in lines if ln.strip()]


def board_path_for(now: float, root: Path | None = None) -> Path:
    base = root or (STATE / "boards")
    return base / f"boards-{datetime.fromtimestamp(now, tz=UTC):%Y%m%d}.jsonl"


def board_candidates(now: float, *, root: Path | None = None) -> dict[str, Candidate]:
    """Live board members and arrivals, newest wins. The best source of mint -> ticker."""
    out: dict[str, Candidate] = {}
    for raw in _read_tail(board_path_for(now, root), BOARDS_TAIL_BYTES):
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        board = row.get("board")
        members: list[Any]
        if kind == "board_snapshot":
            members = [m for m in (row.get("members") or ()) if isinstance(m, dict)]
        elif kind == "board_entry":
            members = [row]
        else:
            continue
        for member in members:
            mint = member.get("mint")
            if not isinstance(mint, str):
                continue
            seen = float(member.get("t_ingest") or row.get("t_ingest") or 0.0)
            previous = out.get(mint)
            if previous is not None and previous.t_seen_unix >= seen:
                continue
            out[mint] = Candidate(
                mint=mint,
                symbol=member.get("symbol"),
                name=None,
                source="boards",
                t_seen_unix=seen,
                detail=str(board or ""),
            )
    return out


def firehose_candidates(now: float, *, root: Path | None = None) -> dict[str, Candidate]:
    """Today's launches. The only source carrying a human NAME as well as a ticker."""
    base = root or (STATE / "firehose" / "new_token")
    path = base / f"{datetime.fromtimestamp(now, tz=UTC):%Y-%m-%d}.jsonl"
    out: dict[str, Candidate] = {}
    for raw in _read_tail(path, FIREHOSE_TAIL_BYTES):
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict) or row.get("kind") != "new_token":
            continue
        mint = row.get("mint")
        payload = row.get("payload")
        if not isinstance(mint, str) or not isinstance(payload, dict):
            continue
        out[mint] = Candidate(
            mint=mint,
            symbol=payload.get("symbol"),
            name=payload.get("name"),
            source="firehose",
            t_seen_unix=parse_iso(row.get("t_ingest")) or 0.0,
            detail="launch",
        )
    return out


def callout_candidates(now: float) -> dict[str, Candidate]:
    """Mints called out in the last hour. No ticker on this source; mints only.

    Reuses ``shitcoims_scalper.feed.poll_callouts`` rather than querying the intelligence
    SQLite here: that function already handles the daemon's write lock (it reads a copy) and
    the three-way mint resolution, including the measured fact that a third of payload mints
    on that feed are lowercase-mangled and must be REJECTED rather than repaired.
    """
    try:
        from shitcoims_scalper.feed import poll_callouts

        calls = poll_callouts(max_age_s=FLOW_WINDOW_S)
    except Exception:
        return {}
    return {
        c.mint: Candidate(
            mint=c.mint,
            symbol=None,
            name=None,
            source="callouts",
            t_seen_unix=c.t_post_unix,
            detail=f"{c.kind} @{c.author}" if c.author else c.kind,
        )
        for c in calls
    }


def held_candidates(now: float) -> dict[str, Candidate]:
    """Bags we are in: the sentinel's live positions and the paper desk's own.

    READ-ONLY, and deliberately by file rather than by importing anything from
    ``shitcoims_sentinel`` -- that package holds keys and this one is a CLI the operator runs
    a dozen times an hour. The sentinel's state carries no symbol at all (its human names are
    assembled in memory and served over HTTP), so held coins resolve by mint and prefix and
    fall through to the other sources for a ticker.
    """
    out: dict[str, Candidate] = {}
    try:
        with (STATE / "sentinel-state.json").open() as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        state = {}
    if isinstance(state, dict):
        stamp = parse_iso(state.get("updated_at")) or 0.0
        for bucket in ("positions", "lots"):
            entries = state.get(bucket)
            if not isinstance(entries, dict):
                continue
            for mint in entries:
                if isinstance(mint, str) and mint not in out:
                    out[mint] = Candidate(
                        mint=mint,
                        symbol=None,
                        name=None,
                        source="held",
                        t_seen_unix=stamp,
                        detail=f"sentinel:{bucket}",
                    )
    try:
        with (STATE / "paperdesk" / "desk-state.json").open() as fh:
            desk = json.load(fh)
    except (OSError, json.JSONDecodeError):
        desk = {}
    if isinstance(desk, dict):
        for book, book_state in desk.items():
            if not isinstance(book_state, dict):
                continue
            for position in (book_state.get("positions") or {}).values():
                mint = position.get("mint") if isinstance(position, dict) else None
                if isinstance(mint, str) and mint not in out:
                    out[mint] = Candidate(
                        mint=mint,
                        symbol=None,
                        name=None,
                        source="held",
                        t_seen_unix=float(position.get("last_obs_unix") or 0.0),
                        detail=f"paper:{book}",
                    )
    return out


# ---------------------------------------------------------------------- resolution


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the query resolved to, or why it did not. ``mint is None`` means REFUSED."""

    query: str
    mint: str | None
    matched_on: str
    chosen: Candidate | None
    candidates: tuple[Candidate, ...] = ()
    suppressed: tuple[Candidate, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.mint is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "matched_on": self.matched_on,
            "source": self.chosen.source if self.chosen else None,
            "detail": self.chosen.detail if self.chosen else None,
            # How many OTHER coins wore the same name and were not chosen. A one here is
            # the difference between "resolved" and "resolved, and you should look".
            "suppressed": len(self.suppressed),
            "suppressed_mints": [c.mint for c in self.suppressed][:10],
            "reason": self.reason,
        }


def _universe(
    now: float, *, sources: dict[str, Callable[[], dict[str, Candidate]]] | None = None
) -> dict[str, list[Candidate]]:
    """mint -> every sighting of it, across sources. Local sources first, network last.

    ``sources is None`` means "use the real tapes"; an EMPTY mapping means "look nowhere",
    and the two must not collapse. Written as ``sources or {...}`` this fell through to the
    live boards on an empty dict, so a caller asking for a cold universe silently got a warm
    one -- a test asserting the no-coverage path passed against real market data.
    """
    builders: dict[str, Callable[[], dict[str, Candidate]]] = (
        sources
        if sources is not None
        else {
            "boards": lambda: board_candidates(now),
            "held": lambda: held_candidates(now),
            "firehose": lambda: firehose_candidates(now),
            "callouts": lambda: callout_candidates(now),
        }
    )
    merged: dict[str, list[Candidate]] = {}
    for build in builders.values():
        try:
            found = build()
        except Exception:
            continue
        for mint, candidate in found.items():
            merged.setdefault(mint, []).append(candidate)
    return merged


def resolve(
    query: str,
    *,
    now: float | None = None,
    sources: dict[str, Callable[[], dict[str, Candidate]]] | None = None,
) -> Resolution:
    """A mint, a mint prefix, or a symbol -> one mint, or a refusal listing the matches.

    THE THREE MODES, and the refusal rule for each:

    * **A full mint** is accepted on its own if it decodes to 32 bytes, whether or not any
      source has seen it. Refusing an address the operator pasted because our tapes are cold
      would be the tool substituting its own coverage for their knowledge.
    * **A prefix** matches across every source at once with NO tier preference, because a
      prefix is typed precisely to be unique -- two matches means the operator's
      disambiguator did not disambiguate, and they need to see that, not have it decided.
    * **A symbol** matches case-insensitively and IS tiered (:data:`SYMBOL_TIERS`), because
      tickers are not unique on this market by construction: dozens of launches a day share
      one. The tier picks between SOURCES; two mints inside the winning tier is still a
      refusal. Everything the tier passed over is carried on the resolution and printed, so
      a tie broken in favour of the live board is a thing the operator sees happen.
    """
    now = time.time() if now is None else now
    text = query.strip()
    if not text:
        return Resolution(query=query, mint=None, matched_on="none", chosen=None, reason="empty query")

    universe = _universe(now, sources=sources)

    if is_mint(text):
        sightings = universe.get(text) or ()
        best = max(sightings, key=lambda c: c.t_seen_unix) if sightings else None
        return Resolution(
            query=query,
            mint=text,
            matched_on="mint",
            chosen=best
            or Candidate(
                mint=text,
                symbol=None,
                name=None,
                source="literal",
                t_seen_unix=0.0,
                detail="address as typed",
            ),
            candidates=(best,) if best else (),
            reason="" if sightings else "address accepted as typed; no source has seen it recently",
        )

    lowered = text.lower()

    prefix_hits = {m: cs for m, cs in universe.items() if m.lower().startswith(lowered)}
    if prefix_hits:
        flat = tuple(sorted(
            (max(cs, key=lambda c: c.t_seen_unix) for cs in prefix_hits.values()),
            key=lambda c: -c.t_seen_unix,
        ))
        if len(prefix_hits) == 1:
            only = flat[0]
            return Resolution(query=query, mint=only.mint, matched_on="prefix", chosen=only, candidates=flat)
        return Resolution(
            query=query,
            mint=None,
            matched_on="prefix",
            chosen=None,
            candidates=flat,
            reason=f"{len(prefix_hits)} mints start with {text!r}",
        )

    by_symbol: dict[str, list[Candidate]] = {}
    for sightings in universe.values():
        for candidate in sightings:
            for field_value in (candidate.symbol, candidate.name):
                if isinstance(field_value, str) and field_value.strip().lstrip("$").lower() == lowered:
                    by_symbol.setdefault(candidate.source, []).append(candidate)
                    break
    if not by_symbol:
        return Resolution(
            query=query,
            mint=None,
            matched_on="symbol",
            chosen=None,
            reason=(
                f"nothing on the boards, the firehose, the callouts or our own bags is called "
                f"{text!r}. Paste the mint address if you have it."
            ),
        )
    all_hits = tuple(c for cs in by_symbol.values() for c in cs)
    for tier in SYMBOL_TIERS:
        tier_hits = by_symbol.get(tier)
        if not tier_hits:
            continue
        mints = {c.mint for c in tier_hits}
        if len(mints) == 1:
            chosen = max(tier_hits, key=lambda c: c.t_seen_unix)
            return Resolution(
                query=query,
                mint=chosen.mint,
                matched_on="symbol",
                chosen=chosen,
                candidates=(chosen,),
                suppressed=tuple(c for c in all_hits if c.mint != chosen.mint),
            )
        return Resolution(
            query=query,
            mint=None,
            matched_on="symbol",
            chosen=None,
            candidates=tuple(sorted(tier_hits, key=lambda c: -c.t_seen_unix)),
            reason=f"{len(mints)} different mints on the {tier} are called {text!r}",
        )
    return Resolution(  # pragma: no cover - unreachable while SYMBOL_TIERS covers every source
        query=query, mint=None, matched_on="symbol", chosen=None, candidates=all_hits,
        reason="matches came from a source with no tier",
    )


# ---------------------------------------------------------------------- the readout


@dataclass
class Readout:
    """Everything measurable about one coin at one instant, with the gaps NAMED.

    A field left ``None`` is absent, and :attr:`absent` says why. Nothing in here is ever
    defaulted to zero: a market cap of zero and an unfetched market cap look identical in a
    number and completely different in a decision, and this desk has already paid once for
    ``drawdown_from_ath = 0.0`` reading as "at its all-time high".
    """

    mint: str
    symbol: str | None = None
    t_unix: float = 0.0
    elapsed_s: float = 0.0
    absent: dict[str, str] = field(default_factory=dict)

    price_sol: float | None = None
    usd_market_cap: float | None = None
    drawdown_from_ath: float | None = None
    age_s: float | None = None
    trade_recency_s: float | None = None
    complete: bool | None = None
    board: str | None = None

    sol_in_curve: float | None = None
    own_exit_impact: float | None = None
    round_trip_cost: float | None = None
    clip_lamports: int = 0

    observations: int | None = None
    obs_per_min: float | None = None
    two_sided_frac: float | None = None
    wiggle_n: int | None = None
    wiggle_amp: float | None = None
    trade_marks_per_hour: float | None = None

    callout_last_s: float | None = None
    callout_kind: str | None = None
    callout_author: str | None = None

    crime_symbol: str | None = None
    crime_peak_mcap: float | None = None
    crime_drawdown: float | None = None

    ghost_town: bool | None = None
    gate_legs: dict[str, bool] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        return out


def parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def board_price_path(
    mint: str, now: float, *, root: Path | None = None, window_s: float = FLOW_WINDOW_S
) -> list[MintObservation]:
    """Every boards sighting of ONE mint in the recent window, oldest first.

    Reads the boards tail as BYTES and prefilters on the mint substring before parsing any
    JSON. A snapshot row carries fifty members and the day's file is ~177 MB, so parsing
    everything to find one coin would blow the readout deadline by an order of magnitude;
    the substring test over the same bytes costs milliseconds and cannot produce a false
    negative, because a row mentioning the mint contains the mint.
    """
    needle = mint.encode()
    cutoff = now - window_s
    out: list[MintObservation] = []
    for raw in _read_tail(board_path_for(now, root), BOARDS_TAIL_BYTES):
        if needle not in raw:
            continue
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        board = row.get("board")
        if kind == "board_snapshot":
            members = [
                m for m in (row.get("members") or ()) if isinstance(m, dict) and m.get("mint") == mint
            ]
        elif kind == "board_entry" and row.get("mint") == mint:
            members = [row]
        else:
            continue
        for member in members:
            vsol, vtok = member.get("virtual_sol_reserves"), member.get("virtual_token_reserves")
            stamp = float(member.get("t_ingest") or row.get("t_ingest") or 0.0)
            if not vsol or not vtok or stamp < cutoff:
                continue
            last_trade = member.get("last_trade_unix")
            out.append(
                MintObservation(
                    mint=mint,
                    source="boards",
                    t_ingest_unix=stamp,
                    t_event_unix=float(last_trade) if last_trade else None,
                    t_event_source="vendor:last_trade_timestamp" if last_trade else "absent:vendor",
                    vsol_lamports=int(vsol),
                    vtok_raw=int(vtok),
                    usd_market_cap=float(member.get("usd_market_cap") or 0.0),
                    ath_market_cap=float(member.get("ath_market_cap") or 0.0),
                    drawdown_from_ath=float(
                        member.get("drawdown_from_ath", DRAWDOWN_UNKNOWN) or DRAWDOWN_UNKNOWN
                    ),
                    created_unix=float(member["created_unix"]) if member.get("created_unix") else None,
                    last_trade_unix=float(last_trade) if last_trade else None,
                    complete=bool(member.get("complete", False)),
                    board=board,
                    symbol=member.get("symbol"),
                )
            )
    out.sort(key=lambda o: o.t_ingest_unix)
    return out


def crime_screen(mint: str) -> dict[str, Any] | None:
    """The offline crime cohort's row for this mint, if it has one. A LOOKUP, not a fit.

    ``studies/crime_signatures.py`` builds its cohort on hourly candles with a 24 h
    breakdown lag, so it can never speak about a coin the operator is looking at right now.
    What it CAN say is that a mint has been through the labelling pipeline before and what
    its peak was -- which for a coin the operator is about to scalp is worth exactly one
    line. Anything more would be a live crime screen, and there isn't one; the live reading
    is the GHOST_TOWN geometry, computed from depth and staleness in :func:`readout`.
    """
    path = STATE / "crime" / "labels.jsonl"
    needle = mint.encode()
    for raw in reversed(_read_tail(path, 4 * 1024 * 1024)):
        if needle not in raw:
            continue
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and row.get("mint") == mint:
            return row
    return None


def _with_deadline(jobs: dict[str, Callable[[], Any]], deadline_s: float) -> dict[str, Any]:
    """Run every job on its own thread; whatever has not landed by the deadline is absent.

    Threads rather than a process pool because every job here is IO -- a socket, a SQLite
    copy, a file read -- and the GIL is released for all three. A job that overruns is
    abandoned, not awaited: the executor is left to reap it and the CLI exits regardless,
    because a hunch that took four seconds to print is a hunch the operator stopped typing.
    """
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=max(1, len(jobs)), thread_name_prefix="readout")
    futures: dict[str, Future[Any]] = {name: pool.submit(job) for name, job in jobs.items()}
    out: dict[str, Any] = {}
    for name, future in futures.items():
        remaining = deadline_s - (time.monotonic() - started)
        try:
            out[name] = future.result(timeout=max(0.0, remaining))
        except Exception:
            out[name] = None
    pool.shutdown(wait=False, cancel_futures=True)
    return out


def readout(
    mint: str,
    *,
    clip_lamports: int,
    now: float | None = None,
    symbol: str | None = None,
    deadline_s: float = READOUT_DEADLINE_S,
    friction: Friction | None = None,
) -> Readout:
    """The instrument, in one call, under a hard deadline.

    Order of preference for the price-carrying fields: the LIVE vendor poll if it lands, the
    boards tape's freshest sighting otherwise. Both are recorded either way -- the tape is
    what the desk itself will mark against, and if the two disagree the operator should be
    looking at the one the book will use, not the prettier one.
    """
    now = time.time() if now is None else now
    started = time.monotonic()
    friction = friction or Friction()
    out = Readout(mint=mint, symbol=symbol, t_unix=now, clip_lamports=clip_lamports)

    def _poll_mint() -> Any:
        from shitcoims_scalper.feed import poll_mint

        return poll_mint(mint)

    def _callout() -> Any:
        from shitcoims_scalper.feed import poll_callouts

        return [c for c in poll_callouts(max_age_s=FLOW_WINDOW_S) if c.mint == mint]

    results = _with_deadline(
        {
            "snap": _poll_mint,
            "path": lambda: board_price_path(mint, now),
            "callouts": _callout,
            "crime": lambda: crime_screen(mint),
        },
        deadline_s,
    )

    path: list[MintObservation] = results.get("path") or []
    snap = results.get("snap")
    latest = path[-1] if path else None

    if latest is not None:
        out.symbol = out.symbol or latest.symbol
        out.board = latest.board
        out.usd_market_cap = latest.usd_market_cap or None
        out.drawdown_from_ath = latest.drawdown_from_ath if latest.drawdown_known else None
        if latest.drawdown_from_ath == DRAWDOWN_UNKNOWN:
            out.absent["drawdown_from_ath"] = "vendor served no all-time high for this coin"
    elif results.get("path") is None:
        out.absent["boards"] = "boards tape unreadable or past the deadline"
    else:
        out.absent["boards"] = "no sighting of this mint on the boards in the last hour"
        out.absent.setdefault("drawdown_from_ath", "only the boards vendor serves an ATH")

    # Reserves: live poll wins, tape is the fallback, and one of them must land or the
    # depth block is absent rather than assumed.
    vsol = vtok = None
    if snap is not None:
        vsol, vtok = snap.vsol_lamports, snap.vtok_raw
        out.age_s = now - snap.created_unix if snap.created_unix else None
        out.trade_recency_s = now - snap.last_trade_unix if snap.last_trade_unix else None
        out.complete = snap.complete
    elif latest is not None:
        vsol, vtok = latest.vsol_lamports, latest.vtok_raw
        out.age_s = now - latest.created_unix if latest.created_unix else None
        out.trade_recency_s = now - latest.last_trade_unix if latest.last_trade_unix else None
        out.complete = latest.complete
        out.absent["live_poll"] = "vendor poll missed the deadline; reserves are from the tape"
    else:
        out.absent["reserves"] = "no live poll and no tape sighting; depth is unmeasured"
    if out.trade_recency_s is None:
        out.absent.setdefault("trade_recency_s", "no last-trade stamp on this coin")
    if out.age_s is None:
        out.absent.setdefault("age_s", "no creation stamp on this coin")

    take_bps = friction.take_bps_for(None)
    if vsol and vtok:
        out.price_sol = vsol / vtok
        out.sol_in_curve = vsol / 1e9
        out.own_exit_impact = ghost_town_impact(clip_lamports, vsol)
        cost = friction.round_trip(clip_lamports, vsol, take_bps=take_bps)
        out.round_trip_cost = cost if math.isfinite(cost) else None

    # Flow and wiggle quality, measured with the DESK's own estimator over the desk's own
    # observation path -- not a second one written for the CLI, or "wiggle" would mean one
    # thing here and another on the book.
    if path:
        watch = WiggleWatch()
        for obs in path:
            watch.observe(obs.price, obs.t_ingest_unix, basis=obs.pool_label)
        out.observations = watch.observations
        out.obs_per_min = watch.observations_per_minute()
        out.two_sided_frac = watch.two_sided_frac() if watch.observations >= 3 else None
        if out.two_sided_frac is None:
            out.absent["two_sided_frac"] = f"{watch.observations} sightings; needs 3"
        # The zigzag threshold is the coin's OWN round-trip cost, so the reference has to
        # be an observation with real reserves -- the freshest one on the tape.
        features = watch.features(friction=friction, obs=path[-1], clip_lamports=clip_lamports)
        out.wiggle_n = int(features["wiggle_n"])
        out.wiggle_amp = features["wiggle_amp"]
        stamps = sorted({o.last_trade_unix for o in path if o.last_trade_unix is not None})
        span = path[-1].t_ingest_unix - path[0].t_ingest_unix
        if span > 0 and stamps:
            # A LOWER BOUND: we only learn a trade happened when we happen to sample after
            # it, so a coin trading faster than the boards poll reads as the poll rate.
            out.trade_marks_per_hour = len(stamps) * 3600.0 / span
    else:
        out.absent.setdefault("flow", "no observation path; flow and wiggle are unmeasured")

    calls = results.get("callouts")
    if calls:
        newest = max(calls, key=lambda c: c.t_post_unix)
        out.callout_last_s = now - newest.t_post_unix
        out.callout_kind = newest.kind
        out.callout_author = newest.author
    elif calls is None:
        out.absent["callouts"] = "intelligence store unreadable or past the deadline"

    crime = results.get("crime")
    if isinstance(crime, dict):
        out.crime_symbol = crime.get("symbol")
        out.crime_peak_mcap = crime.get("peak_mcap")
        out.crime_drawdown = crime.get("drawdown_from_peak")

    # The GHOST_TOWN reading, live: thin AND stale is the archetype, and our own exit
    # against the bracket is what makes "thin" a number rather than a feeling.
    policy = WigglePolicy(seed=0)
    mid = {name: (lo + hi) / 2.0 for name, (lo, hi) in policy.ranges.items()}
    features = {
        "drawdown_known": 1.0 if out.drawdown_from_ath is not None else 0.0,
        "drawdown_from_ath": out.drawdown_from_ath if out.drawdown_from_ath is not None else -1.0,
        "sol_in_curve": out.sol_in_curve if out.sol_in_curve is not None else 0.0,
        "trade_recency_s": out.trade_recency_s if out.trade_recency_s is not None else 1e9,
        "own_exit_impact": out.own_exit_impact if out.own_exit_impact is not None else 1.0,
        "wiggle_observations": float(out.observations or 0),
        "wiggle_obs_per_min": out.obs_per_min or 0.0,
        "wiggle_two_sided_frac": out.two_sided_frac or 0.0,
        "callout_n_60m": float(len(calls) if calls else 0),
    }
    out.gate_legs = policy.legs(features, mid)
    if out.sol_in_curve is not None:
        out.ghost_town = not (out.gate_legs.get("depth", True) and out.gate_legs.get("recently_traded", True))

    out.elapsed_s = time.monotonic() - started
    return out


# ---------------------------------------------------------------------- rendering


def _n(value: float | None, spec: str, absent: str = "—") -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return absent
    return format(value, spec)


def _dur(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.1f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def render_readout(out: Readout, resolution: Resolution | None = None) -> str:
    """The block the operator reads while the position is already opening."""
    name = out.symbol or (out.crime_symbol or "")
    head = f"  {name or out.mint[:8]}  {out.mint}"
    lines = [head]
    if resolution is not None and resolution.chosen is not None:
        via = f"{resolution.matched_on} via {resolution.chosen.source}"
        if resolution.chosen.detail:
            via += f" ({resolution.chosen.detail})"
        if resolution.suppressed:
            via += f"   [{len(resolution.suppressed)} other mint(s) share this name — see --list]"
        lines.append(f"  resolved: {via}")
        if resolution.reason:
            lines.append(f"  note: {resolution.reason}")

    lines += [
        "",
        f"  price      {_n(out.price_sol, '.3e')} SOL/token"
        f"      mcap  ${_n(out.usd_market_cap, ',.0f')}"
        f"      board {out.board or '—'}",
        f"  drawdown   {_n(out.drawdown_from_ath, '.1%')} from ATH"
        f"      age   {_dur(out.age_s)}"
        f"      last trade {_dur(out.trade_recency_s)} ago",
        f"  depth      {_n(out.sol_in_curve, '.1f')} SOL"
        f"      own exit impact {_n(out.own_exit_impact, '.2%')} at "
        f"{out.clip_lamports / 1e9:.2f} SOL"
        f"      round trip {_n(out.round_trip_cost, '.2%')}",
        f"  flow       {_n(out.trade_marks_per_hour, '.0f')} trade marks/h"
        f"      two-sided {_n(out.two_sided_frac, '.0%')}"
        f"      seen {out.observations if out.observations is not None else '—'}x"
        f" ({_n(out.obs_per_min, '.1f')}/min)",
        f"  wiggle     {out.wiggle_n if out.wiggle_n is not None else '—'} swings"
        f"      amplitude {_n(out.wiggle_amp, '.1%')} (log, at this coin's own round-trip cost)",
    ]
    callout = (
        f"{_dur(out.callout_last_s)} ago ({out.callout_kind}"
        + (f" @{out.callout_author}" if out.callout_author else "")
        + ")"
        if out.callout_last_s is not None
        else "none in the last hour"
    )
    lines.append(f"  callout    {callout}")
    if out.crime_peak_mcap:
        lines.append(
            f"  screened   in the crime cohort as {out.crime_symbol or '?'}:"
            f" peak ${out.crime_peak_mcap:,.0f}, {_n(out.crime_drawdown, '.0%')} off it"
            "   (24h-lagged; not a live verdict)"
        )
    if out.complete:
        lines.append("  GRADUATED  this mint has left the bonding curve; the desk marks on the curve")

    vetoes = [k for k, ok in out.gate_legs.items() if not ok]
    if vetoes:
        lines.append(
            f"  gates      would veto: {', '.join(sorted(vetoes))}"
            "   (advisory, at the middle of the jitter box; the desk draws its own and"
            " gates NOTHING here)"
        )
    else:
        lines.append("  gates      the wiggle rule would have taken this one too")
    if out.absent:
        lines.append("  absent     " + "; ".join(f"{k}: {v}" for k, v in sorted(out.absent.items())))
    lines.append(f"  ({out.elapsed_s * 1000:.0f} ms)")
    return "\n".join(lines)
