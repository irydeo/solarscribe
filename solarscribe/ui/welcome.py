############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui welcome module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The inline welcome assistant of ADR-009 and ADR-011.
#
# Inline, not modal: a wizard that blocks the window on first start is exactly
# the gate the session flow forbids. The banner sits above the step rail, says
# the three things that make a first session work (position, camera, mount) and
# can be dismissed with "Remind me later". The observer can ignore it and still
# use every control.
#
# The position is the one field that cannot be skipped silently: without it the
# GOTO cannot compute where the Sun is, and the sentence says why.

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QLabel, QVBoxLayout, QWidget

from .ui_loader import load_ui

__all__ = ["WelcomeBanner"]


class WelcomeBanner(QFrame):
    answered = Signal(float, float, bool)   # lat, lon, do not show again
    dismissed = Signal(bool)                # do not show again

    # @args: parent - the Qt parent
    # @return: the banner, ready to be shown above the rail
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("welcome")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self._ui = ui
        self.lat_spin = self.findChild(QDoubleSpinBox, "welcomeLatSpin")
        self.lon_spin = self.findChild(QDoubleSpinBox, "welcomeLonSpin")
        self.camera_label = self.findChild(QLabel, "welcomeCameraStatus")
        self.mount_label = self.findChild(QLabel, "welcomeMountStatus")
        save = self.findChild(QWidget, "welcomeSaveButton")
        later = self.findChild(QWidget, "welcomeLaterButton")
        if save is not None:
            save.clicked.connect(self._save)
        if later is not None:
            later.clicked.connect(self._later)

    # @args: lat, lon - the observatory position already saved
    def set_location(self, lat: float, lon: float) -> None:
        if self.lat_spin is not None:
            self.lat_spin.setValue(float(lat))
        if self.lon_spin is not None:
            self.lon_spin.setValue(float(lon))

    # @args: none
    # @return: (lat, lon) currently in the fields
    def location(self) -> tuple[float, float]:
        lat = float(self.lat_spin.value()) if self.lat_spin else 0.0
        lon = float(self.lon_spin.value()) if self.lon_spin else 0.0
        return lat, lon

    # @args: camera - a short state; mount - a short state
    def set_device_status(self, camera: str, mount: str) -> None:
        if self.camera_label is not None:
            self.camera_label.setText(self.tr("Camera: {state}").format(state=camera))
        if self.mount_label is not None:
            self.mount_label.setText(self.tr("Mount: {state}").format(state=mount))

    # @args: lon, lat, dont_ask - accepted answer
    def _save(self) -> None:
        lat, lon = self.location()
        dont_ask = self._dont_ask()
        self.answered.emit(lat, lon, dont_ask)
        self.setVisible(False)

    # @args: none. The observer chose to fill it in later
    def _later(self) -> None:
        self.dismissed.emit(self._dont_ask())
        self.setVisible(False)

    # @args: none
    # @return: whether "Do not show this again" is ticked
    def _dont_ask(self) -> bool:
        check = self.findChild(QWidget, "welcomeDontAskCheck")
        return bool(check.isChecked()) if check is not None else False
