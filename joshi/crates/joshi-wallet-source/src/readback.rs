//! Read-back of durably retained wallet observations into portfolio inputs.
//!
//! The live path drafts evidence as bytes arrive; this module walks the other direction. A
//! catalog already holds exact retained frames with their observation identities and clocks, and
//! everything derived here cites those stored identities instead of minting new ones. Nothing in
//! this module performs I/O: callers hand it stored payload bytes and stored identities.

use joshi_accounting::portfolio::{AssetRef, BalanceEventV1, ObservationRef};
use joshi_domain::{StableString, WireStringError};
use joshi_sources::{RETAINED_FRAME_ENVELOPE_VERSION, RetainedFrameEnvelope};
use serde_json::Value;
use thiserror::Error;

use crate::{AcquisitionSurface, PublicKey, RawTransactionFact};

/// What one stored acquisition locator says the retained body is.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StoredLocatorClass {
    /// A wallet acquisition surface this crate normalizes.
    WalletSurface(AcquisitionSurface),
    /// A `getSlot` control read: a chain-head reference, not a wallet fact.
    ChainSlot,
    /// A `getAccountInfo`/`getMultipleAccounts` read of account bytes.
    AccountRead,
    /// A locator this classifier does not recognize. The observation stays retained; it simply
    /// contributes nothing here.
    Unrecognized,
}

/// Classifies a stored redacted locator such as `helius:http:getTransaction`.
#[must_use]
pub fn classify_locator(locator: &str) -> StoredLocatorClass {
    let method = locator.rsplit(':').next().unwrap_or(locator);
    match method {
        "getTransaction" => {
            StoredLocatorClass::WalletSurface(AcquisitionSurface::SolanaGetTransaction)
        }
        "getSignaturesForAddress" => {
            StoredLocatorClass::WalletSurface(AcquisitionSurface::SolanaGetSignaturesForAddress)
        }
        "getTransactionsForAddress" => {
            StoredLocatorClass::WalletSurface(AcquisitionSurface::HeliusGetTransactionsForAddress)
        }
        "transactionSubscribe" => {
            StoredLocatorClass::WalletSurface(AcquisitionSurface::HeliusTransactionSubscribe)
        }
        "getSlot" => StoredLocatorClass::ChainSlot,
        "getAccountInfo" | "getMultipleAccounts" => StoredLocatorClass::AccountRead,
        _ => StoredLocatorClass::Unrecognized,
    }
}

/// A stored payload that could not be read back.
#[derive(Debug, Error)]
pub enum ReadbackError {
    /// The payload is not a retained-frame envelope this crate understands.
    #[error("stored payload is not a readable retained frame envelope: {0}")]
    Envelope(#[from] serde_json::Error),
    /// The envelope names a version this reader does not implement.
    #[error("retained frame envelope version {found:?} is not {expected:?}")]
    EnvelopeVersion { found: String, expected: String },
    /// A provider-stated value violated the shared wire contract.
    #[error("provider-stated value violated the wire contract: {0}")]
    Wire(#[from] WireStringError),
    /// The provider stated token decimals wider than the token program allows.
    #[error("provider stated {found} decimals for mint {mint}, which exceeds u8")]
    DecimalsOutOfRange { mint: String, found: u64 },
}

/// Parses one stored observation payload as the versioned retained-frame envelope.
///
/// # Errors
///
/// Fails when the bytes are not the envelope or name a version this reader does not implement.
pub fn parse_retained_envelope(payload: &[u8]) -> Result<RetainedFrameEnvelope, ReadbackError> {
    let envelope: RetainedFrameEnvelope = serde_json::from_slice(payload)?;
    if envelope.envelope_version != RETAINED_FRAME_ENVELOPE_VERSION {
        return Err(ReadbackError::EnvelopeVersion {
            found: envelope.envelope_version,
            expected: RETAINED_FRAME_ENVELOPE_VERSION.to_owned(),
        });
    }
    Ok(envelope)
}

/// One row of a stored `getSignaturesForAddress` page, as the provider stated it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignaturePageEntry {
    pub signature: String,
    pub slot: Option<u64>,
    /// True when the provider stated a non-null `err` for this signature.
    pub failed: bool,
    pub block_time: Option<i64>,
}

/// Reads the signature list out of a stored `getSignaturesForAddress` body.
///
/// Returns `None` when the body is not that shape; the caller keeps the observation and reports
/// it as unread rather than inventing rows.
#[must_use]
pub fn signature_page_entries(body: &[u8]) -> Option<Vec<SignaturePageEntry>> {
    let value: Value = serde_json::from_slice(body).ok()?;
    let entries = value.get("result")?.as_array()?;
    let mut rows = Vec::with_capacity(entries.len());
    for entry in entries {
        rows.push(SignaturePageEntry {
            signature: entry.get("signature")?.as_str()?.to_owned(),
            slot: entry.get("slot").and_then(Value::as_u64),
            failed: entry.get("err").is_some_and(|err| !err.is_null()),
            block_time: entry.get("blockTime").and_then(Value::as_i64),
        });
    }
    Some(rows)
}

/// Reads the slot out of a stored `getSlot` body.
#[must_use]
pub fn chain_head_slot(body: &[u8]) -> Option<u64> {
    let value: Value = serde_json::from_slice(body).ok()?;
    value.get("result")?.as_u64()
}

/// Extracts the wallet-scoped balance transitions one normalized transaction fact states.
///
/// A row appears only where the retained bytes themselves place the wallet at the boundary: the
/// native row requires the wallet's own account among the balance arrays, and a token row
/// requires the wallet as the provider-stated owner of the token account. Balances the
/// transaction left unchanged produce no row.
///
/// # Errors
///
/// Fails when a provider-stated value cannot satisfy the shared wire contract, including token
/// decimals wider than `u8`.
pub fn balance_events_for_wallet(
    fact: &RawTransactionFact,
    wallet: &PublicKey,
    provenance: &ObservationRef,
) -> Result<Vec<BalanceEventV1>, ReadbackError> {
    let mut events = Vec::new();
    let signature = StableString::new(fact.transaction.signature.as_str())?;
    for effect in &fact.native_effects {
        if effect.account == *wallet {
            events.push(BalanceEventV1 {
                provenance: provenance.clone(),
                signature: signature.clone(),
                slot: fact.transaction.slot,
                transaction_index: fact.transaction.transaction_index,
                block_time_seconds: fact.block_time_seconds,
                asset: AssetRef::Native,
                boundary_account: None,
                pre_atoms: effect.pre_atoms,
                post_atoms: effect.post_atoms,
            });
        }
    }
    for effect in &fact.token_effects {
        if effect.owner.as_ref() != Some(wallet) {
            continue;
        }
        let decimals =
            u8::try_from(effect.decimals.get()).map_err(|_| ReadbackError::DecimalsOutOfRange {
                mint: effect.mint.as_str().to_owned(),
                found: effect.decimals.get(),
            })?;
        let boundary_account = match &effect.account {
            Some(account) => Some(StableString::new(account.as_str())?),
            None => Some(StableString::new(format!(
                "account_index:{}",
                effect.account_index
            ))?),
        };
        events.push(BalanceEventV1 {
            provenance: provenance.clone(),
            signature: signature.clone(),
            slot: fact.transaction.slot,
            transaction_index: fact.transaction.transaction_index,
            block_time_seconds: fact.block_time_seconds,
            asset: AssetRef::Token {
                mint: StableString::new(effect.mint.as_str())?,
                decimals,
            },
            boundary_account,
            pre_atoms: effect.pre_atoms,
            post_atoms: effect.post_atoms,
        });
    }
    Ok(events)
}
