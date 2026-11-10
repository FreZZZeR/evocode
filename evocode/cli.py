# SPDX-License-Identifier: Apache-2.0
"""evocode — command-line interface.

Reads are free; ``write`` is gated and defaults to a dry run. See ``evocode <cmd> --help``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Tuple

from . import __version__, coding, consent, l3, srec
from .hsfz import Hsfz, TGT_HU
from .uds import Uds, UdsError

# coding write choreography constants (see docs/protocol.md)
SESSION_EXTENDED = 0x03
SESSION_CODING = 0x41
SA_SEED_LEVEL = 0x01
SA_KEY_LEVEL = 0x02
RID_CHECK_CODING = 0x0F01
DID_CPS = 0x37FE
CODING_DGS = range(0x3000, 0x3011)      # user datagroups + CAF_ID + signature


def _parse_set(s: str) -> Tuple[int, int, int, int, int]:
    p = s.split(",")
    dg, off, val = int(p[0], 0), int(p[1], 0), int(p[2], 0)
    mask = int(p[3], 0) if len(p) > 3 else 0xFF
    shift = int(p[4], 0) if len(p) > 4 else 0
    return dg, off, val, mask, shift


def _write_order(mem: srec.Mem, scheme: coding.Scheme):
    """Datagroups present in mem, signature datagroup LAST, with their bytes."""
    present = sorted({addr >> 8 for addr in mem})
    order = [dg for dg in present if dg != scheme.sig_dg]
    if scheme.sig_dg in present:
        order.append(scheme.sig_dg)
    return order, srec.pages(mem, order)


# ---- commands ------------------------------------------------------------------

def cmd_identify(a) -> int:
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        vin = u.read_vin()
        svk = u.read_svk()
    print("VIN : %s" % vin)
    print("BTLD: %s" % (svk.btld or "?"))
    for c in svk.cafds:
        print("CAFD: %s" % c)
    return 0


def cmd_read(a) -> int:
    mem: srec.Mem = {}
    chunks = []
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        vin = u.read_vin()
        for dg in CODING_DGS:
            try:
                page = u.read_did(dg)
            except UdsError:
                continue                       # datagroup absent on this variant
            base = dg << 8
            for i, b in enumerate(page):
                mem[base + i] = b
            chunks.append((base, len(page), 3))           # S2: 24-bit address, BMW's convention
    meta = {"header": "S0030000FC", "chunks": chunks,
            "trailer": [srec.count_record(len(chunks)), "S804000000FB"]}
    Path(a.out).write_text(srec.emit(mem, meta))
    print("VIN %s: backed up %d datagroups -> %s" % (vin, len(chunks), a.out))
    print("Keep this file: writing it back is a clean, already-signed revert.")
    return 0


def cmd_verify(a) -> int:
    mem, _ = srec.parse(Path(a.ncd).read_text())
    ok = coding.verify(mem, coding.load_key(a.key), coding.SCHEMES[a.scheme])
    print(json.dumps({"scheme": a.scheme, "signature_valid": ok}, indent=2))
    return 0 if ok else 1


def cmd_sign(a) -> int:
    mem, meta = srec.parse(Path(a.ncd_in).read_text())
    key = coding.load_key(a.key)
    scheme = coding.SCHEMES[a.scheme]
    for s in a.set:
        srec.set_byte(mem, *_parse_set(s))
    sig = coding.resign(mem, key, scheme)
    if not coding.verify(mem, key, scheme):
        print("ERROR: self-verify failed after signing", file=sys.stderr)
        return 1
    Path(a.ncd_out).write_text(srec.emit(mem, meta))
    print(json.dumps({"edits": len(a.set), "signature": sig.hex(), "out": a.ncd_out}, indent=2))
    return 0


def cmd_decode(a) -> int:
    from . import catalog
    mem, _ = srec.parse(Path(a.ncd).read_text())
    params = catalog.load(a.catalog)
    want = set(a.only) if a.only else None
    shown = 0
    for p, raw, label in catalog.decode(mem, params):
        if want and p.name not in want and (p.token or "") not in want:
            continue
        lab = "  = %s" % label if label else ""
        dflt = "  (default %s)" % p.default if p.default is not None else ""
        chg = "  [non-default]" if p.default is not None and raw != p.default else ""
        print("%-32s dg=0x%04X byte=%-3d mask=0x%02X  raw=%d%s%s%s"
              % (p.name, p.dg, p.byte, p.mask, raw, lab, dflt, chg))
        shown += 1
    if not shown:
        print("(no catalog parameters found in this NCD)")
    return 0


def cmd_write(a) -> int:
    mem, _ = srec.parse(Path(a.ncd).read_text())
    key = coding.load_key(a.key)
    scheme = coding.SCHEMES[a.scheme]
    if not coding.verify(mem, key, scheme):
        print("ERROR: NCD signature does not verify locally. Re-sign with `evocode sign` first.", file=sys.stderr)
        return 1
    print("local signature check: OK")
    order, pages = _write_order(mem, scheme)

    if not a.commit:
        print("\n-- DRY RUN -- would send (no bytes written):")
        print("  10 %02X ; 10 %02X            enter extended + coding session" % (SESSION_EXTENDED, SESSION_CODING))
        print("  27 %02X -> seed ; 27 %02X <key>   SecurityAccess L3" % (SA_SEED_LEVEL, SA_KEY_LEVEL))
        for dg in order:
            print("  2E %02X %02X  (%d bytes)%s" % (dg >> 8, dg & 0xFF, len(pages[dg]),
                  "   <- signature LAST" if dg == scheme.sig_dg else ""))
        print("  31 01 %02X %02X  CheckCodingSignature ; 2E 37 FE CPS ; 11 01 reset"
              % (RID_CHECK_CODING >> 8, RID_CHECK_CODING & 0xFF))
        print("\nRehearsal only. Re-run with --commit and --l3-key to write.")
        return 0

    if not a.l3_key:
        print("ERROR: --commit needs --l3-key (your recovered L3 SecurityAccess key)", file=sys.stderr)
        return 2
    consent.owned_vin()                                  # fail early if env not set
    l3_key = json.loads(Path(a.l3_key).read_text())
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        vin = u.read_vin()
        consent.assert_owned(vin)                        # hard stop if not the car you own
        print("connected VIN %s confirmed" % vin)
        cps_now = u.read_did(DID_CPS)
        u.session(SESSION_EXTENDED)
        u.session(SESSION_CODING)
        seed = u.request_seed(SA_SEED_LEVEL, a.user_id)
        u.send_key(SA_KEY_LEVEL, l3.sign_seed(seed, l3_key, user_id=a.user_id))
        print("SecurityAccess granted")
        for dg in order:
            u.write_did(dg, pages[dg])
            print("  wrote 0x%04X (%d bytes)" % (dg, len(pages[dg])))
        resp = u.routine(0x01, RID_CHECK_CODING)
        status = resp[4:]                                # 71 01 0F 01 <status...>
        if status and any(status):
            print("ABORT: CheckCodingSignature not OK (%s). CPS not written, no reset. "
                  "Read back and decide; revert = write your backup NCD." % resp.hex(), file=sys.stderr)
            return 3
        if a.cps:
            cps = bytes.fromhex(a.cps)
        elif cps_now and all(b == 0xFF for b in cps_now):
            cps = vin[-7:].encode("ascii")               # NBT EVO CPS = last 7 of VIN; restore if erased
            print("CPS was erased; restoring VIN-short: %s" % cps.decode())
        else:
            cps = cps_now
        u.write_did(DID_CPS, cps)
        print("CPS read-back: %s" % u.read_did(DID_CPS).hex())
        u.reset(0x01)
        print("reset issued; the HU reboots and re-verifies the new coding")
    print("\nDone. Read it back and diff, and watch the HMI come up. Revert = `evocode write --ncd <backup>`.")
    return 0


def cmd_recover_key(a) -> int:
    import warnings
    if not a.psdzdata:
        print("set --psdzdata (or NBTEVO_PSDZDATA) to your extracted psdzdata/ root", file=sys.stderr)
        return 2
    consent.owned_vin()                                      # owner action (recovering your own key)
    warnings.filterwarnings("ignore", message=".*PKCS#12.*")
    try:
        from . import keys
        key = keys.recover_from_install(a.psdzdata, a.btld, a.kind,
                                        resource_jar=a.resource_jar, logo=a.bmw_logo, mini=a.bmw_mini_logo)
    except ImportError:
        print("recover-key needs the crypto extra:  pip install 'evocode[crypto]'", file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print("recovery failed: %s" % exc, file=sys.stderr)
        return 1
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(key, indent=2))
    try:
        out.chmod(0o600)
    except OSError:
        pass
    warn = "  [TEST KEY — not valid on a customer ECU]" if key["test_key"] else ""
    print("recovered %s key for BTLD %s (%s/%s, e=%d)%s"
          % (key["kind"].upper(), key["btld"], key["scheme"], key["digest"], key["public_exponent"], warn))
    print("  modulus (public): %s…" % key["modulus_hex"][:24])
    print("  -> %s  (keep the private exponent secret; gitignore it)" % out)
    if a.kind == "ncd":
        print("  verify it:  evocode verify --ncd <your backup>.ncd --key %s" % out)
    return 0


def cmd_build_catalog(a) -> int:
    import re
    if not a.psdzdata:
        print("set --psdzdata (or NBTEVO_PSDZDATA) to your extracted psdzdata/ root", file=sys.stderr)
        return 2
    consent.owned_vin()                                      # owner action (decrypts with your key)
    try:
        from . import caf, catalog
        xml = caf.decrypt_caf(a.caf, a.psdzdata, resource_jar=a.resource_jar,
                              logo=a.bmw_logo, mini=a.bmw_mini_logo)
    except ImportError:
        print("build-catalog needs the crypto extra and openssl:  pip install 'evocode[crypto]'", file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError, RuntimeError, OSError) as exc:
        print("build-catalog failed: %s" % exc, file=sys.stderr)
        return 1
    doc = catalog.build_skeleton(xml)
    m = re.search(r"cafd_([0-9a-fA-F]+)\.caf\.([0-9_]+)", Path(a.caf).name)
    if m:
        doc["cafd"], doc["version"] = m.group(1).upper(), m.group(2).replace("_", ".")
    Path(a.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print("CAFD %s v%s: wrote %d coordinates -> %s"
          % (doc.get("cafd") or "?", doc.get("version") or "?", len(doc["parameters"]), a.out))
    print("  coordinates/masks/defaults are factual; parameter NAMES are blank — add them from the")
    print("  firmware-token layer / community (catalogs/README.md).")
    return 0


# ---- FSC (owner-CA activations) ------------------------------------------------

def _fsc_modulus(a) -> int:
    if getattr(a, "key", None):
        return int(json.loads(Path(a.key).read_text())["n_hex"], 16)
    if getattr(a, "blobb", None):
        return int.from_bytes(Path(a.blobb).read_bytes(), "little")
    raise SystemExit("need --key (owner key JSON) or --blobb (128-byte LE modulus)")


def cmd_fsc_keygen(a) -> int:
    from . import fsc as F
    key = F.keygen(a.bits)
    Path(a.out).write_text(json.dumps(key, indent=2))
    try:
        Path(a.out).chmod(0o600)
    except OSError:
        pass
    n = int(key["n_hex"], 16)
    if a.blobb:
        Path(a.blobb).write_bytes(F.blobB_le(n))
    print("owner anchor: e=3, %d-bit, fp %s  -> %s (PRIVATE — your FSC root of trust)"
          % (key["bits"], F.fingerprint(n), a.out))
    return 0


def cmd_fsc_mint(a) -> int:
    from . import fsc as F
    key = json.loads(Path(a.key).read_text())
    n, d = int(key["n_hex"], 16), int(key["d_hex"], 16)
    tok = F.mint(n, d, int(a.appno, 0), upgrade_idx=a.upgrade_index, vin=(a.vin.encode() if a.vin else None))
    if not F.verify(tok, n)[0]:
        print("ERROR: minted FSC failed self-verify", file=sys.stderr)
        return 1
    Path(a.out).write_bytes(tok)
    print("minted AppNo %s (%d B) -> %s; self-verify OK" % (a.appno, len(tok), a.out))
    return 0


def cmd_fsc_verify(a) -> int:
    from . import fsc as F
    ok, msg = F.verify(Path(a.fsc).read_bytes(), _fsc_modulus(a))
    print(json.dumps({"accepted": ok, "detail": msg}, indent=2))
    return 0 if ok else 1


def cmd_fsc_parse(a) -> int:
    from . import fsc as F
    print(json.dumps(F.parse(Path(a.fsc).read_bytes()), indent=2))
    return 0


def cmd_fsc_fingerprint(a) -> int:
    from . import fsc as F
    n = _fsc_modulus(a)
    print("%s  (e=3, %d-bit)" % (F.fingerprint(n), n.bit_length()))
    return 0


def _fsc_anchor(spec: str):
    from . import fsc as F
    label, _, path = spec.partition("=")
    if not path:
        label, path = "", label
    raw = Path(path).read_bytes()
    try:
        n = int(json.loads(raw.decode())["n_hex"], 16)
    except (ValueError, UnicodeDecodeError, KeyError):
        if len(raw) != 128:
            raise SystemExit("%s: not key JSON and not a 128-byte blobB" % path)
        n = int.from_bytes(raw, "little")
    return (label or path), n, F.fingerprint(n)


def cmd_fsc_whosigned(a) -> int:
    from . import fsc as F
    toks = [Path(f).read_bytes() for f in a.fsc]
    for f, t in zip(a.fsc, toks):
        b = F.parse(t)
        print("  %s: AppNo %s, VIN %s" % (f, b["appno"], b["vin"]))
    matched = None
    for spec in a.anchor:
        label, n, fp = _fsc_anchor(spec)
        res = [F.verify(t, n)[0] for t in toks]
        tag = "ALL" if all(res) else ("some" if any(res) else "none")
        print("  [%-4s] %s  (fp %s)" % (tag, label, fp))
        if all(res) and matched is None:
            matched = (label, n)
    if matched:
        print("==> signed by %s (fp %s). That is the installed anchor." % (matched[0], F.fingerprint(matched[1])))
        return 0
    if not a.recover:
        print("==> no candidate anchor verifies all FSCs; add --anchor or pass --recover")
        return 1
    n = F.recover_modulus(toks)
    if all(F.verify(t, n)[0] for t in toks):
        print("==> signed by an UNKNOWN anchor (not a candidate): fp %s, %d-bit.\n"
              "    Someone else set this unit's trust; your overwrite would replace it." % (F.fingerprint(n), n.bit_length()))
        return 0
    print("==> recovery inconclusive — FSCs may not share one anchor", file=sys.stderr)
    return 2


def cmd_fsc_find_blobb(a) -> int:
    from . import fsc as F
    off, n = F.find_blobb(Path(a.nbtcarhu).read_bytes())
    print("blobB @ file offset 0x%06X  (e=3, %d-bit, fp %s)" % (off, n.bit_length(), F.fingerprint(n)))
    if a.save_blobb:
        Path(a.save_blobb).write_bytes(F.blobB_le(n))
    return 0


def cmd_fsc_patch_blobb(a) -> int:
    from . import fsc as F
    data = Path(a.nbtcarhu).read_bytes()
    off = int(a.offset, 0) if a.offset else F.find_blobb(data)[0]
    old = int.from_bytes(data[off:off + 128], "little")
    key = json.loads(Path(a.key).read_text())
    n = int(key["n_hex"], 16)
    if a.backup:
        Path(a.backup).write_bytes(F.blobB_le(old))
    Path(a.out).write_bytes(F.patch_blobb(data, off, n))
    print("patched blobB @0x%06X:  %s -> %s  -> %s" % (off, F.fingerprint(old), F.fingerprint(n), a.out))
    print("  length-preserving; keep the backup to revert. Installing the patched NBTCarHU on the unit")
    print("  is the flash/file-replace step (brick-risk) — see the FSC runbook.")
    return 0


def cmd_fsc_apply(a) -> int:
    import glob
    from . import fsc as F
    store_rco = int(a.store_rco, 0) if a.store_rco else F.RCO_STORE
    files = sorted(glob.glob(str(Path(a.fsc_dir) / "*.fsc")))
    toks = {F.parse(Path(f).read_bytes())["appno"]: Path(f).read_bytes() for f in files}
    if not toks:
        print("no .fsc files in %s (mint some first)" % a.fsc_dir, file=sys.stderr)
        return 2
    if not a.commit:
        print("-- DRY RUN -- would send (no bytes written); needs the installed anchor to be YOUR key:")
        print("  10 03 ; 27 01 -> seed ; 27 02 <L3 key>")
        for app, t in toks.items():
            print("  31 01 %04X %02X <SWID %s + %s FSC %dB>   store %s"
                  % (F.SWT_RID, store_rco, F.swid_of(t).hex(), "base32" if a.base32 else "raw", len(t), app))
        print("  then read-back (RCO 0x%02X) + 11 01 reset. Re-run with --host, --l3-key and --commit." % F.RCO_READ)
        return 0
    if not (a.host and a.l3_key):
        print("ERROR: --commit needs --host and --l3-key", file=sys.stderr)
        return 2
    consent.owned_vin()
    l3_key = json.loads(Path(a.l3_key).read_text())
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        consent.assert_owned(u.read_vin())
        u.session(0x03)
        seed = u.request_seed(0x01, 0x00000000)
        u.send_key(0x02, l3.sign_seed(seed, l3_key, user_id=0x00000000))
        print("SecurityAccess unlocked")
        for app, t in toks.items():
            try:
                u.routine(0x01, F.SWT_RID, bytes([store_rco]) + F.store_payload(t, a.base32))
                print("  stored %s OK" % app)
            except UdsError as e:
                print("  stored %s FAILED: %s" % (app, e))
        print("read-back:")
        for app, t in toks.items():
            try:
                r = u.routine(0x01, F.SWT_RID, bytes([F.RCO_READ]) + F.swid_of(t))
                print("  %s  %s" % (app, r[4:].hex() or "(ok)"))
            except UdsError as e:
                print("  %s  %s" % (app, e))
        u.reset(0x01)
    print("done; reboot + verify features. Revert = restore stock blobB (your --backup), or `fsc disable`.")
    return 0


def cmd_fsc_from_log(a) -> int:
    import re
    from . import fsc as F
    toks = {}
    for line in Path(a.log).read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("<--"):
            hp = line[3:].strip()
            if re.fullmatch(r"([0-9A-Fa-f]{2}\s+)*[0-9A-Fa-f]{2}", hp or ""):
                b = bytes.fromhex(hp.replace(" ", ""))
                if len(b) >= 180:
                    toks.setdefault(F.parse(b)["appno"], b[:188])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for app, t in toks.items():
        (out / ("fsc_%s.fsc" % app)).write_bytes(t)
    print("extracted %d FSC(s) -> %s/" % (len(toks), out))
    return 0


def cmd_fsc_read(a) -> int:
    from . import fsc as F
    appnos = [int(x, 0) for x in a.appno]
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        try:
            u.session(0x03)
        except (UdsError, RuntimeError):
            pass                                             # read works in the default session too
        for app in appnos:
            try:
                r = u.routine(0x01, F.SWT_RID, bytes([F.RCO_READ]) + F.swid(app, a.upgrade_index))
                print("  0x%04X  present      %s" % (app, r[4:].hex() or "(ok)"))
            except UdsError as e:
                print("  0x%04X  not present / %s" % (app, e))
    return 0


def cmd_fsc_disable(a) -> int:
    from . import fsc as F
    appnos = [int(x, 0) for x in a.appno]
    if not a.commit:
        print("-- DRY RUN -- would send (no bytes written):")
        print("  10 03 ; 27 01 -> seed ; 27 02 <L3 key>")
        for app in appnos:
            print("  31 01 %04X %02X %s   disable 0x%04X"
                  % (F.SWT_RID, F.RCO_CANCEL, F.swid(app, a.upgrade_index).hex(), app))
        print("  then 11 01 reset. Re-run with --host, --l3-key and --commit.")
        return 0
    if not (a.host and a.l3_key):
        print("ERROR: --commit needs --host and --l3-key", file=sys.stderr)
        return 2
    consent.owned_vin()
    l3_key = json.loads(Path(a.l3_key).read_text())
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        consent.assert_owned(u.read_vin())
        u.session(0x03)
        seed = u.request_seed(0x01, 0x00000000)
        u.send_key(0x02, l3.sign_seed(seed, l3_key, user_id=0x00000000))
        print("SecurityAccess unlocked")
        for app in appnos:
            try:
                u.routine(0x01, F.SWT_RID, bytes([F.RCO_CANCEL]) + F.swid(app, a.upgrade_index))
                print("  disabled 0x%04X OK" % app)
            except UdsError as e:
                print("  disable 0x%04X FAILED: %s" % (app, e))
        u.reset(0x01)
    print("done; reboot + verify. Re-enable = `fsc apply` the minted FSC again.")
    return 0


# ---- root (OPT_DEBUG) ----------------------------------------------------------

def cmd_root_status(a) -> int:
    from . import root
    ports = root.check_ports(a.host)
    any_open = any(ports.values())
    for p, ok in sorted(ports.items()):
        print("  port %-5d  %s" % (p, "OPEN" if ok else "closed"))
    if any_open:
        print("OPT_DEBUG appears ENABLED (dev ports open)")
    else:
        print("OPT_DEBUG appears DISABLED (dev ports closed)")
    return 0


def cmd_root_prepare(a) -> int:
    from . import root
    cfg = Path(a.starter_cfg).read_text(encoding="latin-1")
    state = root.is_enabled(cfg)
    if state is None:
        print("ERROR: OPT_DEBUG service not found in %s" % a.starter_cfg, file=sys.stderr)
        return 1
    if a.revert:
        patched = root.unpatch(cfg)
        label = "RUN→STOP"
    else:
        patched = root.patch(cfg)
        label = "STOP→RUN"
    Path(a.out).write_text(patched, encoding="latin-1")
    print("OPT_DEBUG %s  %s -> %s" % (label, a.starter_cfg, a.out))
    print("  stock file is your revert — keep it safe.")
    return 0


def _root_flash(a, cfg_data: bytes, label: str) -> int:
    from . import root, swdl
    img = swdl.build_container(cfg_data, root.STARTER_PATH, root.STARTER_NAME)
    btld = int(a.btld, 16)
    tgt, _nm, is_live = swdl.container_target(img)

    if not a.commit:
        print("-- DRY RUN -- %s" % label)
        print("container : %d bytes -> %s  [%s]" % (len(img), tgt, "LIVE-DIRECT" if is_live else "STAGING"))
        print("  planned: enter bolo -> L3 auth -> SWDL transferData -> finalize -> reboot")
        print("  LIVE-DIRECT: writes starter.cfg in place; goes live next boot.")
        print("  A bad/wrong-version cfg fails the next boot — keep the stock for --revert.")
        print("  Run detached (nohup/setsid) so an SSH drop can't tear the write.")
        print("\nRe-run with --commit to flash.")
        return 0

    if not a.l3_key:
        print("ERROR: --commit needs --l3-key (your recovered L3 SecurityAccess key)", file=sys.stderr)
        return 2
    consent.owned_vin()                                  # fail early if env not set
    l3_key = json.loads(Path(a.l3_key).read_text())
    print("COMMIT: %s" % label)
    with Hsfz(a.host) as h:
        u = Uds(h, a.target)
        vin = u.read_vin()
        consent.assert_owned(vin)
        print("VIN %s confirmed" % vin)

    h = Hsfz(a.host)
    wrote = False
    try:
        wrote = swdl.apply_flash(h, img, target=a.target, reset_timeout=a.reset_timeout,
                                 key=l3_key, btld=btld, log=print)
    finally:
        try:
            h.stop_tester_present()
        except Exception:
            pass
        try:
            swdl.teardown(h, target=a.target, log=print)
        except Exception as e:
            print("  [finalize warn] %s" % e)
        try:
            h.close()
        except Exception:
            pass
    return 0 if wrote else 1


def cmd_root_enable(a) -> int:
    from . import root
    cfg = Path(a.starter_cfg).read_text(encoding="latin-1")
    state = root.is_enabled(cfg)
    if state is None:
        print("ERROR: OPT_DEBUG not found in %s" % a.starter_cfg, file=sys.stderr)
        return 1
    if state is True:
        print("starter.cfg already has OPT_DEBUG=RUN — using as-is")
        patched_data = cfg.encode("latin-1")
    else:
        patched_data = root.patch(cfg).encode("latin-1")
    return _root_flash(a, patched_data, "OPT_DEBUG enable (STOP→RUN)")


def cmd_root_revert(a) -> int:
    stock_data = Path(a.stock).read_bytes()
    return _root_flash(a, stock_data, "OPT_DEBUG revert (stock starter.cfg)")


# ---- parser --------------------------------------------------------------------

def _target(x: str) -> int:
    return int(x, 0)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="evocode", description=__doc__)
    ap.add_argument("--version", action="version", version="evocode %s" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def host_target(p):
        p.add_argument("--host", required=True, help="HSFZ endpoint IP")
        p.add_argument("--target", type=_target, default=TGT_HU, help="ECU diag address (default 0x63)")

    p = sub.add_parser("identify", help="read SVK: BTLD, CAFD, VIN"); host_target(p); p.set_defaults(fn=cmd_identify)

    p = sub.add_parser("read", help="back up live coding to an NCD"); host_target(p)
    p.add_argument("-o", "--out", required=True); p.set_defaults(fn=cmd_read)

    p = sub.add_parser("verify", help="check an NCD's signature offline")
    p.add_argument("--ncd", required=True); p.add_argument("--key", required=True)
    p.add_argument("--scheme", default=coding.DEFAULT_SCHEME, choices=sorted(coding.SCHEMES))
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("sign", help="edit + re-sign an NCD offline")
    p.add_argument("ncd_in"); p.add_argument("ncd_out"); p.add_argument("--key", required=True)
    p.add_argument("--scheme", default=coding.DEFAULT_SCHEME, choices=sorted(coding.SCHEMES))
    p.add_argument("--set", action="append", default=[], metavar="DG,OFF,VAL[,MASK,SHIFT]",
                   help="edit a coding byte, e.g. 0x3000,107,1,0x80,7")
    p.set_defaults(fn=cmd_sign)

    p = sub.add_parser("decode", help="show current values of an NCD against a catalog")
    p.add_argument("--ncd", required=True)
    p.add_argument("--catalog", required=True, help="per-CAFD catalog JSON (see catalogs/)")
    p.add_argument("--only", nargs="*", help="limit to these parameter names/tokens")
    p.set_defaults(fn=cmd_decode)

    p = sub.add_parser("write", help="write a signed NCD (gated; dry-run unless --commit)"); host_target(p)
    p.add_argument("--ncd", required=True); p.add_argument("--key", required=True)
    p.add_argument("--scheme", default=coding.DEFAULT_SCHEME, choices=sorted(coding.SCHEMES))
    p.add_argument("--l3-key", help="your recovered L3 SecurityAccess key (required for --commit)")
    p.add_argument("--user-id", type=_target, default=0x00000000, help="testerId for seed+key (default 0)")
    p.add_argument("--cps", help="CPS (0x37FE) value as hex; default keep current / restore VIN-short if erased")
    p.add_argument("--commit", action="store_true", help="actually write (gated); omit to rehearse")
    p.set_defaults(fn=cmd_write)

    p = sub.add_parser("recover-key", help="recover your NCD/L3 signing key from your own PSdZData")
    p.add_argument("--btld", required=True, help="bootloader id, e.g. 00001FFD (from `evocode identify`)")
    p.add_argument("--kind", default="ncd", choices=["ncd", "l3"], help="ncd = coding signing · l3 = write unlock")
    p.add_argument("--psdzdata", default=os.environ.get("NBTEVO_PSDZDATA"), help="your extracted psdzdata/ root")
    p.add_argument("--resource-jar", default=os.environ.get("NBTEVO_PSDZ_RESOURCE_JAR"),
                   help="your PSdZ/bin/psdz/resource.jar (holds the logo PNGs; NOT inside psdzdata/)")
    p.add_argument("--bmw-logo", help="instead of --resource-jar: your own bmw_logo.png")
    p.add_argument("--bmw-mini-logo", help="…and your own bmw_mini_logo.png")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_recover_key)
    p = sub.add_parser("build-catalog", help="build a catalog skeleton from your own encrypted CAFD .caf")
    p.add_argument("--caf", required=True, help="your cafd_<id>.caf.<ver> from psdzdata/swe/cafd/")
    p.add_argument("--psdzdata", default=os.environ.get("NBTEVO_PSDZDATA"), help="your psdzdata/ root (for the keystore)")
    p.add_argument("--resource-jar", default=os.environ.get("NBTEVO_PSDZ_RESOURCE_JAR"),
                   help="your PSdZ/bin/psdz/resource.jar (logo PNGs for the keystore password)")
    p.add_argument("--bmw-logo", help="instead of --resource-jar: your own bmw_logo.png")
    p.add_argument("--bmw-mini-logo", help="…and your own bmw_mini_logo.png")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_build_catalog)

    # FSC activations (owner-CA): a nested `evocode fsc <cmd>` group.
    fp = sub.add_parser("fsc", help="FSC activations (owner-CA): keygen/mint/verify/whosigned")
    fs = fp.add_subparsers(dest="fsc_cmd", required=True)
    g = fs.add_parser("keygen", help="generate your own e=3 FSC trust anchor")
    g.add_argument("-o", "--out", required=True); g.add_argument("--blobb", help="also write the 128-byte LE modulus")
    g.add_argument("--bits", type=int, default=1024); g.set_defaults(fn=cmd_fsc_keygen)
    g = fs.add_parser("mint", help="mint an FSC signed by your own key")
    g.add_argument("--key", required=True); g.add_argument("--appno", required=True, help="e.g. 0x0143 (CarPlay)")
    g.add_argument("--vin", help="9-char VIN field (omit for VIN-generic)")
    g.add_argument("--upgrade-index", type=int, default=1); g.add_argument("-o", "--out", required=True)
    g.set_defaults(fn=cmd_fsc_mint)
    g = fs.add_parser("verify", help="check an FSC would be accepted under a modulus")
    g.add_argument("--fsc", required=True); g.add_argument("--key"); g.add_argument("--blobb")
    g.set_defaults(fn=cmd_fsc_verify)
    g = fs.add_parser("parse", help="decode an FSC's body fields"); g.add_argument("--fsc", required=True)
    g.set_defaults(fn=cmd_fsc_parse)
    g = fs.add_parser("fingerprint", help="stable short id of an anchor"); g.add_argument("--key"); g.add_argument("--blobb")
    g.set_defaults(fn=cmd_fsc_fingerprint)
    g = fs.add_parser("whosigned", help="identify WHOSE anchor signed FSCs read off a unit")
    g.add_argument("--fsc", required=True, action="append"); g.add_argument("--anchor", action="append", default=[])
    g.add_argument("--recover", action="store_true"); g.set_defaults(fn=cmd_fsc_whosigned)
    g = fs.add_parser("from-log", help="extract .fsc tokens from a GetFSC read log")
    g.add_argument("log"); g.add_argument("-o", "--out", required=True); g.set_defaults(fn=cmd_fsc_from_log)
    g = fs.add_parser("find-blobb", help="locate the FSC anchor in a NBTCarHU dump")
    g.add_argument("nbtcarhu"); g.add_argument("--save-blobb", help="write the 128-byte modulus here")
    g.set_defaults(fn=cmd_fsc_find_blobb)
    g = fs.add_parser("patch-blobb", help="swap the anchor in a NBTCarHU dump to your own key (offline)")
    g.add_argument("nbtcarhu"); g.add_argument("--key", required=True)
    g.add_argument("--offset", help="blobB file offset (default: auto-locate)")
    g.add_argument("--backup", help="write the stock 128-byte anchor here, for revert")
    g.add_argument("-o", "--out", required=True); g.set_defaults(fn=cmd_fsc_patch_blobb)
    g = fs.add_parser("apply", help="store minted FSCs on the car (SwtRoutine + L3; dry-run unless --commit)")
    g.add_argument("--fsc-dir", required=True, help="directory of .fsc files (from `fsc mint`)")
    g.add_argument("--host"); g.add_argument("--target", type=_target, default=TGT_HU)
    g.add_argument("--l3-key"); g.add_argument("--commit", action="store_true")
    g.add_argument("--base32", action="store_true", help="base32-encode the FSC (escape hatch; ODX says raw)")
    g.add_argument("--store-rco", help="store op RCO byte (default 0x07)")
    g.set_defaults(fn=cmd_fsc_apply)
    g = fs.add_parser("read", help="read current FSC status from the car (RCO 0x0B; safe, no SecurityAccess)")
    g.add_argument("--host", required=True); g.add_argument("--target", type=_target, default=TGT_HU)
    g.add_argument("--appno", action="append", required=True, help="application number, e.g. 0x0143 (repeatable)")
    g.add_argument("--upgrade-index", type=int, default=1); g.set_defaults(fn=cmd_fsc_read)
    g = fs.add_parser("disable", help="disable an FSC by appno (RCO 0x0A + L3; dry-run unless --commit)")
    g.add_argument("--host"); g.add_argument("--target", type=_target, default=TGT_HU)
    g.add_argument("--appno", action="append", required=True, help="application number, e.g. 0x0143 (repeatable)")
    g.add_argument("--upgrade-index", type=int, default=1)
    g.add_argument("--l3-key"); g.add_argument("--commit", action="store_true"); g.set_defaults(fn=cmd_fsc_disable)

    # Root access (OPT_DEBUG): `evocode root <cmd>` group.
    rp = sub.add_parser("root", help="OPT_DEBUG root-access: status/prepare/enable/revert (see docs/root-access.md)")
    rs = rp.add_subparsers(dest="root_cmd", required=True)
    g = rs.add_parser("status", help="probe whether dev ports (22/23/8000) are open")
    g.add_argument("--host", required=True); g.set_defaults(fn=cmd_root_status)
    g = rs.add_parser("prepare", help="patch starter.cfg offline: STOP→RUN (or --revert: RUN→STOP)")
    g.add_argument("--starter-cfg", required=True, help="stock starter.cfg from the unit")
    g.add_argument("-o", "--out", required=True, help="patched output file")
    g.add_argument("--revert", action="store_true", help="RUN→STOP instead"); g.set_defaults(fn=cmd_root_prepare)
    g = rs.add_parser("enable", help="flash patched starter.cfg (dry-run unless --commit)")
    host_target(g); g.add_argument("--l3-key", help="recovered L3 key (required for --commit)")
    g.add_argument("--starter-cfg", required=True, help="stock starter.cfg (or pre-patched)")
    g.add_argument("--btld", default="00001FFD"); g.add_argument("--reset-timeout", type=int, default=50)
    g.add_argument("--commit", action="store_true"); g.set_defaults(fn=cmd_root_enable)
    g = rs.add_parser("revert", help="flash stock starter.cfg to disable OPT_DEBUG")
    host_target(g); g.add_argument("--l3-key", help="recovered L3 key (required for --commit)")
    g.add_argument("--stock", required=True, help="the original stock starter.cfg")
    g.add_argument("--btld", default="00001FFD"); g.add_argument("--reset-timeout", type=int, default=50)
    g.add_argument("--commit", action="store_true"); g.set_defaults(fn=cmd_root_revert)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except (consent.ConsentError, UdsError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
