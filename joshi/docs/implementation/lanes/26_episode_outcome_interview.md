# Lane 26 — prospective episode close, knowledge, outcome, and interview

Status: **strict V1 leaf contracts and exact abstention goldens complete; store/core/export/live
integration absent**.

Authority: `read_only_no_execution`. Economic claim: `none`.

This lane closes the contract-design part of W4-11 blocker 5. It does not close the operational
blocker. The root Wave 4 status remains `useful_partial`, no prospective episode has run, and none
of these fixtures is a store receipt or an operational witness.

## 1. Frozen decision

The launch already preregisters `joshi.episode.outcome` and `joshi.episode.interview`. Those names
remain canonical. This lane does not mint parallel “outcome at horizon” or “interview disposition”
names. It adds the two missing predecessor contracts whose names were not previously frozen:

| artifact | contract | identity semantics |
| --- | --- | --- |
| session close | `joshi.episode.session_close` V1 | fresh producer occurrence `sessionCloseId`; it was not preregistered and cannot impersonate a launch reservation |
| knowledge cut | `joshi.episode.knowledge_closure` V1 | fresh producer occurrence `knowledgeClosureId`, one-to-one with the reserved outcome occurrence |
| outcome at `H` | `joshi.episode.outcome` V1 | exact launch `reservedOutcomeId`; the later content artifact ID is the SHA-256 of exact bytes and is not a second outcome occurrence |
| interview disposition | `joshi.episode.interview` V1 | exact launch `reservedInterviewId`, including explicit decline and not-offered states |

All four use strict camelCase JSON, `schemaVersion: 1`, exact six-microsecond UTC instants,
algorithm-qualified lowercase SHA-256 digests, canonical unsigned decimal strings, bounded stable
identities, duplicate-key rejection, unknown-field rejection, and a one-MiB parser ceiling.

The implementation is the leaf crate [`joshi-episode-closure`](../../../crates/joshi-episode-closure/src/lib.rs).
It depends on the current admission types rather than cloning protocol, launch, scene,
presentation, nomination, or abstention DTOs. It has no store handle, network client, source
client, wallet material, transaction builder, signer, submission path, or mutation authority.

## 2. One checked episode basis

Every artifact carries one `EpisodeBasisV1`. Repetition on the wire is intentional defensive
closure, not a competing source of truth: `validate_against` resolves every field against exact
protocol, launch, launch receipt, presentation receipt, command bytes, and command-receipt bytes.
It checks:

- protocol registration ID, exact protocol digest, and registered privacy digest;
- launch ID, exact launch-byte digest, prospective session ID, `T0`, `T_end`, `H`, and `K`;
- launch catalog cutoff, census artifact ID/digest, cockpit publication ID/digest;
- witnessed scene/view, presentation ID/digest, assignment, as-of, and choice-universe digests;
- exactly one durable nomination or explicit-abstention command and its exact receipt bytes;
- launch-reserved hot decision and hot intent IDs; and
- launch-reserved outcome, interview, export-request, analysis-run, and artifact-import IDs.

The timing equations are inherited from the actual `EpisodeProtocolRegistrationV1`, not copied as
new policy:

```text
T_end = T0 + duration
H     = T0 + outcomeHorizonOffset
K     = T0 + knowledgeDeadlineOffset
T0 < T_end < H < K
```

Standalone parsing validates syntax and monotonic ordering. Only `validate_against` establishes the
semantic basis. A structurally valid caller-authored basis is never durable evidence.

### Choice closure

`ChoiceClosureV1` is a tagged union. The nomination branch retains the exact
`ChoiceMembershipReferenceV1`; the abstention branch retains one of the four existing frozen
reasons. Both bind:

```text
command occurrence ID
+ SHA-256(exact command bytes)
+ receipt batch ID
+ SHA-256(exact receipt bytes)
+ receipt commit sequence
```

The validator calls the existing command `validate_against` and receipt `validate_against`. A
general operator command, null choice, timeout, matching string without matching bytes, or opposite
branch cannot qualify.

## 3. Session close

`SessionCloseV1` records what happened at the contemporaneous boundary; it does not decide whether
the episode passed. Its finite states preserve failure:

- completion is `complete_on_schedule`, `incomplete_early`, or `incomplete_late`, derived from the
  exact `closedAt - T0` duration;
- source support is satisfied only when the non-fixture occurrence count is positive;
- spool close is catalog-admitted, backlog-recorded, or unresolved;
- budget is within, exceeded, or indeterminate; and
- presentation closure retains exact event receipt references, visibility gaps, and an open-
  interval count. An on-schedule close cannot claim open intervals.

At least one source receipt or scoped gap is required. Every source and presentation reference is
available no later than `closedAt` and committed no later than `closingCutoffCommitSeq`. The closing
cut cannot precede the qualifying choice receipt.

The final contemporaneous scene and witnessed replay are immutable artifact references. The only
allowed outcome visibility is `not_revealed`.

### Hot disposition

An abstention closes both launch-reserved hot IDs as `not_applicable_by_abstention`; it emits no
fake intent. A nomination must keep the exact chosen subject and reserved IDs, and may reference:

- one exact policy-decision evidence occurrence keyed by `reservedHotDecisionId`;
- one `joshi.hot_scope_intent/v1` artifact produced under `reservedHotIntentId`; and
- sorted desired/applied/degraded/closed artifacts from the existing acquisition-policy contracts.

`closed` requires an actual `joshi.hot_scope_closed/v1` record. Applied still does not mean provider
acceptance or coverage. The acquisition-policy `PolicyDecisionV1` currently has no contract header,
so this lane deliberately uses a digest/availability/commit evidence reference for that object; it
does **not** invent a nonexistent `joshi.hot_scope_decision/v1` contract.

## 4. Knowledge by `K`

`KnowledgeClosureV1` freezes the selection of `C_retro` separately from the later outcome. It uses:

```text
event window             [T0,H)
retrospective state time H
knowledge deadline       K
```

The catalog cut is the greatest commit durable by `K`. It requires one of two constructive proofs:

1. the immediate successor commit exists and its commit time is after `K`; or
2. the selected commit was the catalog head when observed at or after `K`.

The selected commit time must be at or before `K`, and cut selection cannot occur before `K`.
Every event/state evidence reference must have `availableAt <= K` and `commitSeq <= C_retro`.

Event time remains typed:

- a point is included only when `T0 <= at < H`;
- a bounded half-open interval is included only when wholly contained in `[T0,H)`;
- a boundary-crossing bounded interval is `interval_censored`; and
- an unresolved interval retains at least one known bound and is always `interval_censored`.

No endpoint snapping, later-valid correction, or merely-late-available event can enter. Coverage and
gap IDs are sorted and at least one must exist. State at `H` remains available, missing,
conflicting, or unsupported.

## 5. Outcome at `H`

`OutcomeAtHorizonV1` references exact admitted session-close and knowledge-closure bytes. Their
content-derived `artifactId` and `artifactDigest` must both equal SHA-256 of the bytes, while the
producer occurrence remains separate. The outcome cannot be produced before `K` or before the
knowledge cut was selected.

The contract deliberately contains no duplicate decimal financial truth. It refers to immutable
producer artifacts for:

- retrospective scene;
- lifecycle/venue state;
- mark evidence;
- exact-size quote or typed refusal;
- whole-position quote or typed refusal; and
- an independently observed finalized external wallet effect, whose intent must remain `unknown`.

Missing, conflicting, unsupported, not-requested, refused, and abstention-not-applicable are typed
states. A nomination must retain the exact membership row. An abstention must have no selected
subject and every exposure-bearing component must be `not_applicable_by_abstention`.

Coverage/gaps must exactly equal the knowledge closure, and `censoringPresent` is derived from
interval censoring or gaps. Interpretation is the fixed literal
`descriptive_non_profit_no_win_loss`. There are no peak-ever, hindsight exit, simulated PnL,
strategy score, trade, or win/loss fields.

## 6. Interview disposition and private artifacts

The reserved interview occurrence always ends in exactly one state:

- `declined`;
- `not_offered_due_to_gap` with a nonempty sorted gap set; or
- `recorded` with one mandatory outcome-hidden segment and an optional outcome-aware segment.

Disposition cannot predate `T_end`. The hidden segment binds the witnessed scene, exact choice
commit as its information cutoff, prompt digest, times, and a local text-blob reference. It must
close before any outcome-aware segment begins. Outcome reveal cannot precede `K`, and an aware
segment must close the exact outcome bytes and a distinct retrospective scene.

V1 permits only blob metadata with:

```text
contentType = text/plain;charset=utf-8
protection  = operator_private_local_only
retention   = hold_no_automatic_deletion
exportPolicy = metadata_only_no_text
```

Text bytes do not appear in these fixtures or public export. Audio, video, microphone, screenshot,
screen recording, remote copy, and external model use remain disabled. The interview private-policy
digest must equal the protocol registration's privacy digest.

## 7. Exact vectors and adversaries

Repository files have one conventional terminal LF. The canonical payload is the file content
excluding that single LF; no other trimming or normalization is permitted.

| vector | canonical bytes | SHA-256 |
| --- | ---: | --- |
| [`session_close.v1.json`](../../../fixtures/episode-closure/session_close.v1.json) | 3,749 | `sha256:b12a6286255eb9710390f1114b3aefac56c6fd607fa0f9c49c36d1862fbbee8e` |
| [`knowledge_closure.v1.json`](../../../fixtures/episode-closure/knowledge_closure.v1.json) | 3,402 | `sha256:4eb1e51903d95a7dabf7a19c8d58ccf012991a45577e4460b253eb5970449d51` |
| [`outcome_at_horizon.v1.json`](../../../fixtures/episode-closure/outcome_at_horizon.v1.json) | 3,391 | `sha256:e4c8cd094e98565506e9f5418251bb393f61390e6dcb701d73b595030a27746d` |
| [`interview_disposition.v1.json`](../../../fixtures/episode-closure/interview_disposition.v1.json) | 2,687 | `sha256:41a775288fa3a43d3035b14dded07f7c463717f858bd530080807d22a2e86ed7` |

The canonical fixture is intentionally an abstention. It proves that instrument closure does not
need a trade, profit, selected subject, quote, or fabricated exposure. Nomination/hot closure and a
recorded two-pass interview are exercised independently in tests.

[`adversarial.json`](../../../fixtures/episode-closure/adversarial.json) names the enforced refusal
matrix: duplicate/unknown keys, authority escalation, future knowledge, boundary snapping,
abstention exposure, bad head proof, hot reservation or subject substitution, false closed state,
early outcome reveal, audio blob, content-digest substitution, and noncanonical integers.

Focused gates:

```text
cargo test -p joshi-episode-closure --locked                    # 8 passed
cargo clippy -p joshi-episode-closure --all-targets --locked \
  --no-deps -- -D warnings                                     # green
RUSTDOCFLAGS='-D warnings' cargo doc -p joshi-episode-closure \
  --locked --no-deps                                           # green
```

## 8. Exact integration seam for store/core

This lane freezes artifacts, not receipts, tables, routes, or authority capabilities. Current plans
do not name those receipt contracts, so inventing them here would create a second root truth.
The infra-owned semantic adapter must:

1. strict-parse exact artifact bytes before persistence;
2. resolve the protocol, launch, presentation, scene, census, publication, source, choice, hot, and
   prior-artifact references from durable store rows—never trust caller-supplied parallel fields;
3. call the relevant `validate_against` method using exact stored bytes;
4. derive content digests and all indexes itself;
5. enforce one exact/idempotent session close per prospective session, one knowledge closure and
   outcome per reserved outcome occurrence, and one interview disposition per reserved interview
   occurrence;
6. retain same-ID/different-body attempts as refusal evidence and never overwrite accepted bytes;
7. select `C_retro` under a store transaction at/after `K`, proving either head-at-selection or the
   immediate post-`K` successor;
8. admit the hidden interview segment before any outcome reveal and preserve operator-private
   protection outside public logs, metrics, exports, and remote replication;
9. issue a distinct durable receipt whose digest domain explicitly names exact artifact bytes,
   semantic basis, commit, status, and catalog schema; and
10. keep core mutation routes disabled until this store-resolved adapter and pairing/session
    binding exist.

The adapter must not expose the crate's structs as a public capability constructor. Exact parsing
is necessary but not sufficient: persisted row resolution is the authority boundary.

### Export seam

Current Snapshot V2 has no lossless protocol/launch/session/choice relation set. Its existing
candidate/territory tables cannot be synthesized from membership IDs. Therefore these artifacts
must continue to make the prospective export fail closed until a reviewed snapshot successor adds
the required relations and provenance. Coverage rows may be exported only where V2 represents
their clocks and recovery state without substitution; that is separate from episode closure.

## 9. What remains open

- no V7/V8 table or migration stores these objects;
- no store semantic writer or durable receipt admits them;
- no core route produces or reads them;
- no production exporter maps them;
- no cross-runtime TypeScript/Python mirror exists;
- no non-fixture source, real `C_retro`, attached browser, outcome, interview, or Ember session was
  run; and
- no root witness consumes these artifacts.

Consequently this lane is **typed contract/reducer plus exact fixture**, not implemented-and-
walking. It removes the arbitrary outcome/interview-string ambiguity from the next integration
step, but it cannot upgrade the terminal root `useful_partial` verdict.
