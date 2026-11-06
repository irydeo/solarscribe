############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices sim backend module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Discovery descriptors for the simulators (ADR-005).
#
# They look like any other backend to the DeviceManager: always AVAILABLE,
# because the simulator needs no SDK, no platform and no server. That is what
# makes "run the whole app with no hardware" a supported mode instead of a test
# trick.

from __future__ import annotations

from solarscribe.devices.abc import BackendReason, CameraInfo, DeviceKind, MountInfo
from solarscribe.devices.sim.camera import SimCamera
from solarscribe.devices.sim.mount import SimMount

__all__ = ["SimCameraBackend", "SimMountBackend"]


class SimCameraBackend:
    # @args: count - how many simulated cameras to advertise
    #        kwargs - passed to each SimCamera (width, height, fps...)
    def __init__(self, count: int = 1, **kwargs) -> None:
        self.name = "sim"
        self.kind = DeviceKind.CAMERA
        self._count = max(1, int(count))
        self._kwargs = kwargs

    # @return: always AVAILABLE: the simulator ships with the app
    def probe(self) -> tuple[BackendReason, str]:
        return BackendReason.AVAILABLE, ""

    # @return: one CameraInfo per simulated camera
    def cameras(self) -> list[CameraInfo]:
        return [
            SimCamera(camera_id=f"sim:{i}", **self._kwargs).info()
            for i in range(self._count)
        ]

    # @args: camera_id - "sim:<index>"
    # @return: the unopened SimCamera
    def create(self, camera_id: str) -> SimCamera:
        return SimCamera(camera_id=camera_id, **self._kwargs)


class SimMountBackend:
    # @args: count - how many simulated mounts to advertise
    #        kwargs - passed to SimMount (ra_hours, dec_deg...)
    def __init__(self, count: int = 1, **kwargs) -> None:
        self.name = "sim"
        self.kind = DeviceKind.MOUNT
        self._count = max(1, int(count))
        self._kwargs = kwargs

    # @return: always AVAILABLE
    def probe(self) -> tuple[BackendReason, str]:
        return BackendReason.AVAILABLE, ""

    # @return: one MountInfo per simulated mount
    def mounts(self) -> list[MountInfo]:
        return [
            SimMount(mount_id=f"sim:mount{i}", **self._kwargs).info()
            for i in range(self._count)
        ]

    # @args: mount_id - "sim:mount<index>"
    # @return: the unconnected SimMount
    def create(self, mount_id: str) -> SimMount:
        return SimMount(mount_id=mount_id, **self._kwargs)
