"""Sequential fixed-demand routed-liquidity shadow reducer."""

from __future__ import annotations

from .arithmetic import atoms
from .contracts import (
    ArbitrageOrdering,
    ArbitrageResponse,
    ArbitrageSpec,
    Coverage,
    Direction,
    ExactQuote,
    ExternalStateTreatment,
    FlowOrigin,
    ModeledTransfer,
    QuoteIntent,
    QuoteRefusal,
    RouteDecision,
    RouteDecisionStatus,
    ShadowEvent,
    ShadowRun,
    ShadowScenario,
    VenueQuote,
    WouldQuote,
)
from .operators import ConstantProductEdge, DlmmBinEdge, EdgeOperator

BaselineEdge = ConstantProductEdge | DlmmBinEdge


def _best_quote(quotes: tuple[VenueQuote, ...], candidates: tuple[str, ...]) -> ExactQuote | None:
    eligible = [
        item.outcome
        for item in quotes
        if item.outcome.venue_id in candidates and isinstance(item.outcome, ExactQuote)
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda item: (-item.output_atoms, item.venue_id))


def _transfer(intent_id: str, direction, quote: ExactQuote, post_digest: str) -> ModeledTransfer:
    return ModeledTransfer(
        venue_id=quote.venue_id,
        intent_id=intent_id,
        direction=direction,
        input_atoms=quote.input_atoms,
        output_atoms=quote.output_atoms,
        post_state_digest=post_digest,
    )


def _apply_arbitrage(
    ghost: DlmmBinEdge,
    spec: ArbitrageSpec,
    request_slot: int,
    *,
    blocked_reason: str | None = None,
) -> tuple[DlmmBinEdge, ArbitrageResponse]:
    arrival_slot = atoms(request_slot + spec.latency_slots, name="arbitrage arrival slot")
    expected_assets = (
        (ghost.asset_x, ghost.asset_y)
        if spec.direction is Direction.X_TO_Y
        else (ghost.asset_y, ghost.asset_x)
    )
    if (spec.input_asset_id, spec.output_asset_id) != expected_assets:
        reason = "arbitrage_asset_unit_mismatch"
        refusal = QuoteRefusal(ghost.edge_id, ghost.current_state_id, reason)
        return ghost, ArbitrageResponse(
            spec, refusal, False, None, None, request_slot, arrival_slot, reason
        )
    if blocked_reason is not None:
        refusal = QuoteRefusal(ghost.edge_id, ghost.current_state_id, blocked_reason)
        return ghost, ArbitrageResponse(
            spec, refusal, False, None, None, request_slot, arrival_slot, blocked_reason
        )
    if spec.latency_slots != 0:
        reason = "latency_state_unavailable"
        refusal = QuoteRefusal(ghost.edge_id, ghost.current_state_id, reason)
        return ghost, ArbitrageResponse(
            spec, refusal, False, None, None, request_slot, arrival_slot, reason
        )
    quote = ghost.quote(spec.direction, spec.input_atoms)
    if isinstance(quote, QuoteRefusal):
        return ghost, ArbitrageResponse(
            spec, quote, False, None, None, request_slot, arrival_slot, quote.reason
        )
    gross_profit = spec.external_unwind_atoms - spec.input_atoms
    profit = gross_profit - spec.priority_and_route_cost_atoms
    if profit < spec.minimum_profit_atoms:
        return ghost, ArbitrageResponse(
            spec,
            quote,
            False,
            profit,
            None,
            request_slot,
            arrival_slot,
            "below_minimum_profit",
        )
    updated = ghost.apply(quote, FlowOrigin.EXTERNAL)
    transfer = _transfer(
        f"arbitrage:{spec.after_intent_id}:{spec.ordering.value}",
        spec.direction,
        quote,
        updated.state_digest,
    )
    return updated, ArbitrageResponse(
        spec, quote, True, profit, transfer, request_slot, arrival_slot, None
    )


def run_shadow_study(
    *,
    ghost: DlmmBinEdge,
    baselines: tuple[BaselineEdge, ...],
    intents: tuple[QuoteIntent, ...],
    scenario: ShadowScenario,
) -> ShadowRun:
    """Replay ordered intents without network, wallet, or transaction capabilities.

    Jupiter witnesses define the observed candidate/routed layer. The reducer uses
    the witnessed candidates plus the scenario's explicit ghost-candidate
    assumption for its own deterministic direct-route comparison. It never turns a
    modeled selection into a ``LandedFill``.
    """

    if tuple(sorted(intents, key=lambda item: item.sequence)) != intents:
        raise ValueError("intents must be strictly ordered by sequence")
    if len({item.sequence for item in intents}) != len(intents):
        raise ValueError("intent sequences must be unique")
    if len({item.intent_id for item in intents}) != len(intents):
        raise ValueError("intent ids must be unique")
    intent_ids = {item.intent_id for item in intents}
    if any(item.after_intent_id not in intent_ids for item in scenario.arbitrage):
        raise ValueError("every arbitrage scenario must target an enrolled intent")
    if len({item.edge_id for item in baselines}) != len(baselines):
        raise ValueError("baseline edge ids must be unique")
    if ghost.edge_id in {item.edge_id for item in baselines}:
        raise ValueError("ghost and baseline edge identities must be distinct")
    if any((item.asset_x, item.asset_y) != (ghost.asset_x, ghost.asset_y) for item in baselines):
        raise ValueError("all direct controls must use the ghost's oriented asset pair")

    initial_ghost = ghost
    initial_baselines = baselines
    current_baselines = {item.edge_id: item for item in baselines}
    events: list[ShadowEvent] = []
    specs = {(item.after_intent_id, item.ordering): item for item in scenario.arbitrage}

    for intent in intents:
        before = ghost.inventory()
        responses: list[ArbitrageResponse] = []
        quote_sources: tuple[BaselineEdge, ...]
        if scenario.state_treatment is ExternalStateTreatment.FIXED_WITNESSED_STATE:
            quote_sources = initial_baselines
        else:
            quote_sources = tuple(current_baselines[item.edge_id] for item in baselines)
        venue_quotes = tuple(
            VenueQuote(
                observation_id=item.current_state_id,
                slot=item.source_cut.slot,
                source_cut=item.source_cut,
                outcome=item.quote(intent.direction, intent.input_atoms),
                coverage=intent.jupiter.coverage,
            )
            for item in quote_sources
        )
        provided_ids = {item.outcome.venue_id for item in venue_quotes}
        missing_candidates = set(intent.jupiter.candidate_venue_ids) - provided_ids
        incompatible_reference_cuts = {
            item.outcome.venue_id
            for item in venue_quotes
            if item.source_cut != intent.jupiter.source_cut
        }
        ghost_cut_incompatible = (
            scenario.ghost_assumed_candidate and ghost.source_cut != intent.jupiter.source_cut
        )
        structurally_complete = (
            intent.jupiter.universe_complete
            and intent.jupiter.coverage is Coverage.OBSERVED_COMPLETE
            and all(item.coverage is Coverage.OBSERVED_COMPLETE for item in venue_quotes)
        )
        baseline = (
            _best_quote(venue_quotes, intent.jupiter.candidate_venue_ids)
            if structurally_complete
            and not missing_candidates
            and not incompatible_reference_cuts
            and not ghost_cut_incompatible
            else None
        )
        if not structurally_complete:
            unknown_status = RouteDecisionStatus.UNKNOWN_INCOMPLETE_UNIVERSE
            unknown_reason = "route_universe_incomplete_or_gapped"
        elif missing_candidates:
            unknown_status = RouteDecisionStatus.UNKNOWN_MISSING_CANDIDATE
            unknown_reason = "candidate_quote_or_refusal_missing"
        elif incompatible_reference_cuts or ghost_cut_incompatible:
            unknown_status = RouteDecisionStatus.UNKNOWN_INCOMPATIBLE_SOURCE_CUT
            unknown_reason = "venue_or_ghost_source_cut_incompatible_with_jupiter"
        elif baseline is None:
            unknown_status = RouteDecisionStatus.UNKNOWN_NO_COMPARABLE_BASELINE
            unknown_reason = "no_successful_comparable_baseline_quote"
        else:
            unknown_status = None
            unknown_reason = None

        before_spec = specs.get((intent.intent_id, ArbitrageOrdering.BEFORE_REQUEST))
        if before_spec is not None:
            ghost, response = _apply_arbitrage(
                ghost,
                before_spec,
                intent.jupiter.slot,
                blocked_reason=unknown_reason,
            )
            responses.append(response)
        ghost_outcome = ghost.quote(intent.direction, intent.input_atoms)
        would_quote = WouldQuote(ghost.schedule_id, ghost.source_cut, ghost_outcome)
        ghost_quote = ghost_outcome if isinstance(ghost_outcome, ExactQuote) else None

        baseline_output = baseline.output_atoms if baseline is not None else None
        ghost_margin = (
            None
            if (
                ghost_quote is None
                or baseline_output is None
                or not scenario.ghost_assumed_candidate
            )
            else ghost_quote.output_atoms - baseline_output
        )
        # The control wins ties. This is deliberately conservative and version-stable.
        ghost_selected = bool(
            unknown_status is None
            and scenario.ghost_assumed_candidate
            and ghost_quote is not None
            and ghost_quote.output_atoms > baseline_output + scenario.minimum_margin_atoms
        )
        selected = (
            None if unknown_status is not None else (ghost_quote if ghost_selected else baseline)
        )
        if unknown_status is not None:
            decision = RouteDecision(
                status=unknown_status,
                selected_venue_id=None,
                baseline_venue_id=None,
                baseline_output_atoms=None,
                selected_output_atoms=None,
                ghost_assumed_candidate=scenario.ghost_assumed_candidate,
                ghost_selected=False,
                margin_atoms=None,
                unknown_reason=unknown_reason,
            )
        else:
            assert selected is not None
            decision = RouteDecision(
                status=RouteDecisionStatus.MODELED_SELECTION,
                selected_venue_id=selected.venue_id,
                baseline_venue_id=baseline.venue_id,
                baseline_output_atoms=baseline_output,
                selected_output_atoms=selected.output_atoms,
                ghost_assumed_candidate=scenario.ghost_assumed_candidate,
                ghost_selected=ghost_selected,
                margin_atoms=ghost_margin,
                unknown_reason=None,
            )
        modeled_transfer = None
        if selected is not None and ghost_selected:
            ghost = ghost.apply(selected, intent.origin)
            modeled_transfer = _transfer(
                intent.intent_id, intent.direction, selected, ghost.state_digest
            )
        elif (
            selected is not None
            and scenario.state_treatment is ExternalStateTreatment.COUPLED_COPIED_STATE
        ):
            baseline_edge: EdgeOperator = current_baselines[selected.venue_id]
            current_baselines[selected.venue_id] = baseline_edge.apply(selected, intent.origin)

        after_spec = specs.get((intent.intent_id, ArbitrageOrdering.AFTER_REQUEST))
        if after_spec is not None:
            ghost, response = _apply_arbitrage(
                ghost,
                after_spec,
                intent.jupiter.slot,
                blocked_reason=unknown_reason,
            )
            responses.append(response)

        events.append(
            ShadowEvent(
                intent=intent,
                venue_quotes=venue_quotes,
                ghost_would_quote=would_quote,
                decision=decision,
                modeled_transfer=modeled_transfer,
                arbitrage_responses=tuple(responses),
                inventory_before=before,
                inventory_after=ghost.inventory(),
            )
        )

    # This assertion is cheap, exact, and catches accidental inventory reset.
    atoms(ghost.inventory().x_atoms, name="terminal X")
    atoms(ghost.inventory().y_atoms, name="terminal Y")
    return ShadowRun(
        scenario=scenario,
        schedule_id=initial_ghost.schedule_id,
        initial_inventory=initial_ghost.inventory(),
        events=tuple(events),
        terminal_inventory=ghost.inventory(),
    )
