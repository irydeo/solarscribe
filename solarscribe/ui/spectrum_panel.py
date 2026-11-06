############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui spectrum panel module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The right-side spectral line panel.
#
# The user asked for the names in a panel next to the video, not drawn over it:
# the video is where the observer judges the exposure and the slit, and a label
# on every line would bury the spectrum. This panel is the reference list, and
# the toolbar's "Identify lines" check shows and hides it.
#
# It is a custom widget, so it enters the .ui through a placeholder and
# replace_widget (ADR-009). The table is not painted by hand: QTableWidget is
# what gives the observer a readable, sortable list without a second toolkit.
#
# Honesty rules, in the order they are checked:
#   - dispersion 0: identification is off, and the panel says where to set it;
#   - no frame: there is no spectrum to read;
#   - no line or no match: say so, with the count of detected dips;
#   - confidence below the configured minimum: the pattern does not support the
#     names, so the names are not shown. A wrong name is worse than no name.
#
# The identification runs in LineIdentifierWorker, a QThread with a one-slot
# queue. The GUI hands it a 1D profile copy, never the live frame buffer; the
# queue drops an older profile, so a slow identification cannot accumulate and
# never blocks capture.

from __future__ import annotations

import queue

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from solarscribe.shg.spectrum import CATALOG, IdentificationResult, identify_lines

__all__ = ["LineIdentifierWorker", "SpectrumPanel"]


class LineIdentifierWorker(QThread):
    resultReady = Signal(object, dict)

    # @args: parent - the Qt parent
    # @return: an idle thread, waiting for a profile
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._running = True

    # @args: profile - 1D dispersion profile, copied before the call
    #        params - the settings and the generation this profile belongs to
    def submit(self, profile: np.ndarray, params: dict) -> None:
        # The newest spectrum is the one worth naming. Dropping the old profile
        # is what keeps a slow match from building a backlog behind the video.
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait((profile, params))
        except queue.Full:
            pass

    # @args: none. Runs until stop() puts the sentinel in the queue
    def run(self) -> None:
        while self._running:
            item = self._queue.get()
            if item is None:
                break
            profile, params = item
            try:
                result = identify_lines(
                    profile, params["dispersion"],
                    target_wavelength=params["target_wavelength"],
                    flip=params["flip"],
                    tolerance_angstrom=params["tolerance"],
                    min_confidence=params["min_confidence"],
                    anchor_search_px=params["anchor_search_px"],
                )
            except Exception:  # noqa: BLE001 - the worker must never die
                result = None
            self.resultReady.emit(result, params)

    # @args: none. Stops the thread and waits for the current match
    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        self.wait(2000)


class SpectrumPanel(QWidget):
    # @args: parent - the Qt parent
    # @return: the panel, empty until the first identification
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SpectrumPanel")
        self.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.title = QLabel(self.tr("Spectral lines"), self)
        self.title.setProperty("role", "subtitle")
        self.state = QLabel(self.tr("Off"), self)
        self.state.setProperty("role", "hint")
        self.state.setWordWrap(True)
        self.anchor = QLabel(self.tr("Anchor: --"), self)
        self.anchor.setProperty("role", "hint")
        self.anchor.setWordWrap(True)
        self.confidence = QLabel(self.tr("Confidence: --"), self)
        self.confidence.setProperty("role", "hint")
        self.confidence.setWordWrap(True)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Line"), self.tr("Å"), self.tr("Row")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setToolTip(self.tr(
            "Names sorted by their row in the frame. The row is where the line "
            "sits in the video; the spectral band starts at the top of the "
            "strip, and the row includes that offset."))

        self.hint = QLabel(
            self.tr("Set the dispersion and the target line in Settings → Spectrum."),
            self)
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)

        self.anchor.setToolTip(self.tr(
            "The target line is the anchor: the grating is tuned to it. The row "
            "is where the strongest matching dip was found."))
        self.confidence.setToolTip(self.tr(
            "An F1 score over the strong catalog lines in the window and the "
            "detected dips. It says how well the pattern supports the names, "
            "not how accurate a wavelength is."))

        layout.addWidget(self.title)
        layout.addWidget(self.state)
        layout.addWidget(self.anchor)
        layout.addWidget(self.confidence)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.hint)
        self._set_meta_visible(False)
        self._set_table_visible(False)

    # ------------------------------------------------------------------ states

    # @args: none. The toggle is on but no first result has arrived
    def show_waiting(self) -> None:
        self._set_meta_visible(False)
        self._set_table_visible(False)
        self._set_state(self.tr("Reading the spectrum..."), "muted")

    # @args: none. The dispersion is 0, so identification cannot start
    def show_no_dispersion(self) -> None:
        self._set_meta_visible(False)
        self._set_table_visible(False)
        self._set_state(self.tr(
            "Identification is off: the dispersion is 0 in Settings → Spectrum. "
            "It is how many angstroms one pixel covers; without it a pixel "
            "distance cannot become a wavelength."), "warning")

    # @args: none. There is no frame to read
    def show_no_spectrum(self) -> None:
        self._set_meta_visible(False)
        self._set_table_visible(False)
        self._set_state(self.tr(
            "No spectrum on screen. Open the camera and start the stream."),
            "muted")

    # @args: reason - the IdentificationResult reason code; detected - dips
    def show_reason(self, reason: str, detected: int = 0) -> None:
        self._set_meta_visible(False)
        self._set_table_visible(False)
        self._set_state(self._reason_text(reason, detected), "warning")

    # @args: result - the IdentificationResult
    #        band_y - the band top in the frame, to show frame rows
    #        min_confidence - the configured minimum
    def show_result(self, result: IdentificationResult, band_y: int,
                    min_confidence: float) -> None:
        if not result.ok:
            self.show_reason(result.reason_code, result.detected)
            return
        self._set_meta_visible(True)
        self.anchor.setText(self._anchor_text(result, band_y))
        self.confidence.setText(self._confidence_text(result.confidence))
        if result.reason_code == "low_confidence" \
                or result.confidence < min_confidence:
            self._set_table_visible(False)
            self._set_state(self.tr(
                "Naming is not trustworthy: confidence {value:.2f} is below the "
                "{minimum:.2f} minimum. No names are shown. Check the target "
                "line and the dispersion in Settings → Spectrum.").format(
                    value=result.confidence, minimum=min_confidence), "warning")
            return
        count = len(result.lines)
        text = (self.tr("1 line named, sorted by row.") if count == 1
                else self.tr("{count} lines named, sorted by row.").format(
                    count=count))
        self._set_state(text, "ok")
        self._fill_table(result, band_y)
        self._set_table_visible(True)

    # ------------------------------------------------------------------ helpers

    # @args: result - an ok IdentificationResult; band_y - the band top
    # @return: the anchor sentence
    def _anchor_text(self, result: IdentificationResult, band_y: int) -> str:
        name = ""
        for line in CATALOG:
            if abs(line.wavelength_angstrom - result.anchor_wavelength) < 1e-3:
                name = line.name
                break
        row = int(round(band_y + float(result.anchor_pixel)))
        if name:
            return self.tr("Anchor: {name} {wave:.2f} Å at row {row}").format(
                name=name, wave=result.anchor_wavelength, row=row)
        return self.tr("Anchor: {wave:.2f} Å at row {row}").format(
            wave=result.anchor_wavelength, row=row)

    # @args: value - the F1 confidence, 0..1
    # @return: the plain-language confidence sentence
    def _confidence_text(self, value: float) -> str:
        return self.tr(
            "Confidence {value:.2f} (0 to 1): the share of catalog lines found "
            "and detected dips named. It is a pattern match, not a wavelength "
            "calibration.").format(value=value)

    # @args: reason - a stable reason code; detected - the dip count
    # @return: a plain sentence; never the raw code
    def _reason_text(self, reason: str, detected: int) -> str:
        if reason == "empty_profile":
            return self.tr(
                "The spectral band has no pixels. Check the band in the ROI "
                "step.")
        if reason == "no_lines":
            return self.tr(
                "No absorption line found in the band. Check the focus, the "
                "exposure and the spectral band.")
        if reason == "no_match":
            return self.tr(
                "No catalog line matched the detected dips ({count}). The "
                "dispersion or the target line is probably wrong; check "
                "Settings → Spectrum.").format(count=int(detected))
        if reason == "no_anchor":
            return self.tr(
                "The target line is missing. Set it in Settings → Spectrum.")
        if reason == "bad_dispersion":
            return self.tr(
                "The dispersion is zero, so identification is off. Set it in "
                "Settings → Spectrum.")
        return self.tr(
            "The identification could not run. Check the log and Settings → "
            "Spectrum.")

    # @args: result - the ok IdentificationResult; band_y - the band top
    def _fill_table(self, result: IdentificationResult, band_y: int) -> None:
        lines = sorted(result.lines, key=lambda line: line.pixel)
        self.table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            name = line.name
            if line.kind == "telluric":
                name += self.tr(" (telluric)")
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(self.tr(
                "Depth {depth:.0f}% of the local continuum. Residual {distance:.2f} "
                "Å from the catalog rest wavelength. {kind}.").format(
                    depth=line.depth * 100.0,
                    distance=line.distance_angstrom,
                    kind=self.tr("telluric (Earth's atmosphere)")
                    if line.kind == "telluric" else self.tr("solar")))
            wave_item = QTableWidgetItem(f"{line.wavelength_angstrom:.2f}")
            wave_item.setToolTip(self.tr(
                "Rest wavelength in angstroms (Å). The measured line is "
                "{distance:.2f} Å from it.").format(
                    distance=line.distance_angstrom))
            row_item = QTableWidgetItem(f"{int(round(band_y + line.pixel))}")
            row_item.setToolTip(self.tr(
                "Row in the frame; the spectral band starts at row {band}.").format(
                    band=int(band_y)))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, wave_item)
            self.table.setItem(row, 2, row_item)

    # @args: visible - whether the anchor and confidence lines are shown
    def _set_meta_visible(self, visible: bool) -> None:
        self.anchor.setVisible(bool(visible))
        self.confidence.setVisible(bool(visible))

    # @args: visible - whether the line table is shown
    def _set_table_visible(self, visible: bool) -> None:
        self.table.setVisible(bool(visible))

    # @args: text - the state sentence; state - ok, warning or muted
    def _set_state(self, text: str, state: str) -> None:
        self.state.setText(text)
        self.state.setProperty("state", state)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
