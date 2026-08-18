# Adversarial evidence-tape fixture

This is a small synthetic trace for the storage and replay boundary. It is deliberately readable
by hand and must run offline. It contains no wallet, credential, secret, live source call, trade
authority, historical-market claim, PnL claim, or real Parquet interoperability claim.

`load.sql` inserts the trace. `expected.sql` checks its semantic distinctions. `manifest.json`
names the cases and exact external artifact hashes. Files under `blobs/sha256` are exact retained
payload bytes. `exports/snapshot-manifest.json` is the immutable parent closure for the opaque
Parquet-shaped stand-in under `exports`; it proves write-first hash/path/manifest semantics only.
A later export lane must add a real Parquet golden.

The fixture proves these cases at the catalog boundary:

- two acquisition occurrences share one exact blob without becoming one observation;
- a single raw transaction contains two distinct events with equal typed amounts;
- redelivery of the transaction does not mint new source-event or assertion identities;
- an unknown future source variant remains inspectable raw evidence;
- a source gap is detected, partially recovered, completely recovered, and only then advances its
  cursor through the recovered observations;
- a decoder correction has old valid time and later system-known time, preserving both assertions;
- witnessed replay at commit 6 sees the first assertion while retrospective replay through commit
  11 sees the correction;
- runner retention, exact-flat assertion, continued flat watching, and re-entry into a fresh
  inventory epoch remain distinct operator records; and
- command identity is idempotent and structurally unable to exceed `observe_only` / `evidence_only`.
- every legacy query row has the V5 lossless typed sidecar required to reconstruct acquisition
  clocks, variants, coverage boundaries, recovery evidence, protection domain, and scoped cursor
  authority.

The operator episode assertions in this fixture are claims recorded from commands, not landed
financial facts. The financial ledger must independently reconcile actual wallet effects before it
can call an inventory epoch flat or a re-entry filled.

Run the complete validation from the repository root with `schema/validate.sh`.
