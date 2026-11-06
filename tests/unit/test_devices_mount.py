############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - mount backend test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Mount backends (ADR-019): the INDI protocol and client, the LX200 fallback and
# the ASCOM platform detection. None of this touches a telescope: the transports
# are fakes, and the ASCOM test only proves the backend disappears with the
# right reason off Windows.

import pytest

from solarscribe.devices.abc import (
    Axis, BackendReason, DeviceError, Mount,
)
from solarscribe.devices.mount import default_mount_backends
from solarscribe.devices.mount.ascom import AscomMount, probe_ascom
from solarscribe.devices.mount.indi import (
    IndiMount, IndiProtocol, backend as indi_backend, probe_indi,
)
from solarscribe.devices.mount.indigo import (
    IndigoMount, IndigoProtocol, backend as indigo_backend,
    enumerate_devices, probe_indigo,
)
from solarscribe.devices.mount.lx200 import (
    Lx200Mount, format_dec, format_ra, parse_dec, parse_ra,
)


class FakeIndiTransport:
    # No recv(): the mount then skips the reader thread, which the unit test
    # does not need. The protocol is fed by hand.

    def __init__(self):
        self.sent = []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def send(self, text):
        self.sent.append(text)

    def close(self):
        self.closed = True


class FakeLx200Transport:
    def __init__(self):
        self.sent = []
        self.opened = False
        self.closed = False
        self.replies = {
            ":GVP#": "OnStep",
            ":GR#": "12:34:56#",
            ":GD#": "-16*30:00#",
        }

    def open(self):
        self.opened = True

    def query(self, command):
        self.sent.append(command)
        return self.replies.get(command, "")

    def send(self, command):
        self.sent.append(command)

    def close(self):
        self.closed = True


def test_indi_protocol_parses_position_and_state():
    protocol = IndiProtocol()
    protocol.feed(
        '<setNumberVector device="Telescope" name="EQUATORIAL_EOD_COORD" '
        'state="Ok"><oneNumber name="RA">12.5</oneNumber>'
        '<oneNumber name="DEC">-16.25</oneNumber></setNumberVector>'
    )
    assert protocol.number("Telescope", "EQUATORIAL_EOD_COORD", "RA") == 12.5
    assert protocol.number("Telescope", "EQUATORIAL_EOD_COORD", "DEC") == -16.25
    assert protocol.state("Telescope", "EQUATORIAL_EOD_COORD") == "Ok"


def test_indi_protocol_buffers_a_split_element():
    protocol = IndiProtocol()
    protocol.feed('<setNumberVector device="Telescope" name="EQUATORIAL_EOD_COORD">')
    assert protocol.get("Telescope", "EQUATORIAL_EOD_COORD") is None
    protocol.feed(
        '<oneNumber name="RA">1.0</oneNumber>'
        '<oneNumber name="DEC">2.0</oneNumber></setNumberVector>'
    )
    assert protocol.number("Telescope", "EQUATORIAL_EOD_COORD", "RA") == 1.0


def test_indi_mount_connects_moves_and_reads_position():
    transport = FakeIndiTransport()
    mount = IndiMount(transport=transport)
    assert isinstance(mount, Mount)
    mount.connect()
    assert transport.opened
    assert any("getProperties" in sent for sent in transport.sent)
    assert any("CONNECTION" in sent for sent in transport.sent)

    mount.protocol.feed(
        '<setNumberVector device="Telescope" name="EQUATORIAL_EOD_COORD" '
        'state="Ok"><oneNumber name="RA">12.5</oneNumber>'
        '<oneNumber name="DEC">-16.25</oneNumber></setNumberVector>'
    )
    assert mount.position() == pytest.approx((12.5, -16.25))

    mount.move_axis(Axis.RA, 10.0)
    joined = "\n".join(transport.sent)
    assert "TELESCOPE_MOTION_WE" in joined
    assert 'name="MOTION_EAST">On' in joined
    assert "TELESCOPE_MOTION_RATE" in joined

    mount.stop()
    assert 'name="MOTION_EAST">Off' in transport.sent[-2]

    mount.slew(3.0, 4.0)
    assert "TARGET_EQUATORIAL" in transport.sent[-1]
    assert mount.status().slewing

    mount.abort_slew()
    assert not mount.status().slewing

    mount.set_tracking(True)
    assert mount.status().tracking
    mount.park()
    assert mount.status().parked
    with pytest.raises(DeviceError):
        mount.move_axis(Axis.RA, 1.0)
    mount.unpark()
    assert not mount.status().parked
    mount.close()
    assert transport.closed


def test_indi_probe_reports_a_missing_server(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", refuse)
    reason, detail = probe_indi("127.0.0.1", 7624)
    assert reason is BackendReason.SERVER_MISSING
    assert "7624" in detail


def test_indi_backend_is_unavailable_without_a_server(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", refuse)
    backend = indi_backend()
    reason, _ = backend.probe()
    assert reason is BackendReason.SERVER_MISSING
    assert backend.mounts() == []


def test_ascom_is_unsupported_off_windows():
    # This suite runs on Linux; the backend must degrade with a stable reason,
    # not with an ImportError from a missing pywin32.
    reason, detail = probe_ascom()
    assert reason is BackendReason.OS_UNSUPPORTED
    assert "Windows" in detail


def test_ascom_mount_proxies_a_com_object():
    class FakeTelescope:
        def __init__(self):
            self.Connected = False
            self.Tracking = False
            self.Slewing = False
            self.AtPark = False
            self.RightAscension = 12.0
            self.Declination = -16.0
            self.calls = []

        def MoveAxis(self, axis, rate):
            self.calls.append(("MoveAxis", axis, rate))

        def SlewToCoordinates(self, ra, dec):
            self.calls.append(("Slew", ra, dec))

        def SyncToCoordinates(self, ra, dec):
            self.calls.append(("Sync", ra, dec))

        def Park(self):
            self.AtPark = True

        def Unpark(self):
            self.AtPark = False

        def AbortSlew(self):
            self.Slewing = False

    telescope = FakeTelescope()
    mount = AscomMount("OnStep.Telescope", telescope=telescope)
    mount.connect()
    assert mount.is_connected()
    assert mount.position() == pytest.approx((12.0, -16.0))
    mount.move_axis(Axis.RA, 3600.0)          # 1 deg/s in ASCOM units
    assert telescope.calls[-1] == ("MoveAxis", 0, 1.0)
    mount.slew(5.0, 6.0)
    assert telescope.calls[-1] == ("Slew", 5.0, 6.0)
    mount.sync(5.0, 6.0)
    assert telescope.calls[-1] == ("Sync", 5.0, 6.0)
    mount.set_tracking(True)
    assert mount.status().tracking
    mount.park()
    assert mount.status().parked
    mount.abort_slew()
    mount.close()
    assert not mount.is_connected()


def test_lx200_position_parsing_and_formatting():
    assert parse_ra("12:34:56#") == pytest.approx(12.0 + 34 / 60 + 56 / 3600)
    assert parse_dec("-16*30:00#") == pytest.approx(-16.5)
    assert parse_dec("+10*15:30#") == pytest.approx(10.0 + 15 / 60 + 30 / 3600)
    assert format_ra(12.5) == "12:30:00"
    assert format_dec(-16.5) == "-16*30:00"


def test_lx200_mount_connects_and_commands_the_mount():
    transport = FakeLx200Transport()
    mount = Lx200Mount(transport=transport)
    assert isinstance(mount, Mount)
    mount.connect()
    assert transport.opened
    assert ":GVP#" in transport.sent
    assert mount.position() == pytest.approx((12.0 + 34 / 60 + 56 / 3600, -16.5))

    mount.move_axis(Axis.RA, 10.0)
    assert transport.sent[-2:] == [":RG#", ":Me#"]
    mount.move_axis(Axis.DEC, -10.0)
    assert transport.sent[-1] == ":Ms#"
    mount.stop()
    assert transport.sent[-1] == ":Q#"

    mount.slew(1.0, 2.0)
    assert transport.sent[-3:] == [":Sr01:00:00#", ":Sd+02*00:00#", ":MS#"]
    assert mount.status().slewing

    mount.sync(1.0, 2.0)
    assert transport.sent[-1] == ":CM#"
    mount.set_tracking(True)
    assert mount.status().tracking
    mount.park()
    assert mount.status().parked
    mount.unpark()
    assert not mount.status().parked
    mount.close()
    assert transport.closed


def test_default_mount_backends_list_the_simulator_first():
    backends = default_mount_backends()
    names = [b.name for b in backends]
    assert names[0] == "sim"
    assert "ascom" in names and "indi" in names and "native/lx200" in names
    reason, _ = backends[0].probe()
    assert reason is BackendReason.AVAILABLE
    assert backends[0].mounts()[0].mount_id == "sim:mount0"


# --- ASCOM capabilities: a driver that cannot move an axis must say so before
# the scan, not throw a COM error mid-barrido -------------------------------

def test_ascom_capabilities_follow_the_driver_flags_and_axis_rates():
    class Rates:
        Count = 1

        def Item(self, index):
            class Rate:
                Minimum = 0.001      # deg/s = 3.6 arcsec/s
                Maximum = 0.5        # deg/s = 1800 arcsec/s
            return Rate()

    class Telescope:
        Connected = False
        Tracking = False
        Slewing = False
        AtPark = False
        RightAscension = 1.0
        Declination = 2.0

        def CanMoveAxis(self, axis):
            return axis == 0          # RA only: this mount cannot rate-move Dec

        def AxisRates(self, axis):
            return Rates()

        def MoveAxis(self, axis, rate):
            pass

    mount = AscomMount("Fake.Telescope", telescope=Telescope())
    mount.connect()
    caps = mount.capabilities()
    assert caps.supports_axis_rates
    assert caps.min_rate_arcsec_s == pytest.approx(3.6)
    assert caps.max_rate_arcsec_s == pytest.approx(1800.0)
    mount.move_axis(Axis.RA, 10.0)
    with pytest.raises(DeviceError) as exc:
        mount.move_axis(Axis.DEC, 10.0)
    assert exc.value.code == "not_supported"
    mount.close()


# --- INDIGO: JSON protocol, framing and the mount command sequence ----------

class FakeIndigoTransport:
    # No recv(): the mount then skips the reader thread, which the unit test
    # does not need. Messages are fed to the protocol by hand.

    def __init__(self):
        self.sent = []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True

    def send(self, text):
        import json
        self.sent.append(json.loads(text))

    def close(self):
        self.closed = True


def _sent_vectors(transport, name):
    # @return: the payloads of the new*Vector messages for one property
    found = []
    for message in transport.sent:
        for kind, payload in message.items():
            if kind.startswith("new") and payload.get("name") == name:
                found.append(payload)
    return found


def test_indigo_protocol_parses_concatenated_and_split_messages():
    import json

    protocol = IndigoProtocol()
    first = json.dumps({
        "setNumberVector": {
            "device": "Telescope", "name": "MOUNT_EQUATORIAL_COORDINATES",
            "state": "Ok",
            "items": [{"name": "RA", "value": 12.5},
                      {"name": "DEC", "value": -16.25}],
        },
    })
    second = json.dumps({
        "setSwitchVector": {
            "device": "Telescope", "name": "MOUNT_TRACKING", "state": "Ok",
            "items": [{"name": "ON", "value": True}],
        },
    })
    text = first + second
    protocol.feed(text[:20])
    assert protocol.number("Telescope", "MOUNT_EQUATORIAL_COORDINATES", "RA") is None
    protocol.feed(text[20:])
    assert protocol.number("Telescope", "MOUNT_EQUATORIAL_COORDINATES", "RA") == 12.5
    assert protocol.value("Telescope", "MOUNT_TRACKING", "ON") is True


def test_indigo_mount_connects_moves_and_reads_position():
    import json

    transport = FakeIndigoTransport()
    mount = IndigoMount(transport=transport, device="Telescope",
                        mount_id="indigo:Telescope")
    assert isinstance(mount, Mount)
    mount.connect()
    assert transport.opened
    assert transport.sent[0]["getProperties"]["version"] == 0x0200
    connection = _sent_vectors(transport, "CONNECTION")[-1]
    assert {"name": "CONNECTED", "value": True} in connection["items"]

    mount.protocol.feed(json.dumps({
        "setNumberVector": {
            "device": "Telescope", "name": "MOUNT_EQUATORIAL_COORDINATES",
            "state": "Ok",
            "items": [{"name": "RA", "value": 12.5},
                      {"name": "DEC", "value": -16.25}],
        },
    }))
    assert mount.position() == pytest.approx((12.5, -16.25))

    mount.move_axis(Axis.RA, 10.0)
    rate = _sent_vectors(transport, "MOUNT_SLEW_RATE")[-1]
    assert {"name": "GUIDE", "value": True} in rate["items"]
    motion = _sent_vectors(transport, "MOUNT_MOTION_RA")[-1]
    assert {"name": "EAST", "value": True} in motion["items"]
    assert {"name": "WEST", "value": False} in motion["items"]

    mount.move_axis(Axis.DEC, -300.0)
    assert {"name": "CENTERING", "value": True} in (
        _sent_vectors(transport, "MOUNT_SLEW_RATE")[-1]["items"]
    )
    assert {"name": "SOUTH", "value": True} in (
        _sent_vectors(transport, "MOUNT_MOTION_DEC")[-1]["items"]
    )

    mount.stop()
    assert {"name": "EAST", "value": False} in (
        _sent_vectors(transport, "MOUNT_MOTION_RA")[-1]["items"]
    )
    assert {"name": "NORTH", "value": False} in (
        _sent_vectors(transport, "MOUNT_MOTION_DEC")[-1]["items"]
    )

    mount.slew(3.0, 4.0)
    assert {"name": "TRACK", "value": True} in (
        _sent_vectors(transport, "MOUNT_ON_COORDINATES_SET")[-1]["items"]
    )
    target = _sent_vectors(transport, "MOUNT_EQUATORIAL_COORDINATES")[-1]
    assert {"name": "RA", "value": 3.0} in target["items"]
    assert {"name": "DEC", "value": 4.0} in target["items"]
    assert mount.status().slewing

    mount.abort_slew()
    assert not mount.status().slewing
    assert {"name": "ABORT_MOTION", "value": True} in (
        _sent_vectors(transport, "MOUNT_ABORT_MOTION")[-1]["items"]
    )

    mount.set_tracking(True)
    assert mount.status().tracking
    mount.park()
    assert mount.status().parked
    with pytest.raises(DeviceError):
        mount.move_axis(Axis.RA, 1.0)
    mount.unpark()
    assert not mount.status().parked

    mount.close()
    assert transport.closed
    assert {"name": "CONNECTED", "value": False} in (
        _sent_vectors(transport, "CONNECTION")[-1]["items"]
    )


def test_indigo_status_prefers_the_servers_own_properties():
    import json

    transport = FakeIndigoTransport()
    mount = IndigoMount(transport=transport, device="Telescope")
    mount.connect()
    mount.protocol.feed(json.dumps({
        "setSwitchVector": {
            "device": "Telescope", "name": "MOUNT_TRACKING", "state": "Ok",
            "items": [{"name": "ON", "value": False},
                      {"name": "OFF", "value": True}],
        },
    }))
    mount.protocol.feed(json.dumps({
        "setSwitchVector": {
            "device": "Telescope", "name": "MOUNT_PARK", "state": "Ok",
            "items": [{"name": "PARKED", "value": True},
                      {"name": "UNPARKED", "value": False}],
        },
    }))
    status = mount.status()
    assert not status.tracking
    assert status.parked
    mount.close()


def test_indigo_probe_reports_a_missing_server(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", refuse)
    reason, detail = probe_indigo("127.0.0.1", 7624)
    assert reason is BackendReason.SERVER_MISSING
    assert "7624" in detail


def test_indigo_backend_degrades_without_a_server(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", refuse)
    backend = indigo_backend()
    reason, _ = backend.probe()
    assert reason is BackendReason.SERVER_MISSING
    assert backend.mounts() == []
    names = [b.name for b in default_mount_backends()]
    assert "indigo" in names


def test_indigo_discovery_lists_only_devices_that_publish_a_mount():
    import json

    class ServerTransport:
        def __init__(self, messages):
            self.messages = [json.dumps(message).encode()
                             for message in messages]
            self.sent = []

        def send(self, text):
            self.sent.append(json.loads(text))

        def recv(self):
            return self.messages.pop(0) if self.messages else b""

    transport = ServerTransport([
        {"setNumberVector": {
            "device": "CCD Simulator", "name": "CCD_INFO", "state": "Ok",
            "items": [
                {"name": "WIDTH", "value": 100},
                {"name": "HEIGHT", "value": 100},
            ],
        }},
        {"defNumberVector": {
            "device": "Telescope Simulator", "name":
            "MOUNT_EQUATORIAL_COORDINATES", "state": "Ok",
            "items": [
                {"name": "RA", "value": 1.0},
                {"name": "DEC", "value": 2.0},
            ],
        }},
    ])
    devices = enumerate_devices(transport, timeout=1.0)
    assert devices == ["Telescope Simulator"]
    assert transport.sent[0]["getProperties"]["version"] == 0x0200


def test_indi_capabilities_follow_the_definitions_the_server_sends():
    transport = FakeIndiTransport()
    mount = IndiMount(transport=transport)
    mount.connect()
    # Before any definition arrives the backend must not disable the panel.
    optimistic = mount.capabilities()
    assert optimistic.supports_axis_rates
    assert optimistic.can_park

    for xml in (
        '<defSwitchVector device="Telescope" name="TELESCOPE_MOTION_WE">'
        '<defSwitch name="MOTION_EAST">Off</defSwitch>'
        '<defSwitch name="MOTION_WEST">Off</defSwitch></defSwitchVector>',
        '<defSwitchVector device="Telescope" name="TELESCOPE_MOTION_NS">'
        '<defSwitch name="MOTION_NORTH">Off</defSwitch>'
        '<defSwitch name="MOTION_SOUTH">Off</defSwitch></defSwitchVector>',
        '<defSwitchVector device="Telescope" name="ON_COORD_SET">'
        '<defSwitch name="SLEW">On</defSwitch></defSwitchVector>',
        '<defSwitchVector device="Telescope" name="TELESCOPE_PARK">'
        '<defSwitch name="PARK">Off</defSwitch></defSwitchVector>',
        '<defNumberVector device="Telescope" name="TELESCOPE_MOTION_RATE">'
        '<defNumber name="MOTION_RATE" min="0.5" max="120">1</defNumber>'
        '</defNumberVector>',
    ):
        mount.protocol.feed(xml)
    caps = mount.capabilities()
    assert caps.supports_axis_rates
    assert caps.can_slew and caps.can_sync
    assert caps.can_park
    assert not caps.can_abort          # TELESCOPE_ABORT_MOTION was not defined
    assert caps.min_rate_arcsec_s == pytest.approx(0.5)
    assert caps.max_rate_arcsec_s == pytest.approx(120.0)
    mount.close()
