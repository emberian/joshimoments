use crate::{ExportError, Result, specs::TABLE_SPECS};
use arrow_array::{ArrayRef, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray};
use joshi_domain::CommitSeq;
use rusqlite::{Connection, params};
use std::sync::Arc;

struct ProvenanceRow {
    assertion_id: String,
    observation_id: String,
    source_id: String,
    semantic_key: String,
    value_sha256: String,
    observed_wall_us: i64,
    available_wall_us: i64,
    available_commit_seq: i64,
}

/// Projects the durable assertion/observation evidence graph into Snapshot V2 provenance.
///
/// One exported row is one exact `(assertion, observation)` evidence edge, which is that
/// relation's frozen primary key. `available_commit_seq` is the commit that produced the
/// assertion, because that is when the edge itself became knowable; `observed_at` stays the
/// retained observation's own receive clock, so the pair remains ordered by construction.
///
/// An edge whose observation was retained before `from_commit_seq` is still exported. The window
/// selects the knowledge produced in it, and dropping such an edge would silently narrow an
/// assertion's evidence closure rather than narrow the window.
pub(crate) fn provenance_batch(
    connection: &Connection,
    from: CommitSeq,
    cutoff: CommitSeq,
) -> Result<RecordBatch> {
    let from = sql_commit(from)?;
    let cutoff = sql_commit(cutoff)?;
    let mut statement = connection.prepare(
        "SELECT a.assertion_id,e.observation_id,o.source_id,a.semantic_key,a.value_sha256,
                o.received_wall_us,a.produced_wall_us,a.produced_commit_seq
         FROM assertion a
         JOIN assertion_observation_evidence e ON e.assertion_id=a.assertion_id
         JOIN observation o ON o.observation_id=e.observation_id
         WHERE a.produced_commit_seq BETWEEN ?1 AND ?2
         ORDER BY a.assertion_id,e.observation_id",
    )?;
    let rows = statement
        .query_map(params![from, cutoff], |row| {
            Ok(ProvenanceRow {
                assertion_id: row.get(0)?,
                observation_id: row.get(1)?,
                source_id: row.get(2)?,
                semantic_key: row.get(3)?,
                value_sha256: row.get(4)?,
                observed_wall_us: row.get(5)?,
                available_wall_us: row.get(6)?,
                available_commit_seq: row.get(7)?,
            })
        })?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    for row in &rows {
        if row.observed_wall_us > row.available_wall_us {
            return Err(invalid(format!(
                "assertion {} became available before its evidence observation {} was received",
                row.assertion_id, row.observation_id
            )));
        }
    }
    let strings = |field: fn(&ProvenanceRow) -> String| -> ArrayRef {
        Arc::new(StringArray::from(
            rows.iter().map(field).collect::<Vec<_>>(),
        ))
    };
    let timestamps = |field: fn(&ProvenanceRow) -> i64| -> ArrayRef {
        Arc::new(
            TimestampMicrosecondArray::from(rows.iter().map(field).collect::<Vec<_>>())
                .with_timezone("UTC"),
        )
    };
    RecordBatch::try_new(
        Arc::new(TABLE_SPECS[11].schema()),
        vec![
            strings(|row| row.assertion_id.clone()),
            strings(|row| row.observation_id.clone()),
            strings(|row| row.source_id.clone()),
            strings(|row| row.semantic_key.clone()),
            strings(|row| format!("sha256:{}", row.value_sha256)),
            timestamps(|row| row.observed_wall_us),
            timestamps(|row| row.available_wall_us),
            Arc::new(Int64Array::from(
                rows.iter()
                    .map(|row| row.available_commit_seq)
                    .collect::<Vec<_>>(),
            )),
        ],
    )
    .map_err(ExportError::Arrow)
}

fn sql_commit(value: CommitSeq) -> Result<i64> {
    i64::try_from(value.get()).map_err(|_| invalid("commit exceeds SQLite i64"))
}

fn invalid(message: impl Into<String>) -> ExportError {
    ExportError::Invalid(message.into())
}
