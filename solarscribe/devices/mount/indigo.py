############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices mount indigo module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# INDIGO mount backend for Linux (ADR-019).
#
# INDIGO is a JSON protocol over TCP to indigo_server (port 7624). Each message
# is one JSON object whose single key names the vector type:
#
#   {"newSwitchVector": {"device": "Mount", "name": "CONNECTION",
#                        "items": [{"name": "CONNECTED", "value": true}]}}
#
# and the server answers with def*/set* vectors that carry the device, the
# property, its state and its items. The stream is not newline framed: messages
# are concatenated and a read may split one, so IndigoProtocol reconstructs the
# objects by brace depth (respecting strings and escapes) before parsing.
#
# Property names are INDIGO's, not INDI's. The mapping is not cosmetic:
#   EQUATORIAL_EOD_COORD -> MOUNT_EQUATORIAL_COORDINATES (RA hours, DEC degrees)
#   TELESCOPE_MOTION_WE  -> MOUNT_MOTION_RA  (WEST/EAST)
#   TELESCOPE_MOTION_NS  -> MOUNT_MOTION_DEC (NORTH/SOUTH)
#   ON_COORD_SET         -> MOUNT_ON_COORDINATES_SET (TRACK/SYNC/SLEW)
#   TELESCOPE_TRACK_STATE-> MOUNT_TRACKING (ON/OFF)
#   TELESCOPE_PARK       -> MOUNT_PARK (PARKED/UNPARKED)
#   TELESCOPE_ABORT_MOTION -> MOUNT_ABORT_MOTION (ABORT_MOTION)
#
# What is NOT covered, on purpose: INDIGO has no arbitrary arcsec/s motion
# property. MOUNT_SLEW_RATE selects one of four classes (GUIDE, CENTERING,
# FIND, MAX) and the driver moves at the rate that class means on that mount.
# The scan calibration measures the rate it really gets, exactly as with the
# LX200 fallback; a driver that invented a rate would make the calibration
# meaningless. MOUNT_CUSTOM_TRACKING_RATE exists but is a tracking rate, not a
# manual motion rate, so it is not used here. BLOBs, the server's LOAD property
# (driver loading) and the device access tokens are out of scope: a mount
# client needs none of them, and a half-implemented auth path would be worse
# than an honest absence.
#
# Hardware validation: the protocol and the command sequence are exercised with
# a fake transport. No indigo_server was running on the validation machine, so
# the hardware test skips and the report must say the INDIGO path is unverified
# against a real mount.

from __future__ import annotations

import json
import os
import socket
import threading
import time

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, MountCaps, MountInfo, MountStatus,
)
from solarscribe.devices.mount.backend import MountBackend

__all__ = [
    "IndigoMount", "IndigoProtocol", "backend", "enumerate_devices",
    "probe_indigo",
]

BACKEND = "indigo"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7624
# The device name of the telescope in most INDIGO setups. The mount simulator
# calls itself "Mount Simulator"; a user with a real driver can override it
# through SOLARSCRIBE_INDIGO_DEVICE or select the discovered name. Full
# multi-device discovery is done by enumerate_devices().
DEFAULT_DEVICE = "Mount Simulator"

# Protocol version in the getProperties handshake: 0x0200 (INDIGO 2.0). The
# server answers with the JSON property definitions.
PROTOCOL_VERSION = 0x0200

# Property and item names from indigo_names.h. Kept as constants so a typo is a
# NameError in the test, not a silently ignored vector.
P_EQUATORIAL = "MOUNT_EQUATORIAL_COORDINATES"
P_MOTION_RA = "MOUNT_MOTION_RA"
P_MOTION_DEC = "MOUNT_MOTION_DEC"
P_SLEW_RATE = "MOUNT_SLEW_RATE"
P_ON_COORD_SET = "MOUNT_ON_COORDINATES_SET"
P_TRACKING = "MOUNT_TRACKING"
P_PARK = "MOUNT_PARK"
P_ABORT = "MOUNT_ABORT_MOTION"
P_CONNECTION = "CONNECTION"
P_INFO = "MOUNT_INFO"

I_RA = "RA"
I_DEC = "DEC"
I_EAST = "EAST"
I_WEST = "WEST"
I_NORTH = "NORTH"
I_SOUTH = "SOUTH"
I_TRACK = "TRACK"
I_SYNC = "SYNC"
I_SLEW = "SLEW"
I_ON = "ON"
I_OFF = "OFF"
I_PARKED = "PARKED"
I_UNPARKED = "UNPARKED"
I_ABORT = "ABORT_MOTION"

# Manual-motion rate classes, selected by magnitude. INDIGO does not carry an
# arbitrary rate; these thresholds only choose the class, and the calibration
# measures the truth afterwards.
_RATE_CLASSES = (
    (15.0, "GUIDE"),
    (300.0, "CENTERING"),
    (1200.0, "FIND"),
    (float("inf"), "MAX"),
)


# @args: host, port - where indigo_server listens
# @return: env overrides, then the standard localhost:7624
def _host_port(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    return (
        host or os.environ.get("SOLARSCRIBE_INDIGO_HOST", DEFAULT_HOST),
        int(port or os.environ.get("SOLARSCRIBE_INDIGO_PORT", DEFAULT_PORT)),
    )


# @args: host, port - where indigo_server should be; timeout - TCP probe
# @return: (reason, detail). A refused connection is SERVER_MISSING
def probe_indigo(host: str | None = None, port: int | None = None,
                 timeout: float = 0.25) -> tuple[BackendReason, str]:
    if os.name == "nt":
        return BackendReason.OS_UNSUPPORTED, "INDIGO is the Linux path (ADR-019)"
    host, port = _host_port(host, port)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return BackendReason.AVAILABLE, ""
    except OSError as exc:
        return BackendReason.SERVER_MISSING, (
            f"no indigo_server at {host}:{port}: {exc}"
        )


class IndigoProtocol:
    # Reassembles the JSON stream and keeps the last value of every property.
    # It knows JSON, not sockets, so a fake transport can test it.

    def __init__(self) -> None:
        self.properties: dict[tuple[str, str], dict] = {}
        self._buffer = ""

    # @args: text - one or more JSON messages, possibly a partial one
    # @return: none. Complete objects are parsed; the rest stays buffered
    def feed(self, text: str) -> None:
        self._buffer += text
        while True:
            message, consumed = _take_object(self._buffer)
            if message is None:
                # A malformed peer must not grow the buffer without limit.
                if len(self._buffer) > 4 * 1024 * 1024:
                    self._buffer = ""
                return
            self._buffer = self._buffer[consumed:]
            try:
                parsed = json.loads(message)
            except ValueError:
                continue
            self._ingest(parsed)

    # @args: device, name - property key
    # @return: the stored dict, or None
    def get(self, device: str, name: str) -> dict | None:
        return self.properties.get((device, name))

    # @args: device, name - property key
    # @return: the devices that published any property
    def devices(self) -> set[str]:
        return {device for device, _name in self.properties}

    # @args: device, name, item - property and item
    # @return: the item value, or None
    def value(self, device: str, name: str, item: str):
        prop = self.get(device, name)
        if not prop:
            return None
        return prop["values"].get(item)

    # @args: device, name, item - property and item
    # @return: the float value, or None when absent or not a number
    def number(self, device: str, name: str, item: str) -> float | None:
        raw = self.value(device, name, item)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    # @args: device, name - property key
    # @return: the INDI/INDIGO state string (Ok, Busy, Alert...)
    def state(self, device: str, name: str) -> str:
        prop = self.get(device, name)
        return prop.get("state", "") if prop else ""

    # @args: message - one parsed JSON object
    # @return: none. Stores def* and set* vectors; ignores the rest
    def _ingest(self, message) -> None:
        if not isinstance(message, dict):
            return
        for kind, payload in message.items():
            if not isinstance(payload, dict):
                continue
            if not (kind.startswith("def") or kind.startswith("set")):
                continue
            device = payload.get("device", "")
            name = payload.get("name", "")
            if not device or not name:
                continue
            values = {}
            targets = {}
            for item in payload.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_name = item.get("name", "")
                if not item_name:
                    continue
                if "value" in item:
                    values[item_name] = item["value"]
                if "target" in item:
                    targets[item_name] = item["target"]
            self.properties[(device, name)] = {
                "state": payload.get("state", ""),
                "values": values,
                "targets": targets,
                "kind": kind[3:],
            }


# @args: text - the receive buffer
# @return: (one complete JSON object or None, bytes consumed). Brace depth is
#          tracked outside strings so a device name with a brace cannot split
#          a message.
def _take_object(text: str) -> tuple[str | None, int]:
    start = 0
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text):
        return None, 0
    if text[start] != "{":
        # Garbage before the next object: drop it instead of refusing the
        # whole stream, because a message could follow a malformed one.
        position = text.find("{", start)
        if position < 0:
            return None, 0
        start = position
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1], index + 1
    return None, 0


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

    # @args: text - one JSON message
    # @return: none
    def send(self, text: str) -> None:
        if self._sock is None:
            raise DeviceError("INDIGO transport is not open",
                              code="not_connected")
        self._sock.sendall(text.encode("utf-8"))

    # @args: seconds - socket timeout, or None to block
    # @return: none
    def settimeout(self, seconds) -> None:
        if self._sock is not None:
            self._sock.settimeout(seconds)

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


class IndigoMount:
    # Mount contract over the INDIGO telescope interface (ADR-019, ADR-012).

    # @args: host, port - indigo_server address
    #        mount_id - "indigo:<device name>"
    #        transport - injectable open/send/recv/close object
    #        device - INDIGO device name of the telescope
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        mount_id: str = "indigo:mount0",
        transport=None,
        device: str | None = None,
    ) -> None:
        host, port = _host_port(host, port)
        self._host = host
        self._port = port
        self._mount_id = mount_id
        # "indigo:mount0" is the synthetic id when discovery found no device;
        # it is not a device name. Only a real name after the colon is used.
        derived = mount_id.split(":", 1)[1] if ":" in mount_id else ""
        if derived in ("", "mount0"):
            derived = ""
        self._device = (
            device
            or derived
            or os.environ.get("SOLARSCRIBE_INDIGO_DEVICE", DEFAULT_DEVICE)
        )
        self._transport = (
            transport if transport is not None
            else _SocketTransport(host, port)
        )
        self._protocol = IndigoProtocol()
        self._connected = False
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._tracking = False
        self._parked = False
        self._slewing = False
        self._rate = {Axis.RA: 0.0, Axis.DEC: 0.0}

    @property
    def protocol(self) -> IndigoProtocol:
        # Exposed so the live readout and the tests can inspect the last values.
        return self._protocol

    @property
    def device(self) -> str:
        return self._device

    # @args: none. Raises DeviceError when the server refuses the connection
    # @return: none
    def connect(self) -> None:
        if self._connected:
            return
        try:
            self._transport.open()
        except OSError as exc:
            raise DeviceError(
                f"could not reach indigo_server at {self._host}:{self._port}: "
                f"{exc}",
                code="server_missing", device_id=self._mount_id,
            ) from exc
        self._reader_stop.clear()
        if hasattr(self._transport, "recv"):
            self._reader = threading.Thread(
                target=self._read_loop, name="indigo-reader", daemon=True,
            )
            self._reader.start()
        self._send("getProperties", {"version": PROTOCOL_VERSION})
        self._connection(True)
        self._connected = True

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop()
        if self._connected:
            self._connection(False)
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

    # @return: (ra_hours, dec_degrees) from MOUNT_EQUATORIAL_COORDINATES
    def position(self) -> tuple[float, float]:
        self._require_connected()
        ra = self._protocol.number(self._device, P_EQUATORIAL, I_RA)
        dec = self._protocol.number(self._device, P_EQUATORIAL, I_DEC)
        if ra is None or dec is None:
            raise DeviceError(
                "indigo_server has not reported a position yet",
                code="no_position", device_id=self._mount_id,
            )
        return ra, dec

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        self._require_connected()
        if self._parked:
            raise DeviceError("mount is parked", code="parked",
                              device_id=self._mount_id)
        if axis not in (Axis.RA, Axis.DEC):
            raise DeviceError(f"unknown axis {axis}", code="not_supported",
                              device_id=self._mount_id)
        magnitude = abs(float(rate))
        if magnitude:
            self._slew_rate(magnitude)
        if axis == Axis.RA:
            self._switch(P_MOTION_RA, {
                I_EAST: float(rate) > 0.0,
                I_WEST: float(rate) < 0.0,
            })
        else:
            self._switch(P_MOTION_DEC, {
                I_NORTH: float(rate) > 0.0,
                I_SOUTH: float(rate) < 0.0,
            })
        self._rate[axis] = float(rate)

    # @args: none
    # @return: none. Stops both axes at once
    def stop(self) -> None:
        if not self._connected:
            return
        self._switch(P_MOTION_RA, {I_EAST: False, I_WEST: False})
        self._switch(P_MOTION_DEC, {I_NORTH: False, I_SOUTH: False})
        self._rate = {Axis.RA: 0.0, Axis.DEC: 0.0}

    # @args: ra - hours; dec - degrees
    # @return: none
    def slew(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._switch(P_ON_COORD_SET, {I_TRACK: True, I_SYNC: False, I_SLEW: False})
        self._coordinates(ra, dec)
        self._slewing = True

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self._require_connected()
        self._switch(P_ON_COORD_SET, {I_TRACK: False, I_SYNC: True, I_SLEW: False})
        self._coordinates(ra, dec)

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        self._require_connected()
        self._switch(P_TRACKING, {I_ON: bool(on), I_OFF: not bool(on)})
        self._tracking = bool(on)

    # @args: none
    # @return: none
    def park(self) -> None:
        self._require_connected()
        self.stop()
        self._switch(P_PARK, {I_PARKED: True, I_UNPARKED: False})
        self._parked = True
        self._tracking = False

    # @args: none
    # @return: none
    def unpark(self) -> None:
        self._require_connected()
        self._switch(P_PARK, {I_PARKED: False, I_UNPARKED: True})
        self._parked = False

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        self._require_connected()
        self._switch(P_ABORT, {I_ABORT: True})
        self._slewing = False

    # @return: live state for the telescope panel. The server's own properties
    #          win when they have arrived; the flags set by our commands are
    #          the fallback before the first vector.
    def status(self) -> MountStatus:
        tracking = self._tracking
        parked = self._parked
        slewing = self._slewing
        track = self._protocol.value(self._device, P_TRACKING, I_ON)
        if track is not None:
            tracking = bool(track)
        park = self._protocol.value(self._device, P_PARK, I_PARKED)
        if park is not None:
            parked = bool(park)
        state = self._protocol.state(self._device, P_EQUATORIAL)
        if state == "Busy":
            # INDIGO marks the coordinate property Busy while the mount moves
            # to a target; an Ok only clears our own abort flag and must not
            # hide a slew we just commanded.
            slewing = True
        return MountStatus(tracking=tracking, slewing=slewing, parked=parked)

    # @return: what the INDIGO telescope interface offers
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
        return MountInfo(mount_id=self._mount_id, name=self._device,
                         backend=BACKEND)

    # @args: on - connect or disconnect the device on the server
    # @return: none
    def _connection(self, on: bool) -> None:
        self._switch(P_CONNECTION, {"CONNECTED": bool(on),
                                    "DISCONNECTED": not bool(on)})

    # @args: magnitude - arcsec/s, unsigned
    # @return: none. Selects the closest INDIGO rate class
    def _slew_rate(self, magnitude: float) -> None:
        for limit, name in _RATE_CLASSES:
            if magnitude <= limit:
                self._switch(P_SLEW_RATE, {
                    "GUIDE": name == "GUIDE",
                    "CENTERING": name == "CENTERING",
                    "FIND": name == "FIND",
                    "MAX": name == "MAX",
                })
                return

    # @args: ra - hours; dec - degrees
    # @return: none
    def _coordinates(self, ra: float, dec: float) -> None:
        self._send("newNumberVector", {
            "device": self._device,
            "name": P_EQUATORIAL,
            "items": [{"name": I_RA, "value": float(ra)},
                      {"name": I_DEC, "value": float(dec)}],
        })

    # @args: name - switch property; values - item name -> bool
    # @return: none
    def _switch(self, name: str, values: dict) -> None:
        self._send("newSwitchVector", {
            "device": self._device,
            "name": name,
            "items": [{"name": item, "value": bool(value)}
                      for item, value in values.items()],
        })

    # @args: kind - message kind, e.g. "getProperties"; payload - its object
    # @return: none
    def _send(self, kind: str, payload: dict) -> None:
        try:
            self._transport.send(
                json.dumps({kind: payload}, separators=(",", ":")),
            )
        except OSError as exc:
            raise DeviceError(f"INDIGO send failed: {exc}", code="device_lost",
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


# @args: device - INDIGO device name
# @return: the mount discovery entry
def _mount_info(device: str) -> MountInfo:
    return MountInfo(f"{BACKEND}:{device}", device, BACKEND)


# @args: transport - opened transport; timeout - how long to listen
# @return: the device names that publish a mount property, sorted
def enumerate_devices(transport, timeout: float = 0.6) -> list[str]:
    protocol = IndigoProtocol()
    transport.send(json.dumps(
        {"getProperties": {"version": PROTOCOL_VERSION}},
        separators=(",", ":"),
    ))
    # A blocking recv would hang discovery forever if the server accepts the
    # socket and then stays silent; the deadline only works with a timeout.
    if hasattr(transport, "settimeout"):
        transport.settimeout(max(0.05, timeout))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = transport.recv()
        except OSError:
            break
        if not data:
            break
        protocol.feed(data.decode("utf-8", "replace"))
        if any(protocol.get(device, P_EQUATORIAL) is not None
               for device in protocol.devices()):
            # A mount property arrived: the devices that publish it are known,
            # and waiting longer would only delay discovery.
            break
    devices = [
        device for device in protocol.devices()
        if protocol.get(device, P_EQUATORIAL) is not None
        or protocol.get(device, P_INFO) is not None
    ]
    return sorted(devices)


# @args: none
# @return: the INDIGO backend descriptor for the DeviceManager
def backend() -> MountBackend:
    def probe() -> tuple[BackendReason, str]:
        return probe_indigo()

    def mounts() -> list[MountInfo]:
        host, port = _host_port()
        transport = _SocketTransport(host, port)
        try:
            transport.open()
            found = enumerate_devices(transport)
        except Exception:  # noqa: BLE001 - a probe must never crash discovery
            found = []
        finally:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass
        if found:
            return [_mount_info(device) for device in found]
        # The server answered the TCP probe but listed no mount in the short
        # discovery window. Offer the configured default so the telescope panel
        # is usable; position() will say "no position" until the device answers.
        return [_mount_info(
            os.environ.get("SOLARSCRIBE_INDIGO_DEVICE", DEFAULT_DEVICE),
        )]

    def create(mount_id: str):
        return IndigoMount(mount_id=mount_id)

    return MountBackend(BACKEND, probe, mounts, create)
