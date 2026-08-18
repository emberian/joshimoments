use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::str::FromStr as _;

use base64::Engine as _;
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::value::RawValue;
use thiserror::Error;

use crate::catalog::RouteId;
use crate::client::sha256;
use crate::model::{Acquisition, BodyCapture, FidelityGap};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SchemaRegistry {
    pub contract: String,
    pub accepted: BTreeMap<String, BTreeSet<String>>,
}

impl SchemaRegistry {
    /// Strictly parse a reviewed schema registry.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid JSON, duplicate fields, unknown fields, or the wrong contract.
    pub fn from_slice(bytes: &[u8]) -> Result<Self, NormalizeError> {
        reject_duplicate_keys(bytes)?;
        let registry: Self = serde_json::from_slice(bytes)?;
        if registry.contract != "joshi.pump_api.schema_registry.v1" {
            return Err(NormalizeError::RegistryContract);
        }
        Ok(registry)
    }

    #[must_use]
    pub fn accepts(&self, route: RouteId, fingerprint: &str) -> bool {
        self.accepted
            .get(&route.to_string())
            .is_some_and(|fingerprints| fingerprints.contains(fingerprint))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TaggedScalar {
    pub field: String,
    pub encoding: String,
    pub value: Option<String>,
    pub semantics: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NormalizedRecord {
    pub acquisition_id: String,
    pub ordinal: String,
    pub exact_row_blob_id: String,
    pub fields: Vec<TaggedScalar>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PageObservation {
    pub item_count: String,
    pub next_cursor_fingerprint: Option<String>,
    pub completion_claim: String,
    pub order_claim: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Normalization {
    pub contract: String,
    pub acquisition_id: String,
    pub route_id: String,
    pub disposition: String,
    pub schema_fingerprint: Option<String>,
    pub records: Vec<NormalizedRecord>,
    pub page: Option<PageObservation>,
    pub fidelity_gaps: Vec<FidelityGap>,
}

#[derive(Error, Debug)]
pub enum NormalizeError {
    #[error("invalid JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("schema registry contract/version is not joshi.pump_api.schema_registry.v1")]
    RegistryContract,
    #[error("duplicate object key {0:?}")]
    DuplicateKey(String),
    #[error("JSON nesting exceeds the normalizer limit")]
    Depth,
    #[error("unknown route ID in acquisition: {0}")]
    Route(String),
}

/// Normalize one exact response only after its exact observed schema has been reviewed and
/// promoted. A quarantine still retains the acquisition bytes; it emits no trusted records.
#[must_use]
pub fn normalize(acquisition: &Acquisition, registry: &SchemaRegistry) -> Normalization {
    match normalize_inner(acquisition, registry) {
        Ok(value) => value,
        Err(error) => Normalization {
            contract: "joshi.pump_api.normalization.v1".to_owned(),
            acquisition_id: acquisition.acquisition_id.clone(),
            route_id: acquisition.route_id.clone(),
            disposition: "quarantined_parse_or_contract_error".to_owned(),
            schema_fingerprint: None,
            records: Vec::new(),
            page: None,
            fidelity_gaps: vec![FidelityGap {
                code: "normalization_error".to_owned(),
                detail: error.to_string(),
                acquisition_id: acquisition.acquisition_id.clone(),
            }],
        },
    }
}

fn normalize_inner(
    acquisition: &Acquisition,
    registry: &SchemaRegistry,
) -> Result<Normalization, NormalizeError> {
    let route = RouteId::from_str(&acquisition.route_id)
        .map_err(|_| NormalizeError::Route(acquisition.route_id.clone()))?;
    let BodyCapture::Exact {
        bytes_base64,
        byte_length,
        blob_id,
        ..
    } = &acquisition.body
    else {
        return Ok(quarantine(
            acquisition,
            "non_exact_body",
            "normalization requires a complete exact response body",
            None,
        ));
    };
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(bytes_base64)
        .map_err(|error| {
            serde_json::Error::io(std::io::Error::new(std::io::ErrorKind::InvalidData, error))
        })?;
    if byte_length != &bytes.len().to_string() || blob_id != &sha256(&bytes) {
        return Ok(quarantine(
            acquisition,
            "body_identity_mismatch",
            "declared body length or digest does not match exact bytes",
            None,
        ));
    }
    if !acquisition
        .http_status
        .is_some_and(|status| (200..300).contains(&status))
    {
        return Ok(quarantine(
            acquisition,
            "non_success_status",
            "HTTP error response retained but not normalized as provider records",
            None,
        ));
    }
    reject_duplicate_keys(&bytes)?;
    let raw: Box<RawValue> = serde_json::from_slice(&bytes)?;
    let schema = schema_fingerprint(&raw)?;
    if !registry.accepts(route, &schema) {
        return Ok(quarantine(
            acquisition,
            "unpromoted_schema",
            "exact bytes retained; schema must be reviewed and added to the registry",
            Some(schema),
        ));
    }
    let rows = records(route, &raw)?;
    let normalized = rows
        .iter()
        .enumerate()
        .map(|(ordinal, row)| normalize_record(acquisition, route, ordinal, row))
        .collect::<Result<Vec<_>, _>>()?;
    let cursor = next_cursor(&raw)?;
    Ok(Normalization {
        contract: "joshi.pump_api.normalization.v1".to_owned(),
        acquisition_id: acquisition.acquisition_id.clone(),
        route_id: acquisition.route_id.clone(),
        disposition: "accepted_provider_assertions".to_owned(),
        schema_fingerprint: Some(schema),
        page: Some(PageObservation {
            item_count: normalized.len().to_string(),
            next_cursor_fingerprint: cursor.map(|value| sha256(value.as_bytes())),
            completion_claim: "unknown_not_inferred_from_page_length".to_owned(),
            order_claim: crate::catalog::RouteSpec::for_id(route).ordering.to_owned(),
        }),
        records: normalized,
        fidelity_gaps: Vec::new(),
    })
}

fn quarantine(
    acquisition: &Acquisition,
    code: &str,
    detail: &str,
    schema_fingerprint: Option<String>,
) -> Normalization {
    Normalization {
        contract: "joshi.pump_api.normalization.v1".to_owned(),
        acquisition_id: acquisition.acquisition_id.clone(),
        route_id: acquisition.route_id.clone(),
        disposition: "quarantined".to_owned(),
        schema_fingerprint,
        records: Vec::new(),
        page: None,
        fidelity_gaps: vec![FidelityGap {
            code: code.to_owned(),
            detail: detail.to_owned(),
            acquisition_id: acquisition.acquisition_id.clone(),
        }],
    }
}

pub(crate) fn records(
    route: RouteId,
    root: &RawValue,
) -> Result<Vec<Box<RawValue>>, NormalizeError> {
    match route {
        RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch
        | RouteId::UserSearch
        | RouteId::Following => raw_array(root),
        RouteId::CalloutRecent | RouteId::CalloutTop | RouteId::CalloutByMint => {
            nested_array(root, &["callouts", "data"])
        }
        RouteId::BalanceTokens => nested_array(root, &["tokens", "data"]),
        RouteId::CommunityMessages => nested_array(root, &["messages", "data"]),
        RouteId::CommunityCallouts => nested_array(root, &["callouts", "data"]),
        RouteId::Candles | RouteId::Trades => nested_array(root, &["candles", "trades", "data"]),
        RouteId::LiveChat => Ok(Vec::new()),
        RouteId::CoinExact | RouteId::SolPrice | RouteId::BalanceSummary | RouteId::UserProfile => {
            Ok(vec![root.to_owned()])
        }
    }
}

fn nested_array(
    root: &RawValue,
    candidates: &[&str],
) -> Result<Vec<Box<RawValue>>, NormalizeError> {
    let object = raw_object(root)?;
    for candidate in candidates {
        if let Some(value) = object.get(*candidate) {
            if value.get().trim_start().starts_with('[') {
                return raw_array(value);
            }
            if value.get().trim_start().starts_with('{') {
                let nested = raw_object(value)?;
                for nested_key in candidates {
                    if let Some(array) = nested.get(*nested_key)
                        && array.get().trim_start().starts_with('[')
                    {
                        return raw_array(array);
                    }
                }
            }
        }
    }
    Ok(Vec::new())
}

fn normalize_record(
    acquisition: &Acquisition,
    route: RouteId,
    ordinal: usize,
    raw: &RawValue,
) -> Result<NormalizedRecord, NormalizeError> {
    let fields = if raw.get().trim_start().starts_with('{') {
        let object = raw_object(raw)?;
        allowed_fields(route)
            .iter()
            .filter_map(|field| {
                object
                    .get(*field)
                    .and_then(|value| tagged_scalar(field, value))
            })
            .collect()
    } else {
        Vec::new()
    };
    Ok(NormalizedRecord {
        acquisition_id: acquisition.acquisition_id.clone(),
        ordinal: ordinal.to_string(),
        exact_row_blob_id: sha256(raw.get().as_bytes()),
        fields,
    })
}

#[allow(clippy::too_many_lines)] // Auditable field policy is intentionally centralized by route.
fn allowed_fields(route: RouteId) -> &'static [&'static str] {
    match route {
        RouteId::CoinExact
        | RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch => &[
            "mint",
            "name",
            "symbol",
            "creator",
            "complete",
            "created_timestamp",
            "last_trade_timestamp",
            "virtual_quote_reserves",
            "virtual_sol_reserves",
            "virtual_token_reserves",
            "real_quote_reserves",
            "real_sol_reserves",
            "real_token_reserves",
            "market_cap",
            "market_cap_quote",
            "market_cap_usd",
            "usd_market_cap",
            "reply_count",
            "token_program",
            "quote_mint",
            "program",
            "protocol",
            "is_currently_live",
            "verified",
            "updated_at",
        ],
        RouteId::SolPrice => &["solPrice", "asOfTimestamp", "stale"],
        RouteId::BalanceSummary | RouteId::BalanceTokens => &[
            "mint",
            "balance",
            "amount",
            "decimals",
            "usdValue",
            "totalValue",
            "updatedAt",
        ],
        RouteId::CalloutRecent
        | RouteId::CalloutTop
        | RouteId::CalloutByMint
        | RouteId::CommunityCallouts => &[
            "calloutId",
            "userId",
            "user_uuid",
            "walletAddress",
            "username",
            "xUsername",
            "coinMint",
            "thesis",
            "createdAt",
            "calloutTimestamp",
            "calloutPrice",
            "marketCap",
            "calledOutAtMcap",
            "multiple",
            "maxMultiplier",
            "maxPriceSol",
            "peakTimestamp",
            "likes",
            "commentCount",
            "replyCount",
        ],
        RouteId::UserSearch | RouteId::UserProfile | RouteId::Following => &[
            "address",
            "userId",
            "username",
            "displayName",
            "followers",
            "followerCount",
            "nativeFollowerCount",
            "timestamp",
            "last_username_update_timestamp",
            "xUsername",
            "twitterId",
        ],
        RouteId::CommunityMessages => &[
            "id",
            "userId",
            "walletAddress",
            "username",
            "content",
            "createdAt",
            "likeCount",
            "replyCount",
            "parentMessageId",
            "parentCalloutId",
            "isSpam",
            "isHarmful",
        ],
        RouteId::Candles | RouteId::Trades => &[
            "timestamp",
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "price",
            "amount",
            "signature",
            "wallet",
            "mint",
        ],
        RouteId::LiveChat => &[],
    }
}

fn tagged_scalar(field: &str, raw: &RawValue) -> Option<TaggedScalar> {
    let source = raw.get().trim();
    let (encoding, value) = match source.as_bytes().first().copied()? {
        b'"' => ("utf8", Some(serde_json::from_str::<String>(source).ok()?)),
        b't' | b'f' => ("boolean", Some(source.to_owned())),
        b'n' if source == "null" => ("null", None),
        b'-' | b'0'..=b'9' => ("json_number_lexeme", Some(source.to_owned())),
        _ => return None,
    };
    Some(TaggedScalar {
        field: field.to_owned(),
        encoding: encoding.to_owned(),
        value,
        semantics: semantics(field).to_owned(),
    })
}

fn semantics(field: &str) -> &'static str {
    match field {
        "mint" | "creator" | "coinMint" | "address" | "userId" | "user_uuid" | "walletAddress"
        | "calloutId" | "id" | "signature" => "provider_identifier",
        "createdAt" | "created_timestamp" | "calloutTimestamp" | "timestamp" | "time" => {
            "provider_event_time_unparsed"
        }
        "multiple" | "maxMultiplier" | "maxPriceSol" | "peakTimestamp" => {
            "retrospective_outcome_as_of_acquisition_never_pre_event_feature"
        }
        "thesis" | "content" => "untrusted_user_content",
        _ => "provider_current_assertion",
    }
}

pub(crate) fn next_cursor(root: &RawValue) -> Result<Option<String>, NormalizeError> {
    if !root.get().trim_start().starts_with('{') {
        return Ok(None);
    }
    let object = raw_object(root)?;
    for key in ["nextPageToken", "nextCursor", "cursor"] {
        if let Some(value) = object.get(key) {
            let source = value.get().trim();
            if source == "null" || source == r#"""# {
                return Ok(None);
            }
            if source.starts_with('"') {
                return serde_json::from_str(source).map(Some).map_err(Into::into);
            }
            return Ok(Some(source.to_owned()));
        }
    }
    Ok(None)
}

/// Hash a bounded, path-and-type structural signature without scalar values.
///
/// # Errors
///
/// Returns an error for invalid nested JSON or nesting beyond the normalizer limit.
pub fn schema_fingerprint(root: &RawValue) -> Result<String, NormalizeError> {
    let mut shape = BTreeSet::new();
    collect_shape(root, "$", 0, &mut shape)?;
    let canonical = shape.into_iter().collect::<Vec<_>>().join("\n");
    Ok(sha256(canonical.as_bytes()))
}

fn collect_shape(
    raw: &RawValue,
    pointer: &str,
    depth: usize,
    shape: &mut BTreeSet<String>,
) -> Result<(), NormalizeError> {
    if depth > 64 {
        return Err(NormalizeError::Depth);
    }
    let source = raw.get().trim_start();
    match source.as_bytes().first().copied() {
        Some(b'{') => {
            shape.insert(format!("{pointer}:object"));
            for (key, value) in raw_object(raw)? {
                collect_shape(
                    &value,
                    &format!("{pointer}/{}", escape_pointer(&key)),
                    depth + 1,
                    shape,
                )?;
            }
        }
        Some(b'[') => {
            shape.insert(format!("{pointer}:array"));
            for value in raw_array(raw)? {
                collect_shape(&value, &format!("{pointer}/*"), depth + 1, shape)?;
            }
        }
        Some(b'"') => {
            shape.insert(format!("{pointer}:string"));
        }
        Some(b't' | b'f') => {
            shape.insert(format!("{pointer}:boolean"));
        }
        Some(b'n') => {
            shape.insert(format!("{pointer}:null"));
        }
        Some(b'-' | b'0'..=b'9') => {
            shape.insert(format!("{pointer}:number"));
        }
        _ => {
            return Err(serde_json::from_str::<serde_json::Value>(source)
                .unwrap_err()
                .into());
        }
    }
    Ok(())
}

fn escape_pointer(value: &str) -> String {
    value.replace('~', "~0").replace('/', "~1")
}

fn raw_object(raw: &RawValue) -> Result<BTreeMap<String, Box<RawValue>>, NormalizeError> {
    serde_json::from_str(raw.get()).map_err(Into::into)
}

fn raw_array(raw: &RawValue) -> Result<Vec<Box<RawValue>>, NormalizeError> {
    serde_json::from_str(raw.get()).map_err(Into::into)
}

/// Validate JSON while rejecting duplicate object keys at every depth.
///
/// # Errors
///
/// Returns an error for invalid JSON or any duplicate object key.
pub fn reject_duplicate_keys(bytes: &[u8]) -> Result<(), NormalizeError> {
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    DuplicateSafe::deserialize(&mut deserializer)?;
    deserializer.end()?;
    Ok(())
}

struct DuplicateSafe;

impl<'de> Deserialize<'de> for DuplicateSafe {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(DuplicateVisitor)
    }
}

struct DuplicateVisitor;

impl<'de> Visitor<'de> for DuplicateVisitor {
    type Value = DuplicateSafe;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("valid JSON without duplicate object keys")
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut keys = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !keys.insert(key.clone()) {
                return Err(serde::de::Error::custom(format!(
                    "duplicate object key {key:?}"
                )));
            }
            map.next_value::<DuplicateSafe>()?;
        }
        Ok(DuplicateSafe)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        while sequence.next_element::<DuplicateSafe>()?.is_some() {}
        Ok(DuplicateSafe)
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_i64<E>(self, _value: i64) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_u64<E>(self, _value: u64) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_f64<E>(self, _value: f64) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_str<E>(self, _value: &str) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_string<E>(self, _value: String) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        DuplicateSafe::deserialize(deserializer)
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(DuplicateSafe)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_duplicate_keys_at_any_depth() {
        let error = reject_duplicate_keys(br#"{"outer":{"same":1,"same":2}}"#).unwrap_err();
        assert!(error.to_string().contains("duplicate object key"));
    }

    #[test]
    fn tagged_numbers_keep_the_exact_json_lexeme() {
        let raw: Box<RawValue> = serde_json::from_str("1.2300e-7").unwrap();
        let value = tagged_scalar("calloutPrice", &raw).unwrap();
        assert_eq!(value.encoding, "json_number_lexeme");
        assert_eq!(value.value.as_deref(), Some("1.2300e-7"));
    }
}
