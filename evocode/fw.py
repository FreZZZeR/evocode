# SPDX-License-Identifier: Apache-2.0
"""Firmware-file install over the unit's dev SSH shell — the filesystem plane.

This is the one filesystem-plane helper in an otherwise diagnostic-plane toolkit (see AGENTS.md §1):
it puts a file onto the head unit's partition **safely and reversibly** — the brick-risky step the FSC
owner-CA flow needs (installing the blobB-patched ``NBTCarHU``). It does NOT touch coding, FSC codes or
OPT_DEBUG; those ride the diagnostic plane (``write`` / ``fsc apply`` / ``root``).

The value here is the *choreography*, not the copy: remount read-write, back up the current file, upload
to a temp path **on the same partition**, **rename-over to a new inode** (never edit a running binary in
place), restore perms, remount read-only, restart the HMI. Transport is plain ``cat`` over an exec
channel: the unit's old sshd is not relied on to expose SFTP (its ``scp`` is driven in legacy mode), so
SFTP / modern ``scp`` are side-stepped.

Needs the ``ssh`` extra (``pip install 'evocode[ssh]'`` → paramiko **3.x/4.x**; paramiko 5.0 dropped the
SHA-1 key exchange the old QNX sshd needs, hence the ``<5`` pin). It forces the legacy ``ssh-rsa``
signature for that sshd. If paramiko still can't negotiate, fall back to the system client:
``ssh``/``scp -O`` with ``-oKexAlgorithms=+diffie-hellman-group14-sha1 -oHostKeyAlgorithms=+ssh-rsa``.
``install()`` verifies the on-unit byte-count before the rename-over and aborts on mismatch, so a dropped
or truncated transfer can't leave a broken/empty file. The choreography (connect, remount, backup,
rename-over, chmod) is validated against real QNX 6.5 in an emulator; the file transport itself is **not
yet validated on a live unit** (an emulator console bridge can't exercise it).
"""
from __future__ import annotations

import shlex
from typing import Callable, List, Optional, Tuple


def plan(remote: str, mount: str, tmp: str, nbytes: int, *, backup: bool = True,
         mode: Optional[str] = "755", restart: Optional[str] = None) -> List[str]:
    """The ordered steps of a safe, reversible file swap (pure — drives the dry-run and the tests).

    Order matters: remount rw → back up the *old* file → upload to a same-partition temp → atomic
    rename-over (new inode) → perms → remount ro → restart. ``tmp`` is on the same partition as
    ``remote`` so the ``mv`` is an atomic same-filesystem rename.
    """
    r, t, m = shlex.quote(remote), shlex.quote(tmp), shlex.quote(mount)
    steps = ["mount -uw %s" % m]
    if backup:
        steps.append("[ -f %s.orig ] || [ ! -f %s ] || cp %s %s.orig" % (r, r, r, r))   # keep FIRST backup; skip if new
    steps.append("upload %s (%d bytes)" % (tmp, nbytes))
    steps.append("verify %s is %d bytes, else abort" % (tmp, nbytes))  # catch a silent/truncated upload
    steps.append("mv %s %s" % (t, r))                                  # rename-over → new inode
    if mode:
        steps.append("chmod %s %s" % (shlex.quote(mode), r))
    steps.append("mount -ur %s" % m)
    if restart:
        steps.append("restart: %s" % restart)
    return steps


def _paramiko():
    try:
        import paramiko
    except ImportError as e:                                           # noqa: F841
        raise ImportError("fw needs the ssh extra:  pip install 'evocode[ssh]'") from None
    return paramiko


def connect(host: str, *, user: str = "root", password: Optional[str] = None,
            key_filename: Optional[str] = None, port: int = 22, timeout: float = 15.0,
            modern: bool = False):
    """A paramiko SSHClient. Default: coerce the legacy ``ssh-rsa`` signature the old QNX sshd needs.

    ``modern=True`` skips that coercion, for a modern sshd — e.g. an emulator's console bridge, or any
    host that (correctly) rejects ``ssh-rsa``.
    """
    paramiko = _paramiko()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # The old QNX sshd omits server-sig-algs, so paramiko 2.9+ won't fall back to ssh-rsa (LP#1973241)
    # unless the SHA-2 RSA variants are disabled. A modern sshd rejects ssh-rsa, so skip it there.
    disabled = {} if modern else {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}
    cli.connect(host, port=port, username=user, password=password, key_filename=key_filename,
                timeout=timeout, allow_agent=key_filename is None and password is None,
                look_for_keys=key_filename is None, disabled_algorithms=disabled)
    return cli


def run(cli, cmd: str, timeout: float = 30.0) -> Tuple[int, str, str]:
    """Run one remote command; return (rc, stdout, stderr)."""
    _in, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode("latin-1", "replace")
    e = err.read().decode("latin-1", "replace")
    return out.channel.recv_exit_status(), o, e


def _run_ok(cli, cmd: str, log: Callable) -> None:
    rc, o, e = run(cli, cmd)
    log("  $ %s%s" % (cmd, "" if rc == 0 else "   -> rc=%d %s" % (rc, (e or o).strip()[:120])))
    if rc != 0:
        raise RuntimeError("remote command failed (rc=%d): %s :: %s" % (rc, cmd, (e or o).strip()[:200]))


def put(cli, data: bytes, remote_tmp: str) -> None:
    """Upload bytes via ``cat > tmp`` over an exec channel (no SFTP needed on old sshd)."""
    _in, out, err = cli.exec_command("cat > %s" % shlex.quote(remote_tmp))
    _in.write(data)
    _in.flush()
    _in.channel.shutdown_write()
    rc = out.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError("upload to %s failed (rc=%d): %s" % (remote_tmp, rc, err.read().decode("latin-1", "replace")[:200]))


def get(cli, remote: str) -> bytes:
    """Download a remote file via ``cat`` (returns raw bytes)."""
    _in, out, err = cli.exec_command("cat %s" % shlex.quote(remote))
    data = out.read()
    rc = out.channel.recv_exit_status()
    if rc != 0:
        raise RuntimeError("read %s failed (rc=%d): %s" % (remote, rc, err.read().decode("latin-1", "replace")[:200]))
    return data


def pull(host: str, remote: str, **conn) -> bytes:
    """Fetch a file off the unit (e.g. the live ``NBTCarHU`` to patch). Read-only."""
    cli = connect(host, **conn)
    try:
        return get(cli, remote)
    finally:
        cli.close()


def install(host: str, data: bytes, remote: str, *, mount: str = "/fs/sda0",
            backup: bool = True, mode: Optional[str] = "755", restart: Optional[str] = None,
            log: Callable = print, **conn) -> bool:
    """Safely replace ``remote`` with ``data``: backup → upload → rename-over → perms → restart.

    Returns True on success. Keeps ``remote.orig`` (first backup) as the revert.
    """
    tmp = remote + ".new"
    cli = connect(host, **conn)
    try:
        # size sanity: a replacement should be non-empty
        if not data:
            raise ValueError("refusing to install an empty file")
        _run_ok(cli, "mount -uw %s" % shlex.quote(mount), log)
        if backup:
            # keep the FIRST backup; skip gracefully if the target doesn't exist yet (installing a new file)
            _run_ok(cli, "[ -f %s.orig ] || [ ! -f %s ] || cp %s %s.orig"
                    % (shlex.quote(remote), shlex.quote(remote), shlex.quote(remote), shlex.quote(remote)), log)
        log("  .. upload %s (%d bytes)" % (tmp, len(data)))
        put(cli, data, tmp)
        # verify the upload landed intact BEFORE the rename-over — a silent truncation would brick the unit
        rc, o, _e = run(cli, "wc -c < %s" % shlex.quote(tmp))
        parts = o.split()
        got = int(parts[0]) if (rc == 0 and parts and parts[0].isdigit()) else None
        if got != len(data):
            run(cli, "rm -f %s" % shlex.quote(tmp))
            run(cli, "mount -ur %s" % shlex.quote(mount))
            raise RuntimeError("upload size mismatch (sent %d, on-unit %s) — ABORTED, %s NOT replaced"
                               % (len(data), got, remote))
        log("  .. verified %d bytes on the unit" % got)
        _run_ok(cli, "mv %s %s" % (shlex.quote(tmp), shlex.quote(remote)), log)
        if mode:
            _run_ok(cli, "chmod %s %s" % (shlex.quote(mode), shlex.quote(remote)), log)
        # best-effort remount ro (not fatal)
        rc, _o, _e = run(cli, "mount -ur %s" % shlex.quote(mount))
        log("  $ mount -ur %s%s" % (mount, "" if rc == 0 else "   -> rc=%d (left rw)" % rc))
        if restart:
            rc, _o, e = run(cli, restart)
            log("  $ %s%s" % (restart, "" if rc == 0 else "   -> rc=%d %s" % (rc, e.strip()[:120])))
        log("  *** installed %s (backup: %s.orig). Watch the HMI come up. ***" % (remote, remote))
        return True
    finally:
        cli.close()


def revert(host: str, remote: str, *, mount: str = "/fs/sda0", restart: Optional[str] = None,
           log: Callable = print, **conn) -> bool:
    """Restore ``remote.orig`` over ``remote`` (the backup install() kept)."""
    cli = connect(host, **conn)
    try:
        rc, _o, _e = run(cli, "[ -f %s.orig ]" % shlex.quote(remote))
        if rc != 0:
            raise RuntimeError("no %s.orig backup on the unit — nothing to revert" % remote)
        _run_ok(cli, "mount -uw %s" % shlex.quote(mount), log)
        _run_ok(cli, "mv %s.orig %s" % (shlex.quote(remote), shlex.quote(remote)), log)
        rc, _o, _e = run(cli, "mount -ur %s" % shlex.quote(mount))
        log("  $ mount -ur %s%s" % (mount, "" if rc == 0 else "   -> rc=%d (left rw)" % rc))
        if restart:
            run(cli, restart)
            log("  $ %s" % restart)
        log("  *** reverted %s from .orig ***" % remote)
        return True
    finally:
        cli.close()
