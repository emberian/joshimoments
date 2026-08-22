use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RouteId {
    CoinExact,
    SolPrice,
    BalanceSummary,
    BalanceTokens,
    DiscoveryCoins,
    CurrentlyLive,
    CoinSearch,
    CalloutRecent,
    CalloutTop,
    CalloutByMint,
    UserSearch,
    UserProfile,
    Following,
    CommunityMessages,
    CommunityCallouts,
    Candles,
    Trades,
    LiveChat,
}

impl RouteId {
    pub const ALL: [Self; 18] = [
        Self::CoinExact,
        Self::SolPrice,
        Self::BalanceSummary,
        Self::BalanceTokens,
        Self::DiscoveryCoins,
        Self::CurrentlyLive,
        Self::CoinSearch,
        Self::CalloutRecent,
        Self::CalloutTop,
        Self::CalloutByMint,
        Self::UserSearch,
        Self::UserProfile,
        Self::Following,
        Self::CommunityMessages,
        Self::CommunityCallouts,
        Self::Candles,
        Self::Trades,
        Self::LiveChat,
    ];
}

impl fmt::Display for RouteId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::CoinExact => "coin_exact",
            Self::SolPrice => "sol_price",
            Self::BalanceSummary => "balance_summary",
            Self::BalanceTokens => "balance_tokens",
            Self::DiscoveryCoins => "discovery_coins",
            Self::CurrentlyLive => "currently_live",
            Self::CoinSearch => "coin_search",
            Self::CalloutRecent => "callout_recent",
            Self::CalloutTop => "callout_top",
            Self::CalloutByMint => "callout_by_mint",
            Self::UserSearch => "user_search",
            Self::UserProfile => "user_profile",
            Self::Following => "following",
            Self::CommunityMessages => "community_messages",
            Self::CommunityCallouts => "community_callouts",
            Self::Candles => "candles",
            Self::Trades => "trades",
            Self::LiveChat => "live_chat",
        })
    }
}

impl FromStr for RouteId {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::ALL
            .into_iter()
            .find(|candidate| candidate.to_string() == value)
            .ok_or_else(|| format!("unknown route {value:?}"))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AccessClass {
    OfficiallyDescribedPublic,
    ObservedPublicProduct,
    AuthenticatedUserSession,
    ReconnaissanceOnly,
}

impl fmt::Display for AccessClass {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::OfficiallyDescribedPublic => "officially_described_public",
            Self::ObservedPublicProduct => "observed_public_product",
            Self::AuthenticatedUserSession => "authenticated_user_session",
            Self::ReconnaissanceOnly => "reconnaissance_only",
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Stability {
    DocumentedMutable,
    UndocumentedObserved,
    AuthenticatedUnverified,
    Unimplemented,
}

impl fmt::Display for Stability {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::DocumentedMutable => "documented_mutable",
            Self::UndocumentedObserved => "undocumented_observed",
            Self::AuthenticatedUnverified => "authenticated_unverified",
            Self::Unimplemented => "unimplemented",
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PaginationKind {
    None,
    OffsetLimit,
    PageSize,
    PageToken,
    BeforeId,
    Cursor,
    VendorWindow,
    Stream,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransportKind {
    Http,
    WebSocket,
}

impl fmt::Display for TransportKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Http => "http",
            Self::WebSocket => "websocket",
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RouteSpec {
    pub id: RouteId,
    pub origin: &'static str,
    pub path_template: &'static str,
    pub access: AccessClass,
    pub stability: Stability,
    pub transport: TransportKind,
    pub pagination: PaginationKind,
    pub ordering: &'static str,
    pub required_path: &'static [&'static str],
    pub allowed_query: &'static [&'static str],
    pub sensitive_query: &'static [&'static str],
    pub collection_enabled: bool,
}

impl RouteSpec {
    #[must_use]
    #[allow(clippy::too_many_lines)] // The source/access catalog is safer when audited together.
    pub fn for_id(id: RouteId) -> Self {
        match id {
            RouteId::CoinExact => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins-v2/{mint}",
                AccessClass::OfficiallyDescribedPublic,
                Stability::DocumentedMutable,
                PaginationKind::None,
                "one current mutable record",
                &["mint"],
                &[],
                &[],
                true,
            ),
            RouteId::SolPrice => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/sol-price",
                AccessClass::OfficiallyDescribedPublic,
                Stability::DocumentedMutable,
                PaginationKind::None,
                "one current quote",
                &[],
                &[],
                &[],
                true,
            ),
            RouteId::BalanceSummary => Self::http(
                id,
                "https://profile-api.pump.fun",
                "/balance/summary/{wallet}",
                AccessClass::OfficiallyDescribedPublic,
                Stability::DocumentedMutable,
                PaginationKind::None,
                "one current wallet summary",
                &["wallet"],
                &[],
                &[],
                true,
            ),
            RouteId::BalanceTokens => Self::http(
                id,
                "https://profile-api.pump.fun",
                "/balance/tokens/{wallet}",
                AccessClass::OfficiallyDescribedPublic,
                Stability::DocumentedMutable,
                PaginationKind::PageSize,
                "provider page order; undocumented",
                &["wallet"],
                &["page", "size"],
                &[],
                true,
            ),
            RouteId::DiscoveryCoins => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "query sort/order; membership and revision unknown",
                &[],
                &[
                    "offset",
                    "limit",
                    "sort",
                    "order",
                    "includeNsfw",
                    "searchTerm",
                    "creator",
                ],
                &["searchTerm", "creator"],
                false,
            ),
            RouteId::CurrentlyLive => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins/currently-live",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "provider live rank; revision unknown",
                &[],
                &["offset", "limit"],
                &[],
                false,
            ),
            RouteId::CoinSearch => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins/search-unrestricted",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "search relevance; session effects unknown",
                &[],
                &["searchTerm", "offset", "limit"],
                &["searchTerm"],
                false,
            ),
            RouteId::CalloutRecent => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/recent",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::PageToken,
                "descending score keyset as observed; revisions unknown",
                &[],
                &["limit", "pageToken"],
                &["pageToken"],
                false,
            ),
            RouteId::CalloutTop => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/top/{mint}",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "retrospective provider score",
                &["mint"],
                &["limit"],
                &[],
                false,
            ),
            RouteId::CalloutByMint => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/list/{mint}",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::PageToken,
                "sortBy/sortOrder; observed window may be censored",
                &["mint"],
                &["limit", "sortBy", "sortOrder", "pageToken"],
                &["pageToken"],
                false,
            ),
            RouteId::UserSearch => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/users/search",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::OffsetLimit,
                "search relevance; personalization unknown",
                &[],
                &["searchTerm", "offset", "limit"],
                &["searchTerm"],
                false,
            ),
            RouteId::UserProfile => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/users/{key}",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::None,
                "one current mutable profile",
                &["key"],
                &[],
                &[],
                false,
            ),
            RouteId::Following => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/following/{wallet}",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::OffsetLimit,
                "outgoing edges; offset order observed, completeness unknown",
                &["wallet"],
                &["offset", "limit"],
                &[],
                false,
            ),
            RouteId::CommunityMessages => Self::http(
                id,
                "https://profile-api.pump.fun",
                "/api/v1/communities/{mint}/messages/public",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::Cursor,
                "provider thread order; moderation/censoring unknown",
                &["mint"],
                &["limit", "cursor"],
                &["cursor"],
                false,
            ),
            RouteId::CommunityCallouts => Self::http(
                id,
                "https://profile-api.pump.fun",
                "/api/v1/communities/{mint}/callouts/public",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::Cursor,
                "provider callout order; revisions unknown",
                &["mint"],
                &["limit", "cursor"],
                &["cursor"],
                false,
            ),
            // Measured live 2026-08-22 against a real mainnet mint. The provider itself
            // enumerates the accepted intervals in its 400 body: 1s, 15s, 30s, 1m, 5m, 15m, 30m,
            // 1h, 4h, 6h, 12h, 24h. `limit` is rejected above 1000. Omitting `currency` returns a
            // USD-denominated series; `currency=SOL` returns a separately computed SOL series
            // whose volume did not agree with the USD one under scalar conversion.
            //
            // `before` was supplied as both epoch milliseconds and epoch seconds and changed
            // nothing: the window still ended at the present instant. It stays allowlisted so
            // that inertia can be re-measured without editing this catalog, not because it
            // paginates. With no working `before` and a hard limit of 1000, the reachable history
            // on this route is one newest-anchored window per interval, and deeper history has to
            // come from the trades route or from our own accumulated tap.
            //
            // The `ordering` string below is deliberately short: joshi-admission concatenates it
            // into a 512-byte coverage-scope subject, so this field is a scope key and not a
            // place for the measurement. The measurement lives in the reviewed-schema rationale
            // at crates/joshi-pump-api/fixtures/schema_review_candles_v1.json.
            RouteId::Candles => Self::http(
                id,
                "https://swap-api.pump.fun",
                "/v1/coins/{mint}/candles",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "measured 2026-08-22: ascending by timestamp; intervals with no trade are omitted, so the \
                 series is a gap-compressed path; newest-anchored, limit<=1000, `before` inert",
                &["mint"],
                &["interval", "limit", "currency", "before"],
                &["before"],
                true,
            ),
            // Measured live 2026-08-22. `limit` is rejected above 100, ten times tighter than the
            // candle route's 1000, so the cost of contiguous tape is fixed by arithmetic:
            // requests per hour of tape equals trades per hour divided by 100. A coin printing
            // two trades a minute costs about one request per hour of history; one printing
            // ninety costs about fifty.
            //
            // `before` is inert here exactly as it is on candles, in both epoch-millisecond and
            // epoch-second form. The cursor is what reaches the past, and it reaches further than
            // a walk: its `slotIndexId` prefix is not validated, and seeking with an all-zero
            // prefix and an arbitrary epoch-millisecond suffix returns the newest rows before
            // that instant. A cursor is therefore a random-access seek to a wall-clock time, not
            // only a continuation of the page that produced it, which is what makes the history
            // horizon measurable by bisection instead of by walking.
            //
            // Reaching past the beginning of a mint's retained history returns
            // `{"trades":[],"pagination":{"hasMore":false,"limit":n}}` with no cursor key at all.
            // That is a different structural shape and the reviewed schema refuses it, which is
            // intended: see crates/joshi-pump-api/fixtures/trades_terminal_page_v1.json.
            RouteId::Trades => Self::http(
                id,
                "https://swap-api.pump.fun",
                "/v2/coins/{mint}/trades",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::Cursor,
                "measured 2026-08-22: descending by slotIndexId, newest first; nextCursor is the \
                 exclusive keyset `slotIndexId-epochMillis` of the last row; revisions unknown",
                &["mint"],
                &["limit", "cursor", "before"],
                &["cursor", "before"],
                true,
            ),
            RouteId::LiveChat => Self {
                id,
                origin: "wss://livechat.pump.fun",
                path_template: "/",
                access: AccessClass::ReconnaissanceOnly,
                stability: Stability::Unimplemented,
                transport: TransportKind::WebSocket,
                pagination: PaginationKind::Stream,
                ordering: "stream order/replay/auth unresolved",
                required_path: &[],
                allowed_query: &[],
                sensitive_query: &[],
                collection_enabled: false,
            },
        }
    }

    #[allow(clippy::too_many_arguments)]
    const fn http(
        id: RouteId,
        origin: &'static str,
        path_template: &'static str,
        access: AccessClass,
        stability: Stability,
        pagination: PaginationKind,
        ordering: &'static str,
        required_path: &'static [&'static str],
        allowed_query: &'static [&'static str],
        sensitive_query: &'static [&'static str],
        collection_enabled: bool,
    ) -> Self {
        Self {
            id,
            origin,
            path_template,
            access,
            stability,
            transport: TransportKind::Http,
            pagination,
            ordering,
            required_path,
            allowed_query,
            sensitive_query,
            collection_enabled,
        }
    }

    #[must_use]
    pub fn requires_session(self) -> bool {
        self.access == AccessClass::AuthenticatedUserSession
    }
}
