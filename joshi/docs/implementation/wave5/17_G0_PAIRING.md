# W5-G0 ordinary pairing seam

Status: protocol frozen; pure state machine, Glass wire, and sealed SQLite journal adapter are
implemented. The default product router remains deliberately unmounted; only the crate-private
honest-store constructor can install the exchange and ordinary-session authorizer.

This is ordinary local pairing only. It grants read and evidence-recording scopes. It has no
wallet, signer, transaction, order, execution, submission, quantity, slippage, or economic
authority. Prospective launch binding remains a separate protocol.

## Frozen V1 wire

The old Rust one-time-code representation (64 lowercase hexadecimal characters) was a machine
token, not a reasonable manual handoff. The Glass `EMBER-482901` value was a mock with too little
guess resistance. Neither is an ordinary V1 code.

An ordinary V1 code is exactly 160 OS-random bits encoded with the unambiguous Crockford alphabet
`0123456789ABCDEFGHJKMNPQRSTVWXYZ` as eight groups of four:

```text
JOSHI-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
```

The wire form is uppercase and 45 ASCII characters. Glass may uppercase and trim a human input
before strict validation, but sends only the canonical form. It does not accept ambiguous `I`,
`L`, `O`, or `U`. The 64-hex static token used by older core routes is a separate legacy/manual
capability and is never accepted as an ordinary code.

The exchange request is strict JSON, bounded to 4 KiB, and contains no capability header. The
response carries one capability as `jpc1_` plus 32 lowercase-hex OS-random bytes. The prefix is an
explicit domain separator: a capability can never occupy the one-time-code namespace. The server
binds the capability record to the exact origin, store-owned restart epoch, sorted scope set,
session identity, and monotonic expiry. Glass accepts exactly this capability form and keeps it in
one `MemoryOnlyPairingSession`; it has no serialization, cookie, URL, IndexedDB, localStorage, or
sessionStorage path.

Exact Rust/TypeScript goldens are:

- `fixtures/pairing/exchange_request_v1.json`
- `fixtures/pairing/exchange_response_v1.json`
- `fixtures/pairing/session_descriptor_v1.json`
- `fixtures/pairing/ordinary_pairing_v1.json`
- `fixtures/pairing/epoch_started_v1.json`

Epoch and monotonic values use canonical decimal strings on JSON so JavaScript cannot silently
round them. UTC instants use the repository's exact six-fractional-digit `Z` form.

## Bounds and clocks

Protocol ceilings are enforced by `PairingConfig`: code TTL 30 seconds through 5 minutes, session
TTL 1 minute through 1 hour, at most 8 active codes, 16 live sessions, 8 failed attempts per
bounded window, and 8 issues per bounded window. Defaults are a 2-minute code, 15-minute session,
5 failed attempts per minute, and 4 issues per minute.

Authorization and expiry use only the server process's monotonic milliseconds. UTC is a separately
typed display/audit instant. The production core clock samples UTC once and advances that anchor
only by monotonic elapsed time, so a later wall-clock adjustment cannot extend or prematurely end
a session and cannot make the displayed expiry move backwards within an epoch. An occurrence with
an issue/consume expiry at or before its observed UTC instant is invalid.

Production entropy is the operating system RNG through `getrandom`; there is no fallback. The
deterministic entropy/clock seams are used only by pure/in-crate tests and cannot construct a
production route.

## Exact local browser posture

Exchange is POST-only and requires all of:

- configured `Origin` equal to the service's exact origin;
- `Host` exactly equal to that origin's authority;
- an HTTP loopback host (`localhost`, `127.0.0.0/8`, or IPv6 loopback);
- `Sec-Fetch-Site: same-origin`, `Sec-Fetch-Mode: cors`, and `Sec-Fetch-Dest: empty`;
- exact `Content-Type: application/json` and strict JSON without duplicate/unknown fields;
- omitted ambient credentials and `Cache-Control: no-store` on the Glass request;
- `Cache-Control: no-store` on every core response.

No CORS relaxation, wildcard/suffix origin matching, cookie credential, URL capability, or
cross-origin pairing path exists.

## Durable state DAG and crash rule

The journal persists canonical nonsecret occurrence bytes plus their digest and normalized fields.
It never persists the code, capability, a hash of either secret, or material derived from either
secret. Occurrence authority is exactly `read_only_pairing_exchange`; returned session authority
is exactly `read_only_no_execution`. The required kinds are `epoch_started`, `issued`,
`attempt_rejected`, `consumed`, `revoked`, `expired`, and `restart_invalidated`.

```text
epoch_started(pair-epoch-{origin_tag}-{epoch})
  ├─ issued(issue_id)
  │    ├─ consumed(issue_id, new session_id)
  │    │    └─ revoked | expired | restart_invalidated (session_id)
  │    └─ expired | restart_invalidated (issue_id)
  └─ attempt_rejected(no issue/session/secret reference)
```

`epoch_started` is the exact root returned by durable epoch begin. Issued and rejected-attempt
occurrences name it as predecessor. `consumed` is terminal for the issue but starts the session
lineage. A consumed session must still be revocable or expirable. Each child names the exact
predecessor occurrence. Every issued or rejected-attempt event carries the exact fixed rate-window
identity and wall deadline. The first event opens a window using its own occurrence identity;
later events before the deadline reuse it, including across restart. Failed-attempt rows also carry
their window-scoped ordinal and current-clock monotonic window anchor. Every bounded strict
exchange submission, including a malformed code shape, advances that attempt counter without
retaining the submitted value. Successful consume does not reset that window.

`origin_tag` is lowercase SHA-256 of `joshi.pairing.origin.v1\0` followed by the exact canonical
origin UTF-8 bytes. Runtime identities
are `{prefix}-{origin_tag}-{epoch}-{ordinal}` for `pair-issue`, `pair-session`, and
`pair-occurrence`. This makes epoch 1 for two different loopback origins globally disjoint.
At restart the store sorts live predecessor occurrence identities bytewise, assigns new-epoch
restart invalidations the contiguous occurrence ordinals 1 through N, and returns their exact
readbacks plus N. Core verifies every byte and seeds the registry at N; the first runtime event is
therefore N+1 rather than an identity collision.

On reopen, the sole writer must atomically append restart invalidations for every formerly live
issue/session and durably begin a strictly higher exact-origin epoch before a registry or route is
made available. Append success is not a Boolean: the narrow `PairingJournal` port must return the
same occurrence identity, digest, exact post-commit readback bytes, and positive commit sequence.
Crash/reopen invalidations carry the new epoch and its begin-epoch monotonic sample, with the
predecessor pointing across the boundary to the prior live row. No new-process tick is ever labeled
as belonging to the old epoch. Cross-epoch predecessors are valid only for this exact
`restart_invalidated` transition and must advance by one epoch for the same origin.

Restart also cannot replenish either rate budget. Durable epoch begin receives the validated
attempt/issue limits and window lengths. The store resolves, persists, and returns each live fixed
wall window's identity (the first event occurrence ID), used count, and wall deadline, plus the
origin's last observed wall instant. Successful consume never resets a window. Core refuses wall
regression, maps only the deadline's remaining duration onto the new monotonic clock, and carries
the used counts until that deadline. A policy change is rejected while either prior window is
live. Production cannot start from a receipt that omits or contradicts this bootstrap state.

Issue and consume mutate zeroizing memory first, then request one atomic journal append. A code is
not shown until its issued occurrence has exact durable readback. A capability is not returned
until its consumed occurrence has exact durable readback. If persistence fails or is ambiguous,
the newly issued code or session is invalidated in memory, the secret is dropped, and the response
is unavailable; it never falls back to an in-memory success. A failed consume is one-time and
fail-closed even if the client retries after writer recovery. Any journal failure poisons that
in-process coordinator: it serves no later exchange, authorization, issue, or revocation until an
honest reopen begins a higher epoch and closes every possibly committed live predecessor.

The public state-machine authorization port returns `PairingAuthorizationOutcome` for both
authorization and rejection. Either outcome carries every expiry occurrence created by that one
sample, so the port cannot mutate terminal state and hide the required journal work behind an
error-only return.

## Mount ceiling

`apps/core::pairing` exposes the neutral journal port and the reviewed route coordinator, but its
production journal binding is sealed and has no public constructor. The private
`SqlitePairingJournal` is the only production implementation: it shares Core's one
single-writer-lease `SqliteStore` mutex, obtains opaque store-clock commit contexts, submits exact
canonical occurrence bytes, and converts only store-owned post-commit readback receipts. A caller
implementation or mock echo of the neutral trait cannot construct a production service.
`CoreService::new` therefore still returns 404 for `/api/v1/pairing/exchange`; the sealed
honest-store constructor must be selected explicitly to install the exchange route and ordinary
authorizer. Normal `serve` selects it only when given an exact loopback
`--ordinary-pairing-origin`; without that flag its router is unchanged.

Core also has a sealed ordinary-session authorizer for the `jpc1_` namespace. When an ordinary
service is configured, cockpit reads require `cockpit_read`, operator writes require
`operator_evidence_write`, and every request rechecks exact origin, epoch, scope, monotonic expiry,
and capability bytes. Expiry occurrences are durably appended before an expired request is
refused. Authorization uses one coherent clock sample whose outcome carries expiry occurrences on
both success and refusal, so a TTL boundary cannot fall between two samples and lose its terminal
event. The legacy raw 64-hex token is not a fallback on cockpit/operator/prospective handlers once
the ordinary authorizer is configured; the companion installation route retains its separate
legacy pairing seam. An end-to-end SQLite test covers exchange, scoped read/write admission,
durable revocation, live-session restart invalidation, seeded post-restart ordinals, and refusal of
the old capability by a reopened service. A separate SQLite reopen adversary proves that the
single sampled authorization boundary persists expiry before refusal. The normal-server opt-in
issues only Cockpit/replay read scopes unless the operator separately enables the two evidence-write
scopes. It cannot issue a signing, wallet, transaction, or execution scope.

No production presentation-mutation route exists in the current Core router. The authorizer
supports `presentation_evidence_write` and refuses a session lacking it, but the ordinary route
must remain unmounted until any future presentation handler invokes that scope check before its
own durable append.

Glass mirrors that ceiling: the production shell shows pairing unavailable unless an operational
client and the matching deliberate loopback Core opt-in are explicitly supplied. Its test client
exercises UI behavior only and is not evidence that the route or product is live.
