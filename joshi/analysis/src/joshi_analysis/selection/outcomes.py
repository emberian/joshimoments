"""Forward outcomes for a selection event, measured only on data later than the act.

Two legs make an outcome:

  baseline  the candidate's price IN THE DECISION SCENE -- the number the operator was
            actually looking at. Its market clock is at or before the decision by
            construction, so it cannot leak.

  forward   the same mint's price in a LATER durably retained scene, at the observation
            whose market clock lands nearest the horizon inside the tolerance band.

The market clock throughout is the candidate's own `lastObservedAt`, never the scene's
`renderedAt`. A scene rendered at noon can carry a price observed at 11:03; dating that
price to noon manufactures return out of rendering activity.

A forward observation is admitted only if its market clock is STRICTLY GREATER than the
decision instant. That single comparison is the entire no-leakage guarantee, and it is
made against the act's issue time, not the scene's render time.

Missing either leg means the outcome is ABSENT. Absent is a recorded state with a reason,
never a zero and never a silent drop.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .events import SelectionEventV1, iter_scene_prices
from .preregistration import (
    HORIZON_TOLERANCE_FRACTION,
    OUTCOME_ABSENT_NO_BASELINE,
    OUTCOME_ABSENT_NO_FORWARD,
    OUTCOME_ABSENT_NO_PASSED,
    OUTCOME_PRESENT,
)


@dataclass(frozen=True, slots=True)
class PricePoint:
    mint: str
    price_sol: float
    market_clock_us: int
    provenance: str


class ForwardPriceIndex:
    """Every priced candidate observation the catalogs retained, keyed by mint and clock.

    Built from the same durable view blobs the scenes are reconstructed from, so a forward
    price is always a byte that Joshi actually kept, never an interpolation and never a
    fetch. As the operator keeps hunting, later scenes deepen this index automatically.
    """

    def __init__(self) -> None:
        self._by_mint: dict[str, list[tuple[int, float, str]]] = {}
        self._sealed = False

    def add(self, point: PricePoint) -> None:
        if self._sealed:
            raise RuntimeError("ForwardPriceIndex is sealed")
        if point.price_sol <= 0:
            # A non-positive price has no log return. Not a zero outcome: no observation.
            return
        self._by_mint.setdefault(point.mint, []).append(
            (point.market_clock_us, point.price_sol, point.provenance)
        )

    def seal(self) -> ForwardPriceIndex:
        for series in self._by_mint.values():
            series.sort()
        self._sealed = True
        return self

    @property
    def mints(self) -> frozenset[str]:
        return frozenset(self._by_mint)

    def observation_count(self, mint: str) -> int:
        return len(self._by_mint.get(mint, ()))

    def nearest_after(
        self, mint: str, after_us: int, target_us: int, tolerance_us: int
    ) -> PricePoint | None:
        """Observation strictly after `after_us` and nearest `target_us` within tolerance.

        `after_us` is the no-leakage boundary and `target_us` the horizon; they are separate
        arguments on purpose, because the admissible band is defined around the horizon while
        the leakage cut is defined at the act.
        """
        series = self._by_mint.get(mint)
        if not series:
            return None
        low = max(after_us + 1, target_us - tolerance_us)
        high = target_us + tolerance_us
        if high < low:
            return None
        start = bisect.bisect_left(series, (low, float("-inf"), ""))
        best: tuple[int, float, str] | None = None
        best_gap = tolerance_us + 1
        for idx in range(start, len(series)):
            clock, price, provenance = series[idx]
            if clock > high:
                break
            gap = abs(clock - target_us)
            if gap < best_gap:
                best_gap = gap
                best = (clock, price, provenance)
        if best is None:
            return None
        return PricePoint(mint=mint, price_sol=best[1], market_clock_us=best[0], provenance=best[2])


def build_price_index(catalogs: Sequence[Path]) -> ForwardPriceIndex:
    index = ForwardPriceIndex()
    for catalog in catalogs:
        for scene_id, _commit, mint, price, clock in iter_scene_prices(Path(catalog)):
            index.add(
                PricePoint(
                    mint=mint,
                    price_sol=price,
                    market_clock_us=clock,
                    provenance=f"scene:{scene_id}",
                )
            )
    return index.seal()


@dataclass(frozen=True, slots=True)
class CandidateOutcome:
    subject_key: str
    was_chosen: bool
    baseline_price_sol: float | None
    baseline_clock_us: int | None
    forward_price_sol: float | None
    forward_clock_us: int | None
    forward_provenance: str | None
    log_return: float | None
    status: str

    @property
    def scored(self) -> bool:
        return self.log_return is not None


@dataclass(frozen=True, slots=True)
class EventOutcomeV1:
    """One event's outcome at one horizon. Absent is a first-class result."""

    event_id: str
    scene_id: str
    horizon_seconds: int
    decision_wall_us: int
    status: str
    candidates: tuple[CandidateOutcome, ...]

    @property
    def scored_candidates(self) -> tuple[CandidateOutcome, ...]:
        return tuple(c for c in self.candidates if c.scored)

    @property
    def scored_chosen(self) -> tuple[CandidateOutcome, ...]:
        return tuple(c for c in self.scored_candidates if c.was_chosen)

    @property
    def scored_passed(self) -> tuple[CandidateOutcome, ...]:
        return tuple(c for c in self.scored_candidates if not c.was_chosen)

    @property
    def is_scored(self) -> bool:
        return self.status == OUTCOME_PRESENT

    def to_json_obj(self) -> dict[str, object]:
        return {
            "eventId": self.event_id,
            "sceneId": self.scene_id,
            "horizonSeconds": self.horizon_seconds,
            "status": self.status,
            "choiceSetSize": len(self.candidates),
            "scoredCount": len(self.scored_candidates),
            "scoredChosen": len(self.scored_chosen),
            "scoredPassed": len(self.scored_passed),
            "candidates": [
                {
                    "subjectKey": c.subject_key,
                    "wasChosen": c.was_chosen,
                    "baselinePriceSol": c.baseline_price_sol,
                    "baselineClockUs": c.baseline_clock_us,
                    "forwardPriceSol": c.forward_price_sol,
                    "forwardClockUs": c.forward_clock_us,
                    "forwardProvenance": c.forward_provenance,
                    "logReturn": c.log_return,
                    "status": c.status,
                }
                for c in self.candidates
            ],
        }


def measure_event(
    event: SelectionEventV1, index: ForwardPriceIndex, horizon_seconds: int
) -> EventOutcomeV1:
    """Score one event at one horizon. Never raises on absent data."""
    horizon_us = horizon_seconds * 1_000_000
    tolerance_us = int(horizon_us * HORIZON_TOLERANCE_FRACTION)
    target_us = event.decision_wall_us + horizon_us

    outcomes: list[CandidateOutcome] = []
    for candidate, was_chosen in [(c, True) for c in event.chosen] + [
        (c, False) for c in event.passed
    ]:
        baseline = candidate.price_sol
        baseline_clock = candidate.price_observed_wall_us
        if baseline is None or baseline <= 0 or baseline_clock is None:
            outcomes.append(
                CandidateOutcome(
                    subject_key=candidate.subject_key,
                    was_chosen=was_chosen,
                    baseline_price_sol=baseline,
                    baseline_clock_us=baseline_clock,
                    forward_price_sol=None,
                    forward_clock_us=None,
                    forward_provenance=None,
                    log_return=None,
                    status=OUTCOME_ABSENT_NO_BASELINE,
                )
            )
            continue
        forward = index.nearest_after(
            candidate.subject_key, event.decision_wall_us, target_us, tolerance_us
        )
        if forward is None:
            outcomes.append(
                CandidateOutcome(
                    subject_key=candidate.subject_key,
                    was_chosen=was_chosen,
                    baseline_price_sol=baseline,
                    baseline_clock_us=baseline_clock,
                    forward_price_sol=None,
                    forward_clock_us=None,
                    forward_provenance=None,
                    log_return=None,
                    status=OUTCOME_ABSENT_NO_FORWARD,
                )
            )
            continue
        outcomes.append(
            CandidateOutcome(
                subject_key=candidate.subject_key,
                was_chosen=was_chosen,
                baseline_price_sol=baseline,
                baseline_clock_us=baseline_clock,
                forward_price_sol=forward.price_sol,
                forward_clock_us=forward.market_clock_us,
                forward_provenance=forward.provenance,
                log_return=math.log(forward.price_sol / baseline),
                status=OUTCOME_PRESENT,
            )
        )

    frozen = tuple(outcomes)
    scored_chosen = [c for c in frozen if c.scored and c.was_chosen]
    scored_passed = [c for c in frozen if c.scored and not c.was_chosen]
    if not scored_chosen:
        status = (
            OUTCOME_ABSENT_NO_BASELINE
            if all(
                c.status == OUTCOME_ABSENT_NO_BASELINE for c in frozen if c.was_chosen
            )
            else OUTCOME_ABSENT_NO_FORWARD
        )
    elif not scored_passed:
        # The chosen coin has an outcome and nothing to compare it to. The within-scene
        # design is the whole point, so this is absent rather than a one-sided score.
        status = OUTCOME_ABSENT_NO_PASSED
    else:
        status = OUTCOME_PRESENT

    return EventOutcomeV1(
        event_id=event.event_id,
        scene_id=event.scene_id,
        horizon_seconds=horizon_seconds,
        decision_wall_us=event.decision_wall_us,
        status=status,
        candidates=frozen,
    )


def measure_all(
    events: Iterable[SelectionEventV1], index: ForwardPriceIndex, horizons: Sequence[int]
) -> dict[int, list[EventOutcomeV1]]:
    events = list(events)
    return {h: [measure_event(e, index, h) for e in events] for h in horizons}
