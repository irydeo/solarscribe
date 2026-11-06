############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg engine module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The scan engine: plan, prepare, run, pause, resume and abort.
#
# It implements the ScanEngine contract of shg/abc.py and is built as
# ScanEngineImpl(mount, frames). It holds no Qt and no driver: it moves the
# mount through the Mount contract and measures the frames it receives through
# the FrameSource port (ARCHITECTURE 2.3).
#
# The science it orchestrates lives in its own modules, so this file is mostly
# sequencing and bookkeeping:
#   - geometry: plate scale, 1/cos(Dec), chord;
#   - calibration: the scan-rate self-calibration;
#   - centering: coarse, symmetry and chord Dec centring;
#   - limb: the adaptive stop;
#   - mosaic: the row plan and the backlash approach;
#   - logs: the three ADR-018 files.
#
# One run() is one cycle. The UI repeats it config.cycles times and can
# recentre between cycles (ARCHITECTURE 2.3). The scan moves by rate, not by
# slew: the RA limits in the plan are the intended geometry for the overlay and
# the log, and the adaptive stop decides the real end.
#
# Sign conventions, fixed here so a positive number means the same thing in the
# plan, the log and the mount:
#   - the scan sweeps towards decreasing RA, so the mount gets a negative RA
#     rate (the Mount contract says a positive rate increases the coordinate);
#   - Dec is positive north; a positive Dec offset is north of the centre.
#
# Threading: _on_frame is called on the capture thread. It only latches the
# last frame and its stats under a small lock, which is far inside the 8.3 ms
# budget at 120 fps (ADR-013). All the waiting and moving happens in run(),
# called from the worker thread the UI owns.

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from solarscribe.devices.abc import Axis, DeviceError, Frame, Mount

from . import analysis, calibration, centering, geometry, mosaic
from .abc import (
    DecCenterMethod,
    FrameSource,
    PreparePhase,
    PrepareResult,
    PrepareStatus,
    RowCounters,
    RowRecorder,
    ScanConfig,
    ScanMode,
    ScanPlan,
    ScanProgress,
    ScanResult,
    ScanRow,
    ScanState,
    ScanStatus,
)
from .ephemeris import SolarPosition
from .limb import LIMB_STDDEV_MIN, ON_DISK_STDDEV, LimbDetector, LimbState
from .logs import (
    ScanLogRow,
    build_session_meta,
    utc_stamp,
    write_scan_log,
    write_scan_stats,
    write_session_meta,
)

__all__ = [
    "ConsistencyIssue",
    "ScanEngineImpl",
    "check_consistency",
]

# Prototype defaults that the engine needs and the config does not carry.
SIDEREAL_ARCSEC_S = 15.04      # arcsec/s per sidereal multiplier unit
DEFAULT_FPS = 120.0            # ADR-013 target
DEFAULT_PIXEL_SCALE = 206265.0 * 0.002 / 714.0
DEFAULT_SOLAR_DIAMETER = 1920.0
SCAN_RETRIES = 1
STALL_TIMEOUT_S = 3.0
POLL_S = 0.02
PROBE_SPEED_MULTIPLIER = 16.0  # prototype MOSAIC_CHORD_SPEED
RETURN_MULTIPLIER = 32.0       # prototype RETURN_MULTIPLIER, for repositioning
REWIND_MARGIN_ARCSEC = 600.0   # extra sky before the disk on a rewind

# A row captured at a different X/Y or slit extent than the first good row is
# what makes a mosaic need a rescale; the prototype warns at 3% (section 7).
CONSISTENCY_TOL_XY = 0.03
CONSISTENCY_TOL_EXTENT = 0.03
SLIT_EXTENT_BANDS = 48


@dataclass(frozen=True)
class ConsistencyIssue:
    # One cross-scan drift. It carries numbers, not a sentence: the UI composes
    # the text with self.tr() (ADR-016) and the log keeps the figure.
    field: str            # "actual_xy" or "slit_extent_px"
    value: float
    reference: float
    deviation: float      # fraction of the reference, e.g. 0.05 = 5%


# @args: actual_xy - X/Y of the current recon
#        slit_extent_px - illuminated extent of the current row
#        reference_xy - X/Y of the first good row, or None
#        reference_extent - extent of the first good row, or None
#        tol_xy, tol_extent - accepted fractional deviation
# @return: the issues found; empty when the row is consistent
# The check is deliberately numeric and pure, so the engine can call it per row
# and the test can pin it without a mount.
def check_consistency(actual_xy: float | None, slit_extent_px: float | None,
                      reference_xy: float | None,
                      reference_extent: float | None,
                      tol_xy: float = CONSISTENCY_TOL_XY,
                      tol_extent: float = CONSISTENCY_TOL_EXTENT) -> tuple[ConsistencyIssue, ...]:
    issues: list[ConsistencyIssue] = []
    if actual_xy and reference_xy:
        deviation = abs(actual_xy - reference_xy) / reference_xy
        if deviation > tol_xy:
            issues.append(ConsistencyIssue("actual_xy", actual_xy,
                                           reference_xy, deviation))
    if slit_extent_px and reference_extent:
        deviation = abs(slit_extent_px - reference_extent) / reference_extent
        if deviation > tol_extent:
            issues.append(ConsistencyIssue("slit_extent_px", slit_extent_px,
                                           reference_extent, deviation))
    return tuple(issues)


@dataclass
class _RowOutcome:
    # Internal result of one row, before it becomes a ScanResult.
    ok: bool
    status: ScanStatus
    counters: RowCounters
    duration_s: float
    dec_error_arcsec: float
    reason_code: str
    ser_path: Path | None


class ScanEngineImpl:
    # The ScanEngine contract (shg/abc.py). Built once per session.

    # @args: mount - the mount contract; frames - the FrameSource port
    #        clock, sleep - injected for the tests; the defaults are monotonic
    #                        time and time.sleep
    #        app_version - what the logs record
    def __init__(self, mount: Mount, frames: FrameSource, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 app_version: str = "") -> None:
        self._mount = mount
        self._frames = frames
        self._clock = clock
        self._sleep = sleep
        self._app_version = app_version

        self._lock = threading.RLock()
        self._latest_frame: Frame | None = None
        self._latest_std = 0.0
        self._latest_mean = 0.0
        self._frame_count = 0
        self._last_frame_time: float | None = None

        self._config: ScanConfig | None = None
        self._plan: ScanPlan | None = None
        self._solar_position_value: SolarPosition | None = None
        self._solar_diameter = DEFAULT_SOLAR_DIAMETER
        self._pixel_scale = DEFAULT_PIXEL_SCALE
        self._fps = DEFAULT_FPS
        self._focal_length_mm: float | None = None
        self._pixel_size_um: float | None = None
        self._slit_arcsec = 0.0
        # Plate scale along the slit axis, measured by the ROI step from the
        # illuminated extent. It can differ from the scan-axis scale when the
        # spectrograph re-images the slit (geometry.slit_image_scale).
        self._slit_arcsec_px: float | None = None
        self._rate_multiplier = 1.0
        self._calibration_per_unit: float | None = None
        self._calibration_factor = 1.0

        self._abort = False
        self._pause = False
        self._resume = threading.Event()
        self._resume.set()
        self._state = ScanState.RUNNING

        self._log_rows: list[ScanLogRow] = []
        self._scan_log_path: Path | None = None
        self._scan_stats_path: Path | None = None
        self._session_meta_path: Path | None = None
        self._reference_xy: float | None = None
        self._reference_extent: float | None = None
        self._consistency: list[ConsistencyIssue] = []

        # Test seams for the two routines that need a real sweep. They are
        # optional callables with the same signatures as the private defaults;
        # production leaves them None.
        self._chord_measure: Callable[[], float | None] | None = None
        self._crossing_measure: Callable[[], float | None] | None = None

        frames.on_frame(self._on_frame)

    # ── configuration supplied by the UI ─────────────────────────────────────
    # @args: pixel_scale - arcsec per pixel on the scan axis
    #        solar_diameter_arcsec - apparent diameter; 0 keeps the current
    #        fps - real capture rate; 0 keeps the current
    #        solar - the ephemeris position, for the plan and the logs
    # @return: none
    def set_optics(self, pixel_scale: float | None = None,
                   solar_diameter_arcsec: float | None = None,
                   fps: float | None = None,
                   solar: SolarPosition | None = None,
                   focal_length_mm: float | None = None,
                   pixel_size_um: float | None = None,
                   slit_arcsec_px: float | None = None) -> None:
        if pixel_scale is not None and pixel_scale > 0:
            self._pixel_scale = float(pixel_scale)
        if solar_diameter_arcsec is not None and solar_diameter_arcsec > 0:
            self._solar_diameter = float(solar_diameter_arcsec)
        if fps is not None and fps > 0:
            self._fps = float(fps)
        if solar is not None:
            self._solar_position_value = solar
            if solar.diameter_arcsec > 0:
                self._solar_diameter = solar.diameter_arcsec
        if focal_length_mm is not None and focal_length_mm > 0:
            self._focal_length_mm = float(focal_length_mm)
        if pixel_size_um is not None and pixel_size_um > 0:
            self._pixel_size_um = float(pixel_size_um)
        if slit_arcsec_px is not None and slit_arcsec_px > 0:
            self._slit_arcsec_px = float(slit_arcsec_px)

    # @args: slit_arcsec - effective slit length on the sky; 0 means unknown
    # @return: none
    def set_slit_arcsec(self, slit_arcsec: float) -> None:
        if slit_arcsec > 0:
            self._slit_arcsec = float(slit_arcsec)

    # @args: scan_log, scan_stats, session_meta - the three ADR-018 paths
    # @return: none
    def set_log_paths(self, scan_log: Path | None = None,
                      scan_stats: Path | None = None,
                      session_meta: Path | None = None) -> None:
        self._scan_log_path = scan_log
        self._scan_stats_path = scan_stats
        self._session_meta_path = session_meta

    # @args: chord_measure - a function() -> chord or None, for tests
    #        crossing_measure - a function() -> sky rate or None, for tests
    # @return: none
    def set_probe_functions(self,
                            chord_measure: Callable[[], float | None] | None = None,
                            crossing_measure: Callable[[], float | None] | None = None) -> None:
        self._chord_measure = chord_measure
        self._crossing_measure = crossing_measure

    # @return: the rows written so far, for the UI and the tests
    def log_rows(self) -> tuple[ScanLogRow, ...]:
        return tuple(self._log_rows)

    # @return: the cross-scan inconsistencies found so far
    def consistency_issues(self) -> tuple[ConsistencyIssue, ...]:
        return tuple(self._consistency)

    # @return: the current state (RUNNING, PAUSED, ABORTING)
    def state(self) -> ScanState:
        return self._state

    # ── frame port ───────────────────────────────────────────────────────────
    # @args: frame - a frame delivered on the capture thread
    # @return: none. Latches the frame and its stats, never blocks
    def _on_frame(self, frame: Frame) -> None:
        try:
            stats = frame.stats()
            mean = float(stats.mean)
            std = float(stats.std)
        except Exception:
            # A broken stats() must not kill the capture thread. The engine
            # will see the stale figures and its stall guard will act.
            return
        with self._lock:
            self._latest_frame = frame
            self._latest_mean = mean
            self._latest_std = std
            self._frame_count += 1
            self._last_frame_time = self._clock()

    # @args: none
    # @return: (frame, std, last frame time, count), a consistent snapshot
    def _snapshot(self) -> tuple[Frame | None, float, float | None, int]:
        with self._lock:
            return (self._latest_frame, self._latest_std,
                    self._last_frame_time, self._frame_count)

    # @args: timeout_s - how long to wait for a frame
    # @return: the frame, or None on timeout
    def _wait_frame(self, timeout_s: float = 3.0) -> Frame | None:
        start = self._clock()
        while self._clock() - start < timeout_s:
            frame, _std, last, _count = self._snapshot()
            if frame is not None and last is not None:
                return frame
            self._sleep(POLL_S)
        return None

    # ── plan ─────────────────────────────────────────────────────────────────
    # @args: config - what the observer asks for
    # @return: the computed plan
    # The RA limits are a snapshot of the mount at plan time; the scan moves by
    # rate and the real end is the adaptive stop. The plan is therefore a pure
    # function of the config plus the mount position and the optics, which is
    # what the UI shows before the observer accepts it.
    def plan(self, config: ScanConfig) -> ScanPlan:
        self._config = config
        # The analysis regions are computed, never stored in the ROI model
        # (ADR-010). Fill the reserved keys here if the UI has not done it, so
        # prepare() and the engine always have "left", "right" and "limb".
        for key, roi in analysis.analysis_regions(config.capture,
                                                  config.band).items():
            config.analysis.setdefault(key, roi)
        ra0, dec0 = self._mount.position()
        diameter = self._solar_diameter
        sky_rate = (config.rate_arcsec_s if config.rate_arcsec_s > 0
                    else self._pixel_scale * self._fps)

        if config.mode == ScanMode.MOSAIC:
            slit = self._slit_arcsec if self._slit_arcsec > 0 else diameter
            layout = mosaic.compute_mosaic_plan(
                dec0, diameter, slit,
                overlap=0.15,
                margin_arcsec=100.0,
                uncertainty_arcsec=0.0,
                rows=config.rows,
                row_step_arcsec=config.row_step_arcsec,
            )
            offsets = tuple((pos - dec0) * 3600.0
                            for pos in layout.positions_dec_deg)
        else:
            offsets = (0.0,)

        rows: list[ScanRow] = []
        total = 0.0
        for index, offset in enumerate(offsets):
            dec_row = dec0 + offset / 3600.0
            crossing = (diameter if config.mode == ScanMode.SIMPLE
                        else geometry.chord_arcsec(offset, self._slit_arcsec
                                                   if self._slit_arcsec > 0
                                                   else diameter, diameter))
            if crossing <= 0:
                crossing = diameter
            duration = 2.0 * max(0.0, config.padding_s) + crossing / sky_rate
            cosd = max(0.5, math.cos(math.radians(dec_row)))
            ra_span_hours = (crossing / cosd) / geometry.ARCSEC_PER_RA_HOUR
            ra_start = ra0
            ra_end = (ra0 - ra_span_hours) % 24.0
            rows.append(ScanRow(
                index=index,
                dec_offset_arcsec=offset,
                ra_start_hours=ra_start,
                ra_end_hours=ra_end,
                duration_s=duration,
            ))
            total += duration

        return ScanPlan(
            mode=config.mode,
            rate_arcsec_s=sky_rate,
            rows=tuple(rows),
            duration_s=total,
            frames_estimate=int(round(self._fps * total)),
            padding_s=max(0.0, config.padding_s),
            preload_s=max(0.0, config.preload_s),
        )

    # ── prepare ──────────────────────────────────────────────────────────────
    # @args: cb - progress callback
    # @return: the residual Dec error and the calibrated rate
    def prepare(self, cb: Callable[[PrepareStatus], None]) -> PrepareResult:
        if self._config is None:
            return PrepareResult(False, 0.0, 0.0, DecCenterMethod.AUTO,
                                 "no_plan")
        config = self._config
        # Without rate movement there is no scan at all. Say so once, with the
        # stable code the UI translates, instead of failing later in the sweep.
        try:
            if not self._mount.capabilities().supports_axis_rates:
                return PrepareResult(False, 0.0, 0.0, config.dec_center,
                                     "mount_no_rate")
        except Exception:
            return PrepareResult(False, 0.0, 0.0, config.dec_center,
                                 "mount_no_rate")
        cb(PrepareStatus(PreparePhase.FINE_CENTER, 0.0))

        # Fine centring: the disk fits the slit -> symmetry; if not -> chord.
        method = config.dec_center
        if method == DecCenterMethod.AUTO:
            slit = self._slit_arcsec if self._slit_arcsec > 0 else self._solar_diameter
            method = (DecCenterMethod.SYMMETRY
                      if slit >= self._solar_diameter
                      else DecCenterMethod.CHORD)

        if method == DecCenterMethod.SYMMETRY:
            centre = self._prepare_symmetry(cb)
        else:
            centre = self._prepare_chord(cb)
        if not centre.ok:
            return PrepareResult(False, centre.dec_offset_arcsec, 0.0,
                                 method, centre.reason_code or "low_contrast")

        # Rate: use the configured value or self-calibrate.
        if config.rate_arcsec_s > 0:
            rate = config.rate_arcsec_s
            self._rate_multiplier = 1.0
        else:
            rate = self._prepare_rate(cb)
            if rate <= 0:
                return PrepareResult(False, centre.dec_offset_arcsec, 0.0,
                                     method, "calibration_failed")
        cb(PrepareStatus(PreparePhase.CALIBRATE_RATE, 1.0,
                         centre.dec_offset_arcsec, rate))
        return PrepareResult(True, centre.dec_offset_arcsec, rate, method,
                             centre.reason_code)

    # @args: cb - progress callback
    # @return: the symmetry centring result
    def _prepare_symmetry(self, cb: Callable[[PrepareStatus], None]) -> centering.CenterResult:
        config = self._config
        assert config is not None
        band = config.analysis.get("limb", config.band)
        # The centroid offset is along the slit, so it uses the slit-axis
        # plate scale when the ROI step has measured one.
        slit_px = self._slit_arcsec_px or self._pixel_scale
        tolerance = 1.0

        # @args: dec_deg - where to move before measuring
        # @return: the measured Dec error, arcsec
        def probe(dec_deg: float) -> float | None:
            self._move_dec_to(dec_deg)
            frame = self._wait_frame(3.0)
            if frame is None:
                return None
            return centering.measure_symmetry_offset_arcsec(
                frame, band, slit_px, columns=64)

        # Progress is published once per correction; the pure loop owns the
        # convergence, so a callback wrapper is enough.
        start = self._mount.position()[1]
        iterations = [0]

        def wrapped(dec_deg: float) -> float | None:
            iterations[0] += 1
            cb(PrepareStatus(PreparePhase.FINE_CENTER,
                             min(0.99, iterations[0] / 8.0)))
            return probe(dec_deg)

        return centering.symmetry_center(wrapped, start, tolerance_arcsec=tolerance,
                                         max_iterations=8)

    # @args: cb - progress callback
    # @return: the chord centring result
    def _prepare_chord(self, cb: Callable[[PrepareStatus], None]) -> centering.CenterResult:
        config = self._config
        assert config is not None
        measure = self._chord_measure or self._measure_chord
        slit = self._slit_arcsec if self._slit_arcsec > 0 else self._solar_diameter
        cb(PrepareStatus(PreparePhase.FINE_CENTER, 0.1))
        result = centering.chord_center(
            measure, self._move_dec_relative, lambda: self._mount.position()[1],
            self._solar_diameter, slit,
            rewind=self._rewind_before_disk)
        cb(PrepareStatus(PreparePhase.FINE_CENTER, 1.0,
                         result.dec_offset_arcsec))
        return result

    # @args: cb - progress callback
    # @return: the calibrated sky rate, arcsec/s; 0 when it did not converge
    def _prepare_rate(self, cb: Callable[[PrepareStatus], None]) -> float:
        measure = self._crossing_measure or self._measure_crossing_rate
        cb(PrepareStatus(PreparePhase.CALIBRATE_RATE, 0.2))
        rate = measure()
        if rate is None or rate <= 0:
            return 0.0
        target = self._pixel_scale * self._fps
        per_unit = rate / PROBE_SPEED_MULTIPLIER
        if per_unit <= 0:
            return 0.0
        factor = calibration.calibration_factor(
            rate, PROBE_SPEED_MULTIPLIER, target, 1.0)
        if factor is None:
            return 0.0
        corrected = factor * per_unit
        if not calibration.rate_is_sane(corrected, target):
            return 0.0
        self._rate_multiplier = factor
        self._calibration_per_unit = per_unit
        self._calibration_factor = factor
        cb(PrepareStatus(PreparePhase.CALIBRATE_RATE, 1.0, None, target))
        return target

    # ── run ──────────────────────────────────────────────────────────────────
    # @args: plan - the plan to run
    #        cb - live progress callback
    #        recorder - where each row is recorded, or None for a dry run
    #        path_for_row - optional function(index) -> Path; the UI passes the
    #                       config/store.py namer. Without it the engine uses
    #                       a neutral local name the adapter may ignore.
    # @return: the outcome of one cycle (the UI repeats it cycles times)
    def run(self, plan: ScanPlan, cb: Callable[[ScanProgress], None],
            recorder: RowRecorder | None = None,
            path_for_row: Callable[[int], Path] | None = None) -> ScanResult:
        self._plan = plan
        self._abort = False
        self._pause = False
        self._resume.set()
        self._state = ScanState.RUNNING
        started = self._clock()
        total_written = 0
        total_dropped = 0
        completed = 0
        ser_paths: list[Path] = []
        last_dec_error = 0.0

        for row in plan.rows:
            if self._abort:
                break
            attempts = 1 + SCAN_RETRIES
            outcome: _RowOutcome | None = None
            for _attempt in range(attempts):
                if self._abort:
                    break
                try:
                    outcome = self._run_row(row, plan, cb, recorder,
                                            path_for_row)
                except DeviceError:
                    # The mount or the camera went away mid-row. Stop it and
                    # report a stable code; the SER already written is kept
                    # (ADR-014).
                    try:
                        self._mount.stop()
                    except Exception:
                        pass
                    return ScanResult(
                        status=ScanStatus.FAILED,
                        frames_written=total_written,
                        frames_dropped=total_dropped,
                        duration_s=self._clock() - started,
                        rate_arcsec_s=plan.rate_arcsec_s,
                        rows_completed=completed,
                        dec_error_arcsec=last_dec_error,
                        ser_paths=tuple(ser_paths),
                        reason_code="device_lost",
                    )
                except OSError:
                    try:
                        self._mount.stop()
                    except Exception:
                        pass
                    return ScanResult(
                        status=ScanStatus.FAILED,
                        frames_written=total_written,
                        frames_dropped=total_dropped,
                        duration_s=self._clock() - started,
                        rate_arcsec_s=plan.rate_arcsec_s,
                        rows_completed=completed,
                        dec_error_arcsec=last_dec_error,
                        ser_paths=tuple(ser_paths),
                        reason_code="disk_full",
                    )
                if outcome.ok:
                    break
                if outcome.status == ScanStatus.ABORTED:
                    break
            if outcome is None:
                break
            total_written += outcome.counters.frames_written
            total_dropped += (outcome.counters.frames_dropped_queue
                              + outcome.counters.frames_dropped_sdk)
            last_dec_error = outcome.dec_error_arcsec
            if outcome.ser_path is not None:
                ser_paths.append(outcome.ser_path)
            if outcome.ok:
                completed += 1
            else:
                # A failed row aborts the cycle: the SERs already written are
                # preserved (ADR-014).
                self._mount.stop()
                self._write_meta(outcome.counters, plan)
                return ScanResult(
                    status=outcome.status,
                    frames_written=total_written,
                    frames_dropped=total_dropped,
                    duration_s=self._clock() - started,
                    rate_arcsec_s=plan.rate_arcsec_s,
                    rows_completed=completed,
                    dec_error_arcsec=last_dec_error,
                    ser_paths=tuple(ser_paths),
                    reason_code=outcome.reason_code,
                )

        status = ScanStatus.ABORTED if self._abort else ScanStatus.COMPLETED
        if not self._abort:
            self._state = ScanState.RUNNING
        self._write_meta(RowCounters(), plan)
        return ScanResult(
            status=status,
            frames_written=total_written,
            frames_dropped=total_dropped,
            duration_s=self._clock() - started,
            rate_arcsec_s=plan.rate_arcsec_s,
            rows_completed=completed,
            dec_error_arcsec=last_dec_error,
            ser_paths=tuple(ser_paths),
            reason_code="aborted" if self._abort else "",
        )

    # @args: row - one row of the plan; plan - the whole plan
    #        cb - progress callback; recorder - the row port
    #        path_for_row - optional path namer
    # @return: the internal outcome
    def _run_row(self, row: ScanRow, plan: ScanPlan,
                 cb: Callable[[ScanProgress], None],
                 recorder: RowRecorder | None,
                 path_for_row: Callable[[int], Path] | None) -> _RowOutcome:
        _ra0, dec0 = self._mount.position()
        target_dec = dec0 + row.dec_offset_arcsec / 3600.0
        self._move_dec_to(target_dec)
        _ra, dec_row = self._mount.position()
        cosd = max(0.5, math.cos(math.radians(dec_row)))
        sky_rate = plan.rate_arcsec_s if plan.rate_arcsec_s > 0 else self._pixel_scale * self._fps
        # The scan sweeps towards decreasing RA; the coordinate rate is the sky
        # rate divided by cos(Dec).
        ra_rate = sky_rate / cosd
        scan_rate = -ra_rate
        path = (path_for_row(row.index) if path_for_row is not None
                else Path(f"scan_{row.index:02d}.ser"))

        # Padding: record background on both sides. It uses the same rate as
        # the scan so the padding is symmetric in sky angle, which is what the
        # prototype fixed after a faster backup clipped the trailing limb.
        if plan.padding_s > 0:
            self._mount.move_axis(Axis.RA, -scan_rate)
            if not self._sleep_abortable(plan.padding_s):
                self._mount.stop()
                return self._aborted_outcome()
            self._mount.stop()

        # RA preload: take up the backlash left by the reverse padding. Cap it
        # at half the padding so the leading padding is never eaten.
        preload = min(plan.preload_s, 0.5 * plan.padding_s)
        if preload > 0:
            self._mount.move_axis(Axis.RA, scan_rate)
            if not self._sleep_abortable(preload):
                self._mount.stop()
                return self._aborted_outcome()
            self._mount.stop()

        if recorder is not None:
            recorder.start_row(path)
        detector = LimbDetector()
        _frame, std0, _last, _count = self._snapshot()
        if std0 > 0:
            detector.set_dark(std0)

        start = self._clock()
        paused_total = 0.0
        last_progress = start
        frames_written_base = self._snapshot()[3]
        problem = ""
        # The row's real start, after the padding and the preload: the log's
        # RA and Dec start figures are the ones the capture actually saw, not
        # the plan's snapshot from before the manoeuvre.
        ra_move_start, dec_move_start = self._mount.position()
        self._mount.move_axis(Axis.RA, scan_rate)
        while True:
            if self._abort:
                problem = "aborted"
                break
            now = self._clock()
            if self._pause:
                self._mount.stop()
                self._state = ScanState.PAUSED
                pause_start = self._clock()
                cb(self._progress(ScanState.PAUSED, row.index, plan,
                                  now - start,
                                  max(0, self._snapshot()[3] - frames_written_base),
                                  dec_row, target_dec))
                while not self._resume.is_set() and not self._abort:
                    self._sleep(POLL_S)
                paused_total += self._clock() - pause_start
                self._state = ScanState.RUNNING
                if self._abort:
                    problem = "aborted"
                    break
                self._mount.move_axis(Axis.RA, scan_rate)
            elapsed = now - start - paused_total
            if elapsed >= row.duration_s:
                break

            self._sleep(POLL_S)
            _frame, std, last_frame_time, count = self._snapshot()
            if last_frame_time is not None and (self._clock() - last_frame_time) > STALL_TIMEOUT_S:
                problem = "stalled"
                break
            state = detector.update(std)
            if (self._config is not None and self._config.adaptive_stop
                    and state == LimbState.TRAILING):
                # The Sun has left the slit: the normal end of a successful
                # row, not a failure (DESIGN.md 7).
                break
            if self._clock() - last_progress >= 0.2:
                last_progress = self._clock()
                cb(self._progress(ScanState.RUNNING, row.index, plan,
                                  elapsed,
                                  max(0, count - frames_written_base),
                                  dec_row, target_dec))

        self._mount.stop()
        end = self._clock()
        move_seconds = end - start - paused_total
        counters = recorder.stop_row() if recorder is not None else RowCounters()
        _frame, _std, _last, frames_end = self._snapshot()
        if recorder is None:
            # A dry run still reports the frames it saw, so the UI can show a
            # rate and the observer can judge the plan.
            counters = RowCounters(
                frames_written=max(0, frames_end - frames_written_base))
        elapsed = max(1e-9, move_seconds)
        actual_fps = counters.frames_written / elapsed
        actual_xy = (self._pixel_scale * actual_fps / sky_rate
                     if sky_rate > 0 else 0.0)
        expected = row.duration_s * self._fps
        short_pct = (max(0.0, (expected - counters.frames_written) / expected) * 100.0
                     if expected > 0 else 0.0)
        dec_error = (self._mount.position()[1] - target_dec) * 3600.0
        extent = self._measure_slit_extent()
        consistency = check_consistency(actual_xy, extent,
                                        self._reference_xy,
                                        self._reference_extent)
        if self._reference_xy is None and actual_xy > 0:
            self._reference_xy = actual_xy
        if self._reference_extent is None and extent:
            self._reference_extent = extent
        self._consistency.extend(consistency)
        consistency_text = ";".join(issue.field for issue in consistency)

        log_row = ScanLogRow(
            label=f"scan{row.index:02d}",
            utc=utc_stamp(datetime.now(timezone.utc)),
            local=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            dec_start_deg=dec_move_start,
            dec_end_deg=self._mount.position()[1],
            dec_offset_measured_arcsec=dec_error,
            ra_start_h=ra_move_start,
            ra_end_h=self._mount.position()[0],
            displacement_arcsec=abs(geometry.ra_diff_arcsec(
                self._mount.position()[0], ra_move_start)),
            fps_used=self._fps,
            scan_multiplier=self._rate_multiplier,
            scan_speed_arcsec_s=sky_rate,
            cos_dec=cosd,
            calibration_factor=self._calibration_factor,
            padded_seconds=plan.padding_s,
            scan_duration_s=row.duration_s,
            frames=counters.frames_written,
            frames_expected=expected,
            frames_short_pct=short_pct,
            move_seconds=move_seconds,
            actual_fps=actual_fps,
            actual_xy=actual_xy,
            slit_extent_px=extent,
            problem=problem,
            consistency=consistency_text,
            roi_capture=",".join(str(v) for v in self._config.capture) if self._config else "",
            roi_band=",".join(str(v) for v in self._config.band) if self._config else "",
            tilt_deg=self._config.tilt_deg if self._config else None,
            tilt_px=self._config.tilt_px if self._config else None,
            frames_dropped_queue=counters.frames_dropped_queue,
            frames_dropped_sdk=counters.frames_dropped_sdk,
            sequence_gaps=counters.sequence_gaps,
            queue_high_water_mb=counters.queue_high_water_mb,
            app_version=self._app_version,
            counters=counters,
        )
        self._log_rows.append(log_row)
        self._persist_logs()

        if problem:
            status = (ScanStatus.ABORTED if problem == "aborted"
                      else ScanStatus.FAILED)
            return _RowOutcome(False, status, counters, move_seconds,
                               dec_error, problem, path if recorder else None)
        cb(self._progress(ScanState.RUNNING, row.index, plan,
                          move_seconds,
                          max(0, frames_end - frames_written_base),
                          dec_row, target_dec))
        return _RowOutcome(True, ScanStatus.COMPLETED, counters, move_seconds,
                           dec_error, "", path if recorder else None)

    # @args: state - RUNNING or PAUSED; index - row index; plan - the plan
    #        elapsed - seconds since the row started; frames - frames seen
    #        dec_row - the row Dec; target_dec - the intended centre
    # @return: a ScanProgress record
    def _progress(self, state: ScanState, index: int, plan: ScanPlan,
                  elapsed: float, frames: int, dec_row: float,
                  target_dec: float) -> ScanProgress:
        ra, dec = self._mount.position()
        progress = (min(1.0, elapsed / plan.duration_s)
                    if plan.duration_s > 0 else 0.0)
        return ScanProgress(
            state=state,
            row=index,
            progress=progress,
            frames_written=frames,
            frames_dropped=0,
            ra_hours=ra,
            dec_deg=dec,
            dec_error_arcsec=(dec - target_dec) * 3600.0,
            elapsed_s=elapsed,
        )

    # ── pause, resume, abort ─────────────────────────────────────────────────
    # @args: none. Stops the mount and holds the sweep
    def pause(self) -> None:
        self._pause = True
        self._resume.clear()
        try:
            self._mount.stop()
        except Exception:
            pass

    # @args: none. Continues a paused sweep
    def resume(self) -> None:
        self._pause = False
        self._resume.set()

    # @args: none. Stops the mount and reports ABORTED, keeping the files
    def abort(self) -> None:
        self._abort = True
        self._state = ScanState.ABORTING
        self._resume.set()
        try:
            self._mount.stop()
        except Exception:
            pass

    # @args: none
    # @return: an ABORTED outcome with an empty counter
    def _aborted_outcome(self) -> _RowOutcome:
        return _RowOutcome(False, ScanStatus.ABORTED, RowCounters(), 0.0,
                           0.0, "aborted", None)

    # ── small helpers ────────────────────────────────────────────────────────
    # @args: seconds - how long to wait
    # @return: False when the scan was aborted during the wait
    def _sleep_abortable(self, seconds: float) -> bool:
        end = self._clock() + max(0.0, seconds)
        while self._clock() < end:
            if self._abort:
                return False
            self._sleep(min(POLL_S, max(0.0, end - self._clock())))
        return not self._abort

    # @args: target_dec - absolute Dec, degrees
    # @return: none. Moves Dec closed-loop with a +Dec final approach
    def _move_dec_to(self, target_dec: float) -> None:
        _ra, current = self._mount.position()
        sequence = mosaic.backlash_approach(current, target_dec)
        for step in sequence:
            delta = (step - self._mount.position()[1]) * 3600.0
            if abs(delta) > 0.5:
                self._move_dec_relative(delta)

    # @args: delta_arcsec - relative Dec move
    # @return: none. Bounded move; stops at the target or after a timeout
    def _move_dec_relative(self, delta_arcsec: float) -> None:
        if abs(delta_arcsec) < 0.5:
            return
        _ra, start = self._mount.position()
        target = start + delta_arcsec / 3600.0
        direction = 1.0 if delta_arcsec > 0 else -1.0
        # A centring nudge is a closed loop: a faster rate saves time, but the
        # 30 ms poll means the overshoot is roughly rate*0.03, so the minimum
        # stays at 5"/s and the maximum at 150"/s. The prototype used 3x
        # sidereal (45"/s) with the same polling idea.
        rate = min(max(5.0, abs(delta_arcsec) * 2.0),
                   10.0 * SIDEREAL_ARCSEC_S)
        self._mount.move_axis(Axis.DEC, direction * rate)
        start_time = self._clock()
        timeout = abs(delta_arcsec) / rate * 1.5 + 1.0
        while self._clock() - start_time < timeout:
            if self._abort:
                break
            current = self._mount.position()[1]
            if (current - target) * direction >= 0:
                break
            self._sleep(0.03)
        self._mount.stop()
        self._sleep(0.1)

    # @args: none
    # @return: the illuminated extent along the slit in the latest frame, px
    # This is the prototype's measure_slit_extent_px: a coarse band profile of
    # the live frame, enough to flag a slit that missed the disk and to compare
    # one row with the next (the consistency check).
    def _measure_slit_extent(self) -> float | None:
        frame = self._snapshot()[0]
        if frame is None or self._config is None:
            return None
        band = self._config.analysis.get("limb", self._config.band)
        try:
            means = analysis.column_means(frame, band, SLIT_EXTENT_BANDS)
            band_px = max(1, band[2] // SLIT_EXTENT_BANDS)
            extent = analysis.measure_slit_extent_px(means, band_px)
        except Exception:
            return None
        return extent or None

    # @args: none
    # @return: none. Slew backwards in RA by more than a disk diameter
    # find_solar_limb and the chord sweep search forward only, so a failed
    # probe can leave the mount past the trailing limb. The prototype's
    # rewind_before_disk restores the precondition; the RA coordinate span
    # grows as 1/cos(Dec) because the mount moves in coordinates.
    def _rewind_before_disk(self) -> None:
        _ra, dec = self._mount.position()
        span = (self._solar_diameter + REWIND_MARGIN_ARCSEC) / max(
            0.5, math.cos(math.radians(dec)))
        rate = RETURN_MULTIPLIER * SIDEREAL_ARCSEC_S
        self._mount.move_axis(Axis.RA, rate)
        self._sleep_abortable(span / rate)
        self._mount.stop()
        self._sleep(0.2)

    # @args: rate - probe rate, arcsec/s; the backup uses the opposite sign
    # @return: the dark baseline std, or None when the backup timed out
    # A chord or a crossing search starts outside the disk. If the slit is
    # already on it, backing off first is what makes the rest of the routine
    # simple: it only has to find a rising edge. The prototype does the same
    # in find_solar_limb before sampling the dark baseline.
    def _ensure_off_disk(self, rate: float) -> float | None:
        _frame, std, _last, _count = self._snapshot()
        if std <= ON_DISK_STDDEV:
            return std
        self._mount.move_axis(Axis.RA, rate)
        start = self._clock()
        while self._clock() - start < 40.0:
            if self._abort:
                break
            self._sleep(POLL_S)
            std = self._snapshot()[1]
            if std < LIMB_STDDEV_MIN:
                self._mount.stop()
                self._sleep(0.2)
                return self._snapshot()[1]
        self._mount.stop()
        return None

    # @args: none
    # @return: the on-disk chord at the current Dec, arcsec, or None
    # A simplified port of the prototype's measure_chord: sweep RA at the probe
    # speed, watch the stddev, time the on-disk interval, convert the RA span
    # to sky with cos(Dec), and rewind. The tests inject their own function.
    def _measure_chord(self) -> float | None:
        detector = LimbDetector()
        frame = self._wait_frame(2.0)
        if frame is None:
            return None
        rate = PROBE_SPEED_MULTIPLIER * SIDEREAL_ARCSEC_S
        dark = self._ensure_off_disk(rate)
        if dark is None:
            return None
        _ra0, dec0 = self._mount.position()
        detector.set_dark(dark)
        self._mount.move_axis(Axis.RA, -rate)
        start = self._clock()
        ra_start = self._mount.position()[0]
        ra_end: float | None = None
        on_disk = False
        while self._clock() - start < 120.0:
            if self._abort:
                break
            self._sleep(POLL_S)
            state = detector.update(self._snapshot()[1])
            if state == LimbState.ON_DISK:
                on_disk = True
            elif state == LimbState.TRAILING and on_disk:
                ra_end = self._mount.position()[0]
                break
        self._mount.stop()
        if ra_end is None:
            return None
        span = abs(geometry.ra_diff_arcsec(ra_end, ra_start))
        return span * math.cos(math.radians(dec0))

    # @args: none
    # @return: the sky rate at the probe speed, arcsec/s, or None
    # Same traversal as _measure_chord, but it returns the rate from the
    # elapsed time instead of the chord. The prototype times the crossing and
    # takes t1 when the mount stops, not after the settle sleep, so the rate is
    # not biased low.
    def _measure_crossing_rate(self) -> float | None:
        detector = LimbDetector()
        frame = self._wait_frame(2.0)
        if frame is None:
            return None
        rate = PROBE_SPEED_MULTIPLIER * SIDEREAL_ARCSEC_S
        dark = self._ensure_off_disk(rate)
        if dark is None:
            return None
        _ra0, dec0 = self._mount.position()
        detector.set_dark(dark)
        self._mount.move_axis(Axis.RA, -rate)
        start = self._clock()
        ra_start = self._mount.position()[0]
        ra_end: float | None = None
        stop_time: float | None = None
        on_disk = False
        while self._clock() - start < 120.0:
            if self._abort:
                break
            self._sleep(POLL_S)
            state = detector.update(self._snapshot()[1])
            if state == LimbState.ON_DISK:
                on_disk = True
            elif state == LimbState.TRAILING and on_disk:
                stop_time = self._clock()
                ra_end = self._mount.position()[0]
                break
        self._mount.stop()
        if ra_end is None or stop_time is None:
            return None
        elapsed = stop_time - start
        if elapsed <= 0:
            return None
        span = abs(geometry.ra_diff_arcsec(ra_end, ra_start))
        return span * math.cos(math.radians(dec0)) / elapsed

    # @args: counters - the counters of the last row; plan - the plan
    # @return: none. Rewrites scan_log.csv and appends scan_stats.jsonl
    def _persist_logs(self) -> None:
        # Logging is best effort: a full disk must not abort a scan whose SER
        # is already being written (ADR-014). The counters still reach the
        # caller through ScanResult.
        try:
            if self._log_rows:
                if self._scan_log_path is not None:
                    write_scan_log(self._log_rows, self._scan_log_path)
                if self._scan_stats_path is not None:
                    write_scan_stats(self._log_rows[-1], self._scan_stats_path)
        except OSError:
            pass

    # @args: counters - the capture accounting; plan - the plan
    # @return: none. Writes session_meta.json when a path was set
    def _write_meta(self, counters: RowCounters, plan: ScanPlan) -> None:
        if self._session_meta_path is None or self._config is None:
            return
        solar = self._solar_position_value
        optics = {
            "focal_length_mm": self._focal_length_mm,
            "pixel_size_um": self._pixel_size_um,
            "pixel_scale_arcsec_px": self._pixel_scale,
            "solar_diameter_arcsec": self._solar_diameter,
            "solar_diameter_source": "ephemeris" if solar is not None else "fallback",
            "sidereal_arcsec_s": SIDEREAL_ARCSEC_S,
            "ra_hours": solar.ra_hours if solar is not None else None,
            "dec_deg": solar.dec_deg if solar is not None else None,
            "hour_angle_deg": solar.hour_angle_deg if solar is not None else None,
        }
        crossing = (plan.rows[0].duration_s - 2.0 * plan.padding_s
                    if plan.rows else None)
        meta = build_session_meta(
            self._config, plan, optics, self._app_version,
            counters=counters,
            fps=self._fps,
            scan_multiplier=self._rate_multiplier,
            crossing_time_s=crossing,
            calibration={
                "applied": self._calibration_per_unit is not None,
                "factor": self._calibration_factor,
                "measured_per_unit": self._calibration_per_unit,
            },
            slit={
                "length_mm": None,
                "image_scale_configured": 1.0,
                "image_scale_used": 1.0,
                "measured_extent_px": None,
                "measured_S_Y_arcsec_px": None,
                "effective_slit_arcsec": self._slit_arcsec or None,
            },
        )
        try:
            write_session_meta(meta, self._session_meta_path)
        except OSError:
            pass
