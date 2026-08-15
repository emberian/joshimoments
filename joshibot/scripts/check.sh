#!/usr/bin/env bash
# The merge gate. Every swarm wave ends here.
#
# Why this exists: three lanes each reported green on 2026-08-13 and the tree was still only
# provably sound once they were built TOGETHER — per-file green hides a broken downstream.
# It also runs the checks that catch the two failure modes this project keeps meeting: a
# vacuous test that cannot fail, and a Lean theorem resting on `sorry`.
#
#   scripts/check.sh          gate only (fails the build)
#   scripts/check.sh --full   gate, then report untracked typing debt without failing
#
# Never runs sentinel.py / intel.py / scout.py: those sign, trade and spend.

set -uo pipefail
cd "$(dirname "$0")/.."

# Never write bytecode during a gate run. CPython invalidates a cached .pyc on
# (source mtime in SECONDS, source size), so a mutation that is the SAME BYTE LENGTH and is
# written and reverted inside one second leaves the MUTATED bytecode running against the
# RESTORED source. That was reproduced live in this repo: a `>=` changed to `> ` (identical
# length) kept failing after the file was restored, and only a __pycache__ purge cleared it.
# It corrupts mutation testing in BOTH directions, including a false "killed" that lets a real
# hole through -- which is worse, because it reads as evidence. Anyone doing write/run/restore
# mutation work by hand must clear __pycache__ between steps; this makes the gate itself immune.
export PYTHONDONTWRITEBYTECODE=1

fail=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mok\033[0m %s\n' "$1"; }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

# NOTE on scope: `scripts/lp/` is deliberately OUT of the blocking gate. Those are one-shot
# exploration scripts, preserved so studies/RESULT_lp_history.md is reproducible, and holding
# throwaway extraction code to library lint standards makes the gate red for reasons unrelated
# to correctness -- which is how a gate stops being a signal. The durable tool that replaced
# them, scripts/lp_report.py, IS gated. See scripts/lp/README.md.
step "ruff"
if uv run ruff check sentinel.py intel.py scout.py shitcoims_sentinel shitcoims_intelligence \
    shitcoims_scout shitcoims_tape shitcoims_paperdesk studies scripts/lp_report.py tests \
    >/tmp/joshi-ruff.log 2>&1; then
  ok "lint clean"
else
  tail -20 /tmp/joshi-ruff.log; bad "ruff"
fi

step "mypy (gated set: executor, transaction, domain, tape)"
if uv run mypy >/tmp/joshi-mypy.log 2>&1; then
  ok "$(grep -c '' /tmp/joshi-mypy.log >/dev/null && echo 'gated modules type-clean')"
else
  tail -20 /tmp/joshi-mypy.log; bad "mypy"
fi

step "pytest"
if uv run pytest >/tmp/joshi-pytest.log 2>&1; then
  ok "$(grep -aE 'passed|failed' /tmp/joshi-pytest.log | tail -1)"
else
  tail -25 /tmp/joshi-pytest.log; bad "pytest"
fi

# A skipped parity test hides Python/Lean drift exactly as well as no test at all.
step "kernel parity did not skip"
if grep -qE '[0-9]+ skipped' /tmp/joshi-pytest.log; then
  grep -E '[0-9]+ skipped' /tmp/joshi-pytest.log; bad "tests skipped (is the lean oracle built?)"
else
  ok "no skipped tests"
fi

step "dashboard (tsc + eslint + render tests)"
if npm test >/tmp/joshi-npm.log 2>&1; then
  ok "typecheck, lint and render tests pass"
else
  tail -20 /tmp/joshi-npm.log; bad "dashboard"
fi

step "lean kernel"
if (cd kernel && lake build && lake build joshi-oracle) >/tmp/joshi-lake.log 2>&1; then
  ok "kernel and oracle build"
else
  tail -20 /tmp/joshi-lake.log; bad "lake build"
fi

# A `sorry` compiles, warns once, and then sits in the tree looking like a theorem.
step "kernel has no sorry"
if grep -rn '\bsorry\b' kernel/Joshi >/tmp/joshi-sorry.log 2>&1; then
  cat /tmp/joshi-sorry.log; bad "kernel contains sorry"
else
  ok "no sorry in kernel"
fi

# The stronger check: a theorem can be sorry-free and still rest on one transitively, and
# `native_decide` quietly adds ofReduceBool. Only the three standard axioms are acceptable.
step "kernel axiom audit"
cat > /tmp/joshi-ax.lean <<'LEAN'
import Joshi
#print axioms Joshi.Reserves.sellOut_le_reserve
#print axioms Joshi.Reserves.sellOut_mono
#print axioms Joshi.Position.no_basis_never_stops
#print axioms Joshi.Position.no_threshold_never_stops
#print axioms Joshi.Position.every_expressible_stop_fires_at_zero
#print axioms Joshi.decision_depends_only_on_the_view
#print axioms Joshi.toStrategy_reads_only_the_visible_prefix
#print axioms Joshi.exposure_bounded
#print axioms Joshi.admitted_spend_within_pool
#print axioms Joshi.Dlmm.outAmount_le_holdings
#print axioms Joshi.Dlmm.outAmount_never_overpays
#print axioms Joshi.Dlmm.powQ64_zero
#print axioms Joshi.run_exposure_conserved
#print axioms Joshi.exposure_monotone_of_entries
#print axioms Joshi.capacity_recoverable
#print axioms Joshi.release_restores_capacity
#print axioms Joshi.tripped_breaker_admits_no_entry
#print axioms Joshi.tripped_breaker_cannot_increase_exposure
#print axioms Joshi.tripped_breaker_is_absorbing_on_entries
LEAN
if (cd kernel && LEAN_PATH=.lake/build/lib/lean lean /tmp/joshi-ax.lean) >/tmp/joshi-axout.log 2>&1; then
  if grep -qE 'sorryAx|ofReduceBool' /tmp/joshi-axout.log; then
    cat /tmp/joshi-axout.log; bad "a theorem rests on sorryAx or native_decide"
  else
    ok "all theorems rest only on propext / Quot.sound / Classical.choice"
  fi
else
  tail -10 /tmp/joshi-axout.log; bad "axiom audit did not run"
fi

if [ "${1:-}" = "--full" ]; then
  step "typing debt outside the gate (informational)"
  uv run mypy shitcoims_sentinel shitcoims_intelligence shitcoims_scout sentinel.py intel.py scout.py \
    2>/dev/null | tail -1 || true
fi

printf '\n'
if [ "$fail" -eq 0 ]; then
  printf '\033[32mgate passed\033[0m\n'
else
  printf '\033[31mgate FAILED\033[0m\n'
fi
exit "$fail"
