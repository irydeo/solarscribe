############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui main window test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The window is the contract with the observer: Designer structure, custom
# widgets swapped in, the status bar explaining every figure, and a rail that
# never gates. These tests build the real window offscreen and aim at those
# promises, not at pixel colours.

import os
import time

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QDockWidget, QLabel, QPushButton, QSpinBox,
    QStackedWidget, QToolButton, QWidget,
)

from solarscribe.config import store  # noqa: E402
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402
from solarscribe.ui.step_rail import StepRail  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def make_window(qapp, tmp_path):
    windows = []

    def make(demo=False, welcome=False, lat=40.0, lon=-3.0):
        settings = store.default_settings()
        settings.values[("observatory", "latitude_deg")] = lat
        settings.values[("observatory", "longitude_deg")] = lon
        settings.values[("session", "session_dir")] = str(tmp_path / "sessions")
        session = Session(settings=settings, folder=tmp_path / "session",
                          demo=demo, autosave=True,
                          settings_path=tmp_path / "config.ini",
                          profile_path=tmp_path / "profile.json")
        window = MainWindow(session, show_welcome=welcome)
        windows.append(window)
        return window

    yield make
    for window in windows:
        window.close()


def test_the_three_menus_exist_with_their_tools(qapp, make_window):
    window = make_window()
    assert window.menuBar() is not None
    titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert titles == ["File", "Tools", "Help"]
    for name in ("actionSettings", "actionSkyCalendar", "actionRoiManager",
                 "actionDiagnostics", "actionLogs",
                 "actionOpenSessionFolder", "actionQuit",
                 "actionQuickStart", "actionAbout",
                 "actionTelescopePanel", "actionCameraPanel",
                 "actionHealthPanel"):
        assert window._action(name) is not None, name
    # The visible session ceremony is gone (ADR-026): the data folder is still
    # one click away, but there is no "New session" or "Open session".
    assert window._action("actionNewSession") is None
    assert window._action("actionOpenSession") is None


def test_custom_widgets_are_swapped_into_their_placeholders(qapp, make_window):
    window = make_window()
    assert window.findChild(StepRail, "stepRailHost") is window.rail
    assert window.findChild(QLabel, "viewerHost") is None      # it is not a label
    assert window.viewer.objectName() == "viewerHost"
    assert window.histogram.objectName() == "histogramHost"
    assert window.scan_view.objectName() == "scanViewHost"
    assert window.recon.objectName() == "reconHost"
    assert window.rail.steps() == ("find_sun", "polar", "focus", "roi", "scan")
    # The spectrum magnifier was removed with ADR-026.
    assert not hasattr(window, "magnifier")
    assert window.findChild(QWidget, "magnifierHost") is None


def test_the_image_owns_the_window_and_the_strips(qapp, make_window):
    window = make_window()
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()
    # The image is the point: more than half of the window is video, the slim
    # rail is not a 64 px monster, and the right docks are capped hard.
    assert window.viewer.height() > window.height() * 0.5
    assert window.rail.button("find_sun").maximumHeight() <= 28
    assert window.findChild(QWidget, "sidePanel").maximumWidth() <= 320
    assert window.telescope_dock.maximumWidth() == 210
    assert window.camera_dock.maximumWidth() == 210
    # The histogram is open by default; the scan strip is folded until a scan.
    histogram = window.findChild(QToolButton, "histogramToggle")
    scan = window.findChild(QToolButton, "scanStripToggle")
    assert histogram is not None and scan is not None
    assert histogram.isChecked()
    assert window.findChild(QWidget, "histogramBody").isVisible()
    assert not window.findChild(QWidget, "scanBody").isVisible()
    histogram.setChecked(False)
    assert not window.findChild(QWidget, "histogramBody").isVisible()
    histogram.setChecked(True)
    assert window.findChild(QWidget, "histogramBody").isVisible()
    # The profile is visible at startup, with the active name.
    profile = window.findChild(QComboBox, "profileCombo")
    assert profile is not None and profile.currentText() == "default"
    assert window.findChild(QToolButton, "profileSaveButton") is not None
    assert window.findChild(QToolButton, "profileManageButton") is not None


def test_the_telescope_panel_collapses_and_comes_back(qapp, make_window):
    window = make_window()
    window.show()
    qapp.processEvents()
    action = window._action("actionTelescopePanel")
    dock = window.findChild(QDockWidget, "telescopeDock")
    assert action is not None and dock is not None
    assert action.isChecked() and dock.isVisible()
    action.setChecked(False)
    assert not dock.isVisible()
    action.setChecked(True)
    assert dock.isVisible()


class _BandFrame:
    def __init__(self, width=240, height=120, value=1200, saturated=False):
        array = np.full((height, width), value, dtype=np.uint16)
        if saturated:
            array[:20, :] = 65535
        self._array = array
        self.data = memoryview(array)
        self.width = width
        self.height = height
        self.dtype = np.dtype(np.uint16)
        self.roi = (0, 0, width, height)

    def cut_roi(self, roi):
        x, y, width, height = roi
        piece = np.ascontiguousarray(self._array[y:y + height, x:x + width])
        frame = _BandFrame()
        frame._array = piece
        frame.data = memoryview(piece)
        frame.width, frame.height = piece.shape[1], piece.shape[0]
        return frame


def test_the_histogram_reads_the_spectral_band_and_warns_about_saturation(
        qapp, make_window):
    window = make_window()
    window.session.set_roi(window.session.roi.capture, (0, 0, 240, 80))
    window._on_frame(_BandFrame(saturated=True))
    # The histogram is fed the cut band, not the 240 x 120 frame.
    assert window.histogram.frame_size() == (240, 80)
    assert window.histogram.saturation_fraction() > 0.1
    label = window.findChild(QLabel, "histogramSaturation")
    assert "clipped" in label.text()
    assert label.property("state") == "warning"


def test_status_bar_shows_the_figures_with_their_meaning(qapp, make_window):
    window = make_window()
    for label in (window.fps_status, window.dropped_status, window.camera_status,
                  window.mount_status, window.disk_status):
        assert label.text()
        assert label.toolTip(), f"{label.text()} has no explanation"
    assert "target" in window.fps_status.toolTip() or "budget" in window.fps_status.toolTip()
    assert "budget" in window.dropped_status.toolTip()


def test_free_navigation_from_the_rail_does_not_gate(qapp, make_window):
    window = make_window()
    window.rail.button("scan").click()
    assert window.session.current_step() == "scan"
    assert window.session.status_of("find_sun").value == "pending"
    # The scanning panel is really the one on screen (fifth card, index 4).
    pages = window.findChild(QStackedWidget, "sideStack")
    assert pages.currentIndex() == 4


def test_each_step_has_exactly_one_primary_action(qapp, make_window):
    window = make_window()
    for page_name in ("findPage", "polarPage", "focusPage", "roiPage",
                      "scanPage"):
        page = window.findChild(QWidget, page_name)
        primaries = [button for button in page.findChildren(QPushButton)
                     if button.property("primary")]
        assert len(primaries) == 1, f"{page_name} has {len(primaries)} primary actions"


def test_mode_is_the_row_count_and_persists(qapp, make_window):
    window = make_window()
    mode = window.findChild(QComboBox, "planModeCombo")
    rows = window.findChild(QSpinBox, "planRowsSpin")
    mode.setCurrentIndex(1)          # mosaic
    assert rows.value() >= 2
    assert window.session.value("scan", "rows") >= 2
    mode.setCurrentIndex(0)          # simple
    assert rows.value() == 1
    assert window.session.value("scan", "rows") == 1


def test_roi_error_disables_the_scan_action_not_the_step(qapp, make_window):
    window = make_window()
    window.select_step("roi")
    height = window.findChild(QSpinBox, "capH")
    height.setValue(100)
    scan = window.findChild(QPushButton, "scanPrimaryButton")
    assert not scan.isEnabled()
    assert "cannot be scanned" in scan.toolTip()
    # The step is still navigable; only the action is gated, and the warning
    # text says what to change.
    window.select_step("scan")
    assert window.session.current_step() == "scan"
    window.select_step("roi")
    assert height.value() == 100
    warning = window.findChild(QLabel, "roiWarnings")
    assert "Cannot scan" in warning.text()
    assert "100" in warning.text() and "160" in warning.text()


def test_valid_roi_can_be_applied_and_completes_the_step(qapp, make_window):
    window = make_window(demo=True)
    window.select_step("roi")
    window.apply_roi()
    assert window.session.status_of("roi").value == "done"
    assert (window.session.folder / "session_state.json").is_file()
    assert (window.session.settings_file()).is_file()
    saved = store.load_settings(window.session.settings_file())
    assert saved.get("roi", "capture_width") == 3480


def test_close_saves_the_step_state(qapp, make_window):
    window = make_window()
    window.session.complete_step("find_sun", dec_error_arcsec=0.3)
    state_file = window.session.folder / "session_state.json"
    window.close()
    assert state_file.is_file()
    restored = store.load_session_state(state_file)
    assert restored.steps["find_sun"].status.value == "done"


def test_recommendation_is_an_invitation_not_an_order(qapp, make_window):
    window = make_window()
    label = window.findChild(QLabel, "recommendationLabel")
    assert "Next: Find the Sun" in label.text()
    assert "Any step is open" in label.text()


def test_welcome_banner_answers_and_saves_the_location(qapp, make_window):
    window = make_window(welcome=True)
    assert not window.welcome.isHidden()
    window.welcome.set_location(51.5, -0.12)
    save = window.findChild(QPushButton, "welcomeSaveButton")
    save.click()
    assert window.welcome.isHidden()
    assert window.session.value("observatory", "latitude_deg") == pytest.approx(51.5)
    assert window.session.value("observatory", "longitude_deg") == pytest.approx(-0.12)


def test_tool_dialogs_open_off_the_gui_thread(qapp, make_window):
    window = make_window()
    window.open_logs()
    window.open_sky_calendar()
    window.open_roi_manager()
    assert window._logs_dialog.isVisible()
    assert window._calendar_dialog.isVisible()
    window._logs_dialog.close()
    window._calendar_dialog.close()


def test_new_session_resets_the_steps_and_changes_the_folder(qapp, make_window):
    window = make_window()
    old_folder = window.session.folder
    window.session.complete_step("roi")
    window.new_session()
    assert window.session.status_of("roi").value == "pending"
    assert window.session.folder != old_folder
    assert window.session.folder.is_dir()


def test_reopen_step_is_offered_only_on_a_completed_step(qapp, make_window):
    window = make_window()
    button = window.findChild(QPushButton, "reopenStepButton")
    window.select_step("roi")
    assert button.isHidden()
    window.session.complete_step("roi", tilt_deg=0.4)
    window.select_step("roi")
    assert not button.isHidden()
    button.click()
    assert window.session.status_of("roi").value == "current"
    assert button.isHidden()
    # The saved number survives the reopen, which is the point of the action.
    assert window.session.step_state("roi").metrics["tilt_deg"] == pytest.approx(0.4)


def test_diagnostics_report_is_readable(qapp, make_window):
    window = make_window()
    text = window._diagnostics_text()
    assert "SolarScribe" in text
    assert "PySide6" in text
    assert "ROI capture" in text
    assert "Tilt" in text


def test_find_button_wires_the_device_layer_simulator(qapp, make_window):
    window = make_window(demo=True)
    refresh = window.findChild(QPushButton, "mountRefreshButton")
    refresh.click()
    mount = window.telescope.mount()
    assert mount is not None
    assert type(mount).__name__ == "SimMount"
    window.telescope.connect_button.click()
    assert mount.is_connected()
    # The harness follows the same mount, so the scan and the panel agree.
    assert window.session.harness.mount is mount


def test_no_demo_mode_can_still_use_a_discovered_mount(qapp, make_window):
    window = make_window(demo=False)
    window.findChild(QPushButton, "mountRefreshButton").click()
    window.telescope.connect_button.click()
    window._update_status_devices()
    assert "Simulator" in window.mount_status.text()
    # The camera side is honestly disconnected, not a pretend stream.
    assert "not connected" in window.camera_status.text()


def test_no_demo_camera_panel_opens_the_simulator(qapp, make_window, tmp_path):
    window = make_window(demo=False)
    panel = window.camera_panel
    panel.refresh_sync()
    assert panel.combo.count() >= 1
    for index in range(panel.combo.count()):
        data = panel.combo.itemData(index)
        if getattr(data, "backend", "") == "sim":
            panel.combo.setCurrentIndex(index)
            break
    panel._open()
    assert window.session.has_camera()
    assert window.session.is_simulated()
    # The frame arrives through the real CaptureEngine and the scene camera.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if window.session.harness.last_frame() is not None:
            break
    assert window.session.harness.last_frame() is not None
    window._camera_close()
    assert not window.session.has_camera()
