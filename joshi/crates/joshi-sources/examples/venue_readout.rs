//! What one coin's live state costs, read before anything is committed.
//!
//! ```text
//! venue_readout --mint <address> [--mint <address> ...]
//!               [--lift-bps 800] [--clip-sol 0.25] [--drift-window-seconds 20]
//!               [--network-fee-lamports 7422] [--rent-lamports 0]
//!               [--max-requests 16] [--key-file ~/.helius-key]
//! ```
//!
//! For each mint this answers three questions Study M0 showed dominate everything else: **which
//! venue is this coin actually on**, **what is the fee floor there**, and **how big a clip can this
//! depth carry before a stated move stops paying for it**. On M0's evening the answers differed by
//! about fifty times between a live bonding curve and a graduated pool holding the same kind of
//! coin, and every input was readable from account bytes at one slot.
//!
//! Where each number comes from:
//!
//! * **The venue account is derived, not looked up.** A bonding curve never names its mint, so an
//!   address from any index is a candidate. This recomputes `PDA(["bonding-curve", mint])` and asks
//!   the provider about the top few bumps in the read it was making anyway, keeping whichever one
//!   exists, is owned by the Pump program, and carries the recomputed `BondingCurve` discriminator.
//!   A graduated pool is discovered with an owner-and-layout-filtered `getProgramAccounts`, then
//!   re-read in the atomic state call and checked against its own mint and its own derivation.
//! * **Fees come from the fee program.** Never the bonding-curve `Global` account, which declared 5
//!   basis points of creator fee while the fee program applied 30, and never any frontend index.
//!   The `Global` disagreement is checked on every curve and printed.
//! * **Reserves come from the accounts.** For a pool that is the two vault balances plus the term
//!   at pool byte 245, which is load-bearing and unnamed; omitting it flatters base-out by 119
//!   basis points.
//! * **Nothing comes from `frontend-api-v3.pump.fun`.** This program never contacts it. M0 measured
//!   that index reporting live reserves off by 158 times.
//!
//! Every account read is one `getMultipleAccounts` at `finalized`, so the accounts in a readout
//! share a slot. The optional drift probe takes a second such read after a declared window and
//! reports how far the marginal price actually moved, because the binding uncertainty on all of
//! this is state age rather than quote error.
//!
//! This program constructs no transaction, signs nothing, simulates nothing, and submits nothing.

use core::fmt::Write as _;
use std::{
    error::Error,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use joshi_liquidity::{
    readout::{
        FeeRateSource, MeasuredDrift, PreTradeReadout, QuoteReserveComposition, ReadoutRequest,
        StateAge, VenueKind,
    },
    round_trip::DeclaredFixedCosts,
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::ExactCurveState,
    wide::{Rounding, mul_div_u128},
    would_quote::{ChainSecond, LocalReceipt},
};
use joshi_sources::{
    AccountSetResponse, CredentialFile, FeeRatesBps, HeliusConfig, HeliusHttpClient,
    PUMP_AMM_PROGRAM_ID, PUMP_BONDING_CURVE_PROGRAM_ID, PUMP_CURVE_FEE_CONFIG_ADDRESS,
    PUMP_FEE_CONFIG_ADDRESS, PUMP_GLOBAL_ADDRESS, PumpBondingCurve, PumpFeeConfig, PumpGlobal,
    PumpSwapPool, RetainedAccount, SolanaReadMethod, SolanaReadRequest, TokenMint, TokenVault,
    UnixMillis, WRAPPED_SOL_MINT, bonding_curve_candidates, fee_config_derivation_bump,
    global_derivation_bump, read_block_clock, read_multiple_accounts,
};
use serde_json::{Value, json};
use time::OffsetDateTime;

const DEFAULT_KEY_PATH: &str = "~/.helius-key";
const COMMITMENT: &str = "finalized";
const RESPONSE_CEILING_BYTES: u64 = 8 * 1024 * 1024;
/// How many descending bumps of the bonding-curve derivation to ask about. Each one that is on the
/// ed25519 curve is not a usable program address, and this crate cannot tell which offline.
const CURVE_BUMP_CANDIDATES: u8 = 5;
/// Network fee observed on a landed `PumpSwap` sell in Study M0's fixture, 2026-08-21.
const DEFAULT_NETWORK_FEE_LAMPORTS: u128 = 7_422;
const DEFAULT_LIFT_BPS: u128 = 800;
const DEFAULT_CLIP_LAMPORTS: u128 = 250_000_000;
const DEFAULT_DRIFT_WINDOW_SECONDS: u64 = 20;
const DEFAULT_MAX_REQUESTS: u32 = 16;
const LAMPORTS_PER_SOL: u128 = 1_000_000_000;

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let mints = repeated(&arguments, "--mint");
    if mints.is_empty() {
        return Err(usage());
    }
    let options = Options {
        lift_bps: parse(&arguments, "--lift-bps", DEFAULT_LIFT_BPS)?,
        clip_lamports: flag(&arguments, "--clip-sol")
            .map(|value| parse_sol(&value))
            .transpose()?
            .unwrap_or(DEFAULT_CLIP_LAMPORTS),
        drift_window: Duration::from_secs(parse(
            &arguments,
            "--drift-window-seconds",
            DEFAULT_DRIFT_WINDOW_SECONDS,
        )?),
        network_fee_lamports: parse(
            &arguments,
            "--network-fee-lamports",
            DEFAULT_NETWORK_FEE_LAMPORTS,
        )?,
        rent_lamports: parse(&arguments, "--rent-lamports", 0)?,
        max_requests: parse(&arguments, "--max-requests", DEFAULT_MAX_REQUESTS)?,
        key_file: PathBuf::from(
            flag(&arguments, "--key-file").unwrap_or_else(|| DEFAULT_KEY_PATH.to_owned()),
        ),
        write_capture: flag(&arguments, "--write-capture").map(PathBuf::from),
    };
    print!("{}", run(&mints, &options)?);
    Ok(())
}

fn usage() -> Box<dyn Error> {
    "usage: venue_readout --mint <address> [--mint <address> ...] [--lift-bps <n>] \
     [--clip-sol <decimal>] [--drift-window-seconds <n>] [--network-fee-lamports <n>] \
     [--rent-lamports <n>] [--max-requests <n>] [--key-file <path>] [--write-capture <path>]"
        .into()
}

struct Options {
    lift_bps: u128,
    clip_lamports: u128,
    drift_window: Duration,
    network_fee_lamports: u128,
    rent_lamports: u128,
    max_requests: u32,
    key_file: PathBuf,
    /// Where to retain the exact state-read response, if anywhere.
    ///
    /// A JSON-RPC account response is POSITIONAL: it names no address, and the address list lives
    /// in the request, which is not retained. So a capture must carry the three things the body
    /// cannot state -- the addresses asked for, the commitment asked at, and the local receipt --
    /// or nothing downstream can say which account is which. `apps/core` renders that list as a
    /// declaration for exactly this reason.
    write_capture: Option<PathBuf>,
}

/// A request budget the program enforces on itself and reports.
struct Budget {
    spent: u32,
    ceiling: u32,
}

impl Budget {
    fn take(&mut self, what: &str) -> Result<(), Box<dyn Error>> {
        if self.spent >= self.ceiling {
            return Err(format!(
                "request budget of {} exhausted before {what}; nothing further was asked of the \
                 provider",
                self.ceiling
            )
            .into());
        }
        self.spent += 1;
        Ok(())
    }
}

/// One provider read, its body, and the local clocks that bracket it.
struct Read {
    body: Vec<u8>,
    receipt: LocalReceipt,
}

struct Client {
    inner: HeliusHttpClient,
    runtime: tokio::runtime::Runtime,
    process_start: Instant,
    clock_id: String,
    sequence: u64,
    write_capture: Option<PathBuf>,
    captured: bool,
}

impl Client {
    fn open(key_file: &Path, write_capture: Option<PathBuf>) -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            inner: HeliusHttpClient::at_startup(
                &HeliusConfig::mainnet(CredentialFile(key_file.to_path_buf())),
                RESPONSE_CEILING_BYTES,
            )?,
            runtime: tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?,
            process_start: Instant::now(),
            clock_id: format!("joshi-venue-readout-{}", std::process::id()),
            sequence: 0,
            write_capture,
            captured: false,
        })
    }

    fn read(
        &mut self,
        budget: &mut Budget,
        what: &str,
        request: &SolanaReadRequest,
    ) -> Result<Read, Box<dyn Error>> {
        budget.take(what)?;
        self.sequence += 1;
        let started = unix_millis()?;
        let (frame, _rate_limit) = self
            .runtime
            .block_on(
                self.inner
                    .request(request, UnixMillis(started), self.sequence),
            )
            .map_err(|error| format!("the {what} read failed: {error}"))?;
        let receipt = LocalReceipt {
            clock_id: self.clock_id.clone(),
            monotonic_ns: u64::try_from(self.process_start.elapsed().as_nanos())?,
            wall_unix_ms: unix_millis()?,
        };
        if frame.http_status != Some(200) {
            return Err(format!(
                "provider rejected the {what} read with HTTP status {:?}; URL withheld",
                frame.http_status
            )
            .into());
        }
        let parsed: Value = serde_json::from_slice(&frame.body)
            .map_err(|_| format!("provider {what} response body was not JSON"))?;
        if let Some(error) = parsed.get("error") {
            return Err(format!(
                "provider {what} returned JSON-RPC error code {:?}; message withheld",
                error.get("code").and_then(Value::as_i64)
            )
            .into());
        }
        Ok(Read {
            body: frame.body.to_vec(),
            receipt,
        })
    }

    fn accounts(
        &mut self,
        budget: &mut Budget,
        what: &str,
        addresses: &[String],
    ) -> Result<(AccountSetResponse, LocalReceipt), Box<dyn Error>> {
        let read = self.read(
            budget,
            what,
            &SolanaReadRequest::new(
                SolanaReadMethod::GetMultipleAccounts,
                json!([addresses, { "encoding": "base64", "commitment": COMMITMENT }]),
            ),
        )?;
        // The first account-set read of a run IS the atomic state read; the later one, if any, is
        // the drift probe. Only the state read is worth retaining, because a readout describes the
        // moment its state was observed.
        if !self.captured
            && let Some(path) = self.write_capture.clone()
        {
            self.captured = true;
            retain_state_read(&path, addresses, &read)?;
        }
        Ok((read_multiple_accounts(&read.body, addresses)?, read.receipt))
    }
}

/// Write the state read in the shape `apps/core` mounts, carrying what the body cannot state.
fn retain_state_read(path: &Path, addresses: &[String], read: &Read) -> Result<(), Box<dyn Error>> {
    let body: Value = serde_json::from_slice(&read.body)?;
    let slot = body
        .pointer("/result/context/slot")
        .and_then(Value::as_u64)
        .ok_or("the state response stated no context slot")?;
    let capture = json!({
        "contract": "joshi.venue_accounts_capture.v1",
        "requestedCommitment": COMMITMENT,
        "requestedAddresses": addresses,
        "clockId": read.receipt.clock_id,
        "receivedMonotonicNs": read.receipt.monotonic_ns,
        "receivedAtUnixMs": read.receipt.wall_unix_ms,
        // The provider states no block time on an account read, and an absent record is not an
        // age of zero, so nothing is substituted here.
        "chainSecondUnixS": Value::Null,
        "provenance": format!(
            "One getMultipleAccounts response at {COMMITMENT} slot {slot}, retained verbatim by \
             the venue_readout example. The address list is a declaration by the reader: the \
             response is positional and names no address."
        ),
        "body": body,
    });
    std::fs::write(path, serde_json::to_vec_pretty(&capture)?)?;
    Ok(())
}

/// A mint and either the venue it resolved to or exactly why it did not.
type Resolution = (String, Result<(Resolved, PumpBondingCurve), String>);

/// Which venue a mint resolved to, and the accounts its state needs.
enum Resolved {
    Curve {
        address: String,
        bump: u8,
    },
    Pool {
        address: String,
        base_vault: String,
        quote_vault: String,
    },
}

#[allow(clippy::too_many_lines)] // One pass, in the order the evidence constrains it.
fn run(mints: &[String], options: &Options) -> Result<String, Box<dyn Error>> {
    let mut budget = Budget {
        spent: 0,
        ceiling: options.max_requests,
    };
    let mut client = Client::open(&options.key_file, options.write_capture.clone())?;
    let mut out = String::new();

    // Round one. Every bonding-curve candidate for every mint, both mints' own accounts, wrapped
    // SOL, the Global account, and both fee configurations, in one read at one slot.
    let mut round_one: Vec<String> = Vec::new();
    let mut candidates: Vec<(usize, Vec<(u8, String)>)> = Vec::new();
    for (index, mint) in mints.iter().enumerate() {
        let derived = bonding_curve_candidates(mint, CURVE_BUMP_CANDIDATES);
        if derived.is_empty() {
            return Err(format!("{mint} is not a 32-byte address").into());
        }
        for (_, address) in &derived {
            round_one.push(address.clone());
        }
        candidates.push((index, derived));
        round_one.push(mint.clone());
    }
    round_one.push(WRAPPED_SOL_MINT.to_owned());
    round_one.push(PUMP_GLOBAL_ADDRESS.to_owned());
    round_one.push(PUMP_CURVE_FEE_CONFIG_ADDRESS.to_owned());
    round_one.push(PUMP_FEE_CONFIG_ADDRESS.to_owned());
    let (first, first_receipt) = client.accounts(&mut budget, "curve candidates", &round_one)?;

    // The two configuration accounts are recomputed from the programs whose fees they set, so
    // neither address has to be believed on anybody's word.
    let global_bump = global_derivation_bump(PUMP_GLOBAL_ADDRESS);
    let curve_fee_bump =
        fee_config_derivation_bump(PUMP_CURVE_FEE_CONFIG_ADDRESS, PUMP_BONDING_CURVE_PROGRAM_ID);
    let amm_fee_bump = fee_config_derivation_bump(PUMP_FEE_CONFIG_ADDRESS, PUMP_AMM_PROGRAM_ID);
    let curve_fee_config = PumpFeeConfig::decode(first.require(PUMP_CURVE_FEE_CONFIG_ADDRESS)?)?;
    let amm_fee_config = PumpFeeConfig::decode(first.require(PUMP_FEE_CONFIG_ADDRESS)?)?;
    // Reading Global is a check, never a rate source, so a Global this decoder refuses must not
    // take the readout down with it. It is reported and the run continues.
    let global = first
        .require(PUMP_GLOBAL_ADDRESS)
        .map_err(|error| error.to_string())
        .and_then(|account| PumpGlobal::decode(account).map_err(|error| error.to_string()));

    let _ = writeln!(
        out,
        "PRE-TRADE VENUE READOUT\n  provider          helius mainnet json-rpc, \
         getMultipleAccounts and getProgramAccounts, commitment {COMMITMENT}\n  not an \
         execution   nothing here is constructed, signed, simulated, or submitted\n  address \
         proofs   global bump {global_bump:?}, curve fee config bump {curve_fee_bump:?}, amm fee \
         config bump {amm_fee_bump:?}"
    );
    let curve_rates = curve_fee_config.agreed_rates(0)?;
    match global.as_ref().map_err(Clone::clone).and_then(|global| {
        global
            .require_agreement_with_fee_program(curve_rates)
            .map_err(|error| error.to_string())
    }) {
        Ok(()) => out.push_str(
            "  global vs fee program  they now agree; the stale-rate regression has cleared\n",
        ),
        Err(error) => {
            let _ = writeln!(out, "  global vs fee program  {error}");
        }
    }

    // Resolve each mint to a venue. A curve that is not complete is the venue; a complete curve
    // means the coin graduated and the pool is. Every mint keeps its place in the caller's order,
    // and a mint that resolves to nothing says so in that place rather than being dropped.
    let mut resolutions: Vec<Resolution> = Vec::new();
    for (index, derived) in &candidates {
        let mint = &mints[*index];
        let mut found = None;
        for (bump, address) in derived {
            if let Ok(account) = first.require(address)
                && let Ok(curve) = PumpBondingCurve::decode(account)
            {
                found = Some((*bump, address.clone(), curve));
                break;
            }
        }
        let Some((bump, address, curve)) = found else {
            resolutions.push((
                mint.clone(),
                Err(format!(
                    "UNRESOLVED: none of the top {CURVE_BUMP_CANDIDATES} derived bonding-curve \
                     addresses holds a decodable curve. This mint may not be a Pump mint, its \
                     canonical bump may be lower than the candidates asked for, or its account may \
                     carry a layout this decoder refuses. An absent account is an absent record, \
                     not evidence the coin does not exist."
                )),
            ));
            continue;
        };
        if curve.complete {
            match discover_pool(&mut client, &mut budget, mint)? {
                Some(pool) => resolutions.push((mint.clone(), Ok((pool, curve)))),
                None => resolutions.push((
                    mint.clone(),
                    Err(format!(
                        "UNRESOLVED: the bonding curve at {address} is complete, so the coin left \
                         the curve, but no PumpSwap pool against wrapped SOL was found for it. It \
                         may have graduated somewhere this program does not read."
                    )),
                )),
            }
        } else {
            resolutions.push((mint.clone(), Ok((Resolved::Curve { address, bump }, curve))));
        }
    }

    // Round two. Everything the graduated mints' states need, in one read at one slot: the pool,
    // both of its vaults, and the mint, so no number in a pool readout comes from a different slot
    // than any other.
    let mut round_two: Vec<String> = Vec::new();
    for (mint, resolved) in &resolutions {
        if let Ok((
            Resolved::Pool {
                address,
                base_vault,
                quote_vault,
            },
            _,
        )) = resolved
        {
            round_two.push(address.clone());
            round_two.push(base_vault.clone());
            round_two.push(quote_vault.clone());
            round_two.push(mint.clone());
        }
    }
    let pools = if round_two.is_empty() {
        None
    } else {
        Some(client.accounts(&mut budget, "pool state", &round_two)?)
    };

    // The chain's own clock for each slot the state was read at.
    let curve_chain = block_second(&mut client, &mut budget, first.context_slot);
    let pool_chain = match &pools {
        None => None,
        Some((response, _)) => block_second(&mut client, &mut budget, response.context_slot),
    };

    // The drift probe: the same two reads again after a declared window, so the readout can say
    // how fast this venue has actually been moving rather than only how old the state is.
    let (drift_first, drift_pools) = if options.drift_window.is_zero() {
        (None, None)
    } else {
        std::thread::sleep(options.drift_window);
        let again = client.accounts(&mut budget, "drift probe", &round_one)?;
        let again_pools = if round_two.is_empty() {
            None
        } else {
            Some(client.accounts(&mut budget, "drift probe, pools", &round_two)?)
        };
        (Some(again), again_pools)
    };

    for (mint, resolved) in &resolutions {
        let _ = writeln!(out, "\n=== {mint} ===");
        let (resolved, curve) = match resolved {
            Err(reason) => {
                let _ = writeln!(out, "  {reason}");
                continue;
            }
            Ok(pair) => pair,
        };
        let card = match resolved {
            Resolved::Curve { address, bump } => curve_readout(
                mint,
                address,
                *bump,
                curve,
                &curve_fee_config,
                (&first, &first_receipt, curve_chain),
                drift_first.as_ref().map(|(r, receipt)| (r, receipt)),
                options,
            ),
            Resolved::Pool {
                address,
                base_vault,
                quote_vault,
            } => {
                let (response, receipt) = pools.as_ref().ok_or("pool state was not read")?;
                pool_readout(
                    mint,
                    address,
                    (base_vault, quote_vault),
                    &amm_fee_config,
                    (response, receipt, pool_chain),
                    drift_pools.as_ref().map(|(r, receipt)| (r, receipt)),
                    options,
                )
            }
        };
        match card {
            Ok(text) => out.push_str(&text),
            Err(error) => {
                let _ = writeln!(out, "  REFUSED: {error}");
            }
        }
    }

    let _ = writeln!(
        out,
        "\nrequest budget    {} of {} spent",
        budget.spent, budget.ceiling
    );
    Ok(out)
}

/// Finds a mint's `PumpSwap` pool against wrapped SOL, by owner and layout filter.
///
/// This is discovery only. The address it returns is re-read in the atomic state call and checked
/// there against the pool's own stated base mint and its own derivation.
fn discover_pool(
    client: &mut Client,
    budget: &mut Budget,
    mint: &str,
) -> Result<Option<Resolved>, Box<dyn Error>> {
    let read = client.read(
        budget,
        "pool discovery",
        &SolanaReadRequest::new(
            SolanaReadMethod::GetProgramAccounts,
            json!([
                PUMP_AMM_PROGRAM_ID,
                {
                    "encoding": "base64",
                    "commitment": COMMITMENT,
                    "withContext": true,
                    "filters": [
                        { "dataSize": joshi_sources::POOL_ACCOUNT_LEN },
                        { "memcmp": { "offset": 43, "bytes": mint } },
                        { "memcmp": { "offset": 75, "bytes": WRAPPED_SOL_MINT } }
                    ]
                }
            ]),
        ),
    )?;
    let parsed: Value = serde_json::from_slice(&read.body)?;
    let rows = parsed["result"]
        .get("value")
        .or_else(|| parsed.get("result"))
        .and_then(Value::as_array)
        .ok_or("pool discovery response states no account array")?;
    let mut best: Option<PumpSwapPool> = None;
    for row in rows {
        let address = row["pubkey"].as_str().unwrap_or_default().to_owned();
        let data = row["account"]["data"][0]
            .as_str()
            .ok_or("pool discovery row states no base64 data")?;
        let account = RetainedAccount {
            address,
            owner: row["account"]["owner"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
            lamports: row["account"]["lamports"].as_u64().unwrap_or_default(),
            executable: row["account"]["executable"].as_bool().unwrap_or_default(),
            data: base64_decode(data)?,
        };
        let Ok(pool) = PumpSwapPool::decode(&account) else {
            continue;
        };
        if pool.base_mint != mint {
            continue;
        }
        if best.as_ref().is_none_or(|held| pool.index < held.index) {
            best = Some(pool);
        }
    }
    Ok(best.map(|pool| Resolved::Pool {
        address: pool.address,
        base_vault: pool.pool_base_token_account,
        quote_vault: pool.pool_quote_token_account,
    }))
}

#[allow(clippy::too_many_arguments)]
fn curve_readout(
    mint: &str,
    address: &str,
    bump: u8,
    curve: &PumpBondingCurve,
    fee_config: &PumpFeeConfig,
    state_read: (&AccountSetResponse, &LocalReceipt, Option<ChainSecond>),
    drift_read: Option<(&AccountSetResponse, &LocalReceipt)>,
    options: &Options,
) -> Result<String, Box<dyn Error>> {
    let (response, receipt, chain) = state_read;
    let base_mint = TokenMint::decode(response.require(mint)?)?;
    // The curve tables carry one row at threshold zero, so no market cap has to be chosen.
    let rates = fee_config.agreed_rates(0)?;
    if !curve.has_priceable_reserves() {
        return Err(format!(
            "the curve at {address} states virtual reserves of {} base and {} quote atoms; a state \
             with a zero reserve is not a state a quote can be computed at",
            curve.virtual_base_atoms, curve.virtual_quote_atoms
        )
        .into());
    }
    let schedule = schedule_from(rates, curve.creator_fee_applies())?;
    let state = ExactCurveState {
        formula: VenueKind::PumpBondingCurve.formula(),
        base_atoms: u128::from(curve.virtual_base_atoms),
        effective_quote_atoms: u128::from(curve.virtual_quote_atoms),
        schedule,
    };
    let drift = drift_read
        .map(|(later, later_receipt)| -> Result<_, Box<dyn Error>> {
            let after = PumpBondingCurve::decode(later.require(address)?)?;
            let later_state = ExactCurveState {
                base_atoms: u128::from(after.virtual_base_atoms),
                effective_quote_atoms: u128::from(after.virtual_quote_atoms),
                ..state
            };
            Ok(MeasuredDrift::measure(
                (&state, age(response.context_slot, chain, receipt)),
                (&later_state, age(later.context_slot, None, later_receipt)),
            )?)
        })
        .transpose()?;
    let readout = PreTradeReadout::build(
        mint,
        VenueKind::PumpBondingCurve,
        address,
        format!(
            "the curve is PDA([\"bonding-curve\", mint], Pump program) at bump {bump}; nothing in \
             the curve account itself names the mint"
        ),
        state,
        QuoteReserveComposition::CurveVirtualReserve {
            virtual_quote_atoms: u128::from(curve.virtual_quote_atoms),
        },
        FeeRateSource::FeeProgramConfig {
            config_address: PUMP_CURVE_FEE_CONFIG_ADDRESS.to_owned(),
            tables_agreed: true,
            selected_at_market_cap_quote_atoms: 0,
        },
        (base_mint.decimals, 9),
        &request_from(options),
        age(response.context_slot, chain, receipt),
        drift,
        curve_unsupported(curve, options),
    )?;
    Ok(readout.render_card())
}

#[allow(clippy::too_many_arguments)]
fn pool_readout(
    mint: &str,
    address: &str,
    vaults: (&str, &str),
    fee_config: &PumpFeeConfig,
    state_read: (&AccountSetResponse, &LocalReceipt, Option<ChainSecond>),
    drift_read: Option<(&AccountSetResponse, &LocalReceipt)>,
    options: &Options,
) -> Result<String, Box<dyn Error>> {
    let (response, receipt, chain) = state_read;
    let pool = PumpSwapPool::decode(response.require(address)?)?;
    if pool.base_mint != mint {
        return Err(format!(
            "pool {address} states base mint {}, not {mint}",
            pool.base_mint
        )
        .into());
    }
    let base_vault = TokenVault::decode(response.require(vaults.0)?)?;
    let quote_vault = TokenVault::decode(response.require(vaults.1)?)?;
    if base_vault.owner != pool.address || quote_vault.owner != pool.address {
        return Err("a vault this pool named is not owned by the pool".into());
    }
    let base_mint = TokenMint::decode(response.require(mint)?)?;
    let effective_quote = pool.effective_quote_atoms(quote_vault.amount);
    let market_cap = mul_div_u128(
        effective_quote,
        u128::from(base_mint.supply),
        u128::from(base_vault.amount),
        Rounding::Down,
    )?;

    // Where the retained tier tables disagree, no byte says which one applies. Rather than pick the
    // flattering one, take the worse and say so.
    let per_table = fee_config.per_table_rates(market_cap);
    let agreed = fee_config.agreed_rates(market_cap);
    let (rates, tables_agreed, note) = if let Ok(rates) = agreed {
        (rates, true, None)
    } else {
        {
            let worst = per_table
                .iter()
                .flatten()
                .copied()
                .max_by_key(|rates| rates.lp + rates.protocol + rates.creator)
                .ok_or("the fee configuration carries no tier at this market cap")?;
            (
                worst,
                false,
                Some(format!(
                    "the retained fee tier tables select different rates at this market cap \
                     ({per_table:?}) and no retained byte says which applies; every number below \
                     uses the worse of them, which errs against the trade and never for it"
                )),
            )
        }
    };
    let schedule = schedule_from(rates, Some(pool.has_coin_creator()))?;
    let state = ExactCurveState {
        formula: VenueKind::PumpSwapPool.formula(),
        base_atoms: u128::from(base_vault.amount),
        effective_quote_atoms: effective_quote,
        schedule,
    };
    let drift = drift_read
        .map(|(later, later_receipt)| -> Result<_, Box<dyn Error>> {
            let after_pool = PumpSwapPool::decode(later.require(address)?)?;
            let after_base = TokenVault::decode(later.require(vaults.0)?)?;
            let after_quote = TokenVault::decode(later.require(vaults.1)?)?;
            let later_state = ExactCurveState {
                base_atoms: u128::from(after_base.amount),
                effective_quote_atoms: after_pool.effective_quote_atoms(after_quote.amount),
                ..state
            };
            Ok(MeasuredDrift::measure(
                (&state, age(response.context_slot, chain, receipt)),
                (&later_state, age(later.context_slot, None, later_receipt)),
            )?)
        })
        .transpose()?;

    let mut unsupported = pool_unsupported(&pool, options);
    if let Some(note) = note {
        unsupported.push(note);
    }
    let readout = PreTradeReadout::build(
        mint,
        VenueKind::PumpSwapPool,
        address,
        format!(
            "the pool states this base mint itself, and its address is the derived address of its \
             own index, creator, and mint pair at bump {:?}",
            pool.self_derivation_bump()
        ),
        state,
        QuoteReserveComposition::VaultBalancePlusLocatedTerm {
            quote_vault_atoms: u128::from(quote_vault.amount),
            located_term_atoms: u128::from(pool.unattributed_quote_side_reserve_atoms),
            located_term_offset: joshi_sources::POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET,
        },
        FeeRateSource::FeeProgramConfig {
            config_address: PUMP_FEE_CONFIG_ADDRESS.to_owned(),
            tables_agreed,
            selected_at_market_cap_quote_atoms: market_cap,
        },
        (base_mint.decimals, 9),
        &request_from(options),
        age(response.context_slot, chain, receipt),
        drift,
        unsupported,
    )?;
    Ok(readout.render_card())
}

fn request_from(options: &Options) -> ReadoutRequest {
    ReadoutRequest {
        declared_lift_bps: options.lift_bps,
        // Small enough that traversal is negligible at any live venue, and the readout prints the
        // probe's share of the reserve so a reader can check that claim rather than take it.
        fee_floor_probe_quote_atoms: LAMPORTS_PER_SOL / 1_000,
        intended_clip_quote_atoms: Some(options.clip_lamports),
        costs: DeclaredFixedCosts {
            provenance: format!(
                "network fee {} lamports per transaction, declared by the operator (default is the \
                 fee a landed PumpSwap sell paid in Study M0's fixture, 2026-08-21); \
                 unrecovered rent {} lamports, declared",
                options.network_fee_lamports, options.rent_lamports
            ),
            per_transaction_quote_atoms: options.network_fee_lamports,
            transactions: 2,
            flat_route_quote_atoms: 0,
            unrecovered_rent_quote_atoms: options.rent_lamports,
        },
    }
}

fn curve_unsupported(curve: &PumpBondingCurve, options: &Options) -> Vec<String> {
    let mut lines = vec![
        format!(
            "this curve account is {} bytes; bonding curves exist at 49, 115, 150, 151, and 256 \
             bytes and the shorter ones do not carry every field",
            curve.account_len
        ),
        format!(
            "bonding curve bytes {}..{} carry {:?} and bytes {}..{} carry {:?}; both regions are \
             located, unnamed, and never interpreted",
            joshi_sources::BONDING_CURVE_UNNAMED_BYTES_RANGE.0,
            joshi_sources::BONDING_CURVE_UNNAMED_BYTES_RANGE.1,
            curve.unnamed_bytes,
            joshi_sources::BONDING_CURVE_UNNAMED_PUBKEY_RANGE.0,
            joshi_sources::BONDING_CURVE_UNNAMED_PUBKEY_RANGE.1,
            curve.unnamed_pubkey.as_deref().unwrap_or("absent")
        ),
        "chart mark: no landed fill was read, so no chart mark is stated. An absent record is not \
         a zero and not the marginal price."
            .to_owned(),
        "priority fee and tip: not modelled. The declared network cost is a base fee only, and a \
         contested block costs more."
            .to_owned(),
    ];
    if options.rent_lamports == 0 {
        lines.push(
            "associated token account rent: declared as zero. If this trade has to open a new \
             token account, pass --rent-lamports; it moves the small end of the break-even \
             interval and nothing else."
                .to_owned(),
        );
    }
    lines
}

fn pool_unsupported(pool: &PumpSwapPool, options: &Options) -> Vec<String> {
    let mut lines = vec![
        format!(
            "pool byte {} carries {} quote atoms that this decoder can locate and cannot name; it \
             is in the effective reserve because four landed fills say it must be. Pool byte {} \
             carries {} and is not interpreted either.",
            joshi_sources::POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET,
            pool.unattributed_quote_side_reserve_atoms,
            joshi_sources::POOL_UNNAMED_BYTE_OFFSET,
            pool.unnamed_byte
        ),
        "chart mark: no landed fill was read, so no chart mark is stated. An absent record is not \
         a zero and not the marginal price."
            .to_owned(),
        "priority fee and tip: not modelled. The declared network cost is a base fee only, and a \
         contested block costs more."
            .to_owned(),
    ];
    if options.rent_lamports == 0 {
        lines.push(
            "associated token account rent: declared as zero. If this trade has to open a new \
             token account, pass --rent-lamports."
                .to_owned(),
        );
    }
    lines
}

/// Builds a fee schedule, keeping "the retained layout does not say" distinct from "no creator".
fn schedule_from(
    rates: FeeRatesBps,
    creator_applies: Option<bool>,
) -> Result<FeeSchedule, Box<dyn Error>> {
    Ok(FeeSchedule {
        lp: FeeBps::new(u16::try_from(rates.lp)?)?,
        protocol: FeeBps::new(u16::try_from(rates.protocol)?)?,
        creator: match creator_applies {
            Some(true) => CreatorFee::Charged(FeeBps::new(u16::try_from(rates.creator)?)?),
            Some(false) => CreatorFee::NotApplicable,
            None => CreatorFee::Unknown,
        },
    })
}

fn age(slot: u64, chain: Option<ChainSecond>, receipt: &LocalReceipt) -> StateAge {
    StateAge {
        context_slot: slot,
        requested_commitment: COMMITMENT.to_owned(),
        chain_second: chain.filter(|second| second.slot == slot),
        local_receipt: receipt.clone(),
    }
}

/// The chain's whole-second report for one slot, or `None` when the provider states none.
fn block_second(client: &mut Client, budget: &mut Budget, slot: u64) -> Option<ChainSecond> {
    let read = client.read(
        budget,
        "block time",
        &SolanaReadRequest::new(
            SolanaReadMethod::GetBlock,
            json!([
                slot,
                {
                    "encoding": "json",
                    "transactionDetails": "none",
                    "rewards": false,
                    "commitment": COMMITMENT,
                    "maxSupportedTransactionVersion": 0
                }
            ]),
        ),
    );
    // A slot the provider states no block for is an absent record, not a time of zero, and not a
    // reason to abandon a readout that is otherwise complete.
    read.ok().and_then(|read| {
        read_block_clock(&read.body, slot)
            .ok()
            .map(|clock| ChainSecond {
                slot,
                block_time_unix_s: clock.block_time_unix_s,
            })
    })
}

fn base64_decode(value: &str) -> Result<Vec<u8>, Box<dyn Error>> {
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    Ok(STANDARD.decode(value)?)
}

fn unix_millis() -> Result<i64, Box<dyn Error>> {
    Ok(i64::try_from(
        OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000,
    )?)
}

fn flag(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .iter()
        .position(|value| value == name)
        .and_then(|index| arguments.get(index + 1))
        .cloned()
}

fn repeated(arguments: &[String], name: &str) -> Vec<String> {
    arguments
        .iter()
        .enumerate()
        .filter(|(_, value)| value.as_str() == name)
        .filter_map(|(index, _)| arguments.get(index + 1).cloned())
        .collect()
}

fn parse<T: std::str::FromStr>(
    arguments: &[String],
    name: &str,
    default: T,
) -> Result<T, Box<dyn Error>>
where
    T::Err: std::fmt::Display,
{
    match flag(arguments, name) {
        None => Ok(default),
        Some(value) => value
            .parse::<T>()
            .map_err(|error| format!("{name}: {error}").into()),
    }
}

/// Parses a decimal SOL amount into exact lamports, refusing more precision than lamports have.
fn parse_sol(value: &str) -> Result<u128, Box<dyn Error>> {
    let (whole, fraction) = value.split_once('.').unwrap_or((value, ""));
    if fraction.len() > 9 {
        return Err("--clip-sol carries more precision than a lamport".into());
    }
    let padded = format!("{fraction:0<9}");
    let whole: u128 = whole.parse()?;
    let fraction: u128 = if padded.is_empty() {
        0
    } else {
        padded.parse()?
    };
    Ok(whole * LAMPORTS_PER_SOL + fraction)
}
