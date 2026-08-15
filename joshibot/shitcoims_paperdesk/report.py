"""The table the operator has never once been able to look at.

Three horizons, identical capital, identical friction, one accounting, side by side --
with the censoring priced rather than dropped, and with the size of that pricing shown
explicitly so nobody has to take it on faith.

WHY EVERY RETURN APPEARS TWICE
------------------------------
``marked`` prices a position that left observation at the last price seen AT OR BEFORE its
trigger. ``pessimistic`` prices the same position as a total loss. The truth is between
them and the gap is the size of the assumption -- which is the number
``studies/RESULT_board_entry.md`` did not report, and reporting only the survivors is how
+21.77% became -12.24%.

A third column, ``live-fill only``, shows the return over positions that never needed a
mark-out at all. On the board cohort that column read **+25.01%** while the full cohort
read **-12.24%**. It is not a better estimate; it is the selection effect, printed, so it
cannot be mistaken for one.

SURVIVAL IS A COMPETING-RISKS PROBLEM AND IS FITTED AS ONE
----------------------------------------------------------
A position ends either because a rule fired or because it left observation, and those two
compete. Treating departure as ordinary censoring in a Kaplan-Meier estimate assumes it is
independent of the outcome, which on a boards feed it emphatically is not -- coins leave
the board because they stopped moving. So the report fits an Aalen-Johansen cumulative
incidence per book with ``lifelines`` (``uv run --group research``) and prints both causes.
Survival tooling makes censoring part of the model specification instead of something an
analyst can forget, which is precisely why this repo now has it.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shitcoims_paperdesk import BOOKS
from shitcoims_paperdesk.ledger import LEDGER_DIR
from shitcoims_paperdesk.toll import GRID_SECONDS, VR_LAG

__all__ = ["Rows", "main", "render"]

SOL = 1_000_000_000

#: Exits produced by a rule the desk actually evaluated, as opposed to the position simply
#: falling out of view. The competing-risks split turns on this set.
RULE_EXITS = frozenset(
    {"take_profit", "stop_loss", "deadline", "deterioration", "graduated",
     "curve_drained", "horizon", "gate_failed"}
)


@dataclass
class Rows:
    """Every ledger row that matters, indexed once so the report scans the file once."""

    closes: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    gates: list[dict[str, Any]] = field(default_factory=list)
    accruals: list[dict[str, Any]] = field(default_factory=list)
    rebalances: list[dict[str, Any]] = field(default_factory=list)
    watch_opens: list[dict[str, Any]] = field(default_factory=list)
    watch_closes: list[dict[str, Any]] = field(default_factory=list)
    defects: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    run_ids: set[str] = field(default_factory=set)
    total: int = 0

    def add(self, row: dict[str, Any]) -> None:
        self.total += 1
        run_id = row.get("run_id")
        if isinstance(run_id, str):
            self.run_ids.add(run_id)
        bucket = {
            "close": self.closes,
            "decision": self.decisions,
            "heartbeat": self.heartbeats,
            "gate": self.gates,
            "accrual": self.accruals,
            "rebalance": self.rebalances,
            "watch_open": self.watch_opens,
            "watch_close": self.watch_closes,
            "defect": self.defects,
            "fill": self.fills,
        }.get(str(row.get("row")))
        if bucket is not None:
            bucket.append(row)


def read_ledger(root: Path | None = None, *, days: int | None = None) -> Rows:
    """Scan the day-partitioned ledger. A half-written final line is skipped, not fatal."""
    base = root or LEDGER_DIR
    rows = Rows()
    paths = sorted(base.glob("ledger-*.jsonl"))
    if days is not None and days > 0:
        paths = paths[-days:]
    for path in paths:
        try:
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        rows.add(payload)
        except OSError:
            continue
    return rows


# ---------------------------------------------------------------------- helpers


def _day(row: dict[str, Any]) -> str:
    return str(row.get("t_ingest") or "")[:10]


def _sol(lamports: float) -> float:
    return lamports / SOL


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def _fmt(value: float, spec: str = ">8.2f") -> str:
    """Format, or a right-aligned dash of the SAME WIDTH when the value is not a number.

    A nan cell that collapses to a six-character dash silently shifts every column to its
    right, which is how a table stops being readable exactly when it has something to say.
    """
    width = "".join(c for c in spec.split(".")[0] if c.isdigit())
    if value == value:
        return format(value, spec)
    return format("-", f">{width}") if width else "-"


def _weighted_return(closes: list[dict[str, Any]], field_name: str) -> float:
    """Capital-weighted return: total P&L over total spend. Never a mean of ratios.

    A mean of per-position returns weights a 0.01 SOL clip the same as a 0.5 SOL one, and
    the desk's sizing rule deliberately makes those differ by 50x.
    """
    spend = sum(float(c.get("spend_lamports") or 0) for c in closes)
    pnl = sum(float(c.get(field_name) or 0) for c in closes)
    return pnl / spend if spend > 0 else float("nan")


# ---------------------------------------------------------------------- sections


def _header(rows: Rows) -> list[str]:
    days = sorted({_day(r) for r in rows.heartbeats + rows.closes if _day(r)})
    span = f"{days[0]} .. {days[-1]}" if days else "no rows"
    last = rows.heartbeats[-1] if rows.heartbeats else None
    age = ""
    if last is not None:
        seconds = datetime.now(tz=UTC).timestamp() - float(last.get("t_ingest_unix") or 0)
        age = f"   last heartbeat {seconds / 60:.1f} min ago"
        if seconds > 300:
            age += "   *** DESK MAY BE DEAD ***"
    return [
        "=" * 96,
        f"PAPER DESK — {span}   runs: {len(rows.run_ids)}   ledger rows: {rows.total:,}{age}",
        "=" * 96,
        "  Identical capital and identical friction per book. Entries fill at the NEXT",
        "  observation after the decision; exits at the FIRST observation after the trigger.",
    ]


def _sources(rows: Rows) -> list[str]:
    out = ["", "SOURCES — absence of data is not absence of events"]
    last = rows.heartbeats[-1] if rows.heartbeats else None
    sources = (last or {}).get("sources") or {}
    if not sources:
        return [*out, "  (no heartbeat carrying source state yet)"]
    out.append(f"  {'source':<16}{'events':>10}{'silent (s)':>13}{'state':>10}")
    for name, state in sorted(sources.items()):
        flag = "STALE" if state.get("stale") else "alive"
        out.append(
            f"  {name:<16}{int(state.get('events', 0)):>10,}"
            f"{float(state.get('silent_seconds', 0)):>13,.0f}{flag:>10}"
        )
    informative = sum(1 for w in rows.watch_closes if w.get("informative"))
    out.append(
        f"  watch windows: {len(rows.watch_opens)} opened, {len(rows.watch_closes)} closed, "
        f"{informative} informatively censored (OBSERVER_LOST / DISPLACED)"
    )
    return out


def _per_day(rows: Rows) -> list[str]:
    out = [
        "",
        "PER-BOOK, PER-DAY — net of friction, marked-out and pessimistic side by side",
        f"  {'book':<8}{'day':<12}{'n':>5}{'spend SOL':>11}{'pnl SOL':>10}"
        f"{'ret%':>9}{'pess%':>9}{'live%':>9}{'cens%':>8}",
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for close in rows.closes:
        grouped[(str(close.get("book")), _day(close))].append(close)
    if not grouped:
        return [*out, "  (no closed positions yet)"]
    for (book, day), closes in sorted(grouped.items()):
        spend = sum(float(c.get("spend_lamports") or 0) for c in closes)
        pnl = sum(float(c.get("pnl_lamports") or 0) for c in closes)
        live = [c for c in closes if c.get("mark_source") == "observed"]
        censored = sum(1 for c in closes if c.get("censored"))
        out.append(
            f"  {book:<8}{day:<12}{len(closes):>5}{_sol(spend):>11.4f}{_sol(pnl):>10.4f}"
            f"{_weighted_return(closes, 'pnl_lamports') * 100:>8.2f}%"
            f"{_weighted_return(closes, 'pnl_pessimistic_lamports') * 100:>8.2f}%"
            f"{(_weighted_return(live, 'pnl_lamports') * 100 if live else float('nan')):>8.2f}%"
            f"{censored / len(closes) * 100:>7.1f}%"
        )
    return out


def _open_positions(rows: Rows) -> list[str]:
    last = rows.heartbeats[-1] if rows.heartbeats else None
    books = (last or {}).get("books") or {}
    out = ["", "OPEN — as of the last heartbeat"]
    if not books:
        return [*out, "  (no heartbeat yet)"]
    out.append(f"  {'book':<8}{'open':>6}{'pending':>9}{'deployed SOL':>14}{'breaker':>10}")
    for book, state in sorted(books.items()):
        out.append(
            f"  {book:<8}{int(state.get('open_positions', 0)):>6}"
            f"{int(state.get('pending', 0)):>9}"
            f"{_sol(float(state.get('deployed_lamports', 0))):>14.4f}"
            f"{('PAUSED' if state.get('breaker_paused') else 'ok'):>10}"
        )
    return out


def _exit_mix(rows: Rows) -> list[str]:
    out = ["", "EXIT REASONS — and the censoring audit behind them"]
    by_book: dict[str, Counter[str]] = defaultdict(Counter)
    censor: dict[str, Counter[str]] = defaultdict(Counter)
    for close in rows.closes:
        by_book[str(close.get("book"))][str(close.get("exit_reason"))] += 1
        censor[str(close.get("book"))][str(close.get("censor_reason") or "none")] += 1
    if not by_book:
        return [*out, "  (no closed positions yet)"]
    for book in sorted(by_book):
        mix = ", ".join(f"{k}={v}" for k, v in by_book[book].most_common())
        cen = ", ".join(f"{k}={v}" for k, v in censor[book].most_common())
        out.append(f"  {book:<8} exits    {mix}")
        out.append(f"  {'':<8} censored {cen}")
    return out


def _survival(rows: Rows) -> list[str]:
    """Kaplan-Meier time-to-exit plus an Aalen-Johansen competing-risks split."""
    out = [
        "",
        "SURVIVAL — leaving observation is a COMPETING RISK, not ordinary censoring",
    ]
    try:
        from lifelines import AalenJohansenFitter, KaplanMeierFitter
    except ImportError:
        return [
            *out,
            "  lifelines not installed; run with `uv run --group research` for this section.",
            "  (declining to hand-roll it: hand-rolled censoring is what this desk exists",
            "   to stop, and an unfitted number here would be the same error in a new place)",
        ]
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for close in rows.closes:
        by_book[str(close.get("book"))].append(close)
    if not by_book:
        return [*out, "  (no closed positions yet)"]
    out.append(
        f"  {'book':<8}{'n':>5}{'events':>8}{'median exit (min)':>20}"
        f"{'CIF rule @1h':>15}{'CIF lost @1h':>15}"
    )
    for book, closes in sorted(by_book.items()):
        durations = [max(1e-6, float(c.get("holding_seconds") or 0.0)) for c in closes]
        # 0 = still at risk (never happens here; every row is a close), 1 = a rule fired,
        # 2 = the position left observation. Declaring the two causes separately is what
        # makes this a competing-risks fit rather than a survival fit with a blind spot.
        events = [
            1 if (str(c.get("exit_reason")) in RULE_EXITS and not c.get("censored")) else 2
            for c in closes
        ]
        n_rule = sum(1 for e in events if e == 1)
        km = KaplanMeierFitter()
        try:
            km.fit(durations, event_observed=[1] * len(durations))
            median = km.median_survival_time_ / 60.0
        except Exception:
            median = float("nan")
        cif_rule = cif_lost = float("nan")
        if len(set(events)) > 1 and len(durations) >= 4:
            for cause, slot in ((1, "rule"), (2, "lost")):
                try:
                    ajf = AalenJohansenFitter(seed=0, calculate_variance=False)
                    ajf.fit(durations, events, event_of_interest=cause)
                    frame = ajf.cumulative_density_
                    at = frame[frame.index <= 3600.0]
                    value = float(at.iloc[-1, 0]) if len(at) else 0.0
                except Exception:
                    value = float("nan")
                if slot == "rule":
                    cif_rule = value
                else:
                    cif_lost = value
        out.append(
            f"  {book:<8}{len(closes):>5}{n_rule:>8}{_fmt(median, '>20.1f')}"
            f"{_fmt(cif_rule, '>15.3f')}{_fmt(cif_lost, '>15.3f')}"
        )
    out.append(
        "  CIF = cumulative incidence at one hour. 'lost' is informative censoring: coins"
    )
    out.append(
        "  leave a board BECAUSE they stopped moving, so treating it as independent would"
    )
    out.append("  bias every return upward -- the +21.77% / -12.24% mechanism exactly.")
    return out


def _propensity(rows: Rows) -> list[str]:
    """What makes this ledger a designed experiment rather than a diary."""
    out = ["", "PROPENSITY LOG — OPE readiness (this is what the board tape never had)"]
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in rows.decisions:
        by_book[str(decision.get("book"))].append(decision)
    if not by_book:
        return [*out, "  (no decisions logged yet)"]
    out.append(
        f"  {'book':<8}{'decisions':>11}{'enter':>8}{'explored':>10}"
        f"{'mean p':>9}{'min p':>8}{'SNIPS ret%':>12}{'ESS':>8}"
    )
    rewards = {
        str(c.get("decision_id")): float(c.get("net_return") or 0.0) for c in rows.closes
    }
    for book, decisions in sorted(by_book.items()):
        props = [float(d.get("propensity") or 0.0) for d in decisions]
        enters = sum(1 for d in decisions if d.get("action") == "enter")
        explored = sum(1 for d in decisions if d.get("explored"))
        snips = ess = float("nan")
        logs = []
        try:
            from shitcoims_replay.ope import LoggedDecision, evaluate

            for decision in decisions:
                reward = rewards.get(str(decision.get("decision_id")))
                if reward is None:
                    continue
                logs.append(
                    LoggedDecision(
                        action=str(decision.get("action")),
                        propensity=float(decision.get("propensity")),
                        reward=reward,
                    )
                )
            # "Always enter" is the simplest target worth asking about, and asking it off
            # our OWN propensities is the whole reason they are logged.
            if logs:
                estimate = evaluate(logs, {"enter": 1.0})
                snips, ess = estimate.snips * 100.0, estimate.ess_fraction
        except Exception:
            pass
        out.append(
            f"  {book:<8}{len(decisions):>11,}{enters:>8}{explored:>10}"
            f"{_mean(props):>9.3f}{(min(props) if props else float('nan')):>8.3f}"
            f"{_fmt(snips, '>11.2f')}%{_fmt(ess, '>8.3f')}"
        )
    out.append(
        "  SNIPS scores 'always enter' against the desk's own logged propensities. Below"
    )
    out.append("  an effective-sample fraction of 0.10 the point value is theatre, not a result.")
    return out


def _toll_gate(rows: Rows) -> list[str]:
    """eta * D > VR, per pool, measured -- the standing version of the LP studies."""
    out = [
        "",
        "TOLL GATE — eta * D > VR   (eta = 2fN/(C*RV); concentration is SIGN-PRESERVING)",
    ]
    latest: dict[str, dict[str, Any]] = {}
    for gate in rows.gates:
        latest[str(gate.get("key"))] = gate
    if not latest:
        return [*out, "  (no pool flow observed; the cluster tape is the source and it may be cold)"]
    out.append(
        f"  {'pool':<18}{'C':>2}{'swaps':>7}{'N (quote)':>15}{'RV':>10}{'VR':>7}"
        f"{'eta':>8}{'D*=VR/eta':>11}{'stale(h)':>10}  verdict"
    )
    for _pool, gate in sorted(latest.items(), key=lambda kv: str(kv[1].get("label"))):
        eta = gate.get("eta")
        vr = gate.get("variance_ratio")
        need = gate.get("required_duty")
        refusal = gate.get("refusal")
        if refusal:
            verdict = refusal
        elif need is not None and need <= 1.0:
            verdict = f"+EV at D >= {need * 100:.0f}%"
        else:
            # D* > 1 is not "needs a tighter range": no duty cycle can exceed 100%, so the
            # pool is -EV at every rebalancing policy and every width.
            verdict = "-EV at any duty cycle"
        exact = str(gate.get("capacitance_basis", "")).startswith("vault_totals_exact")
        out.append(
            f"  {str(gate.get('label'))[:17]:<18}{('' if exact else '~'):>2}"
            f"{int(gate.get('swaps') or 0):>7}"
            f"{float(gate.get('notional_quote') or 0):>15,.1f}"
            f"{float(gate.get('realised_variance') or 0):>10.4f}"
            f"{_fmt(float(vr) if vr is not None else float('nan'), '>7.2f')}"
            f"{_fmt(float(eta) if eta is not None else float('nan'), '>8.3f')}"
            f"{_fmt(float(need) if need is not None else float('nan'), '>11.2f')}"
            f"{float(gate.get('tape_staleness_s') or 0) / 3600:>10.1f}  {verdict}"
        )
    out += [
        f"  VR at {VR_LAG * GRID_SECONDS / 60:.0f} min on a {GRID_SECONDS / 60:.0f}-min"
        " bounce-free grid. N is in the POOL's quote token, so a",
        "  token-token row is not in SOL and is not comparable across rows by size alone.",
        "  D* > 1 means no rebalancing policy can save the pool: narrowing scales BOTH",
        "  terms by 4/W and preserves the sign (W=4.0 gave eta 2.36-2.80; W=1.005, 0.59-0.70).",
        "  ~ marks a DLMM, where only IN-RANGE liquidity is the true capacitance and vault",
        "    totals overstate it -- so those eta are a LOWER bound, not a measurement.",
    ]
    if rows.accruals:
        fees = sum(float(a.get("fee_quote") or 0) for a in rows.accruals)
        out.append(
            f"  accruals: {len(rows.accruals)} fee events, {fees:,.6f} quote units, "
            f"{len(rows.rebalances)} one-sided redeploys"
        )
    return out


def _cross_book(rows: Rows) -> list[str]:
    """The comparison. Same capital, same friction, three horizons."""
    out = [
        "",
        "=" * 96,
        "CROSS-BOOK — identical capital, identical friction, one accounting",
        "=" * 96,
        f"  {'book':<8}{'closed':>8}{'spend SOL':>12}{'pnl SOL':>10}{'ret%':>9}"
        f"{'pess%':>9}{'%/SOL-day':>12}{'cens%':>8}{'median hold':>13}",
    ]
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for close in rows.closes:
        by_book[str(close.get("book"))].append(close)
    for book in (str(b) for b in BOOKS):
        closes = by_book.get(book) or []
        if not closes:
            out.append(
                f"  {book:<8}{0:>8}{'—':>12}{'—':>10}{'—':>9}{'—':>9}{'—':>12}{'—':>8}{'—':>13}"
            )
            continue
        spend = sum(float(c.get("spend_lamports") or 0) for c in closes)
        pnl = sum(float(c.get("pnl_lamports") or 0) for c in closes)
        ret = _weighted_return(closes, "pnl_lamports")
        hours = [float(c.get("holding_seconds") or 0) / 3600.0 for c in closes]
        # THE horizon-fair statistic: P&L per unit of capital held per hour. Comparing a
        # 20-minute scalp with a 3-day LP range on return-per-round flatters the scalp by
        # exactly the ratio of their holding times; comparing on return-per-SOL-hour is
        # what the operator's question ("which use of the same SOL") actually asks.
        capital_hours = sum(
            float(c.get("spend_lamports") or 0) * h for c, h in zip(closes, hours, strict=True)
        )
        per_capital_day = pnl / (capital_hours / 24.0) if capital_hours > 0 else float("nan")
        censored = sum(1 for c in closes if c.get("censored")) / len(closes)
        out.append(
            f"  {book:<8}{len(closes):>8}{_sol(spend):>12.4f}{_sol(pnl):>10.4f}"
            f"{ret * 100:>8.2f}%{_weighted_return(closes, 'pnl_pessimistic_lamports') * 100:>8.2f}%"
            f"{_fmt(per_capital_day * 100, '>11.1f')}%{censored * 100:>7.1f}%"
            f"{statistics.median(hours) * 60:>11.1f}m"
        )
    out += [
        "",
        "  ret%      marks a departed position at the last price seen AT OR BEFORE its trigger.",
        "  pess%     marks the same position as a total loss. The gap is the assumption's size.",
        "  %/SOL-day P&L per SOL of capital per DAY held -- the only horizon-fair column,",
        "            because return-per-round rewards a book purely for closing sooner. On a",
        "            handful of very short holds it annualises noise; read it once n is real.",
        "  These are PRIORS under test, not results: the short book's bracket scored",
        "  +0.156%/round at t = 0.24 in the study that suggested it, and dies at 1-2%",
        "  adverse fill. Nothing here is an edge until this table says so on its own data.",
    ]
    return out


def _defects(rows: Rows) -> list[str]:
    if not rows.defects:
        return []
    counts = Counter(str(d.get("detail")) for d in rows.defects)
    return [
        "",
        "DEFECTS — things the desk refused to price rather than guess at",
        *(f"  {detail:<48}{count:>6}" for detail, count in counts.most_common()),
    ]


def render(rows: Rows) -> str:
    sections: list[list[str]] = [
        _header(rows),
        _sources(rows),
        _open_positions(rows),
        _per_day(rows),
        _exit_mix(rows),
        _survival(rows),
        _propensity(rows),
        _toll_gate(rows),
        _defects(rows),
        _cross_book(rows),
    ]
    return "\n".join(line for section in sections for line in section)


def _json_summary(rows: Rows) -> dict[str, Any]:
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for close in rows.closes:
        by_book[str(close.get("book"))].append(close)
    return {
        "runs": sorted(rows.run_ids),
        "rows": rows.total,
        "books": {
            book: {
                "closed": len(closes),
                "spend_lamports": sum(int(c.get("spend_lamports") or 0) for c in closes),
                "pnl_lamports": sum(int(c.get("pnl_lamports") or 0) for c in closes),
                "pnl_pessimistic_lamports": sum(
                    int(c.get("pnl_pessimistic_lamports") or 0) for c in closes
                ),
                "return": _weighted_return(closes, "pnl_lamports"),
                "return_pessimistic": _weighted_return(closes, "pnl_pessimistic_lamports"),
                "censoring_rate": (
                    sum(1 for c in closes if c.get("censored")) / len(closes) if closes else None
                ),
            }
            for book, closes in sorted(by_book.items())
        },
        "decisions": len(rows.decisions),
        "gates": len(rows.gates),
        "accruals": len(rows.accruals),
        "defects": len(rows.defects),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperdesk-report")
    parser.add_argument("--days", type=int, default=None, help="most recent N ledger days")
    parser.add_argument("--dir", type=Path, default=None, help="ledger directory")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = read_ledger(args.dir, days=args.days)
    if args.json:
        print(json.dumps(_json_summary(rows), indent=1, default=str))
    else:
        print(render(rows))
    return 0
