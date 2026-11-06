############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui usability test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The usability task script, executed. It is the G4 gate of AGENTS.md: a
# newcomer, on the simulator, with no hardware, has to finish a whole session
# inside the budgets below. The assertions are the tasks; the printed timings
# are the evidence, and every friction point found is written in
# solarscribe/ui/USABILITY.md, not hidden here.
#
# The budgets are deliberately generous (the simulator's polar and scan run on
# timers), but they still fail if a task needs a dialog the user cannot find or
# a step that refuses to open.

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QSpinBox, QToolButton, QWidget,
)

from solarscribe.config import store  # noqa: E402
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402

# Seconds a newcomer should need for each task on the simulator.
BUDGETS = {
    "camera": 10.0,
    "welcome": 10.0,
    "free_navigation": 5.0,
    "find_sun": 30.0,
    "polar": 30.0,
    "focus": 30.0,
    "roi": 25.0,
    "reopen": 10.0,
    "scan": 90.0,
}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# @args: predicate - callable returning bool; timeout - seconds
# @return: True when the predicate became true. Processes events, because the
#          simulator advances on Qt timers
def _wait_for(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(predicate())


def test_a_newcomer_can_finish_a_session_on_the_simulator(qapp, tmp_path):
    settings = store.default_settings()
    settings.values[("session", "session_dir")] = str(tmp_path / "sessions")
    session = Session(settings=settings, folder=tmp_path / "session", demo=True,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=True)
    window.show()
    window.start_capture()
    timings = {}

    try:
        # --- camera discovery and open ---------------------------------------
        start = time.monotonic()
        panel = window.camera_panel
        panel.find_button.click()
        assert _wait_for(lambda: panel.combo.count() > 0, timeout=15.0), \
            "camera discovery found nothing"
        sim_index = 0
        for index in range(panel.combo.count()):
            data = panel.combo.itemData(index)
            if getattr(data, "backend", "") == "sim":
                sim_index = index
                break
        panel.combo.setCurrentIndex(sim_index)
        panel.open_button.click()
        assert session.has_camera()
        assert session.camera_info() is not None
        assert session.camera_info().backend == "sim"
        assert session.is_simulated()
        assert _wait_for(lambda: session.harness.last_frame() is not None,
                         timeout=10.0), "the opened camera produced no frame"
        timings["camera"] = time.monotonic() - start

        # --- free navigation -------------------------------------------------
        start = time.monotonic()
        # Jumping to the last step from a standing start is allowed and does not
        # open a dialog or demand the earlier steps.
        window.rail.button("scan").click()
        assert session.current_step() == "scan"
        window.rail.button("find_sun").click()
        assert session.current_step() == "find_sun"
        timings["free_navigation"] = time.monotonic() - start

        # --- welcome ---------------------------------------------------------
        start = time.monotonic()
        assert not window.welcome.isHidden()
        window.welcome.set_location(40.0, -3.0)
        window.findChild(QPushButton, "welcomeSaveButton").click()
        assert window.welcome.isHidden()
        assert session.value("observatory", "latitude_deg") == pytest.approx(40.0)
        timings["welcome"] = time.monotonic() - start

        # --- find the Sun ----------------------------------------------------
        start = time.monotonic()
        if not window.telescope.mount().is_connected():
            window.telescope.connect_button.click()
        assert window.telescope.mount().is_connected()
        window.findChild(QPushButton, "findPrimaryButton").click()
        # The real SunCenteringImpl runs in a worker; wait for the step, not for
        # a fixed sleep.
        assert _wait_for(
            lambda: session.status_of("find_sun").value == "done", timeout=40.0), \
            "the real centring never finished"
        sun_state = window.findChild(QLabel, "sunStateValue")
        assert "On the slit" in sun_state.text()
        assert "arcsec" in window.findChild(QLabel, "decErrorValue").text()
        timings["find_sun"] = time.monotonic() - start

        # --- polar alignment -------------------------------------------------
        start = time.monotonic()
        window.rail.button("polar").click()
        window.findChild(QPushButton, "polarStartButton").click()
        assert _wait_for(lambda: window.findChild(
            QPushButton, "polarSecondButton").isEnabled(), timeout=12.0), \
            "the first polar measurement never finished"
        window.findChild(QPushButton, "polarSecondButton").click()
        assert _wait_for(
            lambda: session.status_of("polar").value == "done", timeout=12.0), \
            "the confirmation measurement never finished"
        assert "arcmin" in window.findChild(QLabel, "polarAzValue").text()
        timings["polar"] = time.monotonic() - start

        # --- focus: three focusers and the slit tilt ------------------------
        start = time.monotonic()
        window.rail.button("focus").click()
        # The three focusers are live from the capture frames; the labels carry
        # the current value and the running best.
        assert _wait_for(
            lambda: "best" in window.findChild(
                QLabel, "lineContrastValue").text(), timeout=8.0), \
            "the focus metrics never received a frame"
        for name in ("lineContrastValue", "lineGradientValue",
                     "edgeSharpValue", "edgeFlatValue", "detailContrastValue",
                     "detailGradientValue", "detailCountValue"):
            text = window.findChild(QLabel, name).text()
            assert "Not measured" not in text, f"{name} stayed empty"
            assert "best" in text, f"{name} has no best figure"
        window.findChild(QPushButton, "focusMeasureButton").click()
        assert _wait_for(
            lambda: session.status_of("focus").value == "done", timeout=8.0), \
            "the slit tilt never reached the Dec axis"
        tilt_text = window.findChild(QLabel, "focusTiltValue").text()
        assert "deg" in tilt_text and "px drift" in tilt_text
        assert "ROI must be at least" in window.findChild(
            QLabel, "focusTiltHeight").text()
        timings["focus"] = time.monotonic() - start

        # --- ROI -------------------------------------------------------------
        start = time.monotonic()
        window.rail.button("roi").click()
        assert _wait_for(lambda: session.harness.last_frame() is not None,
                         timeout=6.0), "the simulator never produced a frame"
        window.findChild(QPushButton, "roiMeasureButton").click()
        assert _wait_for(lambda: session.last_tilt() is not None, timeout=6.0)
        assert "deg" in window.findChild(QLabel, "tiltValue").text()
        window.findChild(QPushButton, "roiApplyButton").click()
        assert session.status_of("roi").value == "done"
        assert "No problems" in window.findChild(QLabel, "roiWarnings").text()
        timings["roi"] = time.monotonic() - start

        # --- scanning --------------------------------------------------------
        start = time.monotonic()
        window.rail.button("scan").click()
        window.findChild(QPushButton, "prepareButton").click()
        assert _wait_for(lambda: "Ready" in window.findChild(
            QLabel, "scanStatusValue").text(), timeout=8.0), \
            "the preparation never reported ready"
        window.findChild(QPushButton, "scanPrimaryButton").click()
        # While a scan runs the progress strip is open and cannot be folded
        # away; the histogram stays visible too.
        assert window.findChild(QWidget, "scanBody").isVisible()
        assert not window.findChild(QToolButton, "scanStripToggle").isEnabled()
        assert window.findChild(QWidget, "histogramBody").isVisible()
        assert _wait_for(
            lambda: session.status_of("scan").value == "done", timeout=90.0), \
            "the scan never finished"
        result = window.findChild(QLabel, "scanResultValue").text()
        assert "frames" in result
        assert window.scan_view.percentage() == 100
        assert window.recon.has_image(), "the quick recon stayed empty"
        assert "Quick recon" in window.findChild(
            QLabel, "reconMessage").text()
        timings["scan"] = time.monotonic() - start

        # --- the friction checks that matter ---------------------------------
        for step in ("find_sun", "polar", "focus", "roi", "scan"):
            assert session.status_of(step).value == "done"
        assert "All five steps are done" in window.findChild(
            QLabel, "recommendationLabel").text()

        # Every figure on the status bar says what it means.
        for label in (window.fps_status, window.dropped_status,
                      window.camera_status, window.mount_status,
                      window.disk_status):
            assert label.toolTip()

        # An impossible ROI is refused in words, with the arithmetic, and the
        # step still opens (only the action is gated).
        window.rail.button("roi").click()
        window.findChild(QSpinBox, "capH").setValue(100)
        warning = window.findChild(QLabel, "roiWarnings").text()
        assert "Cannot scan" in warning
        assert "100" in warning and "160" in warning
        assert not window.findChild(QPushButton, "scanPrimaryButton").isEnabled()
        window.rail.button("scan").click()
        assert session.current_step() == "scan"
        window.rail.button("roi").click()
        window.findChild(QSpinBox, "capH").setValue(248)
        # A ROI edit invalidates the prepared plan: Start stays off until Prepare,
        # with the tooltip saying so. That is a prerequisite, not a step gate.
        assert not window.findChild(QPushButton, "scanPrimaryButton").isEnabled()
        assert "Prepare" in window.findChild(QPushButton, "scanPrimaryButton").toolTip()

        # --- reopen a completed step -----------------------------------------
        start = time.monotonic()
        window.rail.button("roi").click()
        reopen = window.findChild(QPushButton, "reopenStepButton")
        assert not reopen.isHidden()
        reopen.click()
        assert session.status_of("roi").value == "current"
        assert session.step_state("roi").metrics["tilt_deg"] >= 0.0
        timings["reopen"] = time.monotonic() - start

        # The state survived without a Save click: silent autosave (ADR-011).
        assert (session.folder / "session_state.json").is_file()
    finally:
        window.close()

    print("usability timings (s):")
    for name, seconds in timings.items():
        print(f"  {name:16s} {seconds:6.2f}  budget {BUDGETS[name]:5.1f}")
        assert seconds <= BUDGETS[name], (
            f"{name} took {seconds:.1f} s, above the {BUDGETS[name]:.1f} s "
            f"budget: a newcomer is fighting the interface")
    print(f"  total            {sum(timings.values()):6.2f}")


def test_the_image_owns_the_window_and_the_panels_fold(qapp, tmp_path):
    # ADR-026: the image is the point. A newcomer must find more than half of
    # the window given to the video, a slim rail, and a telescope panel that
    # folds away and comes back from Tools, Panels.
    start = time.monotonic()
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=True,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()
    try:
        assert not hasattr(window, "magnifier")
        assert window.viewer.height() > window.height() * 0.5
        assert window.rail.button("find_sun").maximumHeight() <= 28
        assert window.findChild(QWidget, "sidePanel").maximumWidth() <= 320
        assert window.telescope_dock.maximumWidth() == 210
        assert window.findChild(QWidget, "histogramBody").isVisible()
        assert not window.findChild(QWidget, "scanBody").isVisible()
        action = window._action("actionTelescopePanel")
        assert action.isChecked()
        action.setChecked(False)
        assert not window.findChild(QWidget, "telescopeDock").isVisible()
        action.setChecked(True)
        assert window.findChild(QWidget, "telescopeDock").isVisible()
        # The visible session ceremony is gone; the data folder is still there.
        assert window._action("actionNewSession") is None
        assert window._action("actionOpenSession") is None
        assert window._action("actionOpenSessionFolder") is not None
        assert time.monotonic() - start <= 10.0
    finally:
        window.close()


def test_the_histogram_is_a_foldable_strip_over_the_band(qapp, tmp_path):
    # The UFE-style histogram: open by default, compact, computed on the
    # spectral band, and the handles move the stretch with a click.
    start = time.monotonic()
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=True,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    window.resize(1280, 820)
    window.show()
    window.start_capture()
    try:
        toggle = window.findChild(QToolButton, "histogramToggle")
        assert toggle is not None
        assert window.findChild(QWidget, "histogramBody").isVisible()
        toggle.setChecked(False)
        qapp.processEvents()
        assert not window.findChild(QWidget, "histogramBody").isVisible()
        toggle.setChecked(True)
        qapp.processEvents()
        assert window.findChild(QWidget, "histogramBody").isVisible()
        assert _wait_for(lambda: window.histogram.peaks() > 0, timeout=10.0), \
            "the histogram never received a band frame"
        band = session.roi.band
        assert window.histogram.frame_size() == (band[2], band[3])
        before = window.histogram.stretch()
        # A click near the right edge grabs the white handle.
        point = QPoint(max(2, window.histogram.width() - 8),
                       max(2, window.histogram.height() // 2))
        QTest.mouseClick(window.histogram, Qt.MouseButton.LeftButton, pos=point)
        qapp.processEvents()
        after = window.histogram.stretch()
        assert after[1] > before[1], "the white handle did not move"
        assert after[0] < after[1], "the handles crossed"
        # The saturation sentence is present, with its meaning in the tooltip.
        saturation = window.findChild(QLabel, "histogramSaturation")
        assert saturation.text()
        assert saturation.toolTip()
        assert time.monotonic() - start <= 20.0
    finally:
        window.close()
