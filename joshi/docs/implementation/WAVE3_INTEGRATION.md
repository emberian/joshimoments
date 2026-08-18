# Wave 3 integration review

Status: **live cross-lane review; read-only, evidence-only, and pre-authority**
Reviewed: 2026-08-16

## 1. Integration judgment

Wave 3 should not become one large “market field” object. Its coherent architecture is an
append-only evidence spine followed by several typed, point-in-time interpretations and then a
witnessed product/operator loop. Wallet topology, social identity, attention, financial
projection, fitted response models, Ember's perceptions, and presentation policy can inform one
another, but none is a substitute for another. In particular:

- a chain address is not a person, a cluster, or a strategy;
- a social callout is an observed marked event, not a treatment or a cause;
- a conditional response kernel is a fitted estimate, not mechanical impact;
- a heatmap is a rendering, not a physical pressure field;
- what Ember reports perceiving is not the machine's latent field estimate;
- an intended ranking policy is not evidence of what was rendered; and
- an observed later return is not information that was available at the choice.

The useful unification is therefore a dependency graph and a common cutoff calculus, not a common
row type. Every cross-lane result must identify its authority class, occurrence identity, semantic
contract/version, exact input closure, event/valid interval, knowledge availability, coverage,
and correction or supersession relation. Anything that cannot supply those items stays a research
notebook result and cannot enter a witnessed scene or policy input.

No Wave 3 path constructs, signs, submits, or rebroadcasts a transaction. “Choice,” “policy,” and
“action” below describe recorded decisions or read-only presentation interventions unless a later,
separately authorized execution design says otherwise.

## 2. One dependency graph

```text
provider / chain / Pump response occurrences
        |
        v
acquisitions + exact observations + coverage/gaps
        |
        +------------------------------+
        |                              |
        v                              v
versioned semantic assertions     finalized settlement / protocol facts
        |                              |
        +----------+-------------------+
                   |
                   v
       bitemporal topology and attention projections
       (wallet, social, lifecycle, territory, callout)
                   |
        +----------+-------------------+
        |                              |
        v                              v
deterministic read projections      immutable analysis snapshot
(accounting/quote/LP, H0/H1/H2)          |
        |                               v
        |                      fitted kernels / machine fields
        |                         (H3/H4 estimates)
        +---------------+---------------+
                        |
                        v
              content scene / Glass view
                        |
                        v
      policy definition -> assignment -> staged presentation plan
                                             |
                                             v
                                 actual render observations
                                             |
                                             v
                       operator perception / gesture / annotation
                                             |
                                             v
                         choice set -> choice or abstention
                                             |
                                             v
                       later action fact / outcome / censoring
                                             |
                                             v
                         manifested point-in-time research export
```

This graph has three important non-edges. Analysis artifacts do not write back into observation or
assertion tables. An intended policy does not write what the client actually rendered. A later
outcome does not update the historical scene, operator perception, or choice; it is joined only in
a retrospective/export view whose separate outcome cutoff permits it.

The graph is acyclic at artifact level even though the operating process learns over time. A new
model or policy is a new versioned artifact derived from prior closed exports. It affects later
assignments and scenes, never the bytes or meaning of an earlier artifact.

## 3. Canonical object vocabulary

The following nouns are disjoint contract families. A discriminating enum inside a generic metric
does not create enough separation where inputs, validation, provenance, or permitted claims differ.

| Object | Canonical meaning | Required closure | Explicit non-claim |
| --- | --- | --- | --- |
| **acquisition** | one source-access occurrence, even when equal bytes appeared before | source/variant, request or stream occurrence identity, clocks, fidelity/protection, exact payload or named loss, gap linkage | not a semantic market event |
| **observation** | retained evidence of bytes, state, UI geometry, or an occurrence under a declared observation boundary | acquisition and observation IDs, event-time interval if justified, observed/available time, source-event relation, coverage and retention | not automatically true of the world |
| **assertion** | a versioned semantic claim supported by observations | semantic key, producer/version, evidence closure, valid interval, available/known order, status, supersession/conflict/retraction | not raw evidence and not necessarily final |
| **protocol or settlement fact** | decoded chain or program result at a named closure/authority rung | exact transaction/state locator, program/profile, assets/units, finality/canonicality, observation closure | provisional chain data is not finalized settlement; pure quote math is not a fill |
| **deterministic projection** | reproducible transformation of effective assertions/facts under one exact cutoff | calculator build/config/schema, input IDs/digests, as-of vector, coverage, exact units, correction lineage | not a source fact or causal estimate |
| **latent estimate** | fitted or abductive model output, including machine field or cluster hypotheses | estimator/method version and build, immutable input snapshot/digest, fit and availability cutoffs, support/coverage, uncertainty, claim scope, alternatives/falsifiers when abductive | not an observation, identity, mechanism, or causal effect |
| **operator perception** | Ember's recorded report or annotation about what seemed present in the witnessed context | scene and presentation binding, exact gesture/utterance/annotation evidence, client clocks, provisional/correction status | not a machine estimate and not market truth |
| **content scene** | immutable semantic Glass view at one full as-of vector | scene ID, exact `view_bytes` and digest, mode, source/projection watermarks, semantic content membership and order | not proof of actual pixel exposure or attention |
| **presentation intervention** | a prospective assignment plus the separately observed display realization it caused | policy version/digest, assignment, scene/view binding, staged manifest, post-render ordered/visibility/viewport observations, omissions, client occurrence clocks | intended or pre-render `surfaced`/`rendered` fields are not actual exposure; viewport is not gaze |
| **choice context** | the honest alternatives and information available for a decision | witnessed scene and presentation, eligibility/surface/render/viewport/compare sets, exact universe digest, abstention availability | not the entire market unless census coverage establishes that claim |
| **choice** | a selected subject/action disposition or explicit abstention at that context | choice-context identity, command occurrence, scene/presentation binding, issued/available times | not a landed trade or proof of hidden intent |
| **outcome** | a later measured event/result or explicit censoring state | outcome definition, horizon/risk set, event and available times, competing-event/censoring state, coverage | never a contemporaneous feature merely because its event time is earlier than export time |
| **policy artifact** | a prospective mapping/ranking/controller definition | policy ID/version/digest, build/config, eligible inputs, support/safety envelope, assignment mechanism | not observed behavior, safe execution authority, or evidence that assignment rendered |

Use **event** only for an occurrence with a declared universe and locator. Use **fact** only with a
named closure. Use **field** only for a typed quantity indexed by domain, clock, observation policy,
unit, and authority rung. Use **episode**, **inventory epoch**, **lot**, and optional **management
tranche** with the meanings already frozen in the accounting vocabulary; none is renamed to a
topology or response “epoch.” A `topology_epoch` or `regime_epoch` is a model stratum label, never
an operator inventory epoch.

### 3.1 Human and machine configurations are siblings, not variants

Two superficially similar heatmaps need separate contracts:

```text
OperatorPerceptionV1
  -> scene_id + view_digest
  -> presentation_id + presentation_digest
  -> gesture/annotation/utterance occurrence
  -> operator label, anchors, provisional/correction status

MachineFieldEstimateV1
  -> estimator_id/version/build/config_digest
  -> input_snapshot_id + logical_digest
  -> fit/as-of/maximum-training-availability cutoffs
  -> domain/clock/unit + support/coverage
  -> value + uncertainty + claim_scope
```

They may later be compared by a third study artifact. They do not share `ExactMetric<T>`, one
`field_kind`, one evidence class, or one primary key. A model agreeing with Ember does not turn the
perception into an observed market field; Ember drawing a pattern does not validate a fitted latent
state.

## 4. The point-in-time join rule

Every historical join must state both axes:

```text
eligible(version, query) :=
    version.available_at <= query.knowledge_cutoff
    and query.event_slot/time is inside version.valid_interval
    and version is the effective non-superseded branch as known at that cutoff
```

For a chain fact, `query` additionally declares accepted finality/canonicality and the fact's slot
must not exceed the queried slot. Dependent transfers, swaps, bundles, LP events, and caller roles
bind a specific transaction-fact version; they do not join on a natural signature and silently
inherit a later canonical version.

For an identity, territory, cluster, or coordination hypothesis, a current dimension-table join is
forbidden. Selection uses the exact version available then, whose slot and wall validity contain
the historical query. A later attribution can appear in a retrospective view only under that
view's knowledge cutoff and must still be labeled later-known. Retraction remains visible as a
retraction but does not act as active membership.

For a response or outcome:

```text
outcome.event_time <= declared horizon
and outcome.available_at <= analysis_outcome_cutoff
and follow-up coverage supports the measurement
```

No row, mark, target, regime label, topology label, identity class, or censoring decision may use a
future-known value merely because its claimed valid/event time precedes the decision. Missing
follow-up is censored or unknown, never zero. Competing events terminate or alter the risk set under
a named rule. A witnessed-complete sample additionally requires exact choice-universe and
presentation closure; a general attention event must not fabricate scene, wallet, territory, size,
or decision IDs to enter that subset.

## 5. Presentation and witnessed choice

The frozen `joshi.glass.view` V1 remains the semantic content scene. Wave 3 must not add policy,
dwell, or model-study fields to that byte contract. Presentation is a sibling occurrence:

1. `PolicyDefinitionV1` freezes prospective ranking/filter/toggle behavior and its digest.
2. `PolicyAssignmentV1` binds a policy version to a client/session/scene occurrence and records the
   assignment mechanism or stratum.
3. `joshi.presentation.scene` V1 binds an opaque `presentation_id`, client session/sequence,
   `{scene_id, view_digest}`, policy/assignment identity and digest, and a canonical staged
   eligible/intended-surface manifest. Every omitted eligible item has a typed reason. Its digest
   is derived by the receiver over exact canonical bytes. The fields are deliberately named
   `selectedItemIds`, `plannedRenderItemIds`, and `plannedInitialViewportItemIds`; none claims
   empirical exposure.
4. Append-only `joshi.presentation.event` occurrences record post-render visibility transitions,
   focus, filter/toggle changes, and dwell interval boundaries against
   `{presentation_id, presentation_digest, scene_id, view_digest}`. Aggregate dwell is a derived
   assertion, not a field in the immutable initial scene.

If the aim is a witnessed choice experiment, the client stages both content scene and presentation
artifact before reveal and reveals only after exact durable acknowledgement. Failure produces a
loud presentation-coverage gap; it does not silently continue as witnessed-complete.

The existing `joshi.operator.command` V1 is frozen and binds only scene/view. Adding presentation
fields under the same contract/version would invalidate its cross-language golden. A future command
that claims witnessed presentation must therefore be `joshi.operator.command` V2 or have a
separately admitted exact command-to-presentation binding. Until that version exists, V1 commands
remain useful semantic marks but are not presentation-complete choices.

## 6. Ranked architecture decisions

### P0 — required before claiming a Wave 3 walking path

1. **Make the cutoff calculus executable, not documentary.** Every topology, attention, scene,
   response, presentation, command, and export adapter must run the two-axis predicate in section
   4. Cross-lane tests must contain a later-known identity/cluster/pool correction whose claimed
   validity overlaps an old event and prove it cannot enter the old as-known result.
2. **Finish one exact source-to-store boundary.** Source-local envelopes remain source contracts;
   `joshi.durable_ingest_batch.v1` remains the sole store semantic input. Core derives the durable
   batch and its logical digest, store derives a distinct admission digest, and a recursively closed
   receipt reports durable readback. Ingress, durable logical, and store admission digests cover
   different named preimages and are never compared as if interchangeable.
3. **Admit scenes, commands, and exports through private-field typed capabilities.** Structural
   store methods may not remain public bypasses accepting opaque bytes plus independently supplied
   indexes. The adapter parses exact bytes, derives all duplicate indexes, resolves evidence and
   projection references at the cutoff, then hands persistence an unforgeable validated value.
4. **Choose one owner for temporal wallet/topology truth.** Acquisition retains raw responses and
   source-normalized provisional rows. The topology reducer owns versioned transaction facts and
   dependent flows. Natural transaction ID/signature does not pick a version; every dependent fact
   names `transaction_fact_id`. Later identity/cluster hypotheses stay versioned assertions, never
   become address properties.
5. **Freeze the presentation cut before calling a choice witnessed.** Content view, policy,
   assignment, staged render plan, post-mount realization events, and later interaction events are
   separate artifacts. V1 operator commands lack presentation binding, so no study may mark them
   `witnessed_presentation_complete` until the versioned binding exists.
6. **Make export the sole bridge into estimation.** Rust/store emits and registers one closed
   manifest and Parquet part set at an exact as-of vector. Python rejects unregistered or
   mismatched parts and publishes new immutable artifacts. No Python model reads the mutable
   catalog or writes an assertion back into it.
7. **Ship one root offline readiness command.** Component tests and attractive fixtures do not
   close the P0 joins. One clean, network-denied fixture must traverse acquisition, durable store,
   point-in-time topology/projection, exact Glass scene, semantic command, presentation evidence,
   export, and one descriptive kernel artifact while proving the no-authority capability closure.

### P1 — required before a human session becomes research-grade

8. **Keep response artifacts descriptive.** The canonical row family is a general marked event,
   long-form through-cut marks, separately covered response bins, and explicit risk/cohort rows.
   Operator choice, wallet attribution, territory, community, venue, lifecycle, and size are
   optional relations with explicit missing/status meaning; they are not sentinel IDs or zeros.
9. **Keep exact finance narrower than the live cockpit.** Finalized accounting and exact
   profile-bound calculators can populate a deterministic projection. Provisional current state,
   stale quote, intended action, full liquidation, landed fill, and later response remain different
   artifacts. A whole-position quote is not a fill, a marginal mark is not liquidation, and
   “fresh” requires a state/route/clock validity contract rather than visual recency.
10. **Log product reflexivity.** Provider ranking, JOSHI ranking, artifact order, viewport,
    focus/dwell, filters, toggles, omitted items, and model version are features of the observation
    and operator process. They are not harmless market covariates. Any panel or policy change starts
    a new composite-policy regime.
11. **Require promoted model manifests.** H3/H4 artifacts name occurrence ID separately from
    content digest, estimator/method/version/build/config/schema, input snapshot/logical digest,
    train/fit/as-of/outcome-availability cutoffs, topology/regime versions, coverage/support,
    uncertainty, baselines, negative controls, and claim scope.

### P2 — useful only after the above closes

12. Begin model work downstream in Python/DuckDB/Arrow. NumPy/SciPy, NetworkX, statsmodels, and
    scikit-learn enter one named locked experiment at a time. A graph database, Rust ML framework,
    generic “field engine,” or specialized Hawkes/Hodge/JAX stack does not belong in acquisition,
    evidence, store, or accounting.
13. Promote small computation to Rust only for a measured online serving need with byte/schema
    goldens against the research artifact. Keep stable project IDs out of library node indices,
    and keep Parquet rather than pickle/framework checkpoints as the durable boundary.
14. Do not add a canonical `pressure`, `viscosity`, `vorticity`, `temperature`, `turbulence`,
    `criticality`, or `market energy` feature. Native quote, capacity, flow, coverage, topology,
    and response components remain useful even if every analogy and fitted operator fails.

## 7. Duplicate and lossy cross-boundary truths

| Duplicate truth | Canonical owner | Required adapter/check |
| --- | --- | --- |
| provider response versus normalized source record | exact observation owns bytes/fidelity; source adapter owns a provisional assertion | normalized value retains source occurrence and observation; lossy attestation never claims provider-exact bytes |
| source `RawTransactionFact` versus topology `TransactionFact` | source row is provisional decode; topology version is query truth | record deterministic mapping and input observation; preserve finality/canonicality revision rather than overwrite |
| source `PublicKey`, domain `AccountId`, and social wallet link | canonical address bytes under network namespace; typed role/assertion owns meaning | checked reversible identity adapter; no ownership inference from conversion |
| natural signature versus `transaction_fact_id` | signature identifies transaction lineage; fact ID identifies a version | every flow/swap/bundle/LP fact binds exact version; current signature lookup is forbidden in historical joins |
| social identity, profile-wallet relation, and wallet cluster | identity assertion and cluster hypothesis are separate version series | downstream refs retain exact version/digest, validity, availability, status, evidence, and alternatives |
| copied cluster/territory fields in attention rows | topology/social artifact owns version | attention row stores selected version reference plus as-known proof; never a context-free label copied from current state |
| event time in shared evidence and attention | shared event interval is the convention | one endpoint rule—checked half-open `[lower,upper)`—and one exact-precision cross-crate golden |
| `scene_id`, view bytes, view digest, and as-of indexes | exact canonical view bytes are semantic authority | typed adapter derives digest/indexes and proves store/source/projection closure; caller does not supply duplicate truths |
| presentation policy, assignment, and actual display | each is a distinct immutable occurrence | policy digest, assignment ID, actual manifest digest, and receipt are all checked; intent never populates actual exposure |
| viewport/focus/dwell | client events own transitions; aggregates are derived | nested set and interval validation, monotonic clock domain, coverage gaps; viewport is not gaze |
| attention event rows and Python kernel input rows | attention artifact owns marked occurrence; snapshot/export owns physical projection | Python table retains stable source/event/version refs and manifested logical digest; no independently invented classifications |
| exact projection and legacy Glass monetary decimals | exact atoms/ratios and evidence live in projection | Glass formats locally; it must not send display decimals back or label reserve marks executable |
| artifact occurrence ID and content digest | occurrence ID names lineage/retry; qualified digest names bytes/material | never use one as the other; same content may occur under distinct run/assignment/presentation IDs |
| store export registration and Python snapshot manifest | exact manifest bytes plus store registration jointly close the export | typed adapter reconciles contract/version, part paths, hashes, counts, schema/logical digests, cutoffs, scene/view, and coverage |

### 7.1 Known encoding seams

- Public V1 digests are `sha256:<64 lowercase hex>`; physical SQL columns may store bare hex only
  behind a checked strip/restore adapter.
- Public large integers, slots, atoms, ordinals, and monotonic readings are canonical decimal
  strings. SQL-backed commit values remain bounded by signed SQLite range; full atomic widths do
  not pass through JavaScript `number` or Arrow signed integers without an explicit wider type.
- Durable/public instants use exactly six fractional UTC digits. A source-specific three-digit
  browser instant is validated then exactly widened with `000`; it is not rounded.
- Source and durable event intervals are half-open. Inclusive/exclusive semantics may not change
  merely because a modeling library expects another convention.
- Closed wire schemas reject unknown and duplicate keys at untrusted boundaries. Serde and Zod
  hand-written mirrors require cross-language acceptance fixtures, not confidence from similar
  field names.
- The frozen Glass display-decimal grammar permits spellings such as signed zero that the broader
  canonical financial-number guidance would reject. Do not silently change V1 bytes; narrow or
  normalize only in a new semantic financial DTO/version and record the mismatch.

## 8. Response kernels and fields without causal laundering

The admissible first kernel estimates a conditional observed response after a marked event under a
declared observation/risk policy. It may condition on a caller class, exact caller identity version,
direction, amount, lifecycle, topology, territory hypothesis, presentation context, or scene only
when that value passed the point-in-time rule. Provider future peak/multiple, eventual successful
mint, later canonical family winner, later cluster resolution, retrospective interview label, and
outcome-selected regime are forbidden contemporaneous marks.

The event row, mark rows, response bins, and risk/cohort rows remain distinct because they have
different cardinalities and availability. Response absence under a gap becomes censoring/unknown.
Migration, fragmentation, route loss, and other competing events do not become ordinary negative
responses. A cohort states left truncation, risk entry/exit, event of interest, competing events,
right/interval/source-loss censoring, and an outcome availability cutoff.

Allowed claim language:

- `observed conditional response` for a replayable H2 aggregation;
- `fitted response/memory kernel` for an H3 model with chronological held-out evidence;
- `candidate intensity or resilience diagnostic` for a model under explicit assumptions; and
- `latent explanation set` for competing H4 mechanisms.

Forbidden promotion:

```text
callout -> response       therefore caller caused move
Hawkes cross-kernel       therefore contagion
signed flow + quote cost  therefore pressure
cluster hypothesis        therefore one controller
retrospective fit         therefore value available in scene
```

An H3 artifact may enter a later presentation policy only through its manifest's support,
coverage, uncertainty, cutoff, and claim scope—not by handing the UI one unqualified scalar. The UI
must show the native decomposition and gaps beside any compression.

## 9. Architecture dependency constraints

The permitted crate/process direction is:

```text
domain/evidence
  <- source adapters / wallet-source / direct Pump / companion admission
  <- store
  <- typed operator + projection + topology + export adapters
  <- core loopback service

immutable export -> Python analysis -> immutable model artifacts
                                      -> read-only presentation consumer
```

The notation shows dependency on lower-level contracts, not mutation direction. Specifically:

- acquisition and wallet-source do not depend on topology, models, Glass, or presentation;
- topology depends on typed source/evidence inputs, not on current UI selections except through an
  explicitly versioned acquisition lease input;
- projection depends on exact accounting/protocol/evidence/store queries and does not depend on
  Glass types;
- Glass/presentation consume bounded DTOs and do no identity resolution, model fitting, financial
  calculation, or catalog querying;
- Python receives immutable manifests and cannot import the store writer or acquire a catalog
  lease; and
- model artifacts cannot become assertions or policy assignments without a separately reviewed
  promotion adapter.

Avoid a cycle in which Glass ranking promotes a hot scope, the hot scope produces denser data, the
model calls that density market salience, and Glass ranks it higher. The feedback is a real product
process only when every promotion, scope lease, coverage change, policy version, assignment, and
actual presentation is recorded. It is otherwise selection leakage.

## 10. Live implementation audit

The crates now contain substantially more than diagrams, but “the types compile” and “the walking
path is integrated” remain different claims. The current boundary-by-boundary result is:

| Boundary | What is actually closed | Remaining integration status |
| --- | --- | --- |
| companion -> admission -> store | strict duplicate-aware ingress, distinct ingress/durable/store digest domains, exact retry, raw-on/private versus raw-off/lossy fidelity, scoped gaps, recursive receipts, absent browser-start monotonic time, and real core receipt monotonic time | The former eternal product assertion is now a narrowly named capture-snapshot attestation valid only over the browser timestamp's 1 ms precision interval. It must never be reinterpreted as underlying coin/profile/community object validity. Direct social semantics still need their own resolver. |
| attention-directed wallet acquisition | finite bitemporal leases, independent hard budgets, credential-free request plans, exact raw-frame-first normalization, finality/correction inputs, failed-transaction containment, and a typed source-to-topology adapter | No live transport, credential use, pinned Pump/PumpSwap decoder, or durable cursor/coverage acknowledgment is present. This is an offline acquisition substrate, not a crawler. |
| wallet topology | versioned transaction facts, exact dependent-fact binding, accepted-versus-observed separation, three-axis query, versioned cluster hypotheses, retraction, alternatives, and `UnverifiedRequest` coverage | The source adapter exists, but the one-writer evidence/fact/coverage/cursor transaction and an export adapter are not in the root path. The fixture is semantic Rust data, not a cross-language wire golden. |
| social attention | immutable input occurrences, identity and territory version series, event-bound selected cluster context, source-bound event clocks, presentation-scoped UI marks, long marks/responses/cohorts, censoring, and explicit noncausal interpretation | Direct Pump/social source adapters and the ecology-to-selected-context proof adapter remain outside the root path. The crate cannot independently prove the full topology artifact it references; core/export must do so. |
| deterministic financial projection | finalized accounting, exact atoms/ratios, basis and residual quality, episodes/inventory epochs/runners, mark/quote/full-position distinctions, DLMM inventory/action models, refusal states, and `read_only_no_execution` | The exact projection is Rust-only and not mounted by core or decoded by Glass. A real evidence/store query adapter for account, quote, route, state and LP observations is still required. Provisional cockpit state needs a separately named contract. |
| semantic scene and operator command | Rust parses the frozen TypeScript Glass/operator bytes, derives duplicated indexes, checks source/projection/evidence closure as known, and hands private structural store methods validated capabilities; exact retry is durable. Core now wraps the exact stored view in strict `joshi.glass.snapshot/v1` bytes, with a Rust HTTP golden. | Glass requires an explicit launch scene and mutation clients require a memory-only pairing capability, but no safe pairing bootstrap or same-origin browser deployment exists. The actual TypeScript client -> core-router request/receipt path is not yet an integration test. |
| analysis export | Python owns the strict 14-table snapshot contract; Rust now duplicate-safely reads it, rewrites Arrow/Parquet, rehashes all parts, and store registers the resulting private-field capability | `commit_fixture_export_snapshot_v1` is correctly named: this is a locked-fixture rewrite, not a production SQL projection. Rust does not yet reproduce all Python bitemporal/provenance/choice/outcome semantics from store truth, and no pinned Rust output manifest golden exists. |
| response kernels and machine fields | Python produces immutable manifests for descriptive kernels, candidate diagnostics, graph/Hodge observables and synthetic CPMM susceptibility; future-row invariance and orientation tests pass | Current field/venue `int64` values are a deliberately narrow research surface and cannot losslessly consume topology's canonical decimal256-range signed atoms. Real adapters must refuse out-of-range values or introduce a wider schema; they may not truncate. Artifacts are fixture/synthetic evidence, not promoted product inputs. |
| presentation policy laboratory | strict policy, exploration-bundle, scene, event and receipt schemas; exact policy/bundle closure; mandatory assignment; null initial focus; explicitly planned pre-render fields; serialized fail-stop event appends; immutable scene plus append-only intervals; the whole shell waits for the scene receipt, then emits post-mount visibility-start events | There is no typed core/store admission yet. A post-mount lifecycle event is better evidence than policy intent but is still not proof of pixels, viewport, gaze or comprehension; those scopes remain separate. A failed admission may reveal a visibly gapped fallback but is never witnessed-complete. |
| root offline readiness | one script builds/tests/docs every stack offline, scans the normal core dependency tree for authority packages, validates schemas, and runs companion -> store -> exact scene -> command -> retry -> verify -> reopen | It is a useful Wave 1/2 gate, not yet the Wave 3 root witness. It does not run wallet normalization/topology, the projection artifact, presentation admission, registered export, or a kernel/field artifact, and it does not exercise the real TypeScript clients against the core router. |

The important favorable result is that the difficult epistemic separations are now executable in
the component libraries. Wallet topology does not equate an address with an actor. Attention's
selected cluster context is a narrow, event-bound projection rather than a second cluster row.
Financial exact metrics admit only observations and deterministic calculations. The Python field
lane says `observed_price_response_per_flow`, not pressure, and keeps Hodge squared norms distinct
from uncertainty. None of those successes closes the missing adapters above.

## 11. Exact seam contracts and ownership

The remaining adapters should be small enough to state as total functions. If an implementation
needs a fallback, ambient current state, or an invented default, its contract is not ready.

### 11.1 Wallet evidence into topology

```text
RawSourceFrame + EvidenceDraft + AcquisitionResponseContext
  -> NormalizedWalletBatch
  -> Vec<TopologyFact>
  -> StoreTopologyAdmission
  -> TopologySnapshot(query = knowledge cutoff + event slot + event wall time)
```

The source owns exact bytes, occurrence IDs, provisional decode, requested scopes and cursor
candidates. Topology owns version selection and the transaction/dependent-fact graph. Store owns
durability, verified coverage and cursor advancement. The store adapter must prove that every
topology observation and coverage ID exists in the same or an earlier admitted commit, preserve the
exact `transaction_fact_id`, and reject a dependent fact whose transaction version is not in the
batch closure. It must never promote `RequestedUnverified` merely because a page parsed.

### 11.2 Ecology into attention

```text
TopologySnapshot + cluster artifact + exact selection query
  -> SelectedClusterContext
  -> AttentionEvent
```

The projection is valid only for one exact event and cut. It carries the source artifact, topology
snapshot and query digests, adapter version, hypothesis/series IDs, members, status, availability,
wall and slot validity, confidence and adversarial alternatives. Attention admission now enforces
one context per event, a reverse event reference, and exact forcing-input event/observation clocks.
Core still has to prove the full upstream artifact and query rather than trusting the projected
member list.

### 11.3 Store into deterministic projection and Glass

```text
effective assertions/finalized facts at AsOfVector
  -> ProjectionDraft
  -> ProjectionArtifactV1 exact bytes + result digest
  -> registered projection checkpoint
  -> Glass view projection watermark
```

Only the projection owns financial output values. The Glass view owns formatting and semantic
layout, and the store owns the checkpoint that proves the named projection/digest existed at the
scene cut. Core must not extract a few nested values and discard the projection's observation,
coverage, residual, refusal or freshness closure. Glass must never turn display decimal strings
back into calculator inputs.

### 11.4 Content scene, presentation and command

```text
exact Glass view bytes
  + exact policy bytes
  + exact exploration artifact bytes
  + assignment occurrence
  -> exact staged presentation-plan bytes
  -> durable receipt before declared reveal
  -> ordered post-mount presentation events and gaps
  -> future presentation-bound command or explicit abstention
```

The initial admission request must contain or resolve all exact policy, artifact, assignment and
scene bytes; digest references alone do not close it. The receiver recomputes every digest and
derives all indexes. A client event queue stops after a missing receipt and records the gap before
later sequence numbers. Operator command V1 remains scene-bound only; presentation-complete choice
is therefore unavailable until a new command version or separately admitted binding exists.

### 11.5 Store export into Python estimates

```text
typed point-in-time store query
  -> immutable manifest + exact Parquet parts
  -> store registration receipt
  -> Python strict snapshot validation
  -> immutable estimator artifact
  -> separately reviewed product-promotion adapter
```

Manifest closure includes producer/build, projection checkpoint, catalog and full as-of vector,
scene/view when applicable, table schemas, primary keys, row/byte counts, coverage/window/gap IDs,
logical and physical digests, and exact part set. Python never reads the live catalog. A model
artifact never writes an assertion back and does not enter presentation policy without a promotion
contract that checks its cutoff, support, uncertainty and claim scope.

## 12. Root readiness: what the command proves

The repository now has one intended entry point:

```sh
./scripts/offline-readiness
```

It selects a fresh explicit `/tmp/joshi-readiness.*` state directory by default; forces Cargo, npm
and uv offline; checks formatting, locked build/test/Clippy/rustdoc, schemas, Glass, companion and
analysis; scans the normal `joshi-core` dependency graph for signing/submission/remote-control
packages; then runs a deterministic core fixture. The current fixture proves distinct companion
digest domains, accepted/idempotent store receipts, exact typed Glass scene admission, exact typed
operator command and retry, full store verification and read-only reopen.

A fresh focused run during this review passed that component path on catalog V6. It admitted one
acquisition, observation, capture-snapshot assertion and scoped gap; returned idempotent source and
command retries; and finished `integrity = ok` after reopen. Its exact report included ingress
`sha256:7b0f6b421ef1edb29932d74cd2ada03acfa6ac227e2503bb7d94dfd97602255b`,
durable batch `sha256:53d9b3c9c036311872eac45d4fd646f1d21e4743695a25bd157c08022b391623`,
store admission `sha256:fab8196bae9c0364bf84c481dc127ae0dd057535330d071170b7db9471b03df0`,
scene `sha256:0a08b01544d41b6ba0e68855142dfaff432582a8f78c17eef3951ca227121313`
and command `sha256:c0e05b646a5c51816cd409dcbb81c34fe4cb8de40bd519906554bb019c0894cd`.
Those values describe this walking fixture, not the frozen public Glass/operator goldens below.

The final focused transport checks also passed: the core HTTP suite is 5/5, including exact
`joshi.glass.snapshot/v1` response bytes and a paired, allowed-origin operator command whose
sequence, issue time and monotonic time advance from the prior command; Glass is 105/105 with
typecheck and production build green. These component tests still do not substitute for the real
browser/client/router gate below.

That report must be described as `source_scene_command_readiness`, not full Wave 3 readiness, until
the same root command also proves all of the following:

1. exact raw wallet bytes become evidence, a versioned transaction and dependent topology facts in
   one durable closure;
2. a later-known or noncanonical transaction/cluster revision remains observable but disappears
   from the earlier accepted point-in-time result;
3. the pinned finalized financial projection is registered and its exact watermark is mounted in a
   scene without Glass recomputation;
4. the exact policy/bundle/assignment/presentation admission is durably acknowledged before the
   surface it claims is revealed, and ordered interaction retry/gap behavior is exercised;
5. an exact semantic command is sent through the actual TypeScript client and core router under the
   real launch-scene and pairing/origin contract;
6. a Rust-produced, store-registered export passes Python's full snapshot validator, including a
   future-known adversary, then produces one immutable descriptive kernel/field artifact; and
7. the resulting core closure still contains no key loader, transaction builder, simulation,
   signer, submitter, relayer, provider secret or implicit network action.

The real browser test is necessary. Unit tests that stub `fetch` cannot discover that a UI asks for
“latest” while core requires an explicit scene, omits a required capability header, or triggers an
unhandled cross-origin preflight. The safe resolution is an explicit launch scene and an explicit,
memory-only pairing handoff or same-origin session—not a public latest pointer, a token in bundled
environment variables, `localStorage`, query strings, or disabled authorization.

## 13. Exact golden registry

An exact golden is a named byte preimage, byte length, qualified digest and at least two independent
encoders/parsers where a language boundary exists. A deterministic same-runtime fixture is useful,
but is labeled separately rather than promoted by rhetoric.

| Contract/preimage | Bytes | SHA-256 | Present assertion | Status |
| --- | ---: | --- | --- | --- |
| `joshi.glass.view` V1 exact UTF-8 | 2,205 | `sha256:8cbd045cbf22dd4c908ef84ecc14840d71f846b672c0311f65a2a48cdf8d69ab` | TypeScript emits; Rust core/operator/store parse and hash | **cross-language** |
| `joshi.operator.command` V1 payload | 243 | `sha256:11e7520b23cd385313fbdec6c5854614988ba4cdfadbe1958ca2078915233fa7` | TypeScript and Rust assert exact payload bytes | **cross-language** |
| `joshi.operator.command` V1 full command | 808 | `sha256:7b27c7c0ceaee821a45b289c4694ced31d9a3861f1c59044335fd917a3abc531` | TypeScript and Rust assert exact command bytes | **cross-language** |
| Python `joshi.analysis.snapshot/v1` committed fixture manifest file / self-hash preimage | file is 24,495 bytes including its self-ID | self-ID over canonical manifest without `snapshot_id`: `sha256:4528f461322d62ab19e2844ccca790a147cbc709f1329d851ff2acdb705d9718` | Python rebuild/validation is exact; Rust consumes and rewrites the fixture | **semantic bridge, not identical Rust output** |
| Rust-rewritten `joshi.analysis.snapshot/v1` manifest file | 24,493 | file `sha256:019e5cffd17807c6e6ae956650f02a315e5cd8846ff657a6ab1181af3782d93c`; self-ID `sha256:00191b83702d221d8d9f67b5214b8b12742033a9f7bd50ca94de5ba2a0680170` | Rust emitted 14 exact parts; Python strict validator accepted 20 rows and the full manifest | **cross-language fixture**, not production store projection |
| `joshi.read_projection` V1 result material / compact artifact | 27,146 artifact bytes | `resultDigest = sha256:015d40249861b17779ba782e0477bd28b3cadb383ecc6fafe708b0c5c6d72616` | Rust replays byte-identically | **single-runtime**; TS/Python mirror required |
| companion walking ingress digest material | 2,827 bytes after trimming the fixture's final newline | `sha256:7b0f6b421ef1edb29932d74cd2ada03acfa6ac227e2503bb7d94dfd97602255b` | Rust readiness recomputes before adding the digest field | **single-runtime walking fixture** |
| finalized-shape Helius wallet-source JSON | 3,923 | `sha256:fc7a431fd89510ed5b4c74ff0bb810f139ffa359fc6103fbc9a1e7e5d4670a90` | Rust retains exact body then normalizes and reduces v1/v2 through topology | **single-runtime source fixture**; output wire golden still required |

The presentation TypeScript lane also pins the following exact values:

| TypeScript-only presentation preimage | Bytes | SHA-256 |
| --- | ---: | --- |
| policy | 1,285 | `sha256:0dd7aa23c1eb08275436b88e5da0118a06acc482368b94ff2191447a8e8c468c` |
| minimal exploration bundle | 2,560 | `sha256:f57c6cba14bb713dd09ee94e53eb5b26320c17a29c8ec2b4ac84d64afef17362` |
| initial presentation scene | 2,325 | `sha256:8c28191dd9b9714518a634c7fbdd97fa084cf10c8a76bc388dc127afc08d9df7` |
| focus interval event | 821 | `sha256:4fbd49185a10ee42be48a36f456b42c9e1126d079630c6e90d65b0a8b81dc30a` |
| scene receipt | 656 | `sha256:e5fc2454496191cd5a1db0744ddc14329509f0e1abb78c7bf5a01c7c2a01f171` |
| event receipt | 627 | `sha256:a5cff2d703c6a90114d4eeac56e9367958a64e787492e8b56280588d9364c422` |

These do not become cross-language goldens until a Rust admission/parser asserts the same bytes,
lengths, digest domains and semantic closure. The scene is explicitly a staged plan; post-mount
events supply separate realization evidence, and changing either meaning requires a new golden.

Goldens still required for an integrated Wave 3 gate are:

- shared source/attention exact and bounded half-open event-time vectors, including maximum clocks;
- the companion ingress -> durable batch -> store receipt recursive mapping;
- wallet source -> topology IDs, transaction version, Arrow widths and point-in-time snapshot;
- full ecology artifact/query -> `SelectedClusterContext` projection and a future-known refusal;
- projection bytes accepted by a strict TypeScript consumer without numeric coercion;
- presentation admission/event/receipt bytes accepted by Rust after honest render-scope closure;
- Rust exported manifest and every Parquet logical/schema/physical digest accepted by Python; and
- kernel/field input and output logical artifacts, including the tail `-1` / head `+1` incidence
  orientation and a refusal above the current `int64` research boundary.

## 14. Ordered integration gates

Run these gates in order. A later visualization or model result cannot compensate for an earlier
evidence/cutoff failure.

1. **Wire gate.** Duplicate/unknown/prototype keys, invalid Gregorian instants, noncanonical integer
   strings, out-of-range widths, signed-zero policy mismatches, digest-prefix mistakes and altered
   key order all fail consistently in Rust, TypeScript and Python.
2. **Source/durability gate.** Exact occurrence identity, bytes/fidelity, separate wall and
   monotonic domains, gaps, batch digest domains, idempotent receipt and cursor non-authority survive
   commit, full verification and reopen.
3. **Point-in-time topology/attention gate.** Natural signatures never replace fact-version IDs;
   accepted finality/canonicality is explicit; valid-at and known-by both apply; latest-known
   identity/territory/cluster series selection is enforced; corrections/retractions remain visible
   without leaking into old cuts.
4. **Financial projection gate.** Observation/effective-assertion closure, asset units, basis,
   residuals, quote state/route/freshness, LP unsupported fields and finalized cutoff validate; no
   mark impersonates a liquidation or fill.
5. **Scene/command gate.** Exact Glass bytes, source cursors, projection checkpoints, evidence
   clocks, choices, command references and retry are receiver-derived and durable. The actual Glass
   client can select an explicit launch scene, authenticate locally and receive the exact receipt.
6. **Presentation gate.** Policy, artifact, assignment and staged render plan close before reveal;
   post-mount visibility, viewport and focus facts are then recorded rather than inferred from the
   plan; ordered interval events survive retry and gaps; V1 commands remain labeled
   presentation-incomplete.
7. **Export/analysis gate.** Rust's store-derived snapshot passes all Python semantic validators and
   exact part closure; future rows do not change earlier eligible input IDs or outputs; integer
   narrowing refuses rather than truncates; outputs remain immutable and noncausal.
8. **Product/epistemic gate.** Human perception and machine field remain distinct contracts;
   provider/Joshi presentation is inside the observation operator; no global coverage emerges from
   hot scopes; no pressure, energy, contagion, skill, ownership or profitability language exceeds
   the artifact's claim scope.
9. **Authority/root gate.** One fresh offline command runs gates 1--8, audits source and dependency
   closure, opens no socket, and proves there is no construction/signing/submission/engagement
   capability. Full verify and read-only reopen finish the run.

## 15. Release judgment

Wave 3 is not foolish and it is not a trading system. It is a credible research substrate whose
best contribution is preserving distinctions that the previous work repeatedly collapsed: source
occurrence versus semantic event, address versus actor, conditional response versus cause, exact
financial calculation versus quote/fill, machine estimate versus Ember's perception, content scene
versus actual presentation, and choice versus outcome.

The component-level work is strong enough to continue. The integrated Wave 3 claim is **not yet
earned**. Keep live authority at zero and do not begin a broad crawl or model-driven cockpit pilot
until the real Glass/core launch/authentication, honest presentation-surface, wallet durability,
store-derived export and numeric-width gates above close. If those adapters prove awkward, reduce
the first experiment's surface; do not merge contracts or relax point-in-time semantics to make the
demo pass.
