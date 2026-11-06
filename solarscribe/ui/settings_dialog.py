############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui settings dialog module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The settings dialog, built from config.schema.SCHEMA instead of by hand.
#
# Why data-driven: the schema is the contract (ADR-003). A hand-written dialog
# drifts from it the first time a key is added, and the "why" text of every key
# is already written there as the tooltip the observer needs. Here the dialog
# only chooses a widget per type and groups by section; it does not know what a
# setting means.
#
# Nothing is saved until Save: the dialog keeps its own copy, so Cancel really
# cancels and Restore defaults is only a preview.

from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from solarscribe.config.schema import SCHEMA, Key, default_value
from solarscribe.config.store import Settings, default_settings

from .settings_text import SETTINGS_WHY
from .ui_loader import load_ui

__all__ = ["SettingsDialog"]


class SettingsDialog(QDialog):
    # @args: settings - the Settings to show; parent - the Qt parent
    # @return: the dialog, built from the schema
    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("settings_dialog")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(True)
        self._ui = ui
        self._settings = settings if settings is not None else default_settings()
        self._editors: dict[tuple[str, str], QWidget] = {}
        self._rows: list[tuple[Key, QWidget, QGroupBox]] = []
        self._groups: dict[str, QGroupBox] = {}

        self._form = self.findChild(QWidget, "settingsFormHost")
        self._build_form()
        self._wire()
        self._apply_filter("")

    # @args: none. Creates one group per schema section and one row per key
    def _build_form(self) -> None:
        if self._form is None:
            return
        layout = self._form.layout()
        if layout is None:
            return
        current_section = ""
        box = None
        for key in SCHEMA:
            if key.section != current_section:
                current_section = key.section
                box = QGroupBox(self._section_title(current_section), self._form)
                box_layout = QVBoxLayout(box)
                box_layout.setSpacing(4)
                # The group explains where the section comes from: inherited
                # keys keep the nightscribe-scan habits, new ones are ours.
                box.setToolTip(self._section_tooltip(current_section))
                layout.addWidget(box)
                self._groups[current_section] = box
            editor = self._make_editor(key, box)
            row = QWidget(box)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            # The label is plain language; the exact INI key stays in the
            # tooltip, so a hand-edited file is still easy to map to the field.
            label = QLabel(key.name.replace("_", " ").strip().capitalize(), row)
            label.setMinimumWidth(190)
            label.setToolTip(f"{key.name}\n\n{self._why_text(key)}")
            row_layout.addWidget(label, 0)
            row_layout.addWidget(editor, 1)
            if key.kind is str:
                row_layout.addWidget(QLabel(self._origin_text(key.origin), row), 0)
            box.layout().addWidget(row)
            self._rows.append((key, row, box))
        layout.addStretch(1)

    # @args: key - the schema key; parent - the group box
    # @return: the editor widget for that type, initialised to the live value
    def _make_editor(self, key: Key, parent: QWidget) -> QWidget:
        value = self._setting(key.section, key.name)
        if key.kind is bool:
            editor = QCheckBox(parent)
            editor.setChecked(bool(value))
        elif key.kind is int:
            editor = QSpinBox(parent)
            editor.setRange(-1_000_000, 1_000_000)
            editor.setValue(int(value))
        elif key.kind is float:
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(4)
            editor.setRange(-1_000_000_000.0, 1_000_000_000.0)
            editor.setValue(float(value))
        else:
            editor = QLineEdit(parent)
            editor.setText(str(value))
        editor.setToolTip(self._why_text(key))
        self._editors[(key.section, key.name)] = editor
        return editor

    # @args: none. Connects the buttons and the filter
    def _wire(self) -> None:
        save = self.findChild(QWidget, "saveButton")
        cancel = self.findChild(QWidget, "cancelButton")
        restore = self.findChild(QWidget, "restoreDefaultsButton")
        filter_edit = self.findChild(QLineEdit, "filterEdit")
        if save is not None:
            save.clicked.connect(self.accept)
        if cancel is not None:
            cancel.clicked.connect(self.reject)
        if restore is not None:
            restore.clicked.connect(self.restore_defaults)
        if filter_edit is not None:
            filter_edit.textChanged.connect(self._apply_filter)

    # @args: key - a schema key
    # @return: the translated why text, or the schema's developer text when the
    #          generated table missed it. The context is "Settings", the same
    #          one the generated QT_TRANSLATE_NOOP table marks
    def _why_text(self, key: Key) -> str:
        source = SETTINGS_WHY.get((key.section, key.name))
        if source is None:
            return key.why
        return QCoreApplication.translate("Settings", source)

    # @args: section - the schema section
    # @return: its visible name
    def _section_title(self, section: str) -> str:
        if section == "general":
            return self.tr("General")
        if section == "observatory":
            return self.tr("Observatory")
        if section == "camera":
            return self.tr("Camera")
        if section == "roi":
            return self.tr("ROI and tilt")
        if section == "mount":
            return self.tr("Mount")
        if section == "scan":
            return self.tr("Scan")
        if section == "capture":
            return self.tr("Capture limits")
        if section == "session":
            return self.tr("Session")
        if section == "polar":
            return self.tr("Polar alignment")
        return section

    # @args: section - the schema section
    # @return: a sentence about the section, shown as its tooltip
    def _section_tooltip(self, section: str) -> str:
        if section == "roi":
            return self.tr(
                "The two rectangles and the last tilt. The ROI is in sensor "
                "pixels; the band is in frame pixels.")
        if section == "capture":
            return self.tr(
                "The budget of ADR-013. These are the figures the health panel "
                "compares against.")
        return self.tr("Every value has a default, so a partial file still starts "
                       "the app.")

    # @args: origin - "scan" or "new"
    # @return: a short note so a user recognises the inherited keys
    def _origin_text(self, origin: str) -> str:
        return self.tr("inherited") if origin == "scan" else self.tr("new")

    # @args: section, name - the key
    # @return: the editor widget, for the tests
    def editor(self, section: str, name: str) -> QWidget | None:
        return self._editors.get((section, name))

    # @args: section, name - the key
    # @return: its value in the settings handed to the dialog
    def _setting(self, section: str, name: str):
        if isinstance(self._settings, Settings):
            return self._settings.get(section, name)
        return self._settings.get((section, name), default_value(section, name))

    # @args: section, name - the key
    # @return: the value currently shown in the dialog
    def value(self, section: str, name: str):
        editor = self._editors[(section, name)]
        if isinstance(editor, QCheckBox):
            return bool(editor.isChecked())
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if isinstance(editor, QLineEdit):
            return editor.text()
        return None

    # @args: section, name, value - set the editor from code
    def set_value(self, section: str, name: str, value) -> None:
        editor = self._editors[(section, name)]
        if isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.setValue(type(editor.value())(value))
        elif isinstance(editor, QLineEdit):
            editor.setText(str(value))

    # @args: none
    # @return: a complete Settings with the value shown in the dialog
    def values(self) -> Settings:
        return Settings(values={(key.section, key.name):
                                self.value(key.section, key.name)
                                for key in SCHEMA})

    # @args: none. Alias that says what it is used for
    def edited_settings(self) -> Settings:
        return self.values()

    # @args: none. Puts every editor back to the schema default
    def restore_defaults(self) -> None:
        for key in SCHEMA:
            self.set_value(key.section, key.name,
                           default_value(key.section, key.name))

    # @args: text - the filter string
    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible_groups: dict[str, bool] = {}
        for key, row, box in self._rows:
            haystack = (f"{key.section} {key.name} {key.why} "
                        f"{self._why_text(key)}").lower()
            visible = needle in haystack
            row.setVisible(visible)
            visible_groups[box.title()] = visible_groups.get(box.title(), False) or visible
        for section, box in self._groups.items():
            box.setVisible(visible_groups.get(box.title(), True))
