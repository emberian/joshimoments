"""The crime ledger: deployer history, sniper recidivism, and KNOWN-CREW fingerprints.

WHAT THIS IS
------------
The live screen's three history-shaped gates (``prior_rips == 0``, ``prior_dumps == 0``,
``sniper_prior_max == 0``) and the KNOWN-CREW match all consult the past, and the past
lives in the study corpora — ``state/bulk_pump`` (2026-08-05..14) plus
``state/bulk_pump_fresh`` (2026-08-26..28), already distilled by
``studies/operator_crime.py`` into ``panel.parquet`` / ``snipers.parquet`` (the
``combined/`` build under ``studies/data/operator_crime_fresh/``). This module folds
those into ONE versioned sqlite artifact the live scorer loads with stdlib sqlite3 —
the runtime never imports pandas, and the artifact carries its own build date and
corpus span so staleness is a visible fact rather than a surprise.

CAUSALITY, and the ``cutoff`` parameter
---------------------------------------
The study's history features are strictly causal: PANEL_SQL aggregates over EVENTS
whose own timestamp precedes the coin's birth (a launch counts at ``birth_time``, a
dump at ``t_dump``, a graduation at ``t_grad`` — never at the prior coin's birth).
For the LIVE scorer that causality is free: every corpus event precedes every live
launch by construction. ``cutoff`` exists so the parity test can rebuild the exact
history a corpus coin saw at its own birth and hold this module equal to the study's
``prior_*`` columns — it is the same aggregation with the same event clocks, evaluated
at an interior time instead of at +infinity.

CREW FINGERPRINTS, matched at the validated unit
------------------------------------------------
cmd_graph's positive result is PAIRWISE coin-to-coin: same-deployer birth-slot sniper
sets (deployer excluded) overlap at mean Jaccard 0.26 against a day-matched 0.0026 and
a degree-preserving-null 0.0075 (fresh 08-26..28 numbers). So the ledger stores
PER-COIN ex-deployer sniper sets for every multi-launch deployer's coins, and the live
match computes launch-set-vs-stored-coin-set Jaccard — the same statistic at the same
unit, not a diluted set-vs-union approximation. A match names the fingerprint (crew id
= the deployer's ledger id), the best-matching prior coin, the Jaccard, and the crew's
recorded rip/dump counts. A match against a crew with NO recorded rips or dumps is
reported as continuity, never escalated to a KNOWN-CREW verdict — reuse of a clean
crew is not a crime record.

BUILD / REFRESH
---------------
    uv run --group research python -m dregg_screen.ledger build
        [--panel P --snipers S] [--out DIR] [--cutoff UNIX_S]

Defaults read the combined corpus at ``studies/data/operator_crime_fresh/combined/``
and write ``state/dregg_screen/ledger/ledger-<UTCDATE>.sqlite`` plus a ``current.sqlite``
symlink swapped atomically. The biweekly corpus pull re-runs the operator_crime stages
on the new days, rebuilds ``combined/``, and re-runs this build; the live service picks
up the new ledger on its next restart (the heartbeat reports which build is loaded).
The validation blob (B1's ``screen_seeded.json`` + ``graph.json``) is embedded in
``meta`` so every emitted score can carry the measured base rates it is quoting.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMBINED = REPO_ROOT / "studies" / "data" / "operator_crime_fresh" / "combined"
DEFAULT_VALIDATION_DIR = REPO_ROOT / "studies" / "data" / "operator_crime_fresh"
DEFAULT_OUT_DIR = REPO_ROOT / "state" / "dregg_screen" / "ledger"

SCHEMA_VERSION = 1

#: Only deployers with >= 2 corpus launches leave a crew fingerprint — a single coin's
#: sniper set has no reuse to witness. Matches cmd_graph's ``dep >= 2`` arm.
CREW_MIN_COINS = 2

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE deployer_history (
  deployer TEXT PRIMARY KEY,
  launches INTEGER NOT NULL,
  rips INTEGER NOT NULL,
  dumps INTEGER NOT NULL,
  grads INTEGER NOT NULL,
  last_birth_time INTEGER
);
CREATE TABLE sniper_counts (wallet TEXT PRIMARY KEY, n_coins INTEGER NOT NULL);
CREATE TABLE crews (
  crew_id INTEGER PRIMARY KEY,
  deployer TEXT NOT NULL UNIQUE,
  n_coins INTEGER NOT NULL,
  rips INTEGER NOT NULL,
  dumps INTEGER NOT NULL,
  dirty INTEGER NOT NULL
);
CREATE TABLE crew_coins (
  mint TEXT PRIMARY KEY,
  crew_id INTEGER NOT NULL REFERENCES crews(crew_id),
  set_size INTEGER NOT NULL
);
CREATE TABLE crew_set (mint TEXT NOT NULL, wallet TEXT NOT NULL);
CREATE INDEX idx_crew_set_wallet ON crew_set(wallet);
CREATE INDEX idx_crew_set_mint ON crew_set(mint);
"""


# -- build (research-group dependencies) -----------------------------------------------


def build(
    panel_path: Path,
    snipers_path: Path,
    out_path: Path,
    *,
    cutoff: float | None = None,
    validation_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the artifact. Returns the meta dict it embedded (for the CLI to print)."""

    import pandas as pd  # research group; the live scorer never comes through here

    t0 = time.time()
    panel = pd.read_parquet(
        panel_path,
        columns=["mint", "deployer", "birth_time", "is_rip", "t_dump", "graduated", "t_last"],
    )
    snipers = pd.read_parquet(snipers_path, columns=["mint", "owner", "birth_time"])

    horizon = float("inf") if cutoff is None else float(cutoff)

    # Deployer history: each EVENT counts at its own clock (PANEL_SQL's ev CTE).
    d = panel[panel["deployer"].notna()].copy()
    d["e_launch"] = (d["birth_time"] < horizon).astype(int)
    d["e_dump"] = (d["t_dump"].notna() & (d["t_dump"] < horizon)).astype(int)
    d["e_rip"] = (d["is_rip"].fillna(False) & (d["t_dump"] < horizon)).astype(int)
    t_grad = d["t_last"].where(d["graduated"].fillna(False))
    d["e_grad"] = (t_grad.notna() & (t_grad < horizon)).astype(int)
    d["t_birth_seen"] = d["birth_time"].where(d["birth_time"] < horizon)
    hist = (
        d.groupby("deployer")
        .agg(
            launches=("e_launch", "sum"),
            rips=("e_rip", "sum"),
            dumps=("e_dump", "sum"),
            grads=("e_grad", "sum"),
            last_birth_time=("t_birth_seen", "max"),
        )
        .reset_index()
    )
    hist = hist[hist["launches"] > 0]

    # Sniper recidivism: appearances strictly before the horizon (PANEL_SQL's sr CTE
    # orders by birth_time; the live max over corpus counts is its causal analogue).
    sn = snipers[snipers["birth_time"] < horizon]
    counts = sn.groupby("owner").size().rename("n_coins").reset_index()

    # Crew fingerprints: per-coin ex-deployer sniper sets of multi-launch deployers.
    dep_of = d[d["e_launch"] == 1][["mint", "deployer"]]
    multi = hist[hist["launches"] >= CREW_MIN_COINS][["deployer", "launches", "rips", "dumps"]]
    crew_mints = dep_of.merge(multi[["deployer"]], on="deployer")
    sets = sn.merge(crew_mints, on="mint")
    sets = sets[sets["owner"] != sets["deployer"]]  # cmd_graph's ex-deployer rule
    set_sizes = sets.groupby("mint").size().rename("set_size").reset_index()
    crew_mints = crew_mints.merge(set_sizes, on="mint")  # drops empty ex-deployer sets

    crews = multi.merge(
        crew_mints.groupby("deployer").size().rename("n_stored").reset_index(), on="deployer"
    )
    crews = crews.sort_values("deployer").reset_index(drop=True)
    crews["crew_id"] = crews.index + 1
    crews["dirty"] = ((crews["rips"] + crews["dumps"]) > 0).astype(int)
    crew_mints = crew_mints.merge(crews[["deployer", "crew_id"]], on="deployer")
    sets = sets.merge(crews[["deployer", "crew_id"]], on="deployer")

    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cutoff": cutoff,
        "panel_path": str(panel_path),
        "snipers_path": str(snipers_path),
        "corpus_span": [
            datetime.fromtimestamp(int(panel["birth_time"].min()), UTC).date().isoformat(),
            datetime.fromtimestamp(int(panel["birth_time"].max()), UTC).date().isoformat(),
        ],
        "corpus_coins": len(panel),
        "deployers": len(hist),
        "sniper_wallets": len(counts),
        "crews": len(crews),
        "crew_coins": len(crew_mints),
        "crew_set_rows": len(sets),
    }
    validation = _load_validation(validation_dir or DEFAULT_VALIDATION_DIR)
    if validation:
        meta["validation"] = validation

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO deployer_history VALUES (?,?,?,?,?,?)",
            (
                (r.deployer, int(r.launches), int(r.rips), int(r.dumps), int(r.grads),
                 None if pd.isna(r.last_birth_time) else int(r.last_birth_time))
                for r in hist.itertuples()
            ),
        )
        con.executemany(
            "INSERT INTO sniper_counts VALUES (?,?)",
            ((r.owner, int(r.n_coins)) for r in counts.itertuples()),
        )
        con.executemany(
            "INSERT INTO crews VALUES (?,?,?,?,?,?)",
            (
                (int(r.crew_id), r.deployer, int(r.launches), int(r.rips), int(r.dumps), int(r.dirty))
                for r in crews.itertuples()
            ),
        )
        con.executemany(
            "INSERT INTO crew_coins VALUES (?,?,?)",
            ((r.mint, int(r.crew_id), int(r.set_size)) for r in crew_mints.itertuples()),
        )
        con.executemany(
            "INSERT INTO crew_set VALUES (?,?)",
            ((r.mint, r.owner) for r in sets.itertuples()),
        )
        con.executemany(
            "INSERT INTO meta VALUES (?,?)", ((k, json.dumps(v)) for k, v in meta.items())
        )
        con.commit()
    finally:
        con.close()
    os.replace(tmp, out_path)
    meta["build_seconds"] = round(time.time() - t0, 1)
    return meta


def _load_validation(validation_dir: Path) -> dict[str, Any]:
    """B1's fresh-revalidation numbers, embedded so scores can quote what was measured."""

    out: dict[str, Any] = {}
    for name in ("screen_seeded", "graph"):
        path = validation_dir / f"{name}.json"
        if path.exists():
            try:
                out[name] = json.loads(path.read_text())
            except ValueError:
                out[f"{name}_error"] = "unparseable"
    if out.get("screen_seeded"):
        out["validated_span"] = "2026-08-26..28 (seeded history, B1)"
    return out


# -- runtime (stdlib only) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeployerHistory:
    launches: int = 0
    rips: int = 0
    dumps: int = 0
    grads: int = 0


@dataclass(frozen=True, slots=True)
class CrewMatch:
    crew_id: int
    deployer: str
    matched_mint: str
    jaccard: float
    overlap: int
    launch_set_size: int
    matched_set_size: int
    crew_coins: int
    crew_rips: int
    crew_dumps: int
    dirty: bool


class Ledger:
    """Read-only view over the sqlite artifact. One connection, no writes, no pandas."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"ledger artifact not found: {self.path}")
        self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self.meta: dict[str, Any] = {
            k: json.loads(v) for k, v in self._con.execute("SELECT key, value FROM meta")
        }
        if self.meta.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"ledger schema {self.meta.get('schema_version')} != expected {SCHEMA_VERSION}; "
                f"rebuild with `python -m dregg_screen.ledger build`"
            )

    def close(self) -> None:
        self._con.close()

    @property
    def staleness_days(self) -> float | None:
        span = self.meta.get("corpus_span")
        if not span:
            return None
        end = datetime.fromisoformat(span[1]).replace(tzinfo=UTC)
        return round((datetime.now(UTC) - end).total_seconds() / 86400, 1)

    def deployer_history(self, wallet: str | None) -> DeployerHistory:
        if not wallet:
            return DeployerHistory()
        row = self._con.execute(
            "SELECT launches, rips, dumps, grads FROM deployer_history WHERE deployer = ?",
            (wallet,),
        ).fetchone()
        return DeployerHistory(*row) if row else DeployerHistory()

    def sniper_count(self, wallet: str) -> int:
        row = self._con.execute(
            "SELECT n_coins FROM sniper_counts WHERE wallet = ?", (wallet,)
        ).fetchone()
        return int(row[0]) if row else 0

    def sniper_prior_max(self, wallets: Iterable[str]) -> int:
        """max over the birth-slot sniper set of prior corpus appearances — the live
        analogue of PANEL_SQL's ``sniper_prior_max`` (max(nth) - 1), causal because
        every corpus appearance precedes the live launch."""

        return max((self.sniper_count(w) for w in wallets), default=0)

    def crew_match(
        self,
        launch_set: Sequence[str],
        *,
        min_overlap: int = 2,
        min_jaccard: float = 0.10,
        max_candidates: int = 200,
    ) -> CrewMatch | None:
        """Best pairwise Jaccard between the launch's ex-deployer sniper set and any
        stored per-coin crew set. Pairwise coin-vs-coin is the unit cmd_graph validated
        (0.26 same-deployer vs 0.0026 day-matched); ``min_overlap=2`` refuses to call a
        single shared wallet a crew — one recidivist wallet is what ``sniper_prior_max``
        already reports, and inflating it into a fingerprint would manufacture matches
        out of ambient bot traffic.
        """

        wallets = sorted(set(launch_set))
        if len(wallets) < min_overlap:
            return None
        marks = ",".join("?" for _ in wallets)
        rows = self._con.execute(
            f"""SELECT s.mint, count(*) AS overlap, c.set_size, c.crew_id
                FROM crew_set s JOIN crew_coins c USING (mint)
                WHERE s.wallet IN ({marks})
                GROUP BY s.mint HAVING overlap >= ?
                ORDER BY overlap DESC LIMIT ?""",
            (*wallets, min_overlap, max_candidates),
        ).fetchall()
        best: tuple[float, str, int, int, int] | None = None
        for mint, overlap, set_size, crew_id in rows:
            union = len(wallets) + set_size - overlap
            j = overlap / union if union else 0.0
            if j >= min_jaccard and (best is None or j > best[0]):
                best = (j, mint, int(overlap), int(set_size), int(crew_id))
        if best is None:
            return None
        j, mint, overlap, set_size, crew_id = best
        deployer, n_coins, rips, dumps, dirty = self._con.execute(
            "SELECT deployer, n_coins, rips, dumps, dirty FROM crews WHERE crew_id = ?",
            (crew_id,),
        ).fetchone()
        return CrewMatch(
            crew_id=crew_id,
            deployer=deployer,
            matched_mint=mint,
            jaccard=round(j, 4),
            overlap=overlap,
            launch_set_size=len(wallets),
            matched_set_size=set_size,
            crew_coins=int(n_coins),
            crew_rips=int(rips),
            crew_dumps=int(dumps),
            dirty=bool(dirty),
        )


def resolve_current(out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    """The path the live service loads: ``current.sqlite`` in the ledger dir."""

    return out_dir / "current.sqlite"


def _swap_current(out_dir: Path, target: Path) -> None:
    link = resolve_current(out_dir)
    tmp = out_dir / ".current.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target.name)
    os.replace(tmp, link)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dregg_screen.ledger", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the ledger artifact from the study corpora")
    b.add_argument("--panel", type=Path, default=DEFAULT_COMBINED / "panel.parquet")
    b.add_argument("--snipers", type=Path, default=DEFAULT_COMBINED / "snipers.parquet")
    b.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    b.add_argument("--cutoff", type=float, default=None,
                   help="unix seconds; only events strictly before this count (parity tests)")
    s = sub.add_parser("show", help="print the loaded artifact's meta")
    s.add_argument("--path", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "build":
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        out = args.out_dir / f"ledger-{stamp}.sqlite"
        meta = build(args.panel, args.snipers, out, cutoff=args.cutoff)
        _swap_current(args.out_dir, out)
        printable = {k: v for k, v in meta.items() if k != "validation"}
        print(json.dumps(printable, indent=2))
        print(f"-> {out}\n-> {resolve_current(args.out_dir)} (current)")
        return 0
    if args.cmd == "show":
        ledger = Ledger(args.path or resolve_current())
        meta = dict(ledger.meta)
        meta.pop("validation", None)
        meta["staleness_days"] = ledger.staleness_days
        print(json.dumps(meta, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
