"""The network map: the cluster rendered as a circuit, read-only.

PROGRAM.md §8 names this object as missing — "live graph of the cluster — per-edge
conductance, charge state, curl residual, which edges are *ours* — merging the flow tape, the
panel, and the LP meter". This package is that object, with **§8's own correction applied**:

- a pool's liquidity sets a **capacitance** (`C = w_x·w_y·TVL`, `TVL/4` at even weights), not a
  conductance;
- the swap fee is a **back-to-back diode pair** whose dissipation is linear in `|flow|`, not an
  `I²R` resistor, and the no-trade band is literally its dead-zone;
- a Meteora DLMM edge is a **series battery-cell stack**, not a capacitor, and its depth carries
  an unobservable concentration factor, so every DLMM-dependent number is an interval.

Three feeds, all already existing, none of them written to by this package:

1. ``state/cluster_tape`` — swaps, attempts, references and the **watch ledger** that makes "no
   flow" distinguishable from "not watching" (:mod:`shitcoims_netmap.tapefeed`).
2. Meteora's public DLMM data API, through ``scripts/meteora_lp_report.py`` — which edges are
   **ours** (:mod:`shitcoims_netmap.lp`).
3. Keyless DexScreener + GeckoTerminal quotes, two sources on purpose, because the curl is a
   level statistic and a single-source residual is not a measurement
   (:mod:`shitcoims_netmap.prices`).

**The JSON is the contract; the ASCII is a view of it.** :mod:`shitcoims_netmap.assemble` is a
pure function from feeds to a JSON-serialisable dict and does no I/O;
:mod:`shitcoims_netmap.render` does the I/O and the drawing. Everything in the terminal view is
derivable from ``--json`` output, so nothing is visible only to a human.

**Read-only by construction.** No module here opens a file for writing, holds a keypair, or
signs anything. The tape is opened ``"r"`` and is being appended to while it is read.
"""

from __future__ import annotations

from typing import Final

SCHEMA: Final[str] = "shitcoims_netmap/1"

__all__ = ["SCHEMA"]
