//! Exact account decoders for the Meteora DLMM (`lb_clmm`) program.
//!
//! Written for one live question — what a DREGG/SOLVE order ladder actually earns — and kept so
//! the next DLMM question starts from code rather than archaeology. The same properties as
//! [`crate::pump_swap`] hold: identity is proved from bytes, not asserted; named and located
//! fields are labelled differently; and anything these bytes cannot state is carried as
//! unsupported rather than invented.
//!
//! **Layout provenance.** Field names and offsets come from the program's published Anchor IDL
//! (`lb_clmm` 0.12.0, `MeteoraAg/dlmm-sdk` `idls/dlmm.json`, fetched 2026-08-22), which is an
//! off-chain artifact. What binds it to the chain: the IDL's declared program address equals the
//! observed owning program, its declared `LbPair` and `PositionV2` discriminators equal
//! `sha256("account:<Name>")[..8]` recomputed here, both equal the leading bytes of the retained
//! mainnet accounts, and the IDL-computed struct sizes land exactly on the retained lengths (904
//! for `LbPair`; 8120 plus appended per-bin records for `PositionV2`). Decoded values were then
//! cross-checked against independent observations: the active-bin price implied by
//! `(1 + bin_step/10_000)^active_id` reproduced the externally quoted pool price to four
//! significant figures, and the pool's uncollected protocol fee equalled `protocol_share`
//! (10%) of the fee total implied by the pool's complete swap history.
//!
//! **What the bytes never say.** An `LbPair` names its mints only positionally — nothing in the
//! account states a symbol, a decimal count, or which side a human calls the base. Labels like
//! "DREGG" or "SOLVE" are outside attributions and stay outside this module.

use thiserror::Error;

use crate::pump_swap::anchor_account_discriminator;
use crate::solana_account::RetainedAccount;

/// Meteora DLMM program (`lb_clmm`). Owns every `LbPair`, `PositionV2`, and bin array.
pub const METEORA_DLMM_PROGRAM_ID: &str = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo";

/// Exact allocated length of an `LbPair` account.
pub const LB_PAIR_ACCOUNT_LEN: usize = 904;

/// Length of the fixed `PositionV2` layout the IDL declares: an eight-byte discriminator, two
/// pubkeys, seventy per-bin slots, and a fixed tail.
pub const POSITION_V2_FIXED_LEN: usize = 8120;

/// Per-bin slot count in the fixed `PositionV2` arrays.
pub const POSITION_V2_FIXED_BIN_SLOTS: usize = 70;

/// Bytes one bin costs a position: a `u128` liquidity share, a 48-byte reward record, and a
/// 48-byte fee record.
pub const POSITION_V2_BIN_RECORD_LEN: usize = 112;

/// Denominator of `bin_step` and `protocol_share`.
pub const BASIS_POINT_MAX: u32 = 10_000;

/// Denominator of every fee rate this module computes. A rate of `50_000_000` here is 5%.
pub const FEE_RATE_DENOMINATOR: u128 = 1_000_000_000;

/// Errors a Meteora account decode refuses with rather than guessing.
#[derive(Debug, Error)]
pub enum MeteoraDecodeError {
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
        "position {address} is {found} bytes, which is neither the fixed {fixed} nor the fixed \
         length plus a whole number of {record}-byte per-bin records; this decoder cannot lay out \
         what is there"
    )]
    ExtensionNotRecordAligned {
        address: String,
        found: usize,
        fixed: usize,
        record: usize,
    },
    #[error(
        "position {address} spans {bin_count} bins but carries {slots} per-bin slots; the layout \
         reading that reconciled the one observed extended position does not reconcile this one, \
         so its per-bin data is refused rather than misattributed"
    )]
    ExtensionDisagreesWithBinCount {
        address: String,
        bin_count: i64,
        slots: usize,
    },
}

/// Exact `LbPair` state read from one retained account.
///
/// Every field below is named by the IDL. Three fields the IDL names but does not give an enum
/// for — `pair_type`, `function_type`, `collect_fee_mode` — are carried as raw bytes with what
/// observation established documented, and no more.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeteoraLbPair {
    pub address: String,
    /// Static fee half: `base_factor` scales the base fee, see [`Self::base_fee_rate_per_1e9`].
    pub base_factor: u16,
    pub filter_period: u16,
    pub decay_period: u16,
    pub reduction_factor: u16,
    pub variable_fee_control: u32,
    pub max_volatility_accumulator: u32,
    pub min_bin_id: i32,
    pub max_bin_id: i32,
    /// Protocol's cut of every fee, in basis points of the fee (not of the trade). Observed
    /// tx-level: each swap's emitted `protocol_fee` was exactly this share of its `fee`.
    pub protocol_share: u16,
    pub base_fee_power_factor: u8,
    /// Named by the IDL, no enum given. Observed as 2 on the retained pair; meaning unsupported.
    pub function_type: u8,
    /// Named by the IDL, no enum given. Observed as 1 on a pair whose swap events carried
    /// `fees_on_token_x: false` in both directions, whose fee claims paid `fee_x = 0`, and whose
    /// uncollected protocol fee is zero on the X side — every observed fee lived on the Y side.
    /// That is an observation about value 1, not a name for the field.
    pub collect_fee_mode: u8,
    /// Volatility accumulator at retention time. Swaps refresh it; a stale
    /// [`Self::volatility_last_update_unix_s`] is bytes-level evidence of swap silence.
    pub volatility_accumulator: u32,
    pub volatility_reference: u32,
    pub index_reference: i32,
    pub volatility_last_update_unix_s: i64,
    /// `PairType` by IDL enum: 0 `Permissionless`, 1 `Permission`,
    /// 2 `CustomizablePermissionless`, 3 `PermissionlessV2`.
    pub pair_type: u8,
    /// The active bin. [`Self::bin_price_ratio`] of this id is the current pool price as a raw
    /// atom ratio.
    pub active_id: i32,
    /// Price increment per bin, in basis points: each bin's price is `1 + bin_step/10_000` times
    /// its neighbor's.
    pub bin_step: u16,
    /// `PairStatus` by IDL enum: 0 Enabled, 1 Disabled.
    pub status: u8,
    /// `ActivationType` by IDL enum: 0 Slot, 1 Timestamp.
    pub activation_type: u8,
    /// First mint, positionally. The bytes state no symbol and no decimals.
    pub token_x_mint: String,
    /// Second mint, positionally.
    pub token_y_mint: String,
    pub reserve_x: String,
    pub reserve_y: String,
    /// Uncollected protocol fee, X side, in atoms. Sits inside `reserve_x` until claimed, so a
    /// reserve balance overstates LP-owned liquidity by this amount.
    pub protocol_fee_x_atoms: u64,
    /// Uncollected protocol fee, Y side, in atoms. Same reserve caveat as the X side.
    pub protocol_fee_y_atoms: u64,
    pub oracle: String,
    pub creator: String,
    /// `TokenProgramFlags` by IDL enum: 0 `TokenProgram`, 1 `TokenProgram2022`. Verified once
    /// against the mint account's actual owning program rather than trusted.
    pub token_mint_x_program_flag: u8,
    pub token_mint_y_program_flag: u8,
    pub version: u8,
}

impl MeteoraLbPair {
    /// Reads one `LbPair` account.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a wrong length, and a discriminator that is not the recomputed
    /// `LbPair` discriminator.
    pub fn decode(account: &RetainedAccount) -> Result<Self, MeteoraDecodeError> {
        require_owner(account)?;
        require_len(account, LB_PAIR_ACCOUNT_LEN)?;
        require_discriminator(account, "LbPair")?;
        let data = &account.data;
        Ok(Self {
            address: account.address.clone(),
            base_factor: u16_at(data, 8),
            filter_period: u16_at(data, 10),
            decay_period: u16_at(data, 12),
            reduction_factor: u16_at(data, 14),
            variable_fee_control: u32_at(data, 16),
            max_volatility_accumulator: u32_at(data, 20),
            min_bin_id: i32_at(data, 24),
            max_bin_id: i32_at(data, 28),
            protocol_share: u16_at(data, 32),
            base_fee_power_factor: data[34],
            function_type: data[35],
            collect_fee_mode: data[36],
            volatility_accumulator: u32_at(data, 40),
            volatility_reference: u32_at(data, 44),
            index_reference: i32_at(data, 48),
            volatility_last_update_unix_s: i64_at(data, 56),
            pair_type: data[75],
            active_id: i32_at(data, 76),
            bin_step: u16_at(data, 80),
            status: data[82],
            activation_type: data[86],
            token_x_mint: pubkey(data, 88),
            token_y_mint: pubkey(data, 120),
            reserve_x: pubkey(data, 152),
            reserve_y: pubkey(data, 184),
            protocol_fee_x_atoms: u64_at(data, 216),
            protocol_fee_y_atoms: u64_at(data, 224),
            oracle: pubkey(data, 552),
            creator: pubkey(data, 848),
            token_mint_x_program_flag: data[880],
            token_mint_y_program_flag: data[881],
            version: data[882],
        })
    }

    /// The base fee rate, as a numerator over [`FEE_RATE_DENOMINATOR`].
    ///
    /// `base_factor * bin_step * 10 * 10^base_fee_power_factor`, the published `lb_clmm` base-fee
    /// composition. The formula is not stated by the account bytes; what the bytes support is
    /// that the retained pair's complete swap history paid total fees between this floor and
    /// this floor plus [`Self::max_variable_fee_rate_per_1e9`], and each observed swap's emitted
    /// rate sat in the same band.
    #[must_use]
    pub fn base_fee_rate_per_1e9(&self) -> u128 {
        u128::from(self.base_factor)
            * u128::from(self.bin_step)
            * 10
            * 10_u128.pow(u32::from(self.base_fee_power_factor))
    }

    /// The largest variable fee rate the pair's volatility ceiling allows, as a numerator over
    /// [`FEE_RATE_DENOMINATOR`]. Same provenance and caveat as [`Self::base_fee_rate_per_1e9`].
    #[must_use]
    pub fn max_variable_fee_rate_per_1e9(&self) -> u128 {
        if self.variable_fee_control == 0 {
            return 0;
        }
        let vfa_bin = u128::from(self.max_volatility_accumulator) * u128::from(self.bin_step);
        let squared = vfa_bin * vfa_bin;
        let scaled = u128::from(self.variable_fee_control) * squared;
        scaled.div_ceil(100_000_000_000)
    }

    /// Price of one bin as a raw atom ratio, Y atoms per X atom: `(1 + bin_step/10_000)^bin_id`.
    ///
    /// This is a ratio of atoms, not of display units. When the two mints declare different
    /// decimal counts the human-facing price differs by that power of ten, and the mints'
    /// decimals are not in these bytes — a caller who wants display units must bring them.
    #[must_use]
    pub fn bin_price_ratio(&self, bin_id: i32) -> f64 {
        (1.0 + f64::from(self.bin_step) / f64::from(BASIS_POINT_MAX)).powi(bin_id)
    }

    /// [`Self::bin_price_ratio`] of the active bin.
    #[must_use]
    pub fn active_price_ratio(&self) -> f64 {
        self.bin_price_ratio(self.active_id)
    }
}

/// Exact `PositionV2` state read from one retained account.
///
/// **The extension region.** The IDL declares fixed 70-slot arrays and a fixed 8120-byte length,
/// and the program also ships increase/decrease-position-length instructions. The one extended
/// position retained so far is 8232 bytes — the fixed layout plus exactly one
/// [`POSITION_V2_BIN_RECORD_LEN`]-byte record — and spans 71 bins by its own stated
/// `[lower_bin_id, upper_bin_id]`, while its fixed tail decodes coherently at the IDL's offsets
/// (its `last_updated_at` matches the block time of the transaction that created it). The layout
/// reading consistent with all of that is: fixed struct first, whole per-bin records appended
/// after it, one per bin past seventy. This decoder accepts exactly that family, checks the
/// record count against the stated bin span, and carries the appended bytes verbatim — located,
/// not named.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MeteoraPositionV2 {
    pub address: String,
    /// The pair this position is on. Stated by the position bytes themselves.
    pub lb_pair: String,
    pub owner: String,
    pub lower_bin_id: i32,
    /// Inclusive: the retained extended position states a span one wider than its fixed slots,
    /// and its record count reconciles only with an inclusive upper bound.
    pub upper_bin_id: i32,
    pub last_updated_at: i64,
    /// Fees this position has claimed over its lifetime, X side, in atoms.
    pub total_claimed_fee_x_atoms: u64,
    pub total_claimed_fee_y_atoms: u64,
    pub operator: String,
    pub fee_owner: String,
    pub version: u8,
    /// Liquidity shares of the seventy fixed slots, verbatim.
    pub liquidity_shares: Vec<u128>,
    /// Unclaimed fees pending across the seventy fixed slots, X side, in atoms. A bin carried in
    /// the extension region is **not** summed here — its record is appended bytes this decoder
    /// carries but does not attribute, so on an extended position this is a floor, not a total.
    pub pending_fee_x_atoms_fixed_slots: u64,
    /// Y-side counterpart of [`Self::pending_fee_x_atoms_fixed_slots`], same floor caveat.
    pub pending_fee_y_atoms_fixed_slots: u64,
    /// Appended per-bin records past the fixed layout, verbatim.
    pub extension_bytes: Vec<u8>,
}

impl MeteoraPositionV2 {
    /// Reads one `PositionV2` account, fixed or extended.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a wrong discriminator, a length that is not the fixed layout plus
    /// whole per-bin records, and a record count that does not reconcile with the position's own
    /// stated bin span.
    pub fn decode(account: &RetainedAccount) -> Result<Self, MeteoraDecodeError> {
        require_owner(account)?;
        require_discriminator(account, "PositionV2")?;
        let data = &account.data;
        if data.len() < POSITION_V2_FIXED_LEN {
            return Err(MeteoraDecodeError::UnexpectedLength {
                address: account.address.clone(),
                expected: POSITION_V2_FIXED_LEN,
                found: data.len(),
            });
        }
        let extension_len = data.len() - POSITION_V2_FIXED_LEN;
        if !extension_len.is_multiple_of(POSITION_V2_BIN_RECORD_LEN) {
            return Err(MeteoraDecodeError::ExtensionNotRecordAligned {
                address: account.address.clone(),
                found: data.len(),
                fixed: POSITION_V2_FIXED_LEN,
                record: POSITION_V2_BIN_RECORD_LEN,
            });
        }
        let extension_records = extension_len / POSITION_V2_BIN_RECORD_LEN;
        let lower_bin_id = i32_at(data, 7912);
        let upper_bin_id = i32_at(data, 7916);
        let bin_count = i64::from(upper_bin_id) - i64::from(lower_bin_id) + 1;
        let slots = POSITION_V2_FIXED_BIN_SLOTS + extension_records;
        // Slot counts are bounded by the account size and always fit; saturate rather
        // than carry a panic path.
        let slots_i64 = i64::try_from(slots).unwrap_or(i64::MAX);
        let reconciles = if extension_records == 0 {
            bin_count >= 1 && bin_count <= slots_i64
        } else {
            bin_count == slots_i64
        };
        if !reconciles {
            return Err(MeteoraDecodeError::ExtensionDisagreesWithBinCount {
                address: account.address.clone(),
                bin_count,
                slots,
            });
        }
        let liquidity_shares = (0..POSITION_V2_FIXED_BIN_SLOTS)
            .map(|slot| u128_at(data, 72 + 16 * slot))
            .collect();
        // Fixed fee records: 70 slots of {u128 fee_x_per_token_complete, u128
        // fee_y_per_token_complete, u64 fee_x_pending, u64 fee_y_pending} starting at 4552.
        let mut pending_x: u64 = 0;
        let mut pending_y: u64 = 0;
        for slot in 0..POSITION_V2_FIXED_BIN_SLOTS {
            let record = 4552 + 48 * slot;
            pending_x = pending_x.saturating_add(u64_at(data, record + 32));
            pending_y = pending_y.saturating_add(u64_at(data, record + 40));
        }
        Ok(Self {
            address: account.address.clone(),
            lb_pair: pubkey(data, 8),
            owner: pubkey(data, 40),
            lower_bin_id,
            upper_bin_id,
            last_updated_at: i64_at(data, 7920),
            total_claimed_fee_x_atoms: u64_at(data, 7928),
            total_claimed_fee_y_atoms: u64_at(data, 7936),
            operator: pubkey(data, 7960),
            fee_owner: pubkey(data, 8001),
            version: data[8033],
            liquidity_shares,
            pending_fee_x_atoms_fixed_slots: pending_x,
            pending_fee_y_atoms_fixed_slots: pending_y,
            extension_bytes: data[POSITION_V2_FIXED_LEN..].to_vec(),
        })
    }

    /// Bins this position spans by its own stated inclusive range.
    #[must_use]
    pub fn bin_count(&self) -> i64 {
        i64::from(self.upper_bin_id) - i64::from(self.lower_bin_id) + 1
    }

    /// Appended per-bin records past the fixed layout.
    #[must_use]
    pub fn extension_record_count(&self) -> usize {
        self.extension_bytes.len() / POSITION_V2_BIN_RECORD_LEN
    }
}

fn require_owner(account: &RetainedAccount) -> Result<(), MeteoraDecodeError> {
    if account.owner == METEORA_DLMM_PROGRAM_ID {
        Ok(())
    } else {
        Err(MeteoraDecodeError::UnexpectedOwner {
            address: account.address.clone(),
            expected: METEORA_DLMM_PROGRAM_ID.to_owned(),
            found: account.owner.clone(),
        })
    }
}

fn require_len(account: &RetainedAccount, expected: usize) -> Result<(), MeteoraDecodeError> {
    if account.data.len() == expected {
        Ok(())
    } else {
        Err(MeteoraDecodeError::UnexpectedLength {
            address: account.address.clone(),
            expected,
            found: account.data.len(),
        })
    }
}

fn require_discriminator(
    account: &RetainedAccount,
    account_name: &'static str,
) -> Result<(), MeteoraDecodeError> {
    let expected = anchor_account_discriminator(account_name);
    if account.data.len() >= 8 && account.data[..8] == expected {
        Ok(())
    } else {
        Err(MeteoraDecodeError::DiscriminatorMismatch {
            address: account.address.clone(),
            account_name,
        })
    }
}

fn pubkey(data: &[u8], offset: usize) -> String {
    bs58::encode(&data[offset..offset + 32]).into_string()
}

fn u16_at(data: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([data[offset], data[offset + 1]])
}

fn u32_at(data: &[u8], offset: usize) -> u32 {
    let mut bytes = [0_u8; 4];
    bytes.copy_from_slice(&data[offset..offset + 4]);
    u32::from_le_bytes(bytes)
}

fn i32_at(data: &[u8], offset: usize) -> i32 {
    let mut bytes = [0_u8; 4];
    bytes.copy_from_slice(&data[offset..offset + 4]);
    i32::from_le_bytes(bytes)
}

fn u64_at(data: &[u8], offset: usize) -> u64 {
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&data[offset..offset + 8]);
    u64::from_le_bytes(bytes)
}

fn i64_at(data: &[u8], offset: usize) -> i64 {
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&data[offset..offset + 8]);
    i64::from_le_bytes(bytes)
}

fn u128_at(data: &[u8], offset: usize) -> u128 {
    let mut bytes = [0_u8; 16];
    bytes.copy_from_slice(&data[offset..offset + 16]);
    u128::from_le_bytes(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::solana_account::read_account_info;

    /// Exact `getAccountInfo` response received from Helius mainnet on 2026-08-22 (slot
    /// 440996400) for the DREGG/SOLVE DLMM pair.
    const LBPAIR_MAINNET: &str = include_str!("../fixtures/meteora_dlmm_lbpair_mainnet.json");
    /// Exact `getAccountInfo` response received from Helius mainnet on 2026-08-22 for the single
    /// position account that existed on that pair — created earlier the same day, 8232 bytes,
    /// which is the fixed layout plus one appended per-bin record.
    const POSITION_MAINNET: &str = include_str!("../fixtures/meteora_dlmm_position_mainnet.json");

    const PAIR: &str = "HE9UXD4abY8dG1QEmyoZkSETZVScef3t2yZqhbWCT9aJ";
    const POSITION: &str = "CMgNgzL5i5ECiuyyFg8apB52KcM1yinNvCh2bs6TbuE9";
    const CREATOR: &str = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ";

    fn pair_account() -> RetainedAccount {
        read_account_info(LBPAIR_MAINNET.as_bytes(), PAIR)
            .expect("captured response decodes")
            .require(PAIR)
            .expect("pair present")
            .clone()
    }

    fn position_account() -> RetainedAccount {
        read_account_info(POSITION_MAINNET.as_bytes(), POSITION)
            .expect("captured response decodes")
            .require(POSITION)
            .expect("position present")
            .clone()
    }

    #[test]
    fn anchor_discriminators_are_recomputed_not_transcribed() {
        // The IDL declares these literally; recomputation and declaration agree.
        assert_eq!(
            anchor_account_discriminator("LbPair"),
            [0x21, 0x0b, 0x31, 0x62, 0xb5, 0x65, 0xb1, 0x0d]
        );
        assert_eq!(
            anchor_account_discriminator("PositionV2"),
            [0x75, 0xb0, 0xd4, 0xc7, 0xf5, 0xb4, 0x85, 0xb6]
        );
    }

    #[test]
    fn the_mainnet_pair_decodes_with_every_field_the_analysis_relied_on() {
        let pair = MeteoraLbPair::decode(&pair_account()).expect("pair decodes");
        assert_eq!(pair.bin_step, 125);
        assert_eq!(pair.base_factor, 40_000);
        assert_eq!(pair.base_fee_power_factor, 0);
        assert_eq!(pair.protocol_share, 1_000);
        assert_eq!(pair.variable_fee_control, 7_500);
        assert_eq!(pair.max_volatility_accumulator, 150_000);
        assert_eq!(pair.active_id, -126);
        assert_eq!(pair.status, 0, "PairStatus::Enabled");
        assert_eq!(pair.pair_type, 3, "PairType::PermissionlessV2");
        assert_eq!(pair.collect_fee_mode, 1);
        assert_eq!(
            pair.token_x_mint,
            "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"
        );
        assert_eq!(
            pair.token_y_mint,
            "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
        );
        assert_eq!(
            pair.reserve_x,
            "ELy19v2TigCQmgyj8MEZYzjpM9vLQ6GGLg3x6MLnEmZB"
        );
        assert_eq!(
            pair.reserve_y,
            "3dzF5omWG3bpAfGnZfiixh8tSAjmMp9KNtwfMdQNAPUZ"
        );
        assert_eq!(pair.creator, CREATOR);
        // Both mints flagged Token-2022; verified 2026-08-22 against the mint accounts' actual
        // owning program.
        assert_eq!(pair.token_mint_x_program_flag, 1);
        assert_eq!(pair.token_mint_y_program_flag, 1);
        // The fee-mode observation: with 37 swaps in both directions behind it, the uncollected
        // protocol fee is zero on X and nonzero on Y.
        assert_eq!(pair.protocol_fee_x_atoms, 0);
        assert_eq!(pair.protocol_fee_y_atoms, 10_786_133_760);
        // Volatility untouched since 2026-08-16T02:57:25Z at a retention six days later: the
        // bytes themselves state the swap silence the signature history showed.
        assert_eq!(pair.volatility_last_update_unix_s, 1_786_849_045);
        assert_eq!(pair.volatility_accumulator, 0);
    }

    #[test]
    fn fee_rates_compose_as_published_and_as_observed() {
        let pair = MeteoraLbPair::decode(&pair_account()).expect("pair decodes");
        // 40_000 * 125 * 10 over 1e9 = 5%.
        assert_eq!(pair.base_fee_rate_per_1e9(), 50_000_000);
        // 7_500 * (150_000 * 125)^2 ceil-scaled by 1e11, over 1e9 ~= 2.637%.
        assert_eq!(pair.max_variable_fee_rate_per_1e9(), 26_367_188);
        // The one fully decoded mainnet swap on this pair paid 19_237_676_447 fee atoms on
        // 356_124_365_011 atoms in: 5.402%, inside [base, base + max variable].
        let observed_rate_per_1e9 = 19_237_676_447_u128 * FEE_RATE_DENOMINATOR / 356_124_365_011;
        assert!(observed_rate_per_1e9 > pair.base_fee_rate_per_1e9());
        assert!(
            observed_rate_per_1e9
                < pair.base_fee_rate_per_1e9() + pair.max_variable_fee_rate_per_1e9()
        );
    }

    #[test]
    fn the_active_bin_price_reproduces_the_externally_quoted_pool_price() {
        let pair = MeteoraLbPair::decode(&pair_account()).expect("pair decodes");
        let price = pair.active_price_ratio();
        // (1.0125)^-126. The two mints both declare six decimals, so the atom ratio is also the
        // display ratio; that equal-decimals fact is from the mint accounts, not these bytes.
        assert!((price - 0.209_038).abs() < 0.000_001, "price was {price}");
    }

    #[test]
    fn the_mainnet_position_decodes_and_names_its_own_pair_and_owner() {
        let position = MeteoraPositionV2::decode(&position_account()).expect("position decodes");
        // Cross-account identity, all from retained bytes: the position states the pair it is
        // on, and its owner is the pair's creator.
        assert_eq!(position.lb_pair, PAIR);
        assert_eq!(position.owner, CREATOR);
        assert_eq!(position.lower_bin_id, -157);
        assert_eq!(position.upper_bin_id, -87);
        assert_eq!(position.bin_count(), 71);
        assert_eq!(position.extension_record_count(), 1);
        assert_eq!(position.version, 1);
        // Created the same day it was retained: nothing claimed, nothing pending yet.
        assert_eq!(position.total_claimed_fee_x_atoms, 0);
        assert_eq!(position.total_claimed_fee_y_atoms, 0);
        assert_eq!(position.pending_fee_x_atoms_fixed_slots, 0);
        assert_eq!(position.pending_fee_y_atoms_fixed_slots, 0);
        // Every fixed slot is funded, and the one appended record leads with a nonzero
        // u128-shaped value in the share position of the record layout.
        assert!(position.liquidity_shares.iter().all(|share| *share > 0));
        assert!(position.extension_bytes[..16].iter().any(|byte| *byte != 0));
        assert!(position.extension_bytes[16..].iter().all(|byte| *byte == 0));
    }

    #[test]
    fn a_wrong_owner_refuses_both_accounts() {
        let mut pair = pair_account();
        pair.owner = crate::pump_swap::PUMP_AMM_PROGRAM_ID.to_owned();
        assert!(matches!(
            MeteoraLbPair::decode(&pair),
            Err(MeteoraDecodeError::UnexpectedOwner { .. })
        ));
        let mut position = position_account();
        position.owner = crate::pump_swap::PUMP_AMM_PROGRAM_ID.to_owned();
        assert!(matches!(
            MeteoraPositionV2::decode(&position),
            Err(MeteoraDecodeError::UnexpectedOwner { .. })
        ));
    }

    #[test]
    fn a_flipped_discriminator_byte_refuses_the_account() {
        let mut pair = pair_account();
        pair.data[0] ^= 0x01;
        assert!(matches!(
            MeteoraLbPair::decode(&pair),
            Err(MeteoraDecodeError::DiscriminatorMismatch {
                account_name: "LbPair",
                ..
            })
        ));
        let mut position = position_account();
        position.data[7] ^= 0x01;
        assert!(matches!(
            MeteoraPositionV2::decode(&position),
            Err(MeteoraDecodeError::DiscriminatorMismatch {
                account_name: "PositionV2",
                ..
            })
        ));
    }

    #[test]
    fn a_truncated_pair_refuses_on_length() {
        let mut pair = pair_account();
        pair.data.pop();
        assert!(matches!(
            MeteoraLbPair::decode(&pair),
            Err(MeteoraDecodeError::UnexpectedLength {
                expected: LB_PAIR_ACCOUNT_LEN,
                found: 903,
                ..
            })
        ));
    }

    #[test]
    fn a_position_length_that_is_not_whole_records_is_refused() {
        let mut position = position_account();
        position.data.pop();
        assert!(matches!(
            MeteoraPositionV2::decode(&position),
            Err(MeteoraDecodeError::ExtensionNotRecordAligned { found: 8231, .. })
        ));
    }

    #[test]
    fn a_position_shorter_than_the_fixed_layout_is_refused() {
        let mut position = position_account();
        position.data.truncate(POSITION_V2_FIXED_LEN - 1);
        assert!(matches!(
            MeteoraPositionV2::decode(&position),
            Err(MeteoraDecodeError::UnexpectedLength {
                expected: POSITION_V2_FIXED_LEN,
                ..
            })
        ));
    }

    #[test]
    fn an_extension_that_disagrees_with_the_stated_bin_span_is_refused() {
        let mut position = position_account();
        // Append a second whole record without widening the stated span: 72 slots for 71 bins.
        position
            .data
            .extend(std::iter::repeat_n(0_u8, POSITION_V2_BIN_RECORD_LEN));
        assert!(matches!(
            MeteoraPositionV2::decode(&position),
            Err(MeteoraDecodeError::ExtensionDisagreesWithBinCount {
                bin_count: 71,
                slots: 72,
                ..
            })
        ));
    }
}
