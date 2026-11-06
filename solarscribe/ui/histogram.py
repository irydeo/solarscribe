############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui histogram module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The brightness histogram strip (ADR-009, ADR-026).
#
# It is the Unified FITS Editor's histogram, adapted to the Sun: compact, folded
# to a 24 px header until the observer opens it, and computed only on the
# SPECTRAL BAND, not the whole frame. The band is the part of the spectrum that
# matters; a histogram of the whole frame would be dominated by the dark rows and
# say nothing about the exposure that the SER will carry.
#
# It follows the UFE reference (/tmp/opencode/nightscribe/website/docs/adv-UFE.html):
#   - 256 bins in log scale, because the dark background has a huge peak that
#     would flatten the spectrum on a linear axis;
#   - blue/black and orange/white draggable handles, AstroImageJ style: a plain
#     click moves the nearest one, and the white handle never crosses the black;
#   - the zones the stretch throws away are shaded;
#   - a saturation warning, because a clipped spectrum cannot be recovered by the
#     post-processing.
#
# It is a custom widget, so it enters the .ui through a placeholder (ADR-009).

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import PALETTE

__all__ = ["HistogramWidget"]

BINS = 256
# The footer carries the two levels in DN. It is the part of the widget that says
# what the handles mean; without it the lines would be a puzzle.
FOOTER = 15
# A handle drag that leaves less than this fraction of the range between the two
# would turn the picture into a single level; keep a small gap.
MIN_GAP_FRACTION = 0.01
# Above this fraction of the band at the top level, the header warns. 0.1% is
# already visible as a white patch in the reconstructed disk.
SATURATION_WARNING = 0.001


class HistogramWidget(QWidget):
    stretchChanged = Signal(float, float)

    # @args: parent - the Qt parent
    # @return: the widget, waiting for its first frame
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HistogramWidget")
        self.setMinimumSize(220, 56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setToolTip(self.tr(
            "Counts per brightness level of the spectral band. The handles are "
            "the black and white points: below the black point and above the "
            "white point the viewer clips. Drag a handle, or click near one, to "
            "move the nearest. The numbers under the bars are the levels in "
            "camera counts (DN)."))
        self.counts = np.zeros(BINS, dtype=np.int64)
        self._low_pct = 1.0
        self._high_pct = 99.0
        self._max_level = 65535.0
        self._frame_w = 0
        self._frame_h = 0
        self._saturation = 0.0
        self._drag = ""

    # @args: frame - a Frame; the histogram is computed on a sample, because it
    #                repaints at video rate and the count does not need every
    #                pixel. Pass the spectral-band frame, not the full frame
    def set_frame(self, frame) -> None:
        try:
            width = int(frame.width)
            height = int(frame.height)
            array = np.frombuffer(frame.data, dtype=frame.dtype)
            if array.size != width * height:
                return
            array = array.reshape(height, width)[::4, ::4]
            self._max_level = (65535.0 if np.issubdtype(frame.dtype, np.uint16)
                               else 255.0)
        except (AttributeError, TypeError, ValueError):
            return
        self._frame_w = width
        self._frame_h = height
        counts, _ = np.histogram(array, bins=BINS, range=(0, self._max_level))
        self.counts = counts
        # Saturation is the fraction already at the top level. It is measured on
        # the same sample as the histogram, so the warning and the bars agree.
        top = float(self._max_level) * 0.995
        self._saturation = (float(np.count_nonzero(array >= top)) / float(array.size)
                            if array.size else 0.0)
        self.update()

    # @args: low, high - the percentiles the viewer uses (0 to 100)
    def set_stretch(self, low: float, high: float) -> None:
        self._low_pct = max(0.0, min(float(low), 49.0))
        self._high_pct = max(51.0, min(float(high), 100.0))
        self.update()

    # @args: none
    # @return: the black and white points as percentiles of the range
    def stretch(self) -> tuple[float, float]:
        return self._low_pct, self._high_pct

    # @args: none
    # @return: the fraction of the spectral band at the top level. The window
    #          turns it into the saturation sentence in the strip header
    def saturation_fraction(self) -> float:
        return self._saturation

    # @args: none
    # @return: the frame size the histogram last received, in frame pixels
    def frame_size(self) -> tuple[int, int]:
        return self._frame_w, self._frame_h

    # @args: none. Empties the histogram when the camera closes
    def clear(self) -> None:
        self.counts = np.zeros(BINS, dtype=np.int64)
        self._frame_w = 0
        self._frame_h = 0
        self._saturation = 0.0
        self.update()

    # @args: none
    # @return: the bin counts of the last frame, for the tests
    def peaks(self) -> int:
        return int(self.counts.max()) if self.counts.size else 0

    # ---------------------------------------------------------------- painting

    # @args: none
    # @return: the plot rectangle, above the footer that names the two levels
    def _area(self) -> QRect:
        rect = self.rect().adjusted(3, 3, -3, -3)
        if rect.height() <= FOOTER + 4:
            return rect
        return rect.adjusted(0, 0, 0, -FOOTER)

    # @args: level - a level in DN
    # @return: the x in widget pixels
    def _x_for(self, level: float) -> int:
        area = self._area()
        fraction = max(0.0, min(1.0, level / max(1.0, self._max_level)))
        return area.left() + int(round(fraction * area.width()))

    # @args: x - a widget x
    # @return: the level under it
    def _level_at(self, x: int) -> float:
        area = self._area()
        if area.width() <= 0:
            return 0.0
        fraction = (x - area.left()) / float(area.width())
        return max(0.0, min(1.0, fraction)) * self._max_level

    # @args: none
    # @return: (black level, white level) in DN
    def levels(self) -> tuple[float, float]:
        return (self._low_pct / 100.0 * self._max_level,
                self._high_pct / 100.0 * self._max_level)

    # @args: event - paint event
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(PALETTE.surface_deep))
        area = self._area()
        if area.width() <= 1 or area.height() <= 1:
            painter.end()
            return

        peak = int(self.counts.max()) if self.counts.size else 0
        if peak <= 0:
            painter.setPen(QColor(PALETTE.muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self.tr("Waiting for the first frame"))
            painter.end()
            return

        low, high = self.levels()

        # The clip zones: what the stretch throws away is shaded, so the
        # observer can see the price of the current handles before moving them.
        clip = QColor(PALETTE.error)
        clip.setAlpha(38)
        low_x = self._x_for(low)
        high_x = self._x_for(high)
        painter.fillRect(QRect(area.left(), area.top(),
                               max(0, low_x - area.left()), area.height()), clip)
        painter.fillRect(QRect(high_x, area.top(),
                               max(0, area.right() - high_x), area.height()), clip)

        # Bars in log scale: a solar spectrum has a huge peak at the background
        # level that would flatten everything else on a linear axis.
        scale = np.log1p(self.counts) / np.log1p(peak)
        bar_width = max(1.0, area.width() / float(BINS))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PALETTE.muted))
        for index, value in enumerate(scale):
            height = int(value * area.height())
            if height <= 0:
                continue
            x = area.left() + int(index * bar_width)
            painter.drawRect(QRect(x, area.bottom() - height,
                                   max(1, int(bar_width)), height))

        # The two handles, in the accent, with their DN under them. The DN is
        # needed: a bare line cannot tell the observer what level it is at.
        for level, label, colour in ((low, self.tr("black"), PALETTE.accent),
                                     (high, self.tr("white"), PALETTE.accent)):
            x = self._x_for(level)
            painter.setPen(QPen(QColor(colour), 1))
            painter.drawLine(x, area.top(), x, area.bottom())
            painter.setBrush(QColor(colour))
            painter.drawRect(QRect(x - 1, area.top(), 3, 6))
            painter.drawRect(QRect(x - 1, area.bottom() - 6, 3, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(PALETTE.muted))
        painter.drawText(QRect(area.left(), self.rect().bottom() - FOOTER,
                               area.width() // 2, FOOTER),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.tr("black {value}").format(value=int(round(low))))
        painter.drawText(QRect(area.left() + area.width() // 2,
                               self.rect().bottom() - FOOTER,
                               area.width() // 2, FOOTER),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                         self.tr("white {value}").format(value=int(round(high))))
        painter.end()

    # ------------------------------------------------------------------- mouse

    # @args: event - mouse press: choose the nearest handle and move it there
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if not self._area().contains(event.position().toPoint()):
            super().mousePressEvent(event)
            return
        level = self._level_at(event.position().toPoint().x())
        low, high = self.levels()
        self._drag = "low" if abs(level - low) <= abs(level - high) else "high"
        self._move_handle(level)
        event.accept()

    # @args: event - mouse move while dragging a handle
    def mouseMoveEvent(self, event) -> None:
        if not self._drag:
            super().mouseMoveEvent(event)
            return
        self._move_handle(self._level_at(event.position().toPoint().x()))
        event.accept()

    # @args: event - mouse release: finish the drag
    def mouseReleaseEvent(self, event) -> None:
        if self._drag:
            self._drag = ""
            self.stretchChanged.emit(self._low_pct, self._high_pct)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # @args: level - the level the handle should take, in DN
    def _move_handle(self, level: float) -> None:
        gap = max(1.0, self._max_level * MIN_GAP_FRACTION)
        if self._drag == "low":
            level = min(level, self._max_level - gap)
            self._low_pct = max(0.0, level / max(1.0, self._max_level) * 100.0)
            if self._low_pct > self._high_pct - MIN_GAP_FRACTION * 100.0:
                self._low_pct = self._high_pct - MIN_GAP_FRACTION * 100.0
        elif self._drag == "high":
            level = max(level, gap)
            self._high_pct = min(100.0, level / max(1.0, self._max_level) * 100.0)
            if self._high_pct < self._low_pct + MIN_GAP_FRACTION * 100.0:
                self._high_pct = self._low_pct + MIN_GAP_FRACTION * 100.0
        self.update()
        self.stretchChanged.emit(self._low_pct, self._high_pct)
