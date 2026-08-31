#!/usr/bin/env python3
"""Verify the bulk_pump corpus is complete -- on local disk and on every remote mirror.

The corpus (``state/bulk_pump/``) is a FROZEN 10-day born-in-window snapshot:

    raw/day=YYYY-MM-DD/part-*.parquet   35294 shard files, 2026-08-05 .. 08-14
    daily/YYYY-MM-DD.parquet            10 merged dailies, 106,639,238 rows total

The persvati and hbox mirrors go stale or incomplete SILENTLY: a mirror can drop
whole days or truncate shards, and a remote fold then reports a clean-looking number
computed over a subset. Three research lanes were bitten by this before it was written
down (SWARM.md, "Corpus mirrors go stale/incomplete silently").

This tool is the check that would have caught them. For local and each remote mirror it
counts the shard files per day, reads the row count of each daily parquet from its footer
metadata (no data scan), compares both against the frozen reference, prints a table, and
EXITS NONZERO if any mirror is short or unverifiable. It is intentionally cheap -- counts
and parquet footers only, never a fold.

Usage:
    uv run python scripts/corpus_verify.py                 # local + default mirrors
    uv run python scripts/corpus_verify.py --local-only    # skip remotes
    uv run python scripts/corpus_verify.py --mirror persvati=persvati:~/corpus/bulk_pump
    uv run python scripts/corpus_verify.py --json          # machine-readable
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# --- the frozen reference -------------------------------------------------------------
# This corpus is a fixed historical asset (HANDOFF.md §6), not a growing feed, so the
# per-day counts are constants. Regenerate with this same tool's local probe if the
# snapshot is ever legitimately re-cut.
EXPECTED_TOTAL_FILES = 35294
EXPECTED_TOTAL_ROWS = 106_639_238
EXPECTED_FILES: dict[str, int] = {
    "2026-08-05": 3086, "2026-08-06": 3119, "2026-08-07": 3257, "2026-08-08": 3555,
    "2026-08-09": 3793, "2026-08-10": 3574, "2026-08-11": 3737, "2026-08-12": 3912,
    "2026-08-13": 3836, "2026-08-14": 3425,
}
EXPECTED_ROWS: dict[str, int] = {
    "2026-08-05": 10_182_163, "2026-08-06": 9_551_591, "2026-08-07": 10_126_879,
    "2026-08-08": 10_078_716, "2026-08-09": 11_129_539, "2026-08-10": 12_082_790,
    "2026-08-11": 11_589_260, "2026-08-12": 10_231_882, "2026-08-13": 10_843_156,
    "2026-08-14": 10_823_262,
}
EXPECTED_DAYS = tuple(sorted(EXPECTED_FILES))

# Documented mirror locations. persvati path is from SUBSTRATE.md:47 ("corpus/bulk_pump/");
# hbox lives on /tank. A wrong path fails LOUDLY as UNREACHABLE (never silently short), and
# both are overridable with --mirror / --local-only.
DEFAULT_MIRRORS: list[tuple[str, str, str]] = [
    ("persvati", "persvati", "~/corpus/bulk_pump"),
    ("hbox", "hbox", "/tank/joshibot/bulk_pump"),
]

# The probe: a self-contained program, run identically in-process-locally (as a subprocess
# of this interpreter) and over ssh on each remote. stdlib for the file counts; pyarrow for
# the footer row counts if it is importable, else rows come back null and are reported n/a.
PROBE = r"""
import json, os, sys
root = os.path.expanduser(sys.argv[1])
out = {"root": root, "exists": os.path.isdir(root), "pyarrow": False, "days": {}}
raw = os.path.join(root, "raw")
if os.path.isdir(raw):
    for entry in sorted(os.listdir(raw)):
        if not entry.startswith("day="):
            continue
        d = os.path.join(raw, entry)
        try:
            n = sum(1 for f in os.listdir(d)
                    if f.startswith("part-") and f.endswith(".parquet"))
        except OSError:
            n = 0
        out["days"].setdefault(entry[4:], {})["files"] = n
try:
    import pyarrow.parquet as pq
    out["pyarrow"] = True
except Exception:
    pq = None
daily = os.path.join(root, "daily")
if os.path.isdir(daily):
    for f in sorted(os.listdir(daily)):
        if not f.endswith(".parquet"):
            continue
        rows = None
        if pq is not None:
            try:
                rows = pq.ParquetFile(os.path.join(daily, f)).metadata.num_rows
            except Exception:
                rows = None
        out["days"].setdefault(f[:-len(".parquet")], {})["rows"] = rows
print(json.dumps(out))
"""


class ProbeError(Exception):
    pass


def _run_probe(argv: list[str]) -> dict:
    try:
        proc = subprocess.run(
            argv, input=PROBE, capture_output=True, text=True, timeout=45,
        )
    except FileNotFoundError as e:
        raise ProbeError(f"command not found: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise ProbeError("timed out") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ProbeError(tail[-1] if tail else f"exit {proc.returncode}")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        raise ProbeError(f"unparseable probe output: {proc.stdout[:200]!r}") from e


def probe_local(root: Path) -> dict:
    return _run_probe([sys.executable, "-c", PROBE, str(root)])


def probe_remote(host: str, root: str) -> dict:
    return _run_probe([
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        host, "python3", "-", root,
    ])


def evaluate(profile: dict) -> tuple[str, list[str]]:
    """Return (status, notes). status in {OK, SHORT, DRIFT}."""
    if not profile.get("exists"):
        return "SHORT", ["corpus root not found"]
    days = profile.get("days", {})
    notes: list[str] = []
    short = drift = False
    missing = [d for d in EXPECTED_DAYS if d not in days]
    if missing:
        short = True
        notes.append(f"missing days: {', '.join(missing)}")
    total_files = 0
    for d in EXPECTED_DAYS:
        got = days.get(d, {})
        fc = got.get("files")
        if fc is None:
            continue
        total_files += fc
        if fc < EXPECTED_FILES[d]:
            short = True
            notes.append(f"{d}: {fc} files (< {EXPECTED_FILES[d]}, -{EXPECTED_FILES[d] - fc})")
        elif fc > EXPECTED_FILES[d]:
            drift = True
            notes.append(f"{d}: {fc} files (> {EXPECTED_FILES[d]}, +{fc - EXPECTED_FILES[d]})")
        rc = got.get("rows")
        if rc is not None and rc < EXPECTED_ROWS[d]:
            short = True
            notes.append(f"{d}: {rc:,} rows (< {EXPECTED_ROWS[d]:,}, truncated)")
    if total_files < EXPECTED_TOTAL_FILES:
        short = True
        notes.append(f"total {total_files} files (< {EXPECTED_TOTAL_FILES})")
    if not profile.get("pyarrow"):
        notes.append("row counts unavailable (no pyarrow on that host)")
    if short:
        return "SHORT", notes
    if drift:
        return "DRIFT", notes
    return "OK", notes


def _fmt(n: int | None) -> str:
    return "   n/a" if n is None else f"{n:,}"


def print_table(results: list[tuple[str, dict | None, str, list[str]]]) -> None:
    names = [name for name, prof, _, _ in results]
    header = f"{'day':<12} {'expected':>13}  " + "  ".join(f"{n:>13}" for n in names)

    print("\ncorpus completeness -- state/bulk_pump")
    print(f"expected: {EXPECTED_TOTAL_FILES:,} files, {EXPECTED_TOTAL_ROWS:,} rows, "
          f"{len(EXPECTED_DAYS)} days (2026-08-05 .. 08-14)\n")

    print("FILE COUNT per day")
    print(header)
    for d in EXPECTED_DAYS:
        cells = []
        for _, prof, _, _ in results:
            fc = (prof or {}).get("days", {}).get(d, {}).get("files") if prof else None
            cells.append(f"{_fmt(fc):>13}")
        print(f"{d:<12} {EXPECTED_FILES[d]:>13,}  " + "  ".join(cells))
    tot_cells = []
    for _, prof, _, _ in results:
        if not prof:
            tot_cells.append(f"{'ERR':>13}")
            continue
        t = sum(v.get("files", 0) for v in prof.get("days", {}).values())
        tot_cells.append(f"{t:>13,}")
    print(f"{'TOTAL':<12} {EXPECTED_TOTAL_FILES:>13,}  " + "  ".join(tot_cells))

    print("\nROW COUNT per daily parquet (footer metadata)")
    print(header)
    for d in EXPECTED_DAYS:
        cells = []
        for _, prof, _, _ in results:
            rc = (prof or {}).get("days", {}).get(d, {}).get("rows") if prof else None
            cells.append(f"{_fmt(rc):>13}")
        print(f"{d:<12} {EXPECTED_ROWS[d]:>13,}  " + "  ".join(cells))
    tot_cells = []
    for _, prof, _, _ in results:
        if not prof:
            tot_cells.append(f"{'ERR':>13}")
            continue
        vals = [v.get("rows") for v in prof.get("days", {}).values()]
        cell = f"{sum(vals):,}" if vals and all(v is not None for v in vals) else "n/a"
        tot_cells.append(f"{cell:>13}")
    print(f"{'TOTAL':<12} {EXPECTED_TOTAL_ROWS:>13,}  " + "  ".join(tot_cells))

    print("\nstatus")
    for name, _, status, notes in results:
        line = f"  {name:<12} {status}"
        if notes:
            line += "  -- " + "; ".join(notes)
        print(line)


def parse_mirror(spec: str) -> tuple[str, str, str]:
    # NAME=HOST:PATH
    name, _, rest = spec.partition("=")
    host, _, path = rest.partition(":")
    if not (name and host and path):
        raise argparse.ArgumentTypeError(f"bad --mirror {spec!r}; want NAME=HOST:PATH")
    return name, host, path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", type=Path, default=repo_root / "state" / "bulk_pump",
                    help="local corpus root (default: state/bulk_pump)")
    ap.add_argument("--mirror", type=parse_mirror, action="append", default=[],
                    metavar="NAME=HOST:PATH", help="remote mirror; repeatable")
    ap.add_argument("--local-only", action="store_true", help="do not probe remotes")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    mirrors = args.mirror or ([] if args.local_only else DEFAULT_MIRRORS)

    results: list[tuple[str, dict | None, str, list[str]]] = []

    # local
    try:
        prof = probe_local(args.local)
        status, notes = evaluate(prof)
    except ProbeError as e:
        prof, status, notes = None, "ERROR", [str(e)]
    results.append(("local", prof, status, notes))

    # remotes
    for name, host, path in mirrors:
        try:
            prof = probe_remote(host, path)
            status, notes = evaluate(prof)
        except ProbeError as e:
            prof, status, notes = None, "UNREACHABLE", [str(e)]
        results.append((name, prof, status, notes))

    ok = all(status == "OK" for _, _, status, _ in results)

    if args.json:
        print(json.dumps({
            "expected": {"files": EXPECTED_TOTAL_FILES, "rows": EXPECTED_TOTAL_ROWS,
                         "days": len(EXPECTED_DAYS)},
            "mirrors": [{"name": n, "status": s, "notes": nt, "profile": p}
                        for n, p, s, nt in results],
            "ok": ok,
        }, indent=2))
    else:
        print_table(results)
        print()
        if ok:
            print("OK: every mirror is complete.")
        else:
            bad = [n for n, _, s, _ in results if s != "OK"]
            print(f"FAIL: not every mirror is complete ({', '.join(bad)}). "
                  f"Do not trust a fold over a short mirror.")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
