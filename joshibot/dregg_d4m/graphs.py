"""The real matrices, each with a documented provenance and window stamp.

Every builder here returns a ``Graph`` -- an ``Assoc`` plus a ``Provenance`` record naming
the files it read, the calendar window those files cover, what a row key IS, what a column
key IS, and what a VALUE means. The provenance travels into every artifact under
``state/dregg_d4m/`` because a crew graph with no window stamp is a picture, not evidence.

THE MATRICES
------------
``B`` birth-slot snipers x coin  (``birth_snipers``)
    The crew substrate. Source ``studies/data/operator_crime_fresh/combined/snipers.parquet``
    joined to ``panel.parquet`` for the deployer. ``ex_deployer=True`` (the default) drops
    the deployer's own birth-slot buy, which is cmd_graph's rule and the rule the shipped
    ledger stores under; leaving it in inflates same-deployer Jaccard by self-inclusion and
    ``operator_crime`` prints that inflated number explicitly as an artifact check.

``D`` deployer x coin  (``deployer_coins``)
    From the same panel. Carries ``is_rip`` / ``t_dump`` / ``graduated`` outcomes alongside.

``L`` crew-ledger coin x wallet  (``ledger_crew_sets``)
    The SHIPPED artifact, read-only, straight out of ``state/dregg_screen/ledger/
    current.sqlite``. This is the matrix the parity test scores against, so it is read from
    the artifact the live scorer loads -- not rebuilt from the corpus, which would prove
    only that two copies of our own code agree.

``W`` wallet x coin  (``wallet_coins``)
    The executable-priced leg tape, ``state/wallets/stage/legs.parquet`` with the
    ``studies/data/pvp_vamps`` id dictionaries. A DIFFERENT corpus and window from ``B``
    (the ten-day bulk tape, 33,883 mints) -- the two are never silently unioned.

``C`` caller x coin  (``caller_coins``)
    ``state/callouts/*.jsonl``, ``author_username`` x ``mints``. Small by construction; the
    registration sends it through ``svn_cotrading.feasibility_gate`` before any statistic.

WINDOWS
-------
The corpus has an 11-day hole in it. ``WINDOW_A`` is 2026-08-05..14 and ``WINDOW_B`` is
2026-08-26..28; ``"all"`` is their union, which is what the shipped ledger was built on.
Anything that compares across the gap must name which window it means, so the window is a
required-by-default argument rather than a global.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from dregg_d4m.assoc import Assoc

REPO_ROOT = Path(__file__).resolve().parent.parent
COMBINED = REPO_ROOT / "studies" / "data" / "operator_crime_fresh" / "combined"
LEDGER = REPO_ROOT / "state" / "dregg_screen" / "ledger" / "current.sqlite"
LEGS = REPO_ROOT / "state" / "wallets" / "stage" / "legs.parquet"
PVP = REPO_ROOT / "studies" / "data" / "pvp_vamps"
CALLOUTS = REPO_ROOT / "state" / "callouts"

#: The corpus is two blocks separated by an 11-day unobserved gap and a noted regime shift.
WINDOW_A = ("2026-08-05", "2026-08-14")
WINDOW_B = ("2026-08-26", "2026-08-28")
Window = Literal["A", "B", "all"]


def _bounds(window: Window) -> tuple[float, float]:
    if window == "all":
        return (0.0, float("inf"))
    lo, hi = WINDOW_A if window == "A" else WINDOW_B
    start = datetime.fromisoformat(lo).replace(tzinfo=UTC).timestamp()
    end = datetime.fromisoformat(hi).replace(tzinfo=UTC).timestamp() + 86400.0
    return (start, end)


@dataclass(frozen=True, slots=True)
class Provenance:
    """What this matrix is, where it came from, and when it was true."""

    name: str
    sources: tuple[str, ...]
    window: str
    span: tuple[str, str]
    row_key: str
    col_key: str
    value: str
    n_rows: int = 0
    n_cols: int = 0
    nnz: int = 0
    built_at: str = ""
    notes: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Graph:
    a: Assoc
    prov: Provenance

    def __repr__(self) -> str:
        return f"Graph({self.prov.name}, {self.a!r}, window={self.prov.window})"


def _stamp(prov: Provenance, a: Assoc, span: tuple[str, str]) -> Provenance:
    return Provenance(
        name=prov.name,
        sources=prov.sources,
        window=prov.window,
        span=span,
        row_key=prov.row_key,
        col_key=prov.col_key,
        value=prov.value,
        n_rows=a.shape[0],
        n_cols=a.shape[1],
        nnz=a.nnz,
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        notes=prov.notes,
        params=prov.params,
    )


def _span_of(times: np.ndarray) -> tuple[str, str]:
    if times.size == 0:
        return ("", "")
    lo = datetime.fromtimestamp(float(times.min()), UTC).date().isoformat()
    hi = datetime.fromtimestamp(float(times.max()), UTC).date().isoformat()
    return (lo, hi)


# -- B: birth-slot snipers x coin ------------------------------------------------------


def load_snipers(window: Window = "all") -> Any:
    """The raw (mint, owner, birth_time, deployer) frame. Exposed because the parity test
    and the null both need the frame, not only the matrix."""

    import pandas as pd

    sn = pd.read_parquet(COMBINED / "snipers.parquet", columns=["mint", "owner", "birth_time"])
    pan = pd.read_parquet(COMBINED / "panel.parquet", columns=["mint", "deployer"])
    df = sn.merge(pan, on="mint", how="left")
    lo, hi = _bounds(window)
    return df[(df["birth_time"] >= lo) & (df["birth_time"] < hi)].reset_index(drop=True)


def birth_snipers(
    *, window: Window = "all", ex_deployer: bool = True, wallet_degree_cap: int | None = None
) -> Graph:
    """``B`` -- birth-slot buyer x coin, value 1. The crew substrate."""

    df = load_snipers(window)
    if ex_deployer:
        df = df[df["owner"] != df["deployer"]]
    a = Assoc.from_tuples(list(df["owner"]), list(df["mint"]))
    dropped = 0
    if wallet_degree_cap is not None:
        before = a.shape[0]
        a = a.restrict_degree(axis="row", max_degree=wallet_degree_cap)
        dropped = before - a.shape[0]
    prov = Provenance(
        name="B_birth_snipers",
        sources=(str(COMBINED / "snipers.parquet"), str(COMBINED / "panel.parquet")),
        window=window,
        span=("", ""),
        row_key="birth-slot buyer wallet (base58)",
        col_key="pump mint (base58)",
        value="1 -- presence in the coin's birth slot",
        notes=(
            "ex-deployer rule per operator_crime cmd_graph: the deployer's own birth-slot buy "
            "is removed, because leaving it in makes every same-deployer pair share at least "
            "one wallet by construction."
            if ex_deployer
            else "DEPLOYER INCLUDED -- self-inclusion inflates same-deployer overlap; artifact check only."
        ),
        params={
            "ex_deployer": ex_deployer,
            "wallet_degree_cap": wallet_degree_cap,
            "wallets_dropped_by_cap": dropped,
        },
    )
    return Graph(a, _stamp(prov, a, _span_of(df["birth_time"].to_numpy())))


# -- D: deployer x coin, with outcomes -------------------------------------------------


def deployer_coins(*, window: Window = "all") -> tuple[Graph, Any]:
    """``D`` plus the outcome frame (``mint``, ``is_rip``, ``t_dump``, ``graduated``)."""

    import pandas as pd

    pan = pd.read_parquet(
        COMBINED / "panel.parquet",
        columns=["mint", "deployer", "birth_time", "is_rip", "t_dump", "graduated"],
    )
    lo, hi = _bounds(window)
    pan = pan[(pan["birth_time"] >= lo) & (pan["birth_time"] < hi)].reset_index(drop=True)
    has = pan[pan["deployer"].notna()]
    a = Assoc.from_tuples(list(has["deployer"]), list(has["mint"]))
    prov = Provenance(
        name="D_deployer_coins",
        sources=(str(COMBINED / "panel.parquet"),),
        window=window,
        span=("", ""),
        row_key="deployer wallet (base58)",
        col_key="pump mint (base58)",
        value="1 -- this deployer launched this coin",
        notes="outcome columns travel alongside, never inside the matrix",
    )
    return Graph(a, _stamp(prov, a, _span_of(pan["birth_time"].to_numpy()))), pan


# -- L: the SHIPPED ledger's crew sets -------------------------------------------------


def ledger_crew_sets(path: Path = LEDGER) -> tuple[Graph, dict[str, Any], dict[str, int]]:
    """``L`` -- coin x wallet, read straight out of the artifact the live scorer loads.

    Returns the matrix, the ledger's own ``meta``, and ``mint -> crew_id``. Read-only URI;
    this lane never writes to the ledger."""

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
        rows = con.execute("SELECT mint, wallet FROM crew_set").fetchall()
        crew_of = dict(con.execute("SELECT mint, crew_id FROM crew_coins").fetchall())
    finally:
        con.close()
    mints = [r[0] for r in rows]
    wallets = [r[1] for r in rows]
    a = Assoc.from_tuples(mints, wallets)
    meta.pop("validation", None)
    prov = Provenance(
        name="L_ledger_crew_sets",
        sources=(str(path),),
        window="all",
        span=tuple(meta.get("corpus_span", ("", ""))),  # type: ignore[arg-type]
        row_key="stored crew coin (pump mint, base58)",
        col_key="ex-deployer birth-slot wallet (base58)",
        value="1 -- wallet is in this stored coin's crew set",
        notes=(
            "the SHIPPED artifact, not a rebuild. Parity against a rebuild would only show "
            "two copies of our code agree."
        ),
        params={"schema_version": meta.get("schema_version"), "built_at": meta.get("built_at")},
    )
    return Graph(a, _stamp(prov, a, tuple(meta.get("corpus_span", ("", ""))))), meta, crew_of  # type: ignore[arg-type]


def ledger_crew_flags(path: Path = LEDGER) -> dict[int, dict[str, int]]:
    """``crew_id -> {n_coins, rips, dumps, dirty}`` for the seed set in D4."""

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {
            int(cid): {"n_coins": int(n), "rips": int(r), "dumps": int(d), "dirty": int(x)}
            for cid, n, r, d, x in con.execute(
                "SELECT crew_id, n_coins, rips, dumps, dirty FROM crews"
            )
        }
    finally:
        con.close()
    return out


# -- W: wallet x coin over the executable leg tape -------------------------------------


def wallet_coins(
    *, value: Literal["legs", "sol_signed"] = "legs", min_legs: int = 1, memory_limit: str = "8GB"
) -> Graph:
    """``W`` -- wallet x coin over ``state/wallets/stage/legs.parquet`` (57.5M priced legs).

    A DIFFERENT corpus and window from ``B``: the ten-day bulk tape over 33,883 mints, keyed
    by the ``studies/data/pvp_vamps`` id dictionaries. Aggregated in duckdb because 57.5M
    rows through pandas is a memory event, not an analysis.

    ``value="legs"`` counts legs; ``value="sol_signed"`` sums signed SOL (negative = bought).
    They are different associative arrays and the artifact says which one it is.

    ``memory_limit`` is set on the connection rather than left to duckdb's default (80% of
    RAM), because this runs on a laptop that is often also running a null.
    """

    import duckdb

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute("SET threads=4")
    try:
        rows = con.execute(
            f"""
            SELECT o.owner AS owner, m.mint AS mint,
                   count(*) AS n_legs, sum(l.sol) AS sol_signed,
                   min(l.t) AS t_first, max(l.t) AS t_last
            FROM read_parquet('{LEGS}') l
            JOIN read_parquet('{PVP / "owners.parquet"}') o USING (owner_id)
            JOIN read_parquet('{PVP / "mints.parquet"}') m USING (mint_id)
            GROUP BY 1, 2
            HAVING count(*) >= {int(min_legs)}
            """
        ).to_arrow_table()
    finally:
        con.close()
    owners = rows.column("owner").to_pylist()
    mints = rows.column("mint").to_pylist()
    vals = np.asarray(
        rows.column("n_legs" if value == "legs" else "sol_signed").to_pylist(), dtype=np.float64
    )
    times = np.concatenate(
        [np.asarray(rows.column("t_first").to_pylist()), np.asarray(rows.column("t_last").to_pylist())]
    )
    a = Assoc.from_tuples(owners, mints, vals, agg="sum")
    prov = Provenance(
        name="W_wallet_coins",
        sources=(str(LEGS), str(PVP / "owners.parquet"), str(PVP / "mints.parquet")),
        window="bulk-tape",
        span=("", ""),
        row_key="wallet (base58)",
        col_key="mint (base58)",
        value="leg count" if value == "legs" else "signed SOL (negative = net bought)",
        notes=(
            "the ten-day bulk tape, NOT the operator_crime window. Never unioned with B "
            "without saying so."
        ),
        params={"value": value, "min_legs": min_legs, "memory_limit": memory_limit},
    )
    return Graph(a, _stamp(prov, a, _span_of(times)))


# -- C: caller x coin ------------------------------------------------------------------


def caller_coins(*, root: Path = CALLOUTS) -> Graph:
    """``C`` -- callout author x mint over every ``state/callouts/*.jsonl``.

    Deliberately permissive on the mint field: a line carries ``mints`` once the archiver has
    resolved it and ``mint_candidates`` before that, and dropping the unresolved rows would
    shrink an already-tiny matrix without making it more honest. Both are lowercased-safe:
    keys are used verbatim, so a lowercased base58 candidate is its OWN key and cannot
    silently merge with the real mint."""

    rows: list[tuple[str, str, float]] = []
    times: list[float] = []
    for path in sorted(root.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                author = rec.get("author_username")
                if not author:
                    continue
                mints = rec.get("mints") or rec.get("mint_candidates") or []
                for mint in mints:
                    rows.append((str(author), str(mint), 1.0))
                if rec.get("slice_start_unix"):
                    times.append(float(rec["slice_start_unix"]))
    a = Assoc.from_tuples([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], agg="sum")
    prov = Provenance(
        name="C_caller_coins",
        sources=(str(root / "*.jsonl"),),
        window="callout-archive",
        span=("", ""),
        row_key="callout author handle",
        col_key="mint or mint candidate (base58, verbatim)",
        value="number of callouts by this author naming this mint",
        notes=(
            "mostly a per-operator-coin census, so the coin marginal is a SAMPLING artifact "
            "of what was collected, not a popularity measurement."
        ),
    )
    return Graph(a, _stamp(prov, a, _span_of(np.asarray(times, dtype=np.float64))))
