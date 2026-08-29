"""Lift the wallet crypto out of ``dregg_gate/signer/index.html`` instead of copying it.

The signer page is already proven against the bot's verifier — its base58, its vendored
tweetnacl, and its Phantom/Solflare deeplink envelope are covered by
``tests/test_signer_page.py``, which cross-checks them against solders AND an independent
pynacl. A second hand-written copy of any of that on the portal's sign-in page would be
the mirror this project keeps paying for: green in its own tests, subtly different in the
one byte that matters.

So the page carries marker pairs (``/* nacl:begin */`` … ``/* nacl:end */``) and this
module extracts the bytes BETWEEN them, verbatim. The portal's sign-in page is assembled
from those exact bytes at render time. A test asserts byte-equality and re-checks the
sha256 the page pins for the vendored library, so:

* the crypto cannot drift between the two pages, because there is one copy of it;
* upgrading tweetnacl is one edit in one file, and the pin makes it a deliberate one;
* deleting a marker breaks the build loudly rather than silently shipping a page whose
  wallet buttons do nothing — which is the failure mode that hides in a browser, where
  no server log would ever show it.

What is NOT extracted is the signer's flow: that page's whole claim is ``connect-src
'none'`` — it sends nothing anywhere — and the portal's sign-in page must POST a
signature. Those are different pages with different security policies, and pretending
otherwise would mean loosening the signer's CSP to serve the portal. The crypto is
shared; the promise is not.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

SIGNER_PAGE = Path(__file__).resolve().parent.parent / "dregg_gate" / "signer" / "index.html"

# The pin recorded in the signer page's own comment, repeated here so a swap of the
# vendored library fails in TWO places rather than one.
NACL_SHA256 = "973cc5733cc7432e30ee4682098f413094f494bccf76a567c23908c5035ddbbc"

BLOCKS = ("nacl", "b58", "deeplink-crypto")


class SignerExtractError(RuntimeError):
    pass


def extract(name: str, *, page: Path | None = None) -> str:
    """The exact text between ``/* <name>:begin */`` and ``/* <name>:end */``."""

    source = (page or SIGNER_PAGE).read_text(encoding="utf-8")
    start_marker, end_marker = f"/* {name}:begin */", f"/* {name}:end */"
    start = source.find(start_marker)
    end = source.find(end_marker)
    if start == -1 or end == -1 or end < start:
        raise SignerExtractError(
            f"signer page is missing the {name!r} marker pair — the portal sign-in page "
            "cannot be assembled without it"
        )
    return source[start + len(start_marker) : end].strip("\n")


def wallet_crypto(*, page: Path | None = None) -> str:
    """All three blocks, in dependency order, with the pin verified."""

    parts = {name: extract(name, page=page) for name in BLOCKS}
    digest = sha256(parts["nacl"].encode("utf-8")).hexdigest()
    if digest != NACL_SHA256:
        raise SignerExtractError(
            "the vendored tweetnacl in the signer page does not match its recorded sha256 — "
            "refusing to assemble a sign-in page around crypto nobody has re-pinned"
        )
    return "\n".join(
        (
            "/* extracted verbatim from dregg_gate/signer/index.html by dregg_portal.signerjs.",
            f"   tweetnacl-js 1.0.3, Unlicense; sha256 {NACL_SHA256} re-checked at render time. */",
            parts["nacl"],
            parts["b58"],
            parts["deeplink-crypto"],
        )
    )
