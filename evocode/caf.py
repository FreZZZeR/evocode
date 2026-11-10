# SPDX-License-Identifier: Apache-2.0
"""Decrypt a BMW CAFD ``.caf`` into its plaintext CAFD XML.

A ``.caf`` is an XML wrapper::

    <caf isEncrypted="true" isCompressed="true"><encryptedData>BASE64(CMS)</encryptedData></caf>

The inner CMS is a PKCS#7 EnvelopedData encrypted to the **Codier-Encrypt** certificate, whose RSA
private key lives (alongside the E-SYS key) in your ``sec_security.lic`` keystore. The decrypted
payload is **gzip**-compressed CAFD XML. So: recover the Codier-Encrypt key (derived keystore
password, see :mod:`evocode.psdz`), CMS-decrypt, gunzip.

Needs the ``crypto`` extra and an ``openssl`` binary (OpenSSL 3.x): cryptography exposes only one of
the keystore's two private keys and has no EnvelopedData-decrypt API, so the second key and the CMS
decrypt go through ``openssl``. Everything else is pure stdlib.
"""
from __future__ import annotations

import base64
import gzip
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from . import psdz


def _ln(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def cms_from_caf(caf_path) -> bytes:
    """The DER CMS EnvelopedData from a .caf's <encryptedData> (or the file itself if already CMS)."""
    data = Path(caf_path).read_bytes()
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return data
    ed = next((e for e in root.iter() if _ln(e.tag) == "encryptedData"), None)
    if ed is None:
        raise ValueError("%s is not an encrypted .caf (no <encryptedData>)" % caf_path)
    return base64.b64decode("".join((ed.text or "").split()))


def decrypt_caf(caf_path, psdzdata, *, resource_jar=None, logo=None, mini=None,
                recipient="Codier-Encrypt") -> bytes:
    """Return the plaintext CAFD XML bytes for an encrypted ``.caf``."""
    from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key, pkcs12

    sec = Path(psdzdata) / "security"
    lic = sec / "sec_security.lic"
    password = psdz.derive_password(lic, resource_jar=resource_jar, logo=logo, mini=mini)
    der = psdz.keystore_der(lic)
    _key, _cert, chain = pkcs12.load_key_and_certificates(der, password)
    recips = [c for c in (chain or []) if recipient in c.subject.rfc4514_string()]
    if not recips:
        raise KeyError("recipient cert %r not found in sec_security.lic" % recipient)
    n = recips[0].public_key().public_numbers().n

    tmp = tempfile.mkdtemp(prefix="evocode-caf-")
    try:
        p12 = Path(tmp, "ks.p12"); p12.write_bytes(der)
        cms = Path(tmp, "cms.der"); cms.write_bytes(cms_from_caf(caf_path))
        rcert = Path(tmp, "recip.pem"); rcert.write_bytes(recips[0].public_bytes(Encoding.PEM))
        dump = subprocess.run(["openssl", "pkcs12", "-legacy", "-in", str(p12),
                               "-passin", "pass:" + password.decode(), "-nodes"],
                              capture_output=True, text=True).stdout
        rkey = None
        for block in re.findall(r"-----BEGIN PRIVATE KEY-----.*?-----END PRIVATE KEY-----", dump, re.S):
            if load_pem_private_key(block.encode(), password=None).public_key().public_numbers().n == n:
                rkey = Path(tmp, "recip_key.pem"); rkey.write_text(block)
                break
        if rkey is None:
            raise KeyError("recipient private key (%s) not found in keystore" % recipient)
        out = subprocess.run(["openssl", "cms", "-decrypt", "-inform", "DER", "-in", str(cms),
                              "-inkey", str(rkey), "-recip", str(rcert)], capture_output=True)
        if out.returncode != 0:
            raise RuntimeError("openssl cms decrypt failed: %s" % out.stderr.decode()[:200])
        payload = out.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
