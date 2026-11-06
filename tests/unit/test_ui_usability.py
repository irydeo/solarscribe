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

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QSpinBox,
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
        for step in ("find_sun", "polar", "roi", "scan"):
            assert session.status_of(step).value == "done"
        assert "All four steps are done" in window.findChild(
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
