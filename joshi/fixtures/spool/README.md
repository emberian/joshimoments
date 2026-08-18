# Spool protocol fixtures

`replication_schedules.json` is a deterministic, transport-neutral schedule corpus. The Rust
integration test interprets every operation against fresh filesystem roots and verifies that
restart, overlap, duplication, segment reordering, and partial-transfer conflict never manufacture
an acknowledgement or silently skip bytes.

The fixture intentionally contains no credentials, wallet material, endpoint names, or live source
data. Segment bodies in the test are synthetic evidence envelopes.
