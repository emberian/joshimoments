//! A would-quote: exact arithmetic over retained bytes, carrying the age that makes it readable.
//!
//! A would-quote is one sentence — *at this slot, from these bytes, this is the quote* — plus
//! everything a person needs to check that sentence: which retained observation each input came
//! from, which slot the provider evaluated at, what the chain said the time was, when this process
//! received the bytes, and the exact interval between those two clocks.
//!
//! It is not an order, not advice, not a fill, not an execution estimate, and it produces no profit
//! or loss. A quote without its staleness would be a lie by omission, so the age is a required
//! field rather than an annotation, and it is an interval rather than a point because the chain
//! timestamp it starts from has one-second resolution.

use core::fmt::Write as _;

use joshi_domain::ObservationId;
use thiserror::Error;

use crate::{
    fee::{CreatorFee, FeeBreakdown, FeeSchedule},
    quote::{QuoteCalculation, QuoteOutcome, QuoteRefusal, QuoteSize, SpotQuote},
    render::{array, integer, object, quoted},
};

/// Stable contract of the rendered would-quote artifact.
pub const WOULD_QUOTE_CONTRACT: &str = "joshi.market_math.would_quote.v1";
/// The only authority any part of this crate has ever held.
pub const WOULD_QUOTE_AUTHORITY: &str = "read_only_no_execution";

/// What a would-quote refuses to be, stated in the artifact rather than only in a comment.
pub const NOT_AN_EXECUTION: &str = "A would-quote is an arithmetic statement about retained bytes. \
No fill is inferred, no order exists or is implied, no counterfactual execution is claimed, and no \
profit or loss is produced. Nothing in this artifact was, or could be, submitted anywhere.";

/// What the age field measures.
pub const AGE_MEASURES: &str = "Elapsed local wall-clock time from the chain-reported timestamp of \
the slot at which the provider evaluated this query, to the instant this process finished reading \
the response body.";

/// What the age field does not measure, kept next to it so the number is never read alone.
pub const AGE_DOES_NOT_MEASURE: &str = "This is not provider latency and not a network round trip. \
Solana blockTime is a stake-weighted validator report at whole-second resolution, not a \
measurement taken by this process, so the interval also absorbs that one-second quantization, any \
offset between this host's clock and the validators' reported clocks, provider processing, and \
network transit. It is also not the age of the pool state: an account may have last changed many \
slots before the slot it was read at.";

/// The part of the age that the requested commitment puts there by construction.
pub const AGE_COMMITMENT_NOTE: &str = "The requested commitment is inside this interval. A read at \
`finalized` is evaluated at a slot roughly a finalization depth behind the chain tip, so several \
seconds of that interval are the cost of asking for a slot that cannot be rolled back, not \
slowness anywhere. A quote read at a shallower commitment would be younger and less settled.";

/// The chain's own whole-second report of when a slot happened.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ChainSecond {
    pub slot: u64,
    /// `blockTime` exactly as the provider stated it. No sub-second component exists.
    pub block_time_unix_s: i64,
}

impl ChainSecond {
    /// Earliest instant consistent with the chain's whole-second report, in Unix milliseconds.
    ///
    /// # Errors
    ///
    /// Refuses a timestamp whose millisecond form overflows.
    pub fn lower_unix_ms(self) -> Result<i64, WouldQuoteError> {
        self.block_time_unix_s
            .checked_mul(1_000)
            .ok_or(WouldQuoteError::ClockOutOfRange)
    }

    /// First instant after the chain's whole-second report, in Unix milliseconds.
    ///
    /// # Errors
    ///
    /// Refuses a timestamp whose millisecond form overflows.
    pub fn upper_unix_ms(self) -> Result<i64, WouldQuoteError> {
        self.lower_unix_ms()?
            .checked_add(1_000)
            .ok_or(WouldQuoteError::ClockOutOfRange)
    }
}

/// The local clocks that bracket the instant the response body finished arriving.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalReceipt {
    /// Identity of the monotonic clock, which is meaningless across processes without it.
    pub clock_id: String,
    pub monotonic_ns: u64,
    pub wall_unix_ms: i64,
}

/// The exact interval between chain time and local receipt.
///
/// It is an interval and not a scalar because the chain end of it has one-second resolution. Both
/// bounds are reported; collapsing them to a single number would state a precision the bytes do not
/// support.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ChainToReceiptAge {
    /// Smallest age consistent with the chain's report. Exclusive.
    pub earliest_ms: i64,
    /// Largest age consistent with the chain's report. Inclusive.
    pub latest_ms: i64,
}

impl ChainToReceiptAge {
    /// Measures the interval between one chain second and one local receipt.
    ///
    /// # Errors
    ///
    /// Refuses clocks whose difference overflows.
    pub fn measure(chain: ChainSecond, receipt: &LocalReceipt) -> Result<Self, WouldQuoteError> {
        let earliest_ms = receipt
            .wall_unix_ms
            .checked_sub(chain.upper_unix_ms()?)
            .ok_or(WouldQuoteError::ClockOutOfRange)?;
        let latest_ms = receipt
            .wall_unix_ms
            .checked_sub(chain.lower_unix_ms()?)
            .ok_or(WouldQuoteError::ClockOutOfRange)?;
        Ok(Self {
            earliest_ms,
            latest_ms,
        })
    }

    /// Width of the interval, which is the chain timestamp's resolution and nothing else.
    #[must_use]
    pub const fn width_ms(self) -> i64 {
        self.latest_ms.saturating_sub(self.earliest_ms)
    }
}

/// Everything this would-quote knows about, and the exact boundary past which it knows nothing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct KnowledgeCutoff {
    /// Slot the provider stated it evaluated the account read at.
    pub context_slot: u64,
    /// Commitment named in the request. The response body does not restate it.
    pub requested_commitment: String,
    pub chain: ChainSecond,
    pub block_height: Option<u64>,
    pub blockhash: String,
}

/// One retained observation this would-quote is a function of.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetainedInput {
    /// What this observation contributed, for example `pool_and_vault_accounts`.
    pub role: String,
    pub observation_id: ObservationId,
    /// Digest of the exact retained payload, as the durable store recorded it.
    pub payload_digest: String,
    pub payload_bytes: u64,
    pub provider_body_bytes: u64,
}

/// Where the fee schedule came from and why it is unambiguous.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeeProvenance {
    pub fee_config_address: String,
    pub owner_program: String,
    /// The account name whose Anchor discriminator was recomputed and matched.
    pub discriminator_account_name: String,
    pub tier_table_count: usize,
    /// How the schedule was resolved across the retained tier tables.
    pub resolution: String,
    pub schedule: FeeSchedule,
}

/// The observed inventory the quote was computed against.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DepthProvenance {
    pub base_vault_atoms: u64,
    pub raw_quote_vault_atoms: u64,
    pub effective_quote_atoms: u128,
    pub base_mint_supply_atoms: u64,
    pub base_decimals: u8,
    pub quote_decimals: u8,
    pub market_cap_quote_atoms: u128,
    /// Size expressed as a fraction of the observed base inventory, in basis points.
    pub size_bps_of_base_inventory: u16,
}

/// The durable commit that retained the inputs, so the artifact names its own evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CatalogBinding {
    pub catalog_schema: String,
    pub batch_id: String,
    pub batch_digest: String,
    pub store_admission_digest: String,
    pub through_commit_seq: String,
}

/// One honest would-quote.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WouldQuote {
    pub venue: String,
    pub pool_address: String,
    pub base_mint: String,
    pub quote_mint: String,
    pub calculation: QuoteCalculation,
    pub cutoff: KnowledgeCutoff,
    pub receipt: LocalReceipt,
    pub age: ChainToReceiptAge,
    pub inputs: Vec<RetainedInput>,
    pub fees: FeeProvenance,
    pub depth: DepthProvenance,
    pub catalog: CatalogBinding,
}

impl WouldQuote {
    /// Renders the artifact as deterministic JSON.
    ///
    /// Every integer is rendered as a JSON string. A `u128` reserve or a `u64` atom count does not
    /// survive a JSON number in every reader, and an artifact whose numbers change meaning when
    /// reparsed is not evidence.
    #[must_use]
    pub fn render_json(&self) -> String {
        let outcome = match &self.calculation.outcome {
            QuoteOutcome::Success(quote) => {
                object(&[("status", quoted("quoted")), ("quote", render_quote(quote))])
            }
            QuoteOutcome::Refused(refusal) => object(&[
                ("status", quoted("refused")),
                ("refusal", quoted(&refusal.to_string())),
                ("refusalKind", quoted(refusal_kind(refusal))),
            ]),
        };
        object(&[
            ("contract", quoted(WOULD_QUOTE_CONTRACT)),
            ("authority", quoted(WOULD_QUOTE_AUTHORITY)),
            ("notAnExecution", quoted(NOT_AN_EXECUTION)),
            ("venue", quoted(&self.venue)),
            ("poolAddress", quoted(&self.pool_address)),
            ("baseMint", quoted(&self.base_mint)),
            ("quoteMint", quoted(&self.quote_mint)),
            (
                "requestedSize",
                render_size(self.calculation.requested_size),
            ),
            ("outcome", outcome),
            ("knowledgeCutoff", self.render_cutoff()),
            ("localReceipt", self.render_receipt()),
            ("chainToReceiptAge", self.render_age()),
            ("observedDepth", self.render_depth()),
            ("feeProvenance", self.render_fees()),
            (
                "retainedInputs",
                array(&self.inputs.iter().map(render_input).collect::<Vec<_>>()),
            ),
            ("catalog", self.render_catalog()),
        ])
    }

    /// Renders the artifact as a card a person reads.
    #[must_use]
    #[allow(clippy::too_many_lines)] // One card, printed in the order a reader needs it.
    pub fn render_card(&self) -> String {
        let mut card = String::new();
        let _ = writeln!(card, "WOULD-QUOTE  {WOULD_QUOTE_CONTRACT}");
        let _ = writeln!(card, "authority    {WOULD_QUOTE_AUTHORITY}");
        let _ = writeln!(card, "venue        {}", self.venue);
        let _ = writeln!(card, "pool         {}", self.pool_address);
        let _ = writeln!(card, "base mint    {}", self.base_mint);
        let _ = writeln!(card, "quote mint   {}", self.quote_mint);
        let _ = writeln!(card);
        let _ = writeln!(
            card,
            "at slot {} ({}), from the retained bytes below:",
            self.cutoff.context_slot, self.cutoff.requested_commitment
        );
        match &self.calculation.outcome {
            QuoteOutcome::Success(quote) => {
                let _ = writeln!(
                    card,
                    "  {}",
                    describe_size(self.calculation.requested_size, self.depth.base_decimals)
                );
                let _ = writeln!(
                    card,
                    "  input   {} atoms of {}",
                    quote.input.atoms.get(),
                    quote.input.asset_id
                );
                let _ = writeln!(
                    card,
                    "  output  {} atoms of {}",
                    quote.output.atoms.get(),
                    quote.output.asset_id
                );
                let _ = writeln!(
                    card,
                    "  raw consideration before fees  {} quote atoms",
                    quote.raw_quote_atoms.get()
                );
                let _ = writeln!(
                    card,
                    "  fees  lp {}  protocol {}  creator {}  (quote atoms)",
                    quote.fees.lp_atoms, quote.fees.protocol_atoms, quote.fees.creator_atoms
                );
                let _ = writeln!(card, "  formula {:?}", quote.formula);
            }
            QuoteOutcome::Refused(refusal) => {
                let _ = writeln!(card, "  REFUSED: {refusal}");
            }
        }
        let _ = writeln!(card);
        let _ = writeln!(
            card,
            "observed depth   base vault {} atoms, quote vault {} atoms",
            self.depth.base_vault_atoms, self.depth.raw_quote_vault_atoms
        );
        let _ = writeln!(
            card,
            "                 effective quote reserve {}, market cap {} quote atoms",
            self.depth.effective_quote_atoms, self.depth.market_cap_quote_atoms
        );
        let _ = writeln!(
            card,
            "                 size is {} basis points of the observed base inventory",
            self.depth.size_bps_of_base_inventory
        );
        let _ = writeln!(
            card,
            "fee schedule     lp {} bps, protocol {} bps, creator {}",
            self.fees.schedule.lp.get(),
            self.fees.schedule.protocol.get(),
            describe_creator(self.fees.schedule.creator)
        );
        let _ = writeln!(
            card,
            "                 from {} owned by {}, {}",
            self.fees.fee_config_address, self.fees.owner_program, self.fees.resolution
        );
        let _ = writeln!(card);
        let _ = writeln!(
            card,
            "chain time       slot {} blockTime {} (whole seconds, blockhash {})",
            self.cutoff.chain.slot, self.cutoff.chain.block_time_unix_s, self.cutoff.blockhash
        );
        let _ = writeln!(
            card,
            "local receipt    unix ms {} on clock {} at monotonic {} ns",
            self.receipt.wall_unix_ms, self.receipt.clock_id, self.receipt.monotonic_ns
        );
        let _ = writeln!(
            card,
            "AGE              between {} ms and {} ms (interval width {} ms)",
            self.age.earliest_ms,
            self.age.latest_ms,
            self.age.width_ms()
        );
        let _ = writeln!(card, "  measures     {AGE_MEASURES}");
        let _ = writeln!(card, "  does not     {AGE_DOES_NOT_MEASURE}");
        let _ = writeln!(card, "  commitment   {AGE_COMMITMENT_NOTE}");
        let _ = writeln!(card);
        let _ = writeln!(card, "retained inputs this quote is a function of:");
        for input in &self.inputs {
            let _ = writeln!(
                card,
                "  {:<28} observation {} digest {} ({} payload bytes, {} provider body bytes)",
                input.role,
                input.observation_id,
                input.payload_digest,
                input.payload_bytes,
                input.provider_body_bytes
            );
        }
        let _ = writeln!(
            card,
            "catalog          {} batch {} commit {} admission {}",
            self.catalog.catalog_schema,
            self.catalog.batch_id,
            self.catalog.through_commit_seq,
            self.catalog.store_admission_digest
        );
        let _ = writeln!(card);
        let _ = writeln!(card, "{NOT_AN_EXECUTION}");
        card
    }

    fn render_cutoff(&self) -> String {
        object(&[
            ("contextSlot", integer(&self.cutoff.context_slot)),
            (
                "requestedCommitment",
                quoted(&self.cutoff.requested_commitment),
            ),
            (
                "blockTimeUnixSeconds",
                integer(&self.cutoff.chain.block_time_unix_s),
            ),
            ("blockTimeResolutionSeconds", quoted("1")),
            (
                "blockHeight",
                self.cutoff
                    .block_height
                    .map_or_else(|| "null".to_owned(), |height| integer(&height)),
            ),
            ("blockhash", quoted(&self.cutoff.blockhash)),
        ])
    }

    fn render_receipt(&self) -> String {
        object(&[
            ("clockId", quoted(&self.receipt.clock_id)),
            ("monotonicNs", integer(&self.receipt.monotonic_ns)),
            ("wallUnixMs", integer(&self.receipt.wall_unix_ms)),
        ])
    }

    fn render_age(&self) -> String {
        object(&[
            ("earliestMs", integer(&self.age.earliest_ms)),
            ("latestMs", integer(&self.age.latest_ms)),
            ("intervalWidthMs", integer(&self.age.width_ms())),
            ("measures", quoted(AGE_MEASURES)),
            ("doesNotMeasure", quoted(AGE_DOES_NOT_MEASURE)),
            ("commitmentNote", quoted(AGE_COMMITMENT_NOTE)),
        ])
    }

    fn render_depth(&self) -> String {
        object(&[
            ("baseVaultAtoms", integer(&self.depth.base_vault_atoms)),
            (
                "rawQuoteVaultAtoms",
                integer(&self.depth.raw_quote_vault_atoms),
            ),
            (
                "effectiveQuoteAtoms",
                integer(&self.depth.effective_quote_atoms),
            ),
            (
                "baseMintSupplyAtoms",
                integer(&self.depth.base_mint_supply_atoms),
            ),
            ("baseDecimals", integer(&self.depth.base_decimals)),
            ("quoteDecimals", integer(&self.depth.quote_decimals)),
            (
                "marketCapQuoteAtoms",
                integer(&self.depth.market_cap_quote_atoms),
            ),
            (
                "sizeBpsOfBaseInventory",
                integer(&self.depth.size_bps_of_base_inventory),
            ),
        ])
    }

    fn render_fees(&self) -> String {
        object(&[
            ("feeConfigAddress", quoted(&self.fees.fee_config_address)),
            ("ownerProgram", quoted(&self.fees.owner_program)),
            (
                "discriminatorAccountName",
                quoted(&self.fees.discriminator_account_name),
            ),
            ("tierTableCount", integer(&self.fees.tier_table_count)),
            ("resolution", quoted(&self.fees.resolution)),
            ("lpBps", integer(&self.fees.schedule.lp.get())),
            ("protocolBps", integer(&self.fees.schedule.protocol.get())),
            (
                "creator",
                quoted(&describe_creator(self.fees.schedule.creator)),
            ),
        ])
    }

    fn render_catalog(&self) -> String {
        object(&[
            ("catalogSchema", quoted(&self.catalog.catalog_schema)),
            ("batchId", quoted(&self.catalog.batch_id)),
            ("batchDigest", quoted(&self.catalog.batch_digest)),
            (
                "storeAdmissionDigest",
                quoted(&self.catalog.store_admission_digest),
            ),
            ("throughCommitSeq", quoted(&self.catalog.through_commit_seq)),
        ])
    }
}

fn render_quote(quote: &SpotQuote) -> String {
    object(&[
        ("formula", quoted(&format!("{:?}", quote.formula))),
        (
            "input",
            object(&[
                ("assetId", quoted(quote.input.asset_id.as_str())),
                ("atoms", integer(&quote.input.atoms.get())),
            ]),
        ),
        (
            "output",
            object(&[
                ("assetId", quoted(quote.output.asset_id.as_str())),
                ("atoms", integer(&quote.output.atoms.get())),
            ]),
        ),
        ("rawQuoteAtoms", integer(&quote.raw_quote_atoms.get())),
        ("fees", render_fee_breakdown(quote.fees)),
        ("poolId", quoted(quote.binding.pool_id.as_str())),
        ("venueId", quoted(quote.binding.venue_id.as_str())),
        ("quoteId", quoted(quote.binding.quote_id.as_str())),
        (
            "stateObservationId",
            quoted(quote.binding.observed.state_observation_id.as_str()),
        ),
        (
            "feeObservationId",
            quoted(quote.binding.observed.fee_observation_id.as_str()),
        ),
        ("observedSlot", integer(&quote.binding.observed.slot.get())),
    ])
}

fn render_fee_breakdown(fees: FeeBreakdown) -> String {
    object(&[
        ("lpAtoms", integer(&fees.lp_atoms)),
        ("protocolAtoms", integer(&fees.protocol_atoms)),
        ("creatorAtoms", integer(&fees.creator_atoms)),
    ])
}

fn render_size(size: QuoteSize) -> String {
    let (kind, atoms) = match size {
        QuoteSize::ExactBaseOutBuy(atoms) => ("exact_base_out_buy", atoms),
        QuoteSize::ExactBaseInSell(atoms) => ("exact_base_in_sell", atoms),
        QuoteSize::ExactQuoteInBuy(atoms) => ("exact_quote_in_buy", atoms),
        QuoteSize::ExactQuoteOutSell(atoms) => ("exact_quote_out_sell", atoms),
    };
    object(&[("kind", quoted(kind)), ("atoms", integer(&atoms.get()))])
}

fn render_input(input: &RetainedInput) -> String {
    object(&[
        ("role", quoted(&input.role)),
        ("observationId", quoted(input.observation_id.as_str())),
        ("payloadDigest", quoted(&input.payload_digest)),
        ("payloadBytes", integer(&input.payload_bytes)),
        ("providerBodyBytes", integer(&input.provider_body_bytes)),
    ])
}

fn describe_size(size: QuoteSize, base_decimals: u8) -> String {
    let (verb, atoms) = match size {
        QuoteSize::ExactBaseOutBuy(atoms) => ("buying", atoms),
        QuoteSize::ExactBaseInSell(atoms) => ("selling", atoms),
        QuoteSize::ExactQuoteInBuy(atoms) => ("buying with", atoms),
        QuoteSize::ExactQuoteOutSell(atoms) => ("selling for", atoms),
    };
    format!(
        "{verb} {} base atoms ({} decimals)",
        atoms.get(),
        base_decimals
    )
}

fn describe_creator(creator: CreatorFee) -> String {
    match creator {
        CreatorFee::NotApplicable => "not applicable".to_owned(),
        CreatorFee::Charged(rate) => format!("{} bps", rate.get()),
        CreatorFee::Unknown => "unknown".to_owned(),
    }
}

const fn refusal_kind(refusal: &QuoteRefusal) -> &'static str {
    match refusal {
        QuoteRefusal::ZeroSize => "zero_size",
        QuoteRefusal::UnsupportedSizeKind => "unsupported_size_kind",
        QuoteRefusal::InactiveLifecycle => "inactive_lifecycle",
        QuoteRefusal::IntendedStateMismatch => "intended_state_mismatch",
        QuoteRefusal::ProfileMismatch => "profile_mismatch",
        QuoteRefusal::MarketIdentityMismatch => "market_identity_mismatch",
        QuoteRefusal::InvalidReserveState => "invalid_reserve_state",
        QuoteRefusal::InsufficientRealBase => "insufficient_real_base",
        QuoteRefusal::InsufficientRealQuote => "insufficient_real_quote",
        QuoteRefusal::NonpositiveEffectiveQuoteReserve => "nonpositive_effective_quote_reserve",
        QuoteRefusal::MalformedFeeConfiguration => "malformed_fee_configuration",
        QuoteRefusal::CreatorFeeApplicabilityUnknown => "creator_fee_applicability_unknown",
        QuoteRefusal::FeesExceedRawOutput => "fees_exceed_raw_output",
        QuoteRefusal::NotAFullLiquidationQuote => "not_a_full_liquidation_quote",
        QuoteRefusal::Arithmetic => "arithmetic",
    }
}

/// Refusals from constructing a would-quote.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum WouldQuoteError {
    #[error("a clock value is outside the supported range")]
    ClockOutOfRange,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn receipt(wall_unix_ms: i64) -> LocalReceipt {
        LocalReceipt {
            clock_id: "joshi-would-quote-test".to_owned(),
            monotonic_ns: 12_345,
            wall_unix_ms,
        }
    }

    #[test]
    fn the_age_is_an_interval_exactly_one_chain_second_wide() {
        let chain = ChainSecond {
            slot: 440_672_889,
            block_time_unix_s: 1_787_310_191,
        };
        let age = ChainToReceiptAge::measure(chain, &receipt(1_787_310_194_123)).expect("measured");
        assert_eq!(age.latest_ms, 3_123);
        assert_eq!(age.earliest_ms, 2_123);
        assert_eq!(age.width_ms(), 1_000);
    }

    #[test]
    fn an_age_may_be_negative_because_a_local_clock_can_lag_the_chain_report() {
        let chain = ChainSecond {
            slot: 1,
            block_time_unix_s: 1_787_310_191,
        };
        let age = ChainToReceiptAge::measure(chain, &receipt(1_787_310_190_000)).expect("measured");
        assert_eq!(age.latest_ms, -1_000);
        assert_eq!(age.earliest_ms, -2_000);
    }
}
