# Implementation lane 10 — direct Pump product API

Status: **offline implementation complete; public smoke complete; authenticated parity handoff
required before any authenticated route is promoted**  
Observed: 2026-08-16 America/New_York (the bounded responses carried 2026-08-17 UTC server dates)  
Code: `crates/joshi-pump-api`  
Fixtures: `fixtures/pump-api`

## Decision

The continuous Pump product source should be a headless, read-only, honestly authenticated source
adapter where that adapter can reproduce Ember's ordinary session. The companion is now the
reconnaissance, parity, drift, and fallback instrument—not a permanent background pipe and not the
place for product logic.

That decision is narrower than “the frontend API is public.” The direct client has four access
classes, and code enforces them:

1. `officially_described_public`: Pump-authored integration material describes the exact route;
   enabled by default for a bounded call.
2. `observed_public_product`: a bounded current response or the old donor establishes technical
   reachability, but Pump does not document the route as an integration contract; disabled unless
   the operator names the route and supplies `--enable-observed-product-route`.
3. `authenticated_user_session`: a candidate intended to run as Ember's real Pump session;
   disabled unless explicitly enabled and supplied by a session provider.
4. `reconnaissance_only`: known product transport with unresolved protocol/auth/replay semantics;
   no direct collector exists.

The current implementation is therefore suitable for exact public observations and for an
authenticated parity spike after the small interactive handoff below. It does **not** yet establish
that discovery, social, follows, notifications, or exact chart semantics are stable enough for a
continuous production source. A technically successful response is evidence about that response,
not permission, completeness, or parity.

## Access posture

Pump's current [Terms of Use](https://pump.fun/docs/terms-and-conditions), last updated 02 May
2026, say in §6.1 that the platform and services may be accessed through bots as long as the access
otherwise complies with the Terms. The same live terms prohibit, among other things, obtaining
material not purposely provided, unauthorized access, security/authentication testing, tracking
other users, unreasonable load, forged identity, and evasion of platform controls. Ember has
authorized Joshi to use Ember's ordinary authenticated Pump access. Engineering posture:

- make only read-only `GET`s that the product purposely delivers to that same session;
- identify the client honestly, use one identity, keep concurrency effectively one per host, and
  honor `Retry-After`;
- stop on 401/403, persistent 429, changed auth, or any need to mine/replay a browser-shipped key,
  bypass CORS/security, rotate identity, or probe a vulnerability;
- never post, like, report, follow, trade, construct an auth challenge, request a wallet signature,
  or place a wallet signing key in this process;
- treat other users' profiles, follows, and content as personal/provider data with a local purpose,
  field minimum, protection class, and retention—not as a free training corpus.

This is an engineering reading for a personal tool, not legal advice. §6.1 is not a blanket grant
that cancels the rest of the Terms. If the exact authenticated replay method cannot be cleared, the
direct adapter remains public/per-mint and the companion remains a deliberate user-side view.

## Primary-source baseline

Pump's official integration repositories remain pinned at the commits rechecked for this lane:

- [`pump-fun/pump-fun-skills@c8aaa6a`](https://github.com/pump-fun/pump-fun-skills/tree/c8aaa6a8fb766b2765d2663744515bbf88d04380)
  describes exact-mint `coins-v2`, `sol-price`, and optional profile balance routes. The
  [create-coin skill](https://github.com/pump-fun/pump-fun-skills/blob/c8aaa6a8fb766b2765d2663744515bbf88d04380/create-coin/SKILL.md#L255-L295)
  explicitly warns that the HTTP `token_program` may be stale or wrong and must be resolved from
  the mint account. The
  [swap skill](https://github.com/pump-fun/pump-fun-skills/blob/c8aaa6a8fb766b2765d2663744515bbf88d04380/swap/SKILL.md#L297-L358)
  describes the balance summary/token pages, `sol-price`, and `coins-v2`.
- [`pump-fun/pump-public-docs@9c82f61`](https://github.com/pump-fun/pump-public-docs/tree/9c82f61cb711b044a17f770ab8ce9f9bdf78f333)
  remains the authority for Pump/PumpSwap program accounts/events and the basis of the independent
  chain tape. It is not documentation for product feed rank, social content, or notifications.
- Pump's official skills repository describes its collection as on-chain integrations and SDK
  workflows, not a general social/discovery HTTP API. Its
  [README](https://github.com/pump-fun/pump-fun-skills/tree/c8aaa6a8fb766b2765d2663744515bbf88d04380#overview)
  is positive evidence for the named routes and no more.

## What was inspected

### Donor inspection

The old `~/dev/joshibot` packages were read as dated hypotheses, not copied as authority:

- `shitcoims_pumpsocial/endpoints.py` and `client.py` catalogued Pump, profile, swap, and a
  third-party community service;
- `shitcoims_scalper/boards.py` and `feed.py` used `/coins`, `/coins/currently-live`, and exact-mint
  refreshes;
- `studies/imitation_signal.py` and `studies/pvp_vamps.py` used swap candle/trade routes;
- `shitcoims_pumpsocial/probe.py` recorded useful silent-failure traps.

Three donor choices are explicitly rejected here:

1. The browser-mined `api.coin-communities.xyz` key is not copied, loaded, re-mined, or treated as
   a public credential. A shipped key is neither a Pump session nor a durable authorization.
2. Provider JSON is never first parsed into JavaScript/Python floats. Exact bytes are retained;
   selected numeric fields cross normalization as validated JSON-number lexemes.
3. HTTP 200 is not `live=true`. A wrong identity, null object, empty/censored page, unpromoted
   schema, or stale retrospective score remains its own observed state.

### Bounded current reads

Seven initial non-mutating requests were made, with at most two records on list routes and no
crawl. After the implementation passed offline gates, one additional one-shot `sol-price` request
was made through the new client itself:

| route | bounded observation | meaning and limit |
| --- | --- | --- |
| `GET frontend-api-v3.pump.fun/coins-v2/{known mint}` | 200; JSON object; ETag; rate headers reported 60/min; current fields include protocol/quote/reserve/market-cap/lifecycle/display values | official mutable enrichment; numeric values arrive as JSON numbers; on-chain remains authoritative for token program and protocol facts |
| `GET frontend-api-v3.pump.fun/sol-price` | 200; `solPrice`, `asOfTimestamp`, `stale`; rate headers reported 50/min | official auxiliary quote; retain source clock/stale bit |
| `GET profile-api.pump.fun/balance/summary/{system address}` | 200; `{success,data}` | official optional balance cross-check; does not replace chain accounts |
| `GET frontend-api-v3.pump.fun/coins?...limit=2...` | 200; two ordered objects | undocumented discovery candidate; observed reachability is not a stable feed contract |
| `GET frontend-api-v3.pump.fun/coins/currently-live?limit=2` | 200; two ordered objects with live/playlist fields | undocumented live board candidate; stream availability and rights remain distinct |
| `GET frontend-api-v3.pump.fun/callout/recent?limit=1` | 200; one callout and `nextPageToken` | undocumented keyset candidate; body mixes event-time content with retrospective peak/multiple outcomes |
| `GET profile-api.pump.fun/api/v1/users/by-wallet/{system address}` | 401 with `WWW-Authenticate: Basic` | the candidate profile family is authenticated; no bypass or alternate credential was attempted |

The server also set Cloudflare cookies on anonymous responses. They were neither retained in
fixtures nor added to requests. One response's rate headers do not establish a global quota. The
client's default 1.1-second host interval, 20-request run budget, three-attempt cap, and 2 MiB body
cap are deliberately below what those snapshots appeared to allow; provider instructions always
win.

## Surface and route map

`RouteSpec` is the executable map. Every method is structurally `GET`; there is no generic method,
URL, or header escape hatch.

| surface | route candidates | transport / auth | pagination and order | fidelity / revision hazards | V1 disposition |
| --- | --- | --- | --- | --- | --- |
| exact coin | `frontend-api-v3/coins-v2/{mint}` | HTTP, officially described public | one current object | mutable; ETag observed; token program explicitly may be stale; several financial fields are JSON numbers | default-enabled bounded enrichment; chain wins conflicts |
| SOL price | `frontend-api-v3/sol-price` | HTTP, officially described public | one current object | source `asOfTimestamp` and `stale`; quote methodology not canonical | default-enabled auxiliary |
| wallet balances | `profile-api/balance/summary/{wallet}`, `/balance/tokens/{wallet}?page&size` | HTTP, officially described public | page/size; provider order undocumented | current summary/list may lag or omit chain accounts | default-enabled cross-check; wallet path is fingerprinted, not logged |
| discovery boards | `frontend-api-v3/coins` | HTTP/XHR, anonymous response observed | offset/limit plus sort/order; insertion can revise pages | membership/order/personalization/feature flags undocumented; current fields not history | disabled product candidate; promote one named board only after parity census |
| live board | `frontend-api-v3/coins/currently-live` | HTTP/XHR, anonymous response observed; livestream service separate | offset/limit; rank revision unknown | playlist/media fields are hostile input; a current row is not a stream interval | disabled product candidate |
| search | `frontend-api-v3/coins/search-unrestricted`, `/users/search` | HTTP/XHR; coin candidate observed historically; user search classified authenticated until parity | relevance order; offset/limit where present | query may be sensitive; impostor/duplicate names; session effects unknown | query values hashed in fingerprints; disabled |
| callout discovery | `frontend-api-v3/callout/recent` | HTTP/XHR, anonymous bounded response observed | `nextPageToken`; donor decoded it as keyset, but cursor internals are opaque here | current rows include `multiple`, max price, and peak time—future outcomes relative to the call | disabled; retrospective fields tagged and never admitted as pre-call features |
| per-coin callouts | `/callout/top/{mint}`, `/callout/list/{mint}` | HTTP/XHR, donor observation | top list or page token plus sort/order | top is outcome-ranked; donor saw empty recent lists despite top history; deletions/censoring unknown | disabled; companion parity required |
| Pump profile | `frontend-api-v3/users/{key}`, `profile-api/api/v1/users/by-wallet/{wallet}` | HTTP/XHR; candidate authenticated user session | one current object | `{key}` may resolve address or username; username/follower/current creator are mutable; wrong-identity 200 possible | disabled; echo-key guard belongs in promoted schema adapter |
| outgoing follows | `frontend-api-v3/following/{wallet}` | HTTP/XHR; donor-only, personal data; authenticated classification | offset/limit; donor observed timestamps | no complete incoming-edge route; population/order/revisions unknown; tracking concern | disabled; only Ember-selected scope after review |
| thread/social roots | `profile-api/api/v1/communities/{mint}/messages/public` | HTTP/XHR, authenticated candidate; third-party-key twin excluded | opaque cursor | reply bodies may be censored while counts remain; edits/deletes/moderation/private content | disabled; direct signed-session parity required |
| community callouts/replies | `profile-api/api/v1/communities/{mint}/callouts/public` | HTTP/XHR, authenticated candidate; third-party-key twin excluded | opaque cursor | wallet/profile attribution is provider assertion; outcome leakage; completeness unknown | disabled |
| Pump chart candles | `swap-api/v1/coins/{mint}/candles` | HTTP/XHR; donor-only, undocumented | interval/limit/before vendor window | sparse traded buckets, unknown corrections/venue stitching/ordering; not executable quotes | disabled; chain-event chart is canonical fallback |
| Pump trade tape | `swap-api/v2/coins/{mint}/trades` | HTTP/XHR; donor-only, undocumented | cursor/before candidate | wallet attribution/privacy, revisions, exact cursor/order unmeasured | disabled |
| live chat | `wss://livechat.pump.fun` named by product shell | WebSocket, auth/replay unresolved | stream sequence/resume unknown | exact subscription, moderation, private/session state, replay and retention unknown | reconnaissance-only; no connector |
| notifications/activity | no honest route identified | likely authenticated product transport | unknown | viewer-specific state, read status, retention and deep-link semantics unknown | companion reconnaissance; do not guess a URL |

The Pump-owned `profile-api` candidates stay separate from the third-party community host in the
donor. The new crate contains no third-party host and no API-key field. If a future licensed social
provider is adopted, it receives its own provider/access contract rather than being smuggled into
“Pump authentication.”

## Headless client contract

### Request and route safety

- `LogicalRequest` names a `RouteId`; the catalog supplies a fixed origin, fixed path template,
  path parameters, and query allowlist.
- No caller can supply an arbitrary URL, HTTP method, redirect target, header, or request body.
- Redirects and reqwest's implicit retry policy are disabled. The source supervisor owns visible
  retry attempts.
- Public routes never receive session material. Authenticated routes require both route opt-in and
  `SessionProvider` material.
- Search terms, cursors, offsets/pages, and all path subjects participate in a versioned logical
  request fingerprint. Sensitive terms/cursors and every path value are SHA-256 transformed;
  cookie, bearer, CSRF, and response `Set-Cookie` never enter the preimage.

### Honest authentication and credential-by-path

`SessionProvider` is the seam for a future local browser/session broker. The included
`CredentialFileSession` is deliberately boring:

```json
{
  "contract": "joshi.pump_api.session_file.v1",
  "sessionLabel": "ember-normal-pump-session",
  "expiresAt": "2026-08-16T18:00:00Z",
  "bearer": "<optional secret>",
  "cookie": "<optional secret>",
  "csrfHeaderName": "x-csrf-token",
  "csrfToken": "<optional secret>"
}
```

- The command accepts only the **path**, never secret contents, in arguments.
- On Unix the file must be regular and deny all group/other permissions (normally `0600`).
- Unknown fields, wrong versions, expired material, partial CSRF pairs, and arbitrary CSRF header
  names fail closed.
- Material is reloaded for each logical request, represented with `secrecy`, never serialized or
  debug-printed, and never retained in acquisition bytes.
- A 401/403 invalidates the provider, records an authenticated-availability gap, and stops. There
  is no token refresh, cookie acquisition, wallet challenge, signing, identity rotation, or
  “try another host” behavior.

This is full session authentication, not a browser-mined pseudo-public key. It is only useful after
the interactive handoff establishes Pump's actual current scheme and that replaying Ember's own
session into this personal client is within the reviewed access posture.

### Exact response evidence

Each attempt gets an opaque, restart-global ID from a persisted installation namespace plus a
fresh 128-bit occurrence nonce. Its reservation marker is `fsync`ed **before** network I/O. Equal
bytes from two requests therefore share a content digest but never an occurrence identity.

The acquisition retains:

- route/catalog/access/session class and a redacted logical-request fingerprint;
- request group, attempt ordinal, canonical six-digit UTC start/receive clocks, a local monotonic
  clock domain, readings, and elapsed nanoseconds as decimal strings;
- HTTP status and only safe response headers (`Date`, `Age`, cache, ETag, content encoding/type,
  and rate-limit fields); never `Set-Cookie`, auth, or request headers;
- complete response bytes as base64 plus `sha256:<hex>` and decimal-string byte length.

The exact boundary is named
`http_entity_body_post_transfer_decoding_identity_encoding`: HTTP transfer framing is gone and the
client requested `Accept-Encoding: identity`. If the server nevertheless returns a content
encoding, those still-encoded entity bytes are retained under a different boundary. They must not
be compared to the companion's decoded `arrayBuffer()` as though they were the same bytes.

A response over 2 MiB retains only an explicitly labeled exact prefix and creates a scoped
coverage gap; it is never admitted as an exact whole response. A body-read failure is `Missing`
and creates a gap. Transport, 429, 502–504, auth rejection, and budget exhaustion remain distinct.

### Rate, retry, coverage, and durable identity

- Default budget: 20 attempts/run; maximum three attempts/logical request.
- Default pacing: at least 1.1 seconds between requests to the same host, concurrency serialized
  through the host clock.
- 429 and 502–504 are the only status retries. Decimal `Retry-After` is honored; otherwise explicit
  bounded exponential delay is used. 401/403 never retry.
- Every response attempt is its own acquisition. Retry bodies/statuses are evidence, not logs.
- A successful response creates a scoped **one-page observation window**, explicitly saying feed
  completion is unknown. Failures create scope-aware gaps with route, request fingerprint,
  cursor/page fingerprints, detected time, related acquisitions, and unknown interval bounds.
- Gap count/bytes never substitute for missing interval bounds. A later core adapter must add the
  first resumed cursor and close/recover the matching scope.
- Reservation markers remain pending across crashes and ambiguous receipts. Only an exact durable
  core receipt over submitted acquisition IDs may call `IdentityStore::acknowledge_id`; file output
  alone intentionally leaves the marker reserved.

## Lossless normalization and drift quarantine

`serde_json::RawValue` retains exact scalar substrings from provider bytes. The normalizer first
rejects duplicate object keys at every depth, then computes a stable path/type schema fingerprint.
No live shape is trusted by first sight: only fingerprints in an explicit reviewed
`SchemaRegistry` emit normalized records.

An accepted projection has these rules:

- number fields are `json_number_lexeme`; `9007199254740993`, `1.2300e-7`, and `0.0001000` remain
  exactly those strings;
- strings, booleans, and nulls carry tagged encodings; objects/arrays are not flattened into
  invented scalar truth;
- each row carries the source acquisition ID, response ordinal, and exact row-slice digest;
- callout `multiple`, max-price/max-multiple, and peak timestamp are tagged
  `retrospective_outcome_as_of_acquisition_never_pre_event_feature`;
- thesis/content are tagged untrusted user content; current profile/follower/creator fields remain
  provider-current assertions;
- a new shape, duplicate key, wrong digest/length, non-2xx body, or parse error retains the source
  bytes but emits no accepted records.

The committed registry contains only synthetic fixture shapes. A current live response remains
quarantined until its exact shape and field semantics are reviewed; promotion is a code/data review,
not an automatic learning step.

## Direct-versus-companion parity protocol

The companion observes what Pump deliberately delivered inside Ember's ordinary session. The
direct adapter asks whether the same honest session can reproduce the same source response without
keeping a browser interception pipeline alive.

### Frozen comparison unit

One `joshi.pump_api.parity_input.v1` contains:

- source (`pump_companion` or `direct_pump_api`), route/catalog, logical request fingerprint, and
  hashed session class;
- exact observation time and a shared `comparisonBoundary`;
- base64 bytes, decimal byte length, and algorithm-qualified SHA-256.

The comparator first independently verifies both bodies. It refuses comparison unless route,
catalog, logical request fingerprint, session class, and comparison boundary match. The sampling
protocol—not the comparator—must additionally ensure both requests were issued inside the frozen
time tolerance and with the same visible board/filter/cursor state.

Results:

| disposition | defensible claim |
| --- | --- |
| `exact_bytes_equal` | the two acquisitions saw identical bytes at the named boundary |
| `json_semantic_equal_exact_bytes_differ` | decoded JSON meaning matched while serialization differed; not byte parity |
| `comparable_response_difference` | preconditions matched but one or more order-sensitive JSON pointers differed |
| `incomparable` | route/request/session/boundary or body identity did not match; no parity conclusion |
| `quarantined_*` | malformed or duplicate-key JSON prevented a safe structural comparison |

Differences contain JSON pointers, kinds, and value digests—not copied social text or identifiers.
Arrays are order-sensitive. Number lexemes are exact, so `1.000` and `1.0` differ. A single exact
pair validates a route call, not feed census, latency, revision behavior, pagination, or ongoing
coverage.

### Exact Spike A

For each candidate route, in this order:

1. Companion records one ordinary official response in raw-on private mode, including its exact
   decoded-body bytes, route/request fingerprint, page/filter state, clocks, and session class.
2. Within two seconds, direct client issues the same GET using the approved local session provider,
   same query/order/cursor, one request, no retry unless 429/5xx.
3. Compare exact bytes, schemas, row membership/order, next cursor, cache/ETag, and clocks. Preserve
   mismatch rather than re-querying until it agrees.
4. Repeat 20 paired occurrences across at least three ordinary sessions for one route. Include a
   page boundary, empty page if naturally encountered, and one observed content revision.
5. Promote only if at least 19/20 pairs contain the same ordered membership inside Ember's measured
   reaction window, every difference is understood, pagination advances without gaps/duplicates,
   and no auth/rate/privacy stop occurs. Exact-byte equality is welcome but not required for truly
   dynamic fields; exact ordered membership is required for discovery parity.

Callouts require a leakage audit in addition: pre-call projections must exclude the retrospective
outcome fields even though the response currently supplies them.

## Small authenticated handoff

Authenticated live testing was not possible in this noninteractive lane. Do **not** compensate by
making the companion permanent or by copying its cookies/auth headers into the extension.

The smallest handoff is one 10-minute ordinary-session experiment with Ember present:

1. Choose **one** material read route naturally exercised by Ember—prefer the current-user
   following page or one coin's thread; do not manufacture follows, posts, notifications, or
   trades.
2. In local browser developer tools, record only the method, Pump-owned host/path template, query
   names, response status/shape, auth mechanism names, expiry/refresh behavior, and whether the
   request succeeds when repeated once by the browser. Do not paste credential values into chat,
   source, logs, screenshots, or fixtures.
3. If replay of Ember's own session is cleared, place only the ephemeral bearer/cookie/CSRF values
   in a local mode-0600 `joshi.pump_api.session_file.v1` file. The client receives that path. No
   wallet key or signature is involved.
4. Run exactly one paired companion/direct read and the offline comparator. Stop on 401/403/429,
   device/browser binding, a challenge/signature requirement, unexpected cross-user scope, or a
   need for any header outside the narrow session contract.
5. Delete the credential file after the experiment and retain only redacted auth-lifecycle facts,
   exact protected response evidence under its retention class, and the parity result.

If Pump has no purposefully available way to reuse the ordinary session outside the browser, or
the review does not clear that replay, the answer is “no headless authenticated route.” The
companion may still provide deliberate user-side observations; on-chain/public sources remain the
continuous substrate.

## Core adapter and protection boundary

This crate deliberately stops at a source-native acquisition envelope. The root integrator still
must implement one strict adapter to `joshi-evidence`/`joshi-store`:

1. strict-parse `joshi.pump_api.acquisition.v1` with no unknown fields;
2. independently verify every exact body length/SHA-256 and preserve those bytes unchanged as the
   observation payload (or wrap them in a versioned retained-frame envelope without reserializing
   the body);
3. map acquisition/request/clock/attempt IDs without deriving occurrence identity from content;
4. attach protection domain and retention class outside `BlobId`; authenticated profile/social
   bytes are private even when the same route sometimes answers anonymously;
5. map accepted normalized records as assertions derived from the raw observation, never as
   provider-exact independent observations;
6. bind a source-ingress digest/IDs to the separate durable-store batch/admission digests and exact
   committed acquisition/gap/window IDs;
7. call `acknowledge_id` only after the exact idempotent durable receipt validates. Ambiguous,
   partial, wrong-ID, or wrong-digest 2xx responses retry and leave reservations pending.

No direct-client digest is the store's `DurableIngestBatch` digest; the preimages are different.

## Stop/rethink conditions

Stop the affected route immediately if:

- its access basis depends only on anonymity, CORS, a browser bundle, a shipped key, or
  `robots.txt`;
- the authenticated call needs token mining, wallet signing, challenge automation, forged browser
  identity, proxy/VPN rotation, security testing, or credentials from anyone but Ember;
- 401/403 repeats, 429 persists after `Retry-After`, the provider asks us to stop, or arrival falls
  outside Ember's reaction window;
- schema drift cannot be explained and promoted without relabeling historical fields;
- a board/callout route cannot reproduce ordered membership and pagination against the companion;
- personalized rank is material but the direct call returns an anonymous/general population;
- private social retention expands beyond the named local purpose, or hostile content crosses into
  tools/LLM execution;
- an HTTP current creator/profile/follower field starts overwriting point-in-time chain/evidence
  truth;
- the chart route cannot state venue, bucket alignment, sparse-candle behavior, revisions, and
  coverage—use the independent event-backed chart instead;
- the system starts treating a callout peak/multiple as information available at call time.

## Offline gate and observed result

Commands run from `~/dev/joshi`:

```sh
cargo clippy --manifest-path crates/joshi-pump-api/Cargo.toml --locked --all-targets -- -D warnings
cargo test --manifest-path crates/joshi-pump-api/Cargo.toml --locked
```

Result: clippy clean; 12 tests passed (4 unit, 8 integration), plus doc tests. Tests cover:

- exact integers above 2^53, exponent decimals, and trailing-zero numeric lexemes;
- duplicate-key rejection and unpromoted-schema quarantine;
- equal bytes in distinct acquisitions and distinct equal-looking rows;
- restart persistence, reservation-before-I/O, and receipt-gated acknowledgement;
- exact parity, request/session precondition refusal, and numeric-lexeme differences;
- path encoding and sensitive logical-request fingerprinting.

The final one-shot live client smoke called only the officially described `sol-price` route. It
produced one HTTP-200 acquisition with an exact body, one scoped one-response window whose feed
completion remains explicitly unknown, and no coverage gap. Raw bytes remained in a private
temporary output and were not added to fixtures.

The parity fixture pair can be exercised without network:

```sh
out="$(mktemp -d)/parity.json"
cargo run --locked --manifest-path crates/joshi-pump-api/Cargo.toml -- \
  parity fixtures/pump-api/parity-companion.synthetic.json \
  fixtures/pump-api/parity-direct.synthetic.json "$out"
```

No root manifest, root lockfile, extension, wallet process, or external state was changed by this
lane. No account was created and no mutating Pump route was called.

## Wave 4 handoff

Lane 21 supersedes the V1 pair as a promotion boundary. `joshi.pump_api.parity_input.v2` now binds
the original source acquisition occurrence, one shared digest-only request/filter/cursor
projection, session occurrence, page ordinal, auth disposition, exact body boundary, and a bounded
start/receive window. `crates/joshi-pump-adapter` closes direct and companion ingress through exact
batch/policy bytes and the public store receipt, and retains pair/promotion measurements as private
observations with zero facts. V1 remains fixture compatibility only. See
`docs/implementation/lanes/21_pump_parity_promotion.md`; authenticated direct promotion is still
`not_run_ember_present_required`.
