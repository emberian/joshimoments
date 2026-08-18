# Implementation lane 07: read-only source adapters

Status: implemented and offline-validated on 2026-08-16. One separately authorized, bounded,
read-only Helius characterization is documented in `docs/implementation/LIVE_PROVIDER_PROBE.md`.
This lane contains no transaction builder, signer, submitter, wallet capability, or browser
scraper.

## Outcome

`crates/joshi-sources` is the reusable acquisition edge for the authenticated Helius HTTP/WS and
PumpPortal data WS access the operator already intends to use. It separates an always-on broad
census from operator/strategy-selected hot scopes, retains exact transport bytes, and reports
health and uncertainty instead of silently turning a disconnect or full queue into complete data.

The component stops at raw evidence and source-control facts:

```text
provider -> reqwest / tokio-tungstenite -> bounded SourceOutput
         -> exact RawSourceFrame -> shared EvidenceDraft -> one durable writer (separate lane)
                     |                    |
                     +-> health/gaps      +-> later normalization, never replacement
```

All code is observe-only. The HTTP method type cannot express `sendTransaction`,
`simulateTransaction`, or `getLatestBlockhash`. The crate has no Solana transaction, keypair,
wallet, signing, or relay dependency.

## Implemented artifacts

| Artifact | Responsibility |
| --- | --- |
| `frame.rs` | Exact bytes, occurrence provenance, transport/direction, and a small safe-header allowlist |
| `config.rs` | Provider configuration, endpoint confinement, startup-only credential-file loading, and redaction |
| `helius.rs` | Allowlisted Solana read RPC, Helius HTTP response capture, standard Solana WS subscriptions, ack/subscription correlation, slot anchors, and rate-limit signals |
| `pumpportal.rs` | One multiplexed PumpPortal session, broad feeds, metered hot-scope commands, open-world frame classification, and authentication/funding health signals |
| `scope.rs` | Typed mint-versus-wallet leases, overlapping reasons, TTL expiration, desired/applied reconciliation, and capacity bounds |
| `websocket.rs` | Mature-library WS runner, bounded control/output queues, ping/inactivity, reconnect/backoff, exact inbound/outbound frames, and failure containment |
| `coverage.rs` | Explicit windows, observed recovery anchors, gaps, recovery state, and honest dispositions |
| `evidence.rs` | Binding to `joshi-domain` / `joshi-evidence`, safe logical locators, explicit event-time intervals, a versioned lossless raw-frame envelope, and zero-to-many source-event identities |
| `fixtures/sources` | Credential-free observed and official-shape golden frames with provenance labels |

`SourceId` in this crate is a closed transport adapter identity plus `Other(String)`. The evidence
adapter maps it to the validated shared-domain `SourceId`; it does not serialize authenticated
origins into the generic tape.

## Broad census and leased hot scopes

Broad census is low-decision acquisition meant to establish the market surface:

- PumpPortal `subscribeNewToken` and `subscribeMigration` share one data socket.
- Helius can subscribe to Pump program logs using standard Solana `logsSubscribe` and may add
  standard account/program/slot subscriptions.

Leased hot scopes are an explicit, bounded allocation of attention:

- `MintTrades(address)` and `AccountTrades(address)` are different key types even though both are
  32-byte base58 Solana addresses.
- Each lease has an identity, opening and expiration time, and a reason. Multiple reasons may lease
  the same key; ending one does not unsubscribe while another remains.
- `ScopeBook` tracks desired and socket-applied sets. It marks a delta applied only after every
  command in the batch is written. A partial write forces reconnect; the new socket resubscribes
  every desired key.
- Metered PumpPortal hot scopes default off and require both an explicit enable flag and an API-key
  file. Capacity, keys per message, and subscription-message rate are locally bounded.

This is not an autonomous selector. The source layer accepts leases from an operator or later
policy lane and makes their acquisition semantics reliable. It does not decide that a coin merits
attention.

## Transport and state machines

The generic WS runner uses `tokio-tungstenite`; it does not implement the WebSocket wire protocol.
Its connection lifecycle is:

```text
starting -> connecting -> connected -> subscribe desired state -> healthy
               ^                                              |
               |                     disconnect / inactivity / write failure
               +--------------- bounded backoff <-------------+
```

Every connection has a new epoch; every exact inbound frame and outbound subscription command has
a sequence number within the runner. On each fresh socket the provider protocol clears applied
state and reconstructs subscriptions. Backoff is exponential, bounded, jittered, and testable with
injected entropy. Pings and inactivity timers are conservative local controls, not claims about
provider availability.

`WebSocketControlHandle` uses a bounded typed queue and acknowledges a control only after its wire
commands have been written. It does not claim the provider accepted the subscription unless a
provider frame says so. PumpPortal subscription messages are paced; the configured ceiling is
validated below the documented provider maximum.

The output handoff is also bounded. `try_send` returns the unwritten item when full or closed. The
runner stops rather than dropping it and returns an `ingress_saturated` exit. Because a saturated
channel may also prevent delivery of the final gap event, the supervisor must persist the returned
exit snapshot and open a downtime gap before restarting. A successful reconnect must never be
reported as proof that the missed interval was recovered.

## Evidence, identity, and cursor invariants

The adapter preserves these distinctions:

1. Exact provider body bytes are retained before interpretation inside
   `joshi.raw_source_frame.v1`. That storage envelope also preserves transport, stream class,
   inbound/outbound direction, original content type, HTTP status, and allowlisted safe headers.
   Receipt/occurrence identity remains in typed observation metadata, so identical envelopes can
   still content-deduplicate. JSON classification is additive and does not reserialize provider
   numbers.
2. Acquisition and observation identities derive from source, a required stable installation/run
   or connection namespace, connection epoch, and sequence—not from payload equality. The namespace
   prevents epoch/sequence reuse after process restart. Equal bytes received twice remain two
   observations and may share one content-addressed blob.
3. One raw frame may allege zero, one, or many source events. `EvidenceContext.source_events` is a
   vector of typed relation/ordinal links; a transaction/log frame is never collapsed into an
   optional scalar event identity.
4. Missing provider event time is explicit. Receipt time is not substituted as event time. Exact
   event time is a checked half-open `[lower, lower + precision_us)` interval; bounded intervals
   require positive precision and `lower < upper`. UTC wire times have exactly six fractional
   digits, so no hidden rounding enters storage.
5. `LogicalSourceLocator` is typed and non-secret. It can name `helius:http:getTransaction` or
   `pumpportal:websocket:new_token`, never an authenticated URL, query string, or header.
6. A WS slot/signature is an observed recovery anchor. `CoverageEvent::CursorObserved` and
   `AcquisitionRecord.source_cursor` are descriptive candidates only.
7. A durable cursor advances only through the data-platform `CursorAdvance`, atomically committed
   with a non-empty exact observation-evidence set and a primary observation from the same
   acquisition. No source event emitted here authorizes that advancement by itself.

The many-to-many event invariant matters for Helius in particular: one transaction or logs frame
can contain multiple Pump instructions/events. When the acquisition layer cannot justify exact
event identities, it emits an empty vector and later normalization appends the event identities and
links. It never invents one scalar transaction event as a substitute for all instructions.

## Coverage and gaps

Coverage is scoped state, not an inference from event arrival. The runtime reports window open,
cursor observed, gap open, recovery start, gap classification, and window close.

- PumpPortal data WS is live-only and exposes no replay cursor in the documented contract. A
  disconnect gap is therefore classified `Unrecoverable` after reconnect, with the interval kept
  in evidence.
- A Helius/Solana WS slot anchors possible HTTP recovery. The runner leaves that gap open. A
  separate recovery orchestrator must use bounded `getSignaturesForAddress`, `getTransaction`, or
  `getBlock` reads, prove what interval it covered, and commit raw recovery evidence before
  classifying the gap recovered or partial.
- Repeated disconnects keep the first gap boundary. Reconnect does not erase the gap.
- `processed`, `confirmed`, and `finalized` are retained as source finality. They are not treated as
  interchangeable, and later chain correction remains possible.

The current crate supplies the read client and coverage state but not the Helius backfill scheduler
or durable recovery commit. Until those exist, Helius gaps remain open rather than receiving a
false `Recovered` label.

## Credentials and safe configuration

Credentials are configured only as file paths. A live adapter reads the file once at startup into
`secrecy::SecretString`; offline parsers and tests do not load it. On Unix the loader rejects a
symlink, non-regular file, empty or oversized content, and any group/other permission bits. Debug
output redacts the value. Serializable configuration contains the path, never the secret.

Credentialed endpoints are confined to Helius `*.helius-rpc.com` and PumpPortal
`pumpportal.fun`/subdomains over TLS. Base URLs containing user info, fragments, or secret-looking
query parameters are rejected. The adapter appends `api-key` only to its private URL immediately
before connection. Transport errors are sanitized because an upstream error object may retain the
authenticated URL.

An illustrative configuration uses paths, not values:

```json
{
  "helius": {
    "http_url": "https://mainnet.helius-rpc.com/",
    "websocket_url": "wss://mainnet.helius-rpc.com/",
    "api_key_file": "/run/secrets/joshi/helius_api_key",
    "request_timeout_ms": 15000,
    "websocket_inactivity_ms": 60000,
    "ingress_capacity": 4096,
    "backoff": {"initial_ms":500,"maximum_ms":30000,"multiplier_milli":2000,"jitter_per_mille":200}
  },
  "pumpportal": {
    "websocket_url": "wss://pumpportal.fun/api/data",
    "api_key_file": "/run/secrets/joshi/pumpportal_api_key",
    "census_new_tokens": true,
    "census_migrations": true,
    "enable_metered_hot_scopes": false,
    "max_hot_keys": 2000,
    "max_keys_per_message": 1000,
    "max_subscription_messages_per_second": 20,
    "websocket_inactivity_ms": 60000,
    "ingress_capacity": 4096,
    "backoff": {"initial_ms":500,"maximum_ms":30000,"multiplier_milli":2000,"jitter_per_mille":200}
  },
  "public_solana": null
}
```

Secret-file location and access are deployment concerns. They must remain outside fixtures,
evidence envelopes, screenshots, logs, browser state, and crash reports.

## Current official provider facts

These are provider/protocol facts checked against primary documentation on 2026-08-16, not
performance promises:

- Helius exposes ordinary Solana JSON-RPC at
  `https://mainnet.helius-rpc.com/?api-key=...` and standard Solana WS at
  `wss://mainnet.helius-rpc.com/?api-key=...`. Its WS guide documents a ten-minute inactivity
  timer and recommends regular pings. HTTP `429` and JSON-RPC `-32005` are rate-limit signals;
  exact HTTP/WS quotas are plan-specific. Sources: [Helius endpoints], [Helius WebSocket
  quickstart], and [Helius rate limits].
- PumpPortal documents one multiplexed connection with subscribe/unsubscribe commands. New-token
  and migration subscriptions are broad feeds; token/account trade subscriptions are metered. It
  documents fewer than 200 subscription messages per second and at most 5,000 addresses in one
  message, warns that excessive connection/message use can be temporarily banned, uses processed
  commitment, and provides no historical Data API. Its published metered price on this date is
  0.01 SOL per 10,000 token/account trade events, with a linked wallet funded by at least 0.02 SOL.
  Sources: [PumpPortal Data API], [PumpPortal FAQ], and [PumpPortal fees].
- Solana WS subscriptions use JSON-RPC request acknowledgements whose numeric subscription ID
  identifies later notifications. Historical recovery uses HTTP methods such as
  `getSignaturesForAddress`, `getTransaction`, and `getBlock`; query boundaries and commitment must
  be explicit. Sources: [Solana WebSocket RPC] and [Solana HTTP RPC].

[Helius endpoints]: https://www.helius.dev/docs/api-reference/endpoints
[Helius WebSocket quickstart]: https://www.helius.dev/docs/rpc/websocket/quickstart
[Helius rate limits]: https://www.helius.dev/docs/billing/rate-limits
[PumpPortal Data API]: https://pumpportal.fun/data-api/bonk-fun-data-api/
[PumpPortal FAQ]: https://pumpportal.fun/FAQ/
[PumpPortal fees]: https://pumpportal.fun/fees/
[Solana WebSocket RPC]: https://solana.com/docs/rpc/websocket
[Solana HTTP RPC]: https://solana.com/docs/rpc/http

### Explicit gaps and provider hypotheses

- PumpPortal provider fields remain open-world. Observed 2026-08 frames lack a provider event-time
  field and replay cursor, but undocumented variants may differ; raw bytes are authoritative.
- Whether every non-metered PumpPortal broad subscription is accepted without a key is not promoted
  as a stable contract. Production intends authenticated access; a no-key configuration is useful
  only for explicit provider conformance or future public modes, never an assumption that metered
  access is free.
- The provider does not expose a trusted remaining-event budget in the documented frames. Local
  event counts are telemetry, not an invoice or wallet-balance oracle.
- Helius plan quotas and historical retention must be discovered from the operator account and a
  read-only conformance run. They must not be hard-coded from marketing tiers.
- Pump social/chat/livestream data is not exposed by this Data API and is outside this lane. No
  scraping or Pump trade-builder endpoint has been added.

## Failure containment

| Adverse case | Required behavior |
| --- | --- |
| Credential file unsafe or endpoint host unexpected | Fail adapter startup before any network access |
| Auth/funding rejection frame | Preserve raw frame; mark health degraded; do not interpret silence as no market events |
| HTTP `429` / RPC `-32005` | Preserve exact response and safe rate-limit headers; emit typed rate signal |
| Malformed or unknown JSON | Preserve exact bytes; classify malformed/unknown; never discard or coerce |
| WS disconnect/inactivity | Open a scoped gap, clear applied subscriptions, back off, reconnect, and resubscribe desired state |
| Partial subscription-command write | Do not mark delta applied; reconnect to reconstruct the full desired set |
| Bounded ingress full | Stop instead of dropping; supervisor records exit/downtime before restart |
| Duplicate exact bytes | Keep distinct acquisitions/observations while content-addressing one blob |
| One frame contains multiple events | Preserve zero-to-many event IDs or defer identities to normalization |
| Recovery incomplete | Classify partial/unknown; never infer complete coverage from a live socket |

## Offline validation

The golden directory distinguishes provenance:

- three PumpPortal shapes came from the compost repository's 2026-08-14 recorder. That recorder
  had parsed and reserialized JSON, so these fixtures validate observed fields/types but do not
  claim original provider whitespace;
- Helius subscription, log notification, and rate-limit shapes are synthetic examples of the
  documented JSON-RPC contract; and
- no fixture contains a credential, authenticated URL, wallet secret, transaction, or builder
  request.

Validation was run from an isolated copy of the repository so this lane did not modify the shared
`Cargo.lock`:

```text
cargo fmt -p joshi-sources -- --check
cargo clippy -p joshi-sources --all-targets -- -D warnings
cargo test -p joshi-sources --all-targets
```

Strict Clippy passed. Tests passed: 23 unit tests and 3 golden integration tests, 26 total, with no
network or credentials. They cover redaction/host confinement, read-method exclusion, exact bytes,
equal-byte occurrence identity, restart-safe identity namespaces, secret-looking fingerprint
rejection, exact event-time intervals, one-frame/many-event identity, broad/hot multiplexing, lease
overlap/reconnect, bounded overflow, rate limits, provider rejection, WS ack correlation, slot
anchors, and honest reconnect gaps.

## Integration handoff and next gate

The runtime supervisor should:

1. construct provider clients/endpoints at startup, when credentials are allowed to be read;
2. give each runner a bounded `SourceOutput` queue and keep its `WebSocketExit`;
3. transform every `SourceOutput::Frame` through `observation_draft`, supplying only justified
   event IDs, event-time absence/presence, finality, and a typed logical locator;
4. commit raw evidence first through the one-writer data-platform boundary, then acknowledge or
   normalize it; and
5. send coverage/gap records to the same durable batch model without mapping
   `CoverageEvent::CursorObserved` or `AcquisitionRecord.source_cursor` directly to a durable
   cursor advance.

The smallest live follow-up is a read-only conformance run behind an explicit operator gate: open
one Helius standard subscription and one PumpPortal broad-census socket, retain exact frames and
subscription controls for a short bounded interval, disconnect deliberately, verify credential
redaction and gap behavior, then use Helius HTTP to attempt a bounded recovery. Metered PumpPortal
hot scopes remain disabled. The run promotes nothing until the durable store can atomically bind
observations, many-to-many event links, gaps, and evidence-backed cursor advances.

Open dependencies are the one-writer durable ingest API, a supervisor that persists runner exits,
and a bounded Helius recovery orchestrator. Those are integration work; they are not hidden inside
this source crate and are not prerequisites for offline replay of the existing fixtures.
