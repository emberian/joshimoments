"""The DLMM account layouts, read from the program's own on-chain Anchor IDL.

Nothing here hand-writes an offset. `LbPair` is 904 bytes of nested structs and arrays and the
one thing worse than not decoding it is decoding it slightly wrong -- a mis-set offset would
silently shift `active_id`, and a Lean model validated against a shifted `active_id` is
validated against nothing. So the layout comes from the deployed program's published IDL and
the decoder is driven by it.

The IDL is fetched once and cached under `cache/idl.json`.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from rpc import get_account

DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
_CACHE = Path(__file__).resolve().parent / "cache" / "idl.json"


class IdlUnavailable(RuntimeError):
    """The program's IDL could not be read. Decoding cannot proceed on a guessed layout."""


def idl_address(program_id: str = DLMM_PROGRAM) -> Pubkey:
    pid = Pubkey.from_string(program_id)
    base, _ = Pubkey.find_program_address([], pid)
    return Pubkey.create_with_seed(base, "anchor:idl", pid)


def load_idl(*, refresh: bool = False) -> dict[str, Any]:
    if _CACHE.exists() and not refresh:
        return json.loads(_CACHE.read_text())
    acct = get_account(str(idl_address()))
    if acct is None:
        raise IdlUnavailable(f"no IDL account at {idl_address()} for {DLMM_PROGRAM}")
    raw = base64.b64decode(acct["data"][0])
    # Anchor IDL account: 8 discriminator + 32 authority + 4 length + zlib(json)
    (length,) = struct.unpack_from("<I", raw, 40)
    idl = json.loads(zlib.decompress(raw[44 : 44 + length]))
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(idl))
    return idl


# --------------------------------------------------------------------------------------
# Borsh reader, driven by IDL type nodes.
# --------------------------------------------------------------------------------------

_SCALARS: dict[str, tuple[str, int]] = {
    "u8": ("<B", 1),
    "i8": ("<b", 1),
    "u16": ("<H", 2),
    "i16": ("<h", 2),
    "u32": ("<I", 4),
    "i32": ("<i", 4),
    "u64": ("<Q", 8),
    "i64": ("<q", 8),
    "bool": ("<?", 1),
}


class Layout:
    """Decodes IDL-described types out of a byte buffer."""

    def __init__(self, idl: dict[str, Any]) -> None:
        self.idl = idl
        self.types = {t["name"]: t for t in idl.get("types", [])}
        self.accounts = {a["name"]: a for a in idl.get("accounts", [])}

    def account_discriminator(self, name: str) -> bytes:
        return bytes(self.accounts[name]["discriminator"])

    def instruction(self, name: str) -> dict[str, Any]:
        for ix in self.idl["instructions"]:
            if ix["name"] == name:
                return ix
        raise KeyError(f"no instruction {name!r} in IDL")

    def decode_account(self, name: str, data: bytes) -> dict[str, Any]:
        disc = self.account_discriminator(name)
        if data[:8] != disc:
            raise ValueError(
                f"account is not a {name}: discriminator {data[:8].hex()} != {disc.hex()}"
            )
        value, _ = self._read({"defined": {"name": name}}, data, 8)
        return value

    def _read(self, ty: Any, buf: bytes, off: int) -> tuple[Any, int]:
        if isinstance(ty, str):
            if ty in _SCALARS:
                fmt, size = _SCALARS[ty]
                return struct.unpack_from(fmt, buf, off)[0], off + size
            if ty in ("u128", "i128"):
                signed = ty == "i128"
                return int.from_bytes(buf[off : off + 16], "little", signed=signed), off + 16
            if ty in ("pubkey", "publicKey"):
                return str(Pubkey(buf[off : off + 32])), off + 32
            if ty == "string":
                (n,) = struct.unpack_from("<I", buf, off)
                return buf[off + 4 : off + 4 + n].decode(), off + 4 + n
            raise ValueError(f"unhandled scalar type {ty!r}")

        if "array" in ty:
            inner, count = ty["array"]
            if inner == "u8":
                return list(buf[off : off + count]), off + count
            out = []
            for _ in range(count):
                v, off = self._read(inner, buf, off)
                out.append(v)
            return out, off

        if "vec" in ty:
            (n,) = struct.unpack_from("<I", buf, off)
            off += 4
            out = []
            for _ in range(n):
                v, off = self._read(ty["vec"], buf, off)
                out.append(v)
            return out, off

        if "option" in ty:
            tag = buf[off]
            off += 1
            if tag == 0:
                return None, off
            return self._read(ty["option"], buf, off)

        if "defined" in ty:
            name = ty["defined"]["name"] if isinstance(ty["defined"], dict) else ty["defined"]
            node = self.types[name]["type"]
            if node["kind"] == "struct":
                out: dict[str, Any] = {}
                for f in node.get("fields", []):
                    out[f["name"]], off = self._read(f["type"], buf, off)
                return out, off
            if node["kind"] == "enum":
                tag = buf[off]
                off += 1
                variant = node["variants"][tag]
                return {"__variant": variant["name"]}, off
            raise ValueError(f"unhandled defined kind {node['kind']!r} for {name}")

        raise ValueError(f"unhandled type node {ty!r}")


_LAYOUT: Layout | None = None


def layout() -> Layout:
    global _LAYOUT
    if _LAYOUT is None:
        _LAYOUT = Layout(load_idl())
    return _LAYOUT


# --------------------------------------------------------------------------------------
# PDAs. Seeds match the deployed program (`lb_clmm` 0.12.0).
# --------------------------------------------------------------------------------------

BINS_PER_ARRAY = 70


def bin_array_index(bin_id: int) -> int:
    """Which BinArray holds `bin_id`. Floor division, so negative ids land one array lower."""
    return bin_id // BINS_PER_ARRAY


def bin_array_pda(lb_pair: str, index: int, program_id: str = DLMM_PROGRAM) -> Pubkey:
    return Pubkey.find_program_address(
        [b"bin_array", bytes(Pubkey.from_string(lb_pair)), struct.pack("<q", index)],
        Pubkey.from_string(program_id),
    )[0]


def bitmap_extension_pda(lb_pair: str, program_id: str = DLMM_PROGRAM) -> Pubkey:
    return Pubkey.find_program_address(
        [b"bitmap", bytes(Pubkey.from_string(lb_pair))], Pubkey.from_string(program_id)
    )[0]


def event_authority_pda(program_id: str = DLMM_PROGRAM) -> Pubkey:
    return Pubkey.find_program_address([b"__event_authority"], Pubkey.from_string(program_id))[0]
