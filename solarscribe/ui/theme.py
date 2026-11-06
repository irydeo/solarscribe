############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui theme module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The single source of the visual identity (ADR-009).
#
# Only one theme exists, and it is dark on purpose: the observer works in
# daylight with a video of the Sun filling the window, and a light chrome would
# wash the spectrum out. The accent is SolarScribe's own sun amber, not
# NightScribe's blue, so the two siblings are recognisable at a glance while
# sharing the same layout language.
#
# The theme has three jobs:
#   1. The QSS: how every widget we use is painted. A selector that is missing
#      here shows up as a light grey island in a dark window.
#   2. The QPalette: menus, tooltips and disabled text are painted by Qt itself
#      and ignore most of the QSS, so the palette has to be dark too.
#   3. The icon: drawn with QPainter instead of shipped as a bitmap, because a
#      file can go missing from a wheel or a PyInstaller bundle and the window
#      icon is the first thing the user sees. A drawn sun also scales cleanly.
#
# Numbers that matter on screen (fps against 120, contrast, drift) never get a
# colour here without a meaning: `state_colour()` maps a plain state name to the
# token the status bar and the health panel use.

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

__all__ = [
    "APP_NAME",
    "APP_TAGLINE",
    "PALETTE",
    "Palette",
    "apply_theme",
    "state_colour",
    "stylesheet",
    "sun_icon",
    "sun_pixmap",
]

APP_NAME = "SolarScribe"
APP_TAGLINE = "Capture for the solar spectroheliograph"


@dataclass(frozen=True)
class Palette:
    # The tokens every widget reads. Hex strings on purpose: QSS is text, and
    # one string can feed both the stylesheet and a QBrush without converting.
    background: str = "#12151a"      # the window behind everything
    surface: str = "#1b2028"         # cards, panels, menu background
    surface_alt: str = "#222933"     # hover and pressed states
    surface_deep: str = "#0d1014"    # inputs and the video letterbox
    text: str = "#e8edf3"            # primary text
    muted: str = "#93a1b3"           # explanations and secondary labels
    accent: str = "#f4a340"          # SolarScribe's sun amber
    accent_text: str = "#1a1206"     # text on top of the accent
    ok: str = "#4cc38a"              # done, connected, inside budget
    warning: str = "#e0b341"         # recommendation, not a gate
    error: str = "#ff6b6b"           # cannot scan, or a device failed
    border: str = "#2a3441"          # separators and input outlines


PALETTE = Palette()


# @args: name - "ok", "warning" or "error" (anything else falls back to muted)
# @return: the hex colour for that state, for painting a label or a dot
def state_colour(name: str) -> str:
    return {
        "ok": PALETTE.ok,
        "warning": PALETTE.warning,
        "error": PALETTE.error,
    }.get(name, PALETTE.muted)


# @args: none
# @return: the QSS of the only theme. Every widget the app instantiates appears
#          here, or it would keep Qt's light default look
def stylesheet() -> str:
    p = PALETTE
    return f"""
    QMainWindow, QDialog {{
        background: {p.background};
        color: {p.text};
    }}
    QWidget {{
        background: transparent;
        color: {p.text};
        font-size: 13px;
    }}
    QWidget#centralwidget, QWidget#videoPanel, QWidget#sidePanel {{
        background: {p.background};
    }}
    QFrame#card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel[role="title"] {{
        font-size: 16px;
        font-weight: 600;
        color: {p.text};
    }}
    QLabel[role="subtitle"] {{
        font-size: 13px;
        font-weight: 600;
        color: {p.text};
    }}
    QLabel[role="hint"] {{
        color: {p.muted};
        font-size: 12px;
    }}
    QLabel[role="number"] {{
        font-size: 15px;
        font-weight: 600;
        color: {p.accent};
    }}
    QLabel[role="metric"] {{
        font-size: 14px;
        font-weight: 600;
        color: {p.text};
    }}
    QLabel[state="ok"] {{ color: {p.ok}; }}
    QLabel[state="warning"] {{ color: {p.warning}; }}
    QLabel[state="error"] {{ color: {p.error}; }}
    QLabel[state="muted"] {{ color: {p.muted}; }}

    QPushButton {{
        background: {p.surface_alt};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{ background: #2b3542; }}
    QPushButton:pressed {{ background: #182028; }}
    QPushButton:disabled {{ color: #66717f; background: #171c23; }}
    QPushButton[primary="true"] {{
        background: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
        padding: 9px 16px;
    }}
    QPushButton[primary="true"]:hover {{ background: #ffb355; }}
    QPushButton[primary="true"]:disabled {{ background: #5a4526; color: #2c2415; }}
    QPushButton[danger="true"] {{ color: {p.error}; }}
    QToolButton {{
        background: transparent;
        color: {p.text};
        border: 1px solid transparent;
        border-radius: 8px;
        padding: 6px 8px;
        text-align: left;
    }}
    QToolButton:hover {{ background: {p.surface_alt}; }}
    QToolButton:checked {{
        background: {p.surface_alt};
        border: 1px solid {p.accent};
    }}
    QToolButton[rail="true"] {{
        padding: 1px 6px;
        font-size: 12px;
        text-align: center;
        border-radius: 6px;
    }}
    QToolButton[strip="true"] {{
        background: transparent;
        color: {p.text};
        border: none;
        border-radius: 0;
        padding: 2px 6px;
        font-weight: 600;
        text-align: left;
    }}
    QToolButton[strip="true"]:hover {{ background: {p.surface_alt}; }}
    QToolButton[strip="true"]:checked {{ background: transparent; }}
    QToolButton[stepStatus="done"] {{ border-color: {p.ok}; }}
    QToolButton[stepStatus="current"] {{
        background: {p.surface_alt};
        border: 1px solid {p.accent};
    }}
    QToolButton[stepStatus="pending"] {{ color: {p.muted}; }}
    QToolButton[stepStatus="skipped"] {{ color: {p.warning}; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {p.surface_deep};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 5px 8px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
    QComboBox:disabled, QPlainTextEdit:disabled {{
        color: #66717f;
        background: #141920;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        selection-background-color: {p.surface_alt};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background: {p.surface_alt};
        border: none;
        width: 16px;
    }}

    QGroupBox {{
        background: transparent;
        border: 1px solid {p.border};
        border-radius: 9px;
        margin-top: 10px;
        padding: 6px 6px 4px 6px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 0 4px;
        color: {p.muted};
    }}

    QDockWidget {{
        color: {p.text};
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }}
    QDockWidget::title {{
        background: {p.surface};
        padding: 4px 8px;
        border: 1px solid {p.border};
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }}
    QDockWidget > QWidget {{ background: {p.surface}; }}

    QWidget#profileBar {{
        background: {p.surface};
        border-bottom: 1px solid {p.border};
    }}
    QWidget#histogramStrip, QWidget#scanStrip {{
        background: {p.surface};
        border-top: 1px solid {p.border};
    }}
    QWidget#histogramBody, QWidget#scanBody {{ background: {p.surface}; }}
    QWidget#spectrumFrame {{
        background: {p.surface};
        border-left: 1px solid {p.border};
        border-top: 1px solid {p.border};
        border-bottom: 1px solid {p.border};
    }}

    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 8px;
        background: {p.surface};
    }}
    QTabBar::tab {{
        background: {p.surface};
        color: {p.muted};
        padding: 6px 14px;
        border: 1px solid transparent;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
    }}
    QTabBar::tab:selected {{
        background: {p.surface_alt};
        color: {p.text};
        border-color: {p.border};
    }}

    QMenuBar {{
        background: {p.surface};
        color: {p.text};
        border-bottom: 1px solid {p.border};
    }}
    QMenuBar::item {{ background: transparent; padding: 5px 10px; }}
    QMenuBar::item:selected {{ background: {p.surface_alt}; }}
    QMenu {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 4px;
    }}
    QMenu::item {{ padding: 6px 22px 6px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {p.surface_alt}; }}
    QMenu::item:disabled {{ color: #66717f; }}

    QStatusBar {{
        background: {p.surface};
        color: {p.muted};
        border-top: 1px solid {p.border};
    }}
    QStatusBar QLabel {{ color: {p.muted}; padding: 0 7px; }}
    QStatusBar QLabel[alert="true"] {{ color: {p.warning}; }}
    QStatusBar::item {{ border: none; }}

    QToolTip {{
        background: {p.surface_alt};
        color: {p.text};
        border: 1px solid {p.accent};
        padding: 5px 7px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: {p.surface_deep};
        border: none;
        width: 11px;
        height: 11px;
        margin: 0;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: #3a4655;
        border-radius: 5px;
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollBar::handle:hover {{ background: #4b5a6c; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QSplitter::handle {{ background: {p.border}; }}
    QSplitter::handle:horizontal {{ width: 2px; }}
    QSplitter::handle:vertical {{ height: 2px; }}

    QProgressBar {{
        background: {p.surface_deep};
        border: 1px solid {p.border};
        border-radius: 6px;
        text-align: center;
        color: {p.text};
        min-height: 16px;
    }}
    QProgressBar::chunk {{
        background: {p.accent};
        border-radius: 5px;
    }}

    QCheckBox, QRadioButton {{ spacing: 7px; color: {p.text}; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 14px; height: 14px;
        border: 1px solid {p.border};
        border-radius: 4px;
        background: {p.surface_deep};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
    }}

    QTableWidget, QTableView {{
        background: {p.surface_deep};
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 7px;
        gridline-color: {p.border};
        selection-background-color: {p.surface_alt};
    }}
    QHeaderView::section {{
        background: {p.surface_alt};
        color: {p.muted};
        border: none;
        padding: 5px;
    }}

    QFrame[role="separator"] {{ background: {p.border}; max-height: 1px; }}
    """


# @args: app - the QApplication to theme (the only one Qt allows)
# @return: none. Idempotent: calling it twice is harmless
def apply_theme(app: QApplication) -> None:
    # Fusion is the style that honours a palette and a stylesheet on both
    # Windows and Linux; the native styles override half the colours and the
    # window would look different on each platform.
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(PALETTE.background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(PALETTE.surface_deep))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PALETTE.surface))
    palette.setColor(QPalette.ColorRole.Text, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(PALETTE.surface_alt))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PALETTE.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(PALETTE.accent_text))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PALETTE.surface_alt))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(PALETTE.text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(PALETTE.muted))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
                     QColor("#66717f"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                     QColor("#66717f"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())


# @args: size - the square side in pixels
# @return: the SolarScribe sun as a transparent pixmap, drawn with QPainter
def sun_pixmap(size: int = 64) -> QPixmap:
    size = max(8, int(size))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    centre = QPointF(size / 2.0, size / 2.0)
    radius = size * 0.26
    accent = QColor(PALETTE.accent)

    # The rays: eight short strokes, lengthened by a thinner outer ring so the
    # icon still reads at 16 px in a task bar.
    painter.setPen(QPen(accent, max(1.0, size * 0.045),
                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    inner = radius * 1.25
    outer = radius * 1.75
    for step in range(8):
        angle = step * 3.141592653589793 / 4.0
        start = QPointF(centre.x() + inner * _cos(angle),
                        centre.y() + inner * _sin(angle))
        end = QPointF(centre.x() + outer * _cos(angle),
                      centre.y() + outer * _sin(angle))
        painter.drawLine(start, end)

    # The disc, with a warmer rim: a flat circle at 16 px looks like a dot.
    glow = QColor(PALETTE.accent)
    glow.setAlpha(70)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(centre, radius * 1.18, radius * 1.18)
    painter.setBrush(accent)
    painter.drawEllipse(centre, radius, radius)
    painter.setBrush(QColor("#ffe0a3"))
    painter.drawEllipse(centre, radius * 0.62, radius * 0.62)
    painter.end()
    return pixmap


# @args: size - the square side in pixels
# @return: the sun as a QIcon, ready for setWindowIcon()
def sun_icon(size: int = 64) -> QIcon:
    icon = QIcon()
    for side in (16, 24, 32, 48, 64, 128):
        icon.addPixmap(sun_pixmap(side))
    return icon


# @args: angle - radians
# @return: its cosine. Kept local so the drawing block does not need numpy
def _cos(angle: float) -> float:
    import math
    return math.cos(angle)


# @args: angle - radians
# @return: its sine
def _sin(angle: float) -> float:
    import math
    return math.sin(angle)
