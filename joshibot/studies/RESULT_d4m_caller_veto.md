# RESULT: the caller x coin matrix is not a network, and the repo's own gate says so

Registered as D5 in `studies/REGISTRATION_d4m.md`: build `C` = caller x coin, then run
`studies.svn_cotrading.feasibility_gate` on it **before** computing any co-occurrence
statistic, and if it vetoes, report the veto and nothing else.

Reproduce: `uv run --group research python -m dregg_d4m d5`.

## The verdict

**VETO.** No caller co-occurrence statistic is reported.

`C` from `state/callouts/*.jsonl` (`author_username` x `mints`, keys verbatim):

| quantity | value |
|---|---|
| authors with >= 1 named mint | **398** |
| distinct mints / mint candidates | **367** |
| (author, mint) pairs | **703** |
| median mints per author | **1** |
| 90th percentile | 2 |
| busiest author | 52 mints |
| most-called mint | 132 authors |

`feasibility_gate` at alpha = 0.01 over the 9 x C(398, 2) = **711,027** typed tests:

| activity floor | log10 Bonferroni threshold | log10 best attainable p | feasible | max universe at this floor |
|---|---|---|---|---|
| N = 1 (median author) | -7.852 | **-2.565** | **no** | **2 wallets** |
| N = 2 (p90 author) | -7.852 | **-4.827** | **no** | **12 wallets** |

The best case available to *any* pair -- complete overlap of their mint sets -- is five
orders of magnitude short of the threshold. Inverting the gate gives the collection rule:
at this index size (367 mints) and this activity floor, the design supports **12 authors**,
and we have 398. The gap is 33x, and it is not closable by collecting more of the same
thing; it closes by raising the activity floor or enlarging the index, exactly as
`RESULT_svn_cotrading.md` section 6.3 lays out.

## Why this was the expected answer, and why it was still worth running

`state/callouts/` is mostly a **per-operator-coin census**: the `cluster_census_*` files were
collected by searching for four specific coins. So the coin marginal is a property of what we
went looking for, not of what the market talked about. A co-occurrence graph over that matrix
would measure our own collection plan -- the same defect `RESULT_svn_cotrading.md` section 2
records for the two-wallet watchlist, where the estimator was forced to `UNRESOLVABLE` even
though a p-value could have been printed.

Running the gate rather than asserting the conclusion costs one function call and produces a
number the next person can act on: **12**. That is the caller universe this index supports.
The artifact `d5_caller_author_degree` carries every author's mint count so the collection
side can see how far the floor would have to move.

## What this closes off

The registration's D4 mentioned a possible caller-and-crew co-occurrence analysis ("do callers
and crews co-occur"). **It is not computable at this n**, and D4 was spent on hop distance
instead. That substitution is recorded here rather than left as a quiet omission.
