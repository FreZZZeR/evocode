# SPDX-License-Identifier: Apache-2.0
"""Offline self-tests. No car, no network.

Run directly (``python tests/test_coding.py``) or under pytest. The core tests use a throwaway e=3
key to prove the signer and verifier are mutually consistent, and prove the SREC round-trip. If you
point EVOCODE_TEST_NCD (a real backup) and EVOCODE_TEST_KEY (its public modulus) at real data, an
extra test proves the verifier reproduces the car's own signature — the gold check.
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evocode import coding, srec


# ---- a throwaway e=3 keypair (test only; the real coding key is BMW's, recovered not generated) ----

def _is_prime(n, rounds=16):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = 2 + secrets.randbelow(n - 3)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime_e3(bits):
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if (c - 1) % 3 and _is_prime(c):
            return c


def _keygen(bits=256):
    p = _prime_e3(bits // 2)
    q = _prime_e3(bits // 2)
    while q == p:
        q = _prime_e3(bits // 2)
    n = p * q
    phi = (p - 1) * (q - 1)
    return coding.Key(modulus=n, public_exponent=3, private_exponent=pow(3, -1, phi))


def _synthetic_mem():
    """A minimal NBT EVO coding image: a few bytes in each content datagroup, empty signature dg."""
    mem = {}
    for dg in coding.NBTEVO.content_dgs:
        for off in range(4):
            srec.set_byte(mem, dg, off, (dg + off) & 0xFF)
    return mem


# ---- tests ----

def test_srec_roundtrip():
    mem = _synthetic_mem()
    meta = {"header": "S0030000FC",
            "chunks": [((dg << 8), 4) for dg in coding.NBTEVO.content_dgs],
            "terminator": "S70500000000FA"}
    again, _ = srec.parse(srec.emit(mem, meta))
    assert again == mem, "SREC emit->parse is not identity"


def test_sign_and_verify():
    key = _keygen()
    mem = _synthetic_mem()
    assert not coding.verify(mem, key, coding.NBTEVO), "unsigned image must not verify"
    coding.resign(mem, key, coding.NBTEVO)
    assert coding.verify(mem, key, coding.NBTEVO), "freshly signed image must verify"


def test_tamper_breaks_signature():
    key = _keygen()
    mem = _synthetic_mem()
    coding.resign(mem, key, coding.NBTEVO)
    srec.set_byte(mem, 0x3000, 0, 0xAA)                 # change content, do NOT re-sign
    assert not coding.verify(mem, key, coding.NBTEVO), "edited-but-unsigned image must fail verify"


def test_real_signature_optional():
    """Gold check against a real car: verifier reproduces the unit's own signature. Skipped unless
    EVOCODE_TEST_NCD and EVOCODE_TEST_KEY point at real data."""
    ncd, keyf = os.environ.get("EVOCODE_TEST_NCD"), os.environ.get("EVOCODE_TEST_KEY")
    if not (ncd and keyf and Path(ncd).exists() and Path(keyf).exists()):
        print("  (real-signature test skipped: set EVOCODE_TEST_NCD + EVOCODE_TEST_KEY)")
        return
    mem, _ = srec.parse(Path(ncd).read_text())
    key = coding.load_key(keyf)
    assert coding.verify(mem, key, coding.NBTEVO), "verifier did NOT reproduce the car's real signature"
    print("  real-signature check: OK (verifier matches the car)")


def test_catalog_decode():
    from evocode import catalog
    mem = {}
    srec.set_byte(mem, 0x3000, 107, 1, 0x80, 7)              # A4A on
    params = [catalog.Param("A4A", 0x3000, 107, 0x80, 7, {0: "off", 1: "on"}, default=0)]
    got = {p.name: (raw, lab) for p, raw, lab in catalog.decode(mem, params)}
    assert got["A4A"] == (1, "on"), got


def test_fsc_sign_recover():
    from evocode import fsc as F
    k = F.keygen(1024)
    n, d = int(k["n_hex"], 16), int(k["d_hex"], 16)
    a, b = F.mint(n, d, 0x0143), F.mint(n, d, 0x00A0)
    assert F.verify(a, n)[0] and F.verify(b, n)[0], "own mint must verify under own key"
    assert F.recover_modulus([a, b]) == n, "e=3 GCD must recover the signing modulus"
    tampered = bytearray(a)
    tampered[2] ^= 1                                        # change appno, keep old signature
    assert not F.verify(bytes(tampered), n)[0], "tampered body must fail verify"


def test_fsc_swt_framing():
    from evocode import fsc as F
    import base64
    assert F.swid(0x0143, 1) == bytes.fromhex("01430001")
    k = F.keygen(1024); n, d = int(k["n_hex"], 16), int(k["d_hex"], 16)
    tok = F.mint(n, d, 0x0143, upgrade_idx=1)
    assert F.swid_of(tok) == F.swid(0x0143, 1), "SWID must come straight from the FSC body"
    assert F.store_payload(tok) == F.swid_of(tok) + tok, "store = SWID + raw FSC (ODX)"
    assert F.store_payload(tok, base32=True) == F.swid_of(tok) + base64.b32encode(tok)


def test_build_skeleton():
    from evocode import catalog
    xml = (b'<caf><data><datagroup address="3000">'
           b'<function name="."><storageInfo><start>107</start><mask>10000000b</mask></storageInfo>'
           b'<defVal><unitVal position="0">00</unitVal></defVal></function>'
           b'</datagroup></data></caf>')
    doc = catalog.build_skeleton(xml)
    assert doc["parameters"] == [
        {"name": "", "datagroup": "0x3000", "byte": 107, "mask": "0x80", "shift": 7, "default": 0}
    ], doc["parameters"]


def test_fw_install_plan():
    from evocode import fw
    steps = fw.plan("/fs/sda0/opt/car/bin/NBTCarHU", "/fs/sda0",
                    "/fs/sda0/opt/car/bin/NBTCarHU.new", 3827760,
                    backup=True, mode="755", restart="appreset")
    assert steps[0] == "mount -uw /fs/sda0", steps                     # remount rw first
    bi = next(i for i, s in enumerate(steps) if s.startswith("["))     # backup
    ui = next(i for i, s in enumerate(steps) if s.startswith("upload "))
    mi = next(i for i, s in enumerate(steps) if s.startswith("mv "))   # rename-over
    assert bi < mi and ui < mi, steps                                  # backup + upload precede rename-over
    assert steps[mi].endswith("/fs/sda0/opt/car/bin/NBTCarHU"), steps  # mv targets the real path
    assert "mount -ur /fs/sda0" in steps and steps[-1] == "restart: appreset", steps
    # --no-backup drops the cp step
    assert not any(s.startswith("[") for s in fw.plan("/a/b", "/a", "/a/b.new", 10, backup=False))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok:", t.__name__)
    print("\nALL %d TESTS PASSED" % len(tests))
