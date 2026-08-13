#!/usr/bin/env bash
# Falsification harness: break the resolver on purpose, confirm the guarding test goes RED,
# then restore. Operates only on studies/entity_resolution.py, which this lane owns outright.
#
# A test that still passes against a broken resolver has no content. Every MUTATION below is a
# defect this project could plausibly ship; the one that matters most is #1, because a resolver
# without hub exclusion merges an exchange's entire withdrawal set into one entity and every
# downstream temporal split silently becomes a one-entity split.
set -uo pipefail
cd ~/dev/joshibot
SRC=studies/entity_resolution.py
BAK=$(mktemp -t entity_resolution.orig)
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
    echo "MUTATION '$name' -> ***DID NOT APPLY*** (source drifted; the matrix is stale)"
    return
  fi
  if uv run pytest "$sel" -q >/tmp/joshi-entity-mut.log 2>&1; then
    echo "MUTATION '$name' -> test STILL PASSED  ***VACUOUS***"
  else
    echo "MUTATION '$name' -> test FAILED (good): $(grep -cE '^FAILED' /tmp/joshi-entity-mut.log) failing"
    grep -E '^FAILED' /tmp/joshi-entity-mut.log | sed 's/^/       /'
  fi
}

# 1. CEX / hub exclusion disabled. The super-cluster failure, unguarded.
run "hub exclusion removed" \
  's=s.replace("    fanout = funder_fanout(first)\n    return frozenset(","    fanout = funder_fanout(first)\n    return frozenset(x for x in [] if x) if True else frozenset(")' \
  "tests/test_entity_resolution.py::test_cex_hub_funding_thousands_of_unrelated_wallets_does_not_collapse_them"

# 2. Curated exchange list ignored; only the degree rule survives.
run "operator exchange list ignored" \
  's=s.replace("        if funder in exchanges or fanout[funder] >= hub_degree","        if fanout[funder] >= hub_degree")' \
  "tests/test_entity_resolution.py::test_operator_exchange_list_excludes_a_funder_the_degree_rule_would_keep"

# 3. Global super-cluster tripwire removed.
run "supercluster tripwire removed" \
  's=s.replace("            suppressed.update(members)","            pass")' \
  "tests/test_entity_resolution.py::test_chained_sources_build_a_supercluster_that_is_suppressed"

# 4. A suppressed component is emitted anyway.
run "suppressed component emitted" \
  's=s.replace("        if members[0] in suppressed:\n            continue","        if False:\n            continue")' \
  "tests/test_entity_resolution.py::test_suppressed_wallets_are_absent_not_emitted_as_singletons"

# 5. First funder taken as the LAST inbound transfer instead of the earliest.
run "first funder = latest not earliest" \
  's=s.replace("        if current is None or edge.order_key < current.order_key:","        if current is None or edge.order_key > current.order_key:")' \
  "tests/test_entity_resolution.py::test_first_funder_is_the_earliest_by_slot_not_the_first_row_seen"

# 6. Self-funding treated as a linkage relation.
run "self-funding accepted" \
  's=s.replace("        if edge.funder == edge.funded:\n            continue","        if False:\n            continue")' \
  "tests/test_entity_resolution.py::test_self_funding_is_not_a_link"

# 7. Relay/paymaster co-signers not excluded: one relayer merges its whole customer base.
run "cosigning relay hub rule removed" \
  's=s.replace("    links: list[Link] = []\n    for row in sorted(cosignatures","    hubs = frozenset()\n    links: list[Link] = []\n    for row in sorted(cosignatures")' \
  "tests/test_entity_resolution.py::test_relay_cosigner_hub_does_not_merge_its_customers"

# 8. Jito protocol cap on bundle size removed.
run "bundle cap removed" \
  's=s.replace("        if len(wallets) > max_bundle_wallets:\n            refused += 1\n            continue","        if False:\n            refused += 1\n            continue")' \
  "tests/test_entity_resolution.py::test_bundle_over_the_protocol_cap_is_refused"

# 9. Unsigned co-occurrence merged by default -- the airdrop sprayer eats its victims.
run "unsigned co-occurrence accepted by default" \
  's=s.replace("    if allow_unsigned_cooccurrence:\n        links.extend(unsigned)","    if True:\n        links.extend(unsigned)")' \
  "tests/test_entity_resolution.py::test_unsigned_cooccurrence_is_refused_by_default"

# 10. Fee-payer sponsorship merged by default -- the live-store false positive, shipped.
run "sponsor edges trusted by default" \
  's=s.replace("    if trust_sponsor_edges:\n        links.extend(sponsor)","    if True:\n        links.extend(sponsor)")' \
  "tests/test_entity_resolution.py::test_sponsor_edges_are_refused_by_default_and_merge_two_unrelated_wallets_when_trusted"

# 11. The method field collapsed to one value: which heuristic did the work becomes unknowable.
run "method field collapsed" \
  's=s.replace("                        method=method,\n                        confidence=METHOD_CONFIDENCE[method],","                        method=SHARED_FIRST_FUNDER,\n                        confidence=METHOD_CONFIDENCE[SHARED_FIRST_FUNDER],")' \
  "tests/test_entity_resolution.py::test_a_wallet_merged_by_two_sources_emits_one_record_per_method"

# 12. Unassigned wallets pooled into one bucket in the concentration measure -- invents an entity.
run "unassigned wallets pooled in top10" \
  's=s.replace("            grouped[assignment.get(wallet, wallet)] += amount","            grouped[assignment.get(wallet, \"unassigned\")] += amount")' \
  "tests/test_entity_resolution.py::test_unassigned_wallets_are_their_own_entity_in_the_delta"

# 13. Output made order-dependent: the star anchor follows input order rather than sort order.
run "output order-dependent" \
  's=s.replace("    ordered = sorted(set(members))","    ordered = list(dict.fromkeys(members))").replace("    for wallet, edge in sorted(first.items()):","    for wallet, edge in first.items():")' \
  "tests/test_entity_resolution.py::test_resolution_is_deterministic_under_input_shuffling"

# 14. Withheld wallets excused rather than scored as singletons -- makes the tripwire look free.
run "withheld wallets excused in scoring" \
  's=s.replace("            pred = f\"unassigned:{wallet}\"","            continue")' \
  "tests/test_entity_resolution.py::test_pairwise_scores_treat_a_withheld_wallet_as_a_singleton"

# 15. The calibration generator tuned to flatter the resolver: no exchange-funded wallets at all.
run "generator plants no unlinkable wallets" \
  's=s.replace("    cex_withdrawal_rate: float = 0.30,","    cex_withdrawal_rate: float = 0.0,")' \
  "tests/test_entity_resolution.py::test_planted_world_is_recovered_with_perfect_pair_precision"

restore
echo "restored"
