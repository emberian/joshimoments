"""The wallet-dossier index: one sqlite artifact over the state/wallets behavioral layer.

WHAT THIS IS
------------
``state/wallets/`` (built by ``studies/wallet_estimator.py``) is the standing per-wallet
behavioral layer — 728k wallet behavior vectors, 4.35M (wallet, coin) distribution
episodes, and the per-coin exit signal. Those parquets total ~660MB and a bot command
cannot afford to scan them per lookup, so this module folds the card-relevant slice into
ONE versioned sqlite artifact the bot reads with stdlib sqlite3 — the same
build-with-research-deps / serve-with-stdlib split ``dregg_screen.ledger`` uses, with the
same ``current.sqlite`` atomic symlink swap and the same self-describing ``meta`` table
(build date, corpus span, sources) so staleness is a visible fact rather than a surprise.

TABLES
------
* ``wallet`` — one row per active wallet (>= 3 priced legs), keyed by base58 ``owner``:
  guild, rp_mode, executable realized PnL, win rate, hold times, entry latency, ladder,
  rotation. The card-relevant projection of ``estimator.parquet``.
* ``coin`` — one row per corpus coin: how many distinct wallets traded it in the window
  and their composition (guild mix, BREAKEVEN_PRESET count, rotation/ladder counts,
  share with a net-positive record). Built from the full priced-leg tape
  (``trades.parquet``) when present; falls back to the significant-holder set from
  ``iceberg.parquet`` (holders peaking >= 0.1% of supply) — ``meta.comp_source`` records
  which, and the card labels it.
* ``coin_exit`` — the per-coin exit signal, verbatim from ``coin_exit_signal.parquet``.
* ``iceberg`` — the GATED distribution candidates only (drawdown >= 0.60, >= 8 sells,
  >= 300 s; ~53k of 4.35M episodes), indexed by mint so a coin card can name its top
  distributors.
* ``coin_crew`` — the join against dregg_screen's crew ledger, precomputed at build time
  (the ledger may live elsewhere than the bot): coins launched by a fingerprinted crew,
  and coins >= 2 of whose traders appear in a crew's birth-slot sets. Participation
  overlap is labeled as such on the card — it is not the validated pairwise-Jaccard
  fingerprint match, which belongs to the launch screen.

JOIN_CONTRACT rules honored here and in ``cards.py``:
1. a miss is null-with-reason, never zero (absent wallet = below the activity floor;
   absent exit row = clean no-signal);
2. freshness stamps ride the artifact (``meta``) and every rendered card;
3. ``timing_q`` ranks distribution intensity, it does not convict — the caveat is a
   constant on the card, not an optional footnote.

BUILD / REFRESH
---------------
    uv run --group research python -m dregg_dossier build
        [--wallets-dir D] [--trades P] [--mints P] [--owners P]
        [--crew-ledger P] [--out-dir D] [--threads N] [--memory S]

Defaults read ``state/wallets/`` plus the pvp_vamps corpus tables where present, and
write ``state/wallets/dossier/dossier-<UTCDATE>.sqlite`` with a ``current.sqlite``
symlink swapped atomically. Rebuild whenever ``studies/wallet_estimator.py`` repoints
the parquets. ``python -m dregg_dossier wallet <addr>`` / ``coin <mint>`` render the
live cards from the CLI for smoke tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WALLETS_DIR = REPO_ROOT / "state" / "wallets"
DEFAULT_OUT_DIR = DEFAULT_WALLETS_DIR / "dossier"
DEFAULT_PVP_DIR = REPO_ROOT / "studies" / "data" / "pvp_vamps"
DEFAULT_CREW_LEDGER = REPO_ROOT / "state" / "dregg_screen" / "ledger" / "current.sqlite"

SCHEMA_VERSION = 1

#: A coin-crew overlap below this many distinct wallets is ambient bot traffic, not a
#: crew presence — mirrors the ledger's ``min_overlap=2`` refusal to call one shared
#: wallet a crew.
CREW_MIN_OVERLAP = 2
CREW_TOP_PER_COIN = 3

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE wallet (
  owner TEXT PRIMARY KEY,
  guild TEXT NOT NULL,
  guild_cluster TEXT,
  rp_mode TEXT NOT NULL,
  n_legs INTEGER NOT NULL,
  n_buys INTEGER NOT NULL,
  n_sells INTEGER NOT NULL,
  n_coins INTEGER NOT NULL,
  active_days INTEGER NOT NULL,
  t_first INTEGER NOT NULL,
  t_last INTEGER NOT NULL,
  net_realized_sol REAL,
  win_rate REAL,
  n_coins_closed INTEGER NOT NULL,
  n_coins_win INTEGER NOT NULL,
  median_realized_sol_closed REAL,
  median_hold_s REAL,
  p90_hold_s REAL,
  rp_frac_breakeven REAL,
  -- NULL for buy-only wallets: the realization fingerprint had no sells to measure.
  n_priced_sells INTEGER,
  median_entry_latency_s REAL,
  on_ladder INTEGER NOT NULL,
  in_rotation INTEGER NOT NULL,
  rotation_hours INTEGER NOT NULL,
  buy_sol REAL,
  sell_sol REAL,
  sol_asymmetry REAL
) WITHOUT ROWID;
CREATE TABLE coin (
  mint TEXT PRIMARY KEY,
  n_traders INTEGER NOT NULL,
  n_profiled INTEGER NOT NULL,
  n_harvester INTEGER NOT NULL,
  n_slow INTEGER NOT NULL,
  n_accumulator INTEGER NOT NULL,
  n_flash INTEGER NOT NULL,
  n_aftermarket INTEGER NOT NULL,
  n_breakeven_preset INTEGER NOT NULL,
  n_in_rotation INTEGER NOT NULL,
  n_on_ladder INTEGER NOT NULL,
  n_net_positive INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE coin_exit (
  mint TEXT PRIMARY KEY,
  n_distributors INTEGER NOT NULL,
  max_iceberg_score REAL,
  -- NULL = recency untested (only timing-tested episodes carry is_recent), not false.
  any_recent INTEGER,
  n_timing_pass INTEGER NOT NULL,
  last_dist_t INTEGER
) WITHOUT ROWID;
CREATE TABLE iceberg (
  mint TEXT NOT NULL,
  owner TEXT NOT NULL,
  iceberg_score REAL,
  drawdown REAL,
  sold_frac_of_own REAL,
  n_dist_sells INTEGER NOT NULL,
  dist_sold_sol REAL,
  duration_s REAL,
  resilience REAL,
  timing_q REAL,
  self_wash REAL,
  is_recent INTEGER,
  last_dist_t INTEGER
);
CREATE INDEX idx_iceberg_mint ON iceberg(mint);
CREATE TABLE coin_crew (
  mint TEXT NOT NULL,
  crew_id INTEGER NOT NULL,
  launched_by INTEGER NOT NULL,
  n_overlap INTEGER,
  crew_coins INTEGER NOT NULL,
  crew_rips INTEGER NOT NULL,
  crew_dumps INTEGER NOT NULL,
  dirty INTEGER NOT NULL
);
CREATE INDEX idx_coin_crew_mint ON coin_crew(mint);
"""

_WALLET_COLUMNS = (
    "owner", "guild", "guild_cluster", "rp_mode", "n_legs", "n_buys", "n_sells",
    "n_coins", "active_days", "t_first", "t_last", "net_realized_sol", "win_rate",
    "n_coins_closed", "n_coins_win", "median_realized_sol_closed", "median_hold_s",
    "p90_hold_s", "rp_frac_breakeven", "n_priced_sells", "median_entry_latency_s",
    "on_ladder", "in_rotation", "rotation_hours", "buy_sol", "sell_sol", "sol_asymmetry",
)

_GUILD_CASES = """
  count(*) AS n_traders,
  count(e.owner) AS n_profiled,
  coalesce(sum(CASE WHEN e.guild = 'HARVESTER' THEN 1 ELSE 0 END), 0) AS n_harvester,
  coalesce(sum(CASE WHEN e.guild = 'SLOW' THEN 1 ELSE 0 END), 0) AS n_slow,
  coalesce(sum(CASE WHEN e.guild = 'ACCUMULATOR' THEN 1 ELSE 0 END), 0) AS n_accumulator,
  coalesce(sum(CASE WHEN e.guild = 'FLASH' THEN 1 ELSE 0 END), 0) AS n_flash,
  coalesce(sum(CASE WHEN e.guild = 'AFTERMARKET' THEN 1 ELSE 0 END), 0) AS n_aftermarket,
  coalesce(sum(CASE WHEN e.rp_mode = 'BREAKEVEN_PRESET' THEN 1 ELSE 0 END), 0) AS n_breakeven_preset,
  coalesce(sum(CASE WHEN e.in_rotation THEN 1 ELSE 0 END), 0) AS n_in_rotation,
  coalesce(sum(CASE WHEN e.on_ladder THEN 1 ELSE 0 END), 0) AS n_on_ladder,
  coalesce(sum(CASE WHEN e.net_realized_sol > 0 THEN 1 ELSE 0 END), 0) AS n_net_positive
"""


# -- build (research-group dependencies) -----------------------------------------------


def build(
    wallets_dir: Path,
    out_path: Path,
    *,
    trades_path: Path | None = None,
    mints_path: Path | None = None,
    owners_path: Path | None = None,
    crew_ledger_path: Path | None = None,
    threads: int = 6,
    memory: str = "8GB",
) -> dict[str, Any]:
    """Build the artifact. Returns the meta dict it embedded (for the CLI to print)."""

    try:
        import duckdb  # research group; the bot's lookups never come through here
    except ImportError:  # pragma: no cover
        raise SystemExit("the dossier build needs duckdb: `uv run --group research`.") from None

    t0 = time.time()
    estimator = wallets_dir / "estimator.parquet"
    iceberg = wallets_dir / "iceberg.parquet"
    exit_signal = wallets_dir / "coin_exit_signal.parquet"
    for required in (estimator, iceberg, exit_signal):
        if not required.exists():
            raise SystemExit(f"missing input: {required} (run studies/wallet_estimator.py first)")

    duck = duckdb.connect()
    duck.execute(f"PRAGMA threads={int(threads)}")
    duck.execute(f"SET memory_limit='{memory}'")
    duck.execute("SET preserve_insertion_order=false")
    tmp_dir = wallets_dir / "duckdb_tmp"
    tmp_dir.mkdir(exist_ok=True)
    duck.execute(f"SET temp_directory='{tmp_dir}'")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")

        # -- wallet: the card projection of estimator.parquet -------------------------
        cursor = duck.execute(
            f"""
            SELECT owner, guild, guild_cluster, rp_mode,
                   CAST(n_legs AS BIGINT), CAST(n_buys AS BIGINT), CAST(n_sells AS BIGINT),
                   n_coins, active_days, t_first, t_last,
                   net_realized_sol, win_rate,
                   CAST(n_coins_closed AS BIGINT), CAST(n_coins_win AS BIGINT),
                   median_realized_sol_closed, median_hold_s, p90_hold_s,
                   rp_frac_breakeven, n_priced_sells, median_entry_latency_s,
                   CAST(on_ladder AS INTEGER), CAST(in_rotation AS INTEGER), rotation_hours,
                   buy_sol, sell_sol, sol_asymmetry
            FROM read_parquet('{estimator}')
            """
        )
        insert = f"INSERT INTO wallet VALUES ({','.join('?' * len(_WALLET_COLUMNS))})"
        while rows := cursor.fetchmany(100_000):
            con.executemany(insert, rows)

        # -- the corpus-wide context the cards quote (computed, not hardcoded) --------
        (n_wallets, updated_through, corpus_start, net_sum, net_median, frac_positive) = duck.execute(
            f"""
            SELECT count(*), max(updated_through), min(t_first),
                   sum(net_realized_sol), median(net_realized_sol),
                   avg(CASE WHEN net_realized_sol > 0 THEN 1.0 ELSE 0.0 END)
            FROM read_parquet('{estimator}')
            """
        ).fetchone()
        guild_stats = {
            row[0]: {
                "n": int(row[1]),
                "median_win_rate": round(float(row[2]), 4),
                "median_net_sol": round(float(row[3]), 4),
                "breakeven_preset_rate": round(float(row[4]), 4),
            }
            for row in duck.execute(
                f"""
                SELECT guild, count(*), median(win_rate), median(net_realized_sol),
                       avg(CASE WHEN rp_mode = 'BREAKEVEN_PRESET' THEN 1.0 ELSE 0.0 END)
                FROM read_parquet('{estimator}') GROUP BY guild
                """
            ).fetchall()
        }

        # -- coin composition: full trader set when the priced tape is present --------
        have_trades = (
            trades_path is not None and trades_path.exists()
            and mints_path is not None and mints_path.exists()
        )
        if have_trades:
            comp_source = "trades"
            duck.execute(
                f"""
                CREATE TEMP TABLE part AS
                SELECT DISTINCT t.mint_id, t.owner_id
                FROM read_parquet('{trades_path}') t
                """
            )
            comp_sql = f"""
                SELECT m.mint, {_GUILD_CASES}
                FROM part p
                LEFT JOIN read_parquet('{estimator}') e USING (owner_id)
                JOIN read_parquet('{mints_path}') m USING (mint_id)
                GROUP BY m.mint
            """
        else:
            comp_source = "iceberg_holders"
            duck.execute(
                f"""
                CREATE TEMP TABLE part AS
                SELECT DISTINCT mint, owner_id FROM read_parquet('{iceberg}')
                """
            )
            comp_sql = f"""
                SELECT p.mint, {_GUILD_CASES}
                FROM part p
                LEFT JOIN read_parquet('{estimator}') e USING (owner_id)
                GROUP BY p.mint
            """
        cursor = duck.execute(comp_sql)
        while rows := cursor.fetchmany(100_000):
            con.executemany(f"INSERT INTO coin VALUES ({','.join('?' * 12)})", rows)

        # -- exit signal + gated distribution candidates ------------------------------
        con.executemany(
            "INSERT INTO coin_exit VALUES (?,?,?,?,?,?)",
            duck.execute(
                f"""
                SELECT mint, n_distributors, max_iceberg_score,
                       CAST(any_recent AS INTEGER), n_timing_pass, last_dist_t
                FROM read_parquet('{exit_signal}')
                """
            ).fetchall(),
        )
        cursor = duck.execute(
            f"""
            SELECT mint, owner, iceberg_score, drawdown, sold_frac_of_own, n_dist_sells,
                   dist_sold_sol, duration_s, resilience, timing_q, self_wash,
                   CAST(is_recent AS INTEGER), last_dist_t
            FROM read_parquet('{iceberg}') WHERE is_candidate
            """
        )
        n_candidates = 0
        while rows := cursor.fetchmany(100_000):
            n_candidates += len(rows)
            con.executemany(f"INSERT INTO iceberg VALUES ({','.join('?' * 13)})", rows)

        # -- crew ledger join (precomputed; the ledger may be unreachable) ------------
        crew_meta = _join_crews(
            duck, con, crew_ledger_path,
            owners_path=owners_path if have_trades else None,
            mints_path=mints_path if have_trades else None,
            iceberg_path=iceberg,
        )

        meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "wallets_dir": str(wallets_dir),
            "comp_source": comp_source,
            "n_wallets": int(n_wallets),
            "n_coins": con.execute("SELECT count(*) FROM coin").fetchone()[0],
            "n_exit_coins": con.execute("SELECT count(*) FROM coin_exit").fetchone()[0],
            "n_iceberg_candidates": n_candidates,
            "corpus_start": int(corpus_start),
            "updated_through": int(updated_through),
            "corpus_span": [
                datetime.fromtimestamp(int(corpus_start), UTC).date().isoformat(),
                datetime.fromtimestamp(int(updated_through), UTC).date().isoformat(),
            ],
            "crowd": {
                "net_realized_sol_sum": round(float(net_sum), 1),
                "median_net_sol": round(float(net_median), 5),
                "frac_positive": round(float(frac_positive), 4),
            },
            "guild_stats": guild_stats,
            "crew_ledger": crew_meta,
        }
        con.executemany("INSERT INTO meta VALUES (?,?)", ((k, json.dumps(v)) for k, v in meta.items()))
        con.commit()
    finally:
        con.close()
        duck.close()
    os.replace(tmp, out_path)
    meta["build_seconds"] = round(time.time() - t0, 1)
    meta["artifact_bytes"] = out_path.stat().st_size
    return meta


def _join_crews(
    duck: Any,
    con: sqlite3.Connection,
    ledger_path: Path | None,
    *,
    owners_path: Path | None,
    mints_path: Path | None,
    iceberg_path: Path,
) -> dict[str, Any] | None:
    """Fold dregg_screen's crew ledger into per-coin rows. Returns the ledger's identity
    for meta, or None (with the coin card then saying the ledger was not joined)."""

    if ledger_path is None or not ledger_path.exists():
        return None
    ledger = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    try:
        lmeta = {k: json.loads(v) for k, v in ledger.execute("SELECT key, value FROM meta")}
        crews = {
            crew_id: (int(n_coins), int(rips), int(dumps), int(dirty))
            for crew_id, n_coins, rips, dumps, dirty in ledger.execute(
                "SELECT crew_id, n_coins, rips, dumps, dirty FROM crews"
            )
        }
        # Coins the corpus shares with a crew's own launch set: a direct "launched by".
        crew_of_mint = dict(ledger.execute("SELECT mint, crew_id FROM crew_coins"))
        crew_wallets = ledger.execute(
            "SELECT DISTINCT c.crew_id, s.wallet FROM crew_set s JOIN crew_coins c USING (mint)"
        ).fetchall()
    finally:
        ledger.close()

    direct = [
        (mint, crew_of_mint[mint], 1, None, *crews[crew_of_mint[mint]])
        for (mint,) in con.execute("SELECT mint FROM coin")
        if mint in crew_of_mint
    ]
    con.executemany("INSERT INTO coin_crew VALUES (?,?,?,?,?,?,?,?)", direct)

    # Trader-set overlap with crew birth-slot sets. This is participation overlap at the
    # coin grain — context, NOT the validated pairwise fingerprint match (that unit lives
    # in dregg_screen.ledger.crew_match and needs a launch's own birth slot).
    import pyarrow as pa

    duck.register(
        "crew_wallets",
        pa.table({
            "crew_id": [row[0] for row in crew_wallets],
            "wallet": [row[1] for row in crew_wallets],
        }),
    )
    if owners_path is not None and owners_path.exists() and mints_path is not None:
        # Full trader sets: the temp ``part`` table (mint_id, owner_id) from the build.
        overlap_sql = f"""
            SELECT m.mint, cw.crew_id, count(DISTINCT o.owner) AS n_overlap
            FROM part p
            JOIN read_parquet('{owners_path}') o USING (owner_id)
            JOIN crew_wallets cw ON cw.wallet = o.owner
            JOIN read_parquet('{mints_path}') m USING (mint_id)
            GROUP BY m.mint, cw.crew_id
            HAVING count(DISTINCT o.owner) >= {CREW_MIN_OVERLAP}
            QUALIFY row_number() OVER (
                PARTITION BY m.mint ORDER BY count(DISTINCT o.owner) DESC) <= {CREW_TOP_PER_COIN}
        """
    else:
        # Holder fallback: iceberg episode rows carry the base58 owner directly.
        overlap_sql = f"""
            SELECT i.mint, cw.crew_id, count(DISTINCT i.owner) AS n_overlap
            FROM (SELECT DISTINCT mint, owner FROM read_parquet('{iceberg_path}')) i
            JOIN crew_wallets cw ON cw.wallet = i.owner
            GROUP BY i.mint, cw.crew_id
            HAVING count(DISTINCT i.owner) >= {CREW_MIN_OVERLAP}
            QUALIFY row_number() OVER (
                PARTITION BY i.mint ORDER BY count(DISTINCT i.owner) DESC) <= {CREW_TOP_PER_COIN}
        """
    rows = duck.execute(overlap_sql).fetchall()
    con.executemany(
        "INSERT INTO coin_crew VALUES (?,?,?,?,?,?,?,?)",
        ((mint, crew_id, 0, int(n), *crews[crew_id]) for mint, crew_id, n in rows),
    )
    return {
        "path": str(ledger_path),
        "built_at": lmeta.get("built_at"),
        "corpus_span": lmeta.get("corpus_span"),
        "crews": lmeta.get("crews"),
        "n_direct": len(direct),
        "n_overlap_rows": len(rows),
    }


# -- runtime (stdlib only; this is all the bot touches per lookup) ---------------------


class Dossier:
    """Read-only view over the sqlite artifact. One connection, no writes, no pandas.

    ``wallet()`` and ``coin()`` return ``None`` on a miss so the caller can render the
    null-with-reason copy — the layer itself never invents a zero.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"dossier artifact not found: {self.path}")
        self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self.meta: dict[str, Any] = {
            k: json.loads(v) for k, v in self._con.execute("SELECT key, value FROM meta")
        }
        if self.meta.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"dossier schema {self.meta.get('schema_version')} != expected {SCHEMA_VERSION}; "
                f"rebuild with `python -m dregg_dossier build`"
            )

    def close(self) -> None:
        self._con.close()

    @property
    def staleness_days(self) -> float | None:
        end = self.meta.get("updated_through")
        if not end:
            return None
        return round((datetime.now(UTC).timestamp() - end) / 86400, 1)

    def wallet(self, owner: str) -> dict[str, Any] | None:
        row = self._con.execute("SELECT * FROM wallet WHERE owner = ?", (owner,)).fetchone()
        return dict(row) if row is not None else None

    def coin(self, mint: str, *, top_icebergs: int = 3) -> dict[str, Any] | None:
        """Everything the coin card renders, or None when the coin is not in the corpus.
        ``exit`` is None when the coin has NO gated distributor — a clean no-signal."""

        comp = self._con.execute("SELECT * FROM coin WHERE mint = ?", (mint,)).fetchone()
        if comp is None:
            return None
        exit_row = self._con.execute("SELECT * FROM coin_exit WHERE mint = ?", (mint,)).fetchone()
        icebergs = self._con.execute(
            "SELECT * FROM iceberg WHERE mint = ? ORDER BY iceberg_score DESC LIMIT ?",
            (mint, top_icebergs),
        ).fetchall()
        crews = self._con.execute(
            "SELECT * FROM coin_crew WHERE mint = ? ORDER BY launched_by DESC, n_overlap DESC",
            (mint,),
        ).fetchall()
        return {
            "comp": dict(comp),
            "exit": dict(exit_row) if exit_row is not None else None,
            "icebergs": [dict(row) for row in icebergs],
            "crews": [dict(row) for row in crews],
        }


def resolve_current(out_dir: Path = DEFAULT_OUT_DIR) -> Path:
    """The path the bot loads: ``current.sqlite`` in the dossier dir."""

    return out_dir / "current.sqlite"


def _swap_current(out_dir: Path, target: Path) -> None:
    link = resolve_current(out_dir)
    tmp = out_dir / ".current.tmp"
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target.name)
    os.replace(tmp, link)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m dregg_dossier", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the dossier index from state/wallets")
    b.add_argument("--wallets-dir", type=Path, default=DEFAULT_WALLETS_DIR)
    b.add_argument("--trades", type=Path, default=DEFAULT_PVP_DIR / "trades.parquet")
    b.add_argument("--mints", type=Path, default=DEFAULT_PVP_DIR / "mints.parquet")
    b.add_argument("--owners", type=Path, default=DEFAULT_PVP_DIR / "owners.parquet")
    b.add_argument("--crew-ledger", type=Path, default=DEFAULT_CREW_LEDGER)
    b.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    b.add_argument("--threads", type=int, default=6)
    b.add_argument("--memory", default="8GB")

    s = sub.add_parser("show", help="print the loaded artifact's meta")
    s.add_argument("--path", type=Path, default=None)

    for name, help_text in (("wallet", "render the /wallet card"), ("coin", "render the /coin card")):
        c = sub.add_parser(name, help=f"{help_text} for an address (smoke test)")
        c.add_argument("address")
        c.add_argument("--path", type=Path, default=None)

    args = ap.parse_args(argv)
    if args.cmd == "build":
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        out = args.out_dir / f"dossier-{stamp}.sqlite"
        meta = build(
            args.wallets_dir,
            out,
            trades_path=args.trades,
            mints_path=args.mints,
            owners_path=args.owners,
            crew_ledger_path=args.crew_ledger,
            threads=args.threads,
            memory=args.memory,
        )
        _swap_current(args.out_dir, out)
        print(json.dumps(meta, indent=2))
        print(f"-> {out}\n-> {resolve_current(args.out_dir)} (current)")
        return 0
    if args.cmd == "show":
        dossier = Dossier(args.path or resolve_current())
        meta = dict(dossier.meta)
        meta["staleness_days"] = dossier.staleness_days
        print(json.dumps(meta, indent=2))
        return 0
    # wallet / coin: render the exact card the bot would send.
    from . import cards

    dossier = Dossier(args.path or resolve_current())
    now = time.time()
    if args.cmd == "wallet":
        row = dossier.wallet(args.address)
        text = cards.wallet_card(row, dossier.meta, now) if row else cards.wallet_miss(
            args.address, dossier.meta, now
        )
    else:
        view = dossier.coin(args.address)
        text = cards.coin_card(args.address, view, dossier.meta, now) if view else cards.coin_miss(
            args.address, dossier.meta, now
        )
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
