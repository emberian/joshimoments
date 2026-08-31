"""Session tokens: a signed claim of WALLET OWNERSHIP, and nothing else.

THE DESIGN DECISION WORTH READING. The cookie does not carry a seat, a standing, or a
balance. It carries one fact — "this browser proved it controls wallet W at time T" —
and every request re-derives entitlement from the roster. That is why:

* a seat lost overnight is gone on the reader's NEXT PAGE, not when a token expires. The
  alternative (bake the standing into the token) would have invented a revocation
  problem the bot does not have, and then solved it badly with a short TTL.
* the token's TTL bounds only how long a STOLEN cookie is useful, so it can be chosen for
  that alone (12h) instead of being a compromise between staleness and re-login friction.
* a roster push and a session are independent. Neither can lie about the other.

The key lives at ``[paths] session_key`` on the anchor, mode 0600, GENERATED THERE by
``deploy-portal.sh --keygen`` and never transmitted in either direction — the same
posture ``edge/relay`` uses for its attestation key. Rotating it signs everyone out and
costs each of them one click; that is the intended cost of rotation, not a bug.

The cookie is ``__Host-`` prefixed. dregg.studio has siblings (portal.dregg.studio), and
``__Host-`` is the only cookie form a sibling name cannot shadow with a Domain= cookie.
It forces Path=/, so the cookie also rides the static pages on this name; those are
served by Caddy's file_server, which ignores it. Path=/portal would be tighter by one
irrelevant inch and would give up the guarantee that matters.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import stat
from hashlib import sha256
from pathlib import Path

COOKIE_NAME = "__Host-dregg_portal"
TOKEN_VERSION = "v1"
# Domain separation for the MAC, so a session key can never be made to validate bytes
# minted for some other purpose if this key is ever reused by a later feature.
MAC_CONTEXT = b"dregg-portal-session-v1|"
KEY_BYTES = 32


class SessionKeyError(RuntimeError):
    pass


def generate_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


def read_key(path: Path) -> bytes:
    """Load the session key, refusing anything a second account could have read.

    Same private-file hygiene as ``dregg_gate.config.read_secret``: a symlink, a foreign
    owner, or any group/world bit is a refusal, not a warning. A key another account
    could read is not a key.
    """

    try:
        metadata = path.lstat()
    except OSError:
        raise SessionKeyError(f"session key is unavailable at {path}") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SessionKeyError("session key path must be a regular file, not a symlink")
    if metadata.st_uid != os.getuid():
        raise SessionKeyError("session key file must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SessionKeyError("session key file permissions must be 0600 or stricter")
    try:
        raw = path.read_bytes().strip()
    except OSError:
        raise SessionKeyError("session key file could not be read") from None
    try:
        key = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
    except (ValueError, TypeError):
        raise SessionKeyError("session key file is not urlsafe base64") from None
    if len(key) < KEY_BYTES:
        raise SessionKeyError(f"session key must be at least {KEY_BYTES} bytes")
    return key


def write_key(path: Path, key: bytes) -> None:
    """Create the key file 0600 and EXCLUSIVELY — never silently replacing an existing one."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(base64.urlsafe_b64encode(key).rstrip(b"="))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii") + b"=" * (-len(text) % 4))


def mint(key: bytes, wallet: str, *, now: float, ttl_seconds: int) -> str:
    payload = json.dumps(
        {"w": wallet, "iat": int(now), "exp": int(now) + int(ttl_seconds)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    body = _b64(payload)
    mac = hmac.new(key, MAC_CONTEXT + body.encode("ascii"), sha256).digest()
    return f"{TOKEN_VERSION}.{body}.{_b64(mac)}"


def read(key: bytes, token: object, *, now: float) -> str | None:
    """The proven wallet, or None. Every failure is the same None: no oracle for why."""

    if not isinstance(token, str) or len(token) > 1024:
        return None
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        return None
    _, body, signature = parts
    expected = hmac.new(key, MAC_CONTEXT + body.encode("ascii"), sha256).digest()
    try:
        given = _unb64(signature)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, given):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict):
        return None
    wallet, expires = claims.get("w"), claims.get("exp")
    if not isinstance(wallet, str) or not wallet:
        return None
    if isinstance(expires, bool) or not isinstance(expires, int) or now >= expires:
        return None
    return wallet


def set_cookie(token: str, *, ttl_seconds: int) -> str:
    return (
        f"{COOKIE_NAME}={token}; Path=/; Max-Age={int(ttl_seconds)}; "
        "Secure; HttpOnly; SameSite=Lax"
    )


def clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"


def from_cookie_header(header: object) -> str | None:
    """Pull our cookie out of a Cookie: line without trusting its shape."""

    if not isinstance(header, str) or len(header) > 8192:
        return None
    for chunk in header.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name == COOKIE_NAME:
            return value.strip()
    return None
