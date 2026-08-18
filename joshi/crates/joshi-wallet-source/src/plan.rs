use std::collections::BTreeSet;

use joshi_domain::{StableString, WireU64};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::{ActiveLease, Commitment, PublicKey};

/// A hard local budget. Provider billing remains independently reconciled.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReadBudget {
    pub max_requests: WireU64,
    pub max_pages: WireU64,
    pub max_response_bytes: WireU64,
    pub max_provider_credits: WireU64,
    pub max_public_keys: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BudgetUse {
    pub requests: WireU64,
    pub pages: WireU64,
    pub response_bytes: WireU64,
    pub provider_credits: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BudgetLedger {
    limit: ReadBudget,
    used: BudgetUse,
}

impl BudgetLedger {
    #[must_use]
    pub fn new(limit: ReadBudget) -> Self {
        Self {
            limit,
            used: BudgetUse {
                requests: 0.into(),
                pages: 0.into(),
                response_bytes: 0.into(),
                provider_credits: 0.into(),
            },
        }
    }

    /// Admit measured use without ever treating an estimate as permission to exceed a cap.
    ///
    /// # Errors
    ///
    /// Returns `Exceeded` if any independent dimension would cross its hard ceiling.
    pub fn admit(&mut self, use_: &BudgetUse) -> Result<(), PlanError> {
        let candidate = BudgetUse {
            requests: checked_add(self.used.requests, use_.requests)?,
            pages: checked_add(self.used.pages, use_.pages)?,
            response_bytes: checked_add(self.used.response_bytes, use_.response_bytes)?,
            provider_credits: checked_add(self.used.provider_credits, use_.provider_credits)?,
        };
        if candidate.requests > self.limit.max_requests
            || candidate.pages > self.limit.max_pages
            || candidate.response_bytes > self.limit.max_response_bytes
            || candidate.provider_credits > self.limit.max_provider_credits
        {
            return Err(PlanError::BudgetExceeded);
        }
        self.used = candidate;
        Ok(())
    }

    #[must_use]
    pub fn used(&self) -> &BudgetUse {
        &self.used
    }
}

fn checked_add(left: WireU64, right: WireU64) -> Result<WireU64, PlanError> {
    left.get()
        .checked_add(right.get())
        .map(WireU64::new)
        .ok_or(PlanError::BudgetExceeded)
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AcquisitionSurface {
    /// Helius extension returning full transaction notifications for selected account keys.
    HeliusTransactionSubscribe,
    /// Modern Helius-exclusive raw transaction history RPC.
    HeliusGetTransactionsForAddress,
    /// Standard Solana signature pagination.
    SolanaGetSignaturesForAddress,
    /// Standard Solana full transaction lookup.
    SolanaGetTransaction,
    /// Deprecated provider projection used only as a reconciliation hint.
    HeliusLegacyEnhancedCrossCheck,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlannedRead {
    pub request_id: StableString,
    pub lease_ids: Vec<StableString>,
    pub scope_ids: Vec<StableString>,
    pub surface: AcquisitionSurface,
    pub public_keys: Vec<PublicKey>,
    pub mint_filter: Option<PublicKey>,
    pub commitment: Commitment,
    pub page_limit: Option<WireU64>,
    pub cursor: Option<StableString>,
    pub token_accounts_balance_changed: bool,
    pub transaction_details_full: bool,
    pub estimated_use: BudgetUse,
}

/// Credential-free logical request template. The source transport adds authentication privately.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "transport", rename_all = "snake_case")]
pub enum ReadRequestTemplate {
    JsonRpc {
        method: StableString,
        params: Value,
    },
    LegacyEnhancedHttpGet {
        logical_path: StableString,
        query: Vec<(StableString, StableString)>,
    },
}

impl PlannedRead {
    /// Build an allowlisted read-only logical request without an endpoint or credential.
    ///
    /// # Errors
    ///
    /// Rejects a surface whose required public key or transaction-signature cursor is absent.
    pub fn request_template(&self) -> Result<ReadRequestTemplate, PlanError> {
        let commitment = match self.commitment {
            Commitment::Processed => "processed",
            Commitment::Confirmed => "confirmed",
            Commitment::Finalized => "finalized",
        };
        match self.surface {
            AcquisitionSurface::HeliusTransactionSubscribe => Ok(ReadRequestTemplate::JsonRpc {
                method: stable("transactionSubscribe")?,
                params: json!([
                    {"accountInclude": self.public_keys},
                    {
                        "commitment": commitment,
                        "encoding": "jsonParsed",
                        "transactionDetails": "full",
                        "showRewards": false,
                        "maxSupportedTransactionVersion": 0
                    }
                ]),
            }),
            AcquisitionSurface::HeliusGetTransactionsForAddress => {
                let address = only_public_key(&self.public_keys)?;
                let mut options = json!({
                    "transactionDetails": "full",
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "sortOrder": "asc",
                    "limit": self.page_limit.unwrap_or(WireU64::new(100)).get(),
                    "filters": {"tokenAccounts": "balanceChanged"}
                });
                if let Some(cursor) = &self.cursor {
                    options["paginationToken"] = Value::String(cursor.as_str().to_owned());
                }
                Ok(ReadRequestTemplate::JsonRpc {
                    method: stable("getTransactionsForAddress")?,
                    params: json!([address, options]),
                })
            }
            AcquisitionSurface::SolanaGetSignaturesForAddress => {
                let address = only_public_key(&self.public_keys)?;
                Ok(ReadRequestTemplate::JsonRpc {
                    method: stable("getSignaturesForAddress")?,
                    params: json!([
                        address,
                        {
                            "commitment": commitment,
                            "limit": self.page_limit.unwrap_or(WireU64::new(100)).get(),
                            "before": self.cursor.as_ref().map(StableString::as_str)
                        }
                    ]),
                })
            }
            AcquisitionSurface::SolanaGetTransaction => {
                let signature = self
                    .cursor
                    .as_ref()
                    .ok_or(PlanError::MissingSignatureCursor)?;
                Ok(ReadRequestTemplate::JsonRpc {
                    method: stable("getTransaction")?,
                    params: json!([
                        signature.as_str(),
                        {
                            "commitment": commitment,
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0
                        }
                    ]),
                })
            }
            AcquisitionSurface::HeliusLegacyEnhancedCrossCheck => {
                let address = only_public_key(&self.public_keys)?;
                let mut query = vec![
                    (
                        stable("limit")?,
                        stable(self.page_limit.unwrap_or(WireU64::new(100)).to_string())?,
                    ),
                    (stable("sort-order")?, stable("asc")?),
                    (stable("token-accounts")?, stable("balanceChanged")?),
                ];
                if let Some(cursor) = &self.cursor {
                    query.push((stable("after-signature")?, cursor.clone()));
                }
                Ok(ReadRequestTemplate::LegacyEnhancedHttpGet {
                    logical_path: stable(format!(
                        "/v0/addresses/{}/transactions",
                        address.as_str()
                    ))?,
                    query,
                })
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AcquisitionPlan {
    pub contract_version: StableString,
    pub plan_occurrence_id: StableString,
    pub reads: Vec<PlannedRead>,
    pub omitted_duplicate_public_keys: WireU64,
    pub legacy_enhanced_is_authoritative: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanConfig {
    pub max_live_keys_per_subscription: u64,
    pub backfill_page_limit: u64,
    pub include_legacy_enhanced_cross_check: bool,
}

impl Default for PlanConfig {
    fn default() -> Self {
        Self {
            max_live_keys_per_subscription: 500,
            backfill_page_limit: 100,
            include_legacy_enhanced_cross_check: false,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum PlanError {
    #[error("acquisition budget exceeded")]
    BudgetExceeded,
    #[error("live subscription key ceiling must be between 1 and 50000")]
    InvalidLiveKeyCeiling,
    #[error("backfill page limit must be between 1 and 1000")]
    InvalidPageLimit,
    #[error("planner has no active leases")]
    NoActiveLeases,
    #[error("planner identifier violates stable wire rules")]
    InvalidIdentifier,
    #[error("read surface requires exactly one public key")]
    MissingSinglePublicKey,
    #[error("getTransaction requires a signature cursor")]
    MissingSignatureCursor,
}

pub struct AcquisitionPlanner {
    config: PlanConfig,
}

impl AcquisitionPlanner {
    /// Construct a local planner beneath provider-documented ceilings.
    ///
    /// # Errors
    ///
    /// Rejects zero or provider-incompatible configuration.
    pub fn new(config: PlanConfig) -> Result<Self, PlanError> {
        if config.max_live_keys_per_subscription == 0
            || config.max_live_keys_per_subscription > 50_000
        {
            return Err(PlanError::InvalidLiveKeyCeiling);
        }
        if config.backfill_page_limit == 0 || config.backfill_page_limit > 1_000 {
            return Err(PlanError::InvalidPageLimit);
        }
        Ok(Self { config })
    }

    /// Plan one live subscription plus one independently budgeted raw backfill per selected key.
    ///
    /// Legacy enhanced parsing, when enabled, is a non-authoritative cross-check only.
    ///
    /// # Errors
    ///
    /// Rejects an empty active set, identifier failure, or an estimated budget breach.
    #[allow(clippy::too_many_lines)]
    pub fn plan(
        &self,
        plan_occurrence_id: &StableString,
        leases: &[ActiveLease],
    ) -> Result<AcquisitionPlan, PlanError> {
        if leases.is_empty() {
            return Err(PlanError::NoActiveLeases);
        }
        let mut seen = BTreeSet::new();
        let mut keys = Vec::new();
        let mut duplicate_count = 0_u64;
        for lease in leases {
            for key in lease.target.public_keys() {
                if seen.insert(key.clone()) {
                    keys.push(key);
                } else {
                    duplicate_count = duplicate_count.saturating_add(1);
                }
            }
        }
        let mut reads = Vec::new();
        for (chunk_index, chunk) in keys
            .chunks(
                usize::try_from(self.config.max_live_keys_per_subscription).unwrap_or(usize::MAX),
            )
            .enumerate()
        {
            let relevant = relevant_leases(leases, chunk);
            reads.push(PlannedRead {
                request_id: stable(format!(
                    "{}:wallet-live-{chunk_index}",
                    plan_occurrence_id.as_str()
                ))?,
                lease_ids: relevant
                    .iter()
                    .map(|lease| lease.lease_id.clone())
                    .collect(),
                scope_ids: relevant
                    .iter()
                    .map(|lease| lease.scope_id.clone())
                    .collect(),
                surface: AcquisitionSurface::HeliusTransactionSubscribe,
                public_keys: chunk.to_vec(),
                mint_filter: None,
                commitment: Commitment::Processed,
                page_limit: None,
                cursor: None,
                token_accounts_balance_changed: false,
                transaction_details_full: true,
                estimated_use: one_request(1),
            });
        }
        for (index, key) in keys.iter().enumerate() {
            let relevant = relevant_leases(leases, std::slice::from_ref(key));
            reads.push(PlannedRead {
                request_id: stable(format!(
                    "{}:wallet-backfill-{index}",
                    plan_occurrence_id.as_str()
                ))?,
                lease_ids: relevant
                    .iter()
                    .map(|lease| lease.lease_id.clone())
                    .collect(),
                scope_ids: relevant
                    .iter()
                    .map(|lease| lease.scope_id.clone())
                    .collect(),
                surface: AcquisitionSurface::HeliusGetTransactionsForAddress,
                public_keys: vec![key.clone()],
                mint_filter: common_mint(&relevant),
                commitment: Commitment::Finalized,
                page_limit: Some(self.config.backfill_page_limit.into()),
                cursor: None,
                token_accounts_balance_changed: true,
                transaction_details_full: true,
                // Full responses cost ten credits per started block of one hundred returned rows.
                estimated_use: one_request(history_credits(self.config.backfill_page_limit)),
            });
            if self.config.include_legacy_enhanced_cross_check {
                reads.push(PlannedRead {
                    request_id: stable(format!(
                        "{}:wallet-legacy-cross-check-{index}",
                        plan_occurrence_id.as_str()
                    ))?,
                    lease_ids: relevant
                        .iter()
                        .map(|lease| lease.lease_id.clone())
                        .collect(),
                    scope_ids: relevant
                        .iter()
                        .map(|lease| lease.scope_id.clone())
                        .collect(),
                    surface: AcquisitionSurface::HeliusLegacyEnhancedCrossCheck,
                    public_keys: vec![key.clone()],
                    mint_filter: common_mint(&relevant),
                    commitment: Commitment::Finalized,
                    page_limit: Some(self.config.backfill_page_limit.min(100).into()),
                    cursor: None,
                    token_accounts_balance_changed: true,
                    transaction_details_full: false,
                    // The deprecated Enhanced endpoint is intentionally priced conservatively.
                    estimated_use: one_request(100),
                });
            }
        }
        for lease in leases {
            let mut ledger = BudgetLedger::new(lease.budget.clone());
            for read in reads
                .iter()
                .filter(|read| read.lease_ids.contains(&lease.lease_id))
            {
                // Conservatively charge a shared subscription in full to every benefiting lease.
                ledger.admit(&read.estimated_use)?;
            }
        }
        Ok(AcquisitionPlan {
            contract_version: stable(crate::WALLET_SOURCE_CONTRACT_VERSION)?,
            plan_occurrence_id: plan_occurrence_id.clone(),
            reads,
            omitted_duplicate_public_keys: duplicate_count.into(),
            legacy_enhanced_is_authoritative: false,
        })
    }
}

fn relevant_leases<'a>(
    leases: &'a [ActiveLease],
    public_keys: &[PublicKey],
) -> Vec<&'a ActiveLease> {
    leases
        .iter()
        .filter(|lease| {
            lease
                .target
                .public_keys()
                .iter()
                .any(|key| public_keys.contains(key))
        })
        .collect()
}

fn common_mint(leases: &[&ActiveLease]) -> Option<PublicKey> {
    let mut mints = leases
        .iter()
        .filter_map(|lease| lease.target.mint().cloned());
    let first = mints.next()?;
    mints.all(|mint| mint == first).then_some(first)
}

fn one_request(credits: u64) -> BudgetUse {
    BudgetUse {
        requests: 1.into(),
        pages: 1.into(),
        response_bytes: 0.into(),
        provider_credits: credits.into(),
    }
}

fn history_credits(page_limit: u64) -> u64 {
    page_limit.div_ceil(100).saturating_mul(10)
}

fn stable(value: impl Into<String>) -> Result<StableString, PlanError> {
    StableString::new(value).map_err(|_| PlanError::InvalidIdentifier)
}

fn only_public_key(public_keys: &[PublicKey]) -> Result<&PublicKey, PlanError> {
    if let [public_key] = public_keys {
        Ok(public_key)
    } else {
        Err(PlanError::MissingSinglePublicKey)
    }
}
