# Wave 5 G0 — publication to scientific-memory authority walk

Status: public semantic contracts and canonical vectors are frozen. Durable storage, receipt
minting, run binding, and qualified research materialization belong only to `joshi-store`.

The nonempty golden walk is deliberately split across the two public crates so neither acquires a
dependency on the other:

```text
store-resolved public source facts
  -> CockpitV2ResolvedSourceFactsInputV1 exact bytes
  -> prepare_cockpit_v2_from_resolved_source_facts
  -> semantic/container/checkpoint bytes
  -> finalize_cockpit_v2 -> CockpitV2HeadV1 bytes
  -> store-resolved SceneRef -> presentation occurrence or typed gap
  -> unverified OperatorAct -> bounded Episode
  -> hidden replay -> session close -> partial knowledge -> missing/censored outcome bytes
```

`fixtures/publication/cockpit_v2_resolved_source_facts_input_v1.json` is the strict adapter input.
It binds the profile ID/digest, observed-universe ID/digest and denominator, knowledge/commit/chain
cutoff, every public source fact and fact commit clock, memberships, Cartesian coverage cells,
gaps, rendering partition, and ordering/pagination policy. `prepare_cockpit_v2_from_resolved_source_facts`
derives—not accepts—the manifest semantic/container digests. The corresponding canonical manifest
and head vectors are `cockpit_v2_manifest_v1.json` and `cockpit_v2_head_v1.json`; the V2 test pins
the body digest `sha256:8c79941372588b2001608267ce562288488d3c0dd519595674cc6c0721af0f0f`.

The store must persist and rehash all canonical input/prepare/body/head bytes. It must allocate the
publication commit only after the cutoff and append the head later, against the exact body ID,
digest, and commit. A source fact that is private, later than the cutoff, outside the declared
profile/universe, or omitted from exact coverage is refused before preparation.

`fixtures/scientific-memory/adversarial.v1.json#goldenChain` pins the exact semantic sequence from
a matching scene/presentation through an explicit partial closure and `missing { source gap }`
outcome. It shows effect separation (`unknown`, `unresolved`, and `not_applicable_by_no_trade`),
hidden-before-reveal ordering, session terminality, and censoring without a numeric substitute.
Every public memory DTO remains `unverified_semantic`; no public type is a durable receipt.

## Store seam

`MemoryStoreAppendRequestV1::from_occurrence` provides canonical occurrence bytes plus exact
identity and digest to `ScientificMemoryStorePort::append_memory_occurrence`. A conforming private
store must fsync/readback those bytes and atomically retain its own private
`joshi.store.scientific_memory_receipt.v1` record containing the same identity/digest, positive
queue generation, store commit sequence, and run identity. The public trait returns no receipt and
cannot mutate or qualify `MemoryKernel`; a caller-implemented echo port is intentionally harmless.

The store owner must maintain durable status per occurrence, never as a kernel-wide boolean. Only a
store-owned qualified research projection may combine an exact receipt with the exact scene,
presentation-or-gap, episode/replay/closure state. It must not infer fills, transactions, lots, or
effects from an operator intent. Reopening after a crash yields either the prior durable prefix or
the same exact occurrence/body/head bytes, never a mixed pair or promoted unverified prefix.
