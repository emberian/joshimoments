#!/usr/bin/env python3
"""Four cheap statistical discriminators for the operator-crime study.

  (a) normalized compression distance between trade tapes  (same-deployer clustering)
  (b) Benford / first-significant-digit forensics on trade sizes
  (c) Lomb-Scargle periodograms on trade inter-arrivals     (scheduler detection)
  (d) size-vs-impact scaling exponent gamma                 (wash-trade signature)

Every p-value treats the COIN as the unit of resampling.  Every test ships with the
nulls it needs to be interpretable, and a null is a result.

Usage:
    uv run --group research python discriminators.py \
        --tape   .../dev/tape.parquet \
        --cohort .../dev/cohort.parquet \
        --out    .../discriminators \
        --tag    dev
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import zlib
from concurrent.futures import ProcessPoolExecutor

import duckdb
import numpy as np
from scipy import stats

# ----------------------------------------------------------------------------------
# constants -- pre-registered, do not tune
# ----------------------------------------------------------------------------------

SEED = 20260815

CURVE_K = 3.219e25          # 1.073e15 raw tok * 3.0e10 lamports
V_VIRT = 73_000_000_000_000  # virtual token reserve, raw

NCD_N = (256, 512)          # tape truncation lengths; coins must have >= N trades
NCD_PERM = 1999             # permutations of the deployer label

BENFORD_FIRST = 50          # first-N trades used for the first-digit distribution

LS_NFREQ = 400              # log-spaced frequencies
LS_PMIN = 2.0               # seconds -- Nyquist of 1-second block_time quantization
LS_PMAX = 600.0             # seconds
LS_NCAP = 512               # cap on trades per coin fed to the periodogram
LS_MINN = 64                # minimum trades to attempt a periodogram
LS_NULLS = 19               # realizations per null family -> resolution 1/20 = 0.05

IMPACT_H = (10, 25)         # permanent-impact horizons, in trades
BOOT_B = 2000               # clustered bootstrap reps

BY_Q = 0.10                 # Benjamini-Yekutieli target FDR

BENFORD = np.array([math.log10(1.0 + 1.0 / d) for d in range(1, 10)])


# ----------------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------------


def load(tape_path: str, cohort_path: str):
    """Transaction-level tape + cohort, joined and sorted into per-coin blocks.

    A row in tape.parquet is one token-account owner's balance delta.  A single
    transaction can carry several such legs (5.4% of curve transactions do, up to
    20 legs), all sharing one curve_bal_after.  The trade -- the thing a bot emits
    and the thing that moves the curve -- is the TRANSACTION, so we aggregate to
    (mint, block_slot, tx_index) with q = sum(delta_raw) over legs.  Chain-identity
    violation rate falls from 20.2% to 3.9% under that aggregation, which is the
    evidence that it is the right unit.
    """
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    df = con.sql(
        f"""
        select mint, block_slot, tx_index,
               any_value(block_time)::bigint      as bt,
               any_value(curve_bal_after)::double as cba,
               sum(delta_raw)::double             as q,
               count(*)::bigint                   as legs
        from read_parquet('{tape_path}')
        where curve_bal_after is not null
        group by 1, 2, 3
        order by mint, block_slot, tx_index
        """
    ).df()
    coh = con.sql(f"select * from read_parquet('{cohort_path}')").df()
    con.close()

    mints, codes = np.unique(df["mint"].to_numpy(), return_inverse=True)
    # per-coin contiguous blocks (df is sorted by mint first)
    starts = np.searchsorted(codes, np.arange(len(mints)), side="left")
    ends = np.searchsorted(codes, np.arange(len(mints)), side="right")

    tape = {
        "mints": mints,
        "starts": starts,
        "ends": ends,
        "bt": df["bt"].to_numpy(np.int64),
        "cba": df["cba"].to_numpy(np.float64),
        "q": df["q"].to_numpy(np.float64),
        "legs": df["legs"].to_numpy(np.int64),
    }
    coh = coh.set_index("mint").reindex(mints)
    return tape, coh


def coin_slices(tape):
    return [(int(s), int(e)) for s, e in zip(tape["starts"], tape["ends"], strict=False)]


# ----------------------------------------------------------------------------------
# shared statistics helpers
# ----------------------------------------------------------------------------------


def mannwhitney(a, b):
    """Two-sample rank test + Cliff's delta (rank-biserial), coin = unit."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 3 or len(b) < 3:
        return dict(n_a=len(a), n_b=len(b), p=float("nan"), cliffs_delta=float("nan"))
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    delta = 2.0 * u / (len(a) * len(b)) - 1.0  # Cliff's delta in [-1, 1]
    return dict(
        n_a=len(a),
        n_b=len(b),
        mean_a=float(a.mean()),
        mean_b=float(b.mean()),
        median_a=float(np.median(a)),
        median_b=float(np.median(b)),
        p=float(p),
        cliffs_delta=float(delta),
    )


def fisher2x2(a, b, c, d):
    """a=flag&group1, b=noflag&group1, c=flag&group2, d=noflag&group2."""
    odds, p = stats.fisher_exact([[a, b], [c, d]])
    r1 = a / (a + b) if (a + b) else float("nan")
    r2 = c / (c + d) if (c + d) else float("nan")
    return dict(
        table=[[int(a), int(b)], [int(c), int(d)]],
        rate_g1=float(r1),
        rate_g2=float(r2),
        rate_ratio=float(r1 / r2) if r2 else float("nan"),
        odds_ratio=float(odds),
        p=float(p),
    )


def by_fdr(pvals, q=BY_Q):
    """Benjamini-Yekutieli step-up.  Returns boolean survival mask (input order)."""
    p = np.asarray(pvals, float)
    m = len(p)
    cm = float(np.sum(1.0 / np.arange(1, m + 1)))
    order = np.argsort(p)
    thresh = (np.arange(1, m + 1) * q) / (m * cm)
    passed = p[order] <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    keep = np.zeros(m, bool)
    if k:
        keep[order[:k]] = True
    return keep, cm, thresh[np.argsort(order)]


# ----------------------------------------------------------------------------------
# (a) normalized compression distance
# ----------------------------------------------------------------------------------
#
# SERIALIZATION (stated exactly, this is the deliverable):
#   For each coin, take its curve transactions in chain order (block_slot, tx_index),
#   truncate to the first N.  Emit exactly 3 ASCII bytes per trade:
#       byte 0  direction   'B' if q > 0 else 'S'                     (2 symbols)
#       byte 1  size        chr(65 + min(63, floor(log2(|q|))))       (64 symbols)
#       byte 2  gap         chr(97 + min(25, floor(log2(1 + dt_s))))  (26 symbols)
#                           dt_s = block_time gap to the previous trade; 0 for the first
#   No wallet address, no mint, no absolute time appears in the string.  Every string
#   is exactly 3N bytes, so length cannot drive NCD; coins with fewer than N trades are
#   excluded rather than padded.
#
#   C = len(zlib.compress(s, level=9)).  zlib window is 32 KiB, well above 2 * 3N, so
#   the concatenation is fully cross-referenceable.
#   NCD(x, y) = (C(xy) - min(C(x), C(y))) / max(C(x), C(y))

_SIZE_SYM = np.array([chr(65 + i) for i in range(64)])
_GAP_SYM = np.array([chr(97 + i) for i in range(26)])


def serialize(q, bt, n, shuffle_rng=None):
    q = q[:n]
    bt = bt[:n]
    dt = np.diff(bt, prepend=bt[0])
    aq = np.abs(q)
    size_b = np.minimum(63, np.floor(np.log2(np.maximum(aq, 1.0)))).astype(int)
    gap_b = np.minimum(25, np.floor(np.log2(1.0 + np.maximum(dt, 0)))).astype(int)
    dir_b = np.where(q > 0, "B", "S")
    if shuffle_rng is not None:
        # NULL 2: destroy the sequence, preserve the multiset of (dir, size, gap) triples
        # of the SAME first-n trades, so the two strings differ only in trade order.
        perm = shuffle_rng.permutation(len(q))
        dir_b, size_b, gap_b = dir_b[perm], size_b[perm], gap_b[perm]
    out = np.char.add(np.char.add(dir_b, _SIZE_SYM[size_b]), _GAP_SYM[gap_b])
    return "".join(out).encode("ascii")


def _ncd_rows(args):
    lo, hi, blobs, csizes = args
    out = []
    for i in range(lo, hi):
        bi, ci = blobs[i], csizes[i]
        row = np.zeros(len(blobs), np.float32)
        for j in range(i + 1, len(blobs)):
            cxy = len(zlib.compress(bi + blobs[j], 9))
            cj = csizes[j]
            row[j] = (cxy - min(ci, cj)) / max(ci, cj)
        out.append((i, row))
    return out


def ncd_matrix(blobs, workers):
    csizes = [len(zlib.compress(b, 9)) for b in blobs]
    n = len(blobs)
    # balance chunks: row i does n-i-1 compressions
    bounds, acc, total = [0], 0, n * (n - 1) / 2
    per = total / (workers * 4)
    for i in range(n):
        acc += n - i - 1
        if acc >= per:
            bounds.append(i + 1)
            acc = 0
    if bounds[-1] != n:
        bounds.append(n)
    jobs = [(bounds[k], bounds[k + 1], blobs, csizes) for k in range(len(bounds) - 1)]
    D = np.zeros((n, n), np.float32)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_ncd_rows, jobs):
            for i, row in res:
                D[i] = row
    D = D + D.T
    return D


def _group_pair_mean(D, groups):
    """Mean of D over unordered same-group pairs."""
    tot, cnt = 0.0, 0
    for idx in groups:
        if len(idx) < 2:
            continue
        sub = D[np.ix_(idx, idx)]
        tot += float(sub.sum()) / 2.0
        cnt += len(idx) * (len(idx) - 1) // 2
    return tot / cnt if cnt else float("nan"), cnt


def test_a(tape, coh, workers, out):
    rng = np.random.default_rng(SEED)
    slices = coin_slices(tape)
    res = {}
    for n in NCD_N:
        keep = [
            i
            for i in range(len(slices))
            if (slices[i][1] - slices[i][0]) >= n and coh["arm"].iloc[i] == "serial"
        ]
        dep = coh["deployer"].to_numpy()[keep]
        _, dcodes = np.unique(dep, return_inverse=True)
        groups = [np.nonzero(dcodes == g)[0] for g in range(dcodes.max() + 1)]
        gsizes = sorted((len(g) for g in groups), reverse=True)

        Dstore = {}
        for label, shuf in (("real", False), ("shuffled_tape", True)):
            t0 = time.time()
            blobs = []
            for i in keep:
                s, e = slices[i]
                r = np.random.default_rng(SEED + i) if shuf else None
                blobs.append(serialize(tape["q"][s:e], tape["bt"][s:e], n, r))
            assert all(len(b) == 3 * n for b in blobs)
            D = ncd_matrix(blobs, workers)
            Dstore[label] = D

            same, n_same = _group_pair_mean(D, groups)
            iu = np.triu_indices(len(keep), 1)
            allv = D[iu]
            n_all = len(allv)
            n_diff = n_all - n_same
            diff = (float(allv.sum()) - same * n_same) / n_diff
            sd = float(allv.std())

            # permutation: shuffle deployer labels across coins (coin = permuted unit)
            perm_stats = np.empty(NCD_PERM)
            idxs = np.arange(len(keep))
            for b in range(NCD_PERM):
                p = rng.permutation(idxs)
                pg = [p[g] for g in groups]  # preserves group-size structure
                perm_stats[b] = _group_pair_mean(D, pg)[0]
            # one-sided: same-deployer tapes are MORE similar => LOWER NCD
            pval = (1 + int(np.sum(perm_stats <= same))) / (NCD_PERM + 1)

            res[f"N{n}_{label}"] = dict(
                n_coins=len(keep),
                n_deployers=len(groups),
                deployer_group_sizes_top10=gsizes[:10],
                n_same_pairs=int(n_same),
                n_diff_pairs=int(n_diff),
                mean_ncd_same=float(same),
                mean_ncd_diff=float(diff),
                delta=float(same - diff),
                pooled_sd=sd,
                cohens_d=float((same - diff) / sd),
                perm_null_mean=float(perm_stats.mean()),
                perm_null_sd=float(perm_stats.std()),
                p_perm_one_sided_lower=float(pval),
                n_perm=NCD_PERM,
                secs=round(time.time() - t0, 1),
            )
            print(
                f"  [a] N={n:4d} {label:14s} same={same:.5f} diff={diff:.5f} "
                f"d={(same-diff)/sd:+.4f} p={pval:.4f}  ({time.time()-t0:.0f}s)"
            )

        # SEQUENCE RESIDUAL: is same-deployer clustering STRONGER on real tapes than on
        # tapes with the identical (dir, size, gap) multiset in shuffled order?  Both
        # matrices are fixed; one shared permutation of the deployer labels drives both,
        # so the difference of standardized effects is testable directly.
        def _std_gap(D, gs):
            sm, ns = _group_pair_mean(D, gs)
            av = D[np.triu_indices(D.shape[0], 1)]
            df = (float(av.sum()) - sm * ns) / (len(av) - ns)
            return (sm - df) / float(av.std())

        obs_dd = _std_gap(Dstore["real"], groups) - _std_gap(Dstore["shuffled_tape"], groups)
        null_dd = np.empty(NCD_PERM)
        idxs = np.arange(len(keep))
        for b in range(NCD_PERM):
            p = rng.permutation(idxs)
            pg = [p[g] for g in groups]
            null_dd[b] = _std_gap(Dstore["real"], pg) - _std_gap(Dstore["shuffled_tape"], pg)
        res[f"N{n}_sequence_residual"] = dict(
            cohens_d_real=float(_std_gap(Dstore["real"], groups)),
            cohens_d_shuffled=float(_std_gap(Dstore["shuffled_tape"], groups)),
            frac_of_effect_surviving_shuffle=float(
                _std_gap(Dstore["shuffled_tape"], groups) / _std_gap(Dstore["real"], groups)
            ),
            delta_d=float(obs_dd),
            p_perm=float((1 + int(np.sum(null_dd <= obs_dd))) / (NCD_PERM + 1)),
        )
        print(f"  [a] N={n:4d} sequence-residual: d_real - d_shuf = {obs_dd:+.4f} "
              f"p={res[f'N{n}_sequence_residual']['p_perm']:.4f} "
              f"surviving={res[f'N{n}_sequence_residual']['frac_of_effect_surviving_shuffle']:.3f}")
        del Dstore
    res["serialization"] = (
        "3 ASCII bytes/trade in chain order: dir in {B,S}; "
        "chr(65+min(63,floor(log2(|q|)))); chr(97+min(25,floor(log2(1+dt_s)))). "
        "Truncated to first N; coins with <N trades excluded so all strings are 3N bytes. "
        "C = len(zlib.compress(s, level=9)); NCD = (C(xy)-min)/max."
    )
    return res


# ----------------------------------------------------------------------------------
# (b) Benford / first significant digit
# ----------------------------------------------------------------------------------


def _fsd(vals):
    """First significant digit of positive integers held as float64 (exact < 2^53)."""
    v = np.abs(vals)
    v = v[v > 0]
    d = np.floor(v / np.power(10.0, np.floor(np.log10(v)))).astype(int)
    return np.clip(d, 1, 9)


def test_b(tape, coh, out):
    slices = coin_slices(tape)
    n_coins = len(slices)
    mad = np.full(n_coins, np.nan)
    chi2 = np.full(n_coins, np.nan)
    n_distinct = np.full(n_coins, np.nan)  # distinct |q| among the first 50 trades
    ambient_counts = np.zeros(9)
    ambient_sol_counts = np.zeros(9)
    round_sol = 0
    round_sol_tot = 0
    n_used = 0
    for i, (s, e) in enumerate(slices):
        m = min(e - s, BENFORD_FIRST)
        if m < BENFORD_FIRST:
            continue
        q = tape["q"][s : s + m]
        d = _fsd(q)
        if len(d) < BENFORD_FIRST:
            continue
        n_distinct[i] = len(np.unique(np.abs(q)))
        cnt = np.bincount(d, minlength=10)[1:10].astype(float)
        obs = cnt / cnt.sum()
        mad[i] = float(np.mean(np.abs(obs - BENFORD)))
        exp = BENFORD * cnt.sum()
        chi2[i] = float(np.sum((cnt - exp) ** 2 / exp))
        ambient_counts += cnt
        n_used += 1
        # diagnostic: implied SOL amount, where round-number artifacts would live
        v_after = tape["cba"][s : s + m] + V_VIRT
        v_before = v_after + q
        lam = np.abs(CURVE_K / v_after - CURVE_K / v_before)
        lam = lam[np.isfinite(lam) & (lam > 0)]
        if len(lam):
            ambient_sol_counts += np.bincount(_fsd(lam), minlength=10)[1:10]
            sol = lam / 1e9
            # "round" == a multiple of 0.01 SOL to within 1e-6 SOL
            round_sol += int(np.sum(np.abs(sol * 100 - np.round(sol * 100)) < 1e-4))
            round_sol_tot += len(sol)

    amb = ambient_counts / ambient_counts.sum()
    amb_sol = ambient_sol_counts / ambient_sol_counts.sum()

    # second pass: MAD against the AMBIENT first-digit law, which is the reference the
    # brief actually cares about once the ambient turns out not to be Benford.
    mad_amb = np.full(n_coins, np.nan)
    for i, (s, e) in enumerate(slices):
        if (e - s) < BENFORD_FIRST:
            continue
        d = _fsd(tape["q"][s : s + BENFORD_FIRST])
        if len(d) < BENFORD_FIRST:
            continue
        obs = np.bincount(d, minlength=10)[1:10] / float(len(d))
        mad_amb[i] = float(np.mean(np.abs(obs - amb)))

    # finite-sample reference: what MAD does a coin get when its 50 digits really are
    # drawn from the ambient law?  Without this, "MAD = 0.044" has no scale.
    rng = np.random.default_rng(SEED)
    sim = rng.choice(9, size=(20000, BENFORD_FIRST), p=amb)
    simc = np.stack([(sim == k).sum(1) for k in range(9)], 1) / float(BENFORD_FIRST)
    mad_sim_b = np.abs(simc - BENFORD).mean(1)
    mad_sim_a = np.abs(simc - amb).mean(1)

    arm = coh["arm"].to_numpy()
    snip = coh["n_snipers"].to_numpy(float)
    dumped = coh["t_dump"].notna().to_numpy()
    snip_med = float(np.nanmedian(snip))

    contrasts = {
        "serial_vs_solo": mannwhitney(mad[arm == "serial"], mad[arm == "solo"]),
        "high_vs_low_snipers": mannwhitney(mad[snip > snip_med], mad[snip <= snip_med]),
        "dumped_vs_not": mannwhitney(mad[dumped], mad[~dumped]),
    }
    contrasts_ambient = {
        "serial_vs_solo": mannwhitney(mad_amb[arm == "serial"], mad_amb[arm == "solo"]),
        "high_vs_low_snipers": mannwhitney(mad_amb[snip > snip_med], mad_amb[snip <= snip_med]),
        "dumped_vs_not": mannwhitney(mad_amb[dumped], mad_amb[~dumped]),
    }
    # Is MAD just measuring how repetitive the first 50 trade sizes are?  A coin whose
    # early tape is 50 copies of the same sniper size has a degenerate digit histogram
    # and therefore a large MAD for reasons that have nothing to do with fabrication.
    fin = np.isfinite(mad) & np.isfinite(n_distinct)
    rho = float(stats.spearmanr(n_distinct[fin], mad[fin]).statistic)
    distinct_by_group = {
        g: dict(median=float(np.nanmedian(n_distinct[m])), mean=float(np.nanmean(n_distinct[m])))
        for g, m in {
            "serial": arm == "serial", "solo": arm == "solo",
            "high_snipers": snip > snip_med, "low_snipers": snip <= snip_med,
            "dumped": dumped, "not_dumped": ~dumped,
        }.items()
    }
    return dict(
        contrasts_vs_ambient_law=contrasts_ambient,
        repetition_diagnostic=dict(
            spearman_rho_ndistinct_vs_mad=rho,
            n_distinct_sizes_in_first50_by_group=distinct_by_group,
            note="MAD falls as the early tape becomes less repetitive; this is the "
                 "confound that has to be excluded before reading MAD as forensics.",
        ),
        mad_finite_sample_reference=dict(
            n_sim=20000,
            drawn_from="ambient token FSD law, 50 digits",
            vs_benford=dict(mean=float(mad_sim_b.mean()), p95=float(np.percentile(mad_sim_b, 95))),
            vs_ambient=dict(mean=float(mad_sim_a.mean()), p95=float(np.percentile(mad_sim_a, 95))),
        ),
        per_coin_mad_vs_ambient=dict(
            mean=float(np.nanmean(mad_amb)), median=float(np.nanmedian(mad_amb))
        ),
        n_coins_used=n_used,
        first_n_trades=BENFORD_FIRST,
        ambient_fsd_tokens=[float(x) for x in amb],
        benford_fsd=[float(x) for x in BENFORD],
        ambient_mad_vs_benford=float(np.mean(np.abs(amb - BENFORD))),
        ambient_fsd_implied_sol=[float(x) for x in amb_sol],
        ambient_sol_mad_vs_benford=float(np.mean(np.abs(amb_sol - BENFORD))),
        frac_trades_round_sol_to_0p01=float(round_sol / round_sol_tot) if round_sol_tot else None,
        per_coin_mad=dict(
            mean=float(np.nanmean(mad)),
            median=float(np.nanmedian(mad)),
            sd=float(np.nanstd(mad)),
        ),
        per_coin_chi2_median=float(np.nanmedian(chi2)),
        sniper_median_split=snip_med,
        contrasts=contrasts,
        _mad=mad,
    )


# ----------------------------------------------------------------------------------
# (c) Lomb-Scargle
# ----------------------------------------------------------------------------------


def ls_power(x, y, freqs):
    """Standard-normalized Lomb-Scargle power in [0,1] (astropy 'standard' convention).

    p(f) = [ YC'^2/CC' + YS'^2/SS' ] / sum(yhat^2), evaluated at the Scargle offset tau.
    FAP for a single frequency is (1-p)^((N-3)/2).
    """
    x = np.asarray(x, float)
    yh = np.asarray(y, float)
    yh = yh - yh.mean()
    yy = float(yh @ yh)
    if yy <= 0 or len(x) < 8:
        return np.zeros(len(freqs))
    w = 2.0 * np.pi * np.asarray(freqs, float)
    out = np.empty(len(w))
    CH = max(1, int(4_000_000 // max(len(x), 1)))  # frequency chunk
    for a in range(0, len(w), CH):
        wc = w[a : a + CH]
        wx = wc[:, None] * x[None, :]
        C = np.cos(wx)
        S = np.sin(wx)
        CC = np.einsum("ij,ij->i", C, C)
        SS = np.einsum("ij,ij->i", S, S)
        CS = np.einsum("ij,ij->i", C, S)
        YC = C @ yh
        YS = S @ yh
        tau2 = np.arctan2(2.0 * CS, CC - SS)  # = 2*w*tau
        ct = np.cos(0.5 * tau2)
        st = np.sin(0.5 * tau2)
        YCt = ct * YC + st * YS
        YSt = ct * YS - st * YC
        CCt = ct * ct * CC + 2 * ct * st * CS + st * st * SS
        SSt = ct * ct * SS - 2 * ct * st * CS + st * st * CC
        with np.errstate(divide="ignore", invalid="ignore"):
            p = (np.where(CCt > 1e-12, YCt**2 / CCt, 0.0) + np.where(SSt > 1e-12, YSt**2 / SSt, 0.0)) / yy
        out[a : a + CH] = np.nan_to_num(p, nan=0.0, posinf=0.0)
    return np.clip(out, 0.0, 1.0)


def _detrend(x, y):
    """Remove a linear trend in t.  Coin activity decays monotonically over a coin's
    life, and an untrended inter-arrival series puts all of its Lomb-Scargle power at
    the lowest frequency in the band -- that is a trend, not a scheduler."""
    A = np.stack([np.ones_like(x), x], 1)
    try:
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    except np.linalg.LinAlgError:
        return y - y.mean()
    return y - A @ beta


def _ls_coin(args):
    """Two variants x (real, rotation null, Poisson-matched null) for one coin.

    naive     : y = dt,                     f >= 2/T, periods [2, 600] s
    detrended : y = detrend(log1p(dt)),     f >= 5/T, periods [2, 300] s   <- primary

    Rotation null rotates the VALUE sequence and holds the sampling geometry x fixed,
    so the window function (and therefore the 1-second quantization comb) is identical
    between observation and null; only the ordering of the values is destroyed.
    Poisson null regenerates arrival times as a homogeneous Poisson process of the same
    rate and duration, quantized to whole seconds exactly as block_time is.
    """
    i, bt, freqs, seed = args
    rng = np.random.default_rng(seed)
    t = bt.astype(float)
    t = t - t[0]
    T = float(t[-1])
    n = len(t)
    NA = dict(obs=np.nan, f=np.nan, p_rot=np.nan, p_poi=np.nan, poimed=np.nan)
    res = {"i": i, "n": n, "T": T, "naive": dict(NA), "detrended": dict(NA)}
    if n < LS_MINN or T < 2.0 * LS_PMIN:
        return res
    dt = np.diff(t, prepend=t[0])

    for name, (ncyc, pmax) in (("naive", (2.0, 600.0)), ("detrended", (5.0, 300.0))):
        mask = (freqs >= (ncyc / T)) & (freqs >= 1.0 / pmax)
        if mask.sum() < 5:
            continue
        fr = freqs[mask]
        y = dt if name == "naive" else _detrend(t, np.log1p(dt))
        pw = ls_power(t, y, fr)
        obs = float(pw.max())
        rot = np.empty(LS_NULLS)
        for b in range(LS_NULLS):
            k = int(rng.integers(1, n))
            rot[b] = ls_power(t, np.roll(y, k), fr).max()
        poi = np.empty(LS_NULLS)
        for b in range(LS_NULLS):
            u = np.round(np.sort(rng.random(n) * T))  # SAME 1-second quantization
            d2 = np.diff(u, prepend=u[0])
            y2 = d2 if name == "naive" else _detrend(u, np.log1p(d2))
            poi[b] = ls_power(u, y2, fr).max()
        res[name] = dict(
            obs=obs,
            f=float(fr[int(np.argmax(pw))]),
            p_rot=(1 + int(np.sum(rot >= obs))) / (LS_NULLS + 1),
            p_poi=(1 + int(np.sum(poi >= obs))) / (LS_NULLS + 1),
            poimed=float(np.median(poi)),
        )
    return res


def test_c(tape, coh, workers, out):
    slices = coin_slices(tape)
    freqs = np.logspace(np.log10(1.0 / LS_PMAX), np.log10(1.0 / LS_PMIN), LS_NFREQ)
    jobs = []
    for i, (s, e) in enumerate(slices):
        bt = tape["bt"][s : min(e, s + LS_NCAP)]
        jobs.append((i, bt, freqs, SEED + 7919 * i))
    t0 = time.time()
    n_coins = len(slices)
    V = {v: {k: np.full(n_coins, np.nan) for k in ("obs", "f", "p_rot", "p_poi", "poimed")}
         for v in ("naive", "detrended")}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_ls_coin, jobs, chunksize=16):
            i = r["i"]
            for v in ("naive", "detrended"):
                for k in V[v]:
                    V[v][k][i] = r[v][k]
    print(f"  [c] periodograms done in {time.time()-t0:.0f}s")

    arm = coh["arm"].to_numpy()
    snip = coh["n_snipers"].to_numpy(float)
    dumped = coh["t_dump"].notna().to_numpy()
    snip_med = float(np.nanmedian(snip))
    dt_all = np.concatenate([np.diff(tape["bt"][s:e]) for s, e in slices])

    out_v = {}
    flags = {}
    for v in ("naive", "detrended"):
        obs, fat = V[v]["obs"], V[v]["f"]
        ok = np.isfinite(obs)
        line = ok & (V[v]["p_poi"] <= 1.0 / (LS_NULLS + 1))
        line_rot = ok & (V[v]["p_rot"] <= 1.0 / (LS_NULLS + 1))
        # PRIMARY flag: must beat BOTH nulls
        both = line & line_rot
        flags[v] = both

        def cell(g1, g2, fl=both, o=ok):
            return fisher2x2(int(np.sum(fl & g1 & o)), int(np.sum(~fl & g1 & o)),
                             int(np.sum(fl & g2 & o)), int(np.sum(~fl & g2 & o)))

        out_v[v] = dict(
            n_coins_scored=int(ok.sum()),
            n_coins_skipped=int((~ok).sum()),
            obs_maxpower=dict(mean=float(np.nanmean(obs)), median=float(np.nanmedian(obs)),
                              p90=float(np.nanpercentile(obs[ok], 90)), max=float(np.nanmax(obs))),
            poisson_null_maxpower_median_of_coin_medians=float(np.nanmedian(V[v]["poimed"])),
            frac_beats_poisson_null=float(line[ok].mean()),
            frac_beats_rotation_null=float(line_rot[ok].mean()),
            frac_beats_both=float(both[ok].mean()),
            expected_frac_under_either_null=1.0 / (LS_NULLS + 1),
            median_peak_period_s=float(np.nanmedian(1.0 / fat[ok])),
            median_peak_period_s_flagged=float(np.nanmedian(1.0 / fat[both])) if both.any() else None,
            # A real scheduler is a LINE: many coins peaking at the same period.  If the
            # flagged coins' peak periods are spread smoothly across the band instead,
            # the flag is picking up residual low-frequency structure, not a clock.
            flagged_peak_period_hist=(
                lambda per: dict(
                    bin_edges_s=[float(x) for x in np.logspace(np.log10(2), np.log10(600), 21)],
                    counts=[int(x) for x in np.histogram(
                        per, bins=np.logspace(np.log10(2), np.log10(600), 21))[0]],
                    n=len(per),
                    top_modes=[[float(p), int(c)] for p, c in zip(
                        *(lambda u, c: (u[np.argsort(-c)][:8], np.sort(c)[::-1][:8]))(
                            *np.unique(np.round(per, 1), return_counts=True)),
                        strict=False)],
                    frac_within_2pct_of_integer_seconds=float(np.mean(
                        np.abs(per - np.round(per)) <= 0.02 * per)) if len(per) else None,
                )
            )(1.0 / fat[both][np.isfinite(fat[both])]) if both.any() else None,
            contrasts={
                "serial_vs_solo": cell(arm == "serial", arm == "solo"),
                "high_vs_low_snipers": cell(snip > snip_med, snip <= snip_med),
                "dumped_vs_not": cell(dumped, ~dumped),
            },
        )
    return dict(
        primary_variant="detrended",
        variants={
            "naive": "y = dt, f >= 2/T, periods [2,600] s",
            "detrended": "y = detrend_linear_in_t(log1p(dt)), f >= 5/T, periods [2,300] s",
        },
        freq_grid_hz=[float(freqs[0]), float(freqs[-1])],
        n_freq=LS_NFREQ,
        n_null_realizations_each=LS_NULLS,
        nyquist_note=(
            "block_time is 1-second resolution, so the sampling Nyquist is 0.5 Hz and no "
            "period below 2 s is accessible.  62.6% of consecutive curve transactions share "
            "a block_time (dt = 0 s), i.e. the event rate sits far ABOVE the timestamp "
            "Nyquist, so any scheduler with a period under a few seconds is invisible by "
            "construction, not by absence."
        ),
        interarrival=dict(
            frac_zero_seconds=float(np.mean(dt_all == 0)),
            median_s=float(np.median(dt_all)),
            p90_s=float(np.percentile(dt_all, 90)),
        ),
        by_variant=out_v,
        _flag=flags["detrended"],
    )


# ----------------------------------------------------------------------------------
# (d) size vs impact
# ----------------------------------------------------------------------------------


def _coin_stats(x, y):
    """OLS sufficient statistics for y = a + gamma*x, per coin."""
    return np.array([len(x), x.sum(), y.sum(), (x * x).sum(), (x * y).sum()], float)


def _gamma_pooled(S):
    """Pooled OLS slope over the summed sufficient statistics (between + within)."""
    n, sx, sy, sxx, sxy = S
    den = n * sxx - sx * sx
    return float((n * sxy - sx * sy) / den) if den > 0 else float("nan")


def _gamma_within(A):
    """Coin fixed-effects (within) slope: sum of within-coin cross-products.

    This is the estimator that cannot be moved by Simpson's paradox -- between-coin
    differences in price scale, curve depth or activity are absorbed by the coin
    intercept.  A[i] = [n, sx, sy, sxx, sxy] for coin i.
    """
    n, sx, sy, sxx, sxy = A[:, 0], A[:, 1], A[:, 2], A[:, 3], A[:, 4]
    ok = n >= 2
    num = np.sum(sxy[ok] - sx[ok] * sy[ok] / n[ok])
    den = np.sum(sxx[ok] - sx[ok] * sx[ok] / n[ok])
    return float(num / den) if den > 0 else float("nan")


_D_VARIANTS = ("abs", "rel")


def test_d(tape, coh, out):
    """Size-vs-impact scaling.

    Two size parameterizations, because on a CFMM the natural size is the fraction of
    the curve consumed, not the raw token count:
        abs : x = log|q|
        rel : x = log(|q| / V_TOK_before)     <- primary
    With `rel`, the h=0 mechanical control is an identity: R_imm = -2*log(1 - |q|/V),
    so gamma must come out at 1.000 (up to the second-order term).  Any departure of
    the `abs` control from 1 is the size-vs-curve-depth confound made visible.

    Two estimators: `pooled` (OLS over all trades) and `within` (coin fixed effects).
    PRIMARY = rel + within, at h in IMPACT_H.  Everything else is diagnostic.
    """
    slices = coin_slices(tape)
    n_coins = len(slices)
    rng = np.random.default_rng(SEED)

    HS = (0, *IMPACT_H)
    st = {(h, v): np.zeros((n_coins, 5)) for h in HS for v in _D_VARIANTS}
    st_early = {(h, v): np.zeros((n_coins, 5)) for h in HS for v in _D_VARIANTS}  # first 200 trades
    st_signed = {h: np.zeros((n_coins, 5)) for h in HS}  # SIGNED R on SIGNED relative size
    zero_R = {h: [0, 0] for h in HS}
    decile = {h: ([], []) for h in HS}

    for i, (s, e) in enumerate(slices):
        q = tape["q"][s:e]
        v_after = tape["cba"][s:e] + V_VIRT
        v_before = v_after + q  # exact: the curve loses exactly what the trader gains
        good = (v_after > 0) & (v_before > 0) & (q != 0)
        if good.sum() < 30:
            continue
        lp_after = -2.0 * np.log(v_after)
        lp_before = -2.0 * np.log(v_before)
        X = {
            "abs": np.log(np.abs(q)),
            "rel": np.log(np.abs(q)) - np.log(v_before),
        }
        n = len(q)
        for h in HS:
            if h == 0:
                idx = np.arange(n)
                R = lp_after - lp_before
                sel = good
            else:
                if n <= h + 30:
                    continue
                idx = np.arange(n - h)
                R = lp_after[idx + h] - lp_before[idx]
                sel = good[idx] & good[idx + h]
            # attenuation-free companion: SIGNED response on SIGNED relative size.
            # log-log gamma is attenuated toward 0 whenever the noise in R is large
            # relative to a trade's own impact, so a low gamma cannot by itself mean
            # "no permanent impact".  beta from the signed linear fit is not attenuated
            # (the regressor is measured exactly), and beta(h)/beta(0) is the fraction
            # of the mechanical impact still present h trades later.
            fsig = (q / v_before)[idx][sel]
            if sel.sum() >= 20:
                st_signed[h][i] = _coin_stats(fsig, R[sel])
            av = np.abs(R[sel])
            nz = av > 0
            zero_R[h][0] += int((~nz).sum())
            zero_R[h][1] += len(nz)
            if nz.sum() < 20:
                continue
            ly = np.log(av[nz])
            keep_idx = idx[sel][nz]
            early = keep_idx < 200
            for v in _D_VARIANTS:
                xx = X[v][keep_idx]
                st[(h, v)][i] = _coin_stats(xx, ly)
                if early.sum() >= 20:
                    st_early[(h, v)][i] = _coin_stats(xx[early], ly[early])
            if len(decile[h][0]) < 400:
                decile[h][0].append(X["rel"][keep_idx])
                decile[h][1].append(ly)

    # ---- interpretive diagnostics (DESCRIPTIVE, not confirmatory cells) -------------
    # gamma -> 0 has two mechanisms: (i) wash / self-trading, where a trade is undone
    # immediately, and (ii) one enormous exit that swamps every other trade.  These are
    # both operator crime but they are not the same crime, and gamma alone cannot tell
    # them apart.  Signed order-flow autocorrelation and signed follow-through can.
    diag = {k: np.full(n_coins, np.nan) for k in
            ("acf1_signed", "signed_followthrough_h10", "med_abs_R_h10", "sd_log_relsize")}
    for i, (s, e) in enumerate(slices):
        q = tape["q"][s:e]
        v_after = tape["cba"][s:e] + V_VIRT
        v_before = v_after + q
        ok = (v_after > 0) & (v_before > 0) & (q != 0)
        if ok.sum() < 40:
            continue
        q, v_after, v_before = q[ok], v_after[ok], v_before[ok]
        f = q / v_before  # signed relative size
        if f.std() > 0:
            diag["acf1_signed"][i] = float(np.corrcoef(f[:-1], f[1:])[0, 1])
        diag["sd_log_relsize"][i] = float(np.std(np.log(np.abs(f))))
        n = len(q)
        if n > 12:
            lpa = -2.0 * np.log(v_after)
            idx = np.arange(n - 10)
            fut = lpa[idx + 10] - lpa[idx]  # EXCLUDES the trade's own impact
            diag["signed_followthrough_h10"][i] = float(np.mean(np.sign(q[idx]) * fut))
            diag["med_abs_R_h10"][i] = float(np.median(np.abs(fut)))

    arm = coh["arm"].to_numpy()
    snip = coh["n_snipers"].to_numpy(float)
    dumped = coh["t_dump"].notna().to_numpy()
    snip_med = float(np.nanmedian(snip))
    groups = {
        "serial": arm == "serial",
        "solo": arm == "solo",
        "high_snipers": snip > snip_med,
        "low_snipers": snip <= snip_med,
        "dumped": dumped,
        "not_dumped": ~dumped,
        "ALL": np.ones(n_coins, bool),
    }
    diag_out = {
        k: {g: dict(median=float(np.nanmedian(v[m])), mean=float(np.nanmean(v[m])),
                    n=int(np.isfinite(v[m]).sum()))
            for g, m in groups.items()}
        for k, v in diag.items()
    }
    CONTRASTS = {
        "serial_vs_solo": ("serial", "solo"),
        "high_vs_low_snipers": ("high_snipers", "low_snipers"),
        "dumped_vs_not": ("dumped", "not_dumped"),
    }

    def fit_block(A, est):
        f = _gamma_within if est == "within" else (lambda M: _gamma_pooled(M.sum(0)))
        live = A[:, 0] > 0
        gam, boot = {}, {}
        for gname, gm in groups.items():
            m = gm & live
            if m.sum() < 20:
                continue
            gam[gname] = f(A[m])
            idx = np.nonzero(m)[0]
            bs = np.empty(BOOT_B)
            for b in range(BOOT_B):
                bs[b] = f(A[idx[rng.integers(0, len(idx), len(idx))]])
            boot[gname] = bs
        con = {}
        for name, (g1, g2) in CONTRASTS.items():
            if g1 not in boot or g2 not in boot:
                continue
            d = boot[g1] - boot[g2]  # groups are disjoint sets of coins
            obs = gam[g1] - gam[g2]
            p = max(2.0 * min((d <= 0).mean(), (d >= 0).mean()), 1.0 / BOOT_B)
            con[name] = dict(
                gamma_g1=gam[g1], gamma_g2=gam[g2], delta=float(obs),
                ci95=[float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
                p_boot=float(p),
                ratio=float(gam[g1] / gam[g2]) if gam[g2] else float("nan"),
            )
        return dict(
            n_coins=int(live.sum()),
            n_trades=int(A[live, 0].sum()),
            gamma={k: float(v) for k, v in gam.items()},
            gamma_ci95={k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
                        for k, v in boot.items()},
            contrasts=con,
        )

    # Volatility-matched gamma: bin coins by their own 10-trade price-move scale and
    # compare arms WITHIN bins.  If the arm gap in gamma collapses here, gamma is
    # reporting volatility, not permanent impact.
    vol = diag["med_abs_R_h10"]
    vok = np.isfinite(vol) & (vol > 0)
    vbin = np.full(n_coins, -1)
    if vok.sum() > 100:
        edges = np.quantile(vol[vok], np.linspace(0, 1, 11))
        vbin[vok] = np.clip(np.searchsorted(edges, vol[vok], side="right") - 1, 0, 9)

    def stratified(A, g1m, g2m):
        live = A[:, 0] > 0
        rows, num, den = [], 0.0, 0.0
        for k in range(10):
            m = (vbin == k) & live
            a1, a2 = A[m & g1m], A[m & g2m]
            if len(a1) < 20 or len(a2) < 20:
                continue
            d = _gamma_within(a1) - _gamma_within(a2)
            w = len(a1) + len(a2)
            rows.append(dict(bin=k, n_g1=len(a1), n_g2=len(a2),
                             gamma_g1=_gamma_within(a1), gamma_g2=_gamma_within(a2), delta=float(d)))
            num += w * d
            den += w
        return dict(bins=rows, weighted_mean_delta=float(num / den) if den else float("nan"))

    out_all = {}
    for h in HS:
        blocks = {}
        for v in _D_VARIANTS:
            for est in ("pooled", "within"):
                blocks[f"{v}_{est}"] = fit_block(st[(h, v)], est)
        blocks["rel_within_first200trades"] = fit_block(st_early[(h, "rel")], "within")
        blocks["signed_beta_within"] = fit_block(st_signed[h], "within")
        blocks["gamma_volatility_matched"] = {
            name: stratified(st[(h, "rel")], groups[g1], groups[g2])
            for name, (g1, g2) in {
                "serial_vs_solo": ("serial", "solo"),
                "high_vs_low_snipers": ("high_snipers", "low_snipers"),
                "dumped_vs_not": ("dumped", "not_dumped"),
            }.items()
        }
        dm = None
        if decile[h][0]:
            Xc = np.concatenate(decile[h][0])
            Yc = np.concatenate(decile[h][1])
            qs = np.quantile(Xc, np.linspace(0, 1, 11))
            mx, my = [], []
            for k in range(10):
                hi = (Xc <= qs[k + 1]) if k == 9 else (Xc < qs[k + 1])
                selk = (Xc >= qs[k]) & hi
                if selk.sum() > 50:
                    mx.append(float(np.median(Xc[selk])))
                    my.append(float(np.median(Yc[selk])))
            if len(mx) >= 5:
                dm = dict(slope=float(np.polyfit(mx, my, 1)[0]), x=mx, y=my)
        out_all[str(h)] = dict(
            frac_zero_R=float(zero_R[h][0] / zero_R[h][1]) if zero_R[h][1] else None,
            decile_median_fit_rel_pooled=dm,
            **blocks,
        )
    return dict(
        horizons_trades=list(HS),
        primary_block="rel_within",
        size_variants={"abs": "x = log|q|", "rel": "x = log(|q| / V_TOK_before)"},
        by_horizon=out_all,
        diagnostics_per_coin_by_group=diag_out,
        sniper_median_split=snip_med,
        bootstrap_reps=BOOT_B,
    )


# ----------------------------------------------------------------------------------
# driver
# ----------------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", required=True)
    ap.add_argument("--cohort", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="dev")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--only", default="abcd")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    print(f"== loading {args.tape}")
    t0 = time.time()
    tape, coh = load(args.tape, args.cohort)
    slices = coin_slices(tape)
    lens = np.array([e - s for s, e in slices])
    print(
        f"   {len(tape['bt']):,} curve TRANSACTIONS over {len(slices):,} coins "
        f"({time.time()-t0:.0f}s); trades/coin median={np.median(lens):.0f} "
        f"min={lens.min()} max={lens.max()}"
    )

    doc = {
        "tag": args.tag,
        "seed": SEED,
        "tape": os.path.abspath(args.tape),
        "cohort": os.path.abspath(args.cohort),
        "unit": "transaction (mint, block_slot, tx_index), q = sum(delta_raw) over legs",
        "n_transactions": len(tape["bt"]),
        "n_coins": len(slices),
        "trades_per_coin": dict(
            median=float(np.median(lens)), min=int(lens.min()), max=int(lens.max()),
            p10=float(np.percentile(lens, 10)), p90=float(np.percentile(lens, 90)),
        ),
        "frac_multileg_tx": float(np.mean(tape["legs"] > 1)),
    }

    if "a" in args.only:
        print("== (a) NCD")
        doc["a_ncd"] = test_a(tape, coh, args.workers, args.out)
    if "b" in args.only:
        print("== (b) Benford")
        b = test_b(tape, coh, args.out)
        b.pop("_mad", None)
        doc["b_benford"] = b
        print("   ambient FSD (tokens):", np.round(b["ambient_fsd_tokens"], 4))
        print("   benford          :", np.round(b["benford_fsd"], 4))
        for k, v in b["contrasts"].items():
            print(f"   {k:22s} p={v['p']:.4g} cliffs_delta={v['cliffs_delta']:+.4f}")
    if "c" in args.only:
        print("== (c) Lomb-Scargle")
        c = test_c(tape, coh, args.workers, args.out)
        c.pop("_flag", None)
        doc["c_lombscargle"] = c
        for vn, v in c["by_variant"].items():
            print(f"   [{vn}] beats poisson={v['frac_beats_poisson_null']:.4f} "
                  f"rotation={v['frac_beats_rotation_null']:.4f} both={v['frac_beats_both']:.4f} "
                  f"(null expectation {v['expected_frac_under_either_null']:.4f}); "
                  f"median peak period {v['median_peak_period_s']:.1f}s")
            for k, cv in v["contrasts"].items():
                print(f"      {k:22s} p={cv['p']:.4g} rate {cv['rate_g1']:.4f} vs "
                      f"{cv['rate_g2']:.4f} (RR {cv['rate_ratio']:.3f})")
    if "d" in args.only:
        print("== (d) impact scaling")
        d = test_d(tape, coh, args.out)
        doc["d_impact"] = d
        for h, v in d["by_horizon"].items():
            print(f"   h={h}  zeroR={v['frac_zero_R']:.5f}")
            for blk in ("abs_pooled", "abs_within", "rel_pooled", "rel_within",
                        "rel_within_first200trades", "signed_beta_within"):
                g = v[blk]["gamma"]
                print(f"     {blk:26s} ALL={g.get('ALL', float('nan')):.4f} "
                      f"serial={g.get('serial', float('nan')):.4f} solo={g.get('solo', float('nan')):.4f} "
                      f"dump={g.get('dumped', float('nan')):.4f} "
                      f"nodump={g.get('not_dumped', float('nan')):.4f}")
            for k, cv in v["rel_within"]["contrasts"].items():
                print(f"      PRIMARY {k:22s} d={cv['delta']:+.4f} "
                      f"ci={np.round(cv['ci95'],4)} p={cv['p_boot']:.4g}")
            for k, sv in v["gamma_volatility_matched"].items():
                print(f"      vol-matched {k:22s} weighted delta={sv['weighted_mean_delta']:+.4f} "
                      f"({len(sv['bins'])} bins)")
        b0 = d["by_horizon"]["0"]["signed_beta_within"]["gamma"]
        for h in IMPACT_H:
            bh = d["by_horizon"][str(h)]["signed_beta_within"]["gamma"]
            print(f"   persistence beta(h={h})/beta(0): " + "  ".join(
                f"{g}={bh[g]/b0[g]:.4f}" for g in ("ALL", "serial", "solo", "dumped", "not_dumped")
                if g in bh and g in b0 and b0[g]))

    # ---- trials + Benjamini-Yekutieli --------------------------------------------
    cells = []
    if "a" in args.only:
        for k in ("N256_real", "N256_shuffled_tape", "N512_real", "N512_shuffled_tape"):
            cells.append((f"a.{k}", doc["a_ncd"][k]["p_perm_one_sided_lower"],
                          doc["a_ncd"][k]["cohens_d"]))
    if "b" in args.only:
        for k, v in doc["b_benford"]["contrasts"].items():
            cells.append((f"b.{k}", v["p"], v["cliffs_delta"]))
    if "c" in args.only:
        for k, v in doc["c_lombscargle"]["by_variant"]["detrended"]["contrasts"].items():
            cells.append((f"c.{k}", v["p"], v["rate_ratio"]))
    if "d" in args.only:
        for h in IMPACT_H:
            for k, v in doc["d_impact"]["by_horizon"][str(h)]["rel_within"]["contrasts"].items():
                cells.append((f"d.h{h}.{k}", v["p_boot"], v["delta"]))
    if cells:

        ps = [c[1] for c in cells]
        keep, cm, thr = by_fdr(ps)
        doc["multiplicity"] = dict(
            method="Benjamini-Yekutieli",
            q=BY_Q,
            n_cells=len(cells),
            harmonic_c_m=cm,
            cells=[
                dict(name=n, p=float(p), effect=float(ef), by_threshold=float(t), survives=bool(k))
                for (n, p, ef), t, k in zip(cells, thr, keep, strict=False)
            ],
            n_surviving=int(keep.sum()),
        )
        print(f"== BY-FDR q={BY_Q}: {int(keep.sum())}/{len(cells)} cells survive (c_m={cm:.4f})")
        for (n, p, ef), t, k in sorted(zip(cells, thr, keep, strict=False), key=lambda z: z[0][1]):
            print(f"   {'PASS' if k else '    '} {n:34s} p={p:.4g} thr={t:.5f} effect={ef:+.4f}")

    path = os.path.join(args.out, f"discriminators_{args.tag}.json")
    with open(path, "w") as f:
        json.dump(doc, f, indent=2, default=str)
    print(f"== wrote {path}")


if __name__ == "__main__":
    main()
