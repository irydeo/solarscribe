############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui theme test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The visual identity is a contract: one dark theme, SolarScribe's own sun
# accent, and a palette dark enough that the video is the brightest thing on
# screen. A light theme is not an option (ADR-009), so these tests pin the
# tokens and the pieces the rest of the UI reads.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from solarscribe.ui import theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    # One QApplication for the module; widgets need it and Qt refuses two.
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    return app


def test_palette_is_dark_and_has_its_own_sun_accent(qapp):
    # Every token exists and the background is far darker than the text. The
    # accent is the sun colour of this app, not NightScribe's blue: the user
    # must know which sibling is on screen.
    p = theme.PALETTE
    assert p.background.startswith("#") and p.surface.startswith("#")
    background = int(p.background[1:], 16)
    text = int(p.text[1:], 16)
    assert sum(background >> s & 0xFF for s in (0, 8, 16)) < 200
    assert sum(text >> s & 0xFF for s in (0, 8, 16)) > 500
    assert p.accent.lower() == "#f4a340"
    assert p.accent.lower() != "#4da3ff"      # NightScribe's blue is not ours


def test_stylesheet_covers_the_widgets_the_ui_uses(qapp):
    # A theme that misses a widget leaves it light grey in the middle of a dark
    # window, which is the classic "unfinished" look.
    css = theme.stylesheet()
    for selector in ("QMainWindow", "QPushButton", "QLineEdit", "QComboBox",
                     "QGroupBox", "QTabWidget", "QDockWidget", "QStatusBar",
                     "QMenuBar", "QToolTip", "QScrollBar", "QSplitter"):
        assert selector in css, f"{selector} has no style"
    assert theme.PALETTE.accent.lower() in css.lower()
    assert "QPushButton[primary=\"true\"]" in css


def test_apply_theme_sets_a_dark_palette(qapp):
    # QSS styles widgets but not the things Qt paints itself (tooltips, menus,
    # disabled text), so the palette has to be dark too.
    window = qapp.palette().color(QPalette.ColorRole.Window)
    text = qapp.palette().color(QPalette.ColorRole.WindowText)
    assert window.lightness() < 80
    assert text.lightness() > 180


def test_sun_icon_is_drawn_not_a_missing_file(qapp):
    # The window icon is generated with QPainter: no binary asset can go missing
    # in a wheel or a PyInstaller bundle.
    icon = theme.sun_icon(64)
    assert not icon.isNull()
    sizes = icon.availableSizes()
    assert sizes and sizes[0].width() >= 16
    pixmap = theme.sun_pixmap(32)
    assert not pixmap.isNull()
    assert pixmap.width() == 32 and pixmap.height() == 32


def test_plain_language_has_no_em_dash(qapp):
    # AGENTS.md: the em dash is banned in prose. Theme strings are user-visible.
    for name in (theme.APP_NAME, theme.APP_TAGLINE):
        assert "\u2014" not in name
    assert "\u2014" not in theme.stylesheet()
