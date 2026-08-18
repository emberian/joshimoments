from __future__ import annotations

from joshi_analysis.wave6_routed_shadow import (
    ArbitrageOrdering,
    ArbitrageSpec,
    ConstantProductEdge,
    Coverage,
    Direction,
    DlmmBinEdge,
    DlmmFeePolicy,
    ExternalStateTreatment,
    FixedBin,
    FlowOrigin,
    JupiterWitness,
    QuoteIntent,
    ShadowScenario,
    canonical_bytes,
    run_shadow_study,
)
from joshi_analysis.wave6_routed_shadow.arithmetic import Q64
from joshi_analysis.wave6_routed_shadow.contracts import ExactQuote, QuoteRefusal


def _witness(sequence: int, *, complete: bool = True) -> JupiterWitness:
    return JupiterWitness(
        witness_id=f"jupiter:{sequence}",
        slot=100 + sequence,
        candidate_venue_ids=("control",),
        routed_venue_ids=("control",),
        universe_complete=complete,
        coverage=Coverage.OBSERVED_COMPLETE if complete else Coverage.OBSERVED_PARTIAL,
    )


def _ghost(y_atoms: int = 500, fee_rate: int = 0) -> DlmmBinEdge:
    return DlmmBinEdge(
        edge_id="ghost",
        schedule_id="schedule:one",
        state_id="ghost-state",
        asset_x="X",
        asset_y="Y",
        active_bin_id=0,
        fee_policy=DlmmFeePolicy(fee_rate, 0),
        bins=(FixedBin(0, Q64, 0, y_atoms),),
    )


def _control() -> ConstantProductEdge:
    return ConstantProductEdge("control", "control-state", "X", "Y", 1000, 1000)


def _intent(sequence: int, *, origin: FlowOrigin = FlowOrigin.EXTERNAL) -> QuoteIntent:
    return QuoteIntent(
        intent_id=f"intent:{sequence}",
        sequence=sequence,
        direction=Direction.X_TO_Y,
        input_atoms=100,
        origin=origin,
        jupiter=_witness(sequence),
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
    assert event.decision.baseline_output_atoms == 90
    assert event.decision.selected_output_atoms == 100
    assert event.decision.ghost_selected
    assert event.modeled_transfer is not None
    assert event.intent.landed_fill is None
    assert event.modeled_transfer.post_state_digest


def test_sequential_inventory_never_resets_after_finite_edge_depletion() -> None:
    run = run_shadow_study(
        ghost=_ghost(y_atoms=150),
        baselines=(_control(),),
        intents=(_intent(1), _intent(2)),
        scenario=ShadowScenario(
            "sequential", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
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
        baselines=(),
        intents=(_intent(1), _intent(2, origin=FlowOrigin.HOUSEHOLD)),
        scenario=ShadowScenario(
            "fee-origin", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    assert run.terminal_inventory.external_fee_x_atoms == 10
    assert run.terminal_inventory.self_fee_x_atoms == 10
    assert run.terminal_inventory.x_atoms == 180
    assert run.terminal_inventory.consolidated() == (200, 320)


def test_registered_arbitrage_is_a_separate_counterfactual_response() -> None:
    arbitrage = ArbitrageSpec(
        after_intent_id="intent:1",
        ordering=ArbitrageOrdering.AFTER_REQUEST,
        direction=Direction.Y_TO_X,
        input_atoms=50,
        external_unwind_atoms=60,
        priority_and_route_cost_atoms=1,
        minimum_profit_atoms=5,
        latency_slots=1,
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
