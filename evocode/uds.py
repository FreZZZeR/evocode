# SPDX-License-Identifier: Apache-2.0
"""UDS (ISO 14229) over HSFZ — only the services coding needs, plus SVK (``22 F1 01``) decoding.

The SVK is how you learn a module's bootloader (BTLD) and coding dataset (CAFD) ids and versions;
almost everything (which signing key, which coding layout) keys off those. Read it first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .hsfz import Hsfz, TGT_HU

# service ids
SID_SESSION = 0x10
SID_RESET = 0x11
SID_SECURITY = 0x27
SID_READ_DID = 0x22
SID_WRITE_DID = 0x2E
SID_ROUTINE = 0x31

# identifiers used here
DID_SVK = 0xF101
DID_VIN = 0xF190

# The canonical UDS negative-response names. swdl.py builds on this (adds flash-specific NRCs).
NRC_NAMES = {
    0x10: "generalReject", 0x11: "serviceNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat", 0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts", 0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

# SVK process classes (first byte of each 8-byte entry) — the ones coding cares about named.
_SVK_CLASS = {1: "HWEL", 2: "HWAP", 3: "HWFR", 4: "GWTB", 5: "CAFD", 6: "BTLD", 7: "FLSL",
              8: "SWFL", 9: "SWFF", 10: "SWPF", 11: "ONPS"}


class UdsError(Exception):
    def __init__(self, sid: int, nrc: int):
        self.sid, self.nrc = sid, nrc
        super().__init__("UDS 0x%02X negative response: 0x%02X (%s)" % (sid, nrc, NRC_NAMES.get(nrc, "unknown")))


def _positive(sid: int, resp: bytes) -> bytes:
    if len(resp) >= 3 and resp[0] == 0x7F and resp[1] == sid:
        raise UdsError(sid, resp[2])
    if not resp or resp[0] != sid + 0x40:
        raise RuntimeError("unexpected UDS response to 0x%02X: %s" % (sid, resp.hex()))
    return resp


@dataclass
class SgbmId:
    kind: str
    id: int
    main: int
    sub: int
    patch: int

    @property
    def id_hex(self) -> str:
        return "%08X" % self.id

    @property
    def version(self) -> str:
        return "%03d.%03d.%03d" % (self.main, self.sub, self.patch)

    def __str__(self) -> str:
        return "%s-%s-%s" % (self.kind, self.id_hex, self.version)


@dataclass
class Svk:
    version: int
    prog_dep_checked: int
    entries: List[SgbmId]

    def of(self, kind: str) -> List[SgbmId]:
        return [e for e in self.entries if e.kind == kind]

    @property
    def btld(self) -> Optional[SgbmId]:
        got = self.of("BTLD")
        return min(got, key=lambda e: (e.id, e.main, e.sub, e.patch)) if got else None

    @property
    def cafds(self) -> List[SgbmId]:
        return self.of("CAFD")


def decode_sgbm(b: bytes, at: int = 0) -> SgbmId:
    cls = b[at]
    return SgbmId(_SVK_CLASS.get(cls, "C%02X" % cls),
                  int.from_bytes(b[at + 1:at + 5], "big"), b[at + 5], b[at + 6], b[at + 7])


def decode_svk(value: bytes) -> Svk:
    """Decode the bytes after ``62 F1 01``.

    Layout: ``[version u8][progDepChecked u8][count u16 BE][fingerprint (variable)][N*8 entries]``.
    The fingerprint length varies, so the entries are taken from the final ``8*count`` bytes.
    """
    if len(value) < 4:
        raise ValueError("SVK too short: %d bytes" % len(value))
    count = int.from_bytes(value[2:4], "big")
    need = count * 8
    if 4 + need > len(value):
        raise ValueError("SVK announces %d entries but has only %d bytes" % (count, len(value)))
    first = len(value) - need
    entries = [decode_sgbm(value, first + i * 8) for i in range(count)]
    return Svk(value[0], value[1], entries)


class Uds:
    """A thin UDS facade bound to one target over an :class:`~evocode.hsfz.Hsfz` session."""

    def __init__(self, hsfz: Hsfz, target: int = TGT_HU):
        self.h = hsfz
        self.target = target

    def raw(self, uds: bytes) -> bytes:
        return self.h.request(self.target, uds)

    def session(self, sub: int) -> bytes:
        return _positive(SID_SESSION, self.raw(bytes([SID_SESSION, sub])))

    def reset(self, sub: int = 0x01) -> bytes:
        return _positive(SID_RESET, self.raw(bytes([SID_RESET, sub])))

    def request_seed(self, level: int, tester_id: int = 0x00000000) -> bytes:
        # requestSeed carries the 4-byte testerId; a bare 27 xx returns NRC 0x13.
        r = _positive(SID_SECURITY, self.raw(bytes([SID_SECURITY, level]) + tester_id.to_bytes(4, "big")))
        return r[2:]  # strip SID echo + level

    def send_key(self, level: int, key: bytes) -> bytes:
        return _positive(SID_SECURITY, self.raw(bytes([SID_SECURITY, level]) + key))

    def read_did(self, did: int) -> bytes:
        r = _positive(SID_READ_DID, self.raw(bytes([SID_READ_DID, did >> 8, did & 0xFF])))
        return r[3:]  # strip 62 + 2-byte DID echo

    def write_did(self, did: int, data: bytes) -> bytes:
        return _positive(SID_WRITE_DID, self.raw(bytes([SID_WRITE_DID, did >> 8, did & 0xFF]) + data))

    def routine(self, sub: int, rid: int, data: bytes = b"") -> bytes:
        return _positive(SID_ROUTINE, self.raw(bytes([SID_ROUTINE, sub, rid >> 8, rid & 0xFF]) + data))

    def read_vin(self) -> str:
        return self.read_did(DID_VIN).decode("latin1").strip("\x00 ")

    def read_svk(self) -> Svk:
        return decode_svk(self.read_did(DID_SVK))
