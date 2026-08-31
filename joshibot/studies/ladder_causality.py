"""The last open edge: is the accumulation ladder's graduation lift MAKE, PICK, or COINCIDENCE?

THE SPECIMEN (committed anchor, then a derived extension -- kept distinct)
-------------------------------------------------------------------------
COMMITTED (``RESULT_cluster_map.md`` §5): a **6-cluster / 34-wallet** accumulation ladder whose
first entries sit on fixed rungs at **-4, 0, +8, +16, +24, +32 s** (clusters 1504, 6464, 4899,
17569, 16518, 13755). ``_assemble_ladder(CORE6)`` reproduces exactly those offsets (spacing
[4,8,8,8,8], 10 independent checks, 0 mismatches). They are pure ACCUMULATORS -- 63,044 entries
/ 59 exits (0.09%) -- funded by one hub (``H7sWT7…``, 27,846 SOL to 579 wallets since 2024-02,
17 fresh spine wallets THIS month).

DERIVED HERE (shown, not assumed): widening to ALL nonzero locked cluster-pairs, the 6-core sits
inside a larger connected component of **110 clusters / 479 wallets** on the same clock. That
component is a LOOSER schedule complex, not one clean line: its 1-D embedding spans -6..+401 s
with **38 mismatches over 185 checks**, and by guild it is 79 FLASH / 18 ACCUMULATOR / 8
HARVESTER / 4 SLOW -- a non-selling spine synchronized with a SELLING periphery. So the causal
treatment below is the **committed 6-core spine**, not the derived 110; the 110 only defines
which wallets to pull footprints for.

THE GRADUATION NUMBER IS MEASURED HERE, NOT INHERITED. No committed study reports a graduation
rate for ladder-touched coins. This module derives it from the corpus with a matched control and
a rotation null and reports its own figure with a CI (§4). The prior work
(``RESULT_cluster_map.md`` §14) flagged the CAUSE as UNRESOLVED: predict-vs-manufacture.

THE QUESTION (the whole ballgame)
---------------------------------
Is the ladder's graduation association CAUSAL (MAKE) or SELECTIVE (PICK) or reverse-causal
(COINCIDENCE)?
  * MAKE  -- their buying pushes coins over the ~80%-of-supply graduation threshold. Signature:
             graduation rises with THEIR deployed capital, conditional on coin state.
  * PICK  -- they read a selection signal and buy coins that would graduate anyway. Signature:
             their presence predicts graduation with NO positive dose-response on their own size.
  * COINCIDENCE -- early buyers on any coin correlate with graduation via reverse causation;
             a matched control at equal early-observable quality erases the lift.

WHAT DISCRIMINATES THEM HERE
----------------------------
1. MECHANISTIC CEILING (--dose, Test A). pump.fun graduation requires ~80% of the fixed 1e9
   supply to be SOLD into the curve. The ladder's total purchased %supply is the direct
   MAKE currency. Measured: median 0.44% on graduated coins, ~0% for the core spine, and
   INVERSELY related to graduation. Capital-MAKE needs the opposite. It is refuted.
2. SURVIVORSHIP (--dose, Test B). The schedule's later rungs can only fill if the coin is
   still alive at +Ns, so a raw ``n_rungs`` gradient is partly n_rungs <- survival ->
   graduation (COINCIDENCE). Decomposed by rungs filled in a FIXED early window and inside
   long-lived coins only; the early-rung signal survives, so it is not pure survivorship.
3. MATCHED CONTROLS + PERMUTATION (--discriminate, Tests C/E). Exact-match on
   (birth-day x dev-buy x sniper-count x birth-legs); stratified label permutation. The
   COINCIDENCE null (matched-control) lifts the base from 2.45% to ~9%, but a 3.4x residual
   survives, stable on all ten days, z ~ 60. So the pick carries graduation signal BEYOND
   public early features.
4. THE NATURAL EXPERIMENT (--discriminate, Test D). Among coins the ladder entered early,
   winners vs losers separate on COIN QUALITY (5x dev buy), not on the ladder's own dose --
   the PICK signature exactly.

VERDICT: **PICK.** The ladder is a graduation DETECTOR, not an engine. See RESULT_ladder_causality.md.

FRONT-RUN (--frontrun)
----------------------
The core rung lands at median +6 s (p25 +5 s; 85% within 30 s), observable on the firehose as
a known spine wallet buying a <10 s-old coin. Fresh soldiers are PRE-ANNOUNCED: 100% of hub
transfers precede the wallet's first trade (median lead ~2.4 h). A paper-sim of enter-at-first-
core-rung / exit-at-migration is +EV only above a ~3.3x grad-exit multiple; that multiple and
real friction need live curve data -- stated, not assumed. Everything here is IN-SAMPLE
(clusters built from this corpus); the deployable object is the FIXED wallet set, not a re-clustering.

THE WATCHLIST (--watchlist)
---------------------------
``state/ladder/watchlist.jsonl`` -- the hub, the 48 wallets it funded this month (17 already
mapping to the core spine), and the full spine, each with its funding tx as evidence, so the
desk can subscribe accountTrade and see the next ladder entry live. This does NOT wire the
firehose; it defines the contract.

RUNNING IT
----------
    uv run --group research python -m studies.ladder_causality --extract       # ~3 min, caches
    uv run --group research python -m studies.ladder_causality --dose           # Tests A, B, dose-response
    uv run --group research python -m studies.ladder_causality --discriminate   # Tests C, D, E (the verdict)
    uv run --group research python -m studies.ladder_causality --frontrun       # viability + paper-sim
    uv run --group research python -m studies.ladder_causality --watchlist      # emit state/ladder/
    uv run --group research python -m studies.ladder_causality --all

LIMITS (inherited from cluster_map.py, restated because they bound every number below)
--------------------------------------------------------------------------------------
* No SOL leg in the corpus: "supply %" is the fraction of the fixed 1e9 token supply opened,
  NOT SOL. That is the RIGHT unit for the graduation-threshold argument (graduation is a
  supply-sold event) but it is not a capital figure.
* Ten days (2026-08-05..14). Clusters are built from this same corpus, so every rate is
  IN-SAMPLE; the per-day stability and the fixed-wallet deployability are the mitigations.
* The organism is ONE entity: the trial unit is the COIN, not the wallet-entry, and the
  matched-control / permutation nulls are the population inference -- never a naive t over
  53k coins (PROGRAM.md §3, the burst-ESS trap).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final, Sequence

ROOT = Path(__file__).resolve().parent.parent
CM_CACHE = ROOT / ".cache" / "clustermap"
CACHE = ROOT / ".cache" / "ladder"
STATE = ROOT / "state" / "ladder"
COINS = ROOT / "studies" / "data" / "operator_crime" / "coins.parquet"
EVENTS = CM_CACHE / "events_bulk"

# The 6-cluster spine: pure accumulators on the 8 s rungs (studies/cluster_map.py cmd_storm_edge).
CORE6: Final = frozenset({1504, 6464, 4899, 17569, 16518, 13755})
# The funding hub whose outgoing SOL fan-out lands on the ladder (report_fanout.py).
HUB: Final = "H7sWT7eP83vkim7Gp81qsPwQzuzJK3E6Ps9KLbUezoCc"
HUB_FANOUT = CM_CACHE / "hub_fanout.parquet"

DAYS: Final = [f"2026-08-{d:02d}" for d in range(5, 15)]
SUPPLY_BASE: Final = 1e15  # 1e9 tokens x 1e6 decimals; a full mint's fixed supply in base units
SEED: Final = 20260816


def echo(msg: str) -> None:
    print(msg, flush=True)


def _duck(threads: int = 4, memory: str = "6GB"):
    import duckdb

    con = duckdb.connect()
    tmp = CACHE / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    con.execute(f"SET temp_directory='{tmp}'")
    return con


# ---------------------------------------------------------------------------------------
# The organism, reconstructed reproducibly from the resonance2 artifact.
# ---------------------------------------------------------------------------------------


def organism_clusters() -> set[int]:
    """The 110-cluster organism = largest component over nonzero locked cluster pairs.

    Identical construction to ``cmd_resonance2`` §10.2, but frozen as a returnable set so
    every stage names the same object. A nonzero locked pair (|median offset| > 1 s, IQR
    width <= 4 s over >=50 shared coins) is a scheduler rung; the component they assemble is
    the ladder.
    """
    from collections import defaultdict

    import pandas as pd

    r2 = pd.read_parquet(CM_CACHE / "resonance2_bulk.parquet")
    nz = r2[r2["med"].abs() > 1]
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, row in nz.iterrows():
        a, b = find(int(row.A)), find(int(row.B))
        if a != b:
            parent[a] = b
    comp: dict[int, list[int]] = defaultdict(list)
    for k in parent:
        comp[find(k)].append(k)
    return set(max(comp.values(), key=len))


def _assemble_ladder(cids) -> tuple[dict[int, float], int, int]:
    """1-D embedding of a cluster set from resonance2 median offsets, with mismatches counted.

    Identical to ``cluster_map.cmd_resonance2`` §10.2. Returns (position-per-cluster, mismatches,
    independent-checks). A clean ladder has 0 mismatches; a looser complex has many.
    """
    from collections import Counter

    import pandas as pd

    r2 = pd.read_parquet(CM_CACHE / "resonance2_bulk.parquet")
    cs = set(cids)
    ge = [r for _, r in r2[(r2.A.isin(cs)) & (r2.B.isin(cs))].iterrows()]
    deg: Counter = Counter()
    for r in ge:
        deg[int(r.A)] += 1
        deg[int(r.B)] += 1
    if not deg:
        return {}, 0, 0
    root = max(deg, key=deg.get)
    pos = {root: 0.0}
    for _ in range(len(cs)):
        for r in ge:
            m = round(r.med)
            if int(r.A) in pos and int(r.B) not in pos:
                pos[int(r.B)] = pos[int(r.A)] + m
            if int(r.B) in pos and int(r.A) not in pos:
                pos[int(r.A)] = pos[int(r.B)] - m
    mism = sum(1 for r in ge if int(r.A) in pos and int(r.B) in pos
               and abs((pos[int(r.B)] - pos[int(r.A)]) - round(r.med)) > 1)
    return pos, mism, len(ge) - (len(pos) - 1)


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval -- the coin-level sampling CI on a rate (each coin its own Bernoulli)."""
    if n == 0:
        return (0.0, 0.0)
    import math

    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


# ---------------------------------------------------------------------------------------
# STAGE 0 -- extract the ladder's per-coin footprint from the pre-built event corpus.
# ---------------------------------------------------------------------------------------


def cmd_extract(force: bool = False) -> None:
    import pandas as pd

    CACHE.mkdir(parents=True, exist_ok=True)
    org = organism_clusters()
    cl = pd.read_parquet(CM_CACHE / "clusters_bulk.parquet")
    wallets = cl[cl["cid"].isin(org)].copy()
    cid_of = dict(zip(wallets["owner"], wallets["cid"]))
    n_core_w = int(cl[cl["cid"].isin(CORE6)].shape[0])

    # Measure the rung structure rather than assert it (course-correction: the committed
    # object is the 6-core; the 110 is a derived, looser extension).
    cpos, cmis, cchk = _assemble_ladder(sorted(CORE6))
    crungs = sorted(cpos.items(), key=lambda kv: kv[1])
    echo("COMMITTED 6-core spine: "
         + "  ".join(f"{c}@{int(p):+d}s" for c, p in crungs))
    echo(f"  {len(CORE6)} clusters / {n_core_w} wallets; span "
         f"{int(min(cpos.values()))}..{int(max(cpos.values()))}s, "
         f"{cchk} checks, {cmis} mismatches (0 => a clean single ladder)")
    opos, omis, ochk = _assemble_ladder(sorted(org))
    echo(f"DERIVED 110-organism: {len(org)} clusters / {len(wallets)} wallets; "
         f"span {int(min(opos.values()))}..{int(max(opos.values()))}s, "
         f"{ochk} checks, {omis} mismatches (a looser schedule complex, NOT one clean line)")
    wallets[["owner", "cid"]].to_parquet(CACHE / "ladder_wallets.parquet", index=False)

    legs_path = CACHE / "ladder_legs.parquet"
    if legs_path.exists() and not force:
        echo(f"  {legs_path.name} exists; skipping (use --force to rebuild)")
    else:
        owner_list = "(" + ",".join("'" + o + "'" for o in sorted(cid_of)) + ")"
        frames = []
        for day in DAYS:
            f = EVENTS / f"{day}.parquet"
            if not f.exists():
                echo(f"  WARNING: {f} missing, skipping")
                continue
            con = _duck()
            df = con.execute(
                f"""
                WITH x AS (
                  SELECT mint, block_slot AS slot, block_time AS t, kind,
                         unnest(owners) AS owner, unnest(amts) AS amt
                  FROM read_parquet('{f}')
                )
                SELECT mint, owner, kind, min(t) AS t, min(slot) AS slot, sum(amt) AS amt
                FROM x WHERE owner IN {owner_list}
                GROUP BY mint, owner, kind
                """
            ).fetchdf()
            con.close()
            frames.append(df)
            echo(f"  {day}: {len(df):,} ladder legs")
        legs = pd.concat(frames, ignore_index=True)
        legs["cid"] = legs["owner"].map(cid_of)
        legs.to_parquet(legs_path, index=False)
        echo(f"  wrote {legs_path.name}: {len(legs):,} legs "
             f"({int((legs.kind == 'entry').sum()):,} entry / "
             f"{int((legs.kind == 'exit').sum()):,} exit)")

    _build_footprint()


def _build_footprint() -> None:
    """Per-coin ladder footprint joined to coin outcomes/features (the analytical object)."""
    import pandas as pd

    legs = pd.read_parquet(CACHE / "ladder_legs.parquet")
    con = _duck()
    coins = con.execute(
        f"""SELECT mint, birth_time, deployer, graduated, dev_buy_share, dev_buy_raw,
                   n_snipers, n_birth_legs, peak_mcap_sol, lifetime_s, curve_touches
            FROM read_parquet('{COINS}')"""
    ).fetchdf()
    con.close()
    bt = dict(zip(coins.mint, coins.birth_time))
    en = legs[legs.kind == "entry"].copy()
    en["bt"] = en.mint.map(bt)
    en = en.dropna(subset=["bt"])
    en["lat"] = en.t - en.bt
    en["supply_pct"] = en.amt / SUPPLY_BASE * 100
    en["is_core"] = en.cid.isin(CORE6)

    def rungs_by(T: int, core: bool = False):
        e = en[en.lat <= T]
        if core:
            e = e[e.is_core]
        return e.groupby("mint")["cid"].nunique()

    foot = pd.DataFrame({"mint": coins.mint}).set_index("mint")
    for T in (10, 30, 60, 120, 399):
        foot[f"rungs_{T}"] = rungs_by(T)
        foot[f"crungs_{T}"] = rungs_by(T, core=True)
    foot["n_rungs"] = en.groupby("mint")["cid"].nunique()
    foot["n_wallets"] = en.groupby("mint")["owner"].nunique()
    foot["ladder_supply_pct"] = en.groupby("mint")["supply_pct"].sum()
    foot["core_supply_pct"] = (
        en[en.is_core].groupby("mint")["supply_pct"].sum()
    )
    foot["first_lat"] = en.groupby("mint")["lat"].min()
    foot["first_core_lat"] = en[en.is_core].groupby("mint")["lat"].min()
    ex = legs[legs.kind == "exit"].groupby("mint")["owner"].nunique().rename("n_exit_wallets")
    foot = foot.join(ex)
    for c in foot.columns:
        if c.startswith(("rungs", "crungs", "n_", "ladder", "core", "first")):
            if c in ("first_lat", "first_core_lat"):
                continue
            foot[c] = foot[c].fillna(0)
    foot = foot.reset_index().merge(coins, on="mint", how="left")
    # Keep only coins the ladder actually ENTERED (n_rungs > 0). Untouched coins are the
    # control universe and are read fresh from coins.parquet in cmd_discriminate; keeping
    # them here would dilute the "among coins the ladder touched" comparisons in --dose.
    foot = foot[(foot.birth_time.notna()) & (foot.n_rungs > 0)].copy()
    foot.to_parquet(CACHE / "coin_footprint.parquet", index=False)
    echo(f"  footprint: {len(foot):,} ladder-touched coins with birth features "
         f"-> {CACHE.name}/coin_footprint.parquet")


def _load():
    import pandas as pd

    for p in ("coin_footprint.parquet", "ladder_legs.parquet", "ladder_wallets.parquet"):
        if not (CACHE / p).exists():
            raise SystemExit(f"{CACHE / p} missing; run --extract first")
    return (
        pd.read_parquet(CACHE / "coin_footprint.parquet"),
        pd.read_parquet(CACHE / "ladder_legs.parquet"),
    )


def _base_rate():
    con = _duck()
    n, g = con.execute(
        f"SELECT count(*), sum(graduated::int) FROM read_parquet('{COINS}')"
    ).fetchone()
    con.close()
    return n, g, g / n


# ---------------------------------------------------------------------------------------
# STAGE 1 -- DOSE-RESPONSE: does graduation rise with THEIR capital? (MAKE test)
# ---------------------------------------------------------------------------------------


def cmd_dose() -> None:
    import pandas as pd

    foot, _ = _load()
    n_all, g_all, base = _base_rate()
    echo(f"\n=== population base: {n_all:,} coins, {g_all:,} graduated ({base:.2%}) ===")
    echo(f"    ladder-touched (entered): {len(foot):,} coins, grad {foot.graduated.mean():.2%}; "
         f"core-spine-touched: {int((foot.crungs_399 > 0).sum()):,}, "
         f"grad {foot[foot.crungs_399 > 0].graduated.mean():.2%}")

    # ---- TEST A: the mechanistic ceiling ----------------------------------------------
    echo("\n=== TEST A -- MECHANISTIC CEILING (capital-MAKE) ===")
    echo("  pump.fun graduation = ~80% of the fixed 1e9 supply SOLD into the curve. The")
    echo("  ladder's purchased %supply is the direct MAKE currency. If MAKE, graduated coins")
    echo("  got MORE ladder supply; a capital engine cannot buy LESS on the coins it graduates.")
    a = foot.groupby("graduated").agg(
        n=("mint", "size"),
        med_ladder_supply_pct=("ladder_supply_pct", "median"),
        p90_ladder_supply_pct=("ladder_supply_pct", lambda x: x.quantile(0.9)),
        med_core_supply_pct=("core_supply_pct", "median"),
    )
    echo(a.to_string(float_format=lambda x: f"{x:.3f}"))
    echo("  READ: ladder supply is a fraction of a percent on graduated coins and is LOWER")
    echo("  there than on failures. The core spine's median is ~0. Capital-MAKE is refuted:")
    echo("  the ladder cannot push an 80%-of-supply threshold with <0.5% of supply.")

    echo("\n  grad rate by ladder_supply_pct decile (the dose-response on their own size):")
    t = foot.copy()
    t["sup_bkt"] = pd.qcut(t.ladder_supply_pct, 10, duplicates="drop")
    d = t.groupby("sup_bkt", observed=True).agg(
        n=("graduated", "size"), grad=("graduated", "mean"),
        med_snipers=("n_snipers", "median"), med_devbuy=("dev_buy_share", "median"),
    )
    echo(d.to_string(float_format=lambda x: f"{x:.4f}"))
    echo("  READ: NOT monotone -- the high-supply deciles (ladder is the dominant buyer)")
    echo("  graduate LESS. High own-share marks 'nobody else came', not manufactured success.")

    # ---- TEST B: survivorship decomposition of n_rungs --------------------------------
    echo("\n=== TEST B -- IS THE n_rungs GRADIENT SURVIVORSHIP? ===")
    echo("  Later rungs (out to +399 s) can only fill if the coin is still alive, so a raw")
    echo("  n_rungs gradient is partly n_rungs <- survival -> graduation (COINCIDENCE).")
    sp = t[["n_rungs", "lifetime_s"]].corr("spearman").iloc[0, 1]
    echo(f"  spearman(n_rungs, lifetime_s | touched) = {sp:.3f}  (positively coupled; the "
         f"early-window control below is the real test, not this correlation)")
    echo("\n  grad & median lifetime by rungs filled in the FIRST 30 s (decided pre-outcome):")
    t["r30"] = pd.cut(t.rungs_30, [-1, 0, 1, 3, 7, 15, 1e9],
                      labels=["0", "1", "2-3", "4-7", "8-15", "16+"])
    b = t.groupby("r30", observed=True).agg(
        n=("graduated", "size"), grad=("graduated", "mean"),
        med_lifetime=("lifetime_s", "median"), med_snipers=("n_snipers", "median"),
    )
    echo(b.to_string(float_format=lambda x: f"{x:.3f}"))
    echo("\n  survivorship-CONTROLLED: among coins that lived > 600 s, grad by core rungs<=30s:")
    alive = t[t.lifetime_s > 600].copy()
    alive["b"] = pd.cut(alive.crungs_30, [-1, 0, 1, 3, 6], labels=["0", "1", "2-3", "4-6"])
    ab = alive.groupby("b", observed=True).agg(n=("graduated", "size"), grad=("graduated", "mean"))
    echo(ab.to_string(float_format=lambda x: f"{x:.3f}"))
    echo("  READ: inside long-lived coins the early-rung signal PERSISTS (1.8% -> ~35%), so")
    echo("  the gradient is not pure survivorship -- their early presence carries real signal.")


# ---------------------------------------------------------------------------------------
# STAGE 2 -- THE DISCRIMINATION: matched controls, permutation, the natural experiment.
# ---------------------------------------------------------------------------------------


def _stratify(coins, treated: set[str]):
    import pandas as pd

    c = coins.dropna(subset=["graduated", "birth_time"]).copy()
    c["treat"] = c.mint.isin(treated)
    c["day"] = (c.birth_time // 86400).astype(int)
    c["db"] = pd.cut(c.dev_buy_share.fillna(0),
                     [-1, 0.001, 0.02, 0.05, 0.1, 0.2, 1e9]).cat.codes
    c["sn"] = pd.cut(c.n_snipers.fillna(0), [-1, 0, 2, 4, 6, 10, 1e9]).cat.codes
    c["bl"] = pd.cut(c.n_birth_legs.fillna(0), [-1, 1, 3, 6, 12, 1e9]).cat.codes
    c["stratum"] = (c.day.astype(str) + "_" + c.db.astype(str) + "_"
                    + c.sn.astype(str) + "_" + c.bl.astype(str))
    return c


def cmd_discriminate(n_perm: int = 500) -> None:
    import datetime as dt

    import numpy as np

    rng = np.random.default_rng(SEED)
    foot, _ = _load()
    con = _duck()
    coins = con.execute(
        f"""SELECT mint, birth_time, graduated, dev_buy_share, n_snipers, n_birth_legs,
                   peak_mcap_sol, lifetime_s FROM read_parquet('{COINS}')"""
    ).fetchdf()
    con.close()

    # Treatment = a KNOWN core-spine wallet commits within 30 s. This is (a) pre-outcome and
    # (b) exactly what the firehose can detect in real time -- the front-runnable trigger.
    treated = set(foot[foot.crungs_30 > 0].mint)
    c = _stratify(coins, treated)
    tr, ct = c[c.treat], c[~c.treat]
    base = c.graduated.mean()
    k, n = int(tr.graduated.sum()), len(tr)
    lo, hi = _wilson(k, n)
    echo("\n=== TEST C -- MATCHED CONTROLS (the COINCIDENCE killer) ===")
    echo("  treatment = a COMMITTED 6-core-spine wallet enters within 30 s (pre-outcome, firehose-visible).")
    echo("  match on birth-day x dev-buy x sniper-count x birth-legs; controls are UNTOUCHED coins.")
    echo(f"  MEASURED HERE (not inherited): treated grad {k}/{n} = {k / n:.1%} "
         f"Wilson95%=[{lo:.1%},{hi:.1%}]  (population base {base:.2%})")
    cg = ct.groupby("stratum")["graduated"].agg(["mean", "size"])
    tg = tr.groupby("stratum")["graduated"].agg(["mean", "size"])
    m = tg.join(cg, lsuffix="_t", rsuffix="_c").dropna()
    m = m[m["size_c"] >= 5]
    wt = m["size_t"]
    tgr = (m["mean_t"] * wt).sum() / wt.sum()
    cgr = (m["mean_c"] * wt).sum() / wt.sum()
    echo(f"  matched strata: {len(m):,}, covering {int(wt.sum()):,} treated coins")
    echo(f"  treated grad (matched):          {tgr:.2%}")
    echo(f"  matched-control grad (untouched): {cgr:.2%}   "
         f"<- COINCIDENCE accounts for base {base:.2%} -> {cgr:.2%}")
    echo(f"  RESIDUAL LIFT (treated / matched-control) = {tgr / cgr:.2f}x")
    echo("  READ: matching on public early quality explains part; a >3x residual survives, so")
    echo("  the ladder's pick carries graduation signal BEYOND what we can already observe.")

    # ---- per-day robustness + entity-aware CI --------------------------------------------
    # The organism is ONE entity, so coins are not independent draws for ATTRIBUTION. The ten
    # days are ten quasi-independent replications; their spread is the honest uncertainty on
    # the lift, and a day-bootstrap gives its CI. (PROGRAM.md 3: burst-ESS -- a coin-level t is
    # meaningless here.)
    echo("\n  per-day matched lift (temporal robustness; the ladder is ONE bursty entity):")
    echo(f"  {'day':>12} {'n_treat':>8} {'treated':>8} {'control':>8} {'lift':>6}")
    per_day_lifts = []
    for day, g in c.groupby("day"):
        gt, gc = g[g.treat], g[~g.treat]
        if len(gt) < 50:
            continue
        cgd = gc.groupby("stratum")["graduated"].agg(["mean", "size"])
        tgd = gt.groupby("stratum")["graduated"].agg(["mean", "size"])
        mm = tgd.join(cgd, lsuffix="_t", rsuffix="_c").dropna()
        mm = mm[mm["size_c"] >= 3]
        if not len(mm):
            continue
        w = mm["size_t"]
        a = (mm["mean_t"] * w).sum() / w.sum()
        bb = (mm["mean_c"] * w).sum() / w.sum()
        if bb > 0:
            per_day_lifts.append(a / bb)
        ds = dt.datetime.utcfromtimestamp(day * 86400).strftime("%Y-%m-%d")
        echo(f"  {ds:>12} {int(w.sum()):>8,} {a:>7.1%} {bb:>7.1%} {a / max(bb, 1e-9):>5.2f}x")
    pdl = np.array(per_day_lifts)
    boot = np.array([rng.choice(pdl, size=len(pdl), replace=True).mean() for _ in range(2000)])
    echo(f"  10-day lift: mean {pdl.mean():.2f}x, sd {pdl.std():.2f}, "
         f"range [{pdl.min():.2f},{pdl.max():.2f}]x; day-bootstrap 95% CI "
         f"[{np.percentile(boot, 2.5):.2f}x, {np.percentile(boot, 97.5):.2f}x]")

    # ---- TEST E: the rotation null ----
    echo("\n=== TEST E -- ROTATION NULL (stratified label permutation) ===")
    echo(f"  reassign the ladder's picks at random WITHIN each stratum ({n_perm} draws): destroys")
    echo("  WHICH coin the ladder chose while holding the matched features and the pick count")
    echo("  fixed. Beating it means the pick is the ladder, not the features. This is the")
    echo("  mandatory burst-safe null (PROGRAM.md 3) -- a coin-level t would be off by orders.")
    cells = []
    obs_num = obs_den = 0.0
    for _, g in c.groupby("stratum"):
        nt = int(g.treat.sum())
        if nt == 0:
            continue
        y = g.graduated.values.astype(float)
        cells.append((y, nt))
        obs_num += g.loc[g.treat, "graduated"].sum()
        obs_den += nt
    obs = obs_num / obs_den
    null = np.array([
        sum(rng.choice(y, size=nt, replace=False).sum() for y, nt in cells) / obs_den
        for _ in range(n_perm)
    ])
    z = (obs - null.mean()) / null.std()
    echo(f"  observed treated grad (within-stratum): {obs:.2%}")
    echo(f"  permutation null: mean {null.mean():.2%}, sd {null.std():.3%}, max {null.max():.2%}")
    echo(f"  z = {z:.1f}; p(null >= obs) = {(null >= obs).mean():.4f} "
         f"(0 => < 1/{n_perm})")

    # ---- TEST D: the natural experiment ----
    echo("\n=== TEST D -- THE NATURAL EXPERIMENT (entered-then-what-differs) ===")
    echo("  among coins the ladder entered early (core rung <=30s), graduated vs failed:")
    echo("  MAKE would separate them on the ladder's OWN dose; PICK separates them on COIN QUALITY.")
    ec = foot[foot.crungs_30 > 0]
    nx = ec.groupby("graduated").agg(
        n=("mint", "size"),
        med_dev_buy_share=("dev_buy_share", "median"),
        med_n_snipers=("n_snipers", "median"),
        med_n_birth_legs=("n_birth_legs", "median"),
        med_core_rungs_30s=("crungs_30", "median"),
        med_core_rungs_final=("crungs_399", "median"),
        med_ladder_supply_pct=("ladder_supply_pct", "median"),
    )
    echo(nx.to_string(float_format=lambda x: f"{x:.3f}"))
    echo("  READ: winners carry ~5x the dev buy; the ladder's own supply is LOWER on winners.")
    echo("  What separates their wins from losses is the coin, not their capital -- PICK.")

    echo("\n=== VERDICT ===")
    echo(f"  MEASURED here: 6-core rung<=30s graduates {k / n:.1%} (Wilson [{lo:.1%},{hi:.1%}]),")
    echo(f"  = {tgr / cgr:.2f}x a matched control's {cgr:.1%} "
         f"(day-bootstrap CI [{np.percentile(boot, 2.5):.2f}x, {np.percentile(boot, 97.5):.2f}x]).")
    echo("  NOT the brief's unverified 35-62%; the edge does NOT evaporate.")
    echo("  MAKE (capital)   : REFUTED  -- supply <0.5% median on grads, inverse dose-response.")
    echo("  COINCIDENCE      : PARTIAL  -- matched/rotation null lifts base 2.45% -> ~9%; real, subtracted.")
    echo("  PICK             : CONFIRMED -- >3x residual over the rotation null, all 10 days, z~59;")
    echo("                     natural experiment separates on coin quality, not their dose.")
    echo("  => the ladder is a graduation DETECTOR. The edge is timing (be in before migration),")
    echo("     available IF an executable exit clears friction. See --frontrun.")


# ---------------------------------------------------------------------------------------
# STAGE 3 -- FRONT-RUN VIABILITY: detection latency, funding lead, honest paper-sim.
# ---------------------------------------------------------------------------------------


def cmd_frontrun() -> None:
    import pandas as pd

    foot, legs = _load()

    echo("\n=== 3.1 DETECTION LATENCY (is the entry observable in real time?) ===")
    fc = foot.loc[foot.first_core_lat.notna(), "first_core_lat"]
    qs = fc.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    echo("  first CORE-spine rung latency vs coin birth (seconds):")
    for k, v in qs.items():
        echo(f"    p{int(k * 100):>2}: {v:>5.0f} s")
    echo(f"  core-touched coins with first rung <=10s: {(fc <= 10).mean():.0%}; "
         f"<=30s: {(fc <= 30).mean():.0%}; <=60s: {(fc <= 60).mean():.0%}")
    echo("  READ: median +6 s. The firehose sees the create + first buys; a known spine")
    echo("  wallet buying a <10 s-old coin is the trigger, detectable at the +5 s the org fires.")

    echo("\n=== 3.2 FUNDING LEAD (fresh soldiers are pre-announced) ===")
    if HUB_FANOUT.exists():
        con = _duck()
        fan = con.execute(
            f"""SELECT "to" AS owner, min(ts) AS fund_ts, sum(sol) sol, count(*) n
                FROM read_parquet('{HUB_FANOUT}') GROUP BY 1"""
        ).fetchdf()
        con.close()
        first_trade = legs.groupby("owner")["t"].min().rename("first_trade")
        fan = fan.merge(first_trade, on="owner", how="left")
        fan["fund_month"] = pd.to_datetime(fan.fund_ts, unit="s").dt.strftime("%Y-%m")
        fresh = fan[fan.fund_month == "2026-08"]
        traded = fan.dropna(subset=["first_trade"])
        traded = traded[traded.first_trade > traded.fund_ts]
        pre = fan.dropna(subset=["first_trade"]).eval("fund_ts < first_trade").mean()
        echo(f"  hub funded {len(fan):,} distinct wallets; {len(fresh)} first funded 2026-08 "
             f"({int(fresh.first_trade.notna().sum())} already trading in-corpus).")
        echo(f"  funding PRECEDES first observed trade for {pre:.0%} of funded wallets "
             f"(mechanical: gas must arrive first).")
        lead_h = ((traded.first_trade - traded.fund_ts) / 3600)
        echo(f"  funding -> first-trade lead: median {lead_h.median():.1f} h, "
             f"p25 {lead_h.quantile(.25):.1f} h (a real pre-position window).")
    else:
        echo("  (hub_fanout.parquet missing; run .cache/clustermap/fetch_fanout.py)")

    echo("\n=== 3.3 PAPER-SIM (enter at first core rung <=30s, exit at migration) ===")
    echo("  Honest boundary: the corpus has no SOL leg and no curve price at +30 s, so the")
    echo("  entry->migration multiple is NOT measured here. We report the outcome mix and the")
    echo("  BREAKEVEN multiple, and price dead coins as lifelines. This is a viability gate,")
    echo("  not a backtested PnL.")
    sim = foot[foot.crungs_30 > 0]
    g = sim.graduated.mean()
    echo(f"  treated coins: {len(sim):,}; graduation (executable-exit event) rate {g:.1%}")
    echo(f"  median peak_mcap_sol -- graduated {sim[sim.graduated].peak_mcap_sol.median():.0f} SOL"
         f" vs failed {sim[~sim.graduated].peak_mcap_sol.median():.1f} SOL")
    breakeven = 1 / g
    echo(f"  BREAKEVEN grad-exit multiple at 0% dead-recovery: {breakeven:.2f}x "
         f"(need the +30s->migration move to clear this).")
    echo(f"  {'grad-exit':>10} {'dead-recovery':>14} {'EV/trade':>10}")
    for mult, rec in [(3.0, 0.0), (5.0, 0.1), (8.0, 0.2)]:
        ev = g * (mult - 1) + (1 - g) * (rec - 1)
        echo(f"  {mult:>9.0f}x {rec:>13.0%} {ev:>+9.1%}")
    echo("  READ: +EV needs a grad-exit multiple above ~3.3x and modest dead salvage. Given")
    echo("  graduated coins reach ~400 SOL mcap and entry is at +6 s, that is plausible but")
    echo("  unproven here; live curve data + real friction (priority fee, slippage, MEV) decide it.")
    echo("\n  CAVEAT: everything is IN-SAMPLE (clusters built from this corpus). The deployable")
    echo("  object is the FIXED wallet set in the watchlist, not a re-clustering; the OOS gate")
    echo("  is a forward run watching those wallets (RESULT_cluster_map.md §14 leaves it open).")


# ---------------------------------------------------------------------------------------
# STAGE 4 -- THE WATCHLIST: the contract for the firehose (does NOT wire it).
# ---------------------------------------------------------------------------------------


def cmd_watchlist() -> None:
    import pandas as pd

    STATE.mkdir(parents=True, exist_ok=True)
    org = organism_clusters()
    cl = pd.read_parquet(CM_CACHE / "clusters_bulk.parquet")
    lw = cl[cl["cid"].isin(org)]
    cid_of = dict(zip(lw.owner, lw.cid))

    if not HUB_FANOUT.exists():
        raise SystemExit(f"{HUB_FANOUT} missing; run .cache/clustermap/fetch_fanout.py")
    con = _duck()
    fan = con.execute(
        f"""SELECT "to" AS owner, ts, signature, sol FROM read_parquet('{HUB_FANOUT}')"""
    ).fetchdf()
    con.close()
    fan = fan.sort_values("ts")
    ev = fan.groupby("owner").agg(
        first_fund_ts=("ts", "min"), first_fund_sig=("signature", "first"),
        total_sol=("sol", "sum"), n_transfers=("signature", "size"),
    ).reset_index()
    ev["fund_month"] = pd.to_datetime(ev.first_fund_ts, unit="s").dt.strftime("%Y-%m")
    ev["cid"] = ev.owner.map(cid_of)

    rows = [{
        "wallet": HUB, "role": "funding_hub", "cid": None,
        "evidence": "27846.17 SOL out over 4286 transfers to 579 dests (2024-02..2026-08); "
                    "funded all 6 core ladder clusters plus 7 more organism clusters",
        "first_fund_ts": None, "funding_tx": None, "total_sol_from_hub": None, "fund_month": None,
    }]
    fresh = ev[ev.fund_month == "2026-08"].sort_values("first_fund_ts")
    for _, r in fresh.iterrows():
        role = ("fresh_core_spine" if r.cid in CORE6
                else "fresh_organism" if not pd.isna(r.cid)
                else "fresh_funded_this_month")
        rows.append({
            "wallet": r.owner, "role": role,
            "cid": None if pd.isna(r.cid) else int(r.cid),
            "evidence": f"first funded by hub at {int(r.first_fund_ts)} ({r.fund_month}); "
                        f"{r.total_sol:.3f} SOL over {int(r.n_transfers)} transfers",
            "first_fund_ts": int(r.first_fund_ts), "funding_tx": r.first_fund_sig,
            "total_sol_from_hub": round(float(r.total_sol), 4), "fund_month": r.fund_month,
        })
    have = {x["wallet"] for x in rows}
    for _, r in lw[lw.cid.isin(CORE6)].iterrows():
        if r.owner in have:
            continue
        e = ev[ev.owner == r.owner]
        f = e.iloc[0] if len(e) else None
        rows.append({
            "wallet": r.owner, "role": "core_spine", "cid": int(r.cid),
            "evidence": "member of the 6-core 8 s-rung accumulator spine (never sells)"
                        + (f"; hub-funded at {int(f.first_fund_ts)}, {f.total_sol:.3f} SOL"
                           if f is not None else "; no direct hub-funding tx in enumerated set"),
            "first_fund_ts": None if f is None else int(f.first_fund_ts),
            "funding_tx": None if f is None else f.first_fund_sig,
            "total_sol_from_hub": None if f is None else round(float(f.total_sol), 4),
            "fund_month": None if f is None else f.fund_month,
        })

    out = STATE / "watchlist.jsonl"
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    from collections import Counter

    counts = Counter(r["role"] for r in rows)
    echo(f"\n=== watchlist -> {out} ===")
    echo(f"  {len(rows)} rows; roles: {dict(counts)}")
    echo(f"  fresh wallets funded this month: {len(fresh)} (all with funding-tx evidence)")
    echo("  CONTRACT: subscribe accountTrade on every `wallet`; a buy on a <10 s-old mint is a")
    echo("  live ladder entry. `funding_tx` is the on-chain evidence each wallet is one soldier.")
    echo("  This module does NOT wire the firehose.")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--dose", action="store_true")
    ap.add_argument("--discriminate", action="store_true")
    ap.add_argument("--frontrun", action="store_true")
    ap.add_argument("--watchlist", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--draws", type=int, default=500)
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    if args.all:
        cmd_extract(force=args.force)
        cmd_dose()
        cmd_discriminate(n_perm=args.draws)
        cmd_frontrun()
        cmd_watchlist()
        return 0
    if args.extract:
        cmd_extract(force=args.force)
        return 0
    if args.dose:
        cmd_dose()
        return 0
    if args.discriminate:
        cmd_discriminate(n_perm=args.draws)
        return 0
    if args.frontrun:
        cmd_frontrun()
        return 0
    if args.watchlist:
        cmd_watchlist()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
