//! Serve one held coin's fee floor, break-even clip interval, and fee-tier standing.
//!
//! The hold gesture keeps a coin where the feed cannot scroll it away. This is what the coin then
//! has to say for itself: what a round trip costs at this venue before anything is committed, how
//! large a clip can break even inside a stated lift, and which fee-tier row the market cap
//! currently selects. Measured on three real mints, that last one is the lever — a graduated pool
//! at a 42.8 SOL market cap pays the same 125 basis points a leg a brand-new coin does, so
//! "graduated" predicts nothing and the row does.
//!
//! **Nothing in this module reads the network.** The arithmetic is [`joshi_liquidity`], the
//! decoding is [`joshi_sources`], and both are pure over retained bytes. What reaches this module
//! is a *capture*: one `getMultipleAccounts` response, retained exactly, plus the three things a
//! JSON-RPC response body cannot state about itself.
//!
//! Those three are why [`VenueAccountsCapture`] exists rather than a bare response body:
//!
//! 1. **The body names no addresses.** `result.value` is positional and the address list lives in
//!    the request, which is not retained. Every readout built here therefore carries the stated
//!    address list as a *declaration*, and says so.
//! 2. **The body names no commitment.** `finalized` versus `confirmed` is most of the eleven to
//!    thirteen seconds between chain time and local receipt, and the response does not restate it.
//! 3. **The body carries no local clock.** The age that matters is how long ago these bytes
//!    arrived, and only the process that received them knows.
//!
//! A readout whose numbers are two minutes old is a different readout. One pool measured on
//! 2026-08-21 drifted nine to ten basis points in thirty seconds, so its entire sixty-basis-point
//! fee floor is two to four minutes of drift. Every wire this module emits carries its age, and
//! the cockpit is expected to keep showing that age growing.

use std::collections::{BTreeMap, BTreeSet};

use joshi_liquidity::{
    readout::{
        FeeRateSource, PreTradeReadout, QuoteReserveComposition, ReadoutRequest, StateAge,
        VenueKind, render_decimal,
    },
    round_trip::DeclaredFixedCosts,
    tier::{TierBasis, TierDirection, TierLadder, TierRow, TierStanding},
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::ExactCurveState,
    wide::{Rounding, mul_div_u128},
    would_quote::{ChainSecond, LocalReceipt},
};
use joshi_sources::{
    FeeRatesBps, PUMP_CURVE_FEE_CONFIG_ADDRESS, PUMP_FEE_CONFIG_ADDRESS, PumpBondingCurve,
    PumpFeeConfig, PumpSwapPool, TokenMint, TokenVault, WRAPPED_SOL_MINT,
    bonding_curve_derivation_bump,
    solana_account::{AccountSetResponse, read_multiple_accounts},
};
use serde::{Deserialize, Serialize};

/// Wire contract this module emits. Frozen with its schema version.
pub const VENUE_READOUT_CONTRACT: &str = "joshi.glass.venue_readout";
pub const VENUE_READOUT_SCHEMA_VERSION: u16 = 1;
/// Contract a capture file must name to be read at all.
pub const VENUE_ACCOUNTS_CAPTURE_CONTRACT: &str = "joshi.venue_accounts_capture.v1";
/// Lamports in one SOL. Rendering only.
const LAMPORTS_PER_SOL: u128 = 1_000_000_000;
/// Decimals of the quote asset every venue here trades against.
const QUOTE_DECIMALS: u8 = 9;

/// One retained `getMultipleAccounts` response plus what its body cannot state about itself.
#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct VenueAccountsCapture {
    /// Must equal [`VENUE_ACCOUNTS_CAPTURE_CONTRACT`].
    pub contract: String,
    /// Commitment named in the request. A declaration: the response body does not restate it, and
    /// most of the chain-to-receipt age is this choice.
    pub requested_commitment: String,
    /// The address list the request carried, in request order.
    ///
    /// A declaration. `result.value` is positional and names no address, so nothing in the
    /// retained bytes can check this, and every readout built from it says so out loud.
    pub requested_addresses: Vec<String>,
    /// Identity of the clock the receipt was taken on, so two receipts are never compared across
    /// clocks that were never the same clock.
    pub clock_id: String,
    /// Monotonic reading at receipt, in nanoseconds since that clock's own origin.
    pub received_monotonic_ns: u64,
    /// Wall clock at which the receiving process finished reading the response.
    pub received_at_unix_ms: i64,
    /// The chain's whole-second report for the context slot, when the capture recorded one.
    /// `None` is an absent record and never a zero.
    #[serde(default)]
    pub chain_second_unix_s: Option<i64>,
    /// Where these bytes came from, in the capturer's own words. Carried to the reader unchanged.
    pub provenance: String,
    /// The exact provider response body.
    pub body: Box<serde_json::value::RawValue>,
}

/// Everything a readout needs that is declared rather than measured.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VenueReadoutPolicy {
    /// The mark lift the operator thinks these coins have in them, in basis points.
    pub declared_lift_bps: u128,
    /// Size the fee floor is probed at, in quote atoms.
    pub fee_floor_probe_quote_atoms: u128,
    /// A clip the operator wants a hurdle for, if they have one in mind.
    pub intended_clip_quote_atoms: Option<u128>,
    pub costs: DeclaredFixedCosts,
}

impl VenueReadoutPolicy {
    /// The declarations Study M0's own run used, so a cockpit reading matches a terminal reading.
    ///
    /// Every value here is an input rather than a measurement, and the provenance string says so
    /// on the way to the screen.
    #[must_use]
    pub fn study_m0_defaults() -> Self {
        Self {
            declared_lift_bps: 800,
            // Small enough that traversal is negligible at any live venue; the readout prints the
            // probe's share of the reserve so a reader can check that rather than take it.
            fee_floor_probe_quote_atoms: LAMPORTS_PER_SOL / 1_000,
            intended_clip_quote_atoms: None,
            costs: DeclaredFixedCosts {
                provenance: "network fee 7,422 lamports per transaction x 2, the fee a landed \
                             PumpSwap sell paid in Study M0's fixture on 2026-08-21, declared by \
                             the operator and not measured for this coin; unrecovered rent \
                             declared as zero"
                    .to_owned(),
                per_transaction_quote_atoms: 7_422,
                transactions: 2,
                flat_route_quote_atoms: 0,
                unrecovered_rent_quote_atoms: 0,
            },
        }
    }

    fn request(&self) -> ReadoutRequest {
        ReadoutRequest {
            declared_lift_bps: self.declared_lift_bps,
            fee_floor_probe_quote_atoms: self.fee_floor_probe_quote_atoms,
            intended_clip_quote_atoms: self.intended_clip_quote_atoms,
            costs: self.costs.clone(),
        }
    }
}

/// One address the capture covered that named no venue this module could assemble, and why.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UnassembledVenue {
    pub address: String,
    pub reason: String,
}

/// The readouts one capture produced, keyed by mint, plus what it could not assemble.
///
/// This is mounted on the service the same way a derived Glass scene is: derived once, in memory,
/// and served byte-identically for as long as the process lives. It never grows a network client.
#[derive(Debug)]
pub struct MountedVenueReadouts {
    by_mint: BTreeMap<String, PreTradeReadout>,
    unassembled: Vec<UnassembledVenue>,
    provenance: String,
    context_slot: u64,
}

impl MountedVenueReadouts {
    /// Assembles every venue one capture's bytes support.
    ///
    /// A pool is bound to its mint by the pool account stating that mint itself. A bonding curve
    /// never names its mint, so it is bound only when the curve address is exactly the derived
    /// address of a mint the same capture carries — the derivation is recomputed here and a curve
    /// that matches no mint is reported unassembled rather than guessed at.
    ///
    /// # Errors
    ///
    /// Refuses a capture naming another contract, a body that is not a readable account response,
    /// and a capture carrying no fee-program configuration to take rates from.
    pub fn from_capture(
        capture: &VenueAccountsCapture,
        policy: &VenueReadoutPolicy,
    ) -> Result<Self, VenueReadoutError> {
        if capture.contract != VENUE_ACCOUNTS_CAPTURE_CONTRACT {
            return Err(VenueReadoutError::WrongCaptureContract {
                found: capture.contract.clone(),
            });
        }
        let response =
            read_multiple_accounts(capture.body.get().as_bytes(), &capture.requested_addresses)
                .map_err(|error| VenueReadoutError::UnreadableBody(error.to_string()))?;
        let mut by_mint = BTreeMap::new();
        let mut unassembled = Vec::new();
        let mints: Vec<String> = response
            .entries
            .iter()
            .filter(|entry| {
                entry
                    .account
                    .as_ref()
                    .is_some_and(|account| TokenMint::decode(account).is_ok())
            })
            .map(|entry| entry.address.clone())
            .collect();
        let mut claimed_mints: BTreeSet<String> = BTreeSet::new();

        for entry in &response.entries {
            let Some(account) = entry.account.as_ref() else {
                continue;
            };
            if let Ok(pool) = PumpSwapPool::decode(account) {
                match pool_readout(&response, &pool, capture, policy) {
                    Ok(readout) => {
                        claimed_mints.insert(pool.base_mint.clone());
                        by_mint.insert(pool.base_mint.clone(), readout);
                    }
                    Err(reason) => unassembled.push(UnassembledVenue {
                        address: entry.address.clone(),
                        reason,
                    }),
                }
                continue;
            }
            if let Ok(curve) = PumpBondingCurve::decode(account) {
                let bound = mints.iter().find_map(|mint| {
                    bonding_curve_derivation_bump(&entry.address, mint).map(|bump| (mint, bump))
                });
                let Some((mint, bump)) = bound else {
                    unassembled.push(UnassembledVenue {
                        address: entry.address.clone(),
                        reason: "this bonding curve decodes, and no mint in this capture derives \
                                 to its address. A curve account never names its mint, so nothing \
                                 here binds it to a coin and no readout is stated."
                            .to_owned(),
                    });
                    continue;
                };
                match curve_readout(&response, &curve, mint, bump, capture, policy) {
                    Ok(readout) => {
                        claimed_mints.insert(mint.clone());
                        by_mint.insert(mint.clone(), readout);
                    }
                    Err(reason) => unassembled.push(UnassembledVenue {
                        address: entry.address.clone(),
                        reason,
                    }),
                }
            }
        }
        Ok(Self {
            by_mint,
            unassembled,
            provenance: capture.provenance.clone(),
            context_slot: response.context_slot,
        })
    }

    /// The readout for one mint, if this capture's bytes supported one.
    #[must_use]
    pub fn get(&self, mint: &str) -> Option<&PreTradeReadout> {
        self.by_mint.get(mint)
    }

    /// Every mint this mount can answer for, in address order.
    #[must_use]
    pub fn mints(&self) -> Vec<&str> {
        self.by_mint.keys().map(String::as_str).collect()
    }

    #[must_use]
    pub fn unassembled(&self) -> &[UnassembledVenue] {
        &self.unassembled
    }

    #[must_use]
    pub fn provenance(&self) -> &str {
        &self.provenance
    }

    #[must_use]
    pub const fn context_slot(&self) -> u64 {
        self.context_slot
    }
}

/// Reads the tier tables off a fee configuration and picks rates the retained bytes support.
///
/// Where every retained table selects the same rates, nothing is chosen and the basis says so.
/// Where they disagree, no retained byte says which the program applies, so the **most expensive**
/// is used: erring against the trade is the only direction that cannot cost money it did not warn
/// about, and the basis says that too.
fn select_rates(
    config: &PumpFeeConfig,
    market_cap_quote_atoms: u128,
) -> Result<(FeeRatesBps, usize, TierBasis), String> {
    let per_table = config.per_table_rates(market_cap_quote_atoms);
    if per_table.iter().any(Option::is_none) {
        return Err(format!(
            "fee configuration {} carries a tier table with no row at market cap {market_cap_quote_atoms}",
            config.address
        ));
    }
    let first = per_table[0].ok_or_else(|| "empty tier table".to_owned())?;
    if per_table.iter().flatten().all(|rates| *rates == first) {
        return Ok((first, 0, TierBasis::EveryTableAgreed));
    }
    let (index, worst) = per_table
        .iter()
        .enumerate()
        .filter_map(|(index, rates)| rates.map(|rates| (index, rates)))
        .max_by_key(|(_, rates)| rates.lp + rates.protocol + rates.creator)
        .ok_or_else(|| "no tier table selected any row".to_owned())?;
    Ok((worst, index, TierBasis::WorstOfDisagreeingTables))
}

/// Turns the retained tier vectors into validated ladders a position can be located in.
fn ladders(
    config: &PumpFeeConfig,
    creator_applies: Option<bool>,
) -> Result<Vec<TierLadder>, String> {
    config
        .tier_tables
        .iter()
        .map(|table| {
            let rows = table
                .iter()
                .map(|row| {
                    Ok(TierRow {
                        threshold_quote_atoms: row.threshold_quote_atoms,
                        schedule: schedule_from(row.rates, creator_applies)?,
                    })
                })
                .collect::<Result<Vec<_>, String>>()?;
            TierLadder::new(rows).map_err(|error| error.to_string())
        })
        .collect()
}

/// Builds a fee schedule, keeping "the retained layout does not say" distinct from "no creator".
fn schedule_from(rates: FeeRatesBps, creator_applies: Option<bool>) -> Result<FeeSchedule, String> {
    let bps = |value: u64| -> Result<FeeBps, String> {
        FeeBps::new(u16::try_from(value).map_err(|_| format!("fee rate {value} is not a u16"))?)
            .map_err(|error| error.to_string())
    };
    Ok(FeeSchedule {
        lp: bps(rates.lp)?,
        protocol: bps(rates.protocol)?,
        creator: match creator_applies {
            Some(true) => CreatorFee::Charged(bps(rates.creator)?),
            Some(false) => CreatorFee::NotApplicable,
            None => CreatorFee::Unknown,
        },
    })
}

fn age(capture: &VenueAccountsCapture, context_slot: u64) -> StateAge {
    StateAge {
        context_slot,
        requested_commitment: capture.requested_commitment.clone(),
        chain_second: capture
            .chain_second_unix_s
            .map(|block_time_unix_s| ChainSecond {
                slot: context_slot,
                block_time_unix_s,
            }),
        local_receipt: LocalReceipt {
            clock_id: capture.clock_id.clone(),
            monotonic_ns: capture.received_monotonic_ns,
            wall_unix_ms: capture.received_at_unix_ms,
        },
    }
}

/// The declaration every readout built from a capture has to carry.
fn stated_address_list_note(capture: &VenueAccountsCapture) -> String {
    format!(
        "the address list is a declaration, not evidence: a getMultipleAccounts body is positional \
         and names no address, so the {} addresses this readout was decoded against come from the \
         capture and nothing in the retained bytes can check them",
        capture.requested_addresses.len()
    )
}

/// What this readout could not reconstruct about a pool. An empty list would mean nobody looked.
fn pool_gaps(capture: &VenueAccountsCapture, pool: &PumpSwapPool) -> Vec<String> {
    vec![
        stated_address_list_note(capture),
        format!(
            "pool byte {} carries {} quote atoms this decoder can locate and cannot name; it is in \
             the effective reserve because four landed fills say it must be, and omitting it would \
             overstate base-out by about 119 basis points in the flattering direction",
            joshi_sources::POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET,
            pool.unattributed_quote_side_reserve_atoms
        ),
        UNREAD_CHART_MARK.to_owned(),
        UNMODELLED_PRIORITY_FEE.to_owned(),
        UNMEASURED_TOKEN_ACCOUNT_RENT.to_owned(),
    ]
}

/// The same, for a bonding curve, whose retained layout varies by account length.
fn curve_gaps(capture: &VenueAccountsCapture, curve: &PumpBondingCurve) -> Vec<String> {
    vec![
        stated_address_list_note(capture),
        format!(
            "this curve account is {} bytes; bonding curves exist at 49, 115, 150, 151 and 256 \
             bytes and the shorter ones do not carry every field",
            curve.account_len
        ),
        "the market cap this tier row was selected at is the curve's virtual reserve ratio taken \
         against the mint's whole supply. It is arithmetic over observed bytes and not a figure \
         any account states."
            .to_owned(),
        UNREAD_CHART_MARK.to_owned(),
        UNMODELLED_PRIORITY_FEE.to_owned(),
        UNMEASURED_TOKEN_ACCOUNT_RENT.to_owned(),
    ]
}

const UNREAD_CHART_MARK: &str = "chart mark: no landed fill was read, so no chart mark is stated. An absent record is not a \
     zero and not the marginal price.";
const UNMODELLED_PRIORITY_FEE: &str = "priority fee and tip: not modelled. The declared network cost is a base fee only, and a \
     contested block costs more.";
const UNMEASURED_TOKEN_ACCOUNT_RENT: &str = "associated token account rent: whatever the operator declared. If this trade has to open a \
     new token account, that cost moves the small end of the break-even interval and nothing else.";

/// The four accounts a pool's state is composed from, each checked against the pool that named it.
fn pool_accounts(
    response: &AccountSetResponse,
    pool: &PumpSwapPool,
) -> Result<(TokenVault, TokenVault, TokenMint, PumpFeeConfig), String> {
    let need = |address: &str| -> Result<_, String> {
        response
            .require(address)
            .map_err(|error| format!("{address}: {error}"))
    };
    let base_vault = TokenVault::decode(need(&pool.pool_base_token_account)?)
        .map_err(|error| format!("base vault: {error}"))?;
    let quote_vault = TokenVault::decode(need(&pool.pool_quote_token_account)?)
        .map_err(|error| format!("quote vault: {error}"))?;
    if base_vault.owner != pool.address || quote_vault.owner != pool.address {
        return Err(format!(
            "a vault pool {} named is not owned by the pool",
            pool.address
        ));
    }
    if base_vault.amount == 0 {
        return Err(format!(
            "pool {} holds no base atoms, and a state with a zero reserve is not a state a quote \
             can be computed at",
            pool.address
        ));
    }
    let base_mint =
        TokenMint::decode(need(&pool.base_mint)?).map_err(|error| format!("base mint: {error}"))?;
    let fee_config = PumpFeeConfig::decode(need(PUMP_FEE_CONFIG_ADDRESS)?)
        .map_err(|error| format!("fee configuration: {error}"))?;
    Ok((base_vault, quote_vault, base_mint, fee_config))
}

fn pool_readout(
    response: &AccountSetResponse,
    pool: &PumpSwapPool,
    capture: &VenueAccountsCapture,
    policy: &VenueReadoutPolicy,
) -> Result<PreTradeReadout, String> {
    if pool.quote_mint != WRAPPED_SOL_MINT {
        return Err(format!(
            "pool {} quotes against {} rather than wrapped SOL; every declared cost in this \
             readout is in lamports and would be the wrong unit",
            pool.address, pool.quote_mint
        ));
    }
    let (base_vault, quote_vault, base_mint, fee_config) = pool_accounts(response, pool)?;
    let effective_quote = pool.effective_quote_atoms(quote_vault.amount);
    let market_cap = mul_div_u128(
        effective_quote,
        u128::from(base_mint.supply),
        u128::from(base_vault.amount),
        Rounding::Down,
    )
    .map_err(|error| format!("market cap: {error}"))?;

    let creator_applies = Some(pool.has_coin_creator());
    let (rates, applied_table_index, basis) = select_rates(&fee_config, market_cap)?;
    let standing = TierStanding::locate(
        &ladders(&fee_config, creator_applies)?,
        market_cap,
        applied_table_index,
        basis,
    )
    .map_err(|error| error.to_string())?;

    let mut unsupported = pool_gaps(capture, pool);
    if basis == TierBasis::WorstOfDisagreeingTables {
        unsupported.push(format!(
            "the retained fee tier tables select different rates at this market cap and no \
             retained byte says which the program applies; every number here uses table \
             {applied_table_index} because it is the most expensive, which errs against the trade \
             and never for it"
        ));
    }

    let state = ExactCurveState {
        formula: VenueKind::PumpSwapPool.formula(),
        base_atoms: u128::from(base_vault.amount),
        effective_quote_atoms: effective_quote,
        schedule: schedule_from(rates, creator_applies)?,
    };
    PreTradeReadout::build(
        pool.base_mint.clone(),
        VenueKind::PumpSwapPool,
        pool.address.clone(),
        format!(
            "the pool account states this base mint itself, and its address is {}",
            pool.self_derivation_bump().map_or_else(
                || "not the derived address of its own index, creator and mint pair at any bump \
                    this decoder tried, which is a fact about the pair and is stated rather than \
                    hidden"
                    .to_owned(),
                |bump| format!(
                    "the derived address of its own index, creator and mint pair at bump {bump}"
                )
            )
        ),
        state,
        QuoteReserveComposition::VaultBalancePlusLocatedTerm {
            quote_vault_atoms: u128::from(quote_vault.amount),
            located_term_atoms: u128::from(pool.unattributed_quote_side_reserve_atoms),
            located_term_offset: joshi_sources::POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET,
        },
        FeeRateSource::FeeProgramConfig {
            config_address: PUMP_FEE_CONFIG_ADDRESS.to_owned(),
            tables_agreed: basis == TierBasis::EveryTableAgreed,
            selected_at_market_cap_quote_atoms: market_cap,
        },
        (base_mint.decimals, QUOTE_DECIMALS),
        &policy.request(),
        age(capture, response.context_slot),
        // One capture is one observation. Two would be needed to say anything about drift, and
        // saying nothing is the honest answer rather than a zero.
        None,
        unsupported,
    )
    .map_err(|error| error.to_string())?
    .with_tier_standing(standing)
    .map_err(|error| error.to_string())
}

fn curve_readout(
    response: &AccountSetResponse,
    curve: &PumpBondingCurve,
    mint: &str,
    bump: u8,
    capture: &VenueAccountsCapture,
    policy: &VenueReadoutPolicy,
) -> Result<PreTradeReadout, String> {
    if curve.complete {
        return Err(format!(
            "the curve at {} is complete, so it is no longer the venue; quoting against its \
             reserves would price a market that does not trade",
            curve.address
        ));
    }
    if curve.virtual_base_atoms == 0 || curve.virtual_quote_atoms == 0 {
        return Err(format!(
            "the curve at {} states virtual reserves of {} base and {} quote atoms; a state with a \
             zero reserve is not a state a quote can be computed at",
            curve.address, curve.virtual_base_atoms, curve.virtual_quote_atoms
        ));
    }
    let base_mint = TokenMint::decode(
        response
            .require(mint)
            .map_err(|error| format!("{mint}: {error}"))?,
    )
    .map_err(|error| format!("base mint: {error}"))?;
    let fee_config = PumpFeeConfig::decode(
        response
            .require(PUMP_CURVE_FEE_CONFIG_ADDRESS)
            .map_err(|error| format!("{PUMP_CURVE_FEE_CONFIG_ADDRESS}: {error}"))?,
    )
    .map_err(|error| format!("curve fee configuration: {error}"))?;

    let market_cap = mul_div_u128(
        u128::from(curve.virtual_quote_atoms),
        u128::from(base_mint.supply),
        u128::from(curve.virtual_base_atoms),
        Rounding::Down,
    )
    .map_err(|error| format!("market cap: {error}"))?;
    let creator_applies = curve.creator_fee_applies();
    let (rates, applied_table_index, basis) = select_rates(&fee_config, market_cap)?;
    let standing = TierStanding::locate(
        &ladders(&fee_config, creator_applies)?,
        market_cap,
        applied_table_index,
        basis,
    )
    .map_err(|error| error.to_string())?;

    let mut unsupported = curve_gaps(capture, curve);
    if basis == TierBasis::WorstOfDisagreeingTables {
        unsupported.push(format!(
            "the retained curve fee tier tables select different rates at this market cap and no \
             retained byte says which applies; every number here uses table {applied_table_index} \
             because it is the most expensive"
        ));
    }

    let state = ExactCurveState {
        formula: VenueKind::PumpBondingCurve.formula(),
        base_atoms: u128::from(curve.virtual_base_atoms),
        effective_quote_atoms: u128::from(curve.virtual_quote_atoms),
        schedule: schedule_from(rates, creator_applies)?,
    };
    PreTradeReadout::build(
        mint.to_owned(),
        VenueKind::PumpBondingCurve,
        curve.address.clone(),
        format!(
            "the curve is the recomputed PDA([\"bonding-curve\", mint], Pump program) at bump \
             {bump}; nothing in the curve account itself names the mint"
        ),
        state,
        QuoteReserveComposition::CurveVirtualReserve {
            virtual_quote_atoms: u128::from(curve.virtual_quote_atoms),
        },
        FeeRateSource::FeeProgramConfig {
            config_address: PUMP_CURVE_FEE_CONFIG_ADDRESS.to_owned(),
            tables_agreed: basis == TierBasis::EveryTableAgreed,
            selected_at_market_cap_quote_atoms: market_cap,
        },
        (base_mint.decimals, QUOTE_DECIMALS),
        &policy.request(),
        age(capture, response.context_slot),
        None,
        unsupported,
    )
    .map_err(|error| error.to_string())?
    .with_tier_standing(standing)
    .map_err(|error| error.to_string())
}

// -------------------------------------------------------------------------------------------
// The wire.
//
// Every number crosses as a decimal string. The cockpit renders what it is given and computes
// nothing, so a value this side cannot state has to arrive as an explicit absence rather than as
// a blank or a zero — a blank is the shape a reader fills in themselves.
// -------------------------------------------------------------------------------------------

/// One held coin's readout, in the shape the cockpit renders.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VenueReadoutWire {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub mint: String,
    /// Human label for the deployed program this state belongs to.
    pub venue_kind: String,
    /// Stable machine label for the same thing.
    pub venue_kind_label: &'static str,
    pub venue_account: String,
    pub venue_binding: String,
    pub fee_floor_bps: String,
    pub fee_floor_probe_sol: String,
    pub declared_lift_bps: String,
    pub break_even_clip: BreakEvenWire,
    pub fee_tier: FeeTierWire,
    /// Set only when the retained tier tables disagreed and the more expensive one was used.
    /// `None` means they agreed, never that the question was not asked.
    pub pessimistic_tier_branch: Option<String>,
    pub state_age: StateAgeWire,
    pub declared_costs: String,
    pub unsupported: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum BreakEvenWire {
    #[serde(rename_all = "camelCase")]
    Interval {
        smallest_sol: String,
        largest_sol: String,
        smallest_hurdle_bps: String,
        largest_hurdle_bps: String,
    },
    /// "No clip breaks even" is an answer, and it arrives as one.
    #[serde(rename_all = "camelCase")]
    Refused { refusal: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum FeeTierWire {
    /// Boxed so the located case does not make every absence carry its width.
    Located(Box<LocatedTierWire>),
    #[serde(rename_all = "camelCase")]
    Absent { absence: String },
}

/// The row a market cap selects on the table the readout's rates were taken from.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LocatedTierWire {
    pub market_cap_sol: String,
    /// One-based, so it reads as "row 1 of 25".
    pub row_ordinal: String,
    pub row_count: String,
    pub threshold_sol: String,
    pub leg_bps: String,
    /// True when the first row is applying as the deployed fallback rather than because its own
    /// threshold was reached. Two situations with the same rates and different meanings.
    pub below_first_threshold: bool,
    pub next: NextTierWire,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum NextTierWire {
    #[serde(rename_all = "camelCase")]
    Row {
        row_ordinal: String,
        threshold_sol: String,
        gap_sol: String,
        /// The gap as basis points of the current market cap, or an absence at a zero cap.
        gap_bps_of_market_cap: Option<String>,
        leg_bps: String,
        direction: &'static str,
    },
    #[serde(rename_all = "camelCase")]
    Absent { absence: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StateAgeWire {
    pub context_slot: String,
    pub requested_commitment: String,
    pub chain_to_receipt: ChainToReceiptWire,
    /// Wall clock at which these bytes reached the machine that read them, in Unix milliseconds.
    /// The cockpit keeps subtracting this from its own clock for as long as the readout is up.
    pub received_at_unix_ms: String,
    pub clock_id: String,
    pub drift: DriftWire,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum ChainToReceiptWire {
    #[serde(rename_all = "camelCase")]
    Interval {
        earliest_ms: String,
        latest_ms: String,
    },
    #[serde(rename_all = "camelCase")]
    Absent { absence: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(untagged)]
pub enum DriftWire {
    #[serde(rename_all = "camelCase")]
    Measured {
        direction: &'static str,
        bps: String,
        elapsed_slots: String,
        elapsed_local_ms: String,
        bps_per_minute: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    Absent { absence: String },
}

/// Renders one readout onto the wire the cockpit reads.
#[must_use]
#[allow(clippy::too_many_lines)] // One field-for-field mapping is safer read in one place.
pub fn venue_readout_wire(readout: &PreTradeReadout) -> VenueReadoutWire {
    let sol = |atoms: u128| render_decimal(atoms, readout.quote_decimals);
    let bps = |value: Result<u128, joshi_market_math::stack::StackRefusal>| {
        value.map_or_else(
            |error| format!("refused: {error}"),
            |value| value.to_string(),
        )
    };
    let break_even_clip = match &readout.break_even_clips {
        Ok(range) => BreakEvenWire::Interval {
            smallest_sol: sol(range.smallest.clip_quote_in_atoms),
            largest_sol: sol(range.largest.clip_quote_in_atoms),
            smallest_hurdle_bps: bps(range.smallest.mark_lift.bps_ceil()),
            largest_hurdle_bps: bps(range.largest.mark_lift.bps_ceil()),
        },
        Err(error) => BreakEvenWire::Refused {
            refusal: error.to_string(),
        },
    };
    let fee_tier = readout.tier.as_ref().map_or_else(
        || FeeTierWire::Absent {
            absence:
                "The retained fee tier tables were not handed to this readout, so it does not \
                      say which row this market cap selects. That is a missing input and not a \
                      venue without tiers."
                    .to_owned(),
        },
        |standing| {
            let position = standing.applied();
            FeeTierWire::Located(Box::new(LocatedTierWire {
                market_cap_sol: sol(position.market_cap_quote_atoms),
                row_ordinal: (position.row_index + 1).to_string(),
                row_count: position.row_count.to_string(),
                threshold_sol: sol(position.threshold_quote_atoms),
                leg_bps: position
                    .leg_bps()
                    .map_or_else(|| "not observed".to_owned(), |value| value.to_string()),
                below_first_threshold: position.below_first_threshold,
                next: position.next.map_or_else(
                    || NextTierWire::Absent {
                        absence: "This is the top row. There is no further threshold to cross."
                            .to_owned(),
                    },
                    |next| NextTierWire::Row {
                        row_ordinal: (next.row_index + 1).to_string(),
                        threshold_sol: sol(next.threshold_quote_atoms),
                        gap_sol: sol(next.gap_quote_atoms),
                        gap_bps_of_market_cap: next
                            .gap_of_market_cap
                            .map(|ratio| bps(ratio.bps_ceil())),
                        leg_bps: next
                            .leg_bps()
                            .map_or_else(|| "not observed".to_owned(), |value| value.to_string()),
                        direction: match next.direction {
                            TierDirection::Cheaper => "cheaper",
                            TierDirection::Dearer => "dearer",
                            TierDirection::Unchanged => "unchanged",
                            TierDirection::NotComparable => "not_comparable",
                        },
                    },
                ),
            }))
        },
    );
    let pessimistic_tier_branch = readout.tier.as_ref().and_then(|standing| {
        (standing.basis == TierBasis::WorstOfDisagreeingTables).then(|| {
            let rates: Vec<String> = standing
                .per_table
                .iter()
                .map(|position| {
                    format!(
                        "table {} on row {} at {} bps a leg",
                        position.row_index,
                        position.row_index + 1,
                        position
                            .leg_bps()
                            .map_or_else(|| "an unobserved".to_owned(), |value| value.to_string())
                    )
                })
                .collect();
            format!(
                "The retained fee tier tables disagree here ({}) and no retained byte says which \
                 the program applies. Every number above uses the most expensive of them, which \
                 errs against the trade and never for it.",
                rates.join("; ")
            )
        })
    });
    let chain_to_receipt = match readout.age.chain_to_receipt() {
        Ok(Some(interval)) => ChainToReceiptWire::Interval {
            earliest_ms: interval.earliest_ms.to_string(),
            latest_ms: interval.latest_ms.to_string(),
        },
        Ok(None) => ChainToReceiptWire::Absent {
            absence: "The provider stated no blockTime for this slot, so the chain end of the age \
                      is an absent record rather than an age of zero."
                .to_owned(),
        },
        Err(error) => ChainToReceiptWire::Absent {
            absence: format!("Refused: {error}"),
        },
    };
    let drift = readout.drift.as_ref().map_or_else(
        || DriftWire::Absent {
            absence: "Not measured. One observation says nothing about how fast this venue moves, \
                      and a pool measured on 2026-08-21 drifted nine to ten basis points in thirty \
                      seconds."
                .to_owned(),
        },
        |measured| DriftWire::Measured {
            direction: match measured.direction {
                joshi_liquidity::readout::DriftDirection::Up => "up",
                joshi_liquidity::readout::DriftDirection::Down => "down",
                joshi_liquidity::readout::DriftDirection::Unchanged => "unchanged",
            },
            bps: bps(measured.magnitude.bps_ceil()),
            elapsed_slots: measured.elapsed_slots.to_string(),
            elapsed_local_ms: measured.elapsed_local_ms.to_string(),
            bps_per_minute: measured
                .bps_per_minute()
                .ok()
                .flatten()
                .map(|rate| rate.to_string()),
        },
    );
    VenueReadoutWire {
        contract: VENUE_READOUT_CONTRACT,
        schema_version: VENUE_READOUT_SCHEMA_VERSION,
        authority: "read_record_replay_only",
        mint: readout.mint.clone(),
        venue_kind: match readout.venue {
            VenueKind::PumpBondingCurve => "Pump bonding curve".to_owned(),
            VenueKind::PumpSwapPool => "Graduated PumpSwap pool".to_owned(),
        },
        venue_kind_label: readout.venue.label(),
        venue_account: readout.venue_account.clone(),
        venue_binding: readout.venue_binding.clone(),
        fee_floor_bps: bps(readout.fee_floor.venue_cost.bps_ceil()),
        fee_floor_probe_sol: sol(readout.fee_floor_probe_quote_atoms),
        declared_lift_bps: readout.declared_lift_bps.to_string(),
        break_even_clip,
        fee_tier,
        pessimistic_tier_branch,
        state_age: StateAgeWire {
            context_slot: readout.age.context_slot.to_string(),
            requested_commitment: readout.age.requested_commitment.clone(),
            chain_to_receipt,
            received_at_unix_ms: readout.age.local_receipt.wall_unix_ms.to_string(),
            clock_id: readout.age.local_receipt.clock_id.clone(),
            drift,
        },
        declared_costs: readout.costs.provenance.clone(),
        unsupported: readout.unsupported.clone(),
    }
}

/// Exactly why a capture could not be mounted.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum VenueReadoutError {
    #[error(
        "capture names contract {found}, not {VENUE_ACCOUNTS_CAPTURE_CONTRACT}; nothing was read \
         from it"
    )]
    WrongCaptureContract { found: String },
    #[error("the captured response body is not a readable account response: {0}")]
    UnreadableBody(String),
}
