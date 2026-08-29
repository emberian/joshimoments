# RESULT: hop distance to a dirty crew predicts nothing -- a registered negative

Registered as D4 in `studies/REGISTRATION_d4m.md`, which stated the expected outcome before
computing: *"The prior held before computing is that this FAILS at h = 2 and possibly at
h = 1; a negative here is the registered, expected, publishable outcome, and it is written up
either way."* It failed at both. Code `dregg_d4m/analyses.py:d4_reach`; artifacts
`state/dregg_d4m/d4_reach_{dirty,rips}_hop_rip_rates-v1-*.parquet`. Reproduce:
`uv run --group research python -m dregg_d4m d4`.

---

## 0. The one-paragraph answer

**The registered claim does not ship.** Hop distance from a coin's birth-slot sniper set to a
"dirty" crew wallet, over the Jaccard-weighted crew graph, does not order that coin's
probability of being a rip. Both registered conditions fail at `h = 1` and at `h = 2`.

Two things fell out that are worth more than the failed claim:

1. **The ledger's `dirty` flag is nearly vacuous.** It fires for **10,585 of 11,111 crews
   (95.3%)**, because it is `rips + dumps > 0` and `dumps > 0` is the market's default
   outcome. Only **495 crews (4.5%)** have a recorded rip. The registered seed set was
   therefore "almost every crew", and a gate built on `dirty` is selecting on a property
   nineteen crews in twenty share.
2. **The sign is inverted.** Coins whose birth-slot set touches a dirty crew directly
   (`h = 0`) rip at **1.54%**; coins with no path to one at all rip at **4.19%** -- with
   **disjoint** Wilson intervals. Crew-connected coins rip LESS. Section 3 gives the
   mechanism, which is definitional rather than behavioural, and which is exactly why the
   registered estimand was the wrong one.

---

## 1. The construction

Seeds: every wallet in a ledger crew with `rips + dumps > 0` -- **14,583 wallets** across
**121,500 dirty crew coins**. Graph: `G_ww` at `jaccard >= 0.10`, `overlap >= 2` (the crew
graph, not the promiscuity graph). Hop levels come from the **or-and semiring**: a frontier
row-vector times the adjacency IS the next frontier, so breadth-first search over 59,524
wallets is `max_hops` sparse products rather than a traversal.

Coins that are themselves dirty crew coins are **excluded** -- they defined the seeds, and
scoring them would be circular. That leaves **41,944 coins** of the 163,444 with a non-empty
ex-deployer birth-slot set.

## 2. The result

| hops to a dirty crew | coins | rips | rip rate | Wilson 95% CI |
|---|---|---|---|---|
| 0 (a seed wallet is in the set) | 35,041 | 541 | **0.01544** | [0.01420, 0.01678] |
| 1 | 284 | 15 | 0.05282 | [0.03227, 0.08530] |
| 2 | 101 | 1 | 0.00990 | [0.00175, 0.05397] |
| 3 | 50 | 0 | 0.00000 | [0.00000, 0.07135] |
| **unreached** | 6,468 | 271 | **0.04190** | [0.03728, 0.04706] |

Registered ship rule: `h = 1` and `h = 2` must EACH exceed the unreached rate with
non-overlapping Wilson intervals AND exceed the 95th percentile of the degree-preserving null.

* `h = 1`: 0.0528 vs 0.0419, CI [0.0323, 0.0853] **overlaps** [0.0373, 0.0471]. **Fails.**
* `h = 2`: 0.0099 is **below** the unreached rate. **Fails.**

### 2.1 The degree-preserving null, and why it adds nothing here

| hop | observed rate | curveball null mean | null p95 | mean coins at this hop, in the null |
|---|---|---|---|---|
| 1 | 0.0528 | 0.1416 | 0.2045 | **70.4** (observed: 284) |
| 2 | 0.0099 | 0.0000 | 0.0000 | **2.2** (observed: 101) |

50 draws, `studies.operator_crime._curveball` on the wallet x coin incidence.

**The null is uninformative, for the same structural reason `RESULT_d4m_communities.md`
section 2.1 records: the curveball destroys the crew graph.** Randomising the incidence takes
it from 22,458 edges to ~461, so almost nothing is reachable and the null's hop-1 and hop-2
buckets hold 70 and 2 coins. A rate estimated on 2.2 coins is not a comparison, and the h = 2
"beats_null_p95: true" in the artifact is that artefact, not evidence -- it is true because
the null's h = 2 bucket is empty.

**The verdict does not depend on this.** The first registered condition -- disjoint Wilson
intervals against the unreached rate -- is null-free, and both hops fail it outright.

**No hop-distance claim ships.** The h = 1 point estimate is the only one above the unreached
rate, it rests on 15 rips out of 284 coins, and its interval covers the unreached rate. That
is what an n of 284 buys.

## 3. Why the sign is inverted, and why that is definitional

`h = 0` coins rip at 1.54% and unreached coins rip at 4.19%, and the intervals are disjoint.
Read naively, "your snipers are in a known dirty crew" is *protective*. It is not.

The two populations differ by construction. A `h = 0` coin's birth-slot set touches a wallet
that snipes multi-launch deployers' coins -- factory output. In the panel's labelling, factory
output mostly **dumps** rather than **rips**, and `dumps` is what put 95.3% of crews in the
seed set in the first place. The unreached population is disproportionately the coins of
one-off deployers, where the panel's `is_rip` label is the live outcome. **The comparison is
between two different label-generating regimes, not between two levels of exposure**, and no
hop distance was going to fix that.

The exploratory `seed_rule="rips"` arm (crews with an actual recorded rip, 495 of 11,111) was
added after seeing the base rate and is reported in
`state/dregg_d4m/d4_reach_rips_hop_rip_rates-v1-*.parquet`. **It was not registered and
nothing ships from it**; it exists so the next lane does not have to rediscover that the
tighter seed is available.

## 4. What the semiring bought, since the estimand did not

The registration named the widest-path quantity `max_k min(J_ik, J_kj)` while calling it
"max-plus". Those are different semirings and the formula is the one that is correct for
chaining similarities: a two-hop crew link is only as strong as its weaker leg, and max-plus
would let a 0.11 + 0.99 chain beat a 0.55 + 0.54 one. **`max_min` is implemented and used**;
`max_plus` and `min_plus` exist beside it and are tested. The label in the registration was
wrong, the formula was right, and this note is the correction.

On the crew graph (12,538 wallets, 22,458 direct edges at `J >= 0.10`), the widest-path
product `G max-min G` surfaces **16,877 wallet pairs with no direct edge but a two-hop chain**
-- 75% again as many relations as the direct graph -- with a **strongest bottleneck of
0.667**: two wallets that share no qualifying edge, joined through an intermediary where both
legs clear a Jaccard of two thirds. Plus-times cannot express this at all; it would sum every
path and rank a wallet with many weak intermediaries above one with a single strong one.

This is a real object and it is in the artifact layer. It is **not** a validated crew
extension: no null was registered for it, so it is reported as a structure the algebra makes
available and not as a finding.

## 5. Limits

* **`is_rip` is the panel's label**, and section 3 is the argument that it is not comparable
  across the crew / non-crew split. Any future version of this analysis needs an outcome that
  is defined the same way in both populations.
* **`h >= 1` is thin**: 284, 101 and 50 coins. The registered test was underpowered and the
  registration did not say so in advance; that is a miss in the registration, not a result.
* **The 11-day gap is ignored here.** Hop distance is computed over the whole corpus, so a
  `h = 1` link may join a window-A wallet to a window-B wallet that never coexisted. Given
  `RESULT_d4m_communities.md`'s finding that 73% of crews are epoch-local, a windowed version
  of this analysis is the obvious next form and was not run.
