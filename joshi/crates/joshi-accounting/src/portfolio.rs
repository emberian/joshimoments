//! A portfolio statement as a pure derivation from durable wallet observations.
//!
//! Every number a statement carries names the exact observations and durable commits it came
//! from. A balance is stated as a sum of observed transitions, and where the observations cannot
//! explain it the statement says so: an opening balance whose history was not observed is opening
//! inventory, not a claim of completeness. An absent price renders as absent, never zero, and no
//! aggregate value ever appears without the composition of price kinds beside it.

use std::collections::BTreeMap;

use joshi_domain::{
    AccountId, CommitSeq, ObservationId, StableString, UtcTimestamp, WireStringError, WireU64,
    WireU128,
};
use num_bigint::BigUint;
use num_rational::Ratio;
use num_traits::{One, Zero};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Stable wire contract of one derived portfolio statement.
pub const PORTFOLIO_STATEMENT_CONTRACT_VERSION: &str = "joshi.portfolio_statement.v1";

/// The exact stored observation and durable commit one derived number came from.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObservationRef {
    pub observation_id: ObservationId,
    pub commit_seq: CommitSeq,
}

/// The asset at one balance boundary.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AssetRef {
    /// Native lamports at the wallet's own system account. Nine decimals by protocol.
    Native,
    /// SPL token atoms. Decimals are as stated by the provider's token-balance rows, not assumed.
    Token { mint: StableString, decimals: u8 },
}

impl AssetRef {
    /// Decimals of this asset's atom unit.
    #[must_use]
    pub fn decimals(&self) -> u8 {
        match self {
            Self::Native => 9,
            Self::Token { decimals, .. } => *decimals,
        }
    }
}

/// One observed balance transition at one account boundary inside one retained transaction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BalanceEventV1 {
    pub provenance: ObservationRef,
    pub signature: StableString,
    pub slot: WireU64,
    pub transaction_index: Option<WireU64>,
    pub block_time_seconds: Option<WireU64>,
    pub asset: AssetRef,
    /// The token account at whose boundary the transition occurred; absent for the native account.
    pub boundary_account: Option<StableString>,
    pub pre_atoms: WireU64,
    pub post_atoms: WireU64,
}

impl BalanceEventV1 {
    fn boundary_key(&self) -> (AssetRef, Option<StableString>) {
        (self.asset.clone(), self.boundary_account.clone())
    }
}

/// How a price came to be known. There is no universal price; every mark names its kind.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PriceKind {
    /// A provider's asserted mark (for example a balance route's `token_price` field). This is a
    /// provider assertion, not a market observation.
    ProviderMark { provider: StableString },
    /// A marginal price computed from retained venue state (curve or pool bytes) at a named
    /// observation. Marginal: the price of the next infinitesimal unit, not of the whole holding.
    VenueMarginal { venue: StableString },
}

impl PriceKind {
    fn label(&self) -> &'static str {
        match self {
            Self::ProviderMark { .. } => "provider_mark",
            Self::VenueMarginal { .. } => "venue_marginal",
        }
    }
}

/// One labelled price object: kind, quote unit, provenance, and its own clock.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PriceObjectV1 {
    pub asset: AssetRef,
    #[serde(flatten)]
    pub kind: PriceKind,
    /// Quote unit this price is stated in, for example `USD`.
    pub quote: StableString,
    /// Price per whole token as a decimal string, retained verbatim where asserted.
    pub price_per_token: StableString,
    pub provenance: ObservationRef,
    pub as_of: UtcTimestamp,
}

/// A value computed from one labelled price, with its rounding stated.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QuoteValueV1 {
    pub quote: StableString,
    pub amount: StableString,
    /// Exact rounding applied to reach `amount`; never silent.
    pub rounding: StableString,
}

/// Whether a holding carries a price, and which one. Absent is absent, never zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum PriceStatus {
    Priced {
        price: Box<PriceObjectV1>,
        value: QuoteValueV1,
    },
    Absent {
        note: StableString,
    },
}

/// Where the observed transition chain starts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum OpeningInventory {
    /// The first observed event started from zero atoms; the whole balance is explained by
    /// observed transitions.
    ObservedZeroStart,
    /// The first observed event started from a nonzero balance whose history is unobserved.
    /// The statement explains the balance only from that event onward.
    UnobservedOpening { atoms: WireU64 },
}

/// One place where adjacent observed events fail to link post to pre exactly.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContinuityBreak {
    pub prior_signature: StableString,
    pub prior_post_atoms: WireU64,
    pub next_signature: StableString,
    pub next_pre_atoms: WireU64,
}

/// Whether the observed events explain the balance as an unbroken sum of transitions.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ChainContinuity {
    /// Every adjacent pair of observed events links post to pre exactly.
    Contiguous,
    /// The observed events do not all link; the balance between the named events is unexplained
    /// by these observations.
    Broken { breaks: Vec<ContinuityBreak> },
}

/// The chain coordinates and provenance a stated balance is exact at.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BalanceAsOf {
    pub slot: WireU64,
    pub block_time_seconds: Option<WireU64>,
    pub signature: StableString,
    pub provenance: ObservationRef,
}

/// The full derivation of one boundary balance from observed transitions.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HoldingDerivation {
    pub opening: OpeningInventory,
    pub continuity: ChainContinuity,
    /// First observation participating in the explanation; the balance is explained from this
    /// commit onward.
    pub explained_from: ObservationRef,
    pub explained_from_slot: WireU64,
    /// Every observed transition, in derived order, each with its own provenance.
    pub events: Vec<BalanceEventV1>,
}

/// One account boundary's balance with its complete derivation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BoundaryHolding {
    /// The token account this balance sits at; absent for the wallet's native account.
    pub boundary_account: Option<StableString>,
    /// Last observed post balance. Exact at `as_of`, not a claim about now.
    pub balance_atoms: WireU64,
    pub as_of: BalanceAsOf,
    pub derivation: HoldingDerivation,
}

/// One asset's holdings across all observed boundaries, with an optional labelled price.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HoldingV1 {
    pub asset: AssetRef,
    /// Sum of the boundary balances below; the boundaries carry the derivation.
    pub total_atoms: WireU128,
    pub boundaries: Vec<BoundaryHolding>,
    pub price: PriceStatus,
}

/// Token-leg inventory of a venue-native position.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LegInventory {
    /// The token legs are not derivable from the retained bytes alone; the reason names what is
    /// missing rather than pretending a number.
    NotDerivable { reason: StableString },
    /// Leg amounts derived from named observations, with the derivation stated.
    Stated {
        x_atoms: WireU64,
        y_atoms: WireU64,
        derivation: StableString,
        provenance: Vec<ObservationRef>,
    },
}

/// One Meteora DLMM position as its retained bytes state it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DlmmPositionLineV1 {
    pub position_address: StableString,
    pub lb_pair: StableString,
    pub owner: StableString,
    pub lower_bin_id: i32,
    /// Inclusive, as the position bytes state their own span.
    pub upper_bin_id: i32,
    pub bin_count: i64,
    /// Pending fees across the fixed bin slots; a floor on an extended position, not a total.
    pub pending_fee_x_atoms_floor: WireU64,
    pub pending_fee_y_atoms_floor: WireU64,
    pub last_updated_at_unix_seconds: i64,
    pub legs: LegInventory,
    pub provenance: ObservationRef,
}

/// A provider's assertion carried verbatim and labelled; never merged with derived numbers.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProviderAssertionV1 {
    pub provider: StableString,
    pub subject_asset: AssetRef,
    /// Provider field name, for example `tokenPnL`.
    pub field: StableString,
    pub value_verbatim: StableString,
    pub provenance: ObservationRef,
}

/// One signature page and how much of it the catalog's transaction observations cover.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SignaturePageCoverage {
    pub provenance: ObservationRef,
    /// Signatures the page listed.
    pub listed: u64,
    /// Listed signatures with a retained transaction observation in this catalog.
    pub fetched: u64,
    /// Listed signatures with no retained transaction observation. Known, unexplained.
    pub unfetched_signatures: Vec<StableString>,
}

/// The chain head observed during the sweep, for stating how far behind the balances are.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChainHeadRef {
    pub slot: WireU64,
    pub provenance: ObservationRef,
}

/// A named thing this statement cannot contain, and why. An absence is data, not a zero.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NamedAbsence {
    pub name: StableString,
    pub why: StableString,
}

/// What the observations cover, and by name what they cannot.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CoverageV1 {
    pub observed_slot_lower: Option<WireU64>,
    pub observed_slot_upper: Option<WireU64>,
    pub chain_head: Option<ChainHeadRef>,
    pub signature_pages: Vec<SignaturePageCoverage>,
    pub named_absences: Vec<NamedAbsence>,
    pub notes: Vec<StableString>,
}

/// One per-kind, per-quote sum over the priced holdings only.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PricedSum {
    pub price_kind: StableString,
    pub quote: StableString,
    pub amount: StableString,
    pub rounding: StableString,
    pub holdings: u64,
}

/// Value composition. There is deliberately no single total field: a sum only ever appears next
/// to the price kinds that produced it and the count of holdings it excludes.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ValuationCompositionV1 {
    pub priced_sums: Vec<PricedSum>,
    pub unpriced_holdings: u64,
    pub composition_note: StableString,
}

/// The catalog cutoff this statement was derived at.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CatalogCutoff {
    pub commit_seq: CommitSeq,
    pub committed_at: UtcTimestamp,
}

/// One derived portfolio statement.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PortfolioStatementV1 {
    pub contract_version: StableString,
    pub wallet: AccountId,
    pub catalog_cutoff: CatalogCutoff,
    pub holdings: Vec<HoldingV1>,
    pub positions: Vec<DlmmPositionLineV1>,
    pub provider_assertions: Vec<ProviderAssertionV1>,
    pub valuation: ValuationCompositionV1,
    pub coverage: CoverageV1,
}

/// Everything a statement derivation is allowed to consume. All of it is observation-backed or an
/// explicit label; the derivation adds nothing that is not here.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioInput {
    pub wallet: AccountId,
    pub catalog_cutoff: CatalogCutoff,
    pub balance_events: Vec<BalanceEventV1>,
    pub prices: Vec<PriceObjectV1>,
    pub positions: Vec<DlmmPositionLineV1>,
    pub provider_assertions: Vec<ProviderAssertionV1>,
    pub signature_pages: Vec<SignaturePageCoverage>,
    pub chain_head: Option<ChainHeadRef>,
    pub extra_absences: Vec<NamedAbsence>,
    pub notes: Vec<StableString>,
}

/// A statement refused rather than derived wrongly.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PortfolioError {
    /// Two observations state the same signature at the same boundary with different balances.
    #[error(
        "conflicting observations of signature {signature} at one boundary: \
         {first_pre}->{first_post} versus {second_pre}->{second_post}"
    )]
    ConflictingObservations {
        signature: String,
        first_pre: u64,
        first_post: u64,
        second_pre: u64,
        second_post: u64,
    },
    /// Boundary balances for one asset overflowed the aggregate width.
    #[error("aggregate balance overflowed for one asset")]
    AggregateOverflow,
    /// A price string could not be read as a plain non-negative decimal.
    #[error("price for one asset is not a plain non-negative decimal: {value:?}")]
    MalformedPrice { value: String },
    /// An internally constructed label violated the shared wire contract.
    #[error("derived label violated the wire contract: {0}")]
    Label(#[from] WireStringError),
}

/// Number of fractional digits stated values are floored to.
const VALUE_ROUNDING_DP: usize = 9;
const VALUE_ROUNDING_NOTE: &str = "floor to 9 decimal places";

/// Derives one portfolio statement from durable observations, refusing rather than guessing.
///
/// # Errors
///
/// Returns [`PortfolioError`] when observations conflict, an aggregate overflows, or a supplied
/// price is not a plain decimal. Partial observation coverage is not an error: it is stated.
pub fn derive_statement(input: PortfolioInput) -> Result<PortfolioStatementV1, PortfolioError> {
    let PortfolioInput {
        wallet,
        catalog_cutoff,
        balance_events,
        prices,
        positions,
        provider_assertions,
        signature_pages,
        chain_head,
        extra_absences,
        mut notes,
    } = input;

    let (per_asset, slot_lower, slot_upper) = boundary_holdings(balance_events, &mut notes)?;

    let price_by_asset: BTreeMap<AssetRef, PriceObjectV1> = prices
        .into_iter()
        .map(|price| (price.asset.clone(), price))
        .collect();

    let (holdings, priced_sums, unpriced) = price_holdings(per_asset, &price_by_asset)?;

    let priced_sums = priced_sums
        .into_iter()
        .map(|((price_kind, quote), (sum, count))| {
            Ok(PricedSum {
                price_kind: StableString::new(price_kind)?,
                quote: StableString::new(quote)?,
                amount: StableString::new(render_floor(&sum, VALUE_ROUNDING_DP))?,
                rounding: StableString::new(VALUE_ROUNDING_NOTE)?,
                holdings: count,
            })
        })
        .collect::<Result<Vec<_>, PortfolioError>>()?;
    let composition_note = if priced_sums.is_empty() {
        format!("no priced sum is stated: all {unpriced} holdings are unpriced in this catalog")
    } else {
        format!(
            "sums cover priced holdings only, split by price kind; {unpriced} holding(s) carry \
             no price and are excluded, not zero"
        )
    };

    let mut named_absences = structural_absences(positions.is_empty())?;
    named_absences.extend(extra_absences);

    Ok(PortfolioStatementV1 {
        contract_version: StableString::new(PORTFOLIO_STATEMENT_CONTRACT_VERSION)?,
        wallet,
        catalog_cutoff,
        holdings,
        positions,
        provider_assertions,
        valuation: ValuationCompositionV1 {
            priced_sums,
            unpriced_holdings: unpriced,
            composition_note: StableString::new(composition_note)?,
        },
        coverage: CoverageV1 {
            observed_slot_lower: slot_lower.map(WireU64::new),
            observed_slot_upper: slot_upper.map(WireU64::new),
            chain_head,
            signature_pages,
            named_absences,
            notes,
        },
    })
}

/// Groups events per boundary and reconciles each group into one derived holding.
type BoundaryHoldings = (
    BTreeMap<AssetRef, Vec<BoundaryHolding>>,
    Option<u64>,
    Option<u64>,
);

fn boundary_holdings(
    balance_events: Vec<BalanceEventV1>,
    notes: &mut Vec<StableString>,
) -> Result<BoundaryHoldings, PortfolioError> {
    let mut boundaries: BTreeMap<(AssetRef, Option<StableString>), Vec<BalanceEventV1>> =
        BTreeMap::new();
    for event in balance_events {
        boundaries
            .entry(event.boundary_key())
            .or_default()
            .push(event);
    }
    let mut per_asset: BTreeMap<AssetRef, Vec<BoundaryHolding>> = BTreeMap::new();
    let mut slot_lower: Option<u64> = None;
    let mut slot_upper: Option<u64> = None;
    for ((asset, boundary_account), events) in boundaries {
        let events = dedupe_events(events, notes)?;
        let (ordered, continuity) = order_events(events);
        let (Some(first), Some(last)) = (ordered.first(), ordered.last()) else {
            continue;
        };
        for event in &ordered {
            let slot = event.slot.get();
            slot_lower = Some(slot_lower.map_or(slot, |low| low.min(slot)));
            slot_upper = Some(slot_upper.map_or(slot, |high| high.max(slot)));
        }
        let opening = if first.pre_atoms.get() == 0 {
            OpeningInventory::ObservedZeroStart
        } else {
            OpeningInventory::UnobservedOpening {
                atoms: first.pre_atoms,
            }
        };
        let holding = BoundaryHolding {
            boundary_account,
            balance_atoms: last.post_atoms,
            as_of: BalanceAsOf {
                slot: last.slot,
                block_time_seconds: last.block_time_seconds,
                signature: last.signature.clone(),
                provenance: last.provenance.clone(),
            },
            derivation: HoldingDerivation {
                opening,
                continuity,
                explained_from: first.provenance.clone(),
                explained_from_slot: first.slot,
                events: ordered,
            },
        };
        per_asset.entry(asset).or_default().push(holding);
    }
    Ok((per_asset, slot_lower, slot_upper))
}

/// Priced holdings plus the running per-kind sums and the count of unpriced holdings.
type PricedHoldings = (
    Vec<HoldingV1>,
    BTreeMap<(String, String), (Ratio<BigUint>, u64)>,
    u64,
);

fn price_holdings(
    per_asset: BTreeMap<AssetRef, Vec<BoundaryHolding>>,
    price_by_asset: &BTreeMap<AssetRef, PriceObjectV1>,
) -> Result<PricedHoldings, PortfolioError> {
    let mut holdings = Vec::new();
    let mut priced_sums: BTreeMap<(String, String), (Ratio<BigUint>, u64)> = BTreeMap::new();
    let mut unpriced = 0_u64;
    for (asset, asset_boundaries) in per_asset {
        let mut total: u128 = 0;
        for boundary in &asset_boundaries {
            total = total
                .checked_add(u128::from(boundary.balance_atoms.get()))
                .ok_or(PortfolioError::AggregateOverflow)?;
        }
        let price = if let Some(price) = price_by_asset.get(&asset) {
            let value = quote_value(total, asset.decimals(), price)?;
            let key = (
                price.kind.label().to_owned(),
                price.quote.as_str().to_owned(),
            );
            let entry = priced_sums.entry(key).or_insert_with(|| (Ratio::zero(), 0));
            entry.0 += value_ratio(total, asset.decimals(), price)?;
            entry.1 += 1;
            PriceStatus::Priced {
                price: Box::new(price.clone()),
                value,
            }
        } else {
            unpriced += 1;
            PriceStatus::Absent {
                note: StableString::new("no price observation for this asset in the catalog")?,
            }
        };
        holdings.push(HoldingV1 {
            asset,
            total_atoms: WireU128::new(total),
            boundaries: asset_boundaries,
            price,
        });
    }
    Ok((holdings, priced_sums, unpriced))
}

/// The absences every statement must name because they are properties of the observation
/// surface itself, not of any particular catalog.
fn structural_absences(no_positions: bool) -> Result<Vec<NamedAbsence>, PortfolioError> {
    let mut named_absences = vec![NamedAbsence {
        name: StableString::new("venue_resident_open_orders")?,
        why: StableString::new(
            "a resting order held on a venue's book is not observable from wallet-scoped \
             on-chain observations; no order row can appear here, present or absent",
        )?,
    }];
    if no_positions {
        named_absences.push(NamedAbsence {
            name: StableString::new("dlmm_position_accounts")?,
            why: StableString::new(
                "no DLMM position account bytes are retained in this catalog; a live position \
                 is absent from this statement, not absent from the world",
            )?,
        });
    }
    named_absences.push(NamedAbsence {
        name: StableString::new("unlisted_token_accounts")?,
        why: StableString::new(
            "a mint with no balance-affecting transaction among the retained observations has \
             no row; absence of a row is not a zero-balance claim",
        )?,
    });
    Ok(named_absences)
}

/// Drops exact duplicate observations of one signature; refuses conflicting ones.
fn dedupe_events(
    events: Vec<BalanceEventV1>,
    notes: &mut Vec<StableString>,
) -> Result<Vec<BalanceEventV1>, PortfolioError> {
    let mut seen: BTreeMap<StableString, (WireU64, WireU64)> = BTreeMap::new();
    let mut kept = Vec::new();
    for event in events {
        match seen.get(&event.signature) {
            None => {
                seen.insert(event.signature.clone(), (event.pre_atoms, event.post_atoms));
                kept.push(event);
            }
            Some(&(pre, post)) => {
                if pre == event.pre_atoms && post == event.post_atoms {
                    notes.push(StableString::new(format!(
                        "duplicate observation of signature {} deduplicated (identical balances)",
                        event.signature
                    ))?);
                } else {
                    return Err(PortfolioError::ConflictingObservations {
                        signature: event.signature.as_str().to_owned(),
                        first_pre: pre.get(),
                        first_post: post.get(),
                        second_pre: event.pre_atoms.get(),
                        second_post: event.post_atoms.get(),
                    });
                }
            }
        }
    }
    Ok(kept)
}

/// Orders one boundary's events and states whether they chain post to pre exactly.
///
/// Slot then transaction index is the primary order. When that order does not chain (same-slot
/// events without an index), a full post-to-pre linking with non-decreasing slots is accepted as
/// the derived order because the chain constraint itself is the ordering evidence; otherwise the
/// sorted order stands and the breaks are reported, never repaired.
fn order_events(mut events: Vec<BalanceEventV1>) -> (Vec<BalanceEventV1>, ChainContinuity) {
    events.sort_by(|left, right| {
        (
            left.slot.get(),
            left.transaction_index.map_or(u64::MAX, WireU64::get),
            left.signature.as_str(),
        )
            .cmp(&(
                right.slot.get(),
                right.transaction_index.map_or(u64::MAX, WireU64::get),
                right.signature.as_str(),
            ))
    });
    let breaks = continuity_breaks(&events);
    if breaks.is_empty() {
        return (events, ChainContinuity::Contiguous);
    }
    if let Some(linked) = link_by_balance(&events) {
        return (linked, ChainContinuity::Contiguous);
    }
    (events, ChainContinuity::Broken { breaks })
}

fn continuity_breaks(events: &[BalanceEventV1]) -> Vec<ContinuityBreak> {
    events
        .windows(2)
        .filter(|pair| pair[0].post_atoms != pair[1].pre_atoms)
        .map(|pair| ContinuityBreak {
            prior_signature: pair[0].signature.clone(),
            prior_post_atoms: pair[0].post_atoms,
            next_signature: pair[1].signature.clone(),
            next_pre_atoms: pair[1].pre_atoms,
        })
        .collect()
}

/// Attempts a complete post-to-pre chain over all events with non-decreasing slots.
fn link_by_balance(events: &[BalanceEventV1]) -> Option<Vec<BalanceEventV1>> {
    let mut remaining: Vec<BalanceEventV1> = events.to_vec();
    // A chain head is an event whose pre balance is no other event's post balance.
    let head = remaining.iter().position(|candidate| {
        !remaining.iter().any(|other| {
            other.signature != candidate.signature && other.post_atoms == candidate.pre_atoms
        })
    })?;
    let mut ordered = vec![remaining.swap_remove(head)];
    while !remaining.is_empty() {
        let current_post = ordered.last()?.post_atoms;
        let next = remaining
            .iter()
            .position(|candidate| candidate.pre_atoms == current_post)?;
        ordered.push(remaining.swap_remove(next));
    }
    let slots_non_decreasing = ordered
        .windows(2)
        .all(|pair| pair[0].slot.get() <= pair[1].slot.get());
    (slots_non_decreasing && continuity_breaks(&ordered).is_empty()).then_some(ordered)
}

/// Parses a plain non-negative decimal string into an exact ratio.
fn decimal_ratio(value: &str) -> Option<Ratio<BigUint>> {
    let (integer, fraction) = value.split_once('.').unwrap_or((value, ""));
    if integer.is_empty() && fraction.is_empty() {
        return None;
    }
    if !integer.chars().all(|digit| digit.is_ascii_digit())
        || !fraction.chars().all(|digit| digit.is_ascii_digit())
    {
        return None;
    }
    let digits: String = [integer, fraction].concat();
    let numerator = digits.parse::<BigUint>().ok()?;
    let denominator = BigUint::from(10_u32).pow(u32::try_from(fraction.len()).ok()?);
    Some(Ratio::new(numerator, denominator))
}

fn value_ratio(
    atoms: u128,
    decimals: u8,
    price: &PriceObjectV1,
) -> Result<Ratio<BigUint>, PortfolioError> {
    let per_token =
        decimal_ratio(price.price_per_token.as_str()).ok_or(PortfolioError::MalformedPrice {
            value: price.price_per_token.as_str().to_owned(),
        })?;
    let atom_scale = Ratio::new(
        BigUint::one(),
        BigUint::from(10_u32).pow(u32::from(decimals)),
    );
    Ok(per_token * Ratio::from(BigUint::from(atoms)) * atom_scale)
}

fn quote_value(
    atoms: u128,
    decimals: u8,
    price: &PriceObjectV1,
) -> Result<QuoteValueV1, PortfolioError> {
    let exact = value_ratio(atoms, decimals, price)?;
    Ok(QuoteValueV1 {
        quote: price.quote.clone(),
        amount: StableString::new(render_floor(&exact, VALUE_ROUNDING_DP))?,
        rounding: StableString::new(VALUE_ROUNDING_NOTE)?,
    })
}

/// Renders a non-negative ratio floored to `dp` fractional digits, trailing zeros trimmed.
fn render_floor(value: &Ratio<BigUint>, dp: usize) -> String {
    let scale = BigUint::from(10_u32).pow(u32::try_from(dp).unwrap_or(u32::MAX));
    let scaled = (value * Ratio::from(scale)).floor().to_integer();
    let digits = scaled.to_string();
    let (integer, fraction) = if digits.len() > dp {
        let split = digits.len() - dp;
        (digits[..split].to_owned(), digits[split..].to_owned())
    } else {
        ("0".to_owned(), format!("{digits:0>dp$}"))
    };
    let fraction = fraction.trim_end_matches('0');
    if fraction.is_empty() {
        integer
    } else {
        format!("{integer}.{fraction}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obs(id: &str, seq: u64) -> ObservationRef {
        ObservationRef {
            observation_id: ObservationId::new(id).unwrap(),
            commit_seq: CommitSeq::new(seq),
        }
    }

    fn stable(value: &str) -> StableString {
        StableString::new(value).unwrap()
    }

    fn token() -> AssetRef {
        AssetRef::Token {
            mint: stable("MintAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
            decimals: 6,
        }
    }

    fn event(
        signature: &str,
        slot: u64,
        index: Option<u64>,
        pre: u64,
        post: u64,
    ) -> BalanceEventV1 {
        BalanceEventV1 {
            provenance: obs(&format!("obs:{signature}"), 1),
            signature: stable(signature),
            slot: WireU64::new(slot),
            transaction_index: index.map(WireU64::new),
            block_time_seconds: Some(WireU64::new(1_787_000_000)),
            asset: token(),
            boundary_account: Some(stable("TokenAccountAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")),
            pre_atoms: WireU64::new(pre),
            post_atoms: WireU64::new(post),
        }
    }

    fn input(events: Vec<BalanceEventV1>) -> PortfolioInput {
        PortfolioInput {
            wallet: AccountId::new("solana.account:WalletAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                .unwrap(),
            catalog_cutoff: CatalogCutoff {
                commit_seq: CommitSeq::new(1),
                committed_at: "2026-08-21T00:00:00.000000Z".parse().unwrap(),
            },
            balance_events: events,
            prices: Vec::new(),
            positions: Vec::new(),
            provider_assertions: Vec::new(),
            signature_pages: Vec::new(),
            chain_head: None,
            extra_absences: Vec::new(),
            notes: Vec::new(),
        }
    }

    #[test]
    fn contiguous_chain_explains_balance_from_zero() {
        let statement = derive_statement(input(vec![
            event("sig-b", 20, Some(1), 100, 250),
            event("sig-a", 10, Some(5), 0, 100),
        ]))
        .unwrap();
        assert_eq!(statement.holdings.len(), 1);
        let holding = &statement.holdings[0];
        assert_eq!(holding.total_atoms.get(), 250);
        let boundary = &holding.boundaries[0];
        assert_eq!(boundary.balance_atoms.get(), 250);
        assert_eq!(boundary.as_of.signature, stable("sig-b"));
        assert_eq!(
            boundary.derivation.opening,
            OpeningInventory::ObservedZeroStart
        );
        assert_eq!(boundary.derivation.continuity, ChainContinuity::Contiguous);
        assert_eq!(boundary.derivation.explained_from_slot.get(), 10);
    }

    #[test]
    fn nonzero_start_is_unobserved_opening_inventory() {
        let statement = derive_statement(input(vec![event("sig-a", 10, Some(0), 40, 90)])).unwrap();
        let boundary = &statement.holdings[0].boundaries[0];
        assert_eq!(
            boundary.derivation.opening,
            OpeningInventory::UnobservedOpening {
                atoms: WireU64::new(40)
            }
        );
    }

    #[test]
    fn broken_chain_is_reported_not_repaired() {
        let statement = derive_statement(input(vec![
            event("sig-a", 10, Some(0), 0, 100),
            event("sig-b", 20, Some(0), 170, 200),
        ]))
        .unwrap();
        let boundary = &statement.holdings[0].boundaries[0];
        match &boundary.derivation.continuity {
            ChainContinuity::Broken { breaks } => {
                assert_eq!(breaks.len(), 1);
                assert_eq!(breaks[0].prior_post_atoms.get(), 100);
                assert_eq!(breaks[0].next_pre_atoms.get(), 170);
            }
            ChainContinuity::Contiguous => panic!("gap must not read as contiguous"),
        }
        assert_eq!(boundary.balance_atoms.get(), 200);
    }

    #[test]
    fn same_slot_events_without_index_link_by_balance() {
        let statement = derive_statement(input(vec![
            event("sig-z", 10, None, 100, 250),
            event("sig-a", 10, None, 0, 100),
        ]))
        .unwrap();
        let boundary = &statement.holdings[0].boundaries[0];
        assert_eq!(boundary.derivation.continuity, ChainContinuity::Contiguous);
        assert_eq!(boundary.derivation.events[0].signature, stable("sig-a"));
        assert_eq!(boundary.balance_atoms.get(), 250);
    }

    #[test]
    fn duplicate_identical_observation_deduplicates_with_a_note() {
        let statement = derive_statement(input(vec![
            event("sig-a", 10, Some(0), 0, 100),
            event("sig-a", 10, Some(0), 0, 100),
        ]))
        .unwrap();
        assert_eq!(
            statement.holdings[0].boundaries[0].derivation.events.len(),
            1
        );
        assert!(
            statement
                .coverage
                .notes
                .iter()
                .any(|note| note.as_str().contains("deduplicated"))
        );
    }

    #[test]
    fn conflicting_duplicate_observation_is_refused() {
        let error = derive_statement(input(vec![
            event("sig-a", 10, Some(0), 0, 100),
            event("sig-a", 10, Some(0), 0, 150),
        ]))
        .unwrap_err();
        assert!(matches!(
            error,
            PortfolioError::ConflictingObservations { .. }
        ));
    }

    #[test]
    fn absent_price_renders_absent_and_no_total_is_stated() {
        let statement = derive_statement(input(vec![event("sig-a", 10, Some(0), 0, 100)])).unwrap();
        assert!(matches!(
            statement.holdings[0].price,
            PriceStatus::Absent { .. }
        ));
        assert!(statement.valuation.priced_sums.is_empty());
        assert_eq!(statement.valuation.unpriced_holdings, 1);
        let json = serde_json::to_value(&statement).unwrap();
        assert!(json.get("totalValue").is_none());
        assert!(
            statement
                .valuation
                .composition_note
                .as_str()
                .contains("no priced sum")
        );
    }

    #[test]
    fn provider_mark_prices_one_holding_and_sum_carries_composition() {
        let mut portfolio = input(vec![event("sig-a", 10, Some(0), 0, 2_500_000)]);
        portfolio.prices = vec![PriceObjectV1 {
            asset: token(),
            kind: PriceKind::ProviderMark {
                provider: stable("provider-x"),
            },
            quote: stable("USD"),
            price_per_token: stable("0.21"),
            provenance: obs("obs:price", 2),
            as_of: "2026-08-21T00:00:00.000000Z".parse().unwrap(),
        }];
        let statement = derive_statement(portfolio).unwrap();
        match &statement.holdings[0].price {
            PriceStatus::Priced { value, .. } => {
                assert_eq!(value.amount, stable("0.525"));
                assert_eq!(value.rounding, stable(VALUE_ROUNDING_NOTE));
            }
            PriceStatus::Absent { .. } => panic!("price was supplied"),
        }
        assert_eq!(statement.valuation.priced_sums.len(), 1);
        let sum = &statement.valuation.priced_sums[0];
        assert_eq!(sum.price_kind, stable("provider_mark"));
        assert_eq!(sum.amount, stable("0.525"));
        assert_eq!(sum.holdings, 1);
        assert_eq!(statement.valuation.unpriced_holdings, 0);
    }

    #[test]
    fn structural_absences_name_the_resting_order_and_missing_positions() {
        let statement = derive_statement(input(vec![event("sig-a", 10, Some(0), 0, 100)])).unwrap();
        let names: Vec<&str> = statement
            .coverage
            .named_absences
            .iter()
            .map(|absence| absence.name.as_str())
            .collect();
        assert!(names.contains(&"venue_resident_open_orders"));
        assert!(names.contains(&"dlmm_position_accounts"));
        assert!(names.contains(&"unlisted_token_accounts"));
    }

    #[test]
    fn malformed_price_is_refused_not_coerced() {
        let mut portfolio = input(vec![event("sig-a", 10, Some(0), 0, 100)]);
        portfolio.prices = vec![PriceObjectV1 {
            asset: token(),
            kind: PriceKind::ProviderMark {
                provider: stable("provider-x"),
            },
            quote: stable("USD"),
            price_per_token: stable("1e-3"),
            provenance: obs("obs:price", 2),
            as_of: "2026-08-21T00:00:00.000000Z".parse().unwrap(),
        }];
        assert!(matches!(
            derive_statement(portfolio),
            Err(PortfolioError::MalformedPrice { .. })
        ));
    }

    #[test]
    fn native_and_token_boundaries_stay_separate_holdings() {
        let mut native = event("sig-a", 10, Some(0), 5, 7);
        native.asset = AssetRef::Native;
        native.boundary_account = None;
        let statement =
            derive_statement(input(vec![native, event("sig-a", 10, Some(0), 0, 100)])).unwrap();
        assert_eq!(statement.holdings.len(), 2);
    }
}
