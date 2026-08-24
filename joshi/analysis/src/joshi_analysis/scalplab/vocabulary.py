"""The honesty vocabulary every scalplab artifact renders, quoted or declared once.

The economic harnesses in ``crates/joshi-liquidity`` own the money arithmetic; this lab only
proposes. What the lab shares with them is the vocabulary that keeps a result from being read
as a forecast. ``ONE_TAPE_FITS_NOTHING`` is quoted verbatim from
``crates/joshi-liquidity/src/grid.rs`` so the two systems say the same sentence.
"""

from __future__ import annotations

REGISTRATION_VERSION = "joshi.scalplab.registration.v1"
POLICY_CONTRACT = "joshi.scalplab.declared_policy.v1"
LAB_AUTHORITY = "read_only_no_execution"

# Verbatim from crates/joshi-liquidity/src/grid.rs (ONE_TAPE_FITS_NOTHING), the harness's own
# words. The "surface"/"cell" nouns are the grid panel's; the sentence's force is identical
# here: N models x N horizons x N thresholds on one small corpus is N draws from one sample.
ONE_TAPE_FITS_NOTHING = (
    "ONE TAPE OF ONE COIN FITS NOTHING. Every cell of this surface is arithmetic on the same "
    "single retained tape; the best cell is the largest of N draws from one sample, 'tuned on "
    "this tape' can never be read as 'expected forward', and the held-out window is the same "
    "coin on the same afternoon — a weaker check than a different tape, stated as such. The "
    "full-tape and first-window surfaces are IN-SAMPLE by construction. Reading the held-out "
    "surface and preferring a different cell than the pre-named one is fitting on the held-out "
    "window."
)

NOT_AN_ECONOMIC_VERDICT = (
    "This lab proposes policies and calibrates probabilities. It computes no PnL: economic "
    "verdicts belong to the replay/grid harnesses in crates/joshi-liquidity, which own the "
    "exact venue arithmetic, the unremovable baselines, and the central+adverse haircuts. The "
    "bridge is the declared policy file, not a claim."
)

AUTHOR_KNOWLEDGE_REQUIRED = (
    "A blank author-knowledge disclosure is refused: rules written by someone who has seen the "
    "tape are not blind, and a blank would read as 'nothing'. Say what you knew."
)

# --- pre-registered constants (mirror REGISTRATION.md; the doc is the registration, these are
# the executable copies) ---------------------------------------------------------------------

DEFAULT_VENUE_FLOOR_BPS = 250
MEASURED_FLOOR_RANGE_BPS = (190, 250)
EXECUTION_DELAY_EVENTS = 1
HORIZONS_K = (10, 25, 50, 100)
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)

FEATURE_WINDOW = 32
WARMUP_EVENTS = FEATURE_WINDOW + 1

CUSUM_DRIFT = 0.5
CUSUM_THRESHOLD = 5.0
EWMA_HALF_LIFE_EVENTS = 8
ANALOG_NEIGHBOURS = 50
ANALOG_MEMORY_CAP = 4_000
LOGIT_L2 = 1e-3
LOGIT_MAX_ITER = 25
LOGIT_TOL = 1e-8
HAWKES_EVAL_BUDGET = 600
HAWKES_TIE_DITHER_S = 1e-4
HAWKES_WINDOW_EVENTS = 256

GATE_EVAL_MIN_EVENTS = 500
GATE_EVAL_MIN_POS = 25
GATE_TRAIN_MIN_COINS = {"logit": 5, "analog": 8, "hawkes": 5}
GATE_TRAIN_MIN_EVENTS = {"logit": 5_000, "analog": 20_000, "hawkes": 3_000}
GATE_HAWKES_MIN_EVENTS_PER_COIN = 300
CANDIDATE_MIN_FIRED = 20
CANDIDATE_PRECISION_MULTIPLE = 1.5
WILSON_Z_90 = 1.2815515655446004

VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA"
VERDICT_NULL = "CALIBRATED_NULL"
VERDICT_CANDIDATE = "CANDIDATE_POLICY"
