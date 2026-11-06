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

# The brightness histogram under the video (ADR-009).
#
# It answers one question the observer cannot answer by eye: is the exposure
# filling the range without clipping? The two vertical markers are the stretch
# limits the viewer uses, so the histogram and the picture cannot disagree: what
# is under the left marker is painted black, what is above the right marker is
# painted white. That is also why the widget draws both, instead of a bare
# distribution nobody can read.
#
# A custom widget, so it enters the .ui through a placeholder (ADR-009).

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import PALETTE

__all__ = ["HistogramWidget"]

BINS = 128


class HistogramWidget(QWidget):
    # @args: parent - the Qt parent
    # @return: the widget, waiting for its first frame
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HistogramWidget")
        self.setMinimumSize(220, 70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setToolTip(self.tr(
            "Counts per brightness level. The markers are the black and white "
            "points of the stretch: below the first and above the second, the "
            "viewer clips."))
        self.counts = np.zeros(BINS, dtype=np.int64)
        self._low = 0.0
        self._high = 255.0
        self._max_level = 255.0

    # @args: frame - a Frame; the histogram is computed on a sample, because it
    #                repaints at video rate and the count does not need every
    #                pixel
    def set_frame(self, frame) -> None:
        try:
            width = int(frame.width)
            height = int(frame.height)
            array = np.frombuffer(frame.data, dtype=frame.dtype)
            if array.size != width * height:
                return
            array = array.reshape(height, width)[::4, ::4]
            self._max_level = 65535.0 if np.issubdtype(frame.dtype, np.uint16) else 255.0
        except (AttributeError, TypeError, ValueError):
            return
        counts, _ = np.histogram(array, bins=BINS, range=(0, self._max_level))
        self.counts = counts
        self.update()

    # @args: low, high - the percentiles the viewer uses (0 to 100)
    def set_stretch(self, low: float, high: float) -> None:
        self._low = float(low) / 100.0 * self._max_level
        self._high = float(high) / 100.0 * self._max_level
        self.update()

    # @args: none. Empties the histogram when the camera closes
    def clear(self) -> None:
        self.counts = np.zeros(BINS, dtype=np.int64)
        self.update()

    # @args: event - paint event
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(PALETTE.surface_deep))
        area = self.rect().adjusted(3, 3, -3, -14)
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

        # Bars in log scale: a solar spectrum has a huge peak at the background
        # level that would flatten everything else on a linear axis.
        scale = np.log1p(self.counts) / np.log1p(peak)
        bar_width = max(1.0, area.width() / BINS)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PALETTE.muted))
        for index, value in enumerate(scale):
            height = int(value * area.height())
            if height <= 0:
                continue
            x = area.left() + int(index * bar_width)
            painter.drawRect(QRect(x, area.bottom() - height,
                                   max(1, int(bar_width)), height))

        # The two stretch limits, in the accent, with a small word each so the
        # lines are not a puzzle.
        for level, label in ((self._low, self.tr("black")),
                             (self._high, self.tr("white"))):
            x = area.left() + int(level / max(1.0, self._max_level) * area.width())
            painter.setPen(QPen(QColor(PALETTE.accent), 1))
            painter.drawLine(x, area.top(), x, area.bottom())
            painter.setPen(QColor(PALETTE.muted))
            painter.drawText(max(area.left(), x - 18), self.rect().bottom() - 11,
                             36, 12, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

    # @args: none
    # @return: the bin counts of the last frame, for the tests
    def peaks(self) -> int:
        return int(self.counts.max()) if self.counts.size else 0
