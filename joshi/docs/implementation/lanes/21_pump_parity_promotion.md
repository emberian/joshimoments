# Lane 21 — Pump parity, admission closure, and source promotion

Status: offline implementation complete; authenticated promotion unearned  
Wave: W4-02  
Owned code: `crates/joshi-pump-api`, `crates/joshi-pump-adapter`,
`extensions/pump-companion`, `fixtures/pump-api`  
Authority: `read_only_no_execution`

## Result

This lane closes the offline contracts needed to answer a narrow operational question honestly:

> Did one bounded direct Pump response and one response deliberately observed in Ember's ordinary
> Pump browser session represent the same request, session occurrence, visible filter/cursor state,
> decoded-body boundary, page, and reaction window—and, if so, did their ordered provider-response
> membership agree?

It does **not** claim that an authenticated direct route works. No authenticated request was made.
It does not claim product-render order unless a separate render-order witness is supplied. It does
not promote a route after one pair. The companion remains a paused, Ember-present reconnaissance,
drift, and fallback instrument; it is not a continuous source.

## Contracts and status vocabulary

The source-edge contracts are:

- `pump-parity-request-projection.v2`: a common direct/browser digest projection over route,
  origin, hashed path, hashed query values, visible-filter state, cursor/page state, pagination kind,
  and page ordinal. Raw path/query values never leave the source edge.
- `joshi.pump_api.parity_input.v2`: one exact response occurrence. It names the original source
  acquisition ID, pair ID, route/catalog, request/filter/cursor/session occurrence, auth
  disposition, start/receive instants, HTTP status, exact body boundary/digest/length/bytes, and
  optional separate render-order digest.
- `joshi.pump_api.parity_report.v2`: one re-derived pair result with both source acquisition IDs,
  schema, ordered membership, next-cursor, timing, auth, byte/value mismatch, and rendered-order
  uncertainty.
- `joshi.pump_api.promotion_run.v1` and `joshi.pump_api.promotion_report.v1`: the fixed twenty-pair,
  three-session route gate.
- `joshi.pump_source.physical_policy.v1`: exact physical retention/policy bytes kept separately
  from logical evidence bytes.
- `joshi.pump_source.admission_receipt.v1`: the source-specific closure over exact ingress bytes,
  optional source-declared digest, exact durable bytes, canonical logical digest, exact policy
  bytes, store-admission digest, acquisition/gap IDs, counts, catalog, and commit range.

Pair `disposition` is one of:

- `incomparable`;
- `quarantined_companion_schema_or_json`;
- `quarantined_direct_schema_or_json`;
- `exact_bytes_equal`;
- `json_semantic_equal_exact_bytes_differ`; or
- `comparable_with_mismatch_evidence`.

Ordered membership is `exact_match`, `mismatch`, or `unavailable`. Pagination is
`cursor_match_one_page_completion_unknown`, `cursor_mismatch`, or `unavailable`. Render order is
`separately_witnessed_match`, `separately_witnessed_mismatch`, or
`provider_response_only_rendered_order_unwitnessed`.

Promotion is exactly `promotable_continuous_direct_source`, `not_promoted`, or
`authenticated_direct_not_admissible`. The current real-world status is:

```text
not_run_ember_present_required
```

That operational status is outside the synthetic fixture and must not be replaced by its passing
result.

## Common request boundary

The prior V1 comparator could not establish parity. Direct and companion request fingerprints were
different projections, and V1 did not bind visible filters, cursor input, page ordinal, session
occurrence, auth lifecycle, or an interval/skew limit. V1 remains for fixture compatibility but
does not satisfy W4 promotion.

The page-only V2 handoff distinguishes request start, Fetch response availability (`capturedAt`),
and exact decoded-body read completion (`bodyReadAt`). Pair `receivedAt` uses body-read completion,
matching the direct client's complete-body boundary; noncausal source clocks are refused. V1
companion admission continues to use its existing source-native capture clock.

V2 hashes every path/query value before it enters canonical material. The companion computes this
in the main world from the request URL, then posts only digests. The direct side computes the same
material from `LogicalRequest`. A Rust/TypeScript cross-language golden pins:

```text
route       callout_recent
query       limit=20, pageToken=<opaque fixture>
request     sha256:5b1a8618d11ea5e82db7ff655045687041d6b01288a93be29d5e2882c5e62f2f
filter      sha256:6082d6edfb541889d2c990caf17ea94cb564581ac5c2c18c7493ad3e5f84b449
cursor-in   sha256:93439aa1dc7d4b929a45c4c2185edad219c15de28c42a4eb5642aa002254b3b1
```

A pair is incomparable if either projection is partial, any common field differs, the source
acquisition IDs collide, auth dispositions differ or hit a stop condition, timestamps are invalid,
the response intervals exceed the configured skew, or exact body closure fails. A nearby dynamic
response is never silently treated as the same occurrence.

The direct builder accepts only a complete exact body captured at the
`http_entity_body_post_transfer_decoding_identity_encoding` boundary before mapping it to the
common decoded-body comparison label. Content-encoded or truncated direct responses are refused;
the adapter does not pretend their browser boundary is equivalent.

## Mismatch evidence and admission

`crates/joshi-pump-adapter` supplies one strict source-to-spool-to-store seam for both direct and
companion paths:

```text
exact source ingress bytes + source-native digest, if any
  -> strict parse and source adapter
  -> exact DurableIngestBatch bytes + canonical logical digest
  -> exact joshi.pump_source.physical_policy.v1 bytes
  -> EvidenceBatchEntry exact batch/policy closure
  -> PublicStoreReceiptV1
  -> joshi.pump_source.admission_receipt.v1
```

These digest domains are never compared as if their preimages were equal. Direct occurrence
reservations may be acknowledged only after the exact public receipt closes. Companion receives
its existing `joshi.pump_companion.ingest_receipt` only after the same store receipt closes; the
generic Pump receipt is not substituted for the browser ACK.

`prepare_parity_measurement` strict-parses both exact V2 inputs and re-runs the comparator. It
retains three authenticated-private observations under two distinct local measurement acquisition
occurrences: companion input, direct input, and generated report. The report names the two original
source acquisition IDs. It emits no source event, assertion, fact, cursor advance, or coverage
recovery. Thus an auth failure, schema drift, membership difference, pagination defect, partial
projection, or unavailable direct side remains durable mismatch/incomparability evidence rather
than disappearing from a success-only table.

`prepare_promotion_measurement` similarly re-evaluates and admits the exact run and report as two
private observations with zero assertions. Even a synthetically passing report has no API that
changes the census or starts a collector. The census/controller must require a separately closed
real promotion measurement receipt and explicit policy wiring.

Both measurement constructors retain the exact durable-batch bytes and exact physical-policy
bytes produced before append. They expose the same precommit/postcommit `EvidenceBatchEntry`
closure as source ingress and accept a public store receipt only when batch/logical/policy/store
digest domains, admitted counts, acquisition IDs, gap IDs, and the one-commit range agree. The
resulting `joshi.pump_source.measurement_receipt.v1` binds the exact generated report bytes as well.
This is the receipt a later promotion policy must name; a report file or evaluator disposition by
itself is insufficient.

Physical policy is outside the logical batch digest and inside the exact policy/store-admission
closure. Authenticated companion bodies, pair inputs, pair reports, and promotion run material use
`app_private`, forced external storage. Secret session bytes are absent from every DTO, digest,
fixture, spool header, log, and test.

## Promotion measurement

The evaluator requires all of the following for one route/catalog:

- exactly twenty distinct pair IDs;
- at least three distinct non-secret ordinary-session occurrence digests;
- at least nineteen exact ordered-membership matches;
- every pair comparable;
- every difference reviewed, with a review artifact ID whenever mismatch count is nonzero;
- no pagination gap IDs and a complete measured page chain for every occurrence;
- accepted auth, no schema quarantine, and no stop-condition IDs; and
- `ordinary_headless_session_admissible` as the measured session-path disposition.

Anything weaker is `not_promoted`. If no honest headless session path exists, the result is
`authenticated_direct_not_admissible`; companion remains Ember-present fallback and continuous
coverage excludes the surface.

The synthetic twenty-pair fixture proves only evaluator mechanics. It contains nineteen matches,
one reviewed mismatch, three fake session digests, and no gap. It is not evidence about Pump.

## Exact Ember-present handoff

The first authenticated exercise remains deliberately small and interactive:

1. Ember chooses one material GET route naturally exercised in ordinary Pump use. Freeze route,
   catalog, visible filters, page/cursor, maximum pair skew, maximum bytes, and one opaque pair ID.
2. Start from the companion's default paused state. Enable the exact origin and raw capture only
   for this bounded response. Do not enable profile capture unless it is the selected route.
3. Create a random non-secret session-occurrence label and retain only its SHA-256 digest. Never
   inspect or copy cookies, auth headers, challenges, wallet objects, browser storage, or signing
   material.
4. If an honest reviewed owner-only `0600` ephemeral credential file or local broker already
   supplies the same ordinary session, perform one direct GET inside the existing 20-attempt,
   3-retry, 1.1-second-host-interval, 2-MiB bounds. There is no CLI credential value.
5. Stop immediately on challenge/signature/device binding, 401/403, persistent 429, unexpected
   scope, or any need to mine headers/identity/key material or evade a control. Admit the stopped
   pair as incomparable evidence.
6. Export the companion V2 candidate in memory during the handoff, build the direct V2 input from
   its exact acquisition, compare, admit both source batches and the pair measurement, and retain
   all exact receipts before clearing the ephemeral handoff state.
7. Do not add another route. A later preregistered run may collect the remaining pairs across three
   ordinary sessions only after this one occurrence is reviewed.

No authenticated live testing, signup, mutation, engagement, trading, broad crawl, auth bypass, or
remote authenticated capture was performed in this implementation.

## Fixtures and gates

- `fixtures/pump-api/direct-fetch-outcome.synthetic.json` exercises direct ingress, exact body,
  policy, spool, store, and receipt closure.
- `fixtures/pump-api/promotion-gate.synthetic.json` exercises exactly 20 pairs, 3 sessions, 19
  matches, one reviewed difference, and gap-free synthetic pagination declarations.
- `fixtures/pump-api/promotion-not-run.v1.json` is the typed real-world absence state; it prevents
  an unperformed Ember-present run from disappearing from promotion accounting.
- `crates/joshi-pump-api/tests/offline.rs` covers V2 preconditions, auth/schema/membership/cursor
  mismatch evidence, timing, render uncertainty, cross-language request digests, and the promotion
  threshold.
- `crates/joshi-pump-adapter/tests/closure.rs` covers direct/companion digest separation, strict
  receipt bytes, exact policy/spool closure, two-occurrence/three-observation private pair evidence,
  zero semantic assertions, and separately receipted promotion measurement.
- `extensions/pump-companion/tests/parity.test.ts` covers raw-on exact export and refusal of raw-off,
  partial request state, and changed bytes.

Focused TypeScript lint, typecheck, 46 tests, mock replay, Chrome/Firefox builds, and manifest audit
pass. Focused Rust tests, strict rustdoc, dependency-inclusive strict Clippy, and the integrated root
`./scripts/offline-readiness` gate pass:

```sh
cargo test -p joshi-pump-api -p joshi-pump-adapter --offline
cargo clippy -p joshi-pump-api -p joshi-pump-adapter --all-targets --no-deps --offline -- -D warnings
cargo clippy -p joshi-pump-api -p joshi-pump-adapter --all-targets --offline -- -D warnings
cargo doc -p joshi-pump-api -p joshi-pump-adapter --no-deps --offline
cd extensions/pump-companion && npm run check:offline
```

## Root witness accounting

The Wave 4 root witness may count the strict offline contracts, cross-language request-projection
golden, restart-safe direct occurrence reservation, exact source/measurement spool and receipt
closure, mismatch-retention behavior, typed absence disposition, and synthetic evaluator threshold
mechanics. It may also count that the browser companion remains paused, narrowly permissioned, and
non-continuous by construction.

It must not count the synthetic promotion fixture as provider evidence; claim an authenticated Pump
route is parity-proven, headless-admissible, continuously covered, or eligible for census; claim the
companion witnessed rendered order outside its explicit optional digest; infer product-object
validity from a capture attestation; or treat absent authenticated data as an empty feed. Until an
Ember-present run durably closes the required source and measurement receipts, the exact operational
status is `not_run_ember_present_required` and continuous authenticated Pump product coverage is
absent.

## Remaining blockers

- the Ember-present authenticated route has not been chosen or exercised;
- no honest headless ordinary-session path has been demonstrated;
- no real twenty-pair/three-session promotion corpus or receipt exists;
- XHR, WebSocket, service-worker, virtualized DOM, and actual rendered order remain outside the
  companion Fetch boundary; and
- the W4-00 core endpoint/session/bootstrap owner must mount strict adapter calls and require the
  exact promotion receipt before a route can enter census.

Until those close, public exact-mint/SOL-price surfaces remain the only intended direct continuous
Pump reads, and authenticated product surfaces remain excluded from continuous coverage.
