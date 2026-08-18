use crate::backfill::{BackfillPlanV1, BackfillResultV1};
use crate::model::{
    AUTHORITY_CEILING, ArtifactKind, ArtifactStatusV1, CatalogReceiptSummaryV1,
    CursorScopeStatusV1, GapStatusV1, OperationalHealthV1, QuarantineClass, SourceFamily,
    SourceGenerationStatusV1,
};
use crate::{OperationalError, Result};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

/// Operational health snapshot wire contract.
pub const HEALTH_CONTRACT: &str = "joshi.operational.health/v1";
/// Authenticated GET query wire contract.
pub const QUERY_CONTRACT: &str = "joshi.operational.status_query/v1";
/// Authenticated GET result wire contract.
pub const QUERY_RESULT_CONTRACT: &str = "joshi.operational.status_query_result/v1";
/// Maximum same-origin authenticated health/query response body.
pub const MAX_HEALTH_BYTES: usize = 4 * 1024 * 1024;
/// Maximum same-origin query request body.
pub const MAX_QUERY_BYTES: usize = 64 * 1024;
/// Maximum same-origin query result body.
pub const MAX_QUERY_RESULT_BYTES: usize = 4 * 1024 * 1024;
/// Maximum detailed durable rows per page.
pub const MAX_QUERY_PAGE_SIZE: u64 = 100;

/// Exact durable-detail target; it contains no free-form search or log query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum QueryTargetV1 {
    Health {},
    SourceGeneration {
        source_family: SourceFamily,
    },
    CursorScope {
        scope_id: StableString,
    },
    Gap {
        gap_id: StableString,
    },
    Quarantine {
        quarantine_id: StableString,
    },
    BackfillPlan {
        plan_id: StableString,
    },
    BackfillResult {
        result_id: StableString,
    },
    Artifact {
        artifact_kind: ArtifactKind,
        occurrence_id: StableString,
    },
    CatalogReceipt {
        batch_id: StableString,
    },
}

/// Strict bounded same-origin GET query.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationalStatusQueryV1 {
    pub contract: String,
    pub query_id: StableString,
    pub target: QueryTargetV1,
    pub page_size: WireU64,
    pub after: Option<StableString>,
}

impl OperationalStatusQueryV1 {
    /// Validates the fixed contract and bounded cursor pagination.
    ///
    /// # Errors
    ///
    /// Refuses zero/unbounded page sizes and unsupported contracts.
    pub fn validate(&self) -> Result<()> {
        if self.contract != QUERY_CONTRACT {
            return Err(OperationalError::Contract {
                expected: QUERY_CONTRACT,
                received: self.contract.clone(),
            });
        }
        if self.page_size.get() == 0 || self.page_size.get() > MAX_QUERY_PAGE_SIZE {
            return Err(OperationalError::BoundExceeded {
                field: "pageSize",
                maximum: MAX_QUERY_PAGE_SIZE,
            });
        }
        validate_target(&self.target)?;
        Ok(())
    }
}

/// One bounded durable detail returned by the status query seam.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum OperationalDetailV1 {
    Health {
        value: Box<OperationalHealthV1>,
    },
    SourceGeneration {
        value: SourceGenerationStatusV1,
    },
    CursorScope {
        value: CursorScopeStatusV1,
    },
    Gap {
        value: GapStatusV1,
    },
    Quarantine {
        quarantine_id: StableString,
        class: QuarantineClass,
        durable_record_id: StableString,
        content_digest: StableString,
        available_at: UtcTimestamp,
    },
    BackfillPlan {
        value: BackfillPlanV1,
    },
    BackfillResult {
        value: BackfillResultV1,
    },
    Artifact {
        value: ArtifactStatusV1,
    },
    CatalogReceipt {
        value: CatalogReceiptSummaryV1,
    },
}

/// Strict bounded result. The transport additionally enforces
/// [`MAX_QUERY_RESULT_BYTES`] before parsing.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperationalStatusQueryResultV1 {
    pub contract: String,
    pub query_id: StableString,
    pub target: QueryTargetV1,
    pub authority: String,
    pub generated_at: UtcTimestamp,
    pub catalog_through: Option<CommitSeq>,
    pub items: Vec<OperationalDetailV1>,
    pub next_cursor: Option<StableString>,
    pub complete: bool,
}

impl OperationalStatusQueryResultV1 {
    /// Validates authority, pagination, item bounds, and nested artifact contracts.
    ///
    /// # Errors
    ///
    /// Refuses oversized pages, contradictory completion, or invalid nested health/backfill data.
    pub fn validate(&self, requested_page_size: WireU64) -> Result<()> {
        if self.contract != QUERY_RESULT_CONTRACT {
            return Err(OperationalError::Contract {
                expected: QUERY_RESULT_CONTRACT,
                received: self.contract.clone(),
            });
        }
        if self.authority != AUTHORITY_CEILING {
            return Err(OperationalError::Invalid(
                "query result authority must be read_only_no_execution",
            ));
        }
        validate_target(&self.target)?;
        if requested_page_size.get() == 0 || requested_page_size.get() > MAX_QUERY_PAGE_SIZE {
            return Err(OperationalError::BoundExceeded {
                field: "pageSize",
                maximum: MAX_QUERY_PAGE_SIZE,
            });
        }
        let page_limit = requested_page_size.get();
        if u64::try_from(self.items.len()).unwrap_or(u64::MAX) > page_limit {
            return Err(OperationalError::BoundExceeded {
                field: "queryResult.items",
                maximum: page_limit,
            });
        }
        if self.complete != self.next_cursor.is_none() {
            return Err(OperationalError::Invalid(
                "complete result must omit next cursor and incomplete result must provide one",
            ));
        }
        for item in &self.items {
            match item {
                OperationalDetailV1::Health { value } => value.validate(HEALTH_CONTRACT)?,
                OperationalDetailV1::SourceGeneration { value } => value.validate()?,
                OperationalDetailV1::CursorScope { value } => value.validate()?,
                OperationalDetailV1::Gap { value } => value.validate()?,
                OperationalDetailV1::BackfillPlan { value } => value.validate()?,
                OperationalDetailV1::BackfillResult { value } => value.validate()?,
                OperationalDetailV1::Artifact { value } => value.validate()?,
                OperationalDetailV1::CatalogReceipt { value } => value.validate()?,
                OperationalDetailV1::Quarantine { content_digest, .. } => {
                    if !content_digest.as_str().starts_with("sha256:") {
                        return Err(OperationalError::Invalid(
                            "quarantine content digest must be SHA-256 tagged",
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    /// Validates that a result is bound to the exact authenticated query occurrence and target.
    ///
    /// # Errors
    ///
    /// Returns an error when the query or result is invalid, or their IDs/targets differ.
    pub fn validate_for_query(&self, query: &OperationalStatusQueryV1) -> Result<()> {
        query.validate()?;
        self.validate(query.page_size)?;
        if self.query_id != query.query_id || self.target != query.target {
            return Err(OperationalError::Invalid(
                "query result does not bind the requested query ID and target",
            ));
        }
        Ok(())
    }
}

/// Decodes a strict bounded health payload and validates semantic closure.
///
/// # Errors
///
/// Refuses bodies above 4 MiB, unknown/duplicate struct fields, invalid wire primitives, or
/// inconsistent health state.
pub fn decode_health_v1(bytes: &[u8]) -> Result<OperationalHealthV1> {
    let value: OperationalHealthV1 = decode_bounded(bytes, MAX_HEALTH_BYTES, "healthBody")?;
    value.validate(HEALTH_CONTRACT)?;
    Ok(value)
}

/// Decodes a strict bounded status query.
///
/// # Errors
///
/// Refuses bodies above 64 KiB, unknown/duplicate fields, or invalid pagination.
pub fn decode_query_v1(bytes: &[u8]) -> Result<OperationalStatusQueryV1> {
    let value: OperationalStatusQueryV1 = decode_bounded(bytes, MAX_QUERY_BYTES, "queryBody")?;
    value.validate()?;
    Ok(value)
}

/// Decodes and validates a bounded query result after the request's page size is known.
///
/// # Errors
///
/// Refuses bodies above 4 MiB, unknown/duplicate fields, invalid nested detail, or pagination
/// that exceeds the requested page size.
pub fn decode_query_result_v1(
    bytes: &[u8],
    requested_page_size: WireU64,
) -> Result<OperationalStatusQueryResultV1> {
    let value: OperationalStatusQueryResultV1 =
        decode_bounded(bytes, MAX_QUERY_RESULT_BYTES, "queryResultBody")?;
    value.validate(requested_page_size)?;
    Ok(value)
}

/// Decodes a query result and binds it to the exact query that produced it.
///
/// # Errors
///
/// Refuses an oversized or malformed result, invalid nested details, or a mismatched query ID or
/// target.
pub fn decode_query_result_for_query_v1(
    bytes: &[u8],
    query: &OperationalStatusQueryV1,
) -> Result<OperationalStatusQueryResultV1> {
    let value: OperationalStatusQueryResultV1 =
        decode_bounded(bytes, MAX_QUERY_RESULT_BYTES, "queryResultBody")?;
    value.validate_for_query(query)?;
    Ok(value)
}

fn validate_target(target: &QueryTargetV1) -> Result<()> {
    let identity = match target {
        QueryTargetV1::Health {} | QueryTargetV1::SourceGeneration { .. } => None,
        QueryTargetV1::CursorScope { scope_id } => Some(scope_id),
        QueryTargetV1::Gap { gap_id } => Some(gap_id),
        QueryTargetV1::Quarantine { quarantine_id } => Some(quarantine_id),
        QueryTargetV1::BackfillPlan { plan_id } => Some(plan_id),
        QueryTargetV1::BackfillResult { result_id } => Some(result_id),
        QueryTargetV1::Artifact { occurrence_id, .. } => Some(occurrence_id),
        QueryTargetV1::CatalogReceipt { batch_id } => Some(batch_id),
    };
    if identity.is_some_and(|value| value.as_str().is_empty()) {
        return Err(OperationalError::Invalid(
            "query target identity cannot be empty",
        ));
    }
    Ok(())
}

fn decode_bounded<T: DeserializeOwned>(
    bytes: &[u8],
    maximum: usize,
    field: &'static str,
) -> Result<T> {
    if bytes.len() > maximum {
        return Err(OperationalError::BoundExceeded {
            field,
            maximum: u64::try_from(maximum).unwrap_or(u64::MAX),
        });
    }
    Ok(serde_json::from_slice(bytes)?)
}
