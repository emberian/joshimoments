"""Challenge construction and ed25519 signature verification (solders, no new crypto)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from solders.pubkey import Pubkey
from solders.signature import Signature

CHALLENGE_TEMPLATE = (
    "dregg wire wants proof you hold {wallet}\n"
    "nonce: {nonce}\n"
    "issued: {issued}\n"
    "expires: 10min"
)


def new_nonce() -> str:
    """16 random bytes, hex — single-use, enforced by the challenges table."""

    return secrets.token_hex(16)


def build_challenge(wallet: str, nonce: str, issued_at: float) -> str:
    issued = datetime.fromtimestamp(issued_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return CHALLENGE_TEMPLATE.format(wallet=wallet, nonce=nonce, issued=issued)


def parse_pubkey(text: str) -> Pubkey | None:
    try:
        return Pubkey.from_string(text)
    except Exception:
        return None


def parse_signature(text: str) -> Signature | None:
    """Lenient about paste artifacts (quotes, backticks, whitespace), strict about bytes."""

    cleaned = text.strip().strip("`\"'")
    if not cleaned or any(character.isspace() for character in cleaned):
        return None
    try:
        return Signature.from_string(cleaned)
    except Exception:
        return None


def signature_matches(message: str, wallet: str, signature_b58: str) -> bool:
    """True only when this exact challenge text was signed by this exact wallet key."""

    pubkey = parse_pubkey(wallet)
    signature = parse_signature(signature_b58)
    if pubkey is None or signature is None:
        return False
    try:
        return bool(signature.verify(pubkey, message.encode("utf-8")))
    except Exception:
        return False
