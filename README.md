# joshimoments

Two repositories that grew up together, published with their full histories intact.

- **[`joshi/`](joshi/)** — the observatory. A Rust + Python workspace for an accessibility-first,
  human-directed market observatory over Pump.fun and adjacent Solana markets. 304 commits.
- **[`joshibot/`](joshibot/)** — the sentinel and the studies corpus. A local-first, sell-only
  position monitor that grew into the research. 319 commits.

Neither history was squashed and no authorship was rewritten; each subdirectory keeps its own
root-to-tip history, joined by a single merge commit.

## Why they belong in one repository

`joshi` starts from a deliberately narrow claim: that the operator's actual decision process had
never been *measured*, only projected onto a few numeric features and then judged. So it builds the
apparatus to observe the real loop at high resolution before modeling it — a domain spine of 37
Rust crates, a collector, a web board, an analyst jail, and a large body of design documents.

`joshibot` is where the measuring actually happened. Its `studies/` directory holds 50 study
programs and 64 written results under a pre-registration discipline: a `REGISTRATION_*.md` written
*before* the run, then a `RESULT_*.md` that reports the null as readily as the finding. Several
document their own corrections — a claimed 7× that turned out to be a currency mislabel, a
caller-cluster value overturned by four independent disproofs.

## What is not here

The **data is excluded** — roughly 216 GB of chain snapshots, parquet corpora, price caches, tapes
and API captures. None of it is in the history either; both repositories treated data as ignorable
from the start. The collectors that build the caches are here; the caches are not, so **the studies
will not re-run as-is.** They are published as method, reasoning, and reported results.

Provider API keys are read from local files at runtime (`joshibot/shitcoims_sentinel/secrets.py` is
a permission-checking loader, not a store). There are no credentials in the source or in the
history.

## Wallet addresses

Every operator-owned Solana address has been replaced, in the working tree and throughout the
history, with a synthetic placeholder that is a well-formed 32-byte public key but sits *off* the
ed25519 curve — so no private key can exist for it. See
[`joshi/WALLET_PLACEHOLDERS.md`](joshi/WALLET_PLACEHOLDERS.md) for the mapping and the reasoning.
Third-party addresses that are the subject of the research are public chain data and remain.

## Suggested reading order

1. [`joshi/README.md`](joshi/README.md), then `joshi/JOSHI_THOUGHT.md` — the premise and the long argument for it.
2. `joshibot/studies/PANEL.md` and a few `RESULT_*.md` — how a claim gets made, and killed, here.
3. [`joshi/docs/research/lanes/`](joshi/docs/research/lanes/) — the independent investigations.
4. `joshi/docs/microstructure/trades_quotes_prices/` — the market-microstructure distillation.
5. `joshi/crates/joshi-domain/` — where the vocabulary becomes types.

## License

`AGPL-3.0-or-later`. Copyright (C) 2026 Ember Arlynx. See [`LICENSE`](LICENSE).

All first-party work by a single copyright holder. Third-party dependencies remain under their own
licenses, and captured or provider-derived fixtures retain their own provenance; the project
license replaces neither. See `joshi/THIRD_PARTY_NOTICES.md` and
`joshi/docs/implementation/LICENSING.md`.
