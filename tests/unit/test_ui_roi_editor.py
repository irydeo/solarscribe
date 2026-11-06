############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui roi editor test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The ROI step is where a wrong rectangle costs a whole session, so its checks
# must speak with numbers and its sentences must say what the numbers mean
# (AGENTS.md, ADR-010). These tests use the real validator when capture/roi.py
# is present and pin the sentence for both contracts.

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QSpinBox  # noqa: E402

from solarscribe.capture.abc import RoiIssue, RoiWarning, Severity  # noqa: E402
from solarscribe.config import store  # noqa: E402
from solarscribe.devices.abc import RoiConstraints  # noqa: E402
from solarscribe.ui.live_viewer import LiveViewer  # noqa: E402
from solarscribe.ui.roi_editor import RoiEditor  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build(tmp_path, demo=False):
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=demo,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    viewer = LiveViewer()
    warning = QLabel()
    tilt = QLabel()
    rate = QLabel()
    scale = QLabel()
    preset = QComboBox()
    capture = tuple(QSpinBox() for _ in range(4))
    band = tuple(QSpinBox() for _ in range(4))
    for spin in capture + band:
        spin.setMaximum(20000)
    editor = RoiEditor(session, viewer)
    editor.bind(capture, band, warning, tilt, rate, preset, scale)
    return (session, viewer, editor, warning, tilt, rate, preset, capture, band,
            scale)


def test_default_reference_roi_is_scannable(qapp, tmp_path):
    session, viewer, editor, warning, *_ = _build(tmp_path)
    assert editor.warnings() == []
    assert "No problems" in warning.text()
    assert viewer.band() == session.roi.band


def test_tilt_height_is_an_error_with_the_arithmetic(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    capture[3].setValue(100)    # the band is 160 and the margin is 2
    editor.refresh_warnings()
    warnings = editor.warnings()
    assert any(item.issue is RoiIssue.TILT_HEIGHT for item in warnings)
    worst = next(item for item in warnings if item.issue is RoiIssue.TILT_HEIGHT)
    assert worst.severity is Severity.ERROR
    text = editor.warning_text(worst)
    assert "Cannot scan" in text
    assert "100" in text and "160" in text and "162" in text
    assert warning.property("state") == "error"


def test_band_clipping_says_which_edge_is_lost(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    band[2].setValue(4000)
    editor.refresh_warnings()
    warnings = editor.warnings()
    clipped = next(item for item in warnings if item.issue is RoiIssue.BAND_CLIPPED)
    text = editor.warning_text(clipped)
    assert "4000" in text and "3480" in text
    assert "clipped" in text
    assert clipped.severity is Severity.WARNING


def test_sdk_multiple_names_the_multiple(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    session.set_constraints(RoiConstraints(max_width=3480, max_height=248,
                                           width_multiple=8, height_multiple=2))
    editor.reload()
    capture[2].setValue(3481)
    editor.refresh_warnings()
    warnings = editor.warnings()
    multiple = next(item for item in warnings if item.issue is RoiIssue.SDK_MULTIPLE)
    text = editor.warning_text(multiple)
    assert "8" in text and "3481" in text
    assert "driver would reject" in text


def test_low_rate_sentence_has_both_numbers(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    item = RoiWarning(issue=RoiIssue.LOW_RATE, severity=Severity.WARNING,
                      args={"fps": 63.0, "target_fps": 120.0})
    text = editor.warning_text(item)
    assert "63" in text and "120" in text
    assert "Recommendation" in text


def test_apply_writes_the_rectangles_and_the_ini(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    capture[0].setValue(12)
    band[1].setValue(44)
    warnings = editor.apply()
    assert not any(item.severity is Severity.ERROR for item in warnings)
    assert session.roi.capture[0] == 12
    assert session.roi.band[1] == 44
    # The editor only updates the model; the window asks the session to send it
    # to the camera and save it. Without a camera the session still persists.
    assert session.apply_roi()
    saved = store.load_settings(tmp_path / "config.ini")
    assert saved.get("roi", "capture_x") == 12
    assert saved.get("roi", "band_y") == 44


def _start_with_frame(qapp, session):
    assert session.harness.start()
    deadline = time.monotonic() + 5.0
    while session.harness.last_frame() is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert session.harness.last_frame() is not None


def test_tilt_measurement_uses_the_real_maths_on_the_solar_simulator(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, preset, capture, band, _ = _build(
        tmp_path, demo=True)
    _start_with_frame(qapp, session)
    editor.measure_tilt()
    assert session.last_tilt() is not None
    assert "deg" in tilt.text() and "px" in tilt.text()
    assert "fps" in rate.text()
    session.harness.stop()


def test_tilt_measures_the_typed_band_without_losing_it(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, preset, capture, band, _ = _build(
        tmp_path, demo=True)
    _start_with_frame(qapp, session)
    band[1].setValue(60)             # typed, not applied
    editor.measure_tilt()
    assert band[1].value() == 60     # the reload did not throw the edit away
    assert session.roi.band[1] == 40  # the applied model is still the old band
    assert "deg" in tilt.text()
    session.harness.stop()


def test_rate_estimate_is_absent_without_an_engine(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, *_ = _build(tmp_path)
    assert "not estimated" in rate.text()
    assert "Not measured" in tilt.text()


def test_presets_come_from_the_profile(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, preset, capture, band, _ = _build(tmp_path)
    session.save_preset("wide")
    editor.reload_presets()
    names = [preset.itemText(index) for index in range(preset.count())]
    assert "wide" in names


def test_choosing_a_preset_loads_the_fields_but_not_the_camera(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, preset, capture, band, _ = _build(tmp_path)
    session.save_preset("wide", (0, 0, 3480, 300), (0, 60, 3480, 180))
    editor.reload_presets()
    index = preset.findText("wide")
    editor.preset_selected(index)
    assert capture[3].value() == 300
    assert band[1].value() == 60
    # The applied model is still the old rectangle; Apply is what sends it.
    assert session.roi.capture[3] == 248
    assert session.roi.band[1] == 40


def test_apply_refuses_an_invalid_roi(qapp, tmp_path):
    session, viewer, editor, warning, _, _, _, capture, band, _ = _build(tmp_path)
    capture[3].setValue(100)
    warnings = editor.apply()
    assert any(item.severity is Severity.ERROR for item in warnings)
    assert session.roi.capture[3] == 248       # the camera still has the old one
    assert "Cannot scan" in warning.text()


def test_pixel_scale_comes_from_the_profile_optics(qapp, tmp_path):
    session, viewer, editor, warning, tilt, rate, preset, capture, band, scale = _build(tmp_path)
    # 714 mm and 2 um give 0.578 arcsec per pixel; the label says so with units.
    assert "0.58" in scale.text()
    assert "arcsec per pixel" in scale.text()
