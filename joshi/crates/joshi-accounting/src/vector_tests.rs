use std::collections::BTreeMap;

use joshi_domain::{WireU64, WireU128};
use proptest::prelude::*;
use serde::{Deserialize, Serialize};

use crate::accounting::{
    AccountingState, CashEpoch, CashMovement, Classification, ClassificationProjection,
};
use crate::amount::{
    ArithmeticError, AtomQty, SignedAtoms, TotalAtoms, mul_div_ceil, mul_div_floor,
};
use crate::basis::{Basis, BasisQuality, ExactRatio, RatioWire};
use crate::effect::FinalizedWalletEffect;
use crate::episode::{EpisodeBook, EpisodePhase};
use crate::lots::{BasisEpochRef, CapitalRecovery, Lot, LotAllocation, LotBook};
use crate::model::{AssetKey, BalanceWire, EffectKey, EpisodeKey, LotKey, WalletSnapshot};

const ARITHMETIC_FIXTURE: &str = include_str!("../../../fixtures/accounting/arithmetic.json");
const STATE_FIXTURE: &str = include_str!("../../../fixtures/accounting/state_machine.json");

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArithmeticFile {
    schema_version: String,
    cases: Vec<ArithmeticCase>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ArithmeticCase {
    name: String,
    operation: ArithmeticOperation,
    lhs: WireU64,
    rhs: WireU64,
    denominator: WireU64,
    expected: ArithmeticExpected,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ArithmeticOperation {
    MulDivFloor,
    MulDivCeil,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ArithmeticExpected {
    Value { atoms: WireU64 },
    Error { code: ArithmeticErrorCode },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum ArithmeticErrorCode {
    DivisionByZero,
    Narrowing,
}

#[test]
fn arithmetic_goldens_match_checked_fixed_width_operations() {
    let fixture: ArithmeticFile = serde_json::from_str(ARITHMETIC_FIXTURE).unwrap();
    assert_eq!(fixture.schema_version, "joshi.accounting.arithmetic.v1");
    for case in fixture.cases {
        let result = match case.operation {
            ArithmeticOperation::MulDivFloor => {
                mul_div_floor(case.lhs.get(), case.rhs.get(), case.denominator.get())
            }
            ArithmeticOperation::MulDivCeil => {
                mul_div_ceil(case.lhs.get(), case.rhs.get(), case.denominator.get())
            }
        };
        match case.expected {
            ArithmeticExpected::Value { atoms } => {
                assert_eq!(result, Ok(atoms.get()), "{}", case.name);
            }
            ArithmeticExpected::Error { code } => {
                let actual = match result {
                    Err(ArithmeticError::DivisionByZero) => ArithmeticErrorCode::DivisionByZero,
                    Err(ArithmeticError::Narrowing) => ArithmeticErrorCode::Narrowing,
                    other => panic!("{}: unexpected result {other:?}", case.name),
                };
                assert_eq!(actual, code, "{}", case.name);
            }
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StateFile {
    schema_version: String,
    cases: Vec<StateCase>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StateCase {
    name: String,
    episode_id: Option<String>,
    expected_total_realized: Option<RealizedWire>,
    initial: Vec<BalanceWire>,
    steps: Vec<StateStep>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StateStep {
    effect_id: String,
    after: Vec<BalanceWire>,
    classification: ClassificationWire,
    episode_quantity_after: Option<WireU64>,
    #[serde(default)]
    continue_watching_flat: bool,
    expected: ExpectedWire,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum ClassificationWire {
    Acquisition {
        asset: String,
        quantity_atoms: WireU64,
        lot_id: String,
        basis_asset: String,
        basis_atoms: WireU64,
        epoch_index: WireU64,
        cash_atoms: WireU64,
    },
    Disposal {
        asset: String,
        quantity_atoms: WireU64,
        allocations: Vec<AllocationWire>,
        proceeds_asset: String,
        proceeds_atoms: WireU64,
        epoch_index: WireU64,
        cash_atoms: WireU64,
    },
    ExternalInflowUnknown {
        asset: String,
        quantity_atoms: WireU64,
        lot_id: String,
    },
    ExternalOutflow {
        asset: String,
        quantity_atoms: WireU64,
        allocations: Vec<AllocationWire>,
    },
    CustodyOnly,
    Unclassified,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct AllocationWire {
    lot_id: String,
    quantity_atoms: WireU64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ExpectedWire {
    observed_atoms: WireU128,
    lot_atoms: WireU128,
    basis_quality: BasisQuality,
    basis_asset: Option<String>,
    basis: Option<RatioWire>,
    realized: Option<RealizedWire>,
    capital: Option<CapitalWire>,
    episode_phase: Option<EpisodePhaseWire>,
    epoch_index: Option<WireU64>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RealizedWire {
    asset: String,
    amount: RatioWire,
    quality: BasisQuality,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum EpisodePhaseWire {
    OpenFlat,
    Invested,
    WatchingFlat,
    Closed,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum CapitalWire {
    NoCapitalRecorded,
    NotRecovered { atoms: WireU128 },
    Recovered { atoms: WireU128 },
}

#[test]
fn state_machine_goldens_preserve_ledger_lot_and_episode_meanings() {
    let fixture: StateFile = serde_json::from_str(STATE_FIXTURE).unwrap();
    assert_eq!(fixture.schema_version, "joshi.accounting.state_machine.v1");
    for case in fixture.cases {
        run_state_case(case);
    }
}

fn run_state_case(case: StateCase) {
    let mut current = WalletSnapshot::from_wire(&case.initial).unwrap();
    let mut accounting = AccountingState::from_snapshot(&current).unwrap();
    let episode_id = case
        .episode_id
        .as_deref()
        .map(|value| EpisodeKey::new(value).unwrap());
    let mut episodes = EpisodeBook::default();
    if let Some(id) = &episode_id {
        episodes.begin(id.clone()).unwrap();
    }
    let mut realized_totals: BTreeMap<AssetKey, ExactRatio> = BTreeMap::new();

    for step in case.steps {
        let effect_id = EffectKey::new(&step.effect_id).unwrap();
        let after = WalletSnapshot::from_wire(&step.after).unwrap();
        let effect = FinalizedWalletEffect::between(effect_id.clone(), &current, &after).unwrap();
        let (classification, target_asset, cash_epoch) =
            classification_from_wire(step.classification, episode_id.as_ref());

        accounting.apply_effect(effect).unwrap();
        let projection = accounting.classify(&effect_id, classification).unwrap();
        if let ClassificationProjection::Disposal { realized, .. } = &projection {
            for (asset, component) in realized {
                if let Some(result) = &component.result {
                    realized_totals
                        .entry(asset.clone())
                        .or_insert_with(ExactRatio::zero)
                        .add_assign(result);
                }
            }
        }

        if let (Some(id), Some(quantity)) = (&episode_id, step.episode_quantity_after) {
            episodes
                .get_mut(id)
                .unwrap()
                .observe_inventory(effect_id, AtomQty::new(quantity.get()))
                .unwrap();
        }
        if step.continue_watching_flat {
            episodes
                .get_mut(episode_id.as_ref().unwrap())
                .unwrap()
                .continue_watching_flat()
                .unwrap();
        }

        assert_expected(
            &case.name,
            &step.effect_id,
            &accounting,
            &episodes,
            episode_id.as_ref(),
            &target_asset,
            cash_epoch.as_ref(),
            &projection,
            &step.expected,
        );
        current = after;
    }

    match case.expected_total_realized {
        Some(expected) => {
            let asset = AssetKey::new(expected.asset).unwrap();
            assert_eq!(
                realized_totals.get(&asset),
                Some(&expected.amount.parse().unwrap()),
                "{}: total realized cash identity",
                case.name
            );
        }
        None => assert!(
            realized_totals.is_empty(),
            "{}: unexpected realized result",
            case.name
        ),
    }
}

#[allow(clippy::too_many_lines)]
fn classification_from_wire(
    wire: ClassificationWire,
    episode: Option<&EpisodeKey>,
) -> (Classification, AssetKey, Option<CashEpoch>) {
    match wire {
        ClassificationWire::Acquisition {
            asset,
            quantity_atoms,
            lot_id,
            basis_asset,
            basis_atoms,
            epoch_index,
            cash_atoms,
        } => {
            let asset = AssetKey::new(asset).unwrap();
            let basis_asset = AssetKey::new(basis_asset).unwrap();
            let episode = episode.unwrap().clone();
            let index = u32::try_from(epoch_index.get()).unwrap();
            let cash_epoch = CashEpoch {
                episode: episode.clone(),
                index,
                asset: basis_asset.clone(),
            };
            (
                Classification::Acquisition {
                    asset: asset.clone(),
                    quantity: AtomQty::new(quantity_atoms.get()),
                    lot: LotKey::new(lot_id).unwrap(),
                    basis: Basis::known(basis_asset, AtomQty::new(basis_atoms.get())),
                    epoch: Some(BasisEpochRef { episode, index }),
                    cash_spend: Some(CashMovement {
                        epoch: cash_epoch.clone(),
                        amount: AtomQty::new(cash_atoms.get()),
                    }),
                },
                asset,
                Some(cash_epoch),
            )
        }
        ClassificationWire::Disposal {
            asset,
            quantity_atoms,
            allocations,
            proceeds_asset,
            proceeds_atoms,
            epoch_index,
            cash_atoms,
        } => {
            let asset = AssetKey::new(asset).unwrap();
            let proceeds_asset = AssetKey::new(proceeds_asset).unwrap();
            let cash_epoch = CashEpoch {
                episode: episode.unwrap().clone(),
                index: u32::try_from(epoch_index.get()).unwrap(),
                asset: proceeds_asset.clone(),
            };
            (
                Classification::Disposal {
                    asset: asset.clone(),
                    quantity: AtomQty::new(quantity_atoms.get()),
                    allocations: allocations
                        .into_iter()
                        .map(|slice| LotAllocation {
                            lot: LotKey::new(slice.lot_id).unwrap(),
                            quantity: AtomQty::new(slice.quantity_atoms.get()),
                        })
                        .collect(),
                    net_proceeds: BTreeMap::from([(
                        proceeds_asset,
                        AtomQty::new(proceeds_atoms.get()),
                    )]),
                    cash_return: Some(CashMovement {
                        epoch: cash_epoch.clone(),
                        amount: AtomQty::new(cash_atoms.get()),
                    }),
                },
                asset,
                Some(cash_epoch),
            )
        }
        ClassificationWire::ExternalInflowUnknown {
            asset,
            quantity_atoms,
            lot_id,
        } => {
            let asset = AssetKey::new(asset).unwrap();
            (
                Classification::ExternalInflowUnknown {
                    asset: asset.clone(),
                    quantity: AtomQty::new(quantity_atoms.get()),
                    lot: LotKey::new(lot_id).unwrap(),
                },
                asset,
                None,
            )
        }
        ClassificationWire::ExternalOutflow {
            asset,
            quantity_atoms,
            allocations,
        } => {
            let asset = AssetKey::new(asset).unwrap();
            (
                Classification::ExternalOutflow {
                    asset: asset.clone(),
                    quantity: AtomQty::new(quantity_atoms.get()),
                    allocations: allocations
                        .into_iter()
                        .map(|slice| LotAllocation {
                            lot: LotKey::new(slice.lot_id).unwrap(),
                            quantity: AtomQty::new(slice.quantity_atoms.get()),
                        })
                        .collect(),
                },
                asset,
                None,
            )
        }
        ClassificationWire::CustodyOnly => (
            Classification::CustodyOnly,
            AssetKey::new("token-c").unwrap(),
            None,
        ),
        ClassificationWire::Unclassified => (
            Classification::Unclassified,
            AssetKey::new("token-d").unwrap(),
            None,
        ),
    }
}

#[allow(clippy::too_many_arguments)]
fn assert_expected(
    case_name: &str,
    step_name: &str,
    accounting: &AccountingState,
    episodes: &EpisodeBook,
    episode_id: Option<&EpisodeKey>,
    target_asset: &AssetKey,
    cash_epoch: Option<&CashEpoch>,
    projection: &ClassificationProjection,
    expected: &ExpectedWire,
) {
    let context = format!("{case_name}/{step_name}");
    assert_eq!(
        accounting.observed_balance(target_asset).get(),
        expected.observed_atoms.get(),
        "{context}: observed balance"
    );
    assert_eq!(
        accounting
            .lots
            .remaining_quantity(target_asset)
            .unwrap()
            .get(),
        expected.lot_atoms.get(),
        "{context}: lot quantity"
    );
    let remaining_basis = accounting.lots.remaining_basis(target_asset);
    assert_eq!(
        remaining_basis.quality, expected.basis_quality,
        "{context}: basis quality"
    );
    match (&expected.basis_asset, &expected.basis) {
        (Some(asset), Some(ratio)) => {
            let asset = AssetKey::new(asset).unwrap();
            assert_eq!(
                remaining_basis
                    .component(&asset)
                    .cloned()
                    .unwrap_or_else(ExactRatio::zero),
                ratio.parse().unwrap(),
                "{context}: remaining basis"
            );
        }
        (None, None) => assert!(
            remaining_basis.known.is_empty(),
            "{context}: unexpected known basis"
        ),
        _ => panic!("{context}: malformed expected basis pair"),
    }

    match (&expected.realized, projection) {
        (Some(expected), ClassificationProjection::Disposal { realized, .. }) => {
            let asset = AssetKey::new(&expected.asset).unwrap();
            let actual = realized.get(&asset).unwrap();
            assert_eq!(
                actual.quality, expected.quality,
                "{context}: realized quality"
            );
            assert_eq!(
                actual.result.as_ref(),
                Some(&expected.amount.parse().unwrap()),
                "{context}: realized result"
            );
        }
        (None, _) => {}
        _ => panic!("{context}: expected realized disposal projection"),
    }

    match (&expected.capital, cash_epoch) {
        (Some(expected), Some(epoch)) => {
            let actual = accounting.capital_recovery(epoch).unwrap();
            match (expected, actual) {
                (CapitalWire::NoCapitalRecorded, CapitalRecovery::NoCapitalRecorded) => {}
                (
                    CapitalWire::NotRecovered { atoms },
                    CapitalRecovery::NotRecovered { shortfall },
                ) => assert_eq!(atoms.get(), shortfall.get(), "{context}: shortfall"),
                (CapitalWire::Recovered { atoms }, CapitalRecovery::Recovered { excess }) => {
                    assert_eq!(atoms.get(), excess.get(), "{context}: recovered excess");
                }
                pair => panic!("{context}: capital mismatch {pair:?}"),
            }
        }
        (None, None) => {}
        _ => panic!("{context}: capital expectation/key mismatch"),
    }

    match (&expected.episode_phase, episode_id) {
        (Some(expected_phase), Some(id)) => {
            let episode = episodes.get(id).unwrap();
            assert_eq!(
                phase_wire(episode.phase),
                *expected_phase,
                "{context}: episode phase"
            );
            assert_eq!(
                episode.current_epoch_index().map(u64::from),
                expected.epoch_index.map(WireU64::get),
                "{context}: episode epoch"
            );
        }
        (None, None) => {}
        _ => panic!("{context}: episode expectation/id mismatch"),
    }

    let residual = accounting.lot_reconciliation(target_asset).unwrap();
    let expected_residual = SignedAtoms::between(
        TotalAtoms::new(expected.lot_atoms.get()),
        TotalAtoms::new(expected.observed_atoms.get()),
    );
    assert_eq!(residual, expected_residual, "{context}: reconciliation");
}

fn phase_wire(value: EpisodePhase) -> EpisodePhaseWire {
    match value {
        EpisodePhase::OpenFlat => EpisodePhaseWire::OpenFlat,
        EpisodePhase::Invested => EpisodePhaseWire::Invested,
        EpisodePhase::WatchingFlat => EpisodePhaseWire::WatchingFlat,
        EpisodePhase::Closed => EpisodePhaseWire::Closed,
    }
}

#[test]
fn fixture_documents_have_stable_rfc8785_bytes_and_no_json_numbers() {
    for source in [ARITHMETIC_FIXTURE, STATE_FIXTURE] {
        let value: serde_json::Value = serde_json::from_str(source).unwrap();
        assert_has_no_json_number(&value);
        let first = serde_json_canonicalizer::to_vec(&value).unwrap();
        let reparsed: serde_json::Value = serde_json::from_slice(&first).unwrap();
        let second = serde_json_canonicalizer::to_vec(&reparsed).unwrap();
        assert_eq!(first, second);
    }
}

fn assert_has_no_json_number(value: &serde_json::Value) {
    match value {
        serde_json::Value::Number(number) => panic!("JSON numeric token is forbidden: {number}"),
        serde_json::Value::Array(values) => values.iter().for_each(assert_has_no_json_number),
        serde_json::Value::Object(values) => values.values().for_each(assert_has_no_json_number),
        _ => {}
    }
}

proptest! {
    #[test]
    fn proportional_basis_partition_closes_exactly(
        quantity in 2_u64..1_000_000,
        first in 1_u64..999_999,
        basis_atoms in 1_u64..1_000_000,
    ) {
        let first = 1 + (first % (quantity - 1));
        let second = quantity - first;
        let token = AssetKey::new("property-token").unwrap();
        let sol = AssetKey::new("sol").unwrap();
        let lot_id = LotKey::new("property-lot").unwrap();
        let mut book = LotBook::default();
        book.insert(Lot::acquisition(
            lot_id.clone(),
            token.clone(),
            AtomQty::new(quantity),
            Basis::known(sol.clone(), AtomQty::new(basis_atoms)),
            None,
        ).unwrap()).unwrap();

        let first_basis = book.consume(
            &token,
            AtomQty::new(first),
            &[LotAllocation { lot: lot_id.clone(), quantity: AtomQty::new(first) }],
        ).unwrap();
        let second_basis = book.consume(
            &token,
            AtomQty::new(second),
            &[LotAllocation { lot: lot_id, quantity: AtomQty::new(second) }],
        ).unwrap();
        let total = first_basis.merged_with(&second_basis);

        prop_assert_eq!(
            total.component(&sol),
            Some(&ExactRatio::from_u64(basis_atoms))
        );
        prop_assert_eq!(book.remaining_quantity(&token).unwrap(), TotalAtoms::ZERO);
        prop_assert!(book.remaining_basis(&token).is_exact_zero());
    }

    #[test]
    fn floor_and_ceil_differ_by_at_most_one(
        lhs in any::<u32>(),
        rhs in any::<u32>(),
        denominator in 1_u32..=u32::MAX,
    ) {
        let floor = mul_div_floor(u64::from(lhs), u64::from(rhs), u64::from(denominator)).unwrap();
        let ceil = mul_div_ceil(u64::from(lhs), u64::from(rhs), u64::from(denominator)).unwrap();
        prop_assert!(ceil == floor || ceil == floor + 1);
    }
}
