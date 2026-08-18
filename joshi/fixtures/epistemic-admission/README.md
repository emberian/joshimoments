# Epistemic-admission adversarial fixtures

These vectors document cases that must fail before a private store adapter can write an
epistemic-book occurrence, first-round seal, adjudication, score, or ensemble. They are not
durable receipts and must never be used to mint one.

- `b0-issue-before-commit.json`: violates the exact B0 ordering.
- `first-round-peer-visible.json`: a first-round producer saw a peer before its own commit.
- `reveal-before-seal.json`: a reveal predates closure of the eligible first-round set.
- `future-support.json`: an ensemble tries to consume support not strictly earlier than its
  occurrence information cutoff.
