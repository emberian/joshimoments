# W4-11 — prospective operator episode protocol

Status: **protocol draft complete; root Wave 4 terminates at `useful_partial`; no prospective
episode was registered or run**.

Date: 2026-08-17.

Authority: `read_only_no_execution`.

This document defines the first non-fixture, Ember-present Wave 4 observation episode and the
criteria for a future integration verdict. It does not register or run an episode. It contains no
provider credential, private operator content, market subject, session ID, or outcome. The root
offline witness now exists separately in the
[`W4-00 integration handoff`](00_INTEGRATION_HANDOFF.md) and is capped at `useful_partial` with
claim `structural_and_fixture_readiness_only`; it is not evidence that this protocol ran.

The protocol implements W4-11 from
[`WAVE4_OPERATIONAL_EXOCORTEX.md`](../../planning/WAVE4_OPERATIONAL_EXOCORTEX.md). W4-00 owns the
canonical public witness and receipt schemas. The root-owned registrations are now frozen as
`joshi.episode.protocol_registration` V1 with
`joshi.store.episode_protocol_receipt`, and `joshi.episode.launch_registration` V1 with
`joshi.store.episode_launch_receipt`; V7 stores them in `episode_protocol_v1` and
`episode_launch_v1`. Names below are semantic requirements inside those contracts, not permission
to create a competing production schema in this lane.

## 1. Decision and non-claim

The first qualifying episode is one ordinary, attached-browser observation session with a duration
chosen before start from 30–90 minutes. The recommended first duration is 60 minutes. Ember sees the
actual eligible census, may nominate one subject for bounded higher-fidelity observation or may
explicitly abstain, records one presentation-bound semantic choice, and may add a natural-language
or chart gesture if useful. No trade, prediction, profit, or model win is required.

The experiment asks:

> Can the system preserve the exact information surface, source health, promotion decision,
> operator interpretation, later outcome boundary, export, and replay of one ordinary session
> without clerical distortion, future leakage, or economic authority?

It does **not** ask whether a coin rises, Ember's judgment is profitable, callouts cause flow, a
model predicts returns, or an LP/routed-liquidity policy works.

An honest abstention can pass the episode instrumentation gate. If no subject is promoted, however,
the episode cannot prove the census-to-hot integration branch; the Wave 4 verdict is then at most
`useful_partial`. A profitable external trade cannot upgrade any verdict.

## 2. Roles and authority

| role | permitted in this episode | forbidden |
| --- | --- | --- |
| Ember | use the attached Glass; nominate a subject or abstain; record a disposition, note, gesture, or usefulness report; independently use ordinary external software if desired | supplying credentials to artifacts; editing witness closure; being required to trade; being asked to optimize a strategy |
| Collector | execute only preregistered read surfaces under frozen budgets; reserve attempts; durably spool evidence; expose gaps/health | wallet access; economic action; silently adding a source or retry budget; selecting the operator's choice |
| Core/catalog | sole semantic writer; publish immutable projections/scenes; admit presentation, command, outcome, interview, export, and restricted artifact receipts | provider credentials; transaction construction/signing/submission; hand-authored closure; changing an old scene |
| Glass | same-origin paired read/record/replay; stage before reveal; record actual visibility/focus and one command | computing financial truth; hiding gaps; client-only mutation; transaction or wallet capability |
| Analysis worker | consume the named production snapshot offline; emit one immutable descriptive artifact | reading/writing the operational store; network use; fact/projection mutation; ranking or activating a hot scope |
| This W4-11 lane | own this protocol, private-artifact policy, sibling audit, and final evidence-based verdict | editing source/core/store/schema/root implementations; fabricating a session or witness |

All software-visible episode artifacts carry `authority = read_only_no_execution`. An external
manual wallet effect observed later is a public-chain fact. It is not proof Joshi requested,
authorized, or caused the action.

## 3. Registration is a hard boundary

### 3.1 Two-stage registration

The session has two immutable registrations because the launch publication must exist before its
exact scene/universe IDs can be frozen.

1. **Protocol registration** freezes the build, source/config/budget policies, duration, relative
   cutoffs, outcome plan, and privacy policy before the collector/session begins.
2. **Launch registration** resolves exact durably published census, cockpit publication, scene,
   projection, presentation policy/bundle, and source generations and reserves the downstream hot,
   command, outcome, interview, export, analysis, and import occurrences. It commits before Glass
   reveals any session content and before `operator_session_started_at` (`T0`).

Neither registration may be edited. A correction creates a new registration and a new session. A
failed registration remains retained as an abandoned attempt; it cannot be reused for a later run.
The protocol receipt and launch receipt are distinct durable facts; accepting the former cannot
authorize reveal, and accepting the latter cannot rewrite the protocol.

### 3.2 Required protocol-registration fields

W4-00 must encode these in the root-owned registration/witness contract or a one-to-one equivalent:

| field | exact rule |
| --- | --- |
| registration contract / receipt | `joshi.episode.protocol_registration` V1 / `joshi.store.episode_protocol_receipt` |
| `protocol_definition_id` | literal `joshi.wave4.prospective_episode/1` for this document revision; stable semantic identity, never an occurrence |
| `protocol_definition_digest` | SHA-256 over the exact reviewed procedure/private-policy bytes for this document revision |
| `protocol_registration_id` | fresh opaque occurrence ID reserved and durably committed before source/session I/O; the launch references this ID and the exact registration digest |
| `protocol_registration_digest` | receipt-derived SHA-256 of the exact registration bytes, including the fresh registration identity and all policy digests; this is current W4-00 `protocolDigest` semantics |
| `prospective_session_id` | fresh opaque occurrence ID allocated by the later launch registration; never a content digest or reused rehearsal ID |
| `run_class` | literal `prospective_non_fixture` |
| `authority` | literal `read_only_no_execution` |
| `build_id` / `build_digest` | exact core, collector, Glass, analysis, lock, and source-tree closure selected for the run |
| `configuration_id` / `configuration_digest` | exact enabled-source, publication, presentation, export, and artifact-import configuration |
| `budget_policy_id` / `budget_policy_digest` | exact S0 budget configuration; no automatic widening |
| `host_topology_intent` | `local_operational` for the first run unless W4-09 already has separately approved supported-host canaries |
| `duration_us` | let `D = duration_us / 1_000_000`; wire value is a canonical unsigned decimal string, exactly divisible by `60_000_000`, and in `[1_800_000_000, 5_400_000_000]`; recommended `3_600_000_000` (`D = 3600s`) |
| `warmup_offset_us` | literal `300_000_000` |
| `choice_deadline_offset_us` | `floor(3 * D / 5) * 1_000_000`; for the allowed minute durations this is an exact whole second |
| `outcome_horizon_offset_us` | `(D + 1800) * 1_000_000` |
| `knowledge_deadline_offset_us` | `(D + 2700) * 1_000_000`, exactly 900 seconds after the outcome horizon |
| `source_plan` | sorted exact source IDs, adapter/profile versions, allowed surfaces, protection/retention classes, and per-source budgets |
| `census_definition_id` / digest | exact denominator definition and degradation policy; names whether it is Pump-parity or independent chain/provider census |
| `hot_policy_id` / digest | exact maximum-five-mint policy, TTL rule, reason allowlist, and independent request/page/byte/credit/native-unit ceilings |
| `projection_policy_id` / digest | exact deterministic projection build/config and required coverage/freshness rules |
| `presentation_policy_id` / digest | exact policy and safety-item closure; no live randomization |
| `choice_protocol_id` / digest | exact prospective nomination envelope retaining semantic action kind `nominate_candidate`, plus `joshi.operator.explicit_abstention` V1 and their command-binding rules; the current general command V2 is insufficient for nomination |
| `outcome_plan_id` / digest | exact non-profit outcome fields, horizon, censoring, and later-knowledge rule |
| `interview_plan_id` / digest | exact optional two-pass protocol and privacy policy |
| `export_plan_id` / digest | production store-derived snapshot schema, validator, analysis job, and restricted import policy |
| `private_artifact_policy_id` / digest | literal policy in section 9 or a byte-identical registered representation |
| `registered_at` / `registration_commit` | exact UTC microsecond timestamp and catalog commit; registration must precede launch/start |

The actual registration contains no angle-bracket placeholder, null required identity, generic
`latest`, mutable path, or user-authored digest. Its exact bytes and durable receipt become root
witness inputs. The landed W4-00 contract now separates stable `protocolDefinitionId` plus
`protocolRevision` from fresh `protocolRegistrationId`, and the launch separately owns fresh
`prospectiveSessionId`. It does not carry a standalone `protocolDefinitionDigest`; before a real
run, the semantic writer must prove that the registered configuration/privacy digest closure binds
this reviewed procedure and private policy rather than accepting opaque caller-supplied hashes. A
failed/abandoned run must never reuse either occurrence identity.

### 3.3 Required launch-registration closure

The launch registration must resolve and receipt all items below before the attached browser is
allowed to reveal the session:

| identity family | required exact identities and cut |
| --- | --- |
| Launch contract/receipt | `joshi.episode.launch_registration` V1 and its exact `joshi.store.episode_launch_receipt`; committed in `episode_launch_v1` before `T0`/reveal |
| Source | every `source_id`, connection/acquisition `generation_id`, latest catalog admission ACK, scoped cursor/window/gap IDs, delivered-through commit, and source receive cutoff |
| Census | `census_snapshot_id`, `eligible_universe_id`, universe digest/count, membership fact IDs, coverage window/gap IDs, and `census_as_of` |
| Hot policy | root wire `reservedHotDecisionId` and `reservedHotIntentId`; the intent is emitted only on nomination, while abstention records the reserved branch as `not_applicable_by_abstention` |
| Projection | immutable `projection_artifact_id`, result digest, `projection_publication_id`, publication commit, freshness, and complete as-of vector |
| Cockpit publication | `cockpit_publication_id`, supersession pointer, scene ID, projection ID/digest, eligible universe ID/digest, and exact publication receipt |
| Glass scene | `scene_id`, exact `view_digest`, mode `witnessed`, full as-of vector, and launch publication binding |
| Presentation | `presentationPolicyId`/digest, exploration-bundle ID/digest, `assignmentId`, exact root wire reservation `reservedPresentationId`, later presentation ID/digest receipt, and expected planned-render item closure |
| Choice command | exact root wire reservations `reservedCommandId` and `reservedCommandIdempotencyKey`, expected command contract/version, based-on scene/view/presentation/as-of identities, and exact choice deadline |
| Outcome | exact root wire occurrence reservation `reservedOutcomeId`, outcome plan/digest, absolute event horizon, and absolute knowledge deadline; a later content-derived outcome artifact ID/digest is distinct and comes only from its producer receipt |
| Interview | exact root wire reservation `reservedInterviewId`; explicit `optional_not_requested_yet` is a state, not an omitted field |
| Export/readback | three prospectively reservable **occurrence** identities: root wire `reservedExportRequestId`, `reservedAnalysisRunId`, and `reservedArtifactImportId`. W4-07 carries `origin.export_request_id` separately from content-derived Snapshot V2 `snapshot_id`, and derived-artifact V2 carries `analysis_run_id` separately from content-derived `artifact_id`; `reservedArtifactImportId` maps to the future receipt's `importId`. Result identities/digests resolve only from later producer receipts. |

Reservation does not claim the later object exists. Each resolved ID must come from its producing
system's durable receipt. The root witness must retain the distinction among reserved, attempted,
accepted, idempotent, refused, not-applicable, and absent-with-gap.

## 4. Exact clocks and cutoffs

Let `T0 = operator_session_started_at` and `D = duration_us / 1_000_000` seconds. The protocol's
durable catalog commit/time is the **prospective-support boundary**: initial source/census evidence
used to form the launch must originate after that boundary, while at least one further non-fixture
source occurrence must originate during `[T0,T_end)`. This distinction is necessary because the
launch registration must name an already-produced census and publication before the operator
surface can reveal them. It does not permit a subject to be selected during preflight: the source,
census, hot, and publication policies are already frozen and the protocol registration contains no
market subject.

The exact future `T0` is frozen inside the launch registration, which must commit before `T0`.
Same-origin pairing, presentation scene admission, and the collector readiness vector must also
pass before that instant. If they do not, the launch is retained as abandoned and a new launch/T0
is required; T0 is never moved in place. All intervals are half-open unless explicitly a point
observation.

| boundary | definition | allowed information/action |
| --- | --- | --- |
| protocol cut `C_protocol` | protocol registration commit/time | fixes build/config/budget/procedure; no session evidence exists yet |
| launch cut `C_launch` | exact cockpit publication as-of and publication commit, committed before `T0` | fixes the initial eligible universe and scene; no “latest” lookup after reveal |
| warmup `[T0, T0+300s)` | first five minutes | inspect the actual census and source health; choice control is disabled |
| choice window `[T0+300s, T_choice)` | `T_choice = T0 + floor(3D/5)` | Ember may nominate exactly one eligible subject or explicitly abstain; annotations/gestures remain optional |
| choice information cut `C_choice` | the exact scene/presentation/as-of bound into the accepted choice command | only evidence available by this cut may describe why the choice was made |
| observation tail `[T_choice, T_end)` | `T_end = T0 + D` | nominated hot scope continues within its TTL/budget; abstention retains census observation; no revised qualifying choice |
| outcome event horizon `H` | `T0 + D + 1800s` | the outcome event window is `[T0, H)`; an event-time interval contributes only under the preregistered overlap/containment rule, never merely because it became known by `K` |
| outcome knowledge deadline `K` | `H + 900s` | choose the latest catalog commit actually durable by `K`; facts learned after `K` cannot enter the first outcome artifact |
| retrospective cut `C_retro` | exact commit selected by `K`, after horizon data/censoring is admitted | produces a new retrospective scene; never mutates `C_choice` |
| export cut `C_export` | exact commit after session close, outcome/censoring, optional interview disposition, and restricted analysis-plan records are durable | production snapshot and analysis use no later commit |
| witness verification cut | verifier invocation time | may verify/reopen/restore existing closure; cannot add support to the prospective episode |

The wall clock never pauses. Browser, source, or network downtime consumes the planned interval and
creates gaps. Stopping before `T_end` is always allowed for safety, health, or Ember's comfort, but
the session is `incomplete_early_stop`, not silently rescaled to 30 minutes. Extending past `T_end`
requires a new session registration; the maximum is never stretched after seeing activity.

For the recommended 60-minute run:

```text
T0                 launch and reveal
T0 + 05m           choice window opens
T0 + 36m           nomination/abstention deadline
T0 + 60m           contemporaneous session closes
T0 + 90m           outcome event horizon
T0 + 105m          outcome knowledge deadline
```

At `T_choice`, an accepted nomination or explicit abstention must already have a durable command
receipt. Nomination retains the semantic `nominate_candidate` action kind in the distinct landed
`joshi.operator.prospective_nomination` V1 envelope with
`joshi.store.prospective_nomination_receipt`; current general command V2 still cannot substitute
because it omits launch, as-of, universe, membership, and deadline closure. Abstention is the distinct
`joshi.operator.explicit_abstention` V1 command with
`joshi.store.explicit_abstention_receipt`; it is not a new V1 payload variant. Rust and Glass
fixture contracts now cover both branches, but store/core admission and a real Glass-to-core
receipt walk remain open. No general-browsing V2 command, annotation,
null selection, missing command, or timeout may impersonate a prospective choice. Core may display
a one-step abstention prompt, but it may not synthesize consent or a choice. A missing receipt produces
`choice_not_durably_observed` and fails the episode.

## 5. Preconditions: when this episode may be run

Fixture rehearsals may exercise the procedure but can never become the prospective session. The
root integration owner must attest these preconditions from executable gates before asking Ember to
begin:

1. W4-00 has frozen the relevant public receipts, registration, and witness skeleton; duplicate,
   unknown, dangerous, partial-2xx, and same-ID/different-body cases fail closed.
2. W4-01 can supervise at least one enabled non-fixture source through pre-I/O reservation, local
   durable spool, catalog admission, shutdown/restart, backlog drain, and scoped gaps.
3. W4-03 can derive the actual eligible universe and apply/close a bounded hot intent without model
   authority or hidden budget widening.
4. W4-04 can circulate real wallet/public-chain evidence and W4-05 can circulate coherent
   lifecycle and pool state into point-in-time artifacts for a nominated subject; social/product
   context supplies positive evidence when its source qualifies or a visible scoped gap. A smaller
   one-sided context loop may be run only as `useful_partial`, not as the qualifying episode.
5. W4-06 can durably publish an immutable deterministic projection and serve the prior one as stale
   after a failed update.
6. W4-08 can perform same-origin one-time pairing, exact launch, Rust presentation admission,
   staged reveal, actual visibility/focus events, and a presentation-bound choice command in an
   attached production browser.
7. W4-07 can export an operational store cutoff, independently validate it, run one offline
   descriptive analysis, and import it without changing evidence or projection truth.
8. W4-10 can expose the source/spool/catalog/publication/Glass/export readiness vector and record
   failure as evidence rather than logs-only success.
9. The exact secret-canary, dependency-authority, free-space/inode, provider-budget, backup/restore,
   and current schema migration gates pass.
10. Ember sees the intended duration and privacy policy and affirmatively chooses to begin. This is
    participation consent, not trade authority.

W4-09 remote qualification is not a prerequisite for the first local episode. If absent, the
registration says `local_operational`; no witness may claim remote resilience.

## 6. Prospective session procedure

### Phase 0 — registration and dry presentation

1. Create and durably receipt the protocol registration without a market subject.
2. Start the approved source set and wait only for the preregistered readiness predicate; do not
   wait for an interesting coin.
3. Derive and publish the current actual census universe under the frozen definition.
4. Build the deterministic projection and explicit cockpit publication from one named cutoff.
5. Create the launch registration from producer receipts, not copied IDs.
6. Pair the attached production browser through the same-origin one-time flow.
7. Stage and durably admit the exact presentation scene before reveal. Verify that selected/planned
   items close to the eligible universe and safety items cannot be omitted.
8. At the already registered `T0`, mount and reveal the session timer, then append and receipt
   actual visibility events from the mounted DOM. If the admitted scene is not ready before `T0`,
   abort this launch rather than delay it. A presentation-admission failure reveals safety
   information with `presentation_not_witnessed` but the episode cannot qualify.

### Phase 1 — five-minute census warmup

Ember may inspect, scroll, focus, compare, or do nothing. Glass records only actual presentation
events. Salience is not focus; planned rendering is not exposure; viewport membership is not
attention. The nomination control remains unavailable until `T0+300s` so the actual denominator and
source-health surface exist before the qualifying choice.

No interview, outcome display, historical peak/multiple, retrospective label, model-selected rank,
or profit field may enter the witnessed scene.

### Phase 2 — choice or abstention

During the choice window Ember takes exactly one qualifying branch:

#### Branch A: nominate one subject

1. Choose one subject that is a member of the exact launch eligible universe. Later census
   revisions may be displayed as separately witnessed context, but cannot add or replace a
   qualifying subject in protocol v1; exercising a revised choice universe requires a new launch.
2. Submit the frozen prospective nomination envelope with semantic action kind
   `nominate_candidate`, bound to exact launch, cockpit, scene, view, presentation, assignment,
   as-of, eligible universe and subject membership, decision deadline, client clock, reserved
   command ID, and idempotency key. Current general command V2 cannot qualify this step.
3. Wait for the exact durable command receipt; optimistic client state cannot qualify.
4. Emit the preregistered `HotScopeIntent` with the same subject and command/scene evidence.
5. Record desired/applied/degraded/closed records. Applied means collector control was written, not
   that the provider covered the scope. A provider/source acknowledgment and store coverage remain
   separate.
6. Keep the scope within the frozen budget and no later than `T_end`. A source failure retains the
   subject with a visible gap; it does not replace the subject.

#### Branch B: explicit abstention

1. Submit `joshi.operator.explicit_abstention` V1 with exactly one frozen reason from
   `no_acceptable_candidate`, `insufficient_evidence`, `risk_boundary`, or `attention_limit`.
   Optional private free text is a separate annotation/blob and is not part of the abstention
   command.
2. Bind and receipt it exactly like nomination. The choice set remains the actual eligible
   universe; abstention is not an empty or omitted selection.
3. Record the reserved hot intent branch as `not_applicable_by_abstention`; do not activate a scope
   merely to make the witness green.
4. Continue the census observation tail. The episode instrumentation can pass, while the missing
   census-to-hot join remains explicit in the final verdict.

The branch is frozen at the first accepted qualifying command. A later change of mind is a new
semantic command/episode event but does not rewrite the qualifying choice or `C_choice`.

### Phase 3 — optional operator expression

At any time after reveal Ember may record one or more of:

- an open-string disposition or crackle-family label;
- an acceptable-inventory note;
- a point/time/range chart gesture;
- a short annotation;
- an explicit “nothing in particular” report; or
- no additional expression.

These are operator perceptions, not market facts, model labels, or execution intents. Their absence
does not fail the episode. The interface must not demand taxonomy repair during the session.

### Phase 4 — close contemporaneous observation

At `T_end`:

1. close any active episode hot intent and retain desired/applied/degraded/closed receipts;
2. seal/fsync pending spool segments and obtain catalog admission receipts or explicit backlog state;
3. close presentation visibility/focus intervals or record browser-disconnect gaps;
4. publish the final contemporaneous cockpit state without future outcome data;
5. write a session-close occurrence with actual duration, source/gap/budget summary, and qualifying
   choice receipt; and
6. make the witnessed replay immutable and addressable.

The system does not ask Ember to trade and does not wait for a favorable market move before closing.

### Phase 5 — outcome and retrospective scene

At the registered horizon `H`, wait no later than `K` for the allowed data to become durable. The
registered outcome plan uses these exact temporal rules:

- the event window is half-open `[T0,H)`;
- a point event is in-window iff `T0 <= event_time < H`;
- a bounded event-time interval is an ordinary in-window event only when its whole half-open
  interval is contained by `[T0,H)`; a boundary-crossing or unresolved interval is retained as
  interval-censored, never snapped to a convenient endpoint;
- an assertion is eligible only when its event/valid-time rule passes, `available_at <= K`, and its
  durable commit is no later than `C_retro`;
- `C_retro` is the greatest durable commit sequence whose catalog commit time is not after `K`,
  selected deterministically by the store; a later-arriving correction is excluded even when its
  valid time is earlier; and
- retrospective state is queried at the exact instant `H` under `C_retro`, separately from the
  event window, with missing, conflicting, unsupported, and censored states preserved as typed
  outcomes.

The outcome artifact contains only:

- the reserved outcome occurrence ID plus its later producer-derived artifact ID/digest;

- selected subject or explicit abstention and the original choice/universe IDs;
- lifecycle/venue status as observed and known by `C_retro`;
- source coverage, gaps, censoring, finality, and route status;
- typed mark, exact-size quote/refusal, and whole-position quote only when the W4-06 evidence closure
  supports them, each kept distinct;
- an external finalized wallet effect, if independently observed, with intent `unknown` unless a
  separate contemporaneous external record establishes more; and
- no value where the relevant price/route/state is missing, stale, conflicting, or unsupported.

It excludes peak-ever, hindsight-best exit, later-than-`K` facts, simulated counterfactual PnL,
strategy score, or a “win/loss” label. Abstention still receives a session closure and censoring/
coverage record; it does not receive fabricated exposure.

Core creates a distinct retrospective scene from `C_retro`. It links to but never supersedes or
mutates the witnessed scene.

### Phase 6 — optional two-pass interview

The interview is optional. The reserved interview ID ends as `declined`, `not_offered_due_to_gap`,
or `recorded`; no omission is coerced into a negative answer.

If Ember accepts:

1. **Outcome-hidden pass.** Replay only the witnessed scene and contemporaneous operator artifacts.
   Ask open recall: what felt salient, what was uncertain, what alternatives were considered, and
   whether the recorded vocabulary matched the experience. The interview information cutoff is
   exactly `C_choice`; the interviewer and UI do not reveal the outcome artifact or later model.
2. Durably close the outcome-hidden segment before any reveal.
3. **Outcome-aware pass, optional again.** Reveal the separately labeled retrospective scene and
   ask only what the later information changes. Record `outcome_revealed_at` and the exact outcome
   artifact digest.

The later account is a retrospective operator assertion. It cannot become a contemporaneous
feature, change the choice label, or repair a missing scene.

### Phase 7 — production export, analysis, import, restart, replay

1. Select `C_export` after the episode/outcome/interview disposition is durable.
2. Run the production store-derived exporter; fixture rewrite is forbidden.
3. Independently validate every part, schema, digest, point-in-time bound, coverage count, and
   private-field exclusion in Rust and Python.
4. Run exactly the preregistered descriptive analysis job offline. A kernel/field job is allowed
   only if its input schema can represent exact widths without coercion and its registered claim
   scope remains noncausal.
5. Import the immutable artifact under restricted-derived authority and prove no observation,
   assertion, wallet effect, projection, census order, or lease changed.
6. Restart core/collector as required by the root test, reopen/verify the catalog, drain any
   retained backlog, replay both witnessed and retrospective scenes, and compare exact digests.
7. W4-00 derives the single root witness. This lane reviews it; it does not hand-author it.

## 7. Exact identity and receipt closure

The eventual witness must close this graph. A missing node is an explicit open join, never inferred
from matching strings:

```text
protocol registration receipt
  + build/config/budget/source plan digests
  + source generation -> reservation -> local spool ACK -> catalog ACK
  + census publication -> eligible universe membership/coverage
  + cockpit publication -> projection publication/artifact/as-of
  + scene/view -> presentation policy/bundle/assignment/scene receipt
  + actual visibility/focus event receipts
  + command -> nomination|abstention -> exact choice receipt
      + nomination -> hot intent/desired/applied/degraded/closed receipts
  + session close -> outcome plan -> horizon/censoring artifact
  + optional interview disposition/segments
  + production export request/snapshot/parts/validator receipt
  + analysis run/artifact -> restricted import receipt
  + backup/restore/restart/replay/integrity reports
  = root-derived joshi.wave4.operational_witness/v1
```

For every arrow the witness records producer contract/version, occurrence ID, semantic/content
digest where applicable, exact bytes or durable blob reference, commit/time, protection domain,
and receipt status. Digest equality never substitutes for occurrence identity; matching IDs never
substitute for digest/body equality.

The following ACKs remain separate: reservation, local spool, optional remote replica, catalog
admission, projection publication, cockpit publication, presentation scene, presentation event,
operator command, export validation/registration, and analysis import. No one ACK authorizes spool
deletion or upgrades source completeness.

## 8. Source, census, hot-scope, and presentation rules

### Source and census

- The enabled source list is frozen at registration. A source that fails remains enabled-with-gap;
  it is not removed from the denominator after start.
- Each source must show positive evidence or a scoped gap during the interval. Silence is never
  zero activity or healthy coverage.
- The census definition is fixed before `T0`. If authenticated Pump board parity has not qualified,
  the UI and witness say `independent_chain_provider_census`; they never imply the Pump surface.
- No mint may enter or leave the qualifying launch choice universe after reveal. Ordinary later
  census revisions remain separately visible context and may motivate a future launch, but cannot
  change this episode's qualifying choice set.
- Synthetic records may test faults but are marked and excluded from eligible support counts.

### Hot scope

- Only the accepted nomination branch activates the reserved hot intent.
- TTL ends no later than `T_end`; independently fixed request/page/byte/credit/native-unit limits
  apply per source.
- No model artifact, wallet score, later outcome, manual database edit, or convenience retry can
  widen the scope.
- Desired, applied, provider-observed, covered, degraded, and closed are distinct states.
- Overload follows the registered deterministic degradation order; it cannot preferentially retain
  winners, exciting subjects, or later-profitable cases.

### Publication and presentation

- Glass launches one exact cockpit publication. `latest` and null-basis reads are forbidden.
- All financial values originate from the named projection artifact. Glass may format them but may
  not calculate basis, fees, PnL, quote totals, or liquidation.
- Presentation policy and exact bundle are supplied to core and receipt-bound before reveal.
- Eligible, selected, planned-rendered, actually visible, viewport, focused, and interacted sets
  remain different. Initial focus is null until a real DOM focus occurrence.
- Coverage/source health, projection freshness/refusal, asset identity, and protection status are
  non-omittable safety information.
- A qualifying nomination requires the landed `joshi.operator.prospective_nomination` V1 contract
  and exact receipt. General command V2 proves presentation/cockpit binding but omits launch/as-of/
  universe/membership/deadline closure, so it is explicitly non-protocol in prospective mode. V1
  is also insufficient. The typed prospective contract alone is not a durable browser/core path.
- `nominate_candidate` remains the semantic nomination action kind. Abstention uses the distinct
  `joshi.operator.explicit_abstention` V1 command and
  `joshi.store.explicit_abstention_receipt`; it does not broaden the frozen operator-command V1
  allowlist. Until core/Glass/store admit and receipt both branch contracts against the launch,
  publication, scene, presentation, assignment, universe, as-of, and deadline, this episode cannot
  run and no other command may stand in for abstention.

## 9. Private operator artifact policy

The first episode uses the most conservative useful policy:

| artifact | protection/retention | export/model rule |
| --- | --- | --- |
| session participation, command kind, subject/abstention, timestamps, scene/presentation IDs, structured usefulness answers | `operator_private`; local catalog/CAS; owner-controlled local/offline encrypted backup preserving class; no remote copy in protocol v1; `hold_no_automatic_deletion` pending a separate retention decision | production export may include typed metadata and IDs; never publish or use as a public allegation |
| optional disposition/crackle-family/open-string labels | `operator_private`; same as above; versions append rather than rewrite | may enter restricted operator tables with exact scene/cutoff; not market truth or target by default |
| optional free-text note | local private blob with digest, length, content type, purpose, and hostile-text handling; no remote replica unless separately approved encrypted private-domain policy qualifies | default export includes only blob ID/metadata, not text; no external LLM/model/API use |
| interview text | local private blob split into outcome-hidden and outcome-aware segments; prompt/version/interviewer/cutoff/outcome-reveal metadata retained | absent from the first descriptive model input; later use requires explicit corpus/purpose review |
| raw audio, video, microphone, screenshot, screen recording | **disabled for protocol v1** | no artifact may be created; enabling requires a new preregistered protocol and explicit consent |
| browser pairing capability, provider/session credentials, encryption keys | secret capability, not evidence | never stored in scene, export, witness, log, fixture, screenshot, or interview |
| market/public-chain evidence | its source-defined public/provider protection class, separate from operator artifacts | may export only under source/license/retention rules; never inherit operator-private access merely by linkage |

This protocol promises no automated hard deletion because Wave 4 explicitly defers the deletion
controller. A later deletion request is a separately authorized, append-only retention event and
must propagate through backups/derived artifacts according to the then-reviewed policy. Until then,
private material remains local and purpose-bound. “Hold” is not permission for broad future model
training.

## 10. Pass, fail, usefulness, and verdict

### 10.1 Instrumentation pass

The episode passes instrumentation only if all are true:

1. Protocol and launch registrations precede their defined information and exact immutable receipts
   close every populated identity.
2. `T_end - T0` equals the preregistered duration; any early stop is explicitly incomplete.
3. Initial launch evidence originates after the protocol's durable prospective-support boundary,
   and at least one further non-fixture source occurrence in `[T0,T_end)` reaches local spool
   durability and catalog admission; every enabled source has positive coverage or a scoped gap.
4. The census universe is producer-derived under the frozen definition with exact membership,
   coverage, and cutoff; no outcome-selected subject is inserted.
5. An attached production browser completes same-origin pairing, exact launch, staged admission,
   actual visibility/focus evidence, and one accepted nomination or abstention command.
6. A nomination closes the hot-intent state machine within frozen budgets, or abstention closes the
   branch as not applicable without fake scope activation.
7. A nomination carries the selected subject through real W4-04 wallet/public-chain and W4-05
   lifecycle/pool point-in-time artifacts; an unavailable social/product family is explicit as a
   scoped gap. Abstention records the subject-specific context branch as not applicable.
8. The witnessed scene, command, and operator artifacts contain no later-known outcome; the later
   retrospective scene is distinct.
9. The outcome artifact uses `H`, data durable by `K`, explicit gaps/censoring, and no profit/win
   label or unsupported zero.
10. The production snapshot comes from store rows at `C_export`, independently validates, and one
   preregistered analysis artifact imports under restricted-derived authority.
11. Backup/restore, integrity, restart, backlog drain, replay digests, dependency authority,
    secret-canary, width, accessibility, and budget reports are present. Unsupported optional remote
    work is explicit, not omitted.
12. No process constructs, simulates, signs, submits, rebroadcasts, or cancels a transaction, changes
    liquidity, engages socially, or exceeds the frozen spend/native-unit budget.

Profit, price direction, selection quality, a trade, interview acceptance, free-text annotation,
and model performance are not instrumentation criteria.

### 10.2 Hard failure

Any of the following makes the episode `not_qualified` even if the UI felt useful or an external
trade profited:

- fixture/synthetic evidence satisfies prospective support;
- hand-authored IDs/digests/counts repair a missing producer receipt;
- choice set, scene, presentation, command, outcome, or export uses later-known data;
- source silence becomes zero/healthy or an enabled source disappears from the denominator;
- presentation is revealed before its durable receipt or actual exposure is inferred from policy;
- the choice is missing, synthesized, optimistic-only, not presentation-bound, or selected outside
  the witnessed eligible set;
- a quote/mark/model/counterfactual becomes a fill, exact financial truth, or action;
- exact integer/rational values narrow through JS/Arrow/Python without checked refusal;
- private content/secret material crosses its permitted boundary;
- a production export is replaced with a fixture rewrite;
- artifact import changes facts, projections, census order, or hot scopes;
- early stop or extended duration is relabeled to fit the allowed range;
- required recovery/security/budget evidence is omitted; or
- any Joshi component gains economic or social-action authority.

### 10.3 Usefulness assessment

Immediately after `T_end`, before outcome reveal, Ember may submit one bounded usefulness report:

| field | choices |
| --- | --- |
| `scene_recognizable` | `yes`, `partly`, `no` |
| `material_context_missing` | `none_known`, `present_described_privately`, `unsure` |
| `clerical_burden` | `low`, `acceptable`, `high` |
| `decision_support` | `helped`, `neutral`, `hindered`, `unsure` |
| `trust_effect` | `increased`, `unchanged`, `decreased`, `unsure` |
| `would_use_again` | `yes`, `maybe`, `no` |
| `natural_vocabulary` | `yes`, `partly`, `no`, `not_used` |
| `free_text_blob_id` | optional private reference only |

`usefulness_pass` requires:

- `scene_recognizable` is `yes` or `partly`;
- no known materially misleading context omission remains unexplained;
- `clerical_burden` is not `high`;
- `decision_support` is not `hindered`;
- `trust_effect` is not `decreased`; and
- `would_use_again` is `yes` or `maybe`.

This threshold is preregistered for deciding whether to continue the same product slice, not for
statistical inference from one person/session. A usefulness failure does not erase a technically
valid episode. It triggers the reduction/repair rule: fix one named truth/latency/friction defect or
shrink the surface before adding sources, models, or authority.

### 10.4 Integration verdict mapping

| evidence | maximum verdict |
| --- | --- |
| protocol written; no real run | `not_qualified` with `prospective_episode_not_run` |
| fixture rehearsal only | `not_qualified` with `fixture_rehearsal_only` |
| genuine choice/abstention but one or more required operational joins missing | `useful_partial` if the surviving loop passes its stated gates; otherwise `not_qualified` |
| instrumentation passes locally, nomination exercises census-to-hot plus real wallet/lifecycle/pool context, usefulness passes, remote remains unapproved/unqualified | `qualified_local_operational` |
| same plus separately approved supported-host canaries and exact remote durability/recovery closure | `qualified_remote_resilient` |
| abstention passes instrumentation but no other prospective episode exercises census-to-hot | `useful_partial`; never upgrade the missing branch |

W4-11 reports two independent values: `instrumentation_status` and `usefulness_status`. The root
witness status follows the weaker required operational closure; it is never averaged with a profit,
price, or subjective score.

## 11. Sibling-lane integration audit

This lane will update the evidence column as sibling work lands. “Workspace tests pass” is not
sufficient; each row requires the exact seam consumed by the prospective session.

| lane | episode dependency | required evidence for review | current W4-11 status |
| --- | --- | --- | --- |
| W4-00 integration/schema/witness | canonical registrations, receipts, migrations, root verifier, derived witness | contract paths, adversarial tests, exact goldens, root command output | **TERMINAL `useful_partial`; prospective semantic joins open.** `EpisodeProtocolRegistrationV1` separates definition/revision from registration occurrence and enforces the exact timing formulas. `EpisodeLaunchRegistrationV1` carries a fresh session, sorted post-registration source receipts, durable census/publication/scene/presentation-plan references, exact choice members, both branch contracts, reserved hot/command/outcome/interview/export/run/import occurrences, and exact-byte launch receipt closure. Both prospective commands enforce the warmup/deadline window against protocol+launch+presentation evidence; nomination command/receipt bytes match TypeScript at `e182…`/`7dd5…`. V7 separates pairing session from prospective session, excludes the opposite branch, and bounds durable choice commit to `[T0+warmup,T_choice)`. `scripts/wave4-readiness` is green and emits the capped root `useful_partial` structural/fixture witness. No episode/pairing/choice store methods exist and core session/choice routes intentionally return 503 after strict syntax/auth; one-time-code exchange/registry, full launch/session golden, semantic admission, and any prospective episode witness remain absent. |
| W4-01 supervisor/spool | reservation→local spool→catalog ACK, stop/restart/backlog/gaps | fake-provider 24h/kill matrix plus separately authorized real-source receipts | **PARTIAL — offline continuity path reviewed; no live source.** `joshi-supervisor` durably reserves before I/O, bounds record/byte queues plus control reserve, spools exact public/private segments, separates replica and catalog ACKs, retains local bytes, and has shutdown/restart/abandoned-attempt semantics. The 24-hour accelerated fake-provider and process-kill harness cannot satisfy prospective support. The collector deliberately has no live provider `run` interface, listener, deployment unit, or remotely resilient host, and no separately authorized non-fixture source receipt exists. |
| W4-02 Pump parity | honest source status and optional qualified Pump census surface | paired route occurrences or exact stopped/unavailable disposition; no secret artifacts | **FIXTURE-COMPLETE; LIVE QUALIFICATION ABSENT.** The reviewed V2 pair/report and promotion contracts bind route/catalog/filter/cursor/pagination/session/auth/body-boundary/time/uncertainty, retain companion input, direct input, and re-derived report as private observations only, and keep every assertion/source event/fact count at zero. Exact source/policy/store receipt domains stay distinct. The 20-pair/3-session corpus is synthetic; no authenticated Ember-present occurrence, honest headless session path, or live promotion receipt exists, so product-board parity and promotion remain unearned. |
| W4-03 census/hot | exact eligible universe and nomination-bound hot state machine | deterministic replay, budget/degradation tests, producer-derived census/hot receipts | **TYPED REDUCER / FIXTURE COMPLETE; OPERATIONAL ADMISSION OPEN.** Operator activation requires command/digest/receipt plus exact scene/view evidence; reason and evidence availability/commit are bounded by the mandatory intent as-of; denominator artifact/digest/count/coverage and wall/commit cutoffs are mandatory; and control admission parses exact canonical supervisor `AttemptReservation` bytes, requiring `control_write`, subject-bound scope, generation/attempt, lower boundary, protection, time, and authority. Seven locked tests cover the prior P0s, deterministic replay, overload denominator retention, nonactivation, and restart/remove. Durable store/core admission and one producer-derived real census→hot receipt remain absent. |
| W4-04 wallet/public chain | one retained real acquisition through facts/coverage/topology/Glass/export | exact bytes and receipts, decoder conformance, correction/reorg point-in-time test | **PARTIAL — typed fixture path reviewed; durable history/live join open.** `joshi-wallet-admission` hides facts/cursor until exact evidence+coverage commit, quarantines vendor projections, binds source events, and preserves later noncanonical correction without rewriting the old snapshot. Arbitrary caller-supplied prior facts have been replaced by an opaque, nonserializable `VerifiedTopologyHistory` obtainable only from a prior receipt-gated admitted result; catalog and nonfuture-commit checks refuse unrelated history. This closes the in-process injection hole, but no typed store readback reconstructs and registers the full historical fact/snapshot closure after restart, Glass/export do not consume it, and all fixtures are synthetic/offline. One authorized real response and the durable downstream join remain required. |
| W4-05 social/lifecycle/pool | point-in-time enabled-family artifacts and coherent protocol state | real occurrence-to-evidence trace, later-known rejection, mixed/incomplete pool refusal | **TYPED REDUCER / FIXTURE COMPLETE; OPERATIONAL CANARY OPEN.** `joshi-market-state` joins four separately stored streams only at explicit valid-time, knowledge-time, commit, and finality cuts; rejects ambiguous branches and later-known corrections; refuses incomplete/mixed-slot/nonfinal/unsupported pool closure; and produces a private exact V7 `SourceFactArtifactCapability`. Capture attestation remains a legitimate retained observation of what bytes reported when, but it cannot impersonate object/event validity in a point-in-time fact. Ten tests and focused strict gates pass. Synthetic tests cannot supply the required real source observation→assertion→snapshot→evidence trace, and W4-06/W4-00 still own its durable commit/publication receipt. |
| W4-06 projection publication | durable exact projection/cockpit head with crash atomicity | full/incremental byte identity, publication receipts, prior-stale behavior | **PURE CONTRACT + CROSS-RUNTIME COCKPIT GOLDEN COMPLETE; SEMANTIC DURABILITY ADAPTER OPEN.** Rust owns `joshi.cockpit_publication` V1 and its full catalog/projection/result/artifact/manifest/commit closure; the canonical receipt echoes cockpit/projection/result/artifact digests and rejects substitution. Glass independently pins the 800-byte digest preimage, 901-byte full record, and `f9ba49…593d1`, while its richer `joshi.glass.cockpit_launch` stays a distinct envelope that echoes the Rust head. V7 and structural SQLite commit methods now exist, but their capabilities accept parallel field values and exact byte blobs without parsing the canonical publication objects to prove every field/body relation. The required typed adapter, exact CAS/fsync/readback semantics, transaction fault injection, immutable authenticated reads, and prospective publication walk remain open. |
| W4-07 export/readback | operational snapshot, independent validation, offline artifact, restricted import | future-known/width adversaries, exact receipts, no mutation of truth | **STRUCTURAL V2 GOLDENS COMPLETE; PROSPECTIVE DATA PATH ABSENT.** Snapshot V2 carries preregistered `origin.export_request_id` separately from content-derived `snapshot_id`; derived-artifact V2 similarly separates `analysis_run_id` from `artifact_id`. Final fixtures pin snapshot `sha256:629351751418ac0ebe88a5d4a49daa49d08dd94fc9193e2d552b5ade23bbf19f`, manifest `sha256:e2a1105f45ec5281850f60913d85a282269679c5241a7b29910afe131acba92b`, and derived artifact `sha256:0914cb4004bf6a69ef7e24c6a4c2f5c790bf37b1c74682d8e9d109e1beca438f`; focused Rust/Python gates cover exact readback, future-known/altered-output refusal, and arbitrary-precision atom calculations without `DOUBLE` narrowing. However, `relation_batches` currently maps only scenes; the structural golden has zero decision/choice/episode/chart/gesture/interview/outcome/provenance/coverage rows. The exporter correctly refuses if source-fact, protocol, launch, or abstention rows exist rather than emitting a false green empty export. A nonempty typed prospective exporter/golden, durable validation/import receipts, and the root export→analyze→import walk remain required. |
| W4-08 Glass | same-origin pairing, exact launch, Rust presentation admission, command binding, attached-browser replay | production browser transcript/receipts, accessibility reports, secret/CORS tests | **BROWSER FIXTURE PATH COMPLETE; OPERATIONAL SERVER/SESSION OPEN.** General mode has memory-only same-origin pairing, explicit no-latest publication selection, receipt-before-reveal, the distinct `joshi.glass.cockpit_launch`, and exact Rust cockpit-byte parity. The prospective shell calls only parameterless `/api/v1/session/launch`, refuses the index, opens its exact cockpit, stages presentation, disables generic V2 nomination, and exposes dedicated nomination plus abstention clients/UIs with shared branch locking and strict warmup/deadline behavior. TypeScript now mirrors the Rust durable scene, choice members, reserved hot IDs, and export-request name; 127 tests, typecheck, and production build pass, including nomination cross-runtime `e182…`/`7dd5…`. V7 has structurally separated pairing-session and prospective-session identities. Still open: a full protocol/launch/session-envelope cross-runtime golden; core one-time pairing registry/exchange and durable 503 choice/session adapters; a semantic writer exercising that identity binding; and attached-browser/screen-reader evidence. |
| W4-09 remote | optional remote-resilient qualification only | approved supported-host canaries, ciphertext-only replica, recovery/quarantine evidence | **REVIEWED DRY-RUN ARTIFACTS; BLOCKED.** [`persvati`](../../../deploy/wave4/packets/persvati-collector-s0.yaml) is `blocked_eol_and_runtime_absent`; [`hbox`](../../../deploy/wave4/packets/hbox-replica-s0.yaml) is `blocked_eol_storage_memory_and_runtime_absent`; [Hetzner](../../../deploy/wave4/packets/hetzner-optional.yaml) is `not_inspected_not_purchased`. Zero-byte blocked renders and [canary/rollback rules](../../../deploy/wave4/CANARY_ROLLBACK_RECOVERY.md) authorize no mutation. Local qualification remains possible; remote resilience does not. |
| W4-10 operations | finite readiness vector, fault injection, budget/backfill/recovery reports | injected failures and durable gap/recovery evidence; no logs-as-truth | **TYPED SUBSTRATE / FIXTURE COMPLETE; OPERATIONAL ADAPTERS OPEN.** `joshi-operational-status` defines a bounded readiness vector, finite-cardinality metrics, pressure degradation, drain conservation, scoped backfill/recovery, PumpPortal live-only refusal, and a no-I/O fault matrix. It cannot derive evidence from logs or execute backfill. Supervisor/spool and validated-receipt adapters, typed store-backed queries, same-origin paired core GET, durable degradation/recovery records, and the 24-hour/kill/real canaries are not integrated. |

### 11.1 Ranked blockers to one operational witness

These are dependencies, not a request to run the episode early:

1. **Semantic store/core admission for the two choice branches.** Private adapters must parse exact
   protocol, launch, scene, presentation, census-membership, publication, source-receipt, nomination,
   and abstention bytes; resolve every claimed durable object from V7; bind the pairing session;
   reject a second branch; and prove the command receipt itself committed before `T_choice`.
   Structural tables and client `issuedAt` checks do not establish this.
2. **One exact server-bound prospective session.** Pin a full protocol/launch/session-envelope
   Rust/TypeScript golden, implement one-time pairing exchange and launch binding, replace the
   current honest 503 session/choice shells with semantic store-backed adapters, and pass attached
   production-browser plus accessibility tests. The two Glass choice controls are fixture-green;
   general V2 nomination remains nonqualifying.
3. **Non-fixture source, census, and context circulation.** Produce source evidence after the
   protocol boundary and during `[T0,T_end)`, derive a real eligible census, and—for a nomination
   claim—walk the same member through hot-scope admission, wallet/public-chain topology, and coherent
   lifecycle/pool state. Synthetic fixtures and Pump parity measurements with zero facts do not
   supply this support.
4. **Semantic projection/cockpit publication.** Parse the canonical W4-06 objects at the private
   store boundary, prove exact body/field/digest closure, exercise durable readback and crash
   behavior, and serve only immutable authenticated IDs. Parallel caller-supplied fields are not a
   publication proof.
5. **Durable session-close, outcome, and interview disposition.** Replace launch-only reserved IDs
   and arbitrary contract-name strings with typed session-close, outcome-at-`H`, knowledge-by-`K`,
   censoring, and interview-disposition artifacts, V7 rows, semantic writers, and receipts. This is
   required even when Ember abstains or declines an interview; absence must be a typed state.
6. **Nonempty prospective export and restricted import.** Map the actual protocol, launch, choice,
   presentation, context, coverage, outcome, and interview-disposition rows; validate independent
   V2 snapshot bytes; run the reserved analysis occurrence; durably import its artifact; and walk
   all receipts after restart. The current fail-closed structural fixture is valuable but cannot
   export a prospective episode.
7. **Operational readiness from durable state.** Integrate supervisor/spool/store/publication/Glass/
   export adapters into W4-10, persist degradation/recovery, and pass the real-source, kill/restart,
   backlog-drain, secret, budget, disk, and local 24-hour gates required by section 5.
8. **The actual Ember-present occurrence and root derivation.** Only after blockers 1–7 close may a
   fresh protocol and launch be registered and the 30–90 minute session be run. Its user choice,
   later outcome, optional interview, export, restore/replay, and root witness must be producer-
   derived. This step is deliberately still absent and cannot be fulfilled by this document.

Authenticated Pump board parity is optional if the registered census is honestly labeled
`independent_chain_provider_census`. W4-09 remote work is optional for
`qualified_local_operational`. Neither optional lane may conceal a gap in blockers 1–8.

Audit questions for every sibling handoff:

1. Does it mint a duplicate identity, digest preimage, clock, coverage state, or receipt already
   owned elsewhere?
2. Can a producer claim applied/covered/durable/current when it knows only desired/sent/ACKed?
3. Does any point-in-time join select on eventual validity, latest state, or outcome availability?
4. Can a fixture, mock browser, hand-authored manifest, or in-memory registry reach an operational
   status?
5. Can any exact value narrow or become a display decimal before the analytical/UI edge?
6. Does model/presentation/operator evidence enter source, settlement, or deterministic financial
   truth?
7. Can private content, credentials, subject labels, or unbounded cardinality leak into logs,
   metrics, exports, backups, or remote storage?
8. Does the seam preserve the no-trade/no-profit condition and dependency-authority audit?

An urgent violation is reported to the sibling owner immediately. W4-11 does not patch around it in
the protocol or edit their production path.

The W4-09 terminology seam is closed: deployment packets now use
`qualified_local_operational_candidate_subject_to_root_witness`, explicitly defer the authoritative
enum to the root witness, and never claim either qualified status. The reviewed remote artifacts
therefore cannot mint a second qualification vocabulary.

## 12. Run-day checklist

### Before Ember arrives

- [ ] All section 5 executable preconditions are green at exact build/config digests.
- [ ] Free space/inodes, budget balances, clock sync, backup/restore, and secret canaries pass.
- [ ] No provider or private credential appears in environment dumps, CLI arguments, logs, or UI.
- [ ] Protocol registration is durable; planned duration and privacy summary are human-readable.
- [ ] Source readiness predicate is fixed; no waiting for an interesting market event.
- [ ] Rehearsal artifacts are in a disjoint namespace and cannot qualify.

### With Ember, before reveal

- [ ] Ember confirms participation, duration, and no-trade/no-profit purpose.
- [ ] Actual census and launch publication are producer-derived and durably receipted.
- [ ] Launch registration closes all available IDs and explicit gaps.
- [ ] Same-origin one-time pairing succeeds without persisting a capability.
- [ ] Presentation admission succeeds before reveal; actual visibility events receipt after mount.
- [ ] The registered `T0` is still in the future after preflight; at that exact instant the
  immutable timer boundaries are displayed without rewriting T0.

### During and after

- [ ] Choice control opens at +5m and one nomination/abstention receipt exists by `T_choice`.
- [ ] Nomination activates only its exact bounded hot intent; abstention activates none.
- [ ] Gaps remain visible and the subject/universe is not outcome-selected or replaced.
- [ ] Session closes exactly at `T_end`; no outcome has entered the witnessed scene.
- [ ] Outcome/censoring closes at `H` using only knowledge durable by `K`.
- [ ] Optional usefulness/interview states are explicit, including decline/noncollection.
- [ ] Production export, validation, one analysis, restricted import, restart, and replay complete.
- [ ] Root verifier derives one witness; W4-11 records its evidence-based verdict.

## 13. Current verdict

As of this document revision:

```text
protocol_status          = drafted_not_registered
prospective_session      = not_run
root_readiness_gate      = passed
root_operational_witness = useful_partial_structural_and_fixture_only
root_wave4_status        = useful_partial_terminal
w4_11_episode_status     = not_qualified_prospective_episode_not_run
instrumentation_status   = not_evaluated
usefulness_status        = not_evaluated
economic_authority       = none
reviewed_remote_lane     = blocked_dry_run_only
known_command_block      = typed_branches_not_store_core_integrated
known_choice_block       = pairing_registry_and_semantic_choice_commit_unimplemented
known_hot_policy_block   = no_real_census_to_applied_scope_receipt
known_publication_block  = semantic_store_adapter_and_immutable_routes_absent
known_launch_block       = full_launch_golden_pairing_registry_and_semantic_adapter_absent
known_outcome_block      = session_close_outcome_interview_closure_absent
known_export_block       = prospective_relations_receipts_and_root_walk_absent
known_source_block       = no_post_protocol_nonfixture_episode_occurrence
```

This is the terminal Wave 4 handoff. The green root command proves the named offline structural and
fixture gates and no more. No fixture, retrospective reconstruction, profitable outcome, or
agent-authored JSON may change the prospective episode status.

No actual episode or further integration expansion is authorized by this lane. If Ember explicitly
reopens the program, the next operational step is **not** to start the timer: first close ranked
blockers 1–7 with store-resolved, non-fixture canaries and a full launch/export/readback rehearsal.
Only then may a fresh registration be committed and Ember be asked whether to begin blocker 8.
