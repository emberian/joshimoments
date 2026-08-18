//! Read-only I6 projections derived only from already durable Wave 5 rows.

use joshi_domain::{CommitSeq, StableString, UtcTimestamp};
use joshi_operational_status::{
    DurableProgressKind, DurableProgressState, DurableProgressV1, OperationalStatusViewV1,
};
use rusqlite::params;

use crate::{Result, SqliteStore, StoreError};

type ProgressRow = (String, &'static str, String, String, i64, i64);

impl SqliteStore {
    /// Resolves the durable run/spool/export/import milestones for one exact Wave 5 run.
    ///
    /// This is a read-only query adapter. It cannot acknowledge a segment, advance a cursor,
    /// publish, export, import, or change operational readiness. Sampled resources and transition
    /// history remain separate inputs and are therefore empty in this store-only view.
    ///
    /// # Errors
    ///
    /// Refuses an unknown or corrupted run, malformed persisted digests/clocks, duplicate query
    /// identities, or a status-model validation failure.
    pub fn load_wave5_store_status_view_v1(
        &self,
        run_registration_id: &StableString,
    ) -> Result<OperationalStatusViewV1> {
        self.load_wave5_run_registration_v1(run_registration_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 run registration",
                identity: run_registration_id.to_string(),
            })?;

        let mut progress = Vec::new();
        self.collect_wave5_progress(
            "SELECT run_registration_id,registration_sha256,created_commit_seq
             FROM wave5_run_registration_v1 WHERE run_registration_id=?1",
            run_registration_id,
            "run",
            &mut progress,
        )?;
        self.collect_wave5_progress(
            "SELECT catalog_admission_id,binding_sha256,created_commit_seq
             FROM wave5_spool_catalog_binding_v1 WHERE run_registration_id=?1",
            run_registration_id,
            "spool_catalog",
            &mut progress,
        )?;
        self.collect_wave5_progress(
            "SELECT export_binding_id,binding_sha256,created_commit_seq
             FROM wave5_export_validation_binding_v1 WHERE run_registration_id=?1",
            run_registration_id,
            "export",
            &mut progress,
        )?;
        self.collect_wave5_progress(
            "SELECT import_id,registration_sha256,created_commit_seq
             FROM wave5_restricted_artifact_v1 WHERE run_registration_id=?1",
            run_registration_id,
            "import",
            &mut progress,
        )?;
        progress.sort_by(|left, right| left.progress_id.cmp(&right.progress_id));
        let observed_at = progress
            .iter()
            .map(|value| value.observed_at)
            .max()
            .ok_or_else(|| {
                StoreError::InvalidBatch("registered run has no durable progress".into())
            })?;
        OperationalStatusViewV1::new(observed_at, progress, Vec::new(), Vec::new())
            .map_err(|error| StoreError::InvalidBatch(format!("Wave 5 status projection: {error}")))
    }

    fn collect_wave5_progress(
        &self,
        sql: &str,
        run_registration_id: &StableString,
        namespace: &'static str,
        output: &mut Vec<DurableProgressV1>,
    ) -> Result<()> {
        let mut statement = self.connection.prepare(sql)?;
        let rows = statement.query_map(params![run_registration_id.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                namespace,
                run_registration_id.to_string(),
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(2)?,
            ))
        })?;
        for row in rows {
            let (identity, namespace, scope, digest, commit_seq, _) = row?;
            let committed_wall_us: i64 = self.connection.query_row(
                "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
                [commit_seq],
                |value| value.get(0),
            )?;
            output.push(progress_from_row((
                identity,
                namespace,
                scope,
                digest,
                commit_seq,
                committed_wall_us,
            ))?);
        }
        Ok(())
    }
}

fn progress_from_row(row: ProgressRow) -> Result<DurableProgressV1> {
    let (identity, namespace, scope, raw_digest, commit_seq, committed_wall_us) = row;
    if raw_digest.len() != 64
        || !raw_digest.bytes().all(|byte| byte.is_ascii_hexdigit())
        || raw_digest.bytes().any(|byte| byte.is_ascii_uppercase())
    {
        return Err(StoreError::InvalidDigest {
            kind: "Wave 5 durable progress",
            value: raw_digest,
        });
    }
    let commit = u64::try_from(commit_seq).map_err(|_| StoreError::IntegerRange {
        field: "Wave 5 progress commit",
        value: commit_seq.to_string(),
    })?;
    if commit == 0 {
        return Err(StoreError::IntegerRange {
            field: "Wave 5 progress commit",
            value: commit.to_string(),
        });
    }
    let seconds = committed_wall_us.div_euclid(1_000_000);
    let micros = committed_wall_us.rem_euclid(1_000_000);
    let timestamp = time::OffsetDateTime::from_unix_timestamp(seconds)
        .map_err(|_| StoreError::TimestampRange {
            field: "Wave 5 progress commit",
        })?
        .replace_nanosecond(u32::try_from(micros).unwrap_or(0).saturating_mul(1_000))
        .map_err(|_| StoreError::TimestampRange {
            field: "Wave 5 progress commit",
        })?;
    let observed_at = UtcTimestamp::new(timestamp).map_err(|_| StoreError::TimestampRange {
        field: "Wave 5 progress commit",
    })?;
    DurableProgressV1::from_store_resolved(
        StableString::new(format!("{namespace}:{identity}"))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        match namespace {
            "export" => DurableProgressKind::Export,
            "import" => DurableProgressKind::Import,
            _ => DurableProgressKind::Receipt,
        },
        StableString::new(scope).map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        None,
        DurableProgressState::Committed,
        Some(CommitSeq::new(commit)),
        Some(
            StableString::new(format!("sha256:{raw_digest}"))
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        ),
        observed_at,
    )
    .map_err(|error| StoreError::InvalidBatch(format!("Wave 5 progress row: {error}")))
}
