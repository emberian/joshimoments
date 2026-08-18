# Engineering lane 21 — Pump product and social acquisition

Status: material pre-engineering go/no-go, checked 2026-08-16. This document authorizes no
account creation, authentication bypass, browser-key reuse, large crawl, external message,
transaction, or production collector. It is not legal advice.

## Decision

The complete Pump information surface is **not presently established as a lawful, supported,
stable input from which to build a replacement**.

There are three materially different acquisition layers:

1. Pump's programs and Solana give us a strong, public, independently reconstructible market and
   fee-routing substrate.
2. Pump itself now publishes integration material for a small HTTP surface: exact-mint coin data,
   SOL price, and optional wallet balance summaries. That is useful, but it is not a discovery,
   ranking, social, notification, or chart API.
3. Most of the texture Ember actually means by “the Pump information surface” is rendered by the
   product or supplied by undocumented Pump and third-party services. Anonymous responses,
   browser-visible requests, shipped client keys, permissive CORS, rate-limit headers, and
   `robots.txt` do not by themselves provide a durable permission, licence, or SLA for an
   automated replacement.

The recommended Spike 0 candidate is therefore a **hybrid companion**: on-chain facts as the
canonical market spine; Pump's explicitly described HTTP routes only for their described purpose;
and a deliberately narrow, user-triggered record of the Pump scene Ember is actually looking at,
but only after the access/terms review clears the exact capture method. Pump remains the renderer
for Pump-only ranking, personalization, notifications, threads, livestreams, and moderation until
each field has a reviewed source.

This is a contingent recommendation, not a euphemism for “scrape it and see.” If a lawful capture
basis for the material Pump-only cues cannot be established, or a companion needs broad browser
permissions or session credentials, select **on-chain observatory only** or **stop/rethink**. Do
not build a similar-looking substitute and call it parity.

## Epistemic and access vocabulary

Every source entry needs two independent labels:

- **evidence class:** `chain canonical`, `Pump protocol documentation`, `Pump integration
  documentation`, `Pump renderer observation`, `third-party provider assertion`, `operator
  attestation`, or `derived`;
- **access class:** `public chain`, `officially described HTTP`, `purposefully exported by user`,
  `reviewed user-side capture`, `unsupported/reverse-engineered`, `authenticated/private`, or
  `unresolved`.

A source can be factually useful and still have unresolved collection rights. A source can be
officially described and still contain non-canonical mutable data. “Network-visible” is a
transport observation, not an access class.

In the tables below:

- **Observation** means directly established from an official primary source or the dated bounded
  inspection described here.
- **Inference** means a proposed engineering or product conclusion from those observations.
- **Unknown** means Spike 0 must measure it in Ember's normal session; it must not be filled from
  memory or an unofficial API catalogue.

The in-app browser was unavailable in this research session, so no signed-in Pump page, existing
notification, authenticated activity surface, or interactive chart was inspected. Current product
shell observations below came from bounded anonymous HTTP responses and official indexed pages.
All session-dependent behavior remains `unknown` until Ember's ordinary-session experiment; the
old local corpus is not being used to fill that gap.

## What is actually documented or observable

### 1. Official protocol and chain surface

**Observation.** Pump's official public documentation and IDLs define the Pump bonding-curve,
PumpSwap, and Pump Fees programs. At pinned commit
[`9c82f61`](https://github.com/pump-fun/pump-public-docs/tree/9c82f61cb711b044a17f770ab8ce9f9bdf78f333),
they expose coin creation, trades, lifecycle state, pools, dynamic fee inputs, creator fields,
creator-fee collection, fee-sharing configurations and distributions, social-fee PDAs and claims,
and their emitted events. The [Pump program README](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/PUMP_PROGRAM_README.md)
also makes an important identity distinction: the paying `user` and declared `creator` can differ.

**Observation.** Current collection and distribution semantics are not equivalent to creator
intent. The official
[`COLLECT_CREATOR_FEE`](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/COLLECT_CREATOR_FEE.md)
and
[`CREATOR_FEE_SHARING`](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/CREATOR_FEE_SHARING.md)
documents say the current V2 single-recipient sweeps, shared-fee transfer, and distribution are
permissionless. The
[`pump_fees` IDL](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/idl/pump_fees.json)
shows that a social claim is signed by Pump's configured `social_claim_authority`; its recipient
need not sign, and the claim event itself carries no mint.

**Inference.** The chain is sufficient for a genuine independent launch/trade/reserve/migration/
fee-routing tape and event-backed chart. It is not sufficient for Pump's feed membership or order,
viewer personalization, user awareness, public endorsement, comment text, follows,
notifications, moderation, or audience arrival. Social-claim-to-coin attribution must be a
point-in-time routing reconstruction, never a join from the recipient or current creator alone.

### 2. Pump-authored HTTP integration material

**Observation.** Pump's own agent-skills repository at pinned commit
[`c8aaa6a`](https://github.com/pump-fun/pump-fun-skills/tree/c8aaa6a8fb766b2765d2663744515bbf88d04380)
describes these read routes:

| route | Pump-authored description | safe role |
| --- | --- | --- |
| `GET frontend-api-v3.pump.fun/coins-v2/{mint}` | exact-mint coin record including display metadata, creator, lifecycle/pool hints, market-cap fields, reserves, `reply_count`, and last-trade time | current mutable enrichment for a mint already known by another route |
| `GET frontend-api-v3.pump.fun/sol-price` | current SOL/USD price | auxiliary current conversion, with its own observation clock |
| `GET profile-api.pump.fun/balance/summary/{wallet}` | optional wallet balance summary | cross-check only; Solana accounts remain canonical |
| `GET profile-api.pump.fun/balance/tokens/{wallet}?page=1&size=50` | optional paginated wallet token list | discovery/cross-check only; reconcile to chain |

The current [create-coin skill](https://github.com/pump-fun/pump-fun-skills/blob/c8aaa6a8fb766b2765d2663744515bbf88d04380/create-coin/SKILL.md#L255-L295)
says `coins-v2` is CORS-protected and should be called by a web application's backend. More
importantly, it explicitly says its `token_program` can be stale or incorrect and must be resolved
from the mint account on-chain. The current
[swap skill](https://github.com/pump-fun/pump-fun-skills/blob/c8aaa6a8fb766b2765d2663744515bbf88d04380/swap/SKILL.md#L297-L358)
describes the two profile-balance routes, `sol-price`, and `coins-v2`.

**Inference.** These exact routes have materially stronger provenance than routes recovered from
web traffic. They are still mutable HTTP services with no observed versioning, retention promise,
availability SLA, or general grant for the rest of Pump's frontend API. The official stale-field
warning is an explicit reason to preserve field-level authority rather than label an entire
response “official truth.”

### 3. Current public product shell and transport observations

**Observation (bounded, anonymous, 2026-08-16).** The Pump homepage exposed navigation for
`Home`, `Explore`, `GO`, `Callouts`, `Mayhem`, `Live`, `Competition`, `Support`, and `Terminal`.
Its server-rendered configuration named `frontend-api-v3.pump.fun`, `profile-api.pump.fun`,
`livestream-api.pump.fun`, and `wss://livechat.pump.fun`, as well as mutable feature flags. This
proves that these product concepts and service hosts existed in the anonymous shell at that
moment. It does not establish the signed-in contents, field schemas, feed algorithms,
personalization, retention, or permitted automated use.

**Observation (one bounded response, 2026-08-16).** One `coins-v2/{mint}` response returned an
ETag and `x-ratelimit-limit: 60`, `x-ratelimit-remaining: 59`, and
`x-ratelimit-reset: 60`. This is one route at one time, not a global quota or request budget.

**Observation.** Pump's current [`robots.txt`](https://pump.fun/robots.txt) says `Allow: /` and
disallows selected root paths including `/api/`, `/apikey/`, `/livechat/`, moderation, reporting,
and voice-chat paths. It does not document the API subdomains. The third-party
[`api.coin-communities.xyz/robots.txt`](https://api.coin-communities.xyz/robots.txt) currently
publishes Cloudflare content signals `search=yes, ai-train=no,use=reference`, while disallowing a
number of named bots.

**Inference.** A robots rule is not an API contract, service SLA, copyright licence, or resolution
of Pump's Terms. The coin-communities signal expressly rejects model training; even its stated
reference-use signal would not settle the separate rights, privacy, authentication, or Pump-term
questions. Joshi must not train or fine-tune on that corpus, and any later realtime model use
needs a source-specific review.

### 4. Existing local social feasibility corpus

**Observation (compost, not authorization).** `~/dev/joshibot/shitcoims_pumpsocial` and
`studies/RESULT_pump_social_api.md` record a bounded 2026-08-15 mapping of 57 candidate routes:
30 then-live, 14 dead, 2 authentication-walled, and 11 mutating routes that the client refused.
It found:

- current profiles and wallet-keyed outgoing follows with timestamps on
  `frontend-api-v3.pump.fun`;
- a recent Pump callout stream and per-mint callout lists;
- community headers, root messages, public callouts/replies, and wallet/Pump-user/X-numeric-ID
  mappings on the third-party `api.coin-communities.xyz`;
- current coin metadata and creator state;
- important censoring and semantic traps: unreadable comment-reply bodies, no follower in-edge
  list, read-time follower counts, a global feed observed days stale, a current-only mutable
  creator field, and callout peak/multiple fields containing future outcomes.

**Inference.** This corpus is excellent fixture material and evidence that portions of the social
surface are technically obtainable. It is not a production access basis. The routes are
unsupported, two drifted during the original mapping, and the third-party browser key must not be
treated as permission merely because it is shipped to browsers. Do not put that key in the new
system, re-mine bundles, or schedule the existing probe until terms/access review specifically
clears the exact operation.

### 5. Terms and privacy boundary

**Observation.** Pump's official [Terms of Use](https://pump.fun/docs/terms-and-conditions), last
updated 02 May 2026, govern access to the platform. The current prohibited-conduct language
includes using crawlers, bots, spiders, or manual equivalents to access, copy, or monitor the
platform or obtain information not purposefully made available; bypassing navigation or
presentation; unauthorized access or security/authentication testing; tracking other users;
placing unreasonable load; modifying or incorporating the platform into another application;
reverse engineering; and reproducing or storing Pump IP. This summary is for engineering triage,
not a legal conclusion; the exact proposed workflow needs review against the live text.

**Observation.** Pump's official [Privacy Notice](https://pump.fun/docs/privacy-policy), last
updated 22 October 2024, treats wallet addresses, transaction/activity data, and usage data as
potential personal data; describes purpose- and risk-sensitive retention and data-subject rights;
and warns that combining public-chain data can re-identify people even though the chain itself
cannot be erased.

**Inference.** Ember authorizing capture of Ember's screen does not waive Pump's Terms, other
users' privacy, authors' content rights, or a third-party provider's terms. Pump's privacy notice
describes Pump's processing; it does not grant Joshi a right to copy or retain user content. Any
companion needs an independent purpose, minimum fields, retention schedule, deletion/tombstone
behavior, and a decision about whether data ever leaves Ember's machine.

## Field-level source and coverage matrix

This is the pre-Spike hypothesis. `Unsupported candidate` means the old corpus saw a route; it does
not mean Joshi may use it. `Visible` means an operator can attest to or intentionally capture what
the app rendered; it does not make invisible request data user-exported.

| field or material cue | chain / official source | product or companion coverage | unsupported candidate / limitation | pre-Spike disposition |
| --- | --- | --- | --- | --- |
| mint; create slot/time; payer; declared creator; name/symbol/URI | Pump create instruction/event and metadata accounts/URI | visible on card/page | metadata host can mutate or disappear; declared creator is not human identity | `public chain`; canonical bytes plus observed metadata versions |
| bonding-curve state, graduation, canonical pool, token program | Pump/PumpSwap accounts and events; mint account owner | visible lifecycle badges | `coins-v2` supplies hints, and Pump warns `token_program` can be stale | chain canonical; HTTP is a cross-check |
| trades, reserves, fee inputs, supply | program events/accounts | visible chart/tape may aggregate or filter | frontend current fields do not replace event history | chain canonical with event/ingest/finality clocks |
| genuine chart and OHLCV | derived from decoded events or independently reviewed market source | exact Pump chart viewport/aggregation visible only in product | Pump's candle vendor, corrections, gaps, interval alignment, overlays, and venue stitching are undocumented | own event-backed chart is possible; exact Pump-chart parity unresolved |
| size-specific executable quote | official SDK calculations and query-only routing sources, checked against accounts | Pump/Padre quote visible at action time | a chart mark or market cap is not a quote | derived from current canonical state; keep assumptions and quote age |
| current display metadata, image, social links | metadata URI; officially described `coins-v2/{mint}` | rendered card/page | malicious/removed media; links are deployer assertions | supported per-mint enrichment; sandbox media and retain hashes |
| current market cap, USD cap, last trade, reply count | officially described `coins-v2/{mint}` | rendered card/page | mutable/current-only; USD source and reply completeness unknown | officially described HTTP, timestamp every response; never backfill as historical |
| search result membership and order | none | exact visible result can be captured in a normal search | possible undocumented frontend routes; ranking/session effects unknown | Pump-only/access unresolved |
| Home/Explore/GO/Mayhem board membership, filters and rank | none | visible rows/order/filter state | unofficial endpoint catalogues are discovery leads only | Pump-only/access unresolved; central parity gate |
| card movement/update cadence and below-fold served set | none | viewport captures only rendered rows; DOM may expose more if explicitly permitted | screenshots cannot prove unrendered list membership; virtualized rows vanish | Pump-only; distinguish served, rendered, viewport, and inferred |
| personalization, experiments, locale, moderation gates | none | the current session reveals effects, not algorithm or counterfactual rank | mutable feature flags are not stable capability declarations | Pump-only and partly unknowable; store session context/unknown |
| live/stream/voice badge and stream content | on-chain only if a referenced transaction occurs | visible/audible in product | homepage names livestream/livechat services; schemas, auth, replay rights unknown | Pump-only/access unresolved; audio capture out of scope for Spike 0 |
| Callouts feed membership/order | no | visible in `Callouts`; user can record selected rows | old corpus saw live `/callout/recent`; unsupported, scoring includes future peak fields | selected rows may be companion evidence; no background collector yet |
| callout act, author wallet, mint, thesis, event time | no chain proof of a product callout | visible callout | old corpus saw wallet-keyed objects; provider assertion | unsupported candidate; never treat future `multiple`/peak as an input |
| per-coin community header, member/post/like counts | no | visible current header | third-party route; counts are read-time and population semantics may differ | current provider assertion if access cleared; otherwise Pump-only |
| root posts/comments, authors, event time, media | no | visible on coin page | old corpus saw public root messages; third-party wallet attribution | Pump-only unless source-specific access is cleared; content is hostile/untrusted input |
| comment reply bodies and tree | no | visible subset may be manually captured | old public route exposed counts but reply bodies were censored | Pump-only/incomplete; `unknown`, never zero |
| callout replies | no | visible | old third-party route returned some public replies | unsupported candidate; completeness/moderation unresolved |
| deletes, edits, reports, moderation, visibility reason | no | before/after renderer observations can reveal change, not cause | provider may return flags/deletion time; retained deleted content raises rights/safety issues | event observations with tombstones; no cause inference |
| Pump profile ID/name/avatar and current follower counts | no | visible profile | old Pump/third-party current profile routes; two follower populations differed | mutable provider assertion; snapshot with exact source |
| author wallet ↔ Pump UUID ↔ X numeric ID/handle | wallet signature/chain may prove a wallet act, not profile ownership | visible linked profile can be captured | third-party mappings are provider assertions; handle can change/impersonate | temporal identity edge with evidence level, never a permanent identity fact |
| outgoing Pump follows and follow times | no | current user's following UI may show subset | old Pump route exposed wallet-keyed out-edges; no supported docs | personal/behavioral data and unsupported access; exact review required |
| followers/incoming edges | no | visible count, perhaps a displayed subset | old mapping found no complete in-edge route | unavailable/incomplete; sampled in-degree must name its roots |
| signed-in notifications, read state, deep link, trigger | underlying chain event may be reconstructible, notification act is not | user-visible/session-bound | homepage contained a mutable notifications flag; exact service/auth/retention unverified | Pump-only/private; manual observation only in first Spike 0 |
| personalized activity/history feed | wallet transactions on chain; product acts not | visible/session-bound | exact surface and fields unverified | Pump-only/private until ordinary-session inventory |
| wallet balances/token list | Solana RPC canonical; Pump-authored optional profile routes | visible portfolio | HTTP can lag or omit accounts | chain canonical; HTTP cross-check only |
| ordinary fee sweeps and shared distributions | Pump/PumpSwap/Pump Fees instructions/events | may render as claim/activity | anyone may trigger current V2 sweeps/distributions | public chain; label exact permissionless predicate, not creator action |
| creator and fee route through time | point-in-time Pump/PumpSwap/Fees account/event reconstruction | UI generally shows current state | `coins-v2.creator` is current-only; fee-sharing can replace creator with PDA | chain temporal graph; never project current creator backward |
| social-fee destination/claim | Pump Fees account/event | UI may name a social recipient or claim | claim event has no mint; platform authority signs, recipient need not | chain fact plus point-in-time routing; not awareness/endorsement by itself |
| CTO/community takeover | some resulting route/admin changes are on chain | application/review/result may be product-only | process, evidence, rejection and semantics are discretionary/off-chain | separate product event; do not infer from creator change alone |
| creator awareness, public participation, endorsement | no | attributable first-party posts/streams/cross-links can be evidence | claim, fee sweep, metadata link, or same name is insufficient | derived only from preserved evidence and explicit predicate |
| duplicate/fancoin family and audience migration | all coin launches provide denominator; transfers/trades show wallet flow | product search/community context contributes candidates | no canonical target/duplicate relation | versioned inference with unresolved members; preserve every candidate |
| operator viewport, focus, dismiss, compare, gesture | no external source | Joshi can own these events; Pump screenshot can show scene | screenshot does not prove gaze, served-below-fold rows, or hidden tabs | operator/Joshi canonical once capture is implemented |
| screenshot | image bytes plus app/window/time manifest | faithful evidence of visible pixels at one moment | may contain balances, notifications, identities, NSFW media; OCR loses structure | secondary evidence, user-triggered and app-scoped; never sole feed record |
| latency, cache, schema version, errors, coverage | RPC/provider headers and our clocks | app refresh can be visually sampled | one rate header is not universal; product/CDN caching unknown | must be measured per route/session and preserved with every comparison |

## Architecture choices

### A. Product replacement

```text
reviewed source adapters + on-chain index -> own feed/rank/workbench -> Ember
```

**What it buys.** Joshi controls the complete served set, viewport telemetry, stable replay, list
freezing, chart semantics, and operator gestures. If source membership and latency are faithful,
this is the cleanest eventual apparatus.

**What it does not currently have.** No official source found in this review supplies Pump's
named discovery-board membership/order, search rank, notifications, follows, complete threads,
livestreams, or personalization. The officially described per-mint endpoint cannot discover the
same candidates Ember would have seen. A reverse-engineered list endpoint can return convincing
cards while still missing session filters, ranking changes, moderation, feature flags, or a
material cue.

**Go condition.** Choose replacement only after the selected discovery loop clears the exact
100-card/95%/reaction-window gate below **and** the access basis for every automated source is
documented. Unsupported frontend traffic is not an acceptable hidden dependency for the first
replacement claim.

### B. User-authorized browser companion

```text
Pump remains renderer -> explicit local capture/gesture -> Joshi scene + chain join + replay
```

There are three different companion mechanisms, in increasing risk:

1. user types/pastes a mint or uses a purposefully provided Pump share/export action;
2. user deliberately captures the Pump application window at a consequential moment;
3. a Pump-origin extension reads rendered DOM or observes product network requests continuously.

The first two should be tested before the third. A screenshot plus explicit `surface`,
`sort/filter`, selected mint, and one operator gesture may be enough for an early companion, even
though it will not recover the full choice set. A DOM/network extension could recover more
structure, but it is also the mode most exposed to Pump's monitoring/incorporation restrictions,
DOM drift, private-session data, and accidental credential access. Do not assume that “the user
can see it” means an extension may continuously copy it.

**Minimum safety boundary if reviewed capture is permitted:**

- exact `https://pump.fun` origin allowlist; no all-sites, browsing-history, clipboard, microphone,
  keystroke, download, or arbitrary-tab permission;
- never read, log, export, or replay cookies, authorization headers, wallet challenges/signatures,
  local/session storage, private keys, or the third-party browser key;
- no background request replay, authentication emulation, CORS bypass, bundle mining, hidden-tab
  crawling, synthetic scrolling, or follow/post/like/report actions;
- an unmistakable capture indicator and a one-click pause/delete control;
- user-triggered capture first; local encrypted storage; crop/redact wallet balances,
  notifications, direct/private content, unrelated tabs, and OS chrome by default;
- third-party text and media treated as hostile data: sanitize HTML/URLs, proxy or hash media only
  after review, never execute content, and never allow a post to become an instruction to an LLM
  or tool;
- no raw Pump/social content sent to a remote model until the source, purpose, retention, and
  provider-processing terms have separately passed review.

**Go condition.** Select companion mode only if the exact capture operation is reviewed, Ember can
use it without clerical interruption, material scene cues survive, and permissions remain inside
the boundary above. User consent is necessary but not sufficient.

### C. On-chain observatory

```text
Pump/PumpSwap/Pump Fees events + accounts + metadata -> independent census/chart/routing graph
```

**What it buys.** This is the most provider-independent path. It can census every decoded launch,
retain metadata versions, construct real trade/reserve charts, follow migration and fee routing,
reconstruct duplicate candidates, observe wallets, and build fancoin/claim risk sets without
Pump's discovery APIs. Multiple RPC/indexer providers can be checked against finalized chain data,
and saved slots can be replayed.

**What it loses.** It cannot know which Pump cards were served or ranked, what Ember saw, which
thread or callout changed the decision, who was notified, the moderation state, the livestream,
or whether a wallet/profile attribution reflects a human. It can build a new information surface;
it cannot claim to measure or replace Pump's attention surface.

**Go condition.** Choose observatory mode if independent market/social research is useful even
without Pump parity. If Ember's edge depends on the missing product texture and the observatory
does not become a natural place to look, stop instead of broadening the indexer.

### Recommended provisional shape

```text
                   +--------------------------+
Pump normal UI --->| narrow reviewed companion|---> scene/gesture evidence
                   +--------------------------+             |
                                                                v
Solana + Pump IDLs ---> canonical market/fee tape ----------> replay/workbench
                                                                ^
officially described HTTP ---> per-mint current enrichment -----+
```

No unsupported social collector sits on this diagram. One may be added later only as a named,
reviewed, replaceable provider with its own contract, rate, privacy, and failure status.

## Credential, privacy, and provider boundaries

### Credentials and wallet separation

- The read-only cockpit has no signer, broadcast path, wallet-adapter approval request, or reason
  to ingest a seed phrase/private key.
- Pump session material belongs to Pump. Joshi stores no Pump cookie, bearer/JWT, login challenge,
  wallet signature, browser storage, or captured request header.
- Public wallet addresses are not secrets, but mapping them to handles, follows, notification
  state, screenshots, and Ember's dispositions creates a sensitive behavioral dossier. Store the
  minimum locally, partition Ember's private annotations from public-chain records, and define
  export/deletion behavior before collection.
- Never commit provider tokens or browser-shipped keys. A client-shipped key can still be metered,
  revoked, purpose-restricted, attributable, or contractually protected.

### Content and identity safety

- Keep `author_wallet`, Pump UUID, external numeric ID, current handle, displayed name, and human
  subject as different nodes with time-bounded evidence edges.
- A wallet string or handle returned by a service is a provider assertion. Validate address shape
  and echoed lookup keys; the old corpus found HTTP-200 identity substitutions and incompatible
  meanings of `userId` across services.
- Preserve impersonation, compromise, rename, deletion, and conflicting identity evidence. Never
  auto-promote a content author to “the creator.”
- Treat posts, profiles, metadata, SVG/HTML, image URLs, livestream titles, and links as malicious
  input. Use strict output escaping, media MIME/size limits, isolated rendering, and no automatic
  link fetch from privileged networks.
- Notifications and screenshots may contain private or highly contextual information. Default to
  not capturing them; when a consequential notification is deliberately retained, crop to the
  minimum fact and expire raw pixels after structured verification unless Ember explicitly pins
  the artifact.

### Provider and operational risk

- Maintain a provider registry at field granularity: owner, purpose, access basis, authentication,
  observed rate/cache headers, allowed retention, authoritative fields, schema hash, last probe,
  fallback, and kill switch.
- Rate-limit per host **and per route**. Honor `Retry-After`, ETag/conditional requests, and cache
  headers. Treat 401/403/429 as a stop or backoff event, never an invitation to rotate identity,
  alter headers, acquire more credentials, or find another hostname.
- Store `t_event`, `t_observed`, request start/end, server/cache date when available, source version,
  completeness, and raw-payload hash. A 200 with empty/null, a full page without a cursor, and a
  missing row are distinct states.
- Build adapters so an unsupported social provider can be disabled without breaking the canonical
  chain tape or replaying old provider assertions as fresh facts.
- Provider availability is not source coverage. Compare against the actual Pump scene and retain
  mismatches, invisible rows, late rows, deletions, and unknowns.

## Exact Spike 0 experiments

The experiments are sequential gates with one deliberate loop: experiment 0 first clears only
normal manual observation and app-scoped note-taking; experiment 1 then identifies the actual
workflow; and experiment 0 is finalized for the exact sources and capture operations before any
experiment 2–6 automation. Do not start an automated HTTP or browser-capture probe until that
final review clears its exact source and method. “Exact” means the written protocol below is frozen
before results are viewed; it does not mean the proposed thresholds are scientific estimates.

### Experiment 0 — access and data-inventory gate

**Inputs:** the live Pump Terms and Privacy Notice; Pump `robots.txt`; pinned official public-docs
and skills commits; the exact selected routes/capture operations; proposed retained fields and
retention.

**Procedure:**

1. Initially clear only normal manual use and app-scoped notes for experiment 1. After those three
   sessions, return here and name one ordinary Pump workflow; do not write “Pump generally.”
2. For every proposed field, record evidence class, access class, owner/provider, whether it is
   user-specific, content/personal-data status, intended purpose, raw retention, derived retention,
   deletion/tombstone behavior, model exposure, and fallback.
3. Review the exact operation, not merely the host: normal manual use, user-triggered screenshot,
   DOM read, network observation, official HTTP GET, unsupported HTTP GET, or chain RPC.
4. If permission/contractual interpretation is uncertain, obtain qualified review or written
   provider permission before that operation. Contacting a provider is a future external action
   requiring Ember's separate authorization; this research did not do it.

**Pass:** each operation is `cleared`, `excluded`, or has a named human owner and deadline; no
automated test depends on `unresolved`. **Fail:** “public,” “in the browser,” “robots allows it,”
“no auth,” or “the key ships to everyone” is the entire access rationale.

### Experiment 1 — three ordinary-session workflow traces

**No automation.** With Ember participating normally, record app-scoped notes for three sessions
on different days. A user-triggered app-window screenshot is optional only if experiment 0 clears
it. Do not create an account, alter follows, generate notifications, or make trades for the test.

For every material candidate, record:

- surface name and route, signed-in/out state, visible sort/filter/search, viewport size, session
  start, locale if known, and whether a product experiment/banner is visible;
- exact visible neighboring mints/order and whether rows moved while Ember inspected;
- card, chart, thread, callout, profile, notification, live/media, holder/flow, and external-tool
  cues Ember actually used;
- inspect, dismiss, compare, switch-to-Padre/Pump, watch-flat, partial exit, full exit, and re-entry
  acts, without demanding an explanation;
- every cue Ember calls material that is not available from chain or an officially described
  endpoint.

**Output:** one selected discovery-to-coin-page loop, chosen by observed frequency and importance;
an exact field list; a measured reaction window from candidate appearance to meaningful act; and a
list of Pump-only cues. **Stop:** the workflow is too session-sensitive to observe without changing
it, or Ember's natural behavior depends on private/other-user content that should not be retained.

### Experiment 2 — official-source and chain truth probe

**Scope:** 20 exact mints selected by experiment 1, including bonding-curve, graduated, Token-2022
or nonstandard cases if naturally encountered. No full-market crawl.

For each mint:

1. Decode mint owner, Pump bonding curve, canonical PumpSwap pool if present, relevant global/fee
   accounts, create/trade/migration/creator/fee events, and metadata URI from two independent
   read-only RPC/indexing paths where practical.
2. Fetch `coins-v2/{mint}` only if experiment 0 cleared that officially described use. Use a
   descriptive user agent, at most one initial request and one conditional request after at least
   60 seconds per mint; honor cache/rate headers and stop on 401/403/429.
3. Record status, latency, Date/Age/ETag/cache/rate headers, schema hash, raw hash, null/absence,
   and field-by-field agreement. Resolve token program only from chain.
4. Build a trade-event chart and a size-specific query-only quote. Compare the displayed Pump
   chart semantics manually; do not reverse-engineer its vendor.

**Pass:** at least 18/20 mints have a genuine event-backed path and quote; every unsupported case
is named; protocol-critical fields resolve from chain; current HTTP fields have explicit clocks
and no historical projection. This supports the coin workbench, not discovery parity.

### Experiment 3 — selected-surface 100-entry fidelity audit

**Reference sample:** 100 consecutive cards/list entries from the selected surface across the
three sessions. “Consecutive” means no cherry-picking or successful-coin filter. Record exact mint,
reference rank/order, reference appearance time to available precision, material visible fields,
and session context. If a screenshot cannot cover a virtualized/offscreen choice set, record only
what is actually known and do not call it 100 served entries.

**Candidate comparison:** use only sources cleared in experiment 0. For every entry compute exact
mint match, candidate-source arrival time, order/rank match where defined, missing/extra status,
and field disagreements. Preserve candidate-source extras and reference misses.

**Replacement pass:**

- exact mint and order are measurable for all 100 reference entries;
- at least 95 entries arrive from the candidate source inside experiment 1's reaction window;
- every material cue is reproduced or explicitly unavailable, with no unknown omission;
- the workbench clears experiment 2 for at least 90% of inspected mints; and
- access, cache, rate, auth, schema, and breakage behavior are documented.

Opaque personalization or an unobservable served set prevents a replacement pass; it does not
become approximate success.

### Experiment 4 — lowest-privilege companion trial

Run only if replacement fails and experiment 0 clears the capture method.

**Stage A:** during five ordinary sessions, allow Ember to make at most 20 deliberate app-window
captures at consequential gestures. Each capture gets local monotonic/wall time, Pump route,
selected mint if known, viewport dimensions, the operator gesture, and an independent chain/source
watermark. No continuous recording, OCR-driven clicking, DOM access, network interception,
microphone, or hidden-tab capture.

Test whether replay recovers the selected mint, visible choice set/order, chart domain, material
badges, relevant social context, source health, and Ember's gesture. Raw pixels expire after 14
days unless explicitly pinned; derived fields retain the raw hash and redaction/deletion status.

**Stage A pass:** at least 19/20 consequential captures produce a recognizable replay with no
unknown material omission; median capture/gesture overhead stays below Ember's chosen threshold;
and no capture includes unexpected credentials, private content, unrelated application data, or
wallet approval UI.

**Stage B:** a DOM-aware origin-scoped companion is considered only if Stage A lacks one named
material field and experiment 0 separately clears that exact read. Its manifest must request only
Pump-origin active-tab access; a test fixture must prove that cookies, storage, request headers,
keystrokes, wallet UI, and other origins cannot be read. Network interception/replay remains out of
scope.

### Experiment 5 — notifications, follows, activity, and thread reality check

This is manual observation of existing state in Ember's normal Pump session, not endpoint probing.
Across the same five sessions, when the product naturally shows one of these objects, record only:

- notification: displayed type, visible actor/mint, displayed time, deep-link destination, and
  whether the underlying public event can be independently reconstructed;
- following/activity: visible list meaning, ordering, timestamps, counts, and whether it appears
  personalized;
- thread: number of visible roots/replies, expansion behavior, edit/delete/moderation indicators,
  author identifiers, and what Ember used;
- chart: interval, venue/lifecycle boundary, visible overlays, interaction/drawing behavior, and
  any value not reproduced by the event-backed chart.

Do not inspect tokens, replay requests, follow/unfollow, post, like, report, or manufacture an
event. **Output:** each field is `material companion-only`, `reconstructible`, `non-material`, or
`unknown because no natural example occurred`. Unknown is not failure and is not permission to
probe an account.

### Experiment 6 — provider failure and privacy rehearsal, offline

Using only saved, approved fixtures:

- remove each HTTP/social provider and prove the chain tape still works and the UI says exactly
  what disappeared;
- replay a 200/null, 200/wrong-identity, 401, 403, 429 with `Retry-After`, schema change, stale
  cache, full page/no cursor, deletion, handle rename, and conflicting wallet/X mapping;
- verify that a provider record cannot overwrite chain facts or a past as-known scene;
- verify HTML/script/svg/prompt-injection payloads render inertly and never reach tool execution;
- exercise screenshot expiration, export, redaction, tombstone, and deletion; scan repository,
  fixtures, logs, and model payloads for cookies, bearer tokens, wallet signatures, and keys.

**Pass:** every fault becomes a visible source state, no credential is retained, and removal of an
unsupported provider narrows claims rather than corrupting history.

## Mode-selection table

| observed result | select | permitted claim |
| --- | --- | --- |
| experiment 3 passes and all automated acquisition is cleared | replacement-capable for the **one named surface only** | Joshi reproduces that sampled loop within measured coverage/latency |
| experiment 3 fails, but experiment 4 passes with reviewed low-privilege capture | companion-capable | Joshi preserves the Pump scene Ember deliberately captures; Pump remains the discovery renderer |
| companion is not cleared/useful, but experiment 2 proves a useful independent workbench | on-chain observatory only | Joshi observes an independent Pump-program universe, not the Pump product funnel |
| missing Pump-only texture is material and neither replacement nor companion is lawful/reliable/natural | stop/rethink | no parity or attention-funnel claim |

## Stop and rethink conditions

Stop the relevant path immediately if any of these occurs:

- the access basis for a material automated endpoint or capture operation remains unresolved after
  the review gate;
- a 401/403/429, CORS boundary, hidden route, browser key, or short-lived token would need to be
  bypassed, replayed, rotated, mined, or borrowed;
- replacement misses more than 5% of the consecutive reference choice set inside the reaction
  window, exact order cannot be measured, or a material cue remains an unknown omission;
- ranking/personalization is central but only a different anonymous/general feed is reproducible;
- a browser companion needs cookies, bearer headers, wallet signatures, browser storage, broad
  history/all-sites permissions, continuous network interception, synthetic navigation, or
  background capture;
- screenshots cannot preserve enough structure for recognizable replay, or the privacy/redaction
  burden materially changes Ember's behavior;
- threads, notifications, follows, livestreams, or moderation are material but only available by
  collecting private/third-party content without a cleared purpose and retention basis;
- provider fields change meaning without versioning, or rate/cache behavior makes arrival slower
  than the reaction loop;
- an on-chain-only workbench repeatedly sends Ember back to Pump for unknown material context and
  does not become naturally useful;
- the proposed system starts calling a fee sweep “creator action,” a social-authority payment
  “endorsement,” a current creator “creator at launch,” a follower count “audience arrival,” a
  screenshot “served set,” or a provider wallet mapping “verified human identity.”

The last condition matters as much as access. A lawful source used with the wrong predicate would
still build the wrong apparatus.

## Dependencies and unresolved decisions

Before engineering a collector, this lane depends on:

- Ember's three-session workflow inventory and selection of one real discovery loop;
- an exact access/terms review for each proposed automated endpoint and companion operation;
- the event tape's field-level provenance, event/observation clocks, completeness, source-health,
  raw-hash, and as-known replay semantics;
- the protocol/account resolver from lane 04 for point-in-time creator, sharing, social-fee, and
  CTO-related routing;
- a genuine event-backed chart and query-only quote path from the market/execution lanes;
- local data protection: encryption, retention, deletion/tombstones, hostile-content isolation,
  and model/tool boundary;
- a decision about whether raw screenshots or social content may ever leave Ember's machine;
- a provider registry and kill-switch behavior before any unsupported source is reconsidered.

Unresolved questions to answer from normal use rather than assumption:

1. Which single Pump surface actually starts Ember's most important current loop?
2. Is its ordering personalized, and does the product expose any purposeful export/share mechanism?
3. Which card and coin-page cues are material that chain plus the documented per-mint endpoint do
   not reproduce?
4. Are notifications, following/activity, full reply trees, callouts, live content, and chart
   drawings genuinely decision-relevant or merely available?
5. Is a user-triggered screenshot companion sufficient, or is exact choice-set structure central?
6. Would Pump or its social provider offer a documented integration/licence for the selected loop?

Until those answers exist, the engineering conclusion is deliberately narrow:

> We can confidently build the canonical on-chain spine and a per-mint workbench. We cannot yet
> confidently build a complete Pump alternative. The next useful work is a bounded, reviewed
> fidelity experiment—not a generalized scraper and not a frontend built on guessed parity.

## Primary sources and dated local evidence

- Pump, [Terms of Use](https://pump.fun/docs/terms-and-conditions), current page observed
  2026-08-16; page states “Last Updated: 02 May 2026.”
- Pump, [Privacy Notice](https://pump.fun/docs/privacy-policy), current page observed 2026-08-16;
  page states “Last Updated: 22 October 2024.”
- Pump, [`robots.txt`](https://pump.fun/robots.txt), observed 2026-08-16.
- Coin Communities, [`robots.txt`](https://api.coin-communities.xyz/robots.txt), observed
  2026-08-16. This is a third-party provider policy surface, not Pump protocol documentation.
- Pump, [public docs repository](https://github.com/pump-fun/pump-public-docs) at commit
  [`9c82f61`](https://github.com/pump-fun/pump-public-docs/commit/9c82f61cb711b044a17f770ab8ce9f9bdf78f333),
  2026-07-16.
- Pump, [agent skills repository](https://github.com/pump-fun/pump-fun-skills) at commit
  [`c8aaa6a`](https://github.com/pump-fun/pump-fun-skills/commit/c8aaa6a8fb766b2765d2663744515bbf88d04380),
  2026-04-23.
- Local dated feasibility evidence:
  `~/dev/joshibot/studies/RESULT_pump_social_api.md`,
  `~/dev/joshibot/shitcoims_pumpsocial/endpoints.py`, and
  `~/dev/joshibot/shitcoims_pumpsocial/client.py`, produced 2026-08-15. These are not an access
  authorization or source of current contractual truth.
