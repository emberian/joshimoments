# Wave 6 — operator-model prototype

Status: isolated, deterministic evidence-contract prototype. It implements the
boundaries in [the Wave 6 operator-model program](../../research/wave6/03_OPERATOR_MODEL.md);
it is not a taxonomy service, perception model, advisory system, or execution path.

## Scope

`analysis/src/joshi_analysis/wave6_operator_model` contains frozen Python value
objects and deterministic SHA-256 artifact digests. It neither writes a store nor
modifies Wave 5 scene, presentation, act, replay, or effect owners. IDs in this
package are references to those owned artifacts.

`store_input.py` also accepts the artifact-bearing Core V22 operator-evidence report. It enforces
the exact Rust field order, physical document/memory/browser-claim digests, browser-claim
self-digest, store binding identity, commit order, act/scene/gap/subject/publication lineage, and
every negative qualification bit. The returned validated packet is private to the parser rather
than a caller-constructible qualifying DTO, and it is not a `SceneBinding` or `OperatorAct`: V22
preserves the act's original presentation gap, while the later browser report is separate evidence
and contains no recognition response. The parser therefore fixes
`model_admission_refusal=unrepaired_w5_presentation_gap_and_no_recognition_response` and leaves
scene binding, replay, human viewing, recognition, and operator-model resolution false.

The package fixes these separations:

- `RawOperatorAssertion` preserves either exact `raw_bytes`, an opaque token, or
  an explicit response state. `ambiguous`, `cannot_articulate`, `no_response`,
  and `not_asked` remain distinct. A correction is a new assertion with a link
  to the earlier ID, never a rewrite.
- `SceneBinding` binds every capture to typed scene, view, presentation (or
  typed gap), and optional choice-context artifacts. Each reference retains its
  exact ID, version ID, canonical content digest, and available commit sequence;
  the binding also retains its occurrence/availability clocks. If presentation
  evidence is not adequate, it requires a versioned, content-addressed
  `TypedGap`; it cannot substitute the current UI.
- `ComponentBundle` is a sorted set of heterogeneous `ComponentAssertion`
  records. Every applicable component names its asset, unit, reference measure,
  topology/profile, occurrence/availability clocks, cut, and coverage. There is
  deliberately no pressure field, score, ordering, or aggregation API.
- `OperatorAct`, `StatedIntention`, and `ReconciledEconomicEffect` are distinct
  artifacts. Intentions have evidence-only fields and cannot reference effects.
  Effects require external observation, reconciliation, finality, account
  boundary, exact atom deltas, and source digest.
- `OntologyTerm`, `OntologyAssignment`, and `OntologyRelation` are append-only,
  versioned interpretation objects. Split/merge relationships are many-to-many;
  a retired term stays addressable. An assignment can be ambiguous or multi-term
  and is never a truth label.
- `ReplayProtocol` has separate blind/reveal cuts and disjoint hidden/revealed
  references. Each `ReplayEvidenceRef` has a typed artifact identity, exact
  version ID, canonical content digest, availability/knowledge cut, and commit
  sequence. The protocol fixes blind/reveal cut *and* commit boundaries.
  `materialize_replay` accepts only the protocol's exact ordered material tuple;
  an ID with substituted version, digest, bytes, type, cutoff, commit, or order
  is refused. It emits a phase-specific
  `ReplayMaterialReceipt` only when its exact protocol digest, scene/presentation
  binding digest, phase cut/commit, and phase-specific evidence closure agree. An
  outcome-blinded receipt contains only blind material and must be presented
  strictly before reveal; an outcome-aware receipt includes the declared reveal
  material and cannot be presented before the exact reveal cut.
- Every `RecognitionResponse` names the exact material and phase-receipt digests
  it was recorded against. `compare_recognition` revalidates those receipts and
  rejects a phase label that differs from its receipt, another replay/scene,
  mismatched material, a response before presentation, a blinded response at or
  after reveal, or an outcome-aware response before reveal. It summarizes
  response states only; its fixed claim scope explicitly disallows label truth
  or private-state conclusions.

## Clock closure

All authored times are timezone-aware UTC-normalized. A scene/presentation
binding, referred evidence, or component whose `available_at` postdates its
knowledge cut fails closed with `TemporalClosureError`. Replay refuses a scene
that was unavailable at the blind cut or whose binding commit is newer than its
blind commit. It also refuses material whose availability/knowledge cut or commit
postdates the corresponding blind/reveal boundary, then recomputes the ordered
material digest before it will count a response. This is intentionally
conservative: this prototype does not reconstruct missing availability
information.

## Determinism and non-authority

`deterministic_digest` canonicalizes a complete frozen artifact, including raw
bytes (as hex) and clocks, to qualified SHA-256. The output is reproducible for
the same data but is only an integrity handle; it does not confer source truth,
causality, economic value, or action authority.

The receipt closure is an intrinsic check over caller-provided values, not a
store-resolved proof that material was rendered, revealed, or comprehended.
IDs, versions, digests, cuts, commits, and receipt strings therefore remain
unverified semantic input until a separate owner supplies durable scene,
presentation, rendering, and response receipts. Neither recognition nor an
ontology assignment is label truth.

The V22 adapter is a narrower exception to the generic caller-fed input statement: it validates an
artifact-bearing report emitted after sole-store readback. That raises only the evidence-input
ceiling. It still cannot fill the Python model's missing versioned view/presentation material or
prove that a person viewed or recognized anything, so it deliberately refuses model admission.

Focused adversarial tests cover future-cut leakage, forced taxonomy, append-only
correction, unit/topology clock collapse, assertion/effect conflation, typed
presentation gaps, scalar-pressure laundering, replay phase labels after/before
reveal, replay receipt/scene/material substitution, and same-ID material
version/content-digest swaps.

The cross-runtime tests additionally reject duplicate/reordered JSON, scalar substitution,
positive human/model qualification, replacement of the original gap, and omission of the act
subject from the later browser report.
