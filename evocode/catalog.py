# SPDX-License-Identifier: Apache-2.0
"""Per-CAFD bit catalogs: load one and decode a read NCD against it.

A catalog is one JSON file per CAFD (see catalogs/README.md): a list of parameters, each addressing
a coding bitfield by (datagroup, byte, mask, shift) with optional value labels. Decoding is purely
mechanical — the catalog is the data. The names/labels in a catalog are reconstructed descriptions
(firmware-traced or token-derived), authored and grown by the community, not shipped BMW data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import srec


@dataclass
class Param:
    name: str
    dg: int
    byte: int
    mask: int
    shift: int
    values: Dict[int, str] = field(default_factory=dict)
    default: Optional[int] = None
    token: Optional[str] = None


def _int(x) -> int:
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if s.endswith("b"):                 # binary mask like "10000000b"
        return int(s[:-1], 2)
    return int(s, 0)                     # "0x80", "128", "0b1000"


def _shift_of(mask: int) -> int:
    return (mask & -mask).bit_length() - 1 if mask else 0


def load(path: str) -> List[Param]:
    doc = json.loads(open(path, encoding="utf-8").read())
    records = doc["parameters"] if isinstance(doc, dict) else doc
    out: List[Param] = []
    for r in records:
        mask = _int(r.get("mask", 0xFF))
        shift = int(r["shift"]) if "shift" in r else _shift_of(mask)
        dg = _int(r["datagroup"] if "datagroup" in r else r["dg"])
        default = r.get("default")
        out.append(Param(
            name=r.get("name") or r.get("token") or r.get("coord") or "?",
            dg=dg, byte=int(r["byte"]), mask=mask, shift=shift,
            values={_int(k): v for k, v in (r.get("values") or {}).items()},
            default=_int(default) if default not in (None, "") else None,
            token=r.get("token"),
        ))
    return out


def decode(mem: srec.Mem, params: List[Param]):
    """Yield (param, raw_value, label_or_None) for each parameter whose byte is present in mem."""
    for p in params:
        addr = (p.dg << 8) + p.byte
        if addr not in mem:
            continue
        raw = (mem[addr] & p.mask) >> p.shift
        yield p, raw, p.values.get(raw)


# ---- building a catalog skeleton from a decrypted CAFD XML ----

def _mask_int(s: str) -> int:
    s = (s or "").strip()
    return int(s[:-1], 2) if s.endswith("b") else int(s, 0)


def build_skeleton(cafd_xml: bytes) -> dict:
    """Turn a decrypted CAFD XML (see evocode.caf) into a catalog skeleton: every coding coordinate
    with its datagroup, byte, mask, shift and factory default. Parameter NAMES and value labels are
    left blank — BMW ships the CAFD with those stripped; they are a firmware-token / community overlay.
    """
    import xml.etree.ElementTree as ET

    def ln(t):
        return t.rsplit("}", 1)[-1]

    root = ET.fromstring(cafd_xml)
    data = next(e for e in root.iter() if ln(e.tag) == "data")
    params = []
    for dg in data:
        if ln(dg.tag) != "datagroup":
            continue
        addr = dg.attrib.get("address", "")
        for f in dg:
            if ln(f.tag) != "function":
                continue
            si = next((c for c in f if ln(c.tag) == "storageInfo"), None)
            if si is None:
                continue
            get = lambda nm: next((c.text for c in si if ln(c.tag) == nm), None)  # noqa: E731
            start, mask = get("start"), get("mask")
            if start is None or mask is None:
                continue
            m = _mask_int(mask)
            rec = {
                "name": "" if f.attrib.get("name", ".") in (".", "") else f.attrib["name"],
                "datagroup": "0x%s" % addr.upper(),
                "byte": int(start),
                "mask": "0x%02X" % m,
                "shift": (m & -m).bit_length() - 1 if m else 0,
            }
            dv = next((c for c in f if ln(c.tag) == "defVal"), None)
            if dv is not None:
                uv = next((c for c in dv if ln(c.tag) == "unitVal"), None)
                if uv is not None and (uv.text or "").strip():
                    try:
                        rec["default"] = int(uv.text.strip(), 16)
                    except ValueError:
                        pass
            params.append(rec)
    return {"cafd": "", "version": "",
            "note": "Skeleton from `evocode build-catalog`: coordinates/masks/defaults are factual, "
                    "from your CAFD. Parameter names/value-labels are blank — add them from the "
                    "firmware-token layer (community overlay); see catalogs/README.md.",
            "parameters": params}
