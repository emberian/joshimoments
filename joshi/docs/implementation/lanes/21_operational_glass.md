# Lane 21 — same-origin operational Glass

Status: implemented browser boundary, exact cross-runtime session vectors, and fail-closed core posture; durable session semantics and attached-browser gates remain open where named below.

## Outcome

`apps/glass` now boots through an operational shell rather than silently selecting an offline fixture. The shell has three explicit phases:

1. exchange a launcher-issued one-time code on the exact page origin;
2. inspect and explicitly choose an immutable durable cockpit publication ID;
3. verify its launch closure, durably admit the staged presentation, and reveal the cockpit only after the presentation receipt.

The offline data source and sinks remain deterministic test fixtures. They are injectable into `GlassApp`; they are not the production entry point in `main.tsx` and never claim production freshness.

## Same-origin pairing

The browser sends this strict request to `POST /api/v1/pairing/exchange`:

```json
{"contract":"joshi.pairing.exchange","schemaVersion":1,"oneTimeCode":"…"}
```

The response is `joshi.pairing.session` V1 with `sessionId`, exact six-digit UTC `expiresAt`, the fixed canonical scope tuple
`cockpit_read`, `operator_evidence_write`, `presentation_evidence_write`, `replay_read`, literal authority `read_only_no_execution`, and an opaque capability. The caller cannot request scopes.

The capability is held in a private field of `MemoryOnlyPairingSession`. It is never put in a URL, cookie, Web Storage, environment variable, rendered DOM, evidence DTO, or log. Reload, expiry, explicit end-session, 401, or 403 clears it. Reads and evidence writes fail before `fetch` when the required scope is absent. All operational requests use `credentials: "omit"`; constructors reject any origin other than the exact HTTP loopback page origin. No CORS behavior was added.

## Durable publication versus Glass launch

There is one durable cockpit-publication truth: Rust `joshi.cockpit_publication` V1. Glass validates its exact schema-ordered digest preimage and carries its immutable `cockpitPublicationId` and `cockpitPublicationDigest`. The existing Rust vector is pinned in TypeScript:

- preimage: 800 UTF-8 bytes;
- full publication: 901 UTF-8 bytes;
- digest: `sha256:f9ba49c1d85a43bb8ab85bf3ec0c446e53f35fb2e6b6da35bdae65d3557593d1`.

`joshi.glass.cockpit_launch` is deliberately a different browser-serving object. It carries the exact durable publication plus one verified Glass snapshot, exact presentation-policy bytes, exact exploration-bundle bytes, explicit replay-publication references, freshness, and display metadata. Its digest is not a replacement publication digest. Glass rejects disagreement among durable scene ID, snapshot scene/view digest, bundle evidence cut, index entry, replay reference, or either digest domain.

Discovery is a bounded `joshi.glass.cockpit_publication_index` with literal selection policy `explicit_only_no_latest_pointer`. The shell never auto-opens a row. `GET /api/v1/cockpit/publications/{cockpitPublicationId}` is the proposed exact-ID read route. No mutable current/latest pointer exists. Choosing another publication unmounts the cockpit and starts a new presentation witness.

## Presentation and reveal

Existing presentation contracts and receipts remain frozen:

- `POST /api/v1/presentation/scenes`, request bound 128 KiB;
- `POST /api/v1/presentation/events`, request bound 128 KiB;
- receipts bound 64 KiB;
- `joshi.store.presentation_scene_receipt` and `joshi.store.presentation_event_receipt` V1 unchanged.

Production launch material comes from the admitted launch envelope, never `explorationBundleFor`. `GlassApp` constructs the staged scene from those exact policy/bundle bytes. The full cockpit remains concealed until the scene receipt matches the immutable scene and view digest. Post-mount `visibility_started` events remain serialized, append-only component-lifecycle evidence; they do not claim pixels, gaze, or viewport measurement. In operational mode a scene-admission failure remains concealed rather than using the research fixture's explicit coverage-gap fallback.

## Presentation-complete commands

`joshi.operator.command` V1 is unchanged and remains presentation-incomplete. The W4 browser can construct V2 only after the presentation receipt. V2 preserves the same closed semantic command kinds and strict payloads, and adds required:

```text
presentation { presentationId, presentationDigest, assignmentId }
cockpitPublication { cockpitPublicationId, cockpitPublicationDigest }
```

The V2 store receipt echoes those bindings in addition to the V1 scene, payload digest, full command digest, commit and status. The full digest covers the exact strict V2 command bytes. Fixed TypeScript vector:

- command digest: `sha256:c470a79010ac84b2a33d3027faa4695f337e848df7a52d84cf7d1da6c0e80fdb`;
- payload digest: `sha256:11e7520b23cd385313fbdec6c5854614988ba4cdfadbe1958ca2078915233fa7`.

Rust must pin this vector and implement strict V2 admission before the live operator sink is considered complete. V1 records must not be upgraded retrospectively to presentation-complete decisions.

## Prospective registered mode

General browsing and a preregistered prospective episode are different modes. Rust has frozen `joshi.episode.launch_registration` V1 and `joshi.store.episode_launch_receipt` V1. Their strict nested schemas are mirrored in Glass, including exact protocol, cutoff, source receipts, census, hot-scope intents, projection, cockpit, scene, presentation plan/assignment and downstream contract bindings.

The prospective transport is the frozen parameterless authenticated `GET /api/v1/session/launch`. Its strict `joshi.glass.session_launch` V1 response closes the exact protocol and protocol receipt as well as the launch registration and receipt. The server-bound session—not a prop, query parameter, or browser choice—resolves exactly one launch and permits opening only its cockpit publication ID/digest. Glass implements this as a separate prospective shell mode: it never requests or renders the general publication index, rejects any mismatch in cockpit, scene, policy, or bundle closure, uses the reserved presentation occurrence and assignment, and still waits for the presentation receipt before reveal. An actual browser-to-core route test remains required before calling the path operational.

The shared fixture `fixtures/operational/session_launch_v1.json` now provides one exact Rust/TypeScript envelope. Glass reads those same fixture bytes in its contract test, rejects a noncanonical HTTP representation, and pins all three byte domains:

- exact protocol bytes: `sha256:e0ba94b70025608d151a77e983d9a4099dc8aeb19bb282cac94d33ef44569c63`;
- exact launch-registration bytes: `sha256:43372761a889a26422ca6a24fa84d42530ec8c48ca1a1fb7ea79c12f14b8d881`;
- exact trimmed outer session-envelope bytes: `sha256:589610ad2d07fd9a60763bf1cf82834d2c755716141e454bfef2ada41a1b152a`.

Core's existing prospective routes now reject absent or mismatched loopback `Host`/`Origin` and require browser Fetch Metadata `same-origin` / `cors` / `empty` before capability validation. This does not make the routes operational: the session route and strictly parsed choice routes still return `503` because no semantic durable writer exists. The one-time exchange route remains deliberately unmounted rather than minting a session from the static installation token.

Rust also froze separate `joshi.operator.explicit_abstention` V1 and its receipt. Glass mirrors the strict four reasons and the launch, cockpit, scene, presentation, assignment, as-of, universe, deadline and clock closure. The dedicated accessible form is warmup/deadline gated and remains pending until the exact durable receipt arrives; an ambiguous failure retries the identical reserved command bytes. It is not treated as an operator-command V2 variant, and missing input, a null selection, or an annotation can never count as abstention.

General V2 `nominate_candidate` is visibly disabled in prospective mode. It lacks the launch, as-of, universe-membership, and preregistered-deadline closure and therefore cannot qualify for the protocol. Rust now freezes the two branches separately: `joshi.operator.prospective_nomination` V1 and `joshi.operator.explicit_abstention` V1. The launch carries a nonempty, subject-ID-sorted `choiceMembers` array of exact `{subjectId,choiceUniverseDigest,membershipDigest}` rows and preregisters both contract IDs against one reserved command occurrence/idempotency key. Glass can only echo one of those server-issued membership rows; it cannot compute or add membership. Preparing either branch locks the other even across an ambiguous retry, and only its exact receipt counts as committed.

The exact Rust/TypeScript nomination request and receipt vectors are pinned:

- nomination request digest: `sha256:e1826827d4b2629b88e9b51af1d84cc3afffeb7bb07e7a756a758894556a320e`;
- nomination receipt-byte digest: `sha256:7dd5ce90b1a5ae882f81570c0b7adae5d9216302365616b5e1110a66b85b96a3`.

Glass still will not derive a choice from nullable selection, annotations, or an ordinary V2 command.

## Accessibility and restart behavior

- pairing and publication selection are ordinary labelled forms/lists with large targets and visible focus;
- the authority ceiling is literal and non-hideable;
- code input uses `autocomplete="one-time-code"`, no precision pointer interaction is required;
- density, semantic shortcuts, screen-reader headings, reduced motion, and text/table equivalents remain in the cockpit;
- “Choose publication” unmounts the current scene; “End session” clears capability, launch, index, and publication state;
- browser reload cannot restore pairing or silently restore a market scene.

## Verification

Run from `apps/glass`:

```sh
pnpm typecheck
pnpm test
pnpm build
```

Automated tests cover strict duplicate-key/bounds handling, same-origin rejection, fail-before-fetch scope checks, expiry/revocation clearing, one-time-code UI erasure, explicit no-latest selection, durable Rust digest bytes, exact shared session-envelope bytes, launch closure, noncanonical-session rejection, receipt-before-reveal, V2 presentation/publication binding, exact retry behavior, restart clearing, automated accessibility checks, the parameterless no-index prospective path, warmup/deadline-gated abstention, abstention retry byte identity, and the prospective-mode refusal to treat general V2 nomination as qualifying. The current Glass suite is 129 tests.

Still-open honesty gates:

- a typed one-time-code registry/exchange and capability/session binding. The exchange route is intentionally absent until that registry exists;
- store-resolved protocol/launch/presentation/membership writers and exact receipts for the parameterless session, nomination, and abstention paths. The mounted prospective routes remain explicit `503` shells;
- a semantic writer exercising the structurally distinct authenticated pairing `clientSessionId` and prospective-study `prospectiveSessionId` through durable readback;
- an attached real browser against the actual core for pair → explicit publication → snapshot → presentation scene → post-mount event → exact retry → restart → replay;
- attached screen-reader and visual QA. Automated DOM/axe checks do not substitute for either.
