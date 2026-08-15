# RESULT: the pump social API — the author is a wallet, and there are three backends, not one

Mapped and implemented 2026-08-15. Code: `shitcoims_pumpsocial/` (new package, read-only).
Tests: `tests/test_pumpsocial.py` (44, all offline). Outputs: `state/pumpsocial/`.

```
uv run python -m shitcoims_pumpsocial probe        # re-measure all 57 routes -> surface.json
uv run python -m shitcoims_pumpsocial catalogue    # print the map
uv run python -m shitcoims_pumpsocial firehose     # pump's live callout feed
uv run python -m shitcoims_pumpsocial thread <mint>
uv run python -m shitcoims_pumpsocial graph <wallet> --depth 1
uv run python -m shitcoims_pumpsocial callers <wallet>...
```

**Spend: $0.00.** Every endpoint below is unauthenticated or reachable with a key that ships
in the browser bundle. No X actor, no BigQuery, no credential.

---

## 0. The one-paragraph answer

**The data exists, all of it, for free — the previous lanes were looking on the right host for
the wrong service.** pump.fun's social layer is split across **three** backends and the repo
knew about one. Comments and callouts live on `api.coin-communities.xyz` behind a public
browser key; the follow graph lives on `frontend-api-v3.pump.fun` at `/following/<addr>`; and
pump's *own* callout feed — which the repo has never had, because
`shitcoims_intelligence/adapters/pump_callouts.py` was pointed at `advanced-api-v2` behind a
bearer token nobody ever obtained — is sitting unauthenticated at
`frontend-api-v3.pump.fun/callout/recent`. **57 routes are now catalogued and measured: 30 live,
14 dead, 2 auth-walled, 11 mutating-and-refused.** The structural prize the directive predicted
is real and stronger than expected: **every comment, reply, callout and follow edge carries a
native `walletAddress`**, so the handle→wallet join that limited `RESULT_caller_wallets.md` to
5 of 146 handles simply does not exist here — and the same objects carry `userTwitterUrl` as an
X **numeric id**, with `/api/v1/users/by-twitter-id/{id}` inverting it, so **route 2 of that
study — "pump.fun's own X link", recorded as dead because `x_username` is null on all 317
frontend-api-v3 profiles — is alive on the other backend.**

Three findings came out of the mapping that are worth more than the map:

1. **pump's caller scoreboard cannot express a losing call.** On 500 live callouts,
   `multiple == max(1, round(maxPriceSol / calloutPrice, 1))` holds **500/500 exactly**, and
   **0 of 500** rows have a peak below entry. It is a peak-at-any-later-time ratio bounded
   below by 1 by construction. Measured `averageTimeToPeak` on the operator's caller watchlist
   runs **29 to 549 days**. So "jackduvalcalls hits 2x on 68% of calls" and
   `RESULT_callout_edge.md`'s "buying at the callout is −11.9% at 1 h" are both correct and
   measure different things — and only one of them is a return.
2. **The comment reply tail is countable but not readable.** `replyCount` is served,
   `.../messages/{id}/replies/public` is a hard 404, and the replies are absent from the
   top-level listing. Any "comments on this coin" figure from this API is a count of **roots**
   with a censored tail. The crawler reports that as a number (`censored_replies`), not a gap.
3. **The follow graph is one-directional and 100% timestamped.** `/following/<addr>` returns
   out-edges with a per-edge follow timestamp; `/followers/<addr>` does not exist. On a 58-node
   crawl, **1,896 of 1,896 edges (100%) carry a timestamp**, spanning **2024-04-09 to
   2026-08-15**. Two years of social-graph *events*, free — which is the format that caught the
   homoglyph impersonator in `wallet_labels.yaml`, and it generalises.

---

## 1. The three backends

| host | carries | auth | in the repo before today |
|---|---|---|---|
| `frontend-api-v3.pump.fun` | identity, username search, **the follow graph**, **pump's own callout family**, coin metadata, balances | **none** | partially — profiles and search only |
| `api.coin-communities.xyz` | **comment threads**, callouts with entry price/mcap, global feed, wallet↔X-id join, per-wallet caller stats | public `x-api-key` from the browser bundle | **no — host was unknown** |
| `profile-api.pump.fun` | mirrors the coin-communities paths | user bearer; **401 on every route incl. `/public`** | no |

`api.coin-communities.xyz` is **not a pump.fun domain**. pump's social content is served by a
third party, which is worth stating plainly in a repo whose threat model includes impersonation:
the wallet attribution on a comment is that third party's claim, not chain state.

`advanced-api-v2.pump.fun/callouts` — the endpoint the disabled adapter targets — was never
needed. `MIGRATION_NOTE` in `shitcoims_pumpsocial/endpoints.py` records this so retiring or
repointing that adapter is a decision rather than an oversight. **That package was not touched.**

## 2. How the routes were recovered — not by guessing

pump.fun's webapp ships a generated OpenAPI client (`@hey-api/openapi-ts`) in its Next.js
chunks, and every operation carries its own auth spec beside its URL template:

```js
getFollowers: e => (e.client ?? w).get({
    security: [{name: "x-api-key", type: "apiKey"}],
    url: "/api/v1/users/{user_id}/followers", ...})
```

Downloading the 52 chunks and parsing that pattern recovered **73 operations with their auth
requirements**, plus the base URL `https://api.coin-communities.xyz` and the public key
`cc_367f…` (literally `if ("apiKey" === e.type) return "cc_367f…"` in the bundle). A second
pass over the template literals against `getClientServerUrl()` recovered the `/callout/*`
family. So the **auth column is the server's own declaration**; only the **verdicts** are
inferred, and they are measured, not assumed — which matters, because production disagrees with
the client's own declaration on 7 routes.

The 404 handler is a NestJS default that echoes `Cannot GET <path>`, which makes route existence
directly testable. That is how the dead list below was established rather than assumed.

## 3. The structural prize, confirmed

Every content object carries the author as an address. From a real comment on DREGG:

```json
{"id":"dfcb8321…","username":"emberian","content":"dragon's egg is fully formally verified…",
 "createdAt":"2026-06-27T13:30:45.478528Z","replyCount":1,
 "walletAddress":"PmpDh2BQCMMseKYPxseWTSoX3aAouHE4sWyFWTdkqYE"}
```

That wallet is the operator's own — it appears in `wallet_labels.yaml`'s `our_wallets_targeted`
list — which is a useful accident: the join was validated first on a case where the ground truth
was already in the repo.

**The X join, in both directions:**

- `walletAddress` + `userTwitterUrl: "https://x.com/i/user/294759965"` on every post — the
  **numeric** id, which is stable across handle changes. A handle can be squatted; that is the
  homoglyph impersonator's entire method. A numeric id cannot.
- `/api/v1/users/by-wallet/{addr}` → `{userId, twitterId, username}`. For
  `BAr5csYt..` this returns `twitterId: 1592708747943497728, username: "jackduval"`.
- `/api/v1/users/by-twitter-id/1592708747943497728` → the same `userId`. Inverted.
- `/api/v1/users/by-wallet/batch` resolves a whole wallet set in one POST, and reports a
  per-address `status`, so a wallet with no pump identity is a **recorded miss**, not a
  silently dropped row.

This also settles a discrepancy `studies/quality_callers.py` recorded as unresolved: the pump
username is `jackduvalcalls`, the X handle is `jackduval`, and the platform stores **both** —
`username: "jackduvalcalls"` on frontend-api-v3, `username: "jackduval"` on coin-communities,
joined by `twitterId`. Neither was wrong; they are two fields on two backends.

On a 59-post thread crawl of an active coin, **16 of 17 distinct author wallets carried a linked
X id**. The join rate here is not 3.4%.

## 4. Measured dead, and measured walled

Dead (404 in production), so nobody re-derives them:

- `/replies/{mint}`, `/replies/latest`, `/replies/user/{addr}` on frontend-api-v3 — comments are
  not on this host at all. `quality_callers.py` recorded these correctly; it was right about the
  route and unaware of the other backend.
- `/followers/{addr}` — **no in-edge route exists anywhere.**
- `/api/v1/users/{uid}/followers` and `/following` on coin-communities — declared by the bundle,
  404 in production.
- `/api/v1/leaderboard/callouts`, `/ranked`, and the **user-keyed** stats/history routes — while
  the **wallet-keyed** twin `/leaderboard/callouts/wallets/{addr}/stats` is live. Caller quality
  is reachable one wallet at a time, which is the right shape anyway: the operator cares about
  the callers they follow, not a global top 100.
- `.../messages/{id}/replies/public` — finding (2) above.

Auth-walled: `profile-api.pump.fun` (all routes), and `frontend-api-v3/callout/leaderboard`
(401). Everything a bearer token would unlock sits behind a **wallet signature**, which is where
this package stops by design.

## 5. The traps — five ways this API lies with a 200

Catalogued in `endpoints.py`, guarded in code, and each one has a test.

1. **Identity substitution.** `GET /users/{key}` resolves an address **or a username**.
   `/users/batch` returns HTTP 200 describing a real user whose username is literally `batch`,
   at `He7it3jD..` — an unrelated wallet. Against an operator targeted by a live
   prefix-and-suffix address-poisoning campaign, a resolver that silently answers about a
   different wallet is precisely the hazard. `client.profile()` checks the echoed `address` and
   raises.
2. **`/callout/{id}` returns `{"callout": null}` with HTTP 200** for ids taken verbatim from
   `/callout/top` seconds earlier. Same genus as `?username=` returning `[]`: a 200 meaning
   "no". Test the payload, never the status.
3. **No-data rendered as zero, in the source.** A wallet with no callouts comes back as
   `totalCallouts: 0, twoXPercent: 0.0, medianMultiple: 0.0` — which reads as a *bad* caller
   rather than an *unrated* one. `CalloutStats.rates_are_defined` makes it explicit; the CLI
   prints `UNRATED` instead of `0%`. Measured live on mdudas (`FuP8dYQy..`).
4. **`userId` means two different things.** On the `/callout/*` family it is a **wallet
   address**; on coin-communities it is a **UUID**. Same field name, two backends, both about
   callouts — the highest-probability join corruption on this surface. The parser runs the
   on-curve test, so a UUID quarantines as `userId_not_base58_32` rather than becoming a fake
   address. There is a test named for exactly this.
5. **Two casing conventions in one API.** Listing routes are camelCase; `/communities/batch`
   answers snake_case (`member_count`, `latest_post_at`). No field map is shared between them.

A sixth, ours not theirs, is recorded because it is the bug this work actually shipped and fixed:
`messages_public` caps at **50 rows regardless of `limit`** and returns **no cursor of any
spelling**, so a capped page is indistinguishable from a finished one. The first version of the
crawler reported **59 of a coin's own 176 posts as COMPLETE**. `_paginate` now treats a full page
with no cursor as truncation and the report says `PARTIAL`.

## 6. The callout firehose — pump's own, live, and what its scoring actually means

`/callout/recent?limit=&pageToken=` is a keyset-paginated live feed. Sample: **500 callouts over
24.0 h** (0.3/min — a full day fits in 10 requests), 59 distinct caller wallets, 281 distinct
mints, median market cap at call **$28,090**. Each row: caller wallet, mint, **`thesis` (the call
text)**, `calloutPrice`, `marketCap`, `multiple`, `maxPriceSol`, `peakTimestamp`, ms `createdAt`.
Observed returning calls made in the **same second** as the request — unlike coin-communities'
`feed/public`, which served a cache **9 days** stale.

**The scoring identity.** On all 500 rows:

```
multiple == max(1, round(maxPriceSol / calloutPrice, 1))     500/500 exact
rows with maxPriceSol < calloutPrice                         0/500
```

The peak is tracked forward from the call, so it is bounded below by the entry **by
construction**. Median peak 1.50x, mean 2.65x, max 61.2x, 12.8% sitting at exactly 1.0. Median
time-to-peak **9.2 minutes**, p90 **3.8 hours** — but the per-caller `averageTimeToPeak` from the
leaderboard route runs **29 to 549 days**, i.e. an unbounded forward window. **No number in this
family is a return, and none of them can be negative.** The valuable half is the **entry** side:
`calloutPrice` and `marketCap` are the platform's own record of the bar the call was made at,
which is exactly the join key an event study needs and which nothing else gives us free.

**On the content.** 306 distinct theses of 500 (**39% duplicated text**), with strings like
`"Watching this one closely"` and `"Stealth launch organic community bullish"` recurring across
**different wallets**, while each individual wallet's own theses are distinct. 25 of 59 wallets
made ≥10 calls in the window. That is consistent with a shared template pool — an in-app
suggested-text feature or coordinated automation; this study does not distinguish them and does
not claim to. It is flagged because `RESULT_caller_wallets.md` §2 already found **51.4% of the
X-side callout feed was machine-generated referral spam**, and any JOSHI surface rendering this
stream inherits the same question.

## 7. The follow graph

`/following/{addr}?limit=&offset=` — out-edges with `{username, address, timestamp, followers}`.
Crawl from 5 large callers, depth 1, 58 nodes expanded: **1,896 edges, 715 distinct followees,
0 quarantined** (every address on-curve), **100% timestamped**, spanning **2024-04-09 to
2026-08-15**.

Most-followed inside that sample (in-degree over the 58 expanded nodes):

| in-edges | username | pump followers |
|---|---|---|
| 40 | mitch | 506,918 |
| 38 | ansemconzimp | 546,013 |
| 34 | jeets | 24,183 |
| 34 | daumen | 30,365 |
| 27 | traderpow | 7,676 |

**The asymmetry is a finding, not an inconvenience.** Follower *counts* are free from any
profile; the follower *list* is unobtainable. So in-degree is only ever measured over whoever
you chose to expand, and its inclusion probability depends on the roots. `crawl_follow_graph`'s
docstring says this and the report records `max_nodes` truncation explicitly (the crawl above
reports `PARTIAL`, correctly).

Two follower counts exist for the same person and are **different populations**:
`nativeFollowerCount` 17,447 (pump's own) vs `followerCount` 44,267 (union with X) for
jackduvalcalls. They are separate fields in `Profile` and are never summed.

## 8. The operator's caller watchlist, scored

`state/pumpsocial/callers.jsonl`, for the shortlist in `wallet_labels.yaml` (the eight accounts
the homoglyph impersonator follows — read there as candidate next impersonation targets):

| wallet | n | 2x rate | median peak | avg t-to-peak |
|---|---|---|---|---|
| jackduvalcalls `BAr5csYt..` | 25 | 68% | 2.67x | 29 d |
| slingoor `5YRgrP3m..` | 47 | 55% | 2.12x | 322 d |
| daumen `8MaVa9kd..` | 16 | 62% | 6.05x | 430 d |
| nyhrox `6S8Gezkx..` | 15 | 53% | 2.59x | 39 d |
| jeets `D1H83ueS..` | 9 | 56% | 2.79x | 104 d |
| pxblocito `7Mwof5tB..` | 10 | 40% | 1.77x | 31 d |
| mdudas `FuP8dYQy..` | 0 | — | — | UNRATED |
| **imposter** `9T8QKsR2..` | 19 | 47% | 1.65x | 549 d |

Read the t-to-peak column before the 2x column. **Every one of these rates is a peak statistic
over an unbounded window** (§6), so the table ranks *how high a coin ever went after being
mentioned*, not what a follower could have earned. The imposter having 19 scored callouts at a
47% "hit rate" is the cleanest illustration available that this metric measures nothing about
trustworthiness.

## 9. What this unlocks for JOSHI

Against `design/glass.md` §1's parity map, in dependency order:

- **coin page** — the comment thread and callout list, with wallet-attributed authors, entry
  mcap on every call, and the censored reply tail rendered as censored (§0.2).
- **callouts stream** — `/callout/recent` is a real feed with author wallets and call text,
  where the current design note says the callout stream is "a volatility locator, never a
  direction signal". Now it can carry `x_mint_mention` latency badges against a source that is
  live to the second rather than 9 days stale.
- **trenches feed** — `memberCount` and `postCount` per coin are an attention proxy that exists
  nowhere on chain and costs one request.
- **any wallet in the tape → a person.** `users_by_wallet_batch` turns the on-chain tape's
  counterparties into named pump identities with X ids, in batches, with misses reported as
  misses. This is the join the copytrading and entity-resolution studies did not have.
- **the impersonation defence generalises.** The follow graph's timestamps plus
  `last_username_update_timestamp` are exactly the two clocks that pinned the homoglyph attack
  as deliberate. Both are now available for any wallet, on demand, so that analysis is a
  command instead of a one-off.

## 10. Limits, and what was deliberately not done

- **Read-only by construction.** 11 mutating routes (post, reply, like, follow, report, wallet
  sign-in) are catalogued and the client **refuses to dispatch them** — checked against the
  catalogue, not the HTTP verb, because two of the POSTs are reads. There is a test per route,
  generated from the catalogue, plus one asserting the refusal happens before any transport
  call and one asserting no `Authorization` header is ever sent. **Nothing here signs anything.**
- **The public key is public.** `cc_367f…` ships to every browser that loads pump.fun. It is
  committed as an identifier, not a credential, and must never be moved into a secrets file or
  treated as one. If it stops working, re-mine the bundle; `probe` is what tells you.
- **Rate limits are real.** coin-communities 429s on a ~2/s burst with `retry-after: 1`; the
  client paces per host (1.15 s there, 0.35 s on frontend-api-v3) and honours `Retry-After`.
- **This is a reverse-engineered, unsupported surface.** Every record carries
  `contract_status: unsupported_reverse_engineered`. The catalogue's verdicts are dated facts;
  `probe` re-measures all 57 and names anything that drifted. Two routes drifted during this
  session's own work and both were caught that way.
- **Not done, on purpose:** no historical backfill of the callout feed (the keyset cursor
  supports it; `crawl_recent_callouts(since_ms=…)` is the incremental hook, but no collector is
  scheduled and no live lane was touched); no join of these wallets against the on-chain tape;
  no claim about whether callouts predict anything. §6 characterises the platform's metric and
  stops there — measuring callout edge against our own tape is a study, and
  `RESULT_callout_edge.md` already owns that question.
