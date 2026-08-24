"""The pre-registered evaluation protocol, executable form.

REGISTRATION.md in this package is the registration; this module is its executable copy.
Leave-one-coin-out at coin (mint) granularity — tapes covering the same mint are one coin and
are never each other's training data. Time order within a coin is never shuffled. The claims
are calibration claims (reliability bins, Brier); policy extraction is a declared threshold
sweep; economics stay in the Rust harnesses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .analog import fit_analog
from .featureset import feature_matrix
from .hawkes import Sequence, dither_times, fit_hawkes, fit_hawkes_classifier, windowed_branching
from .labels import LabelSet, floor_clearing_labels
from .logit import fit_logistic
from .tape import LoadedTape, TapeEvent, TapeProvenance
from .vocabulary import (
    CANDIDATE_MIN_FIRED,
    CANDIDATE_PRECISION_MULTIPLE,
    GATE_EVAL_MIN_EVENTS,
    GATE_EVAL_MIN_POS,
    GATE_HAWKES_MIN_EVENTS_PER_COIN,
    GATE_TRAIN_MIN_COINS,
    GATE_TRAIN_MIN_EVENTS,
    HORIZONS_K,
    NOT_AN_ECONOMIC_VERDICT,
    ONE_TAPE_FITS_NOTHING,
    REGISTRATION_VERSION,
    THRESHOLDS,
    VERDICT_CANDIDATE,
    VERDICT_INSUFFICIENT,
    VERDICT_NULL,
    WILSON_Z_90,
)

FAMILIES = ("hawkes", "analog", "logit")


@dataclass(frozen=True)
class CoinSeries:
    """One tape's view of one coin. Several series may share a coin; splits never do."""

    coin: str  # mint
    series_id: str  # mint prefix @ tape basename
    events: list[TapeEvent]
    provenance: TapeProvenance


def build_corpus(tapes: list[LoadedTape], min_events: int = 50) -> list[CoinSeries]:
    """Every coin series with at least ``min_events`` trades, deterministic order."""
    corpus: list[CoinSeries] = []
    for tape in tapes:
        basename = Path(tape.provenance.tape_path).name
        for mint, events in sorted(tape.events_by_coin.items()):
            if len(events) < min_events:
                continue
            corpus.append(
                CoinSeries(
                    coin=mint,
                    series_id=f"{mint[:8]}@{basename}",
                    events=events,
                    provenance=tape.provenance,
                )
            )
    corpus.sort(key=lambda s: (-len(s.events), s.series_id))
    return corpus


# --- metrics ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None

    def as_dict(self) -> dict:
        return {
            "low": self.low,
            "high": self.high,
            "n": self.n,
            "meanPredicted": self.mean_predicted,
            "observedRate": self.observed_rate,
        }


def calibration_bins(
    predictions: list[float], labels: list[int], n_bins: int = 10
) -> list[CalibrationBin]:
    sums = [0.0] * n_bins
    hits = [0] * n_bins
    counts = [0] * n_bins
    for p, y in zip(predictions, labels, strict=True):
        idx = min(int(p * n_bins), n_bins - 1)
        counts[idx] += 1
        sums[idx] += p
        hits[idx] += y
    out = []
    for b in range(n_bins):
        out.append(
            CalibrationBin(
                low=b / n_bins,
                high=(b + 1) / n_bins,
                n=counts[b],
                mean_predicted=sums[b] / counts[b] if counts[b] else None,
                observed_rate=hits[b] / counts[b] if counts[b] else None,
            )
        )
    return out


def brier_score(predictions: list[float], labels: list[int]) -> float:
    if not predictions:
        raise ValueError("no predictions")
    return sum((p - y) ** 2 for p, y in zip(predictions, labels, strict=True)) / len(predictions)


def wilson_lower(successes: int, n: int, z: float = WILSON_Z_90) -> float:
    if n == 0:
        return 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - margin) / denom)


@dataclass(frozen=True)
class ThresholdCell:
    tau: float
    fired: int
    hits: int

    @property
    def precision(self) -> float | None:
        return self.hits / self.fired if self.fired else None

    @property
    def wilson_lower_90(self) -> float:
        return wilson_lower(self.hits, self.fired)

    def as_dict(self) -> dict:
        return {
            "tau": self.tau,
            "fired": self.fired,
            "hits": self.hits,
            "precision": self.precision,
            "wilsonLower90": self.wilson_lower_90,
        }


def threshold_cells(predictions: list[float], labels: list[int]) -> list[ThresholdCell]:
    out = []
    for tau in THRESHOLDS:
        fired = sum(1 for p in predictions if p >= tau)
        hits = sum(y for p, y in zip(predictions, labels, strict=True) if p >= tau)
        out.append(ThresholdCell(tau=tau, fired=fired, hits=hits))
    return out


# --- per-series preparation ---------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedSeries:
    series: CoinSeries
    feature_indices: list[int]
    vectors: list[list[float]]
    sequence: Sequence  # dithered clock seconds + marks, whole series
    label_sets: dict[int, LabelSet]  # horizon -> labels

    def judged(self, horizon: int) -> tuple[list[int], list[list[float]], list[int]]:
        """Indices (into events), vectors, labels where a label is defined post-warmup."""
        labels = self.label_sets[horizon].labels
        idx: list[int] = []
        vecs: list[list[float]] = []
        ys: list[int] = []
        for pos, event_index in enumerate(self.feature_indices):
            y = labels[event_index]
            if y is None:
                continue
            idx.append(event_index)
            vecs.append(self.vectors[pos])
            ys.append(y)
        return idx, vecs, ys


def prepare_series(series: CoinSeries, horizons: tuple[int, ...] = HORIZONS_K) -> PreparedSeries:
    indices, vectors = feature_matrix(series.events)
    prices = [event.price for event in series.events]
    floor = series.provenance.venue_floor_bps
    label_sets = {k: floor_clearing_labels(prices, k, floor) for k in horizons}
    times: list[float] = []
    for event in series.events:
        stamp = event.event_time_us if event.event_time_us is not None else event.arrival_wall_us
        times.append((stamp or 0) / 1_000_000)
    marks = [0 if event.side == "buy" else 1 for event in series.events]
    return PreparedSeries(
        series=series,
        feature_indices=indices,
        vectors=vectors,
        sequence=(dither_times(times), marks),
        label_sets=label_sets,
    )


# --- folds --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldResult:
    family: str
    horizon_k: int
    judged_series: str
    judged_coin: str
    n_train_coins: int
    n_train_events: int
    n_eval_events: int
    n_eval_pos: int
    gates_passed: bool
    gate_failures: tuple[str, ...]
    base_rate: float | None
    brier: float | None
    calibration: tuple[CalibrationBin, ...]
    cells: tuple[ThresholdCell, ...]
    predictions: tuple[float, ...] = field(repr=False, default=())
    labels: tuple[int, ...] = field(repr=False, default=())

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "horizonK": self.horizon_k,
            "judgedSeries": self.judged_series,
            "judgedCoin": self.judged_coin[:12],
            "nTrainCoins": self.n_train_coins,
            "nTrainEvents": self.n_train_events,
            "nEvalEvents": self.n_eval_events,
            "nEvalPos": self.n_eval_pos,
            "gatesPassed": self.gates_passed,
            "gateFailures": list(self.gate_failures),
            "baseRate": self.base_rate,
            "brier": self.brier,
            "calibration": [b.as_dict() for b in self.calibration],
            "thresholdCells": [c.as_dict() for c in self.cells],
        }


def _train_gate_failures(
    family: str, train_events_per_coin: dict[str, int]
) -> list[str]:
    failures = []
    n_coins = len(train_events_per_coin)
    n_events = sum(train_events_per_coin.values())
    if n_coins < GATE_TRAIN_MIN_COINS[family]:
        failures.append(
            f"train coins {n_coins} < {GATE_TRAIN_MIN_COINS[family]} required for {family}"
        )
    if n_events < GATE_TRAIN_MIN_EVENTS[family]:
        failures.append(
            f"train labeled events {n_events} < {GATE_TRAIN_MIN_EVENTS[family]} "
            f"required for {family}"
        )
    if family == "hawkes":
        thin = [c for c, n in train_events_per_coin.items() if n < GATE_HAWKES_MIN_EVENTS_PER_COIN]
        if thin:
            failures.append(
                f"{len(thin)} train coin(s) below {GATE_HAWKES_MIN_EVENTS_PER_COIN} "
                "labeled events for hawkes"
            )
    return failures


def _fit_family(
    family: str,
    train: list[PreparedSeries],
    horizon: int,
):
    """Fit one family on the train series; returns a predict(prepared) -> list[float]."""
    if family in ("logit", "analog"):
        vectors: list[list[float]] = []
        labels: list[int] = []
        for prepared in train:
            _, vecs, ys = prepared.judged(horizon)
            vectors.extend(vecs)
            labels.extend(ys)
        if not vectors or len(set(labels)) < 2:
            return None
        model = fit_analog(vectors, labels) if family == "analog" else fit_logistic(
            vectors, labels
        )

        def predict(prepared: PreparedSeries) -> list[float]:
            _, vecs, _ = prepared.judged(horizon)
            return model.predict_proba(vecs)

        return predict
    if family == "hawkes":
        bundle = []
        for prepared in train:
            idx, _, ys = prepared.judged(horizon)
            if idx:
                bundle.append((prepared.sequence, idx, ys))
        if not bundle or len({y for _, _, ys in bundle for y in ys}) < 2:
            return None
        classifier = fit_hawkes_classifier(bundle)

        def predict(prepared: PreparedSeries) -> list[float]:
            idx, _, _ = prepared.judged(horizon)
            return classifier.predict_proba(prepared.sequence, idx)

        return predict
    raise ValueError(f"unknown family {family!r}")


def run_folds(
    prepared: list[PreparedSeries],
    horizons: tuple[int, ...] = HORIZONS_K,
    families: tuple[str, ...] = FAMILIES,
) -> list[FoldResult]:
    """Every (family, horizon, judged coin) fold, models fit on the other coins only."""
    results: list[FoldResult] = []
    coins = sorted({p.series.coin for p in prepared})
    for family in families:
        for horizon in horizons:
            for coin in coins:
                train = [p for p in prepared if p.series.coin != coin]
                judged = [p for p in prepared if p.series.coin == coin]
                train_events_per_coin: dict[str, int] = {}
                for p in train:
                    _, _, ys = p.judged(horizon)
                    if ys:
                        train_events_per_coin[p.series.coin] = (
                            train_events_per_coin.get(p.series.coin, 0) + len(ys)
                        )
                gate_failures = _train_gate_failures(family, train_events_per_coin)
                if not train:
                    gate_failures.insert(0, "no cross-coin training data")
                predictor = _fit_family(family, train, horizon) if train else None
                if predictor is None and train:
                    gate_failures.append("training labels degenerate (single class or empty)")
                for p in judged:
                    idx, _, ys = p.judged(horizon)
                    fold_failures = list(gate_failures)
                    if len(ys) < GATE_EVAL_MIN_EVENTS:
                        fold_failures.append(
                            f"eval labeled events {len(ys)} < {GATE_EVAL_MIN_EVENTS}"
                        )
                    if sum(ys) < GATE_EVAL_MIN_POS:
                        fold_failures.append(f"eval positives {sum(ys)} < {GATE_EVAL_MIN_POS}")
                    predictions = predictor(p) if predictor and idx else []
                    has_preds = bool(predictions)
                    results.append(
                        FoldResult(
                            family=family,
                            horizon_k=horizon,
                            judged_series=p.series.series_id,
                            judged_coin=p.series.coin,
                            n_train_coins=len(train_events_per_coin),
                            n_train_events=sum(train_events_per_coin.values()),
                            n_eval_events=len(ys),
                            n_eval_pos=sum(ys),
                            gates_passed=not fold_failures,
                            gate_failures=tuple(fold_failures),
                            base_rate=(sum(ys) / len(ys)) if ys else None,
                            brier=brier_score(predictions, ys) if has_preds else None,
                            calibration=tuple(calibration_bins(predictions, ys))
                            if has_preds
                            else (),
                            cells=tuple(threshold_cells(predictions, ys)) if has_preds else (),
                            predictions=tuple(predictions),
                            labels=tuple(ys),
                        )
                    )
    return results


# --- verdicts -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CellVerdict:
    family: str
    horizon_k: int
    verdict: str
    reason: str
    n_folds: int
    n_folds_gated_in: int
    pooled_base_rate: float | None
    pooled_brier: float | None
    pooled_calibration: tuple[CalibrationBin, ...]
    pooled_cells: tuple[ThresholdCell, ...]
    candidate_taus: tuple[float, ...]
    honesty: str | None

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "horizonK": self.horizon_k,
            "verdict": self.verdict,
            "reason": self.reason,
            "nFolds": self.n_folds,
            "nFoldsGatedIn": self.n_folds_gated_in,
            "pooledBaseRate": self.pooled_base_rate,
            "pooledBrier": self.pooled_brier,
            "pooledCalibration": [b.as_dict() for b in self.pooled_calibration],
            "pooledThresholdCells": [c.as_dict() for c in self.pooled_cells],
            "candidateTaus": list(self.candidate_taus),
            "honesty": self.honesty,
        }


def verdicts(fold_results: list[FoldResult]) -> list[CellVerdict]:
    out: list[CellVerdict] = []
    keys = sorted({(r.family, r.horizon_k) for r in fold_results})
    for family, horizon in keys:
        folds = [r for r in fold_results if r.family == family and r.horizon_k == horizon]
        gated_in = [r for r in folds if r.gates_passed]
        preds: list[float] = []
        labels: list[int] = []
        for r in gated_in:
            preds.extend(r.predictions)
            labels.extend(r.labels)
        if not gated_in or not preds:
            reasons = sorted({f for r in folds for f in r.gate_failures})
            out.append(
                CellVerdict(
                    family=family,
                    horizon_k=horizon,
                    verdict=VERDICT_INSUFFICIENT,
                    reason="no fold passed every pre-registered data gate: "
                    + "; ".join(reasons[:6]),
                    n_folds=len(folds),
                    n_folds_gated_in=0,
                    pooled_base_rate=None,
                    pooled_brier=None,
                    pooled_calibration=(),
                    pooled_cells=(),
                    candidate_taus=(),
                    honesty=ONE_TAPE_FITS_NOTHING,
                )
            )
            continue
        base_rate = sum(labels) / len(labels)
        cells = threshold_cells(preds, labels)
        winning = tuple(
            c.tau
            for c in cells
            if c.fired >= CANDIDATE_MIN_FIRED
            and c.wilson_lower_90 > CANDIDATE_PRECISION_MULTIPLE * base_rate
        )
        verdict = VERDICT_CANDIDATE if winning else VERDICT_NULL
        reason = (
            f"threshold cell(s) {list(winning)} cleared the pre-registered candidate rule"
            if winning
            else "gates passed; no threshold cell cleared the pre-registered candidate rule"
        )
        out.append(
            CellVerdict(
                family=family,
                horizon_k=horizon,
                verdict=verdict,
                reason=reason,
                n_folds=len(folds),
                n_folds_gated_in=len(gated_in),
                pooled_base_rate=base_rate,
                pooled_brier=brier_score(preds, labels),
                pooled_calibration=tuple(calibration_bins(preds, labels)),
                pooled_cells=tuple(cells),
                candidate_taus=winning,
                honesty=NOT_AN_ECONOMIC_VERDICT,
            )
        )
    return out


# --- descriptive Hawkes diagnostics -------------------------------------------------------------


def hawkes_diagnostics(prepared: list[PreparedSeries]) -> list[dict]:
    """Per-series pooled and per-window branching ratios. Descriptive, in-sample, labeled so."""
    out: list[dict] = []
    for p in prepared:
        if len(p.sequence[0]) < 2:
            continue
        fit = fit_hawkes([p.sequence])
        windows = windowed_branching(p.sequence)
        out.append(
            {
                "series": p.series.series_id,
                "nEvents": len(p.sequence[0]),
                "scope": "descriptive, fit in-sample on this series alone",
                "pooled": fit.params.as_dict(),
                "windows": [
                    {
                        "startIndex": w.start_index,
                        "nEvents": w.n_events,
                        "branchingRatio": w.branching_ratio,
                        "beta": w.beta,
                    }
                    for w in windows
                ],
            }
        )
    return out


# --- the report ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabRun:
    """One full protocol execution, with the objects still in hand for refits."""

    tapes: list[LoadedTape]
    corpus: list[CoinSeries]
    prepared: list[PreparedSeries]
    fold_results: list[FoldResult]
    cell_verdicts: list[CellVerdict]
    report: dict


def run_lab(
    tapes: list[LoadedTape],
    horizons: tuple[int, ...] = HORIZONS_K,
    families: tuple[str, ...] = FAMILIES,
    with_hawkes_diagnostics: bool = True,
) -> LabRun:
    corpus = build_corpus(tapes)
    prepared = [prepare_series(series, horizons) for series in corpus]
    fold_results = run_folds(prepared, horizons, families)
    cell_verdicts = verdicts(fold_results)
    n_events = sum(len(s.events) for s in corpus)
    report = {
        "contract": "joshi.scalplab.lab_report.v1",
        "registration": REGISTRATION_VERSION,
        "honesty": {
            "oneTapeFitsNothing": ONE_TAPE_FITS_NOTHING,
            "notAnEconomicVerdict": NOT_AN_ECONOMIC_VERDICT,
        },
        "corpus": {
            "nTapes": len(tapes),
            "nCoins": len({s.coin for s in corpus}),
            "nSeries": len(corpus),
            "nEvents": n_events,
            "series": [
                {
                    "seriesId": s.series_id,
                    "coin": s.coin[:12],
                    "nEvents": len(s.events),
                    "sourceKind": s.provenance.source_kind,
                    "arrivalClock": s.provenance.arrival_clock,
                    "venueFloorBps": s.provenance.venue_floor_bps,
                    "decisionClock": s.provenance.decision_clock_statement,
                }
                for s in corpus
            ],
            "tapes": [t.provenance.as_dict() for t in tapes],
        },
        "labelSummary": [
            {
                "seriesId": p.series.series_id,
                "horizonK": k,
                "floorBps": p.label_sets[k].floor_bps,
                "nDefined": p.label_sets[k].n_defined,
                "nPositive": p.label_sets[k].n_positive,
                "baseRate": p.label_sets[k].base_rate,
            }
            for p in prepared
            for k in horizons
        ],
        "folds": [r.as_dict() for r in fold_results],
        "verdicts": [v.as_dict() for v in cell_verdicts],
    }
    if with_hawkes_diagnostics:
        report["hawkesDiagnostics"] = hawkes_diagnostics(prepared)
    return LabRun(
        tapes=tapes,
        corpus=corpus,
        prepared=prepared,
        fold_results=fold_results,
        cell_verdicts=cell_verdicts,
        report=report,
    )


def lab_report(
    tapes: list[LoadedTape],
    horizons: tuple[int, ...] = HORIZONS_K,
    families: tuple[str, ...] = FAMILIES,
    with_hawkes_diagnostics: bool = True,
) -> dict:
    return run_lab(tapes, horizons, families, with_hawkes_diagnostics).report
