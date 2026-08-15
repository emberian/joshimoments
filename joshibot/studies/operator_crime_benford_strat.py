#!/usr/bin/env python3
"""Post-hoc for test (b): is the group difference in first-digit MAD explained by how
repetitive the coin's first 50 trade sizes are?  Compares MAD within strata of the
number of distinct |delta_raw| values, so the repetition confound is held fixed."""
import argparse
import json
import math

import numpy as np

from studies.operator_crime_discriminators import (
    BENFORD,
    BENFORD_FIRST,
    _fsd,
    coin_slices,
    load,
    mannwhitney,
)

ap = argparse.ArgumentParser()
ap.add_argument("--tape", required=True)
ap.add_argument("--cohort", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--tag", required=True)
a = ap.parse_args()

tape, coh = load(a.tape, a.cohort)
slices = coin_slices(tape)
n = len(slices)
mad = np.full(n, np.nan)
nd = np.full(n, np.nan)
for i, (s, e) in enumerate(slices):
    if (e - s) < BENFORD_FIRST:
        continue
    q = np.abs(tape["q"][s : s + BENFORD_FIRST])
    d = _fsd(q)
    if len(d) < BENFORD_FIRST:
        continue
    obs = np.bincount(d, minlength=10)[1:10] / float(len(d))
    mad[i] = float(np.mean(np.abs(obs - BENFORD)))
    nd[i] = len(np.unique(q))

arm = coh["arm"].to_numpy()
snip = coh["n_snipers"].to_numpy(float)
dumped = coh["t_dump"].notna().to_numpy()
sm = float(np.nanmedian(snip))
CON = {
    "serial_vs_solo": (arm == "serial", arm == "solo"),
    "high_vs_low_snipers": (snip > sm, snip <= sm),
    "dumped_vs_not": (dumped, ~dumped),
}
ok = np.isfinite(mad)
# strata: distinct-size count.  Most coins sit at 45-50, so use explicit buckets.
edges = [0, 30, 40, 44, 47, 49, 51]
strat = np.full(n, -1)
for k in range(len(edges) - 1):
    strat[ok & (nd >= edges[k]) & (nd < edges[k + 1])] = k

out = {"strata_edges_n_distinct": edges, "contrasts": {}}
for name, (g1, g2) in CON.items():
    rows, num, den = [], 0.0, 0.0
    for k in range(len(edges) - 1):
        m = strat == k
        A, B = mad[m & g1], mad[m & g2]
        A, B = A[np.isfinite(A)], B[np.isfinite(B)]
        if len(A) < 20 or len(B) < 20:
            continue
        r = mannwhitney(A, B)
        w = len(A) + len(B)
        rows.append(dict(stratum=k, n_g1=len(A), n_g2=len(B), median_g1=r["median_a"],
                         median_g2=r["median_b"], cliffs_delta=r["cliffs_delta"], p=r["p"]))
        num += w * r["cliffs_delta"]
        den += w
    unadj = mannwhitney(mad[g1], mad[g2])
    out["contrasts"][name] = dict(
        unadjusted_cliffs_delta=unadj["cliffs_delta"], unadjusted_p=unadj["p"],
        repetition_stratified_cliffs_delta=float(num / den) if den else float("nan"),
        strata=rows,
    )
    print(f"{name:22s} raw d={unadj['cliffs_delta']:+.4f}  "
          f"repetition-stratified d={num/den if den else math.nan:+.4f}")

p = f"{a.out}/benford_repetition_stratified_{a.tag}.json"
with open(p, "w") as f:
    json.dump(out, f, indent=2)
print("wrote", p)
