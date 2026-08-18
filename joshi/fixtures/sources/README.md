# Offline source frames

These fixtures exercise transport fidelity; they are never accounting truth.

- `pumpportal_new_token_observed_2026-08-14.json`, `pumpportal_migration_observed_2026-08-14.json`, and `pumpportal_funded_key_rejection_observed_2026-08-14.json` are copied from the prior repository's tests, which recorded them from the live PumpPortal socket on 2026-08-14. The prior recorder had parsed and reserialized the JSON, so they preserve observed fields/types but are not claimed to preserve the provider's original whitespace.
- `helius_logs_notification_official_shape.json` and `helius_subscription_ack_official_shape.json` are synthetic values in the standard Solana/Helius JSON-RPC shapes documented on 2026-08-16. They are schema fixtures, not observed market events.
- `helius_rate_limit_official_shape.json` is the JSON-RPC error shape documented by Helius. HTTP status and safe `Retry-After` headers are test inputs because they are not part of the JSON body.
- `helius_live_characterization_2026-08-16.sanitized.json` contains only schema and aggregate
  properties from one private bounded live capture. All provider payloads and public identifiers
  remain in ignored `state/probes`; this file is not replay evidence and cannot establish daily
  completeness.

Tests pass every raw-frame fixture through the adapter as bytes and require the shared evidence
draft's versioned raw-frame envelope to retain those exact body bytes. The sanitized live
characterization is parsed and checked as an aggregate contract, not passed off as a provider
frame. No fixture contains a credential, authenticated URL, wallet secret, transaction, or
transaction-building request.
