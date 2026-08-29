"""Removal inference: verdicts only, from windows and absences, never from vibes.

THE INSTRUMENT
--------------
A callout we have previously sighted is judged against every LATER 200-OK fetch of a
deletion surface whose recorded window SPANS the callout's own timestamp:

* window spans `t_event` AND the callout is not among that fetch's rows
      -> one **absent-while-spanned** event. The feed walked straight through the moment
         this callout lives at and did not serve it.
* window no longer reaches `t_event` (the feed's retention rolled past it)
      -> **rolled off**. NO evidence of anything. A feed forgetting is not a platform
         deleting, and conflating the two is how an archive invents censorship.

"Spans" is STRICT (`t_oldest < t_event < t_newest`): the keyset cursor can split rows
sharing a millisecond across a page boundary, so a callout sitting exactly on a window
edge may legitimately live in the neighbouring page. Strictness costs a little
sensitivity at the edges — which the 30-minute overlap's repeated re-walks repay — and
buys the property an accusation instrument needs most: no false positive from pagination
mechanics.

THE VERDICT BAR
---------------
`removed` requires ALL of:
  * >= 2 absent-while-spanned events,
  * spread >= 60 minutes apart (a single moment of feed weirdness is not evidence),
  * >= 2 distinct surfaces — the global firehose re-walk AND the per-mint
    timestamp-sorted listing. One backend view can lie alone; two disagreeing with our
    retained bytes is a different class of fact.
Anything less is `unknown-absent` and is never published (the `published` flag exists for
a later lane; nothing here sets it).

REAPPEARANCE RESETS EVERYTHING. Only absences observed AFTER the callout's most recent
sighting count; a callout that is sighted again after an absence run has demonstrably not
been removed, its accumulated evidence is void, and an existing verdict row is cleared
with a note. Verdicts must be able to retreat, or they are beliefs.

STATED ASSUMPTION (the one this inference stands on): a timestamp-sorted listing is DENSE
over the range it returned — the provider does not serve rows at t1 and t3 while hiding a
t2 it still considers servable. The two-surface requirement is the hedge against exactly
this assumption failing on one surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .store import Store, utc_day

REMOVED = "removed"
UNKNOWN_ABSENT = "unknown-absent"

#: The two surfaces. `callout_top` is deliberately NOT one: it is a ranked list, and
#: absence from a top-50 is competition, not deletion.
RECENT_SURFACE = "callout_recent"
LIST_SURFACE = "callout_list_mint"

MIN_EVENTS = 2
MIN_SPREAD_MS = 60 * 60_000
MIN_SURFACES = 2


@dataclass(frozen=True, slots=True)
class AbsentEvent:
    fetch_id: int
    route: str
    t_response_ms: int


def last_sighting_ms(store: Store, callout_id: str) -> int | None:
    row = store.db.execute(
        "SELECT MAX(f.t_response_ms) FROM sightings s JOIN fetches f ON f.id = s.fetch_id"
        " WHERE s.callout_id = ?",
        (callout_id,),
    ).fetchone()
    return None if row is None or row[0] is None else int(row[0])


def absent_events(store: Store, *, callout_id: str, mint: str, t_event_ms: int) -> list[AbsentEvent]:
    """Every absent-while-spanned observation newer than the callout's last sighting."""

    after = last_sighting_ms(store, callout_id) or 0
    rows = store.db.execute(
        """
        SELECT w.fetch_id, w.route, f.t_response_ms
        FROM fetch_windows w JOIN fetches f ON f.id = w.fetch_id
        WHERE f.status = 200
          AND ((w.route = ? AND w.scope IS NULL) OR (w.route = ? AND w.scope = ?))
          AND w.t_oldest_row_ms IS NOT NULL AND w.t_newest_row_ms IS NOT NULL
          AND w.t_oldest_row_ms < ? AND ? < w.t_newest_row_ms
          AND f.t_response_ms > ?
          AND NOT EXISTS (SELECT 1 FROM sightings s
                          WHERE s.callout_id = ? AND s.fetch_id = w.fetch_id)
        ORDER BY f.t_response_ms
        """,
        (RECENT_SURFACE, LIST_SURFACE, mint, t_event_ms, t_event_ms, after, callout_id),
    ).fetchall()
    return [AbsentEvent(int(r[0]), r[1], int(r[2])) for r in rows]


def classify(events: list[AbsentEvent]) -> str:
    """`removed` only past the full bar; everything else — including NO events, the
    rolled-off case — is `unknown-absent`."""

    if len(events) < MIN_EVENTS:
        return UNKNOWN_ABSENT
    spread = max(e.t_response_ms for e in events) - min(e.t_response_ms for e in events)
    surfaces = {e.route for e in events}
    if spread >= MIN_SPREAD_MS and len(surfaces) >= MIN_SURFACES:
        return REMOVED
    return UNKNOWN_ABSENT


@dataclass(slots=True)
class PassSummary:
    evaluated: int = 0
    removed: int = 0
    unknown_absent: int = 0
    cleared: int = 0
    #: Mints whose evidence is single-surface so far — candidates for a list probe.
    confirm_mints: list[str] = field(default_factory=list)


def run_pass(store: Store, now_ms: int, *, horizon_ms: int) -> PassSummary:
    """Evaluate every callout whose verdict could have changed.

    Candidates are callouts young enough that a surface window can still span them, plus
    every callout that already holds a verdict row (so evidence keeps accruing and a
    reappearance retreats the verdict). Older, verdict-less callouts are structurally
    unreachable — their absence can only ever be roll-off.
    """

    out = PassSummary()
    rows = store.db.execute(
        """
        SELECT c.callout_id, c.mint, c.t_event_ms FROM callouts c
        WHERE c.t_event_ms IS NOT NULL
          AND (c.t_event_ms >= ?
               OR EXISTS (SELECT 1 FROM removal_verdicts v WHERE v.callout_id = c.callout_id))
        """,
        (now_ms - horizon_ms,),
    ).fetchall()
    probe_mints: dict[str, None] = {}
    for callout_id, mint, t_event_ms in rows:
        out.evaluated += 1
        events = absent_events(store, callout_id=callout_id, mint=mint, t_event_ms=int(t_event_ms))
        if not events:
            if store.clear_verdict(callout_id):
                out.cleared += 1
                store.note(now_ms, "verdict_cleared",
                           f"{callout_id}: no absent evidence newer than last sighting")
            continue
        verdict = classify(events)
        prior = store.db.execute(
            "SELECT verdict, evidence_fetch_ids FROM removal_verdicts WHERE callout_id=?",
            (callout_id,),
        ).fetchone()
        evidence = [e.fetch_id for e in events]
        if prior is None or prior[0] != verdict or json.loads(prior[1]) != sorted(evidence):
            store.upsert_verdict(
                callout_id=callout_id, t_verdict_ms=now_ms, verdict=verdict,
                evidence_fetch_ids=evidence,
            )
        if verdict == REMOVED:
            out.removed += 1
        else:
            out.unknown_absent += 1
            if {e.route for e in events} == {RECENT_SURFACE}:
                probe_mints[mint] = None
    out.confirm_mints = list(probe_mints)
    return out


def probe_dedupe(mint: str, now_ms: int) -> str:
    return f"list_probe:{utc_day(now_ms)}:{mint}"
