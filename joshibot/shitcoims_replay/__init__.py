"""Deterministic tape replay: the instrument every strategy claim rests on.

Fills come from ``shitcoims_kernel``, which is held to exact agreement with the Lean artifact
in ``kernel/Joshi/Fill.lean``. Policies are handed a causally-restricted :class:`Snapshot`
rather than the tape, mirroring ``View t`` in ``kernel/Joshi/History.lean``.

Contains no search, no scoring and no sizing — those sit above this and are separately
accountable, so that a bad strategy and a bad simulator can never be confused for each other.
"""

from __future__ import annotations

from shitcoims_replay.engine import (
    Fill,
    Ledger,
    Order,
    Policy,
    PoolState,
    ReplayError,
    Snapshot,
    replay,
)
from shitcoims_replay.ope import Estimate, LoggedDecision, OPEError, evaluate, require_overlap
from shitcoims_replay.split import Fold, Sample, SplitError, assert_no_leakage, walk_forward

__all__ = [
    "Estimate",
    "Fill",
    "Fold",
    "Ledger",
    "LoggedDecision",
    "OPEError",
    "Order",
    "Policy",
    "PoolState",
    "ReplayError",
    "Sample",
    "Snapshot",
    "SplitError",
    "assert_no_leakage",
    "evaluate",
    "replay",
    "require_overlap",
    "walk_forward",
]
