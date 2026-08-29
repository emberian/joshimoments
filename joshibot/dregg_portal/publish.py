"""Build the portal bundle ON HBOX. The only half of the portal that touches real data.

    uv run python -m dregg_portal.publish \\
        --gate-db     /home/hbox/dregg-data/gate/gate.sqlite \\
        --watch-db    /home/hbox/dregg-data/watch/watch.sqlite \\
        --scores-dir  /home/hbox/dregg-data/screen/scores \\
        --archive-db  /home/hbox/dregg-data/archive/archive.sqlite \\
        --dossier     /home/hbox/dregg-data/wallets/dossier/current.sqlite \\
        --out         /home/hbox/dregg-data/portal/bundle

WHAT IT PRODUCES, and what each thing is for:

    roster.json          who holds, as the GATE decided it. The portal's whole auth model.
    manifest.json        what is in the bundle and when it was made.
    gated/*.html         the reading pages, pre-rendered.
    holders/<wallet>.json  one holder's private view (their watchlist), keyed by wallet.

⚠ READ-ONLY, AND NOT THROUGH ``GateState``. That class takes an exclusive flock as its
FIRST act, because the flock guards the identity of the Telegram long-poller: a second
holder of it is a second bot on one token. A publisher that instantiated it would either
refuse to start (bot running) or steal the guard (bot restarting). So the gate database is
opened here with ``mode=ro`` on a URI, directly. The publisher never writes to it, never
locks it, and cannot deadlock the thing that earns the money.

⚠ WHAT DELIBERATELY DOES NOT LEAVE THIS BOX. The roster is wallet-keyed and carries NO
Telegram identifiers. The gate's whole value as a private record is the wallet-to-account
linkage, and that linkage is used HERE — to attach a holder's watchlist to their wallet —
and then dropped. The anchor learns that wallet W watches mint M; it never learns which
Telegram account either belongs to.

The holder roster itself is public chain data (a token's holders are on-chain and any
explorer lists them), so its confidentiality is NOT claimed as a security property. It
still ships to a 0700 directory that no Caddy root names, because "public" and "handed
out on request" are different things.

Deterministic given ``--day`` and ``--now``: no page here reads a clock of its own.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from dregg_dossier.store import Dossier
from dregg_record.leaderboard import build_leaderboard
from dregg_site import record as site_record
from dregg_site.build import data_through as compute_data_through
from dregg_wire.facts import build_facts, load_scores

from . import SCHEMA_HOLDER, SCHEMA_MANIFEST, SCHEMA_ROSTER
from . import gated as pages

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEFAULT_MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
DEFAULT_THRESHOLD = 888_888
# How many coin/wallet dossiers to render. The slice is BOUNDED on purpose: 728k profiled
# wallets is not a static site, and a page that exists for everything would either take
# hours to build or be mostly empty cards that read like findings.
MAX_COIN_PAGES = 400
MAX_WALLET_PAGES = 400


class PublishError(RuntimeError):
    pass


def _ro(path: Path) -> sqlite3.Connection:
    """Open read-only. A missing file raises here rather than being created empty."""

    if not path.exists():
        raise PublishError(f"no database at {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    connection.row_factory = sqlite3.Row
    return connection


# -- the roster ----------------------------------------------------------------------


def read_gate(
    gate_db: Path, *, threshold_tokens: int, overrides: dict[str, int]
) -> tuple[dict[str, dict], int | None, dict[str, int]]:
    """Members as wallet -> standing, plus the on-chain decimals the gate verified.

    Returns ``(holdings, decimals, wallet_to_tg)``. The third value never leaves this
    process — it is the join key for the per-holder views and is dropped immediately after.
    """

    connection = _ro(gate_db)
    try:
        decimals = None
        row = connection.execute("SELECT value FROM metadata WHERE key = 'mint_decimals'").fetchone()
        if row is not None:
            try:
                decimals = int(row["value"])
            except (TypeError, ValueError):
                decimals = None
        holdings: dict[str, dict] = {}
        linkage: dict[str, int] = {}
        for member in connection.execute(
            "SELECT tg_user_id, wallet, status, grace_until, last_checked_at, last_balance_raw FROM members"
        ):
            wallet = str(member["wallet"])
            raw = member["last_balance_raw"]
            try:
                balance = int(raw) if raw is not None else 0
            except (TypeError, ValueError):
                balance = 0
            effective = int(overrides.get(str(member["tg_user_id"]), threshold_tokens))
            holdings[wallet] = {
                "balance_raw": balance,
                "threshold_tokens": effective,
                "standing": str(member["status"]),
                "checked_at": member["last_checked_at"],
                "grace_until": member["grace_until"],
                "origin": "gate",
            }
            linkage[wallet] = int(member["tg_user_id"])
        return holdings, decimals, linkage
    finally:
        connection.close()


def read_snapshot(path: Path | None, *, threshold_tokens: int, decimals: int) -> dict[str, dict]:
    """An optional chain-holders snapshot: wallets that hold but have never used the bot.

    Without it the portal can only admit people the Telegram gate already knows, which
    makes the web a second door onto the same room rather than its own front door. The
    snapshot is produced by whatever already has a Helius key ON THIS BOX; the format is
    deliberately trivial — ``{"generated_at": t, "holders": {wallet: "<raw units>"}}`` —
    so producing it is never a reason to put a provider key anywhere new.
    """

    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PublishError(f"holders snapshot at {path} is unreadable or not JSON") from None
    holders = raw.get("holders") if isinstance(raw, dict) else None
    if not isinstance(holders, dict):
        raise PublishError("holders snapshot carries no 'holders' object")
    checked = raw.get("generated_at")
    need = threshold_tokens * 10**decimals
    out: dict[str, dict] = {}
    for wallet, amount in holders.items():
        if not isinstance(wallet, str) or not BASE58.match(wallet):
            continue
        try:
            balance = int(amount)
        except (TypeError, ValueError):
            continue
        out[wallet] = {
            "balance_raw": balance,
            "threshold_tokens": threshold_tokens,
            # A snapshot wallet has no grace clock — it was never in the group — so it is
            # simply above the line or 'short'. 'ejected' is a gate state and is not
            # invented here for someone the gate has never met.
            "standing": "ok" if balance >= need else "short",
            "checked_at": checked,
            "grace_until": None,
            "origin": "snapshot",
        }
    return out


def build_roster(
    *,
    gate_db: Path,
    snapshot: Path | None,
    mint: str,
    threshold_tokens: int,
    overrides: dict[str, int],
    now: float,
    day: str,
) -> tuple[dict, dict[str, int]]:
    gate_holdings, decimals, linkage = read_gate(
        gate_db, threshold_tokens=threshold_tokens, overrides=overrides
    )
    if decimals is None:
        raise PublishError(
            "the gate database has never recorded the mint's on-chain decimals — refusing to "
            "guess them. Let the bot run one /verify, or set them there, before publishing."
        )
    holdings = read_snapshot(snapshot, threshold_tokens=threshold_tokens, decimals=decimals)
    # The GATE WINS every collision. A wallet the bot has decided about carries a grace
    # clock and possibly a comped threshold; a chain snapshot knows neither.
    holdings.update(gate_holdings)
    sweep_status, sweep_day = _sweep_state(gate_db)
    roster = {
        "schema": SCHEMA_ROSTER,
        "generated_at": now,
        "generated_day": day,
        "mint": mint,
        "decimals": decimals,
        "threshold_tokens": threshold_tokens,
        "source": (
            "gate.sqlite members (daily re-verify, 48h grace)"
            + (" + chain holders snapshot" if snapshot else "")
            + ", desk box"
        ),
        "sweep": {"last_day": sweep_day, "status": sweep_status},
        "holders": dict(sorted(holdings.items())),
    }
    return roster, linkage


def _sweep_state(gate_db: Path) -> tuple[str, str | None]:
    connection = _ro(gate_db)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key = 'last_sweep_day'").fetchone()
        day = str(row["value"]) if row is not None else None
        result = connection.execute(
            "SELECT value FROM metadata WHERE key = 'last_sweep_result'"
        ).fetchone()
        status = str(result["value"]) if result is not None else ("complete" if day else "never")
        return status, day
    except sqlite3.Error:
        return "unknown", None
    finally:
        connection.close()


# -- per-holder views ----------------------------------------------------------------


def build_holder_views(watch_db: Path | None, linkage: dict[str, int]) -> dict[str, dict]:
    """wallet -> that holder's private view. Telegram ids are the JOIN KEY, never the output."""

    if watch_db is None or not watch_db.exists():
        return {}
    connection = _ro(watch_db)
    try:
        views: dict[str, dict] = {}
        for wallet, tg_user_id in linkage.items():
            rows = connection.execute(
                "SELECT kind, spec, mode, created_at FROM subscriptions WHERE tg_user_id = ? "
                "ORDER BY id",
                (tg_user_id,),
            ).fetchall()
            views[wallet] = {
                "schema": SCHEMA_HOLDER,
                "watchlist": [
                    {"kind": str(r["kind"]), "spec": str(r["spec"]), "mode": str(r["mode"])}
                    for r in rows
                ],
                "watch_note": (
                    "source: watch.sqlite on the desk box, joined through the Telegram account "
                    "that verified this wallet. Editing stays in Telegram, where the alerts land."
                ),
            }
        return views
    finally:
        connection.close()


# -- the bundle ----------------------------------------------------------------------


def _write(out: Path, rel: str, text: str) -> Path:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _slice_targets(rows: list[dict], board: dict) -> tuple[list[str], list[str]]:
    """Which coins and wallets get a page. Today's screen, plus the callers on the board."""

    mints, seen = [], set()
    for row in rows:
        mint = str(row.get("mint") or "")
        if BASE58.match(mint) and mint not in seen:
            seen.add(mint)
            mints.append(mint)
    wallets, seen_w = [], set()
    for row in board.get("rows") or []:
        wallet = str(row.get("wallet") or "")
        if BASE58.match(wallet) and wallet not in seen_w:
            seen_w.add(wallet)
            wallets.append(wallet)
    return mints[:MAX_COIN_PAGES], wallets[:MAX_WALLET_PAGES]


def generate(
    *,
    day: str,
    now: float,
    out_dir: Path,
    gate_db: Path,
    scores_dir: Path,
    archive_db: Path,
    watch_db: Path | None = None,
    dossier_index: Path | None = None,
    snapshot: Path | None = None,
    wallet_parquet: Path | None = None,
    mint: str = DEFAULT_MINT,
    threshold_tokens: int = DEFAULT_THRESHOLD,
    overrides: dict[str, int] | None = None,
    base_path: str = "/portal",
    latest_wire: str | None = None,
) -> dict:
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)

    roster, linkage = build_roster(
        gate_db=gate_db,
        snapshot=snapshot,
        mint=mint,
        threshold_tokens=threshold_tokens,
        overrides=overrides or {},
        now=now,
        day=day,
    )
    holder_views = build_holder_views(watch_db, linkage)
    del linkage  # the Telegram linkage does not survive this function, by construction

    rows = load_scores(scores_dir, day)
    facts = build_facts(day, scores_dir=scores_dir, archive_db=archive_db, wallet_parquet=wallet_parquet)
    rec = site_record.collect(archive_db) if archive_db.exists() else {"board": {}, "removals": {}}
    board = (
        build_leaderboard(archive_db, now_ms=int(now * 1000), wallet_parquet=wallet_parquet)
        if archive_db.exists()
        else {"absent": "no callout archive on this box", "coverage": {}}
    )
    through = compute_data_through(rows, archive_db, day)

    coin_mints, caller_wallets = _slice_targets(rows, board)
    screen_by_mint = {str(r.get("mint")): r for r in rows}

    written: list[str] = []
    coin_pages = wallet_pages = 0
    # ⚑ ONE BAD ROW MUST NOT COST THE ROSTER. These loops render hundreds of pages from a
    # third-party-shaped index; a single malformed field (a `updated_through` that is a
    # string where the schema says epoch, say) would otherwise abort the whole publish —
    # and the whole publish includes roster.json, which is the AUTH DATA. Losing a coin
    # page is a stated absence; losing the roster is the portal refusing everyone. So each
    # page is rendered in isolation and the failures are COUNTED INTO THE MANIFEST rather
    # than swallowed: a bundle that quietly rendered 3 of 400 pages must say so.
    render_failures: list[str] = []
    if dossier_index is not None and dossier_index.exists():
        dossier = Dossier(dossier_index)
        try:
            meta = dossier.meta
            for coin_mint in coin_mints:
                try:
                    view = dossier.coin(coin_mint)
                    if view is None:
                        continue
                    html = pages.page_coin(
                        coin_mint,
                        view,
                        meta,
                        base=base_path,
                        now=now,
                        screen_row=screen_by_mint.get(coin_mint),
                    )
                # The exception TYPE is the record; a message could carry provider text.
                except Exception as exc:
                    render_failures.append(f"coin/{coin_mint}: {type(exc).__name__}")
                    continue
                _write(out_dir, f"gated/coin/{coin_mint}.html", html)
                written.append(f"gated/coin/{coin_mint}.html")
                coin_pages += 1
            for owner in caller_wallets:
                try:
                    row = dossier.wallet(owner)
                    if row is None:
                        continue
                    html = pages.page_wallet(owner, row, meta, base=base_path, now=now)
                except Exception as exc:
                    render_failures.append(f"wallet/{owner}: {type(exc).__name__}")
                    continue
                _write(out_dir, f"gated/wallet/{owner}.html", html)
                written.append(f"gated/wallet/{owner}.html")
                wallet_pages += 1
        finally:
            dossier.close()

    slice_window = (
        f"dossier slice: {coin_pages} coins from {day}'s screen, {wallet_pages} wallets from the "
        f"leaderboard. Anything outside it is a stated absence, not a finding."
    )

    _write(
        out_dir,
        "gated/screen.html",
        pages.page_screen(rows, facts, day, base=base_path, data_through=through),
    )
    _write(
        out_dir,
        "gated/record.html",
        pages.page_record(rec, board, base=base_path, day=day, data_through=through),
    )
    _write(
        out_dir,
        "gated/index.html",
        pages.page_index(
            facts,
            rec,
            board,
            base=base_path,
            day=day,
            data_through=through,
            coin_pages=coin_pages,
            wallet_pages=wallet_pages,
            slice_window=slice_window,
            latest_wire=latest_wire,
        ),
    )
    written += ["gated/screen.html", "gated/record.html", "gated/index.html"]

    for wallet, view in sorted(holder_views.items()):
        _write(out_dir, f"holders/{wallet}.json", json.dumps(view, indent=1, sort_keys=True))

    _write(out_dir, "roster.json", json.dumps(roster, indent=1, sort_keys=True))
    manifest = {
        "schema": SCHEMA_MANIFEST,
        "generated_at": now,
        "day": day,
        "data_through": through,
        "slice_window": slice_window,
        "pages": sorted(written),
        "coin_pages": coin_pages,
        "wallet_pages": wallet_pages,
        "holder_views": len(holder_views),
        "roster_wallets": len(roster["holders"]),
        # Named, not just counted: "3 pages failed" is a shrug, and the names are what a
        # reader of last-publish.json needs to tell one bad row from a broken index.
        "render_failures": sorted(render_failures),
    }
    _write(out_dir, "manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dregg_portal.publish", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gate-db", type=Path, required=True)
    parser.add_argument("--scores-dir", type=Path, required=True)
    parser.add_argument("--archive-db", type=Path, required=True)
    parser.add_argument("--watch-db", type=Path, default=None)
    parser.add_argument("--dossier", type=Path, default=None)
    parser.add_argument("--snapshot", type=Path, default=None, help="optional chain holders snapshot JSON")
    parser.add_argument("--wallet-parquet", type=Path, default=None)
    parser.add_argument("--mint", default=DEFAULT_MINT)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--base-path", default="/portal")
    parser.add_argument("--latest-wire", default=None)
    parser.add_argument("--day", default=None)
    parser.add_argument("--now", type=float, default=None, help="override the clock (tests, replays)")
    args = parser.parse_args(argv)

    day = args.day or datetime.now(UTC).strftime("%Y-%m-%d")
    if not DAY_RE.match(day):
        parser.error(f"--day must be YYYY-MM-DD, got {day!r}")
    try:
        manifest = generate(
            day=day,
            now=args.now if args.now is not None else time.time(),
            out_dir=args.out,
            gate_db=args.gate_db,
            scores_dir=args.scores_dir,
            archive_db=args.archive_db,
            watch_db=args.watch_db,
            dossier_index=args.dossier,
            snapshot=args.snapshot,
            wallet_parquet=args.wallet_parquet,
            mint=args.mint,
            threshold_tokens=args.threshold,
            base_path=args.base_path,
            latest_wire=args.latest_wire,
        )
    except PublishError as exc:
        print(f"publish refused: {exc}")
        return 2
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
