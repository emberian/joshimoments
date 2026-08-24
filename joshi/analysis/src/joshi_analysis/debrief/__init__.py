"""The session debrief: "on this day we discussed this about these charts", durably.

One human-readable markdown artifact per operator day, reconstructed read-only from the
records Joshi already keeps: the pairing ledger (when a cockpit was actually paired), the
live-follow state (which scenes advanced), the command ledger (every hold, note, journal
entry and disposition, with her words verbatim in the payload blobs), the retained scene
view blobs (every provider-asserted price and market cap), and the pre-registered
selection instrument's own report.

    stores     read the durable records, mode=ro throughout
    artifact   assemble one day's debrief and render it as markdown

Run it:

    uv run --offline python -m joshi_analysis.debrief \\
        --session-state state/keeper/cockpit-state --catalog state/keeper/catalog

Artifacts land in `state/s2/<date>-session.md` (the S2 runbook's findings convention).
A file holding hand-written words is never overwritten: the debrief goes to a
`-debrief` sibling instead, and only files this module itself wrote are refreshed.
"""

from __future__ import annotations

from .artifact import (
    DebriefInputs,
    is_generated_debrief,
    read_inputs,
    render_day_debrief,
    session_days,
    write_day_debrief,
)
from .stores import (
    HOLD_NOTE_UI_LABEL,
    HOLD_UI_LABEL,
    JOURNAL_UI_LABEL,
    MintCatalogView,
    OperatorAct,
    PairedWindow,
    Reading,
    read_live_scenes,
    read_mint_catalog_view,
    read_operator_acts,
    read_paired_windows,
    read_witnessed_scenes,
)

__all__ = [
    "HOLD_NOTE_UI_LABEL",
    "HOLD_UI_LABEL",
    "JOURNAL_UI_LABEL",
    "DebriefInputs",
    "MintCatalogView",
    "OperatorAct",
    "PairedWindow",
    "Reading",
    "is_generated_debrief",
    "read_inputs",
    "read_live_scenes",
    "read_mint_catalog_view",
    "read_operator_acts",
    "read_paired_windows",
    "read_witnessed_scenes",
    "render_day_debrief",
    "session_days",
    "write_day_debrief",
]
