# Retention adversarial fixtures

`adversarial.v1.json` is a semantic schedule, not an instruction to mutate a filesystem or erase a
key. Each step is an append-only occurrence or an inventory fact. A harness should replay exact
steps, retry the same occurrence after every simulated crash boundary, and assert that refusal
closure and the `coverage_effect: unchanged` marker are stable.

The cases cover an incomplete replica, an outstanding export/derived reference, a stale receipt,
an incomplete key-erasure scope, and an exact idempotent retry. The fixture deliberately contains
no credential, key bytes, path, shell command, or deletion operation.
