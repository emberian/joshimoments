#!/usr/bin/env bash
# Falsification harness: break the estimator on purpose, confirm the guarding test goes RED,
# then restore. Operates only on studies/callout_flow.py, which this spike owns outright.
set -uo pipefail
cd ~/dev/joshibot
SRC=studies/callout_flow.py
BAK=$(mktemp -t callout_flow.orig)
cp "$SRC" "$BAK"
restore() { cp "$BAK" "$SRC"; }
trap restore EXIT

run() { # name, python-mutation, test-selector
  local name="$1" mut="$2" sel="$3"
  restore
  python3 - "$SRC" <<PY
import sys
p=sys.argv[1]; s=open(p).read()
$mut
open(p,"w").write(s)
PY
  if uv run pytest "$sel" -q >/tmp/mut.log 2>&1; then
    echo "MUTATION '$name' -> test STILL PASSED  ***VACUOUS***"
  else
    echo "MUTATION '$name' -> test FAILED (good): $(grep -cE '^FAILED' /tmp/mut.log) failing"
    grep -E '^FAILED' /tmp/mut.log | sed 's/^/       /'
  fi
}

# 1. Defeat hour matching in the PRODUCTION sampler.
run "hour matching removed" \
  's=s.replace("            base = day_zero + timedelta(days=day, hours=callout_at.hour)","            base = day_zero + timedelta(days=day, hours=(callout_at.hour + day * 7) % 24)")' \
  "tests/test_callout_flow_study.py::test_known_zero_effect_is_not_detected"

# 2. Separation uses the post window only -- the documented prior-study bug.
run "separation = post only" \
  's=s.replace("    separation = max(pre, post)","    separation = post")' \
  "tests/test_callout_flow_study.py::test_placebo_separation_uses_max_of_pre_and_post_not_post_alone"

# 3. Count the PRE window instead of the post window.
run "window counts pre not post" \
  's=s.replace("    end = at + post","    end = at\n    at = at - post")' \
  "tests/test_callout_flow_study.py::test_known_injected_effect_is_recovered"

# 4. Estimator returns a constant zero.
run "partial_pool returns zero" \
  's=s.replace("    thetas = [theta for _, theta, _ in effects]\n    variances","    return (0.0, 1.0, 0.0)\n    thetas = [theta for _, theta, _ in effects]\n    variances")' \
  "tests/test_callout_flow_study.py::test_known_injected_effect_is_recovered"

# 5. Trade clock read from the fetch stamp instead of block time.
run "trade time = observed_at" \
  's=s.replace("    emitted = observation.get(\"emitted_at\")","    emitted = observation.get(\"observed_at\")")' \
  "tests/test_callout_flow_study.py::test_trade_chain_time_is_emitted_at_not_observed_at"

# 6. Structural-zero guard removed.
run "structural-zero guard removed" \
  's=s.replace("    elif primary.n_placebo_arrivals == 0:","    elif False:")' \
  "tests/test_callout_flow_study.py::test_structural_zero_baseline_is_unresolvable_not_a_giant_effect"

# 7. p_floor understated (claims finer resolution than the replicate count supports).
run "p_floor understated" \
  's=s.replace("    p_floor = 1.0 / (1.0 + n)","    p_floor = 1.0 / (1.0 + n) / 10.0")' \
  "tests/test_callout_flow_study.py::test_p_floor_is_the_resolution_and_p_never_goes_below_it"

# 8. BH-FDR replaced by uncorrected per-hypothesis alpha.
run "BH-FDR replaced by raw alpha" \
  's=s.replace("        if p_values[index] <= q * rank / n:","        if p_values[index] <= q:")' \
  "tests/test_callout_flow_study.py::test_bh_fdr_matches_hand_computation"

restore
echo "restored"
