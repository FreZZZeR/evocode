# SPDX-License-Identifier: Apache-2.0
"""Tests for evocode.swdl — container build/parse round-trip."""
from evocode import swdl


def test_container_round_trip():
    data = b"test file content " * 100
    img = swdl.build_container(data, "/fs/sda0/opt/sys/etc/", "starter.cfg")
    path, name, is_live = swdl.container_target(img)
    assert path == "/fs/sda0/opt/sys/etc/starter.cfg"
    assert name == "starter.cfg"
    assert is_live is True


def test_container_staging_path():
    img = swdl.build_container(b"\x00", "/repository/istep/foo/", "bar.bin")
    _path, _name, is_live = swdl.container_target(img)
    assert is_live is False


def test_container_data_preserved():
    data = bytes(range(256)) * 10
    img = swdl.build_container(data, "/fs/sda0/etc/", "test.cfg")
    # data record starts after header(10 bytes) + meta record
    # parse: skip to marker 0x04
    pos = 0
    while pos + 9 <= len(img):
        marker = img[pos]
        length = int.from_bytes(img[pos + 3:pos + 7], "little")
        if marker == 0x04:
            assert img[pos + 9:pos + 9 + length] == data
            return
        pos += 9 + length
    raise AssertionError("data record not found")
