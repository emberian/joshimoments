from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from joshi_analysis.errors import ManifestError, TemporalLeakageError
from joshi_analysis.wave6_shadow_policy import (
    ACCOUNTING_IDENTITY,
    AUTHORITY,
    AccountingTreatment,
    ActionKind,
    AdverseSelectionMeasure,
    ArenaPlan,
    AssetAmount,
    AssetDelta,
    BasisQuality,
    BranchStatus,
    CueKind,
    DiagnosticKind,
    EconomicDiagnostic,
    EpistemicKind,
    EvidenceEpisode,
    EvidencePoint,
    EvidenceStatus,
    ExactValuationArtifact,
    LiquidityEffectEvidence,
    LiquidityEventKind,
    PolicyFamily,
    PolicySpec,
    PortfolioSnapshot,
    QuoteRole,
    QuoteStatus,
    RefusalCode,
    ShadowQuote,
    StartingValuation,
    SubjectBasis,
    TerminalLiquidationManifest,
    ValuationComponent,
    ValuationSourceKind,
    ValuationStatus,
    evaluate_arena,
    registered_policy_families,
)

BASE = datetime(2026, 8, 1, 12, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def moment(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def amounts(**values: int) -> tuple[AssetAmount, ...]:
    return tuple(AssetAmount(asset_id, value) for asset_id, value in sorted(values.items()))


def deltas(**values: int) -> tuple[AssetDelta, ...]:
    return tuple(AssetDelta(asset_id, value) for asset_id, value in sorted(values.items()))


def valuation_artifact(
    asset_id: str,
    input_atoms: int,
    output_atoms: int,
    *,
    source_kind: ValuationSourceKind = ValuationSourceKind.EXACT_SIZED_QUOTE,
    source_artifact_id: str | None = None,
) -> ExactValuationArtifact:
    identity = source_kind is ValuationSourceKind.NUMERAIRE_IDENTITY
    unit_output_atoms = 1 if identity else 5
    return ExactValuationArtifact(
        source_kind=source_kind,
        source_artifact_id=source_artifact_id or f"evidence-starting-{asset_id}",
        source_artifact_digest=DIGEST,
        carrier_id=(
            "intrinsic:numeraire-identity-v1"
            if identity
            else "fixture:exact-starting-route-v1"
        ),
        unit_id="asset_atoms_exact_integer",
        unit_input=AssetAmount(asset_id, 1),
        unit_output=AssetAmount("sol", unit_output_atoms),
        sized_input=AssetAmount(asset_id, input_atoms),
        sized_output=AssetAmount("sol", output_atoms),
        available_at=moment(0),
        commit_seq=2,
    )


def point(
    point_id: str,
    minute: int,
    cue: CueKind,
    *,
    status: EvidenceStatus = EvidenceStatus.OBSERVED,
    kind: EpistemicKind = EpistemicKind.OBSERVED_FACT,
) -> EvidencePoint:
    observed = status is EvidenceStatus.OBSERVED
    return EvidencePoint(
        point_id=point_id,
        event_at=moment(minute),
        available_at=moment(minute),
        commit_seq=minute + 1,
        cue=cue,
        status=status,
        epistemic_kind=kind,
        evidence_ids=(f"evidence-{point_id}",),
        evidence_digest=DIGEST,
        scene_id="scene-1" if kind is EpistemicKind.OPERATOR_PERCEPTION else None,
        gap_ids=() if observed else (f"gap-{point_id}",),
        reason=None if observed else f"{status.value} input",
    )


def quote(
    quote_id: str,
    point_id: str,
    minute: int,
    action: ActionKind,
    pre: dict[str, int],
    effect: dict[str, int],
    *,
    role: QuoteRole = QuoteRole.HYPOTHETICAL_EXECUTION,
    method_id: str = "exact-size-route-v1",
    diagnostics: tuple[EconomicDiagnostic, ...] = (),
    liquidity_evidence: LiquidityEffectEvidence | None = None,
    status: QuoteStatus = QuoteStatus.PROJECTED,
    refusal_reason: str | None = None,
) -> ShadowQuote:
    evidence_ids = (f"evidence-{quote_id}",)
    if liquidity_evidence is None and action is ActionKind.LP_INSTALL:
        liquidity_evidence = LiquidityEffectEvidence(
            event_id="lp-install-event-1",
            event_kind=LiquidityEventKind.INSTALL,
            position_id="lp-position-1",
            installed_capital_event_id="lp-install-event-1",
            evidence_ids=evidence_ids,
            evidence_digest=DIGEST,
            principal_deltas=deltas(**effect),
        )
    elif liquidity_evidence is None and action is ActionKind.LP_ROUTE_EXTERNAL:
        fees: dict[str, int] = {}
        for diagnostic in diagnostics:
            if diagnostic.kind is DiagnosticKind.EXTERNAL_LP_FEE:
                fees[diagnostic.asset_id] = fees.get(diagnostic.asset_id, 0) + diagnostic.atoms
        principal = {
            asset_id: atoms - fees.get(asset_id, 0)
            for asset_id, atoms in effect.items()
            if atoms - fees.get(asset_id, 0) != 0
        }
        liquidity_evidence = LiquidityEffectEvidence(
            event_id=f"lp-flow-{quote_id}",
            event_kind=LiquidityEventKind.EXTERNAL_FLOW,
            position_id="lp-position-1",
            installed_capital_event_id="lp-install-event-1",
            evidence_ids=evidence_ids,
            evidence_digest=DIGEST,
            principal_deltas=deltas(**principal),
            external_fee_deltas=deltas(**fees),
        )
    return ShadowQuote(
        quote_id=quote_id,
        decision_point_id=point_id,
        role=role,
        action_kind=action,
        method_id=method_id,
        requested_at=moment(minute),
        state_as_of=moment(minute),
        available_at=moment(minute),
        valid_through=moment(60) if role is QuoteRole.TERMINAL_LIQUIDATION else moment(minute + 1),
        commit_seq=minute + 20,
        status=status,
        pre_balances=amounts(**pre),
        balance_deltas=deltas(**effect) if status is QuoteStatus.PROJECTED else (),
        evidence_ids=evidence_ids,
        evidence_digest=DIGEST,
        terminal_asset_id=(
            next(
                (
                    asset_id
                    for asset_id, atoms in sorted(effect.items())
                    if asset_id != "sol" and atoms < 0
                ),
                None,
            )
            if role is QuoteRole.TERMINAL_LIQUIDATION
            else None
        ),
        liquidity_evidence=liquidity_evidence,
        diagnostics=diagnostics,
        refusal_reason=refusal_reason,
    )


def episode() -> EvidenceEpisode:
    points = (
        point("point-entry", 10, CueKind.CRACKLE_ENTRY, kind=EpistemicKind.OPERATOR_PERCEPTION),
        point("point-take", 20, CueKind.TAKE_SOME),
        point("point-flat", 30, CueKind.FLAT_WATCH),
        point("point-reentry", 40, CueKind.REENTRY),
        point("point-lp-install", 45, CueKind.LP_INSTALL),
        point("point-lp-flow", 50, CueKind.LP_EXTERNAL_FLOW),
    )
    fee = EconomicDiagnostic(
        "diag-external-fee",
        DiagnosticKind.EXTERNAL_LP_FEE,
        "sol",
        5,
        AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
        ("evidence-q-lp-flow",),
    )
    itr = EconomicDiagnostic(
        "diag-itr",
        DiagnosticKind.ITR,
        "sol",
        3,
        AccountingTreatment.COUNTERFACTUAL_NON_POSTING,
        ("evidence-q-lp-flow",),
    )
    execution_quotes = (
        quote(
            "q-entry",
            "point-entry",
            10,
            ActionKind.BUY,
            {"sol": 1000, "token": 0},
            {"sol": -100, "token": 100},
        ),
        quote(
            "q-take",
            "point-take",
            20,
            ActionKind.SELL_PARTIAL,
            {"sol": 900, "token": 100},
            {"sol": 70, "token": -50},
        ),
        quote(
            "q-flat",
            "point-flat",
            30,
            ActionKind.FLAT_WATCH_EXIT,
            {"sol": 900, "token": 100},
            {"sol": 110, "token": -100},
        ),
        quote(
            "q-reentry",
            "point-reentry",
            40,
            ActionKind.REENTER,
            {"sol": 1010, "token": 0},
            {"sol": -100, "token": 80},
        ),
        quote(
            "q-lp-install",
            "point-lp-install",
            45,
            ActionKind.LP_INSTALL,
            {"sol": 1000, "token": 0},
            {"sol": -200, "token": 200},
        ),
        quote(
            "q-lp-flow",
            "point-lp-flow",
            50,
            ActionKind.LP_ROUTE_EXTERNAL,
            {"sol": 800, "token": 200},
            {"sol": 65, "token": -50},
            diagnostics=(fee, itr),
        ),
    )
    terminal_quotes = (
        quote(
            "q-terminal-crackle",
            "terminal-60",
            60,
            ActionKind.TERMINAL_LIQUIDATE,
            {"sol": 900, "token": 100},
            {"sol": 120, "token": -100},
            role=QuoteRole.TERMINAL_LIQUIDATION,
            method_id="terminal-route-v1",
        ),
        quote(
            "q-terminal-flat-reentry",
            "terminal-60",
            60,
            ActionKind.TERMINAL_LIQUIDATE,
            {"sol": 910, "token": 80},
            {"sol": 104, "token": -80},
            role=QuoteRole.TERMINAL_LIQUIDATION,
            method_id="terminal-route-v1",
        ),
        quote(
            "q-terminal-lp",
            "terminal-60",
            60,
            ActionKind.TERMINAL_LIQUIDATE,
            {"sol": 865, "token": 150},
            {"sol": 160, "token": -150},
            role=QuoteRole.TERMINAL_LIQUIDATION,
            method_id="terminal-route-v1",
        ),
        quote(
            "q-terminal-runner",
            "terminal-60",
            60,
            ActionKind.TERMINAL_LIQUIDATE,
            {"sol": 970, "token": 50},
            {"sol": 65, "token": -50},
            role=QuoteRole.TERMINAL_LIQUIDATION,
            method_id="terminal-route-v1",
        ),
    )
    snapshot = PortfolioSnapshot(
        "snapshot-1",
        moment(0),
        moment(0),
        1,
        amounts(sol=1000, token=0),
        ("evidence-snapshot",),
        DIGEST,
    )
    valuation = StartingValuation(
        manifest_id="starting-value-v1",
        numeraire_asset_id="sol",
        as_of=moment(0),
        known_at=moment(0),
        commit_seq=3,
        evidence_ids=(
            "evidence-snapshot",
            "evidence-starting-sol",
            "evidence-starting-token",
        ),
        evidence_digest=DIGEST,
        components=(
            ValuationComponent(
                "sol",
                1000,
                1000,
                ("evidence-snapshot", "evidence-starting-sol"),
                DIGEST,
                "numeraire_identity_1_to_1",
                ValuationStatus.KNOWN,
                source_artifact=valuation_artifact(
                    "sol",
                    1000,
                    1000,
                    source_kind=ValuationSourceKind.NUMERAIRE_IDENTITY,
                ),
            ),
            ValuationComponent(
                "token",
                0,
                0,
                ("evidence-snapshot", "evidence-starting-token"),
                DIGEST,
                "exact_sized_quote_v1",
                ValuationStatus.KNOWN,
                source_artifact=valuation_artifact("token", 0, 0),
            ),
        ),
    )
    return EvidenceEpisode(
        episode_id="episode-1",
        subject_asset_id="token",
        numeraire_asset_id="sol",
        starts_at=moment(1),
        terminal_horizon=moment(60),
        knowledge_cutoff=moment(61),
        as_known_commit_seq=100,
        starting_snapshot=snapshot,
        starting_valuation=valuation,
        starting_subject_basis=SubjectBasis(
            "token", 0, BasisQuality.KNOWN, 0, 1, ("evidence-snapshot",)
        ),
        decision_points=points,
        execution_quotes=execution_quotes,
        terminal_manifest=TerminalLiquidationManifest(
            "terminal-v1", "1", moment(60), "sol", "terminal-route-v1", terminal_quotes
        ),
    )


def policies() -> tuple[PolicySpec, ...]:
    registered = moment(0)
    return (
        PolicySpec("policy-abstain", "1", PolicyFamily.ABSTAIN, registered),
        PolicySpec("policy-observe", "1", PolicyFamily.OBSERVE, registered),
        PolicySpec(
            "policy-crackle", "1", PolicyFamily.CRACKLE_ENTRY, registered, entry_spend_atoms=100
        ),
        PolicySpec(
            "policy-runner",
            "1",
            PolicyFamily.TAKE_SOME_RUNNER,
            registered,
            entry_spend_atoms=100,
            take_fraction_ppm=500_000,
        ),
        PolicySpec(
            "policy-flat",
            "1",
            PolicyFamily.FLAT_WATCH_REENTRY,
            registered,
            entry_spend_atoms=100,
        ),
        PolicySpec(
            "policy-lp",
            "1",
            PolicyFamily.LP_ROUTED_LIQUIDITY_SHADOW,
            registered,
            adverse_selection_measure=AdverseSelectionMeasure.ITR,
        ),
    )


def plan(*, source_episode: EvidenceEpisode | None = None) -> ArenaPlan:
    return ArenaPlan(
        "arena-plan-1",
        moment(0),
        source_episode or episode(),
        policies(),
        "policy-abstain",
    )


def branches_by_id(artifact: object) -> dict[str, object]:
    return {branch.policy_id: branch for branch in artifact.branches}  # type: ignore[attr-defined]


def test_all_registered_families_close_on_common_information_and_terminal_value() -> None:
    artifact = evaluate_arena(plan())
    branches = branches_by_id(artifact)
    assert registered_policy_families() == (
        "abstain",
        "observe",
        "crackle_entry",
        "take_some_runner",
        "flat_watch_reentry",
        "lp_routed_liquidity_shadow",
    )
    assert {branch.common_information_digest for branch in artifact.branches} == {
        artifact.common_information_digest
    }
    assert {name: branch.net_pnl_numeraire_atoms for name, branch in branches.items()} == {
        "policy-abstain": 0,
        "policy-observe": 0,
        "policy-crackle": 20,
        "policy-runner": 35,
        "policy-flat": 14,
        "policy-lp": 25,
    }
    assert all(branch.status is BranchStatus.COMPLETE for branch in artifact.branches)
    assert artifact.as_dict()["accounting_identity"] == ACCOUNTING_IDENTITY
    runner = branches["policy-runner"]
    assert runner.pre_liquidation_subject_basis.as_dict() == {
        "asset_id": "token",
        "quantity_atoms": "50",
        "quality": "known",
        "value": {"numerator": "50", "denominator": "1"},
    }
    assert runner.terminal_subject_basis.value.as_dict() == {
        "numerator": "0",
        "denominator": "1",
    }


def test_action_execution_effect_and_actual_ledger_are_separate() -> None:
    branch = branches_by_id(evaluate_arena(plan()))["policy-flat"]
    assert [action.action_kind for action in branch.actions] == [
        ActionKind.BUY,
        ActionKind.FLAT_WATCH_EXIT,
        ActionKind.REENTER,
    ]
    assert len(branch.actions) == len(branch.executions) == len(branch.effects) == 3
    assert "flat_watching" in branch.episode_states
    assert "exposed_epoch_2" in branch.episode_states
    payload = branch.as_dict()
    assert all(item["authority"] == AUTHORITY for item in payload["actions"])
    assert all(not item["posted_to_actual_ledger"] for item in payload["hypothetical_effects"])
    assert all("fill" in item["explicit_non_claims"] for item in payload["execution_projections"])
    assert branch.effects[0].acquisition_basis.as_dict() == {
        "numerator": "100",
        "denominator": "1",
    }
    assert branch.effects[1].allocated_basis.as_dict() == {
        "numerator": "100",
        "denominator": "1",
    }
    assert branch.effects[1].realized_result.as_dict() == {
        "numerator": "10",
        "denominator": "1",
    }


def test_deterministic_ids_and_canonical_bytes() -> None:
    first = evaluate_arena(plan())
    second = evaluate_arena(plan())
    assert first.artifact_id == second.artifact_id
    assert first.artifact_digest == second.artifact_digest
    assert first.canonical_bytes() == second.canonical_bytes()
    assert [branch.branch_id for branch in first.branches] == [
        branch.branch_id for branch in second.branches
    ]


def test_set_like_input_order_does_not_change_semantic_artifact() -> None:
    original_plan = plan()
    source = original_plan.episode
    reordered_episode = replace(
        source,
        execution_quotes=tuple(reversed(source.execution_quotes)),
        terminal_manifest=replace(
            source.terminal_manifest,
            quotes=tuple(reversed(source.terminal_manifest.quotes)),
        ),
    )
    reordered_plan = replace(
        original_plan,
        episode=reordered_episode,
        policies=tuple(reversed(original_plan.policies)),
    )
    assert evaluate_arena(original_plan).canonical_bytes() == evaluate_arena(
        reordered_plan
    ).canonical_bytes()


def test_pnl_lvr_itr_fee_and_opportunity_cost_are_not_double_counted() -> None:
    artifact = evaluate_arena(plan())
    lp = branches_by_id(artifact)["policy-lp"]
    assert lp.terminal_wealth_numeraire_atoms == 1025
    assert lp.net_pnl_numeraire_atoms == 25
    negative_itr = replace(lp.diagnostics[1], atoms=-3)
    negative_itr.validate()
    assert negative_itr.as_dict()["atoms"] == "-3"
    assert [(item.kind, item.atoms, item.treatment) for item in lp.diagnostics] == [
        (DiagnosticKind.EXTERNAL_LP_FEE, 5, AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT),
        (DiagnosticKind.ITR, 3, AccountingTreatment.COUNTERFACTUAL_NON_POSTING),
    ]
    comparison = next(
        item for item in artifact.opportunity_comparisons if item.candidate_policy_id == "policy-lp"
    )
    assert comparison.opportunity_cost_numeraire_atoms == -25
    assert comparison.candidate_surplus_numeraire_atoms == 25
    assert lp.net_pnl_numeraire_atoms == 25


def test_self_routed_owned_fee_is_internal_and_cannot_manufacture_revenue() -> None:
    original = episode()
    self_point = point("point-lp-self", 55, CueKind.LP_SELF_FLOW)
    self_fee = EconomicDiagnostic(
        "diag-self-owned-fee",
        DiagnosticKind.SELF_ROUTED_OWNED_FEE,
        "sol",
        2,
        AccountingTreatment.INTERNAL_NON_POSTING,
        ("evidence-q-lp-self",),
    )
    self_cost = EconomicDiagnostic(
        "diag-self-external-cost",
        DiagnosticKind.IRREVERSIBLE_COST,
        "sol",
        1,
        AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
        ("evidence-q-lp-self",),
    )
    self_evidence = LiquidityEffectEvidence(
        event_id="lp-self-event-1",
        event_kind=LiquidityEventKind.SELF_FLOW,
        position_id="lp-position-1",
        installed_capital_event_id="lp-install-event-1",
        evidence_ids=("evidence-q-lp-self",),
        evidence_digest=DIGEST,
        external_cost_deltas=deltas(sol=-1),
        self_payer_deltas=deltas(sol=-12, token=10),
        self_lp_deltas=deltas(sol=12, token=-10),
        self_paid_fee=AssetAmount("sol", 2),
        self_owned_fee=AssetAmount("sol", 2),
    )
    self_quote = quote(
        "q-lp-self",
        "point-lp-self",
        55,
        ActionKind.LP_ROUTE_SELF,
        {"sol": 865, "token": 150},
        {"sol": -1},
        diagnostics=(self_cost, self_fee),
        liquidity_evidence=self_evidence,
    )
    terminal_quote = quote(
        "q-terminal-lp-self",
        "terminal-60",
        60,
        ActionKind.TERMINAL_LIQUIDATE,
        {"sol": 864, "token": 150},
        {"sol": 160, "token": -150},
        role=QuoteRole.TERMINAL_LIQUIDATION,
        method_id="terminal-route-v1",
    )
    changed = replace(
        original,
        decision_points=(*original.decision_points, self_point),
        execution_quotes=(*original.execution_quotes, self_quote),
        terminal_manifest=replace(
            original.terminal_manifest,
            quotes=(*original.terminal_manifest.quotes, terminal_quote),
        ),
    )
    lp = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-lp"]
    assert lp.net_pnl_numeraire_atoms == 24
    diagnostic = next(
        item for item in lp.diagnostics if item.kind is DiagnosticKind.SELF_ROUTED_OWNED_FEE
    )
    assert diagnostic.atoms == 2
    assert diagnostic.treatment is AccountingTreatment.INTERNAL_NON_POSTING
    audit = lp.as_dict()["double_counting_audit"]
    assert audit["internal_non_posting_diagnostic_ids"] == ["diag-self-owned-fee"]
    assert not audit["diagnostics_added_to_net_pnl"]


def test_stale_decision_refuses_and_preserves_unknown_instead_of_trading() -> None:
    original = episode()
    stale = replace(
        original.decision_points[0],
        status=EvidenceStatus.STALE,
        gap_ids=("gap-stale-state",),
        reason="quote state exceeded freshness window",
    )
    changed = replace(original, decision_points=(stale, *original.decision_points[1:]))
    branch = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-crackle"]
    assert branch.net_pnl_numeraire_atoms == 0
    assert branch.status is BranchStatus.COMPLETE_WITH_REFUSALS
    assert branch.refusals[0].code is RefusalCode.EVIDENCE_NOT_OBSERVED
    assert branch.uncertainties[0].gap_ids == ("gap-stale-state",)
    assert not branch.effects


def test_unrouteable_terminal_inventory_is_unknown_not_zero_recovery() -> None:
    original = episode()
    terminal = replace(
        original.terminal_manifest,
        quotes=tuple(
            quote
            for quote in original.terminal_manifest.quotes
            if quote.quote_id != "q-terminal-crackle"
        ),
    )
    branch = branches_by_id(
        evaluate_arena(plan(source_episode=replace(original, terminal_manifest=terminal)))
    )["policy-crackle"]
    assert branch.status is BranchStatus.TERMINAL_VALUE_UNKNOWN
    assert branch.terminal_wealth_numeraire_atoms is None
    assert branch.net_pnl_numeraire_atoms is None
    assert branch.liquidation_legs[0].status == "unknown"
    assert branch.terminal_balances == (("sol", 900), ("token", 100))

    refused_quote = replace(
        next(
            quote
            for quote in original.terminal_manifest.quotes
            if quote.quote_id == "q-terminal-crackle"
        ),
        status=QuoteStatus.REFUSED,
        balance_deltas=(),
        refusal_reason="terminal route unavailable",
    )
    refused_terminal = replace(
        original.terminal_manifest,
        quotes=tuple(
            refused_quote if quote.quote_id == refused_quote.quote_id else quote
            for quote in original.terminal_manifest.quotes
        ),
    )
    refused_branch = branches_by_id(
        evaluate_arena(
            plan(source_episode=replace(original, terminal_manifest=refused_terminal))
        )
    )["policy-crackle"]
    assert refused_branch.liquidation_legs[0].quote_id == "q-terminal-crackle"
    assert refused_branch.liquidation_legs[0].reason == "terminal route unavailable"


def test_unknown_basis_never_becomes_zero_basis_or_known_realized_pnl() -> None:
    original = episode()
    changed_snapshot = replace(
        original.starting_snapshot,
        balances=amounts(sol=1000, token=10),
    )
    changed_valuation = replace(
        original.starting_valuation,
        components=(
            ValuationComponent(
                "sol",
                1000,
                1000,
                ("evidence-snapshot", "evidence-starting-sol"),
                DIGEST,
                "numeraire_identity_1_to_1",
                ValuationStatus.KNOWN,
                source_artifact=valuation_artifact(
                    "sol",
                    1000,
                    1000,
                    source_kind=ValuationSourceKind.NUMERAIRE_IDENTITY,
                ),
            ),
            ValuationComponent(
                "token",
                10,
                50,
                ("evidence-snapshot", "evidence-starting-token"),
                DIGEST,
                "exact_sized_quote_v1",
                ValuationStatus.KNOWN,
                source_artifact=valuation_artifact("token", 10, 50),
            ),
        ),
    )
    terminal_quote = quote(
        "q-terminal-unknown-basis",
        "terminal-60",
        60,
        ActionKind.TERMINAL_LIQUIDATE,
        {"sol": 1000, "token": 10},
        {"sol": 60, "token": -10},
        role=QuoteRole.TERMINAL_LIQUIDATION,
        method_id="terminal-route-v1",
    )
    changed = replace(
        original,
        starting_snapshot=changed_snapshot,
        starting_valuation=changed_valuation,
        starting_subject_basis=SubjectBasis(
            "token", 10, BasisQuality.UNKNOWN, None, None, ("evidence-snapshot",)
        ),
        terminal_manifest=replace(
            original.terminal_manifest,
            quotes=(*original.terminal_manifest.quotes, terminal_quote),
        ),
    )
    observed = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-observe"]
    assert observed.net_pnl_numeraire_atoms == 10
    exact_source = changed_valuation.components[1].source_artifact
    assert exact_source is not None
    assert exact_source.sized_input == AssetAmount("token", 10)
    assert exact_source.sized_output == AssetAmount("sol", 50)
    assert exact_source.as_dict()["artifact_digest"] == exact_source.artifact_digest
    assert observed.pre_liquidation_subject_basis.quality is BasisQuality.UNKNOWN
    assert observed.liquidation_legs[0].allocated_basis is None
    assert observed.liquidation_legs[0].realized_result is None
    assert observed.terminal_subject_basis.quality is BasisQuality.KNOWN


def test_late_policy_outcome_leakage_and_predecision_quote_fail_closed() -> None:
    with pytest.raises(TemporalLeakageError, match="registered later"):
        replace(policies()[0], registered_at=moment(2)).validate()
        evaluate_arena(
            replace(plan(), policies=(replace(policies()[0], registered_at=moment(2)),))
        )
    original = episode()
    leaked = replace(original.decision_points[0], outcome_visible=True)
    with pytest.raises(TemporalLeakageError, match="outcome-visible"):
        replace(original, decision_points=(leaked, *original.decision_points[1:])).validate()
    early_quote = replace(original.execution_quotes[0], requested_at=moment(9))
    with pytest.raises(TemporalLeakageError, match="before its policy decision"):
        replace(
            original,
            execution_quotes=(early_quote, *original.execution_quotes[1:]),
        ).validate()
    late_quote = replace(
        original.execution_quotes[0],
        available_at=moment(21),
        valid_through=moment(22),
    )
    with pytest.raises(TemporalLeakageError, match="next decision in as-known order"):
        replace(
            original,
            execution_quotes=(late_quote, *original.execution_quotes[1:]),
        ).validate()


def test_ambiguous_or_wrong_state_quote_refuses_without_guessing() -> None:
    original = episode()
    duplicate = replace(original.execution_quotes[0], quote_id="q-entry-duplicate")
    changed = replace(
        original,
        execution_quotes=(original.execution_quotes[0], duplicate, *original.execution_quotes[1:]),
    )
    branch = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-crackle"]
    assert branch.refusals[0].code is RefusalCode.AMBIGUOUS_QUOTE
    assert branch.net_pnl_numeraire_atoms == 0
    assert not branch.effects


def test_adverse_selection_and_self_fee_contracts_fail_closed() -> None:
    with pytest.raises(ManifestError, match="both LVR_grid and ITR"):
        replace(
            episode().execution_quotes[-1],
            diagnostics=(
                *episode().execution_quotes[-1].diagnostics,
                EconomicDiagnostic(
                    "diag-lvr",
                    DiagnosticKind.LVR_GRID,
                    "sol",
                    4,
                    AccountingTreatment.COUNTERFACTUAL_NON_POSTING,
                    ("evidence-q-lp-flow",),
                ),
            ),
        ).validate()
    with pytest.raises(ManifestError, match="internal_non_posting"):
        EconomicDiagnostic(
            "diag-self-fee",
            DiagnosticKind.SELF_ROUTED_OWNED_FEE,
            "sol",
            2,
            AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
            ("evidence-self-flow",),
        ).validate()
    changed_policies = tuple(
        replace(policy, adverse_selection_measure=AdverseSelectionMeasure.LVR_GRID)
        if policy.policy_id == "policy-lp"
        else policy
        for policy in policies()
    )
    artifact = evaluate_arena(replace(plan(), policies=changed_policies))
    lp = branches_by_id(artifact)["policy-lp"]
    assert lp.refusals[0].code is RefusalCode.ADVERSE_SELECTION_CONFLICT
    assert lp.status is BranchStatus.TERMINAL_VALUE_UNKNOWN
    assert lp.net_pnl_numeraire_atoms is None


def test_quote_effect_cannot_create_inventory_or_ignore_changed_asset_prestate() -> None:
    unsafe = quote(
        "q-unsafe",
        "point-entry",
        10,
        ActionKind.BUY,
        {"sol": 10, "token": 0},
        {"sol": -11, "token": 1},
    )
    with pytest.raises(ManifestError, match="negative"):
        unsafe.validate()
    missing_prestate = replace(
        episode().execution_quotes[0], pre_balances=amounts(sol=1000)
    )
    with pytest.raises(ManifestError, match="bind every asset"):
        missing_prestate.validate()


def test_numeraire_misvaluation_and_zero_positive_inventory_value_fail_closed() -> None:
    original = episode()
    components = list(original.starting_valuation.components)
    components[0] = replace(components[0], numeraire_atoms=0)
    bad_numeraire = replace(original.starting_valuation, components=tuple(components))
    with pytest.raises(ManifestError, match="positive starting inventory"):
        replace(original, starting_valuation=bad_numeraire).validate()

    positive_token = replace(
        original.starting_snapshot,
        balances=amounts(sol=1000, token=10),
    )
    bad_components = (
        original.starting_valuation.components[0],
        replace(
            original.starting_valuation.components[1],
            holding_atoms=10,
            numeraire_atoms=0,
            source_artifact=valuation_artifact("token", 10, 50),
        ),
    )
    with pytest.raises(ManifestError, match="positive exact value or typed refusal"):
        replace(
            original,
            starting_snapshot=positive_token,
            starting_valuation=replace(
                original.starting_valuation, components=bad_components
            ),
            starting_subject_basis=SubjectBasis(
                "token", 10, BasisQuality.UNKNOWN, None, None, ("evidence-snapshot",)
            ),
        ).validate()


def test_refused_starting_value_blocks_pnl_and_opportunity_arithmetic() -> None:
    original = episode()
    changed_snapshot = replace(
        original.starting_snapshot,
        balances=amounts(sol=1000, token=10),
    )
    refused_component = replace(
        original.starting_valuation.components[1],
        holding_atoms=10,
        numeraire_atoms=None,
        valuation_method_id="caller_asserted_positive_quote",
        status=ValuationStatus.REFUSED,
        refusal_reason="no exact starting whole-position route",
        source_artifact=None,
    )
    terminal_quote = quote(
        "q-terminal-refused-start",
        "terminal-60",
        60,
        ActionKind.TERMINAL_LIQUIDATE,
        {"sol": 1000, "token": 10},
        {"sol": 60, "token": -10},
        role=QuoteRole.TERMINAL_LIQUIDATION,
        method_id="terminal-route-v1",
    )
    changed = replace(
        original,
        starting_snapshot=changed_snapshot,
        starting_valuation=replace(
            original.starting_valuation,
            components=(original.starting_valuation.components[0], refused_component),
        ),
        starting_subject_basis=SubjectBasis(
            "token", 10, BasisQuality.UNKNOWN, None, None, ("evidence-snapshot",)
        ),
        terminal_manifest=replace(
            original.terminal_manifest,
            quotes=(*original.terminal_manifest.quotes, terminal_quote),
        ),
    )
    artifact = evaluate_arena(plan(source_episode=changed))
    observed = branches_by_id(artifact)["policy-observe"]
    assert observed.status is BranchStatus.STARTING_VALUE_UNKNOWN
    assert observed.starting_value_numeraire_atoms is None
    assert observed.terminal_wealth_numeraire_atoms == 1060
    assert observed.net_pnl_numeraire_atoms is None
    assert any(item.kind == "starting_valuation_refused" for item in observed.uncertainties)
    assert all(item.status == "unknown" for item in artifact.opportunity_comparisons)


def test_caller_asserted_starting_quote_cannot_manufacture_surplus() -> None:
    original = episode()
    changed_snapshot = replace(
        original.starting_snapshot,
        balances=amounts(sol=1000, token=10),
    )
    forged_component = replace(
        original.starting_valuation.components[1],
        holding_atoms=10,
        numeraire_atoms=1,
        valuation_method_id="caller_asserted_positive_quote",
        source_artifact=valuation_artifact("token", 10, 50),
    )
    terminal_quote = quote(
        "q-terminal-forged-start",
        "terminal-60",
        60,
        ActionKind.TERMINAL_LIQUIDATE,
        {"sol": 1000, "token": 10},
        {"sol": 60, "token": -10},
        role=QuoteRole.TERMINAL_LIQUIDATION,
        method_id="terminal-route-v1",
    )
    adversary = replace(
        original,
        starting_snapshot=changed_snapshot,
        starting_valuation=replace(
            original.starting_valuation,
            components=(original.starting_valuation.components[0], forged_component),
        ),
        starting_subject_basis=SubjectBasis(
            "token", 10, BasisQuality.UNKNOWN, None, None, ("evidence-snapshot",)
        ),
        terminal_manifest=replace(
            original.terminal_manifest,
            quotes=(*original.terminal_manifest.quotes, terminal_quote),
        ),
    )
    with pytest.raises(ManifestError, match="recognized exact valuation method"):
        evaluate_arena(plan(source_episode=adversary))

    forged_amount = replace(
        adversary,
        starting_valuation=replace(
            adversary.starting_valuation,
            components=(
                adversary.starting_valuation.components[0],
                replace(forged_component, valuation_method_id="exact_sized_quote_v1"),
            ),
        ),
    )
    with pytest.raises(ManifestError, match="recomputable source sized output"):
        evaluate_arena(plan(source_episode=forged_amount))


def test_exact_starting_source_must_precede_the_valuation_decision() -> None:
    original = episode()
    token = original.starting_valuation.components[1]
    assert token.source_artifact is not None
    late_commit = replace(
        token,
        source_artifact=replace(token.source_artifact, commit_seq=3),
    )
    with pytest.raises(TemporalLeakageError, match="precede its starting valuation decision"):
        replace(
            original,
            starting_valuation=replace(
                original.starting_valuation,
                components=(original.starting_valuation.components[0], late_commit),
            ),
        ).validate()

    post_decision_valuation = replace(
        original.starting_valuation,
        commit_seq=12,
        components=tuple(
            replace(
                component,
                source_artifact=(
                    None
                    if component.source_artifact is None
                    else replace(component.source_artifact, commit_seq=11)
                ),
            )
            for component in original.starting_valuation.components
        ),
    )
    with pytest.raises(TemporalLeakageError, match="first policy decision commit"):
        replace(original, starting_valuation=post_decision_valuation).validate()


def test_zero_output_terminal_disposal_requires_typed_refusal() -> None:
    original = episode()
    terminal = next(
        item
        for item in original.terminal_manifest.quotes
        if item.quote_id == "q-terminal-crackle"
    )
    zero_output = replace(terminal, balance_deltas=deltas(token=-100))
    with pytest.raises(ManifestError, match="positive exact numeraire output"):
        replace(
            original.terminal_manifest,
            quotes=tuple(
                zero_output if item.quote_id == terminal.quote_id else item
                for item in original.terminal_manifest.quotes
            ),
        ).validate()


def test_lp_flow_before_install_refuses_without_quote_or_balance_effect() -> None:
    original = episode()
    premature = point("point-lp-premature", 44, CueKind.LP_EXTERNAL_FLOW)
    changed = replace(
        original,
        decision_points=(
            *original.decision_points[:4],
            premature,
            *original.decision_points[4:],
        ),
    )
    lp = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-lp"]
    assert lp.refusals[0].code is RefusalCode.ILLEGAL_POLICY_TRANSITION
    assert lp.effects[0].quote_id == "q-lp-install"
    assert all(effect.quote_id != "q-lp-premature" for effect in lp.effects)
    assert lp.net_pnl_numeraire_atoms == 25


def test_lp_flow_must_reconcile_principal_fee_and_active_position() -> None:
    forged = quote(
        "q-lp-forged-gain",
        "point-lp-flow",
        50,
        ActionKind.LP_ROUTE_EXTERNAL,
        {"sol": 1000, "token": 0},
        {"sol": 10},
    )
    with pytest.raises(ManifestError, match="give and receive principal"):
        forged.validate()

    original = episode()
    flow = original.execution_quotes[-1]
    mismatched_evidence = replace(flow.liquidity_evidence, position_id="other-position")
    mismatched_flow = replace(flow, liquidity_evidence=mismatched_evidence)
    changed = replace(
        original,
        execution_quotes=(*original.execution_quotes[:-1], mismatched_flow),
    )
    lp = branches_by_id(evaluate_arena(plan(source_episode=changed)))["policy-lp"]
    assert lp.refusals[0].code is RefusalCode.LP_POSITION_MISMATCH
    assert lp.status is BranchStatus.TERMINAL_VALUE_UNKNOWN


def test_lp_fee_labels_require_evidence_and_self_fee_cannot_post() -> None:
    external_fee = EconomicDiagnostic(
        "diag-unbound-fee",
        DiagnosticKind.EXTERNAL_LP_FEE,
        "sol",
        2,
        AccountingTreatment.INCLUDED_IN_BALANCE_EFFECT,
        ("evidence-q-entry",),
    )
    with pytest.raises(ManifestError, match="exact liquidity accounting evidence"):
        replace(episode().execution_quotes[0], diagnostics=(external_fee,)).validate()

    self_fee = EconomicDiagnostic(
        "diag-self-forged",
        DiagnosticKind.SELF_ROUTED_OWNED_FEE,
        "sol",
        2,
        AccountingTreatment.INTERNAL_NON_POSTING,
        ("evidence-self-forged",),
    )
    evidence = LiquidityEffectEvidence(
        event_id="self-forged",
        event_kind=LiquidityEventKind.SELF_FLOW,
        position_id="lp-position-1",
        installed_capital_event_id="lp-install-event-1",
        evidence_ids=("evidence-self-forged",),
        evidence_digest=DIGEST,
        self_payer_deltas=deltas(sol=-2),
        self_lp_deltas=deltas(sol=2),
        self_paid_fee=AssetAmount("sol", 2),
        self_owned_fee=AssetAmount("sol", 2),
    )
    posted = ShadowQuote(
        quote_id="q-self-forged",
        decision_point_id="point-lp-flow",
        role=QuoteRole.HYPOTHETICAL_EXECUTION,
        action_kind=ActionKind.LP_ROUTE_SELF,
        method_id="exact-size-route-v1",
        requested_at=moment(50),
        state_as_of=moment(50),
        available_at=moment(50),
        valid_through=moment(51),
        commit_seq=70,
        status=QuoteStatus.PROJECTED,
        pre_balances=amounts(sol=1000),
        balance_deltas=deltas(sol=2),
        evidence_ids=("evidence-self-forged",),
        evidence_digest=DIGEST,
        liquidity_evidence=evidence,
        diagnostics=(self_fee,),
    )
    with pytest.raises(ManifestError, match="do not reconcile"):
        posted.validate()
    overstated_fee = replace(
        evidence,
        self_paid_fee=AssetAmount("sol", 3),
        self_owned_fee=AssetAmount("sol", 3),
    )
    with pytest.raises(ManifestError, match="contained in the exact route counterlegs"):
        overstated_fee.validate()


def test_same_time_commit_order_and_quote_after_decision_are_strict() -> None:
    original = episode()
    entry = original.execution_quotes[0]
    same_time_late_commit = replace(
        entry,
        available_at=moment(20),
        valid_through=moment(21),
        commit_seq=30,
    )
    with pytest.raises(TemporalLeakageError, match="precede the next decision"):
        replace(
            original,
            execution_quotes=(same_time_late_commit, *original.execution_quotes[1:]),
        ).validate()

    not_after_own_decision = replace(entry, commit_seq=11)
    with pytest.raises(TemporalLeakageError, match="follow its policy decision commit"):
        replace(
            original,
            execution_quotes=(not_after_own_decision, *original.execution_quotes[1:]),
        ).validate()

    same_time_earlier_commit = replace(
        entry,
        available_at=moment(20),
        valid_through=moment(21),
        commit_seq=20,
    )
    replace(
        original,
        execution_quotes=(same_time_earlier_commit, *original.execution_quotes[1:]),
    ).validate()
