#!/usr/bin/env python3
"""Which numbers in this tree are guesses wearing the costume of facts?

Nearly every material error found in this repo on 2026-08-13/14 was a hardcoded number
that should have been measured:

  * `shitcoims_scalper/policy.py` assumed a 500,000-lamport priority fee. The tape's
    median network fee is 55,000 and our own landing policy budgets 21,000-53,000.
    `B* = sqrt(priority * Y)` therefore sized ~3-5x too large for a whole shadow run.
  * `shitcoims_scalper/policy.py` assumed a flat 100 bps swap fee. Measured effective
    take on our own six pools runs 20.0 bps (DREGG/SOL, SOLVE/SOL) to 908.7 bps
    (weave/SOL) -- a 45x spread. One constant cannot be right anywhere.
  * "Solana gas is ~$0.30" is repeated in three files. It is the *configured priority-fee
    ceiling* ($0.379 at 5,000,000 lamports) read as the typical cost. The measured median
    is $0.0042 and the policy budget is $0.0016-$0.0040.
  * GeckoTerminal caps OHLCV at 500 bars. 500 bars was read as "full history" and produced
    a 22-day age for a 47.6-day-old token. An INSTRUMENT LIMIT read as a fact.

So this is a standing check, not a one-off grep. Four classifications, and the
classification is the whole point -- the grep is trivial, deciding which bucket a number
belongs in is not:

  A  MUST BE DERIVED   varies in reality and is measurable from data we already hold
  B  LEGITIMATE        protocol-fixed or mathematical; correct as a constant, listed here
                       so nobody "fixes" it later
  C  POLICY CHOICE     a decision, not a measurement; correct as a constant but it must be
                       VISIBLE (module constant / config / CLI flag), never buried in a
                       function body
  D  INSTRUMENT LIMIT  an API cap, page size, or lookback treated as a fact about the
                       world. The most dangerous class, because it looks like a measurement

Usage
-----
    uv run python studies/hardcode_audit.py              # ranked report + inventory
    uv run python studies/hardcode_audit.py --json       # structured, for diffing
    uv run python studies/hardcode_audit.py --measure    # re-measure the A-class values
    uv run python studies/hardcode_audit.py --check      # CI gate: registry drift + new
                                                         #   unclassified money-path literals

`--check` is the part that makes this a check rather than a document. It fails when a
REGISTERED finding has moved, changed value, or been fixed (so the registry gets updated
rather than silently rotting), and when a new unexplained numeric literal appears in a
money-path file.

Read-only. Imports nothing from the sentinel's execution path.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parent.parent
TAPE = REPO / "state" / "cluster_tape"
LAMPORTS_PER_SOL = 1_000_000_000

# Checked against Coinbase spot (75.795) and Kraken last (75.79) at 2026-08-14T08:00Z.
# Re-check before quoting any dollar figure from this file; it is here to convert
# lamports for the report, and it is exactly the kind of number this audit is about.
SOL_USD_AT_AUDIT = 75.795
SOL_USD_SOURCE = "Coinbase spot 75.795 / Kraken last 75.79, 2026-08-14T08:00Z"


# --------------------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------------------

#: Packages scanned, with a blast-radius weight. The weight is "what depends on this
#: number if it is wrong": 10 = signs or sizes a real transaction, 1 = formats a report.
PACKAGES: dict[str, int] = {
    "shitcoims_sentinel": 10,  # LIVE-ARMED; signs and broadcasts
    # TypeScript, so the AST scanner does not read it -- but it WRITES the policies the
    # live sentinel acts on, so a number wrong here is money. Weighted accordingly and
    # covered by the registry rather than by the literal walk.
    "app": 9,
    "shitcoims_scalper": 8,  # sizes positions; shadow today, money tomorrow
    "shitcoims_cluster": 5,  # the tape everything else measures against
    "shitcoims_tape": 5,
    "shitcoims_intelligence": 4,
    "shitcoims_netmap": 4,  # decides whether an arb is worth doing
    "shitcoims_replay": 4,  # off-policy value estimates
    "shitcoims_scout": 3,
    "shitcoims_kernel": 3,
    "kernel_svm": 3,
    "scripts": 2,
    "studies": 2,
}

#: Files where a wrong number is money in the next block, not a wrong row in a report.
#: A new unexplained literal here fails `--check`.
MONEY_PATH: tuple[str, ...] = (
    "shitcoims_sentinel/executor.py",
    "shitcoims_sentinel/transaction.py",
    "shitcoims_sentinel/clients.py",
    "shitcoims_sentinel/policies.py",
    "shitcoims_sentinel/lots.py",
    "shitcoims_scalper/policy.py",
    "shitcoims_scalper/shadow.py",
)

SKIP_DIRS = {
    "__pycache__", ".venv", "node_modules", ".git", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".lake", "dist", ".next", "build",
}


# --------------------------------------------------------------------------------------
# Classification vocabulary
# --------------------------------------------------------------------------------------

#: Values that are protocol-fixed or mathematical wherever they appear. Class B on sight.
#: Listed so that a future pass does not "derive" 10_000 basis points from data.
UNIVERSAL_B: dict[float, str] = {
    1_000_000_000: "LAMPORTS_PER_SOL / 1e9",
    1_000_000: "microlamports per lamport; also 1e6 for USDC-scale decimals",
    10_000: "basis points in unity",
    1_000: "milli-units / ms per second",
    100: "percent in unity (ambiguous with 100 bps -- see per-site notes)",
    86_400: "seconds per day",
    3_600: "seconds per hour",
    5_000: "lamports per signature (Solana base fee, protocol-fixed)",
    32: "bytes in a Pubkey; also the getMultipleAccounts / simulation address ceiling",
    8: "bytes in an Anchor discriminator",
    255: "u8 ceiling (max token decimals)",
    1.96: "z for a two-sided 95% normal interval",
    0.05: "conventional alpha (context-dependent: also a policy epsilon)",
}

#: Identifier fragments that mean "this varies in reality and we can measure it".
DERIVE_NAMES = re.compile(
    r"fee|priorit|slippage|price|usd|depth|reserve|liquid|decimal|latenc|"
    r"spread|volatil|impact|tvl|gas|cu_price|compute_unit|bps|rate|apy|apr",
    re.I,
)

#: Identifier fragments that mean "this is an instrument's limit, not the world's".
#: Anchored where a bare fragment would over-match: `top` is in `below_stop_streak`,
#: `bars` is in `bars_seen`. A false D is expensive here -- it is the class we most
#: need people to actually read.
INSTRUMENT_NAMES = re.compile(
    r"limit|page_size|per_page|offset|max_items|max_results|maxresults|max_events|"
    r"batch|backfill|capacity|cache_size|dedupe_window|chunk|\btop_?\d|\bhead\b|"
    r"lookback|horizon|\bwindow|\bbars\b|candles|max_signatures|max_transactions|"
    r"page_cap|max_rows|max_pages|\bcap\b",
    re.I,
)

#: Identifier fragments that mean "someone decided this".
POLICY_NAMES = re.compile(
    r"max_exposure|max_position|max_drawdown|max_attempts|max_sol_cost|"
    r"eps|epsilon|explore|pause|cooldown|hold|stop_loss|take_profit|trailing|"
    r"retry|poll|heartbeat|dedup|grace|delay|interval|timeout|threshold|min_|max_",
    re.I,
)


# --------------------------------------------------------------------------------------
# Literal collection
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Literal:
    """One numeric literal with enough context to classify it."""

    path: str
    line: int
    value: float
    name: str  # assignment target, keyword, or enclosing function
    context: str  # assign | default | keyword | compare | fallback_or | fallback_get | except | bare
    scope: str  # module | function name
    source: str  # the stripped source line

    @property
    def package(self) -> str:
        return self.path.split("/", 1)[0]

    @property
    def weight(self) -> int:
        return PACKAGES.get(self.package, 1)

    @property
    def is_fallback(self) -> bool:
        return self.context.startswith("fallback") or self.context == "except"

    def to_json(self) -> dict[str, Any]:
        cls, why = classify(self)
        return {
            "path": self.path,
            "line": self.line,
            "value": self.value,
            "name": self.name,
            "context": self.context,
            "scope": self.scope,
            "class": cls,
            "reason": why,
            "weight": self.weight,
            "source": self.source,
        }


def _numeric(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            return None
        return float(node.value)
    # -N parses as UnaryOp(USub, Constant)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _numeric(node.operand)
        return None if inner is None else -inner
    return None


class _Collector(ast.NodeVisitor):
    """Walk one module, recording every numeric literal with its syntactic role.

    The role is what makes classification possible: `.get("decimals", 0)` and
    `DECIMALS = 0` are the same literal and completely different problems.
    """

    def __init__(self, path: str, lines: list[str]) -> None:
        self.path = path
        self.lines = lines
        self.out: list[Literal] = []
        self.scope: list[str] = ["module"]
        self._seen: set[tuple[int, float, str]] = set()

    # -- helpers ------------------------------------------------------------------

    def _src(self, line: int) -> str:
        return self.lines[line - 1].strip() if 0 < line <= len(self.lines) else ""

    def _emit(self, node: ast.AST, name: str, context: str) -> None:
        value = _numeric(node)
        if value is None:
            return
        line = getattr(node, "lineno", 0)
        key = (line, value, context)
        if key in self._seen:
            return
        self._seen.add(key)
        self.out.append(
            Literal(
                path=self.path,
                line=line,
                value=value,
                name=name,
                context=context,
                scope=self.scope[-1],
                source=self._src(line),
            )
        )

    def _enter(self, name: str) -> None:
        self.scope.append(name)

    def _exit(self) -> None:
        self.scope.pop()

    # -- scopes -------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        defaults = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
        positional = [a.arg for a in (args.posonlyargs + args.args)]
        names = positional[-len(args.defaults) :] if args.defaults else []
        names += [a.arg for a in args.kwonlyargs if a is not None]
        for index, default in enumerate(defaults):
            self._emit(default, names[index] if index < len(names) else node.name, "default")
        self._enter(node.name)
        for child in node.body:
            self.visit(child)
        self._exit()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node.name)
        self.generic_visit(node)
        self._exit()

    # -- assignment ---------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        name = _target_name(node.targets[0]) if node.targets else "?"
        self._walk_value(node.value, name, "assign")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        name = _target_name(node.target)
        if node.value is not None:
            self._walk_value(node.value, name, "assign")
        self.generic_visit(node)

    def _walk_value(self, value: ast.AST, name: str, context: str) -> None:
        """A literal on the right of `NAME =` inherits NAME, through arithmetic and tuples."""
        if _numeric(value) is not None:
            self._emit(value, name, context)
            return
        if isinstance(value, (ast.BinOp,)):
            self._walk_value(value.left, name, context)
            self._walk_value(value.right, name, context)
        elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            for element in value.elts:
                self._walk_value(element, name, context)

    # -- silent fallbacks ---------------------------------------------------------

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # `x or 0` -- an invented number substituted when real data is absent.
        if isinstance(node.op, ast.Or):
            for value in node.values[1:]:
                self._emit(value, _describe(node.values[0]), "fallback_or")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        # `d.get("k", 0)` -- default-on-missing.
        if isinstance(func, ast.Attribute) and func.attr == "get" and len(node.args) == 2:
            key = node.args[0]
            label = key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "?"
            self._emit(node.args[1], str(label), "fallback_get")
        for keyword in node.keywords:
            if keyword.arg:
                self._walk_value(keyword.value, keyword.arg, "keyword")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # A number produced *by* an error path is a fabricated measurement.
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                self._emit(child.value, "except-return", "except")
            elif isinstance(child, ast.Assign) and child.targets:
                self._emit(child.value, _target_name(child.targets[0]), "except")
        self.generic_visit(node)

    # -- comparisons --------------------------------------------------------------

    def visit_Compare(self, node: ast.Compare) -> None:
        left = _describe(node.left)
        for comparator in node.comparators:
            self._emit(comparator, left, "compare")
        self.generic_visit(node)


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _describe(node.value)
    return "?"


def _describe(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _describe(node.func)
    if isinstance(node, ast.Subscript):
        inner = node.slice
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            return str(inner.value)
        return _describe(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "?"


def python_files() -> Iterator[Path]:
    for package in PACKAGES:
        root = REPO / package
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            yield path


def collect() -> list[Literal]:
    out: list[Literal] = []
    for path in python_files():
        rel = str(path.relative_to(REPO))
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=rel)
        except (OSError, SyntaxError):
            continue
        collector = _Collector(rel, text.splitlines())
        collector.visit(tree)
        out.extend(collector.out)
    return out


# --------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------

#: Per-site rulings that override the heuristics. This is the human judgement the grep
#: cannot supply; key is "path:line-ish" matched by (path, value, name).
OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("shitcoims_scalper/policy.py", "priority_fee_lamports"): (
        "A",
        "measured: tape median network fee 55,000 lamports; landing policy budgets 21,000-53,000",
    ),
    ("shitcoims_scalper/policy.py", "swap_fee_bps"): (
        "A",
        "measured: 20.0-908.7 bps across six pools (scripts/sim2real.py)",
    ),
    ("shitcoims_scalper/shadow.py", "priority_fee_lamports"): ("A", "same constant, second copy"),
    ("shitcoims_scalper/shadow.py", "fee_bps"): ("A", "same constant, second copy"),
    ("shitcoims_netmap/physics.py", "DEFAULT_GAS_USD"): (
        "A",
        "the configured priority-fee CEILING read as a typical cost; measured $0.0042",
    ),
    ("shitcoims_sentinel/clients.py", "SIMULATION_ADDRESS_LIMIT"): (
        "B",
        "Solana simulation accounts ceiling, protocol-fixed",
    ),
    ("shitcoims_scalper/feed.py", "VIRTUAL_SOL_FLOOR_LAMPORTS"): (
        "B",
        "pump.fun initial virtual SOL reserve; program config, readable from the global account",
    ),
    ("shitcoims_sentinel/clients.py", "TIGHT_EXIT_SLIPPAGE_BPS"): (
        "A",
        "a tolerance that should be a minOut computed from live reserves",
    ),
    ("shitcoims_scalper/policy.py", "rho_max_bps"): (
        "C",
        "PROGRAM.md §1.4 pool-impact ceiling; a policy choice, but repeated at :94 and :168",
    ),
    ("shitcoims_sentinel/clients.py", "usd"): (
        "C",
        "a missing DexScreener liquidity.usd becomes 0, so it CAN form the `drained` half of a "
        "rug verdict -- but rug_detector.py:91 requires an independent Jupiter quote collapse "
        "too, so one provider's absent field can never fire a sell on its own. Contained, and "
        "the containment is deliberate (rug_detector.py:86-87). Still worth a None.",
    ),
}


def classify(lit: Literal) -> tuple[str, str]:
    """Return (class, reason). Heuristic, with per-site overrides for the judged cases."""

    ruling = OVERRIDES.get((lit.path, lit.name))
    if ruling:
        return ruling

    # Trivial structural values carry no claim about the world. -1 is the repo's
    # "not observed" sentinel (shitcoims_intelligence/tape.py:289-295), not a value.
    if lit.value in (0.0, 1.0, 2.0, -1.0) and lit.context in ("compare", "bare", "assign", "fallback_get"):
        return "B", "structural or a not-observed sentinel"

    # `(x + 999_999) // 1_000_000` is the microlamport ceiling-division idiom.
    if lit.value in (999_999.0, 1_000_000.0) and DERIVE_NAMES.search(lit.name):
        return "B", "microlamport ceiling division, protocol-fixed"

    if lit.value in UNIVERSAL_B and not DERIVE_NAMES.search(lit.name):
        return "B", UNIVERSAL_B[lit.value]

    # Order matters: a `.get("stop_loss_pct", -30)` is a policy default, not a fabricated
    # measurement. Only fall through to the fallback rule once policy names are excluded.
    if POLICY_NAMES.search(lit.name):
        buried = lit.scope != "module" and lit.context not in ("default",)
        return "C", "policy choice, BURIED in a function body" if buried else "policy choice, surfaced"

    # A number produced by an error path or a missing key is the worst case: it is
    # indistinguishable downstream from a real measurement.
    if lit.is_fallback and lit.value != 0.0:
        return "A", f"silent fallback ({lit.context}) substitutes an invented value"
    if lit.is_fallback and DERIVE_NAMES.search(lit.name):
        return "A", f"silent fallback ({lit.context}) on a measurable quantity"

    if INSTRUMENT_NAMES.search(lit.name):
        return "D", "an instrument's limit; verify the caller does not read it as complete data"

    if DERIVE_NAMES.search(lit.name):
        return "A", "names a quantity that varies in reality and is measurable"

    if lit.value in UNIVERSAL_B:
        return "B", UNIVERSAL_B[lit.value]

    return "C", "unclassified magic number; decide which bucket it belongs in"


# --------------------------------------------------------------------------------------
# The registry: judged findings, ranked. `--check` verifies these still say what we said.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    rank: int
    path: str
    line: int
    symbol: str  # a string that must still appear at/near `line`
    current: str
    correct: str
    cls: str
    wrongness: str  # how wrong, stated in the units the error is actually in
    depends: str
    patch: str
    breaks: str
    evidence: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def weight(self) -> int:
        """What depends on it: 10 = signs a transaction, 1 = formats a report."""
        return PACKAGES.get(self.path.split("/", 1)[0], 1)


REGISTRY: tuple[Finding, ...] = (
    Finding(
        rank=0,
        path="app/views/positions.tsx",
        line=45,
        symbol="cost_basis_sol: Number.isFinite(quoted) ? quoted : null,",
        current="the NEW-POLICY form is pre-filled with the bag's current EXIT QUOTE as its "
        "cost basis, and submit() PUTs the whole editing object",
        correct="null. A basis is a provenance type; the only honest constructor walks the "
        "wallet's own confirmed transactions (engine.reconstruct_observed_basis).",
        cls="A",
        wrongness="makes PnL start at 0% by construction -- the exact -7.47 SOL mechanism",
        depends="PUT /api/policies/{mint} -> policy.cost_basis_sol -> engine.py:1039, which "
        "reconstructs an observed basis only when BOTH cost_basis_sol and buy_price_sol are None",
        patch="cost_basis_sol: null  -- leave the field empty and let the sentinel observe it, "
        "or require the operator to type what they actually paid.",
        breaks="Nothing. A new policy saved from the UI stops carrying a fabricated basis and "
        "falls to the observed-basis path (or rug-only until it resolves), which is the design.",
        evidence="VERIFIED: openNew() sets it from exitSol; submit() spreads `editing` into "
        "savePolicy() (positions.tsx:62); api.ts:115-124 PUTs it unmodified. NOT VERIFIED: "
        "whether _basis_needs_observation's migration clause (engine.py:310-312, origin == "
        "ORIGIN_DEFAULT and buy_price_sol is None) still forces observation and overwrites it. "
        "Resolve that before deciding this is live rather than latent. Contrast app/lib/api.ts, "
        "whose protect-unmonitored path deliberately sends NO basis at all.",
        tags=("money", "fabricated-basis", "default-on-missing", "needs-confirmation"),
    ),
    Finding(
        rank=1,
        path="shitcoims_scalper/policy.py",
        line=167,
        symbol="priority_fee_lamports: int = 500_000",
        current="500,000 lamports",
        correct="21,000-53,000 (policy budget); 55,000 = measured tape median network fee",
        cls="A",
        wrongness="9.1x the measured median; B* oversized 3.0-4.9x",
        depends="B* = sqrt(priority*Y) -- every position size in the shadow book, and the "
        "friction gate that decides whether a candidate is actionable at all",
        patch="priority_fee_lamports: int = 55_000  # measured median; pass the per-pool p75 when known",
        breaks="B* drops 3.0-4.9x. Small pools that previously cleared max_friction now fail it, "
        "so the pass rate falls; the whole shadow run to date is sized wrong and cannot be "
        "compared to a re-run without re-scoring.",
        evidence="scripts/sim2real.py network_fee_lamports median=55000 over n=2937 swaps; "
        "studies/RESULT_execution_landing.md §8",
        tags=("money", "sizing"),
    ),
    Finding(
        rank=2,
        path="shitcoims_scalper/policy.py",
        line=166,
        symbol="swap_fee_bps: int = 100",
        current="100 bps, flat, every pool",
        correct="the TAKER all-in, per pool. 144 bps decoded on PumpSwap "
        "(studies/lp_strategy.py:142); vault inversion measures 20.0 / 20.0 / 406.5 / 908.7 bps "
        "on DREGG-SOL / SOLVE-SOL / nosis-SOL / weave-SOL but that is the LP-RECEIVED leg",
        cls="A",
        wrongness="45x spread across our own six pools; and the obvious fix is measured "
        "on the wrong basis",
        depends="round_trip_friction -> the `actionable` gate -> the logged verdict and propensity. "
        "A wrong fee mis-labels which candidates were ever enterable, which contaminates OPE.",
        patch="swap_fee_bps: int -- make it REQUIRED (no default) and pass the pool's TAKER "
        "all-in; refuse the candidate when it is unknown, never fall back to 100.",
        breaks="On weave-like pools nothing is actionable any more (2 x 908.7bps alone exceeds "
        "max_friction=0.05). That is the correct answer, but the enter rate collapses.",
        evidence="scripts/sim2real.py effective_fee_bps (n=2458 CP swaps) agrees to 0.1 bps with "
        "lp_strategy.py:136-137 'what the LP RECEIVES: 0.200% per leg, measured from "
        "constant-product inversion' -- two independent implementations, same basis. The taker "
        "leg is 1.44%, decoded from pool config (lp_strategy.py:131-142).",
        tags=("money", "fees", "wrong-basis"),
    ),
    Finding(
        rank=3,
        path="shitcoims_intelligence/tape.py",
        line=58,
        symbol='decimals = _as_int(delta.get("decimals")) or 0',
        current="missing decimals -> 0 -> base = raw / 10**0 = raw",
        correct="refuse the row; a missing exponent is not a zero exponent",
        cls="A",
        wrongness="10^6 to 10^9 on any row with absent decimals",
        depends="TapePrint.base -> stored verbatim at runtime.py:305 -> every amount a human or "
        "a sieve ever reads for that mint",
        patch="use the -1 sentinel this same file already defines at tape.py:289-295 and honours "
        "at tape.py:153, then drop the print rather than invent an exponent.",
        breaks="Rows with absent decimals disappear instead of appearing with million-fold "
        "amounts. Any count over those rows changes -- which is the point.",
        evidence="the `if decimals >= 0` guard on the next line is dead code: after `or 0`, "
        "decimals can never be negative, so the defence the author wrote is disarmed by the "
        "fallback one line above it",
        tags=("money-adjacent", "silent-fallback", "decimals"),
    ),
    Finding(
        rank=4,
        path="shitcoims_netmap/tapefeed.py",
        line=515,
        symbol='decimals = int(vault.get("decimals", 0) or 0)',
        current="missing decimals -> 0 -> raw base units emitted as whole tokens",
        correct="None -> refuse the row and count it",
        cls="A",
        wrongness="10^6 to 10^9, into TVL and notional",
        depends="balances -> PoolTape.last_reserves_units -> assemble._tape_tvl_usd -> Edge.tvl_usd "
        "-> capacitance_usd / depth_term -> the arb notional and profit for every cycle",
        patch="decimals = vault.get('decimals'); if decimals is None: return None  -- and "
        "co-change shitcoims_cluster/parse.py:513-519 to emit None rather than 0.",
        breaks="Pools with unparseable vault metadata drop out of the map instead of appearing "
        "with 10^9x TVL. Cycle counts change.",
        evidence="tapefeed.py:549 is the worse twin: pool_tape.decimals.get(out_mint, 0) reads a "
        "CROSS-ROW cache, so it yields 10**0 for any mint whose decimals were never populated in "
        "this window. parse.py always writes the key today -- the fallback is load-bearing on an "
        "invariant nothing asserts.",
        tags=("silent-fallback", "decimals"),
    ),
    Finding(
        rank=5,
        path="shitcoims_netmap/physics.py",
        line=58,
        symbol="DEFAULT_GAS_USD",
        current="$0.30 per atomic route",
        correct="$0.003-$0.009 for a 3-leg route at the RESULT_execution_landing.md bid ladder",
        cls="A",
        wrongness="33-94x, and it sits on a verdict boundary",
        depends="full_band_log = fee_band + sqrt(2*G*sum_depth) -> whether any cycle is reported "
        "tradeable; arb_value_usd subtracts G from profit directly",
        patch="DEFAULT_GAS_USD: Final[float] = 0.01  # 3-leg route, ~371k CU at the 100k-300k "
        "microlamport/CU policy band, SOL=$75.80. Better: derive it from fee_lamports, which is "
        "already on every tape row (shitcoims_cluster/parse.py:785).",
        breaks="Every reported band narrows -- the gas term shrinks by sqrt(30) = 5.5x -- and "
        "cycles previously below the band become tradeable. Any conclusion of the form 'no cycle "
        "clears the band' has to be recomputed.",
        evidence="the docstring says 'at the config's priority-fee cap': "
        "max_priority_fee_lamports=5_000_000 = $0.379. A CEILING was read as a typical cost. "
        "Measured median fee 55,000 lamports = $0.0042. The module quotes per-loop residuals of "
        "$0.37-$9.86, so the gas constant is within 1.2x of the smallest number it judges.",
        tags=("money", "gas", "ceiling-as-typical"),
    ),
    Finding(
        rank=6,
        path="scripts/lp_report.py",
        line=267,
        symbol="(px or 0)",
        current="an unavailable price is valued at $0 inside grand_value / grand_basis",
        correct="carry None through the total, and print the total as unavailable",
        cls="A",
        wrongness="100% of the missing leg, silently, in the headline number",
        depends="the TOTAL / vs HODL line at lp_report.py:301-302, which the operator reads as "
        "the portfolio's value",
        patch="skip the position in the rollup when px or py is None and print how many were "
        "skipped, or accumulate None and render TOTAL as unavailable.",
        breaks="The TOTAL becomes unavailable whenever any leg is unpriced. That is the honest "
        "answer and the file already gives it per-position.",
        evidence="usd_price's own docstring at lp_report.py:118-127 forswears exactly this: 'an "
        "unavailable price is now reported as unavailable and never silently valued at zero'. "
        "Line 297 honours it per-position ('valuing it at zero would lie'); lines 274-275 "
        "accumulate the (px or 0) version one scope up.",
        tags=("money", "silent-fallback", "self-contradiction"),
    ),
    Finding(
        rank=7,
        path="studies/deterioration.py",
        line=586,
        symbol="150.0",
        current="SOL = $150.00 seeded into the SOL/USD reference series",
        correct="return None; a fabricated denominator is worse than a missing study",
        cls="A",
        wrongness="1.98x today's price -- and it is the marketfabric archetype, in our tree",
        depends="SolUsd.at -> every SOL-denominated forward return the study computes "
        "(deterioration.py:634-636), which are both its matching features and its outcome",
        patch="last = next((p for p in price if not math.isnan(p)), None); if last is None: "
        "return None",
        breaks="The study refuses to run when GeckoTerminal serves an all-NaN grid, instead of "
        "running on a $150 denominator. It also persists to state/deterioration/sol_usd.json for "
        "6 hours, so one bad fetch poisons a window.",
        evidence="Coinbase spot 75.795 / Kraken 75.79 at 2026-08-14T08:00Z. marketfabric's "
        "sol_usd = 150.0 produced an 11.3% zero rate and a 50,164x p95/p05 spread; this is the "
        "same constant. Related: SolUsd.at returns 1.0 when the reference is missing "
        "(deterioration.py:601-607) and `self.price[idx] or 1.0` turns one zero hour into a 75x "
        "return spike.",
        tags=("price", "silent-fallback", "archetype"),
    ),
    Finding(
        rank=8,
        path="shitcoims_intelligence/runtime.py",
        line=751,
        symbol="token_largest_accounts(mint)",
        current="getTokenLargestAccounts returns at most 20 rows; concentration() then "
        "normalises by the sum of those 20",
        correct="normalise by getTokenSupply, or rename the outputs to say top-20",
        cls="D",
        wrongness="structural: holder_count is always <= 20 and top20 is always exactly 1.0",
        depends="holder_top1 / holder_hhi / holder_nakamoto -> holder_verdict's veto at "
        "top1 >= 0.35, nakamoto == 1, hhi >= 0.40 (sieve.py:51-52, numerics.py:88)",
        patch="fetch getTokenSupply, append a synthetic remainder bucket before calling "
        "concentration(), or stop emitting top1/hhi/nakamoto and emit only an honestly named "
        "top20_share_of_supply.",
        breaks="The veto rate falls. Mints previously rejected for concentration are admitted -- "
        "correctly, because the concentration was an artefact of the denominator.",
        evidence="numerics.py:60-68: xs = the <=20 amounts, total = sum(xs), top1 = xs[0]/total. "
        "A mint whose top 20 wallets hold 3% of supply, with #1 holding 40% OF THAT 3%, is "
        "vetoed. Nothing records that 20 is a node-imposed ceiling.",
        tags=("instrument-limit", "denominator", "veto-bias"),
    ),
    Finding(
        rank=9,
        path="kernel_svm/stream.py",
        line=233,
        symbol='"limit": 200',
        current="a full 200-signature page is treated as the complete set of new signatures",
        correct="detect len(page) == limit and page with `before`, as the same repo already does",
        cls="D",
        wrongness="unbounded: every signature past 200 between two 4s polls vanishes",
        depends="the `collected` chain fed to replay_stream; a hole makes the replay chain a swap "
        "against a pre-state that skipped an intervening swap",
        patch="if len(page) == 200: page backwards with `before` until the cursor is reached, or "
        "raise. Copy shitcoims_cluster/record.py:155-169.",
        breaks="Nothing when the pool is quiet. On a hot pool it converts a silent hole into "
        "either correct pagination or a loud failure.",
        evidence="the loss does not surface as silence -- it surfaces as `chain_drifted` "
        "(stream.py:120,260), which reads as a race and invites 'fix' by re-snapshotting. "
        "kernel_svm/capture.py:246-253 has the same defect at limit=100, and worse: the page is "
        "newest-first, so filtering by slot drops the OLDEST entries, which are exactly the ones "
        "the chained replay needs first.",
        tags=("instrument-limit", "misattributed-symptom"),
    ),
    Finding(
        rank=10,
        path="studies/power_gate.py",
        line=1148,
        symbol="swap_fee_bps = 110.0",
        current="110 bps/leg, as a bare local inside section [10]",
        correct="144 bps -- decoded from pool config and already a module constant elsewhere",
        cls="A",
        wrongness="31% understated, on a number this repo has already superseded in writing",
        depends="round_trip_friction_sol -> friction_sol -> friction_usd in the "
        "'n -> CALENDAR DAYS AND DOLLARS' feasibility verdict (power_gate.py:1161-1169)",
        patch="from studies.lp_strategy import PUMPSWAP_TAKER_FEE; swap_fee_bps = "
        "PUMPSWAP_TAKER_FEE * 10_000",
        breaks="The feasibility table's friction column rises ~31%. Any experiment sized against "
        "it was under-budgeted.",
        evidence="lp_strategy.py:138-141 names this site: 'RESULT_power_gate.md carried the taker "
        "leg as \"up to 1.10%\" and flagged it as its weakest inherited assumption; 1.44% decoded "
        "settles it, and it is HIGHER than the bound that section called absurd.' The correction "
        "was written down and never propagated.",
        tags=("fees", "known-stale", "buried"),
    ),
    Finding(
        rank=11,
        path="studies/edge_creation.py",
        line=570,
        symbol="return px[max(0, min(len(px) - 1, i))]",
        current="a timestamp outside the fetched window silently returns the window-edge price",
        correct="return None outside [ts[0], ts[-1]] and count how often it fires",
        cls="D",
        wrongness="unbounded, and unsigned -- the error direction depends on the drift",
        depends="deposit USD (edge_creation.py:1067), the HODL counterfactual (:1077) and the IL "
        "ratio (:1083-1084)",
        patch="if when < ts[0] or when > ts[-1]: return None  -- and have the callers refuse the "
        "position rather than price it.",
        breaks="Positions opened before the fetched window drop out of the IL and HODL tables. "
        "Those are precisely the oldest weave/DREGG legs the class docstring already flags.",
        evidence="the class docstring at edge_creation.py:530-537 states the instrument limit "
        "('GeckoTerminal returns 1000 bars, which is ~16.7 hours of minute data') and the method "
        "docstring insists at() 'is a step function ... never an interpolation: interpolating a "
        "price you did not observe is exactly the kind of quiet fabrication PROGRAM.md was "
        "written about'. Backward extrapolation off the window edge is that fabrication, "
        "unguarded.",
        tags=("instrument-limit", "self-contradiction"),
    ),
    Finding(
        rank=12,
        path="config.yaml",
        line=17,
        symbol="slippage_bps: 1500",
        current="1500 bps on the panic/rug path and on every quote_exit mark",
        correct="a minOut computed from live reserves; 250 bps is already the ordinary-exit value",
        cls="A",
        wrongness="6x the tight value the code already prefers, on the disaster path",
        depends="exit_slippage_bps()'s ceiling -> every panic/exit_rug order; and quote_exit "
        "(clients.py:417), which passes config.slippage_bps unmodified into every PnL mark",
        patch="add `exit_slippage_bps: 250` to the jupiter block -- clients.py:65 already honours "
        "it through getattr -- and derive the panic bound from reserve depth.",
        breaks="Panic exits on genuinely collapsing liquidity may revert instead of filling. That "
        "is the trade the 1500 buys; it should be bought deliberately.",
        evidence="LESS BAD THAN IT LOOKS: clients.py:56 TIGHT_EXIT_SLIPPAGE_BPS = 250 already "
        "governs exit_trail / exit_stop / exit_scale / exit_dispose, and executable_order "
        "(clients.py:486-491) rejects any order whose own threshold sits below the computed "
        "floor. The 1500 is live only for panic and exit_rug -- and for quotes.",
        tags=("money", "slippage"),
    ),
    Finding(
        rank=13,
        path="shitcoims_cluster/record.py",
        line=154,
        symbol="cap = self.backfill if not isinstance(until, str) else MAX_SIGNATURE_LIMIT * 10",
        current="the 10,000-signature incremental cap exits the loop, then the cursor advances "
        "to the NEWEST signature collected",
        correct="write a gap row when the cap binds, as every other truncation in this repo does",
        cls="D",
        wrongness="silent and permanent: the skipped interval is never revisited",
        depends="the watch ledger, which then reports the window as covered -- so "
        "tapefeed.evidence returns `observed` over an interval that was truncated",
        patch="if len(collected) >= cap: self.tape.write_watch(... a truncation gap ...) before "
        "advancing cursor_signature at record.py:192.",
        breaks="Nothing at runtime. It makes a censored window visible to every study that reads "
        "the tape's coverage.",
        evidence="the pagination itself is correct (record.py:167 `if len(page) < page_limit: "
        "break` is exactly the check kernel_svm is missing). The defect is only that the cap's "
        "data loss is unrecorded, while note_failure / SourceGap / OBSERVER_LOST record every "
        "other kind.",
        tags=("instrument-limit", "unrecorded-loss"),
    ),
    Finding(
        rank=14,
        path="shitcoims_intelligence/helius.py",
        line=198,
        symbol="estimated_credits_per_page: int = 50",
        current="50 credits per page booked against the daily budget",
        correct="10 -- stated twice in this same file's docstrings",
        cls="A",
        wrongness="5x over-estimate; the collector defects at 20% of its real allowance",
        depends="the credit meter -> max_estimated_credits=150 (runtime.py:639) buys 3 pages "
        "where the true cost buys 15; and the 10,000/day, 300,000/month budgets in collector.py",
        patch="estimated_credits_per_page: int = 10  # vendor-published, see the docstrings at "
        "helius.py:689 and :737",
        breaks="Each run collects up to 5x more pages. Real spend rises toward the budget that "
        "was always there -- verify against the Helius dashboard before shipping.",
        evidence="helius.py:689 'Every page is 10 credits whatever it contains'; helius.py:737 "
        "'it is the 10-credits-per-100-transactions RPC'. The constant contradicts its own file.",
        tags=("budget", "self-contradiction"),
    ),
    Finding(
        rank=15,
        path="shitcoims_intelligence/runtime.py",
        line=69,
        symbol="MINT_TAPE_PAGE_LIMIT = 20",
        current="the page limit (20) exactly equals the decision threshold "
        "_MIN_TRADES_FOR_ORGANIC (sieve.py:44)",
        correct="the page must be strictly larger than any threshold computed from it",
        cls="D",
        wrongness="the organic-wash gate is a near-dead branch",
        depends="organic_verdict (sieve.py:159-166): 'skip if trade_count < 20'. trade_count "
        "cannot exceed the page, so the gate SKIPs almost always -- and in the one boundary case "
        "where it fires, it judges wash-trading off 20 prints, a few seconds of tape.",
        patch="import the threshold and set MINT_TAPE_PAGE_LIMIT = 4 * _MIN_TRADES_FOR_ORGANIC, "
        "and put trade_count_is_truncated = (len(page) == limit) in the feature bag so the sieve "
        "can SKIP explicitly instead of by arithmetic accident.",
        breaks="More credits per mint (see rank 14 -- they interact). organic_verdict starts "
        "actually returning verdicts, so the sieve's behaviour changes.",
        evidence="two independent constants, both 20, in different files, with no comment "
        "connecting them. helius.py:684-686 already warns that mint_enhanced_page 'drops "
        "paginationToken, so a caller can only ever read the first page'.",
        tags=("instrument-limit", "dead-gate"),
    ),
    # ---- registered below the top 15: same treatment, smaller blast radius ----
    Finding(
        rank=16,
        path="studies/circuit_model.py",
        line=568,
        symbol="GAS_USD = 0.30",
        current="$0.30",
        correct="$0.003-$0.009",
        cls="A",
        wrongness="33-94x -- the same number as rank 5, second copy",
        depends="every band and arb-profit figure the circuit model prints",
        patch="GAS_USD = 0.01  # measured; studies/RESULT_execution_landing.md",
        breaks="Published band numbers in RESULT_circuit_model.md move; the study re-runs.",
        evidence="one number, three copies: physics.py:58, circuit_model.py:568, and the prose "
        "at circuit_theory.py:1514",
        tags=("gas", "duplicate"),
    ),
    Finding(
        rank=17,
        path="studies/circuit_theory.py",
        line=1514,
        symbol="gas is ~$0.30",
        current="prose asserting $0.30 as a fact about Solana",
        correct="~$0.004 measured",
        cls="A",
        wrongness="72x -- and it is the provenance of ranks 5 and 16",
        depends="the closed-form optimal-half-width argument built on top of it",
        patch="restate as '~$0.004 (measured median network fee; the $0.30 figure was the "
        "configured priority-fee ceiling)'. The argument SURVIVES -- it concludes gas is "
        "negligible against the swap fee, and the correction strengthens that conclusion.",
        breaks="Nothing computational. But leave it and the constants grow back.",
        evidence="measured median fee 55,000 lamports at SOL=$75.795 = $0.0042",
        tags=("gas", "prose", "provenance"),
    ),
    Finding(
        rank=18,
        path="shitcoims_replay/ope.py",
        line=76,
        symbol="return self.ess_fraction >= 0.10",
        current="the ESS trust gate, as a literal inside a property body",
        correct="correct as a policy choice -- but it must be visible and overridable",
        cls="C",
        wrongness="not wrong; invisible",
        depends="whether any off-policy estimate is reported as trustworthy at all",
        patch="MIN_TRUSTWORTHY_ESS_FRACTION = 0.10 at module level, referenced here and carried "
        "into the returned Estimate so a reader can see which bar was applied.",
        breaks="Nothing.",
        evidence="ope.py deliberately has NO IPS clipping and NO discount factor -- the right "
        "call, since clipping biases in a way no diagnostic recovers. This one threshold is the "
        "exception to an otherwise clean module.",
        tags=("policy", "buried", "ope"),
    ),
    Finding(
        rank=19,
        path="shitcoims_scalper/feed.py",
        line=87,
        symbol="return []",
        current="a failed listing call is indistinguishable from 'no coins were listed'",
        correct="propagate, or return a sentinel the caller counts",
        cls="A",
        wrongness="silently shrinks the OPE denominator by an unknown amount",
        depends="counters['snapshots'] and every per-candidate rate the shadow run reports",
        patch="return None on transport failure; run_shadow increments feed_errors. [] must mean "
        "'the endpoint answered with nothing'.",
        breaks="run_shadow grows a None branch. No change when the network is healthy.",
        evidence="run_shadow counts feed_lost for exits and has no counter for a lost listing",
        tags=("silent-fallback", "denominator"),
    ),
    Finding(
        rank=20,
        path="shitcoims_scalper/feed.py",
        line=100,
        symbol="def poll_listing(limit: int = 50)",
        current="top 50 by created + top 50 by last_trade, treated as the candidate universe",
        correct="not a fixable constant -- record it as a truncation",
        cls="D",
        wrongness="the denominator of every rate the shadow run reports",
        depends="decisions/candidate, enter rate, pass rate",
        patch="return the page size and whether the page came back full, and write page_full into "
        "each heartbeat row.",
        breaks="Nothing at runtime; previously-clean denominators show as censored.",
        evidence="pump.fun creates far more than 50 coins per 3-second poll",
        tags=("instrument-limit", "denominator"),
    ),
    Finding(
        rank=21,
        path="shitcoims_netmap/assemble.py",
        line=325,
        symbol="fdv = (dex_quote.fdv_usd if dex_quote else 0.0) or (gecko_quote.fdv_usd",
        current="both aggregators failing gives fdv = 0.0, which selects the 0.95% creator rung",
        correct="None -> refuse to price the edge, or flag it distinctly",
        cls="A",
        wrongness="picks the most expensive rung whenever FDV is unavailable",
        depends="pumpswap_fee -> fee_band_log -> the cycle verdict",
        patch="if fdv is None: mark the edge fee unknown. pumpswap_fee always sets "
        "uncertain=True, so that flag cannot distinguish measured from guessed today.",
        breaks="Cycles with unpriceable legs drop out instead of being priced pessimistically.",
        evidence="fails conservative, but silently, and prints 'FDV=$0' in a source string "
        "nobody reads",
        tags=("silent-fallback", "fees"),
    ),
    Finding(
        rank=22,
        path="shitcoims_sentinel/transaction.py",
        line=109,
        symbol="unit_limit = 200_000",
        current="200,000 CU assumed when no explicit ComputeBudget limit is present",
        correct="Solana's default is 200,000 PER INSTRUCTION, capped at 1,400,000 per transaction",
        cls="A",
        wrongness="up to 7x under-estimate of the fee, in the direction that passes the cap",
        depends="_compute_budget_fee -> the max_priority_fee_lamports gate",
        patch="unit_limit = min(200_000 * max(1, len(instructions)), 1_400_000)",
        breaks="Nothing in practice -- Jupiter always emits an explicit limit, so this fallback "
        "is cold. It is a latent hole, bounded by the 0.005 SOL cap.",
        evidence="transaction.py:108-121",
        tags=("money", "latent"),
    ),
    Finding(
        rank=23,
        path="shitcoims_sentinel/executor.py",
        line=631,
        symbol='int(order.get("otherAmountThreshold") or 0)',
        current="0 substituted if Jupiter omits the threshold",
        correct="unreachable today, but the `or 0` encodes the opposite invariant",
        cls="A",
        wrongness="latent: at 0 the simulation gate degenerates",
        depends="validate_simulated_exit's minimum_wallet_lamports. At 0 the gate falls from 'the "
        "exit returned at least minOut' to 'the wallet lost less than 0.02 SOL' -- a sell "
        "returning nothing would pass simulation.",
        patch="minimum_output_lamports=int(order['otherAmountThreshold'])  # positive by "
        "construction; a KeyError here is the correct failure",
        breaks="Nothing. It turns a silent degradation into a crash, which on this path is "
        "strictly better.",
        evidence="clients.py:478-482 enforces 0 < minimum_output <= out_amount, so the fallback "
        "is dead code TODAY -- and dead defences are how invariants quietly move",
        tags=("money", "silent-fallback", "latent"),
    ),
    Finding(
        rank=24,
        path="shitcoims_sentinel/engine.py",
        line=69,
        symbol="OBSERVED_BASIS_MAX_SIGNATURES = 100",
        current="100 signatures / 40 transactions inspected",
        correct="correct as written -- registered as the EXEMPLAR, not as a defect",
        cls="C",
        wrongness="none: it fails closed",
        depends="whether a lot ever gets an observed cost basis",
        patch="none required. Emit a counter for lots parked on the structural-retry path so a "
        "permanently unbasisable bag is visible rather than quietly rug-only.",
        breaks="Nothing.",
        evidence="engine.py:283-284 returns (None, 'lot start not reached within N inspected "
        "transaction(s)') -- an instrument limit handled the RIGHT way. This is what every "
        "D-class finding above should look like after it is fixed.",
        tags=("exemplar", "instrument-limit-done-right"),
    ),
)


# --------------------------------------------------------------------------------------
# Measurement: the A-class values, recomputed from the tape
# --------------------------------------------------------------------------------------


def _tape_rows(kinds: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in glob.glob(str(TAPE / "swaps" / "*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # the collector may be mid-append
                if row.get("kind") in kinds:
                    rows.append(row)
    return rows


def _effective_fee_bps(row: dict[str, Any]) -> float | None:
    """Zero-fee constant-product prediction vs realised output, in bps. Same method as
    scripts/sim2real.py, restated here so this audit does not depend on that script."""

    reserves = row.get("reserves") or {}
    if reserves.get("dex") != "pumpswap" or not reserves.get("replay_sufficient"):
        return None
    vaults = reserves.get("vaults") or []
    if len(vaults) != 2:
        return None
    try:
        in_amount, out_amount = int(row["token_in_raw"]), int(row["token_out_raw"])
    except (KeyError, TypeError, ValueError):
        return None
    if in_amount <= 0 or out_amount <= 0:
        return None
    by_mint = {vault.get("mint"): vault for vault in vaults}
    vault_in = by_mint.get(row.get("token_in_mint"))
    vault_out = by_mint.get(row.get("token_out_mint"))
    if not vault_in or not vault_out:
        return None
    try:
        pre_in, pre_out = int(vault_in["pre_raw"]), int(vault_out["pre_raw"])
    except (KeyError, TypeError, ValueError):
        return None
    if pre_in <= 0 or pre_out <= 0:
        return None
    predicted = pre_out - (pre_in * pre_out) // (pre_in + in_amount)
    if predicted <= 0:
        return None
    return (predicted - out_amount) / predicted * 10_000


def measure() -> dict[str, Any]:
    """Re-derive the constants the audit says must be derived. Read-only over the tape."""

    if not TAPE.exists():
        return {"error": f"no tape at {TAPE}"}

    swaps = _tape_rows({"swap"})
    per_pool: dict[str, list[float]] = {}
    for row in swaps:
        if (row.get("reserves") or {}).get("dex") == "meteora_dlmm":
            continue  # a DLMM fill walks bins; it is not a function of vault totals
        bps = _effective_fee_bps(row)
        if bps is not None and -500 <= bps <= 5000:
            per_pool.setdefault(str(row.get("label", "?")), []).append(bps)

    fees = [int(row["fee_lamports"]) for row in swaps if row.get("fee_lamports")]
    units = [int(row["compute_units"]) for row in swaps if row.get("compute_units")]

    def quantile(values: list[float], q: float) -> float:
        if not values:
            return float("nan")
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
        return float(ordered[index])

    fee_median = statistics.median(fees) if fees else float("nan")
    cu_median = statistics.median(units) if units else float("nan")

    # A three-leg atomic route at the studies/RESULT_execution_landing.md §8 bid ladder.
    three_leg_cu = 3.0 * cu_median if units else float("nan")
    gas_low = (5_000 + three_leg_cu * 100_000 / 1e6) / LAMPORTS_PER_SOL * SOL_USD_AT_AUDIT
    gas_high = (5_000 + three_leg_cu * 300_000 / 1e6) / LAMPORTS_PER_SOL * SOL_USD_AT_AUDIT

    return {
        "sol_usd": SOL_USD_AT_AUDIT,
        "sol_usd_source": SOL_USD_SOURCE,
        "swaps": len(swaps),
        "effective_fee_bps": {
            label: {
                "n": len(values),
                "median": round(statistics.median(values), 1),
                "p10": round(quantile(values, 0.10), 1),
                "p90": round(quantile(values, 0.90), 1),
            }
            for label, values in sorted(per_pool.items())
        },
        "network_fee_lamports": {
            "n": len(fees),
            "median": fee_median,
            "p10": quantile([float(f) for f in fees], 0.10),
            "p90": quantile([float(f) for f in fees], 0.90),
            "median_usd": round(fee_median / LAMPORTS_PER_SOL * SOL_USD_AT_AUDIT, 6),
        },
        "compute_units": {
            "n": len(units),
            "median": cu_median,
            "p90": quantile([float(u) for u in units], 0.90),
        },
        "derived": {
            "scalper_priority_fee_lamports": fee_median,
            "netmap_gas_usd_3leg": [round(gas_low, 4), round(gas_high, 4)],
            "b_star_shrink_vs_500k": round((500_000 / fee_median) ** 0.5, 2) if fees else None,
        },
    }


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def _registry_drift() -> list[str]:
    """Has a registered finding moved, changed, or been fixed? Either way, say so."""

    problems: list[str] = []
    for finding in REGISTRY:
        path = REPO / finding.path
        if not path.exists():
            problems.append(f"rank {finding.rank}: {finding.path} no longer exists")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        needle = finding.symbol.splitlines()[0].strip()
        window = range(max(0, finding.line - 6), min(len(lines), finding.line + 6))
        if any(needle in lines[i] for i in window):
            continue
        if needle in "\n".join(lines):
            where = next(i + 1 for i, line in enumerate(lines) if needle in line)
            problems.append(f"rank {finding.rank}: moved {finding.path}:{finding.line} -> :{where}")
        else:
            problems.append(
                f"rank {finding.rank}: RESOLVED or rewritten at {finding.path}:{finding.line} "
                f"({needle!r} is gone) -- update the registry"
            )
    return problems


def _money_path_literals(literals: list[Literal]) -> list[Literal]:
    return [lit for lit in literals if lit.path in MONEY_PATH]


def render(literals: list[Literal]) -> str:
    out: list[str] = []
    add = out.append

    add("HARDCODED CONSTANT AUDIT")
    add("=" * 110)
    add(f"{len(literals)} numeric literals across {len(PACKAGES)} packages.")
    add("")

    add("RANKED BY BLAST RADIUS  (how wrong) x (what depends on it)")
    add("-" * 110)
    add(f"{'#':>3}  {'cls':<4} {'dep':>4}  {'site':<44} {'current / correct / how wrong'}")
    for finding in sorted(REGISTRY, key=lambda f: f.rank):
        site = f"{finding.path}:{finding.line}"
        add(f"{finding.rank:>3}  {finding.cls:<4} {finding.weight:>4}  {site:<44} {finding.current}")
        add(f"{'':>3}  {'':<4} {'':>4}  {'':<44} -> {finding.correct}")
        add(f"{'':>3}  {'':<4} {'':>4}  {'':<44} !! {finding.wrongness}")
    add("")

    counts: dict[str, int] = {}
    for lit in literals:
        counts[classify(lit)[0]] = counts.get(classify(lit)[0], 0) + 1
    add("INVENTORY BY CLASS")
    add("-" * 110)
    for cls, label in (
        ("A", "MUST BE DERIVED"),
        ("B", "LEGITIMATE CONSTANT"),
        ("C", "POLICY CHOICE"),
        ("D", "INSTRUMENT LIMIT"),
    ):
        add(f"  {cls}  {label:<24} {counts.get(cls, 0):>5}")
    add("")

    add("CLASS D -- INSTRUMENT LIMITS (verify each caller does not read the cap as data)")
    add("-" * 110)
    for lit in sorted(literals, key=lambda x: (-x.weight, x.path, x.line)):
        if classify(lit)[0] != "D":
            continue
        add(f"  {lit.path}:{lit.line:<5} {lit.name:<28} = {lit.value:<14g} {lit.source[:52]}")
    add("")

    add("SILENT FALLBACKS -- an invented number substituted for absent data")
    add("-" * 110)
    for lit in sorted(literals, key=lambda x: (-x.weight, x.path, x.line)):
        if not lit.is_fallback or (lit.value == 0.0 and lit.package not in ("shitcoims_sentinel",)):
            continue
        add(f"  {lit.path}:{lit.line:<5} [{lit.context:<13}] {lit.name:<24} -> {lit.value:g}")
    add("")

    add("MONEY-PATH LITERALS (every number in a file that can move real SOL)")
    add("-" * 110)
    for lit in sorted(_money_path_literals(literals), key=lambda x: (x.path, x.line)):
        cls, why = classify(lit)
        add(f"  [{cls}] {lit.path}:{lit.line:<5} {lit.name:<28} = {lit.value:<14g} {why[:44]}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true", help="structured inventory")
    parser.add_argument("--measure", action="store_true", help="re-derive A-class values from the tape")
    parser.add_argument("--check", action="store_true", help="CI gate: drift + new money-path literals")
    args = parser.parse_args()

    if args.measure:
        print(json.dumps(measure(), indent=1, default=str))
        return 0

    literals = collect()

    if args.check:
        problems = _registry_drift()
        for lit in _money_path_literals(literals):
            if classify(lit)[0] == "A" and (lit.path, lit.name) not in OVERRIDES:
                problems.append(
                    f"unclassified derivable literal {lit.path}:{lit.line} {lit.name}={lit.value:g}"
                )
        for problem in problems:
            print(f"DRIFT: {problem}")
        print(f"\n{len(problems)} finding(s). Registry holds {len(REGISTRY)} judged entries.")
        return 1 if problems else 0

    if args.json:
        print(
            json.dumps(
                {
                    "literals": [lit.to_json() for lit in literals],
                    "registry": [
                        {
                            "rank": f.rank, "path": f.path, "line": f.line, "class": f.cls,
                            "current": f.current, "correct": f.correct, "patch": f.patch,
                            "breaks": f.breaks, "depends": f.depends, "evidence": f.evidence,
                            "wrongness": f.wrongness, "depends_weight": f.weight,
                            "tags": list(f.tags),
                        }
                        for f in REGISTRY
                    ],
                },
                indent=1,
            )
        )
        return 0

    print(render(literals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
