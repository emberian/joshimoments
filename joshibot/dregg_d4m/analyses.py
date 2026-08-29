"""D1-D5: the pre-registered analyses. See ``studies/REGISTRATION_d4m.md``.

Each function returns a JSON-able result dict and writes its artifact tables through
``dregg_d4m.artifacts.Run``. Every effect is scored against
``studies.operator_crime._curveball``, reused through ``dregg_d4m.nulls`` -- there is no
i.i.d. shuffle anywhere in this file, for the reason ``RESULT_svn_cotrading.md`` section 5
measured rather than argued.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import scipy.sparse as sp

from dregg_d4m import graphs, nulls
from dregg_d4m.artifacts import Run
from dregg_d4m.assoc import Assoc, co_occurrence, jaccard, threshold, upper_pairs

#: ``studies/data/operator_crime_fresh/graph.json`` -- the numbers D1 must reproduce.
REPLICATION_TARGETS = {
    "same_deployer_jaccard": 0.2607947149034321,
    "day_matched_jaccard": 0.0026193362663966004,
    "curveball_null_mean": 0.007533357468896544,
}
#: cmd_graph's own arm parameters, copied so the replication is of the same object.
ARM_SEED = 20260815
ARM_MAX_DEPLOYERS = 400
ARM_MAX_COINS = 25
ARM_TRADES_PER_ROW = 5  # operator_crime uses 5 * len(sets); cluster_map uses 20

#: The registered live threshold: the crew graph is cut where the shipped matcher cuts.
CREW_JACCARD = 0.10
CREW_MIN_OVERLAP = 2
#: Registered in advance (see the registration's compute-budget section).
WALLET_DEGREE_CAP = 200


def _echo(msg: str) -> None:
    print(msg, flush=True)


# =====================================================================================
# D1 -- the crew graph at scale, and the replication that licenses it
# =====================================================================================


def _fresh_arm() -> tuple[Assoc, list[list[int]], Any]:
    """cmd_graph's exact arm as a coin x wallet ``Assoc``, plus its same-deployer pair list.

    Reproduced from ``studies/operator_crime.py:cmd_graph`` -- the FRESH window
    (2026-08-26..28, ``operator_crime_fresh/coins.parquet``), NOT the combined corpus, because
    that is the window ``graph.json`` was written from."""

    import pandas as pd

    root = graphs.REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
    coins = pd.read_parquet(root / "coins.parquet", columns=["mint", "deployer", "birth_time"])
    sn = pd.read_parquet(root / "snipers.parquet", columns=["mint", "owner"])

    dep = coins.dropna(subset=["deployer"]).groupby("deployer").size()
    top = dep[dep >= 2].sort_values(ascending=False).head(ARM_MAX_DEPLOYERS)
    sub = coins[coins["deployer"].isin(top.index)].copy()
    sub = sub.sort_values("birth_time").groupby("deployer", group_keys=False).head(ARM_MAX_COINS).copy()

    own = dict(zip(sub["mint"], sub["deployer"], strict=True))
    sn_sub = sn[sn["mint"].isin(set(sub["mint"]))]
    mints = sorted(set(sn_sub["mint"]))
    midx = {m: i for i, m in enumerate(mints)}
    sub = sub[sub["mint"].isin(midx)]

    keep = sn_sub[sn_sub["owner"] != sn_sub["mint"].map(own)]
    wallets = sorted(set(keep["owner"]))
    a = Assoc.from_tuples(list(keep["mint"]), list(keep["owner"]), row_keys=mints, col_keys=wallets)

    pairs: list[list[int]] = []
    for _, g in sub.groupby("deployer"):
        idx = [midx[m] for m in g["mint"]]
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                pairs.append([idx[x], idx[y]])
    return a, pairs, sub


def _algebra_mean_jaccard(a: Assoc, pairs: np.ndarray) -> float:
    """Mean Jaccard over a fixed pair list, computed as ONE product plus a normalisation.

    This is the whole thesis of the lane in four lines: the co-occurrence product gives every
    pair's intersection at once, the row degrees give every set size, and the mean over a
    pair list is a lookup. Pairs absent from the product share nothing and contribute 0,
    which is exactly ``operator_crime._mean_jaccard``'s ``u == 0 -> 0.0`` branch."""

    if pairs.size == 0:
        return float("nan")
    prod = co_occurrence(a, axis="row", min_overlap=1.0)
    j = jaccard(prod, a.degree(axis="row"))
    total = float(np.asarray(j.m[pairs[:, 0], pairs[:, 1]]).sum())
    return total / len(pairs)


def d1_crew_graph(*, n_null: int = 200, write: bool = True) -> dict[str, Any]:
    """B'B and BB' at scale, licensed by reproducing cmd_graph's validated statistic."""

    import pandas as pd

    _echo("D1.1 replication: cmd_graph's arm, computed as algebra")
    arm, pair_list, sub = _fresh_arm()
    pairs = np.asarray(pair_list, dtype=np.int64)
    same = _algebra_mean_jaccard(arm, pairs)
    _echo(f"  arm: {arm.shape[0]:,} coins x {arm.shape[1]:,} wallets, {arm.nnz:,} ex-deployer edges")
    _echo(f"  same-deployer pairs: {len(pairs):,}   mean Jaccard {same:.4f}")

    rng = np.random.default_rng(ARM_SEED)
    byday: dict[int, list[tuple[int, str]]] = {}
    midx = {m: i for i, m in enumerate(arm.row)}
    for mint, bt, dep_ in zip(sub["mint"], sub["birth_time"], sub["deployer"], strict=True):
        byday.setdefault(int(bt) // 86400, []).append((midx[mint], dep_))
    control: list[list[int]] = []
    tries = 0
    while len(control) < len(pairs) and tries < 50 * max(len(pairs), 1):
        tries += 1
        pool = byday[int(rng.choice(list(byday.keys())))]
        if len(pool) < 2:
            continue
        i, j = rng.integers(0, len(pool), 2)
        if i == j or pool[i][1] == pool[j][1]:
            continue
        control.append([pool[i][0], pool[j][0]])
    day_matched = _algebra_mean_jaccard(arm, np.asarray(control, dtype=np.int64))
    _echo(f"  day-matched control: {len(control):,} pairs   mean Jaccard {day_matched:.4f}")

    _echo(f"  degree-preserving null, n={n_null} (curveball, {ARM_TRADES_PER_ROW} trades/row)")
    null = nulls.against_null(
        arm,
        lambda x: _algebra_mean_jaccard(x, pairs),
        draws=n_null,
        seed=ARM_SEED,
        trades_per_row=ARM_TRADES_PER_ROW,
    )
    _echo(f"  null mean {null.mean:.4f}  p95 {null.p95:.4f}  p={null.p_value:.4f}  "
          f"{null.ratio:.1f}x over the null")

    checks = {
        "same_deployer_jaccard": {
            "target": REPLICATION_TARGETS["same_deployer_jaccard"],
            "got": same,
            "tol": 0.010,
            "pass": abs(same - REPLICATION_TARGETS["same_deployer_jaccard"]) <= 0.010,
        },
        "day_matched_jaccard": {
            "target": REPLICATION_TARGETS["day_matched_jaccard"],
            "got": day_matched,
            "tol": 0.001,
            "pass": abs(day_matched - REPLICATION_TARGETS["day_matched_jaccard"]) <= 0.001,
        },
        "curveball_null_mean": {
            "target": REPLICATION_TARGETS["curveball_null_mean"],
            "got": null.mean,
            "tol": 0.002,
            "pass": abs(null.mean - REPLICATION_TARGETS["curveball_null_mean"]) <= 0.002,
        },
    }
    replicated = all(c["pass"] for c in checks.values())
    _echo(f"  REPLICATION: {'PASS' if replicated else 'FAIL'}")

    _echo("D1.2 the graphs at scale")
    bw = graphs.birth_snipers(window="all", ex_deployer=True)
    ww_prod = co_occurrence(bw.a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
    ww = jaccard(ww_prod, bw.a.degree(axis="row")).drop_diagonal()
    _echo(f"  wallet x wallet: {ww.shape[0]:,} nodes, {ww.nnz // 2:,} pairs at overlap>={CREW_MIN_OVERLAP}")

    capped = graphs.birth_snipers(window="all", ex_deployer=True, wallet_degree_cap=WALLET_DEGREE_CAP)
    coin_side = capped.a.T
    cc_prod = co_occurrence(coin_side, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
    cc = jaccard(cc_prod, coin_side.degree(axis="row")).drop_diagonal()
    _echo(f"  coin x coin (wallet cap {WALLET_DEGREE_CAP}): {cc.shape[0]:,} nodes, {cc.nnz // 2:,} pairs")

    sensitivity = []
    for cap in (50, 100, 200, 500):
        g = graphs.birth_snipers(window="all", ex_deployer=True, wallet_degree_cap=cap)
        side = g.a.T
        pr = co_occurrence(side, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
        jj = jaccard(pr, side.degree(axis="row")).drop_diagonal()
        strong = int((jj.m.data >= CREW_JACCARD).sum() // 2)
        sensitivity.append(
            {"cap": cap, "wallets": g.a.shape[0], "incidences": g.a.nnz,
             "coin_pairs": jj.nnz // 2, "coin_pairs_at_j10": strong}
        )
        _echo(f"    cap {cap:>4}: {jj.nnz // 2:,} pairs, {strong:,} at Jaccard>={CREW_JACCARD}")

    result: dict[str, Any] = {
        "replication": {"checks": checks, "replicated": replicated,
                        "arm_coins": arm.shape[0], "arm_wallets": arm.shape[1],
                        "arm_edges": arm.nnz, "same_pairs": len(pairs),
                        "control_pairs": len(control), "null": null.to_json()},
        "wallet_graph": {"nodes": ww.shape[0], "pairs": ww.nnz // 2,
                         "pairs_at_j10": int((ww.m.data >= CREW_JACCARD).sum() // 2)},
        "coin_graph": {"nodes": cc.shape[0], "pairs": cc.nnz // 2,
                       "wallet_degree_cap": WALLET_DEGREE_CAP,
                       "pairs_at_j10": int((cc.m.data >= CREW_JACCARD).sum() // 2)},
        "cap_sensitivity": sensitivity,
    }

    if write:
        run = Run("d1_crew_graph")
        wi, wj, wv = upper_pairs(threshold(ww, CREW_JACCARD))
        ov = co_occurrence(bw.a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
        run.write_table(
            "wallet_pairs",
            pd.DataFrame({
                "wallet_a": [ww.row[i] for i in wi],
                "wallet_b": [ww.col[j] for j in wj],
                "jaccard": wv,
                "overlap": np.asarray(ov.m[wi, wj]).ravel().astype(np.int64),
            }),
            columns={
                "wallet_a": "base58 wallet, lexicographically first of the pair",
                "wallet_b": "base58 wallet",
                "jaccard": "shared birth-slot coins / union of their coin sets",
                "overlap": "number of coins both wallets bought in the birth slot",
            },
        )
        ci, cj, cv = upper_pairs(threshold(cc, CREW_JACCARD))
        cov = co_occurrence(coin_side, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
        run.write_table(
            "coin_pairs",
            pd.DataFrame({
                "mint_a": [cc.row[i] for i in ci],
                "mint_b": [cc.col[j] for j in cj],
                "jaccard": cv,
                "overlap": np.asarray(cov.m[ci, cj]).ravel().astype(np.int64),
            }),
            columns={
                "mint_a": "base58 pump mint, lexicographically first of the pair",
                "mint_b": "base58 pump mint",
                "jaccard": "shared birth-slot wallets / union of their sniper sets",
                "overlap": "number of wallets in both coins' birth slots",
            },
        )
        run.meta = result
        run.finish(provenance=[bw.prov.to_json(), capped.prov.to_json()],
                   params={"min_overlap": CREW_MIN_OVERLAP, "crew_jaccard": CREW_JACCARD,
                           "wallet_degree_cap": WALLET_DEGREE_CAP, "n_null": n_null,
                           "arm_seed": ARM_SEED})
    return result


# =====================================================================================
# D2 -- communities and their persistence across the 11-day gap
# =====================================================================================


def label_propagation(m: sp.csr_array, *, rounds: int = 50) -> np.ndarray:
    """Deterministic asynchronous label propagation on a weighted symmetric graph.

    No randomness at all: nodes are visited in ascending index order, a node takes the label
    with the greatest total incident WEIGHT, and exact ties go to the smallest label.
    ``RESULT_cluster_map.md`` section 3 records what non-determinism costs -- three runs of
    one Infomap command returned 24,180 / 24,196 / 24,199 modules because duckdb's unordered
    reads changed the node ids, which made every downstream count unfalsifiable. A partition
    that varies run to run is not a result.

    KNOWN LIMITATION, measured and pinned by
    ``tests/test_d4m_graphs.py::test_label_propagation_is_degenerate_on_unweighted_regular_graphs``:
    on an UNWEIGHTED REGULAR graph every candidate label ties at weight 1, the smallest-label
    rule then cascades, and two cliques joined by one bridge collapse into one community --
    the very blob this method exists to avoid. It does not fire on the crew graph, because
    that graph is Jaccard-WEIGHTED and irregular: a bridge is a weak edge and loses the
    weight comparison outright, which the weighted test pins. The observed giant-component
    share is printed next to every partition (0.003 at the registered cut) precisely so this
    is a checked fact rather than a hope.

    ``studies.svn_cotrading.infomap_communities`` is the repo's documented preference and was
    tried first; it is a map-equation implementation written for that study's tens-of-nodes
    networks and does not return on a 12,538-node graph inside two minutes, let alone 200
    times for the null. Connected components are computed and reported alongside every
    partition so the union-find pathology is visible if it ever does fire."""

    n = m.shape[0]
    labels = np.arange(n, dtype=np.int64)
    ip, ind, dat = m.indptr, m.indices, m.data
    for _ in range(rounds):
        moved = False
        for i in range(n):
            lo, hi = ip[i], ip[i + 1]
            if lo == hi:
                continue
            nbr, w = labels[ind[lo:hi]], dat[lo:hi]
            order = np.argsort(nbr, kind="stable")
            nb, wb = nbr[order], w[order]
            starts = np.flatnonzero(np.concatenate(([True], nb[1:] != nb[:-1])))
            sums = np.add.reduceat(wb, starts)
            best = nb[starts[int(np.argmax(sums))]]  # argmax takes the first = smallest label
            if best != labels[i]:
                labels[i] = best
                moved = True
        if not moved:
            break
    _, compact = np.unique(labels, return_inverse=True)
    return compact.astype(np.int64)


def _giant_share(labels: np.ndarray) -> float:
    if labels.size == 0:
        return float("nan")
    return float(np.bincount(labels).max() / labels.size)


def d2_communities(*, n_null: int = 200, write: bool = True) -> dict[str, Any]:
    """Communities on the wallet-wallet crew graph, and whether they survive the gap."""

    import pandas as pd
    from scipy.sparse.csgraph import connected_components

    from studies.svn_cotrading import adjusted_rand_index

    bw = graphs.birth_snipers(window="all", ex_deployer=True)
    prod = co_occurrence(bw.a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
    full = jaccard(prod, bw.a.degree(axis="row")).drop_diagonal()

    out: dict[str, Any] = {"thresholds": {}}
    keep_labels: np.ndarray | None = None
    keep_sub: Assoc | None = None
    for thr in (0.05, CREW_JACCARD, 0.20):
        g = threshold(full, thr)
        active = np.flatnonzero(g.degree(axis="row") > 0)
        sub = sp.csr_array(g.m[np.ix_(active, active)])
        n_cc, cc = connected_components(sub, directed=False)
        lp = label_propagation(sub)
        sizes = np.bincount(lp)
        rec = {
            "threshold": thr,
            "nodes_with_an_edge": int(active.size),
            "edges": int(sub.nnz // 2),
            "connected_components": int(n_cc),
            "cc_giant_component_share": _giant_share(cc),
            "label_prop_communities": int(sizes.size),
            "lp_giant_component_share": _giant_share(lp),
            "lp_size_ge2": int((sizes >= 2).sum()),
            "lp_max_size": int(sizes.max()) if sizes.size else 0,
            "lp_median_size": float(np.median(sizes)) if sizes.size else float("nan"),
            "ari_lp_vs_cc": adjusted_rand_index(
                dict(enumerate(lp.tolist())), dict(enumerate(cc.tolist()))
            ),
        }
        out["thresholds"][str(thr)] = rec
        _echo(f"  J>={thr}: {rec['nodes_with_an_edge']:,} nodes, {rec['edges']:,} edges, "
              f"CC={rec['connected_components']:,} (giant {rec['cc_giant_component_share']:.3f}), "
              f"LP={rec['label_prop_communities']:,} (giant {rec['lp_giant_component_share']:.3f})")
        if thr == CREW_JACCARD:
            keep_labels, keep_sub = lp, Assoc(
                [full.row[i] for i in active], [full.col[i] for i in active], sub
            )
            keep_active = active

    assert keep_labels is not None and keep_sub is not None
    wallets = list(keep_sub.row)
    comm_of = dict(zip(wallets, keep_labels.tolist(), strict=True))

    # --- persistence across the gap ---------------------------------------------------
    df = graphs.load_snipers("all")
    df = df[(df["owner"] != df["deployer"]) & (df["owner"].isin(set(wallets)))].copy()
    lo_b, _ = graphs._bounds("B")
    df["comm"] = df["owner"].map(comm_of)
    df["in_b"] = df["birth_time"] >= lo_b
    per = df.groupby("comm").agg(
        n_wallets=("owner", "nunique"), n_coins=("mint", "nunique"),
        t_first=("birth_time", "min"), t_last=("birth_time", "max"),
        n_in_b=("in_b", "sum"), n_legs=("mint", "size"),
    )
    sizes = np.bincount(keep_labels)
    per["size"] = [int(sizes[c]) for c in per.index]
    per["spans_gap"] = (per["n_in_b"] > 0) & (per["n_in_b"] < per["n_legs"])
    multi = per[per["size"] >= 2]
    observed_share = float(multi["spans_gap"].mean()) if len(multi) else float("nan")
    _echo(f"  communities with >=2 wallets: {len(multi):,}; spanning the gap: "
          f"{int(multi['spans_gap'].sum()):,} ({observed_share:.4f})")

    def persistence(a: Assoc) -> float:
        """Recluster and re-measure the gap-spanning share on a randomised incidence."""

        pr = co_occurrence(a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
        jj = threshold(jaccard(pr, a.degree(axis="row")).drop_diagonal(), CREW_JACCARD)
        act = np.flatnonzero(jj.degree(axis="row") > 0)
        if act.size == 0:
            return 0.0
        lab = label_propagation(sp.csr_array(jj.m[np.ix_(act, act)]))
        names = [jj.row[i] for i in act]
        cmap = dict(zip(names, lab.tolist(), strict=True))
        d = df[df["owner"].isin(cmap)].copy()
        if d.empty:
            return 0.0
        d["comm"] = d["owner"].map(cmap)
        g = d.groupby("comm").agg(n_in_b=("in_b", "sum"), n_legs=("mint", "size"))
        sz = np.bincount(lab)
        g["size"] = [int(sz[c]) for c in g.index]
        g = g[g["size"] >= 2]
        if not len(g):
            return 0.0
        return float(((g["n_in_b"] > 0) & (g["n_in_b"] < g["n_legs"])).mean())

    _echo(f"  degree-preserving null on the wallet x coin incidence, n={n_null}")
    null = nulls.against_null(bw.a, persistence, draws=n_null, seed=ARM_SEED)
    _echo(f"  observed {null.observed:.4f}  null mean {null.mean:.4f}  p95 {null.p95:.4f}  "
          f"p={null.p_value:.4f}  ratio {null.ratio:.2f}x")

    ships = bool(null.ratio >= 3.0 and null.p_value <= 0.01)
    out["persistence"] = {
        "communities_ge2": len(multi),
        "spanning_gap": int(multi["spans_gap"].sum()) if len(multi) else 0,
        "share": observed_share,
        "wilson": nulls.wilson(int(multi["spans_gap"].sum()) if len(multi) else 0, len(multi)),
        "null": null.to_json(),
        "ship_rule_met": ships,
    }
    out["chosen_threshold"] = CREW_JACCARD

    if write:
        run = Run("d2_communities")
        run.write_table(
            "wallet_communities",
            pd.DataFrame({
                "wallet": wallets,
                "community_id": keep_labels.astype(np.int64),
                "method": "label_propagation",
                "jaccard_threshold": CREW_JACCARD,
            }),
            columns={
                "wallet": "base58 wallet",
                "community_id": "deterministic label-propagation community, dense 0-based",
                "method": "partition method (label_propagation)",
                "jaccard_threshold": "edge cut used to build the graph",
            },
        )
        prof = per.reset_index().rename(columns={"comm": "community_id"})
        prof["community_id"] = prof["community_id"].astype(np.int64)
        prof["n_in_b"] = prof["n_in_b"].astype(np.int64)
        prof["spans_gap"] = prof["spans_gap"].astype(bool)
        run.write_table(
            "community_profile",
            prof[["community_id", "size", "n_wallets", "n_coins", "n_legs", "n_in_b",
                  "t_first", "t_last", "spans_gap"]],
            columns={
                "community_id": "label-propagation community id",
                "size": "wallets in the community",
                "n_wallets": "wallets with at least one birth-slot incidence in the corpus",
                "n_coins": "distinct coins the community touched at birth",
                "n_legs": "birth-slot incidences (wallet-coin) by this community",
                "n_in_b": "of those, incidences in window B (2026-08-26..28)",
                "t_first": "unix seconds of the community's earliest birth-slot incidence",
                "t_last": "unix seconds of its latest",
                "spans_gap": "true iff it acted in BOTH window A and window B",
            },
        )
        run.meta = out
        run.finish(provenance=[bw.prov.to_json()],
                   params={"crew_jaccard": CREW_JACCARD, "min_overlap": CREW_MIN_OVERLAP,
                           "n_null": n_null, "seed": ARM_SEED,
                           "window_a": graphs.WINDOW_A, "window_b": graphs.WINDOW_B})
    out["_labels"] = keep_labels
    out["_wallets"] = wallets
    out["_active"] = keep_active
    return out


# =====================================================================================
# D3 -- territory: do crews avoid each other, as algebra
# =====================================================================================


def _community_coin_matrix(labels: np.ndarray, wallets: Sequence[str], b: Assoc, top_k: int) -> Assoc:
    """``U = binarize(P B)`` -- community x coin, one product where cluster_map looped."""

    keep = [(w, int(c)) for w, c in zip(wallets, labels.tolist(), strict=True)]
    comm_ids = sorted({c for _, c in keep})
    p = Assoc.from_tuples(
        [f"c{c}" for _, c in keep], [w for w, _ in keep],
        row_keys=[f"c{c}" for c in comm_ids], col_keys=list(b.row),
    )
    u = (p @ b).binarize()
    order = np.argsort(-u.degree(axis="row"), kind="stable")[:top_k]
    return u.select(rows=[u.row[i] for i in order])


def d3_territory(
    labels: np.ndarray, wallets: Sequence[str], *, top_k: int = 25, n_null: int = 200,
    write: bool = True,
) -> dict[str, Any]:
    """cluster_map's avoid / pile-on trichotomy, recomputed as one product plus a null.

    A SHAPE replication only: different partition, different substrate (birth-slot snipers
    have no exit leg), different window. cluster_map's 223/67/10 is not a number this can
    hit, and the registration says so."""

    import pandas as pd

    bw = graphs.birth_snipers(window="all", ex_deployer=True)
    u = _community_coin_matrix(labels, wallets, bw.a, top_k)
    deg = u.degree(axis="row")
    _echo(f"D3 top {u.shape[0]} communities, coin universes "
          f"{int(deg.min())}..{int(deg.max())} (median {int(np.median(deg))})")

    def pair_jaccards(x: Assoc) -> np.ndarray:
        prod = co_occurrence(x, axis="row", min_overlap=1.0)
        j = jaccard(prod, x.degree(axis="row"))
        dense = np.zeros((x.shape[0], x.shape[0]))
        ri, ci, v = j.triples()
        dense[ri, ci] = v
        iu = np.triu_indices(x.shape[0], k=1)
        return dense[iu]

    observed = pair_jaccards(u)
    rng = np.random.default_rng(ARM_SEED)
    draws = np.stack([pair_jaccards(nulls.randomise(u, rng)) for _ in range(n_null)])
    mu, sd = draws.mean(axis=0), draws.std(axis=0, ddof=1)
    z = np.where(sd > 0, (observed - mu) / np.where(sd > 0, sd, 1.0), np.nan)
    verdict = np.where(np.isnan(z), "null", np.where(z < -2, "avoid", np.where(z > 2, "pile_on", "null")))
    counts = {v: int((verdict == v).sum()) for v in ("avoid", "pile_on", "null")}
    n_pairs = int(observed.size)
    _echo(f"  {n_pairs} pairs: avoid {counts['avoid']}, pile-on {counts['pile_on']}, "
          f"null {counts['null']}  (cluster_map shape: 223 / 67 / 10 of 300)")
    share = counts["avoid"] / n_pairs if n_pairs else float("nan")

    iu = np.triu_indices(u.shape[0], k=1)
    ov = co_occurrence(u, axis="row", min_overlap=1.0)
    dense_ov = np.zeros((u.shape[0], u.shape[0]))
    ri, ci, v = ov.triples()
    dense_ov[ri, ci] = v
    frame = pd.DataFrame({
        "community_a": [u.row[i] for i in iu[0]],
        "community_b": [u.row[j] for j in iu[1]],
        "coins_a": deg[iu[0]].astype(np.int64),
        "coins_b": deg[iu[1]].astype(np.int64),
        "shared_coins": dense_ov[iu].astype(np.int64),
        "jaccard": observed,
        "null_mean": mu,
        "null_sd": sd,
        "z": z,
        "verdict": verdict,
    })
    out = {
        "top_k": int(u.shape[0]), "pairs": n_pairs, "counts": counts,
        "avoidance_share": share,
        "shape_replicated": bool(share > 0.50),
        "cluster_map_reference": {"avoid": 223, "pile_on": 67, "null": 10, "pairs": 300},
        "n_null": n_null, "seed": ARM_SEED,
        "most_extreme_avoid": frame.nsmallest(3, "z")[
            ["community_a", "community_b", "coins_a", "coins_b", "shared_coins", "jaccard",
             "null_mean", "z"]].to_dict("records"),
        "most_extreme_pile_on": frame.nlargest(3, "z")[
            ["community_a", "community_b", "coins_a", "coins_b", "shared_coins", "jaccard",
             "null_mean", "z"]].to_dict("records"),
        "predation_not_computable": (
            "cluster_map section 4.2's DIRECTIONAL predation needs an exit leg -- one fleet's "
            "selling landing inside another's buying. The birth-slot substrate has entries "
            "only, so that statistic is not computable here and none is reported."
        ),
    }
    if write:
        run = Run("d3_territory")
        run.write_table(
            "community_pairs", frame,
            columns={
                "community_a": "community id (c<N>) from d2_communities",
                "community_b": "community id (c<N>)",
                "coins_a": "size of a's coin universe",
                "coins_b": "size of b's coin universe",
                "shared_coins": "coins in both universes",
                "jaccard": "shared / union of the two coin universes",
                "null_mean": "mean of that Jaccard over degree-preserving curveball draws",
                "null_sd": "its standard deviation over the draws",
                "z": "(observed - null_mean) / null_sd",
                "verdict": "avoid (z < -2) / pile_on (z > 2) / null",
            },
        )
        run.meta = out
        run.finish(provenance=[bw.prov.to_json()],
                   params={"top_k": top_k, "n_null": n_null, "seed": ARM_SEED,
                           "crew_jaccard": CREW_JACCARD})
    return out


# =====================================================================================
# D4 -- hop distance to a dirty crew
# =====================================================================================


def _hop_levels(adj: Assoc, seeds: np.ndarray, max_hops: int) -> np.ndarray:
    """Wallet hop distance from ``seeds`` over the OR-AND semiring, one product per hop.

    ``level = 0`` for a seed, ``k`` for first reached at hop k, ``-1`` for unreached. This is
    the frontier form: the boolean product of a frontier row-vector with the adjacency IS the
    next frontier, so BFS on 59,524 wallets is ``max_hops`` sparse products."""

    n = adj.shape[0]
    level = np.full(n, -1, dtype=np.int64)
    level[seeds] = 0
    frontier = np.zeros(n, dtype=bool)
    frontier[seeds] = True
    m = adj.binarize().m
    for hop in range(1, max_hops + 1):
        nxt = (sp.csr_array(frontier.astype(np.float64).reshape(1, -1)) @ m).toarray().ravel() > 0
        nxt &= level < 0
        if not nxt.any():
            break
        level[nxt] = hop
        frontier = nxt
    return level


def d4_reach(
    *, max_hops: int = 3, n_null: int = 50, seed_rule: str = "dirty", write: bool = True
) -> dict[str, Any]:
    """Does hop distance to a dirty crew predict a rip, beyond what degree alone gives?

    ``seed_rule="dirty"`` is the REGISTERED arm: the ledger's own ``dirty`` flag,
    ``rips + dumps > 0``. Measured here for the first time, that flag fires for **95.3% of
    crews** -- because ``dumps > 0`` is the market's default outcome (10,585 of 11,111 crews)
    while ``rips > 0`` holds for only 495. So the registered seed set is very nearly "every
    crew", and the registered arm is a test of reachability from almost everywhere.

    ``seed_rule="rips"`` is an EXPLORATORY arm added after seeing that, restricted to crews
    with an actual recorded rip. It is reported and never shipped: it was not registered, so
    a positive there would be a hypothesis, not a result.
    """

    import pandas as pd

    lg, _meta, crew_of = graphs.ledger_crew_sets()
    flags = graphs.ledger_crew_flags()
    if seed_rule == "dirty":
        dirty_mints = {m for m, cid in crew_of.items() if flags.get(int(cid), {}).get("dirty")}
    elif seed_rule == "rips":
        dirty_mints = {m for m, cid in crew_of.items() if flags.get(int(cid), {}).get("rips", 0) > 0}
    else:
        raise ValueError(f"unknown seed_rule {seed_rule!r}")
    dirty_wallets = {
        w for m in dirty_mints if m in lg.a._row_ix for w in lg.a.row_set(m)
    }
    _echo(f"D4 seeds: {len(dirty_mints):,} dirty crew coins, {len(dirty_wallets):,} dirty wallets")

    bw = graphs.birth_snipers(window="all", ex_deployer=True)
    _, panel = graphs.deployer_coins(window="all")
    is_rip = dict(zip(panel["mint"], panel["is_rip"].fillna(False), strict=True))

    df = graphs.load_snipers("all")
    df = df[df["owner"] != df["deployer"]]
    df = df[~df["mint"].isin(dirty_mints)]  # never score a coin that DEFINED a seed

    coin_index = {m: i for i, m in enumerate(sorted(set(df["mint"])))}
    coin_names = list(coin_index)
    rip = np.asarray([bool(is_rip.get(m, False)) for m in coin_names])
    w_of = df["owner"].to_numpy()
    c_of = np.asarray([coin_index[m] for m in df["mint"]], dtype=np.int64)

    def hop_rates(a: Assoc) -> dict[str, Any]:
        prod = co_occurrence(a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
        g = threshold(jaccard(prod, a.degree(axis="row")).drop_diagonal(), CREW_JACCARD)
        seeds = np.asarray([g._row_ix[w] for w in dirty_wallets if w in g._row_ix])
        level = _hop_levels(g, seeds, max_hops)
        wlev = {g.row[i]: int(level[i]) for i in range(len(level))}
        per_leg = np.asarray([wlev.get(w, -1) for w in w_of], dtype=np.int64)
        best = np.full(len(coin_names), np.iinfo(np.int64).max, dtype=np.int64)
        seen = per_leg >= 0
        np.minimum.at(best, c_of[seen], per_leg[seen])
        h = np.where(best == np.iinfo(np.int64).max, -1, best)
        out: dict[str, Any] = {}
        for label in (0, 1, 2, 3, -1):
            if label > max_hops:
                continue
            sel = h == label
            n = int(sel.sum())
            k = int(rip[sel].sum())
            out[str(label)] = {"n": n, "rips": k, "rate": (k / n) if n else float("nan"),
                               "wilson": nulls.wilson(k, n)}
        return out

    observed = hop_rates(bw.a)
    for label, rec in observed.items():
        name = "unreached" if label == "-1" else f"h={label}"
        _echo(f"  {name:>10}: n={rec['n']:>7,}  rips={rec['rips']:>5,}  "
              f"rate={rec['rate']:.5f}  95% CI [{rec['wilson'][0]:.5f}, {rec['wilson'][1]:.5f}]")

    _echo(f"  degree-preserving null, n={n_null}")
    rng = np.random.default_rng(ARM_SEED)
    null_rates: dict[str, list[float]] = {k: [] for k in observed}
    null_ns: dict[str, list[int]] = {k: [] for k in observed}
    for i in range(n_null):
        d = hop_rates(nulls.randomise(bw.a, rng))
        for k in observed:
            null_rates[k].append(d.get(k, {}).get("rate", float("nan")))
            null_ns[k].append(d.get(k, {}).get("n", 0))
        if (i + 1) % 10 == 0:
            _echo(f"    draw {i + 1}/{n_null}")

    inf_rate = observed["-1"]["rate"]
    ships: dict[str, bool] = {}
    summary: dict[str, Any] = {}
    for label in ("1", "2"):
        rec = observed.get(label)
        if not rec or rec["n"] == 0:
            ships[label] = False
            continue
        arr = np.asarray([x for x in null_rates[label] if not math.isnan(x)])
        p95 = float(np.quantile(arr, 0.95)) if arr.size else float("nan")
        null_mean = float(arr.mean()) if arr.size else float("nan")
        beats_inf = rec["wilson"][0] > observed["-1"]["wilson"][1]
        beats_null = bool(rec["rate"] > p95)
        ships[label] = bool(beats_inf and beats_null)
        summary[label] = {
            "rate": rec["rate"], "unreached_rate": inf_rate,
            "null_mean": null_mean,
            "null_p95": p95, "beats_unreached_disjoint_ci": bool(beats_inf),
            "beats_null_p95": beats_null, "ships": ships[label],
            "null_mean_n": float(np.mean(null_ns[label])) if null_ns[label] else float("nan"),
        }
        _echo(f"  h={label}: rate {rec['rate']:.5f} vs unreached {inf_rate:.5f} "
              f"(disjoint CI: {beats_inf}); null mean {null_mean:.5f} "
              f"p95 {p95:.5f} -> ships={ships[label]}")

    # the semiring's own justification: the strongest two-hop crew chain
    prod = co_occurrence(bw.a, axis="row", min_overlap=float(CREW_MIN_OVERLAP))
    g = threshold(jaccard(prod, bw.a.degree(axis="row")).drop_diagonal(), CREW_JACCARD)
    active = np.flatnonzero(g.degree(axis="row") > 0)
    gs = Assoc([g.row[i] for i in active], [g.col[i] for i in active],
               sp.csr_array(g.m[np.ix_(active, active)]))
    from dregg_d4m.assoc import matmul as _mm

    widest = _mm(gs, gs, semiring="max_min", chunk_rows=1024).drop_diagonal()
    direct = gs.to_dict()
    wi, wj, wv = upper_pairs(widest)
    new = [(k, (gs.row[i], gs.col[j])) for k, (i, j) in enumerate(zip(wi, wj, strict=True))
           if (gs.row[i], gs.col[j]) not in direct]
    bottleneck = float(np.max([wv[k] for k, _ in new])) if new else float("nan")
    _echo(f"  max-min (widest path) 2-hop: {len(new):,} pairs with NO direct edge, "
          f"strongest bottleneck {bottleneck:.4f}")

    n_dirty = sum(1 for v in flags.values() if v["dirty"])
    n_ripcrews = sum(1 for v in flags.values() if v["rips"] > 0)
    out = {
        "seed_rule": seed_rule,
        "crew_flag_base_rates": {
            "crews": len(flags), "dirty": n_dirty, "dirty_share": n_dirty / max(len(flags), 1),
            "with_a_rip": n_ripcrews, "rip_share": n_ripcrews / max(len(flags), 1),
        },
        "seeds": {"dirty_crew_coins": len(dirty_mints), "dirty_wallets": len(dirty_wallets)},
        "coins_scored": len(coin_names), "max_hops": max_hops,
        "observed": observed, "null_summary": summary, "n_null": n_null, "seed": ARM_SEED,
        "any_hop_claim_ships": bool(ships.get("1") and ships.get("2")),
        "widest_path": {"new_pairs_at_two_hops": len(new), "strongest_bottleneck": bottleneck,
                        "graph_nodes": gs.shape[0], "direct_pairs": gs.nnz // 2},
    }
    if write:
        run = Run(f"d4_reach_{seed_rule}")
        rows = []
        for label, rec in observed.items():
            rows.append({
                "hops": int(label), "n_coins": rec["n"], "n_rips": rec["rips"],
                "rip_rate": rec["rate"], "ci_low": rec["wilson"][0], "ci_high": rec["wilson"][1],
                "null_mean_rate": summary.get(label, {}).get("null_mean", float("nan")),
                "null_p95_rate": summary.get(label, {}).get("null_p95", float("nan")),
            })
        run.write_table(
            "hop_rip_rates", pd.DataFrame(rows),
            columns={
                "hops": ("min hops from the coin's ex-deployer sniper set to a dirty crew "
                         "wallet; -1 = unreached"),
                "n_coins": "coins at this hop distance",
                "n_rips": "of those, coins labelled is_rip in the panel",
                "rip_rate": "n_rips / n_coins",
                "ci_low": "Wilson 95% lower bound",
                "ci_high": "Wilson 95% upper bound",
                "null_mean_rate": "mean rip rate at this hop over degree-preserving draws",
                "null_p95_rate": "95th percentile of that null",
            },
        )
        run.meta = out
        run.finish(provenance=[bw.prov.to_json(), lg.prov.to_json()],
                   params={"crew_jaccard": CREW_JACCARD, "max_hops": max_hops,
                           "n_null": n_null, "seed": ARM_SEED, "seed_rule": seed_rule})
    return out


# =====================================================================================
# D5 -- the caller matrix and its feasibility veto
# =====================================================================================


def d5_caller_feasibility(*, write: bool = True) -> dict[str, Any]:
    """Run the repo's OWN feasibility gate on C before computing any caller statistic."""

    from studies.svn_cotrading import feasibility_gate, max_feasible_wallets

    cg = graphs.caller_coins()
    c = cg.a
    deg = c.degree(axis="row")
    n_wallets, n_index = c.shape
    typical = int(np.median(deg)) if deg.size else 0
    active = int(np.quantile(deg, 0.90)) if deg.size else 0

    gates = {}
    for name, floor in (("median_author", max(typical, 1)), ("p90_author", max(active, 1))):
        g = feasibility_gate(
            n_wallets=n_wallets, n_index_elements=n_index, tokens_per_wallet=floor
        )
        gates[name] = g.to_json()
        gates[name]["max_feasible_wallets_at_this_floor"] = max_feasible_wallets(
            n_index_elements=n_index, tokens_per_wallet=floor
        )
    feasible = any(g["feasible"] for g in gates.values())
    _echo(f"D5 caller matrix: {n_wallets:,} authors x {n_index:,} mints, {c.nnz:,} pairs")
    for name, g in gates.items():
        _echo(f"  {name} (N={g['tokens_per_wallet']}): feasible={g['feasible']}  "
              f"log10 threshold {g['log10_bonferroni_threshold']:.3f} vs best attainable "
              f"{g['log10_min_attainable_p']:.3f}; universe cap "
              f"{g['max_feasible_wallets_at_this_floor']}")
    out = {
        "n_authors": n_wallets, "n_mints": n_index, "n_pairs": c.nnz,
        "author_degree": {"median": typical, "p90": active, "max": int(deg.max()) if deg.size else 0},
        "coin_degree_max": int(c.degree(axis="col").max()) if c.nnz else 0,
        "gates": gates, "feasible": feasible,
        "verdict": (
            "VETO -- no caller co-occurrence statistic is reported" if not feasible
            else "feasible at the stated activity floor"
        ),
    }
    if write:
        import pandas as pd

        run = Run("d5_caller")
        run.write_table(
            "author_degree",
            pd.DataFrame({"author": list(c.row), "n_mints": deg.astype(np.int64)}),
            columns={"author": "callout author handle",
                     "n_mints": "distinct mints this author was recorded naming"},
        )
        run.meta = out
        run.finish(provenance=[cg.prov.to_json()], params={"alpha": 0.01})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m dregg_d4m", description=__doc__)
    ap.add_argument("analysis", choices=["d0", "d1", "d2", "d3", "d4", "d5", "all"])
    ap.add_argument("--n-null", type=int, default=200)
    ap.add_argument("--n-query", type=int, default=3000)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    write = not args.no_write

    if args.analysis in ("d0", "all"):
        from dregg_d4m import parity

        rep = parity.compare(n_query=args.n_query)
        rows = rep.pop("rows")
        if write:
            import pandas as pd

            run = Run("d0_parity")
            run.write_table(
                "parity_rows", pd.DataFrame(rows),
                columns={
                    "mint": "query coin (never stored in the ledger)",
                    "launch_set_size": "distinct ex-deployer birth-slot wallets",
                    "ledger_matched_mint": "crew_match's chosen stored coin",
                    "ledger_jaccard": "crew_match's Jaccard",
                    "ledger_overlap": "crew_match's overlap",
                    "algebra_matched_mint": "the algebra's chosen stored coin",
                    "algebra_jaccard": "the algebra's Jaccard",
                    "algebra_overlap": "the algebra's overlap",
                    "algebra_candidates": "stored coins with overlap >= min_overlap",
                    "algebra_ties_at_best": "candidates tied at the best Jaccard",
                    "untruncated_jaccard": "the algebra's Jaccard with no LIMIT 200",
                    "untruncated_ties_at_best": "ties at the best Jaccard, untruncated",
                    "untruncated_tied_crews": "distinct crew ids among those tied candidates",
                    "ledger_untruncated_jaccard": "crew_match with the LIMIT lifted",
                    "ledger_crew_id": "the crew id crew_match named",
                    "agree_numeric": "overlap and Jaccard agree",
                    "agree_exact": "matched_mint also agrees",
                },
            )
            lg, _m, _c = graphs.ledger_crew_sets()
            bw = graphs.birth_snipers(window="all")
            run.meta = rep
            run.finish(provenance=[bw.prov.to_json(), lg.prov.to_json()],
                       params={**rep["thresholds"], "seed": rep["seed"],
                               "n_query_coins": rep["n_query_coins"]})
        print(json.dumps(rep, indent=2, default=str))
    if args.analysis in ("d1", "all"):
        print(json.dumps(d1_crew_graph(n_null=args.n_null, write=write), indent=2, default=str))
    if args.analysis in ("d2", "d3", "all"):
        d2 = d2_communities(n_null=args.n_null, write=write)
        labels, wallets = d2.pop("_labels"), d2.pop("_wallets")
        d2.pop("_active", None)
        if args.analysis in ("d2", "all"):
            print(json.dumps(d2, indent=2, default=str))
        if args.analysis in ("d3", "all"):
            print(json.dumps(d3_territory(labels, wallets, n_null=args.n_null, write=write),
                             indent=2, default=str))
    if args.analysis in ("d4", "all"):
        print(json.dumps(d4_reach(n_null=min(args.n_null, 50), write=write), indent=2, default=str))
    if args.analysis in ("d5", "all"):
        print(json.dumps(d5_caller_feasibility(write=write), indent=2, default=str))
    return 0
