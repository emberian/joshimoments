from __future__ import annotations

import pytest

from joshi_analysis.wave6_routed_shadow import (
    AdverseSelectionAttribution,
    AssetInventory,
    ConstantProductEdge,
    Coverage,
    Direction,
    DlmmBinEdge,
    DlmmFeePolicy,
    ExternalStateTreatment,
    Falsifier,
    FixedBin,
    FlowOrigin,
    JupiterWitness,
    LiquidationManifest,
    LiquidationQuote,
    LiquidationStatus,
    QuoteIntent,
    ShadowRun,
    ShadowScenario,
    SourceCut,
    assess_falsifiers,
    assess_scenario_signs,
    audit_adverse_selection,
    inventory_transfer_regret,
    joint_branch_surplus,
    lvr_like_diagnostic,
    run_shadow_study,
    score_branch,
    terminal_liquidate,
    toxicity_diagnostic,
)
from joshi_analysis.wave6_routed_shadow.accounting import JointBranchSurplus
from joshi_analysis.wave6_routed_shadow.arithmetic import Q64

SOURCE_CUT = SourceCut("cut:10", 10, "profile:v1", "topology:1")


def _empty_run(
    attribution: AdverseSelectionAttribution,
    *,
    scenario_id: str = "diagnostic",
    minimum_margin_atoms: int = 0,
    schedule_id: str = "schedule:none",
    initial_x_atoms: int = 0,
) -> ShadowRun:
    inventory = AssetInventory(initial_x_atoms, 0)
    return ShadowRun(
        scenario=ShadowScenario(
            scenario_id,
            False,
            minimum_margin_atoms,
            ExternalStateTreatment.FIXED_WITNESSED_STATE,
            adverse_selection_attribution=attribution,
        ),
        schedule_id=schedule_id,
        initial_inventory=inventory,
        events=(),
        terminal_inventory=inventory,
    )


def test_terminal_liquidation_is_partial_instead_of_silently_zeroing_a_leg() -> None:
    partial = terminal_liquidate(
        manifest=LiquidationManifest("terminal:H", "H", "profile:v1", "Y", ()),
        inventory=(("X", 100), ("Y", 50)),
    )
    assert partial.status is LiquidationStatus.PARTIAL
    assert partial.total_numeraire_atoms is None
    assert partial.residuals[0].reason == "missing_full_size_quote"

    complete = terminal_liquidate(
        manifest=LiquidationManifest(
            "terminal:H",
            "H",
            "profile:v1",
            "Y",
            (LiquidationQuote("liq:X", "X", 100, "Y", 90, 2),),
        ),
        inventory=(("X", 100), ("Y", 50)),
    )
    assert complete.status is LiquidationStatus.COMPLETE
    assert complete.total_numeraire_atoms == 138


def test_joint_surplus_and_lvr_like_diagnostic_are_terminal_branch_differences() -> None:
    manifest = LiquidationManifest("terminal:H", "H", "profile:v1", "Y", ())
    joint_terminal = terminal_liquidate(
        manifest=manifest,
        inventory=(("Y", 150),),
    )
    alternative_terminal = terminal_liquidate(
        manifest=manifest,
        inventory=(("Y", 140),),
    )
    joint = score_branch("joint", joint_terminal)
    alternative = score_branch("no-edge", alternative_terminal)
    surplus = joint_branch_surplus(joint, alternative)
    assert surplus.surplus_atoms == 10
    assert surplus.claim_scope.endswith("future_expected_value")

    lvr_run = _empty_run(AdverseSelectionAttribution.LVR_LIKE)
    lvr = lvr_like_diagnostic(lvr_run, "grid:v1", joint, alternative)
    assert lvr.value_atoms == -10
    assert "not_accounting_pnl" in lvr.claim_scope


def test_toxicity_and_inventory_regret_retain_direction_unit_and_sign() -> None:
    toxicity = toxicity_diagnostic(
        intent_id="intent:1",
        direction=Direction.X_TO_Y,
        horizon_id="h:+5slots",
        output_asset_id="Y",
        contemporaneous_reference_output_atoms=100,
        horizon_reference_output_atoms=108,
    )
    assert toxicity.toxicity_atoms == 8
    assert toxicity.output_asset_id == "Y"

    itr_run = _empty_run(AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET)
    regret = inventory_transfer_regret(
        itr_run,
        "intent:1",
        "Y",
        principal_output_atoms=97,
        external_alternative_output_atoms=100,
    )
    assert regret.regret_atoms == 3


def test_adverse_selection_attribution_is_required_and_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="explicit adverse-selection attribution"):
        ShadowScenario(
            "invalid-attribution",
            False,
            0,
            ExternalStateTreatment.FIXED_WITNESSED_STATE,
            adverse_selection_attribution="lvr_like",  # type: ignore[arg-type]
        )

    manifest = LiquidationManifest("terminal:H", "H", "profile:v1", "Y", ())
    passive = score_branch(
        "passive", terminal_liquidate(manifest=manifest, inventory=(("Y", 100),))
    )
    rebalanced = score_branch(
        "rebalanced", terminal_liquidate(manifest=manifest, inventory=(("Y", 101),))
    )
    itr_run = _empty_run(AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET)
    itr = inventory_transfer_regret(
        itr_run,
        "intent:1",
        "Y",
        principal_output_atoms=97,
        external_alternative_output_atoms=100,
    )
    itr_audit = audit_adverse_selection(itr_run, itr=itr)
    assert itr_audit.inventory_transfer_regret == itr
    assert itr_audit.scenario_content_digest == itr_run.scenario.content_digest
    assert itr_audit.run_registration_digest == itr_run.registration_digest
    with pytest.raises(ValueError, match="requires exactly one ITR"):
        audit_adverse_selection(itr_run)
    with pytest.raises(ValueError, match="did not freeze LVR-like"):
        lvr_like_diagnostic(itr_run, "grid:v1", passive, rebalanced)

    lvr_run = _empty_run(AdverseSelectionAttribution.LVR_LIKE)
    lvr = lvr_like_diagnostic(lvr_run, "grid:v1", passive, rebalanced)
    assert audit_adverse_selection(lvr_run, lvr=lvr).lvr_like == lvr
    with pytest.raises(ValueError, match="did not freeze inventory-transfer"):
        inventory_transfer_regret(
            lvr_run,
            "intent:1",
            "Y",
            principal_output_atoms=97,
            external_alternative_output_atoms=100,
        )
    with pytest.raises(ValueError, match="requires exactly one LVR"):
        audit_adverse_selection(lvr_run)

    none_run = _empty_run(AdverseSelectionAttribution.NONE)
    assert audit_adverse_selection(none_run).attribution is AdverseSelectionAttribution.NONE
    with pytest.raises(ValueError, match="no-attribution"):
        audit_adverse_selection(none_run, itr=itr)

    same_label_other_run = _empty_run(
        AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET,
        schedule_id="schedule:other",
    )
    assert same_label_other_run.scenario.content_digest == itr_run.scenario.content_digest
    assert same_label_other_run.registration_digest != itr_run.registration_digest
    with pytest.raises(ValueError, match="different registered run"):
        audit_adverse_selection(same_label_other_run, itr=itr)

    same_label_other_policy = _empty_run(
        AdverseSelectionAttribution.INVENTORY_TRANSFER_REGRET,
        minimum_margin_atoms=1,
    )
    assert same_label_other_policy.scenario.scenario_id == itr_run.scenario.scenario_id
    assert same_label_other_policy.scenario.content_digest != itr_run.scenario.content_digest
    with pytest.raises(ValueError, match="different scenario content"):
        audit_adverse_selection(same_label_other_policy, itr=itr)

    with pytest.raises(TypeError, match="LVR slot requires an exact LVR-like"):
        audit_adverse_selection(itr_run, itr=itr, lvr=itr)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ITR slot requires an exact inventory-transfer"):
        audit_adverse_selection(lvr_run, itr=lvr, lvr=lvr)  # type: ignore[arg-type]


def test_adversarial_falsifiers_detect_rounding_gap_depletion_partial_exit_and_sign_flip() -> None:
    ghost = DlmmBinEdge(
        edge_id="ghost",
        schedule_id="schedule:falsifier",
        state_id="state:0",
        asset_x="X",
        asset_y="Y",
        active_bin_id=0,
        fee_policy=DlmmFeePolicy(0, 0),
        bins=(FixedBin(0, Q64, 0, 1),),
        source_cut=SOURCE_CUT,
    )
    witness = JupiterWitness(
        "jupiter:partial",
        SOURCE_CUT.slot,
        SOURCE_CUT,
        (),
        (),
        False,
        Coverage.OBSERVED_PARTIAL,
    )
    intents = tuple(
        QuoteIntent(
            f"intent:{sequence}",
            sequence,
            Direction.X_TO_Y,
            1,
            FlowOrigin.EXTERNAL,
            witness,
        )
        for sequence in (1, 2)
    )
    run = run_shadow_study(
        ghost=ghost,
        baselines=(),
        intents=intents,
        scenario=ShadowScenario(
            "adversarial", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE
        ),
    )
    terminal = terminal_liquidate(
        manifest=LiquidationManifest("terminal:H", "H", "profile:v1", "Y", ()),
        inventory=(("X", 1),),
    )
    report = assess_falsifiers(run, terminal, economically_relevant_min_input_atoms=10)
    assert set(report.triggered) == {
        Falsifier.INCOMPLETE_ROUTE_UNIVERSE,
        Falsifier.TERMINAL_LIQUIDATION_PARTIAL,
    }

    complete_witness = JupiterWitness(
        "jupiter:complete",
        SOURCE_CUT.slot,
        SOURCE_CUT,
        ("control",),
        ("control",),
        True,
        Coverage.OBSERVED_COMPLETE,
    )
    complete_intents = tuple(
        QuoteIntent(
            f"complete:{sequence}",
            sequence,
            Direction.X_TO_Y,
            2,
            FlowOrigin.EXTERNAL,
            complete_witness,
        )
        for sequence in (1, 2)
    )
    complete_run = run_shadow_study(
        ghost=DlmmBinEdge(
            "ghost",
            "schedule:finite",
            "state:finite",
            "X",
            "Y",
            0,
            DlmmFeePolicy(0, 0),
            (FixedBin(0, Q64, 0, 2),),
            SOURCE_CUT,
        ),
        baselines=(ConstantProductEdge("control", "control", "X", "Y", 1_000, 1_000, SOURCE_CUT),),
        intents=complete_intents,
        scenario=ShadowScenario("finite", True, 0, ExternalStateTreatment.COUPLED_COPIED_STATE),
    )
    complete_report = assess_falsifiers(
        complete_run, terminal, economically_relevant_min_input_atoms=10
    )
    assert Falsifier.ROUNDING_ONLY_ACTIVATION in complete_report.triggered
    assert Falsifier.SEQUENTIAL_DEPLETION in complete_report.triggered

    sign_report = assess_scenario_signs(
        (
            JointBranchSurplus("joint", "alt", "Y", 1, None),
            JointBranchSurplus("joint", "alt", "Y", -1, None),
        )
    )
    assert sign_report.triggered == (Falsifier.SCENARIO_SIGN_INSTABILITY,)


def test_terminal_manifest_identity_rejects_duplicates_aliases_and_zero_recovery() -> None:
    with pytest.raises(ValueError, match="occurrence ids must be unique"):
        LiquidationManifest(
            "terminal:duplicate",
            "H",
            "profile:v1",
            "Y",
            (
                LiquidationQuote("same", "X", 10, "Y", 9, 0),
                LiquidationQuote("same", "Z", 10, "Y", 9, 0),
            ),
        )

    zero_manifest = LiquidationManifest(
        "terminal:zero",
        "H",
        "profile:v1",
        "Y",
        (LiquidationQuote("zero", "X", 10, "Y", 0, 0),),
    )
    zero = terminal_liquidate(manifest=zero_manifest, inventory=(("X", 10),))
    assert zero.status is LiquidationStatus.PARTIAL
    assert zero.total_numeraire_atoms is None
    assert zero.residuals[0].reason == "nonpositive_net_output"

    left_manifest = LiquidationManifest(
        "caller-alias",
        "H",
        "profile:v1",
        "Y",
        (LiquidationQuote("left", "X", 10, "Y", 9, 0),),
    )
    right_manifest = LiquidationManifest(
        "caller-alias",
        "H",
        "profile:v1",
        "Y",
        (LiquidationQuote("right", "X", 10, "Y", 8, 0),),
    )
    left = score_branch("left", terminal_liquidate(manifest=left_manifest, inventory=(("X", 10),)))
    right = score_branch(
        "right", terminal_liquidate(manifest=right_manifest, inventory=(("X", 10),))
    )
    assert left.terminal.manifest_id == right.terminal.manifest_id
    assert left.terminal.manifest_content_digest != right.terminal.manifest_content_digest
    with pytest.raises(ValueError, match="byte-identical"):
        joint_branch_surplus(left, right)


def test_one_content_bound_manifest_can_quote_multiple_branch_sizes() -> None:
    manifest = LiquidationManifest(
        "terminal:shared",
        "H",
        "profile:v1",
        "Y",
        (
            LiquidationQuote("x:10", "X", 10, "Y", 9, 0),
            LiquidationQuote("x:20", "X", 20, "Y", 17, 0),
        ),
    )
    smaller = score_branch("smaller", terminal_liquidate(manifest=manifest, inventory=(("X", 10),)))
    larger = score_branch("larger", terminal_liquidate(manifest=manifest, inventory=(("X", 20),)))
    assert smaller.terminal.manifest_content_digest == larger.terminal.manifest_content_digest
    assert joint_branch_surplus(larger, smaller).surplus_atoms == 8
