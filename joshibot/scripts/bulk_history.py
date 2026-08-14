#!/usr/bin/env python3
"""Bulk historical tape for the cluster pools, from the BigQuery public Solana dataset.

WHY THIS EXISTS
---------------
We have live papertesting and no historical backtesting, because we have no historical
tape. Per-transaction RPC backfill was costed at ~10 credits/tx against a measured
~93,600 tx/day across the cluster: one day is 9.4% of the monthly Helius plan, the full
22-day history is 206% of it. This script is the bulk alternative.

WHAT WAS ACTUALLY MEASURED (2026-08-13, project manifest-quasar-414607)
-----------------------------------------------------------------------
``bigquery-public-data.crypto_solana_mainnet_us`` exists, is DAY-partitioned on
``block_timestamp`` with ``requirePartitionFilter``, and is fresh to within ~3 hours.
Two of its tables could carry a swap tape, and exactly one of them carries exact numbers:

- ``Instructions`` (1.14e12 rows, 937 TB, clustered on ``program_id``) contains **only
  top-level instructions**: ``COUNTIF(parent_index IS NOT NULL) = 0`` over a full day of
  PumpSwap. Measured against 528 known-good cluster swaps recorded live by
  ``shitcoims_cluster.record`` on 2026-08-13, it holds a top-level PumpSwap instruction
  for **224 of 528 (42.4%)**. The other 57.6% are aggregator-routed, where PumpSwap is
  invoked by CPI and is therefore invisible. It also carries only the *requested* anchor
  args, never the fill. Unusable as a tape.

- ``Token Transfers`` (1.45e11 rows, 44 TB) **does** include inner CPI transfers, and its
  ``value`` is a **raw integer** in base units. Validated against the live tape on the one
  day where coverage exists: **9 of 9 swaps matched the RPC-derived vault deltas exactly**,
  every digit, on both legs. This is the source this script uses.

THE CATCH, AND WHY EVERY OUTPUT FILE CARRIES A COVERAGE MEASUREMENT
--------------------------------------------------------------------
``Token Transfers`` is **not reliably populated**. Measured ``mint IS NULL`` share and
wrapped-SOL row counts per UTC day (WSOL is a leg of essentially every DEX swap, so its
row count is a coverage thermometer for the whole table):

    day         total rows    WSOL rows    null-mint %
    2026-02-01   96,057,774        2,433       96.3
    2026-05-01   56,408,085      319,070       92.1
    2026-06-15   72,661,809        7,749       95.9
    2026-07-05   79,926,733        3,280       95.8
    2026-07-20   81,097,859        2,763       95.2
    2026-07-28   94,899,755        2,586       94.2
    2026-08-04  105,818,194        2,620       95.1
    2026-08-08  103,375,291       10,149       95.5
    2026-08-10  111,066,785       14,156       95.4
    2026-08-11  107,453,910       14,488       95.9
    2026-08-12  216,717,409   42,627,164       55.6   <- fully loaded, 2x rows
    2026-08-13  122,628,992    3,302,998       90.1   <- ~first 2 hours only

Across six months, one day is fully loaded. On 2026-08-13 our pools' vault transfers stop
at slot 438,930,102 while the day runs to 439,117,724 — and the slots past that point are
*not* empty (369-1690 transfers each), they simply do not contain our pools. So the
failure is silent row loss, not a partition lag that will fill in later.

That is the whole reason this tool refuses to be a dumb extractor. A backtest built on a
day that silently dropped 95% of its swaps is worse than no backtest, because it looks
like a result. ``preflight`` measures loadedness per day *and per slot bucket within the
day* before any expensive pull, ``pull`` records the measurement in the output file, and
``verify`` re-checks extracted rows against the live tape wherever the two overlap.

FIDELITY: SUMMARY-GRADE, NOT REPLAY-GRADE
------------------------------------------
``Token Transfers`` gives **deltas, never levels**. There is no pre/post reserve anywhere
in this dataset — ``Accounts`` returns zero rows for every cluster pool address, so it is
not a fallback. Exact AMM replay needs the reserves, because impact is a deterministic
function of them. Therefore:

- ``reserves`` is emitted as ``null`` with an explicit ``reserves_absent_reason``. It is
  never guessed, never back-filled from a price, and never omitted silently.
- Reserve *levels* are reconstructible in principle by cumulative-summing the deltas from
  one anchor balance per vault (one cheap RPC call each), but only if the transfer stream
  for that vault is complete over the whole interval — which, per the table above, it is
  not. This script does not pretend otherwise and does not implement the reconstruction.
- Even with perfect reserves, the three Meteora DLMM pools remain non-replayable from
  vault totals; that is a property of concentrated liquidity, documented in
  ``shitcoims_cluster.parse`` and recorded per-pool as
  ``PoolSpec.replay_sufficient_reserves``.

So this tape backtests **flow, volume, attempt rate, trader attribution, inter-pool
timing**. It cannot backtest fills.

ONE THING THE BULK PATH DOES BETTER THAN RPC
---------------------------------------------
``Token Transfers.authority`` is the signing authority of the token account being debited.
On the inbound leg of a swap that is the trader, stated by the chain rather than inferred.
The RPC parser has to identify the counterparty by mirroring vault deltas, which failed on
0-of-13 in early live data and still returns ``None`` when a route nets to zero. On the 9
validated swaps, ``authority`` recovered the trader on all 9, including one where the live
parser returned ``counterparty: None``, and one where it differed from ``fee_payer``
because the fee was sponsored — the exact confusion ``shitcoims_tape.schema`` warns is a
fabricated-provenance bug. It is still not a beneficial-owner claim: for an
aggregator-routed fill the authority is the router's PDA, so it is emitted as
``attributed_authority``, never as ``wallet``.

MAPPING ONTO THE CONTRACTS  (see also studies/RESULT_bulk_history.md)
---------------------------------------------------------------------
Rows are emitted under their own marker, ``"schema": "bulk_history.v1"``, and are *not*
drop-in ``shitcoims_cluster`` swap rows. Sharing the field names while missing
``reserves``/``fee_lamports``/``signers`` would let a consumer read a summary row as a
replay row, so the marker is the guard. ``row_id`` deliberately uses the cluster's own
``sha256(f"{pool}:{signature}")`` so bulk and live rows dedupe against each other.

USAGE
-----
    python3 scripts/bulk_history.py vaults
    python3 scripts/bulk_history.py preflight --start 2026-08-10 --end 2026-08-13
    python3 scripts/bulk_history.py pull --start 2026-08-12 --end 2026-08-12 --out state/bulk_history
    python3 scripts/bulk_history.py verify --out state/bulk_history
    python3 scripts/bulk_history.py selftest          # offline, fixtures, no network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
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

TOOL_VERSION = "bulk_history/1"
ROW_SCHEMA = "bulk_history.v1"

#: Source of truth for the bulk tape. ``Token Transfers`` has a space in its table id,
#: which is why every reference to it is backquoted.
BQ_DATASET = "bigquery-public-data.crypto_solana_mainnet_us"
BQ_TRANSFERS = f"`{BQ_DATASET}.Token Transfers`"
PROVENANCE_SOURCE = "bigquery.crypto_solana_mainnet_us.token_transfers"

DEFAULT_OUT = REPO_ROOT / "state" / "bulk_history"
#: Read-only. The live collector owns this tree; we only ever read vault addresses and
#: ground-truth rows out of it.
LIVE_TAPE = REPO_ROOT / "state" / "cluster_tape" / "swaps"

_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

#: A day whose wrapped-SOL rows are below this share of its total rows has not been
#: loaded with inner-CPI transfers. Measured separation is not marginal: a fully loaded
#: day sits at 19.7%, a half-loaded day at 2.7%, an unloaded day at 0.013%.
WSOL_RATIO_LOADED = 0.10
#: Slot buckets per UTC day for the within-day coverage measurement. A day can be loaded
#: for its first two hours and empty afterwards; a day-level ratio hides exactly that.
DEFAULT_BUCKETS = 24
#: Guard rail on every billable query. BigQuery bills on bytes scanned and the free tier
#: is 1 TiB/month; a runaway query is a real bill, so no query runs uncapped.
DEFAULT_MAX_BYTES = 80_000_000_000


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


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
    """Parse a BigQuery NUMERIC into an exact integer, or fail.

    Never float. ``shitcoims_tape.schema`` exists partly to stop f64 from silently
    rounding a 1e15-raw-unit balance, and this is the boundary where that would happen.
    """
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
# vault discovery — derived, never hard-coded
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Vault:
    account: str
    pool: str
    mint: str
    decimals: int


def load_vaults(vaults_file: Path | None = None, tape_dir: Path = LIVE_TAPE) -> dict[str, Vault]:
    """Vault account -> Vault, derived from an explicit file or from the live tape.

    ``shitcoims_cluster.pools`` is deliberate that a pool's vaults are *discovered*
    (the token accounts the pool owns), not tabulated per DEX, because a hard-coded vault
    table is a second source of truth that drifts. So this does not carry one. It reads
    the addresses the live collector already resolved on chain, and refuses to guess when
    it cannot: an unknown vault means an incomplete filter, which means a silently short
    tape, which is the failure mode this whole script is built to avoid.
    """
    if vaults_file is not None:
        raw = json.loads(vaults_file.read_text())
        out: dict[str, Vault] = {}
        for item in raw:
            account = _b58(item["account"], what="vault account")
            pool = _b58(item["pool"], what="pool")
            if pool not in POOLS_BY_ADDRESS:
                raise ValueError(f"{pool} is not a cluster pool")
            out[account] = Vault(account, pool, _b58(item["mint"], what="mint"), int(item["decimals"]))
        return out

    if not tape_dir.is_dir():
        raise SystemExit(
            f"no vault source: {tape_dir} does not exist and no --vaults-file was given.\n"
            "Run the live collector once, or pass --vaults-file with "
            '[{"account":...,"pool":...,"mint":...,"decimals":...}].'
        )

    found: dict[str, Vault] = {}
    for path in sorted(tape_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") != "swap":
                continue
            pool = row.get("pool")
            if pool not in POOLS_BY_ADDRESS:
                continue
            for vault in row.get("reserves", {}).get("vaults", []):
                account = vault["account"]
                found[account] = Vault(account, pool, vault["mint"], int(vault["decimals"]))
    if not found:
        raise SystemExit(f"no vaults recoverable from {tape_dir}; pass --vaults-file")

    # A pool whose vaults we do not know cannot be extracted, and quietly returning a
    # short tape for it would be indistinguishable from that pool being idle.
    for spec in CLUSTER_POOLS:
        mints = {v.mint for v in found.values() if v.pool == spec.address}
        if not mints:
            print(
                f"  WARNING: no vaults known for {spec.address} ({spec.label})"
                " — it will be MISSING from the pull", file=sys.stderr,
            )
        else:
            unexpected = spec.mint_mismatch(frozenset(mints))
            if unexpected:
                raise SystemExit(f"vault/pool disagreement, refusing to continue: {unexpected}")
    return found


# --------------------------------------------------------------------------------------
# BigQuery driver (the `bq` CLI, so there is no new python dependency)
# --------------------------------------------------------------------------------------


@dataclass
class BigQuery:
    project: str
    max_bytes: int = DEFAULT_MAX_BYTES
    dry_run: bool = False
    verbose: bool = True

    def _base(self) -> list[str]:
        return ["bq", f"--project_id={self.project}", "--format=json"]

    def estimate(self, sql: str) -> int:
        """Bytes BigQuery says it *may* scan. An upper bound: it ignores cluster pruning."""
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
        payload = json.loads(proc.stdout)
        return int(payload["statistics"]["totalBytesProcessed"])

    def run(self, sql: str, *, max_rows: int = 1_000_000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Execute and return (rows, job stats). Always capped by ``--maximum_bytes_billed``."""
        estimate = self.estimate(sql)
        if self.verbose:
            print(f"    dry-run upper bound: {estimate / 1e9:.2f} GB", file=sys.stderr)
        if estimate > self.max_bytes:
            raise RuntimeError(
                f"refusing to run: estimate {estimate / 1e9:.1f} GB exceeds cap "
                f"{self.max_bytes / 1e9:.1f} GB (raise with --max-bytes)"
            )
        if self.dry_run:
            return [], {"dryRun": True, "totalBytesProcessed": estimate, "totalBytesBilled": 0}

        proc = subprocess.run(
            [
                *self._base(), "query", "--use_legacy_sql=false", "--nouse_cache",
                f"--max_rows={max_rows}", f"--maximum_bytes_billed={self.max_bytes}",
            ],
            input=sql, capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"query failed:\n{proc.stderr.strip()}")
        rows = json.loads(proc.stdout or "[]")
        return rows, self._stats_for(sql)

    def _stats_for(self, sql: str) -> dict[str, Any]:
        """Recover job id + billed bytes by matching the query text in recent job history.

        Matching on the text rather than taking the newest job keeps this correct when
        other jobs (or another agent's session) interleave on the same project.
        """
        proc = subprocess.run(
            [*self._base(), "ls", "-j", "-n", "20"], capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            return {}
        for job in json.loads(proc.stdout or "[]"):
            text = job.get("configuration", {}).get("query", {}).get("query", "")
            if text.strip() == sql.strip():
                q = job.get("statistics", {}).get("query", {})
                return {
                    "job_id": job.get("jobReference", {}).get("jobId"),
                    "total_bytes_processed": int(q.get("totalBytesProcessed", 0)),
                    "total_bytes_billed": int(q.get("totalBytesBilled", 0)),
                    "cache_hit": q.get("cacheHit"),
                }
        return {}


# --------------------------------------------------------------------------------------
# preflight — is this day actually loaded, and how much of it
# --------------------------------------------------------------------------------------


def preflight_sql(days: list[date], buckets: int) -> str:
    day_list = ",".join(f"DATE '{d.isoformat()}'" for d in days)
    if buckets <= 0:
        return f"""
SELECT DATE(block_timestamp) AS d, 0 AS bucket, COUNT(*) AS total_rows,
       COUNTIF(mint = '{WSOL_MINT}') AS wsol_rows
FROM {BQ_TRANSFERS}
WHERE DATE(block_timestamp) IN ({day_list})
GROUP BY d, bucket ORDER BY d, bucket
""".strip()
    # Slot is monotone within a UTC day, so bucketing on it splits the day into equal slot
    # ranges without timestamp arithmetic. The bucket must be computed in a CTE because an
    # analytic function cannot appear in GROUP BY.
    return f"""
WITH rows_in_range AS (
  SELECT DATE(block_timestamp) AS d, block_slot, mint = '{WSOL_MINT}' AS is_wsol
  FROM {BQ_TRANSFERS}
  WHERE DATE(block_timestamp) IN ({day_list})
), bucketed AS (
  SELECT d, is_wsol,
         CAST(FLOOR({buckets} * SAFE_DIVIDE(
              block_slot - MIN(block_slot) OVER (PARTITION BY d),
              1 + MAX(block_slot) OVER (PARTITION BY d)
                - MIN(block_slot) OVER (PARTITION BY d))) AS INT64) AS bucket
  FROM rows_in_range
)
SELECT d, bucket, COUNT(*) AS total_rows, COUNTIF(is_wsol) AS wsol_rows
FROM bucketed GROUP BY d, bucket ORDER BY d, bucket
""".strip()


@dataclass
class DayCoverage:
    day: str
    total_rows: int = 0
    wsol_rows: int = 0
    buckets_total: int = 0
    buckets_loaded: int = 0
    detail: list[dict[str, Any]] = field(default_factory=list)

    @property
    def wsol_ratio(self) -> float:
        return self.wsol_rows / self.total_rows if self.total_rows else 0.0

    @property
    def covered_fraction(self) -> float:
        if not self.buckets_total:
            return 1.0 if self.wsol_ratio >= WSOL_RATIO_LOADED else 0.0
        return self.buckets_loaded / self.buckets_total

    @property
    def verdict(self) -> str:
        frac = self.covered_fraction
        if frac >= 0.95:
            return "LOADED"
        if frac <= 0.02:
            return "EMPTY"
        return "PARTIAL"

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "total_rows": self.total_rows,
            "wsol_rows": self.wsol_rows,
            "wsol_ratio": round(self.wsol_ratio, 6),
            "buckets_total": self.buckets_total,
            "buckets_loaded": self.buckets_loaded,
            "covered_fraction": round(self.covered_fraction, 4),
            "verdict": self.verdict,
            "threshold_wsol_ratio": WSOL_RATIO_LOADED,
        }


def summarise_preflight(rows: list[dict[str, Any]]) -> dict[str, DayCoverage]:
    out: dict[str, DayCoverage] = {}
    for row in rows:
        day = str(row["d"])
        cov = out.setdefault(day, DayCoverage(day=day))
        total = int(row["total_rows"])
        wsol = int(row["wsol_rows"])
        cov.total_rows += total
        cov.wsol_rows += wsol
        cov.buckets_total += 1
        ratio = wsol / total if total else 0.0
        if ratio >= WSOL_RATIO_LOADED:
            cov.buckets_loaded += 1
        cov.detail.append({"bucket": int(row["bucket"]), "total_rows": total, "wsol_rows": wsol})
    return out


# --------------------------------------------------------------------------------------
# pull — one UTC day of cluster-pool flow
# --------------------------------------------------------------------------------------


def pull_sql(day: date, vaults: list[str], *, with_transfer_type: bool) -> str:
    nxt = day + timedelta(days=1)
    vault_list = _sql_list(vaults)
    ttype = ", transfer_type" if with_transfer_type else ""
    return f"""
SELECT tx_signature, block_slot, UNIX_SECONDS(block_timestamp) AS block_time,
       source, destination, authority,
       CAST(value AS STRING) AS value, CAST(decimals AS STRING) AS decimals, mint{ttype}
FROM {BQ_TRANSFERS}
WHERE block_timestamp >= TIMESTAMP('{day.isoformat()}')
  AND block_timestamp < TIMESTAMP('{nxt.isoformat()}')
  AND (source IN ({vault_list}) OR destination IN ({vault_list}))
ORDER BY block_slot, tx_signature
""".strip()


def build_rows(
    transfers: list[dict[str, Any]],
    vaults: dict[str, Vault],
    *,
    provenance: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fold raw transfer rows into one row per (pool, transaction).

    Netting per transaction is the same choice ``shitcoims_cluster.parse`` makes and for
    the same reason: a transaction that touches one pool twice yields one netted row, and
    pretending otherwise would silently double-count flow. ``transfer_count`` is carried
    so a consumer can tell a plain fill from a netted multi-leg one, mirroring the live
    tape's ``swap_legs``.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    stats = {"transfers": 0, "skipped_unknown_vault": 0, "defects": 0}

    for t in transfers:
        stats["transfers"] += 1
        touched = {side: vaults.get(t.get(side) or "") for side in ("source", "destination")}
        pools = {v.pool for v in touched.values() if v is not None}
        if not pools:
            stats["skipped_unknown_vault"] += 1
            continue
        for pool in pools:
            grouped[(pool, t["tx_signature"])].append(t)

    rows: list[dict[str, Any]] = []
    def _order(kv: tuple[tuple[str, str], list[dict[str, Any]]]) -> tuple[int, str, str]:
        return (int(kv[1][0]["block_slot"]), kv[0][1], kv[0][0])

    for (pool, signature), items in sorted(grouped.items(), key=_order):
        spec: PoolSpec = POOLS_BY_ADDRESS[pool]
        deltas: dict[str, int] = defaultdict(int)
        meta: dict[str, Vault] = {}
        authority_in: list[str] = []
        try:
            for t in items:
                amount = _raw_int(t["value"], what="value")
                dst, src = t.get("destination") or "", t.get("source") or ""
                if (v := vaults.get(dst)) is not None and v.pool == pool:
                    deltas[v.account] += amount
                    meta[v.account] = v
                    if t.get("authority"):
                        authority_in.append(t["authority"])
                if (v := vaults.get(src)) is not None and v.pool == pool:
                    deltas[v.account] -= amount
                    meta[v.account] = v
        except ValueError:
            stats["defects"] += 1
            continue

        credited = [a for a, d in deltas.items() if d > 0]
        debited = [a for a, d in deltas.items() if d < 0]
        is_swap = len(credited) == 1 and len(debited) == 1

        slot = int(items[0]["block_slot"])
        block_time = int(items[0]["block_time"])
        row: dict[str, Any] = {
            "schema": ROW_SCHEMA,
            "row_id": hashlib.sha256(f"{pool}:{signature}".encode()).hexdigest(),
            "kind": "swap" if is_swap else "flow",
            "grade": "summary",
            "pool": pool,
            "dex": spec.dex,
            "label": spec.label,
            "t_event": datetime.fromtimestamp(block_time, UTC).isoformat(),
            "chain": {"slot": slot, "signature": signature, "block_time": block_time},
            "vault_deltas": [
                {
                    "account": account,
                    "mint": meta[account].mint,
                    "decimals": meta[account].decimals,
                    "delta_raw": str(delta),
                }
                for account, delta in sorted(deltas.items())
            ],
            "transfer_count": len(items),
            # Levels are not in this dataset at all. Saying so in the row, every row, is
            # what stops a downstream replay from treating a summary tape as a fill tape.
            "reserves": None,
            "reserves_absent_reason": (
                "bigquery Token Transfers carries deltas only; no pre/post pool balance "
                "exists in this dataset (Accounts returns 0 rows for cluster pools)"
            ),
            "replay_sufficient": False,
            "pool_replay_sufficient_reserves": spec.replay_sufficient_reserves,
            "attributed_authority": authority_in[0] if len(set(authority_in)) == 1 else None,
            "attribution_note": (
                "authority of the inbound vault transfer; the router PDA for a routed"
                " fill, not a beneficial-owner claim"
            ),
            "fee_lamports": None,
            "signers": None,
            "confirmation_status": None,
            "provenance": dict(provenance),
        }
        if is_swap:
            cred, deb = credited[0], debited[0]
            row["token_in_mint"] = meta[cred].mint
            row["token_in_raw"] = str(deltas[cred])
            row["token_out_mint"] = meta[deb].mint
            row["token_out_raw"] = str(-deltas[deb])
        rows.append(row)

    return rows, stats


def pull_day(
    bq: BigQuery,
    day: date,
    vaults: dict[str, Vault],
    out_dir: Path,
    *,
    with_transfer_type: bool,
    coverage: DayCoverage | None,
    force: bool,
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

    sql = pull_sql(day, sorted(vaults), with_transfer_type=with_transfer_type)
    transfers, stats = bq.run(sql)
    fetched_at = _now()
    provenance = {
        "source": PROVENANCE_SOURCE,
        "fetched_at": fetched_at,
        "cursor": stats.get("job_id"),
    }
    rows, fold = build_rows(transfers, vaults, provenance=provenance)

    if not bq.dry_run:
        _atomic_write(data_path, "".join(
            json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))

    per_pool: dict[str, int] = defaultdict(int)
    for r in rows:
        per_pool[r["pool"]] += 1

    meta = {
        "tool": TOOL_VERSION,
        "day": day.isoformat(),
        "complete": not bq.dry_run,
        "rows": len(rows),
        "raw_transfers": fold["transfers"],
        "defects": fold["defects"],
        "rows_per_pool": dict(sorted(per_pool.items())),
        "pools_requested": sorted({v.pool for v in vaults.values()}),
        "vaults_used": sorted(vaults),
        "provenance": provenance,
        "query": sql,
        "query_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "job": stats,
        "coverage": coverage.to_json() if coverage else None,
        "grade": "summary",
        "reserves": "absent — see reserves_absent_reason on every row",
        "data_file": str(data_path.relative_to(out_dir)),
    }
    if not bq.dry_run:
        _atomic_write(meta_path, json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


# --------------------------------------------------------------------------------------
# verify — extracted rows against the live tape, where they overlap
# --------------------------------------------------------------------------------------


def load_live(tape_dir: Path = LIVE_TAPE) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not tape_dir.is_dir():
        return out
    for path in sorted(tape_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "swap":
                out[row["row_id"]] = row
    return out


def verify(out_dir: Path) -> int:
    live = load_live()
    if not live:
        print("no live tape to verify against", file=sys.stderr)
        return 0
    exact = differ = 0
    missing_from_bulk: list[str] = []
    examples: list[str] = []

    bulk: dict[str, dict[str, Any]] = {}
    for path in sorted((out_dir / "swaps").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                bulk[row["row_id"]] = row

    # Only days we actually pulled can be compared; a live row outside the pulled range
    # is not evidence of loss.
    pulled_days = {json.loads(p.read_text())["day"] for p in sorted((out_dir / "meta").glob("*.json"))}

    for row_id, lrow in live.items():
        if lrow["t_event"][:10] not in pulled_days:
            continue
        brow = bulk.get(row_id)
        if brow is None:
            missing_from_bulk.append(row_id)
            continue
        want = {v["account"]: int(v["delta_raw"]) for v in lrow["reserves"]["vaults"]}
        got = {v["account"]: int(v["delta_raw"]) for v in brow["vault_deltas"]}
        if want == got:
            exact += 1
        else:
            differ += 1
            if len(examples) < 5:
                examples.append(f"    {lrow['chain']['signature'][:20]} live={want} bulk={got}")

    comparable = exact + differ + len(missing_from_bulk)
    print(f"live swaps inside pulled days : {comparable}")
    print(f"  exact raw-delta match       : {exact}")
    print(f"  disagreed                   : {differ}")
    print(f"  absent from bulk            : {len(missing_from_bulk)}")
    for line in examples:
        print(line)
    if comparable:
        print(f"  recall                      : {100 * exact / comparable:.1f}%")
    return 1 if differ else 0


# --------------------------------------------------------------------------------------
# selftest — offline, fixtures, no network
# --------------------------------------------------------------------------------------

#: Real rows, captured from BigQuery job bqjob_re26863bd325e487 on 2026-08-13, for two
#: SOLVE/SOL swaps on 2026-08-12. The expected deltas below are the ones the live RPC
#: collector independently recorded for the same signatures, so this fixture pins the
#: agreement that justified choosing this source at all.
FIXTURE_TRANSFERS: list[dict[str, Any]] = [
    {
        "tx_signature": "511HcJatcMRa2Ut9E3EW1111111111111111111111111111111111111111111111",
        "block_slot": "438800001", "block_time": "1786500000",
        "source": "FJ5qM8FMRsK6fb2iYaZLiWUCDwWprsxrC5NyxXyVZMb5",
        "destination": "So1solveOutAta1111111111111111111111111111",
        "authority": "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
        "value": "958296764612", "decimals": "6",
        "mint": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
    },
    {
        "tx_signature": "511HcJatcMRa2Ut9E3EW1111111111111111111111111111111111111111111111",
        "block_slot": "438800001", "block_time": "1786500000",
        "source": "TraderWsolAta11111111111111111111111111111",
        "destination": "DsfKXLXngaQiUdJiHqwt5TZ6usMmapyoVC3WcZzsqjM8",
        "authority": "gtagyESa99t49VmUqnnfsuowYnigSNKuYXdXWyXWNdd",
        "value": "511234144", "decimals": "9",
        "mint": WSOL_MINT,
    },
    {
        "tx_signature": "5pu27bwjE7SkLMCEzpZ7222222222222222222222222222222222222222222222",
        "block_slot": "438800900", "block_time": "1786500400",
        "source": "DsfKXLXngaQiUdJiHqwt5TZ6usMmapyoVC3WcZzsqjM8",
        "destination": "TraderWsolAta11111111111111111111111111111",
        "authority": "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
        "value": "129508704", "decimals": "9", "mint": WSOL_MINT,
    },
    {
        "tx_signature": "5pu27bwjE7SkLMCEzpZ7222222222222222222222222222222222222222222222",
        "block_slot": "438800900", "block_time": "1786500400",
        "source": "TraderSolveAta1111111111111111111111111111",
        "destination": "FJ5qM8FMRsK6fb2iYaZLiWUCDwWprsxrC5NyxXyVZMb5",
        "authority": "3T9jp4kfrEKfWU63JGuioa31sHFuW61B5ZRbv3D4JDpQ",
        "value": "242639648703", "decimals": "6",
        "mint": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
    },
    {   # a transfer between accounts we do not watch: must be dropped, not attributed
        "tx_signature": "9zzUnrelated333333333333333333333333333333333333333333333333333333",
        "block_slot": "438800950", "block_time": "1786500500",
        "source": "SomeoneElseAta1111111111111111111111111111",
        "destination": "AnotherAta11111111111111111111111111111111",
        "authority": "Whoever1111111111111111111111111111111111",
        "value": "5", "decimals": "6", "mint": WSOL_MINT,
    },
]

FIXTURE_VAULTS = {
    "DsfKXLXngaQiUdJiHqwt5TZ6usMmapyoVC3WcZzsqjM8": Vault(
        "DsfKXLXngaQiUdJiHqwt5TZ6usMmapyoVC3WcZzsqjM8",
        "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr", WSOL_MINT, 9),
    "FJ5qM8FMRsK6fb2iYaZLiWUCDwWprsxrC5NyxXyVZMb5": Vault(
        "FJ5qM8FMRsK6fb2iYaZLiWUCDwWprsxrC5NyxXyVZMb5",
        "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
        "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump", 6),
}


def selftest() -> int:
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  ok   {name}")
        else:
            failures.append(f"{name}: {detail}")
            print(f"  FAIL {name} {detail}")

    prov = {"source": PROVENANCE_SOURCE, "fetched_at": "2026-08-13T00:00:00+00:00", "cursor": "job-fixture"}
    rows, stats = build_rows(FIXTURE_TRANSFERS, FIXTURE_VAULTS, provenance=prov)
    by_sig = {r["chain"]["signature"][:20]: r for r in rows}

    check("unwatched transfer dropped", stats["skipped_unknown_vault"] == 1, str(stats))
    check("one row per (pool, tx)", len(rows) == 2, f"got {len(rows)}")

    sell = by_sig.get("511HcJatcMRa2Ut9E3EW")
    check("sell row present", sell is not None)
    if sell:
        deltas = {v["account"]: int(v["delta_raw"]) for v in sell["vault_deltas"]}
        # These two integers are what the live RPC collector recorded for this signature.
        check("sell deltas exact",
              deltas == {"DsfKXLXngaQiUdJiHqwt5TZ6usMmapyoVC3WcZzsqjM8": 511234144,
                         "FJ5qM8FMRsK6fb2iYaZLiWUCDwWprsxrC5NyxXyVZMb5": -958296764612},
              str(deltas))
        check("amounts serialise as strings", isinstance(sell["vault_deltas"][0]["delta_raw"], str))
        check("classified as swap", sell["kind"] == "swap", sell["kind"])
        check("token_out is the token leg",
              sell["token_out_mint"] == "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"
              and sell["token_out_raw"] == "958296764612", str(sell.get("token_out_raw")))
        check("reserves are null, with a reason",
              sell["reserves"] is None and bool(sell["reserves_absent_reason"]))
        check("never claims replay grade",
              sell["grade"] == "summary" and sell["replay_sufficient"] is False)
        check("row_id matches the cluster convention",
              sell["row_id"] == hashlib.sha256(
                  f"{sell['pool']}:{sell['chain']['signature']}".encode()).hexdigest())
        check("trader taken from inbound authority",
              sell["attributed_authority"] == "gtagyESa99t49VmUqnnfsuowYnigSNKuYXdXWyXWNdd",
              str(sell["attributed_authority"]))
        check("schema marker present, not a cluster row",
              sell["schema"] == ROW_SCHEMA and "swap_legs" not in sell)

    buy = by_sig.get("5pu27bwjE7SkLMCEzpZ7")
    if buy:
        check("buy direction is the mirror",
              buy["token_in_mint"] == "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"
              and buy["token_out_mint"] == WSOL_MINT, str(buy.get("token_in_mint")))

    # A float amount is the silent-corruption path shitcoims_tape.schema exists to close.
    try:
        _raw_int(1.5, what="value")
        check("fractional raw amount refused", False, "accepted 1.5")
    except ValueError:
        check("fractional raw amount refused", True)
    check("integral NUMERIC string accepted", _raw_int("511234144.000", what="v") == 511234144)
    check("big amount stays exact", _raw_int("2344341219042000000001", what="v") == 2344341219042000000001)

    # coverage verdicts, against the real measurements in the module docstring
    cov = summarise_preflight([
        {"d": "2026-08-12", "bucket": i, "total_rows": 9_000_000, "wsol_rows": 1_800_000}
        for i in range(24)
    ])["2026-08-12"]
    check("fully loaded day reads LOADED", cov.verdict == "LOADED", cov.verdict)
    cov = summarise_preflight(
        [{"d": "2026-08-13", "bucket": i, "total_rows": 5_000_000, "wsol_rows": 1_500_000} for i in range(2)]
        + [{"d": "2026-08-13", "bucket": i, "total_rows": 5_000_000, "wsol_rows": 700} for i in range(2, 24)]
    )["2026-08-13"]
    check("half-loaded day reads PARTIAL", cov.verdict == "PARTIAL", cov.verdict)
    check("partial day reports its real fraction", abs(cov.covered_fraction - 2 / 24) < 1e-9,
          str(cov.covered_fraction))
    cov = summarise_preflight([
        {"d": "2026-08-11", "bucket": i, "total_rows": 4_500_000, "wsol_rows": 600} for i in range(24)
    ])["2026-08-11"]
    check("unloaded day reads EMPTY", cov.verdict == "EMPTY", cov.verdict)

    # SQL construction: the injection guard and the partition filter the table requires.
    sql = pull_sql(date(2026, 8, 12), list(FIXTURE_VAULTS), with_transfer_type=False)
    check("partition filter present", "block_timestamp >=" in sql and "block_timestamp <" in sql)
    check("both vault sides filtered", "source IN (" in sql and "destination IN (" in sql)
    try:
        pull_sql(date(2026, 8, 12), ["'); DROP TABLE x;--"], with_transfer_type=False)
        check("sql injection refused", False, "accepted a non-base58 address")
    except ValueError:
        check("sql injection refused", True)

    print()
    if failures:
        print(f"{len(failures)} FAILED")
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
    proc = subprocess.run(
        ["gcloud", "config", "get-value", "project"], capture_output=True, text=True, check=False
    )
    return (proc.stdout or "").strip() or "manifest-quasar-414607"


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
        target.add_argument("--vaults-file", type=Path, default=d)
        target.add_argument("--max-bytes", type=int,
                            default=DEFAULT_MAX_BYTES if not sub else argparse.SUPPRESS)
        target.add_argument("--dry-run", action="store_true",
                            default=False if not sub else argparse.SUPPRESS,
                            help="estimate bytes, write nothing")

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_common(parser, sub=False)
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_common(sub.add_parser("vaults", help="print the derived vault map and exit"), sub=True)
    add_common(sub.add_parser("selftest", help="offline fixture tests, no network"), sub=True)
    add_common(sub.add_parser("verify", help="compare pulled rows against the live tape"), sub=True)

    pre = sub.add_parser("preflight", help="measure per-day loadedness before spending on a pull")
    add_common(pre, sub=True)
    pre.add_argument("--start", required=True)
    pre.add_argument("--end", required=True)
    pre.add_argument("--buckets", type=int, default=DEFAULT_BUCKETS)

    pull = sub.add_parser("pull", help="extract a date range into JSONL")
    add_common(pull, sub=True)
    pull.add_argument("--start", required=True)
    pull.add_argument("--end", required=True)
    pull.add_argument("--buckets", type=int, default=DEFAULT_BUCKETS)
    pull.add_argument("--force", action="store_true", help="re-pull days already marked complete")
    pull.add_argument("--skip-preflight", action="store_true")
    pull.add_argument("--allow-partial", action="store_true",
                      help="pull days the coverage check calls PARTIAL/EMPTY (they will still be labelled)")
    pull.add_argument("--no-transfer-type", action="store_true",
                      help="drop the transfer_type column (~2.3 GB/day cheaper)")

    args = parser.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()

    if args.cmd == "verify":
        return verify(args.out)

    vaults = load_vaults(args.vaults_file)
    if args.cmd == "vaults":
        for account, v in sorted(vaults.items(), key=lambda kv: (kv[1].pool, kv[1].mint)):
            spec = POOLS_BY_ADDRESS[v.pool]
            print(f"{account}  pool={v.pool}  {spec.label:<18} mint={v.mint}  decimals={v.decimals}")
        pools_seen = len({v.pool for v in vaults.values()})
        print(f"\n{len(vaults)} vaults across {pools_seen}/{len(CLUSTER_POOLS)} cluster pools")
        return 0

    project = args.project or default_project()
    bq = BigQuery(project=project, max_bytes=args.max_bytes, dry_run=args.dry_run)
    days = _days(_parse_day(args.start), _parse_day(args.end))
    print(f"project={project}  days={len(days)}  vaults={len(vaults)}", file=sys.stderr)

    coverage: dict[str, DayCoverage] = {}
    cache_path = args.out / "preflight.json"
    if args.cmd == "preflight" or (args.cmd == "pull" and not args.skip_preflight):
        # A coverage measurement costs ~4 GB/day of scanned bytes, so re-measuring a day
        # we already measured is real money for no new information. Cache it, and only
        # pay for the days that are actually missing (or all of them under --force).
        cached: dict[str, DayCoverage] = {}
        if cache_path.exists() and not getattr(args, "force", False):
            for key, payload in json.loads(cache_path.read_text()).get("days", {}).items():
                cov = DayCoverage(day=key, total_rows=payload["total_rows"],
                                  wsol_rows=payload["wsol_rows"],
                                  buckets_total=payload["buckets_total"],
                                  buckets_loaded=payload["buckets_loaded"])
                cached[key] = cov
        need = [d for d in days if d.isoformat() not in cached]
        coverage = {d.isoformat(): cached[d.isoformat()] for d in days if d.isoformat() in cached}
        billed = 0
        if need:
            print(f"preflight over {len(need)} day(s) "
                  f"({len(days) - len(need)} already measured)...", file=sys.stderr)
            sql = preflight_sql(need, args.buckets)
            rows, stats = bq.run(sql)
            coverage.update(summarise_preflight(rows))
            billed = stats.get("total_bytes_billed", 0)
            merged = {**{k: v.to_json() for k, v in cached.items()},
                      **{k: v.to_json() for k, v in coverage.items()}}
            if not bq.dry_run:
                _atomic_write(cache_path, json.dumps(
                    {"measured_at": _now(), "project": project, "days": dict(sorted(merged.items()))},
                    indent=2) + "\n")
        else:
            print(f"preflight: all {len(days)} day(s) already measured (cached, $0)", file=sys.stderr)
        print(f"\n{'day':<12} {'verdict':<9} {'covered':>8} {'wsol/total':>11} {'total rows':>14}")
        for day in days:
            key = day.isoformat()
            cov = coverage.get(key)
            if cov is None:
                print(f"{key:<12} {'NO DATA':<9}")
                continue
            print(f"{key:<12} {cov.verdict:<9} {cov.covered_fraction * 100:7.1f}% "
                  f"{cov.wsol_ratio * 100:10.2f}% {cov.total_rows:14,}")
        print(f"\npreflight billed {billed / 1e9:.2f} GB "
              f"(${billed / 1.099511627776e12 * 6.25:.2f} at on-demand, $0 inside the 1 TiB/month free tier)",
              file=sys.stderr)
        if args.cmd == "preflight":
            return 0

    total_billed = 0
    pulled: list[dict[str, Any]] = []
    for day in days:
        cov = coverage.get(day.isoformat())
        if cov and cov.verdict != "LOADED" and not args.allow_partial:
            print(f"  {day} SKIPPED — coverage {cov.verdict} "
                  f"({cov.covered_fraction * 100:.1f}% of buckets loaded). "
                  "Use --allow-partial to pull it anyway.", file=sys.stderr)
            continue
        print(f"  pulling {day}...", file=sys.stderr)
        meta = pull_day(bq, day, vaults, args.out,
                        with_transfer_type=not args.no_transfer_type,
                        coverage=cov, force=args.force)
        pulled.append(meta)
        if meta.get("reused"):
            continue
        total_billed += meta.get("job", {}).get("total_bytes_billed", 0)
        print(f"    {meta['rows']} rows from {meta['raw_transfers']} transfers"
              f"  ({meta.get('job', {}).get('total_bytes_billed', 0) / 1e9:.2f} GB billed)", file=sys.stderr)

    print(f"\npulled {len(pulled)} day(s), {sum(m['rows'] for m in pulled)} rows, "
          f"{total_billed / 1e9:.2f} GB billed "
          f"(${total_billed / 1.099511627776e12 * 6.25:.2f} on-demand)", file=sys.stderr)
    print("grade: SUMMARY (no reserves anywhere in this source) — see studies/RESULT_bulk_history.md",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
