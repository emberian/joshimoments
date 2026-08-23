//! The paper desk: one declared hypothesis worked live, on paper, against a real venue.
//!
//! ```text
//! paper_desk --mint <address> --hypothesis "<the operator's words, verbatim>" --out <path>
//!            [--declared-by ember] [--clip-sol 0.05] [--entry immediate | --entry dip:<bps>]
//!            [--take-profit-bps 100] [--stop-bps 300] [--max-hold-seconds 300]
//!            [--entry-deadline-seconds 120] [--cadence-seconds 5]
//!            [--abandon-after-failed-polls 3] [--network-fee-lamports 7422]
//!            [--rent-lamports 0] [--max-requests 90] [--key-file ~/.helius-key]
//! ```
//!
//! This opens one [`joshi_liquidity::paper::PaperDeskV1`] episode for the mint, polls the venue's
//! own accounts at the declared cadence under a hard request budget this process enforces on
//! itself, feeds every polled state — or every recorded failure — to the desk, and writes the
//! finished episode JSON to the declared path. The desk, not this driver, holds every rule: this
//! program reads accounts, reconstructs states the way `venue_readout` does, and reports what the
//! desk decided.
//!
//! Where the state comes from, exactly as the venue-readout example established it:
//!
//! * **The venue account is derived, not looked up.** `PDA(["bonding-curve", mint])` for a curve;
//!   an owner-and-layout-filtered `getProgramAccounts` for a graduated pool, re-checked against
//!   the pool's own stated mint.
//! * **Fees come from the fee program's configuration account**, read once at open; the tier row
//!   is re-selected at each poll's market cap. Never the Global account, never a frontend index.
//! * **Pool reserves are the two vault balances plus the located term at pool byte 245.**
//! * **A curve that completes mid-episode abandons the episode**: its reserves are stale
//!   post-graduation and no quote is gap-filled from them.
//!
//! The chain's whole-second clock is requested only for the entry and exit decision slots, and
//! every other poll says so. This program constructs no transaction, signs nothing, simulates
//! nothing, and submits nothing.

use std::{
    error::Error,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use joshi_liquidity::{
    paper::{
        ChainClock, DeclaredHypothesis, DeclaredRules, DeskStep, EntryRule, EpisodeOpening,
        ExitRules, PaperDeskV1, PolledState, StateProvenance, VenueBinding,
    },
    readout::{FeeRateSource, VenueKind},
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
    PUMP_AMM_PROGRAM_ID, PUMP_CURVE_FEE_CONFIG_ADDRESS, PUMP_FEE_CONFIG_ADDRESS, PumpBondingCurve,
    PumpFeeConfig, PumpSwapPool, RetainedAccount, SolanaReadMethod, SolanaReadRequest, TokenMint,
    TokenVault, UnixMillis, WRAPPED_SOL_MINT, bonding_curve_candidates, read_block_clock,
    read_multiple_accounts,
};
use serde_json::{Value, json};
use time::OffsetDateTime;

const DEFAULT_KEY_PATH: &str = "~/.helius-key";
const COMMITMENT: &str = "finalized";
const RESPONSE_CEILING_BYTES: u64 = 8 * 1024 * 1024;
const CURVE_BUMP_CANDIDATES: u8 = 5;
/// Network fee observed on a landed `PumpSwap` sell in Study M0's fixture, 2026-08-21.
const DEFAULT_NETWORK_FEE_LAMPORTS: u128 = 7_422;
const DEFAULT_CLIP_LAMPORTS: u128 = 50_000_000;
const DEFAULT_MAX_REQUESTS: u32 = 90;
/// Requests held back so the entry and exit decision slots can be given a chain clock.
const RESERVED_CLOCK_REQUESTS: u32 = 2;
const LAMPORTS_PER_SOL: u128 = 1_000_000_000;

fn main() -> Result<(), Box<dyn Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let mint = flag(&arguments, "--mint").ok_or_else(usage)?;
    let hypothesis_words = flag(&arguments, "--hypothesis").ok_or_else(usage)?;
    let out = PathBuf::from(flag(&arguments, "--out").ok_or_else(usage)?);
    let entry = match flag(&arguments, "--entry").as_deref() {
        None | Some("immediate") => EntryRule::Immediate,
        Some(value) => {
            let trigger = value
                .strip_prefix("dip:")
                .ok_or("--entry takes 'immediate' or 'dip:<bps>'")?;
            EntryRule::MicrodipBps {
                trigger_bps: trigger.parse()?,
            }
        }
    };
    let options = Options {
        mint,
        hypothesis_words,
        declared_by: flag(&arguments, "--declared-by").unwrap_or_else(|| "ember".to_owned()),
        out,
        clip_lamports: flag(&arguments, "--clip-sol")
            .map(|value| parse_sol(&value))
            .transpose()?
            .unwrap_or(DEFAULT_CLIP_LAMPORTS),
        entry,
        take_profit_bps: parse(&arguments, "--take-profit-bps", 100)?,
        stop_bps: parse(&arguments, "--stop-bps", 300)?,
        max_hold_seconds: parse(&arguments, "--max-hold-seconds", 300)?,
        entry_deadline_seconds: parse(&arguments, "--entry-deadline-seconds", 120)?,
        cadence_seconds: parse(&arguments, "--cadence-seconds", 5)?,
        abandon_after_failed_polls: parse(&arguments, "--abandon-after-failed-polls", 3)?,
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
    };
    run(&options)
}

fn usage() -> Box<dyn Error> {
    "usage: paper_desk --mint <address> --hypothesis \"<words, verbatim>\" --out <path> \
     [--declared-by <name>] [--clip-sol <decimal>] [--entry immediate|dip:<bps>] \
     [--take-profit-bps <n>] [--stop-bps <n>] [--max-hold-seconds <n>] \
     [--entry-deadline-seconds <n>] [--cadence-seconds <n>] [--abandon-after-failed-polls <n>] \
     [--network-fee-lamports <n>] [--rent-lamports <n>] [--max-requests <n>] [--key-file <path>]"
        .into()
}

struct Options {
    mint: String,
    hypothesis_words: String,
    declared_by: String,
    out: PathBuf,
    clip_lamports: u128,
    entry: EntryRule,
    take_profit_bps: u32,
    stop_bps: u32,
    max_hold_seconds: i64,
    entry_deadline_seconds: i64,
    cadence_seconds: i64,
    abandon_after_failed_polls: u32,
    network_fee_lamports: u128,
    rent_lamports: u128,
    max_requests: u32,
    key_file: PathBuf,
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

    const fn remaining(&self) -> u32 {
        self.ceiling.saturating_sub(self.spent)
    }
}

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
}

impl Client {
    fn open(key_file: &Path) -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            inner: HeliusHttpClient::at_startup(
                &HeliusConfig::mainnet(CredentialFile(key_file.to_path_buf())),
                RESPONSE_CEILING_BYTES,
            )?,
            runtime: tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?,
            process_start: Instant::now(),
            clock_id: format!("joshi-paper-desk-{}", std::process::id()),
            sequence: 0,
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
        Ok((read_multiple_accounts(&read.body, addresses)?, read.receipt))
    }
}

/// Which venue the mint resolved to, and the accounts each poll must read.
enum Venue {
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

#[allow(clippy::too_many_lines)] // One run: resolve, declare, poll, finish, write.
fn run(options: &Options) -> Result<(), Box<dyn Error>> {
    // The hypothesis is dated before this process touches the network, so nothing the network
    // says can leak into what was declared.
    let hypothesis = DeclaredHypothesis {
        operator_words_verbatim: options.hypothesis_words.clone(),
        declared_by: options.declared_by.clone(),
        declared_at_unix_ms: unix_millis()?,
    };
    let mut budget = Budget {
        spent: 0,
        ceiling: options.max_requests,
    };
    let mut client = Client::open(&options.key_file)?;

    // Round one: every curve-derivation candidate, the mint itself, and both fee configurations,
    // in one read at one slot.
    let candidates = bonding_curve_candidates(&options.mint, CURVE_BUMP_CANDIDATES);
    if candidates.is_empty() {
        return Err(format!("{} is not a 32-byte address", options.mint).into());
    }
    let mut round_one: Vec<String> = candidates
        .iter()
        .map(|(_, address)| address.clone())
        .collect();
    round_one.push(options.mint.clone());
    round_one.push(PUMP_CURVE_FEE_CONFIG_ADDRESS.to_owned());
    round_one.push(PUMP_FEE_CONFIG_ADDRESS.to_owned());
    let (first, _first_receipt) = client.accounts(&mut budget, "venue resolution", &round_one)?;

    let curve_fee_config = PumpFeeConfig::decode(first.require(PUMP_CURVE_FEE_CONFIG_ADDRESS)?)?;
    let amm_fee_config = PumpFeeConfig::decode(first.require(PUMP_FEE_CONFIG_ADDRESS)?)?;
    let base_mint = TokenMint::decode(first.require(&options.mint)?)?;

    let mut found = None;
    for (bump, address) in &candidates {
        if let Ok(account) = first.require(address)
            && let Ok(curve) = PumpBondingCurve::decode(account)
        {
            found = Some((*bump, address.clone(), curve));
            break;
        }
    }
    let Some((bump, curve_address, curve)) = found else {
        return Err(format!(
            "REFUSED: none of the top {CURVE_BUMP_CANDIDATES} derived bonding-curve addresses for \
             {} holds a decodable curve; this may not be a Pump mint. No episode was opened and \
             nothing was substituted.",
            options.mint
        )
        .into());
    };
    let venue = if curve.complete {
        match discover_pool(&mut client, &mut budget, &options.mint)? {
            Some(venue) => venue,
            None => {
                return Err(format!(
                    "REFUSED: the bonding curve at {curve_address} is complete, so the coin left \
                     the curve, but no PumpSwap pool against wrapped SOL was found for it. No \
                     episode was opened."
                )
                .into());
            }
        }
    } else {
        Venue::Curve {
            address: curve_address,
            bump,
        }
    };

    let (venue_kind, binding) = match &venue {
        Venue::Curve { bump, .. } => (
            VenueKind::PumpBondingCurve,
            format!(
                "the curve is PDA([\"bonding-curve\", mint], Pump program) at bump {bump}; \
                 nothing in the curve account itself names the mint"
            ),
        ),
        Venue::Pool { .. } => (
            VenueKind::PumpSwapPool,
            "the pool states this base mint itself and was discovered by owner-and-layout \
             filter; every poll re-reads it and re-checks its stated mint"
                .to_owned(),
        ),
    };
    let venue_account = match &venue {
        Venue::Curve { address, .. } | Venue::Pool { address, .. } => address.clone(),
    };
    println!(
        "PAPER DESK  resolving {} -> {} at {venue_account}",
        options.mint,
        venue_kind.label()
    );

    let opening = EpisodeOpening {
        episode_id: format!(
            "paper-{}-{}",
            &options.mint[..options.mint.len().min(8)],
            hypothesis.declared_at_unix_ms
        ),
        mint: options.mint.clone(),
        venue: VenueBinding {
            venue: venue_kind,
            venue_account: venue_account.clone(),
            binding,
        },
        hypothesis,
        declared_clip_quote_atoms: options.clip_lamports,
        rules: DeclaredRules {
            entry: options.entry,
            entry_deadline_ms: options.entry_deadline_seconds.saturating_mul(1_000),
            exit: ExitRules {
                take_profit_net_bps: options.take_profit_bps,
                stop_loss_net_bps: options.stop_bps,
                max_hold_ms: options.max_hold_seconds.saturating_mul(1_000),
            },
            poll_cadence_ms: options.cadence_seconds.saturating_mul(1_000),
            abandon_after_consecutive_failed_polls: options.abandon_after_failed_polls,
        },
        costs: DeclaredFixedCosts {
            provenance: format!(
                "network fee {} lamports per transaction x 2 transactions, declared by the \
                 operator (default is the fee a landed PumpSwap sell paid in Study M0's fixture, \
                 2026-08-21); unrecovered rent {} lamports, declared; priority fee and tip not \
                 modelled",
                options.network_fee_lamports, options.rent_lamports
            ),
            per_transaction_quote_atoms: options.network_fee_lamports,
            transactions: 2,
            flat_route_quote_atoms: 0,
            unrecovered_rent_quote_atoms: options.rent_lamports,
        },
        base_decimals: base_mint.decimals,
        quote_decimals: 9,
        opened_at_unix_ms: unix_millis()?,
    };
    let mut desk = PaperDeskV1::open(opening)?;

    // The poll loop. The desk decides; this loop only reads, reconstructs, and reports.
    while !desk.is_closed() {
        if budget.remaining() <= RESERVED_CLOCK_REQUESTS {
            desk.abandon(format!(
                "request budget of {} exhausted with {} reserved for decision-slot clocks; the \
                 episode cannot honestly continue without fresh state",
                budget.ceiling, RESERVED_CLOCK_REQUESTS
            ));
            break;
        }
        let step = match poll_once(
            &mut client,
            &mut budget,
            &venue,
            options,
            &amm_fee_config,
            &curve_fee_config,
        ) {
            Ok(PollResult::State(polled)) => {
                let slot = polled.provenance.context_slot;
                let step = desk.on_observed_poll(&polled)?;
                if matches!(step, DeskStep::Entered | DeskStep::Exited { .. }) {
                    attach_decision_clock(&mut client, &mut budget, &mut desk, slot);
                }
                step
            }
            Ok(PollResult::CurveCompleted) => {
                desk.abandon(
                    "the bonding curve completed mid-episode; its reserves are stale \
                     post-graduation and no quote will be gap-filled from them",
                );
                DeskStep::Abandoned
            }
            Err(error) => desk.on_failed_poll(unix_millis()?, error.to_string())?,
        };
        println!("  poll {:>3}  {}", budget.spent, describe(&step));
        if desk.is_closed() {
            break;
        }
        std::thread::sleep(Duration::from_secs(u64::try_from(options.cadence_seconds)?));
    }

    let episode = desk.finish(unix_millis()?)?;
    let json = episode.render_json();
    std::fs::write(&options.out, &json)?;
    println!("\n{}", episode.render_card());
    println!(
        "episode json written to {} ({} bytes); request budget {} of {} spent",
        options.out.display(),
        json.len(),
        budget.spent,
        budget.ceiling
    );
    Ok(())
}

enum PollResult {
    State(PolledState),
    CurveCompleted,
}

fn poll_once(
    client: &mut Client,
    budget: &mut Budget,
    venue: &Venue,
    options: &Options,
    amm_fee_config: &PumpFeeConfig,
    curve_fee_config: &PumpFeeConfig,
) -> Result<PollResult, Box<dyn Error>> {
    match venue {
        Venue::Curve { address, .. } => {
            let (response, receipt) =
                client.accounts(budget, "curve poll", std::slice::from_ref(address))?;
            let curve = PumpBondingCurve::decode(response.require(address)?)?;
            if curve.complete {
                return Ok(PollResult::CurveCompleted);
            }
            if !curve.has_priceable_reserves() {
                return Err(format!(
                    "the curve states virtual reserves of {} base and {} quote atoms; a state \
                     with a zero reserve is not a state a quote can be computed at",
                    curve.virtual_base_atoms, curve.virtual_quote_atoms
                )
                .into());
            }
            // The curve tables carry one row at threshold zero, so no market cap is chosen.
            let rates = curve_fee_config.agreed_rates(0)?;
            Ok(PollResult::State(PolledState {
                state: ExactCurveState {
                    formula: VenueKind::PumpBondingCurve.formula(),
                    base_atoms: u128::from(curve.virtual_base_atoms),
                    effective_quote_atoms: u128::from(curve.virtual_quote_atoms),
                    schedule: schedule_from(rates, curve.creator_fee_applies())?,
                },
                fee_source: FeeRateSource::FeeProgramConfig {
                    config_address: PUMP_CURVE_FEE_CONFIG_ADDRESS.to_owned(),
                    tables_agreed: true,
                    selected_at_market_cap_quote_atoms: 0,
                },
                provenance: provenance(response.context_slot, receipt),
            }))
        }
        Venue::Pool {
            address,
            base_vault,
            quote_vault,
        } => {
            let addresses = [
                address.clone(),
                base_vault.clone(),
                quote_vault.clone(),
                options.mint.clone(),
            ];
            let (response, receipt) = client.accounts(budget, "pool poll", &addresses)?;
            let pool = PumpSwapPool::decode(response.require(address)?)?;
            if pool.base_mint != options.mint {
                return Err(format!(
                    "pool {address} states base mint {}, not {}",
                    pool.base_mint, options.mint
                )
                .into());
            }
            let base = TokenVault::decode(response.require(base_vault)?)?;
            let quote = TokenVault::decode(response.require(quote_vault)?)?;
            if base.owner != pool.address || quote.owner != pool.address {
                return Err("a vault this pool named is not owned by the pool".into());
            }
            let mint = TokenMint::decode(response.require(&options.mint)?)?;
            let effective_quote = pool.effective_quote_atoms(quote.amount);
            let market_cap = mul_div_u128(
                effective_quote,
                u128::from(mint.supply),
                u128::from(base.amount),
                Rounding::Down,
            )?;
            // Where the retained tier tables disagree, take the worse and carry the flag.
            let (rates, tables_agreed) = if let Ok(rates) = amm_fee_config.agreed_rates(market_cap)
            {
                (rates, true)
            } else {
                let worst = amm_fee_config
                    .per_table_rates(market_cap)
                    .into_iter()
                    .flatten()
                    .max_by_key(|rates| rates.lp + rates.protocol + rates.creator)
                    .ok_or("the fee configuration carries no tier at this market cap")?;
                (worst, false)
            };
            Ok(PollResult::State(PolledState {
                state: ExactCurveState {
                    formula: VenueKind::PumpSwapPool.formula(),
                    base_atoms: u128::from(base.amount),
                    effective_quote_atoms: effective_quote,
                    schedule: schedule_from(rates, Some(pool.has_coin_creator()))?,
                },
                fee_source: FeeRateSource::FeeProgramConfig {
                    config_address: PUMP_FEE_CONFIG_ADDRESS.to_owned(),
                    tables_agreed,
                    selected_at_market_cap_quote_atoms: market_cap,
                },
                provenance: provenance(response.context_slot, receipt),
            }))
        }
    }
}

/// Finds a mint's `PumpSwap` pool against wrapped SOL, by owner and layout filter. Discovery
/// only; every poll re-reads the pool and re-checks its stated mint.
fn discover_pool(
    client: &mut Client,
    budget: &mut Budget,
    mint: &str,
) -> Result<Option<Venue>, Box<dyn Error>> {
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
    Ok(best.map(|pool| Venue::Pool {
        address: pool.address,
        base_vault: pool.pool_base_token_account,
        quote_vault: pool.pool_quote_token_account,
    }))
}

/// Asks the chain for the decision slot's whole-second clock and attaches the answer — or its
/// explicit absence — to every record of that slot.
fn attach_decision_clock(
    client: &mut Client,
    budget: &mut Budget,
    desk: &mut PaperDeskV1,
    slot: u64,
) {
    let read = client.read(
        budget,
        "decision-slot block time",
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
    let clock = read
        .ok()
        .and_then(|read| read_block_clock(&read.body, slot).ok());
    match clock {
        Some(clock) => {
            desk.attach_chain_second(ChainSecond {
                slot,
                block_time_unix_s: clock.block_time_unix_s,
            });
        }
        None => {
            desk.mark_chain_clock_absent(slot);
        }
    }
}

fn provenance(context_slot: u64, local_receipt: LocalReceipt) -> StateProvenance {
    StateProvenance {
        context_slot,
        requested_commitment: COMMITMENT.to_owned(),
        chain: ChainClock::NotRequested,
        local_receipt,
    }
}

fn describe(step: &DeskStep) -> String {
    match step {
        DeskStep::AwaitingEntry => "awaiting entry".to_owned(),
        DeskStep::Entered => "ENTERED (paper; nothing was submitted anywhere)".to_owned(),
        DeskStep::Holding {
            net_of_all_in_cost_bps: Some(bps),
        } => format!("holding, net of all-in cost {bps} bps (arithmetic, not a result)"),
        DeskStep::Holding {
            net_of_all_in_cost_bps: None,
        } => "holding, no fresh valuation this poll".to_owned(),
        DeskStep::Exited { rule } => format!("EXITED by {} (paper)", rule.label()),
        DeskStep::NeverEntered => "never entered".to_owned(),
        DeskStep::Abandoned => "abandoned".to_owned(),
    }
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
