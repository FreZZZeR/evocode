# SPDX-License-Identifier: Apache-2.0
"""Recover your own coding (NCD) or SecurityAccess (L3) key from your own PSdZData — locally.

One chain, keyed by the bootloader (BTLD) id read from the car:

  "ncd" — coding signing key (Codier-Sign), from security/sec_ncdkeys.xml. (Re)signs an NCD.
  "l3"  — Level-3 SecurityAccess key, from security/sec_auth_l3.xml. Unlocks a write session.

Both are wrapped the same way: open the E-SYS PKCS#12 keystore in sec_security.lic with the derived
password (evocode.psdz); RSA-unwrap the AES session key named by the key file's encKeyRef from
sec_keyreference.xml; AES-128-CBC (IV=0) decrypt the BTLD's entry -> a PKCS#8 RSA private key. The
modulus is public (baked into the HU); the private exponent is the secret, written only to a local
file. Needs the `crypto` extra and nothing from BMW is embedded here.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple

from . import psdz

KINDS = {
    "ncd": {"file": "sec_ncdkeys.xml", "elem": "NCodSigKey", "use": "coding signature — (re)sign an NCD"},
    "l3": {"file": "sec_auth_l3.xml", "elem": "AuthenticationKey", "use": "SecurityAccess — write unlock"},
}
_DIGESTS = {"MD5": "md5", "SHA-256": "sha256", "SHA256": "sha256", "SHA-1": "sha1"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _bytes_of(s: str) -> bytes:
    s = re.sub(r"\s+", "", s or "")
    if re.fullmatch(r"[0-9a-fA-F]+", s) and len(s) % 2 == 0:
        return bytes.fromhex(s)
    return base64.b64decode(s)


def _unwrap_session_key(keyref_path: Path, esys_priv, ref_name: Optional[str]) -> bytes:
    """RSA-unwrap the AES session key. Select by the key file's exact encKeyRef: every SessionKey is
    wrapped to the same E-SYS key, so any of them 'decrypts' — picking the wrong one yields garbage."""
    from cryptography.hazmat.primitives.asymmetric import padding
    root = ET.parse(keyref_path).getroot()
    entries: list = []
    for sk in root.iter():
        if _local(sk.tag) != "SessionKey":
            continue
        ref = next(((c.text or "").strip() for c in sk.iter() if _local(c.tag).lower() == "reference"), None)
        kd = next((c.text for c in sk.iter() if _local(c.tag).lower() == "keydata" and (c.text or "").strip()), None)
        if kd:
            entries.append((ref, kd))

    def unwrap(text: str) -> bytes:
        k = esys_priv.decrypt(_bytes_of(text), padding.PKCS1v15())
        return k if len(k) in (16, 24, 32) else k[-16:]

    if ref_name:
        for r, t in entries:
            if r == ref_name:
                return unwrap(t)
        for r, t in entries:
            if r and ref_name in r:
                return unwrap(t)
    for _r, t in entries:                                    # last resort: first that unwraps sanely
        try:
            return unwrap(t)
        except Exception:                                    # noqa: BLE001
            continue
    raise KeyError("no session key could be unwrapped from %s" % keyref_path)


def _find_btld_entry(sec_path: Path, btld: str, elem: str) -> Tuple[bytes, dict]:
    root = ET.parse(sec_path).getroot()
    norm = btld.lower().lstrip("0") or "0"
    for el in root.iter():
        if _local(el.tag) != elem:
            continue
        text = ET.tostring(el, encoding="unicode").lower()
        if ("btld-" + btld.lower()) in text or re.search(r"\b0*" + norm + r"\b", text):
            kd = next((c for c in el.iter() if _local(c.tag).lower() in ("keydata", "key", "privatekey")), None)
            if kd is not None and (kd.text or "").strip():
                return _bytes_of(kd.text), kd.attrib
    raise KeyError("no %s entry for BTLD %s in %s" % (elem, btld, sec_path))


def recover(psdzdata: Path, btld: str, kind: str, keystore_password: bytes) -> dict:
    """Recover the key dict (schema matches the shipped ncd_key.json / l3_key.json)."""
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % sorted(KINDS))
    from cryptography.hazmat.primitives.serialization import load_der_private_key, pkcs12
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    spec = KINDS[kind]
    sec = Path(psdzdata) / "security"
    lic, keyref, src = sec / "sec_security.lic", sec / "sec_keyreference.xml", sec / spec["file"]
    for p in (lic, keyref, src):
        if not p.exists():
            raise FileNotFoundError("expected %s — is --psdzdata the psdzdata/ root?" % p)

    esys_priv, _, _ = pkcs12.load_key_and_certificates(psdz.keystore_der(lic), keystore_password)
    if esys_priv is None:
        raise ValueError("no private key in sec_security.lic (derived keystore password rejected)")
    ref_name = ET.parse(src).getroot().get("encKeyRef")
    aes_key = _unwrap_session_key(keyref, esys_priv, ref_name)

    body, attrib = _find_btld_entry(src, btld, spec["elem"])
    dec = Cipher(algorithms.AES(aes_key), modes.CBC(b"\x00" * 16)).decryptor()
    pt = dec.update(body) + dec.finalize()
    if pt and pt[-1] <= 16:                                  # PKCS#5 unpad
        pt = pt[:-pt[-1]]
    priv = load_der_private_key(pt, password=None)
    nums = priv.private_numbers()
    pub = nums.public_numbers
    dattr = next((v for k, v in attrib.items() if _local(k).lower() == "digestalg"), None)
    return {
        "btld": btld.upper(),
        "kind": kind,
        "use": spec["use"],
        "scheme": next((v for k, v in attrib.items() if _local(k).lower() == "signaturescheme"), "BMWSigVerify"),
        "digest": _DIGESTS.get((dattr or "").upper().replace(" ", "-"), "md5"),
        "test_key": str(attrib.get("testKey", "")).lower() == "true",
        "public_exponent": pub.e,
        "modulus_hex": "%x" % pub.n,
        "private_exponent_hex": "%x" % nums.d,
    }


def recover_from_install(psdzdata: Path, btld: str, kind: str, *, resource_jar: Optional[Path] = None,
                         logo: Optional[Path] = None, mini: Optional[Path] = None) -> dict:
    """Derive the keystore password from the PSdZ resources, then recover the key."""
    password = psdz.derive_password(Path(psdzdata) / "security" / "sec_security.lic",
                                    resource_jar=resource_jar, logo=logo, mini=mini)
    return recover(psdzdata, btld, kind, password)
