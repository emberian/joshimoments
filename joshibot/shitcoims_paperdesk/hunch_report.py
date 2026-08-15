"""``hunch report``: the intuition premium, measured, with the gate-veto table beside it.

THE ONE QUESTION
----------------
Is the operator's way of trading worth anything against the rule's, under identical
execution machinery?

Every entry-selection study in this tree returned null. The one repeatedly-positive
observation is theirs: on the same pattern under the same clock, the rule-chosen wiggle
book's first closes ran **-14.08%** and their hand-picked equivalents measured **+3.14%**.
That was a hand comparison over a handful of trades. This report is the standing version.

The two books share a friction model, a sizing rule, the brackets, the marking discipline
and the close-row builder, all by inheritance rather than by intention. They differ in TWO
places: who chose the coin, and what ended the position. The second one is a correction the
operator made to this lane's first design -- the wiggle book's five-minute clock was read
off their own trades and mistaken for their rule, when it is the outcome distribution of a
reactive policy (*"i watch it closely, and pull out the position whenever i feel like
it"*). So the operator arm exits on their ZAP, and this report never calls the difference
"selection": it is policy against policy, and the exit-reason split is where the two effects
begin to separate.

WHY THE HEADLINE NUMBER IS A DIFFERENCE AND NOT A RETURN
--------------------------------------------------------
The operator book's return on its own is uninterpretable: it is a return over whatever
coins the operator happened to look at, in whatever regime they looked at them in. It only
becomes evidence next to a book that ran the same execution over rule-chosen coins in the
same window -- so the headline is the DIFFERENCE, computed over closes whose windows
overlap, with the wiggle book as the control arm.

THREE HONESTY CONSTRAINTS, EACH OF WHICH THIS REPO HAS PAID FOR
----------------------------------------------------------------
1. **n beside every rate, and no rate at all below a floor.** A four-trade premium is not a
   premium. The interval is printed from the first row and the point estimate is labelled
   as theatre until the interval stops spanning zero.
2. **Clustered by mint.** Three hunches on one coin in one afternoon are not three
   independent observations of the operator's skill; they are one coin. Intervals are
   bootstrapped over MINTS (an entity-clustered bootstrap, the same unit
   ``studies/crime_signatures.py`` clusters on), so the sample size that matters is the
   number of distinct coins and it is printed as such.
3. **Both markings, always.** Marked-out and pessimistic side by side, because the gap
   between them is the size of the assumption, and reporting only the first is exactly the
   +21.77% -> -12.24% failure.

AND THE GATE TABLE IS DESCRIPTIVE. NO MODEL IS FITTED HERE.
------------------------------------------------------------
The gate-veto section counts, per entry gate, how the hunches it would have refused
actually did. That is the beginning of distillation and it is deliberately only the
beginning: it is a contingency table with n in every cell and no fitting, no selection, no
threshold search. The entire history of this repo's null results is a history of exactly
those three things being applied to a few hundred rows.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from shitcoims_paperdesk.hunch import HUNCH_PATH, read_hunches
from shitcoims_paperdesk.report import _fmt, _weighted_return, live_closes, read_ledger

__all__ = ["main", "render_hunch_report"]

SOL = 1_000_000_000

#: Below this many DISTINCT MINTS the premium is a number, not a finding, and the report
#: says so instead of printing an interval that would be read as one. Not a p-value
#: threshold in disguise -- an entity-clustered bootstrap over five coins is arithmetic
#: performed on five coins whatever it returns.
MIN_ENTITIES = 8

BOOTSTRAP_DRAWS = 2000


def _cluster_bootstrap(
    groups: dict[str, list[tuple[float, float]]], draws: int = BOOTSTRAP_DRAWS, seed: int = 11
) -> tuple[float, float] | None:
    """Percentile CI for a capital-weighted return, resampling MINTS with replacement.

    ``groups`` maps a mint to its (spend, pnl) pairs. Resampling whole mints rather than
    whole positions is what makes the interval honest when the operator hunches three times
    on one coin: those three rows share everything that coin did that afternoon, and an
    interval that treats them as independent is narrower than the evidence.
    """
    keys = list(groups)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    out: list[float] = []
    for _ in range(draws):
        spend = pnl = 0.0
        for _ in keys:
            for s, p in groups[keys[rng.randrange(len(keys))]]:
                spend += s
                pnl += p
        if spend > 0:
            out.append(pnl / spend)
    if len(out) < draws // 2:
        return None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def _groups(closes: list[dict[str, Any]], field_name: str) -> dict[str, list[tuple[float, float]]]:
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for close in closes:
        out[str(close.get("key"))].append(
            (float(close.get("spend_lamports") or 0.0), float(close.get(field_name) or 0.0))
        )
    return out


def _overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> tuple[float, float] | None:
    """The window both books were closing positions in. The comparison lives inside it."""
    if not a or not b:
        return None
    a_t = [float(c.get("closed_at_unix") or 0.0) for c in a]
    b_t = [float(c.get("closed_at_unix") or 0.0) for c in b]
    lo, hi = max(min(a_t), min(b_t)), min(max(a_t), max(b_t))
    return (lo, hi) if hi > lo else None


def _within(closes: list[dict[str, Any]], window: tuple[float, float] | None) -> list[dict[str, Any]]:
    if window is None:
        return closes
    lo, hi = window
    return [c for c in closes if lo <= float(c.get("closed_at_unix") or 0.0) <= hi]


def _arm_line(label: str, closes: list[dict[str, Any]]) -> str:
    if not closes:
        return f"  {label:<12}{0:>6}{'—':>8}{'—':>10}{'—':>10}{'—':>10}{'—':>12}"
    mints = len({str(c.get('key')) for c in closes})
    wins = sum(1 for c in closes if float(c.get("pnl_lamports") or 0) > 0)
    holds = statistics.median(float(c.get("holding_seconds") or 0.0) for c in closes)
    return (
        f"  {label:<12}{len(closes):>6}{mints:>8}{f'{wins}/{len(closes)}':>10}"
        f"{_weighted_return(closes, 'pnl_lamports') * 100:>9.2f}%"
        f"{_weighted_return(closes, 'pnl_pessimistic_lamports') * 100:>9.2f}%"
        f"{holds / 60:>11.1f}m"
    )


def _premium(rows: Any) -> list[str]:
    """The headline: operator minus wiggle, under identical execution."""
    # RETRACTED GESTURES ARE OUT OF EVERY FIGURE BELOW. They stay on the ledger and on the
    # tape; what they do not do is enter a measurement of the operator's selection, because
    # a gesture they took back is not a selection they made.
    operator = live_closes(rows, "operator")
    wiggle = live_closes(rows, "wiggle")

    out = [
        "=" * 96,
        "THE INTUITION PREMIUM — the operator's policy against the rule's",
        "=" * 96,
        "  Same clip, same friction, same brackets, same marking, same close-row builder.",
        "  TWO things differ, and the second one is a deliberate correction:",
        "    1. WHO CHOSE THE COIN — a person, versus the jittered entry rule.",
        "    2. WHAT ENDED IT — the operator's zap, versus a 240-420 s clock. That clock was",
        "       read off their own trades and mistaken for their rule; it is the outcome",
        "       distribution of a reactive policy, and they exit on what the chart is doing.",
        "  So this difference is POLICY vs POLICY and NOT selection alone. The exit split",
        "  below is where the two effects start coming apart.",
        "",
        f"  {'arm':<12}{'closes':>6}{'mints':>8}{'winners':>10}{'ret%':>10}{'pess%':>10}{'median hold':>12}",
        _arm_line("operator", operator),
        _arm_line("wiggle", wiggle),
    ]
    if rows.retracted_decisions:
        out.append(
            f"  ({len(rows.retracted_decisions)} close(s) excluded as retracted -- on the ledger,"
            " out of these numbers)"
        )

    window = _overlap(operator, wiggle)
    if window is None:
        return [
            *out,
            "",
            "  No overlapping window yet: one of the two arms has no closes. The premium is not",
            "  computable, and a difference taken across disjoint windows would be a difference",
            "  between two market regimes wearing a selection label.",
        ]

    op_w, wg_w = _within(operator, window), _within(wiggle, window)
    hours = (window[1] - window[0]) / 3600.0
    out += [
        "",
        f"  overlapping window: {hours:.1f} h, {len(op_w)} operator closes vs {len(wg_w)} wiggle closes",
    ]
    if not op_w or not wg_w:
        return [*out, "  (no closes from one arm inside the overlap)"]

    op_ret = _weighted_return(op_w, "pnl_lamports")
    wg_ret = _weighted_return(wg_w, "pnl_lamports")
    op_pess = _weighted_return(op_w, "pnl_pessimistic_lamports")
    wg_pess = _weighted_return(wg_w, "pnl_pessimistic_lamports")
    entities = len({str(c.get("key")) for c in op_w})
    out += [
        f"  premium (marked)      {(op_ret - wg_ret) * 100:>+8.2f} pp"
        f"   [operator {op_ret * 100:+.2f}%  -  wiggle {wg_ret * 100:+.2f}%]",
        f"  premium (pessimistic) {(op_pess - wg_pess) * 100:>+8.2f} pp"
        f"   [operator {op_pess * 100:+.2f}%  -  wiggle {wg_pess * 100:+.2f}%]",
    ]
    by_exit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for close in op_w:
        by_exit[str(close.get("exit_reason"))].append(close)
    if by_exit:
        out.append("")
        out.append("  operator arm by exit — a zap is their decision; a backstop is their absence")
        out.append(f"    {'exit':<18}{'n':>5}{'winners':>10}{'ret%':>10}{'median hold':>13}")
        for reason, subset in sorted(by_exit.items(), key=lambda kv: -len(kv[1])):
            wins = sum(1 for c in subset if float(c.get("pnl_lamports") or 0) > 0)
            holds = statistics.median(float(c.get("holding_seconds") or 0.0) for c in subset)
            out.append(
                f"    {reason:<18}{len(subset):>5}{f'{wins}/{len(subset)}':>10}"
                f"{_weighted_return(subset, 'pnl_lamports') * 100:>9.2f}%{holds / 60:>11.1f}m"
            )
        out.append(
            "    A backstop_expired row is a position the operator never came back to, so its"
        )
        out.append(
            "    only difference from the wiggle arm is selection plus a longer clock. Compare"
        )
        out.append(
            "    THOSE against wiggle for the selection-only contrast -- at the price of"
        )
        out.append(
            "    conditioning on the positions they did not react to, which is its own"
        )
        out.append("    selection effect and is not a free lunch.")

    if entities < MIN_ENTITIES:
        out += [
            f"  n = {entities} distinct coins on the operator arm. Below the {MIN_ENTITIES}-entity floor",
            "  this report will not print an interval, because an entity-clustered bootstrap over",
            f"  {entities} coins is arithmetic performed on {entities} coins whatever it returns. The",
            "  point estimate above is a running total, not a result.",
        ]
        return out
    ci_op = _cluster_bootstrap(_groups(op_w, "pnl_lamports"))
    ci_wg = _cluster_bootstrap(_groups(wg_w, "pnl_lamports"))
    if ci_op and ci_wg:
        out += [
            f"  operator 95% CI  [{ci_op[0] * 100:+.2f}%, {ci_op[1] * 100:+.2f}%]"
            f"   wiggle 95% CI  [{ci_wg[0] * 100:+.2f}%, {ci_wg[1] * 100:+.2f}%]",
            "  Intervals are percentile bootstraps over MINTS, not over positions: several hunches",
            "  on one coin in one afternoon are one observation of the market, not several.",
            "  Overlapping intervals are not a test; they are two intervals. Read them as spread.",
        ]
    return out


def _hunches(rows: Any, tape: list[Any]) -> list[str]:
    """Per-hunch: what was said, what the desk did, and what it cost."""
    out = [
        "",
        "HUNCHES — every gesture, its fate, and the words it came with",
    ]
    if not tape:
        return [
            *out,
            f"  (nothing on the tape yet: {HUNCH_PATH})",
            "  Click a card in the glass, or run `uv run scripts/hunch <coin> \"...\"`.",
        ]

    decisions = {
        str(d.get("hunch_id")): d
        for d in rows.decisions
        if str(d.get("book")) == "operator" and d.get("hunch_id")
    }
    retracted = {
        str(d.get("hunch_id"))
        for d in decisions.values()
        if str(d.get("decision_id")) in rows.retracted_decisions
    }
    by_decision = {
        str(d.get("decision_id")): str(d.get("hunch_id")) for d in decisions.values()
    }
    closes: dict[str, dict[str, Any]] = {}
    for close in rows.closes:
        owner = by_decision.get(str(close.get("decision_id")))
        if owner:
            closes[owner] = close
    # Last-writer-wins over the desk's own acknowledgements, in ledger order: a hunch goes
    # accepted -> decided -> closed, and the row the operator wants to see is the latest.
    states: dict[str, str] = {}
    for row in [*rows.hunch_rows, *rows.expectations]:
        key = row.get("hunch_id")
        if isinstance(key, str):
            states[key] = str(row.get("detail"))

    out.append(
        f"  {'when':<17}{'coin':<10}{'kind':<7}{'state':<24}{'ret%':>9}{'pess%':>9}  utterance"
    )
    for hunch in tape[-40:]:
        close = closes.get(hunch.hunch_id)
        state = states.get(hunch.hunch_id, "pending")
        if close is not None:
            state = f"closed:{close.get('exit_reason')}"
        if hunch.hunch_id in retracted:
            state = f"RETRACTED ({state})"
        ret = float(close.get("net_return") or 0.0) * 100 if close else float("nan")
        pess = float(close.get("net_return_pessimistic") or 0.0) * 100 if close else float("nan")
        said = hunch.utterance.strip().replace("\n", " ")
        # The utterance is the ONLY thing on this desk that is never normalised, so the
        # report truncates it for the column and says so rather than editing it.
        shown = (said[:44] + "…") if len(said) > 45 else (said or "(no words — a click)")
        out.append(
            f"  {hunch.to_json()['t_event'][5:16]:<17}"
            f"{(hunch.symbol or hunch.mint[:8]):<10}{hunch.kind:<7}{state[:23]:<24}"
            f"{_fmt(ret, '>8.2f')}%{_fmt(pess, '>8.2f')}%  {shown}"
        )
    ghosts = sum(1 for d in decisions.values() if d.get("ghost_town"))
    if ghosts:
        out.append(
            f"  {ghosts} entered against a failing DEPTH gate (ghost-town warned, tagged, not vetoed)."
        )
    return out


def _gate_vetoes(rows: Any) -> list[str]:
    """Which of our entry gates disagree with the operator, and are they right to?

    Descriptive only. Per gate: how many hunches it would have refused, and how those did.
    The comparison cell is the hunches it would have ALLOWED, so each row is a 2x1
    contingency on one gate with n printed in both arms and nothing fitted anywhere.
    """
    out = [
        "",
        "GATE VETOES — the beginning of distillation, and only the beginning",
        "  Each row: the hunches this entry gate would have REFUSED, and what they actually did,",
        "  against the hunches it would have allowed. Descriptive. No model is fitted here.",
    ]
    decisions = [
        d
        for d in rows.decisions
        if str(d.get("book")) == "operator"
        and d.get("hunch_id")
        and str(d.get("decision_id")) not in rows.retracted_decisions
    ]
    if not decisions:
        return [*out, "  (no operator decisions logged yet)"]
    by_decision = {str(d.get("decision_id")): d for d in decisions}
    closes: dict[str, dict[str, Any]] = {}
    for close in rows.closes:
        key = str(close.get("decision_id"))
        if key in by_decision:
            closes[key] = close

    gates: Counter[str] = Counter()
    for decision in decisions:
        for leg in decision.get("gates") or {}:
            gates[leg] += 0
        for leg in decision.get("gates_would_veto") or ():
            gates[leg] += 1
    if not gates:
        return [*out, "  (decisions carry no gate map; nothing to count)"]

    out.append(f"  {'gate':<18}{'vetoed':>8}{'closed':>8}{'ret%':>9}{'allowed':>9}{'ret%':>9}")
    for leg, n_veto in sorted(gates.items(), key=lambda kv: -kv[1]):
        vetoed = [
            closes[str(d.get("decision_id"))]
            for d in decisions
            if leg in (d.get("gates_would_veto") or ()) and str(d.get("decision_id")) in closes
        ]
        allowed = [
            closes[str(d.get("decision_id"))]
            for d in decisions
            if leg in (d.get("gates") or {})
            and leg not in (d.get("gates_would_veto") or ())
            and str(d.get("decision_id")) in closes
        ]
        out.append(
            f"  {leg:<18}{n_veto:>8}{len(vetoed):>8}"
            f"{_fmt(_weighted_return(vetoed, 'pnl_lamports') * 100 if vetoed else float('nan'), '>8.2f')}%"
            f"{len(allowed):>9}"
            f"{_fmt(_weighted_return(allowed, 'pnl_lamports') * 100 if allowed else float('nan'), '>8.2f')}%"
        )
    out += [
        "  A gate whose vetoed arm loses and whose allowed arm does not has found something the",
        "  operator has not. A gate whose vetoed arm WINS is the rule being wrong, and is worth",
        "  more than the other case -- it is the only kind of evidence that can loosen a rule.",
        "  Neither sentence is writable at these n. Both become writable by clicking more.",
    ]
    return out


def _scorecard(rows: Any) -> list[str]:
    """The Brier scorecard for the non-positional claims. Censoring counted, not dropped."""
    out = [
        "",
        "EXPECTATIONS — down / up / watch claims, scored at their horizon",
    ]
    resolved = [
        r
        for r in rows.expectations
        if r.get("detail") in {"resolved", "censored", "falsifier_tripped"}
    ]
    if not resolved:
        return [*out, "  (no expectation has reached its horizon yet)"]

    by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in resolved:
        by_claim[str(row.get("claim"))].append(row)
    out.append(
        f"  {'claim':<12}{'n':>5}{'right':>8}{'censored':>10}{'Brier':>9}{'mean move':>12}"
    )
    for claim, entries in sorted(by_claim.items()):
        scored = [e for e in entries if e.get("detail") == "resolved" and e.get("outcome") is not None]
        censored = sum(1 for e in entries if e.get("detail") == "censored")
        briers = [float(e["brier"]) for e in scored if e.get("brier") is not None]
        moves = [float(e["change"]) for e in entries if e.get("change") is not None]
        right = sum(1 for e in scored if int(e.get("outcome") or 0) == 1)
        out.append(
            f"  {claim:<12}{len(entries):>5}{(f'{right}/{len(scored)}' if scored else '—'):>8}"
            f"{censored:>10}"
            f"{_fmt(statistics.fmean(briers) if briers else float('nan'), '>9.3f')}"
            f"{_fmt(statistics.fmean(moves) * 100 if moves else float('nan'), '>11.2f')}%"
        )
    tripped = sum(1 for r in resolved if r.get("detail") == "falsifier_tripped")
    out += [
        "  Brier is LOWER-is-better; 0.25 is the score of declaring 0.50 every time, so anything",
        "  above 0.25 means the declared confidence was worse than saying nothing. A tie scores",
        "  AGAINST the claim, and a claim whose horizon arrived while the coin was unobservable",
        "  is counted as censored in the denominator rather than dropped from it.",
    ]
    if tripped:
        out.append(f"  {tripped} falsifier(s) tripped before horizon — the belief's own stop firing.")
    return out


def _tape_health(tape: list[Any], rows: Any) -> list[str]:
    from shitcoims_paperdesk.hunch import read_tape

    _, retractions, zaps = read_tape()
    kinds = Counter(h.kind for h in tape)
    mints = len({h.mint for h in tape})
    words = sum(1 for h in tape if h.utterance.strip())
    with_state = sum(1 for z in zaps if z.state)
    zap_words = sum(1 for z in zaps if z.reason.strip())
    return [
        "",
        "THE TAPE — the future training set, and its coverage",
        f"  {len(tape)} hunches over {mints} distinct coins   "
        + ", ".join(f"{k}={v}" for k, v in kinds.most_common()),
        f"  {words} of {len(tape)} carry words; the rest are clicks, which is a valid gesture and",
        "  is stored as an empty utterance rather than as a fabricated one.",
        f"  {len(zaps)} zaps, {with_state} carrying instrument state, {zap_words} with words.",
        "  The zaps are the (state, exit) corpus for the reactive-exit-policy search -- the one",
        "  that supersedes the wiggle book's five-minute clock rather than tuning it. A zap",
        "  without state is half a training pair, so that count is the number that matters.",
        f"  {len(retractions)} retraction(s): gestures taken back, kept on disk, out of every score.",
        f"  file: {HUNCH_PATH}   ledger rows this scan: {rows.total:,}",
    ]


def render_hunch_report(root: Path | None = None, *, days: int | None = None) -> str:
    rows = read_ledger(root, days=days)
    tape = read_hunches()
    sections = [
        _premium(rows),
        _hunches(rows, tape),
        _gate_vetoes(rows),
        _scorecard(rows),
        _tape_health(tape, rows),
    ]
    return "\n".join(line for section in sections for line in section)


def _json_summary(root: Path | None = None, *, days: int | None = None) -> dict[str, Any]:
    rows = read_ledger(root, days=days)
    tape = read_hunches()
    operator, wiggle = live_closes(rows, "operator"), live_closes(rows, "wiggle")
    window = _overlap(operator, wiggle)
    op_w, wg_w = _within(operator, window), _within(wiggle, window)
    op_ret = _weighted_return(op_w, "pnl_lamports") if op_w else float("nan")
    wg_ret = _weighted_return(wg_w, "pnl_lamports") if wg_w else float("nan")
    return {
        "hunches": len(tape),
        "mints": len({h.mint for h in tape}),
        "kinds": dict(Counter(h.kind for h in tape)),
        "operator_closes": len(operator),
        "wiggle_closes": len(wiggle),
        "overlap_hours": (window[1] - window[0]) / 3600.0 if window else None,
        "operator_return": None if math.isnan(op_ret) else op_ret,
        "wiggle_return": None if math.isnan(wg_ret) else wg_ret,
        "premium_pp": (
            None if (math.isnan(op_ret) or math.isnan(wg_ret)) else (op_ret - wg_ret) * 100
        ),
        "entities": len({str(c.get("key")) for c in op_w}),
        "entity_floor": MIN_ENTITIES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperdesk-hunch")
    parser.add_argument("--days", type=int, default=None, help="most recent N ledger days")
    parser.add_argument("--dir", type=Path, default=None, help="ledger directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.json:
        print(json.dumps(_json_summary(args.dir, days=args.days), indent=1, default=str))
    else:
        print(render_hunch_report(args.dir, days=args.days))
    return 0
