# G0 fault fixtures

These are shape fixtures, not receipts and not a qualification witness. The
schedule is deterministic: one no-fault baseline and one post-transition kill
for each required G0 seam. `run_manifest_template.json` deliberately contains
invalid digest placeholders; a real run must calculate the schedule digest from
the canonical schedule bytes and replace every placeholder before parsing.

The isolated `apps/g0-harness` package rejects omitted, reordered, duplicate,
or otherwise noncanonical required steps. Its current adapter-free result is
always `fullOfflineFaultWalk: false` and reports a typed `not_implemented` or
`blocked` disposition for every step.
