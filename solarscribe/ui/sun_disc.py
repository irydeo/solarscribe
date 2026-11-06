############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui sun disc module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The schematic solar disk shared by the scan visualisation, the quick recon and
# the sky calendar (ADR-020).
#
# Why a schematic disk instead of a photo: the app has to work with no network
# at all (ADR-021). A drawn disk is always available, it cannot be mistaken for
# the real Sun, and it can carry the overlay (captured strip, slit line, row
# bands) without fighting the texture of a real image. When the network is on
# and the observer asks for it, a real SDO image replaces the drawing, and the
# dialog says which one is on screen.
#
# The percentage is drawn with words, not only as a bar: "Captured 42% of the
# planned sweep" says what the number is, which a bare 42% does not.

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import PALETTE

__all__ = ["QuickRecon", "SunDiscWidget"]


class SunDiscWidget(QWidget):
    # @args: parent - the Qt parent
    # @return: the schematic disk at 0 percent
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SunDiscWidget")
        self.setMinimumSize(220, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._progress = 0.0
        self._rows = 1
        self._row = 0
        self._image: QImage | None = None
        self._result = ""
        self.setToolTip(self.tr(
            "Where the slit is on the Sun. The shaded part is already captured; "
            "the line is the slit right now; the percentage is of the planned "
            "sweep, so 100% means the plan finished, not that the image is done."))

    # @args: progress - 0.0 to 1.0 of the planned sweep; row - mosaic row now
    def set_progress(self, progress: float, row: int = 0) -> None:
        self._progress = max(0.0, min(1.0, float(progress)))
        self._row = max(0, int(row))
        self.update()

    # @args: rows - how many rows the plan has (1 for a simple scan)
    def set_rows(self, rows: int) -> None:
        self._rows = max(1, int(rows))
        self.update()

    # @args: none
    # @return: the rows of the plan currently drawn
    def rows(self) -> int:
        return self._rows

    # @args: image - the day's real Sun image, or None for the schematic disk
    def set_background(self, image: QImage | None) -> None:
        self._image = image
        self.update()

    # @args: text - a short result sentence to draw under the disk, or ""
    def set_result(self, text: str) -> None:
        self._result = str(text)
        self.update()

    # @args: none
    # @return: the result sentence currently drawn
    def result(self) -> str:
        return self._result

    # @args: none
    # @return: the percentage as an integer, what the label shows
    def percentage(self) -> int:
        return int(round(self._progress * 100.0))

    # @args: none
    # @return: the captured fraction, 0.0 to 1.0
    def captured_fraction(self) -> float:
        return self._progress

    # @args: event - paint event
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(PALETTE.surface_deep))

        side = max(40, min(self.width() - 20, self.height() - 34))
        area = QRectF((self.width() - side) / 2.0, 6.0, side, side)
        centre = area.center()
        radius = side / 2.0

        # The disk: a faint warm body with a defined limb. The limb matters,
        # because the scan is a crossing of it.
        gradient = QRadialGradient(centre, radius)
        if self._image is not None:
            gradient.setColorAt(0.0, QColor("#ffd9a0"))
            gradient.setColorAt(1.0, QColor("#a8641b"))
        else:
            gradient.setColorAt(0.0, QColor(244, 163, 64, 70))
            gradient.setColorAt(0.85, QColor(244, 163, 64, 40))
            gradient.setColorAt(1.0, QColor(244, 163, 64, 90))
        painter.setPen(QPen(QColor(PALETTE.accent), 1.5))
        painter.setBrush(gradient)
        painter.drawEllipse(area)

        if self._image is not None:
            path = QPainterPath()
            path.addEllipse(area)
            painter.save()
            painter.setClipPath(path)
            painter.drawImage(area, self._image)
            painter.restore()

        # Mosaic row separators: they tell the observer which pass produced the
        # current strip.
        if self._rows > 1:
            painter.setPen(QPen(QColor(255, 255, 255, 60), 1,
                                Qt.PenStyle.DotLine))
            for row in range(1, self._rows):
                y = area.top() + area.height() * row / self._rows
                painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))

        # Captured strip and the slit. The slit moves from left to right, which
        # is the direction of the sweep in Right Ascension for a solar image.
        slit_x = area.left() + area.width() * self._progress
        captured = QPainterPath()
        captured.addEllipse(area)
        painter.save()
        painter.setClipPath(captured)
        fill = QColor(PALETTE.accent)
        fill.setAlpha(70)
        painter.fillRect(QRectF(area.left(), area.top(),
                                max(0.0, slit_x - area.left()), area.height()),
                         fill)
        painter.restore()

        painter.setPen(QPen(QColor(PALETTE.accent), 2))
        painter.drawLine(QPointF(slit_x, area.top()),
                         QPointF(slit_x, area.bottom()))

        # The words explain the figure; a percentage alone would not.
        painter.setPen(QColor(PALETTE.text))
        caption = self.tr("Captured {percent}% of the planned sweep").format(
            percent=self.percentage())
        painter.drawText(QRect(4, self.height() - 28, self.width() - 8, 18),
                         Qt.AlignmentFlag.AlignCenter, caption)
        if self._result:
            painter.setPen(QColor(PALETTE.muted))
            painter.drawText(QRect(4, self.height() - 14, self.width() - 8, 14),
                             Qt.AlignmentFlag.AlignCenter, self._result)
        painter.end()


class QuickRecon(QWidget):
    # The shg.quick_recon preview, painted on screen only (ADR-020). The widget
    # receives a normalised image from the engine; the fallback accepts strips
    # from the last-resort UI demo. It never exports and never claims to be
    # calibrated: the label and the tooltip say so.

    # @args: parent - the Qt parent
    # @return: the widget, empty until the first preview
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("QuickRecon")
        self.setMinimumSize(200, 70)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._strips: list[np.ndarray] = []
        self._image: QImage | None = None
        self._message = ""
        self.setToolTip(self.tr(
            "A light, non-authoritative preview from shg.quick_recon: the band "
            "averaged and stacked into a disk. It is not calibrated, not "
            "exported and not a substitute for post-processing."))

    # @args: image - float32 in 0..1, or uint8; None clears it
    #        message - what to say when there is nothing to paint
    def set_image(self, image, message: str = "") -> None:
        self._message = str(message)
        self._strips.clear()
        self._image = None
        if image is not None:
            try:
                array = np.asarray(image)
                if array.ndim != 2 or array.size == 0:
                    array = None
                elif array.dtype != np.uint8:
                    array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
                if array is not None:
                    array = np.ascontiguousarray(array)
                    height, width = array.shape
                    preview = QImage(array.data, width, height, width,
                                     QImage.Format.Format_Grayscale8)
                    self._image = preview.copy()
            except (TypeError, ValueError):
                self._image = None
        self.update()

    # @args: text - the sentence shown while there is no image
    def set_message(self, text: str) -> None:
        self._message = str(text)
        self.update()

    # @args: strip - a 2D uint8 array: the pixels of one slice of the disk
    def add_strip(self, strip) -> None:
        try:
            array = np.asarray(strip, dtype=np.uint8)
        except (TypeError, ValueError):
            return
        if array.ndim != 2 or array.size == 0:
            return
        self._image = None
        self._strips.append(np.ascontiguousarray(array))
        # The screen never needs more than a few thousand columns; dropping the
        # oldest ones keeps memory flat on a long mosaic.
        if len(self._strips) > 3000:
            self._strips = self._strips[-3000:]
        self.update()

    # @args: none
    def clear(self) -> None:
        self._strips.clear()
        self._image = None
        self._message = ""
        self.update()

    # @args: none
    # @return: whether there is something to show
    def has_image(self) -> bool:
        return self._image is not None or bool(self._strips)

    # @args: none
    # @return: the assembled reconstruction, or None
    def image(self) -> QImage | None:
        if self._image is not None:
            return self._image
        if not self._strips:
            return None
        try:
            frozen = np.hstack(self._strips)
        except ValueError:
            return None
        frozen = np.ascontiguousarray(frozen)
        height, width = frozen.shape
        image = QImage(frozen.data, width, height, width,
                       QImage.Format.Format_Grayscale8)
        return image.copy()

    # @args: event - paint event
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PALETTE.surface_deep))
        image = self.image()
        if image is None:
            painter.setPen(QColor(PALETTE.muted))
            text = self._message or self.tr(
                "The quick recon appears as the scan advances.")
            painter.drawText(self.rect().adjusted(6, 6, -6, -6),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             text)
            painter.end()
            return
        area = self.rect().adjusted(4, 4, -4, -4)
        scaled = image.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        x = area.left() + (area.width() - scaled.width()) // 2
        y = area.top() + (area.height() - scaled.height()) // 2
        painter.drawImage(QPointF(x, y), scaled)
        painter.setPen(QPen(QColor(PALETTE.border), 1))
        painter.drawRect(QRect(x, y, scaled.width(), scaled.height()))
        painter.end()
