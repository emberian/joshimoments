"""Format proof for the static signer page: page-output => bot-accept.

The page (dregg_gate/signer/index.html) base58-encodes the wallet's raw ed25519
signature with an inline encoder. These tests pin the whole format chain:

- a Python port of that exact JS encoder matches solders' canonical base58,
- the ACTUAL JS encoder, extracted from the page and run under node, matches too,
- a signature over the real challenge format, encoded that way, is accepted by
  dregg_gate.verify.signature_matches — the same call the gateway makes,
- the page stays self-contained (no network) and unbranded (nothing gate-shaped).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from solders.keypair import Keypair

from dregg_gate.verify import build_challenge, new_nonce, signature_matches

PAGE = Path(__file__).resolve().parent.parent / "dregg_gate" / "signer" / "index.html"

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode_like_page(data: bytes) -> str:
    """Line-for-line port of the page's inline b58encode (between its b58 markers)."""

    zeros = 0
    while zeros < len(data) and data[zeros] == 0:
        zeros += 1
    digits: list[int] = []
    for byte in data:
        carry = byte
        for i in range(len(digits)):
            carry += digits[i] * 256
            digits[i] = carry % 58
            carry //= 58
        while carry:
            digits.append(carry % 58)
            carry //= 58
    return "1" * zeros + "".join(B58_ALPHABET[d] for d in reversed(digits))


# -- the encoder is the bot's encoder ------------------------------------------------


def test_port_matches_solders_base58_for_real_signatures() -> None:
    for _ in range(8):
        keypair = Keypair()
        signature = keypair.sign_message(b"any bytes at all")
        assert b58encode_like_page(bytes(signature)) == str(signature)


def test_port_edge_cases() -> None:
    assert b58encode_like_page(b"") == ""
    assert b58encode_like_page(b"\x00") == "1"
    assert b58encode_like_page(b"\x00\x00\x00\x01") == "1112"
    # 64 zero bytes is a syntactically valid (if absurd) signature encoding
    assert b58encode_like_page(bytes(64)) == "1" * 64


def test_page_output_format_accepted_by_gate_verify() -> None:
    """The end-to-end format proof: sign the real challenge shape, encode the raw
    64 signature bytes the way the page does, feed it to the gateway's verifier."""

    keypair = Keypair()
    wallet = str(keypair.pubkey())
    challenge = build_challenge(wallet, new_nonce(), 1_756_000_000.0)
    signature = keypair.sign_message(challenge.encode("utf-8"))
    encoded = b58encode_like_page(bytes(signature))

    assert signature_matches(challenge, wallet, encoded)
    # and the acceptance is exact, not lenient:
    assert not signature_matches(challenge + " ", wallet, encoded)
    assert not signature_matches(challenge, str(Keypair().pubkey()), encoded)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_actual_js_encoder_from_page_is_accepted(tmp_path: Path) -> None:
    """No port drift allowed: run the page's own encoder under node."""

    source = PAGE.read_text(encoding="utf-8")
    match = re.search(r"/\* b58:begin \*/(.*?)/\* b58:end \*/", source, re.DOTALL)
    assert match, "b58 markers missing from the page"

    keypair = Keypair()
    wallet = str(keypair.pubkey())
    challenge = build_challenge(wallet, new_nonce(), 1_756_000_000.0)
    signature = keypair.sign_message(challenge.encode("utf-8"))

    script_path = tmp_path / "encoder.js"
    script_path.write_text(
        match.group(1)
        + "\nconst bytes = Uint8Array.from(JSON.parse(process.argv[2]));"
        + "\nprocess.stdout.write(b58encode(bytes));",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(script_path), json.dumps(list(bytes(signature)))],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout == str(signature)
    assert signature_matches(challenge, wallet, result.stdout)


# -- the page keeps its promises -----------------------------------------------------


def test_page_is_self_contained() -> None:
    """"Sends nothing anywhere" is load-bearing copy: no external loads, no
    network APIs, and a CSP that turns the promise into an enforced policy."""

    source = PAGE.read_text(encoding="utf-8")
    assert "<script src" not in source
    assert "<link" not in source  # no external styles, fonts, or icons
    for network_api in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource"):
        assert network_api not in source, f"page must not reference {network_api}"
    assert "connect-src 'none'" in source, "CSP must forbid outbound connections"
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", source))
    allowed = {"https://phantom.com", "https://github.com/emberian/sol-msg-signer"}
    assert urls <= allowed, f"unexpected URLs in page: {urls - allowed}"


def test_page_is_unbranded() -> None:
    lowered = PAGE.read_text(encoding="utf-8").lower()
    for branded in ("dregg", "wire", "shitcoims", "joshi", "telegram", "holder"):
        # word-boundary match: "placeholder" is fine, "holder"/"holders" is not
        assert not re.search(rf"\b{branded}s?\b", lowered), f"page must stay generic; found {branded!r}"
