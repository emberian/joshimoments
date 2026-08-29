# REGISTRATION: the D4M lane -- associative-array algebra over the crew substrate

2026-08-29, registered BEFORE any estimand in D1-D4 was computed. Instrument will be
`dregg_d4m/` (`assoc.py`, `graphs.py`, `analyses.py`); artifacts to `state/dregg_d4m/`.
Tests in `tests/test_d4m_assoc.py`, `tests/test_d4m_parity.py`, `tests/test_d4m_nulls.py`.

## Why this lane exists

Kepner's D4M observation is that an associative array `A(row_key, col_key) -> value` with
string keys is a sparse matrix, and that most graph questions are one sparse product over the
right semiring. Several instruments in this repo hand-roll the product:
`dregg_screen/ledger.py:crew_match` computes a per-coin ex-deployer sniper set and then scans
it against stored per-coin sets ONE PAIR AT A TIME; `studies/operator_crime.py`'s cmd_graph
arm builds the same-deployer coin-pair list explicitly and calls `_mean_jaccard` over it.
Both are `B' B` over the plus-times semiring with a Jaccard normalisation applied to the
product. This lane does not propose a new statistic. It proposes the same statistics computed
as algebra, at a scale the pairwise form cannot reach, and it is only worth shipping if it
agrees EXACTLY with the validated instrument first.

## Author-knowledge disclosure

I know, before registering: cmd_graph's fresh numbers (same-deployer mean Jaccard 0.2608,
day-matched control 0.0026, curveball null mean 0.0075, p_curveball 0.0, from
`studies/data/operator_crime_fresh/graph.json`); the live match thresholds
(`min_overlap = 2`, `min_jaccard = 0.10`, `max_candidates = 200`); the shipped ledger's sizes
(11,111 crews / 122,567 crew coins / 463,334 crew-set rows / 14,731 distinct crew wallets);
`RESULT_cluster_map.md`'s 223-avoid / 67-pile-on / 10-null trichotomy over 300 cluster pairs
and its 13,462-cluster partition; `RESULT_svn_cotrading.md` section 5 (BH-FDR validates a mean
of 99 false edges per world under heavy-tailed popularity with zero planted coordination, in
30/30 worlds; a degree-preserving null deletes 100% of them) and section 8 (union-find puts
93-100% of a dense validated network into one component). I have computed the corpus shape
(636,136 ex-deployer birth-slot incidences over 59,524 wallets and 163,444 coins, and the
product flop budgets below) because that is a compute-sizing fact, not an estimand.

I have NOT computed: any coin-coin or wallet-wallet Jaccard from the algebra, any community
partition, any territory or predation statistic, any hop-distance rip rate, or any parity
outcome.

## Overlap with REGISTRATION_crew_persistence.md, declared

That registration's P3 measures cross-gap fingerprint persistence anchored on the DEPLOYER
(same-deployer A-coins vs B-coins). D2 below measures persistence of WALLET COMMUNITIES
derived without any deployer label. They are different objects and neither is a re-test of
the other; where they touch, this RESULT will cite that one rather than restate it.

## Compute budget, stated now so the caps are not a post-hoc choice

`sum_w deg(w)^2` over the ex-deployer incidence is 9.763e8 (the coin-coin product's flop
count) and `sum_c deg(c)^2` is 3.643e6 (the wallet-wallet product's). The wallet-wallet
product runs untruncated. The coin-coin product does not fit at full wallet degree, so a
wallet-degree cap is registered NOW at `<= 200 coins` (retains 58,998 of 59,524 wallets and
248,986 of 636,136 incidences; flops 1.331e7). The cap is a compute decision AND a modelling
one in the same direction as `cluster_map`'s `k > 50` exclusion -- a wallet on 13,847 coins
co-occurs with everything by construction. Sensitivity at caps {50, 100, 200, 500} is
reported, and the PARITY arm (D0) runs with NO cap at all, because parity against the shipped
instrument must not be bought with a filter.

## D0 -- PARITY, the credibility gate (not an estimand; a pass/fail on the instrument)

If the algebra disagrees with `dregg_screen.ledger.Ledger.crew_match`, the algebra is wrong
and nothing below ships.

Query set Q: corpus coins with a non-empty ex-deployer birth-slot sniper set that are NOT in
the ledger's `crew_coins` table (their deployer launched once, so they were never stored).
These are exact stand-ins for a live launch: the ledger has never seen them, so no self-match
can flatter the result. n = 3,000, drawn with `numpy.random.default_rng(20260829)`.

For each q the algebra computes `jaccard(B_q' B_crew)` with the ledger's own rules applied to
the product -- `overlap >= 2`, `jaccard >= 0.10`, and the `LIMIT 200 ORDER BY overlap DESC`
truncation emulated -- and the two are compared on `(matched_mint, overlap,
round(jaccard, 4))`.

PASS iff agreement is 100% on `(overlap, round(jaccard, 4))` and on `matched_mint` wherever
the argmax is unique. Ties (equal Jaccard on different mints) are counted and reported, not
excused.

Secondary, reported whatever D0 returns: how often the shipped `max_candidates = 200`
truncation changes the answer relative to the untruncated algebra. `ORDER BY overlap DESC`
is not the Jaccard order -- a smaller stored set with less overlap can score higher -- so the
truncation can drop the true best match. This is an instrument finding about the shipped
product, and it is reported as a rate with a Wilson 95% CI whether it is zero or not.

## D1 -- the crew graph at scale

Objects: `G_cc = jaccard(B_xd' B_xd)` (coin x coin, wallet-degree cap 200) and
`G_ww = jaccard(B_xd B_xd')` (wallet x wallet, untruncated), both pruned at `overlap >= 2`.

Registered check (this is what makes D1 a replication rather than a new number): restricted
to the same arm cmd_graph used, the mean of `G_cc` over same-deployer coin pairs must
reproduce `graph.json`'s 0.2608 to within +/- 0.010 absolute, and the day-matched
different-deployer control must reproduce 0.0026 to within +/- 0.001. The degree-preserving
null is `studies.operator_crime._curveball` REUSED VERBATIM -- the same randomisation that
validated the shipped instrument -- at 200 draws, and its mean must land within +/- 0.002 of
0.0075.

Falsifier: any of those three misses its band. Then the algebra is not computing the validated
statistic and D2-D4 are withdrawn.

## D2 -- crew communities and their persistence across the regime shift

Graph: `G_ww` thresholded at `jaccard >= 0.10` (the live threshold) and `overlap >= 2`.
Sensitivity at 0.05 and 0.20 reported.

Partitions, BOTH computed and BOTH reported: connected components (with
`giant_component_share` printed next to it, per `RESULT_svn_cotrading.md` section 8, which is
the documented failure mode) and deterministic label propagation (seeded, ties broken by
ascending wallet index, iterated to a fixed point or 50 rounds). Claims are made from label
propagation; connected components are reported to show whether the pathology fired.

Registered outputs: community count and size distribution; coins per community; and the
PERSISTENCE share -- the fraction of communities with >= 2 wallets that touch a coin in
window A (2026-08-05..14) AND a coin in window B (2026-08-26..28), across the 11-day
unobserved gap.

Null: `_curveball` on the coin x wallet incidence (200 draws), re-clustered identically, same
persistence share computed. Ship rule: the persistence claim ships iff the observed share is
>= 3x the curveball mean AND `p_curveball <= 0.01`. If it fails, the RESULT reports the
measured share against the null and says the wallet-community fingerprint does not survive
the gap.

## D3 -- territory and predation as algebra

Take the top 25 label-propagation communities by coin-universe size; all 300 unordered pairs.
`P` = community x wallet indicator; `U = binarize(P B_xd)` is community x coin; the shared-coin
matrix is `U U'` -- one product where `cluster_map` looped pairs.

Per pair: observed coin-universe Jaccard, 200 `_curveball` draws on the community x coin
incidence, z-score, and the avoid / pile-on / null trichotomy at |z| > 2 with cluster_map's
sign convention. Registered comparison: cluster_map found 223 avoid / 67 pile-on / 10 null.
This is a DIFFERENT partition on a DIFFERENT substrate (birth-slot snipers, not zero-crossing
exits) over a DIFFERENT window, so the registered claim is a SHAPE replication only -- that
avoidance dominates pile-on -- and it is called reproduced iff avoidance exceeds 50% of pairs.
No numeric agreement with cluster_map is claimed or expected.

Directional predation is NOT registered here: the birth-slot substrate has no exit leg, so the
"one fleet's selling lands inside another's buying" statistic of cluster_map section 4.2 is
not computable from `B`. Saying so is part of the deliverable.

## D4 -- hop distance to a dirty crew (the analysis that needs the algebra)

Seeds: wallets in ledger crews with `rips + dumps > 0` ("dirty"). Graph: `G_ww` at
`jaccard >= 0.10`, `overlap >= 2` -- the crew graph, not the promiscuity graph.

Over the boolean (or-and) semiring, `S A` and `S A A` give the 1- and 2-hop wallet frontiers
in two products. For each corpus coin not itself in a dirty crew, `h(c)` is the minimum hop
distance from its ex-deployer sniper set to any dirty-crew wallet, capped at 3 and otherwise
infinite.

Estimand: `P(is_rip | h)` for `h in {1, 2, 3, inf}`, Wilson 95% CIs, plus the same quantities
recomputed on 200 `_curveball` draws of the coin x wallet incidence -- because 2-hop
reachability inflates under a configuration model by construction and an uncalibrated
reachability number would be exactly the `svn_cotrading` failure mode in a new costume.

Ship rule: a hop-distance claim ships iff the `h = 1` and `h = 2` rip rates each exceed the
`h = inf` rate with NON-OVERLAPPING Wilson intervals AND each exceeds the 95th percentile of
the corresponding curveball null. The prior held before computing is that this FAILS at
`h = 2` and possibly at `h = 1`; a negative here is the registered, expected, publishable
outcome, and it is written up either way.

Also reported from this arm, as the semiring's own justification: the max-plus product's
strongest 2-hop chain weight `max_k min(J_ik, J_kj)` for the surfaced pairs, which the
plus-times product cannot express.

## D5 -- the caller matrix, and its expected veto

`C` = caller x coin from `state/callouts/*.jsonl` (`author_username` x `mints`). Before any
co-occurrence is computed, `studies.svn_cotrading.feasibility_gate` and `max_feasible_wallets`
are run on it, REUSED not reimplemented. The corpus shape is 778 authors, 367 mints, 703
pairs. If the gate vetoes, the deliverable is the veto with its arithmetic and no caller
co-occurrence statistic is reported at all.

## Structure-preserving discipline, stated once

Every null in D1-D4 is `studies.operator_crime._curveball`, degree-preserving on the relevant
bipartite incidence, holding every row degree and every column degree exactly. No i.i.d.
shuffle appears anywhere in this lane. `RESULT_svn_cotrading.md` section 5 is the reason: on
worlds with zero planted coordination, the popularity-only null validated 99 false edges per
world in 30 of 30 worlds, and the degree-preserving null deleted all of them. A test in
`tests/test_d4m_nulls.py` reproduces that failure mode against this lane's own estimator and
shows the null defeats it; if it does not, this lane ships nothing.

## Honest-negative clause

If D1 reproduces cmd_graph and D2-D4 surface no structure the set-based instruments did not
already give us, the RESULT says exactly that -- "the algebra is faster and cleaner and found
no new structure" -- and the deliverable is the reusable layer plus the parity proof. That
outcome is registered as acceptable now so it cannot be quietly upgraded later.
