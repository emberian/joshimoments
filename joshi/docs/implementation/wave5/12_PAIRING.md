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
capability in that mode. The headed Cockpit V2 read route is mounted only by this constructor; its
response embeds the exact store-revalidated publication and head bytes, commit sequences, and byte
digests. Tests cover wrong scope, revoke, expiry, and restart refusal.

`Serve` continues to construct `CoreService::new`, so the exchange and Cockpit V2 route are absent
from the default server and the production Glass shell remains unavailable. The opt-in integration
test is an isolated durable protocol/publication pass, not a product mount, daily-use witness, or
root G0 pass.

Production adapters provide an OS-backed `Entropy` implementation and a monotonic `MonotonicClock`;
the crate performs no wall-clock or device I/O. Public transitions use the monotonic-clock
adapter; raw timestamp transitions are crate-private and reject rollback. `parse_pairing_occurrence` and
`parse_pairing_session_descriptor` are strict canonical inbound decoders. Duplicate active code
or capability bytes are rejected, and a failed duplicate capability restores the consumed code.

The fixtures in `fixtures/pairing/` contain no live capability. Pure tests inject test-only entropy;
production-boundary tests use the SQLite journal and OS entropy and assert exact readback, origin,
scope, expiry, restart, revocation, rate carry-forward, domain separation, rollback refusal, and
redaction behavior.
