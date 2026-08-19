# G0 paired browser-presentation store receipt

Status: **PASS for paired HTTP -> sole-store -> read-only-reopen and Glass post-mount transport
tests**; **BLOCKED for an attached-browser occurrence and product qualification**.

Migration V21 adds the append-only `cockpit_v2_browser_presentation_v1` occurrence. Its only
production writer accepts the exact canonical
`joshi.cockpit.v2.browser_presentation_claim` bytes and an ordinary pairing session descriptor
returned by Core's sealed authorizer. Inside one immediate store transaction it resolves:

- the exact Cockpit V2 publication and head bytes, semantic digests, physical digests, store
  commits, source occurrence, and rendered-subject set;
- the exact prior durable `consumed` pairing occurrence, origin, epoch, session ID, expiry, and
  `presentation_evidence_write` scope;
- the temporal chain `pair consumed <= browser mount <= store commit <= pairing expiry`; and
- absence of any revoke, expiry, or restart invalidation at the presentation commit.

The store retains the canonical claim bytes, their physical digest, the claim's self-excluding
digest, all exact lineage, browser clock/viewport/visibility/focus fields, and the store commit.
Exact retry returns the original commit. A changed claim under the same derived page/sequence key
refuses. Read-only reopen reparses the bytes and rederives the publication, head, pairing, clock,
and digest closure before returning the occurrence.

Core mounts `POST /api/v1/cockpit-v2/presentations` only when the durable ordinary pairing service
is mounted. The route requires exact loopback Origin, same-origin Fetch Metadata, JSON, a bounded
64 KiB body, a live `jpc1_` capability, and the dedicated write scope. Its receipt is deliberately
limited to `durable_browser_report_only_not_pixel_verified`; it carries no wallet, signing,
transaction, execution, or product authority.

The explicit G0 inspector keeps the frozen component catalog at V10. It creates a consistent,
separate `browser-inspector/catalog.sqlite` backup overlay, forward-migrates only that mutable
overlay to V21, and verifies its exact publication/source/head against the V10 report. Restart
reuses the latest V22 overlay containing the V21 row while the evidence source remains V10, avoiding a downgrade trap or silent
mutation of the frozen G0 truth.

Glass builds a page-local random ID, increments one sequence per explicit publication open, and
creates the exact claim only from the already validated open response inside a post-mount React
effect. The first Strict Mode effect owns the stable claim; a repeated effect cannot mint changed
bytes under the same key. The same-origin client requires the dedicated scope, sends no cookies,
bounds and duplicate-key-checks the receipt, recomputes the exact claim-byte digest, and verifies
the session, publication, and later store commit before displaying success.
A visible transport-failure action retries the retained claim object byte-for-byte; it never
remeasures the mount or reuses the idempotency key for changed content.

The V2 root-evidence smoke also exercises the route with an explicitly scripted client. It
exact-retries the retained bytes, restarts pairing, reopens the claim, then backs up and restores
the latest V22 evidence overlay separately from the frozen V10 component catalog. Final recovery hides
both original catalogs and validates the pairing session, publication, claim bytes, claim digest,
and store commit only from the two restored stores. Its fields deliberately say
`scriptedPresentationEvidenceStored:true` and `browserPresented:false`; this closes storage and
recovery plumbing, not an attached-browser occurrence.

## Executed witness

The integration regression executes a real V10 G0 source/publication fixture, forward-migrates its
catalog to V21, exchanges a one-time pairing code, opens the exact headed publication, and then:

1. refuses a canonical claim whose mount predates pairing consumption;
2. accepts a current canonical claim and returns the V21 presentation receipt from the V22 catalog;
3. returns the same commit as `idempotent` for an exact retry;
4. returns conflict for a self-consistent same-key byte mutation;
5. refuses the capability after durable revocation; and
6. reopens the exact claim bytes and pairing/publication lineage through read-only SQLite.

The Core portion is synthetic in-process HTTP. The Glass portion is a jsdom React mount and mocked
same-origin transport. It proves the callback/claim/receipt logic, not that a real browser rendered
pixels or that a human used or understood the surface. Attached-browser QA remains not run because
no browser instance was connected during the prior required discovery attempt.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo test --locked --offline -p joshi-core \
  paired_browser_presentation_is_exact_idempotent_and_store_reopenable --lib
cargo clippy --locked --offline -p joshi-store -p joshi-core --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline \
  -p joshi-store -p joshi-core --no-deps
cd apps/glass
npm run typecheck
npm test -- --run
npm run build
```
