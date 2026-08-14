"""Purged, embargoed, entity-grouped walk-forward splitting.

The single most consequential piece of methodology in this domain, and the one the published
literature most reliably gets wrong. Measured elsewhere in this program: the same model family
scored recall 0.778 under a random split and 0.234 under a temporal one — 54 points, purely
from protocol — and a GNN benchmark moved 39.5 F1 points between transductive and inductive
evaluation. One published "purged" cross-validation had a purge parameter that was a literal
no-op, so callers believed leakage had been handled while nothing was removed.

Three defences, and all three are needed because each catches a different leak:

**Temporal.** Test always follows train. Cheap, obvious, and insufficient on its own.

**Purge.** Financial labels span an interval — "did this bag fall 30% in the next hour" is a
statement about the future of its own sample. A training sample whose label window reaches
into the test period has already seen the test period, and the fact that its *feature*
timestamp precedes the split does not save it. This is the leak that survives a naive temporal
split, which is why a temporal split alone is not enough.

**Entity grouping.** One actor must never straddle the boundary. Wallets resolve to entities
and scam campaigns share deployers, so a model can memorise an actor in training and be scored
on the same actor in test. This is a prerequisite rather than a refinement: it is why entity
resolution is signal #2 and why nothing downstream splits correctly until it exists.

Every fold reports how many samples each defence removed. A purge that silently removes
nothing looks identical to a purge that was never needed, and telling those apart afterwards
is impossible.

**And a fold with no training data left is refused, not returned.** The mirror image of a
no-op purge is a total one: all-one-entity data, all-identical timestamps, a label window
longer than the dataset, or an embargo wider than it, each consume every training row and
leave ``Fold(train=())``. Returned silently that is indistinguishable from a successful
purge — an adversarial audit found three of this module's own tests running on exactly that
fixture, where the independent verifier iterated zero rows and certified nothing while
staying green. ``walk_forward`` therefore raises :class:`DegenerateFoldError` by default and
names which defence consumed the fold, which is what the counters are for; a caller who
genuinely wants the empty folds asks for them with ``allow_degenerate=True``. For the same
reason ``assert_no_leakage`` refuses an empty train or test set instead of vacuously passing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class SplitError(ValueError):
    """The split contract was violated. Always fail closed."""


class DegenerateFoldError(SplitError):
    """A fold came back with no training data, so it is not a split at all.

    Separate from :class:`SplitError` only so a caller can distinguish "your data cannot be
    split this way" from "you asked for something incoherent". Both fail closed.
    """


@dataclass(frozen=True, slots=True)
class Sample:
    """One observation, with the interval its LABEL depends on.

    ``label_end`` is not decoration. If it is left equal to ``at`` for a label that actually
    looks forward, purging silently becomes a no-op — the exact defect published as a working
    purge. Constructing a Sample therefore forces the question.
    """

    at: int
    label_end: int
    entity: str

    def __post_init__(self) -> None:
        if self.label_end < self.at:
            raise SplitError("label_end precedes the sample; a label cannot end before it starts")


@dataclass(frozen=True, slots=True)
class Fold:
    """One train/test division, with an audit of what each defence removed."""

    train: tuple[int, ...]
    test: tuple[int, ...]
    purged_by_label: int
    purged_by_entity: int
    embargoed: int

    @property
    def removed(self) -> int:
        return self.purged_by_label + self.purged_by_entity + self.embargoed

    @property
    def is_degenerate(self) -> bool:
        """No training data survived. Nothing can be fitted, and nothing can be certified.

        Named rather than left as an incidental ``not fold.train`` because the failure it
        describes is silent: every downstream check over an empty train set passes.
        """
        return not self.train


def walk_forward(
    samples: Sequence[Sample],
    *,
    folds: int,
    embargo: int = 0,
    expanding: bool = True,
    allow_degenerate: bool = False,
) -> list[Fold]:
    """Split ``samples`` into ``folds`` forward-chained train/test divisions.

    ``embargo`` is a gap, in the same units as ``at``, held empty immediately before each test
    window. Purge removes leakage that is *visible* in the label interval; the embargo covers
    serial correlation that is not — an autocorrelated feature right at the boundary leaks
    without any label window reaching across it. The boundary is inclusive on the training
    side: a sample exactly ``embargo`` units before the test start is the last one kept, so
    ``embargo=0`` is exactly "no embargo" rather than "drop the sample on the line".

    ``expanding`` grows the training set each fold (the honest default: it is what a live desk
    would actually have). Set it False for a rolling window when non-stationarity dominates.

    ``allow_degenerate`` is the escape hatch for folds the defences emptied completely. The
    default refuses them, because a returned ``Fold(train=())`` is the failure this module
    exists to prevent wearing the costume of the success: every leakage check over an empty
    training set passes, so "the purge worked" and "the training data was deleted" produce
    identical green. Pass True only when the emptiness is itself the measurement.

    Samples are ordered by ``at`` rather than by position, so a tape paged newest-first — the
    real behaviour of the history sources feeding this — does not silently invert time.
    """
    if folds < 2:
        raise SplitError("walk-forward needs at least 2 folds")
    if embargo < 0:
        raise SplitError("embargo must not be negative")
    if not samples:
        return []

    order = sorted(range(len(samples)), key=lambda i: (samples[i].at, i))
    n = len(order)
    if n < folds:
        raise SplitError(f"{n} samples cannot be split into {folds} folds")

    block = n // folds
    out: list[Fold] = []

    for fold in range(1, folds):
        test_positions = (
            order[fold * block : (fold + 1) * block]
            if fold < folds - 1
            else order[fold * block :]
        )
        if not test_positions:
            continue
        train_positions = order[: fold * block]
        if not expanding:
            train_positions = train_positions[-block:]

        test_start = samples[test_positions[0]].at
        test_entities = {samples[i].entity for i in test_positions}

        kept: list[int] = []
        purged_label = purged_entity = embargoed = 0
        for index in train_positions:
            sample = samples[index]
            # Order matters only for the audit, not the outcome: a sample can violate more
            # than one rule, and attributing it to the first one it breaks keeps the counts
            # interpretable rather than double-counted.
            if sample.label_end >= test_start:
                purged_label += 1
                continue
            if embargo and sample.at > test_start - embargo:
                embargoed += 1
                continue
            if sample.entity in test_entities:
                purged_entity += 1
                continue
            kept.append(index)

        out.append(
            Fold(
                train=tuple(kept),
                test=tuple(test_positions),
                purged_by_label=purged_label,
                purged_by_entity=purged_entity,
                embargoed=embargoed,
            )
        )

    if not allow_degenerate:
        empty = [i for i, produced in enumerate(out) if produced.is_degenerate]
        if empty:
            first = out[empty[0]]
            raise DegenerateFoldError(
                f"folds {empty} have no training data left after purging "
                f"(fold {empty[0]}: {first.purged_by_label} purged by label, "
                f"{first.purged_by_entity} by entity, {first.embargoed} embargoed). "
                "An empty training set cannot be fitted and cannot be checked for leakage, "
                "so it is refused rather than returned; pass allow_degenerate=True if the "
                "emptiness is the measurement you want."
            )
    return out


def assert_no_leakage(samples: Sequence[Sample], fold: Fold) -> None:
    """Independently re-check a fold. Cheap, and it is the check nobody runs.

    A splitter is exactly the kind of code that looks right and silently does nothing, so the
    guarantee is verified against the produced indices rather than trusted from the producer.

    An empty train or test set is refused rather than passed. A loop over zero rows raises
    nothing, so a verifier that accepted one would report "no leakage" about a fold that
    contains no data — which is how three of this module's own tests came to certify nothing
    while staying green.
    """
    if not fold.test:
        raise SplitError("fold has no test data; there is nothing to certify")
    if not fold.train:
        raise SplitError(
            "fold has no training data; a leakage check over zero rows certifies nothing"
        )
    test_start = min(samples[i].at for i in fold.test)
    test_entities = {samples[i].entity for i in fold.test}
    for index in fold.train:
        sample = samples[index]
        if sample.at >= test_start:
            raise SplitError(f"train sample at {sample.at} is not before test start {test_start}")
        if sample.label_end >= test_start:
            raise SplitError(
                f"train label ends at {sample.label_end}, inside the test period from {test_start}"
            )
        if sample.entity in test_entities:
            raise SplitError(f"entity {sample.entity} appears in both train and test")
