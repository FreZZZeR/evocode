# SPDX-License-Identifier: Apache-2.0
"""Owner-consent gate for anything that writes to a vehicle.

A deliberate speed bump: a write refuses unless you have set ``NBTEVO_OWN_VIN`` to the VIN of the
car you own, and that VIN matches the one the tool reads back from the connected car. This is not
DRM — it is a guard against writing to the wrong vehicle. Do not route around it.
"""
from __future__ import annotations

import os

ENV_VIN = "NBTEVO_OWN_VIN"


class ConsentError(RuntimeError):
    pass


def owned_vin() -> str:
    vin = os.environ.get(ENV_VIN, "").strip()
    if not vin:
        raise ConsentError("set %s to the VIN of the car you own before any write." % ENV_VIN)
    return vin


def assert_owned(connected_vin: str) -> None:
    want = owned_vin()
    if connected_vin.strip() != want:
        raise ConsentError(
            "connected VIN %r != %s (%r) — refusing to write to a car you have not confirmed you own."
            % (connected_vin, ENV_VIN, want)
        )
