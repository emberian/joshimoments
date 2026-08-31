#!/usr/bin/env python3
"""third_stratum -- membership, birth share, and B1 damage for the USDC-quoted stratum.

Registered in ``studies/REGISTRATION_third_stratum.md`` (+ Amendment 1) BEFORE any
census/share/B1 estimand was computed.

WHAT THE STRATUM TURNED OUT TO BE (predicate-validation ground truth, chain-decoded):
pump's QUOTE-MINT curve -- ``CreateEvent.quote_mint = USDC``, ``virtual_quote_reserves
= 4_292_000_000`` raw USDC ($4,292 = 30 SOL x $143.07: the USD-denominated clone of the
standard curve, initial marked cap $4,000), with the same integer mirrored into
``virtual_sol_reserves``. Supply exactly 1e15 at 6 decimals, ``is_mayhem_mode = false``
-- token-side indistinguishable from a standard birth, which is how it slid inside B1's
validated population. The flagged "~7x mcap overstatement" was a CURRENCY MISLABEL of
that field (4.292 read as SOL): in SOL terms the k_std reconstruction of these coins is
off by P_SOL/143.07 (~1.05x at $150), not 7x. The unit error is real; the magnitude was
not.

MEASUREMENT CHANNELS
--------------------
- BigQuery (registered channel): DEAD -- ``log_messages`` is ``[""]`` on every row of
  every sampled partition of the public dataset (2026-08-05/14/26/29); independently
  documented in ``scripts/pump_history.py``. Real spend before the gate caught it:
  ~$0.5 of the $20 authorization (probe queries; the $2.31 pull itself was never run).
- LOCAL corpus (Amendment 1): the raw bulk exports keep ALL token legs of matching txs,
  and a quote-curve create initializes the curve's USDC vault in the same transaction.
  Corpus predicate: the create tx (legs of the born mint net exactly +minted_raw)
  carries a USDC leg owned by the coin's ``curve_owner``. $0.
- Helius (verify): CreateEvent decoded from ``logMessages`` with invoke-stack
  attribution (``shitcoims_tape.recorder.attribute_program_data`` +
  ``shitcoims_intelligence.pump.decode_pump_event``) -- the same authoritative path the
  live fix uses in ``dregg_screen``.

Commands (in intended order):
    census            T1 identification + T2 share-by-day over both corpus windows
    screen            T3: B1's screen_seeded recomputed (as-shipped / excluded /
                      FX-corrected at $150 and $200), Clopper-Pearson CIs
    verify            Helius spot-check: chain CreateEvent vs corpus-leg membership
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

OUT = HERE / "data" / "third_stratum"
CORPUS = {
    "old": (HERE / "data" / "operator_crime", REPO / "state" / "bulk_pump" / "raw",
            [f"2026-08-{d:02d}" for d in range(5, 15)]),
    "fresh": (HERE / "data" / "operator_crime_fresh", REPO / "state" / "bulk_pump_fresh" / "raw",
              ["2026-08-26", "2026-08-27", "2026-08-28"]),
}

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"

SEED_STANDARD = 30_000_000_000
SEED_STRATUM3 = 4_292_000_000  # raw USDC = $4,292 (and mirrored into virtual_sol_reserves)
SOL_USD_IMPLIED = SEED_STRATUM3 / 1e6 / 30.0  # $143.07 -- the price where both curves agree

# RIP/collapse constants, verbatim from studies/operator_crime.py
RIP_INS_SHARE = 0.05
RIP_PEAK_SOL = 100.0
RIP_DRAWDOWN = 0.90


def _wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - h) / d, (c + h) / d)


def _clopper(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    from scipy.stats import beta

    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.isf(alpha / 2, k + 1, n - k))
    return (lo, hi)


def _census_window(name: str):
    """Per-day membership over one corpus window. Returns a per-mint frame."""

    import duckdb
    import pandas as pd

    dist_dir, raw_dir, days = CORPUS[name]
    birth = pd.read_parquet(
        dist_dir / "birth.parquet",
        columns=["mint", "birth_time", "birth_slot", "minted_raw", "decimals", "curve_owner"],
    )
    born = birth[(birth["minted_raw"] == 10**15) & (birth["decimals"] == 6)].copy()
    born["day"] = pd.to_datetime(born["birth_time"], unit="s").dt.date.astype(str)

    con = duckdb.connect()
    con.execute("SET threads=6; SET memory_limit='10GB'")
    frames = []
    for day in days:
        day_births = born[born["day"] == day][["mint", "birth_slot", "curve_owner"]]
        if not len(day_births):
            continue
        con.register("day_births", day_births)
        # One pass over the day's raw tape:
        #   deltas  = per-(tx, account, mint) net leg changes
        #   create  = the tx where the born mint's legs net exactly +1e15 in its birth slot
        #   foreign = every other-mint leg of that same transaction
        q = f"""
        WITH raw AS (
          SELECT signature, block_slot, pre, post
          FROM read_parquet('{raw_dir}/day={day}/*.parquet')
          WHERE block_slot IN (SELECT DISTINCT birth_slot FROM day_births)
        ),
        post_legs AS (
          SELECT signature, block_slot, p.mint AS leg_mint, p.owner AS owner,
                 p.account_index AS ai, CAST(p.amount AS HUGEINT) AS amt
          FROM raw, UNNEST(post) AS t(p)
        ),
        pre_legs AS (
          SELECT signature, p.mint AS leg_mint, p.account_index AS ai,
                 CAST(p.amount AS HUGEINT) AS amt
          FROM raw, UNNEST(pre) AS t(p)
        ),
        deltas AS (
          SELECT po.signature, po.block_slot, po.leg_mint, po.owner,
                 po.amt - COALESCE(pr.amt, 0) AS delta
          FROM post_legs po
          LEFT JOIN pre_legs pr
            ON pr.signature = po.signature AND pr.ai = po.ai AND pr.leg_mint = po.leg_mint
        ),
        create_tx AS (
          SELECT b.mint, b.curve_owner, d.signature
          FROM day_births b
          JOIN deltas d ON d.leg_mint = b.mint AND d.block_slot = b.birth_slot
          GROUP BY b.mint, b.curve_owner, d.signature
          HAVING SUM(d.delta) = 1000000000000000
        ),
        flegs AS (
          SELECT c.mint,
                 BOOL_OR(d.leg_mint = '{USDC_MINT}' AND d.owner = c.curve_owner) AS usdc_vault,
                 BOOL_OR(d.leg_mint = '{USDC_MINT}') AS usdc_any,
                 MAX(CASE WHEN d.leg_mint = '{USDC_MINT}' AND d.owner = c.curve_owner
                          THEN d.delta END) AS usdc_vault_delta,
                 LIST(DISTINCT d.leg_mint) FILTER (WHERE d.leg_mint <> c.mint) AS foreign_mints
          FROM create_tx c
          JOIN deltas d ON d.signature = c.signature
          GROUP BY c.mint
        )
        SELECT b.mint, f.mint IS NOT NULL AS create_found,
               COALESCE(f.usdc_vault, FALSE) AS usdc_vault,
               COALESCE(f.usdc_any, FALSE) AS usdc_any,
               f.usdc_vault_delta,
               f.foreign_mints
        FROM day_births b LEFT JOIN flegs f ON f.mint = b.mint
        """
        got = con.execute(q).fetchdf()
        got["day"] = day
        frames.append(got)
        con.unregister("day_births")
        print(f"    {name} {day}: {len(got):,} births, create found "
              f"{int(got['create_found'].sum()):,}, usdc_vault {int(got['usdc_vault'].sum()):,}",
              flush=True)
    out = pd.concat(frames, ignore_index=True)
    out["window"] = name
    return out


def cmd_census() -> int:
    import pandas as pd

    OUT.mkdir(parents=True, exist_ok=True)
    frames = [_census_window(name) for name in ("old", "fresh")]
    df = pd.concat(frames, ignore_index=True)
    df["stratum"] = df["usdc_vault"].map({True: "stratum3", False: "standard"})
    df.loc[~df["create_found"], "stratum"] = "unresolved"

    print("\n=== T1 identification ===")
    for name, g in df.groupby("window"):
        n = len(g)
        found = int(g["create_found"].sum())
        print(f"  {name}: births(1e15,6dec) {n:,}; create tx resolved {found:,} "
              f"({100 * found / n:.2f}%) -- T1 coverage gate >= 99.5%: "
              f"{'PASS' if found / n >= 0.995 else 'FAIL'}")
    fp_gauge = df[df["usdc_any"] & ~df["usdc_vault"]]
    print(f"  creates with a USDC leg NOT owned by the curve (excluded by predicate): "
          f"{len(fp_gauge):,}")
    fm = df[df["stratum"] == "stratum3"]["foreign_mints"].map(
        lambda v: ",".join(sorted(list(v))) if v is not None else "")
    print("  stratum3 foreign-mint sets:", dict(fm.value_counts().head(5)))

    print("\n=== T2 stratum-3 share of 1e15 births, by day ===")
    rows = []
    print(f"  {'window':<7}{'day':<12}{'births':>9}{'s3':>6}{'share':>9}{'  wilson95':>22}")
    for (w, day), g in df.groupby(["window", "day"]):
        res = g[g["create_found"]]
        k3, n = int((res["stratum"] == "stratum3").sum()), len(res)
        lo, hi = _wilson(k3, n)
        rows.append({"window": w, "day": day, "births_resolved": n, "stratum3": k3,
                     "share": k3 / n if n else 0.0, "share_lo": lo, "share_hi": hi,
                     "births_total": len(g)})
        print(f"  {w:<7}{day:<12}{n:>9,}{k3:>6,}{100 * k3 / max(n, 1):>8.3f}%   "
              f"[{100 * lo:.3f}%, {100 * hi:.3f}%]")
    for w in ("old", "fresh"):
        g = df[(df["window"] == w) & df["create_found"]]
        k3, n = int((g["stratum"] == "stratum3").sum()), len(g)
        lo, hi = _wilson(k3, n)
        print(f"  pooled {w}: {k3:,}/{n:,} = {100 * k3 / max(n, 1):.3f}% "
              f"[{100 * lo:.3f}%, {100 * hi:.3f}%]")

    art = {
        "coverage": {w: {"births": len(g), "resolved": int(g["create_found"].sum())}
                     for w, g in df.groupby("window")},
        "fp_gauge_usdc_not_vault": len(fp_gauge),
        "share_by_day": rows,
    }
    (OUT / "census.json").write_text(json.dumps(art, indent=1))
    df[["mint", "window", "day", "stratum", "usdc_vault_delta"]].to_parquet(
        OUT / "membership.parquet", index=False)
    print(f"\n  -> {OUT / 'census.json'}\n  -> {OUT / 'membership.parquet'}")
    return 0


def _screen_stats(te, y):
    gates = (
        (te["n_snipers"] <= 1)
        & (te["prior_rips"] == 0)
        & (te["prior_dumps"] == 0)
        & (te["sniper_prior_max"] == 0)
        & (te["dev_buy_share"] < 0.02)
    ).to_numpy()
    y = y.to_numpy().astype(int)
    adm, bad = int(gates.sum()), int(y[gates].sum())
    lo, hi = _clopper(adm - bad, adm)
    return {
        "n": len(te), "n_bad": int(y.sum()), "base_rate": float(y.mean()),
        "admitted": adm, "admitted_bad": bad,
        "clean_precision": float(1 - bad / adm) if adm else None,
        "clean_ci": [lo, hi], "admit_rate": float(adm / len(te)),
    }


def cmd_screen() -> int:
    import pandas as pd

    member = pd.read_parquet(OUT / "membership.parquet")
    s3 = set(member.loc[(member["window"] == "fresh") & (member["stratum"] == "stratum3"),
                        "mint"])

    df = pd.read_parquet(CORPUS["fresh"][0] / "combined" / "panel.parquet")
    te = df[df["deployer"].notna()].copy()
    te["date"] = pd.to_datetime(te["birth_time"], unit="s").dt.date.astype(str)
    te = te[te["date"] >= "2026-08-26"].copy()  # the exact B1 population
    te["is_s3"] = te["mint"].isin(s3)

    def outcomes(frame, fx: float | None):
        peak = frame["peak_mcap_sol"].copy()
        if fx is not None:
            # a stratum-3 pseudo-SOL mcap is really marked USD / 143.07; in SOL at
            # price P it is pseudo * (143.07 / P)
            peak = peak.where(~frame["is_s3"], peak * (SOL_USD_IMPLIED / fx))
        collapse = (peak >= RIP_PEAK_SOL) & (frame["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN)
        rip = (
            frame["t_dump"].notna()
            & (frame["ins_peak_share"] >= RIP_INS_SHARE)
            & (peak >= RIP_PEAK_SOL)
            & (frame["drawdown_from_peak"].fillna(0) >= RIP_DRAWDOWN)
        )
        return rip.astype(int), collapse.astype(int)

    variants = {}
    for key, frame, fx in (
        ("a_as_shipped", te, None),
        ("b_standard_only", te[~te["is_s3"]], None),
        ("c_fx150", te, 150.0),
        ("c_fx200", te, 200.0),
    ):
        rip, col = outcomes(frame, fx)
        variants[key] = {"is_rip": _screen_stats(frame, rip),
                         "collapse": _screen_stats(frame, col)}

    s3f = te[te["is_s3"]]
    s3row: dict = {"n": len(s3f)}
    if len(s3f):
        gates3 = (
            (s3f["n_snipers"] <= 1) & (s3f["prior_rips"] == 0) & (s3f["prior_dumps"] == 0)
            & (s3f["sniper_prior_max"] == 0) & (s3f["dev_buy_share"] < 0.02)
        ).to_numpy()
        rip_u, col_u = outcomes(s3f, None)
        rip_c, col_c = outcomes(s3f, 150.0)
        s3row.update({
            "clean_admitted": int(gates3.sum()),
            "collapse_k_std": int(col_u.sum()), "collapse_fx150": int(col_c.sum()),
            "rip_k_std": int(rip_u.sum()), "rip_fx150": int(rip_c.sum()),
            "admitted_bad_collapse_k_std": int(col_u.to_numpy()[gates3].sum()),
            "admitted_bad_collapse_fx150": int(col_c.to_numpy()[gates3].sum()),
        })

    print(f"\n=== T3 the B1 recompute (fresh window n = {len(te):,}; "
          f"stratum3 n = {int(te['is_s3'].sum()):,}) ===")
    for name, v in variants.items():
        for oname in ("is_rip", "collapse"):
            o = v[oname]
            print(f"  {name:<16} {oname:<9} n={o['n']:>6,} bad={o['n_bad']:>4} "
                  f"adm={o['admitted']:>5,} adm_bad={o['admitted_bad']} "
                  f"prec={100 * o['clean_precision']:.4f}% "
                  f"CI[{100 * o['clean_ci'][0]:.4f}%, {100 * o['clean_ci'][1]:.4f}%]")
    print(f"  stratum3 descriptive: {s3row}")
    claim = (variants["b_standard_only"]["collapse"]["clean_ci"][0] >= 0.9990
             and variants["c_fx150"]["collapse"]["clean_ci"][0] >= 0.9990
             and variants["c_fx200"]["collapse"]["clean_ci"][0] >= 0.9990)
    print(f"\n  RESTATEMENT RULE (>=99.90% collapse lower bound in (b) AND (c)): "
          f"{'HOLDS -- claim survives' if claim else 'FAILS -- restate the site/cards'}")
    art = {"variants": variants, "stratum3": s3row, "claim_survives": bool(claim),
           "sol_usd_implied": SOL_USD_IMPLIED,
           "population": "combined/panel.parquet, fresh window, deployer.notna()"}
    (OUT / "screen_recompute.json").write_text(json.dumps(art, indent=1))
    print(f"  -> {OUT / 'screen_recompute.json'}")
    return 0


def cmd_verify(n: int = 10) -> int:
    """Chain CreateEvent (invoke-stack attributed) vs corpus-leg membership, on a seeded
    sample of stratum-3 AND standard fresh-window mints. Read-only Helius."""

    import pandas as pd

    from shitcoims_intelligence.pump import AdvisoryPumpEvent, decode_pump_event
    from shitcoims_tape.recorder import attribute_program_data

    member = pd.read_parquet(OUT / "membership.parquet")
    fresh = member[member["window"] == "fresh"]
    s3 = fresh[fresh["stratum"] == "stratum3"]
    s3 = s3.sample(min(n, len(s3)), random_state=20260829)
    std = fresh[fresh["stratum"] == "standard"].sample(n, random_state=20260829)

    key = Path(os.path.expanduser("~/.helius-key")).read_text().strip()
    url = f"https://mainnet.helius-rpc.com/?api-key={key}"

    def rpc(method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params}).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read())["result"]

    ok = bad = 0
    for row in pd.concat([s3, std]).itertuples():
        # the create IS the mint's oldest signature (a mint cannot be touched before it
        # exists -- the fact dregg_screen/hydrate.py leans on)
        sigs, before = [], None
        for _ in range(40):
            page = rpc("getSignaturesForAddress",
                       [row.mint, {"limit": 1000, **({"before": before} if before else {})}]) or []
            if not page:
                break
            sigs = page
            if len(page) < 1000:
                break
            before = page[-1]["signature"]
        if not sigs:
            print(f"  {row.mint}  no signatures -- ANOMALY")
            bad += 1
            continue
        # The create is the oldest SUCCESSFUL signature: a losing same-slot sniper race
        # can list a FAILED tx older than the create (seen live: mint AaoWrw4w...,
        # birth slot 442127479), and the registration pins membership to err IS NULL.
        # Walk from the oldest end, skip errs, and accept the first tx that actually
        # carries this mint's CreateEvent (at most 5 fetches).
        ce = att = None
        candidates = [s for s in reversed(sigs) if s.get("err") is None][:5]
        for cand in candidates:
            tx = rpc("getTransaction", [cand["signature"],
                                        {"encoding": "json", "maxSupportedTransactionVersion": 0}])
            logs = (tx.get("meta") or {}).get("logMessages") or []
            att = attribute_program_data(logs)
            for e in att.entries:
                if e.program_id != PUMP_PROGRAM:
                    continue
                got = decode_pump_event(program_id=PUMP_PROGRAM, data=e.payload)
                if isinstance(got, AdvisoryPumpEvent) and got.event_name == "CreateEvent" \
                        and str(got.fields["mint"]) == row.mint:
                    ce = got
                    break
            if ce is not None:
                break
        if ce is None:
            print(f"  {row.mint}  corpus={row.stratum}  NO attributed CreateEvent in the "
                  f"{len(candidates)} oldest successful txs "
                  f"(truncated={att.truncated if att else '?'} "
                  f"unbalanced={att.unbalanced if att else '?'})")
            bad += 1
            continue
        f = ce.fields
        chain = ("stratum3" if int(f["virtual_sol_reserves"]) == SEED_STRATUM3
                 and str(f["quote_mint"]) == USDC_MINT and not f["is_mayhem_mode"]
                 else "standard" if int(f["virtual_sol_reserves"]) == SEED_STANDARD
                 and not f["is_mayhem_mode"] else "other")
        agree = chain == row.stratum
        ok += agree
        bad += not agree
        print(f"  {row.mint}  corpus={row.stratum:<9} chain={chain:<9} "
              f"vsol={int(f['virtual_sol_reserves']):,} vquote={int(f['virtual_quote_reserves']):,} "
              f"quote={str(f['quote_mint'])[:6]} {'OK' if agree else 'DISAGREE'}")
    print(f"\n  {ok} agree / {bad} disagree of {ok + bad}")
    return 0 if bad == 0 else 1


def main() -> int:
    cmds = {"census": cmd_census, "screen": cmd_screen, "verify": cmd_verify}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(f"usage: third_stratum.py {{{'|'.join(cmds)}}}", file=sys.stderr)
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
