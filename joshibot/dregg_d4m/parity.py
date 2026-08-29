"""D0 -- PARITY against ``dregg_screen.ledger.crew_match``. The credibility gate.

The claim this lane rests on is that the shipped crew match is one sparse product with a
Jaccard normalisation. That is either true to the last decimal or the lane is worthless, so
it is tested against the SHIPPED artifact (``state/dregg_screen/ledger/current.sqlite``,
read-only) using coins the ledger has NEVER stored -- the coins of single-launch deployers.
Those are exact stand-ins for a live launch: no self-match can flatter the result.

WHAT IS BEING HELD EQUAL
------------------------
``crew_match`` does, in SQL and Python:

    wallets = sorted(set(launch_set))                      # deduped launch set
    if len(wallets) < min_overlap: return None
    rows = SELECT mint, count(*) AS overlap, set_size, crew_id
           FROM crew_set JOIN crew_coins USING (mint)
           WHERE wallet IN (wallets) GROUP BY mint
           HAVING overlap >= min_overlap                   -- complete scan, no LIMIT
    over all rows: j = overlap / (len(wallets) + set_size - overlap)
    best Jaccard >= min_jaccard wins; ties carried whole (tied_crew_ids), the named
    crew a deterministic representative

The algebra does ``jaccard(co_occurrence(Q, other=L))`` and then applies the SAME rules
to the product. Two details decide whether parity is real or cosmetic:

1. **The union denominator uses the FULL launch-set size**, including launch wallets that
   appear in no stored crew set. Restricting the query matrix to the ledger's wallet
   universe (which the product must do, to share a contraction axis) would shrink
   ``len(wallets)`` and inflate every Jaccard. The full size is carried separately.
2. **Truncation is a RETIRED config, kept here as a measurement.** The instrument used to
   run ``ORDER BY overlap DESC LIMIT 200`` with no tiebreaker; this lane measured that the
   LIMIT could drop the true best match (overlap order is not Jaccard order) and the
   crew-id fix (2026-08-29) removed it — ``crew_match`` now scans every candidate. The
   algebra still emulates the old LIMIT so the cost of any future truncation proposal is a
   number, not a guess; the ledger side no longer has a truncated arm to compare against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from dregg_d4m import graphs
from dregg_d4m.assoc import Assoc, co_occurrence, jaccard


@dataclass(frozen=True, slots=True)
class AlgebraMatch:
    """The algebra's answer, in the shipped instrument's own vocabulary."""

    matched_mint: str
    jaccard: float
    overlap: int
    launch_set_size: int
    matched_set_size: int
    n_candidates: int
    n_ties: int
    tied_mints: tuple[str, ...]


def algebra_matches(
    query: Assoc,
    stored: Assoc,
    launch_size: np.ndarray,
    stored_size: np.ndarray,
    *,
    min_overlap: int = 2,
    min_jaccard: float = 0.10,
    max_candidates: int | None = 200,
) -> list[AlgebraMatch | None]:
    """One product, then the ledger's three rules applied to it.

    ``query`` and ``stored`` are both coin x wallet over the SAME wallet key axis.
    ``launch_size`` is the FULL ex-deployer set size per query coin (see module docstring).
    ``max_candidates=None`` runs untruncated, which is how the truncation cost is measured.
    """

    prod = co_occurrence(query, axis="row", other=stored, min_overlap=float(min_overlap))
    j = jaccard(prod, launch_size, stored_size)
    ip, ind, ov = prod.m.indptr, prod.m.indices, prod.m.data
    jd = j.m.data
    out: list[AlgebraMatch | None] = []
    for i in range(prod.shape[0]):
        if launch_size[i] < min_overlap:
            out.append(None)
            continue
        lo, hi = ip[i], ip[i + 1]
        cand_ov, cand_j, cand_ix = ov[lo:hi], jd[lo:hi], ind[lo:hi]
        if cand_ov.size == 0:
            out.append(None)
            continue
        # the ledger's ORDER BY overlap DESC, then its LIMIT
        order = np.argsort(-cand_ov, kind="stable")
        n_cands = int(cand_ov.size)
        if max_candidates is not None:
            order = order[:max_candidates]
        sel_j, sel_ov, sel_ix = cand_j[order], cand_ov[order], cand_ix[order]
        ok = sel_j >= min_jaccard
        if not ok.any():
            out.append(None)
            continue
        best_j = float(sel_j[ok].max())
        # the ledger keeps the FIRST strict improvement in overlap-desc order
        first = int(np.flatnonzero(ok & (sel_j >= best_j - 1e-12))[0])
        ties = int(np.count_nonzero(ok & (np.abs(sel_j - best_j) <= 1e-12)))
        tie_ix = sel_ix[ok & (np.abs(sel_j - best_j) <= 1e-12)]
        out.append(
            AlgebraMatch(
                matched_mint=stored.row[int(sel_ix[first])],
                jaccard=round(best_j, 4),
                overlap=int(sel_ov[first]),
                launch_set_size=int(launch_size[i]),
                matched_set_size=int(stored_size[int(sel_ix[first])]),
                n_candidates=n_cands,
                n_ties=ties,
                tied_mints=tuple(stored.row[int(k)] for k in tie_ix),
            )
        )
    return out


def build_query_matrices(
    n_query: int, seed: int, *, stored: Assoc
) -> tuple[Assoc, np.ndarray, list[str]]:
    """Query coins the ledger has never stored, as coin x wallet over the LEDGER's wallets.

    Returns the matrix, the FULL ex-deployer launch-set sizes, and the chosen mints."""

    df = graphs.load_snipers("all")
    df = df[df["owner"] != df["deployer"]]
    stored_mints = set(stored.row)
    ledger_wallets = set(stored.col)

    sizes = df.groupby("mint")["owner"].nunique()
    eligible = sorted(m for m in sizes.index if m not in stored_mints and sizes[m] >= 2)
    rng = np.random.default_rng(seed)
    take = min(n_query, len(eligible))
    picked = sorted(np.asarray(eligible)[rng.choice(len(eligible), size=take, replace=False)].tolist())

    sub = df[df["mint"].isin(set(picked))]
    launch_size = np.asarray([int(sizes[m]) for m in picked], dtype=np.int64)
    hit = sub[sub["owner"].isin(ledger_wallets)]
    q = Assoc.from_tuples(
        list(hit["mint"]), list(hit["owner"]), row_keys=picked, col_keys=list(stored.col)
    )
    return q, launch_size, picked


def compare(
    n_query: int = 3000,
    seed: int = 20260829,
    *,
    min_overlap: int = 2,
    min_jaccard: float = 0.10,
    max_candidates: int = 200,
) -> dict[str, Any]:
    """Run the gate. Returns the parity report; the caller writes the artifact.

    Since the crew-id fix (2026-08-29) the shipped ``crew_match`` scans every candidate —
    no LIMIT, no ORDER BY — so the instrument is a pure function of the data at its
    shipped settings and there is ONE ledger arm. The report keeps both algebra arms:

    * **untruncated algebra vs the ledger**: the honest algebra-vs-instrument test
      (``arm1_*`` and, now equivalently, ``agreement_*``). Parity must be exact on the
      numbers, and on ``matched_mint`` wherever the argmax is unique — inside an exact
      tie block the fixed instrument names a deterministic record-first representative
      while the algebra reports its own first row, so mint agreement is only owed where
      no tie exists.
    * **truncated algebra** (``max_candidates``, default the retired 200): a measurement
      of what the retired ``ORDER BY overlap DESC LIMIT`` config would still be costing
      (``truncation_*`` keys), computed algebra-vs-algebra.
    """

    from dregg_screen.ledger import Ledger, resolve_current

    lg, ledger_meta, _ = graphs.ledger_crew_sets()
    stored = lg.a
    stored_size = stored.degree(axis="row")

    _lg2, _m2, crew_of = graphs.ledger_crew_sets()
    query, launch_size, mints = build_query_matrices(n_query, seed, stored=stored)
    algebra = algebra_matches(
        query, stored, launch_size, stored_size,
        min_overlap=min_overlap, min_jaccard=min_jaccard, max_candidates=max_candidates,
    )
    untruncated = algebra_matches(
        query, stored, launch_size, stored_size,
        min_overlap=min_overlap, min_jaccard=min_jaccard, max_candidates=None,
    )

    ledger = Ledger(resolve_current())
    df = graphs.load_snipers("all")
    df = df[df["owner"] != df["deployer"]]
    sets = df[df["mint"].isin(set(mints))].groupby("mint")["owner"].apply(list).to_dict()

    rows: list[dict[str, Any]] = []
    agree_all = agree_num = 0
    both_none = only_ledger = only_algebra = 0
    ties = 0
    crew_ambiguous = 0
    unt_agree_num = unt_agree_all = 0
    trunc_changed = trunc_worse = 0
    for i, mint in enumerate(mints):
        # One ledger arm: the fixed instrument has no truncation to configure.
        want = want_unt = ledger.crew_match(
            sets.get(mint, []),
            min_overlap=min_overlap,
            min_jaccard=min_jaccard,
        )
        got = algebra[i]
        unt = untruncated[i]
        # arm 1: the untruncated comparison, where the instrument is deterministic
        if want_unt is None and unt is None:
            unt_agree_num += 1
            unt_agree_all += 1
        elif want_unt is not None and unt is not None:
            same = (want_unt.overlap == unt.overlap) and (abs(want_unt.jaccard - unt.jaccard) < 5e-5)
            unt_agree_num += int(same)
            unt_agree_all += int(same and want_unt.matched_mint == unt.matched_mint)
        n_tie_crews = len({crew_of.get(m) for m in unt.tied_mints}) if unt else 0
        crew_ambiguous += int(n_tie_crews > 1)
        # agreement_*: ledger vs the untruncated algebra — the shipped configuration on
        # both sides now that the instrument's truncation is gone.
        if want is None and unt is None:
            both_none += 1
            same_num = same_all = True
        elif want is None or unt is None:
            only_ledger += int(unt is None and want is not None)
            only_algebra += int(want is None and unt is not None)
            same_num = same_all = False
        else:
            same_num = (want.overlap == unt.overlap) and (abs(want.jaccard - unt.jaccard) < 5e-5)
            same_all = same_num and (want.matched_mint == unt.matched_mint)
            ties += int(unt.n_ties > 1)
        agree_num += int(same_num)
        agree_all += int(same_all)
        if (unt is None) != (got is None):
            trunc_changed += 1
        elif unt is not None and got is not None and abs(unt.jaccard - got.jaccard) > 5e-5:
            trunc_changed += 1
            trunc_worse += int(unt.jaccard > got.jaccard)
        rows.append(
            {
                "mint": mint,
                "launch_set_size": int(launch_size[i]),
                "ledger_matched_mint": want.matched_mint if want else None,
                "ledger_jaccard": want.jaccard if want else None,
                "ledger_overlap": want.overlap if want else None,
                "algebra_matched_mint": got.matched_mint if got else None,
                "algebra_jaccard": got.jaccard if got else None,
                "algebra_overlap": got.overlap if got else None,
                "algebra_candidates": got.n_candidates if got else 0,
                "algebra_ties_at_best": got.n_ties if got else 0,
                "untruncated_jaccard": unt.jaccard if unt else None,
                "untruncated_ties_at_best": unt.n_ties if unt else 0,
                "untruncated_tied_crews": n_tie_crews,
                "ledger_untruncated_jaccard": want_unt.jaccard if want_unt else None,
                "ledger_crew_id": want.crew_id if want else None,
                "agree_numeric": bool(same_num),
                "agree_exact": bool(same_all),
            }
        )
    ledger.close()

    n = len(mints)
    return {
        "n_query_coins": n,
        "seed": seed,
        "thresholds": {
            "min_overlap": min_overlap,
            "min_jaccard": min_jaccard,
            "max_candidates": max_candidates,
        },
        "ledger_meta": {k: ledger_meta.get(k) for k in ("built_at", "corpus_span", "crews", "crew_coins")},
        "arm1_untruncated_agreement_numeric": unt_agree_num / n if n else float("nan"),
        "arm1_untruncated_agreement_exact": unt_agree_all / n if n else float("nan"),
        "arm1_n_disagree_numeric": n - unt_agree_num,
        "agreement_numeric": agree_num / n if n else float("nan"),
        "agreement_exact": agree_all / n if n else float("nan"),
        "n_agree_numeric": agree_num,
        "n_agree_exact": agree_all,
        "n_both_none": both_none,
        "n_only_ledger_matched": only_ledger,
        "n_only_algebra_matched": only_algebra,
        "n_with_jaccard_ties": ties,
        "n_crew_ambiguous": crew_ambiguous,
        "n_matched_by_ledger": sum(1 for r in rows if r["ledger_matched_mint"]),
        "truncation_changed_answer": trunc_changed,
        "truncation_lost_a_better_match": trunc_worse,
        "max_candidates_seen": max((r["algebra_candidates"] for r in rows), default=0),
        "n_over_the_limit": sum(1 for r in rows if r["algebra_candidates"] > max_candidates),
        "rows": rows,
    }
