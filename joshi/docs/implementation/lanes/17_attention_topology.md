# Implementation lane 17 — attention and caller topology

Status: **offline substrate complete; source adapters and estimation consumers not yet wired**  
Code: `crates/joshi-attention`  
Fixtures: `fixtures/attention`  
Observed/source posture: 2026-08-16 America/New_York

## Decision

Joshi will represent a callout as a **marked forcing-event occurrence** in an observed attention
process. It is not a binary predictor, a caller score, a buy signal, or evidence that the caller
caused a later price/community response.

That language is operational, not philosophical. The implementation stores four different
objects:

1. immutable source inputs: what a chain or provider response established, when it established it,
   and which population/page was actually covered;
2. bitemporal identity/follow/territory assertion versions and adapter-selected cluster contexts;
3. an event-time/availability-time index plus through-cut mark rows; and
4. outcomes and prospective cohort rows, with competing events and censoring separate from a
   measured zero.

The split prevents the mistakes that made the donor studies uninformative: eventual callout
multiple/peak leaking into pre-call features; current handles/creator fields projected backward;
visible winners standing in for the candidate population; incomplete follow-up becoming zero; and
same-name/profile-wallet/co-trading relations being promoted to a person or “smart wallet.”

The crate is deliberately offline. It contains no HTTP client, browser capture, wallet signing,
engagement automation, trading path, scalar caller ranking, or contagion estimator.

## Protocol and product semantics that remain separate

The source contract retains distinct input variants for creator routing, social transitions,
callouts, follow snapshots/members, community snapshots, content revisions, and identity links.
It therefore cannot silently collapse the following into `creator_claimed`:

| observed occurrence | exact claim allowed | claim forbidden without more evidence |
| --- | --- | --- |
| signed launch user / declared `creator` | those exact keys occupied those roles at that creation occurrence | the represented person launched, knew about, or endorsed it |
| ordinary creator-fee sweep | accrued fees moved to the configured route; permission model is retained | creator personally invoked or noticed it |
| fee-sharing recipient/config | routing/admin state changed at that version | represented person accepted the coin |
| social-fee PDA/claim | platform/user/recipient/authority relation and payment occurred | recipient signed, a human identity was verified, or a particular mint was endorsed |
| public attributed content | provider/first-party content occurrence, revision, and attribution | content was authentic unless identity evidence supports it |
| creator participation/endorsement | separately encoded social transition with its evidence | implied from fee movement, metadata, handle similarity, or price response |

These distinctions follow Pump's pinned protocol documentation. Coin creation accepts a declared
creator separate from the paying user; current creator-fee collection and shared distribution can
be permissionless; fee sharing can reroute creator fields; and the Pump Fees claim event is signed
by the configured social claim authority, does not require the recipient to sign, and carries no
mint. See Pump's [coin creation](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/COIN_CREATION.md#instruction-data),
[creator fee collection](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/COLLECT_CREATOR_FEE.md),
[fee-sharing](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/instructions/CREATOR_FEE_SHARING.md),
and [Pump Fees IDL](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/idl/pump_fees.json).

Pump's product language distinguishes coin creator, CTO fee owner, shared routing, and related fee
categories, but product/legal descriptions do not replace chain proof. See Pump's current
[fees page](https://pump.fun/docs/fees) and [Terms](https://pump.fun/docs/terms-and-conditions).

## Public contract

`AttentionDataset` is strict JSON (`deny_unknown_fields`) under
`joshi.attention.dataset.v1`. Every exact integer crosses JSON as a canonical decimal string;
provider decimals cross as `JsonNumberLexeme` strings. The latter validates the full JSON-number
grammar but preserves spellings such as `1.2300e-7` and integers above JavaScript's safe range.

### Shared occurrence and evidence fields

Every `ExactAttentionInput` has:

| field | meaning |
| --- | --- |
| `input_id` | immutable occurrence identity of the source-derived input, not a content hash |
| `acquisition_id`, `observation_id` | restart-global source occurrence and retained observation |
| `source_id`, `source_variant` | adapter contract and exact route/transport variant |
| `event_time` | source-valid half-open interval, independent of receipt time |
| `observed_at` | local receipt/observation wall time |
| `available_at`, `available_commit` | wall and durable-order cuts after which the input may be used |
| `coverage` | population/query scope, windows, gaps, cursor, and complete/partial/gapped/unknown state |
| `protection_domain`, `retention_class` | privacy and retention policy, independent of content identity |
| `epistemic_class` | protocol fact, provider assertion, first-party statement, presentation, operator annotation, derived measure, or model inference |

All event and validity intervals are half-open `[lower, upper)`. `exact` event time must carry both
bounds and a `precision_us`; the validator requires the interval width to equal that precision.
`source_missing` never inherits `observed_at` as fabricated event time.

### Exact input families

| input | distinguishing fields and rules |
| --- | --- |
| `callout_observed` | provider callout/revision/supersession, mint, nullable provider subject/wallet, thesis blob, exact price/cap/amount lexemes, direction and content state; local identity selection stays in the derived event, and provider peak/multiple values live only in `retrospective_outcomes` |
| `follow_snapshot_observed` | root, direction, reported/observed counts, pagination-complete predicate, and exact scope coverage |
| `follow_snapshot_member` | snapshot/root/member/direction, nullable wallet mappings, provider follow time, ordinal |
| `creator_relation_observed` | mint, typed launch/creator/fee/share relation, subject/recipient/actor, permission model, nullable chain slot |
| `community_snapshot_observed` | provider-qualified community/mint, counts, and provider update interval |
| `social_content_observed` | object/revision/supersession, parent, author, mint/community, content blob and created/edited/deleted/moderated/tombstone state |
| `identity_link_observed` | typed edge between Pump UUID, external numeric ID, handle, wallet, or metadata URL; it does not assert one human by default |
| `social_transition_observed` | social claim, profile link, acknowledgement, participation, endorsement, audience arrival, duplicate, fragmentation, persistence, or decay as separate occurrence types |

An edit or deletion is a new occurrence. A deletion/tombstone must supersede a retained revision;
history is never overwritten.

Follow absence is equally strict. A `removed` follow edge needs:

- an exact earlier membership occurrence;
- two distinct, chronologically ordered snapshot-boundary observations;
- the same root and direction, with pagination complete and coverage `complete`; and
- no intervening scoped gap.

Anything weaker remains `removal_candidate`. A missing row on a partial followers/following page is
not an unfollow.

## Point-in-time assertion joins

### Identity

`IdentityVersion` contains an identity series, provider-qualified subject, mutable handle/display
fields, typed wallet links, valid time, knowledge time, evidence, supersession, conflicts, and status. Same-name
or same-handle candidates may coexist as `disputed`; an event selects only the non-retracted
version whose:

```text
event_time ∈ identity.valid_time
event_available_at ∈ identity.knowledge_time
```

Within a series, versions form one acyclic same-subject chain in knowledge order: the first is the
root, every later row supersedes its immediate predecessor, and the predecessor's `known_until`
equals the successor's `known_from`. The event validator also rejects a selected row when a later
effective same-series version was known at the cut. It therefore rejects both a future correction
joined into an earlier callout and a stale open-ended version after a known correction. A profile
wallet is not a trade wallet; a provider author wallet is not a verified signer unless separate
evidence establishes that relation.

### Territory

`TerritorySnapshot` is a versioned assertion with a semantic correction series, evidence,
valid/knowledge intervals, resolver version, competitors, and optional confidence lexeme. Relations
are non-exclusive: launch narrative, community attention, creator affiliation, trading fleet, and
duplicate competitor may overlap. An event may join only a snapshot that was both valid at event
time and known at the event availability cut. Territory series use the same immediate-supersession,
closed knowledge-interval rule with same-mint enforcement. Territory is not a permanent coin column
or a wallet identity.

### Wallet clusters

The attention crate does **not** mirror or truncate ecology's full hypothesis row and does not
define a canonical entity. `SelectedClusterContext` is a narrow adapter projection already selected
for one exact attention event; attention code is forbidden from independently re-selecting it.
Each context retains:

- `cluster_hypothesis_id` and semantic `hypothesis_series_id`;
- member chain `AccountId`s;
- source artifact and source topology-snapshot digests;
- selection-query digest and adapter version;
- half-open wall and chain-slot validity;
- source availability wall/commit and status, selected event/time/slot and as-of wall/commit,
  confidence ppm, locally bound evidence inputs, and projected adversarial alternatives.

An active event join requires `latest_effective_known_for_exact_cut`, an exact match to the bound
attention event/time/slot/availability cut, source availability by that cut, and validity on
**both** event-time and chain-slot axes. Unknown slot validity is non-active. The caller wallet must
be an explicit projected member. There is exactly one selected context per event, and the event
must reference that context; unreferenced alternative selections are rejected. Artifact/snapshot/query digests let the ecology adapter prove its
full per-member support, producer, structured alternatives, and evidence/coverage/derivation
closure without this crate claiming to reproduce it. Profile links, flow/co-trade aggregates, and
cluster hypotheses remain separate, and a current correction cannot leak into an older event.

## Marked forcing event, not caller score

`AttentionEvent` binds one exact `forcing_input_id` to mint, event interval, observation and
availability cuts, nullable caller identity/wallet/cluster, territory/community/lifecycle,
venue/pool/slot, regime/topology epoch, and optional witnessed operator scene/decision/choice set.
Its only interpretation enum is `marked_forcing_event_no_causal_claim`.

The event's full `event_time` (including source lexeme) and `observed_at` must exactly equal the
forcing source occurrence. A semantic adapter may append availability and marks; it may not move
the anchor to a more convenient candle or receipt.

For callouts, `KernelMarkRow` requires an observed or explicitly missing row in every family:

| family | examples | missingness/coverage requirement |
| --- | --- | --- |
| caller history | prior observed callout count, through-cut matured outcome summaries, history start | left truncation and caller-history coverage; eventual results after anchor forbidden |
| context | route/feed, contemporaneous flow state, community state, exact amount/direction | source scope and availability cut |
| territory | selected snapshot, rivals/duplicates as known then | resolver version and assertion evidence |
| lifecycle | bonding curve/AMM phase, venue/pool/capacity snapshot | protocol/market evidence and slot |
| audience overlap | estimate identity | intersection and each denominator/coverage remain separate |

`presentation` is an additional family for board rank, neighbors, filters, render state, or UI-only
context. It cannot exist unless the event binds a `PresentationContext`: provider/Joshi kind,
presentation and view digests, view contract, client session, scene, policy version, and observed
time. The mark must be `provider_presentation` or `operator_annotation`. Board rank can therefore
be studied as a presentation-mediated signal without becoming context-free market truth.

The validator rejects any mark whose observation, availability, commit, or through-cut crosses the
event availability boundary. Names indicating provider `multiple`, `peak`, max price/multiplier, or
future return are fail-closed. The exact source values remain available as retrospective
annotations for audits and outcomes; they simply cannot enter the event feature table.

## Response-kernel and cohort tables

The estimation-facing layout agreed with the estimation lane is:

| table | stable keys and semantics |
| --- | --- |
| `kernel_events` | occurrence `kernel_event_id`, attention-event ID, mint, half-open event interval/precision, event availability wall/commit, fit-eligible time, caller identity/wallet/cluster, exact direction/amount+asset, venue/slot, territory/community/lifecycle, regime/topology epoch, scene/decision/choice set, presentation binding, mark-set version, coverage |
| `kernel_marks` | event/family/name key, tagged exact value, epistemic class, observation/availability/commit/through cuts, source inputs, direction, missingness and coverage |
| `audience_overlap_estimates` | two subjects, exact intersection, left denominator, right denominator, estimator, time/availability and independent coverage on both sets—never one similarity score |
| `response_observations` | event/mint/outcome/window key, value or explicit censoring, event-time interval, observation/availability/analysis cutoff, venue/pool, source inputs and coverage |
| `cohort_rows` | cohort definition, candidate census, risk-set ID and denominator, anchor event/cut, fit cutoff, subject, risk origin/entry/exit/horizon, event of interest, competing events, censoring, choice-set completeness, through-cut exposures, coverage |

Required gates:

- `event_available_at <= fit_cutoff`;
- an outcome may be used only when `outcome_available_at <= analysis_cutoff`;
- no source input or exposure summary may cross its anchor cut;
- choice-set claims require a bound scene/view/presentation/session and complete witnessed
  membership;
- risk-set denominator is explicit and nonzero; rows agree within a risk set, subjects are unique,
  and a completely covered risk set contains exactly its denominator's rows;
- left truncation agrees with entry after the risk origin;
- absent follow-up has explicit right/interval/source-loss censoring, never a zero response; and
- migration, duplicate competition, fragmentation, or death may be competing terminal events;
  they are not censoring.

These tables support marked response kernels, event/cohort comparisons, and competing-risk/hazard
work. They do not by themselves identify causal contagion. Attention, price movement, social
participation, callouts, product ranking, and claim/fee behavior are jointly selected and may share
unobserved causes.

## Source acquisition contract

The continuous product source is lane 10's direct Pump adapter when parity/authentication is
established. The browser companion is reconnaissance, parity, drift, and deliberate fallback—not
the primary pipeline.

### Direct Pump input requirements

For every response that can yield attention rows, the adapter must preserve before normalization:

- opaque restart-safe acquisition and observation occurrence IDs;
- route/catalog/access/session class and versioned redacted logical-request fingerprint;
- exact response entity bytes, algorithm-qualified digest, byte length and media/encoding boundary;
- request/receive/persist clocks, local monotonic domain/elapsed time, HTTP status and safe headers;
- pagination/cursor/order/filter/root/board semantics in the coverage scope;
- scoped window/gap/recovery records, including auth rejection, drift quarantine, truncation and
  exhausted pagination; and
- source schema fingerprint and normalization disposition.

The semantic adapter then creates one input per provider object/revision with source-object ID,
event/update clock lexeme, ordinal, author/profile/wallet fields, parent/community/mint links,
content blob reference, exact numeric lexemes, and the parent acquisition/observation. Normalized
rows are provider assertions derived from retained bytes; their existence does not prove route
completeness.

Pump's official integration skills currently document exact-mint coin, SOL price, and optional
profile-balance routes, not a stable general social API. The direct source therefore treats
discovery/callout/profile/follow/community routes as observed product contracts requiring bounded
parity and drift handling, while chain data remains authoritative for protocol facts. See the
pinned [Pump skills repository](https://github.com/pump-fun/pump-fun-skills/tree/c8aaa6a8fb766b2765d2663744515bbf88d04380).

### Companion fallback requirements

A companion-derived input must additionally retain extension session, page instance, acquisition
sequence, request fingerprint, page/route/filter/cursor context, and fidelity:

- raw-on: exact decoded response-body bytes, digest and length as authenticated-private evidence;
- raw-off: exact companion-produced attestation bytes labeled `lossy_normalized_attestation`, never
  provider-exact truth; or
- failure/drop/oversize: real scoped coverage/fidelity gap with boundaries when known.

The adapter must never accept cookies, auth headers, wallet material, provider keys, or query
secrets as evidence payloads. A presentation mark additionally needs the scene/view/session/digest
contract above. A browser-rendered count without a source population remains a provider
presentation, not an audience census.

Pump's current Terms permit bot access only when the rest of the Terms are satisfied and also
restrict unauthorized access, tracking, unreasonable load, and evasion. The direct/companion
posture remains one honest Ember session, deliberately configured surfaces, bounded requests, no
engagement, and no bypass. See Pump's [Terms](https://pump.fun/docs/terms-and-conditions) and
[Privacy Notice](https://pump.fun/docs/privacy-policy). This is an engineering boundary, not legal
advice.

## Protection and retention

Protection is not inferred from a public-looking URL or blob hash:

| class | examples | default handling |
| --- | --- | --- |
| `public_protocol` | finalized program accounts, instructions and events | permanent exact evidence |
| `public_product` | anonymous exact coin/callout response purposely delivered | permanent/minimum according to catalog, untrusted content |
| `authenticated_private_social` | follows, profile/session-personalized pages, comments, exact companion raw-on response | local private raw, field minimum, purpose-bound; no model export by default |
| `operator_private` | Ember annotations, dispositions, decisions and interviews | local encrypted/private boundary; explicit promotion only |
| `derived_restricted` | identity/territory/cluster hypotheses, audience intersections, study rows | retain evidence closure and resolver/model version; never expose as public allegations |

Raw content is not needed in kernel rows. They carry blob/evidence IDs and minimal structured
features. Handle/wallet/profile ambiguity remains visible in Glass; do not label a person a scammer,
insider, or “smart caller.” No posting, following, outreach, engagement generation, identity
verification challenge, public dossier, or trade automation belongs in this lane.

## Fixtures and adversarial gates

`fixtures/attention/study-ready.valid.json` contains synthetic:

- an exact callout with a >2^53 market-cap lexeme and quarantined future peak multiple;
- same-handle identity conflict where only one version is known at the event cut;
- wall/slot-valid cluster hypothesis and non-exclusive territory snapshot;
- witnessed provider presentation, five required mark families, and separate audience-overlap
  numerators/denominators;
- a measured market response and a source-loss-censored social response; and
- a prospective candidate census/risk set ending in duplicate-coin competition.

`adversarial-mutations.v1.json` proves fail-closed rejection of future identity/cluster attribution,
source/observation clock drift, slot-invalid clusters, peak leakage, unbound UI presentation, uncensored missing follow-up,
outcomes unavailable at analysis cut, incomplete choice sets, and a zero risk denominator. Offline
tests also construct:

- valid create → edit → delete chains and invalid orphan deletions; and
- valid follow removal from earlier membership plus complete comparable snapshots, then invalid
  removal across a gap.

Gate run:

```text
cargo test --manifest-path crates/joshi-attention/Cargo.toml --locked
  11 passed (2 unit + 9 integration)

cargo clippy --manifest-path crates/joshi-attention/Cargo.toml --all-targets --locked -- -D warnings
  passed
```

## Smallest empirical experiment

No live crawl was performed. The smallest honest next experiment is a bounded, prospective parity
and response-kernel pilot—not “do callouts work?”:

1. nominate one callout board/filter and a small fixed observation window;
2. record its complete candidate/page census with direct Pump, while the companion deliberately
   observes the same official view for parity and presentation context;
3. retain exact callout revisions and availability, plus chain lifecycle/venue response coverage;
4. build marks only from evidence available at each callout cut; quarantine Pump peak/multiple;
5. include every observed callout occurrence, not successful callers/coins only;
6. construct response bins and risk sets with duplicate/migration/fragmentation competing events
   and source-loss censoring; and
7. report coverage, latency, identity ambiguity, drift, and response distributions before fitting a
   caller-history or audience-overlap kernel.

Stop or rethink the social acquisition portion if complete pagination/order cannot be established,
authentication cannot be reproduced honestly, provider drift outruns versioning, or the available
surface systematically exposes outcomes without event-time history. Continue with the chain and
operator-attention observatory if social parity is unavailable; do not manufacture a market-wide
attention claim from a partial feed.

## Dependencies and handoff

Still required before empirical use:

- direct Pump adapters for callout/follow/community/content revisions and exact scope coverage;
- core/store mapping from source evidence into `ExactAttentionInput` without changing occurrence,
  clocks, bytes, privacy class, or gaps;
- chain resolver for creator/share/social-fee relations, canonicality and both slot/wall validity;
- ecology adapter that binds the exact cluster artifact/digests and selected-as-known query;
- estimation adapter over `kernel_events`, long-form marks, response rows and cohorts;
- Glass point-in-time identity/territory/coverage/presentation inspection; and
- candidate-census and source-health supervision.

Wallet/watch promotion may consume only versioned input IDs, mints, nullable wallets/cluster
hypotheses, scope coverage and expiry. Social evidence remains distinct from signed chain trades.
Glass may render evidence-classed caller response kernels and topology, but must not render a
causal contagion arrow or global caller score.

## Acceptance boundary

The substrate is admitted when:

- exact source objects remain immutable and revisions/deletions append;
- every identity/territory/cluster join is valid **and** known at the event/decision cut;
- cluster joins are valid on wall and slot axes;
- presentation-derived fields have witnessed scene/view/session/policy bindings;
- every callout has all required mark families, including explicit missingness;
- retrospective outcomes cannot enter through-cut marks;
- response/cohort absence is censored, candidate denominators and coverage are explicit, and
  competing events remain distinct; and
- no API exposed by this crate can trade, sign, post, follow, or claim a causal effect.

Passing those gates does not show that callouts predict anything. It establishes the narrower and
necessary condition: a future estimator can ask the real marked-process question without silently
changing which event, identity, population, time, or outcome it is studying.
