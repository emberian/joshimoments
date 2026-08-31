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

Validated against the live RPC collector: over the full 2026-06-27 .. 2026-08-13 pull,
**1611 of 1611 overlapping swaps matched on BOTH pre and post reserves, every digit, on both
vault legs**, with zero disagreements. 54 further live swaps are absent, and ``verify``
reports absences by (day, pool) WITH their time span because that is what makes them
diagnosable: all 54 fall in two CONTIGUOUS windows — SOLVE/SOL 2026-08-12 14:41..17:32, and
weave/DREGG (5%) 2026-08-12 23:58 .. 2026-08-13 02:17 — both anchored on 2026-08-12, the day
already flagged below as carrying a one-off reprocessing in the upstream dataset. A
contiguous window is an upstream hole; the same count scattered across a whole day would
instead mean a parser disagreement. Do not backtest those two windows.

**Exact vault balances are still not replay grade on PumpSwap**, and that is the one claim
this file used to get wrong. A boosted PumpSwap pool prices against
``pool_quote + virtual_quote_reserves``, which lives in the swap event in ``log_messages`` and
is *not* selected here — 17.58 SOL unaccounted on nosis/SOL and weave/SOL, 0 on DREGG/SOL and
SOLVE/SOL (see :mod:`shitcoims_cluster.pumpswap`). Every PumpSwap row is therefore emitted at
``summary`` grade by :func:`_grade`, and ``regrade`` corrects an older tape in place for free.
Including ``log_messages`` in the next full pull costs ~+1.2% and lifts them to replay grade.

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
from typing import Any, Final

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
#: v3 demotes PumpSwap rows from replay to summary grade. See `_grade`.
ROW_SCHEMA = "bulk_history.v3"

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
            # The estimate is what a dry run is FOR, so report it as the number that would be
            # billed. Returning 0 here made `--dry-run` print "$0.00" for a $50 pull, which is
            # the one thing a spend gate must never do.
            return [], {"dryRun": True, "total_bytes_processed": estimate,
                        "total_bytes_billed": estimate, "estimate_only": True}
        proc = subprocess.run(
            [
                *self._base(), "query", "--use_legacy_sql=false", "--nouse_cache",
                f"--max_rows={max_rows}", f"--maximum_bytes_billed={self.max_bytes}",
            ],
            input=sql, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"query failed:\n{proc.stderr.strip()}\n{proc.stdout.strip()}")
        rows = json.loads(proc.stdout or "[]")
        if len(rows) >= max_rows:
            # `bq --max_rows` TRUNCATES silently. A short day would then be written with
            # `complete: true` and no defect, which is the exact failure mode this tool's
            # preflight exists to rule out — so it must never be reachable by the row cap.
            raise RuntimeError(
                f"result hit the --max_rows cap of {max_rows:,} and was silently truncated; "
                "the day would be recorded short. Re-run with a higher cap."
            )
        return rows, self._stats_for(sql)

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


#: Why a PumpSwap row here cannot claim replay grade, carried on every such row.
CURVE_ABSENT_REASON: Final[str] = (
    "pumpswap prices against pool_quote + virtual_quote_reserves and this pull did not "
    "include log_messages, so the virtual term is unknown for this row"
)


def _grade(spec: PoolSpec) -> str:
    """Replay grade, honestly, per pool.

    ``PoolSpec.replay_sufficient_reserves`` says the pool is CONSTANT PRODUCT. That was taken
    to mean "the two vault balances determine the fill", and for PumpSwap it does not: a
    boosted pool prices against ``pool_quote + virtual_quote_reserves``, which is 17.58 SOL on
    nosis/SOL and weave/SOL and 0 on DREGG/SOL and SOLVE/SOL — a 4.6% and 9.6% error on the
    quote leg, large enough to invert the sign of a fitted fee. See
    :mod:`shitcoims_cluster.pumpswap` for the on-chain decode that established it.

    The live recorder reads the virtual term out of the swap event. THIS path cannot: the
    event lives in ``log_messages``, which this pull does not select. So every PumpSwap row
    here is downgraded to ``summary`` rather than shipped asserting a replay grade it does not
    have — "a replay against wrong reserves is worse than no replay".

    THE FIX, costed: ``log_messages`` is 3.1 GB/day against the 263 GB/day this pull already
    scans, so including it is ~+1.2% (~$0.90 across 48 days). It cannot be back-filled cheaply
    as a second pass, because the join key would have to be re-scanned and the pool filter
    lives in ``post_token_balances`` at 114 GB/day — so the next FULL pull should carry it,
    rather than paying for a separate one.
    """

    if not spec.replay_sufficient_reserves:
        return "summary"
    return "summary" if spec.dex == "pumpswap" else "replay"


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
                "grade": _grade(spec),
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
                    # A PumpSwap pool needs its virtual quote reserve too — see _grade().
                    "replay_sufficient": _grade(spec) == "replay",
                    "replay_sufficient_by_type": spec.replay_sufficient_reserves,
                    "curve": {"source": "absent", "reason": CURVE_ABSENT_REASON},
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
    absent_by_cell: dict[tuple[str, str], int] = defaultdict(int)
    absent_span: dict[tuple[str, str], tuple[str, str]] = {}
    for row_id, lrow in live.items():
        if lrow["t_event"][:10] not in pulled_days:
            continue
        brow = bulk.get(row_id)
        if brow is None:
            missing += 1
            cell = (lrow["t_event"][:10], str(lrow.get("label", "?")))
            absent_by_cell[cell] += 1
            span = absent_span.get(cell)
            stamp = str(lrow["t_event"])
            absent_span[cell] = (
                stamp if span is None else min(span[0], stamp),
                stamp if span is None else max(span[1], stamp),
            )
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
    if absent_by_cell:
        # WHERE the misses are is the whole diagnosis. A recall number spread evenly over 48
        # days is a systematic parser difference; the same number concentrated in one
        # (day, pool) cell is a hole in the upstream dataset, and only the second one means
        # "do not backtest that day". The first run of this hit 29 misses at 98.2% recall,
        # ALL of them SOLVE/SOL on 2026-08-12 — the day whose preflight ratio was the
        # window's second-lowest at 91.6% and which the module docstring already flagged as
        # carrying a one-off reprocessing. A flat percentage would have hidden that.
        print("\n  absent rows by (day, pool) — concentration is the diagnosis:")
        for cell, count in sorted(absent_by_cell.items(), key=lambda kv: -kv[1]):
            day, label = cell
            lo, hi = absent_span[cell]
            print(f"    {day}  {label:<18} {count:>6}   {lo[11:19]}..{hi[11:19]}")
        print("    (a CONTIGUOUS window is an upstream hole; rows scattered across a whole "
              "day would instead be a parser disagreement)")
    return 1 if differ else 0


# --------------------------------------------------------------------------------------
# regrade — correct an already-pulled tape in place, for free
# --------------------------------------------------------------------------------------


def regrade(out_dir: Path) -> int:
    """Re-apply :func:`_grade` to a tape pulled by an older version of this tool.

    This is a pure function of ``pools.py`` and the row's own pool, not new data, so it costs
    nothing and needs no BigQuery. It exists because 3.4M rows were pulled asserting
    ``replay_sufficient: true`` for PumpSwap before the boost mechanism was found, and
    leaving them that way would hand a backtester a 4.6%-wrong quote reserve with a flag
    saying it was exact. Re-pulling to fix a flag would cost ~$54 to change one boolean.

    Idempotent; rewrites via temp-and-rename; bumps ``schema`` so the correction is visible
    in the data rather than only in this file's history.
    """

    changed_files = 0
    changed_rows = 0
    for source in sorted((out_dir / "swaps").glob("*.jsonl")):
        out: list[str] = []
        touched = 0
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                spec = POOLS_BY_ADDRESS.get(str(row.get("pool")))
                if spec is None:
                    out.append(line.rstrip("\n"))
                    continue
                grade = _grade(spec)
                reserves = row.get("reserves") or {}
                before = (row.get("grade"), reserves.get("replay_sufficient"), row.get("schema"))
                row["grade"] = grade
                row["schema"] = ROW_SCHEMA
                reserves["replay_sufficient"] = grade == "replay"
                reserves["replay_sufficient_by_type"] = spec.replay_sufficient_reserves
                reserves.setdefault("curve", {"source": "absent", "reason": CURVE_ABSENT_REASON})
                row["reserves"] = reserves
                if before != (row["grade"], reserves["replay_sufficient"], row["schema"]):
                    touched += 1
                out.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
        if not touched:
            continue
        _atomic_write(source, "\n".join(out) + "\n")
        changed_files += 1
        changed_rows += touched
        print(f"  {source.name}: {touched:,} rows regraded", file=sys.stderr)
    print(f"\nregraded {changed_rows:,} rows across {changed_files} file(s) to {ROW_SCHEMA}. "
          "Re-run `parquet` to refresh the derived view.", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------------------
# parquet — the same rows, in the format a backtester can actually scan
# --------------------------------------------------------------------------------------
#
# The JSONL stays the source of truth: it is append-only, diffable, and independent of any
# library version. Parquet is a DERIVED view, rebuildable at any time from the JSONL, and it
# exists because 3.4M rows across 48 files is 10+ GB of JSON that a study has to re-parse on
# every run.
#
# The schema is declared explicitly rather than inferred. Inference would type `err` from
# whichever day happened to be read first (it is null on ~97% of rows), and — the one that
# actually corrupts data — it would type the raw amounts as int64 or double. Every raw amount
# stays a STRING, the same rule tape.py sets: a 1e9-supply 6-decimal token is 1e15 raw units,
# already within one order of magnitude of the 2**53 float cliff.

def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_PARQUET_VAULT = [
    ("mint", "string"), ("decimals", "int32"),
    ("pre_raw", "string"), ("post_raw", "string"), ("delta_raw", "string"),
]
_PARQUET_COLUMNS: list[tuple[str, str, Any]] = [
    ("row_id", "string", lambda r: r.get("row_id")),
    ("schema", "string", lambda r: r.get("schema")),
    ("kind", "string", lambda r: r.get("kind")),
    ("grade", "string", lambda r: r.get("grade")),
    ("pool", "string", lambda r: r.get("pool")),
    ("label", "string", lambda r: r.get("label")),
    ("dex", "string", lambda r: r.get("dex")),
    # pyarrow will not coerce an ISO string into a timestamp column, so it is parsed here.
    # Keeping it a real timestamp is what lets a study filter a day without string-slicing.
    ("t_event", "timestamp", lambda r: _as_datetime(r.get("t_event"))),
    ("block_time", "int64", lambda r: (r.get("chain") or {}).get("block_time")),
    ("slot", "int64", lambda r: (r.get("chain") or {}).get("slot")),
    ("tx_index", "int64", lambda r: (r.get("chain") or {}).get("tx_index")),
    ("signature", "string", lambda r: (r.get("chain") or {}).get("signature")),
    ("err", "string", lambda r: None if r.get("err") is None else json.dumps(r["err"])),
    ("fee_lamports", "string", lambda r: r.get("fee_lamports")),
    ("compute_units", "int64", lambda r: r.get("compute_units")),
    ("token_in_mint", "string", lambda r: r.get("token_in_mint")),
    ("token_in_raw", "string", lambda r: r.get("token_in_raw")),
    ("token_out_mint", "string", lambda r: r.get("token_out_mint")),
    ("token_out_raw", "string", lambda r: r.get("token_out_raw")),
    ("replay_sufficient", "bool", lambda r: (r.get("reserves") or {}).get("replay_sufficient")),
    ("vaults", "vaults", lambda r: (r.get("reserves") or {}).get("vaults") or []),
    ("curve_source", "string",
     lambda r: ((r.get("reserves") or {}).get("curve") or {}).get("source", "absent")),
    ("provenance_cursor", "string", lambda r: (r.get("provenance") or {}).get("cursor")),
]


def _parquet_schema():
    import pyarrow as pa

    kinds = {
        "string": pa.string(), "int32": pa.int32(), "int64": pa.int64(),
        "bool": pa.bool_(), "timestamp": pa.timestamp("us", tz="UTC"),
        "vaults": pa.list_(pa.struct([(n, pa.int32() if k == "int32" else pa.string())
                                      for n, k in _PARQUET_VAULT])),
    }
    return pa.schema([(name, kinds[kind]) for name, kind, _ in _PARQUET_COLUMNS])


def to_parquet(out_dir: Path, *, force: bool = False) -> int:
    """Rewrite every pulled day's JSONL as parquet beside it. Idempotent."""

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit(
            "parquet needs pyarrow: `uv sync --group research` (it is in the research group "
            "precisely so the live sentinel never depends on it)"
        ) from None

    schema = _parquet_schema()
    target_dir = out_dir / "parquet"
    target_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    total_rows = 0
    for source in sorted((out_dir / "swaps").glob("*.jsonl")):
        target = target_dir / (source.stem + ".parquet")
        if target.exists() and not force and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        columns: dict[str, list[Any]] = {name: [] for name, _, _ in _PARQUET_COLUMNS}
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                for name, kind, get in _PARQUET_COLUMNS:
                    value = get(row)
                    if kind == "vaults":
                        value = [
                            {
                                "mint": v.get("mint"),
                                "decimals": v.get("decimals"),
                                "pre_raw": v.get("pre_raw"),
                                "post_raw": v.get("post_raw"),
                                "delta_raw": v.get("delta_raw"),
                            }
                            for v in value
                        ]
                    columns[name].append(value)
        table = pa.Table.from_pydict(
            {name: pa.array(columns[name], type=schema.field(name).type)
             for name, _, _ in _PARQUET_COLUMNS},
            schema=schema,
        )
        # A temp-then-rename, so an interrupted convert never leaves a half-written parquet
        # that reads as a short day.
        temp = target.with_suffix(".parquet.partial")
        pq.write_table(table, temp, compression="zstd", version="2.6")
        temp.replace(target)
        written += 1
        total_rows += table.num_rows
        print(f"  {source.name} -> {target.name}  {table.num_rows:,} rows "
              f"({source.stat().st_size / 1e6:.0f} MB -> {target.stat().st_size / 1e6:.0f} MB)",
              file=sys.stderr)
    jsonl_bytes = sum(p.stat().st_size for p in (out_dir / "swaps").glob("*.jsonl"))
    parquet_bytes = sum(p.stat().st_size for p in target_dir.glob("*.parquet"))
    print(f"\nwrote {written} file(s), {total_rows:,} rows to {target_dir}", file=sys.stderr)
    print(f"jsonl {jsonl_bytes / 1e9:.2f} GB -> parquet {parquet_bytes / 1e9:.2f} GB "
          f"({jsonl_bytes / max(parquet_bytes, 1):.1f}x smaller); the JSONL remains the "
          f"source of truth", file=sys.stderr)
    return 0


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

    # A PumpSwap pool is constant product and STILL not replay grade from this source: the
    # virtual quote reserve it prices against lives in log_messages, which this pull does not
    # select. This check asserted the opposite until the boost mechanism was decoded.
    cp = build_rows([{**FIXTURE_TX[0],
                      "pre": [{**b, "owner": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
                               "mint": WSOL_MINT if i else "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"}
                              for i, b in enumerate(FIXTURE_TX[0]["pre"])],
                      "post": [{**b, "owner": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
                                "mint": WSOL_MINT if i else "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"}
                               for i, b in enumerate(FIXTURE_TX[0]["post"])]}],
                    provenance=prov)[0][0]
    check("pumpswap pool is constant product BUT not replay grade here",
          cp["grade"] == "summary"
          and cp["reserves"]["replay_sufficient"] is False
          and cp["reserves"]["replay_sufficient_by_type"] is True
          and cp["reserves"]["curve"]["source"] == "absent", cp["grade"])

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
    add_common(sub.add_parser("regrade", help="re-apply the replay-grade rule to a pulled tape"),
               sub=True)
    parquet = sub.add_parser("parquet", help="rewrite the pulled JSONL as parquet (derived view)")
    add_common(parquet, sub=True)
    parquet.add_argument("--force", action="store_true", help="rewrite up-to-date files too")
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
    if args.cmd == "regrade":
        return regrade(args.out)
    if args.cmd == "parquet":
        return to_parquet(args.out, force=args.force)

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
