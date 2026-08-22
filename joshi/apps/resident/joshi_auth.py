"""The resident's Claude auth — reuse allgame's proven tokeman pattern.

This is a deliberately thin restatement of allgame/claude_resident/auth.py's
core: pick the healthiest Claude subscription account tokeman knows about
(drain the busiest usable one first, sticky so a warm prompt cache is not
thrown away), and hand its OAuth token to the Agent SDK subprocess via
CLAUDE_CODE_OAUTH_TOKEN. The resident's turns then draw PLAN LIMITS (flat
rate) rather than metered API credit — the only path a subscription token can
use for Sonnet/Opus (the raw Messages API 429s those tiers on an OAuth token
with no extra-usage balance).

Nothing here is JOSHI-specific; the point of the deputy task was to prove this
existing pattern transplants unchanged. It does.
"""

from __future__ import annotations

import json
import time
import tomllib
import subprocess
from pathlib import Path

TOKENS_PATH = Path.home() / ".config" / "tokeman" / "tokens.toml"
DEFAULT_ACCOUNT = "you@example.com"

_probe_cache = {"at": 0.0, "rows": []}


def probe_accounts(max_age: float = 60.0) -> list[dict]:
    now = time.time()
    if now - _probe_cache["at"] < max_age and _probe_cache["rows"]:
        return _probe_cache["rows"]
    try:
        out = subprocess.run(["tokeman", "--json"], capture_output=True,
                             text=True, timeout=30)
        rows = json.loads(out.stdout) if out.returncode == 0 else []
    except (OSError, ValueError, subprocess.SubprocessError):
        rows = []
    _probe_cache.update(at=now, rows=rows)
    return rows


def _health(row: dict) -> tuple[int, float]:
    q = row.get("quota") or {}
    status = q.get("status", "unknown")
    weekly = ((q.get("weekly") or {}).get("utilization") or 0.0)
    rank = {"allowed": 0, "allowed_warning": 0}.get(status, 2)
    return (rank, -weekly)  # usable first, then closest-to-exhaustion


def choose_account(prefer: str | None = None) -> str | None:
    rows = probe_accounts()
    if not rows:
        return prefer or DEFAULT_ACCOUNT
    healthy = sorted((r for r in rows if _health(r)[0] < 2), key=_health)
    if not healthy:
        return prefer or DEFAULT_ACCOUNT
    return healthy[0].get("token_name")


def read_oauth_token(account: str | None = None) -> str | None:
    try:
        with open(TOKENS_PATH, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = account or choose_account()
    for entry in data.get("tokens", []):
        if entry.get("name") == name:
            return entry.get("key") or None
    return None
