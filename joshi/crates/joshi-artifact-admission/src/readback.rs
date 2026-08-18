use crate::{ArtifactAdmissionError, CLAIM_SCOPE, DescriptiveChartShapeRowV2, Result};
use arrow_array::{
    Array, Decimal128Array, Int64Array, RecordBatch, StringArray, TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema, TimeUnit};
use bytes::Bytes;
use joshi_domain::{StableString, UtcTimestamp};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::cmp::Ordering;

pub(crate) fn read_descriptive_part(
    bytes: Vec<u8>,
) -> Result<(
    Vec<RecordBatch>,
    Vec<DescriptiveChartShapeRowV2>,
    String,
    String,
)> {
    let builder = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(bytes))?;
    let schema = builder.schema().clone();
    let mut batches = builder
        .build()?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if batches.is_empty() {
        batches.push(RecordBatch::new_empty(schema));
    }
    let schema = batches
        .first()
        .ok_or_else(|| invalid("Parquet part has no record batch"))?
        .schema();
    validate_schema(&schema)?;
    let mut rows = Vec::new();
    for batch in &batches {
        if batch.schema() != schema {
            return Err(invalid("Parquet batches disagree on schema"));
        }
        for index in 0..batch.num_rows() {
            rows.push(read_row(batch, index)?);
        }
    }
    if rows.windows(2).any(|window| {
        (window[0].scene_id.as_str(), window[0].episode_id.as_str())
            >= (window[1].scene_id.as_str(), window[1].episode_id.as_str())
    }) {
        return Err(invalid(
            "descriptive rows must be strictly primary-key ordered",
        ));
    }
    let schema_digest = qualified_sha256(&serde_json::to_vec(&schema_descriptor(&schema)?)?);
    let logical = logical_table_digest(&batches, &["scene_id", "episode_id"])?;
    Ok((batches, rows, schema_digest, logical))
}

fn read_row(batch: &RecordBatch, row: usize) -> Result<DescriptiveChartShapeRowV2> {
    let expected = u64_value(batch, "expected_samples", row)?;
    let observed = u64_value(batch, "observed_samples", row)?;
    let gaps = u64_value(batch, "gap_samples", row)?;
    if observed.checked_add(gaps) != Some(expected) {
        return Err(invalid("row sample support does not close"));
    }
    let claim = text(batch, "claim_scope", row)?;
    if claim != CLAIM_SCOPE {
        return Err(invalid("row escaped descriptive-only claim scope"));
    }
    Ok(DescriptiveChartShapeRowV2 {
        scene_id: stable(&text(batch, "scene_id", row)?, "scene_id")?,
        decision_id: stable(&text(batch, "decision_id", row)?, "decision_id")?,
        episode_id: stable(&text(batch, "episode_id", row)?, "episode_id")?,
        candidate_id: stable(&text(batch, "candidate_id", row)?, "candidate_id")?,
        decision_available_at: timestamp(batch, "decision_available_at", row)?,
        expected_samples: expected,
        observed_samples: observed,
        gap_samples: gaps,
        claim_scope: stable(&claim, "claim_scope")?,
    })
}

fn validate_schema(schema: &Schema) -> Result<()> {
    let expected = expected_schema();
    if schema != &expected {
        return Err(invalid("Parquet schema is not descriptive chart-shape V2"));
    }
    Ok(())
}

fn expected_schema() -> Schema {
    let text = |name| Field::new(name, DataType::Utf8, false);
    let integer = |name| Field::new(name, DataType::Int64, false);
    let instant = |name| {
        Field::new(
            name,
            DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into())),
            false,
        )
    };
    let decimal = |name| Field::new(name, DataType::Decimal128(20, 0), false);
    Schema::new(vec![
        text("scene_id"),
        text("decision_id"),
        text("episode_id"),
        text("candidate_id"),
        text("territory_id"),
        text("base_asset_id"),
        text("quote_asset_id"),
        instant("decision_available_at"),
        instant("first_event_time"),
        instant("last_event_time"),
        integer("expected_samples"),
        integer("observed_samples"),
        integer("gap_samples"),
        integer("coverage_ratio_ppm"),
        decimal("start_price_base_atoms"),
        decimal("start_price_quote_atoms"),
        decimal("end_price_base_atoms"),
        decimal("end_price_quote_atoms"),
        integer("signed_change_ppm"),
        integer("range_ppm"),
        integer("max_drawdown_ppm"),
        integer("direction_changes"),
        text("path_signature"),
        integer("exposed_samples"),
        integer("flat_watch_samples"),
        integer("runner_samples"),
        text("feature_version"),
        text("claim_scope"),
    ])
}

fn column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a dyn Array> {
    let index = batch.schema().index_of(name)?;
    Ok(batch.column(index).as_ref())
}
fn text(batch: &RecordBatch, name: &str, row: usize) -> Result<String> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| invalid(format!("{name} is not string")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    Ok(array.value(row).to_owned())
}
fn u64_value(batch: &RecordBatch, name: &str, row: usize) -> Result<u64> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| invalid(format!("{name} is not int64")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    u64::try_from(array.value(row)).map_err(|_| invalid(format!("{name} is negative")))
}
fn timestamp(batch: &RecordBatch, name: &str, row: usize) -> Result<UtcTimestamp> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<TimestampMicrosecondArray>()
        .ok_or_else(|| invalid(format!("{name} is not timestamp[us,UTC]")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    timestamp_from_us(array.value(row))
}
fn stable(value: &str, name: &str) -> Result<StableString> {
    StableString::new(value).map_err(|error| invalid(format!("invalid {name}: {error}")))
}
fn timestamp_from_us(value: i64) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or_else(|| invalid("timestamp overflow"))?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|error| invalid(error.to_string()))?;
    UtcTimestamp::new(datetime).map_err(|error| invalid(error.to_string()))
}

pub(crate) fn schema_descriptor(schema: &Schema) -> Result<Value> {
    Ok(
        json!({"fields": schema.fields().iter().map(|field| Ok(json!({
        "name": field.name(), "nullable": field.is_nullable(), "type": type_name(field.data_type())?
    }))).collect::<Result<Vec<_>>>()?}),
    )
}
fn type_name(value: &DataType) -> Result<&'static str> {
    match value {
        DataType::Utf8 => Ok("string"),
        DataType::Int64 => Ok("int64"),
        DataType::Timestamp(TimeUnit::Microsecond, timezone)
            if timezone.as_deref() == Some("UTC") =>
        {
            Ok("timestamp[us, tz=UTC]")
        }
        DataType::Decimal128(20, 0) => Ok("decimal128(20, 0)"),
        other => Err(invalid(format!("unsupported Arrow type {other}"))),
    }
}

fn logical_table_digest(batches: &[RecordBatch], primary_key: &[&str]) -> Result<String> {
    let schema = batches
        .first()
        .ok_or_else(|| invalid("table has no batches"))?
        .schema();
    let mut rows = Vec::new();
    for batch in batches {
        for row in 0..batch.num_rows() {
            let mut object = Map::new();
            for (column, field) in batch.columns().iter().zip(schema.fields()) {
                object.insert(
                    field.name().clone(),
                    scalar_json(column.as_ref(), field, row)?,
                );
            }
            rows.push(Value::Object(object));
        }
    }
    rows.sort_by(|left, right| compare_rows(left, right, primary_key));
    let mut hasher = Sha256::new();
    hasher.update(serde_json::to_vec(&schema_descriptor(&schema)?)?);
    hasher.update(b"\n");
    for row in rows {
        hasher.update(serde_json::to_vec(&row)?);
        hasher.update(b"\n");
    }
    Ok(format!("sha256:{:x}", hasher.finalize()))
}
fn compare_rows(left: &Value, right: &Value, keys: &[&str]) -> Ordering {
    for key in keys {
        let ordering = compare_scalar(&left[*key], &right[*key]);
        if ordering != Ordering::Equal {
            return ordering;
        }
    }
    Ordering::Equal
}
fn compare_scalar(left: &Value, right: &Value) -> Ordering {
    match (left, right) {
        (Value::String(left), Value::String(right)) => left.cmp(right),
        (Value::Number(left), Value::Number(right)) => left.as_i64().cmp(&right.as_i64()),
        _ => serde_json::to_vec(left)
            .unwrap_or_default()
            .cmp(&serde_json::to_vec(right).unwrap_or_default()),
    }
}
fn scalar_json(array: &dyn Array, field: &Field, row: usize) -> Result<Value> {
    if array.is_null(row) {
        return Ok(Value::Null);
    }
    match field.data_type() {
        DataType::Utf8 => Ok(Value::String(
            array
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| invalid("string downcast"))?
                .value(row)
                .to_owned(),
        )),
        DataType::Int64 => Ok(Value::from(
            array
                .as_any()
                .downcast_ref::<Int64Array>()
                .ok_or_else(|| invalid("int64 downcast"))?
                .value(row),
        )),
        DataType::Timestamp(TimeUnit::Microsecond, timezone)
            if timezone.as_deref() == Some("UTC") =>
        {
            Ok(Value::String(
                timestamp_from_us(
                    array
                        .as_any()
                        .downcast_ref::<TimestampMicrosecondArray>()
                        .ok_or_else(|| invalid("timestamp downcast"))?
                        .value(row),
                )?
                .to_string(),
            ))
        }
        DataType::Decimal128(20, 0) => Ok(Value::String(
            array
                .as_any()
                .downcast_ref::<Decimal128Array>()
                .ok_or_else(|| invalid("decimal downcast"))?
                .value(row)
                .to_string(),
        )),
        other => Err(invalid(format!("unsupported Arrow scalar {other}"))),
    }
}
fn qualified_sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
fn invalid(message: impl Into<String>) -> ArtifactAdmissionError {
    ArtifactAdmissionError::Invalid(message.into())
}
