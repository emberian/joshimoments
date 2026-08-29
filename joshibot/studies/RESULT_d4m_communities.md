# RESULT: 3,366 birth-slot crews, 48.7x above chance -- and they do NOT survive the gap

Registered as D2 in `studies/REGISTRATION_d4m.md`. Code `dregg_d4m/analyses.py:d2_communities`;
artifacts `state/dregg_d4m/d2_communities_*`. Reproduce:
`uv run --group research python -m dregg_d4m d2`.

Prerequisite: D1's replication passed and D0's parity gate passed
(`studies/RESULT_d4m_crew_graph.md`). Without those this file would not have been written.

---

## 0. The one-paragraph answer

The wallet-wallet crew graph is real and large: **12,538 wallets, 22,458 edges** at the live
threshold, against a degree-preserving null of **461 edges (48.7x)** -- and the null's biggest
draw in ten was 501, so the observed graph is not in the null's tail, it is in a different
universe. Deterministic label propagation returns **3,366 crews of two or more wallets**
against **131** in the null.

**The persistence hypothesis fails, and it fails in the direction nobody registered.** Only
**920 of 3,366 crews (27.3%, 95% CI 25.9-28.9%)** act in both window A (2026-08-05..14) and
window B (2026-08-26..28). Holding each crew's coin count fixed and permuting only which coins
fall in window B, **79.4%** of crews would span the gap by chance (500 draws, sd 0.006,
**z = -83.9**, lower-tail p = 0.000). Birth-slot wallet crews are not merely failing to
persist -- they are **far more time-localised than their own coin counts can explain**.

The shippable consequence is a negative that changes product copy: **do not write "this crew
has been active for N weeks" from a wallet-community fingerprint.** Nearly three quarters of
them are epoch-local objects. The 920 that do span the gap are a named, identifiable minority
and are the only ones the claim is available for.

---

## 1. The graph, and what the null says about it

`G_ww = jaccard(B B')` over the ex-deployer birth-slot incidence, pruned at `overlap >= 2`,
cut at the live `jaccard >= 0.10`.

| threshold | nodes with an edge | edges | connected components | CC giant share | label-prop communities | LP giant share | ARI(LP, CC) |
|---|---|---|---|---|---|---|---|
| 0.05 | 13,054 | 26,329 | 2,363 | **0.211** | 3,356 | 0.004 | -- |
| **0.10** (registered) | **12,538** | **22,458** | 2,667 | 0.063 | **3,366** | **0.003** | 0.67 |
| 0.20 | 11,875 | 19,328 | 2,894 | 0.007 | 3,348 | 0.003 | -- |

**The union-find pathology is visible and was caught by printing it.**
`RESULT_svn_cotrading.md` section 8 and `RESULT_cluster_map.md` section 3 both record that
connected components merge a large fraction of this kind of graph into one blob. At the loose
cut it does exactly that -- **21.1%** of all clustered wallets in one component, against label
propagation's **0.4%**. At the registered cut it is 6.3% vs 0.3%. Every partition in this file
is label propagation; connected components are reported beside it so the failure is a checked
fact rather than a docstring.

Against the degree-preserving null (`studies.operator_crime._curveball`, reused verbatim,
10 draws):

| quantity | observed | curveball mean | ratio |
|---|---|---|---|
| edges at J >= 0.10 | **22,458** | 461.4 (max 501) | **48.7x** |
| wallets with an edge | 12,538 | 409.0 | 30.7x |
| communities of >= 2 wallets | 3,366 | 131.1 | 25.7x |

Degree structure alone -- every wallet's coin count and every coin's sniper count held exactly
fixed -- accounts for **2%** of the crew graph. This is the same statement `graph.json` makes
pairwise (0.26 vs a 0.0075 null) restated at the level of the whole graph, and it is the
licence for treating a community here as an object rather than an artifact.

## 2. Persistence across the 11-day gap

The corpus is two blocks with an unobserved gap: window A `2026-08-05..14`, window B
`2026-08-26..28`, and a noted regime shift between them. 28.7% of the 127,552 coins these
crews touched are window-B coins.

A crew "spans the gap" iff it has a birth-slot incidence in both windows.

| quantity | value |
|---|---|
| crews with >= 2 wallets | 3,366 |
| ... spanning the gap | **920** |
| share | **0.2733**, Wilson 95% CI [0.2585, 0.2886] |
| crew coin counts | median 6, mean 50.6, p90 81.5, max 9,652 |
| median coins, gap-spanning crews | 25 |
| median coins, epoch-local crews | 4 |

The last two rows are why the null in 2.2 holds each crew's coin count **fixed**: crews that
span the gap are busier, and a null that did not control for that would report the busyness
as persistence.

### 2.1 The registered null, and why its verdict is not usable as stated

Registered: curveball the wallet x coin incidence, re-cluster identically, recompute the
share; ship iff observed >= 3x the null mean and p <= 0.01.

| quantity | value |
|---|---|
| observed share | 0.2733 |
| curveball null mean (200 draws) | **0.7936** (sd 0.0258, p95 0.8333) |
| ratio over null | **0.344x** (ship rule needed >= 3x) |
| z | -20.2 |
| upper-tail p | 1.000 |

**The ship rule fails.** It also cannot be read as a persistence test, and the reason is
section 1's own number: the curveball *destroys the graph*. The null's crew graph has ~461
edges over ~409 wallets in ~131 communities. A "share of communities" computed over 131 tiny
groups drawn from 409 wallets is not the same measurement as one over 3,366 groups drawn from
12,538, and comparing them is not like-for-like. The registered statistic was a ratio when it
should have been a count, and that is a design error in the registration, disclosed here
rather than repaired quietly. **The un-confounded comparisons are the counts in section 1's
table, and they are all strongly positive.**

### 2.2 A better-posed null for the persistence question (POST-HOC, labelled)

The registered null demolishes the object under test. The question "would this crew have
touched both windows by chance?" is answered by holding the graph, the partition, and every
crew's coin count **fixed**, and permuting only which coins are window-B coins -- preserving
the 28.7% window-B share exactly. 500 draws:

| quantity | value |
|---|---|
| observed share | **0.2733** (920 of 3,366) |
| coin-permutation null mean | **0.7944** (sd 0.0062, p05 0.7840, p95 0.8048) |
| ratio | **0.344x** |
| z | **-83.9** |
| lower-tail p | **0.000** (0 of 500 draws at or below the observed) |

This is post-hoc and is reported after the registered result, never in place of it. It says
what the registered null could not: given how many coins each crew touched, **79% of them
should have straddled the gap and only 27% did.** Crews are concentrated in time to a degree
that has nothing to do with how busy they are.

### 2.3 What this means, plainly

Three readings fit and this instrument cannot separate them:

* **Turnover.** The wallets are disposable and a "crew" is re-provisioned between epochs, so
  the same operator reappears wearing different addresses. The deployer-anchored fingerprint
  (`REGISTRATION_crew_persistence.md` P3) would still work where this one does not; that
  study is the one that can tell them apart, and this file does not pre-empt it.
* **Genuine churn.** The operators themselves are short-lived.
* **The regime shift.** Something changed between 08-14 and 08-26 that retired a population.

What the instrument does establish is the shape of the decay, and the product consequence is
the same under all three readings: **a wallet-community crew id is a within-epoch identifier,
and the ledger's crew memory needs a rebuild cadence shorter than the 12 days this gap
measures.**

## 3. What is newly shippable

The graph and the partition are new objects. The shipped ledger could previously say "this
launch's sniper set matches a prior coin's at Jaccard J". It can now say who the crew IS:

> **Crew c1191 -- 4 wallets, 187 coins, 2026-08-05 to 2026-08-14. Not seen in the
> 2026-08-26..28 window.**

and, for the 920 that qualify:

> **Crew c2848 -- 6 wallets, 198 coins, active across both observation windows (2026-08-05
> through 2026-08-28, 149 of its birth-slot entries in the later one). One of 920 crews of
> 3,366 that survived the gap.**

Both are real rows from the artifact, not illustrations.

Both come straight out of `d2_communities_community_profile`, which carries `size`, `n_coins`,
`t_first`, `t_last` and `spans_gap` per crew. The second sentence is only available for the
27.3%, and that restriction is the finding, not a caveat on it.

## 4. Limits

* **Label propagation, not Infomap.** `studies.svn_cotrading.infomap_communities` is the
  repo's documented preference and was tried first; it does not return on a 12,538-node graph
  within two minutes, let alone 200 times for a null. The substitute is deterministic and its
  known degeneracy (unweighted regular graphs) is pinned by a test and does not apply to this
  weighted graph. Giant-component share is printed next to every partition so the pathology is
  observable if it ever fires.
* **A community is a "moves with" relation and nothing finer.** `RESULT_cluster_map.md`
  section 8's limit applies unchanged: this cannot separate one entity's wallets from a copy
  bot following that entity, nor either from a market maker.
* **`spans_gap` is bounded by the corpus.** A crew active 2026-08-20 is invisible; the gap is
  unobserved, not empty.
* **Section 2.2 is post-hoc.** It is a better-posed null, not a registered one, and it should
  be pre-registered and re-run before anything is built on it alone.
