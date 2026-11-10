# SPDX-License-Identifier: Apache-2.0
"""Tests for evocode.root — starter.cfg OPT_DEBUG edit logic."""
import pytest
from evocode import root

SAMPLE_STOCK = """\
<?xml version="1.0" encoding="UTF-8"?>
<Module>
  <Service>
      <Number>0</Number>
      <Name>OPT_DEBUG</Name>
      <RequestState>STOP</RequestState>
      <Flags>0</Flags>
  </Service>
  <Service>
      <Number>1</Number>
      <Name>HMI</Name>
      <RequestState>RUN</RequestState>
  </Service>
</Module>
"""

SAMPLE_ENABLED = SAMPLE_STOCK.replace(
    "<Name>OPT_DEBUG</Name>\n      <RequestState>STOP</RequestState>",
    "<Name>OPT_DEBUG</Name>\n      <RequestState>RUN</RequestState>",
)


def test_is_enabled_stop():
    assert root.is_enabled(SAMPLE_STOCK) is False


def test_is_enabled_run():
    assert root.is_enabled(SAMPLE_ENABLED) is True


def test_is_enabled_missing():
    assert root.is_enabled("<Module></Module>") is None


def test_patch():
    patched = root.patch(SAMPLE_STOCK)
    assert root.is_enabled(patched) is True
    assert "OPT_DEBUG" in patched
    assert "<RequestState>RUN</RequestState>" in patched


def test_patch_already_run():
    with pytest.raises(ValueError, match="already RUN"):
        root.patch(SAMPLE_ENABLED)


def test_unpatch():
    unpatched = root.unpatch(SAMPLE_ENABLED)
    assert root.is_enabled(unpatched) is False


def test_unpatch_already_stop():
    with pytest.raises(ValueError, match="already STOP"):
        root.unpatch(SAMPLE_STOCK)


def test_round_trip():
    enabled = root.patch(SAMPLE_STOCK)
    reverted = root.unpatch(enabled)
    assert reverted == SAMPLE_STOCK
