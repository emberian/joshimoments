use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;

use crate::client::sha256;
use crate::normalize::{reject_duplicate_keys, schema_fingerprint};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParityInput {
    pub contract: String,
    pub source: String,
    pub route_id: String,
    pub catalog_version: String,
    pub request_fingerprint: String,
    pub session_class: String,
    pub comparison_boundary: String,
    pub observed_at: String,
    pub body_base64: String,
    pub byte_length: String,
    pub blob_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParityDifference {
    pub pointer: String,
    pub companion_kind: String,
    pub direct_kind: String,
    pub companion_value_digest: String,
    pub direct_value_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ParityReport {
    pub contract: String,
    pub disposition: String,
    pub precondition_failures: Vec<String>,
    pub companion_blob_id: String,
    pub direct_blob_id: String,
    pub companion_schema_fingerprint: Option<String>,
    pub direct_schema_fingerprint: Option<String>,
    pub differences: Vec<ParityDifference>,
    pub differences_truncated: bool,
}

/// Compare a companion-observed official response with a direct response. The protocol proves
/// exact equality or reports bounded field differences; it never treats a nearby dynamic response
/// as the same occurrence or claims feed coverage from one pair.
#[must_use]
pub fn compare(
    companion: &ParityInput,
    direct: &ParityInput,
    max_differences: usize,
) -> ParityReport {
    let mut failures = Vec::new();
    if companion.contract != "joshi.pump_api.parity_input.v1"
        || direct.contract != "joshi.pump_api.parity_input.v1"
    {
        failures.push("contract_version".to_owned());
    }
    for (name, left, right) in [
        ("route_id", &companion.route_id, &direct.route_id),
        (
            "catalog_version",
            &companion.catalog_version,
            &direct.catalog_version,
        ),
        (
            "request_fingerprint",
            &companion.request_fingerprint,
            &direct.request_fingerprint,
        ),
        (
            "session_class",
            &companion.session_class,
            &direct.session_class,
        ),
        (
            "comparison_boundary",
            &companion.comparison_boundary,
            &direct.comparison_boundary,
        ),
    ] {
        if left != right {
            failures.push(name.to_owned());
        }
    }
    let companion_bytes = verified_bytes(companion, "companion", &mut failures);
    let direct_bytes = verified_bytes(direct, "direct", &mut failures);
    let mut report = ParityReport {
        contract: "joshi.pump_api.parity_report.v1".to_owned(),
        disposition: "incomparable".to_owned(),
        precondition_failures: failures,
        companion_blob_id: companion.blob_id.clone(),
        direct_blob_id: direct.blob_id.clone(),
        companion_schema_fingerprint: None,
        direct_schema_fingerprint: None,
        differences: Vec::new(),
        differences_truncated: false,
    };
    if !report.precondition_failures.is_empty() {
        return report;
    }
    let (Some(companion_bytes), Some(direct_bytes)) = (companion_bytes, direct_bytes) else {
        return report;
    };
    if companion_bytes == direct_bytes {
        "exact_bytes_equal".clone_into(&mut report.disposition);
        return report;
    }
    if reject_duplicate_keys(&companion_bytes).is_err()
        || reject_duplicate_keys(&direct_bytes).is_err()
    {
        "quarantined_invalid_or_duplicate_key_json".clone_into(&mut report.disposition);
        return report;
    }
    let Ok(companion_raw) = serde_json::from_slice::<Box<RawValue>>(&companion_bytes) else {
        "quarantined_invalid_json".clone_into(&mut report.disposition);
        return report;
    };
    let Ok(direct_raw) = serde_json::from_slice::<Box<RawValue>>(&direct_bytes) else {
        "quarantined_invalid_json".clone_into(&mut report.disposition);
        return report;
    };
    report.companion_schema_fingerprint = schema_fingerprint(&companion_raw).ok();
    report.direct_schema_fingerprint = schema_fingerprint(&direct_raw).ok();
    let limit = max_differences.max(1);
    diff_raw(
        &companion_raw,
        &direct_raw,
        "$",
        &mut report.differences,
        limit,
        &mut report.differences_truncated,
    );
    if report.differences.is_empty() {
        "json_semantic_equal_exact_bytes_differ"
    } else {
        "comparable_response_difference"
    }
    .clone_into(&mut report.disposition);
    report
}

fn verified_bytes(input: &ParityInput, side: &str, failures: &mut Vec<String>) -> Option<Vec<u8>> {
    use base64::Engine as _;
    let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(&input.body_base64) else {
        failures.push(format!("{side}_base64"));
        return None;
    };
    if input.byte_length != bytes.len().to_string() {
        failures.push(format!("{side}_byte_length"));
    }
    if input.blob_id != sha256(&bytes) {
        failures.push(format!("{side}_blob_id"));
    }
    Some(bytes)
}

pub(crate) fn diff_raw(
    left: &RawValue,
    right: &RawValue,
    pointer: &str,
    differences: &mut Vec<ParityDifference>,
    limit: usize,
    truncated: &mut bool,
) {
    if differences.len() >= limit {
        *truncated = true;
        return;
    }
    let left_kind = kind(left);
    let right_kind = kind(right);
    if left_kind != right_kind {
        push_difference(left, right, pointer, differences);
        return;
    }
    match left_kind {
        "object" => {
            let Ok(left_map) = serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(left.get())
            else {
                push_difference(left, right, pointer, differences);
                return;
            };
            let Ok(right_map) =
                serde_json::from_str::<BTreeMap<String, Box<RawValue>>>(right.get())
            else {
                push_difference(left, right, pointer, differences);
                return;
            };
            let keys = left_map
                .keys()
                .chain(right_map.keys())
                .cloned()
                .collect::<BTreeSet<_>>();
            for key in keys {
                let child = format!("{pointer}/{}", key.replace('~', "~0").replace('/', "~1"));
                match (left_map.get(&key), right_map.get(&key)) {
                    (Some(left), Some(right)) => {
                        diff_raw(left, right, &child, differences, limit, truncated);
                    }
                    (Some(left), None) => push_missing(left, "missing", &child, true, differences),
                    (None, Some(right)) => {
                        push_missing(right, "missing", &child, false, differences);
                    }
                    (None, None) => {}
                }
                if differences.len() >= limit {
                    *truncated = true;
                    return;
                }
            }
        }
        "array" => {
            let Ok(left_items) = serde_json::from_str::<Vec<Box<RawValue>>>(left.get()) else {
                push_difference(left, right, pointer, differences);
                return;
            };
            let Ok(right_items) = serde_json::from_str::<Vec<Box<RawValue>>>(right.get()) else {
                push_difference(left, right, pointer, differences);
                return;
            };
            for index in 0..left_items.len().max(right_items.len()) {
                let child = format!("{pointer}/{index}");
                match (left_items.get(index), right_items.get(index)) {
                    (Some(left), Some(right)) => {
                        diff_raw(left, right, &child, differences, limit, truncated);
                    }
                    (Some(left), None) => push_missing(left, "missing", &child, true, differences),
                    (None, Some(right)) => {
                        push_missing(right, "missing", &child, false, differences);
                    }
                    (None, None) => {}
                }
                if differences.len() >= limit {
                    *truncated = true;
                    return;
                }
            }
        }
        "string" => {
            let left_value = serde_json::from_str::<String>(left.get()).ok();
            let right_value = serde_json::from_str::<String>(right.get()).ok();
            if left_value != right_value {
                push_difference(left, right, pointer, differences);
            }
        }
        _ if left.get() != right.get() => push_difference(left, right, pointer, differences),
        _ => {}
    }
}

fn push_difference(
    left: &RawValue,
    right: &RawValue,
    pointer: &str,
    differences: &mut Vec<ParityDifference>,
) {
    differences.push(ParityDifference {
        pointer: pointer.to_owned(),
        companion_kind: kind(left).to_owned(),
        direct_kind: kind(right).to_owned(),
        companion_value_digest: sha256(left.get().as_bytes()),
        direct_value_digest: sha256(right.get().as_bytes()),
    });
}

fn push_missing(
    present: &RawValue,
    missing_kind: &str,
    pointer: &str,
    left_present: bool,
    differences: &mut Vec<ParityDifference>,
) {
    let missing_digest = sha256(b"<missing>");
    let present_digest = sha256(present.get().as_bytes());
    differences.push(ParityDifference {
        pointer: pointer.to_owned(),
        companion_kind: if left_present {
            kind(present)
        } else {
            missing_kind
        }
        .to_owned(),
        direct_kind: if left_present {
            missing_kind
        } else {
            kind(present)
        }
        .to_owned(),
        companion_value_digest: if left_present {
            present_digest.clone()
        } else {
            missing_digest.clone()
        },
        direct_value_digest: if left_present {
            missing_digest
        } else {
            present_digest
        },
    });
}

fn kind(raw: &RawValue) -> &'static str {
    match raw.get().trim_start().as_bytes().first().copied() {
        Some(b'{') => "object",
        Some(b'[') => "array",
        Some(b'"') => "string",
        Some(b't' | b'f') => "boolean",
        Some(b'n') => "null",
        Some(b'-' | b'0'..=b'9') => "number",
        _ => "invalid",
    }
}
