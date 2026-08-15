"""LP-only execution for "tha funds" (Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ).

THE PRODUCT IS THE REFUSAL, NOT THE PLUMBING.

This package can add and remove Meteora DLMM liquidity, claim fees, and close positions.
It CANNOT swap. Not "does not"; cannot. `guard.py` decodes every transaction before a
signature exists and refuses any instruction whose 8-byte Anchor discriminator is not on a
committed allowlist -- and the six swap discriminators of the DLMM program are not on it,
nor is any instruction of any AMM, router, or aggregator, nor an unrestricted SPL transfer.
The worst reachable failure is a badly placed ladder. There is no reachable failure that
drains the wallet, because there is no instruction in the buildable set that could.

WHY THAT IS THE RIGHT SHAPE FOR THIS DESK. A one-sided DLMM ladder converts inventory using
other people's flow: you post asks above spot and arbitrageurs fill them. You never sign a
sale. `studies/RESULT_toll_positioning.md` §4 measured this at +1.4-2.0% per unit of flow
against routing the same size through Jupiter (t=3.31, n=221 fills, 2 pools, hour-clustered)
-- so the safe primitive is also the profitable one, and giving up the swap instruction costs
the desk nothing it was using. The same study's verdict bounds the claim: a ladder is good
AS EXECUTION on flow you must move, bad AS INVENTORY.

THE TRUST BOUNDARY. Meteora's TypeScript SDK builds the transactions (see `sidecar.py` for
why a real dependency beat hand-rolling bin math). The sidecar is a subprocess that never
receives, reads, or derives a key -- it emits unsigned base64. Python decodes what came back,
checks it against the allowlist, the pool allowlist, the caps, and our own pubkey, and only
then signs. A compromised, buggy, or version-drifted sidecar cannot move funds; it can only
produce bytes the guard rejects. This is the shape `shitcoims_sentinel` already earned
against Jupiter -- an untrusted builder, a trusted validator -- reused because it held.

THREE GATES, ALL REQUIRED (`gate.py`): `lpexec.execution.enabled` in config, `--live` on the
command line, and a mode-0600 arm file whose contents bind to this exact wallet. Any one
absent means dry-run. Dry-run is the default of every code path, including error paths.

Nothing here imports `shitcoims_sentinel`. The patterns are copied deliberately; the coupling
is not. That package runs live money on a different wallet with a different mandate, and one
package's refactor must not be able to change the other's refusals.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
