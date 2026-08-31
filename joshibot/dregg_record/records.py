"""Per-caller record aggregation from the callout archive. Measured beside claimed, never merged.

One caller, one dict: ``caller_record`` (the standing record), ``last_calls`` (their
recent tape), ``resolve_caller`` (wallet-or-username -> wallets). Rules, shared with
dregg_wire.facts and enforced here:

* MEASURED numbers come from the ``outcomes`` table only — our candle closes, anchored
  at the callout's clock, method-versioned. The provider's ``multiple`` is a
  recomputed-at-read tick-peak stat; it renders ONLY under a "their claim" label.
* Absences are STATED STRINGS, never zeros. "No measured outcomes yet" is a fact about
  maturity (T+25h / T+7d), not a zero return.
* Every stat carries its n.
* Removals count from ``removal_verdicts`` with ``published=1`` only — a verdict the
  operator has not published is not yet a public fact.
* The wallet layer (estimator.parquet) is a stale batch artifact: color only, joined
  via dregg_wire.facts.caller_color, always stamped as-of + stale
  (state/wallets/JOIN_CONTRACT.md).

stdlib sqlite3 over a read-only connection; the parquet join is optional and states
its own absence.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from dregg_archive.store import MS_DAY
from dregg_wire.facts import caller_color

METHOD_VERSION = "v1"
WINDOW_DAYS = 30
LAST_CALLS = 5
HANDLE_MAX = 24

MEASURED_METHOD = (
    "our archived candle closes, anchored at the callout's clock (outcomes method {v}); "
    "returns mature at T+25h and finalize at T+7d"
)
CLAIM_LABEL = "provider-claimed peak multiples — their recomputed tick-peak stat, never our measurement"

BASE58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")


# -- formatting helpers (shared by the leaderboard and the /caller card) ---------------


def fmt_pct(value: float) -> str:
    return f"{value:+.1%}"


def fmt_mult(value: float) -> str:
    return f"{value:,.1f}x"


def flat(text: str, limit: int = HANDLE_MAX) -> str:
    """Whitespace-flattened and clamped: a hostile provider name cannot add lines."""

    return ("".join(str(text).split()) or "?")[:limit]


def handle(username: str | None, x_username: str | None, wallet: str) -> str:
    name = username or x_username
    return f"@{flat(name)}" if name else short_wallet(wallet)


def short_wallet(wallet: str) -> str:
    return f"{wallet[:4]}…{wallet[-4:]}" if len(wallet) > 12 else wallet


def utc_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


# -- plumbing --------------------------------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _dist(values: list[float], absent: str) -> dict:
    if not values:
        return {"n": 0, "absent": absent}
    return {"n": len(values), "median": median(values), "mean": mean(values)}


# -- the record ------------------------------------------------------------------------


def caller_record(
    archive_db: Path,
    wallet: str,
    *,
    now_ms: int,
    window_days: int = WINDOW_DAYS,
    method_version: str = METHOD_VERSION,
    wallet_parquet: Path | None = None,
) -> dict:
    """The standing record for one caller wallet. Absent archive / unknown wallet are
    stated absences; a wallet with callouts ALWAYS gets its counts, even before any
    outcome has matured."""

    if not archive_db.exists():
        return {"wallet": wallet, "absent": f"callout archive not present at {archive_db}"}
    db = _connect_ro(archive_db)
    try:
        caller = db.execute(
            "SELECT username_last, x_username_last, first_seen_ms, last_seen_ms"
            " FROM callers WHERE wallet = ?",
            (wallet,),
        ).fetchone()
        rows = db.execute(
            "SELECT c.callout_id, c.mint, c.t_event_ms, c.provider_multiple_last,"
            "       c.username_last, c.x_username_last,"
            "       o.ret_1h, o.ret_24h, o.ret_7d, o.max_close_multiple, o.max_drawdown, o.dead_flag"
            "  FROM callouts c"
            "  LEFT JOIN outcomes o ON o.callout_id = c.callout_id AND o.method_version = ?"
            " WHERE c.wallet = ?",
            (method_version, wallet),
        ).fetchall()
        removal_counts = dict(
            db.execute(
                "SELECT v.verdict, count(*) FROM removal_verdicts v"
                "  JOIN callouts c ON c.callout_id = v.callout_id"
                " WHERE c.wallet = ? AND v.published = 1 GROUP BY v.verdict",
                (wallet,),
            ).fetchall()
        )
    finally:
        db.close()
    if not rows:
        return {"wallet": wallet, "absent": f"no archived callouts for wallet {wallet}"}

    dated = [r for r in rows if r["t_event_ms"] is not None]
    window_start = now_ms - window_days * MS_DAY
    in_window = [r for r in dated if r["t_event_ms"] >= window_start]

    username = caller["username_last"] if caller else None
    x_username = caller["x_username_last"] if caller else None
    if username is None or x_username is None:
        newest = max(dated, key=lambda r: r["t_event_ms"], default=rows[0])
        username = username or newest["username_last"]
        x_username = x_username or newest["x_username_last"]
    first_ms = (caller["first_seen_ms"] if caller else None) or min(
        (r["t_event_ms"] for r in dated), default=None
    )
    last_ms = (caller["last_seen_ms"] if caller else None) or max(
        (r["t_event_ms"] for r in dated), default=None
    )

    with_outcomes = [r for r in rows if r["ret_1h"] is not None or r["ret_24h"] is not None
                     or r["ret_7d"] is not None or r["dead_flag"] is not None]
    if with_outcomes:
        ret_24h = [r["ret_24h"] for r in rows if r["ret_24h"] is not None]
        finals = [r for r in rows if r["dead_flag"] is not None]
        drawdowns = [r["max_drawdown"] for r in rows if r["max_drawdown"] is not None]
        measured: dict = {
            "method": MEASURED_METHOD.format(v=method_version),
            "n_with_outcomes": len(with_outcomes),
            "ret_1h": _dist([r["ret_1h"] for r in rows if r["ret_1h"] is not None],
                            "no call has a priced 1h close yet"),
            "ret_24h": _dist(ret_24h, "no call has a priced 24h close yet"),
            "ret_7d": _dist([r["ret_7d"] for r in rows if r["ret_7d"] is not None],
                            "no call has a priced 7d close yet"),
            "hits_24h": (
                {
                    "n": len(ret_24h),
                    "above_0": sum(1 for v in ret_24h if v > 0),
                    "above_50": sum(1 for v in ret_24h if v >= 0.5),
                }
                if ret_24h
                else {"n": 0, "absent": "no priced 24h closes yet"}
            ),
            "drawdown": (
                {"n": len(drawdowns), "median": median(drawdowns)}
                if drawdowns
                else {"n": 0, "absent": "no call has finalized its 7d window yet"}
            ),
            "dead": (
                {
                    "n_final": len(finals),
                    "n_dead": sum(1 for r in finals if r["dead_flag"]),
                    "rate": sum(1 for r in finals if r["dead_flag"]) / len(finals),
                }
                if finals
                else {"n_final": 0, "absent": "no call has passed its +7d gate yet"}
            ),
        }
    else:
        measured = {
            "absent": "no measured outcomes yet — outcomes mature at T+25h and finalize at T+7d"
        }

    claims = [r["provider_multiple_last"] for r in rows if r["provider_multiple_last"] is not None]
    provider_claim = (
        {"n": len(claims), "median_multiple": median(claims), "max_multiple": max(claims),
         "label": CLAIM_LABEL}
        if claims
        else {"n": 0, "absent": "the provider published no multiple for these calls",
              "label": CLAIM_LABEL}
    )

    removals = {
        "published_removed": int(removal_counts.get("removed", 0)),
        "published_unknown_absent": int(removal_counts.get("unknown-absent", 0)),
        "note": (
            "removed callouts STAY on this record; deletion adds a verdict, never subtracts a call"
            if removal_counts
            else "none on record"
        ),
    }

    return {
        "wallet": wallet,
        "source": f"dregg_archive {archive_db.name}, outcomes method {method_version}",
        "identity": {
            "username": username,
            "x_username": x_username,
            "first_seen": utc_day(first_ms) if first_ms else None,
            "last_seen": utc_day(last_ms) if last_ms else None,
            "seen_note": None if first_ms else "provider served no event timestamps for these calls",
        },
        "callouts": {
            "lifetime": len(rows),
            "window": len(in_window),
            "window_days": window_days,
            "undated": len(rows) - len(dated),
            "distinct_mints": len({r["mint"] for r in rows}),
        },
        "measured": measured,
        "provider_claim": provider_claim,
        "removals": removals,
        "wallet_layer": _wallet_layer(wallet_parquet, wallet),
    }


def _wallet_layer(wallet_parquet: Path | None, wallet: str) -> dict:
    """One wallet's slice of the (stale) estimator layer, contract-compliant."""

    color = caller_color(wallet_parquet, [wallet])
    if "entries" not in color:
        return color  # absent-with-reason + the staleness note, verbatim
    entry = dict(color["entries"][0])
    entry.pop("wallet", None)
    return {"as_of": color["as_of"], "stale": True, "note": color["note"], **entry}


# -- the recent tape -------------------------------------------------------------------


def last_calls(
    archive_db: Path,
    wallet: str,
    *,
    limit: int = LAST_CALLS,
    method_version: str = METHOD_VERSION,
) -> list[dict]:
    """The caller's most recent callouts, measured outcomes and removal flags attached."""

    if not archive_db.exists():
        return []
    db = _connect_ro(archive_db)
    try:
        rows = db.execute(
            "SELECT c.callout_id, c.mint, c.t_event_ms, c.provider_multiple_last,"
            "       o.ret_1h, o.ret_24h, o.ret_7d, o.dead_flag,"
            "       (SELECT v.verdict FROM removal_verdicts v"
            "         WHERE v.callout_id = c.callout_id AND v.published = 1) AS removal"
            "  FROM callouts c"
            "  LEFT JOIN outcomes o ON o.callout_id = c.callout_id AND o.method_version = ?"
            " WHERE c.wallet = ?"
            " ORDER BY (c.t_event_ms IS NULL), c.t_event_ms DESC LIMIT ?",
            (method_version, wallet, limit),
        ).fetchall()
    finally:
        db.close()
    return [
        {
            "callout_id": r["callout_id"],
            "mint": r["mint"],
            "day": utc_day(r["t_event_ms"]) if r["t_event_ms"] is not None else None,
            "claimed_multiple": r["provider_multiple_last"],
            "ret_1h": r["ret_1h"],
            "ret_24h": r["ret_24h"],
            "ret_7d": r["ret_7d"],
            "dead": None if r["dead_flag"] is None else bool(r["dead_flag"]),
            "removal": r["removal"],
        }
        for r in rows
    ]


# -- identity resolution ---------------------------------------------------------------


def resolve_caller(archive_db: Path, query: str, *, limit: int = 5) -> list[str]:
    """Wallet-or-username -> caller wallets, newest activity first.

    A base58-shaped query matches an exact wallet on the record; anything else (a
    leading ``@`` is stripped) matches provider or X usernames case-insensitively —
    first against the ``callers`` roster, falling back to the callouts themselves so a
    caller the roster missed is still findable. More than one wallet can share a name
    (names are provider text, not identity); all matches return, capped at ``limit``.
    """

    if not archive_db.exists():
        return []
    q = query.strip().lstrip("@")
    if not q:
        return []
    db = _connect_ro(archive_db)
    try:
        if BASE58.fullmatch(q):
            known = db.execute(
                "SELECT 1 FROM callouts WHERE wallet = ? LIMIT 1", (q,)
            ).fetchone() or db.execute("SELECT 1 FROM callers WHERE wallet = ?", (q,)).fetchone()
            if known:
                return [q]
        rows = db.execute(
            "SELECT wallet FROM callers"
            " WHERE lower(coalesce(username_last, '')) = lower(?)"
            "    OR lower(coalesce(x_username_last, '')) = lower(?)"
            " ORDER BY last_seen_ms DESC, wallet LIMIT ?",
            (q, q, limit),
        ).fetchall()
        if not rows:
            rows = db.execute(
                "SELECT wallet, max(coalesce(t_event_ms, 0)) AS newest FROM callouts"
                " WHERE lower(coalesce(username_last, '')) = lower(?)"
                "    OR lower(coalesce(x_username_last, '')) = lower(?)"
                " GROUP BY wallet ORDER BY newest DESC, wallet LIMIT ?",
                (q, q, limit),
            ).fetchall()
    finally:
        db.close()
    return [r["wallet"] for r in rows]
