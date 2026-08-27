"""The registered tabular workhorses, dependency-light: L2 logistic (IRLS via pyarrow
compute kernels) and a deterministic histogram gradient-boosted tree model (pure Python).

Both are exactly the v1.4 spec: logistic = L2 lambda 1.0 on TRAIN-standardized features
(clip +-8 sd), Newton/IRLS <= 50 iterations; GBM = 32-bin TRAIN-quantile histograms,
depth 2, learning rate 0.1, <= 150 trees, min leaf weight 40, leaf L2 1.0, no
subsampling, tree count chosen on the last-15%-of-TRAIN validation slice only. Sample
weights (1 / instants-in-round) flow through fitting; nothing here ever sees a holdout
row during fitting.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import exp, log, sqrt

import pyarrow as pa
import pyarrow.compute as pc

CLIP_SD = 8.0
LOGISTIC_L2 = 1.0
LOGISTIC_MAX_ITER = 50
GBM_BINS = 32
GBM_DEPTH = 2
GBM_LR = 0.1
GBM_MAX_TREES = 150
GBM_MIN_LEAF_W = 40.0
GBM_LEAF_L2 = 1.0
P_EPS = 1e-12


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + exp(-z))
    e = exp(z)
    return e / (1.0 + e)


def logloss(preds: list[float], y: list[int], w: list[float]) -> float:
    total = sum(w)
    s = 0.0
    for p, yi, wi in zip(preds, y, w, strict=True):
        p = min(max(p, P_EPS), 1.0 - P_EPS)
        s += -wi * (log(p) if yi else log(1.0 - p))
    return s / total if total else 0.0


# ------------------------------------------------------------------ standardization
@dataclass(frozen=True)
class Standardizer:
    means: tuple[float, ...]
    stds: tuple[float, ...]

    @classmethod
    def fit(cls, rows: list[list[float]]) -> Standardizer:
        n = len(rows)
        f = len(rows[0])
        means = [sum(r[j] for r in rows) / n for j in range(f)]
        stds = []
        for j in range(f):
            var = sum((r[j] - means[j]) ** 2 for r in rows) / n
            stds.append(max(sqrt(var), 1e-9))
        return cls(tuple(means), tuple(stds))

    def apply(self, rows: list[list[float]]) -> list[list[float]]:
        out = []
        for r in rows:
            z = [(v - m) / s for v, m, s in zip(r, self.means, self.stds, strict=True)]
            out.append([min(max(v, -CLIP_SD), CLIP_SD) for v in z])
        return out


# ------------------------------------------------------------------ logistic (IRLS)
@dataclass(frozen=True)
class LogisticModel:
    std: Standardizer
    beta: tuple[float, ...]  # [intercept, coef...]
    iterations: int
    converged: bool

    def predict(self, rows: list[list[float]]) -> list[float]:
        zr = self.std.apply(rows)
        b0, coefs = self.beta[0], self.beta[1:]
        return [
            sigmoid(b0 + sum(c * v for c, v in zip(coefs, r, strict=True))) for r in zr
        ]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting; small dense systems only."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-30:
            m[col][col] += 1e-9
            piv = col
        m[col], m[piv] = m[piv], m[col]
        inv = 1.0 / m[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col] * inv
            if factor == 0.0:
                continue
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logistic(
    rows: list[list[float]],
    y: list[int],
    w: list[float],
    *,
    l2: float = LOGISTIC_L2,
    max_iter: int = LOGISTIC_MAX_ITER,
    tol: float = 1e-7,
) -> LogisticModel:
    std = Standardizer.fit(rows)
    zr = std.apply(rows)
    f = len(zr[0])
    cols = [pa.array([r[j] for r in zr], pa.float64()) for j in range(f)]
    ay = pa.array([float(v) for v in y], pa.float64())
    aw = pa.array(w, pa.float64())
    one = pa.scalar(1.0, pa.float64())
    beta = [0.0] * (f + 1)

    def forward(b: list[float]) -> tuple[object, float]:
        z = None
        for j in range(f):
            term = pc.multiply(cols[j], b[j + 1])
            z = term if z is None else pc.add(z, term)
        z = pc.add(z, b[0]) if z is not None else pa.array([b[0]] * len(y), pa.float64())
        p = pc.divide(one, pc.add(pc.exp(pc.negate(z)), one))
        p = pc.min_element_wise(pc.max_element_wise(p, P_EPS), 1.0 - P_EPS)
        nll = pc.sum(
            pc.negate(
                pc.multiply(
                    aw,
                    pc.add(
                        pc.multiply(ay, pc.ln(p)),
                        pc.multiply(pc.subtract(one, ay), pc.ln(pc.subtract(one, p))),
                    ),
                )
            )
        ).as_py()
        penalty = 0.5 * l2 * sum(v * v for v in b[1:])
        return p, nll + penalty

    p, loss = forward(beta)
    iterations = 0
    converged = False
    for iterations in range(1, max_iter + 1):  # noqa: B007 — count reported in the fit
        resid = pc.multiply(aw, pc.subtract(p, ay))
        s = pc.multiply(aw, pc.multiply(p, pc.subtract(one, p)))
        grad = [pc.sum(resid).as_py()]
        grad += [
            pc.sum(pc.multiply(cols[j], resid)).as_py() + l2 * beta[j + 1] for j in range(f)
        ]
        hess = [[0.0] * (f + 1) for _ in range(f + 1)]
        hess[0][0] = pc.sum(s).as_py()
        u = [pc.multiply(cols[j], s) for j in range(f)]
        for j in range(f):
            hj0 = pc.sum(u[j]).as_py()
            hess[0][j + 1] = hess[j + 1][0] = hj0
            for k in range(j, f):
                v = pc.sum(pc.multiply(u[j], cols[k])).as_py()
                if j == k:
                    v += l2
                hess[j + 1][k + 1] = hess[k + 1][j + 1] = v
        step = _solve(hess, grad)
        scale = 1.0
        for _ in range(12):
            trial = [b - scale * d for b, d in zip(beta, step, strict=True)]
            p_new, loss_new = forward(trial)
            if loss_new <= loss + 1e-12:
                break
            scale *= 0.5
        beta, p, prev = trial, p_new, loss
        loss = loss_new
        if max(abs(scale * d) for d in step) < tol or abs(prev - loss) < 1e-10:
            converged = True
            break
    return LogisticModel(std, tuple(beta), iterations, converged)


# ------------------------------------------------------------------ histogram GBM
@dataclass(frozen=True)
class GBMModel:
    edges: tuple[tuple[float, ...], ...]
    trees: tuple[dict, ...]
    f0: float
    lr: float
    best_iteration: int
    val_history: tuple[float, ...]

    def _codes(self, row: list[float]) -> list[int]:
        return [bisect_right(self.edges[j], row[j]) for j in range(len(self.edges))]

    def predict(self, rows: list[list[float]]) -> list[float]:
        out = []
        for row in rows:
            codes = self._codes(row)
            score = self.f0
            for tree in self.trees:
                score += self.lr * _tree_value(tree, codes)
            out.append(sigmoid(score))
        return out


def _tree_value(node: dict, codes: list[int]) -> float:
    while "leaf" not in node:
        node = node["left"] if codes[node["feat"]] <= node["cut"] else node["right"]
    return node["leaf"]


def quantile_edges(values: list[float], bins: int = GBM_BINS) -> tuple[float, ...]:
    s = sorted(values)
    n = len(s)
    edges: list[float] = []
    for k in range(1, bins):
        e = s[min(n - 1, max(0, round(k * (n - 1) / bins)))]
        if not edges or e > edges[-1]:
            edges.append(e)
    return tuple(edges)


def _best_split(
    hg: list[float], hh: list[float], hw: list[float], l2: float, min_leaf_w: float
) -> tuple[float, int] | None:
    total_g, total_h, total_w = sum(hg), sum(hh), sum(hw)
    parent = total_g * total_g / (total_h + l2)
    best = None
    gl = hl = wl = 0.0
    for b in range(len(hg) - 1):
        gl += hg[b]
        hl += hh[b]
        wl += hw[b]
        wr = total_w - wl
        if wl < min_leaf_w or wr < min_leaf_w:
            continue
        gr, hr = total_g - gl, total_h - hl
        gain = gl * gl / (hl + l2) + gr * gr / (hr + l2) - parent
        if gain > 1e-12 and (best is None or gain > best[0]):
            best = (gain, b)
    return best


def _build_node(
    codes_t: list[list[int]],
    idx: list[int],
    g: list[float],
    h: list[float],
    w: list[float],
    depth: int,
    l2: float,
    min_leaf_w: float,
    n_bins_per_feat: list[int],
) -> dict:
    total_g = sum(g[i] for i in idx)
    total_h = sum(h[i] for i in idx)
    if depth == 0 or total_h <= 0:
        return {"leaf": -total_g / (total_h + l2)}
    best = None
    for f, codes in enumerate(codes_t):
        nb = n_bins_per_feat[f]
        hg = [0.0] * nb
        hh = [0.0] * nb
        hw = [0.0] * nb
        for i in idx:
            c = codes[i]
            hg[c] += g[i]
            hh[c] += h[i]
            hw[c] += w[i]
        found = _best_split(hg, hh, hw, l2, min_leaf_w)
        if found and (best is None or found[0] > best[0]):
            best = (found[0], f, found[1])
    if best is None:
        return {"leaf": -total_g / (total_h + l2)}
    _, f, cut = best
    codes = codes_t[f]
    left = [i for i in idx if codes[i] <= cut]
    right = [i for i in idx if codes[i] > cut]
    return {
        "feat": f,
        "cut": cut,
        "left": _build_node(codes_t, left, g, h, w, depth - 1, l2, min_leaf_w, n_bins_per_feat),
        "right": _build_node(codes_t, right, g, h, w, depth - 1, l2, min_leaf_w, n_bins_per_feat),
    }


def fit_gbm(
    rows: list[list[float]],
    y: list[int],
    w: list[float],
    val_rows: list[list[float]],
    val_y: list[int],
    val_w: list[float],
    *,
    max_trees: int = GBM_MAX_TREES,
    lr: float = GBM_LR,
    depth: int = GBM_DEPTH,
    l2: float = GBM_LEAF_L2,
    min_leaf_w: float = GBM_MIN_LEAF_W,
    bins: int = GBM_BINS,
) -> GBMModel:
    n = len(rows)
    f = len(rows[0])
    edges = tuple(quantile_edges([r[j] for r in rows], bins) for j in range(f))
    codes_t = [[bisect_right(edges[j], r[j]) for r in rows] for j in range(f)]
    val_codes_t = [[bisect_right(edges[j], r[j]) for r in val_rows] for j in range(f)]
    n_bins = [len(edges[j]) + 1 for j in range(f)]
    total_w = sum(w)
    base = sum(wi * yi for wi, yi in zip(w, y, strict=True)) / total_w
    base = min(max(base, P_EPS), 1.0 - P_EPS)
    f0 = log(base / (1.0 - base))
    scores = [f0] * n
    val_scores = [f0] * len(val_rows)
    all_idx = list(range(n))
    trees: list[dict] = []
    history: list[float] = []
    for _ in range(max_trees):
        g = []
        h = []
        for i in range(n):
            p = sigmoid(scores[i])
            g.append(w[i] * (p - y[i]))
            h.append(w[i] * p * (1.0 - p))
        tree = _build_node(codes_t, all_idx, g, h, w, depth, l2, min_leaf_w, n_bins)
        if "leaf" in tree and tree["leaf"] == 0.0:
            break
        trees.append(tree)
        for i in range(n):
            scores[i] += lr * _tree_value(tree, [codes_t[j][i] for j in range(f)])
        for i in range(len(val_rows)):
            val_scores[i] += lr * _tree_value(tree, [val_codes_t[j][i] for j in range(f)])
        if val_rows:
            history.append(
                logloss([sigmoid(s) for s in val_scores], val_y, val_w)
            )
    best_iter = (history.index(min(history)) + 1) if history else len(trees)
    return GBMModel(edges, tuple(trees[:best_iter]), f0, lr, best_iter, tuple(history))
