"""Python binding to the Lean decision kernel in ``kernel/``.

Say the substrate out loud: **the fill semantics are authored in Lean**, in
``kernel/Joshi/Fill.lean``, where the properties the desk relies on are machine-checked
theorems about the emitted object — the payout is bounded by the reserve, it is monotone in
size, and the min-out acceptance test is decidable before signing.

This package does two things and nothing else:

- ``oracle`` runs the Lean artifact as a subprocess and asks it. Slow, authoritative.
- ``fill`` is a Python fast path for the replay harness, which will evaluate millions of
  hypothetical fills and cannot pay a subprocess round trip for each one.

The fast path is kept honest by ``tests/test_kernel_parity.py``, which drives both over
random and adversarial vectors and requires exact agreement.

One thing that must not be overstated, because the distinction is the whole point of putting
this in Lean: **the parity tests prove nothing about all inputs.** They are engineering
discipline against drift, not verification. The theorems are in the Lean file and they are
about the Lean definition; the Python here inherits none of them. If the two ever disagree,
the Lean side is right by construction and the Python side is a bug.
"""

from __future__ import annotations

from shitcoims_kernel.fill import Reserves, accepts, sell_out
from shitcoims_kernel.oracle import LeanOracle, OracleRejected, OracleUnavailable

__all__ = ["LeanOracle", "OracleRejected",
    "OracleUnavailable", "Reserves", "accepts", "sell_out"]
