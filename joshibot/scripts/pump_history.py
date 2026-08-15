#!/usr/bin/env python3
"""The all-pump.fun tape: repack the BigQuery export, and check it against the live tape.

WHAT THIS IS
------------
``scripts/bulk_history.py`` pulls the 11 cluster pools. This pulls **every pump.fun coin** for
a shorter window, so that a board event or an imitation swarm observed on the live boards and
firehose tapes can be joined to the full flow around it rather than only to our own pools.

Selection is by the vanity mint suffix::

    EXISTS(SELECT 1 FROM UNNEST(post_token_balances) b WHERE b.mint LIKE '%pump')

which is free: ``post_token_balances`` is already read for the reserves, so swapping the pool
filter for a mint-suffix filter scans **exactly** the same bytes — measured at a ratio of
1.000000 against the 11-pool query on four days spanning the window. The ``accounts``-column
route to the same universe would have cost ~+267 GB/day.

Two things about that filter, recorded rather than assumed:

* **Creates are captured.** A pump.fun bonding-curve initialisation writes the new mint into
  ``postTokenBalances`` (verified over RPC: 6 of 6 sampled creates, two legs each — the curve
  at ~998.2T raw and the dev buy). The ``pre != post`` change filter keeps them, because a
  create has no ``pre`` row for that mint and ``IFNULL(...,0)`` makes its first balance a
  change.
* **Recall is unverified.** The suffix is a *convention*, not a guarantee. The structurally
  exact filter — the pump.fun program id appearing in ``log_messages`` — is **unavailable for
  this window**: ``log_messages`` is empty on 2026-08-04 (0 of 83,100,020 suffix-matching
  transactions mention either program id). So a pre-convention pump.fun coin still trading
  would be missed, and the size of that population is not known. High precision, unmeasured
  recall.

WHY ONLY BALANCE-CHANGING TRANSACTIONS
--------------------------------------
83,100,020 transactions touched a pump-suffixed mint on 2026-08-04 alone. On the 11-pool tape
the same shape is 2.5% real fills, 31% reverts and 66% no-op reference rows, so requiring a
pump leg to have actually MOVED is a ~40x output reduction that costs nothing: the predicate
reads only columns the scan already pays for.

SCHEMA — READ THIS BEFORE WRITING A STUDY AGAINST IT
-----------------------------------------------------
One parquet file per UTC day under ``state/bulk_pump/daily/<YYYY-MM-DD>.parquet``. Read the
directory as a dataset and the ``day`` partition column comes along::

    import pyarrow.dataset as ds
    tape = ds.dataset("state/bulk_pump/daily", format="parquet")

======================== ============================================================
column                   note
======================== ============================================================
``signature``            base58, the join key against the live tapes
``block_slot``           int64
``block_time``           int64, **unix seconds** (not a timestamp column)
``tx_index``             int64, position within the block — orderable within a slot,
                         which ``getTransaction`` cannot give you
``fee_lamports``         **string**
``err``                  **string, and EMPTY STRING means success — never NULL.**
                         ``WHERE err IS NULL`` matches nothing, ever. Use ``err = ''``.
``compute_units``        **string**
``pre`` / ``post``       list<struct<owner, mint, amount, decimals, account_index>>,
                         ``amount`` a **string**
``schema_version``       ``bulk_pump.v1``
``provenance_*``         source, extraction time, sha256 of the exact query text
======================== ============================================================

**Every raw amount is a string.** Same rule as ``shitcoims_cluster.tape``: a 1e9-supply
6-decimal token is 1e15 raw units, already inside one order of magnitude of the 2**53 float
cliff. Cast to ``int``, never to ``float``.

**The arrays are narrowed to the OWNERS holding a pump mint, not to the pump mints.** That is
deliberate and load-bearing: it keeps the other side of the pool — the WSOL or USDC leg, whose
mint does not end in 'pump' — so a fill is reconstructible. ``verify`` is what proves it.

**Not replay grade for boosted PumpSwap pools.** Same limitation as ``bulk_history``: a boosted
pool prices against ``pool_quote + virtual_quote_reserves``, the virtual term lives in the swap
event in ``log_messages``, and that column is empty for this window. Vault levels here are
exact; the curve reserve for a boosted pool is not derivable from them. See
:mod:`shitcoims_cluster.pumpswap`.

THE EXPORT PATH, AND WHY IT IS NOT ``bq query``
-----------------------------------------------
``bulk_history.py`` streams results through ``bq query --format=json``, capped at 2M rows/day.
At this volume that cap fires immediately (correctly — it is the silent-truncation guard). So
this path uses ``EXPORT DATA`` to GCS in ZSTD parquet, which is free to run, parallel, and
needs no local JSONL intermediate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "state" / "bulk_pump"
LIVE_TAPE = REPO_ROOT / "state" / "cluster_tape" / "swaps"


def _pyarrow():
    try:
        import pyarrow  # noqa: F401
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit(
            "needs pyarrow: `uv sync --group research` (research group, so the live sentinel "
            "never depends on it)"
        ) from None
    return ds, pq


def repack(root: Path, *, force: bool = False) -> int:
    """Fold each day's thousands of export shards into one file.

    ``EXPORT DATA`` shards by worker: ~3,000 files of ~1 MB per day, 34,000 in total. That is
    fine in object storage and miserable on a laptop — every study would pay the per-file open
    cost, and a directory listing alone is slow. One file per UTC day keeps the day partition
    that matters and drops the one that is an artefact of BigQuery's parallelism.
    """

    ds, pq = _pyarrow()
    out_dir = root / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for day_dir in sorted((root / "raw").glob("day=*")):
        day = day_dir.name.split("=", 1)[1]
        target = out_dir / f"{day}.parquet"
        if target.exists() and not force:
            continue
        shards = sorted(day_dir.glob("*.parquet"))
        if not shards:
            continue
        # The EXPLICIT file list, not the directory. An interrupted `gcloud storage` transfer
        # leaves zero-byte `*.parquet_.gstmp` scratch files behind, and handing the directory
        # to a dataset makes the reader try to open them and die on the first one. Naming the
        # shards also means a half-downloaded sibling can never be silently folded in.
        dataset = ds.dataset([str(p) for p in shards], format="parquet")
        # STREAMED, not `to_table()`. A day is ~10.8M rows and ~3 GB compressed; materialising
        # one as a single Arrow table costs on the order of 20 GB of RAM and takes the laptop
        # down. Row groups go out as they come in, so peak memory is one batch.
        rows = 0
        temp = target.with_suffix(".parquet.partial")
        writer = None
        try:
            for batch in dataset.to_batches(batch_size=250_000):
                if batch.num_rows == 0:
                    continue
                if writer is None:
                    writer = pq.ParquetWriter(temp, batch.schema, compression="zstd",
                                              version="2.6")
                writer.write_batch(batch)
                rows += batch.num_rows
        finally:
            if writer is not None:
                writer.close()
        if writer is None:
            temp.unlink(missing_ok=True)
            continue
        temp.replace(target)
        written += 1
        print(f"  {day}: {len(shards):>5} shards -> {rows:>12,} rows, "
              f"{target.stat().st_size / 1e9:.2f} GB", file=sys.stderr)
    print(f"\nrepacked {written} day(s) into {out_dir}", file=sys.stderr)
    return 0


def summarise(root: Path) -> int:
    ds, _ = _pyarrow()
    total_rows = 0
    total_bytes = 0
    all_mints: set[str] = set()
    print(f"{'day':<12} {'rows':>13} {'GB':>7}  {'distinct pump mints':>20}")
    for path in sorted((root / "daily").glob("*.parquet")):
        dataset = ds.dataset(path, format="parquet")
        mints: set[str] = set()
        rows = 0
        # Streamed for the same reason repack is: a day does not fit in memory.
        for batch in dataset.to_batches(columns=["post"], batch_size=100_000):
            rows += batch.num_rows
            for legs in batch.column("post").to_pylist():
                for leg in legs or []:
                    mint = leg.get("mint") or ""
                    if mint.endswith("pump"):
                        mints.add(mint)
        size = path.stat().st_size
        total_rows += rows
        total_bytes += size
        all_mints |= mints
        print(f"{path.stem:<12} {rows:>13,} {size / 1e9:>7.2f}  {len(mints):>20,}")
    print(f"\n{'TOTAL':<12} {total_rows:>13,} {total_bytes / 1e9:>7.2f} GB"
          f"  {len(all_mints):>20,} distinct pump mints across the window")
    return 0


def verify(root: Path, *, sample_days: int = 2) -> int:
    """Check the overlap against the live cluster tape, the way bulk_history's verify does.

    The comparison is (pool, signature) -> the pool's own vault balances. The export narrows
    its ``pre``/``post`` arrays to the OWNERS that hold a pump mint, and a cluster pool is such
    an owner, so both of its vault legs — including the WSOL leg, whose mint does not end in
    'pump' — must be present. That is exactly why the narrowing is by owner and not by mint,
    and this check is what proves it.
    """

    ds, _ = _pyarrow()
    live: dict[tuple[str, str], dict[str, Any]] = {}
    live_days: Counter[str] = Counter()
    for path in sorted(LIVE_TAPE.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") != "swap":
                continue
            live[(str(row["pool"]), str(row["chain"]["signature"]))] = row
            live_days[str(row["t_event"])[:10]] += 1

    available = sorted(p.stem for p in (root / "daily").glob("*.parquet"))
    overlap = [d for d in available if live_days.get(d)]
    if not overlap:
        print("no day overlaps the live tape", file=sys.stderr)
        return 0
    chosen = overlap[-sample_days:]
    print(f"live tape days: {sorted(live_days)}")
    print(f"pump export days: {available[0]}..{available[-1]}")
    print(f"comparing on: {chosen}\n")

    exact = differ = missing = 0
    examples: list[str] = []
    absent_by_cell: dict[tuple[str, str], int] = defaultdict(int)
    for day in chosen:
        wanted = {sig for (_pool, sig), lrow in live.items()
                  if str(lrow["t_event"])[:10] == day}
        dataset = ds.dataset(root / "daily" / f"{day}.parquet", format="parquet")
        by_sig: dict[str, tuple[list, list]] = {}
        # Streamed, and only the handful of signatures the live tape can speak to are kept.
        # Materialising the day would be ~10.8M rows of nested structs to answer a question
        # about a few hundred.
        for batch in dataset.to_batches(columns=["signature", "pre", "post"], batch_size=100_000):
            sigs = batch.column("signature").to_pylist()
            if not any(s in wanted for s in sigs):
                continue
            pres = batch.column("pre").to_pylist()
            posts = batch.column("post").to_pylist()
            for sig, pre, post in zip(sigs, pres, posts, strict=True):
                if str(sig) in wanted:
                    by_sig[str(sig)] = (pre or [], post or [])

        for (pool, signature), lrow in live.items():
            if str(lrow["t_event"])[:10] != day:
                continue
            found = by_sig.get(signature)
            if found is None:
                missing += 1
                absent_by_cell[(day, str(lrow.get("label", "?")))] += 1
                continue
            pre_legs, post_legs = found
            want = {
                v["mint"]: (str(v["pre_raw"]), str(v["post_raw"]))
                for v in lrow["reserves"]["vaults"]
            }
            got_pre = {str(x["mint"]): str(x["amount"]) for x in pre_legs if x["owner"] == pool}
            got_post = {str(x["mint"]): str(x["amount"]) for x in post_legs if x["owner"] == pool}
            got = {
                mint: (got_pre.get(mint, "0"), got_post.get(mint, "0"))
                for mint in set(got_pre) | set(got_post)
            }
            if want == got:
                exact += 1
            else:
                differ += 1
                if len(examples) < 5:
                    examples.append(f"    {signature[:22]} {lrow.get('label')} "
                                    f"live={want} pump={got}")

    comparable = exact + differ + missing
    print(f"live cluster swaps inside the compared days : {comparable}")
    print(f"  exact pre+post vault match on both legs   : {exact}")
    print(f"  disagreed                                 : {differ}")
    print(f"  absent from the pump export               : {missing}")
    for line in examples:
        print(line)
    if comparable:
        print(f"  agreement                                 : {100 * exact / comparable:.1f}%")
    if absent_by_cell:
        print("\n  absent by (day, pool):")
        for (day, label), count in sorted(absent_by_cell.items(), key=lambda kv: -kv[1]):
            print(f"    {day}  {label:<20} {count:>6}")
    return 1 if differ else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("repack", help="fold the export shards into one file per UTC day")
    rp.add_argument("--force", action="store_true")
    sub.add_parser("summary", help="rows, bytes and distinct pump mints per day")
    vf = sub.add_parser("verify", help="compare the overlap against the live cluster tape")
    vf.add_argument("--sample-days", type=int, default=2)
    args = parser.parse_args(argv)
    if args.cmd == "repack":
        return repack(args.root, force=args.force)
    if args.cmd == "summary":
        return summarise(args.root)
    return verify(args.root, sample_days=args.sample_days)


if __name__ == "__main__":
    raise SystemExit(main())
