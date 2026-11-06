############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui loader module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Loads the Designer files and swaps the placeholder widgets (ADR-009).
#
# The rule the whole ui layer follows: structure, visible text and tooltips live
# in ui/*.ui; the code only connects signals and fills data. The three custom
# widgets that cannot live in Designer (the live viewer, the histogram and the
# ROI overlay) enter through a plain QWidget placeholder and replace_widget(),
# which keeps the object name so the rest of the code still finds them.
#
# Translations are loaded from ui/i18n/*.qm when the docs agent has built them.
# A missing catalogue is not an error: the source strings are English and the
# app stays usable (ADR-016).

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QDockWidget, QVBoxLayout, QWidget

__all__ = [
    "UI_DIR",
    "install_translator",
    "load_ui",
    "replace_widget",
    "tr_text",
    "ui_path",
    "vertical_layout",
]

UI_DIR = Path(__file__).resolve().parent
I18N_DIR = UI_DIR / "i18n"


# @args: name - a .ui file stem or file name ("main_window" or "main_window.ui")
# @return: the absolute path, after refusing anything that tries to leave ui/
def ui_path(name: str) -> Path:
    stem = name[:-3] if name.endswith(".ui") else name
    if not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        raise ValueError(f"{name!r} is not a .ui file name")
    return UI_DIR / f"{stem}.ui"


# @args: name - a .ui file stem or file name
# @return: the loaded root widget. The caller owns it (no parent is passed to
#          QUiLoader on purpose, so tests can delete it without a window)
def load_ui(name: str) -> QWidget:
    path = ui_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"ui file not found: {path}")
    loader = QUiLoader()
    widget = loader.load(str(path))
    if widget is None:
        raise RuntimeError(f"Qt could not load {path}: {loader.errorString()}")
    return widget


# @args: host - the widget that contains the placeholder
#        placeholder - the object name the .ui gave it
#        widget - the real custom widget to insert
# @return: the inserted widget, with the placeholder's object name, so the
#          rest of the code keeps finding it by the name written in Designer
def replace_widget(host: QWidget, placeholder: str, widget: QWidget) -> QWidget:
    old = host.findChild(QWidget, placeholder)
    if old is None:
        raise KeyError(f"{placeholder!r} is not in {host.objectName() or host}")
    parent = old.parentWidget()
    if isinstance(parent, QDockWidget):
        # A QDockWidget owns exactly one content widget and has no layout; the
        # swap is setWidget(), not a layout operation.
        widget.setObjectName(placeholder)
        parent.setWidget(widget)
        old.hide()
        old.setParent(None)
        old.deleteLater()
        return widget

    layout = parent.layout() if parent is not None else None
    if layout is None:
        layout = host.layout()
    if layout is None and parent is not None:
        # A bare placeholder host (several .ui files use one): wrap it so the
        # custom widget has somewhere to live.
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(old)
    if layout is None:
        raise RuntimeError(f"{placeholder!r} has no layout to swap into")

    widget.setObjectName(placeholder)
    # QLayout.replaceWidget is the portable path: insertWidget only exists on
    # box layouts, and a placeholder may sit in a grid.
    replaced = layout.replaceWidget(old, widget)
    if replaced is None:
        layout.addWidget(widget)
    # Rename and detach the placeholder before deleteLater: until the event loop
    # runs, findChild() would still return it under the same name and the rest
    # of the code would talk to a zombie.
    old.setObjectName(f"{placeholder}_replaced")
    old.hide()
    old.setParent(None)
    old.deleteLater()
    return widget


# @args: host - a widget that may or may not have a layout
# @return: its QVBoxLayout, created on demand. Used by placeholder hosts and by
#          the code-built forms (settings), which are data-driven by design
def vertical_layout(host: QWidget) -> QVBoxLayout:
    layout = host.layout()
    if layout is None:
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
    return layout


# @args: app - the QApplication; language - "es", "en" or "" for the system
# @return: True when a catalogue was installed. False means the source strings
#          are shown, which is honest and never blocks the app (ADR-016)
def install_translator(app: QApplication, language: str = "") -> bool:
    if not language:
        return False
    if not I18N_DIR.is_dir():
        return False
    translator = QTranslator(app)
    if not translator.load(f"solarscribe_{language}", str(I18N_DIR)):
        return False
    app.installTranslator(translator)
    # QTranslator must outlive the call; the QApplication keeps a Python
    # reference through its parent when it was created with app as parent.
    app._solarscribe_translator = translator  # noqa: SLF001 - Qt ownership glue
    return True


# @args: context - the class that owns the string (for the .ts catalogue)
#        text - the English source string
# @return: the translated string. Use only outside a QObject subclass; inside
#          one, self.tr() is the same thing with the context filled in
def tr_text(context: str, text: str) -> str:
    return QCoreApplication.translate(context, text)
