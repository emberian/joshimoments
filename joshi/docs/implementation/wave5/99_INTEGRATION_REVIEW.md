# Wave 5 final adversarial integration review

Status at the 2026-08-18 commit freeze: **not promotable**. No Wave 5 root witness,
nonfixture canary, live-provider claim, product claim, authenticated-private continuity claim,
prospective-forecast claim, or economic capability is qualified.

This is a ceiling ledger, not a test scoreboard. In the tables below, `intrinsic contract` means
that the package can validate or transform caller-provided values; `unverified semantic` means
that useful semantics are present but store/source truth is deliberately unavailable; `durable
offline` means that an exact package-local offline occurrence survives readback/restart. `live` and
`product` require nonfixture evidence and are not attained by any Wave 5 package. A green package
test, a fixture receipt, a public DTO, a syntactically valid digest, or a caller-supplied clock or
commit sequence never raises a ceiling.

## Live seam matrix

| Producer -> consumer | Landed owner/package | What is actually closed | Explicit ceiling | Promotion blocker |
| --- | --- | --- | --- | --- |
| Registered documents -> store | `joshi-admission::wave5` | Strict run and six-document byte closure; read-only authority | **intrinsic contract** | Admission cannot prove a row was committed, read back, or used by a runtime. |
| Run/spool/export/import -> catalog | `joshi-store::wave5` + migration V9 | Private store capabilities; exact run registration; spool/catalog binding; operational records; restricted-artifact CAS/Parquet import and restart reverify | **durable offline** for those rows only | There is no W5 source-fact, surface, memory, retention, epistemic, or Cockpit V2 adapter, and the status view covers only the landed row families. |
| Source plan -> provider call | `joshi-source-registry` | Typed C0/C1/C2 plans, methods, units and bounds | **intrinsic contract** | C1/C2 execution is deliberately refused; registry values are not provider or store evidence. |
| Provider result -> frame | `joshi-sources` | Synthetic C0 is one request/one fixture page, nonempty Frame-only output, zero provider credits | **intrinsic contract** | No admitted C1/C2 provider factory or I/O exists. |
| Reservation -> attempt -> settlement -> spool | `joshi-supervisor` | Append-before-I/O journal, conservative ambiguous-start charging, exact C0 replay-only terminal state, restart reconstruction and local spool | **durable offline**, package-local C0 only | It is not attached to the registered store run or catalog ACK; package tests do not prove the root chain. |
| Registered run -> collector runtime | `apps/collector` | Caller-supplied exact registration/plan/fixture can drive the C0 runtime and local spool | **durable offline**, local C0 only | Collector does not load the registered run from SQLite and does not commit/read back the spool/catalog ACK. This is the first root seam break. |
| Source receipt -> census -> market -> projection -> publication | `joshi-operational-circulation` | Exact-byte and cutoff audit reaches a typed blocked prefix | **intrinsic contract** | It always returns `Blocked`: membership rows are not inspectable, projection does not bind the exact market-state artifact/receipt, and the frozen publication receipt does not bind exact publication bytes. Optional opaque pre-commit capabilities cannot repair post-commit semantics. |
| Store observations -> daily surface | `joshi-surface` | Global task identity, critical-task presence, point-in-time reduction, exact eligible/render/omission and source/subject/field closure; public qualification is fixed unverified | **unverified semantic** | Observations and sessions are caller projections. Open/sample universes can carry caller-selected denominator material; a private store adapter must resolve the exact population, facts, gaps, and lease receipts. |
| Broad manifest -> body/checkpoint/head | `joshi-publication::v2` | Pure strict manifest, field-level coverage/gap checks, exact universe partition, digest cross-binding and adjacent commit-stage model | **unverified semantic** | Commit sequence and all fact/coverage/gap refs are caller values; no atomic store writer/readback/head route exists. The focused tests did not compile at freeze. |
| Cockpit publication -> operator | `apps/glass` | Strict bounded V1 client contracts, stable accepted order, private pending-command/scientific-act transport, same-ID/digest ACK rules, evidence-only UI controls | **intrinsic contract** / fixture UI | Main mounts an operational shell whose one-time exchange and cockpit-index/open routes are not mounted by core; it consumes Cockpit V1 rather than W5 V2. No attached-browser, screen-reader, pointer/touch, or daily-use evidence exists, and the independent DOM suite is red. |
| One-time code -> scoped session | `joshi-pairing` | Pure single-use/rate/expiry/revoke state machine; secret types do not serialize or expose ordinary debug | **intrinsic contract** | Registry/entropy/clock are process-local public adapters and no ordinary core route or durable nonsecret session/revocation ledger is mounted. Core still uses one static file token. Before mounting, bind audited OS entropy, trusted monotonic/restart semantics, exact origin and durable occurrences. |
| Pairing/client -> core routes | `apps/core::service` | Legacy loopback snapshot/operator command routes and fail-closed prospective stubs; static capability file is owner-only and redacted | **durable offline** for legacy scene/operator rows only | No pairing exchange or cockpit publication index/open route; prospective launch/nomination/abstention intentionally return unavailable. The current Glass entry point therefore cannot open an ordinary publication. |
| Inventory -> retention action | `joshi-retention` | Pure typed policy/lifecycle kernel; public construction stays `UnknownInventory`; no destructive API exists | **unverified semantic** | No production verified-inventory constructor, V9 store adapter, filesystem/replica/export/key controller, or physical fault walk. Authenticated continuous social remains unavailable. |
| Scene/act/episode -> research admission | `joshi-scientific-memory` | Separate logical-tick/catalog-sequence types, unverified acts, typed gaps and terminal episode semantics; positive qualification requires an opaque unavailable witness | **unverified semantic** | No store adapter or Glass ACK route. Retrospective reveal must bind a real outcome/reveal occurrence, not merely a hidden replay ID; store integration must also enforce append/record/commit clock order and avoid a competing session protocol. The crate did not compile at freeze. |
| Prospective wrapper -> closure | `joshi-episode-closure` | Exact pure prospective DTO/lineage validation | **intrinsic contract** | Caller-authored receipts are syntactic, not durable. It is not connected to scientific-memory storage or a registered W5 root run. |
| Earlier decisions -> analog/reveal | `analysis/.../analog_memory` | Earlier-only decision records, exact distance/missingness, deterministic tie breaks, complete retrospective outcome partition, and reveal-after-knowledge/maturity checks | **unverified semantic** | Inputs and outcome provenance are caller materialized and not store resolved. The repaired behavior is not a passing witness because two focused tests had stale expected messages at freeze. |
| Claims/submissions -> score/ensemble | `joshi-epistemic-book` | Exact semantic contracts and powerless H3 artifacts; actual score/ensemble builders require durable capability types with private fields and no public constructor | **unverified semantic** | A private store adapter must derive occurrence, frozen evidence, visibility/reveal, adjudication and complete historical support membership. Until then no timely forecast, score, calibration, independence or model usefulness claim exists. |
| Durable progress/resources -> status | `joshi-operational-status` | Bounded read-only adapters, finite metrics, append-only degradation/recovery validation; all public views remain explicitly unverified | **unverified semantic** | `from_store_resolved` is only a name, not authority. Store/core must derive rows and mount an authenticated bounded query; recovery never closes source coverage by itself. |
| Candidate/reference sample -> census decision | `joshi-census-bakeoff` | Exact nonvacuous denominators, finalized reference filtering, explicit gaps/costs, recomputation; pure results cap at `SampleOnly` | **unverified semantic** | Candidate/reference/coverage/decoder/cost attestations need opaque store/source derivation before `CensusQualified`. |
| Mechanics evidence -> claim prerequisites | `joshi-mechanics-capability` | Independent, nontransitive profile rows and explicit refusals; every public row/check is unverified | **unverified semantic** | Add distinct durable simulation-occurrence and settled-attempt receipts before promotion, then resolve every state/quote/fill/liquidation/terminal/publication/calibration ref from store/source owners. |
| Catalog snapshot -> Parquet/CAS/import | `joshi-export`, `joshi-artifact`, store V9 import | Bounded production Snapshot V2 path, Rust readback, Python validator invocation, immutable install, store binding/import reverify for represented relations | **durable offline** | It is not invoked by the W5 root; nonempty W5 source/denominator/hot/surface/memory relations are not all represented, and export/import/backup recovery is absent from the root witness. |
| Research/model output -> acquisition/presentation/action | field/ML/ensemble/shadow-policy lanes | Package-local research only | **unverified semantic** | No model output may influence initial acquisition, ranking, presentation, alerts, hot leases or action affordances. Prospective influence requires a separately registered intervention and evidence. |

No row attains **live** or **product**.

## Hard gate observed at freeze

The representative integration gates are red. They must be rerun from one frozen tree; earlier
focused green runs remain package history, not qualification.

```text
cargo test --workspace --locked --offline
# FAIL: workspace does not compile
# - joshi-scientific-memory: duplicate serde attribute, serializer/import and stale-API test errors
# - joshi-pairing: Result API/const conversion test-build errors
# - joshi-publication V2: tests still construct the superseded fields/scope/subjects model

cd apps/glass && npm test -- --run
# FAIL: 18/19 files passed; 138/140 tests passed
# - semantic keyboard navigation timed out
# - exact replay-scene overlay binding timed out

analysis/.venv/bin/pytest -q analysis/tests/test_analog_memory.py
# FAIL: 6 passed, 2 failed
# Both failures are stale expected-message mismatches after the temporal reveal repair.
```

The Rust failures prevent the root offline/readiness gate from being a release witness even where
individual unaffected packages might still pass. The Glass failures are not dismissed as timing
noise: critical accessibility and replay behavior have no attached-browser witness to supersede
them.

## P0 routing before the first fake/root witness

| P0 owner | Required closure |
| --- | --- |
| All settling package owners / root integrator | Restore one compiling workspace and rerun workspace tests, strict Clippy/schema checks, Glass typecheck/tests/build, Python tests and the root readiness command from the same frozen source tree. |
| Core/readiness owner | Remove the false ladder claim in `scripts/wave5-readiness`: it currently writes `maturity.fixtureWalked:true` although `run_wave5_ignition_readiness` walks only synthetic run registration, retry/conflict, status readback and reopen. Rename it to an ignition-only milestone or implement the complete Phase-0 offline fault walk. |
| Collector + store + supervisor owners | Make collector load the exact registered run from the sole store, then bind attempt/reservation/settlement/local-spool bytes to store catalog admission and exact ACK/readback across crash/restart. |
| Circulation + frozen source/census/market/projection/publication owners | Close the three blockers emitted by `joshi-operational-circulation`; do not turn its `VerifiedPrefix` or optional capabilities into a witness. |
| Surface + Cockpit V2 + store owners | Derive the declared population and every fact/coverage/gap/membership/omission from one commit cutoff; atomically commit body/checkpoint/head and revalidate after reopen. Standalone caller heads and commit sequences remain powerless. |
| Pairing + core + Glass owners | Mount the ordinary one-time exchange and immutable publication index/open routes using the new registry, trusted entropy/clock and durable nonsecret lifecycle. Remove reliance on the legacy static broad token for the ordinary product path. |
| Glass owner | Parse the exact W5 Cockpit V2 publication, expose every critical surface with honest gaps, and complete attached-browser keyboard, focus, zoom/reflow, contrast, screen-reader, pointer/touch and crash/reload/ACK recovery evidence. |
| Scientific-memory + episode + store + Glass owners | Create one store-derived act/session/outcome/interview path with exact scene/presentation references, a real reveal occurrence, clock ordering, retry/ACK/restart closure and no competing episode identity authority. |
| Export/store/core owners | Export a nonempty root snapshot, independently validate in Python and Rust, bind/import by CAS, reopen/reverify, and include backup/restore of every new W5 path. |
| Retention owner | Keep authenticated-private continuous capture disabled until inventory, origin spool, CAS, replicas, exports, derived refs and key destruction are physically controlled and fault-walked. |

### Fixture laundering found

`scripts/wave5-readiness` accurately labels its prose claim
`offline_semantic_run_registration_retry_and_reopen_only`, but simultaneously sets the official
ladder-shaped `fixtureWalked` field to true. The Living Instrument's `fixture_walked` milestone is
the full source -> spool -> catalog/ACK -> denominator -> hot/control -> semantic fact -> immutable
cockpit -> Glass -> scene/act -> restart/replay -> nonempty export/import and backup/restore fault
walk. A narrow registration witness cannot set that bit. Until repaired, the generated JSON is
not admissible as a Wave 5 maturity witness.

## First fake/root witness acceptance matrix

The first root witness remains **not run and not representable by the current root command**. It
must produce one machine-readable bundle containing all of the following without importing
fixture receipts as store truth:

| Required seam | Required witness | Current blocker |
| --- | --- | --- |
| Run authority | Exact store registration read back before any attempt | Collector consumes local registration files. |
| Accounting | Reservation before I/O; conservative started-attempt settlement; exact retry/restart | Package-local only; no store-run binding. |
| Bloodstream | Fsynced spool -> catalog admission -> same segment/batch/policy ACK -> reopen | Collector and W5 store paths are disconnected. |
| Denominator | Explicit nonempty eligible members/count/digest at one cutoff | Surface/publication values are not store derived; circulation cannot inspect census members. |
| Hot/control | Honest independent membership and every declared source/subject/field state | No integrated root producer. |
| Semantic fact | Exact source/fact artifact and provenance read back from store | No W5 source-fact adapter. |
| Cockpit | Atomic immutable V2 body/checkpoint/head with exact coverage/gaps/omissions | Pure library only; focused tests are red. |
| Glass | Same-origin paired open of that exact V2 publication | Expected routes/V2 parser are absent; DOM tests are red. |
| Memory | Scene-bound act/session/outcome/interview with exact ACK and restart | No adapter/route; scientific-memory does not compile. |
| Export/import | Nonempty production snapshot, Python+Rust validation, CAS import/reopen | Durable components exist but are not connected to root. |
| Faults | Crash at every reserve/I/O/spool/commit/head/ACK/export/import boundary | Only package-local subsets exist. |
| Recovery | Catalog plus blobs/private material backup and restore through new paths | No W5 root backup/restore witness. |

## Later nonfixture canary blockers

Only after the fake/root matrix is green may the bounded nonfixture canary begin. Its minimum
evidence remains: admitted C1/C2 provider adapters with canonical billing units; a preregistered
finite budget; at least two real subjects; dynamic hot and cold-control membership; at least two
immutable cuts; every declared source either covered or represented by an exact gap; one hour of
bounded operation; a forced restart with exact replay/readback; a nonempty validated export/import;
and no wallet, signer, transaction builder, submission, or model-driven acquisition/presentation
authority. Authenticated-private sources stay excluded until physical retention control exists.

The canary cannot promote from synthetic C0, the legacy static pairing token, an empty or
sample-only census, quiet sockets, auth failures, `latest` selection, inaccessible Glass, DOM-only
accessibility, fixture receipts, retrospective model skill, or scalar “complete” status. Every
result must retain its exact capability vector, denominator, coverage/gaps, clocks, digests,
identities, build, restart evidence and disqualifiers.
