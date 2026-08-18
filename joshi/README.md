# joshi

`joshi` is a research and implementation workspace for a personal, accessibility-first,
human-directed market observatory and trading cockpit for Pump.fun and adjacent Solana markets.

The project begins from a deliberately narrow claim: Ember's actual process has not yet
been measured. Existing work repeatedly projected fragments of that process onto a few
numeric features, tested the projection, and treated the result as a verdict on the whole.
This repository starts by constructing the experimental apparatus needed to observe the
real loop at high resolution.

The intended system eventually combines:

- a market-wide, Pump-like information surface;
- high-fidelity observation of the slice receiving human attention;
- explicit gestures for crackles, partial exits, retained runners, exits and re-entries,
  catalyst/fancoin positions, LP inventory, and later-discovered dispositions;
- executable quote, fill, fee, latency, and portfolio accounting;
- social/community/identity transition histories;
- immediate annotations and replay-backed postmortem interviews;
- model-free empirical study first, with learned models and policy synthesis only after
  the observation language is adequate.

The repository is now implementing its **read, record, replay, render, and analyze substrate**.
It contains no wallet keys, signer, live executor, or authorization to trade.

## Documents

- [`docs/PROJECT.md`](docs/PROJECT.md) — initial problem statement, vocabulary, and invariants.
- [`docs/research/lanes/`](docs/research/lanes/) — independent R&D investigations.
- [`docs/research/engineering/`](docs/research/engineering/) — runtime, storage, UI, protocol,
  verification, cost, and delivery-option investigations.
- [`docs/research/reviews/`](docs/research/reviews/) — coherence and vertical-slice reviews across
  all lanes.
- [`docs/decisions/FOUNDATION.md`](docs/decisions/FOUNDATION.md) — reconciled semantic architecture
  and build-versus-buy boundary.
- [`docs/decisions/PRE_ENGINEERING_PROGRAM.md`](docs/decisions/PRE_ENGINEERING_PROGRAM.md) — Spike 0,
  staged product slices, gates, and stop conditions.
- [`docs/decisions/RESEARCH_PROGRAM.md`](docs/decisions/RESEARCH_PROGRAM.md) — estimands, study order,
  falsifiers, and reporting contract.
- [`docs/decisions/ENGINEERING_FOUNDATION.md`](docs/decisions/ENGINEERING_FOUNDATION.md) — provisional
  runtime, topology, storage, language-budget, and assurance decision.
- [`docs/decisions/ENGINEERING_CORRIDOR.md`](docs/decisions/ENGINEERING_CORRIDOR.md) — bounded stack
  falsifier and historical narrow delivery corridor, partially superseded by the broad-base
  program.
- [`docs/implementation/PROGRAM.md`](docs/implementation/PROGRAM.md) — active broad-base build
  program, capability boundaries, lane ownership, and first integration gate.
- [`docs/reference/SESSION_HISTORY.md`](docs/reference/SESSION_HISTORY.md) — ClusterVision-derived
  steering history and correction trail.
- [`docs/reference/JOSHIBOT_COMPOST.md`](docs/reference/JOSHIBOT_COMPOST.md) — what to transplant,
  retain as scoped evidence, or reject from `~/dev/joshibot`.
- [`docs/reference/READING_GUIDE.md`](docs/reference/READING_GUIDE.md) — a market-microstructure and
  AMM reading sequence matched to the project.

## License

Unless a file or provenance record says otherwise, Joshi's original source code and original
documentation are licensed under the [GNU Affero General Public License, version 3 or later](LICENSE)
(`AGPL-3.0-or-later`). Copyright (C) 2026 Joshi contributors.

Third-party dependencies, generated bundles containing them, and captured or provider-derived
fixtures remain subject to their own copyright and license terms. The project license does not
claim ownership of those materials. See [the licensing policy](docs/implementation/LICENSING.md)
and [third-party notices](THIRD_PARTY_NOTICES.md) before distributing or hosting a modified build.
