# SPDX-License-Identifier: Apache-2.0
"""HSFZ transport for BMW F/early-G ENET diagnostics (the NBT EVO host).

These cars speak **HSFZ**, not DoIP, over TCP 6801. A frame is::

    u32 payload_len | u16 control | u8 source | u8 target | UDS bytes...

where ``payload_len`` counts the bytes after the control word (so ``2 + len(UDS)`` for a data
frame). control 0x0001 = data, 0x0002 = ack. Discovery is a UDP broadcast of control 0x0011 to
port 6811; each gateway answers, and the reply's source IP is the endpoint. Routing is the target
byte alone — connect once and set ``target`` per ECU; the gateway forwards it.

Addresses: tester source 0xF4, FEM gateway 0x10, NBT EVO head unit 0x63.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

IDENT_PORT = 6811
DIAG_PORT = 6801

CTRL_DATA = 0x0001
CTRL_ACK = 0x0002
CTRL_IDENT = 0x0011

SRC_TESTER = 0xF4
TGT_GATEWAY = 0x10
TGT_HU = 0x63


class HsfzError(Exception):
    pass


@dataclass
class Endpoint:
    ip: str
    diag_addr: Optional[int]
    vin: Optional[str]
    raw_ident: str


def _parse_ident(payload: bytes, ip: str) -> Endpoint:
    text = payload.decode("latin1", "replace")

    def field(tag: str, n: int) -> Optional[str]:
        i = text.find(tag)
        return text[i + len(tag): i + len(tag) + n] if i >= 0 else None

    da = field("DIAGADR", 2)
    vin = field("BMWVIN", 17)
    return Endpoint(ip, int(da, 16) if da else None, vin.strip("\x00 ") if vin else None, text)


def discover(bind_ip: str, broadcast: str = "169.254.255.255", timeout: float = 3.0) -> List[Endpoint]:
    """Broadcast the HSFZ ident request on the ENET segment and collect endpoint replies.

    ``bind_ip`` is your host's address on that segment (e.g. a 169.254.x.x link-local), so the probe
    leaves the right interface.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_ip, 0))
    sock.settimeout(timeout)
    sock.sendto(struct.pack(">IH", 0, CTRL_IDENT), (broadcast, IDENT_PORT))
    found: dict[str, Endpoint] = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, (ip, _) = sock.recvfrom(4096)
        except socket.timeout:
            break
        if len(data) >= 6 and ip not in found:
            found[ip] = _parse_ident(data[6:], ip)
    sock.close()
    return list(found.values())


class Hsfz:
    """One TCP/6801 HSFZ session. Set the target per request; the gateway routes by it."""

    def __init__(self, ip: str, source: int = SRC_TESTER, timeout: float = 5.0):
        self.ip = ip
        self.source = source
        self._timeout = timeout
        self.sock = socket.create_connection((ip, DIAG_PORT), timeout=timeout)
        self.sock.settimeout(timeout)
        self._tp_stop: Optional[threading.Event] = None
        self._tp_thread: Optional[threading.Thread] = None

    def close(self) -> None:
        self.stop_tester_present()
        try:
            self.sock.close()
        except OSError:
            pass

    def reconnect(self, timeout: Optional[float] = None) -> "Hsfz":
        try:
            self.sock.close()
        except OSError:
            pass
        t = timeout or self._timeout
        self.sock = socket.create_connection((self.ip, DIAG_PORT), timeout=t)
        self.sock.settimeout(t)
        return self

    def __enter__(self) -> "Hsfz":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def send_only(self, target: int, uds: bytes) -> None:
        self._send(target, uds)

    def recv_frame(self, timeout: Optional[float] = None) -> tuple[int, bytes]:
        if timeout is not None:
            self.sock.settimeout(timeout)
        return self._recv_frame()

    def start_tester_present(self, target: int = 0xDF, period: float = 1.0,
                             log: Optional[Callable] = None) -> None:
        if self._tp_thread is not None:
            return
        self._tp_stop = threading.Event()
        tp = bytes([0x3E, 0x80])

        def _loop() -> None:
            assert self._tp_stop is not None
            while not self._tp_stop.wait(period):
                try:
                    self._send(target, tp)
                except Exception:
                    break

        self._tp_thread = threading.Thread(target=_loop, name="HSFZ-TP", daemon=True)
        self._tp_thread.start()
        if log:
            log("  [tp] TesterPresent 3E 80 -> 0x%02X every %.1fs" % (target, period))

    def stop_tester_present(self) -> None:
        if self._tp_stop is not None:
            self._tp_stop.set()
        if self._tp_thread is not None:
            self._tp_thread.join(timeout=1.0)
            self._tp_thread = None
        self._tp_stop = None

    def _send(self, target: int, uds: bytes) -> None:
        frame = struct.pack(">IH", 2 + len(uds), CTRL_DATA) + bytes([self.source, target]) + uds
        self.sock.sendall(frame)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise HsfzError("HSFZ peer closed the connection")
            buf += chunk
        return buf

    def _recv_frame(self) -> tuple[int, bytes]:
        length, ctrl = struct.unpack(">IH", self._recv_exact(6))
        body = self._recv_exact(length) if length else b""
        return ctrl, body

    def request(self, target: int, uds: bytes, p2_star: float = 6.0) -> bytes:
        """Send a UDS request and return the raw UDS response, skipping acks/echoes and riding the
        extended P2* timer across ``7F xx 78`` responsePending frames."""
        self._send(target, uds)
        deadline = time.time() + p2_star
        while time.time() < deadline:
            try:
                ctrl, body = self._recv_frame()
            except socket.timeout:
                break
            if ctrl != CTRL_DATA or len(body) < 2:
                continue                                   # ack / status frame
            resp = body[2:]                                # strip source, target
            if not resp or resp == uds:
                continue                                   # some gateways echo the request
            if len(resp) >= 3 and resp[0] == 0x7F and resp[2] == 0x78:
                deadline = time.time() + p2_star           # responsePending: keep waiting
                continue
            return resp
        raise HsfzError("no UDS response from 0x%02X for %s" % (target, uds.hex()))
