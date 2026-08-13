"""The recorded tape: the shared contract every downstream study and replay reads.

This package holds interfaces #1 (tape event schema), #7 (entity resolution output) and
#8 (propensity log) of the Phase 0 manifest in SWARM.md. It contains data contracts only —
no network, no keys, no execution. Nothing here may import from ``shitcoims_sentinel``.
"""

from __future__ import annotations

from shitcoims_tape.schema import (
    INFORMATIVE_CLOSES,
    SCHEMA_VERSION,
    Callout,
    Chainstamp,
    EntityLink,
    EventKind,
    Launch,
    PropensityRecord,
    Provenance,
    Reserves,
    Side,
    TapeError,
    TapeEvent,
    TapeHealth,
    Trade,
    WatchClose,
    WatchWindow,
    event_from_json,
    parse_amount,
    tape_health,
)

__all__ = [
    "INFORMATIVE_CLOSES",
    "SCHEMA_VERSION",
    "Callout",
    "Chainstamp",
    "EntityLink",
    "EventKind",
    "Launch",
    "PropensityRecord",
    "Provenance",
    "Reserves",
    "Side",
    "TapeError",
    "TapeEvent",
    "TapeHealth",
    "Trade",
    "WatchClose",
    "WatchWindow",
    "event_from_json",
    "parse_amount",
    "tape_health",
]
