# Wave 6 epistemic campaign engine

## Status and boundary

`joshi_analysis.wave6_epistemic_campaigns` is a pure fixture-oriented semantic prototype. Every
public operation returns an `UnverifiedSemantic` value with status `unverified_semantic` and
authority `read_only_no_execution`. It owns no store adapter, receipt, sealed journal, collector,
source client, acquisition priority, presentation path, action affordance, capital reservation,
wallet, signer, transaction, or settlement capability. In particular, it cannot establish durable
mutual blindness, prospectivity, a score artifact, qualified support, or an ensemble.

This implements the P0 semantic gate described in
[the research protocol](../../research/wave6/06_EPISTEMIC_CAMPAIGNS.md). It follows the ceiling
and conservative terms of [the epistemic book](../wave5/07_EPISTEMIC_BOOK.md), but does not
bridge Python values to that Rust contract or counterfeit its opaque durable capabilities.

## Implemented semantic scope

- `ClaimDefinition` makes all five initial families explicit: C1 directional response, C2 hazard
  / time-to-event, C3 liquidity / route activation, C4 provider adverse selection, and C5
  recognition / disposition. Each family fixes its exact outcome domain and admits only its named
  typed scoring-rule family; a definition is versioned and explicitly powerless.
- `FrozenUniverse`, scene digest, sorted immutable evidence manifest, capability IDs, and the
  exact occurrence clocks are fixed before the target: maximum input availability ≤ information
  cutoff ≤ occurrence commit ≤ issue deadline < target origin < horizon < knowledge deadline.
  A subject absent from the full frozen eligible roster is refused. `occurrence_id` is recomputed
  from canonical definition content, universe content, evidence manifest content, every committed
  clock, subject, scene, forecaster set, reveal commitment, capability set, and authority. It is
  therefore not caller-spelled and cannot survive a target-definition, universe, evidence, or
  clock edit.
- First-round submissions and adjudications bind both the canonical occurrence ID and the exact
  canonical definition-content digest, as well as the frozen input manifest where applicable.
  First rounds require an empty declared peer/ensemble visibility set. `assess_reveal` requires
  the whole registered eligible set, not a subset or merely the requested component count. This is
  semantic preflight only; a store must independently prove actual sealed writes and visibility.
- Adjudication has distinct observed, healthy-survival, replay, administrative/source/interval
  censoring, truncation, competing-event, refusal, intervention, conflict, unsupported, and open
  dispositions. Censored, conflicting, unsupported, and open values never become zero, neutral,
  success, failure, or a scoreable outcome. Healthy survival requires nonempty complete coverage.
- `preview_brier_score` calculates exact integer Brier loss and a same-occurrence baseline
  increment only for exact binary domains using a registered binary-Brier rule (initially C3 and
  binary C5). It refuses log, multiclass directional/provider, and joint hazard/time-to-event
  rules rather than reinterpret their categories. It is an arithmetic preview only.
  Cross-occurrence definition/submission/adjudication substitution and late knowledge are refused.
- `preflight_ensemble` refuses duplicate primary lineages, duplicate components, noncategorical
  components, future support, reused support, vacuous support, and insufficient dependence-aware
  historical support. A semantically clean result is still
  `blocked_missing_durable_proof`, never an eligible ensemble.
- `account_information_capital_time` records only frozen information age and has zero reserved
  capital and zero capital-time exposure by construction. No forecast can affect acquisition,
  presentation, or action.

Deterministic semantic IDs and all supplied SHA-256 references are strictly validated and
SHA-256-derived from canonical material. They are content labels, not store object IDs or commit
receipts.

## Verification

Focused tests cover future evidence and outcome knowledge, cross-occurrence and cross-definition
substitution, canonical occurrence ID changes for definition/universe/evidence/clock and scoring
rule edits, peer-visible and selective first-round reveal, duplicate participants,
censor-to-score laundering, exact binary-Brier positive and log/multiclass/hazard negative cases,
vacuous support, future support, and shared-lineage ensemble components.

```text
cd analysis
pytest tests/wave6_epistemic_campaigns
ruff check src/joshi_analysis/wave6_epistemic_campaigns tests/wave6_epistemic_campaigns
```
