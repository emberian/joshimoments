use crate::{ExportError, Result, specs::TABLE_SPECS};
use arrow_array::{ArrayRef, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub(crate) struct CoverageBatches {
    pub(crate) windows: RecordBatch,
    pub(crate) gaps: RecordBatch,
}

struct WindowRow {
    id: String,
    scope_id: String,
    source_id: String,
    lower_us: i64,
    upper_us: i64,
    kind: String,
    commit_seq: i64,
}

struct GapRow {
    id: String,
    window_id: String,
    scope_id: String,
    class: String,
    opened_us: i64,
    detected_us: i64,
    recovered_us: Option<i64>,
    recovery_known_us: Option<i64>,
    commit_seq: i64,
}

type StoredWindow = (
    String,
    String,
    String,
    Option<String>,
    String,
    String,
    Option<String>,
    Option<String>,
    String,
    String,
    i64,
);
type StoredRecovery = (String, String, Option<String>, Option<String>, i64, i64);

/// Projects only an explicit, canonically ordered coverage selection into Snapshot V2.
///
/// Snapshot V2 has one total wall clock for coverage. Durable evidence may instead use commit,
/// source-cursor, unknown, or open boundaries. Those valid source records are deliberately
/// refused here rather than rounded, substituted, or omitted from a requested closure.
pub(crate) fn selected_coverage_batches(
    connection: &Connection,
    cutoff: CommitSeq,
    selected: &[StableString],
) -> Result<CoverageBatches> {
    let cutoff = sql_commit(cutoff)?;
    let mut windows = Vec::with_capacity(selected.len());
    let mut gaps = Vec::new();
    for selected_id in selected {
        let window = load_window(connection, cutoff, selected_id.as_str())?;
        gaps.extend(load_gaps(
            connection,
            cutoff,
            &window.id,
            &window.scope_id,
            &window.source_id,
            &window.kind,
        )?);
        windows.push(window);
    }
    Ok(CoverageBatches {
        windows: window_batch(&windows)?,
        gaps: gap_batch(&gaps)?,
    })
}

#[allow(clippy::too_many_lines)]
fn load_window(connection: &Connection, cutoff: i64, id: &str) -> Result<WindowRow> {
    let row: Option<StoredWindow> = connection
        .query_row(
            "SELECT w.source_id,w.scope_kind,c.scope_family_recognition,c.scope_subject,
                    json_extract(c.lower_boundary_json,'$.clock'),
                    json_extract(c.lower_boundary_json,'$.value'),
                    json_extract(c.upper_boundary_json,'$.clock'),
                    json_extract(c.upper_boundary_json,'$.value'),
                    c.state,c.state_recognition,w.opened_commit_seq
             FROM coverage_window w
             JOIN coverage_window_contract c USING(coverage_id)
             WHERE w.coverage_id=?1 AND w.opened_commit_seq<=?2",
            params![id, cutoff],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                    row.get(8)?,
                    row.get(9)?,
                    row.get(10)?,
                ))
            },
        )
        .optional()?;
    let Some((
        source_id,
        family,
        family_recognition,
        subject,
        lower_clock,
        lower_value,
        upper_clock,
        upper_value,
        state,
        state_recognition,
        commit_seq,
    )) = row
    else {
        return Err(invalid(format!(
            "selected coverage window {id} is absent at the export cutoff"
        )));
    };
    if family_recognition != "known" || state_recognition != "known" || state.is_empty() {
        return Err(unrepresentable(id, "unknown family or state"));
    }
    if lower_clock != "wall" || upper_clock.as_deref() != Some("wall") {
        return Err(unrepresentable(
            id,
            "window is open or does not have two Wall boundaries",
        ));
    }
    let lower_us = wall_us(&lower_value, "coverage lower boundary")?;
    let upper_us = wall_us(
        upper_value
            .as_deref()
            .ok_or_else(|| unrepresentable(id, "window upper Wall value is absent"))?,
        "coverage upper boundary",
    )?;
    if lower_us >= upper_us {
        return Err(unrepresentable(id, "window Wall bounds are not ordered"));
    }
    Ok(WindowRow {
        id: id.to_owned(),
        scope_id: scope_id(&source_id, &family, subject.as_deref())?,
        source_id,
        lower_us,
        upper_us,
        kind: family,
        commit_seq,
    })
}

fn load_gaps(
    connection: &Connection,
    cutoff: i64,
    window_id: &str,
    window_scope_id: &str,
    window_source_id: &str,
    window_family: &str,
) -> Result<Vec<GapRow>> {
    let mut statement = connection.prepare(
        "SELECT g.gap_id,g.cause_code,g.detected_commit_seq,g.detected_wall_us,
                c.scope_source_id,c.scope_family,c.scope_family_recognition,c.scope_subject,
                json_extract(c.lower_boundary_json,'$.clock'),
                json_extract(c.lower_boundary_json,'$.value'),
                json_extract(c.upper_boundary_json,'$.clock'),c.reason_recognition
         FROM coverage_gap g JOIN coverage_gap_contract c USING(gap_id)
         WHERE g.coverage_id=?1 AND g.detected_commit_seq<=?2 ORDER BY g.gap_id",
    )?;
    let raw = statement
        .query_map(params![window_id, cutoff], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, String>(6)?,
                row.get::<_, Option<String>>(7)?,
                row.get::<_, String>(8)?,
                row.get::<_, String>(9)?,
                row.get::<_, Option<String>>(10)?,
                row.get::<_, String>(11)?,
            ))
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    raw.into_iter()
        .map(
            |(
                id,
                class,
                detected_commit,
                detected_us,
                source_id,
                family,
                family_recognition,
                subject,
                lower_clock,
                lower_value,
                upper_clock,
                reason_recognition,
            )| {
                if family_recognition != "known"
                    || reason_recognition != "known"
                    || lower_clock != "wall"
                    || upper_clock.is_some()
                {
                    return Err(unrepresentable(
                        &id,
                        "gap requires known scope/reason, Wall lower, and absent upper",
                    ));
                }
                if source_id != window_source_id
                    || family != window_family
                    || scope_id(&source_id, &family, subject.as_deref())? != window_scope_id
                {
                    return Err(unrepresentable(&id, "gap scope differs from its window"));
                }
                let (recovered_us, recovery_known_us, commit_seq) =
                    load_recovery(connection, cutoff, &id, detected_commit, detected_us)?;
                Ok(GapRow {
                    id,
                    window_id: window_id.to_owned(),
                    scope_id: window_scope_id.to_owned(),
                    class,
                    opened_us: wall_us(&lower_value, "coverage gap lower boundary")?,
                    detected_us,
                    recovered_us,
                    recovery_known_us,
                    commit_seq,
                })
            },
        )
        .collect()
}

fn load_recovery(
    connection: &Connection,
    cutoff: i64,
    gap_id: &str,
    detected_commit: i64,
    detected_us: i64,
) -> Result<(Option<i64>, Option<i64>, i64)> {
    let row: Option<StoredRecovery> = connection
        .query_row(
            "SELECT r.recovery_status,c.status_recognition,
                    json_extract(c.recovered_through_json,'$.clock'),
                    json_extract(c.recovered_through_json,'$.value'),
                    c.available_wall_us,r.commit_seq
             FROM coverage_gap_recovery r
             JOIN coverage_recovery_contract c USING(recovery_id)
             WHERE r.gap_id=?1 AND r.commit_seq<=?2
             ORDER BY r.commit_seq DESC LIMIT 1",
            params![gap_id, cutoff],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            },
        )
        .optional()?;
    let Some((status, recognition, clock, value, available_us, commit_seq)) = row else {
        return Ok((None, None, detected_commit));
    };
    if status != "complete" || recognition != "known" || clock.as_deref() != Some("wall") {
        return Err(unrepresentable(
            gap_id,
            "latest recovery is partial, unrecoverable, unknown, or non-Wall",
        ));
    }
    let recovered_us = wall_us(
        value
            .as_deref()
            .ok_or_else(|| unrepresentable(gap_id, "complete recovery Wall value is absent"))?,
        "coverage recovered-through boundary",
    )?;
    if commit_seq <= detected_commit || available_us < detected_us {
        return Err(unrepresentable(
            gap_id,
            "recovery knowledge does not follow gap detection",
        ));
    }
    Ok((Some(recovered_us), Some(available_us), commit_seq))
}

fn window_batch(rows: &[WindowRow]) -> Result<RecordBatch> {
    let strings = |field: fn(&WindowRow) -> &str| -> ArrayRef {
        Arc::new(StringArray::from(
            rows.iter().map(field).collect::<Vec<_>>(),
        ))
    };
    RecordBatch::try_new(
        Arc::new(TABLE_SPECS[12].schema()),
        vec![
            strings(|row| &row.id),
            strings(|row| &row.scope_id),
            strings(|row| &row.source_id),
            Arc::new(
                TimestampMicrosecondArray::from(
                    rows.iter().map(|row| row.lower_us).collect::<Vec<_>>(),
                )
                .with_timezone("UTC"),
            ),
            Arc::new(
                TimestampMicrosecondArray::from(
                    rows.iter().map(|row| row.upper_us).collect::<Vec<_>>(),
                )
                .with_timezone("UTC"),
            ),
            strings(|row| &row.kind),
            Arc::new(Int64Array::from(
                rows.iter().map(|row| row.commit_seq).collect::<Vec<_>>(),
            )),
        ],
    )
    .map_err(ExportError::Arrow)
}

fn gap_batch(rows: &[GapRow]) -> Result<RecordBatch> {
    let strings = |field: fn(&GapRow) -> &str| -> ArrayRef {
        Arc::new(StringArray::from(
            rows.iter().map(field).collect::<Vec<_>>(),
        ))
    };
    let timestamps = |field: fn(&GapRow) -> i64| -> ArrayRef {
        Arc::new(
            TimestampMicrosecondArray::from(rows.iter().map(field).collect::<Vec<_>>())
                .with_timezone("UTC"),
        )
    };
    RecordBatch::try_new(
        Arc::new(TABLE_SPECS[13].schema()),
        vec![
            strings(|row| &row.id),
            strings(|row| &row.window_id),
            strings(|row| &row.scope_id),
            strings(|row| &row.class),
            timestamps(|row| row.opened_us),
            timestamps(|row| row.detected_us),
            timestamps(|row| row.detected_us),
            Arc::new(
                TimestampMicrosecondArray::from(
                    rows.iter().map(|row| row.recovered_us).collect::<Vec<_>>(),
                )
                .with_timezone("UTC"),
            ),
            Arc::new(
                TimestampMicrosecondArray::from(
                    rows.iter()
                        .map(|row| row.recovery_known_us)
                        .collect::<Vec<_>>(),
                )
                .with_timezone("UTC"),
            ),
            Arc::new(Int64Array::from(
                rows.iter().map(|row| row.commit_seq).collect::<Vec<_>>(),
            )),
        ],
    )
    .map_err(ExportError::Arrow)
}

fn scope_id(source_id: &str, family: &str, subject: Option<&str>) -> Result<String> {
    let preimage = serde_json::to_vec(&json!([
        "joshi.analysis.coverage-scope/v1",
        source_id,
        family,
        subject
    ]))?;
    Ok(format!("sha256:{:x}", Sha256::digest(preimage)))
}

fn wall_us(value: &str, field: &'static str) -> Result<i64> {
    let timestamp = value
        .parse::<UtcTimestamp>()
        .map_err(|error| invalid(format!("{field} is not canonical: {error}")))?;
    let microseconds = timestamp.as_datetime().unix_timestamp_nanos() / 1_000;
    i64::try_from(microseconds).map_err(|_| invalid(format!("{field} exceeds i64 microseconds")))
}

fn sql_commit(value: CommitSeq) -> Result<i64> {
    i64::try_from(value.get()).map_err(|_| invalid("commit exceeds SQLite i64"))
}

fn unrepresentable(id: &str, reason: &str) -> ExportError {
    invalid(format!(
        "selected coverage {id} is valid evidence but unrepresentable in Snapshot V2: {reason}"
    ))
}

fn invalid(message: impl Into<String>) -> ExportError {
    ExportError::Invalid(message.into())
}
