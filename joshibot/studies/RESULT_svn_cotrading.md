# Signal #1 — coordinated-cluster detection by Statistically Validated Networks

**Verdict on the signal: UNRESOLVABLE-AT-THIS-N.** The existing store holds **two** wallets whose
activity periods overlap for 5.15 hours and which share **two** mints, neither of which is inside
that overlap. Zero of the nine typed tests for the single available pair can even be performed. No
estimator survives that, and none was allowed to report a number.

**Result on the instrument, which is not null.** Built against realistic synthetic worlds with
known planted rings, the estimator recovers coordination at **precision 1.000** and recall 0.13–0.33,
and — the finding worth carrying forward — it **measures PROGRAM.md §4.1's blocking risk and shows
it is real and large**: under heavy-tailed token popularity with *zero planted coordination*,
BH-FDR validates a mean of **99 false edges per world** (at least one in **30 of 30** worlds), and
the Bonferroni familywise error rate is **0.600 against a nominal 0.01 — a 60× exceedance**. A
degree-preserving null deletes **100%** of those false edges in every world tested. The
hypergeometric null alone is not usable on this data at BH coverage, and that was previously a
worry rather than a number.

**Helius spend: 0 credits.** Everything here reads a *copy* of the existing sqlite store or a
seeded simulation.

Reproduce:

```
cp intelligence_state/intelligence.sqlite3 /tmp/intel_copy.sqlite3   # the daemon holds a lock
uv run python -m studies.svn_cotrading --mode store --store /tmp/intel_copy.sqlite3 --seed 20260813
uv run python -m studies.svn_cotrading --mode simulated --seed 20260813 --randomisations 200
```

Deterministic given the seed, read-only, no network at run time. Estimator:
`studies/svn_cotrading.py`. Tests: `tests/test_svn_cotrading.py` (36). Falsification harness:
`studies/falsify_svn.sh` (16 mutations, 16 kills).

---

## 1. The question

For each pair of wallets, count co-occurrences of **trading states** across an index of tokens.
A wallet's state on a token is one of buy-only / sell-only / round-trip, so the pair variable is
3×3 = **nine typed tests**. Under the null of independent activity the co-occurrence count is
hypergeometric given each wallet's own marginals and the index size. Validate, then extract
communities.

Pre-registered before any estimate was looked at:

| # | object | decision rule |
|---|---|---|
| 1 | same-action validated edges (bb, ss, rr) | Bonferroni at α = 0.01 over the **performed** family |
| 2 | same-action validated edges | BH-FDR at q = 0.05 over the same family |
| 3 | edges surviving a **degree-preserving** null at **matched density** | the object handed downstream |
| 4 | communities | weighted two-level map equation (Infomap core), never union-find |
| 5 | opposite-action edges (bs, sb) | reported separately as wash-trading candidates, never clustered |

Everything in this document is corrected against **PROGRAM.md §4.1**, not against the brief's
summary of the method. §4.1 is explicit that the "overlap ≥5 → p ≈ 3e-6" power claim was our own
construction and was false; that claim is not used here, and §7.2 below reproduces §4.1's own
arithmetic as an executable gate.

---

## 2. n at every stage — the real store

| stage | n |
|---|---|
| `wallet_transaction` rows in the store | 1,578 |
| … kept by `shitcoims_tape.backfill.load_intelligence_wallet_transactions` | **1,250** |
| … skipped by that importer, all causes | 328 |
| … of which: ambiguous multi-leg (one SOL delta, several token legs) | 110 |
| … of which: address unrecoverable (lowercased base58) | 173 |
| … importer-flagged as carrying no block time | 180 |
| … of the 1,250 kept trades, dropped at panel build for no block time | 166 |
| prints entering the panel (block time required) | **1,084** |
| distinct mints in the index | **667** |
| **distinct wallets** | **2** |
| testable pairs (activity periods overlap) | 1 |
| test family (9 × testable pairs) | 9 |
| **typed tests actually performable** | **0** |

The two wallets:

| wallet | first fill (chain) | last fill (chain) | mints |
|---|---|---|---|
| `Sh1WNJ…` (our own sentinel) | 2026-08-12T14:50:01Z | 2026-08-13T12:34:06Z | 96 |
| `GV6UUm…` (Ansem's declared wallet) | 2026-08-08T01:21:50Z | 2026-08-12T19:59:15Z | 573 |

**Activity-period intersection: 5.15 hours.** Shared mints across all time: **2**. Neither of them
first appears inside the 5.15-hour window, so the pair-specific index size `T` is nonzero but the
co-occurrence count is zero for all nine types, and the estimator enumerates nothing.

Three independent refusals fire, and each would have been sufficient on its own:

1. **`n = 2 < min_wallets = 20`.** A "network" on one pair has no community structure to find,
   whatever the p-values say. This is the guard that fires first.
2. **The wallet set is a watchlist.** These two addresses are in `intelligence.yaml` because a
   human put them there. A validated edge over a hand-picked set measures our own selection rule.
   The panel carries `wallets_are_a_watchlist=True` and the verdict is forced to UNRESOLVABLE even
   if every other check passed.
3. **Zero performable tests.** Nothing to correct, nothing to cluster.

This matches the signal-#3 spike's finding exactly, from the other direction: `wallet_transaction`
is `getTransactionsForAddress` over a two-address watchlist, not a firehose. It is a 2-wallet
panel, and neither a co-trading graph nor an arrival process can be built from it.

---

## 3. n at every stage — the simulated panel the estimator was built against

`--mode simulated --seed 20260813` (240 wallets, 400 tokens, 6 rings × 8 members, 9 ring tokens
each at 85% participation, Zipf popularity exponent 1.1, wallet lifetimes 35% of a 14-day horizon,
B = 200 randomisations):

| stage | n |
|---|---|
| wallets | 240 |
| index elements (tokens) | 312 |
| prints | 2,713 |
| testable pairs | 19,444 |
| **tests performed** (9 × testable) | **174,996** |
| naive upper bound (9 × C(240,2)) | 258,120 |
| planted same-ring pairs | 168 |
| pair base rate | **0.00586** |
| log₁₀ Bonferroni threshold | **−7.243** |
| log₁₀ BH threshold at the realised cut | −4.389 |

The correction is applied over tests **performed**, not over tests enumerated. Most pairs never
co-occur at all and have p = 1 by definition; they are not enumerated (that would be O(n²)
certainties) but they **are** in the denominator. `bh_fdr_log` refuses a `family_size` smaller than
the enumerated array precisely so that shortcut cannot be taken silently, and
`test_fdr_correction_actually_binds` pins that shrinking the family strictly enlarges the
rejection set.

---

## 4. The two null models, compared at matched density

### 4.1 What each one validates at its own threshold

| null | threshold | validated tests | same-action edges | opposite | mixed | Infomap clusters | largest |
|---|---|---|---|---|---|---|---|
| hypergeometric | Bonferroni 10⁻⁷·²⁴ | 52 | **52** | 0 | 0 | 6 | 8 |
| hypergeometric | BH q = 0.05 | 143 | 141 | 1 | 1 | 10 | 8 |
| degree-preserving | its p-floor, **uncorrected** | 1,781 | 857 | 384 | 522 | 22 | 27 |
| degree-preserving | BH on its discrete p | 0 | 0 | 0 | 0 | — | — |
| **both, at matched density** | K = 52 | **15** | **15** | 0 | 0 | **5** | 6 |

**The order-of-magnitude spread across nulls at nominally comparable thresholds is 52 vs 857 —
16×.** That is Cimini et al. 2022 (Comms Phys 5:76) reproduced on our own data, and it is why the
comparison below is on density and not on p.

### 4.2 Why the degree-preserving null cannot be thresholded at all here

Its empirical p cannot go below `1/(B+1)`. At 240 wallets the Bonferroni threshold is 10⁻⁷·²⁴, so
matching it would need **B > 1.7 × 10⁷ randomisations**. A draw costs 0.03–0.15 s at these sizes,
so that is **6–30 days of CPU per study**. BH on the discrete p is worse than useless rather than
merely coarse: every test pinned at the floor carries the *same* p, so BH is a step function of how
many happen to tie there. Here 1,781 tests sit at the floor while the BH rank they would need is
17,412, so it rejects **0** — and the moment the tied block crossed that rank it would reject all
1,781 at once. Neither number is a threshold.

**Matched density is therefore not Cimini's preference in our setting. It is the only comparison
that exists.** `test_the_degree_preserving_p_floor_cannot_reach_the_bonferroni_threshold` pins the
arithmetic.

### 4.3 What changed between the two nulls

| quantity | value |
|---|---|
| matched density K | 52 |
| edges in both | **15** |
| hypergeometric-only | 37 |
| degree-preserving-only | 37 |
| Jaccard | 0.169 |
| adjusted Rand index between the two partitions | **0.246** |

At matched density the two nulls agree on **29%** of edges and their community partitions agree at
ARI 0.246. On a world where six rings were *planted by construction*, which wallets look
coordinated is substantially a property of the null model. That is the honest headline for anyone
who plans to act on a cluster list.

**The estimator therefore hands downstream only the intersection** — 15 edges, 5 clusters,
16 wallets — and every `EntityLink` carries the agreement fraction as its `confidence`.

### 4.4 The randomisation, stated precisely

Curveball trades on the wallet × token incidence matrix, preserving **exactly**: every wallet's
token count, every token's participant count, and every wallet's own multiset of states. It does
**not** preserve each token's state composition; that would need a joint model this sample cannot
identify. Below the empirical floor the ranking uses a Poisson upper tail calibrated to the null's
own mean — a **ranking device for the density match, never quoted as a p-value**.

---

## 5. Type-I calibration — §4.1's blocking risk, measured

§4.1: *"The hypergeometric null assumes roughly uniform marginals across the index… Memecoin
activity is a launch spike with power-law decay… A stratified or configuration-model null is a
precondition, not a refinement."* That was a prediction. Here is the measurement.

**Zero planted coordination. 150 wallets, 300 tokens, 11,175 pairs, 30 independent worlds per
cell.** The only thing varying is how heavy the token-popularity tail is and how active wallets are.

| Zipf exponent | tokens per wallet | **FWER (Bonferroni, nominal 0.01)** | P(≥1 BH edge) | mean Bonferroni edges | **mean BH edges** |
|---|---|---|---|---|---|
| 0.0 (uniform — what the null assumes) | 20–60 | 0.000 (0/30) | 0.000 (0/30) | 0.00 | 0.00 |
| 1.1 | 20–60 | 0.000 (0/30) | 0.033 (1/30) | 0.00 | 0.03 |
| 2.2 | 4–14 | 0.033 (1/30) | 0.100 (3/30) | 0.03 | 0.10 |
| **2.2** | **20–60** | **0.600 (18/30)** | **1.000 (30/30)** | **1.17** | **99.00** |

Read the last row carefully. On data containing **no coordination whatsoever**, BH-FDR validates a
mean of 99 wallet pairs out of 11,175 — and it does so in **every single world**. Bonferroni is far
more robust but still exceeds its nominal familywise rate by **60×**.

Both conditions are needed: a heavy tail *and* active wallets. That combination is not a corner
case, it is exactly the population §4.1 says we want ("the *active bot wallets we actually want*…
two wallets each on 100 of 300 tokens"). The naive version of this study, run on real active-wallet
data with BH coverage, would produce a hundred confident wallet clusters out of nothing.

**The degree-preserving null removes all of it.** Same worlds, full pipeline:

| seed | Bonferroni edges | BH edges | **robust edges** | verdict |
|---|---|---|---|---|
| 1 | 3 | 157 | **0** | NULL |
| 2 | 0 | 34 | **0** | NULL |
| 3 | 0 | 48 | **0** | NULL |
| 4 | 1 | 81 | **0** | NULL |
| 5 | 0 | 44 | **0** | NULL |

100% of the false discoveries are deleted and the verdict is correct in **5 of 5** worlds run
through the full pipeline (the randomisation null costs ~25 s per world, which is why the FWER
table above is 30 worlds and this one is 5). `test_heavy_tailed_token_popularity_inflates_the_hypergeometric_null` and
`test_the_degree_preserving_null_removes_the_popularity_artefact` pin both halves.

---

## 6. Power analysis at our actual n

### 6.1 Recovery of planted rings

Bonferroni, α = 0.01, Zipf 1.1, rings of 9 tokens at 85% participation, T = 300, mean of 5 seeds:

| wallets | ring size | planted pairs | validated edges | **precision** | **recall** |
|---|---|---|---|---|---|
| 60 | 4 | 18.0 | 4.6 | **1.000** | 0.256 |
| 60 | 8 | 28.0 | 3.6 | **1.000** | 0.129 |
| 120 | 4 | 36.0 | 9.8 | **1.000** | 0.272 |
| 120 | 8 | 84.0 | 27.8 | **1.000** | 0.331 |
| 240 | 4 | 36.0 | 10.0 | **1.000** | 0.278 |
| 240 | 8 | 168.0 | 45.8 | **1.000** | 0.273 |
| 400 | 4 | 36.0 | 5.6 | **1.000** | 0.156 |
| 400 | 8 | 168.0 | 36.4 | **1.000** | 0.217 |

**Precision is 1.000 everywhere; recall never exceeds 0.33.** The method is a specificity
instrument, not a census. Any downstream use that needs "all members of the ring" is not supported;
"these wallets are together" is. Recall *falls* as the universe grows, because the Bonferroni
threshold tightens as n² while the evidence per pair does not move.

### 6.2 Minimum detectable overlap

For two wallets each active on `N` of T = 300 tokens, the smallest shared-token count `k` that
clears Bonferroni:

| wallets | log₁₀ threshold | N = 5 | N = 10 | N = 20 | N = 50 |
|---|---|---|---|---|---|
| 150 | −7.002 | k ≥ 4 | k ≥ 6 | k ≥ 10 | k ≥ 23 |
| 1,000 | −8.653 | k ≥ 5 | k ≥ 7 | k ≥ 11 | k ≥ 25 |
| 5,000 | −10.051 | k ≥ 5 | k ≥ 8 | k ≥ 12 | k ≥ 26 |

Note the shape §4.1 warned about and this confirms: the requirement is **not** a fixed overlap
count. A pair on 50 tokens each needs 23–26 shared, because λ = N²/T is already 8.3 — an overlap
of 5 is *under*-expressed for such a pair, with p ≈ 1.

### 6.3 The feasibility gate, and how to invert it

§4.1's gate, `C(T, N) ≥ 9 n(n−1)/(2α)`, is implemented as `feasibility_gate` and runs before
anything else. It reproduces §4.1's own arithmetic exactly:

| scope | log₁₀ Bonferroni threshold | log₁₀ smallest attainable p | feasible |
|---|---|---|---|
| n = 50,000, T = 300, N = 5 | −12.051 | −10.292 | **NO** |
| n = 5,000, T = 300, N = 5 | −10.051 | −10.292 | yes (barely) |
| n = 1,415, T = 300, N = 5 | −8.954 | −10.292 | yes |
| n = 240, T = 400, N = 10 | −7.412 | −19.412 | yes, 12 orders of headroom |

Inverting it turns a veto into a collection rule. **The maximum wallet universe at which any pair
can still validate**, by index size and activity floor:

| index size T | N ≥ 2 | N ≥ 3 | N ≥ 5 | N ≥ 8 | N ≥ 10 |
|---|---|---|---|---|---|
| 300 | **10** | 100 | 6,597 | 1,814,180 | 55,743,863 |
| 1,000 | 33 | 608 | 135,403 | 231,493,127 | ≥10⁹ |
| 3,000 | 100 | 3,161 | 2,117,786 | ≥10⁹ | ≥10⁹ |

This is the operational output of the whole feasibility argument, and it points the opposite way
from "the design is dead at 50k wallets". **Admitting tourists is what kills it**: at T = 300, a
universe that includes wallets touching two tokens is capped at *ten* wallets, while requiring
eight tokens supports 1.8 million. The activity floor is not a taste parameter — it is set by the
universe size, and `max_feasible_wallets` computes it.

---

## 7. Baselines before models (§3 rule 4), and what the SVN is actually worth

| method | AUPRC | precision@52 | pair base rate |
|---|---|---|---|
| **popularity baseline** (raw same-action co-occurrence count) | **0.979** | 1.000 | 0.00586 |
| SVN, hypergeometric (−log p) | 0.961 | 1.000 | 0.00586 |
| SVN, degree-preserving (−log score) | 0.921 | 1.000 | 0.00586 |

AUPRC and precision@k, never accuracy or ROC-AUC: the positive class is 0.59% of pairs and ROC-AUC
would read ~0.99 for a scorer useless at any operating point anyone would use.

**The popularity baseline ranks better than the SVN.** That is not a bug and it is not a reason to
drop the method — it is the honest statement of what the method buys. Raw co-occurrence count is a
fine *ordering*; what it cannot give you is a **cut** with a stated false-discovery control, a
principled *threshold*, or an answer to "how many of these are real". The SVN's entire contribution
is the threshold and the null comparison. Reporting only the SVN number would be claiming a
ranking improvement it does not have. `test_recovery_is_reported_against_a_popularity_baseline_first`
pins the ordering of the report.

---

## 8. Clustering: union-find is the documented failure, not the answer

§4.1: connected components put 99.6% of the FDR network and 81% of the Bonferroni network into one
blob. Reproduced at our scale, on the dense networks where it bites:

| network | edges | union-find components | **giant-component share** | Infomap clusters | largest |
|---|---|---|---|---|---|
| BH, heavy tail, zero coordination | 157 | 4 | **0.931** | 20 | 12 |
| degree-preserving at its floor | 2,148 | 1 | **1.000** | 3 | 83 |
| Bonferroni, planted world | 52 | 6 | 0.250 | 6 | 8 |

The pathology appears exactly when the validated network is dense — and **you cannot know which
regime you are in before you look**, which is why `giant_component_share` is printed next to every
clustering result rather than mentioned in a docstring. On the sparse Bonferroni network union-find
happens to agree with Infomap; on the BH network it merges 93% of the graph.

The clustering is the two-level map equation (Rosvall & Bergstrom), optimised by deterministic
local moving plus an explicit module-merge pass. Modularity was not used: its resolution limit
would merge precisely the small validated cliques this study exists to find.

---

## 9. Method — every choice, and the failure it is answering

**Nine typed tests per pair, not one.** The state variable is 3-valued (buy / sell / round-trip)
crossed with itself. Collapsing to "did both trade it" understates the correction by 9× *and*
discards the direction that separates an accumulation ring from two strangers in the same hot
token. §4.1 names this; the ×9 in the Bonferroni denominator is where it comes from.

**T is pair-specific.** The index size for a pair is the number of tokens that existed inside the
**intersection of the two wallets' activity periods**, and each marginal is recounted inside that
same window. A global T for a wallet that lived four hours inflates significance without bound, and
short-lived wallets are the entire population. `test_T_is_pair_specific_…` asserts quantitatively
that the honest p is strictly larger than the global-T p on the same overlap.

**Log-space p-values throughout.** The interesting p-values run past 1e-300. Two pairs at 1e-400
and 1e-500 both become exactly `0.0` as floats and then compare **equal**, silently destroying the
ranking that matched density and every top-k report depend on. The log-space tail is verified
against exact rational arithmetic (`math.comb` + `Fraction`) at six parameter settings and on both
tail branches.

**Chain time is the origin, and the store's clocks are un-inverted by the tape importer.** For
`wallet_transaction` rows the block time is in `emitted_at` and the fetch stamp in `observed_at` —
the reverse of the same store's social rows. `shitcoims_tape.backfill.load_intelligence_wallet_transactions`
is the one place that knows this, so the study calls it rather than re-deriving the convention.
That importer also refuses multi-leg transactions instead of splitting one SOL delta across legs
(110 rows here) and refuses unrecoverable lowercased addresses (173 rows). Both refusals are
counted, never repaired.

**Opposite-action links are kept.** Tumminello's recipe deletes them before clustering. §4.1: *"for
us those are the likeliest wash-trading signature, so adopting it verbatim would discard the thing
we most want to see."* They are excluded from the clustering **weight** — a wash pair must not join
an accumulation ring — and reported as their own network for signal #4.

**Entity-level output, so a downstream split cannot straddle.** The estimator emits interface #7
`EntityLink` records from the **robust** network only, with `confidence` = the fraction of that
wallet's validated same-action edges that survive the change of null model. A link that exists only
under one null gets a low confidence, not a footnote.

**Temporal split, never random.** The holdout validates on the early half of the index and re-tests
on the late half, split on index elements so a pair cannot appear on both sides through the same
token. The control is pairs that co-occur in the training half but do **not** validate.

**A null is a result.** The verdict ladder returns NULL when the hypergeometric validates nothing,
and *also* when it validates edges that no degree-preserving randomisation reproduces — the second
being the artefact signature §5 measures. SUGGESTIVE requires surviving both.

---

## 10. Falsification matrix

Every mutation was applied to `studies/svn_cotrading.py`, the guarding test run, the file restored.
**16 of 16 killed their test. None was vacuous.** Reproduce with `bash studies/falsify_svn.sh`.

| # | mutation | guarding test | outcome |
|---|---|---|---|
| 1 | family drops the ×9 (one test per pair) | `the_test_family_is_nine_per_pair_not_one` | **RED** |
| 2 | global T instead of pair-specific | `T_is_pair_specific_and_a_global_index_would_inflate_significance` | **RED** |
| 3 | BH-FDR replaced by uncorrected α | `bh_fdr_matches_a_hand_computation` | **RED** |
| 4 | BH `family_size` guard removed | `fdr_correction_actually_binds` | **RED** |
| 5 | clustering reverts to union-find | `union_find_blobs_where_the_map_equation_separates` | **RED** |
| 6 | curveball breaks the token-degree margin | `curveball_preserves_wallet_degree_and_token_degree_exactly` | **RED** |
| 7 | matched **p** instead of matched **density** | `nulls_are_compared_at_matched_density_not_matched_p` | **RED** |
| 8 | robust-set guard removed (verdict on one null) | `the_degree_preserving_null_removes_the_popularity_artefact` | **RED** |
| 9 | watchlist guard removed | `a_watchlist_panel_can_never_report_suggestive` | **RED** |
| 10 | feasibility gate always passes | `feasibility_gate_refuses_the_scope_program_md_4_1_refutes` | **RED** |
| 11 | `min_wallets` floor removed | `a_two_wallet_panel_is_unresolvable_not_a_number` | **RED** |
| 12 | opposite-action links carry clustering weight | `opposite_action_links_are_reported_rather_than_silently_dropped` | **RED** |
| 13 | log p clamped at float underflow | `log_hypergeom_sf_orders_p_values_below_float_underflow` | **RED** |
| 14 | degree-preserving score reverts to a degenerate z | `planted_clusters_are_recovered` | **RED** |
| 15 | round-trip state collapsed into buy | `states_are_derived_from_the_actual_sides` | **RED** |
| 16 | `max_feasible_wallets` ignores the activity floor | `max_feasible_wallets_inverts_the_gate_into_a_collection_rule` | **RED** |

**Mutation 14 is not hypothetical — it is a bug this estimator actually shipped for one iteration,
and it is the reason both controls are mandatory.** The first version ranked the degree-preserving
null by a z-score. Under a null that produced the *same value in every draw* the variance is zero,
so every pair the null never reached scored `+inf` and the matched-density ranking degenerated to
array index order. The zero-coordination control stayed **green** throughout — an estimator that
detects nothing passes a null-recovery test perfectly. Only the planted-recovery test caught it
(AUPRC 0.176, precision@k 0.000). A suite with only a false-positive control is satisfied by a
broken instrument; a suite with only a recovery control is satisfied by one that fires at
everything.

The three tests the brief mandates are named literally: `test_planted_clusters_are_recovered`,
`test_independent_wallets_yield_no_validated_edges`, `test_fdr_correction_actually_binds`.

---

## 11. Budget arithmetic

**Spent on this study: 0 Helius credits.** A copy of the existing sqlite store, plus simulation.

For the collection §12 recommends, at `getTransactionsForAddress` = 10 credits per 100 transactions
(parsed raw — the Enhanced API is 100 credits per *call*):

| scope | credits | share of the 10M/month plan |
|---|---|---|
| 300 tokens × 5,000 trades | 150,000 | **1.50%** |
| 400 tokens × 5,000 trades | 200,000 | 2.00% |
| 1,000 tokens × 5,000 trades | 500,000 | 5.00% |
| 3,000 tokens × 2,000 trades | 600,000 | 6.00% |

The first row reproduces PROGRAM.md §4's "300 tokens × 5k trades = 1.5% of monthly credits" to the
credit. But §6.3 adds the constraint §4 does not state: **300 tokens × 5,000 trades will surface
tens of thousands of distinct wallets, most of them one-token tourists, and at T = 300 the universe
is capped at 10 wallets if they are all admitted.** The collection is cheap; the *scoping* is where
the design lives. Either watch ≥1,000 tokens or set the activity floor from
`max_feasible_wallets` before a pair is tested.

CPU: the full simulated study at 240 wallets with B = 200 runs in ~8 s. Matching the Bonferroni
threshold empirically would need B > 1.7 × 10⁷, i.e. ~30 days — which is the argument in §4.2, not
a performance note.

---

## 12. Verdict, and what would change it

**UNRESOLVABLE-AT-THIS-N** on the signal.

Explicitly *not* NULL: a null would assert that coordinated clusters are absent or rare in this
population. Nothing here licenses that. Two wallets, 5.15 hours of overlap, zero performable tests —
the study has no power at any effect size, and §6.1 shows what power at real n looks like.

Explicitly *not* SUGGESTIVE: nothing was validated on real data, and the only wallets available are
ones we chose ourselves.

**The instrument result is separate and is not null.** The hypergeometric null is unusable at BH
coverage on heavy-tailed activity (99 false edges per world on zero coordination, FWER 0.600 at
Bonferroni against a nominal 0.01), and a degree-preserving null removes 100% of the artefact.
That is a property of the method, measured, and it binds any future run.

### What has to be true before this question can be asked again

1. **A mint-indexed multi-wallet tape.** Not per-wallet histories — every fill on each watched
   mint, which is what makes the wallet set a *sample* rather than a watchlist. `shitcoims_tape`
   already has `PumpFirehose` (program-level `transactionSubscribe`) and `HeliusHistorySource`
   (budget-charged, 10 credits/page). Nothing else in signal #1 is worth doing first.
2. **≥ 300 index elements and a wallet universe scoped by `max_feasible_wallets`,** with the
   activity floor set *before* testing. Admitting one-token wallets caps the universe at ten.
3. **Wallet activity periods that actually overlap.** The binding constraint on the real store was
   not sample size, it was that the two wallets barely coexisted.

### Falsification conditions for any future SUGGESTIVE

A SUGGESTIVE from this estimator is falsified by any one of:

- **(a)** the validated edge set not surviving the degree-preserving null at matched density —
  already a hard gate in the verdict ladder, and the check that turned §5's 99 false edges into a
  correct NULL;
- **(b)** the same edges appearing at comparable density when the *token popularity distribution
  alone* is what generated the data, i.e. the §5 control run at the observed tail exponent
  returning a comparable edge count with zero planted coordination;
- **(c)** the clusters failing to reconfirm in the temporal holdout **at a rate above the control
  rate** — reported over the *eligible* denominator, since a ring that operated entirely inside one
  fold cannot reconfirm and its zero is structural, not evidential (measured here: 16 eligible train
  edges, 0 reconfirmed, control 0.0046 over 2,375 eligible pairs — the holdout is uninformative for
  time-localised rings and must not be read as a refutation);
- **(d)** the union-find giant-component share on the validated network approaching 1, which means
  the "clusters" are one blob and the partition is an artefact of the community detector;
- **(e)** the popularity baseline matching or beating the validated set on precision@k, which would
  mean the null model contributed nothing beyond raw co-occurrence counting;
- **(f)** the wallet set turning out to be selected rather than sampled — the same trap as signal
  #3's endogenous arm, where a closed loop produced p = 0.005 and a 240× lift out of our own bot.

---

## 13. What the next experiment should be

Ranked by what unblocks the most.

1. **Collect a mint-indexed panel: 300–1,000 pump.fun mints, every fill, 2–4 weeks.** 1.5–5% of one
   month's Helius credits. This is the same collection signal #3 needs and the same one signal #2
   builds on, so it is one spend against three signals. Use the recorder's `WatchWindow` so absence
   inside a window is evidence of zero and absence outside it is no information.

2. **Set the activity floor from `max_feasible_wallets` before testing anything.** This is the
   cheapest correction available and it is a pre-registration, not a tuning knob: T and the intended
   universe size determine N, and the number should be written down before the panel is built.

3. **Run the pre-registered study as written, unchanged.** The pipeline, both nulls, the guards and
   the tests are ready; only the data is missing. Re-registering the same five objects keeps the
   trials count honest.

4. **Then, and only then, the second hypergeometric layer.** §4.1 notes what we had missed: the
   paper carries a *second* hypergeometric test for over/under-expression of cluster **attributes**
   — "is this cluster over-expressed in rugs, in sniper labels, in one deployer's tokens". That is
   the paper's only real validation and it is the bridge from signal #1 to signals #4 and #5. It
   costs nothing extra once clusters exist and it is the first thing that could make a cluster
   *actionable* rather than merely detected.

5. **Do not expect it to pay by itself.** Tumminello does no economic validation — no returns, no
   PnL, no predictive test — and only 7 of its 30 largest clusters showed any validated
   compositional signature. This method establishes that coordinated groups are *detectable*. It
   establishes nothing about whether detecting them makes money, and the honest next question after
   step 4 is whether cluster membership shifts any base rate that PROGRAM.md §1.1 already measures.

**One structural warning for whoever runs it.** The trap here is the mirror image of signal #3's.
There, a closed loop over our own policy manufactured a 240× lift. Here, the analogous artefact is
already measured: run this method with BH coverage on real active-wallet data and it will hand you
about a hundred confident wallet clusters with nothing behind them. The degree-preserving null is
not a refinement to add later. It is the thing that makes the output mean anything.
