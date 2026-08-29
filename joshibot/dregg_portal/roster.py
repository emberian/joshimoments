"""The holder roster: the gate's own decision, pushed to the public box and read there.

WHAT THIS FILE IS NOT. It is not a balance cache and it is not a chain query. It is the
answer ``dregg_gate.sweep`` already computed — including per-member threshold overrides,
grace clocks, and the day the sweep last completed — serialized so a second surface can
agree with the first BY CONSTRUCTION rather than by re-deriving it.

STALENESS IS NOT REVOCATION, and that is the whole outage policy in one line. The bot's
rule is that a provider error never ejects anyone; the web-side mirror of that rule is
that an old roster never locks anyone out. So there is no maximum trusted age here. An
old roster serves, loudly, with its age on the page. What DOES fail closed is a roster
that is missing or unparseable — a box that has never been told who holds must not guess,
and "serve nothing and say why" is the only honest reading of that state.

The confidentiality of this file is deliberately NOT claimed as a security property: a
token's holders are public on-chain and any explorer will list them. What must never
reach this box, and does not appear in this schema, is the wallet-to-Telegram linkage.
The file still lives under /var/lib with 0600 on a path no Caddy root names, because
"public information" and "convenient to hand out" are different things.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import SCHEMA_ROSTER

# Fresh enough that nobody needs telling. The publish timer runs hourly, so this is six
# consecutive missed pushes before the reader is bothered about it.
FRESH_SECONDS = 6 * 3600
# Past this, the banner stops being a footnote and becomes the loudest thing on the page.
LOUD_SECONDS = 48 * 3600

STANDING_SERVED = ("ok", "grace")


class RosterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Holding:
    """One wallet's standing, exactly as the gate decided it."""

    wallet: str
    balance_raw: int
    threshold_tokens: int
    standing: str  # 'ok' | 'grace' | 'ejected' | 'short'
    checked_at: float | None
    origin: str  # 'gate' (a verified member) | 'snapshot' (chain holders, never in the group)
    grace_until: float | None

    @property
    def entitled(self) -> bool:
        return self.standing in STANDING_SERVED


@dataclass(frozen=True, slots=True)
class Roster:
    generated_at: float
    generated_day: str
    mint: str
    decimals: int
    threshold_tokens: int
    source: str
    sweep_day: str | None
    sweep_status: str
    holdings: dict[str, Holding]

    def age_seconds(self, now: float) -> float:
        return max(0.0, now - self.generated_at)

    def freshness(self, now: float) -> str:
        age = self.age_seconds(now)
        if age <= FRESH_SECONDS:
            return "fresh"
        return "stale" if age <= LOUD_SECONDS else "very-stale"

    def lookup(self, wallet: str) -> Holding | None:
        return self.holdings.get(wallet)


def threshold_raw(threshold_tokens: int, decimals: int) -> int:
    return int(threshold_tokens) * 10 ** int(decimals)


def format_tokens(raw: int, decimals: int) -> str:
    """Byte-for-byte the bot's rendering (``dregg_gate.gateway.format_tokens``).

    Deliberately duplicated rather than imported: this is the only line of gateway.py the
    portal would need, and importing it would drag httpx and the Telegram transport onto
    the public box for a thousand separator. A test pins the two against each other, so
    the copy cannot drift without failing.
    """

    scale = 10**decimals
    whole, frac = divmod(raw, scale)
    text = f"{whole:,}"
    if frac:
        text += f".{frac:0{decimals}d}".rstrip("0")
    return text


def _number(value: object) -> float | None:
    """A real number or None. ``bool`` is an int in Python and is never a timestamp."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RosterError(f"roster field {name!r} must be an integer")
    return value


def parse(raw: object) -> Roster:
    if not isinstance(raw, dict):
        raise RosterError("roster is not an object")
    if raw.get("schema") != SCHEMA_ROSTER:
        raise RosterError(f"roster schema is not {SCHEMA_ROSTER}")
    generated_at = raw.get("generated_at")
    if isinstance(generated_at, bool) or not isinstance(generated_at, (int, float)):
        raise RosterError("roster generated_at must be a number")
    mint = raw.get("mint")
    if not isinstance(mint, str) or not mint:
        raise RosterError("roster mint must be a string")
    decimals = _int(raw.get("decimals"), "decimals")
    if not 0 <= decimals <= 18:
        raise RosterError("roster decimals out of range")
    threshold_tokens = _int(raw.get("threshold_tokens"), "threshold_tokens")
    if threshold_tokens <= 0:
        raise RosterError("roster threshold_tokens must be positive")
    sweep = raw.get("sweep") if isinstance(raw.get("sweep"), dict) else {}
    holders = raw.get("holders")
    if not isinstance(holders, dict):
        raise RosterError("roster holders must be an object")

    holdings: dict[str, Holding] = {}
    for wallet, entry in holders.items():
        if not isinstance(wallet, str) or not isinstance(entry, dict):
            raise RosterError("roster holder entry is malformed")
        standing = entry.get("standing")
        if standing not in ("ok", "grace", "ejected", "short"):
            raise RosterError(f"roster holder {wallet[:8]}… has an unknown standing")
        checked = entry.get("checked_at")
        grace = entry.get("grace_until")
        holdings[wallet] = Holding(
            wallet=wallet,
            balance_raw=_int(entry.get("balance_raw"), "balance_raw"),
            threshold_tokens=_int(entry.get("threshold_tokens", threshold_tokens), "threshold_tokens"),
            standing=standing,
            checked_at=_number(checked),
            origin=str(entry.get("origin", "snapshot")),
            grace_until=_number(grace),
        )

    return Roster(
        generated_at=float(generated_at),
        generated_day=str(raw.get("generated_day", "")),
        mint=mint,
        decimals=decimals,
        threshold_tokens=threshold_tokens,
        source=str(raw.get("source", "")),
        sweep_day=str(sweep["last_day"]) if isinstance(sweep.get("last_day"), str) else None,
        sweep_status=str(sweep.get("status", "unknown")),
        holdings=holdings,
    )


def load(path: Path) -> Roster:
    """Read and validate. A missing OR corrupt roster raises — the caller fails closed."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise RosterError(f"no holder roster has landed at {path}") from None
    try:
        return parse(json.loads(text))
    except json.JSONDecodeError:
        raise RosterError("holder roster is not valid JSON") from None


@dataclass(frozen=True, slots=True)
class Standing:
    """What the portal will tell a signed-in wallet, and whether it opens the door."""

    entitled: bool
    standing: str
    held_raw: int
    required_raw: int
    gap_raw: int
    checked_at: float | None
    grace_until: float | None
    origin: str
    known: bool


def decide(roster: Roster, wallet: str) -> Standing:
    """Entitlement for one wallet. Recomputed on EVERY request; never cached in a token."""

    holding = roster.lookup(wallet)
    if holding is None:
        # Absence in the roster is not "zero $DREGG" — it is "this wallet was not in the
        # last snapshot". The copy that renders this says so with the roster's own stamp
        # rather than reporting a balance nobody measured.
        required = threshold_raw(roster.threshold_tokens, roster.decimals)
        return Standing(
            entitled=False,
            standing="unknown",
            held_raw=0,
            required_raw=required,
            gap_raw=required,
            checked_at=None,
            grace_until=None,
            origin="absent",
            known=False,
        )
    required = threshold_raw(holding.threshold_tokens, roster.decimals)
    return Standing(
        entitled=holding.entitled,
        standing=holding.standing,
        held_raw=holding.balance_raw,
        required_raw=required,
        gap_raw=max(0, required - holding.balance_raw),
        checked_at=holding.checked_at,
        grace_until=holding.grace_until,
        origin=holding.origin,
        known=True,
    )
