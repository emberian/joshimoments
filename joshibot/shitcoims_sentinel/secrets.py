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


def load_shitcoims_keypair(path: Path) -> Keypair:
    encoded = read_secret_file(path, required=True)
    assert encoded is not None
    try:
        keypair = Keypair.from_base58_string(encoded)
    except Exception as exc:
        raise SecretError("shitcoims wallet secret must be a base58-encoded 64-byte keypair") from exc
    if len(bytes(keypair)) != 64:
        raise SecretError("shitcoims wallet secret did not decode to a 64-byte keypair")
    return keypair

