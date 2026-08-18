# Wave 5 ordinary pairing

`joshi-pairing` is the pure, ordinary same-origin pairing waist. It owns a service-memory
registry, not a listener, route, store, browser session, wallet, or launch authority.

`PairingRegistry<E>` issues a 32-byte test/OS-entropy code, stores only its zeroizing hex bytes in
memory, and consumes it exactly once. Code and capability comparisons use a fixed 64-byte
constant-time loop. Public `PairingOccurrence` and `PairingSessionDescriptor` values contain
only nonsecret IDs, exact origin, epoch, scope, and expiry metadata; secret bytes have no serde or
ordinary `Debug` representation and are never hashed or logged.

The exact origin is bound at issue, consume, and authorize. Failed-code attempts are bounded by a
configurable window; wrong-origin requests do not consume a code. Expiry, explicit revocation, and
monotone restart epochs invalidate codes and sessions. Restart drops all pre-restart zeroizing
state, and the next epoch cannot authorize an old capability.

`PairingSessionPort` is the narrow adapter for a route/store owner. The registry remains the only
implementation here, and all returned values are semantic metadata. Prospective launch-bound
pairing is a separate future protocol and is intentionally absent from this contract.

Production adapters provide an OS-backed `Entropy` implementation and a monotonic `MonotonicClock`;
the crate performs no wall-clock or device I/O. `parse_pairing_occurrence` and
`parse_pairing_session_descriptor` are strict canonical inbound decoders. Duplicate active code
or capability bytes are rejected, and a failed duplicate capability restores the consumed code.

The fixture in `fixtures/pairing/ordinary_pairing_v1.json` is deterministic metadata only and is
marked nonproduction by this document; it contains no code or capability. Tests inject
`TestEntropy` and assert replay, origin, expiry, restart, revocation, rate, and redaction behavior.
