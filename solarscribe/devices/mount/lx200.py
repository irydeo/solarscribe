############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount lx200 module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Direct LX200/OnStep fallback (ADR-019).
#
# ASCOM and INDI are the standard paths, but a serial (or TCP) LX200 link is
# the last-resort one: OnStep speaks it natively, and a user with no ASCOM
# Platform and no indiserver can still move the mount.
#
# The LX200 protocol does not take an arbitrary rate. It moves at one of a few
# presets selected with :RG# (guide), :RC# (centre), :RM# (move) and :RS#
# (slew), then starts motion with :Mn#/:Ms#/:Me#/:Mw#. The contract's signed
# arcsec/s is therefore approximated to the nearest preset, and the scan
# calibration measures the rate it really gets. This limitation is deliberate
# and must be written in the hardware report; a driver that lied about the rate
# would make the calibration meaningless.
#
# The transport is injected so the command sequences can be unit-tested without
# a serial port or a mount.

from __future__ import annotations

import importlib.util
import os

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, MountCaps, MountInfo, MountStatus,
)
from solarscribe.devices.mount.backend import MountBackend

__all__ = [
    "Lx200Mount", "backend", "parse_dec", "parse_ra", "format_dec", "format_ra",
]

BACKEND = "native/lx200"
DEFAULT_HOST = "192.168.4.1"        # OnStep's usual Wi-Fi address
DEFAULT_PORT = 9999
DEFAULT_BAUD = 9600

# Preset rates, roughly, in arcsec/s. The driver picks the smallest preset that
# covers the requested magnitude; the calibration then measures the truth.
_GUIDE_ARCSEC_S = 15.0
_CENTRE_ARCSEC_S = 200.0
_MOVE_ARCSEC_S = 1200.0


# @args: text - "HH:MM:SS" as LX200 returns it
# @return: hours as a float
def parse_ra(text: str) -> float:
    cleaned = text.strip().replace("#", "").replace(":", " ")
    hours, minutes, seconds = (float(part) for part in cleaned.split())
    return (hours + minutes / 60.0 + seconds / 3600.0) % 24.0


# @args: text - "+DD*MM:SS" (or with ' instead of *) as LX200 returns it
# @return: degrees as a float
def parse_dec(text: str) -> float:
    cleaned = text.strip().replace("#", "")
    sign = -1.0 if cleaned.startswith("-") else 1.0
    cleaned = cleaned.lstrip("+-").replace("*", " ").replace("'", " ").replace(":", " ")
    degrees, minutes, seconds = (float(part) for part in cleaned.split())
    return sign * (degrees + minutes / 60.0 + seconds / 3600.0)


# @args: hours - 0..24
# @return: "HH:MM:SS"
def format_ra(hours: float) -> str:
    total = int(round((hours % 24.0) * 3600.0))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


# @args: degrees - -90..90
# @return: "+DD*MM:SS"
def format_dec(degrees: float) -> str:
    sign = "-" if degrees < 0 else "+"
    total = int(round(abs(degrees) * 3600.0))
    return f"{sign}{total // 3600:02d}*{(total % 3600) // 60:02d}:{total % 60:02d}"


class Lx200Mount:
    # Mount contract over an LX200 text link (ADR-019, ADR-012).

    # @args: host, port - TCP address of the LX200/OnStep link
    #        mount_id - as returned by discovery
    #        transport - injectable object with open/close/query/send
    #        serial_port - serial device; None reads SOLARSCRIBE_LX200_SERIAL
    #        baud - serial rate, OnStep defaults to 9600
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        mount_id: str = "native/lx200:0",
        transport=None,
        serial_port: str | None = None,
        baud: int = DEFAULT_BAUD,
    ) -> None:
        self._host = host or os.environ.get("SOLARSCRIBE_LX200_HOST", DEFAULT_HOST)
        self._port = int(port or os.environ.get("SOLARSCRIBE_LX200_PORT", DEFAULT_PORT))
        self._mount_id = mount_id
        self._serial_port = serial_port or os.environ.get("SOLARSCRIBE_LX200_SERIAL")
        if transport is not None:
            self._transport = transport
        elif self._serial_port:
            self._transport = _SerialTransport(self._serial_port, int(baud))
        else:
            self._transport = _SocketTransport(self._host, self._port)
        self._connected = False
        self._tracking = False
        self._parked = False
        self._slewing = False

    # @args: none. Raises DeviceError when the link is down
    # @return: none
    def connect(self) -> None:
        if self._connected:
            return
        try:
            self._transport.open()
        except OSError as exc:
            raise DeviceError(
                f"could not open LX200 link {self._host}:{self._port}: {exc}",
                code="server_missing", device_id=self._mount_id,
            ) from exc
        # :GVP# is the product name: it proves there is a mount answering.
        self._transport.query(":GVP#")
        self._connected = True

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        if self._connected:
            self.stop()
        try:
            self._transport.close()
        finally:
            self._connected = False

    # @return: whether the link is open
    def is_connected(self) -> bool:
        return self._connected

    # @return: (ra_hours, dec_degrees) read straight from the mount
    def position(self) -> tuple[float, float]:
        self._require_connected()
        ra = self._transport.query(":GR#")
        dec = self._transport.query(":GD#")
        try:
            return parse_ra(ra), parse_dec(dec)
        except (ValueError, IndexError) as exc:
            raise DeviceError(
                f"unparseable LX200 position RA={ra!r} DEC={dec!r}",
                code="no_position", device_id=self._mount_id,
            ) from exc

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        self._require_connected()
        if self._parked:
            raise DeviceError("mount is parked", code="parked",
                              device_id=self._mount_id)
        magnitude = abs(float(rate))
        if magnitude == 0.0:
            self._transport.send(":Q#")
            return
        # Pick a preset first, then start the direction. The scan measures what
        # it gets; this link cannot promise an arbitrary arcsec/s.
        if magnitude <= _GUIDE_ARCSEC_S:
            self._transport.send(":RG#")
        elif magnitude <= _CENTRE_ARCSEC_S:
            self._transport.send(":RC#")
        else:
            self._transport.send(":RM#")
        if axis == Axis.RA:
            command = ":Me#" if rate > 0 else ":Mw#"
        elif axis == Axis.DEC:
            command = ":Mn#" if rate > 0 else ":Ms#"
        else:
            raise DeviceError(f"unknown axis {axis}", code="not_supported",
                              device_id=self._mount_id)
        self._transport.send(command)

    # @args: none
    # @return: none
    def stop(self) -> None:
        if self._connected:
            self._transport.send(":Q#")

    # @args: ra - hours; dec - degrees
    # @return: none
    def slew(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._transport.send(f":Sr{format_ra(ra)}#")
        self._transport.send(f":Sd{format_dec(dec)}#")
        self._transport.send(":MS#")
        self._slewing = True

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._transport.send(f":Sr{format_ra(ra)}#")
        self._transport.send(f":Sd{format_dec(dec)}#")
        self._transport.send(":CM#")

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        self._require_connected()
        self._transport.send(":TQ#" if on else ":TS#")
        self._tracking = bool(on)

    # @args: none
    # @return: none
    def park(self) -> None:
        self._require_connected()
        self.stop()
        self._transport.send(":hP#")
        self._parked = True
        self._tracking = False

    # @args: none
    # @return: none
    def unpark(self) -> None:
        self._require_connected()
        self._transport.send(":hR#")
        self._parked = False

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        self._require_connected()
        self._transport.send(":Q#")
        self._slewing = False

    # @return: live state for the telescope panel
    def status(self) -> MountStatus:
        return MountStatus(tracking=self._tracking, slewing=self._slewing,
                           parked=self._parked)

    # @return: the LX200 link moves in presets; the scan calibrates the real rate
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
            max_rate_arcsec_s=_MOVE_ARCSEC_S,
        )

    # @args: none
    # @return: identity for the UI
    def info(self) -> MountInfo:
        return MountInfo(mount_id=self._mount_id, name="LX200 / OnStep",
                         backend=BACKEND)

    # @args: none
    # @return: none. Raises DeviceError when connect() was not called
    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("mount is not connected", code="not_connected",
                              device_id=self._mount_id)


class _SocketTransport:
    # Minimal text transport over TCP (OnStep's Wi-Fi link).

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock = None

    def open(self) -> None:
        import socket
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout,
        )
        self._sock.settimeout(self._timeout)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    # @args: command - one LX200 command ending in '#'
    # @return: the reply text without the trailing '#'
    def query(self, command: str) -> str:
        self.send(command)
        data = self._sock.recv(128).decode("ascii", "replace")
        return data.split("#", 1)[0]

    # @args: command - one LX200 command
    # @return: none
    def send(self, command: str) -> None:
        if self._sock is None:
            raise OSError("LX200 transport is not open")
        self._sock.sendall(command.encode("ascii"))


class _SerialTransport:
    # Serial LX200 link. pyserial is imported in open() so the module loads on
    # a machine without it and the backend simply reports what is missing.

    def __init__(self, port: str, baud: int = DEFAULT_BAUD,
                 timeout: float = 1.0) -> None:
        self._port = port
        self._baud = int(baud)
        self._timeout = timeout
        self._serial = None

    def open(self) -> None:
        import serial  # noqa: WPS433 - optional dependency, imported on use
        self._serial = serial.Serial(
            self._port, self._baud, timeout=self._timeout,
        )

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    # @args: command - one LX200 command ending in '#'
    # @return: the reply text without the trailing '#'
    def query(self, command: str) -> str:
        self.send(command)
        data = b""
        while b"#" not in data:
            chunk = self._serial.read(128)
            if not chunk:
                break
            data += chunk
        return data.split(b"#", 1)[0].decode("ascii", "replace")

    # @args: command - one LX200 command
    # @return: none
    def send(self, command: str) -> None:
        if self._serial is None:
            raise OSError("LX200 serial transport is not open")
        self._serial.write(command.encode("ascii"))


# @args: none
# @return: the LX200 backend descriptor. A host means TCP; a serial device or
#          pyserial means the serial fallback is possible. Without either the
#          backend says what to install/configure instead of advertising an
#          unusable port.
def backend() -> MountBackend:
    def probe() -> tuple[BackendReason, str]:
        if os.environ.get("SOLARSCRIBE_LX200_HOST"):
            return BackendReason.AVAILABLE, ""
        if os.environ.get("SOLARSCRIBE_LX200_SERIAL"):
            if importlib.util.find_spec("serial") is None:
                return (BackendReason.SDK_MISSING,
                        "install pyserial for the configured serial port")
            return BackendReason.AVAILABLE, "serial available"
        if importlib.util.find_spec("serial") is not None:
            return BackendReason.AVAILABLE, "serial available"
        return (BackendReason.SDK_MISSING,
                "set SOLARSCRIBE_LX200_HOST/SERIAL or install pyserial")

    def mounts() -> list[MountInfo]:
        return [MountInfo("native/lx200:0", "LX200 / OnStep", BACKEND)]

    def create(mount_id: str):
        return Lx200Mount(mount_id=mount_id)

    return MountBackend(BACKEND, probe, mounts, create)
