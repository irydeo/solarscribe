############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui main window module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The window of DESIGN.md 9, ADR-009, ADR-011 and ADR-026: a slim step indicator
# on top, the active step's compact card on the left, the video taking the centre,
# the telescope and the stream health in collapsible docks on the right, a folded
# histogram and scan strip under the video, and the status bar at the bottom.
#
# The window is deliberately thin. It paints what the Session holds, forwards
# clicks to the Session or to the simulator, and opens the dialogs. It owns no
# state of its own except the widgets: no step logic, no ROI arithmetic, no
# scan maths. That is the rule of ARCHITECTURE 2.4, and it is what lets the
# same window work with the simulator today and with the real engines later.
#
# Three choices a user feels:
#   - Every step's controls are present; the rail changes the panel, it does
#     not unlock it (ADR-011). A pending step is clickable.
#   - One prominent action per step (primary=true). The rest are secondary and
#     share a quieter look, so "what do I do now?" has one answer.
#   - The status bar always carries the numbers that say whether the take is
#     safe: rate against budget, drops against budget, the devices and the
#     free disk. Each has a tooltip with its meaning (AGENTS.md).
#
# ADR-026 removed the visible session ceremony and the spectrum magnifier: the
# session folder is still there for the SER and the logs, but the observer opens
# a camera, points at the Sun, sets the ROI and scans. It also made Focus a
# first-class step: the three focusers and the slit tilt are measured live from
# the capture frames, and the UI only explains the figures.

from __future__ import annotations

import math
import platform
import time
from pathlib import Path

import PySide6
from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import solarscribe
from solarscribe.capture.abc import StreamCounters
from solarscribe.capture.roi import TILT_MARGIN_PX
from solarscribe.shg.ephemeris import solar_position_now
from solarscribe.shg.focus import FocusWatcher, compute_metrics, frame_grid
from solarscribe.shg.geometry import pixel_scale_arcsec_px
from solarscribe.shg.spectrum import dispersion_profile
from solarscribe.config import paths, store
from solarscribe.config.schema import SESSION_STEPS, StepStatus
from solarscribe.devices.manager import DeviceManagerImpl
from solarscribe.devices.native import native_camera_backends
from solarscribe.devices.sim.backend import SimCameraBackend
from solarscribe.devices.sim.frame import SolarPattern

from .camera_panel import CameraPanel
from .health_panel import HealthPanel
from .histogram import HistogramWidget
from .live_viewer import LiveViewer
from .logs_viewer import LogsViewer
from .roi_editor import RoiEditor
from .profile_manager import ProfileManagerDialog
from .profiles import ProfileAdapter, ProfileStoreError
from .roi_manager import RoiManagerDialog
from .scan_view import ScanVisualisation
from .session import Session
from .sky_calendar import SkyCalendarDialog
from .spectrum_panel import LineIdentifierWorker, SpectrumPanel
from .step_rail import StepRail
from .sun_disc import QuickRecon
from .telescope_panel import TelescopePanel
from .engines import SIM_FPS
from .theme import sun_icon
from .ui_loader import load_ui, replace_widget
from .welcome import WelcomeBanner

__all__ = ["MainWindow"]

# Focus step (ADR-026). The three focusers are a judgement; the tilt is the
# objective part. 0.5 deg is the point where the drift across the reference
# 3480 px band is about 30 px, already too much to ignore. The edge is trusted
# only if the fitted line's residual is small, the same rule the ROI editor uses.
FOCUS_TILT_TOLERANCE_DEG = 0.5
FOCUS_EDGE_STD_MAX_PX = 1.5
FOCUS_REFRESH_S = 0.25

# The line identification is a reference, not a measurement: twice a second is
# enough to follow a focuser or a grating change, and the profile is copied on
# the GUI thread while the match runs in the worker (never on the capture path).
IDENTIFY_REFRESH_MS = 500

class MainWindow(QMainWindow):
    # @args: session - the live session, or None for a demo one;
    #        show_welcome - force the banner, or None to read the saved choice
    # @return: the window, fully wired and showing the first step
    def __init__(self, session: Session | None = None,
                 show_welcome: bool | None = None, parent=None) -> None:
        super().__init__(parent)
        self.session = session if session is not None else Session(demo=True)
        self._shell = load_ui("main_window")
        self._adopt_shell()
        self.setWindowIcon(sun_icon(64))
        self._last_counters: StreamCounters | None = None
        self._logs_dialog: LogsViewer | None = None
        self._calendar_dialog: SkyCalendarDialog | None = None
        self._roi_manager_dialog: RoiManagerDialog | None = None
        self._profile_manager_dialog: ProfileManagerDialog | None = None
        # The active named profile is loaded before the solar pattern is built:
        # its optics set the slit scale of the simulator and of the engine.
        # profiles.json is the sibling of the old profile.json (ADR-027), which
        # in production is exactly paths.profiles_path().
        profile_file = self.session.profile_file()
        profiles_path = (Path(profile_file).with_name("profiles.json")
                         if profile_file is not None else paths.profiles_path())
        self._profiles = ProfileAdapter(
            profiles_path=profiles_path,
            legacy_path=profile_file,
            fallback_profile=self.session.profile)
        self._active_profile = self._profiles.active()
        if self._active_profile:
            try:
                active = self._profiles.load(self._active_profile)
                if active is not None:
                    self.session.set_profile(active)
                else:
                    # A hand-edited active name that does not exist: show no
                    # active profile instead of saving back to a ghost.
                    self._active_profile = ""
            except (ProfileStoreError, OSError):
                self._active_profile = ""
        # The ROI preset save goes through the named store when ADR-027 is
        # available; the fallback keeps the old single file.
        if self._profiles.available:
            self.session.profile_saver = self._persist_active_profile
        self._focus_watcher = FocusWatcher()
        self._last_focus_s = 0.0
        self._identify_generation = 0
        self._busy_scan = False
        self._busy_center = False
        self._prepared = False
        self._plan = None
        self._cycle = 0
        self._cycle_total = 0
        # Two managers on purpose: the camera panel discovers in a worker
        # thread while the telescope panel may discover in the GUI thread, and
        # the manager caches its probes. One manager shared across threads would
        # race on that cache.
        sun = solar_position_now(
            float(self.session.value("observatory", "latitude_deg")),
            float(self.session.value("observatory", "longitude_deg")))
        scale = pixel_scale_arcsec_px(
            self.session.profile.telescope.focal_length_mm,
            self.session.profile.camera.pixel_size_um)
        solar = SolarPattern(
            sun_ra_hours=sun.ra_hours,
            sun_dec_deg=sun.dec_deg,
            solar_diameter_arcsec=sun.diameter_arcsec,
            slit_arcsec_px=scale,
            band_y=int(self.session.roi.band[1]),
            band_height=int(self.session.roi.band[3]),
        )
        self.device_manager = DeviceManagerImpl(
            camera_backends=native_camera_backends() + [
                SimCameraBackend(width=3480, height=248, fps=SIM_FPS,
                                 pattern="solar", solar=solar)],
            mount_backends=None,
        )
        self.camera_manager = DeviceManagerImpl(
            camera_backends=native_camera_backends() + [
                SimCameraBackend(width=3480, height=248, fps=SIM_FPS,
                                 pattern="solar", solar=solar)],
            mount_backends=[],
        )

        self._build_custom_widgets(show_welcome)
        self._build_status_bar()
        self._wire_menus()
        self._wire_steps()
        self._wire_controls()
        self._wire_profile()
        self._wire_session()
        self._wire_harness()
        self._initial_fill()

        self._display_timer = QTimer(self)
        self._display_timer.setInterval(30)
        self._display_timer.timeout.connect(self._pump_display)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(1000)
        self._health_timer.timeout.connect(self._update_health)
        self._health_timer.start()
        # The identification worker is created once and kept idle until the
        # observer checks "Identify lines"; its timer drops the rate to 2 Hz.
        self._identify_worker = LineIdentifierWorker(self)
        self._identify_worker.resultReady.connect(self._on_identification)
        self._identify_worker.start()
        self._identify_timer = QTimer(self)
        self._identify_timer.setInterval(IDENTIFY_REFRESH_MS)
        self._identify_timer.timeout.connect(self._identify_now)

        self._refresh_from_session()
        self._update_recommendation()
        self._update_histogram_saturation()
        self.resize(1280, 820)

    # --------------------------------------------------------------- shell

    # @args: none. Moves the Designer shell into this window
    def _adopt_shell(self) -> None:
        shell = self._shell
        self.setWindowTitle(shell.windowTitle())
        central = shell.centralWidget()
        if central is not None:
            self.setCentralWidget(central)
        menu = shell.menuBar()
        if menu is not None:
            self.setMenuBar(menu)
        status = shell.statusBar()
        if status is not None:
            self.setStatusBar(status)
        self.telescope_dock = shell.findChild(QDockWidget, "telescopeDock")
        self.camera_dock = shell.findChild(QDockWidget, "cameraDock")
        self.health_dock = shell.findChild(QDockWidget, "healthDock")
        self._docks = [dock for dock in (self.telescope_dock, self.camera_dock,
                                         self.health_dock) if dock is not None]
        for dock in self._docks:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        if self.camera_dock is not None and self.health_dock is not None:
            # Camera and health share the lower tab: the camera is chosen once
            # per session, the health panel is watched continuously, so neither
            # may push the telescope out of the column.
            self.tabifyDockWidget(self.camera_dock, self.health_dock)
            self.camera_dock.raise_()
        # The right band is capped hard: the image is the point. 210 px holds
        # the compact telescope, camera and health content, and the spectrum
        # panel (when shown) stays at 220 px inside the video row. The cap is
        # what stops a maximised window from giving the docks the extra width.
        for dock in self._docks:
            dock.setMaximumWidth(210)
        if self.telescope_dock is not None:
            self.resizeDocks([self.telescope_dock], [210],
                             Qt.Orientation.Horizontal)
        # The shell keeps the QAction objects alive; the window is hidden and
        # never shown, so it costs nothing and its actions stay reachable.
        shell.hide()

    # @args: name - the object name of a widget in the Designer file
    # @return: the widget, or None
    def _w(self, name: str) -> QWidget | None:
        return self.findChild(QWidget, name)

    # @args: name - the object name of an action in the Designer file
    # @return: the action, or None
    def _action(self, name: str) -> QAction | None:
        return self._shell.findChild(QAction, name)

    # -------------------------------------------------------------- widgets

    # @args: show_welcome - True/False, or None to consult the saved preference
    def _build_custom_widgets(self, show_welcome: bool | None) -> None:
        self.viewer = replace_widget(self, "viewerHost", LiveViewer(self))
        self.viewer.setAccessibleName(self.tr("Live video of the spectrum"))

        self.histogram = replace_widget(self, "histogramHost",
                                        HistogramWidget(self))
        self.scan_view = replace_widget(self, "scanViewHost",
                                        ScanVisualisation(self))
        self.recon = replace_widget(self, "reconHost", QuickRecon(self))
        self.spectrum_panel = replace_widget(self, "spectrumHost",
                                             SpectrumPanel(self))
        self.spectrum_frame = self._w("spectrumFrame")
        self.identify_check = self.findChild(QCheckBox, "identifyCheck")
        self.viewer.setToolTip(self.tr(
            "Scroll to zoom; drag the ROI band to move it. The histogram "
            "handles set the stretch."))

        mount = self.session.demo_mount()
        mount_name = self.tr("Simulator") if mount is not None else ""
        self.telescope = replace_widget(
            self, "telescopeHost",
            TelescopePanel(self, mount=mount, mount_name=mount_name,
                           sun_provider=self.session.sun_position))
        self.telescope.set_mount_factory(self._discover_mount)
        self.health = replace_widget(self, "healthHost", HealthPanel(self))
        self.camera_panel = replace_widget(
            self, "cameraHost", CameraPanel(self.camera_manager, self))
        self.camera_panel.cameraChosen.connect(self._camera_chosen)
        self.camera_panel.closeRequested.connect(self._camera_close)

        # The position belongs to Settings and to a first-run assistant, not to
        # the permanent chrome: the old inline block stole 150 px of image and
        # stretched with the window. The assistant is a non-modal dialog now, so
        # maximising the main window cannot make it bigger.
        self.welcome = WelcomeBanner(self)
        self.welcome_dialog = QDialog(self)
        self.welcome_dialog.setWindowTitle(self.tr("Welcome to SolarScribe"))
        self.welcome_dialog.setModal(False)
        welcome_layout = QVBoxLayout(self.welcome_dialog)
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.addWidget(self.welcome)
        self.welcome_dialog.resize(640, 300)
        self._fill_welcome()
        if show_welcome is None:
            show_welcome = self._welcome_wanted()
        if show_welcome:
            self.welcome_dialog.show()
            self.welcome_dialog.raise_()

        self.rail = replace_widget(self, "stepRailHost", StepRail(self))
        # The placeholder's maximum height does not travel with replace_widget;
        # pin the real rail to 28 px so the image, not the indicator, gets the
        # extra height when the window grows (ADR-026).
        self.rail.setFixedHeight(28)
        stack = self.findChild(QStackedWidget, "sideStack")
        if stack is not None:
            stack.setCurrentIndex(0)
        splitter = self.findChild(QWidget, "mainSplitter")
        if splitter is not None and hasattr(splitter, "setSizes"):
            splitter.setSizes([290, 990])

        self.roi_editor = RoiEditor(self.session, self.viewer, self)
        self.roi_editor.bind(
            capture=(self._w("capX"), self._w("capY"), self._w("capW"), self._w("capH")),
            band=(self._w("bandX"), self._w("bandY"), self._w("bandW"), self._w("bandH")),
            warning_label=self._w("roiWarnings"),
            tilt_label=self._w("tiltValue"),
            rate_label=self._w("roiRateValue"),
            preset_combo=self._w("roiPresetCombo"),
            scale_label=self._w("roiScaleValue"),
        )
        self.viewer.bandEdited.connect(self.roi_editor.band_dragged)
        self.roi_editor.changed.connect(self._roi_edited)
        preset = self._w("roiPresetCombo")
        if isinstance(preset, QComboBox):
            preset.currentIndexChanged.connect(self.roi_editor.preset_selected)
        self._wrap_side_panel()

    # @args: none. Puts the step pages inside a scroll area
    def _wrap_side_panel(self) -> None:
        # A 13 inch laptop cannot show the ROI step's eight fields plus the
        # warnings at once. The recommendation stays fixed above; the page
        # scrolls, so no control is ever unreachable.
        side = self.findChild(QWidget, "sidePanel")
        stack = self.findChild(QStackedWidget, "sideStack")
        if side is None or stack is None or side.layout() is None:
            return
        layout = side.layout()
        layout.removeWidget(stack)
        scroll = QScrollArea(side)
        scroll.setObjectName("sideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # The card is sized for its controls; a horizontal bar would mean a
        # field is cut off, so it is banned and the layouts wrap instead.
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(stack)
        layout.addWidget(scroll)

    # @args: none. Fills the welcome banner with the current facts
    def _fill_welcome(self) -> None:
        self.welcome.set_location(
            float(self.session.value("observatory", "latitude_deg")),
            float(self.session.value("observatory", "longitude_deg")),
        )
        info = self.session.camera_info()
        if self.session.is_simulated():
            camera = self.tr("Simulator (no hardware)")
        elif info is not None:
            camera = getattr(info, "model", self.tr("connected"))
        else:
            camera = self.tr("not connected")
        mount = self.tr("Simulator (no hardware)") if self.session.demo_mount() \
            else self.tr("not connected")
        self.welcome.set_device_status(camera, mount)
        self.welcome.answered.connect(self._welcome_answered)
        self.welcome.dismissed.connect(self._welcome_dismissed)

    # @args: none
    # @return: whether the banner should appear: not dismissed before, or the
    #          observatory position is still zero
    def _welcome_wanted(self) -> bool:
        settings = QSettings("SolarScribe", "SolarScribe")
        if settings.value("welcome_done", False, type=bool):
            return False
        lat = float(self.session.value("observatory", "latitude_deg"))
        lon = float(self.session.value("observatory", "longitude_deg"))
        return lat == 0.0 and lon == 0.0

    # @args: lat, lon, dont_ask - the welcome answer
    def _welcome_answered(self, lat: float, lon: float, dont_ask: bool) -> None:
        self.session.set_value("observatory", "latitude_deg", float(lat))
        self.session.set_value("observatory", "longitude_deg", float(lon))
        if self.session.harness is not None:
            self.session.harness.latitude_deg = float(lat)
        self.session.save_settings()
        if dont_ask:
            self._remember_welcome()
        self.statusBar().showMessage(
            self.tr("Location saved: latitude {lat:.4f}, longitude {lon:.4f}. "
                    "The GOTO can now find the Sun.").format(lat=lat, lon=lon), 7000)
        if hasattr(self, "welcome_dialog"):
            self.welcome_dialog.close()

    # @args: dont_ask - whether the banner should stay away
    def _welcome_dismissed(self, dont_ask: bool) -> None:
        if dont_ask:
            self._remember_welcome()
        else:
            self.statusBar().showMessage(
                self.tr("You can set the observatory position any time in "
                        "Tools, Settings."), 6000)
        if hasattr(self, "welcome_dialog"):
            self.welcome_dialog.close()

    # @args: none. Stores the "do not show again" preference
    def _remember_welcome(self) -> None:
        settings = QSettings("SolarScribe", "SolarScribe")
        settings.setValue("welcome_done", True)
        settings.sync()

    # @args: event - show: keep the first-run assistant on top of the window
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if hasattr(self, "welcome_dialog") and self.welcome_dialog.isVisible():
            self.welcome_dialog.raise_()

    # --------------------------------------------------------------- status

    # @args: none. Adds the five figures of the status bar, each with its meaning
    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.camera_status = QLabel(self.tr("Camera: --"))
        self.camera_status.setToolTip(self.tr(
            "Which camera is streaming. A simulator here means no hardware is "
            "connected and the numbers are not a camera measurement."))
        self.fps_status = QLabel(self.tr("Rate: --"))
        self.fps_status.setToolTip(self.tr(
            "Frames per second received against the 120 fps budget. At 120 fps "
            "each frame has 8.3 ms; below it the scan stretches."))
        self.mount_status = QLabel(self.tr("Mount: --"))
        self.mount_status.setToolTip(self.tr(
            "The mount and its tracking state. Tracking off means the Sun drifts "
            "out of the slit."))
        self.dropped_status = QLabel(self.tr("Dropped: --"))
        self.dropped_status.setToolTip(self.tr(
            "Frames lost inside the SDK, as a count and a fraction. Each one is a "
            "gap in the SER; the budget is 0.1% per scan."))
        self.disk_status = QLabel(self.tr("Disk: --"))
        self.disk_status.setToolTip(self.tr(
            "Free space on the session disk. A recording does not start below "
            "1 GB."))
        bar.addWidget(self.camera_status)
        bar.addWidget(self.fps_status)
        bar.addPermanentWidget(self.mount_status)
        bar.addPermanentWidget(self.dropped_status)
        bar.addPermanentWidget(self.disk_status)
        # The telescope panel also speaks through the status bar: its dock is
        # narrow, and the sentence must be visible even when the panel is
        # scrolled.
        self.telescope.statusMessage.connect(
            lambda text: bar.showMessage(text, 6000))

    # @args: label - the status label; text - the sentence; alert - paint amber
    def _set_status(self, label: QLabel, text: str, alert: bool = False) -> None:
        label.setText(text)
        label.setProperty("alert", bool(alert))
        label.style().unpolish(label)
        label.style().polish(label)

    # ---------------------------------------------------------------- menus

    # @args: none. Connects the File/Tools/Help actions
    def _wire_menus(self) -> None:
        pairs = {
            "actionQuit": self.close,
            "actionOpenSessionFolder": self.open_session_folder,
            "actionSettings": self.open_settings,
            "actionProfiles": self.manage_profiles,
            "actionSkyCalendar": self.open_sky_calendar,
            "actionRoiManager": self.open_roi_manager,
            "actionDiagnostics": self.show_diagnostics,
            "actionLogs": self.open_logs,
            "actionQuickStart": self.show_quick_start,
            "actionAbout": self.show_about,
        }
        for name, slot in pairs.items():
            action = self._action(name)
            if action is not None:
                action.triggered.connect(slot)
        # The right band can be collapsed to its title bar or hidden entirely;
        # the Panels menu is how it comes back, so a closed dock is never a lost
        # control (ADR-026).
        for name, dock in (("actionTelescopePanel", self.telescope_dock),
                           ("actionCameraPanel", self.camera_dock),
                           ("actionHealthPanel", self.health_dock)):
            action = self._action(name)
            if action is None or dock is None:
                continue
            action.setChecked(bool(dock.isVisible()))
            action.toggled.connect(
                lambda checked, d=dock: d.setVisible(bool(checked)))
            dock.visibilityChanged.connect(
                lambda visible, a=action: self._sync_panel_action(a, visible))

    # @args: action - a checkable Panels action; visible - the dock state
    def _sync_panel_action(self, action: QAction, visible: bool) -> None:
        if action.isChecked() == bool(visible):
            return
        action.blockSignals(True)
        action.setChecked(bool(visible))
        action.blockSignals(False)

    # ---------------------------------------------------------------- steps

    # @args: none. Connects the rail and the primary/secondary step actions
    def _wire_steps(self) -> None:
        self.rail.stepActivated.connect(self.select_step)
        self._connect("findPrimaryButton", self.find_the_sun)
        self._connect("findStopButton", self.telescope_stop)
        self._connect("polarStartButton", self.start_polar)
        self._connect("polarSecondButton", self.confirm_polar)
        self._connect("polarStopButton", self.stop_polar)
        self._connect("focusMeasureButton", self.measure_focus_tilt)
        self._connect("focusResetButton", self.reset_focus_holds)
        self._connect("roiApplyButton", self.apply_roi)
        self._connect("roiMeasureButton", self.measure_tilt)
        self._connect("roiSavePresetButton", self.save_preset)
        self._connect("prepareButton", self.prepare_scan)
        self._connect("scanPrimaryButton", self.start_scan)
        self._connect("scanPauseButton", self.toggle_scan_pause)
        self._connect("scanAbortButton", self.abort_scan)
        self._connect("openSessionButton", self.open_session_folder)
        self._connect("reopenStepButton", self.reopen_current_step)

    # @args: name - object name; slot - callable
    def _connect(self, name: str, slot) -> None:
        button = self.findChild(QPushButton, name)
        if button is not None:
            button.clicked.connect(slot)

    # @args: step - a session step
    def select_step(self, step: str) -> None:
        self.session.select_step(step)
        self._show_step(step)

    # @args: none. Marks the current completed step as in progress again
    def reopen_current_step(self) -> None:
        step = self.session.current_step()
        self.session.reopen_step(step)
        self.statusBar().showMessage(self.tr(
            "Step reopened: the numbers already saved are kept, so you can "
            "correct one thing and continue."), 6000)

    # @args: step - the step to show in the side panel
    def _show_step(self, step: str) -> None:
        stack = self.findChild(QStackedWidget, "sideStack")
        if stack is not None and step in SESSION_STEPS:
            stack.setCurrentIndex(SESSION_STEPS.index(step))
        if getattr(self, "_shown_step", None) != step:
            scroll = self.findChild(QScrollArea, "sideScroll")
            if scroll is not None:
                # A new page starts at its top; keeping the old scroll offset
                # hides the primary action of the step the user just opened.
                scroll.verticalScrollBar().setValue(0)
            self._shown_step = step
        self.rail.set_current(step)
        self._update_recommendation()
        if step == "focus":
            self._refresh_focus_labels()
        elif step == "roi" and hasattr(self, "roi_editor"):
            # The Focus step may have measured the tilt; the ROI card shows it
            # and uses it to size the strip, even when the observer jumped here.
            self.roi_editor.refresh_tilt()
            self.roi_editor.refresh_warnings()
        # Do not reload the ROI fields here: the observer may have typed edits
        # that are not applied yet, and peeking at another step must not throw
        # them away. The model changes reload the editor through roiChanged.

    # @args: none. Rewrites the recommendation sentence; never a gate
    def _update_recommendation(self) -> None:
        label = self.findChild(QLabel, "recommendationLabel")
        if label is None:
            return
        statuses = [self.session.status_of(step) for step in SESSION_STEPS]
        if all(status is StepStatus.DONE for status in statuses):
            label.setText(self.tr(
                "All five steps are done. Reopen any step from the rail; nothing "
                "is locked."))
            return
        step = self.session.recommended_step()
        label.setText(self.tr("Next: {step}. Any step is open.").format(
            step=self._step_title(step)))

    # @args: step - a session step
    # @return: its translated name
    def _step_title(self, step: str) -> str:
        if step == "find_sun":
            return self.tr("Find the Sun")
        if step == "polar":
            return self.tr("Polar alignment")
        if step == "focus":
            return self.tr("Focus")
        if step == "roi":
            return self.tr("ROI")
        return self.tr("Scanning")

    # --------------------------------------------------------------- controls

    # @args: none. Fills the combos and connects the view controls
    def _wire_controls(self) -> None:
        stretch = self.findChild(QComboBox, "stretchCombo")
        if stretch is not None:
            # The percentiles say what they do: below the low one the picture
            # is black, above the high one it is white. The last entry is the
            # manual mode the histogram handles switch to (ADR-026).
            stretch.blockSignals(True)
            stretch.clear()
            stretch.addItem(self.tr("Full range: 0 to 100%"), (0.0, 100.0))
            stretch.addItem(self.tr("Soft: 1 to 99%"), (1.0, 99.0))
            stretch.addItem(self.tr("Normal: 5 to 95%"), (5.0, 95.0))
            stretch.addItem(self.tr("Hard: 25 to 75%"), (25.0, 75.0))
            stretch.addItem(self.tr("Manual: drag the histogram handles"), None)
            stretch.setCurrentIndex(2)
            stretch.blockSignals(False)
            stretch.currentIndexChanged.connect(self._stretch_changed)
            self._stretch_changed(2)

        zoom = self.findChild(QSpinBox, "zoomSpin")
        if zoom is not None:
            zoom.valueChanged.connect(self.viewer.set_zoom)
        self.viewer.zoomChanged.connect(
            lambda value: zoom.setValue(value) if zoom is not None else None)

        self._toggle("gridCheck", self.viewer.set_grid)
        self._toggle("crossCheck", self.viewer.set_cross)
        self._toggle("roiCheck", self.viewer.set_show_band)
        self._connect("fitButton", lambda *_: self.viewer.reset_view())
        self.histogram.stretchChanged.connect(self._histogram_stretch_changed)
        self._wire_strip("histogramToggle", "histogramBody", True)
        self._wire_strip("scanStripToggle", "scanBody", False)
        if self.identify_check is not None:
            self.identify_check.toggled.connect(self._toggle_identification)

        mode = self.findChild(QComboBox, "planModeCombo")
        if mode is not None:
            mode.blockSignals(True)
            mode.clear()
            mode.addItem(self.tr("Simple scan"), "simple")
            mode.addItem(self.tr("Mosaic"), "mosaic")
            # The schema has no "mode" key: the mode IS the row count, so the
            # file keeps one truth (ADR-024) instead of two that can disagree.
            stored_rows = max(1, int(self.session.value("scan", "rows")))
            mode.setCurrentIndex(1 if stored_rows > 1 else 0)
            mode.blockSignals(False)
            mode.currentIndexChanged.connect(self._plan_changed)
        for name in ("planCyclesSpin", "planRowsSpin"):
            spin = self.findChild(QSpinBox, name)
            if spin is not None:
                spin.valueChanged.connect(self._plan_changed)
        cycles = self.findChild(QSpinBox, "planCyclesSpin")
        if cycles is not None:
            cycles.setValue(max(1, int(self.session.value("scan", "cycles"))))
        rows = self.findChild(QSpinBox, "planRowsSpin")
        if rows is not None:
            rows.setValue(max(1, int(self.session.value("scan", "rows"))))
        self._plan_changed()

    # @args: name - checkbox object name; slot - callable taking a bool
    def _toggle(self, name: str, slot) -> None:
        check = self.findChild(QCheckBox, name)
        if check is not None:
            check.toggled.connect(slot)
            slot(check.isChecked())

    # @args: button_name, body_name - the strip header and its body; open - start
    #        folded or open. The header is always visible, so a folded strip is
    #        discoverable and costs only its 24 px line (ADR-026)
    def _wire_strip(self, button_name: str, body_name: str, open: bool) -> None:
        button = self.findChild(QToolButton, button_name)
        body = self._w(body_name)
        if button is None or body is None:
            return
        button.setChecked(bool(open))
        body.setVisible(bool(open))
        self._set_strip_arrow(button, bool(open))
        button.toggled.connect(
            lambda checked, b=body, t=button: self._strip_toggled(t, b, checked))

    # @args: button - the strip header; body - the part that folds; open - state
    def _strip_toggled(self, button: QToolButton, body: QWidget,
                       open: bool) -> None:
        body.setVisible(bool(open))
        self._set_strip_arrow(button, bool(open))

    # @args: button - the strip header; open - whether the body is shown
    def _set_strip_arrow(self, button: QToolButton, open: bool) -> None:
        button.setArrowType(Qt.ArrowType.DownArrow if open
                            else Qt.ArrowType.RightArrow)

    # @args: button_name, body_name - the strip; open - force it open or folded
    def _set_strip(self, button_name: str, body_name: str, open: bool) -> None:
        button = self.findChild(QToolButton, button_name)
        if button is None:
            return
        button.blockSignals(True)
        button.setChecked(bool(open))
        button.blockSignals(False)
        body = self._w(body_name)
        if body is not None:
            body.setVisible(bool(open))
            self._set_strip_arrow(button, bool(open))

    # @args: low, high - the percentiles the histogram handles produced
    def _histogram_stretch_changed(self, low: float, high: float) -> None:
        self.viewer.set_stretch(low, high)
        combo = self.findChild(QComboBox, "stretchCombo")
        if combo is None or combo.count() == 0:
            return
        index = combo.count() - 1
        combo.blockSignals(True)
        combo.setItemText(index, self.tr(
            "Manual: black {low:.0f}%, white {high:.0f}%").format(
                low=low, high=high))
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    # @args: index - the stretch preset selected
    def _stretch_changed(self, index: int) -> None:
        combo = self.findChild(QComboBox, "stretchCombo")
        if combo is None:
            return
        data = combo.itemData(index)
        if not data:
            # The manual entry: the histogram handles own the stretch, so the
            # preset must not snap them back.
            return
        low, high = data
        self.viewer.set_stretch(low, high)
        self.histogram.set_stretch(low, high)

    # @args: *_ - the spin or combo that changed
    def _plan_changed(self, *_args) -> None:
        # The plan is built from these controls; changing one invalidates the
        # prepared plan, so the Start action waits for a new Prepare.
        self._prepared = False
        if not self._busy_scan:
            self._plan = None
        mode = self.findChild(QComboBox, "planModeCombo")
        rows = self.findChild(QSpinBox, "planRowsSpin")
        mosaic = bool(mode and mode.currentData() == "mosaic")
        if rows is not None:
            rows.setEnabled(mosaic)
            target = rows.value()
            if mosaic and target < 2:
                # A mosaic of one row is a simple scan; bump it so the control
                # tells the truth instead of pretending to mosaic.
                target = 2
            elif not mosaic:
                # The mode IS the row count (the schema has no separate key), so
                # a simple scan must persist one row or the next start would
                # reopen as a mosaic.
                target = 1
            if target != rows.value():
                rows.blockSignals(True)
                rows.setValue(target)
                rows.blockSignals(False)
            self.session.set_value("scan", "rows", target)
        cycles = self.findChild(QSpinBox, "planCyclesSpin")
        if cycles is not None:
            self.session.set_value("scan", "cycles", cycles.value())
        self._update_plan_summary()

    # @args: none. Explains the plan with its arithmetic, before it runs
    def _update_plan_summary(self) -> None:
        label = self.findChild(QLabel, "planSummary")
        if label is None:
            return
        cycles = self.findChild(QSpinBox, "planCyclesSpin")
        n_cycles = cycles.value() if cycles is not None else 1
        if self._plan is None:
            label.setText(self.tr(
                "The engine computes the plan when you press Prepare: rows, "
                "sweep rate and expected duration. Nothing runs until then."))
            return
        rows = len(self._plan.rows)
        total_s = float(self._plan.duration_s) * max(1, n_cycles)
        text = self.tr(
            "Plan: {rows} row(s), {duration:.0f} s per cycle at {rate:.0f} "
            "arcsec/s, about {frames} frames per cycle. {cycles} cycle(s) take "
            "about {total:.1f} min.").format(
                rows=rows, duration=float(self._plan.duration_s),
                rate=float(self._plan.rate_arcsec_s),
                frames=int(self._plan.frames_estimate),
                cycles=max(1, n_cycles), total=total_s / 60.0)
        if self.session.is_simulated():
            text += self.tr(
                " The simulator uses a fixed rate, chosen so the demo finishes in "
                "seconds; the real camera calibrates the rate during "
                "preparation.")
        label.setText(text)
        self.scan_view.set_rows(rows)

    # @args: plan - the ScanPlan computed by the engine
    def _on_plan_ready(self, plan) -> None:
        self._plan = plan
        self._update_plan_summary()

    # -------------------------------------------------------------- profiles

    # @args: none. Connects the always-visible profile bar
    def _wire_profile(self) -> None:
        combo = self.findChild(QComboBox, "profileCombo")
        if combo is not None:
            combo.currentIndexChanged.connect(self._profile_selected)
        for name, slot in (("profileSaveButton", self.save_profile_as),
                           ("profileManageButton", self.manage_profiles)):
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.clicked.connect(slot)
        self._fill_profile_combo()

    # @args: none. Shows the active name and the names the store returns
    def _fill_profile_combo(self) -> None:
        combo = self.findChild(QComboBox, "profileCombo")
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        names = list(self._profiles.names())
        if self._active_profile not in names:
            combo.addItem(self.tr("No active profile"), "")
        for name in names:
            combo.addItem(name, name)
        index = combo.findData(self._active_profile)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    # @args: index - the combo row the observer picked
    def _profile_selected(self, index: int) -> None:
        combo = self.findChild(QComboBox, "profileCombo")
        if combo is None or index < 0:
            return
        name = str(combo.itemData(index) or "")
        if name and name != self._active_profile:
            self.activate_profile(name)

    # @args: name - the profile to load and make active; "" means no active one
    def activate_profile(self, name: str) -> None:
        if not name:
            self._active_profile = ""
            self._fill_profile_combo()
            self._sync_profile_manager()
            self.statusBar().showMessage(self.tr(
                "No active profile. Choose one in the profile bar or save the "
                "current setup under a name."), 9000)
            return
        try:
            profile = self._profiles.load(name)
        except (ProfileStoreError, OSError) as error:
            self._profile_error(error, name)
            self._fill_profile_combo()
            return
        if profile is None:
            self.statusBar().showMessage(self.tr(
                "The profile '{name}' could not be loaded.").format(name=name),
                9000)
            self._fill_profile_combo()
            return
        try:
            self._profiles.set_active(name)
        except (ProfileStoreError, OSError) as error:
            # If the store cannot remember the switch, do not pretend the
            # session moved: the bar and the next startup would disagree.
            self._profile_error(error, name)
            self._fill_profile_combo()
            return
        self.session.set_profile(profile)
        self._active_profile = name
        if hasattr(self, "roi_editor"):
            self.roi_editor.reload_presets()
            self.roi_editor.refresh_scale()
            self.roi_editor.refresh_rate()
        # The plan depends on the optics, so switching a profile invalidates it.
        self._prepared = False
        self._plan = None
        self._update_plan_summary()
        self._update_scan_enabled()
        self._fill_profile_combo()
        self._sync_profile_manager()
        self.statusBar().showMessage(self.tr(
            "Profile '{name}' loaded: optics, camera and ROI presets. The camera "
            "stays as it is; apply a preset if the strip changed.").format(
                name=name), 9000)

    # @args: none. Saves the current setup under a name and makes it active
    def save_profile_as(self) -> None:
        name, accepted = QInputDialog.getText(
            self, self.tr("Save profile as"), self.tr("Profile name:"),
            text=self._active_profile or self.tr("New profile"))
        if not accepted or not name.strip():
            return
        name = name.strip()
        if name in self._profiles.names():
            answer = QMessageBox.question(
                self, self.tr("Save profile as"),
                self.tr("A profile named '{name}' already exists. Replace "
                        "it?").format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._profiles.save(name, self.session.profile, make_active=True)
        except (ProfileStoreError, OSError) as error:
            self._profile_error(error, name)
            return
        self._active_profile = name
        self._fill_profile_combo()
        self._sync_profile_manager()
        self.statusBar().showMessage(self.tr(
            "Profile saved as '{name}' and set active.").format(name=name), 9000)

    # @args: none. Opens the list where profiles are renamed or deleted
    def manage_profiles(self) -> None:
        if self._profile_manager_dialog is None:
            self._profile_manager_dialog = ProfileManagerDialog(
                self._profiles, self.session.profile, self._active_profile, self)
            self._profile_manager_dialog.profileChosen.connect(self.activate_profile)
            self._profile_manager_dialog.profilesChanged.connect(
                self._on_profiles_changed)
        else:
            self._profile_manager_dialog.set_data(
                self._profiles, self.session.profile, self._active_profile)
        self._profile_manager_dialog.show()
        self._profile_manager_dialog.raise_()

    # @args: profile - the live profile; writes it through the named store
    def _persist_active_profile(self, profile) -> None:
        if not self._active_profile:
            self.statusBar().showMessage(self.tr(
                "No active profile: the ROI preset was not saved. Choose or "
                "save a profile in the top bar."), 9000)
            return
        try:
            self._profiles.save_active(profile)
        except (ProfileStoreError, OSError) as error:
            self._profile_error(error, self._active_profile)

    # @args: none. The manager changed the names; refresh the bar
    def _on_profiles_changed(self) -> None:
        self._fill_profile_combo()
        self._sync_profile_manager()

    # @args: none. Keeps an open manager in step with the bar
    def _sync_profile_manager(self) -> None:
        dialog = self._profile_manager_dialog
        if dialog is not None and dialog.isVisible():
            dialog.set_data(self._profiles, self.session.profile,
                            self._active_profile)

    # @args: error - a ProfileStoreError or OSError; name - the profile involved
    def _profile_error(self, error, name: str) -> None:
        reason = getattr(error, "reason", "")
        if reason == "named_store_missing":
            text = self.tr(
                "Named-profile storage is not available in this build; the "
                "single profile is used.")
        elif reason == "no_profile_path":
            text = self.tr(
                "The profile file is not configured. Check Settings.")
        else:
            text = self.tr(
                "The profile '{name}' could not be changed. The log has the "
                "detail.").format(name=name)
        self.statusBar().showMessage(text, 10000)

    # --------------------------------------------------------------- session


    # @args: none. Connects the Session signals
    def _wire_session(self) -> None:
        self.session.changed.connect(self._refresh_from_session)
        self.session.stepChanged.connect(self._show_step)
        self.session.roiChanged.connect(self._roi_refreshed)
        self.session.message.connect(self._show_message)
        self.session.roiChanged.connect(self._update_scan_enabled)

    # @args: none. Repaints the rail, the recommendation and the status bar
    def _refresh_from_session(self) -> None:
        self.rail.set_state(self.session.state, self.session.current_step())
        self._show_step(self.session.current_step())
        self._update_plan_summary()
        self._update_scan_enabled()
        self._update_status_devices()
        reopen = self.findChild(QPushButton, "reopenStepButton")
        if reopen is not None:
            done = self.session.status_of(self.session.current_step()) is StepStatus.DONE
            reopen.setVisible(done)
        self._sync_camera_panel()
        if hasattr(self, "roi_editor"):
            # A tilt measured in the Focus step has to reach the ROI card: it
            # sizes the strip and the warning, even if the observer is elsewhere.
            self.roi_editor.refresh_tilt()
            self.roi_editor.refresh_warnings()
        if self.session.current_step() == "focus":
            self._refresh_focus_labels()

    # @args: none. The ROI model changed: reload the fields and the overlay
    def _roi_refreshed(self) -> None:
        self.roi_editor.reload()
        self.viewer.set_band(self.session.roi.band)
        self._update_health()
        self._update_scan_enabled()
        self._sync_camera_panel()

    # @args: none. A message from the session goes to the status bar
    def _show_message(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    # @args: none. Re-labels the camera and mount status
    def _update_status_devices(self) -> None:
        info = self.session.camera_info()
        if info is None:
            self._set_status(self.camera_status, self.tr("Camera: not connected"))
        elif self.session.is_simulated():
            self._set_status(self.camera_status, self.tr(
                "Camera: Simulator (no hardware)"))
        else:
            self._set_status(self.camera_status, self.tr("Camera: {model}").format(
                model=getattr(info, "model", "")))
        mount = self.session.demo_mount() or self.telescope.mount()
        if mount is not None:
            try:
                connected = mount.is_connected()
                state = self.tr("tracking") if mount.status().tracking \
                    else self.tr("stopped")
            except Exception:  # noqa: BLE001 - the panel reports the error
                connected, state = False, self.tr("stopped")
            if connected:
                simulated_mount = type(mount).__name__.startswith("Sim")
                prefix = self.tr("Mount: Simulator") if simulated_mount \
                    else self.tr("Mount: connected")
                self._set_status(self.mount_status,
                                 self.tr("{prefix}, {state}").format(
                                     prefix=prefix, state=state))
                return
        self._set_status(self.mount_status, self.tr("Mount: not connected"))

    # --------------------------------------------------------------- camera
    # @args: none. Pushes the live camera into the camera panel
    def _sync_camera_panel(self) -> None:
        harness = self.session.harness
        info = self.session.camera_info()
        streaming = bool(harness is not None and hasattr(harness, "is_running")
                         and harness.is_running())
        if hasattr(self, "camera_panel"):
            self.camera_panel.set_current(info, self.session.is_simulated(),
                                          streaming)
            self.camera_panel.set_roi(self.session.roi.capture if info else None)
            if self._last_counters is not None:
                self.camera_panel.set_counters(self._last_counters)

    # @args: info - the chosen CameraInfo; camera - the unopened Camera
    def _camera_chosen(self, info, camera) -> None:
        if self.session.use_camera(camera, info):
            self._prepared = False
            self._plan = None
            self.roi_editor.reload()
            self._update_plan_summary()
            self._update_scan_enabled()
            self._sync_camera_panel()
            self.statusBar().showMessage(self.tr(
                "Camera {model} opened. The ROI preset from the profile was "
                "restored; check it in the ROI step.").format(
                    model=getattr(info, "model", "")), 9000)
            mount = self.session.demo_mount()
            if not self.session.is_simulated() and mount is not None \
                    and type(mount).__name__.startswith("Sim"):
                self.statusBar().showMessage(self.tr(
                    "The camera is real but the mount is the simulator: use the "
                    "telescope panel's Find to connect the real mount, or the "
                    "centring cannot converge."), 12000)
        else:
            self.statusBar().showMessage(self.tr(
                "The camera could not be opened. The live state and the device "
                "diagnostics say why."), 9000)
        self._sync_camera_panel()

    # @args: none. Closes the camera and empties the video
    def _camera_close(self) -> None:
        self.session.close_camera()
        self.viewer.clear()
        self.histogram.clear()
        self._update_histogram_saturation()
        self._reset_focus_readings()
        self._identify_generation += 1
        if self.identify_check is not None and self.identify_check.isChecked():
            self.spectrum_panel.show_no_spectrum()
        self._prepared = False
        self._plan = None
        self._update_scan_enabled()
        self._sync_camera_panel()
        self.statusBar().showMessage(self.tr(
            "Camera closed. The telescope is untouched."), 6000)

    # @args: info - the live CameraInfo or None; simulated - scene simulator
    def _on_camera_changed(self, info, simulated: bool) -> None:
        self._sync_camera_panel()
        self._update_status_devices()
        self._update_scan_enabled()
        if info is None:
            self.viewer.clear()
            self.histogram.clear()
            self._update_histogram_saturation()
            self._reset_focus_readings()
            self._identify_generation += 1
            if self.identify_check is not None and self.identify_check.isChecked():
                self.spectrum_panel.show_no_spectrum()

    # @args: code - a stable engine reason code
    def _on_engine_error(self, code: str) -> None:
        self._busy_center = False
        self._busy_scan = False
        self._prepared = False
        self._enable("findPrimaryButton", True)
        self._enable("prepareButton", True)
        self._enable("scanPauseButton", False)
        self._enable("scanAbortButton", False)
        self._enable("scanStripToggle", True)
        self._update_scan_enabled()
        self.camera_panel.set_current(self.session.camera_info(),
                                      self.session.is_simulated(), False)
        self.camera_panel.message_label.setText(self.tr(
            "The engine reported a problem. The device diagnostics and the log "
            "say why."))
        self.statusBar().showMessage(self.tr(
            "Engine problem: {reason}.").format(
                reason=self._reason_text(code)), 10000)

    # --------------------------------------------------------------- harness

    # @args: none. Connects the simulator signals, the shape the engines will use
    def _wire_harness(self) -> None:
        harness = self.session.harness
        if harness is None:
            return
        harness.frameReady.connect(self._on_frame)
        harness.countersChanged.connect(self._on_counters)
        harness.prepareStatus.connect(self._on_prepare_status)
        harness.prepareFinished.connect(self._on_prepare_finished)
        harness.scanProgress.connect(self._on_scan_progress)
        harness.scanFinished.connect(self._on_scan_finished)
        if hasattr(harness, "reconResult"):
            harness.reconResult.connect(self._on_recon_result)
        if hasattr(harness, "reconStrip"):
            # Last-resort UI demo only; the real harness emits ReconResult.
            harness.reconStrip.connect(self.recon.add_strip)
        harness.polarProgress.connect(self._on_polar_progress)
        harness.polarFinished.connect(self._on_polar_finished)
        harness.rateEstimate.connect(self._on_rate)
        if hasattr(harness, "cameraChanged"):
            harness.cameraChanged.connect(self._on_camera_changed)
        if hasattr(harness, "engineError"):
            harness.engineError.connect(self._on_engine_error)
        # The harness message signal carries exception detail for the log, not
        # a sentence for the observer; the engineError code is the user-facing
        # path. Do not print technical text in the status bar (ADR-014).
        if hasattr(harness, "centeringProgress"):
            harness.centeringProgress.connect(self._on_centering_progress)
        if hasattr(harness, "centeringFinished"):
            harness.centeringFinished.connect(self._on_centering_finished)
        if hasattr(harness, "planReady"):
            harness.planReady.connect(self._on_plan_ready)
        if hasattr(harness, "cycleStarted"):
            harness.cycleStarted.connect(self._on_cycle_started)
        if hasattr(harness, "scanPhase"):
            harness.scanPhase.connect(self._on_scan_phase)

    # @args: none. Starts the simulator and the display timers. The app calls
    #        this after showing the window; tests drive frames by hand
    def start_capture(self) -> None:
        harness = self.session.harness
        if harness is not None and self.session.has_camera():
            started = harness.start()
            if not started:
                self.statusBar().showMessage(self.tr(
                    "The camera did not start. Open the camera panel and check "
                    "the live state."), 8000)
        self._sync_camera_panel()

    # @args: none. Polls the display bridge (nothing in the demo, which emits)
    def _pump_display(self) -> None:
        return

    # @args: frame - a Frame from the capture thread or the simulator
    def _on_frame(self, frame) -> None:
        self.viewer.set_frame(frame)
        # The histogram reads only the spectral band: the dark rows outside it
        # would dominate a whole-frame count and hide the exposure that matters
        # (ADR-026).
        band = None
        try:
            band = frame.cut_roi(self.session.roi.band)
        except (AttributeError, ValueError):
            band = frame
        if band is not None:
            self.histogram.set_frame(band)
            self._update_histogram_saturation()
        if self.session.current_step() == "focus":
            self._update_focus_metrics(frame)

    # @args: none. Turns the band's saturation fraction into the strip header
    def _update_histogram_saturation(self) -> None:
        label = self.findChild(QLabel, "histogramSaturation")
        if label is None:
            return
        if self.histogram.frame_size() == (0, 0):
            text, state = self.tr("No frame yet"), "muted"
        else:
            fraction = self.histogram.saturation_fraction() * 100.0
            if fraction >= 0.1:
                text = self.tr("{value:.1f}% clipped at white").format(
                    value=fraction)
                state = "warning"
            else:
                text = self.tr("No clipping")
                state = "ok"
        if label.text() == text and label.property("state") == state:
            return
        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)

    # @args: counters - the live StreamCounters
    def _on_counters(self, counters: StreamCounters) -> None:
        self._last_counters = counters
        self._update_health()

    # @args: none. Feeds the health panel and the status bar
    def _update_health(self) -> None:
        counters = self._last_counters or StreamCounters()
        free_gb = None
        if self.session.harness is not None:
            free_gb = self.session.harness.free_gb()
        self.health.set_counters(counters, None, free_gb,
                                 self.session.roi.capture,
                                 simulated=self.session.is_simulated())
        if hasattr(self, "camera_panel"):
            self.camera_panel.set_counters(counters)
            self.camera_panel.set_roi(self.session.roi.capture
                                      if self.session.has_camera() else None)
        target = float(self.session.value("capture", "target_fps"))
        fps = float(counters.fps)
        received = int(counters.frames_received)
        dropped = int(counters.frames_dropped_sdk)
        percent = dropped / received * 100.0 if received else 0.0
        if received:
            self._set_status(self.fps_status,
                             self.tr("Rate: {fps:.0f} fps of {target:.0f}{suffix}").format(
                                 fps=fps, target=target,
                                 suffix=self.tr(" (simulator)")
                                 if self.session.is_simulated() else ""),
                             alert=fps < target)
            self._set_status(
                self.dropped_status,
                self.tr("Dropped: {dropped} ({percent:.2f}%)").format(
                    dropped=dropped, percent=percent),
                alert=percent > 0.1)
        else:
            # No frame yet means no measurement; a zero would be a figure
            # without a meaning.
            self._set_status(self.fps_status, self.tr("Rate: --"))
            self._set_status(self.dropped_status, self.tr("Dropped: --"))
        if free_gb is not None:
            self._set_status(self.disk_status,
                             self.tr("Disk: {free:.1f} GB free").format(free=free_gb),
                             alert=free_gb < float(
                                 self.session.value("capture", "min_free_disk_gb")))
        else:
            self._set_status(self.disk_status, self.tr("Disk: --"))
        self._update_status_devices()

    # @args: fps, mb_s - the rate the engine announced
    def _on_rate(self, fps: float, mb_s: float) -> None:
        self.roi_editor.refresh_rate()

    # ------------------------------------------------------------ find the Sun

    # @args: result - a shg CenteringResult from the Find-the-Sun service
    # The dead zone is shown, not hidden: near the centre the coarse signal is
    # flat, so the number is honest about what the step could not resolve.
    def show_centering_result(self, result) -> None:
        dec = float(result.dec_offset_arcsec)
        dead = float(getattr(result, "dead_zone_arcsec", 0.0))
        if not getattr(result, "ok", False):
            self._set_label("sunStateValue", self.tr("Centring failed"), "error")
            self._set_label("decErrorValue", self.tr(
                "Not measured: {reason}").format(
                    reason=self._reason_text(result.reason_code)), "error")
            return
        self._set_label("sunStateValue", self.tr("On the slit"), "ok")
        suffix = self.tr(" (simulated)") if self.session.is_simulated() else ""
        self._set_label("decErrorValue", self.tr(
            "{value:.1f} arcsec{suffix}").format(value=dec, suffix=suffix), "ok")
        if dead > 0.0:
            self._set_label("deadZoneValue", self.tr(
                "{value:.1f} arcsec").format(value=dead), "warning")
        else:
            self._set_label("deadZoneValue", self.tr(
                "0.0 arcsec: the symmetry method resolves the centre"), "ok")
        self.session.complete_step("find_sun", dec_error_arcsec=dec,
                                   dead_zone_arcsec=dead)

    # @args: none. The one action of the Find the Sun step
    def find_the_sun(self) -> None:
        if not self.session.has_camera():
            self.statusBar().showMessage(self.tr(
                "Open a camera in the camera panel first; the centring needs "
                "frames."), 8000)
            return
        if self._busy_center:
            return
        mount = self.telescope.mount()
        self.telescope.goto_sun_clicked()
        if mount is None or not mount.is_connected():
            return
        if self.session.center_sun():
            self._busy_center = True
            self._enable("findPrimaryButton", False)
            self._set_label("sunStateValue", self.tr("Centring..."), "warning")
            self._set_label("decErrorValue", self.tr("Measuring..."), "warning")
            self.statusBar().showMessage(self.tr(
                "Centring the Sun: the coarse stage maximises the illuminated "
                "extent, then the fine stage balances the slit. It takes about "
                "a minute on real hardware."), 10000)
        else:
            self.statusBar().showMessage(self.tr(
                "The centring could not start. The telescope must be connected "
                "and the stream running."), 8000)

    # @args: status - a shg CenteringStatus
    def _on_centering_progress(self, status) -> None:
        phase = self.tr("Coarse") if status.phase == "coarse" else self.tr("Fine")
        text = self.tr("{phase} centring: {percent}%").format(
            phase=phase, percent=int(status.progress * 100))
        if status.dec_offset_arcsec is not None:
            text += self.tr(", Dec error {value:.1f} arcsec").format(
                value=float(status.dec_offset_arcsec))
        self._set_label("sunStateValue", text, "warning")

    # @args: result - the shg CenteringResult
    def _on_centering_finished(self, result) -> None:
        self._busy_center = False
        self._enable("findPrimaryButton", True)
        self.show_centering_result(result)
        if not getattr(result, "ok", False):
            self.statusBar().showMessage(self.tr(
                "The centring did not converge: {reason}. Move the Sun closer "
                "with the telescope panel and try again.").format(
                    reason=self._reason_text(result.reason_code)), 12000)

    # @args: none. Stops the mount from the step, not only from the panel
    def telescope_stop(self) -> None:
        self.telescope.stop_clicked()

    # ---------------------------------------------------------------- polar

    # @args: none. Starts the first measurement
    def start_polar(self) -> None:
        harness = self.session.harness
        if harness is None:
            self._say_unavailable(self.tr("polar alignment"))
            return
        harness.start_polar(False)
        self._set_label("polarStateValue", self.tr("Measuring..."), "warning")
        self._enable("polarSecondButton", False)
        bar = self.findChild(QWidget, "polarProgress")
        if bar is not None:
            bar.setValue(0)

    # @args: none. Runs the confirmation measurement
    def confirm_polar(self) -> None:
        harness = self.session.harness
        if harness is None:
            self._say_unavailable(self.tr("polar alignment"))
            return
        harness.start_polar(True)
        self._set_label("polarStateValue",
                        self.tr("Confirming..."), "warning")

    # @args: none. Stops the measurement without a result
    def stop_polar(self) -> None:
        if self.session.harness is not None:
            self.session.harness.stop_polar()
        self._set_label("polarStateValue", self.tr("Stopped"), "muted")
        bar = self.findChild(QWidget, "polarProgress")
        if bar is not None:
            bar.setValue(0)

    # @args: progress - 0..1; data - az/alt/samples from the assistant
    def _on_polar_progress(self, progress: float, data: dict) -> None:
        bar = self.findChild(QWidget, "polarProgress")
        if bar is not None:
            bar.setValue(int(progress * 100))
        self._set_label(
            "polarStateValue",
            self.tr("Measuring: {samples} samples").format(
                samples=int(data.get("samples", 0))), "warning")
        self._set_label("polarAzValue", self.tr("{value:.1f} arcmin, {direction}").format(
            value=float(data.get("azimuth_arcmin", 0.0)),
            direction=self._turn_text("az", float(data.get("azimuth_sign", 0.0)))),
            "muted")
        self._set_label("polarAltValue", self.tr(
            "{value:.1f} arcmin, {direction}").format(
                value=float(data.get("altitude_arcmin", 0.0)),
                direction=self._turn_text("alt",
                                          float(data.get("altitude_sign", 0.0)))),
            "muted")

    # @args: axis - "az" or "alt"; value - signed error in arcseconds
    # @return: which way to turn the knob. The sign convention is shg's:
    #          positive azimuth is east of the pole, positive altitude is too high
    def _turn_text(self, axis: str, value: float) -> str:
        if axis == "az":
            return self.tr("west") if value >= 0.0 else self.tr("east")
        return self.tr("down") if value >= 0.0 else self.tr("up")

    # @args: data - the final errors and whether it was the confirmation
    def _on_polar_finished(self, data: dict) -> None:
        azimuth = float(data.get("azimuth_arcmin", 0.0))
        altitude = float(data.get("altitude_arcmin", 0.0))
        azimuth_sign = float(data.get("azimuth_sign", 0.0))
        altitude_sign = float(data.get("altitude_sign", 0.0))
        second = bool(data.get("second", False))
        confirmed = bool(data.get("confirmed", False))
        reason = str(data.get("reason_code", ""))
        self._set_label("polarAzValue", self.tr("{value:.1f} arcmin, {direction}").format(
            value=azimuth, direction=self._turn_text("az", azimuth_sign)), "ok")
        self._set_label("polarAltValue", self.tr("{value:.1f} arcmin, {direction}").format(
            value=altitude, direction=self._turn_text("alt", altitude_sign)), "ok")
        if second:
            if not confirmed:
                self._set_label(
                    "polarStateValue",
                    self.tr("Not confirmed: repeat the measurement"), "warning")
                self._enable("polarSecondButton", True)
                self.statusBar().showMessage(self.tr(
                    "The confirmation is still outside the tolerance ({value:.1f} "
                    "arcmin against {tolerance:.1f} arcmin). Turn the screws again "
                    "and repeat the measurement.").format(
                        value=max(azimuth, altitude),
                        tolerance=float(data.get("tolerance_arcmin", 1.0))), 10000)
                return
            self._set_label("polarStateValue",
                            self.tr("Aligned (confirmed)"), "ok")
            self.session.complete_step("polar", azimuth_arcmin=azimuth,
                                       altitude_arcmin=altitude)
            bar = self.findChild(QWidget, "polarProgress")
            if bar is not None:
                bar.setValue(100)
            self.statusBar().showMessage(self.tr(
                "Polar alignment confirmed: the two measurements agree. The "
                "figures are in arcminutes on each screw."), 8000)
        else:
            self._set_label(
                "polarStateValue",
                self.tr("First measurement done. Turn the screws, then confirm."),
                "warning")
            self._enable("polarSecondButton", True)
            message = self.tr(
                "Turn the azimuth screw {azimuth:.1f} arcmin ({az_dir}) and the "
                "altitude screw {altitude:.1f} arcmin ({alt_dir}), then take the "
                "confirmation measurement.").format(
                    azimuth=azimuth,
                    az_dir=self._turn_text("az", azimuth_sign),
                    altitude=altitude,
                    alt_dir=self._turn_text("alt", altitude_sign))
            message += self.tr(
                " The confirmation must bring both screws inside {tol:.1f} "
                "arcmin.").format(tol=float(data.get("tolerance_arcmin", 1.0)))
            if reason == "geometry_limit":
                # The fit is still the best estimate, but the hour angles are
                # too close to separate the two errors (ADR-007).
                message += self.tr(
                    " The samples were too close in hour angle to separate the "
                    "two errors: measure again later, towards the east or west.")
            self.statusBar().showMessage(message, 12000)

    # ---------------------------------------------------------------- focus

    # @args: frame - the live frame. The three focusers are measured at most
    #        every 0.25 s: the grid is 288 block means, cheap but not free, and
    #        the observer cannot react faster than that
    def _update_focus_metrics(self, frame) -> None:
        now = time.monotonic()
        if now - self._last_focus_s < FOCUS_REFRESH_S:
            return
        self._last_focus_s = now
        try:
            grid = frame_grid(frame, self.session.roi.band)
            metrics = compute_metrics(grid)
        except (AttributeError, TypeError, ValueError):
            return
        self._focus_watcher.update(metrics)
        self._refresh_focus_labels()

    # @args: none. Paints the live metrics and their running best
    def _refresh_focus_labels(self) -> None:
        latest = self._focus_watcher.latest()
        holds = self._focus_watcher.holds()
        if latest is None:
            for name in ("lineContrastValue", "lineGradientValue",
                         "edgeSharpValue", "edgeFlatValue",
                         "detailContrastValue", "detailGradientValue",
                         "detailCountValue"):
                self._set_metric_label(name, self.tr("Not measured yet"), True)
            self._refresh_focus_tilt()
            return
        # The hole in the table: which label, which metric, decimals, and
        # whether lower is better. Edge wobble is the only figure where a lower
        # number is the better one, so its hold takes the low value.
        rows = (
            ("lineContrastValue", "line_contrast", 3, False),
            ("lineGradientValue", "line_gradient", 4, False),
            ("edgeSharpValue", "edge_sharp", 3, False),
            ("edgeFlatValue", "edge_flat", 2, True),
            ("detailContrastValue", "detail_contrast", 3, False),
            ("detailGradientValue", "detail_gradient", 4, False),
            ("detailCountValue", "detail_count", 0, False),
        )
        for name, key, decimals, lower_better in rows:
            value = getattr(latest, key)
            hold = holds.get(key)
            if decimals <= 0:
                current = str(int(round(float(value))))
                best = (str(int(round(float(hold.low if lower_better
                                         else hold.high))))
                        if hold is not None else "")
            else:
                current = f"{float(value):.{decimals}f}"
                best = (f"{float(hold.low if lower_better else hold.high):.{decimals}f}"
                        if hold is not None else "")
            text = (self.tr("{value} · best {best}").format(value=current, best=best)
                    if best else current)
            self._set_metric_label(name, text, False)
        self._refresh_focus_tilt()

    # @args: none. Paints the last tilt, its guidance and the ROI height it needs
    def _refresh_focus_tilt(self) -> None:
        tilt = self.session.last_tilt()
        band_height = int(self.session.roi.band[3])
        if tilt is None:
            self._set_label("focusTiltValue", self.tr("Not measured"), "muted")
            self._set_label("focusTiltHint", self.tr(
                "Measure the slit tilt: rotate the slit until the line is "
                "parallel to Dec."), "muted")
            self._set_label("focusTiltHeight", self.tr(
                "The ROI must hold the band plus the drift and a {margin:g} px "
                "margin.").format(margin=TILT_MARGIN_PX), "muted")
            return
        if not getattr(tilt, "ok", False):
            self._set_label("focusTiltValue", self.tr("The edge was not found"),
                            "warning")
            self._set_label("focusTiltHint", self.tr(
                "Check that the Sun is on the slit, then measure again."),
                "warning")
            self._set_label("focusTiltHeight", self.tr(
                "The ROI must hold the band plus the drift and a {margin:g} px "
                "margin.").format(margin=TILT_MARGIN_PX), "muted")
            return
        deg = float(tilt.tilt_deg)
        drift = float(tilt.tilt_px)
        edge = float(tilt.edge_std_px)
        aligned = abs(deg) <= FOCUS_TILT_TOLERANCE_DEG
        trusted = edge <= FOCUS_EDGE_STD_MAX_PX
        self._set_label("focusTiltValue", self.tr(
            "{deg:.2f} deg, {px:.1f} px drift").format(deg=deg, px=drift),
            "ok" if aligned and trusted else "warning")
        if edge > FOCUS_EDGE_STD_MAX_PX:
            self._set_label("focusTiltHint", self.tr(
                "The edge is irregular ({value:.1f} px); measure again before "
                "trusting the tilt.").format(value=edge), "warning")
        elif abs(deg) <= FOCUS_TILT_TOLERANCE_DEG:
            self._set_label("focusTiltHint", self.tr(
                "The slit is parallel to Dec within {tol:.1f} deg.").format(
                    tol=FOCUS_TILT_TOLERANCE_DEG), "ok")
        else:
            self._set_label("focusTiltHint", self.tr(
                "Rotate the slit towards zero: it leans {deg:.2f} deg. The scan "
                "can still run with a taller ROI.").format(deg=abs(deg)),
                "warning")
        needed = int(math.ceil(band_height + abs(drift) + TILT_MARGIN_PX))
        self._set_label("focusTiltHeight", self.tr(
            "The ROI must be at least {needed} px tall: band {band} + drift "
            "{drift:.1f} + margin {margin:g}.").format(
                needed=needed, band=band_height, drift=abs(drift),
                margin=TILT_MARGIN_PX), "muted")

    # @args: none. The one action of the Focus step
    def measure_focus_tilt(self) -> None:
        result = self.session.measure_tilt(self.session.roi.band)
        self._refresh_focus_tilt()
        if hasattr(self, "roi_editor"):
            self.roi_editor.refresh_tilt()
            self.roi_editor.refresh_warnings()
        if result is None:
            self.statusBar().showMessage(self.tr(
                "The tilt meter needs a frame and the SHG module. Check the "
                "camera and the stream, then measure again."), 9000)
            return
        if not getattr(result, "ok", False):
            self.statusBar().showMessage(self.tr(
                "The tilt could not be measured: {reason}. Check that the Sun is "
                "on the slit and measure again.").format(
                    reason=self._reason_text(result.reason_code)), 10000)
            return
        deg = float(result.tilt_deg)
        drift = float(result.tilt_px)
        edge = float(result.edge_std_px)
        if abs(deg) > FOCUS_TILT_TOLERANCE_DEG:
            needed = int(math.ceil(int(self.session.roi.band[3]) + abs(drift)
                                   + TILT_MARGIN_PX))
            self.statusBar().showMessage(self.tr(
                "Tilt {deg:.2f} deg, {px:.1f} px of drift. Rotate the slit "
                "towards zero; the ROI must be {needed} px tall. The scan can "
                "still run with that taller ROI.").format(
                    deg=deg, px=drift, needed=needed), 12000)
            return
        self.session.complete_step("focus", tilt_deg=deg, tilt_px=drift,
                                   edge_std_px=edge,
                                   **self._focus_metric_numbers())
        message = self.tr(
            "Slit parallel to Dec within {tol:.1f} deg. The Focus step is done; "
            "the ROI can be tight.").format(tol=FOCUS_TILT_TOLERANCE_DEG)
        if edge > FOCUS_EDGE_STD_MAX_PX:
            message += self.tr(
                " The edge is irregular ({value:.1f} px), so treat the tilt with "
                "caution.").format(value=edge)
        self.statusBar().showMessage(message, 12000)

    # @args: none. Clears the running best so the next focuser position is
    #        compared against a fresh baseline
    def reset_focus_holds(self) -> None:
        self._focus_watcher.reset()
        self._last_focus_s = 0.0
        self._refresh_focus_labels()
        self.statusBar().showMessage(self.tr(
            "Best focus values reset: the next readings start a fresh "
            "comparison."), 6000)

    # @args: none
    # @return: the numeric focus metrics of the last reading, for the saved step
    def _focus_metric_numbers(self) -> dict[str, float]:
        latest = self._focus_watcher.latest()
        if latest is None:
            return {}
        numbers = {}
        for key, value in latest.as_dict().items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numbers[key] = float(value)
        return numbers

    # @args: name - the metric label; text - its value and best; muted - no data
    def _set_metric_label(self, name: str, text: str, muted: bool) -> None:
        label = self.findChild(QLabel, name)
        if label is None:
            return
        label.setText(text)
        label.setProperty("state", "muted" if muted else "")
        label.style().unpolish(label)
        label.style().polish(label)

    # @args: none. Clears the focus readings when the camera closes
    def _reset_focus_readings(self) -> None:
        self._focus_watcher.reset()
        self._last_focus_s = 0.0
        self._refresh_focus_labels()

    # -------------------------------------------------------- line identification

    # @args: checked - the toolbar check changed
    def _toggle_identification(self, checked: bool) -> None:
        if self.spectrum_frame is not None:
            self.spectrum_frame.setVisible(bool(checked))
        if not checked:
            self._identify_timer.stop()
            self._identify_generation += 1
            return
        self._identify_generation += 1
        self.spectrum_panel.show_waiting()
        self._identify_timer.start()
        self._identify_now()

    # @args: none
    # @return: the [spectrum] settings plus the current band and generation
    def _spectrum_params(self) -> dict:
        return {
            "dispersion": float(self.session.value(
                "spectrum", "dispersion_angstrom_px")),
            "target_wavelength": float(self.session.value(
                "spectrum", "target_wavelength_angstrom")),
            "flip": bool(self.session.value("spectrum", "flip")),
            "tolerance": float(self.session.value(
                "spectrum", "line_tolerance_angstrom")),
            "min_confidence": float(self.session.value(
                "spectrum", "min_confidence")),
            "anchor_search_px": float(self.session.value(
                "spectrum", "anchor_search_px")),
            "band_y": int(self.session.roi.band[1]),
            "generation": self._identify_generation,
        }

    # @args: none. One 2 Hz tick: copy the profile here, match it in the worker
    def _identify_now(self) -> None:
        if self.identify_check is None or not self.identify_check.isChecked():
            return
        params = self._spectrum_params()
        if params["dispersion"] <= 0:
            self.spectrum_panel.show_no_dispersion()
            return
        harness = self.session.harness
        frame = harness.last_frame() if harness is not None else None
        if frame is None:
            self.spectrum_panel.show_no_spectrum()
            return
        try:
            profile = dispersion_profile(frame, self.session.roi.band)
        except (AttributeError, TypeError, ValueError):
            self.spectrum_panel.show_no_spectrum()
            return
        if profile.size < 3:
            self.spectrum_panel.show_reason("empty_profile")
            return
        # The profile is a new 1D array, not the live frame buffer: the worker
        # can take all the time it needs without touching a recycled frame.
        self._identify_generation += 1
        params["generation"] = self._identify_generation
        self._identify_worker.submit(profile, params)

    # @args: result - an IdentificationResult, or None if the worker failed
    #        params - the settings that produced it
    def _on_identification(self, result, params: dict) -> None:
        if self.identify_check is None or not self.identify_check.isChecked():
            return
        if int(params.get("generation", -1)) != self._identify_generation:
            return
        if result is None:
            self.spectrum_panel.show_reason("engine_error")
            return
        self.spectrum_panel.show_result(
            result, int(params.get("band_y", 0)),
            float(params.get("min_confidence", 0.35)))

    # @args: none. Called after Settings closes: re-read the [spectrum] keys
    def _refresh_spectrum_settings(self) -> None:
        if self.identify_check is None or not self.identify_check.isChecked():
            return
        self._identify_generation += 1
        params = self._spectrum_params()
        if params["dispersion"] <= 0:
            self.spectrum_panel.show_no_dispersion()
            return
        self.spectrum_panel.show_waiting()
        self._identify_now()

    # ---------------------------------------------------------------- ROI



    # @args: none. Applies the fields, saving the values silently
    def apply_roi(self) -> None:
        if not self.session.has_camera():
            self.statusBar().showMessage(self.tr(
                "Open a camera before applying a ROI: the rectangle is sent to "
                "the hardware, not only stored."), 8000)
            return
        previous = (self.session.roi.capture, self.session.roi.band)
        warnings = self.roi_editor.apply()
        errors = [warning for warning in warnings
                  if warning.severity.value == "error"]
        if errors:
            self.statusBar().showMessage(self.tr(
                "The ROI was not applied: the warnings in the step explain what "
                "the camera would reject."), 8000)
            return
        if not self.session.apply_roi():
            # The camera refused it. Put the applied model back so the fields
            # keep describing what the hardware is really delivering.
            self.session.set_roi(previous[0], previous[1], persist=False)
            self.roi_editor.reload()
            return
        self._prepared = False
        self._plan = None
        self._update_plan_summary()
        self._update_scan_enabled()
        self.session.complete_step(
            "roi", tilt_deg=float(self.session.roi.tilt_deg),
            tilt_px=float(self.session.roi.tilt_px),
            capture_width=float(self.session.roi.capture[2]),
            capture_height=float(self.session.roi.capture[3]))
        x, y, width, height = self.session.roi.capture
        message = self.tr(
            "ROI applied to the camera: {width} x {height} px at ({x}, {y}). "
            "The strip sets the frame rate and the SER size.").format(
                width=width, height=height, x=x, y=y)
        if self._profiles.available and not self._active_profile:
            message += self.tr(
                " No active profile: the ROI preset was not saved.")
        self.statusBar().showMessage(message, 9000)

    # @args: none. Runs the tilt meter and reports it
    def measure_tilt(self) -> None:
        self.roi_editor.measure_tilt()
        tilt = self.session.last_tilt()
        if tilt is None:
            self.statusBar().showMessage(self.tr(
                "The tilt meter is not available in this build; the measured tilt "
                "stays at its last value."), 7000)
        elif getattr(tilt, "ok", False):
            self.statusBar().showMessage(self.tr(
                "Tilt measured: {deg:.2f} deg, {px:.1f} px of drift. The ROI must "
                "be tall enough to hold the band plus this drift.").format(
                    deg=float(tilt.tilt_deg), px=float(tilt.tilt_px)), 9000)

    # @args: none. Asks for a name and stores the preset in the profile
    def save_preset(self) -> None:
        if self._profiles.available and not self._active_profile:
            self.statusBar().showMessage(self.tr(
                "There is no active profile: save one in the top bar before "
                "saving a preset."), 8000)
            return
        name, accepted = QInputDialog.getText(
            self, self.tr("Save ROI preset"),
            self.tr("Name for this preset:"),
            text=self.tr("default"))
        if not accepted or not name.strip():
            return
        # Save what is on screen, not the last applied rectangle: the observer
        # may be saving a preset before pressing Apply.
        capture, band = self.roi_editor.rectangles()
        self.session.save_preset(name.strip(), capture, band)
        self.roi_editor.reload_presets()
        self.statusBar().showMessage(self.tr(
            "Preset '{name}' saved with the profile.").format(name=name.strip()),
            5000)

    # ---------------------------------------------------------------- scan

    # @args: none. Enables the scan action only when the ROI is scannable
    def _update_scan_enabled(self) -> None:
        button = self.findChild(QPushButton, "scanPrimaryButton")
        if button is None:
            return
        # Check the rectangles as typed, not the last applied ones: the observer
        # is still editing and the action must react to what is on screen.
        warnings = self.roi_editor.current_warnings()
        broken = any(warning.severity.value == "error" for warning in warnings)
        typed_capture, typed_band = self.roi_editor.rectangles()
        dirty = (typed_capture != self.session.roi.capture
                 or typed_band != self.session.roi.band)
        ready = self._prepared and self.session.has_camera()
        button.setEnabled(not broken and not dirty and not self._busy_scan and ready)
        if broken:
            button.setToolTip(self.tr(
                "The ROI cannot be scanned until the error in the ROI step is "
                "fixed."))
        elif dirty:
            button.setToolTip(self.tr(
                "Press Apply this ROI first: the camera still has the previous "
                "rectangle, and a scan of the wrong strip wastes the take."))
        elif not self.session.has_camera():
            button.setToolTip(self.tr(
                "Open a camera in the camera panel before starting the scan."))
        elif not self._prepared:
            button.setToolTip(self.tr(
                "Press Prepare first: it centres the Sun and calibrates the "
                "sweep rate, and the scan uses that plan."))
        else:
            button.setToolTip(self.tr(
                "Runs the cycles in order. Every row is a SER file in the session "
                "folder; stopping keeps the frames already written."))

    # @args: none. A ROI edit invalidates the prepared plan
    def _roi_edited(self) -> None:
        self._prepared = False
        self._plan = None
        self._update_plan_summary()
        self._update_scan_enabled()

    # @args: none. Runs the preparation inside the Scanning step
    def prepare_scan(self) -> None:
        if not self.session.has_camera():
            self.statusBar().showMessage(self.tr(
                "Open a camera first: the preparation needs frames and a mount."),
                8000)
            return
        self._prepared = False
        self._enable("prepareButton", False)
        self._update_scan_enabled()
        self._set_label("scanStatusValue",
                        self.tr("Preparing: centring the Sun and calibrating "
                                "the sweep rate..."), "warning")
        if not self.session.prepare_scan():
            self._enable("prepareButton", True)
            self.statusBar().showMessage(self.tr(
                "The preparation could not start. Check the camera, the mount "
                "and that the ROI has been applied."), 9000)

    # @args: status - a shg PrepareStatus
    def _on_prepare_status(self, status) -> None:
        progress = int(float(status.progress) * 100)
        if status.phase.value == "fine_center":
            text = self.tr(
                "Centring the Sun: {progress}%. Dec error {dec} arcsec; close to "
                "zero means the slit crosses the middle of the disk.").format(
                    progress=progress,
                    dec=round(float(status.dec_offset_arcsec or 0.0), 1))
        else:
            rate = status.rate_arcsec_s
            text = self.tr(
                "Calibrating the sweep rate: {progress}%. The rate is what turns "
                "time into arcseconds across the disk.").format(progress=progress)
            if rate is not None:
                text += self.tr(" Rate so far: {rate:.2f} arcsec/s.").format(
                    rate=float(rate))
        self._set_label("scanStatusValue", text, "warning")

    # @args: result - a shg PrepareResult
    def _on_prepare_finished(self, result) -> None:
        self._enable("prepareButton", True)
        self._prepared = bool(getattr(result, "ok", False))
        if self._prepared:
            self._set_label("scanStatusValue", self.tr(
                "Ready: Dec error {dec:.1f} arcsec, sweep rate {rate:.2f} "
                "arcsec/s. The error is the Sun's distance from the slit centre; "
                "it should be near zero.").format(
                    dec=float(result.dec_offset_arcsec),
                    rate=float(result.rate_arcsec_s)), "ok")
        else:
            self._set_label("scanStatusValue", self.tr(
                "Preparation failed: {reason}.").format(
                    reason=self._reason_text(result.reason_code)), "error")
        self._update_scan_enabled()

    # @args: none. Starts the simulated run (the real engine is wired the same)
    def start_scan(self) -> None:
        if self.session.roi_has_errors():
            self.statusBar().showMessage(self.tr(
                "The scan did not start: the ROI has an error. Fix it in the ROI "
                "step; the message there says what to change."), 9000)
            return
        if not self._prepared:
            self.statusBar().showMessage(self.tr(
                "Press Prepare first: the scan needs the centred Sun and the "
                "sweep rate from the plan."), 8000)
            return
        cycles = self.findChild(QSpinBox, "planCyclesSpin")
        n_cycles = cycles.value() if cycles is not None else 1
        recenter = self.findChild(QCheckBox, "recenterCheck")
        self.recon.clear()
        self._set_label("reconMessage",
                        self.tr("Waiting for the first frames..."), "muted")
        self.scan_view.set_progress(0.0, 0)
        self.scan_view.set_result("")
        # The strip that carries the captured disk opens by itself: the observer
        # needs it while the sweep runs, and it folds again when they choose
        # (ADR-026).
        self._set_strip("scanStripToggle", "scanBody", True)
        # While a scan runs the progress strip is the point of watching: the
        # header cannot fold it away until the run ends.
        self._enable("scanStripToggle", False)
        self._update_scan_strip_status(0, 0, n_cycles)
        self._busy_scan = True
        self._cycle = 0
        self._cycle_total = n_cycles
        self._enable("scanPrimaryButton", False)
        self._enable("scanPauseButton", True)
        self._enable("scanAbortButton", True)
        self._set_label("scanStatusValue", self.tr("Running..."), "warning")
        if not self.session.start_scan(
                n_cycles, bool(recenter is not None and recenter.isChecked())):
            self._busy_scan = False
            self._enable("scanPauseButton", False)
            self._enable("scanAbortButton", False)
            self._update_scan_enabled()
            self.statusBar().showMessage(self.tr(
                "The scan did not start. Prepare it again and check the log."),
                9000)
            return
        self.statusBar().showMessage(self.tr(
            "Scan started. The shaded part of the disk is already captured; the "
            "percentage is of the planned sweep, so 100% means the plan finished."),
            8000)

    # @args: cycle, total - which cycle began
    def _on_cycle_started(self, cycle: int, total: int) -> None:
        self._cycle = cycle
        self._cycle_total = total
        self.scan_view.set_progress(0.0, 0)
        self.recon.clear()
        self._set_label("reconMessage",
                        self.tr("Waiting for the first frames..."), "muted")
        self._update_scan_strip_status(0, cycle, total)
        self._set_label("scanStatusValue", self.tr(
            "Cycle {cycle} of {total}: sweeping the slit across the disk..."
        ).format(cycle=cycle, total=total), "warning")

    # @args: percent - of the planned sweep; cycle, total - current cycle
    def _update_scan_strip_status(self, percent: int, cycle: int = 0,
                                  total: int = 0) -> None:
        if cycle and total:
            text = self.tr("Cycle {cycle} of {total}, {percent}%").format(
                cycle=cycle, total=total, percent=int(percent))
        elif percent:
            text = self.tr("{percent}% of the planned sweep").format(
                percent=int(percent))
        else:
            text = self.tr("Starting")
        self._set_label("scanStripStatus", text, "warning")

    # @args: phase - "recentring" or "scanning"
    def _on_scan_phase(self, phase: str) -> None:
        if phase == "recentring":
            self._set_label("scanStatusValue", self.tr(
                "Recentring the Sun before the next cycle..."), "warning")
            self._set_label("scanStripStatus", self.tr("Recentring"), "warning")
        elif phase == "scanning":
            self._set_label("scanStatusValue", self.tr("Sweeping..."), "warning")

    # @args: progress - a shg ScanProgress
    def _on_scan_progress(self, progress) -> None:
        self.scan_view.set_progress_from(progress)
        bar = self.findChild(QWidget, "scanProgressBar")
        if bar is not None:
            bar.setValue(int(progress.progress * 100))
        percent = int(progress.progress * 100)
        cycle = getattr(self, "_cycle", 0) or 1
        total_cycles = getattr(self, "_cycle_total", 0) or 1
        self._update_scan_strip_status(percent, cycle, total_cycles)
        self._set_label("scanStatusValue", self.tr(
            "Cycle {cycle} of {cycles}, row {row}: {percent}% complete. Dec error "
            "{dec:.1f} arcsec; a large value means part of the disk is outside "
            "the sweep.").format(cycle=cycle, cycles=total_cycles,
                                 row=progress.row + 1, percent=percent,
                                 dec=float(progress.dec_error_arcsec)),
            "warning")
        total = progress.frames_written + progress.frames_dropped
        dropped_pct = (progress.frames_dropped / total * 100.0) if total else 0.0
        self._set_label("scanDroppedValue", self.tr(
            "Dropped frames: {dropped} of {total} ({percent:.2f}%). Each one is a "
            "gap in the SER.").format(
                dropped=progress.frames_dropped, total=total,
                percent=dropped_pct),
            "ok" if dropped_pct <= 0.1 else "error")
        pause = self.findChild(QPushButton, "scanPauseButton")
        if pause is not None:
            pause.setText(self.tr("Resume") if
                          progress.state.value == "paused" else self.tr("Pause"))

    # @args: result - a shg.recon.ReconResult
    def _on_recon_result(self, result) -> None:
        reason = str(getattr(result, "reason_code", ""))
        image = getattr(result, "image", None)
        ok = bool(getattr(result, "ok", False))
        if ok and image is not None and getattr(image, "size", 0):
            self.recon.set_image(image)
            text = self.tr(
                "Quick recon: {frames} frames, {rows} row(s). Light preview, "
                "not for measurement.").format(
                    frames=int(getattr(result, "frames_used", 0)),
                    rows=int(getattr(result, "rows", 0)))
            if reason == "low_contrast":
                text += " " + self.tr(
                    "Too little contrast to show a disk: the Sun may have been "
                    "off the slit.")
                state = "warning"
            else:
                state = "ok"
        else:
            self.recon.set_image(None)
            text = self._recon_reason(reason)
            state = "warning"
        self._set_label("reconMessage", text, state)

    # @args: reason - no_frames, band_empty, low_contrast or ""
    # @return: a sentence that says what happened and what to check
    def _recon_reason(self, reason: str) -> str:
        if reason == "no_frames":
            return self.tr(
                "No frames reached the preview. Start the scan and let it run "
                "for a few seconds.")
        if reason == "band_empty":
            return self.tr(
                "The spectral band has no pixels in the frames. Check the band "
                "in the ROI step.")
        if reason == "low_contrast":
            return self.tr(
                "The preview has too little contrast. The Sun may have been off "
                "the slit.")
        return self.tr("The preview could not be built from these frames.")

    # @args: result - a shg ScanResult
    def _on_scan_finished(self, result) -> None:
        self._busy_scan = False
        self._enable("scanPauseButton", False)
        self._enable("scanAbortButton", False)
        self._enable("scanStripToggle", True)
        self._update_scan_enabled()
        self.scan_view.set_result_from(result, self._planned_rows())
        text = self.tr("{frames} frames in {seconds:.0f} s. {reason}").format(
            frames=result.frames_written, seconds=float(result.duration_s),
            reason=self._result_reason(result))
        if result.status.value == "completed":
            text += self.tr(" Data folder: {folder}.").format(
                folder=str(self.session.folder))
            self._set_label("scanStripStatus", self.tr("Finished"), "ok")
        else:
            self._set_label("scanStripStatus", self.tr("Stopped"), "warning")
        self._set_label("scanResultValue", text,
                        "ok" if result.status.value == "completed" else "warning")
        if result.status.value == "completed":
            self.session.complete_step(
                "scan", frames_written=float(result.frames_written),
                frames_dropped=float(result.frames_dropped),
                duration_s=float(result.duration_s),
                dec_error_arcsec=float(result.dec_error_arcsec))
        if result.ser_paths:
            finished_text = self.tr(
                "Finished. The data folder holds the SER files and the log.")
        elif self.session.is_simulated():
            finished_text = self.tr(
                "Finished in the simulator: the SER recording is disabled in "
                "the simulation, so this run was a dry run.")
        else:
            finished_text = self.tr(
                "Finished without SER files: the log says why. The frames already "
                "written, if any, are kept.")
        self._set_label("scanStatusValue", finished_text,
                        "ok" if result.status.value == "completed" else "warning")
        if result.ser_paths:
            self.statusBar().showMessage(self.tr(
                "Data written to {folder}").format(
                    folder=str(Path(result.ser_paths[0]).parent)), 9000)

    # @args: none. Pause and resume share one button, as a scan does
    def toggle_scan_pause(self) -> None:
        pause = self.findChild(QPushButton, "scanPauseButton")
        if pause is not None and pause.text() == self.tr("Resume"):
            self.session.resume_scan()
            pause.setText(self.tr("Pause"))
        else:
            self.session.pause_scan()
            if pause is not None:
                pause.setText(self.tr("Resume"))

    # @args: none. Stops the run; the frames already written are kept
    def abort_scan(self) -> None:
        self.session.abort_scan()

    # @args: result - a ScanResult
    # @return: a short sentence for the result line
    def _result_reason(self, result) -> str:
        if result.status.value == "completed":
            if not result.ser_paths:
                return self.tr("Simulator run, no file written.")
            return self.tr("Completed.")
        if result.status.value == "aborted":
            return self.tr("Stopped on purpose; the frames already written are kept.")
        return self.tr("Failed: {reason}.").format(
            reason=self._reason_text(result.reason_code))

    # @args: none
    # @return: the rows of the current plan
    def _planned_rows(self) -> int:
        mode = self.findChild(QComboBox, "planModeCombo")
        rows = self.findChild(QSpinBox, "planRowsSpin")
        if mode is not None and mode.currentData() == "mosaic" and rows is not None:
            return rows.value()
        return 1

    # ------------------------------------------------------------------ dialogs

    # @args: none. Settings, with its changes applied and saved
    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog
        before_language = str(self.session.value("general", "language"))
        dialog = SettingsDialog(self.session.settings, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.session.update_settings(dialog.values())
        if self.session.harness is not None:
            self.session.harness.latitude_deg = float(
                self.session.value("observatory", "latitude_deg"))
            self.session.harness.longitude_deg = float(
                self.session.value("observatory", "longitude_deg"))
        self.session.save_settings()
        if self.session.has_camera():
            # New exposure, binning or ROI values have to reach the camera.
            self.session.apply_roi()
        self._initial_fill()
        self.roi_editor.reload()
        self._sync_camera_panel()
        self._refresh_spectrum_settings()
        self.statusBar().showMessage(self.tr(
            "Settings saved. Every value has a default, so a partial file still "
            "starts the app."), 6000)
        if str(self.session.value("general", "language")) != before_language:
            self.statusBar().showMessage(self.tr(
                "Restart SolarScribe to apply the new language."), 9000)

    # @args: none. Sky calendar, Sun tab
    def open_sky_calendar(self) -> None:
        if self._calendar_dialog is None:
            self._calendar_dialog = SkyCalendarDialog(self.session.sun_info(), self)
            self._calendar_dialog.set_image_fetcher(None)
        else:
            self._calendar_dialog.set_sun_info(self.session.sun_info())
        self._calendar_dialog.show()
        self._calendar_dialog.raise_()

    # @args: none. ROI presets of the profile
    def open_roi_manager(self) -> None:
        if self._roi_manager_dialog is None:
            self._roi_manager_dialog = RoiManagerDialog(
                self.session.profile.roi_presets, self)
            self._roi_manager_dialog.presetChosen.connect(self._preset_chosen)
        else:
            self._roi_manager_dialog.set_presets(self.session.profile.roi_presets)
        self._roi_manager_dialog.show()
        self._roi_manager_dialog.raise_()

    # @args: preset - the preset chosen in the manager
    def _preset_chosen(self, preset) -> None:
        # Load into the fields, not into the applied model: the manager says it
        # does not touch the camera, and this is what keeps that promise.
        self.roi_editor.load_preset(preset)
        self.select_step("roi")
        self.statusBar().showMessage(self.tr(
            "Preset '{name}' copied into the ROI step. Apply it there when you "
            "are ready.").format(name=preset.name), 7000)

    # @args: none. In-app log viewer
    def open_logs(self) -> None:
        if self._logs_dialog is None:
            self._logs_dialog = LogsViewer(
                paths.log_dir() / "solarscribe.log", self)
        else:
            self._logs_dialog.reload()
        self._logs_dialog.show()
        self._logs_dialog.raise_()

    # @args: none. A plain report of the environment and the session
    def show_diagnostics(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("Device diagnostics"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(self.tr(
            "The report below says what this build can and cannot reach. It is "
            "the first thing to attach to a bug report."))
        box.setDetailedText(self._diagnostics_text())
        box.exec()

    # @args: none
    # @return: the diagnostics report
    def _diagnostics_text(self) -> str:
        roi = self.session.roi
        info = self.session.camera_info()
        if self.session.is_simulated():
            camera = self.tr("Simulator (no hardware)")
        elif info is not None:
            camera = f"{getattr(info, 'vendor', '')} {getattr(info, 'model', '')}"
        else:
            camera = self.tr("not open")
        mount = self.tr("Simulator (no hardware)") if self.session.demo_mount() \
            else self.tr("not connected")
        return "\n".join([
            self.tr("SolarScribe {version}").format(
                version=solarscribe.__version__),
            self.tr("Python {version} ({platform})").format(
                version=platform.python_version(), platform=platform.platform()),
            self.tr("PySide6 {version}").format(version=PySide6.__version__),
            self.tr("Settings: {path}").format(path=paths.settings_path()),
            self.tr("Profile: {path}").format(path=paths.profile_path()),
            self.tr("Data folder: {path}").format(path=self.session.folder),
            self.tr("Camera: {state}").format(state=camera),
            self.tr("Mount: {state}").format(state=mount),
            self.tr("ROI capture: {rect}").format(rect=str(roi.capture)),
            self.tr("Spectral band: {rect}").format(rect=str(roi.band)),
            self.tr("Tilt: {deg:.2f} deg, {px:.1f} px").format(
                deg=float(roi.tilt_deg), px=float(roi.tilt_px)),
            self.tr("Spectrum: {target:.2f} Å target, {dispersion:.4f} Å/px, "
                    "flip {flip}").format(
                        target=float(self.session.value(
                            "spectrum", "target_wavelength_angstrom")),
                        dispersion=float(self.session.value(
                            "spectrum", "dispersion_angstrom_px")),
                        flip=bool(self.session.value("spectrum", "flip"))),
            self.tr("Run 'python -m solarscribe --diagnostics' for the backend "
                    "and device list."),
        ])

    # @args: none. The how-to in four sentences
    def show_quick_start(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("Quick start"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(self.tr(
            "1. Open the camera in the camera panel on the right.\n"
            "2. Find the Sun: connect the mount and press Point at the Sun and "
            "centre.\n"
            "3. Focus: sharpen the three focusers and measure the slit tilt; "
            "rotate the slit until it is parallel to Dec.\n"
            "4. ROI: drag the spectral band on the video, type the capture strip "
            "and press Apply this ROI.\n"
            "5. Scanning: prepare, then start. The quick recon tells you whether "
            "the take went well; the post-processing stays external."))
        box.exec()

    # @args: none. Version, licence and the sibling project
    def show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(self.tr("About SolarScribe"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(self.tr(
            "SolarScribe {version}\n\nCapture for the solar spectroheliograph. "
            "It records SER files and logs for the post-processing; it does not "
            "post-process.\n\nGPL v3. Sibling of NightScribe, with its patterns "
            "and its dark theme.").format(version=solarscribe.__version__))
        box.exec()

    # ------------------------------------------------------------- file actions

    # @args: none. Starts a new session folder and resets the five steps
    def new_session(self) -> None:
        self.session.new_session()
        self.recon.clear()
        self.scan_view.set_progress(0.0)
        self.scan_view.set_result("")
        self._reset_live_readings()
        self._initial_fill()
        self.statusBar().showMessage(self.tr(
            "New data folder: {folder}").format(folder=str(self.session.folder)), 6000)

    # @args: none. Clears the readings that belonged to the previous run: the
    #        step state is loaded or reset, but a live "Aligned" from yesterday
    #        would be a lie
    def _reset_live_readings(self) -> None:
        self._set_label("sunStateValue", self.tr("Not measured yet"), "muted")
        self._set_label("decErrorValue", self.tr("Not measured yet"), "muted")
        self._set_label("deadZoneValue", self.tr("Not measured yet"), "muted")
        self._set_label("polarStateValue", self.tr("Not started"), "muted")
        self._set_label("polarAzValue", self.tr("Not measured yet"), "muted")
        self._set_label("polarAltValue", self.tr("Not measured yet"), "muted")
        self._set_label("scanStatusValue", self.tr("Not started."), "muted")
        self._set_label("scanDroppedValue", self.tr(
            "Dropped frames: none so far. Every dropped frame is a gap in the "
            "SER that the reconstruction has to bridge."), "muted")
        self._set_label("scanResultValue", self.tr(
            "When a scan finishes, its result and the data folder appear "
            "here."), "muted")
        self._set_label("scanStripStatus", self.tr("Idle"), "muted")
        self._set_label("histogramSaturation", self.tr("No frame yet"), "muted")
        self._reset_focus_readings()
        self._identify_generation += 1
        if self.identify_check is not None and self.identify_check.isChecked():
            self.spectrum_panel.show_no_spectrum()
        for name, value in (("polarProgress", 0), ("scanProgressBar", 0)):
            bar = self.findChild(QWidget, name)
            if bar is not None:
                bar.setValue(value)
        self.recon.clear()
        self._set_label("reconMessage",
                        self.tr("The preview appears as the scan advances."),
                        "muted")
        self._enable("polarSecondButton", False)
        self._enable("scanPauseButton", False)
        self._enable("scanAbortButton", False)
        self._enable("scanStripToggle", True)
        self._busy_scan = False
        self._busy_center = False
        self._prepared = False
        self._plan = None
        self._cycle = 0
        self._cycle_total = 0
        self._enable("findPrimaryButton", True)
        self._update_scan_enabled()

    # @args: none. Opens another session folder, silently restoring its steps
    def open_session(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Open data folder"), str(self.session.folder))
        if not folder:
            return
        loaded = Session.load(folder, demo=self.session.demo, autosave=True,
                              settings=self.session.settings,
                              settings_path=self.session.settings_file(),
                              profile=self.session.profile,
                              profile_path=self.session.profile_file())
        self.session.adopt(loaded)
        self._reset_live_readings()
        self._initial_fill()
        self.statusBar().showMessage(self.tr(
            "Data folder opened: {folder}. The steps are as you left them.").format(
                folder=folder), 7000)

    # @args: none. Opens the session folder in the file manager
    def open_session_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.folder)))

    # ------------------------------------------------------------------ helpers

    # @args: name - label object name; text - its text; state - QSS state
    def _set_label(self, name: str, text: str, state: str = "muted") -> None:
        label = self.findChild(QLabel, name)
        if label is None:
            return
        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)

    # @args: name - button object name; enabled - whether it is usable
    def _enable(self, name: str, enabled: bool) -> None:
        button = self.findChild(QWidget, name)
        if button is not None:
            button.setEnabled(bool(enabled))

    # @args: what - the module that is missing
    def _say_unavailable(self, what: str) -> None:
        self.statusBar().showMessage(self.tr(
            "{what} is not available in this build. The simulator covers the "
            "interface until the engine lands.").format(what=what), 8000)

    # @args: none
    # @return: (mount, name) from the device layer, or None when it is absent or
    #          finds nothing. Discovery talks to the OS, so this is a deliberate
    #          click, never a startup cost (ARCHITECTURE 2.1)
    def _discover_mount(self):
        try:
            mounts = self.device_manager.mounts()
            if not mounts:
                return None
            info = mounts[0]
            mount = self.device_manager.open_mount(info.mount_id)
        except Exception as error:  # noqa: BLE001 - discovery may fail anywhere
            self.statusBar().showMessage(
                self.tr("Device discovery failed: {error}").format(error=error),
                8000)
            return None
        harness = self.session.harness
        if harness is not None:
            if hasattr(harness, "use_mount"):
                harness.use_mount(mount)
            elif hasattr(harness, "adopt_mount"):
                harness.adopt_mount(mount)
        return mount, info.name

    # @args: code - a stable reason code from shg
    # @return: a plain sentence, never the raw code (ADR-014)
    def _reason_text(self, code: str) -> str:
        if code == "no_limb":
            return self.tr("the limb was not found; check that the Sun is on the slit")
        if code == "sun_lost":
            return self.tr("the Sun left the slit; recentre and try again")
        if code == "calibration_failed":
            return self.tr("the sweep rate did not converge; check the mount rate")
        if code == "mount_no_rate":
            return self.tr("the mount cannot move by rate; the scan needs it")
        if code == "disk_full":
            return self.tr("the disk filled up; free space and retry")
        if code == "device_lost":
            return self.tr("a device disconnected; reconnect it and retry")
        if code == "stalled":
            return self.tr("frames stopped arriving; the SER is preserved")
        if code == "aborted":
            return self.tr("it was stopped on purpose")
        if code == "no_edge":
            return self.tr("the slit edge was not found")
        if code == "low_contrast":
            return self.tr("the image has too little contrast for a measurement")
        if code == "max_iterations":
            return self.tr("the centring did not converge; move the Sun closer "
                           "with the telescope panel and try again")
        if code == "not_ready":
            return self.tr("the camera or the stream is not ready")
        if code == "optics_missing":
            return self.tr("the profile has no focal length or pixel size, so the "
                           "slit geometry is unknown")
        if code == "plan_failed":
            return self.tr("the scan plan could not be computed; check the ROI "
                           "and the mount")
        if code == "not_prepared":
            return self.tr("the scan was not prepared; run the preparation first")
        if code == "no_camera":
            return self.tr("there is no camera connected")
        if code in ("start_failed", "engine_error"):
            return self.tr("the engine stopped unexpectedly; the log has the "
                           "technical detail")
        if code in ("param_rejected", "roi_rejected"):
            return self.tr("the camera rejected a capture setting or the ROI")
        return self.tr("the engine reported a problem; the log says which")

    # @args: none. Re-reads the settings into the plan controls
    def _initial_fill(self) -> None:
        self._prepared = False
        self._plan = None
        self._cycle = 0
        self._cycle_total = 0
        mode = self.findChild(QComboBox, "planModeCombo")
        stored_rows = max(1, int(self.session.value("scan", "rows")))
        if mode is not None:
            mode.blockSignals(True)
            mode.setCurrentIndex(1 if stored_rows > 1 else 0)
            mode.blockSignals(False)
        cycles = self.findChild(QSpinBox, "planCyclesSpin")
        if cycles is not None:
            cycles.blockSignals(True)
            cycles.setValue(max(1, int(self.session.value("scan", "cycles"))))
            cycles.blockSignals(False)
        rows = self.findChild(QSpinBox, "planRowsSpin")
        if rows is not None:
            rows.blockSignals(True)
            rows.setValue(max(1, int(self.session.value("scan", "rows"))))
            rows.blockSignals(False)
        self._plan_changed()

    # @args: event - close: stop the timers and save the session state
    def closeEvent(self, event) -> None:
        # Silent autosave at the last possible moment: a laptop closing must not
        # lose the step the observer was on (ADR-011). The timers stop first so
        # a queued frame cannot repaint a window that is going away.
        self._display_timer.stop()
        self._health_timer.stop()
        self._identify_timer.stop()
        self._identify_worker.stop()
        self.telescope.stop_polling()
        if hasattr(self, "camera_panel"):
            self.camera_panel.shutdown()
        harness = self.session.harness
        if harness is not None:
            if hasattr(harness, "shutdown"):
                harness.shutdown()
            else:
                harness.stop()
        try:
            self.session.save()
        except OSError:
            pass
        super().closeEvent(event)
