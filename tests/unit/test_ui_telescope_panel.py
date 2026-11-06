############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui telescope panel test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The telescope panel is the one screen that can move a heavy mount by accident,
# so every control is tested for two things: it calls the right contract method
# and it leaves a sentence a beginner can understand. The fake mount below is the
# minimal Mount surface; it is not the simulator, it records calls.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from solarscribe.devices.abc import (  # noqa: E402
    Axis, DeviceError, MountCaps, MountStatus,
)
from solarscribe.ui.telescope_panel import TelescopePanel  # noqa: E402


class FakeMount:
    def __init__(self, connected=True):
        self.connected = connected
        self.moves = []
        self.slews = []
        self.syncs = []
        self.stops = 0
        self.aborts = 0
        self.tracking = False
        self.parked = False
        self.fail_slew = False
        self.caps_enabled = True
        self._ra = 12.3456
        self._dec = -10.5

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def position(self):
        return self._ra, self._dec

    def move_axis(self, axis, rate):
        self.moves.append((axis, rate))

    def stop(self):
        self.stops += 1

    def slew(self, ra, dec):
        if self.fail_slew:
            raise DeviceError("gone", code="device_lost")
        self.slews.append((ra, dec))

    def sync(self, ra, dec):
        self.syncs.append((ra, dec))

    def set_tracking(self, on):
        self.tracking = bool(on)

    def park(self):
        self.parked = True

    def unpark(self):
        self.parked = False

    def abort_slew(self):
        self.aborts += 1

    def status(self):
        return MountStatus(tracking=self.tracking, slewing=False,
                           parked=self.parked)

    def capabilities(self):
        return MountCaps(
            supports_axis_rates=self.caps_enabled,
            can_slew=self.caps_enabled,
            can_sync=self.caps_enabled,
            can_track=self.caps_enabled,
            can_park=self.caps_enabled,
            can_abort=self.caps_enabled,
            reports_position_while_moving=True,
            min_rate_arcsec_s=0.1,
            max_rate_arcsec_s=800.0,
        )


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_connect_and_disconnect_say_what_happened(qapp):
    mount = FakeMount(connected=False)
    panel = TelescopePanel(mount=mount, mount_name="Test mount")
    panel.refresh()
    assert panel.state_label.text() == "Not connected"
    panel.connect_clicked()
    assert mount.connected
    assert panel.state_label.text() == "Connected"
    assert panel.connect_button.text() == "Disconnect"
    panel.connect_clicked()
    assert not mount.connected


def test_position_is_formatted_with_units(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    assert "12.34560" in panel.ra_value.text()
    assert "h" in panel.ra_value.text()
    assert "-10.5000" in panel.dec_value.text()
    assert "deg" in panel.dec_value.text()


def test_goto_sun_uses_the_provider(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount, sun_provider=lambda: (12.5, -10.25))
    panel.refresh()
    panel.goto_sun_clicked()
    assert mount.slews[-1] == (12.5, -10.25)
    assert "Slewing to the Sun" in panel.message()


def test_goto_sun_explains_a_missing_ephemeris(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    panel.goto_sun_clicked()
    assert "position is not available" in panel.message()
    assert mount.slews == []


def test_goto_coordinates_and_sync(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    panel.goto_ra.setValue(5.5)
    panel.goto_dec.setValue(20.0)
    panel.goto_clicked()
    assert mount.slews[-1] == (5.5, 20.0)
    panel.sync_clicked()
    assert mount.syncs[-1] == (5.5, 20.0)
    assert "Synced" in panel.message()


def test_move_buttons_use_the_selected_rate_and_stop(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    panel.rate_combo.setCurrentIndex(2)      # Sidereal: 15 arcsec/s
    panel.north_button.pressed.emit()
    assert mount.moves[-1] == (Axis.DEC, 15.0)
    panel.south_button.pressed.emit()
    assert mount.moves[-1] == (Axis.DEC, -15.0)
    panel.east_button.pressed.emit()
    assert mount.moves[-1] == (Axis.RA, 15.0)
    panel.west_button.pressed.emit()
    assert mount.moves[-1] == (Axis.RA, -15.0)
    panel.stop_clicked()
    assert mount.stops >= 1
    assert "Stopped" in panel.message()


def test_tracking_park_and_abort(qapp):
    mount = FakeMount()
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    panel.track_check.setChecked(True)
    assert mount.tracking
    panel.park_clicked()
    assert mount.parked
    assert panel.park_button.text() == "Unpark"
    panel.park_clicked()
    assert not mount.parked
    panel.abort_clicked()
    assert mount.aborts == 1


def test_a_mount_error_is_a_sentence_not_a_code(qapp):
    mount = FakeMount()
    mount.fail_slew = True
    panel = TelescopePanel(mount=mount, sun_provider=lambda: (1.0, 1.0))
    panel.refresh()
    panel.goto_sun_clicked()
    assert "disconnected" in panel.message()
    assert panel.dot.property("state") == "error"
    assert "device_lost" not in panel.message()


def test_unsupported_controls_are_disabled(qapp):
    mount = FakeMount()
    mount.caps_enabled = False
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    assert not panel.north_button.isEnabled()
    assert not panel.goto_button.isEnabled()
    assert not panel.goto_sun_button.isEnabled()


def test_moves_without_a_connection_explain_themselves(qapp):
    mount = FakeMount(connected=False)
    panel = TelescopePanel(mount=mount)
    panel.refresh()
    panel.north_button.pressed.emit()
    assert mount.moves == []
    assert "not connected" in panel.message().lower()
