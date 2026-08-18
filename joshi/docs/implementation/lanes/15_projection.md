# Implementation lane 15 — evidence-backed exact read projection

Status: Wave 3 read-side implementation; finalized accounting truth plus explicitly
observation-bound deterministic market/liquidity calculations; no execution authority.

## Delivered boundary

`crates/joshi-projection` is the only public financial DTO intended for the Glass boundary. It
joins:

- `joshi-store::EffectiveAssertion` as-known query references and a full `AsOfVector`;
- exact observation IDs, coverage state, finalized chain watermark, and controlled-wallet domain;
- `joshi-accounting` finalized balances/effects, explicit classifications, lots, basis, realized
  components, capital recovery, runner state, and episode/inventory epochs;
- `joshi-market-math` reserve-ratio marks, size-specific quote successes/refusals, and exact
  whole-position sell-quote promotion; and
- `joshi-liquidity` DLMM per-bin inventory, principal, pending fees/rewards, and modeled
  add/remove/in-place-rebalance/close-reopen results.

The public entry points are:

```text
project_accounting(&AccountingProjectionInput) -> AccountingProjectionDto
project_market(asset_definitions, marks, quotes, full_position_quotes) -> MarketProjectionDto
project_liquidity(asset_definitions, positions) -> LiquidityProjectionDto
build_projection(ProjectionDraft) -> ProjectionArtifactV1
projection_bytes(&ProjectionArtifactV1) -> exact compact UTF-8 JSON bytes
ProjectionArtifactV1::{validate,watermark}
```

The artifact contract is `joshi.read_projection` schema 1; the named calculator version is
`joshi.projection.v1`. It is a separate immutable DTO, not `serde` on calculator state. The
envelope carries projection/supersession identity, calculator build, request/result SHA-256
digests, commit range, full as-of vector, effective assertion references, exact observation
closure, coverage, derived residuals, and the literal authority ceiling
`read_only_no_execution`.

The outer input deliberately requires a known `finalized` chain watermark. V1 is therefore a
finalized financial projection, not the provisional/current cockpit. A later provisional view must
be a separately named artifact with its own finality and correction semantics; this contract must
not be weakened to admit processed/confirmed state into landed accounting truth.

## Exact wire and accessible metric contract

Every atom/aggregate is a canonical decimal JSON string. Exact ratios are reduced signed
numerator/positive-denominator strings. Bin IDs are canonical signed decimal strings; DLMM Q64.64,
shares, slots, commits, and monotonic clocks are unsigned decimal strings. JSON numbers are limited
to small closed schema versions and asset decimal counts. Financial arithmetic never passes
through float or JavaScript `Number`.

Every atomic amount carries `assetId`, `atoms`, `decimals`, and the exact observation establishing
the asset definition. Artifact validation walks the full DTO and rejects any nested unit that
disagrees with the one canonical asset-definition row. Episode attributed quantity is an
`AtomicAmountDto`; it cannot become a unitless count or mix mints.

Rendered exact metrics carry:

- stable content-derived `metricId` and a semantic text label;
- `observed` or `deterministic_calculation` epistemic class only;
- a tagged reading (`known`, `stale`, `conflicting`, `missing`, `unknown`, `unsupported`, or
  `refused`) rather than a nullable/zero convention;
- exact unit, evidence IDs, optional source-value digest, and optional text rendering hint.

Learned/latent estimates and operator perceptions cannot inhabit `ExactMetric`. A later estimator
artifact needs estimator/build/configuration, point-in-time input closure, support and uncertainty;
an operator-perception artifact needs scene/presentation/gesture or annotation evidence. Merely
adding a runtime enum label would make incomparable claims look like financial facts.

Metric IDs are fixed-width SHA-256-derived stable identities, so a valid maximum-length upstream ID
cannot overflow the shared stable-string boundary. Evidence vectors are nonempty, sorted,
duplicate-free, and contained in the artifact observation closure. Equal state and fee observation
IDs deduplicate before serialization.

## Accounting semantics

The accounting input starts with an independently finalized account snapshot and evidence, an
explicit sorted set of assets governed by lot inventory, a contiguous sequence of evidenced
`FinalizedWalletEffect`s, public accounting classifications, enumerated lots, realized components,
episodes, cash-recovery facts, and optional unrealized inputs.

Only the named inventory assets are reconciled against lots. This prevents a SOL cash reserve from
being mislabeled as an unexplained token-lot residual merely because SOL is also a basis/reference
asset. Every controlled account balance is still present in landed balances.

The adapter verifies that effects are strictly commit ordered, pairwise contiguous, and end at the
final snapshot. A classification remains separate from the effect. `Unclassified`,
`ExternalInflowUnknown`, `ExternalOutflow`, and `CustodyOnly` are visible outcomes, never failures
that erase landed balances.

Lots retain original/remaining quantities, basis quality and exact known vector, origin, and
optional episode/epoch. There is no FIFO/LIFO/default selection. A runner is a nonzero partially
consumed lot ID set; it does not rewrite its remaining basis to zero. Capital recovery is a
separate `no_capital_recorded` / `not_recovered` / `recovered` cash-flow fact and is not `PnL`.

Realized results cite a landed disposal effect and expose proceeds, allocated known basis, quality,
and either exact result or typed unknown. Unrealized results require an independently linked fresh
full-position sell quote, exact quoted proceeds, and remaining basis. Known unrealized result from
a stale/conflicting/unknown quote is rejected. A quote output must agree exactly with the admitted
proceeds. Partial/unknown basis produces typed unknown, never `proceeds - 0`.

Episode attribution cannot alter balances or lots. Phase, exact attributed asset amount, and each
inventory epoch are explicit. Exact flat closes an epoch; `watching_flat` keeps the episode alive;
re-entry starts a new basis epoch in the same episode.

## Mark, quote, and full-position distinctions

Three public shapes remain disjoint:

| Artifact | Meaning | Explicit non-claim |
| --- | --- | --- |
| `MarkProjectionDto` | deterministic reduced reserve ratio at one observation | no size, fee, route capacity, fillability, or causal price effect |
| `QuoteProjectionDto` | deterministic size/direction/profile/route/state-conditioned success or typed refusal | not current execution, landing, or fill |
| `FullPositionQuoteProjectionDto` | exact whole-position sell size and expected output under the linked quote | not “executable liquidation,” landed proceeds, or permission to trade |

Quote binding retains intended state, observed state/fee observations, slot, profile source
revision, venue, pool, asset pair, route, route observation closure, and request size even on
refusal. Successful quote input, output, raw consideration, separately rounded LP/protocol/creator
fees, and total are already exact metrics; Glass must not total or subtract them.

Fresh/stale claims carry state receipt wall time, evaluation wall time, expiry wall time, one named
monotonic window, evaluated/valid-through slots, and explicit route/state coverage. Freshness
validation checks wall, monotonic, slot, and gap-order relations. `conflicting` and `unknown` remain
available when no coherent validity window can be asserted. Quote/impact is a deterministic
response to observed state, not evidence that the quote caused later market movement.

## DLMM inventory and modeled action semantics

Each position retains profile/venue/pool/position/observation/slot identity, account version and
lifecycle, X/Y asset definitions, range, active bin, step, freshness, inventory success/refusal,
and independently identified modeled actions.

Available inventory exposes per-position and per-bin principal, Q64.64 price, pending fees, pending
rewards, and named unsupported fields. Principal, fees, and rewards are never summed. Unsupported
accrual is a tagged state, not zero or an empty observed list. Third-asset rewards require their own
canonical asset definition; they cannot inherit X/Y decimals.

Action output retains four structural meanings:

- add amounts and known/unsupported projected shares;
- removal share/principal plus `not_requested` versus projected fee/reward claims and close flag;
- in-place rebalance current/target/top-up/residual pair budgets while preserving position ID; and
- close/reopen with distinct old/new position IDs.

Every current kernel action remains `modeled_only` with named gaps. No projection says that a
Meteora UI or deployed instruction accepts it. Typed refusal, transaction-account limits,
transaction/priority cost, composition fee, initial/minted share, swaps, interface support, and
close/reopen friction remain visible. There is no builder, instruction, signer request, submission,
or policy chooser in this crate.

## Closure, residual, and digest invariants

`build_projection` refuses unless:

1. commit range is ordered and closes exactly at `asOf.catalogCommit`;
2. the as-of vector names `joshi.read_projection = joshi.projection.v1` and an exact finalized
   chain slot;
3. observations and effective assertions are canonically ordered and none exceed the cutoff;
4. every evidence/reference observation used anywhere in the DTO is in the input closure;
5. asset definitions, ratios, metric IDs, evidence arrays, coverage scopes, gap IDs, and linked
   unrealized/full-position quotes are internally consistent;
6. multiple effective store branches are allowed only when conflicting coverage is visible;
7. the result digest matches the exact schema-ordered compact JSON digest material; and
8. authority is `read_only_no_execution`.

Residuals are deterministic and named. V1 derives exact wallet-minus-lot quantities for governed
inventory assets, unknown residuals for unclassified landed effects, partial/conflicting/unknown
coverage residuals, and named unsupported LP fields. A zero exact reconciliation residual remains
a real calculation; absence, unknown, conflict, and unsupported remain different states.

`projection_bytes` validates before encoding. `resultDigest` is SHA-256 over every semantic field
except itself. `watermark()` returns the exact projection name/version/state digest/delivered commit
that core must mount in a scene. Corrections append a new projection and name
`supersedesProjectionId`; no artifact is updated in place.

## Fixtures and adversarial verification

`fixtures/projection/adversarial.json` is the language-neutral manifest for six executed cases:

- stale full-position quote cannot support known unrealized result;
- competing effective assertion branches require visible conflicting coverage;
- partial coverage creates a named partial residual;
- external inflow creates unknown, not zero, basis;
- exact flat → watching-flat → re-entry preserves episode and starts epoch 2; and
- unclassified external wallet change keeps landed truth and adds an unknown residual.

The Rust golden additionally runs buy → partial disposal → retained runner, exact realized basis,
capital recovery, fresh whole-runner quote/unrealized result, a DLMM position with per-bin
principal/fees, and an in-place rebalance budget through all three component kernels and the final
artifact validator. Its pinned output is 27,146 compact bytes with result digest
`sha256:015d40249861b17779ba782e0477bd28b3cadb383ecc6fafe708b0c5c6d72616`. Replay must produce
byte-identical compact JSON and that digest. Fixture JSON is reparsed through RFC 8785
canonicalization to catch language-neutral numeric or structural drift. There is no TypeScript or
Python byte/acceptance mirror yet, so the byte golden is explicitly single-runtime.

Focused verification:

```sh
cargo test --locked -p joshi-projection --all-targets
cargo clippy --locked -p joshi-projection --all-targets -- -D warnings
cargo doc --locked -p joshi-projection --no-deps
cargo fmt -p joshi-projection -- --check
```

## Core/Glass integration handoff

Core should query the store at an explicit cutoff, construct typed finalized effects and protocol
inputs from effective assertions, call the pure adapters, store/serve the exact artifact bytes, and
mount `artifact.watermark()` in the enclosing scene. It must verify the strong projection digest
and input closure rather than cherry-picking nested fields.

Glass should treat the artifact as the source of all financial values. It may format atom strings
using the carried decimals and accessible labels; it must never recompute fee totals, basis, `PnL`,
capital recovery, quote output, LP inventory, or residuals. Safety-critical exposure/provenance
panels remain non-hideable by presentation policies. Missing/unknown/stale/conflicting/unsupported
states require text/icon treatment and may not be encoded by color alone.

The source/admission lane still must provide coherent finalized account closures, asset metadata,
quote state/fee/route observations and validity clocks, and DLMM position/bin/accrual observations.
Pure calculator agreement is not proof that a route was executable; a later current execution
artifact would additionally require coherent route account state, simulation/provider observation,
and its own expiry policy while retaining the same no-authority boundary until an independently
authorized signer system exists.
