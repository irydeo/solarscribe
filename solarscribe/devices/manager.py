############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices manager module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# DeviceManager implementation (design/ARCHITECTURE.md 2.1, ADR-012, ADR-014).
#
# Discovery is the place where graceful degradation becomes visible: every
# backend is probed and listed, available or not, with a stable reason. The
# cameras and mounts lists only contain devices from available backends, so a
# machine without libtoupcam or without indiserver still starts, still shows the
# simulator, and explains what is missing in the diagnostics panel.
#
# Discovery can block (enumerating USB, probing a TCP server), so the UI calls it
# from a worker thread. Here the only work done is the probe, once: the results
# are cached so repeated calls from the health panel are cheap.
#
# open_camera() and open_mount() return the device WITHOUT opening it. The
# CaptureEngine calls open()/start_stream(); the telescope panel calls
# connect(). Keeping that decision with the caller is what lets the discovery
# step be a pure query.

from __future__ import annotations

from solarscribe.devices.abc import (
    BackendInfo, BackendReason, Camera, CameraInfo, DeviceError, DeviceKind,
    DeviceManager, Mount, MountInfo,
)
from solarscribe.devices.mount import default_mount_backends
from solarscribe.devices.native import native_camera_backends
from solarscribe.devices.sim.backend import SimCameraBackend

__all__ = ["DeviceManagerImpl", "default_manager"]


class DeviceManagerImpl:
    # Aggregator over the camera and mount backends (ADR-012).

    # @args: camera_backends - injectable list; None means the native SDKs plus
    #                          the simulator
    #        mount_backends - injectable list; None means the per-platform set
    def __init__(self, camera_backends=None, mount_backends=None) -> None:
        self._camera_backends = (
            list(camera_backends)
            if camera_backends is not None
            else native_camera_backends() + [SimCameraBackend()]
        )
        self._mount_backends = (
            list(mount_backends)
            if mount_backends is not None
            else default_mount_backends()
        )
        self._backends_probed = False
        self._infos: list[BackendInfo] = []
        # Reasons cached by backend identity so cameras() and mounts() do not
        # probe a backend a second time; probes can touch USB or a TCP server.
        self._camera_reasons: dict[int, BackendReason] = {}
        self._mount_reasons: dict[int, BackendReason] = {}
        self._cameras_scanned = False
        self._mounts_scanned = False
        self._cameras: dict[str, CameraInfo] = {}
        self._mounts: dict[str, MountInfo] = {}
        self._camera_owner: dict[str, object] = {}
        self._mount_owner: dict[str, object] = {}

    # @return: every backend, available or not, with its reason and detail
    def backends(self) -> list[BackendInfo]:
        self._probe_backends()
        return list(self._infos)

    # @return: the cameras found across every available backend
    def cameras(self) -> list[CameraInfo]:
        self._scan_cameras()
        return list(self._cameras.values())

    # @return: the mounts found across every available backend
    def mounts(self) -> list[MountInfo]:
        self._scan_mounts()
        return list(self._mounts.values())

    # @args: camera_id - as reported by cameras()
    # @return: an unopened Camera
    def open_camera(self, camera_id: str) -> Camera:
        self._scan_cameras()
        backend = self._camera_owner.get(camera_id)
        if backend is None:
            raise DeviceError(f"unknown camera {camera_id!r}",
                              code="unknown_camera", device_id=camera_id)
        return backend.create(camera_id)

    # @args: mount_id - as reported by mounts()
    # @return: an unconnected Mount
    def open_mount(self, mount_id: str) -> Mount:
        self._scan_mounts()
        backend = self._mount_owner.get(mount_id)
        if backend is None:
            raise DeviceError(f"unknown mount {mount_id!r}",
                              code="unknown_mount", device_id=mount_id)
        return backend.create(mount_id)

    # @args: none
    # @return: none. Probes each backend once and records the reason
    def _probe_backends(self) -> None:
        if self._backends_probed:
            return
        self._backends_probed = True
        for backend in self._camera_backends:
            reason, detail = self._safe_probe(backend)
            self._camera_reasons[id(backend)] = reason
            self._infos.append(BackendInfo(
                name=backend.name,
                kind=DeviceKind.CAMERA,
                available=reason is BackendReason.AVAILABLE,
                reason=reason,
                detail=detail,
            ))
        for backend in self._mount_backends:
            reason, detail = self._safe_probe(backend)
            self._mount_reasons[id(backend)] = reason
            self._infos.append(BackendInfo(
                name=backend.name,
                kind=DeviceKind.MOUNT,
                available=reason is BackendReason.AVAILABLE,
                reason=reason,
                detail=detail,
            ))

    # @args: backend - camera or mount backend
    # @return: (reason, detail); an exception in a probe is an ERROR, never a
    #          crash of the discovery step
    def _safe_probe(self, backend) -> tuple[BackendReason, str]:
        try:
            reason, detail = backend.probe()
        except Exception as exc:  # noqa: BLE001
            return BackendReason.ERROR, str(exc)
        return reason, detail

    # @args: none
    # @return: none. Enumerates the available camera backends once
    def _scan_cameras(self) -> None:
        if self._cameras_scanned:
            return
        self._cameras_scanned = True
        self._probe_backends()
        for backend in self._camera_backends:
            reason = self._camera_reasons.get(id(backend), BackendReason.ERROR)
            if reason is not BackendReason.AVAILABLE:
                continue
            try:
                found = backend.cameras()
            except Exception:  # noqa: BLE001 - a broken SDK is an absent camera
                continue
            for info in found:
                self._cameras[info.camera_id] = info
                self._camera_owner[info.camera_id] = backend

    # @args: none
    # @return: none. Enumerates the available mount backends once
    def _scan_mounts(self) -> None:
        if self._mounts_scanned:
            return
        self._mounts_scanned = True
        self._probe_backends()
        for backend in self._mount_backends:
            reason = self._mount_reasons.get(id(backend), BackendReason.ERROR)
            if reason is not BackendReason.AVAILABLE:
                continue
            try:
                found = backend.mounts()
            except Exception:  # noqa: BLE001 - a broken backend is an absent mount
                continue
            for info in found:
                self._mounts[info.mount_id] = info
                self._mount_owner[info.mount_id] = backend


# @args: none
# @return: the manager the app uses by default
def default_manager() -> DeviceManagerImpl:
    return DeviceManagerImpl()


# The runtime check the tests use: DeviceManagerImpl must satisfy the contract.
_MANAGER_CONTRACT = DeviceManager
