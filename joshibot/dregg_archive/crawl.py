"""The incremental firehose walk, and the one derivation every callout surface shares.

HIGH-WATER MARK AND OVERLAP
---------------------------
Each cycle walks `/callout/recent` backwards from now until the page is older than
`since_ms = hwm - overlap`. The 30-minute overlap is not slack — it is the sighting
instrument: with a 10-minute cadence every callout is re-walked by roughly the next three
cycles, so a callout that VANISHES from a window it should be inside is observed absent
by multiple later fetches, which is exactly the evidence `deletion.py` requires. The
cursor is pump's keyset token (`{score, member}`), stable under insertion, so pages
partition the feed without skips or duplicates.

A walk that hits `max_pages` before reaching `since_ms` has a GAP, and the gap is
recorded (`notes` kind `walk_gap` with both bounds) rather than silently absorbed —
the high-water mark still advances, because refusing to advance would re-walk forever
without recovering rows the feed no longer serves.

DERIVATION
----------
`derive_callout_rows` is the only path from a fetched body to derived rows, used
identically by the firehose walk, the `callout_top` sweeps and the `callout_list` probes.
It takes the fetch id of retained bytes plus the rows parsed FROM those bytes, applies
the pumpsocial hygiene (on-curve wallets; quarantine counted, never dropped silently),
records the fetch's window — the deletion instrument — and upserts callouts/callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shitcoims_pumpsocial.client import PumpSocialClient, PumpSocialError, _callout_page
from shitcoims_pumpsocial.models import Quarantined, parse_native_callout

from .client import RecordingTransport
from .store import Store

RECENT_ROUTE = "callout_recent"
TOP_ROUTE = "callout_top"
LIST_ROUTE = "callout_list_mint"
CANDLES_ROUTE = "swap_candles"


@dataclass(slots=True)
class DeriveSummary:
    """What one fetch's body became: sightings, new callouts, and what was refused."""

    rows: int = 0
    sightings: int = 0
    new_callouts: list[tuple[str, str, str, int | None]] = field(default_factory=list)
    #: reason -> count. A quarantined row is a counted fact, not a smaller sample.
    quarantined: dict[str, int] = field(default_factory=dict)
    t_oldest_ms: int | None = None
    t_newest_ms: int | None = None


def _int_ms(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def derive_callout_rows(
    store: Store,
    *,
    fetch_id: int,
    route: str,
    rows: list[dict[str, Any]],
    scope: str | None,
    truncated: bool,
) -> DeriveSummary:
    out = DeriveSummary(rows=len(rows))
    for row in rows:
        t_event = _int_ms(row.get("createdAt"))
        if t_event is not None:
            out.t_oldest_ms = t_event if out.t_oldest_ms is None else min(out.t_oldest_ms, t_event)
            out.t_newest_ms = t_event if out.t_newest_ms is None else max(out.t_newest_ms, t_event)
        try:
            parsed = parse_native_callout(row, t_ingest="")  # clocks live on the fetch row
        except Quarantined as exc:
            out.quarantined[str(exc)] = out.quarantined.get(str(exc), 0) + 1
            continue
        if not store.record_sighting(parsed.callout_id, fetch_id, route):
            continue  # same callout twice in one body — the PK makes it one sighting
        out.sightings += 1
        is_new = store.upsert_callout(
            callout_id=parsed.callout_id,
            wallet=parsed.caller_wallet,
            mint=parsed.mint,
            t_event_ms=t_event,
            thesis=parsed.thesis or None,
            callout_price=parsed.callout_price,
            market_cap=parsed.market_cap,
            fetch_id=fetch_id,
            provider_multiple=parsed.multiple,
            provider_peak_t_ms=_int_ms(row.get("peakTimestamp")),
            username=parsed.username,
            x_username=parsed.x_username,
        )
        store.upsert_caller(
            wallet=parsed.caller_wallet,
            username=parsed.username,
            x_username=parsed.x_username,
            seen_ms=t_event,
        )
        if is_new:
            out.new_callouts.append((parsed.callout_id, parsed.mint, parsed.caller_wallet, t_event))
    # The window is recorded even when empty (NULL bounds): "this listing answered with
    # nothing" is the fact deletion inference needs to distinguish from "never asked".
    store.record_window(
        fetch_id,
        route=route,
        scope=scope,
        t_oldest_row_ms=out.t_oldest_ms,
        t_newest_row_ms=out.t_newest_ms,
        row_count=len(rows),
        truncated=truncated,
    )
    return out


@dataclass(slots=True)
class WalkSummary:
    pages: int = 0
    rows: int = 0
    sightings: int = 0
    new_callouts: list[tuple[str, str, str, int | None]] = field(default_factory=list)
    quarantined: dict[str, int] = field(default_factory=dict)
    newest_ms: int | None = None
    oldest_ms: int | None = None
    #: True when the walk got past `since_ms` (or exhausted the feed) — i.e. no gap.
    reached_since: bool = False
    truncated: str | None = None
    failed: str | None = None
    fetch_ids: list[int] = field(default_factory=list)


def walk_firehose(
    client: PumpSocialClient,
    recorder: RecordingTransport,
    store: Store,
    *,
    since_ms: int,
    limit: int,
    max_pages: int,
    guard,
) -> WalkSummary:
    """Walk the firehose back to `since_ms`, retaining every page and deriving from it.

    `guard` is called before each page (the budget's pre-flight); pages already fetched
    when it trips are already safe in the store — a budget stop mid-walk loses nothing
    that was paid for.
    """

    out = WalkSummary()
    token: str | None = None
    seen_tokens: set[str] = set()
    for page in range(max_pages):
        guard()
        recorder.route = RECENT_ROUTE
        try:
            rows, next_token, _prov = client.recent_callouts(limit=limit, page_token=token)
        except PumpSocialError as exc:
            out.failed = f"page{page}: {exc}"
            break
        fetch_id = recorder.last_fetch_id
        assert fetch_id is not None
        out.pages += 1
        out.fetch_ids.append(fetch_id)
        derived = derive_callout_rows(
            store,
            fetch_id=fetch_id,
            route=RECENT_ROUTE,
            rows=rows,
            scope=None,
            truncated=bool(next_token) or len(rows) >= limit,
        )
        out.rows += derived.rows
        out.sightings += derived.sightings
        out.new_callouts.extend(derived.new_callouts)
        for reason, n in derived.quarantined.items():
            out.quarantined[reason] = out.quarantined.get(reason, 0) + n
        if derived.t_newest_ms is not None:
            out.newest_ms = max(out.newest_ms or 0, derived.t_newest_ms)
        if derived.t_oldest_ms is not None:
            out.oldest_ms = (
                derived.t_oldest_ms if out.oldest_ms is None else min(out.oldest_ms, derived.t_oldest_ms)
            )
        if derived.t_oldest_ms is not None and derived.t_oldest_ms < since_ms:
            out.reached_since = True
            break
        if not next_token:
            # Feed exhausted (or a full page with no token, which is the API cutting us
            # off while looking exactly like completion — named, not trusted).
            if len(rows) >= limit:
                out.truncated = f"full_page_no_token@page{page}"
            else:
                out.reached_since = True
            break
        if next_token in seen_tokens:
            out.truncated = f"cursor_loop@page{page}"
            break
        seen_tokens.add(next_token)
        token = next_token
    else:
        out.truncated = "max_pages"
    return out


def candle_window(
    store: Store, *, fetch_id: int, mint: str, candles: list[dict[str, Any]]
) -> tuple[int | None, int | None, int]:
    """Record a candle fetch's coverage window so outcomes can find it without decompressing."""

    stamps = [t for c in candles if (t := _int_ms(c.get("timestamp"))) is not None]
    oldest = min(stamps) if stamps else None
    newest = max(stamps) if stamps else None
    store.record_window(
        fetch_id,
        route=CANDLES_ROUTE,
        scope=mint,
        t_oldest_row_ms=oldest,
        t_newest_row_ms=newest,
        row_count=len(candles),
        truncated=False,
    )
    return oldest, newest, len(candles)


def unwrap_callout_body(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """The `/callout/*` envelope, re-exported so service code has one import site."""

    return _callout_page(data)
