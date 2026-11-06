############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui roi manager module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Tools -> ROI manager (ADR-009): the presets of the profile, in one table.
#
# It is a viewer, not a second editor: choosing a preset copies the rectangles
# into the ROI step and nothing else. Applying a ROI is a deliberate act there,
# because it restarts the stream and, if a recording is running, closes it
# first (ADR-010). That is why this dialog says it does not touch the camera.

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE
from .ui_loader import load_ui

__all__ = ["RoiManagerDialog"]


class RoiManagerDialog(QDialog):
    presetChosen = Signal(object)

    # @args: presets - the profile presets; parent - the Qt parent
    # @return: the dialog, listing the presets
    def __init__(self, presets=(), parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("roi_manager")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(False)
        self._ui = ui
        self._presets: tuple = ()
        self.table = self.findChild(QTableWidget, "presetTable")
        close = self.findChild(QWidget, "roiManagerCloseButton")
        if close is not None:
            close.clicked.connect(self.accept)
        use = self.findChild(QWidget, "usePresetButton")
        if use is not None:
            use.clicked.connect(self._use_current)
        self.set_presets(presets)

    # @args: presets - the profile's RoiPreset sequence
    def set_presets(self, presets) -> None:
        self._presets = tuple(presets)
        empty = self.findChild(QWidget, "roiManagerEmpty")
        if empty is not None:
            empty.setVisible(not self._presets)
        if self.table is None:
            return
        self.table.clear()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([
            self.tr("Preset"),
            self.tr("Capture ROI (sensor px)"),
            self.tr("Spectral band (frame px)"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.table.setRowCount(len(self._presets))
        for row, preset in enumerate(self._presets):
            name = QTableWidgetItem(str(preset.name))
            capture = QTableWidgetItem(self._rect_text(preset.capture))
            band = QTableWidgetItem(self._rect_text(preset.band))
            for column, item in enumerate((name, capture, band)):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        if self._presets:
            self.table.selectRow(0)
        use = self.findChild(QWidget, "usePresetButton")
        if use is not None:
            use.setEnabled(bool(self._presets))

    # @args: roi - a rectangle
    # @return: "x, y, width x height", the way the ROI step writes it
    def _rect_text(self, roi) -> str:
        x, y, width, height = roi
        return f"{int(x)}, {int(y)}, {int(width)} x {int(height)}"

    # @args: none. Emits the selected preset and closes
    def _use_current(self) -> None:
        row = self.table.currentRow() if self.table is not None else -1
        if 0 <= row < len(self._presets):
            self.presetChosen.emit(self._presets[row])
            self.accept()

    # @args: none
    # @return: the number of presets listed, for the tests
    def count(self) -> int:
        return len(self._presets)
