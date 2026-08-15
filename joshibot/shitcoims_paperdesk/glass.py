"""The hunch API: what the glass talks to. Loopback only, and it cannot sign anything.

WHY THIS IS A SEPARATE PROCESS FROM THE SENTINEL'S SERVER
---------------------------------------------------------
``shitcoims_sentinel`` holds keys and constructs sell transactions. This server exists so
the operator can point at a coin and say "that one", and it must therefore be running
whenever they are looking at the screen -- which is not the same availability question, and
must never become the same blast radius. So it is its own process, on its own port, in a
package that imports nothing from the sentinel. It:

* reads the collectors' tapes (boards, firehose, callouts) and the desk's own ledger;
* appends to ``state/hunches.jsonl``;
* and that is the complete list of things it can do. There is no key, no RPC client, no
  broadcast path, and no write to anything the sentinel reads.

The glass holds display logic only, per the dashboard-rebuild boundary: it renders what
these endpoints serve and posts the operator's gesture back. Every measurement on a card is
computed HERE, by the same code the paper desk marks positions with, because a number the
browser derived for itself is a number that will disagree with the book by next week.

THE INDEX IS INCREMENTAL, BECAUSE THE CARD LIST IS POLLED
---------------------------------------------------------
The boards tape runs ~177 MB/day. A card list that re-read it per request would take
seconds and would be re-deriving, every time, a rolling state the desk already knows how to
maintain: :class:`CoinIndex` therefore keeps a tail offset and a bounded per-mint
:class:`~shitcoims_paperdesk.wiggle.WiggleWatch`, advances it on each request, and answers
from memory. Cold start pays for one bounded tail read; every request after it pays for the
delta.

WHAT THE CARDS DO NOT DO
------------------------
No card ever renders an absence as a zero -- every optional figure is ``null`` with a reason
in ``absent``, and the glass has a four-state renderer waiting for exactly that. And nothing
here gates: the entry gates are evaluated per card and shipped as ``gates_would_veto`` so
the operator can SEE which rule disagrees with them at the moment they overrule it.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from shitcoims_paperdesk.feeds import DRAWDOWN_UNKNOWN, STATE, MintObservation
from shitcoims_paperdesk.friction import Friction
from shitcoims_paperdesk.hunch import (
    HUNCH_PATH,
    KIND_CLAIMS,
    Hunch,
    append_hunch,
    default_horizon_s,
    iso,
    new_hunch_id,
    read_hunches,
)
from shitcoims_paperdesk.ledger import LEDGER_DIR
from shitcoims_paperdesk.policy import WigglePolicy
from shitcoims_paperdesk.readout import (
    board_path_for,
    held_candidates,
    is_mint,
    readout,
    resolve,
)
from shitcoims_paperdesk.wiggle import WiggleWatch, ghost_town_impact

__all__ = ["GLASS_PORT", "CoinIndex", "build_app", "main"]

#: Deliberately NOT 8787: that port is the sentinel's, and a glass that can reach one API is
#: a glass that must not accidentally reach the other. Not 8788 or 8799 either -- both are
#: taken by ``intel.py`` on this box, and a capture surface that silently binds nothing (or
#: worse, answers from a different daemon) is a capture surface that loses hunches.
GLASS_PORT: Final[int] = 8790

#: The operator's clip, and the size every impact figure on a card is computed AT. An impact
#: number without a size is not a number.
DEFAULT_CLIP_LAMPORTS: Final[int] = 100_000_000

#: Cold-start window over the boards tape: roughly the last hour. Enough for the wiggle
#: statistics the cards show, bounded so the first request is a second rather than a minute.
COLD_START_BYTES: Final[int] = 8 * 1024 * 1024

#: Mints held in the index. The boards carry ~15,300 distinct mints a day; this is a working
#: set of what is live now, evicted oldest-first, exactly as the wiggle book's watch is.
INDEX_CAPACITY: Final[int] = 3_000

#: How stale a card may be before the explorer stops offering it as "live". Two boards poll
#: cycles: the collector visits five boards every ~30 s.
CARD_FRESH_S: Final[float] = 180.0


@dataclass
class Tracked:
    """One coin in the index: its freshest row, and the price path we have watched."""

    obs: MintObservation
    watch: WiggleWatch = field(default_factory=WiggleWatch)
    name: str | None = None
    first_seen_unix: float = 0.0
    sightings: int = 0
    source: str = "boards"
    board: str | None = None


class CoinIndex:
    """A live, incremental view of every coin the collectors are currently showing us.

    Reads the same files the desk reads, with the same tailing discipline (offset kept,
    partial final line buffered, truncation handled), and maintains one
    :class:`~shitcoims_paperdesk.wiggle.WiggleWatch` per mint so that "is this thing actually
    oscillating" is answered with the desk's own estimator rather than a second one written
    for the UI.
    """

    def __init__(
        self, *, capacity: int = INDEX_CAPACITY, clip_lamports: int = DEFAULT_CLIP_LAMPORTS
    ) -> None:
        self.capacity = capacity
        self.clip_lamports = clip_lamports
        self.friction = Friction()
        self.coins: OrderedDict[str, Tracked] = OrderedDict()
        self._boards_path: Path | None = None
        self._boards_offset = 0
        self._boards_partial = ""
        self._fire_path: Path | None = None
        self._fire_offset = 0
        self._fire_partial = ""
        self.refreshed_unix = 0.0
        self.rows_read = 0

    # ------------------------------------------------------------------ tailing

    def _advance(
        self, path: Path, offset: int, partial: str, cold: int
    ) -> tuple[int, str, list[dict[str, Any]]]:
        try:
            size = path.stat().st_size
        except OSError:
            return offset, partial, []
        if offset == 0 and partial == "":
            offset = max(0, size - cold)
        if size < offset:
            offset, partial = 0, ""
        if size <= offset:
            return offset, partial, []
        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(size - offset)
        except OSError:
            return offset, partial, []
        started_mid_row = offset > 0 and partial == ""
        offset += len(chunk)
        text = partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        partial = lines.pop()
        if started_mid_row and lines:
            lines.pop(0)  # the cold-start window opened inside a row
        rows: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return offset, partial, rows

    def refresh(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        boards = board_path_for(now)
        if boards != self._boards_path:
            self._boards_path, self._boards_offset, self._boards_partial = boards, 0, ""
        self._boards_offset, self._boards_partial, rows = self._advance(
            boards, self._boards_offset, self._boards_partial, COLD_START_BYTES
        )
        for row in rows:
            self.rows_read += 1
            kind = row.get("kind")
            board = row.get("board")
            if kind == "board_snapshot":
                members = [m for m in (row.get("members") or ()) if isinstance(m, dict)]
            elif kind == "board_entry":
                members = [row]
            else:
                continue
            for member in members:
                self._record_board(member, board)

        fire = STATE / "firehose" / "new_token" / f"{datetime.fromtimestamp(now, tz=UTC):%Y-%m-%d}.jsonl"
        if fire != self._fire_path:
            self._fire_path, self._fire_offset, self._fire_partial = fire, 0, ""
        self._fire_offset, self._fire_partial, rows = self._advance(
            fire, self._fire_offset, self._fire_partial, 1024 * 1024
        )
        for row in rows:
            if row.get("kind") != "new_token":
                continue
            self._record_launch(row)

        while len(self.coins) > self.capacity:
            self.coins.popitem(last=False)
        self.refreshed_unix = now

    def _record_board(self, member: dict[str, Any], board: Any) -> None:
        mint = member.get("mint")
        vsol, vtok = member.get("virtual_sol_reserves"), member.get("virtual_token_reserves")
        stamp = float(member.get("t_ingest") or 0.0)
        if not isinstance(mint, str) or not vsol or not vtok or stamp <= 0:
            return
        last_trade = member.get("last_trade_unix")
        obs = MintObservation(
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
            board=str(board) if board else None,
            symbol=member.get("symbol"),
        )
        tracked = self.coins.get(mint)
        if tracked is None:
            tracked = self.coins[mint] = Tracked(obs=obs, first_seen_unix=stamp)
        elif obs.t_ingest_unix < tracked.obs.t_ingest_unix:
            return
        tracked.obs = obs
        tracked.board = obs.board
        tracked.source = "boards"
        tracked.sightings += 1
        tracked.watch.observe(obs.price, obs.t_ingest_unix, basis=obs.pool_label)
        self.coins.move_to_end(mint)

    def _record_launch(self, row: dict[str, Any]) -> None:
        mint = row.get("mint")
        payload = row.get("payload")
        if not isinstance(mint, str) or not isinstance(payload, dict):
            return
        tracked = self.coins.get(mint)
        if tracked is None:
            return  # launches without a board sighting are not explorable cards; they are noise
        tracked.name = payload.get("name") or tracked.name

    # ------------------------------------------------------------------ cards

    def card(self, mint: str, *, now: float, hunched: dict[str, Any] | None, held: bool) -> dict[str, Any]:
        tracked = self.coins.get(mint)
        if tracked is None:
            return {"mint": mint, "absent": {"card": "no board sighting in the index window"}}
        obs = tracked.obs
        watch = tracked.watch
        absent: dict[str, str] = {}

        drawdown = obs.drawdown_from_ath if obs.drawdown_known else None
        if drawdown is None:
            absent["drawdown_from_ath"] = "the vendor served no all-time high for this coin"
        two_sided = watch.two_sided_frac() if watch.observations >= 3 else None
        if two_sided is None:
            absent["two_sided_frac"] = f"seen {watch.observations}x; two-sidedness needs 3"
        features = watch.features(friction=self.friction, obs=obs, clip_lamports=self.clip_lamports)

        policy = WigglePolicy(seed=0)
        mid = {name: (lo + hi) / 2.0 for name, (lo, hi) in policy.ranges.items()}
        gate_features = {
            **obs.features(),
            **features,
            "callout_n_60m": 0.0,
        }
        legs = policy.legs(gate_features, mid)
        impact = ghost_town_impact(self.clip_lamports, obs.vsol_lamports)

        return {
            "mint": mint,
            "symbol": obs.symbol,
            "name": tracked.name,
            "board": tracked.board,
            "source": tracked.source,
            "t_seen": iso(obs.t_ingest_unix),
            "t_seen_unix": obs.t_ingest_unix,
            "seconds_since_seen": now - obs.t_ingest_unix,
            "fresh": (now - obs.t_ingest_unix) <= CARD_FRESH_S,
            "price_sol": obs.price,
            "usd_market_cap": obs.usd_market_cap or None,
            "ath_market_cap": obs.ath_market_cap or None,
            "drawdown_from_ath": drawdown,
            "age_s": (obs.t_ingest_unix - obs.created_unix) if obs.created_unix else None,
            "trade_recency_s": (
                (obs.t_ingest_unix - obs.last_trade_unix) if obs.last_trade_unix else None
            ),
            "sol_in_curve": obs.sol_in_curve,
            "complete": obs.complete,
            "sightings": watch.observations,
            "obs_per_min": watch.observations_per_minute(),
            "two_sided_frac": two_sided,
            "wiggle_n": int(features["wiggle_n"]),
            "wiggle_amp": features["wiggle_amp"],
            "own_exit_impact": impact,
            "round_trip_cost": features["round_trip_cost"],
            "clip_lamports": self.clip_lamports,
            # The gates, evaluated and INERT. `ghost_town` is the one the capture surface
            # must shout about: thin AND stale is the archetype with no exit at the quote.
            "gates": legs,
            "gates_would_veto": sorted(k for k, ok in legs.items() if not ok),
            "ghost_town": not (legs.get("depth", True) and legs.get("recently_traded", True)),
            "held": held,
            "hunched": hunched,
            "absent": absent,
        }


# ---------------------------------------------------------------------- ledger joins


def _ledger_paths(days: int = 2) -> list[Path]:
    return sorted(LEDGER_DIR.glob("ledger-*.jsonl"))[-days:]


def hunch_outcomes(days: int = 2) -> dict[str, dict[str, Any]]:
    """Join each hunch id to what the OPERATOR book did with it, off the ledger.

    Scans only the recent ledger days: the tape is the durable record of the gesture and
    this is the desk's answer to it, which is only interesting while it is recent. A hunch
    with no answer here is a hunch the desk has not acted on yet -- reported as ``pending``
    rather than as a zero-outcome row.
    """
    out: dict[str, dict[str, Any]] = {}
    by_decision: dict[str, str] = {}
    for path in _ledger_paths(days):
        try:
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict) or row.get("book") != "operator":
                        continue
                    kind = row.get("row")
                    hunch_id = row.get("hunch_id")
                    if kind in {"hunch", "expectation"} and isinstance(hunch_id, str):
                        entry = out.setdefault(hunch_id, {"hunch_id": hunch_id})
                        entry["state"] = row.get("detail")
                        entry["at"] = row.get("t_ingest")
                        if row.get("censor_reason"):
                            entry["censor_reason"] = row.get("censor_reason")
                        for key in ("outcome", "brier", "change", "realised_range"):
                            if row.get(key) is not None:
                                entry[key] = row.get(key)
                    elif kind == "decision" and isinstance(hunch_id, str):
                        entry = out.setdefault(hunch_id, {"hunch_id": hunch_id})
                        entry["state"] = "decided"
                        entry["decision_id"] = row.get("decision_id")
                        entry["gates_would_veto"] = row.get("gates_would_veto") or []
                        entry["ghost_town"] = bool(row.get("ghost_town"))
                        if isinstance(row.get("decision_id"), str):
                            by_decision[row["decision_id"]] = hunch_id
                    elif kind == "close":
                        owner = by_decision.get(str(row.get("decision_id")))
                        if owner is None:
                            continue
                        entry = out.setdefault(owner, {"hunch_id": owner})
                        entry["state"] = "closed"
                        entry["net_return"] = row.get("net_return")
                        entry["net_return_pessimistic"] = row.get("net_return_pessimistic")
                        entry["pnl_lamports"] = row.get("pnl_lamports")
                        entry["exit_reason"] = row.get("exit_reason")
                        entry["holding_seconds"] = row.get("holding_seconds")
                        entry["censored"] = row.get("censored")
        except OSError:
            continue
    return out


def desk_health() -> dict[str, Any]:
    """Is the desk alive, and what are the five books doing? From its own heartbeat row."""
    last: dict[str, Any] | None = None
    for path in _ledger_paths(1):
        try:
            with path.open() as fh:
                for line in fh:
                    if '"row":"heartbeat"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict) and row.get("row") == "heartbeat" and row.get("books"):
                        last = row
        except OSError:
            continue
    if last is None:
        return {"alive": False, "reason": "no heartbeat row in the ledger"}
    age = time.time() - float(last.get("t_ingest_unix") or 0.0)
    return {
        # The desk beats once a minute; five minutes of silence is a dead daemon, and the
        # glass renders that rather than quietly serving its last state as current.
        "alive": age < 300.0,
        "seconds_since_heartbeat": age,
        "at": last.get("t_ingest"),
        "run_id": last.get("run_id"),
        "books": last.get("books"),
        "sources": last.get("sources"),
        "hunches": last.get("hunches"),
    }


# ---------------------------------------------------------------------- the app


def build_app(index: CoinIndex | None = None) -> Any:
    from fastapi import FastAPI, HTTPException, Query

    app = FastAPI(title="shitcoims hunch", docs_url=None, redoc_url=None)
    coins = index or CoinIndex()

    def _hunched_by_mint(now: float) -> dict[str, dict[str, Any]]:
        """The "you already called this one" badge. Reads the TAPE only -- a few kB.

        Kept separate from :func:`hunch_outcomes` deliberately. The card list is POLLED
        every few seconds, and joining every card to the desk's ledger to render one badge
        cost a full scan of a 54 MB/day file per request -- measured at 1.5 s, i.e. a
        quarter of the poll interval spent re-reading a day of rows to answer a question the
        4 kB tape already answers. The outcome join is what ``/hunch/tape`` is for.
        """
        by_mint: dict[str, dict[str, Any]] = {}
        for h in read_hunches():
            entry = by_mint.setdefault(h.mint, {"n": 0, "last_kind": None, "last_at": None})
            entry["n"] += 1
            entry["last_kind"] = h.kind
            entry["last_at"] = iso(h.t_gesture_unix)
            entry["last_seconds"] = now - h.t_gesture_unix
        return by_mint

    #: Memoised outcome join: ``(computed_at, outcomes)``. The scan is unavoidable for the
    #: tape view (the outcome of a hunch is a fact about the DESK, and lives in its ledger),
    #: so it is amortised instead -- a positions-and-P&L view is not more useful for being
    #: five seconds fresher, and the desk's own writes are append-only anyway.
    outcome_cache: dict[str, Any] = {"at": 0.0, "value": {}}
    OUTCOME_TTL_S = 15.0

    def _outcomes(now: float) -> dict[str, dict[str, Any]]:
        if now - float(outcome_cache["at"]) > OUTCOME_TTL_S:
            outcome_cache["value"] = hunch_outcomes()
            outcome_cache["at"] = now
        return outcome_cache["value"]

    @app.get("/hunch/health")
    def health() -> dict[str, Any]:
        now = time.time()
        coins.refresh(now)
        tape = read_hunches()
        return {
            "generated_at": iso(now),
            "desk": desk_health(),
            "index": {
                "coins": len(coins.coins),
                "rows_read": coins.rows_read,
                "refreshed_at": iso(coins.refreshed_unix) if coins.refreshed_unix else None,
            },
            "hunches": {
                "total": len(tape),
                "last_at": iso(tape[-1].t_gesture_unix) if tape else None,
                "path": str(HUNCH_PATH),
            },
            # Said on every response, because the glass renders it as a standing pill: this
            # process holds no key and has no broadcast path.
            "can_execute": False,
        }

    @app.get("/hunch/coins")
    def list_coins(
        limit: int = Query(60, ge=1, le=300),
        sort: str = Query("recent"),
        board: str | None = Query(None),
        fresh_only: bool = Query(True),
    ) -> dict[str, Any]:
        now = time.time()
        coins.refresh(now)
        hunched = _hunched_by_mint(now)
        held = set(held_candidates(now))
        rows: list[dict[str, Any]] = []
        for mint in list(coins.coins):
            card = coins.card(mint, now=now, hunched=hunched.get(mint), held=mint in held)
            if card.get("absent", {}).get("card"):
                continue
            if fresh_only and not card["fresh"]:
                continue
            if board and card.get("board") != board:
                continue
            rows.append(card)
        keys = {
            "recent": lambda c: -(c["t_seen_unix"] or 0),
            # The wiggle book's own candidate ordering, offered as a lens rather than a
            # ranking: it is the RULE's taste, and this surface exists to be disagreed with.
            "wiggle": lambda c: -((c.get("two_sided_frac") or 0.0) * 100 + (c.get("wiggle_n") or 0)),
            "drawdown": lambda c: -(c.get("drawdown_from_ath") or -1.0),
            "mcap": lambda c: -(c.get("usd_market_cap") or 0.0),
            "age": lambda c: (c.get("age_s") if c.get("age_s") is not None else 1e12),
        }
        rows.sort(key=keys.get(sort, keys["recent"]))
        return {
            "generated_at": iso(now),
            "sort": sort,
            "n_indexed": len(coins.coins),
            "items": rows[:limit],
        }

    @app.get("/hunch/resolve")
    def resolve_query(q: str = Query(..., min_length=1)) -> dict[str, Any]:
        """Mint, prefix or ticker -> one mint, or the candidate list and a refusal.

        The clipboard bridge calls this on whatever the operator copied. It never acts; a
        resolution is a lookup, and the only thing that opens a position on this desk is a
        POST the operator's own click produced.
        """
        now = time.time()
        found = resolve(q, now=now)
        return {
            "generated_at": iso(now),
            "query": q,
            "mint": found.mint,
            "matched_on": found.matched_on,
            "reason": found.reason,
            "is_address": is_mint(q.strip()),
            "candidates": [
                {
                    "mint": c.mint,
                    "symbol": c.symbol,
                    "name": c.name,
                    "source": c.source,
                    "detail": c.detail,
                    "seconds_since_seen": now - c.t_seen_unix if c.t_seen_unix else None,
                }
                for c in found.candidates
            ],
            "suppressed": [{"mint": c.mint, "source": c.source} for c in found.suppressed],
        }

    @app.get("/hunch/readout/{mint}")
    def one_readout(mint: str) -> dict[str, Any]:
        if not is_mint(mint):
            raise HTTPException(status_code=400, detail="not a 32-byte base58 address")
        now = time.time()
        coins.refresh(now)
        hunched = _hunched_by_mint(now)
        held = set(held_candidates(now))
        card = coins.card(mint, now=now, hunched=hunched.get(mint), held=mint in held)
        full = readout(mint, clip_lamports=coins.clip_lamports, now=now)
        return {"generated_at": iso(now), "card": card, "readout": full.to_json()}

    @app.post("/hunch")
    def capture(body: dict[str, Any]) -> dict[str, Any]:
        """One click. Appends the gesture, warns loudly, and never refuses on a gate.

        Ordering is the contract: the row is fsynced to the tape BEFORE anything else
        happens, and every figure in the response comes from state already in memory. A
        capture that waited on a vendor would be a capture that can be lost by a vendor.
        """
        now = time.time()
        mint = str(body.get("mint") or "").strip()
        if not is_mint(mint):
            raise HTTPException(status_code=400, detail="mint is not a 32-byte base58 address")
        kind = str(body.get("kind") or "wiggle")
        if kind not in KIND_CLAIMS:
            raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(KIND_CLAIMS)}")
        coins.refresh(now)
        held = set(held_candidates(now))
        card = coins.card(mint, now=now, hunched=None, held=mint in held)

        note = str(body.get("note") or "")
        surface = str(body.get("surface") or "glass")
        # ``x or default`` is wrong for every NUMBER the operator can send, and quietly so:
        # a declared confidence of 0.0 is a real statement ("certain this is wrong") and
        # ``0.0 or 0.6`` rewrites it as 0.6 before the range check can refuse it. The same
        # trap on ``size_sol`` turns an explicit 0 into a full clip. Absent and zero are
        # different everywhere on this desk, including in a request body.
        confidence = float(body["confidence"]) if body.get("confidence") is not None else 0.6
        if not 0.0 < confidence < 1.0:
            raise HTTPException(status_code=400, detail="confidence must be in (0, 1)")
        size_sol = float(body["size_sol"]) if body.get("size_sol") is not None else 0.1
        if size_sol <= 0:
            raise HTTPException(status_code=400, detail="size_sol must be positive")
        size_lamports = int(size_sol * 1e9)
        horizon = body.get("horizon_s")
        horizon_s = float(horizon) if horizon is not None else default_horizon_s(kind)
        if horizon_s is not None and horizon_s <= 0:
            raise HTTPException(status_code=400, detail="horizon_s must be positive")

        symbol = card.get("symbol") or body.get("symbol")
        hunch = Hunch(
            hunch_id=new_hunch_id(mint, now),
            run_id=f"glass-{int(now)}",
            mint=mint,
            symbol=symbol,
            kind=kind,
            claim=KIND_CLAIMS[kind],
            # The VERBATIM utterance. On a click with no note that is the empty string, and
            # the empty string is honest: the operator said nothing, they pointed. The
            # context below records what pointing meant here, and is never merged into this
            # field -- a reconstructed utterance in the utterance slot would poison the one
            # corpus this whole design exists to build.
            utterance=note,
            confidence=confidence,
            horizon_s=horizon_s,
            size_lamports=size_lamports,
            t_gesture_unix=float(body.get("t_gesture_unix") or now),
            t_ingest_unix=now,
            resolution={"query": body.get("query") or mint, "matched_on": "mint", "source": surface},
            evidence={
                # What the machine could see at the instant of the click, server-side.
                "card": card,
                # What the OPERATOR could see, as declared by the surface they clicked on.
                # Kept in its own key and labelled, because client-declared context and
                # server-measured evidence are two different kinds of fact and this repo
                # does not sum measured with attested.
                "surface": {"name": surface, "declared_by": "glass", **(body.get("context") or {})},
            },
        )
        append_hunch(hunch)

        warnings: list[str] = []
        if card.get("ghost_town"):
            warnings.append(
                "GHOST TOWN: this coin is thin and/or has not traded recently. Your own exit "
                f"moves the price {(card.get('own_exit_impact') or 0) * 100:.2f}% at "
                f"{size_lamports / 1e9:.2f} SOL. RESULT_crime_signatures §7.1: at this depth "
                "there may be no exit at the quoted price at all. Your call stands; the desk "
                "is opening the position and tagging it."
            )
        if card.get("complete"):
            warnings.append(
                "This mint has graduated off the bonding curve. The desk marks on the curve, "
                "so the position may resolve as GRADUATED rather than on its clock."
            )
        vetoes = card.get("gates_would_veto") or []
        if vetoes:
            warnings.append(
                f"the wiggle rule would have refused this entry on: {', '.join(vetoes)}. "
                "Logged, not enforced."
            )
        if kind != "wiggle":
            warnings.append(
                f"{kind} is a watch-only claim: no position opens. It is scored at its horizon "
                f"({(horizon_s or 0) / 60:.0f} min) and the falsifier alerts if it breaks first."
            )
        return {
            "ok": True,
            "hunch_id": hunch.hunch_id,
            "recorded_at": iso(now),
            "hunch": hunch.to_json(),
            "card": card,
            "warnings": warnings,
            # The desk picks this up on its next cycle (3 s) and arms it on the first
            # observation after that. Said out loud so the glass can show the state machine
            # rather than implying the fill already happened.
            "next": "the desk arms this on its next observation of the coin; the fill is the one after",
        }

    @app.get("/hunch/tape")
    def tape(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        now = time.time()
        rows = read_hunches()[-limit:]
        outcomes = _outcomes(now)
        return {
            "generated_at": iso(now),
            "items": [
                {
                    **h.to_json(),
                    "seconds_ago": now - h.t_gesture_unix,
                    "outcome": outcomes.get(h.hunch_id) or {"state": "pending"},
                }
                for h in reversed(rows)
            ],
        }

    @app.get("/hunch/report")
    def report() -> dict[str, Any]:
        from shitcoims_paperdesk.hunch_report import render_hunch_report

        return {"generated_at": iso(time.time()), "text": render_hunch_report()}

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperdesk-glass")
    parser.add_argument("--port", type=int, default=GLASS_PORT)
    # Loopback, always. There is no flag to widen it: "no public listener, ever" is the v1
    # posture and a host argument is how that posture gets lost at 2am.
    parser.add_argument("--warm", action="store_true", help="build the coin index before serving")
    args = parser.parse_args(argv)

    import uvicorn

    index = CoinIndex()
    if args.warm:
        index.refresh()
    uvicorn.run(build_app(index), host="127.0.0.1", port=args.port, log_level="warning")
    return 0
