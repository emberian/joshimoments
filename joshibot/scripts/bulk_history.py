#!/usr/bin/env python3
"""Bulk historical tape for the cluster pools, from the BigQuery public Solana dataset.

WHY THIS EXISTS
---------------
We have live papertesting and no historical backtesting, because we have no historical
tape. Per-transaction RPC backfill was costed at ~10 credits/tx against a measured
~93,600 tx/day across the cluster: one day is 9.4% of the monthly Helius plan and the full
22-day history is 206% of it. This script is the bulk alternative, and it turns out to be
both cheaper and *strictly more informative* than the RPC path.

THE SOURCE: `Transactions`, NOT `Token Transfers`
-------------------------------------------------
``bigquery-public-data.crypto_solana_mainnet_us.Transactions`` carries the full transaction
meta: ``pre_token_balances`` / ``post_token_balances`` with ``amount`` as **BIGNUMERIC**
(exact integers, never float), plus ``fee``, ``err``, ``index`` and ``compute_units_consumed``.
It is DAY-partitioned on ``block_timestamp`` (``requirePartitionFilter``) and clustered on
``signature``.

Validated against 528 swaps the live RPC collector independently recorded on 2026-08-13:
**528 of 528 present, and 528 of 528 matched on BOTH pre and post reserves, every digit,
on both vault legs.** That is replay-grade, not summary-grade.

Two things this path has that ``getTransaction`` does not:

- **``index``, the transaction's position within its block.** ``shitcoims_cluster.parse``
  documents intra-slot ordering as unrecoverable from ``getTransaction`` (it returns a slot
  but no block index), which matters because 57 of 158 observed slots on nosis/SOL carried
  more than one transaction. This column resolves it, present on 528 of 528.
- **Failed transactions.** ``err`` is non-empty on a revert, so reverts arrive in the same scan
  as fills, and in the live tape attempts outnumber swaps 6.5 to 1. They are emitted as
  ``kind: "failed"``, **not** as the live tape's ``attempt``: a failed transaction moved
  nothing, so token balances cannot say whether it meant to trade *this* pool or merely listed
  its vaults while failing elsewhere. Measured on 2026-08-13, nosis/SOL shows 105,457 failures
  here against 4,336 live attempts — a ~24x gap. Narrowing them to real attempts needs to know
  which program was invoked, which ``log_messages`` (only 3.1 GB/day) would give cheaply; that
  is the obvious next increment and is deliberately not guessed at here.

WHY NOT THE OTHER TABLES (measured, not assumed)
-------------------------------------------------
- ``Token Transfers`` looked promising — it does contain inner CPI transfers and its values
  are exact — but it is **not reliably populated**: ``mint IS NULL`` on 92-96% of rows across
  six sampled months, and our four cluster mints show 1-7 transfer rows per day against
  hundreds of real swaps. Of the same 528 known-good swaps, it contained **0**. One day in
  the sample (2026-08-12) is loaded, at 2x the normal row count, consistent with a one-off
  reprocessing. It also carries deltas only, never reserve levels, and cannot represent a
  failed transaction at all, since a failed swap moves no tokens.
- ``Instructions`` contains **only top-level instructions** (``COUNTIF(parent_index IS NOT
  NULL) = 0`` over a full day of PumpSwap), so it holds a top-level PumpSwap instruction for
  only **224 of those 528 swaps (42.4%)** — the rest are aggregator-routed and invisible. It
  also carries the requested Anchor args, never the realised fill.
- ``Accounts`` returns **zero rows** for every cluster pool address.

COST, AND WHY IT IS A FULL-DAY SCAN
------------------------------------
BigQuery bills on bytes scanned, and on this table the bill is set by which columns you
touch, not by how many pools you filter for. Measured per column for one day:

    signature 30.7 GB   pre_token_balances 114.3 GB   post_token_balances 114.4 GB
    err 7.8 GB   fee 7.5 GB   compute_units 7.5 GB   index 5.0 GB   block_slot 5.0 GB
    accounts 267.0 GB   balance_changes 434.1 GB   log_messages 3.1 GB

The replay set costs **263.1 GB/day billed** on a real run (269.8 GB was the dry-run bound), plus
2.5 GB/day of preflight. So 22 days is ~5.84 TB = 5.31 TiB: **$0 for the first TiB each month and
~$27 total** at the $6.25/TiB on-demand rate. ``accounts`` would more than double that for the
signer list alone, so it is opt-in behind ``--with-signers``.

Filtering by signature *does* prune (clustering), but only pays off for sparse sets: measured
13.6 GB for 200 signatures and 34.2 GB for 528, i.e. ~65 MB per transaction, so it beats the
full-day scan only below ~4,000 transactions/day. The cluster sees 11,103 (2026-08-13) to
65,884 (2026-08-14) transactions/day touching its pools, so the full-day scan wins by a wide
margin and is what ``pull`` does.

COMPLETENESS
------------
Unlike ``Token Transfers``, this table is uniformly populated. Transactions per UTC day over
the target window ran 255M-314M with no collapse and no gap (2026-07-24 .. 2026-08-13), which
is why ``preflight`` here is a cheap sanity check (~2.5 GB/day, the ``block_timestamp`` column
alone) rather than the load-bearing guard it had to be against the transfers table. It still
runs by default, because a silently short tape is the failure mode worth spending 1% of the
pull cost to rule out.

VAULT DISCOVERY IS INHERENT, NOT TABULATED
-------------------------------------------
``pools.py`` is deliberate that a pool's vaults are exactly the token accounts whose ``owner``
is the pool address, and that hard-coding a vault table per DEX creates a second source of
truth that drifts. This tool never needs a vault list: the query filters on
``post_token_balances.owner IN (pool addresses)``, so vault discovery happens in the WHERE
clause and is protocol-agnostic across PumpSwap and Meteora alike.

WHAT IS STILL MISSING  (see studies/RESULT_bulk_history.md for the full mapping)
---------------------------------------------------------------------------------
- **Vault account addresses.** Token balances carry ``mint``, ``owner`` and ``account_index``
  but not the account pubkey; resolving the index needs the ``accounts`` array at 267 GB/day.
  Vaults are therefore keyed by **mint** rather than address. For these pools that is
  sufficient (two distinct mints each) but it is not the live tape's shape.
- **Signers / fee payer** need the same expensive column; ``--with-signers`` turns it on.
- **A DLMM fill is still not a function of vault totals.** Meteora's price and depth live in
  bins. Reserves recorded for the three Meteora pools are a state *summary*, exactly as
  ``PoolSpec.replay_sufficient_reserves`` already records. That is a property of concentrated
  liquidity, not a gap in this source, and no data source fixes it.

USAGE
-----
    python3 scripts/bulk_history.py selftest                       # offline, no network
    python3 scripts/bulk_history.py preflight --start ... --end ...
    python3 scripts/bulk_history.py pull --start 2026-08-13 --end 2026-08-13 \
        --project <billing-project> --out state/bulk_history
    python3 scripts/bulk_history.py verify --out state/bulk_history
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shitcoims_cluster.pools import (  # noqa: E402
    CLUSTER_POOLS,
    POOLS_BY_ADDRESS,
    WSOL_MINT,
    PoolSpec,
)

TOOL_VERSION = "bulk_history/2"
ROW_SCHEMA = "bulk_history.v2"

BQ_DATASET = "bigquery-public-data.crypto_solana_mainnet_us"
BQ_TX = f"`{BQ_DATASET}.Transactions`"
PROVENANCE_SOURCE = "bigquery.crypto_solana_mainnet_us.transactions"

DEFAULT_OUT = REPO_ROOT / "state" / "bulk_history"
#: Read-only. The live collector owns this tree; `verify` only reads ground truth from it.
LIVE_TAPE = REPO_ROOT / "state" / "cluster_tape" / "swaps"

_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

#: A day whose transaction count falls below this share of the window median was not fully
#: loaded. Real days over the target window sat in a 255M-314M band, so a day at half the
#: median is not natural variation.
TX_COUNT_MIN_RATIO = 0.5
#: Guard rail on every billable query. The free tier is 1 TiB/month and a full-day replay
#: scan is ~270 GB, so an unguarded mistake is real money.
DEFAULT_MAX_BYTES = 400_000_000_000


def _b58(value: str, *, what: str) -> str:
    """Validate before interpolating into SQL. Also the injection guard."""
    text = str(value).strip()
    if not _B58.match(text):
        raise ValueError(f"{what} is not a base58 Solana address: {value!r}")
    return text


def _sql_list(values: list[str]) -> str:
    return ",".join("'" + _b58(v, what="address") + "'" for v in sorted(set(values)))


def _days(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _parse_day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _raw_int(value: Any, *, what: str) -> int:
    """Parse a BigQuery BIGNUMERIC into an exact integer, or fail.

    Never float. ``shitcoims_tape.schema`` exists partly to stop f64 from silently rounding
    a 1e15-raw-unit balance, and this is the boundary where that would happen.
    """
    if isinstance(value, bool | float):
        raise ValueError(f"{what} must never arrive as a float")
    text = str(value).strip()
    if "." in text:
        head, _, tail = text.partition(".")
        if tail.strip("0"):
            raise ValueError(f"{what} is not an integral raw amount: {value!r}")
        text = head or "0"
    return int(text)


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".partial")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------------------
# BigQuery driver (the `bq` CLI, so there is no new python dependency)
# --------------------------------------------------------------------------------------


@dataclass
class BigQuery:
    project: str
    max_bytes: int = DEFAULT_MAX_BYTES
    dry_run: bool = False

    def _base(self) -> list[str]:
        return ["bq", f"--project_id={self.project}", "--format=json"]

    def estimate(self, sql: str) -> int:
        proc = subprocess.run(
            [*self._base(), "query", "--use_legacy_sql=false", "--dry_run"],
            input=sql, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            # bq reports API-not-enabled and permission errors on stdout, not stderr, so
            # reporting only stderr produces an empty and unactionable failure.
            detail = (proc.stderr.strip() + "\n" + proc.stdout.strip()).strip()
            raise RuntimeError(
                f"dry run failed for project {self.project!r}:\n{detail}\n"
                "If BigQuery is not enabled on that project, pass --project or set "
                "BULK_HISTORY_PROJECT to one where it is."
            )
        return int(json.loads(proc.stdout)["statistics"]["totalBytesProcessed"])

    def run(self, sql: str, *, max_rows: int = 2_000_000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        estimate = self.estimate(sql)
        print(f"    dry-run upper bound: {estimate / 1e9:.2f} GB", file=sys.stderr)
        if estimate > self.max_bytes:
            raise RuntimeError(
                f"refusing to run: estimate {estimate / 1e9:.1f} GB exceeds cap "
                f"{self.max_bytes / 1e9:.1f} GB (raise with --max-bytes)"
            )
        if self.dry_run:
            return [], {"dryRun": True, "total_bytes_processed": estimate, "total_bytes_billed": 0}
        proc = subprocess.run(
            [
                *self._base(), "query", "--use_legacy_sql=false", "--nouse_cache",
                f"--max_rows={max_rows}", f"--maximum_bytes_billed={self.max_bytes}",
            ],
            input=sql, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"query failed:\n{proc.stderr.strip()}\n{proc.stdout.strip()}")
        return json.loads(proc.stdout or "[]"), self._stats_for(sql)

    def _stats_for(self, sql: str) -> dict[str, Any]:
        """Recover job id + billed bytes by matching the query text in recent job history.

        Matching on the text rather than taking the newest job keeps this correct when other
        jobs (or another agent's session) interleave on the same project.
        """
        proc = subprocess.run([*self._base(), "ls", "-j", "-n", "20"],
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return {}
        for job in json.loads(proc.stdout or "[]"):
            if job.get("configuration", {}).get("query", {}).get("query", "").strip() == sql.strip():
                q = job.get("statistics", {}).get("query", {})
                return {
                    "job_id": job.get("jobReference", {}).get("jobId"),
                    "total_bytes_processed": int(q.get("totalBytesProcessed", 0)),
                    "total_bytes_billed": int(q.get("totalBytesBilled", 0)),
                }
        return {}


# --------------------------------------------------------------------------------------
# preflight — cheap completeness sanity check (~2.5 GB/day)
# --------------------------------------------------------------------------------------


def preflight_sql(days: list[date]) -> str:
    day_list = ",".join(f"DATE '{d.isoformat()}'" for d in days)
    return f"""
SELECT DATE(block_timestamp) AS d, COUNT(*) AS txs
FROM {BQ_TX}
WHERE DATE(block_timestamp) IN ({day_list})
GROUP BY d ORDER BY d
""".strip()


@dataclass
class DayCoverage:
    day: str
    txs: int = 0
    median: int = 0

    @property
    def ratio(self) -> float:
        return self.txs / self.median if self.median else 0.0

    @property
    def verdict(self) -> str:
        if not self.txs:
            return "EMPTY"
        return "LOADED" if self.ratio >= TX_COUNT_MIN_RATIO else "PARTIAL"

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "txs": self.txs, "window_median_txs": self.median,
                "ratio": round(self.ratio, 4), "verdict": self.verdict,
                "threshold_ratio": TX_COUNT_MIN_RATIO}


def summarise_preflight(rows: list[dict[str, Any]]) -> dict[str, DayCoverage]:
    counts = {str(r["d"]): int(r["txs"]) for r in rows}
    if not counts:
        return {}
    median = int(statistics.median(counts.values()))
    return {d: DayCoverage(day=d, txs=n, median=median) for d, n in counts.items()}


# --------------------------------------------------------------------------------------
# pull — one UTC day of replay-grade cluster history
# --------------------------------------------------------------------------------------


def pull_sql(day: date, pools: list[str], *, with_signers: bool) -> str:
    """One day, every transaction that touches a cluster pool's vaults.

    The pre/post arrays are narrowed to the pools inside the query so the returned payload
    stays small; the *scan* cost is unaffected, since BigQuery bills the whole column either
    way. ``owner IN (pools)`` is the protocol-agnostic vault discovery ``pools.py`` prescribes.
    """
    nxt = day + timedelta(days=1)
    plist = _sql_list(pools)
    signers = ""
    if with_signers:
        signers = ",\n       ARRAY(SELECT a.pubkey FROM UNNEST(accounts) a WHERE a.signer) AS signers"
    return f"""
SELECT signature, block_slot, UNIX_SECONDS(block_timestamp) AS block_time, index AS tx_index,
       CAST(fee AS STRING) AS fee, err, CAST(compute_units_consumed AS STRING) AS compute_units,
       ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals, account_index
             FROM UNNEST(pre_token_balances) WHERE owner IN ({plist})) AS pre,
       ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals, account_index
             FROM UNNEST(post_token_balances) WHERE owner IN ({plist})) AS post{signers}
FROM {BQ_TX}
WHERE block_timestamp >= TIMESTAMP('{day.isoformat()}')
  AND block_timestamp < TIMESTAMP('{nxt.isoformat()}')
  AND EXISTS(SELECT 1 FROM UNNEST(post_token_balances) b WHERE b.owner IN ({plist}))
ORDER BY block_slot, tx_index
""".strip()


def build_rows(
    transactions: list[dict[str, Any]],
    *,
    provenance: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fold transaction meta into one row per (pool, transaction).

    Netting per transaction is the same choice ``shitcoims_cluster.parse`` makes and for the
    same reason: pre/post balances are transaction-scoped, so a transaction that swaps
    through the same pool twice yields one netted row. That is recorded rather than hidden —
    a consumer must be able to tell a single fill from a net.
    """
    rows: list[dict[str, Any]] = []
    stats = {"transactions": 0, "defects": 0, "failed": 0, "swaps": 0, "other": 0}

    for tx in transactions:
        stats["transactions"] += 1
        signature = tx["signature"]
        failed = bool(tx.get("err"))

        # Group the pool-side balances by pool, then by mint. The vault account address is
        # not in this table (it would need the 267 GB/day `accounts` column), so the mint is
        # the vault key — sufficient here because each pool holds two distinct mints.
        per_pool: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        try:
            for side in ("pre", "post"):
                for rec in tx.get(side) or []:
                    pool = rec["owner"]
                    if pool not in POOLS_BY_ADDRESS:
                        continue
                    slot_for_mint = per_pool[pool].setdefault(
                        rec["mint"], {"mint": rec["mint"], "decimals": int(rec["decimals"])}
                    )
                    slot_for_mint[f"{side}_raw"] = _raw_int(rec["amount"], what=f"{side} amount")
        except ValueError:
            stats["defects"] += 1
            continue

        for pool, vaults_by_mint in per_pool.items():
            spec: PoolSpec = POOLS_BY_ADDRESS[pool]
            observed = frozenset(vaults_by_mint)
            mismatch = spec.mint_mismatch(observed)

            vaults = []
            for mint in sorted(vaults_by_mint):
                v = vaults_by_mint[mint]
                # A balance present on only one side is a vault created or closed inside the
                # transaction; treat the absent side as 0 rather than dropping the leg.
                pre_raw = v.get("pre_raw", 0)
                post_raw = v.get("post_raw", 0)
                vaults.append({
                    "mint": mint, "decimals": v["decimals"],
                    "pre_raw": str(pre_raw), "post_raw": str(post_raw),
                    "delta_raw": str(post_raw - pre_raw),
                })

            deltas = {v["mint"]: int(v["delta_raw"]) for v in vaults}
            credited = [m for m, d in deltas.items() if d > 0]
            debited = [m for m, d in deltas.items() if d < 0]
            if failed:
                # NOT the live tape's `attempt`. A failed transaction moved nothing, so the
                # balances cannot say whether it meant to trade *this* pool or merely listed
                # its vaults while failing somewhere else. Measured, the difference is a
                # factor of ~24 on nosis/SOL (105,457 failures here vs 4,336 live attempts),
                # so calling these attempts would inflate any attempt-rate study by more than
                # an order of magnitude. Narrowing them needs to know which program was
                # invoked — see `log_messages` (3.1 GB/day) in the module docstring.
                kind = "failed"
            elif len(credited) == 1 and len(debited) == 1:
                kind = "swap"
            elif any(deltas.values()):
                kind = "liquidity"
            else:
                kind = "reference"
            stats["failed" if kind == "failed" else "swaps" if kind == "swap" else "other"] += 1

            row: dict[str, Any] = {
                "schema": ROW_SCHEMA,
                "row_id": hashlib.sha256(f"{pool}:{signature}".encode()).hexdigest(),
                "kind": kind,
                "grade": "replay" if spec.replay_sufficient_reserves else "summary",
                "pool": pool,
                "dex": spec.dex,
                "label": spec.label,
                "t_event": datetime.fromtimestamp(int(tx["block_time"]), UTC).isoformat(),
                "chain": {
                    "slot": int(tx["block_slot"]),
                    "signature": signature,
                    "block_time": int(tx["block_time"]),
                    # Not recoverable from getTransaction; this table has it, which is what
                    # makes two transactions in one slot orderable.
                    "tx_index": int(tx["tx_index"]),
                },
                "reserves": {
                    "pool": pool,
                    "dex": spec.dex,
                    # A DLMM fill walks bins; vault totals do not determine price or depth.
                    "replay_sufficient": spec.replay_sufficient_reserves,
                    "vaults": vaults,
                },
                "fee_lamports": str(_raw_int(tx["fee"], what="fee")),
                "compute_units": int(tx["compute_units"]) if tx.get("compute_units") else None,
                "err": tx.get("err") or None,
                # The vault *address* needs the `accounts` column at 267 GB/day; vaults are
                # keyed by mint here. Stated so nobody reads its absence as "no vault".
                "vault_addresses_available": False,
                "provenance": dict(provenance),
            }
            if mismatch:
                # pools.py turns a table/chain disagreement into a defect rather than a
                # silent relabel; carry it on the row instead of dropping the row.
                row["defect"] = mismatch
            if tx.get("signers") is not None:
                row["signers"] = list(tx["signers"])
            if kind == "swap":
                cin, dout = credited[0], debited[0]
                row["token_in_mint"] = cin
                row["token_in_raw"] = str(deltas[cin])
                row["token_out_mint"] = dout
                row["token_out_raw"] = str(-deltas[dout])
            rows.append(row)

    rows.sort(key=lambda r: (r["chain"]["slot"], r["chain"]["tx_index"], r["pool"]))
    return rows, stats


def pull_day(
    bq: BigQuery, day: date, pools: list[str], out_dir: Path, *,
    with_signers: bool, coverage: DayCoverage | None, force: bool,
) -> dict[str, Any]:
    stamp = day.strftime("%Y%m%d")
    data_path = out_dir / "swaps" / f"{stamp}.jsonl"
    meta_path = out_dir / "meta" / f"{stamp}.json"

    if meta_path.exists() and data_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        if meta.get("complete"):
            print(f"  {day} already complete ({meta.get('rows', 0)} rows) — skipping", file=sys.stderr)
            # Flagged so the run summary does not re-report this day's original cost as if
            # it had just been spent again: a resumed run must read as the $0 it was.
            return {**meta, "reused": True}

    sql = pull_sql(day, pools, with_signers=with_signers)
    txs, stats = bq.run(sql)
    provenance = {"source": PROVENANCE_SOURCE, "fetched_at": _now(), "cursor": stats.get("job_id")}
    rows, fold = build_rows(txs, provenance=provenance)

    if not bq.dry_run:
        _atomic_write(data_path, "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))

    per_pool: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        per_pool[r["label"]][r["kind"]] += 1

    meta = {
        "tool": TOOL_VERSION, "day": day.isoformat(), "complete": not bq.dry_run,
        "rows": len(rows), "transactions": fold["transactions"], "defects": fold["defects"],
        "by_kind": {"swap": fold["swaps"], "failed": fold["failed"], "other": fold["other"]},
        "rows_per_pool": {k: dict(sorted(v.items())) for k, v in sorted(per_pool.items())},
        "pools_requested": sorted(pools),
        "grade": "replay for constant-product pools, summary for DLMM (see PoolSpec)",
        "reserves": "pre_raw/post_raw per vault mint, exact integers",
        "signers_included": with_signers,
        "provenance": provenance, "query": sql,
        "query_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "job": stats, "coverage": coverage.to_json() if coverage else None,
        "data_file": str(data_path.relative_to(out_dir)),
    }
    if not bq.dry_run:
        _atomic_write(meta_path, json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


# --------------------------------------------------------------------------------------
# verify — extracted rows against the live tape, where they overlap
# --------------------------------------------------------------------------------------


def verify(out_dir: Path) -> int:
    live: dict[str, dict[str, Any]] = {}
    if LIVE_TAPE.is_dir():
        for path in sorted(LIVE_TAPE.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("kind") == "swap":
                        live[row["row_id"]] = row
    if not live:
        print("no live tape to verify against", file=sys.stderr)
        return 0

    bulk: dict[str, dict[str, Any]] = {}
    for path in sorted((out_dir / "swaps").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                bulk[row["row_id"]] = row
    pulled_days = {json.loads(p.read_text())["day"] for p in sorted((out_dir / "meta").glob("*.json"))}

    exact = differ = missing = 0
    examples: list[str] = []
    for row_id, lrow in live.items():
        if lrow["t_event"][:10] not in pulled_days:
            continue
        brow = bulk.get(row_id)
        if brow is None:
            missing += 1
            continue
        # Compare pre AND post, keyed by mint. Levels, not just deltas: that is the whole
        # difference between a replay tape and a summary tape.
        want = {v["mint"]: (int(v["pre_raw"]), int(v["post_raw"])) for v in lrow["reserves"]["vaults"]}
        got = {v["mint"]: (int(v["pre_raw"]), int(v["post_raw"])) for v in brow["reserves"]["vaults"]}
        if want == got:
            exact += 1
        else:
            differ += 1
            if len(examples) < 5:
                examples.append(f"    {lrow['chain']['signature'][:20]} live={want} bulk={got}")

    comparable = exact + differ + missing
    print(f"live swaps inside pulled days   : {comparable}")
    print(f"  exact pre+post reserve match  : {exact}")
    print(f"  disagreed                     : {differ}")
    print(f"  absent from bulk              : {missing}")
    for line in examples:
        print(line)
    if comparable:
        print(f"  recall                        : {100 * exact / comparable:.1f}%")
    return 1 if differ else 0


# --------------------------------------------------------------------------------------
# selftest — offline, fixtures, no network
# --------------------------------------------------------------------------------------

#: Shaped exactly like a BigQuery `Transactions` row. The numbers are the ones the live RPC
#: collector independently recorded for these signatures, so the fixture pins the agreement
#: that justified choosing this source.
_FIX_SWAP_SIG = (
    "3JYWwLFzEvrEaT94FRrN9VL3V6PoBKVHuEeGD3yKHYMB"
    "BwXtQEezxHMnYZWSaRpWxbYcxrHqCHHtzQNWT5tQnzRx"
)
_FIX_ATTEMPT_SIG = (
    "1cCKoGk1FtPpYuFiYc1CX8boksF3usScZu84RvAU6AQp"
    "sLtiiTcm3tQeZMBwFBwFeDmhu8QHrJmai97RRM6tiVj"
)

FIXTURE_TX: list[dict[str, Any]] = [
    {
        "signature": _FIX_SWAP_SIG,
        "block_slot": "439117814", "block_time": "1786665636", "tx_index": "42",
        "fee": "58296", "err": "", "compute_units": "234295",
        "pre": [
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
             "amount": "745708166270", "decimals": "6", "account_index": "5"},
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
             "amount": "4417042298150", "decimals": "6", "account_index": "6"},
        ],
        "post": [
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
             "amount": "726574810760", "decimals": "6", "account_index": "5"},
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
             "amount": "4461156942807", "decimals": "6", "account_index": "6"},
        ],
    },
    {   # a reverted attempt: balances unchanged, err set
        "signature": _FIX_ATTEMPT_SIG,
        "block_slot": "439117814", "block_time": "1786665636", "tx_index": "7",
        "fee": "5000", "err": "{'InstructionError': [1, {'Custom': 1004}]}", "compute_units": "12000",
        "pre": [
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
             "amount": "745708166270", "decimals": "6", "account_index": "5"},
        ],
        "post": [
            {"owner": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
             "mint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
             "amount": "745708166270", "decimals": "6", "account_index": "5"},
        ],
    },
]


def selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  ok   {name}")
        else:
            failures.append(name)
            print(f"  FAIL {name} {detail}")

    prov = {"source": PROVENANCE_SOURCE, "fetched_at": "2026-08-14T00:00:00+00:00", "cursor": "job-fixture"}
    rows, stats = build_rows(FIXTURE_TX, provenance=prov)
    swap = next((r for r in rows if r["kind"] == "swap"), None)
    attempt = next((r for r in rows if r["kind"] == "failed"), None)

    check("one row per (pool, tx)", len(rows) == 2, str(len(rows)))
    check("swap and failed both classified", swap is not None and attempt is not None)
    check("failed counted separately", stats["failed"] == 1 and stats["swaps"] == 1, str(stats))

    if swap:
        got = {v["mint"]: (v["pre_raw"], v["post_raw"], v["delta_raw"]) for v in swap["reserves"]["vaults"]}
        # Exactly what the live RPC collector recorded for this signature.
        check("pre/post reserves exact", got == {
            "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump":
                ("745708166270", "726574810760", "-19133355510"),
            "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump":
                ("4417042298150", "4461156942807", "44114644657"),
        }, str(got))
        check("amounts serialise as strings", all(
            isinstance(v[k], str) for v in swap["reserves"]["vaults"]
            for k in ("pre_raw", "post_raw", "delta_raw")))
        check("tx_index carried (RPC cannot supply it)", swap["chain"]["tx_index"] == 42)
        check("row_id matches the cluster convention", swap["row_id"] == hashlib.sha256(
            f"{swap['pool']}:{swap['chain']['signature']}".encode()).hexdigest())
        check("direction is the mirror of the deltas",
              swap["token_in_mint"]
              == "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"
              and swap["token_in_raw"] == "44114644657"
              and swap["token_out_raw"] == "19133355510", str(swap.get("token_in_raw")))
        check("DLMM pool is NOT claimed replay-sufficient",
              swap["reserves"]["replay_sufficient"] is False and swap["grade"] == "summary",
              str(swap["grade"]))
        check("fee carried", swap["fee_lamports"] == "58296")
        check("vault address absence is explicit", swap["vault_addresses_available"] is False)

    if attempt:
        check("failed tx has zero delta", all(
            v["delta_raw"] == "0" for v in attempt["reserves"]["vaults"]))
        check("failed tx records err", bool(attempt["err"]))
        check("failed tx has no direction", "token_in_mint" not in attempt)
        check("failed tx is NOT labelled attempt", attempt["kind"] == "failed")

    # A constant-product pool must be allowed to claim replay grade.
    cp = build_rows([{**FIXTURE_TX[0],
                      "pre": [{**b, "owner": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
                               "mint": WSOL_MINT if i else "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"}
                              for i, b in enumerate(FIXTURE_TX[0]["pre"])],
                      "post": [{**b, "owner": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
                                "mint": WSOL_MINT if i else "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"}
                               for i, b in enumerate(FIXTURE_TX[0]["post"])]}],
                    provenance=prov)[0][0]
    check("constant-product pool IS replay grade",
          cp["grade"] == "replay" and cp["reserves"]["replay_sufficient"] is True, cp["grade"])

    # A float amount is the silent-corruption path shitcoims_tape.schema exists to close.
    for bad in (1.5, 2.0, True):
        try:
            _raw_int(bad, what="amount")
            check(f"float/bool {bad!r} refused", False, "accepted")
        except ValueError:
            check(f"float/bool {bad!r} refused", True)
    check("integral BIGNUMERIC string accepted", _raw_int("745708166270.000", what="v") == 745708166270)
    check("amount above 2**53 stays exact",
          _raw_int("9007199254740993000000", what="v") == 9007199254740993000000)

    cov = summarise_preflight([{"d": "2026-08-13", "txs": 310_361_742},
                               {"d": "2026-08-12", "txs": 266_746_538},
                               {"d": "2026-08-11", "txs": 313_787_304}])
    check("normal days read LOADED", all(c.verdict == "LOADED" for c in cov.values()))
    cov = summarise_preflight([{"d": "2026-08-13", "txs": 310_361_742},
                               {"d": "2026-08-12", "txs": 266_746_538},
                               {"d": "2026-08-14", "txs": 51_774_187}])
    check("a short partition reads PARTIAL", cov["2026-08-14"].verdict == "PARTIAL",
          cov["2026-08-14"].verdict)

    sql = pull_sql(date(2026, 8, 13), [p.address for p in CLUSTER_POOLS], with_signers=False)
    check("partition filter present", "block_timestamp >=" in sql and "block_timestamp <" in sql)
    check("filters on vault owner, not a hard-coded vault table", "b.owner IN (" in sql)
    check("all 7 pools in the filter", all(p.address in sql for p in CLUSTER_POOLS))
    check("accounts column excluded unless asked", "UNNEST(accounts)" not in sql)
    check("signers opt-in adds it", "UNNEST(accounts)" in pull_sql(
        date(2026, 8, 13), [CLUSTER_POOLS[0].address], with_signers=True))
    try:
        pull_sql(date(2026, 8, 13), ["'); DROP TABLE x;--"], with_signers=False)
        check("sql injection refused", False, "accepted a non-base58 address")
    except ValueError:
        check("sql injection refused", True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("all selftests passed")
    return 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def default_project() -> str:
    env = os.environ.get("BULK_HISTORY_PROJECT")
    if env:
        return env
    proc = subprocess.run(["gcloud", "config", "get-value", "project"],
                          capture_output=True, text=True, check=False)
    return (proc.stdout or "").strip()


def main(argv: list[str] | None = None) -> int:
    def add_common(target: argparse.ArgumentParser, *, sub: bool) -> None:
        """Accept the shared flags on either side of the subcommand.

        argparse only takes them before the subcommand by default, which is a trap worth
        closing: ``pull --out X`` reads as the obvious spelling and would otherwise fail.
        The subcommand copies suppress their defaults so they only override when actually
        typed, instead of silently clobbering a value given before the subcommand.
        """
        d: Any = argparse.SUPPRESS if sub else None
        target.add_argument("--project", default=d,
                            help="billing project for BigQuery (it pays for bytes scanned)")
        target.add_argument("--out", type=Path, default=DEFAULT_OUT if not sub else argparse.SUPPRESS)
        target.add_argument("--max-bytes", type=int,
                            default=DEFAULT_MAX_BYTES if not sub else argparse.SUPPRESS)
        target.add_argument("--dry-run", action="store_true",
                            default=False if not sub else argparse.SUPPRESS,
                            help="estimate bytes, write nothing")

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common(parser, sub=False)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_common(sub.add_parser("selftest", help="offline fixture tests, no network"), sub=True)
    add_common(sub.add_parser("verify", help="compare pulled rows against the live tape"), sub=True)
    pre = sub.add_parser("preflight", help="cheap per-day completeness check (~2.5 GB/day)")
    add_common(pre, sub=True)
    pre.add_argument("--start", required=True)
    pre.add_argument("--end", required=True)
    pull = sub.add_parser("pull", help="extract a date range into JSONL (~270 GB/day scanned)")
    add_common(pull, sub=True)
    pull.add_argument("--start", required=True)
    pull.add_argument("--end", required=True)
    pull.add_argument("--force", action="store_true", help="re-pull days already marked complete")
    pull.add_argument("--skip-preflight", action="store_true")
    pull.add_argument("--allow-partial", action="store_true",
                      help="pull days the completeness check calls PARTIAL/EMPTY")
    pull.add_argument("--with-signers", action="store_true",
                      help="include the signer list; needs the accounts column, ~+267 GB/day")

    args = parser.parse_args(argv)
    if args.cmd == "selftest":
        return selftest()
    if args.cmd == "verify":
        return verify(args.out)

    project = args.project or default_project()
    if not project:
        raise SystemExit("no billing project: pass --project or set BULK_HISTORY_PROJECT")
    bq = BigQuery(project=project, max_bytes=args.max_bytes, dry_run=args.dry_run)
    days = _days(_parse_day(args.start), _parse_day(args.end))
    pools = [p.address for p in CLUSTER_POOLS]
    print(f"project={project}  days={len(days)}  pools={len(pools)}", file=sys.stderr)

    coverage: dict[str, DayCoverage] = {}
    cache_path = args.out / "preflight.json"
    if args.cmd == "preflight" or not args.skip_preflight:
        cached: dict[str, DayCoverage] = {}
        if cache_path.exists() and not getattr(args, "force", False):
            for key, payload in json.loads(cache_path.read_text()).get("days", {}).items():
                cached[key] = DayCoverage(day=key, txs=payload["txs"],
                                          median=payload["window_median_txs"])
        need = [d for d in days if d.isoformat() not in cached]
        coverage = {d.isoformat(): cached[d.isoformat()] for d in days if d.isoformat() in cached}
        billed = 0
        if need:
            print(f"preflight over {len(need)} day(s) "
                  f"({len(days) - len(need)} cached)...", file=sys.stderr)
            rows, stats = bq.run(preflight_sql(need))
            coverage.update(summarise_preflight(rows))
            billed = stats.get("total_bytes_billed", 0)
            if not bq.dry_run:
                merged = {**{k: v.to_json() for k, v in cached.items()},
                          **{k: v.to_json() for k, v in coverage.items()}}
                _atomic_write(cache_path, json.dumps(
                    {"measured_at": _now(), "project": project,
                     "days": dict(sorted(merged.items()))}, indent=2) + "\n")
        else:
            print(f"preflight: all {len(days)} day(s) cached ($0)", file=sys.stderr)

        print(f"\n{'day':<12} {'verdict':<9} {'transactions':>15} {'vs median':>10}")
        for day in days:
            cov = coverage.get(day.isoformat())
            if cov is None:
                print(f"{day.isoformat():<12} {'NO DATA':<9}")
            else:
                print(f"{day.isoformat():<12} {cov.verdict:<9} {cov.txs:>15,} {cov.ratio * 100:9.1f}%")
        print(f"\npreflight billed {billed / 1e9:.2f} GB "
              f"(${billed / 1.099511627776e12 * 6.25:.2f} on-demand, $0 inside the free tier)",
              file=sys.stderr)
        if args.cmd == "preflight":
            return 0

    total_billed = 0
    pulled: list[dict[str, Any]] = []
    for day in days:
        cov = coverage.get(day.isoformat())
        if cov and cov.verdict != "LOADED" and not args.allow_partial:
            print(f"  {day} SKIPPED — completeness {cov.verdict} "
                  f"({cov.txs:,} txs, {cov.ratio * 100:.1f}% of median). "
                  "Use --allow-partial to pull it anyway.", file=sys.stderr)
            continue
        print(f"  pulling {day}...", file=sys.stderr)
        meta = pull_day(bq, day, pools, args.out, with_signers=args.with_signers,
                        coverage=cov, force=args.force)
        pulled.append(meta)
        if meta.get("reused"):
            continue
        total_billed += meta.get("job", {}).get("total_bytes_billed", 0)
        print(f"    {meta['rows']} rows from {meta['transactions']} transactions "
              f"{meta['by_kind']} ({meta.get('job', {}).get('total_bytes_billed', 0) / 1e9:.2f} GB)",
              file=sys.stderr)

    print(f"\npulled {len(pulled)} day(s), {sum(m['rows'] for m in pulled)} rows, "
          f"{total_billed / 1e9:.2f} GB billed "
          f"(${total_billed / 1.099511627776e12 * 6.25:.2f} on-demand)", file=sys.stderr)
    print("grade: REPLAY for the constant-product pools (pre/post reserves, exact integers); "
          "DLMM pools are summary by nature — see studies/RESULT_bulk_history.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
