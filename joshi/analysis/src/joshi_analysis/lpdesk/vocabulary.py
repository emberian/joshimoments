"""The honesty vocabulary every LP-desk artifact renders, quoted or declared once.

``ONE_TAPE_FITS_NOTHING`` is quoted from ``crates/joshi-liquidity/src/grid.rs`` via
``scalplab.vocabulary`` so the three systems say the same sentence; the LP-desk restatement
narrows it to this desk's own objects (one pool, one window, one operator's history).
"""

from __future__ import annotations

from joshi_analysis.scalplab.vocabulary import ONE_TAPE_FITS_NOTHING

__all__ = [
    "AUTHOR_KNOWLEDGE",
    "DESK_AUTHORITY",
    "FEE_CAPTURE_MODEL",
    "ONE_POOL_ONE_WINDOW_FITS_NOTHING",
    "ONE_TAPE_FITS_NOTHING",
    "PANEL_CONTRACT",
    "PROVIDER_CLAIM",
    "RECONSTRUCTED_FROM_CHAIN",
    "RETENTION_CONTRACT",
]

PANEL_CONTRACT = "joshi.lpdesk.panel.v1"
RETENTION_CONTRACT = "joshi.lpdesk.retention.v1"

#: The only authority this package holds. Nothing here constructs, signs, or submits a
#: transaction, and nothing here may grow that authority without a new conversation.
DESK_AUTHORITY = "read_only_no_execution"

#: The grid ensemble's sentence, restated for this desk's objects. Rendered on every panel.
ONE_POOL_ONE_WINDOW_FITS_NOTHING = (
    "ONE POOL, ONE WINDOW FITS NOTHING. Every cell of this frontier is arithmetic on the "
    "same retained tape of the same pool; the best cell is the largest of N draws from one "
    "sample; 'tuned on this window' can never be read as 'expected forward'; and the "
    "operator's own history is a handful of decisions by one person in one regime. The "
    "time-split evaluation is the same pool days apart — a weaker check than a different "
    "pool, stated as such."
)

#: Rules written by someone who has seen the tape are not blind. The frontier's author
#: (this package's author) had already read the operator's stated ~6.4%/24h figure and the
#: reconstruction before declaring the policy axes; the axes were chosen to bracket her
#: actual policy, which is a form of fitting, stated here rather than hidden.
AUTHOR_KNOWLEDGE = (
    "The policy axes were declared AFTER reading the operator's reconstructed history and "
    "her stated ~6.4%/24h figure; they bracket her actual width and cadence on purpose. "
    "The both-sides refutation was then challenged by the operator with a chart showing "
    'two-sided chop — verbatim: "ok well maybe you look somewhere wrong etc." — and the '
    "floor-free recount was fetched and computed AFTER that challenge, knowing what it "
    "was checking. Nothing in this panel is a blind experiment."
)

#: Label for any number a provider computed rather than the chain stating it directly.
PROVIDER_CLAIM = "provider_claim"

#: Label for a number derived by this package from retained transaction or account bytes.
RECONSTRUCTED_FROM_CHAIN = "reconstructed_from_retained_bytes"

#: The frontier cannot observe competitor liquidity per bin through time, so a policy's fee
#: take is modeled, and the model is named on every cell that uses it.
FEE_CAPTURE_MODEL = (
    "fee capture model: a policy earns swap_fee * (own_liquidity_in_active_bin / "
    "active_bin_liquidity), with active-bin liquidity held at its measured value and the "
    "policy's own liquidity assumed too small to move it. Competitor liquidity through time "
    "is UNOBSERVED on this tape; the frontier is exact arithmetic on a named model, not a "
    "measurement, and rows are comparable to each other more than they are to the world."
)
