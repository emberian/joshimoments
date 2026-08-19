# C1 raw truth boundary

Status: **LANDED AND GREEN THROUGH STEP 6; NO REQUEST HAS EVER BEEN ISSUED.** Steps 1 to 6 of the
handoff implementation order are implemented, mutation-audited and committed. Step 7, the one
deliberate nonfixture read, remains unauthorized and undone. Nothing in this document is evidence
that a socket has ever opened.

The prior authority chain is described in `docs/implementation/CLAUDE_HANDOFF_2026-08-19.md` and is
inert by construction: it ends at `Supervisor::admit_claimed_wave5_c1_disabled`, which returns a
report-only `DisabledC1RuntimeAdmission` and exposes no executor, transport, reservation, or I/O
entry point.

## What C1 is, and what it is not

C1 is exactly one credential-free HTTPS POST to the official public Solana mainnet JSON-RPC
endpoint, carrying exactly one `getSignaturesForAddress` call for one wallet page, whose exact
response entity bytes are retained once as an opaque raw observation, after which the generation
stops permanently.

C1 is **not** a collector, a cursor, a coverage window, an absence result, a finality fact, a
source-event stream, a chain location, or a provider client. It is a single retained byte string
plus honest accounting of how it was acquired.

The official Solana cluster page, re-verified 2026-08-19, names `https://api.mainnet.solana.com` as
the public mainnet endpoint, states the public endpoints "are not intended for production
applications", and publishes rate limits of 100 requests per 10 s per IP, 40 requests per 10 s per
IP for a single method, 40 concurrent connections per IP, and 100 MB per 30 s. An earlier design
note used the older `api.mainnet-beta.solana.com`; that host is not what the current page names.

## Layers

| Layer | Home | Status |
| --- | --- | --- |
| Exact activation and one-shot store claim | `joshi-wave5-c1-activation`, `joshi-store::wave5_c1`, migration V23 | landed |
| Disabled report-only admission | `joshi-supervisor::c1_activation` | landed |
| C1 journal event family and supervisor seam | `joshi-supervisor::model`, `joshi-supervisor::supervisor` | landed, unconsumed |
| Physical-size proof | `joshi-supervisor::c1::physical_size` | landed |
| Pure wire contract, no I/O | `joshi-sources::public_solana_c1` | landed |
| Raw evidence adapter | `joshi-supervisor::c1::evidence` | landed |
| C1 state machine and replay | `joshi-supervisor::c1::runtime` | landed |
| Fixed transport | `joshi-supervisor::c1::transport` (crate-private) | landed |
| Local-only adversarial tests | in-crate, private loopback | landed |
| One deliberate nonfixture read | none | **not authorized, not done** |

## Where the authority comes from, and where it does not

`ProviderExecutionModeV1` has exactly one variant, `OfflineFixtureOnly`, and
`joshi-store`'s `validate_run_c1_capacity` requires the durable run configuration to carry
`provider_execution: offline_fixture_only`. That is deliberate and must not be widened: it governs
the C0 `CollectorRuntime`, which never performs provider I/O.

C1 therefore does **not** derive its permission from the run configuration. The chain is:

1. the registered run supplies identity and **budget capacity only** (`validate_run_c1_capacity`
   proves the durable accounting limits cover the activation hard cap and attempt cost);
2. the exact C1 activation document is the post-registration permission statement;
3. the one-shot SQLite claim burns that permission exactly once;
4. binding the burned claim to this journal installation is what a request may cite.

Absence of the claim is deny-live by default. The C1 state machine must not read
`CollectorRuntimeConfigV1`, must not construct a `CollectorRuntime`, and must never present the run
configuration as authorization for a socket.

## Journal family

C1 uses a deliberately separate `JournalEvent` family so C0 replay semantics cannot change
silently. The C0 runtime scanner in `crates/joshi-supervisor/src/runtime.rs` ignores every C1
record through its catch-all arm, and the C1 scanner must ignore every C0 record.

| Event | Meaning |
| --- | --- |
| `C1ActivationBound` | one consumed claim bound to this journal installation, carrying the proven `maximum_response_bytes` and `maximum_segment_bytes` |
| `C1AttemptReserved` | the single fsynced attempt identity |
| `C1RequestPrepared` | the exact request closed: digests only, never a URL, body, header value, or credential |
| `C1IoStarted` | the irreversible boundary; every later failure is terminal |
| `C1RawDurabilityRecorded` | the exact raw page appended to the local spool |
| `C1AttemptAbandoned` | a post-I/O attempt resolved as an explicit durable gap |
| `C1BudgetSettled` | conservative settlement of the one reserved attempt |
| `C1Stopped` | the one-shot generation is closed; no further request may ever issue |

`Supervisor` exposes `reserve_c1`, `drain_one_c1`, `append_c1_event`, `c1_abandon_and_stop`, and
`c1_stop_without_gap` as `pub(crate)` seams. They reuse the identical durability machinery as C0
and differ only in which family they record.

## Ordering rules that must hold

1. The SQLite activation claim commits first. SQLite and the supervisor journal are not atomic.
2. Failure after the claim commits but before `C1ActivationBound` is fsynced permanently consumes
   the activation. Authority is never recreated or refunded.
3. No network I/O may occur before `C1ActivationBound`, `C1AttemptReserved`, `C1RequestPrepared`,
   and `C1IoStarted` are all journal-fsynced, in that order.
4. A crash strictly before `C1IoStarted` may cancel and refund, but only when replay proves I/O did
   not start.
5. Any crash or error at or after `C1IoStarted` is terminal: no retry ever, an explicit gap where
   one can be stated, conservative maximum settlement, and a stopped generation.
6. A segment fsynced before its journal record must be rediscovered idempotently on reopen. It must
   never become a false gap and must never cause a second request.
7. Structural reports and receipts are evidence. They are never authority inputs.

## Physical size

A response body is not the durable cost. The chain is response entity body, then
`RetainedFrameEnvelope` (whose `body: Vec<u8>` carries no serde attribute and is therefore encoded
as a JSON array of integers), then the observation payload, then `DurableIngestBatch` JSON, then the
base64 wrapping inside `EvidenceBatchEntry`, then the `SpoolEntry` JSON, then `encode_segment`.

The discarded formula `response_body_bytes + 16 KiB` is false and must not be resurrected. The
admitted one-page ingress ceiling is derived from measurement in
`joshi-supervisor::c1::physical_size` and must leave the derived physical segment strictly under the
durable ceiling that this path can actually meet. A deliberately small ingress ceiling is the
correct answer if that is the only honest one.

## Raw evidence rules

The retained observation is opaque. It carries no source events, assertions, cursor advances,
coverage windows, coverage gaps, coverage recoveries, chain slot, transaction index, instruction
path, log index, or semantic finality. `ProviderEventTime` is `Missing` with a stated reason: the
public endpoint supplies no trustworthy provider clock for this read.

An empty `result` array means the provider returned no rows for this exact request at this exact
time. It never means the wallet is inactive, that a range is covered, or that anything is absent. A
payload `confirmationStatus` of `finalized` is a retained provider claim, not a JOSHI finality fact.

## Transport rules

The transport lives inside `joshi-supervisor`, consumes the non-cloneable admission by value, and
exposes no generic executor, callback, endpoint argument, arbitrary method, or reusable permit. It
uses a fixed credential-free endpoint, a fixed POST body, fixed id 1, the fixed method, the
finalized commitment constraint, redirects disabled, retries disabled, proxy inheritance disabled, a
fixed safe header set, trusted monotonic and wall clocks, a strict deadline, and a streaming body
bounded by the proven physical ceiling. Errors carry no URL, body, or header value.

## Test rules

Tests never contact a public endpoint. They use a private loopback server or a scripted private
transport reachable only from inside the crate, so no production consumer can see the seam.

Required coverage: exact request bytes and headers, redirect refusal, timeout, missing length,
chunked length, lying length, streaming overflow past the ceiling, wrong status, wrong media type,
duplicate JSON fields, wrong JSON-RPC id, row bound, row order, signature length, provider
`rpcError`, post-I/O gap, conservative maximum settlement, every crash prefix through the ordered
journal, zero retries after reopen, and unchanged C0 replay.

## Independent red-team findings on the committed chain

A read-only red team attacked the five claims the handoff makes about the landed chain. Claims 1
(capability cannot be manufactured), 3 (no I/O or credential access) and 4 (activation bytes cannot
be substituted) survived. Three real defects surfaced:

1. **`PRAGMA fullfsync` is set nowhere in the repo.** SQLite's unix VFS uses plain `fsync(2)` unless
   that pragma is on, and on Darwin `fsync(2)` does not flush the drive write cache. A power loss
   after `claim_wave5_c1_activation_v1` returns but before checkpoint can leave the activation row
   present and the claim row absent, making a burned activation re-claimable. That is precisely the
   refund of authority the crash rules forbid. The asymmetry is sharp: the supervisor journal fsyncs
   *harder* than the store, because Rust's `File::sync_all` uses `F_FULLFSYNC` on Apple targets.
2. **The append-only triggers do not defend against `INSERT OR REPLACE`.** SQLite fires delete
   triggers for REPLACE-deleted rows only when `recursive_triggers` is enabled, which it is not. No
   code path uses REPLACE today, so this is latent, not exploitable.
3. **The one-shot is per activation, not global.** `exact_plan_sha256` is UNIQUE, but the final plan
   embeds the run identity and `commit_wave5_run_registration_v1` has no singleton guard. A second
   run registration with byte-identical configuration and accounting yields different plan bytes, a
   fresh activation, and a fresh burnable claim for the same wallet, template and budget. Nothing
   caps the total. This is documentation today and an economic defect the moment a transport
   consumes a claim.

The global cap belongs in the durable supervisor journal, which is the layer that actually gates
I/O and is per-installation: **the C1 runtime must refuse to open if the journal already contains
any `C1ActivationBound` record.** One C1 read per installation, ever, enforced by replay.

A related overclaim: admission currently leaves no durable trace at all, so after a crash "claim
burned and admitted" is indistinguishable from "claim burned and never admitted". Appending
`C1ActivationBound` is what makes the handoff's phrase "bound to the actual durable supervisor
journal" true rather than aspirational.

## Obligations the physical bound places on other layers

The derived bound holds only for the C1 shape. Two of its preconditions are not self-enforcing:

- **Header budget.** `RawSourceFrame::safe_headers` is an unbounded `Vec<SafeHeader>`. Measured at
  the 256 KiB ingress ceiling, 700 synthetic headers already break the retained-envelope bound and
  1024 break every stage including the physical segment. The transport must filter response headers
  through `joshi_sources::public_solana_c1_safe_headers_are_bounded` (at most four allowlisted
  names, 256 bytes each) before a frame is constructed.
- **Configured ceiling.** A compile-time constant cannot guarantee the runtime configuration. The
  C1 runtime must compare its *actual* configured `SpoolConfig::max_segment_bytes` against
  `C1PhysicalBoundV1::max_segment_bytes()` and refuse to open when it does not fit, before any
  socket can be prepared.

## Residual findings, carried openly

Four adversarial waves ran, each auditing the previous. The last two lanes were rated sound after
90 and about 126 single-guard mutations respectively. What remains is recorded rather than closed:

- Roughly eight minor findings survive, all of the form "this branch is unpinned and the file does
  not say so". None is a live defect. The largest cluster is in `c1::runtime`: the operation-kind
  clause of the plan-shape gate, the settlement-violation escalation, and the restart stop reason.
- The production `C1Transport::open` call is shadowed by the `cfg(test)` loopback branch, so its
  arguments are structurally unexercised by any test. Only a real read would exercise them.
- `MAX_REFUSAL_DATA_BYTES` is the one sanitation constant whose value is not pinned downward; it
  could be narrowed sixteenfold with the suite green.
- `C1PhysicalBoundV1` documents that a future reader must re-run the derivation rather than adding
  a `Deserialize` derive. Nothing enforces that instruction.
- Several guards are genuinely unreachable through the only public path and are documented as
  restated defensively rather than tested into a false green. `admit_claimed_wave5_c1_disabled` is
  the clearest case: five of its six refusals cannot fire, because `ClaimedWave5C1Activation` has
  exactly one constructor and it sets the activation field to the parse of the same bytes the
  accessors return.

One unreproduced test failure is worth recording rather than burying. During a heavily loaded gate
run, `joshi-store`'s `derived_import_preserves_occurrences_and_reverifies_part_after_restart` failed
once. Eighteen subsequent runs passed, including under deliberately comparable concurrent load, and
the failure text was not captured because the gate script grepped only summary lines. The most
plausible mechanism is that `fullfsync`, added in this tranche, makes every SQLite commit
substantially slower on Darwin, and that this test does many commits plus a restart under a 5,000 ms
`busy_timeout`. That mechanism is a hypothesis and was **not** demonstrated. It is not treated as
fixed.

## The one deliberate nonfixture read

Step 7 remains explicitly opt-in and is not authorized by this document. It requires exact
activation, reservation, request closure, I/O start, local durability, settlement, stop, and reopen
evidence, one page only, public and credential-free. A green library path is not a reason to mount a
default application or CLI route.
