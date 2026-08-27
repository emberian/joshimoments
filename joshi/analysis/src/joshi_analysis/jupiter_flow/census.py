"""The flow-model census — registration v1.4, the real signal in the registered pipe.

Same decision-time causal census as jupiter_backfill.census (fee 0.070*q(1-q), real
settlement labels, takeable price = last fill <= 60 s, first flagged setup per round):
ONLY the signal changes — the A-surface P(up) is replaced by a flow model fitted on the
Kraken tick tape's order-flow features, with a strict temporal holdout and the market's
own implied probability as the benchmark to beat. Everything quantitative below the
registration's granularity (loop order, tie-breaks) follows the prior census verbatim.

HONESTY (permanent): no leakage — features are strictly-before-t, models never see a
holdout row, tree counts come from a train-internal validation slice; fills are realistic
transacted prices never guaranteed size; the takeable price is a price approximation; the
Kraken reference is a ~2 bp venue-basis approximation of the Chainlink settlement stream;
fee floor beside every edge; the market price is a sophisticated benchmark and the
registered bar is to beat it OUT OF SAMPLE or report a real null.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from datetime import UTC, datetime
from pathlib import Path

from joshi_analysis.jupiter_backfill import reads
from joshi_analysis.jupiter_backfill.census import (
    QUOTE_STALE_S,
    Round,
    by_regime,
    fade_edges,
    last_fill_at,
    load_labeled_rounds,
    pnl_block,
    position_pnl,
)
from joshi_analysis.jupiter_backfill.legin import quantiles
from joshi_analysis.jupiter_base_rate.study import wilson_95
from joshi_analysis.jupiter_conditional import finesol
from joshi_analysis.jupiter_conditional.__main__ import run_gate
from joshi_analysis.jupiter_conditional.state import (
    REMAINING_FRACTIONS,
    decision_states,
    regime,
)
from joshi_analysis.jupiter_conditional.surface import brier_and_reliability

from . import features as feats
from . import hawkes
from . import model as mdl
from . import tape as tape_mod

STATE = Path("~/dev/joshi/state/prediction")
LEAD_MARGIN_S = 3600.0
SPLIT_FRACTION = 0.70
GBM_VAL_FRACTION = 0.85  # last 15% of TRAIN (by time) is the tree-count validation slice
FOLDS = ((0.4, 0.6), (0.6, 0.8), (0.8, 1.0))
THRESHOLDS = (0.0, 0.02, 0.05)
M0_MIN_CELL_N = 30
QUANTS = (0.10, 0.25, 0.50, 0.75, 0.90)


# ------------------------------------------------------------------ dataset
def joinable(rounds: list[Round], tape: tape_mod.FlowTape) -> list[Round]:
    lo, hi = tape.span
    return [r for r in rounds if r.open_s - LEAD_MARGIN_S >= lo and r.close_s <= hi]


def build_dataset(
    rounds: list[Round],
    series: finesol.StepSeries,
    tape: tape_mod.FlowTape,
    excitations: tuple,
    rule: str,
) -> tuple[list[tuple[Round, list[dict]]], dict]:
    """Per round: the decision-instant rows (features, market price, takeables); counted
    exclusions. A row's weight makes each round sum to 1 (registration v1.4)."""
    out = []
    counts = {"instants": 0, "stateAbsent": 0, "featureAbsent": 0, "marketAbsent": 0}
    for rnd in rounds:
        states = decision_states(series, float(rnd.open_s), float(rnd.close_s), rule)
        counts["stateAbsent"] += len(REMAINING_FRACTIONS) - len(states)
        rows = []
        for st in states:
            counts["instants"] += 1
            pf = feats.price_features(tape, st.t)
            if pf is None:
                counts["featureAbsent"] += 1
                continue
            ff = feats.flow_features(tape, excitations, st.t)
            x = {
                "rem_frac": st.remaining_fraction,
                "rem_s": st.remaining_s,
                "is_15m": 1.0 if rnd.horizon == "15m" else 0.0,
                "d_bps": st.d_bps,
                "gap_bps": st.gap_bps,
                **pf,
                **ff,
            }
            q_up = last_fill_at(rnd.rows, 0, st.t, QUOTE_STALE_S)
            q_down = last_fill_at(rnd.rows, 1, st.t, QUOTE_STALE_S)
            sides = [v for v in (q_up, None if q_down is None else 1.0 - q_down) if v is not None]
            p_mkt = sum(sides) / len(sides) if sides else None
            if p_mkt is None:
                counts["marketAbsent"] += 1
            rows.append(
                {
                    "t": st.t,
                    "remFrac": st.remaining_fraction,
                    "x": x,
                    "qUp": q_up,
                    "qDown": q_down,
                    "pMkt": p_mkt,
                    "labelUp": rnd.up_won,
                }
            )
        if rows:
            weight = 1.0 / len(rows)
            for r in rows:
                r["weight"] = weight
            out.append((rnd, rows))
    return out, counts


def temporal_split(
    rounds: list[Round], frac: float
) -> tuple[list[Round], list[Round], int, int]:
    """Cut at the start-time quantile; straddlers excluded from both sides (registered)."""
    starts = sorted(r.open_s for r in rounds)
    cut = starts[int(frac * (len(starts) - 1))]
    train = [r for r in rounds if r.close_s <= cut]
    hold = [r for r in rounds if r.open_s >= cut]
    return train, hold, cut, len(rounds) - len(train) - len(hold)


def flatten(dataset: list[tuple[Round, list[dict]]], keys: set[str]) -> list[dict]:
    return [row for rnd, rows in dataset if rnd.key in keys for row in rows]


def matrix(rows: list[dict], names: tuple[str, ...]) -> list[list[float]]:
    return [[r["x"][k] for k in names] for r in rows]


# ------------------------------------------------------------------ models
def fit_models(
    dataset: list[tuple[Round, list[dict]]],
    train_rounds: list[Round],
    names: tuple[str, ...],
) -> dict:
    """M1 on full TRAIN; M2 on the first 85% with the last 15% as its validation slice."""
    train_keys = {r.key for r in train_rounds}
    rows = flatten(dataset, train_keys)
    y = [int(r["labelUp"]) for r in rows]
    w = [r["weight"] for r in rows]
    m1 = mdl.fit_logistic(matrix(rows, names), y, w)
    fit_r, val_r, _, _ = temporal_split(train_rounds, GBM_VAL_FRACTION)
    fit_rows = flatten(dataset, {r.key for r in fit_r})
    val_rows = flatten(dataset, {r.key for r in val_r})
    m2 = mdl.fit_gbm(
        matrix(fit_rows, names),
        [int(r["labelUp"]) for r in fit_rows],
        [r["weight"] for r in fit_rows],
        matrix(val_rows, names),
        [int(r["labelUp"]) for r in val_rows],
        [r["weight"] for r in val_rows],
    )
    base = sum(wi * yi for wi, yi in zip(w, y, strict=True)) / sum(w)
    return {"m1": m1, "m2": m2, "baseRate": base, "names": names}


def fit_m0(dataset: list, train_rounds: list[Round], holdout_rows: list[dict]) -> dict:
    """Model-free conditional rates: P(up | ofi_60 tercile x sign(d) x rem_frac)."""
    train_rows = flatten(dataset, {r.key for r in train_rounds})
    vals = sorted(r["x"]["ofi_60"] for r in train_rows)
    n = len(vals)
    t1, t2 = vals[n // 3], vals[(2 * n) // 3]
    base = sum(r["labelUp"] for r in train_rows) / n

    def cell_key(row: dict) -> tuple[int, int, float]:
        v = row["x"]["ofi_60"]
        tercile = 0 if v <= t1 else (1 if v <= t2 else 2)
        return (tercile, 1 if row["x"]["d_bps"] >= 0 else -1, row["remFrac"])

    cells: dict[tuple, list[int]] = {}
    for row in train_rows:
        c = cells.setdefault(cell_key(row), [0, 0])
        c[0] += 1
        c[1] += row["labelUp"]
    table = []
    for (tercile, dsign, frac), (cn, up) in sorted(cells.items()):
        ci = wilson_95(up, cn)
        table.append(
            {
                "ofiTercile": tercile,
                "dSign": dsign,
                "remainingFraction": frac,
                "n": cn,
                "pUp": up / cn,
                "wilson95": list(ci) if ci else None,
                "thin": cn < M0_MIN_CELL_N,
            }
        )
    pairs = []
    for row in holdout_rows:
        c = cells.get(cell_key(row))
        p = c[1] / c[0] if c and c[0] >= M0_MIN_CELL_N else base
        pairs.append((p, row["labelUp"]))
    return {
        "terciles": {"ofi60Edges": [t1, t2]},
        "trainTable": table,
        "holdoutBrier": brier_and_reliability(pairs),
        "note": "descriptive; holdout scoring falls back to the train base rate on thin cells",
    }


# ------------------------------------------------------------------ evaluation
def _score(pairs: list[tuple[float, bool]]) -> dict:
    return brier_and_reliability(pairs)


def head_to_head(rows: list[dict], preds: dict[str, list[float]], base_rate: float) -> dict:
    """Model vs the market's own implied probability on IDENTICAL instants."""
    idx = [i for i, r in enumerate(rows) if r["pMkt"] is not None]
    out: dict = {"instants": len(idx), "instantsMarketAbsent": len(rows) - len(idx)}
    mkt_pairs = [(rows[i]["pMkt"], rows[i]["labelUp"]) for i in idx]
    out["market"] = _score(mkt_pairs)
    out["baselineConstantBrier"] = (
        sum((base_rate - rows[i]["labelUp"]) ** 2 for i in idx) / len(idx) if idx else None
    )
    for name, p in preds.items():
        out[name] = _score([(p[i], rows[i]["labelUp"]) for i in idx])
    per_frac = {}
    for frac in REMAINING_FRACTIONS:
        fidx = [i for i in idx if rows[i]["remFrac"] == frac]
        if not fidx:
            continue
        entry = {
            "n": len(fidx),
            "marketBrier": sum((rows[i]["pMkt"] - rows[i]["labelUp"]) ** 2 for i in fidx)
            / len(fidx),
        }
        for name, p in preds.items():
            entry[f"{name}Brier"] = (
                sum((p[i] - rows[i]["labelUp"]) ** 2 for i in fidx) / len(fidx)
            )
        per_frac[str(frac)] = entry
    out["perRemainingFraction"] = per_frac
    return out


def evaluate_holdout(
    dataset: list,
    holdout_rounds: list[Round],
    fits: dict[str, dict],
) -> tuple[dict, list[dict]]:
    """All registered holdout numbers: head-to-head per feature set, per horizon."""
    hold_keys = {r.key for r in holdout_rounds}
    tagged = [
        (rnd.horizon, row) for rnd, rows in dataset if rnd.key in hold_keys for row in rows
    ]
    rows = [row for _, row in tagged]
    base = fits["P+F"]["baseRate"]
    preds: dict[str, list[float]] = {}
    for set_name, fit in fits.items():
        x = matrix(rows, fit["names"])
        preds[f"logistic[{set_name}]"] = fit["m1"].predict(x)
        preds[f"gbm[{set_name}]"] = fit["m2"].predict(x)
    out = {
        "pooled": head_to_head(rows, preds, base),
        "allInstantsCalibration": {
            name: _score(list(zip(p, (r["labelUp"] for r in rows), strict=True)))
            for name, p in preds.items()
        },
    }
    for horizon in ("5m", "15m"):
        sel = [i for i, (h, _) in enumerate(tagged) if h == horizon]
        sub_rows = [rows[i] for i in sel]
        sub_preds = {name: [p[i] for i in sel] for name, p in preds.items()}
        out[horizon] = head_to_head(sub_rows, sub_preds, base)
    return out, rows


# ------------------------------------------------------------------ the census
def flow_fade(
    dataset: list,
    round_set: list[Round],
    fit: dict,
    which: str,
    threshold: float,
    round_regime: dict[str, str],
) -> dict:
    """The v1.3 near-boundary-fade mechanics with the flow model in the signal socket."""
    keys = {r.key for r in round_set}
    per_h: dict[str, dict] = {}
    by_round = [(rnd, rows) for rnd, rows in dataset if rnd.key in keys]
    model = fit[which]
    names = fit["names"]
    for horizon in ("5m", "15m", "pooled"):
        chosen = [
            (rnd, rows)
            for rnd, rows in by_round
            if horizon == "pooled" or rnd.horizon == horizon
        ]
        all_setups = []
        firsts = []
        no_quote = 0
        for rnd, rows in chosen:
            preds = model.predict(matrix(rows, names))
            setups = []
            for row, p_up in zip(rows, preds, strict=True):
                if row["qUp"] is None and row["qDown"] is None:
                    no_quote += 1
                    continue
                for e in fade_edges(p_up, row["qUp"], row["qDown"]):
                    if e["edgeNet"] > threshold:
                        setups.append({**e, "t": row["t"], "remFrac": row["remFrac"]})
            all_setups.extend(setups)
            if setups:
                first = min(setups, key=lambda s: (s["t"], -s["edgeNet"]))
                firsts.append(
                    (rnd, {**first, "pnl": position_pnl(first["q"], rnd.side_won(first["side"]))})
                )
        span_h = (
            (max(r.close_s for r, _ in chosen) - min(r.open_s for r, _ in chosen)) / 3600
            if chosen
            else 0.0
        )
        pnls = [f["pnl"] for _, f in firsts]
        wins = sum(1 for p in pnls if p > 0)
        ci = wilson_95(wins, len(pnls)) if pnls else None
        per_h[horizon] = {
            "scoredRounds": len(chosen),
            "spanHours": span_h,
            "noQuoteInstants": no_quote,
            "setupStates": len(all_setups),
            "roundsWithSetup": len(firsts),
            "setupsPerHour": len(firsts) / span_h if span_h else None,
            "edgeNetQuantiles": quantiles([s["edgeNet"] for s in all_setups], QUANTS),
            "takenPriceQuantiles": quantiles([f["q"] for _, f in firsts], QUANTS),
            "realized": pnl_block(pnls),
            "winRate": {"wins": wins, "n": len(pnls), "wilson95": list(ci) if ci else None}
            if pnls
            else None,
            "realizedByRegime": by_regime(
                [(round_regime[r.key], f["pnl"]) for r, f in firsts]
            ),
        }
    return per_h


# ------------------------------------------------------------------ hawkes finding
def hawkes_finding(tape: tape_mod.FlowTape, cut_s: float) -> dict:
    lo, _hi = tape.span
    train_times = tape.times[: _upper(tape.times, cut_s)]
    fit = hawkes.fit_branching(train_times, lo, cut_s)
    per_day = []
    day = None
    bucket: list[float] = []
    for t in tape.times:
        d = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")
        if d != day:
            if day is not None and len(bucket) > 1000:
                f = hawkes.fit_branching(bucket, bucket[0], bucket[-1])
                per_day.append({"day": day, "postTrainCut": bucket[0] >= cut_s, **f.as_dict()})
            day, bucket = d, []
        bucket.append(t)
    if day is not None and len(bucket) > 1000:
        f = hawkes.fit_branching(bucket, bucket[0], bucket[-1])
        per_day.append({"day": day, "postTrainCut": bucket[0] >= cut_s, **f.as_dict()})
    return {
        "trainSpan": fit.as_dict(),
        "perUtcDay": per_day,
        "reading": "branching ratio -> 1 reads critical/reflexive; DESCRIPTIVE finding, "
        "never a model feature (features use fixed 10 s / 60 s timescales)",
    }


def _upper(times: list[float], cut: float) -> int:
    return bisect_left(times, cut)


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(prog="joshi_analysis.jupiter_flow.census")
    ap.add_argument("--rounds", type=Path, nargs="+", required=True)
    ap.add_argument("--fine", type=Path, default=STATE / "fine")
    ap.add_argument("--collect", type=Path, default=STATE)
    ap.add_argument("--out-dir", type=Path, default=STATE / "study")
    ap.add_argument("--skip-hawkes", action="store_true", help="skip the EM fits (slow)")
    args = ap.parse_args()

    gate_report = run_gate(args.fine, args.collect)
    if gate_report["verdict"]["decision"] != "PROCEED":
        print("GATE SAYS STOP — the census would count the wrong thing. Not counting.")
        return
    rule = gate_report["verdict"]["rule"]
    series = finesol.load_kraken(args.fine)
    tape = tape_mod.load_kraken_flow(args.fine)
    excitations = feats.make_excitations(tape)
    rounds = joinable(load_labeled_rounds(args.rounds), tape)
    dataset, counts = build_dataset(rounds, series, tape, excitations, rule)
    covered = [rnd for rnd, _ in dataset]
    train_rounds, holdout_rounds, cut, straddlers = temporal_split(covered, SPLIT_FRACTION)
    round_regime = {r.key: regime(series, float(r.open_s)) or "absent" for r in covered}

    fits = {
        set_name: fit_models(dataset, train_rounds, names)
        for set_name, names in feats.FEATURE_SETS.items()
    }
    holdout_eval, holdout_rows = evaluate_holdout(dataset, holdout_rounds, fits)
    m0 = fit_m0(dataset, train_rounds, holdout_rows)

    pooled = holdout_eval["pooled"]
    gbm_pf = pooled["gbm[P+F]"]
    gbm_p = pooled["gbm[P]"]
    verdict = {
        "bar": "Brier(gbm[P+F]) < Brier(market) AND ECE(gbm[P+F]) <= 0.10 AND "
        "Brier(gbm[P+F]) < Brier(gbm[P]), pooled holdout head-to-head (registered v1.4)",
        "brierGbmFull": gbm_pf.get("brier"),
        "brierMarket": pooled["market"].get("brier"),
        "eceGbmFull": gbm_pf.get("ece"),
        "brierGbmPriceOnly": gbm_p.get("brier"),
        "beatsMarket": bool(gbm_pf.get("brier", 1) < pooled["market"].get("brier", 0)),
        "calibrated": bool(gbm_pf.get("ece", 1) <= 0.10),
        "flowAddsOverPrice": bool(gbm_pf.get("brier", 1) < gbm_p.get("brier", 0)),
    }
    verdict["flowClaimStands"] = bool(
        verdict["beatsMarket"] and verdict["calibrated"] and verdict["flowAddsOverPrice"]
    )

    folds_out = []
    for a, b in FOLDS:
        tr, _, cut_a, _ = temporal_split(covered, a)
        _, _, cut_b, _ = temporal_split(covered, b)
        test = [r for r in covered if r.open_s >= cut_a and r.close_s <= cut_b]
        if not tr or not test:
            continue
        fold_fits = {
            s: fit_models(dataset, tr, feats.FEATURE_SETS[s]) for s in ("P", "P+F")
        }
        test_rows = flatten(dataset, {r.key for r in test})
        fold_preds = {}
        for s, fit in fold_fits.items():
            x = matrix(test_rows, fit["names"])
            fold_preds[f"logistic[{s}]"] = fit["m1"].predict(x)
            fold_preds[f"gbm[{s}]"] = fit["m2"].predict(x)
        hh = head_to_head(test_rows, fold_preds, fold_fits["P+F"]["baseRate"])
        hh.pop("perRemainingFraction", None)
        folds_out.append(
            {"trainFraction": a, "testTo": b, "trainRounds": len(tr), "testRounds": len(test),
             **hh}
        )

    census_out = {}
    for thr in THRESHOLDS:
        census_out[f"threshold{thr:.2f}"] = {
            "gbm[P+F]": flow_fade(dataset, holdout_rounds, fits["P+F"], "m2", thr,
                                  round_regime),
            "logistic[P+F]": flow_fade(dataset, holdout_rounds, fits["P+F"], "m1", thr,
                                       round_regime),
        }
    in_sample_ref = flow_fade(dataset, train_rounds, fits["P+F"], "m2", 0.0, round_regime)

    hawkes_block = None if args.skip_hawkes else hawkes_finding(tape, float(cut))

    m1_pf = fits["P+F"]["m1"]
    result = {
        "contract": "joshi.jupiter_flow.census.v1",
        "registration": "joshi.jupiter_conditional.registration.v1 amendment v1.4",
        "rule": rule,
        "computedFrom": [str(p) for p in args.rounds],
        "gateLabels": gate_report["labels"],
        "population": {
            "joinableRounds": len(rounds),
            "coveredRounds": len(covered),
            "trainRounds": len(train_rounds),
            "holdoutRounds": len(holdout_rounds),
            "straddlersExcluded": straddlers,
            "cutUnix": cut,
            "instantCounts": counts,
        },
        "featureSets": {k: list(v) for k, v in feats.FEATURE_SETS.items()},
        "models": {
            "m0": "model-free conditional rates (ofi_60 tercile x sign(d) x rem_frac)",
            "m1": "logistic, L2=1.0, standardized clip +-8sd, IRLS<=50",
            "m2": "hist GBM, 32 bins, depth 2, lr 0.1, <=150 trees, min leaf w 40, "
            "leaf L2 1.0, tree count from last-15%-of-train validation",
            "sampleWeight": "1 / decision-instants-in-round (each round counts once)",
            "gbmBestIterations": {s: fits[s]["m2"].best_iteration for s in fits},
            "logisticCoefficients": {
                "P+F": dict(
                    zip(("intercept", *fits["P+F"]["names"]), m1_pf.beta, strict=True)
                )
            },
        },
        "modelFreeM0": m0,
        "holdout": holdout_eval,
        "walkForwardFolds": folds_out,
        "verdict": verdict,
        "census": {
            "signalSocket": "v1.3 near-boundary fade mechanics, flow model P(up) as signal",
            "holdoutOnly": census_out,
            "inSampleReference": {
                "NOT_THE_RESULT": "train rounds; rendered for the overfit gap only",
                "gbm[P+F]@0.00": in_sample_ref,
            },
        },
        "hawkes": hawkes_block,
        "feePerLeg": "0.070*q*(1-q) explicit taker fee; round-up-to-cent rider stated"
        " not applied; spread/overround riders on top",
        "caveats": [
            "fills = realistic transacted prices, NEVER guaranteed fillable size",
            "takeable price at t = last fill <= 60s old: a price approximation",
            "market implied p = mean of fresh {q_up, 1-q_down}: same approximation",
            "Kraken reference ~2bp venue basis vs the Chainlink settlement stream",
            "decision instants within a round are correlated; pooled scores say so and "
            "the per-remaining-fraction table is the decorrelated view",
            "every provider price/timestamp is a provider claim in declared units",
        ],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = reads.utc_stamp()
    out = args.out_dir / f"flow-census-{stamp}.json"
    out.write_text(json.dumps(result, indent=1))
    print(render(result))
    print(f"-> {out}")


def render(result: dict) -> str:
    pop = result["population"]
    v = result["verdict"]
    lines = [
        "FLOW-MODEL CENSUS (registration v1.4) — the real signal in the registered pipe",
        f"rounds: joinable {pop['joinableRounds']}, covered {pop['coveredRounds']} "
        f"(train {pop['trainRounds']} / holdout {pop['holdoutRounds']}, "
        f"straddlers {pop['straddlersExcluded']}), instants {pop['instantCounts']}",
        f"VERDICT: flowClaimStands={v['flowClaimStands']} — beatsMarket={v['beatsMarket']} "
        f"(gbm {v['brierGbmFull']:.4f} vs market {v['brierMarket']:.4f}), "
        f"calibrated={v['calibrated']} (ece {v['eceGbmFull']:.4f}), "
        f"flowAddsOverPrice={v['flowAddsOverPrice']} (price-only {v['brierGbmPriceOnly']:.4f})",
    ]
    pooled = result["holdout"]["pooled"]
    for name in sorted(k for k in pooled if k.startswith(("gbm", "logistic"))):
        s = pooled[name]
        if s.get("n"):
            lines.append(f"  holdout {name}: brier {s['brier']:.4f} ece {s['ece']:.4f}")
    lines.append(
        f"  holdout market: brier {pooled['market']['brier']:.4f} "
        f"ece {pooled['market']['ece']:.4f} (n={pooled['market']['n']})"
    )
    if result["hawkes"]:
        h = result["hawkes"]["trainSpan"]
        lines.append(
            f"hawkes (train span): branching {h['branchingRatio']:.3f} "
            f"@ timescale {h['timescaleS']:.1f}s, ll gain/event "
            f"{h['llGainPerEvent']:.3f} vs poisson"
        )
    c = result["census"]["holdoutOnly"]["threshold0.00"]["gbm[P+F]"]["pooled"]
    r = c["realized"]
    lines.append(
        f"census (holdout, thr 0): {c['roundsWithSetup']}/{c['scoredRounds']} rounds "
        f"with setup ({c['setupsPerHour']:.2f}/h over {c['spanHours']:.0f}h), "
        f"realized total {r.get('totalPnl', 0):+.2f} over n={r.get('n', 0)} "
        f"(mean {r.get('meanPnl', 0):+.4f})"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
