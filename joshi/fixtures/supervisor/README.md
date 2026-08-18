# W4-01 supervisor fixtures

`fake_provider_24h.json` is a 24-hour virtual-clock schedule. It produces one exact fake frame every
hour, deterministic duplicate content, retryable failures, disconnect generations, explicit
gaps, and graceful shutdown. Setting `realtime` through the collector CLI uses the same schedule and
state machine with wall-clock sleeps; tests always use accelerated time.

`kill_failpoint_matrix.json` is the enumerated crash contract. The Rust suite uses real child
processes killed after a durable reservation, after an in-memory bounded enqueue, and after local
spool durability. Separate injected fsync/rename transitions cover deterministic recovery inside
the journal and spool handoff.

Fixtures have no endpoint, credential, wallet, transaction, or economic authority.
