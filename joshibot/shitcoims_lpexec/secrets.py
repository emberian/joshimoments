"""Read a secret from disk, or refuse. Copied from `shitcoims_sentinel/secrets.py`.

Deliberately duplicated rather than imported. `shitcoims_cluster/rpc.py` made the same call
for the same reason: a package that can move money must not have its permission check
change underneath it because another package refactored. Forty lines is a cheap price for
an independent boundary, and the tests here re-derive the invariant rather than trusting it.

The mode check is `mode & 0o077`, not `mode == 0o600`: ANY group or world bit is a refusal,
while a stricter 0o400 passes. The check runs on the arm file too, so an arm file somebody
chmod'ed to 644 disarms the desk instead of quietly arming it to the world.
"""

from __future__ import annotations

import stat
from pathlib import Path

from solders.keypair import Keypair


class SecretError(RuntimeError):
    pass


def read_secret_file(path: Path, *, required: bool = True) -> str | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        if required:
            raise SecretError(f"required secret file is missing: {path}") from None
        return None
    if not stat.S_ISREG(info.st_mode):
        raise SecretError(f"secret path is not a regular file: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise SecretError(f"secret file must not be group/world accessible: {path} is {mode:o}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        if required:
            raise SecretError(f"secret file is empty: {path}")
        return None
    return value


def load_keypair(path: Path, *, expected_pubkey: str | None = None) -> Keypair:
    """Load the wallet key, and refuse a key that is not the wallet we were built for.

    `expected_pubkey` is the difference between this and the sentinel's loader. This package
    is written for one wallet whose address is committed in `allowlist.THA_FUNDS`; loading
    some other key -- a stale path, a copied file, the sentinel's own wallet -- and then
    signing pool instructions with it is a class of accident worth one comparison.
    """
    encoded = read_secret_file(path, required=True)
    assert encoded is not None
    try:
        keypair = Keypair.from_base58_string(encoded)
    except Exception as exc:
        raise SecretError(f"{path} must contain a base58-encoded 64-byte keypair") from exc
    if len(bytes(keypair)) != 64:
        raise SecretError(f"{path} did not decode to a 64-byte keypair")
    if expected_pubkey is not None and str(keypair.pubkey()) != expected_pubkey:
        raise SecretError(
            f"{path} holds {keypair.pubkey()}, but this package manages {expected_pubkey}"
        )
    return keypair
