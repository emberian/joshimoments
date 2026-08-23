//! Read-back of retained wallet-sweep bytes into portfolio balance events.
//!
//! The fixture body is the exact retained provider payload of one real, public, finalized
//! mainnet transaction observed by the collector's live wallet sweep. The tests walk the same
//! path the `joshi-portfolio` binary walks: envelope, stored-body normalization, wallet-scoped
//! balance events, statement derivation.

use joshi_accounting::portfolio::{
    AssetRef, CatalogCutoff, ChainContinuity, ObservationRef, OpeningInventory, PortfolioInput,
    PriceStatus, derive_statement,
};
use joshi_domain::{CommitSeq, ObservationId, StableString};
use joshi_sources::{
    ContentType, FrameDirection, RETAINED_FRAME_ENVELOPE_VERSION, RetainedFrameEnvelope,
    StreamClass, Transport,
};
use joshi_wallet_source::{
    AcquisitionResponseContext, AcquisitionSurface, Commitment, PublicKey, StoredLocatorClass,
    balance_events_for_wallet, chain_head_slot, classify_locator, normalize_stored_body,
    parse_retained_envelope, signature_page_entries,
};

const USDC_TRANSACTION: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/portfolio_get_transaction_usdc_finalized.json");
const WALLET: &str = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ";
const USDC_MINT: &str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}

fn envelope_payload(body: &[u8]) -> Vec<u8> {
    serde_json::to_vec(&RetainedFrameEnvelope {
        envelope_version: RETAINED_FRAME_ENVELOPE_VERSION.to_owned(),
        adapter_contract_version: "joshi.sources.v1".to_owned(),
        transport: Transport::Http,
        stream_class: StreamClass::Backfill,
        direction: FrameDirection::Inbound,
        original_content_type: ContentType::Json,
        http_status: Some(200),
        safe_headers: Vec::new(),
        body: body.to_vec(),
    })
    .unwrap()
}

fn response_context(surface: AcquisitionSurface) -> AcquisitionResponseContext {
    AcquisitionResponseContext {
        surface,
        scope_ids: vec![stable("portfolio:test")],
        requested_public_keys: vec![PublicKey::new(WALLET).unwrap()],
        mint_filter: None,
        commitment: Commitment::Confirmed,
        available_at: "2026-08-22T19:44:40.000000Z".parse().unwrap(),
        cursor_before: None,
        coverage_gap_ids: Vec::new(),
        coverage_ids: Vec::new(),
        transaction_versions: Vec::new(),
    }
}

fn observation_ref(id: &str) -> ObservationRef {
    ObservationRef {
        observation_id: ObservationId::new(id).unwrap(),
        commit_seq: CommitSeq::new(1),
    }
}

#[test]
fn locator_classification_names_each_stored_read() {
    assert_eq!(
        classify_locator("helius:http:getTransaction"),
        StoredLocatorClass::WalletSurface(AcquisitionSurface::SolanaGetTransaction)
    );
    assert_eq!(
        classify_locator("helius:http:getSignaturesForAddress"),
        StoredLocatorClass::WalletSurface(AcquisitionSurface::SolanaGetSignaturesForAddress)
    );
    assert_eq!(
        classify_locator("solana_public:http:getSlot"),
        StoredLocatorClass::ChainSlot
    );
    assert_eq!(
        classify_locator("helius:http:getAccountInfo"),
        StoredLocatorClass::AccountRead
    );
    assert_eq!(
        classify_locator("helius:http:somethingElse"),
        StoredLocatorClass::Unrecognized
    );
}

#[test]
fn retained_envelope_round_trips_and_refuses_a_foreign_version() {
    let payload = envelope_payload(USDC_TRANSACTION);
    let envelope = parse_retained_envelope(&payload).unwrap();
    assert_eq!(envelope.body, USDC_TRANSACTION);

    let mut foreign: serde_json::Value = serde_json::from_slice(&payload).unwrap();
    foreign["envelope_version"] = "joshi.raw_source_frame.v999".into();
    let foreign = serde_json::to_vec(&foreign).unwrap();
    assert!(parse_retained_envelope(&foreign).is_err());
}

#[test]
fn stored_transaction_body_yields_only_the_requested_wallets_boundaries() {
    let batch = normalize_stored_body(
        USDC_TRANSACTION,
        ObservationId::new("obs:fixture:usdc").unwrap(),
        &response_context(AcquisitionSurface::SolanaGetTransaction),
    )
    .unwrap();
    assert_eq!(batch.raw_transactions.len(), 1);
    let fact = &batch.raw_transactions[0];

    let wallet = PublicKey::new(WALLET).unwrap();
    let events =
        balance_events_for_wallet(fact, &wallet, &observation_ref("obs:fixture:usdc")).unwrap();
    // Another owner's USDC account also changed in this transaction and must not appear; the
    // wallet's own lamports were unchanged and must not appear either.
    assert_eq!(events.len(), 1);
    let event = &events[0];
    assert_eq!(
        event.asset,
        AssetRef::Token {
            mint: stable(USDC_MINT),
            decimals: 6,
        }
    );
    assert_eq!(
        event.boundary_account,
        Some(stable("3oQR4sTUnbc2muDh3rWnBWrEcUBa67LTkGg2Jvkvdx9w"))
    );
    assert_eq!(event.pre_atoms.get(), 103);
    assert_eq!(event.post_atoms.get(), 203);
    assert_eq!(event.slot.get(), 440_799_662);
    assert_eq!(event.transaction_index.unwrap().get(), 1_086);
    assert_eq!(event.block_time_seconds.unwrap().get(), 1_787_356_844);

    let other = PublicKey::new("2h13CvKfCnb5Etu1E3xRHz93jodqiWK5iZGFM53gFZVi").unwrap();
    let other_events =
        balance_events_for_wallet(fact, &other, &observation_ref("obs:fixture:usdc")).unwrap();
    assert_eq!(other_events.len(), 2);
    assert!(
        other_events
            .iter()
            .any(|event| event.asset == AssetRef::Native)
    );
}

#[test]
fn readback_events_derive_a_statement_with_unobserved_opening_inventory() {
    let batch = normalize_stored_body(
        USDC_TRANSACTION,
        ObservationId::new("obs:fixture:usdc").unwrap(),
        &response_context(AcquisitionSurface::SolanaGetTransaction),
    )
    .unwrap();
    let wallet = PublicKey::new(WALLET).unwrap();
    let events = balance_events_for_wallet(
        &batch.raw_transactions[0],
        &wallet,
        &observation_ref("obs:fixture:usdc"),
    )
    .unwrap();
    let statement = derive_statement(PortfolioInput {
        wallet: wallet.domain_account_id().unwrap(),
        catalog_cutoff: CatalogCutoff {
            commit_seq: CommitSeq::new(1),
            committed_at: "2026-08-22T19:44:40.000000Z".parse().unwrap(),
        },
        balance_events: events,
        prices: Vec::new(),
        positions: Vec::new(),
        provider_assertions: Vec::new(),
        signature_pages: Vec::new(),
        chain_head: None,
        extra_absences: Vec::new(),
        notes: Vec::new(),
    })
    .unwrap();
    assert_eq!(statement.holdings.len(), 1);
    let holding = &statement.holdings[0];
    assert_eq!(holding.total_atoms.get(), 203);
    let boundary = &holding.boundaries[0];
    assert_eq!(
        boundary.derivation.opening,
        OpeningInventory::UnobservedOpening {
            atoms: joshi_domain::WireU64::new(103)
        }
    );
    assert_eq!(boundary.derivation.continuity, ChainContinuity::Contiguous);
    assert!(matches!(holding.price, PriceStatus::Absent { .. }));
}

#[test]
fn signature_page_and_chain_head_read_back_from_plain_bodies() {
    let page = br#"{"jsonrpc":"2.0","result":[
        {"signature":"sigA","slot":10,"err":null,"memo":null,"blockTime":1787000000,
         "confirmationStatus":"finalized"},
        {"signature":"sigB","slot":9,"err":{"InstructionError":[0,"Custom"]},"memo":null,
         "blockTime":1786999999,"confirmationStatus":"finalized"}
    ],"id":1}"#;
    let entries = signature_page_entries(page).unwrap();
    assert_eq!(entries.len(), 2);
    assert_eq!(entries[0].signature, "sigA");
    assert!(!entries[0].failed);
    assert!(entries[1].failed);
    assert_eq!(entries[1].slot, Some(9));

    assert_eq!(
        chain_head_slot(br#"{"jsonrpc":"2.0","result":440993198,"id":1}"#),
        Some(440_993_198)
    );
    assert_eq!(chain_head_slot(b"not json"), None);
}
