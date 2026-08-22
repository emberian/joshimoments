//! Exact account decoders for the Pump bonding-curve program, the `PumpSwap` AMM program, and the
//! Pump fee program.
//!
//! Every decoder here reads bytes a provider actually returned and refuses anything it cannot read
//! literally. Four properties keep the layouts honest rather than assumed:
//!
//! 1. **Identity is proved, not asserted.** Each account is accepted only when its owning program
//!    matches and its leading eight bytes equal the Anchor account discriminator this crate
//!    recomputes from the account's declared name, `sha256("account:<Name>")[..8]`.
//! 2. **A located field and a named field are different things, and are labelled differently.**
//!    The `PumpSwap` pool layout has named fields through byte 243. At byte 245 there is an
//!    eight-byte quote-side term whose *value* is load-bearing for pricing and whose *name* is not
//!    established; see [`PumpSwapPool::unattributed_quote_side_reserve_atoms`]. Byte 244 is a
//!    second located, unnamed field. Every byte this decoder can neither name nor locate is
//!    required to be zero, because a nonzero value there would mean something it cannot say. The
//!    same split runs through the bonding curve, which also comes in five different lengths.
//! 3. **A rate is taken from the program that charges it.** The bonding-curve `Global` account
//!    carries fee fields that the deployed fee program overrides;
//!    [`PumpGlobal::require_agreement_with_fee_program`] turns reading them as applied rates into a
//!    refusal rather than a silent 25-basis-point understatement.
//! 4. **Structure is checked against the retained length.** The Pump fee configuration is accepted
//!    only when its exact allocated length equals the fixed layout plus two `FeeTier` vectors at
//!    their declared capacity, both vectors parse with strictly increasing thresholds and rates no
//!    greater than 10,000 basis points, and every byte past the last tier is zero.
//!
//! Addresses that arrive from outside — a pool from an index, a curve from a frontend list — are
//! bound to their mint by [`crate::pda`] derivation rather than by trust. This module performs no
//! economic action of any kind. It decodes retained bytes.

use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::pda::{decode_address, derivation_bump, descending_bump_candidates};
use crate::solana_account::RetainedAccount;

/// Pump bonding-curve program. Owns every `BondingCurve` and the single `Global` account.
pub const PUMP_BONDING_CURVE_PROGRAM_ID: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
/// `PumpSwap` AMM program. Every pool and fee-configuration account is checked against an owner.
pub const PUMP_AMM_PROGRAM_ID: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
/// Pump fee program that owns the market-cap fee-tier configuration.
pub const PUMP_FEE_PROGRAM_ID: &str = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ";
/// Seed the fee program derives a venue program's fee configuration from.
pub const FEE_CONFIG_SEED: &[u8] = b"fee_config";
/// Seed the bonding-curve program derives one mint's curve from.
pub const BONDING_CURVE_SEED: &[u8] = b"bonding-curve";
/// Seed the bonding-curve program derives its single `Global` account from.
pub const GLOBAL_SEED: &[u8] = b"global";
/// Seed the AMM derives a pool from, ahead of index, creator, base mint, and quote mint.
pub const POOL_SEED: &[u8] = b"pool";
/// The fee configuration the fee program keeps for the `PumpSwap` AMM.
///
/// This constant is a convenience, not the evidence. The address is the program-derived address of
/// `["fee_config", PumpSwap program]` under [`PUMP_FEE_PROGRAM_ID`], which
/// [`fee_config_derivation_bump`] recomputes and this module's tests assert. It is additionally
/// never trusted on its name: [`PumpFeeConfig::decode`] accepts the response only when the owner is
/// the fee program and the discriminator is the recomputed `FeeConfig` discriminator.
pub const PUMP_FEE_CONFIG_ADDRESS: &str = "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx";
/// The fee configuration the fee program keeps for the bonding-curve program.
///
/// Derived and checked exactly like [`PUMP_FEE_CONFIG_ADDRESS`]. The two configurations are
/// different accounts holding different tier tables, and using one venue's rates on the other venue
/// is a four-times error on the fee floor.
pub const PUMP_CURVE_FEE_CONFIG_ADDRESS: &str = "8Wf5TiAheLUqBrKXeYg2JtAFFMWtKdG2BSFgqUcPVwTt";
/// The bonding-curve program's single `Global` account, `["global"]` under that program.
pub const PUMP_GLOBAL_ADDRESS: &str = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf";
/// Wrapped SOL mint, used only to recognize a lamport-denominated quote asset.
pub const WRAPPED_SOL_MINT: &str = "So11111111111111111111111111111111111111112";
/// Base58 of the all-zero public key, which `PumpSwap` uses to mean "no coin creator".
pub const DEFAULT_PUBKEY: &str = "11111111111111111111111111111111";
/// SPL Token program.
pub const SPL_TOKEN_PROGRAM_ID: &str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
/// SPL Token-2022 program.
pub const SPL_TOKEN_2022_PROGRAM_ID: &str = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";

/// Exact allocated length of a `PumpSwap` pool account.
pub const POOL_ACCOUNT_LEN: usize = 301;
/// First byte past the pool fields this decoder can name.
pub const POOL_NAMED_LEN: usize = 243;
/// Offset of the eight-byte quote-side term this decoder can locate but cannot name.
pub const POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET: usize = 245;
/// Width of that term, in bytes.
pub const POOL_UNATTRIBUTED_QUOTE_SIDE_LEN: usize = 8;
/// Offset of a single pool byte this decoder can locate but cannot name.
///
/// Observed as 0 on 37 and 1 on 5 of 42 mainnet pools sampled 2026-08-22, uncorrelated with whether
/// the term at [`POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET`] is zero. It is read and reported verbatim.
pub const POOL_UNNAMED_BYTE_OFFSET: usize = 244;
/// Half-open pool byte ranges this decoder requires to be zero.
///
/// These surround the located-but-unnamed byte and term. A decoder that can neither name nor locate
/// a field in a region cannot say what a nonzero value there would mean, so a nonzero byte is
/// refused. Both ranges were zero on all 42 mainnet pools sampled 2026-08-22.
pub const POOL_REQUIRED_ZERO_RANGES: [(usize, usize); 2] = [
    (POOL_NAMED_LEN, POOL_UNNAMED_BYTE_OFFSET),
    (
        POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET + POOL_UNATTRIBUTED_QUOTE_SIDE_LEN,
        POOL_ACCOUNT_LEN,
    ),
];
/// Smallest bonding-curve layout observed on mainnet: discriminator, five reserve fields, and the
/// completion flag.
///
/// Curve accounts are **not** a fixed length. Lengths 49, 115, 150, 151, and 256 were all observed
/// among 96 mainnet curves on 2026-08-22, because the program has grown the account across
/// versions and shrinks some of them on migration. A decoder that required one length would refuse
/// most of the market, so this one reads what is there and says which fields the retained length
/// actually contains.
pub const BONDING_CURVE_CORE_LEN: usize = 49;
/// Offset of the creator field, present only in layouts at least [`BONDING_CURVE_WITH_CREATOR_LEN`]
/// long. In shorter layouts the field does not exist, which is not the same as a creator of zero.
pub const BONDING_CURVE_CREATOR_OFFSET: usize = 49;
/// Shortest layout that carries the creator field.
pub const BONDING_CURVE_WITH_CREATOR_LEN: usize = 81;
/// Half-open range of two bonding-curve bytes observed to differ between curves with no meaning
/// established, and no correlation with the completion flag. Read and reported verbatim.
pub const BONDING_CURVE_UNNAMED_BYTES_RANGE: (usize, usize) = (81, 83);
/// Half-open range of a located, pubkey-shaped bonding-curve region with no meaning established.
/// Zero on almost every curve and set on a few. Read and reported verbatim, never resolved.
pub const BONDING_CURVE_UNNAMED_PUBKEY_RANGE: (usize, usize) = (83, 115);
/// First byte past every bonding-curve region this decoder can locate. Anything nonzero beyond it
/// is refused, because an unlocated numeric field is exactly the mistake pool byte 245 was.
pub const BONDING_CURVE_LOCATED_LEN: usize = 115;
/// Exact allocated length of the bonding-curve program's `Global` account.
///
/// The whole length is required even though nothing past [`GLOBAL_NAMED_LEN`] is attributed. A
/// length change is the cheapest available tripwire for a layout change, and a silently wrong
/// offset in this account would make the stale-rate check below stop being loud.
pub const GLOBAL_ACCOUNT_LEN: usize = 1045;
/// First byte past the `Global` fields this decoder can name.
pub const GLOBAL_NAMED_LEN: usize = 162;
/// Fixed prefix of the Pump fee configuration before its first tier vector.
const FEE_CONFIG_PREFIX_LEN: usize = 8 + 1 + 32 + 24;
/// Declared capacity, in tiers, of each fee-tier vector.
const FEE_TIER_CAPACITY: usize = 50;
/// Serialized width of one `FeeTier`.
const FEE_TIER_LEN: usize = 16 + 24;
/// Number of tier vectors the fee configuration carries.
const FEE_TIER_VECTORS: usize = 2;
/// Exact allocated length of the Pump fee configuration account.
pub const FEE_CONFIG_ACCOUNT_LEN: usize =
    FEE_CONFIG_PREFIX_LEN + FEE_TIER_VECTORS * (4 + FEE_TIER_CAPACITY * FEE_TIER_LEN);

/// Minimum length of an SPL token account, shared by Token and Token-2022.
const TOKEN_ACCOUNT_BASE_LEN: usize = 165;
/// Minimum length of an SPL mint account, shared by Token and Token-2022.
const MINT_BASE_LEN: usize = 82;
/// First byte of the Token-2022 extension type-length-value region.
const TOKEN_2022_TLV_START: usize = 166;

/// Computes the Anchor account discriminator for a declared account name.
///
/// This is the identity check that makes an address an input rather than an assumption: an account
/// is only what its own leading bytes say it is.
#[must_use]
pub fn anchor_account_discriminator(account_name: &str) -> [u8; 8] {
    let digest = Sha256::digest(format!("account:{account_name}").as_bytes());
    let mut discriminator = [0_u8; 8];
    discriminator.copy_from_slice(&digest[..8]);
    discriminator
}

/// A Token-2022 extension observed on a mint or token account.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TokenExtension {
    pub extension_type: u16,
    pub value_len: u16,
}

impl TokenExtension {
    /// Whether this extension can change the amount that actually moves in a transfer.
    ///
    /// A quote computed over a mint that charges a transfer fee, routes a transfer hook, or is
    /// non-transferable would be wrong in a way the pool reserves cannot show, so those are
    /// refused rather than quoted.
    #[must_use]
    pub const fn alters_transferred_amount(self) -> bool {
        matches!(
            self.extension_type,
            1 | 2 | 4 | 5 | 6 | 8 | 9 | 10 | 11 | 12 | 14 | 15 | 16 | 17
        )
    }
}

/// Exact `PumpSwap` pool state read from one retained account.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpSwapPool {
    pub address: String,
    pub pool_bump: u8,
    pub index: u16,
    pub creator: String,
    pub base_mint: String,
    pub quote_mint: String,
    pub lp_mint: String,
    pub pool_base_token_account: String,
    pub pool_quote_token_account: String,
    pub lp_supply: u64,
    pub coin_creator: String,
    /// The single byte at [`POOL_UNNAMED_BYTE_OFFSET`], verbatim and uninterpreted.
    pub unnamed_byte: u8,
    /// The eight bytes at [`POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET`], read little-endian.
    ///
    /// **What is established.** The deployed swap adds this value to the quote vault balance before
    /// the constant-product step. Study M0 checked that on this pool against four buys that landed
    /// on chain: including it reproduces every one of them to the atom, and omitting it overstates
    /// base-out by about 119 basis points — four times the whole 30-basis-point round-trip fee, and
    /// in the direction that makes a trade look better than it is. The value did not move across
    /// seventy slots of active trading on that pool.
    ///
    /// **What is not established.** The field's name, what it represents, what event changes it, and
    /// whether it is signed. This decoder therefore does not call it a virtual reserve, does not
    /// widen it to a signed type, and does not assume a pool whose value is zero is the same kind of
    /// pool as one whose value is not. Use [`Self::effective_quote_atoms`] rather than adding it by
    /// hand, so the one place that knows the composition stays the only place.
    ///
    /// **What a later survey added.** Across 42 mainnet pools read on 2026-08-22 the term took the
    /// same value, 17,584,505,288 atoms, on 29 of them, a second value on one, and zero on twelve.
    /// A quantity that is identical across unrelated pools is a protocol-wide constant and not
    /// per-pool state — which is consistent with a virtual reserve and still does not name it.
    pub unattributed_quote_side_reserve_atoms: u64,
}

impl PumpSwapPool {
    /// Reads one `PumpSwap` pool account.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a wrong length, a discriminator that is not the recomputed `Pool`
    /// discriminator, and any nonzero byte in a region this decoder can neither name nor locate a
    /// field in.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_owner(account, PUMP_AMM_PROGRAM_ID)?;
        require_len(account, POOL_ACCOUNT_LEN)?;
        require_discriminator(account, "Pool")?;
        let data = &account.data;
        if let Some((offset, len)) = first_nonzero_range(data, &POOL_REQUIRED_ZERO_RANGES) {
            return Err(PumpDecodeError::PoolReservedRegionIsNonzero {
                address: account.address.clone(),
                offset,
                len,
            });
        }
        Ok(Self {
            address: account.address.clone(),
            pool_bump: data[8],
            index: u16::from_le_bytes([data[9], data[10]]),
            creator: pubkey(data, 11),
            base_mint: pubkey(data, 43),
            quote_mint: pubkey(data, 75),
            lp_mint: pubkey(data, 107),
            pool_base_token_account: pubkey(data, 139),
            pool_quote_token_account: pubkey(data, 171),
            lp_supply: u64_at(data, 203),
            coin_creator: pubkey(data, 211),
            unnamed_byte: data[POOL_UNNAMED_BYTE_OFFSET],
            unattributed_quote_side_reserve_atoms: u64_at(
                data,
                POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET,
            ),
        })
    }

    /// Whether the pool names a coin creator, which is what makes a creator fee applicable.
    #[must_use]
    pub fn has_coin_creator(&self) -> bool {
        self.coin_creator != DEFAULT_PUBKEY
    }

    /// The quote reserve the deployed constant-product step uses, from the observed vault balance.
    ///
    /// The caller supplies the quote vault's own balance because that is a token account this
    /// decoder does not hold. Both terms are `u64`, so the sum cannot overflow `u128`.
    #[must_use]
    pub const fn effective_quote_atoms(&self, quote_vault_atoms: u64) -> u128 {
        quote_vault_atoms as u128 + self.unattributed_quote_side_reserve_atoms as u128
    }

    /// The bump at which this pool's own address derives from the fields it states.
    ///
    /// The pool account names its index, creator, base mint, and quote mint, and the AMM derives
    /// the pool address from exactly those. Recomputing it closes the loop without any outside
    /// input: a `Some` says the address and the contents are the same pool. `None` says they are
    /// not, which is the interesting answer.
    #[must_use]
    pub fn self_derivation_bump(&self) -> Option<u8> {
        let creator = decode_address(&self.creator)?;
        let base = decode_address(&self.base_mint)?;
        let quote = decode_address(&self.quote_mint)?;
        derivation_bump(
            &self.address,
            &[
                POOL_SEED,
                &self.index.to_le_bytes(),
                &creator,
                &base,
                &quote,
            ],
            PUMP_AMM_PROGRAM_ID,
        )
    }
}

/// Exact Pump bonding-curve state read from one retained account.
///
/// The curve carries virtual reserves that the deployed instruction uses directly; unlike a
/// `PumpSwap` pool there is no vault balance to add and no unnamed term to locate. What it does not
/// carry is the mint. Nothing in these bytes says which coin this curve is for, so an address that
/// arrived from outside must be bound with [`bonding_curve_derivation_bump`] before its reserves
/// are used as a quote for any particular mint.
///
/// The account is not a fixed length. Every optional field below is `None` exactly when the
/// retained length does not reach it, which is a different statement from the field being zero.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpBondingCurve {
    pub address: String,
    /// Length the provider returned, which selects which fields exist.
    pub account_len: usize,
    pub virtual_base_atoms: u64,
    pub virtual_quote_atoms: u64,
    pub real_base_atoms: u64,
    pub real_quote_atoms: u64,
    pub base_total_supply_atoms: u64,
    /// Set once the curve has migrated. A complete curve is not the venue any more, and quoting
    /// against its reserves would price a market that no longer trades — which is also why a
    /// migrated curve reads as all-zero reserves rather than as stale ones.
    pub complete: bool,
    /// `None` when the retained layout is shorter than the creator field, which is not the same as
    /// a creator of all zeros.
    pub creator: Option<String>,
    /// Bytes [`BONDING_CURVE_UNNAMED_BYTES_RANGE`], verbatim, when the length reaches them.
    pub unnamed_bytes: Option<[u8; 2]>,
    /// Bytes [`BONDING_CURVE_UNNAMED_PUBKEY_RANGE`] as base58, when the length reaches them. This
    /// region is pubkey-shaped and unnamed; it is carried so a reader can see it was looked at.
    pub unnamed_pubkey: Option<String>,
}

impl PumpBondingCurve {
    /// Reads one bonding-curve account, at whatever length the program left it.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, an account shorter than the smallest observed layout, a discriminator
    /// that is not the recomputed `BondingCurve` discriminator, a completion flag that is neither
    /// zero nor one, and any nonzero byte past the last region this decoder can locate.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_owner(account, PUMP_BONDING_CURVE_PROGRAM_ID)?;
        let len = account.data.len();
        if len < BONDING_CURVE_CORE_LEN {
            return Err(PumpDecodeError::AccountShorterThanLayout {
                address: account.address.clone(),
                minimum: BONDING_CURVE_CORE_LEN,
                found: len,
            });
        }
        require_discriminator(account, "BondingCurve")?;
        let data = &account.data;
        if len > BONDING_CURVE_LOCATED_LEN
            && data[BONDING_CURVE_LOCATED_LEN..]
                .iter()
                .any(|byte| *byte != 0)
        {
            return Err(PumpDecodeError::CurveReservedRegionIsNonzero {
                address: account.address.clone(),
                offset: BONDING_CURVE_LOCATED_LEN,
                len: len - BONDING_CURVE_LOCATED_LEN,
            });
        }
        Ok(Self {
            address: account.address.clone(),
            account_len: len,
            virtual_base_atoms: u64_at(data, 8),
            virtual_quote_atoms: u64_at(data, 16),
            real_base_atoms: u64_at(data, 24),
            real_quote_atoms: u64_at(data, 32),
            base_total_supply_atoms: u64_at(data, 40),
            complete: require_boolean(account, 48)?,
            creator: (len >= BONDING_CURVE_WITH_CREATOR_LEN)
                .then(|| pubkey(data, BONDING_CURVE_CREATOR_OFFSET)),
            unnamed_bytes: (len >= BONDING_CURVE_UNNAMED_BYTES_RANGE.1).then(|| {
                [
                    data[BONDING_CURVE_UNNAMED_BYTES_RANGE.0],
                    data[BONDING_CURVE_UNNAMED_BYTES_RANGE.0 + 1],
                ]
            }),
            unnamed_pubkey: (len >= BONDING_CURVE_UNNAMED_PUBKEY_RANGE.1)
                .then(|| pubkey(data, BONDING_CURVE_UNNAMED_PUBKEY_RANGE.0)),
        })
    }

    /// Whether a creator fee applies, or `None` when the retained layout does not say.
    ///
    /// `None` is the honest answer for a layout that predates the creator field, and a caller must
    /// carry it forward as an unknown rather than as "no creator".
    #[must_use]
    pub fn creator_fee_applies(&self) -> Option<bool> {
        self.creator
            .as_ref()
            .map(|creator| creator != DEFAULT_PUBKEY)
    }

    /// Whether the curve has any quote-side reserve to price against.
    ///
    /// A migrated curve reads as zeros. Zero reserves are not a state a quote can be computed at,
    /// and calling that out here keeps a caller from dividing by it.
    #[must_use]
    pub const fn has_priceable_reserves(&self) -> bool {
        self.virtual_base_atoms > 0 && self.virtual_quote_atoms > 0
    }
}

/// Exact bonding-curve `Global` state, read so that its fee fields cannot be used as rates.
///
/// This account is genuinely authoritative about the program's configuration and genuinely *stale*
/// about fees. On 2026-08-21 it declared a creator fee of 5 basis points while the deployed fee
/// program returned 30 and the landed transfer was 30 — reading it would understate one leg by 25
/// basis points and a round trip by 50, on a venue whose entire fee floor is 247. The fields are
/// therefore named for what they are, `declared_*`, and
/// [`Self::require_agreement_with_fee_program`] exists so that a caller who reaches for them gets a
/// refusal instead of a number.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpGlobal {
    pub address: String,
    pub initialized: bool,
    pub authority: String,
    pub fee_recipient: String,
    pub initial_virtual_base_atoms: u64,
    pub initial_virtual_quote_atoms: u64,
    pub initial_real_base_atoms: u64,
    pub base_total_supply_atoms: u64,
    /// The protocol rate this account declares. Not established to be the rate that is charged.
    pub declared_protocol_fee_basis_points: u64,
    pub withdraw_authority: String,
    pub enable_migrate: bool,
    pub pool_migration_fee_quote_atoms: u64,
    /// The creator rate this account declares. Observed stale against the deployed fee program.
    pub declared_creator_fee_basis_points: u64,
    /// Bytes past [`GLOBAL_NAMED_LEN`], which this decoder reads as neither zero nor meaningful.
    pub unattributed_len: usize,
}

impl PumpGlobal {
    /// Reads the bonding-curve program's `Global` account.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a wrong length, a discriminator that is not the recomputed `Global`
    /// discriminator, and a flag byte that is neither zero nor one.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_owner(account, PUMP_BONDING_CURVE_PROGRAM_ID)?;
        require_len(account, GLOBAL_ACCOUNT_LEN)?;
        require_discriminator(account, "Global")?;
        let data = &account.data;
        Ok(Self {
            address: account.address.clone(),
            initialized: require_boolean(account, 8)?,
            authority: pubkey(data, 9),
            fee_recipient: pubkey(data, 41),
            initial_virtual_base_atoms: u64_at(data, 73),
            initial_virtual_quote_atoms: u64_at(data, 81),
            initial_real_base_atoms: u64_at(data, 89),
            base_total_supply_atoms: u64_at(data, 97),
            declared_protocol_fee_basis_points: u64_at(data, 105),
            withdraw_authority: pubkey(data, 113),
            enable_migrate: require_boolean(account, 145)?,
            pool_migration_fee_quote_atoms: u64_at(data, 146),
            declared_creator_fee_basis_points: u64_at(data, 154),
            unattributed_len: GLOBAL_ACCOUNT_LEN - GLOBAL_NAMED_LEN,
        })
    }

    /// Refuses whenever this account's declared rates differ from the ones the fee program states.
    ///
    /// Call this before using any `Global` fee field for anything. The error carries both rates and
    /// the signed gap, so a caller that logs the refusal has logged the size of the mistake it did
    /// not make.
    ///
    /// # Errors
    ///
    /// Returns [`PumpDecodeError::GlobalDeclaredRatesDisagreeWithFeeProgram`] on any disagreement.
    pub fn require_agreement_with_fee_program(
        &self,
        applied: FeeRatesBps,
    ) -> Result<(), PumpDecodeError> {
        if self.declared_protocol_fee_basis_points == applied.protocol
            && self.declared_creator_fee_basis_points == applied.creator
        {
            return Ok(());
        }
        Err(PumpDecodeError::GlobalDeclaredRatesDisagreeWithFeeProgram {
            address: self.address.clone(),
            declared_protocol_bps: self.declared_protocol_fee_basis_points,
            declared_creator_bps: self.declared_creator_fee_basis_points,
            applied_protocol_bps: applied.protocol,
            applied_creator_bps: applied.creator,
            understated_leg_bps: (applied.protocol + applied.creator).saturating_sub(
                self.declared_protocol_fee_basis_points + self.declared_creator_fee_basis_points,
            ),
        })
    }
}

/// The bump at which `address` is the bonding curve of `mint`.
///
/// A bonding-curve account never names its mint, so this derivation is the only thing that binds
/// the two. `None` means the candidate is some other curve, or not a curve at all.
#[must_use]
pub fn bonding_curve_derivation_bump(address: &str, mint: &str) -> Option<u8> {
    let mint = decode_address(mint)?;
    derivation_bump(
        address,
        &[BONDING_CURVE_SEED, &mint],
        PUMP_BONDING_CURVE_PROGRAM_ID,
    )
}

/// Candidate bonding-curve addresses for one mint, highest bump first.
///
/// The canonical bump cannot be picked offline without ed25519 curve arithmetic this crate does not
/// carry, so a caller asks the provider about several candidates in the batched read it was making
/// anyway and keeps whichever one exists and decodes. See [`crate::pda`].
#[must_use]
pub fn bonding_curve_candidates(mint: &str, count: u8) -> Vec<(u8, String)> {
    let Some(mint) = decode_address(mint) else {
        return Vec::new();
    };
    descending_bump_candidates(
        &[BONDING_CURVE_SEED, &mint],
        PUMP_BONDING_CURVE_PROGRAM_ID,
        count,
    )
}

/// The bump at which `address` is the fee program's configuration for one venue program.
///
/// This is what turns a fee-configuration address from something observed in somebody's transaction
/// into something recomputed from the program whose fees it sets.
#[must_use]
pub fn fee_config_derivation_bump(address: &str, venue_program_id: &str) -> Option<u8> {
    let venue = decode_address(venue_program_id)?;
    derivation_bump(address, &[FEE_CONFIG_SEED, &venue], PUMP_FEE_PROGRAM_ID)
}

/// The bump at which `address` is the bonding-curve program's `Global` account.
#[must_use]
pub fn global_derivation_bump(address: &str) -> Option<u8> {
    derivation_bump(address, &[GLOBAL_SEED], PUMP_BONDING_CURVE_PROGRAM_ID)
}

/// Exact SPL token account state, shared by Token and Token-2022.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenVault {
    pub address: String,
    pub token_program: String,
    pub mint: String,
    pub owner: String,
    pub amount: u64,
    pub state: u8,
    pub extensions: Vec<TokenExtension>,
}

impl TokenVault {
    /// Reads one token account and refuses any extension that can change transferred amounts.
    ///
    /// # Errors
    ///
    /// Refuses a non-token owner, a short account, an uninitialized account, and an amount-altering
    /// extension.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_token_program(account)?;
        if account.data.len() < TOKEN_ACCOUNT_BASE_LEN {
            return Err(PumpDecodeError::UnexpectedLength {
                address: account.address.clone(),
                expected: TOKEN_ACCOUNT_BASE_LEN,
                found: account.data.len(),
            });
        }
        let state = account.data[108];
        if state == 0 {
            return Err(PumpDecodeError::UninitializedTokenAccount(
                account.address.clone(),
            ));
        }
        let extensions = read_extensions(account)?;
        Ok(Self {
            address: account.address.clone(),
            token_program: account.owner.clone(),
            mint: pubkey(&account.data, 0),
            owner: pubkey(&account.data, 32),
            amount: u64_at(&account.data, 64),
            state,
            extensions,
        })
    }
}

/// Exact SPL mint state, shared by Token and Token-2022.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TokenMint {
    pub address: String,
    pub token_program: String,
    pub supply: u64,
    pub decimals: u8,
    pub extensions: Vec<TokenExtension>,
}

impl TokenMint {
    /// Reads one mint account and refuses any extension that can change transferred amounts.
    ///
    /// # Errors
    ///
    /// Refuses a non-token owner, a short account, an uninitialized mint, and an amount-altering
    /// extension.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_token_program(account)?;
        if account.data.len() < MINT_BASE_LEN {
            return Err(PumpDecodeError::UnexpectedLength {
                address: account.address.clone(),
                expected: MINT_BASE_LEN,
                found: account.data.len(),
            });
        }
        if account.data[45] != 1 {
            return Err(PumpDecodeError::UninitializedMint(account.address.clone()));
        }
        let extensions = read_extensions(account)?;
        Ok(Self {
            address: account.address.clone(),
            token_program: account.owner.clone(),
            supply: u64_at(&account.data, 36),
            decimals: account.data[44],
            extensions,
        })
    }
}

/// Exact fee rates in basis points, as the fee program states them.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeeRatesBps {
    pub lp: u64,
    pub protocol: u64,
    pub creator: u64,
}

/// One market-cap threshold and the rates it selects.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FeeTierRow {
    /// Market cap, in quote atoms, at or above which this row applies.
    pub threshold_quote_atoms: u128,
    pub rates: FeeRatesBps,
}

/// Exact Pump fee-program configuration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PumpFeeConfig {
    pub address: String,
    pub bump: u8,
    pub admin: String,
    /// Rates the configuration states outside any tier table.
    pub flat: FeeRatesBps,
    /// Every tier vector the account carries, in serialized order.
    pub tier_tables: Vec<Vec<FeeTierRow>>,
}

impl PumpFeeConfig {
    /// Reads the fee configuration and validates its structure against the account's exact length.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a length that is not the exact fixed layout at declared capacity, a
    /// wrong discriminator, a vector longer than its capacity, an empty vector, a rate above
    /// 10,000 basis points, non-increasing thresholds, and a nonzero byte after the last tier.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_owner(account, PUMP_FEE_PROGRAM_ID)?;
        require_len(account, FEE_CONFIG_ACCOUNT_LEN)?;
        require_discriminator(account, "FeeConfig")?;
        let data = &account.data;
        let mut offset = FEE_CONFIG_PREFIX_LEN;
        let mut tier_tables = Vec::with_capacity(FEE_TIER_VECTORS);
        for _ in 0..FEE_TIER_VECTORS {
            let (table, next) = read_tier_table(&account.address, data, offset)?;
            tier_tables.push(table);
            offset = next;
        }
        if data[offset..].iter().any(|byte| *byte != 0) {
            return Err(PumpDecodeError::FeeConfigTrailerIsNonzero {
                address: account.address.clone(),
                offset,
            });
        }
        Ok(Self {
            address: account.address.clone(),
            bump: data[8],
            admin: pubkey(data, 9),
            flat: FeeRatesBps {
                lp: u64_at(data, 41),
                protocol: u64_at(data, 49),
                creator: u64_at(data, 57),
            },
            tier_tables,
        })
    }

    /// Selects the rates every retained tier table agrees on for one market cap.
    ///
    /// The configuration carries more than one tier table, and these bytes do not state which one
    /// the program applies to which pool class. Rather than choose, this refuses whenever the
    /// tables disagree, so a rate is returned only where the retained bytes make it unambiguous.
    ///
    /// # Errors
    ///
    /// Refuses an empty table set and any market cap at which the tables select different rates.
    pub fn agreed_rates(
        &self,
        market_cap_quote_atoms: u128,
    ) -> Result<FeeRatesBps, PumpDecodeError> {
        let mut selected: Option<FeeRatesBps> = None;
        for table in &self.tier_tables {
            let rates = select_tier(table, market_cap_quote_atoms)
                .ok_or_else(|| PumpDecodeError::EmptyFeeTierTable(self.address.clone()))?;
            match selected {
                None => selected = Some(rates),
                Some(existing) if existing == rates => {}
                Some(existing) => {
                    return Err(PumpDecodeError::FeeTierTablesDisagree {
                        market_cap_quote_atoms,
                        first: existing,
                        second: rates,
                    });
                }
            }
        }
        selected.ok_or_else(|| PumpDecodeError::EmptyFeeTierTable(self.address.clone()))
    }

    /// Reports each table's own selection, so a reader can see what agreement was established over.
    #[must_use]
    pub fn per_table_rates(&self, market_cap_quote_atoms: u128) -> Vec<Option<FeeRatesBps>> {
        self.tier_tables
            .iter()
            .map(|table| select_tier(table, market_cap_quote_atoms))
            .collect()
    }
}

fn select_tier(table: &[FeeTierRow], market_cap_quote_atoms: u128) -> Option<FeeRatesBps> {
    let first = table.first()?;
    Some(
        table
            .iter()
            .rev()
            .find(|row| row.threshold_quote_atoms <= market_cap_quote_atoms)
            .unwrap_or(first)
            .rates,
    )
}

fn read_tier_table(
    address: &str,
    data: &[u8],
    offset: usize,
) -> Result<(Vec<FeeTierRow>, usize), PumpDecodeError> {
    let count = u32::from_le_bytes([
        data[offset],
        data[offset + 1],
        data[offset + 2],
        data[offset + 3],
    ]) as usize;
    if count == 0 || count > FEE_TIER_CAPACITY {
        return Err(PumpDecodeError::FeeTierCountOutOfRange {
            address: address.to_owned(),
            count,
            capacity: FEE_TIER_CAPACITY,
        });
    }
    let start = offset + 4;
    let end = start + count * FEE_TIER_LEN;
    if end > data.len() {
        return Err(PumpDecodeError::FeeTierTableOverrunsAccount {
            address: address.to_owned(),
            end,
            len: data.len(),
        });
    }
    let mut rows = Vec::with_capacity(count);
    for index in 0..count {
        let row_at = start + index * FEE_TIER_LEN;
        let mut threshold = [0_u8; 16];
        threshold.copy_from_slice(&data[row_at..row_at + 16]);
        let rates = FeeRatesBps {
            lp: u64_at(data, row_at + 16),
            protocol: u64_at(data, row_at + 24),
            creator: u64_at(data, row_at + 32),
        };
        for rate in [rates.lp, rates.protocol, rates.creator] {
            if rate > 10_000 {
                return Err(PumpDecodeError::FeeRateAboveOneHundredPercent {
                    address: address.to_owned(),
                    rate,
                });
            }
        }
        rows.push(FeeTierRow {
            threshold_quote_atoms: u128::from_le_bytes(threshold),
            rates,
        });
    }
    if rows
        .windows(2)
        .any(|pair| pair[0].threshold_quote_atoms >= pair[1].threshold_quote_atoms)
    {
        return Err(PumpDecodeError::FeeTierThresholdsNotIncreasing {
            address: address.to_owned(),
        });
    }
    Ok((rows, end))
}

fn read_extensions(account: &RetainedAccount) -> Result<Vec<TokenExtension>, PumpDecodeError> {
    if account.owner != SPL_TOKEN_2022_PROGRAM_ID || account.data.len() <= TOKEN_2022_TLV_START {
        return Ok(Vec::new());
    }
    let data = &account.data;
    let mut extensions = Vec::new();
    let mut offset = TOKEN_2022_TLV_START;
    while offset + 4 <= data.len() {
        let extension_type = u16::from_le_bytes([data[offset], data[offset + 1]]);
        let value_len = u16::from_le_bytes([data[offset + 2], data[offset + 3]]);
        if extension_type == 0 && value_len == 0 {
            break;
        }
        let extension = TokenExtension {
            extension_type,
            value_len,
        };
        if extension.alters_transferred_amount() {
            return Err(PumpDecodeError::AmountAlteringTokenExtension {
                address: account.address.clone(),
                extension_type,
            });
        }
        extensions.push(extension);
        offset = offset
            .checked_add(4 + usize::from(value_len))
            .ok_or_else(|| PumpDecodeError::MalformedExtensionTlv(account.address.clone()))?;
        if offset > data.len() {
            return Err(PumpDecodeError::MalformedExtensionTlv(
                account.address.clone(),
            ));
        }
    }
    Ok(extensions)
}

fn require_owner(account: &RetainedAccount, owner: &str) -> Result<(), PumpDecodeError> {
    if account.owner == owner {
        Ok(())
    } else {
        Err(PumpDecodeError::UnexpectedOwner {
            address: account.address.clone(),
            expected: owner.to_owned(),
            found: account.owner.clone(),
        })
    }
}

fn require_token_program(account: &RetainedAccount) -> Result<(), PumpDecodeError> {
    if account.owner == SPL_TOKEN_PROGRAM_ID || account.owner == SPL_TOKEN_2022_PROGRAM_ID {
        Ok(())
    } else {
        Err(PumpDecodeError::UnexpectedOwner {
            address: account.address.clone(),
            expected: format!("{SPL_TOKEN_PROGRAM_ID} or {SPL_TOKEN_2022_PROGRAM_ID}"),
            found: account.owner.clone(),
        })
    }
}

fn require_len(account: &RetainedAccount, expected: usize) -> Result<(), PumpDecodeError> {
    if account.data.len() == expected {
        Ok(())
    } else {
        Err(PumpDecodeError::UnexpectedLength {
            address: account.address.clone(),
            expected,
            found: account.data.len(),
        })
    }
}

fn require_discriminator(
    account: &RetainedAccount,
    account_name: &'static str,
) -> Result<(), PumpDecodeError> {
    let expected = anchor_account_discriminator(account_name);
    if account.data.len() >= 8 && account.data[..8] == expected {
        Ok(())
    } else {
        Err(PumpDecodeError::DiscriminatorMismatch {
            address: account.address.clone(),
            account_name,
        })
    }
}

/// The first half-open range that is not entirely zero, as `(offset, length)`.
fn first_nonzero_range(data: &[u8], ranges: &[(usize, usize)]) -> Option<(usize, usize)> {
    ranges
        .iter()
        .copied()
        .find(|(start, end)| data[*start..*end].iter().any(|byte| *byte != 0))
        .map(|(start, end)| (start, end - start))
}

/// Reads a Borsh boolean, refusing any byte that is neither zero nor one.
///
/// A flag byte outside `{0, 1}` means the offset is wrong or the layout moved. Coercing it to
/// `true` would quietly turn a layout change into a wrong answer about whether a curve has already
/// migrated, which is the difference between two venues.
fn require_boolean(account: &RetainedAccount, offset: usize) -> Result<bool, PumpDecodeError> {
    match account.data[offset] {
        0 => Ok(false),
        1 => Ok(true),
        value => Err(PumpDecodeError::MalformedBoolean {
            address: account.address.clone(),
            offset,
            value,
        }),
    }
}

fn pubkey(data: &[u8], offset: usize) -> String {
    bs58::encode(&data[offset..offset + 32]).into_string()
}

fn u64_at(data: &[u8], offset: usize) -> u64 {
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&data[offset..offset + 8]);
    u64::from_le_bytes(bytes)
}

/// Refusals from reading a `PumpSwap` or Pump fee-program account.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum PumpDecodeError {
    #[error("account {address} is owned by {found}, not {expected}")]
    UnexpectedOwner {
        address: String,
        expected: String,
        found: String,
    },
    #[error("account {address} is {found} bytes, not the {expected} this layout requires")]
    UnexpectedLength {
        address: String,
        expected: usize,
        found: usize,
    },
    #[error("account {address} does not carry the recomputed {account_name} discriminator")]
    DiscriminatorMismatch {
        address: String,
        account_name: &'static str,
    },
    #[error(
        "pool {address} carries {len} bytes at offset {offset} that this layout requires to be \
         zero and that are not; this decoder can neither name nor locate a field there, so it \
         refuses rather than pricing against bytes it does not understand"
    )]
    PoolReservedRegionIsNonzero {
        address: String,
        offset: usize,
        len: usize,
    },
    #[error(
        "bonding curve {address} carries {len} bytes at offset {offset} that this layout requires \
         to be zero and that are not"
    )]
    CurveReservedRegionIsNonzero {
        address: String,
        offset: usize,
        len: usize,
    },
    #[error(
        "account {address} is {found} bytes, shorter than the {minimum} this layout's smallest \
         observed form needs"
    )]
    AccountShorterThanLayout {
        address: String,
        minimum: usize,
        found: usize,
    },
    #[error("account {address} has {value} at offset {offset}, which is not a boolean")]
    MalformedBoolean {
        address: String,
        offset: usize,
        value: u8,
    },
    #[error(
        "Global account {address} declares protocol {declared_protocol_bps} and creator \
         {declared_creator_bps} basis points, but the fee program applies \
         {applied_protocol_bps} and {applied_creator_bps}; reading Global would understate one \
         leg by {understated_leg_bps} basis points and a round trip by twice that"
    )]
    GlobalDeclaredRatesDisagreeWithFeeProgram {
        address: String,
        declared_protocol_bps: u64,
        declared_creator_bps: u64,
        applied_protocol_bps: u64,
        applied_creator_bps: u64,
        understated_leg_bps: u64,
    },
    #[error("token account {0} is uninitialized")]
    UninitializedTokenAccount(String),
    #[error("mint {0} is uninitialized")]
    UninitializedMint(String),
    #[error(
        "account {address} carries Token-2022 extension {extension_type}, which can change the \
         amount a transfer actually moves; a pool-reserve quote would not show that"
    )]
    AmountAlteringTokenExtension {
        address: String,
        extension_type: u16,
    },
    #[error("account {0} has a malformed Token-2022 extension region")]
    MalformedExtensionTlv(String),
    #[error("fee configuration {address} states {count} tiers, above the capacity {capacity}")]
    FeeTierCountOutOfRange {
        address: String,
        count: usize,
        capacity: usize,
    },
    #[error("fee configuration {address} tier table ends at {end}, past its {len} retained bytes")]
    FeeTierTableOverrunsAccount {
        address: String,
        end: usize,
        len: usize,
    },
    #[error("fee configuration {address} states a rate of {rate} basis points")]
    FeeRateAboveOneHundredPercent { address: String, rate: u64 },
    #[error("fee configuration {address} tier thresholds are not strictly increasing")]
    FeeTierThresholdsNotIncreasing { address: String },
    #[error("fee configuration {address} carries nonzero bytes after its last tier, at {offset}")]
    FeeConfigTrailerIsNonzero { address: String, offset: usize },
    #[error("fee configuration {0} carries an empty tier table")]
    EmptyFeeTierTable(String),
    #[error(
        "retained fee tier tables disagree at market cap {market_cap_quote_atoms} quote atoms: \
         {first:?} against {second:?}; these bytes do not state which table applies"
    )]
    FeeTierTablesDisagree {
        market_cap_quote_atoms: u128,
        first: FeeRatesBps,
        second: FeeRatesBps,
    },
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::solana_account::read_multiple_accounts;

    /// Exact `getMultipleAccounts` response body received from Helius mainnet on 2026-08-21 for
    /// the pool, its two vaults, its base mint, wrapped SOL, and the Pump fee configuration.
    const MAINNET: &str = include_str!("../fixtures/pump_swap_accounts_mainnet.json");
    const POOL: &str = "FnzKY6x7entQ1eR3D225dQyT7ybfka4PskBMQhb8L3CC";
    const BASE_VAULT: &str = "BmCXK8QFCHgjiqGm7peAtBbZpFPJNsp5fYP5rSRazMS8";
    const QUOTE_VAULT: &str = "DaXhQ3pfN3J5dQnXxVU8YqW9bwA3RUVxXvq2iBjTDVt4";
    const BASE_MINT: &str = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump";

    fn addresses() -> Vec<String> {
        [
            POOL,
            BASE_VAULT,
            QUOTE_VAULT,
            BASE_MINT,
            WRAPPED_SOL_MINT,
            PUMP_FEE_CONFIG_ADDRESS,
        ]
        .iter()
        .map(|value| (*value).to_owned())
        .collect()
    }

    fn response() -> crate::solana_account::AccountSetResponse {
        read_multiple_accounts(MAINNET.as_bytes(), &addresses()).expect("captured response decodes")
    }

    #[test]
    fn anchor_discriminators_are_recomputed_not_transcribed() {
        assert_eq!(
            anchor_account_discriminator("Pool"),
            [0xf1, 0x9a, 0x6d, 0x04, 0x11, 0xb1, 0x6d, 0xbc]
        );
        assert_eq!(
            anchor_account_discriminator("FeeConfig"),
            [0x8f, 0x34, 0x92, 0xbb, 0xdb, 0x7b, 0x4c, 0x9b]
        );
    }

    #[test]
    fn a_real_mainnet_pool_decodes_and_proves_its_own_identity() {
        let response = response();
        let pool = PumpSwapPool::decode(response.require(POOL).expect("pool present"))
            .expect("pool decodes");
        assert_eq!(pool.base_mint, BASE_MINT);
        assert_eq!(pool.quote_mint, WRAPPED_SOL_MINT);
        assert_eq!(pool.pool_base_token_account, BASE_VAULT);
        assert_eq!(pool.pool_quote_token_account, QUOTE_VAULT);
        assert_eq!(pool.index, 0);
        assert!(pool.has_coin_creator());
        // This pool's quote-side term happens to be zero. That is a fact about this pool, not a
        // property of the layout, which is exactly what the previous decoder got wrong.
        assert_eq!(pool.unattributed_quote_side_reserve_atoms, 0);
        assert_eq!(pool.effective_quote_atoms(1_000), 1_000);
        // The address and the contents agree without any outside input.
        assert_eq!(pool.self_derivation_bump(), Some(253));
    }

    #[test]
    fn a_nonzero_byte_in_a_required_zero_region_refuses_the_pool() {
        let response = response();
        for (start, end) in POOL_REQUIRED_ZERO_RANGES {
            for offset in [start, end - 1] {
                let mut account = response.require(POOL).expect("pool present").clone();
                account.data[offset] = 1;
                assert!(
                    matches!(
                        PumpSwapPool::decode(&account),
                        Err(PumpDecodeError::PoolReservedRegionIsNonzero { .. })
                    ),
                    "byte {offset} must refuse"
                );
            }
        }
    }

    #[test]
    fn the_located_quote_side_term_is_read_and_is_not_part_of_any_required_zero_region() {
        let response = response();
        let mut account = response.require(POOL).expect("pool present").clone();
        // Write a recognisable value across the whole located term and nowhere else.
        let value = 0x0123_4567_89ab_cdef_u64;
        account.data[POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET
            ..POOL_UNATTRIBUTED_QUOTE_SIDE_OFFSET + POOL_UNATTRIBUTED_QUOTE_SIDE_LEN]
            .copy_from_slice(&value.to_le_bytes());
        let pool = PumpSwapPool::decode(&account).expect("a located term is not a refusal");
        assert_eq!(pool.unattributed_quote_side_reserve_atoms, value);
        assert_eq!(
            pool.effective_quote_atoms(7),
            u128::from(value) + 7,
            "the effective quote reserve is the vault balance plus the located term"
        );
    }

    #[test]
    fn a_pool_read_under_the_wrong_owner_is_refused() {
        let response = response();
        let mut account = response.require(POOL).expect("pool present").clone();
        account.owner = SPL_TOKEN_PROGRAM_ID.to_owned();
        assert!(matches!(
            PumpSwapPool::decode(&account),
            Err(PumpDecodeError::UnexpectedOwner { .. })
        ));
    }

    #[test]
    fn both_real_vaults_and_the_real_base_mint_decode() {
        let response = response();
        let base = TokenVault::decode(response.require(BASE_VAULT).expect("base vault"))
            .expect("base vault decodes");
        let quote = TokenVault::decode(response.require(QUOTE_VAULT).expect("quote vault"))
            .expect("quote vault decodes");
        let mint = TokenMint::decode(response.require(BASE_MINT).expect("base mint"))
            .expect("base mint decodes");
        assert_eq!(base.mint, BASE_MINT);
        assert_eq!(quote.mint, WRAPPED_SOL_MINT);
        assert_eq!(base.token_program, SPL_TOKEN_2022_PROGRAM_ID);
        assert_eq!(quote.token_program, SPL_TOKEN_PROGRAM_ID);
        assert_eq!(mint.decimals, 6);
        assert!(base.amount > 0 && quote.amount > 0 && mint.supply > 0);
        // The observed extensions are metadata only; none of them can move a different amount.
        assert!(
            mint.extensions
                .iter()
                .all(|extension| !extension.alters_transferred_amount())
        );
    }

    #[test]
    fn a_transfer_fee_extension_refuses_the_whole_decode() {
        let response = response();
        let mut account = response.require(BASE_MINT).expect("base mint").clone();
        account.data[TOKEN_2022_TLV_START] = 1;
        account.data[TOKEN_2022_TLV_START + 1] = 0;
        assert!(matches!(
            TokenMint::decode(&account),
            Err(PumpDecodeError::AmountAlteringTokenExtension {
                extension_type: 1,
                ..
            })
        ));
    }

    #[test]
    fn the_real_fee_configuration_matches_its_declared_capacity_exactly() {
        let response = response();
        let account = response
            .require(PUMP_FEE_CONFIG_ADDRESS)
            .expect("fee config present");
        assert_eq!(account.data.len(), FEE_CONFIG_ACCOUNT_LEN);
        let config = PumpFeeConfig::decode(account).expect("fee config decodes");
        assert_eq!(config.tier_tables.len(), 2);
        for table in &config.tier_tables {
            assert!(!table.is_empty());
            assert_eq!(table[0].threshold_quote_atoms, 0);
        }
    }

    #[test]
    fn a_saturating_market_cap_makes_every_retained_tier_table_agree() {
        let response = response();
        let config = PumpFeeConfig::decode(
            response
                .require(PUMP_FEE_CONFIG_ADDRESS)
                .expect("fee config present"),
        )
        .expect("fee config decodes");
        let saturating = u128::from(u64::MAX);
        let rates = config.agreed_rates(saturating).expect("tables agree");
        assert_eq!(
            config.per_table_rates(saturating),
            vec![Some(rates), Some(rates)]
        );
    }

    #[test]
    fn a_market_cap_where_the_tables_differ_is_refused_rather_than_chosen() {
        let response = response();
        let config = PumpFeeConfig::decode(
            response
                .require(PUMP_FEE_CONFIG_ADDRESS)
                .expect("fee config present"),
        )
        .expect("fee config decodes");
        let disagreement = (0_u32..)
            .map(|step| u128::from(step) * 100_000_000_000)
            .take(2_000)
            .find(|value| config.agreed_rates(*value).is_err());
        assert!(
            disagreement.is_some(),
            "the retained tables must not be identical, or agreement would prove nothing"
        );
    }

    #[test]
    fn a_truncated_fee_configuration_is_refused_on_its_length_alone() {
        let response = response();
        let mut account = response
            .require(PUMP_FEE_CONFIG_ADDRESS)
            .expect("fee config present")
            .clone();
        account.data.truncate(FEE_CONFIG_ACCOUNT_LEN - 1);
        assert!(matches!(
            PumpFeeConfig::decode(&account),
            Err(PumpDecodeError::UnexpectedLength { .. })
        ));
    }

    #[test]
    fn every_named_program_address_is_the_derived_address_it_claims_to_be() {
        assert_eq!(
            fee_config_derivation_bump(PUMP_FEE_CONFIG_ADDRESS, PUMP_AMM_PROGRAM_ID),
            Some(255)
        );
        assert_eq!(
            fee_config_derivation_bump(
                PUMP_CURVE_FEE_CONFIG_ADDRESS,
                PUMP_BONDING_CURVE_PROGRAM_ID
            ),
            Some(253)
        );
        assert_eq!(global_derivation_bump(PUMP_GLOBAL_ADDRESS), Some(255));
        // The two configurations are not interchangeable, and the derivation says so.
        assert_eq!(
            fee_config_derivation_bump(PUMP_FEE_CONFIG_ADDRESS, PUMP_BONDING_CURVE_PROGRAM_ID),
            None
        );
    }
}

/// The venue geometry Study M0 measured, decoded from bytes read back at a later slot.
///
/// `fixtures/pump_venue_accounts_m0_pool.json` is one `getMultipleAccounts` response at finalized
/// slot 440840124 on 2026-08-22, covering the graduated pool and the live bonding curve M0 used.
/// The pool account, both fee configurations, and both quote-side mints hash to the exact digests
/// the M0 artifact recorded at slot 440832401, which is what lets these tests speak about M0's
/// numbers rather than about a different day's pool. The two vault balances and the curve reserves
/// did move, and nothing here asserts they did not.
#[cfg(test)]
mod m0_venue_tests {
    use super::*;
    use crate::solana_account::read_multiple_accounts;

    const M0: &str = include_str!("../fixtures/pump_venue_accounts_m0_pool.json");
    const POOL: &str = "7njsrpwivXWJYYTRbpJJ1UhfnjQHrhovuMbY6GLFfbBg";
    const POOL_BASE_VAULT: &str = "HPeNMPnuvq8qMefLtKAcaerissjryocgmcWNpcPMtzJA";
    const POOL_QUOTE_VAULT: &str = "ADYwrWVkqojYCCJwR3W5U8gaXw1BUiKYQhFA1pcgo2v1";
    const POOL_BASE_MINT: &str = "gV5pNNAfxLfJ1fX4kKzJGhENMgE9o12H5aUHUgipump";
    const CURVE: &str = "wrXaYnT8PBRSqigbLL3fTfHN2iYcGHCNfMwaGUKijeW";
    const CURVE_MINT: &str = "BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump";

    /// Digest the M0 artifact recorded for this account at slot 440832401.
    const M0_POOL_SHA256: &str = "57daef39d0e104d0e704af5290bad2ce808cea2ad6f274f9aa5ae4abd81b6a14";
    const M0_AMM_FEE_CONFIG_SHA256: &str =
        "e1c4647573d8caacc33b267781272c4fa0ad30a70900dddbaab512db670d3af2";
    const M0_CURVE_FEE_CONFIG_SHA256: &str =
        "d2864545485600cc11e919ab37c669ca2a31bf6de783ea4e5a0187eb7a203823";
    /// The value Study M0 read at offset 245 and reproduced four landed fills with.
    const M0_QUOTE_SIDE_TERM_ATOMS: u64 = 17_584_505_288;

    fn addresses() -> Vec<String> {
        [
            POOL,
            POOL_BASE_VAULT,
            POOL_QUOTE_VAULT,
            POOL_BASE_MINT,
            WRAPPED_SOL_MINT,
            PUMP_FEE_CONFIG_ADDRESS,
            CURVE,
            "CRNAnGfhY95Fma3CiQcQ5RMD9ebXoPc3TjoBRG6z7iYE",
            CURVE_MINT,
            PUMP_GLOBAL_ADDRESS,
            PUMP_CURVE_FEE_CONFIG_ADDRESS,
        ]
        .iter()
        .map(|value| (*value).to_owned())
        .collect()
    }

    fn response() -> crate::solana_account::AccountSetResponse {
        read_multiple_accounts(M0.as_bytes(), &addresses()).expect("captured response decodes")
    }

    fn digest(account: &RetainedAccount) -> String {
        use core::fmt::Write as _;
        Sha256::digest(&account.data)
            .iter()
            .fold(String::new(), |mut rendered, byte| {
                let _ = write!(rendered, "{byte:02x}");
                rendered
            })
    }

    #[test]
    fn the_pool_the_previous_decoder_refused_now_decodes_and_carries_m0s_own_number() {
        let response = response();
        let account = response.require(POOL).expect("pool present");
        assert_eq!(
            digest(account),
            M0_POOL_SHA256,
            "these must be the bytes M0 measured, or this test is about a different pool"
        );
        let pool = PumpSwapPool::decode(account).expect("the pool M0 measured must decode");
        assert_eq!(
            pool.unattributed_quote_side_reserve_atoms,
            M0_QUOTE_SIDE_TERM_ATOMS
        );
        assert_eq!(pool.base_mint, POOL_BASE_MINT);
        assert_eq!(pool.quote_mint, WRAPPED_SOL_MINT);
        assert_eq!(pool.self_derivation_bump(), Some(255));
    }

    #[test]
    fn omitting_the_located_term_overstates_base_out_by_four_times_the_round_trip_fee() {
        // The landed buy M0 checked: 154,956 quote atoms in against these vault balances produced
        // 1,243,374 base atoms. Both walks below are the deployed constant-product step; the only
        // difference is whether the term at offset 245 is in the quote reserve.
        let response = response();
        let pool = PumpSwapPool::decode(response.require(POOL).expect("pool")).expect("decodes");
        let base_vault_atoms = 12_007_887_448_401_u128;
        let quote_vault_atoms = 1_474_402_181_341_u64;
        let raw_quote_atoms = 154_490_u128;
        let landed_base_out_atoms = 1_243_374_u128;

        let with_term = pool.effective_quote_atoms(quote_vault_atoms);
        let honest = base_vault_atoms * raw_quote_atoms / (with_term + raw_quote_atoms);
        assert_eq!(honest, landed_base_out_atoms, "this fill landed on chain");

        let omitted = u128::from(quote_vault_atoms);
        let flattering = base_vault_atoms * raw_quote_atoms / (omitted + raw_quote_atoms);
        let overstatement_bps =
            (flattering - landed_base_out_atoms) * 10_000 / landed_base_out_atoms;
        assert_eq!(
            overstatement_bps, 119,
            "and it errs in the direction that makes the trade look better than it is"
        );
    }

    #[test]
    fn a_live_bonding_curve_decodes_and_is_bound_to_its_mint_by_derivation() {
        let response = response();
        let curve = PumpBondingCurve::decode(response.require(CURVE).expect("curve present"))
            .expect("curve decodes");
        assert!(
            !curve.complete,
            "a complete curve is not a venue, and this one was still trading"
        );
        assert!(curve.virtual_base_atoms > 0 && curve.virtual_quote_atoms > 0);
        assert_eq!(curve.creator_fee_applies(), Some(true));
        // Nothing in the curve account names the mint. This is the only thing that binds them.
        assert_eq!(bonding_curve_derivation_bump(CURVE, CURVE_MINT), Some(255));
        assert_eq!(bonding_curve_derivation_bump(CURVE, POOL_BASE_MINT), None);
        assert_eq!(
            bonding_curve_candidates(CURVE_MINT, 1),
            vec![(255, CURVE.to_owned())]
        );
        // Read and reported, never interpreted.
        assert_eq!(curve.unnamed_bytes, Some([0x00, 0x01]));
        assert_eq!(curve.account_len, 151);
        assert!(curve.has_priceable_reserves());
    }

    #[test]
    fn a_curve_whose_unlocated_region_is_nonzero_is_refused_rather_than_priced() {
        let response = response();
        let mut account = response.require(CURVE).expect("curve present").clone();
        account.data[BONDING_CURVE_LOCATED_LEN] = 1;
        assert!(matches!(
            PumpBondingCurve::decode(&account),
            Err(PumpDecodeError::CurveReservedRegionIsNonzero { .. })
        ));
    }

    #[test]
    fn a_located_but_unnamed_curve_region_is_reported_and_does_not_refuse() {
        // Both the two-byte region and the pubkey-shaped one are set on real curves. Refusing them
        // would refuse most of the market; interpreting them would be inventing a field.
        let response = response();
        let mut account = response.require(CURVE).expect("curve present").clone();
        account.data[BONDING_CURVE_UNNAMED_BYTES_RANGE.0] = 7;
        account.data[BONDING_CURVE_UNNAMED_PUBKEY_RANGE.0] = 9;
        let curve = PumpBondingCurve::decode(&account).expect("located regions do not refuse");
        assert_eq!(curve.unnamed_bytes, Some([7, 0x01]));
        assert!(curve.unnamed_pubkey.is_some());
    }

    #[test]
    fn a_shorter_curve_layout_reads_the_fields_it_has_and_says_the_rest_are_absent() {
        // Lengths 49, 115, 150, 151, and 256 all exist on mainnet. A missing creator field is not
        // a creator of zero, and this must not silently become "no creator fee".
        let response = response();
        let mut account = response.require(CURVE).expect("curve present").clone();
        account.data.truncate(BONDING_CURVE_CORE_LEN);
        let curve = PumpBondingCurve::decode(&account).expect("the shortest layout still decodes");
        assert_eq!(curve.account_len, BONDING_CURVE_CORE_LEN);
        assert_eq!(curve.creator, None);
        assert_eq!(curve.creator_fee_applies(), None);
        assert_eq!(curve.unnamed_bytes, None);
        assert_eq!(curve.unnamed_pubkey, None);
        assert_eq!(curve.virtual_quote_atoms, 30_559_816_690);

        account.data.truncate(BONDING_CURVE_CORE_LEN - 1);
        assert!(matches!(
            PumpBondingCurve::decode(&account),
            Err(PumpDecodeError::AccountShorterThanLayout { .. })
        ));
    }

    #[test]
    fn a_completion_flag_that_is_not_a_boolean_is_refused_rather_than_coerced() {
        let response = response();
        let mut account = response.require(CURVE).expect("curve present").clone();
        account.data[48] = 2;
        assert!(matches!(
            PumpBondingCurve::decode(&account),
            Err(PumpDecodeError::MalformedBoolean { offset: 48, .. })
        ));
    }

    #[test]
    fn reading_the_global_account_as_a_fee_source_is_a_refusal_and_names_the_shortfall() {
        // This is the regression the brief asked to keep loud. Global still declares a 5
        // basis-point creator fee. The fee program's configuration for the same program declares
        // 30, and the transfer that landed in M0's bonding-curve sell was 30. A caller that read
        // Global would have understated one leg by 25 basis points and a round trip by 50, against
        // a venue whose entire fee floor is 247.
        let response = response();
        let global = PumpGlobal::decode(
            response
                .require(PUMP_GLOBAL_ADDRESS)
                .expect("global present"),
        )
        .expect("global decodes");
        let fee_config = PumpFeeConfig::decode(
            response
                .require(PUMP_CURVE_FEE_CONFIG_ADDRESS)
                .expect("curve fee config present"),
        )
        .expect("fee config decodes");
        assert_eq!(
            digest(
                response
                    .require(PUMP_CURVE_FEE_CONFIG_ADDRESS)
                    .expect("present")
            ),
            M0_CURVE_FEE_CONFIG_SHA256
        );
        assert_eq!(
            digest(response.require(PUMP_FEE_CONFIG_ADDRESS).expect("present")),
            M0_AMM_FEE_CONFIG_SHA256
        );

        assert_eq!(global.declared_creator_fee_basis_points, 5);
        assert_eq!(global.declared_protocol_fee_basis_points, 95);

        // The curve's configuration is a single row at threshold zero, so it is unambiguous at
        // every market cap and no tier had to be chosen.
        let applied = fee_config
            .agreed_rates(0)
            .expect("the curve tables carry one row and agree");
        assert_eq!(applied.protocol, 95);
        assert_eq!(applied.creator, 30);
        assert_eq!(applied.lp, 0);

        let refusal = global
            .require_agreement_with_fee_program(applied)
            .expect_err("Global must not pass as a fee source");
        assert!(matches!(
            refusal,
            PumpDecodeError::GlobalDeclaredRatesDisagreeWithFeeProgram {
                declared_creator_bps: 5,
                applied_creator_bps: 30,
                understated_leg_bps: 25,
                ..
            }
        ));
        assert!(
            refusal.to_string().contains("25 basis points"),
            "the refusal must state the size of the error: {refusal}"
        );
    }

    #[test]
    fn agreeing_rates_are_not_refused_so_the_check_can_distinguish_the_two_cases() {
        let response = response();
        let global =
            PumpGlobal::decode(response.require(PUMP_GLOBAL_ADDRESS).expect("global")).expect("ok");
        assert!(
            global
                .require_agreement_with_fee_program(FeeRatesBps {
                    lp: 0,
                    protocol: global.declared_protocol_fee_basis_points,
                    creator: global.declared_creator_fee_basis_points,
                })
                .is_ok()
        );
    }

    #[test]
    fn a_global_account_of_the_wrong_length_is_refused_as_a_layout_tripwire() {
        let response = response();
        let mut account = response
            .require(PUMP_GLOBAL_ADDRESS)
            .expect("global")
            .clone();
        account.data.push(0);
        assert!(matches!(
            PumpGlobal::decode(&account),
            Err(PumpDecodeError::UnexpectedLength { .. })
        ));
    }

    #[test]
    fn both_pool_vaults_and_both_mints_decode_and_carry_no_amount_altering_extension() {
        let response = response();
        let pool = PumpSwapPool::decode(response.require(POOL).expect("pool")).expect("decodes");
        let base = TokenVault::decode(
            response
                .require(&pool.pool_base_token_account)
                .expect("base vault"),
        )
        .expect("base vault decodes");
        let quote = TokenVault::decode(
            response
                .require(&pool.pool_quote_token_account)
                .expect("quote vault"),
        )
        .expect("quote vault decodes");
        assert_eq!(base.mint, pool.base_mint);
        assert_eq!(quote.mint, pool.quote_mint);
        assert_eq!(base.owner, pool.address);
        assert_eq!(quote.owner, pool.address);
        let base_mint =
            TokenMint::decode(response.require(POOL_BASE_MINT).expect("mint")).expect("decodes");
        let curve_mint =
            TokenMint::decode(response.require(CURVE_MINT).expect("mint")).expect("decodes");
        assert_eq!(base_mint.decimals, 6);
        assert_eq!(curve_mint.decimals, 6);
    }
}
