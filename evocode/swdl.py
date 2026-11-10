# SPDX-License-Identifier: Apache-2.0
"""SWDL flash choreography — enter bootloader, authenticate L3, transfer a container, finalize.

This is the diagnostic-plane flash that coding write already relies on conceptually: same HSFZ
transport, same L3 key, different session (programming 0x02 instead of coding 0x41) and different
services (requestDownload / transferData instead of writeDID). The bootloader processes the
container and writes the enclosed file to the path named in the container's metadata.

Reference behaviour: ``nbt-evo-ssh-unlocker/nbt_optdebug_flash.py`` (no LICENSE file; treated as
behavioural reference for the wire protocol; attribution in CREDITS.md).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import l3
from .hsfz import Hsfz, TGT_HU
from .uds import Uds, NRC_NAMES as _UDS_NRC

# ------------------------------------------------------------------------------- UDS / SWDL constants

SID_ROUTINE = 0x31
SID_RD = 0x34          # requestDownload
SID_TD = 0x36          # transferData
SID_TX = 0x37          # transferExit
SID_WDBI = 0x2E        # writeDataByIdentifier

SA_SEED_FLASH = 0x11   # SecurityAccess requestSeed level for flash
SA_KEY_FLASH = 0x12    # SecurityAccess sendKey level for flash

DID_FINGERPRINT = 0xF15A
DID_ADS = 0xF186       # activeDiagnosticSession
DID_ENERGY = 0x100A
DID_EXTMODE = 0x100E
DID_FTIMING = 0x2504
DID_RASS = 0xF100

RID_ERASE = 0xFF00
RID_CHECKMEM = 0x0202
RID_DEPCHECK = 0xFF01

ERASE_METHOD_IE = 0x02
CHECK_METHOD_ICV = 0x12
ERASE_ACTIVATION = 0x06
ALFI = 0x44
MAX_BLOCKSIZE = 0xFFF1  # 65521

# prog-mode UDS frames
EXT_SESSION = bytes([0x10, 0x03])
PROG_SESSION = bytes([0x10, 0x02])
HARD_RESET = bytes([0x11, 0x01])
ENERGY_ON = bytes.fromhex("31010F0C03")
ENERGY_OFF = bytes.fromhex("31010F0C00")
DTC_OFF = bytes.fromhex("8502")
DTC_ON = bytes.fromhex("8501")
COMM_QUIET = bytes.fromhex("280301")
COMM_NORMAL = bytes.fromhex("280001")
EXT_SET_01 = bytes.fromhex("3101100301")
EXT_SET_OFF = bytes.fromhex("3101100300")
ACT_APP_MODE = bytes.fromhex("3101100F")

# Shared UDS names (evocode.uds) + the NRCs the flash loop specifically handles.
NRC_NAMES = {
    **_UDS_NRC,
    0x12: "subFunctionNotSupported",
    0x21: "busyRepeatRequest",
    0x24: "requestSequenceError",
    0x37: "requiredTimeDelayNotExpired",
    0x73: "wrongBlockSequenceCounter",
    0x78: "responsePending",
}


def is_neg(r: bytes) -> bool:
    return len(r) >= 1 and r[0] == 0x7F


# ------------------------------------------------------------------------------- container format

def build_container(data: bytes, target_path: str, name: str,
                    tag: str = "FIL", cpu: str = "Omap") -> bytes:
    """Build a SWDL no-signature file-copy container from raw file bytes.

    Three records: header (0x01), metadata (0x02), file data (0x04).
    """
    meta = "TargetPath=%s;Name=%s;Tag=%s;CPU=%s;" % (target_path, name, tag, cpu)
    meta_b = meta.encode("latin-1")

    def _rec(marker: int, flags1: int, flags2: int, payload: bytes) -> bytes:
        return (bytes([marker]) + flags1.to_bytes(2, "little") +
                len(payload).to_bytes(4, "little") + flags2.to_bytes(2, "little") + payload)

    return (_rec(0x01, 1, 1, b"\x01") +
            _rec(0x02, 2, 1, meta_b) +
            _rec(0x04, 2, 1, data))


def container_target(img: bytes) -> tuple[Optional[str], Optional[str], Optional[bool]]:
    """Parse the metadata record of a SWDL container: (full_path, name, is_live_direct)."""
    pos, n = 0, len(img)
    while pos + 9 <= n:
        marker = img[pos]
        length = int.from_bytes(img[pos + 3:pos + 7], "little")
        if marker == 0x02:
            meta = img[pos + 9:pos + 9 + length].decode("latin-1", "replace")
            kv = dict(p.split("=", 1) for p in meta.split(";") if "=" in p)
            tp = kv.get("TargetPath", "")
            nm = kv.get("Name", "")
            return (tp + nm, nm, bool(tp) and "/repository/istep/" not in tp)
        pos += 9 + length
    return None, None, None


# ------------------------------------------------------------------------------- low-level helpers

def _tx(h: Hsfz, target: int, uds: bytes, label: str, log: Callable) -> Optional[bytes]:
    try:
        r = h.request(target, uds)
    except Exception as e:
        log("  [tx] %-30s -> ERR %s" % (label, e))
        return None
    if is_neg(r):
        nrc = r[2] if len(r) > 2 else 0
        log("  [tx] %-30s -> NRC 0x%02X %s" % (label, nrc, NRC_NAMES.get(nrc, "?")))
    else:
        log("  [tx] %-30s -> %s" % (label, r[:12].hex()))
    return r


def _ispos(r: Optional[bytes]) -> bool:
    return r is not None and r[0] != 0x7F


def _val(r: Optional[bytes]) -> Optional[int]:
    return r[-1] if _ispos(r) and r[0] == 0x62 else None


def _read_session(h: Hsfz, target: int, label: str, log: Callable) -> Optional[int]:
    r = _tx(h, target, bytes([0x22, 0xF1, 0x86]), label, log)
    return r[3] if _ispos(r) and r[0] == 0x62 and len(r) >= 4 else None


# ------------------------------------------------------------------------------- frame builders

def _fr_erase(lbn: int) -> bytes:
    return (bytes([SID_ROUTINE, 0x01, RID_ERASE >> 8, RID_ERASE & 0xFF,
                   ERASE_METHOD_IE, ALFI]) + lbn.to_bytes(4, "big") + bytes([ERASE_ACTIVATION]))


def _fr_check(lbn: int) -> bytes:
    return (bytes([SID_ROUTINE, 0x01, RID_CHECKMEM >> 8, RID_CHECKMEM & 0xFF,
                   CHECK_METHOD_ICV, ALFI]) + lbn.to_bytes(4, "big") + bytes([0x00, 0x00]))


def _fr_req_download(addr: int, size: int) -> bytes:
    nlen = (ALFI >> 4) & 0x0F
    nsz = ALFI & 0x0F
    return bytes([SID_RD, 0x00, ALFI]) + addr.to_bytes(nlen, "big") + size.to_bytes(nsz, "big")


def _parse_block_length(resp: Optional[bytes], default: int = 0x400) -> int:
    if not resp or resp[0] != SID_RD + 0x40 or len(resp) < 3:
        return default
    nbytes = (resp[1] >> 4) & 0x0F
    if nbytes == 0 or len(resp) < 2 + nbytes:
        return default
    maxblk = int.from_bytes(resp[2:2 + nbytes], "big")
    return max(1, min(maxblk - 2, MAX_BLOCKSIZE)) if maxblk > 2 else default


# ------------------------------------------------------------------------------- prog-mode entry

def enter_progmode(h: Hsfz, target: int = TGT_HU, reset_timeout: int = 50,
                   log: Callable = print) -> bool:
    """Enter the flash bootloader (programming session 0x02).

    Returns True if the HU is in session 0x02 (bootloader). The HU self-reboots on 10 02;
    we close/reopen the TCP connection and poll 22 F186 until it answers 0x02.
    """
    log("== STEP 1: extended session + flash timing ==")
    _tx(h, target, EXT_SESSION, "10 03 ExtendedSession", log)
    _tx(h, target, bytes([0x22, 0x25, 0x04]), "22 2504 FlashTiming", log)

    log("== STEP 2: ActivateFlashMode ==")
    if not _ispos(_tx(h, target, ENERGY_ON, "31 01 0F0C 03 ActivateFlash", log)):
        log("  *** HU refused ActivateFlash — abort. ***")
        return False
    if _val(_tx(h, target, bytes([0x22, 0x10, 0x0A]), "22 100A EnergyMode", log)) in (None, 0x00):
        log("  *** EnergyMode not set — abort. ***")
        return False

    log("== STEP 3: DTC off + CommunicationControl quiet ==")
    _tx(h, target, DTC_OFF, "85 02 DTC off", log)
    _tx(h, target, COMM_QUIET, "28 03 01 CommControl quiet", log)

    log("== STEP 4: SetExtendedMode ==")
    r = _tx(h, target, EXT_SET_01, "31 01 1003 01 SetExtMode", log)
    if r is None or is_neg(r):
        log("  *** SetExtendedMode rejected — abort. ***")
        return False

    log("== STEP 5: programmingSession (HU self-reboots to bootloader) ==")
    _tx(h, target, EXT_SESSION, "10 03", log)
    r = _tx(h, target, PROG_SESSION, "10 02 ProgrammingSession", log)
    if r is not None and is_neg(r) and len(r) > 2 and r[2] == 0x22:
        log("  *** 10 02 conditionsNotCorrect — abort. ***")
        return False

    log("  [..] HU self-rebooting — polling 22 F186 (<= %ds)" % reset_timeout)
    try:
        h.close()
    except Exception:
        pass
    t0 = time.time()
    sess = None
    while time.time() - t0 < reset_timeout:
        time.sleep(1.0)
        try:
            h.reconnect(timeout=2.0)
            r = h.request(target, bytes([0x22, 0xF1, 0x86]))
            if _ispos(r) and r[0] == 0x62 and len(r) >= 4:
                sess = r[3]
                log("  [..] HU answering after %.0fs: session 0x%02X" % (time.time() - t0, sess))
                break
        except Exception:
            try:
                h.sock.close()
            except Exception:
                pass
    h.reconnect()
    if sess == 0x02:
        log("  *** HU in PROGRAMMING SESSION (bootloader). ***")
        return True
    if sess is not None:
        log("  HU in session 0x%02X (not bootloader). ***" % sess)
    else:
        log("  *** HU did not answer within %ds. ***" % reset_timeout)
    return False


# ------------------------------------------------------------------------------- teardown

def teardown(h: Hsfz, target: int = TGT_HU, log: Callable = print) -> bool:
    """Restore the HU to the normal app session after a flash or abort."""
    log("== TEARDOWN: restore HU to app ==")
    try:
        h.reconnect()
    except Exception:
        pass
    _tx(h, target, ACT_APP_MODE, "31 01 100F ActAppMode", log)

    en_ok = ext_ok = False
    st = None
    for _ in range(6):
        try:
            h.reconnect()
        except Exception:
            pass
        _tx(h, target, EXT_SESSION, "10 03", log)
        _tx(h, target, ENERGY_OFF, "31 01 0F0C 00 EnergyOff", log)
        en_ok = _val(_tx(h, target, bytes([0x22, 0x10, 0x0A]), "22 100A", log)) == 0x00
        _tx(h, target, EXT_SET_OFF, "31 01 1003 00 ExtModeOff", log)
        ext_ok = _val(_tx(h, target, bytes([0x22, 0x10, 0x0E]), "22 100E", log)) == 0x00
        st = _read_session(h, target, "22 F186", log)
        if (en_ok and ext_ok) or st == 0x01:
            break
        time.sleep(2.0)

    _tx(h, target, COMM_NORMAL, "28 00 01 CommNormal", log)
    _tx(h, target, DTC_ON, "85 01 DTC on", log)

    if (en_ok and ext_ok) or st == 0x01:
        _tx(h, target, HARD_RESET, "11 01 reset -> app", log)
        return True
    log("  *** not clean — forcing reset ***")
    _tx(h, target, HARD_RESET, "11 01 reset (force)", log)
    try:
        h.close()
    except Exception:
        pass
    t0 = time.time()
    while time.time() - t0 < 25:
        time.sleep(2.0)
        try:
            h.reconnect()
            if _read_session(h, target, "22 F186 (after reset)", log) == 0x01:
                log("  [..] back in app after %.0fs" % (time.time() - t0))
                return True
        except Exception:
            try:
                h.sock.close()
            except Exception:
                pass
    log("  *** HU did not return to app after reset. ***")
    return False


# ------------------------------------------------------------------------------- transfer + auth

def _xfer_block(h: Hsfz, target: int, seq: int, chunk: bytes) -> tuple[bool, Optional[str]]:
    frame = bytes([SID_TD, seq & 0xFF]) + chunk
    for attempt in range(6):
        try:
            h.send_only(target, frame)
            while True:
                _ctrl, body = h.recv_frame(timeout=8.0)
                resp = body[2:] if len(body) > 2 else b""
                if not is_neg(resp) and len(resp) >= 2 and resp[0] == 0x76:
                    if resp[1] == seq:
                        return True, ("resent" if attempt else None)
                    continue
                if is_neg(resp):
                    nrc = resp[2] if len(resp) > 2 else 0
                    if nrc == 0x73:
                        return True, "0x73-advance"
                    if nrc in (0x21, 0x7F):
                        time.sleep(0.2)
                        break
                    return False, "NRC 0x%02X %s" % (nrc, NRC_NAMES.get(nrc, "?"))
        except TimeoutError:
            time.sleep(0.3)
        except Exception:
            time.sleep(0.4)
    return False, "exhausted retries"


def _l3_auth(h: Hsfz, target: int, key: dict, btld: int, user_id: int,
             log: Callable) -> bool:
    log("\n== SecurityAccess L3 (flash) ==")
    u = Uds(h, target)                                   # same facade coding/fsc use, levels 0x11/0x12
    try:
        seed = u.request_seed(SA_SEED_FLASH, user_id)
    except Exception as e:
        log("  *** no seed — abort, nothing written. (%s) ***" % e)
        return False
    sig = l3.sign_seed(seed, key, btld=btld, user_id=user_id)
    try:
        u.send_key(SA_KEY_FLASH, sig)
    except Exception as e:
        log("  *** auth NOT granted — abort, nothing written. (%s) ***" % e)
        return False
    log("  *** L3 auth GRANTED ***")
    return True


# ------------------------------------------------------------------------------- apply_flash

def apply_flash(h: Hsfz, img: bytes, *, target: int = TGT_HU, reset_timeout: int = 50,
                key: dict, btld: int = 0x00001FFD, lbn: int = 0,
                fingerprint: bytes = b"\x00" * 13, user_id: int = 0x00000000,
                log: Callable = print) -> bool:
    """Flash a SWDL container to the HU: enter bootloader → L3 auth → transfer → finalize.

    Returns True on successful transfer commit. The caller is responsible for teardown.
    """
    if not enter_progmode(h, target, reset_timeout, log=log):
        log("\n  *** did not reach bootloader — ABORT, NOTHING written. ***")
        return False

    if not _l3_auth(h, target, key, btld, user_id, log):
        return False

    h.start_tester_present(log=log)

    log("\n== SWDL write (%d bytes) ==" % len(img))
    # fingerprint (optional, may NRC)
    try:
        h.request(target, bytes([SID_WDBI, DID_FINGERPRINT >> 8, DID_FINGERPRINT & 0xFF]) + fingerprint)
    except Exception:
        pass

    # erase
    r = _tx(h, target, _fr_erase(lbn), "31 FF00 eraseMemory", log)
    if not _ispos(r):
        log("  *** erase rejected — ABORT (live file untouched). ***")
        return False

    # request download
    r = _tx(h, target, _fr_req_download(0, len(img)), "34 requestDownload", log)
    if not _ispos(r):
        log("  *** requestDownload rejected — ABORT. ***")
        return False
    block_size = _parse_block_length(r)
    nblocks = (len(img) + block_size - 1) // block_size
    log("  block size %d, %d blocks" % (block_size, nblocks))

    # transfer
    seq = 1
    t0 = time.time()
    recovered = 0
    for i, off in enumerate(range(0, len(img), block_size)):
        chunk = img[off:off + block_size]
        ok, note = _xfer_block(h, target, seq, chunk)
        if not ok:
            log("  *** block %d/%d FAILED: %s — ABORT. ***" % (i + 1, nblocks, note))
            return False
        if note:
            recovered += 1
        if i % 50 == 0 or i == nblocks - 1:
            sent = off + len(chunk)
            elapsed = max(0.001, time.time() - t0)
            log("  [..] block %d/%d (%.0fs, %.1f KB/s, %d recovered)"
                % (i + 1, nblocks, elapsed, sent / 1024.0 / elapsed, recovered))
        seq = (seq + 1) & 0xFF
    log("  transfer complete: %d blocks, %.1fs" % (nblocks, time.time() - t0))

    # finalize
    r = _tx(h, target, bytes([SID_TX]), "37 transferExit", log)
    if not _ispos(r):
        log("  *** transferExit rejected. ***")
        return False

    _tx(h, target, _fr_check(lbn), "31 0202 checkMemory", log)
    _tx(h, target, bytes([SID_ROUTINE, 0x01, RID_DEPCHECK >> 8, RID_DEPCHECK & 0xFF]),
        "31 FF01 checkProgDeps", log)

    tgt, _nm, is_live = container_target(img)
    if is_live:
        log("\n  *** WRITE SENT — LIVE-DIRECT to %s. Goes live next boot. ***" % (tgt or "?"))
    else:
        log("\n  *** WRITE SENT — staged at %s. ***" % (tgt or "?"))
    return True
