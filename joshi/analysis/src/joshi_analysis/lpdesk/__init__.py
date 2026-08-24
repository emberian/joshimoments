"""The LP desk: measurement of one operator's Meteora DLMM position, read-only.

The live question this package exists for, in the operator's words: recentering a really
narrow wSOL/USDC DLMM position "seems to be earning me ~6.4% fee/24hr TVL. which is insane.
is that real and what else should we be thinking about for intelligently automating that".

Four instruments, none of which construct, sign, or submit anything:

* :mod:`.reconstruct` — her position's actual history from retained chain bytes: deposits,
  withdrawals, fee claims, rebalances, tx costs; the honest net beside the gross.
* :mod:`.dial` — the regime dial: fee intensity versus realized variance from the pool's own
  swap tape and oracle, because fees scale with volume and adverse selection with sigma^2.
* :mod:`.frontier` — a declared width x trigger x dwell policy ensemble replayed over the
  retained bin path, with unremovable baselines, the grid ensemble's LP cousin.
* :mod:`.fetch` — the bounded acquisition that retains the bytes the other three read.

Money that is summed is ``Decimal``; every rendered number carries its window and its
denominator; what the bytes cannot state is carried as absence, never invented.
"""
