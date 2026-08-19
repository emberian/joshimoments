# Wave 5 — Glass sensorium

Status: daily shell, bounded pending transport, and an explicit offline Cockpit V2 inspector are
implemented. Live surface, scientific-memory, and product-use qualification remain deliberately
disabled until their complete durable contracts and attached-browser witnesses pass cross-seam
review.

The reviewed scientific-memory seam now also has a fail-closed browser transport primitive. It
mirrors the canonical `MemoryOccurrence::OperatorAct` bytes from
`fixtures/scientific-memory/adversarial.v1.json`, including the reasoned
`external_manual_execution_escape` with a typed `capture_failed` presentation gap. It rejects
duplicate JSON keys, noncanonical/overflowed decimal `LogicalSessionTick` values, decimal or
numeric substitutions, and any byte representation that does not exactly round-trip to the Rust
serde order. `catalogCutoff` remains a separately typed `CatalogCommitSeq`; Glass never compares
or substitutes it with a session tick.

The wrapper `joshi.glass.pending_scientific_memory_act` V1 holds only the canonical occurrence
bytes, exact SHA-256, byte length, enqueue instant, `app_private` classification, and
`pending_store_ack`. It writes to a strict-durability IndexedDB transaction when that adapter is
used and removes an act only after an exact same-act-ID/same-digest ACK. It is local transport,
not a scene/presentation/store witness, and exposes no research-admission path. The server route
and private receipt shape are still unavailable, so this primitive is not wired into product
controls; the existing fixture UI visibly remains nonqualifying rather than approximating an act
or a store ACK.

## Delivered shell

`apps/glass` now keeps the four W5-S persistent contexts in one keyboard-operable layout:

1. a broad attention surface with explicit board filters and exact served-snapshot mint search;
2. a hot coin workbench with chart, social, knowability, and field-lab context;
3. an exposure/episode rail retaining runner, flat-watch, re-entry, and unresolved states; and
4. an outcome-separated replay/interview queue.

The attention list owns a frozen accepted order. Wire-u64 ranks are compared with `BigInt`; updated
rank or membership is buffered behind an explicit **Accept updated order** action. The feed renders
the accepted order verbatim, so a second sort cannot move a card beneath pointer or keyboard focus.
Tests cover rank swaps, focus and `aria-posinset` stability, explicit acceptance, and ranks beyond
JavaScript's safe integer range. Search includes exact mint and candidate identity but remains
honestly scoped to the immutable served publication; an empty result is not reported as market
silence.

Keyboard navigation, skip navigation, large controls, semantic labels, screen-reader text, and a
reduced-motion media path remain first-class. The initial fixture view passes the existing axe
suite with color contrast separately tracked rather than waived as product evidence. Presentation
capture can fail without hiding an ordinary read-only publication: the UI renders a typed visible
presentation gap. A registered prospective session still fails closed until its exact presentation
and cockpit-publication binding exists.

## Exact pending-command transport

The browser does **not** own a second operator-action contract. The only local record is
`joshi.glass.pending_operator_command` V1, a bounded transport wrapper around the exact canonical
bytes of the existing authoritative `joshi.operator.command`. It retains command ID, SHA-256
digest, exact byte length, enqueue/repair timestamps, `app_private` classification, and
`pending_store_ack`; it contains no pairing token, capability, cookie, or authorization material.

For loopback operation this cache uses browser-local IndexedDB and requests strict transaction
durability. IndexedDB remains evictable local transport, not the catalog or a durability authority;
the UI reports failure rather than laundering it into a committed act. Fixture tests use an
in-memory implementation of the same interface. The hard envelope is 512 pending commands,
8 MiB total, 64 KiB per command, and a seven-day visible repair threshold. Overflow refuses the
new append and never evicts unacknowledged evidence. The age threshold is not a deletion deadline
and no overdue record blocks unrelated capture while capacity remains.

An operator command is not sent to core until exact local bytes read through schema validation.
Only a matching same-ID and same-digest durable store ACK removes them. Network failure leaves the
canonical bytes queued. Reloaded earlier-session bytes are never auto-retried; after fresh pairing,
an explicit **Recover retained exact bytes** action submits the original command/session/ID without
rewriting or rebinding it. The normal `online` event only retries commands created by the current
browser session. Tests cover outage, reload, explicit same-byte recovery, mismatched ACK refusal,
overdue repair, hard overflow, and capacity release after ACK. Whether core accepts and
idempotently ACKs an old-session command is a separate server qualification; rejection must leave
the cache intact.

## Replay and interview truth

The replay queue will not let a retrospective scene self-label an interview as outcome-hidden.
Outcome-hidden reconstruction requires a non-retrospective scene plus at least one committed
episode-linked source command. Retrospective reflection is a separate action available only in the
retrospective lens. Source command IDs are unique and canonical-order sorted.

These controls remain UI evidence only. The client cannot prove `later`, episode membership, scene
closure, or durable commit ordering. Core must derive and validate those relations before any
interview enters qualified scientific memory. The UI says so explicitly and does not treat its own
labels as contemporaneous truth.

## Authority and operational boundary

The operational client is exact same-origin HTTP loopback only. Pairing capability remains in page
memory, disappears on reload, uses fixed evidence-only scopes, and is never placed in URL state,
cookies, Web Storage, or the pending cache. Publications are selected by immutable ID; the client
does not open an implicit `latest`. Glass contains no wallet key, signer, transaction builder,
submission route, or fill/economic-effect inference.

The live per-surface capability/gap panel, immediate scientific-memory act/assertion controls, and
reasoned external manual-execution escape are intentionally not approximated with Glass-private
semantics. They will be mirrored only from cross-reviewed Rust DTOs and exact goldens. Until that
join lands, the current feed is fixture/partial and cannot promote `live_read_only`, product parity,
critical-task accessibility, or scientific-memory research admission.

## Explicit Cockpit V2 fixture inspector

The default production build still renders the honest unavailable operational shell. Setting
`VITE_JOSHI_G0_INSPECTOR=1` selects a separate read-only inspector; it never constructs `GlassApp`,
an operator sink, a presentation sink, or a V1 launch envelope. Its same-origin client consumes
only the explicit `wave5-g0-inspect` launcher:

```text
# terminal 1, from the repository root
cargo run --locked --offline -p joshi-core -- wave5-g0-inspect \
  --state /tmp/joshi-g0-inspect.manual

# terminal 2
cd apps/glass
npm run dev:g0-inspect
```

Core exact-retries the offline component before it binds, mounts only a `CockpitRead` ordinary
session, prints one short-lived code after the API listener is bound, and exposes a bounded exact
head index plus explicit-ID open. Vite preserves the browser's `127.0.0.1:4173` Host through its
loopback-only `/api` proxy to Core on `127.0.0.1:43119`.

The browser strictly parses every manifest/body/head field, rejects duplicate/prototype keys,
recomputes the universe, semantic, container, checkpoint, publication, head, and physical-byte
SHA-256 domains, and closes profile × eligible-subject coverage, public-only facts, cutoffs,
rendered/omitted partition, durable index order, and selected-entry lineage. The positive test
matches the frozen Rust publication digest `sha256:8c79941372588b2001608267ce562288488d3c0dd519595674cc6c0721af0f0f`.
Self-consistent private facts, future knowledge, denominator narrowing, index/byte substitution,
unknown fields, and unstable order all refuse.

The inspector shows denominator, membership, presentation partition, facts, coverage, cutoffs, and
exact identities under an `unverified_semantic` banner. It has no action affordance. This raises the
offline cross-runtime inspection seam, not default mount, product use, accessibility, presentation,
or live qualification.

## Deliberate normal-server pairing

The default Glass build and default Core server both remain visibly unmounted. For local testing,
the normal pair may be selected explicitly on both sides:

```text
# once: create the unrelated legacy route guard as an owner-only local file
umask 077
openssl rand -hex 32 > /tmp/joshi-core-legacy-token

# terminal 1
cargo run --locked --offline -p joshi-core -- serve \
  --state /tmp/joshi-local-core \
  --companion-installation-id local-glass \
  --pairing-token-file /tmp/joshi-core-legacy-token \
  --ordinary-pairing-origin http://127.0.0.1:4173 \
  --ordinary-pairing-evidence-write

# terminal 2
cd apps/glass
npm run dev:paired
```

Core prints one short-lived code only after the loopback listener binds. Glass consumes it once,
keeps the resulting `jpc1_` capability only in page memory, lists immutable publication IDs, and
opens only an explicitly selected publication. The full operational shell requires both operator
and presentation evidence-write scopes because it stages presentation evidence and exposes
evidence controls. If Core grants only its default read/replay scopes, Glass clears the transient
session and refuses before listing or opening; the separate G0 inspector is the read-only path.
Neither side has a signing, wallet, transaction, execution, or provider-query capability. This
opt-in is a locally testable mount, not an attached-browser, accessibility, daily-use, or live-data
qualification.

## Verification

Executed from `apps/glass`:

```text
npm run typecheck
npm test -- --run
npm run build
```

Current result: TypeScript passed, 23 test files / 157 tests passed, the default production Vite
build passed, and the explicit inspector build passed. The default build reports one non-fatal
main-chunk size warning (>500 KiB); code splitting remains a performance follow-up rather than an
authority or correctness claim.

A real local smoke also ran through the Vite proxy and Core listener: one-time exchange returned
only `cockpit_read`, the exact index returned one head with two eligible subjects/two facts/zero
gaps, and explicit-ID open returned the same source occurrence with body/head store commits 25/26.
The capability value was not printed. This checks the loopback transport/proxy, not visual UI.

Attached-browser QA: **not run**. The required browser workflow was attempted again after a real
local Core fixture launcher and inspector Vite server both started successfully, but no in-app or
extension browser instance was connected. No screenshot, visual-layout, real screen-reader,
pointer, touch, or actual Ember daily-use claim is inferred from DOM tests.

Core's separate `wave5-g0-inspector-smoke` now exercises the real pairing exchange and exact
Cockpit V2 route in process, refuses the old capability after restarting the SQLite epoch, and
reopens byte-identical content under a fresh session. That closes an API/readback seam only. It
does not run this Glass bundle, mount a browser, or change the attached-browser/accessibility
status above.

## Remaining integration gates

- Cross-review and freeze the repaired `joshi-surface` profile/cut/qualification contract, then
  mirror its exact golden and show independent status, field truth, freshness, and gaps for every
  declared critical surface. Fixture booleans or vacuous zero-session witnesses must never promote
  the UI.
- Extend the strict Cockpit V2 inspection contract into a separately reviewed presentation/scene
  launch only after the default product can retain the exact broad manifest and a real browser
  presentation occurrence. The fixture inspector must never be treated as the root attention
  universe.
- Cross-review and freeze `joshi-scientific-memory`, then extend the existing authoritative command
  family and pending transport with its exact act, scene/presentation gap, optional assertion,
  correction, episode, and two-pass replay bytes. Do not create another client-owned action truth.
- Add the reasoned external manual-execution escape only on that exact act path. Capture failure
  may open a typed gap, but it must never prevent the external escape itself.
- Qualify fresh-pair old-session recovery at the core route and add an attached-browser accessibility
  fault walk before any nonfixture product-use claim.
