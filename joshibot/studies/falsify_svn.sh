#!/usr/bin/env bash
# Falsification harness for signal #1. Break the estimator on purpose, confirm the guarding test
# goes RED, restore. Operates only on studies/svn_cotrading.py, which this spike owns outright.
#
# A test that stays green under a mutation is VACUOUS and is reported as such.
set -uo pipefail
cd ~/dev/joshibot
SRC=studies/svn_cotrading.py
BAK=$(mktemp -t svn_cotrading.orig)
cp "$SRC" "$BAK"
restore() { cp "$BAK" "$SRC"; }
trap restore EXIT

run() { # name, python-mutation, test-selector
  local name="$1" mut="$2" sel="$3"
  restore
  python3 - "$SRC" <<PY
import sys
p=sys.argv[1]; s=open(p).read()
before=s
$mut
assert s != before, "MUTATION DID NOT APPLY: $name"
open(p,"w").write(s)
PY
  if [ $? -ne 0 ]; then
    echo "MUTATION '$name' -> FAILED TO APPLY (source drifted)"
    return
  fi
  if uv run pytest "$sel" -q >/tmp/svn-mut.log 2>&1; then
    echo "MUTATION '$name' -> test STILL PASSED  ***VACUOUS***"
  else
    echo "MUTATION '$name' -> test FAILED (good)"
    grep -E '^FAILED' /tmp/svn-mut.log | sed 's/^/       /'
  fi
}

# 1. One test per pair instead of nine -- the x9 that Bonferroni's correction comes from.
run "family drops the x9 (one test per pair)" \
  's=s.replace("    return tests, 9 * testable, testable","    return tests, testable, testable")' \
  "tests/test_svn_cotrading.py::test_the_test_family_is_nine_per_pair_not_one"

# 2. Global T instead of the pair-specific window -- inflates every short-lived wallet.
run "global T instead of pair-specific" \
  's=s.replace("        total = index.total_in(window)","        total = len(panel.element_time)")' \
  "tests/test_svn_cotrading.py::test_T_is_pair_specific_and_a_global_index_would_inflate_significance"

# 3. BH replaced by an uncorrected per-test alpha.
run "BH-FDR replaced by raw alpha" \
  's=s.replace("        if log_p_values[position] <= log_q + math.log(rank) - log_m:","        if log_p_values[position] <= log_q:")' \
  "tests/test_svn_cotrading.py::test_bh_fdr_matches_a_hand_computation"

# 4. The family-size floor removed: correcting over the enumerated subset understates multiplicity.
run "BH family_size guard removed" \
  's=s.replace("    if family_size < len(log_p_values):\n        raise SvnError(\"family_size cannot be smaller than the number of enumerated tests\")","    if False:\n        raise SvnError(\"unreachable\")")' \
  "tests/test_svn_cotrading.py::test_fdr_correction_actually_binds"

# 5. Union-find instead of the map equation -- 4.1 measured a 99.6% blob.
run "clustering reverts to union-find" \
  's=s.replace("    return _MapEquation(edges).optimise()","    return union_find_components(edges)")' \
  "tests/test_svn_cotrading.py::test_union_find_blobs_where_the_map_equation_separates"

# 6. Curveball stops preserving the TOKEN margin, leaving the popularity artefact intact.
run "curveball breaks the token-degree margin" \
  's=s.replace("        current[left] = shared | set(pool[:take])\n        current[right] = shared | set(pool[take:])","        universe = sorted(set().union(*[set(r) for r in current]))\n        current[left] = set(rng.sample(universe, len(current[left])))\n        current[right] = set(rng.sample(universe, len(current[right])))")' \
  "tests/test_svn_cotrading.py::test_curveball_preserves_wallet_degree_and_token_degree_exactly"

# 7. The two nulls compared at matched p instead of matched density (the Cimini error).
run "matched p instead of matched density" \
  's=s.replace("    degree_ranked = sorted(degree_scores, key=lambda edge: (degree_scores[edge], edge))[:density]","    degree_ranked = sorted(e for e, v in degree_scores.items() if v <= math.log(p_floor))")' \
  "tests/test_svn_cotrading.py::test_nulls_are_compared_at_matched_density_not_matched_p"

# 8. The second null stops being a gate: a verdict on one null model alone.
run "robust-set guard removed" \
  's=s.replace("    if robust.n_same_action_edges == 0:","    if False:")' \
  "tests/test_svn_cotrading.py::test_the_degree_preserving_null_removes_the_popularity_artefact"

# 9. Watchlist selection no longer refused.
run "watchlist guard removed" \
  's=s.replace("    if panel.wallets_are_a_watchlist:\n        return (\n            VERDICT_UNRESOLVABLE,","    if False:\n        return (\n            VERDICT_UNRESOLVABLE,")' \
  "tests/test_svn_cotrading.py::test_a_watchlist_panel_can_never_report_suggestive"

# 10. The feasibility gate always passes.
run "feasibility gate always passes" \
  's=s.replace("        feasible=log_min_p <= log_threshold,","        feasible=True,")' \
  "tests/test_svn_cotrading.py::test_feasibility_gate_refuses_the_scope_program_md_4_1_refutes"

# 11. The wallet-count floor removed, so a 2-wallet panel produces a finding.
run "min_wallets floor removed" \
  's=s.replace("    if n_wallets < min_wallets:","    if False:")' \
  "tests/test_svn_cotrading.py::test_a_two_wallet_panel_is_unresolvable_not_a_number"

# 12. Opposite-action links folded into the clustering weight (wash pairs join rings).
run "opposite-action links carry clustering weight" \
  's=s.replace("        if test.type_key in SAME_ACTION:\n            same[test.key] += 1","        if test.type_key in SAME_ACTION or test.type_key in OPPOSITE_ACTION:\n            same[test.key] += 1")' \
  "tests/test_svn_cotrading.py::test_opposite_action_links_are_reported_rather_than_silently_dropped"

# 13. p-values clamped at float resolution: two very different pairs compare equal.
run "log p clamped at float underflow" \
  's=s.replace("        return min(_logsumexp(terms), 0.0)","        return max(min(_logsumexp(terms), 0.0), -690.0)")' \
  "tests/test_svn_cotrading.py::test_log_hypergeom_sf_orders_p_values_below_float_underflow"

# 14. The degeneracy this file was actually shipped with once: a z-score under a zero-variance
#     null sends every unreached pair to the same infinity, so the matched-density ranking is
#     index order. Found by the planted-recovery test, which is why both controls are required.
run "degree-preserving score reverts to a degenerate z" \
  's=s.replace("        rate = max(self.mean, self.p_floor)\n        return min(math.log(self.p_floor), _log_poisson_sf(observed, rate))","        return -math.inf if observed > self.mean else 0.0")' \
  "tests/test_svn_cotrading.py::test_planted_clusters_are_recovered"

# 16. The inverted gate stops depending on the activity floor, so the collection rule is noise.
run "max_feasible_wallets ignores the activity floor" \
  's=s.replace("    return max(n, 2)","    return UNBOUNDED_WALLETS")' \
  "tests/test_svn_cotrading.py::test_max_feasible_wallets_inverts_the_gate_into_a_collection_rule"

# 15. Round trips collapsed into buys, erasing one of the three states.
run "round-trip state collapsed into buy" \
  's=s.replace("            else:\n                states[wallet][key] = TradeState.ROUND_TRIP","            else:\n                states[wallet][key] = TradeState.BUY")' \
  "tests/test_svn_cotrading.py::test_states_are_derived_from_the_actual_sides"

restore
echo "restored"
