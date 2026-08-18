//! Pinned, read-only Pump/PumpSwap instruction decoding.
//!
//! The decoder recovers transaction intent from official Anchor instruction bytes. It promotes an
//! exact swap only when the same successful instruction invocation has unique, matching executed
//! transfer legs. Slippage bounds and requested amounts are never relabelled as landed fills.

use joshi_domain::{StableString, WireU64};
use serde::{Deserialize, Serialize};

use crate::{
    DecodedSwapInput, InstructionFact, NormalizationError, PublicKey, RawTransactionFact, SwapFact,
    TransferFact, admit_decoded_swap,
};

pub const PUMP_PROGRAM_ID: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
pub const PUMPSWAP_PROGRAM_ID: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
pub const PINNED_DECODER_VERSION: &str = "joshi.pump_instruction_decoder.v1";
pub const PINNED_PUMP_DOCS_COMMIT: &str = "9c82f61cb711b044a17f770ab8ce9f9bdf78f333";
pub const PINNED_PUMP_IDL_SHA256: &str =
    "b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49";
pub const PINNED_PUMPSWAP_IDL_SHA256: &str =
    "6b5c7ec4e5ef9742fa99dc57b0d75b1031b379bba02a7e1b3c5a4cad68d77e56";
pub const PINNED_PUMP_SDK_VERSION: &str = "1.36.0";
pub const PINNED_PUMPSWAP_SDK_VERSION: &str = "1.19.0";
pub const PINNED_PUMP_SDK_NPM_INTEGRITY: &str = "sha512-X8rf+Wm/p/jhBj6zbwouM9blJ3UW8XJFSL7YTT8osBnpHsOH0ccT0DjCkIi6AAT7b6jf1nM3MXk7l78Fuf1M0g==";
pub const PINNED_PUMPSWAP_SDK_NPM_INTEGRITY: &str = "sha512-ayLO7ESmPOpZfz1hQSiGJBanJVaQTQB/+8yRHiuZnaHIRMTwOYknH1EZr++tPNa+kYJgg8kccU98Jp9RGOdZLQ==";

const PUMP_BUY: [u8; 8] = [102, 6, 61, 18, 1, 218, 235, 234];
const PUMP_SELL: [u8; 8] = [51, 230, 133, 164, 1, 127, 131, 173];
const PUMP_BUY_V2: [u8; 8] = [184, 23, 238, 97, 103, 197, 211, 61];
const PUMP_SELL_V2: [u8; 8] = [93, 246, 130, 60, 231, 233, 64, 178];
const PUMP_BUY_EXACT_QUOTE_IN_V2: [u8; 8] = [194, 171, 28, 70, 104, 77, 91, 47];
const PUMPSWAP_BUY_EXACT_QUOTE_IN: [u8; 8] = [198, 46, 21, 82, 180, 217, 232, 112];

/// Exact instruction family under the two pinned official IDLs.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PinnedInstructionKind {
    PumpBuy,
    PumpSell,
    PumpBuyV2,
    PumpSellV2,
    PumpBuyExactQuoteInV2,
    PumpSwapBuy,
    PumpSwapBuyExactQuoteIn,
    PumpSwapSell,
}

/// Typed economic intent encoded by the instruction. These are bounds/requests, not fills.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PinnedSwapIntent {
    ExactBaseOutBuy {
        base_amount_out: WireU64,
        max_quote_amount_in: WireU64,
    },
    ExactQuoteInBuy {
        spendable_quote_in: WireU64,
        min_base_amount_out: WireU64,
    },
    ExactBaseInSell {
        base_amount_in: WireU64,
        min_quote_amount_out: WireU64,
    },
}

/// Exact presence/value of the IDL `OptionBool` volume-tracking argument.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum PinnedTrackVolume {
    FieldAbsent,
    IdlNone,
    Explicit(bool),
}

impl PinnedSwapIntent {
    const fn is_buy(&self) -> bool {
        matches!(
            self,
            Self::ExactBaseOutBuy { .. } | Self::ExactQuoteInBuy { .. }
        )
    }
}

/// Recognized instruction with its pinned account-layout interpretation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PinnedProtocolInstruction {
    pub decoder_version: StableString,
    pub instruction_kind: PinnedInstructionKind,
    pub instruction_path: Vec<WireU64>,
    pub program_id: PublicKey,
    pub trader_wallet: PublicKey,
    pub pool: PublicKey,
    pub base_mint: PublicKey,
    pub quote_asset_id: StableString,
    pub base_user_account: PublicKey,
    pub quote_user_account: PublicKey,
    pub base_pool_account: PublicKey,
    pub quote_pool_account: PublicKey,
    pub intent: PinnedSwapIntent,
    pub track_volume: PinnedTrackVolume,
}

/// Why a recognized instruction did or did not become an exact swap fact.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PinnedDecodeDisposition {
    ExactExecutedSwap,
    IntentOnlyTransactionFailed,
    IntentOnlyMissingOrAmbiguousExecutedLegs,
}

/// One recognized instruction and the optional exact fill it justified.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PinnedDecodeResult {
    pub instruction: PinnedProtocolInstruction,
    pub disposition: PinnedDecodeDisposition,
    pub exact_swap: Option<SwapFact>,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum PinnedDecoderError {
    #[error("recognized Pump/PumpSwap instruction bytes are malformed")]
    MalformedInstruction,
    #[error("recognized Pump/PumpSwap instruction has an incompatible account layout")]
    AccountLayout,
    #[error("strict swap admission rejected decoder output")]
    Admission,
    #[error("decoder could not construct a stable wire value")]
    Wire,
}

/// Decode every recognized top-level or inner Pump/PumpSwap instruction and attach exact swaps.
///
/// Unknown discriminators remain raw instructions. Recognized malformed instructions fail closed.
/// Calling this twice is idempotent: the exact decoded-swap set is replaced, not appended.
///
/// # Errors
///
/// Refuses malformed recognized bytes/account layouts or a strict evidence-admission mismatch.
pub fn apply_pinned_protocol_decoder(
    raw: &mut RawTransactionFact,
) -> Result<Vec<PinnedDecodeResult>, PinnedDecoderError> {
    let mut results = Vec::new();
    for instruction in &raw.instructions {
        let Some(decoded) = decode_instruction(instruction)? else {
            continue;
        };
        let (disposition, exact_swap) = if !raw.succeeded || !instruction.execution_succeeded {
            (PinnedDecodeDisposition::IntentOnlyTransactionFailed, None)
        } else if let Some(input) = exact_swap_input(
            raw,
            &decoded,
            WireU64::new(u64::try_from(results.len()).unwrap_or(u64::MAX)),
        )? {
            let swap = admit_decoded_swap(input, raw).map_err(|_| PinnedDecoderError::Admission)?;
            (PinnedDecodeDisposition::ExactExecutedSwap, Some(swap))
        } else {
            (
                PinnedDecodeDisposition::IntentOnlyMissingOrAmbiguousExecutedLegs,
                None,
            )
        };
        results.push(PinnedDecodeResult {
            instruction: decoded,
            disposition,
            exact_swap,
        });
    }
    raw.decoded_swaps = results
        .iter()
        .filter_map(|result| result.exact_swap.clone())
        .collect();
    Ok(results)
}

/// Decode one raw instruction against the pinned official IDL profiles without inferring a fill.
///
/// This narrow entry point exists for offline differential-vector conformance.
///
/// # Errors
///
/// Refuses malformed recognized bytes or an incompatible official account layout.
pub fn decode_pinned_protocol_instruction(
    instruction: &InstructionFact,
) -> Result<Option<PinnedProtocolInstruction>, PinnedDecoderError> {
    decode_instruction(instruction)
}

fn decode_instruction(
    instruction: &InstructionFact,
) -> Result<Option<PinnedProtocolInstruction>, PinnedDecoderError> {
    let Some(program) = instruction.program_id.as_ref() else {
        return Ok(None);
    };
    if program.as_str() != PUMP_PROGRAM_ID && program.as_str() != PUMPSWAP_PROGRAM_ID {
        return Ok(None);
    }
    let Some(encoded) = instruction.raw_data_base58.as_ref() else {
        return Ok(None);
    };
    let data = bs58::decode(encoded.as_str())
        .into_vec()
        .map_err(|_| PinnedDecoderError::MalformedInstruction)?;
    if data.len() < 8 {
        return Err(PinnedDecoderError::MalformedInstruction);
    }
    let discriminator: [u8; 8] = data[..8]
        .try_into()
        .map_err(|_| PinnedDecoderError::MalformedInstruction)?;
    let profile = if program.as_str() == PUMP_PROGRAM_ID {
        decode_pump(discriminator, &data)?
    } else {
        decode_pumpswap(discriminator, &data)?
    };
    let Some((instruction_kind, intent, layout, track_volume)) = profile else {
        return Ok(None);
    };
    layout.finish(
        instruction,
        program.clone(),
        instruction_kind,
        intent,
        track_volume,
    )
}

#[derive(Clone, Copy)]
struct AccountLayout {
    minimum_accounts: usize,
    trader: usize,
    pool: usize,
    base_mint: usize,
    quote_mint: Option<usize>,
    base_user: usize,
    quote_user: usize,
    base_pool: usize,
    quote_pool: usize,
    native_quote: bool,
}

type DecodedProfile = Option<(
    PinnedInstructionKind,
    PinnedSwapIntent,
    AccountLayout,
    PinnedTrackVolume,
)>;

impl AccountLayout {
    fn finish(
        self,
        instruction: &InstructionFact,
        program_id: PublicKey,
        instruction_kind: PinnedInstructionKind,
        intent: PinnedSwapIntent,
        track_volume: PinnedTrackVolume,
    ) -> Result<Option<PinnedProtocolInstruction>, PinnedDecoderError> {
        if instruction.accounts.len() < self.minimum_accounts {
            return Err(PinnedDecoderError::AccountLayout);
        }
        let account = |index: usize| {
            instruction
                .accounts
                .get(index)
                .map(|value| value.account.clone())
                .ok_or(PinnedDecoderError::AccountLayout)
        };
        let trader_wallet = account(self.trader)?;
        if !instruction.accounts[self.trader].signer {
            return Err(PinnedDecoderError::AccountLayout);
        }
        let quote_asset_id = if self.native_quote {
            stable("solana.native:SOL")?
        } else {
            stable(format!(
                "solana.mint:{}",
                account(self.quote_mint.ok_or(PinnedDecoderError::AccountLayout,)?)?
            ))?
        };
        let path = instruction.inner_index.map_or_else(
            || vec![instruction.outer_index],
            |inner| vec![instruction.outer_index, inner],
        );
        Ok(Some(PinnedProtocolInstruction {
            decoder_version: stable(PINNED_DECODER_VERSION)?,
            instruction_kind,
            instruction_path: path,
            program_id,
            trader_wallet,
            pool: account(self.pool)?,
            base_mint: account(self.base_mint)?,
            quote_asset_id,
            base_user_account: account(self.base_user)?,
            quote_user_account: account(self.quote_user)?,
            base_pool_account: account(self.base_pool)?,
            quote_pool_account: account(self.quote_pool)?,
            intent,
            track_volume,
        }))
    }
}

fn decode_pump(discriminator: [u8; 8], data: &[u8]) -> Result<DecodedProfile, PinnedDecoderError> {
    let legacy = AccountLayout {
        minimum_accounts: 7,
        trader: 6,
        pool: 3,
        base_mint: 2,
        quote_mint: None,
        base_user: 5,
        quote_user: 6,
        base_pool: 4,
        quote_pool: 3,
        native_quote: true,
    };
    let v2 = AccountLayout {
        minimum_accounts: 16,
        trader: 13,
        pool: 10,
        base_mint: 1,
        quote_mint: Some(2),
        base_user: 14,
        quote_user: 15,
        base_pool: 11,
        quote_pool: 12,
        native_quote: false,
    };
    let result = match discriminator {
        PUMP_BUY => {
            let track_volume = decode_option_bool_tail(data)?;
            (
                PinnedInstructionKind::PumpBuy,
                PinnedSwapIntent::ExactBaseOutBuy {
                    base_amount_out: read_u64(data, 8)?.into(),
                    max_quote_amount_in: read_u64(data, 16)?.into(),
                },
                legacy,
                track_volume,
            )
        }
        PUMP_SELL => {
            require_len(data, 24)?;
            (
                PinnedInstructionKind::PumpSell,
                PinnedSwapIntent::ExactBaseInSell {
                    base_amount_in: read_u64(data, 8)?.into(),
                    min_quote_amount_out: read_u64(data, 16)?.into(),
                },
                legacy,
                PinnedTrackVolume::FieldAbsent,
            )
        }
        PUMP_BUY_V2 => {
            require_len(data, 24)?;
            (
                PinnedInstructionKind::PumpBuyV2,
                PinnedSwapIntent::ExactBaseOutBuy {
                    base_amount_out: read_u64(data, 8)?.into(),
                    max_quote_amount_in: read_u64(data, 16)?.into(),
                },
                v2,
                PinnedTrackVolume::FieldAbsent,
            )
        }
        PUMP_SELL_V2 => {
            require_len(data, 24)?;
            (
                PinnedInstructionKind::PumpSellV2,
                PinnedSwapIntent::ExactBaseInSell {
                    base_amount_in: read_u64(data, 8)?.into(),
                    min_quote_amount_out: read_u64(data, 16)?.into(),
                },
                v2,
                PinnedTrackVolume::FieldAbsent,
            )
        }
        PUMP_BUY_EXACT_QUOTE_IN_V2 => {
            require_len(data, 24)?;
            (
                PinnedInstructionKind::PumpBuyExactQuoteInV2,
                PinnedSwapIntent::ExactQuoteInBuy {
                    spendable_quote_in: read_u64(data, 8)?.into(),
                    min_base_amount_out: read_u64(data, 16)?.into(),
                },
                v2,
                PinnedTrackVolume::FieldAbsent,
            )
        }
        _ => return Ok(None),
    };
    Ok(Some(result))
}

fn decode_pumpswap(
    discriminator: [u8; 8],
    data: &[u8],
) -> Result<DecodedProfile, PinnedDecoderError> {
    let layout = AccountLayout {
        minimum_accounts: 9,
        trader: 1,
        pool: 0,
        base_mint: 3,
        quote_mint: Some(4),
        base_user: 5,
        quote_user: 6,
        base_pool: 7,
        quote_pool: 8,
        native_quote: false,
    };
    let result = match discriminator {
        PUMP_BUY => {
            let track_volume = decode_option_bool_tail(data)?;
            (
                PinnedInstructionKind::PumpSwapBuy,
                PinnedSwapIntent::ExactBaseOutBuy {
                    base_amount_out: read_u64(data, 8)?.into(),
                    max_quote_amount_in: read_u64(data, 16)?.into(),
                },
                track_volume,
            )
        }
        PUMPSWAP_BUY_EXACT_QUOTE_IN => {
            let track_volume = decode_option_bool_tail(data)?;
            (
                PinnedInstructionKind::PumpSwapBuyExactQuoteIn,
                PinnedSwapIntent::ExactQuoteInBuy {
                    spendable_quote_in: read_u64(data, 8)?.into(),
                    min_base_amount_out: read_u64(data, 16)?.into(),
                },
                track_volume,
            )
        }
        PUMP_SELL => {
            require_len(data, 24)?;
            (
                PinnedInstructionKind::PumpSwapSell,
                PinnedSwapIntent::ExactBaseInSell {
                    base_amount_in: read_u64(data, 8)?.into(),
                    min_quote_amount_out: read_u64(data, 16)?.into(),
                },
                PinnedTrackVolume::FieldAbsent,
            )
        }
        _ => return Ok(None),
    };
    Ok(Some((result.0, result.1, layout, result.2)))
}

fn require_len(data: &[u8], len: usize) -> Result<(), PinnedDecoderError> {
    if data.len() == len {
        Ok(())
    } else {
        Err(PinnedDecoderError::MalformedInstruction)
    }
}

fn decode_option_bool_tail(data: &[u8]) -> Result<PinnedTrackVolume, PinnedDecoderError> {
    match data.get(24..) {
        Some([0]) => Ok(PinnedTrackVolume::IdlNone),
        Some([1, 0]) => Ok(PinnedTrackVolume::Explicit(false)),
        Some([1, 1]) => Ok(PinnedTrackVolume::Explicit(true)),
        _ => Err(PinnedDecoderError::MalformedInstruction),
    }
}

fn read_u64(data: &[u8], offset: usize) -> Result<u64, PinnedDecoderError> {
    let bytes: [u8; 8] = data
        .get(offset..offset + 8)
        .ok_or(PinnedDecoderError::MalformedInstruction)?
        .try_into()
        .map_err(|_| PinnedDecoderError::MalformedInstruction)?;
    Ok(u64::from_le_bytes(bytes))
}

fn exact_swap_input(
    raw: &RawTransactionFact,
    decoded: &PinnedProtocolInstruction,
    event_ordinal: WireU64,
) -> Result<Option<DecodedSwapInput>, PinnedDecoderError> {
    let base_asset = stable(format!("solana.mint:{}", decoded.base_mint))?;
    let (input, output) = if decoded.intent.is_buy() {
        (
            unique_transfer(
                raw,
                decoded,
                &decoded.quote_user_account,
                &decoded.quote_pool_account,
                &decoded.quote_asset_id,
            ),
            unique_transfer(
                raw,
                decoded,
                &decoded.base_pool_account,
                &decoded.base_user_account,
                &base_asset,
            ),
        )
    } else {
        (
            unique_transfer(
                raw,
                decoded,
                &decoded.base_user_account,
                &decoded.base_pool_account,
                &base_asset,
            ),
            unique_transfer(
                raw,
                decoded,
                &decoded.quote_pool_account,
                &decoded.quote_user_account,
                &decoded.quote_asset_id,
            ),
        )
    };
    let (Some(input), Some(output)) = (input, output) else {
        return Ok(None);
    };
    Ok(Some(DecodedSwapInput {
        decode_id: stable(format!(
            "pinned:{}:{}:{}",
            raw.transaction.signature,
            decoded
                .instruction_path
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>()
                .join("/"),
            PINNED_DECODER_VERSION
        ))?,
        decoder_version: stable(PINNED_DECODER_VERSION)?,
        observation_id: raw.observation_id.clone(),
        transaction: raw.transaction.clone(),
        instruction_path: decoded.instruction_path.clone(),
        event_ordinal,
        trader_wallet: decoded.trader_wallet.clone(),
        program_id: decoded.program_id.clone(),
        pool: Some(decoded.pool.clone()),
        input_asset_id: input.asset_id.clone(),
        input_atoms: input.atoms,
        output_asset_id: output.asset_id.clone(),
        output_atoms: output.atoms,
        available_at: raw.available_at,
    }))
}

fn unique_transfer<'a>(
    raw: &'a RawTransactionFact,
    decoded: &PinnedProtocolInstruction,
    from: &PublicKey,
    to: &PublicKey,
    asset_id: &StableString,
) -> Option<&'a TransferFact> {
    let outer = decoded.instruction_path[0];
    let mut matches = raw.executed_transfers.iter().filter(|transfer| {
        transfer.outer_index == Some(outer)
            && &transfer.from_account == from
            && &transfer.to_account == to
            && &transfer.asset_id == asset_id
            && transfer.atoms.get() > 0
    });
    let first = matches.next()?;
    matches.next().is_none().then_some(first)
}

fn stable(value: impl AsRef<str>) -> Result<StableString, PinnedDecoderError> {
    StableString::new(value.as_ref()).map_err(|_| PinnedDecoderError::Wire)
}

impl From<NormalizationError> for PinnedDecoderError {
    fn from(_: NormalizationError) -> Self {
        Self::Admission
    }
}
