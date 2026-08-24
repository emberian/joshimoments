//! What a held coin costs, assembled from one retained account capture and served over loopback.
//!
//! Every number asserted here is a function of the checked-in provider bytes
//! (`fixtures/venue_accounts_m0_capture.json`, wrapping the exact `getMultipleAccounts` response
//! retained at finalized slot 440840124 on 2026-08-22) and nothing else. No network is touched and
//! no clock is read.

use axum::{
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use joshi_core::{
    service::{CoreService, PairingCapability},
    venue_readout::{
        BreakEvenWire, ChainToReceiptWire, DriftWire, FeeTierWire, MountedVenueReadouts,
        NextTierWire, VenueAccountsCapture, VenueReadoutPolicy, venue_readout_wire,
    },
};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_pairing::{PairingConfig, PairingOrigin, PairingScope};
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use std::{path::Path, time::Duration};
use tower::ServiceExt as _;

const CAPTURE: &str = include_str!("fixtures/venue_accounts_m0_capture.json");
/// The live bonding curve Study M0 measured. Its fee floor is 247 basis points.
const CURVE_MINT: &str = "BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump";
/// The graduated pool. Same evening, same operator, sixty basis points.
const POOL_MINT: &str = "gV5pNNAfxLfJ1fX4kKzJGhENMgE9o12H5aUHUgipump";
const ORIGIN: &str = "http://127.0.0.1:4173";

fn capture() -> VenueAccountsCapture {
    serde_json::from_str(CAPTURE).expect("the retained capture parses")
}

fn mount() -> MountedVenueReadouts {
    MountedVenueReadouts::from_capture(&capture(), &VenueReadoutPolicy::study_m0_defaults())
        .expect("the retained bytes assemble")
}

#[test]
fn one_capture_assembles_both_venues_and_binds_each_to_its_own_mint() {
    let mount = mount();
    assert_eq!(mount.context_slot(), 440_840_124);
    assert_eq!(mount.mints(), vec![CURVE_MINT, POOL_MINT]);

    let curve = mount.get(CURVE_MINT).expect("the curve assembles");
    // A curve account never names its mint. The only thing that binds it is the recomputed
    // derivation, and the readout says so rather than implying the account claimed the coin.
    assert!(curve.venue_binding.contains("recomputed PDA"));
    assert!(curve.venue_binding.contains("bump 255"));
    assert!(
        curve
            .venue_binding
            .contains("nothing in the curve account itself names the mint")
    );

    let pool = mount.get(POOL_MINT).expect("the pool assembles");
    assert!(pool.venue_binding.contains("states this base mint itself"));
}

#[test]
fn the_fee_floors_are_the_ones_measured_on_these_two_venues() {
    // 247 basis points on a live curve against 60 on a graduated pool: four times, before depth is
    // considered at all. This is the number that decides whether a coin is worth her attention.
    let mount = mount();
    let curve = venue_readout_wire(mount.get(CURVE_MINT).expect("curve"));
    let pool = venue_readout_wire(mount.get(POOL_MINT).expect("pool"));
    assert_eq!(curve.fee_floor_bps, "247");
    assert_eq!(pool.fee_floor_bps, "60");
    assert_eq!(curve.venue_kind, "Pump bonding curve");
    assert_eq!(pool.venue_kind, "Graduated PumpSwap pool");
    // The probe is a declared input, not a venue fact, so it travels next to what it produced.
    assert_eq!(curve.fee_floor_probe_sol, "0.001000000");
}

#[test]
fn the_break_even_answer_is_an_interval_and_both_ends_reach_the_wire() {
    // With any fixed cost at all the hurdle is U-shaped: below the small end the network fee eats
    // the trade and above the large end the curve does. A single ceiling would be a different and
    // wrong claim, so the wire carries two numbers or a refusal, never one number.
    let mount = mount();
    let curve = venue_readout_wire(mount.get(CURVE_MINT).expect("curve"));
    let BreakEvenWire::Interval {
        smallest_sol,
        largest_sol,
        ..
    } = &curve.break_even_clip
    else {
        panic!("this curve does carry a feasible clip range");
    };
    assert_eq!(smallest_sol, "0.000277945");
    assert_eq!(largest_sol, "0.810409517");
    assert_eq!(curve.declared_lift_bps, "800");

    let pool = venue_readout_wire(mount.get(POOL_MINT).expect("pool"));
    let BreakEvenWire::Interval { largest_sol, .. } = &pool.break_even_clip else {
        panic!("this pool does carry a feasible clip range");
    };
    // Sixty-eight times the curve's clip, from four times on fees and the rest on depth.
    assert_eq!(largest_sol, "55.619167528");
}

#[test]
fn the_tier_row_the_market_cap_selects_reaches_the_wire_with_its_ladder_position() {
    let mount = mount();
    let pool = venue_readout_wire(mount.get(POOL_MINT).expect("pool"));
    let FeeTierWire::Located(row) = &pool.fee_tier else {
        panic!("the retained fee configuration was handed to this readout");
    };
    assert_eq!(row.market_cap_sol, "131533.191745269");
    assert_eq!(row.row_ordinal, "25");
    assert_eq!(row.row_count, "25");
    assert_eq!(row.leg_bps, "30");
    assert!(!row.below_first_threshold);
    // The top row is an answer, not a blank: there is no further threshold to cross.
    let NextTierWire::Absent { absence } = &row.next else {
        panic!("this pool is on the top row of the retained table");
    };
    assert!(absence.contains("top row"));

    // The curve's retained configuration carries exactly one row, which is itself the answer to
    // "which row does this select" and is rendered rather than hidden.
    let curve = venue_readout_wire(mount.get(CURVE_MINT).expect("curve"));
    let FeeTierWire::Located(row) = &curve.fee_tier else {
        panic!("the curve fee configuration was handed to this readout");
    };
    assert_eq!(
        (row.row_ordinal.as_str(), row.row_count.as_str()),
        ("1", "1")
    );
    assert_eq!(row.leg_bps, "125");
}

#[test]
fn state_age_travels_with_every_number_and_an_absent_clock_is_never_a_zero() {
    // The binding uncertainty on all of this is how long ago the state was true, so the age is not
    // optional. This capture's provider stated no blockTime, and that is reported as an absent
    // record rather than as an age of zero.
    let mount = mount();
    let wire = venue_readout_wire(mount.get(POOL_MINT).expect("pool"));
    assert_eq!(wire.state_age.context_slot, "440840124");
    assert_eq!(wire.state_age.requested_commitment, "finalized");
    let ChainToReceiptWire::Absent { absence } = &wire.state_age.chain_to_receipt else {
        panic!("this capture's provider stated no blockTime");
    };
    assert!(absence.contains("absent record rather than an age of zero"));
    // One observation says nothing about drift, and saying nothing is the answer.
    let DriftWire::Absent { absence } = &wire.state_age.drift else {
        panic!("one capture is one observation");
    };
    assert!(absence.contains("Not measured"));
    // The receipt reaches the cockpit as a clock it can keep subtracting from its own, because the
    // age grows for as long as the readout sits on screen unread.
    assert!(
        wire.state_age
            .received_at_unix_ms
            .parse::<i64>()
            .is_ok_and(|value| value > 0)
    );
}

#[test]
fn the_stated_address_list_is_declared_rather_than_evidenced_and_the_wire_says_so() {
    // A getMultipleAccounts body is positional and names no address. Everything decoded here was
    // decoded against a list nothing in the retained bytes can check.
    let mount = mount();
    let wire = venue_readout_wire(mount.get(POOL_MINT).expect("pool"));
    assert!(
        wire.unsupported
            .iter()
            .any(|line| line.contains("the address list is a declaration, not evidence")),
        "{:?}",
        wire.unsupported
    );
    assert!(
        wire.unsupported
            .iter()
            .any(|line| line.contains("pool byte 245")),
    );
    // These tables agree at this market cap, so nothing was chosen and no pessimistic branch is
    // claimed. `None` here means agreement, never that the question went unasked.
    assert_eq!(wire.pessimistic_tier_branch, None);
}

#[test]
fn a_capture_naming_another_contract_is_refused_rather_than_read() {
    let mut capture = capture();
    capture.contract = "joshi.something.else".to_owned();
    let error =
        MountedVenueReadouts::from_capture(&capture, &VenueReadoutPolicy::study_m0_defaults())
            .expect_err("a capture naming another contract must be refused");
    assert!(error.to_string().contains("nothing was read from it"));
}

#[test]
fn an_address_list_that_does_not_match_the_body_is_refused_whole_rather_than_realigned() {
    // The body is positional: value N belongs to address N and nothing in the bytes says so. A
    // list of the wrong length is refused at the door rather than shifted into alignment.
    let mut capture = capture();
    capture
        .requested_addresses
        .retain(|address| address != "ADYwrWVkqojYCCJwR3W5U8gaXw1BUiKYQhFA1pcgo2v1");
    let error =
        MountedVenueReadouts::from_capture(&capture, &VenueReadoutPolicy::study_m0_defaults())
            .expect_err("a list of the wrong length must be refused");
    assert!(
        error
            .to_string()
            .contains("11 account values for 10 addresses")
    );
}

#[test]
fn a_venue_whose_accounts_the_capture_does_not_name_is_reported_unassembled_not_estimated() {
    // A same-length list can still be wrong, and that is precisely why the address list is carried
    // as a declaration. Here the pool's quote vault is mislabelled: the pool account still decodes
    // and names a vault the capture does not carry, so the pool is reported unassembled with a
    // reason rather than priced from the accounts that happen to be readable.
    let mut capture = capture();
    for address in &mut capture.requested_addresses {
        if address == "ADYwrWVkqojYCCJwR3W5U8gaXw1BUiKYQhFA1pcgo2v1" {
            "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf".clone_into(address);
        }
    }
    let mount =
        MountedVenueReadouts::from_capture(&capture, &VenueReadoutPolicy::study_m0_defaults())
            .expect("the curve still assembles");
    assert!(mount.get(POOL_MINT).is_none());
    assert!(mount.get(CURVE_MINT).is_some());
    assert!(
        mount.unassembled().iter().any(|entry| entry
            .reason
            .contains("ADYwrWVkqojYCCJwR3W5U8gaXw1BUiKYQhFA1pcgo2v1")),
        "{:?}",
        mount.unassembled()
    );
}

// -------------------------------------------------------------------------------------------
// The route.
// -------------------------------------------------------------------------------------------

fn store(root: &Path) -> SqliteStore {
    let mut store = SqliteStore::open(
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: StableString::new("venue-readout-test-catalog").expect("catalog id"),
            max_observations_per_batch: 64,
            max_raw_bytes_per_batch: 1024 * 1024,
        },
        StoreMode::SingleWriter,
    )
    .expect("open");
    store
        .migrate(
            "2026-08-22T00:00:00.000000Z"
                .parse::<UtcTimestamp>()
                .expect("clock"),
        )
        .expect("migrate");
    store
}

async fn paired_router(
    root: &Path,
    venues: Option<MountedVenueReadouts>,
) -> (axum::Router, String) {
    let (core, launcher) = CoreService::with_sqlite_pairing_mounting_venues(
        store(root),
        None,
        PairingCapability::generate_os_random().expect("entropy"),
        PairingOrigin::new(ORIGIN.to_owned()).expect("origin"),
        PairingConfig::default(),
        None,
        venues,
        None,
    )
    .expect("paired service");
    let issued = launcher
        .issue_code(vec![PairingScope::CockpitRead])
        .expect("one-time code");
    let app = core.router();
    let exchange = Request::builder()
        .method("POST")
        .uri("/api/v1/pairing/exchange")
        .header("content-type", "application/json")
        .header("host", "127.0.0.1:4173")
        .header("origin", ORIGIN)
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .body(Body::from(
            serde_json::json!({
                "contract": "joshi.pairing.exchange",
                "schemaVersion": 1,
                "oneTimeCode": issued.code.as_str(),
            })
            .to_string(),
        ))
        .expect("exchange request");
    let response = app.clone().oneshot(exchange).await.expect("exchange");
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), 64 * 1024)
        .await
        .expect("exchange body");
    let parsed: serde_json::Value = serde_json::from_slice(&body).expect("exchange json");
    let capability = parsed["capability"]
        .as_str()
        .expect("capability")
        .to_owned();
    (app, capability)
}

fn read(uri: &str, capability: &str) -> Request<Body> {
    Request::builder()
        .method("GET")
        .uri(uri)
        .header("host", "127.0.0.1:4173")
        .header("origin", ORIGIN)
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .header("x-joshi-pairing-token", capability)
        .body(Body::empty())
        .expect("read request")
}

async fn json_of(app: &axum::Router, request: Request<Body>) -> (StatusCode, serde_json::Value) {
    let response = app.clone().oneshot(request).await.expect("route");
    let status = response.status();
    let body = to_bytes(response.into_body(), 4 * 1024 * 1024)
        .await
        .expect("body");
    (status, serde_json::from_slice(&body).expect("json"))
}

#[tokio::test]
async fn the_paired_route_serves_one_held_mints_readout_and_nothing_else() {
    let root = tempfile::tempdir().expect("state");
    let (app, capability) = paired_router(root.path(), Some(mount())).await;
    let (status, body) = json_of(
        &app,
        read(
            &format!("/api/v1/glass/venue-readouts/{CURVE_MINT}"),
            &capability,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["contract"], "joshi.glass.venue_readout");
    assert_eq!(body["schemaVersion"], 1);
    assert_eq!(body["authority"], "read_record_replay_only");
    assert_eq!(body["mint"], CURVE_MINT);
    assert_eq!(body["feeFloorBps"], "247");
    assert_eq!(body["breakEvenClip"]["smallestSol"], "0.000277945");
    assert_eq!(body["breakEvenClip"]["largestSol"], "0.810409517");
    assert_eq!(body["feeTier"]["legBps"], "125");
    assert_eq!(body["stateAge"]["contextSlot"], "440840124");
    assert_eq!(body["stateAge"]["requestedCommitment"], "finalized");
}

#[tokio::test]
async fn an_unpaired_read_is_refused_before_any_number_is_served() {
    let root = tempfile::tempdir().expect("state");
    let (app, _) = paired_router(root.path(), Some(mount())).await;
    let unpaired = Request::builder()
        .method("GET")
        .uri(format!("/api/v1/glass/venue-readouts/{CURVE_MINT}"))
        .header("host", "127.0.0.1:4173")
        .header("origin", ORIGIN)
        .header("sec-fetch-site", "same-origin")
        .header("sec-fetch-mode", "cors")
        .header("sec-fetch-dest", "empty")
        .body(Body::empty())
        .expect("unpaired request");
    let (status, body) = json_of(&app, unpaired).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(body["code"], "pairing_required");
}

#[tokio::test]
async fn nothing_mounted_and_this_coin_not_covered_are_different_answers() {
    // A cockpit that collapsed these would render "we have not measured this coin" over what is
    // really "nothing has been measured at all", which are different things to know at 3am.
    let empty_root = tempfile::tempdir().expect("state");
    let (empty, capability) = paired_router(empty_root.path(), None).await;
    let (status, body) = json_of(
        &empty,
        read(
            &format!("/api/v1/glass/venue-readouts/{CURVE_MINT}"),
            &capability,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["code"], "venue_readouts_not_mounted");

    let mounted_root = tempfile::tempdir().expect("state");
    let (mounted, capability) = paired_router(mounted_root.path(), Some(mount())).await;
    let (status, body) = json_of(
        &mounted,
        read(
            "/api/v1/glass/venue-readouts/So11111111111111111111111111111111111111112",
            &capability,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["code"], "venue_readout_not_measured");
}
