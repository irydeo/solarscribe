############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui live viewer module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The live video area: frame, stretch, zoom, grid, slit cross and the ROI band
# overlay (ADR-009, ADR-010).
#
# This is a custom widget and therefore never enters a .ui (ADR-009: the viewer,
# the histogram and the ROI overlay go in as a placeholder + replaceWidget).
#
# Decisions that matter:
#   - The stretch is a percentile pair, not a fixed range. At 16 bit the
#     interesting part of a solar spectrum is a narrow band of levels, and a
#     linear 0 to 65535 map would show a black rectangle. Percentiles ignore the
#     few hot pixels that would otherwise set the white point.
#   - The image is copied out of the frame. QImage does not own the numpy
#     buffer, and the buffer is recycled by the next frame; a copy is the price
#     of not painting garbage.
#   - The band, not the capture rectangle, is edited on the video: the frame IS
#     the capture ROI (the camera already cropped it), so dragging a bigger
#     rectangle around it would be a lie. The capture rectangle is typed in the
#     ROI step; the band is dragged here. The window says this in plain words.
#   - One pixel equals one frame pixel in the mapping, so the numbers the user
#     types and the numbers the engine receives are the same.

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from solarscribe.devices.abc import ROI

from .theme import PALETTE

__all__ = ["LiveViewer"]


class LiveViewer(QWidget):
    bandEdited = Signal(object)       # ROI in FRAME pixels
    zoomChanged = Signal(int)

    # @args: parent - the Qt parent
    # @return: the viewer, with no frame yet
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LiveViewer")
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self.tr("Live video"))

        self._image: QImage | None = None
        self._array: np.ndarray | None = None
        self._frame_w = 0
        self._frame_h = 0
        self._zoom = 1
        self._low_pct = 1.0
        self._high_pct = 99.0
        self._grid = False
        self._cross = True
        self._show_band = True
        self._editable = True
        self._band: ROI | None = None
        self._drag_mode = ""
        self._drag_start: QPoint | None = None
        self._drag_band: ROI | None = None
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_origin = QPoint(0, 0)

    # ------------------------------------------------------------------ input

    # @args: frame - anything satisfying the Frame protocol: data, width,
    #                height, dtype
    def set_frame(self, frame) -> None:
        try:
            width = int(frame.width)
            height = int(frame.height)
            array = np.frombuffer(frame.data, dtype=frame.dtype)
            if array.size != width * height:
                return
            array = array.reshape(height, width)
        except (AttributeError, TypeError, ValueError):
            return
        if width <= 0 or height <= 0:
            return
        self._frame_w = width
        self._frame_h = height
        # Keep a copy of the raw levels: the stretch can change without a new
        # frame, and the next frame recycles the SDK buffer.
        self._array = np.array(array, copy=True)
        self._image = self._stretch_to_image(self._array)
        self.update()

    # @args: low, high - percentiles of the levels (0 to 100)
    def set_stretch(self, low: float, high: float) -> None:
        self._low_pct = max(0.0, min(float(low), 49.0))
        self._high_pct = max(51.0, min(float(high), 100.0))
        if self._array is not None:
            self._image = self._stretch_to_image(self._array)
        self.update()

    # @args: level - the zoom factor, clamped to 1..8
    def set_zoom(self, level: int) -> None:
        level = max(1, min(8, int(level)))
        if level != self._zoom:
            self._zoom = level
            if level == 1:
                # At fit there is nothing to pan; keeping an old offset would
                # show a crop the user cannot explain.
                self._pan = QPoint(0, 0)
            self.zoomChanged.emit(level)
            self.update()

    # @args: dx, dy - move the magnified image by this many widget pixels
    def pan_by(self, dx: int, dy: int) -> None:
        if self._zoom > 1:
            self._pan += QPoint(int(dx), int(dy))
            self.update()

    # @args: none. Back to fit and centred
    def reset_view(self) -> None:
        self._pan = QPoint(0, 0)
        self.set_zoom(1)
        self.update()

    # @args: on - show the light grid
    def set_grid(self, on: bool) -> None:
        self._grid = bool(on)
        self.update()

    # @args: on - show the slit cross at the frame centre
    def set_cross(self, on: bool) -> None:
        self._cross = bool(on)
        self.update()

    # @args: roi - the spectral band in FRAME pixels, or None to hide it
    def set_band(self, roi: ROI | None) -> None:
        self._band = tuple(int(v) for v in roi) if roi is not None else None
        self.update()

    # @args: on - show the band overlay at all (the ROI checkbox turns it off)
    def set_show_band(self, on: bool) -> None:
        self._show_band = bool(on)
        self.update()

    # @args: on - allow the band to be dragged
    def set_editable(self, on: bool) -> None:
        self._editable = bool(on)

    # @args: none
    # @return: the band currently drawn, in frame pixels
    def band(self) -> ROI | None:
        return self._band

    # @args: none. Empties the viewer for a closed camera
    def clear(self) -> None:
        self._image = None
        self._array = None
        self._frame_w = 0
        self._frame_h = 0
        self.update()

    # @args: none
    # @return: the rendered image, or None before the first frame
    def image(self) -> QImage | None:
        return self._image

    # @args: none
    # @return: the frame size the viewer last received
    def frame_size(self) -> tuple[int, int]:
        return self._frame_w, self._frame_h

    # @args: none
    # @return: the zoom factor
    def zoom(self) -> int:
        return self._zoom

    # ---------------------------------------------------------------- painting

    # @args: event - paint event
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(PALETTE.surface_deep))

        if self._image is None or self._frame_w == 0:
            self._paint_empty(painter)
            painter.end()
            return

        target = self._image_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(target, self._image)
        painter.setPen(QPen(QColor(PALETTE.border), 1))
        painter.drawRect(target)

        if self._grid:
            self._paint_grid(painter, target)
        if self._show_band and self._band is not None:
            self._paint_band(painter, target)
        if self._cross:
            self._paint_cross(painter, target)
        painter.end()

    # @args: painter - the active painter
    def _paint_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor(PALETTE.muted))
        title = self.tr("No video yet")
        detail = self.tr(
            "Connect the camera and start the stream. The ROI step draws the "
            "spectral band over this view.")
        rect = self.rect().adjusted(30, 0, -30, 0)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         f"{title}\n\n{detail}")

    # @args: painter, target - the image rectangle
    def _paint_grid(self, painter: QPainter, target: QRect) -> None:
        pen = QPen(QColor(255, 255, 255, 26), 1)
        painter.setPen(pen)
        for index in range(1, 8):
            x = target.left() + target.width() * index / 8
            painter.drawLine(QPoint(int(x), target.top()),
                             QPoint(int(x), target.bottom()))
        for index in range(1, 6):
            y = target.top() + target.height() * index / 6
            painter.drawLine(QPoint(target.left(), int(y)),
                             QPoint(target.right(), int(y)))

    # @args: painter, target - the image rectangle
    def _paint_band(self, painter: QPainter, target: QRect) -> None:
        rect = self._band_rect(target)
        if rect.isNull():
            return
        fill = QColor(PALETTE.accent)
        fill.setAlpha(34)
        painter.fillRect(rect, fill)
        painter.setPen(QPen(QColor(PALETTE.accent), 2))
        painter.drawRect(rect)

        # The caption sits on the spectrum, which is bright and busy; a dark
        # plate behind it is what makes it readable at a glance.
        label = QRect(rect.left() + 4, rect.top() + 3,
                      min(230, max(20, rect.width() - 8)), 18)
        painter.fillRect(label, QColor(0, 0, 0, 150))
        painter.setPen(QColor(PALETTE.text))
        painter.drawText(label.adjusted(4, 0, -4, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self.tr("Spectral band: drag to move, corners to resize"))

        # Four corner handles, big enough for a mouse and honest about where
        # the drag will take hold. They are painted last so the caption plate
        # cannot hide them.
        painter.setBrush(QColor(PALETTE.accent))
        for corner in (rect.topLeft(), rect.topRight(),
                       rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(QRect(corner.x() - 5, corner.y() - 5, 10, 10))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # @args: painter, target - the image rectangle
    def _paint_cross(self, painter: QPainter, target: QRect) -> None:
        pen = QPen(QColor(PALETTE.accent), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        cx = target.left() + target.width() / 2.0
        cy = target.top() + target.height() / 2.0
        painter.drawLine(QPoint(int(cx), target.top()),
                         QPoint(int(cx), target.bottom()))
        painter.drawLine(QPoint(target.left(), int(cy)),
                         QPoint(target.right(), int(cy)))

    # ---------------------------------------------------------------- geometry

    # @args: none
    # @return: where the frame is painted, keeping its aspect ratio and
    #          applying the zoom around the centre
    def _image_rect(self) -> QRect:
        if self._frame_w == 0 or self._frame_h == 0:
            return QRect()
        available = self.rect().adjusted(2, 2, -2, -2)
        scale = min(available.width() / self._frame_w,
                    available.height() / self._frame_h)
        width = max(1, int(self._frame_w * scale * self._zoom))
        height = max(1, int(self._frame_h * scale * self._zoom))
        x = available.left() + (available.width() - width) // 2 + self._pan.x()
        y = available.top() + (available.height() - height) // 2 + self._pan.y()
        return QRect(x, y, width, height)

    # @args: target - the image rectangle; roi - frame pixels
    # @return: the same region in widget pixels
    def _roi_to_widget(self, target: QRect, roi: ROI) -> QRect:
        x, y, width, height = roi
        left = target.left() + x * target.width() / self._frame_w
        top = target.top() + y * target.height() / self._frame_h
        right = target.left() + (x + width) * target.width() / self._frame_w
        bottom = target.top() + (y + height) * target.height() / self._frame_h
        return QRect(int(left), int(top), max(1, int(right - left)),
                     max(1, int(bottom - top)))

    # @args: target - the image rectangle
    # @return: the band in widget pixels, or a null rect
    def _band_rect(self, target: QRect) -> QRect:
        if self._band is None:
            return QRect()
        return self._roi_to_widget(target, self._band)

    # @args: point - a widget position
    # @return: the frame pixel under it, clamped to the frame
    def _to_frame(self, point: QPoint) -> tuple[int, int]:
        target = self._image_rect()
        if target.width() == 0 or target.height() == 0:
            return 0, 0
        x = (point.x() - target.left()) * self._frame_w / target.width()
        y = (point.y() - target.top()) * self._frame_h / target.height()
        return (max(0, min(int(round(x)), self._frame_w - 1)),
                max(0, min(int(round(y)), self._frame_h - 1)))

    # ------------------------------------------------------------------- mouse

    # @args: event - mouse press
    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton and self._editable
                and self._show_band and self._band is not None
                and self._image is not None):
            target = self._image_rect()
            rect = self._band_rect(target)
            position = event.position().toPoint()
            if rect.adjusted(-8, -8, 8, 8).contains(position):
                self._drag_mode = self._corner_hit(rect, position)
                self._drag_start = position
                self._drag_band = tuple(self._band)
                return
        if (event.button() == Qt.MouseButton.LeftButton
                and self._zoom > 1 and self._image is not None):
            # At zoom the image is bigger than the viewport; dragging empty
            # space pans it, so a corner that scrolled out is reachable.
            self._panning = True
            self._pan_origin = event.position().toPoint()
            return
        super().mousePressEvent(event)

    # @args: event - mouse move while dragging
    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            position = event.position().toPoint()
            delta = position - self._pan_origin
            self._pan_origin = position
            self.pan_by(delta.x(), delta.y())
            return
        if self._drag_mode and self._drag_start is not None and self._drag_band:
            position = event.position().toPoint()
            dx = position.x() - self._drag_start.x()
            dy = position.y() - self._drag_start.y()
            target = self._image_rect()
            if target.width() and target.height():
                fx = int(round(dx * self._frame_w / target.width()))
                fy = int(round(dy * self._frame_h / target.height()))
                self._band = self._moved_band(self._drag_band, self._drag_mode,
                                              fx, fy)
                self.update()
            return
        super().mouseMoveEvent(event)

    # @args: event - mouse release
    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            return
        if self._drag_mode:
            self._drag_mode = ""
            self._drag_start = None
            self._drag_band = None
            if self._band is not None:
                self.bandEdited.emit(tuple(self._band))
            return
        super().mouseReleaseEvent(event)

    # @args: event - wheel event: zoom around the centre
    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y()
        if steps == 0:
            return
        self.set_zoom(self._zoom + (1 if steps > 0 else -1))
        event.accept()

    # @args: rect - the band in widget pixels; point - the cursor
    # @return: "move" or the corner being resized
    def _corner_hit(self, rect: QRect, point: QPoint) -> str:
        threshold = 10
        corners = {
            "tl": rect.topLeft(), "tr": rect.topRight(),
            "bl": rect.bottomLeft(), "br": rect.bottomRight(),
        }
        for name, corner in corners.items():
            if (abs(point.x() - corner.x()) <= threshold
                    and abs(point.y() - corner.y()) <= threshold):
                return name
        return "move"

    # @args: band - the band at drag start; mode - corner or "move"; dx, dy -
    #        frame-pixel displacement
    # @return: the new band, clamped to the frame and to a 4 px minimum
    def _moved_band(self, band: ROI, mode: str, dx: int, dy: int) -> ROI:
        x, y, width, height = band
        left, top = x, y
        right, bottom = x + width, y + height
        if mode == "move":
            left = max(0, min(x + dx, self._frame_w - width))
            top = max(0, min(y + dy, self._frame_h - height))
            return (left, top, width, height)
        if mode in ("tl", "bl"):
            left = max(0, min(x + dx, right - 4))
        if mode in ("tr", "br"):
            right = min(self._frame_w, max(x + 4, right + dx))
        if mode in ("tl", "tr"):
            top = max(0, min(y + dy, bottom - 4))
        if mode in ("bl", "br"):
            bottom = min(self._frame_h, max(y + 4, bottom + dy))
        return (left, top, right - left, bottom - top)

    # @args: none
    # @return: the size hint the video wants, biased to a wide strip
    def sizeHint(self) -> QSize:
        return QSize(720, 260)

    # @args: none
    # @return: the image as a small grayscale array, for the tests
    def _to_array(self) -> np.ndarray | None:
        if self._image is None:
            return None
        width = self._image.width()
        height = self._image.height()
        data = self._image.constBits()
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width)

    # @args: array - the uint16 frame
    # @return: an 8-bit grayscale QImage stretched between the two percentiles
    def _stretch_to_image(self, array: np.ndarray) -> QImage:
        # Sample every fourth pixel for the percentiles: 1/16 of the work, and
        # the 1st and 99th percentiles of a spectrum do not care about the rest.
        sample = array[::4, ::4]
        try:
            low, high = np.percentile(sample, [self._low_pct, self._high_pct])
        except (TypeError, ValueError):
            low, high = 0.0, 65535.0
        if high <= low:
            high = low + 1.0
        scaled = np.clip((array.astype(np.float32) - low) * (255.0 / (high - low)),
                         0.0, 255.0).astype(np.uint8)
        scaled = np.ascontiguousarray(scaled)
        height, width = scaled.shape
        image = QImage(scaled.data, width, height, width,
                       QImage.Format.Format_Grayscale8)
        # The QImage must not borrow the numpy buffer: it dies with `scaled`.
        return image.copy()
