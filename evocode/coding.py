# SPDX-License-Identifier: Apache-2.0
"""The NBT EVO coding signature (BMWSigVerify) — the maths the head unit runs at every boot.

A signature covers the content datagroups, is computed with the key the bootloader (BTLD) selects,
and lives in its own datagroup. Edit any coding byte without recomputing it and the change reverts
on the next boot. Verifying needs only the public modulus; producing a signature needs the private
exponent (recover it from your own PSdZData — never shipped here).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Tuple

from . import srec


@dataclass(frozen=True)
class Scheme:
    """Which datagroups are signed, with which digest, and where the signature is stored."""
    name: str
    content_dgs: Tuple[int, ...]
    sig_dg: int
    digest: str                       # "md5" or "sha256"

    @property
    def digest_len(self) -> int:
        return hashlib.new(self.digest).digest_size


# NBT EVO (QNX): datagroups 0x3000..0x300F signed with MD5, signature in 0x3010.
NBTEVO = Scheme("nbtevo", tuple(range(0x3000, 0x3010)), 0x3010, "md5")
SCHEMES = {NBTEVO.name: NBTEVO}
DEFAULT_SCHEME = NBTEVO.name


@dataclass
class Key:
    modulus: int
    public_exponent: int = 3
    private_exponent: Optional[int] = None
    btld: Optional[str] = None

    @property
    def size(self) -> int:
        return (self.modulus.bit_length() + 7) // 8


def load_key(path: str) -> Key:
    d = json.loads(open(path, encoding="utf-8").read())
    priv = d.get("private_exponent_hex")
    return Key(
        modulus=int(d["modulus_hex"], 16),
        public_exponent=int(d.get("public_exponent", 3)),
        private_exponent=int(priv, 16) if priv else None,
        btld=d.get("btld"),
    )


def _wordswap(b: bytes) -> bytes:
    """Reverse the bytes within each 32-bit word — BMW's big-number storage order."""
    if len(b) % 4:
        raise ValueError("length must be a multiple of 4")
    return b"".join(b[i:i + 4][::-1] for i in range(0, len(b), 4))


def content_digest(mem: srec.Mem, scheme: Scheme = NBTEVO) -> bytes:
    pages = srec.pages(mem, scheme.content_dgs)
    content = b"".join(pages[dg] for dg in scheme.content_dgs if dg in pages)
    return hashlib.new(scheme.digest, content).digest()


def sign(mem: srec.Mem, key: Key, scheme: Scheme = NBTEVO) -> bytes:
    """The raw signature bytes over the current content (does not modify ``mem``)."""
    if key.private_exponent is None:
        raise ValueError("key has no private exponent; recover it from your own PSdZData")
    m = int.from_bytes(content_digest(mem, scheme), "little")
    s = pow(m, key.private_exponent, key.modulus)
    return _wordswap(s.to_bytes(key.size, "little"))


def signature_page(sig: bytes, key: Key) -> bytes:
    """Signature datagroup payload: big-endian 32-bit word count, then the signature."""
    return (key.size // 4).to_bytes(4, "big") + sig


def resign(mem: srec.Mem, key: Key, scheme: Scheme = NBTEVO) -> bytes:
    """Recompute the signature and write it into the signature datagroup, in place."""
    sig = sign(mem, key, scheme)
    base = scheme.sig_dg << 8
    for i, b in enumerate(signature_page(sig, key)):
        mem[base + i] = b
    return sig


def verify(mem: srec.Mem, key: Key, scheme: Scheme = NBTEVO) -> bool:
    """Reproduce the ECU's check: raise the stored signature to ``e``, compare to the content digest."""
    digest = content_digest(mem, scheme)
    page = srec.pages(mem, [scheme.sig_dg]).get(scheme.sig_dg, b"")
    if len(page) < 4 + key.size:
        return False
    sig = page[4:4 + key.size]
    recovered = pow(int.from_bytes(_wordswap(sig), "little"), key.public_exponent, key.modulus)
    return (recovered.to_bytes(scheme.digest_len, "little") == digest
            and recovered.bit_length() <= 8 * scheme.digest_len)
