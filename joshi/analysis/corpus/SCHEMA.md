# bulk_pump signed-flow artifact — schema and how to query it

Built from `~/dev/joshibot/state/bulk_pump/daily/*.parquet` (READ ONLY, never modified).
Everything here lives under this scratchpad directory. Nothing was written to the joshi repo or to
joshibot.

Engine: **DuckDB 1.5.5** through the locked `analysis` env (`uv run --offline`). Chosen over pure
pyarrow because the whole job is `UNNEST` + `GROUP BY` + as-of joins over 27 GB, which DuckDB
streams and spills on its own; peak RSS stays inside the declared `memory_limit` and a full
10-day pass costs single-digit minutes. `pyarrow` is still used for the parquet footer checks.

    from ddb import connect            # scripts/ddb.py
    con = connect(memory_gb=40, threads=10)

## Tables

### `out/flow/day=YYYY-MM-DD/flow.parquet`  — 220,475,360 rows, 7.0 GB
One row per **(transaction, owner, pump-mint)** whose token balance CHANGED.
Sorted by `(mint, block_slot, tx_index)`, so a per-mint query prunes to a few row groups.

| column | meaning |
| --- | --- |
| `mint` | the pump-suffixed mint |
| `block_slot`, `tx_index` | authoritative Solana ordering; **unique together** (verified: 11,129,539 distinct pairs = 11,129,539 rows on 2026-08-09) |
| `block_time` | unix seconds, from the block |
| `owner` | the wallet / PDA that owns the token account(s) |
| `decimals` | mint decimals |
| `token_pre_raw`, `token_post_raw`, `token_delta_raw` | exact integers in raw base units, `DECIMAL(38,0)`. Summed over that owner's token accounts for the mint (`token_n_accounts` says how many) |
| `wsol_pre_raw`, `wsol_post_raw`, `wsol_delta_raw` | the SAME owner's wrapped-SOL leg in the SAME transaction, or NULL if it has none |
| `owner_has_wsol_leg` | whether that owner had any wSOL account in this transaction |
| `token_n_accounts`, `wsol_n_accounts` | account multiplicity; `>1` means the level is a sum and a two-leg pairing is ambiguous |
| `fee_lamports`, `compute_units` | transaction-level, exact |
| `tx_has_wsol`, `tx_n_pump_mints`, `tx_has_other_mint`, `tx_n_owners` | transaction shape |

### `out/trades/day=YYYY-MM-DD/trades.parquet` — 107,419,789 rows, 5.9 GB
One row per **(transaction, pump-mint)**, with the venue side identified. Same sort order.

Key columns beyond the flow ones:

| column | meaning |
| --- | --- |
| `venue_owner`, `venue_identified` | the counterparty account (bonding-curve ATA or pool vault owner) and whether it was resolvable |
| `venue_token_pre_raw` / `_post_raw` / `_delta_raw` | the venue's exact reserve levels and change — the pre-event state `StateAtEvent` wants |
| `venue_wsol_*` | same for the venue's wSOL vault, NULL when it has none |
| `taker_token_delta_raw` | **signed flow**: `+` the takers acquired the token (BUY), `-` they released it (SELL). Defined as `venue_token_pre - venue_token_post` |
| `trade_sign` | `+1` / `-1` / NULL when no venue is identified |
| `sol_leg_lamports_exact` | the SOL leg, **observed**, from the venue's own wSOL vault. NULL when not observable |
| `sol_leg_lamports_curve_model` | the SOL leg, **modelled** (curve only). Never coalesce the two silently |
| `sol_leg_quality` | `exact_pool_vault` / `curve_model_native_sol_not_observed` / `unsupported` |
| `price_sol_per_token`, `price_kind` | see below |
| `n_parties`, `n_venue_cand`, `n_wsol_paired`, `venue_token_n_accounts`, `venue_wsol_n_accounts` | why a row was or was not supported |

### `out/bars_{sol0,sol01,sol1}.parquet` — minute bars per `(mint, venue_owner, price_kind, minute)`
The suffix is the per-trade notional floor for setting a bar high/low: 0, 0.01 SOL, 0.1 SOL.
No interpolation, no forward-fill, no bar for a minute with no trade.

### `out/mint_meta.parquet` — 449,723 rows, one per mint
`first_bt`, `last_bt`, `distinct_owners`, `std_create` (a standard 1e15-raw curve seed observed
in-window), `max_curve_ata`, `curve_supply_standard`, per-price-kind transaction counts.

### `out/venue.parquet` — mint→owner participation shares (the venue identification evidence)
### `out/minutes.parquet` — per-minute transaction and slot counts for the whole window (coverage)
### `out/blocks_headline_W30_T8_M4.parquet` — the excursion blocks behind the census
### `out/boards_curve_state.parquet` — pump.fun's own `virtual_*_reserves`, extracted from the joshibot boards tape, used to validate the curve readout

## Price objects — there is no column called `price` without a `price_kind`

* `amm_pool_vault_fill` — `|Δ wSOL| / |Δ token|` at the pool's own two vaults. Exact ratio of two
  observed integer balance changes. It is the **pool vault exchange rate realised by this
  transaction**: not the taker's all-in cost (protocol and creator fees leaving to other accounts
  are outside these two legs), and not a quote for any other size.
* `curve_constant_product_readout` — **MODEL**. The pump.fun bonding curve holds SOL as native
  lamports, which this export does not carry, so no SOL amount is observed. Under the standard
  configuration `v_tok = curve_ata_balance + 73_000_000_000_000` and
  `p(lamports per raw token) = 3.219e25 / v_tok²`. Validated against pump.fun's own
  `virtual_sol_reserves` / `virtual_token_reserves`: on cleanly matched observations of
  standard-supply mints, **99.23% of 6,115 observations across 2,086 mints reproduce the board
  price to better than 1e-6 relative; median relative error 4.8e-9**.
* `unsupported` — no price. 13.4% of `(tx, mint)` rows.

## How to query

    -- one mint's ordered event stream (30 ms over 107M rows)
    SELECT block_slot, tx_index, block_time, venue_owner, price_kind,
           taker_token_delta_raw, sol_leg_lamports_exact, sol_leg_quality,
           price_sol_per_token, trade_sign, fee_lamports
    FROM read_parquet('out/trades/day=*/trades.parquet')
    WHERE mint = ? ORDER BY block_slot, tx_index;

    -- who moved, per owner, in the same transactions
    SELECT * FROM read_parquet('out/flow/day=*/flow.parquet')
    WHERE mint = ? ORDER BY block_slot, tx_index, owner;

    -- exact SOL only, never mixed with the model
    ... WHERE sol_leg_quality = 'exact_pool_vault'
