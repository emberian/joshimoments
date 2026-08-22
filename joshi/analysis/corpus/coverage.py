"""Minute-level coverage census: where are the holes?"""
import sys

sys.path.insert(0,"/private/tmp/claude-501/-Users-you-dev-joshi/5f1f382e-9398-4b86-86af-a0ea9e8275df/scratchpad/corpus/scripts")
from ddb import DAILY, SP, connect

con = connect(memory_gb=24, threads=8)
con.execute(f"""
CREATE OR REPLACE TABLE minutes AS
SELECT (block_time // 60) * 60 AS minute,
       count(*) AS n_tx,
       count(DISTINCT block_slot) AS n_slots,
       min(block_slot) AS min_slot, max(block_slot) AS max_slot
FROM read_parquet('{DAILY}/*.parquet')
GROUP BY 1
""")
n = con.execute("SELECT count(*), min(minute), max(minute) FROM minutes").fetchone()
print("minutes present:", n)
span = (n[2]-n[1])//60 + 1
print("minutes in span:", span, "absent minutes:", span - n[0])
# absent minutes
absent = con.execute(f"""
WITH grid AS (SELECT {n[1]} + 60*g AS minute FROM range(0,{span}) t(g))
SELECT g.minute FROM grid g LEFT JOIN minutes m USING(minute) WHERE m.minute IS NULL
ORDER BY 1
""").fetchall()
print("absent minute count:", len(absent))
# collapse into runs
runs=[]
for (mm,) in absent:
    if runs and mm == runs[-1][1] + 60: runs[-1][1] = mm
    else: runs.append([mm, mm])
import datetime as dt


def iso(t): return dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d %H:%M")
print("\nFULLY ABSENT MINUTE RUNS (no transaction at all):")
for a,b in runs:
    print(f"  {iso(a)} .. {iso(b+59)} UTC   ({(b-a)//60+1} min)")
# low-count minutes (relative to global median)
med = con.execute("SELECT median(n_tx) FROM minutes").fetchone()[0]
print(f"\nmedian tx/minute over window: {med:,.0f}")
low = con.execute(f"SELECT minute, n_tx, n_slots FROM minutes WHERE n_tx < {med}*0.25 ORDER BY minute").fetchall()
print(f"minutes with < 25% of median tx: {len(low)}")
runs2=[]
for mm, ntx, ns in low:
    if runs2 and mm == runs2[-1][1] + 60: runs2[-1][1]=mm; runs2[-1][2]+=ntx
    else: runs2.append([mm,mm,ntx])
for a,b,s in runs2:
    print(f"  {iso(a)} .. {iso(b+59)} UTC  ({(b-a)//60+1} min, {s:,} tx total)")
con.execute(f"COPY minutes TO '{SP}/out/minutes.parquet' (FORMAT PARQUET)")
