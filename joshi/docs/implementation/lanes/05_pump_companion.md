# Lane 05 — authenticated Pump companion

Status: Wave 1 scaffold complete with a fully offline path. No signed Pump session was inspected,
no live response was captured, and no external state was changed.

## Outcome

`extensions/pump-companion` is a pinned TypeScript/WXT WebExtension that begins paused and has one
purpose: accessibility-oriented observation inside Ember's ordinary, honestly authenticated Pump
browser session.

It can observe only JSON `fetch` responses that all of the following satisfy:

1. Pump's page already received the response through its own request;
2. the destination origin is one of three compiled, user-visible source choices;
3. the method is `GET`, the response succeeded, and the content type is JSON;
4. the destination path matches an exact, non-mutating route family;
5. the source body is at most 512 KiB;
6. the response is projected onto an explicit field allowlist; and
7. capture is enabled under a short lease renewed by the isolated extension bridge.

Normalized observations are copied to one fixed loopback address. The extension does not request
or implement cookies, history, tabs, web request, debugger, scripting, identity, native messaging,
downloads, proxy, wallet, or all-sites capabilities. It does not inspect request headers or page
storage, replay a request, navigate, scroll, click, post, reply, like, follow, report, construct a
transaction, or touch a wallet prompt.

This is a source adapter, not Pump parity and not a trading extension.

## Access posture after Ember's clarification

The operative model is narrower and more concrete than lane 21's earlier hypothetical extension:

> Ember uses Pump normally under Ember's own legitimate session. The companion may assist Ember by
> observing only configured data Pump purposefully delivered to that session. It may copy permitted
> observations locally, but it may not acquire a second identity, emulate authentication, extract
> session authority, replay traffic, synthesize engagement, or evade a platform control.

Pump's current [Terms of Use](https://pump.fun/docs/terms-and-conditions), last updated 02 May
2026, matter in both directions. Section 6.1 expressly says the platform may be accessed through
bots as long as the access complies with the Terms and Pump's rules. The prohibited-conduct
section still forbids unauthorized acquisition, obtaining information not purposely provided,
tracking other users, unreasonable load, authentication/security circumvention, forged identity,
interference, and other listed conduct. This implementation makes the §6.1-compliant personal
accessibility case concrete; it does not pronounce on every field's content/retention rights or
convert network visibility into blanket permission.

That remaining review is **adapter- and field-specific**, not a reason to block the offline core,
on-chain acquisition, exact-mint workbench, or this least-privilege scaffold. The separately stricter
Go.fun terms explicitly name browser extensions and automated collection; no `go.fun` origin or
route is present here.

## Why WXT and ordinary WebExtension APIs

The scaffold pins [WXT](https://wxt.dev/) 0.21.4 rather than maintaining browser manifests,
bundling, main-world injection, and Chrome/Firefox differences by hand. WXT's
[content-script guidance](https://wxt.dev/guide/essentials/content-scripts.html) recommends an
isolated parent content script plus `injectScript` when a narrow main-world script is required.
That is the topology here:

```text
Pump page world
  fetch response clone
  exact origin/route/method/type/size policy
  hash exact bounded decoded-body bytes before parsing
          |
          | window message: untrusted, schema-bounded
          v
isolated content bridge
  no DOM mutation; extension messaging only
          |
          v
WebExtension background
  verify Pump sender page + policy + hash/length again
  lossless parse + tagged allowlist projection + redaction
  bounded session queue + explicit gaps
          |
          | credentials: omit; redirects: error
          v
127.0.0.1:43119 fixed observation sink
```

Chrome's documented extension network model permits a background/service worker to reach an exact
host declared in the manifest, while content scripts remain tied to the page's origin and must not
be allowed to choose arbitrary cross-origin targets
([Chrome: cross-origin network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests)).
The background therefore owns the fixed loopback transport. It never becomes a proxy for a page
URL.

Settings use `browser.storage.local`; the bounded queue and counters use
`browser.storage.session`. Retry scheduling uses `browser.alarms`, and the action badge uses
`browser.action`. These browser lifecycle APIs replace a persistent background process, web
storage, and timer assumptions. Chrome explicitly recommends extension storage for service-worker
state ([Chrome Storage API](https://developer.chrome.com/docs/extensions/reference/api/storage)).

## Permission and origin manifest

The generated Chrome manifest is audited after every offline build.

| capability | declaration | reason |
| --- | --- | --- |
| API permissions | `alarms`, `storage` | durable retry wake-up, persistent settings, session-bounded queue |
| page host | `https://pump.fun/*` | run the isolated bridge only in the reference product session |
| sink host | `http://127.0.0.1:43119/*` | send observations to the local core only |
| web-accessible resource | `pump-main-world.js` on `https://pump.fun/*` | WXT's cross-browser isolated-to-main injection seam |

The audit fails if `activeTab`, `tabs`, `cookies`, `history`, `webRequest`, `debugger`, `scripting`,
`nativeMessaging`, proxy, identity, or other broad/session permissions appear. It also fails if a
host other than exact Pump or the pinned loopback address appears.

Chrome and Firefox both build as Manifest V3. Firefox's current manifest policy requires an honest
data-transmission declaration for new add-ons. The generated Firefox manifest declares website
content/activity, personal communications, and identifying information because social posts,
routes, usernames, and public author addresses are deliberately transmitted to a process outside
the extension—even though that process is local. It does not claim “none.” See Mozilla's current
[`browser_specific_settings`](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/browser_specific_settings)
documentation.

## Compiled response policy

The source chooser cannot accept an arbitrary hostname. It toggles three compiled origin classes:

| UI source | default | accepted response families | excluded examples |
| --- | --- | --- | --- |
| Pump frontend | on | exact `coins-v2/{mint}`; recent/per-mint callouts; current outgoing follows | login/auth, mutations, leaderboard auth, balances, trades, arbitrary coin search |
| Coin Communities | on | exact public community header, root-message, callout/reply, public feed/top-community families when Pump itself fetches them | user lookup, batch reads, writes, API-key handling, dead/private reply routes |
| Authenticated Pump social/profile | off | exact community message/callout families only | auth/login, wallet/balance/profile administration, all mutations |

These paths are technical adapters based on dated local Pump behavior, not a claim that every
route is contractually stable. A new route requires a code/review change; it cannot arrive through
remote configuration or page input.

The companion observes only `fetch` responses already delivered to the page. There is no Pump
poller and therefore no companion-generated Pump request rate. `sourceOrigin` and `sourcePath`
exclude query strings. The observed Pump page path is replaced at the background boundary with the
actual verified sender pathname.

## Field boundary

Normalizers project only named contemporaneous fields needed for coin, callout, community,
message, feed, and following observations. Unknown fields are rejected/omitted by the closed source
contract. Numbers cross as tagged exact JSON-number lexemes, so prices and market caps do not become
binary JavaScript-number truth in the core.

The allowlist includes identifiers, mint/token address, display names, public author attribution,
text, event/display times, reply/like/member/post/follower counts, moderation flags, parent links,
current coin metadata, contemporaneous callout price/market cap, and current lifecycle hints.

It explicitly excludes:

- authorization, cookie, API-key, token, challenge, signature, private-key, and secret fields;
- request headers and request bodies of every kind;
- Pump/page local storage and wallet-provider objects;
- future callout outcome fields such as peak price/time and maximum multiplier;
- unknown response fields;
- query parameters, including cursor and search state;
- arbitrary nested objects.

A public author wallet address that Pump delivered as social attribution is data, not wallet
authority. The extension may normalize that public identifier. It never reads or exports Ember's
wallet provider, seed, key, approval, challenge, signature, session, balance route, or transaction
material.

The page world is hostile and can spoof `window.postMessage`. Accordingly, the page cannot choose
the destination or field schema. The background verifies the sender is `https://pump.fun`, matches
the source origin/path again, replaces the record kind and natural key, filters fields again, and
re-runs token/secret redaction. Every envelope is labeled
`trust: page-delivered-untrusted`; page observation is evidence of what arrived in that renderer,
not cryptographic provider authenticity.

## Exact-byte capture

Exact-byte capture is visibly **off by default** and independent of normalized capture. Default
normalized output is explicitly a lossy companion attestation, not provider-exact evidence. If
Ember opts in, the unchanged bounded Fetch decoded-body bytes (not headers, cookies, requests, or
wire-compressed bytes) travel to loopback with verified content hash/length and an explicit
authenticated-private/local-retention class. See the integration-repair contract below.

## Rate, backpressure, and failure semantics

| boundary | hard limit / behavior |
| --- | --- |
| source response clone | 512 KiB; larger bodies are not read/exported |
| records per response | 100 |
| acquisition queue | 512 acquisitions or 2 MiB, plus a 256-item/256-KiB gap reserve |
| loopback batch | 25 acquisitions/gaps or 256 KiB |
| one worker flush | at most four batches |
| loopback request | two-second timeout; `credentials: omit`; no referrer; redirects rejected |
| retry | one second growing to 60 seconds, or sink `Retry-After` |
| overflow | reject newest observation; increment visible dropped/gap count; never silently evict |

The popup and badge expose `paused`, `idle`, `healthy`, `backpressure`, or `error`, plus acquisition
and gap depth, queue bytes, accepted/delivered/dropped counters, last capture/delivery, and last
error. Every real loss is a separately identified, scope-aware gap; there is no aggregate drop
counter in the admission batch.

The main-world observer runs only under a 45-second capture lease renewed by the isolated bridge
every 15 seconds. If the extension is disabled, updated, or loses its isolated context, the old
page wrapper becomes inert without relying on a service-worker global.

## Fully offline path and result

The package pins Node/npm, WXT, TypeScript, Zod, Vitest, Biome, and every transitive dependency in
`package-lock.json`. The sole approved dependency install script is exact `esbuild@0.28.2`.

From `extensions/pump-companion`:

```sh
npm run check:offline
```

After dependencies are installed, this command requires no network, credential, Pump session,
provider account, or running core. It:

1. formats/lints and type-checks;
2. runs adversarial unit tests over route rejection, normalization, future-field exclusion,
   secret redaction, page-spoof filtering, queue pressure, fixed sink behavior, and retry;
3. replays the checked-in Pump-shaped fixture through the real policy/normalizer/envelope/queue
   pipeline;
4. builds Chrome MV3;
5. audits the generated manifest; and
6. builds Firefox MV3.

Verified 2026-08-16:

- TypeScript clean;
- Biome clean;
- 6 test files, 13 tests passed;
- mock replay: 5 observations, 3 kinds, 3,742 queued bytes;
- frozen mock digest:
  `e1b5f3ab9e9e8184a24dfbe85907dc661785b36a1a4ece0b58fda6890a076ae7`;
- Chrome MV3 build and exact-permission audit passed;
- Firefox MV3 build passed.

## Remaining real signed-session questions

These questions gate individual adapters or fidelity claims. They do not block the offline core,
public/on-chain work, manual exact-mint use, or the existence of this paused scaffold.

1. **Transport coverage.** Do the material Pump social/feed surfaces use page `fetch`, XHR,
   WebSocket, worker-owned fetch, server-rendered payloads, or a mix? The scaffold intentionally
   covers only finite JSON page fetches. A missing transport is recorded before another observer is
   considered.
2. **Route reality.** Which compiled routes actually occur in Ember's current account, locale,
   viewport, and product flags? Remove dead routes; do not probe for replacements from the
   extension.
3. **Ordering and fidelity.** Does response order correspond to served/rendered order, or does the
   app merge, filter, personalize, moderate, and virtualize after receipt? Response capture alone
   cannot claim viewport or choice-set parity.
4. **Main-world compatibility.** Does the transparent `fetch` proxy preserve Pump behavior under
   navigation, backgrounding, errors, aborts, streaming, and another extension's wrapper? Any
   observable breakage disables capture; no retry/evasion.
5. **Signed-in data minimum.** Which authenticated fields Ember actually needs from threads,
   activity, following, or notifications? Authenticated-profile capture remains off until that
   field list and retention are accepted.
6. **Exact-byte retention.** Is provider-response evidence necessary for each route once normalized
   fidelity is measured? If yes, assign per-route expiry/deletion before enabling the private
   exact-byte switch.
7. **Loopback admission.** The core endpoint does not exist in this lane. It must cap body/rate,
   validate the schema, record sender/acquisition provenance, translate drop counts into coverage
   gaps, and reject public-network binding. A later local-only pairing mechanism may authenticate
   the extension installation without ever involving Pump credentials.
8. **Browser support.** Chrome and Firefox packages build offline; an ordinary signed-session run
   must measure WXT injection, storage-session behavior, suspension/recovery, permission UX, and
   local-network policy on Ember's actual browser. Safari packaging is not claimed.
9. **Content/identity safety.** Public author addresses and posts are provider assertions and
   potentially sensitive personal data. Confirm purpose, local-only boundary, deletion, model
   exposure, and whether any material surface contains private/direct content before retaining it.
10. **Terms drift.** Record the live Terms revision at real-session start. A future change or Pump
    access restriction pauses the affected adapter; it does not trigger identity rotation, header
    forgery, new-host discovery, or a platform-wide architectural restart.

## First live validation, when authorized

1. Start the local sink on loopback only with a fixture-backed, non-persistent quarantine.
2. Load the unpacked extension and inspect the generated permission prompt.
3. Confirm the popup begins paused and authenticated-profile/raw capture are off.
4. Open Pump normally; do not create an account, alter follows, post, trade, or manufacture data.
5. Enable Pump frontend capture for one minute while navigating one ordinary existing surface.
6. Compare browser behavior with capture paused and active; any difference is a failure.
7. Inspect every delivered field, source route, queue/drop counter, and secret scan before
   persistence.
8. Enable Coin Communities only if the ordinary page used it and the exact response is in scope.
9. Leave authenticated-profile and raw capture off until their separate field/retention decision.
10. Stop, export the small validation manifest, and decide route-by-route what survives.

No step expands the extension's permissions, makes a Pump request, or turns a missing response into
a reason to replay traffic.

## Integration repair — exact acquisitions, scoped gaps, durable receipts (2026-08-16)

This section supersedes the earlier field-boundary, raw-capture, queue, and sink descriptions where
they conflict. The coherence review found that the first scaffold could not support evidentiary
claims: it parsed with `JSON.parse` before converting numbers to strings, assigned an unrelated UUID
to every extracted row, reported only an aggregate drop count, and dequeued a batch after any 2xx.
Those behaviors have been removed.

### One response is one acquisition

The capture unit is now an opaque, occurrence-specific `acquisitionId` allocated once when the
allowlisted page `fetch` begins. Equal response content observed twice has one equal
`responseBlobId` but two different acquisition IDs. One acquisition carries:

- the page-instance ID and exact decimal-string request sequence;
- route, origin, query-free path, observed Pump page path, capture and receipt clocks;
- a versioned `requestFingerprint` over method, route, origin, path, and only compiled
  pagination/order query keys;
- an explicit `complete` or `partial-query` projection label when unknown query keys were omitted;
- an algorithm-qualified `responseBlobId` in `sha256:<hex>` form;
- response length as a decimal string and the explicit byte boundary
  `fetch-response-decoded-body-bytes`;
- parse disposition and source/emitted/omitted record counts; and
- derived records with stable acquisition-local decimal-string ordinals.

The request projection exists transiently only to compute the digest. Query values, request
headers, cookies, credentials, and request bodies never cross the bridge or enter storage. The byte
boundary is the bytes exposed by the Fetch `Response` after browser HTTP content decoding—not TLS
records, compressed wire bytes, or a provider-signed object. XHR, WebSocket, worker fetch, and
server-rendered data remain uncovered transports; the extension does not silently describe those
as degraded exact capture.

The response clone is read as bounded binary chunks. SHA-256 is calculated on those bytes before
UTF-8 decoding or JSON parsing. The bounded bytes cross to the background, which recomputes and
checks both hash and length, decodes with fatal UTF-8 handling, and parses with pinned
[`lossless-json`](https://github.com/josdejong/lossless-json) 4.3.1. No JavaScript `number` is an
admissible normalization input. A normalized scalar is a tagged value:

| encoding | meaning |
| --- | --- |
| `utf8` | source JSON string after field-specific secret/URL scrubbing |
| `json-number-lexeme` | exact source numeric token, validated against JSON number grammar |
| `boolean` | JSON boolean |
| `null` | JSON null |
| `utf8-list` | bounded string projection from a permitted list |

Thus `900719925474099312345`, `0.0001000`, and `1.2300e+19` retain those exact lexemes. Extracted
records remain derived assertions linked to the acquisition; they are not promoted to independent
observed truth.

V1 now has an explicit dual-fidelity contract. When exact-byte capture is off, source bytes are
transient and disposed after verification/derivation. The envelope says
`lossy-normalized-attestation`, says it is not admissible as exact observation of the provider
response, and names the fidelity limitation. It remains admissible only as exact evidence of what
the companion attested; the adapter must not promote its normalized fields to provider-exact
claims. This epistemic limitation is not fabricated into a temporal coverage gap.

When Ember deliberately enables the raw switch, the unchanged bounded Fetch decoded-body bytes
cross to loopback as base64 with their already verified hash and length. They are labeled
`authenticated-private-source-evidence` / `local-explicit-raw-opt-in`; content identity remains
separate from protection and retention. No cookie, authorization header, request body, query
projection, Pump credential, or wallet material is added. The popup warns that the permitted
response itself can contain personalized content. Authenticated-profile and exact-byte capture
remain off by default.

### Gaps are scoped evidence

Acquisitions queue atomically. The queue no longer contains one independently identified item per
row, and batches no longer carry `droppedBeforeDelivery`. A separate reserved gap queue records a
rejected acquisition with route, origin/path, page instance, acquisition and request identity,
response hash when known, capture/detection time, sequence start/end, last accepted sequence,
explicitly unknown first-resumed sequence, reason, and diagnostic record/byte counts. Oversize and
read-failed response clones emit the same scoped shape from the page boundary. Invalid unscoped
page messages increment a separate rejection diagnostic and are not falsely called coverage gaps.

If even the reserved gap queue cannot admit the gap, capture pauses fail-closed. Counts and byte
sizes are diagnostics, never substitutes for the scope and interval bounds. V1 does not mutate an
already emitted gap after recovery: `firstResumedSequence: null` means explicitly unknown, not
continuous coverage. A later event-tape recovery object may close that bound.

### A 2xx is not a commit

The background prepares the closed `joshi.pump_companion.capture_batch` V1 source-edge request,
with persistent installation ID, worker-session ID, opaque batch ID, and SHA-256 digest, then
persists the complete pending batch before transport. Retries reuse exact serialized logical
content: there is no attempt clock inside the digest. Public Zod objects are strict; source clocks
are explicitly `browser-wall-rfc3339-utc-milliseconds.v1`, and decimal-string integers reject
values above `u64::MAX`. The core adapter, not the browser, converts this source-native contract to
canonical six-digit UTC `DurableIngestBatchV1` evidence.

A successful-looking HTTP response does not dequeue anything unless its bounded, strict JSON body
validates as `joshi.pump_companion.ingest_receipt` V1. This is the HTTP adapter receipt, not a
renaming of the store receipt: the companion ingress digest and post-transformation durable/store
digests have different preimages and remain separate. The adapter receipt must exactly match:

- `accepted` or idempotent readback status;
- the locally paired catalog ID and `joshi.sqlite.v5` schema;
- ingress batch ID and ingress batch digest;
- `accepted` or `idempotent` durable status and the equal V1 commit range;
- separately named durable-batch and store-admission digests returned only after store commit;
- exact acquisition/gap counts; and
- the complete sorted acquisition-ID and real-gap-ID lists submitted by the companion.

The companion does not predict the adapter's assertion/event count or compare its ingress digest
to the store's `DurableIngestBatch` digest. The core integration test owns the exact source-batch →
durable-batch mapping, internal store receipt, admitted closure, and scoped gap-boundary mapping.

An empty, malformed, wrong-batch, wrong-digest, duplicate-ID, or partial 2xx receipt remains
ambiguous and is retried with the same persisted batch. Only a validated durable receipt permits
dequeue.

Delivery fails closed until an explicit local pairing step has placed the expected catalog binding
in extension-local storage; there is no trust-on-first-receipt fallback. The HTTP endpoint adapter
still needs to implement the exact source-batch-to-store mapping and pairing exchange. The first
real sink validation must also decide whether acquisition IDs must be durably pre-reserved before
the page request rather than UUID-allocated at request initiation; the current UUID is
restart-global in collision scope and stable through every queue retry, but a browser crash before
bridge admission can still leave an unreported initiated request. That is an honest coverage
limit, not permission to replay the request.

### Repaired offline gate

`npm run check:offline` now passes with pinned dependencies, TypeScript and Biome clean, 6 test
files / 25 tests, Chrome and Firefox MV3 builds, and the unchanged exact-permission manifest audit.
The adversarial tests include integers above `2^53`, noncanonical-but-valid decimal/exponent
lexemes, equal response content in distinct acquisitions, scope-aware queue drops, idempotent retry
receipts, empty/wrong 2xx bodies, duplicate/dangerous receipt keys, partial ingress closures,
unpaired-catalog refusal, and byte/hash agreement in both fidelity modes. The mock now yields 3
acquisitions / 5 derived records / 7,184
queued bytes with frozen digest
`637dd49060aa684e388484f156479876a8293a0c238296742164478fa1febed5`.

## Files

- `wxt.config.ts` and `scripts/audit-manifest.mjs`: exact capability ceiling;
- `entrypoints/pump-main-world.ts`: finite JSON response observer with an expiring lease;
- `entrypoints/pump-bridge.content.ts`: isolated-world validator and extension messenger;
- `entrypoints/background.ts`: configuration, second validation, bounded queue, health, retry;
- `entrypoints/popup/*`: accessible pause/source/raw/health surface;
- `src/policy.ts`: compiled destination route policy;
- `src/normalize.ts`, `src/hash.ts`, `src/pipeline.ts`: exact-byte, field, and trust boundary;
- `src/parity.ts`: explicit raw-on, in-memory V2 parity handoff; never continuous acquisition;
- `src/queue.ts`, `src/sink.ts`: explicit pressure and fixed loopback transport;
- `fixtures`, `tests`, and `scripts/replay-mock.ts`: network-free continuation path.

### Wave 4 parity boundary

The page observer now computes a second, shared direct/browser digest projection over the exact
request, visible filter, cursor/page state, pagination kind, request start, response receipt, HTTP
status, and source acquisition ID. These page-only fields are deliberately omitted from the V1
companion admission envelope, so its strict store wire remains unchanged. During a bounded
Ember-present exercise, `src/parity.ts` may turn one raw-on page response into
`joshi.pump_api.parity_input.v2`; it refuses raw-off, partial projection, changed bytes, or route
disagreement. It accepts a non-secret session-occurrence digest, never session material. The
extension remains paused/reconnaissance/fallback and cannot establish continuous coverage.

The focused Wave 4 extension gate is now 8 test files / 46 tests, with the same mock counts and
digest above. Full details and the unearned promotion gate are in
`docs/implementation/lanes/21_pump_parity_promotion.md`.
