############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui i18n test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ADR-016 from day one: every visible string goes through Qt's translation
# machinery, and the prose never uses the em dash. The test parses the sources
# instead of trusting a reviewer: a literal passed straight to setText() is a
# string that lupdate cannot see and a translator will never get.
#
# .ui strings do not need this check: uic generates self.tr() for them.

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

UI_DIR = Path(__file__).resolve().parents[2] / "solarscribe" / "ui"
CLI_DIR = Path(__file__).resolve().parents[2] / "solarscribe" / "cli"

# Methods whose first argument is user-visible text.
TEXT_SETTERS = {
    "setText", "setToolTip", "setWindowTitle", "setPlaceholderText",
    "setAccessibleName", "addItem", "showMessage", "getText",
}

# Widget constructors whose first string argument is shown as-is.
TEXT_CTORS = {"QLabel", "QPushButton", "QCheckBox", "QGroupBox", "QAction",
              "QMessageBox", "QInputDialog"}


# @args: path - a .py file
# @return: [(line, call)] where a raw string reached a visible setter
def _raw_text_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = ""
        if isinstance(function, ast.Attribute):
            name = function.attr
        elif isinstance(function, ast.Name):
            name = function.id
        if name in TEXT_SETTERS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.append((node.lineno, name, first.value))
        if name in TEXT_CTORS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.append((node.lineno, name, first.value))
    return offenders


@pytest.mark.parametrize("path", sorted(UI_DIR.glob("*.py")), ids=lambda p: p.name)
def test_visible_strings_are_translated(path):
    offenders = _raw_text_calls(path)
    assert not offenders, (
        f"{path.name}: raw visible strings must be self.tr() so lupdate sees "
        f"them: {offenders}"
    )


@pytest.mark.parametrize("path", ["ui", "cli"])
def test_no_em_dash_in_the_code(path):
    # The em dash is banned by AGENTS.md, comments included.
    root = UI_DIR if path == "ui" else CLI_DIR
    offenders = []
    for source in sorted(root.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        if "\u2014" in text:
            offenders.append(source.name)
    assert not offenders, f"em dash in {offenders}"


def test_no_em_dash_in_the_designer_files():
    offenders = []
    for source in sorted(UI_DIR.glob("*.ui")):
        text = source.read_text(encoding="utf-8")
        if "\u2014" in text:
            offenders.append(source.name)
    assert not offenders, f"em dash in {offenders}"


def test_every_screen_has_a_ui_file():
    # The window, the telescope panel, the health panel and the dialogs are all
    # Designer files (ADR-009). The viewer, the histogram, the ROI overlay, the
    # step rail and the scan drawing are the documented exceptions.
    expected = {
        "main_window", "telescope_panel", "camera_panel", "health_panel",
        "welcome", "settings_dialog", "logs_viewer", "sky_calendar",
        "roi_manager", "profile_manager",
    }
    present = {path.stem for path in UI_DIR.glob("*.ui")}
    assert expected <= present
    for code_only in ("live_viewer", "histogram", "roi_editor",
                      "spectrum_panel"):
        assert code_only not in present, (
            f"{code_only} must stay a placeholder + replaceWidget (ADR-009)")
