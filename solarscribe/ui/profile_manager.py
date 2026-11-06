############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui profile manager module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The Profiles dialog (ADR-009 style, Tools -> Panels or the profile bar).
#
# The user asked for a profile concept as clear as nightscribe-scan: a named
# setup that is visible, loaded at startup, switchable and manageable. This
# dialog is the manage half; the profile bar in the main window is the visible,
# always-on half.
#
# It knows nothing about the store: ProfileAdapter is the only door, so the
# named-profile API the lead is adding can land without touching this file.

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .profiles import ProfileAdapter, ProfileStoreError
from .ui_loader import load_ui

__all__ = ["ProfileManagerDialog"]


class ProfileManagerDialog(QDialog):
    profileChosen = Signal(str)
    profilesChanged = Signal()

    # @args: adapter - the store adapter; current_profile - the profile to
    #        copy when creating a new one; active - the active name
    def __init__(self, adapter: ProfileAdapter, current_profile,
                 active: str, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("profile_manager")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui)
        self.setWindowTitle(ui.windowTitle())
        self.setModal(False)
        self._ui = ui
        self._adapter = adapter
        self._current_profile = current_profile
        self._active = active or "Default"

        self._list = self.findChild(QListWidget, "profileList")
        self._new_button = self.findChild(QWidget, "profileNewButton")
        self._rename_button = self.findChild(QWidget, "profileRenameButton")
        self._delete_button = self.findChild(QWidget, "profileDeleteButton")
        self._use_button = self.findChild(QWidget, "profileUseButton")
        self._close_button = self.findChild(QWidget, "profileCloseButton")
        self._wire()
        self._refresh()

    # @args: adapter - the store adapter; profile - the current profile to copy;
    #        active - the active name
    def set_data(self, adapter: ProfileAdapter, profile, active: str) -> None:
        self._adapter = adapter
        self._current_profile = profile
        self._active = active or "Default"
        self._refresh()

    # @args: none. Connects the list and the buttons
    def _wire(self) -> None:
        if self._list is not None:
            self._list.itemSelectionChanged.connect(self._update_buttons)
            self._list.itemDoubleClicked.connect(lambda _item: self._use())
        if self._close_button is not None:
            self._close_button.clicked.connect(self.close)
        for button, slot in ((self._new_button, self._new),
                             (self._rename_button, self._rename),
                             (self._delete_button, self._delete),
                             (self._use_button, self._use)):
            if button is not None:
                button.clicked.connect(slot)

    # @args: none. Rebuilds the list and the active marker
    def _refresh(self) -> None:
        if self._list is None:
            return
        self._list.blockSignals(True)
        self._list.clear()
        names = list(self._adapter.names())
        for name in names:
            text = name + (self.tr(" (active)") if name == self._active else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._list.addItem(item)
        index = self._list.findItems(
            self._active + self.tr(" (active)"), Qt.MatchFlag.MatchExactly)
        if index:
            self._list.setCurrentItem(index[0])
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        store_hint = self.findChild(QWidget, "profileManagerStoreHint")
        if store_hint is not None:
            store_hint.setVisible(not self._adapter.available)
        self._update_buttons()

    # @args: none
    # @return: the selected profile name, or ""
    def _selected_name(self) -> str:
        if self._list is None:
            return ""
        item = self._list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    # @args: none. Enables the actions that make sense for the selection
    def _update_buttons(self) -> None:
        selected = bool(self._selected_name())
        named = self._adapter.available
        count = len(self._adapter.names())
        for button, enabled in ((self._new_button, named),
                                (self._rename_button, named and selected),
                                (self._delete_button, named and selected and count > 1),
                                (self._use_button, selected)):
            if button is not None:
                button.setEnabled(bool(enabled))

    # @args: none. Saves the current profile under a new name
    def _new(self) -> None:
        name, accepted = QInputDialog.getText(
            self, self.tr("New profile"), self.tr("Name for the new profile:"),
            text=self.tr("New profile"))
        if not accepted or not name.strip():
            return
        name = name.strip()
        if name in self._adapter.names():
            self._warn(self.tr("A profile named '{name}' already exists.").format(
                name=name))
            return
        try:
            self._adapter.save(name, self._current_profile, make_active=True)
        except (ProfileStoreError, OSError) as error:
            self._say_error(error)
            return
        self._active = name
        self._refresh()
        self.profilesChanged.emit()
        self.profileChosen.emit(name)

    # @args: none. Renames the selected profile
    def _rename(self) -> None:
        old = self._selected_name()
        if not old:
            return
        new, accepted = QInputDialog.getText(
            self, self.tr("Rename profile"), self.tr("New name:"), text=old)
        if not accepted or not new.strip() or new.strip() == old:
            return
        new = new.strip()
        if new in self._adapter.names():
            self._warn(self.tr("A profile named '{name}' already exists.").format(
                name=new))
            return
        try:
            self._adapter.rename(old, new)
            if old == self._active:
                self._adapter.set_active(new)
                self._active = new
                self.profileChosen.emit(new)
        except (ProfileStoreError, OSError) as error:
            self._say_error(error)
            return
        self._refresh()
        self.profilesChanged.emit()

    # @args: none. Deletes the selected profile, never the last one
    def _delete(self) -> None:
        name = self._selected_name()
        names = self._adapter.names()
        if not name:
            return
        if len(names) <= 1:
            self._warn(self.tr("The last profile cannot be deleted."))
            return
        answer = QMessageBox.question(
            self, self.tr("Delete profile"),
            self.tr("Delete the profile '{name}'? The saved optics and ROI "
                    "presets of that profile are lost.").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._adapter.delete(name)
            if name == self._active:
                # ADR-027: deleting the active profile leaves no active one.
                # Do not silently select another instrument; the observer picks.
                self._active = ""
                self.profileChosen.emit("")
        except (ProfileStoreError, OSError) as error:
            self._say_error(error)
            return
        self._refresh()
        self.profilesChanged.emit()

    # @args: none. Makes the selected profile the active one
    def _use(self) -> None:
        name = self._selected_name()
        if not name:
            return
        try:
            self._adapter.set_active(name)
        except (ProfileStoreError, OSError) as error:
            self._say_error(error)
            return
        self._active = name
        self._refresh()
        self.profileChosen.emit(name)

    # @args: text - a short warning
    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, self.tr("Profiles"), text)

    # @args: error - ProfileStoreError or OSError
    def _say_error(self, error) -> None:
        reason = getattr(error, "reason", "")
        if reason == "named_store_missing":
            text = self.tr(
                "Named-profile storage is not available in this build. The "
                "single profile is used.")
        elif reason == "no_profile_path":
            text = self.tr(
                "The profile file is not configured. Check Settings.")
        else:
            text = self.tr(
                "The profile could not be changed. The log has the detail.")
        self._warn(text)
