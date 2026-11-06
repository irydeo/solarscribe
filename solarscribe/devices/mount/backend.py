############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount backend module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Small descriptor shared by the mount backends (ADR-019).
#
# A backend answers the three questions the DeviceManager asks: is the platform
# or server here, which mounts are visible, and give me one. Wrapping the three
# callables instead of writing a class per backend keeps the ASCOM, INDI, LX200
# and simulator paths symmetric.

from __future__ import annotations

from collections.abc import Callable

from solarscribe.devices.abc import (
    BackendReason, DeviceKind, Mount, MountInfo,
)

__all__ = ["MountBackend"]


class MountBackend:
    # Discovery and construction for one mount backend.

    # @args: name - "ascom", "indi", "native/lx200" or "sim"
    #        probe - returns (BackendReason, detail); must not raise
    #        mounts - returns the MountInfo list; called only when available
    #        create - builds an unconnected Mount for a mount_id
    def __init__(
        self,
        name: str,
        probe: Callable[[], tuple[BackendReason, str]],
        mounts: Callable[[], list[MountInfo]],
        create: Callable[[str], Mount],
    ) -> None:
        self.name = name
        self.kind = DeviceKind.MOUNT
        self._probe = probe
        self._mounts = mounts
        self._create = create
        self._probed = False
        self._reason = BackendReason.AVAILABLE
        self._detail = ""

    # @args: none
    # @return: (reason, detail) for the diagnostics panel. Probed once: an INDI
    #          probe opens a TCP connection and discovery must not pay it twice
    def probe(self) -> tuple[BackendReason, str]:
        if self._probed:
            return self._reason, self._detail
        self._probed = True
        try:
            self._reason, self._detail = self._probe()
        except Exception as exc:  # noqa: BLE001 - a probe must never crash start
            self._reason, self._detail = BackendReason.ERROR, str(exc)
        return self._reason, self._detail

    # @args: none
    # @return: the mounts visible through this backend
    def mounts(self) -> list[MountInfo]:
        reason, _ = self.probe()
        if reason is not BackendReason.AVAILABLE:
            return []
        return list(self._mounts())

    # @args: mount_id - as returned by mounts()
    # @return: an unconnected Mount
    def create(self, mount_id: str) -> Mount:
        return self._create(mount_id)
