############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui telescope panel module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The telescope panel of ADR-019, slimmed by ADR-026: the essentials only.
#
# The scan is a movement of the mount, so the observer must be able to connect,
# point, nudge, track and park without leaving the app. A solar observer never
# types a GOTO coordinate: the Sun is the only target, and its position comes
# from the ephemeris. The coordinate fields, sync and abort slew were removed
# with their live RA/Dec readout; the mount contract still has them for the
# engine and for a future advanced mode.
#
# Design decisions that matter for usability:
#   - One obvious danger exit: "Stop" stops every axis at once. It is always
#     enabled while connected, because a panic button that needs a state check
#     is not a panic button.
#   - The N/S/E/W buttons move while held and stop 150 ms after release. A click
#     that starts and stops in the same millisecond would look broken; the small
#     tail makes a tap move a visible amount without the mount running away.
#   - The rate is in arcsec/s with a word ("Sidereal: 15 arcsec/s") because the
#     Sun itself moves 15 arcsec/s: that comparison is what makes the number
#     meaningful.
#   - Every failure is a sentence. DeviceError.code is translated here and the
#     technical detail stays in the log (ADR-014); no raw SDK number is shown.
#   - "Go to the Sun" says why it cannot if the ephemeris is missing, instead of
#     silently doing nothing.

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

from solarscribe.devices.abc import Axis, DeviceError, Mount

from .ui_loader import load_ui

__all__ = ["TelescopePanel"]

# The rates the panel offers, in arcsec/s. 15 is the solar motion and 60 is a
# comfortable slew for a small correction; 1 is for the last few arcseconds.
RATES = (1.0, 5.0, 15.0, 60.0)


class TelescopePanel(QWidget):
    statusMessage = Signal(str)
    connectionChanged = Signal(bool)

    # @args: parent - the Qt parent; mount - an initial mount or None; name -
    #        what to show in the combo; sun_provider - callable for the GOTO
    # @return: the panel, with the controls disabled until a mount connects
    def __init__(self, parent=None, mount: Mount | None = None,
                 mount_name: str = "", sun_provider=None) -> None:
        super().__init__(parent)
        ui = load_ui("telescope_panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(ui)
        self._ui = ui
        self._mount: Mount | None = None
        self._mount_name = mount_name
        self._sun_provider = sun_provider
        self._factory = None
        self._caps = None
        self._move_token = 0
        self._timer = QTimer(self)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self.refresh)

        self._grab_widgets()
        self._populate_rates()
        self._wire()
        self.retranslate_ui()
        if mount is not None:
            self.set_mount(mount, mount_name)
        else:
            self._set_connected_ui(False)

    # @args: none. Finds the widgets the .ui defines
    def _grab_widgets(self) -> None:
        self.dot = self.findChild(QLabel, "mountStateDot")
        self.state_label = self.findChild(QLabel, "mountStateLabel")
        self.connect_button = self.findChild(QPushButton, "connectButton")
        self.mount_combo = self.findChild(QComboBox, "mountCombo")
        self.refresh_button = self.findChild(QPushButton, "mountRefreshButton")
        self.goto_sun_button = self.findChild(QPushButton, "gotoSunButton")
        self.north_button = self.findChild(QPushButton, "northButton")
        self.south_button = self.findChild(QPushButton, "southButton")
        self.east_button = self.findChild(QPushButton, "eastButton")
        self.west_button = self.findChild(QPushButton, "westButton")
        self.stop_button = self.findChild(QPushButton, "stopButton")
        self.rate_combo = self.findChild(QComboBox, "rateCombo")
        self.track_check = self.findChild(QWidget, "trackCheck")
        self.park_button = self.findChild(QPushButton, "parkButton")
        self.message_label = self.findChild(QLabel, "telescopeMessage")
        # The N/S/E/W pad is the only reason the panel needed 290 px. Narrow
        # buttons keep the right band at ~230 px and give the image the rest
        # (ADR-026); the letters are short and the tooltips carry the meaning.
        for button in (self.north_button, self.south_button,
                       self.east_button, self.west_button):
            if button is not None:
                button.setFixedWidth(38)
        if self.stop_button is not None:
            self.stop_button.setFixedWidth(56)
        if self.rate_combo is not None:
            self.rate_combo.setMinimumWidth(90)

    # @args: none. Fills the rate selector, with a word for each value
    def _populate_rates(self) -> None:
        if self.rate_combo is None:
            return
        self.rate_combo.blockSignals(True)
        self.rate_combo.clear()
        # The labels are added with their true meaning: the solar motion is the
        # yardstick, so "Sidereal" is not jargon but a reference the user knows.
        # The labels stay short enough for the 210 px right band; the tooltip
        # and the "Moving at N arcsec/s" sentence carry the full unit.
        self.rate_combo.addItem(self.tr("Fine 1″/s"), 1.0)
        self.rate_combo.addItem(self.tr("Slow 5″/s"), 5.0)
        self.rate_combo.addItem(self.tr("Sidereal 15″/s"), 15.0)
        self.rate_combo.addItem(self.tr("Fast 60″/s"), 60.0)
        self.rate_combo.setCurrentIndex(1)
        self.rate_combo.blockSignals(False)

    # @args: none. Connects every control to its mount call
    def _wire(self) -> None:
        if self.connect_button is not None:
            self.connect_button.clicked.connect(self.connect_clicked)
        if self.refresh_button is not None:
            self.refresh_button.clicked.connect(self.refresh_devices)
        if self.goto_sun_button is not None:
            self.goto_sun_button.clicked.connect(self.goto_sun_clicked)
        if self.north_button is not None:
            self.north_button.pressed.connect(
                lambda: self._start_move(Axis.DEC, +1.0))
            self.north_button.released.connect(self._release_move)
        if self.south_button is not None:
            self.south_button.pressed.connect(
                lambda: self._start_move(Axis.DEC, -1.0))
            self.south_button.released.connect(self._release_move)
        if self.east_button is not None:
            self.east_button.pressed.connect(
                lambda: self._start_move(Axis.RA, +1.0))
            self.east_button.released.connect(self._release_move)
        if self.west_button is not None:
            self.west_button.pressed.connect(
                lambda: self._start_move(Axis.RA, -1.0))
            self.west_button.released.connect(self._release_move)
        if self.stop_button is not None:
            self.stop_button.clicked.connect(self.stop_clicked)
        if self.track_check is not None:
            self.track_check.toggled.connect(self.tracking_toggled)
        if self.park_button is not None:
            self.park_button.clicked.connect(self.park_clicked)

    # @args: mount - a Mount implementation; name - what to show in the combo
    def set_mount(self, mount: Mount | None, name: str = "") -> None:
        if self._mount is not None and mount is not self._mount:
            try:
                self._mount.close()
            except DeviceError:
                pass
        self._mount = mount
        self._mount_name = name or self.tr("Mount")
        self._caps = None
        if self.mount_combo is not None:
            self.mount_combo.blockSignals(True)
            self.mount_combo.clear()
            self.mount_combo.addItem(self._mount_name if mount is not None
                                     else self.tr("No mount found"))
            self.mount_combo.blockSignals(False)
        self.refresh()
        self._timer.start()

    # @args: factory - callable returning a Mount or None; the "Find" button
    def set_mount_factory(self, factory) -> None:
        self._factory = factory

    # @args: provider - callable returning (ra hours, dec degrees) or None
    def set_sun_provider(self, provider) -> None:
        self._sun_provider = provider

    # @args: none
    # @return: the mount the panel is talking to
    def mount(self) -> Mount | None:
        return self._mount

    # @args: none
    # @return: the last sentence shown to the user, for the tests
    def message(self) -> str:
        return self.message_label.text() if self.message_label else ""

    # @args: none. Re-reads the state and the position; called by the timer
    def refresh(self) -> None:
        if self._mount is None:
            self._set_state("warning")
            self._set_text(self.state_label, self.tr("No mount"))
            self._set_connected_ui(False)
            return
        try:
            connected = self._mount.is_connected()
        except DeviceError as error:
            self._fail(error)
            return
        self._set_connected_ui(connected)
        if not connected:
            self._set_state("warning")
            self._set_text(self.state_label, self.tr("Not connected"))
            return

        self._set_state("ok")
        self._set_text(self.state_label, self.tr("Connected"))
        if self._caps is None:
            try:
                self._caps = self._mount.capabilities()
                self._apply_capabilities()
            except DeviceError as error:
                self._fail(error)
                return
        try:
            status = self._mount.status()
        except DeviceError as error:
            self._fail(error)
            return
        # The panel shows only what the observer needs for a solar scan: the
        # tracking switch and the park button. The mount's RA/Dec are not shown:
        # the Sun is the target, and a coordinate readout was one more number
        # without a decision attached (ADR-026).
        if self.track_check is not None:
            self.track_check.blockSignals(True)
            self.track_check.setChecked(bool(status.tracking))
            self.track_check.blockSignals(False)
        if self.park_button is not None:
            self.park_button.setText(self.tr("Unpark") if status.parked
                                     else self.tr("Park"))

    # @args: none. Rebuilds the combo from the factory, if there is one
    def refresh_devices(self) -> None:
        if self._factory is None:
            self._say(self.tr("Discovery is not available in this build. "
                              "The simulator is used instead."))
            return
        try:
            found = self._factory()
        except DeviceError as error:
            self._fail(error)
            return
        if found is None:
            self._say(self.tr("No mount was found. Check the cable and the "
                              "backend (ASCOM on Windows, INDI on Linux)."))
            return
        name = ""
        if isinstance(found, tuple):
            found, name = found
        self.set_mount(found, name or self.tr("Mount found"))

    # @args: none. Connect or disconnect, with the reason when it fails
    def connect_clicked(self) -> None:
        if self._mount is None:
            self._say(self.tr("There is no mount to connect. Open the device "
                              "diagnostics to see what is missing."))
            return
        try:
            if self._mount.is_connected():
                self._mount.close()
                self._say(self.tr("Disconnected. The telescope stopped."))
            else:
                self._mount.connect()
                self._say(self.tr("Connected. Check the position and the tracking "
                                  "before moving it."))
        except DeviceError as error:
            self._fail(error)
            return
        self.refresh()

    # @args: none. GOTO to the Sun by the local ephemeris
    def goto_sun_clicked(self) -> None:
        if not self._require_connected():
            return
        position = None
        if self._sun_provider is not None:
            try:
                position = self._sun_provider()
            except Exception:  # noqa: BLE001 - the provider is external
                position = None
        if position is None:
            self._say(self.tr("The Sun's position is not available: set your "
                              "observatory latitude and longitude in Tools, "
                              "Settings (Observatory), and the ephemeris module "
                              "must be present."))
            return
        ra, dec = position
        try:
            assert self._mount is not None
            self._mount.slew(float(ra) % 24.0, float(dec))
        except DeviceError as error:
            self._fail(error)
            return
        self._say(self.tr("Slewing to the Sun (RA {ra:.4f} h, Dec {dec:+.2f} "
                          "deg). When it stops, centre it on the slit.").format(
            ra=float(ra), dec=float(dec)))
        self.refresh()

    # @args: axis - RA or DEC; sign - direction of the rate
    def _start_move(self, axis: Axis, sign: float) -> None:
        if not self._require_connected():
            return
        self._move_token += 1
        rate = self._rate()
        try:
            assert self._mount is not None
            self._mount.move_axis(axis, sign * rate)
        except DeviceError as error:
            self._fail(error)
            return
        self._say(self.tr("Moving at {rate} arcsec/s. Release to stop.").format(
            rate=rate))

    # @args: none. Schedules the stop, cancelling a previous pending one
    def _release_move(self) -> None:
        token = self._move_token
        # A tap gets a 150 ms tail so the movement is visible; a later press
        # increments the token and the pending stop is ignored.
        QTimer.singleShot(150, lambda: self._delayed_stop(token))

    # @args: token - the move generation that scheduled the stop
    def _delayed_stop(self, token: int) -> None:
        if token != self._move_token or self._mount is None:
            return
        try:
            self._mount.stop()
        except DeviceError as error:
            self._fail(error)

    # @args: none. Stops every axis now
    def stop_clicked(self) -> None:
        self._move_token += 1
        if self._mount is None:
            self._say(self.tr("There is no mount to stop."))
            return
        try:
            self._mount.stop()
        except DeviceError as error:
            self._fail(error)
            return
        self._say(self.tr("Stopped. Every axis is at rest."))

    # @args: on - the new tracking state
    def tracking_toggled(self, on: bool) -> None:
        if not self._require_connected():
            if self.track_check is not None:
                self.track_check.blockSignals(True)
                self.track_check.setChecked(False)
                self.track_check.blockSignals(False)
            return
        try:
            assert self._mount is not None
            self._mount.set_tracking(bool(on))
        except DeviceError as error:
            self._fail(error)
            return
        self._say(self.tr("Tracking on. The Sun stays in the frame.") if on
                  else self.tr("Tracking off. The Sun will drift out of the frame."))
        self.refresh()

    # @args: none. Park or unpark, whichever the state allows
    def park_clicked(self) -> None:
        if not self._require_connected():
            return
        try:
            assert self._mount is not None
            status = self._mount.status()
            if status.parked:
                self._mount.unpark()
                self._say(self.tr("Unparked. The mount can move again."))
            else:
                self._mount.park()
                self._say(self.tr("Parked. The optics are safe to leave."))
        except DeviceError as error:
            self._fail(error)
            return
        self.refresh()

    # @args: none
    # @return: the rate selected in the combo, in arcsec/s
    def _rate(self) -> float:
        if self.rate_combo is None:
            return RATES[1]
        value = self.rate_combo.currentData()
        return float(value) if value is not None else RATES[1]

    # @args: none
    # @return: whether there is a connected mount; says why when there is not
    def _require_connected(self) -> bool:
        if self._mount is None:
            self._say(self.tr("Connect the mount first."))
            return False
        try:
            if not self._mount.is_connected():
                self._say(self.tr("The mount is not connected."))
                return False
        except DeviceError as error:
            self._fail(error)
            return False
        return True

    # @args: none. Enables the controls the capabilities allow
    def _apply_capabilities(self) -> None:
        caps = self._caps
        if caps is None:
            return
        for button, allowed in (
            (self.goto_sun_button, caps.can_slew),
            (self.north_button, caps.supports_axis_rates),
            (self.south_button, caps.supports_axis_rates),
            (self.east_button, caps.supports_axis_rates),
            (self.west_button, caps.supports_axis_rates),
            (self.track_check, caps.can_track),
            (self.park_button, caps.can_park),
        ):
            if button is not None:
                button.setEnabled(bool(allowed))
        if self.rate_combo is not None:
            self.rate_combo.setEnabled(bool(caps.supports_axis_rates))

    # @args: connected - whether the mount is open
    def _set_connected_ui(self, connected: bool) -> None:
        if self.connect_button is not None:
            self.connect_button.setText(self.tr("Disconnect") if connected
                                        else self.tr("Connect"))
        if not connected:
            for button in (self.goto_sun_button, self.north_button,
                           self.south_button, self.east_button,
                           self.west_button, self.track_check,
                           self.park_button):
                if button is not None:
                    button.setEnabled(False)
        elif self._caps is not None:
            self._apply_capabilities()
        # The stop button is the panic exit: it stays live while connected.
        if self.stop_button is not None:
            self.stop_button.setEnabled(True)

    # @args: error - the DeviceError to turn into a sentence
    def _fail(self, error: DeviceError) -> None:
        self._set_state("error")
        self._set_text(self.state_label, self.tr("Error"))
        self._say(self._error_text(error))

    # @args: error - a DeviceError
    # @return: a plain sentence; the technical detail stays in the log
    def _error_text(self, error: DeviceError) -> str:
        code = getattr(error, "code", "error")
        if code == "device_lost":
            return self.tr("The mount disconnected. Check the cable and connect "
                           "it again.")
        if code == "not_supported":
            return self.tr("This mount does not support that command. The panel "
                           "is showing only what it can do.")
        if code == "backend_missing":
            return self.tr("The mount backend is missing: install the ASCOM "
                           "platform on Windows or start indiserver on Linux.")
        if code == "platform_missing":
            return self.tr("The ASCOM platform is not installed on this computer.")
        if code == "server_missing":
            return self.tr("No INDI server is running. Start indiserver and try "
                           "again.")
        return self.tr("The mount refused the command. The technical detail is "
                       "in the log.")

    # @args: state - ok, warning or error
    def _set_state(self, state: str) -> None:
        if self.dot is None:
            return
        self.dot.setProperty("state", state)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)

    # @args: label - the label; text - what to show
    def _set_text(self, label: QLabel | None, text: str) -> None:
        if label is not None:
            label.setText(text)

    # @args: text - a sentence for the user, and the signal the window listens to
    def _say(self, text: str) -> None:
        if self.message_label is not None:
            self.message_label.setText(text)
        self.statusMessage.emit(text)

    # @args: none. Rebuilds the code-created strings
    def retranslate_ui(self) -> None:
        self._populate_rates()
        if self.mount_combo is not None and self.mount_combo.count() == 0:
            self.mount_combo.addItem(self.tr("No mount found"))

    # @args: none. Stops the position poll; called when the window closes
    def stop_polling(self) -> None:
        self._timer.stop()

    # @args: event - show: start the position poll
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    # @args: event - hide: stop the position poll
    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)
