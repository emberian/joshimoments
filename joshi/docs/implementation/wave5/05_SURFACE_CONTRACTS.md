# Wave 5 S-track surface contracts

`joshi-surface` is the pure contract/reducer waist for the daily-use sensorium. It owns no
provider, store, UI, credential, wallet, signer, or execution capability. Publication and Glass
consume its immutable DTOs; they do not reinterpret them.

## Constitution and parity

`DailyUseSurfaceProfileV1` is Ember-approved and versioned. Its `profile_digest` is SHA-256 over
the canonical schema-ordered JSON material excluding the digest field. Every Pump/JOSHI surface
remains in the profile, including a critical surface that is currently unavailable or degraded.
`critical_count()` is therefore the declared denominator, not the attained count.

`promoted_continuous` is the only status that can count as product parity. In particular,
`public_chain_alternative_not_product_parity` can support chain launch/trade/lifecycle/pool facts,
but never personalized membership/order, callouts/follows, social/media, or rendered-product
parity. `absent_by_design` requires an Ember approval reason and contributes no parity credit.
Each entry also carries `field_status` for every declared field/media item; reducers and Glass must
show a gap, stale, refusal or unknown field without promoting the rest of the surface.

## Point-in-time reduction

`DeclaredObservedUniverseV1` carries a closed eligible count, sorted eligible subjects and digest;
`sample_only` is explicit and cannot masquerade as a census. `SurfaceReducer::reduce` filters both
`known_at` and `observed_at` at the requested cutoff, applies explicit supersession, sorts by
`order_key/subject/event_id`, preserves denominator-only omissions, and records field-specific
`covered`, `gap`, `stale`, `refused`, and `unknown` states. A late correction cannot enter an older
cut. `reduce_incremental` uses the same complete target closure, so its bytes equal a full rebuild.

The cut carries the declared universe, profile digest, omissions, typed
`SurfaceFieldStateV1 { surface_id, source_id, subject, field, state }` cells and recomputed
`reducer_digest`; profile-bound validation requires exactly one cell for every declared
surface/source/eligible-subject/field tuple, including independent `unknown` cells. The closed
rendered/omission subject partition is exact. Unknown JSON fields are refused
(`deny_unknown_fields`).

## Hot control and product qualification

`HotLeaseV1` closes `HotScopeIntentV1 -> HotScopeDesiredV1 -> HotControlWriteReservationV1 ->
Applied|Degraded`, binds the exact denominator and subject, requires a positive reasoned TTL, and
requires acquisition reservation after control reservation. Applied is local collector control
closure only; it does not prove provider acceptance or source coverage.

`qualify_cockpit` is independent of acquisition and economics, but its public DTO inputs are an
`unverified_semantic` ceiling: it never grants fixture/live/accessibility capabilities. A private
atomic store adapter must resolve exact durable build/publication/session/accessibility receipts
before any capability can be attained. Typed evidence references and exact acknowledgments remain
available for that adapter; critical surfaces must have globally unique critical task IDs.

The canonical profile vector is
[`daily_use_surface_profile_v1.json`](../../../fixtures/surface/daily_use_surface_profile_v1.json).
