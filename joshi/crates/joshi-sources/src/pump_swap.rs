//! Exact account decoders for the `PumpSwap` AMM program and the Pump fee program.
//!
//! Every decoder here reads bytes a provider actually returned and refuses anything it cannot read
//! literally. Three properties keep the layouts honest rather than assumed:
//!
//! 1. **Identity is proved, not asserted.** Each account is accepted only when its owning program
//!    matches and its leading eight bytes equal the Anchor account discriminator this crate
//!    recomputes from the account's declared name, `sha256("account:<Name>")[..8]`.
//! 2. **Nothing is attributed to bytes this decoder cannot name.** The `PumpSwap` pool layout is
//!    read through byte 243; the remaining 58 bytes are unattributed. `virtual_quote_reserves` is
//!    asserted to be zero only when that whole region is zero, because a signed field located
//!    anywhere inside an all-zero region is zero regardless of its offset. A nonzero unattributed
//!    region is refused, never guessed.
//! 3. **Structure is checked against the retained length.** The Pump fee configuration is accepted
//!    only when its exact allocated length equals the fixed layout plus two `FeeTier` vectors at
//!    their declared capacity, both vectors parse with strictly increasing thresholds and rates no
//!    greater than 10,000 basis points, and every byte past the last tier is zero.
//!
//! This module performs no economic action of any kind. It decodes retained bytes.

use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::solana_account::RetainedAccount;

/// `PumpSwap` AMM program. Every pool and fee-configuration account is checked against an owner.
pub const PUMP_AMM_PROGRAM_ID: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
/// Pump fee program that owns the market-cap fee-tier configuration.
pub const PUMP_FEE_PROGRAM_ID: &str = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ";
/// The fee-configuration account this crate reads.
///
/// This address is an input, exactly like a pool address: it was observed in the account list of a
/// landed `PumpSwap` swap and is supplied to the provider by the caller. It is never trusted on its
/// name — [`PumpFeeConfig::decode`] accepts the response only when the owner is
/// [`PUMP_FEE_PROGRAM_ID`] and the discriminator is the recomputed `FeeConfig` discriminator.
pub const PUMP_FEE_CONFIG_ADDRESS: &str = "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx";
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
/// First byte of the pool region this decoder does not attribute to a named field.
pub const POOL_ATTRIBUTED_LEN: usize = 243;
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
    /// Zero, and asserted only because the whole unattributed tail of the account is zero.
    pub virtual_quote_reserves: i128,
    /// Length of the region this decoder read literally.
    pub attributed_len: usize,
    /// Length of the region this decoder deliberately makes no claim about beyond it being zero.
    pub unattributed_zero_len: usize,
}

impl PumpSwapPool {
    /// Reads one `PumpSwap` pool account.
    ///
    /// # Errors
    ///
    /// Refuses a wrong owner, a wrong length, a discriminator that is not the recomputed `Pool`
    /// discriminator, and any nonzero byte in the unattributed tail.
    pub fn decode(account: &RetainedAccount) -> Result<Self, PumpDecodeError> {
        require_owner(account, PUMP_AMM_PROGRAM_ID)?;
        require_len(account, POOL_ACCOUNT_LEN)?;
        require_discriminator(account, "Pool")?;
        let data = &account.data;
        let tail = &data[POOL_ATTRIBUTED_LEN..];
        if tail.iter().any(|byte| *byte != 0) {
            return Err(PumpDecodeError::UnattributedPoolTailIsNonzero {
                address: account.address.clone(),
                offset: POOL_ATTRIBUTED_LEN,
                len: tail.len(),
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
            virtual_quote_reserves: 0,
            attributed_len: POOL_ATTRIBUTED_LEN,
            unattributed_zero_len: tail.len(),
        })
    }

    /// Whether the pool names a coin creator, which is what makes a creator fee applicable.
    #[must_use]
    pub fn has_coin_creator(&self) -> bool {
        self.coin_creator != DEFAULT_PUBKEY
    }
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
        "pool {address} carries {len} unattributed bytes at offset {offset} that are not zero, so \
         this decoder will not assert a virtual quote reserve it cannot locate"
    )]
    UnattributedPoolTailIsNonzero {
        address: String,
        offset: usize,
        len: usize,
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
        assert_eq!(pool.virtual_quote_reserves, 0);
        assert_eq!(
            pool.unattributed_zero_len,
            POOL_ACCOUNT_LEN - POOL_ATTRIBUTED_LEN
        );
    }

    #[test]
    fn a_nonzero_unattributed_tail_refuses_rather_than_guessing_a_virtual_reserve() {
        let response = response();
        let mut account = response.require(POOL).expect("pool present").clone();
        account.data[POOL_ATTRIBUTED_LEN] = 1;
        assert!(matches!(
            PumpSwapPool::decode(&account),
            Err(PumpDecodeError::UnattributedPoolTailIsNonzero { .. })
        ));
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
}
