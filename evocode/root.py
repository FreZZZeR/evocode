# SPDX-License-Identifier: Apache-2.0
"""OPT_DEBUG root-access enable/revert — starter.cfg edit and flash orchestration.

``starter.cfg`` is a QNX ``starter``-format XML config (``/fs/sda0/opt/sys/etc/starter.cfg``).
Enabling root = flipping the ``OPT_DEBUG`` service from ``STOP`` to ``RUN``; reverting = the
opposite. The patched file is wrapped in a SWDL no-signature container and flashed via the
diagnostic channel (ENET/HSFZ → bootloader → L3 → transferData). See ``docs/root-access.md``.

The ``starter.cfg`` is **build-specific**: a wrong-version config fails the next boot. This module
takes the operator's own config as input — it never inlines a version-specific blob.
"""
from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Optional

# The OPT_DEBUG line in starter.cfg — QNX starter XML:
#   <Name>OPT_DEBUG</Name>\n      <RequestState>STOP</RequestState>
_RE_STOP = re.compile(
    r"(<Name>OPT_DEBUG</Name>\s*<RequestState>)STOP(</RequestState>)")
_RE_RUN = re.compile(
    r"(<Name>OPT_DEBUG</Name>\s*<RequestState>)RUN(</RequestState>)")


def is_enabled(cfg: str) -> Optional[bool]:
    """True if OPT_DEBUG is RUN, False if STOP, None if not found."""
    if _RE_RUN.search(cfg):
        return True
    if _RE_STOP.search(cfg):
        return False
    return None


def patch(cfg: str) -> str:
    """STOP → RUN. Raises if already RUN or OPT_DEBUG not found."""
    state = is_enabled(cfg)
    if state is True:
        raise ValueError("OPT_DEBUG is already RUN")
    if state is None:
        raise ValueError("OPT_DEBUG service not found in starter.cfg")
    return _RE_STOP.sub(r"\g<1>RUN\g<2>", cfg, count=1)


def unpatch(cfg: str) -> str:
    """RUN → STOP. Raises if already STOP or not found."""
    state = is_enabled(cfg)
    if state is False:
        raise ValueError("OPT_DEBUG is already STOP")
    if state is None:
        raise ValueError("OPT_DEBUG service not found in starter.cfg")
    return _RE_RUN.sub(r"\g<1>STOP\g<2>", cfg, count=1)


# ------------------------------------------------------------------------------- status probe

STARTER_PATH = "/fs/sda0/opt/sys/etc/"
STARTER_NAME = "starter.cfg"


def check_ports(host: str, ports: tuple[int, ...] = (22, 23, 8000),
                timeout: float = 2.0) -> dict[int, bool]:
    """Probe whether OPT_DEBUG dev ports are open on the HU."""
    result: dict[int, bool] = {}
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, p))
            result[p] = True
        except (OSError, socket.timeout):
            result[p] = False
        finally:
            s.close()
    return result
