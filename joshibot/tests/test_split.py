"""Tests for the walk-forward splitter.

Each pins a leak the published literature actually shipped.
"""

from __future__ import annotations

import pytest

from shitcoims_replay.split import Fold, Sample, SplitError, assert_no_leakage, walk_forward


def _plain(n: int, *, span: int = 0, entity: str | None = None) -> list[Sample]:
    return [
        Sample(at=i, label_end=i + span, entity=entity or f"e{i}")
        for i in range(n)
    ]


def test_train_is_always_strictly_before_test() -> None:
    samples = _plain(40)
    for fold in walk_forward(samples, folds=4):
        assert_no_leakage(samples, fold)
        assert max(samples[i].at for i in fold.train) < min(samples[i].at for i in fold.test)


def test_a_label_reaching_into_the_test_period_is_purged() -> None:
    """The leak that survives a naive temporal split, and the reason purge exists.

    Every sample's feature timestamp precedes the split, so a temporal check passes — but a
    label spanning 100 units has already observed the test period.
    """
    samples = _plain(40, span=100)
    folds = walk_forward(samples, folds=4)
    assert folds
    for fold in folds:
        assert fold.purged_by_label > 0, "a long label window purged nothing"
        assert_no_leakage(samples, fold)


def test_purge_removes_nothing_when_labels_do_not_span() -> None:
    """The counter must distinguish 'purged nothing' from 'purge was never needed'."""
    samples = _plain(40, span=0)
    for fold in walk_forward(samples, folds=4):
        assert fold.purged_by_label == 0


def test_an_entity_never_appears_in_both_train_and_test() -> None:
    """One actor straddling the boundary is worth 39.5 F1 points of illusion."""
    # Ten actors, each appearing repeatedly across the whole time range.
    samples = [Sample(at=i, label_end=i, entity=f"actor{i % 10}") for i in range(100)]
    folds = walk_forward(samples, folds=5)
    assert folds
    for fold in folds:
        assert fold.purged_by_entity > 0, "recurring actors were not grouped out"
        assert_no_leakage(samples, fold)


def test_the_embargo_holds_a_gap_open_before_the_test_window() -> None:
    """Serial correlation at the boundary leaks without any label window crossing it."""
    samples = _plain(40)
    without = walk_forward(samples, folds=4, embargo=0)
    with_gap = walk_forward(samples, folds=4, embargo=5)
    assert all(f.embargoed == 0 for f in without)
    assert all(f.embargoed > 0 for f in with_gap)
    for fold in with_gap:
        test_start = min(samples[i].at for i in fold.test)
        assert all(samples[i].at <= test_start - 5 for i in fold.train)


def test_every_removal_is_counted_so_a_silent_purge_is_visible() -> None:
    """A purge that removes nothing looks exactly like one that was never needed."""
    samples = [Sample(at=i, label_end=i + 50, entity=f"actor{i % 4}") for i in range(60)]
    for fold in walk_forward(samples, folds=3, embargo=2):
        assert fold.removed == fold.purged_by_label + fold.purged_by_entity + fold.embargoed
        assert fold.removed > 0


def test_a_label_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(SplitError):
        Sample(at=10, label_end=9, entity="e")


def test_folds_are_forward_chained_not_shuffled() -> None:
    samples = _plain(40)
    folds = walk_forward(samples, folds=4)
    starts = [min(samples[i].at for i in f.test) for f in folds]
    assert starts == sorted(starts)


def test_a_rolling_window_does_not_grow_with_each_fold() -> None:
    samples = _plain(40)
    expanding = walk_forward(samples, folds=4, expanding=True)
    rolling = walk_forward(samples, folds=4, expanding=False)
    assert len(expanding[-1].train) > len(rolling[-1].train)


def test_the_independent_checker_catches_a_hand_built_leak() -> None:
    """`assert_no_leakage` must be able to fail, or it certifies nothing."""
    samples = _plain(10)
    leaky = Fold(train=(5,), test=(4,), purged_by_label=0, purged_by_entity=0, embargoed=0)
    with pytest.raises(SplitError, match="not before test start"):
        assert_no_leakage(samples, leaky)

    shared = [Sample(at=0, label_end=0, entity="same"), Sample(at=5, label_end=5, entity="same")]
    with pytest.raises(SplitError, match="both train and test"):
        assert_no_leakage(shared, Fold((0,), (1,), 0, 0, 0))


def test_too_few_samples_or_folds_is_refused_rather_than_degenerate() -> None:
    with pytest.raises(SplitError):
        walk_forward(_plain(10), folds=1)
    with pytest.raises(SplitError):
        walk_forward(_plain(3), folds=5)
    assert walk_forward([], folds=3) == []
