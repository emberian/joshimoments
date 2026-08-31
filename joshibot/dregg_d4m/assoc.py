"""The associative-array layer: string-keyed sparse matrices and the products we need.

WHAT THIS IS
------------
``Assoc`` is a scipy CSR matrix plus two key tuples and their inverse dicts. It is
deliberately SMALL -- this is infrastructure for `dregg_d4m.analyses`, not a library. The
operations here are exactly the ones the pre-registered analyses use, and nothing else:

* ``Assoc.from_tuples``     -- build from (row_key, col_key, value) triples
* ``Assoc.T``               -- transpose
* ``matmul``                -- sparse product over a configurable SEMIRING
* ``co_occurrence``         -- ``A A'`` or ``A' A`` computed in row chunks with pruning,
                               which is the only form that fits at our scale
* ``jaccard`` / ``overlap_coeff`` / ``cosine`` -- normalisations applied TO a product
* ``Assoc.select``          -- row/col selection by name, list, regex or predicate
* ``Assoc.degree`` / ``rowsum`` / ``colsum``
* ``Assoc.binarize`` / ``find`` / ``triples``

THE SEMIRINGS, and why these three
----------------------------------
``plus_times`` (the default, scipy's own product) is the workhorse: over a 0/1 incidence,
``(B' B)[i, j]`` is the number of wallets coin i and coin j share. That single product is
what ``dregg_screen.ledger.crew_match`` computes one candidate at a time, and what
``operator_crime``'s cmd_graph arm computes one coin pair at a time.

``or_and`` (boolean) answers reachability -- "is there ANY shared coin", "is this wallet
within two hops of a dirty crew" -- where the count is not wanted and would only invite a
threshold nobody registered. Implemented as a binarised plus-times followed by a binarise,
which is the standard identity and lets scipy do the work.

``max_plus`` answers "what is the STRONGEST chain", not "how many chains": over a
weighted graph, ``(A max-plus A)[i, j] = max_k (A[i,k] + A[k,j])`` is the best two-hop path,
an object plus-times cannot express at all (it would SUM every path, so a node with many
weak links beats a node with one strong one). ``min_plus`` is the same kernel on negated
values, because shortest-path and longest-path are one piece of code.

``max_min`` is the WIDEST-PATH (bottleneck) semiring, ``max_k min(A[i,k], A[k,j])``, and it
is the one that is actually correct for chaining SIMILARITIES: a two-hop crew link is only
as strong as its weaker leg, and adding two Jaccards would let 0.11 + 0.99 beat 0.55 + 0.54.
``studies/REGISTRATION_d4m.md`` names this quantity by its formula while calling it
"max-plus"; the formula is what D4 uses.

We did NOT implement a general semiring dispatch. A generic ``(oplus, otimes)`` interface
would look more like D4M and would be a lie about what is tested: only these have
hand-checked tests, so only these exist.

SCALE NOTE
----------
``max_plus`` materialises the product's full flop expansion in chunks; it is correct but it
is not scipy's C loop, so it is for the small and medium matrices where the semiring earns
its place (crew graphs, community graphs), not for the 636k-incidence base products. That
limit is enforced by ``chunk_rows`` rather than by hoping.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Literal

import numpy as np
import scipy.sparse as sp

Semiring = Literal["plus_times", "or_and", "max_plus", "min_plus", "max_min"]

#: Selection argument: None (all), one key, an iterable of keys, a compiled regex, or a
#: predicate over the key string.
Selector = None | str | Iterable[str] | re.Pattern[str] | Callable[[str], bool]


class AssocError(ValueError):
    """Raised for shape/key mismatches -- always a programming error, never data."""


def _unique_keys(keys: Sequence[str], what: str) -> tuple[str, ...]:
    out = tuple(keys)
    if len(set(out)) != len(out):
        raise AssocError(f"{what} keys are not unique")
    return out


class Assoc:
    """A string-keyed sparse matrix. Immutable by convention; every op returns a new one."""

    __slots__ = ("_col", "_col_ix", "_m", "_row", "_row_ix")

    def __init__(self, row: Sequence[str], col: Sequence[str], m: sp.csr_array) -> None:
        self._row = _unique_keys(row, "row")
        self._col = _unique_keys(col, "col")
        if m.shape != (len(self._row), len(self._col)):
            raise AssocError(f"matrix shape {m.shape} != key shape {(len(self._row), len(self._col))}")
        self._m = m
        self._row_ix = {k: i for i, k in enumerate(self._row)}
        self._col_ix = {k: i for i, k in enumerate(self._col)}

    # -- construction ------------------------------------------------------------------

    @classmethod
    def from_tuples(
        cls,
        rows: Sequence[str],
        cols: Sequence[str],
        vals: Sequence[float] | float = 1.0,
        *,
        agg: Literal["sum", "max", "min", "first"] = "sum",
        row_keys: Sequence[str] | None = None,
        col_keys: Sequence[str] | None = None,
        dtype: Any = np.float64,
    ) -> Assoc:
        """Build from parallel triple arrays.

        ``agg`` decides what a repeated (row, col) means. ``sum`` is scipy's own duplicate
        handling and is right for counts; ``max``/``min``/``first`` are spelled out because
        "a wallet's SOL on a coin" and "a wallet's leg count on a coin" are different
        associative arrays over the same keys and silently summing one of them is a bug
        that produces a plausible number.
        """

        if len(rows) != len(cols):
            raise AssocError("rows and cols must be the same length")
        n = len(rows)
        values = np.full(n, float(vals), dtype=dtype) if np.isscalar(vals) else np.asarray(vals, dtype=dtype)
        if values.shape[0] != n:
            raise AssocError("vals must be scalar or the same length as rows")

        rkeys = tuple(row_keys) if row_keys is not None else tuple(_sorted_unique(rows))
        ckeys = tuple(col_keys) if col_keys is not None else tuple(_sorted_unique(cols))
        rix = {k: i for i, k in enumerate(rkeys)}
        cix = {k: i for i, k in enumerate(ckeys)}
        try:
            ri = np.fromiter((rix[r] for r in rows), dtype=np.int64, count=n)
            ci = np.fromiter((cix[c] for c in cols), dtype=np.int64, count=n)
        except KeyError as exc:  # explicit key_keys given that do not cover the data
            raise AssocError(f"tuple key not present in the supplied key list: {exc}") from exc

        if agg in ("max", "min", "first") and n:
            ri, ci, values = _dedupe(ri, ci, values, agg, n_cols=len(ckeys))
        m = sp.coo_array((values, (ri, ci)), shape=(len(rkeys), len(ckeys)), dtype=dtype).tocsr()
        m.sum_duplicates()
        m.eliminate_zeros()
        m.sort_indices()
        return cls(rkeys, ckeys, m)

    @classmethod
    def from_matrix(cls, row: Sequence[str], col: Sequence[str], m: sp.spmatrix | sp.sparray) -> Assoc:
        csr = sp.csr_array(m)
        csr.sort_indices()
        return cls(row, col, csr)

    # -- shape / keys ------------------------------------------------------------------

    @property
    def row(self) -> tuple[str, ...]:
        return self._row

    @property
    def col(self) -> tuple[str, ...]:
        return self._col

    @property
    def m(self) -> sp.csr_array:
        return self._m

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self._row), len(self._col))

    @property
    def nnz(self) -> int:
        return int(self._m.nnz)

    def row_index(self, key: str) -> int:
        return self._row_ix[key]

    def col_index(self, key: str) -> int:
        return self._col_ix[key]

    def __repr__(self) -> str:
        return f"Assoc({len(self._row)}x{len(self._col)}, nnz={self.nnz})"

    # -- structural ops ----------------------------------------------------------------

    @property
    def T(self) -> Assoc:
        return Assoc(self._col, self._row, sp.csr_array(self._m.T))

    def binarize(self) -> Assoc:
        m = self._m.copy()
        m.data = np.ones_like(m.data)
        return Assoc(self._row, self._col, m)

    def select(self, rows: Selector = None, cols: Selector = None) -> Assoc:
        """Sub-array by key. Selectors: None, a key, an iterable of keys, a compiled regex
        (matched with ``search``), or a predicate. Missing names are dropped, not raised --
        a watchlist that names a wallet we never saw is a normal fact about the data."""

        ri = _resolve(self._row, self._row_ix, rows)
        ci = _resolve(self._col, self._col_ix, cols)
        m = sp.csr_array(self._m[np.ix_(ri, ci)]) if ri.size and ci.size else sp.csr_array(
            (len(ri), len(ci)), dtype=self._m.dtype
        )
        return Assoc([self._row[i] for i in ri], [self._col[j] for j in ci], m)

    def restrict_degree(self, *, axis: Literal["row", "col"], max_degree: int) -> Assoc:
        """Drop rows (or cols) with more than ``max_degree`` nonzeros.

        A wallet on 13,847 coins co-occurs with everything by construction. This is the
        same exclusion ``cluster_map`` makes at ``k > 50`` on its events, made explicit and
        reported rather than folded into a query."""

        deg = self.degree(axis=axis)
        keep = np.flatnonzero(deg <= max_degree)
        if axis == "row":
            return Assoc([self._row[i] for i in keep], self._col, sp.csr_array(self._m[keep, :]))
        return Assoc(self._row, [self._col[j] for j in keep], sp.csr_array(self._m[:, keep]))

    def drop_diagonal(self) -> Assoc:
        """Zero out (k, k) for keys present in both dimensions -- a co-occurrence array's
        diagonal is the row's own degree and is never an edge."""

        m = self._m.tolil()
        for k, i in self._row_ix.items():
            j = self._col_ix.get(k)
            if j is not None:
                m[i, j] = 0
        out = sp.csr_array(m.tocsr())
        out.eliminate_zeros()
        return Assoc(self._row, self._col, out)

    # -- reductions --------------------------------------------------------------------

    def degree(self, *, axis: Literal["row", "col"] = "row") -> np.ndarray:
        """Nonzero COUNT per row/col (D4M's ``Adj`` degree, not the value sum)."""

        if axis == "row":
            return np.diff(self._m.indptr).astype(np.int64)
        return np.bincount(self._m.indices, minlength=self.shape[1]).astype(np.int64)

    def rowsum(self) -> np.ndarray:
        return np.asarray(self._m.sum(axis=1)).ravel()

    def colsum(self) -> np.ndarray:
        return np.asarray(self._m.sum(axis=0)).ravel()

    # -- extraction --------------------------------------------------------------------

    def triples(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(row_idx, col_idx, value) as arrays -- the fast path for artifact writing."""

        coo = self._m.tocoo()
        return coo.row.astype(np.int64), coo.col.astype(np.int64), coo.data

    def find(self) -> Iterator[tuple[str, str, float]]:
        """D4M's ``find``: iterate (row_key, col_key, value). Row-major, keys sorted within
        a row because the CSR is index-sorted."""

        ri, ci, v = self.triples()
        for i, j, val in zip(ri, ci, v, strict=True):
            yield self._row[i], self._col[j], float(val)

    def to_dict(self) -> dict[tuple[str, str], float]:
        return {(r, c): v for r, c, v in self.find()}

    def row_set(self, key: str) -> set[str]:
        """The set of col keys nonzero in this row -- the bridge back to the set-based
        instruments, used by the parity test."""

        i = self._row_ix[key]
        lo, hi = self._m.indptr[i], self._m.indptr[i + 1]
        return {self._col[j] for j in self._m.indices[lo:hi]}

    def row_sets(self) -> list[set[int]]:
        """Row-major list of column INDEX sets -- the exact input shape
        ``studies.operator_crime._curveball`` takes."""

        ip, ind = self._m.indptr, self._m.indices
        return [set(ind[ip[i] : ip[i + 1]].tolist()) for i in range(self.shape[0])]

    @classmethod
    def from_row_sets(
        cls, rows: Sequence[set[int]], row_keys: Sequence[str], col_keys: Sequence[str]
    ) -> Assoc:
        """Inverse of ``row_sets`` -- rebuild after a curveball randomisation."""

        counts = np.fromiter((len(r) for r in rows), dtype=np.int64, count=len(rows))
        indptr = np.zeros(len(rows) + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        indices = np.fromiter((j for r in rows for j in sorted(r)), dtype=np.int64, count=int(counts.sum()))
        data = np.ones(indices.shape[0], dtype=np.float64)
        m = sp.csr_array((data, indices, indptr), shape=(len(rows), len(col_keys)))
        return cls(row_keys, col_keys, m)

    # -- products ----------------------------------------------------------------------

    def __matmul__(self, other: Assoc) -> Assoc:
        return matmul(self, other)


def _sorted_unique(keys: Iterable[str]) -> list[str]:
    return sorted(set(keys))


def _dedupe(
    ri: np.ndarray, ci: np.ndarray, values: np.ndarray, agg: str, *, n_cols: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collapse duplicate (row, col) with max/min/first before scipy sums them."""

    flat = ri * np.int64(n_cols) + ci
    if agg == "first":
        order = np.arange(flat.shape[0])
        keep_order = np.lexsort((order, flat))
    else:
        keep_order = np.argsort(flat, kind="stable")
    f = flat[keep_order]
    v = values[keep_order]
    starts = np.flatnonzero(np.concatenate(([True], f[1:] != f[:-1])))
    if agg == "first":
        out_v = v[starts]
    else:
        red = np.maximum.reduceat if agg == "max" else np.minimum.reduceat
        out_v = red(v, starts)
    keep = keep_order[starts]
    return ri[keep], ci[keep], out_v


def _resolve(keys: tuple[str, ...], index: dict[str, int], sel: Selector) -> np.ndarray:
    if sel is None:
        return np.arange(len(keys), dtype=np.int64)
    if isinstance(sel, str):
        i = index.get(sel)
        return np.array([] if i is None else [i], dtype=np.int64)
    if isinstance(sel, re.Pattern):
        return np.fromiter(
            (i for i, k in enumerate(keys) if sel.search(k)), dtype=np.int64
        )
    if callable(sel):
        return np.fromiter((i for i, k in enumerate(keys) if sel(k)), dtype=np.int64)
    picked = [index[k] for k in sel if k in index]
    return np.asarray(picked, dtype=np.int64)


# -- semirings -------------------------------------------------------------------------


def matmul(a: Assoc, b: Assoc, *, semiring: Semiring = "plus_times", chunk_rows: int = 4096) -> Assoc:
    """``a`` (m x k) times ``b`` (k x n) over ``semiring``. Inner keys must match exactly.

    Requiring the inner KEYS to be equal (not merely the inner dimension) is the whole
    point of keeping the dictionaries: a product between two matrices built from different
    corpora silently produces garbage if you only check shapes."""

    if a.col != b.row:
        raise AssocError(
            f"inner keys differ: {len(a.col)} col keys vs {len(b.row)} row keys "
            f"(first mismatch at {_first_mismatch(a.col, b.row)})"
        )
    if semiring == "plus_times":
        m = sp.csr_array(a.m @ b.m)
    elif semiring == "or_and":
        m = sp.csr_array(a.binarize().m @ b.binarize().m)
        m.data = np.ones_like(m.data)
    elif semiring in ("max_plus", "min_plus", "max_min"):
        # min-plus is max-plus on negated values; max-min needs no sign trick because
        # min(-x, -y) == -max(x, y) would flip it into min-max, which nobody asked for.
        sign = -1.0 if semiring == "min_plus" else 1.0
        combine = np.minimum if semiring == "max_min" else np.add
        m = _max_plus(
            sp.csr_array((a.m.data * sign, a.m.indices, a.m.indptr), shape=a.shape),
            sp.csr_array((b.m.data * sign, b.m.indices, b.m.indptr), shape=b.shape),
            chunk_rows=chunk_rows,
            combine=combine,
        )
        m.data *= sign
    else:
        raise AssocError(f"unknown semiring {semiring!r}")
    m.eliminate_zeros()
    m.sort_indices()
    return Assoc(a.row, b.col, m)


def _first_mismatch(left: tuple[str, ...], right: tuple[str, ...]) -> str:
    for i, (x, y) in enumerate(zip(left, right, strict=False)):
        if x != y:
            return f"position {i}: {x!r} vs {y!r}"
    return "length"


def _ragged_gather(starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Indices ``concat(range(s, s+c) for s, c in zip(starts, counts))``, vectorised."""

    keep = counts > 0
    starts, counts = starts[keep], counts[keep]
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64)
    out = np.ones(total, dtype=np.int64)
    out[0] = starts[0]
    if starts.shape[0] > 1:
        offs = np.cumsum(counts)[:-1]
        out[offs] = starts[1:] - (starts[:-1] + counts[:-1]) + 1
    return np.cumsum(out)


def _max_plus(
    a: sp.csr_array, b: sp.csr_array, *, chunk_rows: int, combine: Any = np.add
) -> sp.csr_array:
    """``out[i, j] = max_k combine(a[i, k], b[k, j])`` over the structural nonzeros.

    The sparsity pattern is the boolean product's; the values are a segment-max over the
    flop expansion. Done in row chunks so the expansion never exceeds one chunk's flops.
    """

    n_rows, n_cols = a.shape[0], b.shape[1]
    bp, bi, bd = b.indptr, b.indices, b.data
    out_indptr = np.zeros(n_rows + 1, dtype=np.int64)
    parts_i: list[np.ndarray] = []
    parts_v: list[np.ndarray] = []
    for lo in range(0, n_rows, chunk_rows):
        hi = min(lo + chunk_rows, n_rows)
        blk = a[lo:hi, :]
        nz_per_row = np.diff(blk.indptr)
        rows_of_nz = np.repeat(np.arange(hi - lo, dtype=np.int64), nz_per_row)
        k_idx, k_val = blk.indices, blk.data
        cnt = (bp[k_idx + 1] - bp[k_idx]).astype(np.int64)
        gather = _ragged_gather(bp[k_idx].astype(np.int64), cnt)
        if gather.size == 0:
            out_indptr[lo + 1 : hi + 1] = out_indptr[lo]
            continue
        out_rows = np.repeat(rows_of_nz, cnt)
        out_cols = bi[gather].astype(np.int64)
        out_vals = combine(bd[gather], np.repeat(k_val, cnt))
        flat = out_rows * np.int64(n_cols) + out_cols
        order = np.argsort(flat, kind="stable")
        f, v = flat[order], out_vals[order]
        starts = np.flatnonzero(np.concatenate(([True], f[1:] != f[:-1])))
        red_v = np.maximum.reduceat(v, starts)
        red_f = f[starts]
        red_rows = (red_f // n_cols).astype(np.int64)
        parts_i.append((red_f - red_rows * n_cols).astype(np.int64))
        parts_v.append(red_v)
        per_row = np.bincount(red_rows, minlength=hi - lo)
        out_indptr[lo + 1 : hi + 1] = out_indptr[lo] + np.cumsum(per_row)
    indices = np.concatenate(parts_i) if parts_i else np.empty(0, dtype=np.int64)
    data = np.concatenate(parts_v) if parts_v else np.empty(0, dtype=np.float64)
    return sp.csr_array((data, indices, out_indptr), shape=(n_rows, n_cols))


# -- co-occurrence and normalisation ---------------------------------------------------


def co_occurrence(
    a: Assoc,
    *,
    axis: Literal["row", "col"] = "row",
    min_overlap: float = 1.0,
    chunk_rows: int = 2048,
    other: Assoc | None = None,
) -> Assoc:
    """``A A'`` (axis="row") or ``A' A`` (axis="col") over plus-times, pruned as it goes.

    Pruning INSIDE the chunk loop is not an optimisation, it is what makes the product
    exist: the untruncated coin-coin product over our ex-deployer incidence is 9.8e8
    structural nonzeros, and almost all of them are coin pairs sharing exactly ONE wallet,
    which the shipped instrument already refuses to call a crew (``min_overlap = 2``).

    ``other`` computes a RECTANGULAR co-occurrence -- ``A B'`` (or ``A' B``) with the same
    pruning -- which is the parity test's shape: one launch's set against every stored set.
    """

    left = a if axis == "row" else a.T
    right = (other if axis == "row" else other.T) if other is not None else left
    if left.col != right.col:
        raise AssocError("co_occurrence operands must share their contracted key axis")
    lm, rm_t = left.m, sp.csr_array(right.m.T)
    n_rows = lm.shape[0]
    indptr = np.zeros(n_rows + 1, dtype=np.int64)
    parts_i: list[np.ndarray] = []
    parts_v: list[np.ndarray] = []
    for lo in range(0, n_rows, chunk_rows):
        hi = min(lo + chunk_rows, n_rows)
        prod = sp.csr_array(lm[lo:hi, :] @ rm_t)
        if min_overlap > 1:
            prod.data[prod.data < min_overlap] = 0.0
            prod.eliminate_zeros()
        parts_i.append(prod.indices.astype(np.int64))
        parts_v.append(prod.data)
        indptr[lo + 1 : hi + 1] = indptr[lo] + np.cumsum(np.diff(prod.indptr))
    indices = np.concatenate(parts_i) if parts_i else np.empty(0, dtype=np.int64)
    data = np.concatenate(parts_v) if parts_v else np.empty(0, dtype=np.float64)
    m = sp.csr_array((data, indices, indptr), shape=(n_rows, right.m.shape[0]))
    m.sort_indices()
    return Assoc(left.row, right.row, m)


def _normalise(
    prod: Assoc, left_deg: np.ndarray, right_deg: np.ndarray, kind: str
) -> Assoc:
    ri, ci, v = prod.triples()
    dl, dr = left_deg[ri].astype(np.float64), right_deg[ci].astype(np.float64)
    if kind == "jaccard":
        denom = dl + dr - v
    elif kind == "overlap":
        denom = np.minimum(dl, dr)
    elif kind == "cosine":
        denom = np.sqrt(dl * dr)
    else:  # pragma: no cover -- callers are internal
        raise AssocError(f"unknown normalisation {kind!r}")
    out = np.zeros_like(v)
    ok = denom > 0
    out[ok] = v[ok] / denom[ok]
    m = sp.coo_array((out, (ri, ci)), shape=prod.shape).tocsr()
    m.eliminate_zeros()
    m.sort_indices()
    return Assoc(prod.row, prod.col, m)


def jaccard(prod: Assoc, left_deg: np.ndarray, right_deg: np.ndarray | None = None) -> Assoc:
    """Jaccard applied to a co-occurrence product: ``|A n B| / (|A| + |B| - |A n B|)``.

    ``left_deg`` / ``right_deg`` are the SET SIZES of the operands (their row degrees before
    the product), not sums of the product. This is byte-for-byte the arithmetic in
    ``dregg_screen.ledger.crew_match`` (``union = len(wallets) + set_size - overlap``), which
    is why the parity test can be exact rather than approximate."""

    return _normalise(prod, left_deg, right_deg if right_deg is not None else left_deg, "jaccard")


def overlap_coeff(prod: Assoc, left_deg: np.ndarray, right_deg: np.ndarray | None = None) -> Assoc:
    """Szymkiewicz-Simpson: ``|A n B| / min(|A|, |B|)``. Reported alongside Jaccard because
    it does not punish a small set for matching inside a large one."""

    return _normalise(prod, left_deg, right_deg if right_deg is not None else left_deg, "overlap")


def cosine(prod: Assoc, left_deg: np.ndarray, right_deg: np.ndarray | None = None) -> Assoc:
    """``|A n B| / sqrt(|A| |B|)`` -- cluster_map's degree normalisation, for comparability."""

    return _normalise(prod, left_deg, right_deg if right_deg is not None else left_deg, "cosine")


def upper_pairs(a: Assoc) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strict upper triangle of a SQUARE symmetric Assoc as (i, j, v) with i < j."""

    if a.row != a.col:
        raise AssocError("upper_pairs needs a square Assoc with identical row and col keys")
    ri, ci, v = a.triples()
    keep = ri < ci
    return ri[keep], ci[keep], v[keep]


def threshold(a: Assoc, min_value: float) -> Assoc:
    """Drop entries strictly below ``min_value``. The registered crew-graph cut is applied
    with this, once, so the threshold appears in exactly one place in the code."""

    m = a.m.copy()
    m.data[m.data < min_value] = 0.0
    m.eliminate_zeros()
    return Assoc(a.row, a.col, m)
