"""Format proof for the static signer page: page-output => bot-accept.

The page (dregg_gate/signer/index.html) has two signing paths and both must
produce a base58 ed25519 signature the gateway accepts:

- LEGACY/INJECTED: the wallet hands the page raw signature bytes and the page
  base58-encodes them with an inline encoder.
- DEEPLINK (Phantom/Solflare universal links, the Telegram-mobile path): the
  page mints an x25519 keypair, the wallet replies with nacl.box ciphertext,
  and the page decrypts it to get the base58 signature the wallet produced.

These tests pin the whole chain:

- a Python port of the page's exact b58 encoder/decoder matches solders' base58,
- the ACTUAL JS, extracted from the page and run under node, matches too,
- a signature over the real challenge format, encoded that way, is accepted by
  dregg_gate.verify.signature_matches — the same call the gateway makes,
- the deeplink payload crypto round-trips against PyNaCl (an independent
  nacl implementation) in both directions, running the page's own inlined
  tweetnacl + helper code under node,
- the vendored tweetnacl is byte-pinned by sha256, so no silent drift,
- the page stays fetch-free (no fetch/XHR/WebSocket — navigation to the wallet
  apps is the only egress) and keeps its anti-phishing copy prominent.
"""

from __future__ import annotations

import hashlib
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

# sha256 of the exact vendored tweetnacl-js 1.0.3 nacl.min.js bytes between the
# page's nacl:begin/nacl:end marker lines. Fetched 2026-08-29 from cdnjs AND
# unpkg independently; both matched this digest.
TWEETNACL_SHA256 = "973cc5733cc7432e30ee4682098f413094f494bccf76a567c23908c5035ddbbc"


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


def b58decode_like_page(text: str) -> bytes | None:
    """Line-for-line port of the page's inline b58decode (same markers)."""

    zeros = 0
    while zeros < len(text) and text[zeros] == "1":
        zeros += 1
    digits: list[int] = []
    for character in text:
        value = B58_ALPHABET.find(character)
        if value == -1:
            return None
        carry = value
        for i in range(len(digits)):
            carry += digits[i] * 58
            digits[i] = carry & 0xFF
            carry >>= 8
        while carry:
            digits.append(carry & 0xFF)
            carry >>= 8
    return bytes(zeros) + bytes(reversed(digits))


def _page_section(source: str, name: str) -> str:
    match = re.search(rf"/\* {name}:begin \*/(.*?)/\* {name}:end \*/", source, re.DOTALL)
    assert match, f"{name} markers missing from the page"
    return match.group(1)


def _run_node(script_path: Path, *argv: str) -> str:
    result = subprocess.run(
        ["node", str(script_path), *argv],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


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


def test_decode_port_inverts_encode_and_matches_solders() -> None:
    for _ in range(8):
        keypair = Keypair()
        signature = keypair.sign_message(b"round trip me")
        assert b58decode_like_page(str(signature)) == bytes(signature)
        pubkey_text = str(keypair.pubkey())
        decoded = b58decode_like_page(pubkey_text)
        assert decoded is not None and len(decoded) == 32
        assert b58encode_like_page(decoded) == pubkey_text


def test_decode_port_edge_cases() -> None:
    assert b58decode_like_page("") == b""
    assert b58decode_like_page("1") == b"\x00"
    assert b58decode_like_page("1112") == b"\x00\x00\x00\x01"
    assert b58decode_like_page("0") is None  # 0, I, O, l are not in the alphabet
    assert b58decode_like_page("abcO") is None
    assert b58decode_like_page("a b") is None


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
    section = _page_section(source, "b58")

    keypair = Keypair()
    wallet = str(keypair.pubkey())
    challenge = build_challenge(wallet, new_nonce(), 1_756_000_000.0)
    signature = keypair.sign_message(challenge.encode("utf-8"))

    script_path = tmp_path / "encoder.js"
    script_path.write_text(
        section
        + "\nconst bytes = Uint8Array.from(JSON.parse(process.argv[2]));"
        + "\nprocess.stdout.write(b58encode(bytes));",
        encoding="utf-8",
    )
    stdout = _run_node(script_path, json.dumps(list(bytes(signature))))
    assert stdout == str(signature)
    assert signature_matches(challenge, wallet, stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_actual_js_decoder_from_page_matches(tmp_path: Path) -> None:
    """The decoder feeds the deeplink crypto; it gets the same no-drift treatment."""

    source = PAGE.read_text(encoding="utf-8")
    section = _page_section(source, "b58")

    keypair = Keypair()
    signature = keypair.sign_message(b"decode me")

    script_path = tmp_path / "decoder.js"
    script_path.write_text(
        section
        + "\nconst decoded = b58decode(process.argv[2]);"
        + "\nprocess.stdout.write(JSON.stringify(decoded ? Array.from(decoded) : null));",
        encoding="utf-8",
    )
    assert json.loads(_run_node(script_path, str(signature))) == list(bytes(signature))
    assert json.loads(_run_node(script_path, "abcO")) is None  # invalid alphabet char


# -- the deeplink payload crypto is real nacl.box ------------------------------------
#
# Protocol (verified 2026-08-29 against the vendor docs cited in the page head):
# the page mints an x25519 keypair, the wallet replies with its own public key,
# both derive the same XSalsa20-Poly1305 key via nacl.box, and every payload is
# box ciphertext with a fresh 24-byte nonce, all base58 on the wire.


def _deeplink_harness(tmp_path: Path) -> Path:
    """The page's OWN inlined crypto — vendored tweetnacl + b58 + deeplink helpers —
    assembled into a node module. .mjs so the tweetnacl UMD takes its browser branch
    (self.nacl), exactly as it does on the page."""

    source = PAGE.read_text(encoding="utf-8")
    script = "\n".join(
        [
            "globalThis.self = globalThis;",
            _page_section(source, "nacl"),
            _page_section(source, "b58"),
            _page_section(source, "deeplink-crypto"),
            "const [mode, peerPubB58, dappSecretB58, third, nonceB58] = process.argv.slice(2);",
            "const shared = dlSharedSecret(peerPubB58, b58decode(dappSecretB58));",
            "if (mode === 'decrypt') {",
            "  process.stdout.write(JSON.stringify(dlDecryptPayload(third, nonceB58, shared)));",
            "} else if (mode === 'encrypt') {",
            "  const sealed = dlEncryptPayload(JSON.parse(third), shared, b58decode(nonceB58));",
            "  process.stdout.write(JSON.stringify(sealed));",
            "} else { throw new Error('bad mode'); }",
        ]
    )
    script_path = tmp_path / "deeplink.mjs"
    script_path.write_text(script, encoding="utf-8")
    return script_path


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_deeplink_decrypt_path_against_pynacl(tmp_path: Path) -> None:
    """PyNaCl plays the wallet: encrypt a connect-style reply, the page's own JS
    must decrypt it. Two independent nacl implementations agreeing is the proof."""

    public = pytest.importorskip("nacl.public", reason="pynacl not installed")

    dapp_secret = bytes(range(32))  # fixed vector: any 32 bytes are a valid x25519 scalar
    wallet_secret = bytes(range(1, 33))
    dapp_key = public.PrivateKey(dapp_secret)
    wallet_key = public.PrivateKey(wallet_secret)
    nonce = bytes(range(100, 124))

    reply = {"public_key": str(Keypair().pubkey()), "session": "opaque-session-token"}
    box = public.Box(wallet_key, dapp_key.public_key)
    ciphertext = box.encrypt(json.dumps(reply).encode("utf-8"), nonce).ciphertext

    stdout = _run_node(
        _deeplink_harness(tmp_path),
        "decrypt",
        b58encode_like_page(bytes(wallet_key.public_key)),
        b58encode_like_page(dapp_secret),
        b58encode_like_page(ciphertext),
        b58encode_like_page(nonce),
    )
    assert json.loads(stdout) == reply

    # a tampered ciphertext must decrypt to nothing, not to garbage
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    stdout = _run_node(
        _deeplink_harness(tmp_path),
        "decrypt",
        b58encode_like_page(bytes(wallet_key.public_key)),
        b58encode_like_page(dapp_secret),
        b58encode_like_page(tampered),
        b58encode_like_page(nonce),
    )
    assert json.loads(stdout) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_deeplink_encrypt_path_against_pynacl(tmp_path: Path) -> None:
    """The page's JS encrypts the signMessage payload; PyNaCl (as the wallet) must
    decrypt it, and the inner message must be the exact challenge bytes."""

    public = pytest.importorskip("nacl.public", reason="pynacl not installed")

    dapp_secret = bytes(range(32))
    wallet_secret = bytes(range(1, 33))
    dapp_key = public.PrivateKey(dapp_secret)
    wallet_key = public.PrivateKey(wallet_secret)
    nonce = bytes(range(200, 224))

    challenge = build_challenge(str(Keypair().pubkey()), new_nonce(), 1_756_000_000.0)
    payload = {
        "message": b58encode_like_page(challenge.encode("utf-8")),
        "session": "opaque-session-token",
        "display": "utf8",
    }

    stdout = _run_node(
        _deeplink_harness(tmp_path),
        "encrypt",
        b58encode_like_page(bytes(wallet_key.public_key)),
        b58encode_like_page(dapp_secret),
        json.dumps(payload),
        b58encode_like_page(nonce),
    )
    sealed = json.loads(stdout)
    assert sealed is not None, "page-side encryption returned null"
    assert b58decode_like_page(sealed["nonce"]) == nonce

    box = public.Box(wallet_key, dapp_key.public_key)
    ciphertext = b58decode_like_page(sealed["payload"])
    assert ciphertext is not None
    opened = json.loads(box.decrypt(ciphertext, nonce).decode("utf-8"))
    assert opened == payload
    assert b58decode_like_page(opened["message"]) == challenge.encode("utf-8")


# -- the page's own return-leg handler, driven end-to-end under node -----------------
#
# PyNaCl plays the wallet. The page's REAL main script runs against a stub DOM that
# only answers for element ids actually present in the HTML, so a renamed id or a
# broken handler fails here instead of on a phone inside a Telegram webview.

STORE_KEY = "shitcoims-signer-deeplink-v1"


def _dom_harness(source: str, *, search: str, seeded_state: str | None) -> str:
    ids = sorted(set(re.findall(r'id="([A-Za-z0-9_-]+)"', source)))
    scripts = re.findall(r"<script>(.*?)</script>", source, re.DOTALL)
    assert len(scripts) == 2
    lines = [
        "globalThis.self = globalThis;",
        _page_section(source, "nacl"),
        "const PAGE_IDS = new Set(" + json.dumps(ids) + ");",
        "function makeEl(id) { return { id, style: {}, value: '', textContent: '',",
        "  className: '', disabled: false, addEventListener() {}, appendChild() {},",
        "  setAttribute() {}, focus() {}, select() {}, setSelectionRange() {},",
        "  scrollIntoView() {} }; }",
        "const els = new Map();",
        "globalThis.window = globalThis;",
        "globalThis.document = {",
        "  readyState: 'complete',",
        "  getElementById(id) {",
        "    if (!PAGE_IDS.has(id)) throw new Error('page references missing element id: ' + id);",
        "    if (!els.has(id)) els.set(id, makeEl(id));",
        "    return els.get(id);",
        "  },",
        "  addEventListener() {},",
        "  createElement: () => makeEl('dynamic'),",
        "  body: { appendChild() {}, removeChild() {} },",
        "};",
        "globalThis.location = { search: " + json.dumps(search)
        + ", hash: '', pathname: '/sign', href: '' };",
        "globalThis.history = { replaceState() {} };",
        "const storage = new Map();",
        "Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {",
        "  getItem: (k) => (storage.has(k) ? storage.get(k) : null),",
        "  setItem: (k, v) => storage.set(k, String(v)),",
        "  removeItem: (k) => storage.delete(k),",
        "} });",
        "globalThis.setInterval = (fn) => { for (let i = 0; i < 12; i++) fn(); return 0; };",
        "globalThis.clearInterval = () => {};",
    ]
    if seeded_state is not None:
        lines.append(
            "localStorage.setItem(" + json.dumps(STORE_KEY) + ", JSON.stringify("
            "Object.assign(" + seeded_state + ", { t: Date.now() })));"
        )
    lines += [
        scripts[1],
        "process.stdout.write(JSON.stringify({",
        "  dlstatus: document.getElementById('dlstatus').textContent,",
        "  dlstatusClass: document.getElementById('dlstatus').className,",
        "  dlwallet: document.getElementById('dlwallet').textContent,",
        "  step2: document.getElementById('dlstep2').style.display,",
        "  sig: document.getElementById('sig').textContent,",
        "  msg: document.getElementById('msg').value,",
        "  stored: localStorage.getItem(" + json.dumps(STORE_KEY) + "),",
        "}));",
    ]
    return "\n".join(lines)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_boot_runs_clean_with_no_wallet_and_no_params(tmp_path: Path) -> None:
    source = PAGE.read_text(encoding="utf-8")
    script_path = tmp_path / "boot.mjs"
    script_path.write_text(_dom_harness(source, search="", seeded_state=None), encoding="utf-8")
    out = json.loads(_run_node(script_path))
    assert out["dlstatus"] == ""
    assert out["stored"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_deeplink_connect_and_sign_returns_flow_through_page(tmp_path: Path) -> None:
    """Both redirect legs, through the page's real handler: the connect reply
    advances the state machine, the sign reply surfaces a signature the gateway
    verifier accepts. PyNaCl encrypts exactly as the documented wallets do."""

    public = pytest.importorskip("nacl.public", reason="pynacl not installed")
    source = PAGE.read_text(encoding="utf-8")

    dapp_secret = bytes(range(32))
    dapp_key = public.PrivateKey(dapp_secret)
    wallet_box_key = public.PrivateKey(bytes(range(1, 33)))  # the wallet's x25519 side
    box = public.Box(wallet_box_key, dapp_key.public_key)
    identity = Keypair()  # the wallet's ed25519 signing identity
    wallet = str(identity.pubkey())
    challenge = build_challenge(wallet, new_nonce(), 1_756_000_000.0)

    # ---- leg 1: the connect reply ----
    nonce1 = bytes(range(50, 74))
    connect_reply = json.dumps({"public_key": wallet, "session": "sess-token"}).encode("utf-8")
    search1 = (
        "?phantom_encryption_public_key=" + b58encode_like_page(bytes(wallet_box_key.public_key))
        + "&nonce=" + b58encode_like_page(nonce1)
        + "&data=" + b58encode_like_page(box.encrypt(connect_reply, nonce1).ciphertext)
    )
    state1 = json.dumps(
        {
            "v": 1,
            "provider": "phantom",
            "awaiting": "connect",
            "sk": b58encode_like_page(dapp_secret),
            "pk": b58encode_like_page(bytes(dapp_key.public_key)),
            "message": challenge,
        }
    )
    script_path = tmp_path / "leg1.mjs"
    script_path.write_text(_dom_harness(source, search=search1, seeded_state=state1), encoding="utf-8")
    out1 = json.loads(_run_node(script_path))
    assert out1["dlwallet"] == wallet
    assert out1["step2"] == "block"
    assert out1["msg"] == challenge, "the challenge must survive the redirect round-trip"
    stored = json.loads(out1["stored"])
    assert stored["awaiting"] == "sign"
    assert stored["session"] == "sess-token"
    assert stored["wallet"] == wallet

    # ---- leg 2: the sign reply, seeded with exactly what leg 1 stored ----
    signature = identity.sign_message(challenge.encode("utf-8"))
    nonce2 = bytes(range(150, 174))
    sign_reply = json.dumps({"signature": str(signature)}).encode("utf-8")
    search2 = (
        "?nonce=" + b58encode_like_page(nonce2)
        + "&data=" + b58encode_like_page(box.encrypt(sign_reply, nonce2).ciphertext)
    )
    script_path = tmp_path / "leg2.mjs"
    script_path.write_text(
        _dom_harness(source, search=search2, seeded_state=out1["stored"]), encoding="utf-8"
    )
    out2 = json.loads(_run_node(script_path))
    assert out2["sig"] == str(signature)
    assert out2["stored"] is None, "the x25519 secret must be cleared once signing is done"
    # and the page-displayed signature is exactly what the gateway accepts:
    assert signature_matches(challenge, wallet, out2["sig"])


def test_vendored_tweetnacl_is_byte_pinned() -> None:
    """The inlined crypto lib must be the exact audited bytes, forever."""

    source = PAGE.read_text(encoding="utf-8")
    begin = "/* nacl:begin */\n"
    end = "\n/* nacl:end */"
    start = source.index(begin) + len(begin)
    stop = source.index(end, start)
    blob = source[start:stop].encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == TWEETNACL_SHA256
    assert "tweetnacl-js 1.0.3" in source, "the vendored version must be named next to the pin"
    assert TWEETNACL_SHA256 in source, "the page must carry its own pin for auditors"


# -- the deeplink protocol constants match the documented APIs -----------------------


def test_deeplink_protocol_surface_is_pinned() -> None:
    """Source-level pins against silent drift from the documented Phantom/Solflare
    universal-link protocol (citations live in the page's head comment)."""

    source = PAGE.read_text(encoding="utf-8")
    assert '"https://phantom.app/ul/v1/"' in source
    assert '"https://solflare.com/ul/v1/"' in source
    # the redirect must land back on the deployed page, and stay configurable
    assert 'PAGE_URL = "https://shitcoims.dregg.studio/sign"' in source
    for param in (
        "app_url",
        "dapp_encryption_public_key",
        "redirect_link",
        "cluster",
        "payload",
        "phantom_encryption_public_key",
        "solflare_encryption_public_key",
        "errorCode",
        "errorMessage",
    ):
        assert param in source, f"documented deeplink parameter {param} missing"
    # signMessage payload fields, per both vendors' docs
    assert '"utf8"' in source and "session:" in source and "message:" in source
    # the round trip must survive the redirect (new tab, even) — localStorage, not session
    assert "localStorage.setItem" in source
    assert "sessionStorage." not in source  # per-tab storage would strand the return hop


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_main_script_parses(tmp_path: Path) -> None:
    """Whole-script syntax gate: a typo anywhere in the page JS fails here, not on
    a phone in a Telegram webview."""

    source = PAGE.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", source, re.DOTALL)
    assert len(scripts) == 2, "page should have exactly two inline scripts (lib + main)"
    script_path = tmp_path / "main.js"
    script_path.write_text(scripts[1], encoding="utf-8")
    subprocess.run(["node", "--check", str(script_path)], check=True, timeout=30)


# -- the page keeps its promises -----------------------------------------------------


def test_page_is_self_contained() -> None:
    """No fetch targets, no remote scripts: the only egress is the user navigating
    to their wallet app and back. The CSP keeps connect-src 'none' — navigation is
    not a connection, so the promise stays enforced."""

    source = PAGE.read_text(encoding="utf-8")
    assert "<script src" not in source
    assert "<link" not in source  # no external styles, fonts, or icons
    for network_api in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource"):
        assert network_api not in source, f"page must not reference {network_api}"
    assert "connect-src 'none'" in source, "CSP must forbid outbound connections"
    assert "form-action 'none'" in source, "nothing here submits forms"
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", source))
    allowed = {
        # the install link
        "https://phantom.com",
        # the deeplink endpoints (navigation, not fetch)
        "https://phantom.app/ul/v1/",
        "https://solflare.com/ul/v1/",
        # where the wallet sends the user back
        "https://shitcoims.dregg.studio",
        "https://shitcoims.dregg.studio/sign",
        # protocol citations in the head comment
        "https://docs.phantom.com/phantom-deeplinks/provider-methods/connect",
        "https://docs.phantom.com/phantom-deeplinks/provider-methods/signmessage",
        "https://docs.phantom.com/phantom-deeplinks/encryption",
        "https://docs.solflare.com/solflare/technical/deeplinks/provider-methods/connect",
        "https://docs.solflare.com/solflare/technical/deeplinks/provider-methods/signmessage",
    }
    assert urls <= allowed, f"unexpected URLs in page: {urls - allowed}"


def test_page_keeps_anti_phishing_copy() -> None:
    """The load-bearing reassurances: what signing here can and cannot do."""

    source = PAGE.read_text(encoding="utf-8")
    assert "never a transaction" in source
    assert "no network requests" in source
    assert "seed phrase" in source, "must warn that nothing legitimate asks for one"
    assert "in-app" in source or "built-in browser" in source, "mobile in-wallet-browser note"
    assert "paste it to the bot" in source, "the user must be told the last step"
