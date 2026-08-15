"""pump.fun polling feed for the shadow scalper.

Read-only, keyless, gentle: one listing call per poll plus detail refreshes only
for mints we are actively tracking. Every snapshot carries t_ingest (our clock)
and the platform's own created/last-trade timestamps (the event clock) — two
timestamps, always, per the Track B lesson that mixing them fabricates latencies.

The feed is deliberately isolated behind ``poll_listing`` / ``poll_mint`` so the
endpoint can be swapped without touching policy, book, or marking.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shitcoims_scalper.shadow import CurveState

BASE = "https://frontend-api-v3.pump.fun"
UA = "shitcoims-scalper-shadow/0.1 (read-only research)"

# Fresh curves start with 30 virtual SOL; SOL actually deposited is vsol - 30.
VIRTUAL_SOL_FLOOR_LAMPORTS = 30_000_000_000


@dataclass(frozen=True, slots=True)
class MintSnapshot:
    mint: str
    t_ingest_unix: float
    created_unix: float
    last_trade_unix: float | None
    vsol_lamports: int
    vtok_raw: int
    complete: bool

    @property
    def curve(self) -> CurveState:
        return CurveState(
            t_ingest_unix=self.t_ingest_unix,
            vsol_lamports=self.vsol_lamports,
            vtok_raw=self.vtok_raw,
        )

    def features(self) -> dict[str, float]:
        now = self.t_ingest_unix
        recency = (now - self.last_trade_unix) if self.last_trade_unix else 1e9
        sol_in_curve = max(0, self.vsol_lamports - VIRTUAL_SOL_FLOOR_LAMPORTS) / 1e9
        return {
            "age_s": now - self.created_unix,
            "trade_recency_s": max(0.0, recency),
            "sol_in_curve": sol_in_curve,
        }


def _get(url: str, timeout: float = 10.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _snapshot(coin: dict, t_ingest: float) -> MintSnapshot | None:
    try:
        vsol = int(coin["virtual_sol_reserves"])
        vtok = int(coin["virtual_token_reserves"])
        if vsol <= 0 or vtok <= 0:
            return None
        last_trade = coin.get("last_trade_timestamp")
        return MintSnapshot(
            mint=str(coin["mint"]),
            t_ingest_unix=t_ingest,
            created_unix=int(coin["created_timestamp"]) / 1000.0,
            last_trade_unix=(int(last_trade) / 1000.0) if last_trade else None,
            vsol_lamports=vsol,
            vtok_raw=vtok,
            complete=bool(coin.get("complete", False)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _listing(sort: str, limit: int) -> list[MintSnapshot]:
    url = f"{BASE}/coins?offset=0&limit={limit}&sort={sort}&order=DESC&includeNsfw=false"
    try:
        data = _get(url)
    except Exception:
        return []
    t = time.time()
    coins = data if isinstance(data, list) else []
    out = []
    for coin in coins:
        if isinstance(coin, dict):
            snap = _snapshot(coin, t)
            if snap is not None:
                out.append(snap)
    return out


def poll_listing(limit: int = 50) -> list[MintSnapshot]:
    """Two listings, deduped: newest-created AND recently-traded.

    The first smoke run proved created-DESC alone samples the nursery — coins
    seconds old with empty curves; 132 decisions, zero verdict passes. The
    coins actually matching a liveness filter are on the last_trade sort: the
    "looked alive enough" population the operator was clicking through by hand.
    """
    by_mint: dict[str, MintSnapshot] = {}
    for sort in ("created_timestamp", "last_trade_timestamp"):
        for snap in _listing(sort, limit):
            by_mint[snap.mint] = snap
    return list(by_mint.values())


def poll_mint(mint: str) -> MintSnapshot | None:
    """Refresh one tracked mint. None on any failure — the caller decides what a lost feed means."""
    try:
        data = _get(f"{BASE}/coins/{mint}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _snapshot(data, time.time())


# ---------------------------------------------------------------------------------
# callout-sourced candidates — the strategy the operator actually described
# ---------------------------------------------------------------------------------
#
# The operator's original account was: "clicking on every coin in the callout feed
# and glancing at it for a few seconds". The first probe never did that — it polled
# the general listing, i.e. every coin alive on the platform. That is a DIFFERENT
# STRATEGY over a different population, and it is the one that lost 15%.
#
# This reads the intelligence store's already-collected social stream. It is
# strictly read-only over a COPY: the inteld daemon holds a write lock, and opening
# the live file directly raises "database is locked".
#
# Detection latency matters and is measured: x_mint_mention runs p50 209s, which is
# inside Marino's 4.4-minute median time-to-graduation. Everything else is far
# slower (claudekol_claim p50 1,280s, x_reply 8,291s) and is research-grade, not
# trade-grade. `max_age_s` enforces that rather than trusting the source.

INTEL_DB = Path(__file__).resolve().parent.parent / "intelligence_state" / "intelligence.sqlite3"

#: Kinds that carry a mint, ordered by measured detection latency (fastest first).
CALLOUT_KINDS: tuple[str, ...] = ("x_mint_mention", "claudekol_claim", "x_cashtag")


@dataclass(frozen=True, slots=True)
class Callout:
    """One social mention resolved to a mint, with the clock we can defend."""

    mint: str
    kind: str
    t_post_unix: float
    author: str | None
    resolved_from: str  # "payload_mint" | "mint_candidates" | "subject_id"


def _b58_mintish(text: str) -> bool:
    """A real Solana address, not merely a string shaped like one.

    The previous test was length plus a forbidden-character set, which admits
    any 32-44 character string over the base58 alphabet — including transaction
    signature fragments and truncated addresses. Decoding to exactly 32 bytes is
    the actual definition and costs nothing at this volume. Measured on the live
    store, the old test also silently dropped a lowercased address instead of
    defecting it, so a bad string and a bad *parse* were indistinguishable.
    """

    from shitcoims_intelligence.adapters.x_apify import is_solana_mint

    return is_solana_mint(text)


def poll_callouts(*, max_age_s: float = 900.0, limit: int = 200) -> list[Callout]:
    """Recent mint-resolved callouts from the intelligence store. Never raises."""
    if not INTEL_DB.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_s)
    tmp = Path(tempfile.gettempdir()) / "scalper_intel_snapshot.sqlite3"
    try:
        shutil.copy2(INTEL_DB, tmp)  # the daemon holds a write lock on the original
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    except Exception:
        return []
    out: list[Callout] = []
    seen: set[str] = set()
    try:
        placeholders = ",".join("?" for _ in CALLOUT_KINDS)
        rows = conn.execute(
            f"SELECT kind, subject_type, subject_id, observed_at, payload_json "
            f"FROM observations WHERE kind IN ({placeholders}) AND observed_at > ? "
            f"ORDER BY observed_at DESC LIMIT ?",
            (*CALLOUT_KINDS, cutoff.isoformat(), limit),
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    for kind, subject_type, subject_id, observed_at, payload_json in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            payload = {}
        mint, source = None, ""
        if isinstance(payload.get("mint"), str) and _b58_mintish(payload["mint"]):
            mint, source = payload["mint"], "payload_mint"
        elif subject_type == "token" and isinstance(subject_id, str) and _b58_mintish(subject_id):
            mint, source = subject_id, "subject_id"
        else:
            for cand in payload.get("mint_candidates") or []:
                if isinstance(cand, str) and _b58_mintish(cand):
                    mint, source = cand, "mint_candidates"
                    break
        if not mint or mint in seen:
            continue
        seen.add(mint)
        try:
            t_post = datetime.fromisoformat(observed_at).timestamp()
        except (TypeError, ValueError):
            continue
        out.append(
            Callout(
                mint=mint,
                kind=kind,
                t_post_unix=t_post,
                author=payload.get("author_username") or payload.get("author"),
                resolved_from=source,
            )
        )
    return out


def poll_callout_snapshots(*, max_age_s: float = 900.0) -> list[tuple[MintSnapshot, Callout]]:
    """Callouts joined to live curve state — the candidate stream, paired with its provenance."""
    paired: list[tuple[MintSnapshot, Callout]] = []
    for callout in poll_callouts(max_age_s=max_age_s):
        snap = poll_mint(callout.mint)
        if snap is not None:
            paired.append((snap, callout))
    return paired
