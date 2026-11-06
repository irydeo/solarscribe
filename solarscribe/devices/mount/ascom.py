############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount ascom module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ASCOM COM mount backend for Windows (ADR-019).
#
# ASCOM is the standard Windows path: the platform must be installed, the
# selected driver is a registered COM object, and Python reaches it through
# pywin32 (win32com.client) or pythonnet. This module imports neither at module
# load time: on Linux the backend reports OS_UNSUPPORTED, on Windows without the
# COM bridge it reports PLATFORM_MISSING, and the app carries on (ADR-014).
#
# The COM object's API is the ASCOM ITelescopeV3 interface. The methods used
# here are the stable ones: Connected, RA/Declination, MoveAxis, SlewToCoordinates,
# SyncToCoordinates, Tracking, Park, Unpark, AbortSlew and AtPark.
#
# Hardware validation: only the platform detection can be tested on this Linux
# machine. The COM calls are exercised on Windows with an OnStep driver in the
# validation phase and that must be stated in the report.

from __future__ import annotations

import importlib.util
import os

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, MountCaps, MountInfo, MountStatus,
)
from solarscribe.devices.mount.backend import MountBackend

__all__ = ["AscomMount", "backend", "probe_ascom"]

BACKEND = "ascom"


# @args: none
# @return: (reason, detail). Linux says OS_UNSUPPORTED; Windows without a COM
#          bridge says PLATFORM_MISSING
def probe_ascom() -> tuple[BackendReason, str]:
    if os.name != "nt":
        return BackendReason.OS_UNSUPPORTED, "ASCOM COM is Windows only (ADR-019)"
    available = any(
        importlib.util.find_spec(module) is not None
        for module in ("win32com", "pythonnet", "clr")
    )
    if not available:
        return (BackendReason.PLATFORM_MISSING,
                "install pywin32 or pythonnet to reach ASCOM COM")
    return BackendReason.AVAILABLE, ""


class AscomMount:
    # Mount contract over an ASCOM COM telescope driver.

    # @args: prog_id - the driver's registered ProgID
    #        mount_id - as returned by discovery
    #        telescope - injectable COM object, for the Windows tests
    def __init__(self, prog_id: str, mount_id: str = "ascom:mount0",
                 telescope=None) -> None:
        self._prog_id = prog_id
        self._mount_id = mount_id
        self._telescope = telescope
        self._connected = False

    # @args: none. Raises DeviceError when COM or the driver is missing
    # @return: none
    def connect(self) -> None:
        if self._connected:
            return
        try:
            if self._telescope is None:
                import win32com.client  # noqa: F401 - Windows only
                self._telescope = win32com.client.Dispatch(self._prog_id)
            self._telescope.Connected = True
            self._connected = True
        except Exception as exc:  # noqa: BLE001 - COM errors are opaque
            raise DeviceError(
                f"could not connect to ASCOM driver {self._prog_id}: {exc}",
                code="device_lost", device_id=self._mount_id,
            ) from exc

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        if self._telescope is not None and self._connected:
            try:
                self._telescope.Connected = False
            except Exception:  # noqa: BLE001 - a dead COM object is harmless
                pass
        self._connected = False

    # @return: whether the COM driver is connected
    def is_connected(self) -> bool:
        return self._connected

    # @return: (ra_hours, dec_degrees)
    def position(self) -> tuple[float, float]:
        self._require_connected()
        return float(self._telescope.RightAscension), float(self._telescope.Declination)

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        self._require_connected()
        # ASCOM MoveAxis takes degrees per second; the contract is arcsec/s.
        if axis == Axis.RA:
            self._telescope.MoveAxis(0, float(rate) / 3600.0)
        elif axis == Axis.DEC:
            self._telescope.MoveAxis(1, float(rate) / 3600.0)
        else:
            raise DeviceError(f"unknown axis {axis}", code="not_supported",
                              device_id=self._mount_id)

    # @args: none
    # @return: none
    def stop(self) -> None:
        if self._connected:
            try:
                self._telescope.MoveAxis(0, 0.0)
                self._telescope.MoveAxis(1, 0.0)
            except Exception as exc:  # noqa: BLE001
                raise DeviceError(f"ASCOM stop failed: {exc}",
                                  code="device_lost",
                                  device_id=self._mount_id) from exc

    # @args: ra - hours; dec - degrees
    # @return: none
    def slew(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._telescope.SlewToCoordinates(float(ra), float(dec))

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._telescope.SyncToCoordinates(float(ra), float(dec))

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        self._require_connected()
        self._telescope.Tracking = bool(on)

    # @args: none
    # @return: none
    def park(self) -> None:
        self._require_connected()
        self._telescope.Park()

    # @args: none
    # @return: none
    def unpark(self) -> None:
        self._require_connected()
        self._telescope.Unpark()

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        self._require_connected()
        self._telescope.AbortSlew()

    # @return: live state for the telescope panel
    def status(self) -> MountStatus:
        if not self._connected:
            return MountStatus()
        return MountStatus(
            tracking=bool(self._telescope.Tracking),
            slewing=bool(self._telescope.Slewing),
            parked=bool(self._telescope.AtPark),
        )

    # @return: ASCOM telescopes expose the whole interface
    def capabilities(self) -> MountCaps:
        return MountCaps(
            supports_axis_rates=True,
            can_slew=True,
            can_sync=True,
            can_track=True,
            can_park=True,
            can_abort=True,
            reports_position_while_moving=True,
            min_rate_arcsec_s=0.01,
            max_rate_arcsec_s=5000.0,
        )

    # @args: none
    # @return: identity for the UI
    def info(self) -> MountInfo:
        return MountInfo(mount_id=self._mount_id, name=self._prog_id,
                         backend=BACKEND)

    # @args: none
    # @return: none. Raises DeviceError when connect() was not called
    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("mount is not connected", code="not_connected",
                              device_id=self._mount_id)


# @args: none
# @return: the ASCOM backend descriptor
def backend() -> MountBackend:
    def mounts() -> list[MountInfo]:
        # Enumerating the registered drivers needs the ASCOM Profile object.
        # A driver chooser dialog would block discovery, so the registry lookup
        # is the only acceptable route here.
        try:
            import win32com.client
            profile = win32com.client.Dispatch("ASCOM.Utilities.Profile")
            found = []
            for entry in profile.RegisteredDevices("Telescope"):
                prog_id = entry.ProgID
                found.append(MountInfo(f"ascom:{prog_id}", entry.Name, BACKEND))
            return found
        except Exception:  # noqa: BLE001 - no platform: report no devices
            return []

    def create(mount_id: str):
        prog_id = mount_id.split(":", 1)[1] if ":" in mount_id else mount_id
        return AscomMount(prog_id, mount_id=mount_id)

    return MountBackend(BACKEND, probe_ascom, mounts, create)
