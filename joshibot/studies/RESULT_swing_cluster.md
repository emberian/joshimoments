# RESULT: swing structure in the community-cluster universe (weave, nosis, DREGG, SOLVE)

2026-08-13. Hourly GeckoTerminal OHLCV on each token's deepest SOL pool. Panel and scripts in the
session scratchpad (`cluster_pools.py`, `cluster_panel.py`, `cluster_panel.json`); mints and pool
addresses recorded there. This is a *measurement*, run before any strategy — §3 discipline applied to
our own idea.

## Universe as measured

| token | mint (prefix) | FDV | main pool liq | vol24 | history |
|---|---|---|---|---|---|
| weave | 8PecVcCG | $128k | $28k (pumpswap) | $189k | 9.9 d |
| nosis | FPfi9q1A | $263k | $48k (pumpswap) | $585k | 4.5 d |
| DREGG | XkeTXo11 | $358k | $57k (pumpswap) | $26k | 20.8 d |
| SOLVE | GwyWFsDK | $44k | $16k (pumpswap) | $4.3k | 22.0 d |

The operator's Meteora token-token pools appear in routing with small TVL and **large turnover**:
DREGG/nosis $688/day on $433 TVL (**159%/day**), weave/nosis $232/day on $882 (26%/day). At DLMM fee
tiers this is several %/day on capital — the reported "harvesting a LOT" is mechanically confirmed.

## What the panel shows (83 common hours for cross-pairs; 499 for DREGG/SOLVE)

Hourly log-return correlations are **low** (0.11–0.24) — but attenuated by thin-pool microstructure
noise, so read as a floor, not the truth. Hourly close-to-close vol: weave 28%/hr, nosis 38%/hr
(young + thin; inflated), DREGG 5.2%/hr, SOLVE 5.5%/hr.

AR(1) on log-ratios, **with the Kendall small-sample debias `E[ρ̂] ≈ ρ − (1+3ρ)/n` applied** — which
kills half the table and is the honest part:

| pair | n | ρ̂ | debiased | half-life | ratio-sd | verdict |
|---|---|---|---|---|---|---|
| **DREGG/SOLVE** | 499 | 0.901 | 0.908 | **6.6 → 7.2 h** | 15.0% | **robust reversion** |
| weave/nosis | 83 | 0.881 | 0.925 | 5.5 → 8.9 h | 94.4% | reverting, noisy |
| weave/DREGG | 83 | 0.963 | **~1.01** | — | 121% | **artifact; not distinguishable from RW** |
| weave/SOLVE | 83 | 0.962 | ~1.01 | — | 127% | artifact |
| nosis/DREGG | 83 | 0.953 | ~1.00 | — | 122% | artifact |
| nosis/SOLVE | 83 | 0.956 | ~1.01 | — | 130% | artifact |

The debias is not pedantry: four of six "mean-reverting pairs" die under it. They may still revert —
n=83 simply cannot show it. Re-run when weave/nosis have 3+ weeks of history.

## The structural finding

A mean-reverting ratio is **exactly the regime where DLMM token-token LP is +EV**: impermanent loss is
*temporary* by definition (the ratio comes back) while fees accrue on every oscillation. This is the
opposite regime from the one marketfabric measured as "LP is −EV everywhere" — that study was (a) all
token/SOL pools in *trending* regimes, and (b) run on a simulator that destroys ~half of fee income on
chop (the down-move fee bug). Both errors point the same way: **token-token pools between co-moving
community coins are plausibly the best LP venue this desk has**, and the operator found it empirically
before we measured it.

The desk structure this implies: hold inventory in all four; run DLMM pools on the *measured-reverting*
pairs; let a z-score rule rotate inventory through **our own pools**, so the swap fee on the rebalance
leg is partially recaptured as LP fee. Three fee streams compound on the same volatility: DREGG creator
fees (volume-linked), LP fees (relative-vol-linked), and swing capture (reversion-linked).

## Friction arithmetic for the one robust pair

DREGG/SOLVE, ratio-sd 15%, half-life ~7h. A rebalance at |z| ≥ 1.5 capturing ~1σ ≈ 15% gross. Through
SOL pools it is 4 swap legs ≈ 4–6% round-trip friction → ~9% net per swing, cycle 7–14h, entries a few
times a week. Through our own SOLVE/DREGG Meteora pool (currently **$0 TVL — seed it**) the fee legs
partially return as LP income. **No shorting exists or is needed**: for an inventory holder, a ratio
swing is selling the rich leg and buying the cheap one — portfolio rebalancing, not a short.

## Caveats, all real

- Thin-pool close-to-close bars manufacture apparent reversion (bid-ask bounce). The DREGG/SOLVE
  half-life is probably somewhat longer than 7.2h in tradeable terms. The falsification: compute the
  same AR(1) on volume-weighted or midpoint bars once the tape records reserves directly.
- SOLVE's $16k liq bounds size: ρ ≤ 2% → ~0.3 SOL per rebalance leg today.
- These four are one community cluster ≈ one correlated bet. Cluster-level exposure cap, not per-token.
- Swing-selling DREGG interacts with the creator-fee stream and community optics — operator's call,
  not a statistical question.

## Next

1. Re-measure weave/nosis pairs at n ≥ 300; promote any pair whose debiased ρ < 0.98.
2. Meteora API read of the operator's actual LP positions (claimable fees, value) — the fee harvest is
   currently known only anecdotally; make it a number.
3. Shadow the z-score rebalance rule with the scalper's machinery (propensity-logged, ε-explored,
   pessimistically marked) — the `Book`/breaker/heap and `PropensityRecord` conformance port directly;
   only the policy and the clocks change (hours, not minutes).
