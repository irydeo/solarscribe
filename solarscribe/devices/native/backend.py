############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native backend module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# One backend per native SDK (ADR-002).
#
# The backend is the small piece that knows how to answer three questions the
# DeviceManager asks: is the SDK here, which cameras does it see, and give me one
# of them. The driver is a separate object because discovery and streaming are
# different lifetimes: discovery opens a device briefly to read its sensor size,
# streaming opens it for real.
#
# When the shared library is missing the backend reports SDK_MISSING and lists
# no cameras. That is the graceful degradation of ADR-014: nothing above this
# layer needs a try/except to survive a machine without a camera SDK.

from __future__ import annotations

from collections.abc import Callable

from solarscribe.devices.abc import (
    BackendReason, Camera, CameraInfo, DeviceError, DeviceKind,
)
from solarscribe.devices.native.loader import load_library

__all__ = ["NativeCameraBackend"]


class NativeCameraBackend:
    # Discovery and construction for one native SDK.

    # @args: name - backend name, e.g. "native/touptek"
    #        vendor - brand shown in the UI
    #        libraries - candidate file names, most specific first
    #        driver - driver class implementing discover(library) and the Camera
    #                 contract; None marks a skeleton whose SDK is known but
    #                 whose wrapper is not written yet
    #        loader - injectable for tests; defaults to the real ctypes loader
    def __init__(
        self,
        name: str,
        vendor: str,
        libraries: tuple[str, ...],
        driver=None,
        loader: Callable = load_library,
    ) -> None:
        self.name = name
        self.kind = DeviceKind.CAMERA
        self.vendor = vendor
        self.libraries = libraries
        self._driver = driver
        self._loader = loader
        self._library = None
        self._probed = False
        self._reason = BackendReason.AVAILABLE
        self._detail = ""

    # @args: none
    # @return: AVAILABLE, SDK_MISSING when the library is not loadable, or ERROR
    #          when the SDK is present but its driver is still a skeleton
    def probe(self) -> tuple[BackendReason, str]:
        if self._probed:
            return self._reason, self._detail
        self._probed = True
        library = self._loader(self.libraries)
        if library is None:
            self._reason = BackendReason.SDK_MISSING
            self._detail = "missing: " + ", ".join(self.libraries)
            return self._reason, self._detail
        self._library = library
        if self._driver is None:
            # The SDK is installed but SolarScribe has no wrapper for it yet.
            # Saying so is more useful than pretending the camera is absent.
            self._reason = BackendReason.ERROR
            self._detail = "driver_not_implemented"
            return self._reason, self._detail
        self._reason = BackendReason.AVAILABLE
        self._detail = ""
        return self._reason, self._detail

    # @args: none
    # @return: the cameras the SDK reports; empty when the backend is unusable
    def cameras(self) -> list[CameraInfo]:
        reason, _ = self.probe()
        if reason is not BackendReason.AVAILABLE or self._driver is None:
            return []
        return self._driver.discover(self._library)

    # @args: camera_id - as returned by cameras()
    # @return: an unopened Camera; the caller decides when to open()
    def create(self, camera_id: str) -> Camera:
        reason, detail = self.probe()
        if reason is not BackendReason.AVAILABLE or self._driver is None:
            raise DeviceError(
                f"{self.name} is not available ({reason.value}: {detail})",
                code="backend_unavailable", device_id=camera_id,
            )
        return self._driver(camera_id, library=self._library)
