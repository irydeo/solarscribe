############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native zwo module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ZWO ASI backend skeleton (ADR-002).
#
# The SDK is one of the four simple-astro-cap already wraps. Until the wrapper
# is ported here, the backend is still registered: when libASICamera2 is missing
# it reports SDK_MISSING; when it is present it reports ERROR with
# "driver_not_implemented", which is honest and visible in diagnostics instead
# of silently hiding a camera the user paid for.

from __future__ import annotations

from solarscribe.devices.native.backend import NativeCameraBackend

__all__ = ["LIBRARIES", "backend"]

NAME = "native/asi"
VENDOR = "ZWO"
LIBRARIES = ("libASICamera2.so", "libASICamera2.dylib", "ASICamera2.dll")


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None) -> NativeCameraBackend:
    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(
        NAME, VENDOR, LIBRARIES, driver=None, **kwargs,
    )
