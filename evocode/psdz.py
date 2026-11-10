# SPDX-License-Identifier: Apache-2.0
"""Derive the ``sec_security.lic`` keystore password from your own PSdZ install — nothing to type.

PSdZ never stores this password; it computes it from resources that ship in the BMW runtime, and so
do we (reproducing BMW's ``LicenseValidatorCrypto.genHashedPIN`` + ``ResourceParser``):

    password = HEX_UPPER( SHA1( passphrase[pid] ) )

``pid`` is an attribute of your own ``sec_security.lic``. ``passphrase[pid]`` comes from a ``<pplist>``
hidden in two BMW logo PNGs in your PSdZ runtime's ``resource.jar``: ``bmw_logo.png`` carries the
AES-CBC ciphertext, ``bmw_mini_logo.png`` carries the AES key — both steganographically, in the low
two bits of every pixel. This module embeds none of it: point it at your own ``resource.jar``.

The AES/PKCS parts need the ``crypto`` extra (``pip install 'evocode[crypto]'``); the PNG/stego
decode is pure stdlib.
"""
from __future__ import annotations

import base64
import hashlib
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Optional, Tuple

LOGO = "bmw_logo.png"
MINI_LOGO = "bmw_mini_logo.png"


# ---- a minimal 8-bit truecolor PNG decoder (avoids a Pillow dependency for two images) ----

def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def decode_png_rgb8(data: bytes) -> Tuple[int, int, bytes]:
    """Return (width, height, rgb) for an 8-bit, non-interlaced, truecolor-RGB PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, width, height, idat = 8, 0, 0, bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, depth, color, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
            if (depth, color, interlace) != (8, 2, 0):
                raise ValueError("expected an 8-bit non-interlaced RGB PNG (BMW logo format)")
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length                                   # length(4) + type(4) + data + CRC(4)
    raw = zlib.decompress(bytes(idat))
    stride = width * 3
    out, prev, p = bytearray(), bytes(stride), 0
    for _ in range(height):
        ftype = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if ftype == 1:                                       # Sub
            for x in range(3, stride):
                line[x] = (line[x] + line[x - 3]) & 0xFF
        elif ftype == 2:                                     # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:                                     # Average
            for x in range(stride):
                left = line[x - 3] if x >= 3 else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:                                     # Paeth
            for x in range(stride):
                left = line[x - 3] if x >= 3 else 0
                upleft = prev[x - 3] if x >= 3 else 0
                line[x] = (line[x] + _paeth(left, prev[x], upleft)) & 0xFF
        elif ftype != 0:
            raise ValueError("unsupported PNG filter %d" % ftype)
        out += line
        prev = bytes(line)
    return width, height, bytes(out)


# ---- the steganographic payload (BMW ResourceParser.processImg) ----

def extract_payload(png: bytes) -> bytes:
    """Low 2 bits of R,G,B of every pixel (row 0 and column 0 skipped), packed three 2-bit groups to
    one byte (+32 for printable ASCII), until '_'. The ASCII is a hex string; return its bytes."""
    w, h, px = decode_png_rgb8(png)
    tb: list = []
    for row in range(1, h):
        for col in range(1, w):
            o = (row * w + col) * 3
            tb.append(px[o] & 3)
            tb.append(px[o + 1] & 3)
            tb.append(px[o + 2] & 3)
    chars = []
    for i in range(0, len(tb) - 2, 3):
        ch = chr((tb[i] | (tb[i + 1] << 2) | (tb[i + 2] << 4)) + 32)
        if ch == "_":
            break
        chars.append(ch)
    return bytes.fromhex("".join(chars))


def passphrases(logo_png: bytes, mini_logo_png: bytes) -> Dict[str, str]:
    """{pid: passphrase} from the two logo PNGs (mini = AES key, full = AES-CBC ciphertext of pplist)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    ciphertext = extract_payload(logo_png)
    key = extract_payload(mini_logo_png)
    if len(key) not in (16, 24, 32):
        raise ValueError("unexpected AES key length %d from %s" % (len(key), MINI_LOGO))
    dec = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpad = PKCS7(128).unpadder()
    xml = unpad.update(padded) + unpad.finalize()
    root = ET.fromstring(xml)
    pps = {e.attrib["id"]: (e.text or "") for e in root.iter() if e.tag.endswith("passphrase")}
    if not pps:
        raise ValueError("no <passphrase> entries in the decoded pplist")
    return pps


# ---- the .lic wrapper + password ----

def read_logos(resource_jar: Optional[Path], logo: Optional[Path], mini: Optional[Path]) -> Tuple[bytes, bytes]:
    if logo and mini:
        return Path(logo).read_bytes(), Path(mini).read_bytes()
    if resource_jar:
        with zipfile.ZipFile(resource_jar) as z:
            names = z.namelist()

            def grab(leaf: str) -> bytes:
                hit = next((n for n in names if n.rsplit("/", 1)[-1] == leaf), None)
                if hit is None:
                    raise FileNotFoundError("%s not in %s" % (leaf, resource_jar))
                return z.read(hit)

            return grab(LOGO), grab(MINI_LOGO)
    raise ValueError("need --resource-jar (your PSdZ/bin/psdz/resource.jar) or both logo PNGs")


def parse_lic(lic_path: Path) -> Tuple[Optional[str], bytes]:
    """sec_security.lic is ``<... pid="N">BASE64(PKCS#12)</...>``. Return (pid, pkcs12_der)."""
    data = Path(lic_path).read_bytes()
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None, data                                    # already a raw .p12
    return root.attrib.get("pid"), base64.b64decode((root.text or "").strip())


def keystore_der(lic_path: Path) -> bytes:
    return parse_lic(lic_path)[1]


def derive_password(lic_path: Path, *, resource_jar: Optional[Path] = None,
                    logo: Optional[Path] = None, mini: Optional[Path] = None) -> bytes:
    """The PKCS#12 password for sec_security.lic: HEX_UPPER(SHA1(passphrase[pid])), as ASCII bytes."""
    pid, _ = parse_lic(lic_path)
    if pid is None:
        raise ValueError("no pid attribute on %s" % lic_path)
    logo_b, mini_b = read_logos(resource_jar, logo, mini)
    pps = passphrases(logo_b, mini_b)
    if pid not in pps:
        raise KeyError("sec_security.lic pid=%s not among passphrases %s" % (pid, sorted(pps)))
    return hashlib.sha1(pps[pid].encode("ascii")).hexdigest().upper().encode("ascii")
