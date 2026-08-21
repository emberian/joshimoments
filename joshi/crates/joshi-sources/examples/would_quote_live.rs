//! One honest would-quote, from a real `PumpSwap` pool, through the durable catalog and back.
//!
//! ```text
//! would_quote_live acquire  --root <dir> [--pool <address>] [--size-bps <n>] [--key-file <path>]
//! would_quote_live readback --root <dir>
//! ```
//!
//! `acquire` reads a real pool at one slot, retains every response as exact bytes through the
//! shared admission path, then **closes the store, reopens it, and computes the quote only from
//! what came back out of the catalog**. The fetched bodies are dropped before the arithmetic runs,
//! because the point of the exercise is that the quote is a function of what was durably retained.
//!
//! `readback` runs in a fresh process against the same catalog and recomputes the same would-quote
//! from the same retained bytes, then proves the rendering is byte-identical to the retained export.
//!
//! This program constructs no transaction, signs nothing, submits nothing, and produces no profit
//! or loss. It reads accounts, retains bytes, and does arithmetic.

use std::{
    error::Error,
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use joshi_accounting::amount::AtomQty;
use joshi_admission::{PublicStoreReceiptV1, SourceFrameInput, source_frames};
use joshi_domain::{
    AssetId, OpenVariant, PoolId, ProtocolProfileId, QuoteId, StableString, UtcTimestamp, VenueId,
    WireU64,
};
use joshi_liquidity::pool_depth::{DepthFractionBps, ObservedPoolDepth};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeePolicy, FeeSchedule, FeeTier},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    pump::PumpSwapState,
    quote::{QuoteRequest, QuoteSize},
    wide::{Rounding, mul_div_u128},
    would_quote::{
        CatalogBinding, ChainSecond, ChainToReceiptAge, DepthProvenance, FeeProvenance,
        KnowledgeCutoff, LocalReceipt, RetainedInput, WouldQuote,
    },
};
use joshi_sources::{
    AccountSetResponse, CredentialFile, EvidenceContext, HeliusConfig, HeliusHttpClient,
    LogicalSourceLocator, PUMP_AMM_PROGRAM_ID, PUMP_FEE_CONFIG_ADDRESS, PUMP_FEE_PROGRAM_ID,
    ProviderEventTime, PumpFeeConfig, PumpSwapPool, RawSourceFrame, RetainedFrameEnvelope,
    SolanaReadMethod, SolanaReadRequest, TokenMint, TokenVault, UnixMillis, read_account_info,
    read_block_clock, read_multiple_accounts,
};
use joshi_store::{DurableSourceObservation, SqliteStore, StoreConfig, StoreMode};
use serde_json::{Value, json};
use time::OffsetDateTime;

const DEFAULT_KEY_PATH: &str = "~/.helius-key";
/// Deeply liquid mainnet `PumpSwap` pool, discovered from a landed swap rather than assumed.
const DEFAULT_POOL: &str = "FnzKY6x7entQ1eR3D225dQyT7ybfka4PskBMQhb8L3CC";
const CATALOG_ID: &str = "joshi-would-quote-s7";
const HELIUS_HTTP_SOURCE: &str = "helius.http.solana.v1";
const COMMITMENT: &str = "finalized";
const INLINE_BLOB_MAX_BYTES: u64 = 4 * 1024 * 1024;
const MAX_OBSERVATIONS_PER_BATCH: usize = 64;
const MAX_RAW_BYTES_PER_BATCH: u64 = 64 * 1024 * 1024;
const BUSY_TIMEOUT: Duration = Duration::from_secs(5);
const DEFAULT_SIZE_BPS: u16 = 25;
const MANIFEST_EXPORT: &str = "would-quote/request-manifest.json";
const JSON_EXPORT: &str = "would-quote/would-quote.json";
const CARD_EXPORT: &str = "would-quote/would-quote.txt";
const VENUE_ID: &str = "pumpswap";
const PROFILE_ID: &str = "joshi.pumpswap.canonical.v1";

/// Roles of the one atomically consistent account read, in the exact order it is requested.
const ROLES: [&str; 6] = [
    "pool",
    "pool_base_token_account",
    "pool_quote_token_account",
    "base_mint",
    "quote_mint",
    "pump_fee_config",
];

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let Some(command) = arguments.first() else {
        return Err(usage());
    };
    let root = PathBuf::from(flag(&arguments, "--root").ok_or_else(usage)?);
    match command.as_str() {
        "acquire" => {
            let pool = flag(&arguments, "--pool").unwrap_or_else(|| DEFAULT_POOL.to_owned());
            let key_file = PathBuf::from(
                flag(&arguments, "--key-file").unwrap_or_else(|| DEFAULT_KEY_PATH.to_owned()),
            );
            let size_bps = flag(&arguments, "--size-bps")
                .map_or(Ok(DEFAULT_SIZE_BPS), |value| value.parse::<u16>())?;
            println!("{}", acquire(&root, &pool, size_bps, &key_file)?);
        }
        "readback" => println!("{}", readback(&root)?),
        _ => return Err(usage()),
    }
    Ok(())
}

fn usage() -> Box<dyn Error> {
    "usage: would_quote_live <acquire|readback> --root <dir> [--pool <address>] \
     [--size-bps <n>] [--key-file <path>]"
        .into()
}

fn flag(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == name)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

/// One captured provider read and the local clocks that bracket it.
struct CapturedRead {
    frame: RawSourceFrame,
    method: SolanaReadMethod,
    fingerprint_material: String,
    started_at_millis: i64,
    started_mono_ns: u64,
    received_mono_ns: u64,
    chain_slot: Option<u64>,
}

fn acquire(
    root: &Path,
    pool_address: &str,
    size_bps: u16,
    key_file: &Path,
) -> Result<String, Box<dyn Error>> {
    let process_start = Instant::now();
    let namespace = format!(
        "would-quote-s7-{}-{}",
        unix_millis(OffsetDateTime::now_utc())?,
        std::process::id()
    );
    let clock_id = format!("joshi-would-quote-{}", std::process::id());

    // Take the writer lease and reach the current schema before opening a network connection: a
    // read that cannot be durably retained is not evidence, and failing first costs the provider
    // nothing.
    let mut store = SqliteStore::open(catalog_config(root)?, StoreMode::SingleWriter)?;
    store.migrate(now_utc()?)?;

    // Every provider read this program is allowed to make happens here, and the connection is
    // closed before any of the retained bytes are read back.
    let AcquiredReads { reads, addresses } = perform_reads(pool_address, key_file, process_start)?;

    let state_received_mono_ns = reads[1].received_mono_ns;
    let receipt = commit_reads(&mut store, &reads, &namespace, &clock_id, process_start)?;
    // This manifest is this run's own record of what it asked for and which local clock it read
    // on. It states nothing about the world and makes no provider claim; the catalog holds the
    // same clock identity on the acquisition row, and the address list it names is re-derived from
    // the retained pool bytes and refused if it disagrees.
    let manifest = json!({
        "contract": "joshi.would_quote.request_manifest.v1",
        "poolAddress": pool_address,
        "requestedAddresses": addresses,
        "roles": ROLES,
        "commitment": COMMITMENT,
        "sizeBpsOfBaseInventory": size_bps,
        "batchId": receipt.batch_id,
        "batchDigest": receipt.batch_digest.to_string(),
        "storeAdmissionDigest": receipt.store_admission_digest.to_string(),
        "receiptClockId": clock_id,
        "receiptMonotonicNs": state_received_mono_ns,
    });
    let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    store.prepare_export(Path::new(MANIFEST_EXPORT), &manifest_bytes)?;

    // Everything the provider sent is now durable. Drop it all, close the store, and let the
    // arithmetic run only against what the catalog gives back.
    drop(reads);
    drop(store);

    let store = SqliteStore::open(catalog_config(root)?, StoreMode::SingleWriter)?;
    let would_quote = derive_from_catalog(&store, root)?;
    let json = would_quote.render_json();
    let card = would_quote.render_card();
    store.prepare_export(Path::new(JSON_EXPORT), json.as_bytes())?;
    store.prepare_export(Path::new(CARD_EXPORT), card.as_bytes())?;
    drop(store);

    Ok(format!(
        "{card}\ncommit receipt: batch {} status {:?} observations {} through commit {}\nexports: \
         {}\n         {}\n         {}\n",
        receipt.batch_id,
        receipt.status,
        receipt.admitted.observations,
        receipt.through_commit_seq,
        root.join("exports").join(MANIFEST_EXPORT).display(),
        root.join("exports").join(JSON_EXPORT).display(),
        root.join("exports").join(CARD_EXPORT).display(),
    ))
}

/// The four ordered provider reads and the address list the chain itself named for them.
struct AcquiredReads {
    reads: Vec<CapturedRead>,
    addresses: Vec<String>,
}

/// Performs every provider read this program makes, then closes the connection.
///
/// The runtime and client are dropped before returning, so no network connection is alive while
/// the retained bytes are committed or read back out of the catalog.
fn perform_reads(
    pool_address: &str,
    key_file: &Path,
    process_start: Instant,
) -> Result<AcquiredReads, Box<dyn Error>> {
    let helius = HeliusConfig::mainnet(CredentialFile(key_file.to_path_buf()));
    let client = HeliusHttpClient::at_startup(&helius, INLINE_BLOB_MAX_BYTES)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;

    // Read one: learn the pool's own account layout so every other address is named by the chain
    // rather than by this program.
    let discovery = runtime.block_on(perform(
        &client,
        1,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetAccountInfo,
            json!([pool_address, { "encoding": "base64", "commitment": COMMITMENT }]),
        ),
        format!(
            "method=getAccountInfo;address={pool_address};encoding=base64;commitment={COMMITMENT}"
        ),
    ))?;
    accepted(&discovery)?;
    let discovered = read_account_info(&discovery.frame.body, pool_address)?;
    let pool = PumpSwapPool::decode(discovered.require(pool_address)?)?;
    let addresses = requested_addresses(&pool);

    // Read two: every account the quote needs, in one request, so they share one slot. Accounts
    // fetched at materially different slots are an inconsistent state, not a quote.
    let state = runtime.block_on(perform(
        &client,
        2,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetMultipleAccounts,
            json!([addresses, { "encoding": "base64", "commitment": COMMITMENT }]),
        ),
        format!(
            "method=getMultipleAccounts;addresses={};encoding=base64;commitment={COMMITMENT}",
            addresses.join(",")
        ),
    ))?;
    accepted(&state)?;
    let context_slot = read_multiple_accounts(&state.frame.body, &addresses)?.context_slot;

    // Read three: what the chain says the time of that exact slot was.
    let block = runtime.block_on(perform(
        &client,
        3,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetBlock,
            json!([
                context_slot,
                {
                    "encoding": "json",
                    "transactionDetails": "none",
                    "rewards": false,
                    "commitment": COMMITMENT,
                    "maxSupportedTransactionVersion": 0
                }
            ]),
        ),
        format!(
            "method=getBlock;slot={context_slot};transactionDetails=none;commitment={COMMITMENT}"
        ),
    ))?;
    accepted(&block)?;

    // Read four: evidence that this venue is being traded, rather than an assumption that it is.
    let activity = runtime.block_on(perform(
        &client,
        4,
        process_start,
        &SolanaReadRequest::new(
            SolanaReadMethod::GetSignaturesForAddress,
            json!([pool_address, { "limit": 3, "commitment": COMMITMENT }]),
        ),
        format!(
            "method=getSignaturesForAddress;address={pool_address};limit=3;commitment={COMMITMENT}"
        ),
    ))?;
    accepted(&activity)?;

    drop(runtime);
    drop(client);

    Ok(AcquiredReads {
        reads: vec![discovery, state, block, activity],
        addresses,
    })
}

fn readback(root: &Path) -> Result<String, Box<dyn Error>> {
    let store = SqliteStore::open(catalog_config(root)?, StoreMode::ReadOnly)?;
    let would_quote = derive_from_catalog(&store, root)?;
    let json = would_quote.render_json();
    let card = would_quote.render_card();
    let export_root = root.join("exports");
    let retained_json = fs::read(export_root.join(JSON_EXPORT))?;
    let retained_card = fs::read(export_root.join(CARD_EXPORT))?;
    if retained_json != json.as_bytes() {
        return Err("re-derived would-quote JSON differs from the retained export".into());
    }
    if retained_card != card.as_bytes() {
        return Err("re-derived would-quote card differs from the retained export".into());
    }
    let verification = store.verify(joshi_store::VerifyDepth::Quick)?;
    Ok(format!(
        "{card}\nrestart readback: reopened read-only, integrity {}, re-derived {} JSON bytes and \
         {} card bytes from retained payloads, byte-identical to the retained export.\n",
        verification.integrity,
        json.len(),
        card.len(),
    ))
}

#[allow(clippy::too_many_lines)] // One derivation, kept in the order the evidence constrains it.
fn derive_from_catalog(store: &SqliteStore, root: &Path) -> Result<WouldQuote, Box<dyn Error>> {
    let manifest: Value =
        serde_json::from_slice(&fs::read(root.join("exports").join(MANIFEST_EXPORT))?)?;
    let pool_address = manifest["poolAddress"]
        .as_str()
        .ok_or("request manifest states no pool address")?
        .to_owned();
    let size_bps = u16::try_from(
        manifest["sizeBpsOfBaseInventory"]
            .as_u64()
            .ok_or("request manifest states no size")?,
    )?;
    let batch_id = manifest_string(&manifest, "batchId")?;
    let batch_digest = manifest_string(&manifest, "batchDigest")?;
    let store_admission_digest = manifest_string(&manifest, "storeAdmissionDigest")?;
    let receipt_clock_id = manifest_string(&manifest, "receiptClockId")?;
    let receipt_monotonic_ns = manifest["receiptMonotonicNs"]
        .as_u64()
        .ok_or("request manifest states no receipt monotonic reading")?;

    let source_id = joshi_domain::SourceId::new(HELIUS_HTTP_SOURCE)?;
    let stored = store
        .source_observations_as_known(&source_id, None, 64)?
        .ok_or("catalog holds no Helius HTTP observation to read back")?;
    let account_observation = pick(&stored.observations, "helius:http:getMultipleAccounts")?;
    let block_observation = pick(&stored.observations, "helius:http:getBlock")?;
    let activity_observation = pick(&stored.observations, "helius:http:getSignaturesForAddress")?;

    let account_body = provider_body(account_observation)?;
    let block_body = provider_body(block_observation)?;
    let activity_body = provider_body(activity_observation)?;

    // Reconstruct the requested address list from the retained pool bytes alone, then check it
    // against the manifest. A manifest that named the wrong account could not survive this.
    let provisional = read_multiple_accounts(
        &account_body,
        &std::iter::repeat_n(pool_address.clone(), ROLES.len()).collect::<Vec<_>>(),
    )?;
    let pool_bytes = provisional
        .entries
        .first()
        .and_then(|entry| entry.account.as_ref())
        .ok_or("retained account set states no pool account")?;
    let pool = PumpSwapPool::decode(pool_bytes)?;
    let addresses = requested_addresses(&pool);
    let manifest_addresses: Vec<String> = manifest["requestedAddresses"]
        .as_array()
        .ok_or("request manifest states no address list")?
        .iter()
        .filter_map(|value| value.as_str().map(ToOwned::to_owned))
        .collect();
    if addresses != manifest_addresses {
        return Err("retained pool bytes do not name the addresses the manifest recorded".into());
    }

    let accounts: AccountSetResponse = read_multiple_accounts(&account_body, &addresses)?;
    let context_slot = accounts.context_slot;
    let base_vault = TokenVault::decode(accounts.require(&pool.pool_base_token_account)?)?;
    let quote_vault = TokenVault::decode(accounts.require(&pool.pool_quote_token_account)?)?;
    let base_mint = TokenMint::decode(accounts.require(&pool.base_mint)?)?;
    let quote_mint = TokenMint::decode(accounts.require(&pool.quote_mint)?)?;
    let fee_config = PumpFeeConfig::decode(accounts.require(PUMP_FEE_CONFIG_ADDRESS)?)?;
    if base_vault.mint != pool.base_mint || quote_vault.mint != pool.quote_mint {
        return Err("a retained vault does not hold the mint the pool names".into());
    }
    let landed = landed_signature(&activity_body)?;

    let block = read_block_clock(&block_body, context_slot)?;

    let state_observation = observation_id(account_observation)?;
    let base_asset_id = AssetId::new(pool.base_mint.clone())?;
    let quote_asset_id = AssetId::new(pool.quote_mint.clone())?;
    let pool_id = PoolId::new(pool.address.clone())?;

    // joshi-liquidity states the observed inventory and derives the size from it.
    let depth = ObservedPoolDepth {
        pool_id: pool_id.clone(),
        base_asset_id: base_asset_id.clone(),
        quote_asset_id: quote_asset_id.clone(),
        state_observation_id: state_observation.clone(),
        slot: WireU64::new(context_slot),
        base_atoms: AtomQty::new(base_vault.amount),
        raw_quote_atoms: AtomQty::new(quote_vault.amount),
        virtual_quote_reserves: pool.virtual_quote_reserves,
    };
    let effective_quote = depth.effective_quote_atoms()?;
    let size = depth.base_fraction_atoms(DepthFractionBps::new(size_bps)?)?;

    // The fee schedule must be unambiguous in the retained bytes, or there is no quote.
    let market_cap = mul_div_u128(
        effective_quote,
        u128::from(base_mint.supply),
        u128::from(depth.base_atoms.get()),
        Rounding::Down,
    )?;
    let agreed = fee_config.agreed_rates(market_cap)?;
    let creator = if pool.has_coin_creator() {
        CreatorFee::Charged(FeeBps::new(u16::try_from(agreed.creator)?)?)
    } else {
        CreatorFee::NotApplicable
    };
    let fee_policy = FeePolicy::MarketCapTiers(
        fee_config
            .tier_tables
            .first()
            .ok_or("retained fee configuration carries no tier table")?
            .iter()
            .map(|row| {
                Ok(FeeTier {
                    threshold_quote_atoms: row.threshold_quote_atoms,
                    schedule: FeeSchedule {
                        lp: FeeBps::new(u16::try_from(row.rates.lp)?)?,
                        protocol: FeeBps::new(u16::try_from(row.rates.protocol)?)?,
                        creator: if pool.has_coin_creator() {
                            CreatorFee::Charged(FeeBps::new(u16::try_from(row.rates.creator)?)?)
                        } else {
                            CreatorFee::NotApplicable
                        },
                    },
                })
            })
            .collect::<Result<Vec<_>, Box<dyn Error>>>()?,
    );
    let selected = fee_policy.select(market_cap)?;
    if selected.lp.get() != u16::try_from(agreed.lp)?
        || selected.protocol.get() != u16::try_from(agreed.protocol)?
        || selected.creator != creator
    {
        return Err(
            "the tier the kernel selected is not the schedule every table agrees on".into(),
        );
    }

    let profile = ProtocolProfile {
        id: ProtocolProfileId::new(PROFILE_ID)?,
        venue: VenueId::new(VENUE_ID)?,
        family: ProtocolFamily::PumpSwapCanonical,
        program_identity: StableString::new(PUMP_AMM_PROGRAM_ID)?,
        source_revision: StableString::new(format!(
            "fee-config:{PUMP_FEE_CONFIG_ADDRESS};fee-program:{PUMP_FEE_PROGRAM_ID}"
        ))?,
    };
    let state = PumpSwapState {
        profile: profile.clone(),
        pool_id: pool_id.clone(),
        base_asset_id: base_asset_id.clone(),
        quote_asset_id: quote_asset_id.clone(),
        state_observation_id: state_observation.clone(),
        fee_observation_id: state_observation.clone(),
        slot: WireU64::new(context_slot),
        // Supported by the retained signature page: a transaction naming this pool landed without
        // error at slot `landed.slot`. That is evidence the venue was being traded. It is not a
        // claim that any future swap would be accepted.
        lifecycle: VenueLifecycle::Trading,
        base_reserves: depth.base_atoms,
        raw_quote_reserves: depth.raw_quote_atoms,
        virtual_quote_reserves: pool.virtual_quote_reserves,
        base_mint_supply: AtomQty::new(base_mint.supply),
        fee_policy,
    };
    let request = QuoteRequest {
        quote_id: QuoteId::new(format!("would-quote-{}-{}", pool.address, context_slot))?,
        intent_command_id: None,
        intended_state_observation: Some(state_observation.clone()),
        expected_profile_id: profile.id.clone(),
        venue_id: profile.venue.clone(),
        pool_id,
        base_asset_id,
        quote_asset_id,
        size: QuoteSize::ExactBaseOutBuy(size),
    };
    let calculation = state.calculate(&request);

    let receipt = LocalReceipt {
        clock_id: receipt_clock_id,
        monotonic_ns: receipt_monotonic_ns,
        wall_unix_ms: received_wall_ms(account_observation)?,
    };
    let chain = ChainSecond {
        slot: context_slot,
        block_time_unix_s: block.block_time_unix_s,
    };
    let would_quote = WouldQuote {
        venue: format!("{VENUE_ID} ({PUMP_AMM_PROGRAM_ID})"),
        pool_address: pool.address.clone(),
        base_mint: pool.base_mint.clone(),
        quote_mint: pool.quote_mint.clone(),
        calculation,
        cutoff: KnowledgeCutoff {
            context_slot,
            requested_commitment: COMMITMENT.to_owned(),
            chain,
            block_height: block.block_height,
            blockhash: block.blockhash.clone(),
        },
        age: ChainToReceiptAge::measure(chain, &receipt)?,
        receipt,
        inputs: vec![
            retained_input("pool_and_vault_accounts", account_observation)?,
            retained_input("chain_block_clock", block_observation)?,
            retained_input(
                &format!(
                    "venue_activity(last landed {} at slot {})",
                    landed.0, landed.1
                ),
                activity_observation,
            )?,
        ],
        fees: FeeProvenance {
            fee_config_address: fee_config.address.clone(),
            owner_program: PUMP_FEE_PROGRAM_ID.to_owned(),
            discriminator_account_name: "FeeConfig".to_owned(),
            tier_table_count: fee_config.tier_tables.len(),
            resolution: format!(
                "every one of the {} retained tier tables selects this schedule at market cap {} \
                 quote atoms; where they disagree this program refuses rather than choosing",
                fee_config.tier_tables.len(),
                market_cap
            ),
            schedule: selected,
        },
        depth: DepthProvenance {
            base_vault_atoms: depth.base_atoms.get(),
            raw_quote_vault_atoms: depth.raw_quote_atoms.get(),
            effective_quote_atoms: effective_quote,
            base_mint_supply_atoms: base_mint.supply,
            base_decimals: base_mint.decimals,
            quote_decimals: quote_mint.decimals,
            market_cap_quote_atoms: market_cap,
            size_bps_of_base_inventory: size_bps,
        },
        catalog: CatalogBinding {
            catalog_schema: store.catalog_schema()?.to_string(),
            batch_id,
            batch_digest,
            store_admission_digest,
            through_commit_seq: stored.through_commit_seq.get().to_string(),
        },
    };
    Ok(would_quote)
}

fn manifest_string(manifest: &Value, key: &'static str) -> Result<String, Box<dyn Error>> {
    Ok(manifest[key]
        .as_str()
        .ok_or_else(|| format!("request manifest states no {key}"))?
        .to_owned())
}

fn requested_addresses(pool: &PumpSwapPool) -> Vec<String> {
    vec![
        pool.address.clone(),
        pool.pool_base_token_account.clone(),
        pool.pool_quote_token_account.clone(),
        pool.base_mint.clone(),
        pool.quote_mint.clone(),
        PUMP_FEE_CONFIG_ADDRESS.to_owned(),
    ]
}

fn pick<'a>(
    observations: &'a [DurableSourceObservation],
    locator: &str,
) -> Result<&'a DurableSourceObservation, Box<dyn Error>> {
    observations
        .iter()
        .rev()
        .find(|observation| observation.source_locator_redacted.as_deref() == Some(locator))
        .ok_or_else(|| format!("catalog holds no retained {locator} observation").into())
}

fn provider_body(observation: &DurableSourceObservation) -> Result<Vec<u8>, Box<dyn Error>> {
    let envelope: RetainedFrameEnvelope = serde_json::from_slice(&observation.payload)?;
    Ok(envelope.body)
}

fn observation_id(
    observation: &DurableSourceObservation,
) -> Result<joshi_domain::ObservationId, Box<dyn Error>> {
    Ok(joshi_domain::ObservationId::new(
        observation.observation_id.as_str(),
    )?)
}

fn received_wall_ms(observation: &DurableSourceObservation) -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(
        observation.received_at.as_datetime().unix_timestamp_nanos() / 1_000_000,
    )?)
}

fn retained_input(
    role: &str,
    observation: &DurableSourceObservation,
) -> Result<RetainedInput, Box<dyn Error>> {
    let body = provider_body(observation)?;
    Ok(RetainedInput {
        role: role.to_owned(),
        observation_id: observation_id(observation)?,
        payload_digest: format!("sha256:{}", hex_digest(&observation.payload)),
        payload_bytes: u64::try_from(observation.payload.len())?,
        provider_body_bytes: u64::try_from(body.len())?,
    })
}

fn hex_digest(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(bytes);
    digest.iter().fold(String::new(), |mut out, byte| {
        use std::fmt::Write as _;
        let _ = write!(out, "{byte:02x}");
        out
    })
}

/// The most recent landed, non-erroring signature this page states for the pool.
fn landed_signature(body: &[u8]) -> Result<(String, u64), Box<dyn Error>> {
    let parsed: Value = serde_json::from_slice(body)?;
    let rows = parsed
        .get("result")
        .and_then(Value::as_array)
        .ok_or("signature page states no result array")?;
    rows.iter()
        .find(|row| row.get("err").is_some_and(Value::is_null))
        .and_then(|row| {
            Some((
                row.get("signature")?.as_str()?.to_owned(),
                row.get("slot")?.as_u64()?,
            ))
        })
        .ok_or_else(|| {
            "the retained signature page states no landed transaction for this pool, so this run \
             will not claim the venue was trading"
                .into()
        })
}

async fn perform(
    client: &HeliusHttpClient,
    sequence: u64,
    process_start: Instant,
    request: &SolanaReadRequest,
    fingerprint_material: String,
) -> Result<CapturedRead, Box<dyn Error>> {
    let method = request.method;
    let started_at_millis = unix_millis(OffsetDateTime::now_utc())?;
    let started_mono_ns = elapsed_nanos(process_start)?;
    let (mut frame, _rate_limit) = client
        .request(request, UnixMillis(started_at_millis), sequence)
        .await?;
    let received_mono_ns = elapsed_nanos(process_start)?;
    frame.received_at = UnixMillis(unix_millis(OffsetDateTime::now_utc())?);
    Ok(CapturedRead {
        frame,
        method,
        fingerprint_material,
        started_at_millis,
        started_mono_ns,
        received_mono_ns,
        chain_slot: None,
    })
}

fn accepted(read: &CapturedRead) -> Result<(), Box<dyn Error>> {
    let method = read.method.as_str();
    if read.frame.http_status != Some(200) {
        return Err(format!(
            "Helius rejected the {method} read with HTTP status {:?}; authenticated URL omitted",
            read.frame.http_status
        )
        .into());
    }
    let parsed: Value = serde_json::from_slice(&read.frame.body)
        .map_err(|_| format!("Helius {method} response body was not JSON"))?;
    if let Some(error) = parsed.get("error") {
        return Err(format!(
            "Helius {method} returned JSON-RPC error code {:?}; message withheld",
            error.get("code").and_then(Value::as_i64)
        )
        .into());
    }
    Ok(())
}

fn commit_reads(
    store: &mut SqliteStore,
    reads: &[CapturedRead],
    namespace: &str,
    clock_id: &str,
    process_start: Instant,
) -> Result<PublicStoreReceiptV1, Box<dyn Error>> {
    let persisted_at = now_utc()?;
    let frames = reads
        .iter()
        .map(|read| {
            Ok(SourceFrameInput {
                frame: read.frame.clone(),
                context: EvidenceContext {
                    occurrence_namespace: namespace.to_owned(),
                    redacted_request_fingerprint_material: read.fingerprint_material.clone(),
                    parent_acquisition_id: None,
                    locator: LogicalSourceLocator::HeliusHttp {
                        method: read.method.as_str(),
                    },
                    source_variant: OpenVariant::known(format!(
                        "solana_rpc_response:{}",
                        read.method.as_str()
                    ))?,
                    source_cursor: None,
                    source_events: Vec::new(),
                    // A `getMultipleAccounts` response states a context slot, not an event clock,
                    // and a signature page spans many slots. No provider event time is claimed.
                    provider_event_time: ProviderEventTime::Missing {
                        reason: "this read states a context slot, not a provider event clock"
                            .to_owned(),
                    },
                    chain_slot: read.chain_slot,
                    transaction_index: None,
                    instruction_path: Vec::new(),
                    log_index: None,
                    finality: None,
                    acquisition_started_at: utc_from_millis(read.started_at_millis)?,
                    requested_at: Some(utc_from_millis(read.started_at_millis)?),
                    monotonic_clock_id: clock_id.to_owned(),
                    acquisition_started_monotonic_ns: read.started_mono_ns,
                    received_monotonic_ns: read.received_mono_ns,
                    persisted_at,
                },
            })
        })
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
    let batch = source_frames(
        frames,
        Vec::new(),
        Vec::new(),
        StableString::new(format!("batch-{namespace}"))?,
        now_utc()?,
        StableString::new(clock_id)?,
        elapsed_nanos(process_start)?,
    )?;
    Ok(batch.commit(store)?)
}

fn catalog_config(root: &Path) -> Result<StoreConfig, Box<dyn Error>> {
    Ok(StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: INLINE_BLOB_MAX_BYTES,
        busy_timeout: BUSY_TIMEOUT,
        catalog_id: StableString::new(CATALOG_ID)?,
        max_observations_per_batch: MAX_OBSERVATIONS_PER_BATCH,
        max_raw_bytes_per_batch: MAX_RAW_BYTES_PER_BATCH,
    })
}

fn now_utc() -> Result<UtcTimestamp, Box<dyn Error>> {
    let value = OffsetDateTime::now_utc();
    let nanosecond = value.nanosecond();
    Ok(UtcTimestamp::new(
        value.replace_nanosecond(nanosecond - nanosecond % 1_000)?,
    )?)
}

fn unix_millis(value: OffsetDateTime) -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(value.unix_timestamp_nanos() / 1_000_000)?)
}

fn utc_from_millis(millis: i64) -> Result<UtcTimestamp, Box<dyn Error>> {
    Ok(UtcTimestamp::new(
        OffsetDateTime::from_unix_timestamp_nanos(i128::from(millis) * 1_000_000)?,
    )?)
}

fn elapsed_nanos(process_start: Instant) -> Result<u64, Box<dyn Error>> {
    Ok(u64::try_from(process_start.elapsed().as_nanos())?)
}
