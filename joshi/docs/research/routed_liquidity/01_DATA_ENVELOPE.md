# Historical Solana data envelope for routed-liquidity studies

Date checked: 2026-08-17  
Decision scope: research acquisition only; no implementation, cloud mutation, subscription, or
paid scan was performed

## Executive answer

Do **not** begin a ghost-edge study by exporting Solana history. The current public Solana BigQuery
dataset is useful as a partitioned candidate/signature index and as one independent rendering of
landed transactions, instructions, logs, token deltas, and transfers. It is not a historical quote
archive and does not contain the exact pre-transaction account state needed to evaluate an
unexecuted route at its original slot.

The minimum credible acquisition is:

1. use a 7-day, 3-mint/10–30-pool feasibility snarf to discover finalized candidate signatures;
2. hydrate those signatures to raw transaction/status metadata, retaining CPI, ALT-resolved
   accounts, logs, failures, and exact pre/post balances;
3. capture the complete changing account set for those pools forward in time, including vaults,
   bins/ticks/arrays, configs, oracles, mint extensions, and program versions;
4. retain contemporaneous Jupiter and direct-venue quote witnesses at named sizes/directions and a
   precise state/slot cutoff; and
5. continue to a 30-day preliminary study only if candidate completeness, state completeness, and
   time alignment pass explicit gates below.

A sensible base envelope is about **10 GB of BigQuery scan and 60 MB of hydrated transaction
download per day**, plus roughly **100 MB/day compacted** for hydrated transactions, account-write
state, and quote witnesses together. The uncertainty range is enormous—approximately 5 MB to
5.5 GB compacted per day—because one hot mint with many DLMM bin-array writes is a different study
from a quiet two-pool pair. Measure one day before committing to seven.

The decisive constraint is not disk. It is **counterfactual identification**. BigQuery can show what
landed; only slot-aligned state and quote capture can support what another executable route would
have done. A historical BigQuery-only result should be called route archaeology, not a credible
ghost-edge estimate.

## 1. What exists now

Google's current supported-datasets page lists Solana as a **community-maintained** public dataset,
not one of Google's newer first-party Blockchain Analytics schemas. Therefore the blanket schema
claims on the Google-managed product must not be projected onto Solana. The canonical dataset is
[`bigquery-public-data.crypto_solana_mainnet_us`](https://console.cloud.google.com/marketplace/product/bigquery-public-data/crypto-solana-mainnet-us).
[Google's supported-datasets page](https://docs.cloud.google.com/blockchain-analytics/docs/supported-datasets)
was last updated 2026-08-11 and still identifies Solana as community maintained. Public datasets have
no public-dataset SLA; consumers pay query costs, while Google hosts storage
([public-dataset contract](https://docs.cloud.google.com/bigquery/public-data)).

The locally authenticated identity could perform `bq ls` and `bq show` metadata reads through an
existing project. `INFORMATION_SCHEMA.PARTITIONS`, table dry-runs, and data queries were access
denied. Enabling an API, accepting a Marketplace link, changing IAM, or enabling billing would have
mutated cloud state, so this lane stopped. Partition decorators (`bq show Table$YYYYMMDD`) remained
available and supplied row/byte coverage metadata without reading table data.

### 1.1 Exact table inventory

The values below are direct `tables.get`/`bq show` metadata observed on 2026-08-17 around 03:58 UTC.
Bytes are BigQuery logical bytes, not compressed download size.

| Table | Rows | Logical bytes | Partition | Required filter | Cluster | Configured expiry |
|---|---:|---:|---|---|---|---|
| `Transactions` | 563,992,482,774 | 940,872,741,014,199 (940.87 TB) | daily `block_timestamp` | yes | `signature` | none |
| `Instructions` | 1,142,854,530,530 | 938,882,874,424,746 (938.88 TB) | daily `block_timestamp` | yes | `program_id` | none |
| `Token Transfers` | 145,605,767,155 | 43,945,237,393,739 (43.95 TB) | daily `block_timestamp` | yes | none | none |
| `Accounts` | 164,184,066 | 141,715,296,995 (141.72 GB) | monthly `block_timestamp` | no | none | none |
| `Blocks` | 417,731,114 | 74,314,698,577 (74.31 GB) | monthly `block_timestamp` | no | none | none |
| `Tokens` | 22,968,664 | 10,948,394,425 (10.95 GB) | monthly `block_timestamp` | no | none | none |
| `Block Rewards` | 84,080,945,303 | 12,273,568,604,485 (12.27 TB) | monthly `block_timestamp` | yes | `pubkey` | none |
| `tmp_weekly_usage` | 26 | 624 | none | no | none | none |

`tmp_weekly_usage` is an internal-looking weekly job/terabytes-processed summary, not chain evidence.
Do not build a contract around it.

No table has `expirationTime`, and no `timePartitioning.expirationMs` was reported. This means there
is **no configured automatic table/partition expiry**, not that the community dataset promises
permanent retention. Public datasets have no SLA and may revise their schema, history, or access.

### 1.2 Observed partition coverage and freshness

The three daily research tables have nonzero partitions beginning **2020-10-07**. Their 2020-10-06
partition metadata is zero; 2020-10-07 contains 25,875,163 instruction rows, 17,305,189 transaction
rows, and 6,237,049 transfer rows. On 2026-08-17 all three had a nonzero current partial partition.

The monthly tables are less uniform:

- `Accounts` and `Tokens` first show nonzero monthly partitions in October 2020.
- `Blocks` contains one March 2020 row, no rows from April through September 2020, then 5,636,253
  October rows. It is not continuous genesis coverage.
- `Block Rewards` shows additional empty months and is not needed for the routed-liquidity pilot.

Table-level last-modified timestamps were between 2026-08-17 03:57:48 and 03:58:23 UTC. This proves
recent writes, not completeness or a latency SLA. The current partial partition must never be used as
a closed day.

Recent closed-day logical volumes were:

| UTC day | `Instructions` | `Transactions` | `Token Transfers` | Total |
|---|---:|---:|---:|---:|
| 2026-08-14 | 733.10 GB | 922.92 GB | 27.24 GB | 1.683 TB |
| 2026-08-15 | 716.98 GB | 891.55 GB | 35.27 GB | 1.644 TB |
| 2026-08-16 | 645.71 GB | 771.88 GB | 22.62 GB | 1.440 TB |

This current 1.4–1.7 TB/day envelope supersedes estimates based on the all-history average. The
all-history average is artificially low because activity grew and table coverage begins in 2020.

## 2. Exact reconstruction envelope

### 2.1 `Transactions`

The current schema contains:

- slot/hash/timestamp, recent blockhash, signature, transaction index;
- fee, status/error, compute units;
- repeated flattened accounts with signer/writable flags;
- log messages;
- lamport balance changes; and
- repeated pre/post token balances with account index, mint, owner, amount, and decimals.

This is the best BigQuery hydration target after signature discovery because it is clustered on
`signature`. It can establish landed/failure status, transaction order within a block, logs, fees,
and net balance deltas.

It does **not** expose raw serialized message/transaction bytes, transaction version, address lookup
table identities and indices, recent prioritization request parameters, return data, rewards, or an
explicit static-versus-loaded account distinction. Even if its flattened `accounts` list is fully
resolved, it cannot independently prove how an ALT resolved at that slot. Solana's canonical RPC
transaction metadata exposes `innerInstructions`, `loadedAddresses`, logs, return data, version, and
pre/post balances, with explicit historical null/undefined cases
([Solana JSON structures](https://solana.com/docs/rpc/json-structures),
[`getTransaction`](https://solana.com/docs/rpc/http/gettransaction)). Retain the raw RPC response as
the primary hydration witness and use BigQuery as an independent cross-check.

### 2.2 `Instructions`

The schema contains slot/hash/time/signature, `index`, `parent_index`, repeated accounts, raw `data`,
parsed JSON text, program/program ID, instruction type, and repeated key/value params. It appears
designed to include top-level and inner instructions, and `parent_index` suggests a CPI relation.
The fields currently have no public descriptions. Before relying on them, validate against raw RPC
for nested CPI, failed transactions, duplicate indices, unknown programs, and parser fallbacks.

Its daily partition plus `program_id` cluster is the important cost lever. A constant program filter
can prune clustered blocks; an account/pool predicate inside `UNNEST(accounts)` cannot provide a
second clustering dimension. Query target programs first, then target pools/accounts.

Filtering this table by `tx_signature` alone is not narrow: it is not clustered on signature. Do not
discover signatures and then rescan full instruction partitions to recover every CPI. Hydrate raw
transactions by RPC instead, or accept a declared allowlisted-program view.

### 2.3 Logs

There is no standalone `Logs` table. Logs are the repeated `Transactions.log_messages` field. They
can support execution traces, errors, program-emitted data, and parser validation after signature
hydration. Official Solana metadata permits `logMessages: null` if logging was not enabled and
`innerInstructions: null` if inner-instruction recording was not enabled; absence is not a negative
event. Preserve that distinction.

### 2.4 `Token Transfers`

This derived daily table contains signature/slot/time, source, destination, authority, value,
decimals, mint/mint authority, token fee fields, memo, and transfer type. It is useful for candidate
discovery and cross-checking an instruction decoder.

It has **no clustering**. A mint, wallet, authority, source, or destination filter reduces returned
rows and download, but not the logical columns scanned inside selected day partitions. It is also a
parser-derived transfer view: net balance changes, Token-2022 fees/hooks, mint/burn, close-account
effects, and unsupported instruction variants must be reconciled against raw instructions and
pre/post balances rather than treated as an exhaustive ledger.

### 2.5 `Accounts` and `Tokens`

`Accounts` carries pubkey, creation transaction, retrieval timestamp, executable/lamports/owner,
token account fields, program data/raw data, and some vote-account fields. It has no write version,
transaction index, intra-slot ordering, or indication that every account write was captured. The
presence of `retrieval_timestamp` explicitly separates observation from block time. It cannot
reconstruct a pool/vault/bin/tick account at each historical swap.

`Tokens` is token metadata snapshot material (mint, authority, name/symbol/URI, creators, mutability),
not token supply/account-state history. Both may seed identities, but neither is a historical SVM
state store.

### 2.6 Blocks, finality, forks, and order

`Blocks` can check slot/hash/parent continuity, height, timestamp, transaction count, leader, and
leader reward over its covered months. The dataset does not document ingestion commitment and
records no commitment/finality field. Solana distinguishes processed, confirmed, and finalized;
processed blocks may be dropped, while finalized is the maximum-lockout view
([commitment behavior](https://solana.com/docs/rpc)).

For every snarf:

- use slot, transaction index, instruction index/parent relation—not wall time—as execution order;
- compare a sample of slot/hash/signature records against a finalized RPC;
- retain both identities if a slot/hash revision is observed rather than overwriting;
- recheck a bounded recent correction window before closing coverage; and
- record missing/null metadata and partition gaps explicitly.

### 2.7 ALTs and CPI

Versioned v0 transactions use address lookup tables to load additional account keys; each ALT can
hold up to 256 addresses, and v0 transactions can use more accounts than legacy transactions
([official ALT guide](https://solana.com/developers/guides/advanced/lookup-tables)). A flattened
BigQuery account list is not proof of the lookup table's historical contents. The exact study record
needs either raw transaction metadata with resolved `loadedAddresses` plus the lookup-table account
at the relevant slot, or an archival replay witness.

CPI reconstruction needs the complete ordered inner-instruction tree and logs. The BigQuery
`Instructions` representation must be conformance-tested against RPC, especially for nested CPI and
failures. Unknown program data stays opaque; it must not be silently mapped to “no edge.”

## 3. Jupiter routes and the counterfactual hole

BigQuery can reveal a **landed on-chain route**: Jupiter/venue instructions, invoked AMM programs,
accounts, logs, transfers, and realized balance changes. With the correct versioned IDLs and state,
it may decode thresholds, split legs, and fees embedded in the executed transaction.

It cannot reconstruct:

- the `/quote`, `/order`, or `/build` request and response that existed before signing;
- routes considered and rejected, no-route responses, router latency, API region, or cache state;
- JupiterZ/Dflow/OKX RFQ alternatives and prices that never became chain data;
- a user's UI settings, excluded routers/DEXes, slippage choice, taker-less price check, or abandoned
  order; or
- pool state for an unchosen edge at that historical decision point.

Jupiter's current recommended Swap V2 `/order` endpoint selects among Metis, JupiterZ, Dflow, and
OKX and reports the winning router and expected output; options can change router eligibility
([Order & Execute](https://developers.jup.ag/docs/swap/order-and-execute)). The older Metis quote
response exposes a `routePlan` with DEXes, split percentages, amounts, price impact, and a report of
markets that would have quoted, but Swap V1 is no longer the recommended primary integration
([custom Metis quote guide](https://developers.jup.ag/docs/guides/how-to-build-a-custom-swap-with-metis),
[Jupiter changelog](https://developers.jup.ag/docs/changelog)). Neither service is advertised as a
historical quote archive.

Therefore a ghost edge—an executable route/leg that would have improved the contemporaneous
decision—requires forward-captured quote responses and the exact state they were computed from.
Historical chain data can nominate hypotheses and measure realized paths; it cannot identify the
counterfactual alone.

## 4. Cost model

### 4.1 Symbols and observed priors

For a window of `D` days:

```text
scan = Σ_table(partition logical bytes × selected-column fraction × cluster-survival fraction)
download = Σ_returned rows × encoded bytes/row
compact = Σ_returned rows × encoded bytes/row × compacting ratio
```

Partition pruning excludes other days from billed scan. Columnar billing means selecting only
needed fields matters. A constant predicate on `Instructions.program_id` or
`Transactions.signature` can additionally prune clustered blocks. BigQuery documents both
[partition pruning](https://docs.cloud.google.com/bigquery/docs/querying-partitioned-tables) and
[cluster block pruning](https://docs.cloud.google.com/bigquery/docs/clustered-tables). Clustered-query
dry-run estimates can be upper bounds, so record both the estimate and actual job statistics before
scaling.

Low/base/high assumptions used below:

| Quantity | Low | Base | High | Basis |
|---|---:|---:|---:|---|
| full current-chain logical bytes/day | 1.25 TB | 1.59 TB | 2.25 TB | observed 1.44–1.68 TB/day plus quieter/high-growth envelope |
| selected instruction column fraction | 0.25 | 0.40 | 0.65 | projection choice; must be dry-run measured |
| target-program cluster survival | 0.5% | 3% | 12% | one narrow program versus broad Jupiter/venue family; unknown until dry run/job stats |
| selected transfer column fraction | 0.25 | 0.40 | 0.65 | no mint clustering benefit |
| candidate transactions/day | 500 | 5,000 | 50,000 | quiet focus versus hot mint/pool/wallet subgraph |
| hydrated raw transaction bytes | 4 KB | 12 KB | 40 KB | logs/CPI/ALT/meta dependent |
| transaction compaction ratio | 0.25 | 0.35 | 0.50 | projected Parquet/Zstd versus JSON; measure actual |

All TB/GB values below are decimal. “Download” means retaining the selected result locally. A query
that returns only aggregates downloads little but cannot support replay.

### 4.2 Strategy A — naive partition-pruned chain export

This is `SELECT *` from all three daily tables for the chosen dates. It is called “naive” even though
it uses the mandatory partition filter. Omitting that filter is rejected by current table policy.

| Days | BigQuery scan, base [low–high] | Download, base [low–high] | Compact local, base [low–high] |
|---:|---:|---:|---:|
| 1 | 1.59 TB [1.25–2.25 TB] | 1.43 TB [0.75–2.93 TB] | 350 GB [150–788 GB] |
| 7 | 11.1 TB [8.75–15.8 TB] | 10.0 TB [5.25–20.5 TB] | 2.45 TB [1.05–5.51 TB] |
| 30 | 47.7 TB [37.5–67.5 TB] | 42.9 TB [22.5–87.8 TB] | 10.5 TB [4.5–23.6 TB] |
| 90 | 143 TB [112–202 TB] | 129 TB [67.5–263 TB] | 31.5 TB [13.5–70.9 TB] |

Download assumes roughly 0.6/0.9/1.3 encoded bytes per logical byte; local compact assumes
0.12/0.22/0.35. Those are planning ratios, not measured facts. This strategy is unjustified for the
pilot. At current on-demand pricing, scans are $6.25/TiB after the first 1 TiB/month per account
([BigQuery pricing](https://cloud.google.com/bigquery/pricing)); the 30-day base scan alone is about
43.4 TiB before the free allowance. The more important objection is weeks of irrelevant local data.

### 4.3 Strategy B — partition + program/pool candidate extraction

Scan projected columns from `Instructions` with constant program IDs, then account/pool filters;
optionally scan selected columns from unclustered `Token Transfers` for target mints. Do not add a
date-wide `Transactions` join merely to obtain logs: selected transaction columns alone would add
roughly 100–300 GB/day before signature clustering.

The scan model is:

```text
S_B(D) = D × [(I_day × c_I × g_program) + (Xfer_day × c_X)]
```

Using recent `I_day≈699 GB` and `Xfer_day≈28 GB` yields approximately 6.5/19.7/80 GB per day at the
low/base/high assumptions.

| Days | BigQuery scan, base [low–high] | Candidate download, base [low–high] | Compact local, base [low–high] |
|---:|---:|---:|---:|
| 1 | 19.7 GB [6.5–80 GB] | 100 MB [1 MB–5 GB] | 40 MB [0.3 MB–2.5 GB] |
| 7 | 138 GB [45.5–560 GB] | 700 MB [7 MB–35 GB] | 280 MB [2.1 MB–17.5 GB] |
| 30 | 591 GB [195 GB–2.4 TB] | 3 GB [30 MB–150 GB] | 1.2 GB [9 MB–75 GB] |
| 90 | 1.77 TB [585 GB–7.2 TB] | 9 GB [90 MB–450 GB] | 3.6 GB [27 MB–225 GB] |

This is excellent for naming actual programs/pools/signatures and comparing the transfer-derived
view. It is not a sufficient execution witness: it omits full raw transaction metadata, unallowlisted
CPI, and contemporaneous pool state.

### 4.4 Strategy C — two-stage signatures then narrow hydration

Stage 1 emits `(slot, signature, candidate reason)` from clustered `Instructions`, or obtains
signatures from an address-indexed RPC for known wallets/pools. Stage 2 batches literal signatures
by day and reads selected `Transactions` columns, which can use the signature cluster. Raw
`getTransaction` hydration supplies the complete canonical transaction/meta/CPI/ALT record; BigQuery
is the cross-check.

The scan model is:

```text
S_C(D) = candidate instruction scan
       + Σ_day clustered transaction blocks touched by that day's literal signature batches
```

The second term is not safely inferable from row selectivity: BigQuery bills touched storage blocks,
and high-cardinality signatures can fragment many blocks. The 0.25/2/25 GB/day transaction-hydration
allowance is deliberately broad. A dry run and one capped day must replace it.

| Days | BigQuery scan, base [low–high] | Raw hydrated download, base [low–high] | Compact transaction local, base [low–high] |
|---:|---:|---:|---:|
| 1 | 10.4 GB [1–82 GB] | 60 MB [2 MB–2 GB] | 21 MB [0.5 MB–1 GB] |
| 7 | 72.8 GB [7–574 GB] | 420 MB [14 MB–14 GB] | 147 MB [3.5 MB–7 GB] |
| 30 | 312 GB [30 GB–2.46 TB] | 1.8 GB [60 MB–60 GB] | 630 MB [15 MB–30 GB] |
| 90 | 936 GB [90 GB–7.38 TB] | 5.4 GB [180 MB–180 GB] | 1.89 GB [45 MB–90 GB] |

This is the recommended historical path. In the high case it can approach Strategy B because many
signatures touch many cluster blocks. If so, move signature discovery/hydration to an address-indexed
archive API instead of pretending BigQuery is an address index.

### 4.5 The forward state-and-quote addition

Historical hydration is the small part of a credible ghost-edge dataset. Add:

```text
L_forward(D) = D × [N_tx R_tx q_tx + N_write R_write q_write + N_quote R_quote q_quote]
```

The planning cases are:

- low: 500 transactions, 2,000 account writes, 1,000 quote witnesses/day → about 5 MB/day compact;
- base: 5,000 × 12 KB transactions, 50,000 × 3 KB account writes, 10,000 × 5 KB quotes with
  0.35–0.40 compaction → about 100 MB/day compact; and
- high: 50,000 × 40 KB transactions, 1,000,000 × 8 KB writes, 100,000 × 10 KB quotes at 0.5
  compaction → about 5.5 GB/day compact.

| Days | Forward compact local, base [low–high] |
|---:|---:|
| 1 | 100 MB [5 MB–5.5 GB] |
| 7 | 700 MB [35 MB–38.5 GB] |
| 30 | 3 GB [150 MB–165 GB] |
| 90 | 9 GB [450 MB–495 GB] |

Disk is not the limiting factor. Complete account-selection manifests, coverage gaps, fork status,
quote/state alignment, and decoder correctness are.

## 5. Safe query templates

Dry runs do not use query slots and are not charged; they validate SQL and estimate bytes
([BigQuery dry-run contract](https://docs.cloud.google.com/bigquery/docs/running-queries)).
`maximum_bytes_billed` causes an over-cap query to fail without charge
([cost controls](https://docs.cloud.google.com/bigquery/docs/best-practices-costs)). Clustered dry-run
estimates can be upper bounds.

Use a dedicated, approved billing project. Start with a 10 GiB/query cap. Do not remove `--dry_run`
until the estimate, project-wide monthly usage, and intended output have been reviewed. The current
local identity cannot query this dataset, so these templates were schema-checked against metadata
but not accepted by a dry-run job.

```bash
BILLING_PROJECT='replace-with-approved-project'
CAP_BYTES='10737418240' # 10 GiB

bq --project_id="$BILLING_PROJECT" --location=us-central1 query \
  --use_legacy_sql=false \
  --dry_run \
  --maximum_bytes_billed="$CAP_BYTES" \
  'SELECT block_slot, block_timestamp, tx_signature, `index`, parent_index,
          accounts, data, program_id, instruction_type
   FROM `bigquery-public-data.crypto_solana_mainnet_us.Instructions`
   WHERE block_timestamp >= TIMESTAMP("2026-08-15")
     AND block_timestamp <  TIMESTAMP("2026-08-16")
     AND program_id IN ("TARGET_PROGRAM_1", "TARGET_PROGRAM_2")
     AND EXISTS (
       SELECT 1 FROM UNNEST(accounts) AS account
       WHERE account IN ("TARGET_POOL_1", "TARGET_POOL_2")
     )'
```

Candidate signature hydration must use literal/array-parameter signatures and the same constant date
range so both the daily partition and signature cluster can prune:

```sql
SELECT
  block_slot, block_hash, block_timestamp, signature, `index`, fee, status, err,
  compute_units_consumed, accounts, log_messages, balance_changes,
  pre_token_balances, post_token_balances
FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
WHERE block_timestamp >= TIMESTAMP('2026-08-15')
  AND block_timestamp <  TIMESTAMP('2026-08-16')
  AND signature IN ('SIG_1', 'SIG_2')
```

Batch signatures by UTC day. A dynamic join from a large candidate CTE is not automatically
equivalent to a constant cluster predicate; dry-run and actual statistics decide.

The mint-transfer cross-check is intentionally unclustered:

```sql
SELECT block_slot, block_timestamp, tx_signature, source, destination, authority,
       value, decimals, mint, fee, fee_decimals, transfer_type
FROM `bigquery-public-data.crypto_solana_mainnet_us.Token Transfers`
WHERE block_timestamp >= TIMESTAMP('2026-08-15')
  AND block_timestamp <  TIMESTAMP('2026-08-16')
  AND mint IN ('TARGET_MINT')
```

Expect the dry-run estimate to depend mainly on selected columns and days, not mint selectivity.
Never use `LIMIT` as a cost guard on a nonclustered scan; Google explicitly notes it does not reduce
bytes read in that case.

Metadata-only reproduction commands:

```bash
bq --project_id="$BILLING_PROJECT" --location=US ls \
  --format=prettyjson bigquery-public-data:crypto_solana_mainnet_us

bq --project_id="$BILLING_PROJECT" --location=US show --format=prettyjson \
  'bigquery-public-data:crypto_solana_mainnet_us.Instructions'

bq --project_id="$BILLING_PROJECT" --location=US show --format=prettyjson \
  'bigquery-public-data:crypto_solana_mainnet_us.Instructions$20260815'
```

The table metadata reports physical location `us-central1`; use that location for query jobs. Query
result access through ordinary clients is not separately charged as extraction, while bulk extract
and Storage Read API have different compute/transfer rules
([BigQuery extraction pricing](https://cloud.google.com/bigquery/pricing)). The pilot should page a
small capped result directly; it does not need a bucket or export job.

## 6. Data-quality contract

Every retained row/response needs source occurrence, acquisition time, exact bytes, query/RPC
parameters with secrets redacted, contract/schema version, and coverage scope. Additionally:

| Risk | Required treatment |
|---|---|
| changing community schema | snapshot `bq show` metadata and exact SQL with each snarf |
| present-day partial partition | close only UTC days proven complete after a delay/correction window |
| unknown ingestion finality | finalized RPC slot/hash/signature sample; retain mismatch/gap |
| fork/reorg | key block observations by slot+hash; do not overwrite a changed hash |
| failed transactions | retain status/error/logs; exclude from realized transfer totals, include in feasibility/landing analysis |
| missing logs/inner/token balances | explicit unavailable state, never zero |
| CPI parser incompleteness | raw RPC conformance sample; opaque unknown variants |
| ALT resolution | raw v0 transaction/meta, loaded addresses, and historical ALT witness where needed |
| token/Token-2022 semantics | exact mint program/extensions, transfer fees/hooks, raw instructions, pre/post amounts |
| account snapshots | never substitute `Accounts` retrieval state for state at a historical slot |
| derived token transfers | reconcile against instruction decode and pre/post balances |
| wall time | order by slot/transaction/instruction indices; timestamp is contextual only |
| duplicate source views | dedupe analytically by explicit identity while retaining each acquisition occurrence |

The BigQuery `NUMERIC`/`BIGNUMERIC` values and RPC decimal strings must remain exact integers/scaled
integers. No floating point enters route amount, fee, or PnL evidence.

## 7. BigQuery versus the necessary alternatives

| Source | Best role | What it does not solve |
|---|---|---|
| public BigQuery | broad partitioned discovery; clustered program/signature candidate queries; independent logs/balance view | address-indexed wallet search, raw transaction bytes, historical pool state, quotes |
| ordinary archival RPC | `getSignaturesForAddress` discovery and exact `getTransaction` hydration | arbitrary cross-chain SQL; historical account state at an old slot is generally not exposed by ordinary current-state calls |
| Helius | address-indexed history with slot/time/status filters and full/signature modes; unlimited mainnet history is currently advertised | vendor/parser correctness, quote history, unobserved pool state; requires measured plan/rate feasibility |
| Geyser | forward exact account writes, transaction metadata, write versions, slot/bank/finality transitions | history before capture; operating it yourself is heavy and its plugin API can change |
| local archival ledger/replay | strongest path to historical SVM/account state and independent decoding | very large acquisition/ops burden; still no off-chain quote or RFQ history |

Helius's current `getTransactionsForAddress` supports finalized/confirmed commitment, keyset
pagination, slot/time/status filters, up to 1,000 signatures or 100 full transactions per call
([official method reference](https://www.helius.dev/docs/api-reference/rpc/http/gettransactionsforaddress)).
It is a plausible focused discovery/hydration alternative, not an automatic purchase decision. Its
older Enhanced Transactions parser is deprecated for new parser work and can omit unsupported types
([Helius FAQ](https://www.helius.dev/docs/faqs/enhanced-transactions)); retain raw transaction
responses and our own decoders.

Agave's Geyser interface exposes account data, write version, causing transaction, transaction
status metadata/index, and slot/bank status callbacks
([primary interface](https://github.com/anza-xyz/agave/blob/master/geyser-plugin-interface/src/geyser_plugin_interface.rs)).
That is the right semantic shape for forward state capture. Running a validator/plugin is not the
minimum snarf: first test a read-only provider stream or narrowly selected account feed. If provider
semantics cannot preserve forks, write ordering, and exact bytes, then reassess self-hosted replay.

## 8. Minimum viable snarf and gates

### 8.1 Focus set

Choose before querying:

- three mints: one high-activity, one medium, one quiet/control;
- 10–30 pools spanning at least two venue/curve families, including every vault/config/bin/tick/
  oracle/mint account needed for a direct quote;
- Jupiter plus the exact venue program IDs and versioned decoder/IDL fingerprints;
- Ember's relevant wallet and at most two watched-wallet controls; and
- both trade directions at three named input sizes that reflect actual intended decisions.

This is large enough to expose DLMM/account-shape problems without turning “the market” into an
undefined scan.

### 8.2 Seven-day feasibility run

Retain:

1. BigQuery candidate manifests with exact SQL, metadata snapshot, estimate/job bytes, source day,
   and reason each signature entered the set;
2. finalized raw transactions/status metadata for every candidate, plus the BigQuery rendering;
3. exact state changes for the complete selected pool account manifest, with slot, bank/fork status,
   write version/order, and coverage gaps;
4. quote/order responses from current Jupiter V2 and direct venue quote functions, including request,
   response, endpoint/build, receipt clocks, context slot/state digest, route/venue eligibility,
   amount, direction, fees, price impact, and no-route/error outcomes; and
5. an explicit choice set: pools/routes considered, surfaced, selected, skipped, and later outcome.

Pass only if:

- at least 99% of candidate signatures hydrate or every miss has a bounded, retryable gap;
- BigQuery and RPC agree on signature, slot/hash, status, account/token deltas, and target instruction
  topology for at least 99.5% of the conformance sample, with every disagreement classified;
- all state accounts referenced by the direct quote decoder are present at the quote cutoff;
- ALT and nested CPI fixtures round-trip for every observed transaction version/program variant;
- current-partition closure and finality/reorg handling work without silent overwrite;
- scan remains under the predeclared aggregate cap and compact growth fits the measured envelope; and
- quote witnesses are joined by state/slot and receipt clocks, never nearest wall timestamp alone.

Fail/shelf if complete pool state cannot be captured or if a quote cannot be tied to a reproducible
state cutoff. In that case BigQuery archaeology may continue for descriptive route topology, but no
ghost-edge claim is allowed.

### 8.3 Thirty-day preliminary credibility gate

Days are only a coverage proxy. The unit is an independent paired opportunity: actual executable
choice versus ghost edge at the same state, size, direction, eligibility, and fee/landing model.

For a paired mean improvement `δ` with paired standard deviation `σ`, 5% two-sided significance and
80% power require approximately:

```text
n_independent >= ((1.96 + 0.84) × σ / δ)^2
n_effective   = n_raw / design_effect
design_effect = 1 + 2 × Σ positive lag autocorrelations
```

Examples for a 5 bp edge: `σ=20 bp → n≈126`, `σ=50 bp → n≈784`, and `σ=100 bp → n≈3,136`, before
autocorrelation, multiple-edge search, venue outages, or regime stratification. Accordingly:

- target **at least 500–3,000 effective paired opportunities per claimed edge/regime**, not merely a
  large transaction count;
- use day/market-regime clustered uncertainty and a multiple-hypothesis correction;
- include transfer fees, venue fees, priority/compute cost, quote age, landing/failure probability,
  and inventory constraints in the net comparison;
- predeclare the discovery window and keep at least seven later days as temporal holdout; and
- require the sign and materiality of the edge to survive the holdout and reasonable state/latency
  perturbations.

Thirty days can support a **preliminary** claim if those effective-sample and completeness gates pass.
Ninety days is warranted only for a surviving edge, regime robustness, or sparse venue—not as a
default snarf. A null after seven days means “pipeline or candidate hypothesis did not yet clear the
gate,” not “routed liquidity has no structure.”

## 9. Recommendation

Use Strategy C. Start with one closed UTC day and a 10 GiB dry-run cap. If the program-cluster query
cannot stay under the cap, seed signatures through address-indexed RPC for the fixed pools/wallets
and use BigQuery only for a small signature-clustered cross-check. Do not scan `Token Transfers`
unless its mint-level cross-check is worth the unclustered 6–23 GB/day selected-column cost.

The first useful artifact is a 7-day replayable bundle measured in hundreds of megabytes to low
gigabytes—not a chain dump. Its value comes from exact candidate coverage, raw transaction
hydration, complete forward account state, and quote witnesses. Only that bundle can tell us whether
a “ghost edge” is an executable missed route, a stale-state illusion, a parser omission, or simply a
route Jupiter correctly rejected.
