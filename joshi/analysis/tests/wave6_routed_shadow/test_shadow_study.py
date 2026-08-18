from __future__ import annotations

import pytest

from joshi_analysis.wave6_routed_shadow import (
    ArbitrageOrdering,
    ArbitrageSpec,
    AssetInventory,
    ConstantProductEdge,
    Coverage,
    Direction,
    DlmmBinEdge,
    DlmmFeePolicy,
    ExternalStateTreatment,
    FixedBin,
    FlowOrigin,
    HouseholdSelfRouteCounterleg,
    JupiterWitness,
    QuoteIntent,
    RouteDecisionStatus,
    ShadowScenario,
    SourceCut,
    canonical_bytes,
    run_shadow_study,
)
from joshi_analysis.wave6_routed_shadow.arithmetic import Q64
from joshi_analysis.wave6_routed_shadow.contracts import ExactQuote, QuoteRefusal

SOURCE_CUT = SourceCut("cut:101", 101, "profile:v1", "topology:1")


def _witness(
    sequence: int,
    *,
    complete: bool = True,
    source_cut: SourceCut = SOURCE_CUT,
) -> JupiterWitness:
    return JupiterWitness(
        witness_id=f"jupiter:{sequence}",
        slot=source_cut.slot,
        source_cut=source_cut,
        candidate_venue_ids=("control",),
        routed_venue_ids=("control",),
        universe_complete=complete,
        coverage=Coverage.OBSERVED_COMPLETE if complete else Coverage.OBSERVED_PARTIAL,
    )


def _ghost(
    y_atoms: int = 500,
    fee_rate: int = 0,
    *,
    source_cut: SourceCut = SOURCE_CUT,
) -> DlmmBinEdge:
    return DlmmBinEdge(
        edge_id="ghost",
        schedule_id="schedule:one",
        state_id="ghost-state",
        asset_x="X",
        asset_y="Y",
        active_bin_id=0,
        fee_policy=DlmmFeePolicy(fee_rate, 0),
        bins=(FixedBin(0, Q64, 0, y_atoms),),
        source_cut=source_cut,
    )


def _control(*, source_cut: SourceCut = SOURCE_CUT) -> ConstantProductEdge:
    return ConstantProductEdge("control", "control-state", "X", "Y", 1000, 1000, source_cut)


def _intent(
    sequence: int,
    *,
    origin: FlowOrigin = FlowOrigin.EXTERNAL,
    input_atoms: int = 100,
    source_cut: SourceCut = SOURCE_CUT,
) -> QuoteIntent:
    return QuoteIntent(
        intent_id=f"intent:{sequence}",
        sequence=sequence,
        direction=Direction.X_TO_Y,
        input_atoms=input_atoms,
        origin=origin,
        jupiter=_witness(sequence, source_cut=source_cut),
    )


def test_would_quote_candidate_routed_selection_and_fill_remain_distinct() -> None:
    ineligible = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "not-candidate", False, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    event = ineligible.events[0]
    assert isinstance(event.ghost_would_quote.outcome, ExactQuote)
    assert event.intent.jupiter.candidate_venue_ids == ("control",)
    assert event.intent.jupiter.routed_venue_ids == ("control",)
    assert event.decision.selected_venue_id == "control"
    assert not event.decision.ghost_selected
    assert event.modeled_transfer is None
    assert event.intent.landed_fill is None

    eligible = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "assumed-candidate", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    event = eligible.events[0]
    assert event.venue_quotes[0].source_cut == SOURCE_CUT
    assert event.venue_quotes[0].slot == SOURCE_CUT.slot
    assert event.decision.baseline_output_atoms == 90
    assert event.decision.selected_output_atoms == 100
    assert event.decision.ghost_selected
    assert event.modeled_transfer is not None
    assert event.intent.landed_fill is None
    assert event.modeled_transfer.post_state_digest


def test_reference_state_keeps_its_own_source_cut_and_cannot_be_slot_stamped() -> None:
    stale_cut = SourceCut("cut:99", 99, "profile:v1", "topology:1")
    run = run_shadow_study(
        ghost=_ghost(),
        baselines=(
            ConstantProductEdge("control", "control:stale", "X", "Y", 1_000, 1_000, stale_cut),
        ),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "incompatible-cut", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    event = run.events[0]
    assert event.venue_quotes[0].source_cut == stale_cut
    assert event.venue_quotes[0].slot == 99
    assert event.intent.jupiter.slot == 101
    assert event.decision.status is RouteDecisionStatus.UNKNOWN_INCOMPATIBLE_SOURCE_CUT
    assert event.decision.selected_venue_id is None
    assert not event.decision.ghost_selected
    assert run.terminal_inventory == run.initial_inventory

    unused_stale_reference = run_shadow_study(
        ghost=_ghost(),
        baselines=(
            _control(),
            ConstantProductEdge(
                "unused-control", "unused:stale", "X", "Y", 1_000, 1_000, stale_cut
            ),
        ),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "unused-incompatible-cut",
            True,
            0,
            ExternalStateTreatment.COUPLED_COPIED_STATE,
        ),
    )
    assert unused_stale_reference.events[0].decision.status is (
        RouteDecisionStatus.UNKNOWN_INCOMPATIBLE_SOURCE_CUT
    )


def test_sequential_inventory_never_resets_after_finite_edge_depletion() -> None:
    run = run_shadow_study(
        ghost=_ghost(y_atoms=150),
        baselines=(_control(),),
        intents=(_intent(1), _intent(2)),
        scenario=ShadowScenario("sequential", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    assert run.events[0].decision.ghost_selected
    assert isinstance(run.events[1].ghost_would_quote.outcome, QuoteRefusal)
    assert run.events[1].ghost_would_quote.outcome.reason == "insufficient_finite_capacity"
    assert not run.events[1].decision.ghost_selected
    assert run.terminal_inventory == run.events[-1].inventory_after
    assert run.terminal_inventory.x_atoms == 100
    assert run.terminal_inventory.y_atoms == 50


def test_external_and_self_routed_fees_never_collapse_into_one_revenue_number() -> None:
    run = run_shadow_study(
        ghost=_ghost(y_atoms=500, fee_rate=100_000_000),
        baselines=(ConstantProductEdge("control", "bad-control", "X", "Y", 1000, 800, SOURCE_CUT),),
        intents=(_intent(1), _intent(2, origin=FlowOrigin.HOUSEHOLD)),
        scenario=ShadowScenario("fee-origin", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    assert run.terminal_inventory.external_fee_x_atoms == 10
    assert run.terminal_inventory.self_fee_x_atoms == 10
    assert run.terminal_inventory.x_atoms == 180
    assert run.terminal_inventory.household_counterparty_x_atoms == -100
    assert run.terminal_inventory.household_counterparty_y_atoms == 90
    assert run.terminal_inventory.consolidated() == (100, 410)


def test_public_inventory_refuses_unpaired_self_fee_and_accepts_exact_counterleg() -> None:
    with pytest.raises(ValueError, match="self fees must exactly reconcile"):
        AssetInventory(x_atoms=100, y_atoms=0, self_fee_x_atoms=10)

    counterleg = HouseholdSelfRouteCounterleg(
        quote_digest="quote:household",
        direction=Direction.X_TO_Y,
        gross_input_atoms=100,
        output_atoms=90,
        lp_fee_atoms=10,
        protocol_fee_atoms=0,
    )
    exact = AssetInventory(
        x_atoms=100,
        y_atoms=0,
        self_fee_x_atoms=10,
        household_counterparty_x_atoms=-100,
        household_counterparty_y_atoms=90,
        self_route_counterlegs=(counterleg,),
    )
    assert exact.consolidated() == (10, 90)

    with pytest.raises(ValueError, match="counterparty deltas must exactly reconcile"):
        AssetInventory(
            x_atoms=100,
            y_atoms=0,
            self_fee_x_atoms=10,
            household_counterparty_x_atoms=-99,
            household_counterparty_y_atoms=90,
            self_route_counterlegs=(counterleg,),
        )


def test_registered_arbitrage_is_a_separate_counterfactual_response() -> None:
    arbitrage = ArbitrageSpec(
        after_intent_id="intent:1",
        ordering=ArbitrageOrdering.AFTER_REQUEST,
        direction=Direction.Y_TO_X,
        input_asset_id="Y",
        output_asset_id="X",
        external_unwind_asset_id="Y",
        cost_asset_id="Y",
        profit_asset_id="Y",
        input_atoms=50,
        external_unwind_atoms=60,
        priority_and_route_cost_atoms=1,
        minimum_profit_atoms=5,
        latency_slots=0,
    )
    run = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "bounded-arbitrage",
            True,
            0,
            ExternalStateTreatment.COUPLED_COPIED_STATE,
            (arbitrage,),
        ),
    )
    response = run.events[0].arbitrage_responses[0]
    assert response.acted
    assert response.modeled_profit_atoms == 9
    assert response.transfer is not None
    assert response.claim_scope.startswith("registered_arbitrage")
    assert run.terminal_inventory.x_atoms == 50
    assert run.terminal_inventory.y_atoms == 450


def test_nonzero_arbitrage_latency_and_unit_mismatch_refuse_instead_of_acting_now() -> None:
    delayed = ArbitrageSpec(
        after_intent_id="intent:1",
        ordering=ArbitrageOrdering.AFTER_REQUEST,
        direction=Direction.Y_TO_X,
        input_asset_id="Y",
        output_asset_id="X",
        external_unwind_asset_id="Y",
        cost_asset_id="Y",
        profit_asset_id="Y",
        input_atoms=50,
        external_unwind_atoms=60,
        priority_and_route_cost_atoms=1,
        minimum_profit_atoms=5,
        latency_slots=1_000_000_000,
    )
    run = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "delayed", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE, (delayed,)
        ),
    )
    response = run.events[0].arbitrage_responses[0]
    assert not response.acted
    assert response.refusal_reason == "latency_state_unavailable"
    assert response.modeled_arrival_slot == response.request_slot + 1_000_000_000
    assert run.terminal_inventory.x_atoms == 100
    assert run.terminal_inventory.y_atoms == 400

    wrong_units = ArbitrageSpec(
        after_intent_id="intent:1",
        ordering=ArbitrageOrdering.AFTER_REQUEST,
        direction=Direction.Y_TO_X,
        input_asset_id="X",
        output_asset_id="Y",
        external_unwind_asset_id="X",
        cost_asset_id="X",
        profit_asset_id="X",
        input_atoms=50,
        external_unwind_atoms=60,
        priority_and_route_cost_atoms=1,
        minimum_profit_atoms=5,
        latency_slots=0,
    )
    wrong = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "wrong-units", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE, (wrong_units,)
        ),
    )
    assert wrong.events[0].arbitrage_responses[0].refusal_reason == (
        "arbitrage_asset_unit_mismatch"
    )


def test_source_gap_and_missing_candidate_never_become_zero_margin_activation() -> None:
    gap_witness = JupiterWitness(
        "jupiter:gap",
        SOURCE_CUT.slot,
        SOURCE_CUT,
        ("missing-control",),
        (),
        False,
        Coverage.SOURCE_GAP,
    )
    gap_intent = QuoteIntent(
        "intent:gap", 1, Direction.X_TO_Y, 100, FlowOrigin.EXTERNAL, gap_witness
    )
    gap = run_shadow_study(
        ghost=_ghost(),
        baselines=(),
        intents=(gap_intent,),
        scenario=ShadowScenario("gap", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    decision = gap.events[0].decision
    assert decision.status is RouteDecisionStatus.UNKNOWN_INCOMPLETE_UNIVERSE
    assert decision.selected_venue_id is None
    assert decision.margin_atoms is None
    assert not decision.ghost_selected
    assert gap.terminal_inventory == gap.initial_inventory

    missing_witness = JupiterWitness(
        "jupiter:missing",
        SOURCE_CUT.slot,
        SOURCE_CUT,
        ("missing-control",),
        (),
        True,
        Coverage.OBSERVED_COMPLETE,
    )
    missing = run_shadow_study(
        ghost=_ghost(),
        baselines=(),
        intents=(
            QuoteIntent(
                "intent:missing",
                1,
                Direction.X_TO_Y,
                100,
                FlowOrigin.EXTERNAL,
                missing_witness,
            ),
        ),
        scenario=ShadowScenario("missing", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    assert missing.events[0].decision.status is RouteDecisionStatus.UNKNOWN_MISSING_CANDIDATE
    assert missing.events[0].decision.margin_atoms is None

    no_route_witness = JupiterWitness(
        "jupiter:no-route",
        SOURCE_CUT.slot,
        SOURCE_CUT,
        ("control",),
        (),
        True,
        Coverage.OBSERVED_COMPLETE,
    )
    no_route = run_shadow_study(
        ghost=_ghost(),
        baselines=(ConstantProductEdge("control", "thin", "X", "Y", 1_000, 1, SOURCE_CUT),),
        intents=(
            QuoteIntent(
                "intent:no-route",
                1,
                Direction.X_TO_Y,
                1,
                FlowOrigin.EXTERNAL,
                no_route_witness,
            ),
        ),
        scenario=ShadowScenario("no-route", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    assert no_route.events[0].decision.status is (
        RouteDecisionStatus.UNKNOWN_NO_COMPARABLE_BASELINE
    )
    assert no_route.events[0].decision.margin_atoms is None
    assert no_route.terminal_inventory == no_route.initial_inventory

    with pytest.raises(ValueError, match="observed-complete"):
        JupiterWitness(
            "jupiter:contradiction",
            SOURCE_CUT.slot,
            SOURCE_CUT,
            (),
            (),
            True,
            Coverage.SOURCE_GAP,
        )


def test_shadow_run_is_byte_deterministic() -> None:
    kwargs = dict(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "deterministic", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    first = canonical_bytes(run_shadow_study(**kwargs))
    second = canonical_bytes(run_shadow_study(**kwargs))
    assert first == second


def test_run_registration_digest_binds_policy_inputs_and_source_cuts() -> None:
    scenario = ShadowScenario(
        "same-display-id", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
    )
    baseline = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=scenario,
    )
    changed_input = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1, input_atoms=101),),
        scenario=scenario,
    )
    alternate_cut = SourceCut("cut:102", 102, "profile:v1", "topology:1")
    changed_cut = run_shadow_study(
        ghost=_ghost(source_cut=alternate_cut),
        baselines=(_control(source_cut=alternate_cut),),
        intents=(_intent(1, source_cut=alternate_cut),),
        scenario=scenario,
    )
    changed_policy = run_shadow_study(
        ghost=_ghost(),
        baselines=(_control(),),
        intents=(_intent(1),),
        scenario=ShadowScenario(
            "same-display-id", True, 1, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )

    assert baseline.scenario.content_digest == changed_input.scenario.content_digest
    assert baseline.scenario.content_digest != changed_policy.scenario.content_digest
    assert (
        len(
            {
                baseline.registration_digest,
                changed_input.registration_digest,
                changed_cut.registration_digest,
                changed_policy.registration_digest,
            }
        )
        == 4
    )
