use joshi_domain::{
    AssetId, CoverageId, OpenVariant, PoolId, StableString, UtcTimestamp, VenueId, WireStringError,
};
use joshi_wallet_topology::{
    AssetAmount, BundleId, CallerAccountFact, EvidenceClosure, FlowId, FlowMark, ProgramId,
    SameTransactionBundleFact, SwapFact, SwapId, TopologyFact, TopologyFactRef, TransactionFact,
    TransactionFactId, TransactionId, TransferFact,
};
use time::OffsetDateTime;

use crate::{Canonicality, Commitment, PublicKey, RawTransactionFact, Venue};

#[derive(Debug, thiserror::Error)]
pub enum TopologyAdapterError {
    #[error("wallet-source fact could not satisfy the topology wire contract")]
    Wire(#[from] WireStringError),
    #[error("transaction block time is outside the supported UTC range")]
    BlockTime,
}

/// Convert one immutable source transaction version into the final topology fact contract.
///
/// Every dependent fact binds the exact `transaction_fact_id`. Requested coverage references stay
/// unverified until the topology/core-store boundary proves them.
///
/// # Errors
///
/// Rejects any source identity or time that cannot map losslessly into the topology contract.
#[allow(clippy::too_many_lines)]
pub fn to_topology_facts(
    raw: &RawTransactionFact,
) -> Result<Vec<TopologyFact>, TopologyAdapterError> {
    let transaction_id =
        TransactionId::new(format!("solana.transaction:{}", raw.transaction.signature))?;
    let transaction_fact_id = TransactionFactId::new(raw.fact_id.as_str())?;
    let evidence = evidence(raw)?;
    let transaction = TransactionFact {
        transaction_fact_id: transaction_fact_id.clone(),
        transaction_id: transaction_id.clone(),
        version: raw.version,
        supersedes_transaction_fact_id: raw
            .supersedes_transaction_fact_id
            .as_ref()
            .map(|value| TransactionFactId::new(value.as_str()))
            .transpose()?,
        chain_id: StableString::new("solana:mainnet-beta")?,
        signature: raw.transaction.signature.clone(),
        slot: raw.transaction.slot,
        block_time: raw.block_time_seconds.map(block_time).transpose()?,
        finality: finality(raw.commitment)?,
        canonicality: canonicality(&raw.canonicality)?,
        available_at: raw.available_at,
        evidence: evidence.clone(),
    };
    let mut facts = vec![TopologyFact::Transaction(transaction)];
    let mut ordered_member_keys = Vec::new();
    for instruction in &raw.instructions {
        let path = instruction_path(instruction.outer_index.get(), instruction.inner_index)?;
        let program_id = instruction
            .program_id
            .as_ref()
            .map(program_id)
            .transpose()?;
        for account in &instruction.accounts {
            let association_id = StableString::new(format!(
                "caller:{}:{}:{}",
                raw.fact_id,
                path.as_str(),
                account.ordinal
            ))?;
            ordered_member_keys.push((
                instruction.outer_index.get(),
                inner_order(instruction.inner_index),
                0_u8,
                account.ordinal.get(),
                TopologyFactRef::CallerAccount(association_id.clone()),
            ));
            facts.push(TopologyFact::CallerAccount(CallerAccountFact {
                association_id,
                transaction_id: transaction_id.clone(),
                transaction_fact_id: transaction_fact_id.clone(),
                instruction_path: path.clone(),
                account_id: account.account.domain_account_id()?,
                account_ordinal: account.ordinal,
                role: OpenVariant::known(
                    account
                        .role
                        .as_ref()
                        .map_or("ordered_account", StableString::as_str),
                )?,
                program_id: program_id.clone(),
                is_signer: account.signer,
                is_writable: account.writable,
                available_at: raw.available_at,
                evidence: evidence.clone(),
            }));
        }
    }
    for transfer in &raw.executed_transfers {
        let flow_id = FlowId::new(transfer.flow_id.as_str())?;
        ordered_member_keys.push((
            transfer
                .outer_index
                .map_or(u64::MAX, joshi_domain::WireU64::get),
            inner_order(transfer.inner_index),
            1_u8,
            transfer.order.get(),
            TopologyFactRef::Transfer(flow_id.clone()),
        ));
        facts.push(TopologyFact::Transfer(TransferFact {
            flow_id,
            transaction_id: transaction_id.clone(),
            transaction_fact_id: transaction_fact_id.clone(),
            instruction_path: transfer_path(transfer.outer_index, transfer.inner_index)?,
            event_ordinal: transfer.order,
            from_account_id: transfer.from_account.domain_account_id()?,
            to_account_id: transfer.to_account.domain_account_id()?,
            program_id: program_id(&transfer.program_id)?,
            mark: FlowMark {
                asset_id: AssetId::new(transfer.asset_id.as_str())?,
                atoms: transfer.atoms,
                flow_kind: OpenVariant::known("transfer")?,
                venue_id: Some(venue_id(&transfer.venue)?),
                pool_id: transfer.pool.as_ref().map(pool_id).transpose()?,
            },
            available_at: raw.available_at,
            evidence: evidence.clone(),
        }));
    }
    for swap in &raw.decoded_swaps {
        let swap_id = SwapId::new(swap.swap_id.as_str())?;
        ordered_member_keys.push((
            swap.instruction_path
                .first()
                .map_or(u64::MAX, |value| value.get()),
            inner_order(swap.instruction_path.get(1).copied()),
            2_u8,
            swap.event_ordinal.get(),
            TopologyFactRef::Swap(swap_id.clone()),
        ));
        facts.push(TopologyFact::Swap(SwapFact {
            swap_id,
            transaction_id: transaction_id.clone(),
            transaction_fact_id: transaction_fact_id.clone(),
            instruction_path: path_values(&swap.instruction_path)?,
            event_ordinal: swap.event_ordinal,
            trader_wallet_id: Some(swap.trader_wallet.domain_account_id()?),
            caller_account_id: swap.trader_wallet.domain_account_id()?,
            program_id: program_id(&swap.program_id)?,
            venue_id: venue_id(&swap.venue)?,
            pool_id: swap.pool.as_ref().map(pool_id).transpose()?,
            input: AssetAmount {
                asset_id: AssetId::new(swap.input_asset_id.as_str())?,
                atoms: swap.input_atoms,
            },
            output: AssetAmount {
                asset_id: AssetId::new(swap.output_asset_id.as_str())?,
                atoms: swap.output_atoms,
            },
            fee_legs: Vec::new(),
            available_at: swap.available_at,
            evidence: evidence.clone(),
        }));
    }
    ordered_member_keys.sort_by(|left, right| {
        (left.0, left.1, left.2, left.3).cmp(&(right.0, right.1, right.2, right.3))
    });
    let ordered_members: Vec<TopologyFactRef> = ordered_member_keys
        .into_iter()
        .map(|(_, _, _, _, member)| member)
        .collect();
    if ordered_members.len() >= 2 {
        facts.push(TopologyFact::SameTransactionBundle(
            SameTransactionBundleFact {
                bundle_id: BundleId::new(raw.same_transaction_bundle.bundle_id.as_str())?,
                transaction_id,
                transaction_fact_id,
                ordered_members,
                available_at: raw.available_at,
                evidence,
            },
        ));
    }
    Ok(facts)
}

fn inner_order(inner: Option<joshi_domain::WireU64>) -> u64 {
    inner.map_or(0, |value| value.get().saturating_add(1))
}

fn evidence(raw: &RawTransactionFact) -> Result<EvidenceClosure, WireStringError> {
    let mut coverage_ids = raw
        .requested_coverage_ids
        .iter()
        .map(|value| CoverageId::new(value.as_str()))
        .collect::<Result<Vec<_>, _>>()?;
    coverage_ids.sort();
    coverage_ids.dedup();
    let mut source_event_ids = raw.source_event_ids.clone();
    source_event_ids.sort();
    source_event_ids.dedup();
    Ok(EvidenceClosure {
        observation_ids: vec![raw.observation_id.clone()],
        source_event_ids,
        coverage_ids,
    })
}

fn block_time(seconds: joshi_domain::WireU64) -> Result<UtcTimestamp, TopologyAdapterError> {
    let value = i64::try_from(seconds.get()).map_err(|_| TopologyAdapterError::BlockTime)?;
    let datetime =
        OffsetDateTime::from_unix_timestamp(value).map_err(|_| TopologyAdapterError::BlockTime)?;
    UtcTimestamp::new(datetime).map_err(|_| TopologyAdapterError::BlockTime)
}

fn finality(value: Commitment) -> Result<OpenVariant, WireStringError> {
    OpenVariant::known(match value {
        Commitment::Processed => "processed",
        Commitment::Confirmed => "confirmed",
        Commitment::Finalized => "finalized",
    })
}

fn canonicality(value: &Canonicality) -> Result<OpenVariant, WireStringError> {
    OpenVariant::known(match value {
        Canonicality::ObservedAtCommitment => "observed_at_commitment",
        Canonicality::Canonical => "canonical",
        Canonicality::NonCanonical => "noncanonical",
        Canonicality::Conflicted => "conflicted",
    })
}

fn instruction_path(
    outer: u64,
    inner: Option<joshi_domain::WireU64>,
) -> Result<StableString, WireStringError> {
    StableString::new(inner.map_or_else(
        || outer.to_string(),
        |inner| format!("{outer}/{}", inner.get()),
    ))
}

fn transfer_path(
    outer: Option<joshi_domain::WireU64>,
    inner: Option<joshi_domain::WireU64>,
) -> Result<StableString, WireStringError> {
    match outer {
        Some(outer) => instruction_path(outer.get(), inner),
        None => StableString::new("provider_projection_unlocated"),
    }
}

fn path_values(path: &[joshi_domain::WireU64]) -> Result<StableString, WireStringError> {
    StableString::new(
        path.iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join("/"),
    )
}

fn program_id(value: &PublicKey) -> Result<ProgramId, WireStringError> {
    ProgramId::new(format!("solana.program:{value}"))
}

fn pool_id(value: &PublicKey) -> Result<PoolId, WireStringError> {
    PoolId::new(format!("solana.pool:{value}"))
}

fn venue_id(value: &Venue) -> Result<VenueId, WireStringError> {
    VenueId::new(match value {
        Venue::PumpBondingCurve => "pump.bonding_curve".to_owned(),
        Venue::PumpSwap => "pump.swap".to_owned(),
        Venue::SystemProgram => "solana.system_program".to_owned(),
        Venue::SplToken => "solana.spl_token".to_owned(),
        Venue::SplToken2022 => "solana.spl_token_2022".to_owned(),
        Venue::Other(program) => format!("solana.program_venue:{program}"),
    })
}
