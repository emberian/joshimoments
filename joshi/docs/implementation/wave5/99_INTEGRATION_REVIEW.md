# Wave 5 final adversarial integration review

Status on 2026-08-18 at baseline `9db5185` plus the current post-baseline settle:
**not promotable**. No full Phase-0/root witness, nonfixture canary, live-provider claim, product
claim, authenticated-private continuity claim, prospective-forecast claim, or economic capability
is qualified.

This is a ceiling ledger, not a test scoreboard. `intrinsic contract` means a package can validate
or transform caller-provided values. `unverified semantic` means useful semantics exist but
store/source truth is unavailable. `durable offline` means an exact package-local offline
occurrence survives readback/restart. `live` requires bounded nonfixture evidence; `product`
requires ordinary operator access and use. A green unit test, fixture receipt, public DTO,
syntactically valid digest, or caller-supplied clock/commit sequence never raises a ceiling.

## Live seam matrix

| Producer -> consumer | Landed owner/package | What is actually closed | Explicit ceiling | Promotion blocker |
| --- | --- | --- | --- | --- |
| Registered documents -> store | `joshi-admission::wave5` | Strict seven-byte-string run closure, six component semantics and read-only authority | **intrinsic contract** | Admission cannot prove a row was committed, read back or consumed by a runtime. |
| Run/control/import rows -> catalog | `joshi-store::wave5` + migration V9 | Private store capabilities; exact run registration; spool/catalog binding; operational records; restricted-artifact import and restart reverify | **durable offline** for those row families only | No W5 surface, memory, retention, epistemic or Cockpit V2 adapter exists. Authenticated-private spool admission correctly refuses without real AEAD/key-policy proof. |
| Fixture batch -> origin spool -> catalog ACK | `apps/core::wave5_circulation` | Immutable origin bytes precede ingest; exact segment/batch/policy/store receipt precede a run-bound catalog binding; binding precedes local ACK; exact retry and reopen retain the origin. Admission resolves the compiled route and refuses any mismatched access/stability/transport declaration; retention is derived from trusted route access, so an authenticated route cannot be relabeled public. | **durable offline**, one compiled public C0 fixture only | This is not the collector/supervisor root. The ACK closes the ingest receipt but carries no run-binding identity, so the separate binding readback is mandatory. The report emits booleans rather than the segment/policy/binding/ACK identities needed by a root evidence bundle. A later direct-input path must also source session authority from a trusted boundary. |
| Source plan -> provider call | `joshi-source-registry` + `joshi-sources` | Typed C0/C1/C2 plans; sealed C0 is one request/one fixture page and zero provider credits | **intrinsic contract** | C1/C2 execution is deliberately refused; registry values are not source/store evidence. |
| Reservation -> attempt -> settlement -> local spool | `joshi-supervisor` | Append-before-I/O journal; conservative ambiguous-start charging; terminal replay-only recovery; finite C0 completion without a false clean-shutdown gap | **durable offline**, package-local C0 only | It is not attached to the store-readback run or catalog ACK. Its green tests do not prove the root chain. |
| Registered run -> collector runtime | `apps/collector` | Caller-supplied exact registration/plan/fixture can drive the C0 runtime | **durable offline**, local C0 only | Collector does not load its run/plan from SQLite or commit/read back the spool/catalog ACK. The new core helper does not connect the supervisor runtime to the store. |
| Source receipt -> census -> market -> projection -> publication | `joshi-operational-circulation` | Exact-byte and cutoff audit reaches a typed blocked prefix | **intrinsic contract** | It always returns `Blocked`: census members are not inspectable, projection lacks exact market-state artifact/receipt closure, and publication receipt lacks exact publication-byte closure. Optional opaque precommit values cannot repair postcommit semantics. |
| Store observations -> daily surface | `joshi-surface` | Profile/task validation, point-in-time reduction, closed-universe partition and exact profile x source x subject x field closure; public qualification is fixed unverified | **unverified semantic** | Inputs are caller projections. Open sample cuts do not recompute subject order/count/digest; surface/profile parsers do not enforce exact canonical input bytes; stale age is not recomputed from cutoff. A private adapter must derive the population, facts, gaps, clocks and lease receipts. |
| Broad manifest -> body/checkpoint/head | `joshi-publication::v2` | Strict pure manifests; per-cell public fact/gap checks; exact eligible/render/omission partitions; distinct digest domains; canonical manifest/checkpoint/query/head/publication parsers; adjacent stage model | **unverified semantic** | Fact, coverage, gap and membership digests are unresolved caller values. No atomic store prepare/body/head writer, mounted immutable route or restart readback exists. A standalone head is not publication authority. |
| Cockpit publication -> operator | `apps/glass` | Strict bounded client contracts, stable accepted order, private pending-command/act transport, exact ACK rules and evidence-only controls | **intrinsic contract** / fixture UI | Core now has a deliberate loopback-only ordinary-pairing mount for Cockpit index/open and evidence routes, but no attached-browser screen-reader, keyboard/focus, zoom/reflow, contrast or pointer/touch witness qualifies accessibility or product use. |
| One-time code -> scoped session | `joshi-pairing` | Human-checkable single-use code; durable SQLite rate/expiry/revoke/restart state; OS entropy; monotonic-anchored wall time; zeroized and nonserializing secrets; exact Rust/Glass `jpc1_` wire | **isolated durable protocol** | Normal `Serve` remains unmounted by default. Its opt-in is exact-loopback only, read/replay by default, and separately gates evidence writes. No signing, wallet, transaction, or execution scope exists; no browser-use/root occurrence qualifies the product. |
| Pairing/client -> core routes | `apps/core::service` | Legacy loopback routes plus opt-in ordinary exchange, Cockpit V2 index/open and scoped evidence authorization; static capability file remains owner-only/redacted | **isolated durable local mount** | Default remains unmounted; no attached-browser or daily-use witness exists. W5 status/export/import routes and durable prospective launch/nomination/abstention remain unavailable. |
| Inventory -> retention action | `joshi-retention` | Pure typed policy/lifecycle kernel; public construction stays `UnknownInventory`; no destructive API | **unverified semantic** | No verified V9 inventory adapter or physical filesystem/replica/export/key controller/fault walk. Authenticated-private continuous capture remains unavailable. |
| Scene/act/episode -> research admission | `joshi-scientific-memory` | Separate positive logical-tick/catalog-sequence types; strict occurrences; typed gaps; terminal episode semantics; no public positive store witness | **unverified semantic** | Retrospective reveal names the earlier hidden replay rather than a real reveal/outcome occurrence and does not require reveal <= retrospective record. Global append order tracks mixed semantic clocks rather than actual recorded/commit order. Replay blob provenance is opaque. No store/Glass ACK path exists. |
| Earlier decisions -> analog/reveal | `analysis/.../analog_memory` | Earlier-only decisions, exact missingness/distance, deterministic ties, complete matured/missing/conflicting/censored partition and `known <= maturity <= reveal` | **unverified semantic** | Decision and outcome provenance are caller materialized, not store resolved. |
| Prospective wrapper -> closure | `joshi-episode-closure` | Exact pure prospective DTO/lineage validation | **intrinsic contract** | Caller-authored receipts are syntactic and disconnected from scientific-memory and the registered W5 root. |
| Claims/submissions -> score/ensemble | `joshi-epistemic-book` | Exact pure B0-B4 semantics; every artifact is powerless H3; positive score/ensemble APIs require opaque unavailable capabilities | **unverified semantic** | Store must derive occurrence, frozen evidence, visibility/reveal, adjudication and complete earlier-only support. |
| Book DTO -> durable epistemic admission | `joshi-epistemic-admission` | Public success is only `UnverifiedSemantic`; receipt fields are private with no public constructors | **intrinsic contract** | There is no migration/writer or positive durable path. The planned cross-crate book-capability bridge is not implementable as written, support and reveal-receipt verifiers are incomplete, and the four “adversarial” fixture tests only check an expectation label rather than execute the vectors. |
| Durable progress/resources -> status | `joshi-operational-status` | Bounded read-only DTOs and finite degradation/recovery validation | **unverified semantic** | `from_store_resolved` is a name, not authority. No authenticated mounted query derives all required components; recovery never closes source coverage by itself. |
| Candidate/reference sample -> census decision | `joshi-census-bakeoff` | Nonvacuous denominators, finalized-reference filtering, explicit gaps/costs and recomputation; pure result caps at `SampleOnly` | **unverified semantic** | Store/source derivation is required before `CensusQualified`. |
| Mechanics evidence -> claim prerequisites | `joshi-mechanics-capability` | Independent nontransitive profiles and explicit refusals; all public rows/checks are unverified | **unverified semantic** | Durable simulation-occurrence and settled-attempt receipts are absent. |
| Catalog snapshot -> Parquet/CAS/import | `joshi-export`, `joshi-artifact-admission`, store V9 import | V8 Snapshot V2 can be produced/validated; restricted derived-artifact bytes can be imported and reverified | **durable offline** only for the represented fixture relations | Export refuses every populated V9 W5 table, emits only scenes/coverage while other relations are empty, never applies `from_commit_seq` to its queries, accepts caller publication descriptors, and launches `uv run --locked` without `--offline`. Artifact positive coverage is empty-only and does not recompute all derived row metrics. |
| Research/model output -> acquisition/presentation/action | field/ML/ensemble/shadow-policy lanes | Package-local research only | **unverified semantic** | Model output may not influence initial acquisition, ranking, presentation, alerts, hot leases or action affordances without a separately registered prospective intervention. |

No row attains **live** or **product**.

## Current independent gates

These results are from the active post-baseline tree and supersede the pre-baseline compile errors
previously recorded here:

```text
cargo test --locked --offline \
  -p joshi-scientific-memory -p joshi-surface -p joshi-publication \
  -p joshi-pairing -p joshi-supervisor -p joshi-epistemic-book --all-targets
# PASS: 92 tests, including 29 supervisor unit/continuity/process-kill tests

cargo test --locked --offline -p joshi-epistemic-admission --all-targets
# PASS: 4 tests (but its fixture test only checks expectation labels)

cargo clippy --locked --offline \
  -p joshi-scientific-memory -p joshi-surface -p joshi-publication \
  -p joshi-pairing -p joshi-supervisor -p joshi-epistemic-book \
  -p joshi-epistemic-admission --all-targets -- -D warnings
# PASS

RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline --no-deps \
  -p joshi-scientific-memory -p joshi-surface -p joshi-publication \
  -p joshi-pairing -p joshi-supervisor -p joshi-epistemic-book \
  -p joshi-epistemic-admission
# PASS

analysis/.venv/bin/pytest -q analysis/tests/test_analog_memory.py
# PASS: 8 tests

cd apps/glass && npm run build
# PASS; bundle-size warning only

cd apps/glass && npm test -- --run
# PASS: 20 files, 148 tests
```

The narrow C0 component candidate now passes:

```text
cargo test --locked --offline -p joshi-core --all-targets
# PASS: 18 tests

cargo run --locked --offline -p joshi-core -- \
  wave5-ignition-readiness --state /tmp/joshi-wave5-final-ignition.jVRwEP
# PASS: V9 useful_partial; progress=2; circulation/origin/ACK/restart=true;
#       provider/publication/live=false

cargo clippy --locked --offline -p joshi-core -p joshi-admission \
  -p joshi-store -p joshi-pump-adapter --all-targets -- -D warnings
# PASS
```

The root gate is still red:

```text

cargo fmt --all -- --check
# FAIL: current pairing, publication and surface formatting diffs
```

An earlier post-baseline workspace PASS preceded these active integration changes and is not a
full-root result for this tree. More importantly, the green C0 component does not join the
collector/supervisor occurrence, provide an evidence-complete root bundle or repair any later
root seam.

## P0 routing before the first fake/root witness

| P0 owner | Required closure |
| --- | --- |
| Core/admission/source/store/readiness owner | Preserve the new exact `routeId -> RouteSpec` access/stability/transport validation and route-derived retention. For later direct input, also derive exact session authority at a trusted boundary; never let a caller downgrade retention. Keep unknown/authenticated material private. Emit exact segment/batch/policy/admission/binding/ACK identities in the evidence bundle; an ACK alone is not the run binding. |
| Collector + store + supervisor owners | Make the collector load the exact registered run/final plan from the sole store, then bind supervisor reservation/I/O/settlement/local-spool identity to store catalog admission and exact ACK/readback through crash/restart. Do not count the separate core helper as this join. |
| Surface + Cockpit V2 + store owners | Resolve one exact population and every fact/coverage/gap/cell at one commit cutoff; require exact canonical input bytes; atomically persist body/checkpoint/head and reverify after reopen. |
| Pairing + core + Glass owners | Design one wire contract and clock domain first, then mount ordinary one-time exchange and immutable publication index/open with OS entropy and durable nonsecret issue/consume/revoke/restart occurrences. Keep the current path unmounted meanwhile. |
| Glass owner | Parse the exact W5 Cockpit V2 publication, expose every critical surface with honest gaps, and obtain attached-browser keyboard/focus/zoom/reflow/contrast/screen-reader/pointer/touch and crash/reload/ACK evidence. |
| Scientific-memory + episode + store + Glass owners | Store one exact scene-bound act/session/outcome/reveal/interview chain with real recorded/commit order, retry/ACK/restart closure and one episode identity authority. |
| Export/store/core owners | Add nonempty V9 relation adapters and lower-cutoff query semantics; resolve publication metadata from store; force the Python validator offline; validate/import/reopen a nonempty root snapshot; include backup/restore. |
| Retention owner | Keep authenticated-private continuous capture disabled until inventory, origin spool, CAS, replicas, exports, derived refs and key destruction are physically controlled and fault-walked. |

### Fixture-laundering audit

The earlier root blocker was real: `scripts/wave5-readiness` set a ladder-shaped
`fixtureWalked:true` for a run-registration/reopen-only test. The current integration edit repairs
that claim shape: it no longer emits `fixtureWalked`, explicitly emits
`qualification.fullOfflineFaultWalk:false`, and labels only
`public_c0_spool_catalog_closed`. That rename must be retained.

It is still not a root witness. The component walk is green only for one compiled C0 fixture and
its public-retention decision is now pinned to the compiled public route catalog. It still does
not join the collector/supervisor occurrence and omits source fact, denominator, hot/control,
Cockpit V2, Glass, memory, status recovery, nonempty V9 export/import and backup/restore. Therefore no
`fixture_walked`-equivalent bit may reappear until the complete Living Instrument Phase-0 fault
walk exists.

## First fake/root witness acceptance matrix

The first fake/root witness remains **not run and not representable by the current root command**.
It must emit one machine-readable bundle derived from producer/store receipts, not fixture labels:

| Required seam | Required witness | Current blocker |
| --- | --- | --- |
| Run authority | Exact store registration read back before any attempt | Core registers/readbacks a fixture run, but collector/supervisor do not consume that store capability. |
| Accounting | Reservation before I/O; conservative settlement; exact retry/restart | Supervisor PASS is package-local and not in the store-root occurrence. |
| Bloodstream | Fsynced origin -> ingest -> run-bound catalog receipt -> ACK -> reopen | Compiled public C0 component passes with route-derived protection, but it is separate from supervisor acquisition/accounting; ACK and run binding remain separate, and the report omits their exact identities. |
| Denominator | Nonempty eligible members/count/digest at one cutoff | No store-derived declared universe; sample/open surface data remain caller material. |
| Hot/control | Independent membership and every declared source/subject/field state | No integrated producer/store path. |
| Semantic fact | Exact source/fact artifact and provenance read back | No W5 source-fact adapter. |
| Cockpit | Atomic immutable V2 body/checkpoint/head with exact facts/gaps/omissions | Pure unverified library only. |
| Glass | Same-origin paired open of that exact V2 publication | Pairing wire conflict and expected core routes/V2 parser are absent. |
| Memory | Scene-bound act/session/outcome/reveal/interview with exact ACK/restart | No adapter/route; reveal and cross-append clocks remain unclosed. |
| Export/import | Nonempty V9 snapshot, independent Python+Rust validation, CAS import/reopen | Export refuses populated V9 W5 tables and artifact coverage is empty-only. |
| Faults | Crash at reserve/I/O/spool/commit/head/ACK/export/import boundaries | Only package-local subsets exist; circulation covers two post-spool points but not the full root boundary matrix. |
| Recovery | Catalog plus blobs/private material backup/restore through new paths | No W5 root backup/restore witness. |

## Later nonfixture canary blockers

Only after the fake/root matrix is green may the bounded nonfixture canary begin. Minimum evidence:
admitted C1/C2 adapters with canonical billing units; a preregistered finite budget; at least two
real eligible subjects; one dynamically hot subject and one denominator-only cold control; two
immutable cuts; every declared source covered or represented by an exact gap; one bounded hour;
forced restart with exact replay/readback; nonempty validated V9 export/import; and no wallet,
signer, transaction builder, submission or model-driven acquisition/presentation authority.
Authenticated-private sources stay excluded until physical retention control exists.

The canary cannot promote from synthetic C0, the legacy static pairing token, an empty/sample-only
census, quiet sockets, auth failures, `latest` selection, inaccessible Glass, DOM-only
accessibility, fixture receipts, retrospective model skill or a scalar “complete” status. Every
result must retain its exact capability vector, denominator, coverage/gaps, clocks, digests,
identities, build, restart evidence and disqualifiers.
