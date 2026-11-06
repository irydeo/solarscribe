############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount package
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Mount backends (ADR-019): ASCOM COM on Windows, INDI on Linux, INDIGO as the
# optional native fallback on Linux, an LX200 fallback for the user with
# neither, and the simulator for everything else. The order below is the order
# the telescope panel offers them in.

from __future__ import annotations

from solarscribe.devices.mount import ascom, indi, indigo, lx200
from solarscribe.devices.mount.backend import MountBackend
from solarscribe.devices.sim.backend import SimMountBackend

__all__ = ["MountBackend", "default_mount_backends"]


# @args: none
# @return: one backend per mount path, simulators first
def default_mount_backends() -> list:
    return [
        SimMountBackend(),
        ascom.backend(),
        indi.backend(),
        indigo.backend(),
        lx200.backend(),
    ]
