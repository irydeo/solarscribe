############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui camera panel module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The camera half of the device panel, mirroring the telescope panel (ADR-019
# and the ARCHITECTURE 2.1 discovery contract).
#
# Discovery talks to every backend and can block, so it runs in a QThread and
# the panel stays responsive. The list always contains the simulator; a native
# camera appears only when its SDK is installed, and the row says which backend
# it came from. The panel never opens a camera on its own: it emits the choice,
# the Session restores the ROI preset that fits that sensor, and only then does
# the CaptureEngine open the device.
#
# The simulator is labelled in the state line. A test pattern that looks like a
# camera is the easiest way to fool an observer, and a shame to hide.

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget

from solarscribe.devices.abc import CameraInfo, DeviceError

from .ui_loader import load_ui

__all__ = ["CameraPanel"]


class _Discovery(QThread):
    # One discovery pass. The manager caches its probes, so a second Find is
    # cheap; the first one may touch USB or a TCP server.
    found = Signal(object)
    failed = Signal(str)

    # @args: manager - the DeviceManager to ask
    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager

    # @args: none
    def run(self) -> None:
        try:
            cameras = self.manager.cameras()
        except Exception as error:  # noqa: BLE001 - the panel reports it
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.found.emit(cameras)


class CameraPanel(QWidget):
    cameraChosen = Signal(object, object)   # CameraInfo, Camera
    closeRequested = Signal()

    def __init__(self, manager=None, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("camera_panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(ui)
        self._ui = ui
        self.manager = manager
        self._thread: _Discovery | None = None
        self._cameras: list[CameraInfo] = []
        self._current_id = ""
        self.dot = self.findChild(QLabel, "cameraStateDot")
        self.state_label = self.findChild(QLabel, "cameraStateLabel")
        self.combo = self.findChild(QComboBox, "cameraCombo")
        self.find_button = self.findChild(QPushButton, "cameraFindButton")
        self.open_button = self.findChild(QPushButton, "cameraOpenButton")
        self.close_button = self.findChild(QPushButton, "cameraCloseButton")
        self.message_label = self.findChild(QLabel, "cameraMessage")
        self.model_value = self.findChild(QLabel, "cameraModelValue")
        self.sensor_value = self.findChild(QLabel, "cameraSensorValue")
        self.roi_value = self.findChild(QLabel, "cameraRoiValue")
        self.rate_value = self.findChild(QLabel, "cameraRateValue")
        if self.find_button is not None:
            self.find_button.clicked.connect(self.refresh)
        if self.open_button is not None:
            self.open_button.clicked.connect(self._open)
        if self.close_button is not None:
            self.close_button.clicked.connect(self.closeRequested.emit)
        self._set_state("muted")
        self._set_text(self.state_label, self.tr("No camera"))
        if self.combo is not None:
            self.combo.addItem(self.tr("Press Find to search"))

    # @args: manager - the DeviceManager to use
    def set_manager(self, manager) -> None:
        self.manager = manager

    # @args: none. Waits for a discovery thread before the window goes away
    def shutdown(self) -> None:
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait(3000)
        self._thread = None

    # @args: none. Starts discovery in a thread
    def refresh(self) -> None:
        if self.manager is None:
            self._say(self.tr("Discovery is not available in this build."))
            return
        if self._thread is not None and self._thread.isRunning():
            return
        if self.find_button is not None:
            self.find_button.setEnabled(False)
        self._say(self.tr("Searching for cameras..."))
        self._thread = _Discovery(self.manager, self)
        self._thread.found.connect(self._populate)
        self._thread.failed.connect(self._discovery_failed)
        self._thread.finished.connect(self._discovery_done)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    # @args: none. Synchronous discovery for tests and for the CLI-style check
    def refresh_sync(self) -> None:
        if self.manager is None:
            return
        try:
            cameras = self.manager.cameras()
        except Exception as error:  # noqa: BLE001
            self._discovery_failed(f"{type(error).__name__}: {error}")
            return
        self._populate(cameras)
        self._discovery_done()

    # @args: cameras - the CameraInfo list
    def _populate(self, cameras) -> None:
        self._cameras = list(cameras)
        if self.combo is None:
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        for info in self._cameras:
            name = f"{info.model} [{info.backend}]"
            if info.backend == "sim":
                name = self.tr("{model} (simulator)").format(model=info.model)
            self.combo.addItem(name, info)
            if info.camera_id == self._current_id:
                self.combo.setCurrentIndex(self.combo.count() - 1)
        self.combo.blockSignals(False)
        if not self._cameras:
            self._say(self.tr(
                "No camera was found. The simulator should always be there; "
                "if it is not, the device layer is not in this build."))
        else:
            self._say(self.tr("Found {count} camera(s). Choose one and press "
                              "Open.").format(count=len(self._cameras)))

    # @args: detail - the discovery error for the log
    def _discovery_failed(self, detail: str) -> None:
        logging.getLogger("solarscribe").info("camera discovery failed: %s",
                                              detail)
        self._say(self.tr(
            "Discovery failed. Check the device diagnostics for the backend "
            "list; the log has the technical detail."))

    # @args: none. Re-enables Find
    def _discovery_done(self) -> None:
        if self.find_button is not None:
            self.find_button.setEnabled(True)
        self._thread = None

    # @args: none. Opens the selected camera and emits it
    def _open(self) -> None:
        info = self.current_info()
        if info is None or self.manager is None:
            self._say(self.tr("Choose a camera first."))
            return
        try:
            camera = self.manager.open_camera(info.camera_id)
        except DeviceError as error:
            self._say(self._error_text(error))
            return
        self.cameraChosen.emit(info, camera)

    # @args: none
    # @return: the CameraInfo selected in the combo
    def current_info(self) -> CameraInfo | None:
        if self.combo is None:
            return None
        data = self.combo.currentData()
        return data if isinstance(data, CameraInfo) else None

    # @args: info - the live camera, or None; simulated - whether it is the
    #        scene simulator; streaming - whether the stream is running
    def set_current(self, info, simulated: bool = False,
                    streaming: bool = False) -> None:
        self._current_id = info.camera_id if info is not None else ""
        if info is None:
            self._set_state("warning")
            self._set_text(self.state_label, self.tr("No camera"))
            self._set_text(self.model_value, "--")
            self._set_text(self.sensor_value, "--")
            self._set_text(self.roi_value, "--")
            self._set_text(self.rate_value, "--")
            return
        if simulated:
            # The 210 px right band cannot hold "Simulator, streaming"; the dot
            # already says streaming, and the message below says simulator.
            self._set_state("ok" if streaming else "warning")
            self._set_text(self.state_label, self.tr("Simulator"))
        else:
            self._set_state("ok" if streaming else "warning")
            self._set_text(self.state_label,
                           self.tr("Streaming") if streaming
                           else self.tr("Open, stopped"))
        self._set_text(self.model_value, f"{info.vendor} {info.model}")
        caps = info.caps.roi
        self._set_text(self.sensor_value, self.tr("{width} x {height} px").format(
            width=caps.max_width, height=caps.max_height))
        if self.combo is not None:
            index = self.combo.findData(info)
            if index < 0:
                for position in range(self.combo.count()):
                    data = self.combo.itemData(position)
                    if getattr(data, "camera_id", "") == info.camera_id:
                        index = position
                        break
            if index < 0 and self.combo.count() == 0:
                # Before the first Find, the live camera is still selectable, so
                # the panel never shows an empty combo while a camera streams.
                name = self.tr("{model} (simulator)").format(
                    model=info.model) if simulated else info.model
                self.combo.addItem(name, info)
                index = 0
            if index >= 0:
                self.combo.blockSignals(True)
                self.combo.setCurrentIndex(index)
                self.combo.blockSignals(False)

    # @args: roi - the live capture rectangle in sensor pixels
    def set_roi(self, roi) -> None:
        if roi is None:
            self._set_text(self.roi_value, "--")
            return
        x, y, width, height = roi
        self._set_text(self.roi_value, self.tr("{x}, {y}, {width} x {height}").format(
            x=int(x), y=int(y), width=int(width), height=int(height)))

    # @args: counters - the StreamCounters
    def set_counters(self, counters) -> None:
        self._set_text(self.rate_value, self.tr("{fps:.0f} fps").format(
            fps=float(counters.fps)))

    # @args: none
    # @return: the last sentence, for the tests
    def message(self) -> str:
        return self.message_label.text() if self.message_label else ""

    # @args: state - ok, warning, error or muted
    def _set_state(self, state: str) -> None:
        if self.dot is None:
            return
        self.dot.setProperty("state", state)
        self.dot.style().unpolish(self.dot)
        self.dot.style().polish(self.dot)

    # @args: label - a label; text - its text
    def _set_text(self, label: QLabel | None, text: str) -> None:
        if label is not None:
            label.setText(text)

    # @args: text - a sentence
    def _say(self, text: str) -> None:
        if self.message_label is not None:
            self.message_label.setText(text)

    # @args: error - a DeviceError
    # @return: a sentence with no raw code (ADR-014)
    def _error_text(self, error: DeviceError) -> str:
        code = getattr(error, "code", "error")
        if code == "unknown_camera":
            return self.tr("That camera is no longer there. Press Find again.")
        if code == "device_lost":
            return self.tr("The camera disconnected. Check the cable and find it "
                           "again.")
        if code == "sdk_missing":
            return self.tr("The camera's SDK is not installed on this machine.")
        return self.tr("The camera could not be opened. The device diagnostics "
                       "say which backend refused it.")
