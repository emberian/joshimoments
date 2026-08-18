use crate::{ArtifactAdmissionError, CLAIM_SCOPE, DescriptiveChartShapeRowV2, Result};
use arrow_array::{
    Array, Decimal128Array, Int32Array, Int64Array, RecordBatch, StringArray,
    TimestampMicrosecondArray,
};
use arrow_schema::{DataType, Field, Schema, TimeUnit};
use bytes::Bytes;
use joshi_domain::{StableString, UtcTimestamp};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet},
};

const FEATURE_VERSION: &str = "descriptive-chart-shape/v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ChartSampleRowV1 {
    scene_id: String,
    decision_id: String,
    episode_id: String,
    candidate_id: String,
    territory_id: String,
    base_asset_id: String,
    quote_asset_id: String,
    sample_index: i32,
    expected_sample_count: i32,
    event_time: UtcTimestamp,
    observed_at: UtcTimestamp,
    available_at: UtcTimestamp,
    decision_available_at: UtcTimestamp,
    price_base_atoms: Option<u64>,
    price_quote_atoms: Option<u64>,
    buy_volume_base_atoms: Option<u64>,
    sell_volume_base_atoms: Option<u64>,
    position_state: String,
    coverage_status: String,
    coverage_scope_id: String,
    coverage_window_id: String,
    coverage_gap_id: Option<String>,
    source_assertion_id: Option<String>,
    source_observation_id: Option<String>,
    available_commit_seq: u64,
}

pub(crate) struct ChartSampleSupportV1 {
    pub input_rows: u64,
    pub observed_inputs: u64,
    pub gap_inputs: u64,
    pub window_ids: Vec<String>,
    pub gap_ids: Vec<String>,
    pub maximum_available_at: Option<UtcTimestamp>,
}

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
        batches.push(RecordBatch::new_empty(schema.clone()));
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
        territory_id: stable(&text(batch, "territory_id", row)?, "territory_id")?,
        base_asset_id: stable(&text(batch, "base_asset_id", row)?, "base_asset_id")?,
        quote_asset_id: stable(&text(batch, "quote_asset_id", row)?, "quote_asset_id")?,
        decision_available_at: timestamp(batch, "decision_available_at", row)?,
        first_event_time: timestamp(batch, "first_event_time", row)?,
        last_event_time: timestamp(batch, "last_event_time", row)?,
        expected_samples: expected,
        observed_samples: observed,
        gap_samples: gaps,
        coverage_ratio_ppm: u64_value(batch, "coverage_ratio_ppm", row)?,
        start_price_base_atoms: decimal_u64(batch, "start_price_base_atoms", row)?,
        start_price_quote_atoms: decimal_u64(batch, "start_price_quote_atoms", row)?,
        end_price_base_atoms: decimal_u64(batch, "end_price_base_atoms", row)?,
        end_price_quote_atoms: decimal_u64(batch, "end_price_quote_atoms", row)?,
        signed_change_ppm: i64_value(batch, "signed_change_ppm", row)?,
        range_ppm: i64_value(batch, "range_ppm", row)?,
        max_drawdown_ppm: i64_value(batch, "max_drawdown_ppm", row)?,
        direction_changes: u64_value(batch, "direction_changes", row)?,
        path_signature: text(batch, "path_signature", row)?,
        exposed_samples: u64_value(batch, "exposed_samples", row)?,
        flat_watch_samples: u64_value(batch, "flat_watch_samples", row)?,
        runner_samples: u64_value(batch, "runner_samples", row)?,
        feature_version: stable(&text(batch, "feature_version", row)?, "feature_version")?,
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
fn optional_text(batch: &RecordBatch, name: &str, row: usize) -> Result<Option<String>> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| invalid(format!("{name} is not string")))?;
    Ok((!array.is_null(row)).then(|| array.value(row).to_owned()))
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
fn i64_value(batch: &RecordBatch, name: &str, row: usize) -> Result<i64> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| invalid(format!("{name} is not int64")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    Ok(array.value(row))
}
fn i32_value(batch: &RecordBatch, name: &str, row: usize) -> Result<i32> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<Int32Array>()
        .ok_or_else(|| invalid(format!("{name} is not int32")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    Ok(array.value(row))
}
fn decimal_u64(batch: &RecordBatch, name: &str, row: usize) -> Result<u64> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<Decimal128Array>()
        .ok_or_else(|| invalid(format!("{name} is not decimal128")))?;
    if array.is_null(row) {
        return Err(invalid(format!("{name} is null")));
    }
    u64::try_from(array.value(row)).map_err(|_| invalid(format!("{name} exceeds exact u64")))
}
fn optional_decimal_u64(batch: &RecordBatch, name: &str, row: usize) -> Result<Option<u64>> {
    let array = column(batch, name)?
        .as_any()
        .downcast_ref::<Decimal128Array>()
        .ok_or_else(|| invalid(format!("{name} is not decimal128")))?;
    if array.is_null(row) {
        Ok(None)
    } else {
        u64::try_from(array.value(row))
            .map(Some)
            .map_err(|_| invalid(format!("{name} exceeds exact u64")))
    }
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

pub(crate) fn read_chart_samples_part(
    bytes: Vec<u8>,
) -> Result<(Vec<ChartSampleRowV1>, String, String)> {
    let builder = ParquetRecordBatchReaderBuilder::try_new(Bytes::from(bytes))?;
    let schema = builder.schema().clone();
    if schema.as_ref() != &chart_sample_schema() {
        return Err(invalid(
            "store-resolved feature input is not chart-sample/v1",
        ));
    }
    let mut batches = builder
        .build()?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if batches.is_empty() {
        batches.push(RecordBatch::new_empty(schema.clone()));
    }
    let mut rows = Vec::new();
    for batch in &batches {
        if batch.schema() != schema {
            return Err(invalid("chart-sample Parquet batches disagree on schema"));
        }
        for row in 0..batch.num_rows() {
            let value = ChartSampleRowV1 {
                scene_id: text(batch, "scene_id", row)?,
                decision_id: text(batch, "decision_id", row)?,
                episode_id: text(batch, "episode_id", row)?,
                candidate_id: text(batch, "candidate_id", row)?,
                territory_id: text(batch, "territory_id", row)?,
                base_asset_id: text(batch, "base_asset_id", row)?,
                quote_asset_id: text(batch, "quote_asset_id", row)?,
                sample_index: i32_value(batch, "sample_index", row)?,
                expected_sample_count: i32_value(batch, "expected_sample_count", row)?,
                event_time: timestamp(batch, "event_time", row)?,
                observed_at: timestamp(batch, "observed_at", row)?,
                available_at: timestamp(batch, "available_at", row)?,
                decision_available_at: timestamp(batch, "decision_available_at", row)?,
                price_base_atoms: optional_decimal_u64(batch, "price_base_atoms", row)?,
                price_quote_atoms: optional_decimal_u64(batch, "price_quote_atoms", row)?,
                buy_volume_base_atoms: optional_decimal_u64(batch, "buy_volume_base_atoms", row)?,
                sell_volume_base_atoms: optional_decimal_u64(batch, "sell_volume_base_atoms", row)?,
                position_state: text(batch, "position_state", row)?,
                coverage_status: text(batch, "coverage_status", row)?,
                coverage_scope_id: text(batch, "coverage_scope_id", row)?,
                coverage_window_id: text(batch, "coverage_window_id", row)?,
                coverage_gap_id: optional_text(batch, "coverage_gap_id", row)?,
                source_assertion_id: optional_text(batch, "source_assertion_id", row)?,
                source_observation_id: optional_text(batch, "source_observation_id", row)?,
                available_commit_seq: u64_value(batch, "available_commit_seq", row)?,
            };
            rows.push(value);
        }
    }
    if rows.windows(2).any(|window| {
        (
            &window[0].scene_id,
            &window[0].episode_id,
            window[0].sample_index,
        ) >= (
            &window[1].scene_id,
            &window[1].episode_id,
            window[1].sample_index,
        )
    }) {
        return Err(invalid(
            "chart-sample feature input must be strictly primary-key ordered",
        ));
    }
    let schema_digest = qualified_sha256(&serde_json::to_vec(&schema_descriptor(&schema)?)?);
    let logical = logical_table_digest(&batches, &["scene_id", "episode_id", "sample_index"])?;
    Ok((rows, schema_digest, logical))
}

pub(crate) fn validate_descriptive_metrics(
    input: &[ChartSampleRowV1],
    actual: &[DescriptiveChartShapeRowV2],
) -> Result<ChartSampleSupportV1> {
    let mut groups: BTreeMap<(&str, &str), Vec<&ChartSampleRowV1>> = BTreeMap::new();
    for row in input {
        groups
            .entry((&row.scene_id, &row.episode_id))
            .or_default()
            .push(row);
    }
    let expected = groups
        .into_values()
        .filter_map(|rows| expected_metric_row(&rows).transpose())
        .collect::<Result<Vec<_>>>()?;
    if expected != actual {
        return Err(invalid(
            "derived descriptive metrics differ from exact chart-sample feature input",
        ));
    }
    let input_rows =
        u64::try_from(input.len()).map_err(|_| invalid("input row count exceeds u64"))?;
    let observed_inputs = u64::try_from(
        input
            .iter()
            .filter(|row| row.coverage_status == "observed")
            .count(),
    )
    .map_err(|_| invalid("observed input count exceeds u64"))?;
    let gap_inputs = u64::try_from(
        input
            .iter()
            .filter(|row| row.coverage_status == "gap")
            .count(),
    )
    .map_err(|_| invalid("gap input count exceeds u64"))?;
    Ok(ChartSampleSupportV1 {
        input_rows,
        observed_inputs,
        gap_inputs,
        window_ids: input
            .iter()
            .map(|row| row.coverage_window_id.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect(),
        gap_ids: input
            .iter()
            .filter_map(|row| row.coverage_gap_id.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect(),
        maximum_available_at: input.iter().map(|row| row.available_at).max(),
    })
}

#[allow(clippy::too_many_lines)]
fn expected_metric_row(rows: &[&ChartSampleRowV1]) -> Result<Option<DescriptiveChartShapeRowV2>> {
    if rows.is_empty() {
        return Ok(None);
    }
    let expected_count =
        i32::try_from(rows.len()).map_err(|_| invalid("sample count exceeds i32"))?;
    if rows
        .iter()
        .enumerate()
        .any(|(index, row)| row.sample_index != i32::try_from(index).unwrap_or(i32::MAX))
        || rows
            .iter()
            .any(|row| row.expected_sample_count != expected_count)
    {
        return Err(invalid(
            "chart-sample feature input is not a complete contiguous series",
        ));
    }
    if rows.iter().any(|row| {
        !(row.event_time <= row.observed_at
            && row.observed_at <= row.available_at
            && row.available_at <= row.decision_available_at)
    }) {
        return Err(invalid(
            "chart-sample event/observation/availability/decision clocks are not ordered",
        ));
    }
    let stable_all = |field: fn(&ChartSampleRowV1) -> &str, context: &str| -> Result<String> {
        let first = field(rows[0]);
        if rows.iter().any(|row| field(row) != first) {
            Err(invalid(format!("chart series changes {context}")))
        } else {
            Ok(first.to_owned())
        }
    };
    let scene_id = stable(&stable_all(|row| &row.scene_id, "scene_id")?, "scene_id")?;
    let decision_id = stable(
        &stable_all(|row| &row.decision_id, "decision_id")?,
        "decision_id",
    )?;
    let episode_id = stable(
        &stable_all(|row| &row.episode_id, "episode_id")?,
        "episode_id",
    )?;
    let candidate_id = stable(
        &stable_all(|row| &row.candidate_id, "candidate_id")?,
        "candidate_id",
    )?;
    let territory_id = stable(
        &stable_all(|row| &row.territory_id, "territory_id")?,
        "territory_id",
    )?;
    let base_asset_id = stable(
        &stable_all(|row| &row.base_asset_id, "base_asset_id")?,
        "base_asset_id",
    )?;
    let quote_asset_id = stable(
        &stable_all(|row| &row.quote_asset_id, "quote_asset_id")?,
        "quote_asset_id",
    )?;
    stable(
        &stable_all(|row| &row.coverage_scope_id, "coverage_scope_id")?,
        "coverage_scope_id",
    )?;
    stable(
        &stable_all(|row| &row.coverage_window_id, "coverage_window_id")?,
        "coverage_window_id",
    )?;
    if rows
        .windows(2)
        .any(|window| window[0].event_time > window[1].event_time)
    {
        return Err(invalid("chart-sample event times are not ordered"));
    }
    for row in rows {
        let measured = [
            row.price_base_atoms,
            row.price_quote_atoms,
            row.buy_volume_base_atoms,
            row.sell_volume_base_atoms,
        ];
        match row.coverage_status.as_str() {
            "observed"
                if measured.iter().all(Option::is_some)
                    && row.coverage_gap_id.is_none()
                    && row.source_assertion_id.is_some()
                    && row.source_observation_id.is_some()
                    && matches!(
                        row.position_state.as_str(),
                        "exposed" | "flat_watch" | "runner"
                    ) => {}
            "gap"
                if measured.iter().all(Option::is_none)
                    && row.position_state == "unknown"
                    && row.coverage_gap_id.is_some()
                    && row.source_assertion_id.is_none()
                    && row.source_observation_id.is_none() => {}
            _ => {
                return Err(invalid(
                    "chart feature/gap inputs are not separated exactly",
                ));
            }
        }
        if row.available_commit_seq == 0 {
            return Err(invalid("chart-sample available commit is zero"));
        }
    }
    let observed = rows
        .iter()
        .copied()
        .filter(|row| row.coverage_status == "observed")
        .collect::<Vec<_>>();
    if observed.is_empty() {
        return Ok(None);
    }
    let ratios = observed
        .iter()
        .map(|row| {
            let base = row.price_base_atoms.expect("checked observed base");
            let quote = row.price_quote_atoms.expect("checked observed quote");
            if base == 0 || quote == 0 {
                Err(invalid("observed exact price ratio is not positive"))
            } else {
                Ok((quote, base))
            }
        })
        .collect::<Result<Vec<_>>>()?;
    let (start_quote, start_base) = ratios[0];
    let (end_quote, end_base) = *ratios.last().expect("nonempty ratios");
    let signed_change = ppm_difference(
        &[end_quote, start_base],
        &[start_quote, end_base],
        &[end_base, start_quote],
        "signed_change_ppm",
    )?;
    let mut minimum = ratios[0];
    let mut maximum = ratios[0];
    let mut running_peak = ratios[0];
    let mut max_drawdown = 0_i64;
    let mut directions = Vec::new();
    let mut signature = String::new();
    for (index, ratio) in ratios.iter().copied().enumerate() {
        if compare_ratio(ratio, minimum).is_lt() {
            minimum = ratio;
        }
        if compare_ratio(ratio, maximum).is_gt() {
            maximum = ratio;
        }
        if compare_ratio(ratio, running_peak).is_gt() {
            running_peak = ratio;
        }
        let (peak_quote, peak_base) = running_peak;
        let (quote, base) = ratio;
        let drawdown = ppm_difference(
            &[peak_quote, base],
            &[quote, peak_base],
            &[base, peak_quote],
            "max_drawdown_ppm",
        )?;
        max_drawdown = max_drawdown.max(drawdown);
        if index > 0 {
            let direction = compare_ratio(ratio, ratios[index - 1]);
            directions.push(direction);
            signature.push(if direction.is_gt() {
                '+'
            } else if direction.is_lt() {
                '-'
            } else {
                '0'
            });
        }
    }
    let nonzero = directions
        .into_iter()
        .filter(|direction| !direction.is_eq())
        .collect::<Vec<_>>();
    let direction_changes = nonzero
        .windows(2)
        .filter(|window| window[0] != window[1])
        .count();
    let (minimum_quote, minimum_base) = minimum;
    let (maximum_quote, maximum_base) = maximum;
    let range = ppm_difference(
        &[maximum_quote, minimum_base, start_base],
        &[minimum_quote, maximum_base, start_base],
        &[maximum_base, minimum_base, start_quote],
        "range_ppm",
    )?;
    let minimum_event = observed
        .iter()
        .map(|row| row.event_time)
        .min()
        .expect("nonempty observed times");
    let maximum_event = observed
        .iter()
        .map(|row| row.event_time)
        .max()
        .expect("nonempty observed times");
    let decision_available_at = rows
        .iter()
        .map(|row| row.decision_available_at)
        .max()
        .expect("nonempty decision times");
    Ok(Some(DescriptiveChartShapeRowV2 {
        scene_id,
        decision_id,
        episode_id,
        candidate_id,
        territory_id,
        base_asset_id,
        quote_asset_id,
        decision_available_at,
        first_event_time: minimum_event,
        last_event_time: maximum_event,
        expected_samples: u64::try_from(rows.len()).map_err(|_| invalid("sample count"))?,
        observed_samples: u64::try_from(observed.len()).map_err(|_| invalid("observed count"))?,
        gap_samples: u64::try_from(rows.len() - observed.len())
            .map_err(|_| invalid("gap count"))?,
        coverage_ratio_ppm: u64::try_from(observed.len())
            .ok()
            .and_then(|value| value.checked_mul(1_000_000))
            .and_then(|value| value.checked_div(u64::try_from(rows.len()).ok()?))
            .ok_or_else(|| invalid("coverage ratio overflow"))?,
        start_price_base_atoms: start_base,
        start_price_quote_atoms: start_quote,
        end_price_base_atoms: end_base,
        end_price_quote_atoms: end_quote,
        signed_change_ppm: signed_change,
        range_ppm: range,
        max_drawdown_ppm: max_drawdown,
        direction_changes: u64::try_from(direction_changes)
            .map_err(|_| invalid("direction count"))?,
        path_signature: signature,
        exposed_samples: count_position(&observed, "exposed")?,
        flat_watch_samples: count_position(&observed, "flat_watch")?,
        runner_samples: count_position(&observed, "runner")?,
        feature_version: stable(FEATURE_VERSION, "feature_version")?,
        claim_scope: stable(CLAIM_SCOPE, "claim_scope")?,
    }))
}

fn compare_ratio(left: (u64, u64), right: (u64, u64)) -> Ordering {
    (u128::from(left.0) * u128::from(right.1)).cmp(&(u128::from(right.0) * u128::from(left.1)))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct U256([u64; 4]);

impl Ord for U256 {
    fn cmp(&self, other: &Self) -> Ordering {
        self.0.iter().rev().cmp(other.0.iter().rev())
    }
}

impl PartialOrd for U256 {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl U256 {
    const ZERO: Self = Self([0; 4]);

    fn product(values: &[u64]) -> Self {
        values
            .iter()
            .fold(Self([1, 0, 0, 0]), |value, factor| value.mul_u64(*factor))
    }

    fn mul_u64(self, factor: u64) -> Self {
        let mut output = [0_u64; 4];
        let mut carry = 0_u128;
        for (index, limb) in self.0.into_iter().enumerate() {
            let product = u128::from(limb) * u128::from(factor) + carry;
            output[index] = u64::try_from(product & u128::from(u64::MAX))
                .expect("masked product limb fits u64");
            carry = product >> 64;
        }
        debug_assert_eq!(carry, 0, "bounded exact-rational input exceeds u256");
        Self(output)
    }

    fn checked_sub(self, other: Self) -> Option<Self> {
        if self < other {
            return None;
        }
        let mut output = [0_u64; 4];
        let mut borrow = 0_u128;
        for (index, (left, right)) in self.0.into_iter().zip(other.0).enumerate() {
            let subtrahend = u128::from(right) + borrow;
            let left = u128::from(left);
            if left >= subtrahend {
                output[index] =
                    u64::try_from(left - subtrahend).expect("subtraction limb fits u64");
                borrow = 0;
            } else {
                output[index] = u64::try_from((1_u128 << 64) + left - subtrahend)
                    .expect("borrowed subtraction limb fits u64");
                borrow = 1;
            }
        }
        debug_assert_eq!(borrow, 0);
        Some(Self(output))
    }
}

fn ppm_difference(
    left_factors: &[u64],
    right_factors: &[u64],
    denominator_factors: &[u64],
    context: &str,
) -> Result<i64> {
    let left = U256::product(left_factors);
    let right = U256::product(right_factors);
    let denominator = U256::product(denominator_factors);
    if denominator == U256::ZERO {
        return Err(invalid(format!("{context} denominator is not positive")));
    }
    let (negative, numerator) = match left.cmp(&right) {
        Ordering::Less => (true, right.checked_sub(left).expect("ordered subtraction")),
        Ordering::Equal => return Ok(0),
        Ordering::Greater => (false, left.checked_sub(right).expect("ordered subtraction")),
    };
    let scaled = numerator.mul_u64(1_000_000);
    let limit = if negative {
        1_u64 << 63
    } else {
        i64::MAX as u64
    };
    if scaled >= denominator.mul_u64(limit.saturating_add(1)) {
        return Err(invalid(format!("{context} exceeds i64")));
    }
    let mut low = 0_u64;
    let mut high = limit;
    while low < high {
        let midpoint = low + (high - low).div_ceil(2);
        if denominator.mul_u64(midpoint) <= scaled {
            low = midpoint;
        } else {
            high = midpoint - 1;
        }
    }
    let remainder = scaled
        .checked_sub(denominator.mul_u64(low))
        .expect("quotient product does not exceed numerator");
    let rounded = low
        .checked_add(u64::from(remainder.mul_u64(2) >= denominator))
        .ok_or_else(|| invalid(format!("{context} exceeds i64")))?;
    if rounded > limit {
        return Err(invalid(format!("{context} exceeds i64")));
    }
    if negative {
        if rounded == 1_u64 << 63 {
            Ok(i64::MIN)
        } else {
            i64::try_from(rounded)
                .map(|value| -value)
                .map_err(|_| invalid(format!("{context} exceeds i64")))
        }
    } else {
        i64::try_from(rounded).map_err(|_| invalid(format!("{context} exceeds i64")))
    }
}

fn count_position(rows: &[&ChartSampleRowV1], value: &str) -> Result<u64> {
    u64::try_from(
        rows.iter()
            .filter(|row| row.position_state == value)
            .count(),
    )
    .map_err(|_| invalid("position count exceeds u64"))
}

fn chart_sample_schema() -> Schema {
    let text = |name| Field::new(name, DataType::Utf8, false);
    let nullable_text = |name| Field::new(name, DataType::Utf8, true);
    let integer = |name| Field::new(name, DataType::Int64, false);
    let int32 = |name| Field::new(name, DataType::Int32, false);
    let instant = |name| {
        Field::new(
            name,
            DataType::Timestamp(TimeUnit::Microsecond, Some("UTC".into())),
            false,
        )
    };
    let decimal = |name| Field::new(name, DataType::Decimal128(20, 0), true);
    Schema::new(vec![
        text("scene_id"),
        text("scene_mode"),
        text("scene_view_digest"),
        text("decision_id"),
        text("episode_id"),
        text("candidate_id"),
        text("territory_id"),
        text("base_asset_id"),
        text("quote_asset_id"),
        int32("sample_index"),
        int32("expected_sample_count"),
        instant("event_time"),
        instant("observed_at"),
        instant("available_at"),
        instant("decision_available_at"),
        decimal("price_base_atoms"),
        decimal("price_quote_atoms"),
        decimal("buy_volume_base_atoms"),
        decimal("sell_volume_base_atoms"),
        text("position_state"),
        text("coverage_status"),
        text("coverage_scope_id"),
        text("coverage_window_id"),
        nullable_text("coverage_gap_id"),
        nullable_text("source_assertion_id"),
        nullable_text("source_observation_id"),
        integer("available_commit_seq"),
    ])
}
fn type_name(value: &DataType) -> Result<&'static str> {
    match value {
        DataType::Utf8 => Ok("string"),
        DataType::Int64 => Ok("int64"),
        DataType::Int32 => Ok("int32"),
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
        DataType::Int32 => Ok(Value::from(
            array
                .as_any()
                .downcast_ref::<Int32Array>()
                .ok_or_else(|| invalid("int32 downcast"))?
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

#[cfg(test)]
mod tests {
    use super::*;

    fn instant(value: &str) -> UtcTimestamp {
        value.parse().expect("test timestamp")
    }

    fn observed(index: i32) -> ChartSampleRowV1 {
        ChartSampleRowV1 {
            scene_id: "scene-exact".into(),
            decision_id: "decision-exact".into(),
            episode_id: "episode-exact".into(),
            candidate_id: "candidate-exact".into(),
            territory_id: "territory-exact".into(),
            base_asset_id: "base-exact".into(),
            quote_asset_id: "quote-exact".into(),
            sample_index: index,
            expected_sample_count: 2,
            event_time: if index == 0 {
                instant("2026-08-18T00:00:00.000001Z")
            } else {
                instant("2026-08-18T00:00:00.000002Z")
            },
            observed_at: instant("2026-08-18T00:00:00.000003Z"),
            available_at: instant("2026-08-18T00:00:00.000004Z"),
            decision_available_at: if index == 0 {
                instant("2026-08-18T00:00:00.000005Z")
            } else {
                instant("2026-08-18T00:00:00.000006Z")
            },
            price_base_atoms: Some(if index == 0 {
                (1_u64 << 53) + 1
            } else {
                (1_u64 << 53) + 5
            }),
            price_quote_atoms: Some(if index == 0 {
                (1_u64 << 53) + 3
            } else {
                (1_u64 << 53) + 5 + 22_517_998_138
            }),
            buy_volume_base_atoms: Some((1_u64 << 53) + 7),
            sell_volume_base_atoms: Some((1_u64 << 53) + 9),
            position_state: "exposed".into(),
            coverage_status: "observed".into(),
            coverage_scope_id: "coverage-scope-exact".into(),
            coverage_window_id: "coverage-window-exact".into(),
            coverage_gap_id: None,
            source_assertion_id: Some(format!("assertion-{index}")),
            source_observation_id: Some(format!("observation-{index}")),
            available_commit_seq: u64::try_from(index + 1).expect("positive commit"),
        }
    }

    fn all_gap() -> Vec<ChartSampleRowV1> {
        (0..2)
            .map(|index| {
                let mut row = observed(index);
                row.price_base_atoms = None;
                row.price_quote_atoms = None;
                row.buy_volume_base_atoms = None;
                row.sell_volume_base_atoms = None;
                row.position_state = "unknown".into();
                row.coverage_status = "gap".into();
                row.coverage_gap_id = Some(format!("gap-{index}"));
                row.source_assertion_id = None;
                row.source_observation_id = None;
                row
            })
            .collect()
    }

    fn recompute(rows: &[ChartSampleRowV1]) -> Result<Option<DescriptiveChartShapeRowV2>> {
        expected_metric_row(&rows.iter().collect::<Vec<_>>())
    }

    #[test]
    fn exact_ratios_above_javascript_width_and_latest_availability_are_preserved() {
        let rows = [observed(0), observed(1)];
        let metric = recompute(&rows)
            .expect("valid exact metric")
            .expect("observed metric");
        assert_eq!(metric.start_price_base_atoms, (1_u64 << 53) + 1);
        assert_eq!(
            metric.end_price_quote_atoms,
            (1_u64 << 53) + 5 + 22_517_998_138
        );
        assert_eq!(metric.signed_change_ppm, 2);
        assert_eq!(
            metric.decision_available_at,
            instant("2026-08-18T00:00:00.000006Z")
        );
    }

    #[test]
    fn valid_all_gap_series_has_typed_no_metric_outcome() {
        assert!(recompute(&all_gap()).expect("valid gaps").is_none());
    }

    #[test]
    fn all_gap_series_cannot_launder_identity_status_measurement_or_clock() {
        let mut identity = all_gap();
        identity[1].candidate_id = "candidate-foreign".into();
        assert!(recompute(&identity).is_err());

        let mut status = all_gap();
        status[1].coverage_status = "missing".into();
        assert!(recompute(&status).is_err());

        let mut measurement = all_gap();
        measurement[1].price_base_atoms = Some(7);
        assert!(recompute(&measurement).is_err());

        let mut clock = all_gap();
        clock[1].observed_at = instant("2026-08-18T00:00:00.000001Z");
        clock[1].event_time = instant("2026-08-18T00:00:00.000002Z");
        assert!(recompute(&clock).is_err());
    }
}
