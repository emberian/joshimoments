# RESULT: bulk historical tape — replay-grade, complete, ~$27 for 22 days

**Date:** 2026-08-14 · **Tool:** `scripts/bulk_history.py` · **Status:** source chosen, validated
against live ground truth, run end to end.

---

## Bottom line

The operator asked whether we can sync bulk data instead of paying ~206% of the monthly Helius
plan to backfill 22 days by RPC. **Yes — and the bulk path is not a downgrade. It is strictly more
informative than the RPC path, and it costs about $27.**

`bigquery-public-data.crypto_solana_mainnet_us.Transactions` carries full transaction meta:
`pre_token_balances` / `post_token_balances` with `amount` as **BIGNUMERIC** — exact integers, no
float anywhere — plus `fee`, `err`, `index` and `compute_units_consumed`.

Validated against every swap the live RPC collector had independently recorded on 2026-08-13,
across all pools:

> **876 of 876 present. 876 of 876 matched on BOTH pre and post reserves — every digit, both
> vault legs, zero disagreements. Recall 100.0%.**

That is **replay-grade**. Reserves are what make an exact AMM fill replayable, and they are here.

Two capabilities this path has that `getTransaction` does not:

- **`index`, the transaction's position within its block.** `shitcoims_cluster.parse` documents
  intra-slot ordering as *unrecoverable* from `getTransaction`, which matters because 57 of 158
  observed slots on nosis/SOL carried more than one transaction. This column resolves it —
  present on **368,795 of 368,795** rows pulled.
- **Failed transactions.** `err` is non-empty on a revert, so reverts arrive in the same scan as
  fills. In the live tape attempts outnumber swaps **6.5 to 1** (19,061 vs 2,937), so this is most
  of the competitive signal, and here it is free. **But see the caveat below — they are emitted as
  `failed`, not as `attempt`, and the two are not the same thing.**

**Cost: ~263 GB scanned per day** (measured on the real run; 269.8 GB was the dry-run bound). One
day is free inside the 1 TiB/month tier; the full 22 days is ~5.9 TB = 5.4 TiB → **~$27** after the
free tier.

### The one place a bulk row must not be read as a live row: `failed` ≠ `attempt`

A failed transaction moved nothing, so its token balances cannot say whether it *meant* to trade
this pool or merely listed the pool's vaults while failing somewhere else. Measured on 2026-08-13,
nosis/SOL shows **105,457 `failed` rows here against 4,336 `attempt` rows in the live tape — a ~24x
gap.** Reading them as attempts would inflate an attempt-rate study by more than an order of
magnitude, which is exactly the class of silent overcount this project keeps paying for.

So they are emitted as `kind: "failed"`, deliberately *not* as the live tape's `attempt`.
Narrowing them to genuine attempts needs to know which program was invoked — and `log_messages` is
only **3.1 GB/day**, so that is a cheap next increment. It is left undone rather than guessed at.

---

## Correction to an earlier version of this document

An earlier draft of this study concluded that the dataset had **no reserves anywhere** and that
bulk could only ever be summary-grade. **That conclusion was wrong, and the error is worth
recording because it was an error of method, not of arithmetic.**

The initial `bq ls` was piped through `head -40`, and the dataset's multi-line label formatting
meant the output was truncated at five tables. The dataset actually has eight. The truncation hid
`Transactions` — the one table that carries reserves — and every downstream conclusion inherited
that gap. A background research agent tasked with pricing other vendors independently identified
`Transactions` with its `pre/post_token_balances`, which is what prompted re-checking.

The lesson is narrow and mechanical: **a truncating pipe on a discovery command is not a listing,
it is a sample.** Enumeration that a conclusion rests on has to be complete and machine-read
(`--format=json`, count the rows), never eyeballed through `head`.

The rejections below stand — they were measured directly and re-verified — but the headline
verdict is reversed: bulk *does* deliver reserves.

---

## The options, measured

All BigQuery figures are real, measured against project `manifest-quasar-414607` (the gcloud
default project has the BigQuery API disabled; pass `--project` or set `BULK_HISTORY_PROJECT`).
Total spend for the entire investigation, tool development and end-to-end runs included:
**~0.7 TiB, $0.00 actual** — everything fit inside the free tier.

### The dataset

Fresh to within ~3 hours (the 2026-08-14 partition already held 29,896 blocks when queried).
Eight tables; the four that mattered:

| table | rows | size | partition | cluster |
|---|---:|---:|---|---|
| **`Transactions`** | 5.63e11 | 938.3 TB | DAY on `block_timestamp`, required | **`signature`** |
| `Instructions` | 1.14e12 | 936.8 TB | DAY, required | `program_id` |
| `Token Transfers` | 1.45e11 | 43.9 TB | DAY, required | none |
| `Accounts` | 1.64e8 | 0.14 TB | MONTH | none |

### 1. `Transactions` — CHOSEN

Complete, exact, and uniformly populated. Transactions per UTC day across the whole target window:

```
07-24 278.5M   07-29 299.4M   08-03 292.5M   08-08 297.2M   08-13 310.4M
07-25 255.0M   07-30 292.9M   08-04 309.8M   08-09 309.1M   08-14  51.8M (day in progress)
07-26 264.1M   07-31 285.5M   08-05 294.7M   08-10 312.0M
07-27 295.8M   08-01 260.2M   08-06 292.9M   08-11 313.8M
07-28 296.2M   08-02 263.6M   08-07 301.2M   08-12 266.7M
```

No collapse, no gap, 255M–314M throughout. This is the property `Token Transfers` lacks.

### 2. `Token Transfers` — rejected: exact but not populated

It genuinely contains inner CPI transfers and its `value` is a raw integer; on the one day where
coverage exists, 9 of 9 swaps matched the live tape's vault deltas exactly. But across six sampled
months `mint IS NULL` on **92–96%** of rows, our four cluster mints show **1–7 transfer rows per
day** against hundreds of real swaps, and of the same 528 known-good swaps it contained **zero**.

| day | total rows | WSOL rows | null-mint % |
|---|---:|---:|---:|
| 2026-02-01 | 96,057,774 | 2,433 | 96.3 |
| 2026-05-01 | 56,408,085 | 319,070 | 92.1 |
| 2026-07-05 | 79,926,733 | 3,280 | 95.8 |
| 2026-07-28 | 94,899,755 | 2,586 | 94.2 |
| 2026-08-11 | 107,453,910 | 14,488 | 95.9 |
| **2026-08-12** | **216,717,409** | **42,627,164** | **55.6** ← one-off reload, 2x rows |
| 2026-08-13 | 122,628,992 | 3,302,998 | 90.1 |

It also carries **deltas only, never levels**, and cannot represent a failed transaction at all —
a failed swap moves no tokens. Even fully loaded it would be summary-grade.

### 3. `Instructions` — rejected: no inner instructions

`COUNTIF(parent_index IS NOT NULL) = 0` across a full day of PumpSwap (25,360,281 instructions).
It holds a top-level PumpSwap instruction for only **224 of 528 (42.4%)** known-good swaps; the
other 57.6% are aggregator-routed and invisible. It also carries the *requested* Anchor args, never
the realised fill. A tape omitting 57.6% of fills, biased toward exactly the routed/bot flow we
care about, is not a tape.

### 4. `Accounts` — rejected: **zero rows** for every cluster pool address.

### 5. Dune / Flipside — not needed, and they are a downgrade

Both expose *decoded trade* tables (`dex_solana.trades`, `solana.defi.fact_swaps`): amounts,
prices and traders, but not pool state. They would deliver summary-grade at best, which BigQuery
now beats on fidelity **and** on price. Worth keeping only as a cross-check on swap counts.

### 6. Solana Foundation GCS ledger archives — impractical, with numbers

`gs://mainnet-beta-ledger-us-ny5/` is real and reachable but **requester-pays**, and this account's
billing is closed (`HTTPError 403: billing account … is disabled`). Past that wall the arithmetic
settles it: per-epoch RocksDB snapshots, an epoch is ~432,000 slots ≈ 2.2 days, so 22 days is ~10
epochs at multiple TB each — **tens of TB of egress against 1.9 TB free on /tank**, before any of
it is usable, since a raw ledger must be replayed by a validator to yield transactions. Ruled out.

---

## Cost model: why `pull` scans the whole day

BigQuery bills on bytes scanned, and on this table the bill is set by **which columns you touch,
not how many pools you filter for**. Measured per column, one day:

```
balance_changes 434.1 GB    accounts 267.0 GB    post_token_balances 114.4 GB
pre_token_balances 114.3 GB signature 30.7 GB    err 7.8 GB    fee 7.5 GB
compute_units 7.5 GB        index 5.0 GB         block_slot 5.0 GB    log_messages 3.1 GB
```

The replay set — `signature`, `block_slot`, `block_timestamp`, `index`, `fee`, `err`,
`pre_token_balances`, `post_token_balances` — is **269.8 GB/day**. `accounts` (the signer list)
would double it, so it sits behind `--with-signers`. `balance_changes` is never touched.

Signature filtering *does* prune, since `signature` is the clustering key — measured **13.6 GB for
200 signatures** and **34.2 GB for 528**, i.e. ~65 MB per transaction. But that only beats a
full-day scan below ~4,000 transactions/day, and the cluster sees **11,103** (2026-08-13) to
**65,884** (2026-08-14) transactions/day touching its pools. So the full-day scan wins by a wide
margin, and `pull` uses it.

Costs below use the **measured** 263.13 GB pull + 2.48 GB preflight per day, not the dry-run bound.

| what you want | scan | cost after 1 TiB free tier | without free tier |
|---|---:|---:|---:|
| 1 day, replay-grade | 266 GB | **$0.00** | $1.51 |
| 1 week, replay-grade | 1,859 GB | **$4.32** | $10.57 |
| **22 days, replay-grade** | **5,843 GB** | **$26.97** | $33.22 |
| 22 days + signer lists | 11,717 GB | $60.36 | $66.61 |
| 22 days, replay-grade, by RPC | — | **206% of the monthly Helius plan** | — |

---

## Vault discovery is inherent, not tabulated

`pools.py` is deliberate that a pool's vaults are exactly the token accounts whose `owner` is the
pool address, and that hard-coding a vault table per DEX creates a second source of truth that
drifts. This tool needs no vault list at all — the query filters on
`post_token_balances.owner IN (pool addresses)`, so **vault discovery happens in the WHERE clause**
and is protocol-agnostic across PumpSwap and Meteora alike.

This paid off immediately and by accident. Mid-investigation another agent landed `cluster: watch
all eleven pools`, extending `CLUSTER_POOLS` from 7 to 11. Because the tool **imports**
`CLUSTER_POOLS` rather than copying addresses into itself, the very next run picked up all eleven
with no edit — and the run's own output shows real activity on three of the four new edges. An
earlier draft of this tool derived vaults from the live tape instead, which would have silently
skipped every pool the collector had not yet recorded a swap for. Importing the authority beats
mirroring it.

---

## The run actually executed

```
python3 scripts/bulk_history.py selftest                                   # 29/29 offline
python3 scripts/bulk_history.py pull --start 2026-08-13 --end 2026-08-13 \
    --project manifest-quasar-414607 --out state/bulk_history
python3 scripts/bulk_history.py verify --out state/bulk_history
```

**Preflight** — 2.48 GB, `2026-08-13 LOADED, 310,361,742 transactions, 100.0% of window median`.

**Pull** — dry-run bound 263.13 GB, **actual billed 263.13 GB ($1.50 on-demand, $0.00 in free
tier)**. 356,535 transactions folded into **368,795 rows across all 11 pools, 0 defects**, 413 MB
of JSONL.

| pool | dex | swap | failed | liquidity | reference |
|---|---|---:|---:|---:|---:|
| nosis/SOL | pumpswap | 5,898 | 105,457 | 0 | 234,365 |
| weave/SOL | pumpswap | 2,185 | 3,932 | 0 | 4,826 |
| DREGG/SOL | pumpswap | 508 | 1,242 | 0 | 275 |
| weave/SOL (DLMM) | meteora_dlmm | 230 | 2,810 | 18 | 4,517 |
| SOLVE/SOL | pumpswap | 133 | 127 | 0 | 6 |
| weave/DREGG (5%) | meteora_dlmm | 95 | 684 | 9 | 4 |
| weave/nosis | meteora_dlmm | 49 | 400 | 5 | 273 |
| DREGG/nosis | meteora_dlmm | 46 | 426 | 4 | 271 |

9,144 swaps in total: **8,724 replay-grade** (constant product) and 420 summary-grade (DLMM, by
nature). `tx_index` present on **368,795 of 368,795** rows. The three pools with no rows are among
the four added the same day; the other new edge, `weave/DREGG (5%)`, shows 95 swaps — an edge the
live collector had not yet observed.

**Verify, against the live RPC tape:** 876 comparable swaps, **876 exact pre+post reserve matches,
0 disagreements, 0 absent — 100.0% recall.** This compares *levels*, not just deltas, which is the
whole difference between a replay tape and a summary one.

**Idempotency/resumability:** re-running skips completed days and reports $0.00; preflight is
cached so re-measuring is free. Writes are atomic (temp + rename), and every output file records
source, full query text, query SHA-256, job id, billed bytes, extraction time and that day's
completeness measurement. The run above was executed **twice** — once to produce the tape and once
more after the `failed`/`attempt` correction, to make sure the shipped code is the code that ran.

---

## Schema compatibility: where bulk rows map, and where they don't

Rows carry `"schema": "bulk_history.v2"` and are **not** drop-in `shitcoims_cluster` swap rows —
the marker is the guard against a consumer reading one for the other. `row_id` deliberately reuses
the cluster's own `sha256(f"{pool}:{signature}")`, so bulk and live rows dedupe against each other;
that is what made the 528/528 verification a one-line join.

### Against `shitcoims_cluster` swap rows

| field | bulk | note |
|---|---|---|
| `row_id`, `pool`, `dex`, `label`, `t_event` | ✅ identical | same convention |
| `chain.slot` / `.signature` / `.block_time` | ✅ | |
| **`chain.tx_index`** | ✅ **better than RPC** | live tape leaves it `None`; this resolves intra-slot order |
| `reserves.vaults[].pre_raw` / `post_raw` / `delta_raw` | ✅ exact integers | **528/528 verified** |
| `reserves.replay_sufficient` | ✅ | carried from `PoolSpec`, per pool |
| `token_in_*` / `token_out_*` | ✅ | |
| `fee_lamports`, `compute_units` | ✅ | |
| `kind: attempt` (failed txs) | ✅ | via `err` — absent from any transfers-based source |
| `reserves.vaults[].account` | ❌ | **vaults keyed by mint, not address** — see below |
| `signers`, `fee_payer` | ⚠️ opt-in | needs `accounts`, +267 GB/day |
| `counterparty`, `counterparty_paid_fee` | ❌ | needs the full balance set + owner resolution |
| `leg_discriminators`, `leg_names`, `swap_legs` | ❌ | needs instruction-level data |
| `confirmation_status` | ❌ | historical rows are final by construction |

**The vault-address gap.** Token balances carry `mint`, `owner` and `account_index` but not the
account pubkey; resolving the index needs the `accounts` array at 267 GB/day. Vaults are therefore
keyed by **mint**. For these pools that is sufficient — each holds two distinct mints — but it is
not the live tape's shape, and rows say so explicitly via `vault_addresses_available: false` rather
than letting the absence read as "no vault".

### Against `shitcoims_tape.schema`

- `Chainstamp` — fully satisfied, `tx_index` **included** (the live RPC path cannot supply it).
- `Provenance` — fully satisfied: `source` = `bigquery.crypto_solana_mainnet_us.transactions`
  (valid under `_IDENT`), `fetched_at` = extraction time, `cursor` = the BigQuery job id, so any
  row is traceable to the exact billed job.
- `Reserves` — **constructible for pool state**, which is the point. Note the dataclass's
  `virtual_sol` / `virtual_tokens` fields model a pump.fun *bonding curve*; these are graduated AMM
  pools, so the two vault balances are the whole state and the virtual fields do not apply. Do not
  fill them with zeros to satisfy the type — a zero there reads as measured.
- `Trade` — `wallet` still requires care: without `--with-signers` there is no wallet on the row,
  and `fee_payer` is not a custody claim in any case. `side` and `sol_delta_lamports` assume a
  quote asset, so they exist for the four SOL-quoted pools but not for `weave/nosis` or
  `DREGG/nosis`. `routed_via_frontend` is unavailable — it needs instruction-level data.

**The sharpest hazard.** `TapeEvent.observed_at` means *when we saw it*, and the schema's
load-bearing decision is that observer lag is real and must be modelled as delayed entry. For a
bulk row `observed_at` is the extraction timestamp — days after the event. Feeding bulk rows into
a survival model that treats `observed_at` as delayed entry would manufacture a lag distribution
out of when we happened to run a query. **Bulk rows are a separate stream whose only meaningful
clock is `t_event`.** This is unchanged by the upgrade to replay grade.

---

## Recommendation

**Buy the 22 days from BigQuery for ~$27, not from RPC for 206% of the plan.** It is replay-grade,
it covers all eleven pools, and it includes two things RPC cannot give us at any price: intra-slot
transaction ordering, and reverted transactions.

Sequence:

1. `preflight` the full window (~2.5 GB/day, ~$0) to confirm every partition is loaded.
2. `pull` the 22 days. Expect ~5,843 GB scanned; the first TiB each month is free, so splitting the
   pull across two calendar months costs ~$21 instead of ~$27 if the delay is acceptable.
3. `verify` against the live tape on the overlapping days — it should stay at 100%.
4. Only add `--with-signers` if a study actually needs entity resolution; it more than doubles the
   bill for one column.
5. If attempt-rate is the question, add `log_messages` (3.1 GB/day) first and use it to separate a
   real attempt on *this* pool from an unrelated failure — do not use the `failed` count as-is.

Keep the live collector running regardless. It produces the fields bulk cannot — signers,
counterparty attribution, leg discriminators, confirmation status — at zero marginal cost, and the
two streams dedupe on `row_id` by construction.
