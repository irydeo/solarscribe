############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui logs viewer module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The in-app log viewer (ADR-009, Tools -> Logs).
#
# Why inside the app: the observer should not have to know where the platform
# keeps its logs to report a failure. The dialog opens the file, filters it by
# level and follows it while it grows. "Follow" is the useful default before a
# session; turning it off is how you read a line while new ones arrive.

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .ui_loader import load_ui

__all__ = ["LogsViewer"]


class LogsViewer(QDialog):
    # @args: path - the log file or None; parent - the Qt parent
    # @return: the dialog, reading the file when it exists
    def __init__(self, path: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("logs_viewer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(False)
        self._ui = ui
        self._path: Path | None = Path(path) if path else None
        self._mtime = 0.0
        self.view = self.findChild(QPlainTextEdit, "logView")
        self.path_label = self.findChild(QLabel, "logsPathLabel")
        self.filter_combo = self.findChild(QComboBox, "logsFilterCombo")
        self.follow_check = self.findChild(QWidget, "logsFollowCheck")
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._populate_filter()
        self._wire()
        self.set_path(self._path)

    # @args: none. Fills the level selector with words, not codes
    def _populate_filter(self) -> None:
        if self.filter_combo is None:
            return
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        # The levels are the ones the log writes; the filter shows them joined
        # so the user does not have to guess that an error also counts as a
        # warning.
        self.filter_combo.addItem(self.tr("All lines"), "all")
        self.filter_combo.addItem(self.tr("Warnings and errors"), "warn")
        self.filter_combo.addItem(self.tr("Errors only"), "error")
        self.filter_combo.addItem(self.tr("Information"), "info")
        self.filter_combo.blockSignals(False)

    # @args: none
    def _wire(self) -> None:
        reload_button = self.findChild(QWidget, "reloadButton")
        open_button = self.findChild(QWidget, "openFolderButton")
        close_button = self.findChild(QWidget, "logsCloseButton")
        if reload_button is not None:
            reload_button.clicked.connect(self.reload)
        if open_button is not None:
            open_button.clicked.connect(self.open_folder)
        if close_button is not None:
            close_button.clicked.connect(self.accept)
        if self.filter_combo is not None:
            self.filter_combo.currentIndexChanged.connect(self.reload)

    # @args: path - the log file, or None when the app has not written one
    def set_path(self, path: str | Path | None) -> None:
        self._path = Path(path) if path else None
        if self.path_label is not None:
            if self._path is None:
                self.path_label.setText(self.tr("No log file yet."))
            elif self._path.is_file():
                self.path_label.setText(str(self._path))
            else:
                # The app passes the path it will write; showing it even before
                # the file exists tells the observer where the diagnosis will be.
                self.path_label.setText(self.tr("No log yet: {path}").format(
                    path=str(self._path)))
            self.path_label.setToolTip(self.tr(
                "The file the app is writing. A path here means the log can be "
                "copied and attached to a report."))
        self.reload()

    # @args: none
    # @return: the log file the viewer is showing
    def path(self) -> Path | None:
        return self._path

    # @args: none. Reads the file and applies the current filter
    def reload(self) -> None:
        if self.view is None:
            return
        if self._path is None or not self._path.is_file():
            self.view.setPlainText("")
            self._mtime = 0.0
            return
        try:
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
            self._mtime = self._path.stat().st_mtime
        except OSError:
            # The log may be rotated by another process: keep the last text and
            # say nothing, rather than clear the screen mid-read.
            return
        mode = self.filter_combo.currentData() if self.filter_combo else "all"
        selected = [line for line in lines if self._matches(line, mode)]
        # A log can be huge; the last 5000 lines are what a diagnosis needs and
        # painting a million lines would freeze the dialog.
        self.view.setPlainText("\n".join(selected[-5000:]))
        if self.follow_check is not None and self.follow_check.isChecked():
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.maximum())

    # @args: line - a log line; mode - all, warn, error or info
    # @return: whether the line passes the filter
    def _matches(self, line: str, mode: str) -> bool:
        if mode == "all":
            return True
        upper = line.upper()
        if mode == "error":
            return "ERROR" in upper or "CRITICAL" in upper
        if mode == "warn":
            return "ERROR" in upper or "CRITICAL" in upper or "WARNING" in upper
        if mode == "info":
            return "INFO" in upper
        return True

    # @args: none
    # @return: the visible text, for the tests
    def text(self) -> str:
        return self.view.toPlainText() if self.view is not None else ""

    # @args: none. Opens the folder that contains the log
    def open_folder(self) -> None:
        if self._path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path.parent)))

    # @args: none. Reloads when the file changed, while the dialog is visible
    def _poll(self) -> None:
        if self._path is None or not self.isVisible():
            return
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return
        if mtime != self._mtime:
            self.reload()

    # @args: event - show: start the follow timer
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        self.reload()

    # @args: event - hide: stop the timer so a hidden dialog costs nothing
    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)
