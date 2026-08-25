# The pump.fun API surface, mapped from the app that uses it

Status: reconnaissance completed 2026-08-24. Read-only throughout. No route classed MUTATING was
called, and no transaction was constructed, signed, or submitted.

This document answers one question Ember asked — *"maybe there's something we could set up to figure
out what APIs are powering the app?"* — and it answers it by asking the app. The pump.fun web client
is a Turbopack/Next.js bundle. Its complete chunk graph was downloaded and its API surface read out
of the shipped code. That is not inference from behaviour; it is the client's own route table.

`crates/joshi-pump-api/src/catalog.rs` is the pinned catalog this map extends. Nothing here has been
written into it. The proposal is [below](#8-proposal-what-to-add-to-catalogrs-and-in-what-order), as a
proposal.

---

## Contents

1. [The method, so it can be re-run](#1-the-method-so-it-can-be-re-run)
2. [The verdict taxonomy, sharpened](#2-the-verdict-taxonomy-sharpened)
3. [What actually powers the app](#3-what-actually-powers-the-app)
4. [Route inventory by capability](#4-route-inventory-by-capability)
   - [4.1 Discovery and boards](#41-discovery-and-boards)
   - [4.2 Coin detail and price](#42-coin-detail-and-price)
   - [4.3 Callouts and social — the subsurface](#43-callouts-and-social--the-subsurface)
   - [4.4 User, profile, social graph](#44-user-profile-social-graph)
   - [4.5 Holders and the coin social graph](#45-holders-and-the-coin-social-graph)
   - [4.6 Realtime: NATS and the community socket](#46-realtime-nats-and-the-community-socket)
   - [4.7 Mutating routes — mapped, never called](#47-mutating-routes--mapped-never-called)
   - [4.8 Dead, undeployed, and out of scope](#48-dead-undeployed-and-out-of-scope)
5. [The availability clock, answered](#5-the-availability-clock-answered)
6. [The callout/social subsurface in depth](#6-the-calloutsocial-subsurface-in-depth)
7. [Cross-reference against BankkRoll and against our own catalog](#7-cross-reference-against-bankkroll-and-against-our-own-catalog)
8. [Proposal: what to add to catalog.rs, and in what order](#8-proposal-what-to-add-to-catalogrs-and-in-what-order)
9. [What I did not verify, and why](#9-what-i-did-not-verify-and-why)
10. [Counts](#10-counts)

---

## 1. The method, so it can be re-run

Five steps. The whole thing took about 300 HTTP requests, and it converges — the chunk graph closes.

**Step 1 — the app shell.** `GET https://pump.fun/` answers `307 -> /explore`. The response headers
alone are a finding: the **`content-security-policy` `connect-src` directive enumerates every origin
the app is permitted to talk to**. That is an upper bound on the app's network surface, published by
pump.fun, before a single line of JS is read. Anything not in `connect-src` cannot be called by the
web client. Save the headers.

**Step 2 — page shells.** Fetch `/explore`, `/callouts`, `/notifications`, `/leaderboard`,
`/watchlist`, `/live`, `/profile`, `/board`. Each is ~1.5 MB of HTML with an inlined React
Server Component flight payload. Extract `src="/_next/static/chunks/*.js"`. This gives ~72 eagerly
loaded chunks. **The inlined payload also carries runtime configuration** — this is where the NATS
cluster config lives, credentials included.

**Step 3 — close the chunk graph.** Turbopack writes lazy chunk names as literal strings inside the
chunks that import them. So:

```
repeat:
  grep -rhoE '"static/chunks/[^"]+\.js"' js/ | sort -u
  download any name not already present under js/
until a round downloads nothing new
```

This converged in **four rounds: 72 → 163 → 215 → 294 chunks, 15 MB**, round four downloading zero.
294 chunks is the complete client bundle. Re-running this when the app changes is the maintenance
procedure; the deployment id is in the `?dpl=` query on every script src, so a changed `dpl` means
re-run.

**Step 4 — read the route tables out of the code.** Three separate registries exist, and they are
qualitatively different sources:

- **A generated OpenAPI SDK.** `js/132raph.m~bc2.js` contains a
  [`@hey-api/openapi-ts`](https://heyapi.dev)-style client for the coin-communities service. Every
  operation appears as `name:e=>(e.client??w).METHOD({security:[…],url:"/api/v1/…"})`. This yields
  **operation name, HTTP method, path template with named parameters, and the security scheme —
  straight from the service's OpenAPI spec**. 84 operations. This is the highest-grade evidence in
  the whole exercise: it is not observed behaviour, it is the service's own contract.
  Extraction regex:
  ```
  (?:([A-Za-z0-9_$]+):)?\s*e\s*=>\s*\(\s*e\??\.client\s*\?\?\s*[A-Za-z0-9_$]+\s*\)\.
  (get|post|put|patch|delete|head|options)\(\{\s*(security:\[(?P<sec>.*?)\],)?\s*url:\s*"(?P<url>[^"]+)"
  ```
- **A hand-written endpoint-constant module.** `js/0sfs2maqeipt..js` module `38279` holds
  `BASE_URL = {CLIENT, PROFILE, PUMP_SWAP, SWAP_API}` and an `API = {…}` object of URL-builder
  functions. This yields **frontend-api-v3 and swap-api paths together with their query parameters
  and the app's own default values** (e.g. candles default `interval=1m, limit=60`).
- **A service-registry module.** `js/0~twmr9t4c4ou.js` module `503630` exports
  `getClientServerUrl`, `getAdvancedIndexerUrl`, `getAdvancedClientServerUrl`,
  `getBlockchainClientUrl`, `getBlockchainApiServiceUrl`, `getLivestreamServiceUrl`,
  `getPumpSwapClientServerUrl` — the authoritative host list.

Plus a general sweep for path-shaped string and template literals across all 294 chunks, which
catches routes built inline (`/boards/movers`, `/following/v3/following/count/${addr}`).

**Discriminating pump routes from vendored SDK routes matters.** The bundle contains Privy's auth
SDK, WalletConnect, Firebase, Datadog, LiveKit and Mux, all with their own `/api/v1/...` paths. Two
reliable tells: pump's coin-communities SDK uses `{brace}` path parameters, Privy uses `:colon`
parameters; and the service-registry hosts above are the only pump API origins.

**Step 5 — verify live, read-only, and classify.** Nothing from step 4 is promoted on the strength of
appearing in the bundle. Every route quoted below carries a verdict from an actual GET, or is
explicitly marked unverified. 48 routes were probed in the first sweep plus follow-ups.

### Reproducing the credential-bearing bits

Two shipped-to-every-browser credentials are needed to reproduce parts of this. **They are not
transcribed here** — this repo's rule is that credential material does not land in docs or fixtures,
and `auth_session.rs` is emphatic about it. They are public by construction, they rotate, and a
stale copy in a doc would be worse than useless. Extract them at use time:

```sh
# coin-communities public API key (x-api-key header), ~64 hex chars prefixed cc_
grep -o 'cc_[0-9a-f]\{64\}' js/00-w7vn6gf65..js

# NATS cluster credentials for all five realtime clusters
python3 -c "import re,sys;s=open('explore.html').read().replace(chr(92)+chr(34),chr(34));\
print(re.findall(r'\"(ADVANCED|CORE|PUMP_SWAP|UNIFIED|MULTICHAIN)\"\s*:\s*\{(.{0,400}?)\}',s,re.S))"
```

The coin-communities key is `cc_367f14…f131` (64 hex, elided). Every visitor's browser sends it. It
buys a **shared global budget of roughly one request per second** — see §4.3.

---

## 2. The verdict taxonomy, sharpened

`/callout/recent` was catalogued for three days as a real global feed because a 400 looked like a
route. This exercise found the discriminator that would have caught it in one call, and it is worth
stating plainly because it generalises:

> **frontend-api-v3 and swap-api are NestJS. NestJS's unrouted 404 body says
> `"message":"Cannot GET /the/path"`. Any other 404 or 400 body means a handler caught the request.**

That single distinction separates four cases that all look like failure:

| Verdict | Signature | Meaning |
|---|---|---|
| `LIVE` | 200, expected shape | Route exists and answers |
| `ROUTED-REFUSED` | 404, `"message":"Not Found"`, no `"error"` field | **Route exists**; its handler declined this subject |
| `UNROUTED` | 404, `"message":"Cannot GET /path"` | No handler is bound. This is the phantom signature |
| `VALIDATION` | 400, e.g. `"Validation failed (numeric string is expected)"` | **Route exists**; the parameter was the wrong type |
| `GATED` | 401 | Route exists, needs a session |
| `DEGRADED` | 503 | Route exists, upstream is down |
| `THROTTLED` | 429 + `retry-after` | **Not a verdict.** Re-probe with backoff |

Two live demonstrations from this sweep:

- `/global-params/{mint}` → `400 "Validation failed (numeric string is expected)"`. This is the
  *exact same shape* as the `/callout/recent` phantom's `400 (uuid is expected)` — but here it
  proves the route is **real** and takes a numeric id. The phantom's lesson was never "a 400 means
  no route"; it was "the 400 tells you what the router bound, and `recent` was not it." Read the
  message, not the status.
- `/coins/top-holders/{mint}` → `404 {"message":"Not Found"}` with **no `"error"` key**, on two
  different mints, while `/kols` on the same host → `404 {"message":"Cannot GET /kols","error":"Not
  Found"}`. The first is a live route refusing a subject; the second is a retired route. Treating
  both as "404, dead" would have thrown away a holders endpoint.

The coin-communities service is not NestJS and answers with **empty-bodied 404s**, which carry no
such information. There, in-bundle-but-404 is genuinely ambiguous between "undeployed" and "gated
differently", and is recorded as such rather than resolved by guessing.

---

## 3. What actually powers the app

**The single best answer: pump.fun's frontend is not one API. It is seven HTTP services and six
websocket clusters, and the parts Ember cares about most are not on the host our catalog points at.**

If you want the one-sentence version: **the callouts, the feed, the likes, the replies and the
social graph are served by a separate product called coin-communities, at
`https://api.coin-communities.xyz`, authenticated by a public API key rather than by her SIWS
session — and it ships its own OpenAPI contract inside the page.**

The service registry, read out of `js/0~twmr9t4c4ou.js`:

| Origin | Role | In our catalog? |
|---|---|---|
| `https://frontend-api-v3.pump.fun` | Core coin/user/board API | Yes |
| `https://swap-api.pump.fun` | Candles, trades, market activity, fee sharing | Yes |
| `https://profile-api.pump.fun` | Wallet balances | Yes |
| `https://api.coin-communities.xyz` | **Callouts, feeds, messages, social graph** | Aliased, wrongly |
| `https://advanced-indexer.pump.fun` | **Boards, in-memory coin state** | **No** |
| `https://advanced-api-v2.pump.fun` | Advanced trading client | No |
| `https://fun-block.pump.fun`, `https://blockchain-swap.pump.fun` | Chain/swap services | No |
| `https://livestream-api.pump.fun` | Livestreams | No |
| `wss://prod-v2 · prod-advanced · amm-prod · unified-prod · multichain-prod .nats.realtime.pump.fun` | **Realtime event bus (NATS)** | **No** |
| `wss://api.coin-communities.xyz/…/ws` | **Per-coin social push** | **No** |
| `wss://livechat.pump.fun` | Live chat | Reconnaissance-only |

Three structural facts follow, and each is more consequential than any individual route:

1. **The app is push-driven; JOSHI is poll-driven.** The web client subscribes to NATS clusters for
   trades and coin creation and only polls HTTP for the initial page. Every latency number JOSHI has
   measured is a polling artefact of our own architecture, not a property of the provider.
2. **`profile-api.pump.fun` and `api.coin-communities.xyz` are not the same service.** Our catalog
   has `CommunityMessages`/`CommunityCallouts` pointed at `profile-api.pump.fun/api/v1/communities/…`
   and marked `AuthenticatedUserSession` / `AuthenticatedUnverified`. The companion extension's
   allowlist has both hosts. The live service, with the contract, is coin-communities — and the
   `/public` variants of those routes are **anonymous**, needing only the public API key. This is
   catalogued as needing a session that it does not need.
3. **A whole discovery service is missing from our map.** `advanced-indexer.pump.fun` carries
   per-coin volume, trade counts and a server timestamp — the exact fields `catalog.rs` documents as
   *"THE FIELD THAT IS NOT HERE"* on `/coins`.

---

## 4. Route inventory by capability

Verdict key: `LIVE` verified 200 this session · `ROUTED-REFUSED` / `UNROUTED` / `VALIDATION` /
`GATED` / `DEGRADED` per §2 · `BUNDLE` found in shipped code, not called · `SDK-404` in the
generated contract but the server 404s · `STALE-DEAD` in BankkRoll, now unrouted.

All verified against mint `9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump` (ANSEM) and creator wallet
`yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe`, 2026-08-24 ~19:00–19:20 UTC.

### 4.1 Discovery and boards

| Method · Path | Origin | Auth | Returns | Pagination | Verdict |
|---|---|---|---|---|---|
| `GET /boards/movers` | advanced-indexer | anon | `{board, version, serverTs, entries[]}` | `limit` ≤150 | **LIVE** |
| `GET /in-memory-coin/{mint}` | advanced-indexer | anon | rich live coin state | none | **LIVE** |
| `GET /coins/great-coins` | frontend-api-v3 | anon | array of coin records (5) | none observed | **LIVE** |
| `GET /coins/similar?mint&limit&offset&includeNsfw` | frontend-api-v3 | anon | array of coin records | offset/limit | **LIVE** |
| `GET /coins/mayhem-mode?limit&mayhemState` | frontend-api-v3 | anon | array of coin records | `limit` (default 60) | **LIVE** |
| `GET /mayhem/overview` | frontend-api-v3 | anon | `{activeCoins, agentVolumeUsd, coinsCreated, distinctTraders, updatedAt}` | none | **LIVE** |
| `GET /mayhem/top-coins?window` | frontend-api-v3 | anon | `{items, updatedAt, window}` | none | **LIVE** |
| `GET /mayhem/top-traders?window` | frontend-api-v3 | anon | `{items, updatedAt, window}` | none | **LIVE** |
| `GET /pnl-leaderboard?period&sort&limit` | frontend-api-v3 | anon | `{entries[]}` | `limit` | **LIVE** |
| `GET /pnl-leaderboard/rank?wallet&period&sort` | frontend-api-v3 | **SIWS** | one wallet's rank | none | **GATED (401)** |
| `GET /pnl-leaderboard/competition?competitionId&sort&limit` | frontend-api-v3 | ? | competition board | `limit` | **BUNDLE** |
| `GET /coins-v2/{mint}/mayhem-state` | frontend-api-v3 | anon | `null` for a non-mayhem coin | none | **LIVE** |

**`/boards/movers` is the most valuable single discovery in this document.** Envelope:

```json
{"board":"movers","version":0,"serverTs":1787599056259,"entries":[…]}
```

- `serverTs` is **epoch milliseconds, provider-stated**. This is a real availability instant on a
  discovery feed — the first one in this whole surface. See §5.
- Rows use compact keys. The app's own decoder (`js/09373ik9or5q1.js`, function `b`) gives an
  **authoritative** mapping for the ones it reads:

  | Key | Meaning (measured — from the app's decoder) |
  |---|---|
  | `m` `n` `t` `i` | mint · name · symbol · image_uri |
  | `mc` | `usd_market_cap` |
  | `age` | **seconds since creation** (the decoder computes `created_timestamp = Date.now() - age*1000`) |
  | `gd` | graduation; `complete` iff `gd > 0` |
  | `dw` | creator/dev wallet |
  | `pl` | platform · `lv` is_currently_live · `desc` description · `vid` video_uri |
  | `ic` | is_charity · `rid` recommendation id · `ms` mayhem_state |

- The remaining keys are **present on the wire and NOT decoded by the app**, so their meaning is
  *inferred, not measured*, and is flagged as such: `v v5 v15 v1h v24h` and `vUsd vUsd5 vUsd15
  vUsd1h vUsd24h` (volume in SOL and USD over 5m/15m/1h/24h windows), `tx5` `txc` (trade counts),
  `p` (bonding-curve progress; 100 on a graduated coin), `c` (chain, `"solana:mainnet"`),
  `nh` `ih` `mh` `t10` `dh` (holder-shaped), `kol` `sn` `sc` `so` `hs` `bc` `bo` `cb` `np` `pa`
  `pg` `ath` `tf` `tfUsd` `tg` `tw` `ws`. **Do not retain any of these under a semantic name until
  a reviewed-schema artifact pins it.** Naming an undecoded field is how a fabricated number gets
  born, and this repo has done that once already.
- **`rid` is a recommendation id, and the URL builder accepts `userId`, `session_id` and `country`.**
  This board is a *personalised recommendation feed*, not a neutral census. Position is not rank, and
  two clients can be served different boards. Treat exactly as `CurrentlyLive` is treated.

**`/in-memory-coin/{mint}`** returns `mint, chain, name, ticker, dev, program, platform,
creationTime, quoteMint, pair, marketCapUsd, volumeSol, volumeUsd, progress, graduationDate, …`.
Anonymous, no API key. `volumeSol`/`volumeUsd` are cumulative and directly address the catalog's
standing complaint that no coin route carries volume.

### 4.2 Coin detail and price

| Method · Path | Origin | Auth | Returns | Verdict |
|---|---|---|---|---|
| `GET /coins-v3/{mint}?includeLiveStreamInfo=` | frontend-api-v3 | anon | one coin record | **LIVE** |
| `GET /v2/coins/{mint}/candles?createdTs&interval&limit` | swap-api | anon | OHLCV array | **LIVE** |
| `GET /v1/coins/{mint}/line-chart?createdTs&timeframe&width` | swap-api | anon | `[{price,time}]` (108 pts at `width=72`) | **LIVE** |
| `GET /v1/coins/{mint}/market-activity` | swap-api | anon | `{"5m","1h","6h","24h"}` | **LIVE** |
| `GET /v1/coins/{mint}/first-trade` | swap-api | anon | first fill, incl. `isDevBuy`, `slotIndexId` | **LIVE** |
| `GET /v1/coins/{mint}/ath` | swap-api | anon | `{athMarketCap}` | **LIVE** |
| `GET /v1/coins/{mint}/mayhem-stats` | swap-api | anon | — | **DEGRADED (503)** |
| `GET /coins-v2/user-created-coins/{wallet}?limit&offset` | frontend-api-v3 | anon | `{coins,count,limit,offset}` | **LIVE** |
| `POST /coins-v2/mints`, `POST /v1/coins/ath/batch`, `POST /v1/coins/market-activity/batch`, `POST /v1/coins/{mint}/trades/batch`, `POST /coin-narrative/by-mints` | frontend-api-v3 / swap-api | ? | batch reads | **BUNDLE, not called** — see §9 |

**Two version bumps our catalog has missed.**

- `catalog.rs` pins `CoinExact` at `/coins-v2/{mint}`. **The app calls `/coins-v3/{mint}`.**
  Measured this session: fetching the same mint from both, the key sets are **identical — 50 keys,
  zero difference in either direction**. So this is a safe migration, on the evidence of one coin.
  Caveat honestly: one coin, and `includeLiveStreamInfo=true` was not exercised and may add keys.
- `catalog.rs` pins `Candles` at `/v1/coins/{mint}/candles`. **The app calls
  `/v2/coins/{mint}/candles`, and passes `createdTs`.** Our note records `before` as inert with a
  newest-anchored window and history reachable only via trades. `createdTs` is a parameter the app
  supplies and we do not, and it is the obvious candidate for anchoring a window — **untested here**,
  and worth exactly one experiment because it would change what history is reachable.

### 4.3 Callouts and social — the subsurface

This is the part Ember most wants, and it is a different service from the one we have been reading.

**Host `https://api.coin-communities.xyz`. Auth: `x-api-key` header on `/public` routes (the key is
in the bundle; every browser sends it), `Authorization: Bearer` for personalised routes, and
`x-server-key`+`x-server-secret` on `/server` routes which are server-to-server and out of scope.**

**Rate limit, measured:** the public key carries a very tight shared budget — sustained probing
returns `429` with `retry-after: 1`. Individual calls succeed after 1–5 retries at 3 s spacing.
Because the key is global, **the budget is shared with every pump.fun visitor on earth**, so
throughput is not a thing to plan around and a `429` must never be recorded as absence.

| Method · Path | Auth | Returns | Verdict |
|---|---|---|---|
| `GET /api/v1/communities/{mint}/callouts/public` | api-key | `{callouts:[50]}` | **LIVE** |
| `GET /api/v1/communities/{mint}/callouts/{callout_id}/public` | api-key | `{callout}` | **LIVE** |
| `GET /api/v1/communities/{mint}/callouts/{callout_id}/replies/public` | api-key | `{replies:[]}` | **LIVE** |
| `GET /api/v1/communities/{mint}/messages/public` | api-key | `{messages:[50]}` | **LIVE** |
| `GET /api/v1/communities/{mint}/messages/{message_id}/public` | api-key | one message | **BUNDLE** |
| `GET /api/v1/communities/{mint}` | api-key | community summary | **LIVE** |
| `GET /api/v1/communities/top` | api-key | `{communities:[…]}` | **LIVE** |
| `GET /api/v1/feed/public` | api-key | `{items:[…], computedAt}` | **LIVE but STALE — see below** |
| `GET /api/v1/users/{user_uuid}/profile` | api-key | `{user:{…}}` | **LIVE** |
| `GET /health` | none | `Healthy` | **LIVE** |
| `GET /api/v1/leaderboard/callouts` | api-key | caller leaderboard | **SDK-404** |
| `GET /api/v1/leaderboard/callouts/ranked` | api-key | ranked callers | **SDK-404** |
| `GET /api/v1/leaderboard/callouts/users/{user_id}/history` | api-key | caller history | **BUNDLE** |
| `GET /api/v1/leaderboard/callouts/users/{user_id}/stats` | api-key | caller stats | **BUNDLE** |
| `GET /api/v1/leaderboard/callouts/wallets/{address}/stats` | api-key | wallet callout stats | **BUNDLE** (429 only) |
| `GET /api/v1/users/{user_id}/callouts` | bearer + api-key | one caller's callouts | **SDK-404** |
| `GET /api/v1/users/by-wallet/{address}/callouts` | bearer + api-key | callouts by wallet | **BUNDLE** |
| `GET /api/v1/users/{user_id}/callouts/by-mint/{mint}` | bearer + api-key | one caller on one coin | **BUNDLE** |
| `GET /api/v1/communities/{mint}/feed/public` | api-key | per-coin feed | **SDK-404** |
| `GET /api/v1/communities/{mint}/members` | bearer + api-key | member list | **GATED (401)** |
| `GET /api/v1/communities/{mint}/callouts/eligibility` | bearer + api-key | may I call out | **BUNDLE** |
| `GET /api/v1/mock/{mint}/holders`, `/api/v1/mock/callouts/feed`, `/api/v1/mock/{mint}/feed`, `/api/v1/mock/callouts/by-mint/{mint}` | none | scaffolding | **SDK-404** |

And on `frontend-api-v3`, the routes our catalog already knows, re-confirmed live this session:
`/callout/top/{mint}` **LIVE** (`x-ratelimit-limit: 50`), `/callout/list/{user}` unchanged,
`/callout/leaderboard` still the SIWS-gated global caller board.

### 4.4 User, profile, social graph

| Method · Path | Origin | Auth | Returns | Verdict |
|---|---|---|---|---|
| `GET /following/followers/{wallet}` | frontend-api-v3 | anon | **array of 1000 follower records** (`address, username, profile_image, followers, timestamp`) | **LIVE** |
| `GET /following/v3/following/count/{wallet}` | frontend-api-v3 | anon | `{count}` | **LIVE** |
| `GET /following/v3/followers/count/{wallet}` | frontend-api-v3 | anon | `{count}` (9363 on the test wallet) | **LIVE** |
| `GET /profiles/verified` | frontend-api-v3 | anon | array of 50 rich profiles | **LIVE** |
| `GET /auth/disabled-features` | frontend-api-v3 | anon | `{all, livestreams}` | **LIVE** |
| `GET /auth/my-profile` | frontend-api-v3 | **SIWS** | own profile | **GATED (401)** |
| `GET /users/{key}`, `POST /users/batch` | frontend-api-v3 | anon/? | profile(s) | catalogued / **BUNDLE** |
| `GET /api/v1/users/by-wallet/{address}` | coin-communities | api-key | wallet → user uuid | **BUNDLE** (429 only) |
| `GET /api/v1/users/by-twitter-id/{twitter_id}` | coin-communities | api-key | twitter → user | **BUNDLE** |
| `GET /api/v1/users/{user_id}/followers` · `/following` · `/communities` | coin-communities | api-key | social graph | **SDK-404** / **BUNDLE** |
| `GET /v3/followers/count/{wallet}` | frontend-api-v3 | — | — | **UNROUTED** (the working path is under `/following/`) |

`/following/followers/{wallet}` returning **1000 rows in one anonymous call** is the largest
single social-graph read in this surface, and it is not in our catalog. Whether 1000 is a cap or the
true degree is untested; the test wallet's `followers/count` says 9363, so **1000 is a cap** and the
route is a truncated sample, not a census. That is exactly the `/coins` silent-clamp family and must
be recorded the same way.

Note also `/following/v3/followers/count` vs the unrouted `/v3/followers/count`: BankkRoll lists the
latter. The prefix moved.

### 4.5 Holders and the coin social graph

Ember's screenshot showing *"N holders including X and Y"* implies a holders-in-common join. The
finding here is a genuine gap, honestly stated:

- **`GET /coins/top-holders/{mint}` on frontend-api-v3 is `ROUTED-REFUSED`** — 404 with a bare
  `"Not Found"` and no `"error"` key, on two different mints. By §2 the route **exists**; its
  handler declined. Plausibly it needs a session, a different identifier, or an index that is not
  populated for these mints. **This is the highest-value single unresolved question in the map** and
  it is one authenticated retry away from being answered.
- **`POST /pnl/coin/{mint}/holders`** appears in BankkRoll's 2026-06-17 capture with an observed CORS
  preflight, meaning the app really called it. Not called here (§9). This is the likeliest source of
  the holders-with-PnL panel.
- `GET /api/v1/mock/{mint}/holders` on coin-communities is in the SDK under a `mock` namespace and
  404s. Scaffolding for a feature not yet shipped to this surface.
- No holders-in-common route was found anywhere in 294 chunks.

**Conclusion: holders are reachable, but not through any route verified in this pass.** Do not
promote anything here without one more targeted, authenticated probe.

### 4.6 Realtime: NATS and the community socket

**Five NATS clusters over websocket, credentials inlined in every page's HTML** (see §1 for
extraction; user is `subscriber` on all five, passwords are 16 chars):

| Cluster | Server |
|---|---|
| `CORE` | `wss://prod-v2.nats.realtime.pump.fun` |
| `ADVANCED` | `wss://prod-advanced.nats.realtime.pump.fun` |
| `PUMP_SWAP` | `wss://amm-prod.nats.realtime.pump.fun` |
| `UNIFIED` | `wss://unified-prod.nats.realtime.pump.fun` |
| `MULTICHAIN` | `wss://multichain-prod.nats.realtime.pump.fun` |

Connection options are inlined too: `timeout 5000, reconnect true, reconnectTimeWait 1000,
maxReconnectAttempts -1, pingInterval 5000, maxPingOut 2`. The account name `subscriber` is a
strong hint the credential is scoped to subscribe only; **that is an inference, not a measurement** —
no publish was attempted and none should be.

Subjects found in the bundle (`js/09373ik9or5q1.js`, `js/0g8bsduq_nrfc.js`):

| Subject | Cluster | Carries |
|---|---|---|
| `newCoinCreated.prod` | CORE | new coin creation — **a live t=0 for every coin** |
| `unifiedTradeEvent.lite.{mint}` | UNIFIED | per-mint trade events, coalescing |
| `unifiedTradeEvent.processed` | UNIFIED | processed trade events |
| `unifiedCoinCreationEvent` | UNIFIED | coin creation |
| `multichain.trade.*` | MULTICHAIN | cross-chain trades |
| `mayhemTradeEvent`, `mayhemState` | — | mayhem-mode events |

**The per-coin community socket** — this is the callout push channel, and its protocol is fully
specified in `js/132raph.m~bc2.js`:

- URL: `wss://api.coin-communities.xyz/api/v1/communities/{token_address}/ws?ticket={ticket}`
  (the SDK's OpenAPI names the segment `token_address`; the value is the coin mint. An earlier
  draft here rendered it `{mint}` — corrected 2026-08-24 against the generated client.)
- Ticket from `POST /api/v1/communities/{token_address}/ws/ticket` (bearer + api-key). The bearer is
  a coin-communities session (`crate::community_session`), NOT the pump SIWS session.
- Client → server: `{"eventType":"ping"}`; server → client: `pong`, **`message_update`**,
  **`like_update`**, **`moderation_update`**.
- The client models loss explicitly: a reconnect fires an `onGap` callback to every subscriber.
  Whatever we build should keep that property — a gap must be recordable as a gap.

**Measured, and it corrects the code:** the JS has a branch that connects with no ticket when no auth
is configured. **The server rejects it.** An anonymous HTTP/1.1 upgrade returns
`400 Failed to deserialize query string: missing field 'ticket'`. So the ticketless path is dead
code, and the social push channel requires a coin-communities bearer session — which is *not* the
SIWS session in `auth_session.rs`; that service has its own wallet auth at
`POST /api/v1/users/auth/wallet/challenge` → `/verify`.

### 4.7 Mutating routes — mapped, never called

Recorded so the boundary is explicit and so nothing here is ever reached by accident. **None of these
was called.** All are on coin-communities unless noted.

`POST /api/v1/communities/{mint}/callouts` (post a callout) · `POST …/messages` ·
`POST|DELETE …/callouts/{id}/like` · `POST|DELETE …/messages/{id}/like` ·
`POST …/callouts/{id}/replies` · `POST …/messages/{id}/replies` · `POST …/messages/{id}/report` ·
`POST|DELETE /api/v1/users/{user_id}/follow` · `POST /api/v1/users/me/wallets` ·
`POST /api/v1/users/me/wallets/challenge` · `POST /api/v1/users/me/auth-wallet` ·
`POST /api/v1/users/me/auth-wallet/challenge` · `PATCH /api/v1/users/me/twitter-privacy` ·
`POST /api/v1/users/twitter/callback` · `POST /api/v1/users/twitter/challenge/exchange` ·
`POST /api/v1/users/auth/wallet/challenge` · `POST /api/v1/users/auth/wallet/verify` ·
`POST /api/v1/users/token/refresh` · `POST /api/v1/communities/media` (upload) ·
`POST /api/v1/links` · `POST /api/v1/communities/{mint}/ws/ticket` and the two `/server` ticket
variants · frontend-api-v3 `POST /users/register`, `/moderation/ban/address/{addr}`.

`POST …/ws/ticket` is a borderline case worth naming: it *mints a read-only subscription ticket* and
is arguably not mutating. It was still not called, because no bearer session for that service exists
and because "arguably not mutating" is not the standard.

### 4.8 Dead, undeployed, and out of scope

**`UNROUTED` on frontend-api-v3** (`"Cannot GET"`), all present in BankkRoll's June capture —
retired in the ~2 months since: `/kols` · `/callouts` · `/callouts/leaderboard` · `/livestream` ·
`/livestream/history` · `/voice-chats/count` · `/voice-chats/coin/{mint}/count` ·
`/v3/followers/count/{wallet}`.

**`UNROUTED` elsewhere:** `swap-api /v2/creators/unified-totals` 404s on GET — BankkRoll records it
as POST, so the method is the discrepancy, not the route. `advanced-api-v2 /coins/list` and
`livestream-api /livestreams` also 404 — **but those two paths were my own guesses, not extracted
from the bundle, and a guess that 404s proves nothing.** They are recorded as refuted guesses, and
the honest statement is that no path for either host was recoverable from the bundle: the app
imports `getAdvancedClientServerUrl` and `getLivestreamServiceUrl` but the call sites did not survive
minification into greppable literals.

**`SDK-404` — in the generated contract, 404 from the server.** `/api/v1/leaderboard/callouts` and
`/…/ranked`, `/api/v1/users/{id}/callouts`, `/api/v1/users/{id}/followers`,
`/api/v1/communities/{mint}/feed/public`, and the whole `/api/v1/mock/*` namespace. Note the sibling
`/api/v1/users/{id}/profile` **works**, so the service is deployed and these specific paths are not.
Because coin-communities returns empty-bodied 404s, "undeployed" versus "gated differently" cannot be
separated from outside — recorded ambiguous, not resolved.

**The most important entry in this section:** `GET /api/v1/feed/public` — the global social feed, the
one route that could originate a caller population without a subject in hand — **answers 200 and is
abandoned.** Its envelope carries `computedAt: 2026-08-06T05:39:30Z`, **eighteen days stale**, and
`limit=3` returns a single item from 2026-08-04. It is a frozen materialised view. A consumer that
polled it would get a 200, a well-formed body, and a lie. **This is `/callout/recent` again wearing a
200 instead of a 400**, and it is the reason the `computedAt` field must be read and asserted rather
than assumed fresh.

**Out of scope, named so nobody re-derives them:** Privy (`auth.privy.io`, `*.rpc.privy.systems`,
all `:colon`-parameter `/api/v1/*` paths), WalletConnect, Firebase Cloud Messaging, LiveKit, Mux,
Datadog/New Relic, Intercom, MoonPay, relay.link, and the `x-server-key`/`x-server-secret` `/server`
routes.

---

## 5. The availability clock, answered

The question: *is the "@X updated their callout!" push timestamp reachable server-side, or is it
app-only?* The answer has three parts.

**(a) The notification itself is app-only, and the web bundle proves it.** All 294 chunks were
searched for a push-token registration path. Firebase Cloud Messaging *is* vendored in and the app
registers `/firebase-messaging-sw.js`, but **no pump-side endpoint that accepts a device token
exists anywhere in the bundle** — the only `registerDeviceToken` found belongs to WalletConnect's
echo service. There is no `/notifications` API, no notification-settings route, no subscription
route. `/notifications` and `/settings/notifications` are *page* routes with no API behind them in
this bundle. So the push envelope, and its delivery timestamp, are not reachable from the web
surface. Reaching them needs device-side capture — see below.

**(b) But the availability clock is reachable server-side, by a better route than push.** Three
provider-stated instants exist, and none of them was in our catalog:

| Field | Where | What it states |
|---|---|---|
| `serverTs` (epoch ms) | `/boards/movers` envelope | when the provider produced this board |
| `computedAt` (ISO-8601 ns) | `/api/v1/feed/public` envelope | when this view was materialised — **and it is 18 days stale, which is how we know it is real and load-bearing** |
| `lastRefreshedAtMs` | `/pnl-leaderboard` **rows** | when this wallet's PnL was last recomputed |
| `updatedAt` | `/mayhem/*` envelopes | when the aggregate was computed |

`catalog.rs` records, correctly, that no callout route states when the provider learned of a callout.
That remains true of the *callout* routes. It is **no longer true of the surface as a whole** — the
provider does stamp its own computation instants elsewhere, and `lastRefreshedAtMs` in particular is
a per-row provider-side staleness stamp of exactly the kind the house rule *"a number without its age
is a lie by omission"* demands.

**(c) The tightest available bound on callout availability is the community websocket.** A
`message_update` frame on `wss://api.coin-communities.xyz/api/v1/communities/{token_address}/ws`
arrives when the provider pushes it. Our receive instant on that frame is a genuine availability
clock — not the occurrence time the REST rows carry, and far tighter than any polling interval. It
needs a coin-communities bearer session (§4.6), which Ember can obtain with the same wallet, through
that service's own `POST /api/v1/users/auth/wallet/challenge` → `/verify` flow. GROUNDED LIVE
2026-08-24 (`crate::community_session`): the challenge is a SIWS-style authentication text,
`Sign in to CoinCommunities: <uuid-nonce>`, signed through the wallet's message-sign primitive and
nothing transaction-shaped; verify returns an `accessToken`/`refreshToken` pair (~48 h access
token, rotated at `POST /api/v1/users/token/refresh`), and the bearer-gated `GET /api/v1/users/me`
returned 200 under the `bearer + x-api-key` double header.

**So: the occurrence/availability confound that HANDOFF.md lists as unresolved is resolvable, and
without a phone.** The path is the ticketed community socket, not the push notification.

**If the app-only push clock is still wanted** — because it is the clock Ember actually reacts to,
which is a different and legitimate question — that is a **human-assisted** procedure and I did not
attempt it: install mitmproxy on the Mac, add its CA to the iPhone's trust store (Settings → General
→ About → Certificate Trust Settings, which requires Ember's physical taps), point the phone's Wi-Fi
HTTP proxy at the Mac, and drive the app through iPhone Mirroring while the flow log records. Expect
certificate pinning to defeat it on some routes. The deliverable would be the notification payload
and its delivery timestamp against our wall clock. **Worth doing only after (c) is exhausted**, since
(c) answers the same question with no device, no CA trust change, and no pinning fight.

---

## 6. The callout/social subsurface in depth

The hot-attention lane consumes this next, so here is the detail.

### `GET /api/v1/communities/{mint}/callouts/public` — measured

**Envelope:** `{"callouts":[…]}`. Nothing else — **no `nextPageToken`, no cursor, no total.**

**Row keys, complete, as measured:**
`id · communityId · userId · businessId · username · displayName · profileImageUrl · content ·
mediaUrl · likeCount · replyCount · followerCount · liked · createdAt · multiplier · maxMultiplier ·
maxMultiplierAt · calloutPrice · calloutMarketCap · isSpam · isHarmful · deletedAt · deletedReason ·
mentions · mentionedUserIds · source · tokenAddress · walletAddress · userTwitterUrl`

**Against our catalogued `/callout/top/{mint}`, this route adds:** `likeCount`, `replyCount`,
`followerCount`, `liked`, `mentions`/`mentionedUserIds`, `isSpam`, `isHarmful`, `deletedAt`,
`deletedReason`, `source`, and a stable `id` (uuid) that keys the detail and replies routes. Those
are precisely the like/repost/comment counters visible in Ember's screenshots, and precisely what
`/callout/top` does not carry.

**Four measurements that constrain how it can be used:**

1. **`limit` is INERT.** `?limit=5`, `?limit=3` and no parameter at all each returned **exactly 50
   rows**, byte-identical window. Same family as `/coins` silently clamping to 70 — and the same
   lesson: a caller that asks for 5 and counts what it gets is the only caller that finds out.
2. **There is no pagination at all.** `offset=50`, `page=2` and `cursor=x` each returned the *same*
   50 rows. The route is a **fixed newest-50 window**. On a busy coin that window spanned about two
   days (2026-08-22T15:11 → 2026-08-24T18:43). **A coin's callout history beyond the newest 50 is
   unreachable through this route**, which means our own accumulated tape is the only way to hold
   more, and the polling interval must be short enough that 50 rows never roll over between reads.
3. **`createdAt` is ISO-8601 UTC with microseconds** (`2026-08-24T18:43:45.940969Z`), and
   `maxMultiplierAt` likewise — *not* the epoch milliseconds that `/callout/top` and
   `/callout/list` use. **Two callout routes on two hosts with two different time encodings for the
   same event.** Any join across them must normalise explicitly, and a tag must name its clock.
4. **Prices here are USD-denominated** (`calloutPrice`, `calloutMarketCap`). Recall the measured trap
   on `/callout/list`: its SOL-denominated fields are recomputed at read time against the current SOL
   price and are *not* the price at the callout, while the USD pair is the as-of-event quantity.
   These fields being USD is therefore the *good* case — **but that has not been verified here by the
   two-reads-two-seconds-apart test that caught it last time, and it should be before anything is
   retained.**

### The rest of the subsurface

- `…/callouts/{id}/public` → `{callout:{…}}`, single row, same shape. Keys off the `id` above.
- `…/callouts/{id}/replies/public` → `{replies:[…]}`; empty on the sampled callout. This is the
  comment thread in the screenshots.
- `…/messages/public` → `{messages:[50]}`, same 50-row shape, rows adding `parentCalloutId` and
  `parentMessageId`. **`parentCalloutId` is the join from chat back to the callout it discusses** —
  the discussion graph hanging off a callout.
- `/api/v1/communities/top` → `{communities:[…]}` with `postCount`, `memberCount`, `totalLikes`,
  `latestPostAt` (epoch ms). A social-activity board over coins; a third clock encoding on the same
  host.
- `/api/v1/users/{uuid}/profile` → `{user:{id, username, profileImageUrl, nativeFollowerCount,
  nativeFollowingCount, followerCount, createdAt}}`. Note `native*` versus plain counts — two
  follower notions, undocumented, do not coalesce them.
- **The caller-leaderboard family (`/api/v1/leaderboard/callouts*`) is in the contract and 404s.**
  Ember's SIWS-gated `/callout/leaderboard` on frontend-api-v3 remains the only working global caller
  root. The coin-communities replacement is specified but not deployed — worth re-probing
  periodically, because `/…/wallets/{address}/stats` and `/…/users/{id}/history` would give
  per-caller history without a subject in hand, which is the thing the callout study has never had.

### The one thing the screenshots show that no route explains

*"updated their callout"* events. The callout row carries `createdAt` but **no `updatedAt`**. The
websocket event type is `message_update`, which would carry an edit. So callout revisions are
plausibly visible **only** on the socket, and a REST poller would see the new values with no way to
know a revision occurred or when. **Unverified** — it needs the ticketed socket to confirm. If true
it is important: it means REST-sampled callout prices are silently mutable.

---

## 7. Cross-reference against BankkRoll and against our own catalog

**BankkRoll is fresher than the brief assumed, and that changes how to use it.** The repo now carries
a dated capture directory; the latest is **2026-06-17** with 114 endpoints reverse-engineered from
live traffic. The combined `all-endpoints.json` has 245 paths / 283 operations, but the weighting is
the thing to know: **154 operations are tagged `frontend-api.pump.fun (v1, deprecated)` and exactly
one is tagged v3.** So the repo is not "out of date by a decent amount" uniformly — it is a large
archive of a dead v1 API plus one genuinely useful two-month-old traffic capture.

Use it as: **a source of routes the app called but that no longer appear as literals in the current
bundle.** Its OPTIONS entries are especially good evidence, since a recorded CORS preflight means the
browser really was about to make that call.

Verified from BankkRoll's capture this session: `/boards/movers` **LIVE** · `/coins-v3/{mint}`
**LIVE** · `/coins/mayhem-mode` **LIVE** · `/coins/search-unrestricted` **LIVE** (already ours) ·
`/v2/coins/{mint}/candles` **LIVE** · `/v1/coins/{mint}/market-activity` **LIVE** ·
`/v1/coins/{mint}/ath` **LIVE** · `/following/v3/following/count/{id}` **LIVE** ·
`/callout/leaderboard`, `/callout/list/{id}`, `/callout/top/{id}` **LIVE** (ours already).
Refuted as dead: `/kols`, `/callouts`, `/callouts/leaderboard`, `/livestream`, `/livestream/history`,
`/voice-chats/*`, `/v3/followers/count/{id}`. Its hosts `volatility-api-v2.pump.fun`,
`clips-api.pump.fun` and `market-api.pump.fun` **do not appear in the current bundle at all** and
were not probed.

**Against our own catalog**, the corrections are:

| `catalog.rs` says | The app says |
|---|---|
| `CoinExact` → `/coins-v2/{mint}` | `/coins-v3/{mint}` (key sets identical on one coin) |
| `Candles` → `/v1/coins/{mint}/candles` | `/v2/coins/{mint}/candles`, with `createdTs` |
| `CommunityMessages`/`CommunityCallouts` → `profile-api.pump.fun`, `AuthenticatedUserSession` | `api.coin-communities.xyz`, and the `/public` variants are **anonymous** with the shipped key |
| no volume/trade-count/holder-count on any coin route | `/boards/movers` and `/in-memory-coin/{mint}` carry all three |
| callout clocks are epoch millis | coin-communities uses ISO-8601 µs; `/communities/top` uses epoch ms |
| no availability instant anywhere | `serverTs`, `computedAt`, `lastRefreshedAtMs`, `updatedAt` |

The companion extension's allowlist (`extensions/pump-companion/src/policy.ts`) already carries
`api.coin-communities.xyz` including `/feed/public` and `/communities/top` — **the companion was
right and the Rust catalog is the one that drifted.** It also still carries `callout-recent`, which
is the known phantom.

---

## 8. Proposal: what to add to catalog.rs, and in what order

**This is a proposal. No code was edited.** Two other deputies are live in
`crates/joshi-pump-api`, `apps/*` and `crates/joshi-liquidity`.

### The digest ripple, stated first because it prices everything below

`ROUTE_CATALOG = "joshi.pump_api.catalog.2026-08-16.v1"` (`crates/joshi-pump-api/src/lib.rs:73`) is
not a label. It is:

- stamped into every acquisition envelope (`client.rs:617`, `client.rs:883`);
- mixed into **identity material** (`client.rs:499` inserts it as `"catalog"`), so product-identity
  digests move with it;
- a **hard admission gate** — `joshi-admission/src/pump.rs:55` refuses any attempt whose
  `catalog_version != ROUTE_CATALOG`;
- a **hard promotion gate** — `promotion.rs:501` and `promotion.rs:733` refuse on mismatch;
- checked by the audit path (`audit.rs:690`).

So **bumping the catalog version retires every previously retained acquisition from admission and
promotion.** Adding routes without bumping it is worse: it silently widens what the string claims to
describe. Either way this is a migration, not an edit, and it wants Ember's call.

Separately, mechanical: `RouteId::ALL` is `[Self; 19]` and must grow; the closure tests in
`catalog.rs` iterate it; and `query_parameter_never_public` will **refuse `userId`, `session_id`,
`creator` and `searchTerm` by substring**, which is correct and means the movers-board personalisation
parameters can never be declared public. Good — they are subjects.

### Priority 1 — the routes that answer questions we cannot currently answer

1. **`advanced_indexer_movers` → `advanced-indexer.pump.fun/boards/movers`.**
   `ObservedPublicProduct` / `UndocumentedObserved`, `PaginationKind::None`, `limit` allowlisted and
   declarable public; `userId`, `session_id`, `country` allowlisted and **sensitive** (the floor
   refuses them anyway). Carries volume, trade counts and `serverTs`. **Needs a reviewed-schema
   artifact before any row is retained**, and that review must decode-or-refuse each compact key:
   the mapper-confirmed subset in §4.1 is safe to name, the rest must stay unnamed opaque leaves.
   `ordering` must say *personalised recommendation board; position is not rank*.
2. **`community_callouts_public` → `api.coin-communities.xyz/api/v1/communities/{mint}/callouts/public`.**
   `ObservedPublicProduct`, `PaginationKind::None` (**measured: no pagination exists**), `{mint}`
   joins `public_subject_path` on the same reasoning `CalloutTop` was admitted 2026-08-24 — it is a
   public chain fact and the rows restate it as `tokenAddress`. `ordering` must record *fixed
   newest-50 window; `limit` inert; history beyond 50 unreachable*. **Reviewed-schema artifact
   required**, and the review should run the two-reads-two-seconds-apart test on `calloutPrice`
   before anything downstream treats it as as-of-event.
3. **Correct `CommunityMessages`/`CommunityCallouts`**: repoint to `api.coin-communities.xyz`, and
   reclassify the `/public` variants from `AuthenticatedUserSession` to `ObservedPublicProduct`. This
   is a correction of a wrong entry, not an addition — arguably the highest-value item here, since a
   wrong access class means the route is never even attempted.

### Priority 2 — cheap, high-confidence, no new host

4. **`coin_exact` → `/coins-v3/{mint}`**, keeping `/coins-v2` as the documented predecessor. Key
   sets measured identical; still wants a second mint and an `includeLiveStreamInfo=true` read
   before flipping.
5. **`candles` → `/v2/coins/{mint}/candles`** with `createdTs` allowlisted. Run the one experiment
   that matters first: does `createdTs` reach history that `before` could not?
6. **`pnl_leaderboard` → `/pnl-leaderboard?period={daily|weekly|monthly}&sort&limit`.** The provider
   enumerates `period` in its 400 body, exactly as `/coins` enumerates `sort` — record the
   enumeration in the catalog note. Rows carry `lastRefreshedAtMs`, the first per-row provider
   staleness stamp in the catalog.
7. **`in_memory_coin` → `advanced-indexer.pump.fun/in-memory-coin/{mint}`.** Anonymous, keyless,
   carries `volumeSol`/`volumeUsd`/`progress`/`graduationDate`.

### Priority 3 — worth having, lower urgency

8. `/coins/great-coins`, `/coins/similar`, `/mayhem/overview|top-coins|top-traders`,
   `/coins-v2/user-created-coins/{wallet}`, `/profiles/verified`.
9. `/following/followers/{wallet}` and the two `/following/v3/*/count/{wallet}` routes — **with the
   1000-row cap recorded as a silent clamp**, since the test wallet's true follower count is 9363.
10. `/api/v1/communities/{mint}/messages/public` for the discussion graph (`parentCalloutId`).

### Priority 4 — record as refuted, never collectable

11. **`/api/v1/feed/public` as a *catalogued refutation*, exactly as `CalloutRecent` is catalogued.**
    It answers 200 with a well-formed body and is eighteen days stale. `collection_enabled: false`,
    with the note that its `computedAt` is the field that convicts it. This is the durable form of
    the lesson so nobody re-derives a global feed from it in three months. Retain the response as
    `fixtures/community_feed_public_stale_v1.json` beside the phantom fixture.
12. Add the **`Cannot GET` discriminator** from §2 to the catalog's doc comments. It is a
    generalisable refutation tool and it currently lives nowhere in the repo.

### Not proposed

The NATS clusters and the community websocket are **not** proposed as catalog routes. They are a
different transport with different semantics (gap-on-reconnect, no replay, credential-bearing), and
`RouteId::LiveChat` shows the existing shape for holding a websocket as `ReconnaissanceOnly` /
`Unimplemented`. They deserve a design pass of their own, not a row in an HTTP catalog. But they are
the highest-value thing in this document, and §5 is the argument for why.

---

## 9. What I did not verify, and why

- **Every POST, without exception** — including ones that are almost certainly reads
  (`/coins-v2/mints`, `/v1/coins/ath/batch`, `/v1/coins/market-activity/batch`,
  `/v1/coins/{mint}/trades/batch`, `POST /pnl/coin/{mint}/holders`, `/users/batch`,
  `/coin-narrative/by-mints`, `/wallet-overview`, `/v2/creators/unified-*`). The brief's rule is
  never to call a mutating route, and **a path alone cannot tell you which POSTs are reads.** Being
  conservative cost me the holders answer in §4.5; that was the right trade. These are the obvious
  next probes once a human agrees which are reads.
- **Everything requiring a session.** The SIWS token in `auth_session.rs` was not loaded and no
  login was performed, so `/auth/my-profile`, `/pnl-leaderboard/rank`, the bearer-gated
  coin-communities routes, and the `ws/ticket` flow are all unverified from the authenticated side.
  Several 404s in §4.8 might be 200s with a bearer; that is unresolved.
- **The `/server` routes.** `x-server-key`/`x-server-secret` are server-to-server. No credentials,
  and probing them would be noise.
- **NATS.** No cluster was connected to. The subject list is from the bundle; whether
  `unifiedTradeEvent.lite.{mint}` delivers what its name says is **unmeasured**.
- **The community websocket beyond the handshake.** One anonymous upgrade attempt, which returned the
  informative 400 quoted in §4.6. No ticketed connection.
- **`advanced-api-v2` and `livestream-api` paths.** Not recoverable from the bundle; my two guesses
  404'd and prove nothing. Genuinely unmapped.
- **Pagination on most newly-found routes.** Tested exhaustively only on
  `/communities/{mint}/callouts/public`. `/coins/great-coins` returned 5 rows and `/profiles/verified`
  returned 50 — **both suspiciously round, both untested for clamping.** Assume a silent clamp until
  measured.
- **Row-shape stability.** Every shape here is one read of one subject. The catalog's own history
  says shapes drift between reads on this provider (11 reads → 8 fingerprints on the discovery
  routes). Nothing here is a schema.
- **Volume discipline.** ~300 requests for the bundle (static assets), ~70 API calls total, with
  backoff on the one host that asked for it. I did not sweep mints, did not page anything deeply,
  and did not sample repeatedly for stability — that last one is a real gap, and it is why no claim
  above is stated as a schema.

**Confidence, plainly.** *High:* the origin list, the 84-operation coin-communities contract, the
NATS cluster list and the websocket protocol — these are read out of shipped code, not inferred.
*High:* every `LIVE` verdict and the four measurements in §6, which are direct observations.
*Medium:* the `ROUTED-REFUSED` reading of `/coins/top-holders` — the NestJS discriminator is sound
but I could not confirm it positively. *Medium:* `coins-v3 ≡ coins-v2`, one coin only.
*Low, and labelled:* the undecoded movers keys, and the claim that callout revisions appear only on
the socket.

---

## 10. Counts

**Routes by verdict class** (pump-owned surface only; vendored SDK paths excluded):

| Verdict | Count |
|---|---|
| `LIVE` — verified 200 this session | **35** |
| `GATED` — 401, needs a session | 3 |
| `ROUTED-REFUSED` — route exists, handler declined | 1 |
| `VALIDATION` — route exists, wrong parameter type | 2 |
| `DEGRADED` — 503 | 1 |
| `SDK-404` — in the generated contract, server 404s | 7 |
| `UNROUTED` — `Cannot GET`; 8 of the 9 are BankkRoll routes now dead | 9 |
| `BUNDLE` — found in shipped code, not called | ~24 |
| `MUTATING` — mapped, never called | 25 |
| Refuted guesses of my own (not evidence of anything) | 2 |

**Sources:** 294 JS chunks (15 MB) making up the complete client bundle · 84 operations from the
coin-communities OpenAPI SDK · 1 hand-written endpoint-constant module · 1 service registry · 5 NATS
cluster configs · 1 websocket protocol · BankkRoll's 245-path archive of which the 114-entry
2026-06-17 capture is the live-relevant part.

**Working artifacts** (scratchpad, not committed): the 294 chunks, `sdk-ops.json` (the parsed
84-operation table), `verify-results.json` (the first verification sweep), `bankk.json`, and the
saved page shells with their CSP headers.
