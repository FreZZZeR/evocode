# SPDX-License-Identifier: Apache-2.0
"""SecurityAccess "L3" — turn a requestSeed into a sendKey response with your own recovered key.

The coding write (and flashing) unlock with this handshake: hash a block built from the seed, sign
it raw-RSA with your L3 private key, and wire-encode the result a particular way. The algorithm is
public; only the key is yours, and it is never shipped — you pass the ``l3_key.json`` you recovered
from your own PSdZData.
"""
from __future__ import annotations

import hashlib


def _wordswap(b: bytes) -> bytes:
    if len(b) % 4:
        raise ValueError("length must be a multiple of 4")
    return b"".join(b[i:i + 4][::-1] for i in range(0, len(b), 4))


def sign_seed(seed: bytes, key: dict, btld: int = 0x00001FFD, user_id: int = 0x00000000) -> bytes:
    """Bytes to send after ``27 02``: ``MD5([UserID][Controller][seed])`` signed raw-RSA ``e=3``
    (little-endian), as a big-endian 32-bit word count followed by the per-word-swapped signature.

    ``key`` is a dict with ``modulus_hex`` and ``private_exponent_hex`` (public exponent defaults to
    3). ``btld`` is the module's bootloader id; ``user_id`` is the testerId sent with requestSeed
    (0 matches the proven flow). Raises if the signature fails self-verification (wrong key).
    """
    if len(seed) != 8:
        raise ValueError("seed must be 8 bytes, got %d" % len(seed))
    n = int(key["modulus_hex"], 16)
    d = int(key["private_exponent_hex"], 16)
    e = int(key.get("public_exponent", 3))
    block = user_id.to_bytes(4, "big") + btld.to_bytes(4, "big") + seed
    m = int.from_bytes(hashlib.md5(block).digest(), "little")
    s = pow(m, d, n)
    if pow(s, e, n) != m:
        raise ValueError("signature failed self-check — wrong L3 key?")
    size = (n.bit_length() + 7) // 8
    return (size // 4).to_bytes(4, "big") + _wordswap(s.to_bytes(size, "little"))
