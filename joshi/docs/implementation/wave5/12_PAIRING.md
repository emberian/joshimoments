# Wave 5 ordinary pairing

`joshi-pairing` is the pure, ordinary same-origin pairing waist. Core supplies the only production
adapter: OS entropy, a monotonic-anchored wall clock, and the sole SQLite journal. The default
server still does not select that adapter.

`PairingRegistry<E>` receives 32-byte OS entropy through its injected production port,
domain-separates code and capability material before storage, stores only zeroizing hex bytes in
memory, and consumes a code exactly once. Code and capability comparisons use a fixed 64-byte
constant-time loop. Public `PairingOccurrence` and `PairingSessionDescriptor` values contain
only nonsecret IDs, exact origin, epoch, scope, and expiry metadata; secret bytes have no serde or
ordinary `Debug` representation and are never hashed or logged.

The exact origin is bound at issue, consume, and authorize. Failed-code attempts are bounded by a
configurable window; wrong-origin requests do not consume a code. Expiry, explicit revocation, and
monotone restart epochs invalidate codes and sessions. Restart drops all pre-restart zeroizing
state, and the next epoch cannot authorize an old capability.

The SQLite journal retains exact nonsecret occurrence bytes and rate windows before a one-time code
or capability is returned. Restart begins a higher origin-scoped epoch, invalidates prior live
state, carries the bounded rate budget forward, and seeds the next occurrence ordinal from durable
readback. No secret code or `jpc1_` capability is serialized into the journal.

## Opt-in Core seam and default nonclaim

The opt-in Core constructor mounts the human-checkable `JOSHI-…` one-time-code exchange and issues
an origin-, epoch-, expiry-, and scope-bound `jpc1_` capability. Cockpit and operator handlers use
that ordinary capability when the adapter is present and never fall back to the legacy raw-hex
capability in that mode. The headed Cockpit V2 index/open routes are mounted only by this
constructor. The bounded index reparses every body/head through the store and refuses to truncate
more than 256 eligible heads; the open response embeds the exact store-revalidated publication and
head bytes, commit sequences, and byte digests. Tests cover wrong scope, revoke, expiry, restart
refusal, exact index identity, and default route absence. Browser GETs may omit `Origin` under the
Fetch standard, so authorization instead requires the configured loopback authority to equal
`Host`, requires exact same-origin Fetch Metadata, and rejects any supplied nonmatching or
ambiguous `Origin`; exchange and write POSTs still carry and validate the exact origin.

`Serve` remains unmounted by default. A deliberate `--ordinary-pairing-origin` option selects the
sealed SQLite adapter for one exact plain-HTTP `localhost`, `127.0.0.1`, or `[::1]` browser origin,
only while the API listener itself is also loopback. Core binds the listener before issuing and printing a
one-time code. Its default scopes are `CockpitRead` and `ReplayRead`; the separate
`--ordinary-pairing-evidence-write` switch adds only `OperatorEvidenceWrite` and
`PresentationEvidenceWrite`. Transaction, signing, wallet, and execution scopes do not exist.
The write switch is rejected unless the origin option is present, and neither option changes the
no-network/provider policy or establishes product qualification.

Glass selects the normal-server client only when built with `VITE_JOSHI_ORDINARY_PAIRING=1` (the
`npm run dev:paired` script). Its full operational surface requires both evidence-write scopes and
clears/refuses a read-only session before listing or opening a publication. The separate fixture
inspector remains the bounded read-only UI. Pairing material stays in page memory in both cases.

The explicit `wave5-g0-inspect` developer command remains the narrower fixture inspector: it first
exact-retries the offline G0 component, refuses impossible positive qualification bits, reopens its
fixture catalog, binds a caller-declared loopback Glass origin, generates the unrelated legacy
handler guard from OS entropy without a file, and prints one OS-random `CockpitRead` code only after
the listener is bound. It does not enable write scopes. This is an isolated durable
protocol/publication inspection seam, not a product mount, daily-use witness, or root G0 pass.

`wave5-g0-inspector-smoke` is a finite, socket-free execution of that mounted route over an already
completed fixture catalog. It performs a durable one-time exchange, opens the exact headed bytes,
starts a higher SQLite epoch, proves the old capability is unauthorized, and repeats the same open
under a fresh session. Its report retains only nonsecret occurrence/session IDs and digests. This
is paired API/restart evidence, not a default mount, browser presentation, or product-use witness.

Glass's explicit `VITE_JOSHI_G0_INSPECTOR=1` build now consumes this seam and only this seam. It
independently verifies the bounded index plus exact V2 body/head and renders descriptive fixture
facts without operator/presentation controls. The default build does not select it, and attached
browser QA remains not run because no browser instance was connected.

Production adapters provide an OS-backed `Entropy` implementation and a monotonic `MonotonicClock`;
the crate performs no wall-clock or device I/O. Public transitions use the monotonic-clock
adapter; raw timestamp transitions are crate-private and reject rollback. `parse_pairing_occurrence` and
`parse_pairing_session_descriptor` are strict canonical inbound decoders. Duplicate active code
or capability bytes are rejected, and a failed duplicate capability restores the consumed code.

The fixtures in `fixtures/pairing/` contain no live capability. Pure tests inject test-only entropy;
production-boundary tests use the SQLite journal and OS entropy and assert exact readback, origin,
scope, expiry, restart, revocation, rate carry-forward, domain separation, rollback refusal, and
redaction behavior.
