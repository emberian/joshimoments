//! Reading one closed hot lease back out of a reopened catalog.
//!
//! Every value here comes from a row the store already holds. The process that wrote them is
//! gone: the catalog is reopened read-only, the coverage claim and each unobserved interval are
//! read from `coverage_window` and `coverage_gap`, and one retained payload is read back byte for
//! byte through the store's own typed observation reader.
//!
//! `joshi-store` exposes no typed reader for coverage windows or gaps, so the two coverage tables
//! are read directly under a read-only, `query_only` connection. That missing reader is a real
//! gap in the store's public surface, not a licence to widen this one.

use std::path::Path;

use joshi_domain::SourceId as DomainSourceId;
use joshi_store::{SqliteStore, StoreConfig, StoreMode};
use rusqlite::{Connection, OpenFlags, OptionalExtension as _, params};
use serde::{Deserialize, Serialize};

use crate::{Result, SupervisorError, hot_lease::retain::WEBSOCKET_SOURCE_ID};

/// Stable wire contract of one lease readback.
pub const LEASE_READBACK_CONTRACT: &str = "joshi.supervisor.hot_lease_readback/v1";

/// The coverage claim one lease left behind.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StoredCoverageWindowV1 {
    pub coverage_id: String,
    pub source_id: String,
    pub scope_kind: String,
    pub scope_key: String,
    pub coverage_level: String,
    pub opened_commit_seq: i64,
    pub opened_wall_us: i64,
    pub lower_boundary_json: String,
    pub upper_boundary_json: Option<String>,
    pub state: String,
}

/// One exact interval of the lease that was not observed, as the catalog holds it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StoredCoverageGapV1 {
    pub gap_id: String,
    pub coverage_id: String,
    pub cause_code: String,
    pub severity: String,
    pub detected_commit_seq: i64,
    pub detected_wall_us: i64,
    /// Inclusive lower wall boundary in microseconds. Present because both boundaries are exact.
    pub event_lower_us: Option<i64>,
    /// Exclusive upper wall boundary in microseconds.
    pub event_upper_us: Option<i64>,
    pub scope_subject: Option<String>,
}

impl StoredCoverageGapV1 {
    /// Exact duration of the unobserved interval in microseconds, when both boundaries are known.
    #[must_use]
    pub fn duration_us(&self) -> Option<i64> {
        match (self.event_lower_us, self.event_upper_us) {
            (Some(lower), Some(upper)) => Some(upper.saturating_sub(lower)),
            _ => None,
        }
    }
}

/// What a reopened catalog says about one lease.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LeaseReadbackV1 {
    pub contract: String,
    pub schema_version: u64,
    pub catalog_root: String,
    pub catalog_schema: String,
    pub coverage: Option<StoredCoverageWindowV1>,
    pub gaps: Vec<StoredCoverageGapV1>,
    /// Observations the WebSocket source delivered into this catalog through the highest commit.
    pub websocket_observation_count: u64,
    /// Exact byte sum of the payloads read back for those observations.
    pub read_back_payload_bytes: u64,
    /// Highest chain slot any read-back observation names.
    pub highest_observed_slot: Option<u64>,
    /// Exact first bytes of one retained payload, proving the blob survived the restart.
    pub first_payload_preview: Option<String>,
    /// The provider body inside that retained payload, decoded from its frame envelope. This is
    /// the wire text itself, not a summary of it.
    pub first_frame_body_preview: Option<String>,
}

/// Reopen a catalog read-only and read one lease back out of it.
///
/// # Errors
///
/// Returns an error when the catalog is absent or unreadable, or when a stored row violates the
/// schema this reader expects.
pub fn read_lease(
    config: &StoreConfig,
    coverage_id: &str,
    payload_limit: usize,
) -> Result<LeaseReadbackV1> {
    let store = SqliteStore::open(config.clone(), StoreMode::ReadOnly)
        .map_err(|error| SupervisorError::Catalog(error.to_string()))?;
    let catalog_schema = store
        .catalog_schema()
        .map_err(|error| SupervisorError::Catalog(error.to_string()))?;
    let source_id = DomainSourceId::new(WEBSOCKET_SOURCE_ID)?;
    let observations = store
        .source_observations_as_known(&source_id, None, payload_limit)
        .map_err(|error| SupervisorError::Catalog(error.to_string()))?;
    let (count, bytes, slot, preview, body_preview) = match observations {
        None => (0, 0, None, None, None),
        Some(found) => {
            let count = u64::try_from(found.observations.len()).unwrap_or(u64::MAX);
            let bytes = found
                .observations
                .iter()
                .map(|observation| u64::try_from(observation.payload.len()).unwrap_or(u64::MAX))
                .sum();
            let slot = found
                .observations
                .iter()
                .filter_map(|observation| observation.chain_slot)
                .max();
            let first = found.observations.first();
            let preview = first.map(|observation| preview_of(&observation.payload));
            let body_preview = first.and_then(|observation| {
                serde_json::from_slice::<joshi_sources::RetainedFrameEnvelope>(&observation.payload)
                    .ok()
                    .map(|envelope| preview_of(&envelope.body))
            });
            (count, bytes, slot, preview, body_preview)
        }
    };

    let connection = Connection::open_with_flags(
        &config.catalog_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    connection.pragma_update(None, "query_only", "ON")?;
    let coverage = read_window(&connection, coverage_id)?;
    let gaps = read_gaps(&connection, coverage_id)?;

    Ok(LeaseReadbackV1 {
        contract: LEASE_READBACK_CONTRACT.to_owned(),
        schema_version: 1,
        catalog_root: config
            .catalog_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .display()
            .to_string(),
        catalog_schema: catalog_schema.as_str().to_owned(),
        coverage,
        gaps,
        websocket_observation_count: count,
        read_back_payload_bytes: bytes,
        highest_observed_slot: slot,
        first_payload_preview: preview,
        first_frame_body_preview: body_preview,
    })
}

fn read_window(
    connection: &Connection,
    coverage_id: &str,
) -> Result<Option<StoredCoverageWindowV1>> {
    Ok(connection
        .query_row(
            "SELECT w.coverage_id,w.source_id,w.scope_kind,w.scope_key,w.coverage_level,
                    w.opened_commit_seq,w.opened_wall_us,c.lower_boundary_json,
                    c.upper_boundary_json,c.state
             FROM coverage_window w JOIN coverage_window_contract c USING(coverage_id)
             WHERE w.coverage_id=?1",
            params![coverage_id],
            |row| {
                Ok(StoredCoverageWindowV1 {
                    coverage_id: row.get(0)?,
                    source_id: row.get(1)?,
                    scope_kind: row.get(2)?,
                    scope_key: row.get(3)?,
                    coverage_level: row.get(4)?,
                    opened_commit_seq: row.get(5)?,
                    opened_wall_us: row.get(6)?,
                    lower_boundary_json: row.get(7)?,
                    upper_boundary_json: row.get(8)?,
                    state: row.get(9)?,
                })
            },
        )
        .optional()?)
}

fn read_gaps(connection: &Connection, coverage_id: &str) -> Result<Vec<StoredCoverageGapV1>> {
    let mut statement = connection.prepare(
        "SELECT g.gap_id,g.coverage_id,g.cause_code,g.severity,g.detected_commit_seq,
                g.detected_wall_us,g.event_lower_us,g.event_upper_us,c.scope_subject
         FROM coverage_gap g JOIN coverage_gap_contract c USING(gap_id)
         WHERE g.coverage_id=?1
         ORDER BY g.event_lower_us,g.gap_id",
    )?;
    let rows = statement.query_map(params![coverage_id], |row| {
        Ok(StoredCoverageGapV1 {
            gap_id: row.get(0)?,
            coverage_id: row.get(1)?,
            cause_code: row.get(2)?,
            severity: row.get(3)?,
            detected_commit_seq: row.get(4)?,
            detected_wall_us: row.get(5)?,
            event_lower_us: row.get(6)?,
            event_upper_us: row.get(7)?,
            scope_subject: row.get(8)?,
        })
    })?;
    let mut gaps = Vec::new();
    for row in rows {
        gaps.push(row?);
    }
    Ok(gaps)
}

fn preview_of(payload: &[u8]) -> String {
    String::from_utf8_lossy(payload)
        .chars()
        .filter(|value| !value.is_control())
        .take(200)
        .collect()
}

impl From<rusqlite::Error> for SupervisorError {
    fn from(value: rusqlite::Error) -> Self {
        Self::Catalog(value.to_string())
    }
}
