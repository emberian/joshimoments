"""Re-measure the catalogue against the live hosts, and report where it has drifted.

This is the falsifier for `endpoints.py`. The catalogue records a verdict per route with a
date on it; this module goes and checks, and its output distinguishes the four states that
matter — live, dead, auth-walled, and CHANGED (the catalogue says one thing, production
says another). A drifted route is the interesting output: it is how "we suddenly have no
comments" gets diagnosed in one command instead of one afternoon.

Mutating routes are never probed. They are reported as `refused` — the client will not
dispatch them, so the prober cannot either, and that is the intended answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import NotFound, PumpSocialClient, PumpSocialError
from .crawl import OUT
from .endpoints import ENDPOINTS, Endpoint

#: Known-good values to fill path templates. These are deliberately public, long-lived
#: entities: DREGG is the operator's own coin and jackduvalcalls is the caller the
#: operator actually follows, so a probe failure is legible rather than ambiguous.
FIXTURES: dict[str, str] = {
    "mint": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",       # DREGG
    "address": "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",   # jackduvalcalls
    "key": "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh",
    "user_id": "cef4bed6-680b-491c-8089-1f3c6bfe763b",           # jackduvalcalls
    "twitter_id": "1592708747943497728",                         # jackduvalcalls on X
    "message_id": "dfcb8321-3f2b-4775-8b3b-ea359ea320e0",        # a real DREGG comment
    "callout_id": "a0ff5a87-927c-4669-bc75-a24537eebc73",        # a real DREGG callout
}

#: Bodies for the two POST-shaped reads.
BODIES: dict[str, dict[str, Any]] = {
    "users_by_wallet_batch": {"addresses": [FIXTURES["address"]]},
    "communities_batch": {"tokenAddresses": [FIXTURES["mint"]]},
}

#: Query defaults, so listing routes are asked a small question.
QUERIES: dict[str, dict[str, Any]] = {
    "user_search": {"searchTerm": "jackduvalcalls"},
    "coins_search_v3": {"searchTerm": "dregg", "limit": 1},
}


def _params_for(spec: Endpoint) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in FIXTURES.items():
        if "{" + name + "}" in spec.path:
            out[name] = value
    return out


def _shape(body: Any, *, depth: int = 0) -> Any:
    """A body's SHAPE, not its content — what fields exist, not what they say today.

    Recorded instead of a sample because the thing worth diffing across probes is the
    schema. A field silently disappearing is the drift that breaks a parser, and it is
    invisible in a response-code check.
    """

    if depth > 2:
        return "..."
    if isinstance(body, dict):
        return {k: _shape(v, depth=depth + 1) for k, v in sorted(body.items())}
    if isinstance(body, list):
        return [_shape(body[0], depth=depth + 1)] if body else []
    return type(body).__name__


def probe_one(client: PumpSocialClient, spec: Endpoint) -> dict[str, Any]:
    if spec.mutating:
        return {
            "name": spec.name,
            "host": spec.host,
            "path": spec.path,
            "catalogued": spec.verdict,
            "measured": "refused",
            "drift": False,
            "note": "mutating; the client refuses to dispatch it and so does the prober",
        }
    row: dict[str, Any] = {
        "name": spec.name,
        "host": spec.host,
        "path": spec.path,
        "auth": spec.auth,
        "catalogued": spec.verdict,
    }
    try:
        body, prov = client.request(
            spec.name,
            path_params=_params_for(spec),
            query=QUERIES.get(spec.name),
            body=BODIES.get(spec.name),
        )
        row["measured"] = "live"
        row["shape"] = _shape(body)
        row["empty"] = body in ([], {}, None)
        row["t_source_computed"] = prov.t_source_computed
    except NotFound:
        row["measured"] = "dead"
    except PumpSocialError as exc:
        row["measured"] = "auth_walled" if exc.status in (401, 403) else "error"
        row["detail"] = str(exc)[:200]
    row["drift"] = row["measured"] != spec.verdict
    return row


def probe_all(client: PumpSocialClient | None = None, *, out_dir: Path = OUT) -> dict[str, Any]:
    client = client or PumpSocialClient()
    started = datetime.now(UTC).isoformat()
    rows = [probe_one(client, spec) for spec in ENDPOINTS]
    drifted = [r for r in rows if r.get("drift")]
    summary = {
        "t_probe": started,
        "t_end": datetime.now(UTC).isoformat(),
        "endpoints": len(rows),
        "live": sum(1 for r in rows if r["measured"] == "live"),
        "dead": sum(1 for r in rows if r["measured"] == "dead"),
        "auth_walled": sum(1 for r in rows if r["measured"] == "auth_walled"),
        "refused_mutating": sum(1 for r in rows if r["measured"] == "refused"),
        "errors": sum(1 for r in rows if r["measured"] == "error"),
        "drifted": [r["name"] for r in drifted],
        "requests": client.stats.requests,
        "stats": client.stats.line(),
        "results": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "surface.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary
