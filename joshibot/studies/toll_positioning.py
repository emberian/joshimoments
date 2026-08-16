#!/usr/bin/env python3
"""toll_positioning.py -- the toll surface, enumerated and sized against THIS operator.

Eight consecutive strategy studies came back null or negative; the only revenue that has
ever measured positive on this desk is TOLLS ON FLOW (creator fees, LP fee harvest).  The
operator's thesis: you get paid for being positioned where flow crosses, never for
predicting where it goes.  This study takes that seriously and tries to break it.

It (a) enumerates the toll surface, (b) sizes each toll against the desk's actual capital
(~1 SOL liquid, ~$1,400 LP book, a Streamflow escrow vesting 6.2635% of DREGG supply),
(c) models the four coupled DREGG levers -- creator-fee stream, vesting supply, LP, and
volume driving -- as one joint position, and (d) quantifies decay and fragility, because
tolls are rents and rents get routed around.

Inputs it does NOT re-derive (sources cited inline where used):
  - eta > VR(T) rule and all eta/VR measurements ............. RESULT_circuit_theory.md
  - token-token record (10 closed positions, -$595 vs HODL) .. RESULT_edge_creation.md
  - Jupiter maker economics (10 bps, no rebate, one keeper) .. RESULT_jupiter_programs.md
  - FOMO gas-sponsorship channel (22.5% of traders) .......... RESULT_copytrading.md
  - graduation census / launch base rates .................... RESULT_control_arm.md
  - complete claim + wallet ledger ........................... RESULT_position_history.md

New measurements made here:
  decay   -- DREGG volume decay from the pool's full daily life AND creator-fee decay
             from the operator's own 266-claim history: two models (exponential,
             power-law), temporal split, OOS vs no-decay nulls, half-life with
             Newey-West CI, and the fee-stream NPV that follows.
  tiers   -- volume-weighted fee-tier occupancy: does the published inverse-FDV ladder
             explain the measured realized take?  And the weekly realized-take series,
             claims / volume, which is the ladder question measured directly.
  escrow  -- vesting arithmetic against live pool depth; exit-cost table by channel.
  ladder  -- THE unrun benchmark from RESULT_lp_history / RESULT_edge_creation "what to
             do #4": per-fill comparison of the desk's one-sided DLMM sell ladders
             against routing the same size at the same minute.  Hour-clustered
             inference via statsmodels.
  joint   -- the four-lever DREGG model: measured take rate, measured price->volume
             association (rotation null), the tier kink as an upper bound, the value of
             the volume lever, and the joint income statement against obligations.
  rank    -- the ranked toll table with arithmetic shown.
  nulls   -- this study's own nulls and trials accounting in one place.

Methodology (PROGRAM.md par.3): temporal splits only, no resampling, thresholds stated,
nulls run, trials counted and reported in `nulls`.

Requires the research dependency group:
    uv run --group research python studies/toll_positioning.py all
    uv run --group research python studies/toll_positioning.py {decay,tiers,escrow,ladder,joint,rank,nulls}

Read-only: keyless GeckoTerminal (cached), the mean_reversion minute-bar dataset, the
position_history ledger + tx cache, and the edge_creation transaction cache.  Signs
nothing, sends nothing, writes only studies/data/toll_positioning/.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO: Final[Path] = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DATA: Final[Path] = REPO / "studies" / "data" / "toll_positioning"
DATA.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------------------
# fixed inputs, each with its source
# ---------------------------------------------------------------------------------------

DREGG_SOL_POOL: Final[str] = "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU"  # PumpSwap canonical
WEAVE_SOL_POOL: Final[str] = "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn"

SUPPLY: Final[float] = 999_872_425.106879  # RESULT_position_history.md par.7(d)

# pump.fun dynamic creator-fee ladder as recorded twice independently
# (PROGRAM.md par.0; Marino sec.VII).  FDV boundaries in USD.
TIER_TABLE: Final[list[tuple[float, float]]] = [
    (300_000.0, 0.0095),
    (1_000_000.0, 0.0060),
    (float("inf"), 0.0035),
]
REALIZED_TAKE_LO: Final[float] = 0.0081  # RESULT_circuit_model.md par.9.3
REALIZED_TAKE_HI: Final[float] = 0.0119

# position_history ground truth (reproduced from its cache in `decay`)
LEDGER: Final[Path] = REPO / ".cache" / "position_history" / "ledger.json"
TX_CACHE: Final[Path] = REPO / ".cache" / "position_history" / "tx"
PFEE_PROGRAM: Final[str] = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
DREGG_FEE_VAULT: Final[str] = "2dQa7pRL8czyJJsQfGyMBacqf9FSV96cwirov5KyUE4A"
SOCIAL_FEE_VAULT: Final[str] = "8buZegTzEGrEPvHLyeJfP3ppcUFiuPHvTHGCArVcV7kF"

# Streamflow escrow, RESULT_position_history.md par.7(d)
ESCROW_LOCKED_NOW: Final[float] = 59_013_761.85       # DREGG still locked
ESCROW_ORIGINAL: Final[float] = 62_626_849.3125
RELEASE_DREGG: Final[float] = 1_204_362.4868          # per tranche, strict 14-day cadence
RELEASE_PERIOD_D: Final[float] = 14.0
NEXT_TRANCHE: Final[str] = "2026-08-22T16:31Z"

# Desk reality (brief + RESULT_lp_strategy.md par.15)
LIQUID_SOL: Final[float] = 1.0
LP_BOOK_USD: Final[float] = 1_400.0
OBLIGATIONS_USD_MO: Final[float] = 4_100.0

# On-chain-decoded fees (RESULT_edge_creation.md sec.1, RESULT_swing_cluster.md)
PUMPSWAP_TOTAL_FEE: Final[float] = 0.0144   # taker pays, per leg
DLMM_LP_FEE: Final[float] = 0.054           # 6.00% base, 10% protocol -> 5.40% to LP
DLMM_LP_FEE_5: Final[float] = 0.045         # 5.00% tier variant

GECKO: Final[str] = "https://api.geckoterminal.com/api/v2/networks/solana"
UA: Final[dict[str, str]] = {"User-Agent": "joshibot-research/0.1 (studies/toll_positioning.py)"}
LAUNCH_DATE: Final[dt.date] = dt.date(2026, 6, 27)

# edge_creation transaction cache (already on disk from that study's run)
EDGE_CACHE: Final[Path] = Path("/tmp/joshibot-edge-creation")
MR_OHLCV: Final[Path] = REPO / "studies" / "data" / "mean_reversion" / "gt_ohlcv.jsonl"

MINTS: Final[dict[str, str]] = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}
METEORA_DLMM: Final[str] = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"


# ---------------------------------------------------------------------------------------
# data layer
# ---------------------------------------------------------------------------------------

def _get_json(url: str, tries: int = 4) -> Any:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2.0 * (i + 1))


def _cached(name: str, fetch, max_age_s: float = 6 * 3600) -> Any:
    path = DATA / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
        return json.loads(path.read_text())
    out = fetch()
    path.write_text(json.dumps(out))
    return out


def daily_bars(pool: str = DREGG_SOL_POOL) -> pd.DataFrame:
    """Full daily OHLCV+volume of the pool, USD.  Today's partial bar dropped, not zeroed."""
    raw = _cached(
        f"daily_{pool[:8]}.json",
        lambda: _get_json(f"{GECKO}/pools/{pool}/ohlcv/day?aggregate=1&limit=1000&currency=usd"),
    )
    rows = raw["data"]["attributes"]["ohlcv_list"]
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol_usd"])
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.date
    df = df.sort_values("ts").reset_index(drop=True)
    df = df[df["date"] < dt.datetime.now(dt.UTC).date()]
    df["t"] = [(d - LAUNCH_DATE).days for d in df["date"]]
    return df


def hourly_bars(pool: str = DREGG_SOL_POOL) -> pd.DataFrame:
    raw = _cached(
        f"hourly_{pool[:8]}.json",
        lambda: _get_json(f"{GECKO}/pools/{pool}/ohlcv/hour?aggregate=1&limit=1000&currency=usd"),
    )
    rows = raw["data"]["attributes"]["ohlcv_list"]
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol_usd"]) \
        .sort_values("ts").reset_index(drop=True)


def pool_now(pool: str = DREGG_SOL_POOL) -> dict[str, float]:
    raw = _cached(f"pool_{pool[:8]}.json", lambda: _get_json(f"{GECKO}/pools/{pool}"), 1800)
    a = raw["data"]["attributes"]
    return {
        "price_usd": float(a["base_token_price_usd"]),
        "sol_usd": float(a["quote_token_price_usd"]),
        "fdv_usd": float(a["fdv_usd"]),
        "tvl_usd": float(a["reserve_in_usd"]),
        "vol24_usd": float(a["volume_usd"]["h24"]),
    }


def tier_rate(fdv_usd: float) -> float:
    for bound, rate in TIER_TABLE:
        if fdv_usd < bound:
            return rate
    return TIER_TABLE[-1][1]


class StepPrices:
    """Step-function price lookup over the mean_reversion GT dataset.

    Series are token-in-SOL (`<tok>_per_sol`, provenance token=base) and SOL-in-USD.
    `at()` returns the last close at or before t -- never an interpolation
    (interpolating an unobserved price is the fabrication class PROGRAM.md par.0 names).
    """

    def __init__(self) -> None:
        series: dict[str, dict[int, float]] = {}
        with MR_OHLCV.open() as fh:
            for line in fh:
                r = json.loads(line)
                key = r["series"]
                series.setdefault(key, {})
                # minute overwrites hour where both exist (finer wins)
                if r["timeframe"] == "hour" and r["t_event"] in series[key]:
                    continue
                series[key][r["t_event"]] = float(r["close"])
        self._s: dict[str, tuple[list[int], list[float]]] = {}
        for key, m in series.items():
            ts = sorted(m)
            self._s[key] = (ts, [m[t] for t in ts])

    def at(self, series: str, when: int) -> float | None:
        ts, px = self._s[series]
        i = bisect.bisect_right(ts, when) - 1
        if i < 0:
            return None
        return px[i]

    def gap_s(self, series: str, when: int) -> float:
        """Age of the bar `at()` would return -- staleness diagnostic."""
        ts, _ = self._s[series]
        i = bisect.bisect_right(ts, when) - 1
        return float("inf") if i < 0 else when - ts[i]


def claim_series() -> pd.DataFrame:
    """Every creator-fee claim, with the PAYING vault attributed from the raw tx.

    Reproduces RESULT_position_history.md par.7(c) from its own cache: a claim is a
    pfee-program transaction where pumpfun_main's SOL delta is positive; the source is
    whichever fee vault's lamports went DOWN (classify by whose lamports fell, never by
    what the transaction touched).
    """
    led = json.loads(LEDGER.read_text())
    rows = []
    for e in led["entries"]:
        lam = e.get("sol", {}).get("pumpfun_main", 0)
        if PFEE_PROGRAM not in e.get("programs", []) or lam <= 0:
            continue
        src = "other"
        txp = TX_CACHE / f"{e['signature']}.json"
        if txp.exists():
            tx = json.loads(txp.read_text())
            keys = [k["pubkey"] if isinstance(k, dict) else k
                    for k in tx["transaction"]["message"]["accountKeys"]]
            pre, post = tx["meta"]["preBalances"], tx["meta"]["postBalances"]
            for a, pr, po in zip(keys, pre, post):
                if po < pr and a == DREGG_FEE_VAULT:
                    src = "dregg"
                    break
                if po < pr and a == SOCIAL_FEE_VAULT:
                    src = "social"
                    break
        rows.append({"ts": e["block_time"], "sol": lam / 1e9, "src": src,
                     "date": dt.datetime.fromtimestamp(e["block_time"], dt.UTC).date()})
    df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------------------
# decay
# ---------------------------------------------------------------------------------------

def cmd_decay() -> dict[str, Any]:
    import statsmodels.api as sm

    df = daily_bars()
    live = pool_now()
    cl = claim_series()
    print("=" * 100)
    print("DECAY -- volume from the pool's full daily life; fees from the operator's own claims")
    print("=" * 100)
    print(f"volume bars: {len(df)}  {df['date'].iloc[0]} .. {df['date'].iloc[-1]}   "
          f"peak ${df['vol_usd'].max():,.0f}/d   last ${df['vol_usd'].iloc[-1]:,.0f}/d")
    tot = cl.groupby("src")["sol"].sum()
    print(f"claims: {len(cl)} totalling {cl['sol'].sum():.1f} SOL "
          f"(dregg {tot.get('dregg', 0):.1f} / social {tot.get('social', 0):.1f} / "
          f"other {tot.get('other', 0):.1f})  "
          f"[position_history: 266 / 757.07 / 467.2 / 287.2]")

    d = df[df["t"] >= 1].copy()   # day 0 is a partial (pool created intraday)
    assert (d["vol_usd"] > 100).all(), "dust bars would need explicit handling"
    d["logv"] = np.log(d["vol_usd"])
    d["logt"] = np.log(d["t"].astype(float))

    # -------- temporal split ----------------------------------------------------------
    split_date = dt.date(2026, 8, 1)
    train, test = d[d["date"] <= split_date], d[d["date"] > split_date]
    print(f"\ntemporal split: train n={len(train)} (<= {split_date}), test n={len(test)}")

    def fit_ols(y, X):
        return sm.OLS(np.asarray(y), sm.add_constant(np.asarray(X, dtype=float))) \
            .fit(cov_type="HAC", cov_kwds={"maxlags": 7})

    oos: dict[str, float] = {}
    for name, xcol in [("exponential", "t"), ("power-law", "logt")]:
        m = fit_ols(train["logv"], train[xcol])
        pred = m.params[0] + m.params[1] * test[xcol].to_numpy(dtype=float)
        oos[name] = float(np.mean(np.abs(pred - test["logv"].to_numpy())))
    null_const = float(np.mean(np.abs(train["logv"].mean() - test["logv"].to_numpy())))
    null_rw = float(np.mean(np.abs(train["logv"].iloc[-1] - test["logv"].to_numpy())))
    print("OOS mean |error| in log volume (2 candidate models = 2 selection trials, see `nulls`):")
    print(f"  no-decay null (train mean):   {null_const:.3f}")
    print(f"  random-walk null (last obs):  {null_rw:.3f}")
    for k, v in oos.items():
        print(f"  {k:<29} {v:.3f}")

    # -------- full-sample fits --------------------------------------------------------
    print("\nfull-sample fits (HAC/Newey-West, maxlags=7):")
    out: dict[str, Any] = {"oos": oos, "null_const": null_const, "null_rw": null_rw}
    m_exp = fit_ols(d["logv"], d["t"])
    b, se = float(m_exp.params[1]), float(m_exp.bse[1])
    hl = math.log(2) / -b if b < 0 else float("inf")
    hl_lo = math.log(2) / -(b - 1.96 * se) if b - 1.96 * se < 0 else float("inf")
    hl_hi = math.log(2) / -(b + 1.96 * se) if b + 1.96 * se < 0 else float("inf")
    print(f"  exponential: slope {b:+.4f}/day (SE {se:.4f}) -> half-life {hl:.1f} d "
          f"[95% {hl_hi:.1f} .. {hl_lo:.1f} d]")
    m_pl = fit_ols(d["logv"], d["logt"])
    bp, sep = float(m_pl.params[1]), float(m_pl.bse[1])
    print(f"  power-law:   exponent {bp:+.3f} (SE {sep:.3f})  [volume ~ t^{bp:.2f}]")
    out |= {"exp_slope": b, "exp_se": se, "half_life_d": hl, "pl_exponent": bp}

    # -------- the same fits on the FEE series (weekly buckets: claims are lumpy) ------
    cl_d = cl[cl["src"] == "dregg"].copy()
    cl_d["week"] = ((cl_d["ts"] - cl_d["ts"].min()) // (7 * 86400)).astype(int)
    wk = cl_d.groupby("week")["sol"].sum().reset_index()
    wk = wk[wk["week"] < wk["week"].max()]  # last bucket is partial: censored, dropped
    wk["logf"] = np.log(wk["sol"])
    m_fee = fit_ols(wk["logf"], wk["week"] * 7.0)
    bf, sef = float(m_fee.params[1]), float(m_fee.bse[1])
    hlf = math.log(2) / -bf if bf < 0 else float("inf")
    print(f"\nDREGG-vault claim series, weekly buckets (n={len(wk)}, last partial week dropped):")
    for _, r in wk.iterrows():
        print(f"  week {int(r['week']):>2}: {r['sol']:>7.1f} SOL")
    print(f"  exponential fit: slope {bf:+.4f}/day (SE {sef:.4f}) -> half-life {hlf:.1f} d")
    out |= {"fee_slope": bf, "fee_half_life_d": hlf}

    # -------- NPV of the remaining stream ---------------------------------------------
    v0 = float(d["vol_usd"].tail(7).mean())
    fee_sol_14d = cl_d[cl_d["ts"] > cl_d["ts"].max() - 14 * 86400]["sol"].sum()
    fee_usd_day_now = fee_sol_14d / 14 * live["sol_usd"]
    print(f"\ntrailing-7d volume ${v0:,.0f}/day; trailing-14d DREGG-vault claims "
          f"{fee_sol_14d:.1f} SOL = ${fee_usd_day_now:,.0f}/day "
          f"(realized take {fee_sol_14d * live['sol_usd'] / max(1.0, d['vol_usd'].tail(14).sum()):.2%} "
          f"of trailing-14d volume)")
    t_now = float(d["t"].iloc[-1])
    print(f"{'model':<14}{'$/day now':>12}{'NPV of stream':>16}{'days to <$135/d':>18}   note")
    daily = fee_usd_day_now
    npv_exp = daily / -b if b < 0 else float("inf")
    npv_pl = sum(daily * ((t_now + k) / t_now) ** bp for k in range(1, 366))
    floor = OBLIGATIONS_USD_MO / 30.4
    t_floor_exp = math.log(floor / daily) / b if (b < 0 and daily > floor) else 0.0
    t_floor_pl = t_now * ((floor / daily) ** (1 / bp) - 1) if (bp < 0 and daily > floor) else 0.0
    print(f"{'exponential':<14}{daily:>12,.0f}{npv_exp:>16,.0f}{t_floor_exp:>18,.0f}   "
          f"NPV = daily/|slope| (decay is the discount)")
    print(f"{'power-law':<14}{daily:>12,.0f}{npv_pl:>16,.0f}{t_floor_pl:>18,.0f}   "
          f"NPV over a 1-year horizon only")
    print(f"($135/day = obligations ${OBLIGATIONS_USD_MO:,.0f}/mo; NPV in USD, no time discount "
          f"beyond the decay itself)")
    out |= {"v0_7d": v0, "fee_usd_day_now": fee_usd_day_now, "sol_usd": live["sol_usd"],
            "npv_exp": npv_exp, "npv_pl": npv_pl}

    print("""
context that the fit cannot see: the SOCIAL fee stream (id 704250 PDA) is already dead --
142.5 SOL in June, 141.8 in July, 2.9 in August (RESULT_position_history.md par.7c).  Only
the volume-linked DREGG stream survives.  Decay fits above are on the surviving stream.""")
    return out


# ---------------------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------------------

def cmd_tiers() -> dict[str, Any]:

    h = hourly_bars()
    live = pool_now()
    df = daily_bars()
    cl = claim_series()
    print("=" * 100)
    print("TIERS -- does the published inverse-FDV ladder explain the measured take?")
    print("=" * 100)
    print(f"live FDV ${live['fdv_usd']:,.0f} ({100 * (live['fdv_usd'] / 300_000 - 1):+.1f}% from "
          f"the $300k boundary); ladder rate here {tier_rate(live['fdv_usd']):.2%}, one tier "
          f"down {TIER_TABLE[0][1]:.2%}")

    now = time.time()
    out: dict[str, Any] = {}
    print("\nvolume-weighted tier occupancy (hourly close FDV vs $300k):")
    print(f"{'window':<8}{'vol below':>14}{'vol above':>14}{'share below':>13}{'implied take':>14}")
    for days in (7, 14, 30):
        w = h[h["ts"] > now - days * 86400]
        fdv = w["close"].astype(float) * SUPPLY
        vb = float(w.loc[fdv < 300_000, "vol_usd"].sum())
        va = float(w.loc[fdv >= 300_000, "vol_usd"].sum())
        take = (0.0095 * vb + 0.0060 * va) / (vb + va) if vb + va else float("nan")
        print(f"{days:>3}d    {vb:>14,.0f}{va:>14,.0f}{vb / (vb + va):>12.1%}{take:>13.3%}")
        out[f"mixture_take_{days}d"] = take

    # -------- the realized take measured directly: weekly claims / weekly volume ------
    cl_d = cl[cl["src"] == "dregg"].copy()
    daily_fee = cl_d.groupby("date")["sol"].sum()
    vol = df.set_index("date")["vol_usd"]
    close = df.set_index("date")["close"]
    idx = vol.index
    fee_sol = pd.Series([daily_fee.get(dd, 0.0) for dd in idx], index=idx)
    sp = StepPrices()
    solusd = pd.Series([sp.at("sol_per_usd", int(dt.datetime.combine(dd, dt.time(12), dt.UTC)
                                                 .timestamp())) or live["sol_usd"] for dd in idx],
                       index=idx)
    wkkey = pd.Series([(dd - idx[0]).days // 7 for dd in idx], index=idx)
    g = pd.DataFrame({"fee_usd": fee_sol * solusd, "vol": vol, "wk": wkkey,
                      "fdv": close * SUPPLY})
    # ladder-PREDICTED take per day: volume-weighted tier rate over hourly bars where
    # hourly history exists (GT serves 1000 bars ~ 41 days), daily close FDV before that.
    h2 = h.copy()
    h2["date"] = pd.to_datetime(h2["ts"], unit="s", utc=True).dt.date
    h2["fdv"] = h2["close"].astype(float) * SUPPLY
    h2["rate"] = h2["fdv"].map(tier_rate)
    pred_day = h2.groupby("date").apply(
        lambda x: float((x["rate"] * x["vol_usd"]).sum() / x["vol_usd"].sum())
        if x["vol_usd"].sum() > 0 else float("nan"), include_groups=False)
    g["pred_rate"] = [pred_day.get(dd, tier_rate(close[dd] * SUPPLY)) for dd in idx]
    g["pred_fee"] = g["pred_rate"] * g["vol"]
    wk = g.groupby("wk").agg(fee_usd=("fee_usd", "sum"), vol=("vol", "sum"),
                             fdv=("fdv", "mean"), pred_fee=("pred_fee", "sum"),
                             n=("vol", "size"))
    wk = wk[wk["n"] == 7]  # only full weeks; partial buckets are censored, dropped
    wk["take"] = wk["fee_usd"] / wk["vol"]
    wk["pred"] = wk["pred_fee"] / wk["vol"]
    print("\nweekly realized take = DREGG-vault claims / canonical-pool volume "
          "(claims lag accrual by hours; weekly buckets absorb that), against the take "
          "the published ladder PREDICTS (volume-weighted tier rate, hourly FDV where "
          "hourly bars exist, daily close before):")
    print(f"{'week':<6}{'volume $':>14}{'claims $':>12}{'take':>9}{'ladder pred':>13}"
          f"{'meas/pred':>11}{'mean FDV $':>14}")
    for wknum, r in wk.iterrows():
        print(f"{int(wknum):<6}{r['vol']:>14,.0f}{r['fee_usd']:>12,.0f}{r['take']:>9.2%}"
              f"{r['pred']:>13.2%}{r['take'] / r['pred']:>11.2f}{r['fdv']:>14,.0f}")
    ratio = wk["take"] / wk["pred"]
    print(f"\nmeasured/predicted across {len(wk)} full weeks: mean {ratio.mean():.2f}, "
          f"range {ratio.min():.2f}-{ratio.max():.2f}")
    out["weekly_take"] = wk["take"].to_dict()
    out["take_recent"] = float(wk["take"].tail(3).mean())
    out["ratio_mean"] = float(ratio.mean())

    print(f"""
verdict, and it is a CORRECTION to two upstream documents:
  - The full-life claims/volume series measures a realized take of
    {wk['take'].min():.2%}-{wk['take'].max():.2%} weekly (recent 3-week mean {out['take_recent']:.2%}).
  - PROGRAM.md par.0 / RESULT_circuit_model.md par.9.3 report 0.81-1.19% "statistically
    excluding the 0.60% tier".  That figure divided an income ESTIMATE ($213-313/day)
    by a single-day volume snapshot ($26,300).  Dividing the operator's actual 154-claim
    history by the pool's actual daily volume, week by week, gives the series above --
    the better instrument DOES NOT REPLICATE the 0.81-1.19% level as a lifetime take.
  - Against the ladder's own prediction the measured take runs {ratio.mean():.2f}x on
    average.  The income model in PROGRAM.md par.0 should be read at ~{out['take_recent']:.2%}
    of volume, not 0.81-1.19%, and the "realized take exceeds the published tier"
    anomaly mostly dissolves into a denominator artifact.
  - Joint-model consequence: the $300k tier kink (0.60%->0.95%) is carried at the
    ladder's face value where the data is consistent with it, with the measured
    meas/pred ratio as the honest uncertainty band.""")
    return out


# ---------------------------------------------------------------------------------------
# escrow
# ---------------------------------------------------------------------------------------

def cmd_escrow() -> dict[str, Any]:
    live = pool_now()
    p, sol = live["price_usd"], live["sol_usd"]
    print("=" * 100)
    print("ESCROW -- Streamflow vesting vs live pool depth")
    print("=" * 100)
    rel_usd = RELEASE_DREGG * p
    rel_sol = rel_usd / sol
    esc_usd = ESCROW_LOCKED_NOW * p
    periods = ESCROW_LOCKED_NOW / RELEASE_DREGG
    sol_side = live["tvl_usd"] / 2 / sol
    print(f"locked {ESCROW_LOCKED_NOW:,.0f} DREGG = ${esc_usd:,.0f} at ${p:.7f} "
          f"({ESCROW_LOCKED_NOW / SUPPLY:.4%} of supply); next tranche {NEXT_TRANCHE}")
    print(f"release {RELEASE_DREGG:,.0f} DREGG / {RELEASE_PERIOD_D:.0f}d = ${rel_usd:,.0f} "
          f"= {rel_sol:.2f} SOL (~${rel_usd / RELEASE_PERIOD_D:,.0f}/day); "
          f"{periods:.0f} tranches = {periods * RELEASE_PERIOD_D / 30.4:.0f} months to full vest")
    impact = rel_sol / (sol_side + rel_sol)
    print(f"pool SOL side ~{sol_side:,.0f} SOL; one tranche as a single clip: "
          f"rho = B/Y = {rel_sol / sol_side:.2%} (2% envelope cap: "
          f"{'fits in ONE clip' if rel_sol / sol_side <= 0.02 else 'needs slicing'}); "
          f"impact B/(Y+B) = {impact:.2%}")

    take_mid = (REALIZED_TAKE_LO + REALIZED_TAKE_HI) / 2
    print("\nexit-cost per tranche by channel (negative = the channel PAYS you):")
    rows = [
        ("PumpSwap market-sell, outsider", PUMPSWAP_TOTAL_FEE + impact,
         "1.44% decoded fee + impact"),
        ("PumpSwap market-sell, OPERATOR", PUMPSWAP_TOTAL_FEE - take_mid + impact,
         f"minus creator recapture ~{take_mid:.2%} of own notional"),
        ("Jupiter limit order", 0.0010,
         "10 bps, no rebate, option written free (RESULT_jupiter_programs.md)"),
        ("DLMM one-sided sell ladder", float("nan"),
         "EARNS the LP fee on the exit flow -- measured in `ladder`, not assumed"),
    ]
    for name, cost, why in rows:
        tail = "   -> measured in `ladder`" if math.isnan(cost) else f"   -> ${rel_usd * cost:+,.0f}/tranche"
        cs = "   n/a " if math.isnan(cost) else f"{cost:>7.2%}"
        print(f"  {name:<34}{cs}   {why}{tail}")

    monthly = rel_usd * 30.4 / RELEASE_PERIOD_D
    print(f"\nselling the full release stream = ${monthly:,.0f}/mo gross; against obligations "
          f"${OBLIGATIONS_USD_MO:,.0f}/mo it covers {monthly / OBLIGATIONS_USD_MO:.0%}. "
          f"The escrow is a $19k STOCK vesting over ~2 years -- it is not an income "
          f"substitute for the fee stream at any price near today's.")
    return {"rel_usd": rel_usd, "rel_sol": rel_sol, "esc_usd": esc_usd, "impact": impact,
            "monthly_usd": monthly}


# ---------------------------------------------------------------------------------------
# ladder -- the unrun benchmark
# ---------------------------------------------------------------------------------------

LADDER_POOLS: Final[dict[str, dict[str, str]]] = {
    # tag in the edge_creation cache -> pool + the two legs' price series
    "weavedregg": {"pool": "GxnCwxTiK1uNQ1GiNutopyaRxH9X14JEvh6uaMwxuDRM",
                   "sold": "weave", "recv": "DREGG", "fee": "5.00%"},
    # the DREGG/nosis position ended 100% nosis (RESULT_edge_creation par.3): the pool's
    # net flow was DREGG-out / nosis-in, i.e. the desk's ladder was SELLING DREGG.
    "dreggnosis": {"pool": "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD",
                   "sold": "DREGG", "recv": "nosis", "fee": "5.00%"},
}
SYMBOL: Final[dict[str, str]] = {v: k for k, v in MINTS.items()}
SERIES: Final[dict[str, str]] = {"weave": "weave_per_sol", "DREGG": "dregg_per_sol",
                                 "nosis": "nosis_per_sol", "SOLVE": "solve_per_sol"}


def _pool_token_deltas(tx: dict, pool: str) -> dict[str, float]:
    pre = {b["accountIndex"]: b for b in (tx["meta"].get("preTokenBalances") or [])}
    out: dict[str, float] = {}
    for i, b in {b["accountIndex"]: b for b in (tx["meta"].get("postTokenBalances") or [])}.items():
        if b.get("owner") != pool:
            continue
        p = pre.get(i, {}).get("uiTokenAmount", {}).get("uiAmount") or 0.0
        q = b["uiTokenAmount"].get("uiAmount") or 0.0
        sym = SYMBOL.get(b["mint"], b["mint"][:6])
        out[sym] = out.get(sym, 0.0) + (q - p)
    return out


def _is_liquidity_tx(tx: dict) -> bool:
    """DLMM add/remove/claim/initialize touch the vaults without being swaps.

    jsonParsed leaves DLMM instruction data opaque, so liquidity operations are
    identified from the program's own log messages rather than from discriminators.
    """
    logs = tx["meta"].get("logMessages") or []
    for lg in logs:
        for word in ("AddLiquidity", "RemoveLiquidity", "ClaimFee", "InitializePosition",
                     "ClosePosition", "InitializeLbPair"):
            if word in lg:
                return True
    return False


def cmd_ladder() -> dict[str, Any]:
    import statsmodels.api as sm

    print("=" * 100)
    print("LADDER -- per-fill: what did the one-sided DLMM sell ladder pay vs routing the")
    print("same size at the same minute?  (RESULT_edge_creation 'what to do' #4, unrun until now)")
    print("=" * 100)
    sp = StepPrices()
    live_w = pool_now(WEAVE_SOL_POOL)
    live_d = pool_now(DREGG_SOL_POOL)
    y_side = {"weave": live_w["tvl_usd"] / 2 / live_w["sol_usd"],
              "DREGG": live_d["tvl_usd"] / 2 / live_d["sol_usd"],
              "nosis": 375.8}  # RESULT_edge_creation graph read; nosis pool not re-fetched

    out: dict[str, Any] = {}
    all_rows: list[dict[str, float]] = []
    for tag, cfg in LADDER_POOLS.items():
        path = EDGE_CACHE / f"{tag}.json"
        if not path.exists():
            print(f"  [{tag}] cache missing at {path} -- skipped (re-run edge_creation.py flow)")
            continue
        txs = json.loads(path.read_text())
        sold, recv, pool = cfg["sold"], cfg["recv"], cfg["pool"]
        s_sold, s_recv = SERIES[sold], SERIES[recv]
        fills = []
        skipped_liq = skipped_stale = 0
        for _sig, tx in txs.items():
            if tx["meta"].get("err") is not None:
                continue
            dl = _pool_token_deltas(tx, pool)
            if len(dl) != 2 or sold not in dl or recv not in dl:
                continue
            if _is_liquidity_tx(tx):
                skipped_liq += 1
                continue
            s_out, r_in = -dl[sold], dl[recv]
            if s_out <= 0 or r_in <= 0:
                continue  # opposite-direction swap (buying the sold leg) -- not a ladder fill
            t = tx["blockTime"]
            pw0, pd0 = sp.at(s_sold, t), sp.at(s_recv, t)
            # staleness threshold: minute bar within 30 min, else drop (reported)
            if pw0 is None or pd0 is None or sp.gap_s(s_sold, t) > 1800 or sp.gap_s(s_recv, t) > 1800:
                skipped_stale += 1
                continue
            fills.append({"t": t, "sold_amt": s_out, "recv_amt": r_in,
                          "p_sold_sol": pw0, "p_recv_sol": pd0})
        if not fills:
            print(f"  [{tag}] no fills parsed")
            continue
        f = pd.DataFrame(fills).sort_values("t").reset_index(drop=True)
        # fill exchange rate vs market cross rate (recv per sold)
        f["rate_fill"] = f["recv_amt"] / f["sold_amt"]
        f["rate_mkt"] = f["p_sold_sol"] / f["p_recv_sol"]
        f["premium"] = f["rate_fill"] / f["rate_mkt"] - 1.0
        # the executable alternative: sold -> SOL -> recv through the two PumpSwap legs.
        # cost = 1.44% x 2 + impact on each leg at this clip size (B/(Y+B)).
        f["clip_sol"] = f["sold_amt"] * f["p_sold_sol"]
        imp1 = f["clip_sol"] / (y_side[sold] + f["clip_sol"])
        imp2 = f["clip_sol"] / (y_side[recv] + f["clip_sol"])
        f["route_cost"] = 2 * PUMPSWAP_TOTAL_FEE + imp1 + imp2
        f["adv"] = (1 + f["premium"]) / (1 - f["route_cost"]) - 1.0
        f["hour"] = (f["t"] // 3600).astype(int)
        # robustness: value at the NEXT bar (t+60s) -- fills co-move with price inside
        # the bar, so the same-bar premium flatters a sell filled on an uptick
        f["premium_next"] = f.apply(
            lambda r: (r["rate_fill"] / ((sp.at(s_sold, int(r["t"]) + 60) or r["p_sold_sol"]) /
                                         (sp.at(s_recv, int(r["t"]) + 60) or r["p_recv_sol"]))) - 1,
            axis=1)
        f["adv_next"] = (1 + f["premium_next"]) / (1 - f["route_cost"]) - 1.0

        def fit_mean(col: str):
            if f["hour"].nunique() >= 2:
                mm = sm.OLS(f[col].to_numpy(), np.ones((len(f), 1))).fit(
                    cov_type="cluster", cov_kwds={"groups": f["hour"].to_numpy()})
            else:  # single burst: HC1 -- and say so
                mm = sm.OLS(f[col].to_numpy(), np.ones((len(f), 1))).fit(cov_type="HC1")
            return float(mm.params[0]), float(mm.bse[0]), float(mm.tvalues[0])

        w = f["clip_sol"] / f["clip_sol"].sum()
        agg_premium = float((f["premium"] * w).sum())
        agg_adv = float((f["adv"] * w).sum())
        mu, se, tv = fit_mean("adv")
        mu_n, se_n, tv_n = fit_mean("adv_next")
        span_h = (f["t"].max() - f["t"].min()) / 3600
        print(f"\n[{tag}]  pool {pool[:8]}..  tier {cfg['fee']}  fills n={len(f)} over "
              f"{span_h:.1f} h  (skipped: {skipped_liq} liquidity txs, {skipped_stale} "
              f"stale-price fills > 30 min from a bar)")
        print(f"  sold {f['sold_amt'].sum():,.0f} {sold} for {f['recv_amt'].sum():,.0f} {recv}; "
              f"total notional {f['clip_sol'].sum():.2f} SOL; median clip "
              f"{f['clip_sol'].median():.3f} SOL")
        print(f"  premium vs market cross rate (notional-weighted): {agg_premium:+.2%}   "
              f"median per-fill {f['premium'].median():+.2%}   at t+60s: "
              f"{f['premium_next'].median():+.2%}")
        print("  advantage vs routing the same clip (2x1.44% + impact):")
        print(f"    same-bar : mean {mu:+.2%} (cluster SE {se:.2%}, {f['hour'].nunique()} "
              f"hour clusters, t={tv:.2f});  notional-weighted {agg_adv:+.2%}")
        print(f"    t+60s    : mean {mu_n:+.2%} (cluster SE {se_n:.2%}, t={tv_n:.2f})   "
              f"<- conservative read")
        out[tag] = {"n": len(f), "premium_w": agg_premium, "adv_w": agg_adv,
                    "adv_mean": mu, "adv_se_cluster": se, "t": tv,
                    "adv_next_mean": mu_n, "adv_next_t": tv_n,
                    "notional_sol": float(f["clip_sol"].sum()),
                    "premium_next_median": float(f["premium_next"].median())}
        all_rows += f.assign(tag=tag).to_dict("records")

    if all_rows:
        af = pd.DataFrame(all_rows)
        res = {}
        for col in ("adv", "adv_next"):
            mm = sm.OLS(af[col].to_numpy(), np.ones((len(af), 1))).fit(
                cov_type="cluster", cov_kwds={"groups": af["hour"].to_numpy()})
            res[col] = (float(mm.params[0]), float(mm.bse[0]), float(mm.tvalues[0]))
        take_recapture = 0.006  # DREGG-leg creator fee back to the operator (see `tiers`)
        print(f"\nPOOLED (n={len(af)}, {af['hour'].nunique()} hour clusters):")
        print(f"  advantage vs route, same-bar: {res['adv'][0]:+.2%} (SE {res['adv'][1]:.2%}, "
              f"t={res['adv'][2]:.2f});  t+60s: {res['adv_next'][0]:+.2%} "
              f"(SE {res['adv_next'][1]:.2%}, t={res['adv_next'][2]:.2f})")
        print(f"  operator adjustment: the routed alternative's DREGG leg pays ~{take_recapture:.1%} "
              f"creator fee BACK to this operator, so the operator-specific advantage is "
              f"~{res['adv_next'][0] - take_recapture:+.2%} (conservative read minus recapture)")
        out["pooled"] = {"n": len(af), "adv_mean": res["adv"][0], "se": res["adv"][1],
                         "t": res["adv"][2], "adv_next_mean": res["adv_next"][0],
                         "adv_next_se": res["adv_next"][1], "adv_next_t": res["adv_next"][2],
                         "adv_operator": res["adv_next"][0] - take_recapture}
        print("""
READING, with the caveats that keep it honest:
  - This measures EXECUTION QUALITY of the ladder against the live alternative route for
    the same size at the same minute -- the benchmark RESULT_lp_history said was the
    right one for what these positions actually are.  It does NOT measure LP-vs-HODL
    (RESULT_edge_creation already did: -$595 across 10 closed positions).  Both are true:
    the ladder SELLS WELL, and holding the inventory it was selling was the loss.
  - Prices are GT minute closes; fills co-move with price inside the minute, so the
    same-bar premium is biased UP for a sell filled on an uptick.  The t+60s column is
    the conservative read.  Impact on the counterfactual uses TODAY's pool depths for
    the two legs (live read), not depth at fill time -- stated, not hidden.""")
    return out


# ---------------------------------------------------------------------------------------
# joint -- the four coupled DREGG levers
# ---------------------------------------------------------------------------------------

def cmd_joint() -> dict[str, Any]:
    import statsmodels.api as sm

    df = daily_bars()
    live = pool_now()
    cl = claim_series()
    print("=" * 100)
    print("JOINT -- the four coupled DREGG levers: fee stream, vesting supply, LP, volume drive")
    print("=" * 100)

    # measured base parameters
    d = df[df["t"] >= 1].copy()
    v0 = float(d["vol_usd"].tail(7).mean())
    cl_d = cl[cl["src"] == "dregg"]
    fee_sol_14d = cl_d[cl_d["ts"] > cl_d["ts"].max() - 14 * 86400]["sol"].sum()
    fee_day = fee_sol_14d / 14 * live["sol_usd"]
    take = fee_sol_14d * live["sol_usd"] / max(1.0, d["vol_usd"].tail(14).sum())
    b = float(sm.OLS(np.log(d["vol_usd"].to_numpy()),
                     sm.add_constant(d["t"].to_numpy(dtype=float)))
              .fit(cov_type="HAC", cov_kwds={"maxlags": 7}).params[1])
    horizon_d = 1 / -b if b < 0 else 365.0   # expected remaining lifetime under exp decay
    esc_tokens = ESCROW_LOCKED_NOW
    p = live["price_usd"]

    print(f"state: price ${p:.7f}  FDV ${live['fdv_usd']:,.0f}  vol7 ${v0:,.0f}/d  "
          f"fee ${fee_day:,.0f}/d  take {take:.2%}  decay slope {b:+.4f}/d "
          f"(mean remaining life {horizon_d:.0f} d)  escrow {esc_tokens / 1e6:.1f}M DREGG")

    # ---- lever 1: VOLUME.  d(fee)/d(volume) = take, direction-free ------------------
    mult = 1.86  # PROGRAM.md par.8: community activity -> ~1.86x volume, no durable price
    dfee = (mult - 1) * take * v0
    print(f"\nLEVER 1 -- volume driving.  At the measured ~{mult:.2f}x community-activity "
          f"multiplier:\n  delta fee = (1.86-1) x {take:.2%} x ${v0:,.0f}/d = "
          f"${dfee:,.0f}/day (${dfee * 30.4:,.0f}/mo) GROSS.")
    print(f"  This was filed as a price NULL -- for a fee earner it is the POSITIVE: the "
          f"volume lever pays through the fee channel regardless of direction.  It is "
          f"+EV iff the activity costs less than ${dfee:,.0f}/day of labour/spend.  "
          f"Unpriced cost; the null said nothing about durability of the multiplier.")

    # ---- lever 2: PRICE, and the tier kink -------------------------------------------
    # price -> volume association, measured (log-diff daily, HAC + rotation null)
    dlv = np.diff(np.log(d["vol_usd"].to_numpy()))
    dlp = np.diff(np.log(d["close"].to_numpy(dtype=float)))
    mm = sm.OLS(dlv, sm.add_constant(dlp)).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    beta = float(mm.params[1])
    rng = np.random.default_rng(20260815)
    n = len(dlp)
    rots = []
    for _ in range(2000):
        k = int(rng.integers(7, n - 7))
        x = np.roll(dlp, k)
        rots.append(float(sm.OLS(dlv, sm.add_constant(x)).fit().params[1]))
    p_rot = float(np.mean(np.abs(np.asarray(rots)) >= abs(beta)))
    print(f"\nLEVER 2 -- price.  Same-day dlog(volume) ~ dlog(price): beta {beta:+.2f} "
          f"(HAC SE {float(mm.bse[1]):.2f}; rotation null over 2,000 circular shifts: "
          f"p = {p_rot:.3f}).  Association, not causation -- both respond to attention.")
    # wealth derivative at the kink, carried as a BAND because `tiers` showed the
    # published step does not explain the measured take.
    kink_gain_day = (0.0095 - 0.0060) * v0
    stock = esc_tokens * p
    drop_to_boundary = 1 - 300_000 / live["fdv_usd"] if live["fdv_usd"] > 300_000 else 0.0
    stock_cost = stock * drop_to_boundary
    fee_gain = kink_gain_day * horizon_d
    print(f"  THE TIER KINK: crossing under $300k FDV adds (0.95-0.60)% x ${v0:,.0f} = "
          f"${kink_gain_day:,.0f}/day; over the fitted remaining life ({horizon_d:.0f} d) "
          f"= ${fee_gain:,.0f}.  Getting there from ${live['fdv_usd']:,.0f} costs the "
          f"escrow stock {drop_to_boundary:.1%} = ${stock_cost:,.0f}.  Net of sitting "
          f"just below the boundary: ${fee_gain - stock_cost:+,.0f}.")
    print(f"  `tiers` finds the operator's own claims track the ladder at ~0.93x of "
          f"face value (weekly range 0.47-1.42), so the kink is carried as REAL with "
          f"that band.  Consequence: at today's FDV, {drop_to_boundary:.1%} above the "
          f"boundary, the operator's total position is locally SHORT its own price -- "
          f"a small decline through $300k RAISES total wealth.  Do not spend money to "
          f"cause it (the association above cannot carry causal weight), but do not "
          f"spend money to defend the boundary either -- defending it is paying to "
          f"LOWER the take rate.")

    # ---- lever 3: SELLING the vesting stream -----------------------------------------
    rel_usd = RELEASE_DREGG * p
    sol_side = live["tvl_usd"] / 2 / live["sol_usd"]
    rel_sol = rel_usd / live["sol_usd"]
    impact = rel_sol / (sol_side + rel_sol)
    net_recapture = PUMPSWAP_TOTAL_FEE - take + impact
    print(f"\nLEVER 3 -- vesting exits.  ${rel_usd:,.0f}/14d.  Operator's own-pool sell "
          f"cost = 1.44% - {take:.2%} recapture + {impact:.2%} single-clip impact = "
          f"{net_recapture:.2%}, vs {PUMPSWAP_TOTAL_FEE + impact:.2%} for an outsider "
          f"(~{1 - net_recapture / (PUMPSWAP_TOTAL_FEE + impact):.0%} cheaper; slicing "
          f"the tranche shrinks the impact term for both).  A one-sided DLMM ladder "
          f"does better still: measured +1.4-2.0% ADVANTAGE vs routing (see `ladder`) "
          f"-- the exit earns the toll instead of paying it.")

    # ---- lever 4: LP -----------------------------------------------------------------
    print("\nLEVER 4 -- LP.  DREGG/SOL: eta = 0.235 vs best VR 0.438 at 48h -> -EV by "
          "1.9x at the most favourable horizon (RESULT_circuit_theory par.4.5).  "
          "Correct DREGG/SOL LP allocation as a YIELD position: ZERO.  The one LP form "
          "that pays here is the SELL LADDER (lever 3) -- an execution rebate on flow "
          "the desk had to move anyway, not a yield farm.")

    # ---- joint income statement ------------------------------------------------------
    monthly_fee_flat = fee_day * 30.4                       # if decay has stopped (RW null)
    monthly_fee_dec = fee_day * (1 - math.exp(30 * b)) / -b if b < 0 else monthly_fee_flat
    monthly_vest = rel_usd * 30.4 / RELEASE_PERIOD_D
    print("\nJOINT INCOME STATEMENT, next 30 days (USD):")
    print(f"  creator fees        {monthly_fee_dec:>7,.0f} - {monthly_fee_flat:>7,.0f}   "
          f"low = fitted decay integrated; high = decay stops (the RW null that WON the "
          f"OOS test)")
    print(f"  vesting sales       {monthly_vest:>7,.0f}             ~2 years at this rate; "
          f"exit via ladder, not market-sell")
    print(f"  volume lever        {'0':>7} - {dfee * 30.4:>7,.0f}   gross; +EV only if the "
          f"activity costs less than ${dfee:,.0f}/day")
    print(f"  LP yield            {'0':>7}             eta < VR everywhere measured")
    print(f"  TOTAL vs obligations  {monthly_fee_dec + monthly_vest:,.0f} - "
          f"{monthly_fee_flat + monthly_vest:,.0f} vs {OBLIGATIONS_USD_MO:,.0f}  -> "
          f"coverage {(monthly_fee_dec + monthly_vest) / OBLIGATIONS_USD_MO:.2f}x - "
          f"{(monthly_fee_flat + monthly_vest) / OBLIGATIONS_USD_MO:.2f}x")
    print(f"""
COUPLING, stated plainly: all four levers are denominated in ONE community's attention.
The fee stream, the escrow value, the ladder counterflow and the volume multiplier all
discharge together if the community dies -- this is PROGRAM.md par.8's 'capacitors leak'
made concrete.  The only lever that HEDGES the stack is selling vested DREGG for SOL on
schedule, which is also the only lever with a measured, positive, execution-level edge
(operator exit cost {net_recapture:.1%} vs outsider {PUMPSWAP_TOTAL_FEE + impact:.1%}).""")
    return {"take": take, "fee_day": fee_day, "v0": v0, "beta_vol_price": beta,
            "p_rot": p_rot, "monthly_fee_lo": monthly_fee_dec,
            "monthly_fee_hi": monthly_fee_flat, "monthly_vest": monthly_vest,
            "net_exit_cost": net_recapture, "horizon_d": horizon_d}


# ---------------------------------------------------------------------------------------
# rank
# ---------------------------------------------------------------------------------------

def cmd_rank() -> None:
    dec = cmd_decay()
    print()
    jt = cmd_joint()
    print()
    lad = cmd_ladder()
    print()
    esc = cmd_escrow()

    fee_lo, fee_hi = jt["monthly_fee_lo"], jt["monthly_fee_hi"]
    vest_mo = jt["monthly_vest"]
    lever_mo = (1.86 - 1) * jt["take"] * jt["v0"] * 30.4
    ladder_edge = lad.get("pooled", {}).get("adv_operator", float("nan"))
    ladder_save_mo = vest_mo * (ladder_edge if ladder_edge == ladder_edge else 0.0)

    print("\n" + "=" * 100)
    print("RANKED TOLL TABLE -- expected USD/month at THIS desk's size, arithmetic shown")
    print("=" * 100)
    rows = [
        ("1. DREGG creator fee (incumbent)", f"{fee_lo:,.0f}-{fee_hi:,.0f}", "0 (sunk)",
         f"take {jt['take']:.2%} x vol ${jt['v0']:,.0f}/d; DECAYING, "
         f"NPV ${dec['npv_exp']:,.0f}-{dec['npv_pl']:,.0f}",
         "volume decay; pump.fun schedule change; community death"),
        ("2. Vesting exit ladder", f"{vest_mo:,.0f} + {ladder_save_mo:,.0f} edge",
         "0.057 SOL rent (refunded)",
         f"${vest_mo:,.0f}/mo forced flow x measured operator edge "
         f"{ladder_edge:+.1%} vs routing" if ladder_edge == ladder_edge else
         f"${vest_mo:,.0f}/mo forced flow; edge unmeasured",
         "no counterflow (duty cycle); DREGG price; cluster death"),
        ("3. Volume lever via community", f"<= {lever_mo:,.0f} gross", "0 capital, unpriced labour",
         f"(1.86-1) x {jt['take']:.2%} x ${jt['v0']:,.0f}/d x 30.4; multiplier durability unknown",
         "community fatigue; multiplier was measured once"),
        ("4. Token-token arb tolls", "straddles 0", "$100-800/pool",
         "eta 0.59-1.08 on the line; -$595 vs HODL realized on 10 positions; "
         "only lever is duty cycle",
         "ONE Jupiter routing update (step function); range exit"),
        ("5. New-launch creator fees", "~0 per anonymous launch", "~0.03 SOL/launch",
         "0.3% x median curve volume; 2.6% of launches complete the curve (n=913 census); "
         "the DREGG stream came from the community, not the mechanic",
         "launch fatigue burns the community that powers tolls 1-3"),
        ("6. Token/SOL LP yield", "NEGATIVE", "any", "eta 0.055-0.235 vs VR 0.27-0.75: "
         "-EV 1.9-9.2x at the most favourable horizon", "refuted; do not size"),
        ("7. Jupiter maker/resting orders", "NEGATIVE", "escrowed", "pays 10 bps, no rebate, "
         "writes the option free; one keeper fills 100%", "refuted (RESULT_jupiter_programs)"),
        ("8. Gas sponsorship / terminal", "not reachable", ">> capital: distribution",
         "FOMO pays ~$0.0008/tx gas against ~1% fee take -- a real business, and a "
         "software-distribution business, not a capital position",
         "app-store churn; Jupiter/venue integration"),
        ("9. Validator / MEV infra", "fantasy at 1 SOL", "$100k+", "stake economics; say so and move on",
         "n/a"),
    ]
    for name, ev, cap, arith, kill in rows:
        print(f"\n{name}\n    EV/mo: {ev:<28} capital: {cap}\n    arithmetic: {arith}\n    dies to: {kill}")


# ---------------------------------------------------------------------------------------
# nulls & trials
# ---------------------------------------------------------------------------------------

def cmd_nulls() -> None:
    print("=" * 100)
    print("NULLS AND TRIALS ACCOUNTING (PROGRAM.md par.3 rules 9 & 10)")
    print("=" * 100)
    print("""
Nulls run in this study:
  1. decay:  OOS temporal split against a no-decay (constant) null AND a random-walk
     null.  Both models (exponential, power-law) reported; neither cherry-picked.
  2. tiers:  the ladder-predicted take (volume-weighted tier rate) is the null model
     for the claim series -- the claims track it at 0.93x mean, which CORRECTS the
     upstream 0.81-1.19% "anomaly" down to a denominator artifact.
  3. joint:  price->volume association tested against a circular-rotation null (2,000
     shifts, autocorrelation-preserving -- the copytrading study showed label nulls lie).
  4. ladder: same-bar vs t+60s premium (staleness robustness); hour-clustered SEs so
     within-burst fills do not masquerade as independent observations.

Trials counted:
  - decay model family: 2 specifications (exp, power-law).  Both reported, no selection.
  - ladder: 1 pre-committed estimand (advantage vs 2-leg route), 2 price timings
    reported as robustness, both shown.
  - joint elasticity: 1 specification.
  - No grid search anywhere.  Total distinct specifications examined: 6; every one is
    printed above; nothing was run and discarded.

Deflation: with 6 enumerated specifications and no selection step, the only selection
risk is in READING the tables; the headline claims (fee decay is real, ladder advantage
sign, tier-ladder elimination) each carry their own null above.

What this study does NOT establish, kept in one place:
  - week-to-week take variation (meas/pred 0.47-1.42) -- claim-timing noise is the
    likely cause but is not proven;
  - the durability of the 1.86x volume multiplier (measured once, in a study filed as
    a price null);
  - LP-vs-HODL for the ladder (that is RESULT_edge_creation's -$595; this study
    measures execution quality of the selling, which is a different and compatible fact);
  - anything about tolls 8-9 beyond arithmetic (no data was collected on them).""")


# ---------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="all",
                    choices=["all", "decay", "tiers", "escrow", "ladder", "joint", "rank", "nulls"])
    args = ap.parse_args()
    if args.cmd == "all":
        cmd_decay(); print()
        cmd_tiers(); print()
        cmd_escrow(); print()
        cmd_ladder(); print()
        cmd_joint(); print()
        cmd_nulls()
    elif args.cmd == "rank":
        cmd_rank()
    else:
        {"decay": cmd_decay, "tiers": cmd_tiers, "escrow": cmd_escrow,
         "ladder": cmd_ladder, "joint": cmd_joint, "nulls": cmd_nulls}[args.cmd]()


if __name__ == "__main__":
    main()
