# Portfolio truth — statement, route, rail

Status: portfolio deputy, 2026-08-22. The statement engine and CLI landed this session; the core
route and Glass rail below are SPEC ONLY, written so the living-scene lane can land them without
redesign. Nothing here grants trading, signing, or submission authority; everything is a read of
durable observations.

## What already runs

- `joshi_accounting::portfolio` — `PortfolioStatementV1` and `derive_statement(PortfolioInput)`:
  a pure function from observed balance transitions (plus optional labelled prices, DLMM position
  lines, provider assertions, and page/head coverage) to one statement. Per-boundary balances are
  reconciled as post→pre chains; a nonzero first `pre` is opening inventory, unobserved; a break
  is reported, never repaired. Prices are labelled objects (`provider_mark` | `venue_marginal`)
  with their own provenance and clock; an absent price renders absent; the valuation section has
  **no total field at all** — only per-kind sums beside an `unpricedHoldings` count and a
  composition note.
- `joshi_wallet_source` read-back: `classify_locator`, `parse_retained_envelope`,
  `normalize_stored_body` (the read-back twin of `normalize_frame` — same normalization, stored
  observation identity instead of freshly drafted evidence), `balance_events_for_wallet`,
  `signature_page_entries`, `chain_head_slot`.
- `joshi-portfolio` bin (in `crates/joshi-wallet-source/src/bin/`):
  `joshi-portfolio --catalog <dir> --wallet <pubkey> [--source <id>]... [--label <mint>=<name>]...
  [--json]`. Opens the catalog `StoreMode::ReadOnly`, walks
  `source_observations_as_known`, derives, prints human text or the exact JSON statement.
  `--label` is display-only ("operator label"), never part of the statement.

Wire contract: `joshi.portfolio_statement.v1`, camelCase, integers as decimal strings (WireU64/
WireU128), every number beside an `ObservationRef {observationId, commitSeq}`.

## Core route (spec)

`GET /api/v1/portfolio/statement?wallet=<pubkey>` in `apps/core/src/service.rs`, beside the glass
snapshot routes.

- Body: exactly the `PortfolioStatementV1` JSON the CLI's `--json` emits, wrapped the way the
  other glass routes wrap payloads (statement + `servedAt` serve clock). Do not flatten or
  re-derive fields in the handler; the statement is the contract.
- Derivation: identical pipeline to the bin (`source_observations_as_known` → readback →
  `derive_statement`), against core's own catalog, at the current durable cutoff. The handler adds
  a serve clock only; it must not add prices, totals, or freshness claims the statement lacks.
- `wallet` is required; no default wallet is baked into core. 404 with a typed refusal when the
  catalog holds no observations for the configured sources.
- When a price-bearing sweep lands later (`balance_tokens` provider marks, or venue-marginal
  quotes from retained curve/pool state), those enter as `PriceObjectV1` inputs to the derivation
  — never as handler-side decoration.

## Glass rail (spec)

A `PortfolioRail` component beside EpisodeRail, fed by the route above through the existing data
client. Rendering rules are the statement's honesty rules:

- One row per holding: label (operator label if the operator supplied one, else the mint),
  balance rendered at its stated decimals, and **"as of slot N / block time T"** — never "now".
- Price cell: the labelled price kind and age when present; the literal word "absent" when
  absent. Never 0, never a dash that could read as zero.
- No headline portfolio total. The valuation block renders the per-kind sums with their
  composition note and the unpriced count, exactly as stated.
- A derivation disclosure per row (collapsible): opening inventory line, chain continuity
  (broken chains render loudly), and the observation ids / commit seqs.
- Coverage strip at the bottom: chain head vs. latest balance slot, unfetched page signatures
  count, and the named absences verbatim — the resting-order absence is a permanent fixture of
  this rail, not an error state.

## Known limits (state them, do not paper over them)

- The catalog does not retain which address a `getAccountInfo` read asked about, and the response
  does not restate it; a decoded DLMM position is therefore identified as `unstated:<obsId>`
  until the sweep retains the request scope. DLMM token legs need the pair's bin-array reserves;
  until those are swept, the position line carries `legs: not_derivable` with the reason.
- The sweep's requested commitment is not retained; read-back states a `confirmed` floor and says
  so in a note.
- There is no store reader that lists registered sources, so the CLI defaults to
  `helius.http.solana.v1` and accepts `--source`. A `sources_as_known` reader on `joshi-store`
  would remove that default (store territory; same gap the hot-lease readback already documents).
