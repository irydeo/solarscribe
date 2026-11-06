############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui spectrum panel test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The line panel is the reference list, not a measurement: these tests build a
# synthetic spectrum with known lines and check that the names, the wavelengths
# and the frame rows agree with the catalog. They also pin the honest states:
# no dispersion, no spectrum, no line, no match and low confidence. A wrong name
# is worse than no name, so the low-confidence case must hide the table.

import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QWidget  # noqa: E402

from solarscribe.config import store  # noqa: E402
from solarscribe.shg.spectrum import identify_lines  # noqa: E402
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402
from solarscribe.ui.spectrum_panel import SpectrumPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# @args: length - profile length; anchor - H-alpha pixel; dispersion - A/px
# @return: a flat continuum with the H-alpha window's three known absorption dips
def _profile(length=2000, anchor=500.0, dispersion=0.1) -> np.ndarray:
    x = np.arange(length, dtype=float)
    profile = np.full(length, 1000.0, dtype=float)
    for wavelength, depth in ((6562.81, 0.30), (6569.224, 0.15),
                              (6575.037, 0.12)):
        pixel = anchor + (wavelength - 6562.81) / dispersion
        profile -= 1000.0 * depth * np.exp(-0.5 * ((x - pixel) / 1.5) ** 2)
    return profile


# @args: none
# @return: the identification of the synthetic H-alpha window
def _result():
    return identify_lines(_profile(), 0.1, target_wavelength=6562.81)


# @args: profile - 1D profile; width - frame columns
# @return: a Frame-like object whose rows are the profile
def _frame_from_profile(profile: np.ndarray, width: int = 40):
    array = np.repeat(profile[:, None], width, axis=1).astype(np.uint16)

    class FakeFrame:
        pass

    frame = FakeFrame()
    frame.data = memoryview(array)
    frame.width = width
    frame.height = int(profile.size)
    frame.dtype = np.dtype(np.uint16)
    return frame


# @args: predicate - callable returning bool; timeout - seconds
# @return: True when the predicate became true, processing Qt events
def _wait_for(predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(predicate())


def _window(tmp_path):
    settings = store.default_settings()
    settings.values[("session", "session_dir")] = str(tmp_path / "sessions")
    session = Session(settings=settings, folder=tmp_path / "session", demo=False,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    window.resize(1280, 820)
    window.show()
    return window


def test_panel_lists_the_named_lines_sorted_by_row(qapp):
    panel = SpectrumPanel()
    panel.show_result(_result(), band_y=40, min_confidence=0.35)
    assert not panel.table.isHidden()
    assert panel.table.rowCount() == 3
    names = [panel.table.item(row, 0).text() for row in range(3)]
    assert names == ["H-alpha", "Fe I 6569.224", "Fe I 6575.037"]
    assert panel.table.item(0, 1).text() == "6562.81"
    rows = [int(panel.table.item(row, 2).text()) for row in range(3)]
    assert rows == sorted(rows)
    assert abs(rows[0] - 540) <= 1
    assert "H-alpha" in panel.anchor.text()
    assert "6562.81" in panel.anchor.text()
    assert "1.00" in panel.confidence.text()
    assert "lines named" in panel.state.text()


def test_low_confidence_hides_the_names(qapp):
    x = np.arange(2000, dtype=float)
    profile = np.full(2000, 1000.0, dtype=float)
    for pixel, depth in ((100.0, 0.10), (200.0, 0.10), (300.0, 0.10),
                         (400.0, 0.10), (500.0, 0.30), (700.0, 0.10)):
        profile -= 1000.0 * depth * np.exp(-0.5 * ((x - pixel) / 1.5) ** 2)
    result = identify_lines(profile, 0.1, anchor_pixel=500.0,
                            anchor_wavelength=6562.81, refine=False)
    assert result.reason_code == "low_confidence"
    panel = SpectrumPanel()
    panel.show_result(result, band_y=0, min_confidence=0.35)
    assert not panel.anchor.isHidden()
    assert panel.table.isHidden()
    assert "not trustworthy" in panel.state.text()
    assert "Confidence" in panel.confidence.text()


def test_no_dispersion_points_at_settings(qapp):
    panel = SpectrumPanel()
    panel.show_no_dispersion()
    assert "Settings" in panel.state.text()
    assert "dispersion" in panel.state.text()
    assert panel.table.isHidden()
    assert panel.anchor.isHidden()
    assert panel.confidence.isHidden()
    assert "Settings → Spectrum" in panel.hint.text()


def test_no_spectrum_state(qapp):
    panel = SpectrumPanel()
    panel.show_no_spectrum()
    assert "No spectrum" in panel.state.text()
    assert panel.table.isHidden()


def test_no_lines_and_no_match_are_honest(qapp):
    panel = SpectrumPanel()
    panel.show_reason("no_lines")
    assert "No absorption line" in panel.state.text()
    panel.show_reason("no_match", detected=5)
    assert "5" in panel.state.text()
    assert "Settings" in panel.state.text()


def test_window_toggle_shows_the_panel_and_names_the_frame(qapp, tmp_path):
    window = _window(tmp_path)
    try:
        check = window.findChild(QCheckBox, "identifyCheck")
        frame = window.findChild(QWidget, "spectrumFrame")
        assert check is not None and frame is not None
        assert not frame.isVisible()
        check.setChecked(True)
        assert frame.isVisible()
        # The default dispersion is 0: the panel says where to set it, rather
        # than pretending to identify.
        assert "Settings" in window.spectrum_panel.state.text()

        # With the dispersion set but no frame, the panel says so.
        window.session.set_value("spectrum", "dispersion_angstrom_px", 0.1)
        window._identify_now()
        assert "No spectrum" in window.spectrum_panel.state.text()

        # A synthetic frame with the H-alpha window and the dispersion setting.
        window.session.set_roi((0, 0, 40, 2000), (0, 0, 40, 2000))
        window.session.harness._last_frame = _frame_from_profile(_profile())
        window._identify_now()
        assert _wait_for(
            lambda: window.spectrum_panel.table.rowCount() == 3, timeout=5.0), \
            "the worker never filled the panel"
        assert window.spectrum_panel.table.item(0, 0).text() == "H-alpha"
        assert window.spectrum_panel.table.item(0, 1).text() == "6562.81"
        assert "Settings → Spectrum" in window.spectrum_panel.hint.text()
        check.setChecked(False)
        assert not frame.isVisible()
    finally:
        window.close()


def test_window_no_dispersion_state(qapp, tmp_path):
    window = _window(tmp_path)
    try:
        check = window.findChild(QCheckBox, "identifyCheck")
        check.setChecked(True)
        window.session.set_value("spectrum", "dispersion_angstrom_px", 0.0)
        window._refresh_spectrum_settings()
        assert "Settings" in window.spectrum_panel.state.text()
        assert window.spectrum_panel.table.isHidden()
    finally:
        window.close()
