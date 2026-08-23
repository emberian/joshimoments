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
use crate::row_projection::RowProjectionReviewV1;
use crate::trust::SchemaTrustOutcome;

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
    match normalize_inner(acquisition, Gate::Registry(registry)) {
        Ok(value) => value,
        Err(error) => parse_failure(acquisition, &error),
    }
}

fn parse_failure(acquisition: &Acquisition, error: &NormalizeError) -> Normalization {
    Normalization {
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
    }
}

/// Normalize one exact response whose ROWS a reviewer has promoted, rather than whose whole
/// document digest they have.
///
/// This is the entry point for a collection route with heterogeneous rows, where the
/// whole-document fingerprint is a function of which records landed in the page and therefore
/// cannot gate anything. The row gate refuses on a missing required leaf, an unreviewed wire type
/// or an unreviewed leaf, and the refusal reaches the caller as a named fidelity gap rather than
/// as silence.
#[must_use]
pub fn normalize_with_row_projection(
    acquisition: &Acquisition,
    review: &RowProjectionReviewV1,
) -> Normalization {
    match normalize_inner(acquisition, Gate::RowProjection(review)) {
        Ok(value) => value,
        Err(error) => parse_failure(acquisition, &error),
    }
}

/// What a normalization is allowed to trust. Neither variant can be constructed by default: a
/// caller has to name the reviewed artifact it is relying on.
#[derive(Clone, Copy)]
enum Gate<'a> {
    /// One digest over the whole document, as reviewed for a single-record or homogeneous route.
    Registry(&'a SchemaRegistry),
    /// A required and a closed optional leaf set, checked on every row.
    RowProjection(&'a RowProjectionReviewV1),
}

fn normalize_inner(
    acquisition: &Acquisition,
    gate: Gate<'_>,
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
    match gate {
        Gate::Registry(registry) => {
            if !registry.accepts(route, &schema) {
                return Ok(quarantine(
                    acquisition,
                    "unpromoted_schema",
                    "exact bytes retained; schema must be reviewed and added to the registry",
                    Some(schema),
                ));
            }
        }
        Gate::RowProjection(review) => {
            // The whole-document fingerprint above is still computed and still travels on the
            // quarantine below, because it is a usable drift signal. It is simply not what
            // decides anything here.
            let decision = crate::row_projection::decide_row_projection_trust(
                acquisition,
                Some(review),
                &acquisition.clocks.received_at,
            )
            .map_err(|error| NormalizeError::Route(error.to_string()))?;
            if decision.outcome != SchemaTrustOutcome::Promoted {
                return Ok(quarantine(
                    acquisition,
                    &decision.reason_code,
                    &decision.detail,
                    Some(schema),
                ));
            }
        }
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
        // Candles was measured live 2026-08-22 and is a bare top-level JSON array, exactly like
        // the discovery feeds; trades is an object carrying a `trades` array beside a
        // `pagination` object. A single shared guess at ["candles","trades","data"] covered
        // neither and silently produced zero candle rows out of a 1000-row body.
        //
        // Measured live 2026-08-22: /coins, /coins/currently-live and /coins/search-unrestricted
        // are each a BARE top-level JSON array, so `raw_array` is right for all three by
        // measurement rather than by family resemblance.
        RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch
        | RouteId::Candles => raw_array(root),
        // STILL UNMEASURED. Nothing has ever called these two, so `raw_array` here is a guess of
        // exactly the kind that read a 1000-row candle body as zero rows. Both routes are
        // un-collectable in the pinned catalog; the first live call must re-measure this arm
        // before anything downstream believes a row count from it.
        RouteId::UserSearch | RouteId::Following => unmeasured_bare_array_guess(root),
        RouteId::Trades => nested_array(root, &["trades"]),
        // Measured live 2026-08-22 against a busy mint: /callout/top/{mint} answers
        // {"callouts":[...]} and /callout/list/{mint} answers {"callouts":[],"nextPageToken":""},
        // so the envelope key was predicted correctly for both. /callout/recent is not a route at
        // all — see the catalog — and can never reach this arm with a body to read.
        RouteId::CalloutRecent | RouteId::CalloutTop | RouteId::CalloutByUser => {
            nested_array(root, &["callouts", "data"])
        }
        // Measured live 2026-08-23 authenticated: the envelope key is {"callouts":[...]} — the
        // same key the per-mint and per-user callout routes use — but the rows are CALLERS, not
        // callouts: each carries userId, wallets, a topCallouts array, and the provider's own
        // aggregate score fields (totalCallouts, avgMultiple, medianMultiple, averageTimeToPeak).
        // The top-level records are therefore the caller rows.
        RouteId::CalloutLeaderboard => nested_array(root, &["callouts"]),
        RouteId::BalanceTokens => nested_array(root, &["tokens", "data"]),
        RouteId::CommunityMessages => nested_array(root, &["messages", "data"]),
        RouteId::CommunityCallouts => nested_array(root, &["callouts", "data"]),
        RouteId::LiveChat => Ok(Vec::new()),
        RouteId::CoinExact | RouteId::SolPrice | RouteId::BalanceSummary | RouteId::UserProfile => {
            Ok(vec![root.to_owned()])
        }
    }
}

/// The same reader as the measured bare-array arm, under a name that says it is a guess.
///
/// It exists so that a lint, or a later reader in a hurry, cannot merge an arm that was checked
/// against real provider bytes into one that never has been. Both routes are un-collectable in
/// the pinned catalog; the first live call must replace this with a measurement.
fn unmeasured_bare_array_guess(root: &RawValue) -> Result<Vec<Box<RawValue>>, NormalizeError> {
    raw_array(root)
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
        // A coin's `complete` flag decides whether its reserve numbers mean anything at all, so
        // it is read once here and travels into every field's semantics. See `reserve_semantics`.
        let bonded = object
            .get("complete")
            .and_then(|value| match value.get().trim() {
                "true" => Some(true),
                "false" => Some(false),
                _ => None,
            });
        allowed_fields(route)
            .iter()
            .filter_map(|field| {
                object
                    .get(*field)
                    .and_then(|value| tagged_scalar(route, field, value, bonded))
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

/// The exact projection this crate extracts from a row of `route`.
///
/// Exposed inside the crate so that a row-projection review cannot REQUIRE a leaf the normalizer
/// never reads. Requiring an unread field buys nothing and costs a refusal every time the provider
/// omits it on some rare row, which turns a fail-closed gate into noise; requiring a field we DO
/// read is what makes a refusal mean something went missing from the projection.
pub(crate) fn extracted_fields(route: RouteId) -> &'static [&'static str] {
    allowed_fields(route)
}

#[allow(clippy::too_many_lines)]
// Auditable field policy is intentionally centralized by route.
// The measured callout arm and the never-called CommunityCallouts arm coincide today, and that
// coincidence is empirical rather than structural: one list came from live bytes, the other is a
// prediction awaiting its first call. Merging them (what the lint wants) would couple them so a
// future re-measurement of one silently rewrites the other.
#[expect(
    clippy::match_same_arms,
    reason = "identical bodies are separate measurements"
)]
fn allowed_fields(route: RouteId) -> &'static [&'static str] {
    match route {
        // Every name below was seen in a live 2026-08-22 body on at least one of these four
        // routes; extraction is presence-filtered, so a route that does not carry one simply has
        // no such field rather than a null. What the earlier list was MISSING, measured:
        //
        //   ath_market_cap / ath_market_cap_timestamp — present on /coins, on
        //     /coins/currently-live AND on the already-promoted /coins-v2/{mint}, and silently
        //     dropped from all three. It is the only within-lifetime peak this provider exposes,
        //     and the pair with usd_market_cap is the one drawdown signal a SINGLE snapshot can
        //     support.
        //   volume_1h_usd — /coins/search-unrestricted only, and the only realised-flow number
        //     anywhere in this catalog.
        //   num_participants — /coins/currently-live only; a live audience count.
        //   last_reply / king_of_the_hill_timestamp — present on some rows only.
        //   total_supply / total_supply_str / base_decimals / quote_decimals — needed before any
        //     market cap can be turned into a per-token price; `total_supply` is a JSON number
        //     and `total_supply_str` the same quantity as a string, so both are retained and
        //     neither is preferred here.
        //   bonding_curve / associated_bonding_curve / pool_address / pump_swap_pool — the venue
        //     a coin actually trades on, which `complete` alone does not identify.
        //   nsfw / is_banned / boost_mode / mayhem_state / inverted — provider flags that gate
        //     whether a coin is tradeable or promoted at all.
        //
        // Free text and media URLs (description, image_uri, twitter, website, telegram, username,
        // livestream_title, thumbnails, playlist URLs) are deliberately NOT extracted. They are
        // untrusted user content, they are in the retained exact bytes for anyone who needs them,
        // and none of them is a decision input.
        RouteId::CoinExact
        | RouteId::DiscoveryCoins
        | RouteId::CurrentlyLive
        | RouteId::CoinSearch => &[
            "mint",
            "name",
            "symbol",
            "creator",
            "complete",
            "initialized",
            "created_timestamp",
            "last_trade_timestamp",
            "updated_at",
            "ath_market_cap",
            "ath_market_cap_timestamp",
            "king_of_the_hill_timestamp",
            "last_reply",
            "reply_count",
            "volume_1h_usd",
            "num_participants",
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
            "total_supply",
            "total_supply_str",
            "base_decimals",
            "quote_decimals",
            "bonding_curve",
            "associated_bonding_curve",
            "pool_address",
            "pump_swap_pool",
            "token_program",
            "quote_mint",
            "chain_id",
            "multichain_family",
            "program",
            "protocol",
            "is_currently_live",
            "verified",
            "nsfw",
            "is_banned",
            "inverted",
            "boost_mode",
            "mayhem_state",
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
        // MEASURED 2026-08-22 over 3 rows of /callout/top/{mint} and 58 rows of
        // /callout/list/{user} from 8 callers. Every name below was seen on at least one of those
        // routes; extraction is presence-filtered, so a route that does not carry one simply has
        // no such field. `walletAddress`, `calloutTimestamp` and `calledOutAtMcap` were in the
        // earlier guessed list and appear on NEITHER route, so they are gone.
        //
        // Deliberately NOT extracted, and all of it still in the retained exact bytes: `thesis`
        // (untrusted free text and the one thing a caller controls), `mediaUrl`, `username`,
        // `xUsername` and `profileImage` (user content), `updates` (an array, never a scalar), and
        // `hasLiked`/`hasReposted`, which were null on all 58 rows because they are relative to a
        // viewer this client deliberately does not have.
        RouteId::CalloutRecent | RouteId::CalloutTop | RouteId::CalloutByUser => &[
            "calloutId",
            "userId",
            "user_uuid",
            "coinMint",
            "createdAt",
            "calloutPrice",
            "calloutPriceUsd",
            "marketCap",
            "multiple",
            "maxPriceSol",
            "maxPriceUsd",
            "maxMultiplier",
            "maxMultiplierAt",
            "peakTimestamp",
            "likes",
            "viewCount",
            "commentCount",
            "replyCount",
            "repostCount",
            "quoteCount",
            "updateCount",
        ],
        // Measured live 2026-08-23 authenticated: a leaderboard row is a CALLER. Its scalar
        // fields are caller identity plus the provider's own retrospective aggregate score over
        // that caller's history, and those are exactly what the caller-signal question reads. The
        // `topCallouts` and `wallets` arrays are NOT descended into here — they stay whole in the
        // retained bytes for a later reviewed projection — so they are optional in the row review
        // rather than extracted scalars. Every score field is a look-ahead outcome as of the read.
        RouteId::CalloutLeaderboard => &[
            "userId",
            "user_uuid",
            "primaryWallet",
            "totalCallouts",
            "avgMultiple",
            "medianMultiple",
            "pct2xOrMore",
            "onePointFiveXPercent",
            "onePointTwoXPercent",
            "averageTimeToPeak",
        ],
        // The same names under a route NOTHING has ever called. It is a separate arm so that a
        // later reader cannot mistake this list for a measurement: `profile-api.pump.fun` is a
        // different host behind a different session class, and its callout rows have never been
        // seen. The first live call must re-measure this before anything believes a field of it.
        RouteId::CommunityCallouts => &[
            "calloutId",
            "userId",
            "user_uuid",
            "coinMint",
            "createdAt",
            "calloutPrice",
            "calloutPriceUsd",
            "marketCap",
            "multiple",
            "maxPriceSol",
            "maxPriceUsd",
            "maxMultiplier",
            "maxMultiplierAt",
            "peakTimestamp",
            "likes",
            "viewCount",
            "commentCount",
            "replyCount",
            "repostCount",
            "quoteCount",
            "updateCount",
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
        // Measured field names, not guessed ones. Every OHLCV value arrives as a decimal
        // string, so it is retained verbatim rather than parsed here.
        RouteId::Candles => &["timestamp", "open", "high", "low", "close", "volume"],
        // `priceUsd`/`priceSol` are the pool price the trade printed at; `fillPrice*` is what
        // the taker actually paid, so the pair carries the venue fee and is kept as a pair.
        RouteId::Trades => &[
            "slotIndexId",
            "tx",
            "timestamp",
            "userAddress",
            "type",
            "program",
            "priceUsd",
            "priceSol",
            "amountUsd",
            "amountSol",
            "baseAmount",
            "quoteAmount",
            "fillPriceUsd",
            "fillPriceSol",
        ],
        RouteId::LiveChat => &[],
    }
}

/// Tag one leaf with what it MEANS on the route it arrived from.
///
/// The route is a parameter and not an afterthought: `createdAt` is measured epoch milliseconds on
/// the callout routes and has never been measured on the community routes, and a tag that cannot
/// tell those apart has to stay silent on both — which is how a unit error survives.
fn tagged_scalar(
    route: RouteId,
    field: &str,
    raw: &RawValue,
    bonded: Option<bool>,
) -> Option<TaggedScalar> {
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
        semantics: semantics(route, field, bonded).to_owned(),
    })
}

/// The reserve quartet's meaning depends on whether the coin has graduated, so its tag cannot be
/// a constant. `None` means the row carried no readable `complete` flag, which is treated as
/// unusable rather than as not-graduated: an unknown curve state is not a live one.
fn reserve_semantics(field: &str, bonded: Option<bool>) -> Option<&'static str> {
    if !matches!(
        field,
        "virtual_sol_reserves"
            | "virtual_token_reserves"
            | "virtual_quote_reserves"
            | "real_sol_reserves"
            | "real_token_reserves"
            | "real_quote_reserves"
    ) {
        return None;
    }
    Some(match bonded {
        Some(false) => "provider_bonding_curve_reserve_while_on_curve",
        Some(true) => "provider_launch_constant_after_graduation_never_a_price_input",
        None => "provider_reserve_of_unknown_curve_state_never_a_price_input",
    })
}

/// What a callout leaf means, MEASURED 2026-08-22 on `/callout/top/{mint}` and
/// `/callout/list/{user}` and true of neither community route.
///
/// Two measurements are encoded here rather than written down somewhere a reader might not reach.
///
/// THE CLOCK. `createdAt` and `peakTimestamp` are epoch MILLISECONDS and `maxMultiplierAt` is an
/// ISO-8601 UTC string — two encodings of an instant on ONE row. Every one of them is an
/// OCCURRENCE time. Nothing on either route says when the provider learned of a callout or when
/// it became visible, so an availability clock has to come from our own receive instant and is
/// never read off the row.
///
/// THE SOL TRAP. Two reads of the same ten callouts two seconds apart returned identical
/// `calloutPriceUsd` and `maxPriceUsd` and DIFFERENT `calloutPrice` and `maxPriceSol` on all ten.
/// Within one response every row divides by exactly one SOL price, and that divisor moved between
/// the reads. The SOL-denominated numbers are recomputed at READ time against the current SOL
/// price; they are not what the coin cost in SOL when the caller called it, and a backtest that
/// treats them that way is off by however far SOL has moved since.
fn callout_semantics(route: RouteId, field: &str) -> Option<&'static str> {
    if !matches!(
        route,
        RouteId::CalloutRecent | RouteId::CalloutTop | RouteId::CalloutByUser
    ) {
        return None;
    }
    Some(match field {
        "createdAt" => "callout_occurrence_time_epoch_millis_no_availability_time_exists",
        "peakTimestamp" => "retrospective_peak_time_epoch_millis_as_of_acquisition",
        "maxMultiplierAt" => "retrospective_peak_time_iso8601_utc_string_as_of_acquisition",
        "calloutPrice" | "maxPriceSol" => {
            "provider_sol_price_recomputed_at_read_never_the_sol_price_at_the_callout"
        }
        "calloutPriceUsd" | "maxPriceUsd" => "callout_usd_price_as_of_the_callout_event",
        "marketCap" => "callout_usd_market_cap_as_of_the_callout_event",
        _ => return None,
    })
}

fn semantics(route: RouteId, field: &str, bonded: Option<bool>) -> &'static str {
    // MEASURED 2026-08-22, and the reason this function takes the row's `complete` flag at all: a
    // coin with complete=true was observed carrying virtual_sol_reserves=30000000000 and
    // real_sol_reserves=0 — the launch constants, untouched — while its market cap fell 97 percent
    // in ninety-seven seconds. Once a coin graduates off the pump bonding curve its reserve fields
    // stop tracking anything, so reconstructing curve state from them yields a confident price for
    // a coin that no longer trades on that curve. The tag says so on the field itself, and
    // `crate::reserves` is the accessor that refuses outright.
    if let Some(tag) = reserve_semantics(field, bonded) {
        return tag;
    }
    if let Some(tag) = callout_semantics(route, field) {
        return tag;
    }
    // MEASURED 2026-08-23 from the retained live bodies: the two swap-api routes carry the SAME
    // `timestamp` name under different units AND different encodings — a JSON number of epoch
    // MILLISECONDS on candles (the bar open time) and an ISO-8601 UTC STRING on trades (the
    // trade time). Declaring both here makes the homonym a stated fact each tag carries, instead
    // of an inference the audit has to hedge; on every other route the name stays unmeasured and
    // falls through to the silent tag below.
    if field == "timestamp" {
        match route {
            RouteId::Candles => return "provider_bar_open_time_epoch_millis_number",
            RouteId::Trades => return "provider_trade_time_iso8601_utc_string",
            _ => {}
        }
    }
    match field {
        "mint"
        | "creator"
        | "coinMint"
        | "address"
        | "userId"
        | "user_uuid"
        | "walletAddress"
        | "calloutId"
        | "id"
        | "signature"
        | "tx"
        | "userAddress"
        | "slotIndexId"
        | "bonding_curve"
        | "associated_bonding_curve"
        | "pool_address"
        | "pump_swap_pool"
        | "quote_mint"
        | "token_program"
        | "chain_id" => "provider_identifier",
        // Units MEASURED on the coin routes, so the unit travels in the tag.
        "created_timestamp"
        | "last_trade_timestamp"
        | "ath_market_cap_timestamp"
        | "king_of_the_hill_timestamp"
        | "last_reply"
        | "thumbnail_updated_at" => "provider_event_time_epoch_millis_unparsed",
        // Units NOT measured on these, so the tag stays silent rather than guessing one.
        "createdAt" | "calloutTimestamp" | "timestamp" | "time" => "provider_event_time_unparsed",
        // MEASURED 2026-08-22 and NOT a detail: on /coins and /coins/currently-live every other
        // time on the row is epoch MILLISECONDS and `updated_at` alone is epoch SECONDS. Read as
        // milliseconds it lands on 21 January 1970 — which reads as a plausible stale record
        // rather than as a units error, so nothing downstream would flag it. That is why the unit
        // is part of this value's type and not a remark in a comment somewhere, and why the lexeme
        // is never rescaled here.
        "updated_at" => "provider_event_time_epoch_seconds_unparsed",
        // Realised one-hour USD volume, measured only on /coins/search-unrestricted. It is a
        // provider aggregate over a window this catalog cannot see the edges of, so it is never
        // a sum this codebase can reproduce from trades it holds.
        "volume_1h_usd" => "provider_windowed_aggregate_unverifiable",
        // The highest market cap the provider has ever recorded for this coin, with the instant
        // it says that happened. It is an outcome as of the read: comparing it to the current
        // market cap yields a drawdown, never a forecast.
        "ath_market_cap" => "retrospective_peak_as_of_acquisition_never_pre_event_feature",
        "num_participants" => "provider_live_audience_count",
        // These arrive as JSON strings holding 28-significant-digit decimals. Tagging them
        // `utf8` alone would let a later reader mistake a price for a name, and the provider
        // pads `open`/`close` to a fixed width while trimming `high`/`low`, so two byte-unequal
        // strings can denote the same number. Nothing here parses them.
        "open" | "high" | "low" | "close" | "volume" | "priceUsd" | "priceSol" | "amountUsd"
        | "amountSol" | "baseAmount" | "quoteAmount" | "fillPriceUsd" | "fillPriceSol" => {
            "provider_decimal_string_unparsed"
        }
        // MEASURED 2026-08-22: these two provider fields assert the SAME quantity and DISAGREE,
        // by a median of 0.10 percent and up to 0.31 percent over 140 rows, presumably because
        // they were computed against different SOL price snapshots. Neither is preferred and
        // neither is dropped. There is no universal price here, and the gap between two price
        // assertions is itself a state variable, so each tag names the other field: a reader who
        // picks one has to notice that they were choosing.
        "market_cap_usd" => "provider_usd_market_cap_assertion_disagreeing_with_usd_market_cap",
        "usd_market_cap" => "provider_usd_market_cap_assertion_disagreeing_with_market_cap_usd",
        // Quote-denominated, which on every coin measured meant SOL. A third market cap on a
        // third unit, equally not to be conflated with the two above.
        "market_cap" | "market_cap_quote" => "provider_quote_denominated_market_cap_assertion",
        "program" => "provider_execution_venue",
        "type" => "provider_trade_direction",
        "multiple" | "maxMultiplier" | "maxPriceSol" | "peakTimestamp" | "maxPriceUsd" => {
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
    // Measured 2026-08-22: the trades route carries its continuation under `pagination`, not at
    // the root. Reading only the root reported "no next page" while `hasMore` was true.
    let nested = object
        .get("pagination")
        .filter(|value| value.get().trim_start().starts_with('{'))
        .map(|value| raw_object(value))
        .transpose()?;
    for key in ["nextPageToken", "nextCursor", "cursor"] {
        if let Some(value) = object.get(key).or_else(|| nested.as_ref()?.get(key)) {
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

/// Collect the bounded, path-and-type structural signature of a response without scalar values.
///
/// The lines are the exact material a schema review reads, so a reviewer can retain them verbatim
/// and a later run can recompute the same fingerprint from what was actually reviewed.
///
/// # Errors
///
/// Returns an error for invalid nested JSON or nesting beyond the normalizer limit.
pub fn schema_shape(root: &RawValue) -> Result<Vec<String>, NormalizeError> {
    let mut shape = BTreeSet::new();
    collect_shape(root, "$", 0, &mut shape)?;
    Ok(shape.into_iter().collect())
}

/// Hash an already-collected structural signature. Ordering and duplicates are normalized so the
/// digest depends only on the set of shape lines.
#[must_use]
pub fn fingerprint_of_shape(shape: &[String]) -> String {
    let ordered = shape.iter().cloned().collect::<BTreeSet<_>>();
    let canonical = ordered.into_iter().collect::<Vec<_>>().join("\n");
    sha256(canonical.as_bytes())
}

/// Hash a bounded, path-and-type structural signature without scalar values.
///
/// # Errors
///
/// Returns an error for invalid nested JSON or nesting beyond the normalizer limit.
pub fn schema_fingerprint(root: &RawValue) -> Result<String, NormalizeError> {
    Ok(fingerprint_of_shape(&schema_shape(root)?))
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

    /// The 2026-08-22 measurement, defended: reading `calloutPrice` as the SOL price at the
    /// callout is wrong by however far SOL has moved since, and the tag has to say so.
    #[test]
    fn callout_sol_prices_are_tagged_as_recomputed_at_read() {
        for field in ["calloutPrice", "maxPriceSol"] {
            assert_eq!(
                semantics(RouteId::CalloutByUser, field, None),
                "provider_sol_price_recomputed_at_read_never_the_sol_price_at_the_callout"
            );
        }
        for field in ["calloutPriceUsd", "maxPriceUsd"] {
            assert_eq!(
                semantics(RouteId::CalloutTop, field, None),
                "callout_usd_price_as_of_the_callout_event"
            );
        }
    }

    /// `createdAt` was measured as epoch milliseconds on the callout routes and has never been
    /// measured anywhere else, so the tag must stay silent everywhere else.
    #[test]
    fn the_callout_clock_is_typed_only_where_it_was_measured() {
        assert_eq!(
            semantics(RouteId::CalloutTop, "createdAt", None),
            "callout_occurrence_time_epoch_millis_no_availability_time_exists"
        );
        assert_eq!(
            semantics(RouteId::CommunityMessages, "createdAt", None),
            "provider_event_time_unparsed"
        );
        assert_eq!(
            semantics(RouteId::CommunityCallouts, "createdAt", None),
            "provider_event_time_unparsed"
        );
    }

    /// A leaf may only be REQUIRED by a row-projection review if the normalizer reads it. These
    /// three were in the guessed callout projection and appear on neither measured route.
    #[test]
    fn the_callout_projection_drops_names_that_were_never_observed() {
        let read = extracted_fields(RouteId::CalloutByUser);
        for absent in [
            "walletAddress",
            "calloutTimestamp",
            "calledOutAtMcap",
            "thesis",
        ] {
            assert!(
                !read.contains(&absent),
                "{absent} is not a measured callout leaf"
            );
        }
        for present in [
            "calloutId",
            "coinMint",
            "createdAt",
            "calloutPriceUsd",
            "viewCount",
        ] {
            assert!(
                read.contains(&present),
                "{present} was measured on a callout row"
            );
        }
    }

    #[test]
    fn tagged_numbers_keep_the_exact_json_lexeme() {
        let raw: Box<RawValue> = serde_json::from_str("1.2300e-7").unwrap();
        let value = tagged_scalar(RouteId::CalloutTop, "calloutPrice", &raw, None).unwrap();
        assert_eq!(value.encoding, "json_number_lexeme");
        assert_eq!(value.value.as_deref(), Some("1.2300e-7"));
    }
}
