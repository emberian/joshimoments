"""Tests for the walk-forward splitter.

Each pins a leak the published literature actually shipped.

Every fixture here must leave a NON-EMPTY training set after purging, and each test asserts
that it did. An adversarial audit found three of these tests running on data where every
fold's train set was empty: ``assert_no_leakage`` iterated zero rows, so "the purge worked"
and "all the training data was deleted" were the same green. The explicit non-emptiness
assertions are what stop that recurring silently, and the splitter now refuses a degenerate
fold outright so a future fixture cannot reintroduce it by accident.
"""

from __future__ import annotations

import pytest

from shitcoims_replay.split import (
    DegenerateFoldError,
    Fold,
    Sample,
    SplitError,
    assert_no_leakage,
    walk_forward,
)


def _plain(n: int, *, span: int = 0, entity: str | None = None) -> list[Sample]:
    return [
        Sample(at=i, label_end=i + span, entity=entity or f"e{i}")
        for i in range(n)
    ]


def test_train_is_always_strictly_before_test() -> None:
    samples = _plain(40)
    for fold in walk_forward(samples, folds=4):
        assert fold.train
        assert_no_leakage(samples, fold)
        assert max(samples[i].at for i in fold.train) < min(samples[i].at for i in fold.test)


def test_a_label_reaching_into_the_test_period_is_purged() -> None:
    """The leak that survives a naive temporal split, and the reason purge exists.

    Every sample's feature timestamp precedes the split, so a temporal check passes — but a
    label spanning 100 units has already observed the test period.

    Odd-indexed samples carry the long window and must go; even-indexed ones carry a point
    label and must SURVIVE. A fixture where the long window is the only kind purges everything
    and certifies nothing, which is the defect this rewrite exists to remove.
    """
    samples = [
        Sample(at=i, label_end=i + (100 if i % 2 else 0), entity=f"e{i}")
        for i in range(40)
    ]
    folds = walk_forward(samples, folds=4)
    assert len(folds) == 3
    for fold in folds:
        test_start = min(samples[i].at for i in fold.test)
        assert fold.train, "every training sample was purged; this fold certifies nothing"
        # Exactly the point-label samples survive, and exactly the spanning ones are counted.
        assert {samples[i].at for i in fold.train} == {i for i in range(test_start) if not i % 2}
        assert fold.purged_by_label == test_start // 2
        assert fold.purged_by_entity == 0
        assert_no_leakage(samples, fold)


def test_a_label_ending_exactly_on_the_test_start_is_purged() -> None:
    """The boundary is closed. A label ending ON the first test timestamp has observed it.

    ``>`` instead of ``>=`` here leaves one leaking sample in the training set per fold, which
    no amount of aggregate counting notices.
    """
    samples = [
        Sample(at=i, label_end=10 if i == 9 else i, entity=f"e{i}")
        for i in range(20)
    ]
    (fold,) = walk_forward(samples, folds=2)
    assert min(samples[i].at for i in fold.test) == 10
    assert fold.purged_by_label == 1
    assert fold.train == tuple(range(9)), "the sample whose label touches the test start stayed"
    assert_no_leakage(samples, fold)


def test_purge_removes_nothing_when_labels_do_not_span() -> None:
    """The counter must distinguish 'purged nothing' from 'purge was never needed'."""
    samples = _plain(40, span=0)
    for fold in walk_forward(samples, folds=4):
        assert fold.train
        assert fold.purged_by_label == 0


def test_an_entity_never_appears_in_both_train_and_test() -> None:
    """One actor straddling the boundary is worth 39.5 F1 points of illusion.

    Five actors recur across the whole time range and must be grouped out; the other half of
    the data belongs to one-off actors and must survive, so the fold is a real split rather
    than a deleted training set.
    """
    samples = [
        Sample(at=i, label_end=i, entity=f"recurring{i % 5}" if i % 2 else f"once{i}")
        for i in range(100)
    ]
    folds = walk_forward(samples, folds=5)
    assert len(folds) == 4
    for fold in folds:
        test_start = min(samples[i].at for i in fold.test)
        assert fold.train, "recurring actors consumed the entire training set"
        assert {samples[i].at for i in fold.train} == {i for i in range(test_start) if not i % 2}
        assert fold.purged_by_entity == test_start // 2
        assert fold.purged_by_label == 0
        assert_no_leakage(samples, fold)


def test_the_embargo_holds_a_gap_open_before_the_test_window() -> None:
    """Serial correlation at the boundary leaks without any label window crossing it."""
    samples = _plain(40)
    without = walk_forward(samples, folds=4, embargo=0)
    with_gap = walk_forward(samples, folds=4, embargo=5)
    assert all(f.embargoed == 0 for f in without)
    assert all(f.embargoed > 0 for f in with_gap)
    for fold in with_gap:
        assert fold.train
        test_start = min(samples[i].at for i in fold.test)
        assert all(samples[i].at <= test_start - 5 for i in fold.train)


def test_the_embargo_boundary_is_inclusive_on_the_training_side() -> None:
    """``>`` vs ``>=`` at the boundary is one sample per fold and no test noticed it.

    The sample exactly ``embargo`` units before the test start is the last one KEPT. Making it
    ``>=`` silently widens every embargo by one unit, which is a real change to the estimator
    that an aggregate "the gap exists" assertion cannot see.
    """
    samples = _plain(40)
    folds = walk_forward(samples, folds=4, embargo=5)
    assert [f.embargoed for f in folds] == [4, 4, 4]
    for fold in folds:
        test_start = min(samples[i].at for i in fold.test)
        train_times = {samples[i].at for i in fold.train}
        assert test_start - 5 in train_times, "the sample on the boundary was dropped"
        assert test_start - 4 not in train_times, "a sample inside the embargo was kept"


def test_every_removal_is_counted_so_a_silent_purge_is_visible() -> None:
    """A purge that removes nothing looks exactly like one that was never needed.

    All three defences fire on this fixture and a quarter of the data still survives, so the
    counts are checked against a training set that actually exists. Roles by index mod 4:
    0 carries a spanning label, 1 shares an entity with the test window, 2 and 3 are clean and
    must survive except where the embargo reaches them.
    """
    samples = [
        Sample(at=i, label_end=i + 50, entity=f"solo{i}") if i % 4 == 0
        else Sample(at=i, label_end=i, entity=f"shared{i % 8}") if i % 4 == 1
        else Sample(at=i, label_end=i, entity=f"solo{i}")
        for i in range(60)
    ]
    folds = walk_forward(samples, folds=3, embargo=3)
    assert [
        (f.purged_by_label, f.purged_by_entity, f.embargoed, len(f.train)) for f in folds
    ] == [(5, 5, 2, 8), (10, 10, 2, 18)]
    for fold in folds:
        assert fold.train, "the fixture removed everything; the counters certify nothing"
        assert fold.removed == fold.purged_by_label + fold.purged_by_entity + fold.embargoed
        assert fold.removed > 0
        assert_no_leakage(samples, fold)


def test_a_label_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(SplitError):
        Sample(at=10, label_end=9, entity="e")


def test_folds_are_forward_chained_not_shuffled() -> None:
    samples = _plain(40)
    folds = walk_forward(samples, folds=4)
    starts = [min(samples[i].at for i in f.test) for f in folds]
    assert starts == sorted(starts)


def test_samples_are_ordered_by_time_not_by_arrival() -> None:
    """A history source paging backwards emits newest-first, and this module is fed by one.

    Splitting on arrival position rather than on ``at`` puts the newest rows in the training
    set and the oldest in test — a perfect time inversion that every downstream check reports
    as clean, because the indices really are disjoint.
    """
    samples = list(reversed(_plain(40)))
    folds = walk_forward(samples, folds=4)
    assert [sorted(samples[i].at for i in f.test) for f in folds] == [
        list(range(10, 20)),
        list(range(20, 30)),
        list(range(30, 40)),
    ]
    for fold in folds:
        assert fold.train
        # Nothing spans and no entity recurs, so ordering alone has to do all the work.
        assert fold.removed == 0
        assert max(samples[i].at for i in fold.train) < min(samples[i].at for i in fold.test)
        assert_no_leakage(samples, fold)


def test_a_rolling_window_does_not_grow_with_each_fold() -> None:
    samples = _plain(40)
    expanding = walk_forward(samples, folds=4, expanding=True)
    rolling = walk_forward(samples, folds=4, expanding=False)
    assert len(expanding[-1].train) > len(rolling[-1].train)


def test_the_independent_checker_catches_a_hand_built_leak() -> None:
    """`assert_no_leakage` must be able to fail, or it certifies nothing.

    All three of its checks are exercised. The LABEL one matters most and was the one nobody
    pinned: deleting it left the verifier green, so the module's own defence against the
    published no-op-purge defect was itself unverified.
    """
    samples = _plain(10)
    leaky = Fold(train=(5,), test=(4,), purged_by_label=0, purged_by_entity=0, embargoed=0)
    with pytest.raises(SplitError, match="not before test start"):
        assert_no_leakage(samples, leaky)

    # Feature timestamp is safely in the past; the LABEL reaches across the boundary.
    spanning = [Sample(at=0, label_end=7, entity="a"), Sample(at=5, label_end=5, entity="b")]
    with pytest.raises(SplitError, match="inside the test period"):
        assert_no_leakage(spanning, Fold((0,), (1,), 0, 0, 0))

    shared = [Sample(at=0, label_end=0, entity="same"), Sample(at=5, label_end=5, entity="same")]
    with pytest.raises(SplitError, match="both train and test"):
        assert_no_leakage(shared, Fold((0,), (1,), 0, 0, 0))


def test_the_checker_refuses_a_fold_with_nothing_in_it() -> None:
    """A leakage check over zero rows raises nothing and means nothing.

    This is the structural fix for the audit's finding: whatever a future fixture does, the
    verifier can no longer be handed an empty fold and answer 'clean'.
    """
    samples = _plain(10)
    with pytest.raises(SplitError, match="no training data"):
        assert_no_leakage(samples, Fold(train=(), test=(5, 6), purged_by_label=5,
                                        purged_by_entity=0, embargoed=0))
    with pytest.raises(SplitError, match="no test data"):
        assert_no_leakage(samples, Fold(train=(0, 1), test=(), purged_by_label=0,
                                        purged_by_entity=0, embargoed=0))


@pytest.mark.parametrize(
    "samples, kwargs",
    [
        pytest.param(
            [Sample(at=i, label_end=i, entity="one") for i in range(40)],
            {"folds": 4},
            id="every sample belongs to one entity",
        ),
        pytest.param(
            [Sample(at=0, label_end=0, entity=f"e{i}") for i in range(40)],
            {"folds": 4},
            id="every sample shares one timestamp",
        ),
        pytest.param(
            _plain(40, span=100),
            {"folds": 4},
            id="the label window is longer than the data",
        ),
        pytest.param(
            _plain(40),
            {"folds": 4, "embargo": 1000},
            id="the embargo is wider than the data",
        ),
    ],
)
def test_a_fold_with_no_training_data_is_refused_rather_than_returned(
    samples: list[Sample], kwargs: dict[str, int]
) -> None:
    """The mirror image of a no-op purge, and just as invisible.

    Each of these consumes every training row. Returned as an ordinary ``Fold(train=())`` the
    result is indistinguishable from a successful purge, and every downstream leakage check
    passes over the empty set.
    """
    with pytest.raises(DegenerateFoldError, match="no training data"):
        walk_forward(samples, **kwargs)


def test_a_degenerate_fold_is_available_on_request_and_says_so() -> None:
    """The escape hatch, for the caller who is measuring the emptiness itself."""
    samples = _plain(40, span=100)
    folds = walk_forward(samples, folds=4, allow_degenerate=True)
    assert folds
    assert all(f.is_degenerate for f in folds)
    assert all(f.train == () for f in folds)
    # Still not certifiable: the verifier refuses rather than reporting a clean fold.
    with pytest.raises(SplitError, match="no training data"):
        assert_no_leakage(samples, folds[0])
    # A healthy fold is not flagged.
    assert not any(f.is_degenerate for f in walk_forward(_plain(40), folds=4))


def test_too_few_samples_or_folds_is_refused_rather_than_degenerate() -> None:
    with pytest.raises(SplitError):
        walk_forward(_plain(10), folds=1)
    with pytest.raises(SplitError):
        walk_forward(_plain(3), folds=5)
    assert walk_forward([], folds=3) == []
