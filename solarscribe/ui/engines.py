############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui engine harness module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The bridge between the real engines and the window.
#
# The UI simulator used to paint frames and fake progress. This harness replaces
# that path with the real pipeline:
#   - devices.sim.SimCamera through the Camera contract, for the fallback;
#   - capture.engine.CaptureEngineImpl, the real stream, counters and SER writer;
#   - shg.centering.SunCenteringImpl for the Find-the-Sun step;
#   - shg.engine.ScanEngineImpl for prepare and the sweep;
#   - ui.adapters.RowRecorderAdapter and DisplayBridge for the two ports.
#
# The photons come from the first-class devices.sim.SimCamera with
# pattern="solar", bound to the mount. The tests and the bench use the same
# simulator, so the window is not a second implementation. That pattern models
# the chord, the limb darkening, the spectral lines and the Dec shift; it does
# not model a tilted slit line, so the tilt meter reads about 0.0 on the
# simulator. The shg tests exercise the tilt maths on their own fixtures; the
# window shows the honest 0.0 instead of inventing a tilt.
#
# Long operations (centring, preparation, a scan) block, so each runs in a
# QThread. The capture callbacks never touch a widget: they land in a one-frame
# mailbox and a GUI timer paints the newest frame (ARCHITECTURE 4).

from __future__ import annotations

import logging
import math
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from solarscribe.capture.abc import CaptureParams, RoiModel
from solarscribe.capture.engine import CaptureEngineImpl
from solarscribe.config import store
from solarscribe.devices.abc import Camera, DeviceError, Mount
from solarscribe.devices.sim.camera import SimCamera
from solarscribe.devices.sim.frame import SolarPattern
from solarscribe.devices.sim.mount import SimMount
from solarscribe.shg.abc import (
    CenteringResult,
    DecCenterMethod,
    PolarSample,
    PrepareResult,
    ScanEngine,
    ScanProgress,
    ScanResult,
    ScanStatus,
)
from solarscribe.shg.centering import SunCenteringImpl
from solarscribe.shg.engine import ScanEngineImpl
from solarscribe.shg.ephemeris import solar_position_now
from solarscribe.shg.geometry import (
    effective_slit_arcsec, pixel_scale_arcsec_px,
)
from solarscribe.shg.polar import PolarAlignmentSession
from solarscribe.shg.recon import ReconResult, quick_recon

from .adapters import DisplayBridge, RowRecorderAdapter

__all__ = ["EngineHarness"]

# The simulator frame rate: high enough that the scan has frames to measure,
# low enough that a 3480 x 248 scene render does not eat the laptop. The real
# camera proves the 120 fps budget; the simulator only has to be honest about
# its own rate.
SIM_FPS = 20.0

# The simulator uses a fixed sweep rate instead of a real calibration: the
# calibration sweep needs several seconds and the scene is not a radiometric
# instrument. It is labelled as the simulator rate in the plan summary.
SIM_RATE_ARCSEC_S = 1200.0


# @args: fn - the blocking work; receives an emit(object) callback
# @return: a runnable task. Signals are queued to the GUI thread
class _Task(QThread):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    # @args: none
    def run(self) -> None:
        try:
            result = self._fn(self.progress.emit)
        except Exception as error:  # noqa: BLE001 - reported to the window
            self.failed.emit(f"{type(error).__name__}: {error}")
            return
        self.done.emit(result)


class EngineHarness(QObject):
    # The object the window talks to. It exposes the same signals the UI demo
    # used, so the window did not have to learn a second vocabulary.
    frameReady = Signal(object)
    countersChanged = Signal(object)
    cameraChanged = Signal(object, bool)      # CameraInfo, simulated
    rateEstimate = Signal(float, float)       # fps, MB/s
    engineError = Signal(str)                 # stable reason code
    message = Signal(str)
    centeringProgress = Signal(object)        # CenteringStatus
    centeringFinished = Signal(object)        # CenteringResult
    prepareStatus = Signal(object)            # PrepareStatus
    prepareFinished = Signal(object)          # PrepareResult
    planReady = Signal(object)                # ScanPlan
    scanProgress = Signal(object)             # ScanProgress
    scanFinished = Signal(object)             # ScanResult
    cycleStarted = Signal(int, int)           # cycle, total
    scanPhase = Signal(str)                   # "recentring" | "scanning"
    reconResult = Signal(object)              # ReconResult from shg.recon
    polarProgress = Signal(float, object)
    polarFinished = Signal(object)

    def __init__(self, *, folder: Path, settings, profile, roi: RoiModel,
                 simulated: bool = True, camera: Camera | None = None,
                 mount: Mount | None = None, parent=None) -> None:
        super().__init__(parent)
        self.folder = Path(folder)
        self.settings = settings
        self.profile = profile
        self.roi = roi
        self.simulated = bool(simulated)
        self.engine = CaptureEngineImpl(start_timeout_s=5.0)
        self.bridge = DisplayBridge()
        self.engine.on_frame(self.bridge)
        self.camera: Camera | None = None
        self.camera_info = None
        self._live_camera: Camera | None = None
        self._last_frame = None
        self._last_counters = None
        self._task: _Task | None = None
        self._busy_center = False
        self._busy_prepare = False
        self._busy_scan = False
        self._scanning = False
        self._recon_rows: list[list[np.ndarray]] = []
        self._recon_row = 0
        self._recon_frames = 0
        self._next_recon_at = 0.0
        self._scan: ScanEngine | None = None
        self._plan = None
        self._config = None
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(30)
        self._frame_timer.timeout.connect(self._pump)
        self._counter_timer = QTimer(self)
        self._counter_timer.setInterval(400)
        self._counter_timer.timeout.connect(self._publish_counters)
        self._polar_timer = QTimer(self)
        self._polar_timer.setInterval(250)
        self._polar_timer.timeout.connect(self._polar_tick)
        self._polar_session = None
        self._polar_samples: list[PolarSample] = []
        self._polar_index = 0
        self._polar_second = False
        self._polar_progress = 0.0
        self.latitude_deg = float(self._value("observatory", "latitude_deg"))
        self.longitude_deg = float(self._value("observatory", "longitude_deg"))

        if mount is None:
            mount = self._default_mount()
        self.mount = mount
        if camera is None and not simulated:
            # Deliberately empty: --no-demo starts with no camera, and the
            # camera panel is the way to attach one. The telescope still has a
            # simulator mount, so the panel is usable.
            self.camera = None
            self.camera_info = None
            self._live_camera = None
            return
        if camera is None:
            camera, simulated = self._default_camera()
        self.simulated = bool(simulated)
        self._install_camera(camera, self.camera_info or camera.info())

    # @args: section, name - a schema key
    # @return: its value
    def _value(self, section: str, name: str):
        return self.settings.get(section, name)

    # @args: section, name - a key that may not be in this schema version;
    #        default - the fallback
    # @return: the value, or the fallback for a key the file does not have
    def _value_or(self, section: str, name: str, default):
        try:
            return self.settings.get(section, name)
        except KeyError:
            return default

    # @args: none
    # @return: a SimMount parked 120 arcsec off the Sun in Dec
    def _default_mount(self) -> SimMount:
        sun = solar_position_now(self.latitude_deg, self.longitude_deg)
        mount = SimMount(ra_hours=sun.ra_hours,
                         dec_deg=sun.dec_deg - 120.0 / 3600.0)
        mount.connect()
        return mount

    # @args: none
    # @return: (SimCamera, True) sized to the ROI
    def _default_camera(self):
        # The first-class solar simulator, bound to the mount by _install_camera.
        # It models the chord, the limb darkening and the spectral lines with the
        # reference sensor; the ROI is a window inside it.
        sun = solar_position_now(self.latitude_deg, self.longitude_deg)
        scale = pixel_scale_arcsec_px(
            self.profile.telescope.focal_length_mm,
            self.profile.camera.pixel_size_um)
        solar = SolarPattern(
            sun_ra_hours=sun.ra_hours,
            sun_dec_deg=sun.dec_deg,
            solar_diameter_arcsec=sun.diameter_arcsec,
            slit_arcsec_px=scale,
            band_y=int(self.roi.band[1]),
            band_height=int(self.roi.band[3]),
        )
        camera = SimCamera(width=3480, height=248, fps=SIM_FPS,
                           pattern="solar", solar=solar)
        return camera, True

    # @args: camera - the camera; info - its identity
    def _install_camera(self, camera: Camera, info) -> None:
        self._live_camera = camera
        self.camera_info = info
        self.camera = camera
        if self.simulated and hasattr(camera, "bind_mount"):
            sun = solar_position_now(self.latitude_deg, self.longitude_deg)
            if hasattr(camera, "set_sun"):
                camera.set_sun(sun.ra_hours, sun.dec_deg)
            camera.bind_mount(self.mount)
        self.engine.configure(self.camera, self.roi, self._params())

    # @args: none
    # @return: CaptureParams from the INI
    def _params(self) -> CaptureParams:
        return CaptureParams(
            exposure_us=float(self._value("camera", "exposure_us")),
            gain=float(self._value("camera", "gain")),
            offset=float(self._value("camera", "offset")),
            binning=int(self._value("camera", "binning")),
            bit_depth=int(self._value("camera", "bit_depth")),
            readout=float(self._value("camera", "readout")),
            auto_exposure=bool(self._value("camera", "auto_exposure")),
            auto_exposure_target=float(
                self._value_or("camera", "auto_exposure_target", 0.25)),
            queue_budget_mb=float(self._value("capture", "queue_budget_mb")),
            stall_timeout_s=float(self._value("capture", "stall_timeout_s")),
        )

    # @args: none
    # @return: whether the capture engine is streaming
    def is_running(self) -> bool:
        return self.engine.is_running()

    # @args: none. Starts the stream and the GUI timers. Emits engineError when
    #        the camera cannot start instead of raising into the event loop
    def start(self) -> bool:
        if self.camera is None:
            self.engineError.emit("no_camera")
            return False
        try:
            self.engine.configure(self.camera, self.roi, self._params())
            self.engine.start()
        except DeviceError as error:
            self.engineError.emit(error.code or "start_failed")
            return False
        except Exception:  # noqa: BLE001
            self.engineError.emit("start_failed")
            return False
        self._frame_timer.start()
        self._counter_timer.start()
        fps, mb = self.estimate_rate(self.roi.capture[2], self.roi.capture[3])
        self.rateEstimate.emit(fps, mb)
        self.cameraChanged.emit(self.camera_info, self.simulated)
        return True

    # @args: none. Stops a running task, the stream and the timers
    def shutdown(self) -> None:
        if self._scan is not None:
            try:
                self._scan.abort()
            except Exception:  # noqa: BLE001
                pass
        task = self._task
        if task is not None and task.isRunning():
            task.requestInterruption()
            task.wait(3000)
        self._task = None
        self.stop()

    # @args: none. Stops the stream and the timers
    def stop(self) -> None:
        self._frame_timer.stop()
        self._counter_timer.stop()
        self._polar_timer.stop()
        try:
            self.engine.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:  # noqa: BLE001
                pass
        self._last_counters = self.engine.counters()

    # @args: frame - the frame to publish (tests use this without a stream)
    def push_frame(self) -> None:
        frame = self.bridge.take()
        if frame is None:
            return
        self._last_frame = frame
        self.frameReady.emit(frame)
        if self._scanning:
            self._accumulate_recon(frame)

    # @args: none. Pulls the newest frame from the mailbox
    def _pump(self) -> None:
        frame = self.bridge.take()
        if frame is None:
            return
        self._last_frame = frame
        self.frameReady.emit(frame)
        if self._scanning:
            self._accumulate_recon(frame)

    # @args: frame - the newest frame. Reduces the spectral band to a small 2D
    #        slice and appends it to the current row; the full frame is never
    #        kept, so a 120 fps scan does not grow without bound
    def _accumulate_recon(self, frame) -> None:
        if not self._recon_rows:
            self._recon_rows = [[]]
        try:
            band = frame.cut_roi(self.roi.band)
            array = np.frombuffer(band.data, dtype=band.dtype)
            array = array.reshape(band.height, band.width)
            step_y = max(1, band.height // 64)
            step_x = max(1, band.width // 256)
            small = np.ascontiguousarray(array[::step_y, ::step_x])
        except (AttributeError, ValueError, ZeroDivisionError):
            return
        self._recon_rows[-1].append(small)
        self._recon_frames += 1
        now = time.monotonic()
        if self._recon_frames >= 4 and now >= self._next_recon_at:
            self._next_recon_at = now + 1.0
            self._emit_recon(final=False)

    # @args: final - True at the end of the run
    # @return: none. Runs shg.quick_recon over the accumulated rows and emits
    #          the result; the window paints it and explains a failure reason
    def _emit_recon(self, final: bool = False) -> None:
        rows = [row for row in self._recon_rows if row]
        if not rows:
            self.reconResult.emit(ReconResult(
                False, np.zeros((0, 0), dtype=np.float32), 0, 0, 0, 0,
                "no_frames"))
            return
        try:
            result = quick_recon(rows, band=None, width=256, max_height=128)
        except Exception:  # noqa: BLE001 - the preview must not stop the scan
            result = ReconResult(False, np.zeros((0, 0), dtype=np.float32),
                                 0, 0, 0, 0, "no_frames")
        self.reconResult.emit(result)

    # @args: none. Publishes the live counters
    def _publish_counters(self) -> None:
        counters = self.engine.counters()
        self._last_counters = counters
        self.countersChanged.emit(counters)

    # @args: none
    # @return: the live counters
    def counters(self):
        return self.engine.counters()

    # @args: none
    # @return: the last frame seen by the GUI
    def last_frame(self):
        return self._last_frame

    # @args: none
    # @return: free space of the session disk in GB
    def free_gb(self) -> float:
        try:
            return shutil.disk_usage(self.folder).free / (1024 ** 3)
        except OSError:
            return 0.0

    # @args: width, height - the ROI
    # @return: (fps, MB/s) the real camera would need for this geometry
    def estimate_rate(self, width: int, height: int) -> tuple[float, float]:
        fps = float(self._value("capture", "target_fps"))
        mb = width * height * 2.0 * fps / 1e6
        return fps, mb

    # @args: none. Announces the rate to the ROI step
    def announce_rate(self, width: int, height: int) -> None:
        fps, mb = self.estimate_rate(width, height)
        self.rateEstimate.emit(fps, mb)

    # @args: camera - an opened or unopened Camera; info - its identity;
    #        simulated - True for the scene-rendered simulator; roi - the
    #        model to apply before the stream starts, so a preset that fits the
    #        new sensor is used from the first frame
    def use_camera(self, camera: Camera, info=None,
                   simulated: bool | None = None, roi=None) -> bool:
        self.stop()
        if self.camera is not None and self.camera is not camera:
            try:
                self.camera.close()
            except Exception:  # noqa: BLE001
                pass
        if roi is not None:
            self.roi = roi
        if simulated is None:
            simulated = bool(info is not None and getattr(info, "backend", "") == "sim")
        self.simulated = bool(simulated)
        self._install_camera(camera, info or camera.info())
        return self.start()

    # @args: none. Stops the stream and closes the camera; the panel goes empty
    def close_camera(self) -> None:
        self.stop()
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:  # noqa: BLE001
                pass
        self.camera = None
        self.camera_info = None
        self.simulated = False
        self.cameraChanged.emit(None, False)

    # @args: mount - the mount the scene and the engines use
    def use_mount(self, mount: Mount) -> None:
        self.mount = mount
        if self.simulated and self.camera is not None \
                and hasattr(self.camera, "bind_mount"):
            self.camera.bind_mount(mount)

    # @args: roi - the new model
    def apply_roi(self, roi: RoiModel) -> None:
        self.roi = roi
        if self.camera is not None:
            self.engine.configure(self.camera, roi, self._params())

    # @args: settings - the new Settings
    def update_settings(self, settings) -> None:
        self.settings = settings
        self.latitude_deg = float(self._value("observatory", "latitude_deg"))
        self.longitude_deg = float(self._value("observatory", "longitude_deg"))

    # @args: none
    # @return: the effective slit length in arcsec from the profile optics
    def slit_arcsec(self) -> float:
        scale = pixel_scale_arcsec_px(
            self.profile.telescope.focal_length_mm,
            self.profile.camera.pixel_size_um)
        try:
            return effective_slit_arcsec(
                self.profile.telescope.slit_length_mm, 1.0,
                self.profile.camera.pixel_size_um,
                int(self.roi.capture[2]), scale)
        except ValueError:
            return 0.0

    # @args: none
    # @return: the Sun's apparent diameter, arcsec
    def solar_diameter_arcsec(self) -> float:
        return solar_position_now(
            self.latitude_deg, self.longitude_deg).diameter_arcsec

    # @args: none. Starts the real SunCenteringImpl in a worker thread
    def center_sun(self) -> bool:
        if self._busy_center or self._busy_scan or self.camera is None \
                or not self.is_running():
            self.engineError.emit("not_ready")
            return False
        slit = self.slit_arcsec()
        if slit <= 0:
            self.engineError.emit("optics_missing")
            return False
        try:
            service = SunCenteringImpl(
                self.mount, self.engine,
                band=self.roi.band,
                slit_arcsec=slit,
                solar_diameter_arcsec=self.solar_diameter_arcsec(),
                slit_arcsec_px=slit / max(1, self.roi.band[2]),
                method=self._dec_method(),
            )
        except Exception:  # noqa: BLE001 - the service refuses a bad geometry
            self.engineError.emit("optics_missing")
            return False
        self._busy_center = True
        self._start_task(service.center, "center")
        return True

    # @args: none
    # @return: the Dec centring method from the INI
    def _dec_method(self) -> DecCenterMethod:
        value = str(self._value("scan", "dec_center") or "auto")
        try:
            return DecCenterMethod(value)
        except ValueError:
            return DecCenterMethod.AUTO

    # @args: fn - the blocking call; kind - what it is
    def _start_task(self, fn, kind: str) -> None:
        self._finish_task()
        task = _Task(fn, self)
        task.progress.connect(lambda value: self._task_progress(kind, value))
        task.done.connect(lambda value: self._task_done(kind, value))
        task.failed.connect(lambda detail: self._task_failed(kind, detail))
        task.finished.connect(task.deleteLater)
        self._task = task
        task.start()

    # @args: kind - center, prepare or scan; value - the progress object
    def _task_progress(self, kind: str, value) -> None:
        if kind == "center":
            self.centeringProgress.emit(value)
        elif kind == "prepare":
            self.prepareStatus.emit(value)
        elif kind == "scan":
            if isinstance(value, tuple) and value and value[0] == "cycle":
                # Each cycle is its own preview: the mount moved back to the
                # start, so stacking the previous cycle would draw two disks.
                self._recon_rows = [[]]
                self._recon_row = 0
                self._recon_frames = 0
                self._next_recon_at = 0.0
                self.cycleStarted.emit(int(value[1]), int(value[2]))
            elif isinstance(value, tuple) and value and value[0] == "phase":
                self.scanPhase.emit(str(value[1]))
            elif isinstance(value, ScanProgress):
                if not self._recon_rows:
                    self._recon_rows = [[]]
                if value.row != self._recon_row:
                    self._recon_rows.append([])
                    self._recon_row = value.row
                self.scanProgress.emit(value)

    # @args: kind - the operation; value - its result
    def _task_done(self, kind: str, value) -> None:
        if kind == "center":
            self._busy_center = False
            self.centeringFinished.emit(value)
        elif kind == "prepare":
            self._busy_prepare = False
            self.prepareFinished.emit(value)
        elif kind == "scan":
            self._busy_scan = False
            self._emit_recon(final=True)
            self._scanning = False
            self.scanFinished.emit(value)
        self._task = None

    # @args: kind - the operation; detail - the exception text for the log
    def _task_failed(self, kind: str, detail: str) -> None:
        if kind == "center":
            self._busy_center = False
            self.centeringFinished.emit(CenteringResult(
                ok=False, dec_offset_arcsec=0.0,
                method=DecCenterMethod.AUTO, reason_code="engine_error"))
        elif kind == "prepare":
            self._busy_prepare = False
            self.prepareFinished.emit(PrepareResult(
                ok=False, dec_offset_arcsec=0.0, rate_arcsec_s=0.0,
                method=DecCenterMethod.AUTO, reason_code="engine_error"))
        elif kind == "scan":
            self._busy_scan = False
            self._emit_recon(final=True)
            self._scanning = False
            self.scanFinished.emit(ScanResult(
                status=ScanStatus.FAILED, frames_written=0, frames_dropped=0,
                duration_s=0.0, rate_arcsec_s=0.0, rows_completed=0,
                dec_error_arcsec=0.0, reason_code="engine_error"))
        self._task = None
        logging.getLogger("solarscribe").warning("engine task failed: %s", detail)
        self.message.emit(detail)

    # @args: none
    def _finish_task(self) -> None:
        task = self._task
        if task is not None and task.isRunning():
            task.requestInterruption()
        self._task = None

    # @args: none. Builds the ScanConfig from the INI and the ROI
    # @return: the ScanConfig
    def _scan_config(self):
        rows = max(1, int(self._value("scan", "rows")))
        rate = float(self._value("scan", "rate_arcsec_s"))
        if self.simulated and rate <= 0:
            rate = SIM_RATE_ARCSEC_S
        from solarscribe.shg.abc import ScanConfig, ScanMode
        return ScanConfig(
            capture=self.roi.capture,
            band=self.roi.band,
            mode=ScanMode.MOSAIC if rows > 1 else ScanMode.SIMPLE,
            cycles=max(1, int(self._value("scan", "cycles"))),
            rate_arcsec_s=rate,
            dec_center=self._dec_method(),
            rows=rows,
            row_step_arcsec=float(self._value("scan", "row_step_arcsec")),
            padding_s=float(self._value("scan", "padding_s")),
            preload_s=float(self._value("scan", "preload_s")),
            adaptive_stop=bool(self._value("scan", "adaptive_stop")),
            tilt_deg=float(self.roi.tilt_deg),
            tilt_px=float(self.roi.tilt_px),
        )

    # @args: none. Creates the scan engine with the profile optics and logs
    def _new_scan_engine(self):
        import solarscribe
        sun = solar_position_now(self.latitude_deg, self.longitude_deg)
        scale = pixel_scale_arcsec_px(
            self.profile.telescope.focal_length_mm,
            self.profile.camera.pixel_size_um)
        scan = ScanEngineImpl(self.mount, self.engine,
                              app_version=solarscribe.__version__)
        scan.set_optics(
            pixel_scale=scale,
            solar_diameter_arcsec=sun.diameter_arcsec,
            fps=float(self.counters().fps or self._value("capture", "target_fps")),
            solar=sun,
            focal_length_mm=self.profile.telescope.focal_length_mm,
            pixel_size_um=self.profile.camera.pixel_size_um,
            slit_arcsec_px=scale,
        )
        scan.set_slit_arcsec(self.slit_arcsec())
        scan.set_log_paths(
            store.scan_log_path(self.folder),
            store.scan_stats_path(self.folder),
            store.session_meta_path(self.folder),
        )
        return scan

    # @args: none. Plans and prepares in a worker; emits planReady and the result
    def start_prepare(self) -> bool:
        if self._busy_prepare or self._busy_scan or self._busy_center:
            return False
        if self.camera is None or not self.is_running():
            self.engineError.emit("not_ready")
            return False
        try:
            self._scan = self._new_scan_engine()
            self._config = self._scan_config()
            self._plan = self._scan.plan(self._config)
        except Exception:  # noqa: BLE001 - a plan must never crash the window
            self.engineError.emit("plan_failed")
            return False
        self.planReady.emit(self._plan)
        self._busy_prepare = True
        scan = self._scan

        def work(emit):
            return scan.prepare(lambda status: emit(status))

        self._start_task(work, "prepare")
        return True

    # @args: cycles - cycles to run; recenter - recentre between cycles
    def start_scan(self, cycles: int | None = None,
                   recenter: bool = False) -> bool:
        if self._busy_scan or self._busy_prepare or self._busy_center:
            return False
        if self._scan is None or self._plan is None:
            self.engineError.emit("not_prepared")
            return False
        total = max(1, int(cycles or self._value("scan", "cycles")))
        scan = self._scan
        plan = self._plan
        record = bool(self._value("scan", "enable_capture")) and not self.simulated
        recorder = RowRecorderAdapter(self.engine, self.roi,
                                      int(self._value("camera", "bit_depth"))) \
            if record else None
        counter = [0]
        base_name = str(self._value("session", "base_name") or "sun")
        when = datetime.now(timezone.utc)

        def path_for_row(_index: int) -> Path:
            counter[0] += 1
            return store.scan_ser_path(self.folder, base_name, when, counter[0])

        self._busy_scan = True
        self._scanning = True
        self._recon_rows = [[]]
        self._recon_row = 0
        self._recon_frames = 0
        self._next_recon_at = 0.0
        engine = self.engine
        service_factory = self._new_centering_service

        def work(emit):
            results = []
            for cycle in range(total):
                emit(("cycle", cycle + 1, total))
                if cycle:
                    # A sweep ends at the trailing limb, far from the start RA.
                    # Repeating a cycle without going back would sweep empty
                    # sky, so the rewind is mandatory; the recentre is optional.
                    self._rewind_to_plan_start(plan)
                if cycle and recenter:
                    emit(("phase", "recentring"))
                    try:
                        service = service_factory()
                        centre = service.center(lambda status: None)
                    except Exception:  # noqa: BLE001 - the scan still runs
                        centre = None
                    if centre is not None and not centre.ok:
                        emit(("phase", "scanning"))
                else:
                    emit(("phase", "scanning"))
                result = scan.run(plan, lambda progress: emit(progress),
                                  recorder, path_for_row if recorder else None)
                results.append(result)
                if result.status is not ScanStatus.COMPLETED:
                    break
            return _aggregate_results(results, plan.rate_arcsec_s)

        self._start_task(work, "scan")
        return True

    # @args: plan - the plan being repeated
    # @return: none. Puts the mount back at the RA where the sweep began, so the
    #          next cycle crosses the disk instead of empty sky
    def _rewind_to_plan_start(self, plan) -> None:
        if not plan.rows:
            return
        target_ra = float(plan.rows[0].ra_start_hours)
        target_dec = float(self.mount.position()[1])
        try:
            self.mount.slew(target_ra % 24.0, target_dec)
        except DeviceError:
            return
        # A real mount needs a moment; the simulator arrives at once. Poll the
        # reported position instead of a fixed sleep, so a fast mount is not
        # punished and a slow one is not cut short.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                ra, dec = self.mount.position()
                delta_ra = abs((ra - target_ra + 12.0) % 24.0 - 12.0) * 3600.0
                delta_dec = abs(dec - target_dec) * 3600.0
            except DeviceError:
                return
            if delta_ra < 10.0 and delta_dec < 10.0:
                return
            time.sleep(0.02)

    # @args: none
    # @return: a fresh centering service for a between-cycles recentre
    def _new_centering_service(self):
        slit = self.slit_arcsec()
        return SunCenteringImpl(
            self.mount, self.engine,
            band=self.roi.band, slit_arcsec=slit,
            solar_diameter_arcsec=self.solar_diameter_arcsec(),
            slit_arcsec_px=slit / max(1, self.roi.band[2]),
            method=self._dec_method(),
        )

    # @args: none. Holds the sweep
    def pause_scan(self) -> None:
        if self._scan is not None:
            self._scan.pause()

    # @args: none. Continues a held sweep
    def resume_scan(self) -> None:
        if self._scan is not None:
            self._scan.resume()

    # @args: none. Stops the sweep and keeps the frames already written
    def abort_scan(self) -> None:
        if self._scan is not None:
            self._scan.abort()

    # ── polar assistant (the real drift fit, on simulated samples) ───────────
    # @args: second - True for the confirmation measurement
    def start_polar(self, second: bool = False) -> None:
        self._polar_second = bool(second)
        self._polar_progress = 0.0
        self._polar_index = 0
        self._polar_samples = []
        azimuth = 30.0 if second else 300.0
        altitude = 20.0 if second else 180.0
        self._polar_target = (azimuth, altitude)
        self._polar_session = PolarAlignmentSession(
            max(1.0, abs(self.latitude_deg)), required_samples=8)
        if not self._polar_timer.isActive():
            self._polar_timer.start()

    # @args: none
    def stop_polar(self) -> None:
        self._polar_timer.stop()

    # @args: none. Feeds one synthetic sample to the real drift fit
    def _polar_tick(self) -> None:
        if self._polar_session is None:
            return
        index = self._polar_index
        hour_angle = -60.0 + index * 120.0 / 7.0
        ha = math.radians(hour_angle)
        cos_lat = math.cos(math.radians(max(1.0, abs(self.latitude_deg))))
        azimuth, altitude = self._polar_target
        dec = (altitude * math.cos(ha)
               - azimuth * cos_lat * math.sin(ha)) / 3600.0
        sample = PolarSample(time_s=index * 180.0, hour_angle_deg=hour_angle,
                             dec_deg=dec, dec_ephemeris_deg=0.0)
        self._polar_samples.append(sample)
        progress = self._polar_session.add_sample(sample)
        fitted = self._polar_session.result() if index + 1 >= 3 else None
        azimuth_value = fitted.azimuth_error_arcsec if fitted is not None else 0.0
        altitude_value = fitted.altitude_error_arcsec if fitted is not None else 0.0
        self.polarProgress.emit(progress.progress, {
            "azimuth_arcmin": abs(azimuth_value) / 60.0,
            "altitude_arcmin": abs(altitude_value) / 60.0,
            "azimuth_sign": azimuth_value,
            "altitude_sign": altitude_value,
            "samples": progress.samples,
            "second": self._polar_second,
        })
        self._polar_index += 1
        if self._polar_index >= 8:
            self._polar_timer.stop()
            confirmation = (self._polar_session.confirm(self._polar_samples)
                            if self._polar_second
                            else self._polar_session.result())
            self.polarFinished.emit({
                "azimuth_arcmin": abs(confirmation.azimuth_error_arcsec) / 60.0,
                "altitude_arcmin": abs(confirmation.altitude_error_arcsec) / 60.0,
                "samples": confirmation.samples,
                "second": self._polar_second,
                "confirmed": bool(confirmation.confirmation),
                "reason_code": confirmation.reason_code,
                "azimuth_sign": confirmation.azimuth_error_arcsec,
                "altitude_sign": confirmation.altitude_error_arcsec,
                "tolerance_arcmin": self._polar_session.tolerance_arcsec / 60.0,
            })


# @args: results - the ScanResult of each finished cycle; rate - the sweep rate
# @return: one result with the totals, so the window has a single outcome
def _aggregate_results(results, rate: float) -> ScanResult:
    if not results:
        return ScanResult(status=ScanStatus.FAILED, frames_written=0,
                          frames_dropped=0, duration_s=0.0,
                          rate_arcsec_s=rate, rows_completed=0,
                          dec_error_arcsec=0.0, reason_code="engine_error")
    completed = all(item.status is ScanStatus.COMPLETED for item in results)
    status = ScanStatus.COMPLETED if completed else results[-1].status
    paths = tuple(path for item in results for path in item.ser_paths)
    return ScanResult(
        status=status,
        frames_written=sum(item.frames_written for item in results),
        frames_dropped=sum(item.frames_dropped for item in results),
        duration_s=sum(item.duration_s for item in results),
        rate_arcsec_s=rate,
        rows_completed=sum(item.rows_completed for item in results),
        dec_error_arcsec=results[-1].dec_error_arcsec,
        ser_paths=paths,
        reason_code="" if completed else results[-1].reason_code,
    )
