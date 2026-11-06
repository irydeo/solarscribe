############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui focus aid module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Tools -> Focus aid (DESIGN.md 9.4, parity row 8).
#
# It reads the two numbers the capture engine already computes per frame and
# says what they mean. It is deliberately modest: a live trend, not a
# measurement. Seeing moves the contrast, so one reading proves nothing and the
# dialog says so instead of pretending to a precision it does not have.
#
# No focus control here: motorised focus is out of scope (DESIGN.md 1), so the
# observer turns the focuser and watches the trend.

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from .ui_loader import load_ui

__all__ = ["FocusAidDialog"]


class FocusAidDialog(QDialog):
    # @args: parent - the Qt parent
    # @return: the dialog, empty until a frame arrives
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("focus_aid")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(False)
        self._ui = ui
        close = self.findChild(QWidget, "focusCloseButton")
        if close is not None:
            close.clicked.connect(self.accept)

    # @args: mean_fraction - mean level as a fraction of the full range (0..1)
    #        std_fraction - standard deviation as the same fraction
    def set_stats(self, mean_fraction: float, std_fraction: float) -> None:
        mean = max(0.0, min(1.0, float(mean_fraction)))
        std = max(0.0, min(1.0, float(std_fraction)))
        self._set("focusMeanValue", self.tr("{value:.1f}% of full range").format(
            value=mean * 100.0))
        self._set("focusStdValue", self.tr("{value:.2f}% of full range").format(
            value=std * 100.0))
        # 25% of the range is the auto-exposure target (SCHEMA); saying so turns
        # a percentage into something the observer can act on.
        mean_label = self.findChild(QLabel, "focusMeanValue")
        if mean_label is not None:
            mean_label.setProperty("state", "ok" if 0.15 <= mean <= 0.40
                                   else "warning")
            mean_label.style().unpolish(mean_label)
            mean_label.style().polish(mean_label)

    # @args: name - the label object name; text - its text
    def _set(self, name: str, text: str) -> None:
        label = self.findChild(QLabel, name)
        if label is not None:
            label.setText(text)

    # @args: none
    # @return: the two sentences shown, for the tests
    def texts(self) -> tuple[str, str]:
        mean = self.findChild(QLabel, "focusMeanValue")
        std = self.findChild(QLabel, "focusStdValue")
        return (mean.text() if mean else "", std.text() if std else "")
