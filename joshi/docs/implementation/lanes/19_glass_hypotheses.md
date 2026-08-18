# Lane 19 — Glass as a presentation-hypothesis lab

Status: **implemented over exact offline fixture admissions; core presentation endpoints and admitted analysis artifacts remain integration gates**.

Date: 2026-08-16.

## Outcome

The Glass now treats presentation as part of the experiment rather than a neutral UI preference. Its binding product rule is:

> Protect Ember from clerical interruption, not from information.

The implementation preserves a rich market, portfolio, social, topology, and provenance surface. It records which versioned presentation policy prescribed a view, which exact evidence artifacts were eligible, which panels and overlays were selected or omitted, their planned placement/order/salience, active filters and toggles, and later empirical visibility/focus/control events. It never compresses the coupled field into a scalar “pressure score.”

The original `joshi.glass.view` V1 bytes and golden are unchanged. Presentation is a sibling artifact bound to the immutable Glass scene ID and view digest; it does not duplicate or client-filter the as-of vector.

## Implemented surface

`apps/glass` now contains:

- three manually selected presentation hypotheses: **Flow before story**, **Arrival before return**, and **Coupled field bundle**;
- eight fixture-driven exploratory views:
  - wallet and cluster flow;
  - caller response kernels;
  - attention arrival;
  - marked order timing and exact size;
  - liquidity susceptibility and resilience;
  - directed PvP compression and churn;
  - overlapping lifecycle/topology transitions; and
  - a coupled field bundle that preserves disagreement across flow, attention, liquidity, topology, and lifecycle;
- independent observed/derived/inferred/uncertain evidence toggles;
- direct switching with `1`–`8` and `[`/`]`, global `H` focus, large targets, pinning, and up-to-three-view comparison;
- stable `data-voice-command` semantic hooks without microphone permission, ambient capture, or a fabricated transcript;
- an after-action usefulness report for perceived decision latency, attention cost, overtrading, regret, missed opportunity, and overall usefulness;
- PnL represented only as `awaiting_reconciled_projection` or a digest link to a reconciled accounting artifact—never a client-entered or client-computed amount;
- exact source-artifact closure in an accessible disclosure and the scene provenance inspector; and
- a full table/text equivalent for every exploratory view. Any later graph/canvas rendering remains supplementary and `aria-hidden` until it has an equivalent semantic representation.

The layout remains responsive: wide comparison becomes a single column below 920 px, controls stack below 620 px, touch targets remain at least 44–46 px, focus rings remain visible, dialogs use Radix focus management, and reduced-motion preferences disable motion. The initial view and usefulness dialog pass automated axe scans; real attached-browser visual and touch QA remains a separate gate.

## Epistemic contract

Every displayed row carries an evidence class and an explicit epistemic label:

```text
presentation evidence: observed | derived | inferred | uncertain | mixed
source meaning: protocol_fact | provider_assertion | first_party_statement |
                operator_annotation | derived_measure | model_inference
```

The bundle also carries coverage, support, uncertainty, exact availability time, and a source-artifact ID. Every source reference must close to a digest-bound artifact inside the bundle. A source artifact available after bundle generation is invalid. The current exploration bundle has literal claim scope `descriptive_noncausal_fixture`; its source artifacts are explicitly `fixture_unverified` with `unverified_fixture` coverage binding.

This is intentionally conservative. Production admission must not upgrade a panel because its title sounds authoritative. In particular:

- an observed transaction version is not automatically an accepted canonical fact;
- a funding transfer does not prove common control;
- a wallet cluster is a versioned hypothesis, not an entity identity;
- a selected caller/cluster context is event-bound to an exact cut, not global identity truth;
- callout-followed-by-arrival does not prove causal caller impact;
- a marked size is not Ember's order and a reserve-geometry value is not an executable quote;
- apparent resilience can be arbitrage, regime change, opposite flow, or attention exit; and
- directed PvP flow remains dyadic/antisymmetric rather than becoming a coin-level score.

## Presentation policy and witnessed scene

The strict recursively closed contracts live in `apps/glass/src/presentation/contract.ts`.

### Policy

`joshi.presentation.policy` V1 records:

- stable policy ID and version;
- the human-readable presentation hypothesis;
- literal `assignmentMode = operator_selected`;
- primary view, panel order, salience, and initially visible overlays;
- non-omittable safety items;
- literal `liveRandomization = forbidden` and `informationPolicy = preserve_rich_information`; and
- all six outcome measures with the authority allowed to produce each one.

There is no automatic live randomization. A future bounded replay/offline study may compare policies, but the live Glass will not silently hide context or safety-critical truth to satisfy an experiment.

### Exact composite admission

A digest-only reference was insufficient because a real receiver could not resolve client-held policy or bundle bytes. The public write request is therefore the strict composite:

```text
joshi.presentation.scene_admission/v1
  policy: exact joshi.presentation.policy/v1
  explorationBundle: exact joshi.presentation.exploration_bundle/v1
  scene: exact joshi.presentation.scene/v1
```

Admission validates that:

- the scene's policy ID/version/digest closes to the supplied exact policy bytes;
- the scene's exploration artifact ID/digest closes to the supplied exact bundle bytes;
- bundle and presentation name the same immutable Glass scene ID and view digest; and
- each presentation carries a mandatory manual assignment occurrence ID.

The initial shell is gated before reveal. When a Glass snapshot arrives, the app first builds and appends the composite presentation admission. Attention feed, coin workbench, field lab, operator panel, exposure rail, and source provenance do not render until the matching presentation receipt arrives. If admission fails, rich information is shown with an explicit **presentation not witnessed** coverage gap rather than silently claiming a complete witness.

A manual policy change is not a client-only toggle. It builds a fresh presentation scene with a new assignment ID and increasing presentation sequence, sends the exact next policy and bundle again in a composite admission, and applies the policy only after the matching receipt. The prior admitted view remains visible while the new assignment is pending.

### Initial manifest semantics

The immutable initial manifest records the staged prescription, not a browser-render fact:

- canonical eligible item IDs;
- policy-selected `selectedItemIds`;
- `plannedRenderItemIds`, equal in V1 to selected non-omitted content;
- an empty `plannedInitialViewportItemIds` set because the gated surface does not yet exist;
- every eligible item with type, placement, unique placement ordinal, visibility, typed omission reason, salience, pin state, evidence class, and safety-critical flag;
- exact filter/toggle state and comparison members; and
- `initialFocusItemId = null` unless the browser has an actual focus occurrence.

Contract validation requires:

```text
plannedInitialViewport ⊆ plannedRender = selected ⊆ eligible
comparison ⊆ plannedRender
every eligible item has exactly one item record
every omitted item has a typed reason
no safety-critical item may be omitted
placement ordinals are unique
```

Visual primacy is salience, not attention. The UI never fabricates focus from a preferred policy view. After the receipt releases the gate and React mounts the declared surface, the app appends a `visibility_started` occurrence for each planned-render item. Those post-mount events—not the precomputed manifest—are the empirical exposure evidence. A missing event receipt creates an explicit incomplete-exposure gap.

## Interaction, focus, and dwell evidence

Post-reveal activity is append-only `joshi.presentation.event` V1:

- `visibility_started` / `visibility_ended`;
- `focus_started` / `focus_ended`;
- exact `control_changed` for filters, toggles, pins, comparison, and salience;
- a voice-ready semantic capture hook with `transcript = null`; and
- `usefulness_reported` with typed outcomes and no financial value field.

Focus intervals are emitted only when focus actually enters or leaves the lab through DOM focus/focusin behavior, including the explicit `H` shortcut. Selecting a view records the control and visibility transition; it does not assert focus. Dwell is derived later from paired monotonic interval occurrences and browser visibility context. It is never stored as a mutable “attention duration” in the initial scene.

Events are serialized per client session and presentation. A UI transition may create several semantic occurrences, but sequence `n+1` is not sent until `n` has a matching receipt. The first missing/rejected receipt stops the queue; later sequence numbers remain unsent and the UI exposes a capture gap. This prevents network response reordering from inverting focus or visibility intervals.

## Exact bytes and receipts

Canonical V1 encoding is the exact UTF-8, schema-key-ordered, whitespace-free JSON emitted after recursively strict parsing. Unknown/dangerous keys and duplicate receipt keys fail. Receiver-derived SHA-256 digests are algorithm-qualified lowercase strings. Fixed TypeScript reference vectors live in `apps/glass/src/presentation/golden.ts`. They are not called cross-language goldens until a Rust presentation parser/admission test consumes the same bytes:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| policy | 1,285 | `sha256:0dd7aa23c1eb08275436b88e5da0118a06acc482368b94ff2191447a8e8c468c` |
| minimal eight-panel exploration bundle | 2,560 | `sha256:f57c6cba14bb713dd09ee94e53eb5b26320c17a29c8ec2b4ac84d64afef17362` |
| initial presentation scene | 2,325 | `sha256:8c28191dd9b9714518a634c7fbdd97fa084cf10c8a76bc388dc127afc08d9df7` |
| genuine-focus interval event | 821 | `sha256:4fbd49185a10ee42be48a36f456b42c9e1126d079630c6e90d65b0a8b81dc30a` |
| presentation-scene receipt bytes | 656 | `sha256:e5fc2454496191cd5a1db0744ddc14329509f0e1abb78c7bf5a01c7c2a01f171` |
| presentation-event receipt bytes | 627 | `sha256:a5cff2d703c6a90114d4eeac56e9367958a64e787492e8b56280588d9364c422` |

The scene receipt echoes catalog/schema, batch, presentation ID, idempotency key, assignment ID, Glass scene/view reference, policy digest, presentation digest, commit sequence, and accepted/idempotent status. The event receipt binds event ID/digest to the same presentation digest and Glass scene/view.

The offline sink simulates post-commit receipts and exact idempotency conflicts. It is a deterministic contract fixture, not durable storage.

## Domain adapter targets

Glass fixtures deliberately mirror but do not replace the stable lane contracts.

### Wallet/topology

Primary fixture: `fixtures/wallet-topology/point_in_time.json`.

The adapter must preserve `observedTransactionVersions` separately from `acceptedFacts`; include transaction fact version/supersession, canonicality, finality, availability, exact signature/slot/transaction index, and exact atom effects; and represent cluster hypotheses by series/version/status with adversarial alternatives. Three-axis selection is availability cutoff plus event slot plus event time. Requested coverage remains unverified until the core closes the named evidence IDs.

### Attention/social

Planned fixtures are under `fixtures/attention/`, including attention tape, ambiguous identity, revision/deletion, and censoring/competing-event cases. The adapter targets occurrence-specific attention events, bitemporal identity versions, overlapping territory membership hypotheses, selected cluster contexts, coverage context, long-form kernel marks, risk-set cohorts, and response observations. It must render labels such as `CALL OUT OBSERVED`, `PROVIDER IDENTITY LINK`, `INFERRED CLUSTER`, and `COVERAGE UNKNOWN`, never “smart caller” or causal impact.

### Analysis

Stable analysis artifacts are:

- `.artifacts/kernels/kernel-<digest>/kernel_estimates.parquet` — `joshi.analysis.marked-response-kernel/v1`;
- `.artifacts/kernels/kernel-<digest>/candidate_diagnostics.parquet` — `joshi.analysis.response-model-candidate-diagnostic/v1`; and
- `.artifacts/fields/field-<digest>/field_observables.parquet` — `joshi.analysis.dynamic-field-observable/v1`.

Production admission must verify the eligible-input snapshot/logical digest, fit/max-input/as-of cutoff, exact unit and orientation, estimator/build/config/profile, topology epoch/boundary status, support, uncertainty, coverage/gap IDs, gap-sensitivity bounds, and restrictive noncausal claim scope. Current liquidity, Hodge/field, and kernel prototypes remain fixture-only until those checks pass.

### Accounting/portfolio

Financial values will be formatted from exact projection artifacts with stable metric/fact IDs, typed known/missing/stale/conflicting/unsupported status, exact units/atoms or reduced rationals, and evidence digest. Glass does not derive metric identity from JSON paths and does not compute nested accounting or PnL truth.

## Loopback and security boundary

Read startup now requires an explicit immutable launch scene:

```text
GET /api/v1/glass/snapshot?mode=witnessed&basisSceneId=<scene-id>
```

`LoopbackDataSource` refuses to call the core when no witnessed launch scene ID is supplied; it never invents “latest” or “current.” `VITE_JOSHI_LAUNCH_SCENE_ID` is a non-secret explicit launch selector. Reads omit ambient credentials and need no pairing. Core and Glass now share the strict outer `joshi.glass.snapshot/v1` envelope: the core embeds the exact stored canonical view, derives its digest from those bytes, declares `transport = loopback`, and has a Rust exact-response test; the TypeScript client validates the bounded duplicate-safe envelope and the same digest.

Mutation clients now require a `MemoryOnlyPairingSession` containing the exact 32-byte lowercase-hex capability and send it only in `X-Joshi-Pairing-Token`. The session has no serialization API and never reads query state, cookies, local/session storage, or build-time environment. It clears on reload or explicit `clear()`. Unpaired mutation clients fail before `fetch`.

No pairing bootstrap UI is claimed. The shared session starts empty, so configured live operator/presentation mutation remains disabled until an explicit native/manual handoff exists. Core also intentionally has no wildcard CORS/preflight policy: live browser mutation needs same-origin serving/proxying or a separately reviewed explicit origin policy. The implementation does not weaken that boundary.

Current/target routes:

```text
GET  /api/v1/glass/snapshot                    implemented exact-envelope core read; explicit stored scene required
POST /api/v1/operator/commands                 implemented core mutation; paired, same-origin required
POST /api/v1/presentation/scenes               target; exact composite admission; not implemented in core
POST /api/v1/presentation/events               target; serialized exact events; not implemented in core
```

## Tests and gates

Run from `apps/glass`:

```text
npm run typecheck
npm test
npm run build
```

The suite covers:

- fixed TypeScript reference bytes/digests for policy, bundle, scene, interval event, and receipts;
- strict unknown-key, evidence-cut, lineage-closure, future-availability, set-closure, placement-order, safety-omission, and client-PnL rejection;
- exact composite admission, policy/bundle closure, idempotent retry, changed-body conflict, and event-before-scene rejection;
- full-shell pre-receipt staging and explicit gap behavior;
- new exact scene/assignment before applying a manual policy change;
- real keyboard focus intervals rather than salience-derived focus;
- serialized delayed event receipts and fail-stop behavior after a missing receipt;
- keyboard switching, pinning, comparison, evidence omission capture, voice hooks, and usefulness reports;
- non-omittable exposure/source truth;
- memory-only pairing, fail-before-fetch behavior, and no browser persistence access;
- explicit immutable launch-scene query semantics; and
- automated accessibility scans.

Remaining gates are the core presentation admission/event endpoints; a Rust parser/admission binding for the presentation reference vectors; resolution of registered source artifacts against the stored Glass as-of vector; an explicit safe pairing/bootstrap and same-origin browser deployment; a stored-scene selector or builder for requesting separately persisted knowledge-cutoff/retrospective views (the core read endpoint does not synthesize them); real wallet/attention/analysis adapters; and attached-browser visual/touch/screen-reader QA.
