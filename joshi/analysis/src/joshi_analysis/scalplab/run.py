"""The lab runner: tapes in, honest report out, policy files only when a cell earns one.

Usage::

    uv run --offline python -m joshi_analysis.scalplab \
        <tape-dir> [<tape-dir> ...] --out <dir> --author-knowledge "..."

Reads every catalog strictly read-only, executes the pre-registered protocol
(REGISTRATION.md), writes ``lab_report.json`` into ``--out``, and for every
CANDIDATE_POLICY verdict refits the winning family on the full corpus (declared final refit)
and writes a declared policy file beside the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analog import fit_analog
from .evaluation import FAMILIES, LabRun, run_lab
from .hawkes import fit_hawkes_classifier
from .logit import fit_logistic
from .policy import declared_policy, write_policy
from .tape import LoadedTape, TapeError, load_tape
from .vocabulary import (
    CUSUM_DRIFT,
    CUSUM_THRESHOLD,
    DEFAULT_VENUE_FLOOR_BPS,
    HORIZONS_K,
    VERDICT_CANDIDATE,
)

EXIT_ALARM = (
    f"two-sided causal CUSUM on running-standardized r1 (drift k={CUSUM_DRIFT}, threshold "
    f"h={CUSUM_THRESHOLD}): exit any open position when the down-alarm fires"
)


def _refit_full_corpus(run: LabRun, family: str, horizon: int) -> dict | None:
    """The declared final refit behind a candidate's shipped parameters."""
    if family in ("logit", "analog"):
        vectors: list[list[float]] = []
        labels: list[int] = []
        for prepared in run.prepared:
            _, vecs, ys = prepared.judged(horizon)
            vectors.extend(vecs)
            labels.extend(ys)
        if not vectors or len(set(labels)) < 2:
            return None
        model = fit_analog(vectors, labels) if family == "analog" else fit_logistic(
            vectors, labels
        )
        return model.params()
    bundle = []
    for prepared in run.prepared:
        idx, _, ys = prepared.judged(horizon)
        if idx:
            bundle.append((prepared.sequence, idx, ys))
    if not bundle or len({y for _, _, ys in bundle for y in ys}) < 2:
        return None
    return fit_hawkes_classifier(bundle).params()


def emit_policies(run: LabRun, out_dir: Path, author_knowledge: str) -> list[Path]:
    written: list[Path] = []
    decision_clocks = sorted(
        {t.provenance.decision_clock_statement for t in run.tapes}
    )
    floors = sorted({t.provenance.venue_floor_bps for t in run.tapes})
    for verdict in run.cell_verdicts:
        if verdict.verdict != VERDICT_CANDIDATE:
            continue
        model_params = _refit_full_corpus(run, verdict.family, verdict.horizon_k)
        if model_params is None:
            continue
        for tau in verdict.candidate_taus:
            doc = declared_policy(
                family=verdict.family,
                model_params=model_params,
                horizon_k=verdict.horizon_k,
                threshold=tau,
                venue_floor_bps=max(floors),
                decision_clock=" | ".join(decision_clocks),
                exit_alarm=EXIT_ALARM,
                tape_provenances=[t.provenance.as_dict() for t in run.tapes],
                evaluation=verdict.as_dict(),
                author_knowledge=author_knowledge,
            )
            name = f"policy_{verdict.family}_k{verdict.horizon_k}_tau{int(tau * 100)}.json"
            written.append(write_policy(out_dir / name, doc))
    return written


def _summary_lines(run: LabRun) -> list[str]:
    lines = []
    for tape in run.tapes:
        p = tape.provenance
        lines.append(
            f"tape {Path(p.tape_path).name}: {p.source_kind}, {p.n_events} events, "
            f"{len(p.coins)} coin(s), clock={p.arrival_clock}, floor={p.venue_floor_bps} bps, "
            f"gaps={len(p.coverage_gaps)}"
        )
    corpus = run.report["corpus"]
    lines.append(
        f"corpus: {corpus['nCoins']} coin(s), {corpus['nSeries']} series, "
        f"{corpus['nEvents']} events across {corpus['nTapes']} tape(s)"
    )
    for verdict in run.cell_verdicts:
        brier = (
            f", pooled brier {verdict.pooled_brier:.4f}"
            if verdict.pooled_brier is not None
            else ""
        )
        lines.append(
            f"{verdict.family} k={verdict.horizon_k}: {verdict.verdict} "
            f"({verdict.n_folds_gated_in}/{verdict.n_folds} folds gated in{brier}) — "
            f"{verdict.reason}"
        )
    return lines


def run_and_write(
    tape_dirs: list[str],
    out_dir: str | Path,
    author_knowledge: str,
    venue_floor_bps: int = DEFAULT_VENUE_FLOOR_BPS,
    horizons: tuple[int, ...] = HORIZONS_K,
    families: tuple[str, ...] = FAMILIES,
    with_hawkes_diagnostics: bool = True,
) -> LabRun:
    tapes: list[LoadedTape] = []
    skipped: list[str] = []
    for tape_dir in tape_dirs:
        try:
            tape = load_tape(tape_dir, venue_floor_bps=venue_floor_bps)
        except TapeError as error:
            skipped.append(f"{tape_dir}: {error}")
            continue
        if tape.provenance.n_events == 0:
            skipped.append(f"{tape_dir}: zero decodable trade events")
            continue
        tapes.append(tape)
    if not tapes:
        raise TapeError("no loadable tape with events among: " + "; ".join(skipped or ["(none)"]))
    run = run_lab(tapes, horizons, families, with_hawkes_diagnostics)
    run.report["skippedTapes"] = skipped
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "lab_report.json").write_text(
        json.dumps(run.report, indent=2, sort_keys=True, default=str) + "\n"
    )
    emit_policies(run, out, author_knowledge)
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="joshi_analysis.scalplab", description=__doc__)
    parser.add_argument("tapes", nargs="+", help="catalog directories (read-only)")
    parser.add_argument("--out", required=True, help="output directory for report + policies")
    parser.add_argument(
        "--author-knowledge",
        required=True,
        help="what you already knew about these tapes; blank is refused",
    )
    parser.add_argument(
        "--floor-bps",
        type=int,
        default=DEFAULT_VENUE_FLOOR_BPS,
        help="declared venue floor applied to every tape (default: the conservative 250)",
    )
    parser.add_argument(
        "--no-hawkes-diagnostics",
        action="store_true",
        help="skip the per-window branching diagnostics (faster)",
    )
    args = parser.parse_args(argv)
    if not args.author_knowledge.strip():
        parser.error("--author-knowledge may not be blank")
    run = run_and_write(
        args.tapes,
        args.out,
        args.author_knowledge,
        venue_floor_bps=args.floor_bps,
        with_hawkes_diagnostics=not args.no_hawkes_diagnostics,
    )
    for line in _summary_lines(run):
        print(line)
    for line in run.report.get("skippedTapes", []):
        print(f"skipped: {line}")
    print(f"report: {Path(args.out) / 'lab_report.json'}")
    return 0
