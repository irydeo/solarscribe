############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui demo harness module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# A simulator that lets the whole interface run without a camera or a mount.
#
# Why it lives in ui: the app must open on a machine with no SDK, no camera and
# no mount (ADR-004, ADR-014) and still show what the observer will see. The
# real simulators are the QE agent's (ADR-005); this one paints plausible frames
# and answers the contracts so every screen and every control is exercised.
# It is labelled as a simulator everywhere it appears: it never pretends a scan
# produced a SER file, and it never replaces the science of shg.
#
# What it emulates, and what it does not:
#   - frames: a dispersed spectrum with a slightly tilted slit line, a limb and
#     shot noise, so the viewer and the histogram have real work;
#   - mount: the Mount contract, with position, rate moves, slew, sync, park;
#   - streams: counters against the ADR-013 budget, honest about being simulated;
#   - scan and polar: progress callbacks with the dataclasses shg declares, so
#     the UI wiring is the one the real engine will use.
# The Sun position here is an approximation for the demo. The authoritative,
# local ephemeris is shg's (ADR-021); the sky calendar says which one is on
# screen.

from __future__ import annotations

import math
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from solarscribe.capture.abc import StreamCounters
from solarscribe.devices.abc import (
    Axis,
    MountCaps,
    MountStatus,
    ROI,
)
from solarscribe.shg.abc import (
    DecCenterMethod,
    PolarSample,
    PreparePhase,
    PrepareResult,
    PrepareStatus,
    ScanProgress,
    ScanResult,
    ScanState,
    ScanStatus,
    TiltResult,
)
from solarscribe.shg.polar import PolarAlignmentSession

__all__ = [
    "DemoFrame",
    "DemoHarness",
    "DemoMount",
    "DemoStats",
    "demo_sun_info",
    "demo_sun_position",
    "demo_tilt",
]

# The demo runs at this rate instead of 120 fps: a GUI that repaints 120 times a
# second in a simulator teaches nothing and burns a laptop. The health panel
# reports the simulator's real rate and says so, so the figure is never mistaken
# for a camera measurement.
DEMO_FPS = 8.0


@dataclass(frozen=True)
class DemoStats:
    # FrameStats is a Protocol, so a plain pair of numbers satisfies it.
    mean: float
    std: float


# @args: data - the uint16 array of the frame; width, height - its shape
#        roi - the SENSOR ROI this frame came from; sequence - frame counter
# @return: a DemoFrame, the value the Frame protocol describes
class DemoFrame:
    # @args: data - the uint16 pixels; roi - the SENSOR ROI; sequence - counter;
    #        timestamp - seconds, taken now when omitted
    # @return: a frame satisfying the Frame protocol
    def __init__(self, data: np.ndarray, roi: ROI, sequence: int,
                 timestamp: float | None = None) -> None:
        self._array = np.ascontiguousarray(data, dtype=np.uint16)
        self.height, self.width = self._array.shape
        self.data = memoryview(self._array)
        self.dtype = np.dtype(np.uint16)
        self.roi = roi
        self.sequence = sequence
        self.timestamp = time.monotonic() if timestamp is None else timestamp

    # @args: none
    # @return: mean and standard deviation of the frame
    def stats(self) -> DemoStats:
        return DemoStats(float(self._array.mean()), float(self._array.std()))

    # @args: roi - sub-region in FRAME pixels
    # @return: that sub-region as a frame; copied, because a sliced array has
    #          row strides and the contract promises C-contiguous data
    def cut_roi(self, roi: ROI) -> "DemoFrame":
        x, y, width, height = roi
        x = max(0, min(int(x), self.width))
        y = max(0, min(int(y), self.height))
        width = max(1, min(int(width), self.width - x))
        height = max(1, min(int(height), self.height - y))
        piece = self._array[y:y + height, x:x + width].copy()
        return DemoFrame(piece, self.roi, self.sequence, self.timestamp)


# @args: width, height - frame size; band - the spectral band in frame pixels
#        sequence - frame counter; phase - advances the spectrum with time
# @return: a synthetic SHG frame: bright continuum inside the solar disk, a
#          tilted slit line and absorption lines, all in 16 bit
def _make_frame(width: int, height: int, band: tuple[int, int, int, int],
                sequence: int, phase: float) -> DemoFrame:
    band_x, band_y, band_w, band_h = band
    band_y = max(0, min(int(band_y), height - 1))
    band_h = max(1, min(int(band_h), height - band_y))
    centre_y = band_y + band_h / 2.0
    sigma = max(1.0, band_h / 5.0)

    # Vertical profile of the dispersed order: a Gaussian around the band
    # centre. Everything outside it is dark, which is what the ROI step wants
    # to see when it checks that the band fits.
    rows = np.arange(height, dtype=np.float32)[:, None]
    profile = np.exp(-((rows - centre_y) ** 2) / (2.0 * sigma * sigma))

    # The disk along the slit: limb darkening, so the edges roll off and the
    # limb detector has something to find.
    cols = np.arange(width, dtype=np.float32)[None, :]
    u = (cols / max(1, width - 1)) * 2.0 - 1.0
    disk = np.sqrt(np.clip(1.0 - u * u, 0.0, 1.0)) ** 0.35
    # A slowly moving granulation pattern: enough texture that the histogram
    # and the focus aid have a real standard deviation to show.
    texture = 1.0 + 0.06 * np.sin(cols * 0.05 + phase) * np.sin(rows * 0.17)
    continuum = disk * texture

    # Absorption lines at fixed positions, as a real spectrum has. They are what
    # the observer uses to tell focus from defocus.
    spectrum = continuum * (1.0 - 0.35 * np.exp(-((cols - width * 0.25) ** 2)
                                              / (2.0 * (width * 0.006) ** 2)))
    spectrum *= (1.0 - 0.28 * np.exp(-((cols - width * 0.62) ** 2)
                                    / (2.0 * (width * 0.004) ** 2)))

    # The slit line: 0.28 degrees of tilt, the value the demo reports when the
    # ROI step asks for a measurement. It drifts by tan(0.28 deg) * width px.
    slope = math.tan(math.radians(0.28))
    line_centre = centre_y + slope * (cols - width / 2.0)
    slit = np.exp(-((rows - line_centre) ** 2) / (2.0 * 1.2 ** 2))
    level = 0.25 + 0.35 * spectrum * profile + 0.45 * slit * disk

    # Shot noise, seeded by the frame so a test can reproduce one.
    rng = np.random.default_rng(sequence)
    level = level + rng.normal(0.0, 0.008, size=(height, width)).astype(np.float32)
    level = np.clip(level, 0.0, 1.0)
    return DemoFrame((level * 65535.0).astype(np.uint16),
                     (0, 0, width, height), sequence)


class DemoMount:
    # The Mount contract, simulated. It never touches a serial port and it keeps
    # every call cheap: the panel polls position() and status() twice a second.

    # @args: sun_provider - callable for the demo Sun, or None
    # @return: a disconnected mount
    def __init__(self, sun_provider=None) -> None:
        self._ra = 10.0
        self._dec = 10.0
        self._connected = False
        self._tracking = False
        self._parked = False
        self._slewing = False
        self._sun_provider = sun_provider
        self.aborts = 0

    # @args: none
    def connect(self) -> None:
        self._connected = True

    # @args: none
    def close(self) -> None:
        self._connected = False

    # @return: whether the simulated mount is connected
    def is_connected(self) -> bool:
        return self._connected

    # @return: (ra hours, dec degrees)
    def position(self) -> tuple[float, float]:
        return self._ra % 24.0, max(-90.0, min(90.0, self._dec))

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    def move_axis(self, axis: Axis, rate: float) -> None:
        # A rate move is continuous on a real mount. The simulator advances by
        # the 200 ms the UI polls at, so a held button visibly moves.
        step_seconds = 0.2
        if axis is Axis.RA:
            self._ra = (self._ra + rate * step_seconds / 3600.0 / 15.0) % 24.0
        else:
            self._dec = max(-90.0, min(90.0,
                                       self._dec + rate * step_seconds / 3600.0))

    # @args: none
    def stop(self) -> None:
        self._slewing = False

    # @args: ra - hours; dec - degrees
    def slew(self, ra: float, dec: float) -> None:
        self._ra = ra % 24.0
        self._dec = max(-90.0, min(90.0, dec))
        self._slewing = False

    # @args: ra - hours; dec - degrees
    def sync(self, ra: float, dec: float) -> None:
        self._ra = ra % 24.0
        self._dec = max(-90.0, min(90.0, dec))

    # @args: on - tracking enabled
    def set_tracking(self, on: bool) -> None:
        self._tracking = bool(on)

    # @args: none
    def park(self) -> None:
        self._parked = True
        self._tracking = False

    # @args: none
    def unpark(self) -> None:
        self._parked = False

    # @args: none
    def abort_slew(self) -> None:
        self._slewing = False
        self.aborts += 1

    # @args: none
    # @return: the Sun position the demo mount was built with
    def sun_position(self) -> tuple[float, float]:
        if self._sun_provider is None:
            return 0.0, 0.0
        return self._sun_provider()

    # @return: live state for the panel
    def status(self) -> MountStatus:
        return MountStatus(tracking=self._tracking, slewing=self._slewing,
                           parked=self._parked)

    # @return: what the simulator supports
    def capabilities(self) -> MountCaps:
        return MountCaps(supports_axis_rates=True, can_slew=True, can_sync=True,
                         can_track=True, can_park=True, can_abort=True,
                         reports_position_while_moving=True,
                         min_rate_arcsec_s=0.1, max_rate_arcsec_s=800.0)


# @args: none
# @return: an approximate Sun position for the demo: (ra hours, dec degrees).
#          The real one is computed by shg from the observatory position
#          (ADR-021); this approximation only keeps the demo believable
def demo_sun_position() -> tuple[float, float]:
    now = datetime.now(timezone.utc)
    # Days since J2000.0, the usual starting point of the low-precision series.
    days = (now - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0
    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360.0)
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecliptic = mean_longitude + math.radians(
        1.915 * math.sin(anomaly) + 0.020 * math.sin(2.0 * anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * days)
    ra = math.atan2(math.cos(obliquity) * math.sin(ecliptic),
                    math.cos(ecliptic))
    dec = math.asin(math.sin(obliquity) * math.sin(ecliptic))
    return (math.degrees(ra) / 15.0) % 24.0, math.degrees(dec)


# @args: none
# @return: the Sun-tab figures the demo can honestly produce, marked as
#          simulated by the dialog. Missing figures stay None instead of guessed
def demo_sun_info() -> dict:
    ra, dec = demo_sun_position()
    days = (datetime.now(timezone.utc)
            - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0
    distance_au = 1.00014 - 0.01671 * math.cos(
        math.radians((357.528 + 0.9856003 * days) % 360.0))
    diameter_arcmin = 2.0 * math.degrees(math.asin(0.00465047 / distance_au)) * 60.0
    try:
        from solarscribe.shg.ephemeris import julian_date, solar_rotation
        rotation = solar_rotation(julian_date(datetime.now(timezone.utc)))
        position_angle = rotation.position_angle_deg
        heliographic = (f"B0 {rotation.heliographic_latitude_deg:+.2f} deg, "
                        f"L0 {rotation.heliographic_longitude_deg:.2f} deg")
    except ImportError:
        position_angle = None
        heliographic = None
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "diameter_arcmin": diameter_arcmin,
        "ra_hours": ra,
        "dec_deg": dec,
        "rotation": position_angle,
        "heliographic": heliographic,
    }


# @args: none
# @return: a plausible tilt measurement, labelled as simulated by the ROI step
def demo_tilt() -> TiltResult:
    return TiltResult(ok=True, tilt_deg=0.28, tilt_px=1.9, edge_std_px=0.4)


class DemoHarness(QObject):
    # The simulator's event source. MainWindow connects these signals; the real
    # session will connect the same shapes from CaptureEngine and ScanEngine,
    # which is why the wiring is worth doing now.

    frameReady = Signal(object)
    countersChanged = Signal(object)
    rateEstimate = Signal(float, float)
    prepareStatus = Signal(object)
    prepareFinished = Signal(object)
    scanProgress = Signal(object)
    scanFinished = Signal(object)
    reconStrip = Signal(object)
    polarProgress = Signal(float, object)
    polarFinished = Signal(object)
    mountChanged = Signal(object)

    # @args: folder - the session folder for free-space reporting; band - the
    #        spectral band in frame pixels; width, height - the demo frame size
    # @return: the harness, with its timers stopped until start() is called
    def __init__(self, folder: Path, band: ROI, width: int = 3480,
                 height: int = 248, parent=None) -> None:
        super().__init__(parent)
        # The demo frames keep the reference geometry (3480 x 248) on purpose:
        # the ROI step and the histogram then see exactly the strip the observer
        # will see from the Touptek, and no number is a convenient lie. The frame
        # rate is the only thing lowered (DEMO_FPS).
        self.folder = Path(folder)
        self.band = band
        self.width = max(64, min(int(width), 4096))
        self.height = max(16, min(int(height), 2048))
        self.mount = DemoMount(demo_sun_position)
        self._sequence = 0
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(int(1000 / DEMO_FPS))
        self._frame_timer.timeout.connect(self.push_frame)
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(90)
        self._scan_timer.timeout.connect(self._scan_tick)
        self._polar_timer = QTimer(self)
        self._polar_timer.setInterval(250)
        self._polar_timer.timeout.connect(self._polar_tick)
        self._scan_cycles = 1
        self._scan_overall = 0.0
        self._scan_frames = 0
        self._scan_started = 0.0
        self._polar_second = False
        self._polar_progress = 0.0
        self._polar_session = None
        self._polar_index = 0
        self._polar_samples: list[PolarSample] = []
        self._polar_azimuth = 0.0
        self._polar_altitude = 0.0
        # The simulator uses this latitude for the polar fit; the window copies
        # it from the saved observatory position before starting.
        self.latitude_deg = 40.0
        self._last_result: ScanResult | None = None
        self._last_frame = None

    # @args: none
    def start(self) -> None:
        # Timers start only when the app asks, so tests can drive one frame at a
        # time and never depend on wall-clock timing.
        if not self._frame_timer.isActive():
            self._frame_timer.start()

    # @args: none
    def stop(self) -> None:
        for timer in (self._frame_timer, self._scan_timer, self._polar_timer):
            timer.stop()

    # @args: none
    # @return: the last frame emitted, for the ROI tilt and the focus aid
    def last_frame(self):
        return self._last_frame

    # @args: none. Generates and emits exactly one frame (tests use this)
    def push_frame(self) -> None:
        self._sequence += 1
        frame = _make_frame(self.width, self.height, self.band,
                            self._sequence, self._sequence * 0.12)
        self._last_frame = frame
        self.frameReady.emit(frame)
        self.countersChanged.emit(self.counters())

    # @args: mount - a Mount the observer chose in discovery
    def adopt_mount(self, mount) -> None:
        # The demo harness measures its position from this object, so swapping it
        # for the device layer's simulator keeps the panel and the scan on the
        # same mount instead of two that disagree.
        self.mount = mount

    # @args: none
    # @return: the live counters the status bar reads
    def counters(self) -> StreamCounters:
        return StreamCounters(
            frames_received=self._sequence,
            frames_dropped_sdk=0,
            sequence_gaps=0,
            fps=DEMO_FPS,
            disk_mb_s=118.0 if self._scan_timer.isActive() else 0.0,
        )

    # @args: none
    # @return: free space of the session disk, in GB, as the health panel needs
    def free_gb(self) -> float:
        try:
            return shutil.disk_usage(self.folder).free / (1024 ** 3)
        except OSError:
            return 0.0

    # @args: width, height - the capture rectangle the ROI step selected
    def set_frame_size(self, width: int, height: int) -> None:
        self.width = max(64, min(int(width), 4096))
        self.height = max(16, min(int(height), 2048))

    # @args: seconds - ignored; the simulator needs no settling time
    def start_prepare(self) -> None:
        self.prepareStatus.emit(PrepareStatus(
            phase=PreparePhase.FINE_CENTER, progress=0.15,
            dec_offset_arcsec=12.0, rate_arcsec_s=None))
        QTimer.singleShot(250, self._prepare_mid)
        QTimer.singleShot(600, self._prepare_done)

    # @args: none
    def _prepare_mid(self) -> None:
        self.prepareStatus.emit(PrepareStatus(
            phase=PreparePhase.CALIBRATE_RATE, progress=0.55,
            dec_offset_arcsec=1.4, rate_arcsec_s=15.04))

    # @args: none
    def _prepare_done(self) -> None:
        self.prepareStatus.emit(PrepareStatus(
            phase=PreparePhase.CALIBRATE_RATE, progress=1.0,
            dec_offset_arcsec=0.3, rate_arcsec_s=15.04))
        self.prepareFinished.emit(PrepareResult(
            ok=True, dec_offset_arcsec=0.3, rate_arcsec_s=15.04,
            method=DecCenterMethod.SYMMETRY, reason_code=""))

    # @args: cycles - scans to simulate in this run
    def start_scan(self, cycles: int = 1) -> None:
        self._scan_cycles = max(1, int(cycles))
        self._scan_overall = 0.0
        self._scan_frames = 0
        self._scan_started = time.monotonic()
        self._last_result = None
        if not self._scan_timer.isActive():
            self._scan_timer.start()
        self._emit_scan_progress()

    # @args: none
    def _scan_tick(self) -> None:
        increment = 0.012
        self._scan_overall = min(1.0, self._scan_overall + increment)
        self._scan_frames += max(1, int(120 * 0.09))
        self._emit_scan_progress()
        if int(self._scan_overall * 40) % 2 == 0:
            self.reconStrip.emit(self._recon_strip(self._scan_overall))
        if self._scan_overall >= 1.0:
            self._scan_timer.stop()
            result = ScanResult(
                status=ScanStatus.COMPLETED,
                frames_written=self._scan_frames,
                frames_dropped=0,
                duration_s=time.monotonic() - self._scan_started,
                rate_arcsec_s=15.04,
                rows_completed=self._scan_cycles,
                dec_error_arcsec=0.3,
                ser_paths=(),
                reason_code="",
            )
            self._last_result = result
            self.scanFinished.emit(result)

    # @args: none
    def _emit_scan_progress(self) -> None:
        ra, dec = self.mount.position()
        self.scanProgress.emit(ScanProgress(
            state=ScanState.RUNNING if self._scan_timer.isActive()
            else ScanState.PAUSED,
            row=max(0, int(self._scan_overall * self._scan_cycles)),
            progress=self._scan_overall,
            frames_written=self._scan_frames,
            frames_dropped=0,
            ra_hours=ra,
            dec_deg=dec,
            dec_error_arcsec=0.3,
            elapsed_s=time.monotonic() - self._scan_started,
        ))

    # @args: none. Holds the simulated sweep where it is
    def pause_scan(self) -> None:
        if self._scan_timer.isActive():
            self._scan_timer.stop()
            self._emit_scan_progress()

    # @args: none. Continues a paused simulated sweep
    def resume_scan(self) -> None:
        if self._last_result is None and not self._scan_timer.isActive():
            self._scan_timer.start()
            self._emit_scan_progress()

    # @args: none. Stops the run and reports ABORTED, as the real engine does
    def abort_scan(self) -> None:
        self._scan_timer.stop()
        result = ScanResult(
            status=ScanStatus.ABORTED,
            frames_written=self._scan_frames,
            frames_dropped=0,
            duration_s=time.monotonic() - self._scan_started,
            rate_arcsec_s=15.04,
            rows_completed=max(0, int(self._scan_overall * self._scan_cycles)),
            dec_error_arcsec=0.3,
            ser_paths=(),
            reason_code="aborted",
        )
        self._last_result = result
        self.scanFinished.emit(result)

    # @args: overall - 0..1 of the run
    # @return: a slice of the synthetic disk for the quick recon, in grey levels
    def _recon_strip(self, overall: float) -> np.ndarray:
        height = 64
        width = 6
        rows = np.arange(height, dtype=np.float32)[:, None]
        centre = height / 2.0
        disk = np.sqrt(np.clip(1.0 - ((rows - centre) / centre) ** 2, 0.0, 1.0))
        texture = 0.55 + 0.45 * np.cos((overall * 12.0) + rows * 0.2)
        column = np.clip(disk * texture, 0.0, 1.0) * 255.0
        return np.repeat(column, width, axis=1).astype(np.uint8)

    # @args: second - True for the confirmation measurement
    def start_polar(self, second: bool = False) -> None:
        self._polar_second = bool(second)
        self._polar_progress = 0.0
        self._polar_index = 0
        self._polar_samples = []
        # The first run has a deliberately coarse alignment; the confirmation
        # run starts where the observer left it after turning the screws, so the
        # real assistant can mark the result as confirmed. The values are the
        # simulator's, not a measurement.
        self._polar_azimuth = 30.0 if second else 300.0     # arcsec
        self._polar_altitude = 20.0 if second else 180.0    # arcsec
        self._polar_session = PolarAlignmentSession(
            max(1.0, abs(self.latitude_deg)), required_samples=8)
        if not self._polar_timer.isActive():
            self._polar_timer.start()

    # @args: none. Stops the simulated measurement without a result
    def stop_polar(self) -> None:
        self._polar_timer.stop()

    # @args: none. One synthetic sample fed to the real drift fit
    def _polar_tick(self) -> None:
        if self._polar_session is None:
            return
        index = self._polar_index
        # Spread the hour angle from 60 degrees east to 60 degrees west, which
        # is what lets the fit separate azimuth from altitude (ADR-007).
        hour_angle = -60.0 + index * 120.0 / 7.0
        ha = math.radians(hour_angle)
        cos_lat = math.cos(math.radians(max(1.0, abs(self.latitude_deg))))
        # The fit expects y = altitude * cos(H) - azimuth * cos(lat) * sin(H);
        # feeding exactly that recovers the two errors and exercises the real
        # PolarAlignmentSession instead of a hard-coded progress bar.
        dec_ephemeris = 0.0
        dec = dec_ephemeris + (
            self._polar_altitude * math.cos(ha)
            - self._polar_azimuth * cos_lat * math.sin(ha)
        ) / 3600.0
        sample = PolarSample(time_s=index * 180.0, hour_angle_deg=hour_angle,
                             dec_deg=dec, dec_ephemeris_deg=dec_ephemeris)
        self._polar_samples.append(sample)
        progress = self._polar_session.add_sample(sample)
        fitted = self._polar_session.result() if index + 1 >= 3 else None
        azimuth = fitted.azimuth_error_arcsec if fitted is not None else 0.0
        altitude = fitted.altitude_error_arcsec if fitted is not None else 0.0
        self._polar_progress = progress.progress
        self.polarProgress.emit(progress.progress, {
            "azimuth_arcmin": abs(azimuth) / 60.0,
            "altitude_arcmin": abs(altitude) / 60.0,
            "azimuth_sign": azimuth,
            "altitude_sign": altitude,
            "samples": progress.samples,
            "second": self._polar_second,
        })
        self._polar_index += 1
        if self._polar_index >= 8:
            self._polar_timer.stop()
            if self._polar_second:
                confirmation = self._polar_session.confirm(self._polar_samples)
            else:
                confirmation = self._polar_session.result()
            self.polarFinished.emit({
                "azimuth_arcmin": abs(
                    confirmation.azimuth_error_arcsec) / 60.0,
                "altitude_arcmin": abs(
                    confirmation.altitude_error_arcsec) / 60.0,
                "samples": confirmation.samples,
                "second": self._polar_second,
                "confirmed": bool(confirmation.confirmation),
                "reason_code": confirmation.reason_code,
                "azimuth_sign": confirmation.azimuth_error_arcsec,
                "altitude_sign": confirmation.altitude_error_arcsec,
                "tolerance_arcmin": self._polar_session.tolerance_arcsec / 60.0,
            })

    # @args: none
    # @return: the rate the ROI step shows for the current geometry
    def estimate_rate(self, width: int, height: int) -> tuple[float, float]:
        area = max(1, width * height)
        reference = 3480 * 248
        fps = min(180.0, 120.0 * reference / area)
        mb_s = width * height * 2.0 * fps / 1e6
        return fps, mb_s

    # @args: width, height - the capture rectangle
    def announce_rate(self, width: int, height: int) -> None:
        fps, mb_s = self.estimate_rate(width, height)
        self.rateEstimate.emit(fps, mb_s)
