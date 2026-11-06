############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount indi module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# INDI mount backend for Linux (ADR-019).
#
# INDI is a text/XML protocol over a TCP socket to indiserver (port 7624). The
# client sends vectors (newSwitchVector, newNumberVector) and receives def/set
# vectors with the driver's property values. The mount moves through the standard
# telescope interface:
#   - EQUATORIAL_EOD_COORD: where the mount is, RA in hours and Dec in degrees.
#   - TELESCOPE_MOTION_WE / TELESCOPE_MOTION_NS: continuous rate movement.
#   - ON_COORD_SET + TARGET_EQUATORIAL: GOTO and sync.
#   - TELESCOPE_TRACK_STATE, TELESCOPE_PARK, TELESCOPE_ABORT_MOTION.
#
# Rate movement through INDI switches does not carry a magnitude: the driver's
# current rate is whatever the user or the driver selected. We send the standard
# TELESCOPE_MOTION_RATE number as well, which OnStep and several drivers honour,
# but a backend that ignores it will move at its preset rate. That limitation is
# real and is reported in the hardware validation notes; the scan calibrates the
# rate it actually gets.
#
# The socket is injected through a transport so the protocol can be unit-tested
# with a fake server and no indiserver running.

from __future__ import annotations

import os
import socket
import threading
import xml.etree.ElementTree as ET

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, MountCaps, MountInfo, MountStatus,
)
from solarscribe.devices.mount.backend import MountBackend

__all__ = ["IndiMount", "IndiProtocol", "backend", "probe_indi"]

BACKEND = "indi"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7624
# The device name of the telescope in most INDI setups. A user with several
# telescopes can override it through the environment; full multi-device
# discovery belongs to a later phase.
DEFAULT_DEVICE = "Telescope"


# @args: host, port - where indiserver listens
# @return: env overrides, then the standard localhost:7624
def _host_port(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    return (
        host or os.environ.get("SOLARSCRIBE_INDI_HOST", DEFAULT_HOST),
        int(port or os.environ.get("SOLARSCRIBE_INDI_PORT", DEFAULT_PORT)),
    )


# @args: host, port - where indiserver should be
# @return: (reason, detail). A refused connection is SERVER_MISSING, not ERROR
def probe_indi(host: str | None = None, port: int | None = None,
               timeout: float = 0.25) -> tuple[BackendReason, str]:
    if os.name == "nt":
        # ADR-019 splits by platform: ASCOM is the Windows path.
        return BackendReason.OS_UNSUPPORTED, "INDI is the Linux path (ADR-019)"
    host, port = _host_port(host, port)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return BackendReason.AVAILABLE, ""
    except OSError as exc:
        return BackendReason.SERVER_MISSING, f"no indiserver at {host}:{port}: {exc}"


class IndiProtocol:
    # Parser and property store. It knows XML, not sockets, so the same code is
    # tested with a fake transport and used with a real reader thread.

    def __init__(self) -> None:
        self.properties: dict[tuple[str, str], dict] = {}
        self._buffer = ""

    # @args: text - one or more complete INDI XML elements
    # @return: none. Partial input is buffered until the closing tag arrives
    def feed(self, text: str) -> None:
        self._buffer += text
        try:
            root = ET.fromstring(f"<indi>{self._buffer}</indi>")
        except ET.ParseError:
            # A socket read may split an element. Keep it for the next feed;
            # the buffer is bounded below so a malformed peer cannot grow it
            # without limit.
            if len(self._buffer) > 4 * 1024 * 1024:
                self._buffer = ""
            return
        self._buffer = ""
        for vector in root:
            self._ingest(vector)

    # @args: device, name - property key
    # @return: the stored dict, or None
    def get(self, device: str, name: str) -> dict | None:
        return self.properties.get((device, name))

    # @args: device, name - property key; child - element name (RA, DEC...)
    # @return: the float value, or None when the property is absent
    def number(self, device: str, name: str, child: str) -> float | None:
        prop = self.get(device, name)
        if not prop:
            return None
        raw = prop["values"].get(child)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    # @args: device, name - property key
    # @return: the INDI state string (Ok, Busy, Alert...) or ""
    def state(self, device: str, name: str) -> str:
        prop = self.get(device, name)
        return prop.get("state", "") if prop else ""

    # @args: vector - an ElementTree element
    # @return: none. Stores def* and set* vectors; ignores messages
    def _ingest(self, vector) -> None:
        tag = vector.tag
        if not (tag.startswith("def") or tag.startswith("set")):
            return
        device = vector.attrib.get("device", "")
        name = vector.attrib.get("name", "")
        if not device or not name:
            return
        values = {}
        for child in vector:
            child_name = child.attrib.get("name", "")
            if child_name:
                values[child_name] = (child.text or "").strip()
        self.properties[(device, name)] = {
            "state": vector.attrib.get("state", ""),
            "values": values,
            "kind": tag[3:],      # Switch, Number, Text...
        }


class _SocketTransport:
    # Thin TCP transport; the mount only needs open/send/recv/close.

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None

    # @args: none
    # @return: none
    def open(self) -> None:
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=self._timeout,
        )
        self._sock.settimeout(None)

    # @args: text - XML to send
    # @return: none
    def send(self, text: str) -> None:
        if self._sock is None:
            raise DeviceError("INDI transport is not open", code="not_connected")
        self._sock.sendall(text.encode("utf-8"))

    # @args: none
    # @return: bytes, or None when the peer closed the connection
    def recv(self) -> bytes | None:
        if self._sock is None:
            return None
        data = self._sock.recv(65536)
        return data or None

    # @args: none
    # @return: none
    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


class IndiMount:
    # Mount contract over the INDI telescope interface (ADR-019, ADR-012).

    # @args: host, port - indiserver address
    #        mount_id - as returned by discovery
    #        transport - injectable open/send/recv/close object
    #        device - INDI device name of the telescope
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        mount_id: str = "indi:mount0",
        transport=None,
        device: str = DEFAULT_DEVICE,
    ) -> None:
        host, port = _host_port(host, port)
        self._host = host
        self._port = port
        self._mount_id = mount_id
        self._device = device
        self._transport = transport if transport is not None else _SocketTransport(host, port)
        self._protocol = IndiProtocol()
        self._connected = False
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._tracking = False
        self._parked = False
        self._slewing = False
        self._rate = {Axis.RA: 0.0, Axis.DEC: 0.0}

    @property
    def protocol(self) -> IndiProtocol:
        # Exposed so the live readout and the tests can inspect the last vectors.
        return self._protocol

    # @args: none. Raises DeviceError when the socket or server is missing
    # @return: none
    def connect(self) -> None:
        if self._connected:
            return
        try:
            self._transport.open()
        except OSError as exc:
            raise DeviceError(
                f"could not reach indiserver at {self._host}:{self._port}: {exc}",
                code="server_missing", device_id=self._mount_id,
            ) from exc
        self._reader_stop.clear()
        if hasattr(self._transport, "recv"):
            self._reader = threading.Thread(
                target=self._read_loop, name="indi-reader", daemon=True,
            )
            self._reader.start()
        self._send('<getProperties version="1.7"/>')
        self._send(
            f'<newSwitchVector device="{self._device}" name="CONNECTION">'
            '<oneSwitch name="CONNECT">On</oneSwitch></newSwitchVector>'
        )
        self._connected = True

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop()
        self._reader_stop.set()
        # Close before joining: recv() blocks, so closing the socket is what
        # wakes the reader thread. Joining first would always time out.
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001 - closing a dead socket is harmless
            pass
        if self._reader is not None and self._reader.is_alive() and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.0)
        self._reader = None
        self._connected = False

    # @return: whether the client completed connect()
    def is_connected(self) -> bool:
        return self._connected

    # @return: (ra_hours, dec_degrees) from EQUATORIAL_EOD_COORD
    def position(self) -> tuple[float, float]:
        self._require_connected()
        for vector in ("EQUATORIAL_EOD_COORD", "EQUATORIAL_COORD"):
            ra = self._protocol.number(self._device, vector, "RA")
            dec = self._protocol.number(self._device, vector, "DEC")
            if ra is not None and dec is not None:
                return ra, dec
        raise DeviceError(
            "INDI has not reported a position yet", code="no_position",
            device_id=self._mount_id,
        )

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        self._require_connected()
        if self._parked:
            raise DeviceError("mount is parked", code="parked",
                              device_id=self._mount_id)
        magnitude = abs(float(rate))
        if magnitude:
            self._send(
                f'<newNumberVector device="{self._device}" '
                'name="TELESCOPE_MOTION_RATE">'
                f'<oneNumber name="MOTION_RATE">{magnitude}</oneNumber>'
                "</newNumberVector>"
            )
        if axis == Axis.RA:
            east, west = (magnitude > 0.0), (magnitude < 0.0)
            self._send(
                f'<newSwitchVector device="{self._device}" '
                'name="TELESCOPE_MOTION_WE">'
                f'<oneSwitch name="MOTION_EAST">{"On" if east else "Off"}</oneSwitch>'
                f'<oneSwitch name="MOTION_WEST">{"On" if west else "Off"}</oneSwitch>'
                "</newSwitchVector>"
            )
        elif axis == Axis.DEC:
            north, south = (magnitude > 0.0), (magnitude < 0.0)
            self._send(
                f'<newSwitchVector device="{self._device}" '
                'name="TELESCOPE_MOTION_NS">'
                f'<oneSwitch name="MOTION_NORTH">{"On" if north else "Off"}</oneSwitch>'
                f'<oneSwitch name="MOTION_SOUTH">{"On" if south else "Off"}</oneSwitch>'
                "</newSwitchVector>"
            )
        else:
            raise DeviceError(f"unknown axis {axis}", code="not_supported",
                              device_id=self._mount_id)
        self._rate[axis] = float(rate)

    # @args: none
    # @return: none. Stops both axes at once
    def stop(self) -> None:
        if not self._connected:
            return
        self._send(
            f'<newSwitchVector device="{self._device}" '
            'name="TELESCOPE_MOTION_WE">'
            '<oneSwitch name="MOTION_EAST">Off</oneSwitch>'
            '<oneSwitch name="MOTION_WEST">Off</oneSwitch>'
            "</newSwitchVector>"
        )
        self._send(
            f'<newSwitchVector device="{self._device}" '
            'name="TELESCOPE_MOTION_NS">'
            '<oneSwitch name="MOTION_NORTH">Off</oneSwitch>'
            '<oneSwitch name="MOTION_SOUTH">Off</oneSwitch>'
            "</newSwitchVector>"
        )
        self._rate = {Axis.RA: 0.0, Axis.DEC: 0.0}

    # @args: ra - hours; dec - degrees
    # @return: none
    def slew(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._send(
            f'<newSwitchVector device="{self._device}" name="ON_COORD_SET">'
            '<oneSwitch name="SLEW">On</oneSwitch>'
            '<oneSwitch name="TRACK">Off</oneSwitch>'
            '<oneSwitch name="SYNC">Off</oneSwitch>'
            "</newSwitchVector>"
        )
        self._send_coordinates(ra, dec)
        self._slewing = True

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._send(
            f'<newSwitchVector device="{self._device}" name="ON_COORD_SET">'
            '<oneSwitch name="SLEW">Off</oneSwitch>'
            '<oneSwitch name="TRACK">Off</oneSwitch>'
            '<oneSwitch name="SYNC">On</oneSwitch>'
            "</newSwitchVector>"
        )
        self._send_coordinates(ra, dec)

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        self._require_connected()
        self._send(
            f'<newSwitchVector device="{self._device}" '
            'name="TELESCOPE_TRACK_STATE">'
            f'<oneSwitch name="TRACK_ON">{"On" if on else "Off"}</oneSwitch>'
            f'<oneSwitch name="TRACK_OFF">{"Off" if on else "On"}</oneSwitch>'
            "</newSwitchVector>"
        )
        self._tracking = bool(on)

    # @args: none
    # @return: none
    def park(self) -> None:
        self._require_connected()
        self.stop()
        self._send(
            f'<newSwitchVector device="{self._device}" name="TELESCOPE_PARK">'
            '<oneSwitch name="PARK">On</oneSwitch>'
            '<oneSwitch name="UNPARK">Off</oneSwitch>'
            "</newSwitchVector>"
        )
        self._parked = True
        self._tracking = False

    # @args: none
    # @return: none
    def unpark(self) -> None:
        self._require_connected()
        self._send(
            f'<newSwitchVector device="{self._device}" name="TELESCOPE_PARK">'
            '<oneSwitch name="PARK">Off</oneSwitch>'
            '<oneSwitch name="UNPARK">On</oneSwitch>'
            "</newSwitchVector>"
        )
        self._parked = False

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        self._require_connected()
        self._send(
            f'<newSwitchVector device="{self._device}" '
            'name="TELESCOPE_ABORT_MOTION">'
            '<oneSwitch name="ABORT">On</oneSwitch>'
            "</newSwitchVector>"
        )
        self._slewing = False

    # @return: live state for the telescope panel. The driver's own properties
    #          win when the server has reported them; the flags set by our
    #          commands are the fallback before the first vector arrives.
    def status(self) -> MountStatus:
        tracking = self._tracking
        parked = self._parked
        slewing = self._slewing
        track = self._protocol.get(self._device, "TELESCOPE_TRACK_STATE")
        if track:
            tracking = track["values"].get("TRACK_ON") == "On"
        park = self._protocol.get(self._device, "TELESCOPE_PARK")
        if park:
            parked = park["values"].get("PARK") == "On"
        state = self._protocol.state(self._device, "EQUATORIAL_EOD_COORD")
        if state == "Busy":
            # INDI marks the coordinate property Busy while the mount is moving
            # to a target. An "Ok" only clears the flag our own abort_slew()
            # set; it must not hide a slew we just commanded but the server has
            # not reported yet.
            slewing = True
        return MountStatus(tracking=tracking, slewing=slewing, parked=parked)

    # @return: what the INDI telescope interface offers
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
        return MountInfo(mount_id=self._mount_id, name="INDI telescope",
                         backend=BACKEND)

    # @args: ra - hours; dec - degrees
    # @return: none
    def _send_coordinates(self, ra: float, dec: float) -> None:
        self._send(
            f'<newNumberVector device="{self._device}" '
            'name="TARGET_EQUATORIAL">'
            f'<oneNumber name="RA">{ra}</oneNumber>'
            f'<oneNumber name="DEC">{dec}</oneNumber>'
            "</newNumberVector>"
        )

    # @args: xml - a complete INDI element
    # @return: none
    def _send(self, xml: str) -> None:
        try:
            self._transport.send(xml)
        except OSError as exc:
            raise DeviceError(f"INDI send failed: {exc}", code="device_lost",
                              device_id=self._mount_id) from exc

    # @args: none
    # @return: none. Reads the socket until stop or EOF
    def _read_loop(self) -> None:
        while not self._reader_stop.is_set():
            try:
                data = self._transport.recv()
            except OSError:
                break
            if not data:
                break
            self._protocol.feed(data.decode("utf-8", "replace"))

    # @args: none
    # @return: none. Raises DeviceError when connect() was not called
    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("mount is not connected", code="not_connected",
                              device_id=self._mount_id)


# @args: none
# @return: the INDI backend descriptor for the DeviceManager
def backend() -> MountBackend:
    def probe() -> tuple[BackendReason, str]:
        return probe_indi()

    def mounts() -> list[MountInfo]:
        return [MountInfo("indi:mount0", "INDI telescope", BACKEND)]

    def create(mount_id: str):
        return IndiMount(mount_id=mount_id)

    return MountBackend(BACKEND, probe, mounts, create)
