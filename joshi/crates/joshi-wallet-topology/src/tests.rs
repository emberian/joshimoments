use std::collections::BTreeMap;

use joshi_domain::WireU64;
use serde::Deserialize;

use crate::{
    CoverageBinding, HypothesisStatus, ReducerConfig, SnapshotRequest, TopologyFact, TopologyInput,
    TopologyReducer,
};

const FIXTURE: &str = include_str!("../../../fixtures/wallet-topology/point_in_time.json");

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fixture {
    contract: String,
    input: TopologyInput,
    cases: Vec<FixtureCase>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FixtureCase {
    name: String,
    request: SnapshotRequest,
    expected: Expected,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Expected {
    accepted_fact_count: WireU64,
    excluded_noncanonical_count: WireU64,
    flow_edge_count: WireU64,
    co_trade_joint_occurrences: WireU64,
    current_hypothesis_ids: Vec<String>,
}

fn reducer() -> TopologyReducer {
    TopologyReducer::new(ReducerConfig::new(1_000, 100, 1_000, 100).unwrap())
}

fn fixture() -> Fixture {
    serde_json::from_str(FIXTURE).unwrap()
}

#[test]
fn fixture_has_no_json_number_tokens() {
    let value: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
    assert_no_numbers(&value);
    assert_eq!(fixture().contract, "joshi.wallet_topology.fixture.v1");
}

#[test]
fn point_in_time_cases_match_expected_closure() {
    let fixture = fixture();
    for case in fixture.cases {
        let snapshot = reducer()
            .snapshot(&fixture.input, case.request)
            .unwrap_or_else(|error| panic!("{}: {error}", case.name));
        assert_eq!(
            snapshot.accepted_facts.len(),
            usize::try_from(case.expected.accepted_fact_count.get()).unwrap(),
            "{}",
            case.name
        );
        assert_eq!(
            snapshot.excluded_noncanonical_transaction_ids.len(),
            usize::try_from(case.expected.excluded_noncanonical_count.get()).unwrap(),
            "{}",
            case.name
        );
        assert_eq!(
            snapshot.flow_edges.len(),
            usize::try_from(case.expected.flow_edge_count.get()).unwrap(),
            "{}",
            case.name
        );
        assert_eq!(snapshot.co_trades.len(), 1, "{}", case.name);
        assert_eq!(
            snapshot.co_trades[0].joint_occurrences, case.expected.co_trade_joint_occurrences,
            "{}",
            case.name
        );
        let hypothesis_ids = snapshot
            .current_hypotheses
            .iter()
            .map(|value| value.hypothesis_id.to_string())
            .collect::<Vec<_>>();
        assert_eq!(
            hypothesis_ids, case.expected.current_hypothesis_ids,
            "{}",
            case.name
        );
        assert!(matches!(
            snapshot.coverage_binding,
            CoverageBinding::UnverifiedRequest { .. }
        ));
    }
}

#[test]
fn reorg_correction_removes_dependent_flow_but_retains_observation() {
    let fixture = fixture();
    let mut snapshots = fixture
        .cases
        .into_iter()
        .map(|case| {
            (
                case.name,
                reducer().snapshot(&fixture.input, case.request).unwrap(),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let early = snapshots.remove("before_noncanonical_correction").unwrap();
    let late = snapshots
        .remove("after_noncanonical_and_retraction")
        .unwrap();
    assert!(has_swap(&early.accepted_facts, "swap:reorg"));
    assert!(!has_swap(&late.accepted_facts, "swap:reorg"));
    assert!(late.observed_transaction_versions.iter().any(|value| {
        value.transaction_fact_id.as_str() == "txfact:reorg:v2"
            && value.canonicality.discriminator.as_str() == "noncanonical"
    }));
    assert_eq!(late.observed_transaction_versions.len(), 6);
}

#[test]
fn validity_status_and_retraction_are_not_silently_promoted() {
    let fixture = fixture();
    let early = reducer()
        .snapshot(&fixture.input, fixture.cases[0].request.clone())
        .unwrap();
    assert!(early.current_hypotheses.iter().all(|value| {
        value.hypothesis_id.as_str() != "hyp:cluster:unknown_time:v1"
            && value.hypothesis_id.as_str() != "hyp:cluster:future:v1"
    }));
    let late = reducer()
        .snapshot(&fixture.input, fixture.cases[1].request.clone())
        .unwrap();
    let cluster = late
        .current_hypotheses
        .iter()
        .find(|value| value.hypothesis_series_id.as_str() == "hyp_series:cluster:BC")
        .unwrap();
    assert_eq!(cluster.status, HypothesisStatus::Retracted);
}

#[test]
fn oriented_incidence_columns_conserve_each_edge() {
    let fixture = fixture();
    let snapshot = reducer()
        .snapshot(&fixture.input, fixture.cases[0].request.clone())
        .unwrap();
    for edge in &snapshot.flow_edges {
        let rows = snapshot
            .incidence
            .iter()
            .filter(|row| row.edge_id == edge.edge_id)
            .collect::<Vec<_>>();
        assert_eq!(rows.len(), 2);
        assert_ne!(rows[0].sign, rows[1].sign);
        assert_eq!(rows[0].atoms, rows[1].atoms);
        assert_eq!(rows[0].asset_id, rows[1].asset_id);
    }
    assert_eq!(snapshot.cycle_inputs.len(), 1);
    assert!(snapshot.cycle_inputs[0].path_is_contiguous);
    assert!(snapshot.cycle_inputs[0].is_asset_closed);
}

#[test]
fn inference_without_an_adversarial_alternative_is_rejected() {
    let mut fixture = fixture();
    fixture.input.hypotheses[0].adversarial_alternatives.clear();
    let error = reducer()
        .snapshot(&fixture.input, fixture.cases[0].request.clone())
        .unwrap_err();
    assert!(error.to_string().contains("adversarial alternative"));
}

#[test]
fn snapshot_wire_output_keeps_exact_integers_as_strings() {
    let fixture = fixture();
    let snapshot = reducer()
        .snapshot(&fixture.input, fixture.cases[0].request.clone())
        .unwrap();
    let value = serde_json::to_value(snapshot).unwrap();
    assert_no_numbers(&value);
}

fn has_swap(facts: &[TopologyFact], id: &str) -> bool {
    facts
        .iter()
        .any(|fact| matches!(fact, TopologyFact::Swap(value) if value.swap_id.as_str() == id))
}

fn assert_no_numbers(value: &serde_json::Value) {
    match value {
        serde_json::Value::Number(number) => panic!("JSON number token: {number}"),
        serde_json::Value::Array(values) => values.iter().for_each(assert_no_numbers),
        serde_json::Value::Object(values) => values.values().for_each(assert_no_numbers),
        _ => {}
    }
}
