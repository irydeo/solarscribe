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
# The profile is read through the registry (no COM) during the probe, so the
# diagnostics panel can tell "the ASCOM Platform is not installed" from "the
# Python COM bridge is missing". Opening the COM object is left to connect().
#
# The COM object's API is ITelescopeV3. Every call goes through _call(), which
# turns an opaque COM exception into the layer's DeviceError with a stable
# code: a raw HRESULT must never reach the observer (ADR-014).
#
# Hardware validation: only the platform detection is testable on this Linux
# machine. The COM calls are exercised with a fake ITelescope in the unit suite
# and MUST be re-checked on Windows with the OnStep driver; the report says so.

from __future__ import annotations

import importlib.util
import os

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, MountCaps, MountInfo, MountStatus,
)
from solarscribe.devices.mount.backend import MountBackend

__all__ = ["AscomMount", "backend", "probe_ascom"]

BACKEND = "ascom"

# ASCOM MoveAxis uses 0 for RA and 1 for Dec; the contract uses the Axis enum.
_ASCOM_AXIS = {Axis.RA: 0, Axis.DEC: 1}


# @args: none
# @return: (reason, detail). Linux says OS_UNSUPPORTED; Windows without the
#          platform says PLATFORM_MISSING; without the COM bridge, the same
#          reason with a different detail
def probe_ascom() -> tuple[BackendReason, str]:
    if os.name != "nt":
        return BackendReason.OS_UNSUPPORTED, "ASCOM COM is Windows only (ADR-019)"
    bridge = [module for module in ("win32com", "pythonnet", "clr")
              if importlib.util.find_spec(module) is not None]
    if not bridge:
        return (BackendReason.PLATFORM_MISSING,
                "install pywin32 or pythonnet to reach ASCOM COM")
    # The platform registers this ProgID in HKCR; reading the key does not
    # start COM. A missing key means the user installed the bridge but not the
    # ASCOM Platform (ADR-019 lists this as an expected failure).
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            r"ASCOM.Utilities.Profile"):
            pass
    except OSError:
        return (BackendReason.PLATFORM_MISSING,
                "install the ASCOM Platform (ASCOM.Utilities.Profile is not "
                "registered)")
    except ImportError:      # pragma: no cover - only on a broken Windows
        pass
    return BackendReason.AVAILABLE, ""


class AscomMount:
    # Mount contract over an ASCOM COM telescope driver.

    # @args: prog_id - the driver's registered ProgID
    #        mount_id - as returned by discovery
    #        telescope - injectable COM object, for the tests
    def __init__(self, prog_id: str, mount_id: str = "ascom:mount0",
                 telescope=None) -> None:
        self._prog_id = prog_id
        self._mount_id = mount_id
        self._telescope = telescope
        self._connected = False
        self._can_move = {Axis.RA: True, Axis.DEC: True}
        self._caps: MountCaps | None = None

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
        except Exception as exc:  # noqa: BLE001 - COM errors are opaque
            raise DeviceError(
                f"could not connect to ASCOM driver {self._prog_id}: {exc}",
                code="device_lost", device_id=self._mount_id,
            ) from exc
        self._connected = True
        # Drivers differ: an OnStep accepts rate movement on both axes, a
        # focuser-only or a simple mount may not. Reading the Can flags once
        # here lets move_axis() refuse cleanly instead of throwing a COM error
        # at scan time.
        self._read_capabilities()

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        if self._telescope is not None and self._connected:
            try:
                self._telescope.Connected = False
            except Exception:  # noqa: BLE001 - a dead COM object is harmless
                pass
        self._connected = False
        self._caps = None

    # @return: whether the COM driver is connected
    def is_connected(self) -> bool:
        return self._connected

    # @return: (ra_hours, dec_degrees)
    def position(self) -> tuple[float, float]:
        self._require_connected()
        return (float(self._call("RightAscension")),
                float(self._call("Declination")))

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        self._require_connected()
        ascom_axis = _ASCOM_AXIS.get(axis)
        if ascom_axis is None:
            raise DeviceError(f"unknown axis {axis}", code="not_supported",
                              device_id=self._mount_id)
        if not self._can_move.get(axis, True):
            raise DeviceError(
                f"the ASCOM driver cannot move axis {axis.value}",
                code="not_supported", device_id=self._mount_id,
            )
        # ASCOM MoveAxis takes degrees per second; the contract is arcsec/s.
        self._call("MoveAxis", ascom_axis, float(rate) / 3600.0)

    # @args: none
    # @return: none. Stops both axes at once
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
        self._call("SlewToCoordinates", float(ra), float(dec))

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._call("SyncToCoordinates", float(ra), float(dec))

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        self._require_connected()
        self._set("Tracking", bool(on))

    # @args: none
    # @return: none
    def park(self) -> None:
        self._require_connected()
        self._call("Park")

    # @args: none
    # @return: none
    def unpark(self) -> None:
        self._require_connected()
        self._call("Unpark")

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        self._require_connected()
        self._call("AbortSlew")

    # @return: live state for the telescope panel
    def status(self) -> MountStatus:
        if not self._connected:
            return MountStatus()
        return MountStatus(
            tracking=bool(self._get("Tracking", False)),
            slewing=bool(self._get("Slewing", False)),
            parked=bool(self._get("AtPark", False)),
        )

    # @return: what this driver supports; read once on connect()
    def capabilities(self) -> MountCaps:
        return self._caps if self._caps is not None else MountCaps(
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

    # @args: name - method or property; *args - method arguments
    # @return: whatever the COM object returned. Raises DeviceError on failure
    def _call(self, name: str, *args):
        try:
            member = getattr(self._telescope, name)
            return member(*args) if callable(member) else member
        except Exception as exc:  # noqa: BLE001 - COM errors are opaque
            raise DeviceError(
                f"ASCOM {name} failed on {self._prog_id}: {exc}",
                code="device_lost", device_id=self._mount_id,
            ) from exc

    # @args: name - property; value - new value
    # @return: none
    def _set(self, name: str, value) -> None:
        try:
            setattr(self._telescope, name, value)
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(
                f"ASCOM {name} = {value!r} failed on {self._prog_id}: {exc}",
                code="device_lost", device_id=self._mount_id,
            ) from exc

    # @args: name - property; default - value when the driver omits it
    # @return: the property or the default
    def _get(self, name: str, default):
        try:
            return getattr(self._telescope, name)
        except Exception:  # noqa: BLE001 - an optional property may be absent
            return default

    # @args: none
    # @return: none. Reads the Can flags and the axis-rate interval once
    def _read_capabilities(self) -> None:
        for axis in (Axis.RA, Axis.DEC):
            try:
                self._can_move[axis] = bool(
                    self._telescope.CanMoveAxis(_ASCOM_AXIS[axis]),
                )
            except Exception:  # noqa: BLE001 - driver may not implement it
                self._can_move[axis] = True
        minimum, maximum = 0.01, 5000.0
        try:
            rates = self._telescope.AxisRates(0)
            lows, highs = [], []
            for index in range(1, int(rates.Count) + 1):
                rate = rates.Item(index)
                lows.append(float(rate.Minimum))
                highs.append(float(rate.Maximum))
            if lows:
                # ASCOM rates are degrees per second; the contract is
                # arcseconds per second, so multiply by 3600.
                minimum = max(0.01, min(lows) * 3600.0)
                maximum = max(highs) * 3600.0
        except Exception:  # noqa: BLE001 - use the conservative defaults
            pass
        self._caps = MountCaps(
            supports_axis_rates=self._can_move[Axis.RA] or self._can_move[Axis.DEC],
            can_slew=bool(self._get("CanSlew", True)),
            can_sync=bool(self._get("CanSync", True)),
            can_track=bool(self._get("CanSetTracking", True)),
            can_park=bool(self._get("CanPark", True)),
            can_abort=bool(self._get("CanAbortSlew", True)),
            reports_position_while_moving=True,
            min_rate_arcsec_s=minimum,
            max_rate_arcsec_s=maximum,
        )


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
