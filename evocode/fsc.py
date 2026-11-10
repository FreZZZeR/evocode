# SPDX-License-Identifier: Apache-2.0
"""FSC activations — the owner-CA path: your own e=3 trust anchor, and FSCs you mint under it.

The NBT EVO verifies every "long" FSC against ONE RSA modulus — **blobB** — compiled into NBTCarHU
(``e=3``, PKCS#1 v1.5 / MD5). There is no per-feature key and no certificate lookup: an FSC is
accepted iff its signature verifies under whatever modulus is installed as blobB. This is a separate
mechanism from coding (which verifies against BMW's fixed Codier-Sign key you can only *recover*).

The owner path, on a car you own: generate your **own** e=3 key, install its modulus as blobB (a
length-preserving firmware patch — see ``find_blobb``/``patch_blobb``), and mint FSCs with your
private key. No BMW key is forged; you move the unit's trust to a key you hold.

``keygen``/``mint``/``verify``/``parse``/``recover_modulus`` are pure stdlib. ``recover_modulus``
(the e=3 GCD attack) identifies the anchor already on a used unit from the FSCs you read off it.
"""
from __future__ import annotations

import hashlib
import math
import secrets
import struct
from collections import Counter
from math import gcd
from typing import List, Tuple

MD5_DIGESTINFO = bytes.fromhex("3020300c06082a864886f70d020505000410")
BODY_LEN = 60
SIG_LEN = 128

# the application numbers this tooling was built around
APPNOS = {0x0143: "CarPlay", 0x00A0: "Navi Pro ECE", 0x0120: "Map Europe", 0x009C: "A4A / BMW Apps"}


# ---- the 60-byte signed body (byte-exact to the EVO FSC layout) ----

def build_body(appno: int, upgrade_idx: int = 1, supplier_id: bytes = b"       1",
               requester_type: bytes = b"       1", counter: int = 0x0001,
               fscs_id: bytes = b"C329361", vin=None, date: bytes = b"201608242124") -> bytes:
    b = bytearray(b"\x01\x01")
    b += struct.pack(">H", appno)
    b += struct.pack(">H", upgrade_idx)
    assert len(supplier_id) == 8
    b += supplier_id + b"\x01"
    assert len(requester_type) == 8
    b += requester_type
    b += struct.pack(">H", counter) + b"\x01"
    assert len(fscs_id) == 7
    b += fscs_id + b"\x01"                               # VIN-type 1 => a 9-byte VIN follows
    b += (b"\x00" * 9) if vin is None else (vin if isinstance(vin, bytes) else vin.encode())
    b += b"\x04\x02"                                     # date tag/len
    assert len(date) == 12
    b += date + b"Z\x00\x00"
    assert len(b) == BODY_LEN, "body len %d" % len(b)
    return bytes(b)


def _emsa(digest: bytes, modlen: int = SIG_LEN) -> bytes:
    """PKCS#1 v1.5 envelope over an MD5 digest, zero-slack (what the device expects)."""
    t = MD5_DIGESTINFO + digest
    return b"\x00\x01" + b"\xff" * (modlen - 3 - len(t)) + b"\x00" + t


def _emsa_int(body: bytes) -> int:
    return int.from_bytes(_emsa(hashlib.md5(body).digest()), "big")


# ---- mint / resign / verify / parse ----

def mint(n: int, d: int, appno: int, **body_kw) -> bytes:
    """A 188-byte FSC (60-byte body + 128-byte signature) signed by private (n, d), e=3."""
    body = build_body(appno, **body_kw)
    return body + pow(_emsa_int(body), d, n).to_bytes(SIG_LEN, "big")


def resign_body(body: bytes, n: int, d: int) -> bytes:
    """Re-sign an existing 60-byte body under (n, d) — reuse a real FSC's fields exactly."""
    return bytes(body[:BODY_LEN]) + pow(_emsa_int(body[:BODY_LEN]), d, n).to_bytes(SIG_LEN, "big")


def verify(fsc: bytes, n: int, e: int = 3):
    """Reproduce the on-device check: m = sig^e mod N, strip PKCS#1, compare MD5(body)."""
    body, sigb = fsc[:-SIG_LEN], fsc[-SIG_LEN:]
    sig = int.from_bytes(sigb, "big")
    if sig >= n:
        return False, "sig>=N"
    m = pow(sig, e, n).to_bytes(SIG_LEN, "big")
    if m[:2] != b"\x00\x01":
        return False, "bad 00 01"
    i = 2
    while i < SIG_LEN and m[i] == 0xFF:
        i += 1
    if m[i] != 0x00:
        return False, "FF run not 00-terminated"
    i += 1
    if m[i:i + 18] != MD5_DIGESTINFO:
        return False, "bad DigestInfo"
    if i + 34 != SIG_LEN:
        return False, "envelope not exactly 128 bytes"
    if m[i + 18:i + 34] != hashlib.md5(body).digest():
        return False, "hash mismatch"
    return True, "OK"


def parse(fsc: bytes) -> dict:
    b = fsc[:-SIG_LEN]
    vin = b[34:43]
    return {
        "version": b[0:2].hex(),
        "appno": "0x%04X" % struct.unpack(">H", b[2:4])[0],
        "upgrade_index": struct.unpack(">H", b[4:6])[0],
        "fscs_id": b[26:33].decode("latin1"),
        "vin": "(VIN-generic)" if vin == b"\x00" * 9 else vin.decode("latin1"),
        "creation_date": b[45:57].decode("latin1"),
    }


# ---- whose anchor signed these? (e=3 modulus recovery) ----

def recover_modulus(fscs: List[bytes]) -> int:
    """Recover the signing modulus from >=2 FSCs signed by the SAME anchor (e=3 GCD attack)."""
    if len(fscs) < 2:
        raise ValueError("need >=2 FSCs signed by the same anchor to recover a modulus")
    g = 0
    for f in fscs:
        body, sigb = f[:-SIG_LEN], f[-SIG_LEN:]
        g = gcd(g, abs(int.from_bytes(sigb, "big") ** 3 - _emsa_int(body)))
    p = 2
    while p < 100000:                                    # strip tiny cofactors, keep the ~1024-bit N
        while g % p == 0 and (g // p).bit_length() >= 1000:
            g //= p
        p += 1
    return g


def blobB_le(n: int) -> bytes:
    """The 128-byte blobB form of a modulus: little-endian (as it sits in NBTCarHU)."""
    return n.to_bytes(SIG_LEN, "little")


def fingerprint(n: int) -> str:
    return hashlib.sha256(blobB_le(n)).hexdigest()[:16]


# ---- generate your own e=3 anchor ----

def _probable_prime(num: int, rounds: int = 24) -> bool:
    for sp in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if num % sp == 0:
            return num == sp
    if num < 2:
        return False
    d, r = num - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(num - 3)
        x = pow(a, d, num)
        if x in (1, num - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, num)
            if x == num - 1:
                break
        else:
            return False
    return True


def _prime_e3(bits: int) -> int:
    """A prime p with (p-1) coprime to 3, so e=3 is invertible."""
    while True:
        cand = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        while not _probable_prime(cand):
            cand += 2
        if (cand - 1) % 3 != 0:
            return cand


def keygen(bits: int = 1024) -> dict:
    """Your owner trust anchor: RSA with e=3 (what the FSC verifier uses)."""
    p = _prime_e3(bits // 2)
    q = _prime_e3(bits // 2)
    while q == p:
        q = _prime_e3(bits // 2)
    n = p * q
    phi = (p - 1) * (q - 1)
    return {"n_hex": "%x" % n, "e": 3, "d_hex": "%x" % pow(3, -1, phi), "bits": n.bit_length()}


# ---- locating / swapping blobB in a NBTCarHU firmware dump ----

def _entropy(b: bytes) -> float:
    c = Counter(b)
    n = len(b)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def _small_primes(limit: int = 50000) -> List[int]:
    s = bytearray([1]) * limit
    s[0] = s[1] = 0
    for i in range(2, int(limit ** 0.5) + 1):
        if s[i]:
            s[i * i::i] = bytearray(len(s[i * i::i]))
    return [i for i in range(limit) if s[i]]


def find_blobb(nbtcarhu: bytes, bits: int = 1024) -> Tuple[int, int]:
    """Locate the installed FSC anchor in a NBTCarHU ELF dump → (file_offset, modulus).

    The verifier loads blobB's address from a PC-relative literal pool, so the real modulus's
    virtual address appears verbatim as a 4-byte little-endian pointer in the code. Among the
    high-entropy ~1024-bit candidates in the binary, exactly the installed one is code-referenced —
    which pins it with no stock image or disassembler.
    """
    d = nbtcarhu
    if d[:4] != b"\x7fELF" or d[4] != 1:
        raise ValueError("not an ELF32 image (expected a NBTCarHU dump)")
    phoff = struct.unpack("<I", d[28:32])[0]
    phentsize = struct.unpack("<H", d[42:44])[0]
    phnum = struct.unpack("<H", d[44:46])[0]
    segs = []
    for i in range(phnum):
        o = phoff + i * phentsize
        ptype, poff, pvaddr, _ppaddr, pfilesz = struct.unpack("<5I", d[o:o + 20])
        if ptype == 1:                                  # PT_LOAD
            segs.append((poff, pvaddr, pfilesz))

    def off2va(o):
        for poff, pvaddr, pfilesz in segs:
            if poff <= o < poff + pfilesz:
                return pvaddr + (o - poff)
        return None

    L = len(d)
    nbytes = bits // 8

    # This build wraps the anchor in a little key struct { ver(u32)=1, e(u32)=3, len_words(u32),
    # modulus }, and the code references the STRUCT address — so find a code-referenced struct of the
    # wanted width and take the modulus at +12.
    want_words = bits // 32
    o = 0
    while o + 12 + nbytes <= L:
        ver, e3, lw = struct.unpack("<3I", d[o:o + 12])
        if ver == 1 and e3 == 3 and lw == want_words:
            va = off2va(o)
            if va is not None and d.find(struct.pack("<I", va)) >= 0:
                moff = o + 12
                n = int.from_bytes(d[moff:moff + nbytes], "little")
                if (n & 1) and n.bit_length() >= bits - 8:
                    return moff, n
        o += 4

    # Fallback: a build that stores the modulus unwrapped — find the single code-referenced candidate.
    primes = _small_primes()
    o = 0
    while o + nbytes <= L:
        if (d[o] & 1) and (d[o + nbytes - 1] & 0x80):
            w = d[o:o + nbytes]
            if _entropy(w) > 6.4:
                n = int.from_bytes(w, "little")
                if n.bit_length() >= bits - 7 and all(n % p for p in primes):
                    va = off2va(o)
                    if va is not None and d.find(struct.pack("<I", va)) >= 0:
                        return o, n
        o += 4
    raise LookupError("blobB not located by code reference (PIC/GOT? pass an explicit offset)")


def patch_blobb(nbtcarhu: bytes, offset: int, modulus: int) -> bytes:
    """A copy of the dump with the 128 bytes at ``offset`` replaced by ``modulus`` (length-preserving)."""
    d = bytearray(nbtcarhu)
    d[offset:offset + SIG_LEN] = blobB_le(modulus)
    return bytes(d)
