# Joshi collector

`joshi-collector` is the local continuity shell and sealed Wave 5 C0 runtime. It exposes:

- `run --root <collector-root> --registration <json> --build <json> --source-tree <json>
  --config <json> --budget <json> --privacy <json> --surface-profile <json> --plan <json>
  --fixture <json-body>`;
- `replay --root <collector-root> [--private-key-file <owner-only-raw-32-byte-path>]`;
- `fake-provider --root <collector-root> --fixture <path> --hours <1..24> [--realtime]`; and
- `health --root <collector-root>`.

`run` requires the exact seven-document run closure plus a provider plan whose template digest is
closed by the registered configuration and whose final digest is bound to that run occurrence. It
accepts only the sealed, one-operation, no-network `C0` plan. The fixture is emitted once as exact
raw JSON evidence; every request/page/byte/time ceiling is reserved before the synthetic attempt,
and evidence or an explicit source gap is fsync-complete before budget settlement. Reusing a run
whose journal already contains an attempt is refused instead of resetting its runner or budget.

There is no live-provider adapter, credential load, public/local listener, daemon unit, remote-host
control, catalog writer, wallet integration, transaction construction, signing, submission, or
economic action. `run` and `fake-provider` never open a socket. `C1`/`C2` plans remain disabled
pending canonical source admission and a durable run receipt.

The root layout is:

```text
<collector-root>/
  identity/
  journal/events/
  spool/{staging,ready,acks,catalog_acks,quarantine}/
  health/snapshot.json
```

Private replay is optional. The argument contains only a path; the file must be regular, deny all
group/other Unix permissions, and contain exactly 32 raw bytes for the single key ID already named
by private spool metadata. The bytes are zeroized after constructing the in-memory protector.
