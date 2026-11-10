# SPDX-License-Identifier: Apache-2.0
"""Motorola S-record (SREC) read/write for NBT EVO coding NCD files.

An NCD stores each coding datagroup's bytes at address ``(datagroup << 8) + offset``. BMW/E-Sys
export these as **S2** (24-bit address) data records, an S0 header, and an S5 record-count trailer;
others use S3 (32-bit) with an S7 end record. We accept S1/S2/S3 data and re-emit each with the same
address width, and we preserve the header and trailer records verbatim, so an edited file round-trips
byte-for-byte except where data changed. The signature is over the datagroup *content*, never the
record framing.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

Mem = Dict[int, int]            # address -> byte
Chunk = Tuple[int, int, int]    # (start address, length, address-byte-width)

_ADDR_WIDTH = {"1": 2, "2": 3, "3": 4}        # data-record type -> address bytes
_TYPE_FOR_WIDTH = {2: "1", 3: "2", 4: "3"}


def _checksum(payload: bytes) -> int:
    """S-record checksum: ones' complement of the low byte of the sum of count+address+data."""
    return (~sum(payload)) & 0xFF


def parse(text: str) -> Tuple[Mem, dict]:
    """Parse SREC text into a {address: byte} map plus the metadata needed to re-emit it."""
    mem: Mem = {}
    chunks: List[Chunk] = []
    header = None
    trailer: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 4 or line[0] != "S":
            continue
        stype = line[1]
        count = int(line[2:4], 16)
        body = bytes.fromhex(line[4:4 + count * 2])          # address + data + checksum
        if stype == "0":
            header = line
        elif stype in _ADDR_WIDTH:
            w = _ADDR_WIDTH[stype]
            addr = int.from_bytes(body[:w], "big")
            data = body[w:-1]                                # strip trailing checksum
            for i, b in enumerate(data):
                mem[addr + i] = b
            chunks.append((addr, len(data), w))
        elif stype in ("5", "6", "7", "8", "9"):             # record-count + end records
            trailer.append(line)
    return mem, {"header": header, "chunks": chunks, "trailer": trailer}


def _data_record(addr: int, data: bytes, width: int) -> str:
    count = width + len(data) + 1
    body = addr.to_bytes(width, "big") + data
    return "S%s%02X%s%02X" % (_TYPE_FOR_WIDTH[width], count, body.hex().upper(),
                              _checksum(bytes([count]) + body))


def count_record(n: int) -> str:
    """An S5 record stating the number of preceding data records."""
    body = n.to_bytes(2, "big")
    count = len(body) + 1
    return "S5%02X%s%02X" % (count, body.hex().upper(), _checksum(bytes([count]) + body))


def emit(mem: Mem, meta: dict) -> str:
    """Re-emit SREC text from a (possibly edited) mem, preserving address widths and trailer records."""
    lines = [meta.get("header") or "S0030000FC"]
    for chunk in meta["chunks"]:
        addr, length = chunk[0], chunk[1]
        width = chunk[2] if len(chunk) > 2 else 4
        data = bytes(mem.get(addr + i, 0) for i in range(length))
        lines.append(_data_record(addr, data, width))
    lines.extend(meta.get("trailer") or ["S70500000000FA"])
    return "\n".join(lines) + "\n"


def pages(mem: Mem, datagroups) -> Dict[int, bytes]:
    """{datagroup: contiguous bytes} for each requested datagroup present in mem (address = dg<<8)."""
    out: Dict[int, bytes] = {}
    for dg in datagroups:
        base = dg << 8
        run = bytearray()
        i = 0
        while (base + i) in mem:
            run.append(mem[base + i])
            i += 1
        if run:
            out[dg] = bytes(run)
    return out


def set_byte(mem: Mem, dg: int, off: int, val: int, mask: int = 0xFF, shift: int = 0) -> None:
    """Edit one coding byte in place: mem[dg,off] = (old & ~mask) | ((val<<shift) & mask)."""
    addr = (dg << 8) + off
    mem[addr] = (mem.get(addr, 0) & ~mask) | ((val << shift) & mask)
