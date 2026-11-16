#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reshape a community coding-definitions Markdown file into an evocode catalog JSON.

Input is a ``cafd_<id>_definitions.md``: one block per parameter, shaped like

    ### `3006/9/00001111b` — Navigation map variant / regional edition  ·  _high_

    <description>

    | value | meaning |
    |---|---|
    | `0` | No navigation |
    | `1` | ECE (Europe) |

    default `00`· gate: ...· token `NAVI_VARIANTE`· source: firmware-token

Such files (e.g. from vandelayautollc/nbt-evo-toolkit, MIT) are a *reconstructed community overlay*:
the coordinates (datagroup/byte/mask) are factual — they address real coding bytes — while the names
and value labels are reverse-engineered descriptions, NOT shipped BMW data. This tool only reshapes
them into the schema ``evocode decode`` consumes; it adds no knowledge of its own. Always verify a
coordinate against your own unit before writing.

    python3 tools/defs_to_catalog.py path/to/cafd_00001ef6_definitions.md -o catalogs/cafd_00001ef6.full.json \
        --source "vandelayautollc/nbt-evo-toolkit (MIT)"
    python3 tools/defs_to_catalog.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import re

_HEADER = re.compile(r"^###\s+`([0-9A-Fa-f]+)/(\d+)/([01]+)b`\s+—\s+(.+?)(?:\s+·\s+_(\w+)_)?\s*$")
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$")
_TOKEN = re.compile(r"token\s+`([^`]+)`")
_DEFAULT = re.compile(r"default\s+`([0-9A-Fa-f]+)`")
_CAFDHDR = re.compile(r"CAFD\s+([0-9A-Fa-f]+)\s*\(v?([0-9._]+)\)", re.I)


def parse(md: str):
    """Return (cafd, version, [param dict, ...]) parsed from a definitions.md string."""
    lines = md.splitlines()
    cafd = version = ""
    m = _CAFDHDR.search(md)
    if m:
        cafd, version = m.group(1).upper(), m.group(2)
    params = []
    i, n = 0, len(lines)
    while i < n:
        hm = _HEADER.match(lines[i].strip())
        if not hm:
            i += 1
            continue
        dg_hex, byte_s, mask_bin, name, conf = hm.groups()
        mask = int(mask_bin, 2)
        rec = {
            "name": name.strip(),
            "datagroup": "0x%X" % int(dg_hex, 16),
            "byte": int(byte_s),
            "mask": "0x%02X" % mask,
            "shift": (mask & -mask).bit_length() - 1 if mask else 0,
        }
        values, token, default = {}, None, None
        j = i + 1
        while j < n and not _HEADER.match(lines[j].strip()):
            ln = lines[j].strip()
            rm = _ROW.match(ln)
            if rm:
                raw = rm.group(1).strip()
                try:
                    key = int(raw, 0)                 # only numeric enum keys ("0", "255", "0x80")
                except ValueError:
                    key = None
                if key is not None:
                    values[str(key)] = rm.group(2).strip()
            if token is None:
                tm = _TOKEN.search(ln)
                if tm:
                    token = tm.group(1)
            if default is None:
                dm = _DEFAULT.search(ln)
                if dm and len(dm.group(1)) <= 2:      # a single coding byte, not a multi-byte block
                    default = int(dm.group(1), 16)
            j += 1
        if token:
            rec["token"] = token
        if default is not None:
            rec["default"] = default
        if values:
            rec["values"] = values
        if conf:
            rec["confidence"] = conf
        params.append(rec)
        i = j
    return cafd, version, params


def build(md: str, source: str, cafd: str = "", version: str = "") -> dict:
    c, v, params = parse(md)
    return {
        "cafd": cafd or c,
        "version": version or v,
        "note": ("Coordinates (datagroup/byte/mask) address real coding bytes and are factual. "
                 "Parameter names and value labels are a reconstructed community overlay (%s), "
                 "NOT shipped BMW data. Verify a coordinate against your own unit before writing." % source),
        "parameters": params,
    }


_SAMPLE = """# NBT EVO coding definitions — CAFD 00001EF6 (v006.048.013)

### `3006/9/00001111b` — Navigation map variant / regional edition  ·  _high_

Selects the regional navigation map edition.

| value | meaning |
|---|---|
| `0` | No navigation |
| `1` | ECE (Europe) |

default `00`· gate: 609 Professional navigation· token `NAVI_VARIANTE`· source: firmware-token

### `3000/108/00000001b` — A4A remote apps enabled  ·  _med_

Enables remote app execution within the A4A framework.

| value | meaning |
|---|---|
| `0` | Off |
| `1` | On |

default `00`· gate: 6NR Apps· token `A4A_REMOTE_APPS`· source: firmware-token

### `3004/33/11111111b` — Long VIN storage block  ·  _med_

17-byte block; multi-byte default must be ignored.

default `0000000000000000000000000000000000`· source: firmware-trace
"""


def _selftest() -> int:
    cafd, version, params = parse(_SAMPLE)
    assert cafd == "00001EF6" and version == "006.048.013", (cafd, version)
    assert len(params) == 3, params
    nav = params[0]
    assert nav["datagroup"] == "0x3006" and nav["byte"] == 9, nav
    assert nav["mask"] == "0x0F" and nav["shift"] == 0, nav
    assert nav["token"] == "NAVI_VARIANTE" and nav["default"] == 0, nav
    assert nav["values"] == {"0": "No navigation", "1": "ECE (Europe)"}, nav
    assert nav["confidence"] == "high", nav
    a4a = params[1]
    assert a4a["byte"] == 108 and a4a["mask"] == "0x01" and a4a["token"] == "A4A_REMOTE_APPS", a4a
    vin = params[2]
    assert vin["mask"] == "0xFF" and "default" not in vin, vin   # multi-byte default dropped
    assert "values" not in vin and "token" not in vin, vin
    print("selftest OK: parsed %d params" % len(params))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="definitions.md -> evocode catalog JSON")
    ap.add_argument("defs", nargs="?", help="path to cafd_<id>_definitions.md")
    ap.add_argument("-o", "--out", help="output catalog JSON")
    ap.add_argument("--cafd", default="", help="override CAFD id (else read from the md header)")
    ap.add_argument("--version", default="", help="override CAFD version")
    ap.add_argument("--source", default="community firmware-token reconstruction",
                    help="attribution line for the reconstructed names/labels")
    ap.add_argument("--selftest", action="store_true", help="parse a built-in sample and self-check")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.defs or not a.out:
        ap.error("need <defs.md> and -o/--out (or --selftest)")
    doc = build(Path(a.defs).read_text(encoding="utf-8"), a.source, a.cafd, a.version)
    Path(a.out).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %d parameters -> %s (cafd %s v%s)"
          % (len(doc["parameters"]), a.out, doc["cafd"], doc["version"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
