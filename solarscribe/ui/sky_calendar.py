############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui sky calendar module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Tools -> Sky calendar -> Sun (ADR-009).
#
# The tab carries what the SHG needs from the calendar: the date, the solar
# angular diameter (it sets the length of a sweep), the Sun's position (the GOTO
# uses it), the Carrington rotation and the heliographic centre. Everything is
# computed locally by the ephemeris module, with no network (ADR-021).
#
# Honesty rule: when the ephemeris module is not in the build, the dialog says
# so and leaves the figures as "--". A guessed solar diameter would be worse
# than an empty field, because the scan geometry would be built on it.
#
# The only network use in the whole app is the optional SDO image, and it is
# off by default and asks first.

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QVBoxLayout, QWidget

from .sun_disc import SunDiscWidget
from .ui_loader import load_ui, replace_widget

__all__ = ["SkyCalendarDialog"]


class SkyCalendarDialog(QDialog):
    imageRequested = Signal(bool)

    # @args: info - the Sun figures, or {} when the ephemeris is absent;
    #        parent - the Qt parent
    # @return: the dialog on the Sun tab
    def __init__(self, info: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("sky_calendar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(False)
        self._ui = ui
        self._fetcher = None
        self._info: dict = {}
        self.disc = replace_widget(ui, "sunDiscHost", SunDiscWidget(ui))
        close = self.findChild(QWidget, "calendarCloseButton")
        if close is not None:
            close.clicked.connect(self.accept)
        sdo = self.findChild(QCheckBox, "sunSdoCheck")
        if sdo is not None:
            sdo.toggled.connect(self._image_toggled)
        refresh = self.findChild(QWidget, "sunRefreshButton")
        if refresh is not None:
            refresh.clicked.connect(self._refresh_image)
        self.set_sun_info(info or {})

    # @args: fetcher - callable returning a QImage or None; without it the
    #                 image option is disabled and says why
    def set_image_fetcher(self, fetcher) -> None:
        self._fetcher = fetcher
        sdo = self.findChild(QCheckBox, "sunSdoCheck")
        if sdo is not None:
            sdo.setEnabled(fetcher is not None)
            if fetcher is None:
                sdo.setToolTip(self.tr(
                    "The image service is not available in this build. The "
                    "schematic disk is used instead."))

    # @args: info - the figures of the Sun tab. Missing keys stay as "--" and
    #              the empty-state label explains why
    def set_sun_info(self, info: dict) -> None:
        self._info = dict(info or {})
        empty = self.findChild(QWidget, "sunEmptyState")
        if empty is not None:
            empty.setVisible(not self._info)
        if not self._info:
            return
        self._set("sunDateValue", str(self._info.get("date") or "--"))
        diameter = self._info.get("diameter_arcmin")
        self._set("sunDiameterValue",
                  self.tr("{value:.2f} arcmin").format(value=float(diameter))
                  if diameter is not None else "--")
        ra = self._info.get("ra_hours")
        self._set("sunRaValue",
                  self.tr("{value:.4f} h").format(value=float(ra))
                  if ra is not None else "--")
        dec = self._info.get("dec_deg")
        self._set("sunDecValue",
                  self.tr("{value:+.2f} deg").format(value=float(dec))
                  if dec is not None else "--")
        rotation = self._info.get("rotation")
        self._set("sunRotationValue",
                  self.tr("{value:+.2f} deg").format(value=float(rotation))
                  if rotation is not None else "--")
        helio = self._info.get("heliographic")
        self._set("sunHeliographicValue", str(helio) if helio else self.tr(
            "Not available"))
        source = self._info.get("source")
        if source == "simulator":
            self._set("sunImageSource", self.tr(
                "Simulated values: the local ephemeris module is not available "
                "in this build."))
        else:
            self._set("sunImageSource", self.tr(
                "Computed locally from your observatory position."))

    # @args: image - a real Sun image; replaces the schematic disk
    def set_sun_image(self, image: QImage | None) -> None:
        self.disc.set_background(image)
        if image is not None:
            self._set("sunImageSource", self.tr(
                "Image from the SDO service; the overlay is still ours."))

    # @args: none
    # @return: the figures currently shown
    def info(self) -> dict:
        return dict(self._info)

    # @args: name - the label object name; text - its new text
    def _set(self, name: str, text: str) -> None:
        label = self.findChild(QLabel, name)
        if label is not None:
            label.setText(text)

    # @args: checked - the optional SDO image switch
    def _image_toggled(self, checked: bool) -> None:
        if checked:
            self._refresh_image()
        else:
            self.disc.set_background(None)
        self.imageRequested.emit(bool(checked))

    # @args: none. Calls the fetcher, if there is one, and reports the outcome
    def _refresh_image(self) -> None:
        if self._fetcher is None:
            self._set("sunImageSource", self.tr(
                "The image service is not available in this build. The "
                "schematic disk is used instead."))
            return
        try:
            image = self._fetcher()
        except Exception:  # noqa: BLE001 - a network call may fail in any way
            image = None
        if image is None:
            self._set("sunImageSource", self.tr(
                "The image could not be downloaded. The schematic disk is used "
                "instead; the figures are unaffected."))
            return
        self.set_sun_image(image)
