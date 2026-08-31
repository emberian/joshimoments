"""The portal's sign-in challenge: the bot's ceremony, domain-separated for the web.

``dregg_gate.verify`` stays the ONE ed25519 implementation in this tree — the portal
imports ``signature_matches`` rather than reaching for a second library, so the web and
the group can never disagree about what a valid signature is.

Only the TEXT differs, and deliberately:

* line 1 names the surface, so a person reading their wallet's confirmation screen can
  tell a portal sign-in from a bot verification. Replay across the two was already
  impossible (each side only accepts nonces from its own table), but a signed message a
  human cannot place is a phishing lesson taught by us.
* the last line says, IN THE BYTES THE WALLET DISPLAYS, that this is not a transaction.
  A promise on the page is a promise; a promise inside the signed text is shown by the
  wallet itself, next to the approve button, where the doubt actually is.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dregg_gate.verify import new_nonce, parse_pubkey, parse_signature, signature_matches

CHALLENGE_TEMPLATE = (
    "shitcoims wire portal sign-in\n"
    "wallet: {wallet}\n"
    "nonce: {nonce}\n"
    "issued: {issued}\n"
    "expires: 10min\n"
    "this is a message signature, not a transaction. it moves nothing."
)

__all__ = [
    "CHALLENGE_TEMPLATE",
    "build_challenge",
    "new_nonce",
    "parse_signature",
    "signature_matches",
    "valid_wallet",
]


def build_challenge(wallet: str, nonce: str, issued_at: float) -> str:
    issued = datetime.fromtimestamp(issued_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return CHALLENGE_TEMPLATE.format(wallet=wallet, nonce=nonce, issued=issued)


def valid_wallet(text: object) -> str | None:
    """A base58 ed25519 pubkey, normalized, or None. Parsed by solders, never by a regex.

    Returned as the CANONICAL string solders round-trips, so the same key can never enter
    the roster under two spellings.
    """

    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 64:
        return None
    pubkey = parse_pubkey(cleaned)
    return str(pubkey) if pubkey is not None else None
