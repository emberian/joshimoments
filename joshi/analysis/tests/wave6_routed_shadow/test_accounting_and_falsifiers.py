from __future__ import annotations

from joshi_analysis.wave6_routed_shadow import (
    Coverage,
    Direction,
    DlmmBinEdge,
    DlmmFeePolicy,
    ExternalStateTreatment,
    Falsifier,
    FixedBin,
    FlowOrigin,
    JupiterWitness,
    LiquidationQuote,
    LiquidationStatus,
    QuoteIntent,
    ShadowScenario,
    assess_falsifiers,
    assess_scenario_signs,
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


def test_terminal_liquidation_is_partial_instead_of_silently_zeroing_a_leg() -> None:
    partial = terminal_liquidate(
        manifest_id="terminal:H",
        numeraire_id="Y",
        inventory=(("X", 100), ("Y", 50)),
        quotes=(),
    )
    assert partial.status is LiquidationStatus.PARTIAL
    assert partial.total_numeraire_atoms is None
    assert partial.residuals[0].reason == "missing_full_size_quote"

    complete = terminal_liquidate(
        manifest_id="terminal:H",
        numeraire_id="Y",
        inventory=(("X", 100), ("Y", 50)),
        quotes=(LiquidationQuote("liq:X", "X", 100, "Y", 90, 2),),
    )
    assert complete.status is LiquidationStatus.COMPLETE
    assert complete.total_numeraire_atoms == 138


def test_joint_surplus_and_lvr_like_diagnostic_are_terminal_branch_differences() -> None:
    joint_terminal = terminal_liquidate(
        manifest_id="terminal:H",
        numeraire_id="Y",
        inventory=(("Y", 150),),
        quotes=(),
    )
    alternative_terminal = terminal_liquidate(
        manifest_id="terminal:H",
        numeraire_id="Y",
        inventory=(("Y", 140),),
        quotes=(),
    )
    joint = score_branch("joint", joint_terminal)
    alternative = score_branch("no-edge", alternative_terminal)
    surplus = joint_branch_surplus(joint, alternative)
    assert surplus.surplus_atoms == 10
    assert surplus.claim_scope.endswith("future_expected_value")

    lvr = lvr_like_diagnostic("grid:v1", joint, alternative)
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

    regret = inventory_transfer_regret(
        "intent:1", "Y", principal_output_atoms=97, external_alternative_output_atoms=100
    )
    assert regret.regret_atoms == 3


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
    )
    witness = JupiterWitness(
        "jupiter:partial",
        10,
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
        manifest_id="terminal:H",
        numeraire_id="Y",
        inventory=(("X", 1),),
        quotes=(),
    )
    report = assess_falsifiers(run, terminal, economically_relevant_min_input_atoms=10)
    assert set(report.triggered) == {
        Falsifier.INCOMPLETE_ROUTE_UNIVERSE,
        Falsifier.ROUNDING_ONLY_ACTIVATION,
        Falsifier.SEQUENTIAL_DEPLETION,
        Falsifier.TERMINAL_LIQUIDATION_PARTIAL,
    }

    sign_report = assess_scenario_signs(
        (
            JointBranchSurplus("joint", "alt", "Y", 1, None),
            JointBranchSurplus("joint", "alt", "Y", -1, None),
        )
    )
    assert sign_report.triggered == (Falsifier.SCENARIO_SIGN_INSTABILITY,)
