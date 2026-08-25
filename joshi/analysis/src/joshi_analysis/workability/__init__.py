"""Workability census: which statistics tell us which pump.fun coins to work?

A lightweight, budgeted, registered census over recent pump.fun mints (72h) and callouts
(24h), asking two questions with the honesty floor of the house: (1) do any cheap window-A
statistics predict window-B workability — floor-clearing legs per hour at declared latency
tiers — and (2) does selecting coins by such a statistic improve what the committed autostrat
family (the grid-ladder ensemble) extracts, net of its own haircuts?

The registration is ``STUDY.md`` in this directory, written before any request was made.
Every provider request flows through the committed release binaries
(``joshi-pump-product-read``, ``joshi-pump-trades-backfill``) under an append-only ledger
with a hard budget. Tapes load through ``joshi_analysis.scalplab.tape`` (its REGISTRATION.md
governs); every tape here is ``retrospective_none`` and the whole census is an oracle-window
study, never a live-executable claim.
"""

STUDY_VERSION = "joshi.workability_census.v1"

# The tiers of section 3 of STUDY.md, in slots. Slot = first 12 digits of slotIndexId.
TIERS_SLOTS = (0, 2, 8, 32)

# Flat sensitivity floor (scalplab's declared default), computed beside every per-coin floor.
FLAT_FLOOR_BPS = 250

# Minimum window sizes below which a coin's cell is INSUFFICIENT, never imputed.
MIN_A_EVENTS = 20
MIN_B_EVENTS = 10

# The whole-study hard request ceiling. Refusal at the ceiling is a deliverable.
HARD_BUDGET_REQUESTS = 2_200
