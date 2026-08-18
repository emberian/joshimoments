# Wave 5 — scientific memory and retrieval boundary

Status: pure unverified semantic memory kernel delivered; the offline G0 store now retains one
exact censored fixture chain, while presentation capture, qualified outcomes, Glass transport, and
release materialization remain integration-owned.

The current kernel pass remains deliberately below research qualification. The sole store can now
append and reopen an eight-occurrence fixture prefix: scene-bound act, partial episode, hidden
replay, incomplete session close, partial knowledge with an explicit gap, missing/censored outcome,
retrospective replay, and interview disposition. The writer allocates queue/commit order under one
immediate transaction per append and reconstructs the exact prior kernel prefix. It explicitly
refuses `Complete` session close, `Closed` knowledge, and `Available` outcome at this fixture
authority ceiling. This is durable evidence of a censored chain, not a complete or known outcome.

Before promotion, the
store/Glass seam must mint a real reveal/outcome occurrence rather than treating the hidden replay
ID as the reveal relation, enforce `revealed_at <= retrospective.recorded_at`, and witness the
actual append/receipt clock so cross-append recorded/commit rollback cannot be hidden behind a
semantic occurrence-time order. Opaque replay bytes and provenance remain caller assertions until
the store resolves them.

## Contract ceiling

`joshi-scientific-memory` owns no store handle, renderer, network client, wallet, transaction
builder, submission path, fill inference, or economic authority. It defines strict, append-only
references and transitions:

```text
committed SceneRef -> PresentationOccurrenceRef or typed PresentationGap
                   -> immediately retained unverified OperatorAct
                   -> scene-qualified research admission (or refusal)
                   -> bounded Episode / two-pass Replay / typed closure
```

An act is retained immediately as an unverified semantic occurrence, including `mark`, `zap_intent`,
escape/manual-action declarations, and other time-sensitive intentions. The kernel does not mint a
store durability ACK. A missing presentation never blocks the act, but it produces a typed
`MissingPresentation` research refusal. A later matching presentation repairs the gap as a separate
append-only occurrence; it never rewrites the original. Scene-qualified admission also requires a
private store-resolved witness. Acts distinguish observational kinds from evidence-only action
intentions. `external_manual_execution_escape { reason }` is a bounded, reasoned declaration only;
no kind implies a transaction, fill, landing, or position effect. All DTO times use the positive,
canonical decimal-string `LogicalSessionTick` newtype from the session's logical timeline, never an
inferred wall-clock unit; this is frozen as `MEMORY_TIME_ENCODING`. `SceneRef.catalogCutoff` is a
distinct positive decimal-string `CatalogCommitSeq` newtype from the immutable publication catalog,
frozen as `CATALOG_COMMIT_ENCODING`; the type system and kernel never compare catalog sequence
values with session ticks. All stable IDs validate on deserialization (nonempty, unpadded, bounded,
and free of controls), and every outer occurrence DTO rejects unknown fields.

Assertions are optional and separate from the stable act: `verbatim`, `opaque`, and
`cannot_articulate` are preserved as distinct dispositions. Corrections and ontology versions
append with parent/version identities; the original utterance and act bytes remain immutable.

Episodes use bounded `partial_realization`, `runner_retention`, `full_exit`, `flat_watch`,
`reentry`, `no_trade`, `unknown_interval`, and `unresolved_effect` segments. Effect and lot state
are explicit (`Observed`, `Unknown`, `Unresolved`, or no-trade), never inferred from intent,
navigation, or a label. Store-witness prerequisites are mandatory for observed effects, resolved
lots, and complete status. Replay has explicit content role and visibility: hidden
`outcome_hidden_reconstruction` cannot carry a reveal, while a separate
`retrospective_interpretation` must name one. Session terminality, append sequence, knowledge
cutoff, outcome horizon, and typed gaps remain visible; outcome gaps do not become zeros.
Positive closure DTOs carry an explicit `qualification: unverified_semantic`; the pure kernel never
turns `Closed`, `Complete`, `Observed`, `Resolved`, or `Available` into a durable/store-qualified
claim. Closed knowledge and available outcomes additionally require the private store witness.
Episodes bind their session, existing act IDs, and decision cutoff. Session close refuses open or
post-cutoff episode segments, and a hidden replay must precede any outcome for that episode; a
retrospective reveal resolves the exact earlier hidden replay ID.

## Exact store ports

The sole catalog now implements the fixture-authority act, episode, replay, incomplete close,
gapped knowledge, censored outcome, retrospective replay, and interview append/readback waist.
The following remain the promotion contract and must not be inferred from that fixture path:

1. `joshi.store.scientific_memory_scene_ref.v1`: resolve `(scene_id, scene_digest,
   catalog_cutoff)` against an immutable committed Glass publication. Unknown or superseded scenes
   return typed refusal, never a substituted current scene.
2. `joshi.store.scientific_memory_presentation.v1`: append/read exact
   `PresentationOccurrenceRef` or `PresentationGap`, keyed by occurrence ID and exact digest.
   Presentation capture must not be a prerequisite transaction for an act.
3. `joshi.store.scientific_memory_act.v1`: append exact `OperatorAct` bytes immediately to the
   local durable queue, then atomically return a private store-owned receipt containing occurrence
   ID, exact digest, queue generation, and commit sequence. The kernel's `UnverifiedSemanticAct`
   is not this receipt. Same ID with changed bytes is an identity conflict; a retry after a crash is
   an idempotent duplicate.
4. `joshi.store.scientific_memory_correction.v1` and
   `joshi.store.scientific_memory_ontology.v1`: append corrections and ontology versions with
   visible parent IDs/effective cutoffs. No UPDATE/DELETE of an act or ontology label is allowed.
5. `joshi.store.scientific_memory_episode.v1`: append validated bounded segments and preserve
   partial/unknown/unresolved status, evidence digests, and unresolved lot association. Store
   witnesses are mandatory for observed effects, resolved lots, and complete status. It must reject
   inferred fill/transaction fields and cannot turn a no-trade segment into abstention unless an
   independently registered choice protocol says so.
6. `joshi.store.scientific_memory_replay.v1`: append hidden reconstruction before outcome reveal;
   append retrospective interpretation as a separate occurrence with reveal intervention and
   availability cutoff. Hidden artifacts must not reference later outcome evidence.
7. `joshi.store.scientific_memory_closure.v1`: append session-close, knowledge, outcome, and
   interview DTOs with exact contracts, horizon/deadline/cutoff ordering, typed gaps, and durable
   relations. The G0 implementation admits only explicitly nonclosed/censored fixture states; a
   closure receipt is not an economic result or a qualified outcome.

## Glass ports and golden relation

Glass should expose a read-only `SceneRef` plus a bounded presentation occurrence adapter. The
client may enqueue an act against the exact committed `SceneRef` before presentation capture
returns. The transport cache may retain opaque canonical act bytes and match only the private store
receipt `(act_id, exact_digest, queue_generation)`; it must not treat the kernel's unverified result
as durability or invent a scene, assertion, or presentation occurrence. A presentation gap is a
normal typed result, not a client failure.

Golden relation:

```text
SceneRef(scene-1, sceneDigest, cutoff=10)
  + PresentationGap(gap-1, capture_failed)
  -> OperatorAct(act-1, mark, immediately retained/unverified)
  -> ResearchAdmission(refused: missing_presentation)

later PresentationOccurrenceRef(pres-1, scene-1, renderDigest) + private store witness
  -> ResearchAdmission(admitted: scene-1/pres-1)
```

The exact fixture is `fixtures/scientific-memory/adversarial.v1.json`, including a complete
canonical OperatorAct byte string and SHA-256 digest for the manual-escape/gap case. Golden tests
must assert
that the first act remains byte-identical, the later presentation does not rewrite it, and hidden
reconstruction cannot observe retrospective outcome data.

## Fault/restart walk

Crash after scene read, presentation-gap append, act queue fsync, queue receipt readback, correction
append, and closure append. The G0 component now injects immediately before and after its six-event
censored closure and proves exact eight-event queue convergence after reopen. Replay must produce
either the prior complete prefix or the same exact
new occurrence; never a missing act, mixed scene/presentation pair, inferred fill, or hidden replay
with future information. A failed presentation capture opens a gap while preserving ordinary product
use and the durable act.
