# Wave 1 integration review

Status: **pre-integration contract and patch plan; no live authority**
Reviewed: 2026-08-16
Scope: `PROGRAM.md`, the shared Rust domain/evidence core, read-only sources, accounting,
SQLite/CAS/tape, glass, Pump companion, and the analysis snapshot fixture as they existed during
the Wave 1 merge.

## 1. Integration judgment

The repository has the right major pieces, but it is not yet one evidence machine. During this
review the component lanes repaired several defects that were initially P0: source frames now
retain their transport envelope and checked half-open event time; the companion captures numbers
as lexemes and distinguishes exact private response bytes from a lossy attestation; migration
`0005` retains the Rust evidence sidecars; the store now holds a process writer lease and exposes
evidence-justified scoped cursors; and glass now serves one strict, digest-bound view per replay
mode. Those are real advances, not paper resolutions.

The integration risk has therefore moved to the joins: there is still no core adapter from the
companion envelope to `DurableIngestBatch`, and a live repair briefly conflated the ingress digest
with the different durable-batch digest. The store now has scene/command and all-files export
transactions, but it does not yet parse a glass view or final analysis manifest and prove that their
duplicated indexes agree. There is no accounting projection DTO, store-backed snapshot endpoint,
or root command exercising the whole lineage. The old in-memory catalog continues to contain
intentionally incomplete watermark logic, so it must remain fixture-only.

These are integration defects, not reasons to abandon the architecture. The repair is to name one
canonical representation at each boundary and make every other representation a checked physical
encoding or an explicitly lossy display. The V1 path remains read, record, replay, render, mark,
and analyze only.

The target topology is:

```text
direct provider/Pump bytes / companion capture
        |
        v
source-specific admission adapter --rejects loss/degradation--> visible problem + gap
        |
        v
DurableIngestBatchV1 -> SQLite/CAS one-writer commit -> DurableReceiptV1
        |                         |
        |                         +--> exact as-known projection at CommitSeq
        |                                      |
        |                                      v
        |                              GlassViewV1 bytes/digest
        |                                      |
        |                                      +--> Scene + evidence-only CommandV1
        |
        +--> ExportSnapshotManifestV1 -> Parquet parts -> Python validation/run
```

The arrows are directional. A display decimal does not flow back into accounting; an analysis row
does not mutate the catalog; a command records an operator gesture and cannot call a transaction
builder; a source cursor is authoritative only when committed with its evidence.

### 1.1 Observed validation at review close

The live tree passes its component gates:

- `cargo test --locked --workspace --all-targets`: 111 tests passed, including three direct store
  tests, the Rust assertion over the final glass golden, exact Pump API parsing, source evidence,
  the new exact-arithmetic crates, and 15 remote-spool protocol tests;
- `cargo clippy --locked --workspace --all-targets -- -D warnings`: passed after the late Pump API,
  math, liquidity, and spool additions were reconciled;
- `cargo fmt --all -- --check` and workspace rustdoc with warnings denied: passed;
- `./schema/validate.sh`: five migrations, 13 commits, six observations, seven assertions, and all
  printed invariants passed under bundled SQLite 3.53.2;
- glass: 79 tests, typecheck, and production build passed, including strict Gregorian timestamps,
  checked Unix-second/long-uptime monotonic conversion, strict operator commands, retry/receipt,
  and the no-economic-fields boundary;
- companion: 43 tests and the full offline check passed, including strict Gregorian source time,
  typecheck, mock replay, Chrome/Firefox MV3 builds, and manifest audit; and
- analysis: 24 tests and Ruff passed under the locked `uv` environment after the richer manifest,
  multi-table fixture, composite provenance closure, explicit gap rows, and empty-optional-table
  repairs landed.

This is meaningful component evidence, but it is not the missing integration signal. None of these
commands drives one source/companion occurrence through durable admission, a stored glass scene, a
semantic mark, a registered export manifest, and Python analysis. Section 10 defines that one root
gate.

## 2. Ranked blockers and reconciliations

### P0 — must be fixed before calling the walking path integrated

| # | Boundary | Current state at review close | Required reconciliation |
|---:|---|---|---|
| 1 | source edges -> core -> store | `joshi-sources` maps read-only stream frames into shared evidence drafts, and the new closed-GET `joshi-pump-api` preserves bounded response attempts, exact body bytes, restart-safe identity, request fingerprints, and scoped windows/gaps. The companion likewise preserves response occurrences, exact number lexemes, scoped real-loss gaps, retry identity, and optionally exact decoded-body bytes; raw-off is explicitly a lossy attestation. No live edge is wired through a batcher to the durable store; the Pump API `FetchOutcome` and companion capture batch additionally need typed source adapters. | Add the stream batcher/sink plus both strict source adapters and receipt derivation in section 4, converging only at `DurableIngestBatchV1`. A degraded envelope may be exact evidence of what its collector attested, but normalized fields never become provider-exact assertions. A fidelity limitation is not fabricated into a temporal coverage gap. |
| 2 | public wire primitives | Glass now uses six-digit UTC with manual Gregorian validation, decimal-string integers, strict schemas, and a duplicate-/prototype-safe raw parser. Cross-review caught and repaired its former `Date.parse` normalization of impossible dates. The companion now applies the same Gregorian rigor to its three-digit source clock; it also has full-`u64` bounds, paired catalog binding, and duplicate/dangerous-key/unsafe-number receipt parsing. | Preserve these landed edge checks, add cross-language time/integer/digest goldens, and implement/test the explicit three-to-six-digit source-clock normalization in core. Closed schemas reject rather than strip unknown fields. |
| 3 | evidence -> store | Migration `0005`, writer lease, protection-domain blob objects/disposal, SQL-semantic preflight, scoped cursor query, assertion-value digest recomputation, relation-sidecar closure, and three Rust ingest/idempotency/crash tests have landed. The structural `DurableReceipt` is exact as a Rust result, but its derived JSON is not a canonical recursive public DTO: a nonempty nested gap scope still uses `source_id`. | Treat this as a component foundation, not full integration: add the recursively closed core receipt adapter/golden, round-trip tests for every evidence variant, full orphan/reference verification, scene/export crash cases, and the common walking path. |
| 4 | store -> core -> glass | Glass now has exclusive mode DTOs, full scoped `AsOfVector`, strict nested schemas, and golden digest `sha256:8cbd045cbf22dd4c908ef84ecc14840d71f846b672c0311f65a2a48cdf8d69ab`; core asserts those exact TypeScript bytes and watermark/reference invariants from Rust. Store scene write/read now exists, but its deliberately structural API accepts caller-supplied mode/cutoff/watermarks separately from opaque `view_bytes`. No typed admission adapter currently proves they agree. | Parse/validate `GlassViewV1` in a typed core/contract adapter before the structural store call, prove every duplicated index, make the unverified path internal or explicitly unsafe, and implement mode-explicit core endpoints. Exact inner bytes are authority; store/replay them unchanged. |
| 5 | semantic command | Glass now emits a closed scene/view-bound, evidence-only command union, derives full-command and payload digests, validates a closure-rich receipt, and implements retry/compensation UI behavior. Its current sink is still an in-browser fixture. Store atomically commits scene plus command with fixed SQL `observe_only`/`evidence_only` and idempotency, but still accepts any kind and opaque JSON payload, allows a persistent command with no scene, does not require a view digest, and returns a weaker receipt. | Implement the duplicate-safe core wire parser and adapter to the exact section 6 contract, require the referenced stored scene/view digest, and derive the strong receipt from durable readback. Mirror the allowlist at the trust boundary and structurally reject economic fields before the store call. |
| 6 | accounting/math -> projection | Atomic/rational accounting, episode/epoch logic, exact Pump/PumpSwap quote kernels, and DLMM bin/position/action math now exist with typed refusals and provenance-bearing fixtures. No evidence adapter or versioned projection DTO joins them to store/core/glass; pure quote math is not evidence that a route was executable. Glass mock SOL totals are therefore invented display data. | Add the evidence-backed accounting projection DTO with asset IDs, atoms/ratios, reconciliation, evidence/as-of, episode and inventory epoch. Admit mark/quote/liquidation artifacts separately with exact observed state, size, route, validity, and refusal; omit executable value until that closure exists. |
| 7 | store -> Parquet -> analysis | Migration `0005` and Rust register an immutable `export_snapshot`, exact manifest bytes, and all part files in one commit. Python now validates a rich closed manifest with full as-of/producer/scene lineage, qualified digests, composite provenance, `(scene_id,episode_id,sample_index)` chart keys, exact base/quote atoms, real gap IDs, explicit decision/choice/episode/gesture/interview/outcome tables, and truthful empty optional relations. Its checked-in fixture is still generated privately by Python, while the structural store transaction verifies files/drafts but no typed adapter proves that manifest names the exact registered closure. | Implement the typed store-export/analysis-manifest adapter, make it the non-bypassable path to registration, and generate this same fixture contract from a store cutoff. Reconcile every manifest field, part, digest, row count, bound, and coverage ID to readback before commit. |
| 8 | whole repo | The locked Rust suite passes 111 tests and strict Clippy, but no root offline command proves one common fixture across source, store, view, command, export, and analysis. | Make `./scripts/offline-readiness` the only Wave 1 completion signal. Lane-local tests never substitute for it. |

### P1 — required before trusting the first recorded session or analysis result

| Boundary | Duplicate or ambiguous truth | Resolution |
|---|---|---|
| digest types | Rust role types accept any stable string at construction while catalogs/stores separately validate `sha256:`. SQL and Python store bare hex; glass stores qualified text. | Add one shared V1 SHA-256 parser/value type and role wrappers. Public DTOs use `sha256:<64 lowercase hex>`; SQL hash columns contain only the 64-hex payload and adapters strictly strip/restore the prefix. |
| timestamp types | Source adapters have Unix milliseconds, Rust has `UtcTimestamp`, SQL has signed epoch microseconds, glass has strings/`Date`, and Arrow has microsecond UTC. | Use the exact encoding in section 3. Reject rather than round. Adapter-local `UnixMillis` never crosses a durable or public contract. |
| integer ranges | Rust `WireU64`/`CommitSeq` can exceed SQLite's signed integer; JS numbers cannot represent all of either; Arrow `int64` cannot represent all Solana `u64` atoms. | JSON uses decimal strings. SQL integer-backed fields are contract-bounded to `0..i64::MAX`; wider atoms remain canonical decimal text. Parquet uses `decimal128(20,0)` for full `u64` and `decimal256(39,0)` or text for full `u128`, not float. |
| assertion values | `AssertionDraft.extension` is `serde_json::Value`; decimal JSON tokens may already be f64-backed and canonicalization cannot restore them. | Canonical assertion V1 recursively forbids JSON numeric tokens. Exact numbers are decimal strings or named rational/atom objects. Raw provider number lexemes remain tagged source data. |
| source identity | `joshi-sources::SourceId` is a closed adapter enum; `joshi_domain::SourceId` is an opaque contract identity; SQL has a source registration. | The enum is adapter-local only. The domain ID names an immutable registered source contract/configuration and is the only ID crossing evidence, store, scene, or export. |
| occurrence identity | IDs are unconstrained strings; source IDs derived only from epoch/sequence can collide after restart; hashes can accidentally be used as occurrences. | Occurrence IDs are generated/derived once under a persistent installation/run namespace and never from payload equality. Their internal shape is opaque. Content identity alone uses SHA-256. Commit order alone establishes local knowledge order. |
| acquisition clocks | `started_at`, acquisition requested/received/persisted clocks, observation timing, and monotonic readings overlap. | Each field keeps one definition: acquisition start/request describe the attempt; observation receipt describes those bytes; persisted/available describe durable and projection gates. One acquisition repeated in a batch must be byte-for-byte identical. Monotonic values compare only within their named clock ID. |
| source event identity | Observations inline links while the batch separately declares source-event natural keys. | The top-level source-event record owns identity/natural key; observation links own relation and ordinal. Store requires every link's declaration in the same or earlier commit and enforces source agreement. |
| in-memory vs durable catalog | `InMemoryCatalog` assigns one commit per item and omits durable batches, cursors, source-event rows, scenes, and exports. | Keep it as a unit-test/fixture seam. It is not a store implementation, API snapshot source, or oracle for durable commit counts. Integration tests use `joshi-store`. |
| source coverage runtime | `CoverageTracker` mutates runtime state and emits `GapClassified`; durable evidence has immutable gap plus later recovery. | Adapter events are translated: open -> `CoverageGap`; classification/recovery -> later `CoverageRecovery`. Reconnect alone never creates recovery. Runtime state is not replay truth. |
| accounting vs glass | Glass exposes decimal SOL totals and “executable” values; accounting owns atomic/rational basis and currently has no output DTO. | Build a separate versioned accounting projection DTO. It carries asset IDs, decimals, atomic strings, exact rational basis, quality, reconciliation, episode and epoch IDs. Glass decimals are labeled display projections; executable quote values require an independent quote assertion. |
| scene choice context | Candidate arrays, ranks, `scene_choice_member`, and attention-filter state can disagree. | The exact view is what was rendered. The scene membership table is a verified index over eligible/surfaced/rendered/viewport/interacted/compared sets, with evidence IDs where claimed. Search/filter state is a semantic command or scene metadata, not inferred later. |
| commands | UI shell actions and stored semantic commands currently have no shared wire contract. Scene reference is optional in store. | V1 persistent commands require the exact displayed scene and view digest. Local ephemeral navigation remains UI state. The server allowlists evidence-only command kinds and rejects all economic-effect fields. |
| projection identity | Domain `AsOfVector.projections` carries name/version; scene watermark also has optional state digest; glass expects a digest. | A projection watermark is exactly `(name, version, state_digest, delivered_through)`. Version identifies code/schema semantics; digest identifies this state. Both are required for a rendered projection. |
| export lineage | SQL has closed commit ranges; Python has one wall-time maximum; neither alone is an as-known vector. | The export manifest contains catalog cutoff, source/chain/projection watermarks, scene/digest when scene-derived, and the exact registered store export snapshot ID. Wall decision time is an additional row gate, not the catalog cutoff. |
| hashes of manifests | Python uses an algorithm-qualified snapshot ID but bare table hashes; Rust uses qualified values; SQL uses bare storage. | Every JSON manifest hash is algorithm-qualified. File/schema/logical digest fields all use the same external representation. Physical SQL strips it only at persistence. |
| JSON canonicalization | Serde field order, Zod parse order, map sorting, unknown-field stripping, locale sorting, and duplicate JSON keys can produce different bytes or unhashed fields. | Closed contracts reject unknown and duplicate keys. Every digest contract declares one encoder: online envelopes use schema-ordered keys; the analysis manifest uses lexicographically sorted closed ASCII keys. Set-like arrays use bytewise identity order. Cross-language goldens pin the result; never call `localeCompare` canonical. Exact witnessed bytes are retained even when semantic canonicalization is also available. |
| source response fidelity | “Exact bytes” can mean transfer bytes, content-decoded bytes, response text, or reserialized JSON. | Every raw observation declares its fidelity boundary and content encoding. Prefer `Response.clone().arrayBuffer()` for companion-visible response-body bytes. A text-only/XHR path is explicitly degraded; it does not claim transfer-byte identity. |

### P2 — can follow the first offline walking path, but must remain explicit

- A current/live glass view is a current local projection, not a witnessed scene. It may be served
  under `knowledge_cutoff` with the current cutoff; do not overload `witnessed` or pretend fixture
  time is live market time.
- A screenshot is supporting rendering evidence, not the semantic scene contract. `view_bytes`
  remain replay authority.
- Source health and queue metrics are diagnostics unless separately admitted as observations.
- A Parquet physical digest proves bytes, not semantic equivalence; logical and schema digests are
  independently required.
- Analysis features may use float after exact inputs are frozen and labeled, but ledger, amount,
  quote, fee, and manifest truth never does.
- Provider-normalized values may later become typed assertions after a differential parser test.
  V1 does not need to recognize every social or protocol variant to retain it exactly.
- A Wave 2 remote spool is transport durability, not catalog authority. Its segment ACK cannot mint
  a commit, advance a cursor, close a gap, accept an assertion, or authorize retention deletion;
  segment identity, exact-byte digest, and protection domain remain separate truths.

## 3. Canonical V1 encodings

These are cross-process rules. In-memory types may be narrower and SQL may be more compact only
through checked, reversible adapters.

### 3.1 Time

- JSON wall instants: exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC.
- No offsets, omitted fractions, fewer/more than six fraction digits, leap through rounding, or
  local time. An input with sub-microsecond information is rejected, not truncated.
- SQLite: signed Unix epoch microseconds, checked on both conversion directions.
- Arrow/Parquet: `timestamp[us, tz=UTC]`.
- Source-native time that is not already a justified UTC instant remains an opaque retained value
  with authority/precision, or a half-open `ObservationEventTime` interval.
- A source-specific ingress may declare a narrower reversible clock contract. The companion's
  browser clock is exactly RFC 3339 UTC with three fractional digits; its core adapter appends
  `000` and validates the resulting six-digit instant before durable admission. Source-native time
  never silently masquerades as the canonical durable form.
- Monotonic time is an unsigned decimal string plus a clock-domain ID. It never crosses domains or
  substitutes for wall/event/commit order.

### 3.2 Integers, decimals, atoms, and prices

- JSON `u64`, `u128`, commit, slot, ordinal, atom, byte, and monotonic values are canonical unsigned
  decimal strings: `0` or a nonzero digit followed by digits.
- Signed exact integers are `0`, a positive canonical form, or `-` plus a nonzero canonical form;
  `+1`, `01`, and `-0` are invalid.
- A display decimal is a non-exponent base-10 string and must carry its unit. It is not accounting
  truth merely because it is exact text.
- A canonical asset amount is `{assetId, atoms, decimals}`. A canonical exact ratio is
  `{numerator, denominator}` with a positive reduced denominator. A price is either a named ratio
  of base/quote atoms or a value with an explicit quote asset and scale.
- JSON number tokens are allowed only for small closed schema versions and booleans remain
  booleans. Provider JSON numbers are retained as raw bytes and, when extracted, as validated
  `json_number_lexeme` strings.

### 3.3 IDs and digests

- IDs remain typed strings; no caller infers time, source, or truth from their textual shape.
- Occurrence IDs and semantic IDs are never content hashes. Equal bytes in different occurrences
  keep distinct acquisition/observation IDs.
- External digests are exactly `sha256:<64 lowercase hexadecimal digits>`.
- SQL digest columns contain the 64 digits only. The store accepts only the `sha256:` algorithm in
  V1 and performs an exact strip/restore; uppercase, other algorithms, and missing prefixes fail.
- Content hashes cover exact bytes. Semantic value/batch hashes cover a named versioned digest
  material contract. A digest never silently changes its preimage when a schema evolves.

### 3.4 Closed and open schemas

- Envelope, snapshot, command, receipt, and manifest versions are closed: reject unknown keys,
  duplicate JSON keys, invalid enum values, and over-bound arrays/strings before mutation.
- Provider variants and evidence discriminators are open at the source edge. Unknown values retain
  exact raw evidence and an explicit unknown recognition state.
- Collections whose order has no meaning are bytewise sorted by their typed canonical identity and
  reject duplicates before digesting. Collections whose order is evidence—record ordinal, event
  order, command order, sample order—retain and validate that order.

## 4. Canonical durable evidence and admission contracts

### 4.1 `DurableIngestBatchV1`

The Rust `joshi_evidence::DurableIngestBatch` is the semantic source of truth after adapter
admission. Its public contract name is `joshi.durable_ingest_batch.v1`. It contains:

```text
contract_version = "joshi.durable_ingest_batch.v1"
batch_id          = stable idempotency occurrence ID
expected_digest   = sha256 of DurableIngestDigestMaterialV1
observations      = ObservationDraft[]
source_events     = SourceEventRecord[]
assertions        = AssertionDraft[]
coverage_windows  = CoverageWindow[]
coverage_gaps     = CoverageGap[]
coverage_recoveries = CoverageRecovery[]
cursor_advances   = CursorAdvance[]
```

`DurableIngestDigestMaterialV1` contains the contract version and every logical field above except
`expected_digest`. Observation payloads are base64 of exact bytes. It excludes commit-attempt wall
and monotonic clocks, writer build, CAS path, compression, and inline/external placement. Set-like
vectors are sorted by typed ID; observation acquisition ordinals and instruction paths retain
order. Assertion JSON contains no numeric tokens and has schema-ordered/bytewise-sorted objects.

An assertion's `value_digest` is not an unchecked producer label. Its V1 preimage is the canonical
UTF-8 JSON encoding of this exact schema-ordered object:

```json
{
  "contract": "joshi.assertion_value.v1",
  "assertion_kind": {"discriminator": "...", "recognition": "known"},
  "producer": "...",
  "producer_version": "...",
  "extension": {}
}
```

`batchDigest` is not a hash of the containing HTTP bytes and is never compared to the durable
batch digest. Its named preimage is `PumpCompanionBatchDigestMaterialV1`, the schema-ordered object
`(contract, schemaVersion, batchId, producer, acquisitions, gaps)` with `batchDigest` omitted,
encoded as compact UTF-8 JSON. Nested objects follow the source schema's order; acquisition and gap
arrays retain captured order. Core performs duplicate-aware strict parsing, reconstructs that exact
material, hashes it, and compares the submitted ingress digest before mapping anything.

`extension` is the assertion extension object after recursive no-number and canonical-key
validation. Semantic key, evidence, availability, and status are deliberately outside the value
digest; producer identity/version are inside because two decoder contracts need not assign the same
meaning to equal JSON. The enclosing durable batch binds every excluded field. The store now
recomputes this digest and rejects a mismatch before CAS or SQL mutation.

The store additionally binds per-observation retention/content-encoding policy and gap severity in
the landed versioned `joshi.store.admission.v1` digest returned by the receipt. The same `batch_id`
with changed logical digest or changed security policy is an identity conflict, never “idempotent.”

Admission is all-or-nothing. Validation before mutation includes:

- byte/record bounds and exact base64 length;
- V1 digest and batch-ID conflict;
- unique IDs and ordinals;
- acquisition equality across observations;
- every source registration and event/link relation;
- evidence causality and supersession key;
- recursive no-number assertion value validation;
- exact/bounded/absent time-state validity;
- tagged coverage bounds and recovery evidence;
- cursor evidence, acquisition, scope, predecessor, and same-commit closure; and
- supported physical retention/encoding policy.

All validations that do not require mutation, including foreign identities and SQL discriminator
closure, run before installing private CAS bytes. CAS bytes are then written, file-synced,
atomically installed, directory-synced, and reverified before the SQLite transaction references
them. An unavoidable crash can leave an unreferenced artifact, so verification exposes an orphan
inventory and a retention-aware sweeper; a normal invalid request must not. Cursor advancement and
all cited evidence share the same transaction. A response is not success until SQLite commit has
returned and the receipt is built from readback.

### 4.2 Direct provider and Pump API admission

`joshi-sources` already owns the mapping from retained stream frames to shared acquisition,
observation, event-link, and event-time drafts. The new product-API edge has two nested source
contracts: `joshi.pump_api.fetch_outcome.v1` groups one logical request, all attempts, positive
coverage windows, and real gaps; each attempt is `joshi.pump_api.acquisition.v1`. The latter carries a restart-reserved
acquisition ID, request-group/attempt ordinal, immutable route-catalog version, closed GET route,
access/stability/session classes, safe locator and request fingerprint, status/safe headers,
six-digit wall plus monotonic clocks, and one closed body state:

- `exact`: response-body fidelity boundary, media type, base64 exact bytes, length, and blob ID;
- `truncated`: exact retained prefix, lower-bound received length, limit, and prefix blob ID; or
- `missing`: typed reason and no invented bytes.

The route catalog is part of the trust boundary: only audited origins, path placeholders, query
keys, and `GET` are expressible; collection-disabled reconnaissance routes fail before network
I/O. A local session provider may supply read-session material but never wallet signing material,
and no secret enters the fingerprint's public diagnostic representation. Each retry is a distinct
acquisition occurrence under one request group. A retry success does not erase an earlier failed
attempt or real loss.

The missing core adapter validates the source contract/catalog, exact body base64/hash/length,
clock and ID closure, then maps every attempt to an observation of that attempt. Exact bodies may
support provider-derived assertions only through a promoted schema fingerprint; truncated/missing
bodies preserve their explicit fidelity and cannot. Access/session class selects protection and
retention outside the content digest; authenticated profile/social bytes remain private even when
an equal body is public elsewhere. Source-native windows/gaps become durable
coverage evidence with the exact route/request/order/cursor/page-size scope. Core acknowledges the
source `IdentityStore` reservation only after a matching durable receipt closes that acquisition
and its submitted window/gap identities;
an ambiguous or partial sink response retries the same durable identity. `FetchOutcome` is not a
durable batch; neither its request-group identity nor request fingerprint is substituted for the
durable/admission digests.

### 4.3 Pump companion admission

The browser does not construct trusted provider assertions or SQL rows. Its closed source-specific
request is `joshi.pump_companion.capture_batch` version 1. The source-edge envelope is mapped by
core into the durable evidence contract; it is not itself a `DurableIngestBatch`. Each batch has
this outer shape, with acquisitions and gaps kept in captured order:

This contract remains useful for authenticated reconnaissance, parity/drift checks, and fallback;
it is not the intended always-on production source. A future direct Pump adapter must enter through
the same durable evidence boundary with its own trust and coverage claims, not impersonate the
companion contract.

```json
{
  "contract": "joshi.pump_companion.capture_batch",
  "schemaVersion": 1,
  "batchId": "opaque-occurrence-id",
  "batchDigest": "sha256:...",
  "producer": {
    "adapter": "pump-companion",
    "adapterVersion": "0.1.0",
    "installationId": "opaque-local-installation",
    "extensionSessionId": "opaque-worker-session"
  },
  "acquisitions": [],
  "gaps": []
}
```

One acquisition is one captured response occurrence, not one normalized record. It contains:

- `acquisitionId`, `pageInstanceId`, and decimal-string page sequence;
- allowlisted route ID, origin, path without credentials, and an algorithm-qualified fingerprint
  of the complete redacted logical request (including pagination/filter/cursor semantics);
- captured/received browser-wall instants under the explicit
  `browser-wall-rfc3339-utc-milliseconds.v1` source clock contract, plus the observable-byte
  fidelity boundary;
- response blob ID, byte length, media type, parse disposition, source/emitted/omitted record
  counts, and a response-boundary discriminator;
- record count and ordered record ordinals; and
- optional normalized fields encoded as tagged `utf8`, `json_number_lexeme`, `bool`, `null`, or
  bounded list values. These are untrusted parser claims derived from the raw observation.

Fidelity is a closed sum:

- `exact-private-response-bytes` includes a bounded base64 `exactPayload` whose digest/length match
  the decoded Fetch response-body bytes and whose retention/protection class is private; or
- `lossy-normalized-attestation` includes no provider body, is explicitly
  `not-admissible-as-exact-observation`, and names the fidelity limitation.

The latter can still become exact durable evidence of the *companion envelope bytes* and therefore
keeps its acquisition occurrence ID, but normalized values remain companion claims. Withholding
provider bytes is not by itself a coverage interval: only an actual read, size, queue, or scope loss
creates a top-level coverage gap.

No cookie, authorization header, Pump credential, authenticated URL, secret query value, or wallet
material is admissible. The source contract owns a reviewed request-redaction/fingerprint function;
dropping an entire query is invalid if it also drops pagination or choice-surface semantics.

A gap names route/origin/path/page instance, a last trustworthy boundary, an upper/first-resumed
boundary when known, detection time, cause, and diagnostic dropped record/byte counts. A queue
overflow that cannot know its upper bound records `unknown`, not a fabricated interval.

The loopback endpoint is pinned to `127.0.0.1`, rejects browser-origin requests outside the
extension's locally paired installation, bounds content length/rate, and accepts no CORS wildcard.
A local pairing token is installation authentication, not a Pump credential. The exact typed batch
and digest are persisted in session storage before send and retried without changing
identity or material; the HTTP serialization is regenerated from that validated batch. The expected
`catalogId` is obtained from the paired loopback service or explicit local configuration; it is not
a universal compile-time catalog identity and a mismatched receipt does not dequeue work.

The adapter recomputes the ingress digest over the canonical source material, then converts the
request to `DurableIngestBatchV1`: exact private response -> provider-body observation; lossy envelope ->
companion-attestation observation; normalized record -> candidate assertion/source-event relation
with matching trust; declared real loss -> coverage gap. The adapter never upgrades
`page-delivered-untrusted` into provider-attested truth. It converts exact source milliseconds to
six-digit durable UTC by appending three zero microsecond digits; any other source-clock form fails.

### 4.4 Store and companion receipts

The store's Rust `DurableReceipt` is the canonical structural result of durable admission. The
public/core adapter exposes it as `joshi.store.ingest_receipt` V1; this closed success body must
agree exactly with the submitted durable batch:

```json
{
  "contract": "joshi.store.ingest_receipt",
  "schemaVersion": 1,
  "catalogId": "local-catalog-id",
  "catalogSchema": "joshi.sqlite.v5",
  "commitSeq": "14",
  "batchId": "opaque-occurrence-id",
  "batchDigest": "sha256:...",
  "storeAdmissionDigest": "sha256:...",
  "status": "accepted",
  "fromCommitSeq": "14",
  "throughCommitSeq": "14",
  "admitted": {
    "acquisitions": "1",
    "rawBlobs": "1",
    "rawBytes": "9876",
    "observations": "1",
    "sourceEvents": "8",
    "assertions": "8",
    "coverageWindows": "0",
    "coverageGaps": "1",
    "coverageRecoveries": "0",
    "cursorAdvances": "0"
  },
  "acquisitionIds": ["..."],
  "gapOutcomes": []
}
```

This must be a dedicated recursively camel-case wire DTO, not an accidental serialization of
nested Rust domain structs. The adapter is still missing: directly serializing the current
structural receipt leaves at least a nested gap scope as `source_id`. Open variants remain
`{discriminator, recognition}` objects. `status` is
`accepted` or `idempotent`. Counts are decimal strings on JSON even if Rust stores native checked
values. Gap outcomes echo `gapId`, full scope, lower/upper tagged boundaries, and `recorded`.
Acquisition and gap arrays use canonical identity order. V1 uses one commit per batch, so the range
endpoints agree; the two-field range keeps the contract honest if batching changes.

The companion must additionally prove that this durable result corresponds to the exact ingress
batch it queued. The loopback endpoint therefore returns a closed
`joshi.pump_companion.ingest_receipt` version 1 adapter body containing:

```text
contract                  = "joshi.pump_companion.ingest_receipt"
schemaVersion             = 1
catalogId                 = paired catalog ID
catalogSchema             = StoreReceipt.catalogSchema
status                    = "accepted" | "idempotent"
ingressBatchId            = submitted companion batch ID
ingressBatchDigest        = submitted companion batch digest
durableBatchId            = StoreReceipt.batchId
durableBatchDigest        = StoreReceipt.batchDigest
storeAdmissionDigest      = StoreReceipt.storeAdmissionDigest
fromCommitSeq/throughCommitSeq = StoreReceipt commit range, decimal strings
acquisitionCount/gapCount = submitted distinct occurrence counts, decimal strings
committedAcquisitionIds   = exact ordered submitted occurrence closure
committedGapIds           = exact ordered submitted real-gap closure
```

The two IDs may be equal under a simple mapping, but neither equality nor digest equality is
assumed. The ingress digest binds the exact browser request material; the durable digest binds the
normalized evidence contract; the admission digest additionally binds storage/privacy/severity
policy. The companion does not predict store `admitted` counts or parse store-internal gap types
because adapter expansion determines that closure. Core verifies that every submitted occurrence
and real gap was durably mapped, then derives this adapter receipt from the store receipt, never
from request claims.

Wrong contract, catalog, either batch ID or digest, ordered submitted IDs, non-JSON 2xx, or a 2xx
before durable commit is a failed delivery. Rejections use a closed problem body and non-2xx
status; there is no partial acceptance. The companion now uses lossless duplicate-aware parsing,
rejects unsafe JSON number tokens and dangerous prototype keys, and only then applies its strict
receipt schema.

## 5. Canonical snapshot contract

The glass lane's repaired shape is the canonical V1 browser contract:

```json
{
  "contract": "joshi.glass.snapshot",
  "schemaVersion": 1,
  "snapshotDigest": "sha256:...",
  "transport": "offline_fixture",
  "recordingAuthority": "read_record_replay_only",
  "view": {
    "contract": "joshi.glass.view",
    "schemaVersion": 1,
    "mode": "witnessed",
    "sceneId": "...",
    "basisSceneId": null,
    "asOf": {
      "catalogCommit": "42",
      "sources": [],
      "chain": null,
      "projections": [],
      "renderedAt": "2026-08-16T18:42:15.000000Z"
    },
    "payload": {
      "sources": [],
      "candidates": [],
      "episodes": [],
      "socialEvents": []
    }
  }
}
```

`snapshotDigest` is SHA-256 of the exact canonical UTF-8 JSON bytes of the inner `view`, whose own
contract/version are therefore hash-bound. The canonical encoder has schema-ordered object keys,
strict ASCII identity/code-unit-sorted set arrays, no insignificant whitespace, no unknown or
duplicate keys, no unsafe JSON numbers, and cross-language golden bytes. The browser's loopback
reader validates bounded raw UTF-8 for duplicate keys before platform parsing, rejects prototype
keys in the parse reviver, then applies strict Zod and the digest check; `.strict()` alone would be
insufficient. Exact stored `scene.view_bytes` are those inner bytes; `view_sha256`/blob ID is their
digest. The HTTP server may wrap them but must not parse and reserialize witnessed bytes into a
different representation.

The checked TypeScript golden is `apps/glass/src/contract/golden.ts`; its V1 digest is
`sha256:8cbd045cbf22dd4c908ef84ecc14840d71f846b672c0311f65a2a48cdf8d69ab`. Core already
parses those exact golden bytes from Rust, asserts the digest, and checks reference and watermark
consistency. The remaining integration test must run the same bytes through scene admission, store
reopen, and witnessed replay.

Modes are exclusive:

- `witnessed`: exact stored bytes actually delivered; `basisSceneId` is null; no later values;
- `knowledge_cutoff`: a named recomputation restricted to an historical catalog cutoff and based
  on one witnessed scene; and
- `retrospective`: a named later recomputation with outcome cutoff and the witnessed basis scene.

Replay switching loads another snapshot. It does not filter a mixed snapshot in the browser. A
value's `knownAt` may remain as provenance but is not the mechanism that makes a witnessed payload
safe.

An as-of source entry is
`(sourceId, deliveredThrough, cursors[], receivedThrough)`. Each scoped cursor is
`(family, subject|null, cursorKind, value, advancedThrough)`; arrays sort by the byte identity
`family + NUL + subject-or-empty + NUL + cursorKind`, reject duplicates, and never select one
source-wide “latest” cursor. `deliveredThrough` comes from represented observations; every cursor
comes only from a valid atomic `CursorAdvance` at or before that delivery; `receivedThrough` comes
only from represented observation receipt time. A projection entry is
`(name, version, stateDigest)` and the relational scene watermark also records its delivery commit.
Chain slot/finality remains a separate clock.

At scene admission, a typed core/contract adapter parses the strict inner view and proves all of the
following before it can construct the structural store draft:

- contract/version, mode, scene/basis IDs, render time, and catalog cutoff equal scene columns;
- witnessed/knowledge watermarks do not exceed knowledge cutoff; retrospective watermarks do not
  exceed outcome cutoff;
- every projection/source watermark agrees with relational indexes;
- the byte digest equals the view blob and scene digest; and
- choice-member indexes are a subset/equivalent of the exact payload under their set-kind contract.

The browser's V1 loopback request is mode-explicit and already fixed in its client contract:

```text
GET /api/v1/glass/snapshot?mode=witnessed
GET /api/v1/glass/snapshot?mode=knowledge_cutoff&basisSceneId={witnessed_scene_id}
GET /api/v1/glass/snapshot?mode=retrospective&basisSceneId={witnessed_scene_id}
```

The witnessed form resolves the current local projection and persists/delivers its scene before a
command can refer to it. The other forms compute and persist distinct views from the named
witnessed basis; the response chooses and declares its exact catalog/outcome cutoff in `asOf` and
never substitutes a different basis. Exact historical byte retrieval additionally uses
`GET /api/v1/glass/scenes/{sceneId}` and returns the stored witnessed snapshot, not a recomputation.

## 6. Canonical evidence-only command contract

Only semantic marks cross the API. Search focus, selection movement, replay lens choice, palette
open/close, and density are ephemeral UI state unless explicitly promoted to a versioned research
gesture.

```json
{
  "contract": "joshi.operator.command",
  "schemaVersion": 1,
  "commandId": "opaque-occurrence-id",
  "idempotencyKey": "opaque-client-retry-id",
  "clientSessionId": "opaque-session-id",
  "clientCommandSeq": "7",
  "scene": {
    "sceneId": "...",
    "viewDigest": "sha256:..."
  },
  "issuedAt": "2026-08-16T18:42:18.123456Z",
  "clientClock": {"clockId": "...", "monotonicNs": "99123"},
  "commandKind": "record_disposition",
  "subject": {"kind": "candidate", "key": "..."},
  "payload": {},
  "authorityClass": "evidence_only",
  "effectCeiling": "observe_only"
}
```

The request deliberately contains neither a caller-asserted full-command digest nor a payload
digest. The receiver parses bounded duplicate-safe JSON through the same closed union, emits the
schema-ordered compact UTF-8 form, and derives both. `commandDigest` is SHA-256 of those exact
canonical `joshi.operator.command` V1 bytes, including the scene, kind, subject, payload, client
sequence and client clocks. `commandPayloadDigest` is SHA-256 of the canonical strict kind payload.
This avoids two unchecked duplicate truths while still letting the durable receipt close both.
The server retains the exact admitted bytes, requires the referenced stored scene and view digest,
and uses the full digest for both command-ID and idempotency-key conflict checks. An identical retry
returns the original receipt; any changed semantic field conflicts.

The cross-language reference is `apps/glass/src/operator/golden.ts`: its strict 243-byte payload
hashes to `sha256:11e7520b23cd385313fbdec6c5854614988ba4cdfadbe1958ca2078915233fa7`, and its strict
808-byte full command hashes to
`sha256:7b27c7c0ceaee821a45b289c4694ced31d9a3861f1c59044335fd917a3abc531`. Core must assert those
exact bytes and both digests before its endpoint is canonical.

The exact V1 kind allowlist is `record_focus`, `nominate_candidate`, `request_hot_scope`,
`record_disposition`, `record_crackle_family`, `record_gesture`, `record_annotation`,
`record_choice_set`, `record_post_action_report`, `link_interview`, and `compensate_command`.
`request_hot_scope` records operator intent; it does not assert that a planner widened collection.
`record_post_action_report` records a report and never implies a trade. Compensation is append-only
and names the prior command rather than mutating it. Disposition, crackle-family, gesture, note, and
UI-label values may be bounded open strings only inside their strict kind payload. Every payload
includes a versioned UI label/context; optional confidence is integer parts-per-million text rather
than a float. Choice sets are explicitly typed, unique, and canonically ordered.

Chart anchors are semantic scene coordinates: a strict time, sample point, or ordered sample range,
never pixels. A point should carry `sampleId` and its instant; a free `priceSol` duplicate is not
canonical because it can disagree with the sample and has no explicit base/quote contract. The
sample identity resolves the exact value under the referenced scene. Names like buy/sell/quote may
occur only as operator language inside a note/disposition. No payload has quantity-to-submit,
slippage, priority fee, transaction, signer, wallet instruction, submit, cancel-order, or
rebroadcast fields. Command facts may support a later assertion but are never inferred fills or
landed wallet effects.

The successful response is exactly:

```json
{
  "contract": "joshi.store.command_receipt",
  "schemaVersion": 1,
  "catalogId": "local-catalog-id",
  "catalogSchema": "joshi.sqlite.v5",
  "batchId": "opaque-store-batch-id",
  "commandId": "opaque-occurrence-id",
  "commandPayloadDigest": "sha256:...",
  "commandDigest": "sha256:...",
  "scene": {"sceneId": "...", "viewDigest": "sha256:..."},
  "commitSeq": "43",
  "status": "accepted"
}
```

It is returned only after durable commit/readback. The browser applies the same bounded,
duplicate-key/prototype-safe receipt parsing as the snapshot path and verifies both derived digests
and the exact scene reference before marking the journal entry committed. At review close this
browser contract, fixture sink, and adversarial client/contract tests have landed; the
duplicate-safe core endpoint and store adapter remain required.

## 7. Canonical analysis export contract

### 7.1 Store topology

One immutable `ExportSnapshot` owns one final manifest and one or more immutable parts. Migration
`0005` has landed the parent and part-closure tables, and `SqliteStore::register_export_snapshot`
now installs all files and registers them in one commit. Before this is the canonical boundary, a
typed core/analysis admission adapter must parse the exact manifest bytes, prove they describe that
same transaction closure, and be the only normal path to the structural store call. The parent
records:

- `snapshot_id`, manifest contract/version, exact manifest path/blob/digest/length;
- producer build, projection name/version/state digest;
- closed catalog input range and full as-of vector;
- optional source scene ID and exact view digest;
- creation commit/time, retention class, and immutable generation; and
- part count and total rows/bytes.

Write protocol: generate each Parquet temp file -> sync -> atomic rename -> sync directory -> hash
readback -> build final manifest from readback facts -> install/sync/hash manifest -> one SQLite
transaction inserts snapshot, parts, and export commit -> return receipt. A crash before SQL leaves
unreferenced reclaimable artifacts, never a referenced missing file. A crash after SQL leaves a
closed, fully installed set.

### 7.2 `ExportSnapshotManifestV1`

The Python consumer accepts exactly this semantic shape (snake_case is retained for the analysis
file contract):

```json
{
  "manifest_version": "joshi.analysis.snapshot/v1",
  "snapshot_id": "sha256:...",
  "created_at": "2026-08-16T15:00:00.000000Z",
  "producer": {
    "build": "...",
    "projection_name": "chart_samples",
    "projection_version": "1",
    "projection_state_digest": "sha256:..."
  },
  "catalog": {
    "catalog_id": "...",
    "catalog_schema": "...",
    "from_commit_seq": "1",
    "through_commit_seq": "42",
    "as_of": {}
  },
  "scene": {"scene_id": "...", "mode": "witnessed", "view_digest": "sha256:..."},
  "knowledge_mode": "as_known",
  "maximum_decision_available_at": "2026-08-16T14:05:00.000000Z",
  "tables": []
}
```

`snapshot_id` hashes the versioned canonical manifest preimage excluding only `snapshot_id`.
Every table entry contains name, path, schema ID and descriptor, qualified schema/physical/logical
digests, byte and row counts, ordered primary key, commit/event/chain bounds where applicable, and
coverage summary with exact window/gap IDs. The store's export-snapshot row must name the same
snapshot and exact manifest-byte digest; the Python validator verifies both relationships before
reading a table.

For `chart_samples/v1`:

- primary key is `(scene_id, episode_id, sample_index)` unless a separately named series ID is
  introduced;
- scene ID, scene mode, view digest, episode ID, mint/asset ID, decision cutoff, projection
  version, source assertion ID, and optional coverage gap ID are explicit;
- event/observed/available/decision clocks are microsecond UTC and checked in order;
- a represented gap row has null measured values and a non-null gap ID; silence never becomes zero;
- prices identify base/quote assets and exact scale/ratio; volumes use full-width unsigned atom
  representation; and
- the manifest coverage claim is recomputed from rows and reconciled to exported durable gaps.

The analysis run manifest then binds the input snapshot ID/manifest digest, exact job contract and
version, configuration, code/dependency lock identity, output schema/digests, and deterministic
result ID. It cannot overwrite either the export or a prior run.

## 8. Store/core/glass/accounting compatibility

The core is an orchestrator and contract adapter, not another truth store. The integrated read path
is:

1. open `joshi-store` read-only at explicit catalog cutoff;
2. query effective assertions by semantic key under supersession and valid-time rules;
3. run named pure projections, including accounting only from finalized wallet-effect assertions;
4. emit a projection state digest and full watermarks;
5. construct one strict `GlassViewV1`, validate exact numbers/units/coverage, encode/digest it;
6. persist the scene bytes/indexes before or atomically with the first command referring to it;
7. serve those exact bytes for witnessed replay; and
8. generate cutoff/retrospective views as new scenes with the witnessed basis ID.

`CatalogSnapshot` and its fixture query remain useful tests of acquisition/observation/blob
identity, but they do not implement this path. Core must not hold an independent mutable catalog
beside SQLite or give a memory snapshot and durable scene the same contract name.

The first accounting bridge is deliberately narrow: evidence-backed finalized before/after wallet
snapshots -> `FinalizedWalletEffect` -> exact accounting/episode projector -> versioned projection
DTO. Unknown classification and residuals are rendered, not dropped. Display SOL converts atoms
only with an explicit asset-decimals contract. `executableLiquidation` is absent until an
independently evidenced quote projector exists.

That DTO is a projection artifact, never `serde` over mutable accounting internals. Its envelope
contains `contract`, `version`, `calculatorBuild`, `projectionId`, optional
`supersedesProjectionId`, canonical request/result digests, and an input closure of catalog commit,
chain slot/finality, controlled-domain ID, and exact observation IDs. Each asset names `assetId`,
mint, token program, and decimals together with the observation that established those decimals.
Balances and lots use atom strings; basis and allocation use reduced rationals. Every result carries
finalized/provisional status, basis quality and known component, and a signed wallet-versus-lot
reconciliation residual. Missing, refused, and unknown are typed states, never overloaded zero or
null.

Episode and inventory-epoch attribution is explicitly non-ledger interpretation. Capital recovery
is its own fact, not PnL. Marks, executable quotes, and liquidation estimates are separate tagged
artifacts with size, route, state, evidence, and expiry; none is copied into landed accounting.
Corrections append a new projection naming the superseded projection ID. Glass formats these facts
locally and never sends a display decimal back as a financial input.

## 9. No-authority dependency closure

At review time the normal Rust workspace graph and both JavaScript lockfiles contained no Solana
SDK, Anchor, wallet adapter, keypair, signing, or transaction package. That is necessary but not
sufficient. The integrated gate must also prove:

- `joshi-domain`, `joshi-evidence`, `joshi-store`, `joshi-accounting`, core query, glass, and
  analysis have no provider credential or outbound-market dependency;
- `joshi-market-math` and `joshi-liquidity` remain pure, exact, network-free calculators; a quote
  result is a typed projection/refusal and never an instruction or authorization;
- `joshi-sources` contains only allowlisted read RPC/subscription methods and its generic HTTP/WS
  mechanisms cannot express transaction submission through public APIs;
- `joshi-pump-api` exposes only its closed, audited logical GET catalog, refuses redirects, and
  cannot accept an arbitrary method, origin, path, query key, or request body even when a local
  session broker supplies read-session material;
- the companion manifest has only Pump and pinned loopback host permissions, no wallet provider,
  webRequest credential interception, arbitrary host, or remote-code capability;
- the local core exposes only snapshot, evidence admission, semantic command, export, health, and
  static-asset routes—no proxy, arbitrary URL, transaction, signing, or wallet route;
- outbox workers have only projection/export/thumbnail/analysis handlers and no network economic
  handler; and
- tests run with dummy/absent credential paths and an outbound-network deny harness.

This gate says only that Wave 1 cannot execute. It is not a claim that later execution is safe.
Any future signer remains a separately authorized process and protocol.

## 10. One root offline readiness command

The sole Wave 1 integration signal should be run from repository root:

```sh
./scripts/offline-readiness
```

The script must set offline/network-deny modes, create one explicit temporary workspace, clean it
on exit, and fail on the first discrepancy. It performs, in order:

1. locked Rust format check, build, unit/integration tests, Clippy `-D warnings`, and rustdoc for
   `--workspace --all-targets`;
2. the SQL migration checksum/tape invariant suite through linked `joshi-store`, not only the
   shell SQLite runner;
3. locked/offline glass install, typecheck, tests, build, and accessibility assertions;
4. locked/offline companion lint, typecheck, tests, mock replay, builds, and manifest audit;
5. locked/offline analysis sync, Ruff, Pytest, fixture validation, and deterministic run;
6. the integrated Rust command below over a fresh catalog/CAS/export directory; and
7. a dependency/route/manifest capability audit for the no-authority closure above.

The integration executable invoked by the script is one command, not shell-authored business
logic:

```sh
cargo run --locked -p joshi-core -- offline-readiness \
  --fixture fixtures/integration/walking_path_v1 \
  --state "$JOSHI_READINESS_STATE"
```

It must ingest through `SqliteStore`, compare the durable receipt, replay a witnessed cutoff with a
gap and later correction, construct/store/read the exact glass view, submit/retry one semantic
mark, export real Parquet plus final manifest, invoke/verify one analysis result, reopen the store,
and reproduce the witnessed view and manifest digests. It emits one machine-readable readiness
manifest listing tool/contract versions and artifact digests. No step contacts a network, reads a
credential, uses a user catalog, or writes outside the temporary directory.

The command fails if any lane only validates its private fixture. Passing requires one common
integration fixture and exact IDs/digests across every hop.

## 11. Definition of Wave 1 integrated

Wave 1 is integrated only when `./scripts/offline-readiness` passes from a clean checkout with the
declared locked toolchains and dependency cache (or a repository-vendored equivalent), and
the readiness manifest demonstrates all of the following with one fixture lineage:

- exact source/companion bytes and explicit coverage enter one durable batch;
- the store reopens with a matching receipt and correction/gap/cursor semantics;
- one exact as-known projection becomes one immutable witnessed glass scene;
- one semantic operator command is durably idempotent and evidence-only;
- one registered, manifested Parquet snapshot is validated and analyzed reproducibly; and
- no component in that dependency and route closure can construct, sign, submit, or rebroadcast a
  transaction.

Until then, the honest label is **strong components awaiting contract integration**, not a failed
project and not an integrated cockpit.

## 12. Ordered integration patch set

### Patch 1 — close the remaining wire primitive gaps (partially landed)

- Keep the landed canonical microsecond UTC `UtcTimestamp` and glass encodings; normalize the
  companion/core edge to the same wire form.
- Add shared strict SHA-256 parsing/role wrappers and SQL strip/restore helpers.
- Finish durable integer range adapters, companion full-`u64` checks, and duplicate-aware closed
  JSON parsing at every untrusted HTTP edge.
- Add cross-language primitive goldens: timestamps, max widths, `>2^53`, hash prefixes, Unicode or
  ASCII ID policy, unknown/duplicate keys, and number lexemes.

### Patch 2 — close evidence/SQL integrity after migration `0005` (partially landed)

- Keep the landed source events, variants, tagged coverage boundaries, recovery evidence,
  acquisition clocks, instruction path, protection-domain sidecars/disposal, and export-snapshot
  schema.
- Keep the landed `AssertionValueDigestMaterialV1` recomputation and relation-sidecar commit
  closure; extend full verification over canonical boundary JSON and every artifact reference.
- Finish golden tests for durable/admission digests and protection-domain semantics.
- Keep descriptive acquisition cursors out of authoritative watermarks.

### Patch 3 — finish the one-writer store (ingest foundation landed)

- Keep the landed writer lease, source registration, bounded atomic ingest, protection-domain CAS,
  exact receipt, scoped cursor query, verification, backup, and reopen behavior.
- Keep the landed SQL-semantic preflight, scene/command transaction/replay bytes, and
  export-snapshot parent/all-files transaction; put contract-aware glass/command/manifest parsing
  in typed admission adapters, make raw structural calls non-bypassable, and add orphan accounting.
- Test interruption at every file/SQLite boundary and same-ID/different-body/policy conflicts.
- Keep `InMemoryCatalog` explicitly fixture-only.

### Patch 4 — join repaired source edges to admission (component repairs landed)

- Keep the landed raw-source-frame transport envelope, checked event-time interval, closed-GET
  Pump API attempt/body contracts, companion byte capture, lossless number lexemes, restart-safe
  acquisition identity, scoped gaps, and immutable retry queues.
- Implement the stream evidence batcher/durable sink, the Pump API and companion core adapters,
  plus the companion loopback pairing/catalog handshake, source-edge-to-durable digest mapping,
  durable acknowledgement, and two-digest receipt adapter from section 4.4.
- Golden-test both exact-private and lossy-attestation paths without upgrading trust.

### Patch 5 — persist glass scenes and commands (browser contract landed)

- Keep the landed immutable one-mode DTOs, separate replay loads, strict/duplicate-safe parsing,
  deterministic ordering, scoped cursors, and Rust/TypeScript byte/digest golden.
- Implement store-backed core snapshot endpoints and exact witnessed-byte serving.
- Implement the scene-bound, evidence-only command/receipt with idempotent retry.

### Patch 6 — add accounting projection DTO

- Keep the landed exact accounting, Pump/PumpSwap, and DLMM math/refusal kernels; build
  evidence-to-finalized-wallet/state/quote projection adapters rather than calling pure math
  executable evidence.
- Emit atomic/rational unit-bearing accounting facts, reconciliation, episode, and inventory epoch
  state under a named version/build/digest/as-of envelope.
- Replace invented glass monetary fields with labeled projection/display values; leave executable
  quotes null/absent until separately evidenced.

### Patch 7 — join store exports to analysis

- Keep the landed export-snapshot schema/all-files registration and the landed Python manifest,
  composite provenance, chart-series key, exact units/widths, scene/view lineage, real gaps, and
  truthful optional-table contracts.
- Add an exact typed manifest reconciliation adapter against every registered part and lineage
  field, and make the raw structural registration path non-bypassable.
- Generate real Parquet from store cutoff, validate with PyArrow and DuckDB, and bind the Python run
  to the registered snapshot/manifest.

### Patch 8 — add the root readiness path

- Add one shared integration fixture and `joshi-core offline-readiness`.
- Add `./scripts/offline-readiness`, locked offline installs/checks, network denial, no-authority
  dependency/route audit, and machine-readable result manifest.
- Delete no fixtures; label old lane fixtures as component tests and keep them for regression.

## 13. Required tests by boundary

### Evidence/admission

- Same bytes in two occurrences -> two observations, one blob.
- Same batch ID + identical logical and storage policy -> original idempotent receipt.
- Same batch ID + changed byte, field order with semantic change, assertion value, or retention
  policy -> conflict and no mutation.
- Values `9007199254740993`, `u64::MAX`, exponent/long-fraction provider lexemes survive raw capture;
  no normalized exact value passed through JS `number`.
- One acquisition with zero/many observations/events; duplicate ordinals/links rejected.
- Direct API retries retain distinct attempt acquisitions under one request group; a positive
  coverage window is emitted only for the exact successful attempt and is receipt-closed before
  `IdentityStore` acknowledgement.
- Queue overflow and restart produce bounded/unknown scoped gaps; reconnect alone is not recovery.
- Sink refuses empty/non-JSON/mismatched 2xx and dequeues only a matching committed receipt.

### Store/replay

- Every Rust evidence variant round-trips SQL -> Rust exactly, including all boundary tags and
  recovery evidence.
- Exact/bounded/source-missing/not-applicable time cases round-trip; sub-microsecond input fails.
- Cursor watermark appears only after atomic cursor evidence and respects cutoff.
- Multiple observations in one acquisition advance delivered-through to the latest observation,
  not acquisition registration.
- Correction after witnessed cutoff changes retrospective output only.
- Crash matrix proves no referenced-missing CAS/export and no half batch/cursor/scene/command.

### Glass/commands

- Witnessed bytes/digest are byte-identical after store reopen and later evidence ingestion.
- Every later-only field class is absent from witnessed payload; replay switch performs a new load.
- Unknown/duplicate object keys, unsafe numeric tokens, noncanonical times/hashes, unsorted or
  duplicate identity arrays, and cross-language digest mismatch fail closed.
- Calendar-invalid but JavaScript-normalizable instants (day/month zero, February 30/31,
  non-leap February 29, month 13) fail at browser, core, and Python boundaries.
- Stored scene indexes exactly agree with parsed inner view.
- Rust and TypeScript derive the same fixed command and payload digests from one exact golden;
  changed scene/subject/clock/kind/payload changes the full command digest.
- Command retry is idempotent; changed payload conflicts; missing/mismatched scene digest fails.
- Route/schema tests prove no command can express or reach transaction/signing/submission behavior.

### Export/analysis

- Store row -> final manifest -> Parquet -> PyArrow/DuckDB round-trip preserves ID, time, null,
  amount width, schema, row count, logical hash, and physical hash.
- Multi-episode/candidate rows in one scene do not collide.
- Gap rows carry real exported gap IDs and no manufactured measurements.
- Future observation/assertion/command beyond the as-of commit or decision cutoff fails even after
  all hashes are recomputed.
- Missing/swapped/modified part or manifest, wrong catalog/snapshot/scene digest, unsafe path,
  symlink, and unregistered export all fail.
- Repeating the same export/run reproduces semantic IDs and does not overwrite immutable bytes.

### Whole path and authority

- Fresh temporary state completes the common tape path, closes/reopens, and reproduces receipts,
  witnessed snapshot, command, export, and analysis digests.
- Running with empty credential environment and outbound network denied still passes.
- Locked dependency graphs contain no signer, wallet adapter, transaction builder, submission SDK,
  or dynamic remote-code route in any process on the walking path.
