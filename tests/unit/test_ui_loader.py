############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui loader test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ADR-009: the interface is defined in .ui files and the code only wires it.
# These tests are the guard: every screen loads in Designer's format, the
# custom widgets enter through a placeholder, and a path can never escape the
# ui folder.

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from solarscribe.ui import ui_loader  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_every_ui_file_loads(qapp):
    # A .ui that Designer saved but Qt cannot load is a blank window at runtime.
    files = sorted(ui_loader.UI_DIR.glob("*.ui"))
    assert files, "no .ui file found: the interface would be built in code only"
    for path in files:
        widget = ui_loader.load_ui(path.name)
        assert isinstance(widget, QWidget), path.name
        widget.deleteLater()


def test_ui_path_rejects_traversal():
    # Translation and packaging both take a name from outside; a name is a file
    # stem, never a path.
    assert ui_loader.ui_path("main_window") == ui_loader.UI_DIR / "main_window.ui"
    assert ui_loader.ui_path("main_window.ui") == ui_loader.UI_DIR / "main_window.ui"
    for bad in ("../config/schema", "/etc/passwd", "sub/dir/window"):
        with pytest.raises(ValueError):
            ui_loader.ui_path(bad)


def test_missing_ui_file_names_itself():
    with pytest.raises(FileNotFoundError) as info:
        ui_loader.load_ui("does_not_exist")
    assert "does_not_exist" in str(info.value)


def test_replace_widget_keeps_the_placeholder_name(qapp):
    # The rest of the code (and the tests) find the custom widget by the name the
    # .ui gave the placeholder; the swap must not change it (ADR-009).
    host = QWidget()
    placeholder = QLabel("placeholder", host)
    placeholder.setObjectName("viewerHost")
    layout = ui_loader.vertical_layout(host)
    layout.addWidget(placeholder)

    viewer = QWidget()
    ui_loader.replace_widget(host, "viewerHost", viewer)

    assert host.findChild(QWidget, "viewerHost") is viewer
    assert placeholder.parent() is None
    assert layout.count() == 1


def test_vertical_layout_creates_one_when_absent(qapp):
    # Some placeholder hosts are bare widgets in the .ui; the loader wraps them
    # in a layout instead of every caller repeating the same four lines.
    host = QWidget()
    layout = ui_loader.vertical_layout(host)
    assert host.layout() is layout
    assert ui_loader.vertical_layout(host) is layout


def test_message_box_helpers_are_translated(qapp):
    # Dialogs built in code must not leak untranslated English through a raw
    # string; the helper takes a translated title and body.
    title = ui_loader.tr_text("SolarScribe", "No camera")
    assert title == "No camera"
    assert "No camera" in ui_loader.tr_text("SolarScribe", "No camera")
