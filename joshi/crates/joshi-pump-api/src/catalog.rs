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
    CalloutByUser,
    CalloutLeaderboard,
    UserSearch,
    UserProfile,
    Following,
    CommunityMessages,
    CommunityCallouts,
    CommunityMe,
    Candles,
    Trades,
    BoardMovers,
    InMemoryCoin,
    LiveChat,
}

impl RouteId {
    pub const ALL: [Self; 22] = [
        Self::CoinExact,
        Self::SolPrice,
        Self::BalanceSummary,
        Self::BalanceTokens,
        Self::DiscoveryCoins,
        Self::CurrentlyLive,
        Self::CoinSearch,
        Self::CalloutRecent,
        Self::CalloutTop,
        Self::CalloutByUser,
        Self::CalloutLeaderboard,
        Self::UserSearch,
        Self::UserProfile,
        Self::Following,
        Self::CommunityMessages,
        Self::CommunityCallouts,
        Self::CommunityMe,
        Self::Candles,
        Self::Trades,
        Self::BoardMovers,
        Self::InMemoryCoin,
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
            Self::CalloutByUser => "callout_by_user",
            Self::CalloutLeaderboard => "callout_leaderboard",
            Self::UserSearch => "user_search",
            Self::UserProfile => "user_profile",
            Self::Following => "following",
            Self::CommunityMessages => "community_messages",
            Self::CommunityCallouts => "community_callouts",
            Self::CommunityMe => "community_me",
            Self::Candles => "candles",
            Self::Trades => "trades",
            Self::BoardMovers => "board_movers",
            Self::InMemoryCoin => "in_memory_coin",
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
            // Measured live 2026-08-22 across 24 successful calls. The document is a BARE
            // top-level JSON array of coin records; there is no envelope, no total and no cursor,
            // so this route asserts nothing whatever about completeness.
            //
            // The provider enumerates its own accepted `sort` values in its 400 body:
            // created_timestamp, market_cap, ath_market_cap, reply_count, last_reply,
            // last_trade_timestamp. `order` is ASC or DESC and the provider enumerates that too.
            // `last_reply` is sortable but is NOT a field this route returns, so it can order a
            // page that cannot be read back. `includeNsfw`, `searchTerm` and `creator` were all
            // accepted, and `creator` genuinely filtered to that creator's coins.
            //
            // `limit` SILENTLY CLAMPS TO 70. limit=71, limit=100 and limit=1000 each returned
            // exactly 70 rows with HTTP 200 and no warning of any kind, so a caller that asks for
            // a thousand and counts what it gets is the only caller that finds out.
            //
            // `offset` genuinely pages, but over a population that moves under it: at
            // sort=created_timestamp DESC roughly one coin per second is created, so offset=5
            // taken seconds after offset=0 re-served a row the first page had already returned.
            // Deep offsets stop paying out ENTIRELY SILENTLY: offset=1000 returned 70 rows,
            // offset=1030, 2000 and 5000 each returned a bare `[]` under HTTP 200. Past the end
            // and no-such-coin are the same two bytes, so an empty page here is never evidence
            // that nothing matched.
            //
            // THE FIELD THAT IS NOT HERE: this route carries no volume, no trade count, no
            // holder count and no buy/sell split. Its only flow-adjacent fields are
            // last_trade_timestamp, ath_market_cap with ath_market_cap_timestamp, and
            // reply_count. The sibling /coins/search-unrestricted route DOES carry
            // volume_1h_usd; see RouteId::CoinSearch.
            RouteId::DiscoveryCoins => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "measured 2026-08-22: bare array; sort/order as the provider enumerates them; limit \
                 silently clamps to 70; offset pages a population that moves under it and answers \
                 past-the-end with an empty array; no volume field",
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
                true,
            ),
            // Measured live 2026-08-22. Also a bare top-level JSON array. Rows are the same coin
            // record as /coins plus a livestream block: num_participants, livestream_title,
            // thumbnail, thumbnail_updated_at, playlist_status, playlist_updated_at and four
            // playlist URLs. `num_participants` is the only audience-size number anywhere in this
            // catalog and it is present on every row.
            //
            // A bare call returned 60 rows; `limit` and `offset` were both honoured. The row
            // order matches NO field the rows carry: it is not num_participants, not
            // usd_market_cap and not last_trade_timestamp, in either direction. Whatever ranks
            // this feed is not observable in it, so nothing downstream may read position as rank.
            RouteId::CurrentlyLive => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins/currently-live",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "measured 2026-08-22: bare array; offset/limit page; row order matches no returned \
                 field, so position is not a readable rank; membership churns between calls",
                &[],
                &["offset", "limit"],
                &[],
                true,
            ),
            // Measured live 2026-08-22, and it is not what its name suggests. This route returns
            // the same bare array of coin records as /coins with ONE EXTRA FIELD THAT NOTHING
            // ELSE IN THIS CATALOG HAS: `volume_1h_usd`, present and non-zero on all 70 rows of
            // every term-bearing page measured. And the rows arrive strictly DESCENDING BY
            // `volume_1h_usd` — verified monotone over 70 rows for two different terms, and
            // continuing correctly across an offset page whose highest volume sat below the
            // previous page's lowest. It is a live-volume leaderboard filtered by a term, not a
            // relevance ranking.
            //
            // The term is load-bearing. With `searchTerm` omitted, and again with it set to the
            // empty string, the returned rows carry NO `volume_1h_usd` KEY AT ALL — 0 of 20 rows
            // on each of two such pages — and are long-dead coins ordered ASCENDING by market cap.
            // An earlier note here recorded those rows as having a volume of exactly zero; that
            // was a readout defaulting an absent field to 0, which is the fabrication this crate
            // exists to refuse, and it is why `volume_1h_usd` is an OPTIONAL leaf in the row
            // projection rather than a required one. So this route cannot enumerate a global
            // universe in one call; reaching one means sweeping terms, and every such sweep is a
            // biased sample of whatever the terms happened to match.
            //
            // Rows here also carry the only nested structure measured on any coin row, a `mayhem`
            // object with `state`, `mode` and `pause_reason`, and some rows carry NO reserve
            // quartet and no `total_supply` at all.
            //
            // `limit` is NOT clamped at 70 here the way it is on /coins: limit=100 returned 100
            // rows. Two sibling routes on one host with different silent caps is exactly the kind
            // of thing that has to be measured per route rather than inherited.
            RouteId::CoinSearch => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/coins/search-unrestricted",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::OffsetLimit,
                "measured 2026-08-22: bare array carrying volume_1h_usd, strictly descending by it \
                 within the searchTerm match; offset pages; limit 100 honoured; an absent or empty \
                 searchTerm yields dead zero-volume coins ascending by market cap",
                &[],
                &["searchTerm", "offset", "limit"],
                &["searchTerm"],
                true,
            ),
            // MEASURED NON-EXISTENT 2026-08-22. This entry was catalogued for three days as a
            // global recent-callout feed with a descending-score keyset. It has neither, because
            // the path is not a route. A bare GET answered HTTP 400 with
            //   {"statusCode":400,"path":"/callout/recent",
            //    "message":"Validation failed (uuid is expected)","error":"Bad Request"}
            // which is a UUID-parse pipe rejecting the literal segment "recent": the handler that
            // caught the request is /callout/{uuid}, and no handler is bound to /callout/recent.
            // The retained body is fixtures/callout_recent_phantom_v1.json.
            //
            // It stays in the catalog, un-collectable, so that the refutation is durable and the
            // next reader does not re-derive this route from the same wishful reading of the
            // sibling paths. No replacement path is guessed here; /callout/top/{mint} and
            // /callout/list/{mint} below were separately confirmed to exist.
            RouteId::CalloutRecent => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/recent",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "measured 2026-08-22: no such route; the provider answers 400 uuid-expected because \
                 /callout/{uuid} is what catches this path",
                &[],
                &["limit", "pageToken"],
                &["pageToken"],
                false,
            ),
            // Measured live 2026-08-22 against six busy mints: this one is real, and the predicted
            // envelope was right. It returns {"callouts":[...]} whose rows carry calloutId,
            // userId, user_uuid, coinMint, marketCap, calloutPrice, multiple, createdAt,
            // maxPriceSol, thesis, peakTimestamp, username, profileImage and xUsername. `multiple`
            // and `peakTimestamp` are outcomes as of the read, never pre-event features.
            //
            // CLOCK, measured: `createdAt` and `peakTimestamp` are both epoch MILLISECONDS, and
            // both are OCCURRENCE times. No row of this route, and no response header of it,
            // states when the provider learned of a callout or when it became visible. The only
            // availability instant available is our own receive clock, so a t=0 built from this
            // route is "the callout says it happened then", never "we could have known then".
            //
            // It is collectable now because it is the only route that maps a COIN to the callers
            // who called it; two of six busy mints answered with zero callouts, which is retained
            // as an absent record and never as evidence that nobody called them.
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
                true,
            ),
            // RESOLVED 2026-08-22, and the resolution renamed the route. The earlier reading was
            // that /callout/list/{mint} answered {"callouts":[],"nextPageToken":""} for a coin
            // that /callout/top had just returned three callouts for, and that the empty answer
            // was an unexplained default sort, window or censoring. It is none of those: this
            // path segment is not a mint at all. Supplying a caller's `userId` wallet, and
            // separately that same caller's `user_uuid`, each returned TEN of that caller's
            // callouts spanning many different coins. The path is a USER, the feed is one
            // caller's callout history newest-first, and a mint in that slot is simply an
            // identifier no user has — which is why it answered empty. An empty answer here still
            // is not evidence of absence, but the reason is now ordinary rather than mysterious.
            //
            // Measured over 58 rows from 8 callers: `createdAt` is epoch MILLISECONDS and every
            // document was strictly descending by it, so this is the only live callout clock this
            // catalog has. `nextPageToken` decodes to {"v":2,"page":N} — a page counter, not a
            // keyset. Its rows carry MORE than /callout/top's: calloutPriceUsd, maxPriceUsd,
            // maxMultiplier, maxMultiplierAt (an ISO-8601 string, not epoch millis, on the same
            // row as an epoch-millis createdAt), likes, viewCount and the reply/repost/quote
            // counters.
            //
            // THE TRAP, measured on two reads two seconds apart: calloutPrice and maxPriceSol
            // DIFFERED on all ten common rows while calloutPriceUsd and maxPriceUsd were
            // byte-identical. Every row in one response divides by exactly one SOL price, and that
            // divisor moved between reads. The SOL-denominated callout numbers are recomputed at
            // READ time against the current SOL price; they are not the SOL price at the callout.
            // The USD pair is the as-of-event quantity, and marketCap is calloutPriceUsd times a
            // 1e9 supply to the last digit.
            //
            // There is NO discovery-side callout feed: /callout/recent is a phantom and both real
            // routes need a subject already in hand, so nothing here can originate a t=0.
            RouteId::CalloutByUser => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/list/{user}",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::PageToken,
                "measured 2026-08-22: one caller's callouts, strictly descending by createdAt; \
                 pageToken is a page counter",
                &["user"],
                &["limit", "sortBy", "sortOrder", "pageToken"],
                &["pageToken"],
                true,
            ),
            // Measured live 2026-08-23 as Ember's authenticated account. This is the GLOBAL
            // caller leaderboard, and it is the fan-out ROOT the callout study was previously
            // approximating by hand: /callout/recent is a phantom (400 uuid-expected) and both
            // real callout routes need a subject already in hand, so before this route nothing in
            // the catalog could ORIGINATE a caller population. Anonymous it answers 401; the
            // community-documented advanced-api-v2 callout paths are stale (404). It requires the
            // SIWS session in crate::auth_session, whose wallet signs ONLY the login timestamp.
            //
            // ENVELOPE, measured: {"leaderboard":[...]} with no continuation token; `limit` is
            // allowlisted. Each row is a CALLER carrying userId, wallets and a `topCallouts`
            // array whose elements repeat the /callout/top row shape (coinMint, calloutPrice,
            // multiple, createdAt, maxPriceSol, thesis). Its ranking is the provider's own
            // retrospective caller score, so it is a leaderboard and not a census: a caller absent
            // from it is not a caller who never called. Every clock on it is the same occurrence
            // clock the sibling callout routes carry, with no availability instant anywhere, and
            // the SOL-denominated prices carry the same read-time divisor. The row-projection
            // review measured from the real response is the gate for anything retained from it.
            RouteId::CalloutLeaderboard => Self::http(
                id,
                "https://frontend-api-v3.pump.fun",
                "/callout/leaderboard",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::None,
                "measured 2026-08-23 authenticated: global caller leaderboard, provider \
                 retrospective score; each row a caller with a topCallouts array; no continuation \
                 token",
                &[],
                &["limit"],
                &[],
                true,
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
            // CORRECTED 2026-08-24. The earlier entry pointed this route at profile-api.pump.fun
            // behind a user session; the app's own service registry and the 2026-08-24 surface
            // recon (docs/reference/PUMP_API_MAP.md) both say the community subsurface is a
            // SEPARATE product — api.coin-communities.xyz — whose /public routes want no user
            // session, only the shared `x-api-key` product key declared below. This collector has
            // still never called the messages route; the recon verified it LIVE and its rows add
            // `parentCalloutId`, the join from chat back to the callout it discusses. It stays
            // un-collectable until reviewed material exists.
            RouteId::CommunityMessages => Self::http(
                id,
                "https://api.coin-communities.xyz",
                "/api/v1/communities/{mint}/messages/public",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "recon-verified 2026-08-24: newest-window feed like its callout sibling; \
                 never called by this collector",
                &["mint"],
                &["limit", "cursor"],
                &["cursor"],
                false,
            ),
            // CORRECTED AND MEASURED LIVE 2026-08-24 (two mints, four reads). The earlier entry
            // pointed at profile-api.pump.fun behind a user session; the live service is
            // api.coin-communities.xyz and its /public routes are anonymous-with-shipped-key: the
            // only credential is the `x-api-key` product key the app bundle ships to every
            // visitor (see [`Self::shared_product_key_header`] — the key is public by
            // construction, rotates, and never lands in this repo, a fixture, or an envelope).
            //
            // Envelope {"callouts":[...]}, a FIXED NEWEST-50 WINDOW. `limit` is INERT — limit=3
            // returned the same 50 rows byte-identically — and no pagination exists (the recon
            // measured offset/page/cursor all inert; both names stay allowlisted only so inertia
            // can be re-measured). History beyond the newest 50 is unreachable through this
            // route, so our own accumulated tape is the only thing that holds more: the
            // poll-or-lose fact the keeper cadence note in ops/keeper.toml prices. Two reads 3 s
            // apart were BYTE-IDENTICAL including calloutPrice/calloutMarketCap, so the
            // /callout/list SOL trap (read-time recompute) does NOT reproduce here — consistent
            // with a materialised view whose refresh cadence is unmeasured.
            //
            // CLOCKS: createdAt and maxMultiplierAt are ISO-8601 UTC with MICROSECONDS, while
            // /callout/top and /callout/list state the same events in epoch milliseconds — two
            // callout routes on two hosts with two time encodings; any join must normalise
            // explicitly, and normalize::semantics names the clock per route. Prices are
            // USD-denominated JSON numbers. Rows carry what /callout/top does not: likeCount,
            // replyCount, followerCount, the isSpam/isHarmful moderation flags, mentions, and a
            // stable uuid `id` keying the detail/replies routes — the counters Ember actually
            // sees in the app.
            //
            // WHAT LEAVES THE PROCESS toward this NEW third party: the mint asked about (a
            // public chain fact, declared a public subject below), the shared bundle key every
            // pump.fun visitor sends, our IP and user agent. No wallet, no session, no cookie —
            // the same exposure class as swap-api, plus the shared key. The key buys a GLOBAL
            // budget shared with every pump.fun visitor (~1 request/second, measured by the
            // recon), so a 429 here is ordinary weather and never evidence of absence.
            RouteId::CommunityCallouts => Self::http(
                id,
                "https://api.coin-communities.xyz",
                "/api/v1/communities/{mint}/callouts/public",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "measured 2026-08-24: fixed newest-50 window, newest first; limit inert, no \
                 pagination, history beyond the window unreachable; ISO-8601 microsecond clocks",
                &["mint"],
                &["limit", "cursor"],
                &["cursor"],
                true,
            ),
            // The bearer-gated READ the coin-communities wallet-auth session unlocks, and the
            // narrowest one worth declaring: GET /api/v1/users/me reads ONLY the authenticated
            // account — Ember's own — naming nobody else, so it proves the session authenticates as
            // her without harvesting anyone. In the service's own OpenAPI SDK its security is the
            // DOUBLE HEADER `bearer + x-api-key`: every coin-communities request carries the shared
            // product key (a keyless read answers 401), and the bearer is what makes it Ember. That
            // is why this route both requires a session AND declares the shared-product-key header,
            // and why the client stamps both onto the request. It stays collection-disabled and
            // AuthenticatedUnverified — a session read exists to prove the handshake, not to be
            // tapped on a cadence — and is enabled only for a bounded operator verification.
            //
            // Naming note that fixes the map (§4.6): the service's OpenAPI names the community path
            // segment `{token_address}`, not `{mint}`; this catalog keeps its own segments named
            // `{mint}` for consistency with every other coin route (the resolved value is the same
            // public mint either way), and `/api/v1/users/me` carries no path segment at all.
            RouteId::CommunityMe => Self::http(
                id,
                "https://api.coin-communities.xyz",
                "/api/v1/users/me",
                AccessClass::AuthenticatedUserSession,
                Stability::AuthenticatedUnverified,
                PaginationKind::None,
                "one current authenticated account record",
                &[],
                &[],
                &[],
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
            // Measured live 2026-08-24 over five reads, 525 rows, on a host new to this catalog:
            // advanced-indexer.pump.fun, anonymous and keyless. Envelope
            // {"board","version","serverTs","entries":[...]} — `serverTs` is epoch milliseconds
            // and PROVIDER-STATED: the first provider-side availability instant on any discovery
            // feed in this catalog. It rides in the retained exact bytes; nothing normalizes it
            // yet, deliberately, because the row gate certifies rows and the envelope is outside
            // them.
            //
            // Rows use compact keys. The app's own decoder (bundle chunk 09373ik9or5q1) pins
            // m/n/t/i = mint/name/symbol/image_uri, mc = usd_market_cap, age = SECONDS since
            // creation (a duration, not an instant), gd = graduation (`complete` iff gd > 0),
            // dw = dev wallet, plus pl/lv/desc/vid/ic/rid/ms. The volume family (v v5 v15 v1h
            // v24h and vUsd*) and the trade counts (tx5, txc) are NOT decoded by the app: their
            // meanings are INFERRED from the names, normalize::semantics tags them as inferred,
            // and nothing downstream may treat them as measured until a stability check pins
            // them. This is the flow field the /coins entry documents as missing.
            //
            // `limit` is honoured to 150 and then SILENTLY CLAMPS: limit=200 and limit=500 each
            // returned exactly 150 rows, HTTP 200, no warning — the /coins-clamps-to-70 family.
            // A bare call returns 70.
            //
            // `rid` is a recommendation id and the app's URL builder can send userId, session_id
            // and country: this board is a PERSONALISED recommendation feed, not a census.
            // Position is not rank and two clients can be served different boards. Those
            // personalisation parameters are deliberately NOT allowlisted here — this collector
            // must never ask for a personalised board, so a request naming them is refused
            // before any I/O (the never-public floor would refuse retaining them anyway).
            RouteId::BoardMovers => Self::http(
                id,
                "https://advanced-indexer.pump.fun",
                "/boards/movers",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "measured 2026-08-24: personalised recommendation board, position is not rank; \
                 envelope serverTs is a provider availability instant; limit honoured to 150 \
                 then silently clamped",
                &[],
                &["limit"],
                &[],
                true,
            ),
            // Measured live 2026-08-24 against two mints (one graduated, one bonding-history):
            // a single rich live-state object with 69 keys, identical key sets on both reads.
            // Carries volumeSol/volumeUsd (cumulative), buyCount/sellCount/txCount, numHolders,
            // top10HoldersPercent, devHoldingsPercent, sniperCount, progress and graduationDate —
            // per-coin flow and holder numbers no frontend-api coin route carries. Keys prefixed
            // `_` (_dirtyBoards, _lastLruTouchTs, _lastTradeTs, _lastUpdated) are provider cache
            // internals that leak into the response; retained like everything else, read by
            // nothing. Anonymous, keyless. Un-reviewed: retained bytes quarantine until a
            // reviewed projection exists, and nothing taps it on a cadence yet.
            RouteId::InMemoryCoin => Self::http(
                id,
                "https://advanced-indexer.pump.fun",
                "/in-memory-coin/{mint}",
                AccessClass::ObservedPublicProduct,
                Stability::UndocumentedObserved,
                PaginationKind::None,
                "measured 2026-08-24: one current in-memory live-state object; two mints \
                 answered identical key sets",
                &["mint"],
                &[],
                &[],
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

    /// Path segments whose resolved request values this catalog deliberately retains verbatim on
    /// the acquisition envelope, because they are public subject identifiers.
    ///
    /// A provider body frequently does not restate the identifier the request carried — a
    /// `candles` window is a bare OHLCV array that names no coin — so without this the resolved
    /// value survives only inside the one-way request fingerprint and nothing durable says which
    /// subject the retained bytes are about. An SPL mint in `/v1/coins/{mint}/candles` is public
    /// chain data the request already spelled out; retaining it restates a public fact.
    ///
    /// This is a pinned catalog decision, not a default: every segment absent from this list —
    /// `{user}` on the callout route, `{address}` on the balance routes — keeps the existing
    /// redaction and lives only in the fingerprint, because who was asked about is not the same
    /// class of fact as which coin a public price window describes.
    #[must_use]
    pub fn public_subject_path(self) -> &'static [&'static str] {
        match self.id {
            // `/callout/top/{mint}` joins the coin-subject routes (2026-08-24, for the keeper's
            // hot-attention tap): its `{mint}` is the same class of public chain fact as the
            // candles/trades segment, and its body rows name `coinMint` — retaining the resolved
            // ask corroborates the rows rather than revealing anything. `{user}` on the sibling
            // callout routes stays redacted exactly as before.
            //
            // `community_callouts` and `in_memory_coin` join on the same reasoning (2026-08-24,
            // for the keeper's community tap): the mint is a public chain fact and the community
            // rows restate it as `tokenAddress`. `{mint}` on the un-collectable community
            // messages route stays undeclared until something actually collects it — retention
            // declarations are made when they are used, not in advance.
            RouteId::CoinExact
            | RouteId::Candles
            | RouteId::Trades
            | RouteId::CalloutTop
            | RouteId::CommunityCallouts
            | RouteId::InMemoryCoin => &["mint"],
            _ => &[],
        }
    }

    /// Query parameters whose requested values this catalog deliberately retains verbatim on the
    /// acquisition envelope, beside the one-way request fingerprint. This is the query-side twin
    /// of [`Self::public_subject_path`], and the same idiom: retention is a pinned per-route
    /// catalog decision a person can read, never a client-side judgment call.
    ///
    /// WHY RETAIN ANY OF THEM. The source audit's silent-narrowing family is undecidable without
    /// the ask: `/coins` answers `limit=1000` with exactly 70 rows, HTTP 200, no warning
    /// (measured 2026-08-22), and a record that keeps only the answer can never convict that
    /// clamp. Likewise a retained candle window does not restate its own `interval` or
    /// `currency`, so without the request nothing durable says which series the bytes are.
    /// Every name in this list states the SHAPE of the ask — how many rows, from which offset,
    /// in which order, over which bar interval, in which denomination — and none of them states
    /// the SUBJECT of the ask.
    ///
    /// THE PRIVACY LINE, stated so it can be disagreed with: the shape of a request is a fact
    /// about this collector's mechanics; the subject of a request is a fact about what someone
    /// was interested in. Subjects (`searchTerm`, `creator`), continuation material that encodes
    /// a position in someone's reading (`cursor`, `pageToken`, `before`), and anything
    /// credential-adjacent stay ONLY inside the one-way fingerprint. A parameter is restated
    /// because this list says so, never because it looked harmless; the default for an
    /// undeclared parameter is redaction. [`query_parameter_never_public`] is the structural
    /// floor under that: a name it rejects cannot be restated even if a future edit of this
    /// list mistakenly declares it, and the envelope writer re-checks both at write time.
    #[must_use]
    pub fn public_query_parameters(self) -> &'static [&'static str] {
        match self.id {
            RouteId::DiscoveryCoins => &["includeNsfw", "limit", "offset", "order", "sort"],
            RouteId::CurrentlyLive
            | RouteId::CoinSearch
            | RouteId::UserSearch
            | RouteId::Following => &["limit", "offset"],
            // The `{wallet}` path subject stays redacted; the page shape says nothing about it.
            RouteId::BalanceTokens => &["page", "size"],
            // `before` is allowlisted on trades (as on candles) but stays undeclared: it is a
            // wall-clock seek into a subject's history — reading interest, not page shape — and
            // the catalog already pins it sensitive, like every cursor and pageToken here.
            // `board_movers` restates `limit` because its clamp family (honoured to 150, then
            // silently clamped) is undecidable without the ask, exactly like /coins at 70.
            RouteId::CalloutTop
            | RouteId::CalloutLeaderboard
            | RouteId::CommunityMessages
            | RouteId::CommunityCallouts
            | RouteId::Trades
            | RouteId::BoardMovers => &["limit"],
            RouteId::CalloutByUser => &["limit", "sortBy", "sortOrder"],
            // A retained candle window does not restate its own interval or denomination;
            // without these the bytes cannot say which series they are.
            RouteId::Candles => &["currency", "interval", "limit"],
            RouteId::CoinExact
            | RouteId::SolPrice
            | RouteId::BalanceSummary
            | RouteId::CalloutRecent
            | RouteId::UserProfile
            | RouteId::InMemoryCoin
            // users/me takes no query at all — nothing to restate.
            | RouteId::CommunityMe
            | RouteId::LiveChat => &[],
        }
    }

    /// The request header this route needs carrying the provider's SHARED product key, or `None`
    /// for the (ordinary) routes that need nothing.
    ///
    /// This exists for exactly one service today: api.coin-communities.xyz answers its `/public`
    /// routes only when the request carries the `x-api-key` the pump.fun bundle ships to every
    /// visitor. That key is NOT a user credential — every browser on earth sends the same one, it
    /// identifies the product rather than a person, and it rotates with the app deployment — so
    /// these routes stay [`AccessClass::ObservedPublicProduct`] and never touch the session
    /// machinery. The key VALUE never appears in this catalog, in a fixture, or on a retained
    /// envelope: the client takes it from [`crate::client::ClientConfig::shared_product_keys`]
    /// (keyed by origin, supplied by the operator at run time, extractable from the app bundle
    /// with `grep -o 'cc_[0-9a-f]\{64\}'` over the shipped chunks) and stamps the envelope's
    /// `session_class` as `shared_product_key` so the retained record states that the key was
    /// sent without stating the key.
    ///
    /// The key is not always ALONE, though: `community_me` is a bearer-gated read whose `OpenAPI`
    /// security is `bearer + x-api-key`. The two mechanisms are independent in the client — the
    /// shared key is attached because this method names it, the bearer because the route's access
    /// class requires a session — so a coin-communities session route rides BOTH headers, which is
    /// the service's own contract for its personalised routes.
    #[must_use]
    pub fn shared_product_key_header(self) -> Option<&'static str> {
        match self.id {
            RouteId::CommunityMessages | RouteId::CommunityCallouts | RouteId::CommunityMe => {
                Some("x-api-key")
            }
            _ => None,
        }
    }
}

/// Query-parameter names that may NEVER be declared public, whatever a route entry says.
///
/// This is the structural floor under [`RouteSpec::public_query_parameters`]: session tokens,
/// wallet addresses, user identifiers, continuation cursors and anything credential-adjacent are
/// refused BY NAME, so a mistaken future catalog edit cannot widen retention to them — the
/// envelope writer in `crate::client` re-checks this predicate (and the route's
/// `sensitive_query` list) at write time, and the catalog closure test asserts every declared
/// name passes it. Substring matching is deliberate: it over-refuses (`sortByUser` would be
/// refused for containing `user`) and never under-refuses, which is the correct failure
/// direction for a redaction floor.
#[must_use]
pub fn query_parameter_never_public(name: &str) -> bool {
    const NEVER_SUBSTRING: &[&str] = &[
        "account",
        "address",
        "auth",
        "cookie",
        "creator",
        "credential",
        "cursor",
        "key",
        "mail",
        "password",
        "phone",
        "search",
        "secret",
        "session",
        "sign",
        "term",
        "token",
        "user",
        "wallet",
    ];
    const NEVER_EXACT: &[&str] = &["before", "beforeId", "id", "q", "uuid"];
    let lowered = name.to_ascii_lowercase();
    NEVER_EXACT.iter().any(|deny| *deny == lowered)
        || NEVER_SUBSTRING.iter().any(|deny| lowered.contains(deny))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The closure over every route: a declared-public query parameter must be allowlisted,
    /// must not be route-pinned sensitive, and must clear the never-public floor. This is the
    /// test that makes "public because the catalog says so" reviewable in one place.
    #[test]
    fn public_query_declarations_close_over_the_whole_catalog() {
        for route in RouteId::ALL {
            let spec = RouteSpec::for_id(route);
            for name in spec.public_query_parameters() {
                assert!(
                    spec.allowed_query.contains(name),
                    "{route}: `{name}` is declared public but not allowlisted"
                );
                assert!(
                    !spec.sensitive_query.contains(name),
                    "{route}: `{name}` is declared public AND pinned sensitive"
                );
                assert!(
                    !query_parameter_never_public(name),
                    "{route}: `{name}` is on the never-public floor and cannot be declared"
                );
            }
        }
    }

    /// The floor refuses the names this catalog already knows are subjects, continuations, or
    /// credential-adjacent — including every route-pinned sensitive name in the catalog today.
    #[test]
    fn the_never_public_floor_covers_every_pinned_sensitive_name() {
        for route in RouteId::ALL {
            let spec = RouteSpec::for_id(route);
            for name in spec.sensitive_query {
                assert!(
                    query_parameter_never_public(name),
                    "{route}: sensitive `{name}` must also be refused by name"
                );
            }
        }
        for name in [
            "sessionToken",
            "authToken",
            "walletAddress",
            "userId",
            "apiKey",
            "cursor",
            "pageToken",
            "before",
            "searchTerm",
            "creator",
        ] {
            assert!(query_parameter_never_public(name), "{name} must be refused");
        }
        for name in ["limit", "offset", "interval", "sort", "order", "currency"] {
            assert!(
                !query_parameter_never_public(name),
                "{name} states page shape, not a subject, and must stay declarable"
            );
        }
    }

    /// The shared-product-key declaration stays exactly as narrow as the one service that needs
    /// it, and its relationship to the session machinery is now precise. EVERY coin-communities
    /// route carries the key (measured 2026-08-24: a keyless read answers 401), and no route on any
    /// other origin carries it. SOME coin-communities routes ALSO require a bearer session — the
    /// service's own `OpenAPI` contract puts `bearer + x-api-key` on its personalised routes, so the
    /// two headers ride together there — and when they do, the key is still declared. The earlier
    /// invariant that a shared-product-key route must NOT require a session was an artifact of only
    /// having `/public` routes declared; the double header is the real contract, so what must stay
    /// true is only that the key belongs to this origin and that a session on it also carries the
    /// key.
    #[test]
    fn the_shared_product_key_is_declared_for_every_coin_communities_route_and_no_other() {
        let coin_communities = "https://api.coin-communities.xyz";
        for route in RouteId::ALL {
            let spec = RouteSpec::for_id(route);
            let on_coin_communities = spec.origin == coin_communities;
            match spec.shared_product_key_header() {
                Some(header) => {
                    assert_eq!(header, "x-api-key");
                    assert!(
                        on_coin_communities,
                        "{route}: the shared product key belongs only to the coin-communities origin"
                    );
                }
                None => assert!(
                    !on_coin_communities,
                    "{route}: every coin-communities route needs the shipped key (measured \
                     2026-08-24: a keyless read answers 401)"
                ),
            }
            // A coin-communities SESSION route is the double-header case: it must still declare the
            // shared key alongside the bearer.
            if on_coin_communities && spec.requires_session() {
                assert_eq!(
                    spec.shared_product_key_header(),
                    Some("x-api-key"),
                    "{route}: a coin-communities session route needs BOTH the bearer and the \
                     shared product key"
                );
            }
        }
    }
}
