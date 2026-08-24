"""scalplab: a probabilistic policy lab over retained coin tapes, pre-registered.

Rules-based sweeps kept finding nothing executable on these tapes; this package asks the
probabilistic question instead — "what is P(a floor-clearing up-leg begins within k events)?"
— under a protocol registered in REGISTRATION.md before any model touched a real tape. The
lab proposes; the economic verdicts stay with ``crates/joshi-liquidity``. The bridge artifact
is the declared policy file, not a claim.
"""

from .evaluation import LabRun, build_corpus, lab_report, run_lab
from .labels import LabelSet, floor_clearing_labels
from .policy import PolicyError, declared_policy, validate_policy, write_policy
from .run import run_and_write
from .tape import LoadedTape, TapeError, TapeEvent, TapeProvenance, load_tape

__all__ = [
    "LabRun",
    "LabelSet",
    "LoadedTape",
    "PolicyError",
    "TapeError",
    "TapeEvent",
    "TapeProvenance",
    "build_corpus",
    "declared_policy",
    "floor_clearing_labels",
    "lab_report",
    "load_tape",
    "run_and_write",
    "run_lab",
    "validate_policy",
    "write_policy",
]
