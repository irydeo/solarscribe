############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg contracts module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Contracts of the SHG layer (design/ARCHITECTURE.md 2.3, ADR-012).
#
# shg holds the science: limb detection, scan-rate calibration, Dec centring,
# the scan and the mosaic, the solar polar alignment and the tilt measurement.
# It imports devices and nothing else from the application: no Qt (the engine
# runs headless and is tested with the simulators, ADR-005) and no capture
# (they are siblings, ARCHITECTURE 1).
#
# How shg gets what it needs without importing capture: dependency inversion.
# It declares the two ports it uses, and the UI wires them to the capture engine
# (ARCHITECTURE 2.3):
#   - FrameSource: where the live frames come from. CaptureEngine satisfies it
#     structurally, because both declare on_frame(cb).
#   - RowRecorder: where each mosaic row is recorded, with RowCounters as shg's
#     own accounting type. The UI passes a small adapter over
#     CaptureEngine.start_recording()/stop_recording()/counters().
# Construction is part of the contract: shg/engine.py exposes
# ScanEngineImpl(mount: Mount, frames: FrameSource), built once per session.
#
# shg also writes the three logs of ADR-018 (scan_log.csv, scan_stats.jsonl and
# session_meta.json), which is what the prototype did: it has the plan, the
# result and the ROI, and RowCounters gives it the capture side.
#
# Units, fixed once because a mix-up here moves the telescope the wrong way:
# RA in hours, Dec in degrees (the mount convention), rates and offsets in
# arcseconds per second and arcseconds, times in seconds.
#
# Reason codes: PrepareResult, ScanResult and TiltResult carry a stable
# snake_case `reason_code` instead of a sentence. The UI translates it with
# self.tr() (ADR-016) and never shows a raw error (ADR-014). The MVP set is
# "no_limb", "sun_lost", "calibration_failed", "mount_no_rate", "disk_full",
# "device_lost", "stalled", "aborted", "no_edge", "low_contrast".

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from solarscribe.devices.abc import ROI, Frame

__all__ = [
    "ANALYSIS_KEYS",
    "CenteringResult",
    "CenteringStatus",
    "DecCenterMethod",
    "FrameSource",
    "PolarAlignmentAssistant",
    "PolarProgress",
    "PolarResult",
    "PolarSample",
    "PreparePhase",
    "PrepareResult",
    "PrepareStatus",
    "RowCounters",
    "RowRecorder",
    "ScanConfig",
    "ScanEngine",
    "ScanMode",
    "ScanPlan",
    "ScanProgress",
    "ScanResult",
    "ScanRow",
    "ScanState",
    "ScanStatus",
    "SunCenteringService",
    "TiltMeter",
    "TiltResult",
    "analysis_regions",
]


class ScanMode(Enum):
    # A single sweep or a multi-row mosaic (DESIGN.md 7).
    SIMPLE = "simple"
    MOSAIC = "mosaic"


class DecCenterMethod(Enum):
    # How the fine Dec centring is done (ADR-006). AUTO is the default: symmetry
    # when the disk fits along the slit, chord when it does not. The UI shows
    # which one ran, because the chord method needs a short sweep and the
    # symmetry one does not.
    AUTO = "auto"
    SYMMETRY = "symmetry"
    CHORD = "chord"


class PreparePhase(Enum):
    # The two halves of the scan preparation, which lives inside the Scanning
    # step, not in a step of its own (ADR-011).
    FINE_CENTER = "fine_center"           # ADR-006 fine: symmetry or chord
    CALIBRATE_RATE = "calibrate_rate"     # scan-rate autocalibration


class ScanState(Enum):
    # What the scan is doing right now. PAUSED is the honest state of "the Sun
    # left the slit": the engine holds, warns and waits for the observer to
    # recentre before continuing (DESIGN.md 7).
    RUNNING = "running"
    PAUSED = "paused"
    ABORTING = "aborting"


class ScanStatus(Enum):
    # How a scan ended. ABORTED means stopped on purpose or by an anomaly with
    # the SER preserved (ADR-014); FAILED means it could not run at all.
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(frozen=True)
class ScanRow:
    # One row of the plan: one sweep of the slit across the disk, one SER.
    #
    # The scan moves by rate (Mount.move_axis), not by slew: the RA limits are
    # the intended geometry for the overlay and the log, and the sweep ends when
    # the adaptive stop sees the Sun leave the slit.
    index: int
    dec_offset_arcsec: float      # offset from the centred Dec, for the mosaic
    ra_start_hours: float
    ra_end_hours: float
    duration_s: float


@dataclass(frozen=True)
class ScanConfig:
    # What the observer asks for, read from the INI [scan] section and from the
    # ROI step. Everything the engine needs is here, so plan() is a pure
    # function of it and can be tested without hardware.
    #
    # `capture` is the hardware ROI in SENSOR pixels (its width and height are
    # the frame dimensions the engine measures on) and `band` is the spectral
    # band in FRAME pixels. They arrive as plain rectangles because shg cannot
    # import capture's RoiModel: the UI copies them out of it.
    #
    # `analysis` keys are reserved: "left" and "right" are the halves used by
    # the Dec centring (ADR-006) and "limb" is the strip where the limb is
    # detected. shg computes them from `capture` and `band`; it subdivides
    # "limb" into columns internally, so the columns are not part of the
    # contract.
    capture: ROI
    band: ROI
    analysis: dict[str, ROI] = field(default_factory=dict)
    mode: ScanMode = ScanMode.SIMPLE
    cycles: int = 3               # scans per session (DESIGN.md 7). run() does
                                  # ONE cycle: the UI repeats it and can recentre
                                  # in between
    rate_arcsec_s: float = 0.0    # 0.0: calibrate it in prepare()
    dec_center: DecCenterMethod = DecCenterMethod.AUTO
    rows: int = 1                 # mosaic rows; 1 is a simple scan
    row_step_arcsec: float = 0.0  # 0.0: step one slit height between rows
    padding_s: float = 1.0        # frames kept before and after the crossing
    preload_s: float = 1.0        # RA preload: absorb the backlash before the
                                  # sweep starts recording
    adaptive_stop: bool = True    # stop when the Sun leaves the slit
    tilt_deg: float = 0.0         # measured tilt, to size the geometry (ADR-022)
    tilt_px: float = 0.0


@dataclass(frozen=True)
class ScanPlan:
    # What will happen, computed by plan(). The UI shows it before running
    # (duration, rows, rate) so the observer knows what the engine intends and
    # can refuse it: a plan nobody can read is a plan nobody can check.
    mode: ScanMode
    rate_arcsec_s: float
    rows: tuple[ScanRow, ...]
    duration_s: float
    frames_estimate: int      # rate x duration x fps: what the disk must absorb
    padding_s: float
    preload_s: float


@dataclass(frozen=True)
class PrepareStatus:
    # Progress of the preparation, published through the callback so the step can
    # show a live indicator in plain language (ADR-011).
    phase: PreparePhase
    progress: float                           # 0.0 to 1.0 inside the phase
    dec_offset_arcsec: float | None = None    # current Dec error vs the slit
    rate_arcsec_s: float | None = None        # calibrated rate, once known


@dataclass(frozen=True)
class PrepareResult:
    # Outcome of the preparation: fine centring plus rate calibration.
    ok: bool
    dec_offset_arcsec: float      # residual Dec error; the UI says what it means
    rate_arcsec_s: float          # 0.0 when the calibration did not converge
    method: DecCenterMethod       # which fine method actually ran
    reason_code: str = ""         # "" when ok


@dataclass(frozen=True)
class ScanProgress:
    # Progress of a running scan, published through the callback. It feeds the
    # live visualisation (captured strip, slit line, percentage, ADR-020) and the
    # status bar, so it carries both the geometry and the accounting.
    state: ScanState
    row: int
    progress: float               # 0.0 to 1.0 of the whole scan
    frames_written: int
    frames_dropped: int
    ra_hours: float               # where the mount is now
    dec_deg: float
    dec_error_arcsec: float       # Sun vs slit centre: the number that tells the
                                  # observer whether the scan is still on the disk
    elapsed_s: float


@dataclass(frozen=True)
class ScanResult:
    # Outcome of one cycle. One SER per row, so the paths are a tuple; the
    # session summary and session_meta.json are built from this (ADR-018).
    status: ScanStatus
    frames_written: int
    frames_dropped: int
    duration_s: float
    rate_arcsec_s: float
    rows_completed: int
    dec_error_arcsec: float
    ser_paths: tuple[Path, ...] = ()
    reason_code: str = ""         # "" when completed


@runtime_checkable
class FrameSource(Protocol):
    # Port: where the engine gets live frames. Declared here so shg never imports
    # capture; CaptureEngine satisfies it as it stands.
    #
    # @args: cb - called on the capture thread with each frame. The engine's own
    #              consumer must stay inside the frame budget (8.3 ms at 120 fps)
    #              and never block, or the stream loses frames (ADR-013)
    def on_frame(self, cb: Callable[[Frame], None]) -> None: ...


@dataclass(frozen=True)
class RowCounters:
    # Accounting of one recorded row, in shg's own words.
    #
    # Declared here (and not read from capture's WriterCounters) so shg never
    # imports its sibling: the UI's adapter copies the numbers out of
    # WriterCounters and StreamCounters. These five figures are what
    # session_meta.json and scan_stats.jsonl need from the capture side
    # (ADR-013, ADR-018), and they are the three drop sites of ADR-013 plus the
    # queue depth.
    frames_written: int = 0
    frames_dropped_queue: int = 0
    frames_dropped_sdk: int = 0     # cumulative, from Camera.dropped_frames()
    sequence_gaps: int = 0
    queue_high_water_mb: float = 0.0


@runtime_checkable
class RowRecorder(Protocol):
    # Port: where each row is recorded. Declared here for the same reason, and
    # with shg's own value type, so the adapter the UI writes is a few lines and
    # imports nothing from capture.
    #
    # @args: path - the SER file for this row, named by config/store.py
    def start_row(self, path: Path) -> None: ...

    # @return: the counters of the row that just closed
    def stop_row(self) -> RowCounters: ...


@runtime_checkable
class ScanEngine(Protocol):
    # Plan, prepare, scan.
    #
    # The engine holds no Qt and no driver: it moves the mount through the Mount
    # contract and measures the frames it receives through FrameSource. Built as
    # ScanEngineImpl(mount, frames) in shg/engine.py.

    # @args: config - what the observer asks for
    # @return: the computed plan; a pure function of config, so it is testable
    #          without hardware
    def plan(self, config: ScanConfig) -> ScanPlan: ...

    # @args: cb - progress of the fine centring and of the rate calibration
    # @return: the residual Dec error and the calibrated rate
    def prepare(self, cb: Callable[[PrepareStatus], None]) -> PrepareResult: ...

    # @args: plan - what to run; cb - live progress; recorder - where each row is
    #              recorded, or None for a dry run with no files (DESIGN.md 14)
    # @return: the outcome of ONE cycle; the UI repeats it `config.cycles` times
    def run(self, plan: ScanPlan, cb: Callable[[ScanProgress], None],
            recorder: RowRecorder | None = None) -> ScanResult: ...

    # @args: none. Holds the sweep and the mount where they are. The observer
    #              recentres (telescope panel or centring) before resuming
    def pause(self) -> None: ...

    # @args: none. Continues a paused sweep
    def resume(self) -> None: ...

    # @args: none. Stops the mount, closes the SER and reports ABORTED: the
    #              frames already written are preserved (ADR-014)
    def abort(self) -> None: ...


@dataclass(frozen=True)
class TiltResult:
    # A tilt measurement of the spectral line or of the slit edge (ADR-022).
    #
    # edge_std_px is the straightness of the fitted edge, the prototype's
    # edge_flat: a large value means the edge is not a line, so the tilt figure
    # is not trustworthy and the UI must say so instead of showing a number.
    ok: bool
    tilt_deg: float = 0.0
    tilt_px: float = 0.0          # drift across the ROI width, in pixels
    edge_std_px: float = 0.0
    reason_code: str = ""         # "" when ok


@runtime_checkable
class TiltMeter(Protocol):
    # Port: the tilt measurement. It is shg's science (ADR-022), and the ROI step
    # calls it and writes the numbers into capture's RoiModel, so the maths and
    # the model stay in their own layers.
    #
    # @args: frame - a live frame; band - the spectral band in FRAME pixels
    # @return: the fitted tilt; ok=False with a reason when no edge fits
    def measure(self, frame: Frame, band: ROI) -> TiltResult: ...


# ── Pending contracts of ARCHITECTURE 2.3 ────────────────────────────────────
# The three contracts below were listed as pending before the UI could build
# steps 1 and 2. They follow the same rule as the rest of this module: the shape
# is here, the science is in the shg modules that implement it, and nothing
# returns a sentence: the UI composes the text around stable reason codes
# (ADR-014, ADR-016).

# The analysis regions are keyed by these reserved names. "left" and "right"
# are the two halves of the slit axis used by the Dec centring (ADR-006);
# "limb" is the strip where the limb is detected. shg subdivides "limb" into
# columns internally, so the columns are not part of the contract.
ANALYSIS_KEYS: tuple[str, ...] = ("left", "right", "limb")


# @args: capture - the hardware ROI in SENSOR pixels; its width and height are
#                  the dimensions of the delivered frame
#        band - the spectral band in FRAME pixels, (0, 0) at the frame corner
# @return: the analysis regions in FRAME pixels, keyed by ANALYSIS_KEYS
# The implementation lives in shg/analysis.py (analysis_regions): a contract
# module declares types and never computes (ADR-023). The UI calls the
# implementation to draw the regions and to build ScanConfig.analysis.
def analysis_regions(capture: ROI, band: ROI) -> dict[str, ROI]: ...


@dataclass(frozen=True)
class CenteringStatus:
    # Progress of the Find-the-Sun centring, published through the callback so
    # the step can show a live indicator in plain language (ADR-011).
    phase: str                        # "coarse" or "fine"
    progress: float                   # 0.0 to 1.0 of the whole centring
    dec_offset_arcsec: float | None = None   # current estimate; None until known
    score: float | None = None        # coarse score (high percentile), if any


@dataclass(frozen=True)
class CenteringResult:
    # Outcome of the centring. dead_zone_arcsec states the honest limit of the
    # method that ran: the chord inside the slit cannot resolve |offset| below
    # slit/2 (L = 2*sqrt(R^2 - q^2) has zero slope at q = 0), and the coarse
    # histogram is flat there too. The UI must show this figure, not hide it.
    ok: bool
    dec_offset_arcsec: float          # residual Dec error after centring
    method: DecCenterMethod           # which method actually ran
    reason_code: str = ""             # "" when ok
    dead_zone_arcsec: float = 0.0


@runtime_checkable
class SunCenteringService(Protocol):
    # The Find-the-Sun service: coarse by histogram/percentile, fine by
    # symmetry or chord (ADR-006). It moves the mount through the Mount contract
    # and measures the frames it receives through FrameSource, so it stays
    # headless and testable without hardware (ADR-005).

    # @args: cb - progress callback, called from the worker thread
    # @return: the residual Dec error, the method used and the dead zone
    def center(self, cb: Callable[[CenteringStatus], None]) -> CenteringResult: ...


@dataclass(frozen=True)
class PolarSample:
    # One Dec sample of the Sun for the polar alignment (ADR-007).
    #
    # dec_deg is the measured Dec and dec_ephemeris_deg the value predicted by
    # the local ephemeris at the same instant (ADR-021). The assistant subtracts
    # the Sun's own motion before fitting the drift, which is up to ~0.4"/min.
    # hour_angle_deg is the Sun's local hour angle: the drift due to an azimuth
    # error is proportional to cos(H) and that due to an altitude error to
    # sin(H).
    time_s: float                     # seconds since the first sample
    hour_angle_deg: float             # local hour angle, degrees
    dec_deg: float                    # measured Dec, degrees
    dec_ephemeris_deg: float          # predicted Dec, degrees
    altitude_deg: float = 0.0         # for the refraction note and the UI
    azimuth_deg: float = 0.0


@dataclass(frozen=True)
class PolarProgress:
    # Progress of the assistant, published through the callback. `required` is
    # the number of samples the caller asked for; `progress` is samples/required.
    samples: int
    required: int
    progress: float
    hour_angle_deg: float
    elapsed_s: float


@dataclass(frozen=True)
class PolarResult:
    # Outcome of a drift fit.
    #
    # Sign convention, fixed here so the UI can say which way to turn a knob:
    # azimuth_error_arcsec > 0 means the mount's axis is EAST of the pole and
    # the azimuth knob must turn WEST; altitude_error_arcsec > 0 means the axis
    # is TOO HIGH and the altitude knob must come DOWN. confirmation is True on
    # the second measurement when both errors are inside the tolerance.
    ok: bool
    azimuth_error_arcsec: float
    altitude_error_arcsec: float
    drift_rate_arcsec_min: float      # fitted Dec drift, for the log
    residual_arcsec: float            # RMS of the fit
    samples: int
    confirmation: bool = False
    reason_code: str = ""             # "" when there is nothing to warn about;
                                      # "geometry_limit" when the hour angles
                                      # cannot separate the two errors (the fit
                                      # is still the best estimate)


@runtime_checkable
class PolarAlignmentAssistant(Protocol):
    # Drift-based solar polar alignment (ADR-007). The caller feeds samples; the
    # assistant subtracts the ephemeris, fits the drift and asks for a second
    # confirmation measurement.

    # @args: sample - one measured Dec with its hour angle and ephemeris
    #        cb - optional progress callback
    # @return: the progress after this sample
    def add_sample(self, sample: PolarSample,
                   cb: Callable[[PolarProgress], None] | None = None) -> PolarProgress: ...

    # @return: the fit with the samples gathered so far
    def result(self) -> PolarResult: ...

    # @args: samples - the second measurement, taken after the correction; None
    #                  means use the samples already gathered
    #        cb - optional progress callback
    # @return: the confirmation fit; confirmation=True when inside tolerance
    def confirm(self, samples: Sequence[PolarSample] | None = None,
                cb: Callable[[PolarProgress], None] | None = None) -> PolarResult: ...
