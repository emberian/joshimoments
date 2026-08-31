"""The pump.fun social surface, as data — every route, its host, its auth, its verdict.

WHY THIS FILE IS A CATALOGUE AND NOT A PILE OF f-STRINGS
--------------------------------------------------------
`RESULT_caller_wallets.md` §1 records a study that reported a confident zero because
`/users/search?username=` returns HTTP 200 with `[]` for every input, including inputs
that exist. The lesson is not "test your endpoints"; it is that an endpoint's *verdict*
— live, dead, auth-walled, or silently-lying — is a measured fact with a date on it, and
facts belong in one place where they can be re-measured. `probe.py` re-runs this whole
table against the live hosts and writes the verdicts to `state/pumpsocial/surface.json`,
so "is this still true?" is a command, not an archaeology project.

WHERE THE ROUTES CAME FROM
--------------------------
Not guessing. pump.fun's webapp ships a generated OpenAPI client (`@hey-api/openapi-ts`)
in its Next.js chunks, and every operation in it carries its own `security:` spec
alongside its URL template:

    getFollowers: e => (e.client ?? w).get({
        security: [{name: "x-api-key", type: "apiKey"}],
        url: "/api/v1/users/{user_id}/followers", ...})

So the auth column below is the server's own declaration, extracted from the bundle on
2026-08-15, not an inference from response codes. 73 operations were recovered this way.
The verdicts, by contrast, ARE measured — several routes the client declares are 404 in
production, which is exactly the kind of drift a catalogue is for.

THE TWO SOCIAL BACKENDS, AND WHY BOTH ARE NEEDED
------------------------------------------------
pump.fun's social layer is split across two unrelated services, and neither is a superset
of the other. Getting this wrong is how the prior lanes concluded the data did not exist:

* **`api.coin-communities.xyz`** — a third-party service (note: NOT a `pump.fun` host)
  carrying *content*: per-coin comment threads, callouts with the platform's own scoring,
  the global feed, and callout leaderboards. Every post carries `walletAddress`.
  Read routes need only `x-api-key`, whose value ships in the browser bundle.
* **`frontend-api-v3.pump.fun`** — pump's own API carrying *identity and the follow
  graph*: profiles, username search, and `/following/<addr>` with per-edge FOLLOW
  TIMESTAMPS. No key, no auth.

The follow graph exists ONLY on frontend-api-v3 (`/api/v1/users/{uid}/followers` and
`/following` are declared by the coin-communities client but 404 in production). The
comment threads exist ONLY on coin-communities (`/replies/*` is 404 on frontend-api-v3,
which is what `studies/quality_callers.py` correctly recorded as dead — it was looking on
the right host for the wrong service).

THE STRUCTURAL PRIZE
--------------------
On pump the author IS a wallet. Every comment, reply and callout carries `walletAddress`
natively, so the handle->wallet join that limited `RESULT_caller_wallets.md` to 5 of 146
handles does not exist here. It is worse than that for the X route and better than that
for us: the same objects also carry `userTwitterUrl` as `https://x.com/i/user/<numeric
id>`, and `/api/v1/users/by-twitter-id/{twitter_id}` inverts it. The platform's own X link
— "route 2", recorded as dead in `RESULT_caller_wallets.md` §1 because `x_username` is
null on every frontend-api-v3 profile — is alive on the other backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# hosts
# ---------------------------------------------------------------------------

#: pump's own API. No auth, no key. Identity + the follow graph.
FRONTEND_V3 = "https://frontend-api-v3.pump.fun"

#: The social content backend. Note the domain: this is NOT a pump.fun host, and the
#: distinction matters for the threat model — content served from here is attributed to
#: pump wallets by a third party we do not control.
COIN_COMMUNITIES = "https://api.coin-communities.xyz"

#: Where `shitcoims_intelligence.adapters.pump_callouts` points. It is disabled-by-default
#: and requires a private bearer credential nobody has. See MIGRATION_NOTE below.
ADVANCED_V2 = "https://advanced-api-v2.pump.fun"

#: Candles. Already used by `studies/imitation_signal.py`; catalogued for completeness.
SWAP_API = "https://swap-api.pump.fun"

MIGRATION_NOTE = """\
`shitcoims_intelligence/adapters/pump_callouts.py` is a disabled-by-default adapter for
`advanced-api-v2.pump.fun/callouts` that requires a private bearer token
(`PUMP_CALLOUTS_API_TOKEN`) which was never obtained, so the callout feed has never been
collected. The same callouts — with strictly MORE per-item structure (wallet, entry price,
entry market cap, realized multiplier, time-to-peak) — are readable today from
`api.coin-communities.xyz` with a key that ships in every browser. That adapter is not
touched by this package (it is a live money-adjacent tree); this is recorded so the
decision to retire or repoint it is made deliberately rather than by forgetting.
"""

#: The public client key, lifted verbatim from pump.fun's JS bundle
#: (`chunks/*.js`: `if ("apiKey" === e.type) return "cc_367f…"`). It is shipped to every
#: browser that loads pump.fun, so it is a PUBLIC identifier and not a secret: it is
#: committed here for the same reason a user-agent string is, and it must never be treated
#: as a credential, put in a secrets file, or rotated into config as if it were one. If it
#: stops working the fix is to re-mine the bundle, and `probe.py` is what tells you.
PUBLIC_API_KEY = "cc_367f1420841bfb46f31196f4520eff89cdacc311fe001109d181f7675bd7f131"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

Auth = Literal["none", "api_key", "bearer_user", "server_secret"]

Verdict = Literal[
    "live",          # measured 200 with a usable body
    "dead",          # measured 404/410 — declared by the client, absent in production
    "auth_walled",   # measured 401/403 — exists, needs a credential we do not have
    "unmeasured",    # catalogued from the bundle, never probed (all mutating routes)
]


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One route. `path` is a template; `{...}` placeholders are filled by the client."""

    name: str
    host: str
    method: str
    path: str
    auth: Auth
    verdict: Verdict
    #: True for anything that changes state on pump.fun as us — posting, following,
    #: liking, reporting. The client REFUSES these structurally (see `client.py`); they
    #: are catalogued so the surface map is complete and so the refusal is auditable
    #: against a list rather than a regex over method names.
    mutating: bool = False
    note: str = ""
    #: Names of query parameters that are known to work, measured.
    params: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------

ENDPOINTS: tuple[Endpoint, ...] = (
    # -- frontend-api-v3: identity ------------------------------------------------
    Endpoint(
        "user_search", FRONTEND_V3, "GET", "/users/search", "none", "live",
        params=("searchTerm",),
        note="`searchTerm` is the ONLY live param. `username=` and `q=` return 200 with "
             "[] for every input including ones that exist — a silent lie, and the "
             "documented cause of a confident-zero in RESULT_caller_wallets.md §1.",
    ),
    Endpoint(
        "user_profile_v3", FRONTEND_V3, "GET", "/users/{key}", "none", "live",
        note="TRAP: `{key}` resolves an address OR a USERNAME, and returns whichever "
             "profile matched. `/users/batch` is not a batch endpoint — it returns the "
             "real user whose username is literally 'batch' "
             "(He7it3jD9BQ2wHLfJUSvAw1AZK3VoMPPu2ZeDdMAWv3v). Any caller that meant an "
             "address lookup MUST check the echoed `address` field against what it asked "
             "for; `client.profile()` does this and raises otherwise. Carries "
             "`last_username_update_timestamp`, which is how the homoglyph impersonator "
             "in wallet_labels.yaml was caught dressing up five days after picking its "
             "target. Unknown key gives a real 404 with `message: User not found`.",
    ),
    Endpoint(
        "following_v3", FRONTEND_V3, "GET", "/following/{address}", "none", "live",
        params=("limit", "offset"),
        note="THE FOLLOW GRAPH. Out-edges only. Each edge carries `timestamp` (ms, when "
             "the follow happened), plus the target's `username`, `address` and current "
             "`followers`. limit/offset paginate. There is NO in-edge route: "
             "`/followers/{address}` is 404, so the graph is crawlable only forwards, and "
             "a follower COUNT is available (profile) where a follower LIST is not.",
    ),
    Endpoint(
        "balances_v3", FRONTEND_V3, "GET", "/balances/{address}", "none", "dead",
        params=("limit", "offset"),
        note="Token balances for a wallet. Present holdings only, no history.",
    ),
    Endpoint(
        "coin_v3", FRONTEND_V3, "GET", "/coins/{mint}", "none", "live",
        note="Coin metadata incl. creator. RESULT_llm_filter.md §176 warns this is TODAY's "
             "state — it is not a historical record and must not be joined to past tape as "
             "if it were.",
    ),
    Endpoint(
        "coins_search_v3", FRONTEND_V3, "GET", "/coins", "none", "live",
        params=("searchTerm", "creator", "limit", "offset"),
        note="Coin search. `searchTerm=dregg` returns impostor coins sharing the ticker — "
             "useful as an impersonation probe, hazardous as a resolver.",
    ),
    Endpoint(
        "currently_live_v3", FRONTEND_V3, "GET", "/coins/currently-live", "none", "live",
        params=("limit", "offset"),
    ),
    Endpoint(
        "sol_price_v3", FRONTEND_V3, "GET", "/sol-price", "none", "live",
        note="Carries its own `asOfTimestamp` and a `stale` flag — a source that states "
             "its own staleness, which is rare enough to be worth using.",
    ),

    # -- frontend-api-v3: measured dead -------------------------------------------
    Endpoint("replies_mint_v3", FRONTEND_V3, "GET", "/replies/{mint}", "none", "dead",
             note="Comments are NOT on this host. See coin-communities `messages_public`."),
    Endpoint("replies_latest_v3", FRONTEND_V3, "GET", "/replies/latest", "none", "dead"),
    Endpoint("replies_user_v3", FRONTEND_V3, "GET", "/replies/user/{address}", "none", "dead"),
    Endpoint("followers_v3", FRONTEND_V3, "GET", "/followers/{address}", "none", "dead",
             note="No in-edge route exists. The follow graph is one-directional to us."),
    Endpoint("holders_v3", FRONTEND_V3, "GET", "/coins/{mint}/holders", "none", "dead"),
    Endpoint("trades_v3", FRONTEND_V3, "GET", "/trades/all/{mint}", "none", "dead"),

    # -- frontend-api-v3: pump's OWN callouts, wallet-keyed and live ----------------
    # This family is the single most valuable thing in this catalogue and the repo has
    # never had it. `shitcoims_intelligence/adapters/pump_callouts.py` was pointed at
    # `advanced-api-v2/callouts` behind a bearer token nobody obtained, so the callout
    # feed has never been collected. It is here, unauthenticated, keyed by WALLET.
    Endpoint(
        "callout_recent", FRONTEND_V3, "GET", "/callout/recent", "none", "dead",
        params=("limit", "pageToken"),
        note="MEASURED DEAD 2026-08-29: HTTP 400 `Validation failed (uuid is expected)` — "
             "the router now swallows the path as /callout/{callout_id}, so the route is "
             "gone in effect while pump's own webapp still ships code calling it (their "
             "recent tab throws too). Possibly a server-side regression; dregg_archive "
             "re-measures it every cycle and self-heals when it returns. WHEN LIVE it was: "
             "THE LIVE CALLOUT FIREHOSE. Observed returning calls made in the SAME SECOND "
             "as the request — unlike coin-communities' `feed_public`, which served a "
             "cache days old. Each item: `userId` (which is a WALLET ADDRESS on this "
             "family, not a UUID — the two id systems collide on the same field name and "
             "that is the single easiest way to corrupt a join here), `coinMint`, "
             "`thesis` (the call text), `calloutPrice`, `marketCap`, `multiple`, "
             "`maxPriceSol`, `peakTimestamp`, `createdAt` (ms). Pagination is "
             "`nextPageToken`, a base64 JSON cursor "
             "`{\"score\": <ms>, \"member\": \"<wallet>|<ms>|<calloutId>\"}` — it is a "
             "keyset cursor, so it is stable under insertion, which a plain offset is not.",
    ),
    Endpoint(
        "callout_top", FRONTEND_V3, "GET", "/callout/top/{mint}", "none", "live",
        params=("limit",),
        note="Best callouts on one coin by realized multiple. Adds `username`, "
             "`profileImage` and `xUsername` to the recent-feed shape. This is where the "
             "'who called this coin early and was right' question is answered in one "
             "request — on DREGG it names mr589cf at 6.6x from a 232k mcap entry.",
    ),
    Endpoint(
        "callout_list_mint", FRONTEND_V3, "GET", "/callout/list/{mint}", "none", "live",
        params=("limit", "sortBy", "sortOrder", "pageToken"),
        note="`sortBy=TIMESTAMP&sortOrder=DESC`. Returned `{callouts: [], nextPageToken: "
             "''}` for coins that demonstrably HAVE callouts via `callout_top`, so it "
             "appears to serve a recent window rather than all history. Treat an empty "
             "list here as 'none recently', never as 'none ever' — `callout_top` is the "
             "one to ask for history.",
    ),
    Endpoint(
        "callout_replies_by_user", FRONTEND_V3, "GET", "/callout/replies/list/{address}",
        "none", "live",
        params=("limit", "beforeId"),
        note="The richest object on the whole surface, and the ROSETTA STONE between the "
             "two id systems: each row nests a callout carrying BOTH `walletAddress` and "
             "the coin-communities `userId` UUID, plus `userName`, `xUsername`, "
             "`xFollowerCount`, `calledOutAtMcap`, `thesis`, `calloutTimestamp`, `likes`, "
             "`commentCount`, `replyCount`, `maxMultiplier` and an `updates` array. "
             "Keyed by WALLET despite the path reading like a user id.",
    ),
    Endpoint(
        "callout_by_id", FRONTEND_V3, "GET", "/callout/{callout_id}", "none", "live",
        note="SILENT LIE: returns HTTP 200 with `{\"callout\": null}` for callout ids "
             "taken verbatim from `callout_top` seconds earlier. Same genus as "
             "`/users/search?username=` returning `[]` — a 200 that means 'no'. Any caller "
             "must test the payload, not the status. Catalogued live because it answers; "
             "it is not usable as a lookup.",
    ),
    Endpoint(
        "callout_replies_by_id", FRONTEND_V3, "GET", "/callout/{callout_id}/replies",
        "none", "live",
        params=("limit", "filter"),
        note="`filter=ALL|AUTHOR_ONLY`. Returned `{replies: []}` for the same ids that "
             "`callout_by_id` cannot resolve — consistent with those ids being stale "
             "rather than the route being broken.",
    ),
    Endpoint(
        "callout_leaderboard", FRONTEND_V3, "GET", "/callout/leaderboard", "none",
        "auth_walled",
        note="401. The ONE caller-ranking surface that needs a credential. Per-wallet "
             "stats remain free via coin-communities `wallet_callout_stats`, so the "
             "leaderboard is reconstructible one caller at a time from a wallet list we "
             "supply — which is the right shape anyway, since the operator cares about "
             "the callers they follow, not the global top 100.",
    ),
    Endpoint(
        "coins_search_unrestricted", FRONTEND_V3, "GET", "/coins/search-unrestricted",
        "none", "live",
        params=("searchTerm", "limit"),
        note="A better coin search than `/coins?searchTerm=`: for 'dregg' it returns the "
             "REAL DREGG first, where the other route led with an impostor sharing the "
             "ticker.",
    ),

    # -- coin-communities: MEASURED DEAD 2026-08-29 --------------------------------
    # The entire backend was decommissioned between 2026-08-15 (all verdicts below
    # measured live) and 2026-08-29 (probe: every route 404, the POST batches 405).
    # The callout family had already been duplicated onto frontend-api-v3, which now
    # even inlines the coin-communities `user_uuid` on `callout_top` rows — the two-id
    # rosetta join without the second backend. Sole survivor: `user_by_wallet`.
    # Entries keep their original notes: they document what the shapes WERE, which is
    # what any reader of bodies archived before the drift needs.
    Endpoint(
        "community", COIN_COMMUNITIES, "GET", "/api/v1/communities/{mint}", "api_key", "dead",
        note="Per-coin community header: internal `community.id`, postCount, memberCount, "
             "totalLikes, latestPostAt. `memberCount` is a live attention proxy that costs "
             "one request and does not exist anywhere on-chain.",
    ),
    Endpoint(
        "messages_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/messages/public", "api_key", "dead",
        params=("limit", "cursor"),
        note="THE COMMENT THREAD. Each message: id, userId, username, content, createdAt, "
             "likeCount, replyCount, parentMessageId, parentCalloutId, isSpam, isHarmful, "
             "mentions, and `walletAddress` — the author as a native address.",
    ),
    Endpoint(
        "message_replies_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/messages/{message_id}/replies/public", "api_key", "dead",
        params=("limit", "cursor"),
        note="MEASURED 404, and this one is a genuine hole rather than a wrong guess. The "
             "parent message reports `replyCount: 1`, the reply is NOT in the top-level "
             "`messages_public` listing, and this route — the one the bundle declares for "
             "fetching it — is not served publicly. So comment replies are COUNTABLE BUT "
             "NOT READABLE without a user bearer token. Note the asymmetry with "
             "`callout_replies_public`, which IS live: callout threads come back whole, "
             "comment threads come back as roots plus a count. Any 'comments on this coin' "
             "figure built from this API is a count of ROOTS, and the reply tail is "
             "censored — recorded, not silently missing.",
    ),
    Endpoint(
        "message_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/messages/{message_id}/public", "api_key", "dead",
        note="A REDUCED projection: id, username, displayName, profileImageUrl, content, "
             "likeCount, replyCount — and notably NO `walletAddress` and NO `createdAt`. "
             "The listing route carries strictly more. Never use this to attribute a post "
             "to a wallet; it cannot.",
    ),
    Endpoint(
        "callouts_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/callouts/public", "api_key", "dead",
        params=("limit", "cursor"),
        note="THE CALLOUTS, with the platform's OWN scoring attached to each one: "
             "`calloutPrice` and `calloutMarketCap` at the moment of the call, plus "
             "`multiplier`, `maxMultiplier` and `maxMultiplierAt`. Read the multiplier "
             "fields with care — see `models.Callout` for why they are a peak and not a "
             "return.",
    ),
    Endpoint(
        "callout_replies_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/callouts/{callout_id}/replies/public", "api_key", "dead",
        params=("limit", "cursor"),
    ),
    Endpoint(
        "callout_public", COIN_COMMUNITIES, "GET",
        "/api/v1/communities/{mint}/callouts/{callout_id}/public", "api_key", "dead",
    ),
    Endpoint(
        "feed_public", COIN_COMMUNITIES, "GET", "/api/v1/feed/public", "api_key", "dead",
        params=("limit", "cursor"),
        note="Global cross-coin post feed. Carries its own `computedAt` — the body is a "
             "CACHE with a stated age, so `t_event` and freshness are separable. Observed "
             "lagging real time by days; never treat it as a live firehose.",
    ),
    Endpoint(
        "top_communities", COIN_COMMUNITIES, "GET", "/api/v1/communities/top", "api_key", "dead",
        params=("limit",),
        note="Ranked by member count — a social trending board independent of price.",
    ),
    Endpoint(
        "communities_batch", COIN_COMMUNITIES, "POST", "/api/v1/communities/batch",
        "api_key", "dead",
        note="POST-shaped READ (a body carries the key list, nothing is mutated). Body is "
             "`{\"tokenAddresses\": [...]}`, and — unlike every listing route on this host "
             "— the response is snake_case (`member_count`, `post_count`, `latest_post_at`) "
             "with a per-mint `status`. Two casing conventions in one API is a parser trap; "
             "`models` never shares a field map between the two.",
    ),

    # -- coin-communities: identity + the X join ----------------------------------
    Endpoint(
        "user_by_wallet", COIN_COMMUNITIES, "GET",
        "/api/v1/users/by-wallet/{address}", "api_key", "live",
        note="wallet -> {userId, twitterId, username, profileImageUrl}. `twitterId` is the "
             "X NUMERIC id, which is stable across handle changes — a better join key than "
             "a handle precisely because renaming is the impersonator's move.",
    ),
    Endpoint(
        "users_by_wallet_batch", COIN_COMMUNITIES, "POST",
        "/api/v1/users/by-wallet/batch", "api_key", "dead",
        note="POST-shaped READ. Body `{\"addresses\": [...]}`; returns a per-address map "
             "with a `status` field, so a miss is reported as a miss rather than dropped. "
             "This is the cheap way to resolve a wallet set from the tape.",
    ),
    Endpoint(
        "user_by_twitter_id", COIN_COMMUNITIES, "GET",
        "/api/v1/users/by-twitter-id/{twitter_id}", "api_key", "dead",
        note="X numeric id -> pump userId. The inverse join. Combined with `user_profile` "
             "this turns an X account into a pump wallet, which is the join "
             "RESULT_caller_wallets.md could not make.",
    ),
    Endpoint(
        "user_profile", COIN_COMMUNITIES, "GET",
        "/api/v1/users/{user_id}/profile", "api_key", "dead",
        note="Keyed by the coin-communities UUID, not a wallet. Returns BOTH "
             "`nativeFollowerCount` (pump.fun's own follower count) and `followerCount` "
             "(larger; the union with X). They are different numbers for the same person "
             "and must never be summed or silently swapped — jackduvalcalls reads 17,447 "
             "native vs 44,267 combined.",
    ),
    Endpoint(
        "user_communities", COIN_COMMUNITIES, "GET",
        "/api/v1/users/{user_id}/communities", "api_key", "dead",
        params=("limit", "cursor"),
        note="Which coin communities a user belongs to — a per-person watchlist, and the "
             "closest thing to 'what is this caller currently near'.",
    ),

    # -- coin-communities: caller quality, free ------------------------------------
    Endpoint(
        "wallet_callout_stats", COIN_COMMUNITIES, "GET",
        "/api/v1/leaderboard/callouts/wallets/{address}/stats", "api_key", "dead",
        note="Caller quality keyed by WALLET, one request: totalCallouts, twoXPercent, "
             "onePointFiveXPercent, onePointTwoXPercent, averageMultiple, medianMultiple, "
             "averageTimeToPeak. This is the platform's own scoreboard and it is a PEAK "
             "statistic — see `models.CalloutStats`.",
    ),

    # -- coin-communities: declared by the client, measured 404 --------------------
    Endpoint("followers_cc", COIN_COMMUNITIES, "GET",
             "/api/v1/users/{user_id}/followers", "api_key", "dead",
             note="Declared in the bundle, 404 in production. Use `following_v3`."),
    Endpoint("following_cc", COIN_COMMUNITIES, "GET",
             "/api/v1/users/{user_id}/following", "api_key", "dead",
             note="Declared in the bundle, 404 in production. Use `following_v3`."),
    Endpoint("leaderboard", COIN_COMMUNITIES, "GET",
             "/api/v1/leaderboard/callouts", "api_key", "dead",
             note="404 without parameters we have not found. The per-wallet stats route "
                  "works, so caller quality is reachable one wallet at a time."),
    Endpoint("ranked_callers", COIN_COMMUNITIES, "GET",
             "/api/v1/leaderboard/callouts/ranked", "api_key", "dead"),
    Endpoint("user_callout_stats", COIN_COMMUNITIES, "GET",
             "/api/v1/leaderboard/callouts/users/{user_id}/stats", "api_key", "dead",
             note="404, while the wallet-keyed twin is live. Key caller quality by wallet."),
    Endpoint("user_leaderboard_history", COIN_COMMUNITIES, "GET",
             "/api/v1/leaderboard/callouts/users/{user_id}/history", "api_key", "dead"),
    Endpoint("token_feed_public", COIN_COMMUNITIES, "GET",
             "/api/v1/communities/{mint}/feed/public", "api_key", "dead",
             note="Per-coin feed 404s; the global `feed_public` is live."),

    # -- swap-api: candles, keyless -------------------------------------------------
    Endpoint(
        "swap_candles", SWAP_API, "GET", "/v1/coins/{mint}/candles", "none", "live",
        params=("interval", "limit", "currency"),
        note="OHLC candles priced in SOL (`currency=SOL`). `interval` accepts 1m/5m/1h; "
             "limit=600@5m and limit=200@1h both measured working 2026-08-29 (and 1000@1m "
             "by studies/imitation_signal.py). PARSER TRAP, measured: `timestamp` is an "
             "int (bucket-start ms) but open/high/low/close/volume are DECIMAL STRINGS — "
             "imitation_signal never noticed because float() coerces both. A candle "
             "exists only where trades happened, so a series ends at the LAST TRADE, not "
             "at now — an empty tail is 'no trades', which is data, not a gap. This is "
             "the outcome instrument for dregg_archive: returns are computed from these "
             "closes, never from the provider's own `multiple`.",
    ),

    # -- auth-walled: the profile-api host -----------------------------------------
    Endpoint("profile_api_root", "https://profile-api.pump.fun", "GET",
             "/api/v1/users/by-wallet/{address}", "bearer_user", "auth_walled",
             note="`profileApiUrl` in pump.fun's runtime config. Mirrors the "
                  "coin-communities paths but 401s on every route including `/public` "
                  "ones — the public key is NOT accepted here. Catalogued so the next "
                  "reader does not re-derive that this host is a dead end for us."),

    # -- mutating: catalogued, never called ----------------------------------------
    Endpoint("post_message", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/messages", "bearer_user", "unmeasured", mutating=True),
    Endpoint("post_callout", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/callouts", "bearer_user", "unmeasured", mutating=True),
    Endpoint("post_reply", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/messages/{message_id}/replies", "bearer_user",
             "unmeasured", mutating=True),
    Endpoint("like_message", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/messages/{message_id}/like", "bearer_user",
             "unmeasured", mutating=True),
    Endpoint("unlike_message", COIN_COMMUNITIES, "DELETE",
             "/api/v1/communities/{mint}/messages/{message_id}/like", "bearer_user",
             "unmeasured", mutating=True),
    Endpoint("like_callout", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/callouts/{callout_id}/like", "bearer_user",
             "unmeasured", mutating=True),
    Endpoint("report_message", COIN_COMMUNITIES, "POST",
             "/api/v1/communities/{mint}/messages/{message_id}/report", "bearer_user",
             "unmeasured", mutating=True),
    Endpoint("follow_user", COIN_COMMUNITIES, "POST",
             "/api/v1/users/{user_id}/follow", "bearer_user", "unmeasured", mutating=True),
    Endpoint("unfollow_user", COIN_COMMUNITIES, "DELETE",
             "/api/v1/users/{user_id}/follow", "bearer_user", "unmeasured", mutating=True),
    Endpoint("wallet_signin_challenge", COIN_COMMUNITIES, "POST",
             "/api/v1/users/auth/wallet/challenge", "api_key", "unmeasured", mutating=True,
             note="Wallet-signature login. Reaching it would require SIGNING, which this "
                  "package does not do and must not do. Catalogued as the boundary of the "
                  "read-only surface: everything a bearer token would unlock lies behind "
                  "a signature, and that is where we stop."),
    Endpoint("wallet_signin_verify", COIN_COMMUNITIES, "POST",
             "/api/v1/users/auth/wallet/verify", "api_key", "unmeasured", mutating=True),
)

BY_NAME: dict[str, Endpoint] = {e.name: e for e in ENDPOINTS}

#: Everything this package is willing to call.
READABLE: tuple[Endpoint, ...] = tuple(e for e in ENDPOINTS if not e.mutating)

#: The read routes that are measured working — what a crawl may actually use.
LIVE: tuple[Endpoint, ...] = tuple(e for e in READABLE if e.verdict == "live")


def endpoint(name: str) -> Endpoint:
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(f"unknown endpoint {name!r}; known: {sorted(BY_NAME)}") from None
