############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native qhy module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# QHY backend skeleton (ADR-002). QHY has known quirks (USB handle, init order)
# that the eventual wrapper must isolate; this module only registers the backend
# so the DeviceManager reports the right reason on every platform.

from __future__ import annotations

from solarscribe.devices.native.backend import NativeCameraBackend

__all__ = ["LIBRARIES", "backend"]

NAME = "native/qhy"
VENDOR = "QHY"
LIBRARIES = ("libqhyccd.so", "libqhyccd.dylib", "qhyccd.dll")


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None) -> NativeCameraBackend:
    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(
        NAME, VENDOR, LIBRARIES, driver=None, **kwargs,
    )
