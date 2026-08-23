use std::collections::{BTreeMap, BTreeSet};

use joshi_domain::{ObservationId, StableString, UtcTimestamp, WireU64};
use joshi_evidence::EvidenceDraft;
use joshi_sources::{EvidenceContext, RawSourceFrame, observation_draft};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{
    AccountEffect, AccountRole, AcquisitionSurface, AtomDelta, Canonicality, ChainCorrection,
    ChainCorrectionKind, Commitment, CoverageAssessment, CoverageVerificationStatus,
    DecodedSwapInput, EnhancedProjection, EnhancedTransferProjection, FundingHypothesis,
    FundingHypothesisInput, InstructionAccount, InstructionFact, MintRelativeWalletFlow,
    NormalizationIssue, NormalizedWalletBatch, ProgramOccurrence, PublicKey, RawTransactionFact,
    SameTransactionBundle, SwapFact, TokenEffect, TransactionLocator, TransactionVersionInput,
    TransferFact, TransferKind, Venue,
};

const PUMP_PROGRAM: &str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P";
const PUMPSWAP_PROGRAM: &str = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA";
const SYSTEM_PROGRAM: &str = "11111111111111111111111111111111";
const TOKEN_PROGRAM: &str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA";
const TOKEN_2022_PROGRAM: &str = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb";

/// Non-secret request context supplied alongside one exact raw source frame.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AcquisitionResponseContext {
    pub surface: AcquisitionSurface,
    pub scope_ids: Vec<StableString>,
    pub requested_public_keys: Vec<PublicKey>,
    pub mint_filter: Option<PublicKey>,
    pub commitment: Commitment,
    pub available_at: UtcTimestamp,
    pub cursor_before: Option<StableString>,
    pub coverage_gap_ids: Vec<StableString>,
    pub coverage_ids: Vec<StableString>,
    pub transaction_versions: Vec<TransactionVersionInput>,
}

/// Exact evidence plus additive normalization. Durable admission still belongs to the one writer.
#[derive(Debug)]
pub struct WalletAcquisitionOutput {
    pub evidence: EvidenceDraft,
    pub normalized: NormalizedWalletBatch,
}

#[derive(Debug, thiserror::Error)]
pub enum NormalizationError {
    #[error("source evidence envelope rejected the frame")]
    Evidence(#[from] joshi_sources::EvidenceAdapterError),
    #[error("normalizer could not construct a stable identifier")]
    Identifier,
    #[error("normalized exact atom sum overflowed")]
    AtomOverflow,
    #[error("decoded swap does not match its raw transaction evidence")]
    DecoderEvidenceMismatch,
    #[error("funding hypothesis does not match its cited direct transfer")]
    FundingEvidenceMismatch,
    #[error("transaction fact version must be positive")]
    InvalidFactVersion,
    #[error("normalized availability precedes retained source evidence availability")]
    InvalidAvailability,
}

/// Preserve a raw source frame and derive wallet facts without replacing exact bytes.
///
/// Malformed/provider-error payloads remain successful evidence acquisitions with explicit issues.
///
/// # Errors
///
/// Fails only when the source evidence envelope or a required internal identifier is invalid.
pub fn normalize_frame(
    frame: RawSourceFrame,
    evidence_context: EvidenceContext,
    response_context: &AcquisitionResponseContext,
) -> Result<WalletAcquisitionOutput, NormalizationError> {
    let bytes = frame.body.clone();
    let evidence = observation_draft(frame, evidence_context)?;
    let EvidenceDraft::Observation(observation) = &evidence else {
        unreachable!("source observation adapter always returns an observation")
    };
    if response_context.available_at < observation.observation.timing.available_at {
        return Err(NormalizationError::InvalidAvailability);
    }
    let observation_id = observation.observation.observation_id.clone();
    let normalized = normalize_bytes(&bytes, observation_id, response_context)?;
    Ok(WalletAcquisitionOutput {
        evidence,
        normalized,
    })
}

/// Derives wallet facts from a durably retained provider body without drafting new evidence.
///
/// This is the read-back twin of [`normalize_frame`]: the caller already holds a stored
/// observation (identity, clocks, exact body bytes) and wants the same normalization the live
/// path would have produced, citing the stored observation instead of minting a new one.
///
/// # Errors
///
/// Fails only when a required internal identifier cannot be constructed. Malformed provider
/// bodies remain successful normalizations with explicit issues.
pub fn normalize_stored_body(
    body: &[u8],
    observation_id: ObservationId,
    response_context: &AcquisitionResponseContext,
) -> Result<NormalizedWalletBatch, NormalizationError> {
    normalize_bytes(body, observation_id, response_context)
}

// Keep source-surface dispatch together so every branch produces the same coverage closure.
#[allow(clippy::too_many_lines)]
fn normalize_bytes(
    bytes: &[u8],
    observation_id: ObservationId,
    context: &AcquisitionResponseContext,
) -> Result<NormalizedWalletBatch, NormalizationError> {
    let mut issues = Vec::new();
    let mut raw_transactions = Vec::new();
    let mut enhanced_projections = Vec::new();
    let mut slots = Vec::new();
    let mut cursor = None;
    let mut page_exhausted = false;
    let Ok(value) = serde_json::from_slice::<Value>(bytes) else {
        issues.push(NormalizationIssue::MalformedProviderJson);
        return batch(
            observation_id,
            raw_transactions,
            enhanced_projections,
            coverage(context, &slots, cursor, false),
            issues,
        );
    };
    if value.get("error").is_some() {
        issues.push(NormalizationIssue::ProviderError);
        return batch(
            observation_id,
            raw_transactions,
            enhanced_projections,
            coverage(context, &slots, cursor, false),
            issues,
        );
    }
    match context.surface {
        AcquisitionSurface::SolanaGetTransaction => {
            match value.get("result") {
                Some(result) if !result.is_null() => {
                    if let Some(fact) = parse_raw_transaction(
                        result,
                        RawShape::Standard,
                        &observation_id,
                        context,
                        &mut issues,
                    )? {
                        slots.push(fact.transaction.slot);
                        raw_transactions.push(fact);
                    }
                }
                _ => issues.push(NormalizationIssue::NullTransaction),
            }
            page_exhausted = true;
        }
        AcquisitionSurface::HeliusGetTransactionsForAddress => {
            let entries = value.pointer("/result/data").and_then(Value::as_array);
            if let Some(entries) = entries {
                for entry in entries {
                    if let Some(fact) = parse_raw_transaction(
                        entry,
                        RawShape::AddressHistory,
                        &observation_id,
                        context,
                        &mut issues,
                    )? {
                        slots.push(fact.transaction.slot);
                        raw_transactions.push(fact);
                    }
                }
            }
            cursor = value
                .pointer("/result/paginationToken")
                .and_then(Value::as_str)
                .map(stable)
                .transpose()?;
            page_exhausted = cursor.is_none();
        }
        AcquisitionSurface::HeliusTransactionSubscribe => {
            if let Some(result) = value.pointer("/params/result")
                && let Some(fact) = parse_raw_transaction(
                    result,
                    RawShape::TransactionNotification,
                    &observation_id,
                    context,
                    &mut issues,
                )?
            {
                slots.push(fact.transaction.slot);
                raw_transactions.push(fact);
            }
        }
        AcquisitionSurface::SolanaGetSignaturesForAddress => {
            if let Some(entries) = value.get("result").and_then(Value::as_array) {
                for entry in entries {
                    if let Some(slot) = entry.get("slot").and_then(Value::as_u64) {
                        slots.push(slot.into());
                    }
                }
                cursor = entries
                    .last()
                    .and_then(|entry| entry.get("signature"))
                    .and_then(Value::as_str)
                    .map(stable)
                    .transpose()?;
                page_exhausted = entries.is_empty();
            }
        }
        AcquisitionSurface::HeliusLegacyEnhancedCrossCheck => {
            let entries = value.as_array().cloned().unwrap_or_default();
            for (ordinal, entry) in entries.iter().enumerate() {
                if let Some(projection) =
                    parse_enhanced_projection(entry, ordinal, &observation_id, context)?
                {
                    if let Some(slot) = projection.slot {
                        slots.push(slot);
                    }
                    enhanced_projections.push(projection);
                }
            }
            issues.push(NormalizationIssue::LegacyEnhancedNeedsRawReconciliation);
            page_exhausted = entries.is_empty();
        }
    }
    batch(
        observation_id,
        raw_transactions,
        enhanced_projections,
        coverage(context, &slots, cursor, page_exhausted),
        issues,
    )
}

fn batch(
    observation_id: ObservationId,
    raw_transactions: Vec<RawTransactionFact>,
    enhanced_projections: Vec<EnhancedProjection>,
    coverage: CoverageAssessment,
    issues: Vec<NormalizationIssue>,
) -> Result<NormalizedWalletBatch, NormalizationError> {
    Ok(NormalizedWalletBatch {
        contract_version: stable(crate::WALLET_SOURCE_CONTRACT_VERSION)?,
        observation_id,
        raw_transactions,
        enhanced_projections,
        coverage,
        issues,
    })
}

fn coverage(
    context: &AcquisitionResponseContext,
    slots: &[WireU64],
    cursor: Option<StableString>,
    page_exhausted: bool,
) -> CoverageAssessment {
    CoverageAssessment {
        scope_ids: context.scope_ids.clone(),
        lower_slot: slots.iter().min().copied(),
        upper_slot: slots.iter().max().copied(),
        source_cursor_candidate: cursor,
        page_exhausted,
        gap_ids: context.coverage_gap_ids.clone(),
        verification_status: CoverageVerificationStatus::RequestedUnverified,
    }
}

#[derive(Clone, Copy)]
enum RawShape {
    Standard,
    AddressHistory,
    TransactionNotification,
}

#[allow(clippy::too_many_lines)]
fn parse_raw_transaction(
    entry: &Value,
    shape: RawShape,
    observation_id: &ObservationId,
    context: &AcquisitionResponseContext,
    issues: &mut Vec<NormalizationIssue>,
) -> Result<Option<RawTransactionFact>, NormalizationError> {
    let (transaction, meta) = match shape {
        RawShape::Standard | RawShape::AddressHistory => {
            (entry.get("transaction"), entry.get("meta"))
        }
        RawShape::TransactionNotification => (
            entry.pointer("/transaction/transaction"),
            entry.pointer("/transaction/meta"),
        ),
    };
    let Some(transaction) = transaction else {
        issues.push(NormalizationIssue::Other(stable(
            "missing_transaction_body",
        )?));
        return Ok(None);
    };
    let Some(meta) = meta else {
        issues.push(NormalizationIssue::MissingMeta);
        return Ok(None);
    };
    let signature = entry
        .get("signature")
        .and_then(Value::as_str)
        .or_else(|| transaction.pointer("/signatures/0").and_then(Value::as_str));
    let Some(signature) = signature else {
        issues.push(NormalizationIssue::Other(stable("missing_signature")?));
        return Ok(None);
    };
    let slot = entry.get("slot").and_then(Value::as_u64);
    let Some(slot) = slot else {
        issues.push(NormalizationIssue::Other(stable("missing_slot")?));
        return Ok(None);
    };
    let transaction_index = entry
        .get("transactionIndex")
        .and_then(Value::as_u64)
        .map(WireU64::new);
    if transaction_index.is_none() {
        issues.push(NormalizationIssue::MissingTransactionIndex);
    }
    let locator = TransactionLocator {
        signature: stable(signature)?,
        slot: slot.into(),
        transaction_index,
    };
    let version_input = context
        .transaction_versions
        .iter()
        .find(|version| version.signature.as_str() == signature);
    let version = version_input.map_or(WireU64::new(1), |input| input.version);
    if version.get() == 0 {
        return Err(NormalizationError::InvalidFactVersion);
    }
    let fact_id = stable(format!("solana.transaction:{signature}:v{version}"))?;
    let canonicality = version_input.map_or(Canonicality::ObservedAtCommitment, |input| {
        input.canonicality.clone()
    });
    let supersedes_transaction_fact_id =
        version_input.and_then(|input| input.supersedes_transaction_fact_id.clone());
    let succeeded = meta.get("err").is_some_and(Value::is_null);
    let accounts = parse_accounts(transaction, meta, issues);
    let native_effects = parse_native_effects(meta, &accounts);
    let token_effects = parse_token_effects(meta, &accounts);
    let (instructions, programs, transfers) = parse_instructions(
        transaction,
        meta,
        &accounts,
        &token_effects,
        &locator,
        &fact_id,
        succeeded,
        issues,
    )?;
    let ordered_accounts = accounts
        .iter()
        .map(|role| role.account.clone())
        .collect::<Vec<_>>();
    let signer_accounts = accounts
        .iter()
        .filter(|role| role.signer)
        .map(|role| role.account.clone())
        .collect();
    let ordered_fact_ids = instructions
        .iter()
        .map(|instruction| instruction.instruction_id.clone())
        .collect();
    let block_time_seconds = entry
        .get("blockTime")
        .and_then(Value::as_u64)
        .map(WireU64::new);
    if block_time_seconds.is_none() {
        issues.push(NormalizationIssue::MissingBlockTime);
    }
    Ok(Some(RawTransactionFact {
        fact_id: fact_id.clone(),
        version,
        supersedes_transaction_fact_id,
        canonicality,
        observation_id: observation_id.clone(),
        source_event_ids: Vec::new(),
        transaction: locator.clone(),
        block_time_seconds,
        available_at: context.available_at,
        commitment: context.commitment,
        succeeded,
        fee_atoms: meta.get("fee").and_then(Value::as_u64).map(WireU64::new),
        account_roles: accounts,
        native_effects,
        token_effects,
        instructions,
        programs,
        executed_transfers: transfers,
        decoded_swaps: Vec::new(),
        same_transaction_bundle: SameTransactionBundle {
            bundle_id: stable(format!("solana.same_tx_bundle:{signature}:v{version}"))?,
            transaction_fact_id: fact_id,
            transaction: locator,
            ordered_accounts,
            signer_accounts,
            ordered_fact_ids,
        },
        query_scope_ids: context.scope_ids.clone(),
        requested_coverage_ids: context.coverage_ids.clone(),
    }))
}

fn parse_accounts(
    transaction: &Value,
    meta: &Value,
    issues: &mut Vec<NormalizationIssue>,
) -> Vec<AccountRole> {
    let Some(keys) = transaction
        .pointer("/message/accountKeys")
        .and_then(Value::as_array)
    else {
        issues.push(NormalizationIssue::UnknownAccountKeyShape);
        return Vec::new();
    };
    let required = transaction
        .pointer("/message/header/numRequiredSignatures")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let readonly_signed = transaction
        .pointer("/message/header/numReadonlySignedAccounts")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let readonly_unsigned = transaction
        .pointer("/message/header/numReadonlyUnsignedAccounts")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let key_count = u64::try_from(keys.len()).unwrap_or(u64::MAX);
    let mut roles = Vec::new();
    for (index, key) in keys.iter().enumerate() {
        let ordinal = u64::try_from(index).unwrap_or(u64::MAX);
        let (value, signer, writable, source) = if let Some(value) = key.as_str() {
            let signer = ordinal < required;
            let writable = if signer {
                ordinal < required.saturating_sub(readonly_signed)
            } else {
                ordinal < key_count.saturating_sub(readonly_unsigned)
            };
            (value, signer, writable, Some("transaction"))
        } else {
            let Some(value) = key.get("pubkey").and_then(Value::as_str) else {
                issues.push(NormalizationIssue::UnknownAccountKeyShape);
                continue;
            };
            (
                value,
                key.get("signer").and_then(Value::as_bool).unwrap_or(false),
                key.get("writable")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                key.get("source").and_then(Value::as_str),
            )
        };
        if let Ok(account) = PublicKey::new(value) {
            roles.push(AccountRole {
                account,
                ordinal: ordinal.into(),
                signer,
                writable,
                source: source.and_then(|value| stable(value).ok()),
            });
        }
    }
    if keys.iter().all(Value::is_string) {
        for (writable, pointer) in [
            (true, "/loadedAddresses/writable"),
            (false, "/loadedAddresses/readonly"),
        ] {
            let Some(loaded) = meta.pointer(pointer).and_then(Value::as_array) else {
                continue;
            };
            for key in loaded.iter().filter_map(Value::as_str) {
                if let Ok(account) = PublicKey::new(key) {
                    roles.push(AccountRole {
                        account,
                        ordinal: u64::try_from(roles.len()).unwrap_or(u64::MAX).into(),
                        signer: false,
                        writable,
                        source: stable("lookup_table").ok(),
                    });
                }
            }
        }
    }
    roles
}

fn parse_native_effects(meta: &Value, accounts: &[AccountRole]) -> Vec<AccountEffect> {
    let pre = meta
        .get("preBalances")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let post = meta
        .get("postBalances")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    accounts
        .iter()
        .enumerate()
        .filter_map(|(index, role)| {
            let pre = pre.get(index)?.as_u64()?;
            let post = post.get(index)?.as_u64()?;
            (pre != post).then(|| AccountEffect {
                account: role.account.clone(),
                account_index: u64::try_from(index).unwrap_or(u64::MAX).into(),
                pre_atoms: pre.into(),
                post_atoms: post.into(),
                delta_atoms: AtomDelta::from_pre_post(pre, post),
            })
        })
        .collect()
}

#[derive(Clone)]
struct TokenSide {
    account_index: u64,
    mint: PublicKey,
    owner: Option<PublicKey>,
    decimals: u64,
    atoms: u64,
}

type TokenBalanceKey = (u64, PublicKey, Option<PublicKey>);
type TokenBalancePair = (Option<TokenSide>, Option<TokenSide>);

fn parse_token_effects(meta: &Value, accounts: &[AccountRole]) -> Vec<TokenEffect> {
    let mut values: BTreeMap<TokenBalanceKey, TokenBalancePair> = BTreeMap::new();
    for (pre, field) in [(true, "preTokenBalances"), (false, "postTokenBalances")] {
        let Some(entries) = meta.get(field).and_then(Value::as_array) else {
            continue;
        };
        for entry in entries {
            let Some(side) = parse_token_side(entry) else {
                continue;
            };
            let key = (side.account_index, side.mint.clone(), side.owner.clone());
            let pair = values.entry(key).or_default();
            if pre {
                pair.0 = Some(side);
            } else {
                pair.1 = Some(side);
            }
        }
    }
    values
        .into_iter()
        .filter_map(|((account_index, mint, owner), (pre, post))| {
            let pre_atoms = pre.as_ref().map_or(0, |side| side.atoms);
            let post_atoms = post.as_ref().map_or(0, |side| side.atoms);
            if pre_atoms == post_atoms {
                return None;
            }
            let decimals = post
                .as_ref()
                .or(pre.as_ref())
                .map_or(0, |side| side.decimals);
            Some(TokenEffect {
                account_index: account_index.into(),
                account: accounts
                    .get(usize::try_from(account_index).ok()?)
                    .map(|role| role.account.clone()),
                owner,
                mint,
                decimals: decimals.into(),
                pre_atoms: pre_atoms.into(),
                post_atoms: post_atoms.into(),
                delta_atoms: AtomDelta::from_pre_post(pre_atoms, post_atoms),
            })
        })
        .collect()
}

fn parse_token_side(entry: &Value) -> Option<TokenSide> {
    Some(TokenSide {
        account_index: entry.get("accountIndex")?.as_u64()?,
        mint: PublicKey::new(entry.get("mint")?.as_str()?).ok()?,
        owner: entry
            .get("owner")
            .and_then(Value::as_str)
            .and_then(|value| PublicKey::new(value).ok()),
        decimals: entry.pointer("/uiTokenAmount/decimals")?.as_u64()?,
        atoms: entry
            .pointer("/uiTokenAmount/amount")?
            .as_str()?
            .parse()
            .ok()?,
    })
}

type InstructionParse = (
    Vec<InstructionFact>,
    Vec<ProgramOccurrence>,
    Vec<TransferFact>,
);

#[allow(clippy::too_many_arguments)]
fn parse_instructions(
    transaction: &Value,
    meta: &Value,
    accounts: &[AccountRole],
    token_effects: &[TokenEffect],
    locator: &TransactionLocator,
    transaction_fact_id: &StableString,
    succeeded: bool,
    issues: &mut Vec<NormalizationIssue>,
) -> Result<InstructionParse, NormalizationError> {
    let mut facts = Vec::new();
    let mut program_paths: BTreeMap<PublicKey, Vec<Vec<WireU64>>> = BTreeMap::new();
    let mut transfers = Vec::new();
    let token_mints: BTreeMap<PublicKey, PublicKey> = token_effects
        .iter()
        .filter_map(|effect| {
            effect
                .account
                .as_ref()
                .map(|account| (account.clone(), effect.mint.clone()))
        })
        .collect();
    if let Some(outer) = transaction
        .pointer("/message/instructions")
        .and_then(Value::as_array)
    {
        for (outer_index, instruction) in outer.iter().enumerate() {
            parse_one_instruction(
                instruction,
                outer_index,
                None,
                accounts,
                &token_mints,
                locator,
                transaction_fact_id,
                succeeded,
                &mut facts,
                &mut program_paths,
                &mut transfers,
            )?;
        }
    }
    if let Some(groups) = meta.get("innerInstructions").and_then(Value::as_array) {
        for group in groups {
            let Some(outer_index) = group.get("index").and_then(Value::as_u64) else {
                continue;
            };
            let Some(inner) = group.get("instructions").and_then(Value::as_array) else {
                continue;
            };
            for (inner_index, instruction) in inner.iter().enumerate() {
                parse_one_instruction(
                    instruction,
                    usize::try_from(outer_index).unwrap_or(usize::MAX),
                    Some(inner_index),
                    accounts,
                    &token_mints,
                    locator,
                    transaction_fact_id,
                    succeeded,
                    &mut facts,
                    &mut program_paths,
                    &mut transfers,
                )?;
            }
        }
    }
    if facts.iter().any(|fact| fact.parsed_type.is_none()) {
        issues.push(NormalizationIssue::UnsupportedInstruction);
    }
    let programs = program_paths
        .into_iter()
        .map(|(program_id, instruction_paths)| ProgramOccurrence {
            venue: venue(&program_id),
            program_id,
            instruction_paths,
        })
        .collect();
    Ok((facts, programs, transfers))
}

fn instruction_accounts(
    instruction: &Value,
    transaction_accounts: &[AccountRole],
) -> Vec<InstructionAccount> {
    let Some(accounts) = instruction.get("accounts").and_then(Value::as_array) else {
        return Vec::new();
    };
    accounts
        .iter()
        .enumerate()
        .filter_map(|(ordinal, account)| {
            let role = if let Some(index) = account.as_u64() {
                transaction_accounts.get(usize::try_from(index).ok()?)
            } else if let Some(public_key) = account.as_str() {
                transaction_accounts
                    .iter()
                    .find(|role| role.account.as_str() == public_key)
            } else {
                None
            }?;
            Some(InstructionAccount {
                account: role.account.clone(),
                ordinal: u64::try_from(ordinal).unwrap_or(u64::MAX).into(),
                signer: role.signer,
                writable: role.writable,
                role: None,
            })
        })
        .collect()
}

// Parsing one instruction is intentionally atomic: path, program, success, and transfer evidence
// must remain derived from the same JSON object.
#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn parse_one_instruction(
    instruction: &Value,
    outer_index: usize,
    inner_index: Option<usize>,
    accounts: &[AccountRole],
    token_mints: &BTreeMap<PublicKey, PublicKey>,
    locator: &TransactionLocator,
    transaction_fact_id: &StableString,
    succeeded: bool,
    facts: &mut Vec<InstructionFact>,
    program_paths: &mut BTreeMap<PublicKey, Vec<Vec<WireU64>>>,
    transfers: &mut Vec<TransferFact>,
) -> Result<(), NormalizationError> {
    let program_id = instruction
        .get("programId")
        .and_then(Value::as_str)
        .and_then(|value| PublicKey::new(value).ok())
        .or_else(|| {
            instruction
                .get("programIdIndex")
                .and_then(Value::as_u64)
                .and_then(|index| accounts.get(usize::try_from(index).ok()?))
                .map(|role| role.account.clone())
        });
    let parsed_type = instruction
        .pointer("/parsed/type")
        .and_then(Value::as_str)
        .map(stable)
        .transpose()?;
    let raw_data_base58 = instruction
        .get("data")
        .and_then(Value::as_str)
        .map(stable)
        .transpose()?;
    let mut path = vec![u64::try_from(outer_index).unwrap_or(u64::MAX).into()];
    if let Some(inner_index) = inner_index {
        path.push(u64::try_from(inner_index).unwrap_or(u64::MAX).into());
    }
    if let Some(program_id) = &program_id {
        program_paths
            .entry(program_id.clone())
            .or_default()
            .push(path);
    }
    facts.push(InstructionFact {
        instruction_id: stable(format!(
            "{}:instruction:{outer_index}:{}",
            transaction_fact_id,
            inner_index.map_or_else(|| "outer".to_owned(), |value| value.to_string())
        ))?,
        transaction_fact_id: transaction_fact_id.clone(),
        outer_index: u64::try_from(outer_index).unwrap_or(u64::MAX).into(),
        inner_index: inner_index.map(|index| u64::try_from(index).unwrap_or(u64::MAX).into()),
        program_id: program_id.clone(),
        raw_data_base58,
        parsed_type: parsed_type.clone(),
        accounts: instruction_accounts(instruction, accounts),
        execution_succeeded: succeeded,
    });
    if !succeeded || parsed_type.as_ref().map(StableString::as_str) != Some("transfer") {
        return Ok(());
    }
    let Some(info) = instruction.pointer("/parsed/info") else {
        return Ok(());
    };
    let Some(from) = info
        .get("source")
        .and_then(Value::as_str)
        .and_then(|value| PublicKey::new(value).ok())
    else {
        return Ok(());
    };
    let Some(to) = info
        .get("destination")
        .and_then(Value::as_str)
        .and_then(|value| PublicKey::new(value).ok())
    else {
        return Ok(());
    };
    let (kind, atoms, asset_id, authority) =
        if let Some(lamports) = info.get("lamports").and_then(Value::as_u64) {
            (
                TransferKind::NativeSystemInstruction,
                lamports,
                stable("solana.native:SOL")?,
                info.get("source")
                    .and_then(Value::as_str)
                    .and_then(|value| PublicKey::new(value).ok()),
            )
        } else {
            let Some(atoms) = info
                .get("amount")
                .and_then(value_as_u64)
                .or_else(|| info.pointer("/tokenAmount/amount").and_then(value_as_u64))
            else {
                return Ok(());
            };
            let mint = info
                .get("mint")
                .and_then(Value::as_str)
                .and_then(|value| PublicKey::new(value).ok())
                .or_else(|| token_mints.get(&from).cloned())
                .or_else(|| token_mints.get(&to).cloned());
            let Some(mint) = mint else {
                return Ok(());
            };
            (
                TransferKind::ParsedTokenInstruction,
                atoms,
                stable(format!("solana.mint:{mint}"))?,
                info.get("authority")
                    .and_then(Value::as_str)
                    .and_then(|value| PublicKey::new(value).ok()),
            )
        };
    let order = u64::try_from(transfers.len()).unwrap_or(u64::MAX);
    let Some(program_id) = program_id else {
        return Ok(());
    };
    let transfer_venue = venue(&program_id);
    transfers.push(TransferFact {
        flow_id: stable(format!(
            "{}:transfer:{outer_index}:{}",
            transaction_fact_id,
            inner_index.map_or_else(|| "outer".to_owned(), |value| value.to_string())
        ))?,
        transaction_fact_id: transaction_fact_id.clone(),
        transaction: locator.clone(),
        outer_index: Some(u64::try_from(outer_index).unwrap_or(u64::MAX).into()),
        inner_index: inner_index.map(|index| u64::try_from(index).unwrap_or(u64::MAX).into()),
        order: order.into(),
        from_account: from,
        to_account: to,
        authority,
        asset_id,
        atoms: atoms.into(),
        venue: transfer_venue,
        pool: None,
        program_id,
        kind,
    });
    Ok(())
}

fn parse_enhanced_projection(
    entry: &Value,
    ordinal: usize,
    observation_id: &ObservationId,
    context: &AcquisitionResponseContext,
) -> Result<Option<EnhancedProjection>, NormalizationError> {
    let Some(signature) = entry.get("signature").and_then(Value::as_str) else {
        return Ok(None);
    };
    let slot = entry.get("slot").and_then(Value::as_u64).map(WireU64::new);
    let locator = TransactionLocator {
        signature: stable(signature)?,
        slot: slot.unwrap_or_default(),
        transaction_index: None,
    };
    let mut transfers = Vec::new();
    if let Some(native) = entry.get("nativeTransfers").and_then(Value::as_array) {
        for transfer in native {
            let (Some(from), Some(to), Some(amount)) = (
                public_key_field(transfer, "fromUserAccount"),
                public_key_field(transfer, "toUserAccount"),
                transfer.get("amount").and_then(value_as_u64),
            ) else {
                continue;
            };
            transfers.push(enhanced_transfer(
                signature,
                &locator,
                from,
                to,
                stable("solana.native:SOL")?,
                amount,
                transfers.len(),
            )?);
        }
    }
    if let Some(tokens) = entry.get("tokenTransfers").and_then(Value::as_array) {
        for transfer in tokens {
            let (Some(from), Some(to), Some(mint), Some(amount)) = (
                public_key_field(transfer, "fromUserAccount"),
                public_key_field(transfer, "toUserAccount"),
                public_key_field(transfer, "mint"),
                transfer
                    .pointer("/rawTokenAmount/tokenAmount")
                    .and_then(value_as_u64)
                    .or_else(|| transfer.get("tokenAmount").and_then(value_as_u64)),
            ) else {
                continue;
            };
            transfers.push(enhanced_transfer(
                signature,
                &locator,
                from,
                to,
                stable(format!("solana.mint:{mint}"))?,
                amount,
                transfers.len(),
            )?);
        }
    }
    Ok(Some(EnhancedProjection {
        projection_id: stable(format!(
            "helius.enhanced:{signature}:{}:{ordinal}",
            context.available_at
        ))?,
        observation_id: observation_id.clone(),
        signature: stable(signature)?,
        slot,
        provider_type: entry
            .get("type")
            .and_then(Value::as_str)
            .map(stable)
            .transpose()?,
        provider_source: entry
            .get("source")
            .and_then(Value::as_str)
            .map(stable)
            .transpose()?,
        transfers,
        claims_swap: entry
            .pointer("/events/swap")
            .is_some_and(|value| !value.is_null()),
        requires_raw_reconciliation: true,
    }))
}

fn enhanced_transfer(
    signature: &str,
    locator: &TransactionLocator,
    from: PublicKey,
    to: PublicKey,
    asset_id: StableString,
    atoms: u64,
    ordinal: usize,
) -> Result<EnhancedTransferProjection, NormalizationError> {
    Ok(EnhancedTransferProjection {
        projection_transfer_id: stable(format!("helius.enhanced.transfer:{signature}:{ordinal}"))?,
        transaction: locator.clone(),
        order: u64::try_from(ordinal).unwrap_or(u64::MAX).into(),
        from_account: from,
        to_account: to,
        asset_id,
        atoms: atoms.into(),
    })
}

fn public_key_field(value: &Value, field: &str) -> Option<PublicKey> {
    value
        .get(field)
        .and_then(Value::as_str)
        .and_then(|value| PublicKey::new(value).ok())
}

fn value_as_u64(value: &Value) -> Option<u64> {
    value
        .as_u64()
        .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
}

fn venue(program: &PublicKey) -> Venue {
    match program.as_str() {
        PUMP_PROGRAM => Venue::PumpBondingCurve,
        PUMPSWAP_PROGRAM => Venue::PumpSwap,
        SYSTEM_PROGRAM => Venue::SystemProgram,
        TOKEN_PROGRAM => Venue::SplToken,
        TOKEN_2022_PROGRAM => Venue::SplToken2022,
        _ => Venue::Other(program.clone()),
    }
}

/// Admit a versioned protocol-decoder swap only when raw transaction evidence proves the same
/// successful transaction, signer, program path, and observation.
///
/// # Errors
///
/// Rejects any mismatch instead of degrading it to an inferred swap.
pub fn admit_decoded_swap(
    input: DecodedSwapInput,
    raw: &RawTransactionFact,
) -> Result<SwapFact, NormalizationError> {
    let path_matches = raw.programs.iter().any(|program| {
        program.program_id == input.program_id
            && program
                .instruction_paths
                .iter()
                .any(|path| path == &input.instruction_path)
    });
    let signer_matches = raw
        .account_roles
        .iter()
        .any(|role| role.signer && role.account == input.trader_wallet);
    if !raw.succeeded
        || raw.observation_id != input.observation_id
        || raw.transaction != input.transaction
        || !path_matches
        || !signer_matches
        || input.input_atoms.get() == 0
        || input.output_atoms.get() == 0
    {
        return Err(NormalizationError::DecoderEvidenceMismatch);
    }
    Ok(SwapFact {
        swap_id: stable(format!("{}:{}", input.decode_id, raw.fact_id))?,
        transaction_fact_id: raw.fact_id.clone(),
        decoder_version: input.decoder_version,
        observation_id: input.observation_id,
        transaction: input.transaction,
        instruction_path: input.instruction_path,
        event_ordinal: input.event_ordinal,
        trader_wallet: input.trader_wallet,
        venue: venue(&input.program_id),
        program_id: input.program_id,
        pool: input.pool,
        input_asset_id: input.input_asset_id,
        input_atoms: input.input_atoms,
        output_asset_id: input.output_asset_id,
        output_atoms: input.output_atoms,
        available_at: input.available_at,
    })
}

/// Convert an explicitly versioned funding hypothesis input into a separate inferred record.
///
/// # Errors
///
/// Rejects a hypothesis whose cited direct transfer does not fund the candidate recipient.
pub fn propose_funding_hypothesis(
    input: FundingHypothesisInput,
    transfer: &TransferFact,
) -> Result<FundingHypothesis, NormalizationError> {
    if input.transfer_flow_id != transfer.flow_id
        || input.candidate_recipient != transfer.to_account
        || input.evidence_observation_ids.is_empty()
    {
        return Err(NormalizationError::FundingEvidenceMismatch);
    }
    Ok(FundingHypothesis {
        hypothesis_id: input.hypothesis_id,
        transfer_flow_id: input.transfer_flow_id,
        candidate_funder: transfer.from_account.clone(),
        candidate_recipient: input.candidate_recipient,
        method: input.method,
        inference_version: input.inference_version,
        evidence_observation_ids: input.evidence_observation_ids,
        available_at: input.available_at,
        establishes_common_ownership: false,
    })
}

fn stable(value: impl Into<String>) -> Result<StableString, NormalizationError> {
    StableString::new(value).map_err(|_| NormalizationError::Identifier)
}

/// Aggregate exact token balance effects for one supplied mint-relative participant.
///
/// This describes observed in/out atoms; it intentionally does not label them buys or sells.
///
/// # Errors
///
/// Returns an error if exact sums exceed the current unsigned wire domain.
pub fn summarize_mint_relative(
    cohort_input_id: StableString,
    mint: &PublicKey,
    wallet: &PublicKey,
    facts: &[RawTransactionFact],
    available_at: UtcTimestamp,
) -> Result<Option<MintRelativeWalletFlow>, NormalizationError> {
    let mut gross_in = 0_u64;
    let mut gross_out = 0_u64;
    let mut slots = Vec::new();
    let mut fact_ids = Vec::new();
    let mut venues = BTreeSet::new();
    for fact in facts {
        let mut matched = false;
        for effect in &fact.token_effects {
            if effect.mint != *mint || effect.owner.as_ref() != Some(wallet) {
                continue;
            }
            let pre = effect.pre_atoms.get();
            let post = effect.post_atoms.get();
            if post > pre {
                gross_in = gross_in
                    .checked_add(post - pre)
                    .ok_or(NormalizationError::AtomOverflow)?;
            } else {
                gross_out = gross_out
                    .checked_add(pre - post)
                    .ok_or(NormalizationError::AtomOverflow)?;
            }
            matched = true;
        }
        if matched {
            slots.push(fact.transaction.slot);
            fact_ids.push(fact.fact_id.clone());
            venues.extend(fact.programs.iter().map(|program| program.venue.clone()));
        }
    }
    let (Some(first), Some(last)) = (slots.iter().min(), slots.iter().max()) else {
        return Ok(None);
    };
    Ok(Some(MintRelativeWalletFlow {
        flow_summary_id: stable(format!(
            "mint-wallet-flow:{mint}:{wallet}:{}",
            cohort_input_id.as_str()
        ))?,
        mint: mint.clone(),
        wallet: wallet.clone(),
        cohort_input_id,
        evidence_fact_ids: fact_ids,
        gross_in_atoms: gross_in.into(),
        gross_out_atoms: gross_out.into(),
        first_observed_slot: *first,
        last_observed_slot: *last,
        transaction_count: u64::try_from(slots.len()).unwrap_or(u64::MAX).into(),
        venues: venues.into_iter().collect(),
        available_at,
    }))
}

/// Classify an append-only re-observation of one transaction.
///
/// # Errors
///
/// Rejects facts for different signatures or an invalid correction identifier.
pub fn reconcile_transaction_facts(
    previous: &RawTransactionFact,
    current: &RawTransactionFact,
    available_at: UtcTimestamp,
) -> Result<ChainCorrection, NormalizationError> {
    if previous.transaction.signature != current.transaction.signature {
        return Err(NormalizationError::Identifier);
    }
    let previous_noncanonical = matches!(previous.canonicality, Canonicality::NonCanonical);
    let current_noncanonical = matches!(current.canonicality, Canonicality::NonCanonical);
    let kind = if !previous_noncanonical && current_noncanonical {
        ChainCorrectionKind::TransactionBecameUnavailable
    } else if previous_noncanonical && !current_noncanonical {
        ChainCorrectionKind::Reappeared
    } else if previous.transaction.slot != current.transaction.slot {
        ChainCorrectionKind::SlotConflict
    } else if current.commitment > previous.commitment {
        ChainCorrectionKind::FinalityAdvanced
    } else if current.commitment < previous.commitment {
        ChainCorrectionKind::FinalityRegressed
    } else {
        ChainCorrectionKind::NoSemanticChange
    };
    Ok(ChainCorrection {
        correction_id: stable(format!(
            "chain-correction:{}:{}:{}",
            previous.transaction.signature, previous.observation_id, current.observation_id
        ))?,
        signature: previous.transaction.signature.clone(),
        previous_observation_id: previous.observation_id.clone(),
        current_observation_id: current.observation_id.clone(),
        kind,
        available_at,
    })
}
