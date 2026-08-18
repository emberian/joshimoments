# Lane 13 — Operator exocortex glass

Status: **implemented over the offline fixture contract; loopback command endpoint remains an integration gate**.

Date: 2026-08-16.

## Outcome

`apps/glass` now records low-friction semantic operator evidence without acquiring economic authority. The existing single-mode `joshi.glass.snapshot` contract remains unchanged: witnessed, knowledge-cutoff, and retrospective views are still separate immutable DTOs with their own scene ID, full as-of vector, and inner-view digest. Every operator record cites exactly one of those scene IDs and view digests. A record from a retrospective scene is never rendered as a witnessed-scene overlay.

The fixture UI supports:

- explicit, not hover-triggered, research focus;
- candidate nomination and a request for a typed hot scope;
- open-string provisional disposition and crackle-family language;
- episode meaning for externally observed partial recognition, retained runner, continued flat watch, and re-entry;
- semantic chart time, sample point, and ordered range annotations;
- separately named surfaced, filtered, actual viewport, interacted, and recent-comparison sets;
- confidence, urgency of attention, “why now,” and natural free text;
- a quick post-action report and a later interview linked to prior command IDs;
- a receipt timeline, exact retry after disconnection, and append-only compensating undo; and
- a scene inspector for view identity, choice context, source/projection clocks, and command receipts.

No control constructs, signs, submits, or verifies a transaction. Episode buttons record operator claims about actions observed outside Joshi. They are not fills, wallet effects, client-side PnL calculations, or proof that an external action landed.

## Public command envelope

The strict camel-case request is `joshi.operator.command` schema version 1:

```text
contract, schemaVersion
commandId, idempotencyKey
clientSessionId, clientCommandSeq
scene { sceneId, viewDigest }
issuedAt
clientClock { clockId, monotonicNs }
commandKind
subject { kind, key }
payload
authorityClass = evidence_only
effectCeiling = observe_only
```

`clientCommandSeq`, monotonic clocks, and all exact integral quantities are canonical decimal strings. Wall timestamps are UTC RFC3339 with exactly six fractional digits. Identities used for ordering are bounded ASCII. Contract objects are recursively strict.

Snapshot and operator timestamps share one strict calendar validator. It checks month, day, leap-year, hour, minute, and second bounds directly while preserving all six input microdigits; it does not use JavaScript `Date.parse`, which normalizes impossible dates such as February 31. Tests cover valid leap days, invalid non-leap February 29, February 30/31, month 13, day 00, and invalid clock bounds.

Candle `timeUnix` is also a decimal-string clock, but the chart boundary no longer accepts arbitrary `u64`. The snapshot contract caps it at `253402300799` (`9999-12-31T23:59:59Z`), parses through `BigInt`, and checks exact safe-number conversion before Lightweight Charts or `Date` receives it. Browser `monotonicNs` does not claim native nanosecond precision: Glass samples `performance.now()` at a safe integer microsecond, then uses `BigInt * 1000` to encode that sample in the required nanosecond unit. A long-uptime test proves the encoded value may exceed JavaScript's safe-integer range without passing through rounded nanosecond `Number` arithmetic.

The V1 browser allowlist is:

```text
record_focus
nominate_candidate
request_hot_scope
record_disposition
record_crackle_family
record_gesture
record_annotation
record_choice_set
record_post_action_report
link_interview
compensate_command
```

The kind is closed at the ingress boundary, while the provisional `disposition`, `crackleFamily`, and `gestureLabel` values are bounded open strings. This preserves Ember's evolving vocabulary without turning arbitrary payload shapes into an API. `request_hot_scope` is deliberately a request: the operator append does not falsely claim that a collection planner changed its sensing state. `record_post_action_report` is deliberately a report, not a landed trade assertion.

No command schema has quantity-to-submit, slippage, priority fee, transaction, instruction, signer, wallet secret, submission, cancellation, or rebroadcast fields. Unknown and dangerous keys fail.

## Canonical bytes and acknowledgement

Glass command canonical encoding version 1 is the exact UTF-8 encoding of the recursively strict, schema-key-ordered, whitespace-free JSON command. `commandDigest` is SHA-256 over those exact full request bytes. Glass payload canonical encoding version 1 applies the same rule to the strict kind-specific `payload`; `commandPayloadDigest` is SHA-256 over those bytes.

The cross-language golden is `apps/glass/src/operator/golden.ts`: its 243-byte payload digest is `sha256:11e7520b23cd385313fbdec6c5854614988ba4cdfadbe1958ca2078915233fa7`, and its 808-byte full-command digest is `sha256:7b27c7c0ceaee821a45b289c4694ced31d9a3861f1c59044335fd917a3abc531`. Rust must assert the same exact UTF-8 bytes and digests before the endpoint freezes.

The full-command digest is essential: the same payload under a changed scene, subject, kind, sequence, issue clock, or authority boundary is a different command. Neither digest is accepted from the browser as a self-claim. The command adapter derives both and echoes them in a strict `joshi.store.command_receipt` V1 containing:

```text
catalogId, catalogSchema
batchId, commandId
commandPayloadDigest, commandDigest
scene { sceneId, viewDigest }
commitSeq
status = accepted | idempotent
```

Glass accepts an acknowledgement only when command ID, both digests, scene ID, and view digest exactly match the retained request. Duplicate JSON keys are rejected over raw response text before ordinary parsing; dangerous prototype keys, unknown keys, malformed clocks, and oversized bodies fail. Loopback requests omit ambient credentials.

The offline sink is a deterministic contract fixture, not durable storage. It simulates post-commit accepted/idempotent receipts and body conflicts so the browser state machine can be exercised without a core. The production endpoint `POST /api/v1/operator/commands` is not implemented by this lane.

## Append, reconnect, and compensation

A command envelope is minted once. The UI may show it as `submitting` or `queued`, but it does not show a committed semantic mark until the matching acknowledgement arrives. On a retryable disconnect, the exact original envelope—including command ID, idempotency key, sequence, scene, issue clock, and payload—is retained. Manual retry or the browser `online` event resends identical bytes. A successful readback may return `idempotent`; it must name the same original commit.

“Undo” never edits or deletes the prior event. It appends `compensate_command` with a typed `compensatesCommandId` and reason. The timeline continues to show the original record and says that a later record compensates it.

The real adapter must reject:

- the same session/idempotency identity with changed command bytes;
- the same command ID with changed bytes;
- an absent or mismatched stored scene/view digest;
- a subject or choice member outside the admitted scene contract;
- an unsupported command kind or payload;
- a receipt formed before durable store commit/readback; and
- any authority/effect value other than `evidence_only`/`observe_only`.

## Honest scene and choice context

The scene inspector and choice capture do not call every feed member a decision. The client keeps these categories distinct:

- `surfaced`: every candidate served in the current immutable payload;
- `filtered`: the candidates remaining after current search/board filters;
- `viewport`: rows intersecting the actual virtual-list viewport, excluding overscan-only rows;
- `interacted`: candidates explicitly selected during this scene visit; and
- `compared`: the last three interacted candidates.

Choice subjects are typed, unique, and canonically sorted in a command payload. The future core must reconcile them to stored scene choice membership before the store call. The current Glass DTO does not itself prove the relational choice-member closure, so fixture acceptance is not that proof.

Chart annotations are semantic rather than pixel based:

- a time marker names an exact scene-local sample time;
- a point names `sampleId` plus its exact time; and
- a range names ordered start/end sample IDs and times.

Point annotations intentionally do not repeat a display price. A duplicated, unit-ambiguous decimal could disagree with the sample/series evidence. The referenced series/sample remains the value authority.

## Interaction and accessibility posture

The primary surface uses large targets and progressive disclosure. Common semantic actions are visible in the operator panel; episode-specific marks live under a selected episode disclosure; chart annotations have direct semantic buttons and an equivalent table action. Every capture opens a Radix Dialog with focus management, Escape handling, labelled inputs, a description of the current replay mode, and a plain-language no-authority boundary.

Keyboard affordances include:

- `F` — open deliberate-focus capture;
- `I` — open the current scene inspector;
- existing `J`/`K`, `/`, `R`, `P`, `D`, and Command/Ctrl-`K` navigation; and
- normal native keyboard operation for dialog fields, radio buttons, selects, disclosures, and actions.

Global shortcuts are suppressed while a dialog or text control owns focus. Canvas charts remain `aria-hidden`; the text summary, semantic annotation buttons, and latest-bars table are the accessible equivalent. CSS retains visible focus, 44–48 px targets, mobile single-column fallbacks, and `prefers-reduced-motion` behavior.

## Tests and integration gate

The executable suite covers:

- full-command versus payload digest binding;
- strict kind-specific payloads and rejection of economic-effect fields;
- point/range semantic anchor validation;
- exact idempotent retry and changed-body conflict;
- duplicate, dangerous, wrong-scene, wrong-digest, and oversized receipts;
- byte-identical offline reconnect;
- append-before-committed-render behavior;
- compensating-event undo without erasure;
- replay-scene isolation for committed overlays;
- keyboard capture and an axe-core scan of both the initial cockpit and capture dialog; and
- semantic point annotation without a duplicated display price.

Run from `apps/glass`:

```text
npm run typecheck
npm test
npm run build
```

The remaining cross-lane gate is the core adapter. It must strictly parse the public command, derive and retain exact bytes/digests, require the referenced admitted scene, reconcile choice membership, map to `SceneCommandBatch`/`CommandDraft`, wait for `commit_scene_command`, and build the stronger public acknowledgement. The current structural store receipt alone lacks catalog, scene/view, payload, and full-command digest closure and must not be exposed directly.

Visual layout and real keyboard/touch QA remain a separate gate requiring an attached in-app browser target. Automated DOM and axe tests do not claim that visual gate passed.
