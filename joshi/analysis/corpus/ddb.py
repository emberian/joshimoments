"""Shared DuckDB connection settings for the bulk_pump characterization."""
import os

import duckdb

SP = "/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus"
DAILY = "~/dev/joshibot/state/bulk_pump/daily"
RAW = "~/dev/joshibot/state/bulk_pump/raw"
WSOL = "So11111111111111111111111111111111111111112"

def connect(memory_gb: int = 32, threads: int = 8):
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_gb}GB'")
    con.execute(f"SET threads={threads}")
    con.execute(f"SET temp_directory='{SP}/tmp'")
    con.execute("SET preserve_insertion_order=false")
    return con

def days():
    return sorted(
        f[:-len(".parquet")] for f in os.listdir(DAILY) if f.endswith(".parquet")
    )
