"""Pair with a running joshi-core exactly the way the cockpit does.

This is the transport half of the resident: it is another CLIENT of apps/core's
loopback routes, holding an ordinary pairing session with cockpit-read +
operator-evidence-write scope, and NOTHING ELSE. It never bypasses the store's
admission discipline — every write goes through /api/v1/operator/commands and is
validated by ValidatedOperatorCommandV1::parse_exact on the server.

The one non-obvious thing: core is reached on its real listen port, but the
pairing coordinator binds every request to the configured *browser* origin
(default http://127.0.0.1:4173, the vite dev origin). So we send that as the
Host and Origin headers and forge the same Fetch Metadata a browser would — the
posture check is a same-origin gate, not a secret. This mirrors, byte for byte,
the header set in apps/core/src/live_gesture.rs::{exchange, authorized}.
"""

from __future__ import annotations

import json
import http.client
from urllib.parse import urlsplit


class PairingError(RuntimeError):
    pass


class JoshiCoreSession:
    """A memory-only pairing capability against one loopback joshi-core."""

    def __init__(self, listen: str, origin: str = "http://127.0.0.1:4173"):
        # listen is where the TCP socket actually is; origin is the identity the
        # pairing coordinator was configured with and checks the headers against.
        self._listen = urlsplit(listen if "://" in listen else f"http://{listen}")
        self._origin = origin.rstrip("/")
        self._origin_authority = self._origin.split("://", 1)[1]
        self._capability: str | None = None
        self._descriptor: dict | None = None

    # -- low-level request with forged browser posture -------------------
    def _request(self, method: str, path: str, *, body: bytes | None = None,
                 scope_token: str | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection(self._listen.hostname, self._listen.port, timeout=15)
        headers = {
            "Host": self._origin_authority,      # the configured origin, NOT the socket authority
            "Origin": self._origin,
            "Accept": "application/json",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if scope_token is not None:
            headers["X-Joshi-Pairing-Token"] = scope_token
        try:
            # skip_host so our explicit Host header (the configured origin) is the only one sent.
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders(message_body=body)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    # -- pairing ---------------------------------------------------------
    def pair(self, one_time_code: str) -> dict:
        """Exchange a one-time code for an ordinary session capability."""
        payload = json.dumps({
            "contract": "joshi.pairing.exchange",
            "schemaVersion": 1,
            "oneTimeCode": one_time_code.strip(),
        }).encode()
        status, raw = self._request("POST", "/api/v1/pairing/exchange", body=payload)
        if status != 200:
            raise PairingError(f"pairing exchange refused ({status}): {raw.decode('utf-8', 'replace')}")
        descriptor = json.loads(raw)
        self._capability = descriptor["capability"]
        self._descriptor = descriptor
        return descriptor

    @property
    def paired(self) -> bool:
        return self._capability is not None

    @property
    def scopes(self) -> list[str]:
        return list(self._descriptor.get("scopes", [])) if self._descriptor else []

    # -- cockpit-read ----------------------------------------------------
    def read_scene(self, scene_id: str, mode: str = "witnessed") -> dict:
        """Read one scene snapshot through the paired cockpit-read route."""
        if not self._capability:
            raise PairingError("not paired")
        path = f"/api/v1/glass/snapshot?mode={mode}&basisSceneId={scene_id}"
        status, raw = self._request("GET", path, scope_token=self._capability)
        if status != 200:
            raise PairingError(f"snapshot read failed ({status}): {raw.decode('utf-8', 'replace')}")
        return json.loads(raw)

    # -- operator-evidence-write -----------------------------------------
    def append_command(self, canonical_body: bytes) -> tuple[int, dict]:
        """POST one canonical operator command. Returns (status, receipt-or-problem)."""
        if not self._capability:
            raise PairingError("not paired")
        status, raw = self._request(
            "POST", "/api/v1/operator/commands", body=canonical_body,
            scope_token=self._capability)
        return status, json.loads(raw) if raw else {}
