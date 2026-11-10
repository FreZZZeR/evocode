# SPDX-License-Identifier: Apache-2.0
"""evocode — read, decode, sign and write BMW NBT EVO (QNX) coding over ENET/HSFZ.

Pure Python standard library. Platform scope: NBT EVO / QNX (iDrive ID4/ID5/ID6)
only — NOT MGU / ID7+ (Linux). See docs/scope.md.

The mechanism is constant across NBT EVO builds; what changes per car is data —
the BTLD-selected signing key and the per-CAFD bit catalog. Read the SVK first and
key off the unit's real BTLD + CAFD ids; never assume them.
"""

__version__ = "0.1.1"
__all__ = ["__version__"]
