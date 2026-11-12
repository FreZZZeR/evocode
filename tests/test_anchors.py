# SPDX-License-Identifier: Apache-2.0
"""find_anchors / identify_anchor: a used dump can carry >1 e=3 modulus — pick the one the FSCs prove.

Regression for the real-unit lesson: find_blobb returned a struct-wrapped decoy while the live FSC
anchor was a different, bare length-prefixed modulus. identify_anchor must pick the validator, not
the decoy, so patch-blobb targets the right 128 bytes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evocode import fsc as F


def _dump_with_two_anchors():
    """A fake NBTCarHU slice: a bare length-prefixed modulus A, and a struct-wrapped modulus B."""
    A, B = F.keygen(1024), F.keygen(1024)
    nA, nB = int(A["n_hex"], 16), int(B["n_hex"], 16)
    lw = (32).to_bytes(4, "little")
    buf = bytearray(b"\x5a" * 64)
    offA = len(buf) + 4
    buf += lw + nA.to_bytes(128, "little")                      # bare, length-prefixed (real-anchor form)
    buf += b"\x5a" * 48
    offB = len(buf) + 12
    buf += b"\x01\x00\x00\x00" + b"\x03\x00\x00\x00" + lw + nB.to_bytes(128, "little")  # {ver,e=3,lw}+mod
    buf += b"\x5a" * 64
    return bytes(buf), offA, nA, offB, nB, A


def test_find_anchors_sees_both_forms():
    buf, offA, nA, offB, nB, _ = _dump_with_two_anchors()
    found = {off: (n, kind) for off, n, kind in F.find_anchors(buf)}
    assert found.get(offA) == (nA, "lenprefix"), found
    assert found.get(offB) == (nB, "struct"), found


def test_identify_picks_the_fsc_anchor_not_the_decoy():
    buf, offA, nA, offB, nB, A = _dump_with_two_anchors()
    d = int(A["d_hex"], 16)
    fscs = [F.mint(nA, d, ap) for ap in (0x0143, 0x00A0)]        # signed by A, never B
    assert F.identify_anchor(buf, fscs) == (offA, nA, "little")  # the validator, not struct decoy B


def test_recover_and_locate_agree():
    buf, offA, nA, offB, nB, A = _dump_with_two_anchors()
    d = int(A["d_hex"], 16)
    fscs = [F.mint(nA, d, ap) for ap in (0x0143, 0x00A0)]
    assert F.recover_modulus(fscs) == nA                         # e=3 GCD recovers A from its FSCs
    assert F.anchor_at(buf, nA) == (offA, "little")              # and A is located byte-exact


def test_identify_none_when_anchor_absent():
    buf, offA, nA, offB, nB, A = _dump_with_two_anchors()
    other = F.keygen(1024)                                       # FSCs from a key not in the dump
    d = int(other["d_hex"], 16)
    fscs = [F.mint(int(other["n_hex"], 16), d, ap) for ap in (0x0143, 0x00A0)]
    assert F.identify_anchor(buf, fscs) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok:", t.__name__)
    print("\nALL %d TESTS PASSED" % len(tests))
