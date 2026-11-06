############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native playerone module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Player One backend skeleton (ADR-002). Their SDK is written but untested on
# hardware, so the wrapper is deliberately left for a later phase; the backend
# is registered now so the degradation message is accurate.

from __future__ import annotations

from solarscribe.devices.native.backend import NativeCameraBackend

__all__ = ["LIBRARIES", "backend"]

NAME = "native/playerone"
VENDOR = "Player One"
LIBRARIES = (
    "libPlayerOneCamera.so",
    "libPlayerOneCamera.dylib",
    "PlayerOneCamera.dll",
)


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None) -> NativeCameraBackend:
    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(
        NAME, VENDOR, LIBRARIES, driver=None, **kwargs,
    )
