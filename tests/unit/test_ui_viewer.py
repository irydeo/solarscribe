############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui viewer test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The viewer is where the observer judges the exposure and places the band, so
# the tests exercise the three things that must not lie: the frame becomes a
# picture, the stretch changes the picture and not the data, and the band drag
# maps back to frame pixels one to one.

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from solarscribe.devices.abc import ROI  # noqa: E402
from solarscribe.ui.histogram import HistogramWidget  # noqa: E402
from solarscribe.ui.live_viewer import LiveViewer  # noqa: E402


class FakeStats:
    mean = 12000.0
    std = 4000.0


class FakeFrame:
    def __init__(self, width=640, height=480, value=30000):
        self._array = np.full((height, width), 10000, dtype=np.uint16)
        self._array[300:450, :] = value
        self._array[450:, :] = 60000
        self.data = memoryview(self._array)
        self.width = width
        self.height = height
        self.dtype = np.dtype(np.uint16)
        self.roi: ROI = (0, 0, width, height)
        self.sequence = 1
        self.timestamp = 0.0

    def stats(self):
        return FakeStats()

    def cut_roi(self, roi):
        x, y, width, height = roi
        piece = np.ascontiguousarray(self._array[y:y + height, x:x + width])
        frame = FakeFrame()
        frame._array = piece
        frame.data = memoryview(piece)
        frame.width, frame.height = width, height
        return frame


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_a_frame_becomes_an_image_and_the_stretch_changes_it(qapp):
    viewer = LiveViewer()
    viewer.resize(640, 480)
    assert viewer.image() is None
    viewer.set_frame(FakeFrame())
    assert viewer.image() is not None
    assert viewer.frame_size() == (640, 480)
    before = viewer.image().pixel(10, 350)
    viewer.set_stretch(25.0, 75.0)
    after = viewer.image().pixel(10, 350)
    assert before != after


def test_zoom_pan_and_fit(qapp):
    viewer = LiveViewer()
    viewer.resize(640, 480)
    viewer.show()
    viewer.set_frame(FakeFrame())
    first = viewer._image_rect()
    viewer.set_zoom(4)
    assert viewer.zoom() == 4
    zoomed = viewer._image_rect()
    assert zoomed.width() > first.width()
    viewer.pan_by(40, 20)
    panned = viewer._image_rect()
    assert panned.left() == zoomed.left() + 40
    viewer.reset_view()
    assert viewer.zoom() == 1
    assert viewer._image_rect().left() == first.left()


def test_dragging_the_band_emits_frame_pixels(qapp):
    viewer = LiveViewer()
    viewer.resize(640, 480)
    viewer.show()
    viewer.set_frame(FakeFrame())
    viewer.set_band((100, 100, 200, 100))
    emitted = []
    viewer.bandEdited.connect(emitted.append)
    # The widget maps the frame with a 2 px margin, so a point inside the band
    # is around (150, 150). The drag moves it by 50 px in both directions.
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, pos=QPoint(150, 150))
    QTest.mouseMove(viewer, QPoint(200, 200))
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert emitted, "the band drag emitted nothing"
    band = emitted[-1]
    assert band[0] > 100 and band[1] > 100
    assert band[2] == 200 and band[3] == 100     # size unchanged when moving


def test_histogram_counts_the_frame(qapp):
    histogram = HistogramWidget()
    histogram.set_frame(FakeFrame())
    assert histogram.peaks() > 0
    histogram.set_stretch(5.0, 95.0)
    assert histogram.counts.sum() > 0


def test_histogram_click_moves_the_nearest_handle(qapp):
    histogram = HistogramWidget()
    histogram.resize(400, 120)
    histogram.show()
    histogram.set_frame(FakeFrame())
    histogram.set_stretch(5.0, 95.0)
    seen = []
    histogram.stretchChanged.connect(lambda low, high: seen.append((low, high)))
    # A click near the left edge must grab the black handle, not the white one.
    QTest.mouseClick(histogram, Qt.MouseButton.LeftButton, pos=QPoint(6, 50))
    assert seen, "the handle click emitted nothing"
    assert seen[-1][0] < 5.0
    assert seen[-1][1] == pytest.approx(95.0)
    # A click near the right edge grabs the white handle.
    QTest.mouseClick(histogram, Qt.MouseButton.LeftButton, pos=QPoint(390, 50))
    assert seen[-1][1] > 95.0
    # The white handle never crosses the black one.
    histogram.set_stretch(48.0, 52.0)
    QTest.mouseClick(histogram, Qt.MouseButton.LeftButton, pos=QPoint(4, 50))
    QTest.mouseClick(histogram, Qt.MouseButton.LeftButton, pos=QPoint(396, 50))
    low, high = histogram.stretch()
    assert low < high


def test_histogram_reports_saturation(qapp):
    class SaturatedFrame(FakeFrame):
        def __init__(self):
            super().__init__()
            self._array[100:200, :] = 65535
            self.data = memoryview(self._array)

    histogram = HistogramWidget()
    histogram.set_frame(SaturatedFrame())
    assert histogram.saturation_fraction() > 0.1
    histogram.set_frame(FakeFrame())
    assert histogram.saturation_fraction() == pytest.approx(0.0)
