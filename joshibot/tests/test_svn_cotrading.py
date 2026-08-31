"""Falsification suite for signal #1 -- SVN co-trading cluster detection.

Three tests are mandated by the brief and are named so a reader can find them:

* ``test_planted_clusters_are_recovered``
* ``test_independent_wallets_yield_no_validated_edges``
* ``test_fdr_correction_actually_binds``

The rest exist because a suite containing only those three would pass for an estimator that is
wrong in ways this method is specifically known to be wrong: a uniform-marginal null under a
heavy-tailed index, a global ``T`` for short-lived wallets, one test per pair instead of nine,
union-find instead of a real community detector, and a second null compared at matched p rather
than matched density. Every one of those has its own test, and every test was re-run against a
deliberately broken estimator (``studies/falsify_svn.sh``).
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter, defaultdict
from fractions import Fraction

import pytest

from shitcoims_tape.schema import EntityLink
from studies.svn_cotrading import (
    ALPHA,
    OPPOSITE_ACTION,
    SAME_ACTION,
    TEST_TYPES,
    VERDICT_NULL,
    VERDICT_SUGGESTIVE,
    VERDICT_UNRESOLVABLE,
    MatchedDensity,
    Panel,
    Print,
    SvnError,
    TradeState,
    _MapEquation,
    adjusted_rand_index,
    average_precision,
    bh_fdr_log,
    bonferroni_log_threshold,
    curveball,
    feasibility_gate,
    giant_component_share,
    hypergeom_sf_exact,
    infomap_communities,
    log_hypergeom_sf,
    network_from,
    pair_tests,
    panel_from_prints,
    run_study,
    simulate,
    union_find_components,
)

# Fast settings. The estimator is exercised at its real defaults in RESULT_svn_cotrading.md; the
# suite runs the same code paths at a size that keeps the merge gate quick.
DRAWS = 60


def _addresses(count: int, *, seed: int) -> list[str]:
    from solders.pubkey import Pubkey

    rng = random.Random(seed)
    return [str(Pubkey(bytes(rng.randbytes(32)))) for _ in range(count)]


# ---------------------------------------------------------------------------------------------
# The hypergeometric itself
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "successes", "draws", "observed"),
    [
        (50, 10, 12, 5),
        (50, 10, 12, 1),
        (50, 10, 12, 10),
        (300, 40, 35, 12),
        (300, 40, 35, 2),
        (17, 9, 9, 7),
    ],
)
def test_log_hypergeom_sf_matches_the_exact_rational(
    total: int, successes: int, draws: int, observed: int
) -> None:
    """Both tail branches, against exact integer arithmetic. Accuracy here IS the ranking."""
    exact = hypergeom_sf_exact(total=total, successes=successes, draws=draws, observed=observed)
    got = log_hypergeom_sf(total=total, successes=successes, draws=draws, observed=observed)
    assert math.isclose(math.exp(got), float(exact), rel_tol=1e-9)


def test_log_hypergeom_sf_orders_p_values_below_float_underflow() -> None:
    """A p far below 1e-308 must still be ordered, which is why the estimator carries log p.

    Two pairs whose true p-values are 1e-400 and 1e-500 both become exactly 0.0 as floats and
    then compare EQUAL, silently destroying the ranking that matched-density comparison and every
    top-k report depend on.
    """
    small = log_hypergeom_sf(total=4000, successes=300, draws=300, observed=280)
    smaller = log_hypergeom_sf(total=4000, successes=300, draws=300, observed=300)
    assert smaller < small < -800.0
    assert math.exp(small) == 0.0 and math.exp(smaller) == 0.0


def test_zero_overlap_is_certain_and_impossible_overlap_is_refused() -> None:
    assert log_hypergeom_sf(total=100, successes=10, draws=10, observed=0) == 0.0
    assert log_hypergeom_sf(total=100, successes=10, draws=10, observed=11) == -math.inf
    assert hypergeom_sf_exact(total=100, successes=10, draws=10, observed=0) == Fraction(1)


# ---------------------------------------------------------------------------------------------
# Nine typed tests, and a pair-specific T
# ---------------------------------------------------------------------------------------------


def _panel(prints: list[Print], **kwargs: object) -> Panel:
    return panel_from_prints(prints, source="test", **kwargs)  # type: ignore[arg-type]


def test_the_test_family_is_nine_per_pair_not_one() -> None:
    """§4.1: the x9 in the Bonferroni correction comes from a 3-state variable crossed with itself.

    Collapsing to "did both wallets trade this token" understates the correction by 9x AND throws
    away the direction, which is the only thing separating an accumulation ring from two
    strangers who happened to be in the same token.
    """
    assert len(TEST_TYPES) == 9
    assert len(SAME_ACTION) == 3
    assert len(OPPOSITE_ACTION) == 2
    wallets = _addresses(4, seed=11)
    tokens = _addresses(30, seed=12)
    prints = []
    for index, token in enumerate(tokens):
        for wallet in wallets:
            prints.append(Print(wallet=wallet, element=token, is_buy=True, at=float(index)))
    _, family, testable = pair_tests(_panel(prints))
    assert testable == 6
    assert family == 9 * testable


def test_T_is_pair_specific_and_a_global_index_would_inflate_significance() -> None:
    """A short-lived pair is tested against the tokens that existed WHILE BOTH WERE ALIVE.

    §4.1: "Using a global T for a short-lived wallet inflates significance, and short-lived
    wallets are our whole population." The assertion is quantitative: the honest p must be
    strictly LARGER (less significant) than the one a global T would have produced.
    """
    tokens = _addresses(200, seed=21)
    a, b, filler = _addresses(3, seed=22)
    prints: list[Print] = []
    for index, token in enumerate(tokens):
        # Somebody has to make every token exist in the index.
        prints.append(Print(wallet=filler, element=token, is_buy=True, at=float(index)))
    for token in tokens[:10]:
        prints.append(Print(wallet=a, element=token, is_buy=True, at=float(tokens.index(token))))
    for token in tokens[:8]:
        prints.append(Print(wallet=b, element=token, is_buy=True, at=float(tokens.index(token))))
    tests, _, _ = pair_tests(_panel(prints))
    pair = [
        t
        for t in tests
        if {t.left, t.right} == {i for i, w in enumerate(sorted({a, b, filler})) if w in {a, b}}
    ]
    assert pair, "the two short-lived wallets must produce at least one typed test"
    windowed = pair[0]
    assert windowed.total <= 12, "T must be the pair's own window, not the 200-token universe"
    global_p = log_hypergeom_sf(
        total=len(tokens),
        successes=windowed.left_marginal,
        draws=windowed.right_marginal,
        observed=windowed.observed,
    )
    assert windowed.log_p > global_p + 1.0, (
        "a global T makes the same overlap look far more significant than it is"
    )


def test_a_pair_with_no_temporal_overlap_is_never_tested() -> None:
    tokens = _addresses(40, seed=31)
    a, b = _addresses(2, seed=32)
    prints = [
        Print(wallet=a, element=token, is_buy=True, at=float(i)) for i, token in enumerate(tokens[:20])
    ]
    prints += [
        Print(wallet=b, element=token, is_buy=True, at=float(100 + i))
        for i, token in enumerate(tokens[:20])
    ]
    tests, family, testable = pair_tests(_panel(prints))
    assert tests == [] and testable == 0 and family == 0


# ---------------------------------------------------------------------------------------------
# Multiplicity
# ---------------------------------------------------------------------------------------------


def test_bonferroni_threshold_is_alpha_over_the_performed_family() -> None:
    got = bonferroni_log_threshold(alpha=0.01, family_size=9 * 500_000)
    assert math.isclose(math.exp(got), 0.01 / (9 * 500_000), rel_tol=1e-12)
    with pytest.raises(SvnError):
        bonferroni_log_threshold(alpha=0.01, family_size=0)


def test_bh_fdr_matches_a_hand_computation() -> None:
    """BH at q=0.05 over m=10: p_(k) <= 0.05k/10. Hand-checked, not eyeballed."""
    p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    flags, log_threshold = bh_fdr_log(
        [math.log(p) for p in p_values], q=0.05, family_size=len(p_values)
    )
    # Largest k with p_(k) <= 0.005k is k=5 (0.042 <= 0.025 is false; 0.041 <= 0.02 false;
    # 0.039 <= 0.015 false; 0.008 <= 0.01 true at k=2). So the cut is k=2.
    assert flags == [True, True, False, False, False, False, False, False, False, False]
    assert math.isclose(math.exp(log_threshold), 0.05 * 2 / 10, rel_tol=1e-12)


def test_fdr_correction_actually_binds() -> None:
    """MANDATED TEST. BH must sit strictly between no correction and Bonferroni, on real output.

    Two things are pinned. First the ordering: an uncorrected alpha rejects strictly more than BH,
    and BH rejects at least as many as Bonferroni. Second -- and this is the one that has teeth --
    the DENOMINATOR: BH is corrected over every test performed, not merely over the pairs that
    happened to co-occur and get enumerated. Shrinking the family to the enumerated subset makes
    the correction weaker and the rejection set strictly larger, which is exactly the silent
    understatement the ``family_size`` argument exists to prevent.
    """
    world = simulate(
        seed=5, n_wallets=140, n_tokens=280, n_clusters=5, cluster_size=7, popularity_exponent=1.4
    )
    tests, family, _ = pair_tests(world.panel)
    log_p = [t.log_p for t in tests]
    assert family > len(tests), "most pairs never co-occur, so the family exceeds the enumeration"

    bonferroni = bonferroni_log_threshold(alpha=ALPHA, family_size=family)
    n_bonferroni = sum(1 for value in log_p if value <= bonferroni)
    n_uncorrected = sum(1 for value in log_p if value <= math.log(ALPHA))
    bh_flags, _ = bh_fdr_log(log_p, q=0.05, family_size=family)
    n_bh = sum(bh_flags)

    assert n_bonferroni >= 1, "the fixture must produce something to correct"
    assert n_uncorrected > n_bh >= n_bonferroni

    understated, _ = bh_fdr_log(log_p, q=0.05, family_size=len(tests))
    assert sum(understated) > n_bh, (
        "correcting over the enumerated tests alone is a weaker correction and must be visible"
    )
    with pytest.raises(SvnError):
        bh_fdr_log(log_p, q=0.05, family_size=len(tests) - 1)


# ---------------------------------------------------------------------------------------------
# Recovery -- the mandated positive control
# ---------------------------------------------------------------------------------------------


def test_planted_clusters_are_recovered() -> None:
    """MANDATED TEST. Rings planted in a heavy-tailed world come back out, and only they do."""
    world = simulate(
        seed=20260813,
        n_wallets=150,
        n_tokens=300,
        n_clusters=5,
        cluster_size=8,
        popularity_exponent=1.1,
    )
    result = run_study(world.panel, seed=20260813, randomisations=DRAWS, planted=world.planted)
    assert result.verdict == VERDICT_SUGGESTIVE
    assert result.bonferroni is not None and result.bonferroni.n_same_action_edges >= 10
    assert result.robust is not None and result.robust.n_clusters >= 2

    wallets = world.panel.wallets
    hyper = next(m for m in result.recovery if m.method.startswith("svn-hypergeometric"))
    assert hyper.precision_at_k == 1.0, "every validated edge must join two ring-mates"
    assert hyper.average_precision > 0.8
    assert hyper.base_rate < 0.05, "the pair-classification problem must stay a rare-event one"

    # Every emitted entity groups wallets from exactly one planted ring, and never merges two.
    by_entity: dict[str, set[int]] = defaultdict(set)
    for link in result.entity_links:
        assert isinstance(link, EntityLink)
        assert 0.0 <= link.confidence <= 1.0
        assert link.method == "svn_cotrading"
        by_entity[link.entity_id].add(world.planted[link.wallet])
    assert by_entity, "a SUGGESTIVE verdict must emit entity links"
    assert all(len(rings) == 1 for rings in by_entity.values())
    assert all(link.wallet in wallets for link in result.entity_links)


def test_recovery_is_reported_against_a_popularity_baseline_first() -> None:
    """§3 rule 4. The baseline is not decoration: on this problem it ranks at least as well.

    The SVN's contribution is a THRESHOLD -- a validated set with a stated false-discovery
    control -- not a better ordering. A study that reported only the SVN number would be claiming
    an improvement it does not have.
    """
    world = simulate(
        seed=3, n_wallets=140, n_tokens=280, n_clusters=5, cluster_size=8, popularity_exponent=1.1
    )
    result = run_study(world.panel, seed=3, randomisations=DRAWS, planted=world.planted)
    methods = [m.method for m in result.recovery]
    assert methods[0].startswith("popularity-baseline")
    baseline = result.recovery[0]
    assert baseline.average_precision > 0.5


# ---------------------------------------------------------------------------------------------
# False positives -- the mandated negative control
# ---------------------------------------------------------------------------------------------


def test_independent_wallets_yield_no_validated_edges() -> None:
    """MANDATED TEST. Zero planted coordination must give zero validated edges and a NULL verdict."""
    for seed in (1, 2, 3, 4, 5):
        world = simulate(
            seed=seed,
            n_wallets=140,
            n_tokens=280,
            n_clusters=0,
            cluster_size=0,
            popularity_exponent=0.0,
        )
        assert world.planted == {}
        tests, family, _ = pair_tests(world.panel)
        threshold = bonferroni_log_threshold(alpha=ALPHA, family_size=family)
        validated = [t for t in tests if t.log_p <= threshold and t.type_key in SAME_ACTION]
        assert validated == [], f"seed {seed} produced a false positive: {validated}"

    world = simulate(
        seed=2, n_wallets=140, n_tokens=280, n_clusters=0, cluster_size=0, popularity_exponent=0.0
    )
    result = run_study(world.panel, seed=2, randomisations=DRAWS, planted=world.planted)
    assert result.verdict == VERDICT_NULL
    assert result.entity_links == ()


def test_heavy_tailed_token_popularity_inflates_the_hypergeometric_null() -> None:
    """§4.1's blocking risk, measured rather than assumed.

    The hypergeometric assumes roughly uniform marginals across the index. Memecoin token
    popularity is heavy-tailed, so under it "both wallets bought the token everybody bought" reads
    as coordination. With ZERO planted rings the false-discovery count must rise with the tail
    exponent -- if it does not, the null is not being stressed and the degree-preserving comparison
    below is testing nothing.
    """
    counts: dict[float, int] = {}
    for exponent in (0.0, 2.2):
        total = 0
        for seed in (1, 2, 3):
            world = simulate(
                seed=seed,
                n_wallets=150,
                n_tokens=300,
                n_clusters=0,
                cluster_size=0,
                popularity_exponent=exponent,
                activity_low=20,
                activity_high=60,
            )
            tests, family, _ = pair_tests(world.panel)
            flags, _ = bh_fdr_log([t.log_p for t in tests], q=0.05, family_size=family)
            total += len(
                {t.key for t, flag in zip(tests, flags, strict=True) if flag and t.type_key in SAME_ACTION}
            )
        counts[exponent] = total
    assert counts[0.0] == 0
    assert counts[2.2] > 20, (
        f"heavy-tailed popularity produced {counts[2.2]} false BH-validated edges against "
        f"{counts[0.0]} under a uniform index"
    )


def test_the_degree_preserving_null_removes_the_popularity_artefact() -> None:
    """The second null must delete the edges the first one manufactured from popularity alone."""
    world = simulate(
        seed=1,
        n_wallets=150,
        n_tokens=300,
        n_clusters=0,
        cluster_size=0,
        popularity_exponent=2.2,
        activity_low=20,
        activity_high=60,
    )
    result = run_study(world.panel, seed=1, randomisations=DRAWS, planted=world.planted)
    assert result.bonferroni is not None and result.bonferroni.n_same_action_edges > 0, (
        "the fixture must produce hypergeometric false positives, else nothing is being tested"
    )
    assert result.robust is not None and result.robust.n_same_action_edges == 0
    assert result.verdict == VERDICT_NULL
    assert "degree-preserving" in result.reason
    assert result.entity_links == ()


# ---------------------------------------------------------------------------------------------
# Cimini: matched density, never matched p
# ---------------------------------------------------------------------------------------------


def test_nulls_are_compared_at_matched_density_not_matched_p() -> None:
    """Cimini et al. 2022: link density varies by an order of magnitude across nulls at one p.

    The comparison set drawn from the degree-preserving null has EXACTLY as many edges as the
    hypergeometric's Bonferroni set, regardless of how many that null would validate at its own
    (unusable) threshold. The gap between those two counts is the phenomenon.
    """
    world = simulate(
        seed=1,
        n_wallets=150,
        n_tokens=300,
        n_clusters=0,
        cluster_size=0,
        popularity_exponent=2.2,
        activity_low=20,
        activity_high=60,
    )
    result = run_study(world.panel, seed=1, randomisations=DRAWS, planted=world.planted)
    matched = result.matched
    assert isinstance(matched, MatchedDensity)
    assert matched.density == matched.hyper_edges_at_own_threshold
    assert matched.hyper_only == matched.degree_only, "matched density means equal-sized sets"
    assert matched.degree_edges_at_p_floor_uncorrected > 20 * max(matched.density, 1), (
        "the two nulls must differ by an order of magnitude at their own thresholds, which is "
        "precisely why a p-matched comparison would be meaningless"
    )
    assert matched.degree_p_floor == pytest.approx(1.0 / (1.0 + DRAWS))


def test_the_degree_preserving_p_floor_cannot_reach_the_bonferroni_threshold() -> None:
    """Not a nuisance: it is why matched density is the only comparison that exists here.

    The empirical p of a randomisation null cannot go below 1/(B+1). At 150 wallets the Bonferroni
    threshold is already ~1e-7, so B would have to exceed ten million randomisations per study.
    """
    world = simulate(seed=9, n_wallets=150, n_tokens=300, n_clusters=0, cluster_size=0)
    _, family, _ = pair_tests(world.panel)
    threshold = math.exp(bonferroni_log_threshold(alpha=ALPHA, family_size=family))
    required = 1.0 / threshold - 1.0
    assert required > 1e6


# ---------------------------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------------------------


def test_union_find_blobs_where_the_map_equation_separates() -> None:
    """§4.1: connected components put 99.6% of the FDR network into one cluster.

    Two cliques joined by a single link is the smallest instance of that failure. Union-find must
    return one component covering everything; the map equation must return two modules.
    """
    edges: dict[tuple[int, int], int] = {}
    for left, right in itertools.combinations(range(5), 2):
        edges[(left, right)] = 3
    for left, right in itertools.combinations(range(5, 10), 2):
        edges[(left, right)] = 3
    edges[(4, 5)] = 1
    assert giant_component_share(edges) == 1.0
    assert len(set(union_find_components(edges).values())) == 1
    communities = infomap_communities(edges)
    assert len(set(communities.values())) == 2
    assert {communities[node] for node in range(5)} != {communities[node] for node in range(5, 10)}


def test_map_equation_code_length_strictly_decreases() -> None:
    edges: dict[tuple[int, int], int] = {}
    for left, right in itertools.combinations(range(6), 2):
        edges[(left, right)] = 2
    for left, right in itertools.combinations(range(6, 12), 2):
        edges[(left, right)] = 2
    edges[(0, 6)] = 1
    engine = _MapEquation(edges)
    before = engine.code_length()
    engine.optimise()
    assert engine.code_length() < before - 1e-9


def test_clustering_is_reported_with_the_union_find_pathology_next_to_it() -> None:
    world = simulate(
        seed=20260813, n_wallets=150, n_tokens=300, n_clusters=5, cluster_size=8
    )
    result = run_study(world.panel, seed=20260813, randomisations=DRAWS, planted=world.planted)
    assert result.bonferroni is not None
    assert 0.0 <= result.bonferroni.giant_component_share <= 1.0
    assert result.bonferroni.union_find_components >= 1


def test_adjusted_rand_index_counts_unclustered_nodes_as_singletons() -> None:
    """A null model that validates nothing must not score as agreeing perfectly with one that did."""
    left = {0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1}
    assert adjusted_rand_index(left, left) == pytest.approx(1.0)
    assert adjusted_rand_index(left, {}) < 0.2


# ---------------------------------------------------------------------------------------------
# Opposite-action links: kept, not deleted
# ---------------------------------------------------------------------------------------------


def test_opposite_action_links_are_reported_rather_than_silently_dropped() -> None:
    """§4.1: the paper deletes them; for us they are the wash-trading signature.

    They must be excluded from the CLUSTERING weight (so a wash pair does not join an
    accumulation ring) and still present in the reported network.
    """
    from studies.svn_cotrading import PairTest

    tests = [
        PairTest(0, 1, TradeState.BUY, TradeState.SELL, 100, 10, 10, 9, -30.0),
        PairTest(0, 1, TradeState.BUY, TradeState.BUY, 100, 10, 10, 1, -0.1),
        PairTest(2, 3, TradeState.BUY, TradeState.BUY, 100, 10, 10, 9, -30.0),
    ]
    network = network_from(tests, [True, False, True], name="fixture")
    assert set(network.edges) == {(2, 3)}
    assert set(network.opposite_edges) == {(0, 1)}
    assert network.n_validated_tests == 2
    assert (0, 1) not in infomap_communities(network.edges)


# ---------------------------------------------------------------------------------------------
# Feasibility gate
# ---------------------------------------------------------------------------------------------


def test_feasibility_gate_refuses_the_scope_program_md_4_1_refutes() -> None:
    """The exact arithmetic in §4.1, reproduced as a runnable gate.

    At 50,000 wallets Bonferroni over nine tests per pair is 8.9e-13, while the smallest p a
    5-of-300 pair can ever attain is 5.1e-11. No such pair can validate at that scope regardless
    of the data. The gate must say so BEFORE anything is collected.
    """
    huge = feasibility_gate(n_wallets=50_000, n_index_elements=300, tokens_per_wallet=5)
    assert not huge.feasible
    assert math.isclose(
        math.exp(huge.log_bonferroni_threshold), 0.01 / (9 * 50_000 * 49_999 / 2), rel_tol=1e-9
    )
    assert math.isclose(math.exp(huge.log_min_attainable_p), 1.0 / math.comb(300, 5), rel_tol=1e-9)

    modest = feasibility_gate(n_wallets=300, n_index_elements=300, tokens_per_wallet=8)
    assert modest.feasible
    with pytest.raises(SvnError):
        feasibility_gate(n_wallets=1, n_index_elements=300, tokens_per_wallet=5)


def test_max_feasible_wallets_inverts_the_gate_into_a_collection_rule() -> None:
    """The gate is only useful if it can be inverted: how many wallets may the universe hold?

    The answer is dominated by the ACTIVITY FLOOR, not by anything about the data. Admitting
    wallets that touched two tokens caps the universe at ten; requiring eight lifts it past a
    million. That is the operational output of the whole feasibility argument.
    """
    from studies.svn_cotrading import UNBOUNDED_WALLETS, max_feasible_wallets

    ceilings = {
        floor: max_feasible_wallets(n_index_elements=300, tokens_per_wallet=floor)
        for floor in (2, 3, 5, 8)
    }
    assert ceilings[2] < ceilings[3] < ceilings[5] < ceilings[8]
    assert ceilings[2] < 50 and ceilings[5] > 1000
    for floor, ceiling in ceilings.items():
        assert feasibility_gate(
            n_wallets=ceiling, n_index_elements=300, tokens_per_wallet=floor
        ).feasible
        if ceiling < UNBOUNDED_WALLETS:
            assert not feasibility_gate(
                n_wallets=ceiling + 1, n_index_elements=300, tokens_per_wallet=floor
            ).feasible
    # §4.1's own example: 50k wallets on 5-of-300 is refused, and raising the floor fixes it.
    assert ceilings[5] < 50_000
    assert max_feasible_wallets(n_index_elements=300, tokens_per_wallet=8) > 50_000


def test_an_infeasible_scope_returns_unresolvable_rather_than_a_number() -> None:
    tokens = _addresses(6, seed=41)
    wallets = _addresses(30, seed=42)
    prints = [
        Print(wallet=wallet, element=token, is_buy=True, at=float(index))
        for index, token in enumerate(tokens)
        for wallet in wallets
    ]
    result = run_study(_panel(prints), seed=1, randomisations=DRAWS, min_wallets=5)
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert "feasibility gate fails" in result.reason
    assert result.entity_links == ()


# ---------------------------------------------------------------------------------------------
# Refusals on real-shaped data
# ---------------------------------------------------------------------------------------------


def test_a_two_wallet_panel_is_unresolvable_not_a_number() -> None:
    """The live intelligence store holds exactly two wallets. It must not produce a finding."""
    tokens = _addresses(40, seed=51)
    a, b = _addresses(2, seed=52)
    prints = [
        Print(wallet=wallet, element=token, is_buy=True, at=float(index))
        for index, token in enumerate(tokens)
        for wallet in (a, b)
    ]
    result = run_study(_panel(prints), seed=1, randomisations=DRAWS)
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert "below the floor" in result.reason
    assert result.n_wallets == 2
    assert result.entity_links == ()


def test_a_watchlist_panel_can_never_report_suggestive() -> None:
    """Wallets we hand-picked are not a sample. A cluster over them measures our own selection."""
    world = simulate(
        seed=20260813, n_wallets=150, n_tokens=300, n_clusters=5, cluster_size=8
    )
    watchlisted = Panel(
        states=world.panel.states,
        element_time=world.panel.element_time,
        wallet_span=world.panel.wallet_span,
        source=world.panel.source,
        n_prints=world.panel.n_prints,
        wallets_are_a_watchlist=True,
    )
    result = run_study(watchlisted, seed=20260813, randomisations=DRAWS)
    assert result.verdict == VERDICT_UNRESOLVABLE
    assert "watchlist" in result.reason
    assert any("watchlist" in note for note in result.notes)


def test_entity_links_satisfy_the_frozen_tape_contract() -> None:
    world = simulate(
        seed=20260813, n_wallets=150, n_tokens=300, n_clusters=5, cluster_size=8
    )
    result = run_study(world.panel, seed=20260813, randomisations=DRAWS, planted=world.planted)
    assert result.entity_links
    for link in result.entity_links:
        payload = link.to_json()
        assert set(payload) == {"wallet", "entity_id", "method", "confidence", "evidence"}
        assert 0.0 <= payload["confidence"] <= 1.0
        assert payload["evidence"], "a merge with no evidence is a merge nobody can audit"
        EntityLink(
            wallet=payload["wallet"],
            entity_id=payload["entity_id"],
            method=payload["method"],
            confidence=payload["confidence"],
            evidence=tuple(payload["evidence"]),
        )


# ---------------------------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------------------------


def test_curveball_preserves_wallet_degree_and_token_degree_exactly() -> None:
    """Both margins. Preserving only the wallet side would leave the popularity artefact intact."""
    rng = random.Random(7)
    rows = [
        frozenset(rng.sample(range(40), rng.randint(3, 12))) for _ in range(30)
    ]
    shuffled = curveball(rows, rng=rng, swaps=5000)
    assert [len(row) for row in rows] == [len(row) for row in shuffled]
    before = Counter(item for row in rows for item in row)
    after = Counter(item for row in shuffled for item in row)
    assert before == after
    assert [set(row) for row in rows] != shuffled, "a null that changes nothing is not a null"


def test_average_precision_matches_a_hand_computation() -> None:
    scored = [(0.9, True), (0.8, False), (0.7, True), (0.6, False)]
    assert average_precision(scored, n_positive_total=2) == pytest.approx((1.0 + 2 / 3) / 2)
    # A positive that never enters the ranking still counts against recall.
    assert average_precision(scored, n_positive_total=4) == pytest.approx((1.0 + 2 / 3) / 4)


def test_the_study_is_deterministic_given_a_seed() -> None:
    world = simulate(seed=101, n_wallets=120, n_tokens=240, n_clusters=4, cluster_size=7)
    first = run_study(world.panel, seed=101, randomisations=DRAWS, planted=world.planted)
    second = run_study(world.panel, seed=101, randomisations=DRAWS, planted=world.planted)
    assert first.to_json() == second.to_json()


def test_states_are_derived_from_the_actual_sides() -> None:
    token, other = _addresses(2, seed=61)
    wallet, seller, tripper = _addresses(3, seed=62)
    panel = _panel(
        [
            Print(wallet=wallet, element=token, is_buy=True, at=1.0),
            Print(wallet=seller, element=token, is_buy=False, at=2.0),
            Print(wallet=tripper, element=token, is_buy=True, at=3.0),
            Print(wallet=tripper, element=token, is_buy=False, at=4.0),
            Print(wallet=wallet, element=other, is_buy=True, at=5.0),
        ]
    )
    assert panel.states[wallet][token] is TradeState.BUY
    assert panel.states[seller][token] is TradeState.SELL
    assert panel.states[tripper][token] is TradeState.ROUND_TRIP
