############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native package
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Native camera backends (ADR-002). The list is the registration point: adding
# a brand means adding a module here, and a missing SDK means one more absent
# backend with a reason, never an exception (ADR-014).

from __future__ import annotations

from solarscribe.devices.abc import DeviceKind
from solarscribe.devices.native import playerone, qhy, touptek, zwo
from solarscribe.devices.native.backend import NativeCameraBackend

__all__ = ["native_camera_backends", "touptek"]


# @args: loader - injectable library loader; None uses the real ctypes loader
# @return: one backend per native SDK, in the order the UI should show them
def native_camera_backends(loader=None):
    kwargs = {} if loader is None else {"loader": loader}
    return [
        NativeCameraBackend(
            touptek.BACKEND, "Touptek", touptek.LIBRARIES,
            driver=touptek.TouptekCamera, **kwargs,
        ),
        zwo.backend(loader),
        qhy.backend(loader),
        playerone.backend(loader),
    ]


# The kind constant is re-exported so a caller building a BackendInfo for a
# native backend does not have to import devices.abc for one enum value.
CAMERA_KIND = DeviceKind.CAMERA
